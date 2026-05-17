#!/usr/bin/env python3
"""Contract tests for normalized packet synthesis from source graph artifacts."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_homebrew_upload_contract import (
    build_normalized_packet_placeholder,
    validate_review_packet,
)
from utils.toolkit_source_graph_synthesis import (
    synthesize_normalized_packet,
)
from utils.toolkit_source_manifest import build_source_graph


NUMILLIAN_MD = """\
# Test Adventure

## Map Key

### 1. Brooksteps Inn
**Wayne** the innkeeper. A **hidden journal** behind the bar (DC 13 Perception).

### 2. Wizard's Tower
**Irene Laughing-Eyes** the cat wizard. Trapped floor tiles.

## NPC Table

| Name | Role |
|------|------|
| Wayne | Innkeeper |
| Irene Laughing-Eyes | Cat Wizard |
"""


class TestPacketSynthesis(unittest.TestCase):
    """Task 5.x: Packet synthesis from source graph artifacts."""

    def test_synthesis_produces_compatible_packet(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        identity_report = {
            "summary": {"total_canonical": 2, "total_ambiguous": 0},
            "canonical_identities": [
                {
                    "display_name": "Wayne",
                    "entity_type": "npc",
                    "criticality": "required",
                },
                {
                    "display_name": "Irene Laughing-Eyes",
                    "entity_type": "npc",
                    "criticality": "major",
                },
                {
                    "display_name": "Brooksteps Inn",
                    "entity_type": "location",
                    "criticality": "required",
                },
            ],
        }
        plot_topology = {
            "plot_beats": [],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }

        packet = synthesize_normalized_packet(
            source_graph, identity_report, plot_topology
        )
        self.assertIsInstance(packet, dict)
        self.assertIn("title", packet)
        self.assertIn("npc_seeds", packet)
        self.assertIn("locations", packet)
        self.assertGreaterEqual(len(packet["npc_seeds"]), 1)
        self.assertGreaterEqual(len(packet["locations"]), 1)

    def test_legacy_packet_review_validation(self):
        base = build_normalized_packet_placeholder(
            source_path=Path("test.md"),
            source_hash="abc123",
            preflight={"ready": False, "source_readable": True},
        )
        base["title"] = "Test"
        base["description"] = "A test."
        base["locations"] = [{"name": "Entry"}]
        base["npc_seeds"] = [{"name": "Guide", "role": "Ally"}]
        base["monster_refs"] = ["Skeleton"]
        base["packet_version"] = "v1"
        base["source_hash"] = "abc123"
        base["normalization_state"] = "normalized"

        ok, err = validate_review_packet(base)
        self.assertTrue(ok, msg=err)

    def test_synthesized_packet_is_review_valid(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        identity_report = {
            "summary": {"total_canonical": 3, "total_ambiguous": 0},
            "canonical_identities": [
                {
                    "display_name": "Wayne",
                    "entity_type": "npc",
                    "criticality": "required",
                },
                {
                    "display_name": "Brooksteps Inn",
                    "entity_type": "location",
                    "criticality": "required",
                },
            ],
        }
        plot_topology = {
            "plot_beats": [],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }

        packet = synthesize_normalized_packet(
            source_graph, identity_report, plot_topology,
            legacy_model_payload={
                "title": "Test Adventure",
                "description": "A test.",
                "locations": [],
                "npc_seeds": [],
                "monster_refs": [],
                "packet_version": "v1",
            },
        )
        packet["packet_version"] = "v1"
        packet["source_hash"] = "abc123"
        packet["normalization_state"] = "normalized"
        ok, err = validate_review_packet(packet)
        self.assertTrue(ok, msg=err)

    def test_source_graph_counts_in_confidence_notes(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        identity_report = {
            "summary": {"total_canonical": 1, "total_ambiguous": 0},
            "canonical_identities": [],
        }
        plot_topology = {
            "plot_beats": [],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }

        packet = synthesize_normalized_packet(
            source_graph, identity_report, plot_topology
        )
        notes = packet.get("confidence_notes", {})
        self.assertIn("source_graph_atom_count", notes)
        self.assertIn("identity_count", notes)

    def test_legacy_payload_fields_preserved(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        identity_report = {
            "summary": {"total_canonical": 0, "total_ambiguous": 0},
            "canonical_identities": [],
        }
        plot_topology = {
            "plot_beats": [],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }

        legacy = {
            "title": "My Title",
            "description": "My desc",
            "estimated_level_min": 3,
            "estimated_level_max": 5,
            "locations": [{"name": "Castle"}],
            "npc_seeds": [{"name": "Knight"}],
            "monster_refs": ["Goblin"],
        }

        packet = synthesize_normalized_packet(
            source_graph, identity_report, plot_topology,
            legacy_model_payload=legacy,
        )
        self.assertEqual(packet["title"], "My Title")
        self.assertEqual(packet["estimated_level_min"], 3)
        self.assertEqual(len(packet["locations"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
