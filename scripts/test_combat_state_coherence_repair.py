# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Focused regression coverage for tt-combat-state-coherence-repair.

Usage:
    python3 scripts/test_combat_state_coherence_repair.py
"""

import json
import ast
import builtins
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()
PRIVATE_READ_DENIALS = []
REPO_ROOT = Path(__file__).resolve().parents[1]


class _PrivateRootReadDenied(BaseException):
    pass


def _is_private_root_read(path):
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate.parent.resolve() == REPO_ROOT and candidate.name in {"config.py", "party_tracker.json"}
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def check(path, operation):
        if _is_private_root_read(path):
            PRIVATE_READ_DENIALS.append(operation)
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

    patchers = [patch("builtins.open", guarded_open), patch("io.open", guarded_io_open), patch("os.open", guarded_os_open)]
    for patcher in patchers:
        patcher.start()
    return patchers


PRIVATE_READ_PATCHES = _arm_private_root_read_guard()
_IMPORT_FIXTURE = None
_IMPORT_CWD = None
_ORIGINAL_CWD = None
_FACTORY_MOCK = None
_INERT_COMPLETIONS = None


def setUpModule():
    """Import real combat owners under fatal guards and the known inert client seam."""
    global _IMPORT_FIXTURE, _IMPORT_CWD, _ORIGINAL_CWD, _FACTORY_MOCK, _INERT_COMPLETIONS
    global combat_manager, CombatStateManager, Combatant, CombatantType, MultiPCCombatManager, PCStatus
    global _apply_character_ops_deterministic
    import importlib
    import shutil

    import model_config
    from utils import ai_client_factory
    fixture = types.ModuleType("config")
    for name in dir(model_config):
        if name.isupper() and not name.startswith("_"):
            setattr(fixture, name, getattr(model_config, name))
    fixture.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_STATE_COHERENCE_TEST"
    fixture.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_STATE_COHERENCE_TEST"
    _INERT_COMPLETIONS = types.SimpleNamespace(create=Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(
        TripwireFailure("unexpected state-coherence provider request")
    )))
    inert_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_INERT_COMPLETIONS))
    _IMPORT_FIXTURE = ExitStack()
    _IMPORT_FIXTURE.enter_context(patch.dict(sys.modules, {"config": fixture}))
    factory_patcher = patch.object(ai_client_factory, "create_chat_client", return_value=inert_client)
    _FACTORY_MOCK = factory_patcher.start()
    _IMPORT_FIXTURE.callback(factory_patcher.stop)
    tmp_root = REPO_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    _ORIGINAL_CWD = Path.cwd()
    _IMPORT_CWD = Path(tempfile.mkdtemp(prefix="state-coherence-import-", dir=tmp_root))
    try:
        os.chdir(_IMPORT_CWD)
        import updates.update_character_info as character_update_module
        from core.managers import combat_manager as combat_owner
        from core.managers.multi_pc_combat import (
            CombatStateManager as state_manager,
            Combatant as combatant,
            CombatantType as combatant_type,
            MultiPCCombatManager as multi_pc_manager,
            PCStatus as pc_status,
        )
    except BaseException:
        os.chdir(_ORIGINAL_CWD)
        _IMPORT_FIXTURE.close()
        shutil.rmtree(_IMPORT_CWD, ignore_errors=True)
        raise
    finally:
        os.chdir(_ORIGINAL_CWD)
    combat_manager = combat_owner
    CombatStateManager = state_manager
    Combatant = combatant
    CombatantType = combatant_type
    MultiPCCombatManager = multi_pc_manager
    PCStatus = pc_status
    _apply_character_ops_deterministic = character_update_module._apply_character_ops_deterministic


def tearDownModule():
    import shutil
    if _IMPORT_FIXTURE is not None:
        _IMPORT_FIXTURE.close()
    for patcher in reversed(PRIVATE_READ_PATCHES):
        patcher.stop()
    if _IMPORT_CWD is not None:
        shutil.rmtree(_IMPORT_CWD, ignore_errors=True)


class TestCombatStateCoherenceRepair(unittest.TestCase):
    def test_initialize_from_party_dedupes_canonical_identities(self):
        state_mgr = CombatStateManager()
        party_data = {
            "partyMembers": [
                "xorn",
                "Xorn",
                "athelon",
                "Athelon",
                "lidda_underbough",
                "Lidda Underbough",
            ],
            "active_character": "athelon",
        }

        loaded_paths = []

        def fake_safe_json_load(path):
            path = str(path)
            loaded_paths.append(path)
            if path.endswith("characters/xorn.json"):
                return {"name": "Xorn", "hitPoints": 10, "maxHitPoints": 10, "armorClass": 16}
            if path.endswith("characters/athelon.json"):
                return {"name": "Athelon", "hitPoints": 11, "maxHitPoints": 11, "armorClass": 15}
            if path.endswith("characters/lidda_underbough.json"):
                return {"name": "Lidda Underbough", "hitPoints": 9, "maxHitPoints": 9, "armorClass": 15}
            return {}

        with patch("core.managers.multi_pc_combat.safe_json_load", side_effect=fake_safe_json_load):
            state_mgr.initialize_from_party(party_data)

        self.assertEqual(set(state_mgr.pc_states.keys()), {"Xorn", "Athelon", "Lidda Underbough"})
        self.assertEqual(state_mgr.current_pc_name, "Athelon")
        self.assertEqual(
            loaded_paths,
            [
                "characters/xorn.json",
                "characters/athelon.json",
                "characters/lidda_underbough.json",
            ],
        )

    def test_update_pc_hp_preserves_existing_death_save_counts(self):
        state_mgr = CombatStateManager()
        state_mgr.pc_states["Lidda Underbough"] = SimpleNamespace(
            current_hp=0,
            max_hp=9,
            status=PCStatus.INCAPACITATED,
            death_save_successes=0,
            death_save_failures=1,
        )

        state_mgr.update_pc_hp("Lidda Underbough", 0)

        self.assertEqual(state_mgr.pc_states["Lidda Underbough"].death_save_failures, 1)
        self.assertEqual(state_mgr.pc_states["Lidda Underbough"].status, PCStatus.INCAPACITATED)

    def test_dead_enemy_excluded_from_enemy_phase_and_tracker_window(self):
        manager = MultiPCCombatManager()
        manager._state.pc_states = {
            "Redax": SimpleNamespace(status=PCStatus.READY, current_hp=11, max_hp=11),
        }
        manager._state.current_pc_name = "Redax"
        manager._turns.turn_queue = [
            Combatant("Cultist_7", CombatantType.ENEMY, 19, -5, 9, 12, "alive"),
            Combatant("Cultist_4", CombatantType.ENEMY, 18, 9, 9, 12, "alive"),
            Combatant("Redax", CombatantType.PC, 9, 11, 11, 18, "alive"),
        ]

        remaining = manager.get_remaining_enemies_for_round()
        tracker = manager.format_initiative_tracker({})

        self.assertEqual(remaining, ["Cultist_4"])
        self.assertNotIn(">>> PROCESS ALL OF THESE IN ONE RESPONSE (Initiative Order):\n- Cultist_7", tracker)
        self.assertIn("- [D] Cultist_7 (19) - Dead", tracker)

    def test_find_target_prefers_living_enemy_and_rejects_dead_only(self):
        turn_mgr = MultiPCCombatManager()._turns
        turn_mgr.turn_queue = [
            Combatant("Cultist", CombatantType.ENEMY, 20, 0, 9, 12, "dead"),
            Combatant("Cultist_4", CombatantType.ENEMY, 18, 9, 9, 12, "alive"),
            Combatant("Cultist_9", CombatantType.ENEMY, 10, -15, 9, 12, "dead"),
        ]

        target = turn_mgr.find_target("cultist", {})
        dead_only = turn_mgr.find_target("cultist_9", {})

        self.assertIsNotNone(target)
        self.assertEqual(target.name, "Cultist_4")
        self.assertIsNone(dead_only)

    def test_incapacitated_pc_cannot_use_fast_lane_attack_commands(self):
        manager = MultiPCCombatManager()
        manager._state.pc_states = {
            "Lidda Underbough": SimpleNamespace(
                character_name="Lidda Underbough",
                status=PCStatus.INCAPACITATED,
                current_hp=0,
                max_hp=9,
            )
        }
        manager._state.current_pc_name = "Lidda Underbough"

        feedback, spoken_narration, log_msg, skip_llm = manager.handle_combat_command(
            "/att cultist 20",
            {"creatures": []},
            actor_name="lidda_underbough",
        )

        self.assertIn("cannot use /att while at 0 HP", feedback)
        self.assertIsNone(spoken_narration)
        self.assertIsNone(log_msg)
        self.assertTrue(skip_llm)

    def test_player_phase_prompt_uses_selected_active_pc_not_stale_queue_actor(self):
        manager = MultiPCCombatManager()
        manager._state.current_pc_name = "Redax"
        manager._state.pc_states = {
            "Redax": SimpleNamespace(status=PCStatus.READY, current_hp=11, max_hp=11),
            "Lidda Underbough": SimpleNamespace(status=PCStatus.INCAPACITATED, current_hp=0, max_hp=9),
        }
        manager._turns.turn_queue = [
            Combatant("Lidda Underbough", CombatantType.PC, 20, 0, 9, 15, "unconscious"),
            Combatant("Redax", CombatantType.PC, 9, 11, 11, 18, "alive"),
        ]
        manager._turns.current_turn_index = 0
        manager._turns.pc_phase_complete = False

        prompt = manager.get_required_response_prompt()

        self.assertIn("ACTIVE ACTOR: Redax", prompt)
        self.assertIn("Narrate ONLY the result of Redax's declared action.", prompt)
        self.assertNotIn("Lidda Underbough's declared action", prompt)

    def test_death_save_ops_apply_deterministically(self):
        character_data = {
            "name": "Lidda Underbough",
            "hitPoints": 0,
            "maxHitPoints": 9,
            "status": "unconscious",
            "condition": "unconscious",
            "condition_affected": ["unconscious"],
            "deathSaves": {"successes": 0, "failures": 0},
            "spellcasting": {"spellSlots": {"level1": {"current": 0, "max": 0}}},
            "equipment": [],
            "ammunition": [],
            "currency": {"gold": 0, "silver": 0, "copper": 0},
            "classFeatures": [],
        }

        success, updated_data, error_message, unsupported = _apply_character_ops_deterministic(
            character_data,
            [{"op": "death_save_failure", "delta": 1}],
        )

        self.assertTrue(success, error_message)
        self.assertEqual(unsupported, [])
        self.assertEqual(updated_data["deathSaves"], {"successes": 0, "failures": 1})
        self.assertEqual(updated_data["status"], "unconscious")

    def test_combat_manager_applies_ops_payloads_before_prose_fallback(self):
        queued = {}
        combat_manager._queue_final_character_update(
            queued,
            "Lidda Underbough",
            "Failed one death saving throw (1 failure, 0 successes).",
            [{"op": "death_save_failure", "delta": 1}],
        )
        combat_manager._queue_final_character_update(
            queued,
            "Lidda Underbough",
            "awarded 10 experience points",
            None,
        )

        update_calls = []
        sync_calls = []

        def fake_update_character_info(character_name, changes, ops=None):
            update_calls.append((character_name, changes, ops))
            return True

        def fake_safe_json_load(path):
            if str(path).endswith("characters/lidda_underbough.json"):
                return {
                    "name": "Lidda Underbough",
                    "hitPoints": 0,
                    "maxHitPoints": 9,
                    "status": "unconscious",
                    "deathSaves": {"successes": 0, "failures": 1},
                }
            return {}

        fake_manager = SimpleNamespace(
            pc_states={"Lidda Underbough": object()},
            sync_pc_persistent_state=lambda name, data: sync_calls.append((name, data.get("deathSaves"))),
        )

        with patch("core.managers.combat_manager.update_character_info", side_effect=fake_update_character_info), patch(
            "core.managers.combat_manager.safe_json_load", side_effect=fake_safe_json_load
        ):
            combat_manager._apply_final_character_updates(queued, fake_manager)

        self.assertEqual(len(update_calls), 2)
        self.assertIsNotNone(update_calls[0][2])
        self.assertIsNone(update_calls[1][2])
        self.assertEqual(sync_calls[0][1], {"successes": 0, "failures": 1})

    def test_schema_includes_nested_death_saves(self):
        schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas", "char_schema.json")
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

        self.assertIn("deathSaves", schema["properties"])
        self.assertEqual(
            schema["properties"]["deathSaves"]["required"],
            ["successes", "failures"],
        )


class TestImportSafetyProof(unittest.TestCase):
    def test_private_reads_are_denied_and_inert_import_client_is_never_used(self):
        for protected in ("config.py", "party_tracker.json"):
            target = REPO_ROOT / protected
            for operation, attempt in (
                ("builtins.open", lambda: builtins.open(target, "r", encoding="utf-8")),
                ("io.open", lambda: io.open(target, "r", encoding="utf-8")),
                ("os.open", lambda: os.open(target, os.O_RDONLY)),
            ):
                with self.subTest(path=protected, operation=operation), self.assertRaises(_PrivateRootReadDenied):
                    attempt()
        self.assertEqual(PRIVATE_READ_DENIALS, ["builtins.open", "io.open", "os.open"] * 2)
        self.assertGreater(_FACTORY_MOCK.call_count, 0)
        self.assertEqual(_INERT_COMPLETIONS.create.call_count, 0)
        PROCESS_TRIPWIRES.assert_untouched(self)
        for name in ("openai.OpenAI", "socket.socket", "urlopen"):
            guard = PROCESS_TRIPWIRES.calls[name]
            with self.subTest(guard=name), self.assertRaises(TripwireFailure):
                guard()
            guard.reset_mock()
        PROCESS_TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
