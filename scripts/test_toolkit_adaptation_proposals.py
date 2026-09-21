# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Provider-free contract tests for task 6.3 adaptation proposal ledgers.
"""

from __future__ import annotations

import copy
import json
import shutil
import unittest
from pathlib import Path

from utils.toolkit_adaptation_authoring import run_adaptation_authoring
from utils.toolkit_adaptation_proposals import (
    PROPOSAL_APPROVAL_PATH,
    PROPOSAL_CONTEXT_UNAVAILABLE,
    PROPOSAL_STATUS_PENDING_APPROVAL,
    build_adaptation_proposal_ledger,
    get_adaptation_proposal_path,
    guard_adaptation_proposal_application,
    load_adaptation_proposal_ledger,
    parse_adaptation_proposal_ledger,
    persist_adaptation_proposal_ledger,
    prepare_adaptation_proposal_ledger,
    validate_adaptation_proposal_ledger,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_proposals_contract"
SOURCE_HASH = "a" * 64
WORLD_PROVENANCE = {
    "context_version": "toolkit_adaptation_world_context.v1",
    "context_status": "available",
    "fallback_status": "none",
    "world_seed_status": "available",
    "world_seed_version": "fixture.v2",
    "world_seed_hash": "b" * 64,
    "context_hash": "c" * 64,
    "selected_module": "Lantern_Market",
    "read_only": True,
    "provider_free": True,
    "raw_context_included": False,
    "canon_write_allowed": False,
    "registry_write_allowed": False,
    "mechanical_write_allowed": False,
}


def _fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _attempt() -> dict:
    return {
        "attempt_id": "adapt-001-proposals",
        "attempt_number": 1,
        "revision_number": 0,
        "source_title": "The Lantern Catalogue",
        "source_hash": SOURCE_HASH,
        "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
        "source_profile": "catalogue",
        "adaptation_mode": "llm_adaptation",
        "model_metadata": {
            "provider": "fixture",
            "model": "provider_free",
            "parameter_profile": "toolkit_adaptation_author",
        },
        "world_context_provenance": WORLD_PROVENANCE,
    }


class ProposalContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def test_schema_persistence_and_provenance_are_pending_only(self) -> None:
        ledger = build_adaptation_proposal_ledger(
            _fixture(),
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
            created_at="2026-08-04T12:00:00Z",
        )

        self.assertEqual(ledger["status"], PROPOSAL_STATUS_PENDING_APPROVAL)
        self.assertEqual(ledger["approval_status"], "pending")
        self.assertEqual(ledger["approval_path"], PROPOSAL_APPROVAL_PATH)
        self.assertTrue(ledger["approval_required"])
        self.assertFalse(ledger["auto_apply"])
        self.assertFalse(ledger["apply_allowed"])
        self.assertFalse(ledger["canon_write_allowed"])
        self.assertFalse(ledger["registry_write_allowed"])
        self.assertFalse(ledger["mechanical_write_allowed"])
        self.assertEqual(ledger["provenance"]["world_context_provenance"]["world_seed_version"], "fixture.v2")
        self.assertEqual(ledger["provenance"]["world_context_provenance"]["world_seed_hash"], "b" * 64)
        self.assertNotIn("campaign_model", json.dumps(ledger, sort_keys=True))
        self.assertTrue(validate_adaptation_proposal_ledger(ledger)["valid"])

        self.assertTrue(persist_adaptation_proposal_ledger(WORKSPACE, ledger))
        path = get_adaptation_proposal_path(WORKSPACE, ledger["attempt_id"])
        self.assertTrue(path.exists())
        self.assertEqual(load_adaptation_proposal_ledger(WORKSPACE, ledger["attempt_id"]), ledger)
        self.assertFalse(persist_adaptation_proposal_ledger(WORKSPACE, ledger))
        self.assertFalse(path.with_suffix(path.suffix + ".reserve").exists())

    def test_ids_are_deterministic_and_duplicate_or_large_inputs_are_bounded(self) -> None:
        first = _fixture()
        second = copy.deepcopy(first)
        first["world_narrative_hooks"] = [
            {"hook": "Hook %02d" % index, "relationship": "Thread %02d" % index}
            for index in range(12)
        ] + [first["world_narrative_hooks"][0]]
        first["continuity_hints"] = [
            {"hint": "Hint %02d" % index, "scope": "module_follow_up"}
            for index in range(12)
        ] + [first["continuity_hints"][0]]
        second["world_narrative_hooks"] = list(reversed(first["world_narrative_hooks"]))
        second["continuity_hints"] = list(reversed(first["continuity_hints"]))

        ledger_one = build_adaptation_proposal_ledger(
            first,
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
            created_at="2026-08-04T12:00:00Z",
        )
        ledger_two = build_adaptation_proposal_ledger(
            second,
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
            created_at="2026-08-04T12:00:00Z",
        )
        ids_one = sorted(item["proposal_id"] for item in ledger_one["proposals"])
        ids_two = sorted(item["proposal_id"] for item in ledger_two["proposals"])
        self.assertEqual(ids_one, ids_two)
        self.assertLessEqual(ledger_one["proposal_count"], 16)
        self.assertLessEqual(len(ledger_one["proposals"]), 16)
        self.assertEqual(len(ids_one), len(set(ids_one)))
        bounded = copy.deepcopy(first)
        bounded["world_narrative_hooks"][0]["hook"] = "Long hook " + ("x" * 900)
        bounded_ledger = build_adaptation_proposal_ledger(
            bounded,
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
            created_at="2026-08-04T12:00:00Z",
        )
        serialized = json.dumps(bounded_ledger, ensure_ascii=True, sort_keys=True)
        self.assertTrue(all(ord(char) < 128 for char in serialized))
        self.assertLessEqual(max(len(json.dumps(item)) for item in bounded_ledger["proposals"]), 2000)

    def test_unavailable_world_context_is_explicitly_degraded(self) -> None:
        unavailable = {
            "context_status": "fallback",
            "fallback_status": "seed_data_unavailable",
            "world_seed_status": "unavailable",
        }
        ledger = build_adaptation_proposal_ledger(
            _fixture(),
            attempt_metadata=_attempt(),
            world_context_provenance=unavailable,
            created_at="2026-08-04T12:00:00Z",
        )
        self.assertEqual(ledger["context_status"], PROPOSAL_CONTEXT_UNAVAILABLE)
        self.assertEqual(ledger["provenance"]["world_context_provenance"]["world_seed_status"], "unavailable")
        self.assertTrue(any(item["code"] == "proposal_context_degraded" for item in ledger["diagnostics"]))
        self.assertTrue(validate_adaptation_proposal_ledger(ledger)["valid"])

    def test_malformed_and_unsafe_fields_are_rejected(self) -> None:
        unsafe = _fixture()
        unsafe["world_narrative_hooks"][0]["target_path"] = "modules/Registered_Module"
        result = prepare_adaptation_proposal_ledger(
            unsafe,
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] in {"proposal_unsafe_field", "proposal_dossier_invalid"} for item in result["diagnostics"]))

        malformed = _fixture()
        malformed["continuity_hints"] = {"hint": "not a list"}
        result = prepare_adaptation_proposal_ledger(
            malformed,
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] in {"proposal_invalid", "proposal_dossier_invalid"} for item in result["diagnostics"]))

        direct_write = _fixture()
        direct_write["world_narrative_hooks"][0]["proposed_follow_up"] = "Write campaign.json now"
        with self.assertRaises(ValueError):
            build_adaptation_proposal_ledger(
                direct_write,
                attempt_metadata=_attempt(),
                world_context_provenance=WORLD_PROVENANCE,
            )

    def test_parse_and_application_guard_never_authorize_or_write(self) -> None:
        ledger = build_adaptation_proposal_ledger(
            _fixture(),
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
            created_at="2026-08-04T12:00:00Z",
        )
        parsed = parse_adaptation_proposal_ledger(json.dumps(ledger, ensure_ascii=True))
        self.assertTrue(parsed["valid"])
        before = sorted(path.relative_to(WORKSPACE).as_posix() for path in WORKSPACE.rglob("*"))
        decision = guard_adaptation_proposal_application(
            ledger,
            approval_record={"status": "approved", "approval_path": PROPOSAL_APPROVAL_PATH},
        )
        after = sorted(path.relative_to(WORKSPACE).as_posix() for path in WORKSPACE.rglob("*"))
        self.assertFalse(decision["approved"])
        self.assertFalse(decision["apply_allowed"])
        self.assertEqual(decision["status"], "approval_required")
        self.assertEqual(before, after)

    def test_persistence_cannot_target_live_module_or_registry_workspace(self) -> None:
        ledger = build_adaptation_proposal_ledger(
            _fixture(),
            attempt_metadata=_attempt(),
            world_context_provenance=WORLD_PROVENANCE,
        )
        protected = WORKSPACE / "modules" / "Registered_Module" / "module_context.json"
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text("sentinel", encoding="utf-8")
        registry = WORKSPACE / "modules" / "world_registry.json"
        registry.write_text("registry-sentinel", encoding="utf-8")
        campaign = WORKSPACE / "modules" / "campaign.json"
        campaign.write_text("campaign-sentinel", encoding="utf-8")
        before = {path: path.read_bytes() for path in (protected, registry, campaign)}

        self.assertTrue(persist_adaptation_proposal_ledger(WORKSPACE, ledger))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((WORKSPACE / "adaptation_attempts" / ledger["attempt_id"] / "module_context.json").exists())
        with self.assertRaises(ValueError):
            get_adaptation_proposal_path(REPO_ROOT / "modules", ledger["attempt_id"])

    def test_authoring_path_persists_pending_ledger_without_builder_or_publication(self) -> None:
        dossier = _fixture()
        source_context = {
            "source_title": dossier["source_title"],
            "source_hash": SOURCE_HASH,
            "source_ref": {
                "path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                "sha256": SOURCE_HASH,
            },
            "source_profile": "catalogue",
            "context_status": "referenced",
            "rights_class": "user_authored",
            "rights_basis": "Operator attested that the uploaded source is user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }

        def author_runner(*_args, **_kwargs):
            return {
                "ok": True,
                "dossier": copy.deepcopy(dossier),
                "provider": "fixture",
                "model": "provider_free",
            }

        result = run_adaptation_authoring(
            source_context,
            workspace=WORKSPACE / "authoring",
            job_id="proposal-authoring",
            model="provider_free",
            author_runner=author_runner,
            world_context=WORLD_PROVENANCE,
        )
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["proposal_ledger_persisted"])
        self.assertEqual(result["proposal_count"], 2)
        proposal_path = REPO_ROOT / result["proposal_ledger_path"]
        self.assertTrue(proposal_path.exists())
        proposal = load_adaptation_proposal_ledger(
            WORKSPACE / "authoring", result["attempt_id"]
        )
        self.assertEqual(proposal["approval_status"], "pending")
        self.assertFalse(result["module_builder_started"])
        self.assertFalse(result["publication_started"])
        self.assertFalse(result["registry_mutated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
