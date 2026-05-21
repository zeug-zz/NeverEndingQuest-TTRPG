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
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_blueprint_seed_writer import (
    materialize_module_from_blueprint,
    STATUS_SEED_REFUSED,
    STATUS_SEED_PLANNED,
    STATUS_SEED_SUCCESS,
    STATUS_SEED_DEGRADED,
    STATUS_SEED_FAILED,
    NPC_SEED_VERSION,
    MONSTER_SEED_VERSION,
    SEED_SOURCE_REPORT_VERSION,
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


def _make_encounter_fixture(**overrides) -> Dict[str, Any]:
    """Sample blueprint with encounter plan for monster seed tests."""
    bp = _make_sample_blueprint(**overrides)
    bp["encounter_plan"] = [
        {
            "name": "Temple Guardians",
            "location": "Inner Sanctum",
            "monsters": ["Skeleton", "Zombie"],
        },
        {
            "name": "Vault Protectors",
            "location": "Treasure Vault",
            "creatures": [
                {"name": "Golem Guardian", "materialization_hint": "custom_needed"},
            ],
        },
    ]
    bp["coverage"]["encounters_in_blueprint"] = len(bp["encounter_plan"])
    return bp


def _make_location_monster_fixture(**overrides) -> Dict[str, Any]:
    """Sample blueprint with location monster refs for secondary monster seed tests."""
    bp = _make_sample_blueprint(
        location_roster=[
            {
                "atom_id": "loc_1",
                "display_name": "Entrance Hall",
                "aliases": [],
                "parent_area": "Ruined Temple",
                "criticality": "required",
                "source_refs": [{"excerpt": "Guarded by two stone gargoyles"}],
                "monsters": ["Stone Gargoyle"],
            },
            {
                "atom_id": "loc_2",
                "display_name": "Inner Sanctum",
                "aliases": [],
                "parent_area": "Ruined Temple",
                "criticality": "required",
                "source_refs": [],
                "monsters": [],
            },
            {
                "atom_id": "loc_3",
                "display_name": "Treasure Vault",
                "aliases": [],
                "parent_area": "Ruined Temple",
                "criticality": "optional",
                "source_refs": [],
            },
        ],
        encounter_plan=[],
        **overrides,
    )
    return bp


def _make_builder_shape_fixture(**overrides) -> Dict[str, Any]:
    """Sample blueprint using exact shapes from toolkit_builder_blueprint.py.

    Encounter_plan uses atom_id, monster_names, purpose, avoidable, social.
    Item_roster uses atom_id, display_name, required.
    """
    bp = _make_sample_blueprint(**overrides)
    bp["encounter_plan"] = [
        {
            "atom_id": "enc_guardians",
            "name": "Temple Guardians",
            "location": "Inner Sanctum",
            "purpose": "Cult guardians block the path to the inner shrine",
            "monster_names": ["Skeleton", "Zombie"],
            "avoidable": True,
            "social": False,
            "source_refs": [{"excerpt": "Guarded by skeletal remains"}],
        },
        {
            "atom_id": "enc_vault",
            "name": "Vault Protectors",
            "location": "Treasure Vault",
            "purpose": "Golem guardian of the vault",
            "monster_names": ["Golem Guardian"],
            "avoidable": False,
            "social": False,
            "source_refs": [],
        },
    ]
    bp["item_roster"] = [
        {
            "atom_id": "item_amulet",
            "display_name": "Amulet of the Deep",
            "location": "Treasure Vault",
            "required": True,
            "source_refs": [{"excerpt": "A glowing amulet on a pedestal"}],
        },
        {
            "atom_id": "item_scroll",
            "display_name": "Ancient Scroll",
            "location": "Inner Sanctum",
            "required": False,
            "source_refs": [],
        },
    ]
    bp["coverage"]["encounters_in_blueprint"] = len(bp["encounter_plan"])
    bp["coverage"]["items_in_blueprint"] = len(bp["item_roster"])
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


class TestNpcsSeedArtifact(unittest.TestCase):
    """Tests for npcs_seed.json emission."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_npcs_seed_emitted_with_names(self):
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)
        path = Path(self.target) / "npcs_seed.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], NPC_SEED_VERSION)
        npc_names = [n["name"] for n in data["npcs"]]
        self.assertIn("High Priest Malak", npc_names)
        self.assertIn("Guardian Golem", npc_names)
        self.assertIn("Wandering Merchant", npc_names)

    def test_npcs_seed_preserves_role_and_faction(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "npcs_seed.json").read_text(encoding="utf-8"))
        npcs = {n["name"]: n for n in data["npcs"]}
        self.assertEqual(npcs["High Priest Malak"]["role"], "villain")
        self.assertEqual(npcs["High Priest Malak"]["faction"], "Cult of the Deep")
        self.assertEqual(npcs["High Priest Malak"]["location_binding"], "Inner Sanctum")

    def test_npcs_seed_preserves_aliases_and_criticality(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "npcs_seed.json").read_text(encoding="utf-8"))
        npcs = {n["name"]: n for n in data["npcs"]}
        self.assertEqual(npcs["High Priest Malak"]["aliases"], ["Malak"])
        self.assertEqual(npcs["High Priest Malak"]["criticality"], "required")
        self.assertEqual(npcs["Wandering Merchant"]["criticality"], "optional")

    def test_npcs_seed_has_module_title_and_source_hash(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "npcs_seed.json").read_text(encoding="utf-8"))
        self.assertEqual(data["module_title"], "Test Module")
        self.assertEqual(data["source_hash"], "abc123")
        self.assertEqual(data["source"], "builder_blueprint.v2")

    def test_npcs_seed_in_dry_run_planned_files(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            planned_paths = [p["path"] for p in result["planned_files"]]
            self.assertTrue(any("npcs_seed.json" in p for p in planned_paths))

    def test_filtered_npc_roster_excludes_rejected_candidate(self):
        """When an NPC is excluded from npc_roster by triage, seed artifacts must not include it."""
        bp = _make_sample_blueprint()
        bp["npc_roster"] = [
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
            # Guardian Golem is excluded (simulating triage rejection)
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
        ]
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)
        path = Path(self.target) / "npcs_seed.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        npc_names = [n["name"] for n in data["npcs"]]
        self.assertIn("High Priest Malak", npc_names)
        self.assertIn("Wandering Merchant", npc_names)
        self.assertNotIn("Guardian Golem", npc_names,
                         "Rejected/excluded NPC must not appear in npcs_seed.json")


class TestMonstersSeedArtifact(unittest.TestCase):
    """Tests for monsters_seed.json emission."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_monsters_seed_emitted(self):
        bp = _make_encounter_fixture()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)
        path = Path(self.target) / "monsters_seed.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], MONSTER_SEED_VERSION)

    def test_monsters_seed_has_encounter_creatures(self):
        bp = _make_encounter_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "monsters_seed.json").read_text(encoding="utf-8"))
        names = [m["name"] for m in data["monsters"]]
        self.assertIn("Skeleton", names)
        self.assertIn("Zombie", names)

    def test_monsters_seed_deduplicates_by_name(self):
        bp = _make_encounter_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "monsters_seed.json").read_text(encoding="utf-8"))
        names = [m["name"] for m in data["monsters"]]
        self.assertEqual(len(names), len(set(names)),
                         "Monster names should be deduplicated")

    def test_monsters_seed_no_stat_files(self):
        bp = _make_encounter_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        monster_dirs = list((Path(self.target) / "monsters").glob("*.json"))
        self.assertFalse(monster_dirs, "Monster stat files should not be created by seed writer")

    def test_monsters_from_location_roster(self):
        bp = _make_location_monster_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "monsters_seed.json").read_text(encoding="utf-8"))
        names = [m["name"] for m in data["monsters"]]
        self.assertIn("Stone Gargoyle", names)
        self.assertEqual(data["module_title"], "Test Module")

    def test_monsters_seed_in_dry_run_planned_files(self):
        bp = _make_encounter_fixture()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            planned_paths = [p["path"] for p in result["planned_files"]]
            self.assertTrue(any("monsters_seed.json" in p for p in planned_paths))

    def test_monsters_seed_from_monster_names(self):
        bp = _make_builder_shape_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "monsters_seed.json").read_text(encoding="utf-8"))
        names = [m["name"] for m in data["monsters"]]
        self.assertIn("Skeleton", names,
                      "monster_names entries should populate monsters_seed")
        self.assertIn("Golem Guardian", names,
                      "monster_names entries should populate monsters_seed")
        self.assertEqual(data["module_title"], "Test Module")


class TestSeedSourceReport(unittest.TestCase):
    """Tests for seed_source_report.json emission."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_seed_source_report_emitted(self):
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_SUCCESS)
        path = Path(self.target) / "seed_source_report.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["report_version"], SEED_SOURCE_REPORT_VERSION)

    def test_report_has_module_title_and_source_hash(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        self.assertEqual(data["module_title"], "Test Module")
        self.assertEqual(data["source_hash"], "abc123")

    def test_report_has_locations_with_source_order(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        locs = data["locations"]
        self.assertEqual(len(locs), 3)
        self.assertEqual(locs[0]["source_order"], 0)
        self.assertEqual(locs[0]["display_name"], "Entrance Hall")
        self.assertEqual(locs[1]["source_order"], 1)
        self.assertEqual(locs[1]["display_name"], "Inner Sanctum")
        self.assertEqual(locs[2]["source_order"], 2)
        self.assertEqual(locs[2]["display_name"], "Treasure Vault")

    def test_report_has_npcs(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["npcs"]), 3)
        names = [n["display_name"] for n in data["npcs"]]
        self.assertIn("High Priest Malak", names)

    def test_filtered_npc_roster_excludes_rejected_in_report(self):
        """When npc_roster is filtered by triage, seed_source_report npcs must not include excluded NPCs."""
        bp = _make_sample_blueprint()
        bp["npc_roster"] = [bp["npc_roster"][0]]  # Only High Priest Malak
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        names = [n["display_name"] for n in data["npcs"]]
        self.assertIn("High Priest Malak", names)
        self.assertNotIn("Guardian Golem", names,
                         "Rejected/excluded NPC must not appear in seed_source_report npcs")
        self.assertNotIn("Wandering Merchant", names)

    def test_report_has_plot_beats(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["plot_beats"]), 2)

    def test_report_in_dry_run_planned_files(self):
        bp = _make_sample_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = materialize_module_from_blueprint(bp, tmpdir, dry_run=True)
            planned_paths = [p["path"] for p in result["planned_files"]]
            self.assertTrue(any("seed_source_report.json" in p for p in planned_paths))

    def test_numillian_source_order_preserved(self):
        bp = _make_numillian_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "module")
            materialize_module_from_blueprint(bp, target, overwrite=False, dry_run=False)
            data = json.loads((Path(target) / "seed_source_report.json").read_text(encoding="utf-8"))
            locs = data["locations"]
            self.assertEqual(len(locs), 13)
            expected_order = [
                "Outer Ward", "Market District", "Archive Antechamber",
                "Grand Repository", "Restricted Section", "Chamber of Edicts",
                "Observatory", "Trial of the Door", "Gatepact Vault",
                "Kobe's Workshop", "Hidden Archive", "Well of Echoes",
                "Final Gate",
            ]
            for i, name in enumerate(expected_order):
                self.assertEqual(locs[i]["display_name"], name,
                                 f"Source order broken at index {i}")


class TestSeedWriteFailure(unittest.TestCase):
    """Tests for required/optional write failure classification."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    @patch("utils.toolkit_blueprint_seed_writer.safe_write_json")
    def test_required_context_failure_returns_failed(self, mock_safe_write):
        mock_safe_write.side_effect = IOError("Test write failure")
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_FAILED)
        self.assertGreater(len(result.get("blockers", [])), 0,
                           "Required write failures must produce blockers")
        self.assertTrue(
            any("module_context.json" in str(b.get("message", ""))
                for b in result.get("blockers", [])),
            "Blockers must identify failed required artifact"
        )

    @patch("utils.toolkit_blueprint_seed_writer._safe_write_json")
    def test_npcs_seed_failure_classified(self, mock_write):
        def _side_effect(filepath, data, created, skipped):
            if "npcs_seed.json" in str(filepath):
                skipped.append({"path": str(filepath), "reason": "test failure"})
            else:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(str(filepath), "w") as f:
                    json.dump(data, f)
                created.append(str(filepath))

        mock_write.side_effect = _side_effect
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_FAILED)
        self.assertTrue(
            any("npcs_seed.json" in str(b.get("message", ""))
                for b in result.get("blockers", [])),
            "npcs_seed.json failure must produce a blocker identifying the failed artifact"
        )

    @patch("utils.toolkit_blueprint_seed_writer._safe_write_json")
    def test_required_context_BU_failure_blocks_success(self, mock_write):
        called = {"write_block": False}

        def _side_effect(filepath, data, created, skipped):
            if "module_context_BU.json" in str(filepath):
                called["write_block"] = True
                skipped.append({"path": str(filepath), "reason": "test failure"})
            else:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(str(filepath), "w") as f:
                    json.dump(data, f)
                created.append(str(filepath))

        mock_write.side_effect = _side_effect
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertTrue(called["write_block"])
        self.assertEqual(result["seed_status"], STATUS_SEED_FAILED)
        self.assertTrue(
            any("module_context_BU.json" in str(b.get("message", ""))
                for b in result.get("blockers", [])),
            "module_context_BU.json failure must produce a blocker"
        )

    @patch("utils.toolkit_blueprint_seed_writer._safe_write_json")
    def test_area_failure_not_success(self, mock_write):
        def _side_effect(filepath, data, created, skipped):
            if "areas/" in str(filepath) and "_BU.json" in str(filepath):
                skipped.append({"path": str(filepath), "reason": "test area write failure"})
            else:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(str(filepath), "w") as f:
                    json.dump(data, f)
                created.append(str(filepath))

        mock_write.side_effect = _side_effect
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertEqual(result["seed_status"], STATUS_SEED_FAILED,
                         "Area write failure must not return success")
        self.assertTrue(
            any("areas/" in str(b.get("message", ""))
                for b in result.get("blockers", [])),
            "Area failure must be in blockers"
        )

    @patch("utils.toolkit_blueprint_seed_writer._safe_write_json")
    def test_map_failure_not_success(self, mock_write):
        wrote_map = {"failed": False}

        def _side_effect(filepath, data, created, skipped):
            if "map_" in str(filepath):
                wrote_map["failed"] = True
                skipped.append({"path": str(filepath), "reason": "test map write failure"})
            else:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(str(filepath), "w") as f:
                    json.dump(data, f)
                created.append(str(filepath))

        mock_write.side_effect = _side_effect
        bp = _make_sample_blueprint()
        result = materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        self.assertTrue(wrote_map["failed"], "Map write should have been attempted")
        self.assertEqual(result["seed_status"], STATUS_SEED_FAILED,
                         "Map write failure must not return success")


class TestSeedSourceReportExtra(unittest.TestCase):
    """Additional seed_source_report.json tests for coverage and source_refs."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")

    def test_report_has_coverage_metadata(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        self.assertIn("coverage", data)
        cov = data["coverage"]
        self.assertIsInstance(cov, dict)
        self.assertIn("locations_count", cov)
        self.assertIn("npcs_count", cov)
        self.assertIn("plot_beats_count", cov)
        self.assertIn("encounters_in_blueprint", cov)

    def test_report_preserves_source_refs_for_non_location(self):
        bp = _make_sample_blueprint()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        # Plot beats should preserve criticality and source_refs
        for beat in data.get("plot_beats", []):
            self.assertIn("criticality", beat,
                          "Plot beat must preserve criticality field")
            self.assertIn("source_refs", beat,
                          "Plot beat must preserve source_refs field")
        # Encounters should preserve source_refs
        for enc in data.get("encounters", []):
            self.assertIn("source_refs", enc,
                          "Encounter must preserve source_refs field")

    def test_report_preserves_builder_encounter_shape(self):
        bp = _make_builder_shape_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        encs = data["encounters"]
        self.assertEqual(len(encs), 2)
        guardians = next(e for e in encs if e["name"] == "Temple Guardians")
        self.assertEqual(guardians["atom_id"], "enc_guardians")
        self.assertEqual(guardians["purpose"], "Cult guardians block the path to the inner shrine")
        self.assertEqual(guardians["monster_names"], ["Skeleton", "Zombie"])
        self.assertTrue(guardians["avoidable"])
        self.assertFalse(guardians["social"])
        self.assertGreater(len(guardians["source_refs"]), 0)
        vault = next(e for e in encs if e["name"] == "Vault Protectors")
        self.assertEqual(vault["monster_names"], ["Golem Guardian"])
        self.assertFalse(vault["avoidable"])

    def test_report_preserves_builder_item_shape(self):
        bp = _make_builder_shape_fixture()
        materialize_module_from_blueprint(bp, self.target, overwrite=False, dry_run=False)
        data = json.loads((Path(self.target) / "seed_source_report.json").read_text(encoding="utf-8"))
        items = data["items"]
        self.assertEqual(len(items), 2)
        amulet = next(i for i in items if i["display_name"] == "Amulet of the Deep")
        self.assertEqual(amulet["atom_id"], "item_amulet")
        self.assertTrue(amulet["required"])
        scroll = next(i for i in items if i["display_name"] == "Ancient Scroll")
        self.assertFalse(scroll["required"])


if __name__ == "__main__":
    unittest.main()
