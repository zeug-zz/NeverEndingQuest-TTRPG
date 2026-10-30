# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free identity and receipt model tests for committed combat turns."""

import copy
import importlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft7Validator, FormatChecker, ValidationError

from scripts.core_chat_test_safety import arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()

from core.combat.turn import (
    CombatNormalTurnDependencies,
    CombatNormalTurnInputs,
    CombatRetryDependencies,
    CombatRetryInputs,
    CombatTurnIterationResult,
    RoundTransitionDependencies,
    apply_reported_round_transition,
    prepare_combat_normal_turn,
    run_combat_provider_retry_stage,
    stage_combat_turn_snapshot,
    sync_committed_combat_turn,
)
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.turn_commit import (
    TurnCharacterEffect,
    TurnCommitError,
    build_accepted_input_record,
    build_turn_receipt,
    commit_combat_turn,
    compute_applied_id,
    conversation_history_for_prompt,
    new_turn_id,
    read_character_applied_id,
    read_turn_receipts,
    with_character_applied_id,
    with_turn_receipt,
)
from core.combat.bootstrap import (
    CombatHistoryDependencies,
    CombatInitializationDependencies,
    CombatInitializationInputs,
    CombatTurnRecoveryError,
    CombatStartupNarrativeInputs,
    initialize_combat_session,
    _run_initial_scene_generation,
    _run_resume_narrative,
    run_startup_narrative,
)
from core.combat.session import CombatSession
from core.combat.narration import publish_combat_narration
from core.combat import turn_fault_injection
from core.combat.enemy_batch_apply import apply_enemy_batch
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyDeparture,
    EnemyResolutionLedger,
)
from core.combat.validation import CombatValidationDependencies, validate_combat_response
from scripts.combat_latency_fixtures import build_capture_character_payload
from utils.file_operations import safe_read_json, safe_write_json
import model_config


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXED_TURN_ID = "00000000-0000-4000-8000-000000000001"
FIXED_ENCOUNTER_ID = "fixture-encounter"
FIXED_TIMESTAMP = "2026-10-26T12:34:56.123Z"
STANDARD_PROVIDER_MESSAGE_FIELDS = frozenset({
    "role", "content", "name", "tool_calls", "tool_call_id", "function_call",
})
_MODULE_CACHE_MISSING = object()
_COMBAT_MANAGER_MODULE_KEYS = (
    "core.combat.combat_manager",
    "core.managers.combat_manager",
)
_COMBAT_MANAGER_PARENT_MODULES = ("core.combat", "core.managers")
_COMBAT_MANAGER_MODULE_SNAPSHOT = None
_COMBAT_MANAGER_PARENT_ATTRIBUTE_SNAPSHOT = None


def setUpModule():
    """Snapshot provider-bearing aliases before tests import the combat owner."""
    global _COMBAT_MANAGER_MODULE_SNAPSHOT
    global _COMBAT_MANAGER_PARENT_ATTRIBUTE_SNAPSHOT

    _COMBAT_MANAGER_MODULE_SNAPSHOT = {
        name: sys.modules.get(name, _MODULE_CACHE_MISSING)
        for name in _COMBAT_MANAGER_MODULE_KEYS
    }
    _COMBAT_MANAGER_PARENT_ATTRIBUTE_SNAPSHOT = {}
    for name in _COMBAT_MANAGER_PARENT_MODULES:
        package = sys.modules.get(name)
        _COMBAT_MANAGER_PARENT_ATTRIBUTE_SNAPSHOT[name] = (
            package.__dict__.get("combat_manager", _MODULE_CACHE_MISSING)
            if package is not None else _MODULE_CACHE_MISSING
        )


def tearDownModule():
    """Restore module aliases so later suites can install guarded import fixtures."""
    for name, module in (_COMBAT_MANAGER_MODULE_SNAPSHOT or {}).items():
        if module is _MODULE_CACHE_MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module

    for name, original_attribute in (
        _COMBAT_MANAGER_PARENT_ATTRIBUTE_SNAPSHOT or {}
    ).items():
        package = sys.modules.get(name)
        if package is None:
            continue
        if original_attribute is _MODULE_CACHE_MISSING:
            package.__dict__.pop("combat_manager", None)
        else:
            package.__dict__["combat_manager"] = original_attribute


def _load_combat_manager_for_unit_tests():
    """Import the owner with inert configuration/client bindings in guarded runs."""
    existing = sys.modules.get("core.combat.combat_manager")
    if existing is not None:
        return existing

    import utils.ai_client_factory as client_factory

    test_config = ModuleType("config")
    test_config.COMBAT_MAIN_MODEL = "fixture-combat-main"
    test_config.DM_VALIDATION_MODEL = "fixture-validation"
    test_config.COMBAT_DIALOGUE_SUMMARY_MODEL = "fixture-summary"
    test_config.DM_MINI_MODEL = "fixture-mini"
    test_config.OPENAI_API_KEY = ""
    test_config.OPENROUTER_API_KEY = ""
    test_character_updates = ModuleType("updates.update_character_info")
    test_character_updates.update_character_info = lambda *_args, **_kwargs: {}
    test_character_updates.normalize_character_name = lambda name: name
    with (
        patch("os.makedirs"),
        patch.dict(sys.modules, {
            "config": test_config,
            "updates.update_character_info": test_character_updates,
        }),
        patch.object(client_factory, "create_chat_client", return_value=None),
    ):
        return importlib.import_module("core.combat.combat_manager")


def _load_schema(name):
    with (REPO_ROOT / "schemas" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _receipt(encounter_id=FIXED_ENCOUNTER_ID):
    return build_turn_receipt(
        encounter_id,
        FIXED_TURN_ID,
        1,
        FIXED_TIMESTAMP,
    )


class CombatTurnIdentityAndReceiptTests(unittest.TestCase):
    def tearDown(self):
        PROCESS_TRIPWIRES.assert_untouched(self)

    def test_applied_id_matches_fixed_versioned_sha256_vector(self):
        self.assertEqual(
            compute_applied_id(FIXED_ENCOUNTER_ID, FIXED_TURN_ID),
            "sha256:db4252cfbc1cd39234a5005f16abe22c58a1f430b2bd86c75a85615731fd4794",
        )

    def test_encounter_schema_accepts_only_the_committed_phase_values(self):
        schema = _load_schema("encounter_schema.json")
        validator = Draft7Validator(schema)
        base = {
            "encounterId": FIXED_ENCOUNTER_ID,
            "encounterSummary": "Fixture encounter",
            "creatures": [],
        }
        validator.validate(dict(base, combat_phase="PC_PHASE"))
        validator.validate(dict(base, combat_phase="ENEMY_PHASE"))
        with self.assertRaises(ValidationError):
            validator.validate(dict(base, combat_phase="MODEL_PHASE"))

    def test_receipt_schema_accepts_exact_fields_and_optional_reserved_slot(self):
        schema = _load_schema("encounter_schema.json")
        base_encounter = {
            "encounterId": FIXED_ENCOUNTER_ID,
            "encounterSummary": "Fixture encounter",
            "creatures": [],
        }
        receipt = _receipt()
        self.assertEqual(
            set(receipt),
            {
                "schema_version",
                "turn_id",
                "applied_id",
                "encounter_id",
                "combat_round",
                "commit_timestamp",
            },
        )
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        validator.validate({**base_encounter, "turn_receipts": [receipt]})

        receipt_with_reserved_slot = dict(receipt, position_deltas={})
        validator.validate({
            **base_encounter,
            "position_deltas": [],
            "turn_receipts": [receipt_with_reserved_slot],
        })
        self.assertNotIn("position_deltas", _receipt())

        invalid_receipts = (
            dict(receipt, extra_field="not allowed"),
            dict(receipt, applied_id="sha256:" + "A" * 64),
            dict(receipt, turn_id="not-a-uuid"),
            dict(receipt, combat_round=0),
            dict(receipt, commit_timestamp="2026-10-26T12:34:56+00:00"),
        )
        for invalid in invalid_receipts:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validator.validate({
                    **base_encounter,
                    "turn_receipts": [invalid],
                })

        with self.assertRaises(ValueError):
            build_turn_receipt(
                FIXED_ENCOUNTER_ID,
                FIXED_TURN_ID,
                1,
                "2026-02-30T12:34:56Z",
            )

    def test_character_marker_schema_is_optional_and_validated(self):
        schema = _load_schema("char_schema.json")
        character = build_capture_character_payload("Acheron", 18)
        Draft7Validator(schema).validate(character)

        applied_id = "sha256:" + "a" * 64
        marked_character = with_character_applied_id(character, applied_id)
        Draft7Validator(schema).validate(marked_character)
        self.assertEqual(read_character_applied_id(marked_character), applied_id)

        marked_character["last_combat_applied_id"] = "sha256:" + "A" * 64
        with self.assertRaises(ValidationError):
            Draft7Validator(schema).validate(marked_character)

    def test_legacy_receipt_and_character_readers_treat_missing_fields_as_empty(self):
        self.assertEqual(read_turn_receipts({"encounterId": "legacy"}), [])
        self.assertIsNone(read_character_applied_id({"name": "legacy"}))
        self.assertIsNone(read_character_applied_id({"name": "legacy", "last_combat_applied_id": ""}))

    def test_receipt_writer_is_append_only_and_omits_position_deltas(self):
        initial = {"encounterId": FIXED_ENCOUNTER_ID, "encounterSummary": "Fixture"}
        receipt = _receipt()
        appended = with_turn_receipt(initial, receipt)
        replayed = with_turn_receipt(appended, receipt)

        self.assertEqual(len(read_turn_receipts(appended)), 1)
        self.assertEqual(len(read_turn_receipts(replayed)), 1)
        self.assertNotIn("position_deltas", read_turn_receipts(appended)[0])
        self.assertNotIn("turn_receipts", initial)
        with self.assertRaises(ValueError):
            with_turn_receipt(appended, dict(receipt, combat_round=2))

        spatial_candidate = with_turn_receipt(
            initial,
            dict(receipt, position_deltas={"reserved": "not consumed"}),
        )
        self.assertNotIn("position_deltas", spatial_candidate["turn_receipts"][0])
        self.assertNotIn("position_deltas", read_turn_receipts(spatial_candidate)[0])

    def test_identity_helpers_apply_identically_to_one_and_four_pc_fixtures(self):
        party_shapes = {
            1: ["Acheron"],
            4: ["Acheron", "Merisiel", "Kira", "Vitreol"],
        }
        for party_size, names in party_shapes.items():
            with self.subTest(party_size=party_size):
                encounter_id = "fixture-%d-pc" % party_size
                encounter = {
                    "encounterId": encounter_id,
                    "encounterSummary": "Party-shape fixture",
                    "creatures": [
                        {"name": name, "type": "player"} for name in names
                    ],
                }
                receipt = build_turn_receipt(
                    encounter_id, FIXED_TURN_ID, 1, FIXED_TIMESTAMP
                )
                committed_encounter = with_turn_receipt(encounter, receipt)
                committed_characters = {
                    name: with_character_applied_id({"name": name}, receipt["applied_id"])
                    for name in names
                }

                self.assertEqual(len(read_turn_receipts(committed_encounter)), 1)
                self.assertEqual(
                    [read_character_applied_id(value) for value in committed_characters.values()],
                    [receipt["applied_id"]] * party_size,
                )


class CombatTurnCommitCoordinatorTests(unittest.TestCase):
    def _fixture(self, names):
        encounter_path = "modules/encounters/encounter_fixture.json"
        encounter = {
            "encounterId": FIXED_ENCOUNTER_ID,
            "combat_round": 2,
            "creatures": [
                {"name": name, "type": "player", "currentHitPoints": 20}
                for name in names
            ],
        }
        state = {encounter_path: copy.deepcopy(encounter)}
        paths = {
            name: "characters/%s.json" % name.casefold() for name in names
        }
        for name, path in paths.items():
            state[path] = {"name": name, "hitPoints": 20, "status": "alive"}
        events = []
        failing_path = {"value": None}

        def read_json(path):
            return copy.deepcopy(state.get(path))

        def write_json(path, payload):
            events.append(path)
            if path == failing_path["value"]:
                return False
            state[path] = copy.deepcopy(payload)
            return True

        effects = []
        for name, path in paths.items():
            def stage(current):
                updated = copy.deepcopy(dict(current))
                updated["hitPoints"] -= 1
                return updated

            effects.append(TurnCharacterEffect(name, path, stage))
        return encounter_path, encounter, state, paths, events, failing_path, effects, read_json, write_json

    def _commit(self, fixture, *, effects=None):
        encounter_path, encounter, _state, _paths, _events, _fail, default_effects, read_json, write_json = fixture
        return commit_combat_turn(
            FIXED_ENCOUNTER_ID,
            FIXED_TURN_ID,
            encounter_path,
            encounter,
            default_effects if effects is None else effects,
            read_json=read_json,
            write_json=write_json,
            validate_character=lambda _name, _payload: True,
        )

    def test_one_and_four_pc_commits_write_sorted_characters_then_one_encounter(self):
        for names in (
            ["Acheron"],
            ["Vitreol", "Acheron", "Kira", "Merisiel"],
        ):
            with self.subTest(party_size=len(names)):
                fixture = self._fixture(names)
                result = self._commit(fixture)
                expected_paths = [
                    fixture[3][name]
                    for name in sorted(names, key=lambda value: value.casefold())
                ] + [fixture[0]]
                self.assertEqual(fixture[4], expected_paths)
                self.assertEqual(result.write_count, len(names) + 1)
                self.assertEqual(len(result.encounter_data["turn_receipts"]), 1)
                for name, path in fixture[3].items():
                    self.assertEqual(fixture[2][path]["hitPoints"], 19)
                    self.assertEqual(
                        read_character_applied_id(fixture[2][path]),
                        result.applied_id,
                    )

    def test_normal_turn_owner_routes_staged_effects_through_the_coordinator(self):
        combat_manager = _load_combat_manager_for_unit_tests()

        class PathManager:
            def __init__(self, names, encounter_path):
                self.character_paths = {
                    name: "characters/%s.json" % name.casefold() for name in names
                }
                self.encounter_path = encounter_path

            def get_character_path(self, name):
                return self.character_paths[name]

            def get_encounter_path_from_id(self, _encounter_id):
                return self.encounter_path

        for names in (
            ["Acheron"],
            ["Vitreol", "Acheron", "Kira", "Merisiel"],
        ):
            with self.subTest(party_size=len(names)):
                encounter_path = "modules/encounters/encounter_fixture.json"
                path_manager = PathManager(names, encounter_path)
                encounter = {
                    "encounterId": FIXED_ENCOUNTER_ID,
                    "combat_round": 1,
                    "creatures": [
                        {
                            "name": name,
                            "type": "player",
                            "currentHitPoints": 20,
                            "status": "alive",
                        }
                        for name in names
                    ],
                }
                state = {encounter_path: copy.deepcopy(encounter)}
                for name, path in path_manager.character_paths.items():
                    state[path] = build_capture_character_payload(name, 18)
                events = []

                def read_json(path):
                    return copy.deepcopy(state.get(path))

                def write_json(path, payload):
                    events.append(path)
                    state[path] = copy.deepcopy(payload)
                    return True

                def stage_character(
                    _name, _entries, current, _update_character_info, *, log_error=None
                ):
                    updated = copy.deepcopy(current)
                    updated["hitPoints"] -= 1
                    return updated

                updates = {
                    name: [{"changes": "fixture effect", "ops": None}]
                    for name in names
                }
                with (
                    patch.object(combat_manager, "safe_json_load", side_effect=read_json),
                    patch.object(combat_manager, "safe_write_json", side_effect=write_json),
                    patch.object(
                        combat_manager,
                        "stage_final_character_update",
                        side_effect=stage_character,
                    ),
                ):
                    result = combat_manager._commit_normal_combat_turn(
                        FIXED_ENCOUNTER_ID,
                        FIXED_TURN_ID,
                        encounter,
                        updates,
                        path_manager,
                        validate_character=lambda _name, _payload: True,
                    )
                    self.assertEqual(
                        [
                            path_manager.character_paths[name]
                            for name in sorted(names, key=lambda value: value.casefold())
                        ] + [encounter_path],
                        events,
                    )
                    events.clear()
                    replay = combat_manager._commit_normal_combat_turn(
                        FIXED_ENCOUNTER_ID,
                        FIXED_TURN_ID,
                        encounter,
                        updates,
                        path_manager,
                        validate_character=lambda _name, _payload: True,
                    )

                self.assertFalse(result.replayed)
                self.assertTrue(replay.replayed)
                self.assertEqual(events, [])
                for name, path in path_manager.character_paths.items():
                    self.assertEqual(state[path]["hitPoints"], 19)
                    self.assertEqual(
                        read_character_applied_id(state[path]), result.applied_id
                    )

    def test_normal_turn_staging_skips_rejected_ops_for_one_and_four_pc(self):
        combat_manager = _load_combat_manager_for_unit_tests()

        class PathManager:
            def __init__(self, names, encounter_path):
                self.character_paths = {
                    name: "characters/%s.json" % name.casefold() for name in names
                }
                self.encounter_path = encounter_path

            def get_character_path(self, name):
                return self.character_paths[name]

            def get_encounter_path_from_id(self, _encounter_id):
                return self.encounter_path

        for names in (
            ["Acheron"],
            ["Vitreol", "Acheron", "Kira", "Merisiel"],
        ):
            for reject_prose in (False, True):
                with self.subTest(party_size=len(names), reject_prose=reject_prose):
                    encounter_path = "modules/encounters/encounter_fixture.json"
                    path_manager = PathManager(names, encounter_path)
                    encounter = {
                        "encounterId": FIXED_ENCOUNTER_ID,
                        "combat_round": 1,
                        "creatures": [
                            {
                                "name": name,
                                "type": "player",
                                "currentHitPoints": 20,
                                "status": "alive",
                            }
                            for name in names
                        ],
                    }
                    state = {encounter_path: copy.deepcopy(encounter)}
                    for name, path in path_manager.character_paths.items():
                        state[path] = build_capture_character_payload(name, 18)
                    write_events = []
                    stage_calls = []
                    errors = []

                    def read_json(path):
                        return copy.deepcopy(state.get(path))

                    def write_json(path, payload):
                        write_events.append(path)
                        state[path] = copy.deepcopy(payload)
                        return True

                    def update_character_info(
                        name, changes, *, ops=None, _stage_only=False, _stage_data=None
                    ):
                        self.assertTrue(_stage_only)
                        stage_calls.append((name, ops[0]["op"] if ops else "prose"))
                        if ops and ops[0]["op"] == "rejected_fixture_op":
                            return False
                        if not ops and reject_prose:
                            return False
                        updated = copy.deepcopy(_stage_data)
                        if ops:
                            updated["hitPoints"] += ops[0]["delta"]
                        else:
                            updated["gold"] = updated.get("gold", 0) + 1
                        return updated

                    updates = {
                        name: [
                            {
                                "changes": "rejected effect",
                                "ops": [{"op": "rejected_fixture_op"}],
                            },
                            {
                                "changes": "accepted effect",
                                "ops": [{"op": "hp_delta", "delta": -1}],
                            },
                            {"changes": "follow-up prose effect", "ops": None},
                        ]
                        for name in names
                    }

                    with (
                        patch.object(
                            combat_manager, "safe_json_load", side_effect=read_json
                        ),
                        patch.object(
                            combat_manager, "safe_write_json", side_effect=write_json
                        ),
                        patch.object(
                            combat_manager,
                            "update_character_info",
                            side_effect=update_character_info,
                        ),
                        patch.object(
                            combat_manager,
                            "error",
                            side_effect=lambda message, **kwargs: errors.append(
                                (message, kwargs)
                            ),
                        ),
                    ):
                        result = combat_manager._commit_normal_combat_turn(
                            FIXED_ENCOUNTER_ID,
                            FIXED_TURN_ID,
                            encounter,
                            updates,
                            path_manager,
                            validate_character=lambda _name, _payload: True,
                        )

                    ordered_names = sorted(names, key=lambda value: value.casefold())
                    self.assertEqual(
                        stage_calls,
                        [
                            (name, operation)
                            for name in ordered_names
                            for operation in (
                                "rejected_fixture_op", "hp_delta", "prose"
                            )
                        ],
                    )
                    self.assertEqual(
                        write_events,
                        [path_manager.character_paths[name] for name in ordered_names]
                        + [encounter_path],
                    )
                    self.assertEqual(result.changed_characters, tuple(ordered_names))
                    self.assertEqual(len(result.encounter_data["turn_receipts"]), 1)
                    expected_errors = []
                    for name in ordered_names:
                        expected_errors.append(
                            "FAILURE: Deterministic combat update failed for %s." % name
                        )
                        if reject_prose:
                            expected_errors.append(
                                "FAILURE: Final consolidated update failed for %s." % name
                            )
                    self.assertEqual([message for message, _ in errors], expected_errors)
                    for name in names:
                        character = state[path_manager.character_paths[name]]
                        self.assertEqual(character["hitPoints"], 19)
                        self.assertEqual(character.get("gold", 0), 0 if reject_prose else 1)
                        self.assertEqual(
                            read_character_applied_id(character), result.applied_id
                        )
                    self.assertEqual(
                        [row["currentHitPoints"] for row in state[encounter_path]["creatures"]],
                        [19] * len(names),
                    )

    def test_partial_character_write_retry_skips_marked_characters(self):
        fixture = self._fixture(["Vitreol", "Merisiel", "Acheron", "Kira"])
        failed_path = fixture[3]["Merisiel"]
        fixture[5]["value"] = failed_path
        with self.assertRaises(TurnCommitError) as raised:
            self._commit(fixture)
        self.assertEqual(raised.exception.stage, "character_write")
        self.assertNotIn(fixture[0], fixture[4])
        self.assertEqual(fixture[2][fixture[3]["Acheron"]]["hitPoints"], 19)
        self.assertEqual(fixture[2][fixture[3]["Kira"]]["hitPoints"], 19)

        fixture[4].clear()
        fixture[5]["value"] = None
        result = self._commit(fixture)
        self.assertEqual(fixture[4], [
            fixture[3]["Merisiel"], fixture[3]["Vitreol"], fixture[0],
        ])
        self.assertEqual(fixture[2][fixture[3]["Acheron"]]["hitPoints"], 19)
        self.assertEqual(fixture[2][fixture[3]["Kira"]]["hitPoints"], 19)
        self.assertEqual(result.changed_characters, ("Merisiel", "Vitreol"))

    def test_encounter_write_failure_retry_commits_receipt_without_rewriting_characters(self):
        fixture = self._fixture(["Acheron"])
        fixture[5]["value"] = fixture[0]
        with self.assertRaises(TurnCommitError) as raised:
            self._commit(fixture)
        self.assertEqual(raised.exception.stage, "encounter_write")
        self.assertEqual(fixture[2][fixture[3]["Acheron"]]["hitPoints"], 19)
        self.assertIsNone(fixture[2][fixture[0]].get("turn_receipts"))

        fixture[4].clear()
        fixture[5]["value"] = None
        result = self._commit(fixture)
        self.assertEqual(fixture[4], [fixture[0]])
        self.assertEqual(result.write_count, 1)
        self.assertEqual(len(fixture[2][fixture[0]]["turn_receipts"]), 1)


    def test_completed_receipt_replay_skips_character_and_encounter_writes(self):
        fixture = self._fixture(["Acheron"])
        self._commit(fixture)
        fixture[4].clear()
        replay = self._commit(fixture)
        self.assertTrue(replay.replayed)
        self.assertEqual(fixture[4], [])
        self.assertEqual(fixture[2][fixture[3]["Acheron"]]["hitPoints"], 19)

    def test_accepted_input_history_persists_turn_id_before_later_effects(self):
        events = []
        persisted_histories = []

        def save_history(path, history):
            events.append("persist_history")
            persisted_histories.append(copy.deepcopy(history))
            return True

        def assemble_context(_inputs):
            return SimpleNamespace(
                return_early=False,
                encounter_data={"encounterId": FIXED_ENCOUNTER_ID, "creatures": []},
                player_info={},
                player_file="characters/acheron.json",
                path_manager=None,
                fresh_player_data={},
                current_hp=20,
                max_hp=20,
                user_input_text="attack",
                user_prompt="Exact assembled prompt bytes",
            )

        session = SimpleNamespace(bind_history=lambda _history: None, active_pc=None)
        encounter = {"encounterId": FIXED_ENCOUNTER_ID, "creatures": []}
        history = [{"role": "system", "content": "Existing system bytes"}]
        iteration = CombatTurnIterationResult(
            session=session,
            encounter_data=encounter,
            multi_pc_manager=None,
            party_tracker_data={"active_character": "Acheron"},
            conversation_history=history,
            npc_templates={},
            player_file="characters/acheron.json",
            fresh_player_data={},
            current_hp=20,
            max_hp=20,
            player_name_display="Acheron",
            current_round_trace_start=0.0,
            user_input_text="attack",
            path_manager=None,
            player_info={"name": "Acheron"},
        )
        dependencies = CombatNormalTurnDependencies(
            input_phase_gate=lambda *_args, **_kwargs: SimpleNamespace(
                control_action="proceed",
                raw_input="attack",
                clean_input="attack",
                input_actor_name=None,
                pc_phase_started=False,
            ),
            phase_gate_io_factory=lambda _manager: None,
            initiative_gate=lambda *_args, **_kwargs: None,
            fast_command_stage=lambda **_kwargs: SimpleNamespace(
                control_action="proceed", user_input_text="attack"
            ),
            fast_command_io_factory=lambda: None,
            deterministic_command_stage=lambda **_kwargs: SimpleNamespace(
                control_action="proceed", status="ready"
            ),
            deterministic_command_io_factory=lambda *_args: None,
            character_stat_command=lambda *_args: False,
            character_stat_io_factory=lambda _path_manager: None,
            normalize_character_name=lambda name: name.lower(),
            safe_json_load=lambda _path: {},
            pc_action_enabled=False,
            perf_counter=lambda: 0.0,
            trace_decision=lambda *_args, **_kwargs: None,
            enhance_inventory_context=lambda inputs: SimpleNamespace(
                user_input_text=inputs.user_input_text,
                fresh_player_data=inputs.preexisting_player_data,
            ),
            enhance_player_input_with_inventory=lambda text, *_args, **_kwargs: text,
            assemble_context=assemble_context,
            clean_old_dm_notes=lambda messages: messages,
            clean_combat_state_blocks=lambda messages: messages,
            save_json=save_history,
            debug=lambda *_args, **_kwargs: None,
            emit=lambda _message: None,
            flush=lambda: None,
        )

        result = prepare_combat_normal_turn(
            CombatNormalTurnInputs(
                iteration=iteration,
                encounter_id=FIXED_ENCOUNTER_ID,
                json_file_path="modules/encounters/encounter_fixture.json",
                conversation_history_file="modules/conversation_history/history.json",
                location_info={},
            ),
            dependencies,
        )
        events.append("mechanical_effect")

        self.assertEqual(result.control_action, "proceed")
        self.assertEqual(events, ["persist_history", "mechanical_effect"])
        record = persisted_histories[0][-1]
        self.assertEqual(record["content"], "Exact assembled prompt bytes")
        self.assertEqual(record["role"], "user")
        self.assertEqual(record["turn_id"], result.conversation_history[-1]["turn_id"])
        self.assertEqual(str(uuid.UUID(record["turn_id"])), record["turn_id"])

    def test_provider_and_validation_histories_omit_turn_id_without_changing_bytes(self):
        turn_id = new_turn_id()
        persisted_history = [
            {"role": "system", "content": "System bytes"},
            build_accepted_input_record("Exact user prompt bytes", turn_id=turn_id),
        ]
        expected_prompt_history = [
            {"role": "system", "content": "System bytes"},
            {"role": "user", "content": "Exact user prompt bytes"},
        ]
        expected_bytes = json.dumps(
            expected_prompt_history, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(
            json.dumps(
                conversation_history_for_prompt(persisted_history),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            expected_bytes,
        )
        self.assertEqual(persisted_history[-1]["turn_id"], turn_id)

        provider_calls = []
        validation_histories = []

        def fake_llm_call(task, messages, **_kwargs):
            provider_calls.append((task, copy.deepcopy(messages)))
            return '{"narration":"The turn is ready.","actions":[]}'

        retry_dependencies = CombatRetryDependencies(
            client=None,
            use_gpt5_models=False,
            gpt5_mini_model="fixture-mini",
            gpt5_high_reasoning_on_retry=True,
            combat_main_model="fixture-main",
            get_completion_params=lambda *_args, **_kwargs: {},
            get_temperature=lambda *_args, **_kwargs: 0.2,
            perf_counter=lambda: 1.0,
            trace_stage=lambda *_args, **_kwargs: None,
            trace_provider_call=lambda *_args, **_kwargs: None,
            export_open=lambda *_args, **_kwargs: None,
            makedirs=lambda *_args, **_kwargs: None,
            emit=lambda _message: None,
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            usage_tracking_available=False,
            track_usage=lambda _response: None,
            is_valid_json=lambda _value: True,
            check_multiple_update_encounter=lambda _actions: False,
            make_multiple_update_feedback=lambda _parsed: "retry",
            validate_combatant_integrity=lambda *_args, **_kwargs: True,
            validate_combat_response=lambda *args, **_kwargs: (
                validation_histories.append(copy.deepcopy(args[3])) or True
            ),
            update_status=lambda *_args, **_kwargs: None,
            debug_dumps_enabled=lambda: False,
            llm_call=fake_llm_call,
            receipt_observer_factory=lambda **_kwargs: (lambda *_args: None),
        )
        run_combat_provider_retry_stage(
            CombatRetryInputs(
                conversation_history=persisted_history,
                initial_conversation_length=len(persisted_history),
                encounter_data={"encounterId": FIXED_ENCOUNTER_ID, "creatures": []},
                party_tracker_data={"partyMembers": ["Acheron"]},
                multi_pc_manager=None,
                user_input_text="attack",
            ),
            retry_dependencies,
        )

        self.assertEqual(provider_calls[0][0], "combat_main")
        self.assertEqual(provider_calls[0][1], expected_prompt_history)
        self.assertEqual(validation_histories[0][1], expected_prompt_history[1])
        self.assertNotIn("turn_id", validation_histories[0][1])
        self.assertIn("turn_id", persisted_history[-1])

    def test_turn_identity_history_serializes_byte_identically_to_legacy_messages(self):
        turn_id = new_turn_id()
        durable_history = [
            {"role": "system", "content": "System bytes", "name": "combat"},
            {
                "role": "user",
                "content": "Exact user prompt bytes",
                "turn_id": turn_id,
                "_combat_turn_commit_manifest": {
                    "schema_version": 1,
                    "private_staged_effect": "never sent",
                },
                "internal_receipt_context": {"applied_id": "private"},
                "future_private_field": "never sent",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tool-1", "type": "function"}],
            },
        ]
        legacy_history = [
            {"role": "system", "content": "System bytes", "name": "combat"},
            {"role": "user", "content": "Exact user prompt bytes"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tool-1", "type": "function"}],
            },
        ]

        durable_provider_bytes = json.dumps(
            conversation_history_for_prompt(durable_history),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy_provider_bytes = json.dumps(
            conversation_history_for_prompt(legacy_history),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(durable_provider_bytes, legacy_provider_bytes)

    def test_resending_identical_input_receives_a_new_durable_turn_identity(self):
        first = build_accepted_input_record("same accepted input")
        resent = build_accepted_input_record("same accepted input")

        self.assertEqual(first["content"], resent["content"])
        self.assertNotEqual(first["turn_id"], resent["turn_id"])
        self.assertNotEqual(
            compute_applied_id(FIXED_ENCOUNTER_ID, first["turn_id"]),
            compute_applied_id(FIXED_ENCOUNTER_ID, resent["turn_id"]),
        )


class CombatTurnPhaseCommitTests(unittest.TestCase):
    @staticmethod
    def _transition_dependencies():
        from core.combat.turn import RoundTransitionDependencies

        return RoundTransitionDependencies(
            apply_opening_batch_marker=lambda *_args: False,
            sync_available=True,
            save_json=lambda *_args: True,
            compress_old_rounds=lambda history, *_args, **_kwargs: history,
            log_debug=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            log_warning=lambda *_args, **_kwargs: None,
            bind_history=lambda *_args: None,
        )

    @staticmethod
    def _manager_for_party(names, encounter):
        manager = MultiPCCombatManager()
        for name in names:
            manager._state.pc_states[name] = PCCombatState(
                character_name=name,
                status=PCStatus.READY,
                current_hp=20,
                max_hp=20,
                ac=15,
            )
        manager._state.current_pc_name = names[0]
        manager.initialize_turn_queue(encounter)
        return manager

    def test_model_reported_round_does_not_advance_the_authoritative_counter(self):
        encounter = {
            "encounterId": FIXED_ENCOUNTER_ID,
            "combat_round": 1,
            "combat_phase": "PC_PHASE",
            "openingEnemyBatchPending": False,
            "creatures": [],
        }
        result = apply_reported_round_transition(
            {"combat_round": 99},
            encounter,
            [],
            encounter_id=FIXED_ENCOUNTER_ID,
            conversation_history_file="history.json",
            multi_pc_manager=None,
            dependencies=self._transition_dependencies(),
        )

        self.assertEqual(result.encounter_data["combat_round"], 1)
        self.assertEqual(result.encounter_data["combat_phase"], "PC_PHASE")
        self.assertEqual(encounter["combat_round"], 1)

    def test_end_and_enemy_phase_commit_python_owned_round_for_one_and_four_pcs(self):
        party_shapes = (
            ["Acheron"],
            ["Acheron", "Merisiel", "Kira", "Vitreol"],
        )
        for names in party_shapes:
            with self.subTest(party_size=len(names)):
                encounter_id = "phase-fixture-%d" % len(names)
                encounter_path = "modules/encounters/encounter_%s.json" % encounter_id
                encounter = {
                    "encounterId": encounter_id,
                    "combat_round": 1,
                    "roundStartsWith": "pcGroup",
                    "openingEnemyBatchPending": False,
                    "combat_phase": "PC_PHASE",
                    "creatures": [
                        {
                            "name": name,
                            "type": "player",
                            "currentHitPoints": 20,
                            "maxHitPoints": 20,
                            "armorClass": 15,
                            "status": "alive",
                        }
                        for name in names
                    ] + [{
                        "name": "Goblin",
                        "type": "enemy",
                        "currentHitPoints": 7,
                        "maxHitPoints": 7,
                        "armorClass": 13,
                        "status": "alive",
                    }],
                }
                manager = self._manager_for_party(names, encounter)
                durable = {encounter_path: copy.deepcopy(encounter)}

                def read_json(path):
                    return copy.deepcopy(durable.get(path))

                def write_json(path, payload):
                    durable[path] = copy.deepcopy(payload)
                    return True

                # /end is a legal same-round transition into ENEMY_PHASE; the
                # following completed enemy batch advances exactly one round.
                manager.force_end_pc_phase()
                end_snapshot = stage_combat_turn_snapshot(
                    encounter,
                    [],
                    phase_before="PC_PHASE",
                    phase_after="ENEMY_PHASE",
                    enemy_batch_completed=False,
                    opening_batch_pending_before=False,
                    dependencies=self._transition_dependencies(),
                )
                self.assertEqual(end_snapshot.encounter_data["combat_round"], 1)
                self.assertEqual(end_snapshot.encounter_data["combat_phase"], "ENEMY_PHASE")
                end_commit = commit_combat_turn(
                    encounter_id,
                    "00000000-0000-4000-8000-000000000011",
                    encounter_path,
                    end_snapshot.encounter_data,
                    [],
                    read_json=read_json,
                    write_json=write_json,
                    validate_character=lambda *_args: True,
                )
                self.assertEqual(end_commit.receipt["combat_round"], 1)
                self.assertEqual(end_commit.encounter_data["combat_phase"], "ENEMY_PHASE")
                sync_committed_combat_turn(end_commit.encounter_data, manager)
                self.assertEqual(manager.combat_phase, "ENEMY_PHASE")

                enemy_snapshot = stage_combat_turn_snapshot(
                    end_commit.encounter_data,
                    [],
                    phase_before="ENEMY_PHASE",
                    phase_after="ENEMY_PHASE",
                    enemy_batch_completed=True,
                    opening_batch_pending_before=False,
                    dependencies=self._transition_dependencies(),
                )
                enemy_snapshot.encounter_data["creatures"][0]["currentHitPoints"] = 18
                enemy_snapshot.encounter_data["creatures"][-1]["currentHitPoints"] = 5
                enemy_commit = commit_combat_turn(
                    encounter_id,
                    "00000000-0000-4000-8000-000000000012",
                    encounter_path,
                    enemy_snapshot.encounter_data,
                    [],
                    read_json=read_json,
                    write_json=write_json,
                    validate_character=lambda *_args: True,
                )
                self.assertEqual(enemy_commit.receipt["combat_round"], 2)
                self.assertEqual(enemy_commit.encounter_data["combat_round"], 2)
                self.assertEqual(enemy_commit.encounter_data["combat_phase"], "PC_PHASE")
                session = SimpleNamespace(
                    active_pc="stale-pc",
                    encounter=None,
                    phase=None,
                    bind_encounter=lambda snapshot: setattr(session, "encounter", snapshot),
                    set_phase=lambda phase: setattr(session, "phase", phase),
                )
                sync_committed_combat_turn(enemy_commit.encounter_data, manager, session)
                self.assertEqual(manager.current_round, 2)
                self.assertEqual(manager.combat_phase, "PC_PHASE")
                self.assertEqual(manager._turns.current_turn_index, 0)
                self.assertEqual(session.active_pc, manager.current_pc_name)
                self.assertIs(session.encounter, enemy_commit.encounter_data)
                self.assertEqual(session.phase, "PC_PHASE")
                self.assertTrue(all(
                    state.status == PCStatus.READY
                    for state in manager.pc_states.values()
                ))
                self.assertEqual(manager.pc_states[names[0]].current_hp, 18)
                self.assertEqual(
                    next(
                        actor for actor in manager._turns.turn_queue
                        if actor.name == names[0]
                    ).hp,
                    18,
                )
                self.assertEqual(
                    next(
                        actor for actor in manager._turns.turn_queue
                        if actor.name == "Goblin"
                    ).hp,
                    5,
                )

                # Simulate a fresh process rebuilding its manager from the
                # durable receipt snapshot; synchronization must not advance it.
                restarted_manager = self._manager_for_party(
                    names, enemy_commit.encounter_data
                )
                sync_committed_combat_turn(
                    enemy_commit.encounter_data, restarted_manager
                )
                self.assertEqual(restarted_manager.current_round, 2)
                self.assertEqual(restarted_manager.combat_phase, "PC_PHASE")
                self.assertEqual(restarted_manager.pc_states[names[0]].current_hp, 18)
                self.assertEqual(
                    next(
                        actor for actor in restarted_manager._turns.turn_queue
                        if actor.name == "Goblin"
                    ).hp,
                    5,
                )
                self.assertEqual(
                    durable[encounter_path]["turn_receipts"],
                    enemy_commit.encounter_data["turn_receipts"],
                )
                self.assertEqual(len(durable[encounter_path]["turn_receipts"]), 2)


class CombatTurnFaultInjectionRestartTests(unittest.TestCase):
    """Provider-free retained-file recovery across every approved stop point."""

    def tearDown(self):
        PROCESS_TRIPWIRES.assert_untouched(self)

    @staticmethod
    def _noop(*_args, **_kwargs):
        return None

    def _new_fixture(self, names):
        capture_root = REPO_ROOT / "tmp" / "combat_capture"
        capture_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(
            prefix="turn-fault-", dir=str(capture_root)
        )
        runtime_root = Path(temporary.name).resolve()
        encounter_id = "fault-fixture-%d" % len(names)
        turn_id = str(uuid.uuid4())
        encounter_path = runtime_root / "modules" / "encounters" / (
            "encounter_%s.json" % encounter_id
        )
        encounter_relative = "modules/encounters/encounter_%s.json" % encounter_id
        history_path = runtime_root / "modules" / "conversation_history" / (
            "combat_%s.json" % encounter_id
        )
        tracker_path = runtime_root / "party_tracker.json"
        monster_path = runtime_root / "modules" / "fixture" / "monsters" / "goblin.json"
        character_paths = {
            name: runtime_root / "characters" / (name.casefold() + ".json")
            for name in names
        }
        for path in (
            encounter_path,
            history_path,
            tracker_path,
            monster_path,
            *character_paths.values(),
            runtime_root / "history" / "second.json",
            runtime_root / "history" / "third.json",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)

        creatures = [
            {
                "name": name,
                "type": "player",
                "initiative": 15 - index,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "armorClass": 15,
                "status": "alive",
            }
            for index, name in enumerate(names)
        ]
        creatures.append({
            "name": "Practice Goblin",
            "type": "enemy",
            "monsterType": "Fault Fixture Goblin",
            "initiative": 8,
            "currentHitPoints": 10,
            "maxHitPoints": 10,
            "armorClass": 13,
            "status": "alive",
        })
        encounter = {
            "encounterId": encounter_id,
            "combat_round": 1,
            "roundStartsWith": "pcGroup",
            "openingEnemyBatchPending": False,
            "combat_phase": "ENEMY_PHASE",
            "encounterSummary": "Provider-free turn fault fixture",
            "creatures": creatures,
        }
        tracker = {
            "module": "Fault Injection Fixture",
            "active_character": names[0],
            "partyMembers": [{"name": name} for name in names],
            "partyNPCs": [],
            "worldConditions": {},
        }
        history = [
            {"role": "system", "content": "Current Combat Encounter: " + encounter_id},
            {"role": "system", "content": "Retained restart fixture " + ("x" * 180)},
            build_accepted_input_record("Enemies turn.", turn_id=turn_id),
        ]
        safe_write_json(str(encounter_path), encounter, create_backup=False)
        safe_write_json(str(tracker_path), tracker, create_backup=False)
        safe_write_json(str(history_path), history, create_backup=False)
        safe_write_json(
            str(monster_path),
            {"name": "Fault Fixture Goblin", "hitPoints": 10, "armorClass": 13},
            create_backup=False,
        )
        for name, path in character_paths.items():
            safe_write_json(
                str(path),
                {
                    "name": name,
                    "hitPoints": 20,
                    "maxHitPoints": 20,
                    "armorClass": 15,
                    "experience_points": 100,
                    "gold": 0,
                    "condition_affected": [],
                    "status": "alive",
                },
                create_backup=False,
            )

        fixture = {
            "temporary": temporary,
            "runtime_root": runtime_root,
            "encounter_id": encounter_id,
            "turn_id": turn_id,
            "encounter_path": encounter_path,
            "encounter_relative": encounter_relative,
            "history_path": history_path,
            "tracker_path": tracker_path,
            "monster_path": monster_path,
            "character_paths": character_paths,
            "names": list(names),
            "character_write_events": [],
            "encounter_write_events": [],
            "tracker_write_events": [],
            "publication_ids": [],
            "outputs": [],
            "flushes": [],
        }
        return fixture

    @staticmethod
    def _resolve_fixture_path(fixture, path):
        raw = os.fspath(path)
        if raw == "party_tracker.json":
            return fixture["tracker_path"]
        if raw == fixture["encounter_relative"]:
            return fixture["encounter_path"]
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else fixture["runtime_root"] / candidate

    def _read_json(self, fixture, path):
        return safe_read_json(str(self._resolve_fixture_path(fixture, path)))

    def _write_json(self, fixture, path, payload):
        resolved = self._resolve_fixture_path(fixture, path)
        for name, character_path in fixture["character_paths"].items():
            if resolved == character_path:
                fixture["character_write_events"].append(name)
                break
        if resolved == fixture["encounter_path"]:
            fixture["encounter_write_events"].append(copy.deepcopy(payload))
        if resolved == fixture["tracker_path"]:
            fixture["tracker_write_events"].append(copy.deepcopy(payload))
        return safe_write_json(str(resolved), payload, create_backup=False)

    def _bootstrap_from_disk(self, fixture):
        encounter_id = fixture["encounter_id"]
        names = fixture["names"]
        path_manager = self._path_manager(fixture)

        def create_manager(_party_tracker):
            manager = MultiPCCombatManager()
            for name in names:
                character = self._read_json(fixture, fixture["character_paths"][name])
                manager._state.pc_states[name] = PCCombatState(
                    character_name=name,
                    status=PCStatus.READY,
                    current_hp=character["hitPoints"],
                    max_hp=character["maxHitPoints"],
                    ac=character["armorClass"],
                )
            manager._state.current_pc_name = names[0]
            return manager

        history_dependencies = CombatHistoryDependencies(
            exists=lambda path: Path(path).exists(),
            getsize=lambda path: Path(path).stat().st_size,
            load_json=lambda path: self._read_json(fixture, path),
            read_prompt=lambda _path: "",
            save_json=lambda path, payload: self._write_json(fixture, path, payload),
            format_character=lambda *_args, **_kwargs: "",
            format_npc=lambda *_args, **_kwargs: "",
            filter_dynamic_fields=lambda value: value,
            filter_encounter=lambda value: value,
            log_structure=self._noop,
            debug=self._noop,
            error=self._noop,
            emit=self._noop,
            remove=lambda path: Path(path).unlink(missing_ok=True),
        )
        dependencies = CombatInitializationDependencies(
            module_path_manager_factory=lambda _module=None: path_manager,
            safe_json_load=lambda path: self._read_json(fixture, path),
            session_factory=lambda **kwargs: CombatSession(**kwargs),
            multi_pc_combat_available=True,
            is_multi_pc_enabled=lambda: True,
            normalize_phase1_initiative=lambda encounter, _tracker: (encounter, False, None),
            save_json=lambda path, payload: self._write_json(fixture, path, payload),
            get_combat_manager=lambda: None,
            create_combat_manager=create_manager,
            history_file=str(fixture["history_path"]),
            second_model_history_file=str(fixture["runtime_root"] / "history" / "second.json"),
            third_model_history_file=str(fixture["runtime_root"] / "history" / "third.json"),
            history_dependencies=history_dependencies,
            normalize_character_name=lambda name: name,
            load_npc_with_fuzzy_match=lambda *_args, **_kwargs: (None, None),
            file_exists=lambda path: Path(path).exists(),
            list_directory=lambda _path: [],
            print_exception=self._noop,
            emit=self._noop,
            debug=self._noop,
            info=self._noop,
            warning=self._noop,
            error=self._noop,
            write_json=lambda path, payload: self._write_json(fixture, path, payload),
            validate_character=lambda _name, _payload: True,
            publish_narration=lambda text, *, applied_id: publish_combat_narration(
                text,
                applied_id=applied_id,
                emit=lambda output: fixture["outputs"].append(output),
                flush=lambda: fixture["flushes"].append(applied_id),
            ) and fixture["publication_ids"].append(applied_id),
        )
        tracker = self._read_json(fixture, "party_tracker.json")
        result = initialize_combat_session(
            CombatInitializationInputs(
                encounter_id=encounter_id,
                party_tracker_data=tracker,
                location_info={},
            ),
            dependencies,
        )
        if result.return_early:
            self.fail("provider-free bootstrap unexpectedly returned early")
        return result

    @staticmethod
    def _path_manager(fixture):
        class FixturePathManager:
            module_dir = str(fixture["runtime_root"] / "modules" / "fixture")

            def get_character_path(self, name):
                return str(fixture["character_paths"][name])

            def get_monster_path(self, _monster_type):
                return str(fixture["monster_path"])

            def get_encounter_path_from_id(self, _encounter_id):
                return str(fixture["encounter_path"])

        return FixturePathManager()

    def _run_normal_fixture_turn(self, fixture):
        combat_manager = _load_combat_manager_for_unit_tests()
        history = self._read_json(fixture, fixture["history_path"])
        encounter = self._read_json(fixture, fixture["encounter_relative"])
        encounter["combat_round"] = 2
        encounter["current_round"] = 2
        encounter["combat_phase"] = "PC_PHASE"
        encounter["openingEnemyBatchPending"] = False
        encounter["creatures"][-1]["currentHitPoints"] = 7
        updates = {
            name: [{"changes": "fixture staged turn effect", "ops": None}]
            for name in fixture["names"]
        }

        def stage_character(
            _name, _entries, current, _update_character_info, *, log_error=None
        ):
            updated = copy.deepcopy(current)
            updated["hitPoints"] -= 2
            updated["experience_points"] += 25
            updated["gold"] = updated.get("gold", 0) + 7
            updated.setdefault("condition_affected", []).append("poisoned")
            return updated

        with (
            patch.object(
                combat_manager,
                "safe_json_load",
                side_effect=lambda path: self._read_json(fixture, path),
            ),
            patch.object(
                combat_manager,
                "safe_write_json",
                side_effect=lambda path, payload: self._write_json(
                    fixture, path, payload
                ),
            ),
            patch.object(
                combat_manager,
                "stage_final_character_update",
                side_effect=stage_character,
            ),
        ):
            result = combat_manager._commit_normal_combat_turn(
                fixture["encounter_id"],
                fixture["turn_id"],
                encounter,
                updates,
                self._path_manager(fixture),
                conversation_history=history,
                conversation_history_file=str(fixture["history_path"]),
                narration="The party's actions resolve.",
                validate_character=lambda *_args: True,
            )
        sync_committed_combat_turn(result.encounter_data, None)
        fixture["publication_ids"].append(result.applied_id)
        publish_combat_narration(
            "The party's actions resolve.",
            applied_id=result.applied_id,
            emit=fixture["outputs"].append,
            flush=lambda: fixture["flushes"].append(result.applied_id),
        )

    def _run_enemy_batch_fixture_turn(self, fixture):
        names = fixture["names"]
        history = self._read_json(fixture, fixture["history_path"])
        encounter = self._read_json(fixture, fixture["encounter_relative"])
        tracker = self._read_json(fixture, "party_tracker.json")
        encounter["combat_round"] = 2
        encounter["current_round"] = 2
        encounter["combat_phase"] = "PC_PHASE"
        encounter["openingEnemyBatchPending"] = False
        entries = tuple(
            EnemyAttackLedgerEntry(
                actor=CombatantIdentity("Practice Goblin", "enemy"),
                action_name="Claw",
                target=CombatantIdentity(name, "player"),
                d20=15,
                attack_total=17,
                armor_class=15,
                hit=True,
                critical=False,
                damage_dice_rolls=(2,),
                damage_total=2,
                damage_type="slashing",
                target_hp_before=20,
                target_hp_after=18,
                target_status_after="alive",
                target_max_hp=20,
            )
            for name in names
        )
        ledger = EnemyResolutionLedger(
            encounter_id=fixture["encounter_id"],
            round_number=1,
            batch_id="fixture-enemy-batch",
            batch_kind="enemy_phase",
            seed=17,
            entries=entries,
            bloodied=(),
            departures=(
                EnemyDeparture(
                    CombatantIdentity("Practice Goblin", "enemy"), "surrendered"
                ),
            ),
        )
        narration = NarrationResult(
            text="The Practice Goblin yields.", source="template"
        )
        application = apply_enemy_batch(
            ledger,
            narration,
            user_input_text="Enemies turn.",
            turn_id=fixture["turn_id"],
            conversation_history=history[:-1],
            conversation_history_file=str(fixture["history_path"]),
            encounter_projection=encounter,
            path_manager=self._path_manager(fixture),
            read_json=lambda path: self._read_json(fixture, path),
            write_json=lambda path, payload: self._write_json(
                fixture, path, payload
            ),
            party_tracker_data=tracker,
            calculate_xp_for_encounter=lambda *_args: ("25 XP each", 25),
            check_all_monsters_defeated=lambda _encounter: True,
            validate_character=lambda *_args: True,
        )
        sync_committed_combat_turn(application.encounter_projection, None)
        fixture["publication_ids"].append(application.applied_id)
        publish_combat_narration(
            narration.text,
            applied_id=application.applied_id,
            emit=fixture["outputs"].append,
            flush=lambda: fixture["flushes"].append(application.applied_id),
        )

    def _run_fixture_turn(self, fixture, path):
        if path == "normal":
            return self._run_normal_fixture_turn(fixture)
        if path == "enemy_batch":
            return self._run_enemy_batch_fixture_turn(fixture)
        raise AssertionError("unexpected commit path: %s" % path)

    def _durable_snapshot(self, fixture):
        encounter = safe_read_json(str(fixture["encounter_path"]))
        characters = {
            name: safe_read_json(str(path))
            for name, path in fixture["character_paths"].items()
        }
        return encounter, characters

    def _assert_snapshot(self, fixture, point, applied_id, path):
        encounter, characters = self._durable_snapshot(fixture)
        if point == "before_first_character_write":
            marked_names = set()
        elif point.startswith("after_character_write:"):
            count = int(point.split(":", 1)[1])
            marked_names = set(sorted(fixture["names"], key=str.casefold)[:count])
        else:
            marked_names = set(fixture["names"])
        receipt_expected = point in {
            "after_encounter_write",
            "after_phase_sync",
            "during_success_publication",
            "after_success_publication",
        }
        self.assertEqual(
            [read_character_applied_id(characters[name]) for name in fixture["names"]],
            [applied_id if name in marked_names else None for name in fixture["names"]],
        )
        self.assertEqual(len(read_turn_receipts(encounter)), 1 if receipt_expected else 0)
        if receipt_expected:
            self.assertEqual(read_turn_receipts(encounter)[0]["applied_id"], applied_id)
            self.assertEqual(encounter["combat_round"], 2)
            self.assertEqual(encounter["combat_phase"], "PC_PHASE")
            if path == "normal":
                self.assertEqual(encounter["creatures"][-1]["currentHitPoints"], 7)
                self.assertEqual(encounter["creatures"][-1]["status"], "alive")
            else:
                self.assertEqual(encounter["creatures"][-1]["currentHitPoints"], 10)
                self.assertEqual(encounter["creatures"][-1]["status"], "defeated")
        else:
            self.assertNotIn("turn_receipts", encounter)
            self.assertEqual(encounter["combat_round"], 1)
            self.assertEqual(encounter["combat_phase"], "ENEMY_PHASE")
            self.assertEqual(encounter["creatures"][-1]["currentHitPoints"], 10)
        for name, character in characters.items():
            changed = name in marked_names
            self.assertEqual(character["hitPoints"], 18 if changed else 20)
            self.assertEqual(character["experience_points"], 125 if changed else 100)
            self.assertEqual(
                character["gold"],
                (7 if changed else 0) if path == "normal" else 0,
            )
            self.assertEqual(
                character["condition_affected"],
                (["poisoned"] if changed else []) if path == "normal" else [],
            )
        return encounter, characters

    def test_fault_boundaries_restart_from_disk_without_duplicate_effects(self):
        party_shapes = (
            ["Acheron"],
            ["Acheron", "Merisiel", "Kira", "Vitreol"],
        )
        paths = ("normal", "enemy_batch")
        for names in party_shapes:
            boundaries = ["before_first_character_write"]
            boundaries.extend(
                "after_character_write:%d" % ordinal
                for ordinal in range(1, len(names) + 1)
            )
            boundaries.extend((
                "after_encounter_write",
                "after_phase_sync",
                "during_success_publication",
                "after_success_publication",
            ))
            for path in paths:
                for fault_point in boundaries:
                    fixture = self._new_fixture(names)
                    self.addCleanup(fixture["temporary"].cleanup)
                    with self.subTest(
                        path=path, party_size=len(names), fault_point=fault_point
                    ):
                        with (
                            patch.object(
                                model_config,
                                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                                True,
                            ),
                            patch.object(
                                turn_fault_injection,
                                "repository_root",
                                return_value=fixture["runtime_root"],
                            ),
                            patch.dict(
                                os.environ, {"NEQ_COMBAT_FAULT_POINT": fault_point}
                            ),
                        ):
                            with self.assertRaises(
                                turn_fault_injection.CombatTurnFaultInjected
                            ) as raised:
                                self._run_fixture_turn(fixture, path)
                        self.assertEqual(raised.exception.fault_point, fault_point)
                        applied_id = compute_applied_id(
                            fixture["encounter_id"], fixture["turn_id"]
                        )
                        encounter_before, _characters_before = self._assert_snapshot(
                            fixture, fault_point, applied_id, path
                        )

                        persisted_history = self._read_json(
                            fixture, fixture["history_path"]
                        )
                        accepted = next(
                            message for message in persisted_history
                            if isinstance(message, dict)
                            and message.get("role") == "user"
                            and message.get("turn_id") == fixture["turn_id"]
                        )
                        manifest = accepted["_combat_turn_commit_manifest"]
                        self.assertEqual(
                            set(manifest),
                            {
                                "schema_version",
                                "turn_id",
                                "applied_id",
                                "encounter_id",
                                "path",
                                "character_effects",
                                "encounter_projection",
                                "receipt",
                                "staged_rewards",
                                "success_narration",
                            },
                        )
                        self.assertEqual(manifest["path"], path)
                        self.assertEqual(manifest["turn_id"], fixture["turn_id"])
                        self.assertEqual(manifest["applied_id"], applied_id)
                        self.assertEqual(
                            [row["character_name"] for row in manifest["character_effects"]],
                            sorted(names, key=str.casefold),
                        )
                        self.assertEqual(
                            manifest["staged_rewards"],
                            [
                                {
                                    "character_name": name,
                                    "experience_points_delta": 25,
                                }
                                for name in sorted(names, key=str.casefold)
                            ],
                        )
                        self.assertEqual(
                            manifest["receipt"],
                            {
                                "schema_version": 1,
                                "turn_id": fixture["turn_id"],
                                "applied_id": applied_id,
                                "encounter_id": fixture["encounter_id"],
                                "combat_round": 2,
                            },
                        )
                        self.assertEqual(
                            manifest["encounter_projection"]["combat_round"], 2
                        )
                        self.assertEqual(
                            manifest["encounter_projection"]["combat_phase"],
                            "PC_PHASE",
                        )
                        self.assertEqual(
                            read_turn_receipts(manifest["encounter_projection"]), []
                        )
                        expected_narration = (
                            "The party's actions resolve."
                            if path == "normal" else "The Practice Goblin yields."
                        )
                        self.assertEqual(
                            manifest["success_narration"]["text"], expected_narration
                        )

                        character_counts_before = {
                            name: fixture["character_write_events"].count(name)
                            for name in names
                        }
                        encounter_writes_before = len(fixture["encounter_write_events"])
                        tracker_writes_before = len(fixture["tracker_write_events"])
                        provider_calls = []

                        def recording_llm_call(*args, **kwargs):
                            provider_calls.append((args, kwargs))
                            raise AssertionError("provider call during manifest recovery")

                        with (
                            patch.dict(os.environ, {"NEQ_COMBAT_FAULT_POINT": ""}),
                            patch("utils.llm_router.llm.call", side_effect=recording_llm_call),
                        ):
                            restarted_bootstrap = self._bootstrap_from_disk(fixture)
                        self.assertEqual(provider_calls, [])
                        self.assertEqual(
                            restarted_bootstrap.recovered_pending_turn,
                            not bool(read_turn_receipts(encounter_before)),
                        )
                        self.assertEqual(
                            restarted_bootstrap.conversation_history[
                                next(
                                    index for index, message in enumerate(
                                        restarted_bootstrap.conversation_history
                                    )
                                    if isinstance(message, dict)
                                    and message.get("turn_id") == fixture["turn_id"]
                                )
                            ]["turn_id"],
                            fixture["turn_id"],
                        )
                        expected_receipt_write = int(not any(read_turn_receipts(encounter_before)))
                        self.assertEqual(
                            len(fixture["encounter_write_events"]),
                            encounter_writes_before + expected_receipt_write,
                        )
                        for name in names:
                            self.assertEqual(
                                fixture["character_write_events"].count(name), 1
                            )
                            if fault_point in {
                                "after_encounter_write",
                                "after_phase_sync",
                                "during_success_publication",
                                "after_success_publication",
                            }:
                                self.assertEqual(
                                    fixture["character_write_events"].count(name),
                                    character_counts_before[name],
                                )
                        self.assertEqual(
                            len(fixture["tracker_write_events"]), tracker_writes_before
                        )

                        final_encounter, final_characters = self._assert_snapshot(
                            fixture, "after_phase_sync", applied_id, path
                        )
                        self.assertEqual(len(read_turn_receipts(final_encounter)), 1)
                        self.assertEqual(
                            read_turn_receipts(final_encounter)[0]["turn_id"],
                            fixture["turn_id"],
                        )
                        for character in final_characters.values():
                            self.assertEqual(read_character_applied_id(character), applied_id)
                        self.assertEqual(
                            restarted_bootstrap.encounter_data["combat_round"], 2
                        )
                        self.assertEqual(
                            restarted_bootstrap.multi_pc_manager.current_round, 2
                        )
                        self.assertEqual(
                            restarted_bootstrap.multi_pc_manager.combat_phase,
                            "PC_PHASE",
                        )

                        pre_receipt = not bool(read_turn_receipts(encounter_before))
                        expected_output_count = 1
                        if not pre_receipt and fault_point in {
                            "after_encounter_write", "after_phase_sync"
                        }:
                            expected_output_count = 0
                        self.assertEqual(
                            len(fixture["publication_ids"]), expected_output_count
                        )
                        self.assertEqual(
                            fixture["publication_ids"],
                            [applied_id] * expected_output_count,
                        )
                        self.assertEqual(
                            fixture["outputs"],
                            ["Dungeon Master: " + expected_narration]
                            * expected_output_count,
                        )
                        expected_flushes = expected_output_count
                        if fault_point == "during_success_publication":
                            expected_flushes = 0
                        self.assertEqual(
                            fixture["flushes"], [applied_id] * expected_flushes
                        )

                        if pre_receipt:
                            next_turn = build_accepted_input_record("Enemies turn.")
                            self.assertNotEqual(
                                next_turn["turn_id"], fixture["turn_id"]
                            )
                            self.assertEqual(len(read_turn_receipts(final_encounter)), 1)

    def test_bootstrap_rejects_corrupt_pending_manifest_before_recovery_writes(self):
        fixture = self._new_fixture(["Acheron"])
        self.addCleanup(fixture["temporary"].cleanup)
        history = self._read_json(fixture, fixture["history_path"])
        history[-1]["_combat_turn_commit_manifest"] = {
            "schema_version": 1,
            "turn_id": fixture["turn_id"],
        }
        self._write_json(fixture, fixture["history_path"], history)
        initial_encounter, initial_characters = self._durable_snapshot(fixture)
        encounter_write_count = len(fixture["encounter_write_events"])
        character_write_counts = list(fixture["character_write_events"])
        provider_calls = []

        def forbidden_provider_call(*args, **kwargs):
            provider_calls.append((args, kwargs))
            raise AssertionError("provider call during invalid-manifest bootstrap")

        with (
            patch.dict(os.environ, {"NEQ_COMBAT_FAULT_POINT": ""}),
            patch("utils.llm_router.llm.call", side_effect=forbidden_provider_call),
            self.assertRaises(CombatTurnRecoveryError),
        ):
            self._bootstrap_from_disk(fixture)

        self.assertEqual(provider_calls, [])
        self.assertEqual(
            len(fixture["encounter_write_events"]), encounter_write_count
        )
        self.assertEqual(fixture["character_write_events"], character_write_counts)
        self.assertEqual(len(fixture["tracker_write_events"]), 0)
        encounter_after, characters_after = self._durable_snapshot(fixture)
        self.assertEqual(encounter_after, initial_encounter)
        self.assertEqual(characters_after, initial_characters)

    def test_flag_off_ignores_fault_without_resolving_root_or_reading_selector(self):
        fixture = self._new_fixture(["Acheron"])
        self.addCleanup(fixture["temporary"].cleanup)
        self.assertIs(model_config.COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED, False)
        with (
            patch.object(model_config, "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED", False),
            patch.object(turn_fault_injection, "repository_root") as root_resolver,
            patch.object(turn_fault_injection, "_read_requested_fault_point") as read_selector,
            patch.dict(os.environ, {"NEQ_COMBAT_FAULT_POINT": "before_first_character_write"}),
        ):
            self._run_fixture_turn(fixture, "normal")
        root_resolver.assert_not_called()
        read_selector.assert_not_called()
        self.assertEqual(len(read_turn_receipts(self._durable_snapshot(fixture)[0])), 1)
        PROCESS_TRIPWIRES.assert_untouched(self)

    def test_enabled_fault_outside_capture_tree_is_logged_and_ignored(self):
        fixture = self._new_fixture(["Acheron"])
        self.addCleanup(fixture["temporary"].cleanup)
        with (
            patch.object(model_config, "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED", True),
            patch.object(turn_fault_injection, "repository_root", return_value=REPO_ROOT),
            patch.object(turn_fault_injection, "_read_requested_fault_point") as read_selector,
            patch.object(turn_fault_injection, "_LOGGED_REJECTIONS", set()),
            patch.object(turn_fault_injection._LOGGER, "error") as error_log,
            patch.dict(os.environ, {"NEQ_COMBAT_FAULT_POINT": "before_first_character_write"}),
        ):
            self._run_fixture_turn(fixture, "normal")
        read_selector.assert_not_called()
        error_log.assert_called_once()
        self.assertIn("runtime_root_outside_tmp_combat_capture", error_log.call_args.args[1])
        self.assertEqual(len(read_turn_receipts(self._durable_snapshot(fixture)[0])), 1)
        PROCESS_TRIPWIRES.assert_untouched(self)


class CombatHistoryProviderBoundaryTests(unittest.TestCase):
    def tearDown(self):
        PROCESS_TRIPWIRES.assert_untouched(self)

    def test_combat_history_provider_paths_exclude_private_message_metadata(self):
        provider_calls = []

        def recording_llm_call(task, messages, **_kwargs):
            provider_calls.append({"task": task, "messages": copy.deepcopy(messages)})
            joined_content = "\n".join(
                str(message.get("content", ""))
                for message in messages
                if isinstance(message, dict)
            )
            if task == "combat_main" and "--- ROUND INFO ---" in joined_content:
                return "**Live Initiative Tracker:**\n- Acheron (18)"
            if task == "combat_main":
                return '{"narration":"The turn is ready.","actions":[]}'
            if task == "combat_validation":
                return '{"valid":true,"feedback":{}}'
            if task == "combat_summary":
                return "A vivid battle summary."
            if task == "compression" and "Convert this combat round" in joined_content:
                return '{"round":1,"actions":[],"narrative_highlights":[]}'
            if task == "compression":
                return "@T=CS/v2 compact combat state"
            raise AssertionError("unexpected task: %s" % task)

        # Drive accepted-input persistence and the provider retry stage for both
        # party shapes through the same normal-turn orchestration.
        party_shapes = (
            (1, ["Acheron"]),
            (4, ["Acheron", "Merisiel", "Kira", "Vitreol"]),
        )
        for party_size, names in party_shapes:
            encounter_id = "provider-fixture-%d-pc" % party_size
            encounter = {
                "encounterId": encounter_id,
                "combat_round": 1,
                "creatures": [{"name": name, "type": "player"} for name in names],
            }
            manager = (
                SimpleNamespace(current_pc_name=names[0], combat_phase="PC_PHASE")
                if party_size == 4 else None
            )
            persisted_histories = []
            session = SimpleNamespace(
                active_pc=None,
                bind_history=lambda _history: None,
                set_phase=lambda _phase: None,
            )
            iteration = CombatTurnIterationResult(
                session=session,
                encounter_data=encounter,
                multi_pc_manager=manager,
                party_tracker_data={"partyMembers": names, "active_character": names[0]},
                conversation_history=[{"role": "system", "content": "Legacy combat prompt bytes"}],
                npc_templates={},
                player_file="characters/acheron.json",
                fresh_player_data={},
                current_hp=20,
                max_hp=20,
                player_name_display=names[0],
                current_round_trace_start=0.0,
                user_input_text="attack",
                path_manager=None,
                player_info={"name": names[0]},
            )

            def assemble_context(_inputs):
                return SimpleNamespace(
                    return_early=False,
                    encounter_data=encounter,
                    player_info={"name": names[0]},
                    player_file="characters/acheron.json",
                    path_manager=None,
                    fresh_player_data={},
                    current_hp=20,
                    max_hp=20,
                    user_input_text="attack",
                    user_prompt="Exact prompt bytes for %d PCs" % party_size,
                )

            normal_dependencies = CombatNormalTurnDependencies(
                input_phase_gate=lambda text, **_kwargs: SimpleNamespace(
                    control_action="proceed", raw_input=text, clean_input=text.strip(),
                    input_actor_name=None, pc_phase_started=False,
                ),
                phase_gate_io_factory=lambda _manager: None,
                initiative_gate=lambda *_args, **_kwargs: None,
                fast_command_stage=lambda **kwargs: SimpleNamespace(
                    control_action="proceed", user_input_text=kwargs["user_input_text"]
                ),
                fast_command_io_factory=lambda: None,
                deterministic_command_stage=lambda **_kwargs: SimpleNamespace(
                    control_action="proceed", status="ready"
                ),
                deterministic_command_io_factory=lambda *_args: None,
                character_stat_command=lambda *_args: False,
                character_stat_io_factory=lambda _path_manager: None,
                normalize_character_name=lambda name: name.lower(),
                safe_json_load=lambda _path: {},
                pc_action_enabled=False,
                perf_counter=lambda: 1.0,
                trace_decision=lambda *_args, **_kwargs: None,
                enhance_inventory_context=lambda inputs: SimpleNamespace(
                    user_input_text=inputs.user_input_text,
                    fresh_player_data=inputs.preexisting_player_data,
                ),
                enhance_player_input_with_inventory=lambda text, *_args, **_kwargs: text,
                assemble_context=assemble_context,
                clean_old_dm_notes=lambda messages: messages,
                clean_combat_state_blocks=lambda messages: messages,
                save_json=lambda _path, history: persisted_histories.append(copy.deepcopy(history)),
                debug=lambda *_args, **_kwargs: None,
                emit=lambda _message: None,
                flush=lambda: None,
            )
            prepared = prepare_combat_normal_turn(
                CombatNormalTurnInputs(
                    iteration=iteration,
                    encounter_id=encounter_id,
                    json_file_path="modules/encounters/encounter_%s.json" % encounter_id,
                    conversation_history_file="modules/conversation_history/history.json",
                    location_info={},
                ),
                normal_dependencies,
            )
            self.assertEqual(prepared.control_action, "proceed")
            self.assertIn("turn_id", prepared.conversation_history[-1])

            retry_dependencies = CombatRetryDependencies(
                client=None,
                use_gpt5_models=False,
                gpt5_mini_model="fixture-mini",
                gpt5_high_reasoning_on_retry=True,
                combat_main_model="fixture-main",
                get_completion_params=lambda *_args, **_kwargs: {},
                get_temperature=lambda *_args, **_kwargs: 0.2,
                perf_counter=lambda: 1.0,
                trace_stage=lambda *_args, **_kwargs: None,
                trace_provider_call=lambda *_args, **_kwargs: None,
                export_open=lambda *_args, **_kwargs: None,
                makedirs=lambda *_args, **_kwargs: None,
                emit=lambda _message: None,
                debug=lambda *_args, **_kwargs: None,
                warning=lambda *_args, **_kwargs: None,
                error=lambda *_args, **_kwargs: None,
                usage_tracking_available=False,
                track_usage=lambda _response: None,
                is_valid_json=lambda _value: True,
                check_multiple_update_encounter=lambda _actions: False,
                make_multiple_update_feedback=lambda _parsed: "retry",
                validate_combatant_integrity=lambda *_args, **_kwargs: True,
                validate_combat_response=lambda *_args, **_kwargs: True,
                update_status=lambda *_args, **_kwargs: None,
                llm_call=recording_llm_call,
                receipt_observer_factory=lambda **_kwargs: (lambda *_args: None),
            )
            retry_result = run_combat_provider_retry_stage(
                CombatRetryInputs(
                    conversation_history=prepared.conversation_history,
                    initial_conversation_length=len(prepared.conversation_history),
                    encounter_data=prepared.encounter_data,
                    party_tracker_data=prepared.party_tracker_data,
                    multi_pc_manager=manager,
                    user_input_text="attack",
                    max_retries=1,
                ),
                retry_dependencies,
            )
            self.assertTrue(retry_result.valid_response)
            self.assertEqual(retry_result.retry_request_history[-1]["content"], "Exact prompt bytes for %d PCs" % party_size)

        # Exercise the independent validation provider boundary with durable
        # history supplied directly, including a turn identity in its context.
        def validation_precheck(*_args, **_kwargs):
            return True, ""

        validation_dependencies = CombatValidationDependencies(
            parse_json_safely=json.loads,
            phase_precheck=validation_precheck,
            replay_precheck=lambda *_args, **_kwargs: (True, ""),
            narration_precheck=validation_precheck,
            enemy_boundary_precheck=validation_precheck,
            truth_pack_builder=lambda *_args, **_kwargs: [],
            canonical_attack_facts_builder=lambda *_args, **_kwargs: [],
            read_prompt=lambda path: "validation prompt: " + path,
            compressed_combat=False,
            compression_enabled=False,
            compression_threshold_chars=100000,
            compression_decision=lambda **_kwargs: (False, "fixture_uncompressed"),
            telemetry_builder=lambda **kwargs: kwargs,
            client=None,
            validation_model="fixture-validation",
            completion_params=lambda *_args, **_kwargs: {},
            trace_provider_call=lambda *_args, **_kwargs: None,
            sanitize_for_logging=str,
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            emit_console=lambda _message: None,
            usage_tracking_available=False,
            track_usage=lambda _response: None,
            log_api_call=lambda *_args, **_kwargs: None,
            export_open=lambda *_args, **_kwargs: None,
            makedirs=lambda *_args, **_kwargs: None,
            now=lambda: None,
            format_log_timestamp=lambda *_args, **_kwargs: "fixture-time",
            perf_counter=lambda: 1.0,
            llm_call=recording_llm_call,
            receipt_observer_factory=lambda **_kwargs: (lambda *_args: None),
            debug_dumps_enabled=lambda: False,
        )
        candidate_response = '{"narration":"The enemy advances.","actions":[]}'
        validation_history = [{"role": "system", "content": "validation system"}]
        for index in range(6):
            validation_history.extend([
                {"role": "user", "content": "prior player %d" % index},
                {"role": "assistant", "content": "prior DM %d" % index},
            ])
        validation_history.append(build_accepted_input_record("Enemies turn.", turn_id=FIXED_TURN_ID))
        validation_history.append({"role": "assistant", "content": candidate_response})
        self.assertIs(
            validate_combat_response(
                candidate_response,
                {"encounterId": FIXED_ENCOUNTER_ID, "creatures": []},
                "Enemies turn.",
                validation_history,
                dependencies=validation_dependencies,
            ),
            True,
        )

        # Startup resume and initial-scene provider calls both consume history
        # records; they must leave the persisted identity on disk but omit it
        # from the outgoing messages.
        startup_dependency_values = {
            "client": None,
            "resume_config": lambda: (False, "fixture-model"),
            "combat_main_model": "fixture-model",
            "completion_params": lambda *_args, **_kwargs: {},
            "get_temperature": lambda *_args, **_kwargs: 0.2,
            "get_initiative_order": lambda _encounter: "Acheron (18)",
            "get_multi_pc_initiative_narrative": lambda _manager: "",
            "modify_prompt_for_multi_pc": lambda prompt, *_args: prompt,
            "is_valid_json": lambda _value: True,
            "validate_response": lambda *_args, **_kwargs: True,
            "save_json": lambda *_args, **_kwargs: None,
            "export_open": lambda *_args, **_kwargs: None,
            "perf_counter": lambda: 1.0,
            "trace_stage": lambda *_args, **_kwargs: None,
            "trace_provider_call": lambda *_args, **_kwargs: None,
            "usage_tracking_available": False,
            "track_usage": lambda _response: None,
            "log_api_call": lambda *_args, **_kwargs: None,
            "emit": lambda _message: None,
            "flush": lambda: None,
            "debug": lambda *_args, **_kwargs: None,
            "info": lambda *_args, **_kwargs: None,
            "warning": lambda *_args, **_kwargs: None,
            "error": lambda *_args, **_kwargs: None,
            "publish_narration": lambda *_args, **_kwargs: None,
            "publish_output": lambda *_args, **_kwargs: None,
            "debug_dumps_enabled": lambda: False,
            "llm_call": recording_llm_call,
            "receipt_observer_factory": lambda **_kwargs: (lambda *_args: None),
        }
        startup_dependencies = SimpleNamespace(**startup_dependency_values)
        startup_history = [
            {"role": "system", "content": "resumed system"},
            dict(build_accepted_input_record("Persisted action", turn_id=FIXED_TURN_ID), internal_state="private"),
        ]
        _run_resume_narrative(
            SimpleNamespace(
                history=startup_history,
                history_file="fixture-history.json",
                temperature_used=None,
                recovered_pending_turn=False,
                encounter_data={"creatures": []},
                session=None,
            ),
            startup_dependencies,
        )
        self.assertIn("turn_id", startup_history[1])

        initial_history = [
            {"role": "system", "content": "initial system"},
            dict(build_accepted_input_record("Prior accepted action", turn_id=FIXED_TURN_ID), internal_state="private"),
        ]
        _run_initial_scene_generation(
            CombatStartupNarrativeInputs(
                history=initial_history,
                history_file="fixture-history.json",
                is_resuming=False,
                encounter_data={"encounterId": FIXED_ENCOUNTER_ID, "creatures": []},
                party_tracker_data={"worldConditions": {}},
                multi_pc_manager=None,
                dynamic_state="fixture dynamic state",
                preroll_text="fixture prerolls",
                session=SimpleNamespace(bind_history=lambda _history: None),
            ),
            startup_dependencies,
        )
        self.assertIn("turn_id", initial_history[1])

        # The compressor, round summarizer, dialogue summary, and initiative
        # tracker reduce history to content before constructing provider calls.
        with patch("os.makedirs"):
            combat_manager = _load_combat_manager_for_unit_tests()
        from core.ai import combat_compression_engine
        from core.combat import initiative_tracker_ai

        with (
            patch.object(combat_manager.llm, "call", side_effect=recording_llm_call),
            patch.object(combat_compression_engine.llm, "call", side_effect=recording_llm_call),
            patch.object(combat_manager, "make_legacy_receipt_observer", return_value=lambda *_args, **_kwargs: None),
            patch.object(combat_manager, "error", return_value=None),
            patch.object(combat_compression_engine, "make_legacy_receipt_observer", return_value=lambda *_args, **_kwargs: None),
            patch.object(initiative_tracker_ai, "make_legacy_receipt_observer", return_value=lambda *_args, **_kwargs: None),
        ):
            compressor = combat_compression_engine.CombatCompressor(enable_caching=False)
            self.assertTrue(compressor.compress("A long combat-state message").startswith("@T=CS/v2"))

            raw_compression_history = [
                {
                    "role": "user",
                    "content": "--- ROUND INFO ---\n--- CREATURE STATES ---\n--- DICE POOLS ---",
                    "turn_id": FIXED_TURN_ID,
                    "internal_receipt_context": "private",
                },
            ] + [
                {"role": "assistant", "content": "Earlier combat narration %d" % index}
                for index in range(5)
            ]
            compressor_without_cache = combat_compression_engine.CombatCompressor(
                enable_caching=False
            )
            with patch.object(
                combat_compression_engine,
                "CombatCompressor",
                return_value=compressor_without_cache,
            ):
                projected_history = combat_compression_engine.compress_combat_history(
                    raw_compression_history
                )
            self.assertTrue(all("turn_id" not in message for message in projected_history))
            self.assertTrue(all("internal_receipt_context" not in message for message in projected_history))

            from core.ai.combat_compressor import CombatUserMessageCompressor

            user_message_compressor = CombatUserMessageCompressor(
                cache_file="tmp/router-rollout/g7/compressor-cache-unused.json",
                max_workers=1,
            )
            user_message_compressor.save_cache = lambda: None
            compressed_messages = user_message_compressor.process_combat_conversation(
                raw_compression_history
            )
            self.assertTrue(all("turn_id" not in message for message in compressed_messages))
            self.assertTrue(all("internal_receipt_context" not in message for message in compressed_messages))

            round_history = [
                {"role": "user", "content": "COMBAT ROUND 1: Round: 1; attacks resolved.", "turn_id": FIXED_TURN_ID},
                {"role": "assistant", "content": '{"combat_round":1,"narration":"A hit."}'},
            ]
            combat_manager.compress_old_combat_rounds(
                round_history, current_round=3, keep_recent_rounds=1
            )
            combat_manager.generate_combat_round_summary(1, round_history)
            combat_manager.summarize_dialogue(
                round_history,
                None,
                {"worldConditions": {
                    "currentLocationId": "fixture-location",
                    "year": 1,
                    "month": "January",
                    "day": 1,
                    "time": "Noon",
                }},
            )
            initiative_tracker_ai.generate_live_initiative_tracker(
                {
                    "combat_round": 1,
                    "creatures": [{"name": "Acheron", "type": "player", "initiative": 18}],
                },
                [
                    {"role": "user", "content": "Round: 1 player action", "turn_id": FIXED_TURN_ID},
                    {"role": "assistant", "content": '{"combat_round":1,"narration":"The strike lands."}'},
                ],
                current_round=1,
            )

        task_counts = {
            task: sum(1 for call in provider_calls if call["task"] == task)
            for task in {call["task"] for call in provider_calls}
        }
        self.assertGreaterEqual(task_counts.get("combat_main", 0), 5)
        self.assertEqual(task_counts.get("combat_validation"), 1)
        self.assertEqual(task_counts.get("combat_summary"), 1)
        self.assertGreaterEqual(task_counts.get("compression", 0), 5)
        for party_size in (1, 4):
            expected_prompt = "Exact prompt bytes for %d PCs" % party_size
            self.assertTrue(any(
                call["task"] == "combat_main"
                and any(message.get("content") == expected_prompt for message in call["messages"])
                for call in provider_calls
            ))
        for call in provider_calls:
            for message_index, message in enumerate(call["messages"]):
                with self.subTest(task=call["task"], message_index=message_index):
                    self.assertIsInstance(message, dict)
                    self.assertTrue(
                        set(message).issubset(STANDARD_PROVIDER_MESSAGE_FIELDS),
                        "non-standard provider message keys: %r" % (set(message) - STANDARD_PROVIDER_MESSAGE_FIELDS),
                    )
                    self.assertNotIn("turn_id", message)


class CombatBootstrapResumeNarrativeTests(unittest.TestCase):
    """Manifest recovery skips re-engagement while ordinary resumes retain it."""

    def tearDown(self):
        PROCESS_TRIPWIRES.assert_untouched(self)

    @staticmethod
    def _inputs(history, *, recovered_pending_turn):
        return CombatStartupNarrativeInputs(
            history=history,
            history_file="fixture-history.json",
            is_resuming=True,
            encounter_data={"encounterId": FIXED_ENCOUNTER_ID, "creatures": []},
            party_tracker_data={"partyMembers": ["Acheron"]},
            multi_pc_manager=None,
            dynamic_state="fixture dynamic state",
            preroll_text="fixture prerolls",
            session=SimpleNamespace(),
            recovered_pending_turn=recovered_pending_turn,
        )

    @staticmethod
    def _dependencies(provider_calls, publications, saved_histories, observer_calls):
        def fake_llm_call(task, messages, **_kwargs):
            provider_calls.append((task, copy.deepcopy(messages)))
            return '{"narration":"The scene is re-established.","actions":[]}'

        return SimpleNamespace(
            client=None,
            resume_config=lambda: (False, "fixture-model"),
            combat_main_model="fixture-model",
            completion_params=lambda *_args, **_kwargs: {},
            get_temperature=lambda *_args, **_kwargs: 0.2,
            get_initiative_order=lambda _encounter: "Acheron (18)",
            get_multi_pc_initiative_narrative=lambda _manager: "",
            modify_prompt_for_multi_pc=lambda prompt, *_args: prompt,
            is_valid_json=lambda _value: True,
            validate_response=lambda *_args, **_kwargs: True,
            save_json=lambda _path, saved_history: saved_histories.append(
                copy.deepcopy(saved_history)
            ),
            export_open=lambda *_args, **_kwargs: None,
            perf_counter=lambda: 1.0,
            trace_stage=lambda *_args, **_kwargs: None,
            trace_provider_call=lambda *_args, **_kwargs: None,
            usage_tracking_available=False,
            track_usage=lambda _response: None,
            log_api_call=lambda *_args, **_kwargs: None,
            emit=lambda _message: None,
            flush=lambda: None,
            debug=lambda *_args, **_kwargs: None,
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            publish_narration=lambda text, **_kwargs: publications.append(text),
            publish_output=lambda text, **_kwargs: publications.append(text),
            debug_dumps_enabled=lambda: False,
            llm_call=fake_llm_call,
            receipt_observer_factory=lambda **kwargs: (
                observer_calls.append(kwargs) or (lambda *_args, **_kwargs: None)
            ),
        )

    def test_pending_manifest_recovery_skips_second_narration_and_provider_call(self):
        history = [{"role": "system", "content": "resumed combat"}]
        provider_calls = []
        publications = ["stored recovery narration"]
        saved_histories = []
        observer_calls = []
        result = run_startup_narrative(
            self._inputs(history, recovered_pending_turn=True),
            self._dependencies(provider_calls, publications, saved_histories, observer_calls),
        )

        self.assertEqual(provider_calls, [])
        self.assertEqual(observer_calls, [])
        self.assertEqual(saved_histories, [])
        self.assertEqual(publications, ["stored recovery narration"])
        self.assertIs(result.history, history)
        self.assertTrue(result.is_resuming)

    def test_plain_resume_without_pending_manifest_keeps_reengagement(self):
        history = [{"role": "system", "content": "resumed combat"}]
        provider_calls = []
        publications = []
        saved_histories = []
        observer_calls = []
        run_startup_narrative(
            self._inputs(history, recovered_pending_turn=False),
            self._dependencies(provider_calls, publications, saved_histories, observer_calls),
        )

        self.assertEqual([task for task, _messages in provider_calls], ["combat_main"])
        self.assertEqual(len(observer_calls), 1)
        self.assertEqual(observer_calls[0]["trace_site"], "combat_reengage")
        self.assertEqual(publications, ["The scene is re-established."])
        self.assertEqual(len(saved_histories), 2)


if __name__ == "__main__":
    unittest.main()
