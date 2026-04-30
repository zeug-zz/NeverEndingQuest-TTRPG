# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for MMG final report safe monster slug handling."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.module_media_generator_report import build_module_media_generator_report


class TestModuleMediaGeneratorReportSafeSlug(unittest.TestCase):
    """Ensure MMG report resolves punctuation-bearing monster IDs safely."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.module_slug = "Murder_at_the_Drowning_Lass"
        self.monster_media_dir = (
            self.repo_root / "modules" / self.module_slug / "media" / "monsters"
        )
        self.npc_media_dir = (
            self.repo_root / "modules" / self.module_slug / "media" / "npcs"
        )
        self.monster_media_dir.mkdir(parents=True, exist_ok=True)
        self.npc_media_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stale_will_o_wisp_asset_id_resolves_safe_media_files(self) -> None:
        (self.monster_media_dir / "will_o_wisp.jpg").write_bytes(b"jpg")
        (self.monster_media_dir / "will_o_wisp_thumb.jpg").write_bytes(b"thumb")

        report = build_module_media_generator_report(
            self.module_slug,
            assets=[
                {
                    "id": "will-o'-wisp",
                    "name": "Will-o'-Wisp",
                    "type": "monster",
                }
            ],
            project_root=self.repo_root,
        )

        self.assertEqual(report.get("status"), "pass")
        self.assertEqual(int(report.get("missing_count", -1)), 0)
        self.assertEqual(report.get("missing_assets"), [])

        asset_audits = report.get("asset_audits") or []
        self.assertEqual(len(asset_audits), 1)
        audit = asset_audits[0]
        self.assertEqual(audit.get("id"), "will_o_wisp")
        self.assertEqual(audit.get("name"), "Will-o'-Wisp")
        self.assertTrue(audit.get("has_image"))
        self.assertTrue(audit.get("has_thumbnail"))

    def test_monster_asset_id_normalization_collapses_multiple_underscores(self) -> None:
        (self.monster_media_dir / "will_o_wisp.jpg").write_bytes(b"jpg")
        (self.monster_media_dir / "will_o_wisp_thumb.jpg").write_bytes(b"thumb")

        report = build_module_media_generator_report(
            self.module_slug,
            assets=[
                {
                    "id": "Will-o'-Wisp",
                    "name": "Will-o'-Wisp",
                    "type": "monster",
                }
            ],
            project_root=self.repo_root,
        )

        audit = (report.get("asset_audits") or [{}])[0]
        self.assertEqual(audit.get("id"), "will_o_wisp")
        self.assertTrue(audit.get("has_image"))
        self.assertTrue(audit.get("has_thumbnail"))

    def test_npc_asset_id_is_not_monster_normalized(self) -> None:
        (self.npc_media_dir / "maela_kett.jpg").write_bytes(b"jpg")
        (self.npc_media_dir / "maela_kett_thumb.jpg").write_bytes(b"thumb")

        report = build_module_media_generator_report(
            self.module_slug,
            assets=[
                {
                    "id": "maela_kett",
                    "name": "Maela Kett",
                    "type": "npc",
                }
            ],
            project_root=self.repo_root,
        )

        audit = (report.get("asset_audits") or [{}])[0]
        self.assertEqual(audit.get("id"), "maela_kett")
        self.assertTrue(audit.get("has_image"))
        self.assertTrue(audit.get("has_thumbnail"))


if __name__ == "__main__":
    unittest.main()
