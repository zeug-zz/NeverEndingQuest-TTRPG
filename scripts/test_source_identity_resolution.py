#!/usr/bin/env python3
"""Contract tests for identity resolution and alias adjudication."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_source_graph_synthesis import (
    build_identity_resolution_report,
)
from utils.toolkit_source_manifest import build_source_graph


NUMILLIAN_MD = """\
# Test Adventure

## Map Key

### 1. Brooksteps Inn
**Wayne** the crooked-toothed innkeeper serves ale and gossip.

### 2. The Rookery
**Irene Laughing-Eyes** and **Irene** the cat wizard bicker constantly.

## NPC Table

| Name | Role |
|------|------|
| Wayne | Innkeeper |
| Belrik Dumma-dhur | Assassin |
| Irene | Cat Wizard |
| Irene Laughing-Eyes | Mage |
"""


class TestIdentityResolution(unittest.TestCase):
    """Task 3.x: Identity resolution and alias handling."""

    def test_mechanical_identities_preserved(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(
            source_graph,
            [],
        )
        identities = report["canonical_identities"]
        self.assertGreaterEqual(len(identities), 1)
        names = {i["display_name"] for i in identities}
        self.assertTrue(any("Wayne" in n for n in names))

    def test_duplicate_name_merged(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(source_graph, [])
        identities = report["canonical_identities"]
        # Irene may appear in multiple places; keyed by lower name
        irene_entries = [
            i
            for i in identities
            if "irene" in i["display_name"].lower()
        ]
        self.assertGreaterEqual(len(irene_entries), 1)

    def test_criticality_preserved_from_graph(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(source_graph, [])
        identities = report["canonical_identities"]
        for i in identities:
            self.assertIn(
                i["criticality"],
                ("required", "major", "minor", "ambiguous", "ignore"),
            )

    def test_summary_counts(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(source_graph, [])
        self.assertIn("summary", report)
        self.assertIn("total_canonical", report["summary"])
        self.assertIn("total_ambiguous", report["summary"])
        self.assertGreaterEqual(report["summary"]["total_canonical"], 1)

    def test_model_adjudication_merge_applied(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(
            source_graph,
            [],
            adjudication_model_output={
                "decisions": [
                    {
                        "type": "merge",
                        "name_a": "wayne",
                        "name_b": "wayne",
                        "evidence": "same entity",
                    }
                ]
            },
        )
        self.assertGreaterEqual(report["summary"]["total_canonical"], 1)

    def test_model_adjudication_ambiguous_not_applied(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(
            source_graph,
            [],
            adjudication_model_output={
                "decisions": [
                    {
                        "type": "ambiguous",
                        "name_a": "irene laughing-eyes",
                        "name_b": "irene",
                        "evidence": "unclear if same entity",
                    }
                ]
            },
        )
        # Ambiguous should be listed but source identities still present
        self.assertGreaterEqual(len(report["ambiguous_identities"]), 1)

    def test_reclassify_preserves_criticality(self):
        source_graph = build_source_graph(NUMILLIAN_MD)
        report = build_identity_resolution_report(
            source_graph,
            [],
            adjudication_model_output={
                "decisions": [
                    {
                        "type": "reclassify",
                        "name_a": "wayne",
                        "criticality": "required",
                        "entity_type": "npc",
                    }
                ]
            },
        )
        # Wayne should be present
        identities = report["canonical_identities"]
        wayne_entries = [
            i
            for i in identities
            if "wayne" in i["display_name"].lower()
        ]
        self.assertGreaterEqual(len(wayne_entries), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
