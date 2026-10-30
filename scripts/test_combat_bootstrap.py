# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Bootstrap Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free checks for startup ownership and typed handoffs.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import builtins
import io
import inspect
import json
import socket
import os
import unittest
import uuid
from dataclasses import replace as dataclass_replace
from types import SimpleNamespace
from unittest.mock import patch

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()


class _ForbiddenEffect(BaseException):
    pass


_real_socket = socket.socket
_real_create_connection = socket.create_connection
_real_open = builtins.open
_real_import = builtins.__import__
_real_os_open = os.open


def _deny_network(*args, **kwargs):
    raise _ForbiddenEffect("network access forbidden in combat bootstrap tests")


def _deny_write(path, mode="r", *args, **kwargs):
    if any(flag in mode for flag in ("w", "a", "+", "x")):
        raise _ForbiddenEffect("outside/test-file write forbidden in combat bootstrap tests")
    return _real_open(path, mode, *args, **kwargs)


def _deny_sdk_import(name, *args, **kwargs):
    if name.split(".", 1)[0] in {"openai", "httpx", "requests", "socketio"}:
        raise _ForbiddenEffect("SDK/provider import forbidden in combat bootstrap tests")
    return _real_import(name, *args, **kwargs)


def _deny_os_write(path, flags, *args, **kwargs):
    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        raise _ForbiddenEffect("filesystem write forbidden in combat bootstrap tests")
    return _real_os_open(path, flags, *args, **kwargs)


# Install fatal guards before importing the component under test.
socket.socket = _deny_network
socket.create_connection = _deny_network
builtins.open = _deny_write
builtins.__import__ = _deny_sdk_import
os.open = _deny_os_write
try:
    from core.combat.bootstrap import (
        CombatInitializationDependencies,
        CombatInitializationInputs,
        CombatStartupNarrativeDependencies,
        CombatStartupNarrativeInputs,
        CombatHistoryDependencies,
        build_fresh_combat_history,
        hydrate_fresh_combat_history,
        initialize_combat_session,
        refresh_resumed_combat_history,
        run_startup_narrative,
        select_combat_history,
    )
    from core.combat.prompts import (
        InitialCombatStateDependencies,
        InitialCombatStateInputs,
        prepare_initial_combat_state,
    )
    from core.combat.turn import (
        CombatActionTraceDependencies,
        CombatActionTraceInputs,
        CombatNormalTurnDependencies,
        CombatNormalTurnInputs,
        PhaseGateIO,
        CombatTurnIterationDependencies,
        CombatTurnIterationInputs,
        CombatTurnIterationResult,
        InputPhaseGateResult,
        begin_combat_turn_iteration,
        prepare_combat_normal_turn,
        run_input_phase_gate,
        trace_combat_action_batch_metadata,
    )
    from core.combat import decisions as combat_decisions
    from core.combat.commands import (
        DeterministicCommandIO,
        FastCommandIO,
        FastCommandResult,
        run_deterministic_command_stage,
        run_fast_commands_stage,
        run_character_stat_command,
        CharacterStatCommandIO,
    )
    from core.combat.persistence import (
        CombatFinalizationDependencies,
        CombatFinalizationInputs,
        finalize_combat_session,
    )
finally:
    socket.socket = _real_socket
    socket.create_connection = _real_create_connection
    builtins.open = _real_open
    builtins.__import__ = _real_import
    os.open = _real_os_open


class _Session:
    def __init__(self, multi_pc_manager=None):
        self.calls = []
        self.multi_pc_manager = multi_pc_manager
        self.active_pc = None
        self.phase = "PC_PHASE"
        self.encounter = {}
        self.turn_iteration_id = 0
        self.last_active_encounter_sync_turn_id = None

    def begin_turn_iteration(self):
        self.turn_iteration_id += 1
        return self.turn_iteration_id

    def claim_active_encounter_sync(self, turn_identity, *, force=False):
        if not force and self.last_active_encounter_sync_turn_id == turn_identity:
            return False
        self.last_active_encounter_sync_turn_id = turn_identity
        return True

    def history_payloads(self, **kwargs):
        self.calls.append(("payloads", kwargs))
        return {"head": kwargs["head_context"], "monsters": "Monster Templates", "location": "Location"}

    def apply_history_payloads(self, payloads):
        self.calls.append(("apply", payloads))

    def bind_history(self, history):
        self.history = history
        self.calls.append(("bind_history", history))

    def bind_encounter(self, encounter):
        self.encounter = encounter
        self.calls.append(("bind_encounter", encounter))

    def set_phase(self, phase):
        self.phase = phase
        self.calls.append(("phase", phase))
        return phase

    def replace_system_payload(self, marker, content):
        self.calls.append(("replace_system_payload", marker, content))
        for message in self.history:
            if message.get("role") == "system" and marker in message.get("content", ""):
                message["content"] = content
                return True
        return False


def _is_json_object(value):
    try:
        return isinstance(json.loads(value), dict)
    except (TypeError, ValueError):
        return False


class CombatBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.files = {}
        self.dependencies = CombatHistoryDependencies(
            exists=lambda path: path in self.files,
            getsize=lambda path: 101,
            load_json=lambda path: self.files[path],
            read_prompt=lambda path: self.events.append(("prompt", path)) or "system prompt [PC_LIST]",
            save_json=lambda path, value: self.events.append(("save", path, value)),
            format_character=lambda info, **kwargs: f"PC:{info['name']}",
            format_npc=lambda info, role: f"NPC:{info['name']}:{role}",
            filter_dynamic_fields=lambda value: value,
            filter_encounter=lambda value: value,
            log_structure=lambda history: self.events.append(("log", history)),
            debug=lambda *args, **kwargs: self.events.append(("debug", args[0])),
            error=lambda *args, **kwargs: self.events.append(("error", args[0])),
            emit=lambda value: self.events.append(("emit", value)),
            remove=lambda path: self.events.append(("remove", path)),
        )

    def test_selects_matching_history_and_rejects_stale_history(self):
        matching = [{"role": "system", "content": "Current Combat Encounter: e-1"}]
        self.files["history"] = matching
        selected = select_combat_history(
            encounter_id="e-1", history_file="history", dependencies=self.dependencies
        )
        self.assertTrue(selected.is_resuming)
        self.assertIs(selected.history, matching)

        self.files["history"] = [{"role": "system", "content": "Current Combat Encounter: old"}]
        stale = select_combat_history(
            encounter_id="e-1", history_file="history", dependencies=self.dependencies
        )
        self.assertFalse(stale.is_resuming)
        self.assertEqual(stale.history, [])

    def test_fresh_prompt_uses_compressed_multipc_asset_and_pc_list(self):
        history = build_fresh_combat_history(
            encounter_id="e-1",
            encounter_data={"creatures": [{"type": "player", "name": "A"}]},
            party_tracker_data={"active_character": "A"},
            multi_pc=True,
            dependencies=self.dependencies,
        )
        self.assertIn(("prompt", "combat/combat_sim_prompt_multipc_compressed.txt"), self.events)
        self.assertEqual(history[0]["content"], "system prompt A")
        self.assertEqual(history[1]["content"], "Current Combat Encounter: e-1")
        self.assertEqual([message["content"] for message in history[2:]], ["", "", ""])

    def test_fresh_payload_order_and_cache_then_history_writes(self):
        session = _Session()
        history = [{"role": "system", "content": ""}]
        ready = hydrate_fresh_combat_history(
            history=history,
            encounter_id="e-1",
            encounter_data={"creatures": [{"type": "enemy"}]},
            player_info={"name": "A"},
            monster_templates={"goblin": {"name": "Goblin"}},
            npc_templates={"ally.json": {"name": "Ally"}},
            party_tracker_data={"partyNPCs": [{"name": "Ally", "role": "Scout"}]},
            location_info={"name": "Cave", "encounters": [1]},
            multi_pc_manager=None,
            history_file="history",
            session=session,
            dependencies=self.dependencies,
        )
        self.assertTrue(ready)
        self.assertEqual(session.calls[-1][0], "apply")
        self.assertEqual(session.calls[-1][1]["monsters"], "Monster Templates")
        self.assertEqual(history[-2]["content"], "Here's the NPC data for Ally:\n\nNPC:Ally:Scout\n")
        self.assertTrue(history[-1]["content"].startswith("Encounter Details:\n{\n"))
        self.assertLess(
            next(i for i, event in enumerate(self.events) if event[0] == "emit" and "clearing compression caches" in event[1]),
            next(i for i, event in enumerate(self.events) if event[0] == "save"),
        )

    def test_missing_monster_templates_preserves_early_failure_before_output(self):
        session = _Session()
        ready = hydrate_fresh_combat_history(
            history=[], encounter_id="e-1", encounter_data={"creatures": [{"type": "enemy"}]},
            player_info={"name": "A"}, monster_templates={}, npc_templates={},
            party_tracker_data={}, location_info={}, multi_pc_manager=None,
            history_file="history", session=session, dependencies=self.dependencies,
        )
        self.assertFalse(ready)
        self.assertEqual(session.calls[-1][0], "apply")
        self.assertFalse(any(event[0] in ("save", "log") for event in self.events))

    def test_resume_replaces_payloads_and_persists_before_owner_continues(self):
        session = _Session()
        history = [
            {"role": "system", "content": "Here's the player character data: old"},
            {"role": "system", "content": "Location:\nold"},
            {"role": "system", "content": "Here's the NPC data for Ally: old"},
            {"role": "user", "content": "keep"},
        ]
        refresh_resumed_combat_history(
            history=history, player_info={"name": "A"}, monster_templates={"goblin": {}},
            npc_templates={"ally.json": {"name": "Ally"}},
            party_tracker_data={"partyNPCs": [{"name": "Ally", "role": "Scout"}]},
            multi_pc_manager=None, history_file="history", location_info={"name": "Cave"},
            session=session, dependencies=self.dependencies,
        )
        self.assertEqual(history[0]["content"], "Here's the player character data:\n\nPC:A\n")
        self.assertEqual(history[-1], {"role": "user", "content": "keep"})
        self.assertTrue(any("NPC data for Ally" in item["content"] for item in history))
        self.assertEqual(self.events[-1][0], "emit")
        self.assertEqual(self.events[-2][0], "save")

    def _startup_fakes(self, responses=(), *, gpt5=False, temperature=0.63, validation=True):
        events = []
        requests = []
        compressed = []
        validations = []
        saves = []
        errors = []
        warnings = []
        outputs = []
        usage = []
        response_queue = list(responses)

        def llm_call(task, messages, **kwargs):
            requests.append({"task": task, "messages": messages, **kwargs})
            events.append(("request", requests[-1]))
            if not response_queue:
                raise AssertionError("unexpected router attempt")
            response = response_queue.pop(0)
            if isinstance(response, BaseException):
                raise response
            if kwargs.get("observer"):
                kwargs["observer"](SimpleNamespace(kind="response", attempt_id=len(requests)),
                                   SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))]))
            return response

        def emit(text):
            events.append(("emit", text))

        def flush():
            events.append(("flush",))

        def exporter(path, mode, **kwargs):
            events.append(("export", path, mode, kwargs))
            return io.StringIO()

        def completion_params(task, model, **kwargs):
            events.append(("params", task, model, kwargs))
            return {"task": task, "model": model, **kwargs}

        def get_temperature(encounter, validation_attempt):
            events.append(("temperature", validation_attempt))
            return temperature - 0.1 * validation_attempt

        def validate(response, encounter, prompt, history, *, multi_pc_manager):
            validations.append((response, encounter, prompt, history, multi_pc_manager))
            events.append(("validate", prompt))
            if isinstance(validation, list):
                return validation.pop(0)
            return validation

        def log_api_call(*args, **kwargs):
            events.append(("api_log", args, kwargs))

        def track_usage(response):
            usage.append(response)
            events.append(("usage",))
            raise RuntimeError("fake usage sink unavailable")

        def receipt_observer_factory(**options):
            events.append(("observer_factory", options))
            def observe(receipt, response):
                events.append(("trace_provider", (options.get("trace_site"), receipt, response)))
                if options.get("endpoint_name"):
                    log_api_call(options["endpoint_name"], options.get("messages"), response,
                                 metadata=options.get("legacy_context"))
                if options.get("track_usage"):
                    try:
                        track_usage(response)
                    except Exception as exc:
                        dependencies.warning(f"USAGE_TRACKING: Failed to track startup response: {exc}",
                                             category="combat_events")
            return observe

        def publish_narration(text, *, emit, flush):
            outputs.append(f"Dungeon Master: {text}")
            emit(f"Dungeon Master: {text}")
            flush()

        def publish_output(text, *, emit, flush):
            outputs.append(text)
            emit(text)
            flush()

        dependencies = CombatStartupNarrativeDependencies(
            client=None,
            resume_config=lambda: (gpt5, "gpt-5-mini"),
            combat_main_model="legacy-main-model",
            completion_params=completion_params,
            get_temperature=get_temperature,
            get_initiative_order=lambda encounter: events.append(("initiative",)) or "initiative-order",
            get_multi_pc_initiative_narrative=lambda manager: "group-initiative-narrative",
            modify_prompt_for_multi_pc=lambda prompt, active, manager: prompt + f"\nACTIVE:{active}",
            is_valid_json=lambda text: _is_json_object(text),
            validate_response=validate,
            save_json=lambda path, value: (saves.append((path, value)), events.append(("save", path, value))),
            export_open=exporter,
            perf_counter=lambda: events.append(("clock",)) or 12.5,
            trace_stage=lambda *args: events.append(("trace_stage", args)),
            trace_provider_call=lambda *args: events.append(("trace_provider", args)),
            usage_tracking_available=True,
            track_usage=track_usage,
            log_api_call=log_api_call,
            emit=emit,
            flush=flush,
            debug=lambda message, **kwargs: events.append(("debug", message, kwargs)),
            info=lambda message, **kwargs: events.append(("info", message, kwargs)),
            warning=lambda message, **kwargs: (warnings.append(message), events.append(("warning", message))),
            error=lambda message, **kwargs: (errors.append(message), events.append(("error", message))),
            publish_narration=publish_narration,
            publish_output=publish_output,
            llm_call=llm_call,
            receipt_observer_factory=receipt_observer_factory,
        )
        return dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage

    def _real_router_startup_dependencies(self, responses, *, gpt5=False, validation=True):
        from dataclasses import replace
        import utils.ai_client_factory as factory
        import utils.llm_router as router_module
        from utils.llm_runtime import make_legacy_receipt_observer

        events = []
        sdk_calls = []
        queue = list(responses)

        class FakeCompletions:
            def create(self, **kwargs):
                sdk_calls.append(kwargs)
                if not queue:
                    raise AssertionError("real facade made an unexpected SDK attempt")
                result = queue.pop(0)
                if isinstance(result, BaseException):
                    raise result
                return result

        class FakeSDKClient:
            chat = SimpleNamespace(completions=FakeCompletions())

            def with_options(self, **kwargs):
                events.append(("sdk_options", kwargs))
                return self

        client = FakeSDKClient()
        base, _old_events, _requests, _compressed, _validations, _saves, _errors, _warnings, _outputs, _usage = self._startup_fakes(
            (), gpt5=gpt5, validation=validation
        )
        tracker = SimpleNamespace(track=lambda raw, context: events.append(("usage", raw, context)))

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: tracker,
                trace_gate=lambda: True,
                trace_writer=lambda name, **fields: events.append(("trace", name, fields)),
            )

        def real_facade_call(task, messages, **kwargs):
            events.append(("router_call", task, messages, kwargs))
            return router_module.llm.call(task, messages, **kwargs)

        dependencies = replace(
            base,
            llm_call=real_facade_call,
            receipt_observer_factory=observer_factory,
            log_api_call=lambda *args, **kwargs: events.append(("api", args, kwargs)),
        )
        return dependencies, factory, router_module, client, sdk_calls, events

    def test_real_router_fake_sdk_runs_actual_startup_stages_and_receipts(self):
        from unittest.mock import patch

        cases = (
            ("resume-gpt5", True, True, '{"narration":"GPT-5 resumes."}', "GPT-5 resumes."),
            ("resume-legacy", True, False, '{"narration":"Legacy resumes."}', "Legacy resumes."),
            ("initial", False, False,
             '{"narration":"Initial scene.","combat_round":1,"actions":[]}', "Initial scene."),
        )
        for label, resume, gpt5, content, narration in cases:
            with self.subTest(case=label):
                raw = {"choices": [{"message": {"content": content}}], "model": "fixture-resolved",
                       "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
                dependencies, factory, router_module, client, sdk_calls, events = self._real_router_startup_dependencies(
                    [raw], gpt5=gpt5
                )
                inputs = CombatStartupNarrativeInputs(
                    history=[{"role": "system", "content": "Current Combat Encounter: fixture"}],
                    history_file="history", is_resuming=resume,
                    encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                    dynamic_state="unchanged dynamic", preroll_text="unchanged preroll", session=_Session(),
                )
                with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
                     patch.object(factory, "create_chat_client", return_value=client):
                    result = run_startup_narrative(inputs, dependencies)

                self.assertEqual(result.narration, narration)
                self.assertEqual(len(sdk_calls), 1)
                self.assertNotIn("timeout", sdk_calls[0])
                router_request = next(event for event in events if event[0] == "router_call")
                self.assertEqual(router_request[1], "combat_main")
                self.assertIs(router_request[3]["json_output"], False)
                self.assertNotIn("timeout", router_request[3])
                if resume:
                    api_event = next(event for event in events if event[0] == "api")
                    self.assertEqual(sdk_calls[0]["messages"], api_event[1][1])
                else:
                    self.assertTrue(sdk_calls[0]["messages"][-1]["content"].startswith("Dungeon Master Note:"))
                self.assertEqual(len([event for event in events if event[0] == "trace"]), 1)
                self.assertEqual(len([event for event in events if event[0] == "usage"]), 1)
                self.assertEqual(len([event for event in events if event[0] == "api"]), int(resume))
                delivered = [event[0] for event in events if event[0] in ("trace", "api", "usage")]
                self.assertEqual(delivered, ["trace", "api", "usage"] if resume else ["trace", "usage"])
                trace = next(event[2] for event in events if event[0] == "trace")
                self.assertEqual(trace["task"], "combat_main")
                self.assertTrue(trace["requested_model"])
                self.assertEqual(trace["resolved_model"], "fixture-resolved")
                if label == "resume-gpt5":
                    self.assertNotIn("temperature", sdk_calls[0])
                elif label == "resume-legacy":
                    self.assertEqual(next(event for event in events if event[0] == "router_call")[3]["temperature"], 0.63)
                else:
                    self.assertEqual(next(event for event in events if event[0] == "router_call")[3]["temperature"], 0.63)

    def test_real_router_preserves_three_nonterminal_initial_attempts(self):
        from unittest.mock import patch

        invalid_responses = [
            {"choices": [{"message": {"content": f"not-json-{index}"}}], "model": "fixture"}
            for index in range(3)
        ]
        from dataclasses import replace
        dependencies, factory, _router_module, client, sdk_calls, events = self._real_router_startup_dependencies(
            invalid_responses
        )
        dependencies = replace(
            dependencies,
            publish_output=lambda text, **kwargs: events.append(("published_output", text)),
        )
        history = [{"role": "system", "content": "fresh"}]
        inputs = CombatStartupNarrativeInputs(
            history=history, history_file="history", is_resuming=False,
            encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
            dynamic_state="d", preroll_text="p", session=_Session(),
        )
        with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
             patch.object(factory, "create_chat_client", return_value=client):
            result = run_startup_narrative(inputs, dependencies)
        self.assertFalse(result.return_early)
        self.assertEqual(len(sdk_calls), 3)
        self.assertEqual(sum(event[0] == "router_call" for event in events), 3)
        self.assertTrue(all(event[3]["json_output"] is False
                            for event in events if event[0] == "router_call"))
        self.assertEqual(sum(event[0] == "trace" for event in events), 3)
        self.assertEqual(sum(event[0] == "usage" for event in events), 3)
        self.assertEqual(sum(event[0] == "published_output" for event in events), 1)

    def test_real_router_terminal_receipts_stop_startup_without_stale_publish(self):
        from dataclasses import replace
        from unittest.mock import patch
        from utils.llm_router import GameLLMTerminalError

        cases = (
            ("quota", RuntimeError("insufficient_quota")),
            ("refusal", {"choices": [{"message": {"content": "", "refusal": "refused"}}], "model": "fixture"}),
            ("content_filter", {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}], "model": "fixture"}),
        )
        for terminal_kind, terminal_result in cases:
            with self.subTest(terminal=terminal_kind):
                dependencies, factory, router_module, client, sdk_calls, events = self._real_router_startup_dependencies(
                    [terminal_result]
                )
                dependencies = replace(
                    dependencies,
                    publish_narration=lambda *args, **kwargs: events.append(("published_narration", args)),
                    publish_output=lambda *args, **kwargs: events.append(("published_output", args)),
                )
                inputs = CombatStartupNarrativeInputs(
                    history=[{"role": "system", "content": "fresh"}], history_file="history",
                    is_resuming=False, encounter_data={"creatures": []}, party_tracker_data={},
                    multi_pc_manager=None, dynamic_state="d", preroll_text="p", session=_Session(),
                )
                with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
                     patch.object(factory, "create_chat_client", return_value=client):
                    with self.assertRaises(GameLLMTerminalError):
                        run_startup_narrative(inputs, dependencies)
                self.assertEqual(len(sdk_calls), 1)
                expected_usage = 0 if terminal_kind == "quota" else 1
                self.assertEqual(sum(event[0] == "usage" for event in events), expected_usage)
                self.assertTrue(any(event[0] == "trace" for event in events))
                self.assertFalse(any(event[0] == "api" for event in events))
                self.assertFalse(any(event[0] in ("published_narration", "published_output") for event in events))
                self.assertFalse(any(message.get("role") == "assistant" for message in inputs.history))
                self.assertFalse(any(event[0] == "validate" for event in events))

    def test_real_router_late_terminal_does_not_publish_or_save_prior_nonterminal_text(self):
        from dataclasses import replace
        from unittest.mock import patch
        from utils.llm_router import GameLLMTerminalError

        invalid = {"choices": [{"message": {"content": "not json"}}], "model": "fixture"}
        refusal = {"choices": [{"message": {"content": "", "refusal": "refused"}}], "model": "fixture"}
        dependencies, factory, router_module, client, sdk_calls, events = self._real_router_startup_dependencies(
            [invalid, refusal]
        )
        saves = []
        outputs = []
        dependencies = replace(
            dependencies,
            save_json=lambda path, value: saves.append((path, value)),
            publish_narration=lambda *args, **kwargs: outputs.append(("narration", args)),
            publish_output=lambda *args, **kwargs: outputs.append(("output", args)),
        )
        history = [{"role": "system", "content": "fresh"}]
        inputs = CombatStartupNarrativeInputs(
            history=history, history_file="history", is_resuming=False,
            encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
            dynamic_state="d", preroll_text="p", session=_Session(),
        )
        with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
             patch.object(factory, "create_chat_client", return_value=client):
            with self.assertRaises(GameLLMTerminalError):
                run_startup_narrative(inputs, dependencies)

        self.assertEqual(len(sdk_calls), 2)
        self.assertEqual([event[0] for event in events if event[0] == "trace"].__len__(), 2)
        self.assertEqual([event[0] for event in events if event[0] == "usage"].__len__(), 2)
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0][1][-1], {"role": "user", "content": history[-1]["content"]})
        self.assertEqual(history[-1]["role"], "user")
        self.assertEqual(outputs, [])

    def _initialization_fakes(self, pc_names=("Acheron",), *, cached_manager=None, missing_character=None,
                              encounter_failure=None, multipc=True):
        events = []
        saves = []
        files = {"party_tracker.json": {"module": "Current Module"}}
        encounter_id = "fixture-encounter"
        encounter_path = f"modules/encounters/encounter_{encounter_id}.json"
        encounter = {
            "encounterId": encounter_id,
            "combat_round": 4,
            "creatures": ([{"type": "player", "name": name} for name in pc_names]
                          + [{"type": "enemy", "name": "Goblin A", "monsterType": "goblin"},
                             {"type": "enemy", "name": "Goblin B", "monsterType": "goblin"},
                             {"type": "npc", "name": "Scout"}]),
        }
        files[encounter_path] = encounter
        for name in pc_names:
            files[f"characters/{name.lower()}.json"] = {"name": name, "hitPoints": 17, "maxHitPoints": 22}
        files["modules/monsters/goblin.json"] = {"name": "Goblin", "maxHitPoints": 7}
        party_tracker = {"active_character": pc_names[0], "partyNPCs": [{"name": "Scout", "role": "Guide"}]}
        cached_history = {"history": []}

        class PathManager:
            module_dir = "modules/current_module"

            def get_character_path(self, name):
                value = f"characters/{name}.json"
                events.append(("character_path", name, value))
                return value

            def get_monster_path(self, name):
                value = f"modules/monsters/{name}.json"
                events.append(("monster_path", name, value))
                return value

        class Manager:
            combat_phase = "PC_PHASE"
            current_round = 4

            def initialize_turn_queue(self, current_encounter):
                events.append(("initialize_turn_queue", current_encounter))

            def sync_committed_turn_state(self, current_encounter):
                events.append(("sync_committed_turn_state", current_encounter))
                self.current_round = current_encounter.get(
                    "combat_round", current_encounter.get("current_round", 1)
                )
                self.combat_phase = current_encounter.get(
                    "combat_phase",
                    "ENEMY_PHASE"
                    if current_encounter.get("openingEnemyBatchPending") is True
                    else "PC_PHASE",
                )
                return self.combat_phase

        manager = cached_manager or Manager()

        def safe_load(path):
            events.append(("read", path))
            if path == encounter_path and encounter_failure is not None:
                raise encounter_failure
            if path == f"characters/{missing_character}.json":
                return None
            return files.get(path)

        def save(path, value):
            events.append(("write", path))
            saves.append((path, value))

        history_dependencies = CombatHistoryDependencies(
            exists=lambda path: events.append(("history_exists", path)) or False,
            getsize=lambda path: events.append(("history_size", path)) or 0,
            load_json=lambda path: events.append(("history_read", path)) or cached_history["history"],
            read_prompt=lambda path: events.append(("read_prompt", path)) or "fresh system prompt [PC_LIST]",
            save_json=save,
            format_character=lambda info, **kwargs: f"PC:{info['name']}",
            format_npc=lambda info, role: f"NPC:{info['name']}:{role}",
            filter_dynamic_fields=lambda value: value,
            filter_encounter=lambda value: value,
            log_structure=lambda history: events.append(("history_structure", history)),
            debug=lambda message, **kwargs: events.append(("debug", message)),
            error=lambda message, **kwargs: events.append(("error", message)),
            emit=lambda message: events.append(("history_emit", message)),
            remove=lambda path: events.append(("remove", path)),
        )

        def normalize(current_encounter, disk_party):
            events.append(("normalize", current_encounter, disk_party))
            return current_encounter, True, {"partyRoll": 18, "enemyRoll": 11}

        def get_manager():
            events.append(("get_manager",))
            return cached_manager

        def create_manager(party):
            events.append(("create_manager", party))
            return manager

        def load_npc(name, path_manager):
            events.append(("load_npc", name))
            return {"name": name, "maxHitPoints": 11}, "scout.json"

        dependencies = CombatInitializationDependencies(
            module_path_manager_factory=lambda *args: events.append(("path_manager", args)) or PathManager(),
            safe_json_load=safe_load,
            session_factory=lambda **kwargs: events.append(("session_factory", kwargs)) or _Session(),
            multi_pc_combat_available=True,
            is_multi_pc_enabled=lambda: events.append(("multi_pc_enabled",)) or multipc,
            normalize_phase1_initiative=normalize,
            save_json=save,
            get_combat_manager=get_manager,
            create_combat_manager=create_manager,
            history_file="modules/conversation_history/combat_conversation_history.json",
            second_model_history_file="modules/conversation_history/second_model_history.json",
            third_model_history_file="modules/conversation_history/third_model_history.json",
            history_dependencies=history_dependencies,
            normalize_character_name=lambda name: name.lower(),
            load_npc_with_fuzzy_match=load_npc,
            file_exists=lambda path: events.append(("exists", path)) or True,
            list_directory=lambda path: events.append(("listdir", path)) or ["goblin.json"],
            print_exception=lambda: events.append(("traceback",)),
            emit=lambda message: events.append(("emit", message)),
            debug=lambda message, **kwargs: events.append(("debug", message)),
            info=lambda message, **kwargs: events.append(("info", message)),
            warning=lambda message, **kwargs: events.append(("warning", message)),
            error=lambda message, **kwargs: events.append(("error", message)),
        )
        inputs = CombatInitializationInputs(encounter_id, party_tracker, {"name": "Cave"})
        return inputs, dependencies, events, saves, files, party_tracker, manager, encounter

    def _turn_iteration_fakes(self, *, multipc=False, input_value="attack", eof=False):
        events = []
        pc_names = ("PC1", "PC2", "PC3", "PC4") if multipc else ("PC1",)
        active_pc = "PC4" if multipc else "PC1"
        party = {"active_character": active_pc, "partyMembers": list(pc_names),
                 "worldConditions": {"time": "noon"}}
        encounter = {"encounterId": "turn-e", "creatures": [
            *[{"type": "player", "name": name, "currentHitPoints": 10 + index}
              for index, name in enumerate(pc_names)],
            {"type": "npc", "name": "Scout", "currentHitPoints": 4},
        ]}
        history = [
            {"role": "system", "content": "=== AUTHORITATIVE MULTI-PC STATE (JSON) === old"},
            {"role": "system", "content": "Encounter Details: old"},
            {"role": "system", "content": "NPC Templates: old"},
        ]
        manager = SimpleNamespace(
            current_pc_name="PC1", combat_phase="PC_PHASE", pc_states={},
            set_current_pc=lambda name: (events.append(("set_current_pc", name)), setattr(manager, "current_pc_name", name)),
            get_next_pending_death_save_pc=lambda: None,
            update_pc_hp=lambda name, hp: events.append(("update_pc_hp", name, hp)),
            format_multi_pc_head_context=lambda: "=== AUTHORITATIVE MULTI-PC STATE (JSON) === current",
        )
        if multipc:
            manager.handle_combat_command = lambda *args, **kwargs: (None, None, None, False)

        def safe_load(path):
            events.append(("read", path))
            if path == "party_tracker.json":
                return party
            if path == "modules/encounters/encounter_turn-e.json":
                return encounter
            if path == "characters/pc1.json":
                return {"name": "PC1", "hitPoints": 13, "maxHitPoints": 20}
            if path == "characters/pc2.json":
                return {"name": "PC2", "hitPoints": 19, "maxHitPoints": 25}
            return None

        def read_input(prompt):
            events.append(("input", prompt))
            if eof:
                raise EOFError()
            return input_value

        session = _Session(manager if multipc else None)
        session.active_pc = "PC1"
        session.history = history
        dependencies = CombatTurnIterationDependencies(
            safe_json_load=safe_load,
            perf_counter=lambda: events.append(("clock",)) or 5.0,
            trace_file_operation=lambda *args: events.append(("trace_file", args)),
            trace_set_context=lambda **kwargs: events.append(("trace_context", kwargs)),
            trace_stage=lambda *args: events.append(("trace_stage", args)),
            trace_enabled=lambda: False,
            debug=lambda message, **kwargs: events.append(("debug", message)),
            emit=lambda message: events.append(("emit", message)),
            error=lambda message, **kwargs: events.append(("error", message)),
            update_status=lambda message, processing: events.append(("status", message, processing)),
            sync_active_encounter=lambda *args: events.append(("sync_active",) + args),
            normalize_character_name=lambda name: name.lower(),
            format_character=lambda data, **kwargs: f"PC:{data['name']}",
            load_npc_with_fuzzy_match=lambda name, path: events.append(("load_npc", name)) or ({"name": name}, "scout.json"),
            filter_encounter=lambda data: data,
            filter_dynamic_fields=lambda data: data,
            save_json=lambda path, data: events.append(("save", path, data)),
            read_input=read_input,
            flush=lambda: events.append(("flush",)),
        )
        inputs = CombatTurnIterationInputs(
            session=session, encounter_id="turn-e", encounter_data=encounter,
            multi_pc_manager=manager if multipc else None, party_tracker_data=party,
            path_manager=SimpleNamespace(get_character_path=lambda name: f"characters/{name}.json"),
            json_file_path="modules/encounters/encounter_turn-e.json",
            conversation_history=history, conversation_history_file="history",
            npc_templates={"old.json": {"name": "Old"}},
            player_info={"name": pc_names[-1], "hitPoints": 17, "maxHitPoints": 22},
            player_file=f"characters/{pc_names[-1].lower()}.json", fresh_player_data={"name": pc_names[-1]},
            current_hp=17, max_hp=22,
        )
        return inputs, dependencies, events, manager, party, encounter, history

    def _normal_turn_fakes(self, user_input, *, multipc=False):
        events = []
        party = {"active_character": "PC2", "partyMembers": ["PC1", "PC2"],
                 "worldConditions": {"time": "noon"}}
        encounter = {"encounterId": "turn-e", "creatures": []}
        history = [{"role": "system", "content": "system"}]
        session = _Session()
        session.history = history
        manager = SimpleNamespace(
            current_pc_name="PC2", combat_phase="PC_PHASE", pc_states={},
            get_next_pending_death_save_pc=lambda: None,
            handle_combat_command=lambda *args, **kwargs: events.append(("manager_command",)) or (None, None, None, False),
            set_current_pc=lambda name: events.append(("set_current_pc", name)),
        )
        path_manager = SimpleNamespace(get_character_path=lambda name: f"characters/{name}.json")
        turn_iteration = CombatTurnIterationResult(
            session=session, encounter_data=encounter,
            multi_pc_manager=manager if multipc else None,
            party_tracker_data=party, conversation_history=history, npc_templates={},
            player_file="characters/pc1.json", fresh_player_data={"name": "PC1"},
            current_hp=17, max_hp=22, player_name_display="PC1", current_round_trace_start=1.0,
            user_input_text=user_input,
        )

        def input_phase_gate(*args, **kwargs):
            events.append(("phase_gate",))
            return run_input_phase_gate(*args, **kwargs)

        def fast_stage(**kwargs):
            events.append(("fast_commands",))
            return run_fast_commands_stage(**kwargs)

        def deterministic_stage(**kwargs):
            events.append(("deterministic",))
            return run_deterministic_command_stage(**kwargs)

        def make_phase_io(manager_for_gate):
            return PhaseGateIO(
                emit=lambda text: events.append(("emit", text)),
                flush=lambda: events.append(("flush",)),
                debug=lambda message, **kwargs: events.append(("debug", message)),
                save_json=lambda path, value: events.append(("save", path, value)),
                parse_death_save_roll=lambda text, gate: (False, None, None),
            )

        def make_fast_io():
            return FastCommandIO(
                emit=lambda text: events.append(("emit", text)),
                flush=lambda: events.append(("flush",)),
                debug=lambda message, **kwargs: events.append(("debug", message)),
                warning=lambda message, **kwargs: events.append(("warning", message)),
                save_json=lambda path, value: events.append(("save", path, value)),
                persist_encounter=lambda *args: True,
            )

        def make_deterministic_io(current_path_manager, player_file, session, party_tracker_snapshot):
            return DeterministicCommandIO(
                emit=lambda text: events.append(("emit", text)),
                flush=lambda: events.append(("flush",)),
                load_json=lambda path: ({"active_character": "PC1", "partyMembers": ["PC1"]}
                                         if path == "party_tracker.json" else None),
                save_json=lambda path, value: events.append(("save", path, value)),
                write_json=lambda path, value: events.append(("write", path, value)),
                path_manager=current_path_manager,
                normalize_name=lambda name: name.lower(),
                sync_active_encounter=lambda **kwargs: events.append(("sync_active", kwargs)),
                save_manager_factory=lambda: SimpleNamespace(create_save_game=lambda *args: (True, "saved")),
                summarize_dialogue=lambda *args: "summary",
                generate_chat_history=lambda *args: None,
            )

        def make_stat_io(current_path_manager):
            return CharacterStatCommandIO(
                load_json=lambda path: {"active_character": "PC1", "partyMembers": ["PC1"]}
                if path == "party_tracker.json" else {"experience_points": 4, "level": 1},
                normalize_name=lambda name: name.lower(),
                path_manager=current_path_manager,
                write_json=lambda path, value: events.append(("write", path, value)),
                emit=lambda text: events.append(("emit", text)),
                flush=lambda: events.append(("flush",)),
            )

        def enhance_inventory(inputs):
            events.append(("inventory", inputs.user_input_text))
            return SimpleNamespace(user_input_text=inputs.user_input_text, fresh_player_data=inputs.preexisting_player_data)

        def assemble_context(context_inputs):
            events.append(("context", context_inputs.user_input_text))
            return SimpleNamespace(
                return_early=False, return_value=None, encounter_data=context_inputs.encounter_data,
                player_info={"name": context_inputs.player_name_display},
                player_file="characters/pc1.json", path_manager=context_inputs.path_manager,
                fresh_player_data=context_inputs.pre_context_player_data,
                current_hp=context_inputs.current_hp, max_hp=context_inputs.max_hp,
                user_input_text=context_inputs.user_input_text, user_prompt="enriched user prompt",
            )

        dependencies = CombatNormalTurnDependencies(
            input_phase_gate=input_phase_gate,
            phase_gate_io_factory=make_phase_io,
            initiative_gate=lambda *args: {"handled": False, "error_message": ""},
            fast_command_stage=fast_stage,
            fast_command_io_factory=make_fast_io,
            deterministic_command_stage=deterministic_stage,
            deterministic_command_io_factory=make_deterministic_io,
            character_stat_command=run_character_stat_command,
            character_stat_io_factory=make_stat_io,
            normalize_character_name=lambda name: name.lower(),
            safe_json_load=lambda path: None,
            pc_action_enabled=True,
            perf_counter=lambda: events.append(("decision_clock",)) or 3.0,
            trace_decision=lambda *args, **kwargs: events.append(("decision_trace", args)),
            enhance_inventory_context=enhance_inventory,
            enhance_player_input_with_inventory=lambda text, *args, **kwargs: text,
            assemble_context=assemble_context,
            clean_old_dm_notes=lambda messages: events.append(("clean_notes",)) or messages,
            clean_combat_state_blocks=lambda messages: events.append(("clean_blocks",)) or messages,
            save_json=lambda path, value: events.append(("save", path, value)),
            debug=lambda message, **kwargs: events.append(("debug", message)),
            emit=lambda message: events.append(("emit", message)),
            flush=lambda: events.append(("flush",)),
        )
        inputs = CombatNormalTurnInputs(
            iteration=turn_iteration, encounter_id="turn-e",
            json_file_path="modules/encounters/encounter_turn-e.json",
            conversation_history_file="history", location_info={"name": "Cave"},
        )
        return inputs, dependencies, events, session, manager, history

    def test_fresh_fast_lane_has_zero_compress_provider_validation_or_write_calls(self):
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes()
        session = _Session()
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=[{"role": "system", "content": "fresh"}], history_file="history",
                is_resuming=False, encounter_data={"awaitingPcGroupRoll": True},
                party_tracker_data={"partyMembers": ["A", "B", "C", "D"], "active_character": "A"},
                multi_pc_manager=SimpleNamespace(), dynamic_state="unchanged dynamic state",
                preroll_text="cached rolls", session=session, temperature_used=0.63,
            ),
            dependencies,
        )
        self.assertTrue(result.is_fast_lane)
        self.assertIs(result.session, session)
        self.assertEqual(result.temperature_used, 0.63)
        self.assertEqual((requests, compressed, validations, saves, usage), ([], [], [], [], []))
        self.assertFalse(any(event[0] in ("save", "export", "request") for event in events))
        self.assertFalse(any(event[0] == "observer_factory" for event in events))
        self.assertIn(
            ("emit", "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Combat initiated. Initiative pending. Enter /init <1-20> to begin combat."),
            events,
        )
        self.assertEqual([event[0] for event in events], ["info", "emit", "flush", "debug"])

    def test_resume_gpt5_keeps_request_shape_history_order_log_and_output(self):
        response_text = '{"narration":"The battle resumes."}'
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            [response_text], gpt5=True
        )
        history = [{"role": "system", "content": "Current Combat Encounter: e-1"}]
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=history, history_file="history", is_resuming=True,
                encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                dynamic_state="unchanged", preroll_text="unchanged", session=_Session(),
                temperature_used=0.63,
            ),
            dependencies,
        )
        expected_resume_prompt = (
            "Dungeon Master Note: The game session is resuming after a pause. The player has returned. "
            "Please provide a brief narration to re-establish the scene and prompt the player for their next action, "
            "based on the last known state from the conversation history."
        )
        self.assertEqual(result.temperature_used, 0.63)
        self.assertEqual([message["role"] for message in history], ["system", "user", "assistant"], events)
        self.assertEqual(history[1]["content"], expected_resume_prompt)
        self.assertEqual([path for path, _ in saves], ["history", "history"])
        self.assertEqual(sum(event[0] == "export" for event in events), 0)
        self.assertEqual(requests[0]["messages"], history[:2])
        self.assertEqual(requests[0]["task"], "combat_main")
        self.assertIs(requests[0]["json_output"], False)
        self.assertNotIn("model", requests[0])
        self.assertEqual(outputs, ["Dungeon Master: The battle resumes."])
        self.assertEqual(len(usage), 1)
        self.assertEqual(len(validations), 0)
        self.assertTrue(any(event[0] == "warning" and "usage" in event[1] for event in events))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ["USAGE_TRACKING: Failed to track startup response: fake usage sink unavailable"])
        api_log = next(event for event in events if event[0] == "api_log")
        self.assertEqual({key: value for key, value in api_log[2]["metadata"].items()
                          if key != "legacy_context_model"},
                         {"branch": "gpt5", "context": "re-engage"})
        self.assertEqual(outputs, ["Dungeon Master: The battle resumes."])
        self.assertIn(("flush",), events)
        self.assertEqual(
            [event[0] for event in events],
            [
                "emit", "debug", "emit", "debug", "emit", "save", "emit", "debug", "emit", "emit",
                "clock", "observer_factory", "request", "trace_provider", "api_log",
                "usage", "warning", "debug", "emit", "save", "emit", "flush", "debug", "emit",
            ],
        )

    def test_resume_legacy_sends_temperature_override_and_metadata(self):
        response_text = '{"narration":"Legacy resume."}'
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            [response_text], gpt5=False, temperature=0.63
        )
        history = [{"role": "system", "content": "Existing"}]
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=history, history_file="history", is_resuming=True,
                encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                dynamic_state="d", preroll_text="p", session=_Session(), temperature_used=None,
            ),
            dependencies,
        )
        self.assertEqual(result.temperature_used, 0.63)
        self.assertEqual(requests[0]["task"], "combat_main")
        self.assertEqual(requests[0]["temperature"], 0.63)
        self.assertNotIn("model", requests[0])
        self.assertNotIn("timeout", requests[0])
        self.assertEqual(outputs, ["Dungeon Master: Legacy resume."])
        api_log = next(event for event in events if event[0] == "api_log")
        self.assertEqual({key: value for key, value in api_log[2]["metadata"].items()
                          if key != "legacy_context_model"},
                         {"temperature": 0.63, "branch": "gpt4.1", "context": "re-engage"})

    def test_initial_scene_retries_invalid_json_then_validates_with_owner_inputs(self):
        response = '{"narration":"A valid scene.","combat_round":1,"actions":[]}'
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            ["not json", response], validation=True
        )
        session = _Session()
        history = [{"role": "system", "content": "fresh head"}]
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=history, history_file="history", is_resuming=False,
                encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                dynamic_state="dynamic byte string", preroll_text="preroll byte string",
                session=session, temperature_used=0.63,
            ),
            dependencies,
        )
        self.assertFalse(result.return_early)
        self.assertEqual(result.temperature_used, 0.53)
        self.assertIs(result.session, session)
        self.assertEqual(result.initial_conversation_length, 2)
        self.assertEqual(result.narration, "A valid scene.")
        self.assertEqual([request["temperature"] for request in requests], [0.63, 0.53])
        self.assertTrue(all(request["task"] == "combat_main" and request["json_output"] is False for request in requests))
        self.assertTrue(all("timeout" not in request and "model" not in request for request in requests))
        self.assertEqual(requests[0]["messages"][-1]["role"], "user")
        self.assertEqual(requests[1]["messages"][-1]["content"], "Invalid JSON format. Please try again.")
        self.assertEqual(requests[0]["messages"], history[:2])
        self.assertEqual(requests[1]["messages"][:-1], history[:2])
        self.assertEqual(validations[0][2], result.initial_prompt_text)
        self.assertIs(validations[0][4], None)
        self.assertEqual(session.calls[0][0], "bind_history")
        self.assertEqual(result.history[-1], {"role": "assistant", "content": response})
        self.assertEqual(outputs, ["Dungeon Master: A valid scene."])
        self.assertEqual(len(usage), 2)
        self.assertEqual(compressed, [])
        self.assertEqual([request["task"] for request in requests], ["combat_main", "combat_main"])
        self.assertEqual(len(warnings), 2)
        self.assertEqual(sum(event[0] == "export" for event in events), 0)
        self.assertEqual([path for path, _ in saves], ["history", "history"])
        attempt_events = [
            "temperature", "clock", "trace_stage", "clock", "observer_factory", "request",
            "trace_provider", "usage", "warning",
        ]
        self.assertEqual(
            [event[0] for event in events],
            ["debug", "initiative", "save"] + attempt_events + attempt_events + [
                "clock", "validate", "trace_stage", "save", "emit", "flush",
            ],
        )

    def test_initial_scene_multipc_keeps_initiative_handoff_and_active_pc_prompt(self):
        response = '{"narration":"The party faces the goblin.","combat_round":1,"actions":[]}'
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            [response]
        )
        manager = SimpleNamespace(
            current_pc_name="Acheron", party_initiative=0, enemy_initiative=0, party_goes_first=False
        )
        party = {"active_character": "Acheron"}
        encounter = {"creatures": [], "initiativeRolls": {"pcGroup": 17, "dmGroup": 12}, "initiativeWinner": "pcGroup"}
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=[{"role": "system", "content": "multi-pc head"}],
                history_file="history", is_resuming=False, encounter_data=encounter,
                party_tracker_data=party, multi_pc_manager=manager, dynamic_state="fixed dynamic state",
                preroll_text="fixed prerolls", session=_Session(), temperature_used=None,
            ),
            dependencies,
        )
        initial_user_prompt = requests[0]["messages"][-1]["content"]
        self.assertIn("group-initiative-narrative", initial_user_prompt)
        self.assertIn("Initiative Order: initiative-order", initial_user_prompt)
        self.assertIn("ACTIVE:Acheron", initial_user_prompt)
        self.assertEqual(manager.party_initiative, 17)
        self.assertEqual(manager.enemy_initiative, 12)
        self.assertTrue(manager.party_goes_first)
        self.assertEqual(result.initiative_order, "initiative-order")

    def test_initial_validation_exhaustion_uses_last_response_and_retry_feedback(self):
        responses = [
            '{"narration":"one","combat_round":1,"actions":[]}',
            '{"narration":"two","combat_round":1,"actions":[]}',
            '{"narration":"three","combat_round":1,"actions":[]}',
        ]
        validations_outcomes = ["fix one", "fix two", "last feedback"]
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            responses, validation=validations_outcomes
        )
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=[{"role": "system", "content": "fresh"}], history_file="history",
                is_resuming=False, encounter_data={"creatures": []}, party_tracker_data={},
                multi_pc_manager=None, dynamic_state="d", preroll_text="p", session=_Session(),
                temperature_used=None,
            ),
            dependencies,
        )
        self.assertFalse(result.return_early)
        self.assertEqual(result.initial_response, responses[-1])
        self.assertEqual(result.retry_feedback_note, "fix two")
        self.assertEqual([request["messages"][-1]["content"] for request in requests[1:]], ["fix one", "fix two"])
        self.assertEqual(outputs, ["Dungeon Master: three"])
        self.assertEqual(len(validations), 3)

    def test_resume_does_not_duplicate_an_already_trailing_resume_prompt(self):
        response_text = '{"narration":"Continue."}'
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            [response_text], gpt5=True
        )
        prompt = (
            "Dungeon Master Note: The game session is resuming after a pause. The player has returned. "
            "Please provide a brief narration to re-establish the scene and prompt the player for their next action, "
            "based on the last known state from the conversation history."
        )
        history = [{"role": "user", "content": prompt}]
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=history, history_file="history", is_resuming=True,
                encounter_data={}, party_tracker_data={}, multi_pc_manager=None,
                dynamic_state="d", preroll_text="p", session=_Session(), temperature_used=0.63,
            ),
            dependencies,
        )
        self.assertEqual(len(result.history), 2)
        self.assertEqual(len(saves), 1)
        self.assertEqual(result.history[0]["content"], prompt)
        self.assertTrue(any(event[0] == "debug" and "already exists" in event[1] for event in events))

    def test_initial_provider_abort_returns_legacy_tuple_and_preserves_append_cleanup(self):
        dependencies, events, requests, compressed, validations, saves, errors, warnings, outputs, usage = self._startup_fakes(
            [RuntimeError("provider unavailable")] * 3
        )
        session = _Session()
        history = [{"role": "system", "content": "fresh"}]
        result = run_startup_narrative(
            CombatStartupNarrativeInputs(
                history=history, history_file="history", is_resuming=False,
                encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                dynamic_state="d", preroll_text="p", session=session, temperature_used=0.63,
            ),
            dependencies,
        )
        self.assertTrue(result.return_early)
        self.assertEqual(result.return_value, (None, None))
        self.assertIs(result.session, session)
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(errors), 4)
        self.assertEqual([message["role"] for message in result.history], ["system", "user"])
        self.assertEqual(session.calls[0][0], "bind_history")
        self.assertEqual(outputs, [])

    def test_terminal_startup_errors_escape_resume_and_initial_scene_before_fallback_or_cleanup(self):
        from utils.llm_router import GameLLMTerminalError

        for terminal_kind in ("quota", "refusal", "content_filter"):
            for is_resuming in (True, False):
                with self.subTest(is_resuming=is_resuming, terminal=terminal_kind):
                    dependencies, events, requests, _compressed, _validations, saves, _errors, _warnings, outputs, _usage = self._startup_fakes(
                        [GameLLMTerminalError(terminal_kind)]
                    )
                    history = [{"role": "system", "content": "existing"}]
                    session = _Session()
                    with self.assertRaises(GameLLMTerminalError):
                        run_startup_narrative(
                            CombatStartupNarrativeInputs(
                                history=history, history_file="history", is_resuming=is_resuming,
                                encounter_data={"creatures": []}, party_tracker_data={}, multi_pc_manager=None,
                                dynamic_state="d", preroll_text="p", session=session,
                            ),
                            dependencies,
                        )
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(requests[0]["task"], "combat_main")
                    self.assertIs(requests[0]["json_output"], False)
                    self.assertFalse(any(message.get("role") == "assistant" for message in history))
                    self.assertEqual(outputs, [])
                    if is_resuming:
                        self.assertEqual([event[0] for event in events].count("save"), 1)
                        self.assertEqual(len(saves), 1)
                    else:
                        self.assertFalse(any(call[0] == "bind_history" for call in session.calls))
                        self.assertEqual([event[0] for event in events].count("save"), 1)

    def test_current_owner_bindings_and_explicit_result_contract_are_source_anchored(self):
        import ast
        from pathlib import Path
        source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        initialization_builder = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_build_combat_initialization_dependencies"
        )
        initialization_bindings = ast.get_source_segment(source, initialization_builder)
        self.assertIn("normalize_phase1_initiative=normalize_phase1_initiative", initialization_bindings)
        self.assertIn("get_combat_manager=get_combat_manager", initialization_bindings)
        self.assertIn("create_combat_manager=create_combat_manager", initialization_bindings)
        self.assertIn("load_npc_with_fuzzy_match=load_npc_with_fuzzy_match", initialization_bindings)
        self.assertIn("safe_json_load=safe_json_load", initialization_bindings)
        builder = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_build_startup_narrative_dependencies")
        source_segment = ast.get_source_segment(source, builder)
        self.assertIn("client=client", source_segment)
        self.assertNotIn("compressor=", source_segment)
        self.assertIn("completion_params=get_chat_completion_params", source_segment)
        self.assertIn("validate_response=validate_combat_response", source_segment)
        iteration_builder = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_build_turn_iteration_dependencies"
        )
        iteration_bindings = ast.get_source_segment(source, iteration_builder)
        self.assertIn("safe_json_load=safe_json_load", iteration_bindings)
        self.assertIn("sync_active_encounter=sync_active_encounter", iteration_bindings)
        normal_builder = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_build_normal_turn_dependencies"
        )
        normal_bindings = ast.get_source_segment(source, normal_builder)
        self.assertIn("run_fast_commands_stage", normal_bindings)
        self.assertIn("run_deterministic_command_stage", normal_bindings)
        self.assertIn("run_character_stat_command", normal_bindings)
        self.assertIn("client=client", source_segment)
        self.assertEqual(
            list(inspect.signature(run_startup_narrative).parameters),
            ["inputs", "dependencies"],
        )
        owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal")
        init_calls = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "initialize_combat_session"
        ]
        self.assertEqual(len(init_calls), 1)
        init_result_fields = {node.attr for node in ast.walk(owner) if isinstance(node, ast.Attribute)}
        self.assertTrue({
            "encounter_data", "path_manager", "session", "multi_pc_manager",
            "conversation_history", "is_resuming", "player_info", "player_file",
            "monster_templates", "npc_templates", "return_early", "return_value",
        }.issubset(init_result_fields))
        calls = [node for node in ast.walk(owner) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_startup_narrative"]
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(isinstance(node, ast.Attribute) and node.attr == "temperature_used" for node in ast.walk(owner)))
        self.assertTrue(any(isinstance(node, ast.Attribute) and node.attr == "return_value" for node in ast.walk(owner)))
        self.assertEqual(
            list(inspect.signature(initialize_combat_session).parameters),
            ["inputs", "dependencies"],
        )
        owner_calls = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        owner_order = (
            "begin_combat_turn_iteration", "prepare_combat_normal_turn", "run_combat_provider_retry_stage",
            "trace_combat_action_batch_metadata", "process_combat_action_batch",
            "stage_combat_turn_snapshot", "_commit_normal_combat_turn",
            "sync_committed_combat_turn", "publish_combat_narration", "finalize_combat_session",
        )
        call_positions = []
        for name in owner_order:
            matching = [call for call in owner_calls if call.func.id == name]
            self.assertEqual(len(matching), 1, name)
            call_positions.append(matching[0].lineno)
        self.assertEqual(call_positions, sorted(call_positions))
        self.assertEqual(
            list(inspect.signature(begin_combat_turn_iteration).parameters),
            ["inputs", "dependencies"],
        )
        owner_calls = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        positions = {}
        for call_name in (
            "initialize_combat_session", "prepare_initial_combat_state", "run_startup_narrative",
            "begin_combat_turn_iteration", "prepare_combat_normal_turn", "run_combat_provider_retry_stage",
            "trace_combat_action_batch_metadata", "process_combat_action_batch",
            "stage_combat_turn_snapshot", "_commit_normal_combat_turn",
            "sync_committed_combat_turn", "publish_combat_narration", "finalize_combat_session",
        ):
            matches = [call for call in owner_calls if call.func.id == call_name]
            self.assertEqual(len(matches), 1, call_name)
            positions[call_name] = matches[0].lineno
        expected_order = [
            "initialize_combat_session", "prepare_initial_combat_state", "run_startup_narrative",
            "begin_combat_turn_iteration", "prepare_combat_normal_turn", "run_combat_provider_retry_stage",
            "trace_combat_action_batch_metadata", "process_combat_action_batch",
            "stage_combat_turn_snapshot", "_commit_normal_combat_turn",
            "sync_committed_combat_turn", "publish_combat_narration", "finalize_combat_session",
        ]
        self.assertEqual([positions[name] for name in expected_order], sorted(positions.values()))

    def test_initialization_one_and_four_pc_cache_round_history_and_read_order(self):
        for party_size, expected_active, expect_reuse in ((1, "Acheron", False), (4, "PC4", True)):
            with self.subTest(party_size=party_size):
                pc_names = ("Acheron",) if party_size == 1 else ("Acheron", "PC2", "PC3", "PC4")
                cached_manager = None
                inputs, dependencies, events, saves, files, party_tracker, manager, encounter = self._initialization_fakes(
                    pc_names, cached_manager=cached_manager
                )
                session = _Session(manager if expect_reuse else None)
                session.active_pc = "stale-pc"
                party_tracker["active_character"] = expected_active
                if expect_reuse:
                    inputs = CombatInitializationInputs(inputs.encounter_id, party_tracker, inputs.location_info, session)
                    dependencies = dataclass_replace(
                        dependencies,
                        get_combat_manager=lambda: (events.append(("get_manager",)), manager)[1],
                    )
                else:
                    dependencies = dataclass_replace(dependencies, session_factory=lambda **kwargs: session)
                result = initialize_combat_session(inputs, dependencies)
                self.assertFalse(result.return_early)
                self.assertIs(result.session, session)
                self.assertIs(result.encounter_data, encounter)
                self.assertIs(session.encounter, encounter)
                self.assertIs(result.conversation_history, session.history)
                self.assertEqual(result.is_multipc, True)
                self.assertEqual(result.is_resuming, False)
                self.assertEqual(session.active_pc, expected_active)
                self.assertEqual(result.player_info["name"], expected_active)
                self.assertEqual(result.player_file, f"characters/{expected_active.lower()}.json")
                self.assertEqual(result.player_info["hitPoints"], 17)
                self.assertEqual(result.player_info["maxHitPoints"], 22)
                self.assertEqual(result.monster_templates, {"goblin": files["modules/monsters/goblin.json"]})
                self.assertEqual(result.npc_templates, {"scout.json": {"name": "Scout", "maxHitPoints": 11}})
                self.assertEqual(manager.current_round, 4)
                self.assertEqual(manager.combat_phase, "PC_PHASE")
                self.assertEqual(party_tracker["worldConditions"]["combatInitiative"], {"partyRoll": 18, "enemyRoll": 11})
                self.assertEqual([path for path, _ in saves[:4]], [
                    "modules/encounters/encounter_fixture-encounter.json",
                    "party_tracker.json",
                    "modules/conversation_history/second_model_history.json",
                    "modules/conversation_history/third_model_history.json",
                ])
                event_kinds = [event[0] for event in events]
                ordered_markers = [
                    lambda event: event[:2] == ("read", "party_tracker.json"),
                    lambda event: event[0] == "path_manager",
                    lambda event: event[:2] == ("read", "modules/encounters/encounter_fixture-encounter.json"),
                    lambda event: event[0] == "normalize",
                    lambda event: event[:2] == ("write", "modules/encounters/encounter_fixture-encounter.json"),
                    lambda event: event[:2] == ("write", "party_tracker.json"),
                    *([] if expect_reuse else [lambda event: event[0] == "get_manager"]),
                    lambda event: event[0] == "initialize_turn_queue",
                    lambda event: event[0] == "sync_committed_turn_state",
                    lambda event: event[0] == "history_exists",
                    lambda event: event[0] == "read_prompt",
                    lambda event: event[0] == "history_emit",
                    lambda event: event[:2] == ("write", "modules/conversation_history/second_model_history.json"),
                    lambda event: event[:2] == ("write", "modules/conversation_history/third_model_history.json"),
                    lambda event: event[0] == "character_path",
                ]
                positions = []
                for match in ordered_markers:
                    found = next((i for i, event in enumerate(events) if match(event)), None)
                    self.assertIsNotNone(found, events)
                    positions.append(found)
                self.assertEqual(positions, sorted(positions))
                self.assertEqual(sum(event[0] == "read" and event[1] == "modules/monsters/goblin.json" for event in events), 1)
                self.assertEqual(sum(event[0] == "load_npc" for event in events), 1)
                self.assertEqual(sum(event[0] == "create_manager" for event in events), 0 if expect_reuse else 1)
                self.assertEqual(sum(event[0] == "get_manager" for event in events), 0 if expect_reuse else 1)
                self.assertEqual(sum(event[0] == "initialize_turn_queue" for event in events), 1)
                self.assertEqual(sum(event[0] == "sync_committed_turn_state" for event in events), 1)
                self.assertEqual(session.calls.count(("bind_history", result.conversation_history)), 1)

    def test_restart_bootstrap_hands_off_durable_phase_and_round_without_advancing(self):
        (
            inputs,
            dependencies,
            events,
            _saves,
            _files,
            _party_tracker,
            manager,
            encounter,
        ) = self._initialization_fakes(
            ("Acheron", "Merisiel", "Kira", "Vitreol")
        )
        receipt = {
            "schema_version": 1,
            "turn_id": "00000000-0000-4000-8000-000000000001",
            "applied_id": "sha256:" + "a" * 64,
            "encounter_id": inputs.encounter_id,
            "combat_round": 5,
            "commit_timestamp": "2026-10-26T12:34:56Z",
        }
        encounter.update({
            "combat_round": 5,
            "current_round": 5,
            "combat_phase": "PC_PHASE",
            "openingEnemyBatchPending": False,
            "turn_receipts": [receipt],
        })
        session = _Session(manager)
        inputs = CombatInitializationInputs(
            inputs.encounter_id,
            inputs.party_tracker_data,
            inputs.location_info,
            session,
        )

        result = initialize_combat_session(inputs, dependencies)

        self.assertFalse(result.return_early)
        self.assertEqual(manager.current_round, 5)
        self.assertEqual(manager.combat_phase, "PC_PHASE")
        self.assertEqual(session.phase, "PC_PHASE")
        self.assertEqual(session.encounter["turn_receipts"], [receipt])
        self.assertEqual(
            sum(event[0] == "sync_committed_turn_state" for event in events), 1
        )
        sync_event = next(
            event for event in events if event[0] == "sync_committed_turn_state"
        )
        self.assertEqual(sync_event[1]["combat_round"], 5)
        self.assertEqual(sync_event[1]["turn_receipts"], [receipt])

    def test_initialization_encounter_abort_does_not_create_session_or_write(self):
        inputs, dependencies, events, saves, files, party_tracker, manager, encounter = self._initialization_fakes(
            encounter_failure=ValueError("bad encounter json")
        )
        session = _Session(manager)
        inputs = CombatInitializationInputs(inputs.encounter_id, party_tracker, inputs.location_info, session)
        result = initialize_combat_session(inputs, dependencies)
        self.assertTrue(result.return_early)
        self.assertEqual(result.return_value, (None, None))
        self.assertIs(result.session, session)
        self.assertEqual(session.calls, [])
        self.assertEqual([event[1] for event in events if event[0] == "read"], [
            "party_tracker.json", "modules/encounters/encounter_fixture-encounter.json"
        ])
        self.assertEqual(saves, [])
        self.assertFalse(any(event[0] in ("history_exists", "read_prompt", "character_path") for event in events))

    def test_initialization_missing_character_returns_after_resets_without_monster_reads(self):
        inputs, dependencies, events, saves, files, party_tracker, manager, encounter = self._initialization_fakes(
            missing_character="acheron", multipc=False
        )
        result = initialize_combat_session(inputs, dependencies)
        self.assertTrue(result.return_early)
        self.assertEqual(result.return_value, (None, None))
        self.assertTrue(result.is_multipc is False)
        self.assertEqual([path for path, _ in saves], [
            "modules/conversation_history/second_model_history.json",
            "modules/conversation_history/third_model_history.json",
        ])
        self.assertNotIn("modules/monsters/goblin.json", [event[1] for event in events if event[0] == "read"])
        self.assertIs(result.session.history, result.conversation_history)

    def test_initial_prompt_state_refreshes_hp_conditions_roster_round_and_preroll_in_order(self):
        events = []
        player = {
            "name": "Acheron", "hitPoints": 18, "maxHitPoints": 24, "status": "alive",
            "condition": "prone", "condition_affected": ["prone"],
            "spellcasting": {"spellSlots": {"level1": {"current": 1, "max": 2}}},
        }
        encounter = {
            "combat_round": 4,
            "creatures": [
                {"type": "player", "name": "Acheron"},
                {"type": "npc", "name": "Scout", "currentHitPoints": 5, "status": "alive"},
                {"type": "enemy", "name": "Goblin", "currentHitPoints": 3, "maxHitPoints": 7, "status": "alive"},
            ],
        }
        dependencies = InitialCombatStateDependencies(
            normalize_character_name=lambda name: name.lower(),
            safe_json_load=lambda path: events.append(("read", path)) or player,
            load_npc_with_fuzzy_match=lambda name, paths: events.append(("npc", name)) or ({"maxHitPoints": 9}, "scout.json"),
            collect_authoritative_combat_roster=lambda data, **kwargs: events.append(("roster", kwargs)) or [
                {"name": "Acheron", "type": "player"},
                {"name": "Scout", "type": "npc"},
                {"name": "Goblin", "type": "enemy"},
            ],
            generate_prerolls=lambda data, **kwargs: events.append(("prerolls", kwargs)) or "roll bundle",
            save_json=lambda path, data: events.append(("save", path, data)),
            random_int=lambda low, high: events.append(("random", low, high)) or 4321,
            debug=lambda message, **kwargs: events.append(("debug", message)),
            error=lambda message, **kwargs: events.append(("error", message)),
        )
        result = prepare_initial_combat_state(
            InitialCombatStateInputs(
                encounter_data=encounter,
                player_info=player,
                path_manager=SimpleNamespace(get_character_path=lambda name: f"characters/{name}.json"),
                multi_pc_manager=SimpleNamespace(current_pc_name="Acheron"),
                party_tracker_data={"active_character": "Acheron"},
                json_file_path="modules/encounters/e-1.json",
            ),
            dependencies,
        )
        self.assertEqual(result.current_hp, 18)
        self.assertEqual(result.max_hp, 24)
        self.assertIs(result.fresh_player_data, player)
        self.assertEqual(result.player_file, "characters/acheron.json")
        self.assertEqual(result.current_round, 4)
        self.assertEqual(result.preroll_text, "roll bundle")
        self.assertIn("Acheron: HP 18/24, alive, prone, conditions: prone, Spell Slots: L1:1/2", result.dynamic_state)
        self.assertIn("Scout: HP 5/9, alive", result.dynamic_state)
        self.assertIn("Goblin: HP 3/7, alive", result.dynamic_state)
        self.assertIn("++ VALID TARGETS & ACTORS (IMMUTABLE) ++", result.dynamic_state)
        self.assertEqual(encounter["preroll_cache"], {"round": 4, "rolls": "roll bundle", "preroll_id": "4-4321"})
        self.assertEqual([event[0] for event in events], ["read", "npc", "roster", "prerolls", "random", "save", "debug"])

    def test_turn_iteration_preserves_one_and_four_pc_actor_hp_history_and_input_handoffs(self):
        for party_size, multipc, active_pc in ((1, False, "PC1"), (4, True, "PC4")):
            with self.subTest(party_size=party_size):
                inputs, dependencies, events, manager, party, encounter, history = self._turn_iteration_fakes(
                    multipc=multipc, input_value="attack goblin"
                )
                session = inputs.session
                result = begin_combat_turn_iteration(inputs, dependencies)
                self.assertIs(result.session, session)
                self.assertIs(result.conversation_history, history)
                self.assertIs(result.encounter_data, encounter)
                self.assertEqual(result.user_input_text, "attack goblin")
                self.assertEqual(result.player_file, f"characters/{active_pc.lower()}.json")
                self.assertEqual((result.current_hp, result.max_hp), (17, 22))
                self.assertEqual(session.active_pc, active_pc)
                self.assertEqual(result.current_round_trace_start, 5.0)
                self.assertEqual(
                    result.party_tracker_data["active_character"],
                    active_pc,
                )
                self.assertEqual(sum(event[0] == "save" for event in events), 1)
                self.assertEqual(
                    sum(event == ("read", "party_tracker.json") for event in events),
                    1,
                )
                self.assertEqual(session.turn_iteration_id, 1)
                self.assertLess(
                    next(i for i, event in enumerate(events) if event[0] == "sync_active"),
                    next(i for i, event in enumerate(events) if event[0] == "save"),
                )
                if multipc:
                    self.assertEqual([event[1:] for event in events if event[0] == "update_pc_hp"],
                                     [(name, 10 + index) for index, name in enumerate(("PC1", "PC2", "PC3", "PC4"))])
                    self.assertEqual(manager.current_pc_name, "PC4")
                self.assertEqual(next(event for event in events if event[0] == "input")[1],
                                 f"[noon][HP:17/22][XP:0/0] {active_pc}: ")

    def test_turn_iteration_eof_returns_structured_quit_at_the_original_input_point(self):
        inputs, dependencies, events, manager, party, encounter, history = self._turn_iteration_fakes(eof=True)
        result = begin_combat_turn_iteration(inputs, dependencies)
        self.assertTrue(result.return_early)
        self.assertEqual(result.return_value.control_action, "quit")
        self.assertEqual(result.return_value.status, "exit_requested")
        self.assertEqual(result.return_value.reason, "input_eof")
        self.assertEqual(result.return_value.exit_code, 0)
        self.assertLess(
            next(i for i, event in enumerate(events) if event[0] == "input"),
            next(i for i, event in enumerate(events) if event[0] == "error"),
        )

    def test_normal_turn_quit_and_fast_command_preserve_early_control_edges(self):
        quit_inputs, quit_dependencies, quit_events, quit_session, _, _ = self._normal_turn_fakes("/quit")
        quit_result = prepare_combat_normal_turn(quit_inputs, quit_dependencies)
        self.assertEqual(quit_result.control_action, "exit_requested")
        self.assertEqual(quit_result.return_value.status, "exit_requested")
        self.assertFalse(any(event[0] == "context" for event in quit_events))

        switch_inputs, switch_dependencies, switch_events, switch_session, _, _ = self._normal_turn_fakes(
            "/switch_pc_focus"
        )
        switch_result = prepare_combat_normal_turn(switch_inputs, switch_dependencies)
        self.assertEqual(switch_result.control_action, "continue")
        self.assertTrue(any(event[0] == "fast_commands" for event in switch_events))
        self.assertFalse(any(event[0] in ("deterministic", "context") for event in switch_events))

    def test_normal_turn_parser_miss_flows_to_prompt_and_history_in_legacy_order(self):
        inputs, dependencies, events, session, manager, history = self._normal_turn_fakes(
            "I inspect the stone archway carefully.", multipc=True
        )
        real_decision = combat_decisions.run_pc_action_decision

        def parser_miss(**kwargs):
            def parse(*args, **parse_kwargs):
                events.append(("parser", args[0], parse_kwargs.get("actor_name")))
                return {"handled": False, "fallback_reason": "unrecognized_action"}

            def apply(*args, **apply_kwargs):
                events.append(("apply",))
                return False

            return real_decision(**kwargs, parser_loader=lambda: (parse, apply))

        with patch.object(combat_decisions, "run_pc_action_decision", parser_miss):
            result = prepare_combat_normal_turn(inputs, dependencies)
        self.assertEqual(result.control_action, "proceed")
        self.assertIs(result.session, session)
        accepted_record = result.conversation_history[-1]
        self.assertEqual(
            {key: value for key, value in accepted_record.items() if key != "turn_id"},
            {"role": "user", "content": "enriched user prompt"},
        )
        self.assertEqual(str(uuid.UUID(accepted_record["turn_id"])), accepted_record["turn_id"])
        self.assertIs(session.history, result.conversation_history)
        self.assertEqual(result.user_input_text, "I inspect the stone archway carefully.")
        self.assertEqual(result.context_result.user_prompt, "enriched user prompt")
        self.assertEqual([event[0] for event in events if event[0] in {
            "phase_gate", "fast_commands", "manager_command", "deterministic", "decision_clock",
            "parser", "decision_trace", "inventory", "context", "clean_notes", "clean_blocks", "save",
        }], [
            "phase_gate", "fast_commands", "manager_command", "deterministic", "decision_clock",
            "parser", "decision_trace", "inventory", "context", "clean_notes", "clean_blocks", "save",
        ])
        self.assertTrue(any(event[0] == "decision_trace" and event[1][1] == "llm_fallback" for event in events))

    def test_end_of_combat_finalization_summarizes_before_cleanup_and_history_write(self):
        events = []
        tracker = {"worldConditions": {"activeCombatEncounter": "E-1"}}
        history = [{"role": "assistant", "content": "last turn"}]
        deps = CombatFinalizationDependencies(
            summarize_dialogue=lambda h, location, party: events.append(("summary", party["worldConditions"]["activeCombatEncounter"])) or "summary",
            safe_write_json=lambda path, value: events.append(("write", path, value["worldConditions"].copy())),
            generate_chat_history=lambda h, encounter: events.append(("chat_history", encounter)),
            safe_json_load=lambda path: events.append(("reload_player", path)) or {"name": "A"},
            log_info=lambda message, **kwargs: events.append(("info", message)),
            log_debug=lambda message, **kwargs: events.append(("debug", message)),
        )
        result = finalize_combat_session(
            CombatFinalizationInputs(tracker, history, {"name": "Cave"}, "E-1", "characters/a.json"),
            deps,
        )
        self.assertEqual((result.dialogue_summary, result.player_info), ("summary", {"name": "A"}))
        self.assertEqual(tracker["worldConditions"], {"activeCombatEncounter": "", "lastCompletedEncounter": "E-1"})
        self.assertEqual([event[0] for event in events], [
            "info", "summary", "debug", "write", "info", "chat_history", "reload_player", "info",
        ])

    def test_action_trace_metadata_is_read_only_bounded_and_default_off(self):
        observations = []
        inputs = CombatActionTraceInputs(
            actions=[{"action": "attack", "parameters": {
                "actor": "PC1", "target": "Goblin", "ops": [{"op": "hp_delta", "creature": "Goblin"}],
            }}],
            encounter_data={"creatures": [{"name": "Goblin", "type": "enemy"}]},
            encounter_id="E-1",
            pre_action_context={"logical_turn": 3, "phase": "PC_PHASE", "combat_round": 2,
                               "validation_accepted": True, "enemy_phase_expected": False},
            validation_accepted=True,
        )
        trace_combat_action_batch_metadata(inputs, CombatActionTraceDependencies(
            trace_enabled=lambda: False, trace_observation=lambda *args, **kwargs: observations.append((args, kwargs))
        ))
        self.assertEqual(observations, [])
        trace_combat_action_batch_metadata(inputs, CombatActionTraceDependencies(
            trace_enabled=lambda: True, trace_observation=lambda *args, **kwargs: observations.append((args, kwargs))
        ))
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0][0], ("combat_action_batch",))
        self.assertEqual(observations[0][1]["explicit_actor_records"], [{"action_index": 0, "name": "PC1", "source": "actor"}])
        self.assertEqual(observations[0][1]["affected_entities"], [
            {"action_index": 0, "name": "Goblin", "source": "target"},
            {"action_index": 0, "name": "Goblin", "source": "ops.creature"},
        ])


if __name__ == "__main__":
    unittest.main()
