# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free conditional ally-order prefetch lifecycle tests."""

from __future__ import annotations

import copy
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import model_config
from core.combat.ally_controller import (
    _ALLY_STANDING_ORDERS_SYSTEM_PROMPT,
    build_ally_directive_history_record,
    build_ally_menus,
    compile_ally_standing_orders,
    parse_ally_standing_orders_response,
    parse_ally_standing_orders_response_with_reason,
    validate_ally_plan,
)
from core.combat.ally_prefetch import (
    _reset_ally_prefetch_for_tests,
    ally_prefetch_batch_id,
    has_ally_prefetch_replan_submission,
    has_ally_prefetch_submission,
    invalidate_ally_prefetch,
    select_ally_prefetch_plan,
    submit_ally_prefetch,
)
from core.combat.enemy_batch_apply import is_ally_prefetch_enabled
from core.combat.tactical_prefetch import _reset_tactical_prefetch_for_tests
from core.combat.turn import (
    CombatNormalTurnInputs,
    InputPhaseGateResult,
    prepare_combat_normal_turn,
    should_consider_ally_prefetch_replan,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase
from utils import combat_latency_trace
from utils.llm_runtime import make_legacy_receipt_observer


ENCOUNTER_ID = "ally-prefetch-encounter"


def _encounter() -> dict:
    return {
        "encounterId": ENCOUNTER_ID,
        "combat_round": 1,
        "creatures": [
            {
                "name": "Serah",
                "type": "npc",
                "currentHitPoints": 12,
                "maxHitPoints": 12,
                "status": "alive",
                "attacksAndSpellcasting": [
                    {
                        "name": "Longbow",
                        "attackBonus": 4,
                        "damageDice": "1d8",
                        "damageBonus": 2,
                        "damageType": "piercing",
                        "attackType": "ranged",
                    },
                    {
                        "name": "Dagger",
                        "attackBonus": 3,
                        "damageDice": "1d4",
                        "damageBonus": 1,
                        "damageType": "piercing",
                        "attackType": "melee",
                    },
                ],
            },
            {
                "name": "Goblin",
                "type": "enemy",
                "currentHitPoints": 8,
                "maxHitPoints": 8,
                "status": "alive",
            },
            {
                "name": "Hobgoblin",
                "type": "enemy",
                "currentHitPoints": 12,
                "maxHitPoints": 12,
                "status": "alive",
            },
            {
                "name": "Acheron",
                "type": "player",
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            },
        ],
    }


def _menus(encounter: dict):
    batch_id = ally_prefetch_batch_id(ENCOUNTER_ID, encounter["combat_round"])
    return build_ally_menus(encounter, batch_id)


def _manager(phase="PC_PHASE"):
    return SimpleNamespace(combat_phase=phase)


def _enabled_flags():
    return (
        mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True),
        mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True),
        mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True),
    )


def _attack_orders(actor="Serah", target="Goblin", condition="always"):
    return {
        "actors": [{
            "actor": {"name": actor, "kind": "npc"},
            "clauses": [{
                "when": condition,
                "do": {
                    "kind": "attack",
                    "target": {"name": target, "kind": "enemy"},
                    "action": "Longbow",
                },
            }],
        }],
    }


def _cover_orders(actor="Serah", feature_id=None):
    action = {"kind": "take_cover"}
    if feature_id is not None:
        action["feature_id"] = feature_id
    return {
        "actors": [{
            "actor": {"name": actor, "kind": "npc"},
            "clauses": [{"when": "cover_available", "do": action}],
        }],
    }


class CombatAllyPrefetchTests(ProviderFreeTestCase):
    def setUp(self):
        _reset_ally_prefetch_for_tests()
        _reset_tactical_prefetch_for_tests()

    def tearDown(self):
        _reset_ally_prefetch_for_tests()
        _reset_tactical_prefetch_for_tests()
        super().tearDown()

    def test_standing_orders_prompt_closed_schema_example_parses(self):
        prompt = _ALLY_STANDING_ORDERS_SYSTEM_PROMPT
        for required in (
            "top-level keys are actors (required array) and optional intent",
            "Each actor row has exactly actor and clauses",
            "each with exactly when and do",
            "do must be an object",
            "target has exactly name (string) and kind (the string enemy)",
            "No additional fields are allowed at any level",
            "no markdown or code fences",
        ):
            self.assertIn(required, prompt)
        example = {
            "actors": [{
                "actor": {"name": "<ally>", "kind": "npc"},
                "clauses": [{
                    "when": "always",
                    "do": {
                        "kind": "attack",
                        "target": {"name": "<enemy>", "kind": "enemy"},
                    },
                }],
            }],
            "intent": "<brief intent>",
        }
        self.assertEqual(parse_ally_standing_orders_response(example), example)

    def _submit(self, encounter, *, trigger="initial", history=None, executor=None,
                llm_call=None, manager=None):
        return submit_ally_prefetch(
            encounter,
            encounter_id=ENCOUNTER_ID,
            multi_pc_manager=manager or _manager(),
            active_encounter_id=ENCOUNTER_ID,
            history=history,
            llm_call=llm_call or (lambda *_args, **_kwargs: json.dumps(_attack_orders())),
            trigger=trigger,
            executor=executor,
        )

    def test_default_off_is_inert_and_prefetch_flag_dependency_fails_closed(self):
        encounter = _encounter()
        before = copy.deepcopy(encounter)
        jobs = []
        calls = []
        self.assertFalse(is_ally_prefetch_enabled())
        self.assertIsNone(self._submit(
            encounter,
            executor=jobs.append,
            llm_call=lambda *args, **kwargs: calls.append((args, kwargs)),
        ))
        self.assertEqual(encounter, before)
        self.assertEqual(jobs, [])
        self.assertEqual(calls, [])
        self.assertFalse(model_config.DETERMINISTIC_ENEMY_RESOLUTION_ENABLED)
        self.assertFalse(model_config.COMBAT_ALLY_CONTROLLER_ENABLED)
        self.assertFalse(model_config.COMBAT_ALLY_PREFETCH_ENABLED)

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", False), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True):
            self.assertFalse(is_ally_prefetch_enabled())
            self.assertIsNone(self._submit(encounter, executor=jobs.append))
        self.assertEqual(jobs, [])

    def test_pc_phase_start_submits_immutable_ally_projection(self):
        encounter = _encounter()
        original = copy.deepcopy(encounter)
        jobs = []
        router_calls = []
        response = json.dumps(_attack_orders())

        def router(task, messages, **kwargs):
            router_calls.append((task, copy.deepcopy(messages), kwargs))
            return response

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            submitted = self._submit(encounter, executor=jobs.append, llm_call=router)
            self.assertTrue(submitted.submitted)
            self.assertEqual(submitted.status, "submitted")
            self.assertEqual(len(jobs), 1)
            duplicate = self._submit(encounter, executor=jobs.append, llm_call=router)
            self.assertFalse(duplicate.submitted)
            self.assertEqual(duplicate.status, "already_submitted")
            self.assertEqual(len(jobs), 1)
            self.assertTrue(has_ally_prefetch_submission(
                ENCOUNTER_ID, ally_prefetch_batch_id(ENCOUNTER_ID, 1)
            ))
            jobs[0]()

        self.assertEqual(encounter, original)
        self.assertEqual(len(router_calls), 1)
        task, messages, kwargs = router_calls[0]
        self.assertEqual(task, "combat_main")
        self.assertFalse(kwargs["json_output"])
        self.assertTrue(kwargs["json_contract"])
        projection = json.loads(messages[1]["content"])
        self.assertEqual(projection["scheduled_allies"][0]["actor"], "Serah")
        self.assertEqual(projection["visible_enemies"], [
            {"name": "Goblin"}, {"name": "Hobgoblin"},
        ])
        self.assertEqual(
            ally_prefetch_batch_id(ENCOUNTER_ID, 1),
            "ally-prefetch-encounter-r1-ally",
        )

    def test_trace_failure_does_not_drop_submitted_background_request(self):
        jobs = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2], \
                mock.patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                mock.patch.object(
                    combat_latency_trace, "trace_ally_prefetch_submission",
                    side_effect=OSError("trace unavailable"),
                ) as trace:
            submitted = self._submit(_encounter(), executor=jobs.append)

        self.assertIsNotNone(submitted)
        self.assertTrue(submitted.submitted)
        self.assertIsInstance(submitted.receipt_correlation_id, str)
        self.assertEqual(len(jobs), 1)
        trace.assert_called_once()

    def test_directive_and_state_edge_share_one_replan_cap(self):
        encounter = _encounter()
        jobs = []
        request_messages = []

        def router(_task, messages, **_kwargs):
            request_messages.append(copy.deepcopy(messages))
            return json.dumps(_attack_orders())

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            initial = self._submit(encounter, executor=jobs.append, llm_call=router)
            self.assertTrue(initial.submitted)
            jobs[0]()
            # Non-semantic PC action counts are intentionally not snapshot inputs.
            count_only = dict(encounter, action_count=42)
            self.assertEqual(
                self._submit(
                    count_only,
                    trigger="state_edge",
                    executor=jobs.append,
                    llm_call=router,
                ).status,
                "no_major_change",
            )

            history = [
                build_ally_directive_history_record("Serah", "Watch the west gate"),
                build_ally_directive_history_record("Serah", "Guard the bridge"),
            ]
            replanned = self._submit(
                encounter,
                trigger="directive",
                history=history,
                executor=jobs.append,
                llm_call=router,
            )
            self.assertTrue(replanned.submitted)
            self.assertEqual(replanned.status, "replan_submitted")
            self.assertEqual(len(jobs), 2)
            jobs[1]()
            self.assertTrue(has_ally_prefetch_replan_submission(
                ENCOUNTER_ID, ally_prefetch_batch_id(ENCOUNTER_ID, 1)
            ))
            latest_projection = json.loads(request_messages[1][1]["content"])
            self.assertEqual(
                latest_projection["scheduled_allies"][0]["directive"],
                "Guard the bridge",
            )
            capped = self._submit(
                encounter,
                trigger="state_edge",
                executor=jobs.append,
                llm_call=router,
            )
            self.assertEqual(capped.status, "request_cap_reached")
            self.assertEqual(len(jobs), 2)

    def test_completed_initial_plan_remains_usable_while_replan_is_pending(self):
        encounter = _encounter()
        menus = _menus(encounter)
        jobs = []
        calls = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            initial = self._submit(
                encounter,
                executor=jobs.append,
                llm_call=lambda *_args, **_kwargs: json.dumps(_attack_orders()),
            )
            self.assertTrue(initial.submitted)
            jobs[0]()

            replan = self._submit(
                encounter,
                trigger="directive",
                history=[build_ally_directive_history_record("Serah", "Guard the bridge")],
                executor=jobs.append,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
            self.assertTrue(replan.submitted)
            self.assertEqual(replan.status, "replan_submitted")
            selected = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)

        self.assertTrue(selected.selected)
        self.assertEqual(selected.status, "prefetch_hit")
        self.assertEqual(selected.plan_origin, "standing_orders")
        self.assertEqual(selected.plan.status, "accepted")
        self.assertEqual(calls, [])
        # Selection cancels a still-running newer request after using the
        # newest completed result; its worker cannot mutate the consumed batch.
        jobs[1]()
        self.assertEqual(calls, [])

    def test_newest_completed_replan_compiles_against_current_menus(self):
        encounter = _encounter()
        jobs = []
        response_rows = [
            json.dumps(_attack_orders(target="Goblin")),
            json.dumps(_attack_orders(target="Hobgoblin")),
        ]
        responses = iter(response_rows)

        def router(*_args, **_kwargs):
            return next(responses)

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            initial = self._submit(encounter, executor=jobs.append, llm_call=router)
            self.assertTrue(initial.submitted)
            jobs[0]()
            latest_encounter = copy.deepcopy(encounter)
            latest_encounter["creatures"][1]["currentHitPoints"] = 0
            latest_encounter["creatures"][1]["status"] = "defeated"
            replan = self._submit(
                latest_encounter,
                trigger="directive",
                executor=jobs.append,
                llm_call=router,
            )
            self.assertTrue(replan.submitted)
            jobs[1]()
            current_menus = _menus(latest_encounter)
            selected = select_ally_prefetch_plan(
                ENCOUNTER_ID, current_menus, latest_encounter
            )

        self.assertTrue(selected.selected)
        self.assertEqual(selected.status, "prefetch_hit")
        self.assertEqual(selected.plan.status, "accepted")
        choice = selected.plan.choices[0]
        option = next(
            option
            for option in current_menus.actor_menus[0].attack_options
            if option.option_id == choice.option_ids[0]
        )
        self.assertEqual(option.target.name, "Hobgoblin")

    def test_production_response_content_maps_cover_to_current_menu_and_traces_batch(self):
        encounter = _encounter()
        features = [{
            "featureId": "ca02-ally-shield-racks",
            "name": "Practice Shield Racks",
            "kind": "cover",
            "coverType": "half",
            "usableBy": ["npc"],
        }]
        history = [build_ally_directive_history_record(
            "Serah", "take cover behind the shield racks"
        )]
        jobs = []
        trace_events = []

        def trace_writer(event_type, **fields):
            trace_events.append({"event_type": event_type, **fields})
            return True

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                trace_gate=lambda: True,
                trace_writer=trace_writer,
            )

        def router_call(task, messages, **kwargs):
            projection = json.loads(messages[1]["content"])
            self.assertIn("actor has exactly name (string) and kind (the string npc)", messages[0]["content"])
            self.assertIn("Return exactly one closed JSON object", messages[0]["content"])
            self.assertFalse(kwargs["json_output"])
            self.assertTrue(kwargs["json_contract"])
            actor = projection["scheduled_allies"][0]
            if "directive" in actor:
                self.assertEqual(actor["directive"], "take cover behind the shield racks")
                orders = _cover_orders(feature_id="ca02-ally-shield-racks")
                orders["intent"] = "Blairen follows the directive toward the shield racks."
                content = json.dumps(orders)
            else:
                content = json.dumps(_attack_orders())
            provider_response = SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=content)
                )],
                usage=SimpleNamespace(
                    prompt_tokens=64, completion_tokens=48, total_tokens=112
                ),
            )
            attempt = len([
                event for event in trace_events
                if event.get("event_type") == "provider"
            ]) + 1
            receipt = SimpleNamespace(
                kind="response",
                attempt_id="ally-attempt-%d" % attempt,
                call_id="ally-call-%d" % attempt,
                attempt_number=1,
                task=task,
                transport_provider="openrouter",
                observed_upstream_provider="provider-free",
                requested_model="openrouter/auto",
                resolved_model="test-model",
                fallback=False,
                transport_retry=False,
            )
            kwargs["observer"](receipt, provider_response)
            return provider_response.choices[0].message.content

        def record_submission(batch_id, request_id, request_kind):
            trace_events.append({
                "event_type": "combat_observation",
                "observation": "ally_prefetch_submission",
                "batch_id": batch_id,
                "request_id": request_id,
                "request_kind": request_kind,
            })
            return True

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2], \
                mock.patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                mock.patch.object(
                    combat_latency_trace,
                    "trace_ally_prefetch_submission",
                    side_effect=record_submission,
                ):
            initial = submit_ally_prefetch(
                encounter,
                encounter_id=ENCOUNTER_ID,
                multi_pc_manager=_manager(),
                active_encounter_id=ENCOUNTER_ID,
                tactical_features=features,
                llm_call=router_call,
                trigger="initial",
                executor=jobs.append,
                receipt_observer_factory=observer_factory,
            )
            self.assertTrue(initial.submitted)
            jobs.pop(0)()
            replan = submit_ally_prefetch(
                encounter,
                encounter_id=ENCOUNTER_ID,
                multi_pc_manager=_manager(),
                active_encounter_id=ENCOUNTER_ID,
                history=history,
                tactical_features=features,
                llm_call=router_call,
                trigger="directive",
                executor=jobs.append,
                receipt_observer_factory=observer_factory,
            )
            self.assertTrue(replan.submitted)
            jobs.pop(0)()
            current_menus = build_ally_menus(
                encounter,
                ally_prefetch_batch_id(ENCOUNTER_ID, encounter["combat_round"]),
                tactical_features=features,
            )
            selected = select_ally_prefetch_plan(
                ENCOUNTER_ID, current_menus, encounter
            )

        self.assertEqual(selected.status, "prefetch_hit")
        self.assertEqual(selected.request_kind, "replan")
        self.assertEqual(selected.plan_origin, "standing_orders")
        self.assertEqual(selected.prefetch_resolution, "current_menu_selected")
        choice = selected.plan.choices[0]
        self.assertEqual(choice.kind, "take_cover")
        self.assertIsNone(choice.default_reason)
        self.assertEqual(choice.cover_feature_id, "ca02-ally-shield-racks")
        current_cover_option = next(
            option for option in current_menus.actor_menus[0].cover_options
            if option.feature_id == "ca02-ally-shield-racks"
        )
        self.assertEqual(choice.option_ids, (current_cover_option.option_id,))
        provider_events = [
            event for event in trace_events if event.get("event_type") == "provider"
        ]
        self.assertEqual([event["request_kind"] for event in provider_events],
                         ["initial", "replan"])
        self.assertTrue(all(
            event["batch_id"] == "enemy:r1"
            and event["purpose"] == "combat_ally_standing_orders"
            and event["request_site"] == "combat_tactical_prefetch"
            for event in provider_events
        ))
        self.assertEqual(
            [event["request_kind"] for event in trace_events
             if event.get("observation") == "ally_prefetch_submission"],
            ["initial", "replan"],
        )

    def test_ally_standing_orders_diagnostics_match_prompt_contract_and_reject_unsafe_shapes(self):
        response = _cover_orders(feature_id="ca02-ally-shield-racks")
        response["intent"] = "A brief non-mechanical trace label."
        parsed, reason = parse_ally_standing_orders_response_with_reason(
            json.dumps(response)
        )
        self.assertEqual(parsed, response)
        self.assertIsNone(reason)

        wrong_actor_kind = copy.deepcopy(response)
        wrong_actor_kind["actors"][0]["actor"]["kind"] = "enemy"
        parsed, reason = parse_ally_standing_orders_response_with_reason(wrong_actor_kind)
        self.assertIsNone(parsed)
        self.assertEqual(reason, "actor_kind_invalid")

        forbidden_action = copy.deepcopy(response)
        forbidden_action["actors"][0]["clauses"][0]["do"] = {"kind": "surrender"}
        parsed, reason = parse_ally_standing_orders_response_with_reason(forbidden_action)
        self.assertIsNone(parsed)
        self.assertEqual(reason, "unsupported_action")

        parsed, reason = parse_ally_standing_orders_response_with_reason({"not_actors": []})
        self.assertIsNone(parsed)
        self.assertEqual(reason, "top_level_shape")

    def test_stale_cover_feature_keeps_rule_default_instead_of_forcing_cover(self):
        encounter = _encounter()
        features = [{
            "featureId": "ca02-ally-shield-racks",
            "name": "Practice Shield Racks",
            "kind": "cover",
            "coverType": "half",
            "usableBy": ["npc"],
        }]
        menus = build_ally_menus(
            encounter,
            ally_prefetch_batch_id(ENCOUNTER_ID, encounter["combat_round"]),
            tactical_features=features,
        )
        candidate = compile_ally_standing_orders(
            _cover_orders(feature_id="stale-feature-id"),
            menus,
            encounter,
        )
        self.assertEqual(candidate, {"choices": []})
        plan = validate_ally_plan(candidate, menus)
        self.assertEqual(plan.choices[0].kind, "attack")
        self.assertEqual(plan.choices[0].default_reason, "MISSING_CHOICE")

    def test_prefetch_diagnostics_distinguish_invalid_response_from_unavailable(self):
        encounter = _encounter()
        menus = _menus(encounter)
        jobs = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            invalid = self._submit(
                encounter,
                executor=jobs.append,
                llm_call=lambda *_args, **_kwargs: json.dumps({"not_actors": []}),
            )
            self.assertTrue(invalid.submitted)
            jobs.pop(0)()
            rejected = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)
            self.assertEqual(rejected.status, "standing_orders_unavailable")
            self.assertEqual(rejected.prefetch_resolution, "response_rejected")
            self.assertEqual(rejected.prefetch_rejection_reason, "top_level_shape")
            self.assertEqual(rejected.plan.choices[0].default_reason, "MISSING_CHOICE")

            _reset_ally_prefetch_for_tests()
            _reset_tactical_prefetch_for_tests()

            def unavailable_router(*_args, **_kwargs):
                raise RuntimeError("provider-free injected failure")

            unavailable = self._submit(
                encounter,
                executor=jobs.append,
                llm_call=unavailable_router,
            )
            self.assertTrue(unavailable.submitted)
            jobs.pop(0)()
            failed = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)

            _reset_ally_prefetch_for_tests()
            _reset_tactical_prefetch_for_tests()
            wrong_actor_kind = _cover_orders()
            wrong_actor_kind["actors"][0]["actor"]["kind"] = "enemy"
            invalid_kind = self._submit(
                encounter,
                executor=jobs.append,
                llm_call=lambda *_args, **_kwargs: json.dumps(wrong_actor_kind),
            )
            self.assertTrue(invalid_kind.submitted)
            jobs.pop(0)()
            kind_rejected = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)

        self.assertEqual(failed.status, "standing_orders_unavailable")
        self.assertEqual(failed.prefetch_resolution, "prefetch_unavailable")
        self.assertIsNone(failed.prefetch_rejection_reason)
        self.assertEqual(failed.plan.choices[0].default_reason, "MISSING_CHOICE")
        self.assertEqual(kind_rejected.status, "standing_orders_unavailable")
        self.assertEqual(kind_rejected.prefetch_resolution, "response_rejected")
        self.assertEqual(kind_rejected.prefetch_rejection_reason, "actor_kind_invalid")
        self.assertEqual(kind_rejected.plan.choices[0].default_reason, "MISSING_CHOICE")

    def test_prefetch_diagnostics_identify_current_menu_default_without_forcing_cover(self):
        encounter = _encounter()
        features = [{
            "featureId": "ca02-ally-shield-racks",
            "name": "Practice Shield Racks",
            "kind": "cover",
            "coverType": "half",
            "usableBy": ["npc"],
        }]
        jobs = []
        response = json.dumps(_cover_orders(feature_id="stale-feature-id"))
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            submitted = submit_ally_prefetch(
                encounter,
                encounter_id=ENCOUNTER_ID,
                multi_pc_manager=_manager(),
                active_encounter_id=ENCOUNTER_ID,
                tactical_features=features,
                llm_call=lambda *_args, **_kwargs: response,
                executor=jobs.append,
            )
            self.assertTrue(submitted.submitted)
            jobs.pop(0)()
            menus = build_ally_menus(
                encounter,
                ally_prefetch_batch_id(ENCOUNTER_ID, encounter["combat_round"]),
                tactical_features=features,
            )
            selected = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)

        self.assertEqual(selected.status, "prefetch_hit")
        self.assertEqual(selected.prefetch_resolution, "current_menu_default")
        self.assertEqual(selected.plan.choices[0].kind, "attack")
        self.assertEqual(selected.plan.choices[0].default_reason, "MISSING_CHOICE")

    def test_major_state_edge_replans_once_and_later_state_edges_are_capped(self):
        encounter = _encounter()
        jobs = []
        calls = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            self.assertTrue(self._submit(
                encounter,
                executor=jobs.append,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)) or json.dumps(_attack_orders()),
            ).submitted)
            changed = copy.deepcopy(encounter)
            changed["creatures"][1]["currentHitPoints"] = 4
            replan = self._submit(
                changed,
                trigger="state_edge",
                executor=jobs.append,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)) or json.dumps(_attack_orders()),
            )
            self.assertTrue(replan.submitted)
            self.assertEqual(replan.status, "replan_submitted")
            changed_again = copy.deepcopy(changed)
            changed_again["creatures"][2]["currentHitPoints"] = 5
            capped = self._submit(
                changed_again,
                trigger="state_edge",
                executor=jobs.append,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)) or json.dumps(_attack_orders()),
            )
        self.assertEqual(capped.status, "request_cap_reached")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(calls, [])

    def test_canonical_pc_hp_edge_triggers_the_single_state_replan(self):
        encounter = _encounter()
        manager = SimpleNamespace(
            combat_phase="PC_PHASE",
            pc_states={"Acheron": SimpleNamespace(current_hp=20)},
        )
        jobs = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            initial = self._submit(
                encounter,
                manager=manager,
                executor=jobs.append,
                llm_call=lambda *_args, **_kwargs: json.dumps(_attack_orders()),
            )
            self.assertTrue(initial.submitted)
            manager.pc_states["Acheron"].current_hp = 0
            replan = self._submit(
                encounter,
                manager=manager,
                trigger="state_edge",
                executor=jobs.append,
                llm_call=lambda *_args, **_kwargs: json.dumps(_attack_orders()),
            )

        self.assertTrue(replan.submitted)
        self.assertEqual(replan.status, "replan_submitted")
        self.assertEqual(len(jobs), 2)

    def test_current_menus_skip_stale_target_and_compile_next_legal_clause(self):
        encounter = _encounter()
        encounter["creatures"][1]["currentHitPoints"] = 0
        encounter["creatures"][1]["status"] = "defeated"
        menus = _menus(encounter)
        orders = {
            "actors": [{
                "actor": {"name": "Serah", "kind": "npc"},
                "clauses": [
                    {
                        "when": "always",
                        "do": {
                            "kind": "attack",
                            "target": {"name": "Goblin", "kind": "enemy"},
                            "action": "Longbow",
                        },
                    },
                    {
                        "when": "always",
                        "do": {
                            "kind": "attack",
                            "target": {"name": "Hobgoblin", "kind": "enemy"},
                            "action": "Longbow",
                        },
                    },
                ],
            }],
        }
        compiled = compile_ally_standing_orders(orders, menus, encounter)
        self.assertIsNotNone(compiled)
        menu = menus.actor_menus[0]
        selected_id = compiled["choices"][0]["option_ids"][0]
        selected = next(option for option in menu.attack_options if option.option_id == selected_id)
        self.assertEqual(selected.target.name, "Hobgoblin")

    def test_orders_reject_flight_dodge_and_spatial_placeholders(self):
        for action in (
            {"kind": "flee"},
            {"kind": "surrender"},
            {"kind": "dodge"},
            {"kind": "move_to_cover"},
            {"kind": "interpose_for_ally"},
            {"kind": "guard_ally"},
        ):
            response = {
                "actors": [{
                    "actor": {"name": "Serah", "kind": "npc"},
                    "clauses": [{"when": "always", "do": action}],
                }],
            }
            with self.subTest(action=action):
                self.assertIsNone(parse_ally_standing_orders_response(response))

    def test_pending_and_failed_selected_paths_default_without_sync_repair(self):
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            encounter = _encounter()
            menus = _menus(encounter)
            jobs = []
            calls = []
            self.assertTrue(self._submit(
                encounter,
                executor=jobs.append,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)),
            ).submitted)
            pending = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)
            self.assertTrue(pending.selected)
            self.assertEqual(pending.status, "standing_orders_unavailable")
            self.assertEqual(pending.prefetch_resolution, "prefetch_unavailable")
            self.assertEqual(pending.plan.status, "defaulted")
            self.assertEqual(calls, [])
            # The worker's result is not awaited or used after the batch boundary.
            jobs[0]()
            self.assertEqual(calls, [])

            _reset_ally_prefetch_for_tests()
            _reset_tactical_prefetch_for_tests()
            failed_jobs = []

            def failed_router(*_args, **_kwargs):
                raise RuntimeError("provider-free injected failure")

            self.assertTrue(self._submit(
                encounter, executor=failed_jobs.append, llm_call=failed_router
            ).submitted)
            failed_jobs[0]()
            failed = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)
            self.assertTrue(failed.selected)
            self.assertEqual(failed.status, "standing_orders_unavailable")
            self.assertEqual(failed.prefetch_resolution, "prefetch_unavailable")
            self.assertEqual(failed.plan.status, "defaulted")

    def test_late_deadline_result_defaults_without_running_provider(self):
        encounter = _encounter()
        menus = _menus(encounter)
        now = [10.0]
        jobs = []
        calls = []
        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            submitted = submit_ally_prefetch(
                encounter,
                encounter_id=ENCOUNTER_ID,
                multi_pc_manager=_manager(),
                active_encounter_id=ENCOUNTER_ID,
                llm_call=lambda *args, **kwargs: calls.append((args, kwargs)),
                deadline_seconds=1.0,
                clock=lambda: now[0],
                executor=jobs.append,
            )
            self.assertTrue(submitted.submitted)
            now[0] = 12.0
            jobs[0]()
            selected = select_ally_prefetch_plan(
                ENCOUNTER_ID, menus, encounter, clock=lambda: now[0]
            )

        self.assertTrue(selected.selected)
        self.assertEqual(selected.status, "standing_orders_unavailable")
        self.assertEqual(selected.plan.status, "defaulted")
        self.assertEqual(calls, [])

    def test_late_stale_result_remains_selected_and_defaults(self):
        encounter = _encounter()
        menus = _menus(encounter)
        before = copy.deepcopy(encounter)
        started = threading.Event()
        release = threading.Event()
        workers = []
        calls = []

        def router(*_args, **_kwargs):
            calls.append(True)
            started.set()
            release.wait(2)
            return json.dumps(_attack_orders())

        def threaded_executor(job):
            worker = threading.Thread(target=job, daemon=True)
            workers.append(worker)
            worker.start()

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            submitted = self._submit(
                encounter, executor=threaded_executor, llm_call=router
            )
            self.assertTrue(submitted.submitted)
            self.assertTrue(started.wait(2), "background worker did not start")
            invalidated = invalidate_ally_prefetch(
                ENCOUNTER_ID, ally_prefetch_batch_id(ENCOUNTER_ID, 1)
            )
            self.assertEqual(invalidated.status, "prefetch_stale")
            self.assertTrue(has_ally_prefetch_submission(
                ENCOUNTER_ID, ally_prefetch_batch_id(ENCOUNTER_ID, 1)
            ))
            release.set()
            for worker in workers:
                worker.join(timeout=2)
            selected = select_ally_prefetch_plan(ENCOUNTER_ID, menus, encounter)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(calls, [True])
        self.assertTrue(selected.selected)
        self.assertEqual(selected.status, "standing_orders_unavailable")
        self.assertEqual(selected.plan.status, "defaulted")
        self.assertEqual(encounter, before)

    def test_ineligible_phase_and_directive_command_do_not_trigger_state_edge_hook(self):
        for command in ("/end", "Enemies turn.", "/cmd Serah Hold the bridge"):
            self.assertFalse(should_consider_ally_prefetch_replan(command, _manager()))
        self.assertFalse(should_consider_ally_prefetch_replan(
            "/att Goblin", _manager("ENEMY_PHASE")
        ))
        self.assertTrue(should_consider_ally_prefetch_replan(
            "[Acheron]: /att Goblin", _manager()
        ))

    def test_seeded_pc_phase_initial_prefetch_hands_off_to_cmd_replan(self):
        session = SimpleNamespace(
            active_pc=None,
            set_phase=lambda _phase: None,
        )
        manager = SimpleNamespace(
            combat_phase="PC_PHASE",
            current_pc_name="Acheron",
            pc_states={},
        )
        encounter = _encounter()
        party_tracker_data = {
            "active_character": "Acheron",
            "worldConditions": {"activeCombatEncounter": ENCOUNTER_ID},
        }
        history = []
        iteration = SimpleNamespace(
            session=session,
            encounter_data=encounter,
            multi_pc_manager=manager,
            party_tracker_data=party_tracker_data,
            conversation_history=history,
            user_input_text="/cmd Serah Guard the bridge",
            path_manager=None,
            npc_templates={},
        )
        inputs = CombatNormalTurnInputs(
            iteration=iteration,
            encounter_id=ENCOUNTER_ID,
            json_file_path="encounter.json",
            conversation_history_file="history.json",
            location_info={},
        )
        jobs = []
        projections = []

        def router(_task, messages, **_kwargs):
            projections.append(json.loads(messages[1]["content"]))
            return json.dumps(_attack_orders())

        def submit(**kwargs):
            return submit_ally_prefetch(
                kwargs["encounter_data"],
                encounter_id=kwargs["encounter_id"],
                multi_pc_manager=kwargs["multi_pc_manager"],
                active_encounter_id=party_tracker_data["worldConditions"][
                    "activeCombatEncounter"
                ],
                history=kwargs["conversation_history"],
                llm_call=router,
                trigger=kwargs["trigger"],
                executor=jobs.append,
            )

        def accepted_cmd(**_kwargs):
            history.append(build_ally_directive_history_record("Serah", "Guard the bridge"))
            return SimpleNamespace(
                control_action="continue",
                user_input_text="/cmd Serah Guard the bridge",
                status="accepted",
                reason="accepted",
            )

        dependencies = SimpleNamespace(
            input_phase_gate=lambda *_args, **_kwargs: InputPhaseGateResult(
                control_action="proceed",
                raw_input="/cmd Serah Guard the bridge",
                clean_input="/cmd Serah Guard the bridge",
                input_actor_name="Acheron",
            ),
            phase_gate_io_factory=lambda _manager: None,
            initiative_gate=None,
            submit_standing_orders=None,
            submit_ally_prefetch=submit,
            fast_command_stage=accepted_cmd,
            fast_command_io_factory=lambda: None,
        )

        with _enabled_flags()[0], _enabled_flags()[1], _enabled_flags()[2]:
            result = prepare_combat_normal_turn(inputs, dependencies)
            self.assertEqual(result.control_action, "continue")
            self.assertEqual(len(jobs), 2)
            jobs[0]()
            jobs[1]()
            selected = select_ally_prefetch_plan(
                ENCOUNTER_ID, _menus(encounter), encounter
            )

        self.assertTrue(selected.selected)
        self.assertEqual(selected.request_kind, "replan")
        self.assertEqual(len(projections), 2)
        self.assertNotIn("directive", projections[0]["scheduled_allies"][0])
        self.assertEqual(
            projections[1]["scheduled_allies"][0]["directive"], "Guard the bridge"
        )


if __name__ == "__main__":
    unittest.main()
