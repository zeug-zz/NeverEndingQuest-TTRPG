# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Provider-free tests for critical narrative repair Step 3.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in __import__("sys").path:
    __import__("sys").path.insert(0, _REPO_ROOT)

from utils.critical_narrative_repair import (
    _REQUIRED_RUN_FILES,
    _FORBIDDEN_RELATIVE_PATHS,
    _FORBIDDEN_PATH_PREFIXES,
    apply_repair_plan,
    build_builder_repair_prompt,
    load_repair_run,
    parse_builder_repair_response,
    validate_repair_plan,
    write_builder_repair_result,
)


def _make_fake_run_dir(base: Path) -> Path:
    """Create a minimal valid agent-run directory fixture."""
    run_dir = base / "fake-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "task_id": "test-001", "module_slug": "TestModule",
        "status": "evidence_collected", "fail_count": 3,
        "review_count": 1, "source_markdown_read": True,
    }))
    (run_dir / "critical_evidence.json").write_text(json.dumps({
        "critical_omissions": [
            {"name": "Kobe", "type": "missing_critical_actor", "classification": "builder_repair_recommended"},
            {"name": "skull_riddle", "type": "missing_critical_puzzle", "classification": "builder_repair_recommended"},
            {"name": "flooding_room", "type": "missing_critical_puzzle", "classification": "builder_repair_recommended"},
        ],
        "review_items": [
            {"name": "Wayne", "type": "missing_critical_actor", "classification": "alias_variant_review"},
        ],
        "fail_count": 3, "review_count": 1,
    }))
    (run_dir / "source_excerpts.json").write_text(json.dumps({
        "kobe": {"name": "Kobe", "excerpt": "Kobe appears in the trial.", "char_count": 25},
        "skull_riddle": {"name": "skull_riddle", "excerpt": "Skull riddle text.", "char_count": 18},
        "flooding_room": {"name": "flooding_room", "excerpt": "Flooding room text.", "char_count": 20},
    }))
    (run_dir / "builder_repair_brief.md").write_text(
        "# Critical Narrative Repair Brief - TestModule\n\n"
        "## Source-Lock Constraints\n\n"
        "- Kobe is the final no-win trial actor.\n"
        "## Required Repair Targets\n\n"
        "### Kobe\n- module_context.json NPC surfaces\n"
    )
    return run_dir


def _make_fake_module_dir(base: Path) -> Path:
    """Create a minimal module directory fixture with a module_context.json."""
    mod_dir = base / "TestModule"
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "module_context.json").write_text(json.dumps({
        "module_name": "TestModule",
        "npcs": {"test_npc": {"name": "TestNPC"}},
    }))
    (mod_dir / "module_plot.json").write_text(json.dumps({
        "plotTitle": "Test", "plotPoints": [
            {"id": "PP000", "title": "Existing plot point"},
        ],
    }))
    return mod_dir


def _valid_repair_plan(slug: str = "TestModule") -> Dict[str, Any]:
    """A valid repair plan fixture - preserves existing protected content."""
    return {
        "repair_plan_version": "critical_narrative_repair.v1",
        "module_slug": slug,
        "omissions_addressed": ["Kobe", "skull_riddle", "flooding_room"],
        "artifact_updates": [
            {
                "relative_path": "module_context.json",
                "operation": "patch_json_object",
                "json": {
                    "npcs": {
                        "kobe": {"name": "Kobe", "role": "Trial objective"},
                    },
                },
                "source_excerpt_keys": ["kobe"],
                "rationale": "Added Kobe NPC via patch to preserve existing npcs",
            },
            {
                "relative_path": "module_plot.json",
                "operation": "replace_json_file",
                "json": {
                    "plotTitle": "Test",
                    "plotPoints": [
                        {"id": "PP001", "title": "The First Trial - Skull Riddle"},
                    ],
                },
                "source_excerpt_keys": ["skull_riddle", "flooding_room"],
                "rationale": "Added skull_riddle and flooding_room trial plot points",
            },
        ],
    }


class TestLoadRepairRun(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_loads_valid_run(self):
        run_dir = _make_fake_run_dir(self.base)
        data = load_repair_run(run_dir)
        self.assertIsNotNone(data)
        self.assertIsNotNone(data.get("run"))
        self.assertIsNotNone(data.get("critical_evidence"))

    def test_missing_file_fails_closed(self):
        run_dir = _make_fake_run_dir(self.base)
        (run_dir / "run.json").unlink()
        self.assertIsNone(load_repair_run(run_dir))

    def test_malformed_json_fails_closed(self):
        run_dir = _make_fake_run_dir(self.base)
        (run_dir / "critical_evidence.json").write_text("not-json")
        self.assertIsNone(load_repair_run(run_dir))

    def test_empty_dir_fails_closed(self):
        d = self.base / "empty"
        d.mkdir()
        self.assertIsNone(load_repair_run(d))

    def test_missing_dir_returns_none(self):
        self.assertIsNone(load_repair_run(self.base / "nonexistent"))


class TestParseBuilderResponse(unittest.TestCase):

    def test_parses_clean_json(self):
        plan = parse_builder_repair_response(
            '{"repair_plan_version": "critical_narrative_repair.v1", "module_slug": "Test"}'
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["module_slug"], "Test")

    def test_parses_fenced_json(self):
        plan = parse_builder_repair_response(
            '```json\n{"repair_plan_version":"critical_narrative_repair.v1","module_slug":"X"}\n```'
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["module_slug"], "X")

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_builder_repair_response(""))

    def test_plain_prose_returns_none(self):
        self.assertIsNone(parse_builder_repair_response("Here is the repair plan..."))

    def test_none_returns_none(self):
        self.assertIsNone(parse_builder_repair_response(None))


class TestValidateRepairPlan(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.module_dir = _make_fake_module_dir(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_plan_passes(self):
        plan = _valid_repair_plan()
        result = validate_repair_plan(plan, self.module_dir)
        self.assertTrue(result["valid"], msg=result["errors"])

    def test_wrong_version_fails(self):
        plan = _valid_repair_plan()
        plan["repair_plan_version"] = "v0"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])

    def test_mismatched_module_slug_fails(self):
        plan = _valid_repair_plan(slug="OtherModule")
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("module_slug does not match" in e for e in result["errors"]))

    def test_missing_omission_fails(self):
        plan = _valid_repair_plan()
        plan["omissions_addressed"] = ["Kobe"]
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Required omissions" in e for e in result["errors"]))

    def test_forbidden_relative_path_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "MODULE_SUMMARY.md"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("forbidden" in e for e in result["errors"]))

    def test_path_traversal_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "../outside.json"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("traversal" in e for e in result["errors"]))

    def test_forbidden_prefix_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "data/benchmarks/foo.json"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])

    def test_non_json_relative_path_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "notes.txt"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("must target a JSON artifact" in e for e in result["errors"]))

    def test_report_file_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "validation_report.json"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])

    def test_none_json_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["json"] = None
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])

    def test_empty_rationale_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["rationale"] = ""
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])

    def test_empty_source_keys_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["source_excerpt_keys"] = []
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("source_excerpt_keys is empty" in e for e in result["errors"]))

    def test_missing_required_source_excerpt_key_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["source_excerpt_keys"] = ["kobe"]
        plan["artifact_updates"][1]["source_excerpt_keys"] = ["skull_riddle"]
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Required source excerpts" in e for e in result["errors"]))

    def test_unknown_source_excerpt_key_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["source_excerpt_keys"] = ["kobe", "invented"]
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("unknown source_excerpt_keys" in e for e in result["errors"]))

    def test_invalid_operation_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["operation"] = "delete_file"
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])


class TestApplyRepairPlan(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.module_dir = _make_fake_module_dir(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_produces_plan_without_writes(self):
        plan = _valid_repair_plan()
        result = apply_repair_plan(plan, self.module_dir, apply=False)
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(len(result["files_proposed"]), 2)
        self.assertEqual(len(result["files_written"]), 0)
        self.assertIn("next_verification_commands", result)

    def test_apply_writes_files(self):
        plan = _valid_repair_plan()
        result = apply_repair_plan(plan, self.module_dir, apply=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(result["files_written"]), 2)
        # Verify file was actually written
        ctx = json.loads((self.module_dir / "module_context.json").read_text())
        self.assertIn("kobe", ctx.get("npcs", {}))

    def test_invalid_plan_apply_fails(self):
        plan = _valid_repair_plan()
        plan["repair_plan_version"] = "v0"
        result = apply_repair_plan(plan, self.module_dir, apply=True)
        self.assertEqual(result["status"], "failed")

    def test_forbidden_path_apply_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "MODULE_SUMMARY.md"
        result = apply_repair_plan(plan, self.module_dir, apply=True)
        self.assertEqual(result["status"], "failed")

    def test_safe_write_false_fails_apply(self):
        from unittest.mock import patch

        plan = _valid_repair_plan()
        # Use patch_json_object for first update so plan validates, but
        # mock safe_write to fail on the second update (replace_json_file)
        with patch("utils.critical_narrative_repair.safe_write_json", return_value=False):
            result = apply_repair_plan(plan, self.module_dir, apply=True)
        self.assertEqual(result["status"], "failed")
        self.assertGreaterEqual(len(result["write_errors"]), 1)
        self.assertEqual(result["files_written"], [])

    def test_replace_drops_existing_npcs_fails_closed(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0] = {
            "relative_path": "module_context.json",
            "operation": "replace_json_file",
            "json": {"module_name": "TestModule", "npcs": {}},
            "source_excerpt_keys": ["kobe"],
            "rationale": "Drops existing npcs",
        }
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("npcs.test_npc" in e for e in result["errors"]),
                        f"Expected npcs.test_npc error, got: {result['errors']}")

    def test_replace_shrinks_plot_points_fails_closed(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][1] = {
            "relative_path": "module_plot.json",
            "operation": "replace_json_file",
            "json": {"plotTitle": "Test", "plotPoints": []},
            "source_excerpt_keys": ["skull_riddle", "flooding_room"],
            "rationale": "Shrinks plot points",
        }
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("shrink protected list plotPoints" in e for e in result["errors"]),
                        f"Expected plotPoints shrink error, got: {result['errors']}")

    def test_patch_json_object_passes_protected_guard(self):
        plan = _valid_repair_plan()
        # First update is already patch_json_object -- should pass
        result = validate_repair_plan(plan, self.module_dir)
        self.assertTrue(result["valid"], msg=result["errors"])

    def test_replace_preserves_all_existing_keys_passes(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0] = {
            "relative_path": "module_context.json",
            "operation": "replace_json_file",
            "json": {
                "module_name": "TestModule",
                "npcs": {"test_npc": {"name": "TestNPC"}, "kobe": {"name": "Kobe"}},
            },
            "source_excerpt_keys": ["kobe"],
            "rationale": "Preserves test_npc and adds Kobe",
        }
        result = validate_repair_plan(plan, self.module_dir)
        self.assertTrue(result["valid"], msg=result["errors"])

    def test_patch_replaces_npcs_dict_with_list_fails_closed(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["json"] = {"npcs": []}
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("protected dict npcs" in e for e in result["errors"]))

    def test_patch_shrinks_plot_points_fails_closed(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][1] = {
            "relative_path": "module_plot.json",
            "operation": "patch_json_object",
            "json": {"plotPoints": []},
            "source_excerpt_keys": ["skull_riddle", "flooding_room"],
            "rationale": "Deletes plot points by patch",
        }
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("shrink protected list plotPoints" in e for e in result["errors"]))

    def test_replace_changes_npcs_dict_to_list_fails_closed(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0] = {
            "relative_path": "module_context.json",
            "operation": "replace_json_file",
            "json": {"module_name": "TestModule", "npcs": []},
            "source_excerpt_keys": ["kobe"],
            "rationale": "Changes npcs type",
        }
        result = validate_repair_plan(plan, self.module_dir)
        self.assertFalse(result["valid"])
        self.assertTrue(any("protected dict npcs" in e for e in result["errors"]))


class TestWriteRepairResult(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.run_dir = _make_fake_run_dir(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_result_json(self):
        result = {
            "status": "dry_run_ready",
            "module_slug": "TestModule",
            "omissions_addressed": ["Kobe", "skull_riddle", "flooding_room"],
            "files_proposed": ["a.json"],
            "files_written": [],
            "validation_errors": [],
            "next_verification_commands": ["cmd"],
        }
        ok = write_builder_repair_result(self.run_dir, result)
        self.assertTrue(ok)
        rpath = self.run_dir / "builder_repair_result.json"
        self.assertTrue(rpath.exists())
        parsed = json.loads(rpath.read_text())
        self.assertEqual(parsed["status"], "dry_run_ready")

    def test_creates_dir_if_missing(self):
        new_dir = self.base / "new-run"
        result = {"status": "dry_run_ready"}
        ok = write_builder_repair_result(new_dir, result)
        self.assertTrue(ok)


class TestProviderFreeCliRun(unittest.TestCase):
    """End-to-end provider-free test via subprocess."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.run_dir = _make_fake_run_dir(self.base)
        self.module_dir = _make_fake_module_dir(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_fake_response(self, plan: Dict[str, Any]) -> Path:
        p = self.base / "fake_response.json"
        p.write_text(json.dumps(plan))
        return p

    def test_fake_response_dry_run_succeeds(self):
        plan = _valid_repair_plan()
        fake_path = self._write_fake_response(plan)

        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_critical_narrative_repair.py",
                "--run-dir", str(self.run_dir),
                "--module", "TestModule",
                "--fake-response", str(fake_path),
            ],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
        )
        self.assertIn("dry_run_ready", result.stdout)
        self.assertNotIn("ERROR", result.stderr)

    def test_missing_run_dir_fails(self):
        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_critical_narrative_repair.py",
                "--run-dir", str(self.base / "nonexistent"),
                "--module", "TestModule",
                "--fake-response", str(self.base / "none.json"),
            ],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_malformed_json_response_fails(self):
        bad = self.base / "bad.json"
        bad.write_text("not-json")
        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_critical_narrative_repair.py",
                "--run-dir", str(self.run_dir),
                "--module", "TestModule",
                "--fake-response", str(bad),
            ],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_forbidden_path_response_fails(self):
        plan = _valid_repair_plan()
        plan["artifact_updates"][0]["relative_path"] = "MODULE_SUMMARY.md"
        fake_path = self._write_fake_response(plan)
        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_critical_narrative_repair.py",
                "--run-dir", str(self.run_dir),
                "--module", "TestModule",
                "--fake-response", str(fake_path),
            ],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_no_real_provider_call(self):
        """Fake response path never triggers a provider call."""
        plan = _valid_repair_plan()
        fake_path = self._write_fake_response(plan)

        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/run_critical_narrative_repair.py",
                "--run-dir", str(self.run_dir),
                "--module", "TestModule",
                "--fake-response", str(fake_path),
            ],
            capture_output=True, text=True, timeout=30,
            cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
        )
        # Neither calling provider nor producing provider_error
        self.assertNotIn("provider_error", result.stdout.lower())

    def test_build_prompt_from_run_data(self):
        run_data = {
            "builder_repair_brief": "# Brief\n## Source-Lock\n- Kobe is the final trial actor.\n",
        }
        prompt = build_builder_repair_prompt(run_data)
        self.assertIn("Brief", prompt)
        self.assertIn("repair_plan_version", prompt)
        self.assertIn("Builder Instruction", prompt)

    def test_builder_repair_result_shape(self):
        plan = _valid_repair_plan()
        mod_dir = _make_fake_module_dir(self.base)
        result = apply_repair_plan(plan, mod_dir, apply=False)
        for key in ("status", "module_slug", "omissions_addressed",
                     "files_proposed", "files_written", "validation_errors",
                     "next_verification_commands"):
            self.assertIn(key, result, f"Missing key in result: {key}")


if __name__ == "__main__":
    unittest.main()
