# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Contracts for toolkit MMG creature/NPC authority resolution.

This suite verifies the final model:
- Same-slug monster-authoritative actors are emitted as MONSTER assets only.
- Weak creature-derived monster candidates do not suppress authored NPC rows.
- The MMG helper stays module-local and does not read runtime party state.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.module_media_generator_report import build_module_media_generator_report
from utils.module_mmg_authority import (
    build_module_mmg_assets,
    canonicalize_module_mmg_asset_audits,
)


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
        self.helper_module = Path("utils/module_mmg_authority.py").read_text(
            encoding="utf-8"
        )

    def test_unified_assets_uses_module_mmg_helper(self):
        self.assertIn("build_module_mmg_assets", self.web_interface)
        self.assertIn("suppressed_npc_slugs", self.web_interface)

    def test_helper_is_module_local(self):
        self.assertNotIn("open(\"party_tracker.json\"", self.helper_module)
        self.assertNotIn("open('party_tracker.json'", self.helper_module)
        self.assertIn("module_context_BU.json", self.helper_module)

    def test_generation_path_skips_stale_npc_payloads_by_authority(self):
        self.assertIn("explicit_monster_authority_slugs", self.web_interface)
        self.assertIn("slug is monster-authoritative", self.web_interface)

    def test_report_uses_shared_canonicalizer(self):
        self.assertIn("canonicalize_module_mmg_asset_audits", self.report_module)


class TestMMGAuthorityBehaviorContracts(unittest.TestCase):
    """Behavioral checks against live endpoint/report artifacts."""

    def _get_unified_assets(self, module_name: str):
        from web.web_interface import app

        with app.test_client() as client:
            response = client.get(f"/api/toolkit/modules/{module_name}/unified-assets")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload.get("success"))
            return payload.get("assets", [])

    def test_monster_authority_slugs_emitted_as_monster_only(self):
        assets = self._get_unified_assets("The_Thornwood_Watch")

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
            self.assertEqual(matching[0].get("authority_role"), "explicit_monster")

    def test_true_npc_remains_npc_asset(self):
        assets = self._get_unified_assets("The_Thornwood_Watch")
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

    def test_night_weak_creatures_keep_npc_rows(self):
        assets = self._get_unified_assets("Night_of_the_Restless_Dead")

        for slug in {"ma", "blarg", "red"}:
            matching = [a for a in assets if a.get("id") == slug]
            self.assertEqual(len(matching), 1, f"Expected one row for {slug}")
            self.assertEqual(matching[0].get("type"), "npc")
            self.assertEqual(matching[0].get("authority_role"), "npc")

        for slug in {"crawling_claw", "zombie", "undead_giant_spider", "cultist", "skeleton"}:
            matching = [a for a in assets if a.get("id") == slug]
            self.assertTrue(matching, f"Expected monster row for {slug}")
            self.assertEqual(matching[0].get("type"), "monster")

    def test_report_mirrors_endpoint_authority(self):
        assets = self._get_unified_assets("Night_of_the_Restless_Dead")
        report = build_module_media_generator_report(
            "Night_of_the_Restless_Dead",
            assets=assets,
        )
        audits = report.get("asset_audits", [])
        canonical = canonicalize_module_mmg_asset_audits(audits)
        self.assertEqual(len(audits), len(canonical))

        for slug in {"ma", "blarg", "red"}:
            matching = [a for a in audits if a.get("id") == slug]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].get("type"), "npc")

        for slug in {"crawling_claw", "zombie", "undead_giant_spider", "cultist", "skeleton"}:
            matching = [a for a in audits if a.get("id") == slug]
            self.assertTrue(matching)
            self.assertEqual(matching[0].get("type"), "monster")

    def test_canonicalizer_prefers_npc_over_weak_and_monster_over_npc(self):
        audits = canonicalize_module_mmg_asset_audits(
            [
                {"id": "blarg", "type": "monster", "authority_role": "weak_monster"},
                {"id": "blarg", "type": "npc", "authority_role": "npc"},
                {
                    "id": "corrupted_ranger_thane",
                    "type": "npc",
                    "authority_role": "npc",
                },
                {
                    "id": "corrupted_ranger_thane",
                    "type": "monster",
                    "authority_role": "explicit_monster",
                },
            ]
        )
        by_slug = {row["id"]: row for row in audits}
        self.assertEqual(by_slug["blarg"]["type"], "npc")
        self.assertEqual(by_slug["corrupted_ranger_thane"]["type"], "monster")

    def test_night_endpoint_omits_duplicate_monster_rows_for_npc_authority(self):
        assets = self._get_unified_assets("Night_of_the_Restless_Dead")
        for slug in {"ma", "blarg", "red"}:
            self.assertEqual(len([a for a in assets if a.get("id") == slug]), 1)

        for slug in {"crawling_claw", "cultist", "skeleton", "undead_giant_spider", "zombie"}:
            matching = [a for a in assets if a.get("id") == slug]
            self.assertTrue(matching, f"Expected weak monster row for {slug}")
            self.assertEqual(matching[0].get("type"), "monster")


if __name__ == "__main__":
    unittest.main()
