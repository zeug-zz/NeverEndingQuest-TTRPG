# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free production convergence failure and integrity contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Mapping

from utils.toolkit_adaptation_publication_convergence import (
    AdaptationConvergenceConfig,
    run_adaptation_publication_convergence,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from web.extensions.toolkit_adaptation_runtime import adaptation_convergence_callback


SOURCE_HASH = "a" * 64


class _FakeCompletions:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.completions = _FakeCompletions(outcome)
        self.chat = type("Chat", (), {"completions": self.completions})()


class AdaptationProviderSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir="tmp", prefix="adaptation_provider_safety_")
        self.root = Path(self.tmp.name)
        self.target = create_adaptation_staging_target(
            SOURCE_HASH,
            attempt_id="provider-safety",
            attempt_number=1,
            revision_number=1,
            module_slug="Provider_Safety",
            repo_root=self.root,
            staging_root="staging",
        )
        self.stage = self.root / self.target["path"]
        (self.stage / "module_context.json").write_text(
            json.dumps({"moduleName": "Provider_Safety", "sentinel": "staged"}),
            encoding="utf-8",
        )
        self.live = self.root / "modules" / "Provider_Safety"
        self.live.mkdir(parents=True)
        (self.live / "module_context.json").write_text('{"live": "unchanged"}', encoding="utf-8")
        self.registry = self.root / "modules" / "world_registry.json"
        self.registry.write_text('{"Provider_Safety": "registered"}', encoding="utf-8")
        self.campaign = self.root / "modules" / "campaign.json"
        self.campaign.write_text('{"active_module": "Provider_Safety"}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _context(self, *, current_attempt: int = 0) -> Dict[str, Any]:
        return {
            "contract_version": "toolkit_adaptation_publication_convergence.v1",
            "attempt_id": self.target["attempt_id"],
            "attempt_number": self.target["attempt_number"],
            "revision_number": self.target["revision_number"],
            "source_hash": SOURCE_HASH,
            "staging_identity": {
                "stage_id": self.target["stage_id"],
                "module_slug": self.target["module_slug"],
                "path": self.target["path"],
                "output_directory": self.target["output_directory"],
            },
            "budget": {
                "current_attempt": current_attempt,
                "max_attempts": 2,
                "max_operations_per_round": 3,
                "operation_timeout_seconds": 30,
            },
            "validation_context": {
                "status": "blocked",
                "repairable": True,
                "repair_requests": [{"code": "destination_alias"}],
                "source_reference_ids": ["source_manifest"],
                "canonical_location_ids": ["LOC01"],
                "authored_target_ids": [],
                "approved_monster_ids": [],
                "approved_monster_identities": ["Cave Guardian"],
                "monster_reference_keys": ["cave_guardians"],
                "quantity_bounds": {"cave_guardians": {"min": 1, "max": 2}},
                "topology": {"location_ids": ["LOC01"], "edges": []},
            },
        }

    def _adapter_callback(self, outcome: Any):
        def callback(context: Mapping[str, Any]) -> Dict[str, Any]:
            # The production convergence context is intentionally bounded.  A
            # repair request is injected here solely to exercise the provider
            # seam; no real provider or network is used by this test.
            provider_context = dict(context)
            provider_context["request"] = {"operation": "bounded_repair"}
            return adaptation_convergence_callback(
            provider_context,
            client=_FakeClient(outcome),
            parameter_resolver=lambda *_: {"model": "test-model"},
            )
        return callback

    def _snapshot(self) -> Dict[str, bytes]:
        paths = [self.registry, self.campaign]
        paths.extend(path for path in self.live.rglob("*") if path.is_file())
        paths.extend(
            path for path in self.stage.rglob("*")
            if path.is_file() and path.name != "adaptation_convergence_report.json"
        )
        return {str(path.relative_to(self.root)): path.read_bytes() for path in paths}

    def _run(self, callback, *, current_attempt: int = 0) -> Dict[str, Any]:
        return run_adaptation_publication_convergence(
            str(self.stage),
            mode="llm_adaptation",
            attempt_id=self.target["attempt_id"],
            attempt_number=self.target["attempt_number"],
            revision_number=self.target["revision_number"],
            source_hash=SOURCE_HASH,
            current_attempt=current_attempt,
            config=AdaptationConvergenceConfig(max_attempts=2),
            provider_callback=callback,
            validation_context=self._context(current_attempt=current_attempt)["validation_context"],
            repo_root=self.root,
        )

    def test_infrastructure_failures_are_bounded_and_retry_only_with_budget(self) -> None:
        cases = (
            (TimeoutError("provider timeout; api_key=sk-secret"), "timeout", True),
            (RuntimeError("429 quota exceeded; token=secret"), "quota", True),
            (RuntimeError("service unavailable"), "unavailable", True),
            ({"status": "malformed", "raw_response": "provider secret"}, "malformed", False),
            ({"status": "rejected", "reason_code": "invalid_operation"}, "rejected", False),
        )
        before = self._snapshot()
        for outcome, expected_class, retryable in cases:
            result = self._run(self._adapter_callback(outcome))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["provider_failure_class"], expected_class)
            self.assertEqual(result["next_revision_eligible"], retryable)
            self.assertEqual(result["attempt_id"], self.target["attempt_id"])
            self.assertEqual(result["revision_number"], self.target["revision_number"])
            self.assertEqual(result["source_hash"], SOURCE_HASH)
            report = json.loads((self.stage / "adaptation_convergence_report.json").read_text())
            encoded = json.dumps(report, sort_keys=True)
            self.assertLessEqual(len(encoded), 20_000)
            self.assertNotIn("sk-secret", encoded)
            self.assertNotIn("provider secret", encoded)
        self.assertEqual(before, self._snapshot())

        exhausted = self._run(self._adapter_callback(TimeoutError("timeout")), current_attempt=2)
        self.assertEqual(exhausted["reason_code"], "finalization_attempt_budget_exhausted")
        self.assertFalse(exhausted["next_revision_eligible"])

    def test_provider_boundary_uses_explicit_bounded_envelope_prompt(self) -> None:
        captured = _FakeClient(
            {
                "status": "success",
                "proposal": {"operation": "bounded_repair"},
            }
        )
        result = adaptation_convergence_callback(
            {**self._context(), "request": {"operation": "bounded_repair"}},
            client=captured,
            parameter_resolver=lambda *_: {"model": "test-model"},
        )
        self.assertEqual(result["status"], "success")
        call = captured.completions.calls[0]
        self.assertEqual(call["response_format"], {"type": "json_object"})
        prompt = call["messages"][0]["content"]
        self.assertIn('"status":"success","proposal":{"operation":"resolve_destination_alias"}', prompt)
        self.assertIn("only these top-level keys", prompt)
        self.assertIn("Do not add any other top-level key", prompt)
        self.assertIn("one operation only", prompt)

    def test_provider_envelope_rejects_extra_keys_and_unknown_statuses(self) -> None:
        for payload, diagnostic in (
            (
                {"status": "success", "proposal": {"operation": "bounded_repair"}, "extra": True},
                "provider_response_fields_invalid",
            ),
            (
                {"status": "pending", "proposal": {"operation": "bounded_repair"}},
                "provider_response_status_invalid",
            ),
        ):
            with self.subTest(payload=payload):
                result = adaptation_convergence_callback(
                    {**self._context(), "request": {"operation": "bounded_repair"}},
                    client=_FakeClient(payload),
                    parameter_resolver=lambda *_: {"model": "test-model"},
                )
                self.assertEqual(result["provider_failure_class"], "malformed")
                self.assertIn(diagnostic, result["diagnostics"])

    def test_dependency_initialization_is_non_retryable_and_live_state_is_unchanged(self) -> None:
        def missing_client() -> Any:
            raise ImportError("missing provider dependency")

        def callback(context: Mapping[str, Any]) -> Dict[str, Any]:
            provider_context = dict(context)
            provider_context["request"] = {"operation": "bounded_repair"}
            return adaptation_convergence_callback(
                provider_context,
                client_factory=missing_client,
                parameter_resolver=lambda *_: {"model": "test-model"},
            )
        before = self._snapshot()
        result = self._run(callback)
        self.assertEqual(result["provider_failure_class"], "unavailable")
        self.assertFalse(result["next_revision_eligible"])
        self.assertEqual(before, self._snapshot())

    def test_invalid_operation_stale_identity_and_unsupported_target_are_blocked(self) -> None:
        before = self._snapshot()

        def invalid_operation(context: Mapping[str, Any]) -> Dict[str, Any]:
            identity = {key: context[key] for key in ("attempt_id", "attempt_number", "revision_number", "source_hash", "staging_identity")}
            return {"status": "success", "proposal": {"operation": "not_allowlisted"}, **identity}

        result = self._run(invalid_operation)
        self.assertEqual(result["reason_code"], "finalization_proposal_rejected")
        self.assertEqual(result["provider_failure_class"], "rejected")
        self.assertFalse(result["next_revision_eligible"])

        def unsupported_target(context: Mapping[str, Any]) -> Dict[str, Any]:
            identity = {key: context[key] for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")}
            proposal = {
                "operation": "resolve_destination_alias",
                "identity": identity,
                "target": {
                    "location_id": "LOC999",
                    "origin_location_id": "LOC01",
                    "phrase": "unsupported target",
                },
                "source_references": ["source_manifest"],
                "confidence": 0.95,
                "replacement": "LOC999",
                "topology": {"location_ids": ["LOC01"], "edges": []},
            }
            return {"status": "success", "proposal": proposal, **identity, "staging_identity": context["staging_identity"]}

        result = self._run(unsupported_target)
        self.assertEqual(result["reason_code"], "finalization_proposal_rejected")
        self.assertFalse(result["next_revision_eligible"])

        def stale_identity(context: Mapping[str, Any]) -> Dict[str, Any]:
            return {"status": "success", "attempt_id": "stale-attempt", "attempt_number": context["attempt_number"], "revision_number": context["revision_number"], "source_hash": context["source_hash"], "staging_identity": context["staging_identity"]}

        result = self._run(stale_identity)
        self.assertEqual(result["reason_code"], "callback_identity_mismatched")
        self.assertFalse(result["next_revision_eligible"])
        self.assertEqual(before, self._snapshot())

    def test_no_legacy_fallback_and_staging_revision_identity_survive_failures(self) -> None:
        metadata_before = (self.stage / "staging_metadata.json").read_bytes()
        result = self._run(self._adapter_callback(RuntimeError("unsupported target")))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(metadata_before, (self.stage / "staging_metadata.json").read_bytes())
        self.assertFalse((self.live / "legacy_fallback.json").exists())
        self.assertEqual(result["attempt_number"], 1)
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(result["source_hash"], SOURCE_HASH)


if __name__ == "__main__":
    unittest.main()
