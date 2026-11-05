# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for deterministic D1 selection and provenance."""

import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mapping_pilot.d1_selection import MODULE_QUOTAS, create_d1_selection
from scripts.mapping_pilot.cartographer import PROJECT_ROOT


class D1SelectionTests(unittest.TestCase):
    def _fixture(self, base: Path) -> Path:
        modules = PROJECT_ROOT / base / "modules"
        for slug, quota in MODULE_QUOTAS.items():
            areas = modules / slug / "areas"
            areas.mkdir(parents=True)
            if slug == "Keep_of_Doom":
                groups = [("dungeon", ["d1", "d2", "d3", "d4"]),
                          ("wilderness", ["w1", "w2", "w3", "w4"])]
            else:
                groups = [("wilderness", ["x%02d" % i for i in range(quota + 1)])]
            for index, (area_type, ids) in enumerate(groups):
                payload = {"areaType": area_type,
                           "locations": [{"locationId": item} for item in ids]}
                (areas / ("area%d_BU.json" % index)).write_text(
                    json.dumps(payload), encoding="utf-8")
        return modules

    def _assert_no_run(self, base: Path, run_id: str) -> None:
        run_dir = PROJECT_ROOT / base / "d1" / run_id
        self.assertFalse(run_dir.exists())
        self.assertFalse((run_dir / "selection.json").exists())

    def test_insufficient_quota_leaves_no_run_or_record(self) -> None:
        base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
        try:
            modules = self._fixture(base)
            area = modules / "Keep_of_Doom" / "areas" / "area0_BU.json"
            area.write_text(json.dumps({"areaType": "dungeon", "locations": [
                {"locationId": "only-one"}]}), encoding="utf-8")
            (modules / "Keep_of_Doom" / "areas" / "area1_BU.json").unlink()
            with self.assertRaisesRegex(ValueError, "insufficient eligible locations"):
                create_d1_selection("too-few", modules_dir=modules, output_root=base,
                                    commit_reader=lambda: "c" * 40)
            self._assert_no_run(base, "too-few")
        finally:
            shutil.rmtree(PROJECT_ROOT / base, ignore_errors=True)

    def test_missing_or_empty_area_type_leaves_no_run(self) -> None:
        for area_type in (None, ""):
            with self.subTest(area_type=area_type):
                base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
                try:
                    modules = self._fixture(base)
                    area_path = modules / "Keep_of_Doom" / "areas" / "area0_BU.json"
                    payload = json.loads(area_path.read_text(encoding="utf-8"))
                    if area_type is None:
                        del payload["areaType"]
                    else:
                        payload["areaType"] = area_type
                    area_path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "missing authored area type"):
                        create_d1_selection("bad-type", modules_dir=modules, output_root=base,
                                            commit_reader=lambda: "d" * 40)
                    self._assert_no_run(base, "bad-type")
                finally:
                    shutil.rmtree(PROJECT_ROOT / base, ignore_errors=True)

    def test_existing_run_preserves_selection_bytes(self) -> None:
        base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
        try:
            modules = self._fixture(base)
            create_d1_selection("same", modules_dir=modules, output_root=base,
                                commit_reader=lambda: "e" * 40)
            record = PROJECT_ROOT / base / "d1" / "same" / "selection.json"
            before = record.read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_d1_selection("same", modules_dir=modules, output_root=base,
                                    commit_reader=lambda: "f" * 40)
            self.assertEqual(record.read_bytes(), before)
        finally:
            shutil.rmtree(PROJECT_ROOT / base, ignore_errors=True)

    def test_fixture_round_robin_provenance_and_refusal(self) -> None:
        base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
        source_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for slug in MODULE_QUOTAS
            for path in sorted((PROJECT_ROOT / "modules" / slug / "areas").glob("*_BU.json"))
        }
        try:
            modules = self._fixture(base)
            one = create_d1_selection("one", modules_dir=modules, output_root=base,
                                      commit_reader=lambda: "b" * 40)
            rows = [row for row in one["locations"] if row["module_slug"] == "Keep_of_Doom"]
            self.assertEqual([(r["area_type"], r["location_id"]) for r in rows],
                             [("dungeon", "d1"), ("wilderness", "w1"),
                              ("dungeon", "d2"), ("wilderness", "w2"),
                              ("dungeon", "d3"), ("wilderness", "w3"), ("dungeon", "d4")])
            for row in one["locations"]:
                self.assertEqual(len(row["source_paths"]), 1)
                self.assertEqual(set(row["source_paths"]), set(row["source_sha256"]))
                self.assertEqual(len(next(iter(row["source_sha256"].values()))), 64)
            self.assertEqual(one["commit"], "b" * 40)
            # A duplicate authored ID across two area files fails before creating the run directory.
            duplicate_file = modules / "Keep_of_Doom" / "areas" / "area2_BU.json"
            duplicate_file.write_text('{"areaType":"dungeon","locations":[{"locationId":"d1"}]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate location ID"):
                create_d1_selection("duplicate", modules_dir=modules, output_root=base,
                                    commit_reader=lambda: "b" * 40)
            self.assertFalse((PROJECT_ROOT / base / "d1" / "duplicate").exists())
        finally:
            shutil.rmtree(PROJECT_ROOT / base, ignore_errors=True)

    def test_real_modules_are_read_only_and_selection_is_repeatable(self) -> None:
        missing = [slug for slug in MODULE_QUOTAS if not (PROJECT_ROOT / "modules" / slug).is_dir()]
        if missing:
            self.skipTest("approved module directory absent: %s" % ", ".join(missing))
        base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
        source_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for slug in MODULE_QUOTAS
            for path in sorted((PROJECT_ROOT / "modules" / slug / "areas").glob("*_BU.json"))
        }
        try:
            first = create_d1_selection("first", output_root=base, commit_reader=lambda: "a" * 40)
            second = create_d1_selection("second", output_root=base, commit_reader=lambda: "a" * 40)
            self.assertEqual(source_hashes, {
                path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_hashes
            })
            expected = {slug: quota for slug, quota in MODULE_QUOTAS.items()}
            counts = {slug: sum(row["module_slug"] == slug for row in first["locations"])
                      for slug in MODULE_QUOTAS}
            self.assertEqual(counts, expected)
            self.assertEqual([(r["module_slug"], r["location_id"]) for r in first["locations"]],
                             [(r["module_slug"], r["location_id"]) for r in second["locations"]])
            self.assertEqual(len(first["locations"]), 20)
            for row in first["locations"]:
                self.assertTrue(row["area_type"])
                self.assertEqual(len(row["source_paths"]), len(row["source_sha256"]))
                self.assertTrue(all(len(value) == 64 for value in row["source_sha256"].values()))
                self.assertTrue(all(not path.startswith("/") for path in row["source_paths"]))
            for slug in MODULE_QUOTAS:
                self.assertEqual(sum(first["selected_counts_by_area_type"][slug].values()), MODULE_QUOTAS[slug])
        finally:
            shutil.rmtree(PROJECT_ROOT / base, ignore_errors=True)

    def test_bad_token_refuses_without_output(self) -> None:
        base = Path("tmp") / ("mapping_pilot_d1_selection_" + uuid.uuid4().hex)
        with self.assertRaises(ValueError):
            create_d1_selection("../unsafe", output_root=base, commit_reader=lambda: "a" * 40)
        self.assertFalse((PROJECT_ROOT / base / "d1").exists())


if __name__ == "__main__":
    unittest.main()
