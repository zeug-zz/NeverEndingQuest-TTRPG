#!/usr/bin/env python3
"""Tests for layered module publishability audit."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parent / "audit_module_publishability.py"
SPEC = importlib.util.spec_from_file_location(
    "audit_module_publishability", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
publishability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publishability)


class TestAuditModulePublishability(unittest.TestCase):
    def test_publishable_pass_requires_all_layers(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={"overall_status": "pass", "fix_list": [], "gates": {}},
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertEqual(report["ready_status"], "pass")
        self.assertEqual(report["publishable_status"], "pass")
        self.assertEqual(report["exit_code"], 0)

    def test_ready_can_pass_while_publishable_fails(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={"overall_status": "pass", "fix_list": [], "gates": {}},
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "fail",
                    "blocking_errors": ["semantic issue"],
                    "warnings": [],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertEqual(report["ready_status"], "pass")
        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("semantic issue", report["blocking_errors"])
        self.assertIn("semantic_publishability_blocking", report["remediation_categories"])
        self.assertNotIn("mixed_media_semantic_blocking", report["remediation_categories"])
        self.assertEqual(report["exit_code"], 1)

    def test_readiness_failure_forces_publishable_failure(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": ["fix ready"],
                    "gates": {},
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertEqual(report["ready_status"], "fail")
        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("readiness_gate_failed", " ".join(report["blocking_errors"]))
        self.assertIn("fix ready", report["fix_list"])

    def test_toolkit_source_is_forwarded_to_readiness(self):
        captured = {}

        def _fake_readiness(module_slug, source="watcher", **_kwargs):
            captured["source"] = source
            return {"overall_status": "pass", "fix_list": [], "gates": {}}

        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                side_effect=_fake_readiness,
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability(
                "example_module",
                source="toolkit",
            )

        self.assertEqual(captured.get("source"), "toolkit")
        self.assertEqual(report.get("source"), "toolkit")

    def test_degraded_semantic_audit_without_blocking_errors_does_not_fail_publishability(
        self,
    ):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={"overall_status": "pass", "fix_list": [], "gates": {}},
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["npc_scene_authority has no visible locations"],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertEqual(report["ready_status"], "pass")
        self.assertEqual(report["publishable_status"], "pass")
        self.assertEqual(report["exit_code"], 0)
        self.assertNotIn(
            "semantic_publication_audit_nonpass",
            " ".join(report.get("blocking_errors", [])),
        )

    def test_degraded_semantic_probes_without_blocking_errors_does_not_fail_publishability(
        self,
    ):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={"overall_status": "pass", "fix_list": [], "gates": {}},
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["handoff_probe_fixture_missing"],
                },
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertEqual(report["ready_status"], "pass")
        self.assertEqual(report["publishable_status"], "pass")
        self.assertEqual(report["exit_code"], 0)
        self.assertNotIn(
            "semantic_probe_harness_nonpass",
            " ".join(report.get("blocking_errors", [])),
        )

    def test_remediation_categories_classifies_warning_only_degraded(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={"overall_status": "pass", "fix_list": [], "gates": {}},
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["npc_scene_authority has no visible locations"],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["handoff_probe_fixture_missing"],
                },
            ),
        ):
            report = publishability.audit_module_publishability("example_module")

        self.assertIn("remediation_categories", report)
        cats = report["remediation_categories"]
        self.assertIn("semantic_warning_only", cats)
        self.assertIn("semantic_tooling_debt", cats)

    def test_toolkit_media_policy_passthrough_drives_media_remediation_categories(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": [],
                    "gates": {"sidecar": {"reason": "pass"}},
                    "toolkit_media_policy": {
                        "structural_media_debt_count": 2,
                        "structural_media_debt_slugs": ["ogre", "goblin"],
                    },
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability(
                "example_module", source="toolkit"
            )

        self.assertIn("structured_monster_media_missing", report["remediation_categories"])
        self.assertIn(
            "toolkit_manual_media_generation_required", report["remediation_categories"]
        )
        self.assertEqual(
            report.get("toolkit_media_policy", {}).get("structural_media_debt_count"),
            2,
        )

    def test_mixed_media_and_semantic_blockers_are_classified(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": [],
                    "gates": {"sidecar": {"reason": "pass"}},
                    "toolkit_media_policy": {
                        "structural_media_debt_count": 1,
                        "structural_media_debt_slugs": ["ogre"],
                    },
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "fail",
                    "blocking_errors": ["travel_unresolved_destination_phrase: crucible hall"],
                    "warnings": [],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability(
                "example_module", source="toolkit"
            )

        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("structured_monster_media_missing", report["remediation_categories"])
        self.assertIn("semantic_publishability_blocking", report["remediation_categories"])
        self.assertIn("mixed_media_semantic_blocking", report["remediation_categories"])

    def test_shared_static_fallback_does_not_override_module_local_media_debt(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": ["Add media: modules/example_module/media/monsters/ogre.jpg"],
                    "gates": {"gameplay": {"reason": "missing_base_media_files"}},
                    "toolkit_media_policy": {
                        "structural_media_debt_count": 1,
                        "structural_media_debt_slugs": ["ogre"],
                        "fallback_hits": ["web/static/media/monsters/ogre.jpg"],
                    },
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability(
                "example_module", source="toolkit"
            )

        self.assertEqual(report["ready_status"], "fail")
        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("readiness_gate_failed", " ".join(report["blocking_errors"]))
        self.assertIn("structured_monster_media_missing", report["remediation_categories"])

    def test_scene_entity_modeling_candidate_for_media_plus_semantic_warnings(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": [],
                    "gates": {"sidecar": {"reason": "pass"}},
                    "toolkit_media_policy": {
                        "structural_media_debt_count": 1,
                        "structural_media_debt_slugs": ["illusory_beast"],
                    },
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["npc_scene_authority has no visible locations"],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": ["handoff_probe_fixture_missing"],
                },
            ),
        ):
            report = publishability.audit_module_publishability(
                "example_module", source="toolkit"
            )

        self.assertIn("structured_monster_media_missing", report["remediation_categories"])
        self.assertIn("semantic_warning_only", report["remediation_categories"])
        self.assertIn("scene_entity_modeling_candidate", report["remediation_categories"])
        self.assertNotIn("mixed_media_semantic_blocking", report["remediation_categories"])

    def test_normalized_shortform_semantic_context_does_not_create_semantic_blocker(self):
        with (
            patch.object(
                publishability,
                "audit_module_readiness",
                return_value={
                    "overall_status": "fail",
                    "fix_list": [],
                    "gates": {"sidecar": {"reason": "pass"}},
                    "toolkit_media_policy": {
                        "structural_media_debt_count": 1,
                        "structural_media_debt_slugs": ["oathbound_shade"],
                    },
                },
            ),
            patch.object(
                publishability,
                "audit_module_semantic_authority",
                return_value={
                    "status": "degraded",
                    "blocking_errors": [],
                    "warnings": [
                        "normalized short-form destination: oath chamber -> silent oath chamber"
                    ],
                    "normalized_shortform_destination_phrases": [
                        {
                            "phrase": "oath chamber",
                            "anchor_phrase": "silent oath chamber",
                            "location_id": "H03",
                        }
                    ],
                },
            ),
            patch.object(
                publishability,
                "run_module_semantic_probes",
                return_value={"status": "pass", "blocking_errors": [], "warnings": []},
            ),
        ):
            report = publishability.audit_module_publishability(
                "Murder_at_the_Drowning_Lass", source="toolkit"
            )

        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("structured_monster_media_missing", report["remediation_categories"])
        self.assertIn("semantic_warning_only", report["remediation_categories"])
        self.assertNotIn("semantic_publishability_blocking", report["remediation_categories"])
        self.assertNotIn("mixed_media_semantic_blocking", report["remediation_categories"])


class TestAuditPublishabilitySourceFidelity(unittest.TestCase):
    """Source-fidelity dimension tests for audit_module_publishability."""

    def setUp(self):
        self.base_readiness = {"overall_status": "pass", "fix_list": [], "gates": {}}
        self.base_authority = {"status": "pass", "blocking_errors": [], "warnings": []}
        self.base_probes = {"status": "pass", "blocking_errors": [], "warnings": []}

    def test_source_fidelity_status_in_output(self):
        with (
            patch.object(publishability, "audit_module_readiness", return_value=self.base_readiness),
            patch.object(publishability, "audit_module_semantic_authority", return_value=self.base_authority),
            patch.object(publishability, "run_module_semantic_probes", return_value=self.base_probes),
            patch.object(publishability, "_load_source_fidelity_status",
                         return_value={"source_fidelity_status": "blocked", "category_results": []}),
        ):
            report = publishability.audit_module_publishability("example_module")
        self.assertIn("source_fidelity_status", report)
        self.assertIn("effective_publishable_status", report)
        self.assertIn("source_fidelity_categories", report)

    def test_blocked_fidelity_surfaces_blockers(self):
        with (
            patch.object(publishability, "audit_module_readiness", return_value=self.base_readiness),
            patch.object(publishability, "audit_module_semantic_authority", return_value=self.base_authority),
            patch.object(publishability, "run_module_semantic_probes", return_value=self.base_probes),
            patch.object(publishability, "_load_source_fidelity_status",
                         return_value={"source_fidelity_status": "blocked", "category_results": []}),
        ):
            report = publishability.audit_module_publishability("example_module")
        self.assertEqual(report["source_fidelity_status"], "blocked")
        self.assertIn("blocked", report["effective_publishable_status"])
        self.assertGreater(len(report["blocking_errors"]), 0)

    def test_unknown_fidelity_does_not_block(self):
        with (
            patch.object(publishability, "audit_module_readiness", return_value=self.base_readiness),
            patch.object(publishability, "audit_module_semantic_authority", return_value=self.base_authority),
            patch.object(publishability, "run_module_semantic_probes", return_value=self.base_probes),
            patch.object(publishability, "_load_source_fidelity_status",
                         return_value={"source_fidelity_status": "unknown", "category_results": []}),
        ):
            report = publishability.audit_module_publishability("example_module")
        self.assertEqual(report["source_fidelity_status"], "unknown")
        self.assertEqual(report["effective_publishable_status"], "pass")

    def test_existing_keys_unchanged(self):
        with (
            patch.object(publishability, "audit_module_readiness", return_value=self.base_readiness),
            patch.object(publishability, "audit_module_semantic_authority", return_value=self.base_authority),
            patch.object(publishability, "run_module_semantic_probes", return_value=self.base_probes),
            patch.object(publishability, "_load_source_fidelity_status",
                         return_value={"source_fidelity_status": "pass", "category_results": []}),
        ):
            report = publishability.audit_module_publishability("example_module")
        self.assertIn("ready_status", report)
        self.assertIn("publishable_status", report)
        self.assertIn("blocking_errors", report)
        self.assertIn("fix_list", report)
        self.assertIn("warnings", report)
        self.assertIn("remediation_categories", report)

    def test_category_results_surfaced(self):
        categories = [
            {"category": "npc_preservation", "status": "degraded", "score": 0.87},
            {"category": "location_preservation", "status": "pass", "score": 1.0},
        ]
        with (
            patch.object(publishability, "audit_module_readiness", return_value=self.base_readiness),
            patch.object(publishability, "audit_module_semantic_authority", return_value=self.base_authority),
            patch.object(publishability, "run_module_semantic_probes", return_value=self.base_probes),
            patch.object(publishability, "_load_source_fidelity_status",
                         return_value={"source_fidelity_status": "degraded", "category_results": categories}),
        ):
            report = publishability.audit_module_publishability("example_module")
        self.assertEqual(len(report["source_fidelity_categories"]), 2)
        self.assertEqual(report["source_fidelity_categories"][0]["category"], "npc_preservation")


class TestSourceFidelityFilePrecedence(unittest.TestCase):
    """Tests for _load_source_fidelity_status file-based precedence."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _write_json(self, name: str, data: dict):
        path = self.tmpdir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_final_report_wins_over_benchmark(self):
        self._write_json("accurate_ingest_benchmark_report.json", {
            "source_fidelity_status": "pass",
            "category_results": [{"category": "benchmark", "score": 1.0}],
        })
        self._write_json("source_fidelity_report.json", {
            "report_version": "source_fidelity_report.v1",
            "module_slug": "test_module",
            "source_fidelity_status": "blocked",
            "categories": [{"category": "npc_preservation", "status": "blocked"}],
        })
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "blocked",
                         "Final report should win over benchmark")
        self.assertEqual(len(result["category_results"]), 1)

    def test_benchmark_fallback_when_no_final_report(self):
        self._write_json("accurate_ingest_benchmark_report.json", {
            "source_fidelity_status": "degraded",
            "category_results": [{"category": "location_preservation", "score": 0.85}],
        })
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "degraded")

    def test_unknown_when_no_reports(self):
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "unknown")
        self.assertEqual(result["category_results"], [])

    def test_final_report_category_mapping(self):
        self._write_json("source_fidelity_report.json", {
            "source_fidelity_status": "pass",
            "categories": [{"category": "npc_preservation", "status": "pass"}],
        })
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "pass")
        self.assertEqual(len(result["category_results"]), 1)

    def test_invalid_final_report_returns_unknown(self):
        """Invalid source_fidelity_report.json must return unknown, not fall through to benchmark."""
        self._write_json("accurate_ingest_benchmark_report.json", {
            "source_fidelity_status": "pass",
            "category_results": [{"category": "benchmark", "score": 1.0}],
        })
        path = self.tmpdir / "source_fidelity_report.json"
        path.write_text("not valid json", encoding="utf-8")
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "unknown",
                         "Invalid final report must return unknown, not stale benchmark")

    def test_corrupt_json_final_report_returns_unknown(self):
        """Corrupt JSON in source_fidelity_report.json must return unknown."""
        path = self.tmpdir / "source_fidelity_report.json"
        path.write_text("{invalid: true, missing: quotes}", encoding="utf-8")
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "unknown")

    def test_non_dict_final_report_returns_unknown(self):
        """source_fidelity_report.json containing non-dict json must return unknown."""
        self._write_json("source_fidelity_report.json", ["pass", "degraded"])
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "unknown")

    def test_build_source_fidelity_report_artifact(self):
        pub_report = {
            "source_fidelity_status": "degraded",
            "source_fidelity_categories": [
                {"category": "npc_preservation", "status": "degraded", "score": 0.87},
            ],
        }
        artifact = publishability._build_source_fidelity_report_artifact(
            module_slug="test_module",
            module_path=self.tmpdir,
            publishability_report=pub_report,
        )
        self.assertEqual(artifact["report_version"], "source_fidelity_report.v1")
        self.assertEqual(artifact["module_slug"], "test_module")
        self.assertEqual(artifact["source_fidelity_status"], "degraded")
        self.assertEqual(len(artifact["categories"]), 1)
        self.assertEqual(artifact["categories"][0]["category"], "npc_preservation")

    def test_module_summary_does_not_override_blocked_fidelity(self):
        """MODULE_SUMMARY.md must not override blocked source-fidelity status."""
        self._write_json("source_fidelity_report.json", {
            "report_version": "source_fidelity_report.v1",
            "module_slug": "test_module",
            "source_fidelity_status": "blocked",
            "categories": [],
        })
        path = self.tmpdir / "MODULE_SUMMARY.md"
        path.write_text("# This module summary should not override source fidelity", encoding="utf-8")
        result = publishability._load_source_fidelity_status(self.tmpdir)
        self.assertEqual(result["source_fidelity_status"], "blocked",
                         "MODULE_SUMMARY.md must not override blocked source fidelity")


if __name__ == "__main__":
    unittest.main()
