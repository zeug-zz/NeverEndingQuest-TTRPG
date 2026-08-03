# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit Final Reconciliation
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

from utils.toolkit_final_reconciliation import (
    BRIEF_VERSION,
    REPORT_VERSION,
    DEFAULT_EDITABLE_SURFACES,
    _build_generated_module_summary,
    _resolve_source_excerpts,
    build_final_reconciliation_brief,
    build_final_reconciliation_report,
    persist_final_reconciliation_brief,
    should_persist_final_reconciliation_brief,
    persist_final_reconciliation_report,
    load_final_reconciliation_report,
    is_final_reconciliation_accepted,
)


class TestBuildFinalReconciliationBrief(unittest.TestCase):
    """Test build_final_reconciliation_brief contracts."""

    def _editorial_classification(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                    "raw": {},
                }
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "Required location 'Trigger' not found in module",
            "report_paths": {"report_path": "/tmp/report.json"},
        }

    def test_brief_shape_for_editorial_classification(self):
        """Brief includes version, job_id, module_name, module_dir, and trigger."""
        classification = self._editorial_classification()
        brief = build_final_reconciliation_brief(
            classification,
            job_id="job-001",
            module_name="TestModule",
            module_dir=Path("/tmp/test"),
        )

        self.assertEqual(brief["version"], BRIEF_VERSION)
        self.assertEqual(brief["job_id"], "job-001")
        self.assertEqual(brief["module_name"], "TestModule")
        self.assertEqual(brief["module_dir"], "/tmp/test")
        self.assertEqual(brief["trigger"], "editorial_blockers_present")
        self.assertEqual(brief["classification_status"], "editorial")
        self.assertEqual(len(brief["editorial_blockers"]), 1)
        self.assertEqual(brief["fatal_blockers"], [])
        self.assertEqual(brief["warnings"], [])
        self.assertEqual(
            brief["original_refusal_reason"],
            "Required location 'Trigger' not found in module"
        )
        self.assertEqual(brief["report_paths"]["report_path"], "/tmp/report.json")

    def test_brief_includes_editable_surfaces_and_instructions(self):
        """Brief uses default editable surfaces and instructions."""
        classification = self._editorial_classification()
        brief = build_final_reconciliation_brief(classification)

        self.assertIn("editable_surfaces", brief)
        self.assertIsInstance(brief["editable_surfaces"], list)
        self.assertGreater(len(brief["editable_surfaces"]), 0)
        # Narrowed canonical surfaces: no runtime-only or source/middle entries
        self.assertNotIn("module_plot.json", brief["editable_surfaces"])
        self.assertNotIn("areas/", brief["editable_surfaces"])
        self.assertNotIn("monsters/", brief["editable_surfaces"])
        self.assertIn("module_context_BU.json", brief["editable_surfaces"])
        self.assertIn("module_plot_BU.json", brief["editable_surfaces"])
        self.assertIn("areas/*_BU.json", brief["editable_surfaces"])
        self.assertIn("map_*.json", brief["editable_surfaces"])

        self.assertIn("instructions", brief)
        self.assertIsInstance(brief["instructions"], str)
        self.assertGreater(len(brief["instructions"]), 0)

    def test_brief_does_not_mutate_classification_input(self):
        """Brief building does not mutate classifier output input dict."""
        classification = self._editorial_classification()
        original = json.loads(json.dumps(classification))

        build_final_reconciliation_brief(classification, job_id="test")

        self.assertEqual(classification, original)

    def test_brief_no_blockers_triggers_no_editorial(self):
        """Brief with no editorial blockers has trigger 'no_editorial_blockers'."""
        classification = {
            "status": "no_blockers",
            "fatal_blockers": [],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        brief = build_final_reconciliation_brief(classification)
        self.assertEqual(brief["trigger"], "no_editorial_blockers")
        self.assertEqual(brief["classification_status"], "no_blockers")

    def test_brief_source_excerpts_and_module_summary_defaults(self):
        """Brief has empty source_excerpts and generated_module_summary by default."""
        classification = self._editorial_classification()
        brief = build_final_reconciliation_brief(classification)

        self.assertEqual(brief["source_excerpts"], [])
        self.assertEqual(brief["generated_module_summary"], {})


class TestDefaultEditableSurfaces(unittest.TestCase):
    """Verify DEFAULT_EDITABLE_SURFACES match the canonical contract.

    The preferred canonical surfaces are:
      module_context.json, module_context_BU.json, module_plot_BU.json,
      areas/*_BU.json, map_*.json.

    Runtime-only files, broad directory prefixes, and source/middle
    pipeline artifacts must remain absent from defaults.
    """

    CANONICAL_SURFACES = [
        "module_context.json",
        "module_context_BU.json",
        "module_plot_BU.json",
        "areas/*_BU.json",
        "map_*.json",
    ]

    def test_default_surfaces_match_canonical_list(self):
        """DEFAULT_EDITABLE_SURFACES is exactly the canonical list."""
        self.assertEqual(DEFAULT_EDITABLE_SURFACES, self.CANONICAL_SURFACES)

    def test_default_surfaces_excludes_runtime_module_plot(self):
        """module_plot.json (runtime-only) is NOT in defaults."""
        self.assertNotIn("module_plot.json", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_excludes_broad_areas_prefix(self):
        """areas/ (broad directory prefix) is NOT in defaults."""
        self.assertNotIn("areas/", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_excludes_monsters_prefix(self):
        """monsters/ is NOT in defaults."""
        self.assertNotIn("monsters/", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_includes_module_context_bu(self):
        """module_context_BU.json (canonical backup) IS in defaults."""
        self.assertIn("module_context_BU.json", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_includes_module_plot_bu(self):
        """module_plot_BU.json (canonical backup) IS in defaults."""
        self.assertIn("module_plot_BU.json", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_includes_areas_bu_glob(self):
        """areas/*_BU.json (canonical backup glob) IS in defaults."""
        self.assertIn("areas/*_BU.json", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_includes_map_glob(self):
        """map_*.json (static authored maps) IS in defaults."""
        self.assertIn("map_*.json", DEFAULT_EDITABLE_SURFACES)

    def test_default_surfaces_are_all_strings(self):
        """Every surface entry is a non-empty string."""
        for surface in DEFAULT_EDITABLE_SURFACES:
            self.assertIsInstance(surface, str)
            self.assertTrue(surface)

    def test_default_surfaces_are_ascii_only(self):
        """All surface entries are ASCII-safe."""
        combined = "".join(DEFAULT_EDITABLE_SURFACES)
        combined.encode("ascii")


class TestEvidenceEnrichment(unittest.TestCase):
    """Test source_excerpts and generated_module_summary enrichment."""

    def _editorial_classification(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'Trigger' not found in module",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                    "raw": {},
                },
                {
                    "type": "editorial",
                    "message": "Required npc 'Wayne' not found in module",
                    "category": "npc",
                    "source_atom_id": "ent_wayne",
                    "raw": {},
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 2,
            "original_refusal_reason": "",
            "report_paths": {},
        }

    def _source_graph(self):
        return {
            "atoms": [
                {"id": "loc_trigger", "type": "location", "name": "Trigger",
                 "summary": "The ancient Trigger chamber beneath the ruin"},
                {"id": "ent_wayne", "type": "npc", "name": "Wayne",
                 "summary": "Wayne the gatekeeper of the hidden city"},
                {"id": "loc_unreferenced", "type": "location", "name": "Unreferenced",
                 "summary": "A location not referenced by any blocker"},
            ],
        }

    def _classification_no_source_atom_ids(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Some editorial issue",
                    "category": "general",
                    "source_atom_id": None,
                    "raw": {},
                },
                {
                    "type": "editorial",
                    "message": "Another issue",
                    "category": "general",
                    "raw": {},
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 2,
            "original_refusal_reason": "",
            "report_paths": {},
        }

    def test_resolve_source_excerpts_with_matching_atoms(self):
        """Resolved excerpts contain enriched data from source graph atoms."""
        classification = self._editorial_classification()
        sg = self._source_graph()
        excerpts = _resolve_source_excerpts(classification, sg)

        self.assertEqual(len(excerpts), 2)

        # Order matches blocker order (loc_trigger first)
        self.assertEqual(excerpts[0]["source_atom_id"], "loc_trigger")
        self.assertEqual(excerpts[0]["atom_type"], "location")
        self.assertEqual(excerpts[0]["name"], "Trigger")
        self.assertIn("Trigger chamber", excerpts[0]["excerpt"])

        self.assertEqual(excerpts[1]["source_atom_id"], "ent_wayne")
        self.assertEqual(excerpts[1]["atom_type"], "npc")
        self.assertEqual(excerpts[1]["name"], "Wayne")

    def test_resolve_source_excerpts_no_source_graph(self):
        """No source_graph returns empty list."""
        classification = self._editorial_classification()
        excerpts = _resolve_source_excerpts(classification, None)
        self.assertEqual(excerpts, [])

    def test_resolve_source_excerpts_empty_source_graph(self):
        """Empty source graph dict returns empty list."""
        classification = self._editorial_classification()
        excerpts = _resolve_source_excerpts(classification, {})
        self.assertEqual(excerpts, [])

    def test_resolve_source_excerpts_no_atoms_in_graph(self):
        """Source graph with no atoms returns empty list."""
        classification = self._editorial_classification()
        excerpts = _resolve_source_excerpts(classification, {"atoms": []})
        self.assertEqual(excerpts, [])

    def test_resolve_source_excerpts_no_source_atom_ids(self):
        """Blockers without source_atom_id produce no excerpts."""
        classification = self._classification_no_source_atom_ids()
        sg = self._source_graph()
        excerpts = _resolve_source_excerpts(classification, sg)
        self.assertEqual(excerpts, [])

    def test_resolve_source_excerpts_atom_id_no_match(self):
        """Non-matching source_atom_id produces no excerpt for that blocker."""
        classification = self._editorial_classification()
        sg = {"atoms": [
            {"id": "unrelated", "type": "npc", "name": "Ghost",
             "summary": "A ghostly figure"},
        ]}
        excerpts = _resolve_source_excerpts(classification, sg)
        self.assertEqual(excerpts, [])

    def test_resolve_source_excerpts_bounded_at_max(self):
        """More blockers than _MAX_EXCERPTS are bounded."""
        many_blockers = []
        many_atoms = []
        for i in range(25):
            atom_id = f"blk_{i:03d}"
            many_blockers.append({
                "type": "editorial",
                "message": f"Blocker {i}",
                "category": "general",
                "source_atom_id": atom_id,
                "raw": {},
            })
            many_atoms.append({
                "id": atom_id, "type": "npc", "name": f"Blocker_{i}",
                "summary": f"Entity number {i}",
            })
        classification = {
            "status": "editorial", "fatal_blockers": [], "editorial_blockers": many_blockers,
            "warnings": [], "can_attempt_final_reconciliation": True,
            "fatal_count": 0, "editorial_count": 25,
            "original_refusal_reason": "", "report_paths": {},
        }
        sg = {"atoms": many_atoms}
        excerpts = _resolve_source_excerpts(classification, sg)
        self.assertLessEqual(len(excerpts), 20)

    def test_generated_module_summary_no_module_dir(self):
        """No module_dir returns empty dict."""
        self.assertEqual(_build_generated_module_summary(None), {})

    def test_generated_module_summary_missing_dir(self):
        """Non-existent module_dir returns empty dict."""
        self.assertEqual(_build_generated_module_summary(Path("/nonexistent")), {})

    def test_generated_module_summary_with_real_artifacts(self):
        """Valid module dir returns counts and missing categories."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = Path(d)
            area_dir = mod_dir / "areas"
            area_dir.mkdir(parents=True)
            (area_dir / "AREA001_BU.json").write_text("{}")
            (area_dir / "AREA002_BU.json").write_text("{}")
            (area_dir / "AREA003.json").write_text("{}")
            monsters_dir = mod_dir / "monsters"
            monsters_dir.mkdir()
            (monsters_dir / "goblin.json").write_text("{}")
            (mod_dir / "module_context.json").write_text("{}")
            (mod_dir / "module_plot.json").write_text("{}")

            summary = _build_generated_module_summary(mod_dir)
            self.assertEqual(summary["area_count"], 3)
            self.assertEqual(summary["area_bu_count"], 2)
            self.assertEqual(summary["monster_count"], 1)
            self.assertTrue(summary["has_module_context"])
            self.assertTrue(summary["has_module_plot"])
            self.assertEqual(summary["missing_categories"], [])

    def test_generated_module_summary_missing_categories(self):
        """Module dir with missing artifacts reports missing categories."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = Path(d)
            area_dir = mod_dir / "areas"
            area_dir.mkdir(parents=True)
            (area_dir / "AREA001_BU.json").write_text("{}")
            (mod_dir / "module_context.json").write_text("{}")
            # No module_plot, no monsters

            summary = _build_generated_module_summary(mod_dir)
            self.assertEqual(summary["area_count"], 1)
            self.assertEqual(summary["area_bu_count"], 1)
            self.assertEqual(summary["monster_count"], 0)
            self.assertTrue(summary["has_module_context"])
            self.assertFalse(summary["has_module_plot"])
            self.assertIn("module_plot", summary["missing_categories"])
            self.assertIn("monsters", summary["missing_categories"])
            self.assertNotIn("areas", summary["missing_categories"])
            self.assertNotIn("module_context", summary["missing_categories"])

    def test_brief_with_source_graph_has_excerpts(self):
        """Brief built with source_graph has enriched source_excerpts."""
        classification = self._editorial_classification()
        sg = self._source_graph()
        brief = build_final_reconciliation_brief(
            classification, job_id="j1", module_name="M1",
            source_graph=sg,
        )
        self.assertEqual(len(brief["source_excerpts"]), 2)
        self.assertEqual(brief["source_excerpts"][0]["source_atom_id"], "loc_trigger")

    def test_brief_with_module_dir_has_generated_summary(self):
        """Brief built with existing module_dir has generated_module_summary."""
        classification = self._editorial_classification()
        with tempfile.TemporaryDirectory() as d:
            mod_dir = Path(d)
            area_dir = mod_dir / "areas"
            area_dir.mkdir(parents=True)
            (area_dir / "AREA001_BU.json").write_text("{}")
            (mod_dir / "module_context.json").write_text("{}")

            brief = build_final_reconciliation_brief(
                classification, job_id="j1", module_name="M1",
                module_dir=mod_dir,
            )
            summary = brief["generated_module_summary"]
            self.assertEqual(summary["area_count"], 1)
            self.assertTrue(summary["has_module_context"])
            self.assertFalse(summary["has_module_plot"])

    def test_brief_default_empty_behavior_preserved(self):
        """Default call without source_graph or module_dir source_excerpts=[] summary={}."""
        classification = self._editorial_classification()
        brief = build_final_reconciliation_brief(
            classification, job_id="j1", module_name="M1",
        )
        self.assertEqual(brief["source_excerpts"], [])
        self.assertEqual(brief["generated_module_summary"], {})


class TestBuildFinalReconciliationReport(unittest.TestCase):
    """Test build_final_reconciliation_report contracts."""

    def test_report_no_blockers_returns_not_required(self):
        """No blockers -> status=not_required, playable candidate."""
        classification = {
            "status": "no_blockers",
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["version"], REPORT_VERSION)
        self.assertEqual(report["status"], "not_required")
        self.assertEqual(report["reconciliation_status"], "not_required")
        self.assertEqual(report["source_fidelity_effective_status"], "pass")
        self.assertTrue(report["playable_publication_candidate"])

    def test_report_editorial_without_acceptance_returns_required(self):
        """Editorial blockers without acceptance -> status=required."""
        classification = {
            "status": "editorial",
            "fatal_count": 0,
            "editorial_count": 3,
            "original_refusal_reason": "Required location 'Trigger' not found in module",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["version"], REPORT_VERSION)
        self.assertEqual(report["status"], "required")
        self.assertEqual(report["reconciliation_status"], "pending")
        self.assertEqual(report["source_fidelity_effective_status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])
        self.assertEqual(report["decisions"], [])

    def test_report_accepted_editorial_returns_accepted(self):
        """Accepted editorial reconciliation -> status=accepted, reconciled_degraded."""
        classification = {
            "status": "editorial",
            "fatal_count": 0,
            "editorial_count": 2,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        accepted = {"accepted_at": "2026-06-02", "reviewer": "operator"}
        report = build_final_reconciliation_report(classification, accepted)

        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["reconciliation_status"], "accepted")
        self.assertEqual(report["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(report["playable_publication_candidate"])
        self.assertIn("accepted_final_reconciliation", report["decisions"])

    def test_report_fatal_returns_blocked(self):
        """Fatal blockers -> status=blocked."""
        classification = {
            "status": "fatal",
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reconciliation_status"], "not_applicable")
        self.assertFalse(report["playable_publication_candidate"])

    def test_report_mixed_returns_blocked(self):
        """Mixed fatal + editorial -> status=blocked."""
        classification = {
            "status": "mixed",
            "fatal_count": 1,
            "editorial_count": 2,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])

    def test_report_unknown_returns_failed(self):
        """Unknown classification -> status=failed."""
        classification = {
            "status": "unknown",
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reconciliation_status"], "invalid_classification")
        self.assertFalse(report["playable_publication_candidate"])

    def test_report_arbitrary_status_returns_failed(self):
        """Malformed/garbled classification -> status=failed."""
        classification = {
            "status": "garbled",
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)

        self.assertEqual(report["status"], "failed")

    def test_all_artifacts_are_json_serializable(self):
        """Brief and report outputs are JSON-serializable."""
        classification = {
            "status": "editorial",
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "test",
            "report_paths": {},
        }

        brief = build_final_reconciliation_brief(classification, job_id="j1", module_name="M1")
        report = build_final_reconciliation_report(classification)

        self.assertIsInstance(json.dumps(brief), str)
        self.assertIsInstance(json.dumps(report), str)

    def test_report_fatal_overrides_accepted_reconciliation(self):
        """Even with accepted reconciliation, fatal blockers still -> blocked."""
        classification = {
            "status": "fatal",
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        accepted = {"accepted_at": "2026-06-02"}
        report = build_final_reconciliation_report(classification, accepted)

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])

    def test_brief_malformed_none_does_not_raise(self):
        """build_final_reconciliation_brief(None) returns valid brief, does not raise."""
        brief = build_final_reconciliation_brief(None, job_id="j1", module_name="M1")
        
        self.assertEqual(brief["version"], BRIEF_VERSION)
        self.assertEqual(brief["job_id"], "j1")
        self.assertEqual(brief["module_name"], "M1")
        self.assertEqual(brief["classification_status"], "unknown")
        self.assertEqual(brief["editorial_blockers"], [])
        self.assertEqual(brief["fatal_blockers"], [])
        self.assertEqual(len(brief["warnings"]), 1)
        self.assertEqual(brief["warnings"][0]["type"], "invalid_classification")
        self.assertEqual(brief["trigger"], "no_editorial_blockers")

    def test_brief_malformed_string_does_not_raise(self):
        """build_final_reconciliation_brief('bad') returns valid brief, does not raise."""
        brief = build_final_reconciliation_brief("bad")
        
        self.assertEqual(brief["version"], BRIEF_VERSION)
        self.assertEqual(brief["classification_status"], "unknown")
        self.assertEqual(len(brief["warnings"]), 1)
        self.assertEqual(brief["warnings"][0]["type"], "invalid_classification")
        self.assertEqual(brief["editorial_blockers"], [])

    def test_report_malformed_none_does_not_raise(self):
        """build_final_reconciliation_report(None) returns failed report, does not raise."""
        report = build_final_reconciliation_report(None)
        
        self.assertEqual(report["version"], REPORT_VERSION)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reconciliation_status"], "invalid_classification")
        self.assertEqual(report["source_fidelity_effective_status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])

    def test_report_malformed_string_does_not_raise(self):
        """build_final_reconciliation_report('bad') returns failed report, does not raise."""
        report = build_final_reconciliation_report("bad")
        
        self.assertEqual(report["version"], REPORT_VERSION)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["playable_publication_candidate"])

    def test_malformed_brief_and_report_are_json_serializable(self):
        """Malformed-input brief and report are JSON-serializable."""
        brief = build_final_reconciliation_brief(None)
        report = build_final_reconciliation_report(42)
        
        self.assertIsInstance(json.dumps(brief), str)
        self.assertIsInstance(json.dumps(report), str)

    def test_report_metadata_fields_are_dicts_not_none(self):
        """Report metadata fields are dicts, not None."""
        classification = {
            "status": "editorial",
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)
        
        self.assertIsInstance(report["validation_after_reconciliation"], dict)
        self.assertIsInstance(report["publishability_after_reconciliation"], dict)
        self.assertIsInstance(report["report_agreement_after_reconciliation"], dict)


class TestPersistFinalReconciliationBrief(unittest.TestCase):
    """Test persistence helpers for final reconciliation brief."""

    def _editorial_classification(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {"type": "editorial", "message": "Required location 'X' not found in module", "category": "location"}
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "Required location 'X' not found in module",
            "report_paths": {},
        }

    def test_should_persist_true_for_editorial_only(self):
        self.assertTrue(should_persist_final_reconciliation_brief(self._editorial_classification()))

    def test_should_persist_false_for_fatal(self):
        c = {**self._editorial_classification(), "status": "fatal", "fatal_count": 1, "editorial_count": 0, "can_attempt_final_reconciliation": False}
        self.assertFalse(should_persist_final_reconciliation_brief(c))

    def test_should_persist_false_for_mixed(self):
        c = {**self._editorial_classification(), "status": "mixed", "fatal_count": 1, "can_attempt_final_reconciliation": False}
        self.assertFalse(should_persist_final_reconciliation_brief(c))

    def test_should_persist_false_for_no_blockers(self):
        c = {**self._editorial_classification(), "status": "no_blockers", "editorial_count": 0, "can_attempt_final_reconciliation": False}
        self.assertFalse(should_persist_final_reconciliation_brief(c))

    def test_should_persist_false_for_malformed(self):
        self.assertFalse(should_persist_final_reconciliation_brief(None))
        self.assertFalse(should_persist_final_reconciliation_brief("bad"))

    def test_persist_writes_brief_json(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            brief = build_final_reconciliation_brief(
                self._editorial_classification(), job_id="job-1", module_name="Test"
            )
            result = persist_final_reconciliation_brief(ws, brief)

            self.assertEqual(result["status"], "written")
            self.assertTrue(result["path"].endswith("final_reconciliation_brief.json"))
            self.assertGreater(result["bytes"], 0)
            self.assertIsNone(result["error"])

            target = ws / "final_reconciliation_brief.json"
            self.assertTrue(target.exists())

    def test_persist_roundtrips_content(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            classification = self._editorial_classification()
            brief = build_final_reconciliation_brief(classification, job_id="job-2", module_name="Roundtrip")

            result = persist_final_reconciliation_brief(ws, brief)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)

            self.assertEqual(loaded["version"], BRIEF_VERSION)
            self.assertEqual(loaded["job_id"], "job-2")
            self.assertEqual(loaded["module_name"], "Roundtrip")
            self.assertEqual(loaded["classification_status"], "editorial")
            self.assertEqual(len(loaded["editorial_blockers"]), 1)
            self.assertEqual(loaded["original_refusal_reason"], "Required location 'X' not found in module")

    def test_persist_invalid_path_returns_failed(self):
        brief = build_final_reconciliation_brief(self._editorial_classification())
        result = persist_final_reconciliation_brief(Path("/nonexistent/path/deep"), brief)

        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error"])

    def test_persist_does_not_mutate_brief(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            classification = self._editorial_classification()
            brief = build_final_reconciliation_brief(classification)
            original = json.loads(json.dumps(brief))

            persist_final_reconciliation_brief(ws, brief)

            self.assertEqual(brief, original)


class TestFinalReconciliationArtifactImmutability(unittest.TestCase):
    """Prove brief generation/persistence does not mutate existing artifacts."""

    def _editorial_classification(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {"type": "editorial", "message": "Required location 'X' not found in module", "category": "location"}
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "test",
            "report_paths": {},
        }

    def _build_workspace(self, base: Path) -> Path:
        """Create a workspace with representative artifact files and return the ws dir."""
        ws = base / "workspace"
        ws.mkdir()

        (ws / "source_graph.json").write_text(json.dumps({"atoms": [{"name": "A"}]}))
        (ws / "source_manifest.json").write_text(json.dumps({"headings": ["H1"]}))
        (ws / "normalized_packet.json").write_text(json.dumps({"locations": []}))
        (ws / "builder_blueprint.json").write_text(json.dumps({"areas": []}))

        audit_dir = ws / "backstage_audit"
        audit_dir.mkdir()
        (audit_dir / "run.json").write_text(json.dumps({"task_id": "t1"}))
        (audit_dir / "evidence.json").write_text(json.dumps({"findings": []}))
        (audit_dir / "audit_report.json").write_text(json.dumps({"blockers": 0}))
        (audit_dir / "recommendation.json").write_text(json.dumps({"action": "none"}))

        return ws

    def _file_hashes(self, ws: Path):
        """Return {relpath: md5_hex} for all files under workspace."""
        import hashlib
        hashes = {}
        for fpath in sorted(ws.rglob("*")):
            if fpath.is_file():
                rel = str(fpath.relative_to(ws))
                hashes[rel] = hashlib.md5(fpath.read_bytes()).hexdigest()
        return hashes

    def test_build_brief_does_not_mutate_workspace_files(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = self._build_workspace(base)

            pre_hashes = self._file_hashes(ws)

            brief = build_final_reconciliation_brief(self._editorial_classification())

            post_hashes = self._file_hashes(ws)
            self.assertEqual(pre_hashes, post_hashes, "build_brief must not mutate workspace files")

    def test_persist_brief_only_creates_brief_json(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = self._build_workspace(base)

            pre_hashes = self._file_hashes(ws)

            classification = self._editorial_classification()
            brief = build_final_reconciliation_brief(classification, job_id="j1", module_name="M1")
            persist_final_reconciliation_brief(ws, brief)

            post_hashes = self._file_hashes(ws)

            brief_path = "final_reconciliation_brief.json"
            self.assertIn(brief_path, post_hashes)

            # Remove the brief from post-hashes and compare rest
            del post_hashes[brief_path]
            self.assertEqual(pre_hashes, post_hashes,
                            "persist must only create final_reconciliation_brief.json; all other files unchanged")

    def test_build_brief_does_not_mutate_classification_input(self):
        classification = self._editorial_classification()
        original = json.loads(json.dumps(classification))

        build_final_reconciliation_brief(classification)

        self.assertEqual(classification, original)

    def test_source_graph_bytes_unchanged_after_brief_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = self._build_workspace(base)

            sg_path = ws / "source_graph.json"
            original = sg_path.read_bytes()

            classification = self._editorial_classification()
            brief = build_final_reconciliation_brief(classification)
            persist_final_reconciliation_brief(ws, brief)

            self.assertEqual(sg_path.read_bytes(), original)
            (ws / "final_reconciliation_brief.json").unlink()

            sm_path = ws / "source_manifest.json"
            original_sm = sm_path.read_bytes()
            self.assertEqual(sm_path.read_bytes(), original_sm)

    def test_files_outside_workspace_not_listed(self):
        """Brief target is workspace-relative; no stray files outside workspace."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = self._build_workspace(base)
            pre_count = len(list(base.rglob("*")))

            classification = self._editorial_classification()
            brief = build_final_reconciliation_brief(classification)
            persist_final_reconciliation_brief(ws, brief)

            post_count = len(list(base.rglob("*")))
            self.assertEqual(post_count, pre_count + 1,
                             "Only one new file (final_reconciliation_brief.json) should appear")


class TestPersistFinalReconciliationReport(unittest.TestCase):
    """Test persistence for final reconciliation report."""

    def _classification(self, status="editorial", fatal=0, editorial=1):
        return {
            "status": status,
            "fatal_count": fatal,
            "editorial_count": editorial,
            "original_refusal_reason": "test",
            "report_paths": {},
        }

    def test_writes_report_json(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("no_blockers", 0, 0))
            result = persist_final_reconciliation_report(ws, report)

            self.assertEqual(result["status"], "written")
            self.assertTrue(result["path"].endswith("final_reconciliation_report.json"))
            self.assertGreater(result["bytes"], 0)
            self.assertIsNone(result["error"])

            self.assertTrue((ws / "final_reconciliation_report.json").exists())

    def test_roundtrips_not_required_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("no_blockers", 0, 0))

            result = persist_final_reconciliation_report(ws, report)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["status"], "not_required")
            self.assertEqual(loaded["reconciliation_status"], "not_required")
            self.assertEqual(loaded["source_fidelity_effective_status"], "pass")
            self.assertTrue(loaded["playable_publication_candidate"])

    def test_roundtrips_required_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("editorial", 0, 3))

            result = persist_final_reconciliation_report(ws, report)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["status"], "required")
            self.assertEqual(loaded["reconciliation_status"], "pending")
            self.assertEqual(loaded["source_fidelity_effective_status"], "blocked")
            self.assertFalse(loaded["playable_publication_candidate"])

    def test_roundtrips_accepted_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(
                self._classification("editorial", 0, 2),
                accepted_reconciliation={"accepted_at": "2026-06-02"},
            )

            result = persist_final_reconciliation_report(ws, report)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["status"], "accepted")
            self.assertEqual(loaded["reconciliation_status"], "accepted")
            self.assertEqual(loaded["source_fidelity_effective_status"], "reconciled_degraded")
            self.assertTrue(loaded["playable_publication_candidate"])
            self.assertIn("accepted_final_reconciliation", loaded["decisions"])

    def test_roundtrips_blocked_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("fatal", 1, 0))

            result = persist_final_reconciliation_report(ws, report)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["status"], "blocked")
            self.assertFalse(loaded["playable_publication_candidate"])

    def test_roundtrips_failed_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("unknown", 0, 0))

            result = persist_final_reconciliation_report(ws, report)
            self.assertEqual(result["status"], "written")

            with open(result["path"], encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["status"], "failed")
            self.assertEqual(loaded["reconciliation_status"], "invalid_classification")

    def test_invalid_path_returns_failed(self):
        report = build_final_reconciliation_report(self._classification("no_blockers", 0, 0))
        result = persist_final_reconciliation_report(Path("/nonexistent/path/deep"), report)

        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error"])

    def test_persist_does_not_mutate_report(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(self._classification("editorial", 0, 1))
            original = json.loads(json.dumps(report))

            persist_final_reconciliation_report(ws, report)

            self.assertEqual(report, original)


class TestStep35ContractCompleteness(unittest.TestCase):
    """Step 3.5 coverage: stable key contracts and per-file immutability."""

    BRIEF_KEYS = [
        "version", "job_id", "module_name", "module_dir", "trigger",
        "classification_status", "editorial_blockers", "fatal_blockers", "warnings",
        "original_refusal_reason", "report_paths", "source_excerpts",
        "generated_module_summary", "editable_surfaces", "instructions",
    ]

    REPORT_KEYS = [
        "version", "status", "reconciliation_status",
        "source_fidelity_effective_status", "playable_publication_candidate",
        "decisions", "validation_after_reconciliation",
        "publishability_after_reconciliation",
        "report_agreement_after_reconciliation", "notes",
    ]

    ARTIFACT_FILES = [
        "source_graph.json",
        "source_manifest.json",
        "normalized_packet.json",
        "builder_blueprint.json",
        "backstage_audit/run.json",
        "backstage_audit/evidence.json",
        "backstage_audit/audit_report.json",
        "backstage_audit/recommendation.json",
    ]

    def test_brief_contains_all_required_keys(self):
        classification = {
            "status": "editorial", "fatal_blockers": [], "editorial_blockers": [
                {"type": "editorial", "message": "M", "category": "location"}
            ],
            "warnings": [], "can_attempt_final_reconciliation": True,
            "fatal_count": 0, "editorial_count": 1,
            "original_refusal_reason": "", "report_paths": {},
        }
        brief = build_final_reconciliation_brief(classification, job_id="j", module_name="M")
        for key in self.BRIEF_KEYS:
            self.assertIn(key, brief, f"Brief must contain key: {key}")

    def test_report_contains_all_required_keys(self):
        classification = {
            "status": "editorial", "fatal_count": 0, "editorial_count": 1,
            "original_refusal_reason": "", "report_paths": {},
        }
        report = build_final_reconciliation_report(classification)
        for key in self.REPORT_KEYS:
            self.assertIn(key, report, f"Report must contain key: {key}")

    def test_all_file_names_explicitly_unchanged_after_build_brief(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = base / "ws"
            ws.mkdir()
            for f in self.ARTIFACT_FILES:
                p = ws / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"file": f}))

            pre = {f: hashlib.md5((ws / f).read_bytes()).hexdigest() for f in self.ARTIFACT_FILES}

            classification = {
                "status": "editorial", "fatal_blockers": [], "editorial_blockers": [
                    {"type": "editorial", "message": "X", "category": "location"}
                ],
                "warnings": [], "can_attempt_final_reconciliation": True,
                "fatal_count": 0, "editorial_count": 1,
                "original_refusal_reason": "", "report_paths": {},
            }
            build_final_reconciliation_brief(classification)

            for f in self.ARTIFACT_FILES:
                current = hashlib.md5((ws / f).read_bytes()).hexdigest()
                self.assertEqual(pre[f], current, f"File {f} changed after build_brief")

    def test_all_file_names_explicitly_unchanged_after_persist_brief(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ws = base / "ws"
            ws.mkdir()
            for f in self.ARTIFACT_FILES:
                p = ws / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"file": f}))

            pre = {f: hashlib.md5((ws / f).read_bytes()).hexdigest() for f in self.ARTIFACT_FILES}

            classification = {
                "status": "editorial", "fatal_blockers": [], "editorial_blockers": [
                    {"type": "editorial", "message": "X", "category": "location"}
                ],
                "warnings": [], "can_attempt_final_reconciliation": True,
                "fatal_count": 0, "editorial_count": 1,
                "original_refusal_reason": "", "report_paths": {},
            }
            brief = build_final_reconciliation_brief(classification)
            persist_final_reconciliation_brief(ws, brief)

            for f in self.ARTIFACT_FILES:
                current = hashlib.md5((ws / f).read_bytes()).hexdigest()
                self.assertEqual(pre[f], current, f"File {f} changed after persist_brief")

    def test_accepted_fixture_produces_reconciled_degraded(self):
        classification = {
            "status": "editorial", "fatal_count": 0, "editorial_count": 1,
            "original_refusal_reason": "", "report_paths": {},
        }
        report = build_final_reconciliation_report(
            classification, accepted_reconciliation={"accepted_at": "2026-06-02"}
        )
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(report["playable_publication_candidate"])
        self.assertIn("accepted_final_reconciliation", report["decisions"])

    def test_fatal_with_accepted_fixture_remains_blocked(self):
        classification = {
            "status": "fatal", "fatal_count": 1, "editorial_count": 0,
            "original_refusal_reason": "", "report_paths": {},
        }
        report = build_final_reconciliation_report(
            classification, accepted_reconciliation={"accepted_at": "2026-06-02"}
        )
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])


class TestAcceptedReconciliationHelpers(unittest.TestCase):
    """Test load_final_reconciliation_report and is_final_reconciliation_accepted."""

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            self.assertIsNone(load_final_reconciliation_report(ws))

    def test_load_non_dict_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "final_reconciliation_report.json").write_text('"not a dict"')
            self.assertIsNone(load_final_reconciliation_report(ws))

    def test_load_valid_report_returns_dict(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = {"status": "accepted", "reconciliation_status": "accepted"}
            (ws / "final_reconciliation_report.json").write_text(json.dumps(report))
            loaded = load_final_reconciliation_report(ws)
            self.assertEqual(loaded, report)

    def test_is_accepted_true_for_accepted(self):
        report = {
            "status": "accepted",
            "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": True,
        }
        self.assertTrue(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_effective_pass(self):
        """Accepted with effective_fidelity='pass' must be rejected."""
        report = {
            "status": "accepted", "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "pass",
            "playable_publication_candidate": True,
        }
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_effective_blocked(self):
        """Accepted with effective_fidelity='blocked' must be rejected."""
        report = {
            "status": "accepted", "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "blocked",
            "playable_publication_candidate": True,
        }
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_missing_effective(self):
        """Accepted without source_fidelity_effective_status must be rejected."""
        report = {
            "status": "accepted", "reconciliation_status": "accepted",
            "playable_publication_candidate": True,
        }
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_playable_false(self):
        """Accepted with playable_publication_candidate=False must be rejected."""
        report = {
            "status": "accepted", "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": False,
        }
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_for_required(self):
        report = {
            "status": "required",
            "reconciliation_status": "pending",
            "source_fidelity_effective_status": "blocked",
            "playable_publication_candidate": False,
        }
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_for_blocked(self):
        report = {"status": "blocked"}
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_for_failed(self):
        report = {"status": "failed"}
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_for_not_required(self):
        report = {"status": "not_required"}
        self.assertFalse(is_final_reconciliation_accepted(report))

    def test_is_accepted_false_for_none(self):
        self.assertFalse(is_final_reconciliation_accepted(None))

    def test_is_accepted_false_for_non_dict(self):
        self.assertFalse(is_final_reconciliation_accepted("bad"))


if __name__ == "__main__":
    unittest.main()
