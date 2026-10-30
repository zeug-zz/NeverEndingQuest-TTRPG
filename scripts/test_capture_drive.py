# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the bounded Capture_Arena scenario profiles."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# This must precede every runtime-owner import in this process. The shared
# guard protects mkdir/rmtree/rename/copy operations as well as file writes.
from scripts.core_chat_test_safety import (
    TripwireFailure,
    _ProcessTripwires,
    arm_process_tripwires,
)

_PROCESS_TRIPWIRES = arm_process_tripwires()

import ast
import builtins
import contextlib
import copy
import hashlib
import http.client
import importlib
import io
import json
import os
import pathlib
import re
import socket
import sys
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
import uuid
from contextlib import ExitStack
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch


class ForbiddenSideEffect(BaseException):
    """Fatal guard for an accidental network, SDK, or outside write attempt."""


def _forbidden(*args, **kwargs):
    raise ForbiddenSideEffect("unexpected network or filesystem side effect")


def _guard_write_open(path, mode="r", *args, **kwargs):
    if any(flag in mode for flag in "wax+"):
        resolved = pathlib.Path(path).resolve()
        allowed = (ROOT / "tmp").resolve()
        if resolved != allowed and allowed not in resolved.parents:
            raise ForbiddenSideEffect("write outside repository tmp/: %s" % path)
    return _REAL_OPEN(path, mode, *args, **kwargs)


def _guard_os_open(path, flags, *args, **kwargs):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if flags & write_flags:
        resolved = pathlib.Path(os.fspath(path)).resolve()
        allowed = (ROOT / "tmp").resolve()
        if resolved != allowed and allowed not in resolved.parents:
            raise ForbiddenSideEffect("os.open write outside repository tmp/: %s" % path)
    return _REAL_OS_OPEN(path, flags, *args, **kwargs)


IMPORT_GUARD_COUNTS = {"sdk_constructor": 0, "network": 0}


def _sdk_constructor_tripwire(*args, **kwargs):
    IMPORT_GUARD_COUNTS["sdk_constructor"] += 1
    raise ForbiddenSideEffect("SDK client constructor attempted")


def _network_tripwire(*args, **kwargs):
    IMPORT_GUARD_COUNTS["network"] += 1
    raise ForbiddenSideEffect("network operation attempted")


def _load_source_functions(source_path, names, namespace):
    """Execute actual selected functions plus their literal helper closure, never module scope."""
    source_path = pathlib.Path(source_path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = {node.name: node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments[target.id] = node

    pending, selected = list(names), set()
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        node = functions.get(name) or assignments.get(name)
        if node is None:
            continue
        for child in ast.walk(node):
            if (isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and
                    (child.id in functions or child.id in assignments)):
                pending.append(child.id)

    nodes = [node for name in selected for node in (functions.get(name) or assignments.get(name),)
             if node is not None]
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if any(isinstance(child, ast.Call) for child in ast.walk(value)):
                raise AssertionError("refusing to execute non-literal module assignment: %s" % source_path)
    nodes.sort(key=lambda node: node.lineno)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


_REAL_OPEN = builtins.open
_REAL_OS_OPEN = os.open
_fake_socketio = ModuleType("socketio")
_fake_socketio.Client = _network_tripwire
_fake_requests = ModuleType("requests")
_fake_requests.post = _network_tripwire
_fake_requests.get = _network_tripwire
_fake_openai = ModuleType("openai")
_fake_openai.OpenAI = _sdk_constructor_tripwire
_fake_logger = ModuleType("utils.enhanced_logger")
for _logger_name in ("debug", "info", "warning", "error", "game_event", "set_script_name"):
    setattr(_fake_logger, _logger_name, lambda *args, **kwargs: None)
sys.modules["utils.enhanced_logger"] = _fake_logger

_fake_config = ModuleType("config")
_fake_config.OPENAI_API_KEY = ""
_fake_config.OPENROUTER_API_KEY = ""
_fake_config.MULTIPLAYER_MODE = True
_fake_config.TABLETOP_DEBUG_VERBOSE = False
_fake_config.__path__ = []


def _unexpected_config_read(name):
    raise ForbiddenSideEffect("unexpected config attribute read: %s" % name)


_fake_config.__getattr__ = _unexpected_config_read
sys.modules["config"] = _fake_config

_test_pure_globals = {
    "copy": copy,
    "glob": __import__("glob"),
    "os": os,
    "re": __import__("re"),
    "Dict": Dict,
    "Any": Any,
    "List": List,
    "Tuple": Tuple,
    "Optional": Optional,
}
_update_helper_path = ROOT / "updates" / "update_character_info.py"
_update_helpers = _load_source_functions(
    _update_helper_path,
    ("_apply_character_ops_deterministic", "find_character_file_fuzzy"),
    dict(_test_pure_globals),
)
_fake_update_module = ModuleType("updates.update_character_info")
_fake_update_module.__path__ = []
_fake_update_module._apply_character_ops_deterministic = _update_helpers["_apply_character_ops_deterministic"]
_fake_update_module.find_character_file_fuzzy = _update_helpers["find_character_file_fuzzy"]
_fake_update_module.normalize_character_name = _update_helpers["normalize_character_name"]


def _unexpected_update_import(name):
    raise ForbiddenSideEffect("unexpected update_character_info import attribute: %s" % name)


_fake_update_module.__getattr__ = _unexpected_update_import
sys.modules["updates.update_character_info"] = _fake_update_module

# Tripwires are armed before importing the fixture helpers or driver. Fake
# transport/SDK modules avoid import-time socket probes and real constructors.
with patch.dict(sys.modules, {
    "socketio": _fake_socketio, "requests": _fake_requests, "openai": _fake_openai,
    "utils.enhanced_logger": _fake_logger,
}), \
     patch("socket.socket", side_effect=_network_tripwire), \
     patch("socket.create_connection", side_effect=_network_tripwire), \
     patch("urllib.request.urlopen", side_effect=_network_tripwire), \
     patch("http.client.HTTPConnection.connect", side_effect=_network_tripwire), \
     patch("builtins.open", side_effect=_guard_write_open), \
     patch("io.open", side_effect=_guard_write_open), \
     patch("os.open", side_effect=_guard_os_open):
    import scripts.combat_latency_fixtures as fixtures
    from scripts import capture_drive
    from scripts import capture_evidence
    from scripts import seed_combat_capture
    from scripts import combat_latency_report
    from utils import combat_latency_trace
    import model_config
    import jsonschema
    from core.combat.multi_pc.manager import (
        Combatant,
        CombatantType,
        MultiPCCombatManager,
    )
    from core.combat.multi_pc.state import PCCombatState, PCStatus
    from core.generators.generate_prerolls import get_npc_attacks
    from core.ai.build_npc_context import extract_npcs_from_area
    from utils.runtime_hydration import hydrate_missing_live_area_files_from_bu
    from utils.character_state_hygiene import get_supernatural_state_summary
    _combat_projection_namespace = _load_source_functions(
        ROOT / "core" / "combat" / "combat_manager.py",
        ("filter_encounter_for_system_prompt", "format_npc_for_combat"),
        {"debug": lambda *_args, **_kwargs: None,
         "get_supernatural_state_summary": get_supernatural_state_summary},
    )
    filter_encounter_for_system_prompt = _combat_projection_namespace["filter_encounter_for_system_prompt"]
    format_npc_for_combat = _combat_projection_namespace["format_npc_for_combat"]
    _apply_character_ops_deterministic = _update_helpers["_apply_character_ops_deterministic"]

if any(IMPORT_GUARD_COUNTS.values()):
    raise AssertionError("import-time side-effect tripwire fired: %s" % IMPORT_GUARD_COUNTS)

# Verbatim event-shape excerpt from the G5T gate capture that exposed status-before-output.
G5T_STATUS_BEFORE_OUTPUT_TRANSCRIPT = (
    "[status_update] is_processing=False message=\n"
    "[status_update] is_processing=False message=Enter your command:\n"
    "[status_update] is_processing=False message=Ready for input\n"
    "[game_output] type=narration content=Hobgoblin Captain catches Acheron cleanly with the Longsword, "
    "forcing it to stagger (Rolled 23 vs AC 14; d20 19). It deals 5 slashing damage. Acheron has 226/231 HP.\n"
)
G5T_R1_TURN_END_TRACE_LINE = (
    '{"schema_version":1,"event_type":"stage","mode":"mp","phase":"ENEMY_PHASE",'
    '"batch_id":"enemy:r1","combat_round":1,"stage":"turn_end",'
    '"elapsed_ms":7350.522416876629,"run_id":"g5t-gate-p1-r2-1792851094000",'
    '"recorded_at_ms":1792851113885}'
)

capture_drive.POLL_INTERVAL_SECONDS = 0.001


class FixedGatePreparationTests(unittest.TestCase):
    """Provider-free fixed gate and sandbox-only narrator preparation contracts."""

    def test_tooling_imports_and_help_are_clean_in_fresh_guarded_process(self):
        code = r'''
import builtins, io, logging.handlers, os, pathlib, runpy, sys
from types import ModuleType
from scripts.core_chat_test_safety import arm_process_tripwires, TripwireFailure
guards = arm_process_tripwires()
root = pathlib.Path.cwd().resolve()
private_config = (root / "config.py").resolve()
root_log_attempts = []
def deny_root_log(*_args, **_kwargs):
    root_log_attempts.append(1)
    raise TripwireFailure("production root logger initialization denied")
logging.handlers.RotatingFileHandler = deny_root_log
real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
def deny_private_config(operation):
    def guarded(path, *args, **kwargs):
        try:
            if pathlib.Path(path).resolve() == private_config:
                raise TripwireFailure("private config.py read denied")
        except (TypeError, OSError, ValueError):
            pass
        return operation(path, *args, **kwargs)
    return guarded
builtins.open = deny_private_config(real_open)
io.open = deny_private_config(real_io_open)
os.open = deny_private_config(real_os_open)
if hasattr(io, "open_code"):
    io.open_code = deny_private_config(io.open_code)
config = ModuleType("config")
config.OPENAI_API_KEY = "UNIT_TEST_NONEMPTY_OPENAI_KEY_SENTINEL"
config.OPENROUTER_API_KEY = "UNIT_TEST_NONEMPTY_ROUTER_KEY_SENTINEL"
config.LLM_PROVIDER = "openai"
config.ACTIVE_PROFILE = "auto"
config.PLAYER_INFO_UPDATE_MODEL = "unit-test-player-model"
config.NPC_INFO_UPDATE_MODEL = "unit-test-npc-model"
config.MULTIPLAYER_MODE = sys.argv[2] == "1"
config.TABLETOP_DEBUG_VERBOSE = sys.argv[3] == "1"
config.__path__ = []
config.__getattr__ = lambda name: (_ for _ in ()).throw(TripwireFailure("unexpected config read: " + name))
sys.modules["config"] = config
case = sys.argv[1]
if case == "builders":
    import scripts.seed_combat_capture as seeder
    import combat_latency_fixtures as top_level_fixtures
    import scripts.combat_latency_fixtures as package_fixtures
    import scripts.capture_evidence as evidence
    assert top_level_fixtures is not package_fixtures
    assert len(evidence.REQUIRED_KEYS) == 18
    for fixtures in (top_level_fixtures, package_fixtures):
        for party in (1, 4):
            narrator = fixtures.build_gate_profile("g4", "narrator-dialogue-travel", party)
            assert len(narrator["turns"]) == 5
            assert narrator["max_requests"] == (8 if party == 1 else 9)
            combat = fixtures.build_gate_profile("g4", "combat-smoke", party)
            names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            encounter, encounter_id = seeder._build_encounter(names, party, combat)
            assert encounter_id == ("capture_one_pc" if party == 1 else "capture_mp")
            writes = {}
            actual_seed_id = seeder._seed_party(
                {"module": "Capture_Arena", "area_id": "CTR001",
                 "area_name": "Capture Arena", "start_location_id": "CA01",
                 "start_location_name": "Waystone Gate"}, names, party, combat,
                writer=lambda path, payload: writes.setdefault(path, payload),
            )
            assert actual_seed_id == encounter_id
            assert writes["party_tracker.json"]["partyMembers"] == names
            assert [row["name"] for row in writes[
                "modules/encounters/encounter_%s.json" % encounter_id]["creatures"]
                if row["type"] == "enemy"] == (["Goblin"] if party == 1 else ["Goblin Alpha", "Goblin Beta"])
elif case in ("seed-help", "driver-help", "evidence-help"):
    script = {"seed-help": "scripts/seed_combat_capture.py",
              "driver-help": "scripts/capture_drive.py",
              "evidence-help": "scripts/capture_evidence.py"}[case]
    sys.argv = [script, "--help"]
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("actual __main__ --help did not exit")
else:
    raise AssertionError("unknown guarded import case")
for name in ("updates.update_character_info", "utils.update_character_info",
             "utils.multi_pc_dm_note", "utils.enhanced_logger",
             "core.ai.build_npc_context", "core.generators.generate_prerolls",
             "utils.npc_reconciler", "core.managers.multi_pc_combat",
             "core.ai.combat_compressor", "core.ai.combat_compression_engine"):
    assert name not in sys.modules, "runtime owner imported: " + name
assert not root_log_attempts
guards.assert_untouched(__import__("unittest").TestCase())
print("IMPORT_GUARDS_CLEAR")
'''
        env = {**os.environ, "OPENSPEC_TELEMETRY": "0", "DO_NOT_TRACK": "1",
               "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPYCACHEPREFIX": "tmp/g4-importfix-pycache", "TMPDIR": "tmp"}
        cases = [("seed-help", 1, 0), ("driver-help", 1, 0),
                 ("evidence-help", 1, 0)] + [
                     ("builders", multiplayer, verbose)
                     for multiplayer in (0, 1) for verbose in (0, 1)
                 ]
        for case, multiplayer, verbose in cases:
            with self.subTest(case=case, multiplayer=multiplayer, verbose=verbose):
                result = subprocess.run(
                    [sys.executable, "-c", code, case, str(multiplayer), str(verbose)],
                    cwd=str(ROOT), capture_output=True, text=True, env=env,
                )
                self.assertEqual(result.returncode, 0,
                                 "fresh guarded import case failed: %s (%s)" %
                                 (case, result.stderr.splitlines()[-1][:160]
                                  if result.stderr.splitlines() else "no diagnostic"))
                self.assertTrue(result.stdout.rstrip().endswith("IMPORT_GUARDS_CLEAR"), case)
                self.assertNotIn("Creating OpenAI client", result.stdout, case)

    def test_process_tripwires_remained_untouched(self):
        _PROCESS_TRIPWIRES.assert_untouched(self)

    def test_tripwire_failure_diagnostics_redact_call_arguments(self):
        sentinel = "SYNTHETIC_CREDENTIAL_SENTINEL_MUST_NOT_PRINT"
        synthetic_guard = unittest.mock.Mock(
            side_effect=TripwireFailure("synthetic test tripwire")
        )
        with self.assertRaises(TripwireFailure):
            synthetic_guard(api_key=sentinel)

        isolated_tripwires = _ProcessTripwires()
        isolated_tripwires.calls = {"synthetic.sdk_constructor": synthetic_guard}
        with self.assertRaises(AssertionError) as failure:
            isolated_tripwires.assert_untouched(self)
        diagnostic = str(failure.exception)
        self.assertIn("synthetic.sdk_constructor", diagnostic)
        self.assertIn("1 call(s)", diagnostic)
        self.assertNotIn(sentinel, diagnostic)

    def test_actual_main_narrator_path_injects_authored_current_location_npcs(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        main_function_start = main_source.index("def main_game_loop():")
        main_loop_source = main_source[main_function_start:]
        history_refresh = main_loop_source.index("conversation_history = update_conversation_history(")
        narrator_request = main_loop_source.index("ai_response_content = get_ai_response(")
        self.assertLess(history_refresh, narrator_request)

        conversation_source = (ROOT / "core" / "ai" / "conversation_utils.py").read_text(
            encoding="utf-8"
        )
        conversation_tree = ast.parse(conversation_source)
        history_function = next(node for node in conversation_tree.body
                                if isinstance(node, ast.FunctionDef) and
                                node.name == "update_conversation_history")
        history_body = ast.get_source_segment(conversation_source, history_function)
        self.assertIn('path_manager.get_area_path(current_area_id)', history_body)
        self.assertIn('location["locationId"] == current_location_id', history_body)
        self.assertIn('location_for_conversation = {k: v for k, v in current_location.items() if k != \'adventureSummary\'}',
                      history_body)
        self.assertIn('"content": f"Current Location:\\n{compress_json_data(location_for_conversation)}\\n"',
                      history_body)

        # The authored area record itself supplies Mira's scene identity and
        # description; the current-location system message carries that entire
        # record. No persisted NPC character file is part of this path.
        area_path = ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001.json"
        authored_area = json.loads(area_path.read_text(encoding="utf-8"))
        mira = next(npc for room in authored_area["locations"] if room["locationId"] == "CA03"
                    for npc in room.get("npcs", []) if npc.get("name") == "Warden Mira")
        self.assertIn("description", mira)
        self.assertEqual(extract_npcs_from_area(authored_area)["CA03"], {"Warden Mira"})
        narrator_profile = fixtures.build_gate_profile("g4", "narrator-dialogue-travel", 1)
        self.assertNotIn("npc_characters", narrator_profile)

    def test_fixed_gate_profiles_and_invalid_combinations_are_bounded(self):
        self.assertEqual(capture_drive.build_parser().parse_args(["--party", "1"]).gate, "g3")
        for party, controls in ((1, 8), (4, 9)):
            profile = fixtures.build_gate_profile("g4", "narrator-dialogue-travel", party)
            self.assertEqual((profile["max_inputs"], profile["max_controls"]), (6, controls))
            self.assertEqual(profile["turn_timeout_seconds"], 300)
            self.assertEqual(profile["max_health_reads"], 3)
            self.assertEqual([turn["expected_location_id"] for turn in profile["turns"]],
                             ["CA02", "CA03", "CA03", "CA02", "CA01"])
            expected_actors = (["Acheron"] * 5 if party == 1 else
                               ["Acheron", "Acheron", "Merisiel", "Merisiel", "Merisiel"])
            self.assertEqual([turn["character"] for turn in profile["turns"]], expected_actors)
            self.assertEqual([turn["kind"] for turn in profile["turns"]].count("mira_dialogue"), 1)
        for party, steps, controls, identity in (
                (1, 5, 7, "P1 Goblin"), (4, 22, 35, "P4 Goblin Alpha+Beta")):
            profile = fixtures.build_gate_profile("g4", "combat-smoke", party)
            self.assertEqual((profile["max_inputs"], profile["max_controls"]), (steps, controls))
            self.assertEqual(profile["seed_identity"], identity)
            self.assertEqual(profile["turn_timeout_seconds"], 300)
            self.assertEqual(profile["max_health_reads"], 3)
            roster = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            encounter, encounter_id = seed_combat_capture._build_encounter(roster, party, profile)
            expected_enemies = ["Goblin"] if party == 1 else ["Goblin Alpha", "Goblin Beta"]
            self.assertEqual(encounter_id, "capture_one_pc" if party == 1 else "capture_mp")
            self.assertEqual([row["name"] for row in encounter["creatures"] if row["type"] == "enemy"],
                             expected_enemies)
            self.assertTrue(all(row["currentHitPoints"] == 20 for row in encounter["creatures"]
                                if row["type"] == "enemy"))

        health_calls = []
        args = _args("narrator-dialogue-travel", 1, ROOT / "tmp")
        session = capture_drive.CaptureSession(
            args, socket_client=FakeSocket(), http_get=lambda _url, **_kwargs: (
                health_calls.append("read") or FakeHealthResponse(["Acheron"])
            ),
        )
        session.capture_profile = fixtures.build_gate_profile(
            "g4", "narrator-dialogue-travel", 1
        )
        for _ in range(3):
            self.assertEqual(session.read_server_health(["Acheron"])["status"], "ok")
        with self.assertRaises(capture_drive.DriverConnectionError):
            session.read_server_health(["Acheron"])
        self.assertEqual((session.health_read_attempts, session.blocked_control_attempts), (3, 1))
        self.assertEqual(len(health_calls), 3)

        for selection in (
                ("g3", "narrator-dialogue-travel", 1, "", ""),
                ("g4", "initiative-pc", 1, "", ""),
                ("g4", "combat-smoke", 2, "", ""),
                ("g4", "narrator-dialogue-travel", 1, "surrender", ""),
                ("unknown", "combat-smoke", 1, "", "")):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                fixtures.build_gate_profile(*selection)

        self.assertEqual(capture_drive.build_parser().parse_args(["--party", "1"]).gate, "g3")
        self.assertEqual(IMPORT_GUARD_COUNTS, {"sdk_constructor": 0, "network": 0})

    def test_game_started_listener_is_scoped_to_g10(self):
        for gate in ("g3", "g4", "g5", "g7", "g9"):
            with self.subTest(gate=gate):
                socket = FakeSocket()
                args = _args(None, 1, ROOT / "tmp")
                args.gate = gate
                session = capture_drive.CaptureSession(args, socket_client=socket)
                session.register_handlers()
                self.assertNotIn("game_started", socket.handlers)

        socket = FakeSocket()
        args = _args(None, 1, ROOT / "tmp")
        args.gate = "g10"
        session = capture_drive.CaptureSession(args, socket_client=socket)
        session.register_handlers()
        self.assertIn("game_started", socket.handlers)

    def test_g4_state_projection_is_read_only_and_checks_room_roster_and_active_pc(self):
        snapshot = {"records": {"party_tracker.json": {"status": "ok"}},
                    "g4_read_only_projection": {
                        "partyMembers": ["Acheron", "Merisiel"], "active_character": "Merisiel",
                        "currentLocation": "Reliquary Alcove", "currentLocationId": "CA03"}}
        projected = capture_evidence.g4_location_projection(
            snapshot, "CA03", ["Acheron", "Merisiel"], "Merisiel")
        self.assertEqual(projected["status"], "PASS")
        self.assertEqual(projected["observed"]["currentLocationId"], "CA03")
        self.assertEqual(capture_evidence.g4_location_projection(
            snapshot, "CA02", ["Acheron", "Merisiel"], "Merisiel")["status"], "BLOCKED")
        self.assertEqual(capture_evidence.g4_location_projection(
            snapshot, "CA03", ["Acheron", "Merisiel"], "Acheron")["status"], "BLOCKED")
        self.assertEqual(capture_evidence.g4_location_projection(
            {}, "CA03", ["Acheron", "Merisiel"], "Merisiel")["status"], "BLOCKED")

    def test_g4_transcript_user_input_parser_requires_exact_author_and_content(self):
        actual = ("[2026-10-18T21:41:03Z] [game_output] type=user-input "
                  "author=Acheron content=Walk east from the gate into the training pit.")
        self.assertTrue(capture_evidence._transcript_has_user_input(
            actual, "Acheron", "Walk east from the gate into the training pit."))
        self.assertFalse(capture_evidence._transcript_has_user_input(
            actual, "Merisiel", "Walk east from the gate into the training pit."))
        self.assertFalse(capture_evidence._transcript_has_user_input(
            actual, "Acheron", "Walk east from the gate."))
        # Echo-looking prose and an output record with no author are not a socket identity record.
        self.assertFalse(capture_evidence._transcript_has_user_input(
            "type=user-input author=Acheron content=Walk east from the gate into the training pit.",
            "Acheron", "Walk east from the gate into the training pit."))
        self.assertFalse(capture_evidence._transcript_has_user_input(
            actual.replace("type=user-input", "type=narration"), "Acheron",
            "Walk east from the gate into the training pit."))

    def test_g4_actual_receipts_pair_to_step_and_keep_zero_cost_provenance(self):
        event = {"event_type": "provider", "site": "main_dm", "call_id": "call-1", "attempt_id": "attempt-1",
                 "attempt_number": 1, "task": "dm_main", "provider": "openai",
                 "requested_model": "requested-model", "resolved_model": "resolved-model",
                 "retry": False, "retry_tier": None, "fallback": False,
                 "usage_available": True, "usage_complete": True, "prompt_tokens": 10,
                 "cached_tokens": 0, "completion_tokens": 5,
                 "provider_reported_cost_usd": 0.0, "cost_usd": 0.0,
                 "cost_provenance": "actual", "cost_complete": True,
                 "_source_byte_start": 10, "_source_byte_end": 20}
        steps = [{"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 0}}},
                  "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}}}]
        paired = capture_evidence.pair_g4_receipts([event], steps)
        self.assertEqual(paired["status"], "ok")
        self.assertEqual(paired["receipts"][0]["step"], 1)
        self.assertEqual(paired["receipts"][0]["receipt"]["provider_reported_cost_usd"], 0.0)
        self.assertEqual(paired["receipts"][0]["receipt"]["cost_label"], "actual")
        self.assertEqual(capture_evidence.pair_g4_receipts([], steps)["status"], "BLOCKED")
        self.assertEqual(capture_evidence.pair_g4_receipts([dict(event, attempt_id=None)], steps)["status"], "BLOCKED")
        self.assertEqual(capture_evidence.pair_g4_receipts([event, event], steps)["status"], "BLOCKED")
        self.assertEqual(capture_evidence.project_g4_receipts([
            dict(event, provider_reported_cost_usd=0.0, cost_provenance="estimated")
        ])["status"], "BLOCKED")
        self.assertEqual(capture_evidence.project_g4_receipts([
            dict(event, provider_reported_cost_usd=None, cost_usd=0.2,
                 cost_provenance="estimated")
        ])["receipts"][0]["cost_label"], "estimated")
        self.assertEqual(capture_evidence.project_g4_receipts([
            dict(event, provider_reported_cost_usd=None, cost_usd=None,
                 cost_provenance="unpriced")
        ])["receipts"][0]["cost_label"], "unpriced_unknown")
        self.assertEqual(capture_evidence.project_g4_receipts([
            dict(event, provider_reported_cost_usd=None, cost_usd=None,
                 cost_provenance=None)
        ])["status"], "BLOCKED")

        startup_receipt = dict(event, _source_byte_start=2, _source_byte_end=8)
        step_receipt = dict(event, call_id="call-2", attempt_id="attempt-2",
                            _source_byte_start=18, _source_byte_end=25)
        startup_and_step = capture_evidence.pair_g4_receipts(
            [startup_receipt, step_receipt],
            [{"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 10},
                                             "input": "Ask Mira", "character": "Acheron"}},
              "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}}}],
            {"status": "captured", "offset_before_bytes": 0, "offset_after_bytes": 10},
            "narrator-dialogue-travel",
        )
        self.assertEqual(startup_and_step["status"], "ok")
        self.assertEqual([row["step"] for row in startup_and_step["receipts"]], ["startup", 1])
        self.assertEqual(capture_evidence.pair_g4_receipts(
            [startup_receipt], [],
            {"status": "captured", "offset_before_bytes": 0, "offset_after_bytes": 4},
            "narrator-dialogue-travel")["status"], "BLOCKED")
        self.assertEqual(capture_evidence.pair_g4_receipts(
            [startup_receipt], [], None, "narrator-dialogue-travel")["status"], "BLOCKED")

        # A legitimate deterministic fast-path input may contain no provider
        # receipt while the following free-text input has a scoped actual call.
        fastpath_and_text = capture_evidence.pair_g4_receipts(
            [dict(step_receipt, task="combat_main", site="combat_main")],
            [
                {"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 10},
                                                "input": "/att Goblin 20 training blade", "character": "Acheron"}},
                 "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 17}}}},
                {"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 17},
                                                "input": "Describe the goblin's response", "character": "Acheron"}},
                 "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}}},
            ], None, "combat-smoke",
        )
        self.assertEqual(fastpath_and_text["status"], "ok")
        self.assertEqual([row["step"] for row in fastpath_and_text["receipts"]], [2])
        self.assertEqual(capture_evidence.pair_g4_receipts(
            [dict(step_receipt, task="dm_main", site="main_dm")], [
                {"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 10},
                                                "input": "Describe the goblin's response"}},
                 "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}}},
            ], None, "combat-smoke")["status"], "BLOCKED")
        self.assertEqual(capture_evidence.pair_g4_receipts(
            [dict(step_receipt, _source_byte_start=31, _source_byte_end=40)], [
                {"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 10}}},
                 "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}}},
            ], None, "combat-smoke")["status"], "BLOCKED")
        legacy = {"schema_version": 1, "event_type": "provider", "site": "combat_compression",
                  "elapsed_ms": 4.0, "prompt_tokens": 10, "completion_tokens": 3,
                  "total_tokens": 13, "recorded_at_ms": 123, "_source_byte_start": 20,
                  "_source_byte_end": 30}
        projected = capture_evidence.project_g4_receipts([dict(event, site="combat_main"), legacy])
        self.assertEqual(projected["status"], "ok")
        self.assertEqual(projected["counts"], {"core_receipts": 1,
                                                 "legacy_provider_observations": 1,
                                                 "trace_provider_rows": 2})
        self.assertEqual(projected["legacy_observations"][0]["provider"], "unknown")
        run_id = "g5-before-p4-1792781887000"
        stamped_legacy = dict(legacy, run_id=run_id, action_id="pc:r1:vitreol")
        stamped = capture_evidence.project_g4_receipts(
            [dict(event, site="combat_main"), stamped_legacy], expected_run_id=run_id
        )
        self.assertEqual(stamped["status"], "ok")
        self.assertEqual(stamped["counts"], {"core_receipts": 1,
                                             "legacy_provider_observations": 1,
                                             "trace_provider_rows": 2})
        self.assertEqual(stamped["legacy_observations"][0]["run_id"], run_id)
        self.assertEqual(stamped["legacy_observations"][0]["action_id"], "pc:r1:vitreol")
        inferred_stamped = capture_evidence.project_g4_receipts([
            dict(event, site="combat_main", run_id=run_id), stamped_legacy,
        ])
        self.assertEqual(inferred_stamped["status"], "ok")
        inferred_foreign = capture_evidence.project_g4_receipts([
            dict(event, site="combat_main", run_id=run_id),
            dict(stamped_legacy, run_id="another-g5-run"),
        ])
        self.assertEqual(inferred_foreign["status"], "BLOCKED")
        for forged in (dict(legacy, task="compression"), dict(legacy, call_id="fake"),
                       dict(legacy, site="unknown_site"), dict(legacy, total_tokens=99),
                       dict(legacy, prompt_tokens=None)):
            self.assertEqual(capture_evidence.project_g4_receipts(
                [dict(event, site="combat_main"), forged])["status"], "BLOCKED")
        for forged in (dict(stamped_legacy, run_id="not a safe id"),
                       dict(stamped_legacy, run_id="another-g5-run"),
                       dict(stamped_legacy, action_id="pc:r1:Vitreol"),
                       dict(stamped_legacy, batch_id="enemy:r1:bad")):
            self.assertEqual(capture_evidence.project_g4_receipts(
                [dict(event, site="combat_main"), forged], expected_run_id=run_id
            )["status"], "BLOCKED")
        self.assertEqual(capture_evidence.project_g4_receipts([
            dict(event, site="combat_main", attempt_id=None)
        ])["status"], "BLOCKED")
        for invalid_core in (dict(event, site="combat_main", call_id=None),
                             dict(event, site="unknown_core_site"),
                             dict(event, site="combat_compression", task="combat_main")):
            self.assertEqual(capture_evidence.pair_g4_receipts(
                [invalid_core], steps, scenario="combat-smoke")["status"], "BLOCKED")

    def test_g4_router_compression_uses_core_projection_and_pairing(self):
        event = {
            "event_type": "provider", "site": "combat_compression",
            "call_id": "compression-call-1", "attempt_id": "compression-attempt-1",
            "attempt_number": 1, "task": "compression", "provider": "openai",
            "requested_model": "requested-model", "resolved_model": "resolved-model",
            "retry": False, "retry_tier": None, "fallback": False,
            "usage_available": True, "usage_complete": True,
            "prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 5,
            "provider_reported_cost_usd": 0.0, "cost_usd": 0.0,
            "cost_provenance": "actual", "cost_complete": True,
            "outcome": "response", "error_type": None,
        }
        projected = capture_evidence.project_g4_receipts([event])
        other_site = capture_evidence.project_g4_receipts([
            dict(event, site="combat_main")
        ])
        self.assertEqual(projected, other_site)
        self.assertEqual(projected["status"], "ok")
        self.assertEqual(projected["counts"], {
            "core_receipts": 1, "legacy_provider_observations": 0,
            "trace_provider_rows": 1,
        })
        self.assertEqual(projected["receipts"][0]["call_id"], "compression-call-1")
        self.assertEqual(projected["receipts"][0]["attempt_id"], "compression-attempt-1")
        self.assertEqual(projected["receipts"][0]["cost_label"], "actual")

        positioned = dict(event, _source_byte_start=10, _source_byte_end=20)
        steps = [{
            "before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 0},
                                          "input": "Describe the goblin response"}},
            "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 30}}},
        }]
        paired = capture_evidence.pair_g4_receipts(
            [positioned], steps, scenario="combat-smoke"
        )
        self.assertEqual(paired["status"], "ok")
        self.assertEqual(paired["counts"], {
            "core_receipts": 1, "legacy_provider_observations": 0,
            "trace_provider_rows": 1,
        })
        self.assertEqual(paired["receipts"][0]["receipt"]["site"], "combat_compression")

    def test_g4_legacy_compression_projection_and_malformed_rules_are_unchanged(self):
        legacy = {
            "schema_version": 1, "event_type": "provider", "site": "combat_compression",
            "elapsed_ms": 4.0, "prompt_tokens": 10, "completion_tokens": 3,
            "total_tokens": 13, "recorded_at_ms": 123,
            "_source_byte_start": 20, "_source_byte_end": 30,
        }
        projected = capture_evidence.project_g4_receipts([legacy])
        self.assertEqual(projected, {
            "status": "BLOCKED", "reason": "required_actual_receipts_missing",
            "receipts": [],
            "legacy_observations": [{
                "schema_version": 1, "event_type": "provider", "site": "combat_compression",
                "elapsed_ms": 4.0, "prompt_tokens": 10, "completion_tokens": 3,
                "total_tokens": 13, "recorded_at_ms": 123,
                "classification": "known_unmigrated_compression_observation",
                "provider": "unknown", "model": "unknown", "cost": "unknown",
                "identity_status": "no_router_attempt_identity",
                "_source_byte_start": 20, "_source_byte_end": 30,
            }],
            "counts": {"core_receipts": 0, "legacy_provider_observations": 1,
                       "trace_provider_rows": 1},
        })
        malformed = capture_evidence.project_g4_receipts([
            dict(legacy, total_tokens=99)
        ])
        self.assertEqual(malformed["status"], "BLOCKED")
        self.assertEqual(malformed["reason"], "invalid_legacy_compression_observation")

    def test_g4_partial_compression_receipt_identity_is_blocked(self):
        legacy = {
            "schema_version": 1, "event_type": "provider", "site": "combat_compression",
            "elapsed_ms": 4.0, "prompt_tokens": 10, "completion_tokens": 3,
            "total_tokens": 13, "recorded_at_ms": 123,
        }
        for mixed in (dict(legacy, task="compression"),
                      dict(legacy, attempt_id="partial-attempt"),
                      dict(legacy, call_id="partial-call", attempt_id="partial-attempt")):
            with self.subTest(keys=sorted(mixed)):
                result = capture_evidence.project_g4_receipts([mixed])
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["reason"], "invalid_or_duplicate_receipt_identity")

    def test_g4_collector_reads_real_router_adapter_receipts_from_real_trace_writer(self):
        """Exercise the actual router -> legacy observer -> real JSONL writer path."""
        from types import SimpleNamespace
        from utils import ai_client_factory, llm_router, llm_runtime, combat_latency_trace
        import model_config as runtime_model_config

        class FakeSDKClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
                self.responses = [
                    {"choices": [{"message": {"content": "zero priced"}}],
                     "model": "g4-test-resolved", "provider": "openai",
                     "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                               "prompt_tokens_details": {"cached_tokens": 0},
                               "total_tokens": 14, "cost": 0.0}},
                    {"choices": [{"message": {"content": "unpriced"}}],
                     "model": "g4-test-resolved", "provider": "openai",
                     "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                               "prompt_tokens_details": {"cached_tokens": 0},
                               "total_tokens": 14}},
                    {"choices": [{"message": {"content": "@T=CS/v2\n@ROUND=2"}}],
                     "model": "g4-test-resolved", "provider": "openai",
                     "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                               "prompt_tokens_details": {"cached_tokens": 0},
                               "total_tokens": 14, "cost": 0.0}},
                ]

            def with_options(self, **_kwargs):
                return self

            def create(self, **_kwargs):
                return self.responses.pop(0)

        class RecordingTracker:
            def __init__(self):
                self.calls = []

            def track(self, response, metadata):
                self.calls.append((response, metadata))

        with tempfile.TemporaryDirectory(prefix="g4-receipt-vertical-", dir="tmp") as directory:
            trace_path = pathlib.Path(directory) / "combat_turn_trace.jsonl"
            source_before = capture_evidence.trace_byte_offset(trace_path, pathlib.Path(directory))
            client = FakeSDKClient()
            tracker = RecordingTracker()
            real_writer = lambda event_type, **fields: combat_latency_trace.emit_trace_event(
                event_type, path=trace_path, **fields
            )
            observer = llm_runtime.make_legacy_receipt_observer(
                trace_site="combat_main", trace_gate=lambda: True,
                trace_writer=real_writer, tracker_getter=lambda: tracker,
            )
            with patch.object(ai_client_factory, "_get_actual_provider", return_value=("openai", False)), \
                 patch.object(ai_client_factory, "create_chat_client", return_value=client), \
                 patch.object(runtime_model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                 patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                router = llm_router.LLMRouter()
                router.call("combat_main", [{"role": "user", "content": "receipt vertical"}],
                            json_output=False, observer=observer)
                startup_end = capture_evidence.trace_byte_offset(trace_path, pathlib.Path(directory))
                router.call("combat_main", [{"role": "user", "content": "receipt provenance"}],
                            json_output=False, observer=observer)
                compression_observer = llm_runtime.make_legacy_receipt_observer(
                    trace_site="combat_compression", trace_gate=lambda: True,
                    trace_writer=real_writer, tracker_getter=lambda: tracker,
                )
                router.call("compression", [{"role": "user", "content": "compression receipt"}],
                            json_output=False, observer=compression_observer)
                legacy_response = SimpleNamespace(usage={"prompt_tokens": 2417,
                                                          "completion_tokens": 283,
                                                          "total_tokens": 2700})
                self.assertTrue(combat_latency_trace.trace_provider_call(
                    "combat_compression", __import__("time").perf_counter(), legacy_response
                ))

            source_after = capture_evidence.trace_byte_offset(trace_path, pathlib.Path(directory))
            self.assertEqual(source_before["status"], "captured")
            self.assertEqual(source_after["status"], "captured")
            events, parse_errors = capture_evidence.parse_trace_positions(trace_path, 0)
            self.assertEqual(parse_errors, [])
            provider_rows = [row for row in events if row.get("event_type") == "provider"]
            self.assertEqual(len(provider_rows), 4)
            self.assertEqual(provider_rows[0]["task"], "combat_main")
            self.assertTrue(provider_rows[0]["call_id"])
            self.assertTrue(provider_rows[0]["attempt_id"])
            self.assertEqual(provider_rows[0]["provider"], "openai")
            self.assertTrue(provider_rows[0]["requested_model"])
            self.assertEqual(provider_rows[0]["resolved_model"], "g4-test-resolved")
            self.assertIs(provider_rows[0]["retry"], False)
            self.assertIs(provider_rows[0]["fallback"], False)
            self.assertIs(provider_rows[0]["usage_available"], True)
            self.assertIs(provider_rows[0]["usage_complete"], True)
            self.assertEqual(provider_rows[0]["provider_reported_cost_usd"], 0.0)
            self.assertEqual(provider_rows[0]["cost_provenance"], "actual")
            self.assertEqual(provider_rows[2]["site"], "combat_compression")
            self.assertEqual(provider_rows[2]["task"], "compression")
            self.assertTrue(provider_rows[2]["call_id"])
            self.assertTrue(provider_rows[2]["attempt_id"])

            step = [{"before": {"observation": {"runtimeTrace": {
                        "status": "captured", "offset_bytes": startup_end["offset_bytes"]},
                        "input": "Ask Warden Mira", "character": "Acheron"}},
                     "after": {"observation": {"runtimeTrace": {
                         "status": "captured", "offset_bytes": source_after["offset_bytes"]}}}}]
            startup = {"status": "captured", "offset_before_bytes": source_before["offset_bytes"],
                       "offset_after_bytes": startup_end["offset_bytes"]}
            paired = capture_evidence.pair_g4_receipts(
                provider_rows, step, startup, "combat-smoke"
            )
            self.assertEqual(paired["status"], "ok")
            self.assertEqual([row["step"] for row in paired["receipts"]], ["startup", 1, 1])
            self.assertEqual(paired["counts"], {"core_receipts": 3,
                                                   "legacy_provider_observations": 1,
                                                   "trace_provider_rows": 4})
            compression_pair = next(row for row in paired["receipts"]
                                    if row["receipt"]["site"] == "combat_compression")
            self.assertEqual(compression_pair["receipt"]["task"], "compression")
            self.assertEqual(compression_pair["receipt"]["cost_label"], "actual")
            self.assertEqual(len(tracker.calls), 3)
            self.assertEqual(paired["legacy_observations"][0]["step"], 1)
            self.assertEqual(paired["legacy_observations"][0]["observation"]["model"], "unknown")
            legacy_pair = paired["legacy_observations"][0]
            self.assertEqual(legacy_pair["observation"]["prompt_tokens"], 2417)
            self.assertEqual(legacy_pair["observation"]["completion_tokens"], 283)
            self.assertEqual(legacy_pair["observation"]["total_tokens"], 2700)
            self.assertEqual(legacy_pair["source_byte_start"], provider_rows[3]["_source_byte_start"])
            self.assertEqual(legacy_pair["source_byte_end"], provider_rows[3]["_source_byte_end"])
            self.assertEqual(legacy_pair["source_line"], provider_rows[3]["_source_line"])
            labels = {row["receipt"]["cost_label"] for row in paired["receipts"]}
            self.assertIn("actual", labels)
            self.assertTrue(labels.intersection({"estimated", "unpriced_unknown"}))
            for field, bad_value in (("resolved_model", None), ("task", None),
                                     ("retry", None), ("fallback", None),
                                     ("usage_available", None), ("provider", None)):
                self.assertEqual(capture_evidence.pair_g4_receipts(
                    [dict(provider_rows[0], **{field: bad_value})], step
                )["status"], "BLOCKED", field)

    def test_g4_run_path_uses_distinct_strict_root_and_preserves_g3_root(self):
        scratch = tempfile.TemporaryDirectory(prefix="g4-path-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        sandbox = pathlib.Path(scratch.name) / "sandbox"
        sandbox.mkdir()
        for gate, root in (("g3", capture_evidence.RUN_ROOT), ("g4", capture_evidence.G4_RUN_ROOT)):
            run = root / ("unit-" + gate + "-path")
            if run.exists():
                self.fail("test run path must be unique")
            validated_run, validated_state = capture_evidence.validate_evidence_paths(run, sandbox, gate)
            self.assertEqual(validated_run, run)
            self.assertEqual(validated_state, sandbox.resolve())

    def test_g5_gate_reuses_fixed_latency_fixtures_and_keeps_g3_default(self):
        self.assertEqual(fixtures.CAPTURE_GATES, ("g3", "g4", "g5", "g5r", "g5t"))
        self.assertEqual(capture_drive.build_parser().parse_args(["--party", "1"]).gate, "g3")
        self.assertEqual(capture_drive.build_parser().parse_args(
            ["--party", "1", "--gate", "g5", "--scenario", "combat-smoke"]
        ).gate, "g5")
        self.assertEqual(capture_drive.build_parser().parse_args(
            ["--party", "1", "--gate", "g5r", "--scenario", "combat-smoke"]
        ).gate, "g5r")
        self.assertEqual(capture_drive.build_parser().parse_args(
            ["--party", "1", "--gate", "g5t", "--scenario", "g5t-commander-p1"]
        ).scenario, "g5t-commander-p1")

        for party, seed_identity in ((1, "P1 Goblin"), (4, "P4 Goblin Alpha+Beta")):
            baseline = fixtures.build_capture_profile("combat-smoke", party)
            g5_profile = fixtures.build_gate_profile("g5", "combat-smoke", party)
            g5r_profile = fixtures.build_gate_profile("g5r", "combat-smoke", party)
            self.assertEqual(g5_profile["gate"], "g5")
            self.assertEqual(g5r_profile["gate"], "g5r")
            self.assertEqual(g5r_profile["fixture"], g5_profile["fixture"])
            self.assertEqual(g5r_profile["seed_identity"], g5_profile["seed_identity"])
            self.assertEqual(g5r_profile["max_steps"], g5_profile["max_steps"])
            self.assertEqual(g5r_profile["max_requests"], g5_profile["max_requests"])
            for field in ("scenario_id", "party_size", "branch", "phase", "max_steps",
                          "max_active_switches", "applicability", "seed"):
                if party == 4 and field == "max_steps":
                    continue
                self.assertEqual(g5_profile[field], baseline[field], field)
                self.assertEqual(g5r_profile[field], g5_profile[field], field)
            self.assertEqual(g5_profile["seed_identity"], seed_identity)
            self.assertEqual(g5_profile["max_inputs"], g5_profile["max_steps"])
            self.assertEqual(g5_profile["max_controls"], g5_profile["max_requests"])
            self.assertEqual(g5_profile["max_health_reads"], 0)

        p1 = fixtures.build_gate_profile("g5", "combat-smoke", 1)
        self.assertEqual((p1["max_steps"], p1["max_requests"], p1["max_inputs"],
                          p1["max_controls"]), (5, 7, 5, 7))
        p1_g5r = fixtures.build_gate_profile("g5r", "combat-smoke", 1)
        self.assertEqual((p1_g5r["max_steps"], p1_g5r["max_requests"],
                          p1_g5r["max_inputs"], p1_g5r["max_controls"]), (5, 7, 5, 7))

        p4 = fixtures.build_gate_profile("g5", "combat-smoke", 4)
        p4_g5r = fixtures.build_gate_profile("g5r", "combat-smoke", 4)
        script = fixtures.build_command_script()
        steps = fixtures.build_g5_script_steps(4)
        self.assertEqual(len(script), 26)
        self.assertEqual(p4["max_steps"], len(script))
        self.assertEqual(len(steps), len(script))
        # The driver counts one start_game request, every scripted user_input,
        # and every set_active call (including the initial switch to Acheron).
        switches = 1
        current_character = capture_drive.MP_PARTY_ROSTER[0]
        for step in steps:
            character = step["character"]
            if character and character != current_character:
                switches += 1
                current_character = character
        self.assertEqual(switches, p4["max_active_switches"])
        expected_driver_requests = 1 + len(steps) + switches
        self.assertEqual(expected_driver_requests, 39)
        self.assertEqual(p4["max_requests"], expected_driver_requests)
        self.assertEqual(p4["max_controls"], expected_driver_requests)
        self.assertEqual((p4_g5r["max_steps"], p4_g5r["max_requests"],
                          p4_g5r["max_inputs"], p4_g5r["max_controls"]),
                         (26, 39, 26, 39))

        # G3/G4 profile caps and the G3 default remain untouched.
        self.assertEqual(capture_drive.build_parser().parse_args(["--party", "1"]).gate, "g3")
        for gate in ("g3", "g4"):
            for party, expected in ((1, (5, 7)), (4, (22, 35))):
                profile = fixtures.build_gate_profile(gate, "combat-smoke", party)
                self.assertEqual((profile["max_steps"], profile["max_requests"]), expected)
                if gate == "g4":
                    self.assertEqual((profile["max_inputs"], profile["max_controls"]), expected)

        self.assertEqual(fixtures.build_gate_profile("g3", "combat-smoke", 1)["max_steps"], 5)
        self.assertEqual(fixtures.build_gate_profile("g4", "combat-smoke", 1)["gate"], "g4")
        with self.assertRaisesRegex(ValueError, "G5 supports only"):
            fixtures.build_gate_profile("g5", "narrator-dialogue-travel", 1)
        with self.assertRaisesRegex(ValueError, "G5R supports only"):
            fixtures.build_gate_profile("g5r", "narrator-dialogue-travel", 1)

        args = capture_drive.build_parser().parse_args(["--party", "1", "--gate", "g5"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = capture_drive.run(args)
        self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
        self.assertIn("--gate g5 requires --scenario combat-smoke", output.getvalue())

        args = capture_drive.build_parser().parse_args(["--party", "1", "--gate", "g5r"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = capture_drive.run(args)
        self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
        self.assertIn("--gate g5r requires --scenario combat-smoke", output.getvalue())

    def test_capture_goblin_encounters_use_one_attack_without_mutating_fixtures(self):
        for party in (1, 4):
            names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            original_one_pc = fixtures._one_pc_encounter_payload()
            original_four_pc = fixtures._encounter_payload()
            profile = fixtures.build_gate_profile("g5", "combat-smoke", party)
            encounter, _ = seed_combat_capture._build_encounter(names, party, profile)
            goblins = [row for row in encounter["creatures"]
                       if row.get("type") == "enemy" and row.get("monsterType") == "Goblin"]
            self.assertTrue(goblins)
            for goblin in goblins:
                self.assertEqual(goblin["numAttacks"], 1)
                self.assertEqual([attack["name"] for attack in goblin["attacks"]],
                                 ["Scimitar", "Shortbow"])
            self.assertTrue(all("numAttacks" not in row and "attacks" not in row
                                for row in encounter["creatures"] if row.get("type") == "player"))
            self.assertTrue(all("numAttacks" not in row for row in original_one_pc["creatures"]))
            self.assertTrue(all("numAttacks" not in row for row in original_four_pc["creatures"]))

        profile = fixtures.build_capture_profile("combat-smoke-allied-inactive", 4)
        encounter, _ = seed_combat_capture._build_encounter(list(fixtures.PC_NAMES), 4, profile)
        inactive = next(row for row in encounter["creatures"] if row.get("name") == "Inactive Goblin")
        self.assertEqual(inactive["numAttacks"], 1)
        self.assertEqual([attack["name"] for attack in inactive["attacks"]],
                         ["Scimitar", "Shortbow"])

    def test_g5_run_path_is_strictly_isolated_and_unique(self):
        scratch = tempfile.TemporaryDirectory(prefix="g5-path-state-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        sandbox = pathlib.Path(scratch.name) / "sandbox"
        sandbox.mkdir()
        g5_root = capture_evidence.G5_RUN_ROOT
        g5r_root = capture_evidence.G5R_RUN_ROOT
        run = g5_root / ("unit-g5-" + uuid.uuid4().hex)
        validated_run, validated_state = capture_evidence.validate_evidence_paths(run, sandbox, "g5")
        self.assertEqual(validated_run, run)
        self.assertEqual(validated_state, sandbox.resolve())
        g5r_run = g5r_root / ("unit-g5r-" + uuid.uuid4().hex)
        validated_g5r_run, validated_g5r_state = capture_evidence.validate_evidence_paths(
            g5r_run, sandbox, "g5r"
        )
        self.assertEqual(validated_g5r_run, g5r_run)
        self.assertEqual(validated_g5r_state, sandbox.resolve())

        rejected_paths = (
            capture_evidence.RUN_ROOT / "wrong-gate-g3",
            capture_evidence.G4_RUN_ROOT / "wrong-gate-g4",
            g5_root / ".." / "g3" / "traversal",
            pathlib.Path("/outside-project/router-rollout/g5/absolute-run"),
        )
        for rejected in rejected_paths:
            with self.subTest(path=str(rejected)), self.assertRaises(ValueError):
                capture_evidence.validate_evidence_paths(rejected, sandbox, "g5")

        rejected_g5r_paths = (
            capture_evidence.RUN_ROOT / "wrong-gate-g3-for-g5r",
            capture_evidence.G4_RUN_ROOT / "wrong-gate-g4-for-g5r",
            g5_root / "wrong-gate-g5-for-g5r",
            g5r_root / ".." / "g5" / "traversal",
            pathlib.Path("/outside-project/router-rollout/g5r/absolute-run"),
        )
        for rejected in rejected_g5r_paths:
            with self.subTest(path=str(rejected)), self.assertRaises(ValueError):
                capture_evidence.validate_evidence_paths(rejected, sandbox, "g5r")

        root_was_present = g5_root.exists()
        g5_root.mkdir(parents=True, exist_ok=True)
        g5r_root_was_present = g5r_root.exists()
        g5r_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="existing-g5-run-", dir=str(g5_root)) as existing:
                with self.assertRaisesRegex(ValueError, "not-yet-existing"):
                    capture_evidence.validate_evidence_paths(existing, sandbox, "g5")
            with tempfile.TemporaryDirectory(prefix="existing-g5r-run-", dir=str(g5r_root)) as existing:
                with self.assertRaisesRegex(ValueError, "not-yet-existing"):
                    capture_evidence.validate_evidence_paths(existing, sandbox, "g5r")
        finally:
            if not root_was_present:
                try:
                    g5_root.rmdir()
                except OSError:
                    pass
            if not g5r_root_was_present:
                try:
                    g5r_root.rmdir()
                except OSError:
                    pass

        for gate, root in (("g3", capture_evidence.RUN_ROOT),
                           ("g4", capture_evidence.G4_RUN_ROOT),
                           ("g5", g5_root)):
            old_gate_run = root / ("unit-preserved-" + gate + "-" + uuid.uuid4().hex)
            self.assertEqual(capture_evidence.validate_evidence_paths(
                old_gate_run, sandbox, gate
            )[0], old_gate_run)
            with self.assertRaises(ValueError):
                capture_evidence.validate_evidence_paths(g5r_run, sandbox, gate)

    def test_evidence_cli_evaluates_g5_roles_without_falling_back_and_preserves_g3_g4_dispatch(self):
        for selected_gate, expected_status in (("g3", "G3_DISPATCHED"),
                                               ("g4", "G4_DISPATCHED")):
            g3_result = {"automated_status": expected_status, "primary_verdict": "PENDING"}
            g4_result = {"automated_status": expected_status, "primary_verdict": "PENDING"}
            output = io.StringIO()
            argv = ["--run-dir", "tmp/router-rollout/%s/selector-test" % selected_gate]
            if selected_gate == "g4":
                argv = ["--gate", "g4"] + argv
            with patch.object(capture_evidence, "evaluate_matrix", return_value=g3_result) as g3_eval, \
                    patch.object(capture_evidence, "evaluate_g4_matrix", return_value=g4_result) as g4_eval, \
                    contextlib.redirect_stdout(output):
                status = capture_evidence.main(argv)
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(output.getvalue())["automated_status"], expected_status)
            self.assertEqual(g3_eval.called, selected_gate == "g3")
            self.assertEqual(g4_eval.called, selected_gate == "g4")

        output = io.StringIO()
        table = io.StringIO()
        with patch.object(capture_evidence, "evaluate_matrix") as g3_eval, \
                patch.object(capture_evidence, "evaluate_g4_matrix") as g4_eval, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(table):
            status = capture_evidence.main([
                "--gate", "g5"
            ])
        self.assertEqual(status, 2)
        blocked = json.loads(output.getvalue())
        self.assertEqual(blocked["automated_status"], "BLOCKED")
        self.assertEqual(blocked["gate"], "g5")
        self.assertIn("before_role_requires_exactly_two_bundles", blocked["blocking_reasons"])
        self.assertIn("after_role_requires_exactly_two_bundles", blocked["blocking_reasons"])
        self.assertIn("Combat G5 comparison [BLOCKED]", table.getvalue())
        g3_eval.assert_not_called()
        g4_eval.assert_not_called()

        output = io.StringIO()
        table = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(table):
            status = capture_evidence.main([
                "--gate", "g5", "--run-dir", "tmp/router-rollout/g5/legacy-single-input"
            ])
        self.assertEqual(status, 2)
        blocked = json.loads(output.getvalue())
        self.assertEqual(blocked["automated_status"], "BLOCKED")
        self.assertIn("g5_requires_explicit_before_and_after_roles", blocked["blocking_reasons"])

    def test_g5r_evidence_cli_enforces_three_runs_per_party_from_isolated_root(self):
        root = capture_evidence.G5R_RUN_ROOT
        root_was_present = root.exists()
        root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="g5r-run-count-", dir=str(root)) as scratch:
                after_paths = []
                for party_size, count in ((1, 2), (4, 3)):
                    for index in range(count):
                        run_id = "p%d-run-%d" % (party_size, index + 1)
                        run_dir = pathlib.Path(scratch) / run_id
                        run_dir.mkdir()
                        (run_dir / "manifest.json").write_text(json.dumps({
                            "gate": "g5r", "run_id": run_id, "party": {"size": party_size},
                        }), encoding="ascii")
                        after_paths.append(run_dir)
                argv = ["--gate", "g5r",
                        "--before", "tmp/router-rollout/g5/missing-p1",
                        "--before", "tmp/router-rollout/g5/missing-p4"]
                for run_dir in after_paths:
                    argv.extend(("--after", str(run_dir)))
                output = io.StringIO()
                table = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(table):
                    status = capture_evidence.main(argv)
                result = json.loads(output.getvalue())
                self.assertEqual(status, 2)
                self.assertEqual(result["gate"], "g5r")
                self.assertEqual(result["automated_status"], "BLOCKED")
                self.assertIn("p1_after_role_requires_exactly_three_bundles",
                              result["blocking_reasons"])
                self.assertIn("Combat G5R comparison [BLOCKED]", table.getvalue())

            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                status = capture_evidence.main(["--gate", "g5r", "--run-dir",
                                                "tmp/router-rollout/g5r/single-run"])
            result = json.loads(output.getvalue())
            self.assertEqual(status, 2)
            self.assertEqual(result["automated_status"], "BLOCKED")
            self.assertIn("g5r_requires_explicit_before_and_after_roles",
                          result["blocking_reasons"])
        finally:
            if not root_was_present:
                try:
                    root.rmdir()
                except OSError:
                    pass

    def test_g5r_seeder_enables_resolver_only_in_temporary_sandbox(self):
        root = capture_evidence.G5R_RUN_ROOT
        root_was_present = root.exists()
        root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="g5r-seeder-", dir=str(root)) as scratch:
                source = seed_combat_capture.PROJECT_ROOT / "model_config.py"
                installed_before = source.read_bytes()
                for gate, expected_resolver, expected_tactical in (
                        ("g5", False, False), ("g5r", True, False), ("g5t", True, True)):
                    sandbox = pathlib.Path(scratch) / ("sandbox-" + gate)
                    sandbox.mkdir()
                    sandbox_model_config = sandbox / "model_config.py"
                    sandbox_model_config.write_bytes(installed_before)
                    with patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox):
                        seed_combat_capture._patch_sandbox_model_config(gate)
                    sandbox_text = sandbox_model_config.read_text(encoding="utf-8")
                    self.assertIn("ENABLE_COMBAT_TURN_TRACE = True", sandbox_text)
                    literal = "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED = %s" % str(expected_resolver)
                    self.assertIn(literal, sandbox_text)
                    identity = capture_evidence.read_sandbox_resolver_identity(sandbox)
                    self.assertEqual(identity["status"], "ok")
                    self.assertIs(identity["enabled"], expected_resolver)
                    tactical_identity = capture_evidence.read_sandbox_tactical_identity(sandbox)
                    self.assertEqual(tactical_identity["status"], "ok")
                    self.assertIs(tactical_identity["enabled"], expected_tactical)
                self.assertEqual(source.read_bytes(), installed_before)
        finally:
            if not root_was_present:
                try:
                    root.rmdir()
                except OSError:
                    pass

    def test_g5t_profiles_and_sandbox_cover_fixture_are_isolated(self):
        self.assertEqual(fixtures.G5_CAPTURE_GATES, ("g5", "g5r", "g5t", "g5a"))
        expected = {
            1: {"max_steps": 31, "max_requests": 33, "max_controls": 33,
                "max_inputs": 31, "max_active_switches": 1},
            4: {"max_steps": 42, "max_requests": 57, "max_controls": 57,
                "max_inputs": 42, "max_active_switches": 14},
        }
        for party_size in (1, 4):
            scenario = "g5t-commander-p%d" % party_size
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile("g5t", scenario, party_size)
                fixture = fixtures.build_g5t_commander_fixture(party_size)
                steps = fixtures.build_g5t_script_steps(party_size)
                for key, value in expected[party_size].items():
                    self.assertEqual(profile[key], value, key)
                self.assertEqual(profile["max_steps"], len(steps))
                self.assertEqual(profile["max_inputs"], len(steps))
                self.assertEqual(profile["max_requests"],
                                 len(steps) + 1 + fixtures.build_g5t_script_active_switch_count(
                                     party_size))
                self.assertEqual(profile["max_health_reads"], 0)
                self.assertEqual(profile["seed"], {
                    "captain_hit_points": 39, "goblin_squad_a_hit_points": 7,
                    "goblin_squad_b_hit_points": 7,
                    "goblin_squad_b_cover_type": "half",
                    "goblin_squad_b_cover_feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                    "pc_hit_points": fixtures.build_g5t_worst_case_pc_hit_points(party_size),
                    "awaitingPcGroupRoll": False, "initiativeWinner": "pcGroup",
                })
                self.assertEqual(profile["seed_identity"],
                                 "Hobgoblin Captain + Goblin Squad A+B")
                self.assertEqual(profile["fixture"]["fixture_id"], scenario)
                self.assertEqual(profile["fixture"]["steps_sha256"],
                                 fixtures.build_g5t_fixture_metadata(party_size)["steps_sha256"])
                self.assertEqual(
                    len([row for row in steps if row["unit_type"] == "batch"]),
                    7 if party_size == 1 else 6,
                )
                captain = next(row for row in fixture["encounter"]["creatures"]
                               if row.get("name") == fixtures.G5T_COMMANDER_NAME)
                self.assertIs(captain["leader"], True)
                self.assertEqual(captain["tactics"], "commander")
                goblins = [row for row in fixture["encounter"]["creatures"]
                           if row.get("name") in fixtures.G5T_GOBLIN_NAMES]
                self.assertEqual(len(goblins), 2)
                self.assertTrue(all(row["monsterType"] == "Goblin" for row in goblins))
                self.assertEqual(
                    {row["name"]: (row["currentHitPoints"], row["maxHitPoints"])
                     for row in [captain] + goblins},
                    {fixtures.G5T_COMMANDER_NAME: (39, 39),
                     fixtures.G5T_GOBLIN_NAMES[0]: (7, 7),
                     fixtures.G5T_GOBLIN_NAMES[1]: (7, 7)},
                )
                goblin_b = next(row for row in goblins
                                if row["name"] == fixtures.G5T_GOBLIN_NAMES[1])
                self.assertEqual(goblin_b["coverFeatureId"],
                                 fixtures.G5T_TRAINING_PIT_FEATURE_ID)
                self.assertEqual(goblin_b["coverType"], "half")

        p1_steps = fixtures.build_g5t_script_steps(1)
        self.assertEqual([row["input"] for row in p1_steps], [
            "/end",
            "/att Goblin Squad B 19 training blade", "/dmg 4 Goblin Squad B",
            "/att Goblin Squad A 19 training blade", "/dmg 4 Goblin Squad A",
            "/end",
            "/att Goblin Squad A 19 training blade", "/dmg 3 Goblin Squad A",
            "/att Goblin Squad B 19 training blade", "/dmg 4 Goblin Squad B",
            "/end",
            "/att Hobgoblin Captain 19 training blade", "/dmg 8 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 training blade", "/dmg 8 Hobgoblin Captain",
            "/end",
            "/att Goblin Squad B 19 training blade", "/dmg 3 Goblin Squad B",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/end",
            "/att Hobgoblin Captain 19 training blade", "/dmg 6 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 training blade", "/dmg 5 Hobgoblin Captain",
            "/end",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 training blade", "/dmg 6 Hobgoblin Captain",
            "/end",
        ])
        p4_steps = fixtures.build_g5t_script_steps(4)
        self.assertEqual([row["input"] for row in p4_steps], [
            "/end",
            "/att Goblin Squad B 19 training blade", "/dmg 4 Goblin Squad B",
            "/att Goblin Squad B 1 training blade", "/dmg 3 Goblin Squad B",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 shortsword", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 crossbow, light", "/dmg 3 Hobgoblin Captain",
            "/end",
            "/att Goblin Squad A 19 training blade", "/dmg 4 Goblin Squad A",
            "/att Goblin Squad B 19 training blade", "/dmg 4 Goblin Squad B",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 shortsword", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 crossbow, light", "/dmg 3 Hobgoblin Captain",
            "/end",
            "/att Goblin Squad B 19 training blade", "/dmg 3 Goblin Squad B",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 training blade", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 shortsword", "/dmg 3 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 crossbow, light", "/dmg 3 Hobgoblin Captain",
            "/end",
            "/att Goblin Squad A 19 training blade", "/dmg 3 Goblin Squad A",
            "/end",
            "/att Hobgoblin Captain 19 training blade", "/dmg 5 Hobgoblin Captain",
            "/att Hobgoblin Captain 19 training blade", "/dmg 5 Hobgoblin Captain",
            "/end",
        ])
        self.assertEqual([p1_steps[0]["input"], p4_steps[0]["input"]], ["/end", "/end"])
        for steps, round_number in ((p1_steps, 7), (p4_steps, 6)):
            closing_step = steps[-1]
            self.assertEqual(closing_step["label"], "final enemy phase (/end) combat exit")
            self.assertEqual(closing_step["input"], "/end")
            self.assertEqual(closing_step["unit_type"], "batch")
            self.assertEqual(closing_step["unit_id"], "batch-step-%03d" % len(steps))
            self.assertEqual(closing_step["trace_batch_id"], "enemy:r%d" % round_number)
            self.assertIs(closing_step["requires_combat_exit"], True)
        self.assertEqual(
            [row["trace_batch_id"] for row in p1_steps if row["unit_type"] == "batch"],
            ["enemy:r1", "enemy:r2", "enemy:r3", "enemy:r4", "enemy:r5", "enemy:r6",
             "enemy:r7"],
        )
        self.assertEqual(
            [row["trace_batch_id"] for row in p4_steps if row["unit_type"] == "batch"],
            ["enemy:r1", "enemy:r2", "enemy:r3", "enemy:r4", "enemy:r5", "enemy:r6"],
        )
        self.assertEqual(fixtures.build_g5t_worst_case_script_damage(1), 192)
        self.assertEqual(fixtures.build_g5t_worst_case_script_damage(4), 160)
        self.assertEqual(fixtures.build_g5t_worst_case_pc_hit_points(1), 193)
        self.assertEqual(fixtures.build_g5t_worst_case_pc_hit_points(4), 161)

        for party_size, round_number in ((1, 2), (4, 2)):
            same_round_acheron_attacks = [
                row for row in fixtures.build_g5t_script_steps(party_size)
                if row["round"] == round_number
                and row["character"] == "Acheron"
                and row["input"].startswith("/att ")
            ]
            self.assertEqual(len(same_round_acheron_attacks), 2)
            self.assertEqual(
                [row["input"] for row in same_round_acheron_attacks],
                [
                    "/att Goblin Squad B 19 training blade",
                    "/att Goblin Squad A 19 training blade",
                ] if party_size == 1 else [
                    "/att Goblin Squad B 19 training blade",
                    "/att Goblin Squad B 1 training blade",
                ],
            )

        for name in ("Acheron", "Merisiel"):
            character = fixtures.build_capture_character_payload(name, 20)
            blade = next(item for item in character["equipment"]
                         if item["item_name"] == "training blade")
            self.assertEqual(blade["damage"], "1d6+2 slashing")
        acheron = fixtures.build_capture_character_payload("Acheron", 20)
        self.assertTrue(any(feature["name"] == "Extra Attack"
                            for feature in acheron["classFeatures"]))

        for party_size in (1, 4):
            profile = fixtures.build_gate_profile(
                "g5t", "g5t-commander-p%d" % party_size, party_size)
            encounter, encounter_id = seed_combat_capture._build_encounter(
                list(fixtures.PC_NAMES[:party_size]), party_size, profile)
            self.assertEqual(encounter_id, "g5t-commander-p%d" % party_size)
            enemies = {row["name"]: row for row in encounter["creatures"]
                       if row.get("type") == "enemy"}
            self.assertEqual(
                {name: (row["currentHitPoints"], row["maxHitPoints"])
                 for name, row in enemies.items()},
                {fixtures.G5T_COMMANDER_NAME: (39, 39),
                 fixtures.G5T_GOBLIN_NAMES[0]: (7, 7),
                 fixtures.G5T_GOBLIN_NAMES[1]: (7, 7)},
            )
            goblin_b = enemies[fixtures.G5T_GOBLIN_NAMES[1]]
            self.assertEqual(goblin_b["coverFeatureId"],
                             fixtures.G5T_TRAINING_PIT_FEATURE_ID)
            self.assertEqual(goblin_b["coverType"], "half")

        for party_size in (1, 4):
            profile = fixtures.build_gate_profile(
                "g5t", "g5t-commander-p%d" % party_size, party_size)
            seeded = {}
            reference = {
                "module": "Capture_Arena", "start_location_name": "Waystone Gate",
                "start_location_id": "CA01", "area_name": "Capture Arena",
                "area_id": "CTR001",
            }
            path_manager = SimpleNamespace(
                get_character_unified_path=lambda name: "characters/%s.json" % name.lower()
            )
            seed_combat_capture._seed_party(
                reference, list(fixtures.PC_NAMES[:party_size]), party_size, profile,
                writer=lambda path, payload: seeded.__setitem__(path, copy.deepcopy(payload)),
                path_manager=path_manager,
            )
            seeded_location = seeded["party_tracker.json"]["worldConditions"]
            self.assertEqual(seeded_location["currentLocationId"], "CA02")
            self.assertEqual(seeded_location["currentLocation"], "Training Pit")
            expected_hp = fixtures.build_g5t_worst_case_pc_hit_points(party_size)
            for name in fixtures.PC_NAMES[:party_size]:
                pc = seeded["characters/%s.json" % name.lower()]
                self.assertEqual(pc["hitPoints"], expected_hp)
                self.assertEqual(pc["maxHitPoints"], expected_hp)
                self.assertEqual(pc["armorClass"], 14)
                self.assertEqual(pc["initiative"], seed_combat_capture._party_initiative(
                    name, party_size))
        with self.assertRaisesRegex(ValueError, "G5T supports only"):
            fixtures.build_gate_profile("g5t", "g5t-commander-p1", 4)
        with self.assertRaisesRegex(ValueError, "not supported by G5T"):
            fixtures.build_gate_profile("g5t", "g5t-commander-p1", 1, branch="surrender")

        args = capture_drive.build_parser().parse_args(["--party", "1", "--gate", "g5t"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = capture_drive.run(args)
        self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
        self.assertIn("--gate g5t requires --scenario g5t-commander-p1|g5t-commander-p4",
                      output.getvalue())

        tmp_root = ROOT / "tmp"
        tmp_root.mkdir(exist_ok=True)
        source_module = ROOT / "modules" / "Capture_Arena"
        source_paths = [source_module / "areas" / name
                        for name in ("CTR001_BU.json", "CTR001.json")]
        source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in source_paths}
        with tempfile.TemporaryDirectory(prefix="task53-g5t-transform-", dir=str(tmp_root)) as scratch:
            sandbox_root = pathlib.Path(scratch)
            sandbox_module = sandbox_root / "modules" / "Capture_Arena"
            sandbox_areas = sandbox_module / "areas"
            sandbox_areas.mkdir(parents=True)
            for source_path in source_paths:
                shutil.copyfile(source_path, sandbox_areas / source_path.name)
            hashes = seed_combat_capture.transform_g5t_commander_fixtures(sandbox_module)
            self.assertEqual(set(hashes), {
                "CTR001_BU.json", "CTR001.json",
                "modules/Capture_Arena/monsters/hobgoblin_captain.json",
                "modules/Capture_Arena/monsters/goblin.json",
            })
            for area_name in ("CTR001_BU.json", "CTR001.json"):
                payload = json.loads((sandbox_areas / area_name).read_text(encoding="utf-8"))
                ca02 = next(row for row in payload["locations"] if row["locationId"] == "CA02")
                features = [row for row in ca02["tacticalFeatures"]
                            if row.get("featureId") == fixtures.G5T_TRAINING_PIT_FEATURE_ID]
                self.assertEqual(len(features), 1)
                self.assertEqual(features[0]["coverType"], "half")
            goblin = json.loads((sandbox_module / "monsters" / "goblin.json").read_text(
                encoding="utf-8"))
            self.assertEqual(goblin["multiattack"], [{"action": "Shortbow", "count": 1}])
            shortbow = next(action for action in goblin["actions"]
                            if action["name"] == "Shortbow")
            self.assertEqual(shortbow["attackType"], "ranged")
            self.assertEqual(shortbow["range"], {"normal": 80, "long": 320})
            captain = json.loads((sandbox_module / "monsters" /
                                  "hobgoblin_captain.json").read_text(
                                      encoding="utf-8"))
            self.assertEqual(
                captain["multiattack"], [{"action": "Javelin", "count": 2}]
            )
            javelin = next(action for action in captain["actions"]
                           if action["name"] == "Javelin")
            self.assertEqual(javelin["attackType"], "ranged")
            self.assertEqual(javelin["range"], {"normal": 30, "long": 120})
            self.assertEqual({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in source_paths}, source_hashes)
            with self.assertRaisesRegex(ValueError, "below project tmp"):
                seed_combat_capture.transform_g5t_commander_fixtures(source_module)

    def test_g5t_scripted_damage_matches_declared_weapon_damage_ranges(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                rows = fixtures.build_g5t_script_steps(party_size)
                rows_by_step = {row["step"]: row for row in rows}
                checked = 0
                for damage_step in rows:
                    damage_match = re.fullmatch(
                        r"/dmg (\d+) (.+)", damage_step["input"]
                    )
                    if damage_match is None:
                        continue
                    checked += 1
                    attack_step = rows_by_step.get(damage_step.get("requires_hit_step"))
                    self.assertIsNotNone(attack_step, damage_step)
                    self.assertEqual(attack_step["character"], damage_step["character"])
                    attack_match = re.fullmatch(
                        r"/att (.+) (\d+) (.+)", attack_step["input"]
                    )
                    self.assertIsNotNone(attack_match, attack_step["input"])
                    weapon_name = attack_match.group(3)
                    character = fixtures.build_capture_character_payload(
                        attack_step["character"], 20
                    )
                    weapons = [item for item in character.get("equipment", [])
                               if str(item.get("item_name", "")).casefold() ==
                               weapon_name.casefold()]
                    self.assertEqual(len(weapons), 1, weapon_name)
                    damage_text = weapons[0].get("damage")
                    weapon_damage = re.fullmatch(
                        r"\s*(\d+)d(\d+)([+-]\d+)?\s+.+\s*",
                        str(damage_text),
                    )
                    self.assertIsNotNone(weapon_damage, damage_text)
                    dice_count = int(weapon_damage.group(1))
                    die_sides = int(weapon_damage.group(2))
                    modifier = int(weapon_damage.group(3) or 0)
                    minimum = dice_count + modifier
                    maximum = dice_count * die_sides + modifier
                    amount = int(damage_match.group(1))
                    self.assertGreaterEqual(amount, minimum, damage_step["input"])
                    self.assertLessEqual(amount, maximum, damage_step["input"])
                self.assertGreater(checked, 0)

    def test_g5t_scripted_hp_trajectory_preserves_choices_and_finishes_both_branches(self):
        captain_name = fixtures.G5T_COMMANDER_NAME
        goblin_a, goblin_b = fixtures.G5T_GOBLIN_NAMES
        maximum_hp = {captain_name: 39, goblin_a: 7, goblin_b: 7}
        late_near_death_round = {1: 6, 4: 4}

        for party_size in (1, 4):
            fixture = fixtures.build_g5t_commander_fixture(party_size)
            enemies = {row["name"]: row for row in fixture["encounter"]["creatures"]
                       if row.get("type") == "enemy"}
            self.assertEqual(enemies[captain_name]["currentHitPoints"], 39)
            self.assertEqual(enemies[goblin_a]["currentHitPoints"], 7)
            self.assertEqual(enemies[goblin_b]["currentHitPoints"], 7)
            self.assertEqual(enemies[goblin_b]["coverFeatureId"],
                             fixtures.G5T_TRAINING_PIT_FEATURE_ID)
            self.assertEqual(enemies[goblin_b]["coverType"], "half")

        def make_snapshot(captain_hp, goblin_a_hp, goblin_b_hp, *, flee=(),
                          surrender=(), side_surrender=False):
            return {
                "hp": {
                    captain_name: captain_hp,
                    goblin_a: goblin_a_hp,
                    goblin_b: goblin_b_hp,
                },
                "legal": {
                    "flee": tuple(flee),
                    "individual_surrender": tuple(surrender),
                    "side_surrender": side_surrender,
                },
            }

        no_options = make_snapshot(39, 7, 7)["legal"]
        expected = {
            1: {
                False: {
                    1: make_snapshot(39, 7, 7),
                    2: make_snapshot(39, 3, 7, flee=(goblin_a,)),
                    3: make_snapshot(39, 0, 3, flee=(goblin_b,)),
                    4: make_snapshot(23, 0, 3, flee=(goblin_b,)),
                    5: make_snapshot(20, 0, 0),
                    6: make_snapshot(9, 0, 0, flee=(captain_name,),
                                      surrender=(captain_name,),
                                      side_surrender=True),
                    7: make_snapshot(0, 0, 0),
                },
                True: {
                    1: make_snapshot(39, 7, 7),
                    2: make_snapshot(39, 3, 3, flee=(goblin_a, goblin_b)),
                    3: make_snapshot(39, 0, 0),
                    4: make_snapshot(23, 0, 0),
                    5: make_snapshot(20, 0, 0),
                    6: make_snapshot(9, 0, 0, flee=(captain_name,),
                                      surrender=(captain_name,),
                                      side_surrender=True),
                    7: make_snapshot(0, 0, 0),
                },
            },
            4: {
                False: {
                    1: make_snapshot(39, 7, 7),
                    2: make_snapshot(30, 7, 7),
                    3: make_snapshot(21, 3, 3, flee=(goblin_a, goblin_b)),
                    4: make_snapshot(9, 3, 0, flee=(captain_name, goblin_a),
                                      surrender=(captain_name,), side_surrender=True),
                    5: make_snapshot(9, 0, 0, flee=(captain_name,),
                                      surrender=(captain_name,), side_surrender=True),
                    6: make_snapshot(0, 0, 0),
                },
                True: {
                    1: make_snapshot(39, 7, 7),
                    2: make_snapshot(30, 7, 3, flee=(goblin_b,)),
                    3: make_snapshot(21, 3, 0, flee=(goblin_a,)),
                    4: make_snapshot(9, 3, 0, flee=(captain_name, goblin_a),
                                      surrender=(captain_name,), side_surrender=True),
                    5: make_snapshot(9, 0, 0, flee=(captain_name,),
                                      surrender=(captain_name,), side_surrender=True),
                    6: make_snapshot(0, 0, 0),
                },
            },
        }

        def simulate(party_size, covered_attack_hits):
            rows = fixtures.build_g5t_script_steps(party_size)
            hp = {captain_name: 39, goblin_a: 7, goblin_b: 7}
            rows_by_step = {row["step"]: row for row in rows}
            covered_attack_step = next(
                row["step"] for row in rows
                if "covered-target" in row["label"]
            )
            hit_by_step = {}
            end_snapshots = {}
            for row in rows:
                command = row["input"]
                if row["unit_type"] == "batch":
                    flee = tuple(name for name in (captain_name, goblin_a, goblin_b)
                                 if 0 < hp[name] * 2 <= maximum_hp[name])
                    surrender = tuple(name for name in (captain_name, goblin_a, goblin_b)
                                      if 0 < hp[name] * 4 <= maximum_hp[name])
                    end_snapshots[row["round"]] = make_snapshot(
                        hp[captain_name], hp[goblin_a], hp[goblin_b],
                        flee=flee, surrender=surrender,
                        side_surrender=hp[captain_name] > 0 and bool(surrender),
                    )
                    continue
                attack_match = re.fullmatch(r"/att (.+) (\d+) (.+)", command)
                if attack_match is not None:
                    target = attack_match.group(1)
                    roll = int(attack_match.group(2))
                    target_alive = target in hp and hp[target] > 0
                    if row["step"] == covered_attack_step:
                        hit = covered_attack_hits
                    else:
                        hit = roll == 19
                    hit_by_step[row["step"]] = target_alive and hit
                    continue
                damage_match = re.fullmatch(r"/dmg (\d+) (.+)", command)
                if damage_match is None:
                    continue
                attack_step = row["requires_hit_step"]
                attack_row = rows_by_step[attack_step]
                target = damage_match.group(2)
                self.assertEqual(target, re.fullmatch(
                    r"/att (.+) (\d+) (.+)", attack_row["input"]
                ).group(1))
                if hit_by_step.get(attack_step, False) and hp[target] > 0:
                    hp[target] = max(0, hp[target] - int(damage_match.group(1)))
            return end_snapshots, hp

        for party_size in (1, 4):
            for covered_attack_hits in (False, True):
                with self.subTest(party_size=party_size,
                                  covered_attack_hits=covered_attack_hits):
                    snapshots, final_hp = simulate(party_size, covered_attack_hits)
                    self.assertEqual(snapshots, expected[party_size][covered_attack_hits])
                    self.assertEqual(snapshots[1]["legal"], no_options)
                    bloodied_round = 2 if party_size == 1 else 3
                    self.assertTrue(any(
                        0 < snapshots[bloodied_round]["hp"][name] * 2
                        <= maximum_hp[name]
                        and snapshots[bloodied_round]["hp"][name] * 4
                        > maximum_hp[name]
                        for name in (goblin_a, goblin_b)
                    ))
                    late_round = late_near_death_round[party_size]
                    for round_number, state in snapshots.items():
                        if round_number >= late_round:
                            continue
                        self.assertFalse(any(
                            0 < state["hp"][name] * 4 <= maximum_hp[name]
                            for name in maximum_hp
                        ), "near-death state appeared at early /end r%d: %r" %
                             (round_number, state))
                    late_state = snapshots[late_round]
                    self.assertEqual(late_state["hp"][captain_name], 9)
                    self.assertEqual(late_state["legal"]["individual_surrender"],
                                     (captain_name,))
                    self.assertTrue(late_state["legal"]["side_surrender"])
                    if party_size == 4:
                        second_chance = snapshots[5]
                        self.assertEqual(second_chance["hp"][captain_name], 9)
                        self.assertEqual(second_chance["hp"][goblin_a], 0)
                        self.assertEqual(second_chance["hp"][goblin_b], 0)
                        self.assertEqual(
                            second_chance["legal"]["individual_surrender"],
                            (captain_name,),
                        )
                        self.assertTrue(second_chance["legal"]["side_surrender"])
                    rows = fixtures.build_g5t_script_steps(party_size)
                    covered_attack = next(row for row in rows
                                          if "covered-target" in row["label"])
                    late_end = next(row for row in rows
                                    if row["unit_type"] == "batch"
                                    and row["round"] == late_round)
                    self.assertGreaterEqual(sum(
                        row["unit_type"] == "batch"
                        and covered_attack["step"] < row["step"] < late_end["step"]
                        for row in rows
                    ), 1)
                    for row in rows:
                        match = re.fullmatch(r"/att (.+) (\d+) (.+)", row["input"])
                        if match is None:
                            continue
                        expected_roll = 1 if "miss" in row["label"] else 19
                        self.assertEqual(int(match.group(2)), expected_roll, row["label"])
                    self.assertEqual(final_hp, {captain_name: 0, goblin_a: 0, goblin_b: 0})

    def test_g5t_driver_skips_damage_after_covered_attack_miss_and_keeps_receipt(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile(
                    "g5t", "g5t-commander-p%d" % party_size, party_size)
                args = SimpleNamespace(
                    url="http://localhost:8360", party=party_size,
                    transcript="tmp/router-rollout/g5t/driver-script-test.log",
                    trace_src="tmp/no-trace.jsonl", trace_dst=None,
                    start_timeout=0.2, turn_timeout=0.2, turn_quiet_seconds=0.001,
                    settle_seconds=0, init_roll=15, scenario=profile["scenario_id"],
                    branch=None, phase=None, state_root=None,
                )
                session = capture_drive.CaptureSession(args, socket_client=object())
                session.capture_gate = "g5t"
                session.capture_profile = profile
                session._g5t_combat_is_over = lambda: False
                session._g5t_target_is_inactive = lambda _target: False
                sent = []

                def fake_send_turn(label, text, character, *, fixture_step=None,
                                   allow_canonical_exit_completion=False):
                    del allow_canonical_exit_completion
                    sent.append((fixture_step["step"], text, character))
                    unit = {"type": fixture_step["unit_type"],
                            "id": fixture_step["unit_id"],
                            "round": fixture_step["round"]}
                    session.g5_step_receipts.append({
                        "step": fixture_step["step"],
                        "script_step": fixture_step["step"],
                        "status": "sent", "work_unit": unit,
                        "work_only_ms": 1.0,
                        "trace_window": {"start_epoch_ms": 1.0, "end_epoch_ms": 2.0},
                    })
                    if text.casefold().startswith("/att "):
                        attack_match = re.fullmatch(r"/att (.+) (\d+) (.+)", text)
                        rolled_value = int(attack_match.group(2))
                        output = (
                            "Miss. (Rolled 19 vs AC 20)"
                            if fixture_step["step"] == 2 else
                            "Miss. (Rolled 1 vs AC 15)"
                            if rolled_value == 1
                            else "Hit! (Rolled %d vs AC 15)" % rolled_value
                        )
                        session.game_outputs.append({
                            "payload": {"type": "narration", "content": output},
                            "label": label,
                        })

                session.send_turn = fake_send_turn
                session.run_g5t_scenario(profile)
                self.assertEqual(sent[0][1], "/end")
                self.assertNotIn(
                    3, {step for step, _text, _character in sent}
                )
                sent_steps = {step: (text, character)
                              for step, text, character in sent}
                second_attack_step = 4
                second_damage_step = second_attack_step + 1
                self.assertEqual(
                    sent_steps[second_attack_step],
                    (("/att Goblin Squad B 1 training blade", "Acheron")
                     if party_size == 4 else
                     ("/att Goblin Squad A 19 training blade", "Acheron")),
                )
                if party_size == 1:
                    self.assertEqual(sent_steps[second_damage_step],
                                     ("/dmg 4 Goblin Squad A", "Acheron"))
                else:
                    self.assertNotIn(second_damage_step, sent_steps)
                    self.assertIn(13, sent_steps)
                    self.assertEqual(sent_steps[14],
                                     ("/dmg 4 Goblin Squad A", "Acheron"))
                skipped = [row for row in session.g5_step_receipts
                           if row.get("skip_reason") == "attack_missed"]
                expected_skipped_steps = {3} if party_size == 1 else {3, 5}
                self.assertEqual(
                    {row["script_step"] for row in skipped}, expected_skipped_steps
                )
                covered_damage_receipt = next(
                    row for row in skipped if row["script_step"] == 3
                )
                self.assertIsNone(covered_damage_receipt["work_only_ms"])
                self.assertEqual(len(session.g5_step_receipts), len(
                    fixtures.build_g5t_script_steps(party_size)))

    def test_g5t_closing_batch_is_sent_when_all_script_targets_are_inactive(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile(
                    "g5t", "g5t-commander-p%d" % party_size, party_size)
                args = SimpleNamespace(
                    url="http://localhost:8360", party=party_size,
                    transcript="tmp/router-rollout/g5t/closing-step-test.log",
                    trace_src="tmp/no-trace.jsonl", trace_dst=None,
                    start_timeout=0.2, turn_timeout=0.2, turn_quiet_seconds=0.001,
                    settle_seconds=0, init_roll=15, scenario=profile["scenario_id"],
                    branch=None, phase=None, state_root=None,
                )
                session = capture_drive.CaptureSession(args, socket_client=object())
                session.capture_gate = "g5t"
                session.capture_profile = profile
                session._g5t_combat_is_over = lambda: False
                session._g5t_target_is_inactive = lambda _target: True
                sent = []

                def fake_send_turn(label, text, character, *, fixture_step=None,
                                   allow_canonical_exit_completion=False):
                    del label, allow_canonical_exit_completion
                    sent.append(fixture_step["step"])
                    session.g5_step_receipts.append({
                        "step": fixture_step["step"],
                        "script_step": fixture_step["step"],
                        "status": "sent",
                        "work_unit": {"type": fixture_step["unit_type"],
                                      "id": fixture_step["unit_id"],
                                      "round": fixture_step["round"]},
                    })

                session.send_turn = fake_send_turn
                session.run_g5t_scenario(profile)
                closing_step = fixtures.build_g5t_script_steps(party_size)[-1]
                self.assertIn(closing_step["step"], sent)
                self.assertEqual(sent[-1], closing_step["step"])
                closing_receipt = next(
                    row for row in session.g5_step_receipts
                    if row.get("script_step") == closing_step["step"]
                )
                self.assertEqual(closing_receipt["status"], "sent")

    def test_g5t_closing_batch_skips_cleanly_after_earlier_exit(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile(
                    "g5t", "g5t-commander-p%d" % party_size, party_size)
                args = SimpleNamespace(
                    url="http://localhost:8360", party=party_size,
                    transcript="tmp/router-rollout/g5t/closing-skip-test.log",
                    trace_src="tmp/no-trace.jsonl", trace_dst=None,
                    start_timeout=0.2, turn_timeout=0.2, turn_quiet_seconds=0.001,
                    settle_seconds=0, init_roll=15, scenario=profile["scenario_id"],
                    branch=None, phase=None, state_root=None,
                )
                session = capture_drive.CaptureSession(args, socket_client=object())
                session.capture_gate = "g5t"
                session.capture_profile = profile
                session._g5t_combat_is_over = lambda: session._g5t_exit_marker_seen
                session._g5t_target_is_inactive = lambda _target: False
                sent = []
                earlier_exit_round = 2

                def fake_send_turn(label, text, character, *, fixture_step=None,
                                   allow_canonical_exit_completion=False):
                    del label, text, character, allow_canonical_exit_completion
                    sent.append(fixture_step["step"])
                    if (fixture_step["unit_type"] == "batch" and
                            fixture_step["round"] == earlier_exit_round):
                        session._g5t_exit_marker_seen = True

                session.send_turn = fake_send_turn
                session.run_g5t_scenario(profile)
                closing_step = fixtures.build_g5t_script_steps(party_size)[-1]
                self.assertNotIn(closing_step["step"], sent)
                closing_receipt = next(
                    row for row in session.g5_step_receipts
                    if row.get("script_step") == closing_step["step"]
                )
                self.assertEqual(closing_receipt["status"], "skipped")
                self.assertEqual(closing_receipt["skip_reason"], "combat_ended")

    def test_g5t_run_root_and_three_run_cli_selection_are_isolated(self):
        root = capture_evidence.G5T_RUN_ROOT
        root_was_present = root.exists()
        root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="task53-g5t-cli-", dir=str(root)) as scratch:
                sandbox = ROOT / "tmp" / ("task53-g5t-state-" + uuid.uuid4().hex)
                sandbox.mkdir(parents=True)
                self.addCleanup(lambda path=sandbox: shutil.rmtree(path) if path.exists() else None)
                run_dir = root / ("task53-g5t-new-" + uuid.uuid4().hex)
                validated_run, validated_state = capture_evidence.validate_evidence_paths(
                    run_dir, sandbox, "g5t")
                self.assertEqual(validated_run, run_dir)
                self.assertEqual(validated_state, sandbox.resolve())
                rejected_paths = (
                    capture_evidence.RUN_ROOT / "g5t-wrong-g3",
                    capture_evidence.G4_RUN_ROOT / "g5t-wrong-g4",
                    capture_evidence.G5_RUN_ROOT / "g5t-wrong-g5",
                    capture_evidence.G5R_RUN_ROOT / "g5t-wrong-g5r",
                    root / ".." / "g5r" / "g5t-traversal",
                    ROOT / "outside-project" / "router-rollout" / "g5t" / "run",
                )
                for rejected in rejected_paths:
                    with self.subTest(path=str(rejected)), self.assertRaises(ValueError):
                        capture_evidence.validate_evidence_paths(rejected, sandbox, "g5t")

                after_paths = []
                for party_size in (1, 4):
                    for index in range(3):
                        run_id = "task53-p%d-run-%d" % (party_size, index + 1)
                        bundle = pathlib.Path(scratch) / run_id
                        bundle.mkdir()
                        manifest = {"gate": "g5t", "run_id": run_id,
                                    "party": {"size": party_size},
                                    "scenario": {"id": "g5t-commander-p%d" % party_size}}
                        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
                        after_paths.append(bundle)
                grouped_after, rejected_after = capture_evidence._group_g5t_after_runs(after_paths)
                self.assertEqual(rejected_after, [])
                self.assertEqual({party: len(runs) for party, runs in grouped_after.items()},
                                 {1: 3, 4: 3})

                output, table = io.StringIO(), io.StringIO()
                report = {"automated_status": "READY_FOR_PRIMARY_REVIEW", "gate": "g5t"}
                argv = ["--gate", "g5t"]
                for bundle in after_paths:
                    argv.extend(("--after", str(bundle)))
                active_report_module = importlib.import_module("scripts.combat_latency_report")
                with patch.object(active_report_module, "evaluate_g5t_comparison",
                                  return_value=report) as evaluator, \
                        patch.object(active_report_module, "render_g5t_comparison",
                                     return_value="G5T comparison rendered") as renderer, \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(table):
                    status = capture_evidence.main(argv)
                self.assertEqual(status, 0, msg=output.getvalue() + "\n" + table.getvalue())
                self.assertEqual(json.loads(output.getvalue()), report)
                self.assertEqual(table.getvalue().strip(), "G5T comparison rendered")
                grouped = evaluator.call_args.args[0]
                kwargs = evaluator.call_args.kwargs
                self.assertEqual({party: len(runs) for party, runs in grouped.items()},
                                 {1: 3, 4: 3})
                self.assertEqual(kwargs, {"run_root": root})
                renderer.assert_called_once_with(report)

                for extra_args, reason in (
                        (["--run-dir", str(after_paths[0])],
                         "g5t_requires_explicit_before_and_after_roles"),
                        (["--before", str(after_paths[0])],
                         "g5t_primary_accepts_after_runs_only")):
                    rejected_output = io.StringIO()
                    with patch.object(active_report_module, "evaluate_g5t_comparison",
                                      return_value=report), \
                            patch.object(active_report_module, "render_g5t_comparison",
                                         return_value="blocked"), \
                            contextlib.redirect_stdout(rejected_output), \
                            contextlib.redirect_stderr(io.StringIO()):
                        rejected_status = capture_evidence.main(["--gate", "g5t"] + extra_args)
                    self.assertEqual(rejected_status, 2)
                    self.assertIn(reason, json.loads(rejected_output.getvalue())["blocking_reasons"])
        finally:
            if not root_was_present:
                try:
                    root.rmdir()
                except OSError:
                    pass

    def test_fake_driver_preserves_g4_bundles_and_g5_rejects_foreign_receipt_run_ids(self):
        from utils import combat_latency_trace
        import model_config as runtime_model_config

        narrator_turns = fixtures.G4_NARRATOR_TURNS

        def run_case(scenario, party, *, break_room=False, gate="g4", final_trace_positions=None):
            scratch = tempfile.TemporaryDirectory(prefix="g4-driver-unit-state-", dir="tmp")
            self.addCleanup(scratch.cleanup)
            state = pathlib.Path(scratch.name)
            (state / "debug").mkdir()
            (state / "modules" / "encounters").mkdir(parents=True)
            (state / "modules" / "conversation_history").mkdir(parents=True)
            (state / "save_games").mkdir()
            (state / "model_config.py").write_text("ENABLE_COMBAT_TURN_TRACE = True\n", encoding="ascii")
            (state / "server.log").write_text("synthetic unit server log\n", encoding="ascii")
            roster = ["Acheron"] if party == 1 else list(fixtures.PC_NAMES)
            encounter_id = "" if scenario == "narrator-dialogue-travel" else (
                "capture_one_pc" if party == 1 else "capture_mp")
            enemy_names = [] if not encounter_id else (["Goblin"] if party == 1 else ["Goblin Alpha", "Goblin Beta"])
            tracker = {"partyMembers": roster, "active_character": roster[0], "module": "Capture_Arena",
                       "worldConditions": {"currentLocation": "Waystone Gate", "currentLocationId": "CA01",
                                           "currentArea": "Capture Arena", "currentAreaId": "CTR001",
                                           "activeCombatEncounter": encounter_id}}
            tracker_path = state / "party_tracker.json"
            tracker_path.write_text(json.dumps(tracker), encoding="ascii")
            (state / "debug" / "combat_turn_trace.jsonl").write_text("", encoding="ascii")
            for name in roster:
                (state / "characters").mkdir(exist_ok=True)
                (state / "characters" / (name.lower() + ".json")).write_text(
                    json.dumps({"name": name, "type": "player", "hitPoints": 20,
                                "maxHitPoints": 20, "status": "alive"}), encoding="ascii")
            if encounter_id:
                creatures = [{"name": name, "type": "enemy", "currentHitPoints": 20,
                              "maxHitPoints": 20, "status": "alive"} for name in enemy_names]
                (state / "modules" / "encounters" / ("encounter_%s.json" % encounter_id)).write_text(
                    json.dumps({"encounterId": encounter_id, "creatures": creatures}), encoding="ascii")

            run_dir = pathlib.Path("tmp/router-rollout") / gate / ("unit-" + uuid.uuid4().hex)
            trace_path = state / "debug" / "combat_turn_trace.jsonl"

            class Response:
                status_code = 200
                def __init__(self, body): self.body = body
                def json(self): return self.body

            class ScriptedSocket:
                def __init__(self):
                    self.handlers = {}
                    self.emitted = []
                    self.regular_combat_inputs = 0
                    self.synthetic_attempt = 0
                def on(self, event, callback): self.handlers[event] = callback
                def connect(self, _url, **_kwargs): pass
                def disconnect(self): pass
                def receipt(self, task):
                    self.synthetic_attempt += 1
                    combat_latency_trace.emit_trace_event(
                        "provider", path=trace_path,
                        site=("main_dm" if task == "dm_main" else
                              "main_validation" if task == "dm_validation" else
                              "combat_validation" if task == "combat_validation" else "combat_main"),
                        call_id="synthetic-call-%d" % self.synthetic_attempt,
                        attempt_id="synthetic-attempt-%d" % self.synthetic_attempt,
                        attempt_number=1, task=task,
                        provider="openai", observed_upstream_provider="openai",
                        model="synthetic-resolved-model", requested_model="synthetic-requested-model",
                        resolved_model="synthetic-resolved-model", retry=False, retry_tier=None,
                        fallback=False, prompt_tokens=10, cached_tokens=0, completion_tokens=2,
                        provider_reported_cost_usd=0.0, cost_usd=0.0, cost_provenance="actual",
                        cost_complete=True, usage_complete=True, usage_available=True, outcome="response",
                    )
                def emit(self, event, data=None):
                    self.emitted.append((event, data))
                    if event == "start_game":
                        self.receipt("dm_main" if scenario == "narrator-dialogue-travel" else "combat_main")
                        if scenario == "combat-smoke":
                            combat_latency_trace.emit_trace_event(
                                "provider", path=trace_path, site="combat_compression",
                                elapsed_ms=4.0, prompt_tokens=10, completion_tokens=3,
                                total_tokens=13,
                            )
                        self.handlers["game_output"]({"type": "system", "content": "session ready"})
                        self.handlers["status_update"]({"is_processing": False, "message": "ready"})
                    elif event == "user_input":
                        value = data["input"]
                        if scenario == "narrator-dialogue-travel" or not value.lstrip().startswith(("/att", "/dmg")):
                            self.receipt("dm_main" if scenario == "narrator-dialogue-travel" else "combat_main")
                        if scenario == "narrator-dialogue-travel":
                            step_index = next((i for i, row in enumerate(narrator_turns, 1)
                                               if row[1] == value), None)
                            if step_index:
                                expected = narrator_turns[step_index - 1][4]
                                room_names = {"CA01": "Waystone Gate", "CA02": "Training Pit",
                                              "CA03": "Reliquary Alcove"}
                                if not (break_room and step_index == 2):
                                    current = json.loads(tracker_path.read_text(encoding="ascii"))
                                    current["worldConditions"]["currentLocationId"] = expected
                                    current["worldConditions"]["currentLocation"] = room_names[expected]
                                    tracker_path.write_text(json.dumps(current), encoding="ascii")
                        elif value != "/end":
                            self.regular_combat_inputs += 1

                        self.handlers["game_output"]({"type": "user-input", "author": data.get("character"),
                                                       "content": value})
                        backend = "Warden Mira answers the shrine question." if "Warden Mira" in value or "shrine" in value else "Synthetic backend reply."
                        if scenario == "combat-smoke" and party == 4 and self.regular_combat_inputs in (6, 12, 18):
                            backend += " PC phase complete: true; current phase: enemy_phase; await /end."
                        self.handlers["game_output"]({"type": "narration", "content": backend})
                        self.handlers["status_update"]({"is_processing": False, "message": "idle"})

            def post_active(_url, *, json, **_kwargs):
                current = pathlib.Path(tracker_path).read_text(encoding="ascii")
                saved = __import__("json").loads(current)
                saved["active_character"] = json["character"]
                tracker_path.write_text(__import__("json").dumps(saved), encoding="ascii")
                return FakeResponse()

            def get_party(_url, **_kwargs):
                saved = json.loads(tracker_path.read_text(encoding="ascii"))
                return FakeHealthResponse(saved["partyMembers"])

            argv = ["--gate", gate, "--scenario", scenario, "--party", str(party),
                    "--run-dir", run_dir.as_posix(), "--state-root", state.as_posix(),
                    "--trace-src", (state / "debug" / "combat_turn_trace.jsonl").as_posix(),
                    "--server-log", (state / "server.log").as_posix(), "--turn-quiet-seconds", "0.001"]
            args = capture_drive.build_parser().parse_args(argv)
            socket_client = ScriptedSocket()
            try:
                with patch.object(runtime_model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                     contextlib.redirect_stdout(io.StringIO()):
                    if final_trace_positions is None:
                        result = capture_drive.run(args, socket_factory=lambda: socket_client,
                                                   http_post=post_active, http_get=get_party)
                    else:
                        with patch.object(capture_evidence, "parse_trace_positions",
                                          return_value=(copy.deepcopy(final_trace_positions), [])):
                            result = capture_drive.run(args, socket_factory=lambda: socket_client,
                                                       http_post=post_active, http_get=get_party)
                return result, run_dir, socket_client, party
            except BaseException:
                if run_dir.exists():
                    shutil.rmtree(run_dir)
                raise

        cases = (("narrator-dialogue-travel", 1), ("narrator-dialogue-travel", 4),
                 ("combat-smoke", 1), ("combat-smoke", 4))
        matrix_bundles = []
        for scenario, party in cases:
            with self.subTest(scenario=scenario, party=party):
                result, run_dir, socket_client, expected_party = run_case(scenario, party)
                self.addCleanup(lambda path=run_dir: shutil.rmtree(path) if path.exists() else None)
                self.assertEqual(result, capture_drive.EXIT_OK)
                matrix_bundles.append(run_dir)
                manifest = json.loads((run_dir / "manifest.json").read_text(encoding="ascii"))
                self.assertEqual(manifest["evidence_kind"], "synthetic")
                self.assertFalse(manifest["live_eligible"])
                self.assertEqual(manifest["party"]["roster"],
                                 ["Acheron"] if expected_party == 1 else list(fixtures.PC_NAMES))
                self.assertLessEqual(manifest["counts"]["health_read_attempts"], 3)
                expected_steps = 5 if scenario == "narrator-dialogue-travel" else (4 if party == 1 else 21)
                expected_max_inputs = (6 if scenario == "narrator-dialogue-travel" else (5 if party == 1 else 22))
                expected_max_controls = ((8 if party == 1 else 9) if scenario == "narrator-dialogue-travel"
                                         else (7 if party == 1 else 35))
                self.assertEqual(manifest["counts"]["steps_sent"], expected_steps)
                self.assertEqual(manifest["bounds"]["max_inputs"], expected_max_inputs)
                self.assertEqual(manifest["bounds"]["max_controls"], expected_max_controls)
                self.assertEqual(manifest["bounds"]["turn_timeout_seconds"], 300)
                self.assertLessEqual(manifest["counts"]["steps_sent"], manifest["bounds"]["max_inputs"])
                self.assertLessEqual(manifest["counts"]["control_requests_sent"], manifest["bounds"]["max_controls"])
                self.assertTrue(manifest["source"]["head"])
                self.assertEqual(manifest["receipt_projection"]["status"], "ok")
                self.assertTrue(manifest["receipt_projection"]["receipts"])
                if scenario == "combat-smoke":
                    self.assertEqual(manifest["counts"]["provider_calls"], {
                        "count": len(manifest["receipt_projection"]["receipts"]) + 1,
                        "source": "runtime-trace",
                        "core_receipts": len(manifest["receipt_projection"]["receipts"]),
                        "legacy_provider_observations": 1,
                    })
                    legacy_rows = manifest["receipt_projection"]["legacy_observations"]
                    self.assertEqual(len(legacy_rows), 1)
                    self.assertEqual(legacy_rows[0]["step"], "startup")
                    self.assertEqual(legacy_rows[0]["observation"]["site"], "combat_compression")
                    self.assertEqual(legacy_rows[0]["observation"]["provider"], "unknown")
                    self.assertEqual(legacy_rows[0]["observation"]["model"], "unknown")
                    self.assertEqual(legacy_rows[0]["observation"]["cost"], "unknown")
                    self.assertNotIn("call_id", legacy_rows[0]["observation"])
                for required in ("transcript", "server_log", "trace", "report", "checks",
                                 "before_snapshot", "after_snapshot"):
                    reference = manifest["artifacts"].get(required)
                    self.assertTrue(reference, required)
                    self.assertTrue((run_dir / reference).is_file(), required)
                if scenario == "narrator-dialogue-travel":
                    self.assertEqual(len(manifest["g4_step_projections"]), 5)
                    self.assertEqual([row["projection"]["status"] for row in manifest["g4_step_projections"]],
                                     ["PASS"] * 5)
                    self.assertEqual([row["projection"]["observed"]["currentLocationId"]
                                      for row in manifest["g4_step_projections"]],
                                     ["CA02", "CA03", "CA03", "CA02", "CA01"])
                    self.assertEqual(manifest["g4_startup_trace_span"]["status"], "captured")
                    first_before = json.loads((run_dir / "snapshots" / "step-001-before.json").read_text(
                        encoding="ascii"))
                    self.assertEqual(first_before["g4_read_only_projection"]["currentLocationId"], "CA01")
                    self.assertTrue(any("Warden Mira" in row["content"]
                                        for row in manifest["g4_step_projections"][2]["actual_backend_outputs"]))
                else:
                    before = json.loads((run_dir / "snapshots" / "before-run.json").read_text(encoding="ascii"))
                    encounter = before["records"]["selected_encounter"]
                    self.assertEqual(encounter["encounterId"], "capture_one_pc" if party == 1 else "capture_mp")
                    self.assertEqual([row["name"] for row in encounter["creatures"] if row["type"] == "enemy"],
                                     ["Goblin"] if party == 1 else ["Goblin Alpha", "Goblin Beta"])

        # Driver-generated bundles are intentionally synthetic: the G4 offline
        # evaluator must derive all four identities but never promote fake
        # transport/state evidence to a live-review candidate.
        matrix = capture_evidence.evaluate_g4_matrix(matrix_bundles)
        self.assertEqual(matrix["observed_keys"], sorted(capture_evidence.G4_REQUIRED_KEYS))
        self.assertEqual(matrix["missing_required_keys"], [])
        self.assertEqual(matrix["automated_status"], "BLOCKED")
        self.assertEqual(len(matrix["not_ready_keys"]), 4)
        self.assertTrue(all({"synthetic_or_ineligible_evidence", "synthetic_transport"}.issubset(
            set(row["problems"])) for row in matrix["runs"].values()),
            {key: row["problems"] for key, row in matrix["runs"].items()})
        self.assertFalse(any("narrator_combat_checks_not_marked_not_applicable" in row["problems"]
                             for row in matrix["runs"].values()))
        for path in matrix_bundles[:2]:
            saved_checks = json.loads((path / "checks.json").read_text(encoding="ascii"))["checks"]
            by_id = {row["id"]: row for row in saved_checks}
            self.assertEqual(by_id["selected_encounter_available"]["status"], "N/A")
            self.assertIs(by_id["selected_encounter_available"]["required"], False)
            self.assertEqual(by_id["g4_narrator_route_and_actor_observations"]["status"], "PASS")
            self.assertEqual(by_id["g4_narrator_mira_backend_response"]["status"], "PASS")
        self.assertFalse(any(any(problem.startswith("narrator_input_echo_transcript_mismatch:")
                                 for problem in row["problems"])
                             for key, row in matrix["runs"].items()
                             if key.startswith("narrator-dialogue-travel:")))
        self.assertTrue(all(any(row["step"] == "startup" for row in
                                item["receipt_projection"]["receipts"])
                            for item in (json.loads((path / "manifest.json").read_text(encoding="ascii"))
                                         for path in matrix_bundles)))

        # The G5 capture path must bind legacy observations to the manifest run,
        # not infer trust from a self-consistent but foreign trace run_id.
        foreign_positions = [
            {"event_type": "provider", "site": "combat_main", "call_id": "core-call",
             "attempt_id": "core-attempt", "attempt_number": 1, "task": "combat_main",
             "provider": "openai", "requested_model": "requested-model",
             "resolved_model": "resolved-model", "retry": False, "retry_tier": None,
             "fallback": False, "usage_available": True, "usage_complete": True,
             "prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 5,
             "provider_reported_cost_usd": 0.0, "cost_usd": 0.0,
             "cost_provenance": "actual", "cost_complete": True,
             "_source_byte_start": 1, "_source_byte_end": 20},
            {"event_type": "provider", "schema_version": 1, "site": "combat_compression",
             "mode": "mp", "combat_round": 1, "phase": "PC_PHASE",
             "run_id": "foreign-g5-run", "action_id": "pc:r1:acheron",
             "elapsed_ms": 4.0, "prompt_tokens": 10, "completion_tokens": 3,
             "total_tokens": 13, "recorded_at_ms": 1234,
             "_source_byte_start": 20, "_source_byte_end": 40},
        ]
        self.assertEqual(capture_evidence.project_g4_receipts(foreign_positions)["status"], "ok")
        foreign_result, foreign_run_dir, _socket_client, _party = run_case(
            "combat-smoke", 1, gate="g5", final_trace_positions=foreign_positions
        )
        self.addCleanup(lambda path=foreign_run_dir: shutil.rmtree(path) if path.exists() else None)
        self.assertEqual(foreign_result, capture_drive.EXIT_OK)
        foreign_manifest = json.loads((foreign_run_dir / "manifest.json").read_text(encoding="ascii"))
        self.assertNotEqual(foreign_manifest["run_id"], "foreign-g5-run")
        self.assertEqual(foreign_manifest["receipt_projection"]["status"], "BLOCKED")
        self.assertEqual(foreign_manifest["receipt_projection"]["reason"],
                         "invalid_legacy_compression_observation")
        missing = capture_evidence.evaluate_g4_matrix(matrix_bundles[:3])
        self.assertEqual(len(missing["missing_required_keys"]), 1)
        duplicate = capture_evidence.evaluate_g4_matrix(matrix_bundles + [matrix_bundles[0]])
        self.assertEqual(duplicate["duplicate_keys"], ["narrator-dialogue-travel:p1"])

        # Hashes and reflected projections are checked against retained bytes,
        # not manifest/check status declarations.
        target = matrix_bundles[0]
        transcript = target / "transcript.log"
        original = transcript.read_bytes()
        transcript.write_bytes(original + b"tampered\n")
        tampered = capture_evidence.evaluate_g4_matrix(matrix_bundles)
        self.assertIn("artifact_hash_or_bytes_mismatch",
                      tampered["runs"]["narrator-dialogue-travel:p1"]["problems"])
        transcript.write_bytes(original)

        manifest_path = target / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        base_manifest = json.loads(manifest_bytes.decode("ascii"))
        mutations = (
            ("wrong_seed", lambda value: value["seed"].update({"seed_id": "0" * 64}),
             "seed_identity_mismatch"),
            ("wrong_roster", lambda value: value["party"].update({"roster": ["Acheron", "Wrong PC"]}),
             "manifest_roster_identity_mismatch"),
            ("receipt_projection_tamper", lambda value: value["configuration"]["actual_runtime"].update(
                {"receipts": [{"fallback": True}]}), "receipt_manifest_projection_mismatch"),
            ("timeout", lambda value: value["counts"].update({"timeouts": 1}),
             "timeout_or_cap_observed"),
            ("over_cap", lambda value: value["counts"].update({"steps_sent": 7}), "bound_exceeded"),
            ("underreported_steps", lambda value: value["counts"].update({"steps_sent": 4}),
             "count_transcript_mismatch:steps_sent"),
            ("underreported_controls", lambda value: value["counts"].update({"control_requests_sent": 0}),
             "count_transcript_mismatch:control_requests_sent"),
            ("underreported_health", lambda value: value["counts"].update({"health_read_attempts": 0}),
             "count_transcript_mismatch:health_read_attempts"),
            ("underreported_provider_calls", lambda value: value["counts"]["provider_calls"].update(
                {"count": 0}), "provider_count_trace_mismatch"),
            ("boolean_counter", lambda value: value["counts"].update({"steps_sent": True}),
             "count_invalid:steps_sent"),
            ("float_counter", lambda value: value["counts"].update({"control_requests_sent": 7.5}),
             "count_invalid:control_requests_sent"),
            ("missing_receipt_projection", lambda value: value["configuration"]["actual_runtime"].update(
                {"receipts": []}), "receipt_manifest_projection_mismatch"),
            ("wrong_room_projection", lambda value: value["g4_step_projections"][1]["projection"][
                "observed"].update({"currentLocationId": "CA04"}), "narrator_projection_mismatch:2"),
            ("mira_echo_only", lambda value: value["g4_step_projections"][2].update(
                {"actual_backend_outputs": value["g4_step_projections"][2].get("input_echoes", [])}),
             "mira_backend_reply_missing_or_echo_only"),
        )
        for label, mutate, expected_problem in mutations:
            with self.subTest(g4_negative=label):
                changed = copy.deepcopy(base_manifest)
                mutate(changed)
                manifest_path.write_text(json.dumps(changed), encoding="ascii")
                evaluation = capture_evidence.evaluate_g4_matrix(matrix_bundles)
                result_row = evaluation["runs"]["narrator-dialogue-travel:p1"]
                self.assertIn(expected_problem, result_row["problems"])
                if label not in ("missing_receipt_projection", "receipt_projection_tamper", "float_counter"):
                    self.assertEqual(result_row["automated_status"], "FAIL", label)
        manifest_path.write_bytes(manifest_bytes)

        # Forge a green manifest and saved checks while making the retained
        # projected state contradict the fixed profile. The raw evidence still
        # prevents readiness.
        step_ref = "snapshots/step-002-after.json"
        step_path = target / step_ref
        step_bytes = step_path.read_bytes()
        check_ref = base_manifest["artifacts"]["checks"]
        check_path = target / check_ref
        check_bytes = check_path.read_bytes()
        changed_step = json.loads(step_bytes.decode("ascii"))
        changed_step["g4_read_only_projection"]["currentLocationId"] = "CA04"
        step_path.write_text(json.dumps(changed_step), encoding="ascii")
        forged_checks = json.loads(check_bytes.decode("ascii"))
        for check in forged_checks.get("checks", []):
            check["status"] = "PASS"
        forged_checks["primary_verdict"] = "PASS"
        check_path.write_text(json.dumps(forged_checks), encoding="ascii")
        forged = copy.deepcopy(base_manifest)
        forged["g4_step_projections"][1]["projection"]["observed"]["currentLocationId"] = "CA04"
        forged["artifact_sha256"][step_ref] = hashlib.sha256(step_path.read_bytes()).hexdigest()
        forged["artifact_sha256"][check_ref] = hashlib.sha256(check_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(forged), encoding="ascii")
        forged_result = capture_evidence.evaluate_g4_matrix(matrix_bundles)
        forged_row = forged_result["runs"]["narrator-dialogue-travel:p1"]
        self.assertIn("narrator_projection_mismatch:2", forged_row["problems"])
        self.assertNotEqual(forged_row["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        step_path.write_bytes(step_bytes)
        check_path.write_bytes(check_bytes)
        manifest_path.write_bytes(manifest_bytes)

        # A transcript that contains only the Mira user echo cannot inherit the
        # manifest's previously observed backend reply or green checks.
        transcript_path = target / base_manifest["artifacts"]["transcript"]
        transcript_bytes = transcript_path.read_bytes()
        transcript_text = transcript_bytes.decode("utf-8")
        backend_utterance = "type=narration content=Warden Mira answers the shrine question."
        self.assertIn(backend_utterance, transcript_text)
        transcript_text = transcript_text.replace(
            backend_utterance,
            "type=user-input content=Ask Warden Mira what the three-ring shrine means.", 1)
        transcript_path.write_text(transcript_text, encoding="utf-8")
        echo_forgery = copy.deepcopy(base_manifest)
        echo_forgery["artifact_sha256"][base_manifest["artifacts"]["transcript"]] = hashlib.sha256(
            transcript_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(echo_forgery), encoding="ascii")
        echo_result = capture_evidence.evaluate_g4_matrix(matrix_bundles)
        echo_row = echo_result["runs"]["narrator-dialogue-travel:p1"]
        self.assertIn("mira_backend_reply_missing_or_echo_only", echo_row["problems"])
        self.assertNotEqual(echo_row["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        transcript_path.write_bytes(transcript_bytes)
        manifest_path.write_bytes(manifest_bytes)

        trace_relative = base_manifest["artifacts"]["trace"]
        trace_path = target / trace_relative
        trace_bytes = trace_path.read_bytes()
        changed_trace = trace_bytes.replace(b'"fallback":false', b'"fallback":true ').replace(
            b'"fallback": false', b'"fallback": true ')
        self.assertNotEqual(changed_trace, trace_bytes)
        trace_path.write_bytes(changed_trace)
        changed_manifest = copy.deepcopy(base_manifest)
        changed_manifest["artifact_sha256"][trace_relative] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(changed_manifest), encoding="ascii")
        fallback = capture_evidence.evaluate_g4_matrix(matrix_bundles)
        fallback_row = fallback["runs"]["narrator-dialogue-travel:p1"]
        self.assertIn("unexpected_or_unknown_fallback", fallback_row["problems"])
        self.assertEqual(fallback_row["automated_status"], "FAIL")
        trace_path.write_bytes(trace_bytes)
        manifest_path.write_bytes(manifest_bytes)

        failed, run_dir, socket_client, _party = run_case(
            "narrator-dialogue-travel", 1, break_room=True)
        self.addCleanup(lambda path=run_dir: shutil.rmtree(path) if path.exists() else None)
        self.assertEqual(failed, capture_drive.EXIT_START_FAILURE)
        self.assertEqual(sum(event == "user_input" for event, _ in socket_client.emitted), 2)
        failed_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="ascii"))
        self.assertEqual(failed_manifest["g4_step_projections"][-1]["projection"]["status"], "BLOCKED")

    def test_peaceful_area_copy_remains_peaceful_through_real_hydrator(self):
        root_authored = ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001_BU.json"
        root_hash = hashlib.sha256(root_authored.read_bytes()).hexdigest()
        scratch = tempfile.TemporaryDirectory(prefix="g4-peaceful-area-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        sandbox = pathlib.Path(scratch.name)
        module = sandbox / "modules" / "Capture_Arena"
        areas = module / "areas"
        areas.mkdir(parents=True)
        for name in ("CTR001_BU.json", "CTR001.json"):
            (areas / name).write_bytes(root_authored.with_name(name).read_bytes())

        hashes = seed_combat_capture.transform_g4_narrator_area_fixture(module)
        self.assertEqual(set(hashes), {"CTR001_BU.json", "CTR001.json"})
        bu_path, live_path = areas / "CTR001_BU.json", areas / "CTR001.json"
        bu, live = (json.loads(path.read_text(encoding="utf-8")) for path in (bu_path, live_path))
        for area in (bu, live):
            pit = next(row for row in area["locations"] if row["locationId"] == "CA02")
            self.assertEqual(pit["monsters"], [])
            self.assertIn("quiet", pit["description"])
            self.assertIn("do not start or imply combat", pit["dmInstructions"])
        self.assertEqual(bu, live)

        # Exercise actual startup area-hydration semantics: when live CA02 is
        # missing, the transformed BU copy is the material restored at runtime.
        live_path.unlink()
        result = hydrate_missing_live_area_files_from_bu(str(sandbox / "modules"))
        restored = json.loads(live_path.read_text(encoding="utf-8"))
        restored_pit = next(row for row in restored["locations"] if row["locationId"] == "CA02")
        self.assertEqual(result["restored"], 1)
        self.assertEqual(restored, bu)
        self.assertEqual(restored_pit["monsters"], [])
        self.assertEqual(hashlib.sha256(root_authored.read_bytes()).hexdigest(), root_hash)

    def test_narrator_seed_has_no_startup_encounter_and_uses_authored_ca03_mira(self):
        authored_area = json.loads(
            (ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(extract_npcs_from_area(authored_area)["CA03"], {"Warden Mira"})
        for party_size in (1, 4):
            with self.subTest(party=party_size):
                root = pathlib.Path("tmp") / ("g4-narrator-seed-p%d" % party_size)
                files = {}

                class FakePathManager:
                    @staticmethod
                    def get_character_unified_path(name):
                        return "characters/%s.json" % name.lower().replace(" ", "_")

                def writer(relative_path, payload):
                    destination = (root / relative_path).resolve()
                    self.assertTrue(destination.is_relative_to((ROOT / "tmp").resolve()))
                    files[destination.relative_to(root.resolve()).as_posix()] = copy.deepcopy(payload)
                    return destination

                names = [fixtures.ONE_PC_NAME] if party_size == 1 else list(fixtures.PC_NAMES)
                profile = fixtures.build_gate_profile("g4", "narrator-dialogue-travel", party_size)
                encounter_id = seed_combat_capture._seed_party(
                    {"module": "Capture_Arena", "area_id": "CTR001",
                     "area_name": "Capture Arena", "start_location_id": "CA01",
                     "start_location_name": "Waystone Gate"}, names, party_size, profile,
                    writer=writer, path_manager=FakePathManager(),
                )
                self.assertEqual(encounter_id, "")
                tracker = files["party_tracker.json"]
                self.assertEqual(tracker["worldConditions"]["activeCombatEncounter"], "")
                self.assertEqual(tracker["worldConditions"]["currentLocationId"], "CA01")
                self.assertEqual(tracker["partyMembers"], names)
                self.assertFalse(any(path.startswith("modules/encounters/") for path in files))
                self.assertFalse(any("mira" in path.casefold() for path in files))


class FakeSocket:
    def __init__(self, pending_initiative=False, pending_enemy=False):
        self.handlers = {}
        self.emitted = []
        self.connected = False
        self.connected_url = None
        self.pending_initiative = pending_initiative
        self.pending_enemy = pending_enemy

    def on(self, event, callback):
        self.handlers[event] = callback

    def connect(self, url, **kwargs):
        self.connected = True
        self.connected_url = url

    def emit(self, event, data=None):
        self.emitted.append((event, data))
        if event == "start_game":
            opening = "session ready"
            if self.pending_initiative:
                opening += " Initiative pending: enter /init."
            self.handlers["game_output"]({"type": "system", "content": opening})
            self.handlers["status_update"]({"is_processing": False, "message": "ready"})
        elif event == "user_input":
            output = "synthetic response"
            if self.pending_enemy:
                output += " PC phase complete: true; await /end."
            self.handlers["game_output"]({"type": "narration", "content": output})
            self.handlers["status_update"]({"is_processing": False, "message": "idle"})

    def disconnect(self):
        self.connected = False


class DelayedExplicitExitSocket(FakeSocket):
    """Echo immediately, then clear canonical state and report backend idle later."""

    def __init__(self, tracker_path):
        super().__init__()
        self.tracker_path = pathlib.Path(tracker_path)
        self.timer = None

    def emit(self, event, data=None):
        self.emitted.append((event, data))
        if event == "start_game":
            self.handlers["game_output"]({"type": "system", "content": "session ready"})
            self.handlers["status_update"]({"is_processing": False, "message": "ready"})
        elif event == "user_input" and data.get("input") == "/end_combat":
            self.handlers["game_output"]({"type": "user-input", "content": "/end_combat"})
            self.handlers["status_update"]({"is_processing": True, "message": "summary running"})

            def finish_exit():
                tracker = json.loads(self.tracker_path.read_text(encoding="utf-8"))
                tracker["worldConditions"]["activeCombatEncounter"] = ""
                self.tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
                self.handlers["status_update"]({"is_processing": False, "message": "ready"})

            self.timer = threading.Timer(0.02, finish_exit)
            self.timer.start()
        elif event == "user_input":
            self.handlers["game_output"]({"type": "user-input", "content": data.get("input", "")})
            self.handlers["game_output"]({"type": "narration", "content": "The quiet yard rests beyond the cleared encounter."})
            self.handlers["status_update"]({"is_processing": False, "message": "idle"})


class FakeHealthResponse:
    status_code = 200

    def __init__(self, roster):
        self.roster = list(roster)

    def json(self):
        return {"partyMembers": self.roster}


class FakeResponse:
    status_code = 200

    @staticmethod
    def json():
        return {"success": True}


def _args(scenario, party, directory, branch=None, phase=None):
    return SimpleNamespace(
        url="http://localhost:8360", party=party, transcript=str(directory / "transcript.log"),
        trace_src="tmp/no-trace.jsonl", trace_dst=None, start_timeout=0.2,
        turn_timeout=0.2, turn_quiet_seconds=0.001, settle_seconds=0,
        init_roll=15, scenario=scenario, branch=branch, phase=phase,
    )


def _g5t_trace_session(directory, socket_client, turn_timeout=0.15):
    root = pathlib.Path(directory)
    trace_path = root / "debug" / "combat_turn_trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")
    args = _args(None, 1, root)
    args.gate = "g5t"
    args.turn_timeout = turn_timeout
    args.turn_quiet_seconds = 0.005
    args.trace_src = str(trace_path)
    args.state_root = str(root)
    session = capture_drive.CaptureSession(args, socket_client=socket_client)
    session.capture_profile = fixtures.build_gate_profile(
        "g5t", "g5t-commander-p1", 1)
    session.current_character = "Acheron"
    session.register_handlers()
    return session, trace_path


def _g5a_trace_session(directory, socket_client, turn_timeout=0.6):
    root = pathlib.Path(directory)
    trace_path = root / "debug" / "combat_turn_trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")
    args = _args("g5a-ally-p1", 1, root)
    args.gate = "g5a"
    args.run_dir = str(root / "g5a-driver-run")
    args.turn_timeout = turn_timeout
    args.turn_quiet_seconds = 0.005
    args.trace_src = str(trace_path)
    args.state_root = str(root)
    session = capture_drive.CaptureSession(args, socket_client=socket_client)
    session.capture_profile = fixtures.build_gate_profile("g5a", "g5a-ally-p1", 1)
    session.current_character = "Acheron"
    session.register_handlers()
    return session, trace_path


class CaptureDriveScenarioTests(unittest.TestCase):
    def test_g5t_zero_issued_squad_batch_is_not_applicable(self):
        profile = fixtures.build_gate_profile("g5t", "g5t-commander-p1", 1)
        fixture = profile["fixture"]
        batch = next(row for row in fixture["steps"]
                     if isinstance(row, dict) and row.get("unit_type") == "batch")
        fixture["steps"] = [batch]
        batch_id = batch["trace_batch_id"]
        events = [
            {
                "event_type": "decision",
                "decision_point": "enemy_batch_resolution",
                "batch_id": batch_id,
                "decision_source": "llm_tactical",
            },
            {
                "event_type": "combat_observation",
                "observation": "combat_tactical_plan_result",
                "batch_id": batch_id,
                "tactical_plan_outcome": "rejected_all",
            },
            {
                "event_type": "combat_observation",
                "observation": "commander_squad_follows_orders",
                "batch_id": batch_id,
                "followed_orders": False,
                "issued_choice_count": 0,
                "applied_choice_count": 0,
            },
        ]
        checks = capture_evidence.observed_checks(
            profile,
            {"records": {}, "errors": [], "numeric_errors": []},
            {"records": {}, "errors": [], "numeric_errors": []},
            {"trace": "trace.jsonl"},
            [],
            events,
        )
        squad_check = next(row for row in checks
                           if row.get("id") == "commander_squad_follows_orders")
        self.assertEqual(squad_check["status"], "NOT_APPLICABLE")
        self.assertIsNone(squad_check["observed"]["followed_orders"])
        observation = squad_check["observed"]["observations"][0]
        self.assertEqual(observation["status"], "NOT_APPLICABLE")
        self.assertEqual(observation["observed"], {
            "applicability": "no_commander_plan_contribution"
        })

    def test_named_timeout_policy_is_identical_at_driver_and_evaluator_boundaries(self):
        valid_300 = (
            ("combat-smoke", 1, None), ("combat-smoke", 4, None),
            ("combat-smoke-allied-inactive", 1, None),
            ("combat-smoke-allied-inactive", 4, None),
            ("surrender-exit", 4, "surrender"),
        )
        invalid_300 = (
            ("initiative-pc", 1, None), ("surrender-exit", 1, "surrender"),
            ("surrender-exit", 4, "explicit-exit"),
        )
        for scenario, party, branch in valid_300:
            with self.subTest(preflight=(scenario, party, branch)):
                args = _args(scenario, party, ROOT / "tmp", branch)
                args.turn_timeout = 300.0
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = capture_drive.run(args)
                self.assertEqual(result, capture_drive.EXIT_CONNECT_FAILURE)
                self.assertIn("--run-dir", output.getvalue())
                self.assertNotIn("timeout up to 150", output.getvalue())
            profile = fixtures.build_capture_profile(scenario, party, branch or "")
            manifest = {
                "scenario": {"id": scenario, "branch": branch}, "party": {"size": party},
                "counts": {name: 0 for name in (
                    "step_attempts", "steps_sent", "backend_output_count",
                    "control_request_attempts", "control_request_calls",
                    "control_request_failures", "control_requests_sent",
                    "active_switch_attempts", "active_switch_requests_sent",
                    "blocked_step_attempts", "blocked_control_attempts", "timeouts",
                    "step_caps_reached", "idle_settle_caps_reached",
                    "active_switch_failures", "health_read_attempts",
                    "exit_health_read_attempts",
                )},
                "bounds": {"max_steps": profile["max_steps"],
                           "max_requests": profile["max_requests"],
                           "max_health_reads": profile["max_health_reads"],
                           "max_active_switches": profile["max_active_switches"],
                           "turn_timeout_seconds": 300.0,
                           "start_timeout_seconds": 180.0,
                           "turn_quiet_seconds": 1.5},
            }
            evaluation = capture_evidence.evaluate_evidence(
                manifest, [], {"matrix_keys": [capture_evidence.matrix_key(
                    scenario, party, branch=branch)], "required_evidence_status": "ok"},
                run_dir=ROOT / "tmp" / "timeout-policy-test", integrity={"failures": []},
                profile=profile,
            )
            self.assertNotIn("malformed_counts_or_bounds", evaluation["problems"])
            self.assertNotEqual(evaluation["automated_status"], "READY_FOR_PRIMARY_REVIEW")

        rejected_values = (175.0, 301.0, float("nan"), float("inf"), True, 0.0, -1.0)
        for scenario, party, branch in invalid_300:
            with self.subTest(preflight=(scenario, party, branch)):
                args = _args(scenario, party, ROOT / "tmp", branch)
                args.turn_timeout = 300.0
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = capture_drive.run(args)
                self.assertEqual(result, capture_drive.EXIT_CONNECT_FAILURE)
                self.assertIn("timeout up to 150", output.getvalue())

        for value in rejected_values:
            args = _args("combat-smoke", 1, ROOT / "tmp")
            args.turn_timeout = value
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = capture_drive.run(args)
            self.assertEqual(result, capture_drive.EXIT_CONNECT_FAILURE)
            self.assertIn("timeout up to 150", output.getvalue())
            self.assertFalse(fixtures.capture_turn_timeout_allowed("combat-smoke", 1, None, value))

        evaluator_profile = fixtures.build_capture_profile("combat-smoke", 1)
        for value in (150.0, 0.2, 175.0, 301.0, float("nan"), float("inf"), True, 0.0, -1.0):
            with self.subTest(evaluator_timeout=value):
                manifest = {
                    "scenario": {"id": "combat-smoke"}, "party": {"size": 1},
                    "counts": {name: 0 for name in (
                        "step_attempts", "steps_sent", "backend_output_count",
                        "control_request_attempts", "control_request_calls",
                        "control_request_failures", "control_requests_sent",
                        "active_switch_attempts", "active_switch_requests_sent",
                        "blocked_step_attempts", "blocked_control_attempts", "timeouts",
                        "step_caps_reached", "idle_settle_caps_reached",
                        "active_switch_failures", "health_read_attempts",
                        "exit_health_read_attempts",
                    )},
                    "bounds": {"max_steps": 5, "max_requests": 7,
                               "max_health_reads": 0, "max_active_switches": 1,
                               "turn_timeout_seconds": value,
                               "start_timeout_seconds": 180.0,
                               "turn_quiet_seconds": 1.5},
                }
                evaluation = capture_evidence.evaluate_evidence(
                    manifest, [], {"matrix_keys": ["combat-smoke:p1"],
                                   "required_evidence_status": "ok"},
                    run_dir=ROOT / "tmp" / "timeout-policy-invalid-test",
                    integrity={"failures": []}, profile=evaluator_profile,
                )
                malformed = "malformed_counts_or_bounds" in evaluation["problems"]
                self.assertEqual(malformed, value not in (150.0, 0.2))

        for scenario, party, branch in valid_300:
            profile = fixtures.build_capture_profile(scenario, party, branch or "")
            for failed_count, failed_name in ((1, "timeouts"), (1, "step_caps_reached")):
                manifest = {
                    "scenario": {"id": scenario, "branch": branch}, "party": {"size": party},
                    "counts": {name: 0 for name in (
                        "step_attempts", "steps_sent", "backend_output_count",
                        "control_request_attempts", "control_request_calls",
                        "control_request_failures", "control_requests_sent",
                        "active_switch_attempts", "active_switch_requests_sent",
                        "blocked_step_attempts", "blocked_control_attempts", "timeouts",
                        "step_caps_reached", "idle_settle_caps_reached",
                        "active_switch_failures", "health_read_attempts",
                        "exit_health_read_attempts",
                    )},
                    "bounds": {"max_steps": profile["max_steps"],
                               "max_requests": profile["max_requests"],
                               "max_health_reads": profile["max_health_reads"],
                               "max_active_switches": profile["max_active_switches"],
                               "turn_timeout_seconds": 300.0,
                               "start_timeout_seconds": 180.0,
                               "turn_quiet_seconds": 1.5},
                }
                manifest["counts"][failed_name] = failed_count
                failed = capture_evidence.evaluate_evidence(
                    manifest, [], {"matrix_keys": [capture_evidence.matrix_key(
                        scenario, party, branch=branch)], "required_evidence_status": "ok"},
                    run_dir=ROOT / "tmp" / "timeout-policy-failure-test",
                    integrity={"failures": []}, profile=profile,
                )
                self.assertNotIn("malformed_counts_or_bounds", failed["problems"])
                self.assertIn("required_timeout" if failed_name == "timeouts" else "required_cap",
                              failed["problems"])
                self.assertNotEqual(failed["automated_status"], "READY_FOR_PRIMARY_REVIEW")

    @staticmethod
    def _causal_steps(party=1):
        rows = []
        for index in range(1, 3):
            rows.append({
                "before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": (index - 1) * 100},
                                             "input": "/dmg 2", "character": "Acheron"},
                            "records": {"party_tracker.json": {"active_character": "Acheron"}}},
                "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": index * 100}}},
            })
        return rows

    @staticmethod
    def _hp_snapshot(acheron=20, goblin=20, blairen=12, party=1):
        party_names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
        pc_creatures = [{"name": name, "type": "player",
                         "currentHitPoints": acheron if name == "Acheron" else 20}
                        for name in party_names]
        character_records = {"characters/%s.json" % name.casefold(): {
            "read_status": "ok", "name": name,
            "hitPoints": acheron if name == "Acheron" else 20,
        } for name in party_names}
        character_records["characters/blairen.json"] = {
            "read_status": "ok", "name": "Blairen", "hitPoints": blairen,
        }
        return {"label": "synthetic-test", "records": {
            "selected_encounter": {"status": "ok", "encounterId": "synthetic_encounter",
                                    "creatures": pc_creatures + [
                                        {"name": "Goblin", "type": "enemy", "currentHitPoints": goblin},
                                        {"name": "Blairen", "type": "npc", "currentHitPoints": blairen}]},
            **character_records,
            "party_tracker.json": {"status": "ok", "partyMembers": party_names,
                                   "active_character": "Acheron"},
        }}

    @staticmethod
    def _hp_step(index, before, after, command="observe"):
        start = (index - 1) * 100
        end = index * 100
        return {"before": {**copy.deepcopy(before), "observation": {
                    "label": "synthetic-test", "input": command, "character": "Acheron",
                    "runtimeTrace": {"status": "captured", "offset_bytes": start}}},
                "after": {**copy.deepcopy(after), "observation": {
                    "runtimeTrace": {"status": "captured", "offset_bytes": end}}}}

    def test_canonical_mirror_same_step_and_delayed_next_step_are_counted_once(self):
        initial = self._hp_snapshot()
        same_after = self._hp_snapshot(blairen=9)
        event = {"event_type": "combat_observation", "observation": "combat_apply_result",
                 "fixture": "synthetic-test", "domain": "character",
                 "operation": "update_character_info_ops", "target": "Blairen", "applied": True,
                 "ops": [{"op": "hp_delta", "delta": -3}],
                 "_source_byte_start": 10, "_source_byte_end": 20}
        same = capture_evidence._hp_causal_ledger(initial, [self._hp_step(1, initial, same_after)],
                                                  same_after, [event])
        self.assertEqual(same["status"], "PASS")
        self.assertEqual(same["steps"][0]["logical_hp_effects"], [{
            "entity": "blairen", "delta": -3, "sources": ["character", "encounter"]}])
        pc_after = self._hp_snapshot(acheron=15)
        pc_event = {"event_type": "combat_observation", "observation": "combat_apply_result",
                    "fixture": "synthetic-test", "domain": "character",
                    "operation": "update_character_info_ops", "target": "Acheron", "applied": True,
                    "ops": [{"op": "hp_delta", "delta": -5}],
                    "_source_byte_start": 30, "_source_byte_end": 40}
        pc_same = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, pc_after)], pc_after, [pc_event]
        )
        self.assertEqual(pc_same["status"], "PASS")
        pc_effect = next(row for row in pc_same["steps"][0]["logical_hp_effects"]
                         if row["entity"] == "acheron")
        self.assertEqual(pc_effect, {"entity": "acheron", "delta": -5,
                                     "sources": ["character", "encounter"]})
        first_after = self._hp_snapshot(blairen=12)
        first_after["records"]["characters/blairen.json"]["hitPoints"] = 9
        second_before = copy.deepcopy(first_after)
        delayed_after = self._hp_snapshot(blairen=9)
        delayed = capture_evidence._hp_causal_ledger(
            initial,
            [self._hp_step(1, initial, first_after), self._hp_step(2, second_before, delayed_after)],
            delayed_after,
            [event],
        )
        self.assertEqual(delayed["status"], "PASS")
        self.assertEqual(delayed["steps"][0]["logical_hp_effects"][0]["sources"], ["character"])
        self.assertTrue(any(row.get("direction") == "delayed_encounter" for row in delayed["steps"][1]["mirror_projections"]))
        next_before_sync = self._hp_snapshot(blairen=9)
        boundary_sync = capture_evidence._hp_causal_ledger(
            initial,
            [self._hp_step(1, initial, first_after),
             self._hp_step(2, next_before_sync, next_before_sync)],
            next_before_sync,
            [event],
        )
        self.assertEqual(boundary_sync["status"], "PASS")
        self.assertTrue(any(row.get("justification", "").startswith("exact pending mirror")
                            for row in boundary_sync["boundaries"]))

    def test_wrong_mirror_and_unexplained_between_or_end_mutations_fail(self):
        initial = self._hp_snapshot()
        wrong = self._hp_snapshot(blairen=12)
        wrong["records"]["characters/blairen.json"]["hitPoints"] = 9
        char_event = {"event_type": "combat_observation", "observation": "combat_apply_result",
                      "fixture": "synthetic-test", "domain": "character",
                      "operation": "update_character_info_ops", "target": "Blairen", "applied": True,
                      "ops": [{"op": "hp_delta", "delta": -3}],
                      "_source_byte_start": 10, "_source_byte_end": 20}
        wrong_result = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, wrong)], wrong, [char_event]
        )
        self.assertEqual(wrong_result["status"], "FAIL")

        step_after = self._hp_snapshot(blairen=9)
        second_before = self._hp_snapshot(blairen=9, goblin=19)
        second_after = self._hp_snapshot(blairen=9, goblin=19)
        char_event["_source_byte_start"], char_event["_source_byte_end"] = 10, 20
        between = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, step_after),
                      self._hp_step(2, second_before, second_after)], second_after, [char_event]
        )
        self.assertEqual(between["status"], "FAIL")
        final_mutation = self._hp_snapshot(blairen=9, goblin=19)
        end_extra = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, step_after)], final_mutation, [char_event]
        )
        self.assertEqual(end_extra["status"], "FAIL")

    def test_apply_and_final_validation_failures_dominate_missing_hp_proof(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        before = self._hp_snapshot()
        events = [
            {"event_type": "combat_observation", "observation": "combat_apply_result",
             "fixture": "synthetic-test", "domain": "encounter", "operation": "update_encounter",
             "target": "Goblin", "applied": False, "failure": "false_return"},
            {"event_type": "combat_observation", "observation": "combat_validation_result",
             "fixture": "synthetic-test", "validation_accepted": False},
        ]
        checks = capture_evidence.observed_checks(profile, before, before, {}, [], events)
        by_id = {row["id"]: row for row in checks}
        self.assertEqual(by_id["hp_delta_snapshot_reconciliation"]["status"], "BLOCKED")
        self.assertEqual(by_id["mechanical_apply_outcomes"]["status"], "FAIL")
        self.assertEqual(by_id["final_response_validation_truth"]["status"], "FAIL")

    def test_resolver_final_response_truth_requires_decision_narration_and_no_validation_call(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        snapshot = self._hp_snapshot()
        # Minimal, in-test excerpt shaped from the post-fix capture trace; the
        # live bundle itself is not a test dependency or fixture artifact.
        trace_fixture = [
            {"event_type": "decision", "decision_point": "enemy_batch_resolution",
             "decision_source": "deterministic", "decision_outcome": "resolver_supported",
             "decision_reason": "ledger_supported", "action_id": "pc:r1:acheron",
             "batch_id": "enemy:r1", "logical_turn": 1},
            {"event_type": "combat_observation", "observation": "combat_action_batch",
             "action_id": "pc:r1:acheron", "batch_id": "enemy:r1", "logical_turn": 1,
             "validation_accepted": True},
            {"event_type": "combat_observation", "observation": "combat_batch_narration_result",
             "action_id": "pc:r1:acheron", "batch_id": "enemy:r1", "logical_turn": 1,
             "source": "llm"},
            {"event_type": "combat_observation", "observation": "combat_logical_batch_completed",
             "action_id": "pc:r1:acheron", "batch_id": "enemy:r1", "logical_turn": 1,
             "accepted_batch": True},
        ]

        def final_truth(events, trace_provider_events=None):
            artifacts = ({"trace_provider_events": trace_provider_events}
                         if trace_provider_events is not None else {})
            checks = capture_evidence.observed_checks(
                profile, snapshot, snapshot, artifacts, [], events
            )
            return {row["id"]: row for row in checks}

        positive = final_truth(trace_fixture)
        self.assertEqual(positive["final_response_validation_truth"]["status"], "PASS")
        self.assertEqual(positive["accepted_logical_batch_once"]["status"], "PASS")
        self.assertEqual(
            positive["accepted_logical_batch_once"]["observed"]["resolver_batches"][0]["batch_id"],
            "enemy:r1",
        )

        missing_decision = final_truth(trace_fixture[1:])
        self.assertEqual(missing_decision["final_response_validation_truth"]["status"], "BLOCKED")
        self.assertEqual(missing_decision["accepted_logical_batch_once"]["status"], "BLOCKED")

        missing_narration_events = [trace_fixture[0]] + [
            event for event in trace_fixture[1:]
            if event["observation"] != "combat_batch_narration_result"
        ]
        missing_narration = final_truth(missing_narration_events)
        self.assertEqual(missing_narration["final_response_validation_truth"]["status"], "BLOCKED")
        self.assertEqual(missing_narration["accepted_logical_batch_once"]["status"], "PASS")

        validation_call = {
            "event_type": "provider",
            "site": "combat_validation",
            "task": "combat_validation",
            "batch_id": "enemy:r1",
        }
        validation_call_result = final_truth(
            trace_fixture, trace_provider_events=[validation_call]
        )
        self.assertEqual(validation_call_result["final_response_validation_truth"]["status"], "BLOCKED")
        # This check proves batch application pairing only; it does not require
        # a combat_validation_result pairing for resolver-supported turns.
        self.assertEqual(validation_call_result["accepted_logical_batch_once"]["status"], "PASS")

        for negative_events in (
            trace_fixture[:-1],
            trace_fixture + [copy.deepcopy(trace_fixture[1])],
            trace_fixture[:3] + [{**trace_fixture[3], "batch_id": "enemy:r2"}],
            trace_fixture[:1] + [{**trace_fixture[1], "validation_accepted": False}]
            + trace_fixture[2:],
        ):
            with self.subTest(events=negative_events):
                self.assertEqual(
                    final_truth(negative_events)["accepted_logical_batch_once"]["status"],
                    "BLOCKED",
                )

    def test_g5t_final_response_truth_accepts_tactical_decision_only_without_validation(self):
        snapshot = self._hp_snapshot()

        def final_truth(profile, decision_source, *, narration=True, provider_events=None):
            events = [{
                "event_type": "decision", "decision_point": "enemy_batch_resolution",
                "decision_source": decision_source,
                "decision_outcome": "resolver_supported", "batch_id": "enemy:r1",
                "logical_turn": 1,
            }]
            if narration:
                events.append({
                    "event_type": "combat_observation",
                    "observation": "combat_batch_narration_result",
                    "batch_id": "enemy:r1", "logical_turn": 1, "source": "llm",
                })
            artifacts = ({"trace_provider_events": provider_events}
                         if provider_events is not None else {})
            checks = capture_evidence.observed_checks(
                profile, snapshot, snapshot, artifacts, [], events
            )
            return next(row for row in checks
                        if row["id"] == "final_response_validation_truth")

        g5t = fixtures.build_gate_profile("g5t", "g5t-commander-p1", 1)
        tactical = final_truth(g5t, "llm_tactical")
        self.assertEqual(tactical["status"], "PASS")
        self.assertFalse(tactical["required"])
        self.assertEqual(
            tactical["observed"]["resolver_batches"][0]["validation_provider_calls"], 0
        )
        self.assertEqual(final_truth(g5t, "llm_tactical", narration=False)["status"],
                         "BLOCKED")
        validation_provider_call = {
            "event_type": "provider", "site": "combat_validation",
            "batch_id": "enemy:r1",
        }
        self.assertEqual(final_truth(
            g5t, "llm_tactical", provider_events=[validation_provider_call]
        )["status"], "BLOCKED")

        for gate in ("g5", "g5r"):
            profile = fixtures.build_gate_profile(gate, "combat-smoke", 1)
            with self.subTest(gate=gate):
                self.assertEqual(final_truth(profile, "llm_tactical")["status"], "BLOCKED")
                self.assertEqual(final_truth(profile, "deterministic")["status"], "PASS")

    def test_capture_time_checks_accept_resolver_only_trace(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        snapshot = self._hp_snapshot()
        batch_id = "enemy:r1"
        trace = [
            {"event_type": "decision", "decision_point": "enemy_batch_resolution",
             "decision_source": "deterministic", "decision_outcome": "resolver_supported",
             "decision_reason": "ledger_supported", "batch_id": batch_id,
             "logical_turn": 1, "phase": "ENEMY_PHASE"},
            {"event_type": "combat_observation", "observation": "combat_action_batch",
             "batch_id": batch_id, "logical_turn": 1, "validation_accepted": True},
            {"event_type": "combat_observation", "observation": "combat_batch_narration_result",
             "batch_id": batch_id, "logical_turn": 1, "source": "llm"},
            {"event_type": "combat_observation", "observation": "combat_logical_batch_completed",
             "batch_id": batch_id, "logical_turn": 1, "accepted_batch": True},
            {"event_type": "provider", "site": "combat_main", "batch_id": batch_id},
        ]
        artifacts = {}

        checks, observations = capture_drive._build_capture_time_checks(
            profile, snapshot, snapshot, artifacts, [], trace, []
        )

        by_id = {row["id"]: row for row in checks}
        self.assertNotIn("combat_validation_result", [row.get("observation") for row in observations])
        self.assertEqual(len(artifacts["trace_provider_events"]), 1)
        self.assertEqual(by_id["final_response_validation_truth"]["status"], "PASS")
        self.assertEqual(by_id["accepted_logical_batch_once"]["status"], "PASS")
        self.assertEqual(
            by_id["accepted_logical_batch_once"]["observed"]["resolver_batches"][0]["batch_id"],
            batch_id,
        )

    def test_unassigned_hp_event_missing_invalid_duplicate_cells_and_boolean_offsets_block(self):
        initial = self._hp_snapshot()
        after = self._hp_snapshot(blairen=9)
        event = {"event_type": "combat_observation", "observation": "combat_apply_result",
                 "fixture": "synthetic-test", "domain": "character",
                 "operation": "update_character_info_ops", "target": "Blairen", "applied": True,
                 "ops": [{"op": "hp_delta", "delta": -3}],
                 "_source_byte_start": 250, "_source_byte_end": 260}
        unassigned = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, after)], after, [event]
        )
        self.assertEqual(unassigned["status"], "BLOCKED")
        event["_source_byte_start"] = 10
        event["_source_byte_end"] = 20
        for bad_hp in (None, float("inf"), 8.5, True):
            invalid = copy.deepcopy(after)
            invalid["records"]["characters/blairen.json"]["hitPoints"] = bad_hp
            self.assertEqual(capture_evidence._hp_causal_ledger(
                initial, [self._hp_step(1, initial, invalid)], invalid, [event]
            )["status"], "BLOCKED")
        duplicate = copy.deepcopy(after)
        duplicate["records"]["characters/blairen-copy.json"] = copy.deepcopy(
            duplicate["records"]["characters/blairen.json"]
        )
        self.assertEqual(capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, duplicate)], duplicate, [event]
        )["status"], "BLOCKED")
        bool_offset_steps = [self._hp_step(1, initial, after)]
        bool_offset_steps[0]["before"]["observation"]["runtimeTrace"]["offset_bytes"] = True
        self.assertEqual(capture_evidence._hp_causal_ledger(
            initial, bool_offset_steps, after, [event]
        )["status"], "BLOCKED")

    def test_missing_encounter_cell_and_missing_apply_target_are_blocked(self):
        initial = self._hp_snapshot()
        missing_encounter = {"records": {"selected_encounter": {"status": "missing"}}}
        self.assertEqual(capture_evidence._hp_causal_ledger(
            missing_encounter, [], missing_encounter, []
        )["status"], "BLOCKED")
        after = self._hp_snapshot()
        event = {"event_type": "combat_observation", "observation": "combat_apply_result",
                 "fixture": "synthetic-test", "domain": "encounter", "operation": "update_encounter",
                 "target": "synthetic_encounter", "applied": True,
                 "ops": [{"op": "hp_delta", "creature": "Missing Creature", "delta": -1}],
                 "_source_byte_start": 10, "_source_byte_end": 20}
        result = capture_evidence._hp_causal_ledger(
            initial, [self._hp_step(1, initial, after)], after, [event]
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_hp_check_reports_complete_per_step_and_run_source_totals(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        initial = self._hp_snapshot()
        steps, events = [], []
        current = initial
        for index in range(1, 7):
            next_state = self._hp_snapshot(goblin=20 - index * 2)
            steps.append(self._hp_step(index, current, next_state, "/dmg 2"))
            events.append({"event_type": "decision", "fixture": "synthetic-test",
                           "decision_point": "combat_command_fast_path", "decision_source": "deterministic",
                           "provider_call_avoided": True,
                           "_source_byte_start": (index - 1) * 100 + 10,
                           "_source_byte_end": (index - 1) * 100 + 20})
            current = next_state
        final = self._hp_snapshot(goblin=4)
        steps.append(self._hp_step(7, current, final))
        events.append({"event_type": "combat_observation", "observation": "combat_apply_result",
                       "fixture": "synthetic-test", "domain": "encounter",
                       "operation": "update_encounter", "target": "synthetic_encounter", "applied": True,
                       "ops": [{"op": "hp_delta", "creature": "Goblin", "delta": -4}],
                       "_source_byte_start": 610, "_source_byte_end": 620})
        checks = capture_evidence.observed_checks(profile, initial, final, {}, steps, events)
        hp = next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")
        self.assertEqual(hp["status"], "PASS")
        ledger = hp["observed"]
        goblin_total = next(row for row in ledger["canonical_run_deltas_by_source"]
                            if row["domain"] == "encounter" and row["entity"] == "goblin")
        self.assertEqual(goblin_total["delta"], -16)
        self.assertEqual(len(ledger["steps"]), 7)
        self.assertEqual([row["logical_hp_effects"][0]["delta"] for row in ledger["steps"]],
                         [-2, -2, -2, -2, -2, -2, -4])

    def test_causal_ledger_normalizes_only_proven_net_zero_totals(self):
        for party in (1, 4):
            with self.subTest(party=party):
                initial = self._hp_snapshot(party=party)
                damaged = self._hp_snapshot(goblin=18, party=party)
                healed = self._hp_snapshot(goblin=20, party=party)
                events = [
                    {"event_type": "combat_observation", "observation": "combat_apply_result",
                     "fixture": "synthetic-test", "domain": "encounter", "operation": "update_encounter",
                     "target": "synthetic_encounter", "applied": True,
                     "ops": [{"op": "hp_delta", "creature": "Goblin", "delta": -2}],
                     "_source_byte_start": 10, "_source_byte_end": 20},
                    {"event_type": "combat_observation", "observation": "combat_apply_result",
                     "fixture": "synthetic-test", "domain": "encounter", "operation": "update_encounter",
                     "target": "synthetic_encounter", "applied": True,
                     "ops": [{"op": "hp_delta", "creature": "Goblin", "delta": 2}],
                     "_source_byte_start": 110, "_source_byte_end": 120},
                ]
                neutral = capture_evidence._hp_causal_ledger(
                    initial,
                    [self._hp_step(1, initial, damaged), self._hp_step(2, damaged, healed)],
                    healed, events,
                )
                self.assertEqual(neutral["status"], "PASS")
                self.assertEqual([row["structured_hp_operations"][0]["delta"]
                                  for row in neutral["steps"]], [-2, 2])
                extra = self._hp_snapshot(goblin=19, party=party)
                unexplained = capture_evidence._hp_causal_ledger(
                    initial,
                    [self._hp_step(1, initial, damaged), self._hp_step(2, damaged, healed),
                     self._hp_step(3, healed, extra)],
                    extra, events,
                )
                self.assertEqual(unexplained["status"], "FAIL")

    def test_trace_parser_preserves_source_positions_after_nonzero_resume_offset(self):
        scratch = tempfile.TemporaryDirectory(prefix="trace-offset-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        trace = pathlib.Path(scratch.name) / "trace.jsonl"
        raw = b'{"event_type":"combat_observation","observation":"x"}\n'
        trace.write_bytes(raw)
        records, errors = capture_evidence.parse_trace_positions(trace, 8192)
        self.assertEqual(errors, [])
        self.assertEqual(records[0]["_source_byte_start"], 8192)
        self.assertEqual(records[0]["_source_byte_end"], 8192 + len(raw))

    def test_causal_trace_linkage_is_party_neutral_and_requires_unique_full_spans(self):
        event = {"event_type": "combat_observation", "fixture": "synthetic-test",
                 "observation": "combat_apply_result",
                 "_source_byte_start": 12, "_source_byte_end": 28}
        for party in (1, 4):
            with self.subTest(party=party):
                steps = self._causal_steps(party)
                linked = capture_evidence.link_trace_events_to_steps([event], steps)
                self.assertEqual(linked["status"], "PASS")
                self.assertEqual(linked["events"][0]["step"], 1)
                mixed = [event, dict(event, _source_byte_start=35, _source_byte_end=45,
                                     event_type="decision", decision_point="combat_command_fast_path")]
                self.assertEqual(len(capture_evidence.link_trace_events_to_steps(mixed, steps)["events"]), 2)
                self.assertEqual(capture_evidence.link_trace_events_to_steps([event, dict(event)], steps)["reason"],
                                 "duplicate_event_coverage")
                # A partial boundary crossing cannot be assigned to either step.
                crossing = dict(event, _source_byte_start=95, _source_byte_end=105)
                self.assertEqual(capture_evidence.link_trace_events_to_steps([crossing], steps)["status"], "BLOCKED")
                missing = dict(event)
                missing.pop("_source_byte_start")
                self.assertEqual(capture_evidence.link_trace_events_to_steps([missing], steps)["status"], "BLOCKED")

    def test_causal_trace_linkage_blocks_duplicate_step_coverage_and_unknown_positions(self):
        steps = self._causal_steps()
        steps[1]["before"]["observation"]["runtimeTrace"]["offset_bytes"] = 90
        self.assertEqual(capture_evidence.link_trace_events_to_steps([], steps)["status"], "BLOCKED")
        unknown = self._causal_steps()
        unknown[0]["after"]["observation"]["runtimeTrace"] = {"status": "unavailable"}
        self.assertEqual(capture_evidence.link_trace_events_to_steps([], unknown)["status"], "BLOCKED")

    def test_failed_structured_operation_remains_failure_even_with_matching_hp_ledger(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        checks = capture_evidence.observed_checks(
            profile,
            {"records": {"party_tracker.json": {}, "selected_encounter": {"status": "missing"}}},
            {"records": {"party_tracker.json": {}, "selected_encounter": {"status": "missing"}}},
            {}, [], [{"observation": "combat_apply_result", "domain": "encounter",
                      "operation": "update_encounter", "target": "Goblin", "applied": False,
                      "failure": "actual_false_return"}],
        )
        self.assertEqual(next(row for row in checks if row["id"] == "mechanical_apply_outcomes")["status"], "FAIL")

    def test_unknown_structured_mutation_blocks_reconciliation(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        event = {"observation": "combat_apply_result", "domain": "encounter",
                 "operation": "update_encounter", "target": "not-an-identity", "applied": True,
                 "ops": [{"op": "future_mutation", "value": 1}],
                 "_source_byte_start": 10, "_source_byte_end": 20}
        step = [{"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 0}}},
                 "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 100}}}}]
        checks = capture_evidence.observed_checks(profile, {"records": {}}, {"records": {}}, {}, step, [event])
        self.assertEqual(next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")["status"], "BLOCKED")
        check_ids = {row["id"] for row in checks}
        self.assertEqual(check_ids, capture_evidence._required_check_ids(profile))

    def test_encounter_hp_delta_reconciliation_handles_both_party_shapes_and_ally_damage(self):
        def state(party, ally_rows):
            party_names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            pcs = [{"name": name, "type": "player", "status": "alive",
                    "currentHitPoints": 20} for name in party_names]
            creatures = pcs + [{"name": "Goblin", "type": "enemy", "status": "alive",
                                "currentHitPoints": 20}] + copy.deepcopy(ally_rows)
            characters = {"characters/%s.json" % name.casefold(): {
                "read_status": "ok", "name": name, "hitPoints": 20,
            } for name in party_names}
            for ally in ally_rows:
                characters["characters/%s.json" % ally["name"].casefold()] = {
                    "read_status": "ok", "name": ally["name"],
                    "hitPoints": ally["currentHitPoints"],
                }
            return {"records": {
                "party_tracker.json": {"status": "ok", "partyMembers": party_names},
                "selected_encounter": {"status": "ok", "encounterId": "capture_test",
                                        "creatures": creatures},
                **characters,
            }}

        event = {"observation": "combat_apply_result", "domain": "encounter",
                 "operation": "update_encounter", "target": "capture_test", "applied": True,
                 "_source_byte_start": 5, "_source_byte_end": 15,
                 "ops": [{"op": "hp_delta", "creature": "Blairen", "delta": -3}]}
        profile_for = lambda party: fixtures.build_capture_profile(
            "combat-smoke-allied-inactive", party
        )

        # These provider-free cases exercise the same canonical snapshot and
        # trace field shapes as the preserved Capture_Arena run. The expectations
        # below are synthetic test inputs, never live acceptance evidence.
        for party in (1, 4):
            with self.subTest(party=party):
                before = state(party, [{"name": "Blairen", "type": "npc", "npcType": "ally",
                                        "status": "alive", "currentHitPoints": 12}])
                after = state(party, [{"name": "Blairen", "type": "npc", "npcType": "ally",
                                       "status": "alive", "currentHitPoints": 9}])
                linked_step = [{
                    "before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 0}},
                                "records": copy.deepcopy(before["records"])},
                    "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 100}},
                               "records": copy.deepcopy(after["records"])},
                }]
                checks = capture_evidence.observed_checks(profile_for(party), before, after, {}, linked_step, [event])
                hp_check = next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")
                self.assertEqual(hp_check["status"], "PASS")
                self.assertEqual(hp_check["observed"]["steps"][0]["status"], "PASS")
                self.assertEqual(hp_check["observed"]["steps"][0]["structured_hp_operations"], [{
                    "domain": "encounter", "entity": "blairen", "delta": -3,
                }])

                mismatched = dict(event, ops=[{"op": "hp_delta", "creature": "Blairen", "delta": -2}])
                checks = capture_evidence.observed_checks(
                    profile_for(party), before, after, {}, linked_step, [mismatched]
                )
                self.assertEqual(
                    next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")["status"],
                    "FAIL",
                )

                missing = state(party, [])
                missing_steps = copy.deepcopy(linked_step)
                missing_steps[0]["after"]["records"]["selected_encounter"]["creatures"] = []
                checks = capture_evidence.observed_checks(
                    profile_for(party), before, missing, {}, missing_steps, [event]
                )
                self.assertEqual(
                    next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")["status"],
                    "BLOCKED",
                )

                ambiguous = state(party, [
                    {"name": "Blairen", "type": "npc", "npcType": "ally",
                     "status": "alive", "currentHitPoints": 9},
                    {"name": "Blairen", "type": "npc", "npcType": "ally",
                     "status": "alive", "currentHitPoints": 9},
                ])
                ambiguous_steps = copy.deepcopy(linked_step)
                ambiguous_steps[0]["after"]["records"]["selected_encounter"]["creatures"] = [
                    {"name": "Blairen", "type": "npc", "npcType": "ally",
                     "status": "alive", "currentHitPoints": 9},
                    {"name": "Blairen", "type": "npc", "npcType": "ally",
                     "status": "alive", "currentHitPoints": 9},
                ]
                checks = capture_evidence.observed_checks(
                    profile_for(party), before, ambiguous, {}, ambiguous_steps, [event]
                )
                self.assertEqual(
                    next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")["status"],
                    "BLOCKED",
                )

    def test_g5t_character_hp_delta_reconciles_legacy_encounter_mirror_projection(self):
        profile = fixtures.build_gate_profile(
            "g5t", "g5t-commander-p4", 4
        )

        def snapshot(character_hp, encounter_hp=None):
            encounter = copy.deepcopy(
                fixtures.build_g5t_commander_fixture(4)["encounter"]
            )
            for creature in encounter["creatures"]:
                if creature.get("type") == "player" and creature.get("name") == "Acheron":
                    creature["currentHitPoints"] = (
                        character_hp if encounter_hp is None else encounter_hp
                    )
            records = {
                "selected_encounter": {
                    "status": "ok",
                    "encounterId": encounter["encounterId"],
                    "creatures": encounter["creatures"],
                },
                "party_tracker.json": {
                    "status": "ok",
                    "partyMembers": list(fixtures.PC_NAMES),
                },
            }
            for creature in encounter["creatures"]:
                if creature.get("type") != "player":
                    continue
                name = creature["name"]
                hit_points = character_hp if name == "Acheron" else creature["currentHitPoints"]
                records["characters/%s.json" % name.casefold().replace(" ", "_")] = {
                    "read_status": "ok",
                    "name": name,
                    "hitPoints": hit_points,
                }
            return {"records": records}

        before = snapshot(185)
        after = snapshot(146)
        events = []
        for batch_id, delta in zip(
            ("enemy:r1", "enemy:r2", "enemy:r3", "enemy:r4"),
            (-11, -15, -9, -4),
        ):
            events.append({
                "event_type": "combat_observation",
                "observation": "combat_apply_result",
                "domain": "character",
                "operation": "update_character_info_ops",
                "target": "Acheron",
                "applied": True,
                "ops": [{"op": "hp_delta", "delta": delta}],
                "batch_id": batch_id,
            })
            if batch_id != "enemy:r4":
                events.append({
                    "event_type": "combat_observation",
                    "observation": "combat_apply_result",
                    "domain": "encounter",
                    "operation": "update_encounter",
                    "target": "g5t-commander-p4",
                    "applied": True,
                    "ops": [{"op": "hp_delta", "creature": "Acheron", "delta": delta}],
                    "batch_id": batch_id,
                })
        # The leader-down fallback wrote through legacy sites without an
        # encounter-domain hp_delta event, matching the preserved p4-r1 trace.
        events.extend({
            "event_type": "file_operation",
            "category": "write",
            "site": "legacy_character_or_encounter_write",
            "batch_id": "enemy:r4",
        } for _ in range(4))

        checks = capture_evidence.observed_checks(profile, before, after, {}, [], events)
        hp_check = next(
            row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation"
        )
        self.assertEqual(hp_check["status"], "PASS")
        mirror = next(
            row for row in hp_check["observed"]
            if row["domain"] == "encounter" and row["target"] == "acheron"
        )
        self.assertEqual(mirror["expected_delta"], -39)
        self.assertEqual(mirror["observed_delta"], -39)

        mismatched_after = snapshot(146, encounter_hp=147)
        mismatched_checks = capture_evidence.observed_checks(
            profile, before, mismatched_after, {}, [], events
        )
        mismatched_hp = next(
            row for row in mismatched_checks
            if row["id"] == "hp_delta_snapshot_reconciliation"
        )
        self.assertEqual(mismatched_hp["status"], "FAIL")

    def test_user_input_echo_and_idle_status_do_not_complete_turn(self):
        class EchoThenDelayedBackend(FakeSocket):
            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["game_output"]({"type": "user-input", "content": data["input"]})
                    inner.handlers["status_update"]({"is_processing": False, "message": "idle echo"})
                    inner.timer = threading.Timer(0.025, lambda: (
                        inner.handlers["game_output"]({"type": "narration", "content": "backend reply"}),
                        inner.handlers["status_update"]({"is_processing": False, "message": "idle"}),
                    ))
                    inner.timer.start()

        scratch = tempfile.TemporaryDirectory(prefix="capture-echo-delay-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        args = _args(None, 1, pathlib.Path(scratch.name))
        args.turn_timeout = 0.12
        args.turn_quiet_seconds = 0.005
        socket_client = EchoThenDelayedBackend()
        session = capture_drive.CaptureSession(args, socket_client=socket_client)
        session.current_character = "Acheron"
        session.register_handlers()
        result = session.send_turn("delayed", "look around", "Acheron")
        self.assertGreaterEqual(result.elapsed_seconds, 0.02)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.new_game_outputs, 2)
        self.assertEqual(result.backend_output_count, 1)

    def test_g5t_status_before_output_completes_with_batch_trace_marker(self):
        step = fixtures.build_g5t_script_steps(1)[0]

        class StatusBeforeOutputSocket(FakeSocket):
            def __init__(inner, trace_path):
                super().__init__()
                inner.trace_path = pathlib.Path(trace_path)

            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    # Replay the captured event ordering and the matching real trace row.
                    for line in G5T_STATUS_BEFORE_OUTPUT_TRANSCRIPT.splitlines():
                        if line.startswith("[status_update] "):
                            message = line.split("message=", 1)[1]
                            inner.handlers["status_update"]({
                                "is_processing": False, "message": message,
                            })
                        elif line.startswith("[game_output] "):
                            inner.handlers["game_output"]({
                                "type": "narration", "content": line.split("content=", 1)[1],
                            })
                    marker = json.loads(G5T_R1_TURN_END_TRACE_LINE)
                    with inner.trace_path.open("ab") as handle:
                        handle.write((json.dumps(marker) + "\n").encode("utf-8"))

        scratch = tempfile.TemporaryDirectory(prefix="g5t-status-before-output-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        trace_path = root / "debug" / "combat_turn_trace.jsonl"
        socket_client = StatusBeforeOutputSocket(trace_path)
        session, _ = _g5t_trace_session(root, socket_client)
        result = session.send_turn(
            step["label"], step["input"], step["character"], fixture_step=step)

        self.assertFalse(result.timed_out)
        self.assertEqual(len(session.status_events), 3)
        self.assertTrue(all(event["ts"] < session.game_outputs[0]["ts"]
                            for event in session.status_events))
        marker = session.g5_step_receipts[-1]["server_completion_marker"]
        self.assertEqual(marker["stage"], "turn_end")
        self.assertEqual(marker["batch_id"], "enemy:r1")

    def test_g5a_end_waits_for_matching_run_logical_batch_marker(self):
        step = fixtures.build_g5a_script_steps(1)[-1]
        run_id = "g5a-driver-run"

        class DelayedLogicalBatchMarkerSocket(FakeSocket):
            def __init__(inner, trace_path):
                super().__init__()
                inner.trace_path = pathlib.Path(trace_path)
                inner.timer = None

            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["status_update"]({
                        "is_processing": False, "message": "The round is settled.",
                    })
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "The enemies answer the call.",
                    })

                    def complete_batch():
                        marker = {
                            "schema_version": 1,
                            "event_type": "combat_observation",
                            "observation": "combat_logical_batch_completed",
                            "batch_id": step["trace_batch_id"],
                            "accepted_batch": True,
                            "validation_accepted": True,
                            "run_id": run_id,
                            "recorded_at_ms": 12345,
                        }
                        with inner.trace_path.open("ab") as handle:
                            handle.write((json.dumps(marker) + "\n").encode("ascii"))

                    inner.timer = threading.Timer(0.03, complete_batch)
                    inner.timer.start()

        scratch = tempfile.TemporaryDirectory(prefix="g5a-end-marker-delay-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        socket_client = DelayedLogicalBatchMarkerSocket(
            root / "debug" / "combat_turn_trace.jsonl")
        session, _ = _g5a_trace_session(root, socket_client)
        result = session.send_turn(
            step["label"], step["input"], step["character"], fixture_step=step)

        self.assertGreaterEqual(result.elapsed_seconds, 0.025)
        self.assertFalse(result.timed_out)
        marker = session.g5_step_receipts[-1]["server_completion_marker"]
        self.assertEqual(marker["observation"], "combat_logical_batch_completed")
        self.assertEqual(marker["batch_id"], step["trace_batch_id"])
        self.assertEqual(marker["run_id"], run_id)

    def test_g5a_end_times_out_without_matching_run_logical_batch_marker(self):
        step = fixtures.build_g5a_script_steps(1)[-1]
        run_id = "g5a-driver-run"

        class ForeignRunMarkerSocket(FakeSocket):
            def __init__(inner, trace_path):
                super().__init__()
                inner.trace_path = pathlib.Path(trace_path)

            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["status_update"]({
                        "is_processing": False, "message": "The round is settled.",
                    })
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "The DM acknowledgement arrived.",
                    })
                    marker = {
                        "schema_version": 1,
                        "event_type": "combat_observation",
                        "observation": "combat_logical_batch_completed",
                        "batch_id": step["trace_batch_id"],
                        "accepted_batch": True,
                        "validation_accepted": True,
                        "run_id": run_id + "-foreign",
                        "recorded_at_ms": 12345,
                    }
                    with inner.trace_path.open("ab") as handle:
                        handle.write((json.dumps(marker) + "\n").encode("ascii"))

        scratch = tempfile.TemporaryDirectory(prefix="g5a-end-foreign-marker-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        session, _ = _g5a_trace_session(
            root, ForeignRunMarkerSocket(root / "debug" / "combat_turn_trace.jsonl"),
            turn_timeout=0.1,
        )
        with self.assertRaisesRegex(
                capture_drive.DriverConnectionError,
                "named scenario stopped after first timeout"):
            session.send_turn(step["label"], step["input"], step["character"], fixture_step=step)
        receipt = session.g5_step_receipts[-1]
        self.assertTrue(receipt["timed_out"])
        self.assertIsNone(receipt["server_completion_marker"])

    def test_g5a_action_step_keeps_backend_output_completion_contract(self):
        step = fixtures.build_g5a_script_steps(1)[0]

        class ActionOutputSocket(FakeSocket):
            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["status_update"]({
                        "is_processing": False, "message": "Idle.",
                    })
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "The directive is recorded.",
                    })

        scratch = tempfile.TemporaryDirectory(prefix="g5a-action-output-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        session, _ = _g5a_trace_session(
            root, ActionOutputSocket(), turn_timeout=0.6)
        result = session.send_turn(
            step["label"], step["input"], step["character"], fixture_step=step)
        self.assertFalse(result.timed_out)
        self.assertNotIn("server_completion_marker", session.g5_step_receipts[-1])

    def test_g5t_exit_waits_for_marker_after_silent_post_combat_flow(self):
        step = fixtures.build_g5t_script_steps(1)[-1]

        class DelayedExitMarkerSocket(FakeSocket):
            def __init__(inner, trace_path):
                super().__init__()
                inner.trace_path = pathlib.Path(trace_path)
                inner.timer = None

            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    # The observed exit flow has no useful status edge after narration.
                    inner.handlers["status_update"]({
                        "is_processing": False, "message": "Combat in progress - awaiting your action",
                    })
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "Combat is resolved.",
                    })
                    ordinary_marker = {
                        "schema_version": 1, "event_type": "stage",
                        "stage": "turn_end", "elapsed_ms": 0,
                        "batch_id": step["trace_batch_id"],
                    }
                    with inner.trace_path.open("ab") as handle:
                        handle.write((json.dumps(ordinary_marker) + "\n").encode("utf-8"))

                    def finish_exit_flow():
                        marker = {
                            "schema_version": 1, "event_type": "stage",
                            "stage": "combat_exit_complete", "elapsed_ms": 0,
                            "batch_id": step["trace_batch_id"],
                            "encounter_id": "g5t-commander-p1",
                        }
                        with inner.trace_path.open("ab") as handle:
                            handle.write((json.dumps(marker) + "\n").encode("utf-8"))

                    inner.timer = threading.Timer(0.03, finish_exit_flow)
                    inner.timer.start()

        scratch = tempfile.TemporaryDirectory(prefix="g5t-exit-marker-delay-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        socket_client = DelayedExitMarkerSocket(root / "debug" / "combat_turn_trace.jsonl")
        session, _ = _g5t_trace_session(root, socket_client)
        result = session.send_turn(
            step["label"], step["input"], step["character"], fixture_step=step)

        self.assertGreaterEqual(result.elapsed_seconds, 0.025)
        self.assertFalse(result.timed_out)
        marker = session.g5_step_receipts[-1]["server_completion_marker"]
        self.assertEqual(marker["stage"], "combat_exit_complete")
        self.assertEqual(marker["batch_id"], step["trace_batch_id"])
        self.assertTrue(session._g5t_combat_is_over())

    def test_g5t_marker_missing_fails_at_turn_timeout(self):
        class MarkerlessSocket(FakeSocket):
            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["status_update"]({
                        "is_processing": False, "message": "idle before narration",
                    })
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "Output arrived, trace did not.",
                    })

        scratch = tempfile.TemporaryDirectory(prefix="g5t-marker-missing-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        session, _ = _g5t_trace_session(root, MarkerlessSocket(), turn_timeout=0.04)
        step = fixtures.build_g5t_script_steps(1)[0]
        with self.assertRaisesRegex(
                capture_drive.DriverConnectionError, "named scenario stopped after first timeout"):
            session.send_turn(step["label"], step["input"], step["character"], fixture_step=step)
        self.assertTrue(session.g5_step_receipts[-1]["timed_out"])
        self.assertIsNone(session.g5_step_receipts[-1]["server_completion_marker"])
        self.assertFalse(session._g5t_combat_is_over())

    def test_g5t_action_step_uses_combat_command_decision_marker(self):
        step = fixtures.build_g5t_script_steps(1)[1]

        class ActionMarkerSocket(FakeSocket):
            def __init__(inner, trace_path):
                super().__init__()
                inner.trace_path = pathlib.Path(trace_path)

            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["game_output"]({
                        "type": "narration", "content": "The attack is resolved.",
                    })
                    action_id = capture_drive.combat_latency_trace.build_work_unit_trace_context(
                        step["round"], step["phase"], step["character"]
                    )["action_id"]
                    marker = {
                        "schema_version": 1, "event_type": "decision",
                        "decision_point": "combat_command_fast_path", "action_id": action_id,
                    }
                    with inner.trace_path.open("ab") as handle:
                        handle.write((json.dumps(marker) + "\n").encode("utf-8"))

        scratch = tempfile.TemporaryDirectory(prefix="g5t-action-marker-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        session, _ = _g5t_trace_session(
            root, ActionMarkerSocket(root / "debug" / "combat_turn_trace.jsonl"))
        result = session.send_turn(
            step["label"], step["input"], step["character"], fixture_step=step)
        self.assertFalse(result.timed_out)
        marker = session.g5_step_receipts[-1]["server_completion_marker"]
        self.assertEqual(marker["decision_point"], "combat_command_fast_path")
        self.assertEqual(marker["action_id"], "pc:r2:acheron")

    def test_g5t_exit_marker_is_required_before_combat_ended_skip(self):
        args = _args(None, 1, ROOT / "tmp")
        session = capture_drive.CaptureSession(args, socket_client=FakeSocket())
        session.capture_gate = "g5t"
        session._on_game_output({"type": "narration", "content": "Combat complete."})
        self.assertFalse(session._g5t_combat_is_over())
        session._g5t_exit_marker_seen = True
        self.assertTrue(session._g5t_combat_is_over())

        non_g5t = capture_drive.CaptureSession(args, socket_client=FakeSocket())
        non_g5t.capture_gate = "g4"
        non_g5t._on_game_output({"type": "narration", "content": "Combat complete."})
        self.assertTrue(non_g5t._g5t_combat_is_over())

    def test_main_emits_exit_marker_after_both_post_combat_narrations(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("from utils.combat_latency_trace import trace_combat_exit_complete", source)

        normal_start = source.index('result.get("status") == "needs_post_combat_narration"')
        normal_call = source.index("post_combat_result = process_ai_response(", normal_start)
        normal_marker = source.index("trace_combat_exit_complete()", normal_call)
        normal_return = source.index("return post_combat_result", normal_marker)
        self.assertLess(normal_call, normal_marker)
        self.assertLess(normal_marker, normal_return)

        resume_start = source.index("dialogue_summary, _ = run_combat_simulation(")
        resume_call = source.index("process_ai_response(", resume_start)
        resume_marker = source.index("trace_combat_exit_complete(active_encounter_id)", resume_call)
        self.assertLess(resume_call, resume_marker)

    def test_echo_without_backend_reply_hits_bounded_timeout(self):
        class EchoOnlySocket(FakeSocket):
            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["game_output"]({"type": "user-input", "content": data["input"]})
                    inner.handlers["status_update"]({"is_processing": False, "message": "idle"})

        scratch = tempfile.TemporaryDirectory(prefix="capture-echo-timeout-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        args = _args(None, 1, pathlib.Path(scratch.name))
        args.turn_timeout = 0.025
        args.turn_quiet_seconds = 0.005
        session = capture_drive.CaptureSession(args, socket_client=EchoOnlySocket())
        session.current_character = "Acheron"
        session.register_handlers()
        result = session.send_turn("no reply", "look around", "Acheron")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.new_game_outputs, 1)
        self.assertEqual(result.backend_output_count, 0)
        self.assertEqual(session.timeout_count, 1)

    def test_g4_timeout_raises_before_any_later_input_can_be_queued(self):
        class EchoOnlySocket(FakeSocket):
            def emit(inner, event, data=None):
                inner.emitted.append((event, data))
                if event == "user_input":
                    inner.handlers["game_output"]({"type": "user-input", "content": data["input"]})
                    inner.handlers["status_update"]({"is_processing": False, "message": "idle"})

        scratch = tempfile.TemporaryDirectory(prefix="g4-timeout-stop-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        args = _args("narrator-dialogue-travel", 1, pathlib.Path(scratch.name))
        args.gate = "g4"
        args.turn_timeout = 0.02
        args.turn_quiet_seconds = 0.002
        socket_client = EchoOnlySocket()
        session = capture_drive.CaptureSession(args, socket_client=socket_client)
        session.capture_profile = fixtures.build_gate_profile("g4", "narrator-dialogue-travel", 1)
        session.current_character = "Acheron"
        session.register_handlers()
        with self.assertRaisesRegex(capture_drive.DriverConnectionError, "timeout"):
            session.send_turn("first", "first input", "Acheron")
        self.assertEqual([event for event, _data in socket_client.emitted], ["user_input"])
        self.assertEqual(session.steps_sent, 1)

    def test_named_smoke_timeout_or_cap_fail_stops_after_one_step_and_preserves_partial_bundle(self):
        class AdvancingClock:
            def __init__(self):
                self.now = 1000.0

            def time(self):
                return self.now

        class BusyFirstStepSocket(FakeSocket):
            def __init__(self, clock, cap):
                super().__init__()
                self.clock = clock
                self.cap = cap

            def emit(self, event, data=None):
                self.emitted.append((event, data))
                if event == "start_game":
                    self.handlers["game_output"]({"type": "narration", "content": "ready"})
                    self.handlers["status_update"]({"is_processing": False, "message": "ready"})
                elif event == "user_input":
                    self.clock.now += 151.0
                    if self.cap:
                        self.handlers["game_output"]({"type": "narration", "content": "still processing"})
                    self.handlers["status_update"]({"is_processing": True, "message": "busy"})

        class PartyResponse(FakeHealthResponse):
            pass

        for cap in (False, True):
            with self.subTest(cap=cap):
                capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
                scratch = tempfile.TemporaryDirectory(
                    prefix="named-fail-stop-", dir=str(capture_evidence.RUN_ROOT)
                )
                self.addCleanup(scratch.cleanup)
                root = pathlib.Path(scratch.name)
                state_root = root / "state"
                (state_root / "debug").mkdir(parents=True)
                (state_root / "modules" / "encounters").mkdir(parents=True)
                (state_root / "model_config.py").write_text(
                    "ENABLE_COMBAT_TURN_TRACE = True\n", encoding="ascii"
                )
                (state_root / "party_tracker.json").write_text(json.dumps({
                    "partyMembers": ["Acheron"], "active_character": "Acheron",
                    "worldConditions": {"activeCombatEncounter": "capture_one_pc"},
                }), encoding="ascii")
                (state_root / "modules" / "encounters" / "encounter_capture_one_pc.json").write_text(
                    json.dumps({"encounterId": "capture_one_pc", "creatures": []}), encoding="ascii"
                )
                trace_source = state_root / "debug" / "combat_turn_trace.jsonl"
                trace_source.write_text("", encoding="ascii")
                run_dir = root / "run"
                args = _args("combat-smoke", 1, root)
                args.turn_timeout = 150.0
                args.run_dir = str(run_dir)
                args.state_root = str(state_root)
                args.trace_src = str(trace_source)
                args.trace_dst = None
                args.transcript = None
                clock = AdvancingClock()
                fake_socket = BusyFirstStepSocket(clock, cap)
                post_calls = []
                get_calls = []

                def fake_post(url, **kwargs):
                    post_calls.append((url, kwargs))
                    return FakeResponse()

                def fake_get(url, **kwargs):
                    get_calls.append((url, kwargs))
                    return PartyResponse(["Acheron"])

                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch.object(
                    capture_drive.time, "time", side_effect=clock.time
                ):
                    result = capture_drive.run(
                        args, socket_factory=lambda: fake_socket,
                        http_post=fake_post, http_get=fake_get,
                    )

                self.assertEqual(result, capture_drive.EXIT_START_FAILURE, output.getvalue())
                self.assertEqual([event for event, _payload in fake_socket.emitted], [
                    "start_game", "user_input",
                ])
                self.assertEqual(len(post_calls), 1)
                self.assertEqual(post_calls[0][0].endswith("/api/party/set_active"), True)
                self.assertEqual(len(get_calls), 1)  # Existing read-only finally health observation.
                self.assertTrue((run_dir / "snapshots" / "step-001-before.json").is_file())
                self.assertTrue((run_dir / "snapshots" / "step-001-after.json").is_file())
                for artifact in ("transcript.log", "trace.jsonl", "report.json", "checks.json", "manifest.json"):
                    self.assertTrue((run_dir / artifact).is_file(), artifact)
                after = json.loads((run_dir / "snapshots" / "step-001-after.json").read_text(encoding="utf-8"))
                observation = after["observation"]
                self.assertEqual(observation["timed_out"], not cap)
                self.assertTrue(observation["cap_reached"])
                self.assertEqual(observation["runtimeTrace"].get("reason"), "idle_not_observed")

    def test_apply_failure_overrides_validated_batch_readiness(self):
        profile = fixtures.build_capture_profile("combat-smoke", 1)
        old_bare = fixtures._character_payload("Acheron", fixtures.ONE_PC_INITIATIVE)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(old_bare, json.loads((ROOT / "schemas" / "char_schema.json").read_text(encoding="utf-8")))
        def state(hp):
            return {"records": {
                "party_tracker.json": {"status": "ok", "partyMembers": ["Acheron"],
                                       "active_character": "Acheron"},
                "selected_encounter": {"status": "ok", "encounterId": "capture_test",
                                        "creatures": [
                                            {"name": "Acheron", "type": "player", "status": "alive",
                                             "currentHitPoints": hp},
                                            {"name": "Goblin", "type": "enemy", "status": "alive",
                                             "currentHitPoints": 20}]},
                "characters/acheron.json": {"read_status": "ok", "name": "Acheron", "hitPoints": hp},
            }}
        before, after = state(20), state(12)
        checks = capture_evidence.observed_checks(
            profile,
            before, after, {}, [{"before": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 0}},
                                              "records": copy.deepcopy(before["records"])},
                                  "after": {"observation": {"runtimeTrace": {"status": "captured", "offset_bytes": 100}},
                                             "records": copy.deepcopy(after["records"])}}], [
                {"observation": "combat_validation_result", "validation_accepted": True,
                 "logical_turn": 1, "_source_byte_start": 1, "_source_byte_end": 5},
                {"observation": "combat_action_batch", "validation_accepted": True,
                 "logical_turn": 1, "_source_byte_start": 5, "_source_byte_end": 9},
                {"observation": "combat_logical_batch_completed", "accepted_batch": True,
                 "logical_turn": 1, "_source_byte_start": 9, "_source_byte_end": 10},
                {"observation": "combat_apply_result", "domain": "character",
                  "operation": "update_character_info_ops", "target": "Acheron",
                  "applied": False, "failure": "false_return",
                  "_source_byte_start": 10, "_source_byte_end": 20},
                {"observation": "combat_apply_result", "domain": "character",
                 "operation": "update_character_info_ops", "target": "Acheron",
                  "ops": [{"op": "hp_delta", "delta": -8}], "applied": True,
                  "_source_byte_start": 25, "_source_byte_end": 35},
            ],
        )
        by_id = {row["id"]: row for row in checks}
        self.assertEqual(by_id["mechanical_apply_outcomes"]["status"], "FAIL")
        self.assertEqual(by_id["hp_delta_snapshot_reconciliation"]["status"], "PASS")
        self.assertEqual(by_id["accepted_logical_batch_once"]["status"], "PASS")
        manifest = {"scenario": {"id": "combat-smoke"}, "party": {"size": 1}}
        evaluation = capture_evidence.evaluate_evidence(
            manifest, checks, {"matrix_keys": ["combat-smoke:p1"],
                               "required_evidence_status": "ok"},
            run_dir=ROOT / "tmp" / "apply-failure-test",
            integrity={"failures": []}, profile=profile,
        )
        self.assertEqual(evaluation["automated_status"], "FAIL")
        self.assertIn("failed_required_checks", evaluation["problems"])

    def setUp(self):
        self._guards = ExitStack()
        self.addCleanup(self._guards.close)
        self._guards.enter_context(patch("socket.socket", side_effect=_network_tripwire))
        self._guards.enter_context(patch("socket.create_connection", side_effect=_network_tripwire))
        self._guards.enter_context(patch("urllib.request.urlopen", side_effect=_network_tripwire))
        self._guards.enter_context(patch("http.client.HTTPConnection.connect", side_effect=_network_tripwire))
        self._guards.enter_context(patch("builtins.open", side_effect=_guard_write_open))
        self._guards.enter_context(patch("io.open", side_effect=_guard_write_open))
        self._guards.enter_context(patch("os.open", side_effect=_guard_os_open))
        self._guards.enter_context(patch.object(capture_drive.socketio, "Client", side_effect=_network_tripwire))
        self._guards.enter_context(patch.object(capture_drive.requests_module, "post", side_effect=_network_tripwire))

    def _run_fake(
        self, scenario, party, branch=None, phase=None,
        pending_initiative=False, pending_enemy=False,
    ):
        scratch = tempfile.TemporaryDirectory(prefix="capture-drive-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        directory = pathlib.Path(scratch.name)
        self.assertTrue(directory.resolve().is_relative_to((ROOT / "tmp").resolve()))
        tracker_path = None
        http_get = None
        if scenario == "surrender-exit" and branch == "explicit-exit":
            tracker_path = directory / "party_tracker.json"
            tracker_path.write_text(json.dumps({
                "partyMembers": [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES),
                "worldConditions": {"activeCombatEncounter": "capture_one_pc"},
            }), encoding="utf-8")
            encounter_dir = directory / "modules" / "encounters"
            encounter_dir.mkdir(parents=True)
            (encounter_dir / "encounter_capture_one_pc.json").write_text(json.dumps({
                "encounterId": "capture_one_pc", "creatures": []
            }), encoding="utf-8")
            fake_socket = DelayedExplicitExitSocket(tracker_path)
            expected_roster = ([fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES))
            http_get = lambda url, **kwargs: FakeHealthResponse(expected_roster)
        else:
            fake_socket = FakeSocket(pending_initiative, pending_enemy)
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

        args = _args(scenario, party, directory, branch, phase)
        args.state_root = str(directory)
        args.selected_encounter_id = "capture_one_pc"
        with patch.object(capture_drive.socketio, "Client", side_effect=_forbidden), patch.object(
            capture_drive.requests_module, "post", side_effect=_forbidden
        ):
            session = capture_drive.CaptureSession(args, socket_client=fake_socket, http_post=fake_post,
                                                   http_get=http_get)
        with contextlib.redirect_stdout(io.StringIO()):
            session.open_transcript()
            try:
                session.register_handlers()
                self.assertTrue(session.start_session())
                self.assertEqual(session.run_scenario(), capture_drive.EXIT_OK)
            finally:
                session.disconnect()
                session.close_transcript()
        emitted_inputs = [payload for event, payload in fake_socket.emitted if event == "user_input"]
        self.assertEqual(len(emitted_inputs), session.turn_index)
        profile = (
            fixtures.build_capture_profile(scenario, party, branch or "", phase or "")
            if scenario else None
        )
        if profile is not None:
            self.assertLessEqual(session.steps_sent, profile["max_steps"])
            self.assertLessEqual(session.control_requests_sent, profile["max_requests"])
        if not (scenario == "resume-replay" and phase == "replay"):
            self.assertTrue(calls)
        self.assertTrue(all(call[0].endswith("/api/party/set_active") for call in calls))
        self.assertTrue(all(call[1]["json"].keys() == {"character"} for call in calls))
        self.assertTrue(all(event in ("start_game", "user_input") for event, _data in fake_socket.emitted))
        self.assertEqual(fake_socket.emitted[0][0], "start_game")
        self.assertTrue(all(
            isinstance(payload.get("input"), str) and isinstance(payload.get("character"), str)
            for event, payload in fake_socket.emitted if event == "user_input"
        ))
        return emitted_inputs, session, fake_socket, calls

    def _write_resume_bundle(self, bundle_root, state_root, phase, *, chain_id="resume-chain",
                             start_hp=20, end_hp=19, end_xp=0, source_override=None,
                             party_override=None, history_message="completed seed turn",
                             history_append=False, history_missing=False, end_slots=1):
        run_dir = pathlib.Path(bundle_root) / phase
        run_dir.mkdir()
        state_root = pathlib.Path(state_root)
        (state_root / "characters").mkdir(parents=True, exist_ok=True)
        (state_root / "modules" / "encounters").mkdir(parents=True, exist_ok=True)
        (state_root / "modules" / "conversation_history").mkdir(parents=True, exist_ok=True)
        (state_root / "save_games").mkdir(parents=True, exist_ok=True)
        party_names = list(party_override or ["Acheron"])
        party = {"partyMembers": party_names, "active_character": party_names[0],
                 "worldConditions": {"activeCombatEncounter": "capture_one_pc"}}
        (state_root / "party_tracker.json").write_text(json.dumps(party), encoding="utf-8")
        enemy_hp = start_hp
        encounter = {"id": "capture_one_pc", "encounterId": "capture_one_pc",
                     "encounterSummary": "Capture Arena resume seed", "combat_round": 1,
                     "initiativeMode": "one_pc_compatible", "initiativeWinner": "pcGroup",
                     "roundStartsWith": "pcGroup", "awaitingPcGroupRoll": False,
                     "openingEnemyBatchPending": False,
                     "creatures": [
                         {"name": "Acheron", "type": "player", "status": "alive",
                          "currentHitPoints": 20, "maxHitPoints": 20, "conditions": [],
                          "deathSaves": {"successes": 0, "failures": 0}},
                         {"name": "Goblin", "type": "enemy", "status": "alive",
                          "currentHitPoints": enemy_hp, "maxHitPoints": 20, "conditions": [],
                          "deathSaves": {"successes": 0, "failures": 0}},
                     ]}
        encounter_path = state_root / "modules" / "encounters" / "encounter_capture_one_pc.json"
        encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
        character = {"name": "Acheron", "type": "player", "character_type": "player",
                     "hitPoints": 20, "maxHitPoints": 20, "status": "alive",
                     "deathSaves": {"successes": 0, "failures": 0},
                     "spellcasting": {"spellSlots": {"level1": {"current": 1, "max": 1}}},
                     "classFeatures": [], "experience_points": 0,
                     "currency": {"gold": 0}}
        (state_root / "characters" / "acheron.json").write_text(json.dumps(character), encoding="utf-8")
        history = state_root / "modules" / "conversation_history" / "combat.json"
        if not history_missing:
            history.write_text(json.dumps({"messages": [{"role": "user", "content": history_message}]}), encoding="utf-8")
        profile = fixtures.build_capture_profile("resume-replay", 1, phase=phase)
        before = capture_evidence.snapshot_state(state_root, "before-run", "capture_one_pc")
        capture_evidence._write_new(run_dir / "snapshots" / "before-run.json", before)
        step_count = 2 if phase == "complete" else 0
        step_refs = []
        if phase == "complete":
            capture_evidence.write_step_snapshot(run_dir, state_root, 1, "before", "capture_one_pc",
                {"label": "completed turn attack", "input": "/att Goblin 20 training blade", "character": "Acheron",
                 "runtimeTrace": {"status": "captured", "offset_bytes": 0}})
            capture_evidence.write_step_snapshot(run_dir, state_root, 1, "after", "capture_one_pc",
                {"label": "completed turn attack", "input": "/att Goblin 20 training blade", "character": "Acheron",
                 "runtimeTrace": {"status": "captured", "offset_bytes": 116}})
            capture_evidence.write_step_snapshot(run_dir, state_root, 2, "before", "capture_one_pc",
                {"label": "completed turn damage", "input": "/dmg 1", "character": "Acheron",
                 "runtimeTrace": {"status": "captured", "offset_bytes": 116}})
            encounter["creatures"][1]["currentHitPoints"] = end_hp
            encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
            character["experience_points"] = end_xp
            (state_root / "characters" / "acheron.json").write_text(json.dumps(character), encoding="utf-8")
            capture_evidence.write_step_snapshot(run_dir, state_root, 2, "after", "capture_one_pc",
                {"label": "completed turn damage", "input": "/dmg 1", "character": "Acheron",
                 "runtimeTrace": {"status": "captured", "offset_bytes": 300}})
            step_refs = ["snapshots/step-%03d-%s.json" % (i, edge)
                         for i in (1, 2) for edge in ("before", "after")]
        elif end_hp != start_hp or end_xp or end_slots != 1:
            encounter["creatures"][1]["currentHitPoints"] = end_hp
            encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
            character["experience_points"] = end_xp
            character["spellcasting"]["spellSlots"]["level1"]["current"] = end_slots
            (state_root / "characters" / "acheron.json").write_text(json.dumps(character), encoding="utf-8")
        if history_append:
            history_data = json.loads(history.read_text(encoding="utf-8"))
            history_data["messages"].append({"role": "assistant", "content": "Acheron completed the turn."})
            history_data["messages"].append({"role": "system", "content": "Encounter Details: volatile context"})
            history.write_text(json.dumps(history_data), encoding="utf-8")
        after = capture_evidence.snapshot_state(state_root, "after-run", "capture_one_pc")
        capture_evidence._write_new(run_dir / "snapshots" / "after-run.json", after)
        trace_records = [
            {"event_type": "stage", "stage": "synthetic_resume_fixture", "elapsed_ms": 1,
             "fixture": "synthetic-test", "mode": "one_pc"},
            {"event_type": "decision", "decision_point": "combat_command_fast_path",
             "decision_source": "deterministic", "provider_call_avoided": True,
             "fixture": "synthetic-test", "mode": "one_pc"},
        ]
        trace_path = run_dir / "trace.jsonl"
        trace_path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in trace_records), encoding="ascii")
        report = combat_latency_report.build_report(trace_path)
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        (run_dir / "transcript.log").write_text(
            "[driver] capture start\n" + "".join(
                "[driver] step=%d start label=x\n[driver] step=%d done in 1s\n" % (i, i)
                for i in range(1, step_count + 1)), encoding="utf-8")
        (run_dir / "server.log").write_text("synthetic fake server output\n", encoding="utf-8")
        session = SimpleNamespace(
            socket=object(), transport_injected=True, url="http://localhost:8360",
            step_attempts=step_count, steps_sent=step_count,
            control_request_attempts=4 if step_count else 1,
            control_request_calls=4 if step_count else 1,
            control_request_failures=0,
            control_requests_sent=4 if step_count else 1,
            blocked_step_attempts=0, blocked_control_attempts=0,
            timeout_count=0, start_timed_out=False, step_caps_reached=0,
            idle_settle_caps_reached=0, active_switch_failures=0,
            active_switch_attempts=1 if step_count else 0,
            active_switch_requests_sent=1 if step_count else 0,
            health_read_attempts=0, party=1,
        )
        args = SimpleNamespace(
            state_root=str(state_root), chain_id=chain_id,
            declared_provider=None, declared_profile="test-only", declared_model=None,
            start_timeout=10.0, turn_timeout=10.0, turn_quiet_seconds=0.01,
        )
        seed_identity = {"roster": party_names, "active_encounter": "capture_one_pc"}
        manifest = capture_evidence.build_manifest(profile, args, session, seed_identity, "test-start")
        seed_profile = dict(profile.get("seed", {}))
        seed_profile.pop("resume_phase", None)
        seed_hash = hashlib.sha256(json.dumps(seed_profile, sort_keys=True).encode()).hexdigest()
        manifest["seed"].update({"profile_seed": seed_profile, "seed_profile_sha256": seed_hash, "seed_id": seed_hash})
        manifest["run_id"] = run_dir.name
        manifest["timestamps"]["ended_at"] = "test-end"
        manifest["trace_span"] = {"status": "copied", "offset_before_bytes": 0,
                                   "span_bytes": trace_path.stat().st_size,
                                   "start_status": "captured"}
        manifest["trace_start_offset"] = {"status": "captured", "source_byte_offset": 0,
                                          "prefix_sha256": hashlib.sha256(b"").hexdigest()}
        manifest["snapshot_chain"] = {
            "before_projection": before["mechanical_projection"],
            "after_projection": after["mechanical_projection"],
            "before_history_inventory": capture_evidence._history_inventory(before),
            "after_history_inventory": capture_evidence._history_inventory(after),
        }
        manifest["counts"].update({"attempted_control_request_count": session.control_request_attempts,
                                   "confirmed_sent_control_request_count": session.control_requests_sent,
                                   "provider_calls": {"count": 0, "source": "runtime-trace"}})
        artifacts = {
            "transcript": "transcript.log", "server_log": "server.log", "trace": "trace.jsonl",
            "report": "report.json", "before_snapshot": "snapshots/before-run.json",
            "after_snapshot": "snapshots/after-run.json", "checks": "checks.json",
            "step_snapshots": step_refs, "missing_step_snapshots": [],
            "required_evidence_status": report["status"],
            "trace_copy": {"status": "copied", "source_records": len(trace_records),
                           "destination_records": len(trace_records)},
            "copy_errors": [], "matrix_keys": [capture_evidence.matrix_key("resume-replay", 1, phase=phase)],
            "health_probe": {"status": "not_checked"}, "health_read_attempts": 0,
        }
        manifest["artifacts"] = artifacts
        steps, _errors = capture_evidence.load_step_snapshots(run_dir, manifest)
        checks = capture_evidence.observed_checks(profile, before, after, artifacts, steps,
                                                  report["combat_observations"])
        (run_dir / "checks.json").write_text(json.dumps({"checks": checks, "primary_verdict": "PENDING"}), encoding="utf-8")
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run_dir, artifacts)
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run_dir

    def test_profiles_cover_each_named_scenario_for_both_party_shapes(self):
        for scenario in fixtures.CAPTURE_SCENARIOS:
            for party in (1, 4):
                with self.subTest(scenario=scenario, party=party):
                    if scenario == "surrender-exit":
                        for branch in fixtures.CAPTURE_BRANCHES:
                            self._run_fake(scenario, party, branch=branch)
                    elif scenario == "resume-replay":
                        for phase in fixtures.CAPTURE_RESUME_PHASES:
                            self._run_fake(scenario, party, phase=phase)
                    else:
                        inputs, session, _socket, calls = self._run_fake(scenario, party)
                        if scenario == "combat-smoke":
                            if party == 1:
                                self.assertEqual([row["character"] for row in inputs], ["Acheron"] * 4)
                            else:
                                self.assertEqual(
                                    [row["character"] for row in inputs[:6]],
                                    ["Acheron", "Acheron", "Merisiel", "Merisiel", "Kira", "Vitreol"],
                                )
                                self.assertEqual(session.turn_index, 19)
                            self.assertTrue(calls)

    def test_pending_enemy_end_branches_and_optional_init_fallback_fit_named_bounds(self):
        four_inputs, four, _socket, _calls = self._run_fake(
            "combat-smoke", 4, pending_initiative=True, pending_enemy=True
        )
        self.assertEqual(four_inputs[0]["input"], "/init 15")
        self.assertEqual(sum(row["input"] == "/end" for row in four_inputs), 3)
        self.assertEqual((four.step_attempts, four.steps_sent), (22, 22))
        self.assertEqual(four.control_requests_sent, 35)
        self.assertEqual((four.blocked_step_attempts, four.blocked_control_attempts), (0, 0))

        one_inputs, one, _socket, _calls = self._run_fake(
            "combat-smoke", 1, pending_initiative=True, pending_enemy=True
        )
        self.assertEqual(one_inputs[0]["input"], "/init 15")
        self.assertEqual(sum(row["input"] == "/end" for row in one_inputs), 1)
        self.assertEqual((one.step_attempts, one.steps_sent), (5, 5))
        self.assertEqual(one.control_requests_sent, 7)

        legacy_inputs, legacy, _socket, _calls = self._run_fake(None, 4)
        self.assertEqual(len(legacy_inputs), 19)
        self.assertEqual(legacy.steps_sent, 19)

    def test_cap_blocked_step_and_control_are_not_reported_as_sent(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-cap-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        fake_socket = FakeSocket()
        http_calls = []
        args = _args("initiative-pc", 1, pathlib.Path(scratch.name))
        session = capture_drive.CaptureSession(
            args, socket_client=fake_socket,
            http_post=lambda *call_args, **kwargs: http_calls.append((call_args, kwargs)),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            session.register_handlers()
            self.assertTrue(session.start_session())
        session.capture_profile = {
            "scenario_id": "bounded-test", "max_steps": 0,
            "max_requests": 1, "max_active_switches": 0,
        }
        session.control_request_attempts = 1
        session.control_request_calls = 1
        session.control_requests_sent = 1
        session.control_request_count = 1
        with self.assertRaises(capture_drive.DriverConnectionError):
            session.send_turn("blocked", "should not emit", "Acheron")
        with self.assertRaises(capture_drive.DriverConnectionError):
            session.set_active_character("Acheron")
        self.assertEqual([event for event, _payload in fake_socket.emitted], ["start_game"])
        self.assertEqual(http_calls, [])
        self.assertEqual((session.step_attempts, session.steps_sent), (1, 0))
        self.assertEqual(session.control_requests_sent, 1)
        self.assertEqual((session.blocked_step_attempts, session.blocked_control_attempts), (1, 1))
        session.disconnect()
        session.close_transcript()

    def test_death_save_wrong_actor_is_only_declared_for_four_party(self):
        one, _session, _socket, _calls = self._run_fake("death-save", 1)
        four, _session, _socket, _calls = self._run_fake("death-save", 4)
        self.assertEqual([item["character"] for item in one], ["Acheron", "Acheron"])
        self.assertEqual([item["character"] for item in four], ["Merisiel", "Acheron", "Acheron"])
        self.assertFalse(fixtures.build_capture_profile("death-save", 1)["applicability"]["wrong_actor_death_save"])
        self.assertTrue(fixtures.build_capture_profile("death-save", 4)["applicability"]["wrong_actor_death_save"])

    def test_wrong_actor_and_invalid_roll_leave_pending_actor_and_state_unchanged(self):
        manager = MultiPCCombatManager()
        acheron = PCCombatState(
            "Acheron", status=PCStatus.INCAPACITATED,
            death_save_successes=0, death_save_failures=0, current_hp=0, max_hp=20,
        )
        merisiel = PCCombatState("Merisiel", status=PCStatus.READY, current_hp=20, max_hp=20)
        manager._state.pc_states = {"Acheron": acheron, "Merisiel": merisiel}
        manager._state.current_pc_name = "Acheron"
        manager._state.current_round = 1
        manager._turns.turn_queue = [
            Combatant("Acheron", CombatantType.PC, 20, 0, 20, 14, "unconscious"),
            Combatant("Merisiel", CombatantType.PC, 18, 20, 20, 14, "alive"),
        ]
        before = (manager.get_current_actor().name, manager.get_next_pending_death_save_pc(),
                  acheron.current_hp, acheron.death_save_successes, acheron.death_save_failures,
                  merisiel.current_hp, merisiel.death_save_successes, merisiel.death_save_failures)
        allowed, pending, _message = manager.validate_death_save_input_actor("Merisiel")
        self.assertFalse(allowed)
        self.assertEqual(pending, "Acheron")
        self.assertEqual(manager.parse_death_save_roll_input("21", True)[0:2], (False, None))
        after_rejections = (
            manager.get_current_actor().name, manager.get_next_pending_death_save_pc(),
            acheron.current_hp, acheron.death_save_successes, acheron.death_save_failures,
            merisiel.current_hp, merisiel.death_save_successes, merisiel.death_save_failures,
        )
        self.assertEqual(after_rejections, before)

        valid, roll, _error = manager.parse_death_save_roll_input("10", True)
        self.assertTrue(valid)
        fake_update = ModuleType("updates.update_character_info")
        fake_update.update_character_info = lambda *_args, **_kwargs: True
        with patch.dict(sys.modules, {"updates.update_character_info": fake_update}):
            ok, _message = manager.resolve_death_save_roll("Acheron", roll)
        self.assertTrue(ok)
        self.assertEqual((acheron.death_save_successes, acheron.death_save_failures), (1, 0))
        self.assertEqual((merisiel.death_save_successes, merisiel.death_save_failures), (0, 0))
        self.assertIsNone(manager.get_next_pending_death_save_pc())

    def test_named_seed_shapes_preserve_schema_and_default_latency_payloads(self):
        self.assertEqual(fixtures.build_command_script()[0], "/init 18")
        self.assertEqual(len(fixtures.build_command_script()), 26)
        legacy_mp_script = ["/init 18"]
        for round_number in range(1, 4):
            for name in fixtures.PC_NAMES:
                legacy_mp_script.extend([
                    "%s: /att Goblin Alpha 20 training blade" % name,
                    "%s: /dmg 1 round %d" % (name, round_number),
                ])
            if round_number == 1:
                legacy_mp_script.append("/end (enemy batch trigger)")
        self.assertEqual(
            fixtures.build_command_script(),
            legacy_mp_script,
        )
        self.assertEqual(fixtures.build_one_pc_command_script(), [
            "Acheron: /att Goblin 20 training blade", "Acheron: /dmg 1 round 1",
            "/end (enemy phase completion)",
        ])
        self.assertEqual(
            fixtures.build_capture_profile("combat-smoke", 4)["seed"],
            {"encounter_context": fixtures.build_capture_combat_context(4)},
        )
        self.assertNotEqual(
            fixtures.build_capture_profile("combat-smoke", 4)["seed"],
            fixtures.build_capture_profile("combat-smoke-allied-inactive", 4)["seed"],
        )
        self.assertEqual(fixtures.build_capture_profile("initiative-pc", 4)["seed"]["dmGroup"], 8)
        self.assertEqual(fixtures.build_capture_profile("initiative-dm-tie", 4)["seed"]["expected_roll"], 12)
        party_names = ["Acheron"]
        for scenario, party in (("initiative-pc", 1), ("initiative-dm-tie", 4),
                                ("death-save", 1),
                                ("combat-smoke-allied-inactive", 1),
                                ("combat-smoke-allied-inactive", 4),
                                ("resume-replay", 4)):
            profile = fixtures.build_capture_profile(
                scenario, party, phase="replay" if scenario == "resume-replay" else ""
            )
            payload = fixtures._one_pc_encounter_payload() if party == 1 else fixtures._encounter_payload()
            names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            initiatives = ({fixtures.ONE_PC_NAME: fixtures.ONE_PC_INITIATIVE}
                           if party == 1 else fixtures.PC_INITIATIVES)
            payload["creatures"] = [
                {"name": name, "type": "player", "initiative": initiatives[name],
                 "status": "alive", "conditions": [], "currentHitPoints": 20,
                 "maxHitPoints": 20, "armorClass": 14}
                for name in names
            ] + payload["creatures"]
            fixtures.apply_capture_profile(payload, {"partyMembers": party_names}, profile)
            self.assertTrue(all(isinstance(row.get("name"), str) and row.get("type") for row in payload["creatures"]))
            if scenario == "combat-smoke-allied-inactive":
                ally = next(row for row in payload["creatures"] if row["name"] == "Blairen")
                dead_name = "Inactive Goblin"
                dead = next(row for row in payload["creatures"] if row["name"] == dead_name)
                self.assertEqual((ally["type"], ally["npcType"]), ("npc", "ally"))
                self.assertEqual((dead["currentHitPoints"], dead["status"]), (0, "defeated"))
            if scenario == "death-save":
                acheron = next(row for row in payload["creatures"] if row["name"] == "Acheron")
                self.assertEqual(acheron["deathSaves"], {"successes": 0, "failures": 0})
                self.assertEqual(profile["character_overrides"]["Acheron"]["hitPoints"], 0)
            if scenario == "resume-replay":
                self.assertNotIn("captureCompletedTurn", payload)

    def test_seed_writer_persists_merged_pc_death_state_and_npc_projection_in_fake_fs(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-seed-fs-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        fake_root = pathlib.Path(scratch.name)
        self.assertTrue(fake_root.resolve().is_relative_to((ROOT / "tmp").resolve()))
        files = {}
        active_root = fake_root / "p4"

        class FakePathManager:
            @staticmethod
            def get_character_unified_path(name):
                return (active_root / "characters" / (name.lower() + ".json")).as_posix()

        def fake_writer(relative_path, payload):
            candidate = pathlib.Path(relative_path)
            destination = (candidate if candidate.is_absolute() else active_root / candidate).resolve()
            self.assertTrue(destination.is_relative_to(active_root.resolve()))
            files[destination] = copy.deepcopy(payload)
            return destination

        reference = {
            "module": "Capture_Arena", "area_id": "CTR001", "area_name": "Capture Arena",
            "start_location_id": "CA01", "start_location_name": "Waystone Gate",
        }
        base_character_payload = seed_combat_capture.capture_fixtures._character_payload

        def extended_base_payload(name, initiative):
            payload = base_character_payload(name, initiative)
            payload["personality_traits"] = "preserve this authored base value"
            return payload

        death_profile = fixtures.build_capture_profile("death-save", 4)
        with patch.object(
            seed_combat_capture.capture_fixtures,
            "_character_payload",
            side_effect=extended_base_payload,
        ):
            seed_combat_capture._seed_party(
                reference, list(fixtures.PC_NAMES), 4, death_profile,
                writer=fake_writer, path_manager=FakePathManager(),
            )
        pc_path = (active_root / "characters" / "acheron.json").resolve()
        death_character = files[pc_path]
        self.assertEqual(death_character["personality_traits"], "preserve this authored base value")
        self.assertEqual(death_character["experience_points"], 0)
        self.assertEqual((death_character["hitPoints"], death_character["maxHitPoints"]), (0, 20))
        self.assertEqual(death_character["deathSaves"], {"successes": 0, "failures": 0})
        death_encounter = files[(active_root / "modules/encounters/encounter_capture_mp.json").resolve()]
        death_actor = next(row for row in death_encounter["creatures"] if row["name"] == "Acheron")
        self.assertEqual((death_actor["currentHitPoints"], death_actor["status"]), (0, "unconscious"))
        self.assertEqual(death_actor["deathSaves"], death_character["deathSaves"])
        self.assertEqual(death_actor["conditions"], death_character["condition_affected"])

        active_root = fake_root / "legacy"
        seed_combat_capture._seed_party(
            reference, [fixtures.ONE_PC_NAME], 1, None,
            writer=fake_writer, path_manager=FakePathManager(),
        )
        legacy_character = files[(active_root / "characters" / "acheron.json").resolve()]
        self.assertNotIn("experience_points", legacy_character)

        encounter_schema = json.loads((ROOT / "schemas" / "encounter_schema.json").read_text(encoding="utf-8"))
        party_schema = json.loads((ROOT / "schemas" / "party_schema.json").read_text(encoding="utf-8"))
        character_schema = json.loads((ROOT / "schemas" / "char_schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(death_encounter, encounter_schema)
        for party in (1, 4):
            names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            for scenario in fixtures.CAPTURE_SCENARIOS:
                branches = fixtures.CAPTURE_BRANCHES if scenario == "surrender-exit" else (None,)
                phases = fixtures.CAPTURE_RESUME_PHASES if scenario == "resume-replay" else (None,)
                for branch in branches:
                    for phase in phases:
                        profile = fixtures.build_capture_profile(scenario, party, branch=branch, phase=phase)
                        overrides = profile.get("character_overrides", {})
                        for name in names:
                            record = fixtures.build_capture_character_payload(
                                name, fixtures.PC_INITIATIVES.get(name, fixtures.ONE_PC_INITIATIVE),
                                overrides.get(name),
                            )
                            self.assertNotIn("resources_known", record)
                            jsonschema.validate(record, character_schema)
                            expected_gear = {
                                "Acheron": "training blade",
                                "Merisiel": "training blade",
                                "Kira": "shortsword",
                                "Vitreol": "crossbow, light",
                            }
                            if name in expected_gear:
                                self.assertEqual(record["equipment"][0]["item_name"], expected_gear[name])
                            if name == "Vitreol":
                                self.assertEqual(record["ammunition"], [{
                                    "name": "crossbow bolts", "quantity": 3,
                                    "description": "Standard crossbow bolts for use with crossbows",
                                }])
        for party in (1, 4):
            active_root = fake_root / ("p%d" % party)
            names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            profile = fixtures.build_capture_profile("combat-smoke-allied-inactive", party)
            seed_combat_capture._seed_party(
                reference, names, party, profile,
                writer=fake_writer, path_manager=FakePathManager(),
            )
            ally_path = (active_root / "characters" / "blairen.json").resolve()
            ally = files[ally_path]
            self.assertEqual((ally["name"], ally["type"], ally["character_role"]),
                             (fixtures.CAPTURE_ALLIED_NPC_NAME, "npc", "npc"))
            self.assertNotIn(ally["name"], names)
            tracker = files[(active_root / "party_tracker.json").resolve()]
            self.assertEqual(tracker["partyNPCs"], [{"name": "Blairen", "role": "Ally"}])
            self.assertEqual(tracker["partyMembers"], names)
            encounter_id = "capture_one_pc" if party == 1 else "capture_mp"
            ally_encounter = files[(active_root / "modules/encounters" / ("encounter_%s.json" % encounter_id)).resolve()]
            inactive = next(row for row in ally_encounter["creatures"] if row["name"] == "Inactive Goblin")
            self.assertEqual((inactive["type"], inactive["currentHitPoints"], inactive["status"]),
                             ("enemy", 0, "defeated"))
            self.assertEqual(sum(row["type"] == "enemy" and row["currentHitPoints"] > 0
                                 for row in ally_encounter["creatures"]), 2 if party == 4 else 1)
            jsonschema.validate(ally_encounter, encounter_schema)
            jsonschema.validate(tracker, party_schema)
            jsonschema.validate(ally, character_schema)
        self.assertTrue((ROOT / "web/static/media/npcs/blairen.jpg").is_file())

    def test_named_allied_npc_attack_is_seeded_and_reaches_read_only_projections(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-ally-attack-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        scratch_root = pathlib.Path(scratch.name).resolve()
        schema = json.loads((ROOT / "schemas" / "char_schema.json").read_text(encoding="utf-8"))
        reference = {
            "module": "Capture_Arena", "area_id": "CTR001", "area_name": "Capture Arena",
            "start_location_id": "CA01", "start_location_name": "Waystone Gate",
        }
        previous_cwd = pathlib.Path.cwd()
        try:
            for party_size in (1, 4):
                sandbox = scratch_root / ("party-%d" % party_size)
                (sandbox / "characters").mkdir(parents=True)

                class FakePathManager:
                    @staticmethod
                    def get_character_unified_path(name):
                        return "characters/%s.json" % name.lower().replace(" ", "_")

                def writer(relative_path, payload):
                    destination = (sandbox / relative_path).resolve()
                    self.assertTrue(destination.is_relative_to(sandbox.resolve()))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(payload), encoding="utf-8")
                    return destination

                party_names = [fixtures.ONE_PC_NAME] if party_size == 1 else list(fixtures.PC_NAMES)
                profile = fixtures.build_capture_profile("combat-smoke-allied-inactive", party_size)
                seed_combat_capture._seed_party(
                    reference, party_names, party_size, profile,
                    writer=writer, path_manager=FakePathManager(),
                )
                ally_path = sandbox / "characters" / "blairen.json"
                ally = json.loads(ally_path.read_text(encoding="utf-8"))
                jsonschema.validate(ally, schema)
                self.assertEqual(ally["proficiencies"]["weapons"], ["simple weapons", "martial weapons"])
                self.assertEqual(ally["equipment"][0]["item_name"], "longsword")
                self.assertEqual(ally["equipment"][0]["attack_bonus"], 3)
                self.assertEqual(ally["attacksAndSpellcasting"], [{
                    "name": "longsword", "attackBonus": 3, "damageDice": "1d8",
                    "damageBonus": 1, "damageType": "slashing", "type": "melee",
                    "description": "Melee weapon attack: +3 to hit, reach 5 ft., one target. Hit: 1d8 + 1 slashing damage.",
                }])

                # These are the production read-only prompt and preroll projections.
                before_projection = copy.deepcopy(ally)
                npc_prompt = format_npc_for_combat(ally, "Ally")
                self.assertIn("PROF: armor: none, weapons: simple weapons, martial weapons, tools: none", npc_prompt)
                self.assertIn("EQUIP: longsword", npc_prompt)
                self.assertIn("ATK: longsword (melee, 1d8 slashing)", npc_prompt)

                old_cwd = pathlib.Path.cwd()
                os.chdir(sandbox)
                try:
                    preroll_attacks, count = get_npc_attacks("Blairen")
                finally:
                    os.chdir(old_cwd)
                self.assertEqual((preroll_attacks, count), ([{"name": "longsword"}], 1))
                self.assertEqual(ally, before_projection)

        finally:
            os.chdir(previous_cwd)

        # The common NPC base remains unarmed, and named PCs still inherit no
        # Blairen-only attack data. Bare latency payloads are unchanged.
        self.assertEqual(fixtures.build_capture_npc_payload("Unarmed NPC")["attacksAndSpellcasting"], [])
        self.assertEqual(fixtures.build_capture_character_payload("Acheron", 20)["attacksAndSpellcasting"], [])
        self.assertEqual(fixtures._character_payload("Acheron", 20), {
            "name": "Acheron", "type": "player", "character_type": "player",
            "hitPoints": 20, "maxHitPoints": 20, "armorClass": 14,
            "initiative": 20, "status": "alive",
            "deathSaves": {"successes": 0, "failures": 0},
        })

    def test_named_profiles_seed_party_local_context_and_exact_evidence_contract(self):
        reference = {
            "module": "Capture_Arena", "area_id": "CTR001", "area_name": "Capture Arena",
            "start_location_id": "CA01", "start_location_name": "Waystone Gate",
        }

        class FakePathManager:
            @staticmethod
            def get_character_unified_path(name):
                return "characters/%s.json" % name.lower().replace(" ", "_")

        for scenario in fixtures.CAPTURE_SCENARIOS:
            for party in (1, 4):
                branches = fixtures.CAPTURE_BRANCHES if scenario == "surrender-exit" else (None,)
                phases = fixtures.CAPTURE_RESUME_PHASES if scenario == "resume-replay" else (None,)
                for branch in branches:
                    for phase in phases:
                        with self.subTest(scenario=scenario, party=party, branch=branch, phase=phase):
                            profile = fixtures.build_capture_profile(
                                scenario, party, branch=branch or "", phase=phase or ""
                            )
                            files = {}

                            def fake_writer(relative_path, payload):
                                files[pathlib.Path(relative_path).as_posix()] = copy.deepcopy(payload)

                            party_names = ([fixtures.ONE_PC_NAME] if party == 1
                                           else list(fixtures.PC_NAMES))
                            encounter_id = seed_combat_capture._seed_party(
                                reference, party_names, party, profile,
                                writer=fake_writer, path_manager=FakePathManager(),
                            )
                            encounter = files[
                                "modules/encounters/encounter_%s.json" % encounter_id
                            ]
                            tracker = files["party_tracker.json"]
                            self.assertEqual(tracker["partyMembers"], party_names)
                            projected = filter_encounter_for_system_prompt(encounter)
                            roster = {row["name"] for row in projected["creatures"]}
                            if scenario in ("combat-smoke", "combat-smoke-allied-inactive"):
                                context = fixtures.build_capture_combat_context(
                                    party, include_allied_inactive=(
                                        scenario == "combat-smoke-allied-inactive"
                                    ),
                                )
                                self.assertEqual(profile["seed"]["encounter_context"], context)
                                self.assertEqual(projected["encounterSummary"], context)
                                if party == 1:
                                    self.assertIn("Acheron", context)
                                    self.assertIn("Goblin", context)
                                    for absent in ("Kira", "Vitreol", "Goblin Alpha", "Goblin Beta", "Merisiel"):
                                        self.assertNotIn(absent, context)
                                else:
                                    self.assertIn("Kira", context)
                                    self.assertIn("Goblin Alpha", context)
                                    self.assertIn("Goblin Beta", context)
                                    self.assertIn("Vitreol", context)
                                    self.assertIn("within her reach", context)
                                if scenario == "combat-smoke-allied-inactive":
                                    self.assertIn("Blairen", roster)
                                    self.assertIn("Inactive Goblin", roster)
                                    self.assertIn("not an active hostile", context)
                                    self.assertIn("or an eligible nearest-target candidate", context)
                                    self.assertEqual(
                                        set(profile["seed"]) - {"encounter_context"},
                                        {"allied_npc", "inactive_enemy", "party_ally", "media_asset"},
                                    )
                            else:
                                self.assertNotIn("Kira", projected["encounterSummary"])
                                self.assertNotIn("Vitreol", projected["encounterSummary"])
                                if scenario == "surrender-exit":
                                    last = profile["seed"]["last_hostile"]
                                    if branch == "surrender":
                                        context = profile["seed"]["encounter_context"]
                                        self.assertEqual(projected["encounterSummary"], context)
                                        self.assertIn("voluntarily offered unconditional surrender", context)
                                        self.assertIn("lowered its weapon", context)
                                        self.assertIn("awaits the party's acceptance", context)
                                        last_row = next(
                                            row for row in encounter["creatures"] if row["name"] == last
                                        )
                                        self.assertEqual(
                                            (last_row["status"], last_row["currentHitPoints"],
                                             last_row["maxHitPoints"]),
                                            ("alive", 20, 20),
                                        )
                                        self.assertNotIn(
                                            "Restrained",
                                            last_row["conditions"],
                                        )
                                        self.assertEqual(
                                            tracker["worldConditions"]["activeCombatEncounter"],
                                            encounter_id,
                                        )
                                        if party == 1:
                                            for absent in ("Goblin Alpha", "Goblin Beta", "Kira", "Vitreol"):
                                                self.assertNotIn(absent, context)
                                        else:
                                            self.assertIn("Goblin Beta", context)
                                            for absent in ("Goblin Alpha", "Kira", "Vitreol"):
                                                self.assertNotIn(absent, context)
                                            inactive = next(
                                                row for row in encounter["creatures"]
                                                if row["name"] == "Goblin Alpha"
                                            )
                                            self.assertEqual(
                                                (inactive["status"], inactive["currentHitPoints"]),
                                                ("defeated", 0),
                                            )
                                        for row in files.values():
                                            if isinstance(row, dict) and row.get("type") == "player":
                                                self.assertEqual(row.get("experience_points"), 0)
                                    else:
                                        self.assertNotIn("encounter_context", profile["seed"])
                                        self.assertEqual(
                                            projected["encounterSummary"],
                                            "Capture Arena named scenario seed: surrender-exit",
                                        )

                            expected = capture_evidence._expected_profile_contract(
                                scenario, party, branch, phase
                            )
                            actual = {key: profile.get(key) for key in (
                                "scenario_id", "party_size", "branch", "phase", "seed", "applicability"
                            )}
                            self.assertEqual(actual, expected)
                            forged = copy.deepcopy(actual)
                            forged["seed"]["unexpected"] = "forged"
                            self.assertNotEqual(forged, expected)
                            if scenario == "surrender-exit" and branch == "surrender":
                                forged["seed"]["encounter_context"] = (
                                    "A different creature has offered to surrender."
                                )
                                self.assertNotEqual(forged, expected)
        self.assertIsNone(capture_evidence._expected_profile_contract("combat-smoke", 2, None, None))

    def test_vitreol_named_seed_removes_three_singular_bolts_then_fails_closed(self):
        character = fixtures.build_capture_character_payload("Vitreol", 14)
        jsonschema.validate(character, json.loads((ROOT / "schemas" / "char_schema.json").read_text(encoding="utf-8")))
        for expected in (2, 1, 0):
            applied, updated, error, _unsupported = _apply_character_ops_deterministic(
                character,
                [{"op": "inventory_remove", "item_name": "crossbow bolt",
                  "quantity": 1, "container": "ammunition"}],
            )
            self.assertTrue(applied, error)
            character = updated
            total = sum(row["quantity"] for row in character.get("ammunition", []))
            self.assertEqual(total, expected)
        before = copy.deepcopy(character)
        applied, updated, error, _unsupported = _apply_character_ops_deterministic(
            character,
            [{"op": "inventory_remove", "item_name": "crossbow bolt",
              "quantity": 1, "container": "ammunition"}],
        )
        self.assertFalse(applied)
        self.assertIn("cannot remove ammunition not present", error)
        self.assertEqual(updated, before)

    def test_unknown_profiles_and_invalid_branch_combinations_fail_closed(self):
        invalid = [
            ("missing", 1, "", ""),
            ("combat-smoke", 2, "", ""),
            ("surrender-exit", 1, "", ""),
            ("initiative-pc", 4, "explicit-exit", ""),
            ("resume-replay", 4, "", ""),
            ("death-save", 1, "", "complete"),
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                fixtures.build_capture_profile(*values)

    def test_branch_inputs_and_resume_restart_phase_are_distinct(self):
        for party in (1, 4):
            surrender, surrender_session, _socket, _calls = self._run_fake(
                "surrender-exit", party, branch="surrender"
            )
            exit_steps, exit_session, exit_socket, _calls = self._run_fake(
                "surrender-exit", party, branch="explicit-exit"
            )
            surrender_profile = fixtures.build_capture_profile("surrender-exit", party, branch="surrender")
            surrender_text = surrender[0]["input"].lower()
            last_hostile_name = surrender_profile["seed"]["last_hostile"]
            self.assertIn("party accepts", surrender_text)
            self.assertIn("restrains " + last_hostile_name.lower(), surrender_text)
            self.assertEqual(surrender_session.steps_sent, 1)
            self.assertEqual(surrender_session.control_requests_sent, 3)
            self.assertEqual([row["input"] for row in exit_steps], [
                "/end_combat", "Describe the quiet gravel yard now that combat has ended."
            ])
            self.assertEqual(exit_session.steps_sent, 2)
            self.assertEqual(exit_session.control_requests_sent, 4)
            self.assertEqual(exit_session.exit_health_read_attempts, 1)
            self.assertEqual(exit_session._last_completion_criterion["criterion"], "backend_narration")
            self.assertTrue(exit_session._last_completion_criterion["canonical_encounter_cleared"])
            output_types = [entry["payload"].get("type") for entry in exit_session.game_outputs]
            self.assertIn("user-input", output_types)
            self.assertIn("narration", output_types)
            surrender_seed = (
                fixtures._one_pc_encounter_payload() if party == 1 else fixtures._encounter_payload()
            )
            party_names = [fixtures.ONE_PC_NAME] if party == 1 else list(fixtures.PC_NAMES)
            pc_initiatives = ({fixtures.ONE_PC_NAME: fixtures.ONE_PC_INITIATIVE}
                              if party == 1 else fixtures.PC_INITIATIVES)
            surrender_seed["creatures"] = [
                {"name": name, "type": "player", "initiative": pc_initiatives[name],
                 "status": "alive", "conditions": [], "actions": {"actionType": "", "target": ""},
                 "currentHitPoints": 20, "maxHitPoints": 20}
                for name in party_names
            ] + surrender_seed["creatures"]
            fixtures.apply_capture_profile(surrender_seed, {}, surrender_profile)
            last_hostile = next(row for row in surrender_seed["creatures"] if row["name"] == last_hostile_name)
            self.assertEqual((last_hostile["type"], last_hostile["status"], last_hostile["currentHitPoints"]),
                             ("enemy", "alive", 20))
            self.assertTrue(all(
                next(row for row in surrender_seed["creatures"] if row["name"] == inactive_name)["status"] == "defeated"
                for inactive_name in surrender_profile["seed"]["inactive_enemies"]
            ))
        complete, _session, _socket, _calls = self._run_fake("resume-replay", 4, phase="complete")
        replay, _session, replay_socket, _calls = self._run_fake("resume-replay", 4, phase="replay")
        self.assertEqual([row["input"] for row in complete], ["/att Goblin Alpha 20 training blade", "/dmg 1"])
        self.assertEqual(replay, [])
        self.assertEqual([event for event, _data in replay_socket.emitted], ["start_game"])
        # Driver reports a phase only; lifecycle/restart remains externally owned.
        self.assertFalse(any(event == "stop_server" for event, _payload in replay_socket.emitted))

    def test_driver_help_exposes_implemented_bounded_options(self):
        help_text = capture_drive.build_parser().format_help()
        for value in CAPTURE_SCENARIOS_FOR_TEST:
            self.assertIn(value, help_text)
        self.assertIn("--branch", help_text)
        self.assertIn("--phase", help_text)
        self.assertIn("latency script", help_text)

    def test_resume_replay_seed_phase_is_rejected_before_prepare(self):
        with patch.object(seed_combat_capture, "prepare") as prepare_mock:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                seed_combat_capture.main([
                    "--prepare", "--party", "4", "--scenario", "resume-replay", "--phase", "replay",
                ])
        prepare_mock.assert_not_called()

    def test_cli_rejects_invalid_profile_before_transport_construction(self):
        invalid_args = [
            ["--party", "4", "--scenario", "surrender-exit"],
            ["--party", "1", "--scenario", "initiative-pc", "--branch", "surrender"],
            ["--party", "4", "--scenario", "combat-smoke", "--phase", "complete"],
        ]
        for argv in invalid_args:
            with self.subTest(argv=argv):
                with patch.object(capture_drive, "CaptureSession", side_effect=_forbidden) as session_ctor, \
                     patch.object(capture_drive.socketio, "Client", side_effect=_forbidden) as socket_ctor, \
                     patch.object(capture_drive.requests_module, "post", side_effect=_forbidden) as http_post, \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(capture_drive.main(argv), capture_drive.EXIT_CONNECT_FAILURE)
                session_ctor.assert_not_called()
                socket_ctor.assert_not_called()
                http_post.assert_not_called()

    def test_resume_capture_requires_explicit_identity_chain_before_transport(self):
        with patch.object(capture_drive, "CaptureSession", side_effect=_forbidden) as session_ctor, \
             patch.object(capture_drive.socketio, "Client", side_effect=_forbidden) as socket_ctor, \
             contextlib.redirect_stdout(io.StringIO()):
            result = capture_drive.main([
                "--party", "1", "--scenario", "resume-replay", "--phase", "complete",
                "--run-dir", "tmp/router-rollout/g3/resume-chain-required",
            ])
        self.assertEqual(result, capture_drive.EXIT_CONNECT_FAILURE)
        session_ctor.assert_not_called()
        socket_ctor.assert_not_called()

    def test_run_rejects_non_capture_endpoints_before_session_or_transport(self):
        bad_urls = [
            "http://localhost:8357", "http://localhost:8361", "http://example.org:8360",
            "https://localhost:8360", "http://user:pass@localhost:8360",
            "http://localhost:8360/campaign", "http://localhost:8360/?x=1",
            "http://localhost:8360/#frag", "http://localhost:8360?",
            "http://localhost:8360#", "http://localhost:8360:bad",
            "http://192.0.2.1:8360", "http://127.0.0.2:8360", "http://localhost",
        ]
        for url in bad_urls:
            for scenario_args in ([], ["--scenario", "initiative-pc"]):
                with self.subTest(url=url, scenario_args=scenario_args):
                    with patch.object(capture_drive, "CaptureSession", side_effect=_forbidden) as session_ctor, \
                         patch.object(capture_drive.socketio, "Client", side_effect=_forbidden) as socket_ctor, \
                         patch.object(capture_drive.requests_module, "post", side_effect=_forbidden) as http_post, \
                         contextlib.redirect_stdout(io.StringIO()):
                        result = capture_drive.main(["--url", url, "--party", "1"] + scenario_args)
                    self.assertEqual(result, capture_drive.EXIT_CONNECT_FAILURE)
                    session_ctor.assert_not_called()
                    socket_ctor.assert_not_called()
                    http_post.assert_not_called()

    def test_run_accepts_only_local_8360_forms_through_fake_transport(self):
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        for url in ("http://localhost:8360", "http://127.0.0.1:8360/", "http://[::1]:8360"):
            with self.subTest(url=url):
                scratch = tempfile.TemporaryDirectory(prefix="capture-url-", dir=str(capture_evidence.RUN_ROOT))
                self.addCleanup(scratch.cleanup)
                scratch_root = pathlib.Path(scratch.name)
                state_root = scratch_root / "state"
                state_root.mkdir()
                (state_root / "model_config.py").write_text("ENABLE_COMBAT_TURN_TRACE = True\n", encoding="utf-8")
                (state_root / "party_tracker.json").write_text(json.dumps({
                    "partyMembers": ["Acheron"], "active_character": "Acheron",
                    "worldConditions": {"activeCombatEncounter": "capture_one_pc"},
                }), encoding="utf-8")
                trace_source = state_root / "combat_turn_trace.jsonl"
                trace_source.write_text(json.dumps({"event_type": "stage", "stage": "synthetic-test",
                                                   "elapsed_ms": 1}) + "\n", encoding="ascii")
                owned_log = scratch_root / "owned-server.log"
                owned_log.write_text("synthetic owned server output\n", encoding="utf-8")
                socket_clients = []
                post_calls = []

                def make_fake_socket(**_kwargs):
                    fake = FakeSocket()
                    socket_clients.append(fake)
                    return fake

                def fake_post(endpoint, **kwargs):
                    post_calls.append((endpoint, kwargs))
                    return FakeResponse()

                args = _args("initiative-pc", 1, scratch_root / "run")
                args.run_dir = str(scratch_root / "evidence")
                args.state_root = str(state_root)
                args.server_log = str(owned_log)
                args.transcript = None
                args.trace_src = str(trace_source)
                args.url = url
                fake_get = lambda endpoint, **kwargs: FakeResponse()
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(capture_drive.run(
                        args, socket_factory=make_fake_socket,
                        http_post=fake_post, http_get=fake_get,
                    ), capture_drive.EXIT_OK)
                self.assertEqual(len(socket_clients), 1)
                self.assertEqual(socket_clients[0].connected_url, url.rstrip("/"))
                self.assertFalse(socket_clients[0].connected)  # driver finally closes only client transport
                self.assertTrue(post_calls)
                self.assertTrue(all(call[0].startswith(url.rstrip("/") + "/api/party/set_active")
                                    for call in post_calls))
                self.assertTrue((scratch_root / "evidence" / "manifest.json").is_file())
                manifest = json.loads((scratch_root / "evidence" / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["evidence_kind"], "synthetic")
                self.assertFalse(manifest["live_eligible"])
                self.assertEqual(manifest["transport"]["client_source"], "constructor_injected")
                self.assertEqual(manifest["counts"]["health_read_attempts"], 1)
                self.assertEqual(manifest["counts"]["control_requests_sent"], 4)
                self.assertTrue((scratch_root / "evidence" / "server.log").is_file())
                self.assertTrue((scratch_root / "evidence" / "trace.jsonl").is_file())
                self.assertTrue((scratch_root / "evidence" / "report.json").is_file())
                self.assertTrue((scratch_root / "evidence" / "snapshots" / "step-001-before.json").is_file())
                self.assertTrue((scratch_root / "evidence" / "snapshots" / "step-002-after.json").is_file())
                self.assertEqual((scratch_root / "evidence" / "server.log").read_text(encoding="utf-8"),
                                 "synthetic owned server output\n")
                checks = json.loads((scratch_root / "evidence" / "checks.json").read_text(encoding="utf-8"))
                self.assertEqual(checks["primary_verdict"], "PENDING")
                self.assertTrue(checks["checks"])
                self.assertTrue(any(row["status"] == "BLOCKED" for row in checks["checks"]))
                start_snapshot = json.loads((scratch_root / "evidence" / "snapshots" / "before-run.json").read_text(encoding="utf-8"))
                self.assertEqual(start_snapshot["records"]["selected_encounter"]["path"],
                                 "modules/encounters/encounter_capture_one_pc.json")
                self.assertNotIn("modules/encounters/encounter_capture_mp.json", start_snapshot["records"])
                # State is still present and unchanged after the driver has preserved
                # its bundle; a primary may now perform the documented teardown.
                self.assertEqual(json.loads((state_root / "party_tracker.json").read_text(encoding="utf-8"))["partyMembers"],
                                 ["Acheron"])

    def test_explicit_exit_final_snapshot_retains_initial_encounter_identity(self):
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(
            prefix="capture-exit-final-snapshot-", dir=str(capture_evidence.RUN_ROOT)
        )
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        state_root = root / "state"
        state_root.mkdir()
        (state_root / "model_config.py").write_text("ENABLE_COMBAT_TURN_TRACE = True\n", encoding="utf-8")
        tracker_path = state_root / "party_tracker.json"
        tracker_path.write_text(json.dumps({
            "partyMembers": [fixtures.ONE_PC_NAME], "active_character": fixtures.ONE_PC_NAME,
            "worldConditions": {"activeCombatEncounter": "capture_one_pc"},
        }), encoding="utf-8")
        encounter_path = state_root / "modules" / "encounters" / "encounter_capture_one_pc.json"
        encounter_path.parent.mkdir(parents=True)
        encounter_path.write_text(json.dumps({
            "encounterId": "capture_one_pc", "id": "capture_one_pc", "creatures": [],
        }), encoding="utf-8")
        encounter_bytes = encounter_path.read_bytes()
        trace_source = state_root / "combat_turn_trace.jsonl"
        trace_source.write_text("", encoding="ascii")
        server_log = root / "owned-server.log"
        server_log.write_text("synthetic server log\n", encoding="utf-8")
        bundle = root / "evidence"
        socket_client = DelayedExplicitExitSocket(tracker_path)
        args = _args("surrender-exit", 1, root, branch="explicit-exit")
        args.run_dir = str(bundle)
        args.state_root = str(state_root)
        args.server_log = str(server_log)
        args.trace_src = str(trace_source)
        args.trace_dst = None
        args.transcript = None
        final_snapshot_calls = []
        original_snapshot_state = capture_evidence.snapshot_state

        def record_snapshot_call(state, label, encounter_id=None, observation=None):
            snapshot = original_snapshot_state(
                state, label, encounter_id=encounter_id, observation=observation
            )
            if label == "after-run":
                final_snapshot_calls.append((encounter_id, snapshot))
            return snapshot

        output = io.StringIO()
        with patch.object(capture_evidence, "snapshot_state", side_effect=record_snapshot_call), \
             contextlib.redirect_stdout(output):
            result = capture_drive.run(
                args,
                socket_factory=lambda: socket_client,
                http_post=lambda _url, **_kwargs: FakeResponse(),
                http_get=lambda _url, **_kwargs: FakeHealthResponse([fixtures.ONE_PC_NAME]),
            )

        self.assertEqual(result, capture_drive.EXIT_OK, output.getvalue())
        self.assertEqual(len(final_snapshot_calls), 1)
        self.assertEqual(final_snapshot_calls[0][0], "capture_one_pc")
        final_snapshot = final_snapshot_calls[0][1]
        selected = final_snapshot["records"]["selected_encounter"]
        self.assertEqual(selected["status"], "ok")
        self.assertEqual(selected["encounterId"], "capture_one_pc")
        self.assertEqual(selected["path"], "modules/encounters/encounter_capture_one_pc.json")
        self.assertEqual(json.loads(tracker_path.read_text(encoding="utf-8"))["worldConditions"][
            "activeCombatEncounter"], "")
        step_after = json.loads((bundle / "snapshots" / "step-002-after.json").read_text(encoding="utf-8"))
        self.assertEqual(step_after["records"]["selected_encounter"]["encounterId"], "capture_one_pc")
        self.assertEqual(step_after["records"]["selected_encounter"]["status"], "ok")
        for step in (1, 2):
            for edge in ("before", "after"):
                self.assertTrue((bundle / "snapshots" / ("step-%03d-%s.json" % (step, edge))).is_file())
        self.assertEqual(encounter_path.read_bytes(), encounter_bytes)

    def test_combat_observation_trace_gate_is_default_off_and_preserves_observations(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-observation-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        trace_path = pathlib.Path(scratch.name) / "trace.jsonl"
        with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
            combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
        ), patch.dict(sys.modules, {"model_config": model_config}):
            self.assertFalse(combat_latency_trace.trace_combat_observation(
                "initiative_gate", accepted=False, before={"awaiting": True}, after={"awaiting": True}
            ))
        self.assertFalse(trace_path.exists())
        with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
            combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
        ), patch.dict(sys.modules, {"model_config": model_config}):
            self.assertTrue(combat_latency_trace.trace_combat_observation(
                "initiative_gate", accepted=False, before={"awaiting": True}, after={"awaiting": True}
            ))
        records, malformed, _lines, error = combat_latency_report.load_trace(trace_path)
        self.assertIsNone(error)
        self.assertEqual(malformed, 0)
        self.assertEqual(records[0]["observation"], "initiative_gate")
        self.assertFalse(records[0]["accepted"])

    def test_per_run_trace_span_copies_only_new_suffix_and_detects_reset(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-trace-span-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        source = root / "debug" / "combat_turn_trace.jsonl"
        source.parent.mkdir()
        old_line = json.dumps({"event_type": "stage", "stage": "old", "elapsed_ms": 1}) + "\n"
        new_line = json.dumps({"event_type": "stage", "stage": "new", "elapsed_ms": 2}) + "\n"
        source.write_text(old_line, encoding="ascii")
        start = capture_evidence.capture_trace_start(source, root)
        with source.open("a", encoding="ascii") as handle:
            handle.write(new_line)
        destination = root / "bundle" / "trace.jsonl"
        result = capture_evidence.preserve_trace_span(source, destination, root, start)
        self.assertEqual(result["status"], "copied")
        self.assertEqual(destination.read_text(encoding="ascii"), new_line)
        self.assertEqual((result["offset_before_bytes"], result["span_bytes"]),
                         (len(old_line.encode("ascii")), len(new_line.encode("ascii"))))

        reset_start = capture_evidence.capture_trace_start(source, root)
        source.write_text(new_line, encoding="ascii")
        reset_result = capture_evidence.preserve_trace_span(
            source, root / "bundle" / "trace-reset.jsonl", root, reset_start
        )
        self.assertEqual(reset_result["status"], "source_reset_or_truncated")
        self.assertTrue(reset_result["source_reset_detected"])

    def test_replay_driver_waits_for_quiet_health_and_preserves_fresh_empty_trace_span(self):
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="capture-replay-driver-", dir=str(capture_evidence.RUN_ROOT)) as temp:
            root = pathlib.Path(temp)
            state_root = root / "retained-sandbox"
            self._write_resume_bundle(root, state_root, "complete")
            (state_root / "model_config.py").write_text("ENABLE_COMBAT_TURN_TRACE = True\n", encoding="utf-8")
            trace_source = state_root / "debug" / "combat_turn_trace.jsonl"
            trace_source.parent.mkdir(parents=True, exist_ok=True)
            trace_source.write_bytes(b"")
            owned_log = root / "owned-server.log"
            owned_log.write_text("owned sandbox server started\n", encoding="utf-8")
            run_dir = root / "replay-driver"
            args = _args("resume-replay", 1, root / "unused", phase="replay")
            args.run_dir = str(run_dir)
            args.state_root = str(state_root)
            args.trace_src = str(trace_source)
            args.transcript = None
            args.server_log = str(owned_log)
            args.chain_id = "resume-chain"
            args.start_timeout = 1.0

            class HealthResponse:
                status_code = 200

                @staticmethod
                def json():
                    return {"partyMembers": ["Acheron"], "active_character": "Acheron"}

            with contextlib.redirect_stdout(io.StringIO()):
                result = capture_drive.run(
                    args, socket_factory=lambda: FakeSocket(),
                    http_get=lambda _url, **_kwargs: HealthResponse(),
                )
            self.assertEqual(result, capture_drive.EXIT_OK)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["steps_sent"], 0)
            self.assertEqual(manifest["counts"]["health_read_attempts"], 2)
            self.assertEqual(manifest["artifacts"]["startup_readiness"]["status"], "ready")
            self.assertEqual(manifest["trace_span"]["status"], "copied")
            self.assertEqual(manifest["trace_span"]["span_bytes"], 0)
            self.assertEqual(manifest["artifacts"]["trace_applicability"]["status"], "non_applicable")
            self.assertEqual((run_dir / "trace.jsonl").read_bytes(), b"")
            reevaluated = capture_evidence._load_run_evidence(run_dir)
            self.assertTrue(reevaluated["integrity"]["valid"], reevaluated["integrity"])
            required_trace = next(row for row in reevaluated["checks"] if row["id"] == "required_trace")
            self.assertEqual(required_trace["status"], "PASS")
            self.assertNotEqual(reevaluated["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")

            prior_record = json.dumps({"event_type": "stage", "stage": "old-run-prefix", "elapsed_ms": 1}) + "\n"
            new_record = json.dumps({"event_type": "combat_observation", "observation": "fresh-replay-span"}) + "\n"
            trace_source.write_text(prior_record, encoding="ascii")

            class TraceAppendingSocket(FakeSocket):
                def emit(self, event, data=None):
                    super().emit(event, data)
                    if event == "start_game":
                        with trace_source.open("a", encoding="ascii") as handle:
                            handle.write(new_record)

            args.run_dir = str(root / "replay-with-fresh-trace")
            args.trace_dst = None
            args.transcript = None
            with contextlib.redirect_stdout(io.StringIO()):
                fresh_result = capture_drive.run(
                    args, socket_factory=lambda: TraceAppendingSocket(),
                    http_get=lambda _url, **_kwargs: HealthResponse(),
                )
            self.assertEqual(fresh_result, capture_drive.EXIT_OK)
            fresh_manifest = json.loads((root / "replay-with-fresh-trace" / "manifest.json").read_text(encoding="utf-8"))
            fresh_span = fresh_manifest["trace_span"]
            self.assertEqual(fresh_span["offset_before_bytes"], len(prior_record.encode("ascii")))
            self.assertEqual(fresh_span["span_bytes"], len(new_record.encode("ascii")))
            copied_trace = (root / "replay-with-fresh-trace" / "trace.jsonl").read_text(encoding="ascii")
            self.assertEqual(copied_trace, new_record)
            self.assertNotIn("old-run-prefix", copied_trace)

    def test_existing_phase_gate_hooks_emit_real_gated_observations_without_state_io(self):
        from core.combat.turn import (
            PhaseGateIO,
            RoundTransitionDependencies,
            capture_pre_round_transition_combat_context,
            run_input_phase_gate,
            stage_combat_turn_snapshot,
        )

        scratch = tempfile.TemporaryDirectory(prefix="capture-phase-hook-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        trace_path = pathlib.Path(scratch.name) / "combat_turn_trace.jsonl"
        emitted = []
        writes = []
        io_contract = PhaseGateIO(
            emit=emitted.append, flush=lambda: None, debug=lambda *_args, **_kwargs: None,
            save_json=lambda *args: writes.append(args),
            parse_death_save_roll=lambda *_args: (False, None, "invalid"),
        )
        manager = SimpleNamespace(
            combat_phase="ENEMY_PHASE", get_remaining_enemies_for_round=lambda: ["Goblin"]
        )
        encounter = {"awaitingPcGroupRoll": True, "initiativeWinner": None,
                     "openingEnemyBatchPending": False, "roundStartsWith": None}
        invalid_gate = lambda *_args: {"handled": False, "error_message": "invalid initiative"}
        args = {"partyMembers": ["Acheron"], "active_character": "Acheron", "worldConditions": {}}
        phase_trace_globals = run_input_phase_gate.__globals__["trace_combat_observation"].__globals__
        with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), \
             patch.dict(phase_trace_globals, {"DEFAULT_TRACE_PATH": trace_path}), \
             patch.dict(sys.modules, {"model_config": model_config}):
            result = run_input_phase_gate("/init 21", encounter_data=encounter,
                multi_pc_manager=manager, party_tracker_data=args, json_file_path="encounter.json",
                conversation_history=[], conversation_history_file="history.json", io=io_contract,
                initiative_gate=invalid_gate)
        self.assertEqual(result.control_action, "continue")
        self.assertFalse(trace_path.exists())
        self.assertEqual(writes, [])

        encounter = {"awaitingPcGroupRoll": False}
        manager = SimpleNamespace(
            combat_phase="PC_PHASE", current_pc_name="Merisiel",
            pc_states={"Acheron": SimpleNamespace(death_save_successes=0, death_save_failures=0)},
            get_next_pending_death_save_pc=lambda: "Acheron",
            validate_death_save_input_actor=lambda *_args, **_kwargs: (False, None, "wrong actor"),
        )
        with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
             patch.dict(phase_trace_globals, {"DEFAULT_TRACE_PATH": trace_path}), \
             patch.dict(sys.modules, {"model_config": model_config}):
            run_input_phase_gate("[Merisiel]: 10", encounter_data=encounter,
                multi_pc_manager=manager, party_tracker_data={"partyMembers": ["Acheron", "Merisiel"],
                    "active_character": "Merisiel", "worldConditions": {}},
                json_file_path="encounter.json", conversation_history=[],
                conversation_history_file="history.json", io=io_contract, initiative_gate=invalid_gate)
        records, malformed, _lines, error = combat_latency_report.load_trace(trace_path)
        self.assertIsNone(error)
        self.assertEqual(malformed, 0)
        actor_events = [row for row in records if row.get("observation") == "death_save_actor_gate"]
        self.assertEqual(len(actor_events), 1)
        self.assertEqual((actor_events[0]["actor"], actor_events[0]["pending_pc"], actor_events[0]["accepted"]),
                         ("Merisiel", "Acheron", False))
        self.assertEqual(writes, [])

        fixture = fixtures.build_mp_fixture()
        self.addCleanup(fixture["tempdir"].cleanup)
        manager = fixture["manager"]
        manager.pc_phase_complete = True
        self.assertEqual(manager.combat_phase, "ENEMY_PHASE")
        with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
             patch.dict(sys.modules, {"model_config": model_config}):
            traced_context = capture_pre_round_transition_combat_context(
                fixture["encounter"], manager, {"combat_round": 2}, True, 22
            )
            transition = stage_combat_turn_snapshot(
                fixture["encounter"],
                [],
                phase_before="ENEMY_PHASE",
                phase_after="ENEMY_PHASE",
                enemy_batch_completed=True,
                opening_batch_pending_before=False,
                dependencies=RoundTransitionDependencies(
                    apply_opening_batch_marker=lambda encounter, starts: False,
                    sync_available=False, save_json=lambda *_args: True,
                    compress_old_rounds=lambda history, *_args, **_kwargs: history,
                    log_debug=lambda *_args, **_kwargs: None,
                    log_info=lambda *_args, **_kwargs: None,
                    log_warning=lambda *_args, **_kwargs: None,
                    bind_history=lambda *_args: None,
                ),
            )
            rejected_context = capture_pre_round_transition_combat_context(
                fixture["encounter"], manager, {"combat_round": 3}, False, 23
            )
        self.assertEqual(traced_context["phase"], "ENEMY_PHASE")
        self.assertEqual(traced_context["eligible_non_pc_cohort"], ["Goblin Alpha", "Goblin Beta"])
        self.assertTrue(transition.phase_transitioned)
        self.assertEqual(transition.encounter_data["combat_phase"], "PC_PHASE")
        self.assertEqual(manager.combat_phase, "ENEMY_PHASE")
        self.assertEqual(traced_context["eligible_non_pc_cohort"], ["Goblin Alpha", "Goblin Beta"])
        self.assertEqual(rejected_context["eligible_non_pc_cohort"], [])

    def test_read_only_snapshot_and_evidence_gate_fail_closed(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-evidence-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        party = {"partyMembers": ["Acheron"], "active_character": "Acheron",
                 "worldConditions": {"activeCombatEncounter": "capture_one_pc"}}
        (root / "party_tracker.json").write_text(json.dumps(party), encoding="utf-8")
        before_bytes = (root / "party_tracker.json").read_bytes()
        before = capture_evidence.snapshot_state(root, "before")
        self.assertEqual((root / "party_tracker.json").read_bytes(), before_bytes)
        after = capture_evidence.snapshot_state(root, "after")
        profile = fixtures.build_capture_profile("initiative-pc", 1)
        checks = capture_evidence.observed_checks(profile, before, after, {})
        manifest = {"evidence_kind": "synthetic", "live_eligible": False,
                    "scenario": {"id": "initiative-pc"}, "party": {"size": 1},
                    "source": {}, "prompt_identity_sha256": {},
                    "counts": {"step_attempts": 0, "steps_sent": 0,
                               "control_request_attempts": 0, "control_request_calls": 0,
                               "control_request_failures": 0,
                               "control_requests_sent": 0, "blocked_step_attempts": 0,
                               "blocked_control_attempts": 0, "timeouts": 1,
                               "step_caps_reached": 0, "idle_settle_caps_reached": 0,
                               "active_switch_failures": 0, "health_read_attempts": 0},
                    "bounds": {"max_steps": 2, "max_requests": 4,
                               "turn_timeout_seconds": 10, "start_timeout_seconds": 10}}
        artifacts = {"matrix_keys": ["initiative-pc:p1"], "required_evidence_status": "degraded"}
        result = capture_evidence.evaluate_evidence(
            manifest, checks, artifacts, run_dir=root,
            integrity={"failures": ["transcript:missing"]}, profile=profile,
        )
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertFalse(result["live_eligible"])
        self.assertIn("synthetic_evidence", result["problems"])
        self.assertIn("required_timeout", result["problems"])
        self.assertIn("invalid_missing_or_stale_artifacts", result["problems"])
        manifest["counts"]["timeouts"] = 0
        manifest["counts"]["blocked_step_attempts"] = 1
        capped = capture_evidence.evaluate_evidence(
            manifest, checks, artifacts, run_dir=root,
            integrity={"failures": ["transcript:missing"]}, profile=profile,
        )
        self.assertIn("required_cap", capped["problems"])
        self.assertTrue(any(row["status"] == "BLOCKED" for row in checks))

    def test_matrix_inventory_and_resume_identity_mismatch_are_blocking(self):
        keys = capture_evidence.required_matrix_keys()
        self.assertEqual(len(keys), 18)
        self.assertEqual(len(set(keys)), 18)
        partial = capture_evidence.evaluate_matrix([])
        self.assertEqual(partial["automated_status"], "BLOCKED")
        self.assertEqual(len(partial["missing_required_keys"]), 18)
        fake_row = capture_evidence.evaluate_matrix([{
            "run_dir": str(capture_evidence.RUN_ROOT / "nonexistent-status-spoof"),
            "matrix_key": "resume-replay:complete:p1",
            "automated_status": "READY_FOR_PRIMARY_REVIEW", "live_eligible": True,
        }])
        self.assertEqual(fake_row["observed_keys"], [])
        self.assertEqual(len(fake_row["missing_required_keys"]), 18)
        self.assertTrue(fake_row["invalid_run_bundles"])
        history_identity = [{"index": 0, "role": "user", "sha256": "history-message-sha"}]
        history_file = {"path": "history.json", "bytes": 10, "semantic_message_count": 1,
                        "semantic_message_identities": history_identity,
                        "identity_status": "ok", "status": "ok"}
        complete = {"scenario": {"phase": "complete"}, "sandbox_id": "same", "source": "head-a",
                    "party": ["Acheron"], "seed": "seed-a", "transport": "socket", "chain_id": "resume-one",
                    "snapshot_chain": {"after_projection": {"hp": 19}, "after_history_inventory": {
                        "modules/conversation_history": [history_file]}}}
        replay = dict(complete, source="head-b", seed="seed-b",
                      scenario={"phase": "replay"}, snapshot_chain={"before_projection": {"hp": 19},
                      "after_projection": {"hp": 19}, "before_history_inventory": {
                          "modules/conversation_history": [history_file]},
                      "after_history_inventory": {"modules/conversation_history": [history_file]}})
        chain = capture_evidence.compare_resume_chain(complete, replay)
        self.assertEqual(chain["status"], "FAIL")
        self.assertEqual(chain["mismatched_identity_fields"], ["source", "seed"])
        party_mismatch = dict(replay, source="head-a", seed="seed-a", party=["Other"])
        self.assertIn("party", capture_evidence.compare_resume_chain(complete, party_mismatch)["mismatched_identity_fields"])
        sandbox_mismatch = dict(complete, sandbox_id="other")
        self.assertIn("sandbox_id", capture_evidence.compare_resume_chain(complete, sandbox_mismatch)["mismatched_identity_fields"])

    def test_resume_bundle_replay_projection_positive_and_mutation_negatives(self):
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resume-bundle-", dir=str(capture_evidence.RUN_ROOT)) as scratch:
            root = pathlib.Path(scratch)
            state = root / "retained-sandbox"
            complete_dir = self._write_resume_bundle(root, state, "complete")
            replay_dir = self._write_resume_bundle(root, state, "replay", start_hp=19, end_hp=19)
            complete_run = capture_evidence._load_run_evidence(complete_dir)
            self.assertEqual(complete_run["evaluation"]["missing_required_checks"], [])
            manifest = json.loads((complete_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                len(manifest["prompt_identity_sha256"]),
                len(sorted((ROOT / "prompts" / "combat").glob("*.txt"))),
            )
            self.assertEqual(manifest["configuration"]["actual_runtime"]["response_model"], "unknown")
            complete_after_snapshot = json.loads((complete_dir / "snapshots" / "after-run.json").read_text(encoding="utf-8"))
            self.assertEqual(complete_after_snapshot["records"]["characters/acheron.json"][
                "resource_state"]["spellSlots"]["level1"]["current"], 1)
            self.assertEqual(complete_run["evaluation"]["checks"][
                next(i for i, row in enumerate(complete_run["evaluation"]["checks"])
                     if row["id"] == "completed_turn_applied_once")
            ]["status"], "PASS")
            linked = capture_evidence.evaluate_matrix([complete_dir, replay_dir])
            self.assertEqual(linked["resume_chain_failures"], [])
            self.assertEqual(len(linked["missing_required_keys"]), 16)
            self.assertIn("resume-replay:complete:p1", linked["observed_keys"])
            self.assertIn("resume-replay:replay:p1", linked["observed_keys"])
            self.assertIn("resume-replay:complete:p1", linked["synthetic_keys"])
            self.assertNotEqual(linked["automated_status"], "READY_FOR_PRIMARY_REVIEW")

        with tempfile.TemporaryDirectory(prefix="resume-history-append-", dir=str(capture_evidence.RUN_ROOT)) as scratch:
            root = pathlib.Path(scratch)
            state = root / "retained-sandbox"
            complete_dir = self._write_resume_bundle(root, state, "complete")
            replay_dir = self._write_resume_bundle(root, state, "replay", start_hp=19, end_hp=19,
                                                   history_append=True)
            appended = capture_evidence.evaluate_matrix([complete_dir, replay_dir])
            self.assertEqual(appended["resume_chain_failures"], [])
            self.assertEqual(appended["invalid_run_bundles"], [])

        variants = [
            ("reseed-hp20", {"start_hp": 20, "end_hp": 20, "end_xp": 0}, None),
            ("extra-hp18", {"start_hp": 19, "end_hp": 18, "end_xp": 0}, None),
            ("xp-delta", {"start_hp": 19, "end_hp": 19, "end_xp": 10}, None),
            ("source-mismatch", {"start_hp": 19, "end_hp": 19, "end_xp": 0}, "source"),
            ("party-mismatch", {"start_hp": 19, "end_hp": 19, "end_xp": 0}, "party"),
            ("chain-mismatch", {"start_hp": 19, "end_hp": 19, "end_xp": 0}, "chain"),
            ("same-length-history-replacement", {"start_hp": 19, "end_hp": 19, "end_xp": 0,
                                                   "history_message": "completed bait turn"}, None),
            ("missing-history", {"start_hp": 19, "end_hp": 19, "end_xp": 0,
                                  "history_missing": True}, None),
            ("spell-slot-delta", {"start_hp": 19, "end_hp": 19, "end_xp": 0,
                                   "end_slots": 0}, None),
        ]
        for suffix, replay_options, mismatch_kind in variants:
            with self.subTest(variant=suffix), tempfile.TemporaryDirectory(
                prefix="resume-negative-", dir=str(capture_evidence.RUN_ROOT)
            ) as scratch:
                root = pathlib.Path(scratch)
                state = root / "retained-sandbox"
                complete_dir = self._write_resume_bundle(
                    root, state, "complete", history_missing=bool(replay_options.get("history_missing"))
                )
                replay_dir = self._write_resume_bundle(root, state, "replay", **replay_options)
                manifest_path = replay_dir / "manifest.json"
                replay_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if mismatch_kind == "source":
                    replay_manifest["source"]["head"] = "different-source-head"
                elif mismatch_kind == "party":
                    replay_manifest["party"]["roster"] = ["Different PC"]
                elif mismatch_kind == "chain":
                    replay_manifest["chain_id"] = "different-chain"
                if mismatch_kind:
                    manifest_path.write_text(json.dumps(replay_manifest), encoding="utf-8")
                evaluated = capture_evidence.evaluate_matrix([complete_dir, replay_dir])
                self.assertEqual(len(evaluated["resume_chain_failures"]), 1)
                self.assertNotEqual(evaluated["automated_status"], "READY_FOR_PRIMARY_REVIEW")

    def test_bundle_recalculation_rejects_forged_checks_and_stale_files(self):
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resume-integrity-", dir=str(capture_evidence.RUN_ROOT)) as scratch:
            root = pathlib.Path(scratch)
            bundle = self._write_resume_bundle(root, root / "sandbox", "complete")
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            baseline = capture_evidence._load_run_evidence(bundle)
            self.assertNotEqual(baseline.get("error"), "invalid_profile")
            self.assertNotIn("manifest:seed_profile_content_mismatch",
                             baseline["integrity"]["failures"])
            self.assertNotIn("manifest:party_identity_mismatch",
                             baseline["integrity"]["failures"])

            forged_seed = copy.deepcopy(manifest)
            forged_seed["seed"]["profile_seed"]["unexpected"] = "forged"
            manifest_path.write_text(json.dumps(forged_seed), encoding="utf-8")
            rejected_seed = capture_evidence._load_run_evidence(bundle)
            self.assertIn("manifest:seed_profile_content_mismatch",
                          rejected_seed["integrity"]["failures"])

            forged_party = copy.deepcopy(manifest)
            forged_party["party"]["roster"] = ["Different PC"]
            manifest_path.write_text(json.dumps(forged_party), encoding="utf-8")
            rejected_party = capture_evidence._load_run_evidence(bundle)
            self.assertIn("manifest:party_identity_mismatch",
                          rejected_party["integrity"]["failures"])

            checks_path = bundle / "checks.json"
            document = json.loads(checks_path.read_text(encoding="utf-8"))
            document["checks"][0]["observed"] = "forged observed value"
            document["checks"][0]["status"] = "PASS"
            checks_path.write_text(json.dumps(document), encoding="utf-8")
            derived = capture_evidence._load_run_evidence(bundle)
            self.assertIn("checks:derived_result_mismatch", derived["integrity"]["failures"])
            self.assertNotEqual(derived["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")

            transcript_path = bundle / "transcript.log"
            transcript_path.write_text(transcript_path.read_text(encoding="utf-8") + "stale modification\n",
                                       encoding="utf-8")
            stale = capture_evidence._load_run_evidence(bundle)
            self.assertTrue(any("transcript:hash_mismatch" in reason
                                for reason in stale["integrity"]["failures"]))

    def test_snapshot_refuses_symlinked_allowlisted_state(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-symlink-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        target = root / "real-party.json"
        target.write_text(json.dumps({"partyMembers": ["Acheron"]}), encoding="utf-8")
        (root / "party_tracker.json").symlink_to(target)
        snapshot = capture_evidence.snapshot_state(root, "symlink-test")
        self.assertEqual(snapshot["records"]["party_tracker.json"]["status"], "unsafe_path")
        self.assertIn("party_tracker.json", snapshot["errors"])

    def test_snapshot_marks_nonfinite_hp_as_invalid_not_zero(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-numeric-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        (root / "party_tracker.json").write_text(json.dumps({
            "partyMembers": ["Acheron"], "active_character": "Acheron",
            "worldConditions": {"activeCombatEncounter": "odd_encounter"},
        }), encoding="utf-8")
        (root / "modules" / "encounters").mkdir(parents=True)
        (root / "modules" / "encounters" / "encounter_odd_encounter.json").write_text(json.dumps({
            "encounterId": "odd_encounter", "creatures": [{"name": "Goblin", "type": "enemy",
                "status": "alive", "currentHitPoints": float("nan"), "maxHitPoints": 20}],
        }), encoding="utf-8")
        snapshot = capture_evidence.snapshot_state(root, "bad-number")
        self.assertTrue(any("currentHitPoints" in item
                            for item in capture_evidence._snapshot_numeric_errors(snapshot)))

    def test_step_snapshots_and_runtime_events_assert_initiative_death_and_ally_batches(self):
        def seed(root, party_names, creatures, npc_names=()):
            root.mkdir(parents=True, exist_ok=True)
            (root / "characters").mkdir(exist_ok=True)
            (root / "modules" / "encounters").mkdir(parents=True, exist_ok=True)
            for name in party_names:
                char = {"name": name, "type": "player", "hitPoints": 20, "maxHitPoints": 20,
                        "status": "alive", "deathSaves": {"successes": 0, "failures": 0},
                        "experience_points": 0, "spellSlots": {}, "classFeatures": {}, "currency": {}}
                (root / "characters" / (name.lower() + ".json")).write_text(json.dumps(char), encoding="utf-8")
            for name in npc_names:
                npc = {"name": name, "type": "npc", "character_type": "npc", "hitPoints": 12,
                       "maxHitPoints": 12, "status": "alive", "deathSaves": {"successes": 0, "failures": 0},
                       "experience_points": 0, "spellSlots": {}, "classFeatures": {}, "currency": {}}
                (root / "characters" / (name.lower() + ".json")).write_text(json.dumps(npc), encoding="utf-8")
            tracker = {"partyMembers": list(party_names), "active_character": party_names[0],
                       "partyNPCs": [{"name": name, "role": "Ally"} for name in npc_names],
                       "worldConditions": {"activeCombatEncounter": "capture_one_pc"}}
            (root / "party_tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
            encounter = {"id": "capture_one_pc", "encounterId": "capture_one_pc", "combat_round": 1,
                         "initiativeMode": "two_group_phase1", "initiativeRolls": {"dmGroup": 8, "pcGroup": None},
                         "initiativeWinner": None, "roundStartsWith": None, "awaitingPcGroupRoll": False,
                         "openingEnemyBatchPending": False, "creatures": creatures}
            path = root / "modules" / "encounters" / "encounter_capture_one_pc.json"
            path.write_text(json.dumps(encounter), encoding="utf-8")
            return path, encounter

        def check_by_id(checks, check_id):
            return next(row for row in checks if row["id"] == check_id)

        with tempfile.TemporaryDirectory(prefix="capture-init-observed-", dir="tmp") as temp:
            root = pathlib.Path(temp) / "state"
            creatures = [
                {"name": "Acheron", "type": "player", "status": "alive", "currentHitPoints": 20,
                 "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
                {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": 20,
                 "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
            ]
            encounter_path, encounter = seed(root, ["Acheron"], creatures)
            encounter["awaitingPcGroupRoll"] = True
            encounter["initiativeRolls"] = {"dmGroup": 8, "pcGroup": None}
            encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
            before_run = capture_evidence.snapshot_state(root, "before", "capture_one_pc")
            bundle = pathlib.Path(temp) / "bundle"
            bundle.mkdir()
            step_pairs = []
            capture_evidence.write_step_snapshot(bundle, root, 1, "before", "capture_one_pc",
                {"label": "invalid initiative", "input": "/init 21", "character": "Acheron"})
            before = capture_evidence.snapshot_state(root, "invalid-before", "capture_one_pc",
                {"label": "invalid initiative", "input": "/init 21", "character": "Acheron"})
            capture_evidence.write_step_snapshot(bundle, root, 1, "after", "capture_one_pc",
                {"label": "invalid initiative", "input": "/init 21", "character": "Acheron"})
            after_invalid = capture_evidence.snapshot_state(root, "invalid-after", "capture_one_pc",
                {"label": "invalid initiative", "input": "/init 21", "character": "Acheron"})
            step_pairs.append({"before": before, "after": after_invalid})
            encounter.update({"initiativeWinner": "pcGroup", "roundStartsWith": "pcGroup",
                              "awaitingPcGroupRoll": False, "openingEnemyBatchPending": False})
            encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
            capture_evidence.write_step_snapshot(bundle, root, 2, "before", "capture_one_pc",
                {"label": "resolve initiative", "input": "/init 18", "character": "Acheron"})
            before_valid = capture_evidence.snapshot_state(root, "valid-before", "capture_one_pc",
                {"label": "resolve initiative", "input": "/init 18", "character": "Acheron"})
            capture_evidence.write_step_snapshot(bundle, root, 2, "after", "capture_one_pc",
                {"label": "resolve initiative", "input": "/init 18", "character": "Acheron"})
            after_valid = capture_evidence.snapshot_state(root, "valid-after", "capture_one_pc",
                {"label": "resolve initiative", "input": "/init 18", "character": "Acheron"})
            step_pairs.append({"before": before_valid, "after": after_valid})
            final = capture_evidence.snapshot_state(root, "after-run", "capture_one_pc")
            profile = fixtures.build_capture_profile("initiative-pc", 1)
            events = [{"observation": "initiative_gate", "input": "/init 21", "accepted": False},
                      {"observation": "initiative_gate", "input": "/init 18", "accepted": True,
                       "expected_winner": "pcGroup", "marker_enabled": False}]
            checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, step_pairs, events)
            self.assertEqual(check_by_id(checks, "invalid_initiative_holds_pending_gate")["status"], "PASS")
            self.assertEqual(check_by_id(checks, "pc_win_without_opening_batch")["status"], "PASS")

        with tempfile.TemporaryDirectory(prefix="capture-dm-tie-observed-", dir="tmp") as temp:
            root = pathlib.Path(temp) / "state"
            creatures = [
                {"name": "Acheron", "type": "player", "status": "alive", "currentHitPoints": 20,
                 "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
                {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": 20,
                 "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
            ]
            path, encounter = seed(root, ["Acheron"], creatures)
            encounter.update({"awaitingPcGroupRoll": True, "initiativeRolls": {"dmGroup": 12, "pcGroup": None}})
            path.write_text(json.dumps(encounter), encoding="utf-8")
            before_run = capture_evidence.snapshot_state(root, "before", "capture_one_pc")
            bundle = pathlib.Path(temp) / "bundle"
            bundle.mkdir()
            steps = []
            for index, label, text in ((1, "invalid initiative", "/init 21"),
                                       (2, "resolve initiative tie", "/init 12")):
                details = {"label": label, "input": text, "character": "Acheron"}
                capture_evidence.write_step_snapshot(bundle, root, index, "before", "capture_one_pc", details)
                before = capture_evidence.snapshot_state(root, label + "-before", "capture_one_pc", details)
                if text == "/init 12":
                    encounter.update({"initiativeWinner": "dmGroup", "roundStartsWith": "dmGroup",
                                      "awaitingPcGroupRoll": False, "openingEnemyBatchPending": False})
                    path.write_text(json.dumps(encounter), encoding="utf-8")
                capture_evidence.write_step_snapshot(bundle, root, index, "after", "capture_one_pc", details)
                after = capture_evidence.snapshot_state(root, label + "-after", "capture_one_pc", details)
                steps.append({"before": before, "after": after})
            final = capture_evidence.snapshot_state(root, "after-run", "capture_one_pc")
            profile = fixtures.build_capture_profile("initiative-dm-tie", 1)
            events = [
                {"observation": "initiative_gate", "input": "/init 21", "accepted": False},
                {"observation": "initiative_gate", "input": "/init 12", "accepted": True,
                 "expected_winner": "dmGroup", "marker_enabled": True,
                 "eligible_non_pc_cohort": ["Goblin"]},
                {"observation": "combat_validation_result", "logical_turn": 1,
                 "validation_accepted": True},
                {"observation": "combat_action_batch", "logical_turn": 1,
                 "validation_accepted": True, "enemy_phase_batch": True,
                 "opening_batch_pending_before_round_transition": True,
                 "eligible_non_pc_cohort": ["Goblin"], "explicit_actor_records": [],
                 "affected_entities": [{"entity": "Acheron", "source": "parameters.characterName"}],
                 "action_count": 0},
                {"observation": "opening_enemy_batch_completed", "opening_marker_before": True,
                 "opening_marker_after": False},
                {"observation": "combat_logical_batch_completed", "logical_turn": 1,
                 "validation_accepted": True, "accepted_batch": True,
                 "phase_after_processing": "PC_PHASE", "opening_pending_after": False},
            ]
            checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, steps, events)
            self.assertEqual(check_by_id(checks, "initiative_expected_winner")["status"], "PASS")
            self.assertEqual(check_by_id(checks, "dm_tie_eligible_batch_once_and_marker_cleared")["status"], "PASS")
            self.assertEqual(check_by_id(checks, "dm_tie_returns_to_pc_phase")["status"], "PASS")
            no_batch_checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, steps, events[:2])
            self.assertEqual(check_by_id(no_batch_checks, "dm_tie_eligible_batch_once_and_marker_cleared")["status"], "BLOCKED")

        with tempfile.TemporaryDirectory(prefix="capture-death-observed-", dir="tmp") as temp:
            root = pathlib.Path(temp) / "state"
            party_names = ["Acheron", "Merisiel", "Kira", "Vitreol"]
            creatures = [{"name": name, "type": "player", "status": "unconscious" if name == "Acheron" else "alive",
                          "currentHitPoints": 0 if name == "Acheron" else 20, "maxHitPoints": 20,
                          "conditions": ["unconscious"] if name == "Acheron" else [],
                          "deathSaves": {"successes": 0, "failures": 0}}
                         for name in party_names]
            path, encounter = seed(root, party_names, creatures)
            char_path = root / "characters" / "acheron.json"
            char = json.loads(char_path.read_text(encoding="utf-8"))
            char.update({"hitPoints": 0, "status": "unconscious", "deathSaves": {"successes": 0, "failures": 0}})
            char_path.write_text(json.dumps(char), encoding="utf-8")
            before_run = capture_evidence.snapshot_state(root, "before", "capture_one_pc")
            bundle = pathlib.Path(temp) / "bundle"
            bundle.mkdir()
            step_pairs = []
            for index, label, text, actor in ((1, "wrong actor", "10", "Merisiel"),
                                               (2, "invalid death save", "21", "Acheron"),
                                               (3, "legal death save", "10", "Acheron")):
                detail = {"label": label, "input": text, "character": actor}
                if label == "wrong actor":
                    tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
                    tracker["active_character"] = "Merisiel"
                    (root / "party_tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
                capture_evidence.write_step_snapshot(bundle, root, index, "before", "capture_one_pc", detail)
                before = capture_evidence.snapshot_state(root, label + "-before", "capture_one_pc", detail)
                if label == "wrong actor":
                    tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
                    tracker["active_character"] = "Acheron"
                    (root / "party_tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
                if label == "legal death save":
                    char = json.loads(char_path.read_text(encoding="utf-8"))
                    char["deathSaves"] = {"successes": 1, "failures": 0}
                    char_path.write_text(json.dumps(char), encoding="utf-8")
                    encounter["creatures"][0]["deathSaves"] = {"successes": 1, "failures": 0}
                    path.write_text(json.dumps(encounter), encoding="utf-8")
                capture_evidence.write_step_snapshot(bundle, root, index, "after", "capture_one_pc", detail)
                after = capture_evidence.snapshot_state(root, label + "-after", "capture_one_pc", detail)
                step_pairs.append({"before": before, "after": after})
            final = capture_evidence.snapshot_state(root, "after-run", "capture_one_pc")
            profile = fixtures.build_capture_profile("death-save", 4)
            events = [
                {"observation": "death_save_actor_gate", "actor": "Merisiel", "pending_pc": "Acheron", "accepted": False},
                {"observation": "death_save_roll", "input": "21", "valid": False, "pending_pc": "Acheron"},
                {"observation": "death_save_roll", "input": "10", "valid": True, "pending_pc": "Acheron", "resolved_pc": "Acheron"},
            ]
            checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, step_pairs, events)
            for check_id in ("pending_pc_death_state_seeded", "invalid_death_roll_no_state_change",
                             "wrong_actor_rejected_without_state_change", "legal_roll_updates_only_pending_pc_once"):
                self.assertEqual(check_by_id(checks, check_id)["status"], "PASS", check_by_id(checks, check_id))
            bad_events = [dict(events[0], accepted=True), *events[1:]]
            bad_checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, step_pairs, bad_events)
            self.assertEqual(check_by_id(bad_checks, "wrong_actor_rejected_without_state_change")["status"], "FAIL")
            merisiel_path = root / "characters" / "merisiel.json"
            merisiel = json.loads(merisiel_path.read_text(encoding="utf-8"))
            merisiel["deathSaves"] = {"successes": 1, "failures": 0}
            merisiel_path.write_text(json.dumps(merisiel), encoding="utf-8")
            encounter["combat_round"] = 2
            path.write_text(json.dumps(encounter), encoding="utf-8")
            wrong_actor_effect = capture_evidence.snapshot_state(root, "wrong-actor-effect", "capture_one_pc")
            mutated_steps = copy.deepcopy(step_pairs)
            mutated_steps[0]["after"] = wrong_actor_effect
            effect_checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, mutated_steps, events)
            self.assertEqual(check_by_id(effect_checks, "wrong_actor_rejected_without_state_change")["status"], "FAIL")

        with tempfile.TemporaryDirectory(prefix="capture-ally-observed-", dir="tmp") as temp:
            root = pathlib.Path(temp) / "state"
            ally = {"name": "Blairen", "type": "npc", "npcType": "ally", "status": "alive",
                    "currentHitPoints": 12, "maxHitPoints": 12, "conditions": [],
                    "deathSaves": {"successes": 0, "failures": 0}}
            goblin = {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": 20,
                      "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}}
            inactive = {"name": "Inactive Goblin", "type": "enemy", "status": "defeated",
                        "currentHitPoints": 0, "maxHitPoints": 20, "conditions": [],
                        "deathSaves": {"successes": 0, "failures": 0}}
            player = {"name": "Acheron", "type": "player", "status": "alive", "currentHitPoints": 20,
                      "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}}
            path, encounter = seed(root, ["Acheron"], [player, goblin, ally, inactive], ["Blairen"])
            before_run = capture_evidence.snapshot_state(root, "before", "capture_one_pc")
            bundle = pathlib.Path(temp) / "bundle"
            bundle.mkdir()
            steps = []
            for index, label, text, target in ((1, "attack", "/att Goblin 20 training blade", None),
                                                (2, "damage", "/dmg 2", "Goblin"),
                                                (3, "enemy batch", "/end", None)):
                details = {"label": label, "input": text, "character": "Acheron"}
                capture_evidence.write_step_snapshot(bundle, root, index, "before", "capture_one_pc", details)
                before = capture_evidence.snapshot_state(root, label + "-before", "capture_one_pc", details)
                if target:
                    encounter["creatures"][1]["currentHitPoints"] -= 2
                    path.write_text(json.dumps(encounter), encoding="utf-8")
                capture_evidence.write_step_snapshot(bundle, root, index, "after", "capture_one_pc", details)
                after = capture_evidence.snapshot_state(root, label + "-after", "capture_one_pc", details)
                steps.append({"before": before, "after": after})
            final = capture_evidence.snapshot_state(root, "after-run", "capture_one_pc")
            profile = fixtures.build_capture_profile("combat-smoke-allied-inactive", 1)
            events = [{"observation": "combat_action_batch", "enemy_phase_batch": True,
                       "validation_accepted": True,
                       "eligible_non_pc_cohort": ["Goblin", "Blairen"],
                       "explicit_actor_records": [{"name": "Goblin", "source": "actor"}],
                       "affected_entities": [{"entity": "Blairen", "source": "parameters.characterName"}],
                       "action_count": 2, "phase": "ENEMY_PHASE", "combat_round": 1}]
            checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, steps, events)
            self.assertEqual(check_by_id(checks, "ally_and_inactive_actual_batch_filter")["status"], "PASS")
            self.assertFalse(any(row.get("name") == "Blairen" for row in
                                 check_by_id(checks, "ally_and_inactive_actual_batch_filter")["observed"]["explicit_actor_records"]))
            incomplete_events = [dict(events[0], explicit_actor_records=[
                {"name": "Goblin", "source": "actor"}, {"name": "Acheron", "source": "actorName"}])]
            incomplete_checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, steps, incomplete_events)
            self.assertEqual(check_by_id(incomplete_checks, "ally_and_inactive_actual_batch_filter")["status"], "FAIL")
            inactive_cohort = [dict(events[0], eligible_non_pc_cohort=["Goblin", "Blairen", "Inactive Goblin"])]
            inactive_checks = capture_evidence.observed_checks(profile, before_run, final,
                {"required_evidence_status": "ok", "trace": "trace.jsonl"}, steps, inactive_cohort)
            self.assertEqual(check_by_id(inactive_checks, "ally_and_inactive_actual_batch_filter")["status"], "FAIL")

        for branch in ("surrender", "explicit-exit"):
            with self.subTest(exit_branch=branch), tempfile.TemporaryDirectory(
                prefix="capture-exit-observed-", dir="tmp"
            ) as temp:
                root = pathlib.Path(temp) / "state"
                creatures = [
                    {"name": "Acheron", "type": "player", "status": "alive", "currentHitPoints": 20,
                     "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
                    {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": 20,
                     "maxHitPoints": 20, "conditions": [], "deathSaves": {"successes": 0, "failures": 0}},
                ]
                path, encounter = seed(root, ["Acheron"], creatures)
                before_run = capture_evidence.snapshot_state(root, "before", "capture_one_pc")
                bundle = pathlib.Path(temp) / "bundle"
                bundle.mkdir()
                input_text = ("Goblin offers to surrender; the party accepts and restrains Goblin."
                              if branch == "surrender" else "/end_combat")
                details = ({"label": "accept last hostile surrender", "input": input_text,
                            "character": "Acheron", "game_output_count": 1,
                            "backend_output_count": 1, "game_output_types": ["narration"],
                            "backend_output_types": ["narration"], "timed_out": False,
                            "completion_criterion": {"criterion": "backend_output",
                                                     "canonical_encounter_cleared": False}}
                           if branch == "surrender" else
                           {"label": "explicit exit branch", "input": input_text, "character": "Acheron",
                            "game_output_count": 1, "backend_output_count": 0,
                            "game_output_types": ["user-input"], "backend_output_types": [],
                            "timed_out": True,
                            "completion_criterion": {"criterion": "canonical_exit_clear",
                                                     "canonical_encounter_cleared": True,
                                                     "backend_ready": True}})
                capture_evidence.write_step_snapshot(bundle, root, 1, "before", "capture_one_pc", details)
                step_before = capture_evidence.snapshot_state(root, "exit-before", "capture_one_pc", details)
                tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
                tracker["worldConditions"]["activeCombatEncounter"] = ""
                (root / "party_tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
                events = [{"observation": "xp_award", "source": "explicit_exit" if branch == "explicit-exit" else "auto_exit",
                           "amount": 0, "participants": ["Acheron"]}]
                if branch == "explicit-exit":
                    char_path = root / "characters" / "acheron.json"
                    char = json.loads(char_path.read_text(encoding="utf-8"))
                    char["experience_points"] = 10
                    char_path.write_text(json.dumps(char), encoding="utf-8")
                    events[0]["amount"] = 10
                capture_evidence.write_step_snapshot(bundle, root, 1, "after", "capture_one_pc", details)
                step_after = capture_evidence.snapshot_state(root, "exit-after", "capture_one_pc", details)
                after_run = capture_evidence.snapshot_state(root, "after", "capture_one_pc")
                profile = fixtures.build_capture_profile("surrender-exit", 1, branch=branch)
                checks = capture_evidence.observed_checks(profile, before_run, after_run, {
                    "required_evidence_status": "ok", "trace": "trace.jsonl",
                    "health_probe": {"status": "ok", "http_status": 200},
                }, [{"before": step_before, "after": step_after}], events)
                for check_id in ("requested_exit_branch_observed", "encounter_cleared",
                                 "server_alive_readonly_probe", "no_duplicate_hp_or_xp_awards"):
                    self.assertEqual(check_by_id(checks, check_id)["status"], "PASS",
                                     (branch, check_by_id(checks, check_id)))
                self.assertEqual(check_by_id(checks, "narration_handoff_observed")["status"],
                                 "PASS" if branch == "surrender" else "FAIL")
                if branch == "explicit-exit":
                    followup = "Describe the quiet gravel yard now that combat has ended."
                    followup_details = {"label": "post-exit narrator handoff", "input": followup,
                                        "character": "Acheron", "game_output_count": 2,
                                        "backend_output_count": 1,
                                        "game_output_types": ["user-input", "narration"],
                                        "backend_output_types": ["narration"], "timed_out": False,
                                        "completion_criterion": {"criterion": "backend_narration",
                                            "canonical_encounter_cleared": True}}
                    capture_evidence.write_step_snapshot(bundle, root, 2, "before", "capture_one_pc",
                                                         followup_details)
                    followup_before = capture_evidence.snapshot_state(root, "handoff-before", "capture_one_pc",
                                                                      followup_details)
                    capture_evidence.write_step_snapshot(bundle, root, 2, "after", "capture_one_pc",
                                                         followup_details)
                    followup_after = capture_evidence.snapshot_state(root, "handoff-after", "capture_one_pc",
                                                                     followup_details)
                    checks = capture_evidence.observed_checks(profile, before_run, after_run, {
                        "required_evidence_status": "ok", "trace": "trace.jsonl",
                        "health_probe": {"status": "ok", "http_status": 200},
                    }, [{"before": step_before, "after": step_after},
                        {"before": followup_before, "after": followup_after}], events)
                    self.assertEqual(check_by_id(checks, "narration_handoff_observed")["status"], "PASS")

    def test_path_and_stale_run_directory_rejected_before_transport(self):
        scratch = tempfile.TemporaryDirectory(prefix="capture-path-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        with self.assertRaises(ValueError):
            capture_evidence.validate_evidence_paths(root / "outside", root)
        state = root / "state"
        state.mkdir()
        capture_evidence.RUN_ROOT.mkdir(parents=True, exist_ok=True)
        run = capture_evidence.RUN_ROOT / ("test-stale-" + pathlib.Path(scratch.name).name)
        run.mkdir()
        self.addCleanup(lambda: run.rmdir())
        with self.assertRaisesRegex(ValueError, "unique"):
            capture_evidence.validate_evidence_paths(run, state)


CAPTURE_SCENARIOS_FOR_TEST = fixtures.CAPTURE_SCENARIOS


if __name__ == "__main__":
    unittest.main()
