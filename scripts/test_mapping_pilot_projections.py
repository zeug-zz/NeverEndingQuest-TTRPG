# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for deterministic mapping-pilot packet projections."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.knowledge import filter_layout_for_viewpoint
from scripts.mapping_pilot.projections import (
    SHARED_INSTRUCTION,
    packet_hash,
    relationship_statements,
    render_packet,
)


class MappingPilotProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, _hashes = load_verified_fixtures()

    def _project(self, fixture: dict, perceived_ids=None) -> dict:
        return filter_layout_for_viewpoint(
            fixture,
            current_location_id=fixture["location_ids"][0],
            active_actor_id="Acheron",
            party_known_ids=frozenset(fixture["location_ids"]),
            perceived_ids=perceived_ids,
        )

    def test_all_frozen_fixtures_have_semantically_identical_b_and_d_statements(self) -> None:
        for fixture in self.fixtures.values():
            with self.subTest(fixture=fixture["fixture_id"]):
                projection = self._project(fixture)
                b_packet = render_packet(projection, "B")
                d_packet = render_packet(projection, "D")
                statements = relationship_statements(projection)
                self.assertEqual(b_packet, "\n\n".join(("Relationships:", *statements, SHARED_INSTRUCTION)))
                self.assertTrue(d_packet.startswith("Schematic (not to scale):\n"))
                self.assertTrue(d_packet.endswith("\n\n" + b_packet))
                self.assertEqual(b_packet.count(SHARED_INSTRUCTION), 1)
                self.assertEqual(d_packet.count(SHARED_INSTRUCTION), 1)
                self.assertEqual(render_packet(projection, "B").encode("ascii"), b_packet.encode("ascii"))
                self.assertEqual(render_packet(projection, "D").encode("ascii"), d_packet.encode("ascii"))
                self.assertEqual(packet_hash(b_packet), hashlib.sha256(b_packet.encode("ascii")).hexdigest())
                self.assertEqual(packet_hash(d_packet), hashlib.sha256(d_packet.encode("ascii")).hexdigest())

    def test_exact_instruction_and_no_ids_or_unfiltered_facts(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        fixture.setdefault("hidden_facts", []).append("SECRET_HIDDEN_SENTINEL")
        projection = self._project(fixture, perceived_ids=frozenset({"MPV2_F_TAVERN_FRONT_DOOR"}))
        b_packet = render_packet(projection, "B")
        d_packet = render_packet(projection, "D")
        self.assertIn(SHARED_INSTRUCTION, b_packet)
        self.assertIn(SHARED_INSTRUCTION, d_packet)
        self.assertNotIn("MPV2_", b_packet + d_packet)
        self.assertNotIn("SECRET_HIDDEN_SENTINEL", b_packet + d_packet)
        self.assertNotIn("{", b_packet + d_packet)
        self.assertNotIn("}", b_packet + d_packet)
        self.assertNotIn("JSON", b_packet + d_packet)

    def test_unknown_destinations_and_unreachable_landmarks_are_explicit_and_separate(self) -> None:
        fixture = copy.deepcopy(self.fixtures["landscape_village"])
        projection = self._project(fixture)
        projection["known_location_names"] = {
            "MPV2_LOC_SECRET": "Hidden fallback name must not appear"
        }
        packet = render_packet(projection, "B")
        self.assertIn("destination unknown", packet)
        self.assertIn("Visible but unreachable landmark:", packet)
        self.assertIn("Omitted facts are unknown", packet)
        self.assertNotIn("Hidden fallback name", packet)

    def test_filtered_safe_location_names_survive_without_emitting_ids(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        projection = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"MPV2_LOC_TAVERN", "MPV2_LOC_VILLAGE_GREEN"}),
        )
        projection["known_location_names"] = {
            "MPV2_LOC_VILLAGE_GREEN": "Rillford Village Green"
        }
        packet = render_packet(projection, "B")
        self.assertIn("destination Rillford Village Green", packet)
        self.assertNotIn("MPV2_LOC_VILLAGE_GREEN", packet)

    def test_origin_facing_and_recent_movement_are_rendered(self) -> None:
        fixture = copy.deepcopy(self.fixtures["transition_tower_approach"])
        projection = self._project(fixture)
        projection["recent_movement"] = {
            "from_location_id": "MPV2_LOC_VILLAGE_GREEN",
            "to_location_id": "MPV2_LOC_TOWER_APPROACH",
            "from_name": "Rillford Village Green",
        }
        packet = render_packet(projection, "B")
        self.assertIn("Schematic origin:", packet)
        self.assertTrue("Entry facing:" in packet or "North:" in packet)
        self.assertIn("recently moved", packet)
        self.assertIn("from Rillford Village Green", packet)
        self.assertNotIn("MPV2_LOC_", packet)

    def test_combat_schematic_uses_directions_and_authored_balcony_label(self) -> None:
        projection = self._project(self.fixtures["combat_stage_tavern_zones"])
        packet = render_packet(projection, "D")
        self.assertIn("Schematic (not to scale)", packet)
        self.assertIn("Kitchen door", packet)
        self.assertIn("Stone hearth", packet)
        self.assertIn("Upper balcony and rail", packet)
        self.assertIn("upper east", packet)
        self.assertIn("northwest", packet)
        self.assertIn("Upper level (elevation; layout unspecified):", packet)
        self.assertIn("Upper balcony and rail at upper level east", packet)
        schematic = packet.split("Relationships:", 1)[0]
        cardinal_grid = schematic.split("Upper level", 1)[0]
        self.assertNotIn("Upper balcony and rail", cardinal_grid)
        self.assertNotIn("Balcony zone", packet)
        self.assertNotIn("MPV2_Z_", packet)

    def test_hash_and_packet_are_independent_of_mapping_insertion_order(self) -> None:
        projection = self._project(self.fixtures["interior_tavern"])
        reordered = dict(reversed(list(projection.items())))
        for arm in ("B", "D"):
            first = render_packet(projection, arm)
            second = render_packet(reordered, arm)
            self.assertEqual(first.encode("ascii"), second.encode("ascii"))
            self.assertEqual(packet_hash(first), packet_hash(second))

    def test_non_ascii_text_is_rejected_and_arm_a_is_disabled(self) -> None:
        projection = self._project(self.fixtures["interior_tavern"])
        projection["feature_anchors"][0]["name"] = "cafe\N{LATIN SMALL LETTER E WITH ACUTE}"
        with self.assertRaisesRegex(ValueError, "non-ASCII"):
            render_packet(projection, "B")
        with self.assertRaisesRegex(ValueError, "B or D"):
            render_packet({}, "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
