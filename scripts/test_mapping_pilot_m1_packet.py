# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for M1 owner packets."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import pathlib
import shutil
import sys
import unittest
import uuid
from collections import defaultdict
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot import m1_packet
from scripts.mapping_pilot.fixtures import FIXTURE_FILES, load_verified_fixtures
from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT


class M1PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, cls.frozen_hashes = load_verified_fixtures()

    def _scratch_root(self) -> pathlib.Path:
        root = pathlib.Path("tmp/mapping_pilot_m1_packet_%s" % uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    @staticmethod
    def _read_manifest(run_dir: pathlib.Path) -> dict:
        return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    def test_fixture_views_are_complete_stable_and_match_combat_placements(self) -> None:
        scratch = self._scratch_root()
        output_root = scratch / "m1"
        first_relative = m1_packet.create_m1_packet(
            "fixture-first", output_root=output_root
        )
        second_relative = m1_packet.create_m1_packet(
            "fixture-second", output_root=output_root
        )
        first_dir = pathlib.Path.cwd() / first_relative
        second_dir = pathlib.Path.cwd() / second_relative
        first = self._read_manifest(first_dir)
        second = self._read_manifest(second_dir)

        fixture_rows = [row for row in first["sketches"] if row["source"] == "fixture"]
        self.assertEqual(len(fixture_rows), 5)
        viewpoints: dict[str, set[str]] = defaultdict(set)
        for row in fixture_rows:
            viewpoints[row["identity"]].add(row["viewpoint"])
        self.assertEqual(
            dict(viewpoints),
            {
                "interior_tavern": {"start"},
                "landscape_village": {"start"},
                "transition_tower_approach": {"start"},
                "combat_stage_tavern_zones": {"P1", "P4"},
            },
        )
        self.assertEqual(
            [row["sketch_id"] for row in fixture_rows],
            [row["sketch_id"] for row in second["sketches"]],
        )
        for first_row, second_row in zip(fixture_rows, second["sketches"]):
            self.assertEqual(
                (first_dir / first_row["file"]).read_bytes(),
                (second_dir / second_row["file"]).read_bytes(),
            )

        combat_rows = {
            row["viewpoint"]: row
            for row in fixture_rows
            if row["identity"] == "combat_stage_tavern_zones"
        }
        self.assertEqual(set(combat_rows), {"P1", "P4"})
        p1_text = (first_dir / combat_rows["P1"]["file"]).read_text(encoding="ascii")
        p4_text = (first_dir / combat_rows["P4"]["file"]).read_text(encoding="ascii")
        self.assertNotEqual(p1_text, p4_text)

        combat_fixture = self.fixtures["combat_stage_tavern_zones"]
        zones = {row["zone_id"]: row for row in combat_fixture["zones"]}
        for viewpoint, party_key in (("P1", "party_1"), ("P4", "party_4")):
            row = combat_rows[viewpoint]
            self.assertEqual(row["viewpoint_context"]["active_actor_id"], "Acheron")
            expected_pcs = combat_fixture["initial_placement_rules"][party_key]["pcs"]
            self.assertEqual(
                row["viewpoint_context"]["party_members"], list(expected_pcs)
            )
            text = (first_dir / row["file"]).read_text(encoding="ascii")
            for actor_id, zone_id in expected_pcs.items():
                self._assert_actor_at_position(text, actor_id, zones[zone_id]["position"])
            self.assertIn(
                "MPV2_LOC_VILLAGE_GREEN",
                row["viewpoint_context"]["party_known_ids"],
            )
            self.assertIn(
                "MPV2_F_TAVERN_LONG_TABLE",
                row["viewpoint_context"]["perceived_ids"],
            )
        for actor_id in ("Merisiel", "Kira", "Vitreol"):
            self.assertNotIn(actor_id, p1_text)
            self.assertIn(actor_id, p4_text)

        expected_fixture_hashes = {
            path: self.frozen_hashes[path] for path in FIXTURE_FILES.values()
        }
        observed_fixture_hashes = {
            row["fixture_path"]: row["fixture_sha256"] for row in first["fixtures"]
        }
        self.assertEqual(observed_fixture_hashes, expected_fixture_hashes)

    def test_fixture_hidden_facts_and_unperceived_exit_do_not_reach_sketch(self) -> None:
        scratch = self._scratch_root()
        hidden_facts: dict[str, list[str]] = {}
        relative = m1_packet.create_m1_packet("frozen-hidden", output_root=scratch / "m1")
        run_dir = pathlib.Path.cwd() / relative
        manifest = self._read_manifest(run_dir)
        for fixture_id, fixture in self.fixtures.items():
            hidden = list(fixture.get("hidden_facts", []))
            for location in fixture.get("locations", []):
                if isinstance(location, dict):
                    hidden.extend(location.get("hidden_facts", []))
            hidden_facts[fixture_id] = hidden
        for row in manifest["sketches"]:
            if row["source"] != "fixture":
                continue
            sketch = (run_dir / row["file"]).read_text(encoding="ascii")
            for fact in hidden_facts[row["identity"]]:
                self.assertNotIn(fact, sketch)
            fixture = self.fixtures[row["identity"]]
            for location in fixture.get("locations", []):
                if not isinstance(location, dict):
                    continue
                for exit_row in location.get("exits", []):
                    if exit_row.get("perceivable") is False:
                        self.assertNotIn(exit_row["exit_id"], sketch)

        mutated = copy.deepcopy(self.fixtures)
        interior = mutated["interior_tavern"]["locations"][0]
        interior["features"].append(
            {
                "feature_id": "SECRET_UNPERCEIVED_FEATURE",
                "name": "Unseen alcove sentinel",
                "position": "north",
                "perceivable": False,
            }
        )
        interior["exits"].append(
            {
                "exit_id": "SECRET_UNPERCEIVED_EXIT",
                "feature_id": "MPV2_F_TAVERN_FRONT_DOOR",
                "side": "north",
                "state": "open",
                "known_destination_location_id": None,
                "destination_knowledge": "unknown",
                "perceivable": False,
            }
        )
        interior["hidden_facts"].append("SECRET_HIDDEN_FACT_SENTINEL")
        with patch.object(
            m1_packet,
            "load_verified_fixtures",
            return_value=(mutated, self.frozen_hashes),
        ):
            mutated_relative = m1_packet.create_m1_packet(
                "mutated-hidden", output_root=scratch / "mutated"
            )
        mutated_dir = pathlib.Path.cwd() / mutated_relative
        mutated_manifest = self._read_manifest(mutated_dir)
        interior_row = next(
            row
            for row in mutated_manifest["sketches"]
            if row["identity"] == "interior_tavern"
        )
        sketch = (mutated_dir / interior_row["file"]).read_text(encoding="ascii")
        self.assertNotIn("SECRET_HIDDEN_FACT_SENTINEL", sketch)
        self.assertNotIn("SECRET_UNPERCEIVED_FEATURE", sketch)
        self.assertNotIn("Unseen alcove sentinel", sketch)
        self.assertNotIn("SECRET_UNPERCEIVED_EXIT", sketch)

    def test_only_validated_d1_layout_is_rendered_and_other_attempts_are_explained(self) -> None:
        scratch = self._scratch_root()
        d1_root = scratch / "d1"
        d1_run_id = "fake-d1"
        d1_dir = d1_root / d1_run_id
        d1_dir.mkdir(parents=True)
        valid_layout = {
            "layout_type": "locations",
            "fixture_id": "Keep_of_Doom:LOC001",
            "locations": [
                {
                    "location_id": "LOC001",
                    "name": "D1 room",
                    "orientation": {"position_semantics": "schematic"},
                    "features": [
                        {
                            "feature_id": "D1_FEATURE",
                            "name": "D1 anchor",
                            "position": "center",
                        }
                    ],
                    "exits": [],
                    "perceivable_facts": [],
                    "hidden_facts": ["SECRET_D1_HIDDEN_FACT"],
                }
            ],
            "authored_distances": [],
        }
        ledger = {
            "schema_version": 1,
            "attempts": [
                {
                    "attempt_number": 1,
                    "location_key": "Keep_of_Doom:LOC001",
                    "module_slug": "Keep_of_Doom",
                    "location_id": "LOC001",
                    "status": "validated",
                    "proposal": valid_layout,
                },
                {
                    "attempt_number": 2,
                    "location_key": "Keep_of_Doom:LOC002",
                    "module_slug": "Keep_of_Doom",
                    "location_id": "LOC002",
                    "status": "invalid_layout",
                    "proposal": None,
                },
                {
                    "attempt_number": 3,
                    "location_key": "The_Thornwood_Watch:LOC003",
                    "module_slug": "The_Thornwood_Watch",
                    "location_id": "LOC003",
                    "status": "client_error",
                    "proposal": None,
                },
            ],
        }
        ledger_path = d1_dir / "d1_attempt_ledger.json"
        ledger_path.write_text(
            json.dumps(ledger, ensure_ascii=True, sort_keys=True), encoding="ascii"
        )

        relative = m1_packet.create_m1_packet(
            "with-d1",
            d1_run_id=d1_run_id,
            output_root=scratch / "m1",
            d1_root=d1_root,
        )
        run_dir = pathlib.Path.cwd() / relative
        manifest = self._read_manifest(run_dir)
        d1_rows = [row for row in manifest["sketches"] if row["source"] == "d1"]
        self.assertEqual(len(d1_rows), 1)
        d1_sketch = (run_dir / d1_rows[0]["file"]).read_text(encoding="ascii")
        self.assertIn("D1 anchor", d1_sketch)
        self.assertNotIn("SECRET_D1_HIDDEN_FACT", d1_sketch)
        omitted = manifest["omitted_d1_layouts"]
        self.assertEqual(len(omitted), 2)
        self.assertEqual(
            {row["reason"] for row in omitted},
            {"status:invalid_layout", "status:client_error"},
        )
        self.assertEqual(
            {row["location_id"] for row in omitted}, {"LOC002", "LOC003"}
        )
        self.assertEqual(
            manifest["inputs"]["d1_ledger"]["sha256"],
            hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        )

    def test_ratings_are_blank_with_threshold_disclosure_and_all_hashes_match(self) -> None:
        scratch = self._scratch_root()
        relative = m1_packet.create_m1_packet("rating-sheet", output_root=scratch / "m1")
        run_dir = pathlib.Path.cwd() / relative
        manifest = self._read_manifest(run_dir)
        self.assertEqual(manifest["completion"], "complete")

        ratings_bytes = (run_dir / "ratings.csv").read_bytes()
        ratings = ratings_bytes.decode("ascii")
        self.assertIn("mean >= 3.5", ratings)
        self.assertIn("legibility and usefulness", ratings)
        self.assertIn("from 1 to 5", ratings)
        self.assertIn("sketch format is visible", ratings)
        self.assertIn("blinding is partial", ratings)
        lines = ratings.splitlines()
        data = list(csv.DictReader(io.StringIO("\n".join(lines[3:]) + "\n")))
        self.assertEqual(len(data), len(manifest["sketches"]))
        self.assertTrue(
            all(row["legibility_1_5"] == "" and row["usefulness_1_5"] == "" for row in data)
        )

        expected_hashes = {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in manifest["artifact_sha256"]
        }
        self.assertEqual(manifest["artifact_sha256"], expected_hashes)
        for row in manifest["sketches"]:
            self.assertEqual(
                row["sha256"],
                hashlib.sha256((run_dir / row["file"]).read_bytes()).hexdigest(),
            )

    def test_existing_run_id_is_refused_without_changing_original_bytes(self) -> None:
        scratch = self._scratch_root()
        output_root = scratch / "m1"
        relative = m1_packet.create_m1_packet("immutable-run", output_root=output_root)
        run_dir = pathlib.Path.cwd() / relative
        before = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.iterdir()
        }
        with self.assertRaises(FileExistsError):
            m1_packet.create_m1_packet("immutable-run", output_root=output_root)
        after = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.iterdir()
        }
        self.assertEqual(before, after)

    def test_manifest_failure_does_not_leave_a_complete_looking_packet(self) -> None:
        scratch = self._scratch_root()
        output_root = scratch / "m1"
        with patch("utils.file_operations.safe_write_json", return_value=False):
            with self.assertRaisesRegex(OSError, "no completion manifest"):
                m1_packet.create_m1_packet("incomplete-run", output_root=output_root)
        run_dir = pathlib.Path.cwd() / output_root / "incomplete-run"
        self.assertTrue((run_dir / "ratings.csv").is_file())
        self.assertFalse((run_dir / "manifest.json").exists())
        self.assertFalse((run_dir / "complete").exists())

    def _assert_actor_at_position(
        self, sketch: str, actor_id: str, position: str
    ) -> None:
        coordinates = {
            "center": (1, 1),
            "northeast": (0, 2),
            "south_center": (2, 1),
            "west_center": (1, 0),
        }
        self.assertIn(position, coordinates)
        row_index, column_index = coordinates[position]
        grid = sketch.splitlines()[1:4]
        self.assertEqual(len(grid), 3)
        cell = grid[row_index].split(" | ")[column_index]
        if actor_id not in cell:
            raise AssertionError(
                "%s was not rendered at %s; cell was %r" % (actor_id, position, cell)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
