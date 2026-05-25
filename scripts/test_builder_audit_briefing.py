#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
"""Tests for builder audit briefing - loader (1.1), missing-artifact (1.2), brief emission (2.1), prompt context (2.2), schema contract (2.3), lane classification (3.1), runtime-only (3.2), no-mutating-workflows (3.3)."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_builder_from_backstage_audit import (
    MissingArtifactError,
    TaskIdentityError,
    _grouped_finding_counts,
    _lane_text,
    build_builder_prompt_context,
    load_audit_run_artifacts,
    write_builder_brief_json,
    write_builder_prompt_context_md,
)


def _make_task_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _build_fixture_run(
    tmpdir: Path,
    task_id: str,
    module_slug: str = "Test_Module",
    extra_run_fields: dict = None,
    extra_evidence_fields: dict = None,
    extra_audit_fields: dict = None,
    extra_rec_fields: dict = None,
) -> Path:
    """Create a complete audit run fixture directory and return its path."""
    run_dir = tmpdir / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_payload = {
        "task_id": task_id,
        "module_slug": module_slug,
        "module_path": str(tmpdir / "modules" / module_slug),
        "output_dir": str(run_dir),
        "created_at": "2026-05-25T00:00:00+00:00",
        "command": "accurate-ingest-audit",
        "status": "completed",
    }
    if extra_run_fields:
        run_payload.update(extra_run_fields)
    (run_dir / "run.json").write_text(json.dumps(run_payload))

    evidence_payload = {
        "status": "completed",
        "module_path": str(tmpdir / "modules" / module_slug),
        "collected_at": "2026-05-25T00:00:00+00:00",
        "artifacts": [
            {
                "artifact_key": "toolkit_build_report",
                "path": str(tmpdir / "modules" / module_slug / "toolkit_build_report.json"),
                "exists": True,
                "parsed": True,
                "status_summary": "failed; publishable_status=fail",
                "sha256": "abc123",
            }
        ],
    }
    if extra_evidence_fields:
        evidence_payload.update(extra_evidence_fields)
    (run_dir / "evidence.json").write_text(json.dumps(evidence_payload))

    audit_payload = {
        "task_id": task_id,
        "module_slug": module_slug,
        "finding_count": 1,
        "counts_by_severity": {"blocker": 1, "warning": 0, "info": 0},
        "findings": [
            {
                "domain": "report_consistency",
                "severity": "blocker",
                "message": "source_fidelity=pass, toolkit_build=fail",
                "evidence_keys": ["toolkit_build_report"],
            }
        ],
        "evidence_refs": ["toolkit_build_report"],
        "grouped_findings": {"report_consistency": []},
        "report_consistency_summary": {"count": 1, "blocker_count": 1, "warning_count": 0, "findings": [], "evidence_refs": ["toolkit_build_report"]},
        "next_step_recommendation": {"recommended_action": "investigate_disagreement", "reason": "1 report-consistency blocker(s) found", "evidence_refs": ["toolkit_build_report"]},
    }
    if extra_audit_fields:
        audit_payload.update(extra_audit_fields)
    (run_dir / "audit_report.json").write_text(json.dumps(audit_payload))

    rec_payload = {
        "task_id": task_id,
        "module_slug": module_slug,
        "recommended_action": "investigate_disagreement",
        "reason": "1 report-consistency blocker(s) found",
        "evidence_refs": ["toolkit_build_report"],
    }
    if extra_rec_fields:
        rec_payload.update(extra_rec_fields)
    (run_dir / "recommendation.json").write_text(json.dumps(rec_payload))

    return run_dir


class TestBuilderAuditBriefingLoader(unittest.TestCase):
    """Step 1.1: Audit-run artifact loader and task identity validator."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_valid_audit_run_loads_all_four_artifacts(self):
        """A complete audit run loads all four required artifacts successfully."""
        task_id = _make_task_id()
        run_dir = _build_fixture_run(self.tmpdir, task_id)
        result = load_audit_run_artifacts(run_dir)
        self.assertEqual(result["task_id"], task_id)
        self.assertEqual(result["module_slug"], "Test_Module")
        self.assertIn("run", result)
        self.assertIn("evidence", result)
        self.assertIn("audit_report", result)
        self.assertIn("recommendation", result)
        self.assertIn("paths", result)

    def test_missing_artifact_raises_error(self):
        """A run directory missing a required artifact raises MissingArtifactError."""
        task_id = _make_task_id()
        run_dir = self.tmpdir / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run_payload = {"task_id": task_id, "module_slug": "Test", "command": "audit", "status": "completed", "output_dir": str(run_dir)}
        (run_dir / "run.json").write_text(json.dumps(run_payload))
        (run_dir / "evidence.json").write_text('{"status": "ok"}')
        (run_dir / "audit_report.json").write_text('{"task_id": "' + task_id + '"}')
        # No recommendation.json
        with self.assertRaises(MissingArtifactError):
            load_audit_run_artifacts(run_dir)

    def test_missing_directory_raises_error(self):
        """A non-existent run directory raises MissingArtifactError."""
        fake_dir = self.tmpdir / "does_not_exist"
        with self.assertRaises(MissingArtifactError):
            load_audit_run_artifacts(fake_dir)

    def test_task_id_mismatch_raises_error(self):
        """Inconsistent task IDs across artifacts raise TaskIdentityError."""
        tid_a = _make_task_id()
        tid_b = _make_task_id()
        run_dir = self.tmpdir / "runs" / tid_a
        run_dir.mkdir(parents=True, exist_ok=True)
        run_payload = {"task_id": tid_a, "module_slug": "Test", "command": "audit", "status": "completed", "output_dir": str(run_dir)}
        (run_dir / "run.json").write_text(json.dumps(run_payload))
        (run_dir / "evidence.json").write_text('{"status": "ok"}')
        audit_payload = {"task_id": tid_b, "module_slug": "Test", "findings": [], "counts_by_severity": {}}
        (run_dir / "audit_report.json").write_text(json.dumps(audit_payload))
        rec_payload = {"task_id": tid_a, "module_slug": "Test", "recommended_action": "no_action", "reason": "test", "evidence_refs": []}
        (run_dir / "recommendation.json").write_text(json.dumps(rec_payload))
        with self.assertRaises(TaskIdentityError):
            load_audit_run_artifacts(run_dir)

    def test_missing_task_id_field_raises_error(self):
        """An artifact without a task_id field raises TaskIdentityError."""
        task_id = _make_task_id()
        run_dir = self.tmpdir / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run_payload = {"module_slug": "Test", "command": "audit", "status": "completed", "output_dir": str(run_dir)}
        (run_dir / "run.json").write_text(json.dumps(run_payload))
        (run_dir / "evidence.json").write_text('{"status": "ok"}')
        (run_dir / "audit_report.json").write_text('{"task_id": "' + task_id + '"}')
        (run_dir / "recommendation.json").write_text('{"task_id": "' + task_id + '"}')
        with self.assertRaises(TaskIdentityError):
            load_audit_run_artifacts(run_dir)

    def test_returned_metadata_includes_artifact_paths(self):
        """The returned dict includes source paths for all four artifacts."""
        task_id = _make_task_id()
        run_dir = _build_fixture_run(self.tmpdir, task_id)
        result = load_audit_run_artifacts(run_dir)
        self.assertIn("paths", result)
        paths = result["paths"]
        self.assertEqual(len(paths), 4)
        self.assertIn("run", paths)
        self.assertIn("evidence", paths)
        self.assertIn("audit_report", paths)
        self.assertIn("recommendation", paths)
        for key, path_str in paths.items():
            self.assertTrue(Path(path_str).is_file(), f"Path for {key} is not a file: {path_str}")

    def test_malformed_json_raises_error(self):
        """A required artifact with malformed JSON raises MissingArtifactError."""
        task_id = _make_task_id()
        run_dir = self.tmpdir / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text('{"task_id": "' + task_id + '"}')
        (run_dir / "evidence.json").write_text('not valid json')
        (run_dir / "audit_report.json").write_text('{"task_id": "' + task_id + '"}')
        (run_dir / "recommendation.json").write_text('{"task_id": "' + task_id + '"}')
        with self.assertRaises(MissingArtifactError):
            load_audit_run_artifacts(run_dir)

    def test_loader_does_not_write_files(self):
        """load_audit_run_artifacts does not create or modify files."""
        task_id = _make_task_id()
        run_dir = _build_fixture_run(self.tmpdir, task_id)
        before = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
        load_audit_run_artifacts(run_dir)
        after = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class TestBuilderAuditBriefingOutput(unittest.TestCase):
    """Step 2.1: builder_brief.json emission from a valid audit run."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.task_id = _make_task_id()
        self.run_dir = _build_fixture_run(self.tmpdir, self.task_id)
        self.module_dir = self.tmpdir / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_write_builder_brief_creates_file(self):
        """write_builder_brief_json writes builder_brief.json into the run directory."""
        brief = write_builder_brief_json(self.run_dir)
        brief_path = self.run_dir / "builder_brief.json"
        self.assertTrue(brief_path.is_file(), "builder_brief.json was not created")
        self.assertEqual(brief["task_id"], self.task_id)

    def test_brief_contains_required_fields(self):
        """builder_brief.json contains all required compact fields."""
        brief = write_builder_brief_json(self.run_dir)
        self.assertEqual(brief["task_id"], self.task_id)
        self.assertEqual(brief["module_slug"], "Test_Module")
        self.assertIn("audit_output_dir", brief)
        self.assertIn("generated_at", brief)
        self.assertIn("recommended_action", brief)
        self.assertIn("reason", brief)
        self.assertIn("evidence_refs", brief)
        self.assertIn("finding_count", brief)
        self.assertIn("counts_by_severity", brief)
        self.assertIn("grouped_finding_counts", brief)
        self.assertIn("top_findings", brief)
        self.assertIn("report_consistency_summary", brief)
        self.assertIn("source_artifact_paths", brief)
        self.assertIn("builder_lane", brief)

    def test_recommendation_fields_match_source(self):
        """recommended_action and reason match recommendation.json."""
        with open(self.run_dir / "recommendation.json") as f:
            rec = json.load(f)
        brief = write_builder_brief_json(self.run_dir)
        self.assertEqual(brief["recommended_action"], rec["recommended_action"])
        self.assertEqual(brief["reason"], rec["reason"])

    def test_evidence_refs_include_audit_and_recommendation_refs(self):
        """evidence_refs preserve ordered unique refs from audit and recommendation."""
        task_id = _make_task_id()
        run_dir = _build_fixture_run(
            self.tmpdir,
            task_id,
            extra_audit_fields={"evidence_refs": ["audit_only", "shared"]},
            extra_rec_fields={"evidence_refs": ["shared", "recommendation_only"]},
        )
        brief = write_builder_brief_json(run_dir)
        self.assertEqual(
            brief["evidence_refs"],
            ["audit_only", "shared", "recommendation_only"],
        )

    def test_report_consistency_summary_preserved(self):
        """report_consistency_summary is propagated from audit_report.json."""
        with open(self.run_dir / "audit_report.json") as f:
            audit = json.load(f)
        brief = write_builder_brief_json(self.run_dir)
        self.assertEqual(brief["report_consistency_summary"], audit["report_consistency_summary"])

    def test_grouped_finding_counts_counts_by_domain(self):
        """grouped_finding_counts counts findings per domain without copying full lists."""
        brief = write_builder_brief_json(self.run_dir)
        counts = brief["grouped_finding_counts"]
        self.assertIsInstance(counts, dict)
        self.assertIn("report_consistency", counts)
        self.assertGreaterEqual(counts["report_consistency"], 0)
        for domain, count in counts.items():
            self.assertIsInstance(domain, str)
            self.assertIsInstance(count, int)

    def test_source_artifact_paths_point_to_input_files(self):
        """source_artifact_paths reference all four input artifact files."""
        brief = write_builder_brief_json(self.run_dir)
        paths = brief["source_artifact_paths"]
        self.assertEqual(len(paths), 4)
        self.assertIn("run", paths)
        self.assertIn("evidence", paths)
        self.assertIn("audit_report", paths)
        self.assertIn("recommendation", paths)
        for key, path_str in paths.items():
            self.assertTrue(Path(path_str).is_file(), f"Source path for {key} does not exist: {path_str}")

    def test_no_markdown_context_written(self):
        """Step 2.1 does not create builder_prompt_context.md."""
        write_builder_brief_json(self.run_dir)
        md_path = self.run_dir / "builder_prompt_context.md"
        self.assertFalse(md_path.exists(), "builder_prompt_context.md should not exist yet")

    def test_no_files_outside_run_directory(self):
        """Builder brief writes only inside the audit run directory."""
        before = {str(p.relative_to(self.tmpdir)) for p in self.tmpdir.rglob("*") if p.is_file()}
        write_builder_brief_json(self.run_dir)
        after = {str(p.relative_to(self.tmpdir)) for p in self.tmpdir.rglob("*") if p.is_file()}
        added = after - before
        for path_str in added:
            self.assertTrue(
                path_str.startswith(f"runs/{self.task_id}/"),
                f"New file {path_str} is outside the run directory",
            )

    def test_module_files_not_mutated(self):
        """Writer does not create or modify files under the module directory."""
        before = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        write_builder_brief_json(self.run_dir)
        after = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_builder_lane_is_classified(self):
        """builder_lane is classified from the recommended action."""
        brief = write_builder_brief_json(self.run_dir)
        self.assertEqual(brief["builder_lane"], "diagnose_reports")
        self.assertIn("builder_lane_rationale", brief)
        self.assertIn("builder_lane_evidence_refs", brief)

    def test_top_findings_messages_are_bounded(self):
        """Top finding messages are bounded to avoid copying full raw report bodies."""
        task_id = _make_task_id()
        run_dir = _build_fixture_run(
            self.tmpdir,
            task_id,
            extra_audit_fields={
                "findings": [{
                    "domain": "source_fidelity",
                    "severity": "blocker",
                    "message": "x" * 400,
                    "evidence_keys": ["source_fidelity_report"],
                }]
            },
        )
        brief = write_builder_brief_json(run_dir)
        message = brief["top_findings"][0]["message"]
        self.assertLessEqual(len(message), 240)
        self.assertTrue(message.endswith("..."))

    def test_loaded_brief_reads_back_correctly(self):
        """Written builder_brief.json can be read back with correct content."""
        brief = write_builder_brief_json(self.run_dir)
        with open(self.run_dir / "builder_brief.json") as f:
            read_back = json.load(f)
        self.assertEqual(read_back, brief)


class TestBuilderAuditBriefingGroupedFindingCounts(unittest.TestCase):
    """Unit tests for _grouped_finding_counts helper."""

    def test_empty_grouped(self):
        self.assertEqual(_grouped_finding_counts({}), {})

    def test_single_domain(self):
        data = {"source_fidelity": [{"domain": "source_fidelity", "severity": "pass"}]}
        self.assertEqual(_grouped_finding_counts(data), {"source_fidelity": 1})

    def test_multiple_domains(self):
        data = {
            "source_fidelity": [{"domain": "source_fidelity"}] * 2,
            "build_fidelity": [{"domain": "build_fidelity"}] * 3,
        }
        self.assertEqual(_grouped_finding_counts(data), {"source_fidelity": 2, "build_fidelity": 3})

    def test_empty_list_per_domain(self):
        data = {"report_consistency": []}
        self.assertEqual(_grouped_finding_counts(data), {"report_consistency": 0})


class TestBuilderAuditBriefingPromptContext(unittest.TestCase):
    """Step 2.2: builder_prompt_context.md emission."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.task_id = _make_task_id()
        self.run_dir = _build_fixture_run(self.tmpdir, self.task_id)
        self.module_dir = self.tmpdir / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _write_brief_and_get_context(self):
        write_builder_brief_json(self.run_dir)
        return write_builder_prompt_context_md(self.run_dir)

    def test_writes_markdown_file(self):
        """write_builder_prompt_context_md creates builder_prompt_context.md."""
        md = self._write_brief_and_get_context()
        md_path = self.run_dir / "builder_prompt_context.md"
        self.assertTrue(md_path.is_file(), "builder_prompt_context.md was not created")
        self.assertGreater(len(md), 50)

    def test_contains_module_slug(self):
        """Markdown includes the module slug."""
        md = self._write_brief_and_get_context()
        self.assertIn("Test_Module", md)

    def test_contains_module_summary_section(self):
        """Markdown includes an explicit compact module summary section."""
        brief = write_builder_brief_json(self.run_dir)
        md = build_builder_prompt_context(brief)
        self.assertIn("## Module Summary", md)
        self.assertIn("Audit Output Dir", md)

    def test_contains_task_id(self):
        """Markdown includes the task ID."""
        md = self._write_brief_and_get_context()
        self.assertIn(self.task_id, md)

    def test_contains_recommendation_action(self):
        """Markdown includes the recommended action."""
        md = self._write_brief_and_get_context()
        self.assertIn("investigate_disagreement", md)

    def test_contains_recommendation_reason(self):
        """Markdown includes the reason."""
        md = self._write_brief_and_get_context()
        self.assertIn("found", md)

    def test_contains_classified_lane(self):
        """Markdown includes the classified builder lane and rationale."""
        md = self._write_brief_and_get_context()
        self.assertIn("diagnose_reports", md)
        self.assertIn("Rationale:", md)

    def test_contains_evidence_refs(self):
        """Markdown lists evidence refs from the brief."""
        md = self._write_brief_and_get_context()
        self.assertIn("toolkit_build_report", md)

    def test_contains_finding_count(self):
        """Markdown includes the total finding count."""
        md = self._write_brief_and_get_context()
        self.assertIn("Total Findings", md)
        self.assertIn("1", md)

    def test_contains_severity_breakdown(self):
        """Markdown includes counts by severity."""
        md = self._write_brief_and_get_context()
        self.assertIn("blocker:", md)

    def test_contains_domain_breakdown(self):
        """Markdown includes grouped finding counts by domain."""
        md = self._write_brief_and_get_context()
        self.assertIn("report_consistency:", md)

    def test_contains_top_findings(self):
        """Markdown includes compact top findings from the brief."""
        md = self._write_brief_and_get_context()
        self.assertIn("## Top Findings", md)
        self.assertIn("source_fidelity=pass, toolkit_build=fail", md)
        self.assertIn("toolkit_build_report", md)

    def test_contains_advisory_warning(self):
        """Markdown includes the advisory warning."""
        md = self._write_brief_and_get_context()
        self.assertIn("advisory and cannot override", md)

    def test_no_files_outside_run_directory(self):
        """Writer writes only inside the audit run directory."""
        write_builder_brief_json(self.run_dir)
        before = {str(p.relative_to(self.tmpdir)) for p in self.tmpdir.rglob("*") if p.is_file()}
        write_builder_prompt_context_md(self.run_dir)
        after = {str(p.relative_to(self.tmpdir)) for p in self.tmpdir.rglob("*") if p.is_file()}
        added = after - before
        for path_str in added:
            self.assertTrue(
                path_str.startswith(f"runs/{self.task_id}/"),
                f"New file {path_str} is outside the run directory",
            )

    def test_module_files_not_mutated(self):
        """Writer does not create or modify files under the module directory."""
        write_builder_brief_json(self.run_dir)
        before = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        write_builder_prompt_context_md(self.run_dir)
        after = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_reuses_existing_brief_when_present(self):
        """If builder_brief.json already exists, it is reused (no error from absent artifacts)."""
        brief = write_builder_brief_json(self.run_dir)
        # Remove audit artifacts to prove reuse
        for artifact in ["run.json", "evidence.json", "audit_report.json", "recommendation.json"]:
            (self.run_dir / artifact).unlink()
        md = write_builder_prompt_context_md(self.run_dir)
        self.assertIn(brief["module_slug"], md)

    def test_generates_brief_when_absent(self):
        """If builder_brief.json does not exist, fresh brief is generated from audit artifacts."""
        md = write_builder_prompt_context_md(self.run_dir)
        self.assertIn("Test_Module", md)


class TestBuilderAuditBriefingLaneText(unittest.TestCase):
    """Unit tests for _lane_text helper."""

    def test_none_returns_pending(self):
        self.assertEqual(_lane_text(None), "pending")

    def test_string_passthrough(self):
        self.assertEqual(_lane_text("fast_path"), "fast_path")

    def test_empty_string(self):
        self.assertEqual(_lane_text(""), "")

    def test_falsey_non_none(self):
        self.assertEqual(_lane_text(False), "False")


class TestBuilderAuditBriefingLaneClassification(unittest.TestCase):
    """Step 3.1: Deterministic builder-lane classification from recommended action."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.task_id = _make_task_id()

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _classify(self, action: str, refs: list = None) -> dict:
        from scripts.prepare_builder_from_backstage_audit import classify_builder_lane
        return classify_builder_lane(action, refs or [])

    def test_investigate_disagreement_maps_to_diagnose_reports(self):
        result = self._classify("investigate_disagreement")
        self.assertEqual(result["builder_lane"], "diagnose_reports")

    def test_repair_artifacts_maps_to_repair_artifacts(self):
        result = self._classify("repair_artifacts")
        self.assertEqual(result["builder_lane"], "repair_artifacts")

    def test_openspec_work_maps_to_openspec_work(self):
        result = self._classify("openspec_work")
        self.assertEqual(result["builder_lane"], "openspec_work")

    def test_review_warnings_maps_to_review_warnings(self):
        result = self._classify("review_warnings")
        self.assertEqual(result["builder_lane"], "review_warnings")

    def test_no_action_maps_to_no_action(self):
        result = self._classify("no_action")
        self.assertEqual(result["builder_lane"], "no_action")

    def test_unknown_action_maps_to_diagnose_reports(self):
        result = self._classify("nonexistent_action")
        self.assertEqual(result["builder_lane"], "diagnose_reports")

    def test_empty_action_maps_to_diagnose_reports(self):
        result = self._classify("")
        self.assertEqual(result["builder_lane"], "diagnose_reports")

    def test_classified_lane_includes_rationale(self):
        result = self._classify("investigate_disagreement")
        self.assertIn("builder_lane_rationale", result)
        self.assertIsInstance(result["builder_lane_rationale"], str)
        self.assertGreater(len(result["builder_lane_rationale"]), 0)

    def test_classified_lane_includes_evidence_refs(self):
        refs = ["audit_report", "toolkit_build"]
        result = self._classify("investigate_disagreement", refs)
        self.assertEqual(result["builder_lane_evidence_refs"], refs)

    def test_classified_lane_evidence_refs_default_to_empty(self):
        result = self._classify("no_action")
        self.assertEqual(result["builder_lane_evidence_refs"], [])

    def test_brief_includes_builder_lane_fields(self):
        """builder_brief.json includes builder_lane, rationale, and evidence refs after classification."""
        run_dir = _build_fixture_run(self.tmpdir, _make_task_id())
        brief = write_builder_brief_json(run_dir)
        self.assertIn("builder_lane", brief)
        self.assertIn("builder_lane_rationale", brief)
        self.assertIn("builder_lane_evidence_refs", brief)

    def test_markdown_includes_classified_lane_and_rationale(self):
        """builder_prompt_context.md includes the classified lane and rationale text."""
        run_dir = _build_fixture_run(self.tmpdir, _make_task_id())
        write_builder_brief_json(run_dir)
        md = write_builder_prompt_context_md(run_dir)
        self.assertIn("## Module Summary", md)
        self.assertIn("Builder Lane:", md)
        self.assertIn("Rationale:", md)

    def test_classification_does_not_create_extra_files(self):
        """Classification writes only builder_brief.json and builder_prompt_context.md."""
        run_dir = _build_fixture_run(self.tmpdir, _make_task_id())
        before = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
        write_builder_brief_json(run_dir)
        write_builder_prompt_context_md(run_dir)
        after = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
        added = after - before
        for path_str in added:
            self.assertIn(path_str, {"builder_brief.json", "builder_prompt_context.md"})

    def test_classification_does_not_mutate_module(self):
        """Classification does not create or modify files under the module directory."""
        run_dir = _build_fixture_run(self.tmpdir, _make_task_id())
        module_dir = self.tmpdir / "modules" / "Test_Module"
        module_dir.mkdir(parents=True, exist_ok=True)
        before = {str(p.relative_to(module_dir)) for p in module_dir.rglob("*") if p.is_file()}
        write_builder_brief_json(run_dir)
        write_builder_prompt_context_md(run_dir)
        after = {str(p.relative_to(module_dir)) for p in module_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class TestBuilderAuditBriefingContractSchema(unittest.TestCase):
    """Step 2.3: Schema/contract tests proving compact fields, evidence refs, grouped counts, and report-consistency summary are preserved without full raw bodies."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.task_id = _make_task_id()
        self.run_dir = _build_fixture_run(self.tmpdir, self.task_id)
        self.brief = write_builder_brief_json(self.run_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_brief_task_id_is_string(self):
        """task_id is a non-empty string."""
        self.assertIsInstance(self.brief["task_id"], str)
        self.assertGreater(len(self.brief["task_id"]), 0)

    def test_brief_module_slug_is_string(self):
        """module_slug is a non-empty string."""
        self.assertIsInstance(self.brief["module_slug"], str)
        self.assertGreater(len(self.brief["module_slug"]), 0)

    def test_brief_audit_output_dir_is_string(self):
        """audit_output_dir is a non-empty string."""
        self.assertIsInstance(self.brief["audit_output_dir"], str)
        self.assertGreater(len(self.brief["audit_output_dir"]), 0)

    def test_brief_recommended_action_is_string(self):
        """recommended_action is a non-empty string."""
        self.assertIsInstance(self.brief["recommended_action"], str)
        self.assertGreater(len(self.brief["recommended_action"]), 0)

    def test_brief_reason_is_string(self):
        """reason is a non-empty string."""
        self.assertIsInstance(self.brief["reason"], str)
        self.assertGreater(len(self.brief["reason"]), 0)

    def test_brief_builder_lane_is_known_lane(self):
        """builder_lane is a known classified lane string."""
        self.assertIsInstance(self.brief["builder_lane"], str)
        self.assertIn(self.brief["builder_lane"], {"diagnose_reports", "repair_artifacts", "openspec_work", "review_warnings", "no_action"})
        self.assertIsInstance(self.brief.get("builder_lane_rationale"), str)
        self.assertIsInstance(self.brief.get("builder_lane_evidence_refs"), list)

    def test_brief_evidence_refs_is_list_of_strings(self):
        """evidence_refs is a list of non-empty strings."""
        refs = self.brief["evidence_refs"]
        self.assertIsInstance(refs, list)
        for ref in refs:
            self.assertIsInstance(ref, str)
            self.assertGreater(len(ref), 0)

    def test_brief_grouped_finding_counts_are_integers(self):
        """grouped_finding_counts values are integers, not lists."""
        counts = self.brief["grouped_finding_counts"]
        self.assertIsInstance(counts, dict)
        for domain, count in counts.items():
            self.assertIsInstance(domain, str)
            self.assertIsInstance(count, int)
        self.assertEqual(counts.get("report_consistency"), 0)

    def test_brief_no_raw_findings_list(self):
        """builder_brief.json does not contain a full raw findings list."""
        self.assertNotIn("findings", self.brief)

    def test_brief_no_raw_evidence_list(self):
        """builder_brief.json does not contain a full raw evidence list."""
        self.assertNotIn("artifacts", self.brief)

    def test_brief_report_consistency_summary_is_dict(self):
        """report_consistency_summary is a dict with expected keys."""
        summary = self.brief["report_consistency_summary"]
        self.assertIsInstance(summary, dict)
        self.assertIn("count", summary)
        self.assertIn("blocker_count", summary)
        self.assertIn("findings", summary)

    def test_markdown_no_raw_json_report_body(self):
        """builder_prompt_context.md does not contain raw JSON report body blocks."""
        md = write_builder_prompt_context_md(self.run_dir)
        self.assertNotIn('{"', md)
        self.assertNotIn('"findings":', md)

    def test_markdown_no_full_findings_array(self):
        """Markdown does not contain a full raw findings array."""
        md = write_builder_prompt_context_md(self.run_dir)
        self.assertNotIn('"domain"', md)
        self.assertNotIn('"evidence_keys"', md)
        self.assertNotIn('"severity"', md)

    def test_markdown_evidence_refs_match_brief(self):
        """Evidence refs in markdown match the brief's evidence_refs field."""
        md = write_builder_prompt_context_md(self.run_dir)
        for ref in self.brief["evidence_refs"]:
            self.assertIn(ref, md)

    def test_markdown_report_consistency_blocker_count_matches_brief(self):
        """The report-consistency blocker_count in markdown matches the brief."""
        md = write_builder_prompt_context_md(self.run_dir)
        expected = str(self.brief["report_consistency_summary"]["blocker_count"])
        self.assertIn(expected, md)

    def test_markdown_grouped_finding_domain_in_markdown(self):
        """Grouped finding domain names appear in the markdown finding summary."""
        md = write_builder_prompt_context_md(self.run_dir)
        for domain in self.brief["grouped_finding_counts"]:
            self.assertIn(domain, md)

    def test_markdown_no_evidence_artifacts_raw_list(self):
        """Markdown does not contain raw evidence artifact blocks."""
        md = write_builder_prompt_context_md(self.run_dir)
        self.assertNotIn("artifact_key", md)
        self.assertNotIn("status_summary", md)

    def test_brief_source_artifact_paths_are_files(self):
        """source_artifact_paths point to real files in the run directory."""
        paths = self.brief["source_artifact_paths"]
        self.assertEqual(len(paths), 4)
        self.assertIn("run", paths)
        self.assertIn("evidence", paths)
        self.assertIn("audit_report", paths)
        self.assertIn("recommendation", paths)
        for key, path_str in paths.items():
            self.assertTrue(
                Path(path_str).is_file(),
                f"Path for {key} is not a file: {path_str}",
            )


class TestBuilderAuditBriefingRuntimeOnly(unittest.TestCase):
    """Step 3.2: Runtime-only output and module non-mutation tests."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.task_id = _make_task_id()
        self.run_dir = _build_fixture_run(self.tmpdir, self.task_id)
        self.module_dir = self.tmpdir / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        self.fake_module_file = self.module_dir / "module_context.json"
        self.fake_module_file.write_text(json.dumps({"name": "Test", "version": "1.0"}))

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    @staticmethod
    def _file_hashes(directory: Path):
        import hashlib
        hashes = {}
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                hashes[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def test_builder_brief_writes_only_brief_json(self):
        """write_builder_brief_json writes exactly builder_brief.json inside run_dir."""
        before = {p.name for p in self.run_dir.rglob("*") if p.is_file()}
        write_builder_brief_json(self.run_dir)
        after = {p.name for p in self.run_dir.rglob("*") if p.is_file()}
        self.assertEqual(after - before, {"builder_brief.json"})

    def test_markdown_context_writes_only_md_when_brief_exists(self):
        """write_builder_prompt_context_md writes exactly builder_prompt_context.md when brief exists."""
        write_builder_brief_json(self.run_dir)
        before = {p.name for p in self.run_dir.rglob("*") if p.is_file()}
        write_builder_prompt_context_md(self.run_dir)
        after = {p.name for p in self.run_dir.rglob("*") if p.is_file()}
        self.assertEqual(after - before, {"builder_prompt_context.md"})

    def test_no_outputs_under_module_directory(self):
        """Generated outputs do not appear under modules/<slug>/."""
        write_builder_brief_json(self.run_dir)
        write_builder_prompt_context_md(self.run_dir)
        module_files = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        self.assertNotIn("builder_brief.json", module_files)
        self.assertNotIn("builder_prompt_context.md", module_files)

    def test_module_file_hashes_unchanged_after_brief(self):
        """Module file SHA-256 hashes are unchanged after write_builder_brief_json."""
        before = self._file_hashes(self.module_dir)
        write_builder_brief_json(self.run_dir)
        after = self._file_hashes(self.module_dir)
        self.assertEqual(before, after)

    def test_module_file_hashes_unchanged_after_context(self):
        """Module file SHA-256 hashes are unchanged after write_builder_prompt_context_md."""
        write_builder_brief_json(self.run_dir)
        before = self._file_hashes(self.module_dir)
        write_builder_prompt_context_md(self.run_dir)
        after = self._file_hashes(self.module_dir)
        self.assertEqual(before, after)

    def test_no_new_module_report_artifacts_created(self):
        """No module report artifacts are created or refreshed in the module directory."""
        before = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        write_builder_brief_json(self.run_dir)
        write_builder_prompt_context_md(self.run_dir)
        after = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class TestBuilderAuditBriefingNoMutatingWorkflows(unittest.TestCase):
    """Step 3.3: Source-contract tests - no provider, builder, or refresh calls."""

    def setUp(self):
        self.script_path = Path(__file__).resolve().parent / "prepare_builder_from_backstage_audit.py"
        self.script_text = self.script_path.read_text(encoding="utf-8")

    def test_no_create_chat_client(self):
        """Script does not call create_chat_client or OpenAI client constructors."""
        self.assertNotIn("create_chat_client", self.script_text)
        self.assertNotIn("OpenAI(", self.script_text)
        self.assertNotIn("openai.OpenAI(", self.script_text)

    def test_no_openrouter_references(self):
        """Script does not reference openrouter."""
        self.assertNotIn("openrouter", self.script_text.lower())

    def test_no_requests_http_imports(self):
        """Script does not import requests for HTTP calls."""
        self.assertNotIn("import requests", self.script_text)
        self.assertNotIn("from requests", self.script_text)

    def test_no_module_builder_references(self):
        """Script does not reference ModuleBuilder."""
        self.assertNotIn("ModuleBuilder", self.script_text)
        self.assertNotIn("module_builder", self.script_text)

    def test_no_seed_writer_references(self):
        """Script does not reference seed writer flows."""
        self.assertNotIn("seed_writer", self.script_text)

    def test_no_benchmark_refresh(self):
        """Script does not call benchmark_accurate_ingest."""
        self.assertNotIn("benchmark_accurate_ingest", self.script_text)

    def test_no_publishability_refresh(self):
        """Script does not call audit_module_publishability."""
        self.assertNotIn("audit_module_publishability", self.script_text)

    def test_no_readiness_repair(self):
        """Script does not reference readiness repair."""
        self.assertNotIn("readiness_repair", self.script_text)
        self.assertNotIn("character_creation_audit", self.script_text)

    def test_no_media_generation(self):
        """Script does not reference media generation or portrait creation."""
        self.assertNotIn("media_generation", self.script_text)
        self.assertNotIn("generate_and_save_portrait", self.script_text)

    def test_no_module_finisher(self):
        """Script does not reference module finisher."""
        self.assertNotIn("module_finisher", self.script_text)
        self.assertNotIn("toolkit_module_finisher", self.script_text)


if __name__ == "__main__":
    unittest.main()
