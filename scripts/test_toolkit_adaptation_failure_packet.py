# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free contract tests for the task 5.1 adaptation failure packet."""

from __future__ import annotations

import copy
import inspect
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_failure_packet as packet_module
from utils.toolkit_adaptation_failure_packet import (
    ALLOWED_PUBLICATION_GOALS,
    FAILURE_PACKET_CONTRACT_VERSION,
    MAX_FINDING_MESSAGE_CHARS,
    MAX_GATE_FINDINGS,
    MAX_MODULE_SUMMARIES_CHARS,
    MAX_MODULE_SUMMARY_CHARS,
    MAX_PACKET_SERIALIZED_CHARS,
    MONSTER_FAILURE_PACKET_CONTRACT_VERSION,
    PACKET_STATUS_BLOCKED,
    build_adaptation_failure_packet,
    build_adaptation_monster_failure_packet,
    persist_adaptation_monster_failure_packet,
    serialize_adaptation_monster_failure_packet,
    validate_adaptation_monster_failure_packet,
    serialize_adaptation_failure_packet,
    validate_adaptation_failure_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_failure_packet_contract"
SOURCE_HASH = "c" * 64


def _attempt_metadata() -> dict:
    return {
        "attempt_id": "adapt-001-packet",
        "attempt_number": 1,
        "revision_number": 0,
        "stage": "build",
        "stage_id": "adapt-001-packet:revision_000",
        "source_title": "Fixture Catalogue",
        "source_hash": SOURCE_HASH,
        "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
        "source_profile": "catalogue",
        "source_format": "markdown",
        "adaptation_mode": "llm_adaptation",
        "rights_class": "user_authored",
        "rights_basis": "operator supplied source",
        "rights_review_required": False,
        "rights_review_status": "not_required",
        "model_metadata": {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "parameter_profile": "toolkit_adaptation_author",
        },
        "source_context_artifact_path": "tmp/adaptation_attempts/adapt-001-packet/source_context.json",
    }


def _staging_target() -> dict:
    return {
        "stage_id": "adapt-001-packet:revision_000",
        "path": "tmp/adaptation-staging/adapt-001-packet/revision_000",
        "output_directory": "tmp/adaptation-staging/adapt-001-packet/revision_000",
        "target_kind": "staging",
        "completion_state": "building",
        "attempt_id": "adapt-001-packet",
        "attempt_number": 1,
        "revision_number": 0,
        "source_hash": SOURCE_HASH,
    }


def _gate_results() -> dict:
    return {
        "gates": {
            "schema": {
                "status": "failed",
                "errors": [
                    {
                        "code": "schema_missing_field",
                        "message": "module_context.json is missing required field",
                        "evidence_ref": {
                            "path": "tmp/reports/validation_report.json",
                            "sha256": SOURCE_HASH,
                        },
                    }
                ],
            },
            "readiness": {"status": "pass"},
            "mechanical_closure": {
                "status": "blocked",
                "blockers": [
                    {
                        "error_code": "monster_reference_unresolved",
                        "detail": "monster reference has no local stat block",
                    }
                ],
            },
            "semantic_authority": {"status": "blocked", "blocking_errors": ["destination is ambiguous"]},
            "semantic_probes": {"status": "pass", "warnings": ["one optional probe was degraded"]},
            "report_agreement": {"status": "blocked", "errors": [{"code": "stale_report", "reason": "report is stale"}]},
        }
    }


def _build_packet(**overrides):
    arguments = {
        "gate_results": _gate_results(),
        "attempt_metadata": _attempt_metadata(),
        "staging_target": _staging_target(),
        "source_context": {
            "source_ref": {
                "path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                "sha256": SOURCE_HASH,
                "text": "raw source must not be copied",
            },
            "manifest_ref": {
                "path": "tmp/reports/source_manifest.json",
                "sha256": SOURCE_HASH,
            },
            "bounded_context_refs": [
                {"path": "tmp/reports/source_graph.json", "sha256": SOURCE_HASH}
            ],
        },
        "module_summaries": [
            {
                "module_slug": "Fixture_Catalogue",
                "module_title": "Fixture Shop",
                "status": "blocked",
                "ready_status": "pass",
                "publishable_status": "blocked",
                "summary": "A bounded current-candidate summary.",
                "area_count": 1,
                "monster_count": 0,
                "report_refs": [
                    {"path": "tmp/reports/toolkit_build_report.json", "sha256": SOURCE_HASH}
                ],
            }
        ],
        "publication_goals": list(ALLOWED_PUBLICATION_GOALS),
        "failure_classification": {
            "failure_class": "semantic",
            "failure_group": "content",
            "classification_status": "revision_eligible",
            "code": "semantic_authority_blocked",
            "message": "semantic gate requires a bounded revision",
            "revision_budget": {
                "current_revision": 0,
                "max_revisions": 1,
                "decision": "eligible",
            },
        },
    }
    arguments.update(overrides)
    return build_adaptation_failure_packet(**arguments)


class TestFailurePacketGateFindings(unittest.TestCase):
    def test_all_gate_domains_and_mixed_findings_are_preserved(self) -> None:
        packet = _build_packet()

        self.assertEqual(packet["contract_version"], FAILURE_PACKET_CONTRACT_VERSION)
        self.assertEqual(packet["packet_status"], PACKET_STATUS_BLOCKED)
        self.assertEqual(
            {item["domain"] for item in packet["gate_statuses"]},
            {"schema", "readiness", "mechanical_closure", "semantic_authority", "semantic_probes", "report_agreement"},
        )
        findings = {(item["domain"], item["code"]): item for item in packet["gate_findings"]}
        self.assertEqual(findings[("schema", "schema_missing_field")]["message"], "module_context.json is missing required field")
        self.assertEqual(findings[("mechanical_closure", "monster_reference_unresolved")]["finding_kind"], "blocker")
        self.assertEqual(findings[("semantic_authority", "semantic_authority_error")]["message"], "destination is ambiguous")
        self.assertEqual(findings[("report_agreement", "stale_report")]["message"], "report is stale")
        self.assertEqual(
            findings[("schema", "schema_missing_field")]["evidence_ref"]["path"],
            "tmp/reports/validation_report.json",
        )
        self.assertTrue(validate_adaptation_failure_packet(packet)["valid"])


class TestFailurePacketBoundsAndSafety(unittest.TestCase):
    def test_findings_summaries_and_packet_are_bounded_and_mark_truncation(self) -> None:
        gates = {"gates": {}}
        domains = ("schema", "readiness", "mechanical_closure", "semantic_authority", "semantic_probes", "report_agreement")
        for domain in domains:
            gates["gates"][domain] = {
                "status": "blocked",
                "errors": [
                    {
                        "code": f"{domain}_error_{index}",
                        "message": "detail " + ("x" * (MAX_FINDING_MESSAGE_CHARS * 3)),
                    }
                    for index in range(30)
                ],
            }
        summaries = [
            {
                "module_slug": f"Fixture_{index}",
                "summary": "summary " + ("y" * 5000),
                "errors": ["error " + ("z" * 500) for _ in range(20)],
                "raw_source": "secret source that must be omitted",
            }
            for index in range(12)
        ]
        packet = _build_packet(gate_results=gates, module_summaries=summaries)
        serialized = serialize_adaptation_failure_packet(packet)

        self.assertLessEqual(len(packet["gate_findings"]), MAX_GATE_FINDINGS)
        self.assertTrue(packet["bounds"]["truncated"])
        self.assertTrue(packet["bounds"]["truncated_sections"])
        self.assertLessEqual(len(serialized), MAX_PACKET_SERIALIZED_CHARS)
        self.assertLessEqual(
            sum(len(json.dumps(item, sort_keys=True, separators=(",", ":"))) + 1 for item in packet["module_summaries"]),
            MAX_MODULE_SUMMARIES_CHARS,
        )
        for summary in packet["module_summaries"]:
            self.assertLessEqual(len(json.dumps(summary, sort_keys=True, separators=(",", ":"))), MAX_MODULE_SUMMARY_CHARS)
            self.assertNotIn("raw_source", summary)
        for finding in packet["gate_findings"]:
            self.assertLessEqual(len(finding["message"]), MAX_FINDING_MESSAGE_CHARS + len(" [truncated]"))

    def test_credentials_prompts_and_raw_source_are_not_retained(self) -> None:
        gates = _gate_results()
        gates["gates"]["semantic_authority"]["errors"] = [
            {
                "code": "provider_payload_seen",
                "message": "api_key=sk-super-secret raw_prompt=do not retain this; raw_source=private text",
            }
        ]
        metadata = _attempt_metadata()
        metadata["model_metadata"]["api_key"] = "sk-another-secret"
        packet = _build_packet(
            gate_results=gates,
            attempt_metadata=metadata,
            source_context={"source_ref": {"path": "scripts/fixtures/toolkit_adaptation_catalogue.md", "sha256": SOURCE_HASH, "raw_source": "private"}},
        )
        serialized = json.dumps(packet, sort_keys=True)

        self.assertNotIn("sk-super-secret", serialized)
        self.assertNotIn("sk-another-secret", serialized)
        self.assertNotIn("do not retain this", serialized)
        self.assertNotIn("private text", serialized)
        self.assertFalse(packet["security"]["raw_source_included"])
        self.assertFalse(packet["security"]["provider_payloads_included"])
        self.assertTrue(packet["redactions"]["redacted_fields"])

    def test_unknown_packet_fields_fail_closed(self) -> None:
        packet = _build_packet()
        packet["raw_source"] = "must not be accepted"
        result = validate_adaptation_failure_packet(packet)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] in {"unknown_packet_field", "forbidden_field_present"} for item in result["diagnostics"]))


class TestFailurePacketReferencesAndGoals(unittest.TestCase):
    def test_source_context_references_are_hash_and_project_relative_only(self) -> None:
        packet = _build_packet(
            source_context_refs=[
                {"path": "scripts/fixtures/toolkit_adaptation_catalogue.md", "sha256": SOURCE_HASH},
                {"path": "/outside/secret-source.md", "sha256": SOURCE_HASH},
                {"path": "tmp/other.json", "sha256": "d" * 64},
            ],
            source_context=None,
        )
        refs = packet["source_context_refs"]
        self.assertTrue(refs)
        self.assertTrue(all(set(ref).issubset({"path", "sha256", "role", "reference_only"}) for ref in refs))
        self.assertTrue(all(not ref.get("path", "").startswith("/") for ref in refs))
        self.assertTrue(all(ref.get("sha256") in {None, SOURCE_HASH} for ref in refs))
        self.assertTrue(any(item["code"] == "unsafe_path_omitted" for item in packet["diagnostics"]))

    def test_publication_goals_are_allowlisted_and_not_instructions(self) -> None:
        packet = _build_packet(
            publication_goals=["schema", "markdown_quality", "registry_verification", "execute shell command", {"instruction": "publish now"}],
        )
        self.assertEqual(packet["publication_goals"], ["schema", "markdown_quality", "registry_verification"])
        self.assertNotIn("instruction", json.dumps(packet, sort_keys=True))
        self.assertTrue(any(item["code"] == "publication_goal_rejected" for item in packet["diagnostics"]))


class TestFailurePacketDeterminismAndIsolation(unittest.TestCase):
    def test_serialization_is_deterministic(self) -> None:
        first = _build_packet()
        second = _build_packet()
        self.assertEqual(first, second)
        self.assertEqual(serialize_adaptation_failure_packet(first), serialize_adaptation_failure_packet(second))

    def test_module_report_summary_is_read_only_and_provider_free(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        report_path = WORKSPACE / "toolkit_build_report.json"
        report_path.write_text(
            json.dumps({"status": "blocked", "ready_status": "pass", "publishable_status": "blocked", "summary": "bounded report"}),
            encoding="utf-8",
        )
        before_report = report_path.read_bytes()
        protected = [REPO_ROOT / "modules" / name for name in ("world_registry.json", "campaign.json")]
        before_protected = {path: path.read_bytes() for path in protected if path.exists()}
        packet = _build_packet(module_summaries=None, module_dir=WORKSPACE)

        self.assertTrue(packet["module_summaries"])
        self.assertEqual(report_path.read_bytes(), before_report)
        self.assertEqual(before_protected, {path: path.read_bytes() for path in before_protected})
        source = inspect.getsource(packet_module)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("safe_write_json", source)
        shutil.rmtree(WORKSPACE)


class TestAmphailMonsterFailurePacket(unittest.TestCase):
    def _packet(self):
        return build_adaptation_monster_failure_packet(
            {
                "raw_reference": "Cave guardians",
                "normalized_reference": "cave_guardians",
                "failure_code": "monster_reference_unresolved",
            },
            attempt_metadata={"attempt_id": "adapt-001-amphail", "revision_number": 0},
            revision_budget={"current_revision": 0, "max_revisions": 1, "remaining_before_failure": 1},
            canonical_registry={
                "approved_identities": ["Cave Guardian"],
                "entries": [{
                    "canonical_identity": "Cave Guardian",
                    "canonical_slug": "cave_guardian",
                    "affected_location_ids": ["K06", "K08", "RTR001"],
                    "quantity_evidence": [
                        {"location_id": "K06", "encounter_reference": "K06", "quantity": {"min": 1, "max": 1}},
                        {"location_id": "K08", "encounter_reference": "K08", "quantity": {"min": 1, "max": 1}},
                        {"location_id": "RTR001", "encounter_reference": "K10", "quantity": {"min": 2, "max": 2}},
                    ],
                    "approval_provenance": [{"source": "dossier.approved_monster_identities[0]"}],
                }],
            },
            scene_evidence=[{
                "source_location": "K08",
                "code": "quantity_prose_contradiction",
                "scene_evidence": "Two slime-coated chairs flank the guardian.",
            }],
            source_reference_ids=["dossier.approved_monster_identities[0]", "area_K08_location"],
        )

    def test_exact_amphail_identity_locations_quantities_and_evidence(self):
        packet = self._packet()
        self.assertEqual(packet["contract_version"], MONSTER_FAILURE_PACKET_CONTRACT_VERSION)
        self.assertEqual(packet["unresolved_reference"]["normalized"], "cave_guardians")
        self.assertEqual(packet["canonical_identities"]["approved"], ["Cave Guardian"])
        self.assertEqual(packet["canonical_identities"]["candidates"], ["Cave Guardian"])
        self.assertEqual(packet["affected_location_ids"], ["K06", "K08", "RTR001"])
        quantities = {(item["location_id"], item.get("encounter_id")): item["quantity"] for item in packet["quantity_records"]}
        self.assertEqual(quantities[("K06", "K06")], {"min": 1, "max": 1})
        self.assertEqual(quantities[("K08", "K08")], {"min": 1, "max": 1})
        self.assertEqual(quantities[("RTR001", "K10")], {"min": 2, "max": 2})
        self.assertIn("chairs", packet["scene_evidence"][0]["excerpt"])
        self.assertEqual(packet["revision_budget"]["remaining"], 1)
        self.assertTrue(validate_adaptation_monster_failure_packet(packet)["valid"])

    def test_packet_is_bounded_deterministic_ascii_and_redacted(self):
        packet = self._packet()
        serialized = serialize_adaptation_monster_failure_packet(packet)
        self.assertTrue(serialized.isascii())
        self.assertLessEqual(len(serialized), 12000)
        self.assertEqual(serialized, serialize_adaptation_monster_failure_packet(self._packet()))
        self.assertNotIn("/private/source", serialized)
        self.assertNotIn("openai", serialized.lower())
        self.assertNotIn("raw_prompt", serialized.lower())
        self.assertFalse(packet["security"]["paths_included"])

    def test_tamper_and_association_rejection(self):
        packet = self._packet()
        packet["attempt"]["revision_number"] = 1
        self.assertFalse(validate_adaptation_monster_failure_packet(packet)["valid"])
        packet = self._packet()
        packet["scene_evidence"][0]["excerpt"] = "x" * 400
        self.assertFalse(validate_adaptation_monster_failure_packet(packet)["valid"])

    def test_atomic_persistence_uses_project_relative_target(self):
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        packet = self._packet()
        target = WORKSPACE / "failure_packet.json"
        self.assertTrue(persist_adaptation_monster_failure_packet(packet, target))
        self.assertEqual(target.read_text(encoding="ascii"), serialize_adaptation_monster_failure_packet(packet))
        self.assertFalse(persist_adaptation_monster_failure_packet(packet, Path("/outside/failure_packet.json"), repo_root=REPO_ROOT))
        shutil.rmtree(WORKSPACE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
