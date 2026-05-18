"""Tests for utils/toolkit_blueprint_seed_writer.py.

All tests are provider-free and use temp directories.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_blueprint_seed_writer import (
    materialize_module_from_blueprint,
    STATUS_SEED_REFUSED,
    STATUS_SEED_PLANNED,
    STATUS_SEED_SUCCESS,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


def _make_sample_blueprint(**overrides) -> Dict[str, Any]:
    bp: Dict[str, Any] = {
        "blueprint_version": VALID_V2_VERSION,
        "blueprint_status": "ready",
        "source_hash": "abc123",
        "module": {
            "title": "Test Module",
            "summary": "A test module for unit tests",
            "tone_profile": {"markers": [], "unsupported_inventions": []},
        },
        "source_lock": {
            "canonical_names_locked": True,
            "required_atom_omission_blocks_build": True,
            "invented_major_entities_forbidden": True,
            "replacement_plotlines_forbidden": True,
            "puzzle_rule_rewrite_forbidden": True,
            "module_summary_is_derived_only": True,
        },
        "area_plan": [
            {
                "area_name": "Ruined Temple",
                "area_type": "dungeon",
                "source_locations": [
                    {"atom_id": "loc_1", "display_name": "Entrance Hall"},
                    {"atom_id": "loc_2", "display_name": "Inner Sanctum"},
                    {"atom_id": "loc_3", "display_name": "Treasure Vault"},
                ],
            },
        ],
        "location_roster": [
            {
                "atom_id": "loc_1",
                "display_name": "Entrance Hall",
                "aliases": ["Main Entry", "Gate Room"],
                "parent_area": "Ruined Temple",
                "criticality": "required",
                "source_refs": [{"excerpt": "A grand entrance with crumbling pillars"}],
            },
            {
                "atom_id": "loc_2",
                "display_name": "Inner Sanctum",
                "aliases": ["Sanctum"],
                "parent_area": "Ruined Temple",
                "criticality": "required",
                "source_refs": [],
            },
            {
                "atom_id": "loc_3",
                "display_name": "Treasure Vault",
                "aliases": ["Vault"],
                "parent_area": "Ruined Temple",
                "criticality": "optional",
                "source_refs": [],
            },
        ],
        "npc_roster": [
            {
                "atom_id": "npc_1",
                "display_name": "High Priest Malak",
                "aliases": ["Malak"],
                "role": "villain",
                "faction": "Cult of the Deep",
                "location_binding": "Inner Sanctum",
                "scene_presence": "present",
                "criticality": "required",
                "source_refs": [],
            },
            {
                "atom_id": "npc_2",
                "display_name": "Guardian Golem",
                "aliases": [],
                "role": "guardian",
                "faction": "",
                "location_binding": "Treasure Vault",
                "scene_presence": "present",
                "criticality": "required",
                "source_refs": [],
            },
            {
                "atom_id": "npc_3",
                "display_name": "Wandering Merchant",
                "aliases": ["Merchant"],
                "role": "vendor",
                "faction": "Merchants Guild",
                "location_binding": "",
                "scene_presence": "absent",
                "criticality": "optional",
                "source_refs": [],
            },
        ],
        "plot_graph": [
            {
                "beat_id": "PP001",
                "title": "Enter the Temple",
                "trigger": "Players approach the temple entrance",
                "dependencies": [],
                "required_location": "Entrance Hall",
                "required_npc": "",
                "outcome": "Players discover signs of cult activity",
                "failure_state": "",
                "beat_type": "mainline",
            },
            {
                "beat_id": "PP002",
                "title": "Confront the Priest",
                "trigger": "Players reach the Inner Sanctum",
                "dependencies": ["PP001"],
                "required_location": "Inner Sanctum",
                "required_npc": "High Priest Malak",
                "outcome": "Confront Malak and learn his plans",
                "failure_state": "Malak escapes through secret passage",
                "beat_type": "climax",
            },
        ],
        "puzzle_graph": [],
        "clue_graph": [],
        "encounter_plan": [],
        "item_roster": [],
        "tone_requirements": ["Tone marker: dark_fantasy"],
        "source_refs": [],
        "warnings": [],
        "coverage": {
            "locations_in_blueprint": 3,
            "npcs_in_blueprint": 3,
            "plot_beats_in_blueprint": 2,
            "puzzles_in_blueprint": 0,
            "clues_in_blueprint": 0,
            "encounters_in_blueprint": 0,
            "items_in_blueprint": 0,
        },
        "enrichment_allowlist": {},
        "artifact_refs": {},
        "blockers": [],
    }
    bp.update(overrides)
    return bp


def _make_numillian_blueprint(**overrides) -> Dict[str, Any]:
    """A Numillian-like blueprint with 13 location atoms."""
    locs = [
        "Outer Ward", "Market District", "Archive Antechamber", "Grand Repository",
        "Restricted Section", "Chamber of Edicts", "Observatory",
        "Trial of the Door", "Gatepact Vault", "Kobe's Workshop",
        "Hidden Archive", "Well of Echoes", "Final Gate",
    ]
    area_plan = [{"area_name": "Hidden City of Numillian", "area_type": "urban", "source_locations": []}]
    location_roster = []
    for i, name in enumerate(locs):
        aid = f"loc_{i+1}"
        area_plan[0]["source_locations"].append({"atom_id": aid, "display_name": name})
        location_roster.append({
            "atom_id": aid,
            "display_name": name,
            "aliases": [],
            "parent_area": "Hidden City of Numillian",
            "criticality": "required",
            "source_refs": [],
        })
    bp = _make_sample_blueprint(
        area_plan=area_plan,
        location_roster=location_roster,
        npc_roster=[
            {"atom_id": "npc_primus", "display_name": "Archivus Primus", "aliases": [],
             "role": "loremaster", "faction": "Numillian Archivists",
             "location_binding": "Grand Repository", "scene_presence": "present",
             "criticality": "required", "source_refs": []},
            {"atom_id": "npc_kobe", "display_name": "Kobe the Tinkerer", "aliases": [],
             "role": "artificer", "faction": "",
             "location_binding": "Kobe's Workshop", "scene_presence": "present",
             "criticality": "required", "source_refs": []},
        ],
        coverage={
            "locations_in_blueprint": len(locs),
            "npcs_in_blueprint": 2,
            "plot_beats_in_blueprint": 0,
            "puzzles_in_blueprint": 0,
            "clues_in_blueprint": 0,
            "encounters_in_blueprint": 0,
            "items_in_blueprint": 0,
        },
    )
    bp.update(overrides)
    return bp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBlueprintValidation(unittest.TestCase):
    """Test seed writer blueprint validation."""

    def test_refuses_non_v2_version(self):
        bp = _make_sample_blueprint(blueprint_version="source_faithful_builder_blueprint.v1")
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)
        self.assertFalse(result["validation"]["valid"])

    def test_refuses_blocked_status(self):
        bp = _make_sample_blueprint(blueprint_status="blocked")
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_refuses_failed_status(self):
        bp = _make_sample_blueprint(blueprint_status="failed")
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_refuses_blocked_by_fidelity_status(self):
        bp = _make_sample_blueprint(blueprint_status="blocked_by_fidelity")
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_refuses_generation_failed_status(self):
        bp = _make_sample_blueprint(blueprint_status="generation_failed")
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_refuses_missing_module_section(self):
        bp = _make_sample_blueprint()
        del bp["module"]
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_refuses_empty_location_roster(self):
        bp = _make_sample_blueprint(
            location_roster=[],
            area_plan=[],
            coverage={"locations_in_blueprint": 0, "npcs_in_blueprint": 3},
        )
        result = materialize_module_from_blueprint(bp, "/tmp/fake", dry_run=True)
        self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)


class TestDryRun(unittest.TestCase):
    """Test dry_run behavior."""

    def test_dry_run_returns_planned(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            self.assertEqual(result["seed_status"], STATUS_SEED_PLANNED)
            self.assertTrue("planned_files" in result)
            self.assertGreater(len(result["planned_files"]), 0)

    def test_dry_run_does_not_write_files(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            files_before = set(os.listdir(tmpdir))
            self.assertEqual(len(result["created_files"]), 0)
            self.assertEqual(files_before, set())

    def test_dry_run_coverage_has_counts(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            c = result["coverage"]
            self.assertGreater(c["areas"], 0)
            self.assertGreater(c["locations"], 0)
            self.assertGreater(c["npcs_in_roster"], 0)

    def test_dry_run_with_empty_npc_roster(self):
        bp = _make_sample_blueprint(
            npc_roster=[],
            coverage={"locations_in_blueprint": 3, "npcs_in_blueprint": 0},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            self.assertEqual(result["seed_status"], STATUS_SEED_PLANNED)
            self.assertEqual(result["coverage"]["npcs_in_roster"], 0)


class TestSuccessfulSeed(unittest.TestCase):
    """Test successful materialization."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def _materialize(self, **bp_overrides) -> Dict[str, Any]:
        bp = _make_sample_blueprint(**bp_overrides)
        return materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)

    def _root(self):
        return Path(self.target)

    def test_seed_status_is_success(self):
        result = self._materialize()
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)

    def test_creates_module_context(self):
        result = self._materialize()
        path = self._root() / "module_context.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["module_name"], "Test Module")
        self.assertTrue("areas" in data)
        self.assertTrue("npcs" in data)

    def test_creates_module_context_BU(self):
        result = self._materialize()
        path = self._root() / "module_context_BU.json"
        self.assertTrue(path.exists())

    def test_creates_module_plot(self):
        result = self._materialize()
        path = self._root() / "module_plot.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue("plotTitle" in data)
        self.assertTrue("plotPoints" in data)
        self.assertGreater(len(data["plotPoints"]), 0)

    def test_creates_module_plot_BU(self):
        result = self._materialize()
        path = self._root() / "module_plot_BU.json"
        self.assertTrue(path.exists())

    def test_creates_area_files(self):
        result = self._materialize()
        area_dir = self._root() / "areas"
        self.assertTrue(area_dir.exists())
        bu_files = list(area_dir.glob("*_BU.json"))
        live_files = list(area_dir.glob("*.json"))
        self.assertGreater(len(bu_files), 0)
        self.assertGreater(len(live_files), 0)

    def test_creates_map_file(self):
        result = self._materialize()
        map_files = list(self._root().glob("map_*.json"))
        self.assertGreater(len(map_files), 0)

    def test_source_name_preserved(self):
        result = self._materialize()
        ctx = json.loads((self._root() / "module_context.json").read_text(encoding="utf-8"))
        area = list(ctx["areas"].values())[0]
        self.assertEqual(area["name"], "Ruined Temple")

    def test_npc_names_preserved(self):
        result = self._materialize()
        ctx = json.loads((self._root() / "module_context.json").read_text(encoding="utf-8"))
        npc_keys = list(ctx["npcs"].keys())
        self.assertTrue(any("high_priest_malak" in k for k in npc_keys))
        self.assertTrue(any("guardian_golem" in k for k in npc_keys))
        self.assertTrue(any("wandering_merchant" in k for k in npc_keys))

    def test_npc_location_binding(self):
        result = self._materialize()
        ctx = json.loads((self._root() / "module_context.json").read_text(encoding="utf-8"))
        malak_key = [k for k in ctx["npcs"] if "high_priest_malak" in k][0]
        self.assertGreater(len(ctx["npcs"][malak_key]["appears_in"]), 0)

    def test_area_locations_populated(self):
        result = self._materialize()
        area_file = list((self._root() / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        locs = area_data.get("locations", [])
        names = [loc["name"] for loc in locs]
        self.assertIn("Entrance Hall", names)
        self.assertIn("Inner Sanctum", names)
        self.assertIn("Treasure Vault", names)

    def test_plot_data_has_title_and_objective(self):
        result = self._materialize()
        plot = json.loads((self._root() / "module_plot.json").read_text(encoding="utf-8"))
        self.assertEqual(plot["plotTitle"], "Test Module - Plot")
        self.assertEqual(plot["mainObjective"], "A test module for unit tests")

    def test_report_has_created_files(self):
        result = self._materialize()
        self.assertGreater(len(result["created_files"]), 0)
        self.assertEqual(len(result["skipped_files"]), 0)

    def test_report_coverage_counts(self):
        result = self._materialize()
        c = result["coverage"]
        self.assertEqual(c["areas"], 1)
        self.assertEqual(c["locations"], 3)
        self.assertEqual(c["npcs_in_roster"], 3)

    def test_warnings_for_unassigned_npcs(self):
        result = self._materialize()
        self.assertTrue(len(result["warnings"]) > 0)


class TestOverwriteBehavior(unittest.TestCase):
    """Test overwrite and directory existence behavior."""

    def test_refuses_existing_dir_without_overwrite(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "areas").mkdir(exist_ok=True)
            result = materialize_module_from_blueprint(bp, tmpdir, overwrite=False, dry_run=False)
            self.assertEqual(result["seed_status"], STATUS_SEED_REFUSED)

    def test_overwrites_existing_dir_when_allowed(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "some_old_file.txt").write_text("old data")
            result = materialize_module_from_blueprint(bp, tmpdir, overwrite=True, dry_run=False)
            self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)


class TestNumillianBlueprint(unittest.TestCase):
    """Test with a Numillian-like blueprint (13 locations)."""

    def test_13_locations_seeded(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            result = materialize_module_from_blueprint(bp, target, dry_run=True)
            self.assertEqual(result["seed_status"], STATUS_SEED_PLANNED)
            self.assertEqual(result["coverage"]["locations"], 13)
            self.assertEqual(result["coverage"]["npcs_in_roster"], 2)

    def test_13_locations_in_context(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            result = materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
            self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)
            ctx = json.loads((Path(target) / "module_context.json").read_text(encoding="utf-8"))
            area = list(ctx["areas"].values())[0]
            self.assertGreaterEqual(len(area["locations"]), 13)
            locs = ctx.get("locations", {})
            self.assertGreaterEqual(len(locs), 13)

    def test_13_locations_in_area_file(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
            area_file = list((Path(target) / "areas").glob("*_BU.json"))[0]
            area_data = json.loads(area_file.read_text(encoding="utf-8"))
            locs = area_data.get("locations", [])
            self.assertEqual(len(locs), 13)
            names = [loc["name"] for loc in locs]
            self.assertIn("Trial of the Door", names)
            self.assertIn("Gatepact Vault", names)
            self.assertIn("Kobe's Workshop", names)

    def test_source_order_preserved(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
            area_file = list((Path(target) / "areas").glob("*_BU.json"))[0]
            area_data = json.loads(area_file.read_text(encoding="utf-8"))
            names = [loc["name"] for loc in area_data["locations"]]
            expected = [
                "Outer Ward", "Market District", "Archive Antechamber",
                "Grand Repository", "Restricted Section", "Chamber of Edicts",
                "Observatory", "Trial of the Door", "Gatepact Vault",
                "Kobe's Workshop", "Hidden Archive", "Well of Echoes",
                "Final Gate",
            ]
            self.assertEqual(names, expected)

    def test_npc_binding_in_numillian(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
            ctx = json.loads((Path(target) / "module_context.json").read_text(encoding="utf-8"))
            primus_key = [k for k in ctx["npcs"] if "archivus" in k]
            self.assertGreater(len(primus_key), 0)
            appears = ctx["npcs"][primus_key[0]].get("appears_in", [])
            self.assertGreater(len(appears), 0)


class TestSchemaCompliance(unittest.TestCase):
    """Verify seeded files have required schema fields."""

    LOCA_REQUIRED = [
        "name", "type", "description", "dmInstructions", "locationId",
        "coordinates", "accessibility", "npcs", "monsters",
        "plotHooks", "lootTable", "dangerLevel", "connectivity",
        "areaConnectivity", "areaConnectivityId", "traps", "features",
        "dcChecks", "encounters", "adventureSummary", "doors",
    ]

    MODULE_CONTEXT_REQUIRED = ["module_name", "module_id", "areas", "npcs"]

    def _do(self, **bp_overrides):
        bp = _make_sample_blueprint(**bp_overrides)
        tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_obj.cleanup)
        target = os.path.join(tmpdir_obj.name, "module")
        materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
        return Path(target)

    def test_module_context_has_required_keys(self):
        root = self._do()
        ctx = json.loads((root / "module_context.json").read_text(encoding="utf-8"))
        for key in self.MODULE_CONTEXT_REQUIRED:
            self.assertIn(key, ctx, f"module_context missing required key: {key}")

    def test_area_locations_have_required_keys(self):
        root = self._do()
        area_file = list((root / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        for loc in area_data.get("locations", []):
            for key in self.LOCA_REQUIRED:
                self.assertIn(key, loc, f"Location '{loc.get('name', '?')}' missing required field: {key}")

    def test_plot_has_required_keys(self):
        root = self._do()
        plot = json.loads((root / "module_plot.json").read_text(encoding="utf-8"))
        self.assertIn("plotTitle", plot)
        self.assertIn("mainObjective", plot)
        self.assertIn("plotPoints", plot)
        if plot["plotPoints"]:
            pp = plot["plotPoints"][0]
            for key in ("id", "title", "description", "location", "nextPoints", "status", "plotImpact"):
                self.assertIn(key, pp)

    def test_area_has_map_required_keys(self):
        root = self._do()
        area_file = list((root / "areas").glob("*_BU.json"))[0]
        area_data = json.loads(area_file.read_text(encoding="utf-8"))
        map_data = area_data.get("map", {})
        for key in ("mapId", "mapName", "totalRooms", "rooms", "layout"):
            self.assertIn(key, map_data)

    def test_map_file_has_required_keys(self):
        root = self._do()
        map_file = list(root.glob("map_*.json"))[0]
        map_data = json.loads(map_file.read_text(encoding="utf-8"))
        for key in ("mapName", "mapId", "totalRooms", "rooms", "layout"):
            self.assertIn(key, map_data)


if __name__ == "__main__":
    unittest.main()
