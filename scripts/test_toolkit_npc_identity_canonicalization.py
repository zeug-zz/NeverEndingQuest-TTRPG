#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Toolkit NPC Identity Canonicalization Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.npc_identity import (
    build_npc_asset_payload,
    canonicalize_npc_identity,
    get_npc_compendium_lookup_keys,
    merge_npc_identity_metadata,
)


WEB_INTERFACE = REPO_ROOT / "web" / "web_interface.py"
LLM_CLASSIFICATION = REPO_ROOT / "web" / "extensions" / "toolkit_llm_classification.py"


class TestNPCIdentityCanonicalization(unittest.TestCase):
    def test_numillian_appositive_labels_canonicalize_to_short_slugs(self) -> None:
        examples = {
            "Arannis, vault scholar and alarmed archivist": (
                "Arannis",
                "arannis",
                "vault scholar and alarmed archivist",
            ),
            "Elaris, a diplomat of the Secrecy Council": (
                "Elaris",
                "elaris",
                "a diplomat of the Secrecy Council",
            ),
            "Ilyra, wardkeeper adjudicator": (
                "Ilyra",
                "ilyra",
                "wardkeeper adjudicator",
            ),
            "Kobe, the life at the center of the crisis": (
                "Kobe",
                "kobe",
                "the life at the center of the crisis",
            ),
            "Letharel, the silent border warden": (
                "Letharel",
                "letharel",
                "the silent border warden",
            ),
        }

        for label, expected in examples.items():
            with self.subTest(label=label):
                identity = canonicalize_npc_identity(label)
                self.assertEqual(identity.canonical_name, expected[0])
                self.assertEqual(identity.slug, expected[1])
                self.assertEqual(identity.role_hint, expected[2])
                self.assertNotIn("and", identity.slug)
                self.assertNotIn(",", identity.slug)

    def test_variant_labels_collapse_to_same_identity_slug(self) -> None:
        variants = [
            "Kobe, a guarded resident tied to the vault",
            "Kobe, endangered key witness",
            "Kobe, guarded resident tied to the vault",
        ]

        slugs = {canonicalize_npc_identity(label).slug for label in variants}
        self.assertEqual(slugs, {"kobe"})

    def test_metadata_merge_preserves_source_label_and_role_hint(self) -> None:
        identity = canonicalize_npc_identity(
            "Arannis, vault scholar and alarmed archivist",
            fallback_id="arannis,_vault_scholar_and_alarmed_archivist",
        )
        entry = merge_npc_identity_metadata({"description": "A scholar."}, identity)

        self.assertEqual(entry["name"], "Arannis")
        self.assertEqual(entry["source_label"], "Arannis, vault scholar and alarmed archivist")
        self.assertEqual(entry["source_id"], "arannis,_vault_scholar_and_alarmed_archivist")
        self.assertEqual(entry["role_hint"], "vault scholar and alarmed archivist")
        self.assertIn("Arannis, vault scholar and alarmed archivist", entry["source_labels"])
        self.assertIn("arannis,_vault_scholar_and_alarmed_archivist", entry["source_ids"])
        self.assertIn("vault scholar and alarmed archivist", entry["role_hints"])

    def test_asset_payload_uses_canonical_slug(self) -> None:
        identity = canonicalize_npc_identity("Letharel, divided border warden")
        payload = build_npc_asset_payload(identity)

        self.assertEqual(payload["id"], "letharel")
        self.assertEqual(payload["name"], "Letharel")
        self.assertEqual(payload["type"], "npc")
        self.assertEqual(payload["role_hint"], "divided border warden")

    def test_legacy_lookup_keys_include_canonical_and_legacy_forms(self) -> None:
        keys = get_npc_compendium_lookup_keys(
            "arannis,_vault_scholar_and_alarmed_archivist",
            "Arannis, vault scholar and alarmed archivist",
        )

        self.assertEqual(keys[0], "arannis")
        self.assertIn("arannis_vault_scholar_and_alarmed_archivist", keys)
        self.assertIn("arannis,_vault_scholar_and_alarmed_archivist", keys)


class TestToolkitSourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.web_source = WEB_INTERFACE.read_text(encoding="utf-8")
        cls.classification_source = LLM_CLASSIFICATION.read_text(encoding="utf-8")

    def test_web_interface_imports_identity_helper(self) -> None:
        self.assertIn("from utils.npc_identity import (", self.web_source)
        self.assertIn("canonicalize_npc_identity", self.web_source)
        self.assertIn("merge_npc_identity_metadata", self.web_source)

    def test_toolkit_routes_use_canonical_asset_payloads(self) -> None:
        self.assertGreaterEqual(self.web_source.count("build_npc_asset_payload(identity)"), 2)
        self.assertIn("npcs[identity.slug] = build_npc_asset_payload(identity)", self.web_source)
        self.assertIn("npcs_found[identity.slug] = build_npc_asset_payload(identity)", self.web_source)

    def test_compendium_writes_merge_identity_metadata(self) -> None:
        self.assertGreaterEqual(self.web_source.count("merge_npc_identity_metadata"), 6)
        self.assertIn("compendium_data['npcs'][asset_id] = merge_npc_identity_metadata", self.web_source)
        self.assertIn("npc_compendium['npcs'][npc_id] = merge_npc_identity_metadata", self.web_source)

    def test_legacy_lookup_keys_used_for_description_reads(self) -> None:
        self.assertGreaterEqual(self.web_source.count("get_npc_compendium_lookup_keys"), 4)
        self.assertIn("for lookup_id in get_npc_compendium_lookup_keys(npc_id):", self.web_source)
        self.assertIn("for lookup_id in lookup_ids:", self.web_source)

    def test_runtime_npc_paths_no_longer_use_naive_label_slugging(self) -> None:
        runtime_source = self._strip_triple_quoted_blocks(self.web_source)
        forbidden_patterns = [
            "npc_id = npc['name'].lower().replace(' ', '_').replace(\"'\", \"\")",
            "npc_id = npc_name.lower().replace(' ', '_').replace(\"'\", \"\").replace(\"-\", \"_\")",
            "npc_id = npc_name.lower().replace(' ', '_').replace(\"'\", \"\")",
        ]
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, runtime_source)

    def test_monster_bestiary_normalization_left_unchanged(self) -> None:
        expected = 'return raw.lower().strip().replace(" ", "_")'
        self.assertIn(expected, self.classification_source)

    @staticmethod
    def _strip_triple_quoted_blocks(source: str) -> str:
        return re.sub(r'(?s)(""".*?"""|\'\'\'.*?\'\'\')', '', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
