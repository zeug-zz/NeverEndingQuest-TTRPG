# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest C5 Regression - Combat hardening checks.

Focused checks for C4 behavior:
- Enemy-phase actor batching only includes valid living non-PC actors.
- Integrity validation accepts legal non-active PC targets.
- Integrity validation rejects unknown targets.
"""

import os
import sys
import types
import ast
import builtins
import io
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Install fatal SDK/network/outside-write guards before importing project owners.
from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()


class _PrivateRootReadDenied(BaseException):
    """Fatal sentinel for attempts to read private root fixtures/configuration."""


def _is_private_root_read(path):
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = Path(PROJECT_ROOT) / candidate
        return candidate.parent.resolve() == Path(PROJECT_ROOT).resolve() and candidate.name in {
            "config.py",
            "party_tracker.json",
        }
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    """Deny root config/party reads while allowing explicitly supplied fixtures."""
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    denied = []

    def check(path, operation):
        if _is_private_root_read(path):
            denied.append(operation)
            raise _PrivateRootReadDenied("private root read denied: " + operation)

    def guarded_open(path, mode="r", *args, **kwargs):
        check(path, "builtins.open")
        return real_open(path, mode, *args, **kwargs)

    def guarded_io_open(path, mode="r", *args, **kwargs):
        check(path, "io.open")
        return real_io_open(path, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        check(path, "os.open")
        return real_os_open(path, flags, *args, **kwargs)

    patches = [
        patch("builtins.open", guarded_open),
        patch("io.open", guarded_io_open),
        patch("os.open", guarded_os_open),
    ]
    for patcher in patches:
        patcher.start()
    return patches, denied


PRIVATE_READ_PATCHES, PRIVATE_READ_DENIALS = _arm_private_root_read_guard()


from core.managers.multi_pc_combat import Combatant, CombatantType, TurnQueueManager


def _load_combat_runtime_sources():
    """Load all extracted combat-manager stages for source-contract checks."""
    source_paths = (
        "core/combat/combat_manager.py",
        "core/combat/prompts.py",
        "core/combat/turn.py",
        "core/combat/persistence.py",
        "core/combat/commands.py",
        "core/combat/decisions.py",
    )
    parts = []
    for path in source_paths:
        with open(os.path.join(PROJECT_ROOT, path), "r", encoding="utf-8") as handle:
            parts.append(handle.read())
    return "\n".join(parts)


def _function_node(source, function_name):
    tree = ast.parse(source)
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )


def _call_nodes(node, function_name):
    return [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and ((isinstance(call.func, ast.Name) and call.func.id == function_name)
             or (isinstance(call.func, ast.Attribute) and call.func.attr == function_name))
    ]


def _action_type_branch(node, action_name):
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.If) or not isinstance(candidate.test, ast.Compare):
            continue
        test = candidate.test
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "action_type"
            and test.ops
            and isinstance(test.ops[0], ast.Eq)
            and test.comparators
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == action_name
        ):
            return candidate
    raise AssertionError(f"Missing action branch for {action_name}")


def _load_main_helper_namespace():
    """Load selected pure helper functions from main.py via AST."""
    main_path = os.path.join(PROJECT_ROOT, "main.py")
    with open(main_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename="main.py")
    helper_names = {
        "_normalize_combat_command_input",
        "_is_combat_only_command",
        "get_noncombat_guard_message",
        "get_validation_retry_exhaustion_message",
    }

    helper_defs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]

    helper_module = ast.Module(body=helper_defs, type_ignores=[])
    namespace = {}
    exec(compile(helper_module, filename="main.py", mode="exec"), namespace)
    return namespace


def _load_integrity_validator():
    """Execute the actual validator and its complete pure helper closure via AST."""
    source_path = os.path.join(PROJECT_ROOT, "core", "combat", "combat_manager.py")
    with open(source_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=source_path)

    required_names = {
        "_normalize_combatant_name",
        "_name_matches_authoritative_roster",
        "_collect_authoritative_combat_roster",
        "validate_combatant_integrity",
    }
    selected_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in required_names
    ]
    selected_names = {node.name for node in selected_nodes}
    if selected_names != required_names:
        raise AssertionError("Integrity validator source closure is incomplete")

    namespace = {
        "json": __import__("json"),
        # The validator's logger is only reached on its fail-open exception path;
        # make unexpected logger reachability loud without substituting behavior.
        "error": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected integrity-validator error logging")
        ),
    }
    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(helper_module, filename=source_path, mode="exec"), namespace)
    validator = namespace["validate_combatant_integrity"]
    expected_parameters = (
        "response_json_str", "encounter_data", "multi_pc_manager", "party_tracker_data"
    )
    if tuple(inspect.signature(validator).parameters) != expected_parameters:
        raise AssertionError("Integrity validator public signature changed")
    return validator


def _deny_root_fixture_read(path):
    """Exercise the private-read guard without reading a protected file."""
    with unittest.TestCase().assertRaises(_PrivateRootReadDenied):
        builtins.open(os.path.join(PROJECT_ROOT, path), "r", encoding="utf-8")


class TestC5HarnessSafety(unittest.TestCase):
    def test_actual_integrity_loader_uses_no_private_root_or_external_capability(self):
        _deny_root_fixture_read("config.py")
        _deny_root_fixture_read("party_tracker.json")

        validator = _load_integrity_validator()
        self.assertEqual(
            tuple(inspect.signature(validator).parameters),
            ("response_json_str", "encounter_data", "multi_pc_manager", "party_tracker_data"),
        )
        self.assertEqual(PRIVATE_READ_DENIALS[-2:], ["builtins.open", "builtins.open"])
        PROCESS_TRIPWIRES.assert_untouched(self)
        for name in ("openai.OpenAI", "socket.socket", "urlopen"):
            guard = PROCESS_TRIPWIRES.calls[name]
            with self.subTest(guard=name), self.assertRaises(TripwireFailure):
                guard()
            guard.reset_mock()

        outside_path = os.path.join(PROJECT_ROOT, "scripts", "c5-tripwire-must-not-write")
        for operation in (
            lambda: builtins.open(outside_path, "w", encoding="utf-8"),
            lambda: io.open(outside_path, "w", encoding="utf-8"),
            lambda: os.open(outside_path, os.O_CREAT | os.O_WRONLY),
            lambda: os.mkdir(outside_path),
        ):
            with self.assertRaises(TripwireFailure):
                operation()
        self.assertFalse(Path(outside_path).exists())
        PROCESS_TRIPWIRES.assert_untouched(self)


class TestC4Hardening(unittest.TestCase):
    """Regression tests for C4 combat hardening."""

    @classmethod
    def setUpClass(cls):
        cls.validate_integrity = staticmethod(_load_integrity_validator())

    def test_enemy_phase_actor_filter(self):
        manager = TurnQueueManager()
        manager.current_turn_index = 0
        manager.turn_queue = [
            Combatant("Goblin A", CombatantType.ENEMY, 15, 7, 7, 15, "alive"),
            Combatant("Fallen Orc", CombatantType.ENEMY, 12, 0, 15, 13, "dead"),
            Combatant("Guard Ally", CombatantType.NPC, 10, 12, 12, 14, "alive"),
            Combatant("Stunned Ally", CombatantType.NPC, 9, 0, 12, 13, "unconscious"),
            Combatant("Acheron", CombatantType.PC, 18, 21, 21, 16, "alive"),
        ]

        remaining = manager.get_remaining_enemies_for_round()
        self.assertEqual(remaining, ["Goblin A", "Guard Ally"])

    def test_enemy_phase_actor_filter_ignores_turn_pointer(self):
        manager = TurnQueueManager()
        manager.turn_queue = [
            Combatant("Goblin A", CombatantType.ENEMY, 19, 7, 7, 15, "alive"),
            Combatant("Acheron", CombatantType.PC, 16, 21, 21, 16, "alive"),
            Combatant("Guard Ally", CombatantType.NPC, 14, 12, 12, 14, "alive"),
            Combatant("Bandit B", CombatantType.ENEMY, 10, 11, 11, 12, "alive"),
        ]

        expected = ["Goblin A", "Guard Ally", "Bandit B"]

        manager.current_turn_index = 0
        self.assertEqual(manager.get_remaining_enemies_for_round(), expected)

        manager.current_turn_index = 2
        self.assertEqual(manager.get_remaining_enemies_for_round(), expected)

    def test_advance_turn_skips_defeated_and_unconscious(self):
        manager = TurnQueueManager()
        manager.current_turn_index = 0
        manager.turn_queue = [
            Combatant("Acheron", CombatantType.PC, 18, 21, 21, 16, "alive"),
            Combatant("Captured Bandit", CombatantType.ENEMY, 15, 1, 11, 12, "defeated"),
            Combatant("Downed Ally", CombatantType.NPC, 13, 0, 12, 14, "unconscious"),
            Combatant("Goblin A", CombatantType.ENEMY, 10, 7, 7, 15, "alive"),
        ]

        actor, rolled_over = manager.advance_turn()
        self.assertEqual(actor.name, "Goblin A")
        self.assertFalse(rolled_over)

    def test_integrity_accepts_non_active_pc_target(self):
        response = (
            '{"actions":[{"action":"updateCharacterInfo",'
            '"parameters":{"characterName":"Merisiel","changes":"Takes 6 damage."}}]}'
        )
        encounter_data = {
            "creatures": [
                {"name": "Goblin A", "type": "enemy"},
                {"name": "Guard Ally", "type": "npc"},
            ]
        }
        multi_pc_manager = types.SimpleNamespace(pc_states={"Acheron": {}, "Merisiel": {}})

        result = self.validate_integrity(
            response,
            encounter_data,
            multi_pc_manager=multi_pc_manager,
            party_tracker_data={},
        )
        self.assertTrue(result is True)

    def test_integrity_rejects_unknown_target(self):
        response = (
            '{"actions":[{"action":"updateCharacterInfo",'
            '"parameters":{"characterName":"Phantom Knight","changes":"Takes 5 damage."}}]}'
        )
        encounter_data = {
            "creatures": [
                {"name": "Goblin A", "type": "enemy"},
            ]
        }

        party_fixture = {"partyMembers": ["Acheron", "Merisiel"]}
        result = self.validate_integrity(
            response, encounter_data, multi_pc_manager=None, party_tracker_data=party_fixture
        )
        self.assertIsInstance(result, str)
        self.assertIn("INTEGRITY ERROR", result)
        self.assertIn("Phantom Knight", result)


class TestC1C2MainLoopHelpers(unittest.TestCase):
    """Regression tests for C1/C2 fail-closed + command guard helpers."""

    @classmethod
    def setUpClass(cls):
        cls.helper_ns = _load_main_helper_namespace()

    def test_noncombat_guard_init_outside_combat(self):
        guard_fn = self.helper_ns["get_noncombat_guard_message"]
        msg = guard_fn("/init 13", "")
        self.assertIsInstance(msg, str)
        self.assertIn("No active combat encounter", msg)
        self.assertIn("/init", msg)

    def test_noncombat_guard_end_outside_combat(self):
        guard_fn = self.helper_ns["get_noncombat_guard_message"]
        msg = guard_fn("/end", "")
        self.assertIsInstance(msg, str)
        self.assertIn("No active combat encounter", msg)
        self.assertIn("/end command", msg)

    def test_noncombat_guard_ignores_when_active_combat_exists(self):
        guard_fn = self.helper_ns["get_noncombat_guard_message"]
        msg = guard_fn("/end", "encounter_123")
        self.assertIsNone(msg)

    def test_noncombat_guard_handles_tagged_input(self):
        guard_fn = self.helper_ns["get_noncombat_guard_message"]
        msg = guard_fn("[Acheron]: /att goblin 15", "")
        self.assertIsInstance(msg, str)
        self.assertIn("No active combat encounter", msg)
        self.assertIn("/att", msg)

    def test_fail_closed_retry_exhaustion_message_is_deterministic(self):
        msg_fn = self.helper_ns["get_validation_retry_exhaustion_message"]
        msg = msg_fn()
        self.assertEqual(
            msg,
            "[SYSTEM] I could not process that turn right now. "
            "Please try the action again in a simpler sentence, or try a different action.",
        )

    def test_fail_closed_path_present_and_fail_open_text_removed(self):
        main_path = os.path.join(PROJECT_ROOT, "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            source = f.read()

        self.assertIn("if not valid_response_received:", source)
        self.assertIn("continue", source)
        self.assertNotIn("Proceeding with the last generated response.", source)


class TestDmGroupOpeningPhaseTransitionContract(unittest.TestCase):
    """Regression tests for dmGroup opening enemy batch -> PC phase transition and non-loop behavior."""

    def _load_combat_manager_source(self):
        """Load raw source of combat_manager.py for contract tests."""
        return _load_combat_runtime_sources()

    def test_init_dmgroup_sets_opening_marker(self):
        """/init path must set openingEnemyBatchPending when dmGroup wins initiative."""
        source = self._load_combat_manager_source()
        # Find the /init resolution block where dmGroup wins
        # The marker should be set via apply_opening_batch_marker when winner is dmGroup
        self.assertIn('apply_opening_batch_marker(encounter_data, winner)', source)
        # Verify the PHASE_MARKER debug log for dmGroup via /init path
        self.assertIn(
            'PHASE_MARKER: Set openingEnemyBatchPending=True via /init dmGroup path',
            source
        )

    def test_roundstart_dmgroup_sets_opening_marker(self):
        """Opening DM batches retain the round and stage a PC-phase handoff."""
        source = Path(os.path.join(PROJECT_ROOT, "core/combat/turn.py")).read_text(encoding="utf-8")
        stage = _function_node(source, "stage_combat_turn_snapshot")
        stage_text = "\n".join(source.splitlines()[stage.lineno - 1:stage.end_lineno])
        self.assertIn('encounter_data.get("roundStartsWith", "pcGroup")', stage_text)
        self.assertIn('round_starts_with != "dmGroup"', stage_text)
        self.assertIn('final_round = current_round', stage_text)
        self.assertIn('final_phase = "PC_PHASE"', stage_text)
        self.assertIn('final_opening_pending = False', stage_text)

    def test_opening_batch_clears_marker_and_returns_pc_phase(self):
        """Opening batch completion must clear marker and transition to PC_PHASE."""
        source = Path(os.path.join(PROJECT_ROOT, "core/combat/turn.py")).read_text(encoding="utf-8")
        stage = _function_node(source, "complete_opening_enemy_batch")
        stage_text = "\n".join(source.splitlines()[stage.lineno - 1:stage.end_lineno])
        self.assertIn('encounter_data.get("openingEnemyBatchPending", False)', stage_text)
        self.assertIn('encounter_data["openingEnemyBatchPending"] = False', stage_text)
        self.assertIn('multi_pc_manager.pc_phase_complete = False', stage_text)
        self.assertIn('PHASE_MARKER: Cleared openingEnemyBatchPending after opening enemy batch resolution', stage_text)
        self.assertIn('STATE_CHANGE: Opening batch complete -> PC_PHASE', stage_text)
        self.assertEqual(len(_call_nodes(stage, "save_json")), 1)

    def test_opening_batch_completion_block_is_non_looping_contract(self):
        """Opening batch completion block must not re-enable marker in the same path (non-loop)."""
        source = Path(os.path.join(PROJECT_ROOT, "core/combat/turn.py")).read_text(encoding="utf-8")
        stage = _function_node(source, "complete_opening_enemy_batch")
        assignments = [node for node in ast.walk(stage) if isinstance(node, ast.Assign)]
        marker_assignments = [
            node for node in assignments
            if isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].slice, ast.Constant)
            and node.targets[0].slice.value == "openingEnemyBatchPending"
        ]
        self.assertEqual(len(marker_assignments), 1, "Marker must be cleared exactly once in completion helper")
        self.assertIsInstance(marker_assignments[0].value, ast.Constant)
        self.assertIs(marker_assignments[0].value.value, False)
        self.assertFalse(_call_nodes(stage, "apply_opening_batch_marker"), "Completion cannot re-enable opening marker")
        self.assertEqual(len(_call_nodes(stage, "save_json")), 1, "Encounter must persist after completion")

    def test_pcgroup_clears_marker_does_not_set(self):
        """pcGroup winner must clear opening marker without setting it."""
        source = self._load_combat_manager_source()
        # Verify the PHASE_MARKER debug log for pcGroup clearing marker
        self.assertIn(
            'PHASE_MARKER: Cleared openingEnemyBatchPending via /init pcGroup path',
            source
        )
        self.assertIn(
            'PHASE_MARKER: Cleared openingEnemyBatchPending via round-start pcGroup path',
            source
        )

        from core.combat.multi_pc.sync import apply_opening_batch_marker
        from core.combat.turn import handle_group_initiative_gate

        encounter = {
            "initiativeRolls": {"dmGroup": 10},
            "openingEnemyBatchPending": True,
        }
        result = handle_group_initiative_gate(
            "/init 11",
            encounter,
            None,
            {},
            apply_opening_batch_marker=apply_opening_batch_marker,
            sync_available=True,
        )
        self.assertEqual(result["winner"], "pcGroup")
        self.assertFalse(result["marker_enabled"])
        self.assertFalse(result["needs_enemy_injection"])
        self.assertFalse(encounter["openingEnemyBatchPending"])


class TestCombatManagerEncounterSyncContracts(unittest.TestCase):
    """Regression tests for encounter ops forwarding and fast-lane persistence."""

    def _load_combat_manager_source(self):
        return _load_combat_runtime_sources()

    def test_update_encounter_branch_reads_ops_parameter(self):
        source = Path(os.path.join(PROJECT_ROOT, "core/combat/persistence.py")).read_text(encoding="utf-8")
        stage = _function_node(source, "process_combat_action_batch")
        update_branch = _action_type_branch(stage, "updateencounter")
        self.assertTrue(any(
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "ops"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "get"
            and len(node.value.args) >= 1
            and isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == "ops"
            for node in ast.walk(update_branch)
        ))

    def test_update_encounter_branch_forwards_ops(self):
        owner_source = Path(os.path.join(PROJECT_ROOT, "core/combat/combat_manager.py")).read_text(encoding="utf-8")
        owner = _function_node(owner_source, "_run_combat_simulation_internal")
        dependencies = [
            call for call in ast.walk(owner)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "CombatActionDependencies"
        ]
        update_binding = next(keyword.value for call in dependencies for keyword in call.keywords if keyword.arg == "update_encounter")
        self.assertIsInstance(update_binding, ast.Name)
        self.assertEqual(update_binding.id, "_stage_encounter_action")
        update_adapter = _function_node(owner_source, "_stage_encounter_action")
        delegated_update = _call_nodes(update_adapter, "stage_encounter_update")
        self.assertEqual(len(delegated_update), 1)
        self.assertTrue(
            any(
                keyword.arg == "ops"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "ops"
                for keyword in delegated_update[0].keywords
            ),
            "The extracted adapter must preserve the action's ops payload",
        )

        from core.combat.persistence import CombatActionDependencies, process_combat_action_batch

        ops = [{"op": "hp_delta", "target": "Goblin", "delta": -2}]
        forwarded = []
        encounter = {
            "creatures": [
                {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": 6}
            ]
        }

        def update_encounter(encounter_id, changes, ops=None):
            forwarded.append((encounter_id, changes, ops))
            return encounter

        dependencies = CombatActionDependencies(
            queue_character_update=lambda *_args, **_kwargs: None,
            update_encounter=update_encounter,
            normalize_encounter_status=lambda value: value,
            sync_non_pc_queue_state=lambda *_args: False,
            log_info=lambda *_args, **_kwargs: None,
            log_debug=lambda *_args, **_kwargs: None,
            log_error=lambda *_args, **_kwargs: None,
            log_warning=lambda *_args, **_kwargs: None,
            calculate_xp=lambda: ("", 0),
            save_json=lambda *_args, **_kwargs: None,
            active_character_update_available=False,
            emit_combat_event=lambda *_args, **_kwargs: None,
            get_current_actor=lambda _manager: None,
            advance_turn=lambda _manager: None,
            get_pc_state=lambda _manager, _name: None,
            pc_acted_status=object(),
            npc_combatant_type=object(),
            pc_combatant_type=object(),
            check_all_monsters_defeated=lambda _encounter: False,
        )
        with patch("core.combat.persistence.trace_enabled", return_value=False):
            process_combat_action_batch(
                [{
                    "action": "updateEncounter",
                    "parameters": {
                        "encounterId": "fixture-encounter",
                        "changes": "Goblin takes damage",
                        "ops": ops,
                    },
                }],
                encounter,
                {},
                encounter_id="fixture-encounter",
                conversation_history=[],
                conversation_history_file="fixture-history.json",
                multi_pc_manager=None,
                party_tracker_data={},
                is_combat_ending=False,
                dependencies=dependencies,
            )
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0][:2], ("fixture-encounter", "Goblin takes damage"))
        self.assertIs(forwarded[0][2], ops)
        self.assertTrue(any(
            keyword.arg == "ops" and isinstance(keyword.value, ast.Name) and keyword.value.id == "ops"
            for keyword in delegated_update[0].keywords
        ))

        stage_source = Path(os.path.join(PROJECT_ROOT, "core/combat/persistence.py")).read_text(encoding="utf-8")
        stage = _function_node(stage_source, "process_combat_action_batch")
        update_branch = _action_type_branch(stage, "updateencounter")
        staged_calls = _call_nodes(update_branch, "update_encounter")
        self.assertEqual(len(staged_calls), 1)
        self.assertTrue(any(
            keyword.arg == "ops" and isinstance(keyword.value, ast.Name) and keyword.value.id == "ops"
            for keyword in staged_calls[0].keywords
        ))

    def test_fast_lane_log_path_persists_encounter_state(self):
        source = self._load_combat_manager_source()
        self.assertIn('STATE_PERSIST: Fast-lane encounter state persisted', source)
        self.assertIn('io.persist_encounter(encounter_id, encounter_data)', source)

    def test_fast_path_spoken_narration_contract(self):
        source = self._load_combat_manager_source()
        self.assertIn('mechanical_feedback, spoken_narration, log_msg, skip_llm = multi_pc_manager.handle_combat_command', source)
        self.assertIn('if spoken_narration:', source)
        self.assertIn('io.emit(spoken_narration)', source)

    def test_update_encounter_branch_resyncs_non_pc_queue_state(self):
        stage_source = Path(os.path.join(PROJECT_ROOT, "core/combat/persistence.py")).read_text(encoding="utf-8")
        stage = _function_node(stage_source, "process_combat_action_batch")
        update_branch = _action_type_branch(stage, "updateencounter")
        sync_calls = _call_nodes(update_branch, "sync_non_pc_queue_state")
        self.assertEqual(len(sync_calls), 1)
        self.assertIn('STATE_SYNC: Refreshed non-PC turn queue state from authoritative encounter data', stage_source)
        sync_guard = next(
            node for node in ast.walk(update_branch)
            if isinstance(node, ast.If) and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "sync_non_pc_queue_state"
                for call in ast.walk(node.test)
            )
        )
        self.assertTrue(any(
            isinstance(node, ast.Name) and node.id == "multi_pc_manager"
            for node in ast.walk(sync_guard.test)
        ))
        updated_guard = next(
            node for node in ast.walk(update_branch)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "updated_encounter_data"
        )
        self.assertIn(sync_guard, list(ast.walk(updated_guard)))

        owner_source = Path(os.path.join(PROJECT_ROOT, "core/combat/combat_manager.py")).read_text(encoding="utf-8")
        owner = _function_node(owner_source, "_run_combat_simulation_internal")
        sync_bindings = [
            keyword.value for call in ast.walk(owner)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "CombatActionDependencies"
            for keyword in call.keywords if keyword.arg == "sync_non_pc_queue_state"
        ]
        self.assertEqual(len(sync_bindings), 1)
        self.assertIsInstance(sync_bindings[0], ast.Lambda)
        self.assertEqual(len(_call_nodes(sync_bindings[0], "sync_non_pc_queue_state")), 1)

        queue_source = Path(os.path.join(PROJECT_ROOT, "core/combat/multi_pc/turn_queue.py")).read_text(encoding="utf-8")
        queue_tree = ast.parse(queue_source)
        self.assertTrue(any(
            isinstance(node, ast.FunctionDef) and node.name == "_is_valid_enemy_phase_actor"
            for node in ast.walk(queue_tree)
        ), "Authoritative living/non-PC queue filter remains owned by turn queue")


class TestCombatFastPathConfigContract(unittest.TestCase):
    """Regression tests for deterministic fast-path config and runtime wiring."""

    def _load_model_config_source(self):
        cfg_path = os.path.join(PROJECT_ROOT, "model_config.py")
        with open(cfg_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_fast_path_flag_present_and_documented(self):
        source = self._load_model_config_source()
        self.assertIn('COMBAT_FAST_DETERMINISTIC_NARRATION = True', source)
        self.assertIn('Fast-path local narration for deterministic PC_PHASE commands', source)


class TestCombatNaturalLanguageParserContract(unittest.TestCase):
    """Regression tests for NL parser config flag and hook presence."""

    def _load_model_config_source(self):
        cfg_path = os.path.join(PROJECT_ROOT, "model_config.py")
        with open(cfg_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_combat_manager_source(self):
        return _load_combat_runtime_sources()

    def test_nl_parser_flag_present_and_documented(self):
        source = self._load_model_config_source()
        self.assertIn("COMBAT_PC_PHASE_NL_FAST_PATH = True", source)
        self.assertIn("Canary enabled; rollback by setting False", source)

    def test_nl_parser_import_hook_present(self):
        source = self._load_combat_manager_source()
        self.assertIn("from core.combat.decisions import", source)
        self.assertIn("from utils.combat_pc_action_parser import", source)
        self.assertIn("parse_pc_phase_action", source)
        self.assertIn("enabled=COMBAT_PC_PHASE_NL_FAST_PATH", source)
        self.assertIn('multi_pc_manager.combat_phase == "PC_PHASE"', source)
        self.assertIn("pc_action_decision_eligible(", source)
        self.assertIn("PCActionDecisionStatus.DECLINED", source)
        self.assertIn("PCActionDecisionStatus.UNAVAILABLE", source)

    def test_nl_parser_apply_order_source_contract(self):
        source = self._load_combat_manager_source()
        turn_source = Path(PROJECT_ROOT, "core/combat/turn.py").read_text(encoding="utf-8")
        owner_source = Path(PROJECT_ROOT, "core/combat/combat_manager.py").read_text(encoding="utf-8")
        decision_source = Path(PROJECT_ROOT, "core/combat/decisions.py").read_text(encoding="utf-8")
        seam_call = turn_source.find("pc_action_decision = run_pc_action_decision(")
        context_stage = turn_source.find("context_result = dependencies.assemble_context(")
        owner_stage = owner_source.find("normal_turn = prepare_combat_normal_turn(")
        provider_stage = owner_source.find("run_combat_provider_retry_stage(")
        parse_call = decision_source.find("parse_result = parse_action(")
        apply_call = decision_source.find("if not apply_result(")
        handled_return = decision_source.find(
            "PCActionDecisionStatus.HANDLED, actor_name, parse_result"
        )
        handled_gate = turn_source.find(
            "if pc_action_decision.status is PCActionDecisionStatus.HANDLED:"
        )
        feedback = turn_source.find("if mechanical_feedback:", handled_gate)
        history_log = turn_source.find("if log_message:", feedback)
        handled_continue = turn_source.find('CombatNormalTurnResult("continue"', history_log)
        self.assertGreater(seam_call, 0, "decision seam call must remain in the normal-turn owner")
        self.assertGreater(context_stage, 0, "context stage anchor must remain in the normal-turn owner")
        self.assertGreater(owner_stage, 0, "legacy loop must enter the typed normal-turn owner")
        self.assertGreater(provider_stage, 0, "normal-turn stage must still precede provider retry")
        self.assertGreater(parse_call, 0, "parser invocation must remain in decision owner")
        self.assertGreater(apply_call, 0, "apply invocation must remain in decision owner")
        self.assertGreater(handled_return, 0, "handled result must be emitted only after apply")
        self.assertGreater(handled_gate, 0, "owner must branch on the typed handled result")
        self.assertGreater(feedback, 0, "mechanical feedback emission must remain under handled")
        self.assertGreater(history_log, 0, "history insertion must remain under handled")
        self.assertGreater(handled_continue, 0, "handled parser path must retain its continue")
        self.assertLess(seam_call, context_stage)
        self.assertLess(owner_stage, provider_stage)
        self.assertLess(parse_call, apply_call)
        self.assertLess(apply_call, handled_return)
        self.assertLess(seam_call, handled_gate)
        self.assertLess(handled_gate, feedback)
        self.assertLess(feedback, history_log)
        self.assertLess(history_log, handled_continue)
        self.assertIn('outcome="hit",', decision_source)
        self.assertIn('outcome="miss",', decision_source)
        self.assertIn('outcome="false_positive",', decision_source)
        self.assertIn('outcome="unavailable",', decision_source)


class TestCombatSingleActiveSessionContracts(unittest.TestCase):
    """Regression tests for single-active-session combat ownership guardrails."""

    def _load_action_handler_source(self):
        ah_path = os.path.join(PROJECT_ROOT, "core/ai/action_handler.py")
        with open(ah_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_combat_manager_source(self):
        return _load_combat_runtime_sources()

    def test_action_handler_declares_tabletop_ownership_helpers(self):
        source = self._load_action_handler_source()
        self.assertIn("def _is_tabletop_multi_pc_guard_active(", source)
        self.assertIn("def _get_active_combat_owner(", source)

    def test_action_handler_blocks_duplicate_createencounter(self):
        source = self._load_action_handler_source()
        self.assertIn("Duplicate createEncounter blocked", source)
        self.assertIn(
            "Combat is already active. Continue the current encounter before starting a new one.",
            source,
        )
        self.assertIn("if _is_tabletop_multi_pc_guard_active(party_tracker_data):", source)

    def test_combat_manager_wraps_simulation_with_session_claim(self):
        source = self._load_combat_manager_source()
        self.assertIn("def run_combat_simulation(encounter_id, party_tracker_data, location_info):", source)
        self.assertIn("_enter_combat_session(effective_encounter_id)", source)
        self.assertIn("_run_combat_simulation_internal(", source)
        self.assertIn("session=session,", source)
        self.assertIn("_exit_combat_session(effective_encounter_id)", source)

    def test_combat_manager_prefers_durable_owner_on_mismatch(self):
        source = self._load_combat_manager_source()
        self.assertIn("COMBAT_SESSION_MISMATCH:", source)
        self.assertIn("effective_encounter_id = durable_owner", source)


class TestEncounterRosterBackfillContract(unittest.TestCase):
    """Regression tests for encounter roster backfill and duplicate-prevention."""

    def _load_combat_manager_source(self):
        """Load raw source of combat_manager.py for contract tests."""
        return _load_combat_runtime_sources()

    def _load_combat_state_sync_source(self):
        """Load raw source of combat_state_sync.py for backfill contract tests."""
        css_path = os.path.join(PROJECT_ROOT, "core/combat/multi_pc/sync.py")
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_combat_builder_source(self):
        """Load raw source of combat_builder.py for encounter generation contract tests."""
        cb_path = os.path.join(PROJECT_ROOT, "core/generators/combat_builder.py")
        with open(cb_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_backfill_contract_present_for_missing_party_members(self):
        """Backfill must add missing party members to encounter roster."""
        # Check combat_state_sync.py for normalize_multi_pc_roster function
        css_source = self._load_combat_state_sync_source()
        self.assertIn(
            "def normalize_multi_pc_roster(",
            css_source,
            "normalize_multi_pc_roster function must exist for roster backfill"
        )
        # Check for party member iteration logic
        self.assertIn(
            'party_members = party_tracker_data.get("partyMembers", [])',
            css_source,
            "Must read partyMembers from party_tracker_data"
        )
        # Check for missing player detection
        self.assertIn(
            "if not normalized_member or normalized_member in existing_players:",
            css_source,
            "Must check for existing players to identify missing ones"
        )
        # Check for player addition to creatures
        self.assertIn(
            'creatures.append(',
            css_source,
            "Must append missing players to creatures list"
        )
        # Check backfill logging
        self.assertIn(
            "ROSTER_BACKFILL: Added missing player",
            css_source,
            "Must log when backfilling missing players"
        )

    def test_backfill_contract_preserves_existing_enemy_npc_state(self):
        """Backfill must preserve existing enemy/NPC HP/status/initiative (additive only)."""
        css_source = self._load_combat_state_sync_source()
        # Verify additive-only approach - creatures list is extended, not replaced
        self.assertIn(
            "creatures = encounter_data.get(\"creatures\", [])",
            css_source,
            "Must read existing creatures list (not replace)"
        )
        # Verify only appending new players, not modifying existing entries
        append_pos = css_source.find("creatures.append(")
        self.assertGreater(append_pos, 0, "Must append to creatures list")
        # Verify no modification of existing creature properties
        self.assertNotIn(
            "creature[\"status\"] =",
            css_source,
            "Must NOT modify existing creature status (preserve enemy/NPC state)"
        )
        self.assertNotIn(
            "creature[\"initiative\"] =",
            css_source,
            "Must NOT modify existing creature initiative (preserve enemy/NPC state)"
        )

    def test_duplicate_prevention_when_player_already_exists(self):
        """Duplicate prevention: existing player must not be added again."""
        css_source = self._load_combat_state_sync_source()
        # Check for existing player tracking set
        self.assertIn(
            "existing_players = {",
            css_source,
            "Must track existing players in a set for deduplication"
        )
        # Check for case-insensitive name normalization
        self.assertIn(
            "def _normalize_name(name: Any) -> str:",
            css_source,
            "Must normalize names for case-insensitive matching"
        )
        self.assertIn(
            '.strip().lower()',
            css_source,
            "Must use lowercase comparison for name deduplication"
        )
        # Check for skip logic when player already exists
        self.assertIn(
            "if not normalized_member or normalized_member in existing_players:",
            css_source,
            "Must skip players already in existing_players set (duplicate prevention)"
        )
        # Also verify combat_builder.py duplicate prevention during generation
        cb_source = self._load_combat_builder_source()
        self.assertIn(
            "if not normalized_member or normalized_member in seen_players:",
            cb_source,
            "combat_builder must also prevent duplicate players during generation"
        )

    def test_fail_open_contract_for_missing_character_sources(self):
        """Missing character file must not crash combat (fail-open behavior)."""
        css_source = self._load_combat_state_sync_source()
        # Check for safe character loading with fallback
        self.assertIn(
            "char_data = safe_json_load(char_file)",
            css_source,
            "Must use safe_json_load for character file loading"
        )
        # Check for continue on missing character (not crash)
        self.assertIn(
            "if not char_data:",
            css_source,
            "Must check if character data loaded successfully"
        )
        self.assertIn(
            "continue",
            css_source,
            "Must continue to next party member if character file missing (fail-open)"
        )
        # Check for warning log instead of error/crash
        self.assertIn(
            "warning(",
            css_source,
            "Must use warning (not error) for missing character data"
        )
        self.assertIn(
            "ROSTER_BACKFILL: Missing character data for",
            css_source,
            "Must log warning when character data missing"
        )
        # Check outer exception handling (fail-open at function level)
        self.assertIn(
            "except Exception as e:",
            css_source,
            "Must have outer exception handler for fail-open behavior"
        )
        self.assertIn(
            "ROSTER_BACKFILL: Fail-open due to normalization error",
            css_source,
            "Must log and return safely on any normalization error"
        )


class TestInitiativePayloadInclusionContract(unittest.TestCase):
    """Regression tests for initiative payload inclusion of unconscious/incapacitated players."""

    def _load_tabletop_socket_handlers_source(self):
        """Load raw source of tabletop_socket_handlers.py for contract tests."""
        tsh_path = os.path.join(PROJECT_ROOT, "web/extensions/tabletop_socket_handlers.py")
        with open(tsh_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_unconscious_incapacitated_players_included_in_payload(self):
        """Unconscious and incapacitated players must be included in initiative payload."""
        source = self._load_tabletop_socket_handlers_source()
        # Verify Section 3.1 TABLETOP MODE comment exists
        self.assertIn(
            "TABLETOP MODE: Section 3.1 - Keep player combatants visible during active combat",
            source,
            "Must have TABLETOP MODE Section 3.1 comment for player visibility"
        )
        # Verify player inclusion logic includes non-dead players
        self.assertIn(
            'if creature_type == "player":',
            source,
            "Must check creature type for player combatants"
        )
        self.assertIn(
            'if status != "dead":',
            source,
            "Must include players with status != dead (covers unconscious/incapacitated)"
        )
        self.assertIn(
            "visible_combatants.append(creature)",
            source,
            "Must append non-dead players to visible combatants"
        )

    def test_dead_players_excluded_from_payload(self):
        """Dead players must be excluded from initiative payload."""
        source = self._load_tabletop_socket_handlers_source()
        # Verify dead player exclusion logic
        self.assertIn(
            'if status != "dead":',
            source,
            "Must exclude dead players via status != dead check"
        )
        # Ensure there's no logic that would include dead players
        player_block_start = source.find('if creature_type == "player":')
        player_block_end = source.find("else:", player_block_start)
        player_block = source[player_block_start:player_block_end]
        # Verify dead check is present in player block
        self.assertIn(
            'if status != "dead":',
            player_block,
            "Dead player exclusion must be in player type block"
        )

    def test_status_field_preserved_for_ui_display(self):
        """Status field must be preserved in payload for UI consumption."""
        source = self._load_tabletop_socket_handlers_source()
        # Verify status is read from creature data
        self.assertIn(
            'status = str(creature.get("status", "unknown")).lower()',
            source,
            "Must read status field from creature data"
        )
        # Verify status is included in combatant_data
        self.assertIn(
            '"status": combatant.get("status")',
            source,
            "Must include status in combatant_data payload"
        )

    def test_all_unconscious_edge_case_payload_still_active(self):
        """All players unconscious/incapacitated must still show active combat payload."""
        source = self._load_tabletop_socket_handlers_source()
        # Verify active flag is set when visible_combatants exist
        self.assertIn(
            "if not visible_combatants:",
            source,
            "Must check if visible combatants exist before setting inactive"
        )
        self.assertIn(
            "'active': True",
            source,
            "Must set active: True when combatants are present"
        )
        # Verify the flow: non-dead players -> visible_combatants -> active: True
        # This ensures even all-unconscious party keeps combat active
        visible_check_pos = source.find("if not visible_combatants:")
        active_true_pos = source.find("'active': True")
        self.assertGreater(
            active_true_pos,
            visible_check_pos,
            "active: True must come after visible_combatants check"
        )

    def test_non_player_payload_filters_zero_hp_alive_ghosts(self):
        """Non-player initiative entries must exclude zero-HP ghosts even if status drift says alive."""
        source = self._load_tabletop_socket_handlers_source()
        self.assertIn(
            'current_hp = int(creature.get("currentHitPoints", 0))',
            source,
            "Must read currentHitPoints for non-player initiative filtering"
        )
        self.assertIn(
            'if status == "alive" and current_hp > 0:',
            source,
            "Non-player initiative visibility must require alive status and positive HP"
        )


class TestCompatibilityAndSinglePlayerContract(unittest.TestCase):
    """Regression tests for pcGroup starts and single-player behavior compatibility."""

    def _load_combat_manager_source(self):
        """Load raw source of combat_manager.py for contract tests."""
        return _load_combat_runtime_sources()

    def _load_combat_state_sync_source(self):
        """Load raw source of combat_state_sync.py for contract tests."""
        css_path = os.path.join(PROJECT_ROOT, "core/combat/multi_pc/sync.py")
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_combat_builder_source(self):
        """Load raw source of combat_builder.py for contract tests."""
        cb_path = os.path.join(PROJECT_ROOT, "core/generators/combat_builder.py")
        with open(cb_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_pcgroup_winner_no_opening_batch_marker(self):
        """pcGroup winner must NOT set openingEnemyBatchPending marker."""
        cm_source = self._load_combat_manager_source()
        css_source = self._load_combat_state_sync_source()

        # Verify apply_opening_batch_marker exists
        self.assertIn(
            "def apply_opening_batch_marker(",
            css_source,
            "apply_opening_batch_marker function must exist"
        )

        # Verify pcGroup path clears marker via apply_opening_batch_marker
        self.assertIn(
            'apply_opening_batch_marker(encounter_data, winner)',
            cm_source,
            "Must call apply_opening_batch_marker with winner parameter"
        )

        # Verify pcGroup clears marker (sets to False)
        self.assertIn(
            'marker_enabled = str(starts_with or "").strip() == "dmGroup"',
            css_source,
            "Marker must only be enabled for dmGroup, not pcGroup"
        )

        # Verify PHASE_MARKER logs for pcGroup clearing
        self.assertIn(
            'PHASE_MARKER: Cleared openingEnemyBatchPending via /init pcGroup path',
            cm_source,
            "Must log pcGroup marker clearing via /init path"
        )

    def test_single_player_no_roster_expansion(self):
        """Single-player mode must NOT trigger multi-PC roster expansion."""
        css_source = self._load_combat_state_sync_source()
        cb_source = self._load_combat_builder_source()

        # Verify backfill only triggers with > 1 party members
        self.assertIn(
            "if len(party_members) <= 1:",
            css_source,
            "Must skip backfill for single party member"
        )

        # Verify combat_builder single-party-member guard
        self.assertIn(
            "if len(party_members) > 1:",
            cb_source,
            "combat_builder must check party size > 1 before roster expansion"
        )

        # Verify single player keeps existing behavior
        self.assertIn(
            'player_names = [encounter_data["player"]]',
            cb_source,
            "Single-player must use only triggering player, not expand roster"
        )

    def test_legacy_encounter_fail_open_contract(self):
        """Legacy encounters without new fields must work (fail-open compatibility)."""
        cm_source = self._load_combat_manager_source()
        css_source = self._load_combat_state_sync_source()

        # Verify safe defaults for missing initiativeMode
        self.assertIn(
            'encounter_data.get("initiativeMode", "two_group_phase1")',
            cm_source,
            "Must use default initiativeMode when field missing (legacy compatibility)"
        )

        # Verify safe defaults for missing initiativeWinner
        self.assertIn(
            'encounter_data.get("initiativeWinner", "pending")',
            cm_source,
            "Must use default initiativeWinner when field missing"
        )

        # Verify safe defaults for missing roundStartsWith
        self.assertIn(
            'encounter_data.get("roundStartsWith", "pcGroup")',
            cm_source,
            "Must use default roundStartsWith when field missing"
        )

        # Verify safe_json_load usage in backfill
        self.assertIn(
            "char_data = safe_json_load(char_file)",
            css_source,
            "Must use safe_json_load for fail-open character loading"
        )

    def test_roundstart_pcgroup_no_forced_enemy_phase(self):
        """Round start with pcGroup must NOT force enemy phase."""
        from core.combat.turn import RoundTransitionDependencies, stage_combat_turn_snapshot

        encounter = {
            "combat_round": 4,
            "roundStartsWith": "pcGroup",
            "openingEnemyBatchPending": False,
            "combat_phase": "ENEMY_PHASE",
        }
        logs = []
        dependencies = RoundTransitionDependencies(
            apply_opening_batch_marker=lambda _data, _side: self.fail(
                "Staged round transitions must not mutate through the runtime marker helper"
            ),
            sync_available=True,
            save_json=lambda *_args: self.fail("Staging must not persist encounter state"),
            compress_old_rounds=lambda history, *_args, **_kwargs: history,
            log_debug=lambda message, **kwargs: logs.append((message, kwargs)),
            log_info=lambda *_args, **_kwargs: None,
            log_warning=lambda *_args, **_kwargs: None,
            bind_history=lambda _history: None,
        )
        result = stage_combat_turn_snapshot(
            encounter,
            [{"role": "user", "content": "Enemies turn."}],
            phase_before="ENEMY_PHASE",
            phase_after="ENEMY_PHASE",
            enemy_batch_completed=True,
            opening_batch_pending_before=False,
            authoritative_round_before=4,
            round_starts_with_before="pcGroup",
            dependencies=dependencies,
        )

        self.assertEqual(result.encounter_data["combat_round"], 5)
        self.assertEqual(result.encounter_data["combat_phase"], "PC_PHASE")
        self.assertFalse(result.encounter_data["openingEnemyBatchPending"])
        self.assertEqual(encounter["combat_round"], 4, "Staging must not mutate the durable source snapshot")
        self.assertEqual(
            [
                message for message, _kwargs in logs
                if message.startswith(("PHASE_MARKER:", "STATE_CHANGE:"))
            ],
            [
                "PHASE_MARKER: Cleared openingEnemyBatchPending via round-start pcGroup path",
                "STATE_CHANGE: Applied roundStartsWith=pcGroup -> PC_PHASE start",
            ],
        )


class TestFastLaneInitiationContract(unittest.TestCase):
    """Regression tests for Phase 1 fast-lane combat initiation (no-duplicate-opening)."""

    def _load_combat_manager_source(self):
        """Load raw source of combat_manager.py for contract tests."""
        return _load_combat_runtime_sources()

    def _load_bootstrap_source(self):
        with open(os.path.join(PROJECT_ROOT, "core/combat/bootstrap.py"), "r", encoding="utf-8") as handle:
            return handle.read()

    def test_fast_lane_guard_contract_exists(self):
        """Fast-lane must guard on multi_pc_manager and awaitingPcGroupRoll."""
        source = self._load_bootstrap_source()
        # Must contain the guard condition
        self.assertIn("multi_pc_manager is not None", source)
        self.assertIn('encounter_data.get("awaitingPcGroupRoll", False) is True', source)
        # Must be assigned to is_fast_lane and used in if statement
        self.assertIn("is_fast_lane = (", source)
        self.assertIn("if is_fast_lane:", source)

    def test_immediate_initiative_prompt_exists(self):
        """Fast-lane must print immediate initiative prompt without LLM call."""
        source = self._load_bootstrap_source()
        self.assertIn("Combat initiated. Initiative pending. ", source)
        self.assertIn('"Enter /init <1-20> to begin combat."', source)
        # TABLETOP MODE: Ensure initiative helper auto-prefill marker is preserved
        self.assertIn("[prefill:/init ]", source)
        # Must flush stdout immediately after print
        self.assertIn("dependencies.flush()", source)
        self.assertIn("flush=sys.stdout.flush", self._load_combat_manager_source())

    def test_initial_scene_llm_in_non_fast_lane_path(self):
        """Initial scene AI call must be in non-fast-lane (else) branch."""
        source = self._load_bootstrap_source()
        startup = _function_node(source, "run_startup_narrative")
        fast_lane = next(
            node for node in ast.walk(startup)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "is_fast_lane"
        )
        initial_call = _call_nodes(startup, "_run_initial_scene_generation")[0]
        self.assertFalse(any(node is initial_call for node in ast.walk(fast_lane)))
        call_statement_index = next(
            index for index, statement in enumerate(startup.body)
            if any(node is initial_call for node in ast.walk(statement))
        )
        self.assertLess(startup.body.index(fast_lane), call_statement_index)
        self.assertTrue(any(isinstance(node, ast.Return) for node in fast_lane.body))
        self.assertIn('dependencies.debug("AI_CALL: Getting initial scene description..."', source)

    def test_existing_init_gate_preserved(self):
        """Existing /init validation gate must remain present."""
        source = self._load_combat_manager_source()
        # Must contain the awaitingPcGroupRoll gate in combat loop
        self.assertIn(
            'if multi_pc_manager and encounter_data.get("awaitingPcGroupRoll", False):',
            source
        )
        # Must contain usage prompts for invalid /init
        self.assertIn('Dungeon Master: [SYSTEM] Initiative pending. Usage: /init <1-20>', source)
        self.assertIn(
            'Dungeon Master: [SYSTEM] Initiative pending. Roll must be between 1 and 20.',
            source
        )
        # TABLETOP MODE: Prompt lines should carry /init input prefill marker
        self.assertIn('[prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Usage: /init <1-20>', source)
        self.assertIn('[prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Enter /init <1-20> to begin combat.', source)

    def test_initiative_lock_message_uses_readable_phase_text(self):
        """Initiative lock system message should use spaces instead of underscores."""
        source = self._load_combat_manager_source()
        self.assertIn("DM GROUP", source)
        self.assertIn("PC GROUP", source)
        self.assertIn("phase_label_display", source)
        self.assertIn("replace(\"_\", \" \")", source)

    def test_pc_group_winner_followup_prompt_exists(self):
        """PC-group initiative win should emit an immediate spoken turn prompt."""
        source = self._load_combat_manager_source()
        self.assertIn(
            "Dungeon Master: Your party has the initiative and strikes first, ",
            source
        )
        self.assertIn("what does {active_pc_name} do?", source)
        self.assertIn("active_pc_name = multi_pc_manager.current_pc_name", source)

    def test_fast_lane_skips_initial_scene_bootstrap_contract(self):
        """Fast-lane must skip initial scene bootstrap and defer narration until phase starts."""
        source = self._load_bootstrap_source()
        startup = _function_node(source, "run_startup_narrative")
        self.assertIn("if is_fast_lane:", source)
        self.assertIn('initial_prompt = f"""Dungeon Master Note:', source)
        self.assertTrue(_call_nodes(startup, "_run_initial_scene_generation"))
        fast_lane = next(
            node for node in ast.walk(startup)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "is_fast_lane"
        )
        self.assertTrue(any(isinstance(node, ast.Return) for node in fast_lane.body))

        # Fast-lane path should explicitly log deferred narration contract
        self.assertIn(
            "COMBAT_INIT: Fast-lane startup complete; deferring narration until phase starts",
            source
        )

    def test_initiative_order_usage_stays_in_non_fast_lane_contract(self):
        """initiative_order assignment and usage must stay in non-fast-lane paths."""
        source = self._load_bootstrap_source()
        startup = _function_node(source, "run_startup_narrative")
        prompt = _function_node(source, "_build_initial_scene_prompt")
        generation = _function_node(source, "_run_initial_scene_generation")
        fast_lane = next(
            node for node in ast.walk(startup)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "is_fast_lane"
        )
        self.assertTrue(any(isinstance(node, ast.Return) for node in fast_lane.body))
        self.assertTrue(_call_nodes(startup, "_run_initial_scene_generation"))
        self.assertIn("initiative_order = dependencies.get_initiative_order(inputs.encounter_data)", ast.get_source_segment(source, prompt))
        self.assertIn("Initiative Order: {initiative_order}", ast.get_source_segment(source, prompt))
        self.assertTrue(_call_nodes(generation, "_build_initial_scene_prompt"))


class TestCombatReplayAuthorityContracts(unittest.TestCase):
    """Regression tests for combat replay markers and phase-aware prompt authority."""

    def _read_source(self, relative_path):
        file_path = os.path.join(PROJECT_ROOT, relative_path)
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_phase_authority_cleanup_source_contract(self):
        source = self._read_source("core/combat/multi_pc/manager.py")
        self.assertIn('CURRENT_PHASE: {current_phase}', source)
        self.assertIn('if not self._turns.pc_phase_complete:', source)
        self.assertIn('elif not self._turns.pc_phase_complete and name == self._state.current_pc_name:', source)
        self.assertNotIn('PROCESS ALL OF THESE IN ONE RESPONSE', source)

    def test_deterministic_command_markers_source_contract(self):
        source = self._read_source("core/combat/multi_pc/manager.py")
        self.assertIn('[ALREADY_APPLIED][prefill:/dmg ] Dungeon Master: Hit!', source)
        self.assertIn('[ALREADY_APPLIED] Dungeon Master: Damage applied (', source)
        self.assertIn('Result HP:', source)
        self.assertIn('[ALREADY_APPLIED] [System:', source)

    def test_pc_phase_ledger_source_contract(self):
        source = self._read_source("core/combat/multi_pc/manager.py")
        combat_manager_source = self._read_source("core/combat/combat_manager.py")
        self.assertIn("pc_phase_event_ledger", source)
        self.assertIn("record_pc_phase_event", source)
        self.assertIn("clear_pc_phase_event_ledger", source)
        self.assertIn("HISTORICAL ONLY; DO NOT REPLAY MECHANICS", source)
        self.assertNotIn("PC PHASE RECAP FACTS (HISTORICAL ONLY; DO NOT REPLAY MECHANICS)", combat_manager_source)

    def test_combat_validation_prompt_source_contracts(self):
        sim_source = self._read_source("prompts/combat/combat_sim_prompt_multipc.txt")
        validation_source = self._read_source("prompts/combat/combat_validation_prompt_multipc.txt")
        sim_compressed = self._read_source("prompts/combat/combat_sim_prompt_multipc_compressed.txt")
        validation_compressed = self._read_source("prompts/combat/combat_validation_prompt_multipc_compressed.txt")

        self.assertIn('CURRENT_PHASE always wins over the `[>]` marker.', sim_source)
        self.assertIn('If a combat history line contains `[ALREADY_APPLIED]`', sim_source)
        self.assertIn('During ENEMY_PHASE, prompting any PC what they do is INVALID', validation_source)
        self.assertIn('If a combat history line is marked [ALREADY_APPLIED]', validation_source)
        self.assertIn('Python owns the death-save roll and result', sim_compressed)
        self.assertIn('Only the pending PC\'s active tab/input may supply that PC\'s death-save roll.', sim_compressed)
        self.assertIn('Death-save rolls are Python-deterministic.', validation_compressed)
        self.assertIn('already applied or marked [ALREADY_APPLIED]', validation_compressed)

    def test_combat_prompt_closure_source_contracts(self):
        combat_manager_source = self._read_source("core/combat/combat_manager.py")
        decision_source = self._read_source("core/combat/decisions.py")
        sim_multipc_compressed = self._read_source("prompts/combat/combat_sim_prompt_multipc_compressed.txt")
        sim_compressed = self._read_source("prompts/combat/combat_sim_prompt_compressed.txt")
        validation_compressed = self._read_source("prompts/combat/combat_validation_prompt_compressed.txt")

        self.assertIn("COMBAT_PC_PHASE_NL_FAST_PATH", combat_manager_source)
        self.assertIn("enabled=COMBAT_PC_PHASE_NL_FAST_PATH", combat_manager_source)
        self.assertIn("and enabled", decision_source)
        self.assertIn('multi_pc_manager.combat_phase == "PC_PHASE"', decision_source)
        self.assertNotIn("continue processing remaining NPCs/monsters", sim_multipc_compressed)
        self.assertNotIn("continue processing ALL remaining NPCs/monsters in initiative", sim_compressed)
        self.assertNotIn("EXACTLY ONE updateEncounter per response consolidating ALL enemy changes", validation_compressed)
        self.assertNotIn("System requires exactly ONE", validation_compressed)
        self.assertIn("at most one updateEncounter when enemy state changes exist", validation_compressed)


class TestInterpreterSafeSubprocessContracts(unittest.TestCase):
    """Regression tests for Windows-safe subprocess interpreter usage."""

    def _read_source(self, relative_path):
        file_path = os.path.join(PROJECT_ROOT, relative_path)
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_combat_entry_uses_active_interpreter(self):
        source = self._read_source("core/ai/action_handler.py")
        self.assertIn("import sys", source)
        self.assertIn("[sys.executable, combat_builder_path]", source)
        self.assertNotIn('["python", combat_builder_path]', source)

    def test_process_action_does_not_shadow_sys_locally(self):
        source = self._read_source("core/ai/action_handler.py")
        process_start = source.find("def process_action(")
        self.assertGreater(process_start, 0, "process_action definition must exist")
        process_tail = source[process_start:]
        self.assertNotIn("\n            import sys\n", process_tail)
        self.assertNotIn("\n        import sys\n", process_tail)

    def test_combat_builder_nested_launches_use_active_interpreter(self):
        source = self._read_source("core/generators/combat_builder.py")
        self.assertIn("import sys", source)
        self.assertIn("[sys.executable, monster_builder_path, monster_type]", source)
        self.assertIn("[sys.executable, npc_builder_path, formatted_npc_name]", source)
        self.assertNotIn('["python", monster_builder_path, monster_type]', source)
        self.assertNotIn('["python", npc_builder_path, formatted_npc_name]', source)

    def test_adjacent_runtime_subprocesses_use_active_interpreter(self):
        location_source = self._read_source("core/managers/location_manager.py")
        cumulative_source = self._read_source("core/ai/cumulative_summary.py")
        memories_source = self._read_source("core/memories/initialize_memories.py")
        dm_wrapper_source = self._read_source("core/ai/dm_wrapper.py")
        enhanced_wrapper_source = self._read_source("core/ai/enhanced_dm_wrapper.py")

        self.assertIn("import sys", location_source)
        self.assertIn("[sys.executable, adv_summary_path", location_source)
        self.assertIn("import sys", cumulative_source)
        self.assertIn("[sys.executable, \"scripts/memory_management/compress_memories.py\"]", cumulative_source)
        self.assertIn("import sys", memories_source)
        self.assertIn("[sys.executable, \"scripts/memory_management/compress_memories.py\"]", memories_source)
        self.assertIn("[sys.executable, \"main.py\"]", dm_wrapper_source)
        self.assertIn("[sys.executable, \"main.py\"]", enhanced_wrapper_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
