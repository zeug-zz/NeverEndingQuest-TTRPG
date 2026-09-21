# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Hostis-shaped provider-free tests for adaptation spatial convergence."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.spatial_repair import normalize_adaptation_spatial_topology


class AdaptationSpatialConvergenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir="tmp", prefix="hostis_spatial_")
        self.root = Path(self.temp_dir.name)
        (self.root / "areas").mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_fixture(self, connections, *, logical=None, malformed=False) -> None:
        logical = logical or []
        locations = [
            {"locationId": "K01", "name": "Marchwarden Barracks", "areaConnectivityId": logical, "connectivity": connections[0]},
            {"locationId": "K02", "name": "Wayfarers Guildhall", "areaConnectivityId": [], "connectivity": connections[1]},
        ]
        area = {"areaId": "WM002", "locations": locations}
        rooms = [
            {"id": "K01", "name": "Marchwarden Barracks", "coordinates": "X10Y10", "connections": connections[0]},
            {"id": "K02", "name": "Wayfarers Guildhall", "coordinates": "X11Y10", "connections": connections[1]},
        ]
        (self.root / "areas" / "WM002.json").write_text(json.dumps(area), encoding="utf-8")
        (self.root / "map_WM002.json").write_text("{bad" if malformed else json.dumps({"rooms": rooms}), encoding="utf-8")

    def test_rich_map_survives_and_valid_edges_are_preserved(self) -> None:
        self._write_fixture([["K02"], ["K01"]])
        report = normalize_adaptation_spatial_topology(str(self.root))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["changed_edges"], [])
        self.assertEqual(json.loads((self.root / "map_WM002.json").read_text())["rooms"][0]["connections"], ["K02"])

    def test_map_wm002_style_edge_reclassifies_with_authored_logical_evidence(self) -> None:
        self._write_fixture([["K02"], ["K01"]], logical=["K02"])
        map_path = self.root / "map_WM002.json"
        data = json.loads(map_path.read_text())
        data["rooms"][1]["coordinates"] = "X15Y10"
        map_path.write_text(json.dumps(data), encoding="utf-8")
        report = normalize_adaptation_spatial_topology(str(self.root))
        self.assertEqual(report["status"], "changed")
        self.assertEqual(report["changed_edges"][0]["classification"], "logical_area_connection")
        self.assertEqual(json.loads(map_path.read_text())["rooms"][0]["connections"], [])
        self.assertIn("K02", json.loads((self.root / "areas" / "WM002.json").read_text())["locations"][0]["areaConnectivityId"])

    def test_ambiguous_edge_blocks_and_preserves_authored_evidence(self) -> None:
        self._write_fixture([["K02"], ["K01"]])
        map_path = self.root / "map_WM002.json"
        data = json.loads(map_path.read_text())
        data["rooms"][1]["coordinates"] = "X15Y10"
        original = json.dumps(data, sort_keys=True)
        map_path.write_text(json.dumps(data), encoding="utf-8")
        report = normalize_adaptation_spatial_topology(str(self.root))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("ambiguous_non_cardinal_edge", {item["code"] for item in report["blockers"]})
        self.assertEqual(json.dumps(json.loads(map_path.read_text()), sort_keys=True), original)

    def test_malformed_topology_blocks_and_live_module_is_forbidden(self) -> None:
        self._write_fixture([[], []], malformed=True)
        report = normalize_adaptation_spatial_topology(str(self.root))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("malformed_topology_artifact", {item["code"] for item in report["blockers"]})
        self.assertEqual(normalize_adaptation_spatial_topology("modules/Hostis")["blockers"][0]["code"], "live_module_path_forbidden")


if __name__ == "__main__":
    unittest.main()
