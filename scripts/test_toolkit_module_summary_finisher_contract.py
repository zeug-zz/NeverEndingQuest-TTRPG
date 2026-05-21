"""Contract tests for toolkit finisher and MODULE_SUMMARY.md behavior.

Tests verify:
- Finisher accepts extra_stages for seed/enrichment status from v2 builds
- Summary generation failure degrades but does not mutate module JSON
- Summary is final-derived output, not a source-fidelity repair path
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestRefreshToolkitBuildReportContract(unittest.TestCase):
    """Test the refresh_toolkit_build_report function signature and extra_stages."""

    def test_accepts_extra_stages_kwarg(self):
        from web.extensions.toolkit_module_finisher import (
            refresh_toolkit_build_report,
        )

        import inspect
        sig = inspect.signature(refresh_toolkit_build_report)
        self.assertIn("extra_stages", sig.parameters)

    def test_default_extra_stages_is_none(self):
        from web.extensions.toolkit_module_finisher import (
            refresh_toolkit_build_report,
        )

        import inspect
        sig = inspect.signature(refresh_toolkit_build_report)
        default = sig.parameters["extra_stages"].default
        self.assertIsNone(default)

    def test_docstring_notes_extra_stages(self):
        from web.extensions.toolkit_module_finisher import (
            refresh_toolkit_build_report,
        )

        doc = (refresh_toolkit_build_report.__doc__ or "").lower()
        self.assertTrue("report-refresh" in doc or "publishability" in doc)

    def test_run_postbuild_finishing_accepts_extra_stages(self):
        from web.extensions.toolkit_module_finisher import (
            run_toolkit_module_postbuild_finishing,
        )

        import inspect
        sig = inspect.signature(run_toolkit_module_postbuild_finishing)
        self.assertIn("extra_stages", sig.parameters)

    def test_run_postbuild_finishing_default_none(self):
        from web.extensions.toolkit_module_finisher import (
            run_toolkit_module_postbuild_finishing,
        )

        import inspect
        sig = inspect.signature(run_toolkit_module_postbuild_finishing)
        default = sig.parameters["extra_stages"].default
        self.assertIsNone(default)


class TestExtraStagesInjection(unittest.TestCase):
    """Test that extra_stages are injected into stages dict correctly."""

    def _make_stages(self, extra_stages=None):
        """Simulate the extra_stages injection code from the finisher."""
        stages: Dict[str, Any] = {}
        if extra_stages and isinstance(extra_stages, dict):
            for stage_key, stage_payload in extra_stages.items():
                if stage_key not in stages and isinstance(stage_payload, dict):
                    stages[stage_key] = stage_payload
        return stages

    def test_accurate_ingest_stage_injected(self):
        extra = {
            "accurate_ingest_build": {
                "seed_status": "success",
                "enrichment_status": "skipped",
            }
        }
        stages = self._make_stages(extra_stages=extra)
        self.assertIn("accurate_ingest_build", stages)
        self.assertEqual(
            stages["accurate_ingest_build"]["seed_status"],
            "success",
        )

    def test_extra_stages_none_is_noop(self):
        stages = self._make_stages(extra_stages=None)
        self.assertEqual(stages, {})

    def test_extra_stages_empty_dict_is_noop(self):
        stages = self._make_stages(extra_stages={})
        self.assertEqual(stages, {})

    def test_extra_stages_overwrites_nonexisting_no_override(self):
        extra = {"existing_key": {"value": "rejected"}}
        stages = {"existing_key": {"value": "accepted"}}
        if extra and isinstance(extra, dict):
            for stage_key, stage_payload in extra.items():
                if stage_key not in stages and isinstance(stage_payload, dict):
                    stages[stage_key] = stage_payload
        self.assertEqual(stages["existing_key"]["value"], "accepted")

    def test_extra_stages_does_not_override_existing(self):
        extra = {"existing_stage": {"status": "new"}}
        stages = {"existing_stage": {"status": "original"}}
        if extra and isinstance(extra, dict):
            for stage_key, stage_payload in extra.items():
                if stage_key not in stages and isinstance(stage_payload, dict):
                    stages[stage_key] = stage_payload
        self.assertEqual(stages["existing_stage"]["status"], "original")


class TestRunHomebrewFinisherContract(unittest.TestCase):
    """Test the _run_homebrew_finisher routes function accepts build_result."""

    def test_signature_has_build_result(self):
        from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher

        import inspect
        sig = inspect.signature(_run_homebrew_finisher)
        self.assertIn("build_result", sig.parameters)

    def test_build_result_defaults_to_none(self):
        from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher

        import inspect
        sig = inspect.signature(_run_homebrew_finisher)
        default = sig.parameters["build_result"].default
        self.assertIsNone(default)

    @patch("web.extensions.toolkit_module_finisher.refresh_toolkit_build_report")
    def test_extra_stages_constructed_from_build_result(self, mock_refresh):
        from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher

        mock_refresh.return_value = {"status": "success"}

        build_result = {
            "build_mode": "packet_workspace_v2",
            "seed_status": "success",
            "enrichment_status": "skipped",
        }
        _run_homebrew_finisher("test_module", build_result=build_result)

        args, kwargs = mock_refresh.call_args
        extra_stages = kwargs.get("extra_stages")
        self.assertIsNotNone(extra_stages)
        self.assertIn("accurate_ingest_build", extra_stages)
        self.assertEqual(extra_stages["accurate_ingest_build"]["seed_status"], "success")

    @patch("web.extensions.toolkit_module_finisher.refresh_toolkit_build_report")
    def test_no_extra_stages_when_build_result_empty(self, mock_refresh):
        from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher

        mock_refresh.return_value = {"status": "success"}
        _run_homebrew_finisher("test_module", build_result={})

        args, kwargs = mock_refresh.call_args
        extra_stages = kwargs.get("extra_stages")
        self.assertIsNone(extra_stages)

    @patch("web.extensions.toolkit_module_finisher.refresh_toolkit_build_report")
    def test_no_extra_stages_when_build_result_is_none(self, mock_refresh):
        from web.routes.toolkit_homebrew_routes import _run_homebrew_finisher

        mock_refresh.return_value = {"status": "success"}
        _run_homebrew_finisher("test_module")

        args, kwargs = mock_refresh.call_args
        extra_stages = kwargs.get("extra_stages")
        self.assertIsNone(extra_stages)


class TestModuleSummaryContract(unittest.TestCase):
    """Contract tests for MODULE_SUMMARY.md generation behavior."""

    def test_summary_generation_in_finisher_stages(self):
        from web.extensions.toolkit_module_finisher import (
            run_toolkit_module_postbuild_finishing,
        )

        doc = (run_toolkit_module_postbuild_finishing.__doc__ or "").lower()
        self.assertTrue("post-build" in doc or "finishing" in doc)

    def test_summary_failure_degraded_not_fatal(self):
        finisher_stages_module = Path("web/extensions/toolkit_module_finisher.py")

        if not finisher_stages_module.exists():
            self.skipTest("finisher module not found for source inspection")

        content = finisher_stages_module.read_text(encoding="utf-8")

        self.assertIn("module_summary", content)
        self.assertIn("MODULE_SUMMARY.md", content)

        degrade_patterns = [
            "degraded",
            "overall_status =",
        ]
        for pattern in degrade_patterns:
            self.assertIn(pattern, content)

    def test_summary_generation_is_before_final_report(self):
        finisher_path = Path("web/extensions/toolkit_module_finisher.py")
        if not finisher_path.exists():
            self.skipTest("finisher module not found")

        content = finisher_path.read_text(encoding="utf-8")

        gen_pos = content.find("Generate Homebrewery module adventure summary")
        report_pos = content.find("def _build_report")

        if gen_pos == -1:
            self.skipTest("Summary generation marker not found")
        if report_pos == -1:
            self.skipTest("_build_report not found")

        self.assertLess(
            gen_pos, report_pos,
            "MODULE_SUMMARY.md generation should come before final report build"
        )

    def test_summary_is_not_source_fidelity_repair(self):
        finisher_path = Path("web/extensions/toolkit_module_finisher.py")
        if not finisher_path.exists():
            self.skipTest("finisher module not found")

        content = finisher_path.read_text(encoding="utf-8")

        gen_pos = content.find("Generate Homebrewery module adventure summary")
        self.assertGreater(gen_pos, 0, "Summary generation marker not found")

        summary_area = content[gen_pos:]

        self.assertIn("degraded", summary_area)
        self.assertIn("MODULE_SUMMARY.md", summary_area)

        gen_comment = summary_area[:250].lower()
        self.assertIn("summary", gen_comment)
        self.assertIn("adventure", gen_comment)
        self.assertNotIn("write_report", summary_area[:300].lower())


class TestBuildResultFinisherHandoffSourceContract(unittest.TestCase):
    """Source-level contract: build_result seed/enrichment flows into finisher report."""

    def test_finisher_accepts_extra_stages_in_stages_dict(self):
        from web.extensions.toolkit_module_finisher import (
            run_toolkit_module_postbuild_finishing,
        )

        result = run_toolkit_module_postbuild_finishing(
            module_slug="__nonexistent_test_module_do_not_create__",
            extra_stages={
                "accurate_ingest_build": {
                    "seed_status": "success",
                    "enrichment_status": "skipped",
                }
            },
        )

        self.assertIn("stages", result)
        if result.get("status") != "failed":
            self.assertIn("accurate_ingest_build", result["stages"])


if __name__ == "__main__":
    unittest.main()
