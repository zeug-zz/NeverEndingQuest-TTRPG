# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Contract tests for utils/toolkit_narrative_enrichment_plan.py.

Verifies:
- Default "none" profile produces skipped plan.
- Blocked source fidelity prevents non-none enrichment.
- Plan is artifact-only (does not mutate modules).
- Profile vocabulary validation.
- Source-lock fields are present and locked when fidelity passes.
"""

import unittest
from typing import Any, Dict

from utils.toolkit_narrative_enrichment_plan import (
    ENRICHMENT_PLAN_VERSION,
    VALID_PROFILES,
    STATUS_SKIPPED,
    STATUS_BLOCKED,
    STATUS_PLANNED,
    build_enrichment_plan,
    can_plan_enrichment,
    _validate_profile,
    _derive_source_fidelity_status,
    _build_default_source_locks,
    _is_non_none_profile,
)


def _passing_build_result(fidelity_status: str = "pass") -> Dict[str, Any]:
    return {
        "status": "success",
        "build_fidelity": {
            "status": fidelity_status,
            "blocker_count": 0,
            "warning_count": 0,
            "can_continue": True,
            "refusal_reason": "",
        },
    }


def _blocked_build_result(refusal: str = "source_fidelity_blocked") -> Dict[str, Any]:
    return {
        "status": "blocked",
        "stage": "build_fidelity",
        "build_fidelity": {
            "status": "blocked",
            "blocker_count": 1,
            "can_continue": False,
            "refusal_reason": refusal,
        },
    }


def _failed_build_result() -> Dict[str, Any]:
    return {"status": "failed", "build_fidelity": {"status": "failed", "can_continue": False}}


class TestBuildEnrichmentPlan(unittest.TestCase):
    """Core plan shape and status derivation."""

    def test_default_none_profile_skipped(self):
        plan = build_enrichment_plan(_passing_build_result(), profile="none")
        self.assertEqual(plan.get("status"), STATUS_SKIPPED)
        self.assertEqual(plan.get("profile"), "none")
        self.assertEqual(plan.get("can_apply"), False)
        self.assertEqual(plan.get("auto_apply"), False)
        self.assertEqual(len(plan.get("blockers") or []), 0)
        self.assertEqual(len(plan.get("warnings") or []), 0)

    def test_default_profile_empty_string_returns_none(self):
        plan = build_enrichment_plan(_passing_build_result(), profile="")
        self.assertEqual(plan.get("profile"), "none")

    def test_version_present(self):
        plan = build_enrichment_plan(_passing_build_result())
        self.assertEqual(plan.get("version"), ENRICHMENT_PLAN_VERSION)

    def test_source_locks_present(self):
        plan = build_enrichment_plan(_passing_build_result())
        locks = plan.get("source_locks") or {}
        self.assertIn("required_npcs_locked", locks)
        self.assertIn("required_locations_locked", locks)
        self.assertIn("plot_topology_locked", locks)
        self.assertIn("puzzle_rules_locked", locks)
        self.assertIn("source_evidence_locked", locks)

    def test_source_locks_true_when_passing(self):
        plan = build_enrichment_plan(_passing_build_result())
        for field, val in (plan.get("source_locks") or {}).items():
            self.assertTrue(val, f"Expected {field}=True when fidelity passes")

    def test_source_locks_false_when_blocked(self):
        plan = build_enrichment_plan(_blocked_build_result())
        for field, val in (plan.get("source_locks") or {}).items():
            self.assertFalse(val, f"Expected {field}=False when fidelity blocked")

    def test_artifact_refs_included(self):
        plan = build_enrichment_plan(_passing_build_result(), report_path="rp.json", rollup_path="sr.json")
        refs = plan.get("artifact_refs") or {}
        self.assertIn("build_fidelity_report", refs)
        self.assertIn("source_fidelity_report", refs)

    def test_eligible_fields_empty_by_default(self):
        plan = build_enrichment_plan(_passing_build_result())
        self.assertEqual(plan.get("eligible_fields"), [])
        self.assertEqual(plan.get("field_budgets"), {})

    def test_profile_notes_empty_by_default(self):
        plan = build_enrichment_plan(_passing_build_result())
        self.assertEqual(plan.get("profile_notes"), [])

    def test_no_module_mutation(self):
        """Plans are artifact-only; this test proves no output is a module path."""
        plan = build_enrichment_plan(_passing_build_result())
        self.assertNotIn("output_directory", plan)
        self.assertNotIn("patches", plan)
        self.assertNotIn("generated_enrichment", plan)


class TestBlockedFidelityPreventsEnrichment(unittest.TestCase):
    """Non-none enrichment profiles are blocked when fidelity is not pass/degraded."""

    def test_blocked_fidelity_blocks_planning(self):
        ok, reason = can_plan_enrichment(_blocked_build_result())
        self.assertFalse(ok)
        self.assertIn("build_fidelity_blocked", reason)

    def test_failed_fidelity_blocks_planning(self):
        ok, reason = can_plan_enrichment(_failed_build_result())
        self.assertFalse(ok)
        self.assertIn("build_fidelity_failed", reason)

    def test_passing_fidelity_allows_planning(self):
        ok, reason = can_plan_enrichment(_passing_build_result())
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_degraded_fidelity_allows_planning(self):
        ok, reason = can_plan_enrichment(_passing_build_result(fidelity_status="degraded"))
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_non_none_profile_blocked_when_fidelity_blocked(self):
        plan = build_enrichment_plan(_blocked_build_result(), profile="three_stance_single_turn")
        self.assertEqual(plan.get("status"), STATUS_BLOCKED)
        self.assertGreater(len(plan.get("blockers") or []), 0)

    def test_non_none_profile_planned_when_fidelity_passes(self):
        plan = build_enrichment_plan(_passing_build_result(), profile="five_playline_stateful")
        self.assertEqual(plan.get("status"), STATUS_PLANNED)

    def test_custom_profile_planned_when_fidelity_passes(self):
        plan = build_enrichment_plan(_passing_build_result(), profile="custom")
        self.assertEqual(plan.get("status"), STATUS_PLANNED)


class TestProfileVocabulary(unittest.TestCase):
    """Profile validation and vocabulary contract."""

    def test_valid_profiles(self):
        expected = {"none", "three_stance_single_turn", "five_playline_stateful", "custom"}
        self.assertEqual(VALID_PROFILES, expected)

    def test_case_insensitive(self):
        self.assertEqual(_validate_profile("NONE"), "none")
        self.assertEqual(_validate_profile("Three_Stance_Single_Turn"), "three_stance_single_turn")
        self.assertEqual(_validate_profile("CUSTOM"), "custom")

    def test_empty_string_defaults_to_none(self):
        self.assertEqual(_validate_profile(""), "none")

    def test_blank_string_defaults_to_none(self):
        self.assertEqual(_validate_profile("  "), "none")

    def test_invalid_profile_preserved_for_blocking(self):
        self.assertEqual(_validate_profile("invalid_profile"), "invalid_profile")

    def test_invalid_profile_blocks_plan(self):
        plan = build_enrichment_plan(_passing_build_result(), profile="invalid_profile")
        self.assertEqual(plan.get("status"), STATUS_BLOCKED)
        self.assertGreater(len(plan.get("blockers") or []), 0)
        blockers = plan.get("blockers") or []
        self.assertTrue(
            any(b.get("category") == "invalid_profile" for b in blockers),
            "Expected at least one blocker with category 'invalid_profile'",
        )

    def test_non_none_detection(self):
        self.assertFalse(_is_non_none_profile("none"))
        self.assertFalse(_is_non_none_profile(""))
        self.assertTrue(_is_non_none_profile("three_stance_single_turn"))
        self.assertTrue(_is_non_none_profile("five_playline_stateful"))
        self.assertTrue(_is_non_none_profile("custom"))


class TestSourceFidelityStatus(unittest.TestCase):
    """Derive fidelity status from build result."""

    def test_pass_from_build_fidelity(self):
        br = _passing_build_result()
        status = _derive_source_fidelity_status(br)
        self.assertEqual(status, "pass")

    def test_degraded_from_build_fidelity(self):
        br = _passing_build_result(fidelity_status="degraded")
        status = _derive_source_fidelity_status(br)
        self.assertEqual(status, "degraded")

    def test_blocked_from_build_fidelity(self):
        br = _blocked_build_result()
        status = _derive_source_fidelity_status(br)
        self.assertEqual(status, "blocked")

    def test_failed_from_build_result(self):
        br = {"status": "failed"}
        status = _derive_source_fidelity_status(br)
        self.assertEqual(status, "failed")

    def test_unknown_when_no_fidelity_data(self):
        br = {"status": "success"}
        status = _derive_source_fidelity_status(br)
        self.assertEqual(status, "pass")


class TestSourceLocks(unittest.TestCase):
    """Source-lock helper behavior."""

    def test_locked_when_not_blocked_or_failed(self):
        locks = _build_default_source_locks("pass")
        for val in locks.values():
            self.assertTrue(val)

    def test_locked_when_degraded(self):
        locks = _build_default_source_locks("degraded")
        for val in locks.values():
            self.assertTrue(val)

    def test_unlocked_when_blocked(self):
        locks = _build_default_source_locks("blocked")
        for val in locks.values():
            self.assertFalse(val)

    def test_unlocked_when_failed(self):
        locks = _build_default_source_locks("failed")
        for val in locks.values():
            self.assertFalse(val)


if __name__ == "__main__":
    unittest.main()
