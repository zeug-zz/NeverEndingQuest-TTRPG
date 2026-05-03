# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Source and schema contract tests for PC supernatural state layer."""

import json
import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class TestSupernaturalSchemaContracts(unittest.TestCase):
    def test_character_schema_has_supernatural_fields(self):
        schema_path = os.path.join(REPO_ROOT, "schemas", "char_schema.json")
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

        properties = schema.get("properties", {})
        self.assertIn("creatureTypes", properties)
        self.assertIn("supernaturalStates", properties)

        state_props = properties["supernaturalStates"]["items"]["properties"]
        self.assertIn("id", state_props)
        self.assertIn("label", state_props)
        self.assertIn("category", state_props)
        self.assertIn("source", state_props)
        self.assertIn("playable", state_props)
        self.assertIn("mechanicalEffects", state_props)
        self.assertIn("narrativeEffects", state_props)


class TestSupernaturalProjectionContracts(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
            return handle.read()

    def test_dm_note_projects_supernatural_summary(self):
        content = self._read("utils/multi_pc_dm_note.py")
        self.assertIn("get_supernatural_state_summary", content)
        self.assertIn("Supernatural:", content)
        self.assertIn("Supra:", content)

    def test_conversation_context_projects_supernatural_summary(self):
        content = self._read("core/ai/conversation_utils.py")
        self.assertIn("get_supernatural_state_summary", content)
        self.assertIn("SUPERNATURAL:", content)

    def test_combat_context_projects_supernatural_summary(self):
        content = self._read("core/managers/combat_manager.py")
        self.assertIn("get_supernatural_state_summary", content)
        self.assertIn("SUPERNATURAL:", content)
        self.assertIn("supernaturalStates", content)

    def test_character_sheet_ui_projects_supernatural_state(self):
        content = self._read("web/templates/game_interface.html")
        self.assertIn("Supernatural State", content)
        self.assertIn("data.supernaturalStates", content)
        self.assertIn("data.creatureTypes", content)

    def test_pdf_route_projects_supernatural_summary(self):
        content = self._read("web/routes/character_sheet_routes.py")
        self.assertIn("get_supernatural_state_summary", content)
        self.assertIn("Supernatural:", content)

    def test_character_sheet_compressor_projects_supernatural_tokens(self):
        content = self._read("core/ai/character_sheet_compressor.py")
        self.assertIn("CREATURE_TYPES=", content)
        self.assertIn("SUPERNATURAL=", content)


class TestResurrectionContracts(unittest.TestCase):
    def test_resurrection_action_supports_undead_mode(self):
        content = self._read_action_handler()
        self.assertIn("undead_resurrection", content)

    def test_resurrection_no_private_supernatural_metadata_write(self):
        content = self._read_action_handler()
        self.assertNotIn("updated_data[\"_supernatural_metadata\"]", content)

    def _read_action_handler(self) -> str:
        with open(os.path.join(REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as handle:
            return handle.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
