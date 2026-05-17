# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for Phase 10 map-key location import in homebrewery_importer.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.importers.homebrewery_importer import (
    _parse_content_blocks,
    _content_block_to_room_record,
    _build_intermediate_adventure,
    _generate_neq_ids,
    import_homebrewery_adventure_to_module,
)


_MAP_KEY_SOURCE = """```metadata
title: Test Map Key Module
```

# Map Key

### 1. Brooksteps Inn
A cozy inn run by a retired adventurer.
The common room smells of ale and woodsmoke.

### 2. Wizard's Tower
A crumbling stone tower crackling with arcane energy.
Three floors of puzzles and treasure.

### 3. Temple of Broance
A serene marble temple with a central fountain.
The high priest offers quests to worthy adventurers.
"""


class TestMapKeyParsing(unittest.TestCase):
    """Map-key heading parsing."""

    def test_dot_headings_parsed(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["_source_block_kind"], "map_key_location")
        self.assertEqual(blocks[0]["_source_title"], "Brooksteps Inn")
        self.assertEqual(blocks[1]["_source_title"], "Wizard's Tower")
        self.assertEqual(blocks[2]["_source_title"], "Temple of Broance")

    def test_source_order_preserved(self):
        text = "### 1. First\nA.\n\n### 4. Fourth\nB.\n\n### 2. Second\nC."
        blocks = _parse_content_blocks(text)
        titles = [b["_source_title"] for b in blocks]
        self.assertEqual(titles, ["First", "Fourth", "Second"])

    def test_source_number_provenance(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        numbers = [b["_source_number"] for b in blocks]
        self.assertEqual(numbers, [1, 2, 3])

    def test_dash_headings_parsed(self):
        text = "# Map Key\n\n### 1 - Crypt Entrance\nA dark tunnel leads down."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["_source_block_style"], "map_key_dash")
        self.assertEqual(blocks[0]["_source_title"], "Crypt Entrance")

    def test_content_preserved(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        self.assertIn("cozy inn", blocks[0]["description"])
        self.assertIn("crumbling", blocks[1]["description"])
        self.assertIn("serene", blocks[2]["description"])


class TestMapKeyConversion(unittest.TestCase):
    """Map-key content block to room-record conversion."""

    def test_room_record_shape(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        record = _content_block_to_room_record(blocks[0], 1)
        self.assertEqual(record["source_room_number"], 1)
        self.assertEqual(record["source_room_title"], "Brooksteps Inn")
        self.assertEqual(record["name"], "Brooksteps Inn")
        self.assertIn("cozy inn", record["description"])
        self.assertIn("raw_content", record)
        self.assertIn("tables", record)
        self.assertIn("other_sections", record)

    def test_neq_id_sequential(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        rooms = [_content_block_to_room_record(b, i + 1) for i, b in enumerate(blocks)]
        area_id, location_ids = _generate_neq_ids("TestMap", rooms)
        self.assertEqual(area_id, "TES001")
        self.assertEqual(len(location_ids), 3)
        self.assertEqual(location_ids, ["TES01", "TES02", "TES03"])

    def test_source_number_not_id(self):
        rooms = [
            {"source_room_number": 100, "source_room_title": "Finale",
             "name": "Finale", "description": "", "puzzle": "", "solution": "",
             "creatures": "", "exit_comment": "", "other_sections": {},
             "tables": [], "raw_content": ""},
        ]
        area_id, location_ids = _generate_neq_ids("Fin", rooms)
        self.assertEqual(location_ids[0], "FIN01")
        self.assertNotEqual(location_ids[0], "FIN100")


class TestMapKeyDryRun(unittest.TestCase):
    """Dry-run behavior for map-key sources."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source_file = Path(self.temp_dir) / "test_map_key.txt"
        self.source_file.write_text(_MAP_KEY_SOURCE)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_dry_run_returns_preview(self):
        result = import_homebrewery_adventure_to_module(
            source_path=str(self.source_file),
            module_slug="TestMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertIn("block_count", result.get("preview", {}))
        self.assertEqual(result["preview"]["block_count"], 3)

    def test_dry_run_no_files_created(self):
        output_root = Path(self.temp_dir) / "modules"
        result = import_homebrewery_adventure_to_module(
            source_path=str(self.source_file),
            module_slug="TestMapKey",
            output_root=str(output_root),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(output_root.exists())

    def test_dry_run_preview_has_location_ids(self):
        result = import_homebrewery_adventure_to_module(
            source_path=str(self.source_file),
            module_slug="TestMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        preview = result.get("preview", {})
        self.assertIn("location_ids", preview)
        self.assertEqual(len(preview["location_ids"]), 3)


class TestMapKeyEmittedArtifacts(unittest.TestCase):
    """Full deterministic build for map-key source."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source_file = Path(self.temp_dir) / "test_map_key.txt"
        self.source_file.write_text(_MAP_KEY_SOURCE)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_build_emits_artifacts(self):
        result = import_homebrewery_adventure_to_module(
            source_path=str(self.source_file),
            module_slug="TestMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=False,
        )
        # Module may be quarantined after schema validation; artifacts were still created
        self.assertIn(result["status"], ("success", "quarantined"))
        self.assertGreater(len(result.get("artifacts", [])), 0)

    def test_intermediate_source_metadata(self):
        blocks = _parse_content_blocks(_MAP_KEY_SOURCE)
        rooms = [_content_block_to_room_record(b, i + 1) for i, b in enumerate(blocks)]
        intermediate = _build_intermediate_adventure("Test", "test.txt", rooms)
        # Source metadata is preserved at the block level
        self.assertEqual(intermediate["source"]["room_count"], 3)
        # Each block retains additive metadata keys
        for b in blocks:
            self.assertIn("_source_block_kind", b)
            self.assertIn("_source_number", b)
            self.assertIn("_source_heading_text", b)
            self.assertIn("_source_heading_level", b)
            self.assertIn("_source_block_style", b)
            self.assertIn("_source_title", b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
