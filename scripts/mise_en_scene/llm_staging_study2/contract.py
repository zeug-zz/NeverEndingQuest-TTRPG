# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Strict, offline validation for the Study 2 delta-only output contract.

This module binds response references to the frozen Study 1 inputs. It does
not hydrate a full fixture, run the existing output gates, or perform I/O
other than read-only access to frozen protocol artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY1_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-protocol"
)
STUDY2_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-study2/protocol"
)
STUDY1_MANIFEST_RELATIVE = STUDY1_PROTOCOL_RELATIVE + "/staging-manifest.json"
INPUT_BINDINGS_RELATIVE = STUDY2_PROTOCOL_RELATIVE + "/input-bindings.json"
OUTPUT_SCHEMA_RELATIVE = STUDY2_PROTOCOL_RELATIVE + "/output-contract.schema.json"
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
CANONICALIZATION = "UTF-8 JSON; ensure_ascii=false; sort_keys=true; separators=(',', ':')"
MAX_DELTA_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_SHA256 = "cd254952bf85e31d6ad2bd91531021221eac74aa9bdd1a6970a0907848891e69"
_ROLE_NAMES = ("approach", "threshold", "focal_anchor", "usable_space")
_ARRIVAL_ROLES = ("approach", "threshold", "focal")
_ALLOWED_PREDICATES = {
    "approach_to_threshold",
    "threshold_to_focal",
    "usable_space",
    "light_gradient",
    "sound_gradient",
    "weather_gradient",
    "visible_affordance",
}


class ContractError(ValueError):
    """A safe contract failure with a metadata-only stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FrozenReference:
    """Immutable identity and content digest for one frozen input."""

    identifier: str
    sha256: str

    def as_dict(self) -> dict[str, str]:
        """Return a fresh JSON-ready copy, never a stored mutable alias."""

        return {"id": self.identifier, "sha256": self.sha256}


@dataclass(frozen=True)
class FrozenSceneBinding:
    """Immutable Study 1 references and structural allowlists for one scene."""

    scene_id: str
    source_packet: FrozenReference
    expected_bundle: FrozenReference
    topology: FrozenReference
    gate_canonical_context: FrozenReference
    module_id: str
    topology_node_ids: frozenset[str]
    role_bindings: Mapping[str, tuple[str, ...]]
    base_fact_ids: frozenset[str]
    public_base_fact_ids: frozenset[str]

    def input_refs(self) -> dict[str, Any]:
        """Return fresh input references bound to this scene."""

        return {
            "scene_id": self.scene_id,
            "source_packet": self.source_packet.as_dict(),
            "expected_bundle": self.expected_bundle.as_dict(),
            "topology": self.topology.as_dict(),
            "gate_canonical_context": self.gate_canonical_context.as_dict(),
        }


def load_frozen_bindings() -> Mapping[str, FrozenSceneBinding]:
    """Read and verify Study 1 input hashes, returning immutable bindings.

    Only IDs, hashes, topology node IDs, role-binding IDs, and fact IDs are
    retained. Source packet and expected-input objects are not returned.
    """

    manifest = _read_json_object(STUDY1_MANIFEST_RELATIVE)
    binding_document = _read_json_object(INPUT_BINDINGS_RELATIVE)
    if not _exact_keys(
        binding_document,
        {"schema", "study1_manifest_path", "canonicalization", "scenes"},
    ):
        raise ContractError("INPUT_BINDINGS_INVALID")
    if (
        binding_document.get("schema") != "neq.llm_staging_study2_input_bindings.v1"
        or binding_document.get("study1_manifest_path") != STUDY1_MANIFEST_RELATIVE
        or binding_document.get("canonicalization") != CANONICALIZATION
        or manifest.get("schema") != "neq.llm_staging_manifest.v1"
    ):
        raise ContractError("INPUT_BINDINGS_INVALID")

    manifest_scenes = manifest.get("scenes")
    binding_scenes = binding_document.get("scenes")
    if (
        type(manifest_scenes) is not list
        or type(binding_scenes) is not list
        or len(manifest_scenes) != len(SCENE_ORDER)
        or len(binding_scenes) != len(SCENE_ORDER)
        or [row.get("scene_id") for row in manifest_scenes if type(row) is dict] != list(SCENE_ORDER)
        or [row.get("scene_id") for row in binding_scenes if type(row) is dict] != list(SCENE_ORDER)
    ):
        raise ContractError("INPUT_BINDINGS_INVALID")

    artifacts = manifest.get("artifacts")
    if type(artifacts) is not dict:
        raise ContractError("STUDY1_MANIFEST_INVALID")

    result: dict[str, FrozenSceneBinding] = {}
    for manifest_scene, binding_scene in zip(manifest_scenes, binding_scenes):
        if type(manifest_scene) is not dict or type(binding_scene) is not dict:
            raise ContractError("INPUT_BINDINGS_INVALID")
        if not _exact_keys(
            binding_scene,
            {
                "scene_id",
                "source_packet",
                "expected_bundle",
                "topology",
                "gate_canonical_context",
            },
        ):
            raise ContractError("INPUT_BINDINGS_INVALID")
        scene_id = manifest_scene.get("scene_id")
        if scene_id != binding_scene.get("scene_id"):
            raise ContractError("INPUT_BINDINGS_INVALID")

        source_path = manifest_scene.get("source_packet_path")
        source_hash = manifest_scene.get("source_packet_sha256")
        expected_path = manifest_scene.get("expected_inputs_path")
        expected_hash = manifest_scene.get("expected_inputs_sha256")
        if any(
            type(item) is not str or not item
            for item in (scene_id, source_path, source_hash, expected_path, expected_hash)
        ):
            raise ContractError("STUDY1_MANIFEST_INVALID")
        if not _valid_ref_record(binding_scene.get("source_packet")) or not _valid_ref_record(
            binding_scene.get("expected_bundle")
        ):
            raise ContractError("INPUT_BINDINGS_INVALID")
        if (
            binding_scene["source_packet"] != {"id": source_path, "sha256": source_hash}
            or binding_scene["expected_bundle"] != {"id": expected_path, "sha256": expected_hash}
            or artifacts.get(source_path) != source_hash
            or artifacts.get(expected_path) != expected_hash
        ):
            raise ContractError("STUDY1_REFERENCE_MISMATCH")

        source_bytes = _read_project_file(source_path)
        expected_bytes = _read_project_file(expected_path)
        if _sha256(source_bytes) != source_hash or _sha256(expected_bytes) != expected_hash:
            raise ContractError("STUDY1_INPUT_HASH_MISMATCH")
        expected_inputs = _parse_json_object(expected_bytes, "STUDY1_EXPECTED_INPUTS_INVALID")
        if (
            expected_inputs.get("schema") != "neq.llm_staging_expected_inputs.v1"
            or expected_inputs.get("scene_id") != scene_id
        ):
            raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")

        topology = expected_inputs.get("approved_topology")
        source_facts = expected_inputs.get("source_facts")
        if (
            type(topology) is not dict
            or type(source_facts) is not dict
            or topology.get("scene_id") != scene_id
            or source_facts.get("scene_id") != scene_id
        ):
            raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
        topology_id = topology.get("topology_id")
        module_id = topology.get("module_id")
        if type(topology_id) is not str or type(module_id) is not str:
            raise ContractError("STUDY1_TOPOLOGY_INVALID")
        topology_canonical = _canonical_json_bytes(topology)
        topology_hash = _sha256(topology_canonical)
        if binding_scene.get("topology") != {"id": topology_id, "sha256": topology_hash}:
            raise ContractError("STUDY1_TOPOLOGY_MISMATCH")
        gate_context_id = scene_id + "#gate-canonical-context:" + topology_id
        if binding_scene.get("gate_canonical_context") != {
            "id": gate_context_id,
            "sha256": topology_hash,
        }:
            raise ContractError("STUDY1_CONTEXT_MISMATCH")

        nodes = topology.get("nodes")
        role_bindings_raw = topology.get("stage_role_bindings")
        if (
            type(nodes) is not list
            or type(role_bindings_raw) is not dict
            or set(role_bindings_raw) != set(_ROLE_NAMES)
        ):
            raise ContractError("STUDY1_TOPOLOGY_INVALID")
        node_ids: set[str] = set()
        for node in nodes:
            if type(node) is not dict or type(node.get("id")) is not str:
                raise ContractError("STUDY1_TOPOLOGY_INVALID")
            node_ids.add(node["id"])
        role_bindings: dict[str, tuple[str, ...]] = {}
        for role in _ROLE_NAMES:
            ids = role_bindings_raw.get(role)
            if (
                type(ids) is not list
                or not ids
                or any(type(item) is not str or item not in node_ids for item in ids)
                or len(ids) != len(set(ids))
            ):
                raise ContractError("STUDY1_TOPOLOGY_INVALID")
            role_bindings[role] = tuple(ids)

        fact_rows = source_facts.get("facts")
        if type(fact_rows) is not list:
            raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
        base_fact_ids: set[str] = set()
        public_fact_ids: set[str] = set()
        for fact in fact_rows:
            if type(fact) is not dict or type(fact.get("fact_id")) is not str:
                raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
            fact_id = fact["fact_id"]
            if fact_id in base_fact_ids:
                raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
            base_fact_ids.add(fact_id)
            if fact.get("audience") == "public_candidate_subject_to_semantic_review":
                public_fact_ids.add(fact_id)

        result[scene_id] = FrozenSceneBinding(
            scene_id=scene_id,
            source_packet=FrozenReference(source_path, source_hash),
            expected_bundle=FrozenReference(expected_path, expected_hash),
            topology=FrozenReference(topology_id, topology_hash),
            gate_canonical_context=FrozenReference(gate_context_id, topology_hash),
            module_id=module_id,
            topology_node_ids=frozenset(node_ids),
            role_bindings=MappingProxyType(dict(role_bindings)),
            base_fact_ids=frozenset(base_fact_ids),
            public_base_fact_ids=frozenset(public_fact_ids),
        )

    return MappingProxyType(result)


def validate_delta_payload(
    output_bytes: object,
    *,
    scene_id: str,
) -> Mapping[str, Any]:
    """Validate exact references and a closed delta payload; return immutable data."""

    if type(output_bytes) is not bytes or len(output_bytes) > MAX_DELTA_BYTES:
        raise ContractError("OUTPUT_BYTES_INVALID")
    if type(scene_id) is not str or scene_id not in SCENE_ORDER:
        raise ContractError("SCENE_NOT_APPROVED")
    active_bindings = load_frozen_bindings()
    binding = active_bindings.get(scene_id)
    if type(binding) is not FrozenSceneBinding or binding.scene_id != scene_id:
        raise ContractError("SCENE_BINDING_MISSING")

    try:
        payload = _parse_json_object(output_bytes, "OUTPUT_JSON_INVALID")
    except ContractError:
        raise
    schema = _load_delta_schema()
    try:
        schema_error = next(Draft202012Validator(schema).iter_errors(payload), None)
    except (RecursionError, TypeError, ValueError):
        raise ContractError("OUTPUT_SCHEMA_INVALID") from None
    if schema_error is not None:
        raise ContractError("OUTPUT_SCHEMA_REJECTED")

    references = payload["input_refs"]
    if references.get("scene_id") != scene_id:
        raise ContractError("SCENE_ID_MISMATCH")
    expected_refs = binding.input_refs()
    for reference_name in ("source_packet", "expected_bundle", "topology", "gate_canonical_context"):
        observed = references[reference_name]
        expected = expected_refs[reference_name]
        if observed["id"] != expected["id"]:
            raise ContractError("INPUT_REFERENCE_ID_MISMATCH")
        if observed["sha256"] != expected["sha256"]:
            raise ContractError("INPUT_REFERENCE_HASH_MISMATCH")

    _validate_delta_semantics(payload, binding)
    return _freeze_json(payload)


def _validate_delta_semantics(payload: dict[str, Any], binding: FrozenSceneBinding) -> None:
    stage_bindings = payload["stage_role_bindings"]
    for role in _ROLE_NAMES:
        if any(item not in binding.role_bindings[role] for item in stage_bindings[role]):
            raise ContractError("UNKNOWN_TOPOLOGY_ID")

    authored_facts = payload["fixture_deltas"]["facts"]
    authored_ids: set[str] = set()
    for fact in authored_facts:
        fact_id = fact["fact_id"]
        if fact_id in binding.base_fact_ids:
            raise ContractError("BASE_FACT_OVERWRITE")
        if not fact_id.startswith(binding.module_id + ":fact:study2-authored:"):
            raise ContractError("AUTHORED_FACT_ID_INVALID")
        if fact_id in authored_ids:
            raise ContractError("AUTHORED_FACT_ID_DUPLICATE")
        authored_ids.add(fact_id)
    for fact in authored_facts:
        if fact["predicate"] not in _ALLOWED_PREDICATES:
            raise ContractError("AUTHORED_PREDICATE_INVALID")
        if fact["subject_id"] not in binding.topology_node_ids:
            raise ContractError("UNKNOWN_TOPOLOGY_ID")
        object_id = fact["object_id"]
        if object_id is not None and object_id not in binding.topology_node_ids:
            raise ContractError("UNKNOWN_TOPOLOGY_ID")
        if fact["predicate"] in ("approach_to_threshold", "threshold_to_focal") and object_id is None:
            raise ContractError("STAGE_RELATION_INVALID")
        if fact["predicate"] == "approach_to_threshold" and (
            fact["subject_id"] not in stage_bindings["approach"]
            or object_id not in stage_bindings["threshold"]
            or fact["value"] is not True
        ):
            raise ContractError("STAGE_RELATION_INVALID")
        if fact["predicate"] == "threshold_to_focal" and (
            fact["subject_id"] not in stage_bindings["threshold"]
            or object_id not in stage_bindings["focal_anchor"]
            or fact["value"] is not True
        ):
            raise ContractError("STAGE_RELATION_INVALID")
        if fact["predicate"] == "usable_space" and fact["subject_id"] not in stage_bindings["usable_space"]:
            raise ContractError("STAGE_RELATION_INVALID")
        _validate_fact_value(fact["value"], binding, authored_ids)

    arrival_segments = payload["arrival_prose"]
    segment_ids: list[str] = []
    segment_text: dict[str, str] = {}
    for role, segment in zip(_ARRIVAL_ROLES, arrival_segments):
        expected_id = binding.scene_id + ":arrival:" + role
        if segment["role"] != role or segment["id"] != expected_id:
            raise ContractError("ARRIVAL_ROLE_BINDING_INVALID")
        segment_ids.append(segment["id"])
        segment_text[segment["id"]] = segment["text"]

    claim_groups = payload["claims"]
    if [group["segment_id"] for group in claim_groups] != segment_ids:
        raise ContractError("CLAIM_SEGMENT_BINDING_INVALID")
    seen_claim_ids: set[str] = set()
    known_claim_facts = binding.public_base_fact_ids | authored_ids
    for group in claim_groups:
        text = segment_text[group["segment_id"]]
        for claim in group["items"]:
            if not claim["id"].startswith(binding.scene_id + ":claim:"):
                raise ContractError("CLAIM_ID_INVALID")
            if claim["id"] in seen_claim_ids:
                raise ContractError("CLAIM_ID_DUPLICATE")
            seen_claim_ids.add(claim["id"])
            if claim["fact_id"] not in known_claim_facts:
                raise ContractError("CLAIM_FACT_REFERENCE_INVALID")
            if claim["span"] not in text:
                raise ContractError("CLAIM_SPAN_INVALID")
            if claim["kind"] == "invitation":
                if claim["choice"] != "open" or claim["success"] != "unspecified":
                    raise ContractError("INVITATION_AGENCY_INVALID")
            elif claim["choice"] is not None or claim["success"] is not None:
                raise ContractError("CLAIM_AGENCY_FIELDS_INVALID")


def _validate_fact_value(value: object, binding: FrozenSceneBinding, authored_ids: set[str]) -> None:
    if type(value) is dict:
        kind = value.get("kind")
        if kind == "entity_ref" and value.get("entity_id") not in binding.topology_node_ids:
            raise ContractError("UNKNOWN_TOPOLOGY_ID")
        if kind == "fact_ref" and value.get("fact_id") not in (binding.public_base_fact_ids | authored_ids):
            raise ContractError("FACT_VALUE_REFERENCE_INVALID")


def _load_delta_schema() -> dict[str, Any]:
    try:
        contents = _read_project_file(OUTPUT_SCHEMA_RELATIVE)
    except ContractError:
        raise ContractError("OUTPUT_SCHEMA_UNAVAILABLE") from None
    if _sha256(contents) != _SCHEMA_SHA256:
        raise ContractError("OUTPUT_SCHEMA_UNAVAILABLE")
    try:
        schema = _parse_json_object(contents, "OUTPUT_SCHEMA_INVALID")
        Draft202012Validator.check_schema(schema)
        return schema
    except SchemaError:
        raise ContractError("OUTPUT_SCHEMA_INVALID") from None
    except ContractError:
        raise ContractError("OUTPUT_SCHEMA_INVALID") from None


def _read_json_object(relative_path: str) -> dict[str, Any]:
    return _parse_json_object(_read_project_file(relative_path), "FROZEN_JSON_INVALID")


def _read_project_file(relative_path: str) -> bytes:
    raw = PurePosixPath(relative_path)
    if raw.is_absolute() or not raw.parts or any(part in ("", ".", "..") for part in raw.parts):
        raise ContractError("FROZEN_PATH_INVALID")
    candidate = REPO_ROOT.joinpath(*raw.parts)
    current = REPO_ROOT
    try:
        for part in raw.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ContractError("FROZEN_PATH_INVALID")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ContractError("FROZEN_FILE_INVALID")
        return resolved.read_bytes()
    except ContractError:
        raise
    except (OSError, ValueError):
        raise ContractError("FROZEN_FILE_UNAVAILABLE") from None


def _parse_json_object(contents: bytes, error_code: str) -> dict[str, Any]:
    if type(contents) is not bytes:
        raise ContractError(error_code)
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise ContractError(error_code) from None
    if type(value) is not dict:
        raise ContractError(error_code)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError("non-standard constant")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite number")
    return parsed


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ContractError("FROZEN_TOPOLOGY_INVALID") from None


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _exact_keys(value: object, expected: set[str]) -> bool:
    return type(value) is dict and set(value) == expected


def _valid_ref_record(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == {"id", "sha256"}
        and type(value.get("id")) is str
        and bool(value["id"])
        and type(value.get("sha256")) is str
        and _SHA256_RE.fullmatch(value["sha256"]) is not None
    )


def _freeze_json(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_json(item) for item in value)
    return value


__all__ = [
    "ContractError",
    "FrozenReference",
    "FrozenSceneBinding",
    "load_frozen_bindings",
    "validate_delta_payload",
]
