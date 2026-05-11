# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Contract tests for utils/homebrewery_style.py.

Verifies that all template constants are non-empty, helper functions produce
valid V3 Homebrewery markdown, and no legacy renderer patterns are present.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.homebrewery_style import (
    METADATA_TEMPLATE,
    COVER_PAGE_TEMPLATE,
    MONSTER_STATBLOCK_TEMPLATE,
    ITEM_BLOCK_TEMPLATE,
    IMAGE_PLACEMENT_TEMPLATE,
    IMAGE_MASK_EDGE7_TEMPLATE,
    TOC_TEMPLATE,
    WIDE_CONTENT_TEMPLATE,
    FOOTNOTE_TEMPLATE,
    FRONT_COVER_SNIPPET,
    BANNER_SNIPPET,
    PAGE_NUMBER_SNIPPET,
    INSIDE_COVER_SNIPPET,
    CREDITS_SNIPPET,
    PAGE_BREAK,
    COLUMN_BREAK,
    format_metadata,
    format_cover_page,
    format_monster_statblock,
    format_item_block,
    format_image_placement,
    format_toc,
    format_wide_content,
    format_footnote,
    sanitize_markdown_text,
)

LEGACY_PATTERNS = [
    ".phb#",
    "pageNumber auto",
    "class='footnote'",
    "position:absolute;",
]


class TestHomebreweryStyleModule(unittest.TestCase):
    """Verify module imports and exports."""

    def test_module_imports(self):
        from utils.homebrewery_style import (
            format_metadata,
            format_cover_page,
            format_monster_statblock,
            format_item_block,
        )
        self.assertTrue(callable(format_metadata))

    def test_all_constants_non_empty(self):
        constants = [
            METADATA_TEMPLATE,
            COVER_PAGE_TEMPLATE,
            MONSTER_STATBLOCK_TEMPLATE,
            ITEM_BLOCK_TEMPLATE,
            IMAGE_PLACEMENT_TEMPLATE,
            TOC_TEMPLATE,
            WIDE_CONTENT_TEMPLATE,
            FOOTNOTE_TEMPLATE,
            PAGE_BREAK,
            COLUMN_BREAK,
        ]
        for const in constants:
            self.assertTrue(isinstance(const, str))
            self.assertGreater(len(const.strip()), 0)

    def test_snippets_non_empty(self):
        snippets = [
            FRONT_COVER_SNIPPET,
            BANNER_SNIPPET,
            PAGE_NUMBER_SNIPPET,
            INSIDE_COVER_SNIPPET,
            CREDITS_SNIPPET,
        ]
        for snippet in snippets:
            self.assertGreater(len(snippet), 0)

    def test_no_legacy_patterns_in_templates(self):
        templates = [
            METADATA_TEMPLATE,
            COVER_PAGE_TEMPLATE,
            MONSTER_STATBLOCK_TEMPLATE,
            ITEM_BLOCK_TEMPLATE,
            IMAGE_PLACEMENT_TEMPLATE,
            TOC_TEMPLATE,
            WIDE_CONTENT_TEMPLATE,
            FOOTNOTE_TEMPLATE,
            PAGE_BREAK,
            COLUMN_BREAK,
        ]
        for i, tmpl in enumerate(templates):
            for pattern in LEGACY_PATTERNS:
                self.assertNotIn(
                    pattern,
                    tmpl,
                    f"Template at index {i} contains legacy pattern: {pattern}",
                )


class TestMetadataFunction(unittest.TestCase):
    """Test format_metadata() output."""

    def test_produces_yaml_header(self):
        result = format_metadata("Test Adventure")
        self.assertIn("renderer: V3", result)
        self.assertIn("theme: 5ePHB", result)
        self.assertIn("Test Adventure", result)
        self.assertIn("<!--", result)
        self.assertIn("-->", result)

    def test_has_title_quoted(self):
        result = format_metadata("My Module")
        self.assertIn("title: 'My Module'", result)

    def test_empty_fields_accepted(self):
        result = format_metadata("", tags="", systems="")
        self.assertIn("renderer: V3", result)


class TestCoverPageFunction(unittest.TestCase):
    """Test format_cover_page() output."""

    def test_contains_all_snippets(self):
        result = format_cover_page("Adventure", "Module", "cover.jpg")
        self.assertIn(FRONT_COVER_SNIPPET, result)
        self.assertIn(BANNER_SNIPPET, result)
        self.assertIn(PAGE_NUMBER_SNIPPET, result)

    def test_contains_title_and_subtitle(self):
        result = format_cover_page("Test", "Sub")
        self.assertIn("# Test", result)
        self.assertIn("## Sub", result)

    def test_contains_image_directive(self):
        result = format_cover_page("T", "S", "https://example.com/img.jpg")
        self.assertIn("example.com/img.jpg", result)
        self.assertIn("position:absolute", result)

    def test_empty_image_url(self):
        result = format_cover_page("T", "S", "")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 20)

    def test_front_cover_snippet_present(self):
        result = format_cover_page("A", "B", "c.jpg")
        self.assertTrue(result.strip().startswith("{{frontCover}}"))


class TestMonsterStatBlock(unittest.TestCase):
    """Test format_monster_statblock() output."""

    def test_produces_statblock_structure(self):
        result = format_monster_statblock(
            name="Goblin",
            size="Small",
            creature_type="Humanoid",
            alignment="Neutral Evil",
            armor_class=15,
            hit_points="7 (2d6)",
            speed="30 ft.",
        )
        self.assertIn("> ### Goblin", result)
        self.assertIn("Small Humanoid", result)
        self.assertIn("Neutral Evil", result)
        self.assertIn("Armor Class", result)
        self.assertIn("Hit Points", result)
        self.assertIn("|STR|DEX|CON|INT|WIS|CHA|", result)

    def test_ability_table_rendered(self):
        result = format_monster_statblock(
            name="Ogre",
            strength=19,
            dexterity=8,
            constitution=16,
            intelligence=5,
            wisdom=7,
            charisma=7,
        )
        self.assertIn("19 (+4)", result)
        self.assertIn("8 (-1)", result)
        self.assertIn("5 (-3)", result)

    def test_traits_and_actions_included(self):
        result = format_monster_statblock(
            name="Test",
            abilities="> ***Keen Senses.*** Advantage on Perception.",
            actions="> ***Bite.*** +5 to hit, 1d6 damage.",
        )
        self.assertIn("Keen Senses", result)
        self.assertIn("Bite.", result)


class TestItemBlock(unittest.TestCase):
    """Test format_item_block() output."""

    def test_produces_item_structure(self):
        result = format_item_block(
            name="Ring of Power",
            rarity="Rare",
            description="A golden ring with an inscribed flame motif.",
        )
        self.assertIn(">#### Ring of Power", result)
        self.assertIn("**Rare**", result)
        self.assertIn("golden ring", result)

    def test_empty_rarity(self):
        result = format_item_block(name="Mysterious Stone", rarity="", description="A smooth stone.")
        self.assertIn("Mysterious Stone", result)
        self.assertIn("smooth stone", result)


class TestImagePlacement(unittest.TestCase):
    """Test format_image_placement() output."""

    def test_with_position_args(self):
        result = format_image_placement(
            url="img.png",
            alt="Map",
            position_args="top:0,left:0,width:100%",
        )
        self.assertIn("img.png", result)
        self.assertIn("position:absolute", result)
        self.assertIn("top:0", result)

    def test_without_position_args(self):
        result = format_image_placement(url="img.png", alt="Pic")
        self.assertIn("img.png", result)
        self.assertNotIn("position:", result)


class TestSanitizeText(unittest.TestCase):
    """Test sanitize_markdown_text() output."""

    def test_replaces_em_dash(self):
        self.assertEqual(sanitize_markdown_text("foo\u2014bar"), "foo--bar")

    def test_replaces_curly_quotes(self):
        self.assertEqual(
            sanitize_markdown_text("\u201cHello\u201d"),
            '"Hello"',
        )

    def test_replaces_ellipsis(self):
        self.assertEqual(sanitize_markdown_text("wait\u2026"), "wait...")

    def test_ascii_passthrough(self):
        self.assertEqual(sanitize_markdown_text("Hello World"), "Hello World")

    def test_multiple_replacements(self):
        text = "\u201c\u2018Test\u2019\u201d"
        expected = "\"'Test'\""
        self.assertEqual(sanitize_markdown_text(text), expected)

    def test_empty_string(self):
        self.assertEqual(sanitize_markdown_text(""), "")


class TestUtilityFunctions(unittest.TestCase):
    """Test format_toc, format_wide_content, format_footnote."""

    def test_toc_snippet(self):
        result = format_toc()
        self.assertIn("{{toc}}", result)

    def test_wide_content(self):
        result = format_wide_content("# Wide Title\n\nContent here.")
        self.assertIn("# Wide Title", result)
        self.assertIn("{{wide", result)

    def test_footnote(self):
        result = format_footnote("Chapter 1 | The Beginning")
        self.assertIn("footnote", result)
        self.assertIn("Chapter 1 | The Beginning", result)


class TestCoverPageSnippetIntegration(unittest.TestCase):
    """Verify cover page helper uses correct snippets."""

    def test_format_cover_page_uses_front_cover(self):
        result = format_cover_page("A", "B", "c.jpg")
        self.assertIn("{{frontCover}}", result)

    def test_format_cover_page_uses_banner(self):
        result = format_cover_page("A", "B", "c.jpg")
        self.assertIn("{{banner HOMEBREW}}", result)

    def test_format_cover_page_uses_pagenumber(self):
        result = format_cover_page("A", "B", "c.jpg")
        self.assertIn("{{pageNumber,auto}}", result)


class TestMonsterStatBlockEdgeCases(unittest.TestCase):
    """Edge cases for stat block formatting."""

    def test_minimal_statblock(self):
        result = format_monster_statblock(name="Slime")
        self.assertIn("> ### Slime", result)
        self.assertIn("10 (+0)", result)

    def test_high_ability_scores(self):
        result = format_monster_statblock(name="Dragon", strength=30, charisma=28)
        self.assertIn("30 (+10)", result)
        self.assertIn("28 (+9)", result)

    def test_negative_ability_mods(self):
        result = format_monster_statblock(name="Weak", strength=1, dexterity=2)
        self.assertIn("1 (-5)", result)
        self.assertIn("2 (-4)", result)


class TestPageBreakAndColumn(unittest.TestCase):
    """Test PAGE_BREAK and COLUMN_BREAK constants."""

    def test_page_break_starts_with_backslash(self):
        self.assertTrue(PAGE_BREAK.strip().startswith("\\page"))

    def test_page_break_contains_page_number(self):
        self.assertIn("pageNumber,auto", PAGE_BREAK)

    def test_column_break_is_column(self):
        self.assertTrue(COLUMN_BREAK.strip().startswith("\\column"))


if __name__ == "__main__":
    unittest.main()
