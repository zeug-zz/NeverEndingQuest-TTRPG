# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit Adaptation Gate Composer
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free contract tests for task 4.2. The tests use isolated staging
targets and patch only deterministic gate runners where a full schema-valid
module fixture is not required.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_gate_composer import (
    GATE_MECHANICAL_CLOSURE,
    GATE_READINESS,
    GATE_REPORT_AGREEMENT,
    GATE_SCHEMA,
    GATE_SEMANTIC_AUTHORITY,
    GATE_SEMANTIC_PROBES,
    REQUIRED_GATE_DOMAINS,
    _run_semantic_authority_gate,
    _run_continuity_gate,
    _run_semantic_probe_gate,
    _normalize_gate_result,
    _parse_command_json,
    compose_adaptation_gate_result,
    run_adaptation_gate_composer,
)
from scripts.audit_module_readiness import (
    _extract_gameplay_payload,
    _maybe_relax_toolkit_media_only_gameplay_gate,
)
from utils.toolkit_adaptation_staging import (
    create_adaptation_staging_target,
)
from utils.toolkit_adaptation_publication_convergence import (
    apply_validated_adaptation_finalization_operation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_gate_contract"
SOURCE_HASH = "b" * 64


def _passing_reports():
    """Return deterministic pass reports for all six composition domains."""
    return {
        GATE_SCHEMA: {"status": "pass", "exit_code": 0},
        GATE_READINESS: {"status": "pass"},
        GATE_MECHANICAL_CLOSURE: {"status": "pass"},
        GATE_SEMANTIC_AUTHORITY: {"status": "pass"},
        GATE_SEMANTIC_PROBES: {"status": "pass"},
        GATE_REPORT_AGREEMENT: {
            "status": "pass",
            "playable_publication_status": "pass",
        },
    }


class AdaptationGateComposerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _target(self, job_id: str = "gate-fixture"):
        return create_adaptation_staging_target(
            SOURCE_HASH,
            job_id=job_id,
            attempt_number=1,
            revision_number=0,
            module_slug="Gate_Fixture",
            staging_root="tmp/toolkit_adaptation_gate_contract/staging",
            repo_root=REPO_ROOT,
        )

    def _patch_runners(self):
        return (
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_schema_gate"],
                ),
                "_run_schema_gate",
                return_value={"status": "pass", "exit_code": 0},
            ),
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_gameplay_gate"],
                ),
                "_run_gameplay_gate",
                return_value={"status": "pass", "blocking_errors": []},
            ),
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_continuity_gate"],
                ),
                "_run_continuity_gate",
                return_value={"status": "pass", "blocking_errors": []},
            ),
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_mechanical_closure_gate"],
                ),
                "_run_mechanical_closure_gate",
                return_value={"status": "pass"},
            ),
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_semantic_authority_gate"],
                ),
                "_run_semantic_authority_gate",
                return_value={"status": "pass"},
            ),
            patch.object(
                __import__(
                    "utils.toolkit_adaptation_gate_composer",
                    fromlist=["_run_semantic_probe_gate"],
                ),
                "_run_semantic_probe_gate",
                return_value={"status": "pass"},
            ),
        )

    def test_composes_all_required_gate_domains(self) -> None:
        target = self._target()
        result = compose_adaptation_gate_result(
            _passing_reports(),
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
            attempt_metadata={
                "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
            },
        )

        self.assertEqual(set(result["gates"]), set(REQUIRED_GATE_DOMAINS))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["playable_status"], "pass")
        self.assertTrue(result["candidate_eligible"])
        self.assertEqual(result["provenance"]["stage"], "adaptation_gate_composition")
        self.assertEqual(
            result["provenance"]["source_path"],
            "scripts/fixtures/toolkit_adaptation_catalogue.md",
        )

        # Passing deterministic gates makes a candidate eligible for the next
        # Python transaction, but this task never performs publication.
        self.assertTrue(result["python_authoritative"])
        self.assertFalse(result["publication"]["attempted"])
        self.assertFalse(result["publication"]["allowed"])

    def test_model_pass_claim_cannot_override_gate_failure(self) -> None:
        target = self._target("model-pass-cannot-override")
        reports = _passing_reports()
        reports[GATE_SEMANTIC_AUTHORITY] = {
            "status": "failed",
            "blocking_errors": ["ambiguous destination remains unresolved"],
        }

        result = compose_adaptation_gate_result(
            reports,
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
            llm_result={
                "status": "pass",
                "publication_allowed": True,
                "arbitrary_target": "modules/Keep_of_Doom",
            },
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["playable_status"], "blocked")
        self.assertFalse(result["candidate_eligible"])
        self.assertFalse(result["model_advisory"]["used_for_gate"])
        self.assertTrue(result["model_advisory"]["ignored_for_publication"])
        self.assertFalse(result["publication"]["allowed"])
        self.assertTrue(
            any("semantic_authority" in blocker for blocker in result["blockers"])
        )

    def test_current_convergence_identity_is_required_for_gate_status(self) -> None:
        target = self._target("convergence-identity")
        current = {
            "status": "ready",
            "attempt_id": target["attempt_id"],
            "attempt_number": target["attempt_number"],
            "revision_number": target["revision_number"],
            "source_hash": target["source_hash"],
            "report_path": str(REPO_ROOT / target["path"] / "adaptation_convergence_report.json"),
        }
        with patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_schema_gate"]),
            "_run_schema_gate",
            return_value={"status": "pass", "exit_code": 0},
        ), patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_gameplay_gate"]),
            "_run_gameplay_gate",
            return_value={"status": "pass"},
        ), patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_continuity_gate"]),
            "_run_continuity_gate",
            return_value={"status": "pass"},
        ), patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_mechanical_closure_gate"]),
            "_run_mechanical_closure_gate",
            return_value={"status": "pass"},
        ), patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_semantic_authority_gate"]),
            "_run_semantic_authority_gate",
            return_value={"status": "pass"},
        ), patch.object(
            __import__("utils.toolkit_adaptation_gate_composer", fromlist=["_run_semantic_probe_gate"]),
            "_run_semantic_probe_gate",
            return_value={"status": "pass"},
        ):
            result = run_adaptation_gate_composer(
                target,
                module_dir=REPO_ROOT / target["path"],
                repo_root=REPO_ROOT,
                convergence_result=current,
            )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["publishable_status"], "pass")
        self.assertEqual(result["convergence_report"]["revision_number"], target["revision_number"])

        stale = dict(current)
        stale["revision_number"] = target["revision_number"] + 1
        blocked = compose_adaptation_gate_result(
            _passing_reports(),
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
            convergence_result=stale,
        )
        self.assertEqual(blocked["playable_status"], "blocked")
        self.assertEqual(blocked["publishable_status"], "blocked")
        self.assertIn("adaptation_convergence_report_stale_or_mismatched", blocked["blockers"])

    def test_recomputed_semantic_gate_preserves_validated_alias_and_rejects_stale_operation(self) -> None:
        target = self._target("semantic-reapply")
        module_dir = REPO_ROOT / target["path"]
        authority = {
            "location_aliases": {
                "watchers crown": {"candidate_location_ids": ["K02", "K05"]},
            },
            "destination_phrases": {
                "watchers crown": {"status": "ambiguous", "candidate_location_ids": ["K02", "K05"]},
            },
            "diagnostics": {"ambiguous_destination_phrases": [{"phrase": "watchers crown"}], "unresolved_destination_phrases": []},
            "summary": {"ambiguous_destination_count": 1},
            "source_evidence": [{"source": "source_manifest", "source_ref": "source_manifest"}],
            "adaptation_provenance": {"mode": "llm_adaptation"},
        }
        identity = {key: target[key] for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")}
        # The semantic gate consumes the post-application staging artifact. The
        # fixture must therefore materialize the accepted operation through the
        # same Python-owned staging helper used by production convergence.
        authority["attempt"] = identity
        (module_dir / "module_context.json").write_text(json.dumps({"moduleName": "Gate_Fixture", "semantic_authority": authority}))
        (module_dir / "module_plot.json").write_text(json.dumps({"plotPoints": []}))
        operation = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": "resolve_destination_alias",
            "identity": identity,
            "target": {"location_id": "K02", "phrase": "watchers crown"},
            "source_references": ["source_manifest"],
            "confidence": 0.95,
            "replacement": "K02",
            "topology": {"location_ids": ["K02", "K05"], "edges": []},
        }
        applied = apply_validated_adaptation_finalization_operation(
            module_dir, operation, identity
        )
        self.assertEqual(applied["status"], "applied")
        enrichment = {"status": "degraded", "module_context": {"semantic_authority": deepcopy(authority)}, "changed": False, "warnings": [], "errors": []}
        with patch("utils.toolkit_adaptation_gate_composer.enrich_module_semantic_authority", return_value=enrichment), patch("utils.toolkit_adaptation_gate_composer.audit_module_semantic_authority", return_value={"blocking_errors": [], "warnings": []}):
            result = _run_semantic_authority_gate("Gate_Fixture", module_dir, {"status": "ready", **identity, "accepted_operation": operation})
        self.assertEqual(result["status"], "pass")
        updated = json.loads((module_dir / "module_context.json").read_text())
        self.assertEqual(updated["semantic_authority"]["destination_phrases"]["watchers crown"]["location_id"], "K02")
        self.assertEqual(updated["semantic_authority"]["diagnostics"]["ambiguous_destination_phrases"], [])

        (module_dir / "module_context.json").write_text(json.dumps({"moduleName": "Gate_Fixture", "semantic_authority": authority}))
        stale_operation = deepcopy(operation)
        stale_operation["identity"] = dict(identity, revision_number=identity["revision_number"] + 1)
        with patch("utils.toolkit_adaptation_gate_composer.enrich_module_semantic_authority", return_value=enrichment), patch("utils.toolkit_adaptation_gate_composer.audit_module_semantic_authority", return_value={"blocking_errors": [], "warnings": []}):
            stale = _run_semantic_authority_gate("Gate_Fixture", module_dir, {"status": "ready", **identity, "accepted_operation": stale_operation})
        self.assertEqual(stale["status"], "blocked")
        self.assertTrue(any("operation_rejected" in item or "identity" in item for item in stale["blockers"]))
        unchanged = json.loads((module_dir / "module_context.json").read_text())
        self.assertEqual(unchanged["semantic_authority"]["destination_phrases"]["watchers crown"]["status"], "ambiguous")

    def test_warning_only_continuity_and_semantic_reports_remain_passing(self) -> None:
        target = self._target("warning-only-gates")
        module_dir = REPO_ROOT / target["path"]
        with patch(
            "utils.toolkit_adaptation_gate_composer.audit_module_continuity",
            return_value={"status": "degraded", "exit_code": 0, "blocking_errors": [], "warnings": ["cross_module_refs is empty"]},
        ):
            continuity = _run_continuity_gate(module_dir)
        self.assertEqual(continuity["status"], "pass")
        self.assertEqual(continuity["warnings"], ["cross_module_refs is empty"])

    def test_deterministic_noop_convergence_does_not_require_operation(self) -> None:
        target = self._target("deterministic-noop")
        module_dir = REPO_ROOT / target["path"]
        (module_dir / "module_context.json").write_text(
            json.dumps({"moduleName": "Gate_Fixture"}), encoding="utf-8"
        )
        (module_dir / "module_plot.json").write_text(
            json.dumps({"plotPoints": []}), encoding="utf-8"
        )
        identity = {
            key: target[key]
            for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")
        }
        convergence = {
            "status": "ready",
            "reason_code": "no_repairable_blocker",
            **identity,
            "accepted_operation": None,
        }
        enrichment = {
            "status": "degraded",
            "module_context": {"moduleName": "Gate_Fixture"},
            "changed": False,
            "warnings": [],
            "errors": [],
        }
        with patch(
            "utils.toolkit_adaptation_gate_composer.enrich_module_semantic_authority",
            return_value=enrichment,
        ), patch(
            "utils.toolkit_adaptation_gate_composer.audit_module_semantic_authority",
            return_value={"blocking_errors": [], "warnings": []},
        ):
            result = _run_semantic_authority_gate(
                "Gate_Fixture", module_dir, convergence
            )
        self.assertEqual(result["status"], "pass")
        self.assertIn(
            "adaptation_convergence_deterministic_noop_accepted",
            result["warnings"],
        )

        (module_dir / "module_context.json").write_text(json.dumps({"semantic_authority": {"source_evidence": []}}))
        (module_dir / "module_plot.json").write_text(json.dumps({"plotPoints": []}))
        with patch(
            "utils.toolkit_adaptation_gate_composer.enrich_module_semantic_authority",
            return_value={"status": "degraded", "module_context": {"semantic_authority": {"source_evidence": []}}, "changed": False, "warnings": ["semantic_authority_normalized_shortform_destination_phrases=5"], "errors": []},
        ), patch(
            "utils.toolkit_adaptation_gate_composer.audit_module_semantic_authority",
            return_value={"blocking_errors": [], "warnings": []},
        ):
            semantic = _run_semantic_authority_gate("Gate_Fixture", module_dir)
        self.assertEqual(semantic["status"], "pass")
        self.assertIn("semantic_authority_normalized_shortform_destination_phrases=5", semantic["warnings"])

        with patch(
            "utils.toolkit_adaptation_gate_composer.audit_module_continuity",
            return_value={"status": "fail", "exit_code": 1, "blocking_errors": ["missing required key"], "warnings": []},
        ):
            self.assertEqual(_run_continuity_gate(module_dir)["status"], "fail")
        with patch(
            "utils.toolkit_adaptation_gate_composer.enrich_module_semantic_authority",
            return_value={"status": "success", "module_context": {"semantic_authority": {}}, "changed": False, "warnings": [], "errors": []},
        ), patch(
            "utils.toolkit_adaptation_gate_composer.audit_module_semantic_authority",
            return_value={"blocking_errors": ["ambiguous destination"], "warnings": []},
        ):
            self.assertEqual(_run_semantic_authority_gate("Gate_Fixture", module_dir)["status"], "blocked")

    def test_warning_only_semantic_probes_pass_but_true_probe_failures_block(self) -> None:
        target = self._target("probe-warning-policy")
        module_dir = REPO_ROOT / target["path"]
        warning_report = {
            "status": "degraded",
            "exit_code": 0,
            "blocking_errors": [],
            "errors": [],
            "warnings": ["handoff_probe_fixture_missing", "ambiguous expected target"],
        }
        with patch(
            "utils.toolkit_adaptation_gate_composer.run_module_semantic_probes",
            return_value=warning_report,
        ):
            result = _run_semantic_probe_gate(module_dir)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["warnings"], warning_report["warnings"])

        for failure in (
            {"status": "degraded", "exit_code": 0, "blocking_errors": ["unsafe destination"], "errors": [], "warnings": []},
            {"status": "failed", "exit_code": 1, "blocking_errors": [], "errors": [], "warnings": []},
            {"status": "unknown", "exit_code": 0, "blocking_errors": [], "errors": [], "warnings": []},
        ):
            with patch(
                "utils.toolkit_adaptation_gate_composer.run_module_semantic_probes",
                return_value=failure,
            ):
                self.assertEqual(_run_semantic_probe_gate(module_dir)["status"], "blocked")

    def test_mixed_failures_remain_visible_and_fail_closed(self) -> None:
        target = self._target("mixed-failures")
        reports = _passing_reports()
        reports[GATE_SCHEMA] = {
            "status": "failed",
            "errors": ["schema validation failed"],
        }
        reports[GATE_SEMANTIC_PROBES] = {
            "status": "blocked",
            "blocking_errors": ["travel destination is ambiguous"],
        }

        result = compose_adaptation_gate_result(
            reports,
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("schema" in item for item in result["errors"]))
        self.assertTrue(any("semantic_probes" in item for item in result["blockers"]))
        self.assertIsNotNone(result["failure_classification"])

    def test_staged_runner_propagates_metadata_and_does_not_publish(self) -> None:
        target = self._target("staged-runner")
        module_dir = REPO_ROOT / target["path"]
        protected_paths = [
            REPO_ROOT / "modules" / "world_registry.json",
            REPO_ROOT / "modules" / "campaign.json",
        ]
        before = {
            path: path.read_bytes() for path in protected_paths if path.exists()
        }

        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=module_dir,
                repo_root=REPO_ROOT,
                source_fidelity_status="blocked",
                attempt_metadata={"source_format": "markdown"},
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["playable_status"], "pass")
        self.assertEqual(
            result["gates"][GATE_REPORT_AGREEMENT]["playable_publication_status"],
            "pass",
        )
        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        self.assertEqual(
            result["source_fidelity_report"]["evidence"]["source_fidelity_status"],
            "blocked",
        )
        self.assertEqual(result["provenance"]["attempt_id"], target["attempt_id"])
        self.assertEqual(result["staging_target"]["stage_id"], target["stage_id"])
        self.assertEqual(
            before,
            {path: path.read_bytes() for path in before},
        )
        self.assertFalse(result["publication"]["attempted"])

    def test_missing_optional_legacy_reports_are_explicit_and_not_silent(self) -> None:
        target = self._target("missing-legacy-reports")
        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=REPO_ROOT / target["path"],
                repo_root=REPO_ROOT,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        report_gate = result["gates"][GATE_REPORT_AGREEMENT]
        self.assertTrue(
            any(
                "optional_legacy_report_missing" in warning
                for warning in report_gate["warnings"]
            )
        )
        self.assertFalse(
            any(
                "source_fidelity_status_unresolved" in blocker
                for blocker in report_gate["blockers"]
            )
        )

    def test_media_only_gameplay_debt_is_manual_handoff_at_adaptation_boundary(self) -> None:
        """Structural media debt passes while raw gameplay failure stays visible."""
        target = self._target("media-only-handoff")
        media_slugs = ["goblin", "orc"]
        blocking_errors = [
            f"Missing base media for: {slug} (from structural monster media finding)"
            for slug in media_slugs
        ]
        gameplay_report = {
            "status": "fail",
            "reason": "gameplay_blocking_errors",
            "exit_code": 1,
            "blocking_error_count": len(blocking_errors),
            "warning_count": 0,
            "raw": {
                "exit_code": 1,
                "stdout": "bounded gameplay audit output",
                "stderr": "",
                "json": {
                    "blocking_errors": blocking_errors,
                    "warnings": [],
                    "monster_media_findings": [
                        {
                            "slug": slug,
                            "confidence": "structural",
                            "outcome": "provider_disabled_missing",
                        }
                        for slug in media_slugs
                    ],
                },
            },
        }

        composer = __import__(
            "utils.toolkit_adaptation_gate_composer", fromlist=["_run_gameplay_gate"]
        )
        normalized_gameplay = {}
        original_normalize = composer._normalize_gate_result

        def capture_gameplay_normalization(domain, report):
            normalized = original_normalize(domain, report)
            if domain == "gameplay":
                normalized_gameplay.update(normalized)
            return normalized

        patches = self._patch_runners()
        with patches[0], patch.object(
            composer,
            "_run_gameplay_gate",
            return_value=gameplay_report,
        ), patch.object(
            composer,
            "_normalize_gate_result",
            side_effect=capture_gameplay_normalization,
        ), patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=REPO_ROOT / target["path"],
                repo_root=REPO_ROOT,
                source_fidelity_status="pass",
            )

        gameplay_gate = normalized_gameplay
        self.assertEqual(gameplay_gate["effective_status"], "pass")
        self.assertFalse(gameplay_gate["blocking"])
        self.assertTrue(gameplay_gate["manual_handoff_only"])
        self.assertEqual(
            gameplay_gate["reason"],
            "toolkit_structural_media_handoff_only",
        )
        self.assertEqual(gameplay_gate["structural_media_debt_count"], 2)
        self.assertEqual(gameplay_gate["structural_media_debt_slugs"], media_slugs)
        self.assertEqual(gameplay_gate["exit_code"], 1)
        self.assertEqual(result["gates"][GATE_READINESS]["effective_status"], "pass")
        self.assertEqual(result["status"], "pass")

    def test_negative_gameplay_shapes_stay_blocked_at_relaxation_boundary(self) -> None:
        """Only the exact media-only shape may cross the normalization exception."""
        media_error = "Missing base media for: goblin (from structural monster media finding)"
        media_finding = {
            "slug": "goblin",
            "confidence": "structural",
            "outcome": "provider_disabled_missing",
        }
        cases = {
            "mixed_media_and_missing_monster_json": {
                "blocking_errors": [media_error, "Missing monster JSON for: basilisk"],
                "monster_media_findings": [media_finding],
            },
            "missing_monster_json_with_media_debt": {
                "blocking_errors": [media_error, "monster JSON missing: basilisk"],
                "monster_media_findings": [media_finding],
            },
            "unknown_media_outcome": {
                "blocking_errors": [media_error],
                "monster_media_findings": [dict(media_finding, outcome="unknown")],
            },
            "disallowed_media_outcome": {
                "blocking_errors": [media_error],
                "monster_media_findings": [dict(media_finding, outcome="generated")],
            },
        }

        for name, payload in cases.items():
            with self.subTest(name=name):
                report = {
                    "status": "fail",
                    "reason": "gameplay_blocking_errors",
                    "exit_code": 1,
                    "raw": {"exit_code": 1, "json": payload},
                }
                extracted = _extract_gameplay_payload(report["raw"])
                relaxed = _maybe_relax_toolkit_media_only_gameplay_gate(
                    report, extracted, "toolkit"
                )
                normalized = _normalize_gate_result("gameplay", relaxed)

                self.assertIs(relaxed, report)
                self.assertEqual(normalized["effective_status"], "blocked")
                self.assertTrue(normalized["blocking"])
                self.assertNotIn("manual_handoff_only", normalized)
                self.assertEqual(normalized["exit_code"], 1)

    def test_malformed_or_wrong_handoff_markers_cannot_pass_normalization(self) -> None:
        """Malformed payloads and incomplete handoff markers remain fail-closed."""
        cases = {
            "missing_gameplay_payload": {
                "status": "fail",
                "exit_code": 1,
                "raw": {"exit_code": 1, "json": None},
            },
            "malformed_gameplay_payload": {
                "status": "fail",
                "exit_code": 1,
                "raw": {"exit_code": 1, "json": ["not", "an", "object"]},
            },
            "wrong_reason_marker": {
                "status": "pass",
                "manual_handoff_only": True,
                "reason": "not_a_toolkit_media_handoff",
                "structural_media_debt_count": 1,
                "structural_media_debt_slugs": ["goblin"],
                "exit_code": 1,
            },
            "invalid_debt_marker": {
                "status": "pass",
                "manual_handoff_only": True,
                "reason": "toolkit_structural_media_handoff_only",
                "structural_media_debt_count": 2,
                "structural_media_debt_slugs": ["goblin"],
                "exit_code": 1,
            },
        }

        for name, report in cases.items():
            with self.subTest(name=name):
                normalized = _normalize_gate_result("gameplay", report)
                self.assertEqual(normalized["effective_status"], "blocked")
                self.assertTrue(normalized["blocking"])
                self.assertNotIn("manual_handoff_only", normalized)
                if report.get("exit_code") is not None:
                    self.assertEqual(normalized["exit_code"], report["exit_code"])

    def test_negative_gameplay_failures_preserve_bounded_revision_classification(self) -> None:
        """Blocked gameplay failures retain the existing classification envelope."""
        target = self._target("negative-revision-policy")
        reports = _passing_reports()
        reports[GATE_READINESS] = {
            "status": "fail",
            "reason": "gameplay_blocking_errors",
            "blocking_errors": ["gameplay:missing monster JSON"],
            "exit_code": 1,
        }

        result = compose_adaptation_gate_result(
            reports,
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
        )
        classification = result["failure_classification"]

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["playable_status"], "blocked")
        self.assertIsNotNone(classification)
        self.assertEqual(classification["classification_status"], "blocked")
        self.assertTrue(classification["blocked"])
        self.assertIn("revision_budget", classification)
        self.assertEqual(
            classification["revision_budget"]["decision"],
            "explicit_opt_in_required",
        )
        self.assertFalse(classification["revision_eligible"])

    def test_malformed_authoritative_report_cannot_pass(self) -> None:
        target = self._target("malformed-authoritative")
        module_dir = REPO_ROOT / target["path"]
        (module_dir / "toolkit_build_report.json").write_text(
            "{malformed", encoding="utf-8"
        )
        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=module_dir,
                repo_root=REPO_ROOT,
                source_fidelity_status="pass",
            )

        self.assertEqual(result["status"], "blocked")
        self.assertTrue(
            any(
                "toolkit_build_report_malformed" in blocker
                for blocker in result["gates"][GATE_REPORT_AGREEMENT]["blockers"]
            )
        )

    def test_module_builder_context_report_does_not_override_canonical_schema_gate(self) -> None:
        """The builder context summary is not the schema-validator result."""
        target = self._target("builder-context-report")
        module_dir = REPO_ROOT / target["path"]
        (module_dir / "validation_report.json").write_text(
            json.dumps(
                {
                    "validation_date": "2026-08-17T18:42:01",
                    "issues": [],
                    "context_summary": {"areas": 4, "npcs": 1},
                }
            ),
            encoding="utf-8",
        )
        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=module_dir,
                repo_root=REPO_ROOT,
                source_fidelity_status="pass",
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["gates"][GATE_SCHEMA]["effective_status"], "pass")
        self.assertTrue(
            any(
                "non_authoritative_validation_context_report_ignored" in warning
                for warning in result["gates"][GATE_REPORT_AGREEMENT]["warnings"]
            )
        )

    def test_unknown_or_failed_authoritative_validation_report_stays_fail_closed(self) -> None:
        target = self._target("authoritative-report-contract")
        module_dir = REPO_ROOT / target["path"]
        patches = self._patch_runners()
        for payload in (
            {"issues": []},
            {"status": "failed", "errors": ["schema failure"]},
            {"status": "pass", "report_freshness": {"state": "unknown"}},
        ):
            with self.subTest(payload=payload):
                (module_dir / "validation_report.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                    result = run_adaptation_gate_composer(
                        target,
                        module_dir=module_dir,
                        repo_root=REPO_ROOT,
                        source_fidelity_status="pass",
                    )
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(
                    any(
                        token in blocker
                        for blocker in result["gates"][GATE_REPORT_AGREEMENT]["blockers"]
                        for token in (
                            "authoritative_validation_report_not_passing",
                            "stale_report:validation:unknown",
                        )
                    )
                )

    def test_non_staged_module_path_is_rejected_before_gate_use(self) -> None:
        target = self._target("non-staged-path")
        result = run_adaptation_gate_composer(
            target,
            module_dir=REPO_ROOT / "modules" / "Keep_of_Doom",
            repo_root=REPO_ROOT,
            llm_result={"status": "pass"},
        )

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["publication"]["attempted"])
        self.assertFalse(result["model_advisory"]["used_for_gate"])

    def test_command_json_parser_handles_mixed_validator_output(self) -> None:
        parsed = _parse_command_json(
            "validator notice\n{\"status\": \"pass\", \"errors\": []}\n"
        )

        self.assertEqual(parsed, {"status": "pass", "errors": []})

    def test_composer_is_provider_free_and_uses_no_registry_writer(self) -> None:
        import utils.toolkit_adaptation_gate_composer as composer

        source = inspect.getsource(composer)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("ModuleStitcher", source)
        self.assertNotIn("world_registry", source)
        self.assertNotIn("campaign.json", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
