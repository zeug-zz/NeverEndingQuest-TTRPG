# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the sandbox mapping-pilot adapter and launcher."""

from __future__ import annotations

import copy
import ast
import builtins
import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Guard network/provider and outside-scratch writes before importing pilot code.
from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot import adapter, launcher
from scripts.mapping_pilot.fixtures import FIXTURE_FILES


TMP_ROOT = ROOT / "tmp"
FIXTURE_ROOT = ROOT / "plans" / "v2-mapping-pilot-prereg" / "fixtures"
_RUNTIME_LOCATION_IDS = {
    "MPV2_LOC_TAVERN": "MP01",
    "MPV2_LOC_VILLAGE_GREEN": "MP02",
    "MPV2_LOC_TOWER_APPROACH": "MP03",
}
_AREA_BY_RUNTIME_ID = {"MP01": "MPA001", "MP02": "MPA001", "MP03": "MPA002"}
_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    "combat_stage_tavern_zones",
)


def _verified_input_lines(source_path: pathlib.Path) -> tuple[list[int], list[int]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    main_loop = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main_game_loop"
    )
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    player_lines: list[int] = []
    nested_lines: list[int] = []
    for node in ast.walk(main_loop):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
        ):
            continue
        parent = parents.get(node)
        targets = []
        if isinstance(parent, ast.Assign):
            targets = parent.targets
        names = {
            child.id
            for target in targets
            for child in ast.walk(target)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
        }
        if names == {"user_input_text"}:
            player_lines.append(node.lineno)
        elif names == {"level_up_input"}:
            nested_lines.append(node.lineno)
    return sorted(player_lines), sorted(nested_lines)


def _mock_main_module(
    runtime_root: pathlib.Path,
    *,
    on_startup,
    on_player_input,
) -> types.ModuleType:
    """Load safe callsite probes at the copied main.py AST input lines."""
    source_path = runtime_root / "main.py"
    source_path.write_bytes((ROOT / "main.py").read_bytes())
    player_lines, nested_lines = _verified_input_lines(source_path)
    if len(player_lines) != 2 or len(nested_lines) != 2:
        raise AssertionError("main.py input callsites changed; update the seam probe")

    real_tree = ast.parse(source_path.read_text(encoding="utf-8"))
    main_loop_line = next(
        node.lineno
        for node in real_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main_game_loop"
    )
    final_line = max(max(nested_lines) + 2, main_loop_line + 4)
    source_lines = ["\n"] * final_line
    source_lines[main_loop_line - 1] = "def main_game_loop():\n"
    source_lines[main_loop_line] = "    on_startup()\n"
    source_lines[main_loop_line + 1] = "    iteration = 0\n"
    source_lines[main_loop_line + 2] = "    while iteration < 4:\n"
    source_lines[nested_lines[0] - 1] = "        level_up_input = input('Level-up A: ')\n"
    source_lines[player_lines[0] - 2] = "        if iteration % 2 == 0:\n"
    source_lines[player_lines[0] - 1] = "            user_input_text = input('User A: ')\n"
    source_lines[player_lines[1] - 2] = "        else:\n"
    source_lines[player_lines[1] - 1] = "            user_input_text = input('User B: ')\n"
    source_lines[player_lines[1]] = (
        "        if user_input_text and user_input_text.strip():\n"
    )
    source_lines[player_lines[1] + 1] = "            on_player_input(user_input_text)\n"
    source_lines[nested_lines[1] - 1] = "        level_up_input = input('Level-up B: ')\n"
    source_lines[nested_lines[1]] = "        iteration += 1\n"
    source_lines[nested_lines[1] + 1] = "    return iteration\n"

    source_bytes = "".join(source_lines).encode("utf-8")
    source_path.write_bytes(source_bytes)
    spec = importlib.util.spec_from_file_location(
        "mapping_pilot_test_main", source_path
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load mapping pilot main seam probe")
    module = importlib.util.module_from_spec(spec)
    module.on_startup = on_startup
    module.on_player_input = on_player_input
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeCombatPromptResult:
    user_prompt: str
    dynamic_state: str
    marker: str = "preserved"


class MappingPilotAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        if not TMP_ROOT.is_dir() or TMP_ROOT.is_symlink():
            self.fail("project-local tmp/ must exist and must not be a symlink")
        self._temporary = tempfile.TemporaryDirectory(
            prefix="mapping-pilot-adapter-", dir=str(TMP_ROOT)
        )
        self.addCleanup(self._temporary.cleanup)
        self.work = pathlib.Path(self._temporary.name)
        self._workspace_index = 0

    def _workspace(
        self,
        *,
        arm: str = "B",
        fixture_id: str = "interior_tavern",
        party_size: int = 1,
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, Any], dict[str, Any]]:
        self._workspace_index += 1
        owner = self.work / ("owner-%d" % self._workspace_index)
        root = owner / "tmp" / "combat_capture"
        (root / "mapping_pilot" / "expected").mkdir(parents=True)
        (root / "modules" / "Mapping_Pilot_Arena" / "areas").mkdir(parents=True)
        (root / "characters").mkdir(parents=True)
        (root / "scripts" / "mapping_pilot").mkdir(parents=True)
        (root / "core" / "combat").mkdir(parents=True)
        (root / "web").mkdir(parents=True)
        for relative in (
            "main.py",
            "web/web_interface.py",
            "core/combat/prompts.py",
            "core/combat/combat_manager.py",
            "scripts/mapping_pilot/adapter.py",
        ):
            (root / relative).write_text("# sandbox test fixture\n", encoding="utf-8")
        (root / "config.py").write_text("WEB_PORT = 8360\n", encoding="utf-8")

        source_fixtures = {
            fixture_name: json.loads(
                (ROOT / "plans" / "v2-mapping-pilot-prereg" / relative_path).read_text(
                    encoding="utf-8"
                )
            )
            for fixture_name, relative_path in FIXTURE_FILES.items()
        }
        for fixture_name, fixture in source_fixtures.items():
            (root / "mapping_pilot" / "expected" / (fixture_name + ".json")).write_text(
                json.dumps(
                    {"fixture_id": fixture_name, "source_truth": fixture},
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

        selected_fixture = source_fixtures[fixture_id]
        source_location_id = selected_fixture["location_ids"][0]
        runtime_location_id = _RUNTIME_LOCATION_IDS[source_location_id]
        area_id = _AREA_BY_RUNTIME_ID[runtime_location_id]
        location_rows = selected_fixture.get("locations", [])
        start_name = (
            location_rows[0].get("name", "The Lantern and Reed Tavern")
            if location_rows
            else "The Lantern and Reed Tavern"
        )
        members = ["Acheron"] if party_size == 1 else ["Acheron", "Merisiel", "Valerius", "Nym"]
        for member in members:
            self._write_json(root / "characters" / (member + ".json"), {"name": member})
        mapping: dict[str, Any] = {
            "module": "Mapping_Pilot_Arena",
            "source_location_id": source_location_id,
            "runtime_location_id": runtime_location_id,
            "area_id": area_id,
            "area_name": "Mapping Pilot Arena",
            "location_name": start_name,
            "id_map_file": "modules/Mapping_Pilot_Arena/location_id_map.json",
        }
        active_encounter = ""
        if fixture_id == "combat_stage_tavern_zones":
            active_encounter = "mapping_pilot_combat"
            mapping["combat_actors"] = {"placement_scope": "shadow_only"}
        metadata = {
            "format_version": 1,
            "effective_seed": 5101,
            "arm": arm,
            "fixture_id": fixture_id,
            "party": {"size": party_size, "members": members},
            "counterbalance": {
                "row_id": "MPV2-TEST-ROW",
                "row_type": "planned",
                "fixed_seed": 5101,
                "script": "scripts/interior.json",
            },
            "mapping": mapping,
        }
        self._write_json(root / "mapping_pilot" / "seed_metadata.json", metadata)
        self._write_json(
            root / "modules" / "Mapping_Pilot_Arena" / "location_id_map.json",
            {
                "mapping_version": 1,
                "source_namespace": "MPV2_",
                "runtime_location_ids": _RUNTIME_LOCATION_IDS,
            },
        )
        tracker = {
            "module": "Mapping_Pilot_Arena",
            "partyMembers": members,
            "active_character": members[0],
            "partyNPCs": [],
            "worldConditions": {
                "currentLocationId": runtime_location_id,
                "currentLocation": start_name,
                "currentAreaId": area_id,
                "currentArea": "Mapping Pilot Arena",
                "activeCombatEncounter": active_encounter,
            },
        }
        self._write_json(root / "party_tracker.json", tracker)

        tavern_features = [
            {"name": "Back door", "description": "Position: north center. State: closed_unbarred."},
            {"name": "Front entrance", "description": "Position: south center. State: open."},
        ]
        area_one = {
            "areaId": "MPA001",
            "locations": [
                {
                    "locationId": "MP01",
                    "name": "The Lantern and Reed Tavern",
                    "connectivity": ["MP02"],
                    "areaConnectivity": [],
                    "areaConnectivityId": [],
                    "features": tavern_features,
                },
                {
                    "locationId": "MP02",
                    "name": "Rillford Village Green",
                    "connectivity": ["MP01"],
                    "areaConnectivity": ["Old Watchtower Approach"],
                    "areaConnectivityId": ["MP03"],
                    "features": [],
                },
            ],
        }
        area_two = {
            "areaId": "MPA002",
            "locations": [
                {
                    "locationId": "MP03",
                    "name": "Old Watchtower Approach",
                    "connectivity": [],
                    "areaConnectivity": ["Mapping Pilot Arena"],
                    "areaConnectivityId": ["MP02"],
                    "features": [],
                }
            ],
        }
        self._write_json(
            root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA001.json",
            area_one,
        )
        self._write_json(
            root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA002.json",
            area_two,
        )
        return owner, root, metadata, source_fixtures

    @staticmethod
    def _write_json(path: pathlib.Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=True, sort_keys=True), encoding="utf-8"
        )

    def _provider(
        self,
        root: pathlib.Path,
        metadata: dict[str, Any],
        fixtures: dict[str, Any],
        *,
        knowledge_resolver=None,
    ) -> adapter.SandboxPacketProvider:
        return adapter.SandboxPacketProvider(
            runtime_root=root,
            metadata=metadata,
            fixture_payloads=fixtures,
            runtime_to_source={value: key for key, value in _RUNTIME_LOCATION_IDS.items()},
            knowledge_resolver=knowledge_resolver,
        )

    def _move_tracker_to_green(self, root: pathlib.Path) -> None:
        tracker_path = root / "party_tracker.json"
        tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        tracker["worldConditions"]["currentLocationId"] = "MP02"
        tracker["worldConditions"]["currentLocation"] = "Rillford Village Green"
        tracker["worldConditions"]["currentAreaId"] = "MPA001"
        tracker["worldConditions"]["currentArea"] = "Mapping Pilot Arena"
        self._write_json(tracker_path, tracker)

    @staticmethod
    def _parent_state_hash(owner: pathlib.Path) -> str:
        from scripts.mapping_pilot import row_runner

        with mock.patch.object(row_runner, "PROJECT_ROOT", owner):
            return row_runner.hash_canonical_sandbox_state("tmp/combat_capture")[
                "sha256"
            ]

    def test_arm_a_is_no_patch_and_byte_identical_for_both_prompt_seams(self):
        dm_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def dm_note(*args, **kwargs):
            dm_calls.append((args, kwargs))
            return "Dungeon Master Note: Adjacent locations: north road. Player: look."

        def combat_prompt(*args, **kwargs):
            return FakeCombatPromptResult("initiative\ncombat prompt", "dynamic")

        main_owner = SimpleNamespace(build_enhanced_dm_note=dm_note)
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=combat_prompt,
            CombatPromptResult=FakeCombatPromptResult,
        )
        dm_identity = main_owner.build_enhanced_dm_note
        combat_identity = prompt_owner.assemble_combat_prompt
        dm_args = ("dm", "look", None, {"partyMembers": ["Acheron"]}, None, False)
        baseline_note = dm_identity(*dm_args).encode("utf-8")
        baseline_prompt = combat_identity(object()).user_prompt.encode("utf-8")

        installation = adapter.install_adapter(
            arm="A",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=lambda *_args: self.fail("arm A requested a packet"),
            movement_hint_observer=lambda _observation: self.fail("arm A observed a hint"),
        )
        try:
            self.assertEqual(installation.installed_attributes, ())
            self.assertIs(main_owner.build_enhanced_dm_note, dm_identity)
            self.assertIs(prompt_owner.assemble_combat_prompt, combat_identity)
            self.assertEqual(main_owner.build_enhanced_dm_note(*dm_args).encode("utf-8"), baseline_note)
            self.assertEqual(
                prompt_owner.assemble_combat_prompt(object()).user_prompt.encode("utf-8"),
                baseline_prompt,
            )
        finally:
            installation.uninstall()
        self.assertEqual(dm_calls[0][0], dm_args)

    def test_unaugmented_calls_delegate_exact_args_results_and_exceptions(self):
        expected_note = "Dungeon Master Note: Adjacent locations: north road. Player: wait."
        seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def original(*args, **kwargs):
            seen.append((args, kwargs))
            return expected_note

        def prompt_original(*args, **kwargs):
            seen.append((args, kwargs))
            return FakeCombatPromptResult("base", "state")

        main_owner = SimpleNamespace(build_enhanced_dm_note=original)
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=prompt_original,
            CombatPromptResult=FakeCombatPromptResult,
        )
        installation = adapter.install_adapter(
            arm="D",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=lambda *_args: None,
        )
        args = ("dm", "wait", None, {"active_character": "Acheron"}, None, False)
        kwargs = {"trace_id": "exact-kwargs"}
        try:
            result = main_owner.build_enhanced_dm_note(*args, **kwargs)
            self.assertIs(result, expected_note)
            self.assertEqual(seen[0], (args, kwargs))
            prompt_args = (object(),)
            prompt_kwargs = {"marker": "preserved"}
            prompt_result = prompt_owner.assemble_combat_prompt(*prompt_args, **prompt_kwargs)
            self.assertEqual(prompt_result, FakeCombatPromptResult("base", "state"))
            self.assertEqual(seen[1], (prompt_args, prompt_kwargs))
        finally:
            installation.uninstall()

        raised = RuntimeError("original failure")

        def raises(*args, **kwargs):
            seen.append((args, kwargs))
            raise raised

        main_owner.build_enhanced_dm_note = raises
        installation = adapter.install_adapter(
            arm="B",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=lambda *_args: None,
        )
        try:
            with self.assertRaises(RuntimeError) as caught:
                main_owner.build_enhanced_dm_note(*args, **kwargs)
            self.assertIs(caught.exception, raised)
            self.assertEqual(seen[-1], (args, kwargs))
        finally:
            installation.uninstall()

    def test_b_and_d_replace_only_the_verified_exits_slot(self):
        note = (
            "Dungeon Master Note: Current location: Tavern. "
            "Adjacent locations in this area: north road.\nActive plot points:\nNone"
        )
        original_calls: list[tuple[Any, ...]] = []

        def original(*args, **kwargs):
            original_calls.append(args)
            return note

        for arm in ("B", "D"):
            owner = SimpleNamespace(build_enhanced_dm_note=original)
            prompts = SimpleNamespace(
                assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult("p", "s"),
                CombatPromptResult=FakeCombatPromptResult,
            )
            installation = adapter.install_adapter(
                arm=arm,
                main_module=owner,
                combat_prompts_module=prompts,
                packet_provider=lambda surface, _args, _kwargs: "Relationships:\nExit at door is open.",
                fixture_id="interior_tavern",
            )
            try:
                output = owner.build_enhanced_dm_note("unchanged", user="input")
                self.assertTrue(output.startswith("Dungeon Master Note: Current location: Tavern.\n"))
                self.assertIn("--- EXITS / COMPACT ORIENTATION (MAPPING PILOT %s) ---" % arm, output)
                self.assertIn("Relationships:\nExit at door is open.", output)
                self.assertNotIn("north road", output)
                self.assertIn("Active plot points:\nNone", output)
            finally:
                installation.uninstall()
        self.assertEqual(original_calls, [("unchanged",), ("unchanged",)])

    def test_exploration_packet_appends_when_the_original_note_has_no_exit_slot(self):
        original_note = "Dungeon Master Note: a short multi-PC note."
        owner = SimpleNamespace(
            build_enhanced_dm_note=lambda *_args, **_kwargs: original_note
        )
        prompts = SimpleNamespace(
            assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult("p", "s"),
            CombatPromptResult=FakeCombatPromptResult,
        )
        packet = "Relationships:\nCurrent place: Rillford Village Green."
        installation = adapter.install_adapter(
            arm="B",
            main_module=owner,
            combat_prompts_module=prompts,
            packet_provider=lambda *_args: packet,
        )
        try:
            result = owner.build_enhanced_dm_note("arg")
            self.assertTrue(result.startswith(original_note + "\n"))
            self.assertTrue(result.endswith("--- EXITS / COMPACT ORIENTATION (MAPPING PILOT B) ---\n" + packet))
        finally:
            installation.uninstall()

    def test_d_combat_preserves_result_fields_and_requests_only_observational_hint(self):
        result = FakeCombatPromptResult("base prompt", "dynamic state", "marker-value")
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def original(*args, **kwargs):
            calls.append((args, kwargs))
            return result

        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=original,
            CombatPromptResult=FakeCombatPromptResult,
        )
        main_owner = SimpleNamespace(build_enhanced_dm_note=lambda *args: "note")
        packet = "Schematic (not to scale):\n- | Goblin | -\nRelationships:\nGoblin is near the bar."
        installation = adapter.install_adapter(
            arm="D",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=lambda surface, _args, _kwargs: packet if surface == "combat" else None,
        )
        input_value = object()
        kwargs = {"retry": 2}
        try:
            augmented = prompt_owner.assemble_combat_prompt(input_value, **kwargs)
            self.assertIs(type(augmented), FakeCombatPromptResult)
            self.assertEqual(augmented.dynamic_state, result.dynamic_state)
            self.assertEqual(augmented.marker, result.marker)
            self.assertEqual(augmented.user_prompt, result.user_prompt + "\n\n--- MAPPING PILOT COMBAT ZONE (D) ---\n" + packet + "\n\n" + adapter._MOVEMENT_HINT_INSTRUCTION)
            self.assertIn("top-level movement_hint", augmented.user_prompt)
            self.assertEqual(calls, [((input_value,), kwargs)])
        finally:
            installation.uninstall()

        with self.assertRaises(adapter.UnsupportedMappingPilotArmError):
            adapter.install_adapter(
                arm="B",
                fixture_id="combat_stage_tavern_zones",
                main_module=main_owner,
                combat_prompts_module=prompt_owner,
            )

        installation = adapter.install_adapter(
            arm="B",
            fixture_id="interior_tavern",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
        )
        try:
            with self.assertRaises(adapter.UnsupportedMappingPilotArmError):
                prompt_owner.assemble_combat_prompt(input_value)
        finally:
            installation.uninstall()

    def test_b_d_packets_freeze_per_surface_per_turn_and_record_exact_uses(self):
        for arm in ("B", "D"):
            with self.subTest(arm=arm):
                _owner, root, _metadata, _fixtures = self._workspace(arm=arm)
                packet_state = {"exploration": "STARTUP", "combat": "STARTUP"}
                provider_calls: list[tuple[str, str]] = []
                outputs: dict[str, str] = {}
                validation_calls: list[tuple[Any, ...]] = []
                observation_calls: list[Any] = []

                def provider(surface, _args, _kwargs):
                    value = packet_state[surface]
                    provider_calls.append((surface, value))
                    return ("packet %s at %s" % (surface, value)).encode("ascii")

                def original_note(*_args, **_kwargs):
                    return "Dungeon Master Note: Adjacent locations: baseline."

                def original_combat(*_args, **_kwargs):
                    return FakeCombatPromptResult("combat baseline", "dynamic")

                def validate(response, *args, **kwargs):
                    validation_calls.append((response, args, kwargs))
                    return response["accepted"]

                main_owner = _mock_main_module(
                    root,
                    on_startup=lambda: None,
                    on_player_input=lambda _value: None,
                )
                main_owner.build_enhanced_dm_note = original_note
                prompt_owner = SimpleNamespace(
                    assemble_combat_prompt=original_combat,
                    CombatPromptResult=FakeCombatPromptResult,
                )
                manager_owner = SimpleNamespace(validate_combat_response=validate)

                def _use_turn(value: str) -> None:
                    if value == "player-one":
                        packet_state["exploration"] = "EXPLORATION_TURN_ONE"
                        outputs["turn-one-normal"] = main_owner.build_enhanced_dm_note(
                            "normal"
                        )
                        packet_state["exploration"] = "EXPLORATION_AFTER_TRANSITION"
                        outputs["turn-one-retry"] = main_owner.build_enhanced_dm_note(
                            "validation retry"
                        )
                        outputs["turn-one-transition"] = main_owner.build_enhanced_dm_note(
                            "same-turn transition"
                        )
                        if arm == "D":
                            packet_state["combat"] = "COMBAT_AFTER_TRANSITION"
                            first_combat = prompt_owner.assemble_combat_prompt(
                                "normal combat"
                            )
                            outputs["combat-turn-one-normal"] = first_combat.user_prompt
                            failed = {"accepted": False, "narration": "retry"}
                            self.assertFalse(
                                manager_owner.validate_combat_response(failed, "encounter")
                            )
                            packet_state["combat"] = "COMBAT_AFTER_VALIDATION_RETRY"
                            retried_combat = prompt_owner.assemble_combat_prompt(
                                "validation retry combat"
                            )
                            outputs["combat-turn-one-retry"] = retried_combat.user_prompt
                            accepted = {"accepted": True, "narration": "ok"}
                            self.assertTrue(
                                manager_owner.validate_combat_response(accepted, "encounter")
                            )
                    elif value == "player-two":
                        packet_state["exploration"] = "EXPLORATION_TURN_TWO"
                        outputs["turn-two-normal"] = main_owner.build_enhanced_dm_note(
                            "next logical turn"
                        )
                        packet_state["exploration"] = "EXPLORATION_TURN_TWO_MUTATED"
                        outputs["turn-two-retry"] = main_owner.build_enhanced_dm_note(
                            "next turn retry"
                        )
                        if arm == "D":
                            packet_state["combat"] = "COMBAT_TURN_TWO"
                            outputs["combat-turn-two"] = (
                                prompt_owner.assemble_combat_prompt("next turn combat")
                                .user_prompt
                            )

                # The callbacks close over the module, so replace the initially
                # installed function attributes after its globals are created.
                main_owner.on_startup = lambda: outputs.setdefault(
                    "startup", main_owner.build_enhanced_dm_note("startup")
                )
                main_owner.on_player_input = _use_turn

                eof = EOFError("input exhausted")
                input_values = iter(
                    [
                        "nested-zero-a",
                        "",
                        "nested-zero-b",
                        "nested-one-a",
                        "player-one",
                        "nested-one-b",
                        "nested-two-a",
                        "player-two",
                        "nested-two-b",
                        "nested-three-a",
                        eof,
                    ]
                )
                prompts_seen: list[str] = []

                def fake_input(prompt=""):
                    prompts_seen.append(prompt)
                    value = next(input_values)
                    if isinstance(value, BaseException):
                        raise value
                    return value

                original_builtin_input = None
                with mock.patch("builtins.input", fake_input) as input_patch:
                    original_builtin_input = builtins.input
                    installation = adapter.install_adapter(
                        arm=arm,
                        main_module=main_owner,
                        combat_prompts_module=prompt_owner,
                        packet_provider=provider,
                        combat_manager_module=manager_owner,
                        movement_hint_observer=(
                            observation_calls.append if arm == "D" else None
                        ),
                        fixture_id="interior_tavern",
                        runtime_root=root,
                    )
                    self.addCleanup(installation.uninstall)
                    self.assertIn("input", installation.installed_attributes)
                    self.assertIs(builtins.input, fake_input)
                    with self.assertRaises(EOFError) as caught:
                        main_owner.main_game_loop()
                    self.assertIs(caught.exception, eof)
                    self.assertEqual(
                        prompts_seen,
                        [
                            "Level-up A: ",
                            "User A: ",
                            "Level-up B: ",
                            "Level-up A: ",
                            "User B: ",
                            "Level-up B: ",
                            "Level-up A: ",
                            "User A: ",
                            "Level-up B: ",
                            "Level-up A: ",
                            "User B: ",
                        ],
                    )

                    self.assertIn("packet exploration at STARTUP", outputs["startup"])
                    for key in (
                        "turn-one-normal",
                        "turn-one-retry",
                        "turn-one-transition",
                    ):
                        self.assertIn(
                            "packet exploration at EXPLORATION_TURN_ONE", outputs[key]
                        )
                        self.assertNotIn("EXPLORATION_AFTER_TRANSITION", outputs[key])
                    self.assertIn(
                        "packet exploration at EXPLORATION_TURN_TWO",
                        outputs["turn-two-normal"],
                    )
                    self.assertIn(
                        "packet exploration at EXPLORATION_TURN_TWO",
                        outputs["turn-two-retry"],
                    )
                    self.assertNotIn(
                        "EXPLORATION_TURN_ONE", outputs["turn-two-normal"]
                    )
                    if arm == "D":
                        for key in (
                            "combat-turn-one-normal",
                            "combat-turn-one-retry",
                        ):
                            self.assertIn(
                                "packet combat at COMBAT_AFTER_TRANSITION",
                                outputs[key],
                            )
                            self.assertNotIn("COMBAT_AFTER_VALIDATION_RETRY", outputs[key])
                        self.assertIn(
                            "packet combat at COMBAT_TURN_TWO",
                            outputs["combat-turn-two"],
                        )
                        self.assertEqual(len(validation_calls), 2)
                        self.assertEqual(len(observation_calls), 2)

                    # The expected call ordering is startup exploration, turn 1
                    # exploration/combat, then turn 2 exploration/combat.
                    expected_calls = [
                        ("exploration", "STARTUP"),
                        ("exploration", "EXPLORATION_TURN_ONE"),
                    ]
                    if arm == "D":
                        expected_calls.append(("combat", "COMBAT_AFTER_TRANSITION"))
                    expected_calls.append(("exploration", "EXPLORATION_TURN_TWO"))
                    if arm == "D":
                        expected_calls.append(("combat", "COMBAT_TURN_TWO"))
                    self.assertEqual(provider_calls, expected_calls)

                    evidence_dir = (
                        root
                        / "mapping_pilot"
                        / "turn_packet_evidence"
                        / installation.lifecycle_id
                    )
                    records = [
                        json.loads(path.read_text(encoding="utf-8"))
                        for path in sorted(evidence_dir.glob("record-*.json"))
                    ]
                    first_record_bytes = {
                        path.name: path.read_bytes()
                        for path in sorted(evidence_dir.glob("record-*.json"))
                    }
                    sequences = [record["sequence"] for record in records]
                    self.assertEqual(sequences, list(range(1, len(records) + 1)))
                    packet_records = [
                        record for record in records if record["event_type"] == "packet_use"
                    ]
                    self.assertGreater(len(packet_records), 1)
                    for record in packet_records:
                        packet_bytes = record["packet_ascii"].encode("ascii")
                        self.assertEqual(
                            hashlib.sha256(packet_bytes).hexdigest(),
                            record["packet_sha256"],
                        )
                    by_turn_surface: dict[tuple[str, str], list[dict[str, Any]]] = {}
                    for record in packet_records:
                        by_turn_surface.setdefault(
                            (record["turn_id"], record["surface"]), []
                        ).append(record)
                    for uses in by_turn_surface.values():
                        self.assertEqual(
                            [use["use_index"] for use in uses],
                            list(range(1, len(uses) + 1)),
                        )
                        self.assertEqual(
                            len({use["packet_ascii"] for use in uses}), 1
                        )
                        self.assertEqual(len({use["packet_sha256"] for use in uses}), 1)
                    exploration_turns = [
                        record
                        for record in packet_records
                        if record["surface"] == "exploration"
                    ]
                    self.assertEqual(
                        sorted({record["turn_number"] for record in exploration_turns}),
                        [0, 1, 2],
                    )
                    self.assertEqual(
                        [
                            record["use_index"]
                            for record in exploration_turns
                            if record["turn_number"] == 1
                        ],
                        [1, 2, 3],
                    )
                    if arm == "D":
                        turn_one_combat = [
                            record
                            for record in packet_records
                            if record["turn_number"] == 1
                            and record["surface"] == "combat"
                        ]
                        self.assertEqual(len(turn_one_combat), 2)
                        self.assertNotEqual(
                            turn_one_combat[0]["packet_sha256"],
                            next(
                                record["packet_sha256"]
                                for record in packet_records
                                if record["turn_number"] == 1
                                and record["surface"] == "exploration"
                            ),
                        )
                    self.assertNotIn("player-one", repr(records))
                    self.assertNotIn("nested-one", repr(records))
                    self.assertEqual(installation.evidence_status, "recording")
                    first_lifecycle_id = installation.lifecycle_id
                    installation.uninstall()
                    self.assertFalse(hasattr(main_owner, "input"))
                    self.assertIs(builtins.input, original_builtin_input)

                self.assertEqual(main_owner.build_enhanced_dm_note, original_note)
                self.assertEqual(prompt_owner.assemble_combat_prompt, original_combat)
                self.assertIs(manager_owner.validate_combat_response, validate)

                packet_state["exploration"] = "NEW_LIFECYCLE"
                resumed_installation = adapter.install_adapter(
                    arm=arm,
                    main_module=main_owner,
                    combat_prompts_module=prompt_owner,
                    packet_provider=provider,
                    fixture_id="interior_tavern",
                    runtime_root=root,
                )
                self.addCleanup(resumed_installation.uninstall)
                try:
                    resumed_output = main_owner.build_enhanced_dm_note("resumed")
                    self.assertIn("packet exploration at NEW_LIFECYCLE", resumed_output)
                    self.assertNotEqual(
                        resumed_installation.lifecycle_id, first_lifecycle_id
                    )
                    self.assertTrue(
                        (root / "mapping_pilot" / "turn_packet_evidence" / first_lifecycle_id).is_dir()
                    )
                    self.assertTrue(
                        (
                            root
                            / "mapping_pilot"
                            / "turn_packet_evidence"
                            / resumed_installation.lifecycle_id
                        ).is_dir()
                    )
                    self.assertEqual(
                        first_record_bytes,
                        {
                            path.name: path.read_bytes()
                            for path in sorted(evidence_dir.glob("record-*.json"))
                        },
                    )
                finally:
                    resumed_installation.uninstall()

    def test_packet_cache_isolated_between_execution_threads(self):
        _owner, root, _metadata, _fixtures = self._workspace(arm="B")
        packet_state = {"value": "main-thread"}
        provider_calls: list[str] = []
        original_note = lambda *_args, **_kwargs: (
            "Dungeon Master Note: Adjacent locations: baseline."
        )
        main_owner = _mock_main_module(
            root,
            on_startup=lambda: None,
            on_player_input=lambda _value: None,
        )
        main_owner.build_enhanced_dm_note = original_note
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult(
                "combat", "dynamic"
            ),
            CombatPromptResult=FakeCombatPromptResult,
        )

        def provider(_surface, _args, _kwargs):
            value = packet_state["value"]
            provider_calls.append(value)
            return value

        installation = adapter.install_adapter(
            arm="B",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=provider,
            fixture_id="interior_tavern",
            runtime_root=root,
        )
        try:
            main_output = main_owner.build_enhanced_dm_note("main context")
            packet_state["value"] = "worker-thread"
            worker_outputs: list[str] = []
            worker_errors: list[BaseException] = []

            def worker() -> None:
                try:
                    worker_outputs.append(
                        main_owner.build_enhanced_dm_note("worker context")
                    )
                except BaseException as exc:
                    worker_errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worker_errors, [])
            self.assertIn("main-thread", main_output)
            self.assertIn("worker-thread", worker_outputs[0])
            self.assertEqual(provider_calls, ["main-thread", "worker-thread"])

            evidence_dir = (
                root
                / "mapping_pilot"
                / "turn_packet_evidence"
                / installation.lifecycle_id
            )
            records = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(evidence_dir.glob("record-*.json"))
            ]
            uses = [record for record in records if record["event_type"] == "packet_use"]
            self.assertEqual(len(uses), 2)
            self.assertEqual(len({record["context_id"] for record in uses}), 2)
        finally:
            installation.uninstall()

    def test_exploration_snapshot_survives_same_turn_location_transition(self):
        _owner, root, metadata, fixtures = self._workspace(arm="B")
        tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
        provider = self._provider(root, metadata, fixtures)
        outputs: dict[str, str] = {}
        main_ref: dict[str, types.ModuleType] = {}

        def note(label: str) -> str:
            return main_ref["main"].build_enhanced_dm_note(
                "dm",
                label,
                None,
                tracker,
                None,
                False,
            )

        def on_player_input(value: str) -> None:
            if value == "player-one":
                tracker["worldConditions"]["currentLocationId"] = "MP01"
                outputs["turn-one-first"] = note("normal")
                tracker["worldConditions"]["currentLocationId"] = "MP02"
                tracker["worldConditions"]["currentAreaId"] = "MPA001"
                tracker["worldConditions"]["currentLocation"] = "Rillford Village Green"
                outputs["turn-one-retry"] = note("retry")
                outputs["turn-one-transition"] = note("transition")
            elif value == "player-two":
                outputs["turn-two-first"] = note("next turn")

        main_owner = _mock_main_module(
            root,
            on_startup=lambda: outputs.setdefault("startup", note("startup")),
            on_player_input=on_player_input,
        )
        main_ref["main"] = main_owner
        main_owner.build_enhanced_dm_note = (
            lambda *_args, **_kwargs: "Dungeon Master Note: Adjacent locations: baseline."
        )
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult(
                "combat", "dynamic"
            ),
            CombatPromptResult=FakeCombatPromptResult,
        )
        values = iter(
            [
                "nested-zero-a",
                "player-one",
                "nested-zero-b",
                "nested-one-a",
                "player-two",
                "nested-one-b",
                "nested-two-a",
                "",
                "nested-two-b",
                "nested-three-a",
                EOFError("input exhausted"),
            ]
        )

        def fake_input(_prompt=""):
            value = next(values)
            if isinstance(value, BaseException):
                raise value
            return value

        with mock.patch("builtins.input", fake_input):
            installation = adapter.install_adapter(
                arm="B",
                main_module=main_owner,
                combat_prompts_module=prompt_owner,
                packet_provider=provider,
                fixture_id="interior_tavern",
                runtime_root=root,
            )
            try:
                with self.assertRaises(EOFError):
                    main_owner.main_game_loop()
            finally:
                installation.uninstall()

        self.assertIn("Current place: The Lantern and Reed Tavern.", outputs["startup"])
        for key in ("turn-one-first", "turn-one-retry", "turn-one-transition"):
            self.assertIn("Current place: The Lantern and Reed Tavern.", outputs[key])
            self.assertNotIn(
                "Current place: Rillford Village Green.", outputs[key]
            )
        self.assertIn("Current place: Rillford Village Green.", outputs["turn-two-first"])
        evidence_dir = (
            root
            / "mapping_pilot"
            / "turn_packet_evidence"
            / installation.lifecycle_id
        )
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(evidence_dir.glob("record-*.json"))
        ]
        packet_records = [
            record for record in records if record["event_type"] == "packet_use"
        ]
        turn_one = [
            record for record in packet_records if record["turn_number"] == 1
        ]
        turn_two = [
            record for record in packet_records if record["turn_number"] == 2
        ]
        self.assertEqual(len(turn_one), 3)
        self.assertEqual(len({record["packet_sha256"] for record in turn_one}), 1)
        self.assertEqual(len(turn_two), 1)
        self.assertNotEqual(turn_one[0]["packet_sha256"], turn_two[0]["packet_sha256"])

    def test_packet_log_failure_is_degraded_without_changing_validation(self):
        _owner, root, _metadata, _fixtures = self._workspace(arm="D")
        main_owner = _mock_main_module(
            root,
            on_startup=lambda: None,
            on_player_input=lambda _value: None,
        )
        original_note = lambda *_args, **_kwargs: "Dungeon Master Note: Adjacent locations: baseline."
        main_owner.build_enhanced_dm_note = original_note
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult(
                "combat baseline", "dynamic"
            ),
            CombatPromptResult=FakeCombatPromptResult,
        )
        validation_sentinel = object()
        validation_calls: list[tuple[Any, ...]] = []

        def validate(*args, **kwargs):
            validation_calls.append((args, kwargs))
            return validation_sentinel

        manager_owner = SimpleNamespace(validate_combat_response=validate)
        reported: list[tuple[str, str]] = []

        def failing_writer(_path, _payload):
            raise OSError("synthetic evidence disk failure")

        installation = adapter.install_adapter(
            arm="D",
            main_module=main_owner,
            combat_prompts_module=prompt_owner,
            packet_provider=lambda *_args: "frozen packet bytes",
            combat_manager_module=manager_owner,
            movement_hint_observer=lambda _observation: None,
            fixture_id="interior_tavern",
            runtime_root=root,
            lifecycle_id="writer-failure-test",
            turn_record_writer=failing_writer,
            turn_evidence_error_callback=lambda event, error: reported.append(
                (event, error)
            ),
        )
        try:
            prompt = main_owner.build_enhanced_dm_note("test")
            self.assertIn("frozen packet bytes", prompt)
            response = {"narration": "preserved", "actions": []}
            result = manager_owner.validate_combat_response(response, "encounter")
            self.assertIs(result, validation_sentinel)
            self.assertEqual(validation_calls, [((response, "encounter"), {})])
            self.assertEqual(installation.evidence_status, "degraded")
            self.assertIn(
                ("packet_hash_log_write_failed", "OSError"), reported
            )
            self.assertNotIn("synthetic evidence disk failure", repr(reported))
        finally:
            installation.uninstall()

    def test_input_source_drift_fails_closed_without_advancing_turn(self):
        _owner, root, _metadata, _fixtures = self._workspace(arm="B")
        outputs: list[str] = []
        main_ref: dict[str, types.ModuleType] = {}

        def startup() -> None:
            outputs.append(main_ref["main"].build_enhanced_dm_note("startup"))

        def player_input(value: str) -> None:
            outputs.append(value)
            outputs.append(main_ref["main"].build_enhanced_dm_note("player"))

        main_owner = _mock_main_module(
            root,
            on_startup=startup,
            on_player_input=player_input,
        )
        main_ref["main"] = main_owner
        main_owner.build_enhanced_dm_note = lambda *_args, **_kwargs: (
            "Dungeon Master Note: Adjacent locations: baseline."
        )
        prompt_owner = SimpleNamespace(
            assemble_combat_prompt=lambda *_args, **_kwargs: FakeCombatPromptResult(
                "combat", "dynamic"
            ),
            CombatPromptResult=FakeCombatPromptResult,
        )
        reported: list[tuple[str, str]] = []
        eof = EOFError("input exhausted")
        input_values = iter(["nested-a", "drift-player", "nested-b", "nested-c", eof])

        def fake_input(_prompt=""):
            value = next(input_values)
            if isinstance(value, BaseException):
                raise value
            return value

        with mock.patch("builtins.input", fake_input):
            installation = adapter.install_adapter(
                arm="B",
                main_module=main_owner,
                combat_prompts_module=prompt_owner,
                packet_provider=lambda *_args: "startup-only",
                fixture_id="interior_tavern",
                runtime_root=root,
                turn_evidence_error_callback=lambda event, error: reported.append(
                    (event, error)
                ),
            )
            original_source = (root / "main.py").read_bytes()
            (root / "main.py").write_bytes(original_source + b"\n# source drift\n")
            try:
                with self.assertRaises(EOFError):
                    main_owner.main_game_loop()
            finally:
                installation.uninstall()

        self.assertIn(("turn_boundary_source_drift", "SourceDrift"), reported)
        self.assertEqual(installation.evidence_status, "degraded")
        evidence_dir = (
            root
            / "mapping_pilot"
            / "turn_packet_evidence"
            / installation.lifecycle_id
        )
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(evidence_dir.glob("record-*.json"))
        ]
        self.assertFalse(
            any(
                record.get("boundary") == "accepted_player_input"
                for record in records
            )
        )
        self.assertTrue(
            all(record["turn_number"] == 0 for record in records)
        )

    def test_d_raw_response_observation_never_changes_validation_result_or_input(self):
        sentinel = object()
        raw_response = {
            "narration": "Acheron moves.",
            "actions": [],
            "movement_hint": {
                "from": "MPV2_Z_FLOOR",
                "to": "MPV2_Z_TABLE",
                "disengage": False,
                "cover_sought": None,
            },
        }
        seen: list[tuple[Any, ...]] = []
        observations: list[adapter.MovementHintObservation] = []

        def original(*args, **kwargs):
            seen.append((args, kwargs))
            return sentinel

        manager = SimpleNamespace(validate_combat_response=original)
        main_owner = SimpleNamespace(build_enhanced_dm_note=lambda *args: "note")
        prompts = SimpleNamespace(
            assemble_combat_prompt=lambda *_args: FakeCombatPromptResult("p", "s"),
            CombatPromptResult=FakeCombatPromptResult,
        )
        installation = adapter.install_adapter(
            arm="D",
            main_module=main_owner,
            combat_prompts_module=prompts,
            combat_manager_module=manager,
            movement_hint_observer=observations.append,
        )
        args = (raw_response, "encounter", True)
        kwargs = {"mode": "normal"}
        try:
            result = manager.validate_combat_response(*args, **kwargs)
            self.assertIs(result, sentinel)
            self.assertIs(seen[0][0][0], raw_response)
            self.assertEqual(seen[0], (args, kwargs))
            self.assertEqual(observations, [
                adapter.MovementHintObservation(
                    "valid",
                    hint={
                        "from": "MPV2_Z_FLOOR",
                        "to": "MPV2_Z_TABLE",
                        "disengage": False,
                        "cover_sought": None,
                    },
                )
            ])
        finally:
            installation.uninstall()

        self.assertEqual(adapter.observe_movement_hint({"narration": "ok", "actions": []}).status, "missing")
        self.assertEqual(adapter.observe_movement_hint({"movement_hint": "bad"}).status, "invalid")
        self.assertEqual(adapter.observe_movement_hint("not-json").status, "invalid")

        def observer_failure(_observation):
            raise RuntimeError("secret response text must not be reported")

        degradation_events: list[tuple[str, str]] = []

        def record_degradation(event: str, error_type: str) -> None:
            degradation_events.append((event, error_type))

        manager.validate_combat_response = original
        installation = adapter.install_adapter(
            arm="D",
            main_module=main_owner,
            combat_prompts_module=prompts,
            combat_manager_module=manager,
            movement_hint_observer=observer_failure,
            observer_error_callback=record_degradation,
        )
        seen_before_failure = len(seen)
        try:
            self.assertIs(manager.validate_combat_response(raw_response), sentinel)
            self.assertEqual(len(seen), seen_before_failure + 1)
            self.assertEqual(seen[-1], ((raw_response,), {}))
            self.assertEqual(
                degradation_events,
                [("movement_hint_observer_failed", "RuntimeError")],
            )
            self.assertNotIn("secret response text", repr(degradation_events))
        finally:
            installation.uninstall()

    def test_packet_provider_uses_live_location_known_names_and_canonical_feature_state(self):
        _owner, root, metadata, fixtures = self._workspace()
        provider = self._provider(root, metadata, fixtures)
        tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
        call_args = ("dm note", "look", None, tracker, None, False)
        packet = provider("exploration", call_args, {})
        self.assertIn("Current place: The Lantern and Reed Tavern.", packet)
        self.assertIn("destination Rillford Village Green", packet)
        self.assertIn("destination unknown", packet)
        self.assertNotIn("Contents of the kitchen", packet)
        self.assertNotIn("contents beyond the back door", packet)

        area_path = root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA001.json"
        area_data = json.loads(area_path.read_text(encoding="utf-8"))
        area_data["locations"][0]["features"][0]["state"] = "barred"
        self._write_json(area_path, area_data)
        changed_packet = provider("exploration", call_args, {})
        self.assertIn("Back door is barred.", changed_packet)
        self.assertNotIn("Back door is closed unbarred.", changed_packet)

        tracker["worldConditions"]["currentLocationId"] = "MP03"
        tracker["worldConditions"]["currentAreaId"] = "MPA002"
        tracker["worldConditions"]["currentLocation"] = "Old Watchtower Approach"
        moved_args = ("dm note", "travel", None, tracker, None, False)
        moved_packet = provider("exploration", moved_args, {})
        self.assertIn("Current place: Old Watchtower Approach.", moved_packet)
        self.assertNotIn("The Lantern and Reed Tavern", moved_packet)

    def test_packet_provider_adds_only_known_recent_movement_names(self):
        _owner, root, metadata, fixtures = self._workspace()
        tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
        tracker["worldConditions"]["currentLocationId"] = "MP03"
        tracker["worldConditions"]["currentAreaId"] = "MPA002"

        def resolver(**context):
            layout = context["layout"]
            current_id = context["current_location_id"]
            location = next(
                row for row in layout["locations"] if row["location_id"] == current_id
            )
            visible = {
                feature["feature_id"] for feature in location["features"]
                if feature.get("perceivable", True) is not False
            }
            visible.update(
                npc["npc_id"] for npc in location.get("npc_anchors", [])
                if npc.get("perceivable", True) is not False
            )
            return {
                "party_known_ids": {current_id, "MPV2_LOC_VILLAGE_GREEN", *visible},
                "perceived_ids": visible,
                "recent_movement": {
                    "from_location_id": "MPV2_LOC_VILLAGE_GREEN",
                    "to_location_id": current_id,
                },
            }

        provider = self._provider(
            root, metadata, fixtures, knowledge_resolver=resolver
        )
        packet = provider("exploration", ("dm", "arrive", None, tracker), {})
        self.assertIn("recently moved to the current place from Rillford Village Green", packet)

        def unknown_resolver(**context):
            resolved = resolver(**context)
            resolved["party_known_ids"] = {context["current_location_id"]}
            return resolved

        unknown_provider = self._provider(
            root, metadata, fixtures, knowledge_resolver=unknown_resolver
        )
        unknown_packet = unknown_provider(
            "exploration", ("dm", "arrive", None, tracker), {}
        )
        self.assertNotIn("Rillford Village Green", unknown_packet)
        self.assertNotIn("recently moved", unknown_packet)

    def test_combat_projection_is_d_only_and_reads_current_canonical_tracker(self):
        _owner, root, metadata, fixtures = self._workspace(
            arm="D", fixture_id="combat_stage_tavern_zones"
        )
        provider = self._provider(root, metadata, fixtures)
        packet = provider("combat", (), {})
        self.assertIn("Schematic (not to scale):", packet)
        self.assertIn("Relationships:", packet)
        self.assertIn("destination Rillford Village Green", packet)

        b_metadata = copy.deepcopy(metadata)
        b_metadata["arm"] = "B"
        b_provider = self._provider(root, b_metadata, fixtures)
        with self.assertRaises(adapter.UnsupportedMappingPilotArmError):
            b_provider("combat", (), {})

    def test_launcher_rejects_outside_roots_symlinks_and_metadata_conflicts(self):
        owner, root, metadata, _fixtures = self._workspace()
        validated = launcher.validate_sandbox(
            root,
            arm="B",
            fixture_id="interior_tavern",
            party_size=1,
            project_root=owner,
        )
        self.assertEqual(validated.root, root.resolve())

        other = self.work / "other"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "exactly"):
            launcher.validate_runtime_root(other, project_root=owner)
        with self.assertRaisesRegex(ValueError, "traversal"):
            launcher.validate_runtime_root(
                owner / "tmp" / ".." / "tmp" / "combat_capture",
                project_root=owner,
            )
        with self.assertRaisesRegex(ValueError, "arm must be A, B, or D"):
            launcher.validate_sandbox(
                root,
                arm="C",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=owner,
            )

        with self.assertRaisesRegex(ValueError, "does not match"):
            launcher.validate_sandbox(
                root,
                arm="D",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=owner,
            )
        with self.assertRaisesRegex(ValueError, "party size"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=4,
                project_root=owner,
            )
        with self.assertRaisesRegex(ValueError, "party size"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=True,
                project_root=owner,
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="landscape_village",
                party_size=1,
                project_root=owner,
            )

        metadata_path = root / "mapping_pilot" / "seed_metadata.json"
        combat_owner, combat_root, _combat_metadata, _combat_fixtures = self._workspace(
            arm="B", fixture_id="combat_stage_tavern_zones"
        )
        with self.assertRaisesRegex(ValueError, "not registered"):
            launcher.validate_sandbox(
                combat_root,
                arm="B",
                fixture_id="combat_stage_tavern_zones",
                party_size=1,
                project_root=combat_owner,
            )

        original_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        tampered_seed = copy.deepcopy(original_metadata)
        tampered_seed["counterbalance"]["fixed_seed"] += 1
        self._write_json(metadata_path, tampered_seed)
        with self.assertRaisesRegex(ValueError, "counterbalance seed"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=owner,
            )

        original_metadata["api_key"] = "TEST_SECRET_SHOULD_NOT_LEAK"
        self._write_json(metadata_path, original_metadata)
        with self.assertRaises(ValueError) as caught:
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=owner,
            )
        self.assertNotIn("TEST_SECRET_SHOULD_NOT_LEAK", str(caught.exception))

        symlink_owner = self.work / "symlink-owner"
        (symlink_owner / "tmp").mkdir(parents=True)
        target = self.work / "symlink-target"
        target.mkdir()
        (symlink_owner / "tmp" / "combat_capture").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            launcher.validate_runtime_root(
                symlink_owner / "tmp" / "combat_capture",
                project_root=symlink_owner,
            )

        file_symlink_owner, file_symlink_root, _file_metadata, _file_fixtures = self._workspace()
        config_path = file_symlink_root / "config.py"
        config_path.unlink()
        external_config = self.work / "external-config.py"
        external_config.write_text("WEB_PORT = 8360\n", encoding="utf-8")
        config_path.symlink_to(external_config)
        with self.assertRaisesRegex(ValueError, "sandbox path is unsafe"):
            launcher.validate_sandbox(
                file_symlink_root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=file_symlink_owner,
            )

    def test_launcher_resume_accepts_only_checkpointed_frozen_location_moves(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                owner, root, _metadata, _fixtures = self._workspace(
                    party_size=party_size
                )
                metadata_path = root / "mapping_pilot" / "seed_metadata.json"
                original_metadata = metadata_path.read_bytes()
                self._move_tracker_to_green(root)
                checkpoint = self._parent_state_hash(owner)
                original_cwd = pathlib.Path.cwd()
                original_path = list(sys.path)
                original_launcher_root = launcher.PROJECT_ROOT
                imports: list[str] = []
                starts: list[str] = []
                modules = {
                    "web.web_interface": SimpleNamespace(
                        __file__=str(root / "web" / "web_interface.py"),
                        dm_main=SimpleNamespace(__file__=str(root / "main.py")),
                        INSTALL_ROOT=str(root),
                        _configured_web_port=8360,
                        WEB_HOST="127.0.0.1",
                        app=object(),
                        socketio=SimpleNamespace(),
                    ),
                    "core.combat.prompts": SimpleNamespace(
                        __file__=str(root / "core" / "combat" / "prompts.py")
                    ),
                    "core.combat.combat_manager": SimpleNamespace(
                        __file__=str(root / "core" / "combat" / "combat_manager.py")
                    ),
                    "scripts.mapping_pilot.adapter": SimpleNamespace(
                        __file__=str(root / "scripts" / "mapping_pilot" / "adapter.py"),
                        SandboxPacketProvider=lambda **_kwargs: object(),
                    ),
                }

                def importer(name: str) -> Any:
                    imports.append(name)
                    return modules[name]

                def server_runner(_web: Any) -> str:
                    starts.append("server")
                    return "resumed"

                try:
                    launcher.PROJECT_ROOT = owner
                    result = launcher.launch(
                        arm="B",
                        fixture_id="interior_tavern",
                        party_size=party_size,
                        resume=True,
                        resume_checkpoint_sha256=checkpoint,
                        runtime_root=root,
                        module_importer=importer,
                        server_runner=server_runner,
                        adapter_installer=lambda **_kwargs: SimpleNamespace(
                            uninstall=lambda: None
                        ),
                    )
                finally:
                    launcher.PROJECT_ROOT = original_launcher_root
                    os.chdir(original_cwd)
                    sys.path[:] = original_path

                self.assertEqual(result, "resumed")
                self.assertEqual(starts, ["server"])
                self.assertTrue(imports)
                self.assertEqual(metadata_path.read_bytes(), original_metadata)
                self.assertEqual(
                    self._parent_state_hash(owner), checkpoint
                )

    def test_launcher_initial_location_guard_still_rejects_moved_tracker(self):
        owner, root, _metadata, _fixtures = self._workspace()
        self._move_tracker_to_green(root)
        with self.assertRaisesRegex(ValueError, "conflicts with seed metadata"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                project_root=owner,
            )

    def test_launcher_resume_rejects_missing_tampered_and_drifted_checkpoints(self):
        owner, root, _metadata, _fixtures = self._workspace()
        self._move_tracker_to_green(root)
        with self.assertRaisesRegex(ValueError, "checkpoint is missing"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                resume=True,
                project_root=owner,
            )

        checkpoint = self._parent_state_hash(owner)
        with self.assertRaisesRegex(ValueError, "checkpoint hash does not match"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                resume=True,
                resume_checkpoint_sha256="0" * 64,
                project_root=owner,
            )

        character_path = root / "characters" / "Acheron.json"
        character_path.write_text('{"name":"changed"}', encoding="ascii")
        with self.assertRaisesRegex(ValueError, "checkpoint hash does not match"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                resume=True,
                resume_checkpoint_sha256=checkpoint,
                project_root=owner,
            )

    def test_launcher_resume_rejects_tracker_identity_and_location_drift(self):
        cases = (
            ("roster", "sandbox party tracker conflicts with seed metadata"),
            ("module", "sandbox party tracker conflicts with seed metadata"),
            ("active_pc", "sandbox party tracker conflicts with seed metadata"),
            ("unknown_location", "resume location identity is unknown"),
            ("area_mismatch", "resume location area does not match"),
            ("fake_connection", "resume location is not a frozen open exit"),
            ("self_loop", "connectivity is not frozen"),
            ("duplicate_location", "runtime location is missing or duplicated"),
        )
        for case, expected_error in cases:
            with self.subTest(case=case):
                owner, root, _metadata, _fixtures = self._workspace()
                self._move_tracker_to_green(root)
                tracker_path = root / "party_tracker.json"
                tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
                if case == "roster":
                    tracker["partyMembers"] = ["Other"]
                elif case == "module":
                    tracker["module"] = "Other_Module"
                elif case == "active_pc":
                    tracker["active_character"] = "Not a party member"
                elif case == "unknown_location":
                    tracker["worldConditions"]["currentLocationId"] = "MP99"
                elif case == "area_mismatch":
                    tracker["worldConditions"]["currentAreaId"] = "MPA002"
                elif case == "fake_connection":
                    tracker["worldConditions"]["currentLocationId"] = "MP03"
                    tracker["worldConditions"]["currentAreaId"] = "MPA002"
                self._write_json(tracker_path, tracker)

                if case == "self_loop":
                    area_path = root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA001.json"
                    area = json.loads(area_path.read_text(encoding="utf-8"))
                    area["locations"][1]["connectivity"] = ["MP01", "MP02"]
                    self._write_json(area_path, area)
                elif case == "duplicate_location":
                    area_path = root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA002.json"
                    area = json.loads(area_path.read_text(encoding="utf-8"))
                    area["locations"].append(
                        {"locationId": "MP02", "name": "Fake duplicate"}
                    )
                    self._write_json(area_path, area)

                checkpoint = self._parent_state_hash(owner)
                with self.assertRaisesRegex(ValueError, expected_error):
                    launcher.validate_sandbox(
                        root,
                        arm="B",
                        fixture_id="interior_tavern",
                        party_size=1,
                        resume=True,
                        resume_checkpoint_sha256=checkpoint,
                        project_root=owner,
                    )

    def test_launcher_resume_rejects_symlinked_checkpoint_state(self):
        owner, root, _metadata, _fixtures = self._workspace()
        self._move_tracker_to_green(root)
        character_path = root / "characters" / "Acheron.json"
        outside = self.work / "outside-character.json"
        outside.write_text('{"name":"Acheron"}', encoding="ascii")
        character_path.unlink()
        character_path.symlink_to(outside)

        with self.assertRaisesRegex(ValueError, "sandbox path is unsafe"):
            launcher.validate_sandbox(
                root,
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                resume=True,
                resume_checkpoint_sha256="a" * 64,
                project_root=owner,
            )

    def test_launcher_imports_and_starts_the_sandbox_in_the_same_process(self):
        owner, root, metadata, fixtures = self._workspace()
        original_browser_flag = os.environ.get("NEQ_OPEN_BROWSER")
        os.environ["NEQ_OPEN_BROWSER"] = "1"
        original_cwd = pathlib.Path.cwd()
        original_path = list(sys.path)
        original_launcher_root = launcher.PROJECT_ROOT
        original_dm = lambda *args, **kwargs: "Dungeon Master Note: Adjacent locations: baseline."
        original_prompt = lambda *_args, **_kwargs: FakeCombatPromptResult("base", "state")
        main_owner = _mock_main_module(
            root,
            on_startup=lambda: None,
            on_player_input=lambda _value: None,
        )
        main_owner.build_enhanced_dm_note = original_dm
        prompt_owner = SimpleNamespace(
            __file__=str(root / "core" / "combat" / "prompts.py"),
            assemble_combat_prompt=original_prompt,
            CombatPromptResult=FakeCombatPromptResult,
        )
        manager_owner = SimpleNamespace(
            __file__=str(root / "core" / "combat" / "combat_manager.py"),
            validate_combat_response=lambda response, *_args: response,
        )
        def fake_socketio_run(app, **kwargs):
            self.assertIs(app, web_owner.app)
            self.assertEqual(os.getpid(), imported[0][1])
            self.assertEqual(os.environ.get("NEQ_OPEN_BROWSER"), "0")
            self.assertEqual(pathlib.Path.cwd(), root)
            self.assertIn(str(root), sys.path)
            self.assertIsNot(main_owner.build_enhanced_dm_note, original_dm)
            self.assertEqual(kwargs, {
                "host": "127.0.0.1",
                "port": 8360,
                "debug": False,
                "use_reloader": False,
                "allow_unsafe_werkzeug": True,
            })
            tracker = json.loads((root / "party_tracker.json").read_text(encoding="utf-8"))
            augmented = main_owner.build_enhanced_dm_note(
                "Dungeon Master Note: Adjacent locations: old atlas.",
                "look",
                None,
                tracker,
                None,
                False,
            )
            self.assertIn("EXITS / COMPACT ORIENTATION", augmented)
            self.assertIn("Current place: The Lantern and Reed Tavern.", augmented)
            self.assertNotIn("old atlas", augmented)
            return "same-process-started"

        web_owner = SimpleNamespace(
            __file__=str(root / "web" / "web_interface.py"),
            dm_main=main_owner,
            INSTALL_ROOT=str(root),
            _configured_web_port=8360,
            WEB_HOST="127.0.0.1",
            app=object(),
            socketio=SimpleNamespace(run=fake_socketio_run),
        )
        adapter_owner = SimpleNamespace(
            __file__=str(root / "scripts" / "mapping_pilot" / "adapter.py"),
            SandboxPacketProvider=adapter.SandboxPacketProvider,
            install_adapter=adapter.install_adapter,
        )
        owners = {
            "web.web_interface": web_owner,
            "core.combat.prompts": prompt_owner,
            "core.combat.combat_manager": manager_owner,
            "scripts.mapping_pilot.adapter": adapter_owner,
        }
        imported: list[tuple[str, int, str, pathlib.Path]] = []

        def importer(name):
            imported.append((name, os.getpid(), os.environ.get("NEQ_OPEN_BROWSER", ""), pathlib.Path.cwd()))
            return owners[name]

        try:
            launcher.PROJECT_ROOT = owner
            result = launcher.launch(
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                runtime_root=root,
                module_importer=importer,
            )
        finally:
            launcher.PROJECT_ROOT = original_launcher_root
            if original_browser_flag is None:
                os.environ.pop("NEQ_OPEN_BROWSER", None)
            else:
                os.environ["NEQ_OPEN_BROWSER"] = original_browser_flag
            os.chdir(original_cwd)
            sys.path[:] = original_path

        self.assertEqual(result, "same-process-started")
        self.assertEqual([item[0] for item in imported], [
            "web.web_interface",
            "core.combat.prompts",
            "core.combat.combat_manager",
            "scripts.mapping_pilot.adapter",
        ])
        self.assertTrue(all(item[2] == "0" and item[3] == root for item in imported))
        self.assertIs(main_owner.build_enhanced_dm_note, original_dm)
        self.assertFalse(hasattr(main_owner, "input"))
        self.assertIs(prompt_owner.assemble_combat_prompt, original_prompt)
        self.assertEqual(pathlib.Path.cwd(), original_cwd)
        self.assertEqual(sys.path, original_path)

    def test_provider_free_tests_do_not_import_runtime_owners(self):
        self.assertNotIn("main", sys.modules)
        self.assertNotIn("web.web_interface", sys.modules)
        self.assertNotIn("core.combat.combat_manager", sys.modules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
