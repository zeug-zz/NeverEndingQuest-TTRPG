#!/usr/bin/env python3
"""
Tests for utils.monster_reference_closure - Monster reference closure utility.

Verifies that the standalone module-level functions extracted from
ModuleGenerator produce correct closure reports and handle edge cases.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

# Ensure the repo root is on sys.path so utils imports resolve
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.monster_reference_closure import (
    normalize_monster_name,
    get_active_area_files,
    collect_referenced_monsters,
    collect_existing_monster_slugs,
    ensure_monster_reference_closure,
    _is_npc_like_name,
    _is_ambiguous_npc_like,
)

from web.extensions.toolkit_homebrew_packet_builder import (
    run_toolkit_homebrew_packet_build,
)

_VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


class TestNormalizeMonsterName(unittest.TestCase):
    """Tests for normalize_monster_name."""

    def test_basic_normalization(self):
        """'Goblin' -> 'goblin'"""
        self.assertEqual(normalize_monster_name("Goblin"), "goblin")

    def test_hyphenated_name(self):
        """'Will-o'-Wisp' -> 'will_o_wisp'"""
        self.assertEqual(normalize_monster_name("Will-o'-Wisp"), "will_o_wisp")

    def test_empty_string(self):
        """'' -> ''"""
        self.assertEqual(normalize_monster_name(""), "")

    def test_special_chars(self):
        """'Skeleton King!' -> 'skeleton_king'"""
        self.assertEqual(normalize_monster_name("Skeleton King!"), "skeleton_king")


class TestGetActiveAreaFiles(unittest.TestCase):
    """Tests for get_active_area_files."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.areas_dir = os.path.join(self.temp_dir.name, "areas")
        os.makedirs(self.areas_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_area_file(self, name: str, content: Dict[str, Any]):
        path = os.path.join(self.areas_dir, name)
        with open(path, 'w') as f:
            json.dump(content, f)

    def test_excludes_backup_files(self):
        """Only active .json files, not _BU, .bak, .tmp, etc."""
        self._write_area_file("A01.json", {"areaId": "A01"})
        self._write_area_file("A01_BU.json", {"areaId": "A01"})
        self._write_area_file("A01.bak", {})
        files = get_active_area_files(self.temp_dir.name)
        basenames = [os.path.basename(f) for f in files]
        self.assertIn("A01.json", basenames)
        self.assertNotIn("A01_BU.json", basenames)
        self.assertNotIn("A01.bak", basenames)

    def test_nonexistent_directory(self):
        """Empty module_dir without areas/ returns []."""
        empty_dir = os.path.join(self.temp_dir.name, "empty_module")
        os.makedirs(empty_dir, exist_ok=True)
        files = get_active_area_files(empty_dir)
        self.assertEqual(files, [])

    def test_only_json_files(self):
        """Only .json files returned, not .txt or other files."""
        self._write_area_file("A01.json", {"areaId": "A01"})
        readme_path = os.path.join(self.areas_dir, "readme.txt")
        with open(readme_path, 'w') as f:
            f.write("README")
        files = get_active_area_files(self.temp_dir.name)
        basenames = [os.path.basename(f) for f in files]
        self.assertIn("A01.json", basenames)
        self.assertNotIn("readme.txt", basenames)


class TestCollectReferencedMonsters(unittest.TestCase):
    """Tests for collect_referenced_monsters."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.areas_dir = os.path.join(self.temp_dir.name, "areas")
        os.makedirs(self.areas_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_area_file(self, name: str, content: Dict[str, Any]):
        path = os.path.join(self.areas_dir, name)
        with open(path, 'w') as f:
            json.dump(content, f)

    def test_collects_dict_monsters(self):
        """Dict monster references with name field are collected."""
        area_data = {
            "areaId": "A01",
            "areaName": "Test Area",
            "locations": [
                {
                    "locationId": "R01",
                    "locationName": "Entrance",
                    "monsters": [{"name": "Goblin"}, {"name": "Skeleton"}],
                }
            ],
        }
        self._write_area_file("A01.json", area_data)
        result = collect_referenced_monsters(self.temp_dir.name)
        self.assertIn("goblin", result)
        self.assertIn("skeleton", result)
        self.assertEqual(result["goblin"]["original_names"], ["Goblin"])
        self.assertEqual(len(result["goblin"]["sources"]), 1)
        self.assertEqual(result["goblin"]["sources"][0]["area_id"], "A01")

    def test_collects_string_monsters(self):
        """String monster references are collected."""
        area_data = {
            "areaId": "A01",
            "areaName": "Test Area",
            "locations": [
                {
                    "locationId": "R01",
                    "locationName": "Entrance",
                    "monsters": ["Goblin", "Skeleton"],
                }
            ],
        }
        self._write_area_file("A01.json", area_data)
        result = collect_referenced_monsters(self.temp_dir.name)
        self.assertIn("goblin", result)
        self.assertIn("skeleton", result)

    def test_empty_areas(self):
        """No monsters in areas returns empty dict."""
        area_data = {
            "areaId": "A01",
            "areaName": "Empty Area",
            "locations": [
                {"locationId": "R01", "locationName": "Empty Room", "monsters": []}
            ],
        }
        self._write_area_file("A01.json", area_data)
        result = collect_referenced_monsters(self.temp_dir.name)
        self.assertEqual(result, {})


class TestCollectExistingMonsterSlugs(unittest.TestCase):
    """Tests for collect_existing_monster_slugs."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.monsters_dir = os.path.join(self.temp_dir.name, "monsters")
        os.makedirs(self.monsters_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collects_existing_slugs(self):
        """Active .json files are collected, backup files excluded."""
        for name in ["goblin.json", "skeleton.json"]:
            path = os.path.join(self.monsters_dir, name)
            with open(path, 'w') as f:
                json.dump({"name": name.replace(".json", "")}, f)
        slugs = collect_existing_monster_slugs(self.temp_dir.name)
        self.assertIn("goblin", slugs)
        self.assertIn("skeleton", slugs)

    def test_excludes_backups(self):
        """Backup files (*_BU.json, .bak, etc.) are excluded."""
        for name in ["goblin.json", "goblin_BU.json"]:
            path = os.path.join(self.monsters_dir, name)
            with open(path, 'w') as f:
                json.dump({"name": "goblin"}, f)
        slugs = collect_existing_monster_slugs(self.temp_dir.name)
        self.assertIn("goblin", slugs)
        self.assertEqual(len(slugs), 1)


class TestAmbiguousNpcLikeDetection(unittest.TestCase):
    """Tests for NPC-like ambiguity detection."""

    def test_npc_title_pattern_flagged(self):
        """Title-prefixed names like 'Sir Reginald' are flagged."""
        self.assertTrue(_is_ambiguous_npc_like("Sir Reginald", "sir_reginald"))

    def test_creature_type_not_flagged(self):
        """Generic creature types like 'Goblin' are not flagged."""
        self.assertFalse(_is_ambiguous_npc_like("Goblin", "goblin"))

    def test_lady_title_flagged(self):
        """'Lady Mirabelle' is flagged."""
        self.assertTrue(_is_ambiguous_npc_like("Lady Mirabelle", "lady_mirabelle"))

    def test_bandit_not_flagged(self):
        """'Bandit' contains a creature-type keyword and is not flagged."""
        self.assertFalse(_is_ambiguous_npc_like("Bandit", "bandit"))

    def test_skeleton_not_flagged(self):
        """'Skeleton' contains a creature-type keyword and is not flagged."""
        self.assertFalse(_is_ambiguous_npc_like("Skeleton", "skeleton"))

    def test_dr_title_flagged(self):
        """'Dr Mortimer' is flagged."""
        self.assertTrue(_is_ambiguous_npc_like("Dr Mortimer", "dr_mortimer"))

    def test_sir_not_creature_keyword(self):
        """'Sir' alone without creature keywords is flagged."""
        self.assertTrue(_is_ambiguous_npc_like("Sir", "sir"))


class TestEnsureMonsterReferenceClosure(unittest.TestCase):
    """Tests for ensure_monster_reference_closure."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.areas_dir = os.path.join(self.temp_dir.name, "areas")
        self.monsters_dir = os.path.join(self.temp_dir.name, "monsters")
        os.makedirs(self.areas_dir, exist_ok=True)
        os.makedirs(self.monsters_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_json(self, path: str, data: Dict[str, Any]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)

    def test_no_references_returns_empty_report(self):
        """Module with no monster references: required=0, unresolved=0."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Empty",
                "locations": [
                    {"locationId": "R01", "locationName": "Room", "monsters": []}
                ],
            },
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        self.assertEqual(report["required"], 0)
        self.assertEqual(report["unresolved"], 0)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["existing_before"], 0)

    def test_all_references_exist(self):
        """All referenced monsters already have stat files -> no generation."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Tavern",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Main Hall",
                        "monsters": [{"name": "Goblin"}],
                    }
                ],
            },
        )
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        self.assertEqual(report["required"], 1)
        self.assertEqual(report["existing_before"], 1)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["unresolved"], 0)

    def test_missing_references_attempt_materialization(self):
        """Missing references produce report with materialization attempt."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Crypt",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Tomb",
                        "monsters": [{"name": "Skeleton"}, {"name": "Goblin"}],
                    }
                ],
            },
        )
        # Only goblin exists
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        self.assertEqual(report["required"], 2)
        self.assertEqual(report["existing_before"], 1)
        # Materialization may succeed or fail depending on environment
        self.assertIn("generation", report["details"])
        self.assertIn("generated", report["details"]["generation"])
        self.assertIn("failed", report["details"]["generation"])

    def test_closure_report_persisted(self):
        """monster_closure_report.json is written to module_dir."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Hall",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Corridor",
                        "monsters": [{"name": "Goblin"}],
                    }
                ],
            },
        )
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        report_path = os.path.join(self.temp_dir.name, "monster_closure_report.json")
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, 'r') as f:
            saved = json.load(f)
        # All required keys present
        for key in ("timestamp", "required", "existing_before", "generated", "unresolved", "details", "ambiguous_npc_like"):
            self.assertIn(key, saved)

    def test_ambiguous_npc_flagged_in_report(self):
        """NPC-like monster names appear in ambiguous_npc_like list."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Castle",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Throne Room",
                        "monsters": [{"name": "Sir Reginald"}, {"name": "Goblin"}],
                    }
                ],
            },
        )
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        self.assertIn("sir_reginald", report["ambiguous_npc_like"])
        self.assertNotIn("goblin", report["ambiguous_npc_like"])

    def test_no_ambiguous_when_not_npc_like(self):
        """Generic creature types not in ambiguous_npc_like list."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Dungeon",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Cell",
                        "monsters": [{"name": "Skeleton"}],
                    }
                ],
            },
        )
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)
        self.assertEqual(report["ambiguous_npc_like"], [])


# ---------------------------------------------------------------------------
# TestMonsterClosureReportPersistence
# ---------------------------------------------------------------------------


class TestMonsterClosureReportPersistence(unittest.TestCase):
    """Tests for monster_closure_report.json persistence and format.

    Verifies that the report written to disk by ensure_monster_reference_closure
    is compatible with downstream consumers (readiness gate, finisher, reports)
    and that the build result carries the report path.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.areas_dir = os.path.join(self.temp_dir.name, "areas")
        self.monsters_dir = os.path.join(self.temp_dir.name, "monsters")
        os.makedirs(self.areas_dir, exist_ok=True)
        os.makedirs(self.monsters_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_json(self, path: str, data: Dict[str, Any]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)

    def test_report_persisted_to_module_dir(self):
        """After closure on a module with references, assert monster_closure_report.json
        exists in module dir and is valid JSON with all required fields."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Crypt",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Tomb",
                        "monsters": [{"name": "Goblin"}, {"name": "Skeleton"}],
                    }
                ],
            },
        )
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        ensure_monster_reference_closure("test_module", self.temp_dir.name)

        report_path = os.path.join(self.temp_dir.name, "monster_closure_report.json")
        self.assertTrue(os.path.exists(report_path))

        with open(report_path, 'r') as f:
            saved = json.load(f)

        required_fields = [
            "timestamp", "required", "existing_before", "generated",
            "unresolved", "details", "ambiguous_npc_like",
        ]
        for field in required_fields:
            self.assertIn(field, saved, f"Field '{field}' missing from persisted report")
        self.assertIsInstance(saved["timestamp"], str)
        self.assertIsInstance(saved["required"], int)
        self.assertIsInstance(saved["existing_before"], int)
        self.assertIsInstance(saved["generated"], int)
        self.assertIsInstance(saved["unresolved"], int)
        self.assertIsInstance(saved["details"], dict)
        self.assertIsInstance(saved["ambiguous_npc_like"], list)

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    def test_report_path_in_build_result(
        self,
        mock_is_required,
        mock_seed,
        mock_closure,
    ):
        """After the packet builder runs monster closure, build_result
        carries the report_path pointing to module_dir/monster_closure_report.json."""
        # Use a fresh workspace with v2 blueprint artifacts so the seed
        # writer path is taken and ModuleBuilder is never invoked.
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        ws = Path(self.tmpdir_obj.name) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)

        defaults = {
            "normalized_packet.json": {
                "packet_version": "packet.v1",
                "name": "test-pipeline",
                "title": "Report Path Test",
                "description": "Test report path in build result",
                "source_hash": "abc123",
                "source_rights": "user_authored",
                "normalization_state": "normalized",
            },
            "ui_review_snapshot.json": {
                "decision": "approve",
                "recorded_at": "2026-01-01T00:00:00Z",
                "job_id": "test-job-rp",
                "packet_identity": {"source_hash": "abc123"},
            },
            "builder_blueprint.json": {},
            "builder_blueprint_report.json": {},
            "builder_narrative.txt": "Test narrative",
        }
        for filename, content in defaults.items():
            path = ws / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content) if isinstance(content, dict) else content,
                encoding="utf-8",
            )

        # Build v2 blueprint artifacts so handoff goes to the seed
        # writer path (which is fully mocked) instead of ModuleBuilder.
        bp = {
            "blueprint_version": _VALID_V2_VERSION,
            "blueprint_status": "ready",
            "module": {"title": "Report Path Test", "summary": "A test"},
            "source_lock": {"canonical_names_locked": True},
            "area_plan": [],
            "location_roster": [],
            "npc_roster": [],
            "plot_graph": [],
            "puzzle_graph": [],
            "clue_graph": [],
            "encounter_plan": [],
            "item_roster": [],
            "tone_requirements": [],
            "source_refs": [],
            "warnings": [],
            "coverage": {},
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "blockers": [],
        }
        (ws / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (ws / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")

        mock_closure.return_value = {
            "required": 2,
            "existing_before": 1,
            "generated": 1,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = {"seed_status": "success", "coverage": {}, "warnings": []}
        mock_is_required.return_value = False

        result = run_toolkit_homebrew_packet_build(
            ws,
            "test-report-path",
            overwrite_confirmed=True,
        )

        self.assertIn("monster_closure", result)
        self.assertIn("report_path", result["monster_closure"])
        self.assertTrue(
            result["monster_closure"]["report_path"].endswith("monster_closure_report.json"),
            f"report_path does not end with monster_closure_report.json: "
            f"{result['monster_closure']['report_path']}"
        )

    def test_report_includes_ambiguous_npc_like_field(self):
        """After closure on a module with NPC-like monster names, the persisted
        report includes the ambiguous_npc_like field."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Castle",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Throne Room",
                        "monsters": [{"name": "Sir Reginald"}],
                    }
                ],
            },
        )
        ensure_monster_reference_closure("test_module", self.temp_dir.name)

        report_path = os.path.join(self.temp_dir.name, "monster_closure_report.json")
        with open(report_path, 'r') as f:
            saved = json.load(f)

        self.assertIn("ambiguous_npc_like", saved)
        self.assertIsInstance(saved["ambiguous_npc_like"], list)

    def test_report_includes_unresolved_details(self):
        """After closure on a module with unresolved references, the persisted
        report includes details.unresolved with slug, original_names, and sources."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Crypt",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Tomb",
                        "monsters": [{"name": "Nothic"}, {"name": "Grick"}],
                    }
                ],
            },
        )
        # No monsters dir at all -- both will be unresolved
        report = ensure_monster_reference_closure("test_module", self.temp_dir.name)

        report_path = os.path.join(self.temp_dir.name, "monster_closure_report.json")
        with open(report_path, 'r') as f:
            saved = json.load(f)

        self.assertIn("details", saved)
        self.assertIsInstance(saved["details"], dict)
        if report.get("unresolved", 0) > 0:
            self.assertIn("unresolved", saved["details"])
            for entry in saved["details"]["unresolved"]:
                self.assertIn("slug", entry)
                self.assertIn("original_names", entry)
                self.assertIn("sources", entry)

    def test_report_is_loadable_by_downstream_consumers(self):
        """After closure, the report JSON can be loaded without error and
        field types are correct for downstream consumption."""
        self._write_json(
            os.path.join(self.areas_dir, "A01.json"),
            {
                "areaId": "A01",
                "areaName": "Dungeon",
                "locations": [
                    {
                        "locationId": "R01",
                        "locationName": "Cell",
                        "monsters": [
                            {"name": "Goblin"},
                            {"name": "Skeleton"},
                            {"name": "Sir Reginald"},
                        ],
                    }
                ],
            },
        )
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )
        ensure_monster_reference_closure("test_module", self.temp_dir.name)

        report_path = os.path.join(self.temp_dir.name, "monster_closure_report.json")
        # Loadable
        with open(report_path, 'r') as f:
            saved = json.load(f)

        # Field types correct for downstream consumers
        self.assertIsInstance(saved["required"], int)
        self.assertIsInstance(saved["existing_before"], int)
        self.assertIsInstance(saved["generated"], int)
        self.assertIsInstance(saved["unresolved"], int)
        self.assertIsInstance(saved["ambiguous_npc_like"], list)
        self.assertIsInstance(saved["details"], dict)
        self.assertIsInstance(saved["timestamp"], str)


# ---------------------------------------------------------------------------
# TestPacketBuilderMonsterClosureWiring
# ---------------------------------------------------------------------------


class TestPacketBuilderMonsterClosureWiring(unittest.TestCase):
    """Tests for monster reference closure wiring in the packet builder.

    Verifies that monster closure is called between build completion and
    fidelity gates, and that unresolved references correctly block the
    build before fidelity gates or final-editor routing.
    """

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = self._create_workspace(self.tmpdir_obj.name)

    # -- workspace helpers -----------------------------------------------

    def _create_workspace(self, tmpdir: str) -> Path:
        """Create a minimal workspace with required files."""
        ws = Path(tmpdir) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)

        defaults: Dict[str, Any] = {
            "normalized_packet.json": {
                "packet_version": "packet.v1",
                "name": "test-pipeline",
                "title": "Monster Closure Test",
                "description": "Test module for monster closure wiring",
                "source_hash": "abc123",
                "source_rights": "user_authored",
                "normalization_state": "normalized",
            },
            "ui_review_snapshot.json": {
                "decision": "approve",
                "recorded_at": "2026-01-01T00:00:00Z",
                "job_id": "test-job-mc",
                "packet_identity": {"source_hash": "abc123"},
            },
            "builder_blueprint.json": {},
            "builder_blueprint_report.json": {},
            "builder_narrative.txt": "Test narrative for build",
        }

        for filename, content in defaults.items():
            path = ws / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content) if isinstance(content, dict) else content,
                encoding="utf-8",
            )

        return ws

    def _build_v2_workspace(self) -> None:
        """Set up v2 blueprint artifacts in the existing workspace."""
        bp: Dict[str, Any] = {
            "blueprint_version": _VALID_V2_VERSION,
            "blueprint_status": "ready",
            "module": {"title": "Test V2 Module", "summary": "A v2 test"},
            "source_lock": {"canonical_names_locked": True},
            "area_plan": [],
            "location_roster": [],
            "npc_roster": [],
            "plot_graph": [],
            "puzzle_graph": [],
            "clue_graph": [],
            "encounter_plan": [],
            "item_roster": [],
            "tone_requirements": [],
            "source_refs": [],
            "warnings": [],
            "coverage": {},
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "blockers": [],
        }
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report: Dict[str, str] = {
            "blueprint_status": "ready",
            "fidelity_status": "pass",
        }
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status: str = "success") -> Dict[str, Any]:
        """Return a mock seed writer success result."""
        return {
            "seed_status": status,
            "coverage": {},
            "warnings": [],
        }

    # -- tests -----------------------------------------------------------

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_successful_closure_does_not_block_build(
        self,
        mock_seed,
        mock_rollup,
        mock_can_continue,
        mock_build_report,
        mock_is_required,
        mock_closure,
    ):
        """When monster closure resolves all references, build continues
        to fidelity gates and is not blocked at monster_closure stage."""
        self._build_v2_workspace()
        mock_closure.return_value = {
            "required": 3,
            "existing_before": 2,
            "generated": 1,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = False
        mock_rollup.return_value = {"status": "pass", "blockers": []}

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-successful-closure",
        )

        self.assertIn("monster_closure", result)
        self.assertEqual(result["monster_closure"]["unresolved"], 0)
        # Build should NOT be blocked at monster_closure stage
        self.assertNotEqual(result.get("stage"), "monster_closure")
        self.assertNotEqual(result.get("status"), "blocked")

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    def test_unresolved_monsters_block_build_before_fidelity(
        self,
        mock_rollup,
        mock_can_continue,
        mock_build_report,
        mock_is_required,
        mock_seed,
        mock_closure,
    ):
        """Unresolved monster references block the build at
        monster_closure stage before fidelity gates run."""
        self._build_v2_workspace()
        mock_closure.return_value = {
            "required": 5,
            "existing_before": 2,
            "generated": 0,
            "unresolved": 3,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-unresolved-monsters",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "monster_closure")
        self.assertTrue(
            result["error"].startswith("monster_closure_unresolved:")
        )
        # Fidelity gate helpers should not be called because the build
        # returned before reaching the fidelity gates section.
        mock_is_required.assert_not_called()

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    def test_closure_exception_fails_open(
        self,
        mock_is_required,
        mock_seed,
        mock_closure,
    ):
        """If monster closure raises an exception, the build continues
        past the closure step to fidelity gates."""
        self._build_v2_workspace()
        mock_closure.side_effect = Exception("Transient closure error")
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-closure-exception",
        )

        # The build should NOT be blocked at monster_closure stage
        self.assertNotEqual(result.get("stage"), "monster_closure")
        # Fidelity helpers were called because the build continued past
        # the closure step (fail-open behavior).
        mock_is_required.assert_called()

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    def test_closure_report_attached_to_build_result(
        self,
        mock_is_required,
        mock_seed,
        mock_closure,
    ):
        """Monster closure report is attached to the build result with
        correct counts."""
        self._build_v2_workspace()
        mock_closure.return_value = {
            "required": 5,
            "existing_before": 3,
            "generated": 2,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = False

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-closure-report",
        )

        self.assertIn("monster_closure", result)
        self.assertEqual(result["monster_closure"]["required"], 5)
        self.assertEqual(result["monster_closure"]["existing_before"], 3)
        self.assertEqual(result["monster_closure"]["generated"], 2)
        self.assertEqual(result["monster_closure"]["unresolved"], 0)
        self.assertEqual(result["monster_closure"]["ambiguous_npc_like"], [])


# ---------------------------------------------------------------------------
# TestMonsterClosureParityAndRegression
# ---------------------------------------------------------------------------


class TestMonsterClosureParityAndRegression(unittest.TestCase):
    """Parity tests comparing standalone utility with ModuleGenerator,
    plus regression tests for resolved/unresolved/ambiguous scenarios.

    Verifies that the extracted standalone monster_reference_closure
    functions produce identical results to the original ModuleGenerator
    instance methods for the same inputs, and that specific edge cases
    (resolved, unresolved required, NPC-like ambiguous names) are
    handled correctly.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.module_dir = self.temp_dir.name
        self.areas_dir = os.path.join(self.module_dir, "areas")
        self.monsters_dir = os.path.join(self.module_dir, "monsters")
        os.makedirs(self.areas_dir, exist_ok=True)
        os.makedirs(self.monsters_dir, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_json(self, path: str, data: Dict[str, Any]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _make_mg_instance():
        """Create ModuleGenerator without calling __init__ (avoids provider
        calls and config dependencies)."""
        from core.generators.module_generator import ModuleGenerator
        return object.__new__(ModuleGenerator)

    # -- parity tests -----------------------------------------------------

    def test_normalize_monster_name_parity(self):
        """Compare normalize_monster_name with ModuleGenerator static
        method for 10 test cases."""
        from core.generators.module_generator import ModuleGenerator

        cases = [
            "Goblin",
            "Will-o'-Wisp",
            "Skeleton King",
            "",
            "Orc Warrior",
            "Zombie",
            "Air Elemental",
            "Dr. Frankenstein",
            "Lady Death",
            "Sir Reginald the Bold",
        ]
        for name in cases:
            with self.subTest(name=repr(name)):
                expected = ModuleGenerator._normalize_monster_name(name)
                got = normalize_monster_name(name)
                self.assertEqual(expected, got)

    def test_get_active_area_files_parity(self):
        """Compare get_active_area_files with ModuleGenerator."""
        mg = self._make_mg_instance()

        names = ["A01.json", "A02.json", "A01_BU.json", "A01.bak", "notes.txt"]
        for fname in names:
            path = os.path.join(self.areas_dir, fname)
            if fname.endswith(".json"):
                self._write_json(path, {"areaId": fname[:3]})
            else:
                with open(path, 'w') as f:
                    f.write("x")

        mg_files = mg._get_active_area_files(self.module_dir)
        util_files = get_active_area_files(self.module_dir)

        mg_basenames = sorted(os.path.basename(f) for f in mg_files)
        util_basenames = sorted(os.path.basename(f) for f in util_files)

        self.assertEqual(mg_basenames, util_basenames)
        self.assertIn("A01.json", mg_basenames)
        self.assertNotIn("A01_BU.json", mg_basenames)
        self.assertNotIn("A01.bak", mg_basenames)
        self.assertNotIn("notes.txt", mg_basenames)

    def test_collect_referenced_monsters_parity(self):
        """Compare collect_referenced_monsters with ModuleGenerator for
        dict and string monster references."""
        mg = self._make_mg_instance()

        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Dungeon",
            "locations": [{
                "locationId": "R01",
                "locationName": "Cell",
                "monsters": [{"name": "Goblin"}, {"name": "Skeleton"}, "Orc"],
            }],
        })

        mg_result = mg._collect_referenced_monsters(self.module_dir)
        util_result = collect_referenced_monsters(self.module_dir)

        # Same slugs
        self.assertEqual(set(mg_result.keys()), set(util_result.keys()))

        # Same original_names and source count per slug
        for slug in mg_result:
            mg_names = sorted(mg_result[slug]["original_names"])
            util_names = sorted(util_result[slug]["original_names"])
            self.assertEqual(
                mg_names, util_names,
                f"original_names mismatch for slug '{slug}'",
            )
            self.assertEqual(
                len(mg_result[slug]["sources"]),
                len(util_result[slug]["sources"]),
                f"source count mismatch for slug '{slug}'",
            )

    def test_collect_existing_monster_slugs_parity(self):
        """Compare collect_existing_monster_slugs with ModuleGenerator."""
        mg = self._make_mg_instance()

        for fname in ["goblin.json", "skeleton.json", "goblin_BU.json"]:
            self._write_json(
                os.path.join(self.monsters_dir, fname),
                {"name": fname.replace(".json", "")},
            )

        mg_result = mg._collect_existing_monster_slugs(self.module_dir)
        util_result = collect_existing_monster_slugs(self.module_dir)

        self.assertEqual(mg_result, util_result)
        self.assertIn("goblin", mg_result)
        self.assertIn("skeleton", mg_result)
        self.assertEqual(len(mg_result), 2)

    # -- regression tests -------------------------------------------------

    def test_resolved_monsters_all_present(self):
        """All 3 monster refs already have stat files -> required=3,
        generated=0, unresolved=0."""
        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Dungeon",
            "locations": [{
                "locationId": "R01",
                "locationName": "Cell",
                "monsters": [{"name": "Goblin"}, {"name": "Skeleton"}, {"name": "Orc"}],
            }],
        })
        for slug in ["goblin", "skeleton", "orc"]:
            self._write_json(
                os.path.join(self.monsters_dir, f"{slug}.json"),
                {"name": slug.capitalize()},
            )

        report = ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertEqual(report["required"], 3)
        self.assertEqual(report["existing_before"], 3)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["unresolved"], 0)

    @patch("utils.monster_reference_closure.subprocess.run")
    def test_unresolved_required_monster_blocks(self, mock_run):
        """Missing monster that fails materialization -> unresolved=1
        and slug appears in details.unresolved."""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Mock generation failure"

        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Crypt",
            "locations": [{
                "locationId": "R01",
                "locationName": "Tomb",
                "monsters": [{"name": "Goblin"}, {"name": "Nothic"}],
            }],
        })
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin"},
        )

        report = ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertEqual(report["required"], 2)
        self.assertEqual(report["existing_before"], 1)
        self.assertEqual(report["unresolved"], 1)
        self.assertIn("unresolved", report["details"])
        unresolved_slugs = [u["slug"] for u in report["details"]["unresolved"]]
        self.assertIn("nothic", unresolved_slugs)

    def test_npc_like_ambiguous_name_flagged_in_report(self):
        """NPC-like name 'Sir Reginald' appears in ambiguous_npc_like."""
        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Castle",
            "locations": [{
                "locationId": "R01",
                "locationName": "Throne Room",
                "monsters": [{"name": "Sir Reginald"}],
            }],
        })
        report = ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertIn("sir_reginald", report["ambiguous_npc_like"])

    @patch("utils.monster_reference_closure.subprocess.run")
    def test_npc_like_ambiguous_name_not_silently_materialized(self, mock_run):
        """NPC-like 'Lady Death' is flagged in ambiguous_npc_like even
        when materialization proceeds (ambiguity is recorded pre-generation)."""
        mock_run.return_value.returncode = 0

        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Graveyard",
            "locations": [{
                "locationId": "R01",
                "locationName": "Tomb",
                "monsters": [{"name": "Lady Death"}],
            }],
        })
        report = ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertIn("lady_death", report["ambiguous_npc_like"])

    def test_creature_type_name_not_flagged_as_ambiguous(self):
        """'Goblin' is a creature type keyword and is NOT in
        ambiguous_npc_like."""
        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Cave",
            "locations": [{
                "locationId": "R01",
                "locationName": "Entrance",
                "monsters": [{"name": "Goblin"}],
            }],
        })
        report = ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertNotIn("goblin", report["ambiguous_npc_like"])

    def test_module_generator_closure_still_works(self):
        """ModuleGenerator._ensure_monster_reference_closure still works
        (required=1, existing=1, unresolved=0) proving existing path was
        not broken. All monsters exist so subprocess is never called."""
        from core.generators.module_generator import ModuleGenerator
        mg = object.__new__(ModuleGenerator)

        self._write_json(os.path.join(self.areas_dir, "A01.json"), {
            "areaId": "A01",
            "areaName": "Dungeon",
            "locations": [{
                "locationId": "R01",
                "locationName": "Cell",
                "monsters": [{"name": "Goblin"}],
            }],
        })
        self._write_json(
            os.path.join(self.monsters_dir, "goblin.json"),
            {"name": "Goblin", "armorClass": 15, "hitPoints": 7},
        )

        # All monsters exist, so no subprocess call is made.
        report = mg._ensure_monster_reference_closure("test_module", self.module_dir)
        self.assertEqual(report["required"], 1)
        self.assertEqual(report["existing_before"], 1)
        self.assertEqual(report["unresolved"], 0)


if __name__ == "__main__":
    unittest.main()
