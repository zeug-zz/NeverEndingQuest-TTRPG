# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for toolkit source manifest and source graph extraction.
Phase 1 accurate-ingest verification.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.toolkit_source_manifest import (
    build_source_manifest,
    build_source_graph,
    _extract_heading_hierarchy,
    _extract_markdown_tables,
    _extract_location_candidates,
    _extract_entity_candidates,
    _extract_mechanic_candidates,
    _extract_puzzle_candidates,
    _extract_item_candidates,
    _extract_encounter_candidates,
    _extract_tone_candidates,
    _dedupe_atoms,
    SOURCE_MANIFEST_VERSION,
    SOURCE_GRAPH_VERSION,
)


NUMILLIAN_LIKE_MD = """# The Hidden City of Numillian

An adventure for 3-6 characters of levels 1-3.

## The Gatepact

Long ago, the wizard Shuluth forged a pact with the gate guardians.
The Gatepact binds the city of Numillian to the minds of those who enter.
Only the worthy may pass through the Door.

**Kobe** is a young apprentice who accidentally triggered the Gatepact.
**Shuluth** is the ancient wizard who forged the pact centuries ago.

### The Trial at the Door

The trial consists of three challenges:

1. **The Skull Riddle** - A skull on a pedestal asks: "What grows when the Door is open, yet keeps the Gatepact whole?"
2. **The Flooding Room** - Water rises slowly. The party must find the hidden release valve under the loose stone.
3. **The Dog Mindscape** - A spectral hound named **Dog-Growl** guards the final passage. The party must pass without harming it.

| NPC Name | Role | Location |
|----------|------|----------|
| Wayne | Crooked-toothed innkeeper | Brooksteps Inn |
| Irene Laughing-Eyes | Cat wizard | Wizard's Tower |
| Belrik Dumma-dhur | Duergar assassin | Shuluth's Tomb |
| Bramak Pakel | Nervous quartermaster | Charion Tamer |
| Treever | Woodsman guide | The Grove |
| Dog-Growl | Spectral hound | Trial at the Door |
| Book-shut | Kenku composer | The Rookery |
| Deflation | Kenku composer | The Rookery |

## Map Key

### 1. Charion Tamer

A small cottage with a thatched roof. **Bramak Pakel** sits at a desk cluttered with papers.
DC 12 Investigation reveals a hidden compartment with a **bronze key**.

### 2. Shuluth's Tomb

A dark crypt. **Belrik Dumma-dhur** lurks in the shadows. The tomb contains a **journal** with clues about the Gatepact.
Perception check DC 14 to spot the hidden pressure plate.

### 3. The Rookery

A crumbling tower where **Book-shut** and **Deflation** the kenku composers practice their art.
Treasury: 50 gp in assorted coins.

### 4. Brooksteps Inn

**Wayne** the innkeeper serves stew and ale. He knows the city's secrets but won't share them freely.
Persuasion DC 13 to earn his trust.

### 5. Wizard's Tower

**Irene Laughing-Eyes** studies ancient texts. She can identify magic items for a price.
Arcana check DC 15 to decipher her notes.

### 6. Art Gallery

Haunted portraits line the walls. A **spectral curator** challenges intruders.

### 7. Temple of Broance

A peaceful shrine. The **high priestess Miranda Dawnlight** tends the eternal flame.

### 8. The Grove

**Treever** the woodsman guide lives here. He knows the hidden paths through the city.

### 9. City of the Mind

A shimmering portal to the psychic realm. The final challenge awaits.

### 10. The Door

The Gatepact's terminus. **Kobe** must be protected here.

### 11. Shuluth's Sanctum

The wizard's private study. Contains the **Gatepact Scroll**.

### 12. The Ramparts

Crumbling walls overlooking the city. A **gargoyle sentinel** patrols.

### 13. The Hidden Vault

Sealed behind a puzzle door. Requires keys from three locations.
Solution: the skull riddle answer is "silence."

## Adventure Summary

This quirky character-driven adventure follows the party through the hidden city
of Numillian as they unravel the Gatepact mystery, endure the Trial at the Door,
and protect Kobe from those who would exploit the ancient magic.
"""

EMPTY_MD = ""

MINIMAL_MD = "# Just a title\n\nSome text here."

TONE_MD = (
    "A dark and gritty investigation into the conspiracy. "
    "Ominous shadows lurk in every corner. "
    "Quirky characters and whimsical encounters provide comic relief."
)


class TestHeadingExtraction(unittest.TestCase):
    """Task 1.2: Heading hierarchy extraction."""

    def test_extracts_levels_and_text(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        texts = [h["text"] for h in headings]
        self.assertIn("The Hidden City of Numillian", texts)
        self.assertIn("The Gatepact", texts)
        self.assertIn("The Trial at the Door", texts)

    def test_line_ranges(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        for h in headings:
            self.assertGreater(h["line_end"], h["line_start"])

    def test_parent_tracking(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        trial = [h for h in headings if "Trial at the Door" in h["text"]]
        self.assertTrue(trial)
        self.assertEqual(trial[0]["parent"], "The Gatepact")

    def test_empty_text(self):
        headings = _extract_heading_hierarchy(EMPTY_MD)
        self.assertEqual(headings, [])


class TestMarkdownTableExtraction(unittest.TestCase):
    """Task 1.3: Markdown table extraction."""

    def test_extracts_npc_table(self):
        tables = _extract_markdown_tables(NUMILLIAN_LIKE_MD)
        npc_tables = [t for t in tables if "NPC Name" in t.get("headers", [])]
        self.assertTrue(npc_tables)
        table = npc_tables[0]
        self.assertIn("Wayne", [row[0] for row in table["rows"]])
        self.assertIn("Irene Laughing-Eyes", [row[0] for row in table["rows"]])

    def test_headers_and_rows(self):
        tables = _extract_markdown_tables(NUMILLIAN_LIKE_MD)
        for t in tables:
            self.assertTrue(t["headers"])
            self.assertTrue(t["rows"])

    def test_empty_text(self):
        tables = _extract_markdown_tables(EMPTY_MD)
        self.assertEqual(tables, [])


class TestLocationCandidateExtraction(unittest.TestCase):
    """Task 1.4: Map-key and room-style location parsing."""

    def test_map_key_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        locations = _extract_location_candidates(NUMILLIAN_LIKE_MD, headings)
        names = [l["name"] for l in locations]
        self.assertIn("Charion Tamer", names)
        self.assertIn("Shuluth's Tomb", names)
        self.assertIn("Brooksteps Inn", names)

    def test_minimum_thirteen_locations(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        locations = _extract_location_candidates(NUMILLIAN_LIKE_MD, headings)
        self.assertGreaterEqual(len(locations), 13)

    def test_location_type_map_key(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        locations = _extract_location_candidates(NUMILLIAN_LIKE_MD, headings)
        for loc in locations:
            self.assertEqual(loc["location_type"], "map_key")

    def test_empty_text(self):
        locations = _extract_location_candidates(EMPTY_MD, [])
        self.assertEqual(locations, [])


class TestEntityCandidateExtraction(unittest.TestCase):
    """Task 1.5: Conservative entity extraction."""

    def test_bold_span_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        tables = _extract_markdown_tables(NUMILLIAN_LIKE_MD)
        entities = _extract_entity_candidates(NUMILLIAN_LIKE_MD, headings, tables)
        names = [e["name"] for e in entities]
        self.assertIn("Kobe", names)
        self.assertIn("Shuluth", names)
        self.assertIn("Bramak Pakel", names)
        self.assertIn("Belrik Dumma-dhur", names)

    def test_table_cell_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        tables = _extract_markdown_tables(NUMILLIAN_LIKE_MD)
        entities = _extract_entity_candidates(NUMILLIAN_LIKE_MD, headings, tables)
        names = [e["name"] for e in entities]
        self.assertIn("Wayne", names)
        self.assertIn("Irene Laughing-Eyes", names)
        self.assertIn("Treever", names)

    def test_minimum_eighteen_npcs(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        tables = _extract_markdown_tables(NUMILLIAN_LIKE_MD)
        entities = _extract_entity_candidates(NUMILLIAN_LIKE_MD, headings, tables)
        npc_count = sum(1 for e in entities if e.get("entity_type") == "npc" or e.get("entity_type") == "unknown")
        self.assertGreaterEqual(len(entities), 18)

    def test_common_words_rejected(self):
        headings = _extract_heading_hierarchy(TONE_MD)
        tables = _extract_markdown_tables(TONE_MD)
        entities = _extract_entity_candidates(TONE_MD, headings, tables)
        common = [e["name"] for e in entities if e["name"].lower() in (
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
        )]
        self.assertEqual(len(common), 0)


class TestMechanicAndPuzzleExtraction(unittest.TestCase):
    """Task 1.6: Mechanic, puzzle, item, encounter, tone extraction."""

    def test_dc_checks_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        mechanics = _extract_mechanic_candidates(NUMILLIAN_LIKE_MD, headings)
        cues = [m["cue"].lower() for m in mechanics]
        self.assertTrue(any("dc 12" in c for c in cues))
        self.assertTrue(any("dc 13" in c for c in cues))
        self.assertTrue(any("dc 14" in c for c in cues))

    def test_skill_checks_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        mechanics = _extract_mechanic_candidates(NUMILLIAN_LIKE_MD, headings)
        cues = [m["cue"].lower() for m in mechanics]
        self.assertTrue(any("perception check" in c for c in cues))
        self.assertTrue(any("dc 14" in c for c in cues))

    def test_puzzle_cues_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        puzzles = _extract_puzzle_candidates(NUMILLIAN_LIKE_MD, headings)
        cues = [p["cue"].lower() for p in puzzles]
        self.assertTrue(any("riddle" in c for c in cues))
        self.assertTrue(any("trial" in c for c in cues))
        self.assertTrue(any("mindscape" in c for c in cues))

    def test_skull_riddle_flooding_dog(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        puzzles = _extract_puzzle_candidates(NUMILLIAN_LIKE_MD, headings)
        all_context = " ".join(p["context"].lower() for p in puzzles)
        self.assertIn("skull", all_context)
        self.assertIn("flooding", all_context)
        self.assertIn("dog", all_context)

    def test_item_cues_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        items = _extract_item_candidates(NUMILLIAN_LIKE_MD, headings)
        cues = [i["cue"].lower() for i in items]
        self.assertTrue(any("journal" in c for c in cues))
        self.assertTrue(any("key" in c for c in cues))
        self.assertGreater(len(cues), 1)

    def test_encounter_cues_detected(self):
        headings = _extract_heading_hierarchy(NUMILLIAN_LIKE_MD)
        encounters = _extract_encounter_candidates(NUMILLIAN_LIKE_MD, headings)
        cues = [e["cue"].lower() for e in encounters]
        self.assertTrue(any("spectral" in c for c in cues))
        self.assertTrue(any("gargoyle" in c for c in cues))
        self.assertTrue(any("patrol" in c for c in cues))

    def test_tone_cues_detected(self):
        tones = _extract_tone_candidates(TONE_MD)
        phrases = [t["phrase"].lower() for t in tones]
        self.assertTrue(any("dark" in p for p in phrases))
        self.assertTrue(any("gritty" in p for p in phrases))
        self.assertTrue(any("ominous" in p for p in phrases))
        self.assertTrue(any("quirky" in p for p in phrases))


class TestSourceManifest(unittest.TestCase):
    """Task 2.x: Full source manifest construction."""

    def test_manifest_shape(self):
        manifest = build_source_manifest(NUMILLIAN_LIKE_MD)
        self.assertEqual(manifest["manifest_version"], SOURCE_MANIFEST_VERSION)
        self.assertIn("headings", manifest)
        self.assertIn("source_hash", manifest)
        self.assertIn("tables", manifest)
        self.assertIn("location_candidates", manifest)
        self.assertIn("entity_candidates", manifest)
        self.assertIn("mechanic_candidates", manifest)
        self.assertIn("puzzle_candidates", manifest)
        self.assertIn("item_candidates", manifest)
        self.assertIn("encounter_candidates", manifest)
        self.assertIn("tone_candidates", manifest)

    def test_manifest_has_content(self):
        manifest = build_source_manifest(NUMILLIAN_LIKE_MD)
        self.assertGreater(len(manifest["headings"]), 5)
        self.assertGreater(len(manifest["tables"]), 0)
        self.assertGreaterEqual(len(manifest["location_candidates"]), 13)
        self.assertGreaterEqual(len(manifest["entity_candidates"]), 18)

    def test_manifest_source_hash_present(self):
        manifest = build_source_manifest(NUMILLIAN_LIKE_MD)
        self.assertTrue(manifest["source_hash"])
        self.assertGreaterEqual(len(manifest["source_hash"]), 32)

    def test_empty_source(self):
        manifest = build_source_manifest(EMPTY_MD)
        for key in ("headings", "tables", "location_candidates",
                     "entity_candidates", "mechanic_candidates",
                     "puzzle_candidates", "item_candidates",
                     "encounter_candidates", "tone_candidates"):
            self.assertEqual(len(manifest[key]), 0)


class TestSourceGraph(unittest.TestCase):
    """Task 2.x: Source graph atom construction."""

    def test_graph_shape(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        self.assertEqual(graph["graph_version"], SOURCE_GRAPH_VERSION)
        self.assertIn("atoms", graph)
        self.assertIn("summary", graph)

    def test_graph_summary_counts(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        summary = graph["summary"]
        self.assertIn("npc_candidates", summary)
        self.assertIn("location_candidates", summary)
        self.assertIn("puzzle_candidates", summary)
        self.assertIn("encounter_candidates", summary)
        self.assertIn("item_candidates", summary)
        self.assertIn("tone_candidates", summary)
        self.assertIn("total_atoms", summary)

    def test_atoms_contain_evidence_refs(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        for atom in graph["atoms"]:
            self.assertIn("source_refs", atom)
            self.assertGreater(len(atom["source_refs"]), 0)
            ref = atom["source_refs"][0]
            self.assertIn("source_path", ref)
            self.assertIn("line_start", ref)
            self.assertIn("excerpt", ref)

    def test_table_entity_uses_table_row_line(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        wayne_atoms = [a for a in graph["atoms"] if a.get("name") == "Wayne"]
        self.assertGreaterEqual(len(wayne_atoms), 1)
        wayne = wayne_atoms[0]
        self.assertGreater(wayne["source_refs"][0]["line_start"], 1)
        self.assertNotEqual(wayne["source_refs"][0]["section"], "")

    def test_location_atoms_have_required_criticality(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        loc_atoms = [a for a in graph["atoms"] if a["type"] == "location"]
        for loc in loc_atoms:
            self.assertEqual(loc["criticality"], "required")

    def test_proper_noun_only_not_over_promoted(self):
        md = "Some random ProperNoun of Nothing Interesting passed by."
        graph = build_source_graph(md)
        npc_or_unknown = [a for a in graph["atoms"]
                          if a["type"] in ("npc", "unknown")]
        for atom in npc_or_unknown:
            self.assertIn(atom["criticality"], ("ambiguous", "minor"))

    def test_empty_source(self):
        graph = build_source_graph(EMPTY_MD)
        self.assertEqual(len(graph["atoms"]), 0)
        self.assertEqual(graph["summary"]["total_atoms"], 0)

    def test_minimal_source(self):
        graph = build_source_graph(MINIMAL_MD)
        self.assertIsInstance(graph["atoms"], list)

    def test_numillian_benchmark_npcs(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        npc_count = graph["summary"]["npc_candidates"]
        loc_count = graph["summary"]["location_candidates"]
        self.assertGreaterEqual(npc_count, 18)
        self.assertGreaterEqual(loc_count, 13)

    def test_puzzle_atoms_include_trial_cues(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        puzzle_atoms = [a for a in graph["atoms"] if a["type"] == "puzzle"]
        all_summaries = " ".join(a.get("summary", "") for a in puzzle_atoms).lower()
        self.assertIn("skull", all_summaries)
        self.assertIn("riddle", all_summaries)
        self.assertIn("flooding", all_summaries)
        self.assertIn("dog", all_summaries)


class TestSourceGraphAtomIds(unittest.TestCase):
    """Task 2.1: Stable atom IDs."""

    def test_ids_are_stable(self):
        graph1 = build_source_graph(NUMILLIAN_LIKE_MD, source_path="test.md")
        graph2 = build_source_graph(NUMILLIAN_LIKE_MD, source_path="test.md")
        ids1 = [a["id"] for a in graph1["atoms"]]
        ids2 = [a["id"] for a in graph2["atoms"]]
        self.assertEqual(ids1, ids2)

    def test_ids_remain_unique_with_full_source_hash(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD, source_path="test.md", source_hash="a" * 64)
        ids = [a["id"] for a in graph["atoms"]]
        self.assertEqual(len(ids), len(set(ids)))


class TestCriticalityClassification(unittest.TestCase):
    """Task 2.3: Criticality classification."""

    def test_location_atoms_required(self):
        graph = build_source_graph(NUMILLIAN_LIKE_MD)
        loc_atoms = [a for a in graph["atoms"] if a["type"] == "location"]
        self.assertTrue(all(a["criticality"] == "required" for a in loc_atoms))

    def test_tone_markers_minor(self):
        graph = build_source_graph(TONE_MD)
        tone_atoms = [a for a in graph["atoms"] if a["type"] == "tone_marker"]
        for t in tone_atoms:
            self.assertIn(t["criticality"], ("minor", "ambiguous", "ignore"))

    def test_tone_atom_names_are_preserved(self):
        graph = build_source_graph(TONE_MD)
        tone_names = [a["name"].lower() for a in graph["atoms"] if a["type"] == "tone_marker"]
        self.assertIn("dark", tone_names)
        self.assertIn("gritty", tone_names)
        self.assertIn("ominous", tone_names)
        self.assertIn("quirky", tone_names)
        self.assertIn("whimsical", tone_names)


class TestAtomDedupe(unittest.TestCase):
    """Task 2.x: Duplicate atom resolution."""

    def test_dedupe_merges_source_refs_and_keeps_best_atom(self):
        atoms = [
            {
                "id": "a1",
                "type": "npc",
                "name": "Wayne",
                "summary": "First ref",
                "criticality": "minor",
                "confidence": "medium",
                "source_refs": [{"source_path": "a.md", "section": "S", "line_start": 2, "line_end": 2, "excerpt": "one"}],
            },
            {
                "id": "a2",
                "type": "npc",
                "name": "Wayne",
                "summary": "Second ref",
                "criticality": "required",
                "confidence": "high",
                "source_refs": [{"source_path": "a.md", "section": "S", "line_start": 8, "line_end": 8, "excerpt": "two"}],
            },
        ]
        _dedupe_atoms(atoms)
        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0]["criticality"], "required")
        self.assertEqual(len(atoms[0]["source_refs"]), 2)


class TestUploadContractHelpers(unittest.TestCase):
    """Tasks 3.x: Contract extension for source graph artifacts."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_workspace_files_includes_source_graph(self):
        from utils.toolkit_homebrew_upload_contract import get_workspace_files
        files = get_workspace_files(self.workspace)
        self.assertIn("source_manifest", files)
        self.assertIn("source_graph", files)

    def test_persist_and_load_source_manifest(self):
        from utils.toolkit_homebrew_upload_contract import (
            persist_source_manifest_artifact,
            load_source_manifest_artifact,
        )
        manifest = {"test": True}
        ok = persist_source_manifest_artifact(self.workspace, manifest)
        self.assertTrue(ok)
        loaded = load_source_manifest_artifact(self.workspace)
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["test"])

    def test_persist_and_load_source_graph(self):
        from utils.toolkit_homebrew_upload_contract import (
            persist_source_graph_artifact,
            load_source_graph_artifact,
        )
        graph = {"test": True}
        ok = persist_source_graph_artifact(self.workspace, graph)
        self.assertTrue(ok)
        loaded = load_source_graph_artifact(self.workspace)
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["test"])

    def test_legacy_workspace_returns_none(self):
        from utils.toolkit_homebrew_upload_contract import (
            load_source_manifest_artifact,
            load_source_graph_artifact,
        )
        self.assertIsNone(load_source_manifest_artifact(self.workspace))
        self.assertIsNone(load_source_graph_artifact(self.workspace))


class TestNormalizerIntegration(unittest.TestCase):
    """Tasks 4.x: Source graph integration in normalizer (compile only)."""

    def test_source_graph_imports(self):
        from utils.toolkit_source_manifest import build_source_manifest, build_source_graph
        self.assertTrue(callable(build_source_manifest))
        self.assertTrue(callable(build_source_graph))

    def test_normalizer_imports_helpers(self):
        from utils.toolkit_homebrew_normalizer import normalize_homebrew_upload
        self.assertTrue(callable(normalize_homebrew_upload))


if __name__ == "__main__":
    unittest.main()
