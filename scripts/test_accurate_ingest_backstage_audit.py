# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Tests for utils.accurate_ingest_backstage_audit - read-only accurate-ingest
audit input collection.
"""

import hashlib
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Optional

from utils.accurate_ingest_backstage_audit import (
    EXPECTED_ARTIFACT_KEYS,
    build_audit_findings,
    collect_accurate_ingest_audit_inputs,
    summarize_report_artifact,
)


class TestCollectAccurateIngestAuditInputs(unittest.TestCase):
    """Tests for the top-level audit input collection function."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.module_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_artifact(self, name: str, data: dict) -> Path:
        path = self.module_dir / name
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_all_reports_present_and_valid(self):
        """All five expected reports present and parse OK."""
        artifacts = {
            "accurate_ingest_benchmark_report.json": {
                "source_fidelity_status": "pass", "status": "complete",
            },
            "toolkit_build_report.json": {
                "status": "failed", "ready_status": "pass",
                "publishable_status": "fail",
            },
            "validation_report.json": {
                "summary": {"total_passed": 11, "total_failed": 0},
                "status": "pass",
            },
            "source_fidelity_report.json": {
                "source_fidelity_status": "pass",
                "report_version": "v1",
            },
            "build_fidelity_report.json": {
                "status": "pass", "blocker_count": 0,
            },
        }
        for name, data in artifacts.items():
            self._write_artifact(name, data)

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["artifacts"]), 5)
        for art in result["artifacts"]:
            self.assertEqual(
                art["parse_status"], "ok",
                f"{art['artifact_key']} should parse ok",
            )
            self.assertTrue(art["exists"])
            self.assertIn("hash", art)
            self.assertEqual(len(art["hash"]), 64)
            self.assertIn("compact", art)

    def test_all_five_expected_keys_present(self):
        """The five expected artifact keys are all present."""
        expected_keys = [
            "accurate_ingest_benchmark_report",
            "toolkit_build_report",
            "validation_report",
            "source_fidelity_report",
            "build_fidelity_report",
        ]
        self.assertEqual(sorted(EXPECTED_ARTIFACT_KEYS.keys()), sorted(expected_keys))

    def test_missing_optional_report(self):
        """Missing optional report gets missing parse_status; collection continues."""
        self._write_artifact("toolkit_build_report.json", {"status": "pass"})

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        found = {a["artifact_key"]: a for a in result["artifacts"]}

        self.assertEqual(found["toolkit_build_report"]["parse_status"], "ok")
        self.assertTrue(found["toolkit_build_report"]["exists"])

        for key in [
            "accurate_ingest_benchmark_report",
            "validation_report",
            "source_fidelity_report",
            "build_fidelity_report",
        ]:
            self.assertFalse(found[key]["exists"])
            self.assertEqual(found[key]["parse_status"], "missing")

    def test_corrupt_json_report(self):
        """Corrupt JSON produces invalid_json parse_status; collection continues."""
        corrupt_path = self.module_dir / "toolkit_build_report.json"
        with open(corrupt_path, "w") as f:
            f.write("{invalid json!!!")

        self._write_artifact("source_fidelity_report.json", {"source_fidelity_status": "pass"})

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        found = {a["artifact_key"]: a for a in result["artifacts"]}

        self.assertEqual(found["toolkit_build_report"]["parse_status"], "invalid_json")
        self.assertIn("error", found["toolkit_build_report"])
        self.assertEqual(found["source_fidelity_report"]["parse_status"], "ok")
        self.assertTrue(found["source_fidelity_report"]["exists"])

        for key in [
            "accurate_ingest_benchmark_report",
            "validation_report",
            "build_fidelity_report",
        ]:
            self.assertFalse(found[key]["exists"])
            self.assertEqual(found[key]["parse_status"], "missing")

    def test_missing_module_directory(self):
        """Missing module directory produces failed status; no files created."""
        missing = str(self.module_dir / "nonexistent_module")

        result = collect_accurate_ingest_audit_inputs(missing)

        self.assertEqual(result["status"], "failed")
        self.assertIn("error", result)
        self.assertIn("module_directory_not_found", result["error"])
        self.assertFalse(Path(missing).exists())

    def test_read_only_safety(self):
        """Module directory files are unchanged after collection."""
        orig_content = {"key": "value", "status": "pass"}
        artifact_path = self._write_artifact("toolkit_build_report.json", orig_content)

        with open(artifact_path, "rb") as f:
            orig_hash = hashlib.sha256(f.read()).hexdigest()

        collect_accurate_ingest_audit_inputs(str(self.module_dir))

        with open(artifact_path, "rb") as f:
            new_hash = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(orig_hash, new_hash)

    def test_read_only_safety_no_new_files_created(self):
        """No new files are created in the module directory by collection."""
        self._write_artifact("toolkit_build_report.json", {"status": "pass"})

        before = set(self.module_dir.iterdir())

        collect_accurate_ingest_audit_inputs(str(self.module_dir))

        after = set(self.module_dir.iterdir())
        self.assertEqual(before, after)

    def test_path_is_not_a_directory(self):
        """A path that is a file produces failed status."""
        file_path = self.module_dir / "a_file.txt"
        file_path.write_text("not a directory")

        result = collect_accurate_ingest_audit_inputs(str(file_path))

        self.assertEqual(result["status"], "failed")
        self.assertIn("not_a_directory", result["error"])

    def test_compact_status_fields_extracted(self):
        """Compact status extracts only known fields from report data."""
        self._write_artifact("toolkit_build_report.json", {
            "status": "failed",
            "ready_status": "pass",
            "publishable_status": "fail",
            "source_fidelity_status": "pass",
            "effective_publishable_status": "blocked",
            "unknown_field": "should_not_appear",
            "another_unknown": True,
        })

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        art = next(
            a for a in result["artifacts"]
            if a["artifact_key"] == "toolkit_build_report"
        )

        compact = art.get("compact", {})
        self.assertEqual(compact.get("status"), "failed")
        self.assertEqual(compact.get("ready_status"), "pass")
        self.assertEqual(compact.get("publishable_status"), "fail")
        self.assertEqual(compact.get("source_fidelity_status"), "pass")
        self.assertEqual(compact.get("effective_publishable_status"), "blocked")
        self.assertNotIn("unknown_field", compact)
        self.assertNotIn("another_unknown", compact)

    def test_validation_summary_field_extracted_without_status(self):
        """Validation reports with only a summary still produce compact evidence."""
        validation_summary_full = {"total_files": 9, "total_passed": 11, "total_failed": 0}
        self._write_artifact("validation_report.json", {
            "module": "Example_Module",
            "summary": validation_summary_full,
        })

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        art = next(
            a for a in result["artifacts"]
            if a["artifact_key"] == "validation_report"
        )

        self.assertEqual(art["parse_status"], "ok")
        self.assertEqual(art.get("compact", {}).get("summary"), validation_summary_full)

    def test_raw_body_not_embedded(self):
        """Large raw report bodies are not embedded in artifact summaries."""
        large_data = {"status": "pass", "long_array": ["x" * 10000]}
        self._write_artifact("toolkit_build_report.json", large_data)

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        art = next(
            a for a in result["artifacts"]
            if a["artifact_key"] == "toolkit_build_report"
        )

        serialized = json.dumps(art)
        self.assertNotIn("x" * 200, serialized)

    def test_unparseable_json_does_not_crash_collection(self):
        """A file that exists but is unreadable as JSON fails open."""
        bad_path = self.module_dir / "validation_report.json"
        bad_path.write_text("not json at all\n")

        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        art = next(
            a for a in result["artifacts"]
            if a["artifact_key"] == "validation_report"
        )

        self.assertEqual(art["parse_status"], "invalid_json")
        self.assertTrue(art["exists"])
        self.assertIn("error", art)

    def test_collected_at_iso_format(self):
        """collected_at timestamp is present and ISO-formatted."""
        result = collect_accurate_ingest_audit_inputs(str(self.module_dir))
        self.assertIn("collected_at", result)
        self.assertTrue("T" in result["collected_at"] or "Z" in result["collected_at"])


class TestSummarizeReportArtifact(unittest.TestCase):
    """Tests for the individual artifact summary helper."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, name: str, data: dict) -> Path:
        path = self.base / name
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_nonexistent_file_returns_missing(self):
        path = self.base / "nonexistent.json"
        summary = summarize_report_artifact(path, "test_key")
        self.assertFalse(summary["exists"])
        self.assertEqual(summary["parse_status"], "missing")
        self.assertEqual(summary["artifact_key"], "test_key")

    def test_valid_json_returns_ok_with_hash(self):
        path = self._write("report.json", {"status": "pass"})
        summary = summarize_report_artifact(path, "my_report")
        self.assertTrue(summary["exists"])
        self.assertEqual(summary["parse_status"], "ok")
        self.assertIn("hash", summary)
        self.assertEqual(len(summary["hash"]), 64)

    def test_corrupt_json_returns_invalid(self):
        path = self.base / "bad.json"
        path.write_text("{{{")
        summary = summarize_report_artifact(path, "bad")
        self.assertTrue(summary["exists"])
        self.assertEqual(summary["parse_status"], "invalid_json")
        self.assertIn("error", summary)

    def test_non_dict_json_returns_ok_no_compact(self):
        path = self._write("array.json", [1, 2, 3])
        summary = summarize_report_artifact(path, "array_data")
        self.assertEqual(summary["parse_status"], "ok")
        self.assertNotIn("compact", summary)


class TestBuildAuditFindings(unittest.TestCase):
    """Tests for the report-disagreement and domain-finding builder."""

    def _make_artifact(
        self, key: str, exists: bool = True,
        parse_status: str = "ok", compact: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> dict:
        art: dict = {
            "artifact_key": key,
            "path": f"/fake/{key}.json",
            "exists": exists,
            "parse_status": parse_status,
        }
        if compact:
            art["compact"] = compact
        if error:
            art["error"] = error
        return art

    def _ok_collection(self, artifacts: list) -> dict:
        return {
            "status": "ok",
            "module_path": "/fake",
            "collected_at": "2026-05-25T00:00:00",
            "artifacts": artifacts,
        }

    def test_all_missing_artifacts(self):
        """All artifacts missing produces warning-level artifact_presence findings."""
        artifacts = [
            self._make_artifact(k, exists=False, parse_status="missing")
            for k in EXPECTED_ARTIFACT_KEYS
        ]
        findings = build_audit_findings(self._ok_collection(artifacts))
        presence = [f for f in findings if f["domain"] == "artifact_presence"]
        self.assertEqual(len(presence), 5)
        for f in presence:
            self.assertEqual(f["severity"], "warning")
            self.assertEqual(f["message"], f"Expected artifact '{f['evidence_keys'][0]}' is missing")

    def test_corrupt_artifact_produces_blocker(self):
        """Corrupt artifact produces blocker-level artifact_presence finding."""
        artifacts = [
            self._make_artifact("toolkit_build_report", exists=True,
                                parse_status="invalid_json", error="invalid json"),
        ]
        for k in EXPECTED_ARTIFACT_KEYS:
            if k != "toolkit_build_report":
                artifacts.append(
                    self._make_artifact(k, exists=True, parse_status="ok", compact={"status": "pass"})
                )
        findings = build_audit_findings(self._ok_collection(artifacts))
        corrupt = [
            f for f in findings
            if f["domain"] == "artifact_presence"
            and f["evidence_keys"] == ["toolkit_build_report"]
        ]
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0]["severity"], "blocker")
        self.assertIn("unparseable", corrupt[0]["message"])

    def test_source_fidelity_pass_publishability_fail(self):
        """Disagreement between source_fidelity=pass and publishability=fail."""
        artifacts = [
            self._make_artifact("source_fidelity_report", compact={"source_fidelity_status": "pass"}),
            self._make_artifact("toolkit_build_report", compact={
                "publishable_status": "fail", "status": "failed", "ready_status": "pass",
            }),
            self._make_artifact("accurate_ingest_benchmark_report", compact={
                "source_fidelity_status": "pass", "status": "complete",
            }),
            self._make_artifact("validation_report", compact={"status": "pass"}),
            self._make_artifact("build_fidelity_report", compact={"status": "pass"}),
        ]
        findings = build_audit_findings(self._ok_collection(artifacts))
        consistency = [f for f in findings if f["domain"] == "report_consistency"]
        self.assertGreater(len(consistency), 0)
        for f in consistency:
            self.assertEqual(f["severity"], "blocker")
            self.assertIn("source_fidelity_status=pass", f["message"])
            self.assertIn("toolkit_build_report", f["evidence_keys"])

    def test_consistency_uses_benchmark_evidence_when_source_report_missing(self):
        """Consistency finding cites benchmark when source_fidelity_report is missing."""
        artifacts = [
            self._make_artifact("source_fidelity_report", exists=False, parse_status="missing"),
            self._make_artifact("accurate_ingest_benchmark_report", compact={
                "source_fidelity_status": "pass", "status": "complete",
            }),
            self._make_artifact("toolkit_build_report", compact={
                "publishable_status": "fail", "status": "failed",
            }),
            self._make_artifact("validation_report", compact={"status": "pass"}),
            self._make_artifact("build_fidelity_report", compact={"status": "pass"}),
        ]
        findings = build_audit_findings(self._ok_collection(artifacts))
        consistency = [f for f in findings if f["domain"] == "report_consistency"]
        self.assertEqual(len(consistency), 1)
        self.assertEqual(consistency[0]["evidence_keys"], [
            "accurate_ingest_benchmark_report",
            "toolkit_build_report",
        ])

    def test_clean_agree_pass_no_report_consistency_blocker(self):
        """All reports agree-pass produces no report_consistency blocker findings."""
        artifacts = [
            self._make_artifact(k, compact={"status": "pass"})
            for k in EXPECTED_ARTIFACT_KEYS
        ]
        findings = build_audit_findings(self._ok_collection(artifacts))
        consistency = [f for f in findings if f["domain"] == "report_consistency"]
        self.assertEqual(len(consistency), 0)

    def test_missing_module_directory_blocker(self):
        """Missing module directory produces a single blocker finding."""
        collection = {
            "status": "failed",
            "module_path": "/fake/nonexistent",
            "error": "module_directory_not_found:/fake/nonexistent",
            "artifacts": [],
        }
        findings = build_audit_findings(collection)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["domain"], "artifact_presence")
        self.assertEqual(findings[0]["severity"], "blocker")
        self.assertIn("Module access failed", findings[0]["message"])

    def test_readiness_blocker_when_not_pass(self):
        """Non-pass readiness status produces blocker."""
        artifacts = [
            self._make_artifact("toolkit_build_report", compact={
                "status": "failed", "ready_status": "blocked", "publishable_status": "fail",
            }),
        ]
        for k in EXPECTED_ARTIFACT_KEYS:
            if k != "toolkit_build_report":
                artifacts.append(
                    self._make_artifact(k, compact={"status": "pass"})
                )
        findings = build_audit_findings(self._ok_collection(artifacts))
        readiness = [f for f in findings if f["domain"] == "readiness"]
        self.assertGreater(len(readiness), 0)
        for f in readiness:
            self.assertEqual(f["severity"], "blocker")

    def test_validation_summary_info_without_status(self):
        """Validation summary with zero failures creates info finding."""
        artifacts = [
            self._make_artifact("validation_report", compact={
                "summary": {"total_files": 9, "total_passed": 11, "total_failed": 0},
            }),
        ]
        for k in EXPECTED_ARTIFACT_KEYS:
            if k != "validation_report":
                artifacts.append(self._make_artifact(k, compact={"status": "pass"}))
        findings = build_audit_findings(self._ok_collection(artifacts))
        validation = [f for f in findings if f["domain"] == "validation"]
        self.assertEqual(len(validation), 1)
        self.assertEqual(validation[0]["severity"], "info")
        self.assertIn("total_failed=0", validation[0]["message"])

    def test_validation_summary_failed_blocker_without_status(self):
        """Validation summary with failures creates blocker finding."""
        artifacts = [
            self._make_artifact("validation_report", compact={
                "summary": {"total_files": 9, "total_passed": 10, "total_failed": 2},
            }),
        ]
        for k in EXPECTED_ARTIFACT_KEYS:
            if k != "validation_report":
                artifacts.append(self._make_artifact(k, compact={"status": "pass"}))
        findings = build_audit_findings(self._ok_collection(artifacts))
        validation = [f for f in findings if f["domain"] == "validation"]
        self.assertEqual(len(validation), 1)
        self.assertEqual(validation[0]["severity"], "blocker")
        self.assertIn("total_failed=2", validation[0]["message"])

    def test_domain_findings_have_correct_structure(self):
        """All finding dicts contain required keys."""
        artifacts = [
            self._make_artifact(k, compact={"status": "pass"})
            for k in EXPECTED_ARTIFACT_KEYS
        ]
        findings = build_audit_findings(self._ok_collection(artifacts))
        for f in findings:
            self.assertIn("domain", f)
            self.assertIn("severity", f)
            self.assertIn("message", f)
            self.assertIn("evidence_keys", f)
            self.assertIsInstance(f["evidence_keys"], list)


class TestBackstageAgentCliMutationSafety(unittest.TestCase):
    """Mutation-safety tests for the accurate-ingest-audit CLI runner."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        self._populate_module()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_json(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f)

    def _populate_module(self) -> None:
        reports = {
            "accurate_ingest_benchmark_report.json": {
                "source_fidelity_status": "pass", "status": "complete",
            },
            "toolkit_build_report.json": {
                "status": "failed", "ready_status": "pass",
                "publishable_status": "fail",
            },
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {
                "source_fidelity_status": "pass", "report_version": "v1",
            },
            "build_fidelity_report.json": {"status": "pass", "blocker_count": 0},
        }
        for name, data in reports.items():
            self._write_json(self.module_dir / name, data)
        extra = self.module_dir / "unexpected_extra_file.json"
        self._write_json(extra, {"unused": True})

    def _hash_tree(self, root: Path) -> dict:
        hashes = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(root))
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                hashes[rel] = h.hexdigest()
        return hashes

    def _relative_file_set(self, root: Path) -> set:
        return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}

    def test_cli_runner_does_not_mutate_module(self):
        """run_accurate_ingest_audit does not change module files or create new ones."""
        import scripts.run_backstage_agent as ra

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            before_hashes = self._hash_tree(self.module_dir)
            before_files = self._relative_file_set(self.module_dir)

            output_dir = Path(self.tmpdir.name) / "output"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)

            after_hashes = self._hash_tree(self.module_dir)
            after_files = self._relative_file_set(self.module_dir)

            self.assertEqual(before_hashes, after_hashes, "Module file hashes changed")
            self.assertEqual(before_files, after_files, "Module files added or removed")

            run_dir = Path(result["output_dir"])
            self.assertEqual(run_dir.parent, output_dir)
            output_files = {p.name for p in run_dir.iterdir() if p.is_file()}
            for expected in ("run.json", "evidence.json", "audit_report.json", "recommendation.json"):
                self.assertIn(expected, output_files)

    def test_missing_module_produces_error_output(self):
        """Missing module slug produces output files with error state, no module tree writes."""
        import scripts.run_backstage_agent as ra

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = Path(self.tmpdir.name) / "output_missing"
            result = ra.run_accurate_ingest_audit("NonExistent", output_dir)

            self.assertEqual(result["blockers"], 1)

            run_dir = Path(result["output_dir"])
            self.assertEqual(run_dir.parent, output_dir)
            with open(run_dir / "evidence.json") as f:
                evidence = json.load(f)
            self.assertEqual(evidence.get("status"), "failed")

            nonexistent_dir = self.fake_root / "modules" / "NonExistent"
            self.assertFalse(nonexistent_dir.exists())


class TestBackstageAgentBenchmarkCommand(unittest.TestCase):
    """Tests for the optional benchmark command collection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass"},
            "toolkit_build_report.json": {"status": "pass"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass"},
            "build_fidelity_report.json": {"status": "pass"},
        }
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _valid_benchmark_result(self) -> dict:
        return {
            "command": "python3 benchmark_accurate_ingest.py --module Test_Module --json --out /tmp/out",
            "exit_code": 0,
            "stdout_parse_status": "ok",
            "stderr_preview": "",
            "parsed_summary": {
                "source_fidelity_status": "pass",
                "passed": True,
                "degraded": False,
                "blocked": False,
                "module_slug": "Test_Module",
                "benchmark_version": "v1",
            },
        }

    def test_disabled_default_no_commands_in_evidence(self):
        """include_benchmark_command=False does not add commands to evidence."""
        import scripts.run_backstage_agent as ra

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = Path(self.tmpdir.name) / "out_disabled"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        self.assertNotIn("commands", evidence)

    def test_enabled_adds_benchmark_command_evidence(self):
        """include_benchmark_command=True adds commands.benchmark to evidence."""
        import scripts.run_backstage_agent as ra

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra, "run_benchmark_command",
                                            return_value=self._valid_benchmark_result()):
                output_dir = Path(self.tmpdir.name) / "out_enabled"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir,
                                                      include_benchmark_command=True)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        self.assertIn("commands", evidence)
        self.assertIn("benchmark", evidence["commands"])
        cmd = evidence["commands"]["benchmark"]
        self.assertEqual(cmd["stdout_parse_status"], "ok")
        self.assertIsNotNone(cmd["parsed_summary"])
        self.assertEqual(cmd["parsed_summary"]["source_fidelity_status"], "pass")

    def test_run_benchmark_command_uses_json_and_runtime_out(self):
        """Benchmark command uses --json and --out under the audit run directory."""
        import scripts.run_backstage_agent as ra

        run_dir = Path(self.tmpdir.name) / "run_dir"
        run_dir.mkdir()
        stdout = json.dumps({
            "source_fidelity_status": "pass",
            "passed": True,
            "degraded": False,
            "blocked": False,
            "module_slug": "Test_Module",
            "benchmark_version": "v1",
        })
        proc = unittest.mock.Mock(returncode=0, stdout=stdout, stderr="[OK] written")

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", return_value=proc) as run_mock:
                evidence = ra.run_benchmark_command("Test_Module", run_dir)

        cmd = run_mock.call_args.args[0]
        self.assertIn("--json", cmd)
        self.assertIn("--out", cmd)
        out_path = Path(cmd[cmd.index("--out") + 1])
        self.assertEqual(out_path, run_dir / "command_outputs" / "benchmark")
        self.assertNotIn(str(self.module_dir), str(out_path))
        self.assertEqual(evidence["stdout_parse_status"], "ok")
        self.assertEqual(evidence["parsed_summary"]["source_fidelity_status"], "pass")

    def test_invalid_json_stdout_produces_blocker_finding(self):
        """Invalid JSON with nonzero exit from benchmark produces blocker finding."""
        import scripts.run_backstage_agent as ra

        bad_result = {
            "command": "benchmark script",
            "exit_code": 1,
            "stdout_parse_status": "invalid_json",
            "stderr_preview": "corrupt data",
            "parsed_summary": None,
        }

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra, "run_benchmark_command",
                                            return_value=bad_result):
                output_dir = Path(self.tmpdir.name) / "out_invalid"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir,
                                                       include_benchmark_command=True)

        self.assertGreater(result["blockers"], 0)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "audit_report.json") as f:
            report = json.load(f)
        cmd_findings = [f for f in report["findings"] if f["domain"] == "command_execution"]
        self.assertGreater(len(cmd_findings), 0)
        self.assertEqual(cmd_findings[0]["evidence_keys"], ["commands.benchmark"])


class TestBackstageAgentPublishabilityCommand(unittest.TestCase):
    """Tests for the optional publishability command collection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass"},
            "toolkit_build_report.json": {"status": "pass"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass"},
            "build_fidelity_report.json": {"status": "pass"},
        }
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _valid_publishability_json(self) -> str:
        return json.dumps({
            "ready_status": "pass",
            "publishable_status": "pass",
            "source_fidelity_status": "pass",
            "effective_publishable_status": "pass",
            "exit_code": 0,
            "blocking_errors": [],
            "warnings": ["minor warning"],
            "publication_gates": {
                "semantic_audit": {"status": "pass"},
                "semantic_probes": {"status": "pass"},
            },
        })

    def test_disabled_default_no_publishability_in_evidence(self):
        """include_publishability_command=False does not add publishability to evidence."""
        import scripts.run_backstage_agent as ra

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = Path(self.tmpdir.name) / "out_disabled"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        self.assertNotIn("commands", evidence)

    def test_enabled_adds_publishability_evidence(self):
        """include_publishability_command=True adds commands.publishability to evidence."""
        import scripts.run_backstage_agent as ra

        proc = unittest.mock.Mock(returncode=0, stdout=self._valid_publishability_json(), stderr="")

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", return_value=proc):
                output_dir = Path(self.tmpdir.name) / "out_enabled"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir,
                                                      include_publishability_command=True)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        self.assertIn("commands", evidence)
        self.assertIn("publishability", evidence["commands"])
        cmd = evidence["commands"]["publishability"]
        self.assertEqual(cmd["stdout_parse_status"], "ok")
        self.assertIsNotNone(cmd["parsed_summary"])
        self.assertEqual(cmd["parsed_summary"]["ready_status"], "pass")
        self.assertEqual(cmd["parsed_summary"]["publishable_status"], "pass")
        self.assertEqual(cmd["parsed_summary"]["blocking_error_count"], 0)
        self.assertEqual(cmd["parsed_summary"]["semantic_audit_status"], "pass")

    def test_publishability_command_args(self):
        """Publishability command includes --module and --json."""
        import scripts.run_backstage_agent as ra

        proc = unittest.mock.Mock(returncode=0, stdout=self._valid_publishability_json(), stderr="")

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", return_value=proc) as run_mock:
                ra.run_publishability_command("Test_Module")

        cmd = run_mock.call_args.args[0]
        self.assertIn("--module", cmd)
        self.assertEqual(cmd[cmd.index("--module") + 1], "Test_Module")
        self.assertIn("--json", cmd)
        module_path_str = str(self.module_dir)
        for arg in cmd:
            self.assertNotIn(str(module_path_str), arg,
                             msg=f"Command argument should not reference module directory: {arg}")

    def test_both_commands_enabled(self):
        """Both benchmark and publishability commands appear in evidence.commands."""
        import scripts.run_backstage_agent as ra

        pub_proc = unittest.mock.Mock(returncode=0, stdout=self._valid_publishability_json(), stderr="")
        bench_proc = unittest.mock.Mock(returncode=0, stdout=json.dumps({
            "source_fidelity_status": "pass", "passed": True,
            "degraded": False, "blocked": False,
            "module_slug": "Test_Module", "benchmark_version": "v1",
        }), stderr="[OK]")

        def _run_side_effect(cmd, *a, **kw):
            if "benchmark_accurate_ingest" in str(cmd):
                return bench_proc
            return pub_proc

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", side_effect=_run_side_effect):
                output_dir = Path(self.tmpdir.name) / "out_both"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir,
                                                      include_benchmark_command=True,
                                                      include_publishability_command=True)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        self.assertIn("commands", evidence)
        self.assertIn("benchmark", evidence["commands"])
        self.assertIn("publishability", evidence["commands"])

    def test_invalid_json_produces_blocker(self):
        """Invalid JSON with nonzero exit from publishability produces blocker finding."""
        import scripts.run_backstage_agent as ra

        proc = unittest.mock.Mock(returncode=1, stdout="not json", stderr="parse error")

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", return_value=proc):
                output_dir = Path(self.tmpdir.name) / "out_invalid"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir,
                                                       include_publishability_command=True)

        self.assertGreater(result["blockers"], 0)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "audit_report.json") as f:
            report = json.load(f)
        cmd_findings = [f for f in report["findings"] if f["domain"] == "command_execution"
                        and "publishability" in str(f.get("evidence_keys", []))]
        self.assertGreater(len(cmd_findings), 0)
        self.assertEqual(cmd_findings[0]["evidence_keys"], ["commands.publishability"])


class TestParseJsonStdout(unittest.TestCase):
    """Tests for _parse_json_stdout helper."""

    def test_valid_json_object(self):
        import scripts.run_backstage_agent as ra
        status, parsed = ra._parse_json_stdout('{"status": "pass"}')
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, {"status": "pass"})

    def test_blank_stdout(self):
        import scripts.run_backstage_agent as ra
        status, parsed = ra._parse_json_stdout("   ")
        self.assertEqual(status, "empty")
        self.assertEqual(parsed, {})

    def test_empty_string(self):
        import scripts.run_backstage_agent as ra
        status, parsed = ra._parse_json_stdout("")
        self.assertEqual(status, "empty")
        self.assertEqual(parsed, {})

    def test_malformed_json(self):
        import scripts.run_backstage_agent as ra
        status, parsed = ra._parse_json_stdout("not json")
        self.assertEqual(status, "invalid_json")
        self.assertEqual(parsed, {})

    def test_json_array_rejected(self):
        import scripts.run_backstage_agent as ra
        status, parsed = ra._parse_json_stdout("[1, 2, 3]")
        self.assertEqual(status, "invalid_json")
        self.assertEqual(parsed, {})


class TestPreviewText(unittest.TestCase):
    """Tests for _preview_text helper."""

    def test_short_text_unchanged(self):
        import scripts.run_backstage_agent as ra
        result = ra._preview_text("short", limit=10)
        self.assertEqual(result, "short")

    def test_long_text_capped(self):
        import scripts.run_backstage_agent as ra
        long = "x" * 100
        result = ra._preview_text(long, limit=10)
        self.assertEqual(len(result), 13)
        self.assertTrue(result.endswith("..."))
        self.assertEqual(result, "xxxxxxxxxx...")

    def test_exact_limit_no_ellipsis(self):
        import scripts.run_backstage_agent as ra
        exact = "y" * 5
        result = ra._preview_text(exact, limit=5)
        self.assertEqual(result, exact)

    def test_default_limit(self):
        import scripts.run_backstage_agent as ra
        short = "hello"
        result = ra._preview_text(short)
        self.assertEqual(result, short)


class TestBackstageAgentCommandEvidenceContract(unittest.TestCase):
    """Formal evidence shape contract for benchmark and publishability commands."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass"},
            "toolkit_build_report.json": {"status": "pass"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass"},
            "build_fidelity_report.json": {"status": "pass"},
        }
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_audit_with_mocked_command(
        self, command_key: str, stdout: str,
        returncode: int = 0, stderr: str = "",
    ) -> dict:
        import scripts.run_backstage_agent as ra

        def _side_effect(cmd, *a, **kw):
            return unittest.mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)

        flags = {}
        if command_key == "benchmark":
            flags["include_benchmark_command"] = True
        elif command_key == "publishability":
            flags["include_publishability_command"] = True

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", side_effect=_side_effect):
                output_dir = Path(self.tmpdir.name) / f"out_{command_key}"
                result = ra.run_accurate_ingest_audit("Test_Module", output_dir, **flags)

        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            evidence = json.load(f)
        with open(run_dir / "audit_report.json") as f:
            report = json.load(f)
        return evidence, report, result

    def _valid_benchmark_stdout(self) -> str:
        return json.dumps({
            "source_fidelity_status": "pass", "passed": True,
            "degraded": False, "blocked": False,
            "module_slug": "Test_Module", "benchmark_version": "v1",
        })

    def _valid_publishability_stdout(self) -> str:
        return json.dumps({
            "ready_status": "pass", "publishable_status": "pass",
            "source_fidelity_status": "pass", "effective_publishable_status": "pass",
            "exit_code": 0, "blocking_errors": [], "warnings": [],
            "publication_gates": {
                "semantic_audit": {"status": "pass"},
                "semantic_probes": {"status": "pass"},
            },
        })

    # --- Benchmark evidence shape ---

    def test_benchmark_evidence_shapes(self):
        """Benchmark command evidence contains all required compact fields."""
        evidence, report, result = self._run_audit_with_mocked_command(
            "benchmark", self._valid_benchmark_stdout(),
        )
        cmd = evidence["commands"]["benchmark"]
        self.assertEqual(set(cmd.keys()), {
            "command",
            "exit_code",
            "stdout_parse_status",
            "stderr_preview",
            "parsed_summary",
        })
        self.assertEqual(cmd["stdout_parse_status"], "ok")
        self.assertIsNotNone(cmd["parsed_summary"])

    def test_benchmark_parsed_summary_compact(self):
        """Benchmark parsed_summary does not contain full raw JSON bodies."""
        large = {"source_fidelity_status": "pass", "passed": True,
                 "degraded": False, "blocked": False,
                 "module_slug": "Test_Module", "benchmark_version": "v1",
                 "long_array": ["x" * 10000]}
        stdout = json.dumps(large)
        evidence, report, result = self._run_audit_with_mocked_command("benchmark", stdout)
        summary = evidence["commands"]["benchmark"]["parsed_summary"]
        serialized = json.dumps(summary)
        self.assertNotIn("x" * 200, serialized)
        self.assertNotIn("long_array", serialized)

    def test_benchmark_fail_evidence_refs_includes_commands(self):
        """Benchmark parse failure includes commands.benchmark in audit evidence_refs."""
        evidence, report, result = self._run_audit_with_mocked_command(
            "benchmark", "not json", returncode=1, stderr="error",
        )
        self.assertIn("commands.benchmark", report.get("evidence_refs", []))

    # --- Publishability evidence shape ---

    def test_publishability_evidence_shapes(self):
        """Publishability command evidence contains all required compact fields."""
        evidence, report, result = self._run_audit_with_mocked_command(
            "publishability", self._valid_publishability_stdout(),
        )
        cmd = evidence["commands"]["publishability"]
        self.assertEqual(set(cmd.keys()), {
            "command",
            "exit_code",
            "stdout_parse_status",
            "stderr_preview",
            "parsed_summary",
        })
        self.assertEqual(cmd["stdout_parse_status"], "ok")
        self.assertIsNotNone(cmd["parsed_summary"])

    def test_publishability_parsed_summary_compact(self):
        """Publishability parsed_summary does not contain full raw JSON bodies."""
        large = {"ready_status": "pass", "publishable_status": "pass",
                 "blocking_errors": [{"description": "x" * 10000}]}
        stdout = json.dumps(large)
        evidence, report, result = self._run_audit_with_mocked_command("publishability", stdout)
        summary = evidence["commands"]["publishability"]["parsed_summary"]
        self.assertEqual(summary["blocking_error_count"], 1)
        serialized = json.dumps(summary)
        self.assertNotIn("x" * 200, serialized)

    def test_publishability_fail_evidence_refs_includes_commands(self):
        """Publishability parse failure includes commands.publishability in audit evidence_refs."""
        evidence, report, result = self._run_audit_with_mocked_command(
            "publishability", "not json", returncode=1, stderr="error",
        )
        self.assertIn("commands.publishability", report.get("evidence_refs", []))


class TestBackstageAgentRuntimeOutputContract(unittest.TestCase):
    """Step 3.1: Runtime output contract tests for the backstage audit runner.

    Verifies:
      - Default output path resolves under data/agent_runs/accurate_ingest_audit/
      - Supplied output dir produces exactly four top-level JSON files
      - command_outputs/ is allowed only when command flags are enabled
      - task_id consistency across run.json, audit_report.json, recommendation.json
      - run.json.output_dir equals the actual run directory
      - run.json.module_path equals the resolved module path
      - No output files ever land under the module directory
      - Module files are never mutated
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass", "status": "complete"},
            "toolkit_build_report.json": {"status": "failed", "ready_status": "pass", "publishable_status": "fail"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass", "report_version": "v1"},
            "build_fidelity_report.json": {"status": "pass", "blocker_count": 0},
        }
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _hash_tree(self, root: Path) -> dict:
        hashes = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(root))
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                hashes[rel] = h.hexdigest()
        return hashes

    def test_default_output_path_under_data_agent_runs(self):
        """Default output directory places run under data/agent_runs/accurate_ingest_audit/<task_id>/."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            default_base = self.fake_root / ra.DEFAULT_OUTPUT_BASE
            result = ra.run_accurate_ingest_audit("Test_Module", default_base)
        run_dir = Path(result["output_dir"])
        self.assertTrue(str(run_dir).startswith(str(default_base)),
                        f"Run dir {run_dir} not under default base {default_base}")
        self.assertEqual(run_dir.parent, default_base)

    def test_four_top_level_json_files_written(self):
        """Run directory contains exactly run.json, evidence.json, audit_report.json, recommendation.json."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
        run_dir = Path(result["output_dir"])
        expected = {"run.json", "evidence.json", "audit_report.json", "recommendation.json"}
        actual = {p.name for p in run_dir.iterdir() if p.is_file()}
        self.assertEqual(actual, expected)
        self.assertEqual({p.name for p in run_dir.iterdir() if p.is_dir()}, set())

    def test_command_outputs_not_created_without_command_flags(self):
        """command_outputs/ is not created when optional command flags are disabled."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_no_cmds"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
        run_dir = Path(result["output_dir"])
        self.assertFalse((run_dir / "command_outputs").exists())

    def test_four_files_with_command_flags_no_module_mutation(self):
        """With command flags enabled, four JSON files written and module dir unchanged."""
        import scripts.run_backstage_agent as ra
        proc = unittest.mock.Mock(returncode=0, stdout=json.dumps({
            "source_fidelity_status": "pass", "passed": True,
            "degraded": False, "blocked": False,
            "module_slug": "Test_Module", "benchmark_version": "v1",
        }), stderr="")
        pub_proc = unittest.mock.Mock(returncode=0, stdout=json.dumps({
            "ready_status": "pass", "publishable_status": "pass",
            "source_fidelity_status": "pass", "effective_publishable_status": "pass",
            "exit_code": 0, "blocking_errors": [], "warnings": [],
            "publication_gates": {"semantic_audit": {"status": "pass"}, "semantic_probes": {"status": "pass"}},
        }), stderr="")

        def _side(cmd, *a, **kw):
            if "benchmark_accurate_ingest" in str(cmd):
                return proc
            return pub_proc

        before_hashes = self._hash_tree(self.module_dir)
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", side_effect=_side):
                output_dir = self.fake_root / "output_with_cmds"
                result = ra.run_accurate_ingest_audit(
                    "Test_Module", output_dir,
                    include_benchmark_command=True,
                    include_publishability_command=True,
                )
        after_hashes = self._hash_tree(self.module_dir)
        self.assertEqual(before_hashes, after_hashes, "Module files mutated with command flags enabled")

        run_dir = Path(result["output_dir"])
        expected_files = {"run.json", "evidence.json", "audit_report.json", "recommendation.json"}
        actual_files = {p.name for p in run_dir.iterdir() if p.is_file()}
        self.assertEqual(actual_files, expected_files)

    def test_task_id_consistent_across_report_files(self):
        """run.json, audit_report.json, recommendation.json share the same task_id."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_tid"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
        run_dir = Path(result["output_dir"])

        with open(run_dir / "run.json") as f:
            run_data = json.load(f)
        with open(run_dir / "audit_report.json") as f:
            audit_data = json.load(f)
        with open(run_dir / "recommendation.json") as f:
            rec_data = json.load(f)

        self.assertEqual(run_data["task_id"], result["task_id"])
        self.assertEqual(audit_data["task_id"], result["task_id"])
        self.assertEqual(rec_data["task_id"], result["task_id"])

    def test_run_json_metadata_fields(self):
        """run.json contains output_dir pointing to actual run dir and correct module_path."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_meta"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
        run_dir = Path(result["output_dir"])

        with open(run_dir / "run.json") as f:
            run_data = json.load(f)

        self.assertEqual(run_data["output_dir"], str(run_dir))
        self.assertEqual(run_data["module_path"], str(self.module_dir))
        self.assertEqual(run_data["module_slug"], "Test_Module")
        self.assertEqual(run_data["command"], "accurate-ingest-audit")
        self.assertEqual(run_data["status"], "completed")

    def test_no_output_files_under_module_directory(self):
        """Audit runner never writes to or creates files under the module directory."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            before_hashes = self._hash_tree(self.module_dir)
            before_files = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
            output_dir = self.fake_root / "output_safe"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
            after_hashes = self._hash_tree(self.module_dir)
            after_files = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}
        self.assertEqual(before_hashes, after_hashes)
        self.assertEqual(before_files, after_files)

    def test_no_module_path_in_output_file_relative_paths(self):
        """Output file paths under run_dir never contain 'modules/' as a component."""
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_nomod"
            result = ra.run_accurate_ingest_audit("Test_Module", output_dir)
        run_dir = Path(result["output_dir"])
        for f in run_dir.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(run_dir))
                self.assertNotIn("modules", rel,
                                 f"Output file {rel} contains 'modules' in path")
                self.assertNotIn(str(self.module_dir).replace(str(self.fake_root), "").lstrip("/"), rel,
                                 f"Output file {rel} references module directory path")


class TestBackstageAgentReportSchema(unittest.TestCase):
    """Step 3.2: Report schema tests for evidence references, grouped findings,
    report consistency summary, and next-step recommendation."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_reports(self, reports: dict):
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def _run_audit(self, output_subdir: str = "output") -> dict:
        import scripts.run_backstage_agent as ra
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / output_subdir
            return ra.run_accurate_ingest_audit("Test_Module", output_dir)

    def _load_audit_report(self, result: dict) -> dict:
        run_dir = Path(result["output_dir"])
        with open(run_dir / "audit_report.json") as f:
            return json.load(f)

    def _load_recommendation(self, result: dict) -> dict:
        run_dir = Path(result["output_dir"])
        with open(run_dir / "recommendation.json") as f:
            return json.load(f)

    def _load_evidence(self, result: dict) -> dict:
        run_dir = Path(result["output_dir"])
        with open(run_dir / "evidence.json") as f:
            return json.load(f)

    def _all_pass_reports(self) -> dict:
        return {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass", "status": "complete"},
            "toolkit_build_report.json": {"status": "pass", "ready_status": "pass", "publishable_status": "pass"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass", "report_version": "v1"},
            "build_fidelity_report.json": {"status": "pass", "blocker_count": 0},
        }

    def _source_pass_toolkit_fail_reports(self) -> dict:
        return {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass", "status": "complete"},
            "toolkit_build_report.json": {"status": "failed", "ready_status": "pass", "publishable_status": "fail"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass", "report_version": "v1"},
            "build_fidelity_report.json": {"status": "pass", "blocker_count": 0},
        }

    def test_grouped_findings_contains_all_findings_exactly_once(self):
        """grouped_findings contains every finding exactly once, grouped by domain."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_grouped")
        report = self._load_audit_report(result)
        self.assertIn("grouped_findings", report)
        grouped = report["grouped_findings"]
        self.assertIsInstance(grouped, dict)
        all_grouped = []
        for domain, findings in grouped.items():
            self.assertIsInstance(domain, str)
            self.assertIsInstance(findings, list)
            all_grouped.extend(findings)
        self.assertEqual(len(all_grouped), report["finding_count"])
        for f in report["findings"]:
            domain = f["domain"]
            self.assertIn(domain, grouped)
            self.assertIn(f, grouped[domain])

    def test_grouped_findings_domain_keys_match_finding_domains(self):
        """grouped_findings keys correspond to finding domains."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_domains")
        report = self._load_audit_report(result)
        expected_domains = set(f["domain"] for f in report["findings"])
        self.assertEqual(set(report["grouped_findings"].keys()), expected_domains)

    def test_report_consistency_summary_present_when_disagreement(self):
        """report_consistency_summary reflects report-consistency findings when source passes but toolkit fails."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_consistency")
        report = self._load_audit_report(result)
        self.assertIn("report_consistency_summary", report)
        summary = report["report_consistency_summary"]
        self.assertGreater(summary["count"], 0)
        self.assertIn("evidence_refs", summary)
        self.assertIn("blocker_count", summary)
        self.assertIn("warning_count", summary)
        self.assertIn("findings", summary)
        self.assertEqual(len(summary["findings"]), summary["count"])

    def test_report_consistency_summary_empty_when_all_pass(self):
        """report_consistency_summary has zero count when all reports agree-pass."""
        self._write_reports(self._all_pass_reports())
        result = self._run_audit("output_allpass")
        report = self._load_audit_report(result)
        summary = report["report_consistency_summary"]
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["blocker_count"], 0)
        self.assertEqual(summary["warning_count"], 0)
        self.assertEqual(len(summary["findings"]), 0)

    def test_next_step_recommendation_matches_recommendation_json(self):
        """next_step_recommendation matches recommendation.json fields."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_rec")
        report = self._load_audit_report(result)
        rec = self._load_recommendation(result)
        self.assertIn("next_step_recommendation", report)
        nsr = report["next_step_recommendation"]
        self.assertEqual(nsr["recommended_action"], rec["recommended_action"])
        self.assertEqual(nsr["reason"], rec["reason"])
        self.assertEqual(nsr["evidence_refs"], rec["evidence_refs"])

    def test_next_step_recommendation_structure(self):
        """next_step_recommendation has required fields."""
        self._write_reports(self._all_pass_reports())
        result = self._run_audit("output_struct")
        report = self._load_audit_report(result)
        nsr = report["next_step_recommendation"]
        self.assertIn("recommended_action", nsr)
        self.assertIn("reason", nsr)
        self.assertIn("evidence_refs", nsr)
        self.assertIsInstance(nsr["evidence_refs"], list)

    def test_evidence_refs_resolve_to_artifact_keys(self):
        """Every evidence_refs entry resolves to a known artifact key or commands.* key."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_refs")
        report = self._load_audit_report(result)
        known_artifact_keys = set(EXPECTED_ARTIFACT_KEYS.keys())
        for ref in report["evidence_refs"]:
            if ref.startswith("commands."):
                continue
            self.assertIn(ref, known_artifact_keys,
                          f"evidence_ref '{ref}' does not resolve to an artifact key")

    def test_finding_evidence_keys_appear_in_evidence_refs(self):
        """Each finding's evidence_keys appear in the audit report's evidence_refs."""
        self._write_reports(self._source_pass_toolkit_fail_reports())
        result = self._run_audit("output_keys")
        report = self._load_audit_report(result)
        evidence_refs_set = set(report["evidence_refs"])
        for f in report["findings"]:
            for key in f.get("evidence_keys", []):
                self.assertIn(key, evidence_refs_set,
                              f"Finding evidence_key '{key}' missing from evidence_refs in {f['domain']}")

    def test_command_evidence_refs_resolve_to_command_entries(self):
        """commands.<name> evidence refs resolve to evidence.json.commands entries."""
        import scripts.run_backstage_agent as ra

        self._write_reports(self._all_pass_reports())
        proc = unittest.mock.Mock(returncode=1, stdout="not json", stderr="parse error")

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", return_value=proc):
                output_dir = self.fake_root / "output_command_refs"
                result = ra.run_accurate_ingest_audit(
                    "Test_Module", output_dir,
                    include_benchmark_command=True,
                )

        report = self._load_audit_report(result)
        evidence = self._load_evidence(result)
        self.assertIn("commands.benchmark", report["evidence_refs"])
        self.assertIn("commands", evidence)
        self.assertIn("benchmark", evidence["commands"])

        for f in report["findings"]:
            for key in f.get("evidence_keys", []):
                if key.startswith("commands."):
                    command_name = key.split(".", 1)[1]
                    self.assertIn(command_name, evidence["commands"])


class TestBackstageAgentNumillianFixture(unittest.TestCase):
    """Step 3.4: Numillian-oriented fixture coverage for source-fidelity pass
    plus stale toolkit/publishability failure disagreement."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Numillian"
        self.module_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_reports(self, reports: dict):
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def _hash_tree(self, root: Path) -> dict:
        hashes = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(root))
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                hashes[rel] = h.hexdigest()
        return hashes

    def _numillian_disagreement_reports(self) -> dict:
        """Fixture modelling Numillian: source-fidelity passes but toolkit/publishability is stale/failing."""
        return {
            "accurate_ingest_benchmark_report.json": {
                "source_fidelity_status": "pass", "status": "complete",
                "passed": True, "degraded": False, "blocked": False,
                "module_slug": "Test_Numillian", "benchmark_version": "v1",
            },
            "toolkit_build_report.json": {
                "status": "failed", "ready_status": "pass",
                "publishable_status": "fail",
            },
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {
                "source_fidelity_status": "pass", "report_version": "v1",
            },
            "build_fidelity_report.json": {"status": "pass", "blocker_count": 0},
        }

    def test_numillian_disagreement_report_consistency(self):
        """Numillian fixture produces report_consistency finding and investigate_disagreement recommendation."""
        import scripts.run_backstage_agent as ra
        self._write_reports(self._numillian_disagreement_reports())
        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_numillian"
            result = ra.run_accurate_ingest_audit("Test_Numillian", output_dir)
        run_dir = Path(result["output_dir"])

        with open(run_dir / "audit_report.json") as f:
            report = json.load(f)
        with open(run_dir / "recommendation.json") as f:
            rec = json.load(f)

        consistency = [f for f in report["findings"] if f["domain"] == "report_consistency"]
        self.assertGreater(len(consistency), 0)
        self.assertEqual(rec["recommended_action"], "investigate_disagreement")
        self.assertEqual(result["recommended_action"], "investigate_disagreement")
        self.assertGreater(report["report_consistency_summary"]["count"], 0)
        self.assertEqual(
            report["next_step_recommendation"]["recommended_action"],
            "investigate_disagreement",
        )

    def test_numillian_fixture_no_module_mutation(self):
        """Numillian fixture files are not mutated and no new files created under module dir."""
        import scripts.run_backstage_agent as ra
        self._write_reports(self._numillian_disagreement_reports())
        before_hashes = self._hash_tree(self.module_dir)
        before_files = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            output_dir = self.fake_root / "output_numillian_safe"
            result = ra.run_accurate_ingest_audit("Test_Numillian", output_dir)

        after_hashes = self._hash_tree(self.module_dir)
        after_files = {str(p.relative_to(self.module_dir)) for p in self.module_dir.rglob("*") if p.is_file()}

        self.assertEqual(before_hashes, after_hashes, "Numillian fixture files were mutated")
        self.assertEqual(before_files, after_files, "Files were added or removed from Numillian fixture dir")


class TestBackstageAgentCommandFailureFindings(unittest.TestCase):
    """Command failure findings: nonzero exit, timeout, parse-only failure."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmpdir.name)
        self.module_dir = self.fake_root / "modules" / "Test_Module"
        self.module_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "accurate_ingest_benchmark_report.json": {"source_fidelity_status": "pass"},
            "toolkit_build_report.json": {"status": "pass"},
            "validation_report.json": {"status": "pass"},
            "source_fidelity_report.json": {"source_fidelity_status": "pass"},
            "build_fidelity_report.json": {"status": "pass"},
        }
        for name, data in reports.items():
            (self.module_dir / name).write_text(json.dumps(data))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_audit(self, command_key: str, stdout: str,
                   returncode: int = 0, stderr: str = "") -> dict:
        import scripts.run_backstage_agent as ra

        def _side(cmd, *a, **kw):
            return unittest.mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)

        flags = {}
        if command_key == "benchmark":
            flags["include_benchmark_command"] = True
        elif command_key == "publishability":
            flags["include_publishability_command"] = True

        with unittest.mock.patch.object(ra, "REPO_ROOT", self.fake_root):
            with unittest.mock.patch.object(ra.subprocess, "run", side_effect=_side):
                output_dir = Path(self.tmpdir.name) / f"out_{command_key}_{id(self)}"
                return ra.run_accurate_ingest_audit("Test_Module", output_dir, **flags)

    def _valid_benchmark_stdout(self) -> str:
        return json.dumps({
            "source_fidelity_status": "pass", "passed": True,
            "degraded": False, "blocked": False,
            "module_slug": "Test_Module", "benchmark_version": "v1",
        })

    def _valid_publishability_stdout(self) -> str:
        return json.dumps({
            "ready_status": "pass", "publishable_status": "pass",
            "source_fidelity_status": "pass", "effective_publishable_status": "pass",
            "exit_code": 0, "blocking_errors": [], "warnings": [],
            "publication_gates": {
                "semantic_audit": {"status": "pass"},
                "semantic_probes": {"status": "pass"},
            },
        })

    def _load_report(self, result: dict) -> dict:
        run_dir = Path(result["output_dir"])
        with open(run_dir / "audit_report.json") as f:
            return json.load(f)

    def test_benchmark_nonzero_exit_with_valid_json_is_blocker(self):
        """Benchmark exit_code=2 with valid JSON produces blocker finding."""
        result = self._run_audit("benchmark", self._valid_benchmark_stdout(), returncode=2)
        self.assertGreater(result["blockers"], 0)
        report = self._load_report(result)
        cmd = [f for f in report["findings"] if f["evidence_keys"] == ["commands.benchmark"]]
        self.assertEqual(len(cmd), 1)
        self.assertEqual(cmd[0]["severity"], "blocker")

    def test_publishability_nonzero_exit_with_valid_json_is_blocker(self):
        """Publishability exit_code=1 with valid JSON produces blocker finding."""
        result = self._run_audit("publishability", self._valid_publishability_stdout(), returncode=1)
        self.assertGreater(result["blockers"], 0)
        report = self._load_report(result)
        cmd = [f for f in report["findings"] if f["evidence_keys"] == ["commands.publishability"]]
        self.assertEqual(len(cmd), 1)
        self.assertEqual(cmd[0]["severity"], "blocker")

    def test_timeout_exit_minus_one_is_blocker(self):
        """Benchmark exit_code=-1 produces blocker finding."""
        import scripts.run_backstage_agent as ra

        evidence = {
            "command": "benchmark",
            "exit_code": -1,
            "stdout_parse_status": "empty",
            "stderr_preview": "command timed out",
            "parsed_summary": None,
        }
        finding = ra._build_command_findings("benchmark", evidence)
        self.assertEqual(len(finding), 1)
        self.assertEqual(finding[0]["severity"], "blocker")

    def test_parse_failure_only_is_warning(self):
        """Parse failure with exit_code=0 produces warning finding."""
        result = self._run_audit("benchmark", "invalid json", returncode=0, stderr="warn")
        self.assertEqual(result["blockers"], 0)
        self.assertGreater(result["warnings"], 0)
        report = self._load_report(result)
        cmd = [f for f in report["findings"] if f["evidence_keys"] == ["commands.benchmark"]]
        self.assertEqual(len(cmd), 1)
        self.assertEqual(cmd[0]["severity"], "warning")

    def test_successful_command_no_finding(self):
        """Successful command (exit=0, parse ok) produces no command_execution finding."""
        result = self._run_audit("benchmark", self._valid_benchmark_stdout(), returncode=0)
        report = self._load_report(result)
        cmd = [f for f in report["findings"] if f["domain"] == "command_execution"]
        self.assertEqual(len(cmd), 0)

    def test_recommendation_not_no_action_when_command_blocker(self):
        """Recommendation is not no_action when a command blocker exists."""
        result = self._run_audit("benchmark", self._valid_benchmark_stdout(), returncode=2)
        self.assertNotEqual(result["recommended_action"], "no_action")
        # Should be repair_artifacts since command blocker is non-consistency non-presence
        self.assertEqual(result["recommended_action"], "repair_artifacts")
