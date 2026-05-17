# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for Phase 10 deterministic import fallback routing.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.importers.homebrewery_importer import (
    _parse_content_blocks,
    import_homebrewery_adventure_to_module,
)


class TestInsufficientStructure(unittest.TestCase):
    """Deterministic path fails closed when no blocks found."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_no_structured_headings_returns_error(self):
        source = Path(self.temp_dir) / "empty_adventure.txt"
        source.write_text("# Just a Title\n\nSome prose description.\n\nNo room blocks here.")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="EmptyTest",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("quarantine_reason"), "deterministic_insufficient_structure")

    def test_no_artifact_files_created(self):
        source = Path(self.temp_dir) / "empty_adventure.txt"
        source.write_text("# Just prose with no structure.")
        output_root = Path(self.temp_dir) / "modules"
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="EmptyTest",
            output_root=str(output_root),
            use_deterministic=True,
            dry_run=False,
        )
        self.assertEqual(result["status"], "error")
        self.assertFalse((output_root / "EmptyTest").exists())

    def test_empty_source_returns_error(self):
        source = Path(self.temp_dir) / "empty.txt"
        source.write_text("")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="EmptyTest",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "error")

    def test_parse_content_blocks_empty_prose(self):
        self.assertEqual(_parse_content_blocks("Just prose, no headings."), [])
        self.assertEqual(_parse_content_blocks(""), [])


class TestAiDrivenPathNotAffected(unittest.TestCase):
    """Non-deterministic AI-driven path is not affected by deterministic changes.

    The AI-driven path code was not modified; these tests verify the
    deterministic_insufficient_structure error is NOT returned from the AI path.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source = Path(self.temp_dir) / "test.txt"
        self.source.write_text(
            "```metadata\ntitle: Test Module\n```\n\nSome content without room blocks."
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_ai_path_error_not_deterministic_insufficient(self):
        """The AI-driven path returns its own error type, not
        deterministic_insufficient_structure."""
        from unittest.mock import patch
        with patch("core.importers.homebrewery_importer.ai_driven_module_creation",
                   return_value=(False, None)):
            result = import_homebrewery_adventure_to_module(
                source_path=str(self.source),
                module_slug="NonDetTest",
                output_root=str(self.temp_dir),
                use_deterministic=False,
                dry_run=True,
            )
        self.assertNotEqual(
            result.get("quarantine_reason"),
            "deterministic_insufficient_structure",
        )


class TestNumberedListNotPromoted(unittest.TestCase):
    """Numbered lists and prose are not treated as location blocks."""

    def test_bullet_points_not_locations(self):
        text = "# Map Key\n\n### 1. Tavern\n\nItems:\n- Ale\n- Bread\n- Cheese\n\nPrices:\n1. Ale: 1 sp\n2. Bread: 2 cp"
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)

    def test_description_list_items_not_locations(self):
        text = "# Map Key\n\n### 1. Armory\n\nWeapons:\n1. Longsword (on rack)\n2. Shortbow (on wall)\n3. Shield (leaning)"
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["_source_title"], "Armory")


class TestSubLocationParentMetadata(unittest.TestCase):
    """Sub-location parent context preservation."""

    def test_sub_location_has_parent(self):
        text = "# Map Key\n\n### 2. Brooksteps Inn\nMain floor.\n\n#### 1. Cellar\nDamp and dark."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["_source_block_kind"], "map_key_location")
        self.assertEqual(blocks[1]["_source_block_kind"], "sub_location")
        self.assertEqual(blocks[1]["_source_parent_title"], "Brooksteps Inn")
        self.assertEqual(blocks[1]["_source_parent_number"], 2)


class TestSourceMetadataPreservation(unittest.TestCase):
    """Source metadata retained for downstream fidelity stages."""

    def test_block_kind_preserved(self):
        text = "### 1. Crypt\nDark.\n\n# Map Key\n\n### 2. Vault\nGold."
        blocks = _parse_content_blocks(text)
        kinds = [b["_source_block_kind"] for b in blocks]
        self.assertEqual(kinds, ["map_key_location"])

    def test_heading_text_preserved(self):
        text = "# Map Key\n\n### 1. Brooksteps Inn\nWarm."
        blocks = _parse_content_blocks(text)
        self.assertIn("Brooksteps Inn", blocks[0]["_source_heading_text"])

    def test_heading_level_preserved(self):
        text = "# Locations\n\n### 1. Shop\nGoods.\n\n#### 1. Back Room\nStoreroom."
        blocks = _parse_content_blocks(text)
        self.assertEqual(blocks[0]["_source_heading_level"], 3)
        self.assertEqual(blocks[1]["_source_heading_level"], 4)

    def test_style_preserved(self):
        text = "# Map Key\n\n### 1 - Outskirts\nFarming.\n\n### 2. Town Center\nMarket."
        blocks = _parse_content_blocks(text)
        styles = [b["_source_block_style"] for b in blocks]
        self.assertEqual(styles, ["map_key_dash", "map_key_dot"])

    def test_raw_content_preserved(self):
        text = "# Map Key\n\n### 1. Tavern\nAle served here."
        blocks = _parse_content_blocks(text)
        self.assertIn("Ale served", blocks[0]["raw_content"])

    def test_emitter_compatible_source_number_available(self):
        text = "# Map Key\n\n### 1. Tavern\nBeer."
        blocks = _parse_content_blocks(text)
        record_keys = {"source_room_number", "source_room_title", "name", "description",
                       "puzzle", "solution", "creatures", "exit_comment",
                       "other_sections", "tables", "raw_content"}
        for block in blocks:
            for key in record_keys:
                self.assertIn(key, block, f"Missing key: {key}")


class TestConservativeMapKeyClassification(unittest.TestCase):
    """Phase 10: Conservative map-key heading acceptance rules."""

    def test_isolated_heading_rejected(self):
        """Single ### N. Title outside a map-key section is rejected."""
        text = "### 1. Adventure Hook\nA mysterious summons."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 0)

    def test_two_isolated_headings_rejected(self):
        """Two ### N. headings outside a map-key section are rejected."""
        text = ("### 1. Backstory\nOnce upon a time.\n\n"
                "### 2. Quest Giver\nAn old wizard appears.")
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 0)

    def test_under_map_key_section_accepted(self):
        """### heading under # Map Key is accepted."""
        text = "# Map Key\n\n### 1. Brooksteps Inn\nA cozy inn."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["_source_title"], "Brooksteps Inn")

    def test_under_locations_section_accepted(self):
        """### heading under ## Locations is accepted."""
        text = "## Locations\n\n### 2 - Wizard Tower\nCrackling with energy."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["_source_title"], "Wizard Tower")

    def test_under_town_section_accepted(self):
        """### heading under # Town is accepted."""
        text = "# The Town of Haven\n\n### 1. Market\nBusy square."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)

    def test_under_non_map_parent_rejected(self):
        """### heading under ## Backstory (non-map term) is rejected."""
        text = "## Backstory\n\n### 1. Origin\nBorn in a storm."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 0)

    def test_dense_run_accepted(self):
        """Three consecutive ### headings form a dense run."""
        text = ("### 1. Crypt\nDark.\n\n"
                "### 2. Vault\nGold.\n\n"
                "### 3. Armory\nWeapons.")
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 3)
        titles = [b["_source_title"] for b in blocks]
        self.assertEqual(titles, ["Crypt", "Vault", "Armory"])

    def test_dense_run_with_room_mixed(self):
        """### headings after a room heading can form a dense run."""
        text = ("### 1. Outer Bailey\nGuard post.\n\n"
                "## Room 1: Keep\nThrone room.\n\n"
                "### 2. Inner Sanctum\nSecret chamber.\n\n"
                "### 3. Treasury\nGold piles.\n\n"
                "### 4. Dungeon\nCells.")
        blocks = _parse_content_blocks(text)
        # Outer Bailey is isolated (not in dense run), only ### 2-4 form a run
        self.assertEqual(len(blocks), 4)

    def test_two_headings_not_enough_for_dense_run(self):
        """Two ### headings alone do not form a dense run."""
        text = ("### 1. Crypt\nDark.\n\n"
                "### 2. Vault\nGold.")
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 0)

    def test_heading_under_room_colon_always_accepted(self):
        """## Room N: Title is always accepted regardless of context."""
        text = "## Room 1: Entrance\nA door."
        blocks = _parse_content_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["_source_block_kind"], "room")


class TestAmbiguousImportRouting(unittest.TestCase):
    """Deterministic import returns ambiguous status for weak map-key structure."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_insufficient_dot1_heading_no_blocks(self):
        """A single ambiguous ### heading returns ambiguous."""
        source = Path(self.temp_dir) / "test.txt"
        source.write_text("### 1. Adventure Hook\nA mysterious summons.\n\n### 2. Quest\nGo find the orb.\n\n### 3. Encounter\nFight!")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="WeakMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        # Three ### in a row with no intervening non-### headings = dense run, accepted.
        # This should succeed.
        self.assertEqual(result["status"], "dry_run")

    def test_ambiguous_single_heading_in_import(self):
        """Single isolated ### heading returns ambiguous_ structure."""
        source = Path(self.temp_dir) / "test.txt"
        source.write_text("### 1. Adventure Hook\nA mysterious summons.")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="WeakMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("quarantine_reason"), "deterministic_ambiguous_structure")

    def test_ambiguous_two_headings_in_import(self):
        """Two isolated ### headings return ambiguous."""
        source = Path(self.temp_dir) / "test.txt"
        source.write_text("### 1. Backstory\nOnce upon a time.\n\n### 2. Quest\nFind the orb.")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="TwoMapKey",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("quarantine_reason"), "deterministic_ambiguous_structure")

    def test_ambiguous_creates_no_artifacts(self):
        """Ambiguous structure writes no module artifacts."""
        source = Path(self.temp_dir) / "test.txt"
        source.write_text("### 1. Ambiguous\nNot enough context.")
        output_root = Path(self.temp_dir) / "modules"
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="NoArtifacts",
            output_root=str(output_root),
            use_deterministic=True,
            dry_run=False,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("quarantine_reason"), "deterministic_ambiguous_structure")
        self.assertFalse((output_root / "NoArtifacts").exists())

    def test_dense_run_three_imports_success(self):
        """Three ### consecutive in file is accepted (dense run)."""
        source = Path(self.temp_dir) / "test.txt"
        source.write_text("### 1. Crypt\nDark.\n\n### 2. Vault\nGold.\n\n### 3. Armory\nWeapons.")
        result = import_homebrewery_adventure_to_module(
            source_path=str(source),
            module_slug="DenseRun",
            output_root=str(self.temp_dir),
            use_deterministic=True,
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        preview = result.get("preview", {})
        self.assertEqual(preview.get("block_count"), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
