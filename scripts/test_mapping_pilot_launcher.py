# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free parity and confinement tests for mapping-pilot state hashes."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import live_gate_preflight_sandbox as sandbox
from scripts.mapping_pilot import launcher, row_runner
from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.manifest import PROJECT_ROOT


class MappingPilotLauncherHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path("tmp") / ("mapping_pilot_launcher_" + uuid.uuid4().hex)
        (PROJECT_ROOT / self.scratch).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(PROJECT_ROOT / self.scratch, ignore_errors=True)

    def _make_sandbox(self, name: str) -> tuple[Path, Path, Path]:
        owner = PROJECT_ROOT / self.scratch / name
        root = owner / "tmp" / "combat_capture"
        (root / "characters").mkdir(parents=True)
        (root / "modules" / "Mapping_Pilot_Arena" / "areas").mkdir(parents=True)
        (root / "modules" / "encounters").mkdir(parents=True)
        (root / "encounters").mkdir(parents=True)
        (root / "party_tracker.json").write_text("{}", encoding="ascii")
        (root / "characters" / "acheron.json").write_text(
            '{"name":"Acheron"}', encoding="ascii"
        )
        (root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA001.json").write_text(
            '{"areaId":"MPA001"}', encoding="ascii"
        )
        actual_encounter = (
            root
            / "modules"
            / "encounters"
            / "encounter_mapping_pilot_combat.json"
        )
        actual_encounter.write_text('{"round":1}', encoding="ascii")
        (root / "encounters" / "legacy.json").write_text(
            '{"legacy":true}', encoding="ascii"
        )
        return owner, root, actual_encounter

    def test_hashes_match_and_mutated_canonical_encounter_invalidates_checkpoint(self) -> None:
        owner, root, encounter = self._make_sandbox("parity")
        with mock.patch.object(row_runner, "PROJECT_ROOT", owner):
            before = row_runner.hash_canonical_sandbox_state()
            self.assertIn(
                "modules/encounters/encounter_mapping_pilot_combat.json",
                before["files"],
            )
            self.assertIn("encounters/legacy.json", before["files"])
            self.assertEqual(
                before["sha256"], launcher._canonical_state_sha256(root)
            )

            encounter.write_text('{"round":2}', encoding="ascii")
            after = row_runner.hash_canonical_sandbox_state()
            self.assertNotEqual(before["sha256"], after["sha256"])
            self.assertNotEqual(
                before["sha256"], launcher._canonical_state_sha256(root)
            )
            with self.assertRaisesRegex(ValueError, "checkpoint hash does not match"):
                launcher._validate_resume_checkpoint(
                    root,
                    fixture_id="interior_tavern",
                    mapping={},
                    tracker={},
                    world={},
                    runtime_to_source={},
                    resume_checkpoint_sha256=before["sha256"],
                )

    def test_hashers_reject_symlinked_canonical_encounter_paths(self) -> None:
        for name, symlink_kind in (
            ("directory", "directory"),
            ("file", "file"),
        ):
            with self.subTest(symlink_kind=symlink_kind):
                owner, root, encounter = self._make_sandbox("symlink-" + name)
                external = PROJECT_ROOT / self.scratch / ("outside-" + name)
                if symlink_kind == "directory":
                    shutil.rmtree(root / "modules" / "encounters")
                    external.mkdir(parents=True)
                    (root / "modules" / "encounters").symlink_to(
                        external, target_is_directory=True
                    )
                else:
                    external.parent.mkdir(parents=True, exist_ok=True)
                    external.write_text('{"round":1}', encoding="ascii")
                    encounter.unlink()
                    encounter.symlink_to(external)

                with mock.patch.object(row_runner, "PROJECT_ROOT", owner):
                    with self.assertRaises(row_runner.RowExecutionError):
                        row_runner.hash_canonical_sandbox_state()
                with self.assertRaisesRegex(ValueError, "sandbox path is unsafe"):
                    launcher._canonical_state_sha256(root)


class MappingPilotFrozenOpenExitResumeTests(unittest.TestCase):
    """_validate_resume_checkpoint's frozen open-exit edge requirement.

    Ruling neq-w1-launcher-open-exit-20261117: a frozen seed location may have
    more than one open+known exit to the same destination (landscape_village's
    village green has two open exits, MPV2_EXIT_VILLAGE_DETOUR and
    MPV2_EXIT_VILLAGE_FORD, plus one blocked exit, MPV2_EXIT_VILLAGE_BRIDGE, all
    to MPV2_LOC_TOWER_APPROACH), so the requirement is at least one such exit,
    not exactly one.
    """

    def setUp(self) -> None:
        self.scratch = Path("tmp") / ("mapping_pilot_open_exit_" + uuid.uuid4().hex)
        (PROJECT_ROOT / self.scratch).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(PROJECT_ROOT / self.scratch, ignore_errors=True)

    def _build_moved_resume_state(
        self, name: str, fixture_id: str, destination_source_id: str
    ) -> tuple[Path, dict, dict, str]:
        """Seed a real mapping-pilot sandbox for fixture_id and move it to a
        destination source location, using the frozen fixtures and the same
        sandbox-preparation helpers the live preflight sandbox uses."""
        owner = PROJECT_ROOT / self.scratch / name
        root = owner / "tmp" / "combat_capture"
        root.parent.mkdir(parents=True)

        seed_plan, _profile = sandbox._load_profile_seed_plan(fixture_id, 1, None)
        module_payloads, expected_payloads = sandbox._load_profile_seed_inputs(
            PROJECT_ROOT
        )
        written = sandbox._write_fixture_module(
            root, seed_plan, module_payloads, expected_payloads
        )
        metadata = sandbox._write_seed_state(
            PROJECT_ROOT, root, seed_plan, written["module_payloads"], written["mapping"]
        )

        runtime_ids = written["module_payloads"]["location_id_map.json"][
            "runtime_location_ids"
        ]
        destination_runtime = runtime_ids[destination_source_id]
        destination_area, destination_area_payload, destination_location = (
            sandbox._runtime_location(written["module_payloads"], destination_runtime)
        )

        tracker_path = root / "party_tracker.json"
        moved_tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        moved_world = moved_tracker["worldConditions"]
        moved_world["currentLocationId"] = destination_runtime
        moved_world["currentLocation"] = destination_location.get("name")
        moved_world["currentAreaId"] = destination_area
        moved_world["currentArea"] = destination_area_payload.get("areaName")
        tracker_path.write_text(
            json.dumps(moved_tracker, sort_keys=True), encoding="ascii"
        )

        runtime_to_source = {
            runtime_id: source_id for source_id, runtime_id in runtime_ids.items()
        }

        checkpoint_sha256 = launcher._canonical_state_sha256(root)
        return root, metadata["mapping"], moved_tracker, checkpoint_sha256, runtime_to_source

    def test_two_open_known_exits_to_destination_are_accepted(self) -> None:
        root, mapping, tracker, checkpoint_sha256, runtime_to_source = (
            self._build_moved_resume_state(
                "two-open", "landscape_village", "MPV2_LOC_TOWER_APPROACH"
            )
        )
        launcher._validate_resume_checkpoint(
            root,
            fixture_id="landscape_village",
            mapping=mapping,
            tracker=tracker,
            world=tracker["worldConditions"],
            runtime_to_source=runtime_to_source,
            resume_checkpoint_sha256=checkpoint_sha256,
        )

    def test_single_open_known_exit_to_destination_is_still_accepted(self) -> None:
        root, mapping, tracker, checkpoint_sha256, runtime_to_source = (
            self._build_moved_resume_state(
                "single-open", "interior_tavern", "MPV2_LOC_VILLAGE_GREEN"
            )
        )
        launcher._validate_resume_checkpoint(
            root,
            fixture_id="interior_tavern",
            mapping=mapping,
            tracker=tracker,
            world=tracker["worldConditions"],
            runtime_to_source=runtime_to_source,
            resume_checkpoint_sha256=checkpoint_sha256,
        )

    def test_no_exit_to_destination_is_rejected(self) -> None:
        root, mapping, tracker, checkpoint_sha256, runtime_to_source = (
            self._build_moved_resume_state(
                "no-exit", "interior_tavern", "MPV2_LOC_TOWER_APPROACH"
            )
        )
        with self.assertRaisesRegex(
            ValueError, "mapping-pilot resume location is not a frozen open exit"
        ):
            launcher._validate_resume_checkpoint(
                root,
                fixture_id="interior_tavern",
                mapping=mapping,
                tracker=tracker,
                world=tracker["worldConditions"],
                runtime_to_source=runtime_to_source,
                resume_checkpoint_sha256=checkpoint_sha256,
            )

    def test_only_blocked_exits_to_destination_are_rejected(self) -> None:
        root, mapping, tracker, checkpoint_sha256, runtime_to_source = (
            self._build_moved_resume_state(
                "all-blocked", "landscape_village", "MPV2_LOC_TOWER_APPROACH"
            )
        )
        real_fixtures, real_hashes = load_verified_fixtures()
        blocked_fixtures = copy.deepcopy(real_fixtures)
        village_location = next(
            location
            for location in blocked_fixtures["landscape_village"]["locations"]
            if location.get("location_id") == "MPV2_LOC_VILLAGE_GREEN"
        )
        for exit_row in village_location.get("exits", []):
            if exit_row.get("known_destination_location_id") == "MPV2_LOC_TOWER_APPROACH":
                exit_row["state"] = "blocked"

        with mock.patch.object(
            launcher,
            "load_verified_fixtures",
            return_value=(blocked_fixtures, real_hashes),
        ):
            with self.assertRaisesRegex(
                ValueError, "mapping-pilot resume location is not a frozen open exit"
            ):
                launcher._validate_resume_checkpoint(
                    root,
                    fixture_id="landscape_village",
                    mapping=mapping,
                    tracker=tracker,
                    world=tracker["worldConditions"],
                    runtime_to_source=runtime_to_source,
                    resume_checkpoint_sha256=checkpoint_sha256,
                )


if __name__ == "__main__":
    unittest.main()
