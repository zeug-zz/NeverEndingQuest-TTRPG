# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit Final Blocker Classifier
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import unittest
import tempfile
from pathlib import Path

from utils.toolkit_final_blocker_classifier import classify_final_build_blockers


class TestFinalBlockerClassifier(unittest.TestCase):
    """Test the final blocker classifier contract."""

    def test_passing_report_returns_no_blockers(self):
        """Passing report should return status: no_blockers."""
        report = {
            "status": "pass",
            "can_continue": True,
            "blockers": [],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "no_blockers")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 0)
        self.assertEqual(result["editorial_count"], 0)
        self.assertEqual(result["fatal_blockers"], [])
        self.assertEqual(result["editorial_blockers"], [])
        self.assertEqual(result["warnings"], [])

    def test_zero_blockers_returns_no_blockers(self):
        """Report with zero blockers should return status: no_blockers."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "no_blockers")
        self.assertFalse(result["can_attempt_final_reconciliation"])

    def test_missing_report_returns_unknown(self):
        """None report should return status: unknown."""
        result = classify_final_build_blockers(None)
        
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["type"], "invalid_input")

    def test_non_dict_report_returns_unknown(self):
        """Non-dict report should return status: unknown."""
        result = classify_final_build_blockers("not a dict")
        
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["type"], "invalid_input")

    def test_missing_module_dir_returns_fatal(self):
        """Missing module_dir when supplied should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dir = Path(tmpdir) / "nonexistent"
            result = classify_final_build_blockers(report, module_dir=fake_dir)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["fatal_blockers"][0]["type"], "missing_module_directory")

    def test_required_location_blocker_returns_editorial(self):
        """Required location blocker should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                }
            ],
            "refusal_reason": "Required location 'Trigger' not found in module",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)
        self.assertEqual(result["editorial_blockers"][0]["category"], "location")
        self.assertEqual(result["editorial_blockers"][0]["source_atom_id"], "loc_trigger")

    def test_well_terms_return_editorial(self):
        """Well terms (Trigger, Passive Element, Active Element) should be editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                },
                {
                    "message": "Required location 'Passive Element' not found in module",
                    "category": "location",
                },
                {
                    "message": "Required location 'Active Element' not found in module",
                    "category": "location",
                },
            ],
            "refusal_reason": "Required location 'Trigger' not found in module; Required location 'Passive Element' not found in module; Required location 'Active Element' not found in module",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 3)
        for blocker in result["editorial_blockers"]:
            self.assertEqual(blocker["category"], "location")

    def test_invalid_json_returns_fatal(self):
        """Invalid JSON blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in module_context.json",
                    "category": "structural",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_missing_required_artifacts_returns_fatal(self):
        """Missing required artifacts blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Missing required artifact: module_context.json",
                    "category": "structural",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_mixed_fatal_editorial_returns_mixed(self):
        """Mixed fatal + editorial blockers should return status: mixed."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in module_context.json",
                    "category": "structural",
                },
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                },
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "mixed")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 1)

    def test_original_refusal_reason_preserved(self):
        """Original refusal reason should be preserved in result."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                }
            ],
            "refusal_reason": "Required location 'Trigger' not found in module",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(
            result["original_refusal_reason"],
            "Required location 'Trigger' not found in module"
        )

    def test_blocker_metadata_preserved(self):
        """Original blocker message/category/source_atom_id should be preserved."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        blocker = result["editorial_blockers"][0]
        self.assertEqual(blocker["message"], "Required location 'Trigger' not found in module")
        self.assertEqual(blocker["category"], "location")
        self.assertEqual(blocker["source_atom_id"], "loc_trigger")
        self.assertEqual(blocker["raw"]["message"], "Required location 'Trigger' not found in module")

    def test_input_report_not_mutated(self):
        """Input report should not be mutated."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                }
            ],
        }
        original_blockers = report["blockers"].copy()
        
        classify_final_build_blockers(report)
        
        self.assertEqual(report["blockers"], original_blockers)

    def test_unknown_only_blocker_returns_unknown(self):
        """Unknown-only blocker should return status: unknown."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Some unknown issue",
                    "category": "unknown_category",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["type"], "unknown")

    def test_fatal_and_editorial_counts_correct(self):
        """fatal_count and editorial_count should be correct."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in module_context.json",
                    "category": "structural",
                },
                {
                    "message": "Schema validation failed",
                    "category": "structural",
                },
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                },
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "npc",
                },
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["fatal_count"], 2)
        self.assertEqual(result["editorial_count"], 2)

    def test_missing_module_dir_is_fatal_even_when_report_passes(self):
        """Missing module_dir should be fatal even if report status is pass."""
        report = {
            "status": "pass",
            "can_continue": True,
            "blockers": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dir = Path(tmpdir) / "nonexistent"
            result = classify_final_build_blockers(report, module_dir=fake_dir)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["fatal_blockers"][0]["type"], "missing_module_directory")

    def test_report_paths_preserved_when_present(self):
        """Report paths should be preserved from input report."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                }
            ],
            "report_path": "/path/to/report.json",
            "source_fidelity_report_path": "/path/to/source_fidelity.json",
            "build_fidelity_report_path": "/path/to/build_fidelity.json",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["report_paths"]["report_path"], "/path/to/report.json")
        self.assertEqual(result["report_paths"]["source_fidelity_report_path"], "/path/to/source_fidelity.json")
        self.assertEqual(result["report_paths"]["build_fidelity_report_path"], "/path/to/build_fidelity.json")

    def test_missing_canonical_artifact_returns_fatal(self):
        """Missing canonical artifact blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Missing canonical artifact: module_context.json",
                    "category": "structural",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_critical_file_missing_returns_fatal(self):
        """Critical file missing blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Critical file missing: module_plot.json",
                    "category": "structural",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_unrecoverable_topology_returns_fatal(self):
        """Unrecoverable topology blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Unrecoverable topology failure in area connectivity",
                    "category": "topology",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_broken_topology_returns_fatal(self):
        """Broken topology blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Broken topology: disconnected areas detected",
                    "category": "topology",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_no_valid_topology_returns_fatal(self):
        """No valid topology blocker should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "No valid topology graph could be constructed",
                    "category": "topology",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_schema_category_returns_fatal(self):
        """Blocker with schema category should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Schema validation error in module_context.json",
                    "category": "schema",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_topology_category_returns_fatal(self):
        """Blocker with topology category should return status: fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Area connectivity validation failed",
                    "category": "topology",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_fatal_category_without_fatal_message_returns_fatal(self):
        """Blocker with fatal category but no fatal message keywords should still be fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Some structural issue",
                    "category": "structural",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)

    def test_npc_category_returns_editorial(self):
        """Blocker with npc category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "npc",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_puzzle_category_returns_editorial(self):
        """Blocker with puzzle category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required puzzle 'Skull Riddle' not found in module",
                    "category": "puzzle",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_clue_category_returns_editorial(self):
        """Blocker with clue category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required clue 'Ancient Map' not found in module",
                    "category": "clue",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_item_category_returns_editorial(self):
        """Blocker with item category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required item 'Magic Sword' not found in module",
                    "category": "item",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_encounter_category_returns_editorial(self):
        """Blocker with encounter category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required encounter 'Dragon Fight' not found in module",
                    "category": "encounter",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_plot_beat_category_returns_editorial(self):
        """Blocker with plot_beat category should return status: editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required plot beat 'Betrayal' not found in module",
                    "category": "plot_beat",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_location(self):
        """Message pattern 'Required location' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_npc(self):
        """Message pattern 'Required NPC' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_puzzle(self):
        """Message pattern 'Required puzzle' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required puzzle 'Skull Riddle' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_clue(self):
        """Message pattern 'Required clue' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required clue 'Ancient Map' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_item(self):
        """Message pattern 'Required item' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required item 'Magic Sword' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_encounter(self):
        """Message pattern 'Required encounter' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required encounter 'Dragon Fight' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_message_pattern_fallback_plot_beat(self):
        """Message pattern 'Required plot beat' should be editorial even with generic category."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required plot beat 'Betrayal' not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_fatal_over_editorial_priority(self):
        """Fatal message with editorial category should be classified as fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in location definition",
                    "category": "location",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 0)

    def test_editorial_only_sets_can_attempt_reconciliation(self):
        """Editorial-only blockers should set can_attempt_final_reconciliation to True."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                },
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "npc",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 2)
        self.assertEqual(result["fatal_count"], 0)

    def test_source_fidelity_category_with_not_found_in_module(self):
        """source_fidelity category with 'not found in module' should be editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Some named source element not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_unknown_category_with_bare_not_found_in_module(self):
        """unknown category with bare 'not found in module' should NOT be editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "module_context.json not found in module",
                    "category": "unknown",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 0)

    def test_unknown_category_with_required_location_pattern(self):
        """unknown category with 'Required location' pattern should be editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "unknown",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_unknown_category_with_required_npc_pattern(self):
        """unknown category with 'Required NPC' pattern should be editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "unknown",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)

    def test_editorial_blocker_preserves_message_category_source_atom_id_raw(self):
        """Editorial blocker should preserve message/category/source_atom_id/raw."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                    "extra_field": "should be in raw",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["editorial_blockers"][0]
        self.assertEqual(b["type"], "editorial")
        self.assertEqual(b["message"], "Required location 'Trigger' not found in module")
        self.assertEqual(b["category"], "location")
        self.assertEqual(b["source_atom_id"], "loc_trigger")
        self.assertEqual(b["raw"]["extra_field"], "should be in raw")

    def test_fatal_blocker_preserves_message_category_source_atom_id_raw(self):
        """Fatal blocker should preserve message/category/source_atom_id/raw."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in module_context.json",
                    "category": "structural",
                    "source_atom_id": "struct_json",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["fatal_blockers"][0]
        self.assertEqual(b["type"], "fatal")
        self.assertEqual(b["message"], "Invalid JSON in module_context.json")
        self.assertEqual(b["category"], "structural")
        self.assertEqual(b["source_atom_id"], "struct_json")
        self.assertIsNotNone(b["raw"])

    def test_blocker_preserves_atom_id(self):
        """Blocker with atom_id field should preserve it."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "atom_id": "atom_42",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["editorial_blockers"][0]
        self.assertEqual(b["atom_id"], "atom_42")

    def test_blocker_preserves_source_ref_and_refs(self):
        """Blocker with source_ref/source_refs should preserve them."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_ref": "heading_17",
                    "source_refs": ["heading_17", "heading_22"],
                    "ref": "r_01",
                    "refs": ["r_01", "r_02"],
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["editorial_blockers"][0]
        self.assertEqual(b["source_ref"], "heading_17")
        self.assertEqual(b["source_refs"], ["heading_17", "heading_22"])
        self.assertEqual(b["ref"], "r_01")
        self.assertEqual(b["refs"], ["r_01", "r_02"])

    def test_blocker_preserves_expected_actual_reason(self):
        """Blocker with expected/actual/reason should preserve them."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "expected": "location Trigger",
                    "actual": "location trigger_puzzle",
                    "reason": "Source named 'Trigger' as location but module has 'trigger_puzzle'",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["editorial_blockers"][0]
        self.assertEqual(b["expected"], "location Trigger")
        self.assertEqual(b["actual"], "location trigger_puzzle")
        self.assertEqual(b["reason"], "Source named 'Trigger' as location but module has 'trigger_puzzle'")

    def test_blocker_preserves_severity(self):
        """Blocker with severity should preserve it."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "severity": "warning",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        b = result["editorial_blockers"][0]
        self.assertEqual(b["severity"], "warning")

    def test_nested_report_paths_preserved_and_merged(self):
        """Nested report_paths dict should be merged into report_paths."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [],
            "report_path": "/top/report.json",
            "report_paths": {
                "build_fidelity_report_path": "/nested/bf.json",
                "source_fidelity_report_path": "/nested/sf.json",
            },
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["report_paths"]["report_path"], "/top/report.json")
        self.assertEqual(result["report_paths"]["build_fidelity_report_path"], "/nested/bf.json")
        self.assertEqual(result["report_paths"]["source_fidelity_report_path"], "/nested/sf.json")


class TestFinalBlockerBoundaryContracts(unittest.TestCase):
    """Acceptance-criteria boundary contract tests for the final blocker classifier.

    These tests exercise combined classifier behavior as integration-level
    boundary contracts, complementing the unit-level tests in TestFinalBlockerClassifier.
    """

    def test_fatal_boundary_contract_invalid_json(self):
        """Fatal boundary: structural blocker prevents reconciliation."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Invalid JSON in module_context.json",
                    "category": "structural",
                    "source_atom_id": "struct_01",
                }
            ],
            "refusal_reason": "Invalid JSON in module_context.json",
            "build_fidelity_report_path": "/tmp/bf.json",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 0)
        self.assertEqual(result["fatal_blockers"][0]["type"], "fatal")
        self.assertEqual(result["fatal_blockers"][0]["message"], "Invalid JSON in module_context.json")
        self.assertEqual(result["fatal_blockers"][0]["source_atom_id"], "struct_01")
        self.assertEqual(result["original_refusal_reason"], "Invalid JSON in module_context.json")
        self.assertEqual(result["report_paths"]["build_fidelity_report_path"], "/tmp/bf.json")

    def test_editorial_boundary_contract_required_location(self):
        """Editorial boundary: source-fidelity mismatch allows reconciliation."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Dark Cave' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_99",
                },
                {
                    "message": "Required NPC 'Wise Hermit' not found in module",
                    "category": "npc",
                    "source_atom_id": "npc_12",
                },
                {
                    "message": "Required puzzle 'Ancient Lock' not found in module",
                    "category": "puzzle",
                    "source_atom_id": "puz_05",
                },
            ],
            "refusal_reason": "Required location 'Dark Cave' not found in module; Required NPC 'Wise Hermit' not found in module; Required puzzle 'Ancient Lock' not found in module",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 0)
        self.assertEqual(result["editorial_count"], 3)
        self.assertEqual(result["fatal_blockers"], [])
        self.assertEqual(len(result["editorial_blockers"]), 3)
        categories = [b["category"] for b in result["editorial_blockers"]]
        self.assertIn("location", categories)
        self.assertIn("npc", categories)
        self.assertIn("puzzle", categories)
        self.assertEqual(result["original_refusal_reason"], report["refusal_reason"])

    def test_mixed_boundary_contract_fatal_plus_editorial(self):
        """Mixed boundary: fatal + editorial prevents reconciliation."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Unrecoverable topology failure",
                    "category": "topology",
                },
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                },
                {
                    "message": "Required NPC 'Hero' not found in module",
                    "category": "npc",
                },
            ],
            "refusal_reason": "Unrecoverable topology; Required location; Required NPC",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "mixed")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 2)
        self.assertEqual(result["fatal_blockers"][0]["category"], "topology")
        editorial_cats = [b["category"] for b in result["editorial_blockers"]]
        self.assertIn("location", editorial_cats)
        self.assertIn("npc", editorial_cats)
        self.assertEqual(result["original_refusal_reason"], "Unrecoverable topology; Required location; Required NPC")

    def test_well_like_bogus_heading_boundary_contract(self):
        """Well boundary: Trigger/Passive Element/Active Element are editorial, not fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger_17",
                },
                {
                    "message": "Required location 'Passive Element' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_passive_22",
                },
                {
                    "message": "Required location 'Active Element' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_active_41",
                },
            ],
            "refusal_reason": "Required location 'Trigger' not found in module; Required location 'Passive Element' not found in module; Required location 'Active Element' not found in module",
            "build_fidelity_report_path": "/wrkspc/build_fidelity.json",
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 0)
        self.assertEqual(result["editorial_count"], 3)
        self.assertEqual(result["original_refusal_reason"], report["refusal_reason"])
        
        messages = [b["message"] for b in result["editorial_blockers"]]
        self.assertTrue(any("Trigger" in m for m in messages))
        self.assertTrue(any("Passive Element" in m for m in messages))
        self.assertTrue(any("Active Element" in m for m in messages))
        
        atom_ids = [b.get("source_atom_id") for b in result["editorial_blockers"]]
        self.assertIn("loc_trigger_17", atom_ids)
        self.assertIn("loc_passive_22", atom_ids)
        self.assertIn("loc_active_41", atom_ids)
        
        self.assertEqual(result["report_paths"]["build_fidelity_report_path"], "/wrkspc/build_fidelity.json")

    def test_source_fidelity_category_not_found_in_module_is_editorial(self):
        """Generic source_fidelity + not found in module stays editorial."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Some source element not found in module",
                    "category": "source_fidelity",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)
        self.assertEqual(result["fatal_count"], 0)

    def test_unknown_category_bare_not_found_in_module_is_unknown(self):
        """Unknown category + bare not found in module stays unknown."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "module_context.json not found in module",
                    "category": "unknown",
                }
            ],
        }
        result = classify_final_build_blockers(report)
        
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 0)
        self.assertEqual(result["fatal_count"], 0)


if __name__ == "__main__":
    unittest.main()
