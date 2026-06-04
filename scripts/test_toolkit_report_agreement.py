# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit Report Agreement
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.toolkit_report_agreement import (
    compose_report_agreement,
    compose_report_agreement_from_module_dir,
    STATUS_PASS,
    STATUS_BLOCKED,
)


class TestComposeReportAgreementAcceptReconciliation(unittest.TestCase):
    """Step 5.1: report agreement consumes source_fidelity_effective_status and accepted reconciliation."""

    def _base_kwargs(self):
        return dict(
            source_fidelity_status="blocked",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def test_no_accepted_reconciliation_preserves_original_status(self):
        """Without accepted reconciliation, effective = normalized original blocked."""
        result = compose_report_agreement(**self._base_kwargs())
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertEqual(result["final_reconciliation_status"], "not_applicable")
        self.assertFalse(result["source_fidelity_reconciled"])

    def test_accepted_reconciled_degraded_exposes_effective_status(self):
        """Accepted reconciliation with reconciled_degraded exposes effective status but preserves original."""
        result = compose_report_agreement(
            **self._base_kwargs(),
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
            final_reconciliation_status="accepted",
        )
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["final_reconciliation_accepted"])
        self.assertEqual(result["final_reconciliation_status"], "accepted")
        self.assertTrue(result["source_fidelity_reconciled"])

    def test_reconciled_does_not_convert_original_to_pass(self):
        """Reconciled degraded must not convert source_fidelity_status to pass."""
        result = compose_report_agreement(
            **self._base_kwargs(),
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
        )
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertNotEqual(result["source_fidelity_status"], STATUS_PASS)

    def test_accepted_without_effective_status_does_not_set_reconciled(self):
        """Accepted but missing effective status must not set source_fidelity_reconciled."""
        result = compose_report_agreement(
            **self._base_kwargs(),
            source_fidelity_effective_status=None,
            final_reconciliation_accepted=True,
        )
        self.assertFalse(result["source_fidelity_reconciled"])

    def test_original_pass_with_reconciliation_not_required(self):
        """Original pass with no reconciliation needed stays pass."""
        result = compose_report_agreement(
            **{**self._base_kwargs(), "source_fidelity_status": "pass"},
            source_fidelity_effective_status="pass",
            final_reconciliation_accepted=False,
        )
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "pass")
        self.assertFalse(result["source_fidelity_reconciled"])

    def test_accepted_with_degraded_effective_is_not_reconciled(self):
        """Accepted with effective='degraded' (not reconciled_degraded) -> not reconciled."""
        result = compose_report_agreement(
            **self._base_kwargs(),
            source_fidelity_effective_status="degraded",
            final_reconciliation_accepted=True,
        )
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertEqual(result["source_fidelity_effective_status"], "degraded")

    def test_accepted_with_blocked_effective_is_not_reconciled(self):
        """Accepted with effective='blocked' -> not reconciled."""
        result = compose_report_agreement(
            **self._base_kwargs(),
            source_fidelity_effective_status="blocked",
            final_reconciliation_accepted=True,
        )
        self.assertFalse(result["source_fidelity_reconciled"])


class TestReportAgreementFromModuleDir(unittest.TestCase):
    """Test compose_report_agreement_from_module_dir reconciliation loading."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = Path(self.tmpdir.name)

    def _write_json(self, filename, data):
        (self.module_dir / filename).write_text(json.dumps(data))

    def _write_accepted_report(self):
        self._write_json("final_reconciliation_report.json", {
            "version": "accurate_ingest_final_reconciliation_report.v1",
            "status": "accepted",
            "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": True,
            "decisions": ["accepted_final_reconciliation"],
        })

    def _write_minimal_reports(self):
        self._write_json("validation_report.json", {"status": "pass", "valid": True})
        self._write_json("source_fidelity_report.json", {"source_fidelity_status": "blocked"})
        self._write_json("toolkit_build_report.json", {
            "status": "pass", "ready_status": "pass", "publishable_status": "pass",
            "effective_publishable_status": "pass",
        })

    def test_missing_recon_report_preserves_behavior(self):
        """Missing final_reconciliation_report -> existing behavior unchanged."""
        self._write_minimal_reports()
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])

    def test_accepted_recon_report_exposes_effective_status(self):
        """Accepted reconciliation in module dir -> effective reconciled_degraded."""
        self._write_minimal_reports()
        self._write_accepted_report()
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertTrue(result["final_reconciliation_accepted"])
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertTrue(result["source_fidelity_reconciled"])

    def test_malformed_recon_report_treated_as_absent(self):
        """Malformed final_reconciliation_report treated as absent."""
        self._write_minimal_reports()
        self._write_json("final_reconciliation_report.json", "not a dict")
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])


class TestBlockedPlayableWithoutAcceptedReconciliation(unittest.TestCase):
    """Step 5.2: blocked source fidelity without accepted reconciliation blocks playable publication."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = Path(self.tmpdir.name)

    def _base_kwargs(self):
        return dict(
            source_fidelity_status="blocked",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def _write_json(self, filename, data):
        (self.module_dir / filename).write_text(json.dumps(data))

    def _write_minimal_reports(self):
        self._write_json("validation_report.json", {"status": "pass", "valid": True})
        self._write_json("source_fidelity_report.json", {"source_fidelity_status": "blocked"})
        self._write_json("toolkit_build_report.json", {
            "status": "pass", "ready_status": "pass", "publishable_status": "pass",
            "effective_publishable_status": "pass",
        })

    def test_direct_blocked_source_no_reconciliation_blocks_playable(self):
        """Blocked source fidelity without accepted reconciliation -> playable blocked."""
        result = compose_report_agreement(**self._base_kwargs())
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_module_dir_blocked_no_recon_report_blocks_playable(self):
        """Module dir with blocked source fidelity and no recon report -> playable blocked."""
        self._write_minimal_reports()
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])

    def test_module_dir_malformed_recon_still_blocks_playable(self):
        """Malformed (non-dict) recon report still blocks playable publication."""
        self._write_minimal_reports()
        self._write_json("final_reconciliation_report.json", "not a dict")
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])

    def test_module_dir_not_accepted_recon_still_blocks_playable(self):
        """Not-accepted recon report still blocks playable publication."""
        self._write_minimal_reports()
        self._write_json("final_reconciliation_report.json", {
            "version": "v1", "status": "required",
            "reconciliation_status": "pending",
            "source_fidelity_effective_status": "blocked",
            "playable_publication_candidate": False,
        })
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])


class TestAcceptedReconciliationAllowsPlayable(unittest.TestCase):
    """Step 5.3: accepted reconciliation allows playable pass when all other gates pass."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = Path(self.tmpdir.name)

    def _passing_kwargs(self):
        return dict(
            source_fidelity_status="blocked",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def _accepted(self):
        return dict(
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
            final_reconciliation_status="accepted",
        )

    def test_accepted_reconciliation_allows_playable_pass(self):
        """Blocked source + accepted reconciliation + all gates pass -> playable pass."""
        result = compose_report_agreement(**self._passing_kwargs(), **self._accepted())
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertTrue(result["source_fidelity_reconciled"])

    def test_no_accepted_reconciliation_blocks_playable(self):
        """Blocked source + no reconciliation -> playable blocked (5.2 regression)."""
        result = compose_report_agreement(**self._passing_kwargs())
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_validation_blocked_overrides_accepted(self):
        """Accepted reconciliation but validation blocked -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "validation_status": "blocked"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_ready_blocked_overrides_accepted(self):
        """Accepted reconciliation but ready blocked -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "ready_status": "blocked"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_publishable_blocked_overrides_accepted(self):
        """Accepted reconciliation but publishable blocked -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "publishable_status": "blocked"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_effective_publishable_blocked_overrides_accepted(self):
        """Accepted reconciliation but effective_publishable blocked -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "effective_publishable_status": "blocked"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_toolkit_top_level_blocked_overrides_accepted(self):
        """Accepted reconciliation but toolkit_top_level_status=blocked -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "toolkit_top_level_status": "blocked"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertTrue(result["source_fidelity_reconciled"])

    def test_toolkit_top_level_failed_overrides_accepted(self):
        """Accepted reconciliation but toolkit_top_level_status=failed -> playable blocked."""
        result = compose_report_agreement(
            **{**self._passing_kwargs(), "toolkit_top_level_status": "failed"},
            **self._accepted(),
        )
        self.assertEqual(result["playable_publication_status"], "blocked")
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertTrue(result["source_fidelity_reconciled"])


class TestOriginalSourceFidelityPreserved(unittest.TestCase):
    """Step 5.4: original source_fidelity_status never converted to clean pass."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = Path(self.tmpdir.name)

    def _write_json(self, filename, data):
        (self.module_dir / filename).write_text(json.dumps(data))

    def _passing_kwargs(self):
        return dict(
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def _accepted_reconciled(self):
        return dict(
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
            final_reconciliation_status="accepted",
        )

    def test_blocked_original_with_accepted_stays_blocked(self):
        """Blocked original + accepted reconciliation -> source_fidelity_status stays blocked, playable pass."""
        result = compose_report_agreement(
            **self._passing_kwargs(),
            source_fidelity_status="blocked",
            **self._accepted_reconciled(),
        )
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["source_fidelity_reconciled"])
        self.assertEqual(result["playable_publication_status"], "pass")

    def test_degraded_original_with_accepted_stays_degraded(self):
        """Degraded original + accepted reconciliation -> source_fidelity_status stays degraded, not pass."""
        result = compose_report_agreement(
            **self._passing_kwargs(),
            source_fidelity_status="degraded",
            **self._accepted_reconciled(),
        )
        self.assertEqual(result["source_fidelity_status"], "degraded")
        self.assertNotEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")

    def test_pass_original_no_reconciliation_stays_pass(self):
        """Pass original + no reconciliation -> source_fidelity_status pass."""
        result = compose_report_agreement(
            **self._passing_kwargs(),
            source_fidelity_status="pass",
        )
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "pass")

    def test_pass_original_with_accepted_preserves_pass(self):
        """Pass original + accepted reconciliation -> still pass, no inventing blocked."""
        result = compose_report_agreement(
            **self._passing_kwargs(),
            source_fidelity_status="pass",
            **self._accepted_reconciled(),
        )
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertNotEqual(result["source_fidelity_status"], "blocked")

    def test_module_dir_blocked_accepted_preserves_blocked_original(self):
        """Module dir: blocked source + accepted recon -> original blocked, effective reconciled, playable pass."""
        self._write_json("validation_report.json", {"status": "pass", "valid": True})
        self._write_json("source_fidelity_report.json", {"source_fidelity_status": "blocked"})
        self._write_json("toolkit_build_report.json", {
            "status": "pass", "ready_status": "pass", "publishable_status": "pass",
            "effective_publishable_status": "pass",
        })
        self._write_json("final_reconciliation_report.json", {
            "version": "v1", "status": "accepted",
            "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": True,
            "decisions": ["accepted_final_reconciliation"],
        })
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["source_fidelity_reconciled"])
        self.assertTrue(result["final_reconciliation_accepted"])
        self.assertEqual(result["playable_publication_status"], "pass")

    def test_module_dir_pass_no_recon_stays_pass(self):
        """Module dir: pass source + no recon -> original pass, effective pass, not reconciled."""
        self._write_json("validation_report.json", {"status": "pass", "valid": True})
        self._write_json("source_fidelity_report.json", {"source_fidelity_status": "pass"})
        self._write_json("toolkit_build_report.json", {
            "status": "pass", "ready_status": "pass", "publishable_status": "pass",
            "effective_publishable_status": "pass",
        })
        result = compose_report_agreement_from_module_dir(self.module_dir)
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "pass")
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertEqual(result["playable_publication_status"], "pass")

    def test_no_source_fidelity_pass_assignment_in_production(self):
        """Production code never assigns source_fidelity_status = pass in reconciliation."""
        import inspect
        import utils.toolkit_report_agreement as tra
        source = inspect.getsource(tra)
        self.assertNotIn('["source_fidelity_status"] = "pass"', source,
                         "Must not hard-assign source_fidelity_status to pass")
        self.assertNotIn("'source_fidelity_status'] = 'pass'", source)


class TestFinalReconciliationReportAgreementEndStates(unittest.TestCase):
    """Step 5.5: end-state regression tests for the three canonical cases."""

    def _all_pass(self):
        return dict(
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )

    def test_blocked_without_reconciliation(self):
        """Blocked source, no reconciliation, all gates pass -> playable blocked."""
        result = compose_report_agreement(
            **self._all_pass(),
            source_fidelity_status="blocked",
        )
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "blocked")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertEqual(result["playable_publication_status"], "blocked")

    def test_pass_with_accepted_reconciliation(self):
        """Blocked source, accepted reconciliation, all gates pass -> playable pass, source stays blocked."""
        result = compose_report_agreement(
            **self._all_pass(),
            source_fidelity_status="blocked",
            source_fidelity_effective_status="reconciled_degraded",
            final_reconciliation_accepted=True,
            final_reconciliation_status="accepted",
        )
        self.assertEqual(result["source_fidelity_status"], "blocked")
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result["final_reconciliation_accepted"])
        self.assertTrue(result["source_fidelity_reconciled"])
        self.assertEqual(result["playable_publication_status"], "pass")
        self.assertNotEqual(result["source_fidelity_status"], "pass")
        self.assertTrue(
            any("reconciled" in d.lower() or "degraded" in d.lower()
                for d in result.get("diagnostics", [])),
            "Diagnostics should mention reconciled/degraded",
        )

    def test_clean_source_fidelity_pass(self):
        """Clean pass, no reconciliation, all gates pass -> playable pass, no reconciled wording."""
        result = compose_report_agreement(
            **self._all_pass(),
            source_fidelity_status="pass",
        )
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(result["source_fidelity_effective_status"], "pass")
        self.assertFalse(result["final_reconciliation_accepted"])
        self.assertFalse(result["source_fidelity_reconciled"])
        self.assertEqual(result["playable_publication_status"], "pass")
        for d in result.get("diagnostics", []):
            self.assertNotIn("reconciled", d.lower())
            self.assertNotIn("degraded", d.lower())


if __name__ == "__main__":
    unittest.main()
