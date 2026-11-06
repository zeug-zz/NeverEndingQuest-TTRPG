#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regressions for the main-loop DM Note connectivity fallback.

Covers the NameError where ``main_game_loop`` referenced ``packet_location``
(defined only in the validator scope) for any location without same-area
connectivity, and the packet-adjacency fallback for 1-PC and 4-PC parties.
"""

import ast
import os
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(PROJECT_ROOT, "main.py")


def _function_node(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("function not found: %s" % name)


def _party_tracker(members):
    return {
        "module": "Fixture_Module",
        "partyMembers": list(members),
        "activeCharacter": members[0],
        "worldConditions": {
            "currentAreaId": "FX01",
            "currentArea": "Fixture Area",
            "currentLocationId": "L01",
            "currentLocation": "Lonely Hill",
        },
    }


PARTIES = (["Acheron"], ["Acheron", "Merisiel", "Kira", "Vitreol"])


class TestMainLocationConnectivityNoteFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MAIN_PATH, "r", encoding="utf-8") as handle:
            cls.main_source = handle.read()
        cls.tree = ast.parse(cls.main_source)

    def test_connectivity_fallback_uses_note_scoped_location_id(self):
        self.assertIn('current_location_id_note = world_conditions["currentLocationId"]', self.main_source)
        self.assertIn('loc.get("locationId") == current_location_id_note', self.main_source)

    def test_main_game_loop_has_no_unbound_packet_location(self):
        loop = _function_node(self.tree, "main_game_loop")
        assigned = {
            target.id
            for node in ast.walk(loop)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        loaded = {
            node.id
            for node in ast.walk(loop)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        module_names = {
            node.name for node in self.tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        for name in ("packet_location", "packet_topology", "packet_world"):
            if name in loaded:
                self.assertTrue(name in assigned or name in module_names, name)

    def test_authored_connectivity_wins_without_building_packet(self):
        import main

        with mock.patch.object(main, "build_authoritative_state_packet") as builder:
            ids = main._resolve_dm_note_connected_ids(
                {"locationId": "L01", "connectivity": ["L02", "", 7, "L03"]},
                _party_tracker(["Acheron"]),
                {"locations": []},
            )
        self.assertEqual(ids, ["L02", "L03"])
        builder.assert_not_called()

    def test_empty_connectivity_falls_back_to_packet_adjacency_for_1pc_and_4pc(self):
        import main

        location = {"locationId": "L01", "name": "Lonely Hill", "connectivity": []}
        area = {"areaId": "FX01", "locations": [location]}
        packet = {"location": {"adjacent_location_ids": ["FX02-L01", None, "FX02-L02"]}}
        for members in PARTIES:
            with self.subTest(party_size=len(members)):
                tracker = _party_tracker(members)
                with mock.patch.object(main, "build_authoritative_state_packet", return_value=packet) as builder:
                    ids = main._resolve_dm_note_connected_ids(location, tracker, area)
                self.assertEqual(ids, ["FX02-L01", "FX02-L02"])
                args, kwargs = builder.call_args
                self.assertIs(args[0], tracker)
                self.assertIs(kwargs["area_data"], area)
                self.assertIs(kwargs["location_data"], location)

    def test_isolated_location_without_any_adjacency_returns_empty_list(self):
        import main

        for members in PARTIES:
            for packet in ({}, {"location": None}, {"location": {"adjacent_location_ids": "bad"}}):
                with self.subTest(party_size=len(members), packet=packet):
                    with mock.patch.object(main, "build_authoritative_state_packet", return_value=packet):
                        ids = main._resolve_dm_note_connected_ids({}, _party_tracker(members), None)
                    self.assertEqual(ids, [])

    def test_real_packet_builder_on_isolated_location_does_not_raise(self):
        import main

        location = {"locationId": "L01", "name": "Lonely Hill", "connectivity": []}
        area = {"areaId": "FX01", "locations": [location]}
        for members in PARTIES:
            with self.subTest(party_size=len(members)):
                ids = main._resolve_dm_note_connected_ids(location, _party_tracker(members), area)
                self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
