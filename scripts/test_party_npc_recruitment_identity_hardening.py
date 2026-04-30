#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for party NPC recruitment identity hardening."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import action_handler  # noqa: E402


class _FakePathManager:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def get_character_path(self, name: str) -> str:
        normalized = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
        normalized = normalized.replace("'", "_")
        return os.path.join(self.base_dir, f"{normalized}.json")


class _FakeModuleResolution:
    def __init__(self, status: str, canonical_name: str = ""):
        self.status = status
        self.canonical_name = canonical_name


class TestPartyNpcRecruitmentIdentityHardening(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = self.tempdir.name
        self.saved_payloads = []

    def tearDown(self):
        self.tempdir.cleanup()

    def _write_character_file(self, stem: str, name: str) -> None:
        path = os.path.join(self.base_dir, f"{stem}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"name": name, "class": "NPC", "level": 3}, handle)

    def _capture_save(self, payload, path):
        self.saved_payloads.append({"path": path, "payload": json.loads(json.dumps(payload))})

    def test_module_recruit_keeps_canonical_display_name_and_metadata(self):
        self._write_character_file("thorn_touched_dryad_sylara", "Dryad Sylara")

        party_tracker = {
            "module": "The_Thornwood_Watch",
            "worldConditions": {"currentLocationId": "RO01"},
            "partyMembers": ["Acheron"],
            "partyNPCs": [],
        }

        with (
            patch.object(action_handler, "ModulePathManager", lambda module_name: _FakePathManager(self.base_dir)),
            patch.object(action_handler, "safe_json_dump", self._capture_save),
            patch.object(action_handler.subprocess, "run", return_value=None),
            patch("utils.npc_arrival_validator.load_module_npc_names", return_value={"Thorn-Touched Dryad Sylara"}),
            patch("utils.npc_arrival_validator.resolve_npc_identity", return_value=_FakeModuleResolution("matched", "Thorn-Touched Dryad Sylara")),
        ):
            action_handler.update_party_npcs(
                party_tracker,
                "add",
                {"name": "Sylara", "role": "Guide"},
            )

        self.assertTrue(self.saved_payloads, "Recruitment should persist party tracker changes")
        entry = party_tracker["partyNPCs"][0]
        self.assertEqual(entry["name"], "Thorn-Touched Dryad Sylara")
        self.assertEqual(entry["source_module"], "The_Thornwood_Watch")
        self.assertEqual(entry["source_npc_name"], "Thorn-Touched Dryad Sylara")
        self.assertEqual(entry["source_entity_slug"], "thorn_touched_dryad_sylara")
        self.assertEqual(entry["recruited_from_location_id"], "RO01")
        self.assertEqual(entry["character_file_ref"], "thorn_touched_dryad_sylara")

    def test_exact_name_recruit_preserves_display_name_without_module_rename(self):
        self._write_character_file("river_guard", "River Guard")

        party_tracker = {
            "module": "",
            "worldConditions": {"currentLocationId": "RO01"},
            "partyMembers": ["Acheron"],
            "partyNPCs": [],
        }

        with (
            patch.object(action_handler, "ModulePathManager", lambda module_name: _FakePathManager(self.base_dir)),
            patch.object(action_handler, "safe_json_dump", self._capture_save),
            patch.object(action_handler.subprocess, "run", return_value=None),
            patch("utils.npc_arrival_validator.load_module_npc_names", return_value=set()),
            patch("utils.npc_arrival_validator.resolve_npc_identity", return_value=_FakeModuleResolution("unmatched", "")),
        ):
            action_handler.update_party_npcs(
                party_tracker,
                "add",
                {"name": "River Guard", "role": "Guard"},
            )

        self.assertTrue(self.saved_payloads, "Exact-name recruit should persist party tracker changes")
        entry = party_tracker["partyNPCs"][0]
        self.assertEqual(entry["name"], "River Guard")
        self.assertNotIn("source_module", entry)
        self.assertNotIn("source_npc_name", entry)
        self.assertNotIn("source_entity_slug", entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
