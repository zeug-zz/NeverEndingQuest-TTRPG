# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Task 1.1 baseline: prove Well-of-Ruin-style table/effect text is promoted
to NPC atoms/entity candidates by current production source-manifest helpers.

This is a BASELINE / REGRESSION test file.  Tests assert the CURRENT
false-positive class: effect labels and full effect sentences from trap/table
context appearing as entity candidates (default type "npc") in the manifest
and as npc-type atoms in the source graph.  When production fixes land in
later tasks, these assertions should be updated to expect filtered output.

Repository: NeverEndingQuest
"""

import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.toolkit_source_manifest import (
    build_source_manifest,
    build_source_graph,
    _extract_entity_candidates,
    _extract_heading_hierarchy,
    _extract_markdown_tables,
    _normalize_table_header,
    _table_headers_indicate_entity_identity,
    _table_headers_indicate_effect_text,
    SOURCE_MANIFEST_VERSION,
    SOURCE_GRAPH_VERSION,
)

from utils.toolkit_builder_blueprint import (
    _build_npc_roster,
    generate_builder_blueprint,
)

from utils.toolkit_build_fidelity import (
    _find_required_atoms,
    _check_atoms_vs_module,
)

from utils.toolkit_entity_candidate_triage import (
    build_triage_decision,
    build_entity_candidate_triage_report,
    build_prefilter_decision,
    build_underbound_npc_findings,
    DECISION_REJECT,
    DECISION_KEEP,
    TYPE_NARRATIVE_PHRASE,
    TYPE_TRUE_NPC,
    TYPE_PLOT_NOTE,
    TYPE_TONE_MARKER,
    TYPE_UNKNOWN,
)


# ---------------------------------------------------------------------------
# Synthetic Well-of-Ruin-style markdown fixture
# ---------------------------------------------------------------------------
# This fixture reproduces the pattern observed in the Well of Ruin encounter:
# a heading declaring level/difficulty, followed by a markdown table whose
# cells contain one-word effect labels (Well, Ruin, Awaken, ...) and full
# effect-prose sentences.  Current _extract_entity_candidates iterates all
# table cells and registers any text passing _is_likely_name as an "npc"
# entity candidate, producing false positives.

WELL_OF_RUIN_MD = """# Well of Ruin

A deadly magical trap that activates when any creature enters the central
chamber.  The effects are determined by rolling on the table below.

## Complex Trap

This trap has been dormant for centuries but awakens at the slightest
disturbance.

### level 11-16 Complex Trap, Deadly

| d100 | Effect | Description |
|------|--------|-------------|
| 01-15 | Well | The stone floor cracks open, revealing a deep shaft that radiates cold air. |
| 16-30 | Ruin | Ancient masonry crumbles from the ceiling. Chunks of stone crash down, creating clouds of dust. |
| 31-45 | Awaken | Mundane objects worth at least 1 gp become sentient and hostile. |
| 46-55 | Menace | Sinister whispers fill the room. Shadows coalesce into threatening forms. |
| 56-65 | Enrage | A wave of crimson energy washes over the area. Creatures must make a DC 16 Wisdom saving throw or attack the nearest target. |
| 66-75 | Enthrall | Hypnotic patterns dance in the air. Affected creatures must succeed on a DC 16 Charisma save or be charmed. |
| 76-85 | Irradiate | Pale green light floods the chamber. Creatures take 4d10 radiant damage and are poisoned until the end of their next turn. |
| 86-95 | Overwhelm | Psychic pressure crushes the mind. Creatures take 6d8 psychic damage and are stunned for 1 round. |
| 96-00 | All Effects | The trap activates every effect simultaneously. Roll for each effect separately. |
"""

# Well effect label names that current code falsely promotes to NPC candidates.
_WELL_FALSE_NPC_NAMES = [
    "Well",
    "Ruin",
    "Awaken",
    "Menace",
    "Enrage",
    "Enthrall",
    "Irradiate",
    "Overwhelm",
]

_FULL_EFFECT_SENTENCE = (
    "Mundane objects worth at least 1 gp become sentient and hostile."
)


class TestWellOfRuinManifestLevel( unittest.TestCase ):
    """Prove table-cell filtering removes Well effect labels from manifest."""

    maxDiff = None

    def test_well_effect_names_not_in_entity_candidates(self):
        """All 8 effect labels are excluded from entity_candidates."""
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        candidates = manifest.get("entity_candidates", [])
        candidate_names = [c["name"] for c in candidates]
        for name in _WELL_FALSE_NPC_NAMES:
            self.assertNotIn(
                name, candidate_names,
                f"'{name}' should NOT be an entity candidate "
                f"(effect table filtered).",
            )

    def test_no_well_false_names_present(self):
        """None of the false effect-label names appear in entity_candidates."""
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        candidates = manifest.get("entity_candidates", [])
        candidate_names = {c["name"] for c in candidates}
        false_set = set(_WELL_FALSE_NPC_NAMES)
        self.assertFalse(
            bool(candidate_names & false_set),
            f"Entity candidates should not contain any false names, "
            f"but found: {candidate_names & false_set}",
        )

    def test_well_table_cell_source_no_false_names(self):
        """No table_cell-sourced candidate matches a false effect label."""
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        candidates = manifest.get("entity_candidates", [])
        for cand in candidates:
            self.assertNotIn(
                cand["name"], _WELL_FALSE_NPC_NAMES,
                f"'{cand['name']}' should not be in entity_candidates "
                f"(effect table filtered).",
            )

    def test_full_effect_sentence_not_in_entity_candidates(self):
        """Full effect sentence is excluded from entity_candidates."""
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        candidates = manifest.get("entity_candidates", [])
        candidate_names = [c["name"] for c in candidates]
        self.assertNotIn(
            _FULL_EFFECT_SENTENCE, candidate_names,
            "Full effect sentence should NOT be an entity candidate "
            "(effect table filtered).",
        )


class TestWellOfRuinGraphLevel( unittest.TestCase ):
    """Prove table-cell filtering removes Well effect labels from graph."""

    maxDiff = None

    def test_well_effect_names_not_in_graph_npc_atoms(self):
        """All 8 effect labels are excluded from npc-type atoms."""
        graph = build_source_graph(WELL_OF_RUIN_MD)
        atoms = graph.get("atoms", [])
        npc_names = {
            a["name"] for a in atoms if a.get("type") == "npc"
        }
        for name in _WELL_FALSE_NPC_NAMES:
            self.assertNotIn(
                name, npc_names,
                f"'{name}' should NOT be an npc atom "
                f"(effect table filtered).",
            )

    def test_full_effect_sentence_not_in_graph_npc_atoms(self):
        """Full effect sentence is excluded from npc-type atoms."""
        graph = build_source_graph(WELL_OF_RUIN_MD)
        atoms = graph.get("atoms", [])
        npc_names = {
            a["name"] for a in atoms if a.get("type") == "npc"
        }
        self.assertNotIn(
            _FULL_EFFECT_SENTENCE, npc_names,
            "Full effect sentence should NOT produce an npc atom.",
        )

    def test_graph_count_excludes_false_positives(self):
        """npc_candidates summary is 0 (no table-derived NPCs)."""
        graph = build_source_graph(WELL_OF_RUIN_MD)
        summary = graph.get("summary", {})
        npc_count = summary.get("npc_candidates", 0)
        self.assertEqual(
            npc_count, 0,
            f"npc_candidates count ({npc_count}) should be 0 since "
            f"the only entity candidates were effect-table cells.",
        )


class TestWellOfRuinDirectExtractor( unittest.TestCase ):
    """Prove table-cell filtering at the _extract_entity_candidates level."""

    maxDiff = None

    def test_direct_extraction_excludes_effect_labels(self):
        """Direct call to _extract_entity_candidates excludes effect labels.

        This bypasses the full build_source_manifest pipeline to prove the
        exclusion happens at the entity-candidate extraction level.
        """
        headings = _extract_heading_hierarchy(WELL_OF_RUIN_MD)
        tables = _extract_markdown_tables(WELL_OF_RUIN_MD)
        candidates = _extract_entity_candidates(WELL_OF_RUIN_MD, headings, tables)
        candidate_names = [c["name"] for c in candidates]
        for name in _WELL_FALSE_NPC_NAMES:
            self.assertNotIn(
                name, candidate_names,
                f"Direct extraction should exclude '{name}' (effect table).",
            )
        self.assertNotIn(
            _FULL_EFFECT_SENTENCE, candidate_names,
            "Direct extraction should exclude the full effect sentence.",
        )


class TestWellOfRuinFixtureCompleteness( unittest.TestCase ):
    """Verify the synthetic fixture contains required elements."""

    def test_fixture_contains_level_header(self):
        self.assertIn("level 11-16 Complex Trap, Deadly", WELL_OF_RUIN_MD)

    def test_fixture_contains_well_term(self):
        self.assertIn("Well", WELL_OF_RUIN_MD)

    def test_fixture_contains_ruin_term(self):
        self.assertIn("Ruin", WELL_OF_RUIN_MD)

    def test_fixture_contains_awaken_term(self):
        self.assertIn("Awaken", WELL_OF_RUIN_MD)

    def test_fixture_contains_menace_term(self):
        self.assertIn("Menace", WELL_OF_RUIN_MD)

    def test_fixture_contains_enrage_term(self):
        self.assertIn("Enrage", WELL_OF_RUIN_MD)

    def test_fixture_contains_enthrall_term(self):
        self.assertIn("Enthrall", WELL_OF_RUIN_MD)

    def test_fixture_contains_irradiate_term(self):
        self.assertIn("Irradiate", WELL_OF_RUIN_MD)

    def test_fixture_contains_overwhelm_term(self):
        self.assertIn("Overwhelm", WELL_OF_RUIN_MD)

    def test_fixture_contains_full_effect_sentence(self):
        self.assertIn(
            "Mundane objects worth at least 1 gp become sentient and hostile.",
            WELL_OF_RUIN_MD,
        )


# ---------------------------------------------------------------------------
# Baseline manifest/graph structural integrity
# ---------------------------------------------------------------------------
class TestManifestGraphStructure( unittest.TestCase ):
    """Verify that manifest and graph structures are well-formed."""

    def test_manifest_has_entity_candidates_key(self):
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        self.assertIn("entity_candidates", manifest)

    def test_manifest_version_present(self):
        manifest = build_source_manifest(WELL_OF_RUIN_MD)
        self.assertIn("manifest_version", manifest)
        self.assertEqual(manifest["manifest_version"], SOURCE_MANIFEST_VERSION)

    def test_graph_version_present(self):
        graph = build_source_graph(WELL_OF_RUIN_MD)
        self.assertIn("graph_version", graph)
        self.assertEqual(graph["graph_version"], SOURCE_GRAPH_VERSION)

    def test_graph_has_summary(self):
        graph = build_source_graph(WELL_OF_RUIN_MD)
        self.assertIn("summary", graph)
        self.assertIn("npc_candidates", graph["summary"])

    def test_graph_atoms_no_false_npc_names(self):
        """Verify no graph atoms contain effect-label names."""
        graph = build_source_graph(WELL_OF_RUIN_MD)
        atoms = graph.get("atoms", [])
        atom_names = {a["name"] for a in atoms}
        false_set = set(_WELL_FALSE_NPC_NAMES)
        self.assertFalse(
            bool(atom_names & false_set),
            f"Graph atoms should not contain effect-label names, "
            f"but found: {atom_names & false_set}",
        )


# ---------------------------------------------------------------------------
# Task 2.1: Table-header role classification helpers
# ---------------------------------------------------------------------------

class TestTableHeaderRoleHelpers(unittest.TestCase):
    """Pure helper contract tests for table-header role classification."""

    # -- _normalize_table_header -----------------------------------------

    def test_normalize_plain_text(self):
        """Plain lowercase header normalizes to itself."""
        self.assertEqual("name", _normalize_table_header("name"))

    def test_normalize_case(self):
        """Uppercase header normalizes to lowercase."""
        self.assertEqual("name", _normalize_table_header("Name"))

    def test_normalize_trailing_colon(self):
        """Trailing colon is stripped."""
        self.assertEqual("effect", _normalize_table_header("Effect:"))

    def test_normalize_trailing_period(self):
        """Trailing period is stripped."""
        self.assertEqual("effect", _normalize_table_header("Effect."))

    def test_normalize_trailing_semicolon(self):
        """Trailing semicolon is stripped."""
        self.assertEqual("npc", _normalize_table_header("NPC;"))

    def test_normalize_bold_markers(self):
        """Bold markers ** stripped."""
        self.assertEqual("name", _normalize_table_header("**Name**"))

    def test_normalize_italic_markers(self):
        """Italic markers * stripped."""
        self.assertEqual("name", _normalize_table_header("*Name*"))

    def test_normalize_trailing_comma(self):
        """Trailing comma is stripped."""
        self.assertEqual("spell", _normalize_table_header("spell,"))

    def test_normalize_trailing_question_mark(self):
        """Trailing question mark is stripped."""
        self.assertEqual("spell", _normalize_table_header("spell?"))

    def test_normalize_trailing_exclamation(self):
        """Trailing exclamation is stripped."""
        self.assertEqual("trap", _normalize_table_header("Trap!"))

    def test_normalize_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        self.assertEqual("name", _normalize_table_header("  Name  "))

    def test_normalize_empty_string(self):
        """Empty string normalizes to empty."""
        self.assertEqual("", _normalize_table_header(""))

    def test_normalize_spaces_in_multiword(self):
        """Multi-word header preserves internal spaces."""
        self.assertEqual("passive element",
                         _normalize_table_header("Passive Element"))

    def test_normalize_bold_multiword(self):
        """Bold multi-word header normalizes correctly."""
        self.assertEqual("active element",
                         _normalize_table_header("**Active Element**"))

    # -- _table_headers_indicate_entity_identity -------------------------

    def test_identity_name_header(self):
        """'Name' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Name", "Role", "Location"]))

    def test_identity_npc_header(self):
        """'NPC' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["NPC", "Description"]))

    def test_identity_character_header(self):
        """'Character' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Character", "Role"]))

    def test_identity_creature_header(self):
        """'Creature' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Creature", "HP", "AC"]))

    def test_identity_faction_header(self):
        """'Faction' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Faction", "Leader"]))

    def test_identity_monster_header(self):
        """'Monster' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Monster", "CR"]))

    def test_identity_person_header(self):
        """'Person' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Person", "Role"]))

    def test_identity_actor_header(self):
        """'Actor' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["Actor"]))

    def test_identity_people_header(self):
        """'People' header is identity-bearing."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["People", "Title"]))

    def test_identity_normalized_punctuation(self):
        """Punctuation variants of identity headers match."""
        self.assertTrue(
            _table_headers_indicate_entity_identity(["**Name:**", "Role"]))
        self.assertTrue(
            _table_headers_indicate_entity_identity(["NPC:", "Location"]))
        self.assertTrue(
            _table_headers_indicate_entity_identity(["*Character.*", "Role"]))

    def test_identity_empty_headers_returns_false(self):
        """Empty header list returns False."""
        self.assertFalse(_table_headers_indicate_entity_identity([]))

    def test_identity_none_headers_returns_false(self):
        """None/null-like headers do not match."""
        self.assertFalse(_table_headers_indicate_entity_identity([""]))

    # -- _table_headers_indicate_effect_text -----------------------------

    def test_effect_effect_header(self):
        """'Effect' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d100", "Effect", "Description"]))

    def test_effect_complication_header(self):
        """'Complication' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d6", "Complication"]))

    def test_effect_result_header(self):
        """'Result' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d20", "Result"]))

    def test_effect_description_header(self):
        """'Description' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d100", "Description"]))

    def test_effect_spell_header(self):
        """'Spell' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Spell", "School", "Level"]))

    def test_effect_trigger_header(self):
        """'Trigger' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Trigger", "Effect"]))

    def test_effect_trap_header(self):
        """'Trap' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Trap Name", "Effect"]))

    def test_effect_mechanic_header(self):
        """'Mechanic' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Mechanic", "Effect"]))

    def test_effect_damage_header(self):
        """'Damage' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Damage", "Effect"]))

    def test_effect_condition_header(self):
        """'Condition' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Condition", "Duration"]))

    def test_effect_passive_element_header(self):
        """'Passive Element' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Passive Element"]))

    def test_effect_active_element_header(self):
        """'Active Element' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["Active Element"]))

    def test_effect_d100_header(self):
        """'d100' header is effect-bearing."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d100", "Effect"]))

    def test_effect_normalized_punctuation(self):
        """Punctuation variants of effect headers match."""
        self.assertTrue(
            _table_headers_indicate_effect_text(["d100:", "Effect:", "Description:"]))
        self.assertTrue(
            _table_headers_indicate_effect_text(["**Result**", "Effect**"]))

    def test_effect_empty_headers_returns_false(self):
        """Empty header list returns False."""
        self.assertFalse(_table_headers_indicate_effect_text([]))

    # -- Negative checks: identity vs effect non-overlap -----------------

    def test_name_not_effect(self):
        """'Name' header is NOT classified as effect-bearing."""
        self.assertFalse(
            _table_headers_indicate_effect_text(["Name", "Role", "Location"]))

    def test_npc_not_effect(self):
        """'NPC' header alone is NOT classified as effect-bearing."""
        self.assertFalse(
            _table_headers_indicate_effect_text(["NPC"]))
        self.assertFalse(
            _table_headers_indicate_effect_text(["NPC", "Role", "Location"]))

    def test_effect_not_identity(self):
        """'Effect' header is NOT classified as identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["d100", "Effect", "Description"]))

    def test_complication_not_identity(self):
        """'Complication' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["d6", "Complication"]))

    def test_result_not_identity(self):
        """'Result' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["d20", "Result"]))

    def test_trap_not_identity(self):
        """'Trap' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Trap"]))

    def test_damage_not_identity(self):
        """'Damage' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Damage"]))

    def test_trigger_not_identity(self):
        """'Trigger' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Trigger"]))

    def test_spell_not_identity(self):
        """'Spell' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Spell", "School", "Level"]))

    def test_passive_element_not_identity(self):
        """'Passive Element' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Passive Element"]))

    def test_active_element_not_identity(self):
        """'Active Element' header is NOT identity-bearing."""
        self.assertFalse(
            _table_headers_indicate_entity_identity(["Active Element"]))

    # -- Well fixture regression: effect table headers -------------------

    def test_well_table_is_effect(self):
        """Well-of-Ruin fixture table is classified as effect-bearing."""
        tables = _extract_markdown_tables(WELL_OF_RUIN_MD)
        self.assertTrue(len(tables) >= 1, "Fixture must have at least one table")
        for table in tables:
            headers = table.get("headers", [])
            self.assertTrue(
                _table_headers_indicate_effect_text(headers),
                f"Well fixture table headers {headers} should be "
                f"classified as effect-bearing.",
            )

    def test_well_table_is_not_identity(self):
        """Well-of-Ruin fixture table is NOT classified as identity-bearing."""
        tables = _extract_markdown_tables(WELL_OF_RUIN_MD)
        for table in tables:
            headers = table.get("headers", [])
            self.assertFalse(
                _table_headers_indicate_entity_identity(headers),
                f"Well fixture table headers {headers} should NOT be "
                f"classified as identity-bearing.",
            )

    # -- Numillian fixture regression: identity-bearing table headers -----

    def test_numillian_table_is_identity(self):
        """Numillian fixture table IS identity-bearing."""
        tables = _extract_markdown_tables(NUMILLIAN_NPC_TABLE_MD)
        self.assertTrue(len(tables) >= 1, "Numillian fixture must have table")
        for table in tables:
            headers = table.get("headers", [])
            self.assertTrue(
                _table_headers_indicate_entity_identity(headers),
                f"Numillian 'Name' table should be identity-bearing.",
            )

    def test_numillian_table_is_not_effect(self):
        """Numillian fixture table is NOT classified as effect-bearing."""
        tables = _extract_markdown_tables(NUMILLIAN_NPC_TABLE_MD)
        for table in tables:
            headers = table.get("headers", [])
            self.assertFalse(
                _table_headers_indicate_effect_text(headers),
                f"Numillian 'Name' table should NOT be "
                f"classified as effect-bearing.",
            )


# ---------------------------------------------------------------------------
# Task 1.2: Positive regression tests -- true table-sourced NPC names
# ---------------------------------------------------------------------------
# This fixture reproduces a Numillian-like identity-bearing table with known
# NPC names in the first column.  Current extraction MUST still find these
# names as entity/NPC candidates.  The fixture uses an identity-bearing
# header ("Name") and supporting columns ("Role", "Location").
#
# When production table-cell filtering lands (task 2.x), these tests MUST
# continue to pass -- the filtering must preserve true named NPCs from
# identity-header table cells.

NUMILLIAN_NPC_TABLE_MD = """# The Hidden City of Numillian

## Notable NPCs

| Name | Role | Location |
|------|------|----------|
| Wayne | Crypt caretaker | The Crypts |
| Irene Laughing-Eyes | Tavern keeper | The Gilded Tankard |
| Treever | Town herbalist | Apothecary |
"""

_NUMILLIAN_TRUE_NPC_NAMES = [
    "Wayne",
    "Irene Laughing-Eyes",
    "Treever",
]


class TestNumillianIdentityTableManifestLevel(unittest.TestCase):
    """Prove true NPC names from identity-bearing table survive
    source-manifest extraction."""

    maxDiff = None

    def test_true_npc_names_in_entity_candidates(self):
        """All 3 true NPC names appear as entity_candidates in manifest."""
        manifest = build_source_manifest(NUMILLIAN_NPC_TABLE_MD)
        candidates = manifest.get("entity_candidates", [])
        candidate_names = [c["name"] for c in candidates]
        for name in _NUMILLIAN_TRUE_NPC_NAMES:
            self.assertIn(
                name, candidate_names,
                f"'{name}' should be a true NPC entity candidate "
                f"(from identity-bearing table) in current code.",
            )

    def test_true_npc_names_have_entity_type_npc(self):
        """Extracted identity-table NPC names default to entity_type 'npc'."""
        manifest = build_source_manifest(NUMILLIAN_NPC_TABLE_MD)
        candidates = manifest.get("entity_candidates", [])
        for cand in candidates:
            if cand["name"] in _NUMILLIAN_TRUE_NPC_NAMES:
                self.assertEqual(
                    cand["entity_type"], "npc",
                    f"'{cand['name']}' should have entity_type 'npc' "
                    f"not '{cand['entity_type']}'.",
                )

    def test_true_npc_names_source_is_table_cell(self):
        """Extracted identity-table NPC names originate from table_cell source."""
        manifest = build_source_manifest(NUMILLIAN_NPC_TABLE_MD)
        candidates = manifest.get("entity_candidates", [])
        for cand in candidates:
            if cand["name"] in _NUMILLIAN_TRUE_NPC_NAMES:
                self.assertEqual(
                    cand["source"], "table_cell",
                    f"'{cand['name']}' should source from table_cell.",
                )


class TestNumillianIdentityTableGraphLevel(unittest.TestCase):
    """Prove true NPC names appear as npc-type atoms in source graph."""

    maxDiff = None

    def test_true_npc_names_in_graph_npc_atoms(self):
        """All 3 true NPC names produce npc-type atoms in source graph."""
        graph = build_source_graph(NUMILLIAN_NPC_TABLE_MD)
        atoms = graph.get("atoms", [])
        npc_names = {a["name"] for a in atoms if a.get("type") == "npc"}
        for name in _NUMILLIAN_TRUE_NPC_NAMES:
            self.assertIn(
                name, npc_names,
                f"'{name}' should be a true NPC atom in source graph.",
            )

    def test_graph_npc_count_includes_true_npcs(self):
        """npc_candidates summary count includes the 3 true NPC names."""
        graph = build_source_graph(NUMILLIAN_NPC_TABLE_MD)
        summary = graph.get("summary", {})
        npc_count = summary.get("npc_candidates", 0)
        self.assertGreaterEqual(
            npc_count, 3,
            f"npc_candidates count ({npc_count}) should include at least "
            f"the 3 true NPC names.",
        )


class TestNumillianIdentityTableDirectExtractor(unittest.TestCase):
    """Prove true NPC extraction at the _extract_entity_candidates level."""

    maxDiff = None

    def test_direct_extraction_via_extract_entity_candidates(self):
        """Direct call to _extract_entity_candidates extracts true NPC names."""
        headings = _extract_heading_hierarchy(NUMILLIAN_NPC_TABLE_MD)
        tables = _extract_markdown_tables(NUMILLIAN_NPC_TABLE_MD)
        candidates = _extract_entity_candidates(
            NUMILLIAN_NPC_TABLE_MD, headings, tables,
        )
        candidate_names = [c["name"] for c in candidates]
        for name in _NUMILLIAN_TRUE_NPC_NAMES:
            self.assertIn(
                name, candidate_names,
                f"Direct extraction should include '{name}' as true NPC.",
            )


class TestNumillianFixtureCompleteness(unittest.TestCase):
    """Verify the synthetic fixture contains required elements."""

    def test_fixture_contains_wayne(self):
        self.assertIn("Wayne", NUMILLIAN_NPC_TABLE_MD)

    def test_fixture_contains_irene_laughing_eyes(self):
        self.assertIn("Irene Laughing-Eyes", NUMILLIAN_NPC_TABLE_MD)

    def test_fixture_contains_treever(self):
        self.assertIn("Treever", NUMILLIAN_NPC_TABLE_MD)

    def test_fixture_has_name_header(self):
        self.assertIn("| Name | Role | Location |", NUMILLIAN_NPC_TABLE_MD)

    def test_fixture_has_separator_line(self):
        self.assertIn("|------|------|----------|", NUMILLIAN_NPC_TABLE_MD)


# ---------------------------------------------------------------------------
# Task 1.3: Blueprint NPC roster triage filtering
# ---------------------------------------------------------------------------

def _build_well_graph():
    """Build source graph from Well fixture with deterministic source_hash."""
    h = hashlib.sha256(WELL_OF_RUIN_MD.encode("utf-8")).hexdigest()
    return build_source_graph(WELL_OF_RUIN_MD, source_hash=h), h


def _build_well_triage_report(graph):
    """Build a triage report that rejects Well false NPC names as non-actors.

    Iterates source-graph atoms and creates reject/narrative_phrase decisions
    for any atom whose name matches the known false-positive set.  Returns
    the report dict or None if no false atoms found.
    """
    atoms = graph.get("atoms", [])
    false_set = set(_WELL_FALSE_NPC_NAMES) | {_FULL_EFFECT_SENTENCE}
    decisions = []
    for atom in atoms:
        name = atom.get("name", "")
        if name in false_set:
            candidate_slug = (atom.get("id") or name or "").replace(" ", "_").lower()
            decisions.append(
                build_triage_decision(
                    candidate_text=name,
                    candidate_slug=candidate_slug,
                    proposed_type="npc",
                    adjudicated_type=TYPE_NARRATIVE_PHRASE,
                    decision=DECISION_REJECT,
                    reason=(
                        "Trap/effect table context: not a "
                        "named actor candidate."
                    ),
                )
            )
    if not decisions:
        return None
    return build_entity_candidate_triage_report(decisions)


def _build_numillian_triage_report(graph):
    """Build a triage report that KEEPS all true Numillian NPC names.

    Returns the report dict or None if no true NPC atoms found.
    """
    atoms = graph.get("atoms", [])
    decisions = []
    for atom in atoms:
        name = atom.get("name", "")
        if name in _NUMILLIAN_TRUE_NPC_NAMES:
            candidate_slug = (atom.get("id") or name or "").replace(" ", "_").lower()
            decisions.append(
                build_triage_decision(
                    candidate_text=name,
                    candidate_slug=candidate_slug,
                    proposed_type="npc",
                    adjudicated_type=TYPE_TRUE_NPC,
                    decision=DECISION_KEEP,
                    reason=(
                        "Identity-bearing table NPC, "
                        "keep as true NPC candidate."
                    ),
                )
            )
    if not decisions:
        return None
    return build_entity_candidate_triage_report(decisions)


class TestWellBlueprintNpcRosterWithTriage(unittest.TestCase):
    """Prove _build_npc_roster respects triage exclusions for Well false names.

    Current production code includes false-positive effect labels in the
    source graph and therefore in the blueprint NPC roster when no triage
    report is passed.  When a triage report that rejects these names is
    provided, the existing _build_npc_roster triage check already excludes
    them.  True NPC names from identity-bearing tables are preserved.
    """

    maxDiff = None

    def setUp(self):
        self.graph, self.source_hash = _build_well_graph()
        self.atoms = self.graph.get("atoms", [])
        self.well_triage = _build_well_triage_report(self.graph)

        # Numillian graph for true NPC preservation
        h2 = hashlib.sha256(
            NUMILLIAN_NPC_TABLE_MD.encode("utf-8")
        ).hexdigest()
        self.num_graph = build_source_graph(
            NUMILLIAN_NPC_TABLE_MD, source_hash=h2
        )
        self.num_triage = _build_numillian_triage_report(self.num_graph)

    # -- Without triage (task 2.2: source manifest filtering removes false
    # names from graph, so roster naturally excludes them) -----------------

    def test_without_triage_excludes_awaken(self):
        """Awaken excluded from npc_roster without triage (table filtering)."""
        roster = _build_npc_roster(self.atoms, None, triage_report=None)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn(
            "Awaken", roster_names,
            "Awaken should NOT appear in npc_roster (effect label, "
            "filtered at source-manifest level).",
        )

    def test_without_triage_excludes_enrage(self):
        """Enrage excluded from npc_roster without triage (table filtering)."""
        roster = _build_npc_roster(self.atoms, None, triage_report=None)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn(
            "Enrage", roster_names,
            "Enrage should NOT appear in npc_roster (effect label, "
            "filtered at source-manifest level).",
        )

    def test_without_triage_excludes_full_sentence(self):
        """Full effect sentence excluded without triage (table filtering)."""
        roster = _build_npc_roster(self.atoms, None, triage_report=None)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn(
            _FULL_EFFECT_SENTENCE, roster_names,
            "Full effect sentence should NOT appear in npc_roster "
            "(filtered at source-manifest level).",
        )

    # -- With triage (already works: blueprint code checks triage) ----------

    def test_with_triage_excludes_well_false_names(self):
        """With triage report, all false Well names are excluded from roster.

        This passes now because _build_npc_roster already consults the
        triage report and skips rejected / non-actor adjudicated atoms.
        """
        roster = _build_npc_roster(
            self.atoms, None, triage_report=self.well_triage
        )
        roster_names = [n["display_name"] for n in roster]
        false_set = set(_WELL_FALSE_NPC_NAMES) | {_FULL_EFFECT_SENTENCE}
        for name in false_set:
            self.assertNotIn(
                name, roster_names,
                f"'{name}' must be excluded from npc_roster "
                f"when triage rejects it.",
            )

    def test_with_triage_preserves_numillian_true_npcs(self):
        """True NPC names remain in roster when triage keeps them."""
        num_atoms = self.num_graph.get("atoms", [])
        roster = _build_npc_roster(
            num_atoms, None, triage_report=self.num_triage
        )
        roster_names = [n["display_name"] for n in roster]
        for name in _NUMILLIAN_TRUE_NPC_NAMES:
            self.assertIn(
                name, roster_names,
                f"True NPC '{name}' must remain in npc_roster "
                f"when triage keeps it.",
            )

    def test_with_triage_numillian_roster_count(self):
        """Numillian npc_roster count includes all 3 true NPCs."""
        num_atoms = self.num_graph.get("atoms", [])
        roster = _build_npc_roster(
            num_atoms, None, triage_report=self.num_triage
        )
        self.assertGreaterEqual(
            len(roster), 3,
            f"Numillian roster should contain at least 3 NPCs, "
            f"got {len(roster)}.",
        )


class TestNpcRosterTriageNonActorTypes(unittest.TestCase):
    """Prove _build_npc_roster excludes rejected/non-actor triage decisions
    for all four non-actor adjudicated types (narrative_phrase, plot_note,
    tone_marker, unknown).

    Production _is_triage_blocked_for_npc_roster already handles all four
    types; these tests verify that _build_npc_roster correctly delegates to
    the blocker for each non-actor type.  A kept true NPC control is
    included to prove the exclusion is not a blanket filter.
    """

    maxDiff = None

    def setUp(self):
        # Atoms with stable IDs that can be matched by triage candidate_slug
        self.atoms = [
            {"id": "awaken_effect", "name": "Awaken", "type": "npc"},
            {"id": "plot_note_item", "name": "Plot Note Item", "type": "npc"},
            {"id": "tone_marker_item", "name": "Tone Marker Item", "type": "npc"},
            {"id": "unknown_item", "name": "Unknown Item", "type": "npc"},
            {"id": "kept_npc", "name": "Kept NPC", "type": "npc"},
        ]

    def _build_triage_report(self, adjudicated_type: str) -> dict:
        """Build a triage report with one decision for each non-keep atom."""
        decisions = []
        for atom in self.atoms:
            name = atom.get("name", "")
            if name == "Kept NPC":
                # Keep as true NPC
                decisions.append(
                    build_triage_decision(
                        candidate_text=name,
                        candidate_slug="kept_npc",
                        proposed_type="npc",
                        adjudicated_type=TYPE_TRUE_NPC,
                        decision=DECISION_KEEP,
                        reason="True NPC, keep in roster.",
                    )
                )
            else:
                # Reject with the specified non-actor type
                decisions.append(
                    build_triage_decision(
                        candidate_text=name,
                        candidate_slug=atom["id"],
                        proposed_type="npc",
                        adjudicated_type=adjudicated_type,
                        decision=DECISION_REJECT,
                        reason=f"Non-actor ({adjudicated_type}), exclude.",
                    )
                )
        return build_entity_candidate_triage_report(decisions)

    # -- narrative_phrase (baseline, already tested via Well fixture) ---------

    def test_narrative_phrase_excluded(self):
        """narrative_phrase adjudicated type is excluded from roster."""
        report = self._build_triage_report(TYPE_NARRATIVE_PHRASE)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn("Awaken", roster_names)
        self.assertNotIn("Plot Note Item", roster_names)
        self.assertNotIn("Tone Marker Item", roster_names)
        self.assertNotIn("Unknown Item", roster_names)
        self.assertEqual(roster_names, ["Kept NPC"])

    # -- plot_note -----------------------------------------------------------

    def test_plot_note_excluded(self):
        """plot_note adjudicated type is excluded from roster."""
        report = self._build_triage_report(TYPE_PLOT_NOTE)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn("Plot Note Item", roster_names)
        self.assertIn("Kept NPC", roster_names)

    def test_plot_note_excludes_all(self):
        """plot_note excludes all non-kept atoms, keeps only kept NPC."""
        report = self._build_triage_report(TYPE_PLOT_NOTE)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertEqual(
            roster_names, ["Kept NPC"],
            "Only the kept true NPC should remain in roster.",
        )

    # -- tone_marker ---------------------------------------------------------

    def test_tone_marker_excluded(self):
        """tone_marker adjudicated type is excluded from roster."""
        report = self._build_triage_report(TYPE_TONE_MARKER)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn("Tone Marker Item", roster_names)
        self.assertIn("Kept NPC", roster_names)

    def test_tone_marker_excludes_all(self):
        """tone_marker excludes all non-kept atoms, keeps only kept NPC."""
        report = self._build_triage_report(TYPE_TONE_MARKER)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertEqual(
            roster_names, ["Kept NPC"],
            "Only the kept true NPC should remain in roster.",
        )

    # -- unknown -------------------------------------------------------------

    def test_unknown_excluded(self):
        """unknown adjudicated type is excluded from roster."""
        report = self._build_triage_report(TYPE_UNKNOWN)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertNotIn("Unknown Item", roster_names)
        self.assertIn("Kept NPC", roster_names)

    def test_unknown_excludes_all(self):
        """unknown excludes all non-kept atoms, keeps only kept NPC."""
        report = self._build_triage_report(TYPE_UNKNOWN)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertEqual(
            roster_names, ["Kept NPC"],
            "Only the kept true NPC should remain in roster.",
        )

    # -- True NPC keep control -----------------------------------------------

    def test_kept_true_npc_preserved(self):
        """A kept true NPC appears in roster even when mixed with rejected
        non-actors of various types."""
        report = self._build_triage_report(TYPE_PLOT_NOTE)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        roster_names = [n["display_name"] for n in roster]
        self.assertIn(
            "Kept NPC", roster_names,
            "Kept true NPC must appear in roster.",
        )

    def test_kept_true_npc_entry_structure(self):
        """Kept NPC entry has expected structure fields."""
        report = self._build_triage_report(TYPE_TONE_MARKER)
        roster = _build_npc_roster(self.atoms, None, triage_report=report)
        self.assertEqual(len(roster), 1, "Only one NPC should survive.")
        entry = roster[0]
        self.assertEqual(entry.get("display_name"), "Kept NPC")
        self.assertEqual(entry.get("atom_id"), "kept_npc")
        self.assertIn("aliases", entry)
        self.assertIn("role", entry)
        self.assertIn("faction", entry)
        self.assertIn("location_binding", entry)
        self.assertIn("scene_presence", entry)
        self.assertIn("criticality", entry)
        self.assertIn("source_refs", entry)


class TestWellBlueprintGenerateWithTriage(unittest.TestCase):
    """Prove generate_builder_blueprint npc_roster respects triage exclusions.

    End-to-end check: building a full blueprint from Well source graph
    with a triage report that rejects false names must produce an
    npc_roster that excludes them.  Without triage, they remain (current
    baseline).
    """

    maxDiff = None

    def setUp(self):
        self.graph, self.source_hash = _build_well_graph()
        self.minimal_packet = {
            "title": "Well of Ruin",
            "adventure_summary": (
                "A deadly magical trap encounter."
            ),
            "source_hash": self.source_hash,
        }
        self.well_triage = _build_well_triage_report(self.graph)

    # -- Without triage (task 2.2: source-manifest filtering applies) ------

    def test_without_triage_npc_roster_excludes_awaken(self):
        """generate_builder_blueprint excludes Awaken without triage."""
        bp = generate_builder_blueprint(
            source_graph=self.graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.minimal_packet,
            fidelity_report=None,
            triage_report=None,
        )
        roster_names = [n["display_name"] for n in bp.get("npc_roster", [])]
        self.assertNotIn("Awaken", roster_names)

    def test_without_triage_npc_roster_excludes_enrage(self):
        """generate_builder_blueprint excludes Enrage without triage."""
        bp = generate_builder_blueprint(
            source_graph=self.graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.minimal_packet,
            fidelity_report=None,
            triage_report=None,
        )
        roster_names = [n["display_name"] for n in bp.get("npc_roster", [])]
        self.assertNotIn("Enrage", roster_names)

    def test_without_triage_npc_roster_excludes_full_sentence(self):
        """generate_builder_blueprint excludes full effect sentence without triage."""
        bp = generate_builder_blueprint(
            source_graph=self.graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.minimal_packet,
            fidelity_report=None,
            triage_report=None,
        )
        roster_names = [n["display_name"] for n in bp.get("npc_roster", [])]
        self.assertNotIn(_FULL_EFFECT_SENTENCE, roster_names)

    # -- With triage (should pass: already wired) --------------------------

    def test_with_triage_npc_roster_excludes_well_false_names(self):
        """With triage report, generate_builder_blueprint npc_roster
        excludes false Well names."""
        bp = generate_builder_blueprint(
            source_graph=self.graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.minimal_packet,
            fidelity_report=None,
            triage_report=self.well_triage,
        )
        roster_names = [n["display_name"] for n in bp.get("npc_roster", [])]
        false_set = set(_WELL_FALSE_NPC_NAMES) | {_FULL_EFFECT_SENTENCE}
        for name in false_set:
            self.assertNotIn(
                name, roster_names,
                f"'{name}' must be excluded from blueprint npc_roster "
                f"when triage rejects it.",
            )

    def test_with_triage_blueprint_structure_valid(self):
        """Blueprinted generated with triage has valid structure."""
        bp = generate_builder_blueprint(
            source_graph=self.graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.minimal_packet,
            fidelity_report=None,
            triage_report=self.well_triage,
        )
        self.assertIn("npc_roster", bp)
        self.assertIn("blueprint_version", bp)
        self.assertIn("module", bp)
        self.assertEqual(
            bp.get("module", {}).get("title"), "Well of Ruin",
        )


class TestWellBuildFidelityBlockers(unittest.TestCase):
    """Prove build-fidelity path currently produces Required npc blockers
    for Well false-positive names, and the future invariant that they must
    not do so.

    Tests exercise _find_required_atoms (reads source graph) and
    _check_atoms_vs_module (compares required atoms against module output
    which has no matching NPCs for the false names).  This is the path
    that would produce ``Required npc 'Awaken' not found in module``.
    """

    maxDiff = None

    def setUp(self):
        self.graph, self.source_hash = _build_well_graph()
        self.required = _find_required_atoms(self.graph)
        self.npc_atoms = self.required.get("npc", [])
        # Empty module: no NPCs or monsters to match against
        self.empty_module = {"npcs": [], "monsters": [], "areas": []}

    # -- Task 2.2: false names no longer in required atoms -----------------

    def test_find_required_atoms_excludes_awaken(self):
        """find_required_atoms excludes Awaken (effect table filtered)."""
        names = {a.get("name", "") for a in self.npc_atoms}
        self.assertNotIn(
            "Awaken", names,
            "Awaken should NOT be a required npc atom (table filtering).",
        )

    def test_find_required_atoms_excludes_enrage(self):
        """find_required_atoms excludes Enrage (effect table filtered)."""
        names = {a.get("name", "") for a in self.npc_atoms}
        self.assertNotIn(
            "Enrage", names,
            "Enrage should NOT be a required npc atom (table filtering).",
        )

    def test_find_required_atoms_excludes_full_sentence(self):
        """find_required_atoms excludes full effect sentence."""
        names = {a.get("name", "") for a in self.npc_atoms}
        self.assertNotIn(
            _FULL_EFFECT_SENTENCE, names,
            "Full effect sentence should NOT be a required npc atom.",
        )

    def test_find_required_atoms_excludes_all_well_false_names(self):
        """All 8 Well false effect-label names are excluded from
        required npc atoms."""
        names = {a.get("name", "") for a in self.npc_atoms}
        for false_name in _WELL_FALSE_NPC_NAMES:
            self.assertNotIn(
                false_name, names,
                f"'{false_name}' should NOT be a required npc atom "
                f"(effect table filtered).",
            )

    # -- Task 2.2: no Required npc blockers for false names ----------------

    def test_no_required_npc_blocker_for_awaken(self):
        """No blocker message equals 'Required npc 'Awaken' ...'."""
        blockers, _ = _check_atoms_vs_module(
            "npc", self.npc_atoms, self.empty_module
        )
        for b in blockers:
            self.assertNotEqual(
                b.get("message", "").split("'", 2)[:2],
                ["Required npc ", "Awaken"],
                "No Required npc blocker should target 'Awaken'.",
            )

    def test_no_required_npc_blocker_for_enrage(self):
        """No blocker message equals 'Required npc 'Enrage' ...'."""
        blockers, _ = _check_atoms_vs_module(
            "npc", self.npc_atoms, self.empty_module
        )
        for b in blockers:
            self.assertNotEqual(
                b.get("message", "").split("'", 2)[:2],
                ["Required npc ", "Enrage"],
                "No Required npc blocker should target 'Enrage'.",
            )

    def test_no_required_npc_blocker_for_full_sentence(self):
        """No blocker message contains full effect sentence."""
        blockers, _ = _check_atoms_vs_module(
            "npc", self.npc_atoms, self.empty_module
        )
        for b in blockers:
            self.assertNotIn(
                _FULL_EFFECT_SENTENCE, b.get("message", ""),
                "No Required npc blocker should mention the full sentence.",
            )

    def test_no_required_npc_blockers_for_any_well_false_name(self):
        """Zero 'Required npc' blockers for any of the 8 false Well names
        or the full effect sentence."""
        blockers, _ = _check_atoms_vs_module(
            "npc", self.npc_atoms, self.empty_module
        )
        self.assertEqual(
            len(blockers), 0,
            f"Expected 0 Required npc blockers for Well false names, "
            f"got {len(blockers)}: "
            f"{[b.get('message') for b in blockers]}",
        )

    # -- Positive check: exact blocker message format -----------------------

    def test_blocker_message_format(self):
        """Required npc blocker message follows 'Required npc '<name>' ...'."""
        blockers, _ = _check_atoms_vs_module(
            "npc", self.npc_atoms, self.empty_module
        )
        for b in blockers:
            msg = b.get("message", "")
            self.assertTrue(
                msg.startswith("Required npc '"),
                f"Blocker message should start with "
                f"'Required npc '': {msg}",
            )

    # -- Positive control: a truly missing NPC still produces a blocker -----

    def test_positive_control_missing_npc_produces_blocker(self):
        """A genuinely missing NPC atom still produces a Required npc
        blocker.  Positive control: proves fidelity gating is not weakened
        by the false-name filtering.  A synthetic NPC atom 'MissingHero'
        passed to _check_atoms_vs_module with an empty module must produce
        the expected blocker.
        """
        synthetic_atoms = [
            {"name": "MissingHero", "type": "npc", "source_atom_id": "test_001"}
        ]
        blockers, _ = _check_atoms_vs_module(
            "npc", synthetic_atoms, self.empty_module
        )
        expected_msg = "Required npc 'MissingHero' not found in module"
        self.assertEqual(
            len(blockers), 1,
            "A missing real NPC atom must produce exactly one blocker.",
        )
        self.assertEqual(
            blockers[0]["message"], expected_msg,
            "Blocker message must match the expected format.",
        )

    def test_positive_control_missing_npc_message_format(self):
        """Blocker message for missing NPC follows exact required format."""
        synthetic_atoms = [
            {"name": "LostKnight", "type": "npc", "source_atom_id": "test_002"}
        ]
        blockers, _ = _check_atoms_vs_module(
            "npc", synthetic_atoms, self.empty_module
        )
        self.assertEqual(len(blockers), 1)
        msg = blockers[0]["message"]
        self.assertTrue(
            msg.startswith("Required npc '"),
            f"Message must start with 'Required npc '': {msg}",
        )
        self.assertIn(
            "LostKnight", msg,
            "Message must contain the missing NPC name.",
        )
        self.assertTrue(
            msg.endswith("not found in module"),
            f"Message must end with 'not found in module': {msg}",
        )


# ---------------------------------------------------------------------------
# Task 3.1: Prefilter extension for full sentences and mechanic verbs
# ---------------------------------------------------------------------------

class TestPrefilterNonActorExtension(unittest.TestCase):
    """Prove build_prefilter_decision now rejects full sentences/long clauses
    and one-word mechanic/effect verbs when context indicates mechanics
    material, while preserving true one-word NPC names."""

    maxDiff = None

    # -- Full sentences with period ---------------------------------------

    def test_full_sentence_with_period_rejected(self):
        """Full sentence ending with period is rejected as narrative_phrase."""
        candidate = {
            "candidate_text": "Mundane objects worth at least 1 gp become sentient and hostile.",
            "candidate_slug": "mundane_objects_become_sentient",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    def test_short_sentence_with_period_rejected(self):
        """Short sentence ending with period is also rejected."""
        candidate = {
            "candidate_text": "The trap activates.",
            "candidate_slug": "the_trap_activates",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    # -- Long clauses without period --------------------------------------

    def test_long_clause_mixed_case_rejected(self):
        """Long clause (6+ words with lowercase-starting words) rejected."""
        candidate = {
            "candidate_text": "The ancient corridor stretches into darkness and decay",
            "candidate_slug": "ancient_corridor_stretches",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    def test_long_clause_no_period_rejected(self):
        """Long effect-like clause without period is still rejected."""
        candidate = {
            "candidate_text": "All creatures within 30 feet must make a DC 15 Wisdom save",
            "candidate_slug": "creatures_30ft_wisdom_save",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)

    # -- Short multi-word title-cased text (NPC names) --------------------

    def test_multi_word_title_cased_npc_pass(self):
        """Short multi-word title-cased NPC name is NOT rejected."""
        candidate = {
            "candidate_text": "Irene Laughing-Eyes",
            "candidate_slug": "irene_laughing_eyes",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_three_word_location_name_pass(self):
        """Three-word title-cased location name is NOT rejected."""
        candidate = {
            "candidate_text": "The Gilded Tankard",
            "candidate_slug": "the_gilded_tankard",
            "proposed_type": "location",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_hyphenated_npc_name_pass(self):
        """Hyphenated compound NPC name passes through."""
        candidate = {
            "candidate_text": "Kaelen Swiftarrow",
            "candidate_slug": "kaelen_swiftarrow",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_four_word_npc_title_pass(self):
        """4-word title-cased entity name is NOT rejected (not a clause)."""
        candidate = {
            "candidate_text": "High Priestess of Shadows",
            "candidate_slug": "high_priestess_of_shadows",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    # -- One-word mechanic verbs with mechanics context -------------------

    def test_awaken_in_trap_context_rejected(self):
        """'Awaken' with trap/effect context is rejected."""
        candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source_refs": [{"section": "Complex Trap", "context": "trap effect table"}],
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)

    def test_enrage_in_effect_context_rejected(self):
        """'Enrage' with effect table context is rejected."""
        candidate = {
            "candidate_text": "Enrage",
            "candidate_slug": "enrage",
            "proposed_type": "npc",
            "source_refs": [{"section": "Effect", "context": "d100 table result"}],
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)

    def test_overwhelm_in_spell_context_rejected(self):
        """'Overwhelm' with spell context is rejected."""
        candidate = {
            "candidate_text": "Overwhelm",
            "candidate_slug": "overwhelm",
            "proposed_type": "npc",
            "source_role": "spell_effect",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)

    # -- One-word mechanic verbs WITHOUT mechanics context ----------------

    def test_awaken_without_context_pass(self):
        """'Awaken' without mechanics context is NOT rejected
        (could be a true entity name)."""
        candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source_refs": [{"section": "NPC Roster", "context": "town guard roster"}],
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_menace_without_context_pass(self):
        """'Menace' without mechanics context is NOT rejected."""
        candidate = {
            "candidate_text": "Menace",
            "candidate_slug": "menace",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    # -- True one-word NPC names ------------------------------------------

    def test_true_one_word_npc_name_pass(self):
        """True one-word NPC name 'Wayne' is NOT rejected."""
        candidate = {
            "candidate_text": "Wayne",
            "candidate_slug": "wayne",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_true_one_word_npc_name_treever_pass(self):
        """True one-word NPC name 'Treever' is NOT rejected."""
        candidate = {
            "candidate_text": "Treever",
            "candidate_slug": "treever",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    def test_one_word_location_name_pass(self):
        """One-word location name 'Cathedral' is NOT rejected."""
        candidate = {
            "candidate_text": "Cathedral",
            "candidate_slug": "cathedral",
            "proposed_type": "location",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    # -- Existing lowercase prose still rejected --------------------------

    def test_lowercase_conjunction_prose_still_rejected(self):
        """Lowercase conjunction-starting prose is still rejected by
        the original looks_like_narrative_phrase check."""
        candidate = {
            "candidate_text": "but this is not true",
            "candidate_slug": "but_this_is_not_true",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    # -- Schema validation ------------------------------------------------

    def test_rejected_decision_schema(self):
        """Rejected decision contains all expected schema keys."""
        candidate = {
            "candidate_text": "Mundane objects worth at least 1 gp become sentient and hostile.",
            "candidate_slug": "mundane_sentence",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIn("candidate_text", decision)
        self.assertIn("candidate_slug", decision)
        self.assertIn("proposed_type", decision)
        self.assertIn("adjudicated_type", decision)
        self.assertIn("decision", decision)
        self.assertIn("reason", decision)

    def test_mechanic_rejected_decision_schema(self):
        """Mechanic-verb decision also follows schema."""
        candidate = {
            "candidate_text": "Enthrall",
            "candidate_slug": "enthrall",
            "proposed_type": "npc",
            "source_refs": [{"section": "Effect", "context": "trap"}],
        }
        decision = build_prefilter_decision(candidate)
        self.assertIn("candidate_text", decision)
        self.assertIn("candidate_slug", decision)
        self.assertIn("proposed_type", decision)
        self.assertIn("adjudicated_type", decision)
        self.assertIn("decision", decision)
        self.assertIn("reason", decision)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)

    # -- Empty/missing safe handling --------------------------------------

    def test_empty_candidate_returns_none(self):
        """Empty or missing candidate fields return None."""
        self.assertIsNone(build_prefilter_decision({}))
        self.assertIsNone(build_prefilter_decision({"candidate_text": ""}))
        self.assertIsNone(build_prefilter_decision({"candidate_text": "test"}))

    def test_one_word_candidate_not_in_verb_set_passes(self):
        """One-word capitalized non-verb 'Deflation' passes prefilter."""
        candidate = {
            "candidate_text": "Deflation",
            "candidate_slug": "deflation",
            "proposed_type": "npc",
        }
        self.assertIsNone(build_prefilter_decision(candidate))

    # -- Over-broad mechanics-context regression test ---------------------

    def test_awaken_as_true_npc_from_identity_table_not_rejected(self):
        """'Awaken' from identity-bearing NPC table with source='table_cell'
        and identity context is NOT rejected.  Regression for over-broad
        mechanics-context check where 'source':'table_cell' or
        'context':'Table: ...' falsely triggered the 'table' keyword."""
        candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source": "table_cell",
            "context": "Table: NPC Name, Role, Location -> Awaken",
            "section": "NPC Roster",
        }
        self.assertIsNone(
            build_prefilter_decision(candidate),
            "Awaken from identity-bearing NPC table should NOT be "
            "rejected. source='table_cell' alone must not imply "
            "mechanics context.",
        )


# ---------------------------------------------------------------------------
# Task 3.2: Prefilter decisions and underbound NPC findings
# ---------------------------------------------------------------------------
# Rejected non-actors (full sentences, mechanic verbs) MUST NOT create
# underbound NPC warnings/blockers.  Kept true NPCs without bindings
# MAY still warn according to existing underbound NPC rules.

class TestPrefilterUnderboundNpc(unittest.TestCase):
    """Prove prefilter-rejected non-actors do not create underbound NPC
    warnings/blockers while kept true NPCs may still warn per existing
    rules."""

    maxDiff = None

    # -- Prefilter-rejected full sentence ---------------------------------

    def test_rejected_full_sentence_no_underbound_warning(self):
        """Prefilter-rejected full sentence does not create underbound
        NPC warning."""
        candidate = {
            "candidate_text": (
                "Mundane objects worth at least 1 gp become "
                "sentient and hostile."
            ),
            "candidate_slug": "mundane_objects_sentient",
            "proposed_type": "npc",
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        self.assertEqual(decision["adjudicated_type"], TYPE_NARRATIVE_PHRASE)
        findings = build_underbound_npc_findings([decision])
        self.assertEqual(
            len(findings["warnings"]), 0,
            "Rejected full sentence must not produce underbound NPC "
            "warnings.",
        )
        self.assertEqual(
            len(findings["blockers"]), 0,
            "Rejected full sentence must not produce underbound NPC "
            "blockers.",
        )

    def test_rejected_full_sentence_no_underbound_mixed(self):
        """Prefilter-rejected full sentence stays clean even when mixed
        with other decisions."""
        sentence_candidate = {
            "candidate_text": "The trap activates instantly.",
            "candidate_slug": "trap_activates",
            "proposed_type": "npc",
        }
        sentence_dec = build_prefilter_decision(sentence_candidate)
        self.assertIsNotNone(sentence_dec)
        self.assertEqual(sentence_dec["decision"], DECISION_REJECT)
        unbound_dec = build_triage_decision(
            candidate_text="UnboundNPC",
            candidate_slug="unboundnpc",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="Kept true NPC without bindings.",
        )
        findings = build_underbound_npc_findings([
            sentence_dec, unbound_dec,
        ])
        self.assertEqual(
            len(findings["warnings"]), 1,
            "Only the kept NPC without bindings should produce a "
            "warning; the rejected sentence must not.",
        )
        self.assertIn(
            "UnboundNPC", findings["warnings"][0]["finding"],
        )

    # -- Prefilter-rejected mechanic verb ---------------------------------

    def test_rejected_mechanic_verb_no_underbound_warning(self):
        """Prefilter-rejected mechanic/effect verb does not create
        underbound NPC warning."""
        candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source_refs": [{
                "section": "Complex Trap",
                "context": "trap effect table",
            }],
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        findings = build_underbound_npc_findings([decision])
        self.assertEqual(
            len(findings["warnings"]), 0,
            "Rejected mechanic verb must not produce underbound NPC "
            "warnings.",
        )
        self.assertEqual(
            len(findings["blockers"]), 0,
            "Rejected mechanic verb must not produce underbound NPC "
            "blockers.",
        )

    def test_rejected_enrage_no_underbound_warning(self):
        """'Enrage' rejected by prefilter produces no underbound NPC
        warning."""
        candidate = {
            "candidate_text": "Enrage",
            "candidate_slug": "enrage",
            "proposed_type": "npc",
            "source_refs": [{
                "section": "Effect",
                "context": "d100 table result",
            }],
        }
        decision = build_prefilter_decision(candidate)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], DECISION_REJECT)
        findings = build_underbound_npc_findings([decision])
        self.assertEqual(len(findings["warnings"]), 0)
        self.assertEqual(len(findings["blockers"]), 0)

    def test_rejected_mechanic_verb_plus_kept_unbound_mixed(self):
        """Rejected mechanic verb stays clean in mixed context with
        a kept unbound NPC."""
        awaken_candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source_refs": [{
                "section": "Complex Trap",
                "context": "trap effect table",
            }],
        }
        awaken_dec = build_prefilter_decision(awaken_candidate)
        self.assertIsNotNone(awaken_dec)
        self.assertEqual(awaken_dec["decision"], DECISION_REJECT)
        unbound_dec = build_triage_decision(
            candidate_text="LostSoul",
            candidate_slug="lost_soul",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="Kept true NPC without bindings.",
        )
        findings = build_underbound_npc_findings([
            awaken_dec, unbound_dec,
        ])
        self.assertEqual(
            len(findings["warnings"]), 1,
            "Only the kept NPC should warn; rejected verb must not.",
        )
        self.assertIn("LostSoul", findings["warnings"][0]["finding"])

    # -- Control: kept true NPC without bindings still warns ---------------

    def test_kept_true_npc_without_bindings_produces_warning(self):
        """A kept TYPE_TRUE_NPC without location/plot/faction bindings
        or source_role produces an underbound NPC warning (control)."""
        decision = build_triage_decision(
            candidate_text="Wanderer",
            candidate_slug="wanderer",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="True NPC candidate from identity-bearing source.",
        )
        self.assertEqual(decision["decision"], DECISION_KEEP)
        self.assertEqual(decision["adjudicated_type"], TYPE_TRUE_NPC)
        findings = build_underbound_npc_findings([decision])
        self.assertEqual(
            len(findings["warnings"]), 1,
            "Kept true NPC without bindings MUST produce an underbound "
            "NPC warning per existing rules.",
        )
        self.assertEqual(len(findings["blockers"]), 0)
        self.assertIn("Wanderer", findings["warnings"][0]["finding"])

    def test_kept_bound_npc_no_warning(self):
        """A kept TYPE_TRUE_NPC with location bindings does NOT produce
        an underbound NPC warning (control)."""
        decision = build_triage_decision(
            candidate_text="SettledNPC",
            candidate_slug="settled_npc",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="True NPC with location binding.",
            location_bindings=["The Gilded Tankard"],
        )
        findings = build_underbound_npc_findings([decision])
        self.assertEqual(
            len(findings["warnings"]), 0,
            "Bound NPC should not warn.",
        )

    # -- Report-level summary tests ---------------------------------------

    def test_report_summary_rejected_non_actors_zero_underbound(self):
        """Report summary counts rejected/non_actor for prefilter-rejected
        decisions but underbound_npcs remains 0."""
        sentence_candidate = {
            "candidate_text": "All creatures within 30 feet "
                              "must make a DC 15 Wisdom save.",
            "candidate_slug": "creatures_30ft_wisdom_save",
            "proposed_type": "npc",
        }
        sentence_dec = build_prefilter_decision(sentence_candidate)
        self.assertIsNotNone(sentence_dec)
        awaken_candidate = {
            "candidate_text": "Awaken",
            "candidate_slug": "awaken",
            "proposed_type": "npc",
            "source_refs": [{
                "section": "Effect",
                "context": "trap effect table",
            }],
        }
        awaken_dec = build_prefilter_decision(awaken_candidate)
        self.assertIsNotNone(awaken_dec)
        report = build_entity_candidate_triage_report(
            [sentence_dec, awaken_dec],
        )
        self.assertEqual(report.get("total_candidates"), 2)
        summary = report.get("summary", {})
        self.assertEqual(summary.get("rejected"), 2)
        self.assertEqual(summary.get("non_actor"), 2)
        self.assertEqual(
            summary.get("underbound_npcs"), 0,
            "underbound_npcs must be 0 when all decisions are rejected "
            "non-actors.",
        )
        self.assertEqual(summary.get("kept"), 0)

    def test_report_summary_mixed_kept_and_rejected(self):
        """Report summary correctly separates kept-bound, kept-unbound,
        and rejected counts."""
        sentence_candidate = {
            "candidate_text": (
                "Mundane objects worth at least 1 gp become "
                "sentient and hostile."
            ),
            "candidate_slug": "mundane_objects",
            "proposed_type": "npc",
        }
        sentence_dec = build_prefilter_decision(sentence_candidate)
        self.assertIsNotNone(sentence_dec)
        bound_dec = build_triage_decision(
            candidate_text="BoundNPC",
            candidate_slug="bound_npc",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="True NPC with location binding.",
            location_bindings=["The Crypts"],
        )
        unbound_dec = build_triage_decision(
            candidate_text="UnboundNPC",
            candidate_slug="unbound_npc",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="True NPC without bindings.",
        )
        report = build_entity_candidate_triage_report([
            sentence_dec, bound_dec, unbound_dec,
        ])
        self.assertEqual(report.get("total_candidates"), 3)
        summary = report.get("summary", {})
        self.assertEqual(summary.get("rejected"), 1)
        self.assertEqual(summary.get("non_actor"), 1)
        self.assertEqual(summary.get("kept"), 2)
        self.assertEqual(
            summary.get("underbound_npcs"), 1,
            "underbound_npcs should count only the kept NPC without "
            "bindings, not the rejected sentence or the bound NPC.",
        )

    def test_report_summary_no_kept_npcs_zero_underbound(self):
        """Report with only rejected non-actors has underbound_npcs = 0."""
        cand1 = {
            "candidate_text": "The trap activates.",
            "candidate_slug": "trap_activates",
            "proposed_type": "npc",
        }
        cand2 = {
            "candidate_text": "Irradiate",
            "candidate_slug": "irradiate",
            "proposed_type": "npc",
            "source_refs": [{
                "section": "Effect", "context": "d100 table",
            }],
        }
        dec1 = build_prefilter_decision(cand1)
        dec2 = build_prefilter_decision(cand2)
        self.assertIsNotNone(dec1)
        self.assertIsNotNone(dec2)
        report = build_entity_candidate_triage_report([dec1, dec2])
        self.assertEqual(report.get("total_candidates"), 2)
        summary = report.get("summary", {})
        self.assertEqual(summary.get("rejected"), 2)
        self.assertEqual(summary.get("non_actor"), 2)
        self.assertEqual(summary.get("underbound_npcs"), 0)
        self.assertEqual(summary.get("kept"), 0)


if __name__ == "__main__":
    unittest.main()
