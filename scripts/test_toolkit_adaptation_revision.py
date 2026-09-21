# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for the bounded adaptation final revision runner."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.test_toolkit_adaptation_auditor import (  # noqa: E402
    _base_response,
    _dossier,
    _packet,
)
from utils.toolkit_adaptation_revision import (  # noqa: E402
    MAX_FINAL_REVISIONS,
    REVISION_STATUS_BLOCKED,
    REVISION_STATUS_FAILED,
    REVISION_STATUS_INFRASTRUCTURE_FAILED,
    REVISION_STATUS_NO_REVISION,
    REVISION_STATUS_REVISION_PASSED,
    describe_adaptation_revision_limit,
    normalize_adaptation_revision_limit,
    run_adaptation_final_revision,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _response(packet: Dict[str, Any], decision: str = "revise", *, directive: bool = False) -> Dict[str, Any]:
    response = _base_response(packet, decision)
    if decision == "revise":
        if directive:
            response["rebuild_directive"] = {
                "action": "fresh_build",
                "target": "staging",
                "basis": "revised_dossier",
                "guidance": ["Keep the revised adaptation playable and bounded."],
            }
        else:
            response["revised_dossier"] = _dossier()
    return response


class TestAdaptationRevisionBudget(unittest.TestCase):
    def test_default_and_hard_cap(self) -> None:
        self.assertEqual(normalize_adaptation_revision_limit(0), 0)
        self.assertEqual(normalize_adaptation_revision_limit(1), 1)
        self.assertEqual(normalize_adaptation_revision_limit(2), 2)
        self.assertEqual(normalize_adaptation_revision_limit(99), MAX_FINAL_REVISIONS)
        self.assertEqual(normalize_adaptation_revision_limit(-1), 0)
        self.assertEqual(normalize_adaptation_revision_limit("2"), 1)
        description = describe_adaptation_revision_limit(99)
        self.assertTrue(description["clamped"])
        self.assertEqual(description["max_revisions"], 2)


class RevisionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / "tmp" / "toolkit_adaptation_revision_contract"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.packet = _packet()
        self.dossier = _dossier()
        self.auditor_calls: List[Dict[str, Any]] = []
        self.build_calls: List[Dict[str, Any]] = []

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def auditor(self, failure_packet: Dict[str, Any], **_: Any) -> Dict[str, Any]:
        self.auditor_calls.append(copy.deepcopy(failure_packet))
        return {
            "status": "success",
            "decision": "revise",
            "ok": True,
            "response": _response(failure_packet),
            "model_metadata": {"provider": "fixture", "model": "fixture-auditor"},
        }

    def builder(self, staging_target: Dict[str, Any], dossier: Dict[str, Any], directive: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        self.build_calls.append({
            "target": copy.deepcopy(staging_target),
            "dossier": copy.deepcopy(dossier),
            "directive": copy.deepcopy(directive),
            "kwargs": copy.deepcopy(kwargs),
        })
        stage = self.root / staging_target["path"]
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "revision_marker.json").write_text(
            json.dumps({"revision": staging_target["revision_number"]}), encoding="utf-8"
        )
        return {"status": "success", "output_hash": "d" * 64}

    def run_revision(self, **kwargs: Any) -> Dict[str, Any]:
        return run_adaptation_final_revision(
            self.packet,
            workspace=self.root,
            repo_root=self.root,
            staging_root="tmp/adaptation-staging",
            build_callback=kwargs.pop("build_callback", self.builder),
            auditor_runner=kwargs.pop("auditor_runner", self.auditor),
            current_dossier=kwargs.pop("current_dossier", self.dossier),
            **kwargs,
        )


class TestAdaptationRevisionOrchestration(RevisionFixture):
    def test_initial_eligible_failure_reaches_auditor_without_consumption_flag(self) -> None:
        packet = copy.deepcopy(self.packet)
        packet["failure_classification"]["consumes_semantic_revision_budget"] = False

        result = run_adaptation_final_revision(
            packet,
            workspace=self.root,
            repo_root=self.root,
            staging_root="tmp/adaptation-staging",
            build_callback=self.builder,
            auditor_runner=self.auditor,
            current_dossier=self.dossier,
            max_revisions=1,
        )

        self.assertEqual(result["status"], REVISION_STATUS_REVISION_PASSED, result)
        self.assertEqual(len(self.auditor_calls), 1)
        self.assertEqual(len(self.build_calls), 1)
        self.assertTrue(result["semantic_revision_budget_consumed"])

    def test_zero_budget_does_not_call_auditor_or_builder(self) -> None:
        result = self.run_revision(max_revisions=0)
        self.assertEqual(result["status"], REVISION_STATUS_NO_REVISION)
        self.assertEqual(self.auditor_calls, [])
        self.assertEqual(self.build_calls, [])
        self.assertEqual(result["staging_targets"], [])

    def test_default_one_revision_uses_fresh_stage_and_records_revision(self) -> None:
        result = self.run_revision()
        self.assertEqual(result["status"], REVISION_STATUS_REVISION_PASSED)
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(result["staging_target"]["revision_number"], 1)
        self.assertIn("revision_001", result["staging_target"]["path"])
        self.assertEqual(len(self.build_calls), 1)
        self.assertEqual(self.build_calls[0]["target"]["revision_number"], 1)
        self.assertEqual(self.build_calls[0]["directive"]["target"], "staging")
        self.assertTrue(result["revision_report_persisted"])
        self.assertTrue(result["build_result_persisted"])
        self.assertTrue((self.root / result["staging_target"]["path"] / "staging_metadata.json").exists())

    def test_configured_two_revision_cap_runs_two_distinct_stages(self) -> None:
        calls = {"count": 0}

        def failing_then_passing(staging_target: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            calls["count"] += 1
            self.build_calls.append(copy.deepcopy(staging_target))
            if calls["count"] == 1:
                return {
                    "status": "failed",
                    "failure_class": "semantic",
                    "revision_eligible": True,
                    "error": "semantic destination remains ambiguous",
                    "gate_results": {"semantic_authority": {"status": "blocked", "errors": ["ambiguous"]}},
                }
            return {"status": "success"}

        result = self.run_revision(max_revisions=2, build_callback=failing_then_passing)
        self.assertEqual(result["status"], REVISION_STATUS_REVISION_PASSED)
        self.assertEqual(result["revision_number"], 2)
        self.assertEqual([item["revision_number"] for item in self.build_calls], [1, 2])
        self.assertNotEqual(self.build_calls[0]["path"], self.build_calls[1]["path"])
        self.assertEqual([item["revision_number"] for item in self.auditor_calls], [0, 1])

    def test_maximum_above_two_is_clamped_and_never_runs_three_builds(self) -> None:
        def always_fail(staging_target: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            self.build_calls.append(copy.deepcopy(staging_target))
            return {
                "status": "failed",
                "failure_class": "semantic",
                "revision_eligible": True,
                "error": "semantic failure",
            }

        result = self.run_revision(max_revisions=99, build_callback=always_fail)
        self.assertEqual(result["max_revisions"], 2)
        self.assertEqual(len(self.build_calls), 2)
        self.assertLessEqual(len(self.auditor_calls), 2)
        self.assertEqual(result["status"], REVISION_STATUS_FAILED)

    def test_infrastructure_failure_does_not_consume_revision_budget(self) -> None:
        def provider_failure(_: Dict[str, Any], **__: Any) -> Dict[str, Any]:
            return {
                "status": "provider_failed",
                "decision": "failed",
                "failure_class": "timeout",
                "reason": "provider timeout",
            }

        result = self.run_revision(auditor_runner=provider_failure)
        self.assertEqual(result["status"], REVISION_STATUS_INFRASTRUCTURE_FAILED)
        self.assertFalse(result["semantic_revision_budget_consumed"])
        self.assertEqual(result["revision_number"], 0)
        self.assertEqual(result["staging_targets"], [])
        self.assertEqual(self.build_calls, [])

    def test_refusal_returns_bounded_blocked_result_without_build(self) -> None:
        def refusal(_: Dict[str, Any], **__: Any) -> Dict[str, Any]:
            return {"status": "refused", "decision": "refuse", "reason": "not safe to revise"}

        result = self.run_revision(auditor_runner=refusal)
        self.assertEqual(result["status"], REVISION_STATUS_BLOCKED)
        self.assertEqual(result["auditor_decision"], "refuse")
        self.assertEqual(self.build_calls, [])
        self.assertTrue(result["revision_report_persisted"])

    def test_unsafe_directive_is_rejected_before_build(self) -> None:
        def unsafe(packet: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            response = _response(packet, directive=True)
            response["rebuild_directive"]["target"] = "modules/Registered_Module"
            return {"status": "success", "decision": "revise", "ok": True, "response": response}

        result = self.run_revision(auditor_runner=unsafe)
        self.assertEqual(result["status"], REVISION_STATUS_BLOCKED)
        self.assertEqual(self.build_calls, [])
        self.assertEqual(result["staging_targets"], [])

    def test_build_failure_leaves_stage_failed_and_no_publication_side_effect(self) -> None:
        protected = self.root / "modules" / "Registered_Module"
        protected.mkdir(parents=True, exist_ok=True)
        registry = self.root / "modules" / "world_registry.json"
        registry.write_text('{"modules":["Registered_Module"]}', encoding="utf-8")
        before = {path: path.read_bytes() for path in (protected, registry) if path.is_file()}

        def failure(staging_target: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            self.build_calls.append(copy.deepcopy(staging_target))
            return {"status": "failed", "failure_class": "semantic", "error": "semantic build failure"}

        result = self.run_revision(build_callback=failure)
        self.assertEqual(result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(result["staging_target"]["completion_state"], "failed")
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse(result["registry_mutated"])
        self.assertFalse(result["published"])

    def test_same_attempt_does_not_reuse_an_existing_revision_target(self) -> None:
        first = self.run_revision()
        self.assertEqual(first["status"], REVISION_STATUS_REVISION_PASSED)
        self.auditor_calls.clear()
        self.build_calls.clear()
        second = self.run_revision()
        self.assertEqual(second["status"], REVISION_STATUS_FAILED)
        self.assertEqual(self.auditor_calls, [])
        self.assertEqual(self.build_calls, [])
        self.assertEqual(second["diagnostics"][0]["code"], "revision_target_exists")

    def test_no_live_module_or_registry_path_is_accepted_as_target(self) -> None:
        result = self.run_revision(module_slug="Registered_Module")
        self.assertEqual(result["status"], REVISION_STATUS_REVISION_PASSED)
        self.assertNotIn("modules/", result["staging_target"]["path"])
        self.assertNotIn("world_registry.json", result["staging_target"]["path"])


class TestAdaptationRevisionExhaustion(RevisionFixture):
    """Task 5.5: explicit failed/blocked terminal status on revision budget
    exhaustion with zero registry, campaign, or completed-module side effect."""

    def _sentinel_snapshot(self) -> Dict[str, str]:
        """Hash registry/campaign sentinel fixtures and list the modules dir."""
        modules_dir = self.root / "modules"
        modules_dir.mkdir(parents=True, exist_ok=True)
        registry = modules_dir / "world_registry.json"
        campaign = modules_dir / "campaign.json"
        if not registry.exists():
            registry.write_text(
                json.dumps({"modules": ["Registered_Module"], "version": 1}, sort_keys=True),
                encoding="utf-8",
            )
        if not campaign.exists():
            campaign.write_text(
                json.dumps({"active_modules": ["Registered_Module"], "version": 1}, sort_keys=True),
                encoding="utf-8",
            )
        return {
            "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
            "campaign_sha256": hashlib.sha256(campaign.read_bytes()).hexdigest(),
            "module_entries": sorted(entry.name for entry in modules_dir.iterdir()),
        }

    def _failing_builder(
        self,
        failure_class: str = "semantic",
        *,
        switch_to: str = "",
    ) -> Callable[..., Dict[str, Any]]:
        calls = {"count": 0}

        def builder(staging_target: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            calls["count"] += 1
            self.build_calls.append(copy.deepcopy(staging_target))
            stage = self.root / staging_target["path"]
            stage.mkdir(parents=True, exist_ok=True)
            # Partial build evidence is retained in staging; it must never be
            # treated as a completed module.
            (stage / "module_context.json").write_text(
                json.dumps({"name": "partial", "status": "draft"}), encoding="utf-8"
            )
            effective_class = switch_to if (switch_to and calls["count"] > 1) else failure_class
            if effective_class == "semantic":
                return {
                    "status": "failed",
                    "failure_class": "semantic",
                    "revision_eligible": True,
                    "error": "semantic destination remains ambiguous",
                    "gate_results": {"semantic_authority": {"status": "blocked", "errors": ["ambiguous"]}},
                }
            return {
                "status": "failed",
                "failure_class": effective_class,
                "revision_eligible": True,
                "error": "publication or policy gate failed",
                "gate_results": {"registry_verification": {"status": "failed", "errors": ["registry missing"]}},
            }

        return builder

    def _assert_terminal_failed(self, result: Dict[str, Any]) -> None:
        self.assertEqual(result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(result["outcome"], REVISION_STATUS_FAILED)
        self.assertFalse(result["ok"])
        self.assertFalse(result["published"])
        self.assertFalse(result["publication_started"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(result["staging_targets"][-1]["completion_state"], "failed")

    def test_default_one_revision_exhaustion_is_explicit_failed(self) -> None:
        snapshot = self._sentinel_snapshot()
        result = self.run_revision(max_revisions=1, build_callback=self._failing_builder())
        self._assert_terminal_failed(result)
        self.assertEqual(result["diagnostics"][0]["code"], "revision_budget_exhausted")
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(result["max_revisions"], 1)
        self.assertEqual(result["revision_budget"]["remaining_revisions"], 0)
        self.assertTrue(result["semantic_revision_budget_consumed"])
        self.assertEqual(result["failure_classification"]["failure_class"], "semantic")
        self.assertEqual(result["failure_classification"]["revision_budget"]["decision"], "exhausted")
        # Exactly one revision was attempted; no accidental extra revision.
        self.assertEqual(len(self.build_calls), 1)
        self.assertEqual([item["revision_number"] for item in self.auditor_calls], [0])
        # Staging evidence is retained and marked failed, never completed.
        target = result["staging_target"]
        marker = self.root / target["path"] / "staging_metadata.json"
        self.assertTrue(marker.exists())
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["completion_state"], "failed")
        self.assertTrue((self.root / target["path"] / "module_context.json").exists())
        self.assertTrue(result["build_result_persisted"])
        self.assertTrue(result["failure_artifact_persisted"])
        self.assertTrue(result["revision_report_persisted"])
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_configured_two_revision_exhaustion_is_explicit_failed(self) -> None:
        snapshot = self._sentinel_snapshot()
        result = self.run_revision(max_revisions=2, build_callback=self._failing_builder())
        self._assert_terminal_failed(result)
        self.assertEqual(result["diagnostics"][0]["code"], "revision_budget_exhausted")
        self.assertEqual(result["revision_number"], 2)
        self.assertEqual(result["max_revisions"], 2)
        self.assertEqual(result["revision_budget"]["remaining_revisions"], 0)
        self.assertEqual([item["revision_number"] for item in self.build_calls], [1, 2])
        self.assertEqual(len(self.auditor_calls), 2)
        # Both staging targets are retained, distinct, and marked failed.
        self.assertEqual(len(result["staging_targets"]), 2)
        self.assertNotEqual(
            result["staging_targets"][0]["path"], result["staging_targets"][1]["path"]
        )
        for target in result["staging_targets"]:
            marker = self.root / target["path"] / "staging_metadata.json"
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["completion_state"], "failed")
        # Attempt artifacts for both revisions are retained.
        for revision in (1, 2):
            build_path = (
                self.root
                / "adaptation_attempts"
                / "adapt-001-auditor"
                / "revisions"
                / f"revision_{revision:03d}"
                / "build_result.json"
            )
            self.assertTrue(build_path.exists(), build_path)
        # History retains per-revision entries (initial failure, scheduled,
        # and failed entries) rather than collapsing back to the first entry.
        self.assertGreaterEqual(len(result["history"]), 4)
        self.assertEqual(result["history"][-1]["revision_number"], 2)
        self.assertEqual(result["history"][-1]["status"], "failed")
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_already_exhausted_packet_returns_explicit_failed_without_seams(self) -> None:
        snapshot = self._sentinel_snapshot()
        packet = copy.deepcopy(self.packet)
        packet["attempt_metadata"]["revision_number"] = 1
        packet["revision_number"] = 1
        result = run_adaptation_final_revision(
            packet,
            workspace=self.root,
            repo_root=self.root,
            staging_root="tmp/adaptation-staging",
            build_callback=self.builder,
            auditor_runner=self.auditor,
            current_dossier=self.dossier,
            max_revisions=1,
        )
        self.assertEqual(result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(result["diagnostics"][0]["code"], "revision_budget_exhausted")
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(self.auditor_calls, [])
        self.assertEqual(self.build_calls, [])
        self.assertEqual(result["staging_targets"], [])
        self.assertFalse(result["semantic_revision_budget_consumed"])
        self.assertFalse(result["module_builder_started"])
        self.assertFalse(result["published"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_refusal_is_blocked_with_revision_report_and_no_side_effect(self) -> None:
        snapshot = self._sentinel_snapshot()

        def refusal(_: Dict[str, Any], **__: Any) -> Dict[str, Any]:
            return {"status": "refused", "decision": "refuse", "reason": "not safe to revise"}

        result = self.run_revision(auditor_runner=refusal)
        self.assertEqual(result["status"], REVISION_STATUS_BLOCKED)
        self.assertEqual(result["outcome"], REVISION_STATUS_BLOCKED)
        self.assertEqual(result["auditor_decision"], "refuse")
        self.assertEqual(self.build_calls, [])
        self.assertEqual(result["staging_targets"], [])
        self.assertTrue(result["revision_report_persisted"])
        self.assertFalse(result["published"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_unsafe_directive_is_blocked_before_staging_and_no_side_effect(self) -> None:
        snapshot = self._sentinel_snapshot()

        def unsafe(packet: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            response = _response(packet, directive=True)
            response["rebuild_directive"]["target"] = "modules/Registered_Module"
            return {"status": "success", "decision": "revise", "ok": True, "response": response}

        result = self.run_revision(auditor_runner=unsafe)
        self.assertEqual(result["status"], REVISION_STATUS_BLOCKED)
        self.assertEqual(result["outcome"], REVISION_STATUS_BLOCKED)
        self.assertEqual(self.build_calls, [])
        self.assertEqual(result["staging_targets"], [])
        self.assertFalse(result["published"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_publication_failure_never_starts_an_extra_revision(self) -> None:
        snapshot = self._sentinel_snapshot()
        result = self.run_revision(
            max_revisions=2,
            build_callback=self._failing_builder("semantic", switch_to="publication"),
        )
        # Revision one failed semantically; revision two failed on a
        # publication gate. Publication is fail-closed and must not spend a
        # third revision even though the hard budget allowed two.
        self._assert_terminal_failed(result)
        self.assertEqual(result["diagnostics"][0]["code"], "revision_build_not_retryable")
        self.assertEqual(result["failure_classification"]["failure_class"], "publication")
        self.assertEqual(len(self.build_calls), 2)
        self.assertEqual(self._sentinel_snapshot(), snapshot)

    def test_rights_failure_never_starts_an_extra_revision(self) -> None:
        snapshot = self._sentinel_snapshot()
        result = self.run_revision(
            max_revisions=2,
            build_callback=self._failing_builder("semantic", switch_to="rights"),
        )
        self._assert_terminal_failed(result)
        self.assertEqual(result["diagnostics"][0]["code"], "revision_build_not_retryable")
        self.assertEqual(result["failure_classification"]["failure_class"], "rights")
        self.assertEqual(len(self.build_calls), 2)
        self.assertEqual(self._sentinel_snapshot(), snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
