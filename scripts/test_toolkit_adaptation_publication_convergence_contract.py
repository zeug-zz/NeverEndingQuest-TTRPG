# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free interface contracts for adaptation publication convergence.

This task inventories existing seams only.  It deliberately does not add a
convergence implementation, call a provider, or touch a shipped module.
"""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import audit_module_gameplay as gameplay
from scripts import audit_module_publishability as publishability
from scripts import audit_module_readiness as readiness
from utils import spatial_contract
from utils import spatial_repair
from utils.module_semantic_authority import enrich_module_semantic_authority
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    resolve_adaptation_input_route,
)
from utils.toolkit_adaptation_failure_classifier import classify_adaptation_failure
from utils.toolkit_adaptation_gate_composer import (
    GATE_MECHANICAL_CLOSURE,
    GATE_READINESS,
    GATE_REPORT_AGREEMENT,
    GATE_SCHEMA,
    GATE_SEMANTIC_AUTHORITY,
    GATE_SEMANTIC_PROBES,
    REQUIRED_GATE_DOMAINS,
    compose_adaptation_gate_result,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_report_agreement import compose_adaptation_report_agreement


REPO_ROOT = Path(__file__).resolve().parents[1]


class AdaptationPublicationConvergenceContractTest(unittest.TestCase):
    """Lock callable signatures and bounded result contracts."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"), prefix="adaptation_publication_contract_"
        )
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _module_fixture(self, slug: str = "Contract_Module") -> Path:
        module_dir = self.root / slug
        (module_dir / "areas").mkdir(parents=True)
        area = {
            "areaId": "TST001",
            "areaName": "Contract Area",
            "locations": [
                {
                    "locationId": "LOC01",
                    "name": "Moonlit Shrine",
                    "aliases": ["moonlit shrine"],
                    "npcs": [],
                }
            ],
        }
        (module_dir / "areas" / "TST001.json").write_text(
            json.dumps(area), encoding="utf-8"
        )
        (module_dir / "module_context.json").write_text(
            json.dumps({"module_name": slug, "npcs": {}}), encoding="utf-8"
        )
        (module_dir / "module_plot.json").write_text(
            json.dumps({"plotPoints": []}), encoding="utf-8"
        )
        return module_dir

    def _staging_target(self) -> tuple[dict, Path]:
        target = create_adaptation_staging_target(
            "a" * 64,
            job_id="contract-job",
            attempt_number=1,
            revision_number=10,
            module_slug="Contract_Module",
            staging_root="staging",
            repo_root=self.root,
        )
        return target, self.root / target["path"]

    def test_spatial_interfaces_and_result_contracts(self) -> None:
        self.assertEqual(
            list(inspect.signature(spatial_contract.build_linear_spatial_plan).parameters),
            ["location_ids", "start_x", "start_y"],
        )
        self.assertEqual(
            list(inspect.signature(spatial_repair.repair_module_spatial).parameters),
            ["module_dir"],
        )
        plan = spatial_contract.build_linear_spatial_plan(["A", "B"])
        self.assertEqual(set(plan), {"coordinates", "connectivity", "directions", "layout"})
        self.assertEqual(plan["connectivity"]["A"], ["B"])

        with patch.object(
            spatial_repair,
            "remediate_module",
            return_value={"processed": 1, "changed": 0, "errors": []},
        ):
            report = spatial_repair.repair_module_spatial(str(self._module_fixture()))
        self.assertEqual(report["status"], "pass")
        for key in (
            "timestamp",
            "input_location_count",
            "repaired_area_count",
            "edge_count",
            "unresolved_count",
            "details",
        ):
            self.assertIn(key, report)

    def test_semantic_authority_interface_has_provenance_and_ambiguity(self) -> None:
        module_dir = self._module_fixture()
        context = json.loads((module_dir / "module_context.json").read_text())
        plot = json.loads((module_dir / "module_plot.json").read_text())
        result = enrich_module_semantic_authority("Contract_Module", context, plot, module_dir)
        self.assertIn(result["status"], {"success", "degraded"})
        authority = result["semantic_authority"]
        self.assertEqual(
            set(("version", "module_slug", "location_aliases", "location_index", "destination_phrases", "npc_scene_authority", "diagnostics", "summary")),
            set(authority),
        )
        self.assertEqual(authority["location_aliases"]["moonlit shrine"]["location_id"], "LOC01")
        self.assertIn("sources", authority["location_aliases"]["moonlit shrine"])

    def test_readiness_gameplay_and_publishability_boundaries(self) -> None:
        self.assertEqual(
            list(inspect.signature(readiness.audit_module_readiness).parameters)[:2],
            ["module_slug", "include_gameplay_gate"],
        )
        self.assertEqual(
            list(inspect.signature(gameplay.audit_module).parameters),
            ["module_name", "strict_instructions"],
        )
        self.assertEqual(
            gameplay.classify_monster_media_outcome({"base": False, "thumb": False, "video": False}),
            "provider_disabled_missing",
        )

        with patch.object(
            readiness, "run_gate_command", side_effect=[
                {"exit_code": 1, "json": {"blocking_errors": ["missing base media"], "warnings": []}},
                {"exit_code": 0, "json": {"valid": True, "sidecar_found": True}},
                {"exit_code": 0, "json": {"summary": {"any_failed": False}}},
                {"exit_code": 1, "json": {"blocking_errors": ["continuity metadata missing"], "warnings": []}},
            ],
        ):
            ready = readiness.audit_module_readiness("Hostis_Fixture")
        self.assertEqual(ready["overall_status"], "fail")
        self.assertEqual(ready["gates"]["gameplay"]["status"], "fail")

        module_dir = self._module_fixture()
        with (
            patch.object(publishability, "audit_module_readiness", return_value={"overall_status": "pass", "fix_list": [], "gates": {}}),
            patch.object(publishability, "audit_module_semantic_authority", return_value={"status": "fail", "blocking_errors": ["ambiguous watchers crown"], "warnings": []}),
            patch.object(publishability, "run_module_semantic_probes", return_value={"status": "pass", "blocking_errors": [], "warnings": []}),
        ):
            report = publishability.audit_module_publishability("Contract_Module", module_path=str(module_dir))
        self.assertEqual(report["ready_status"], "pass")
        self.assertEqual(report["publishable_status"], "fail")
        self.assertIn("ambiguous watchers crown", report["blocking_errors"])

    def test_adaptation_gate_and_report_agreement_require_fresh_identity(self) -> None:
        target, module_dir = self._staging_target()
        reports = {
            domain: {"status": "pass"} for domain in REQUIRED_GATE_DOMAINS
        }
        reports[GATE_REPORT_AGREEMENT] = {"status": "pass", "playable_publication_status": "pass"}
        result = compose_adaptation_gate_result(
            reports, staging_target=target, module_dir=module_dir, repo_root=self.root
        )
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["python_authoritative"])
        self.assertFalse(result["publication"]["attempted"])
        self.assertEqual(result["provenance"]["revision_number"], 10)

        agreement = compose_adaptation_report_agreement(
            {}, expected_attempt_id=target["attempt_id"], expected_source_hash=target["source_hash"], expected_revision_number=10, require_publication=True
        )
        self.assertEqual(agreement["status"], "blocked")
        self.assertIn("attempt_report_invalid", agreement["blockers"])

    def test_hostis_failure_classes_remain_concrete_and_fail_closed(self) -> None:
        cases = [
            ("mechanical", "continuity metadata missing"),
            ("mechanical", "gameplay exit 1: missing base monster media assets"),
            ("semantic", "ambiguous destination: watchers crown"),
            ("publication", "report agreement blocked by readiness"),
        ]
        for failure_class, message in cases:
            result = classify_adaptation_failure(
                {"failure_class": failure_class, "message": message, "code": "hostis_fixture"},
                attempt_metadata={"attempt_id": "hostis", "revision_number": 10, "max_revisions": 2},
            )
            self.assertTrue(result["blocked"])
            self.assertFalse(result["publication_allowed"])
            self.assertEqual(result["attempt_id"], "hostis")
            self.assertEqual(result["revision_number"], 10)

    def test_legacy_route_and_reports_do_not_gain_convergence_metadata(self) -> None:
        decision = resolve_adaptation_input_route(
            {"build_mode": "legacy_modulebuilder", "source_text": "fixture"},
            enabled_override=False,
        )
        self.assertNotEqual(decision.get("reported_route"), BUILD_MODE_LLM_ADAPTATION)
        self.assertFalse(decision.get("adaptation_artifacts_required"))

        legacy = publishability.audit_module_publishability
        self.assertNotIn("convergence", inspect.signature(legacy).parameters)
        self.assertNotIn("adaptation_convergence", {"ready_status", "publishable_status"})


if __name__ == "__main__":
    unittest.main()
