# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for the adaptation publication convergence seam."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils.toolkit_adaptation_publication_convergence import (
    AdaptationConvergenceConfig,
    CONVERGENCE_REPORT_FILENAME,
    FINALIZATION_OPERATION_DESTINATION_ALIAS,
    FINALIZATION_OPERATION_NARRATIVE_COMPLETION,
    FINALIZATION_OPERATION_STAT_COMPLETION,
    FINALIZATION_OPERATION_MONSTER_REFERENCE,
    apply_adaptation_finalization_proposal,
    build_adaptation_resolution_request,
    prepare_adaptation_repair_context,
    run_adaptation_publication_convergence,
    validate_adaptation_publication_continuation,
    validate_adaptation_finalization_proposal,
)
from utils.toolkit_adaptation_monster_guardrail import (
    build_adaptation_monster_guardrail_report,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_adaptation_staging import STAGING_METADATA_FILENAME


class AdaptationPublicationConvergenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir="tmp", prefix="adaptation_convergence_")
        self.root = Path(self.tmp.name)
        self.source_hash = "b" * 64
        self.target = create_adaptation_staging_target(
            self.source_hash,
            attempt_id="adapt-test",
            attempt_number=1,
            revision_number=1,
            module_slug="Test_Module",
            repo_root=self.root,
            staging_root="staging",
        )
        self.path = self.root / self.target["path"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, **kwargs):
        values = {
            "staged_module_path": str(self.path),
            "mode": "llm_adaptation",
            "attempt_id": "adapt-test",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
            "repo_root": self.root,
        }
        values.update(kwargs)
        return run_adaptation_publication_convergence(**values)

    def _continuation_inputs(self):
        identity = {
            "attempt_id": "adapt-test",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
        }
        gates = {
            name: {"effective_status": "pass"}
            for name in (
                "schema", "readiness", "mechanical_closure",
                "semantic_authority", "semantic_probes", "report_agreement",
            )
        }
        return {
            "staging_target": dict(self.target),
            "build_result": {"status": "success"},
            "attempt_report": dict(identity),
            "semantic_authority": {
                "attempt": dict(identity),
                "adaptation_provenance": {"source_hash": self.source_hash},
            },
            "convergence_result": {
                **identity, "status": "ready", "report_path": "staging/report.json",
            },
            "gate_result": {
                "status": "pass", "playable_status": "pass",
                "publishable_status": "pass", "candidate_eligible": True,
                "provenance": dict(identity), "gates": gates,
            },
        }

    def test_publication_continuation_requires_current_identity_and_all_gates(self):
        result = validate_adaptation_publication_continuation(
            **self._continuation_inputs()
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason_code"], "publication_inputs_agree")

    def test_publication_continuation_blocks_stale_report_identity(self):
        values = self._continuation_inputs()
        values["attempt_report"]["revision_number"] = 0
        result = validate_adaptation_publication_continuation(**values)
        self.assertFalse(result["allowed"])
        self.assertIn("attempt_report_identity_mismatch", result["blockers"])

    def test_valid_callback_success_writes_atomic_staging_report(self) -> None:
        calls = []
        result = self._run(provider_callback=lambda context: calls.append(context) or {"status": "success"})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(calls), 1)
        report = json.loads((self.path / "adaptation_convergence_report.json").read_text())
        self.assertEqual(report["status"], "ready")
        self.assertNotIn("provider_payload", report)
        self.assertTrue(result["report_path"])
        self.assertEqual(report["report_path"], result["report_path"])
        self.assertEqual(result["source_hash"], self.source_hash)
        self.assertEqual(report["source_hash"], self.source_hash)

    def test_repair_context_is_forwarded_as_bounded_destination_request(self) -> None:
        calls = []
        validation_context = {
            "status": "repairable",
            "repairable": True,
            "repair_requests": [{
                "operation": "resolve_destination_alias",
                "phrase": "softstone inn",
                "blocker": "ambiguous_destination_phrase",
            }],
            "ambiguous_phrase": "softstone inn",
            "candidates": [
                {"id": "EV001:K02", "name": "Softstone Inn", "area_id": "EV001"},
                {"id": "RO001:K03", "name": "Softstone Inn", "area_id": "RO001"},
            ],
            "source_reference_ids": ["source-1"],
            "source_references": [{"id": "source-1", "excerpt": "The softstone inn stands near the road."}],
            "canonical_location_ids": ["EV001:K02", "RO001:K03"],
            "allowed_operations": ["resolve_destination_alias"],
            "confidence_threshold": 0.80,
            "operation_budget": 1,
            "timeout_seconds": 30,
            "topology": {
                "locations": ["EV001:K02", "RO001:K03"],
                "edges": [["EV001:K02", "RO001:K03"]],
            },
        }
        result = self._run(
            validation_context=validation_context,
            provider_callback=lambda context: calls.append(context) or {"status": "success"},
        )
        self.assertEqual(result["status"], "ready")
        request = calls[0]["request"]
        self.assertEqual(request["operation"], "resolve_destination_alias")
        bounded = request["validation_context"]
        self.assertEqual(bounded["ambiguous_phrase"], "softstone inn")
        self.assertEqual([row["id"] for row in bounded["candidates"]], ["EV001:K02", "RO001:K03"])
        self.assertEqual(bounded["allowed_operations"], ["resolve_destination_alias"])
        self.assertEqual(bounded["operation_budget"], 1)
        self.assertEqual(bounded["timeout_seconds"], 30)
        serialized = json.dumps(request)
        self.assertNotIn("module_contents", serialized)
        self.assertNotIn("provider_history", serialized)
        self.assertNotIn("live_module", serialized)

    def test_callback_identity_mismatch_is_blocked_before_report_persistence(self) -> None:
        def stale_callback(context):
            return {
                "status": "success",
                "reason_code": "no_repairable_blocker",
                "attempt_id": "different-attempt",
                "attempt_number": context["attempt_number"],
                "revision_number": context["revision_number"],
                "source_hash": context["source_hash"],
                "staging_identity": context["staging_identity"],
            }

        result = self._run(provider_callback=stale_callback)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "callback_identity_mismatched")
        self.assertFalse((self.path / CONVERGENCE_REPORT_FILENAME).exists())

    def test_staging_metadata_mutation_after_callback_is_blocked(self) -> None:
        def mutating_callback(_context):
            metadata_path = self.path / STAGING_METADATA_FILENAME
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["revision_number"] = 2
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            return {"status": "success"}

        result = self._run(provider_callback=mutating_callback)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            result["reason_code"], "staging_target_changed_after_callback"
        )
        self.assertFalse((self.path / CONVERGENCE_REPORT_FILENAME).exists())

    def test_report_persists_bounded_hashes_budget_and_accepted_provenance(self) -> None:
        raw = {"status": "success", "operation": "resolve_destination_alias", "payload": "secret" * 500}
        result = self._run(current_attempt=1, provider_callback=lambda _: raw)
        report = json.loads((self.path / "adaptation_convergence_report.json").read_text())
        self.assertEqual(report["budget_state"]["current_attempt"], 1)
        self.assertEqual(report["provider_failure_class"], None)
        self.assertEqual(len(report["proposal_input_hash"]), 64)
        self.assertEqual(len(report["accepted_output_hash"]), 64)
        self.assertEqual(len(report["provenance_hash"]), 64)
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(result["status"], "ready")

    def test_accepted_destination_alias_is_validated_and_applied_to_staging(self) -> None:
        identity = {
            "attempt_id": "adapt-test",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
        }
        (self.path / "module_context.json").write_text(json.dumps({
            "moduleName": "Test_Module",
            "semantic_authority": {"attempt": identity, "destination_phrases": {}, "diagnostics": {
                "ambiguous_destination_phrases": [{"phrase": "watchers crown", "candidate_location_ids": ["LOC01", "LOC02"]}]
            }},
        }))
        proposal = {
            "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
            "identity": identity,
            "target": {"location_id": "LOC01", "origin_location_id": "LOC02", "phrase": "watchers crown"},
            "source_references": ["source_manifest"],
            "confidence": 0.95,
            "replacement": "LOC01",
            "topology": {"location_ids": ["LOC01", "LOC02"], "edges": [["LOC01", "LOC02"]]},
        }
        context = {
            "source_reference_ids": ["source_manifest"],
            "canonical_location_ids": ["LOC01", "LOC02"],
            "authored_target_ids": [],
            "approved_monster_ids": [],
            "topology": proposal["topology"],
        }
        def proposal_callback(callback_context):
            return {
                "status": "success",
                "proposal": proposal,
                "provider_payload": "secret",
                **{
                    key: callback_context[key]
                    for key in (
                        "attempt_id",
                        "attempt_number",
                        "revision_number",
                        "source_hash",
                        "staging_identity",
                    )
                },
            }

        result = self._run(
            validation_context=context,
            provider_callback=proposal_callback,
        )
        self.assertEqual(result["status"], "ready")
        updated = json.loads((self.path / "module_context.json").read_text())
        authority = updated["semantic_authority"]
        self.assertEqual(authority["destination_phrases"]["watchers crown"]["location_id"], "LOC01")
        self.assertEqual(authority["diagnostics"]["ambiguous_destination_phrases"], [])
        self.assertNotIn("provider_payload", json.dumps(json.loads((self.path / "adaptation_convergence_report.json").read_text())))

    def test_packet_builder_passes_current_convergence_identity_to_gate(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_packet_builder.py").read_text(encoding="utf-8")
        gate_call = source.index("run_adaptation_gate_composer(")
        gate_end = source.index("_adaptation_gate_result[\"convergence_rerun\"]", gate_call)
        self.assertIn("convergence_result=_adaptation_convergence_result", source[gate_call:gate_end])

    def test_provider_tripwire_timeout_malformed_and_rejection_are_bounded(self) -> None:
        def tripwire(_):
            raise AssertionError("provider/network must not be imported or called")

        # The callback seam is the only execution boundary; no real provider is
        # imported by this module.  A caller may still inject a deterministic
        # failure for report-contract testing.
        result = self._run(provider_callback=lambda _: (_ for _ in ()).throw(TimeoutError("provider timeout")))
        report = json.loads((self.path / "adaptation_convergence_report.json").read_text())
        self.assertEqual(report["provider_failure_class"], "timeout")
        self.assertNotIn("provider timeout", json.dumps(report))
        result = self._run(provider_callback=lambda _: {"status": "malformed", "payload": {"secret": "x"}})
        self.assertEqual(result["provider_failure_class"], "malformed")
        result = self._run(provider_callback=lambda _: {"status": "rejected", "reason_code": "invalid_operation"})
        self.assertEqual(result["provider_failure_class"], "rejected")
        self.assertIsNotNone(tripwire)

    def test_budget_exhaustion_and_stale_identity_do_not_overwrite_report(self) -> None:
        result = self._run(provider_callback=lambda _: {"status": "success"})
        report_path = self.path / "adaptation_convergence_report.json"
        before = report_path.read_bytes()
        result = self._run(source_hash="c" * 64, provider_callback=lambda _: {"status": "success"})
        self.assertEqual(result["reason_code"], "staging_target_invalid_or_mismatched")
        self.assertEqual(before, report_path.read_bytes())

    def test_attempt_and_revision_mismatch_refuse_gate_identity_without_overwrite(self) -> None:
        self._run(provider_callback=lambda _: {"status": "success"})
        report_path = self.path / "adaptation_convergence_report.json"
        before = report_path.read_bytes()
        for kwargs in (
            {"attempt_id": "stale-attempt"},
            {"attempt_number": 2},
            {"revision_number": 2},
        ):
            result = self._run(**kwargs, provider_callback=lambda _: self.fail("stale callback invoked"))
            self.assertEqual(result["reason_code"], "staging_target_invalid_or_mismatched")
            self.assertEqual(before, report_path.read_bytes())
        result = self._run(current_attempt=3, provider_callback=lambda _: {"status": "success"})
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(before, report_path.read_bytes())

    def test_callback_is_called_at_most_once_per_round(self) -> None:
        calls = []
        config = AdaptationConvergenceConfig(max_attempts=2)
        self._run(config=config, provider_callback=lambda _: calls.append(1) or {"status": "failed"})
        self.assertEqual(len(calls), 1)
        self._run(current_attempt=1, config=config, provider_callback=lambda _: calls.append(1) or {"status": "failed"})
        self.assertEqual(len(calls), 2)
        self._run(current_attempt=2, config=config, provider_callback=lambda _: calls.append(1) or {"status": "failed"})
        self.assertEqual(len(calls), 2)

    def test_callback_result_and_structured_failure_reason_are_bounded(self) -> None:
        called = []
        result = self._run(provider_callback=lambda _: called.append(True) or [])
        self.assertEqual(result["reason_code"], "callback_result_invalid")
        self.assertEqual(len(called), 1)
        result = self._run(
            provider_callback=lambda _: {"status": "failed", "reason_code": "source_gap"}
        )
        self.assertEqual(result["reason_code"], "source_gap")

    def test_invalid_provenance_and_budget_reject_without_report_or_callback(self) -> None:
        called = []
        report = self.path / "adaptation_convergence_report.json"
        for kwargs in (
            {"source_hash": "not-a-sha"},
            {"current_attempt": True},
            {"current_attempt": -1},
            {"current_attempt": 3},
        ):
            result = self._run(**kwargs, provider_callback=lambda _: called.append(True))
            self.assertIn(result["status"], {"blocked", "budget_exhausted"})
            self.assertFalse(report.exists())
        self.assertFalse(called)

    def test_config_bounds_reject_invalid_values(self) -> None:
        for kwargs in (
            {"max_attempts": True},
            {"max_attempts": 0},
            {"max_attempts": 11},
            {"max_operations_per_round": 0},
            {"operation_timeout_seconds": 301},
        ):
            with self.assertRaises(ValueError):
                AdaptationConvergenceConfig(**kwargs)

    def test_identity_valid_metadata_at_different_path_is_rejected(self) -> None:
        copied = self.root / "copied-target"
        copied.mkdir()
        (copied / "staging_metadata.json").write_text(
            (self.path / "staging_metadata.json").read_text(), encoding="utf-8"
        )
        called = []
        result = self._run(
            staged_module_path=str(copied),
            provider_callback=lambda _: called.append(True),
        )
        self.assertEqual(result["reason_code"], "staging_path_unsafe")
        self.assertFalse(called)
        self.assertFalse((copied / "adaptation_convergence_report.json").exists())

    def test_symlink_staging_path_is_rejected(self) -> None:
        link = self.root / "staging-link"
        try:
            link.symlink_to(self.path, target_is_directory=True)
        except OSError as exc:
            self.skipTest("symlinks unavailable: %s" % exc)
        called = []
        result = self._run(staged_module_path=str(link), provider_callback=lambda _: called.append(True))
        self.assertEqual(result["reason_code"], "staging_path_unsafe")
        self.assertFalse(called)

    def test_report_persistence_failure_does_not_write_outside_target(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        with patch(
            "utils.toolkit_adaptation_publication_convergence.safe_write_json",
            return_value=False,
        ):
            result = self._run(provider_callback=lambda _: {"status": "success"})
        self.assertEqual(result["reason_code"], "report_persist_failed")
        self.assertFalse((outside / "adaptation_convergence_report.json").exists())

    def test_legacy_is_noop_and_callback_not_called(self) -> None:
        called = []
        result = self._run(mode="legacy_modulebuilder", provider_callback=lambda _: called.append(True))
        self.assertEqual(result["status"], "not_applicable")
        self.assertFalse(called)
        self.assertFalse((self.path / "adaptation_convergence_report.json").exists())

    def test_packet_builder_stage_order_and_legacy_metadata_isolation_contract(self) -> None:
        source = Path("web/extensions/toolkit_homebrew_packet_builder.py").read_text(encoding="utf-8")
        convergence = source.index("run_adaptation_publication_convergence(")
        readiness = source.index("run_adaptation_gate_composer(")
        self.assertLess(convergence, readiness)
        self.assertIn('"source_hash"', source[source.index('build_result["adaptation_convergence"]'):])
        self.assertIn('build_result.get("status") == "success"', source[convergence:readiness])
        self.assertIn('_adaptation_convergence_result.get("status") == "ready"', source[convergence:readiness])
        self.assertIn('"convergence_rerun"', source[readiness:])
        self.assertIn('"accepted": True', source[readiness:])

        called = []
        legacy_result = self._run(mode="legacy_modulebuilder", provider_callback=lambda _: called.append(True))
        self.assertEqual(legacy_result["status"], "not_applicable")
        self.assertFalse(called)
        self.assertNotIn("adaptation_convergence", legacy_result)
        self.assertFalse((self.path / "adaptation_convergence_report.json").exists())

    def test_stale_or_unsafe_identity_rejects_before_callback(self) -> None:
        called = []
        result = self._run(source_hash="c" * 64, provider_callback=lambda _: called.append(True))
        self.assertEqual(result["reason_code"], "staging_target_invalid_or_mismatched")
        self.assertFalse(called)

    def test_terminal_target_and_budget_reject_before_callback(self) -> None:
        metadata = json.loads((self.path / "staging_metadata.json").read_text())
        metadata["completion_state"] = "failed"
        (self.path / "staging_metadata.json").write_text(json.dumps(metadata))
        called = []
        result = self._run(provider_callback=lambda _: called.append(True))
        self.assertEqual(result["reason_code"], "staging_target_terminal")
        self.assertFalse(called)
        result = self._run(current_attempt=3, provider_callback=lambda _: called.append(True))
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertFalse(called)

    def test_callback_failure_preserves_module_and_reports_failure(self) -> None:
        before = (self.path / "staging_metadata.json").read_bytes()
        result = self._run(provider_callback=lambda _: (_ for _ in ()).throw(RuntimeError("provider")))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(before, (self.path / "staging_metadata.json").read_bytes())
        self.assertTrue(Path(result["report_path"]).exists())

    def test_budgets_are_in_result_contract(self) -> None:
        result = self._run(config=AdaptationConvergenceConfig(2, 1, 9), provider_callback=lambda _: {"status": "success"})
        self.assertEqual(result["budget"], {"max_attempts": 2, "max_operations_per_round": 1, "operation_timeout_seconds": 9})

    def _resolution(self, **kwargs):
        values = {
            "mode": "llm_adaptation",
            "ambiguous_phrase": "watchers crown",
            "candidates": [
                {"id": "LOC02", "name": "Crown Hall"},
                {"id": "LOC01", "name": "Moonlit Shrine"},
            ],
            "source_references": [{"id": "src-2", "excerpt": "The crown hall is north."}],
            "topology_summary": {"locations": ["LOC02", "LOC01"], "edges": [["LOC02", "LOC01"]], "summary": "adjacent"},
            "attempt_id": "adapt-test",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
            "current_identity": {"attempt_id": "adapt-test", "attempt_number": 1, "revision_number": 1, "source_hash": self.source_hash},
        }
        values.update(kwargs)
        return build_adaptation_resolution_request(**values)

    def test_bounded_resolution_request_has_only_allowed_context_and_identity(self) -> None:
        result = self._resolution()
        self.assertEqual(result["status"], "ready")
        request = result["request"]
        self.assertEqual(request["operation"], "resolve_destination_alias")
        self.assertEqual(request["identity"]["source_hash"], self.source_hash)
        self.assertEqual([row["id"] for row in request["context"]["candidates"]], ["LOC01", "LOC02"])
        self.assertNotIn("provider_callback", json.dumps(request))
        self.assertNotIn("staged_module_path", json.dumps(request))
        self.assertEqual(set(request["context"]), {"ambiguous_phrase", "candidates", "source_references", "topology_summary"})

    def test_resolution_order_is_deterministic_and_limits_are_enforced(self) -> None:
        first = self._resolution()
        second = self._resolution(candidates=list(reversed(first["request"]["context"]["candidates"])))
        self.assertEqual(first["request"], second["request"])
        result = self._resolution(source_references=[{"id": "x", "excerpt": "x"}] * 9)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("source_references_limit_exceeded", result["diagnostics"])

    def test_resolution_legacy_and_bad_identity_are_noops_or_blocked(self) -> None:
        self.assertEqual(self._resolution(mode="legacy_modulebuilder")["status"], "not_applicable")
        result = self._resolution(attempt_number=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("attempt_number_invalid", result["diagnostics"])
        result = self._resolution(current_identity={"attempt_id": "stale"})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(item.startswith("current_identity_mismatch") for item in result["diagnostics"]))

    def test_resolution_rejects_unbounded_or_structural_context(self) -> None:
        result = self._resolution(ambiguous_phrase="x" * 161)
        self.assertEqual(result["status"], "blocked")
        result = self._resolution(topology_summary={"locations": ["x"] * 25, "edges": []})
        self.assertEqual(result["status"], "blocked")
        result = self._resolution(source_references=[{"id": "x", "excerpt": "x", "path": "secret"}])
        self.assertEqual(result["status"], "blocked")

    def test_resolution_has_no_provider_call_seam(self) -> None:
        result = self._resolution()
        self.assertNotIn("provider_callback", result)
        self.assertNotIn("provider", result["request"])

    def _prepare_context_fixture(self, *, ambiguous: bool = True) -> dict:
        """Create a small staged authority fixture without provider imports."""
        (self.path / "areas").mkdir(parents=True, exist_ok=True)
        (self.path / "module_context.json").write_text(
            json.dumps({"module_name": "Test_Module", "npcs": {}}), encoding="utf-8"
        )
        phrase = "softstone inn" if ambiguous else "moonlit shrine"
        (self.path / "module_plot.json").write_text(
            json.dumps({"plotPoints": [{"id": "P1", "title": "Travel to " + phrase}]}),
            encoding="utf-8",
        )
        for area_id, name in (("EV001", "East Softstone Inn"), ("RO001", "Road Softstone Inn")):
            area = {"areaId": area_id, "locations": [{
                "locationId": "K02", "name": name,
                "aliases": ["softstone inn"] if ambiguous else [], "connectivity": [],
            }]}
            (self.path / "areas" / (area_id + ".json")).write_text(json.dumps(area), encoding="utf-8")
        workspace = self.root / "workspace"
        workspace.mkdir()
        identity = {
            "attempt_id": "adapt-test", "attempt_number": 1,
            "revision_number": 1, "source_hash": self.source_hash,
        }
        manifest = {**identity, "module_slug": "Test_Module", "location_candidates": [
            {"name": "softstone inn", "source_ref": "src-location-1"}
        ]}
        packet = {**identity, "module_slug": "Test_Module", "destination_phrases": [
            {"phrase": phrase, "source_ref": "src-destination-1", "excerpt": "Travel to " + phrase}
        ]}
        graph = {"atoms": [{"atom_id": "src-graph-1", "text": "The road reaches the inn."}]}
        for filename, payload in (("source_manifest.json", manifest), ("normalized_packet.json", packet), ("source_graph.json", graph)):
            (workspace / filename).write_text(json.dumps(payload), encoding="utf-8")
        return {"workspace": workspace, "identity": identity}

    def test_prepared_repair_context_preserves_identity_area_scope_and_bounds(self) -> None:
        fixture = self._prepare_context_fixture()
        result = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        self.assertEqual(result["status"], "repairable")
        self.assertEqual(result["identity"], fixture["identity"])
        context = result["validation_context"]
        self.assertEqual(context["operation_budget"], 1)
        self.assertEqual(context["timeout_seconds"], 30)
        self.assertEqual({row["id"] for row in context["candidates"]}, {"EV001:K02", "RO001:K02"})
        self.assertTrue(all("area_id" in row for row in context["candidates"]))
        self.assertLessEqual(len(context["candidates"]), 8)
        self.assertLessEqual(len(context["source_references"]), 8)
        self.assertLessEqual(len(json.dumps(context)), 6000)
        saved = json.loads((self.path / "module_context.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["semantic_authority"]["attempt"], fixture["identity"])

    def test_preparation_selects_one_blocker_and_has_no_provider_seam(self) -> None:
        fixture = self._prepare_context_fixture()
        called = []
        result = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        called.append(result)
        self.assertEqual(len(called), 1)
        self.assertEqual(result["validation_context"]["repair_requests"][0]["phrase"], "softstone inn")
        self.assertNotIn("provider_callback", json.dumps(result))

    def test_post_application_refresh_preserves_validated_alias_and_hashes(self) -> None:
        fixture = self._prepare_context_fixture()
        prepared = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        context = prepared["validation_context"]
        proposal = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
            "identity": fixture["identity"],
            "target": {
                "location_id": "EV001:K02",
                "phrase": "softstone inn",
            },
            "source_references": ["src-location-1"],
            "confidence": 0.95,
            "replacement": "EV001:K02",
            "topology": {"location_ids": ["EV001:K02", "RO001:K02"], "edges": []},
        }
        def accepted_callback(request):
            return {
                "status": "success",
                "identity": fixture["identity"],
                "staging_identity": request["staging_identity"],
                "proposal": proposal,
            }

        applied = self._run(
            validation_context=context, provider_callback=accepted_callback,
        )
        self.assertEqual(applied["status"], "ready")

        refreshed = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        self.assertEqual(refreshed["status"], "no_repairable_blocker")
        authority = refreshed["semantic_authority"]
        resolved = authority["destination_phrases"]["softstone inn"]
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["location_id"], "EV001:K02")
        self.assertEqual(authority["attempt"], fixture["identity"])
        self.assertEqual(authority["finalization_repairs"][0]["identity"], fixture["identity"])
        for field in ("input_hash", "output_hash", "provenance_hash"):
            self.assertRegex(authority["finalization_repairs"][0][field], r"^[0-9a-f]{64}$")
        self.assertFalse(any(
            isinstance(row, dict) and row.get("phrase") == "softstone inn"
            for row in authority.get("diagnostics", {}).get("ambiguous_destination_phrases", [])
        ))

    def test_preparation_returns_empty_context_without_ambiguous_blocker(self) -> None:
        fixture = self._prepare_context_fixture(ambiguous=False)
        result = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        self.assertEqual(result["status"], "no_repairable_blocker")
        self.assertIsNone(result["validation_context"])

    def test_preparation_fails_closed_for_missing_source_artifact(self) -> None:
        fixture = self._prepare_context_fixture()
        (fixture["workspace"] / "source_graph.json").unlink()
        result = prepare_adaptation_repair_context(
            workspace=fixture["workspace"], staged_module_path=self.path,
            module_slug="Test_Module", attempt=fixture["identity"], repo_root=self.root,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "repair_context_preparation_failed")
        self.assertIsNone(result["validation_context"])

    def _proposal(self, operation, **overrides):
        proposal = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": operation,
            "identity": {
                "attempt_id": "adapt-test",
                "attempt_number": 1,
                "revision_number": 1,
                "source_hash": self.source_hash,
            },
            "target": {"location_id": "LOC01", "phrase": "moonlit shrine"},
            "source_references": ["src-1"],
            "confidence": 0.95,
            "replacement": "LOC01",
            "topology": {"location_ids": ["LOC01", "LOC02"], "edges": [["LOC01", "LOC02"]]},
        }
        proposal.update(overrides)
        return proposal

    def test_finalization_accepts_destination_alias_and_staging_dict_apply(self) -> None:
        result = validate_adaptation_finalization_proposal(
            self._proposal(FINALIZATION_OPERATION_DESTINATION_ALIAS),
            current_identity=self._proposal(FINALIZATION_OPERATION_DESTINATION_ALIAS)["identity"],
            source_reference_ids=["src-1"],
            canonical_location_ids=["LOC01", "LOC02"],
            topology={"location_ids": ["LOC01", "LOC02"], "edges": [["LOC01", "LOC02"]]},
        )
        self.assertTrue(result["valid"])
        updated = apply_adaptation_finalization_proposal({"module_slug": "Test_Module"}, result["operation"])
        self.assertEqual(updated["module_slug"], "Test_Module")
        self.assertEqual(updated["semantic_authority"]["destination_phrases"]["moonlit shrine"]["location_id"], "LOC01")

    def test_finalization_accepts_narrative_and_approved_stat_requests(self) -> None:
        identity = self._proposal(FINALIZATION_OPERATION_NARRATIVE_COMPLETION)["identity"]
        narrative = self._proposal(
            FINALIZATION_OPERATION_NARRATIVE_COMPLETION,
            target={"target_id": "LOC01", "field": "description"},
            replacement="A moonlit shrine overlooks the old road.",
        )
        result = validate_adaptation_finalization_proposal(
            narrative, current_identity=identity, source_reference_ids=["src-1"], authored_target_ids=["LOC01"], topology={"location_ids": ["LOC01"], "edges": []}
        )
        self.assertTrue(result["valid"])

    def test_finalizer_completes_guardrail_approved_stat_request_without_identity_mutation(self) -> None:
        """Stat completion records metadata but cannot bypass monster authority."""
        monster_path = self.path / "monsters" / "approved_wight.json"
        monster_path.parent.mkdir(parents=True, exist_ok=True)
        monster_path.write_text(json.dumps({
            "name": "Approved Wight",
            "size": "Medium",
            "alignment": "lawful evil",
            "armorClass": 14,
        }), encoding="utf-8")
        guardrail = build_adaptation_monster_guardrail_report(
            {"encounter_seeds": [{"adversaries": ["approved_wight"]}]},
            self.path,
        )
        self.assertEqual(guardrail["status"], "pass")
        approved_monster_ids = [
            row["ref"]
            for row in guardrail["resolution_diagnostics"]
            if row["status"] == "reused"
        ]
        self.assertEqual(approved_monster_ids, ["approved_wight"])

        identity = {
            "attempt_id": "adapt-test",
            "attempt_number": 1,
            "revision_number": 1,
            "source_hash": self.source_hash,
        }
        stat_proposal = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": FINALIZATION_OPERATION_STAT_COMPLETION,
            "identity": identity,
            "target": {"monster_id": "approved_wight"},
            "source_references": ["guardrail-report"],
            "confidence": 0.95,
            "topology": {"location_ids": ["LOC01"], "edges": []},
        }
        validation_context = {
            "source_reference_ids": ["guardrail-report"],
            "canonical_location_ids": ["LOC01"],
            "authored_target_ids": [],
            "approved_monster_ids": approved_monster_ids,
            "topology": stat_proposal["topology"],
        }
        callback_contexts = []

        def callback(context):
            callback_contexts.append(context)
            return {
                "status": "success",
                "proposal": stat_proposal,
                "staging_identity": context["staging_identity"],
            }

        result = self._run(
            validation_context=validation_context,
            provider_callback=callback,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["operation"], FINALIZATION_OPERATION_STAT_COMPLETION)
        self.assertEqual(result["accepted_operation"]["target"]["monster_id"], "approved_wight")
        self.assertEqual(result["accepted_operation"]["identity"], identity)
        self.assertEqual(callback_contexts[0]["validation_context"]["approved_monster_ids"], approved_monster_ids)
        self.assertEqual(result["source_hash"], self.source_hash)
        self.assertEqual(len(result["proposal_input_hash"]), 64)
        self.assertEqual(len(result["accepted_output_hash"]), 64)
        self.assertEqual(len(result["provenance_hash"]), 64)
        report = json.loads((self.path / "adaptation_convergence_report.json").read_text())
        self.assertEqual(report["operation"], FINALIZATION_OPERATION_STAT_COMPLETION)
        self.assertEqual(len(report["proposal_input_hash"]), 64)
        self.assertEqual(len(report["accepted_output_hash"]), 64)
        self.assertEqual(len(report["provenance_hash"]), 64)

        staging = {
            "module_slug": "Test_Module",
            "monster_identity": "approved_wight",
            "monster_artifact": json.loads(monster_path.read_text(encoding="utf-8")),
            "coordinates": {"approved_wight": [1, 2]},
            "connectivity": [["LOC01", "LOC01"]],
            "schema": {"monster_id": "approved_wight"},
            "registry": {"approved_wight": "approved_wight.json"},
            "live_files": {"approved_wight": "unchanged"},
        }
        before_apply = json.loads(json.dumps(staging, sort_keys=True))
        applied = apply_adaptation_finalization_proposal(
            staging, result["accepted_operation"]
        )
        self.assertEqual(
            {key: value for key, value in applied.items() if key != "stat_completion_requests"},
            before_apply,
        )
        self.assertEqual(len(applied["stat_completion_requests"]), 1)
        self.assertEqual(applied["stat_completion_requests"][0]["target"], {"monster_id": "approved_wight"})
        self.assertEqual(applied["monster_identity"], "approved_wight")
        self.assertEqual(applied["registry"], before_apply["registry"])
        self.assertEqual(json.loads(monster_path.read_text(encoding="utf-8")), before_apply["monster_artifact"])

        invented = dict(stat_proposal, target={"monster_id": "invented_wight"})
        rejected = validate_adaptation_finalization_proposal(
            invented,
            current_identity=identity,
            source_reference_ids=["guardrail-report"],
            approved_monster_ids=approved_monster_ids,
            topology=stat_proposal["topology"],
        )
        self.assertFalse(rejected["valid"])
        self.assertIn("monster_identity_not_approved", {item["code"] for item in rejected["diagnostics"]})

        structural = dict(
            stat_proposal,
            target={
                "monster_id": "approved_wight",
                "field": "identity",
                "value": "invented_wight",
            },
        )
        structural_result = validate_adaptation_finalization_proposal(
            structural,
            current_identity=identity,
            source_reference_ids=["guardrail-report"],
            approved_monster_ids=approved_monster_ids,
            topology=stat_proposal["topology"],
        )
        self.assertFalse(structural_result["valid"])
        self.assertIn("monster_identity_not_approved", {item["code"] for item in structural_result["diagnostics"]})
        stat = self._proposal(
            FINALIZATION_OPERATION_STAT_COMPLETION,
            target={"monster_id": "approved_wight"},
        )
        stat.pop("replacement")
        result = validate_adaptation_finalization_proposal(
            stat, current_identity=identity, source_reference_ids=["src-1"], approved_monster_ids=["approved_wight"], topology={"location_ids": ["LOC01"], "edges": []}
        )
        self.assertTrue(result["valid"])

    def test_finalization_rejects_identity_source_confidence_topology_and_extra_fields(self) -> None:
        base = self._proposal(FINALIZATION_OPERATION_DESTINATION_ALIAS)
        cases = [
            (dict(base, identity=dict(base["identity"], revision_number=2)), "identity_mismatch"),
            (dict(base, source_references=["not-in-context"]), "source_evidence_invalid"),
            (dict(base, confidence=0.2), "confidence_below_threshold"),
            (dict(base, target={"location_id": "LOC99", "phrase": "moonlit shrine"}), "canonical_destination_invalid"),
            (dict(base, target={"location_id": "LOC01", "origin_location_id": "LOC99", "phrase": "moonlit shrine"}), "topology_edge_invalid"),
            (dict(base, arbitrary_path="modules/live.json"), "unknown_proposal_field"),
        ]
        for proposal, code in cases:
            result = validate_adaptation_finalization_proposal(
                proposal, current_identity=base["identity"], source_reference_ids=["src-1"], canonical_location_ids=["LOC01", "LOC02"], topology=base["topology"]
            )
            self.assertFalse(result["valid"], code)
            self.assertIn(code, {item["code"] for item in result["diagnostics"]}, code)

    def test_finalization_rejects_structural_identity_and_legacy_noop(self) -> None:
        base = self._proposal("edit_coordinates")
        result = validate_adaptation_finalization_proposal(
            base, current_identity=base["identity"], source_reference_ids=["src-1"], canonical_location_ids=["LOC01"], topology={"location_ids": ["LOC01"], "edges": []}
        )
        self.assertFalse(result["valid"])
        self.assertEqual(run_adaptation_publication_convergence(str(self.path), mode="legacy_modulebuilder", attempt_id="adapt-test", attempt_number=1, revision_number=1, source_hash=self.source_hash)["status"], "not_applicable")

    def test_finalization_accepts_bounded_cave_guardian_resolution(self) -> None:
        identity = {
            "attempt_id": "adapt-test", "attempt_number": 1,
            "revision_number": 1, "source_hash": self.source_hash,
        }
        proposal = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": FINALIZATION_OPERATION_MONSTER_REFERENCE,
            "identity": identity,
            "target": {
                "reference_key": "cave_guardians",
                "canonical_identity": "Cave Guardian",
            },
            "source_references": ["K06", "K08", "K10"],
            "confidence": 0.95,
            "resolution_code": "plural_group_label",
            "quantity_confirmation": {"confirmed": 1, "min": 1, "max": 2},
        }
        result = validate_adaptation_finalization_proposal(
            proposal,
            current_identity=identity,
            source_reference_ids=["K06", "K08", "K10"],
            approved_monster_identities=["Cave Guardian"],
            monster_reference_keys=["cave_guardians"],
            quantity_bounds={"cave_guardians": {"min": 1, "max": 2}},
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["operation"]["target"]["canonical_identity"], "Cave Guardian")
        updated = apply_adaptation_finalization_proposal(
            {"module_slug": "Test_Module"}, result["operation"]
        )
        self.assertEqual(updated["monster_resolution_requests"][0]["target"]["reference_key"], "cave_guardians")

    def test_monster_resolution_rejects_identity_target_freshness_and_unsafe_fields(self) -> None:
        identity = {"attempt_id": "adapt-test", "attempt_number": 1, "revision_number": 1, "source_hash": self.source_hash}
        base = {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": FINALIZATION_OPERATION_MONSTER_REFERENCE,
            "identity": identity,
            "target": {"reference_key": "cave_guardians", "canonical_identity": "Cave Guardian"},
            "source_references": ["K08"], "confidence": 0.95,
            "resolution_code": "plural_group_label",
            "quantity_confirmation": {"confirmed": 1, "min": 1, "max": 2},
        }
        cases = [
            (dict(base, target={"reference_key": "unknown", "canonical_identity": "Cave Guardian"}), "monster_reference_not_approved"),
            (dict(base, target={"reference_key": "cave_guardians", "canonical_identity": "Invented Beast"}), "monster_identity_not_approved"),
            (dict(base, identity=dict(identity, revision_number=2)), "identity_mismatch"),
            (dict(base, arbitrary_path="modules/live.json"), "unknown_proposal_field"),
            (dict(base, raw_patch={"op": "replace"}), "unknown_proposal_field"),
            (dict(base, target={"reference_key": "cave_guardians", "canonical_identity": "Cave Guardian", "path": "x"}), "monster_target_fields_invalid"),
            (dict(base, quantity_confirmation={"confirmed": 3, "min": 1, "max": 2}), "monster_quantity_bounds_invalid"),
        ]
        for proposal, code in cases:
            result = validate_adaptation_finalization_proposal(
                proposal,
                current_identity=identity,
                source_reference_ids=["K08"],
                approved_monster_identities=["Cave Guardian"],
                monster_reference_keys=["cave_guardians"],
                quantity_bounds={"cave_guardians": {"min": 1, "max": 2}},
            )
            self.assertFalse(result["valid"], code)
            self.assertIn(code, {item["code"] for item in result["diagnostics"]}, code)

    def test_monster_resolution_rejects_multiple_or_malformed_operations_and_keeps_legacy(self) -> None:
        identity = {"attempt_id": "adapt-test", "attempt_number": 1, "revision_number": 1, "source_hash": self.source_hash}
        common = {
            "current_identity": identity,
            "source_reference_ids": ["K08"],
            "approved_monster_identities": ["Cave Guardian"],
            "monster_reference_keys": ["cave_guardians"],
        }
        multiple = validate_adaptation_finalization_proposal([{"operation": FINALIZATION_OPERATION_MONSTER_REFERENCE}], **common)
        malformed = validate_adaptation_finalization_proposal({"operation": FINALIZATION_OPERATION_MONSTER_REFERENCE}, **common)
        self.assertFalse(multiple["valid"])
        self.assertEqual(multiple["diagnostics"][0]["code"], "proposal_shape_invalid")
        self.assertFalse(malformed["valid"])
        self.assertTrue(any(item["code"] == "identity_invalid" for item in malformed["diagnostics"]))
        legacy = validate_adaptation_finalization_proposal(
            {"operation": FINALIZATION_OPERATION_MONSTER_REFERENCE}, mode="legacy_modulebuilder", **common
        )
        self.assertEqual(legacy["status"], "not_applicable")

    def test_finalization_public_boundary_is_legacy_noop_for_validate_and_apply(self) -> None:
        base = self._proposal(FINALIZATION_OPERATION_DESTINATION_ALIAS)
        validated = validate_adaptation_finalization_proposal(
            base,
            mode="legacy_modulebuilder",
            current_identity=base["identity"],
            source_reference_ids=["src-1"],
            canonical_location_ids=["LOC01", "LOC02"],
            topology=base["topology"],
        )
        self.assertFalse(validated["valid"])
        self.assertEqual(validated["status"], "not_applicable")
        self.assertIsNone(validated["operation"])
        self.assertEqual(validated["diagnostics"][0]["code"], "legacy_mode")

        staging = {"module_slug": "Test_Module"}
        applied = apply_adaptation_finalization_proposal(
            staging,
            base,
            mode="legacy_modulebuilder",
        )
        self.assertEqual(applied, staging)
        self.assertNotIn("semantic_authority", applied)


class LegacyAdaptationIsolationContractTest(unittest.TestCase):
    """Lock the legacy packet-builder seam against adaptation convergence."""

    def test_packet_builder_convergence_call_is_adaptation_guarded(self) -> None:
        source = Path(
            "web/extensions/toolkit_homebrew_packet_builder.py"
        ).read_text(encoding="utf-8")
        convergence_start = source.index(
            "_adaptation_convergence_result: Optional[Dict[str, Any]] = None"
        )
        convergence_end = source.index(
            "# Refresh the attempt artifact after convergence",
            convergence_start,
        )
        convergence_section = source[convergence_start:convergence_end]
        self.assertIn(
            "if _is_adaptation_build and build_result.get(\"status\") == \"success\":",
            convergence_section,
        )
        self.assertIn("provider_callback=adaptation_convergence_callback", convergence_section)
        self.assertNotIn(
            "run_adaptation_publication_convergence(\n",
            source[:convergence_start],
        )

    def test_legacy_packet_result_skips_callback_and_adaptation_persistence(self) -> None:
        """Exercise the legacy result path with a callback tripwire."""
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder
        from utils.toolkit_homebrew_upload_contract import (
            ensure_workspace_placeholders,
            get_workspace_files,
        )

        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory(dir="tmp", prefix="legacy_isolation_") as temp:
            root = Path(temp)
            workspace = root / "workspace"
            ensure_workspace_placeholders(workspace)
            files = get_workspace_files(workspace)
            os.chdir(root)
            self.addCleanup(lambda: os.chdir(original_cwd))

            packet = {
                "packet_version": "packet.v1",
                "normalization_state": "normalized",
                "source_hash": "legacy-source",
                "source_path": "uploads/legacy.md",
                "title": "Legacy Isolation Fixture",
                "description": "A legacy builder fixture.",
                "adventure_summary": "A bounded legacy build.",
                "acts": [],
                "locations": [],
                "source_rights": "user_authored",
            }
            snapshot = {
                "decision": "approve",
                "packet_identity": {"source_hash": "legacy-source"},
            }
            files["normalized_packet"].write_text(json.dumps(packet), encoding="utf-8")
            files["ui_review_snapshot"].write_text(json.dumps(snapshot), encoding="utf-8")

            callback = Mock(side_effect=AssertionError("legacy convergence callback called"))
            legacy_persist = Mock(return_value=True)
            adaptation_persist = Mock(return_value=True)
            builder_executor = Mock()

            with patch.object(packet_builder, "persist_builder_input_artifact", return_value=True), patch.object(
                packet_builder,
                "persist_legacy_build_result_artifact",
                legacy_persist,
            ), patch.object(
                packet_builder,
                "persist_adaptation_build_result_artifact",
                adaptation_persist,
            ), patch.object(
                packet_builder,
                "ensure_monster_reference_closure",
                create=True,
            ), patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure",
                return_value={"required": 0, "existing_before": 0, "generated": 0, "unresolved": 0},
            ), patch(
                "utils.spatial_repair.repair_module_spatial",
                return_value={"status": "success", "unresolved_count": 0},
            ), patch(
                "utils.calendar_normalization.normalize_party_calendar",
                return_value={"status": "success"},
            ), patch(
                "utils.toolkit_build_fidelity.is_build_fidelity_required",
                return_value=False,
            ):
                result = packet_builder.run_toolkit_homebrew_packet_build(
                    workspace,
                    "legacy-isolation-job",
                    builder_executor=builder_executor,
                    adaptation_convergence_callback=callback,
                )

            self.assertEqual(result.get("status"), "success")
            callback.assert_not_called()
            legacy_persist.assert_called()
            adaptation_persist.assert_not_called()
            for key in (
                "adaptation_convergence",
                "convergence_report",
                "adaptation_gates",
                "adaptation_fidelity_boundary",
                "adaptation_source_fidelity",
                "playable_status",
                "publishable_status",
            ):
                self.assertNotIn(key, result)
            self.assertEqual(result.get("build_mode"), "packet_workspace_v1")
            builder_executor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
