# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for filtered, deterministic M1 sketches."""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.m1 import render_m1_sketch


class MappingPilotM1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, _hashes = load_verified_fixtures()

    def _render(self, layout: dict, perceived_ids=None) -> str:
        return render_m1_sketch(
            layout,
            current_location_id=layout["location_ids"][0],
            active_actor_id="Acheron",
            party_known_ids=frozenset(layout["location_ids"]),
            perceived_ids=perceived_ids,
        )

    def test_all_frozen_fixtures_are_deterministic_ascii_schematics(self) -> None:
        for fixture in self.fixtures.values():
            with self.subTest(fixture=fixture["fixture_id"]):
                first = self._render(fixture)
                self.assertEqual(first, self._render(copy.deepcopy(fixture)))
                self.assertTrue(first.startswith("Schematic (not to scale):"))
                first.encode("ascii")

    def test_hidden_features_and_exits_do_not_leak(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        hidden_name = "SECRET_HIDDEN_ANCHOR_SENTINEL"
        fixture["locations"][0]["features"].append({
            "feature_id": "SECRET_HIDDEN_FEATURE",
            "name": hidden_name,
            "position": "north",
            "perceivable": False,
        })
        fixture["locations"][0]["exits"].append({
            "exit_id": "SECRET_HIDDEN_EXIT",
            "feature_id": "SECRET_HIDDEN_FEATURE",
            "side": "north",
            "state": "open",
            "known_destination_location_id": None,
            "destination_knowledge": "unknown",
            "perceivable": False,
        })
        sketch = self._render(fixture, perceived_ids=frozenset())
        self.assertNotIn(hidden_name, sketch)
        self.assertNotIn("SECRET_HIDDEN", sketch)
        self.assertNotIn("Exit", sketch)

    def test_validated_synthetic_d1_layout_renders_only_projected_facts(self) -> None:
        layout = {
            "layout_type": "locations",
            "fixture_id": "Module_A:LOC01",
            "locations": [{
                "location_id": "LOC01",
                "name": "Room One",
                "orientation": {"position_semantics": "schematic"},
                "features": [{
                    "feature_id": "FEATURE_ONE",
                    "name": "Old arch",
                    "position": "north",
                    "reachable": True,
                }],
                "exits": [{
                    "exit_id": "EXIT_ONE",
                    "feature_id": "FEATURE_ONE",
                    "side": "east",
                    "state": "open",
                    "known_destination_location_id": None,
                    "destination_knowledge": "unknown",
                }],
                "npc_anchors": [],
                "perceivable_facts": [],
                "hidden_facts": ["SECRET_HIDDEN_FACT_SENTINEL"],
            }],
            "authored_distances": [],
        }
        first = render_m1_sketch(
            layout,
            current_location_id="LOC01",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"LOC01"}),
        )
        self.assertEqual(first, render_m1_sketch(
            layout,
            current_location_id="LOC01",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"LOC01"}),
        ))
        self.assertIn("Old arch", first)
        self.assertIn("schematic", first.lower())
        self.assertNotIn("SECRET_HIDDEN", first)
        self.assertNotIn("EXIT_ONE", first)
        self.assertNotIn("distance", first.lower())

    def test_unknown_destination_is_not_named_and_invalid_layout_is_rejected(self) -> None:
        layout = copy.deepcopy(self.fixtures["landscape_village"])
        layout["locations"][0]["exits"][0]["known_destination_location_id"] = None
        sketch = self._render(layout)
        self.assertNotIn("MPV2_LOC_", sketch)
        invalid = copy.deepcopy(layout)
        invalid["locations"][0]["features"][0].pop("name", None)
        with self.assertRaises(ValueError):
            self._render(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
