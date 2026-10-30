# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - updateEncounter ops runtime tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Runtime coverage for Workstream I Step 3.2 deterministic encounter ops.
"""

import json
import builtins
import io
import os
import pathlib
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()
PRIVATE_READ_DENIALS = []


class _PrivateRootReadDenied(BaseException):
    pass


def _is_private_root_read(path):
    try:
        candidate = pathlib.Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = pathlib.Path.cwd() / candidate
        return candidate.parent.resolve() == pathlib.Path(REPO_ROOT).resolve() and candidate.name in {
            "config.py", "party_tracker.json",
        }
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
MISSING_JSONSCHEMA = False
update_encounter = None
_IMPORT_FIXTURE = None
_IMPORT_CWD = None
_ORIGINAL_CWD = None
_FACTORY_PATCHER = None
_FACTORY_MOCK = None


def setUpModule():
    """Import the actual updater while denying provider-client construction."""
    global MISSING_JSONSCHEMA, update_encounter, _IMPORT_FIXTURE, _IMPORT_CWD
    global _ORIGINAL_CWD, _FACTORY_PATCHER, _FACTORY_MOCK
    import importlib
    from contextlib import ExitStack

    try:
        import model_config
        from utils import ai_client_factory
        fixture = types.ModuleType("config")
        for name in dir(model_config):
            if name.isupper() and not name.startswith("_"):
                setattr(fixture, name, getattr(model_config, name))
        fixture.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_UPDATE_ENCOUNTER_TEST"
        fixture.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_UPDATE_ENCOUNTER_TEST"
        _IMPORT_FIXTURE = ExitStack()
        _IMPORT_FIXTURE.enter_context(patch.dict(sys.modules, {"config": fixture}))
        _FACTORY_PATCHER = patch.object(
            ai_client_factory,
            "create_chat_client",
            side_effect=AssertionError("update_encounter constructed a provider client"),
        )
        _FACTORY_MOCK = _FACTORY_PATCHER.start()
        _IMPORT_FIXTURE.callback(_FACTORY_PATCHER.stop)
        tmp_root = pathlib.Path(REPO_ROOT, "tmp")
        tmp_root.mkdir(exist_ok=True)
        _ORIGINAL_CWD = pathlib.Path.cwd()
        _IMPORT_CWD = pathlib.Path(tempfile.mkdtemp(prefix="update-encounter-import-", dir=tmp_root))
        os.chdir(_IMPORT_CWD)
        try:
            update_encounter = importlib.import_module("updates.update_encounter").update_encounter
        finally:
            os.chdir(_ORIGINAL_CWD)
        _FACTORY_MOCK.assert_not_called()
    except ModuleNotFoundError as import_error:
        if getattr(import_error, "name", "") == "jsonschema":
            MISSING_JSONSCHEMA = True
        else:
            raise


def tearDownModule():
    if _IMPORT_FIXTURE is not None:
        _IMPORT_FIXTURE.close()
    for patcher in reversed(PRIVATE_READ_PATCHES):
        patcher.stop()
    if _IMPORT_CWD is not None:
        import shutil
        shutil.rmtree(_IMPORT_CWD, ignore_errors=True)


class FixtureWriteDenied(BaseException):
    """Fatal sentinel for attempts to mutate files outside this test's fixture."""


@contextmanager
def _guarded_runtime_io(fixture_root, test_case):
    """Allow runtime mutations only inside the unique encounter fixture root."""
    from scripts.test_llm_router import ProviderTripwire

    root = pathlib.Path(fixture_root).resolve()
    real_open = open
    real_os_open = os.open
    real_mutators = {
        name: getattr(os, name)
        for name in ("remove", "unlink", "rename", "replace", "mkdir", "makedirs", "rmdir")
        if hasattr(os, name)
    }

    def is_owned(path):
        return pathlib.Path(os.fspath(path)).resolve().is_relative_to(root)

    def resolve_fixture_or_schema_path(path):
        candidate = pathlib.Path(os.fspath(path))
        if not candidate.is_absolute() and candidate.parts and candidate.parts[0] == "schemas":
            return pathlib.Path(REPO_ROOT, candidate)
        return candidate

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")) and not is_owned(file):
            raise FixtureWriteDenied(f"write outside owned fixture denied: {file}")
        return real_open(resolve_fixture_or_schema_path(file), mode, *args, **kwargs)

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def guarded_os_open(file, flags, *args, **kwargs):
        if flags & write_flags and not is_owned(file):
            raise FixtureWriteDenied(f"os.open write outside owned fixture denied: {file}")
        return real_os_open(resolve_fixture_or_schema_path(file), flags, *args, **kwargs)

    def guarded_mutator(original):
        def call(path, *args, **kwargs):
            if not is_owned(path):
                raise FixtureWriteDenied(f"mutation outside owned fixture denied: {path}")
            return original(path, *args, **kwargs)
        return call

    with ExitStack() as stack:
        tripwire = stack.enter_context(ProviderTripwire())
        stack.enter_context(patch("builtins.open", side_effect=guarded_open))
        stack.enter_context(patch("io.open", side_effect=guarded_open))
        stack.enter_context(patch("os.open", side_effect=guarded_os_open))
        for name, original in real_mutators.items():
            stack.enter_context(patch.object(os, name, side_effect=guarded_mutator(original)))
        stack.enter_context(patch.object(pathlib.Path, "write_text", side_effect=FixtureWriteDenied))
        stack.enter_context(patch.object(pathlib.Path, "write_bytes", side_effect=FixtureWriteDenied))
        stack.enter_context(patch.object(pathlib.Path, "unlink", side_effect=guarded_mutator(pathlib.Path.unlink)))
        stack.enter_context(patch.object(pathlib.Path, "rename", side_effect=guarded_mutator(pathlib.Path.rename)))
        stack.enter_context(patch.object(pathlib.Path, "replace", side_effect=guarded_mutator(pathlib.Path.replace)))
        yield
        tripwire.assert_untouched(test_case)


@unittest.skipIf(MISSING_JSONSCHEMA, "jsonschema dependency unavailable")
class TestUpdateEncounterOpsRuntime(unittest.TestCase):
    """Covers narrow deterministic enemy encounter ops runtime path."""

    def setUp(self):
        self.encounter_id = "UNITTEST_ENCOUNTER_OPS"
        self.original_cwd = os.getcwd()
        self._scratch = tempfile.TemporaryDirectory(
            prefix="update_encounter_ops_",
            dir=os.path.join(REPO_ROOT, "tmp"),
        )
        self.scratch_root = pathlib.Path(self._scratch.name).resolve()
        self.assertTrue(self.scratch_root.is_relative_to(pathlib.Path(REPO_ROOT, "tmp").resolve()))
        self.addCleanup(self._cleanup_scratch)
        os.chdir(self.scratch_root)
        os.makedirs("modules/encounters", exist_ok=True)
        with open("party_tracker.json", "w", encoding="utf-8") as file_handle:
            json.dump({"module": "update_encounter_ops_fixture"}, file_handle)
        self.encounter_path = os.path.join(
            "modules",
            "encounters",
            f"encounter_{self.encounter_id}.json",
        )
        self._write_fixture()

    def _cleanup_scratch(self):
        if pathlib.Path.cwd().resolve().is_relative_to(self.scratch_root):
            os.chdir(self.original_cwd)
        self._scratch.cleanup()

    def _write_fixture(self):
        fixture = {
            "encounterId": self.encounter_id,
            "encounterSummary": "Unit test encounter",
            "creatures": [
                {
                    "name": "Goblin-1",
                    "type": "enemy",
                    "monsterType": "goblin",
                    "initiative": 12,
                    "status": "alive",
                    "conditions": [],
                    "actions": {"actionType": "attack", "target": "pc"},
                    "currentHitPoints": 15,
                    "maxHitPoints": 15,
                }
            ],
        }
        with open(self.encounter_path, "w", encoding="utf-8") as file_handle:
            json.dump(fixture, file_handle, indent=2)

    def _read_encounter(self):
        with open(self.encounter_path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def test_supported_enemy_ops_apply_deterministically(self):
        with _guarded_runtime_io(self.scratch_root, self):
            result = update_encounter(
                self.encounter_id,
                None,
                ops=[
                    {"op": "hp_delta", "creature": "Goblin-1", "delta": -7},
                    {"op": "condition_add", "creature": "Goblin-1", "condition": "Prone"},
                    {"op": "set_status", "creature": "Goblin-1", "status": "defeated"},
                ],
            )

        self.assertIsNotNone(result)
        goblin = result["creatures"][0]
        self.assertEqual(goblin["currentHitPoints"], 8)
        self.assertEqual(goblin["status"], "defeated")
        self.assertIn("Prone", goblin["conditions"])

        persisted = self._read_encounter()
        persisted_goblin = persisted["creatures"][0]
        self.assertEqual(persisted_goblin["currentHitPoints"], 8)
        self.assertEqual(persisted_goblin["status"], "defeated")
        self.assertIn("Prone", persisted_goblin["conditions"])

    def test_unsupported_ops_fail_open_to_noop_without_changes(self):
        baseline = self._read_encounter()
        with _guarded_runtime_io(self.scratch_root, self):
            result = update_encounter(
                self.encounter_id,
                None,
                ops=[{"op": "initiative_set", "creature": "Goblin-1", "initiative": 20}],
            )

        self.assertEqual(result, baseline)
        self.assertEqual(self._read_encounter(), baseline)

    def test_overkill_enemy_hp_is_clamped_and_status_is_non_living(self):
        with _guarded_runtime_io(self.scratch_root, self):
            result = update_encounter(
                self.encounter_id,
                None,
                ops=[{"op": "hp_delta", "creature": "Goblin-1", "delta": -30}],
            )

        self.assertIsNotNone(result)
        goblin = result["creatures"][0]
        self.assertEqual(goblin["currentHitPoints"], 0)
        self.assertEqual(goblin["status"], "dead")

        persisted_goblin = self._read_encounter()["creatures"][0]
        self.assertEqual(persisted_goblin["currentHitPoints"], 0)
        self.assertEqual(persisted_goblin["status"], "dead")

    def test_previously_defeated_enemy_cannot_be_revived_by_later_ops(self):
        fixture = self._read_encounter()
        fixture["creatures"][0]["currentHitPoints"] = 0
        fixture["creatures"][0]["status"] = "dead"
        with open(self.encounter_path, "w", encoding="utf-8") as file_handle:
            json.dump(fixture, file_handle, indent=2)

        with _guarded_runtime_io(self.scratch_root, self):
            result = update_encounter(
                self.encounter_id,
                None,
                ops=[
                    {"op": "set_hp", "creature": "Goblin-1", "hp": 5},
                    {"op": "set_status", "creature": "Goblin-1", "status": "alive"},
                ],
            )

        self.assertIsNotNone(result)
        goblin = result["creatures"][0]
        self.assertEqual(goblin["currentHitPoints"], 0)
        self.assertEqual(goblin["status"], "dead")

        persisted_goblin = self._read_encounter()["creatures"][0]
        self.assertEqual(persisted_goblin["currentHitPoints"], 0)
        self.assertEqual(persisted_goblin["status"], "dead")

    def test_import_safety_guards_are_armed_and_private_reads_are_denied(self):
        for protected in ("config.py", "party_tracker.json"):
            target = os.path.join(REPO_ROOT, protected)
            for operation, attempt in (
                ("builtins.open", lambda: builtins.open(target, "r", encoding="utf-8")),
                ("io.open", lambda: io.open(target, "r", encoding="utf-8")),
                ("os.open", lambda: os.open(target, os.O_RDONLY)),
            ):
                with self.subTest(path=protected, operation=operation), self.assertRaises(_PrivateRootReadDenied):
                    attempt()
        self.assertEqual(PRIVATE_READ_DENIALS[-6:], ["builtins.open", "io.open", "os.open"] * 2)
        _FACTORY_MOCK.assert_not_called()
        self.assertFalse(hasattr(sys.modules["updates.update_encounter"], "client"))
        PROCESS_TRIPWIRES.assert_untouched(self)
        for name in ("openai.OpenAI", "socket.socket", "urlopen"):
            guard = PROCESS_TRIPWIRES.calls[name]
            with self.subTest(guard=name), self.assertRaises(TripwireFailure):
                guard()
            guard.reset_mock()
        PROCESS_TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main(verbosity=2)
