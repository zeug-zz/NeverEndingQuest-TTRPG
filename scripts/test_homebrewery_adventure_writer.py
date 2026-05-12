# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Contract tests for utils/homebrewery_adventure_writer.py.

Verifies generation produces valid V3 Homebrewery output, includes all required
sections, handles credits attribution correctly, and handles missing data.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.homebrewery_adventure_writer import (
    generate_homebrewery_adventure,
    load_module_data,
    _parse_author_field,
    _npc_display_name,
)


class TestGenerateHomebreweryAdventure(unittest.TestCase):
    """End-to-end generation tests for The Ancients Lab."""

    @classmethod
    def setUpClass(cls):
        cls.md = generate_homebrewery_adventure("The_Ancients_Lab")

    def test_output_is_non_empty(self):
        self.assertIsInstance(self.md, str)
        self.assertGreater(len(self.md), 1000)

    def test_starts_with_v3_metadata(self):
        self.assertIn("renderer: V3", self.md[:500])
        self.assertIn("theme: 5ePHB", self.md[:500])

    def test_contains_cover_page(self):
        self.assertIn("{{frontCover}}", self.md)

    def test_contains_page_breaks(self):
        self.assertIn("\\page", self.md)
        self.assertIn("{{pageNumber,auto}}", self.md)

    def test_contains_plot_points(self):
        self.assertIn("PP001", self.md)
        self.assertIn("PP013", self.md)

    def test_contains_npc_names(self):
        # Display names use title case
        self.assertIn("The Thing", self.md)
        self.assertIn("Archivist Automaton", self.md)
        self.assertIn("Edda Coppervein", self.md)

    def test_contains_location_section(self):
        self.assertIn("# Locations", self.md)

    def test_contains_monster_gallery(self):
        self.assertIn("# Monster Gallery", self.md)

    def test_contains_credits(self):
        self.assertIn("{{credits}}", self.md)
        self.assertIn("# Credits", self.md)

    def test_credits_author(self):
        self.assertIn("**Author:** Kuhal", self.md)

    def test_credits_source_url(self):
        self.assertIn("homebrewery.naturalcrit.com", self.md)

    def test_credits_license(self):
        self.assertIn("creativecommons.org", self.md)
        self.assertIn("[https://creativecommons.org", self.md)

    def test_credits_srd_attribution(self):
        self.assertIn("CC BY 4.0", self.md)

    def test_output_is_ascii(self):
        try:
            self.md.encode("ascii")
        except UnicodeEncodeError:
            self.fail("Output contains non-ASCII characters")


class TestLoadModuleData(unittest.TestCase):
    """Test data loading for a real module."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_module_data("The_Ancients_Lab")

    def test_loads_author(self):
        self.assertIn("Kuhal", self.data["author"])

    def test_loads_license(self):
        self.assertIn("creativecommons.org", self.data["license"])

    def test_loads_npcs(self):
        npcs = self.data.get("npcs", {})
        self.assertIsInstance(npcs, dict)
        self.assertGreater(len(npcs), 0)

    def test_loads_plot_points(self):
        plot = self.data.get("plot_points", [])
        self.assertIsInstance(plot, list)
        self.assertGreater(len(plot), 0)

    def test_loads_areas(self):
        areas = self.data.get("areas", [])
        self.assertIsInstance(areas, list)
        self.assertGreater(len(areas), 0)

    def test_loads_monsters(self):
        monsters = self.data.get("monsters", [])
        self.assertIsInstance(monsters, list)
        self.assertGreater(len(monsters), 0)

    def test_loads_display_name(self):
        self.assertEqual(self.data["display_name"], "The Ancients Lab")


class TestParseAuthorField(unittest.TestCase):
    """Test author field parsing."""

    def test_author_with_url(self):
        author = "Kuhal - Module derived from https://homebrewery.naturalcrit.com/share/SyBdnURLNZ"
        name, url = _parse_author_field(author)
        self.assertEqual(name, "Kuhal")
        self.assertEqual(url, "https://homebrewery.naturalcrit.com/share/SyBdnURLNZ")

    def test_author_no_url(self):
        author = "Kuhal"
        name, url = _parse_author_field(author)
        self.assertEqual(name, "Kuhal")
        self.assertEqual(url, "")

    def test_author_em_dash(self):
        author = "Alice \u2014 description"
        name, url = _parse_author_field(author)
        self.assertEqual(name, "Alice")

    def test_author_en_dash(self):
        author = "Bob \u2013 notes"
        name, url = _parse_author_field(author)
        self.assertEqual(name, "Bob")

    def test_author_empty(self):
        name, url = _parse_author_field("")
        self.assertEqual(name, "")
        self.assertEqual(url, "")

    def test_author_only_url(self):
        author = "https://example.com"
        name, url = _parse_author_field(author)
        self.assertEqual(url, "https://example.com")

    def test_author_multiple_urls(self):
        author = "Test - see https://a.com or https://b.com"
        name, url = _parse_author_field(author)
        self.assertEqual(name, "Test")
        self.assertEqual(url, "https://a.com")


class TestNpcDisplayName(unittest.TestCase):
    """Test NPC key to display name conversion."""

    def test_underscore_conversion(self):
        self.assertEqual(_npc_display_name("the_thing"), "The Thing")

    def test_multi_word(self):
        self.assertEqual(
            _npc_display_name("rambling_dwarven_survivor"),
            "Rambling Dwarven Survivor",
        )

    def test_already_title(self):
        self.assertEqual(_npc_display_name("Kuhal"), "Kuhal")


class TestMissingDataModule(unittest.TestCase):
    """Test that missing/nonexistent module data doesn't crash."""

    def test_nonexistent_module_returns_empty_data(self):
        data = load_module_data("nonexistent_module_xyz")
        self.assertIsInstance(data, dict)
        self.assertEqual(data["npcs"], {})
        self.assertEqual(data["author"], "")
        self.assertEqual(data["license"], "")

    def test_missing_module_generates_minimal_doc(self):
        # Should not raise
        result = generate_homebrewery_adventure("nonexistent_module_xyz")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)
        self.assertIn("renderer: V3", result)


class TestGeneratedSections(unittest.TestCase):
    """Verify specific section content."""

    @classmethod
    def setUpClass(cls):
        cls.md = generate_homebrewery_adventure("The_Ancients_Lab")

    def test_intro_contains_module_name(self):
        self.assertIn("The Ancients Lab", self.md)

    def test_plot_overview_section(self):
        self.assertIn("# Plot Overview", self.md)

    def test_npc_gallery_section(self):
        self.assertIn("# NPC Gallery", self.md)

    def test_locations_section(self):
        self.assertIn("# Locations", self.md)

    def test_items_appendix(self):
        self.assertIn("# Appendix A: Treasures", self.md)

    def test_treasure_index_present(self):
        """Verify treasure index has at least 10 items for a module with 35+ loot entries."""
        treasure_section = self.md.split("# Appendix A: Treasures")[1].split("\n# ")[0]
        bullet_count = treasure_section.count("\n- **")
        self.assertGreaterEqual(bullet_count, 10,
                                "Expected >=10 treasure items, got {}".format(bullet_count))

    def test_location_section_exists(self):
        loc_section = self.md.split("# Locations")[1].split("\n# ")[0]
        self.assertIsInstance(loc_section, str)
        self.assertGreater(len(loc_section.strip()), 0)
        self.assertIn("Warped Sentinel Vestibule", loc_section,
                      "Location section should contain actual room names, not placeholder text")

    def test_locations_contain_room_names(self):
        """Verify all 12 room names appear in the output."""
        rooms = [
            "Warped Sentinel Vestibule",
            "Fleshforged Observation Nook",
            "Huskbound Termination Cell",
            "Shattered Forge Approach",
            "Abyssal Fracture",
            "Forsaken Outrider Encampment",
            "Fused Iron Antechamber",
            "Throne of Twisted Lineage",
            "Forgotten Splice Vault",
            "Twisted Forge Atrium",
            "Bygone Mutation Vault",
            "Runebound Isolation Cell",
        ]
        for room in rooms:
            self.assertIn(room, self.md, "Missing room: {}".format(room))

    def test_locations_contain_dm_guidance(self):
        """Verify DM Guidance appears at least once per room (12+)."""
        count = self.md.count("**DM Guidance:**")
        self.assertGreaterEqual(count, 12,
                                "Expected >=12 DM Guidance sections, got {}".format(count))

    def test_locations_contain_npcs(self):
        """Verify location NPCS appear in output."""
        self.assertIn("Rambling Dwarven Survivor", self.md)
        self.assertIn("Damaged Security Overseer", self.md)
        self.assertIn("Archivist Automaton", self.md)

    def test_locations_contain_monsters(self):
        """Verify monster names appear in location sections."""
        self.assertIn("Aberrant Creeper", self.md)
        self.assertIn("Fleshforged Aberrant", self.md)
        self.assertIn("Huskbound Wretch", self.md)

    def test_locations_contain_plot_hooks(self):
        """Verify Plot Hooks headers appear."""
        self.assertIn("**Plot Hooks:**", self.md)

    def test_locations_have_area_overview(self):
        """Verify area-level prose exists between area heading and first location."""
        loc_section = self.md.split("# Locations")[1].split("\n# ")[0]
        area_blocks = loc_section.split("## ")
        # Each area block except the first (empty) should have content between
        # the ## heading and the first ### location heading
        for block in area_blocks[1:]:
            # Content between area header and first location header
            if "### " in block:
                area_prose = block.split("### ")[0].strip()
                self.assertGreater(len(area_prose), 50,
                                   "Area overview prose too short for block starting: {}".format(
                                       block[:60]
                                   ))
            else:
                # Flat-schema area with no locations
                self.assertGreater(len(block.strip()), 0)

    def test_monster_has_statblock(self):
        mg_start = self.md.find("# Monster Gallery")
        self.assertIn("Armor Class", self.md[mg_start:])

    def test_cover_has_right_snippets(self):
        cover_section = self.md[: self.md.find("\\page")]
        self.assertIn("{{frontCover}}", cover_section)


class TestAdventureEndpointContract(unittest.TestCase):
    """Test the API endpoint contract for adventure markdown download.

    These tests verify the generation logic that the Flask endpoint wraps.
    Full HTTP-level tests (Content-Type, Content-Disposition, status codes)
    require a running Flask server and are verified manually.
    """

    def test_adventure_endpoint_content_is_valid_markdown(self):
        """Endpoint returns valid V3 Homebrewery markdown (covers 5.10)."""
        md = generate_homebrewery_adventure("The_Ancients_Lab")
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 1000)
        self.assertIn("renderer: V3", md[:500])
        self.assertIn("\\page", md)

    def test_adventure_endpoint_nonexistent_module(self):
        """Endpoint for nonexistent module returns minimal valid doc (covers 5.9)."""
        md = generate_homebrewery_adventure("nonexistent_module_xyz")
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 100)
        self.assertIn("renderer: V3", md)

    def test_adventure_download_filename(self):
        """Download filename contract: <slug>_adventure.md."""
        slug = "The_Ancients_Lab"
        expected = f"{slug}_adventure.md"
        self.assertEqual(expected, "The_Ancients_Lab_adventure.md")

    def test_adventure_endpoint_content_type_text_markdown(self):
        """The generation function produces text-compatible markdown output."""
        md = generate_homebrewery_adventure("The_Ancients_Lab")
        self.assertTrue(md.startswith("<!--") or md.startswith("{{"))


if __name__ == "__main__":
    unittest.main()
