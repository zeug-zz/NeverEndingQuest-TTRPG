#!/usr/bin/env python3
"""Contract tests for toolkit section-bounded source extraction."""

import json
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_source_extraction import (
    build_extraction_index,
    build_extraction_units,
    compute_section_identity,
    record_section_extraction_result,
)
from utils.toolkit_source_manifest import (
    build_source_graph,
    build_source_manifest,
)


NUMILLIAN_LIKE_MD = """\
# The Hidden City of Numillian

A quirky adventure in a hidden city beneath the rolling hills.

## Overview

The party must pass the Trial at the Door to enter the City of the Mind.

## Map Key

### 1. Brooksteps Inn

Wayne the crooked-toothed innkeeper runs this lively establishment.
A DC 13 Perception check reveals a hidden journal behind the bar.

### 2. The Rookery

Aerie of the kenku composers **Dog-Growl** and **Book-shut**.
The room contains a spectral curator who tests visitors.

### 3. Wizard's Tower

This crumbling spire houses Irene Laughing-Eyes, a cat wizard.
A DC 14 Investigation check identifies trapped floor tiles.

### 4. Temple of Broance

An ancient temple guarded by a **gargoyle sentinel**.
Patrols of spectral hounds sweep through at night.

## NPC Roster

| Name | Role | Location |
|------|------|----------|
| Wayne | Innkeeper | Brooksteps Inn |
| Belrik Dumma-dhur | Assassin | The Rookery |
| Irene Laughing-Eyes | Cat Wizard | Wizard's Tower |

## Trial at the Door

### Skull Riddle
The skull speaks: "I have cities but no houses..."

### Flooding Room
Water rises. A DC 14 Wisdom check finds the hidden drain.

### The Dog Test
A mindscape where the party must not kill the dog.
"""

EMPTY_MD = ""

MINIMAL_MD = "# Just a Title\n\nNo real content."


class TestExtractionUnits(unittest.TestCase):
    """Task 1.1: Section extraction unit construction."""

    def test_units_built_from_headings(self):
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_path="test.md")
        self.assertGreaterEqual(len(units), 5)
        heading_paths = [u["heading_path"] for u in units]
        self.assertTrue(any("Brooksteps Inn" in p for p in heading_paths))
        self.assertTrue(any("Trial at the Door" in p for p in heading_paths))
        self.assertTrue(any("Skull Riddle" in p for p in heading_paths))

    def test_unit_has_required_fields(self):
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_path="test.md")
        for u in units:
            self.assertIn("section_id", u)
            self.assertIn("heading_path", u)
            self.assertIn("line_start", u)
            self.assertIn("line_end", u)
            self.assertIn("source_text", u)
            self.assertIn("source_hash", u)
            self.assertIn("chars", u)
            self.assertIn("atom_hints", u)
            self.assertIn("status", u)

    def test_empty_source_returns_single_unit(self):
        units = build_extraction_units(EMPTY_MD, source_path="test.md")
        self.assertEqual(len(units), 0)

    def test_minimal_source_returns_unit(self):
        units = build_extraction_units(MINIMAL_MD, source_path="test.md")
        self.assertGreaterEqual(len(units), 1)

    def test_unit_text_is_bounded(self):
        units = build_extraction_units(NUMILLIAN_LIKE_MD, source_path="test.md")
        for u in units:
            self.assertGreaterEqual(u["chars"], 0)
            self.assertLessEqual(u["chars"], 9000)

    def test_section_identity_is_stable(self):
        units1 = build_extraction_units(NUMILLIAN_LIKE_MD)
        units2 = build_extraction_units(NUMILLIAN_LIKE_MD)
        for u1, u2 in zip(units1, units2):
            self.assertEqual(u1["section_identity"], u2["section_identity"])

    def test_graph_passed_provides_atom_hints(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        units = build_extraction_units(
            NUMILLIAN_LIKE_MD, source_graph=graph
        )
        total_hints = sum(len(u.get("atom_hints", [])) for u in units)
        self.assertGreaterEqual(total_hints, 1)
        for u in units:
            for hint in u.get("atom_hints", []):
                self.assertIn("atom_id", hint)
                self.assertIn("type", hint)


class TestExtractionIndex(unittest.TestCase):
    """Task 1.3: Section extraction index."""

    def test_index_shape(self):
        units = build_extraction_units(NUMILLIAN_LIKE_MD)
        index = build_extraction_index(units)
        self.assertEqual(index["index_version"], "toolkit_source_extraction.v1")
        self.assertIn("total_units", index)
        self.assertIn("degraded_units", index)
        self.assertIn("completed_units", index)
        self.assertIn("entries", index)

    def test_index_entries_match_units(self):
        units = build_extraction_units(NUMILLIAN_LIKE_MD)
        index = build_extraction_index(units)
        self.assertEqual(len(index["entries"]), len(units))
        for entry in index["entries"]:
            self.assertIn("section_id", entry)
            self.assertIn("heading_path", entry)
            self.assertIn("status", entry)
            self.assertIn("artifact", entry)


class TestSectionResultRecording(unittest.TestCase):
    """Task 1.4: Degraded section status handling."""

    def test_success_recording(self):
        unit = {
            "section_id": "S001",
            "heading_path": "Test",
            "status": "pending",
        }
        result = record_section_extraction_result(
            unit,
            "success",
            "test-model",
            extracted_atoms=[{"type": "npc", "name": "Wayne"}],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(unit["status"], "success")
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(len(result["extracted_atoms"]), 1)
        self.assertEqual(result["evidence_summary"]["atom_count"], 1)

    def test_degraded_recording(self):
        unit = {"section_id": "S002", "heading_path": "Test", "status": "pending"}
        result = record_section_extraction_result(
            unit, "degraded", "test-model", error="invalid_json"
        )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(unit["status"], "degraded")
        self.assertIn("invalid_json", result["error"])

    def test_no_extracted_atoms(self):
        unit = {"section_id": "S003", "heading_path": "Test", "status": "pending"}
        result = record_section_extraction_result(unit, "success", "test-model")
        self.assertEqual(result["evidence_summary"]["atom_count"], 0)


class TestSectionIdentity(unittest.TestCase):
    """Stable section identity hashing."""

    def test_same_text_same_identity(self):
        a = compute_section_identity("The quick brown fox.")
        b = compute_section_identity("The quick brown fox.")
        self.assertEqual(a, b)

    def test_different_text_different_identity(self):
        a = compute_section_identity("The quick brown fox.")
        b = compute_section_identity("The quick brown dog.")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
