# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for source-locked builder narrative serialization (Phase 4, Section 4).

Verifies that:
- narrative includes SOURCE-FAITHFUL BUILD LOCK section
- exact source names are present
- forbidden-invention guidance is present
- puzzle rule preservation is stated
- all required section headings are present
- narrative is deterministic and ASCII-safe
"""

import unittest
from typing import Any, Dict

from utils.toolkit_builder_blueprint import serialize_builder_blueprint_to_narrative


def _make_blueprint(with_unsupported: bool = False, with_puzzles: bool = True) -> Dict[str, Any]:
    warnings = []
    if with_unsupported:
        warnings.append({"source": "unsupported_addition", "finding_id": "u1",
                         "message": "Detected replacement faction 'Ward Network'"})

    bp = {
        "blueprint_version": "source_faithful_builder_blueprint.v1",
        "module": {
            "title": "The Hidden City of Numillian",
            "summary": "A quirky character-driven adventure in a hidden city",
            "tone_profile": {
                "markers": ["quirky character-driven fantasy", "hidden city mystery"],
                "unsupported_inventions": [{"finding_id": "u1", "detail": "Detected replacement faction 'Ward Network'"}] if with_unsupported else [],
            },
        },
        "source_lock": {
            "canonical_names_locked": True,
            "required_atom_omission_blocks_build": True,
            "invented_major_entities_forbidden": True,
            "replacement_plotlines_forbidden": True,
            "puzzle_rule_rewrite_forbidden": True,
        },
        "location_roster": [
            {"atom_id": "loc_brooksteps", "display_name": "Brooksteps Inn",
             "aliases": [], "criticality": "required",
             "source_refs": [{"excerpt": "The Brooksteps Inn"}]},
            {"atom_id": "loc_wizard_tower", "display_name": "Wizard's Tower",
             "aliases": [], "criticality": "required",
             "source_refs": []},
        ],
        "npc_roster": [
            {"atom_id": "npc_wayne", "display_name": "Wayne",
             "aliases": ["Wayne the innkeeper"], "role": "Innkeeper",
             "faction": "", "criticality": "required",
             "source_refs": [{"excerpt": "Wayne the crooked-toothed innkeeper"}]},
            {"atom_id": "npc_irene", "display_name": "Irene Laughing-Eyes",
             "aliases": ["Irene"], "role": "Cat Wizard",
             "faction": "", "criticality": "major",
             "source_refs": []},
        ],
        "plot_graph": [
            {"beat_id": "beat_01", "title": "Arrival at Brooksteps",
             "trigger": "Players arrive", "dependencies": [],
             "beat_type": "mainline",
             "outcome": "Learn of the Trial",
             "failure_state": ""},
        ],
        "puzzle_graph": [
            {
                "chain_id": "trial_door",
                "title": "Trial at the Door",
                "setup": "A magical door blocks the way",
                "rules": "Answer the riddle correctly",
                "solution": "Speak the password: OUROBOROS",
                "failure_consequences": "A trap triggers",
                "unlocks": "Wizard's Tower inner sanctum",
                "clue_dependencies": ["skull_riddle"],
            }
        ] if with_puzzles else [],
        "clue_graph": [
            {"clue_id": "skull_riddle", "description": "A skull on the door speaks a riddle",
             "location": "Wizard's Tower entrance",
             "reveals": "The password is Ouroboros",
             "mandatory": True},
        ],
        "encounter_plan": [
            {"name": "Tower Guards", "location": "Wizard's Tower",
             "purpose": "Guard the entrance",
             "monster_names": ["Guard"], "avoidable": True, "social": False},
        ],
        "item_roster": [
            {"display_name": "Crystal Orb", "location": "Wizard's Tower", "required": True},
        ],
        "tone_requirements": ["Tone marker: quirky character-driven fantasy"],
        "source_refs": [],
        "warnings": warnings,
    }
    return bp


class TestNarrativeSerialization(unittest.TestCase):

    def test_contains_build_lock_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("SOURCE-FAITHFUL BUILD LOCK", text)

    def test_contains_module_identity_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("MODULE IDENTITY AND TONE", text)

    def test_contains_location_roster_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("REQUIRED LOCATION ROSTER", text)

    def test_contains_npc_roster_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("REQUIRED NPC ROSTER", text)

    def test_contains_plot_topology_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("PLOT TOPOLOGY", text)

    def test_contains_puzzle_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("PUZZLE AND TRIAL RULES", text)

    def test_contains_clue_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("CLUE GRAPH", text)

    def test_contains_encounter_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("ENCOUNTER AND MONSTER PLAN", text)

    def test_contains_item_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("ITEM AND TREASURE PLAN", text)

    def test_contains_forbidden_inventions_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("FORBIDDEN INVENTIONS AND REPLACEMENTS", text)

    def test_contains_compression_notes_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("ALLOWED COMPRESSION OR MERGE NOTES", text)

    def test_exact_source_names_present(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("Brooksteps Inn", text)
        self.assertIn("Wizard's Tower", text)
        self.assertIn("Wayne", text)
        self.assertIn("Irene Laughing-Eyes", text)

    def test_forbidden_invention_guidance_present(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("Invented major entities", text)
        self.assertIn("Replacement plotlines", text)
        self.assertIn("Canonical source names are LOCKED", text)

    def test_puzzle_rule_preservation_stated(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("puzzle/trial setup, rules, solutions", text)

    def test_unsupported_finding_shown_in_forbidden_section(self):
        bp = _make_blueprint(with_unsupported=True)
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("Ward Network", text)

    def test_narrative_ascii_safe(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        try:
            text.encode("ascii")
        except UnicodeEncodeError as e:
            self.fail(f"Narrative contains non-ASCII characters: {e}")

    def test_deterministic_output(self):
        bp = _make_blueprint()
        text1 = serialize_builder_blueprint_to_narrative(bp)
        text2 = serialize_builder_blueprint_to_narrative(bp)
        self.assertEqual(text1, text2)

    def test_tone_markers_listed(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("quirky character-driven fantasy", text)

    def test_encounter_plan_includes_monsters(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("Tower Guards", text)
        self.assertIn("Guard", text)

    def test_item_plan_includes_items(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("Crystal Orb", text)

    def test_no_puzzle_section_when_no_puzzles(self):
        bp = _make_blueprint(with_puzzles=False)
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("no source puzzles in blueprint", text)

    def test_module_title_in_identity_section(self):
        bp = _make_blueprint()
        text = serialize_builder_blueprint_to_narrative(bp)
        self.assertIn("The Hidden City of Numillian", text)


if __name__ == "__main__":
    unittest.main()
