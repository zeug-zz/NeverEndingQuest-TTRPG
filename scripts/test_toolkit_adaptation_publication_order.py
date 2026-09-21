# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free regression tests for adaptation publication ordering.

These tests use only project-local temporary staging targets. Registry calls
are mocked so no real world registry, campaign state, module, or publication
artifact is mutated.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_module_finisher as finisher
from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher
from utils.toolkit_adaptation_staging import create_adaptation_staging_target


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASH = "c" * 64


def _passing_adaptation_gates() -> dict:
    """Return the complete Python-owned pass envelope from task 4.2."""
    domains = (
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
    )
    gates = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in domains
    }
    gates["report_agreement"] = {
        "status": "pass",
        "effective_status": "pass",
        "playable_publication_status": "pass",
        "agreement": {"playable_publication_status": "pass"},
    }
    return {
        "status": "pass",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": gates,
        "publication": {
            "authority": "python",
            "attempted": False,
            "allowed": False,
        },
    }


class AdaptationPublicationFixture(unittest.TestCase):
    """Create an isolated project root and one reserved adaptation target."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_publication_order_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.target = create_adaptation_staging_target(
            SOURCE_HASH,
            job_id="publication-order",
            attempt_number=1,
            revision_number=0,
            module_slug="Adaptation_Publication_Fixture",
            staging_root="tmp/adaptation-staging",
            repo_root=self.root,
        )
        self.module_dir = self.root / self.target["path"]

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _run(self, gates=None, summary=None, registry=None):
        events = []

        def summary_stage(*args, **kwargs):
            events.append("markdown")
            if summary is not None:
                return summary
            return {
                "status": "success",
                "path": str(self.module_dir / "MODULE_SUMMARY.md"),
                "bytes": 256,
                "quality": {"valid": True, "reason": "readable_markdown"},
            }

        def registry_stage(*args, **kwargs):
            events.append("registry")
            return registry or {
                "status": "success",
                "verified": True,
                "integration_attempted": True,
                "campaign_sync": {
                    "status": "success",
                    "campaign_visibility_verified": True,
                },
            }

        with patch.object(finisher, "_run_module_summary_stage", side_effect=summary_stage), patch.object(
            finisher, "_run_registry_stage", side_effect=registry_stage
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                "Adaptation_Publication_Fixture",
                adaptation_mode="llm_adaptation",
                adaptation_gates=gates or _passing_adaptation_gates(),
                adaptation_staging_target=self.target,
                adaptation_module_dir=str(self.module_dir),
            )
        return result, events

    def test_adaptation_orders_markdown_before_registry_and_marks_registry_last(self):
        result, events = self._run()

        self.assertEqual(result["status"], "success")
        self.assertEqual(events, ["markdown", "registry"])
        self.assertEqual(
            result["publication_order"],
            [
                "schema",
                "readiness",
                "mechanical_closure",
                "semantic_authority",
                "semantic_probes",
                "report_agreement",
                "markdown",
                "registry",
            ],
        )
        self.assertTrue(result["registry_is_final_stateful_publication"])
        self.assertEqual(result["stages"]["registry"]["status"], "success")

    def test_semantic_gate_failure_is_fail_closed_before_registry(self):
        gates = _passing_adaptation_gates()
        gates["gates"]["semantic_authority"] = {
            "status": "blocked",
            "effective_status": "blocked",
            "blockers": ["ambiguous destination"],
        }

        result, events = self._run(gates=gates)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(events, [])
        self.assertEqual(result["stages"]["registry"]["status"], "not_attempted")
        self.assertIn(
            "semantic_authority",
            result["stages"]["adaptation_gate_order"]["failed_domains"],
        )

    def test_report_agreement_failure_is_fail_closed_before_registry(self):
        gates = _passing_adaptation_gates()
        gates["gates"]["report_agreement"] = {
            "status": "blocked",
            "effective_status": "blocked",
            "playable_publication_status": "blocked",
            "blockers": ["stale report"],
        }

        result, events = self._run(gates=gates)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(events, [])
        self.assertEqual(result["stages"]["registry"]["status"], "not_attempted")

    def test_markdown_quality_failure_prevents_registry_call(self):
        result, events = self._run(
            summary={
                "status": "failed",
                "reason": "summary_missing_markdown_heading",
                "quality": {"valid": False},
            }
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(events, ["markdown"])
        self.assertEqual(result["stages"]["registry"]["status"], "not_attempted")
        self.assertEqual(
            result["reason"], "adaptation_markdown_quality_failed"
        )

    def test_revision_required_candidate_never_reaches_markdown_or_registry(self):
        gates = _passing_adaptation_gates()
        gates["revision_required"] = True

        result, events = self._run(gates=gates)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(events, [])
        self.assertEqual(
            result["stages"]["registry"]["status"], "not_attempted"
        )
        self.assertEqual(
            result["stages"]["adaptation_hard_safety"]["status"], "failed"
        )

    def test_missing_registry_verification_is_blocked(self):
        result, events = self._run(
            registry={"status": "success", "integration_attempted": True}
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(events, ["markdown", "registry"])
        self.assertEqual(
            result["stages"]["registry"]["reason"],
            "registry_post_write_verification_missing",
        )


class TestAdaptationRoutingAndContracts(unittest.TestCase):
    """Ensure explicit adaptation routing does not change legacy routing."""

    def test_route_forwards_adaptation_transaction_metadata(self):
        target = {
            "path": "tmp/adaptation-staging/attempt/revision_000",
        }
        gates = _passing_adaptation_gates()
        refresh = Mock(return_value={"status": "success"})
        build_result = {
            "build_mode": "llm_adaptation",
            "adaptation_gates": gates,
            "staging_target": target,
            "output_directory": target["path"],
            "adaptation_artifact_workspace": "tmp/adaptation-artifacts",
        }

        with patch(
            "web.extensions.toolkit_module_finisher.refresh_toolkit_build_report",
            refresh,
        ):
            _run_homebrew_finisher(
                "Adaptation_Publication_Fixture", build_result=build_result
            )

        kwargs = refresh.call_args.kwargs
        self.assertEqual(kwargs["adaptation_mode"], "llm_adaptation")
        self.assertEqual(kwargs["adaptation_gates"], gates)
        self.assertEqual(kwargs["adaptation_staging_target"], target)
        self.assertEqual(kwargs["adaptation_module_dir"], target["path"])
        self.assertEqual(
            kwargs["adaptation_artifact_workspace"], "tmp/adaptation-artifacts"
        )

    def test_legacy_build_does_not_enter_adaptation_transaction(self):
        refresh = Mock(return_value={"status": "success"})
        with patch(
            "web.extensions.toolkit_module_finisher.refresh_toolkit_build_report",
            refresh,
        ):
            _run_homebrew_finisher(
                "Legacy_Publication_Fixture",
                build_result={"build_mode": "packet_workspace_v1"},
            )

        kwargs = refresh.call_args.kwargs
        self.assertNotIn("adaptation_mode", kwargs)
        self.assertNotIn("adaptation_gates", kwargs)
        self.assertNotIn("adaptation_staging_target", kwargs)
        self.assertNotIn("adaptation_module_dir", kwargs)

    def test_source_contract_places_registry_after_adaptation_checks(self):
        source = Path("web/extensions/toolkit_module_finisher.py").read_text(
            encoding="utf-8"
        )
        start = source.index("def _run_adaptation_postbuild_finishing")
        end = source.index("def run_toolkit_module_postbuild_finishing", start)
        section = source[start:end]
        self.assertLess(
            section.index("_run_adaptation_gate_order_stage"),
            section.index("_run_module_summary_stage"),
        )
        self.assertLess(
            section.index("_run_module_summary_stage"),
            section.index("_run_registry_stage"),
        )
        self.assertIn("pre_registry_report", section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
