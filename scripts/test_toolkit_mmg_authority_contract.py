# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Contracts for toolkit MMG monster-authority collision fix.

This suite verifies the final model:
- Same-slug monster-authoritative actors are emitted as MONSTER assets only.
- Duplicate NPC asset rows are suppressed for those slugs.
- True NPCs remain normal NPC assets.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


MONSTER_AUTHORITY_SLUGS = {
    "bandit_captain_gorvek",
    "corrupted_ranger_thane",
    "malarok_the_corruptor",
}


class TestMMGAuthoritySourceContracts(unittest.TestCase):
    """Source-level regression guards for authority suppression."""

    def setUp(self):
        self.web_interface = Path("web/web_interface.py").read_text(encoding="utf-8")
        self.report_module = Path("utils/module_media_generator_report.py").read_text(
            encoding="utf-8"
        )

    def test_unified_assets_uses_monster_authority_filter(self):
        self.assertIn("monster_authority_slugs", self.web_interface)
        self.assertIn("if npc_id in monster_authority_slugs", self.web_interface)
        self.assertIn("suppressed_npc_slugs", self.web_interface)

    def test_unified_assets_no_longer_assigns_media_authority_for_duplicates(self):
        self.assertNotIn("npcs[npc_id]['media_authority']", self.web_interface)

    def test_generation_path_skips_stale_npc_payloads_by_authority(self):
        self.assertIn("generation_monster_authority", self.web_interface)
        self.assertIn("slug is monster-authoritative", self.web_interface)

    def test_report_collapses_same_slug_npc_monster_rows(self):
        self.assertIn("grouped_by_slug", self.report_module)
        self.assertIn("monster_rows", self.report_module)
        self.assertIn("asset_audits = canonical_audits", self.report_module)


class TestMMGAuthorityBehaviorContracts(unittest.TestCase):
    """Behavioral checks against live endpoint/report artifacts."""

    def _get_unified_assets(self):
        from web.web_interface import app

        with app.test_client() as client:
            response = client.get(
                "/api/toolkit/modules/The_Thornwood_Watch/unified-assets"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload.get("success"))
            return payload.get("assets", [])

    def test_monster_authority_slugs_emitted_as_monster_only(self):
        assets = self._get_unified_assets()

        for slug in MONSTER_AUTHORITY_SLUGS:
            matching = [a for a in assets if a.get("id") == slug]
            self.assertEqual(
                len(matching),
                1,
                f"Expected exactly one asset row for {slug}, found {len(matching)}",
            )
            self.assertEqual(
                matching[0].get("type"),
                "monster",
                f"Expected {slug} as monster asset authority",
            )

    def test_true_npc_remains_npc_asset(self):
        assets = self._get_unified_assets()
        matching = [a for a in assets if a.get("id") == "wounded_ranger_gareth"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].get("type"), "npc")

    def test_scene_follower_thane_remains_monster_entity_type(self):
        follower_path = Path("data/runtime/scene_followers.json")
        self.assertTrue(follower_path.exists())
        with open(follower_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        followers = payload.get("followers", [])
        thane = [f for f in followers if f.get("entity_id") == "corrupted_ranger_thane"]
        self.assertEqual(len(thane), 1)
        self.assertEqual(thane[0].get("entity_type"), "monster")

    def test_report_has_no_duplicate_npc_rows_for_monster_authority(self):
        report_path = Path("modules/The_Thornwood_Watch/module_media_generator_report.json")
        self.assertTrue(report_path.exists())
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)

        audits = report.get("asset_audits", [])
        for slug in MONSTER_AUTHORITY_SLUGS:
            matching = [a for a in audits if a.get("id") == slug]
            self.assertEqual(
                len(matching),
                1,
                f"Report should contain one canonical row for {slug}",
            )
            self.assertEqual(matching[0].get("type"), "monster")


if __name__ == "__main__":
    unittest.main()
