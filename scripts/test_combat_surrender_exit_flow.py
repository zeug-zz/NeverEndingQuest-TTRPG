# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - surrender/capture combat exit flow tests.

Focused regression coverage for the reported live failure mode:
- last hostile yields/captured but combat does not end,
- enemy batch omits a remaining hostile due to queue pointer,
- defeated captives remain eligible turn actors.
"""

import builtins
import json
import importlib
import importlib.util
import io
import os
import pathlib
import socket
import sys
import tempfile
import unittest
import urllib.request
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.managers.multi_pc_combat import Combatant, CombatantType, TurnQueueManager


class ForbiddenSideEffect(BaseException):
    """Fatal test guard for accidental provider, network, or external I/O."""


def _forbidden(*args, **kwargs):
    raise ForbiddenSideEffect("unexpected external side effect")


def _fake_client_factory():
    _fake_client_factory.constructor_calls += 1

    def reject_provider_call(*args, **kwargs):
        _fake_client_factory.provider_attempts += 1
        raise ForbiddenSideEffect("provider operation attempted")

    completions = SimpleNamespace(create=reject_provider_call)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


_fake_client_factory.provider_attempts = 0
_fake_client_factory.constructor_calls = 0
MISSING_JSONSCHEMA = importlib.util.find_spec("jsonschema") is None
ENCOUNTER_UPDATE_MODULE = None
_IMPORT_GUARD_AUDIT = {
    "blocked_factory": 0,
    "blocked_sdk_constructor": 0,
    "blocked_network": 0,
    "blocked_write": 0,
    "blocked_campaign_read": 0,
}
_IMPORT_ROOT = pathlib.Path.cwd().resolve()
_IMPORT_REAL_OPEN = builtins.open
_IMPORT_REAL_OS_OPEN = os.open


def _is_campaign_state_path(path):
    resolved = pathlib.Path(os.fspath(path)).resolve()
    try:
        relative = resolved.relative_to(_IMPORT_ROOT)
    except ValueError:
        return False
    return relative.as_posix() == "party_tracker.json" or bool(relative.parts and relative.parts[0] in {
        "modules", "characters", "data"
    })


def _guarded_import_factory(*args, **kwargs):
    _IMPORT_GUARD_AUDIT["blocked_factory"] += 1
    raise ForbiddenSideEffect("client factory tripwire")


def _guarded_sdk_constructor(*args, **kwargs):
    _IMPORT_GUARD_AUDIT["blocked_sdk_constructor"] += 1
    raise ForbiddenSideEffect("SDK constructor tripwire")


def _guarded_import_network(*args, **kwargs):
    _IMPORT_GUARD_AUDIT["blocked_network"] += 1
    raise ForbiddenSideEffect("network tripwire")


def _guarded_import_open(path, mode="r", *args, **kwargs):
    if any(flag in mode for flag in "wax+"):
        _IMPORT_GUARD_AUDIT["blocked_write"] += 1
        raise ForbiddenSideEffect("import-time write tripwire")
    if _is_campaign_state_path(path):
        _IMPORT_GUARD_AUDIT["blocked_campaign_read"] += 1
        raise ForbiddenSideEffect("campaign-state read tripwire")
    return _IMPORT_REAL_OPEN(path, mode, *args, **kwargs)


def _guarded_import_os_open(path, flags, *args, **kwargs):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if flags & write_flags:
        _IMPORT_GUARD_AUDIT["blocked_write"] += 1
        raise ForbiddenSideEffect("import-time os.open write tripwire")
    if _is_campaign_state_path(path):
        _IMPORT_GUARD_AUDIT["blocked_campaign_read"] += 1
        raise ForbiddenSideEffect("campaign-state os.open tripwire")
    return _IMPORT_REAL_OS_OPEN(path, flags, *args, **kwargs)


def _all_enemies_resolved(encounter_data):
    """Mirror combat-manager enemy resolution contract for exit gating."""
    if not encounter_data or "creatures" not in encounter_data:
        return False

    has_enemies = False
    all_defeated = True

    for creature in encounter_data.get("creatures", []):
        if creature.get("type") != "enemy":
            continue

        has_enemies = True
        current_hp = creature.get("currentHitPoints", 0)
        status = str(creature.get("status", "alive")).lower()
        if current_hp > 0 and status not in ("dead", "defeated", "unconscious"):
            all_defeated = False
            break

    return has_enemies and all_defeated


class TestSurrenderExitQueueBehavior(unittest.TestCase):
    """Queue-level behavior for capture/surrender combat wrap-up."""

    def test_enemy_batch_ignores_turn_pointer_for_end_phase(self):
        manager = TurnQueueManager()
        manager.turn_queue = [
            Combatant("Vitreol", CombatantType.PC, 19, 18, 18, 14, "alive"),
            Combatant("Blairen", CombatantType.PC, 17, 20, 20, 16, "alive"),
            Combatant("Bandit_2", CombatantType.ENEMY, 14, 0, 11, 12, "defeated"),
            Combatant("Scout Kira", CombatantType.NPC, 13, 12, 12, 13, "alive"),
            Combatant("Bandit_1", CombatantType.ENEMY, 11, 5, 11, 12, "alive"),
        ]

        expected = ["Scout Kira", "Bandit_1"]

        manager.current_turn_index = 0
        self.assertEqual(manager.get_remaining_enemies_for_round(), expected)

        manager.current_turn_index = 3
        self.assertEqual(manager.get_remaining_enemies_for_round(), expected)

        manager.current_turn_index = 4
        self.assertEqual(manager.get_remaining_enemies_for_round(), expected)

    def test_advance_turn_skips_captured_defeated_actor(self):
        manager = TurnQueueManager()
        manager.current_turn_index = 0
        manager.turn_queue = [
            Combatant("Chronos", CombatantType.PC, 20, 30, 30, 18, "alive"),
            Combatant("Captured Bandit", CombatantType.ENEMY, 16, 4, 11, 12, "defeated"),
            Combatant("Bandit Leader", CombatantType.ENEMY, 12, 9, 16, 13, "alive"),
        ]

        actor, rolled_over = manager.advance_turn()

        self.assertEqual(actor.name, "Bandit Leader")
        self.assertFalse(rolled_over)


@unittest.skipIf(MISSING_JSONSCHEMA, "jsonschema dependency unavailable")
class TestSurrenderExitEncounterState(unittest.TestCase):
    """Encounter-state behavior for last-hostile surrender/capture exits."""

    def setUp(self):
        self.encounter_id = "UNITTEST_SURRENDER_EXIT"
        self._scratch = tempfile.TemporaryDirectory(prefix="surrender_exit_", dir="tmp")
        self.addCleanup(self._scratch.cleanup)
        self.scratch_root = pathlib.Path(self._scratch.name)
        self.assertTrue(self.scratch_root.resolve().is_relative_to(pathlib.Path("tmp").resolve()))
        self.encounter_path = self.scratch_root / f"encounter_{self.encounter_id}.json"
        self.legacy_encounter_path = f"modules/encounters/encounter_{self.encounter_id}.json"
        self._write_fixture()

    def _guarded_call(self, callback):
        scratch_encounter = self.encounter_path.resolve()
        legacy_encounter = self.legacy_encounter_path
        real_open = open
        real_os_open = os.open
        external_io_attempts = []
        network_attempts = []

        def guarded_open(path, mode="r", *args, **kwargs):
            raw_path = os.fspath(path)
            if raw_path == legacy_encounter:
                raw_path = str(scratch_encounter)
            resolved = pathlib.Path(raw_path).resolve()
            if resolved != scratch_encounter:
                external_io_attempts.append(raw_path)
                raise ForbiddenSideEffect(f"unexpected file access outside fixture: {raw_path}")
            return real_open(resolved, mode, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            resolved = pathlib.Path(path).resolve()
            if resolved != scratch_encounter:
                external_io_attempts.append(os.fspath(path))
                raise ForbiddenSideEffect(f"unexpected os.open outside fixture: {path}")
            return real_os_open(resolved, flags, *args, **kwargs)

        def guarded_network(*args, **kwargs):
            network_attempts.append("network")
            raise ForbiddenSideEffect("network access attempted")

        def scratch_party_tracker(path):
            if path == "party_tracker.json":
                return {"module": "surrender_exit_fixture"}
            raise ForbiddenSideEffect(f"unexpected party/state read: {path}")

        update_module = ENCOUNTER_UPDATE_MODULE
        self.assertIsNotNone(update_module)
        self.assertEqual(_fake_client_factory.provider_attempts, 0)
        self.assertEqual(_fake_client_factory.constructor_calls, 0)
        with mock.patch("builtins.open", side_effect=guarded_open), \
             mock.patch("os.open", side_effect=guarded_os_open), \
             mock.patch("os.remove", side_effect=_forbidden), \
             mock.patch("os.rename", side_effect=_forbidden), \
             mock.patch("os.replace", side_effect=_forbidden), \
             mock.patch("os.mkdir", side_effect=_forbidden), \
             mock.patch("os.makedirs", side_effect=_forbidden), \
             mock.patch("pathlib.Path.unlink", side_effect=_forbidden), \
             mock.patch("pathlib.Path.rename", side_effect=_forbidden), \
             mock.patch("pathlib.Path.replace", side_effect=_forbidden), \
              mock.patch("socket.socket", side_effect=guarded_network), \
              mock.patch("socket.create_connection", side_effect=guarded_network), \
              mock.patch("pathlib.Path.write_text", side_effect=_forbidden), \
              mock.patch("pathlib.Path.write_bytes", side_effect=_forbidden), \
             mock.patch("utils.encoding_utils.safe_json_load", side_effect=scratch_party_tracker), \
             mock.patch.object(update_module, "load_encounter_schema", return_value=self.schema), \
             mock.patch.object(update_module, "_sync_non_enemy_creatures", return_value=None) as sync_mock, \
             mock.patch.object(update_module, "debug"), \
             mock.patch.object(update_module, "info"), \
             mock.patch.object(update_module, "warning"), \
             mock.patch.object(update_module, "error"):
            updated = callback(update_module)

        self.assertEqual(_fake_client_factory.provider_attempts, 0)
        self.assertEqual(external_io_attempts, [])
        self.assertEqual(network_attempts, [])
        self.assertTrue(sync_mock.called)
        return updated

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if MISSING_JSONSCHEMA:
            return
        # Load optional import dependencies before arming the import tripwires.
        import jsonschema  # noqa: F401
        import config  # noqa: F401
        import utils.ai_client_factory as ai_client_factory
        import utils.enhanced_logger  # noqa: F401
        import utils.encoding_utils  # noqa: F401
        import utils.module_path_manager  # noqa: F401
        import utils.openai_usage_tracker  # noqa: F401

        global ENCOUNTER_UPDATE_MODULE
        if "updates.update_encounter" in sys.modules:
            raise AssertionError("update_encounter was imported before the factory tripwire")
        with ExitStack() as guards:
            guards.enter_context(mock.patch.object(
                ai_client_factory, "create_chat_client", side_effect=_fake_client_factory
            ))
            guards.enter_context(mock.patch.object(
                ai_client_factory, "OpenAI", side_effect=_guarded_sdk_constructor
            ))
            guards.enter_context(mock.patch("builtins.open", side_effect=_guarded_import_open))
            guards.enter_context(mock.patch("io.open", side_effect=_guarded_import_open))
            guards.enter_context(mock.patch("os.open", side_effect=_guarded_import_os_open))
            guards.enter_context(mock.patch("os.remove", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.rename", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.replace", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.mkdir", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.makedirs", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.unlink", side_effect=_forbidden))
            guards.enter_context(mock.patch("os.rmdir", side_effect=_forbidden))
            guards.enter_context(mock.patch("pathlib.Path.unlink", side_effect=_forbidden))
            guards.enter_context(mock.patch("socket.socket", side_effect=_guarded_import_network))
            guards.enter_context(mock.patch("socket.create_connection", side_effect=_guarded_import_network))
            guards.enter_context(mock.patch("urllib.request.urlopen", side_effect=_guarded_import_network))
            previous_bytecode_setting = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                ENCOUNTER_UPDATE_MODULE = importlib.import_module("updates.update_encounter")
            finally:
                sys.dont_write_bytecode = previous_bytecode_setting
        if _fake_client_factory.constructor_calls != 0:
            raise AssertionError("updates.update_encounter constructed a provider client during import")
        if _fake_client_factory.provider_attempts:
            raise AssertionError("provider operation attempted during module import")
        if any(_IMPORT_GUARD_AUDIT.values()):
            raise AssertionError(f"an import tripwire fired unexpectedly: {_IMPORT_GUARD_AUDIT}")
        cls.import_guard_clean_counts = dict(_IMPORT_GUARD_AUDIT)
        schema_path = pathlib.Path("schemas/encounter_schema.json")
        with schema_path.open("r", encoding="utf-8") as handle:
            cls.schema = json.load(handle)

    def test_import_tripwires_fatally_reject_factory_sdk_network_and_write(self):
        import utils.ai_client_factory as ai_client_factory

        before = dict(_IMPORT_GUARD_AUDIT)
        with mock.patch.object(ai_client_factory, "create_chat_client", side_effect=_guarded_import_factory):
            with self.assertRaises(ForbiddenSideEffect):
                ai_client_factory.create_chat_client()
        with mock.patch.object(ai_client_factory, "OpenAI", side_effect=_guarded_sdk_constructor):
            with self.assertRaises(ForbiddenSideEffect):
                ai_client_factory.OpenAI()
        with mock.patch.object(socket, "socket", side_effect=_guarded_import_network):
            with self.assertRaises(ForbiddenSideEffect):
                socket.socket()
        with mock.patch.object(builtins, "open", side_effect=_guarded_import_open):
            with self.assertRaises(ForbiddenSideEffect):
                open("tmp/combat_import_guard_probe", "w", encoding="utf-8")
        self.assertFalse(hasattr(ENCOUNTER_UPDATE_MODULE, "client"))

        self.assertEqual(
            {key: _IMPORT_GUARD_AUDIT[key] - before[key] for key in before},
            {
                "blocked_factory": 1,
                "blocked_sdk_constructor": 1,
                "blocked_network": 1,
                "blocked_write": 1,
                "blocked_campaign_read": 0,
            },
        )

    def _write_fixture(self):
        fixture = {
            "encounterId": self.encounter_id,
            "encounterSummary": "Surrender exit regression fixture",
            "creatures": [
                {
                    "name": "UT_Player_One",
                    "type": "player",
                    "initiative": 20,
                    "status": "alive",
                    "conditions": [],
                    "currentHitPoints": 30,
                    "maxHitPoints": 30,
                    "actions": {"actionType": "attack", "target": "enemy"},
                },
                {
                    "name": "UT_Companion_One",
                    "type": "npc",
                    "npcType": "ally",
                    "initiative": 13,
                    "status": "alive",
                    "conditions": [],
                    "currentHitPoints": 12,
                    "maxHitPoints": 12,
                    "actions": {"actionType": "attack", "target": "enemy"},
                },
                {
                    "name": "UT_Bandit",
                    "type": "enemy",
                    "monsterType": "bandit",
                    "initiative": 11,
                    "status": "alive",
                    "conditions": [],
                    "actions": {"actionType": "attack", "target": "pc"},
                    "currentHitPoints": 5,
                    "maxHitPoints": 11,
                },
            ],
        }
        with self.encounter_path.open("w", encoding="utf-8") as file_handle:
            json.dump(fixture, file_handle, indent=2)

    def _read_encounter(self):
        with self.encounter_path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def test_last_hostile_set_to_defeated_satisfies_exit_gate(self):
        # Simulate LLM + runtime capture/surrender resolution for final hostile.
        self.assertIsNotNone(ENCOUNTER_UPDATE_MODULE)
        updated = self._guarded_call(
            lambda update_module: update_module.update_encounter(
                self.encounter_id,
                "Bandit yields and is captured.",
                ops=[
                    {"op": "set_status", "creature": "UT_Bandit", "status": "defeated"},
                    {"op": "condition_add", "creature": "UT_Bandit", "condition": "Restrained"},
                ],
            )
        )

        self.assertIsNotNone(updated)
        self.assertTrue(_all_enemies_resolved(updated))

        persisted = self._read_encounter()
        self.assertTrue(_all_enemies_resolved(persisted))
        enemy = next(c for c in persisted["creatures"] if c.get("type") == "enemy")
        self.assertEqual(enemy.get("status"), "defeated")
        self.assertIn("Restrained", enemy.get("conditions", []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
