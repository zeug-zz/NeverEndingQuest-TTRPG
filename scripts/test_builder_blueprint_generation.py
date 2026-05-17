# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for builder blueprint generation (Phase 4, Section 3).

Verifies that:
- blueprint is generated from source graph, identity, topology artifacts
- required source NPCs and locations appear in blueprint rosters
- source atom IDs and original display names are preserved
- puzzle/trial chains from topology appear in puzzle_graph and clue_graph
- unsupported replacement findings are carried into warnings
"""

import json
import unittest
from typing import Any, Dict

from utils.toolkit_builder_blueprint import generate_builder_blueprint


def _make_source_graph() -> dict:
    return {
        "atoms": [
            {"id": "loc_brooksteps", "name": "Brooksteps Inn", "type": "location",
             "criticality": "required", "source_section": "Map Key 1",
             "source_refs": [{"excerpt": "The Brooksteps Inn"}]},
            {"id": "loc_wizard_tower", "name": "Wizard's Tower", "type": "location",
             "criticality": "required", "source_section": "Map Key 2",
             "source_refs": [{"excerpt": "The Wizard's Tower"}]},
            {"id": "npc_wayne", "name": "Wayne", "type": "npc",
             "criticality": "required",
             "source_refs": [{"excerpt": "Wayne the crooked-toothed innkeeper"}]},
            {"id": "npc_irene", "name": "Irene Laughing-Eyes", "type": "npc",
             "criticality": "major",
             "source_refs": [{"excerpt": "Irene Laughing-Eyes the cat wizard"}]},
            {"id": "puzzle_trial_door", "name": "Trial at the Door", "type": "puzzle",
             "criticality": "required",
             "source_refs": [{"excerpt": "The Trial at the Door"}]},
            {"id": "clue_skull_riddle", "name": "Skull Riddle", "type": "puzzle",
             "criticality": "required",
             "source_refs": [{"excerpt": "The skull riddle"}]},
            {"id": "encounter_guards", "name": "Tower Guards", "type": "encounter",
             "location": "Wizard's Tower", "monster_names": ["Guard"],
             "criticality": "major",
             "source_refs": [{"excerpt": "Tower guards"}]},
            {"id": "item_orb", "name": "Crystal Orb", "type": "item",
             "location": "Wizard's Tower", "required": True,
             "source_refs": [{"excerpt": "Crystal orb"}]},
            {"id": "tone_quirky", "name": "quirky character-driven fantasy", "type": "tone_marker",
             "source_refs": []},
        ]
    }


def _make_identity_report() -> dict:
    return {
        "canonical_identities": [
            {"canonical_id": "npc_wayne", "display_name": "Wayne",
             "aliases": [{"name": "Wayne the innkeeper"}],
             "entity_type": "npc", "criticality": "required"},
            {"canonical_id": "npc_irene", "display_name": "Irene Laughing-Eyes",
             "aliases": [{"name": "Irene"}],
             "entity_type": "npc", "criticality": "major"},
        ]
    }


def _make_plot_topology() -> dict:
    return {
        "plot_beats": [
            {"beat_id": "beat_01", "title": "Arrival at Brooksteps",
             "trigger": "Players enter Brooksteps Inn",
             "dependencies": [], "required_location": "Brooksteps Inn",
             "outcome": "Learn about the Trial", "beat_type": "mainline"},
            {"beat_id": "beat_02", "title": "The Trial",
             "trigger": "Players attempt the Trial at the Door",
             "dependencies": ["beat_01"], "required_location": "Wizard's Tower",
             "outcome": "Enter the hidden city", "beat_type": "climax"},
        ],
        "puzzle_chains": [
            {"chain_id": "trial_door", "title": "Trial at the Door",
             "setup": "A magical door blocks the way",
             "rules": "Answer the riddle correctly",
             "solution": "Speak the password: OUROBOROS",
             "failure_consequences": "A trap triggers",
             "unlocks": "Wizard's Tower inner sanctum",
             "clue_dependencies": ["skull_riddle"]},
        ],
        "clues": [
            {"clue_id": "skull_riddle", "description": "A skull on the door speaks a riddle",
             "location": "Wizard's Tower entrance",
             "reveals": "The password is Ouroboros",
             "mandatory": True},
        ],
    }


def _make_synthesis_report() -> dict:
    return {"total_candidates": 10, "canonical_identities": 5}


def _make_packet() -> dict:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_hash": "abc123",
        "title": "The Hidden City of Numillian",
        "description": "A quirky character-driven adventure",
    }


def _make_fidelity_report() -> dict:
    return {
        "status": "clean",
        "findings": [
            {"finding_id": "unsup_01", "category": "unsupported",
             "severity": "warning",
             "detail": "Detected replacement faction 'Ward Network of Numillian'",
             "expected": "Original Gatepact lore",
             "actual": "Ward Network conspiracy"},
        ],
    }


class TestBlueprintGeneration(unittest.TestCase):

    def setUp(self):
        self.source_graph = _make_source_graph()
        self.identity_report = _make_identity_report()
        self.plot_topology = _make_plot_topology()
        self.synthesis_report = _make_synthesis_report()
        self.packet = _make_packet()
        self.fidelity_report = _make_fidelity_report()

    def test_generates_blueprint_with_required_sections(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        self.assertEqual(bp["blueprint_version"], "source_faithful_builder_blueprint.v1")
        self.assertEqual(bp["blueprint_status"], "ready")
        self.assertIn("area_plan", bp)
        self.assertIn("location_roster", bp)
        self.assertIn("npc_roster", bp)
        self.assertIn("plot_graph", bp)
        self.assertIn("puzzle_graph", bp)
        self.assertIn("clue_graph", bp)
        self.assertIn("encounter_plan", bp)
        self.assertIn("item_roster", bp)
        self.assertIn("source_refs", bp)
        self.assertIn("warnings", bp)

    def test_required_npcs_in_roster(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        npc_names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Wayne", npc_names)
        self.assertIn("Irene Laughing-Eyes", npc_names)

    def test_required_locations_in_roster(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        loc_names = [l["display_name"] for l in bp["location_roster"]]
        self.assertIn("Brooksteps Inn", loc_names)
        self.assertIn("Wizard's Tower", loc_names)

    def test_preserves_source_atom_ids(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        loc_ids = {l["atom_id"] for l in bp["location_roster"]}
        self.assertIn("loc_brooksteps", loc_ids)
        self.assertIn("loc_wizard_tower", loc_ids)

    def test_preserves_aliases_from_identity_report(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        wayne = next(n for n in bp["npc_roster"] if n["display_name"] == "Wayne")
        self.assertIn("Wayne the innkeeper", wayne["aliases"])

    def test_puzzle_chains_in_puzzle_graph(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        puzzle_titles = [p["title"] for p in bp["puzzle_graph"]]
        self.assertIn("Trial at the Door", puzzle_titles)

    def test_clue_graph_present(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        self.assertTrue(len(bp["clue_graph"]) > 0)

    def test_encounter_plan_present(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        encounter_names = [e["name"] for e in bp["encounter_plan"]]
        self.assertIn("Tower Guards", encounter_names)

    def test_item_roster_present(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        item_names = [i["display_name"] for i in bp["item_roster"]]
        self.assertIn("Crystal Orb", item_names)

    def test_tone_markers_in_module_profile(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        markers = bp["module"]["tone_profile"]["markers"]
        self.assertIn("quirky character-driven fantasy", markers)

    def test_unsupported_findings_carried_to_warnings(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        warning_sources = [w["source"] for w in bp["warnings"]]
        self.assertIn("unsupported_addition", warning_sources)

    def test_plot_topology_preserved(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        beat_titles = [b["title"] for b in bp["plot_graph"]]
        self.assertIn("Arrival at Brooksteps", beat_titles)
        self.assertIn("The Trial", beat_titles)

    def test_source_refs_are_included(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        self.assertTrue(len(bp["source_refs"]) > 0)

    def test_module_identity_from_packet(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        self.assertEqual(bp["module"]["title"], "The Hidden City of Numillian")

    def test_source_lock_defaults(self):
        bp = generate_builder_blueprint(
            self.source_graph, self.identity_report, self.plot_topology,
            self.synthesis_report, self.packet, self.fidelity_report,
        )
        lock = bp["source_lock"]
        self.assertTrue(lock["canonical_names_locked"])
        self.assertTrue(lock["invented_major_entities_forbidden"])
        self.assertTrue(lock["replacement_plotlines_forbidden"])
        self.assertTrue(lock["puzzle_rule_rewrite_forbidden"])


if __name__ == "__main__":
    unittest.main()
