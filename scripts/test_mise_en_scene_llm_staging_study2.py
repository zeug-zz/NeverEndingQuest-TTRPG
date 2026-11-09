# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the Study 2 delta-only contract."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import builtins
import copy
from dataclasses import replace
from decimal import Decimal
import hashlib
import http.client
import inspect
import io
import json
import logging
import os
from pathlib import Path
import socket
import tempfile
import threading
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mise_en_scene.llm_staging_study2.contract import (
    ContractError,
    FrozenSceneBinding,
    load_frozen_bindings,
    validate_delta_payload,
)
from mise_en_scene.llm_staging_study2 import hydration as hydration_module
from mise_en_scene.llm_staging_study2.hydration import (
    hydrate_delta_output,
    validate_delta_output,
)
from mise_en_scene.llm_staging.output_gates import validate_model_output
from mise_en_scene.llm_staging_study2 import client as study2_client_module
from mise_en_scene.llm_staging_study2 import materialize as study2_materialize_module
from mise_en_scene.llm_staging_study2 import ledger as study2_ledger_module
from mise_en_scene.llm_staging_study2 import transport as study2_transport_module
from mise_en_scene.llm_staging_study2.sizing import approximate_tokens, cost_estimate, sizing_proposal
from mise_en_scene.llm_staging_study2.client import (
    ApprovalPins,
    Study2Client,
    Study2ExecutionError,
)
from mise_en_scene.llm_staging_study2.ledger import (
    LEDGER_NAME as STUDY2_LEDGER_NAME,
    SCENE_ORDER as STUDY2_SCENE_ORDER,
    STUDY2_ROOT_RELATIVE,
    STUDY_ID as STUDY2_ID,
    Study2Ledger,
    Study2LedgerError,
)
from mise_en_scene.llm_staging_study2.transport import (
    MODEL_ID as STUDY2_MODEL_ID,
    OPENROUTER_ENDPOINT as STUDY2_ENDPOINT,
    OpenRouterTransport,
    Study2TransportError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY1_PROTOCOL_ROOT = REPO_ROOT / (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-protocol"
)
STUDY1_RUNTIME_ROOT = REPO_ROOT / (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging"
)
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
STUDY2_REFERENCE_ROOT = REPO_ROOT / (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-study2/protocol/references"
)
STUDY1_PROTOCOL_TREE_SHA256 = "9451ea6046e57afc1d8ecb76de4206720a09a9c1e759b74731704579f27a882a"


@contextmanager
def _network_tripwire():
    """Make socket and standard-library HTTP dispatch fail in every test."""

    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in Study 2 preparation tests")

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", side_effect=fail_network))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=fail_network))
        stack.enter_context(patch.object(http.client.HTTPConnection, "request", side_effect=fail_network))
        stack.enter_context(patch("urllib.request.urlopen", side_effect=fail_network))
        yield


@contextmanager
def _no_write_tripwire():
    """Fail if contract validation attempts project or scratch writes."""

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("writes are forbidden in Study 2 contract tests")

    original_path_open = Path.open
    original_builtin_open = builtins.open
    original_os_open = os.open

    def guarded_path_open(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            fail_write(path, mode)
        return original_path_open(path, mode, *args, **kwargs)

    def guarded_builtin_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            fail_write(file, mode)
        return original_builtin_open(file, mode, *args, **kwargs)

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def guarded_os_open(path: object, flags: int, *args: object, **kwargs: object):
        if flags & write_flags:
            fail_write(path, flags)
        return original_os_open(path, flags, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "open", guarded_path_open))
        stack.enter_context(patch.object(Path, "write_bytes", side_effect=fail_write))
        stack.enter_context(patch.object(Path, "write_text", side_effect=fail_write))
        stack.enter_context(patch.object(Path, "mkdir", side_effect=fail_write))
        stack.enter_context(patch.object(builtins, "open", guarded_builtin_open))
        stack.enter_context(patch.object(os, "open", guarded_os_open))
        yield


def _tree_fingerprint(root: Path) -> tuple[int, str]:
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.as_posix())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        digest.update(relative + b"\0" + content_hash + b"\n")
    return len(files), digest.hexdigest()


def _tree_fingerprint_if_present(root: Path) -> tuple[int, str] | None:
    if not root.exists():
        return None
    return _tree_fingerprint(root)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def _valid_payload(binding: FrozenSceneBinding) -> dict[str, object]:
    scene_id = binding.scene_id
    approach_id = binding.role_bindings["approach"][0]
    threshold_id = binding.role_bindings["threshold"][0]
    focal_id = binding.role_bindings["focal_anchor"][0]
    usable_id = binding.role_bindings["usable_space"][0]
    fact_id = binding.module_id + ":fact:study2-authored:approach-threshold"
    arrival = [
        {
            "id": scene_id + ":arrival:" + role,
            "role": role,
            "text": text,
        }
        for role, text in (
            ("approach", "A marked way leads toward the threshold."),
            ("threshold", "The stone opening frames the chamber."),
            ("focal", "A pale sigil rests beyond the entry."),
        )
    ]
    return {
        "schema": "neq.llm_staging_study2_delta.v1",
        "input_refs": binding.input_refs(),
        "fixture_deltas": {
            "facts": [
                {
                    "fact_id": fact_id,
                    "subject_id": approach_id,
                    "predicate": "approach_to_threshold",
                    "object_id": threshold_id,
                    "value": True,
                }
            ]
        },
        "stage_role_bindings": {
            "approach": [approach_id],
            "threshold": [threshold_id],
            "focal_anchor": [focal_id],
            "usable_space": [usable_id],
        },
        "claims": [
            {
                "segment_id": arrival[0]["id"],
                "items": [
                    {
                        "id": scene_id + ":claim:approach-01",
                        "fact_id": fact_id,
                        "kind": "factual",
                        "span": "A marked way leads toward the threshold.",
                        "choice": None,
                        "success": None,
                    }
                ],
            },
            {"segment_id": arrival[1]["id"], "items": []},
            {"segment_id": arrival[2]["id"], "items": []},
        ],
        "arrival_prose": arrival,
    }


def _reference_path(scene_id: str) -> Path:
    return STUDY2_REFERENCE_ROOT / (scene_id.replace(":", "__") + ".json")


def _reference_payload(scene_id: str) -> tuple[bytes, dict[str, object]]:
    raw = _reference_path(scene_id).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if type(payload) is not dict:
        raise AssertionError("hand-assembled reference root must be an object")
    return raw, payload


STUDY2_TEST_SCRATCH = REPO_ROOT / (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study2/test-scratch"
)
STUDY2_AUTHORITY_ID = "neq-study2-execution-review-synthetic-test"


def _study2_generation_config() -> dict[str, object]:
    return {
        "schema": "neq.llm_staging_study2_generation_config.v1",
        "endpoint": STUDY2_ENDPOINT,
        "model_id": STUDY2_MODEL_ID,
        "temperature": 0.2,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "max_tokens": 3072,
        "timeout_seconds": 240,
        "stream": False,
        "response_format": {"type": "json_object"},
        "tools": [],
        "tool_choice": "none",
        "provider": {"allow_fallbacks": False},
    }


def _canonical_study2_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _study2_transport_request(config: dict[str, object] | None = None) -> dict[str, object]:
    generation_config = _study2_generation_config() if config is None else config
    return {
        "model": generation_config["model_id"],
        "messages": [
            {"role": "system", "content": "synthetic system"},
            {"role": "user", "content": "synthetic user"},
        ],
        "temperature": generation_config["temperature"],
        "top_p": generation_config["top_p"],
        "frequency_penalty": generation_config["frequency_penalty"],
        "presence_penalty": generation_config["presence_penalty"],
        "max_tokens": generation_config["max_tokens"],
        "stream": generation_config["stream"],
        "response_format": copy.deepcopy(generation_config["response_format"]),
        "tools": copy.deepcopy(generation_config["tools"]),
        "tool_choice": generation_config["tool_choice"],
        "provider": copy.deepcopy(generation_config["provider"]),
    }


def _synthetic_reserved_context(
    request: dict[str, object],
    generation_config_bytes: bytes,
    owner_token: object,
):
    return study2_transport_module._create_reserved_dispatch_context(
        owner_token,
        attempt_number=1,
        scene_id=STUDY2_SCENE_ORDER[0],
        run_id="synthetic-transport-test",
        request_sha256=hashlib.sha256(_canonical_study2_bytes(request)).hexdigest(),
        config_sha256=hashlib.sha256(generation_config_bytes).hexdigest(),
    )


@contextmanager
def _study2_root_patch(root: Path):
    with patch.object(study2_client_module, "STUDY2_ROOT", root), patch.object(
        study2_ledger_module, "STUDY2_ROOT", root
    ):
        yield


def _synthetic_study2_bundle():
    """Build an in-memory S2.4-shaped bundle without creating frozen files."""

    from mise_en_scene.llm_staging_study2.client import _FrozenBundle

    artifact_paths = study2_client_module._expected_artifact_paths()
    config = _study2_generation_config()
    artifact_bytes = {
        "protocol": (REPO_ROOT / artifact_paths["protocol"]).read_bytes(),
        "input_bindings": (REPO_ROOT / artifact_paths["input_bindings"]).read_bytes(),
        "output_schema": (REPO_ROOT / artifact_paths["output_schema"]).read_bytes(),
        "system_prompt": b"Synthetic Study 2 system prompt.",
        "task_prompt": (
            b"Scene {{SCENE_ID}}; refs {{INPUT_REFS_JSON}}; source "
            b"{{SOURCE_PACKET_JSON}}; expected {{EXPECTED_BUNDLE_JSON}}; schema "
            b"{{OUTPUT_SCHEMA_JSON}}"
        ),
        "generation_config": _json_bytes(config),
        "availability_attestation": (
            REPO_ROOT / artifact_paths["availability_attestation"]
        ).read_bytes(),
    }
    artifact_records: dict[str, dict[str, str]] = {}
    artifact_hashes: dict[str, str] = {}
    for role, contents in artifact_bytes.items():
        path = artifact_paths[role]
        digest = hashlib.sha256(contents).hexdigest()
        artifact_records[role] = {"path": path, "sha256": digest}
        artifact_hashes[path] = digest

    bindings = load_frozen_bindings()
    scene_rows = []
    for scene_id in STUDY2_SCENE_ORDER:
        binding = bindings[scene_id]
        scene_rows.append(
            {
                "scene_id": scene_id,
                "source_packet": {
                    "path": binding.source_packet.identifier,
                    "sha256": binding.source_packet.sha256,
                },
                "expected_bundle": {
                    "path": binding.expected_bundle.identifier,
                    "sha256": binding.expected_bundle.sha256,
                },
            }
        )
        artifact_hashes[binding.source_packet.identifier] = binding.source_packet.sha256
        artifact_hashes[binding.expected_bundle.identifier] = binding.expected_bundle.sha256

    availability_digest = artifact_records["availability_attestation"]["sha256"]
    manifest = {
        "schema": "neq.llm_staging_study2_manifest.v1",
        "study_id": STUDY2_ID,
        "protocol_version": "neq.llm_staging_study2_delta.v1",
        "status": "FROZEN_FOR_REVIEW",
        "scene_order": list(STUDY2_SCENE_ORDER),
        "attempt_cap": len(STUDY2_SCENE_ORDER),
        "endpoint": STUDY2_ENDPOINT,
        "model_id": STUDY2_MODEL_ID,
        "availability": {
            "raw_listing_path": study2_client_module.HISTORICAL_RAW_LISTING_PATH,
            "raw_listing_sha256": study2_client_module.HISTORICAL_RAW_LISTING_SHA256,
            "attestation_path": artifact_paths["availability_attestation"],
            "attestation_sha256": availability_digest,
        },
        "artifacts": artifact_records,
        "scenes": scene_rows,
    }
    manifest_bytes = _json_bytes(manifest)
    return _FrozenBundle(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifact_bytes=artifact_bytes,
        artifact_hashes=artifact_hashes,
        scene_bindings=dict(bindings),
        generation_config=config,
        generation_config_bytes=artifact_bytes["generation_config"],
        availability_attestation_sha256=availability_digest,
    )


def _write_synthetic_approvals(
    root: Path,
    bundle: object,
) -> ApprovalPins:
    protocol_digest = bundle.manifest["artifacts"]["protocol"]["sha256"]
    common = {
        "study_id": STUDY2_ID,
        "attempt_cap": len(STUDY2_SCENE_ORDER),
        "model_id": STUDY2_MODEL_ID,
        "endpoint": STUDY2_ENDPOINT,
        "manifest_sha256": bundle.manifest_sha256,
        "protocol_version": bundle.manifest["protocol_version"],
        "protocol_sha256": protocol_digest,
        "availability_attestation_sha256": bundle.availability_attestation_sha256,
        "availability_raw_listing_sha256": study2_client_module.HISTORICAL_RAW_LISTING_SHA256,
        "scene_order": list(STUDY2_SCENE_ORDER),
        "study_root_relative": STUDY2_ROOT_RELATIVE,
        "authority_record_id": STUDY2_AUTHORITY_ID,
        "approved_at_utc": "2026-11-10T00:00:00Z",
    }
    owner = {
        "schema": "neq.llm_staging_study2_owner_cap_approval.v1",
        "status": "APPROVED_STUDY2_CAP",
        "review_status": "OWNER_APPROVED",
        **common,
        "approved_by": "synthetic-owner",
    }
    overseer = {
        "schema": "neq.llm_staging_study2_overseer_step_a_approval.v1",
        "status": "APPROVED_STEP_A",
        "review_status": "PASS",
        **common,
        "approved_by": "overseer",
    }
    owner_bytes = json.dumps(owner, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    overseer_bytes = json.dumps(overseer, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    (root / "owner-cap-approval.json").write_bytes(owner_bytes)
    (root / "overseer-step-a-approval.json").write_bytes(overseer_bytes)
    return ApprovalPins(
        owner_approval_sha256=hashlib.sha256(owner_bytes).hexdigest(),
        overseer_approval_sha256=hashlib.sha256(overseer_bytes).hexdigest(),
        authority_record_id=STUDY2_AUTHORITY_ID,
    )


class _FakeStudy2HTTP:
    def __init__(self, status: int, body: bytes, callback=None) -> None:
        self.status = status
        self.body = body
        self.callback = callback
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs: object) -> tuple[int, bytes]:
        self.calls.append(dict(kwargs))
        if self.callback is not None:
            self.callback()
        return self.status, self.body


def _study2_response(
    *,
    model: str = STUDY2_MODEL_ID,
    provider: str | None = "OpenAI",
    generation_id: str | None = "synthetic-generation",
    usage: dict[str, object] | None = None,
) -> bytes:
    response: dict[str, object] = {
        "model": model,
        "provider": provider,
        "id": generation_id,
        "usage": usage if usage is not None else {"prompt_tokens": 17, "completion_tokens": 31, "total_tokens": 48, "cost": 0.0042},
        "choices": [{"message": {"role": "assistant", "content": "{}"}}],
    }
    return _json_bytes(response)


def _primary_audit_usage_shapes() -> tuple[dict[str, object], ...]:
    """Safe usage metadata copied from primary-audit reported_usage only."""

    return (
        {
            "completion_tokens": 4096,
            "completion_tokens_details": {
                "audio_tokens": 0,
                "image_tokens": 0,
                "reasoning_tokens": 1462,
            },
            "cost": 0.0040938,
            "cost_details": {
                "upstream_inference_completions_cost": 0.002048,
                "upstream_inference_cost": 0.0040938,
                "upstream_inference_prompt_cost": 0.0020458,
            },
            "is_byok": False,
            "prompt_tokens": 16367,
            "prompt_tokens_details": {
                "audio_tokens": 0,
                "cache_write_tokens": 16364,
                "cached_tokens": 0,
                "video_tokens": 0,
            },
            "total_tokens": 20463,
        },
        {
            "completion_tokens": 4096,
            "completion_tokens_details": {
                "audio_tokens": 0,
                "image_tokens": 0,
                "reasoning_tokens": 1613,
            },
            "cost": 0.0037473,
            "cost_details": {
                "upstream_inference_completions_cost": 0.002048,
                "upstream_inference_cost": 0.0037473,
                "upstream_inference_prompt_cost": 0.0016993,
            },
            "is_byok": False,
            "prompt_tokens": 13595,
            "prompt_tokens_details": {
                "audio_tokens": 0,
                "cache_write_tokens": 13592,
                "cached_tokens": 0,
                "video_tokens": 0,
            },
            "total_tokens": 17691,
        },
        {
            "completion_tokens": 4096,
            "completion_tokens_details": {
                "audio_tokens": 0,
                "image_tokens": 0,
                "reasoning_tokens": 1758,
            },
            "cost": 0.0039153,
            "cost_details": {
                "upstream_inference_completions_cost": 0.002048,
                "upstream_inference_cost": 0.0039153,
                "upstream_inference_prompt_cost": 0.0018673,
            },
            "is_byok": False,
            "prompt_tokens": 14939,
            "prompt_tokens_details": {
                "audio_tokens": 0,
                "cache_write_tokens": 14936,
                "cached_tokens": 0,
                "video_tokens": 0,
            },
            "total_tokens": 19035,
        },
    )


class Study2DeltaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with _network_tripwire():
            cls.bindings = load_frozen_bindings()

    def setUp(self) -> None:
        self.scene_id = SCENE_ORDER[0]
        self.binding = self.bindings[self.scene_id]
        self.payload = _valid_payload(self.binding)

    def _validate(self, payload: dict[str, object] | bytes, scene_id: str | None = None) -> object:
        output_bytes = payload if type(payload) is bytes else _json_bytes(payload)
        with _network_tripwire():
            return validate_delta_payload(
                output_bytes,
                scene_id=self.scene_id if scene_id is None else scene_id,
            )

    def _assert_code(self, code: str, payload: dict[str, object] | bytes, scene_id: str | None = None) -> None:
        with self.assertRaises(ContractError) as caught:
            self._validate(payload, scene_id)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        if code == "OUTPUT_JSON_INVALID":
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(caught.exception.__suppress_context__)

    def test_exact_three_scene_bindings_recompute_frozen_context(self) -> None:
        self.assertEqual(tuple(self.bindings), SCENE_ORDER)
        expected = (
            (
                "into_the_deepvault:topology:i02",
                "02271ab7eca053818af57a14977de6356607382c6b47d9929355d8070376906c",
                "642597984aac4c8cf7de1b7364be7c097f67b092e65ef6b66c093fc2667bb258",
            ),
            (
                "into_the_deepvault:topology:i03",
                "9fef91cf653debbaf900f378859a196005dd0970e0d0270ea2d2062e443e902a",
                "f1a5835b517fe38521b8a2af89cd4de8dd23c25370082501ed07c1591b4ea20b",
            ),
            (
                "xhalruuns_masquerade:topology:ao02",
                "a3c93908e343e3a4c22be0056259e1498426310402bae7093f9eb312f4639e29",
                "6e0e07ac80632252f40207e82d94b4c532cadddf2e4895beca49a701524997af",
            ),
        )
        for scene_id, expected_values in zip(SCENE_ORDER, expected):
            binding = self.bindings[scene_id]
            self.assertEqual(binding.topology.identifier, expected_values[0])
            self.assertEqual(binding.topology.sha256, expected_values[1])
            self.assertEqual(binding.gate_canonical_context.sha256, expected_values[1])
            self.assertEqual(binding.expected_bundle.sha256, expected_values[2])
            self.assertEqual(binding.gate_canonical_context.identifier, scene_id + "#gate-canonical-context:" + expected_values[0])

    def test_valid_slim_contract_is_accepted_and_returned_immutable(self) -> None:
        result = self._validate(self.payload)
        self.assertEqual(result["schema"], "neq.llm_staging_study2_delta.v1")
        self.assertEqual(len(result["fixture_deltas"]["facts"]), 1)
        with self.assertRaises(TypeError):
            result["input_refs"]["scene_id"] = "changed"
        with self.assertRaises(TypeError):
            result["fixture_deltas"]["facts"][0]["fact_id"] = "changed"
        with self.assertRaises(TypeError):
            self.bindings["other"] = self.binding
        copied_refs = self.binding.input_refs()
        copied_refs["topology"]["id"] = "local mutation only"
        self.assertEqual(
            self.binding.input_refs()["topology"]["id"],
            self.binding.topology.identifier,
        )

    def test_unknown_keys_are_rejected_at_each_nested_object(self) -> None:
        mutations = (
            lambda item: item.update({"topology": {"nodes": []}}),
            lambda item: item["input_refs"]["topology"].update({"extra": "x"}),
            lambda item: item["fixture_deltas"].update({"base_facts": []}),
            lambda item: item["fixture_deltas"]["facts"][0].update({"provenance": {}}),
            lambda item: item["fixture_deltas"]["facts"][0].update(
                {"value": {"kind": "entity_ref", "entity_id": self.binding.role_bindings["approach"][0], "extra": 1}}
            ),
            lambda item: item["claims"][0]["items"][0].update({"value": "echo"}),
            lambda item: item["arrival_prose"][0].update({"fact_ids": []}),
        )
        for mutation in mutations:
            candidate = copy.deepcopy(self.payload)
            mutation(candidate)
            with self.subTest(candidate_keys=tuple(candidate)):
                self._assert_code("OUTPUT_SCHEMA_REJECTED", candidate)

    def test_stale_or_unknown_input_hashes_and_ids_are_rejected(self) -> None:
        cases = (
            ("expected_bundle", "sha256", "0" * 64, "INPUT_REFERENCE_HASH_MISMATCH"),
            ("source_packet", "sha256", "1" * 64, "INPUT_REFERENCE_HASH_MISMATCH"),
            ("topology", "sha256", "2" * 64, "INPUT_REFERENCE_HASH_MISMATCH"),
            ("gate_canonical_context", "sha256", "3" * 64, "INPUT_REFERENCE_HASH_MISMATCH"),
            ("topology", "id", "unknown:topology", "INPUT_REFERENCE_ID_MISMATCH"),
            ("expected_bundle", "id", "unknown:bundle", "INPUT_REFERENCE_ID_MISMATCH"),
        )
        for reference, field, value, expected_code in cases:
            candidate = copy.deepcopy(self.payload)
            candidate["input_refs"][reference][field] = value
            with self.subTest(reference=reference, field=field):
                self._assert_code(expected_code, candidate)

    def test_wrong_and_unapproved_scene_ids_are_rejected(self) -> None:
        other_scene = SCENE_ORDER[1]
        other_payload = _valid_payload(self.bindings[other_scene])
        self._assert_code("SCENE_ID_MISMATCH", other_payload, self.scene_id)
        self._assert_code("SCENE_NOT_APPROVED", self.payload, "unknown:scene")

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        self._assert_code("OUTPUT_JSON_INVALID", b'{"schema":"one","schema":"two"}')
        self._assert_code("OUTPUT_JSON_INVALID", b'{"schema":"neq.llm_staging_study2_delta.v1","value":NaN}')
        self._assert_code("OUTPUT_JSON_INVALID", b'{"schema":"neq.llm_staging_study2_delta.v1","value":1e999}')

    def test_topology_and_base_fact_overwrites_are_rejected(self) -> None:
        for key in ("topology", "base_facts"):
            candidate = copy.deepcopy(self.payload)
            candidate[key] = {}
            with self.subTest(root_key=key):
                self._assert_code("OUTPUT_SCHEMA_REJECTED", candidate)

        for key in ("topology", "base_facts", "entities"):
            candidate = copy.deepcopy(self.payload)
            candidate["fixture_deltas"][key] = []
            with self.subTest(delta_key=key):
                self._assert_code("OUTPUT_SCHEMA_REJECTED", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["fixture_deltas"]["facts"][0]["fact_id"] = next(iter(self.binding.base_fact_ids))
        self._assert_code("BASE_FACT_OVERWRITE", candidate)

    def test_unknown_topology_fact_and_claim_ids_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.payload)
        candidate["stage_role_bindings"]["approach"] = ["unknown:entity"]
        self._assert_code("UNKNOWN_TOPOLOGY_ID", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["fixture_deltas"]["facts"][0]["subject_id"] = "unknown:entity"
        self._assert_code("UNKNOWN_TOPOLOGY_ID", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["claims"][0]["items"][0]["fact_id"] = "unknown:fact"
        self._assert_code("CLAIM_FACT_REFERENCE_INVALID", candidate)

    def test_unbounded_fact_values_and_nonpublic_fact_refs_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.payload)
        candidate["fixture_deltas"]["facts"][0]["value"] = {"arbitrary": [1, 2]}
        self._assert_code("OUTPUT_SCHEMA_REJECTED", candidate)

        nonpublic = next(iter(self.binding.base_fact_ids - self.binding.public_base_fact_ids))
        candidate = copy.deepcopy(self.payload)
        candidate["claims"][0]["items"][0]["fact_id"] = nonpublic
        self._assert_code("CLAIM_FACT_REFERENCE_INVALID", candidate)

    def test_malformed_stage_claim_and_arrival_bindings_are_rejected(self) -> None:
        candidate = copy.deepcopy(self.payload)
        candidate["arrival_prose"][0]["role"] = "focal"
        self._assert_code("OUTPUT_SCHEMA_REJECTED", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["arrival_prose"][0]["id"] = "wrong:segment"
        self._assert_code("ARRIVAL_ROLE_BINDING_INVALID", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["claims"][0]["items"][0]["span"] = "not present"
        self._assert_code("CLAIM_SPAN_INVALID", candidate)

        candidate = copy.deepcopy(self.payload)
        candidate["claims"][0]["items"][0]["kind"] = "invitation"
        self._assert_code("INVITATION_AGENCY_INVALID", candidate)

    def test_study1_protocol_and_available_runtime_bytes_remain_unchanged(self) -> None:
        before_protocol = _tree_fingerprint(STUDY1_PROTOCOL_ROOT)
        self.assertEqual(before_protocol, (16, STUDY1_PROTOCOL_TREE_SHA256))
        before_runtime = _tree_fingerprint_if_present(STUDY1_RUNTIME_ROOT)

        with patch.object(Path, "exists", return_value=False):
            self.assertIsNone(_tree_fingerprint_if_present(STUDY1_RUNTIME_ROOT))

        with _network_tripwire(), _no_write_tripwire():
            bindings = load_frozen_bindings()
            validate_delta_payload(
                _json_bytes(_valid_payload(bindings[self.scene_id])),
                scene_id=self.scene_id,
            )

        self.assertEqual(_tree_fingerprint(STUDY1_PROTOCOL_ROOT), before_protocol)
        self.assertEqual(_tree_fingerprint_if_present(STUDY1_RUNTIME_ROOT), before_runtime)


class Study2HydrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with _network_tripwire():
            cls.bindings = load_frozen_bindings()

    def test_three_hand_assembled_references_run_the_real_study1_gates(self) -> None:
        self.assertEqual(tuple(self.bindings), SCENE_ORDER)
        self.assertEqual(
            sorted(path.name for path in STUDY2_REFERENCE_ROOT.glob("*.json")),
            sorted(scene_id.replace(":", "__") + ".json" for scene_id in SCENE_ORDER),
        )
        for scene_id in SCENE_ORDER:
            raw, payload = _reference_payload(scene_id)
            self.assertEqual(payload["schema"], "neq.llm_staging_study2_delta.v1")
            self.assertEqual(payload["input_refs"]["scene_id"], scene_id)
            with self.subTest(scene_id=scene_id), _network_tripwire():
                with patch.object(
                    hydration_module,
                    "validate_model_output",
                    wraps=validate_model_output,
                ) as full_gate:
                    report = validate_delta_output(raw, scene_id=scene_id)
                self.assertEqual(full_gate.call_count, 1)
                self.assertEqual(report.deterministic_status, "PASS")
                self.assertEqual(report.scene_status, "BLOCKED")
                self.assertEqual(report.semantic_review_status, "PENDING")
                self.assertEqual(report.owner_rating_status, "PENDING")
                self.assertEqual(report.diagnostics, ())
                self.assertEqual(
                    report.delta_artifact_sha256,
                    hashlib.sha256(raw).hexdigest(),
                )
                self.assertRegex(report.hydrated_output_sha256 or "", r"^[0-9a-f]{64}$")
                self.assertEqual(report.to_dict()["deterministic_status"], "PASS")

    def test_delta_failures_are_rejected_before_full_fixture_hydration(self) -> None:
        scene_id = SCENE_ORDER[0]
        binding = self.bindings[scene_id]
        _raw, reference = _reference_payload(scene_id)
        cases: list[tuple[str, dict[str, object], str]] = []

        unknown_key = copy.deepcopy(reference)
        unknown_key["unexpected"] = True
        cases.append(("unknown_key", unknown_key, "OUTPUT_SCHEMA_REJECTED"))

        stale_hash = copy.deepcopy(reference)
        stale_hash["input_refs"]["expected_bundle"]["sha256"] = "0" * 64
        cases.append(("stale_hash", stale_hash, "INPUT_REFERENCE_HASH_MISMATCH"))

        overwrite = copy.deepcopy(reference)
        overwrite["fixture_deltas"]["facts"][0]["fact_id"] = next(
            iter(binding.base_fact_ids)
        )
        cases.append(("base_fact_overwrite", overwrite, "BASE_FACT_OVERWRITE"))

        topology_overwrite = copy.deepcopy(reference)
        topology_overwrite["topology"] = {}
        cases.append(("topology_overwrite", topology_overwrite, "OUTPUT_SCHEMA_REJECTED"))

        with _network_tripwire(), patch.object(
            hydration_module,
            "validate_model_output",
            wraps=validate_model_output,
        ) as full_gate:
            for name, candidate, expected_code in cases:
                with self.subTest(case=name):
                    report = validate_delta_output(
                        _json_bytes(candidate), scene_id=scene_id
                    )
                    self.assertEqual(report.deterministic_status, "FAIL")
                    self.assertIsNone(report.hydrated_output_sha256)
                    self.assertIn(expected_code, {item.code for item in report.diagnostics})
        self.assertEqual(full_gate.call_count, 0)

    def test_real_full_gate_rejects_missing_stage_relations_and_known_cues(self) -> None:
        scene_id = SCENE_ORDER[0]
        binding = self.bindings[scene_id]
        _raw, reference = _reference_payload(scene_id)
        cases: list[tuple[str, dict[str, object], str]] = []

        for predicate, claim_group_index in (
            ("approach_to_threshold", 0),
            ("threshold_to_focal", 2),
        ):
            candidate = copy.deepcopy(reference)
            removed_fact_id = next(
                item["fact_id"]
                for item in candidate["fixture_deltas"]["facts"]
                if item["predicate"] == predicate
            )
            candidate["fixture_deltas"]["facts"] = [
                item
                for item in candidate["fixture_deltas"]["facts"]
                if item["fact_id"] != removed_fact_id
            ]
            candidate["claims"][claim_group_index]["items"] = [
                item
                for item in candidate["claims"][claim_group_index]["items"]
                if item["fact_id"] != removed_fact_id
            ]
            cases.append(("missing_" + predicate, candidate, "MISSING_RELATION"))

        for cue in ("light", "sound"):
            candidate = copy.deepcopy(reference)
            candidate["fixture_deltas"]["facts"].append(
                {
                    "fact_id": binding.module_id + ":fact:study2-authored:negative-" + cue,
                    "subject_id": candidate["stage_role_bindings"]["threshold"][0],
                    "predicate": cue + "_gradient",
                    "object_id": None,
                    "value": "bright-to-dim",
                }
            )
            cases.append(
                ("known_" + cue + "_gradient", candidate, "PROTECTED_UNKNOWN_PROMOTED")
            )

        for name, candidate, expected_code in cases:
            with self.subTest(case=name), _network_tripwire():
                with patch.object(
                    hydration_module,
                    "validate_model_output",
                    wraps=validate_model_output,
                ) as full_gate:
                    report = validate_delta_output(
                        _json_bytes(candidate), scene_id=scene_id
                    )
            self.assertEqual(full_gate.call_count, 1)
            self.assertEqual(report.deterministic_status, "FAIL")
            self.assertIsNotNone(report.hydrated_output_sha256)
            self.assertIn(expected_code, {item.code for item in report.diagnostics})

    def test_closed_delta_contract_rejects_unrepresentable_or_forbidden_negatives(self) -> None:
        scene_id = SCENE_ORDER[0]
        binding = self.bindings[scene_id]
        _raw, reference = _reference_payload(scene_id)
        cases: list[tuple[str, bytes, str]] = []

        def add_case(name: str, candidate: dict[str, object], code: str) -> None:
            cases.append((name, _json_bytes(candidate), code))

        missing_usable = copy.deepcopy(reference)
        missing_usable["stage_role_bindings"]["usable_space"] = []
        add_case("empty_usable_space_binding", missing_usable, "OUTPUT_SCHEMA_REJECTED")

        missing_usable = copy.deepcopy(reference)
        del missing_usable["stage_role_bindings"]["usable_space"]
        add_case("missing_usable_space_binding", missing_usable, "OUTPUT_SCHEMA_REJECTED")

        missing_extent = copy.deepcopy(reference)
        missing_extent["fixture_deltas"]["multi_cell_extents"] = []
        add_case("delta_cannot_remove_hydrated_usable_extent", missing_extent, "OUTPUT_SCHEMA_REJECTED")

        for predicate in ("distance", "mechanic"):
            forbidden = copy.deepcopy(reference)
            forbidden["fixture_deltas"]["facts"].append(
                {
                    "fact_id": binding.module_id + ":fact:study2-authored:negative-" + predicate,
                    "subject_id": forbidden["stage_role_bindings"]["threshold"][0],
                    "predicate": predicate,
                    "object_id": None,
                    "value": "known",
                }
            )
            add_case("forbidden_" + predicate, forbidden, "OUTPUT_SCHEMA_REJECTED")

        choice_prescription = copy.deepcopy(reference)
        choice_prescription["claims"][0]["items"][0].update(
            {"kind": "invitation", "choice": "choose the eastern passage"}
        )
        add_case("prescriptive_invitation_choice", choice_prescription, "OUTPUT_SCHEMA_REJECTED")

        success_prescription = copy.deepcopy(reference)
        success_prescription["claims"][0]["items"][0].update(
            {"kind": "invitation", "choice": "open", "success": "the party succeeds"}
        )
        add_case("prescriptive_invitation_success", success_prescription, "OUTPUT_SCHEMA_REJECTED")

        nonpublic_fact = next(iter(binding.base_fact_ids - binding.public_base_fact_ids))
        nonpublic_claim = copy.deepcopy(reference)
        nonpublic_claim["claims"][0]["items"][0]["fact_id"] = nonpublic_fact
        add_case("claim_nonpublic_base_fact", nonpublic_claim, "CLAIM_FACT_REFERENCE_INVALID")

        base_overwrite = copy.deepcopy(reference)
        base_overwrite["fixture_deltas"]["facts"][0]["fact_id"] = next(
            iter(binding.base_fact_ids)
        )
        add_case("overwrite_source_base_fact_id", base_overwrite, "BASE_FACT_OVERWRITE")

        stale_id = copy.deepcopy(reference)
        stale_id["input_refs"]["topology"]["id"] = "unknown:topology"
        add_case("stale_topology_id", stale_id, "INPUT_REFERENCE_ID_MISMATCH")

        stale_hash = copy.deepcopy(reference)
        stale_hash["input_refs"]["expected_bundle"]["sha256"] = "0" * 64
        add_case("stale_expected_bundle_hash", stale_hash, "INPUT_REFERENCE_HASH_MISMATCH")

        topology_echo = copy.deepcopy(reference)
        topology_echo["topology"] = {}
        add_case("attempt_topology_overwrite", topology_echo, "OUTPUT_SCHEMA_REJECTED")

        source_echo = copy.deepcopy(reference)
        source_echo["source_facts"] = {}
        add_case("attempt_source_facts_overwrite", source_echo, "OUTPUT_SCHEMA_REJECTED")

        provenance_echo = copy.deepcopy(reference)
        provenance_echo["source_provenance"] = {}
        add_case("attempt_source_provenance_overwrite", provenance_echo, "OUTPUT_SCHEMA_REJECTED")

        base_rows = copy.deepcopy(reference)
        base_rows["fixture_deltas"]["base_facts"] = []
        add_case("attempt_base_facts_overwrite", base_rows, "OUTPUT_SCHEMA_REJECTED")

        authored_provenance = copy.deepcopy(reference)
        authored_provenance["fixture_deltas"]["facts"][0]["provenance"] = {
            "class": "source_extracted",
            "source_refs": [],
        }
        add_case("attempt_authored_provenance_overwrite", authored_provenance, "OUTPUT_SCHEMA_REJECTED")

        duplicate_json = b'{"schema":"neq.llm_staging_study2_delta.v1","schema":"neq.llm_staging_study2_delta.v1"}'
        cases.append(("duplicate_json_key", duplicate_json, "OUTPUT_JSON_INVALID"))

        self.assertTrue(
            all(len(item.role_bindings["usable_space"]) == 1 for item in self.bindings.values())
        )
        with _network_tripwire(), patch.object(
            hydration_module,
            "validate_model_output",
            wraps=validate_model_output,
        ) as full_gate:
            for name, candidate_bytes, expected_code in cases:
                with self.subTest(case=name):
                    report = validate_delta_output(candidate_bytes, scene_id=scene_id)
                    self.assertEqual(report.deterministic_status, "FAIL")
                    self.assertIsNone(report.hydrated_output_sha256)
                    self.assertEqual(
                        {item.code for item in report.diagnostics}, {expected_code}
                    )
        self.assertEqual(full_gate.call_count, 0)

    def test_guarded_source_marker_fails_the_full_study1_knowledge_gate(self) -> None:
        scene_id = SCENE_ORDER[0]
        binding = self.bindings[scene_id]
        _raw, reference = _reference_payload(scene_id)
        expected = json.loads(
            (REPO_ROOT / binding.expected_bundle.identifier).read_text(encoding="utf-8")
        )
        approach_text = reference["arrival_prose"][0]["text"]
        marker = next(
            item["exact_value"]
            for item in expected["source_facts"]["guarded_content_markers"]
            if type(item.get("exact_value")) is str
            and 0 < len(item["exact_value"]) <= 200
            and item["exact_value"] not in approach_text
        )
        reference["arrival_prose"][0]["text"] = approach_text + " " + marker
        with _network_tripwire():
            report = validate_delta_output(_json_bytes(reference), scene_id=scene_id)
        self.assertEqual(report.deterministic_status, "FAIL")
        self.assertIn("GUARDED_CONTENT_LEAK", {item.code for item in report.diagnostics})
        self.assertEqual(report.semantic_review_status, "PENDING")
        self.assertEqual(report.owner_rating_status, "PENDING")

    def test_canonical_inputs_remain_immutable_and_hydration_never_writes(self) -> None:
        before_protocol = _tree_fingerprint(STUDY1_PROTOCOL_ROOT)
        self.assertEqual(before_protocol, (16, STUDY1_PROTOCOL_TREE_SHA256))
        before_runtime = _tree_fingerprint_if_present(STUDY1_RUNTIME_ROOT)
        canonical_paths = {
            reference.identifier: hashlib.sha256(
                (REPO_ROOT / reference.identifier).read_bytes()
            ).hexdigest()
            for binding in self.bindings.values()
            for reference in (binding.source_packet, binding.expected_bundle)
        }

        with _network_tripwire(), _no_write_tripwire():
            for scene_id in SCENE_ORDER:
                raw, _payload = _reference_payload(scene_id)
                canonical = hydration_module._load_canonical_inputs(scene_id)
                self.assertEqual(
                    canonical.source_packet_bytes,
                    (REPO_ROOT / canonical.source_packet_id).read_bytes(),
                )
                self.assertEqual(
                    canonical.expected_bundle_bytes,
                    (REPO_ROOT / canonical.expected_bundle_id).read_bytes(),
                )
                hydrated = hydrate_delta_output(raw, scene_id=scene_id)
                self.assertEqual(hydrated["scene_id"], scene_id)
                expected = canonical.expected_inputs_copy()
                topology = expected["approved_topology"]
                source_rows = expected["source_facts"]["facts"]
                representable_source_rows = {
                    item["fact_id"]: item
                    for item in source_rows
                    if type(item.get("value")) in (str, bool, int, float)
                    or item.get("value") is None
                }
                source_facts = {
                    item["id"]: item
                    for item in hydrated["fixture"]["facts"]
                    if item["provenance"]["class"] == "source_extracted"
                }
                self.assertEqual(set(source_facts), set(representable_source_rows))
                for fact_id, source in representable_source_rows.items():
                    self.assertEqual(source_facts[fact_id]["value"], source["value"])
                    self.assertEqual(
                        source_facts[fact_id]["provenance"],
                        {
                            "class": "source_extracted",
                            "source_refs": [source["source_ref"]],
                        },
                    )
                audience_knowledge = {
                    item["fact_id"]: item
                    for item in hydrated["fixture"]["extension_seams"][
                        "audience_knowledge"
                    ]
                }
                self.assertEqual(
                    set(audience_knowledge),
                    {item["fact_id"] for item in source_rows},
                )
                for source in source_rows:
                    self.assertEqual(
                        audience_knowledge[source["fact_id"]],
                        {
                            "fact_id": source["fact_id"],
                            "audience": source["audience"],
                            "status": source["status"],
                            "source_pointer": source["source_pointer"],
                            "source_ref": source["source_ref"],
                            "value": source.get("value"),
                        },
                    )
                self.assertEqual(
                    hydrated["arrival"]["source_provenance"],
                    {
                        "source_ref": expected["source_facts"]["source_reference"],
                        "path": expected["source_facts"]["source_file"],
                        "section": expected["source_facts"]["source_packet_path"]
                        .rsplit("/", 1)[-1]
                        .removesuffix(".json"),
                        "sha256": expected["source_facts"]["source_file_sha256"],
                        "source_kind": "published_module",
                        "legacy_truth_verified": False,
                    },
                )
                self.assertEqual(
                    hydrated["fixture"]["extension_seams"]["unknown_metrics"],
                    expected["protected_unknowns"]["unknowns"],
                )
                self.assertEqual(hydrated["arrival"]["topology"], topology)
                self.assertEqual(
                    [item["id"] for item in hydrated["fixture"]["fixed_anchors"]],
                    topology["fixed_anchor_ids"],
                )
                self.assertEqual(
                    [
                        item["id"]
                        for item in hydrated["fixture"]["initial_mobile_occupants"]
                    ],
                    topology["mobile_occupant_ids"],
                )
                nodes = {item["id"]: item["kind"] for item in topology["nodes"]}
                role_by_entity = {
                    entity_id: role
                    for role, entity_ids in topology["stage_role_bindings"].items()
                    for entity_id in entity_ids
                }
                self.assertEqual(
                    [item["kind"] for item in hydrated["fixture"]["fixed_anchors"]],
                    [
                        topology["stage_role_entity_kinds"].get(
                            role_by_entity.get(entity_id), nodes[entity_id]
                        )
                        for entity_id in topology["fixed_anchor_ids"]
                    ],
                )
                self.assertEqual(
                    [
                        item["kind"]
                        for item in hydrated["fixture"]["initial_mobile_occupants"]
                    ],
                    [nodes[entity_id] for entity_id in topology["mobile_occupant_ids"]],
                )
                report = validate_delta_output(raw, scene_id=scene_id)
                self.assertEqual(report.deterministic_status, "PASS")

        after_protocol = _tree_fingerprint(STUDY1_PROTOCOL_ROOT)
        self.assertEqual(after_protocol, before_protocol)
        self.assertEqual(_tree_fingerprint_if_present(STUDY1_RUNTIME_ROOT), before_runtime)
        self.assertEqual(
            canonical_paths,
            {
                path: hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()
                for path in canonical_paths
            },
        )

    def test_two_authored_ids_alias_stably_without_collision_or_value_changes(self) -> None:
        scene_id = SCENE_ORDER[0]
        binding = self.bindings[scene_id]
        raw, delta = _reference_payload(scene_id)
        authored_rows = delta["fixture_deltas"]["facts"]
        self.assertEqual(len(authored_rows), 2)

        with _network_tripwire():
            first = hydrate_delta_output(raw, scene_id=scene_id)
            second = hydrate_delta_output(raw, scene_id=scene_id)
        first_authored = [
            item
            for item in first["fixture"]["facts"]
            if item["provenance"]["class"] == "builder_authored"
        ]
        second_authored = [
            item
            for item in second["fixture"]["facts"]
            if item["provenance"]["class"] == "builder_authored"
        ]
        self.assertEqual(len(first_authored), len(authored_rows))
        self.assertEqual(len(second_authored), len(authored_rows))
        alias_map = {
            authored["fact_id"]: hydrated["id"]
            for authored, hydrated in zip(authored_rows, first_authored)
        }
        second_alias_map = {
            authored["fact_id"]: hydrated["id"]
            for authored, hydrated in zip(authored_rows, second_authored)
        }
        self.assertEqual(alias_map, second_alias_map)
        self.assertEqual(len(set(alias_map.values())), len(authored_rows))
        self.assertTrue(set(alias_map.values()).isdisjoint(binding.base_fact_ids))
        for authored, hydrated in zip(authored_rows, first_authored):
            self.assertEqual(hydrated["value"], authored["value"])
            self.assertEqual(hydrated["provenance"]["class"], "builder_authored")

        for delta_group, hydrated_group in zip(
            delta["claims"], first["arrival"]["claims"]
        ):
            self.assertEqual(delta_group["segment_id"], hydrated_group["segment_id"])
            self.assertEqual(
                len(delta_group["items"]), len(hydrated_group["claims"])
            )
            for delta_claim, hydrated_claim in zip(
                delta_group["items"], hydrated_group["claims"]
            ):
                self.assertEqual(
                    hydrated_claim["fact_id"],
                    alias_map.get(delta_claim["fact_id"], delta_claim["fact_id"]),
                )

        expected_relations = {
            (
                alias_map[item["fact_id"]],
                item["subject_id"],
                item["predicate"],
                item["object_id"],
            )
            for item in authored_rows
            if item["predicate"]
            in ("approach_to_threshold", "threshold_to_focal")
        }
        hydrated_relations = {
            (item["fact_id"], item["from_id"], item["predicate"], item["to_id"])
            for item in first["fixture"]["extension_seams"]["stage_relations"]
        }
        self.assertEqual(hydrated_relations, expected_relations)


class Study2ExecutionFenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with _network_tripwire():
            cls.bindings = load_frozen_bindings()

    def setUp(self) -> None:
        STUDY2_TEST_SCRATCH.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="study2-execution-test-",
            dir=STUDY2_TEST_SCRATCH,
        )
        self.root = Path(self.temp_dir.name)
        self.root_patch = ExitStack()
        self.root_patch.enter_context(_study2_root_patch(self.root))
        self.addCleanup(self.root_patch.close)
        self.addCleanup(self.temp_dir.cleanup)
        self.bundle = _synthetic_study2_bundle()

    def _client(self, run_id: str = "synthetic-run") -> tuple[Study2Client, ApprovalPins]:
        pins = _write_synthetic_approvals(self.root, self.bundle)
        client = Study2Client(run_id, pins)
        loader_patch = patch.object(
            client,
            "_load_frozen_bundle",
            return_value=self.bundle,
        )
        loader_patch.start()
        self.addCleanup(loader_patch.stop)
        return client, pins

    def _ledger_records(self, root: Path | None = None) -> list[dict[str, object]]:
        ledger_path = (root or self.root) / "study-attempt-ledger.jsonl"
        return [json.loads(line) for line in ledger_path.read_text(encoding="ascii").splitlines()]

    def _transport(
        self,
        body: bytes,
        *,
        root: Path | None = None,
        config_callback=None,
        http_callback=None,
    ) -> tuple[OpenRouterTransport, _FakeStudy2HTTP, list[str]]:
        callbacks: list[str] = []
        active_root = root or self.root

        def load_config() -> object:
            callbacks.append("config")
            if config_callback is not None:
                config_callback(active_root)
            return SimpleNamespace(OPENROUTER_API_KEY="synthetic-secret-token")

        def before_post() -> None:
            callbacks.append("http")
            if http_callback is not None:
                http_callback(active_root)

        fake_http = _FakeStudy2HTTP(200, body, before_post)
        return (
            OpenRouterTransport(http=fake_http, config_loader=load_config),
            fake_http,
            callbacks,
        )

    def test_direct_transport_and_invalid_reserved_dispatches_stop_before_config_or_http(self) -> None:
        config = _study2_generation_config()
        config_bytes = _json_bytes(config)
        request = _study2_transport_request(config)
        token = object()
        context = _synthetic_reserved_context(request, config_bytes, token)
        transport, fake_http, callbacks = self._transport(_study2_response())

        with _network_tripwire(), self.assertRaises(Study2TransportError) as caught:
            transport(STUDY2_ENDPOINT, request)
        self.assertEqual(str(caught.exception), "RESERVATION_REQUIRED")
        with _network_tripwire(), self.assertRaises(Study2TransportError) as caught:
            transport._dispatch_reserved(
                None,
                STUDY2_ENDPOINT,
                request,
                config_bytes,
                owner_token=token,
            )
        self.assertEqual(str(caught.exception), "RESERVATION_CAPABILITY_INVALID")
        with _network_tripwire(), self.assertRaises(Study2TransportError) as caught:
            transport._dispatch_reserved(
                context,
                STUDY2_ENDPOINT,
                request,
                config_bytes,
                owner_token=object(),
            )
        self.assertEqual(str(caught.exception), "RESERVATION_CAPABILITY_INVALID")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])

        base_config = _study2_generation_config()
        base_config_bytes = _json_bytes(base_config)
        base_request = _study2_transport_request(base_config)
        cases = (
            ("reserved_request_changed", "RESERVED_REQUEST_HASH_MISMATCH"),
            ("reserved_config_hash_changed", "GENERATION_CONFIG_HASH_MISMATCH"),
            ("wrong_endpoint", "FROZEN_REQUEST_REQUIRED"),
            ("wrong_model", "FROZEN_MODEL_REQUIRED"),
            ("models_array", "FROZEN_REQUEST_REQUIRED"),
            ("fallback", "GENERATION_CONFIG_INVALID"),
            ("tools", "GENERATION_CONFIG_INVALID"),
            ("redirect_flag", "FROZEN_REQUEST_REQUIRED"),
            ("stream", "GENERATION_CONFIG_INVALID"),
            ("reasoning", "GENERATION_CONFIG_INVALID"),
            ("unfrozen_parameter", "FROZEN_PARAMETERS_REQUIRED"),
        )
        for name, expected_error in cases:
            with self.subTest(case=name):
                candidate_config = copy.deepcopy(base_config)
                candidate_request = _study2_transport_request(candidate_config)
                endpoint: object = STUDY2_ENDPOINT
                config_bytes_for_dispatch = base_config_bytes
                capability_request = base_request
                capability_config_bytes = base_config_bytes

                if name == "reserved_request_changed":
                    candidate_request["messages"][0]["content"] = "changed after reserve"
                elif name == "reserved_config_hash_changed":
                    config_bytes_for_dispatch += b" "
                elif name == "wrong_endpoint":
                    endpoint = "https://invalid.example/chat/completions"
                elif name == "wrong_model":
                    candidate_request["model"] = "other/model"
                    capability_request = candidate_request
                elif name == "models_array":
                    candidate_request["models"] = [STUDY2_MODEL_ID]
                    capability_request = candidate_request
                elif name == "fallback":
                    candidate_config["provider"] = {"allow_fallbacks": True}
                    candidate_request = _study2_transport_request(candidate_config)
                    config_bytes_for_dispatch = _json_bytes(candidate_config)
                    capability_request = candidate_request
                    capability_config_bytes = config_bytes_for_dispatch
                elif name == "tools":
                    candidate_config["tools"] = [{"type": "function"}]
                    candidate_request = _study2_transport_request(candidate_config)
                    config_bytes_for_dispatch = _json_bytes(candidate_config)
                    capability_request = candidate_request
                    capability_config_bytes = config_bytes_for_dispatch
                elif name == "redirect_flag":
                    candidate_request["allow_redirects"] = True
                    capability_request = candidate_request
                elif name == "stream":
                    candidate_config["stream"] = True
                    candidate_request = _study2_transport_request(candidate_config)
                    config_bytes_for_dispatch = _json_bytes(candidate_config)
                    capability_request = candidate_request
                    capability_config_bytes = config_bytes_for_dispatch
                elif name == "reasoning":
                    candidate_config["reasoning"] = {"effort": "high"}
                    candidate_request["reasoning"] = {"effort": "high"}
                    config_bytes_for_dispatch = _json_bytes(candidate_config)
                    capability_request = candidate_request
                    capability_config_bytes = config_bytes_for_dispatch
                elif name == "unfrozen_parameter":
                    candidate_request["temperature"] = 0.7

                capability = _synthetic_reserved_context(
                    capability_request,
                    capability_config_bytes,
                    token,
                )
                if name in ("reserved_request_changed", "reserved_config_hash_changed", "unfrozen_parameter"):
                    capability = _synthetic_reserved_context(
                        base_request,
                        base_config_bytes,
                        token,
                    )
                case_transport, case_http, case_callbacks = self._transport(_study2_response())
                with _network_tripwire(), self.assertRaises(Study2TransportError) as caught:
                    case_transport._dispatch_reserved(
                        capability,
                        endpoint,
                        candidate_request,
                        config_bytes_for_dispatch,
                        owner_token=token,
                    )
                self.assertEqual(str(caught.exception), expected_error)
                self.assertEqual(case_callbacks, [])
                self.assertEqual(case_http.calls, [])

        with _network_tripwire(), self.assertRaises(Study2TransportError) as caught:
            study2_transport_module._UrllibHTTP().post(
                url=STUDY2_ENDPOINT,
                headers={},
                body=b"{}",
                timeout=1.0,
                allow_redirects=True,
            )
        self.assertEqual(str(caught.exception), "REDIRECTS_DISABLED")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])

    def test_public_root_apis_are_fixed_and_symlinked_roots_or_ledgers_are_denied(self) -> None:
        client_parameters = set(inspect.signature(Study2Client).parameters)
        ledger_parameters = set(inspect.signature(Study2Ledger).parameters)
        self.assertEqual(client_parameters, {"run_id", "approval_pins"})
        self.assertEqual(ledger_parameters, set())

        first = Study2Client("run-one")
        second = Study2Client("run-two")
        self.assertEqual(first.ledger_path, self.root / STUDY2_LEDGER_NAME)
        self.assertEqual(second.ledger_path, first.ledger_path)
        self.assertNotEqual(first.run_dir, second.run_dir)
        self.assertEqual(
            study2_ledger_module.REPO_ROOT / STUDY2_ROOT_RELATIVE,
            study2_ledger_module.REPO_ROOT / study2_ledger_module.STUDY2_ROOT_RELATIVE,
        )

        client, pins = self._client()
        binding = client._ledger_binding(
            self.bundle,
            pins.owner_approval_sha256,
            pins.overseer_approval_sha256,
        )
        actual_root = self.root / "real-root"
        actual_root.mkdir(mode=0o700)
        linked_root = self.root / "linked-root"
        linked_root.symlink_to(actual_root, target_is_directory=True)
        with _study2_root_patch(linked_root), self.assertRaises(Study2LedgerError) as caught:
            Study2Ledger().initialize(binding)
        self.assertEqual(str(caught.exception), "LEDGER_ROOT_INVALID")
        self.assertFalse((actual_root / STUDY2_LEDGER_NAME).exists())

        target = self.root / "ledger-target.jsonl"
        original_target = b"synthetic target remains untouched\n"
        target.write_bytes(original_target)
        ledger_link = self.root / STUDY2_LEDGER_NAME
        ledger_link.symlink_to(target)
        with self.assertRaises(Study2LedgerError) as caught:
            Study2Ledger().reserve(
                binding,
                scene_id=STUDY2_SCENE_ORDER[0],
                run_id="symlink-run",
                run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/symlink-run",
                request_sha256="1" * 64,
            )
        self.assertEqual(str(caught.exception), "LEDGER_MISSING_OR_UNSAFE")
        self.assertEqual(target.read_bytes(), original_target)

    def test_changed_manifest_artifact_or_approval_hash_refuses_before_new_reservation(self) -> None:
        client, pins = self._client()
        client.initialize_ledger()
        transport, fake_http, callbacks = self._transport(_study2_response())
        changed_hashes = dict(self.bundle.artifact_hashes)
        changed_hashes["synthetic-changed-artifact"] = "2" * 64
        changed_bundle = replace(
            self.bundle,
            manifest_sha256="3" * 64,
            artifact_hashes=changed_hashes,
        )
        with patch.object(client, "_load_frozen_bundle", return_value=changed_bundle):
            with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertEqual(str(caught.exception), "APPROVAL_BINDING_MISMATCH")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])
        self.assertEqual([row["event"] for row in self._ledger_records()], ["header"])

        owner_path = self.root / "owner-cap-approval.json"
        owner_path.write_bytes(owner_path.read_bytes() + b" ")
        with patch.object(client, "_load_frozen_bundle", return_value=self.bundle):
            with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertEqual(str(caught.exception), "EXTERNAL_APPROVAL_HASH_MISMATCH")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])
        self.assertEqual([row["event"] for row in self._ledger_records()], ["header"])

    def test_missing_or_changed_approval_refuses_before_reservation_credentials_and_http(self) -> None:
        client, _pins = self._client()
        client.initialize_ledger()
        self.assertEqual([row["event"] for row in self._ledger_records()], ["header"])

        overseer_path = self.root / "overseer-step-a-approval.json"
        overseer_path.unlink()
        transport, fake_http, callbacks = self._transport(_study2_response())
        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertEqual(str(caught.exception), "REQUIRED_APPROVAL_MISSING")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])
        self.assertEqual([row["event"] for row in self._ledger_records()], ["header"])

        _write_synthetic_approvals(self.root, self.bundle)
        owner_path = self.root / "owner-cap-approval.json"
        owner_path.write_bytes(owner_path.read_bytes() + b" ")
        transport, fake_http, callbacks = self._transport(_study2_response())
        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertEqual(str(caught.exception), "EXTERNAL_APPROVAL_HASH_MISMATCH")
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])
        self.assertEqual([row["event"] for row in self._ledger_records()], ["header"])

    def test_fake_dispatch_is_single_model_only_reserved_before_config_and_preserves_clean_bytes(self) -> None:
        client, _pins = self._client()
        client.initialize_ledger()
        raw_body = _study2_response()
        callback_order: list[str] = []

        def assert_reserved(_root: Path) -> None:
            records = self._ledger_records()
            self.assertEqual(records[-1]["event"], "reservation")
            callback_order.append(records[-1]["event"])

        transport, fake_http, callbacks = self._transport(
            raw_body,
            config_callback=assert_reserved,
            http_callback=assert_reserved,
        )
        with self.assertRaises(Study2TransportError) as caught:
            transport(STUDY2_ENDPOINT, {})
        self.assertEqual(str(caught.exception), "RESERVATION_REQUIRED")
        self.assertEqual(callbacks, [])

        with _network_tripwire():
            receipt = client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertEqual(callbacks, ["config", "http"])
        self.assertEqual(callback_order, ["reservation", "reservation"])
        self.assertEqual(len(fake_http.calls), 1)
        call = fake_http.calls[0]
        self.assertEqual(call["url"], STUDY2_ENDPOINT)
        self.assertIs(call["allow_redirects"], False)
        self.assertEqual(call["timeout"], 240.0)
        request = json.loads(call["body"].decode("ascii"))
        self.assertEqual(request["model"], STUDY2_MODEL_ID)
        self.assertEqual(request["max_tokens"], 3072)
        self.assertFalse(request["stream"])
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        self.assertEqual(request["provider"], {"allow_fallbacks": False})
        self.assertEqual(receipt.returned_model_id, STUDY2_MODEL_ID)
        self.assertEqual(receipt.upstream_provider, "OpenAI")
        self.assertEqual(receipt.usage["cost"], 0.0042)
        response_path = self.root / receipt.response_path
        self.assertEqual(response_path.read_bytes(), raw_body)
        self.assertEqual(receipt.response_sha256, hashlib.sha256(raw_body).hexdigest())
        records = self._ledger_records()
        self.assertEqual([row["event"] for row in records], ["header", "reservation", "result"])
        self.assertEqual(records[-1]["outcome"], "succeeded")
        self.assertEqual(records[-1]["receipt"]["usage"]["cost"], 0.0042)

    def test_reported_usage_shapes_round_trip_with_byok_and_studywide_cap(self) -> None:
        client, pins = self._client("usage-shapes-run")
        client.initialize_ledger()
        usage_shapes = [copy.deepcopy(value) for value in _primary_audit_usage_shapes()]
        usage_shapes[1]["is_byok"] = True

        for attempt_number, (scene_id, usage) in enumerate(
            zip(STUDY2_SCENE_ORDER, usage_shapes), start=1
        ):
            raw_body = _study2_response(usage=usage)
            transport, fake_http, callbacks = self._transport(raw_body)
            with self.subTest(attempt_number=attempt_number), _network_tripwire():
                receipt = client.send_once(scene_id, transport=transport)

            self.assertEqual(receipt.attempt_number, attempt_number)
            self.assertEqual(receipt.usage, usage)
            self.assertIs(type(receipt.usage["is_byok"]), bool)
            self.assertIs(receipt.usage["is_byok"], usage["is_byok"])
            self.assertEqual(len(fake_http.calls), 1)
            self.assertEqual(callbacks, ["config", "http"])
            response_path = self.root / receipt.response_path
            self.assertEqual(response_path.read_bytes(), raw_body)
            self.assertEqual(receipt.response_sha256, hashlib.sha256(raw_body).hexdigest())

            records = self._ledger_records()
            result = records[-1]
            self.assertEqual(result["event"], "result")
            self.assertEqual(result["outcome"], "succeeded")
            persisted_usage = result["receipt"]["usage"]
            self.assertEqual(persisted_usage, usage)
            self.assertIs(type(persisted_usage["is_byok"]), bool)
            self.assertIs(persisted_usage["is_byok"], usage["is_byok"])

        records = self._ledger_records()
        self.assertEqual(
            [row["event"] for row in records],
            ["header", "reservation", "result", "reservation", "result", "reservation", "result"],
        )
        self.assertEqual(
            [row["attempt_number"] for row in records if row["event"] == "reservation"],
            [1, 2, 3],
        )

        over_cap = Study2Client("usage-shapes-over-cap", pins)
        with patch.object(over_cap, "_load_frozen_bundle", return_value=self.bundle):
            transport, fake_http, callbacks = self._transport(_study2_response())
            with self.assertRaises(Study2ExecutionError) as caught:
                over_cap.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertIn("SCENE_ALLOCATION_UNAVAILABLE", str(caught.exception))
        self.assertEqual(fake_http.calls, [])
        self.assertEqual(callbacks, [])

    def test_invalid_reported_usage_consumes_and_stops_without_retry(self) -> None:
        usage_shapes = _primary_audit_usage_shapes()
        invalid_usage_cases = []

        bad_prompt_count = copy.deepcopy(usage_shapes[0])
        bad_prompt_count["prompt_tokens"] = True
        invalid_usage_cases.append(("boolean-prompt-count", _study2_response(usage=bad_prompt_count)))

        bad_cost = copy.deepcopy(usage_shapes[0])
        bad_cost["cost"] = True
        invalid_usage_cases.append(("boolean-cost", _study2_response(usage=bad_cost)))

        numeric_byok = copy.deepcopy(usage_shapes[0])
        numeric_byok["is_byok"] = 0
        invalid_usage_cases.append(("numeric-byok", _study2_response(usage=numeric_byok)))

        invalid_usage_cases.append(("empty-usage", _study2_response(usage={})))

        missing_counter = copy.deepcopy(usage_shapes[0])
        del missing_counter["total_tokens"]
        invalid_usage_cases.append(("missing-counter", _study2_response(usage=missing_counter)))

        arbitrary_boolean = copy.deepcopy(usage_shapes[0])
        arbitrary_boolean["debug_flag"] = False
        invalid_usage_cases.append(("arbitrary-boolean", _study2_response(usage=arbitrary_boolean)))

        nested_boolean = copy.deepcopy(usage_shapes[0])
        nested_boolean["completion_tokens_details"]["reasoning_tokens"] = True
        invalid_usage_cases.append(("nested-boolean", _study2_response(usage=nested_boolean)))

        nested_string = copy.deepcopy(usage_shapes[0])
        nested_string["cost_details"]["untrusted_metadata"] = "synthetic-untrusted-value"
        invalid_usage_cases.append(("nested-string", _study2_response(usage=nested_string)))

        secret_value = copy.deepcopy(usage_shapes[0])
        secret_value["api_key"] = "synthetic-untrusted-metadata"
        invalid_usage_cases.append(("string-metadata", _study2_response(usage=secret_value)))

        valid_body = _study2_response(usage=usage_shapes[0])
        for label, nonfinite in (("nan", b"NaN"), ("infinity", b"Infinity"), ("overflow", b"1e999")):
            body = valid_body.replace(b'"cost":0.0040938', b'"cost":' + nonfinite, 1)
            self.assertNotEqual(body, valid_body)
            invalid_usage_cases.append(("nonfinite-" + label, body))

        for label, raw_body in invalid_usage_cases:
            with self.subTest(case=label):
                case_root = self.root / ("invalid-usage-" + label)
                case_root.mkdir(mode=0o700)
                with _study2_root_patch(case_root):
                    pins = _write_synthetic_approvals(case_root, self.bundle)
                    client = Study2Client("invalid-usage-" + label, pins)
                    with patch.object(client, "_load_frozen_bundle", return_value=self.bundle):
                        client.initialize_ledger()
                        transport, fake_http, callbacks = self._transport(raw_body, root=case_root)
                        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
                        self.assertIn("RETURNED_IDENTITY_OR_USAGE_MISSING", str(caught.exception))
                        records = self._ledger_records(case_root)
                        self.assertEqual(records[-1]["outcome"], "failed")
                        self.assertEqual(records[-1]["failure_reason"], "returned_identity_or_usage_missing")
                        self.assertIs(records[-1]["stop_study"], True)
                        self.assertIsNone(records[-1]["receipt"]["usage"])
                        self.assertEqual(len(fake_http.calls), 1)
                        self.assertEqual(callbacks, ["config", "http"])

                        with self.assertRaises(Study2ExecutionError) as stopped:
                            client.send_once(STUDY2_SCENE_ORDER[1], transport=transport)
                        self.assertIn("LEDGER_STUDY_STOPPED", str(stopped.exception))
                        self.assertEqual(len(fake_http.calls), 1)
                        self.assertEqual(callbacks, ["config", "http"])

    def test_missing_or_mismatched_returned_identity_consumes_attempt_and_stops(self) -> None:
        cases = (
            ("wrong_model", _study2_response(model="other/model"), "RETURNED_MODEL_MISMATCH"),
            ("missing_provider", _study2_response(provider=None), "RETURNED_IDENTITY_OR_USAGE_MISSING"),
            ("missing_generation", _study2_response(generation_id=None), "RETURNED_IDENTITY_OR_USAGE_MISSING"),
        )
        for label, raw_body, expected_error in cases:
            with self.subTest(case=label):
                case_root = self.root / label
                case_root.mkdir(mode=0o700)
                with _study2_root_patch(case_root):
                    pins = _write_synthetic_approvals(case_root, self.bundle)
                    client = Study2Client("identity-run", pins)
                    with patch.object(client, "_load_frozen_bundle", return_value=self.bundle):
                        client.initialize_ledger()
                        transport, fake_http, callbacks = self._transport(
                            raw_body,
                            root=case_root,
                        )
                        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
                        self.assertIn(expected_error, str(caught.exception))
                        self.assertEqual(len(fake_http.calls), 1)
                        self.assertEqual(callbacks, ["config", "http"])
                        records = self._ledger_records(case_root)
                        self.assertEqual([row["event"] for row in records], ["header", "reservation", "result"])
                        self.assertEqual(records[-1]["outcome"], "failed")
                        self.assertIs(records[-1]["stop_study"], True)
                        self.assertEqual(records[-1]["failure_reason"], expected_error.lower())

                        with self.assertRaises(Study2ExecutionError):
                            client.send_once(STUDY2_SCENE_ORDER[1], transport=transport)
                        self.assertEqual(len(fake_http.calls), 1)
                        self.assertEqual(callbacks, ["config", "http"])

    def test_non_200_response_consumes_and_stops_without_continuation(self) -> None:
        client, _pins = self._client()
        client.initialize_ledger()
        callbacks: list[str] = []
        fake_http = _FakeStudy2HTTP(503, _study2_response(), lambda: callbacks.append("http"))
        transport = OpenRouterTransport(
            http=fake_http,
            config_loader=lambda: callbacks.append("config")
            or SimpleNamespace(OPENROUTER_API_KEY="synthetic-secret-token"),
        )
        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertIn("HTTP_STATUS_ERROR", str(caught.exception))
        records = self._ledger_records()
        self.assertEqual([row["event"] for row in records], ["header", "reservation", "result"])
        self.assertEqual(records[-1]["failure_reason"], "http_status_error")
        self.assertIs(records[-1]["stop_study"], True)
        self.assertEqual(callbacks, ["config", "http"])
        self.assertEqual(len(fake_http.calls), 1)

        with self.assertRaises(Study2ExecutionError) as caught:
            client.send_once(STUDY2_SCENE_ORDER[1], transport=transport)
        self.assertIn("LEDGER_STUDY_STOPPED", str(caught.exception))
        self.assertEqual(len(fake_http.calls), 1)
        self.assertEqual(callbacks, ["config", "http"])

    def test_provider_secret_echoes_are_redacted_for_literal_escaped_duplicate_and_malformed_json(self) -> None:
        secret = "synthetic-secret-token"
        unicode_escaped_secret = "".join("\\u%04x" % ord(character) for character in secret)
        clean_response = _study2_response().decode("ascii")
        response_prefix = clean_response[:-1]
        bodies = (
            (
                "literal_value",
                (response_prefix + ',"debug":"credential=' + secret + '"}').encode("ascii"),
            ),
            (
                "escaped_key_and_value",
                (
                    response_prefix
                    + ',"debug_'
                    + unicode_escaped_secret
                    + '":"credential='
                    + unicode_escaped_secret
                    + '"}'
                ).encode("ascii"),
            ),
            (
                "duplicate_key",
                (
                    response_prefix
                    + ',"debug":"credential='
                    + secret
                    + '","debug":"benign"}'
                ).encode("ascii"),
            ),
            (
                "malformed_json",
                ('{"debug":"credential=' + unicode_escaped_secret + '",]').encode("ascii"),
            ),
        )
        for label, raw_body in bodies:
            with self.subTest(case=label):
                case_root = self.root / label
                case_root.mkdir(mode=0o700)
                with _study2_root_patch(case_root):
                    pins = _write_synthetic_approvals(case_root, self.bundle)
                    client = Study2Client("secret-redaction-run", pins)
                    with patch.object(client, "_load_frozen_bundle", return_value=self.bundle):
                        client.initialize_ledger()
                        fake_http = _FakeStudy2HTTP(200, raw_body)
                        callbacks: list[str] = []

                        def config_loader() -> object:
                            callbacks.append("config")
                            return SimpleNamespace(OPENROUTER_API_KEY=secret)

                        transport = OpenRouterTransport(http=fake_http, config_loader=config_loader)
                        log_stream = io.StringIO()
                        log_handler = logging.StreamHandler(log_stream)
                        root_logger = logging.getLogger()
                        root_logger.addHandler(log_handler)
                        try:
                            with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                                client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
                        finally:
                            root_logger.removeHandler(log_handler)
                            log_handler.close()

                        self.assertIn("RETURNED_IDENTITY_OR_USAGE_MISSING", str(caught.exception))
                        self.assertIsNone(caught.exception.__context__)
                        self.assertIsNone(caught.exception.__cause__)
                        exception_text = "".join(traceback.format_exception(caught.exception))
                        self.assertNotIn(secret, exception_text)
                        self.assertNotIn(unicode_escaped_secret, exception_text)
                        self.assertNotIn(secret, log_stream.getvalue())
                        self.assertNotIn(unicode_escaped_secret, log_stream.getvalue())
                        records = self._ledger_records(case_root)
                        self.assertEqual(records[-1]["failure_reason"], "returned_identity_or_usage_missing")
                        self.assertIs(records[-1]["stop_study"], True)
                        saved = (case_root / records[-1]["response_path"]).read_bytes()
                        if label != "duplicate_key":
                            self.assertIn(b"[REDACTED]", saved)
                        for path in case_root.rglob("*"):
                            if path.is_file():
                                contents = path.read_bytes()
                                self.assertNotIn(secret.encode("ascii"), contents)
                                self.assertNotIn(unicode_escaped_secret.encode("ascii"), contents)
                        self.assertEqual(callbacks, ["config"])
                        self.assertEqual(len(fake_http.calls), 1)

                        with self.assertRaises(Study2ExecutionError) as stopped:
                            client.send_once(STUDY2_SCENE_ORDER[1], transport=transport)
                        self.assertIn("LEDGER_STUDY_STOPPED", str(stopped.exception))
                        self.assertEqual(callbacks, ["config"])
                        self.assertEqual(len(fake_http.calls), 1)

    def test_config_and_http_exceptions_never_leak_secrets_and_stop_study(self) -> None:
        secret = 'synthetic-"credential\\token'
        json_escaped_secret = json.dumps(secret, ensure_ascii=True)[1:-1]
        unicode_escaped_secret = "".join("\\u%04x" % ord(character) for character in secret)
        cases = ("config_loader", "http")
        for failure_point in cases:
            with self.subTest(failure_point=failure_point):
                case_root = self.root / ("exception-" + failure_point)
                case_root.mkdir(mode=0o700)
                with _study2_root_patch(case_root):
                    pins = _write_synthetic_approvals(case_root, self.bundle)
                    client = Study2Client("exception-run", pins)
                    with patch.object(client, "_load_frozen_bundle", return_value=self.bundle):
                        client.initialize_ledger()
                        config_calls: list[str] = []
                        http_calls: list[dict[str, object]] = []

                        def config_loader() -> object:
                            config_calls.append("config")
                            if failure_point == "config_loader":
                                raise RuntimeError("config secret=" + secret)
                            return SimpleNamespace(OPENROUTER_API_KEY=secret)

                        class RaisingHTTP:
                            def post(self, **kwargs: object) -> tuple[int, bytes]:
                                http_calls.append(dict(kwargs))
                                raise RuntimeError("HTTP secret=" + secret)

                        http = RaisingHTTP()
                        transport = OpenRouterTransport(http=http, config_loader=config_loader)
                        log_stream = io.StringIO()
                        log_handler = logging.StreamHandler(log_stream)
                        root_logger = logging.getLogger()
                        root_logger.addHandler(log_handler)
                        try:
                            with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
                                client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
                        finally:
                            root_logger.removeHandler(log_handler)
                            log_handler.close()

                        self.assertEqual(str(caught.exception), "TRANSPORT_FAILED; allocation consumed")
                        self.assertIsNone(caught.exception.__context__)
                        self.assertIsNone(caught.exception.__cause__)
                        exception_text = "".join(traceback.format_exception(caught.exception))
                        self.assertNotIn(secret, exception_text)
                        self.assertNotIn(json_escaped_secret, exception_text)
                        self.assertNotIn(unicode_escaped_secret, exception_text)
                        self.assertNotIn(secret, log_stream.getvalue())
                        self.assertNotIn(json_escaped_secret, log_stream.getvalue())
                        self.assertNotIn(unicode_escaped_secret, log_stream.getvalue())
                        records = self._ledger_records(case_root)
                        self.assertEqual([row["event"] for row in records], ["header", "reservation", "result"])
                        self.assertEqual(records[-1]["failure_reason"], "transport_failure")
                        self.assertIs(records[-1]["stop_study"], True)
                        for path in case_root.rglob("*"):
                            if path.is_file():
                                contents = path.read_bytes()
                                self.assertNotIn(secret.encode("ascii"), contents)
                                self.assertNotIn(json_escaped_secret.encode("ascii"), contents)
                                self.assertNotIn(unicode_escaped_secret.encode("ascii"), contents)
                        self.assertEqual(config_calls, ["config"])
                        self.assertEqual(len(http_calls), 0 if failure_point == "config_loader" else 1)

                        with self.assertRaises(Study2ExecutionError) as stopped:
                            client.send_once(STUDY2_SCENE_ORDER[1], transport=transport)
                        self.assertIn("LEDGER_STUDY_STOPPED", str(stopped.exception))
                        self.assertEqual(config_calls, ["config"])
                        self.assertEqual(len(http_calls), 0 if failure_point == "config_loader" else 1)

    def test_run_ids_share_the_same_ordered_studywide_cap(self) -> None:
        client_a, pins = self._client("run-alpha")
        client_a.initialize_ledger()
        clients = (
            client_a,
            Study2Client("run-beta", pins),
            Study2Client("run-gamma", pins),
        )
        for client in clients[1:]:
            patcher = patch.object(client, "_load_frozen_bundle", return_value=self.bundle)
            patcher.start()
            self.addCleanup(patcher.stop)

        receipts = []
        for scene_id, client in zip(STUDY2_SCENE_ORDER, clients):
            transport, fake_http, _callbacks = self._transport(_study2_response())
            with _network_tripwire():
                receipts.append(client.send_once(scene_id, transport=transport))
            self.assertEqual(len(fake_http.calls), 1)
        self.assertEqual([item.attempt_number for item in receipts], [1, 2, 3])
        self.assertEqual(
            [row["run_id"] for row in self._ledger_records() if row["event"] == "reservation"],
            ["run-alpha", "run-beta", "run-gamma"],
        )
        fourth = Study2Client("run-delta", pins)
        with patch.object(fourth, "_load_frozen_bundle", return_value=self.bundle):
            transport, fake_http, callbacks = self._transport(_study2_response())
            with self.assertRaises(Study2ExecutionError) as caught:
                fourth.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
            self.assertIn("SCENE_ALLOCATION_UNAVAILABLE", str(caught.exception))
            self.assertEqual(fake_http.calls, [])
            self.assertEqual(callbacks, [])
        self.assertEqual(
            self.root / "study-attempt-ledger.jsonl",
            client_a.ledger_path,
        )

    def test_missing_corrupt_and_pending_ledger_states_fail_closed_without_replay(self) -> None:
        client, pins = self._client()
        transport, fake_http, callbacks = self._transport(_study2_response())
        with _network_tripwire(), self.assertRaises(Study2ExecutionError) as caught:
            client.send_once(STUDY2_SCENE_ORDER[0], transport=transport)
        self.assertIn("LEDGER_MISSING_OR_UNSAFE", str(caught.exception))
        self.assertEqual(callbacks, [])
        self.assertEqual(fake_http.calls, [])
        self.assertFalse((self.root / "study-attempt-ledger.jsonl").exists())

        binding = client._ledger_binding(
            self.bundle,
            pins.owner_approval_sha256,
            pins.overseer_approval_sha256,
        )
        missing_ledger = Study2Ledger()
        with self.assertRaises(Study2LedgerError) as caught:
            missing_ledger.reserve(
                binding,
                scene_id=STUDY2_SCENE_ORDER[0],
                run_id="missing-run",
                run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/missing-run",
                request_sha256="a" * 64,
            )
        self.assertEqual(str(caught.exception), "LEDGER_MISSING_OR_UNSAFE")

        pending_root = self.root / "pending"
        with _study2_root_patch(pending_root):
            pending_ledger = Study2Ledger()
            pending_ledger.initialize(binding)
            pending_ledger.reserve(
                binding,
                scene_id=STUDY2_SCENE_ORDER[0],
                run_id="pending-run",
                run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/pending-run",
                request_sha256="b" * 64,
            )
            for scene_id in (STUDY2_SCENE_ORDER[0], STUDY2_SCENE_ORDER[1]):
                with self.subTest(pending_scene=scene_id), self.assertRaises(Study2LedgerError) as caught:
                    Study2Ledger().reserve(
                        binding,
                        scene_id=scene_id,
                        run_id="another-run",
                        run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/another-run",
                        request_sha256="c" * 64,
                    )
                self.assertEqual(str(caught.exception), "LEDGER_PENDING_RESERVATION")

        corrupt_root = self.root / "corrupt"
        with _study2_root_patch(corrupt_root):
            corrupt_ledger = Study2Ledger()
            corrupt_ledger.initialize(binding)
            corrupt_ledger.path.write_bytes(b"not-json\n")
            with self.assertRaises(Study2LedgerError) as caught:
                Study2Ledger().reserve(
                    binding,
                    scene_id=STUDY2_SCENE_ORDER[0],
                    run_id="corrupt-run",
                    run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/corrupt-run",
                    request_sha256="d" * 64,
                )
            self.assertEqual(str(caught.exception), "LEDGER_CORRUPT")

    def test_concurrent_reservations_cannot_create_two_pending_attempts(self) -> None:
        client, pins = self._client()
        binding = client._ledger_binding(
            self.bundle,
            pins.owner_approval_sha256,
            pins.overseer_approval_sha256,
        )
        ledger = Study2Ledger()
        ledger.initialize(binding)
        start = threading.Barrier(3)
        reserved: list[int] = []
        rejected: list[str] = []
        result_lock = threading.Lock()

        def reserve(run_id: str, request_hash: str) -> None:
            start.wait()
            try:
                attempt = Study2Ledger().reserve(
                    binding,
                    scene_id=STUDY2_SCENE_ORDER[0],
                    run_id=run_id,
                    run_root_relative=STUDY2_ROOT_RELATIVE + "/runs/" + run_id,
                    request_sha256=request_hash,
                )
                with result_lock:
                    reserved.append(attempt)
            except Study2LedgerError as error:
                with result_lock:
                    rejected.append(str(error))

        workers = (
            threading.Thread(target=reserve, args=("race-one", "e" * 64)),
            threading.Thread(target=reserve, args=("race-two", "f" * 64)),
        )
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(timeout=5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(reserved, [1])
        self.assertEqual(rejected, ["LEDGER_PENDING_RESERVATION"])
        self.assertEqual(
            [row["event"] for row in self._ledger_records()],
            ["header", "reservation"],
        )

    def test_mocked_missing_manifest_fails_closed_without_synthetic_execution_artifacts(self) -> None:
        client = Study2Client("manifest-missing")

        def missing_manifest(relative_path: object) -> bytes:
            self.assertEqual(
                relative_path,
                study2_client_module.STUDY2_PROTOCOL_RELATIVE
                + "/"
                + study2_client_module.MANIFEST_NAME,
            )
            raise Study2ExecutionError("FROZEN_FILE_UNAVAILABLE")

        with patch.object(
            study2_client_module,
            "_read_project_file",
            side_effect=missing_manifest,
        ), self.assertRaises(Study2ExecutionError) as caught:
            client.build_request(STUDY2_SCENE_ORDER[0])
        self.assertEqual(str(caught.exception), "FROZEN_FILE_UNAVAILABLE")
        self.assertFalse((self.root / STUDY2_LEDGER_NAME).exists())

    def test_offline_sizing_uses_byte_approximation_and_exact_rounding(self) -> None:
        self.assertEqual(approximate_tokens("\u00e9"), 1)
        self.assertEqual(approximate_tokens("abcd"), 2)
        self.assertEqual(
            sizing_proposal({"a": 1000, "b": 900, "c": 1100}),
            {"largest_estimate": 1100, "max_tokens": 6144, "timeout_seconds": 360},
        )
        self.assertEqual(study2_materialize_module.OWNER_APPROVED_MAX_TOKENS, 16384)
        self.assertEqual(study2_materialize_module.OWNER_APPROVED_TIMEOUT_SECONDS, 720)
        self.assertEqual(
            cost_estimate(10, 20, "0.0000001", "0.0000005"),
            Decimal("0.0000110"),
        )
        for args in (
            (-1, 2, "0.1", "0.2"),
            (1.5, 2, "0.1", "0.2"),
            (1, 2, "NaN", "0.2"),
            (1, 2, "Infinity", "0.2"),
            (1, 2, "bad", "0.2"),
            (1, 2, "-0.1", "0.2"),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "UNPRICED/BLOCKED"):
                cost_estimate(*args)

    def test_materialized_manifest_artifact_hashes_match_fixed_roles(self) -> None:
        manifest_path = (
            study2_client_module.REPO_ROOT
            / study2_client_module.STUDY2_PROTOCOL_RELATIVE
            / study2_client_module.MANIFEST_NAME
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        generation_config = json.loads(
            (manifest_path.parent / "generation-config.json").read_text(encoding="utf-8")
        )
        for artifact in manifest["artifacts"].values():
            artifact_path = study2_client_module.REPO_ROOT / artifact["path"]
            self.assertEqual(
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                artifact["sha256"],
            )
        report_path = manifest_path.parent / "sizing-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(generation_config["max_tokens"], 16384)
        self.assertEqual(generation_config["timeout_seconds"], 720)
        self.assertEqual(manifest["attempt_cap"], 3)
        self.assertEqual(report["formula_proposal"]["max_tokens"], 6144)
        self.assertEqual(report["formula_proposal"]["timeout_seconds"], 360)
        self.assertEqual(report["max_tokens"], 16384)
        self.assertEqual(report["timeout_seconds"], 720)
        self.assertEqual(report["cost"]["total_usd"], "0.0298980")
        for scene_id in STUDY2_SCENE_ORDER:
            reference_path = STUDY2_REFERENCE_ROOT / (scene_id.replace(":", "__") + ".json")
            raw_reference = reference_path.read_bytes()
            row = report["scenes"][scene_id]
            self.assertEqual(row["reference_utf8_bytes"], len(raw_reference))
            self.assertEqual(row["reference_sha256"], hashlib.sha256(raw_reference).hexdigest())
            self.assertEqual(row["reference_estimated_tokens"], (len(raw_reference) + 2) // 3)
            request = Study2Client("offline-materialized-check").build_request(scene_id)
            self.assertEqual(request["model"], "openai/gpt-6-luna")
            self.assertEqual(len(request["messages"]), 2)
            self.assertEqual(request["max_tokens"], generation_config["max_tokens"])
            self.assertEqual(request["max_tokens"], 16384)
            self.assertEqual(
                row["request_input_estimated_tokens"],
                sum(approximate_tokens(message["content"]) for message in request["messages"]),
            )

    def test_materializer_check_uses_stored_rates_when_listing_is_absent(self) -> None:
        raw_path = study2_materialize_module.ROOT / study2_materialize_module.RAW
        original_exists = Path.exists

        def exists_without_listing(path: Path) -> bool:
            return False if path == raw_path else original_exists(path)

        with patch.object(Path, "exists", autospec=True, side_effect=exists_without_listing):
            checked = study2_materialize_module.generate(check=True)
            with self.assertRaisesRegex(ValueError, "UNPRICED/BLOCKED"):
                study2_materialize_module.generate(check=False)
        for relative, content in checked.items():
            self.assertEqual((study2_materialize_module.ROOT / relative).read_bytes(), content)
        report = json.loads(checked[f"{study2_materialize_module.P}/sizing-report.json"])
        self.assertFalse(report["cost"]["fresh_availability_confirmation"])
        self.assertIn("check-mode stored provenance", report["cost"]["rate_source"])

    def test_materializer_rejects_present_empty_truncated_or_mismatched_listing(self) -> None:
        raw_path = study2_materialize_module.ROOT / study2_materialize_module.RAW
        original_exists = Path.exists
        original_read_bytes = Path.read_bytes

        def exists_with_listing(path: Path) -> bool:
            return True if path == raw_path else original_exists(path)

        for listing in (b"", b"{}", b"x" * study2_materialize_module.RAW_SIZE):
            def read_listing(path: Path, raw: bytes = listing) -> bytes:
                return raw if path == raw_path else original_read_bytes(path)

            with self.subTest(size=len(listing)), patch.object(
                Path, "exists", autospec=True, side_effect=exists_with_listing
            ), patch.object(
                Path, "read_bytes", autospec=True, side_effect=read_listing
            ), self.assertRaisesRegex(ValueError, "UNPRICED/BLOCKED"):
                study2_materialize_module.generate(check=True)


if __name__ == "__main__":
    unittest.main()
