#!/usr/bin/env python3
"""Merge tests for section extraction results and source graph enrichment."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_source_extraction import (
    build_extraction_units,
    record_section_extraction_result,
)
from utils.toolkit_source_graph_synthesis import (
    build_identity_resolution_report,
    build_source_graph_synthesis_report,
)
from utils.toolkit_source_manifest import build_source_graph


NUMILLIAN_LIKE_MD = """\
# Test Adventure

## Map Key

### 1. Brooksteps Inn
Wayne runs this inn. A hidden journal sits behind the bar.

### 2. Wizard's Tower
**Irene** the cat wizard lives here. Trapped floor tiles (DC 14).

## NPC Roster

| Name | Role |
|------|------|
| Wayne | Innkeeper |
| Belrik Dumma-dhur | Assassin |
| Irene Laughing-Eyes | Cat Wizard |
"""


class TestExtractionMerge(unittest.TestCase):
    """Merge mechanical graph atoms with section extraction facts."""

    def test_graph_atoms_preserved_with_section_facts(self):
        source_graph = build_source_graph(NUMILLIAN_LIKE_MD)
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_graph=source_graph)
        section_results = []
        for unit in units:
            extracted = record_section_extraction_result(
                unit,
                "success",
                "test-model",
                extracted_atoms=[
                    {
                        "type": "npc",
                        "name": "Wayne",
                        "criticality": "major",
                        "source_refs": [
                            {"excerpt": "Wayne runs this inn", "line_start": 7}
                        ],
                    }
                ],
            )
            section_results.append(extracted)

        identity_report = build_identity_resolution_report(
            source_graph, section_results
        )
        # Wayne should be canonical with evidence from both mechanical + section
        wayne_ids = [
            i
            for i in identity_report["canonical_identities"]
            if "wayne" in i["display_name"].lower()
        ]
        self.assertGreaterEqual(len(wayne_ids), 1)

        synthesis = build_source_graph_synthesis_report(
            source_graph, section_results, identity_report, {}
        )
        self.assertIn("identity", synthesis)
        self.assertIn("section_extraction", synthesis)
        self.assertGreaterEqual(
            synthesis["section_extraction"]["completed_units"], 1
        )

    def test_degraded_section_preserves_mechanical_graph(self):
        source_graph = build_source_graph(NUMILLIAN_LIKE_MD)
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_graph=source_graph)
        section_results = []
        for unit in units:
            extracted = record_section_extraction_result(
                unit, "degraded", "test-model", error="provider_timeout"
            )
            section_results.append(extracted)

        identity_report = build_identity_resolution_report(
            source_graph, section_results
        )
        # Mechanical identities should still be present
        self.assertGreaterEqual(
            identity_report["summary"]["total_canonical"], 1
        )

        synthesis = build_source_graph_synthesis_report(
            source_graph, section_results, identity_report, {}
        )
        self.assertGreaterEqual(synthesis["section_extraction"]["degraded_units"], 1)

    def test_section_atom_counts_are_coherent(self):
        source_graph = build_source_graph(NUMILLIAN_LIKE_MD)
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_graph=source_graph)
        section_results = []
        for unit in units:
            section_results.append(
                record_section_extraction_result(
                    unit,
                    "success",
                    "test-model",
                    extracted_atoms=[
                        {"type": "npc", "name": "Wayne"},
                        {"type": "location", "name": "Inn"},
                    ],
                )
            )

        for result in section_results:
            self.assertEqual(result["evidence_summary"]["atom_count"], 2)
            self.assertIn("npc", result["evidence_summary"]["types"])
            self.assertIn("location", result["evidence_summary"]["types"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
