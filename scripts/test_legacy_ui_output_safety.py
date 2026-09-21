# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Provider-free source and runtime contract tests for legacy UI output safety.

The template is intentionally tested as source text. The small JavaScript
helper block is also executed with Node when available so escaping and JSON
attribute round-trips are covered without a browser or provider call.
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


TEMPLATE_PATH = os.path.join(REPO_ROOT, "web", "templates", "game_interface.html")


def _read_template() -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def _extract_function(source: str, name: str) -> str:
    pattern = rf"function {re.escape(name)}\([^)]*\) \{{.*?\n\s*\}}"
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        raise AssertionError(f"Could not extract JavaScript helper: {name}")
    return match.group(0)


def _run_node_helpers(source: str, values):
    helper_block = "\n\n".join(
        _extract_function(source, name)
        for name in ("escapeLegacyHtml", "legacyJsonAttribute")
    )
    harness = f"""
{helper_block}
const values = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const result = values.map((value) => ({{
  escaped: escapeLegacyHtml(value),
  attribute: legacyJsonAttribute(value),
}}));
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=REPO_ROOT,
        input=json.dumps(values),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


class TestLegacyHelperPresence(unittest.TestCase):
    """Both helpers remain in the template script scope."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_helpers_are_defined(self):
        self.assertRegex(self.source, r"function escapeLegacyHtml\(")
        self.assertRegex(self.source, r"function legacyJsonAttribute\(")


@unittest.skipUnless(shutil.which("node"), "node is unavailable")
class TestLegacyHelperBehavior(unittest.TestCase):
    """Exercise helper behavior without loading the complete browser script."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_ordinary_names_remain_readable(self):
        result = _run_node_helpers(self.source, ["Kira", "Blarg"])
        self.assertEqual([item["escaped"] for item in result], ["Kira", "Blarg"])

    def test_adversarial_text_is_entity_escaped(self):
        value = "\"'` & <script> onmouseover=alert(1) </script>"
        result = _run_node_helpers(self.source, [value])[0]
        escaped = result["escaped"]
        for entity in ("&quot;", "&#39;", "&#96;", "&amp;", "&lt;", "&gt;"):
            self.assertIn(entity, escaped)
        for raw in ('"', "'", "`", "<", ">"):
            self.assertNotIn(raw, escaped)
        self.assertIn("onmouseover=", escaped)

    def test_nullish_and_undefined_helper_contract(self):
        helper_block = "\n\n".join(
            _extract_function(self.source, name)
            for name in ("escapeLegacyHtml", "legacyJsonAttribute")
        )
        harness = f"""
{helper_block}
process.stdout.write(JSON.stringify({{
  nullEscaped: escapeLegacyHtml(null),
  undefinedEscaped: escapeLegacyHtml(undefined),
  undefinedAttribute: legacyJsonAttribute(undefined),
}}));
"""
        completed = subprocess.run(
            ["node", "-e", harness],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["nullEscaped"], "")
        self.assertEqual(result["undefinedEscaped"], "")
        self.assertEqual(result["undefinedAttribute"], "null")

    def test_json_attribute_round_trips_string_and_object(self):
        values = [
            "Ma's \"Ghost\" <watcher> & `echo`",
            {"name": "<script>", "quote": '" & \'', "nested": ["Kira"]},
        ]
        result = _run_node_helpers(self.source, values)
        for original, item in zip(values, result):
            self.assertNotIn('"', item["attribute"])
            decoded = html.unescape(item["attribute"])
            self.assertEqual(json.loads(decoded), original)


class TestCharacterSheetHandlerSerialization(unittest.TestCase):
    """Character-sheet inline handlers serialize normalized identity values."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_character_handlers_use_legacy_json_attribute(self):
        handlers = (
            "openReadinessRepairModal",
            "uploadPortrait",
            "createPortrait",
            "downloadPortrait",
            "openCharacterEdit",
            "downloadCharacterSheetPDF",
        )
        for handler in handlers:
            with self.subTest(handler=handler):
                self.assertRegex(
                    self.source,
                    rf"{handler}\([^\n]*legacyJsonAttribute\(normalizedName\)",
                )
        self.assertNotIn("'${normalizedName}'", self.source)


class TestNpcHandlerSerialization(unittest.TestCase):
    """NPC detail buttons serialize names and structured arguments."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_all_npc_handler_sites_serialize_arguments(self):
        calls = re.findall(r'onclick="(showNPC[^\"]+)"', self.source)
        self.assertEqual(len(calls), 7)
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("legacyJsonAttribute(npc.name)", call)
                self.assertGreaterEqual(call.count("legacyJsonAttribute("), 2)
        self.assertNotIn("'${npc.name}'", self.source)


class TestSaveArchiveSerialization(unittest.TestCase):
    """Save-folder and archive handlers keep serialized attribute payloads."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_save_and_archive_handlers_and_payloads_are_serialized(self):
        self.assertIn(
            "selectSaveGame(${legacyJsonAttribute(save.save_folder)}, this)",
            self.source,
        )
        self.assertIn(
            'data-save="${legacyJsonAttribute(save)}"',
            self.source,
        )
        self.assertIn(
            "selectArchiveZip(${legacyJsonAttribute(archive.zip_name)}, this)",
            self.source,
        )
        self.assertIn(
            'data-save="${legacyJsonAttribute(archiveData)}"',
            self.source,
        )


class TestLegacyEscapingBoundaries(unittest.TestCase):
    """Quote-only escaping is limited to the known helper internals."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_quote_replacements_are_inside_allowed_helpers(self):
        allowed = {
            "escapeMessageHtml",
            "escapeLegacyHtml",
            "escapeRepairHtml",
            "journalEscapeHtml",
        }
        matches = list(re.finditer(r"\.replace\(/\"/g, '&quot;'\)", self.source))
        self.assertGreaterEqual(len(matches), 4)
        function_starts = list(re.finditer(r"function\s+(\w+)\s*\(", self.source))
        for match in matches:
            prior = [item for item in function_starts if item.start() < match.start()]
            self.assertTrue(prior)
            self.assertIn(prior[-1].group(1), allowed)


class TestTabletopPortraitAndPartyStripContracts(unittest.TestCase):
    """Legacy TABLETOP MODE portrait and party-strip behavior stays intact."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_template()

    def test_tabletop_markers_and_portrait_slug_remain(self):
        self.assertIn("TABLETOP MODE:", self.source)
        self.assertRegex(self.source, r"function normalizePortraitSlug\(")
        self.assertIn("normalizePortraitSlug(data.name || '')", self.source)

    def test_party_strip_player_video_behavior_remains(self):
        for identifier in (
            "playerFullPortraitUrl",
            "member.type === 'player'",
            "isPartyCompanion",
            "videoCandidates",
            "showVideoPopup(item, firstVideo, true)",
        ):
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, self.source)
        self.assertIn("All member types use unified video-first path", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
