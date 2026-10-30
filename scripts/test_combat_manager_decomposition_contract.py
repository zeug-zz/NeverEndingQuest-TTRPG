# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Focused package/shim identity and monkeypatch compatibility checks."""

import importlib
import builtins
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
import shutil
import types
import unittest
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The actual combat package is imported below under process-wide fatal guards.
# The only mocked production dependency is its unused import-time chat-client
# factory seam; the real owners, aliases, callbacks, and lifecycle code remain.
from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires


PROCESS_TRIPWIRES = arm_process_tripwires()


class _PrivateRootReadDenied(BaseException):
    """Fatal sentinel for reads of private root configuration/runtime files."""


def _is_private_root_read(path):
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate.parent.resolve() == REPO_ROOT and candidate.name in {
            "config.py",
            "party_tracker.json",
        }
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    denials = []

    def check(path, operation):
        if _is_private_root_read(path):
            denials.append(operation)
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
    return patches, denials


def _dummy_config_fixture(model_config):
    fixture = types.ModuleType("config")
    for name in dir(model_config):
        if name.isupper() and not name.startswith("_"):
            setattr(fixture, name, getattr(model_config, name))
    fixture.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_COMBAT_CONTRACT"
    fixture.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_COMBAT_CONTRACT"
    return fixture


class _InertCompletions:
    requests = 0

    def create(self, *args, **kwargs):
        self.requests += 1
        raise TripwireFailure("unexpected combat contract provider request")


def setUpModule():
    """Import real owners under fatal guards and an import-only tmp CWD."""
    global _IMPORT_FIXTURE, _PRIVATE_READ_PATCHES, _PRIVATE_READ_DENIALS
    global _INERT_CLIENT, _INERT_COMPLETIONS, _FACTORY_PATCHER, _FACTORY_MOCK
    global _ORIGINAL_CWD, _IMPORT_CWD
    _PRIVATE_READ_PATCHES, _PRIVATE_READ_DENIALS = _arm_private_root_read_guard()

    # model_config is public/checked-in. A dummy private config module supplies
    # only those constants plus nonempty sentinel credentials; config.py itself
    # is never read.
    import model_config
    from utils import ai_client_factory

    _INERT_COMPLETIONS = _InertCompletions()
    _INERT_CLIENT = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_INERT_COMPLETIONS)
    )
    _IMPORT_FIXTURE = ExitStack()
    _IMPORT_FIXTURE.enter_context(
        patch.dict(sys.modules, {"config": _dummy_config_fixture(model_config)})
    )
    _FACTORY_PATCHER = patch.object(
        ai_client_factory, "create_chat_client", return_value=_INERT_CLIENT
    )
    _FACTORY_MOCK = _FACTORY_PATCHER.start()
    _IMPORT_FIXTURE.callback(_FACTORY_PATCHER.stop)

    tmp_root = REPO_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    _IMPORT_CWD = Path(tempfile.mkdtemp(prefix="combat-manager-contract-", dir=tmp_root))
    _ORIGINAL_CWD = Path.cwd()
    owner_modules = (
        "core.managers.combat_manager",
        "core.combat.combat_manager",
        "core.combat",
        "core.combat.multi_pc",
        "core.combat.multi_pc.state",
        "core.combat.multi_pc.turn_queue",
        "core.combat.multi_pc.manager",
        "core.managers.multi_pc_combat",
        "core.combat.session",
        "core.combat.multi_pc.dm_note",
    )
    try:
        os.chdir(_IMPORT_CWD)
        for module_name in owner_modules:
            importlib.import_module(module_name)
    except BaseException:
        os.chdir(_ORIGINAL_CWD)
        _IMPORT_FIXTURE.close()
        for patcher in reversed(_PRIVATE_READ_PATCHES):
            patcher.stop()
        shutil.rmtree(_IMPORT_CWD, ignore_errors=True)
        raise
    finally:
        os.chdir(_ORIGINAL_CWD)


def tearDownModule():
    # All test-owned worker threads join in their cases; restore fixture
    # dependencies before removing only this fixture's import-time scratch.
    _IMPORT_FIXTURE.close()
    for patcher in reversed(_PRIVATE_READ_PATCHES):
        patcher.stop()
    shutil.rmtree(_IMPORT_CWD, ignore_errors=True)


_CHILD_IMPORT_GUARDS = r'''\
import builtins, io, os, pathlib, shutil, sys, tempfile, types, atexit
from unittest import mock
root = pathlib.Path.cwd().resolve()
sys.path.insert(0, str(root))
from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires
guards = arm_process_tripwires()
private_denials = []
def private_path(path):
    try:
        candidate = pathlib.Path(os.fsdecode(path))
        if not candidate.is_absolute(): candidate = root / candidate
        return candidate.parent.resolve() == root and candidate.name in {"config.py", "party_tracker.json"}
    except (TypeError, ValueError, OSError): return False
real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
def check(path, operation):
    if private_path(path):
        private_denials.append(operation)
        raise TripwireFailure("private root read denied: " + operation)
def guarded_open(path, mode="r", *args, **kwargs):
    check(path, "builtins.open"); return real_open(path, mode, *args, **kwargs)
def guarded_io_open(path, mode="r", *args, **kwargs):
    check(path, "io.open"); return real_io_open(path, mode, *args, **kwargs)
def guarded_os_open(path, flags, *args, **kwargs):
    check(path, "os.open"); return real_os_open(path, flags, *args, **kwargs)
for target, replacement in (("builtins.open", guarded_open), ("io.open", guarded_io_open), ("os.open", guarded_os_open)):
    mock.patch(target, replacement).start()
import model_config
fixture = types.ModuleType("config")
for name in dir(model_config):
    if name.isupper() and not name.startswith("_"): setattr(fixture, name, getattr(model_config, name))
fixture.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_LAZY_IMPORT_CONTRACT"
fixture.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_LAZY_IMPORT_CONTRACT"
sys.modules["config"] = fixture
from utils import ai_client_factory
class InertCompletions:
    requests = 0
    def create(self, *args, **kwargs):
        self.requests += 1
        raise TripwireFailure("unexpected child import provider request")
completions = InertCompletions()
client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
factory_patch = mock.patch.object(ai_client_factory, "create_chat_client", return_value=client)
factory_patch.start()
scratch_root = root / "tmp"
scratch_root.mkdir(exist_ok=True)
scratch = pathlib.Path(tempfile.mkdtemp(prefix="combat-lazy-import-", dir=scratch_root))
atexit.register(lambda: shutil.rmtree(scratch, ignore_errors=True))
def _safe_import(statement):
    original = pathlib.Path.cwd()
    try:
        os.chdir(scratch)
        exec(statement, globals())
    finally:
        os.chdir(original)
'''


class ForbiddenSideEffect(BaseException):
    """Fatal tripwire for provider, network, and filesystem effects."""


def _forbidden_side_effect(*args, **kwargs):
    raise ForbiddenSideEffect("unexpected combat boundary side effect")


class CombatManagerPackageBoundaryTests(unittest.TestCase):
    def test_import_fixture_keeps_fatal_guards_and_inert_factory_untouched(self):
        self.assertIsNotNone(_FACTORY_PATCHER)
        self.assertGreater(_FACTORY_MOCK.call_count, 0)
        self.assertEqual(_INERT_COMPLETIONS.requests, 0)
        self.assertEqual(_PRIVATE_READ_DENIALS, [])
        PROCESS_TRIPWIRES.assert_untouched(self)

        with self.assertRaises(_PrivateRootReadDenied):
            builtins.open(REPO_ROOT / "config.py", "r", encoding="utf-8")
        with self.assertRaises(_PrivateRootReadDenied):
            (REPO_ROOT / "party_tracker.json").read_text(encoding="utf-8")
        with self.assertRaises(_PrivateRootReadDenied):
            os.open(REPO_ROOT / "config.py", os.O_RDONLY)
        self.assertEqual(
            _PRIVATE_READ_DENIALS,
            ["builtins.open", "io.open", "os.open"],
        )
        self.assertEqual(_INERT_COMPLETIONS.requests, 0)
        PROCESS_TRIPWIRES.assert_untouched(self)

    def test_old_and_new_paths_are_the_same_module(self):
        old = importlib.import_module("core.managers.combat_manager")
        new = importlib.import_module("core.combat.combat_manager")
        package = importlib.import_module("core.combat")
        self.assertIs(old, new)
        self.assertIs(package.validate_combatant_integrity, new.validate_combatant_integrity)
        self.assertLess(len(Path("core/managers/combat_manager.py").read_text(encoding="utf-8").splitlines()), 100)

    def test_legacy_monkeypatch_changes_package_global(self):
        old = importlib.import_module("core.managers.combat_manager")
        new = importlib.import_module("core.combat.combat_manager")
        original = new.TEMPERATURE
        try:
            old.TEMPERATURE = 0.123
            self.assertEqual(new.TEMPERATURE, 0.123)
        finally:
            new.TEMPERATURE = original

    def test_multi_pc_classes_keep_package_ownership_and_legacy_identity(self):
        package = importlib.import_module("core.combat.multi_pc")
        state = importlib.import_module("core.combat.multi_pc.state")
        queue = importlib.import_module("core.combat.multi_pc.turn_queue")
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        manager = importlib.import_module("core.combat.multi_pc.manager")
        self.assertIs(package.MultiPCCombatManager, manager.MultiPCCombatManager)
        self.assertIs(package.CombatStateManager, state.CombatStateManager)
        self.assertIs(package.TurnQueueManager, queue.TurnQueueManager)
        self.assertIs(package.Combatant, queue.Combatant)
        self.assertIs(package.PCStatus, state.PCStatus)
        self.assertEqual(state.CombatStateManager.__module__, state.__name__)
        self.assertEqual(queue.TurnQueueManager.__module__, queue.__name__)
        self.assertIs(legacy, manager)
        self.assertIs(legacy.CombatStateManager, state.CombatStateManager)
        self.assertIs(legacy.TurnQueueManager, queue.TurnQueueManager)

    def test_direct_state_patch_survives_nested_legacy_patch_exception(self):
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        state = importlib.import_module("core.combat.multi_pc.state")
        original_loader = state.safe_json_load
        outer_loader = Mock(return_value={"name": "Outer"})
        inner_loader = Mock(return_value={"name": "Inner"})

        with patch.object(state, "safe_json_load", outer_loader):
            self.assertIs(state.safe_json_load, outer_loader)
            self.assertIs(state.__dict__["safe_json_load"], outer_loader)
            self.assertIs(legacy.__dict__["safe_json_load"], outer_loader)
            self.assertEqual(state.__dict__["safe_json_load"]("state-outer.json"), {"name": "Outer"})
            self.assertEqual(legacy.__dict__["safe_json_load"]("manager-outer.json"), {"name": "Outer"})
            with self.assertRaisesRegex(RuntimeError, "loader context"):
                with patch.object(legacy, "safe_json_load", inner_loader):
                    self.assertIs(state.safe_json_load, inner_loader)
                    self.assertIs(state.__dict__["safe_json_load"], inner_loader)
                    self.assertIs(legacy.__dict__["safe_json_load"], inner_loader)
                    self.assertEqual(state.__dict__["safe_json_load"]("state-inner.json"), {"name": "Inner"})
                    self.assertEqual(legacy.__dict__["safe_json_load"]("manager-inner.json"), {"name": "Inner"})
                    raise RuntimeError("loader context")
            self.assertIs(state.safe_json_load, outer_loader)
            self.assertIs(state.__dict__["safe_json_load"], outer_loader)
            self.assertIs(legacy.__dict__["safe_json_load"], outer_loader)

        self.assertIs(state.safe_json_load, original_loader)
        self.assertIs(state.__dict__["safe_json_load"], original_loader)
        self.assertIs(legacy.__dict__["safe_json_load"], original_loader)
        self.assertEqual(outer_loader.call_args_list, [
            unittest.mock.call("state-outer.json"),
            unittest.mock.call("manager-outer.json"),
        ])
        self.assertEqual(inner_loader.call_args_list, [
            unittest.mock.call("state-inner.json"),
            unittest.mock.call("manager-inner.json"),
        ])

    def test_legacy_patch_survives_nested_direct_state_patch_exception(self):
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        state = importlib.import_module("core.combat.multi_pc.state")
        original_loader = state.safe_json_load
        outer_loader = Mock(return_value={"name": "Outer"})
        inner_loader = Mock(return_value={"name": "Inner"})

        with patch.object(legacy, "safe_json_load", outer_loader):
            self.assertIs(state.__dict__["safe_json_load"], outer_loader)
            self.assertIs(legacy.__dict__["safe_json_load"], outer_loader)
            self.assertEqual(state.__dict__["safe_json_load"]("state-outer.json"), {"name": "Outer"})
            self.assertEqual(legacy.__dict__["safe_json_load"]("manager-outer.json"), {"name": "Outer"})
            with self.assertRaisesRegex(RuntimeError, "state loader context"):
                with patch.object(state, "safe_json_load", inner_loader):
                    self.assertIs(state.safe_json_load, inner_loader)
                    self.assertIs(state.__dict__["safe_json_load"], inner_loader)
                    self.assertIs(legacy.__dict__["safe_json_load"], inner_loader)
                    self.assertEqual(state.__dict__["safe_json_load"]("state-inner.json"), {"name": "Inner"})
                    self.assertEqual(legacy.__dict__["safe_json_load"]("manager-inner.json"), {"name": "Inner"})
                    raise RuntimeError("state loader context")
            self.assertIs(state.safe_json_load, outer_loader)
            self.assertIs(state.__dict__["safe_json_load"], outer_loader)
            self.assertIs(legacy.__dict__["safe_json_load"], outer_loader)

        self.assertIs(state.safe_json_load, original_loader)
        self.assertIs(state.__dict__["safe_json_load"], original_loader)
        self.assertIs(legacy.__dict__["safe_json_load"], original_loader)
        self.assertEqual(outer_loader.call_args_list, [
            unittest.mock.call("state-outer.json"),
            unittest.mock.call("manager-outer.json"),
        ])
        self.assertEqual(inner_loader.call_args_list, [
            unittest.mock.call("state-inner.json"),
            unittest.mock.call("manager-inner.json"),
        ])

    def test_direct_state_loader_patch_remains_effective(self):
        state = importlib.import_module("core.combat.multi_pc.state")
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        fake_loader = Mock(return_value={"name": "Direct"})

        with patch.object(state, "safe_json_load", fake_loader):
            self.assertIs(legacy.safe_json_load, fake_loader)
            state_manager = state.CombatStateManager()
            state_manager.initialize_from_party({"partyMembers": ["Fixture PC"]})
            self.assertEqual(list(state_manager.pc_states), ["Direct"])

        fake_loader.assert_called_once_with("characters/fixture_pc.json")

    def test_package_lifecycle_and_callback_exports_keep_identity(self):
        package = importlib.import_module("core.combat.multi_pc")
        manager = importlib.import_module("core.combat.multi_pc.manager")
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        self.assertIs(package.temporary_combat_manager, manager.temporary_combat_manager)
        self.assertIs(package.temporary_combat_callback, manager.temporary_combat_callback)
        self.assertIs(package.get_combat_manager, legacy.get_combat_manager)
        sentinel = object()
        with package.temporary_combat_manager(sentinel):
            self.assertIs(package.get_combat_manager(), sentinel)
        self.assertIsNone(package.get_combat_manager())

    def test_every_package_all_entry_resolves(self):
        package = importlib.import_module("core.combat.multi_pc")
        for name in package.__all__:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(package, name))
        self.assertFalse(hasattr(package, "get_multi_pc_dm_note_initiative_narrative"))

    def test_public_types_and_lifecycle_callbacks_match_legacy_module(self):
        package = importlib.import_module("core.combat.multi_pc")
        legacy = importlib.import_module("core.managers.multi_pc_combat")
        for name in (
            "MultiPCCombatManager",
            "PCStatus",
            "PCCombatState",
            "CombatStateManager",
            "CombatantType",
            "Combatant",
            "TurnQueueManager",
            "temporary_combat_manager",
            "temporary_combat_callback",
            "reset_combat_state",
            "set_combat_callback",
            "emit_combat_event",
            "get_combat_manager",
            "create_combat_manager",
            "end_combat_session",
            "cleanup_combat_manager",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(package, name), getattr(legacy, name))

    def test_narrow_imports_are_lazy_and_do_not_construct_combat_owner(self):
        code = _CHILD_IMPORT_GUARDS + """
import sys
_safe_import("import core.combat")
assert 'core.combat.combat_manager' not in sys.modules
_safe_import("import core.combat.multi_pc.state")
_safe_import("import core.combat.multi_pc.dm_note")
_safe_import("import utils.multi_pc_dm_note")
assert 'core.combat.combat_manager' not in sys.modules
_safe_import("import core.managers.multi_pc_combat")
assert 'core.combat.combat_manager' not in sys.modules
assert completions.requests == 0 and private_denials == []
assert all(getattr(guard, "call_count", 0) == 0 for guard in guards.calls.values())
print('lazy narrow imports pass')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("lazy narrow imports pass", result.stdout)

    def test_public_package_import_is_lazy_until_owner_access(self):
        code = _CHILD_IMPORT_GUARDS + """
import sys
_safe_import("from core.combat.multi_pc import PCStatus")
assert 'core.combat.multi_pc.manager' not in sys.modules
assert PCStatus.__module__ == 'core.combat.multi_pc.state'
assert 'core.combat.multi_pc.manager' not in sys.modules
_safe_import("from core.combat.multi_pc import MultiPCCombatManager")
assert MultiPCCombatManager.__module__ == 'core.combat.multi_pc.manager'
assert 'core.combat.multi_pc.manager' in sys.modules
assert completions.requests == 0 and private_denials == []
assert all(getattr(guard, "call_count", 0) == 0 for guard in guards.calls.values())
print('public lazy imports pass')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("public lazy imports pass", result.stdout)


class MultiPCDMNoteAdapterTests(unittest.TestCase):
    def test_four_adapters_match_real_manager_and_known_stub_methods(self):
        dm_note = importlib.import_module("core.combat.multi_pc.dm_note")
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        state_module = importlib.import_module("core.combat.multi_pc.state")
        real_manager = manager_module.MultiPCCombatManager()
        real_manager._state.pc_states = {
            "Fixture PC": state_module.PCCombatState(
                character_name="Fixture PC", current_hp=10, max_hp=10
            )
        }
        real_manager._state.party_initiative = 14
        real_manager._state.enemy_initiative = 9
        real_manager._state.party_goes_first = True
        encounter_data = {"creatures": []}

        self.assertEqual(
            dm_note.format_multi_pc_head_context(real_manager),
            real_manager.format_multi_pc_head_context(),
        )
        self.assertEqual(
            dm_note.format_party_turn_summary(real_manager),
            real_manager.format_party_turn_summary(),
        )
        self.assertEqual(
            dm_note.format_initiative_tracker(real_manager, encounter_data),
            real_manager.format_initiative_tracker(encounter_data),
        )
        self.assertEqual(
            dm_note.get_multi_pc_initiative_narrative(real_manager),
            manager_module.get_multi_pc_initiative_narrative(real_manager),
        )

        class StubManager:
            def format_multi_pc_head_context(self):
                return "head"

            def format_party_turn_summary(self):
                return "turns"

            def format_initiative_tracker(self, data):
                return f"initiative:{data['id']}"

        stub = StubManager()
        self.assertEqual(dm_note.format_multi_pc_head_context(stub), "head")
        self.assertEqual(dm_note.format_party_turn_summary(stub), "turns")
        self.assertEqual(dm_note.format_initiative_tracker(stub, {"id": "fixture"}), "initiative:fixture")


class CombatSessionOwnershipTests(unittest.TestCase):
    def test_session_entry_binds_state_and_preserves_explicit_none(self):
        combat = importlib.import_module("core.combat.combat_manager")
        session_module = importlib.import_module("core.combat.session")
        session = session_module.CombatSession(encounter={}, active_pc="Acheron")
        captured = {}

        def fake_internal(encounter_id, party_data, location, *, session):
            captured["session"] = session
            session.bind_encounter({"id": "runtime"})
            session.bind_history([{"role": "system", "content": "history"}])
            session.set_phase("ENEMY_PHASE")
            session.active_pc = "Merisiel"
            return "dialogue", {"name": "Acheron"}

        with patch.object(combat, "_run_combat_simulation_internal", fake_internal):
            result = combat.run_combat_simulation_session(session, {"active_character": "Acheron"}, {})

        self.assertEqual(result, ("dialogue", {"name": "Acheron"}))
        self.assertIs(captured["session"], session)
        self.assertEqual(session.encounter, {"id": "runtime"})
        self.assertEqual(session.history, [{"role": "system", "content": "history"}])
        self.assertEqual(session.active_pc, "Merisiel")
        self.assertEqual(session.phase, "ENEMY_PHASE")

    def test_nested_and_threaded_contexts_do_not_leak_explicit_none(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        outer = object()
        nested = object()
        results = []

        with manager_module.temporary_combat_manager(outer):
            self.assertIs(manager_module.get_combat_manager(), outer)
            try:
                with manager_module.temporary_combat_manager(None):
                    self.assertIsNone(manager_module.get_combat_manager())
                    with manager_module.temporary_combat_manager(nested):
                        self.assertIs(manager_module.get_combat_manager(), nested)
                    self.assertIsNone(manager_module.get_combat_manager())
                    raise RuntimeError("nested context test")
            except RuntimeError:
                pass
            self.assertIs(manager_module.get_combat_manager(), outer)

            def worker():
                with manager_module.temporary_combat_manager(None):
                    results.append(manager_module.get_combat_manager())

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()

        self.assertEqual(results, [None])

    def test_callback_contexts_are_isolated_and_restore_after_exception(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        events = []
        callback = lambda event, data: events.append((event, data))

        with manager_module.temporary_combat_callback(callback):
            manager_module.emit_combat_event("outer", {})
            try:
                with manager_module.temporary_combat_callback(None):
                    manager_module.emit_combat_event("suppressed", {})
                    raise RuntimeError("callback context test")
            except RuntimeError:
                pass
            manager_module.emit_combat_event("restored", {})

        self.assertEqual([event for event, _ in events], ["outer", "restored"])

    def test_unbound_worker_reads_global_callback_and_bound_none_only_suppresses_local(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        events = []
        callback = lambda event, data: events.append((event, data))
        manager_module.reset_combat_state()
        manager_module.set_combat_callback(callback)

        worker = threading.Thread(target=lambda: manager_module.emit_combat_event("worker", {}))
        worker.start()
        worker.join()
        self.assertEqual([event for event, _ in events], ["worker"])

        with manager_module.temporary_combat_callback(None):
            manager_module.emit_combat_event("bound-suppressed", {})
            worker = threading.Thread(target=lambda: manager_module.emit_combat_event("unbound", {}))
            worker.start()
            worker.join()
        self.assertEqual([event for event, _ in events], ["worker", "unbound"])

    def test_unbound_worker_sees_mock_created_manager(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        manager_module.reset_combat_state()
        created = Mock()
        with patch.object(manager_module, "MultiPCCombatManager", return_value=created) as constructor:
            # The lightweight mock exercises the actual create entry without
            # requiring character files or a running web server.
            created.get_combat_state_summary.return_value = {}
            result = manager_module.create_combat_manager({"partyMembers": []})
        self.assertIs(result, created)
        observed = []
        worker = threading.Thread(target=lambda: observed.append(manager_module.get_combat_manager()))
        worker.start()
        worker.join()
        self.assertEqual(observed, [created])
        constructor.assert_called_once_with()

    def test_session_entry_binds_supplied_manager_and_restores_after_exception(self):
        combat = importlib.import_module("core.combat.combat_manager")
        session_module = importlib.import_module("core.combat.session")
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        supplied = object()
        prior = object()
        session = session_module.CombatSession(encounter={}, multi_pc_manager=supplied, encounter_id="E")

        def failing_internal(*args, **kwargs):
            self.assertIs(manager_module.get_combat_manager(), supplied)
            raise RuntimeError("lifecycle test")

        with manager_module.temporary_combat_manager(prior):
            with patch.object(combat, "_run_combat_simulation_internal", failing_internal):
                with self.assertRaisesRegex(RuntimeError, "lifecycle test"):
                    combat.run_combat_simulation_session(session, {}, {})
            self.assertIs(manager_module.get_combat_manager(), prior)

    def test_two_manager_contexts_and_two_callback_contexts_are_isolated(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        manager_results = []
        callback_results = []

        def manager_worker(value):
            with manager_module.temporary_combat_manager(value):
                manager_results.append(manager_module.get_combat_manager())

        def callback_worker(value):
            with manager_module.temporary_combat_callback(value):
                manager_module.emit_combat_event("thread", {})

        callback_a = lambda event, data: callback_results.append("a")
        callback_b = lambda event, data: callback_results.append("b")
        threads = [
            threading.Thread(target=manager_worker, args=("manager-a",)),
            threading.Thread(target=manager_worker, args=("manager-b",)),
            threading.Thread(target=callback_worker, args=(callback_a,)),
            threading.Thread(target=callback_worker, args=(callback_b,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(manager_results, ["manager-a", "manager-b"])
        self.assertCountEqual(callback_results, ["a", "b"])

    def test_legacy_private_patches_override_bound_reset_context_and_restore(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        manager_module.reset_combat_state()
        patched_events = []
        patched_manager = object()
        with patch.object(manager_module, "_combat_callback", lambda event, data: patched_events.append(event)):
            with patch.object(manager_module, "_active_combat_manager", patched_manager):
                self.assertIs(manager_module.get_combat_manager(), patched_manager)
                manager_module.emit_combat_event("patched", {})
        self.assertEqual(patched_events, ["patched"])
        self.assertIsNone(manager_module.get_combat_manager())
        self.assertIsNone(manager_module._combat_callback)

    def test_legacy_private_patches_restore_after_nested_exception(self):
        manager_module = importlib.import_module("core.combat.multi_pc.manager")
        manager_module.reset_combat_state()
        outer_callback = lambda event, data: None
        inner_callback = lambda event, data: None
        try:
            with manager_module.temporary_combat_callback(outer_callback):
                with patch.object(manager_module, "_combat_callback", inner_callback):
                    self.assertIs(manager_module._combat_callback, inner_callback)
                    raise RuntimeError("patch restore test")
        except RuntimeError:
            pass
        self.assertIsNone(manager_module._combat_callback)

    def test_session_defaults_are_distinct_and_keep_encounter_contexts(self):
        session_module = importlib.import_module("core.combat.session")
        first = session_module.CombatSession(encounter={"id": "one"})
        second = session_module.CombatSession(encounter={"id": "two"})
        self.assertIsNot(first.history, second.history)
        first.history.append({"role": "user", "content": "one"})
        self.assertEqual(second.history, [])
        self.assertEqual(first.encounter["id"], "one")
        self.assertEqual(second.encounter["id"], "two")

    def test_semantic_payloads_update_fresh_and_resumed_histories_in_place(self):
        session_module = importlib.import_module("core.combat.session")
        payloads = {
            "head": "=== AUTHORITATIVE MULTI-PC STATE (JSON) ===\nnew-head",
            "monsters": "Monster Templates:\nnew-monsters",
            "location": "Location:\nnew-location",
        }

        fresh = session_module.CombatSession(
            encounter={},
            history=[
                {
                    "role": "system",
                    "content": "prompt example: Monster Templates: and Location: are described here",
                },
                {"role": "system", "content": "Current Combat Encounter: X"},
                {"role": "system", "content": ""},
                {"role": "system", "content": ""},
                {"role": "system", "content": ""},
            ],
        )
        fresh.apply_history_payloads(payloads)
        self.assertEqual([message["content"] for message in fresh.history], [
            "prompt example: Monster Templates: and Location: are described here",
            "Current Combat Encounter: X", payloads["head"],
            payloads["monsters"], payloads["location"],
        ])

        resumed = session_module.CombatSession(
            encounter={},
            history=[
                {
                    "role": "system",
                    "content": "prompt example: Monster Templates: and Location: are described here",
                },
                {"role": "system", "content": payloads["head"] + "\nold-head-body"},
                {"role": "system", "content": payloads["monsters"] + "\nold-monsters-body"},
                {"role": "system", "content": payloads["location"] + "\nold-location-body"},
            ],
        )
        resumed.apply_history_payloads(payloads)
        self.assertEqual(resumed.history[0]["content"], fresh.history[0]["content"])
        self.assertEqual([message["content"] for message in resumed.history[1:]], list(payloads.values()))

        resumed_history = [
            {"role": "system", "content": "prompt"},
            {"role": "system", "content": "Current Combat Encounter: X"},
            {"role": "system", "content": "Player Character:\nold-head"},
            {"role": "system", "content": "Monster Templates:\nold-monsters"},
            {"role": "system", "content": "Location:\nold-location"},
            {"role": "user", "content": "player message"},
        ]
        resumed = session_module.CombatSession(encounter={}, history=resumed_history)
        resumed.apply_history_payloads(payloads)
        self.assertEqual(resumed.history[0:2], resumed_history[0:2])
        self.assertEqual(resumed.history[2]["content"], payloads["head"])
        self.assertEqual(resumed.history[3]["content"], payloads["monsters"])
        self.assertEqual(resumed.history[4]["content"], payloads["location"])
        self.assertEqual(resumed.history[-1], {"role": "user", "content": "player message"})


class CombatStageBehaviorTests(unittest.TestCase):
    """Provider-free persisted behavior checks for the 3.1 stage owners."""

    def _command_io(self, *, files=None, writes=None, output=None):
        from core.combat.commands import DeterministicCommandIO

        files = files or {}
        writes = writes if writes is not None else []
        output = output if output is not None else []

        class Paths:
            def get_character_path(self, name):
                return f"characters/{name}.json"

        class Save:
            def create_save_game(self, label, kind):
                writes.append(("save", label, kind))
                return True, "saved"

        return DeterministicCommandIO(
            emit=output.append,
            flush=lambda: output.append("<flush>"),
            load_json=lambda path: files.get(path),
            save_json=lambda path, data: writes.append(("save_json", path, data)),
            write_json=lambda path, data: writes.append(("write_json", path, data)),
            path_manager=Paths(),
            normalize_name=lambda name: name.lower().replace(" ", "_"),
            sync_active_encounter=lambda **kwargs: writes.append(("sync", kwargs)),
            save_manager_factory=Save,
            summarize_dialogue=lambda history, location, party: "summary",
            generate_chat_history=lambda history, encounter: writes.append(("history", encounter)),
        )

    def test_invalid_and_init_pc_group_gate(self):
        from core.combat.turn import PhaseGateIO, handle_group_initiative_gate, run_input_phase_gate

        output = []
        writes = []
        party = {"active_character": "Acheron", "worldConditions": {}}
        manager = type("Manager", (), {"combat_phase": "PC_PHASE", "current_pc_name": "Acheron", "get_next_pending_death_save_pc": lambda self: None})()
        io = PhaseGateIO(output.append, lambda: output.append("<flush>"), lambda *a, **k: None, lambda p, d: writes.append((p, d)), lambda text, gate: (False, None, "bad roll"))
        result = run_input_phase_gate("/init 21", encounter_data={"awaitingPcGroupRoll": True, "initiativeRolls": {"dmGroup": 10}}, multi_pc_manager=manager, party_tracker_data=party, json_file_path="encounter.json", conversation_history=[], conversation_history_file="history.json", io=io, initiative_gate=lambda *args: handle_group_initiative_gate(*args, apply_opening_batch_marker=lambda data, winner: False, sync_available=False))
        self.assertEqual(result.control_action, "continue")
        self.assertIn("Roll must be between 1 and 20", output[0])

        result = run_input_phase_gate("/init 15", encounter_data={"awaitingPcGroupRoll": True, "initiativeRolls": {"dmGroup": 10}}, multi_pc_manager=manager, party_tracker_data=party, json_file_path="encounter.json", conversation_history=[], conversation_history_file="history.json", io=io, initiative_gate=lambda *args: handle_group_initiative_gate(*args, apply_opening_batch_marker=lambda data, winner: False, sync_available=False))
        self.assertEqual(result.control_action, "continue")
        self.assertEqual(writes[0][0], "encounter.json")

    def test_init_dm_tie_and_batch_handoff(self):
        from core.combat.turn import handle_group_initiative_gate, run_input_phase_gate, PhaseGateIO

        class Manager:
            combat_phase = "PC_PHASE"
            current_pc_name = "Acheron"
            pc_states = {"Merisiel": object()}
            pc_states = {"Merisiel": object()}
            pc_phase_complete = False
            def get_next_pending_death_save_pc(self): return None
            def get_remaining_enemies_for_round(self): return ["Goblin"]
        manager = Manager()
        history, output, writes = [], [], []
        io = PhaseGateIO(output.append, lambda: None, lambda *a, **k: None, lambda p, d: writes.append(p), lambda text, gate: (False, None, None))
        result = run_input_phase_gate("/init 10", encounter_data={"awaitingPcGroupRoll": True, "initiativeRolls": {"dmGroup": 10}}, multi_pc_manager=manager, party_tracker_data={"active_character": "Acheron", "worldConditions": {}}, json_file_path="encounter.json", conversation_history=history, conversation_history_file="history.json", io=io, initiative_gate=lambda *args: handle_group_initiative_gate(*args, apply_opening_batch_marker=lambda data, winner: True, sync_available=True))
        self.assertEqual(result.raw_input, "Enemies turn.")
        self.assertEqual(result.control_action, "proceed")
        self.assertIn("Goblin", history[-1]["content"])
        self.assertEqual(manager.pc_phase_complete, True)

    def test_initiative_gate_observations_follow_applied_state(self):
        from core.combat import turn

        class Manager:
            combat_phase = "PC_PHASE"
            current_pc_name = "Acheron"
            pc_phase_complete = False

            def get_next_pending_death_save_pc(self):
                return None

            def get_remaining_enemies_for_round(self):
                return ["Goblin"]

        def run(command, dm_roll):
            manager = Manager()
            encounter = {
                "awaitingPcGroupRoll": True,
                "initiativeRolls": {"dmGroup": dm_roll},
                "openingEnemyBatchPending": False,
            }
            party = {"active_character": "Acheron", "worldConditions": {}}
            observations, saves = [], []
            io = turn.PhaseGateIO(
                lambda _text: None, lambda: None, lambda *_args, **_kwargs: None,
                lambda path, data: saves.append((path, dict(data))),
                lambda *_args: (False, None, "invalid"),
            )

            def marker(data, winner):
                data["openingEnemyBatchPending"] = winner == "dmGroup"
                return data["openingEnemyBatchPending"]

            with patch.object(turn, "trace_enabled", return_value=True), patch.object(
                turn, "trace_combat_observation",
                side_effect=lambda name, **fields: observations.append(
                    (name, fields, dict(encounter))
                ),
            ):
                result = turn.run_input_phase_gate(
                    command, encounter_data=encounter, multi_pc_manager=manager,
                    party_tracker_data=party, json_file_path="encounter.json",
                    conversation_history=[], conversation_history_file="history.json",
                    io=io,
                    initiative_gate=lambda *args: turn.handle_group_initiative_gate(
                        *args, apply_opening_batch_marker=marker, sync_available=True
                    ),
                )
            return result, encounter, manager, observations, saves

        invalid_before = {
            "awaitingPcGroupRoll": True,
            "initiativeRolls": {"dmGroup": 8},
            "openingEnemyBatchPending": False,
        }
        invalid_result, invalid_state, _, invalid_events, invalid_saves = run("/init 21", 8)
        self.assertEqual(invalid_result.control_action, "continue")
        self.assertEqual(invalid_state, invalid_before)
        self.assertEqual(invalid_saves, [])
        self.assertEqual(invalid_events[0][1]["before"], invalid_events[0][1]["after"])
        self.assertFalse(invalid_events[0][1]["accepted"])

        _, pc_state, _, pc_events, pc_saves = run("/init 18", 8)
        pc_event = next(event for event in pc_events if event[1]["accepted"])
        self.assertEqual(pc_event[1]["expected_winner"], "pcGroup")
        self.assertEqual(pc_event[1]["after"], {
            "winner": "pcGroup", "awaiting": False,
            "opening_batch_pending": False, "round_starts_with": "pcGroup",
        })
        self.assertEqual(pc_event[1]["eligible_non_pc_cohort"], ["Goblin"])
        self.assertEqual(pc_event[2], pc_state)
        self.assertEqual([path for path, _ in pc_saves], ["encounter.json", "party_tracker.json"])

        dm_result, dm_state, dm_manager, dm_events, dm_saves = run("/init 8", 8)
        dm_event = next(event for event in dm_events if event[1]["accepted"])
        self.assertEqual(dm_result.control_action, "proceed")
        self.assertEqual(dm_event[1]["expected_winner"], "dmGroup")
        self.assertEqual(dm_event[1]["after"], {
            "winner": "dmGroup", "awaiting": False,
            "opening_batch_pending": True, "round_starts_with": "dmGroup",
        })
        self.assertEqual(dm_event[1]["eligible_non_pc_cohort"], ["Goblin"])
        self.assertEqual(dm_event[2], dm_state)
        self.assertEqual([path for path, _ in dm_saves], ["encounter.json", "party_tracker.json", "history.json"])
        self.assertTrue(turn.complete_opening_enemy_batch(
            dm_state, dm_manager, encounter_id="fixture",
            save_json=lambda path, data: dm_saves.append((path, dict(data))),
            debug=lambda *_args, **_kwargs: None,
        ))
        self.assertFalse(dm_state["openingEnemyBatchPending"])
        self.assertEqual(dm_saves[-1][0], "modules/encounters/encounter_fixture.json")

    def test_death_save_wrong_actor_and_valid_roll(self):
        from core.combat.turn import PhaseGateIO, run_input_phase_gate

        class Manager:
            combat_phase = "PC_PHASE"
            current_pc_name = "Acheron"
            pc_states = {"Merisiel": object()}
            def set_current_pc(self, name): self.current_pc_name = name
            def get_next_pending_death_save_pc(self): return "Merisiel"
            def validate_death_save_input_actor(self, actor, fallback_actor_name=None): return False, None, "Merisiel must roll"
            def resolve_death_save_roll(self, pc, roll): return True, "resolved"
        output = []
        io = PhaseGateIO(output.append, lambda: output.append("flush"), lambda *a, **k: None, lambda *a: None, lambda text, gate: (True, 12, None))
        result = run_input_phase_gate("[Acheron]: 12", encounter_data={}, multi_pc_manager=Manager(), party_tracker_data={"active_character": "Acheron"}, json_file_path="x", conversation_history=[], conversation_history_file="h", io=io, initiative_gate=lambda *args: {"handled": False, "error_message": ""})
        self.assertEqual(result.control_action, "continue")
        self.assertIn("Merisiel must roll", output[0])

        manager = Manager()
        manager.validate_death_save_input_actor = lambda actor, fallback_actor_name=None: (True, "Merisiel", "")
        result = run_input_phase_gate("[Merisiel]: 12", encounter_data={}, multi_pc_manager=manager, party_tracker_data={"active_character": "Acheron"}, json_file_path="x", conversation_history=[], conversation_history_file="h", io=io, initiative_gate=lambda *args: {"handled": False, "error_message": ""})
        self.assertEqual(result.control_action, "continue")
        self.assertIn("resolved", output)

    def test_stats_hp_save_and_quit_are_stage_owned(self):
        from core.combat.commands import run_deterministic_command_stage

        files = {"party_tracker.json": {"active_character": "Acheron", "partyMembers": ["Acheron"], "worldConditions": {}}, "characters/acheron.json": {"name": "Acheron", "hitPoints": 5, "maxHitPoints": 10, "abilities": {}}}
        output, writes = [], []
        io = self._command_io(files=files, writes=writes, output=output)
        result = run_deterministic_command_stage(cmd="/stats", current_round=2, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertEqual(result.control_action, "continue")
        self.assertIn("Stats for Acheron", output[0])
        run_deterministic_command_stage(cmd="/hp -2", current_round=2, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertEqual(files["characters/acheron.json"]["hitPoints"], 3)
        self.assertTrue(any(item[0] == "write_json" for item in writes))
        run_deterministic_command_stage(cmd="/save", current_round=2, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertIn(("save", "Combat Save - Round 2", "essential"), writes)
        result = run_deterministic_command_stage(cmd="/quit", current_round=2, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertEqual(result.control_action, "quit")
        self.assertEqual((result.status, result.reason, result.exit_code), ("exit_requested", "user_quit", 0))
        self.assertEqual(output[-2:], ["[SYSTEM] Exiting game...", "<flush>"])

    def test_legacy_run_boundary_maps_typed_exit_to_tuple_and_releases_claim(self):
        from core.combat import combat_manager
        from core.combat.commands import FastCommandResult

        result = FastCommandResult(
            control_action="quit", status="exit_requested", reason="user_quit", exit_code=0
        )
        with ExitStack() as guards:
            for target in (
                "builtins.open", "io.open", "os.open", "os.remove", "os.rename", "os.replace",
                "os.mkdir", "os.makedirs", "socket.socket", "socket.create_connection",
            ):
                guards.enter_context(patch(target, side_effect=_forbidden_side_effect))
            guards.enter_context(patch.object(
                combat_manager.client.chat.completions,
                "create",
                side_effect=_forbidden_side_effect,
            ))
            guards.enter_context(patch.object(combat_manager, "safe_json_load", return_value={"worldConditions": {}}))
            guards.enter_context(patch.object(combat_manager, "MULTI_PC_COMBAT_AVAILABLE", False))
            enter = guards.enter_context(patch.object(combat_manager, "_enter_combat_session"))
            release = guards.enter_context(patch.object(combat_manager, "_exit_combat_session"))
            guards.enter_context(patch.object(combat_manager, "run_combat_simulation_session", return_value=result))
            legacy_result = combat_manager.run_combat_simulation(
                "encounter-fixture", {"active_character": "Acheron"}, {}
            )
        self.assertEqual(legacy_result, (None, None))
        enter.assert_called_once_with("encounter-fixture")
        release.assert_called_once_with("encounter-fixture")

    def test_legacy_run_boundary_releases_claim_and_propagates_exceptions(self):
        from core.combat import combat_manager

        with ExitStack() as guards:
            for target in (
                "builtins.open", "io.open", "os.open", "os.remove", "os.rename", "os.replace",
                "os.mkdir", "os.makedirs", "socket.socket", "socket.create_connection",
            ):
                guards.enter_context(patch(target, side_effect=_forbidden_side_effect))
            guards.enter_context(patch.object(
                combat_manager.client.chat.completions,
                "create",
                side_effect=_forbidden_side_effect,
            ))
            guards.enter_context(patch.object(combat_manager, "safe_json_load", return_value={"worldConditions": {}}))
            guards.enter_context(patch.object(combat_manager, "MULTI_PC_COMBAT_AVAILABLE", False))
            guards.enter_context(patch.object(combat_manager, "_enter_combat_session"))
            release = guards.enter_context(patch.object(combat_manager, "_exit_combat_session"))
            guards.enter_context(patch.object(
                combat_manager,
                "run_combat_simulation_session",
                side_effect=RuntimeError("fixture"),
            ))
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                combat_manager.run_combat_simulation("encounter-fixture", {}, {})
        release.assert_called_once_with("encounter-fixture")

    def test_combat_library_contains_no_process_exit_calls_or_bare_handlers(self):
        import ast
        from pathlib import Path

        package = Path("core/combat")
        process_exits = []
        bare_handlers = []
        for source_path in package.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    bare_handlers.append((str(source_path), node.lineno))
                if isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name) and function.id in {"exit", "quit", "exit_process"}:
                        process_exits.append((str(source_path), node.lineno, function.id))
                    elif isinstance(function, ast.Attribute) and function.attr in {"exit", "_exit"}:
                        process_exits.append((str(source_path), node.lineno, ast.unparse(function)))
        self.assertEqual(process_exits, [])
        self.assertEqual(bare_handlers, [])

        owner_source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        owner_tree = ast.parse(owner_source)
        combat_owner = next(
            node for node in ast.walk(owner_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal"
        )
        turn_source = Path("core/combat/turn.py").read_text(encoding="utf-8")
        turn_tree = ast.parse(turn_source)
        normal_turn = next(
            node for node in ast.walk(turn_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_combat_normal_turn"
        )
        command_stage = next(
            node for node in ast.walk(normal_turn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "deterministic_command_stage"
        )
        exit_guards = [
            node for node in ast.walk(normal_turn)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and any(isinstance(value, ast.Constant) and value.value == "exit_requested"
                    for value in node.test.comparators)
            and any(isinstance(statement, ast.Return) for statement in node.body)
        ]
        provider_stages = [
            node for node in ast.walk(combat_owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_combat_provider_retry_stage"
        ]
        normal_turn_calls = [
            node for node in ast.walk(combat_owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "prepare_combat_normal_turn"
        ]
        self.assertEqual(len(exit_guards), 1)
        self.assertEqual(len(provider_stages), 1)
        self.assertEqual(len(normal_turn_calls), 1)
        self.assertLess(command_stage.lineno, exit_guards[0].lineno)
        self.assertLess(normal_turn_calls[0].lineno, provider_stages[0].lineno)

    def test_combat_loop_diagnostic_anchors_remain_stable(self):
        from pathlib import Path
        import ast

        owner_source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        turn_source = Path("core/combat/turn.py").read_text(encoding="utf-8")
        self.assertIn("DEBUG: [COMBAT_LOOP] Entering main while True combat loop", owner_source)
        for diagnostic in (
            "DEBUG: [COMBAT_LOOP] Top of while loop - syncing character data",
            "DEBUG: [COMBAT_LOOP] About to request player input",
            "DEBUG: [COMBAT_LOOP] EOF encountered, breaking loop",
        ):
            self.assertIn(diagnostic, turn_source)

        tree = ast.parse(turn_source)
        owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "begin_combat_turn_iteration"
        )
        eof_handlers = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "EOFError"
        ]
        self.assertEqual(len(eof_handlers), 1)
        eof_result = any(
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "CombatTurnIterationResult"
            and any(
                keyword.arg == "return_value"
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id == "FastCommandResult"
                for keyword in statement.value.keywords
            )
            for handler in eof_handlers for statement in handler.body
        )
        self.assertTrue(eof_result)

    def test_end_combat_and_hp_feedback_order(self):
        from core.combat.commands import run_deterministic_command_stage

        files = {"party_tracker.json": {"active_character": "Acheron", "partyMembers": ["Acheron"], "worldConditions": {"activeCombatEncounter": "E"}}, "characters/acheron.json": {"name": "Acheron", "hitPoints": 5, "maxHitPoints": 10, "abilities": {}}}
        output, writes = [], []
        io = self._command_io(files=files, writes=writes, output=output)
        run_deterministic_command_stage(cmd="/hp 2", current_round=1, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertLess(next(i for i, value in enumerate(output) if "Acheron healed" in value), output.index("<flush>"))
        result = run_deterministic_command_stage(cmd="/end_combat", current_round=1, encounter_id="E", encounter_data={}, party_tracker_data=files["party_tracker.json"], conversation_history=[], location_info={}, player_file="characters/acheron.json", io=io)
        self.assertEqual(result.control_action, "return")
        self.assertEqual(result.return_value, ("summary", files["characters/acheron.json"]))
        self.assertEqual(files["party_tracker.json"]["worldConditions"]["activeCombatEncounter"], "")

    def test_attack_damage_feedback_precedes_persist_and_skips_provider(self):
        from core.combat.commands import FastCommandIO, run_fast_commands_stage

        events = []
        class Manager:
            current_pc_name = "Acheron"
            def handle_combat_command(self, clean_input, encounter_data, actor_name=None, **kwargs):
                return "feedback", "narration", "log", True
        io = FastCommandIO(
            emit=lambda value: events.append(("emit", value)),
            flush=lambda: events.append(("flush",)),
            debug=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            save_json=lambda *args: events.append(("save",)),
            persist_encounter=lambda *args: events.append(("persist",)) or True,
        )
        result = run_fast_commands_stage(cmd="/att Goblin 18", clean_input="/att Goblin 18", user_input_text="/att Goblin 18", input_actor_name=None, multi_pc_manager=Manager(), encounter_data={}, encounter_id="E", party_tracker_data={"active_character": "Acheron"}, conversation_history=[], conversation_history_file="history.json", io=io)
        self.assertEqual(result.control_action, "continue")
        self.assertEqual([event[0] for event in events[:4]], ["emit", "flush", "emit", "flush"])
        self.assertNotIn("persist", [event[0] for event in events])

    def test_end_phase_command_keeps_phase_transition_and_history_write(self):
        from core.combat.commands import FastCommandIO, run_fast_commands_stage

        events, history = [], []
        class Manager:
            current_pc_name = "Acheron"
            def force_end_pc_phase(self): events.append("force")
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def handle_combat_command(self, clean_input, encounter_data, actor_name=None, **kwargs): return None, None, None, True
            def set_current_pc(self, name): events.append(("active", name))
        io = FastCommandIO(output := (lambda value: events.append(("emit", value))), lambda: None, lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: events.append("save"), lambda *a, **k: True)
        result = run_fast_commands_stage(cmd="/end", clean_input="/end", user_input_text="/end", input_actor_name="Acheron", multi_pc_manager=Manager(), encounter_data={}, encounter_id="E", party_tracker_data={"active_character": "Acheron"}, conversation_history=history, conversation_history_file="history.json", io=io)
        self.assertEqual(result.user_input_text, "Enemies turn.")
        self.assertIn("force", events)
        self.assertIn("Turn Order: Goblin.", history[-1]["content"])


if __name__ == "__main__":
    unittest.main()
