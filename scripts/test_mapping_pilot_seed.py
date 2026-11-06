# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the opt-in Mapping Pilot sandbox seeder."""

from __future__ import annotations

import builtins
import contextlib
import io
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types
import unittest
import uuid
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arm process-wide guards before importing the seeder or pilot fixture helpers.
from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

_PRIVATE_CONFIG = (ROOT / "config.py").resolve()
_REAL_BUILTINS_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open


def _is_private_config(path: Any) -> bool:
    try:
        return pathlib.Path(os.fsdecode(path)).resolve() == _PRIVATE_CONFIG
    except (OSError, TypeError, ValueError):
        return False


def _guard_config_open(path, mode="r", *args, **kwargs):
    if _is_private_config(path) and not any(flag in mode for flag in "wax+"):
        raise TripwireFailure("mapping-pilot test attempted to read config.py")
    return _REAL_BUILTINS_OPEN(path, mode, *args, **kwargs)


def _guard_config_io_open(path, mode="r", *args, **kwargs):
    if _is_private_config(path) and not any(flag in mode for flag in "wax+"):
        raise TripwireFailure("mapping-pilot test attempted to read config.py")
    return _REAL_IO_OPEN(path, mode, *args, **kwargs)


def _guard_config_os_open(path, flags, *args, **kwargs):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if _is_private_config(path) and not flags & write_flags:
        raise TripwireFailure("mapping-pilot test attempted to read config.py")
    return _REAL_OS_OPEN(path, flags, *args, **kwargs)


builtins.open = _guard_config_open
io.open = _guard_config_io_open
os.open = _guard_config_os_open
if hasattr(io, "open_code"):
    _REAL_IO_OPEN_CODE = io.open_code

    def _guard_config_open_code(path):
        if _is_private_config(path):
            raise TripwireFailure("mapping-pilot test attempted to import config.py")
        return _REAL_IO_OPEN_CODE(path)

    io.open_code = _guard_config_open_code

from scripts import seed_combat_capture as seeder
from scripts.mapping_pilot.fixtures import FIXTURE_FILES


PREREG_ROOT = ROOT / "plans" / "v2-mapping-pilot-prereg"
_PLANNED_ROWS = {
    ("interior_tavern", 1): ("A", 5101, "E01"),
    ("interior_tavern", 4): ("A", 5103, "E09"),
    ("landscape_village", 1): ("A", 5102, "E06"),
    ("landscape_village", 4): ("A", 5105, "E14"),
    ("transition_tower_approach", 1): ("A", 5102, "E06"),
    ("transition_tower_approach", 4): ("A", 5105, "E14"),
    ("combat_stage_tavern_zones", 1): ("A", 5201, "C01"),
    ("combat_stage_tavern_zones", 4): ("A", 5203, "C06"),
}


def _read_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree_bytes(root: pathlib.Path) -> Dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_capture_template(module: types.ModuleType) -> int:
    """Supply a harmless copied module; never inspect installed campaign files."""
    module_root = module.SANDBOX_ROOT / "modules" / "Capture_Arena"
    area_path = module_root / "areas" / "CTR001.json"
    map_path = module_root / "map_CTR001.json"
    area_path.parent.mkdir(parents=True, exist_ok=True)
    area_path.write_text(
        json.dumps({
            "areaId": "CTR001",
            "areaName": "Capture Arena",
            "locations": [{"locationId": "CA01", "name": "Waystone Gate"}],
        }, sort_keys=True),
        encoding="ascii",
    )
    map_path.write_text(
        json.dumps({"startRoom": "CA01"}, sort_keys=True), encoding="ascii"
    )
    monster_source = ROOT / "modules" / "Capture_Arena" / "monsters" / "goblin.json"
    monster_target = module_root / "monsters" / "goblin.json"
    monster_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(monster_source, monster_target)
    return 3


@contextlib.contextmanager
def _sandbox_globals(
    module: types.ModuleType, sandbox: pathlib.Path
) -> Iterator[None]:
    display = sandbox.relative_to(ROOT).as_posix()
    with patch.object(module, "SANDBOX_ROOT", sandbox), \
            patch.object(module, "SANDBOX_DISPLAY", display), \
            patch.object(module, "_assert_sandbox_root", return_value=sandbox), \
            patch.object(module, "_copy_runtime", side_effect=lambda: _write_capture_template(module)), \
            patch.object(module, "_patch_sandbox_config"), \
            patch.object(module, "_patch_sandbox_model_config"), \
            patch.object(module, "_hash_installed_sentinels", return_value={}):
        yield


class MappingPilotSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = pathlib.Path("tmp") / ("mapping_pilot_seed_" + uuid.uuid4().hex)
        (ROOT / self.scratch).mkdir(parents=True)

    def tearDown(self) -> None:
        scratch_path = ROOT / self.scratch
        if scratch_path.exists():
            shutil.rmtree(scratch_path)

    def _run_seed(
        self, fixture_id: str, party_size: int, arm: str, seed: int, name: str
    ) -> Tuple[pathlib.Path, str]:
        sandbox = ROOT / self.scratch / name / "combat_capture"
        argv = [
            "--prepare",
            "--party",
            str(party_size),
            "--mapping-pilot-fixture",
            fixture_id,
            "--mapping-pilot-arm",
            arm,
            "--mapping-pilot-seed",
            str(seed),
        ]
        output = io.StringIO()
        with _sandbox_globals(seeder, sandbox), contextlib.redirect_stdout(output):
            result = seeder.main(argv)
        self.assertEqual(result, 0)
        self.assertFalse((sandbox / "config.py").exists())
        self.assertFalse((sandbox / "model_config.py").exists())
        return sandbox, output.getvalue()

    def _assert_rejected_before_mutation(
        self,
        argv,
        *,
        prereg_root: pathlib.Path | None = None,
    ) -> None:
        sandbox = ROOT / self.scratch / "invalid" / "combat_capture"
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "sentinel.bin").write_bytes(b"preserve-before-validation")
        before = _tree_bytes(sandbox)
        display = sandbox.relative_to(ROOT).as_posix()
        root_patch = (
            patch.object(seeder, "MAPPING_PILOT_PREREG_ROOT", prereg_root)
            if prereg_root is not None
            else contextlib.nullcontext()
        )
        with root_patch, \
                patch.object(seeder, "SANDBOX_ROOT", sandbox), \
                patch.object(seeder, "SANDBOX_DISPLAY", display), \
                patch.object(seeder, "_assert_sandbox_root", return_value=sandbox), \
                patch.object(seeder, "_copy_runtime") as copy_runtime, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                seeder.main(argv)
        self.assertEqual(raised.exception.code, 2)
        copy_runtime.assert_not_called()
        self.assertEqual(_tree_bytes(sandbox), before)

    def test_all_fixture_dry_seeds_have_consistent_canonical_state(self) -> None:
        for (fixture_id, party_size), (arm, seed, row_id) in _PLANNED_ROWS.items():
            with self.subTest(fixture=fixture_id, party_size=party_size):
                sandbox, _output = self._run_seed(
                    fixture_id, party_size, arm, seed,
                    "%s_p%d" % (fixture_id, party_size),
                )
                module_root = sandbox / "modules" / "Mapping_Pilot_Arena"
                capture_root = sandbox / "modules" / "Capture_Arena"
                self.assertTrue(capture_root.is_dir())
                self.assertTrue(module_root.is_dir())
                id_map = _read_json(module_root / "location_id_map.json")
                metadata = _read_json(sandbox / "mapping_pilot" / "seed_metadata.json")
                tracker = _read_json(sandbox / "party_tracker.json")
                fixture_source = _read_json(PREREG_ROOT / FIXTURE_FILES[fixture_id])
                source_location_id = fixture_source["location_ids"][0]
                runtime_location_id = id_map["runtime_location_ids"][source_location_id]
                area_matches = []
                for area_path in (module_root / "areas").glob("*.json"):
                    if area_path.name.endswith("_BU.json"):
                        continue
                    area_payload = _read_json(area_path)
                    area_matches.extend(
                        (area_payload, location)
                        for location in area_payload["locations"]
                        if location["locationId"] == runtime_location_id
                    )
                self.assertEqual(len(area_matches), 1)
                area_payload, location = area_matches[0]
                self.assertEqual(tracker["module"], "Mapping_Pilot_Arena")
                conditions = tracker["worldConditions"]
                self.assertEqual(conditions["currentAreaId"], area_payload["areaId"])
                self.assertEqual(conditions["currentArea"], area_payload["areaName"])
                self.assertEqual(conditions["currentLocationId"], runtime_location_id)
                self.assertEqual(conditions["currentLocation"], location["name"])
                map_payload = _read_json(
                    module_root / ("map_%s.json" % area_payload["areaId"])
                )
                self.assertEqual(map_payload["startRoom"], runtime_location_id)
                self.assertEqual(metadata["effective_seed"], seed)
                self.assertEqual(metadata["arm"], arm)
                self.assertEqual(metadata["fixture_id"], fixture_id)
                self.assertEqual(metadata["party"]["size"], party_size)
                self.assertEqual(metadata["counterbalance"]["row_id"], row_id)
                self.assertEqual(metadata["counterbalance"]["fixed_seed"], seed)
                self.assertEqual(
                    metadata["mapping"]["source_location_id"], source_location_id
                )
                self.assertEqual(
                    metadata["mapping"]["runtime_location_id"], runtime_location_id
                )

                if fixture_id == "combat_stage_tavern_zones":
                    encounter_id = conditions["activeCombatEncounter"]
                    self.assertEqual(encounter_id, "mapping_pilot_combat")
                    encounter = _read_json(
                        sandbox / "modules" / "encounters" /
                        ("encounter_%s.json" % encounter_id)
                    )
                    creature_rows = encounter["creatures"]
                    seeded_names = [
                        "Acheron", "Merisiel", "Kira", "Vitreol"
                    ][:party_size]
                    self.assertEqual(
                        [row["name"] for row in creature_rows if row["type"] == "player"],
                        seeded_names,
                    )
                    enemy_rows = [row for row in creature_rows if row["type"] == "enemy"]
                    combat_fixture = _read_json(
                        PREREG_ROOT / FIXTURE_FILES["combat_stage_tavern_zones"]
                    )
                    self.assertEqual(
                        {row["name"] for row in enemy_rows},
                        {row["name"] for row in combat_fixture["occupant_roles"]},
                    )
                    capture_goblin = _read_json(
                        capture_root / "monsters" / "goblin.json"
                    )
                    authored_goblin = _read_json(
                        ROOT / "modules" / "Capture_Arena" / "monsters" / "goblin.json"
                    )
                    pilot_goblin_path = module_root / "monsters" / "goblin.json"
                    self.assertEqual(capture_goblin, authored_goblin)
                    self.assertEqual(_read_json(pilot_goblin_path), authored_goblin)
                    for enemy in enemy_rows:
                        monster_type = enemy.get("monsterType")
                        self.assertIsInstance(monster_type, str)
                        resolved_template = (
                            module_root / "monsters" / (monster_type.lower() + ".json")
                        )
                        self.assertTrue(resolved_template.is_file())
                        template = _read_json(resolved_template)
                        self.assertEqual(template["name"], monster_type)
                        self.assertEqual(template, authored_goblin)
                    combat_mapping = metadata["mapping"]["combat_actors"]
                    self.assertFalse(combat_mapping["movement_enforced"])
                    placement = combat_fixture["initial_placement_rules"][
                        "party_%d" % party_size
                    ]
                    self.assertEqual(
                        {
                            row["actor_id"]: row["initial_zone_id"]
                            for row in combat_mapping["party_actors"]
                        },
                        placement["pcs"],
                    )
                    self.assertEqual(
                        {
                            row["actor_id"]: row["initial_zone_id"]
                            for row in combat_mapping["enemy_roles"]
                        },
                        placement["enemies"],
                    )
                else:
                    self.assertEqual(conditions["activeCombatEncounter"], "")
                    self.assertNotIn("combat_actors", metadata["mapping"])

    def test_combat_seed_fails_closed_when_copied_goblin_template_is_bad(self) -> None:
        fixtures = __import__("scripts.mapping_pilot.fixtures", fromlist=["fixtures"])
        plan = {"fixture_id": "combat_stage_tavern_zones", "prereg_root": PREREG_ROOT}
        for source_kind, source_bytes in (
            ("missing", None),
            ("invalid_json", b"{not-json"),
            ("malformed_shape", b'{"name":"Goblin"}'),
        ):
            with self.subTest(source_kind=source_kind):
                sandbox = ROOT / self.scratch / source_kind / "combat_capture"
                source = (
                    sandbox / "modules" / "Capture_Arena" / "monsters" / "goblin.json"
                )
                source.parent.mkdir(parents=True, exist_ok=True)
                if source_bytes is not None:
                    source.write_bytes(source_bytes)
                with patch.object(seeder, "SANDBOX_ROOT", sandbox), \
                        patch.object(seeder, "_assert_sandbox_root", return_value=sandbox), \
                        patch.object(fixtures, "write_fixture_outputs") as write_outputs:
                    with self.assertRaisesRegex(RuntimeError, "Goblin template"):
                        seeder._seed_mapping_pilot(plan, ["Acheron"])
                write_outputs.assert_not_called()
                self.assertFalse(
                    (sandbox / "modules" / "Mapping_Pilot_Arena").exists()
                )

    def test_every_planned_row_and_reserve_seed_is_counterbalance_bound(self) -> None:
        counterbalance = _read_json(PREREG_ROOT / "counterbalance.json")
        for row in counterbalance["rows"]:
            if row["row_type"] != "planned":
                continue
            script = _read_json(PREREG_ROOT / row["script"])
            for fixture_id in script["fixture_ids"]:
                plan = seeder._build_mapping_pilot_seed_plan(
                    fixture_id, row["arm"], row["party"], row["fixed_seed"]
                )
                self.assertEqual(plan["counterbalance"]["row_id"], row["row_id"])
                self.assertEqual(plan["effective_seed"], row["fixed_seed"])

        for reserve_row in (
            row for row in counterbalance["rows"]
            if row["row_type"] == "replacement_only"
        ):
            plan = seeder._build_mapping_pilot_seed_plan(
                "interior_tavern", "A", 1, reserve_row["fixed_seed"]
            )
            self.assertEqual(plan["counterbalance"]["row_id"], reserve_row["row_id"])
            self.assertEqual(
                plan["counterbalance"]["row_type"], "replacement_only"
            )
            self.assertEqual(plan["counterbalance"]["fixed_seed"], reserve_row["fixed_seed"])

    def test_invalid_and_incomplete_options_fail_before_sandbox_mutation(self) -> None:
        common = ["--prepare", "--party", "1"]
        self._assert_rejected_before_mutation([
            "--restore",
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "5101",
        ])
        self._assert_rejected_before_mutation(
            common + ["--mapping-pilot-fixture", "interior_tavern"]
        )
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "A",
        ])
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "not_a_fixture",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "5101",
        ])
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "C",
            "--mapping-pilot-seed", "5101",
        ])
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "combat_stage_tavern_zones",
            "--mapping-pilot-arm", "B",
            "--mapping-pilot-seed", "5201",
        ])
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "9999",
        ])
        self._assert_rejected_before_mutation(common + [
            "--mapping-pilot-fixture", "landscape_village",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "5101",
        ])
        self._assert_rejected_before_mutation([
            "--prepare", "--party", "4",
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "5101",
        ])
        self._assert_rejected_before_mutation([
            "--prepare", "--party", "1", "--scenario", "combat-smoke",
            "--mapping-pilot-fixture", "interior_tavern",
            "--mapping-pilot-arm", "A",
            "--mapping-pilot-seed", "5101",
        ])

    def test_manifest_mismatch_fails_before_sandbox_mutation(self) -> None:
        copied_prereg = ROOT / self.scratch / "prereg"
        shutil.copytree(PREREG_ROOT, copied_prereg)
        fixture_path = copied_prereg / "fixtures" / "interior_tavern.json"
        fixture_path.write_bytes(fixture_path.read_bytes() + b" ")
        self._assert_rejected_before_mutation(
            [
                "--prepare", "--party", "1",
                "--mapping-pilot-fixture", "interior_tavern",
                "--mapping-pilot-arm", "A",
                "--mapping-pilot-seed", "5101",
            ],
            prereg_root=copied_prereg,
        )

    def test_omitted_pilot_options_match_pre_edit_seeder_bytes(self) -> None:
        # Pin the original SP0 seeder: after this implementation is committed,
        # HEAD will contain the pilot flags and can no longer serve as the legacy oracle.
        # check=True intentionally makes a missing baseline revision fail this test.
        legacy_source = subprocess.run(
            [
                "git",
                "show",
                "c6ed675b2efa4fafb85d3d9df2a236f91ae850d9:scripts/seed_combat_capture.py",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        self.assertNotIn(b"--mapping-pilot-fixture", legacy_source)
        legacy_source_path = ROOT / self.scratch / "legacy_seed_combat_capture.py"
        legacy_source_path.write_bytes(legacy_source)
        spec = importlib.util.spec_from_file_location(
            "_mapping_pilot_legacy_seed_combat_capture", legacy_source_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("could not load pinned legacy combat seeder")
        legacy_module = importlib.util.module_from_spec(spec)
        # Keep the pinned module's original project-root bootstrap semantics.
        legacy_module.__file__ = str(ROOT / "scripts" / "seed_combat_capture.py")
        spec.loader.exec_module(legacy_module)

        sandbox = ROOT / self.scratch / "legacy-parity" / "combat_capture"
        runs = []
        for module in (legacy_module, seeder):
            output = io.StringIO()
            errors = io.StringIO()
            with _sandbox_globals(module, sandbox), \
                    contextlib.redirect_stdout(output), \
                    contextlib.redirect_stderr(errors):
                result = module.main(["--prepare", "--party", "1"])
            self.assertEqual(result, 0)
            self.assertEqual(errors.getvalue(), "")
            self.assertFalse((sandbox / "config.py").exists())
            runs.append((output.getvalue().encode("utf-8"), _tree_bytes(sandbox)))
        self.assertEqual(runs[1], runs[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
