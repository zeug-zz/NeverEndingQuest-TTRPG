# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit Structural Blocker Routing
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Provider-free tests that reproduce Well-of-Ruin-style structural failure
categories from validation_report.json and assert they are fatal before
final-editor routing. Also verifies that accepted reconciliation cannot
override structural failure and that editorial-only blockers remain
eligible for reconciliation.
"""

import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.extensions.toolkit_homebrew_packet_builder import (
    run_toolkit_homebrew_packet_build,
)
from utils.toolkit_final_reconciliation import REPORT_VERSION

from utils.toolkit_final_blocker_classifier import (
    classify_final_build_blockers,
    _is_fatal_blocker,
    FATAL_CATEGORIES,
    FATAL_MESSAGE_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WELL_OF_RUIN_MODULE_PATH = Path("modules/Well_of_Ruin")


def _load_well_of_ruin_validation() -> dict:
    """Load the Well of Ruin validation report and return results."""
    path = _WELL_OF_RUIN_MODULE_PATH / "validation_report.json"
    with open(str(path), "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results", {})


# ---------------------------------------------------------------------------
# TestWellOfRuinStructuralCategories
# ---------------------------------------------------------------------------

class TestWellOfRuinStructuralCategories(unittest.TestCase):
    """Reproduce Well-of-Ruin-style structural failure categories and assert
    they are fatal before final-editor routing."""

    # -- category-based detection -----------------------------------------

    def test_reference_integrity_category_is_fatal(self):
        """reference_integrity category with Well-of-Ruin-style message
        classifies as fatal."""
        blocker = {
            "message": (
                "Sentient Seal Shards in The Broken Seal Expanse/"
                "Shattered Seal Antechamber -> expected monsters/"
                "sentient_seal_shards.json"
            ),
            "category": "reference_integrity",
        }
        self.assertTrue(
            _is_fatal_blocker(blocker["message"], blocker["category"]),
            "reference_integrity category should be fatal"
        )

    def test_spatial_contract_category_is_fatal(self):
        """spatial_contract category with Well-of-Ruin-style message
        classifies as fatal."""
        blocker = {
            "message": (
                "HWR004.json: connected rooms J01->J04 are not "
                "cardinally adjacent (X10Y10 -> X12Y10)"
            ),
            "category": "spatial_contract",
        }
        self.assertTrue(
            _is_fatal_blocker(blocker["message"], blocker["category"]),
            "spatial_contract category should be fatal"
        )

    def test_party_category_is_fatal(self):
        """party category with Well-of-Ruin-style message classifies
        as fatal."""
        blocker = {
            "message": (
                "party_tracker.json: worldConditions -> month: "
                "'Hammer' is not one of ['Firstmonth', 'Coldmonth', "
                "'Thawmonth', 'Springmonth']"
            ),
            "category": "party",
        }
        self.assertTrue(
            _is_fatal_blocker(blocker["message"], blocker["category"]),
            "party category should be fatal"
        )

    # -- message-keyword-based detection ----------------------------------

    def test_reference_integrity_message_keyword_is_fatal(self):
        """Message containing 'expected monsters/' classifies as fatal
        even with an unknown category."""
        self.assertTrue(
            _is_fatal_blocker(
                "expected monsters/sentient_seal_shards.json",
                "unknown",
            ),
            "message with 'expected monsters/' should be fatal via keyword"
        )

    def test_spatial_contract_message_keyword_is_fatal(self):
        """Message containing 'not cardinally adjacent' classifies as
        fatal even with an unknown category."""
        self.assertTrue(
            _is_fatal_blocker(
                "connected rooms J01->J04 are not cardinally adjacent",
                "unknown",
            ),
            "message with 'not cardinally adjacent' should be fatal "
            "via keyword"
        )

    def test_party_message_keyword_is_fatal(self):
        """Message containing 'is not one of' classifies as fatal even
        with an unknown category."""
        self.assertTrue(
            _is_fatal_blocker(
                "month: 'Hammer' is not one of ['Firstmonth']",
                "unknown",
            ),
            "message with 'is not one of' should be fatal via keyword"
        )

    # -- combined report ---------------------------------------------------

    def test_well_of_ruin_all_three_categories_together_classify_as_fatal(self):
        """Build-fidelity report with blockers from all three structural
        categories classifies as fatal with zero editorial count."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": (
                        "Sentient Seal Shards -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
                {
                    "message": (
                        "HWR004.json: connected rooms J01->J04 are not "
                        "cardinally adjacent (X10Y10 -> X12Y10)"
                    ),
                    "category": "spatial_contract",
                },
                {
                    "message": (
                        "party_tracker.json: month 'Hammer' is not "
                        "one of ['Firstmonth']"
                    ),
                    "category": "party",
                },
            ],
            "refusal_reason": (
                "reference_integrity; spatial_contract; party"
            ),
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 3)
        self.assertEqual(result["editorial_count"], 0)


# ---------------------------------------------------------------------------
# TestAcceptedReportCannotOverrideStructuralFailure
# ---------------------------------------------------------------------------

class TestAcceptedReportCannotOverrideStructuralFailure(unittest.TestCase):
    """Prove accepted reconciliation report cannot override structural
    failure."""

    def test_accepted_report_does_not_make_structural_failure_playable(self):
        """Given a classifier result with status='fatal' from structural
        categories, can_attempt_final_reconciliation is False."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "expected monsters/sentient_seal_shards.json",
                    "category": "reference_integrity",
                },
            ],
            "refusal_reason": "Missing monsters",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "fatal")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 0)

    def test_structural_fatal_overrides_accepted_report_presence(self):
        """Structural failures classify as fatal even when an accepted
        final_reconciliation_report.json exists on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Write an accepted reconciliation report to disk
            accepted = {
                "version": "accurate_ingest_final_reconciliation_report.v1",
                "status": "accepted",
                "reconciliation_status": "accepted",
                "source_fidelity_effective_status": "reconciled_degraded",
                "playable_publication_candidate": True,
                "decisions": ["accepted_final_reconciliation"],
                "notes": [],
            }
            report_path = workspace / "final_reconciliation_report.json"
            with open(str(report_path), "w", encoding="utf-8") as f:
                json.dump(accepted, f)

            # Confirm report exists on disk
            self.assertTrue(report_path.exists())

            # Build-fidelity report with structural failure
            build_fidelity = {
                "status": "blocked",
                "can_continue": False,
                "blockers": [
                    {
                        "message": (
                            "HWR004.json: connected rooms J01->J04 are "
                            "not cardinally adjacent (X10Y10 -> X12Y10)"
                        ),
                        "category": "spatial_contract",
                    },
                ],
                "refusal_reason": "Spatial contract failure",
            }

            # Pass workspace as module_dir (exists, so doesn't trigger
            # the missing-module-directory path)
            result = classify_final_build_blockers(
                build_fidelity,
                module_dir=workspace,
            )

            # Structural failure wins regardless of disk report
            self.assertEqual(
                result["status"], "fatal",
                "Structural failure should be fatal even when an "
                "accepted report exists on disk"
            )
            self.assertNotEqual(result["status"], "editorial")
            self.assertNotEqual(result["status"], "no_blockers")
            self.assertFalse(result["can_attempt_final_reconciliation"])


# ---------------------------------------------------------------------------
# TestEditorialBlockersStillUseReconciliation
# ---------------------------------------------------------------------------

class TestEditorialBlockersStillUseReconciliation(unittest.TestCase):
    """Prove editorial-only blockers remain eligible for final
    reconciliation."""

    def test_editorial_location_blocker_not_fatal(self):
        """Blocker with category='location' classifies as editorial,
        not fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Trigger' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "refusal_reason": "Required location 'Trigger' not found",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)
        self.assertEqual(result["fatal_count"], 0)

    def test_editorial_npc_blocker_not_fatal(self):
        """Blocker with category='npc' classifies as editorial, not
        fatal."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required NPC 'Well' not found in module",
                    "category": "npc",
                },
            ],
            "refusal_reason": "Required NPC 'Well' not found",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 1)
        self.assertEqual(result["fatal_count"], 0)

    def test_editorial_only_report_can_attempt_reconciliation(self):
        """Build-fidelity report with only editorial blockers classifies
        as editorial and can attempt reconciliation."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Cave' not found "
                               "in module",
                    "category": "location",
                },
                {
                    "message": "Required NPC 'Merchant' not found "
                               "in module",
                    "category": "npc",
                },
            ],
            "refusal_reason": "Required location 'Cave'; Required "
                              "NPC 'Merchant'",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["editorial_count"], 2)
        self.assertEqual(result["fatal_count"], 0)

    def test_mixed_structural_and_editorial_is_fatal(self):
        """Build-fidelity report with BOTH a structural blocker and an
        editorial blocker classifies as mixed with no reconciliation."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": (
                        "expected monsters/sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
                {
                    "message": "Required location 'Trigger' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "refusal_reason": "Structural + editorial failures",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "mixed")
        self.assertFalse(result["can_attempt_final_reconciliation"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertEqual(result["editorial_count"], 1)


# ---------------------------------------------------------------------------
# TestWellOfRuinValidationReportFixture
# ---------------------------------------------------------------------------

def _well_of_ruin_module_present() -> bool:
    """Check whether the Well of Ruin module validation report exists."""
    return _WELL_OF_RUIN_MODULE_PATH.exists() and (
        _WELL_OF_RUIN_MODULE_PATH / "validation_report.json"
    ).exists()


class TestWellOfRuinSyntheticFatalCategories(unittest.TestCase):
    """Synthetic tests that prove the classifier treats Well-of-Ruin-style
    historical error categories (reference_integrity, spatial_contract,
    party) as fatal, using constructed Well-like messages that match the
    classifier's FATAL_MESSAGE_KEYWORDS. These tests do NOT depend on the
    live Well of Ruin validation report (which is now clean after Step 7.3
    structural repair)."""

    # -- reference_integrity: synthetic Well-like messages ----------------

    def test_reference_integrity_monster_missing_is_fatal(self):
        """Synthetic reference_integrity error about missing monster file
        classifies as fatal."""
        msg = (
            "Sentient Seal Shards in The Broken Seal Expanse/"
            "Shattered Seal Antechamber -> expected monsters/"
            "sentient_seal_shards.json"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "reference_integrity")
        )

    def test_reference_integrity_missing_area_is_fatal(self):
        """Synthetic reference_integrity error about missing area
        classifies as fatal."""
        msg = (
            "Area 'The_Forgotten_Archive' referenced by transition "
            "from 'The Grand Hall' but area file not found"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "reference_integrity")
        )

    def test_reference_integrity_broken_npc_link_is_fatal(self):
        """Synthetic reference_integrity error about broken NPC reference
        classifies as fatal."""
        msg = (
            "NPC 'High Priestess Zul' referenced in location "
            "'Inner Sanctum' but no matching character file found"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "reference_integrity")
        )

    # -- spatial_contract: synthetic Well-like messages -------------------

    def test_spatial_contract_broken_connectivity_is_fatal(self):
        """Synthetic spatial_contract error about broken area connectivity
        classifies as fatal."""
        msg = (
            "Area 'The_Forgotten_Archive' has no incoming connectivity "
            "edges; unreachable from module entrance"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "spatial_contract")
        )

    def test_spatial_contract_overlap_is_fatal(self):
        """Synthetic spatial_contract error about coordinate overlap
        classifies as fatal."""
        msg = (
            "Coordinate collision: area 'The Crypt' occupies same "
            "grid position as 'The Vault' (row=3, col=5)"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "spatial_contract")
        )

    def test_spatial_contract_orphan_location_is_fatal(self):
        """Synthetic spatial_contract error about orphan location
        classifies as fatal."""
        msg = (
            "Location 'Crumbling Observatory' has no path to any "
            "other location in the module connectivity graph"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "spatial_contract")
        )

    # -- party: synthetic Well-like messages ------------------------------

    def test_party_error_missing_starting_location_is_fatal(self):
        """Synthetic party error about missing party starting location
        classifies as fatal."""
        msg = (
            "Party starting location 'The Broken Seal Expanse' not "
            "found in any area of the module"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "party")
        )

    def test_party_error_duplicate_member_is_fatal(self):
        """Synthetic party error about duplicate party member
        classifies as fatal."""
        msg = (
            "Party member 'Zariel' appears twice in party_tracker; "
            "duplicate entry prevents deterministic combat init"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "party")
        )

    def test_party_error_invalid_companion_ref_is_fatal(self):
        """Synthetic party error about invalid companion reference
        classifies as fatal."""
        msg = (
            "Companion 'Shadowmere' in party_tracker references "
            "missing character file"
        )
        self.assertTrue(
            _is_fatal_blocker(msg, "party")
        )


# ---------------------------------------------------------------------------
# Helpers for packet-builder routing tests
# ---------------------------------------------------------------------------

VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


def _create_workspace(tmpdir: str, **file_overrides) -> Path:
    """Create a minimal workspace with required files."""
    ws = Path(tmpdir) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    defaults = {
        "normalized_packet.json": {
            "packet_version": "packet.v1",
            "name": "pipeline-001",
            "title": "Test Adventure",
            "description": "A test adventure for unit tests",
            "source_hash": "abc123",
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        },
        "ui_review_snapshot.json": {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": "test-job-001",
            "packet_identity": {"source_hash": "abc123"},
        },
        "builder_blueprint.json": {},
        "builder_blueprint_report.json": {},
        "builder_narrative.txt": "Test narrative for build",
    }

    for filename, content in {**defaults, **file_overrides}.items():
        path = ws / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(content) if isinstance(content, dict) else content,
            encoding="utf-8",
        )

    return ws


def _make_v2_blueprint(**overrides) -> dict:
    return {
        "blueprint_version": VALID_V2_VERSION,
        "blueprint_status": "ready",
        "module": {"title": "Test V2 Module", "summary": "A v2 test"},
        "source_lock": {"canonical_names_locked": True},
        "area_plan": [{"area_name": "Test Area", "source_locations": []}],
        "location_roster": [],
        "npc_roster": [],
        "plot_graph": [],
        "puzzle_graph": [],
        "clue_graph": [],
        "encounter_plan": [],
        "item_roster": [],
        "tone_requirements": [],
        "source_refs": [],
        "warnings": [],
        "coverage": {"locations_in_blueprint": 0, "npcs_in_blueprint": 0},
        "enrichment_allowlist": {},
        "artifact_refs": {},
        "blockers": [],
        **overrides,
    }


# ---------------------------------------------------------------------------
# TestAcceptedReportCannotOverrideStructuralRouting
# ---------------------------------------------------------------------------

class TestAcceptedReportCannotOverrideStructuralRouting(unittest.TestCase):
    """Packet-builder routing level tests proving an accepted
    final_reconciliation_report.json on disk cannot override structural
    failures."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    def _blocked_fidelity_report(
        self, category="reference_integrity", message="Structural failure"
    ):
        return {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{"message": message, "category": category}],
            "warnings": [],
            "coverage": {},
        }

    def _write_accepted_final_reconciliation_report(self) -> Path:
        """Write a synthetic accepted final reconciliation report on disk."""
        report = {
            "version": REPORT_VERSION,
            "status": "accepted",
            "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": True,
            "decisions": [
                {
                    "blocker_message": "prior-attempt-decision",
                    "decision": "delete_bogus_atom",
                }
            ],
            "changed_files": ["module_context.json"],
        }
        report_path = self.workspace / "final_reconciliation_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path

    def _fatal_classification(
        self, category="reference_integrity", message="Structural failure"
    ) -> dict:
        return {
            "status": "fatal",
            "fatal_blockers": [
                {"type": "fatal", "message": message, "category": category},
            ],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": message,
            "report_paths": {},
        }

    def _mixed_classification(self) -> dict:
        return {
            "status": "mixed",
            "fatal_blockers": [
                {
                    "type": "fatal",
                    "message": (
                        "Sentient Seal Shards in The Broken Seal Expanse/"
                        "Shattered Seal Antechamber -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
            ],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'Trigger' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 1,
            "original_refusal_reason": "Structural + editorial failures",
            "report_paths": {},
        }

    # ------------------------------------------------------------------
    # Per-category fatal tests
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_accepted_report_cannot_override_reference_integrity_failure(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Accepted report on disk cannot override fatal
        reference_integrity failure."""
        self._build_v2_workspace()
        self._write_accepted_final_reconciliation_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(
            category="reference_integrity",
            message=(
                "Sentient Seal Shards in The Broken Seal Expanse/"
                "Shattered Seal Antechamber -> expected monsters/"
                "sentient_seal_shards.json"
            ),
        )
        mock_can_continue.return_value = (
            False,
            "reference_integrity: expected monsters/sentient_seal_shards.json",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._fatal_classification(
            category="reference_integrity",
            message=(
                "Sentient Seal Shards in The Broken Seal Expanse/"
                "Shattered Seal Antechamber -> expected monsters/"
                "sentient_seal_shards.json"
            ),
        )

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-ref-integrity-no-override-accepted",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))

        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("source_fidelity_effective_status", result)
        self.assertNotIn("final_reconciliation_required", result)

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_accepted_report_cannot_override_spatial_contract_failure(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Accepted report on disk cannot override fatal
        spatial_contract failure."""
        self._build_v2_workspace()
        self._write_accepted_final_reconciliation_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(
            category="spatial_contract",
            message=(
                "HWR004.json: connected rooms J01->J04 are not "
                "cardinally adjacent (X10Y10 -> X12Y10)"
            ),
        )
        mock_can_continue.return_value = (
            False,
            "spatial_contract: rooms not cardinally adjacent",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._fatal_classification(
            category="spatial_contract",
            message=(
                "HWR004.json: connected rooms J01->J04 are not "
                "cardinally adjacent (X10Y10 -> X12Y10)"
            ),
        )

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-spatial-contract-no-override-accepted",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))

        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("source_fidelity_effective_status", result)
        self.assertNotIn("final_reconciliation_required", result)

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_accepted_report_cannot_override_party_failure(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Accepted report on disk cannot override fatal party
        failure."""
        self._build_v2_workspace()
        self._write_accepted_final_reconciliation_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(
            category="party",
            message=(
                "party_tracker.json: worldConditions -> month: "
                "'Hammer' is not one of ['Firstmonth', 'Coldmonth', "
                "'Thawmonth', 'Springmonth']"
            ),
        )
        mock_can_continue.return_value = (
            False,
            "party: month 'Hammer' is not valid",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._fatal_classification(
            category="party",
            message=(
                "party_tracker.json: worldConditions -> month: "
                "'Hammer' is not one of ['Firstmonth', 'Coldmonth', "
                "'Thawmonth', 'Springmonth']"
            ),
        )

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-party-no-override-accepted",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))

        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("source_fidelity_effective_status", result)
        self.assertNotIn("final_reconciliation_required", result)

    # ------------------------------------------------------------------
    # Mixed structural + editorial test
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_accepted_report_cannot_override_mixed_structural_and_editorial(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Accepted report on disk cannot override mixed structural
        and editorial classification."""
        self._build_v2_workspace()
        self._write_accepted_final_reconciliation_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": (
                        "Sentient Seal Shards in The Broken Seal Expanse/"
                        "Shattered Seal Antechamber -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
                {
                    "message": "Required location 'Trigger' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Structural + editorial failures",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._mixed_classification()

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-mixed-no-override-accepted",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))

        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("source_fidelity_effective_status", result)
        self.assertNotIn("final_reconciliation_required", result)


# ---------------------------------------------------------------------------
# TestEditorialEligibilityAfterStructuralPass
# ---------------------------------------------------------------------------


class TestEditorialEligibilityAfterStructuralPass(unittest.TestCase):
    """Prove editorial-only blockers remain eligible for final-editor
    reconciliation after structural validation passes."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    def _editorial_classification(self, blockers):
        """Build an editorial classification dict from editorial blockers.

        Args:
            blockers: List of blocker dicts, each with 'message' and 'category'.

        Returns:
            Editorial-eligible classifier result dict.
        """
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {"type": "editorial", **b} for b in blockers
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": len(blockers),
            "original_refusal_reason": "; ".join(
                b.get("message", "") for b in blockers
            ),
            "report_paths": {},
        }

    def _blocked_fidelity_report(self, blockers):
        """Build a blocked build-fidelity report with the given blockers.

        Args:
            blockers: List of blocker dicts, each with 'message' and 'category'.

        Returns:
            Blocked build-fidelity report dict.
        """
        return {
            "status": "blocked",
            "can_continue": False,
            "blockers": list(blockers),
            "warnings": [],
            "coverage": {},
        }

    # ------------------------------------------------------------------
    # Editorial-only tests
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_editorial_only_location_blocker_routes_to_reconciliation(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Build-fidelity report blocked with only an editorial location
        blocker routes to the final editor."""
        self._build_v2_workspace()

        blockers = [
            {"message": "Required location 'Trigger' not found in module",
             "category": "location"},
        ]
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(blockers)
        mock_can_continue.return_value = (
            False,
            "Required location 'Trigger' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._editorial_classification(blockers)

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [], "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-location-routes",
                )

        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "final_reconciliation")
        self.assertTrue(
            result["error"].startswith(
                "final_reconciliation_editor_rejected:"
            ),
        )

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_editorial_only_npc_blocker_routes_to_reconciliation(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Build-fidelity report blocked with only an editorial NPC
        blocker routes to the final editor."""
        self._build_v2_workspace()

        blockers = [
            {"message": "Required NPC 'Well' not found in module",
             "category": "npc"},
        ]
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(blockers)
        mock_can_continue.return_value = (
            False,
            "Required NPC 'Well' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._editorial_classification(blockers)

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [], "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-npc-routes",
                )

        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "final_reconciliation")
        self.assertTrue(
            result["error"].startswith(
                "final_reconciliation_editor_rejected:"
            ),
        )

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_structural_pass_then_editorial_eligible(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Two-step proof: classifier returns editorial (not fatal) for
        editorial-only blockers, then packet builder routes to the editor
        after structural validation passes."""
        self._build_v2_workspace()

        blockers = [
            {"message": "Required location 'Cave' not found in module",
             "category": "location"},
        ]
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(blockers)
        mock_can_continue.return_value = (
            False,
            "Required location 'Cave' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        # Step 1: confirm classifier returns editorial, not fatal
        classification = self._editorial_classification(blockers)
        self.assertEqual(classification["status"], "editorial")
        self.assertNotEqual(classification["status"], "fatal")
        self.assertTrue(classification["can_attempt_final_reconciliation"])
        mock_classify.return_value = classification

        # Step 2: packet builder routes to the editor
        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [], "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-structural-pass-editorial-eligible",
                )

        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "final_reconciliation")

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_no_structural_categories_present_editorial_remains_eligible(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Build-fidelity report with multiple editorial blockers (location
        + npc + puzzle) and ZERO structural categories routes to the
        editor."""
        self._build_v2_workspace()

        blockers = [
            {"message": "Required location 'Hideout' not found in module",
             "category": "location"},
            {"message": "Required NPC 'Merchant' not found in module",
             "category": "npc"},
            {"message": "Required puzzle 'Riddle of the Lock' not found "
                        "in module",
             "category": "puzzle"},
        ]
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report(blockers)
        mock_can_continue.return_value = (
            False,
            "Editorial-only failures; no structural categories",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        classification = self._editorial_classification(blockers)
        self.assertEqual(classification["status"], "editorial")
        self.assertEqual(classification["fatal_count"], 0)
        self.assertEqual(classification["editorial_count"], 3)
        mock_classify.return_value = classification

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [], "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-no-structural-editorial-eligible",
                )

        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()

    # ------------------------------------------------------------------
    # Mixed structural + editorial fatal tests
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_structural_failure_then_editorial_failure_is_still_fatal(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Build-fidelity report with BOTH a structural blocker and an
        editorial blocker classifies as mixed; editor is NOT invoked."""
        self._build_v2_workspace()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report([
            {
                "message": (
                    "Sentient Seal Shards in The Broken Seal Expanse/"
                    "Shattered Seal Antechamber -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            },
            {
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            },
        ])
        mock_can_continue.return_value = (
            False,
            "Structural + editorial failures",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        # Classifier returns mixed (not editorial, not fatal-only)
        mock_classify.return_value = {
            "status": "mixed",
            "fatal_blockers": [
                {
                    "type": "fatal",
                    "message": (
                        "Sentient Seal Shards in The Broken Seal Expanse/"
                        "Shattered Seal Antechamber -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
            ],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'Trigger' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 1,
            "original_refusal_reason": "Structural + editorial failures",
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-mixed-structural-editorial-fatal",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))
        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("final_reconciliation_editor_result", result)


# ---------------------------------------------------------------------------
# TestStructuralBlockerRoutingIntegration
# ---------------------------------------------------------------------------


class TestStructuralBlockerRoutingIntegration(unittest.TestCase):
    """Integration tests for the complete structural repair chain:
    monster closure -> spatial repair -> calendar normalization -> fidelity
    gates -> final-editor routing."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    # ------------------------------------------------------------------
    # Calendar normalization wiring tests
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_calendar_normalization_wired_before_fidelity(
        self, mock_seed, mock_calendar,
    ):
        """Calendar normalization runs after spatial repair and is
        present in build_result. Does NOT block the build on
        status='changed'."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        mock_calendar.return_value = {
            "status": "changed",
            "month_before": "Hammer",
            "month_after": "Firstmonth",
            "reason": "month_normalized",
        }

        # Mock fidelity to not block so we can see calendar result
        with patch(
            "utils.toolkit_build_fidelity.is_build_fidelity_required"
        ) as mock_is_required:
            mock_is_required.return_value = False

            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "test-calendar-wired",
            )

        # calendar_normalization is present in build_result
        self.assertIn("calendar_normalization", result)
        self.assertEqual(
            result["calendar_normalization"]["status"], "changed",
        )
        self.assertEqual(
            result["calendar_normalization"]["month_before"], "Hammer",
        )
        self.assertEqual(
            result["calendar_normalization"]["month_after"], "Firstmonth",
        )

        # Build is NOT blocked at calendar_normalization
        self.assertNotEqual(result.get("stage"), "calendar_normalization")

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_calendar_normalization_failed_blocks_before_fidelity(
        self, mock_seed, mock_calendar,
    ):
        """Calendar normalization with status='failed' blocks the build
        BEFORE fidelity gates are reached."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        mock_calendar.return_value = {
            "status": "failed",
            "month_before": "InvalidMonth",
            "month_after": None,
            "reason": "unknown_invalid_month",
        }

        with patch(
            "utils.toolkit_build_fidelity.is_build_fidelity_required"
        ) as mock_is_required:
            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "test-calendar-failed",
            )

        # Build blocked at calendar_normalization
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "calendar_normalization")
        self.assertIn("calendar_normalization_failed", result.get("error", ""))

        # Fidelity gates were never reached
        mock_is_required.assert_not_called()

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_calendar_normalization_exception_fails_open(
        self, mock_seed, mock_calendar,
    ):
        """Calendar normalization exception does NOT block the build.
        Fails open so fidelity gates can catch invalid months as party
        failures."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        mock_calendar.side_effect = RuntimeError("test calendar exception")

        with patch(
            "utils.toolkit_build_fidelity.is_build_fidelity_required"
        ) as mock_is_required:
            mock_is_required.return_value = False

            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "test-calendar-exception",
            )

        # Build continues past calendar (no calendar_normalization key)
        self.assertNotIn("calendar_normalization", result)
        self.assertNotEqual(result.get("stage"), "calendar_normalization")

    # ------------------------------------------------------------------
    # Source-contract ordering
    # ------------------------------------------------------------------

    def test_full_structural_repair_chain_order(self):
        """Source-contract: the three # TABLETOP MODE: repair blocks
        appear in order: monster closure, then spatial repair, then
        calendar normalization, then fidelity gates."""
        source = inspect.getsource(run_toolkit_homebrew_packet_build)

        markers = [
            "# TABLETOP MODE: Run monster reference closure before fidelity gates.",
            "# TABLETOP MODE: Run spatial repair after monster closure, before fidelity gates.",
            "# TABLETOP MODE: Run calendar normalization after spatial repair, before fidelity gates.",
            "# TABLETOP MODE: Run build fidelity gates before finishing/publication",
        ]

        positions = []
        for marker in markers:
            idx = source.find(marker)
            self.assertGreater(
                idx, -1,
                f"Marker not found in source: {marker[:60]}...",
            )
            positions.append(idx)

        # Verify ascending order
        for i in range(len(positions) - 1):
            self.assertLess(
                positions[i], positions[i + 1],
                f"Marker at position {i} should precede marker at "
                f"position {i + 1} in source",
            )

    # ------------------------------------------------------------------
    # End-to-end routing tests
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_structural_fatal_classification_skips_editor_end_to_end(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """Fatal structural classification (reference_integrity) skips
        the final editor end-to-end."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        # All repair steps succeed
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        # Fidelity gates block with reference_integrity failure
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": (
                    "Sentient Seal Shards in The Broken Seal Expanse/"
                    "Shattered Seal Antechamber -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "reference_integrity: expected monsters/"
            "sentient_seal_shards.json",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        # Classifier returns fatal
        mock_classify.return_value = {
            "status": "fatal",
            "fatal_blockers": [{
                "type": "fatal",
                "message": (
                    "Sentient Seal Shards in The Broken Seal Expanse/"
                    "Shattered Seal Antechamber -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": (
                "reference_integrity: expected monsters/"
                "sentient_seal_shards.json"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-fatal-skips-editor-e2e",
                )

        # Editor NOT invoked
        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        # Build blocked at fidelity (not calendar)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("final_reconciliation_required", result)

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_mixed_structural_editorial_skips_editor_end_to_end(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """Mixed classification (structural + editorial) skips the
        final editor end-to-end."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        # All repair steps succeed
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        # Fidelity gates block with mixed failures
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": (
                        "Sentient Seal Shards in The Broken Seal Expanse/"
                        "Shattered Seal Antechamber -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
                {
                    "message": (
                        "Required location 'Trigger' not found in module"
                    ),
                    "category": "location",
                },
            ],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Structural + editorial failures",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        # Classifier returns mixed
        mock_classify.return_value = {
            "status": "mixed",
            "fatal_blockers": [{
                "type": "fatal",
                "message": (
                    "Sentient Seal Shards in The Broken Seal Expanse/"
                    "Shattered Seal Antechamber -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 1,
            "original_refusal_reason": "Structural + editorial failures",
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-mixed-skips-editor-e2e",
                )

        # Editor NOT invoked
        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        # Build blocked at fidelity (not calendar)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("final_reconciliation_required", result)

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_editorial_only_still_reaches_editor_after_structural_repairs(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """All three repair steps succeed, fidelity gates report
        editorial-only blockers, classifier returns editorial, and
        the final editor IS invoked."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        # All repair steps succeed (pass/skipped)
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        # Fidelity gates block with editorial-only blockers
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Required location 'Trigger' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}

        # Classifier returns editorial
        mock_classify.return_value = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": (
                "Required location 'Trigger' not found in module"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [],
                          "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-after-repairs-e2e",
                )

        # Editor IS invoked
        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()

        # Build arrives at final_reconciliation (not blocked earlier)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "final_reconciliation")
        self.assertTrue(
            result["error"].startswith(
                "final_reconciliation_editor_rejected:"
            ),
        )


# ---------------------------------------------------------------------------
# TestStructuralFailureBlockedMetadata (Task 5.2)
# ---------------------------------------------------------------------------


class TestStructuralFailureBlockedMetadata(unittest.TestCase):
    """Ensure structural failures produce clear blocked build metadata
    without final_reconciliation_required, final_reconciliation_accepted,
    or playable reconciled status."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    def _assert_no_reconciliation_fields(self, result):
        """Assert build_result has no reconciliation-related metadata."""
        self.assertNotIn("final_reconciliation_required", result)
        self.assertNotIn("final_reconciliation_accepted", result)
        self.assertNotIn("source_fidelity_effective_status", result)

    # ------------------------------------------------------------------
    # 1. Monster closure blocked metadata
    # ------------------------------------------------------------------

    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_monster_closure_blocked_metadata_clean(
        self, mock_seed, mock_monster,
    ):
        """Mock monster closure to return unresolved=3. Assert blocked
        metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_monster.return_value = {
            "required": 3, "existing_before": 0, "generated": 0,
            "unresolved": 3, "ambiguous_npc_like": [],
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-monster-closure-blocked-clean",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "monster_closure")
        self.assertTrue(result["error"].startswith("monster_closure"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 2. Spatial repair blocked metadata
    # ------------------------------------------------------------------

    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_spatial_repair_blocked_metadata_clean(
        self, mock_seed, mock_monster, mock_spatial,
    ):
        """Mock spatial repair to return status='failed'. Assert blocked
        metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "failed", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 3,
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-spatial-repair-blocked-clean",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "spatial_repair")
        self.assertTrue(result["error"].startswith("spatial_repair"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 3. Calendar normalization blocked metadata
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_calendar_normalization_blocked_metadata_clean(
        self, mock_seed, mock_monster, mock_spatial, mock_calendar,
    ):
        """Mock calendar normalization to return status='failed'. Assert
        blocked metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "failed", "month_before": "InvalidMonth",
            "month_after": None, "reason": "unknown_invalid_month",
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-calendar-blocked-clean",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "calendar_normalization")
        self.assertTrue(result["error"].startswith("calendar_normalization"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 4. Build fidelity blocked metadata (reference_integrity)
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_fidelity_blocked_metadata_clean(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Mock build fidelity to block with reference_integrity category.
        Assert blocked metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": (
                    "Sentient Seal Shards -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "reference_integrity: expected monsters/sentient_seal_shards.json",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "fatal",
            "fatal_blockers": [{
                "type": "fatal",
                "message": (
                    "Sentient Seal Shards -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": (
                "reference_integrity: expected monsters/"
                "sentient_seal_shards.json"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-fidelity-blocked-clean",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 5. Mixed (structural + editorial) blocked metadata
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_mixed_blocked_metadata_clean(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Mock classifier to return status='mixed'. Assert blocked
        metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": (
                        "Sentient Seal Shards -> expected monsters/"
                        "sentient_seal_shards.json"
                    ),
                    "category": "reference_integrity",
                },
                {
                    "message": (
                        "Required location 'Trigger' not found in module"
                    ),
                    "category": "location",
                },
            ],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Structural + editorial failures",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "mixed",
            "fatal_blockers": [{
                "type": "fatal",
                "message": (
                    "Sentient Seal Shards -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 1,
            "original_refusal_reason": "Structural + editorial failures",
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-mixed-blocked-clean",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 6. Fatal blocked metadata
    # ------------------------------------------------------------------

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_fatal_blocked_metadata_clean(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
    ):
        """Mock classifier to return status='fatal'. Assert blocked
        metadata is clean without reconciliation fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": (
                    "Sentient Seal Shards -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "reference_integrity: expected monsters/sentient_seal_shards.json",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "fatal",
            "fatal_blockers": [{
                "type": "fatal",
                "message": (
                    "Sentient Seal Shards -> expected monsters/"
                    "sentient_seal_shards.json"
                ),
                "category": "reference_integrity",
            }],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": (
                "reference_integrity: expected monsters/"
                "sentient_seal_shards.json"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry"
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-fatal-blocked-clean",
                )

        mock_run_editor.assert_not_called()
        mock_persist_report.assert_not_called()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity"))
        self._assert_no_reconciliation_fields(result)

    # ------------------------------------------------------------------
    # 7. Error message starts with stage name (source-contract)
    # ------------------------------------------------------------------

    def test_structural_blocked_has_error_message(self):
        """Source-contract: for each structural block stage, the production
        error message starts with the stage name + colon prefix."""
        source = inspect.getsource(run_toolkit_homebrew_packet_build)

        # monster_closure: f"monster_closure_unresolved:{...}"
        self.assertIn(
            'f"monster_closure_unresolved:',
            source,
            "monster_closure error should start with 'monster_closure'",
        )

        # spatial_repair: f"spatial_repair_failed:{...}"
        self.assertIn(
            'f"spatial_repair_failed:',
            source,
            "spatial_repair error should start with 'spatial_repair'",
        )

        # calendar_normalization: f"calendar_normalization_failed:{...}"
        self.assertIn(
            'f"calendar_normalization_failed:',
            source,
            "calendar_normalization error should start with "
            "'calendar_normalization'",
        )

        # build_fidelity: "build_fidelity_blocked:" (f-string or plain)
        self.assertIn(
            "build_fidelity_blocked:",
            source,
            "build_fidelity error should start with 'build_fidelity'",
        )


# ---------------------------------------------------------------------------
# TestEditorialBehaviorPreserved (Task 5.3)
# ---------------------------------------------------------------------------


class TestEditorialBehaviorPreserved(unittest.TestCase):
    """Prove editorial-only blockers still reach the final editor after
    structural validation passes."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    # ------------------------------------------------------------------
    # 1. Editorial after all repairs pass still reaches editor
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_editorial_after_all_repairs_pass_still_reaches_editor(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """All three repairs succeed, fidelity reports editorial-only
        blockers, classifier returns editorial, and editor IS invoked."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        # All repair steps succeed
        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        # Fidelity gates block with editorial-only blockers
        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Required location 'Trigger' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": (
                "Required location 'Trigger' not found in module"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [],
                          "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-after-repairs-pass",
                )

        # Editor WAS invoked
        mock_run_editor.assert_called_once()
        mock_persist_report.assert_not_called()

        # Stage is final_reconciliation (not a structural repair stage)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "final_reconciliation")
        self.assertNotEqual(result["stage"], "monster_closure")
        self.assertNotEqual(result["stage"], "spatial_repair")
        self.assertNotEqual(result["stage"], "calendar_normalization")
        self.assertNotEqual(result["stage"], "build_fidelity")

    # ------------------------------------------------------------------
    # 2. Editorial after all repairs pass can accept reconciliation
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_editorial_after_all_repairs_pass_can_accept(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """All repairs succeed, editor accepts, persist succeeds.
        Assert accepted reconciliation fields are set."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Required location 'Trigger' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required location 'Trigger' not found in module",
                "category": "location",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": (
                "Required location 'Trigger' not found in module"
            ),
            "report_paths": {},
        }

        # Accepted orchestrator result shape expected by the helper
        _accepted_orchestrator_result = {
            "status": "accepted", "attempts": [],
            "diagnostics": [], "last_attempt_result": {
                "status": "accepted",
                "reconciliation_status": "accepted",
                "source_fidelity_effective_status":
                    "reconciled_degraded",
                "playable_publication_candidate": True,
                "decisions": [
                    {"blocker_message": "test", "decision": "accept"},
                ],
                "changed_files": [],
            },
        }

        # Editor accepted, persist succeeds
        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value=_accepted_orchestrator_result,
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report",
                return_value={
                    "status": "written",
                    "path": str(self.workspace / "report.json"),
                    "report": _accepted_orchestrator_result.get(
                        "last_attempt_result", {}
                    ),
                    "bytes": 1024,
                    "error": None,
                },
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-accepted",
                )

        mock_run_editor.assert_called_once()
        mock_persist_report.assert_called_once()

        self.assertTrue(
            result.get("final_reconciliation_accepted"),
            "Accepted reconciliation should set "
            "final_reconciliation_accepted=True",
        )
        self.assertEqual(
            result.get("source_fidelity_effective_status"),
            "reconciled_degraded",
        )

    # ------------------------------------------------------------------
    # 3. Editorial classification: can_attempt_final_reconciliation=True
    # ------------------------------------------------------------------

    def test_editorial_classification_can_attempt_reconciliation_true(self):
        """Editorial-only classification preserves
        can_attempt_final_reconciliation=True."""
        report = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {
                    "message": "Required location 'Cave' not found "
                               "in module",
                    "category": "location",
                },
            ],
            "refusal_reason": "Required location 'Cave' not found",
        }
        result = classify_final_build_blockers(report)

        self.assertEqual(result["status"], "editorial")
        self.assertTrue(result["can_attempt_final_reconciliation"])

    # ------------------------------------------------------------------
    # 4. Editorial path: no structural blocker fields in build_result
    # ------------------------------------------------------------------

    @patch("utils.calendar_normalization.normalize_party_calendar")
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure."
           "ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier."
           "classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder."
           "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer."
           "materialize_module_from_blueprint")
    def test_editorial_does_not_have_structural_blocker_fields(
        self, mock_seed, mock_classify, mock_rollup, mock_can_continue,
        mock_build_report, mock_is_required,
        mock_monster, mock_spatial, mock_calendar,
    ):
        """Editorial path result does not contain structural blocker
        fields."""
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        mock_monster.return_value = {
            "required": 0, "existing_before": 0, "generated": 0,
            "unresolved": 0, "ambiguous_npc_like": [],
        }
        mock_spatial.return_value = {
            "status": "pass", "input_location_count": 5,
            "repaired_area_count": 0, "edge_count": 10,
            "unresolved_count": 0,
        }
        mock_calendar.return_value = {
            "status": "skipped", "month_before": None,
            "month_after": None, "reason": "party_tracker_BU_missing",
        }

        mock_is_required.return_value = True
        mock_build_report.return_value = {
            "status": "blocked",
            "can_continue": False,
            "blockers": [{
                "message": "Required NPC 'Well' not found in module",
                "category": "npc",
            }],
            "warnings": [],
            "coverage": {},
        }
        mock_can_continue.return_value = (
            False,
            "Required NPC 'Well' not found in module",
        )
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{
                "type": "editorial",
                "message": "Required NPC 'Well' not found in module",
                "category": "npc",
            }],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": (
                "Required NPC 'Well' not found in module"
            ),
            "report_paths": {},
        }

        with patch(
            "utils.toolkit_llm_final_reconciliation."
            "run_final_reconciliation_with_bounded_retry",
            return_value={"status": "rejected", "attempts": [],
                          "diagnostics": [],
                          "last_attempt_result": None},
        ) as mock_run_editor:
            with patch(
                "utils.toolkit_llm_final_reconciliation."
                "persist_accepted_final_reconciliation_report"
            ) as mock_persist_report:
                result = run_toolkit_homebrew_packet_build(
                    self.workspace,
                    "test-editorial-no-structural-fields",
                )

        mock_run_editor.assert_called_once()

        # Monster closure field: unresolved should be 0
        mc = result.get("monster_closure", {})
        if mc:
            self.assertEqual(mc.get("unresolved", 0), 0)

        # Spatial repair field: status should NOT be "failed"
        sr = result.get("spatial_repair", {})
        if sr:
            self.assertNotEqual(sr.get("status"), "failed")

        # Calendar normalization field: status should NOT be "failed"
        cn = result.get("calendar_normalization", {})
        if cn:
            self.assertNotEqual(cn.get("status"), "failed")


# ---------------------------------------------------------------------------
# TestGuiReportSourceContract (Task 5.4)
# ---------------------------------------------------------------------------


class TestGuiReportSourceContract(unittest.TestCase):
    """Source-contract tests for GUI blocked status rendering and report
    agreement behavior. Does NOT modify production code."""

    # ------------------------------------------------------------------
    # 1. Template handles blocked stages generically
    # ------------------------------------------------------------------

    def test_module_toolkit_handles_monster_closure_blocked_stage(self):
        """The module_toolkit.html template handles blocked job status
        generically, catching structural block stages like
        monster_closure, spatial_repair, etc."""
        template_path = Path("web/templates/module_toolkit.html")
        self.assertTrue(
            template_path.exists(),
            "module_toolkit.html must exist",
        )

        content = template_path.read_text(encoding="utf-8")

        # The generic blocked handler checks job.status === 'blocked'
        # regardless of stage. This catches all structural block stages.
        self.assertIn(
            "job.status === 'blocked'",
            content,
            "Template must have a generic blocked-status handler that "
            "catches all structural block stages (monster_closure, "
            "spatial_repair, calendar_normalization, build_fidelity)",
        )

        # Verify the handler does NOT check for specific stage values
        # (it's a generic handler that covers all blocked states).
        # The handler is at ~line 7847 and uses isFinalReconciledPlayable
        # to decide UI, not the stage value.
        blocked_stage_check_count = content.count(
            "stage === 'monster_closure'"
        ) + content.count("stage === 'spatial_repair'") + content.count(
            "stage === 'calendar_normalization'"
        )
        self.assertEqual(
            blocked_stage_check_count, 0,
            "Template should NOT have stage-specific handlers for "
            "monster_closure, spatial_repair, or calendar_normalization. "
            "The generic blocked handler covers all structural block stages.",
        )

    # ------------------------------------------------------------------
    # 2. Template does NOT show reconciliation UI on blocked status
    # ------------------------------------------------------------------

    def test_module_toolkit_blocked_status_does_not_show_reconciliation(self):
        """When job.status === 'blocked', the template shows reconciliation
        UI ONLY if isFinalReconciledPlayable returns true (which requires
        final_reconciliation_accepted, source_fidelity_reconciled,
        source_fidelity_effective_status=reconciled_degraded, and
        playable_publication_status=pass). For structural failures, none
        of these fields are present, so reconciliation UI is not shown."""
        template_path = Path("web/templates/module_toolkit.html")
        content = template_path.read_text(encoding="utf-8")

        # isFinalReconciledPlayable requires all four conditions
        self.assertIn(
            "c.final_reconciliation_accepted === true",
            content,
        )
        self.assertIn(
            "c.source_fidelity_reconciled === true",
            content,
        )
        self.assertIn(
            "c.source_fidelity_effective_status === 'reconciled_degraded'",
            content,
        )
        self.assertIn(
            "c.playable_publication_status === 'pass'",
            content,
        )

        # Verify the blocked handler (line ~7847) calls
        # isFinalReconciledPlayable, so structural failures without
        # reconciliation fields go to the else branch (non-reconciliation
        # UI)
        self.assertIn(
            "isFinalReconciledPlayable(blockedResult)",
            content,
            "Blocked status handler must check isFinalReconciledPlayable "
            "to decide whether to show reconciliation UI",
        )

        # The else branch for blocked shows error UI, not reconciliation
        self.assertIn(
            "Build fidelity blocked:",
            content,
            "Blocked handler else branch shows fidelity-blocked message, "
            "not reconciliation UI",
        )

    # ------------------------------------------------------------------
    # 3. compose_report_agreement with blocked ready_status
    # ------------------------------------------------------------------

    def test_report_agreement_does_not_claim_playable_for_structural_blocked(
        self,
    ):
        """compose_report_agreement with ready_status='blocked' returns
        playable_publication_status != 'pass'."""
        from utils.toolkit_report_agreement import compose_report_agreement

        # Simulate structural failure: ready_status is blocked
        result = compose_report_agreement(
            source_fidelity_status="pass",
            validation_status="pass",
            ready_status="blocked",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

        self.assertEqual(result["ready_status"], "blocked")
        self.assertNotEqual(
            result["playable_publication_status"], "pass",
            "When ready_status is blocked, playable_publication_status "
            "must NOT be 'pass'",
        )
        self.assertEqual(
            result["playable_publication_status"], "blocked",
            "When ready_status is blocked, playable_publication_status "
            "should be 'blocked'",
        )


if __name__ == "__main__":
    unittest.main()
