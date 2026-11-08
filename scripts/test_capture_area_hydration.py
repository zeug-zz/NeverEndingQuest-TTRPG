# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for Capture_Arena's sandbox-only area hydration."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

from scripts import seed_combat_capture as seeder


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _area_payload() -> dict:
    return {
        "areaId": "CTR001",
        "areaName": "Capture Arena",
        "locations": [
            {"locationId": "CA01", "name": "Waystone Gate"},
            {"locationId": "CA02", "name": "Training Pit", "tacticalFeatures": []},
        ],
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class CaptureAreaHydrationTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch_root = ROOT / "tmp" / "n2"
        self.scratch = tempfile.TemporaryDirectory(
            prefix="capture-area-hydration-", dir=str(scratch_root)
        )
        self.scratch_root = Path(self.scratch.name)
        self.source_areas = ROOT / "modules" / "Capture_Arena" / "areas"
        self.source_snapshot = _tree_bytes(self.source_areas)
        self.assertFalse((self.source_areas / "CTR001.json").exists())

    def tearDown(self) -> None:
        try:
            self.assertEqual(_tree_bytes(self.source_areas), self.source_snapshot)
            self.assertFalse((self.source_areas / "CTR001.json").exists())
        finally:
            self.scratch.cleanup()

    def _make_project(
        self,
        name: str,
        *,
        backup_names: tuple[str, ...] = ("CTR001_BU.json",),
        live_bytes: bytes | None = None,
        include_canonical_live: bool = False,
    ) -> tuple[Path, bytes]:
        project = self.scratch_root / name
        for relative in (
            "core", "utils", "updates", "web", "prompts", "schemas", "scripts",
            "templates", "icons", "data/bestiary", "data/styles",
            "modules/Capture_Arena/areas",
        ):
            (project / relative).mkdir(parents=True, exist_ok=True)
        (project / "tmp").mkdir(exist_ok=True)

        (project / "main.py").write_text("# fake sandbox source\n", encoding="ascii")
        (project / "run_web.py").write_text("# fake sandbox source\n", encoding="ascii")
        (project / "config.py").write_text("WEB_PORT = 8357\n", encoding="ascii")
        (project / "model_config.py").write_text(
            "ENABLE_COMBAT_TURN_TRACE = False\n"
            "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED = False\n"
            "COMBAT_TACTICAL_BRAIN_ENABLED = False\n"
            "COMBAT_ALLY_CONTROLLER_ENABLED = False\n"
            "COMBAT_ALLY_PREFETCH_ENABLED = False\n"
            "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED = False\n",
            encoding="ascii",
        )
        (project / "VERSION").write_text("test\n", encoding="ascii")

        area_bytes = _json_bytes(_area_payload())
        areas = project / "modules" / "Capture_Arena" / "areas"
        for backup_name in backup_names:
            (areas / backup_name).write_bytes(area_bytes)
        if live_bytes is not None:
            (areas / "CTR001.json").write_bytes(live_bytes)
        elif include_canonical_live:
            (areas / "CTR001.json").write_bytes(area_bytes)

        (project / "modules" / "Capture_Arena" / "map_CTR001.json").write_bytes(
            _json_bytes({"startRoom": "CA01"})
        )
        return project, area_bytes

    @contextlib.contextmanager
    def _patched_project(self, project: Path):
        sandbox = project / "tmp" / "combat_capture"
        with patch.object(seeder, "PROJECT_ROOT", project), \
                patch.object(seeder, "SANDBOX_ROOT", sandbox), \
                patch.object(seeder, "SANDBOX_DISPLAY", "tmp/combat_capture"):
            yield sandbox

    def _prepare(self, project: Path, party_size: int, **kwargs) -> Path:
        logger = logging.getLogger("utils.file_operations")
        previous_level = logger.level
        source_areas = project / "modules" / "Capture_Arena" / "areas"
        source_before = _tree_bytes(source_areas)
        with self._patched_project(project) as sandbox, contextlib.redirect_stdout(io.StringIO()):
            try:
                result = seeder.prepare(party_size, **kwargs)
            finally:
                logger.setLevel(previous_level)
        self.assertEqual(result, 0)
        self.assertEqual(_tree_bytes(source_areas), source_before)
        return sandbox

    def _assert_prepared_seed(self, sandbox: Path, party_size: int) -> None:
        expected_names = seeder._party_names(party_size)
        area_path = sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001.json"
        area = json.loads(area_path.read_bytes())
        self.assertEqual(area["areaId"], "CTR001")
        self.assertTrue(area["locations"])

        tracker = json.loads((sandbox / "party_tracker.json").read_bytes())
        self.assertEqual(tracker["partyMembers"], expected_names)
        self.assertEqual(tracker["active_character"], expected_names[0])
        encounter_id = tracker["worldConditions"]["activeCombatEncounter"]
        self.assertTrue(encounter_id)
        encounter_path = sandbox / "modules" / "encounters" / (
            "encounter_%s.json" % encounter_id
        )
        encounter = json.loads(encounter_path.read_bytes())
        players = [row["name"] for row in encounter["creatures"] if row["type"] == "player"]
        enemies = [row for row in encounter["creatures"] if row["type"] == "enemy"]
        self.assertEqual(players, expected_names)
        self.assertTrue(enemies)

    def test_imports_remain_provider_free_and_do_not_load_private_config(self) -> None:
        forbidden = ("openai", "requests", "httpx", "socketio", "config")
        loaded = sorted(
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        )
        self.assertEqual(loaded, [])

    def test_clean_checkout_prepare_hydrates_full_one_and_four_pc_seeds(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                project, canonical_bytes = self._make_project("clean-p%d" % party_size)
                source_before = _tree_bytes(project / "modules" / "Capture_Arena" / "areas")
                self.assertEqual(set(source_before), {"CTR001_BU.json"})
                sandbox = self._prepare(project, party_size)
                self._assert_prepared_seed(sandbox, party_size)
                self.assertEqual(
                    (sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001.json").read_bytes(),
                    canonical_bytes,
                )
                self.assertEqual(
                    _tree_bytes(project / "modules" / "Capture_Arena" / "areas"),
                    source_before,
                )

    def test_canonical_live_and_hydrated_inputs_produce_identical_sandbox_hashes(self) -> None:
        hydrated_project, _canonical = self._make_project("hydrated")
        live_project, _ = self._make_project("live", include_canonical_live=True)
        hydrated_sandbox = self._prepare(hydrated_project, 1)
        live_sandbox = self._prepare(live_project, 1)

        hydrated_tree = _tree_bytes(hydrated_sandbox)
        live_tree = _tree_bytes(live_sandbox)
        self.assertEqual(
            {path: hashlib.sha256(data).hexdigest() for path, data in hydrated_tree.items()},
            {path: hashlib.sha256(data).hexdigest() for path, data in live_tree.items()},
        )
        self._assert_prepared_seed(hydrated_sandbox, 1)
        self._assert_prepared_seed(live_sandbox, 1)

    def test_existing_live_area_bytes_are_never_rewritten(self) -> None:
        project, _canonical = self._make_project("existing-live", live_bytes=(
            b" \n" + _json_bytes(_area_payload()) + b"  \n"
        ))
        source_areas = project / "modules" / "Capture_Arena" / "areas"
        supplied_live = (source_areas / "CTR001.json").read_bytes()
        supplied_backup = (source_areas / "CTR001_BU.json").read_bytes()
        sandbox = self._prepare(project, 1)
        self.assertEqual(
            (sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001.json").read_bytes(),
            supplied_live,
        )
        self.assertEqual(
            (sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001_BU.json").read_bytes(),
            supplied_backup,
        )
        self.assertEqual((source_areas / "CTR001.json").read_bytes(), supplied_live)
        self.assertEqual((source_areas / "CTR001_BU.json").read_bytes(), supplied_backup)

    def test_missing_or_multiple_backups_fail_before_seeding_writes(self) -> None:
        for name, backup_names, expected_count in (
            ("no-backup", (), 0),
            ("two-backups", ("CTR001_BU.json", "CTR002_BU.json"), 2),
        ):
            with self.subTest(name=name):
                project, _canonical = self._make_project(name, backup_names=backup_names)
                source_areas = project / "modules" / "Capture_Arena" / "areas"
                source_before = _tree_bytes(source_areas)
                sandbox = project / "tmp" / "combat_capture"
                logger = logging.getLogger("utils.file_operations")
                previous_level = logger.level
                try:
                    with self._patched_project(project), contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "expected exactly one \\*_BU\\.json backup, found %d" % expected_count,
                        ):
                            seeder.prepare(1)
                finally:
                    logger.setLevel(previous_level)
                self.assertFalse((sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001.json").exists())
                self.assertFalse((sandbox / "party_tracker.json").exists())
                self.assertEqual((sandbox / "config.py").read_bytes(), (project / "config.py").read_bytes())
                self.assertEqual(
                    (sandbox / "model_config.py").read_bytes(),
                    (project / "model_config.py").read_bytes(),
                )
                self.assertEqual(_tree_bytes(source_areas), source_before)

    def test_g5a_prepare_transform_reads_both_hydrated_area_files(self) -> None:
        project, _canonical_bytes = self._make_project("g5a-clean")
        source_areas = project / "modules" / "Capture_Arena" / "areas"
        source_before = _tree_bytes(source_areas)
        sandbox = self._prepare(
            project, 1, scenario_id="g5a-ally-p1", gate="g5a"
        )
        areas = sandbox / "modules" / "Capture_Arena" / "areas"
        self.assertTrue((areas / "CTR001.json").is_file())
        for filename in ("CTR001_BU.json", "CTR001.json"):
            payload = json.loads((areas / filename).read_bytes())
            training_pit = next(
                row for row in payload["locations"] if row["locationId"] == "CA02"
            )
            self.assertIn(
                seeder.capture_fixtures.G5A_COVER_FEATURE_ID,
                [feature["featureId"] for feature in training_pit["tacticalFeatures"]],
            )
        self._assert_prepared_seed(sandbox, 1)
        self.assertEqual(_tree_bytes(source_areas), source_before)

    def test_non_sandbox_and_symlink_paths_are_refused(self) -> None:
        project, _canonical = self._make_project("unsafe-path")
        source_areas = project / "modules" / "Capture_Arena" / "areas"
        source_before = _tree_bytes(source_areas)
        with patch.object(seeder, "PROJECT_ROOT", project), patch.object(
            seeder, "SANDBOX_ROOT", project / "modules" / "Capture_Arena"
        ):
            with self.assertRaisesRegex(RuntimeError, "sandbox root"):
                seeder._hydrate_capture_arena_area_file()

        sandbox = project / "tmp" / "combat_capture"
        sandbox.mkdir(parents=True)
        outside_areas = self.scratch_root / "outside-areas"
        outside_areas.mkdir()
        (outside_areas / "CTR001_BU.json").write_bytes(_json_bytes(_area_payload()))
        (sandbox / "modules").symlink_to(self.scratch_root / "outside-modules", target_is_directory=True)
        outside_modules = self.scratch_root / "outside-modules"
        outside_modules.mkdir()
        outside_module = outside_modules / "Capture_Arena"
        outside_module.mkdir()
        (outside_module / "areas").symlink_to(outside_areas, target_is_directory=True)
        with patch.object(seeder, "PROJECT_ROOT", project), patch.object(
            seeder, "SANDBOX_ROOT", sandbox
        ):
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                seeder._hydrate_capture_arena_area_file()
        self.assertFalse((outside_areas / "CTR001.json").exists())
        self.assertEqual(_tree_bytes(source_areas), source_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
