# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Offline Study 2 delta hydration and Study 1 full-gate evaluation.

The delta is validated before any hydration. Frozen Study 1 inputs stay gate-
owned read-only bytes; each evaluation parses fresh copies, applies only the
closed delta, and calls the unchanged Study 1 output gates. Reports contain
hashes and bounded diagnostics, never output prose or semantic/owner verdicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from ..llm_staging.output_gates import (
    OutputDiagnostic,
    OutputGateReport,
    validate_model_output,
)
from .contract import (
    ContractError,
    FrozenSceneBinding,
    SCENE_ORDER,
    load_frozen_bindings,
    validate_delta_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY1_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-protocol"
)
STUDY1_MANIFEST_RELATIVE = STUDY1_PROTOCOL_RELATIVE + "/staging-manifest.json"
STUDY1_OUTPUT_SCHEMA_RELATIVE = STUDY1_PROTOCOL_RELATIVE + "/output-contract.schema.json"
MAX_DELTA_BYTES = 64 * 1024
MAX_CANONICAL_FILE_BYTES = 2 * 1024 * 1024
MAX_REPORT_DIAGNOSTICS = 128

_BLOCKED_CODES = {
    "CANONICAL_INPUTS_INVALID",
    "CANONICAL_INPUTS_UNAVAILABLE",
    "FROZEN_FILE_INVALID",
    "FROZEN_FILE_UNAVAILABLE",
    "FROZEN_PATH_INVALID",
    "FROZEN_JSON_INVALID",
    "FROZEN_TOPOLOGY_INVALID",
    "INPUT_BINDINGS_INVALID",
    "OUTPUT_SCHEMA_UNAVAILABLE",
    "OUTPUT_SCHEMA_INVALID",
    "SCENE_BINDING_MISSING",
    "STUDY1_EXPECTED_INPUTS_INVALID",
    "STUDY1_INPUT_HASH_MISMATCH",
    "STUDY1_MANIFEST_INVALID",
    "STUDY1_CONTEXT_MISMATCH",
    "STUDY1_OUTPUT_SCHEMA_HASH_MISMATCH",
    "STUDY1_REFERENCE_MISMATCH",
    "STUDY1_SOURCE_PACKET_INVALID",
    "STUDY1_TOPOLOGY_MISMATCH",
    "STUDY1_TOPOLOGY_INVALID",
}


@dataclass(frozen=True)
class CanonicalSceneInputs:
    """Immutable byte snapshots retained by the gate for one approved scene."""

    scene_id: str
    source_packet_id: str
    source_packet_sha256: str
    source_packet_bytes: bytes
    expected_bundle_id: str
    expected_bundle_sha256: str
    expected_bundle_bytes: bytes
    output_schema_sha256: str
    output_schema_bytes: bytes

    def expected_inputs_copy(self) -> dict[str, Any]:
        """Parse a fresh, mutable copy without exposing retained canonical state."""

        return _parse_json_object(
            self.expected_bundle_bytes, "STUDY1_EXPECTED_INPUTS_INVALID"
        )

    def output_schema_copy(self) -> dict[str, Any]:
        """Parse a fresh, mutable copy of the hash-verified Study 1 schema."""

        return _parse_json_object(
            self.output_schema_bytes, "OUTPUT_SCHEMA_INVALID"
        )


@dataclass(frozen=True)
class Study2OutputGateReport:
    """Bounded deterministic result; semantic review and owner ratings stay pending."""

    scene_id: str
    delta_artifact_sha256: str | None
    hydrated_output_sha256: str | None
    deterministic_status: str
    scene_status: str
    semantic_review_status: str
    owner_rating_status: str
    diagnostics: tuple[OutputDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a bounded metadata-only report with no response text."""

        return {
            "schema": "neq.llm_staging_study2_output_gate_report.v1",
            "scene_id": self.scene_id,
            "delta_artifact_sha256": self.delta_artifact_sha256,
            "hydrated_output_sha256": self.hydrated_output_sha256,
            "deterministic_status": self.deterministic_status,
            "scene_status": self.scene_status,
            "semantic_review_status": self.semantic_review_status,
            "owner_rating_status": self.owner_rating_status,
            "diagnostics": [
                {"code": item.code, "layer": item.layer, "path": item.path}
                for item in self.diagnostics[:MAX_REPORT_DIAGNOSTICS]
            ],
        }


def hydrate_delta_output(output_bytes: object, *, scene_id: str) -> dict[str, Any]:
    """Validate the closed delta, then build a fresh full Study 1 output in memory."""

    delta = validate_delta_payload(output_bytes, scene_id=scene_id)
    canonical = _load_canonical_inputs(scene_id)
    return _hydrate_validated_delta(delta, canonical)


def validate_delta_output(
    output_bytes: object, *, scene_id: str
) -> Study2OutputGateReport:
    """Run strict delta validation and every unchanged Study 1 output gate.

    The raw delta hash identifies exactly the submitted delta bytes. The
    hydrated output hash identifies the canonical full-output envelope passed
    to Study 1's gate; neither hash is a semantic or owner-review result.
    """

    raw_hash = _bounded_delta_hash(output_bytes)
    safe_scene_id = scene_id if type(scene_id) is str and scene_id in SCENE_ORDER else ""
    try:
        delta = validate_delta_payload(output_bytes, scene_id=scene_id)
        canonical = _load_canonical_inputs(scene_id)
        full_output = _hydrate_validated_delta(delta, canonical)
        hydrated_bytes = _canonical_json_bytes(full_output)
        old_report: OutputGateReport = validate_model_output(
            hydrated_bytes,
            canonical.expected_inputs_copy(),
            scene_id,
            canonical.output_schema_copy(),
        )
    except ContractError as error:
        status = "BLOCKED" if error.code in _BLOCKED_CODES else "FAIL"
        return Study2OutputGateReport(
            scene_id=safe_scene_id,
            delta_artifact_sha256=raw_hash,
            hydrated_output_sha256=None,
            deterministic_status=status,
            scene_status="BLOCKED" if status == "BLOCKED" else "FAIL",
            semantic_review_status="PENDING",
            owner_rating_status="PENDING",
            diagnostics=(OutputDiagnostic(error.code, "study2_contract", "$output"),),
        )

    diagnostics = tuple(
        OutputDiagnostic(item.code, item.layer, item.path)
        for item in old_report.diagnostics[:MAX_REPORT_DIAGNOSTICS]
    )
    return Study2OutputGateReport(
        scene_id=safe_scene_id,
        delta_artifact_sha256=raw_hash,
        hydrated_output_sha256=old_report.artifact_sha256,
        deterministic_status=old_report.deterministic_status,
        scene_status=old_report.scene_status,
        semantic_review_status="PENDING",
        owner_rating_status="PENDING",
        diagnostics=diagnostics,
    )


def _load_canonical_inputs(scene_id: str) -> CanonicalSceneInputs:
    bindings = load_frozen_bindings()
    binding = bindings.get(scene_id)
    if type(binding) is not FrozenSceneBinding or binding.scene_id != scene_id:
        raise ContractError("SCENE_BINDING_MISSING")

    expected_bytes = _read_study1_file(binding.expected_bundle.identifier, "expected")
    source_bytes = _read_study1_file(binding.source_packet.identifier, "source-packets")
    if (
        _sha256(expected_bytes) != binding.expected_bundle.sha256
        or _sha256(source_bytes) != binding.source_packet.sha256
    ):
        raise ContractError("STUDY1_INPUT_HASH_MISMATCH")

    expected = _parse_json_object(expected_bytes, "STUDY1_EXPECTED_INPUTS_INVALID")
    source_packet = _parse_json_object(source_bytes, "STUDY1_SOURCE_PACKET_INVALID")
    topology = expected.get("approved_topology")
    source_facts = expected.get("source_facts")
    protected_unknowns = expected.get("protected_unknowns")
    if (
        expected.get("schema") != "neq.llm_staging_expected_inputs.v1"
        or expected.get("scene_id") != scene_id
        or type(topology) is not dict
        or topology.get("scene_id") != scene_id
        or topology.get("topology_id") != binding.topology.identifier
        or type(source_facts) is not dict
        or source_facts.get("scene_id") != scene_id
        or source_facts.get("source_packet_path") != binding.source_packet.identifier
        or source_facts.get("source_packet_sha256") != binding.source_packet.sha256
        or type(protected_unknowns) is not dict
        or protected_unknowns.get("source_packet_sha256") != binding.source_packet.sha256
        or type(source_packet) is not dict
        or set(source_packet) != {"location", "map_room"}
        or type(source_packet.get("location")) is not dict
        or type(source_packet.get("map_room")) is not dict
    ):
        raise ContractError("CANONICAL_INPUTS_INVALID")
    if _sha256(_canonical_json_bytes(topology)) != binding.topology.sha256:
        raise ContractError("STUDY1_TOPOLOGY_MISMATCH")

    manifest_bytes = _read_project_file(STUDY1_MANIFEST_RELATIVE)
    manifest = _parse_json_object(manifest_bytes, "STUDY1_MANIFEST_INVALID")
    artifacts = manifest.get("artifacts")
    schema_digest = artifacts.get(STUDY1_OUTPUT_SCHEMA_RELATIVE) if type(artifacts) is dict else None
    schema_bytes = _read_project_file(STUDY1_OUTPUT_SCHEMA_RELATIVE)
    if (
        type(schema_digest) is not str
        or _sha256(schema_bytes) != schema_digest
    ):
        raise ContractError("STUDY1_OUTPUT_SCHEMA_HASH_MISMATCH")
    schema = _parse_json_object(schema_bytes, "OUTPUT_SCHEMA_INVALID")
    if schema.get("$id") != "neq.llm-staging-output.v1":
        raise ContractError("OUTPUT_SCHEMA_INVALID")

    return CanonicalSceneInputs(
        scene_id=scene_id,
        source_packet_id=binding.source_packet.identifier,
        source_packet_sha256=binding.source_packet.sha256,
        source_packet_bytes=source_bytes,
        expected_bundle_id=binding.expected_bundle.identifier,
        expected_bundle_sha256=binding.expected_bundle.sha256,
        expected_bundle_bytes=expected_bytes,
        output_schema_sha256=schema_digest,
        output_schema_bytes=schema_bytes,
    )


def _hydrate_validated_delta(
    validated_delta: Mapping[str, Any], canonical: CanonicalSceneInputs
) -> dict[str, Any]:
    delta = _plain_json(validated_delta)
    if type(delta) is not dict or delta.get("input_refs", {}).get("scene_id") != canonical.scene_id:
        raise ContractError("SCENE_ID_MISMATCH")

    expected = canonical.expected_inputs_copy()
    topology = expected["approved_topology"]
    coverage = expected["reference_coverage"]
    source_facts = expected["source_facts"]
    protected = expected["protected_unknowns"]
    base_fact_ids = {
        item["fact_id"]
        for item in source_facts["facts"]
        if type(item) is dict and type(item.get("fact_id")) is str
    }
    authored_fact_id_map: dict[str, str] = {}
    projected_fact_ids: set[str] = set()
    for item in delta["fixture_deltas"]["facts"]:
        authored_id = item["fact_id"]
        projected_id = _legacy_authored_fact_id(topology["module_id"], authored_id)
        if projected_id in base_fact_ids or projected_id in projected_fact_ids:
            raise ContractError("AUTHORED_FACT_ID_COLLISION")
        authored_fact_id_map[authored_id] = projected_id
        projected_fact_ids.add(projected_id)

    nodes = {
        item["id"]: item
        for item in topology["nodes"]
        if type(item) is dict and type(item.get("id")) is str
    }
    role_by_entity = {
        entity_id: role
        for role, entity_ids in topology["stage_role_bindings"].items()
        for entity_id in entity_ids
    }
    fixed_anchors = [
        {
            "id": entity_id,
            "kind": topology["stage_role_entity_kinds"].get(
                role_by_entity.get(entity_id), nodes[entity_id]["kind"]
            ),
        }
        for entity_id in topology["fixed_anchor_ids"]
    ]
    mobile_occupants = [
        {"id": entity_id, "kind": nodes[entity_id]["kind"]}
        for entity_id in topology["mobile_occupant_ids"]
    ]
    if any(item["kind"] in ("pc", "player_character") for item in mobile_occupants):
        raise ContractError("PRIOR_PC_CONTAMINATION")

    scene_node_id = topology["scene_node_id"]
    fixture_facts: list[dict[str, Any]] = []
    source_rows = source_facts["facts"]
    audience_knowledge: list[dict[str, Any]] = []
    for source in source_rows:
        if type(source) is not dict:
            raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
        source_id = source.get("fact_id")
        source_ref = source.get("source_ref")
        if type(source_id) is not str or type(source_ref) is not str:
            raise ContractError("STUDY1_EXPECTED_INPUTS_INVALID")
        audience_knowledge.append(
            {
                "fact_id": source_id,
                "audience": source["audience"],
                "status": source["status"],
                "source_pointer": source["source_pointer"],
                "source_ref": source_ref,
                "value": _plain_json(source.get("value")),
            }
        )
        value = source.get("value")
        if type(value) not in (str, bool, int, float) and value is not None:
            continue
        fixture_facts.append(
            {
                "id": source_id,
                "subject_id": scene_node_id,
                "predicate": "source_record",
                "object_id": scene_node_id,
                "status": "known",
                "value": value,
                "provenance": {
                    "class": "source_extracted",
                    "source_refs": [source_ref],
                },
            }
        )

    authored_facts: list[dict[str, Any]] = []
    for item in delta["fixture_deltas"]["facts"]:
        subject_id = item["subject_id"]
        object_id = item["object_id"]
        authored_facts.append(
            {
                "id": authored_fact_id_map[item["fact_id"]],
                "subject_id": subject_id,
                "predicate": item["predicate"],
                "object_id": object_id if object_id is not None else subject_id,
                "status": "known",
                "value": _legacy_scalar_value(item["value"], authored_fact_id_map),
                "provenance": {"class": "builder_authored", "source_refs": []},
            }
        )
    fixture_facts.extend(authored_facts)
    fact_map = {item["id"]: item for item in fixture_facts}

    claims_by_segment = {
        item["segment_id"]: item["items"] for item in delta["claims"]
    }
    segments: list[dict[str, Any]] = []
    claim_groups: list[dict[str, Any]] = []
    arrival_claim_rows: list[dict[str, Any]] = []
    for segment in delta["arrival_prose"]:
        segment_id = segment["id"]
        authored_claims = claims_by_segment[segment_id]
        fact_ids = [
            authored_fact_id_map.get(item["fact_id"], item["fact_id"])
            for item in authored_claims
        ]
        segments.append(
            {
                "id": segment_id,
                "role": segment["role"],
                "text": segment["text"],
                "fact_ids": fact_ids,
            }
        )
        full_claims: list[dict[str, Any]] = []
        for claim in authored_claims:
            fixture_fact_id = authored_fact_id_map.get(
                claim["fact_id"], claim["fact_id"]
            )
            fact = fact_map.get(fixture_fact_id)
            if fact is None:
                raise ContractError("CLAIM_FACT_NOT_MATERIALIZABLE")
            full_claims.append(
                {
                    "id": claim["id"],
                    "kind": "invitation" if claim["kind"] == "invitation" else "assertion",
                    "fact_id": fact["id"],
                    "predicate": fact["predicate"],
                    "subject_id": fact["subject_id"],
                    "object_id": fact["object_id"],
                    "status": fact["status"],
                    "value": fact["value"],
                    "provenance": _plain_json(fact["provenance"]),
                    "span": claim["span"],
                    "choice": claim["choice"],
                    "success": claim["success"],
                }
            )
        claim_groups.append({"segment_id": segment_id, "claims": full_claims})
        arrival_claim_rows.append(
            {"segment_id": segment_id, "fact_ids": fact_ids}
        )

    usable_space_id = delta["stage_role_bindings"]["usable_space"][0]
    relation_rows = [
        {
            "fact_id": item["id"],
            "from_id": item["subject_id"],
            "predicate": item["predicate"],
            "to_id": item["object_id"],
            "status": item["status"],
        }
        for item in authored_facts
        if item["predicate"] in ("approach_to_threshold", "threshold_to_focal")
    ]
    fixture = {
        "schema_version": 1,
        "module_id": topology["module_id"],
        "topology_id": topology["topology_id"],
        "scene": {
            "id": canonical.scene_id,
            "scope": {"id": topology["scope_id"], "kind": "area"},
            "orientation": _unknown_orientation(),
        },
        "fixed_anchors": fixed_anchors,
        "initial_mobile_occupants": mobile_occupants,
        "facts": fixture_facts,
        "extension_seams": {
            "multi_cell_extents": [
                {
                    "entity_id": usable_space_id,
                    "status": "known",
                    "schematic_cells": [[0, 0]],
                    "reason": None,
                }
            ],
            "stage_relations": relation_rows,
            "unknown_metrics": _plain_json(protected["unknowns"]),
            "audience_knowledge": audience_knowledge,
            "arrival_claims": arrival_claim_rows,
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
    unknown_provenance = {"class": "unknown", "source_refs": []}
    arrival = {
        "fixture_id": canonical.scene_id,
        "topology": _plain_json(topology),
        "arrival_segments": segments,
        "source_provenance": source_provenance,
        "metadata": {
            "authorship": "builder_authored_initial_scene",
            "development_only": True,
            "held_out": False,
            "legacy_truth_verified": False,
            # The frozen Study 1 gate envelope requires this legacy value. It is
            # not evidence that this hand-assembled reference was model-tested.
            "llm_builder_tested": True,
        },
        "orientation": _unknown_orientation(),
        "cue_states": [
            {
                "cue": cue,
                "status": "unknown",
                "fact_id": None,
                "reason": "No independent gradient fact is supplied.",
            }
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
    return {
        "schema": "neq.llm_staging_output.v1",
        "scene_id": canonical.scene_id,
        "fixture": fixture,
        "arrival": arrival,
    }


def _unknown_orientation() -> dict[str, Any]:
    return {
        "status": "unknown",
        "frame": None,
        "provenance": {"class": "unknown", "source_refs": []},
    }


def _legacy_scalar_value(
    value: object, authored_fact_id_map: Mapping[str, str]
) -> object:
    """Lower typed references to tagged scalars accepted by the frozen v1 fixture."""

    if type(value) is dict:
        kind = value.get("kind")
        if kind == "entity_ref" and type(value.get("entity_id")) is str:
            return "entity_ref:" + value["entity_id"]
        if kind == "fact_ref" and type(value.get("fact_id")) is str:
            fact_id = value["fact_id"]
            return "fact_ref:" + authored_fact_id_map.get(fact_id, fact_id)
        raise ContractError("DELTA_VALUE_NOT_MATERIALIZABLE")
    if value is None or type(value) in (str, bool, int):
        return value
    raise ContractError("DELTA_VALUE_NOT_MATERIALIZABLE")


def _legacy_authored_fact_id(module_id: str, authored_id: str) -> str:
    """Project the delta namespace into the legacy fixture's bounded fact ID."""

    digest = hashlib.sha256(authored_id.encode("utf-8")).hexdigest()
    return module_id + ":fact:s2-" + digest[:61]


def _read_study1_file(relative_path: str, expected_directory: str) -> bytes:
    prefix = STUDY1_PROTOCOL_RELATIVE + "/" + expected_directory + "/"
    if type(relative_path) is not str or not relative_path.startswith(prefix):
        raise ContractError("FROZEN_PATH_INVALID")
    return _read_project_file(relative_path)


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
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CANONICAL_FILE_BYTES:
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
        raise ContractError("CANONICAL_INPUTS_INVALID") from None


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_json(item) for item in value]
    if type(value) is list:
        return [_plain_json(item) for item in value]
    if type(value) is dict:
        return {key: _plain_json(item) for key, item in value.items()}
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bounded_delta_hash(value: object) -> str | None:
    if type(value) is not bytes or len(value) > MAX_DELTA_BYTES:
        return None
    return _sha256(value)


__all__ = [
    "CanonicalSceneInputs",
    "Study2OutputGateReport",
    "hydrate_delta_output",
    "validate_delta_output",
]
