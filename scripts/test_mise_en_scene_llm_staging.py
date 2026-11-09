# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

#!/usr/bin/env python3
"""Provider-free tests for the isolated LLM staging study client."""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

from mise_en_scene.llm_staging import availability
from mise_en_scene.llm_staging.client import (
    AttemptReceipt,
    MODEL_ID,
    SCENE_ORDER,
    StagingClient,
    StagingError,
    TransportResult,
)
from mise_en_scene.llm_staging.output_gates import (
    extract_model_content,
    validate_model_output,
)
from mise_en_scene import contract as contract_module
from mise_en_scene import coverage as coverage_module
from mise_en_scene.llm_staging import client as client_module
from mise_en_scene.llm_staging import output_gates as output_gates_module


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging"
FROZEN_ROOT = REPO_ROOT / "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol"
MANIFEST_PATH = FROZEN_ROOT / "staging-manifest.json"
PROTOCOL_RELATIVE = "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.md"


def _reload_staging_modules() -> None:
    """Rebind after other suites reload the shared offline contract modules."""

    importlib.reload(contract_module)
    importlib.reload(coverage_module)
    importlib.reload(output_gates_module)
    importlib.reload(client_module)
    global AttemptReceipt, StagingClient, StagingError, TransportResult
    global extract_model_content, validate_model_output
    AttemptReceipt = client_module.AttemptReceipt
    StagingClient = client_module.StagingClient
    StagingError = client_module.StagingError
    TransportResult = client_module.TransportResult
    extract_model_content = output_gates_module.extract_model_content
    validate_model_output = output_gates_module.validate_model_output


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _valid_output(scene_index: int = 0) -> tuple[str, dict[str, object], dict[str, object], dict[str, object]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scene = manifest["scenes"][scene_index]
    scene_id = scene["scene_id"]
    expected = json.loads((REPO_ROOT / scene["expected_inputs_path"]).read_text(encoding="utf-8"))
    schema = json.loads((FROZEN_ROOT / "output-contract.schema.json").read_text(encoding="utf-8"))
    source_facts = expected["source_facts"]
    topology = expected["approved_topology"]
    coverage = expected["reference_coverage"]
    protected = expected["protected_unknowns"]
    module_id = topology["module_id"]
    node_map = {node["id"]: node for node in topology["nodes"]}
    role_by_entity = {
        entity_id: role
        for role, entity_ids in topology["stage_role_bindings"].items()
        for entity_id in entity_ids
    }
    fixed_anchors = [
        {
            "id": entity_id,
            "kind": topology["stage_role_entity_kinds"].get(
                role_by_entity.get(entity_id), node_map[entity_id]["kind"]
            ),
        }
        for entity_id in topology["fixed_anchor_ids"]
    ]
    mobile_occupants = [
        {"id": entity_id, "kind": node_map[entity_id]["kind"]}
        for entity_id in topology["mobile_occupant_ids"]
    ]
    scene_node_id = topology["scene_node_id"]
    facts: list[dict[str, object]] = []
    for source in source_facts["facts"]:
        value = source["value"]
        if type(value) not in (str, bool, int, float) and value is not None:
            continue
        facts.append({
            "id": source["fact_id"],
            "subject_id": scene_node_id,
            "predicate": "source_record",
            "object_id": scene_node_id,
            "status": "known",
            "value": value,
            "provenance": {"class": "source_extracted", "source_refs": [source["source_ref"]]},
        })

    relations: list[dict[str, object]] = []
    for ordinal, (name, predicate) in enumerate((
        ("approach_to_threshold", "approach_to_threshold"),
        ("threshold_to_focal", "threshold_to_focal"),
    ), start=1):
        expected_relation = coverage["stage_relations"][name]
        relations.append({
            "id": module_id + ":fact:stage-" + name,
            "subject_id": expected_relation["from_id"],
            "predicate": predicate,
            "object_id": expected_relation["to_id"],
            "status": "known",
            "value": "builder-authored initial staging relation %d" % ordinal,
            "provenance": {"class": "builder_authored", "source_refs": []},
        })
    facts.extend(relations)

    segment_texts = (
        "A connected room is the approach to the threshold.",
        "The threshold marks where this scene begins.",
        "The threshold leads the staged arrival toward the focal anchor.",
    )
    relation_for_segment = (relations[0], relations[0], relations[1])
    segments: list[dict[str, object]] = []
    claim_groups: list[dict[str, object]] = []
    for index, (role, text, relation) in enumerate(zip(
        ("approach", "threshold", "focal"), segment_texts, relation_for_segment
    )):
        segment_id = "arrival-" + role
        segments.append({
            "id": segment_id,
            "role": role,
            "text": text,
            "fact_ids": [relation["id"]],
        })
        claim_groups.append({
            "segment_id": segment_id,
            "claims": [{
                "id": "claim-%s" % role,
                "kind": "assertion",
                "fact_id": relation["id"],
                "predicate": relation["predicate"],
                "subject_id": relation["subject_id"],
                "object_id": relation["object_id"],
                "status": relation["status"],
                "value": relation["value"],
                "provenance": relation["provenance"],
                "span": text,
                "choice": None,
                "success": None,
            }],
        })

    unknown_provenance = {"class": "unknown", "source_refs": []}
    unknown_orientation = {"status": "unknown", "frame": None, "provenance": unknown_provenance}
    usable_space_id = topology["stage_role_bindings"]["usable_space"][0]
    fixture = {
        "schema_version": 1,
        "module_id": module_id,
        "topology_id": topology["topology_id"],
        "scene": {
            "id": scene_id,
            "scope": {"id": topology["scope_id"], "kind": "area"},
            "orientation": unknown_orientation,
        },
        "fixed_anchors": fixed_anchors,
        "initial_mobile_occupants": mobile_occupants,
        "facts": facts,
        "extension_seams": {
            "multi_cell_extents": [{
                "entity_id": usable_space_id,
                "status": "known",
                "schematic_cells": [[0, 0]],
                "reason": None,
            }],
            "stage_relations": [
                {
                    "fact_id": item["id"],
                    "from_id": item["subject_id"],
                    "predicate": item["predicate"],
                    "to_id": item["object_id"],
                    "status": item["status"],
                }
                for item in relations
            ],
            "unknown_metrics": protected["unknowns"],
            "audience_knowledge": [],
            "arrival_claims": [
                {"segment_id": group["segment_id"], "fact_ids": [claim["fact_id"] for claim in group["claims"]]}
                for group in claim_groups
            ],
        },
    }
    source_provenance = {
        "source_ref": source_facts["source_reference"],
        "path": source_facts["source_file"],
        "section": source_facts["source_packet_path"].rsplit("/", 1)[-1].removesuffix(".json"),
        "sha256": source_facts["source_file_sha256"],
        "source_kind": "published_module",
        "legacy_truth_verified": False,
    }
    arrival = {
        "fixture_id": scene_id,
        "topology": topology,
        "arrival_segments": segments,
        "source_provenance": source_provenance,
        "metadata": {
            "authorship": "builder_authored_initial_scene",
            "development_only": True,
            "held_out": False,
            "legacy_truth_verified": False,
            "llm_builder_tested": True,
        },
        "orientation": unknown_orientation,
        "cue_states": [
            {"cue": cue, "status": "unknown", "fact_id": None, "reason": "No independent gradient fact is supplied."}
            for cue in ("light", "sound", "weather")
        ],
        "next_section": {
            "status": "unknown",
            "from_scene_id": None,
            "to_scene_id": None,
            "transition_fact_id": None,
            "perception_fact_id": None,
            "provenance": unknown_provenance,
            "reason": "No independently approved transition is supplied.",
        },
        "claims": claim_groups,
    }
    return scene_id, expected, schema, {"schema": "neq.llm_staging_output.v1", "scene_id": scene_id, "fixture": fixture, "arrival": arrival}


class StagingClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Other provider-free suites reload these modules to exercise import
        # guards. Rebind this package to the current module objects afterward.
        _reload_staging_modules()
        cls.test_root = STAGING_ROOT / "test-runs"
        cls.test_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.test_root.rmdir()
        except OSError:
            pass

    def setUp(self) -> None:
        STAGING_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="staging-test-", dir=self.test_root)
        self.root = Path(self.temp_dir.name)
        self.study_ledger_path = self.root / "study-attempt-ledger.jsonl"
        self.ledger_path_patch = mock.patch.object(
            client_module, "STUDY_LEDGER_PATH", self.study_ledger_path
        )
        self.ledger_path_patch.start()
        self.availability_dir = self.root / "availability"
        self.approval_path = self.root / "execution-approval.json"
        self.run_root = self.root / "runs"
        self.network_guard = mock.patch.object(socket, "socket", side_effect=AssertionError("network socket used"))
        self.network_guard.start()

    def tearDown(self) -> None:
        self.network_guard.stop()
        self.ledger_path_patch.stop()
        self.temp_dir.cleanup()

    def _get_approval_path(self) -> Path:
        path = self.root / "availability-get-approval.json"
        path.write_text(json.dumps({
            "schema": "neq.openrouter_availability_get_approval.v1",
            "status": "APPROVED_REPLACEMENT_GET",
            "requested_model_id": MODEL_ID,
            "authorized_gets": 1,
            "approved_by": "overseer",
        }, sort_keys=True), encoding="ascii")
        return path

    def _confirmed_availability(self, model_id: str = MODEL_ID) -> Path:
        raw = json.dumps({"data": [{"id": model_id}]}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fetch_calls: list[str] = []

        def fake_fetch(url: str) -> tuple[int, bytes]:
            fetch_calls.append(url)
            return 200, raw

        with mock.patch.object(availability, "AVAILABILITY_DIR", self.availability_dir):
            result = availability.check_model_availability(
                self._get_approval_path(),
                fetch_once=fake_fetch,
                performed_utc="2026-11-09T00:00:00Z",
            )
        self.assertEqual(len(fetch_calls), 1)
        self.assertEqual(result["request_count"], 1)
        return self.availability_dir / "attestation.json"

    def _execution_approval(self) -> Path:
        manifest_bytes = MANIFEST_PATH.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        approval = {
            "schema": "neq.llm_staging_execution_approval.v1",
            "status": "APPROVED_STEP_B",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "protocol_sha256": manifest["artifacts"][PROTOCOL_RELATIVE],
            "approved_scene_ids": list(SCENE_ORDER),
            "generation_attempt_cap": 3,
            "approved_by": "overseer",
            "package_review": "PASS",
            "manual_lineage_review": "COMPLETE",
            "lineage_reviewed_scene_ids": list(SCENE_ORDER),
            "reviewed_source_packet_sha256": {
                row["scene_id"]: row["source_packet_sha256"]
                for row in manifest["scenes"]
            },
            "approved_at_utc": "2026-11-09T00:00:00Z",
        }
        self.approval_path.write_text(json.dumps(approval, sort_keys=True), encoding="ascii")
        return self.approval_path

    def _client(
        self,
        availability_path: Path,
        run_id: str = "test-run",
        run_root: Path | None = None,
        approval_path: Path | None = None,
    ) -> StagingClient:
        return StagingClient(
            run_id,
            availability_path,
            approval_path or self._execution_approval(),
            manifest_path=MANIFEST_PATH,
            run_root=run_root or self.run_root,
        )

    def test_frozen_package_is_tracked_and_runtime_root_is_only_created_for_tests(self) -> None:
        for name in (
            "scenes.json", "system-prompt.txt", "task-prompt.txt",
            "output-contract.schema.json", "generation-parameters.json",
            "availability-check-20261108.json", "staging-manifest.json",
        ):
            self.assertTrue((FROZEN_ROOT / name).is_file(), name)
        self.assertEqual(client_module.MANIFEST_PATH, FROZEN_ROOT / "staging-manifest.json")
        self.assertNotEqual(client_module.MANIFEST_PATH.parent, STAGING_ROOT)

    def test_clean_checkout_runtime_test_root_creates_missing_parent(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp_root:
            missing_test_root = Path(temp_root) / "router-rollout/mapping-pilot/staging-test-runs"
            missing_test_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.assertTrue(missing_test_root.is_dir())

    @staticmethod
    def _success_transport(_endpoint: str, _request: dict[str, object]) -> TransportResult:
        body = json.dumps({"id": "generation-test", "model": MODEL_ID}).encode("ascii")
        return TransportResult(
            http_status=200,
            body=body,
            returned_model_id=MODEL_ID,
            upstream_provider="OpenAI",
            generation_id="generation-test",
            usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        )

    def test_request_is_pinned_scene_local_and_has_no_secret_or_config_dependency(self) -> None:
        client = self._client(FROZEN_ROOT / "availability-check-20261108.json")
        request = client.build_request(SCENE_ORDER[0])
        self.assertEqual(request["model"], MODEL_ID)
        self.assertEqual(request["temperature"], 1.0)
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["provider"], {"allow_fallbacks": False})
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        self.assertNotIn("models", request)
        self.assertEqual([message["role"] for message in request["messages"]], ["system", "user"])
        prompt = request["messages"][1]["content"]
        self.assertIn(SCENE_ORDER[0], prompt)
        self.assertNotIn(SCENE_ORDER[1], prompt)
        self.assertNotIn(SCENE_ORDER[2], prompt)
        self.assertNotIn("owner:A", prompt)
        self.assertNotIn("Authorization", prompt)
        self.assertNotIn("OPENROUTER_API_KEY", prompt)
        self.assertNotIn("config", sys.modules)
        scene_record = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["scenes"][0]
        for key, prompt_marker in (
            ("source_packet_path", "APPROVED_SOURCE_PACKET:"),
            ("expected_inputs_path", "INDEPENDENT_EXPECTED_INPUTS:"),
        ):
            exact_contents = (REPO_ROOT / scene_record[key]).read_text(encoding="utf-8")
            self.assertIn(prompt_marker + "\n" + exact_contents, prompt)

    def test_changed_frozen_prompt_blocks_before_transport_dispatch(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        prompt_path = FROZEN_ROOT / "system-prompt.txt"
        original = prompt_path.read_bytes()
        calls: list[dict[str, object]] = []
        try:
            prompt_path.write_bytes(original + b"\nchanged")
            with self.assertRaisesRegex(StagingError, "frozen artifact hash changed"):
                client.send_once(SCENE_ORDER[0], lambda _endpoint, request: calls.append(request))
        finally:
            prompt_path.write_bytes(original)
        self.assertEqual(calls, [])
        self.assertFalse(client.run_dir.exists())

    def test_changed_expected_input_blocks_artifact_validation(self) -> None:
        availability_path = self._confirmed_availability()
        scene_id, _expected, _schema, output = _valid_output()
        content = _json_bytes(output).decode("ascii")
        provider_body = _json_bytes({
            "id": "generation-test",
            "model": MODEL_ID,
            "choices": [{"message": {"role": "assistant", "content": content}}],
        })
        client = self._client(availability_path)
        receipt = client.send_once(scene_id, lambda _endpoint, _request: TransportResult(
            http_status=200,
            body=provider_body,
            returned_model_id=MODEL_ID,
            upstream_provider="OpenAI",
            generation_id="generation-test",
            usage={"total_tokens": 300},
        ))
        expected_path = REPO_ROOT / client._scene(scene_id)["expected_inputs_path"]
        original = expected_path.read_bytes()
        try:
            expected_path.write_bytes(original + b"\nchanged")
            with self.assertRaisesRegex(StagingError, "frozen artifact hash changed"):
                client.validate_attempt(receipt)
        finally:
            expected_path.write_bytes(original)
        self.assertFalse((client.run_dir / "artifacts").exists())

    def test_frozen_expected_fact_ids_and_source_refs_fit_offline_contract(self) -> None:
        qualified_fact = re.compile(r"^[a-z][a-z0-9_-]{0,63}:fact:[a-z0-9][a-z0-9_-]{0,63}$")
        source_reference = re.compile(r"^source:[a-z0-9][a-z0-9._/-]{0,127}$")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for scene in manifest["scenes"]:
            expected_inputs = json.loads((REPO_ROOT / scene["expected_inputs_path"]).read_text(encoding="utf-8"))
            facts = expected_inputs["source_facts"]
            self.assertTrue(facts["guarded_content_markers"])
            self.assertLessEqual(len(facts["guarded_content_markers"]), 32)
            for fact in facts["facts"]:
                self.assertRegex(fact["fact_id"], qualified_fact)
                self.assertRegex(fact["source_ref"], source_reference)
            coverage = expected_inputs["reference_coverage"]
            self.assertEqual(set(coverage), {"schema_version", "stage_relations", "extents", "usable_spaces"})

    def test_output_schema_is_valid_and_enforces_arrival_role_order(self) -> None:
        scene_id, expected, schema, output = _valid_output()
        report = validate_model_output(_json_bytes(output), expected, scene_id, schema)
        self.assertEqual(report.deterministic_status, "PASS")
        self.assertEqual(report.scene_status, "BLOCKED")
        output["arrival"]["arrival_segments"][0]["role"] = "threshold"
        report = validate_model_output(_json_bytes(output), expected, scene_id, schema)
        self.assertEqual(report.deterministic_status, "FAIL")
        self.assertIn("OUTPUT_SCHEMA", {item.code for item in report.diagnostics})

    def test_unconfirmed_availability_blocks_before_transport_and_ledger(self) -> None:
        client = self._client(FROZEN_ROOT / "availability-check-20261108.json")
        calls: list[dict[str, object]] = []
        with self.assertRaisesRegex(StagingError, "availability"):
            client.send_once(SCENE_ORDER[0], lambda _endpoint, request: calls.append(request))
        self.assertEqual(calls, [])
        self.assertFalse(client.run_dir.exists())

    def test_one_successful_fake_dispatch_is_recorded_without_response_text(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        receipt = client.send_once(SCENE_ORDER[0], self._success_transport)
        self.assertEqual(receipt.outcome, "succeeded")
        self.assertEqual(receipt.returned_model_id, MODEL_ID)
        self.assertEqual(receipt.upstream_provider, "OpenAI")
        ledger = client.ledger_path.read_text(encoding="ascii")
        self.assertEqual(ledger.count('"event":"reservation"'), 1)
        self.assertEqual(ledger.count('"event":"result"'), 1)
        self.assertIn("generation-test", ledger)
        self.assertNotIn('"model":"openai/gpt-6-luna"', ledger)
        self.assertNotIn("OPENROUTER_API_KEY", ledger)
        self.assertEqual(os.stat(client.ledger_path).st_mode & 0o777, 0o600)
        response_path = STAGING_ROOT / receipt.response_path
        self.assertEqual(hashlib.sha256(response_path.read_bytes()).hexdigest(), receipt.response_sha256)

    def test_forged_receipt_identity_cannot_rebind_a_saved_response(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        receipt = client.send_once(SCENE_ORDER[0], self._success_transport)
        forged = AttemptReceipt(
            scene_id=receipt.scene_id,
            attempt_number=receipt.attempt_number,
            outcome=receipt.outcome,
            response_path=receipt.response_path,
            response_sha256=receipt.response_sha256,
            returned_model_id=receipt.returned_model_id,
            upstream_provider=receipt.upstream_provider,
            generation_id="forged-generation-id",
            usage=receipt.usage,
        )
        with self.assertRaisesRegex(StagingError, "not bound"):
            client.validate_attempt(forged)

    def test_fake_transport_output_is_saved_then_deterministically_checked(self) -> None:
        availability_path = self._confirmed_availability()
        scene_id, _expected, _schema, output = _valid_output()
        model_content = _json_bytes(output).decode("ascii")
        provider_body = _json_bytes({
            "id": "generation-test",
            "model": MODEL_ID,
            "choices": [{"message": {"role": "assistant", "content": model_content}}],
        })
        client = self._client(availability_path)
        receipt = client.send_once(scene_id, lambda _endpoint, _request: TransportResult(
            http_status=200,
            body=provider_body,
            returned_model_id=MODEL_ID,
            upstream_provider="OpenAI",
            generation_id="generation-test",
            usage={"total_tokens": 300},
        ))
        report = client.validate_attempt(receipt)
        self.assertEqual(report.deterministic_status, "PASS")
        self.assertEqual(report.semantic_review_status, "PENDING")
        self.assertEqual(report.owner_rating_status, "PENDING")
        self.assertEqual(report.scene_status, "BLOCKED")
        artifact = next((client.run_dir / "artifacts").glob("*.json"))
        gate_report = next((client.run_dir / "gates").glob("*.json"))
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), report.artifact_sha256)
        self.assertNotIn("A connected room is the approach", gate_report.read_text(encoding="ascii"))

    def test_failed_transport_consumes_attempt_and_never_retries_same_scene(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        calls = 0

        def failing_transport(_endpoint: str, _request: dict[str, object]) -> TransportResult:
            nonlocal calls
            calls += 1
            raise RuntimeError("SECRET-DO-NOT-LOG")

        with self.assertRaisesRegex(StagingError, "allocation consumed"):
            client.send_once(SCENE_ORDER[0], failing_transport)
        self.assertEqual(calls, 1)
        ledger = client.ledger_path.read_text(encoding="ascii")
        self.assertIn('"failure_reason":"transport_exception"', ledger)
        self.assertNotIn("SECRET-DO-NOT-LOG", ledger)
        with self.assertRaisesRegex(StagingError, "out of approved order"):
            client.send_once(SCENE_ORDER[0], failing_transport)
        self.assertEqual(calls, 1)

    def test_wrong_returned_model_is_counted_and_stops_later_scenes(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        wrong = TransportResult(
            http_status=200,
            body=b"{}",
            returned_model_id="openai/gpt-6-luna-pro",
            upstream_provider="OpenAI",
            generation_id="generation-wrong-model",
            usage={"total_tokens": 1},
        )
        with self.assertRaisesRegex(StagingError, "identity failed"):
            client.send_once(SCENE_ORDER[0], lambda _endpoint, _request: wrong)
        calls: list[dict[str, object]] = []
        with self.assertRaisesRegex(StagingError, "scene allocation"):
            client.send_once(SCENE_ORDER[1], lambda _endpoint, request: calls.append(request))
        self.assertEqual(calls, [])

    def test_three_attempts_are_allocated_once_in_approved_order(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        sent: list[str] = []

        def transport(_endpoint: str, request: dict[str, object]) -> TransportResult:
            prompt = request["messages"][1]["content"]
            scene_id = next(value for value in SCENE_ORDER if value in prompt)
            sent.append(scene_id)
            return self._success_transport(_endpoint, request)

        for scene_id in SCENE_ORDER:
            client.send_once(scene_id, transport)
        self.assertEqual(sent, list(SCENE_ORDER))
        ledger = [json.loads(line) for line in client.ledger_path.read_text(encoding="ascii").splitlines()]
        reservations = [row for row in ledger if row["event"] == "reservation"]
        self.assertEqual([row["scene_id"] for row in reservations], list(SCENE_ORDER))
        calls: list[dict[str, object]] = []
        with self.assertRaisesRegex(StagingError, "exhausted"):
            client.send_once(SCENE_ORDER[-1], lambda _endpoint, request: calls.append(request))
        self.assertEqual(calls, [])

    def test_new_run_id_or_run_root_cannot_reset_study_allocation(self) -> None:
        availability_path = self._confirmed_availability()
        for identity_change in ("run_id", "run_root"):
            with self.subTest(identity_change=identity_change):
                ledger_path = self.root / (identity_change + "-ledger.jsonl")
                first_run_root = self.root / (identity_change + "-runs")
                with mock.patch.object(client_module, "STUDY_LEDGER_PATH", ledger_path):
                    first = self._client(
                        availability_path,
                        run_root=first_run_root,
                    )
                    first.send_once(SCENE_ORDER[0], self._success_transport)
                    if identity_change == "run_id":
                        replacement = self._client(
                            availability_path,
                            run_id="replacement-run",
                            run_root=first_run_root,
                        )
                    else:
                        replacement = self._client(
                            availability_path,
                            run_root=self.root / "alternate-runs",
                        )
                    calls: list[dict[str, object]] = []
                    with self.assertRaisesRegex(StagingError, "another run identity"):
                        replacement.send_once(
                            SCENE_ORDER[1],
                            lambda _endpoint, request: calls.append(request),
                        )
                    self.assertEqual(calls, [])
                    self.assertFalse(replacement.run_dir.exists())

    def test_changed_execution_approval_cannot_rebind_study(self) -> None:
        availability_path = self._confirmed_availability()
        approval_path = self._execution_approval()
        first = self._client(availability_path, approval_path=approval_path)
        first.send_once(SCENE_ORDER[0], self._success_transport)

        alternate_approval_path = self.root / "alternate-execution-approval.json"
        approval = json.loads(approval_path.read_text(encoding="ascii"))
        alternate_approval_path.write_text(
            json.dumps(approval, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        self.assertNotEqual(approval_path.read_bytes(), alternate_approval_path.read_bytes())
        alternate = self._client(availability_path, approval_path=alternate_approval_path)
        calls: list[dict[str, object]] = []
        with self.assertRaisesRegex(StagingError, "another run identity"):
            alternate.send_once(
                SCENE_ORDER[1],
                lambda _endpoint, request: calls.append(request),
            )
        self.assertEqual(calls, [])

    def test_concurrent_clients_share_one_pending_reservation(self) -> None:
        availability_path = self._confirmed_availability()
        clients = [self._client(availability_path), self._client(availability_path)]
        start_together = threading.Barrier(3)
        transport_entered = threading.Event()
        release_transport = threading.Event()
        worker_result: list[object] = []
        result_lock = threading.Lock()
        first_worker_finished = threading.Event()
        finished_count = 0
        dispatches: list[int] = []

        def blocking_transport(_endpoint: str, _request: dict[str, object]) -> TransportResult:
            dispatches.append(1)
            transport_entered.set()
            if not release_transport.wait(timeout=5):
                raise RuntimeError("test transport release timed out")
            return self._success_transport(_endpoint, _request)

        def run_client(client: StagingClient) -> None:
            nonlocal finished_count
            start_together.wait(timeout=5)
            try:
                worker_result.append(client.send_once(SCENE_ORDER[0], blocking_transport))
            except BaseException as exc:
                worker_result.append(exc)
            finally:
                with result_lock:
                    finished_count += 1
                    if finished_count == 1:
                        first_worker_finished.set()

        workers = [threading.Thread(target=run_client, args=(client,)) for client in clients]
        for worker in workers:
            worker.start()
        start_together.wait(timeout=5)
        self.assertTrue(transport_entered.wait(timeout=5))
        try:
            self.assertTrue(first_worker_finished.wait(timeout=5))
        finally:
            release_transport.set()
            for worker in workers:
                worker.join(timeout=5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(dispatches, [1])
        self.assertEqual(len(worker_result), 2)
        self.assertEqual(sum(isinstance(item, AttemptReceipt) for item in worker_result), 1)
        self.assertEqual(sum(isinstance(item, StagingError) for item in worker_result), 1)

    def test_interrupted_reservation_blocks_same_and_alternate_clients(self) -> None:
        class SimulatedInterruption(BaseException):
            pass

        availability_path = self._confirmed_availability()
        client = self._client(availability_path)

        def interrupt_transport(_endpoint: str, _request: dict[str, object]) -> TransportResult:
            raise SimulatedInterruption()

        with self.assertRaises(SimulatedInterruption):
            client.send_once(SCENE_ORDER[0], interrupt_transport)
        records = [json.loads(line) for line in client.ledger_path.read_text(encoding="ascii").splitlines()]
        self.assertEqual([row["event"] for row in records], ["header", "reservation"])

        same_identity = self._client(availability_path)
        with self.assertRaisesRegex(StagingError, "pending"):
            same_identity.send_once(SCENE_ORDER[1], self._success_transport)
        alternate = self._client(
            availability_path,
            run_id="after-interruption",
            run_root=self.root / "alternate-runs",
        )
        with self.assertRaisesRegex(StagingError, "another run identity"):
            alternate.send_once(SCENE_ORDER[0], self._success_transport)

    def test_corrupt_study_ledger_blocks_before_transport(self) -> None:
        availability_path = self._confirmed_availability()
        client = self._client(availability_path)
        client.ledger_path.write_bytes(b"{broken-ledger\n")
        calls: list[dict[str, object]] = []
        with self.assertRaisesRegex(StagingError, "malformed"):
            client.send_once(
                SCENE_ORDER[0],
                lambda _endpoint, request: calls.append(request),
            )
        self.assertEqual(calls, [])
        self.assertFalse(client.run_dir.exists())

    def test_missing_receipt_identity_or_usage_is_preserved_failed_and_stops_study(self) -> None:
        availability_path = self._confirmed_availability()
        raw_body = b'{"data":"PRIVATE-RAW-RESPONSE"}'
        cases = (
            ("returned_model_id", None, "returned_model_id_missing_or_invalid"),
            ("upstream_provider", None, "upstream_provider_missing_or_invalid"),
            ("generation_id", None, "generation_id_missing_or_invalid"),
            ("usage", None, "usage_receipt_missing_or_invalid"),
        )
        for field, missing_value, expected_reason in cases:
            with self.subTest(field=field):
                ledger_path = self.root / ("missing-" + field + "-ledger.jsonl")
                run_root = self.root / ("missing-" + field + "-runs")
                with mock.patch.object(client_module, "STUDY_LEDGER_PATH", ledger_path):
                    client = self._client(
                        availability_path,
                        run_id="missing-" + field,
                        run_root=run_root,
                    )
                    result_fields: dict[str, object] = {
                        "http_status": 200,
                        "body": raw_body,
                        "returned_model_id": MODEL_ID,
                        "upstream_provider": "OpenAI",
                        "generation_id": "generation-test",
                        "usage": {"total_tokens": 1},
                    }
                    result_fields[field] = missing_value
                    bad_result = TransportResult(**result_fields)
                    dispatches: list[int] = []

                    def one_dispatch(_endpoint: str, _request: dict[str, object]) -> TransportResult:
                        dispatches.append(1)
                        return bad_result

                    with self.assertRaisesRegex(StagingError, "receipt failed validation"):
                        client.send_once(SCENE_ORDER[0], one_dispatch)
                    self.assertEqual(dispatches, [1])
                    records = [
                        json.loads(line)
                        for line in client.ledger_path.read_text(encoding="ascii").splitlines()
                    ]
                    result_record = next(row for row in records if row["event"] == "result")
                    self.assertEqual(result_record["outcome"], "failed")
                    self.assertTrue(result_record["stop_run"])
                    self.assertEqual(result_record["failure_reason"], expected_reason)
                    self.assertEqual(
                        (STAGING_ROOT / result_record["response_path"]).read_bytes(),
                        raw_body,
                    )
                    self.assertEqual(
                        result_record["response_sha256"],
                        hashlib.sha256(raw_body).hexdigest(),
                    )
                    ledger_text = client.ledger_path.read_text(encoding="ascii")
                    self.assertNotIn("PRIVATE-RAW-RESPONSE", ledger_text)
                    self.assertNotIn("SECRET", ledger_text)
                    later_calls: list[dict[str, object]] = []
                    with self.assertRaisesRegex(StagingError, "scene allocation"):
                        client.send_once(
                            SCENE_ORDER[1],
                            lambda _endpoint, request: later_calls.append(request),
                        )
                    self.assertEqual(later_calls, [])

    def test_availability_check_makes_one_mock_get_and_refuses_a_second(self) -> None:
        authority = self._get_approval_path()
        raw = json.dumps({"data": [{"id": MODEL_ID}]}, separators=(",", ":")).encode("ascii")
        calls: list[str] = []

        def fake_fetch(url: str) -> tuple[int, bytes]:
            calls.append(url)
            return 200, raw

        with mock.patch.object(availability, "AVAILABILITY_DIR", self.availability_dir):
            result = availability.check_model_availability(authority, fetch_once=fake_fetch, performed_utc="2026-11-09T00:00:00Z")
            self.assertEqual(result["verdict"], "CONFIRMED")
            self.assertEqual(result["raw_listing_sha256"], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(availability.AvailabilityCheckError, "refusing a second GET"):
                availability.check_model_availability(authority, fetch_once=fake_fetch, performed_utc="2026-11-09T00:00:01Z")
        self.assertEqual(calls, [availability.MODEL_LIST_URL])

    def test_availability_check_requires_exact_id_and_explicit_authority(self) -> None:
        raw = json.dumps({"data": [{"id": "openai/gpt-6-luna-pro"}]}).encode("ascii")
        with mock.patch.object(availability, "AVAILABILITY_DIR", self.availability_dir):
            result = availability.check_model_availability(
                self._get_approval_path(),
                fetch_once=lambda _url: (200, raw),
                performed_utc="2026-11-09T00:00:00Z",
            )
        self.assertEqual(result["verdict"], "UNCONFIRMED")
        self.assertFalse(result["exact_model_id_present"])

        other_dir = self.root / "blocked"
        with mock.patch.object(availability, "AVAILABILITY_DIR", other_dir):
            calls: list[str] = []
            with self.assertRaisesRegex(availability.AvailabilityCheckError, "explicit Overseer authority"):
                availability.check_model_availability(self.root / "missing-approval.json", fetch_once=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_failed_availability_dispatch_is_durably_consumed(self) -> None:
        calls: list[str] = []

        def failed_fetch(url: str) -> tuple[int, bytes]:
            calls.append(url)
            raise OSError("transport failure")

        with mock.patch.object(availability, "AVAILABILITY_DIR", self.availability_dir):
            with self.assertRaisesRegex(availability.AvailabilityCheckError, "no retry"):
                availability.check_model_availability(self._get_approval_path(), fetch_once=failed_fetch)
            with self.assertRaisesRegex(availability.AvailabilityCheckError, "refusing a second GET"):
                availability.check_model_availability(self._get_approval_path(), fetch_once=failed_fetch)
        self.assertEqual(calls, [availability.MODEL_LIST_URL])
        reservation = json.loads((self.availability_dir / "get-reservation.json").read_text(encoding="ascii"))
        self.assertEqual(reservation["reservation_status"], "CONSUMED_BEFORE_DISPATCH")

    def test_client_and_tests_do_not_import_config_or_provider_sdk(self) -> None:
        client_source = (REPO_ROOT / "scripts/mise_en_scene/llm_staging/client.py").read_text(encoding="ascii")
        availability_source = (REPO_ROOT / "scripts/mise_en_scene/llm_staging/availability.py").read_text(encoding="ascii")
        test_source = Path(__file__).read_text(encoding="ascii")
        self.assertNotIn("import config", client_source)
        self.assertNotIn("from config", client_source)
        self.assertNotIn("import config", availability_source)
        self.assertNotIn("import httpx", client_source)
        self.assertNotIn("import openai", client_source)
        self.assertNotRegex(client_source, r"(?m)^\s*(?:from|import)\s+(?:urllib|requests|socket)(?:\s|\.)")
        self.assertNotRegex(test_source, r"(?m)^\s*(?:from|import)\s+config(?:\s|\.)")
        self.assertNotRegex(test_source, r"(?m)^\s*(?:from|import)\s+(?:openai|httpx)(?:\s|\.)")
        self.assertNotIn("config", sys.modules)
        self.assertIs(
            inspect.signature(StagingClient.send_once).parameters["transport"].default,
            inspect.Parameter.empty,
        )


class OutputGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reload_staging_modules()

    def setUp(self) -> None:
        self.scene_id, self.expected, self.schema, self.output = _valid_output()
        self.network_guard = mock.patch.object(socket, "socket", side_effect=AssertionError("network socket used"))
        self.network_guard.start()

    def tearDown(self) -> None:
        self.network_guard.stop()

    def _validate(self, output: object | None = None, raw: bytes | None = None):
        contents = raw if raw is not None else _json_bytes(self.output if output is None else output)
        return validate_model_output(contents, self.expected, self.scene_id, self.schema)

    def test_valid_synthetic_output_passes_deterministic_gates_only(self) -> None:
        report = self._validate()
        self.assertEqual(report.deterministic_status, "PASS")
        self.assertEqual(report.semantic_review_status, "PENDING")
        self.assertEqual(report.owner_rating_status, "PENDING")
        self.assertEqual(report.scene_status, "BLOCKED")
        self.assertEqual(report.diagnostics, ())
        result = report.to_dict()
        self.assertNotIn("owner_rating", result)
        self.assertNotIn("legibility", result)
        self.assertNotIn("usefulness", result)

    def test_each_approved_scene_has_a_provider_free_synthetic_gate_pass(self) -> None:
        for scene_index in range(len(SCENE_ORDER)):
            scene_id, expected, schema, output = _valid_output(scene_index)
            report = validate_model_output(_json_bytes(output), expected, scene_id, schema)
            self.assertEqual(report.deterministic_status, "PASS", scene_id)
            self.assertEqual(report.scene_status, "BLOCKED", scene_id)

    def test_duplicate_keys_and_nonfinite_numbers_are_invalid_json(self) -> None:
        duplicate = b'{"schema":"neq.llm_staging_output.v1","schema":"bad"}'
        report = self._validate(raw=duplicate)
        self.assertIn("OUTPUT_JSON_INVALID", {item.code for item in report.diagnostics})
        nonfinite = b'{"schema":"neq.llm_staging_output.v1","number":1e999}'
        report = self._validate(raw=nonfinite)
        self.assertIn("OUTPUT_JSON_INVALID", {item.code for item in report.diagnostics})
        deeply_nested = b'{"x":' + (b"[" * 1200) + b"0" + (b"]" * 1200) + b"}"
        report = self._validate(raw=deeply_nested)
        self.assertNotEqual(report.deterministic_status, "PASS")

    def test_schema_failure_paths_do_not_echo_untrusted_property_names(self) -> None:
        output = copy.deepcopy(self.output)
        output["SECRET-DO-NOT-LOG"] = "untrusted"
        report = self._validate(output=output)
        self.assertIn("OUTPUT_SCHEMA", {item.code for item in report.diagnostics})
        self.assertNotIn("SECRET-DO-NOT-LOG", " ".join(item.path for item in report.diagnostics))

    def test_unsupported_schema_fails_closed(self) -> None:
        schema = copy.deepcopy(self.schema)
        schema["unknownSchemaKeyword"] = True
        report = validate_model_output(_json_bytes(self.output), self.expected, self.scene_id, schema)
        self.assertEqual(report.deterministic_status, "BLOCKED")
        self.assertIn("OUTPUT_SCHEMA_INVALID", {item.code for item in report.diagnostics})

    def test_topology_and_anchor_set_cannot_change(self) -> None:
        output = copy.deepcopy(self.output)
        output["arrival"]["topology"]["nodes"].append({"id": "invented", "kind": "feature"})
        report = self._validate(output=output)
        self.assertIn("APPROVED_TOPOLOGY_CHANGED", {item.code for item in report.diagnostics})

        output = copy.deepcopy(self.output)
        output["fixture"]["fixed_anchors"][0]["id"] = self.scene_id
        report = self._validate(output=output)
        self.assertIn("FIXED_ANCHOR_SET_MISMATCH", {item.code for item in report.diagnostics})

    def test_positional_coverage_detects_missing_relation(self) -> None:
        output = copy.deepcopy(self.output)
        output["fixture"]["facts"] = [
            fact for fact in output["fixture"]["facts"]
            if fact["predicate"] != "approach_to_threshold"
        ]
        report = self._validate(output=output)
        self.assertIn("MISSING_RELATION", {item.code for item in report.diagnostics})

    def test_protected_unknowns_cannot_be_changed_or_promoted(self) -> None:
        output = copy.deepcopy(self.output)
        output["fixture"]["extension_seams"]["unknown_metrics"][0]["status"] = "known"
        report = self._validate(output=output)
        self.assertIn("PROTECTED_UNKNOWNS_CHANGED", {item.code for item in report.diagnostics})

        output = copy.deepcopy(self.output)
        module_id = output["fixture"]["module_id"]
        scene_node_id = output["fixture"]["scene"]["id"].replace(":scene:", ":entity:")
        output["fixture"]["facts"].append({
            "id": module_id + ":fact:invented-distance",
            "subject_id": scene_node_id,
            "predicate": "distance",
            "object_id": scene_node_id,
            "status": "known",
            "value": 10,
            "provenance": {"class": "builder_authored", "source_refs": []},
        })
        report = self._validate(output=output)
        self.assertIn("PROTECTED_UNKNOWN_PROMOTED", {item.code for item in report.diagnostics})

    def test_guarded_source_fact_cannot_be_bound_to_public_arrival(self) -> None:
        output = copy.deepcopy(self.output)
        source_rows = self.expected["source_facts"]["facts"]
        guarded = next(
            row for row in source_rows
            if row["audience"] == "gm_guarded" and type(row["value"]) is str and row["value"]
        )
        candidate_fact = next(
            fact for fact in output["fixture"]["facts"] if fact["id"] == guarded["fact_id"]
        )
        segment = output["arrival"]["arrival_segments"][2]
        claim_group = output["arrival"]["claims"][2]
        segment["text"] = guarded["value"]
        segment["fact_ids"] = [candidate_fact["id"]]
        claim_group["claims"] = [{
            "id": "claim-guarded",
            "kind": "assertion",
            "fact_id": candidate_fact["id"],
            "predicate": candidate_fact["predicate"],
            "subject_id": candidate_fact["subject_id"],
            "object_id": candidate_fact["object_id"],
            "status": candidate_fact["status"],
            "value": candidate_fact["value"],
            "provenance": candidate_fact["provenance"],
            "span": guarded["value"],
            "choice": None,
            "success": None,
        }]
        report = self._validate(output=output)
        codes = {item.code for item in report.diagnostics}
        self.assertIn("NONPUBLIC_FACT_IN_ARRIVAL", codes)
        self.assertIn("GUARDED_CONTENT_LEAK", codes)

    def test_arrival_claim_cannot_reference_guarded_entity_id(self) -> None:
        output = copy.deepcopy(self.output)
        topology = self.expected["approved_topology"]
        monster_id = next(
            entity_id for entity_id in topology["mobile_occupant_ids"]
            if next(node for node in topology["nodes"] if node["id"] == entity_id)["kind"] == "monster"
        )
        scene_node_id = topology["scene_node_id"]
        module_id = topology["module_id"]
        fact = {
            "id": module_id + ":fact:guarded-entity-claim",
            "subject_id": monster_id,
            "predicate": "approaches",
            "object_id": scene_node_id,
            "status": "known",
            "value": "a figure is present",
            "provenance": {"class": "builder_authored", "source_refs": []},
        }
        output["fixture"]["facts"].append(fact)
        segment = output["arrival"]["arrival_segments"][2]
        segment["text"] = "A figure is present at the focal point."
        segment["fact_ids"] = [fact["id"]]
        output["arrival"]["claims"][2]["claims"] = [{
            "id": "claim-guarded-entity",
            "kind": "assertion",
            "fact_id": fact["id"],
            "predicate": fact["predicate"],
            "subject_id": fact["subject_id"],
            "object_id": fact["object_id"],
            "status": fact["status"],
            "value": fact["value"],
            "provenance": fact["provenance"],
            "span": segment["text"],
            "choice": None,
            "success": None,
        }]
        report = self._validate(output=output)
        self.assertIn("NONPUBLIC_ENTITY_IN_ARRIVAL", {item.code for item in report.diagnostics})

    def test_prior_pc_contamination_is_rejected(self) -> None:
        output = copy.deepcopy(self.output)
        module_id = output["fixture"]["module_id"]
        output["fixture"]["initial_mobile_occupants"].append({
            "id": module_id + ":entity:player-character",
            "kind": "pc",
        })
        report = self._validate(output=output)
        self.assertIn("PRIOR_PC_CONTAMINATION", {item.code for item in report.diagnostics})

    def test_unknown_cues_and_next_section_cannot_be_fabricated(self) -> None:
        output = copy.deepcopy(self.output)
        output["arrival"]["cue_states"][0].update({
            "status": "known", "fact_id": "invented-gradient", "reason": None,
        })
        output["arrival"]["next_section"].update({
            "status": "known",
            "from_scene_id": self.scene_id,
            "to_scene_id": "other:scene:room",
            "transition_fact_id": "invented-transition",
            "perception_fact_id": "invented-perception",
            "provenance": {"class": "builder_authored", "source_refs": []},
            "reason": None,
        })
        report = self._validate(output=output)
        codes = {item.code for item in report.diagnostics}
        self.assertIn("CUE_GRADIENT_UNSUPPORTED", codes)
        self.assertIn("NEXT_SECTION_NOT_PROTECTED_UNKNOWN", codes)

    def test_claim_bindings_and_player_agency_are_checked(self) -> None:
        output = copy.deepcopy(self.output)
        claim = output["arrival"]["claims"][0]["claims"][0]
        claim["kind"] = "invitation"
        claim["span"] = "not present in the segment"
        claim["success"] = "guaranteed"
        report = self._validate(output=output)
        codes = {item.code for item in report.diagnostics}
        self.assertIn("CLAIM_SPAN_MISMATCH", codes)
        self.assertIn("AGENCY_PRESCRIBED", codes)

    def test_invalid_expected_inputs_block_without_exception(self) -> None:
        report = validate_model_output(_json_bytes(self.output), {}, self.scene_id, self.schema)
        self.assertEqual(report.deterministic_status, "BLOCKED")
        malformed = copy.deepcopy(self.expected)
        del malformed["source_facts"]["source_reference"]
        report = validate_model_output(_json_bytes(self.output), malformed, self.scene_id, self.schema)
        self.assertEqual(report.deterministic_status, "BLOCKED")
        malformed = copy.deepcopy(self.expected)
        malformed["approved_topology"]["stage_role_bindings"]["usable_space"] = []
        report = validate_model_output(_json_bytes(self.output), malformed, self.scene_id, self.schema)
        self.assertEqual(report.deterministic_status, "BLOCKED")

    def test_provider_content_requires_matching_identity_one_choice_and_no_tools(self) -> None:
        content = _json_bytes(self.output).decode("ascii")
        response = _json_bytes({
            "id": "generation-test",
            "model": MODEL_ID,
            "choices": [{"message": {"role": "assistant", "content": content}}],
        })
        self.assertEqual(
            extract_model_content(response, expected_model_id=MODEL_ID, expected_generation_id="generation-test"),
            content.encode("ascii"),
        )
        for invalid in (
            _json_bytes({"id": "generation-test", "model": "wrong", "choices": [{"message": {"role": "assistant", "content": content}}]}),
            _json_bytes({"id": "wrong", "model": MODEL_ID, "choices": [{"message": {"role": "assistant", "content": content}}]}),
            _json_bytes({"id": "generation-test", "model": MODEL_ID, "choices": [{"message": {"role": "assistant", "content": content}}, {"message": {"role": "assistant", "content": content}}]}),
            _json_bytes({"id": "generation-test", "model": MODEL_ID, "choices": [{"message": {"role": "assistant", "tool_calls": [], "content": content}}]}),
        ):
            with self.assertRaises(ValueError):
                extract_model_content(invalid, expected_model_id=MODEL_ID, expected_generation_id="generation-test")


if __name__ == "__main__":
    unittest.main()
