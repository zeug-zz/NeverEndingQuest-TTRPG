# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Deterministic, provider-free gates for one staged Builder output."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

from ..contract import ApprovedTopology, validate_fixture
from ..coverage import validate_positional_coverage


_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_DIAGNOSTICS = 128
_FORBIDDEN_KNOWN_PREDICATES = {
    "access",
    "acoustic",
    "audible",
    "audibility",
    "bearing",
    "compass_bearing",
    "door",
    "door_exists",
    "doorway",
    "distance",
    "entrance",
    "exit",
    "line_of_sight",
    "light_gradient",
    "metric_distance",
    "movement_cost",
    "movement_legality",
    "scale",
    "sensory_gradient",
    "sensory_reach",
    "sound_gradient",
    "traversability",
    "traversal",
    "visibility",
    "visibility_gradient",
    "visible_from",
    "weather_gradient",
}


@dataclass(frozen=True)
class OutputDiagnostic:
    """One stable output-gate diagnostic without generated text."""

    code: str
    layer: str
    path: str


@dataclass(frozen=True)
class OutputGateReport:
    """Machine-gate outcome; semantic review and ratings remain pending."""

    scene_id: str
    artifact_sha256: str | None
    deterministic_status: str
    semantic_review_status: str
    owner_rating_status: str
    scene_status: str
    diagnostics: tuple[OutputDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a bounded JSON-safe report with no raw response text."""

        return {
            "schema": "neq.llm_staging_output_gate_report.v1",
            "scene_id": self.scene_id,
            "artifact_sha256": self.artifact_sha256,
            "deterministic_status": self.deterministic_status,
            "semantic_review_status": self.semantic_review_status,
            "owner_rating_status": self.owner_rating_status,
            "scene_status": self.scene_status,
            "diagnostics": [
                {"code": item.code, "layer": item.layer, "path": item.path}
                for item in self.diagnostics
            ],
        }


def validate_model_output(
    output_bytes: object,
    expected_inputs: object,
    scene_id: str,
    schema: object,
) -> OutputGateReport:
    """Validate JSON/schema/fixture/coverage/bindings against frozen inputs.

    The function deliberately does not claim that typed claims semantically
    describe their prose. Exact protected-marker scanning catches literal leaks
    only; a human Overseer review remains mandatory before owner access.
    """

    diagnostics: list[OutputDiagnostic] = []
    artifact_hash: str | None = None
    if type(output_bytes) is not bytes or len(output_bytes) > _MAX_OUTPUT_BYTES:
        return _report(scene_id, None, [OutputDiagnostic("OUTPUT_BYTES_INVALID", "schema", "$output")], blocked=True)
    artifact_hash = hashlib.sha256(output_bytes).hexdigest()
    if type(scene_id) is not str or not scene_id:
        return _report("", artifact_hash, [OutputDiagnostic("SCENE_ID_INVALID", "schema", "$scene_id")], blocked=True)
    expected_parts = _expected_parts(expected_inputs, scene_id)
    if expected_parts is None:
        return _report(scene_id, artifact_hash, [OutputDiagnostic("FROZEN_EXPECTED_INPUTS_INVALID", "schema", "$expected")], blocked=True)
    if not _is_supported_schema(schema):
        return _report(scene_id, artifact_hash, [OutputDiagnostic("OUTPUT_SCHEMA_INVALID", "schema", "$schema")], blocked=True)

    try:
        payload = json.loads(
            output_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return _report(scene_id, artifact_hash, [OutputDiagnostic("OUTPUT_JSON_INVALID", "schema", "$output")])
    if type(payload) is not dict:
        return _report(scene_id, artifact_hash, [OutputDiagnostic("OUTPUT_ROOT_TYPE", "schema", "$output")])

    schema_errors = _instance_errors(payload, schema, schema)
    for path in schema_errors[:_MAX_DIAGNOSTICS]:
        diagnostics.append(OutputDiagnostic("OUTPUT_SCHEMA", "schema", path))
    if len(schema_errors) > _MAX_DIAGNOSTICS:
        diagnostics.append(OutputDiagnostic("DIAGNOSTIC_LIMIT", "schema", "$output"))
    if diagnostics:
        return _report(scene_id, artifact_hash, diagnostics)

    if payload.get("scene_id") != scene_id:
        diagnostics.append(OutputDiagnostic("SCENE_ID_MISMATCH", "identity", "$.scene_id"))
    fixture = payload.get("fixture")
    arrival = payload.get("arrival")
    if type(fixture) is not dict or type(arrival) is not dict:
        diagnostics.append(OutputDiagnostic("OUTPUT_COMPONENT_SHAPE", "schema", "$output"))
        return _report(scene_id, artifact_hash, diagnostics)

    source_facts, topology, coverage, protected = expected_parts
    topology_contract = _approved_topology(topology)
    if topology_contract is None:
        return _report(scene_id, artifact_hash, [OutputDiagnostic("FROZEN_TOPOLOGY_INVALID", "schema", "$expected.approved_topology")], blocked=True)
    consulted_refs = tuple(
        sorted({
            item["source_ref"]
            for item in source_facts["facts"]
            if type(item) is dict and type(item.get("source_ref")) is str
        })
    )

    if fixture.get("scene", {}).get("id") != scene_id:
        diagnostics.append(OutputDiagnostic("FIXTURE_SCENE_ID_MISMATCH", "identity", "$.fixture.scene.id"))
    if arrival.get("fixture_id") != scene_id:
        diagnostics.append(OutputDiagnostic("ARRIVAL_FIXTURE_ID_MISMATCH", "identity", "$.arrival.fixture_id"))
    if arrival.get("topology") != topology:
        diagnostics.append(OutputDiagnostic("APPROVED_TOPOLOGY_CHANGED", "topology", "$.arrival.topology"))

    source_provenance = _source_provenance(source_facts)
    if arrival.get("source_provenance") != source_provenance:
        diagnostics.append(OutputDiagnostic("SOURCE_PROVENANCE_MISMATCH", "provenance", "$.arrival.source_provenance"))
    if arrival.get("metadata") != {
        "authorship": "builder_authored_initial_scene",
        "development_only": True,
        "held_out": False,
        "legacy_truth_verified": False,
        "llm_builder_tested": True,
    }:
        diagnostics.append(OutputDiagnostic("DEVELOPMENT_METADATA_MISMATCH", "provenance", "$.arrival.metadata"))

    fixture_result = validate_fixture(fixture, topology_contract, consulted_refs)
    diagnostics.extend(
        OutputDiagnostic(item.code, "schema", item.path)
        for item in fixture_result.diagnostics
    )
    coverage_report = validate_positional_coverage(
        fixture, coverage, topology_contract, consulted_refs
    )
    diagnostics.extend(
        OutputDiagnostic(item.code, item.layer, item.path)
        for item in coverage_report.diagnostics
        if item.code != "NOT_APPLICABLE"
    )

    _check_entity_bindings(fixture, topology, diagnostics)
    fact_map, expected_fact_map = _check_source_facts(fixture, source_facts, diagnostics)
    _check_protected_unknowns(fixture, protected, diagnostics)
    _check_arrival(arrival, fixture, fact_map, expected_fact_map, source_facts, topology, diagnostics)
    _check_guarded_markers(arrival, source_facts, diagnostics)

    return _report(scene_id, artifact_hash, diagnostics)


def extract_model_content(
    provider_body: bytes,
    *,
    expected_model_id: str,
    expected_generation_id: str,
) -> bytes:
    """Extract one assistant JSON-content string from a provider response."""

    if type(provider_body) is not bytes or len(provider_body) > _MAX_OUTPUT_BYTES:
        raise ValueError("provider response is missing or oversized")
    try:
        decoded = json.loads(
            provider_body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("provider response is not bounded valid JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("provider response root is not an object")
    if decoded.get("model") != expected_model_id or decoded.get("id") != expected_generation_id:
        raise ValueError("provider response identity does not match its receipt")
    choices = decoded.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise ValueError("provider response must contain exactly one choice")
    message = choices[0].get("message")
    if (
        type(message) is not dict
        or message.get("role") != "assistant"
        or "tool_calls" in message
    ):
        raise ValueError("provider response assistant message is missing")
    content = message.get("content")
    if type(content) is not str:
        raise ValueError("provider response content is not one text value")
    return content.encode("utf-8")


_SCHEMA_KEYWORDS = {
    "$defs", "$id", "$ref", "$schema", "additionalProperties", "const",
    "enum", "items", "maxItems", "maxLength", "minItems", "minLength",
    "pattern", "prefixItems", "properties", "required", "title", "type",
    "uniqueItems",
}
_JSON_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


def _is_supported_schema(schema: object) -> bool:
    """Check the bounded Draft 2020-12 subset used by the frozen output schema."""

    visiting: set[int] = set()

    def visit(value: object, depth: int) -> bool:
        if type(value) is bool:
            return True
        if type(value) is not dict or depth > 64 or id(value) in visiting:
            return False
        visiting.add(id(value))
        try:
            if any(type(key) is not str or key not in _SCHEMA_KEYWORDS for key in value):
                return False
            schema_type = value.get("type")
            if schema_type is not None:
                allowed_types = [schema_type] if type(schema_type) is str else schema_type
                if (
                    type(allowed_types) is not list
                    or not allowed_types
                    or any(type(item) is not str or item not in _JSON_TYPES for item in allowed_types)
                ):
                    return False
            for key in ("minItems", "maxItems", "minLength", "maxLength"):
                if key in value and (type(value[key]) is not int or value[key] < 0):
                    return False
            for key in ("uniqueItems",):
                if key in value and type(value[key]) is not bool:
                    return False
            if "pattern" in value:
                if type(value["pattern"]) is not str:
                    return False
                try:
                    re.compile(value["pattern"])
                except re.error:
                    return False
            if "required" in value:
                required = value["required"]
                if type(required) is not list or any(type(item) is not str for item in required) or len(set(required)) != len(required):
                    return False
            for key in ("properties", "$defs"):
                if key in value:
                    children = value[key]
                    if type(children) is not dict or any(
                        type(name) is not str or not visit(child, depth + 1)
                        for name, child in children.items()
                    ):
                        return False
            if "prefixItems" in value:
                children = value["prefixItems"]
                if type(children) is not list or any(not visit(child, depth + 1) for child in children):
                    return False
            for key in ("additionalProperties", "items"):
                if key in value and not visit(value[key], depth + 1):
                    return False
            reference = value.get("$ref")
            if reference is not None:
                if type(reference) is not str or not reference.startswith("#/$defs/"):
                    return False
                target: object = schema
                for raw_part in reference[2:].split("/"):
                    part = raw_part.replace("~1", "/").replace("~0", "~")
                    if type(target) is not dict or part not in target:
                        return False
                    target = target[part]
                if type(target) not in (dict, bool):
                    return False
            return True
        finally:
            visiting.remove(id(value))

    return visit(schema, 0)


def _instance_errors(instance: object, schema: object, root_schema: object) -> list[str]:
    errors: list[str] = []
    stack: set[tuple[int, int]] = set()

    def add(path: str) -> None:
        if len(errors) <= _MAX_DIAGNOSTICS:
            errors.append(path)

    def visit(value: object, rule: object, path: str, depth: int) -> None:
        if len(errors) > _MAX_DIAGNOSTICS:
            return
        if type(rule) is bool:
            if not rule:
                add(path)
            return
        if type(rule) is not dict or depth > 64:
            add(path)
            return
        marker = (id(value), id(rule))
        if marker in stack:
            add(path)
            return
        stack.add(marker)
        try:
            reference = rule.get("$ref")
            if type(reference) is str:
                target: object = root_schema
                for raw_part in reference[2:].split("/"):
                    target = target[raw_part.replace("~1", "/").replace("~0", "~")]
                visit(value, target, path, depth + 1)

            expected_type = rule.get("type")
            if expected_type is not None:
                expected_types = [expected_type] if type(expected_type) is str else expected_type
                if not any(_matches_json_type(value, item) for item in expected_types):
                    add(path)
                    return
            if "const" in rule and not _json_equal(value, rule["const"]):
                add(path)
            if "enum" in rule and not any(_json_equal(value, item) for item in rule["enum"]):
                add(path)
            if type(value) is dict:
                for required in rule.get("required", []):
                    if required not in value:
                        add(_property_path(path, required))
                properties = rule.get("properties", {})
                for key, child in properties.items():
                    if key in value:
                        visit(value[key], child, _property_path(path, key), depth + 1)
                additional = rule.get("additionalProperties", True)
                for key in value:
                    if key not in properties:
                        if additional is False:
                            add(path + ".*")
                        elif additional is not True:
                            visit(value[key], additional, path + ".*", depth + 1)
            if type(value) is list:
                if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", len(value)):
                    add(path)
                prefix = rule.get("prefixItems", [])
                for index, item in enumerate(value):
                    if index < len(prefix):
                        visit(item, prefix[index], _index_path(path, index), depth + 1)
                    elif "items" in rule:
                        visit(item, rule["items"], _index_path(path, index), depth + 1)
                if rule.get("uniqueItems") is True:
                    keys = [_canonical_json(item) for item in value]
                    if len(keys) != len(set(keys)):
                        add(path)
            if type(value) is str:
                if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", len(value)):
                    add(path)
                pattern = rule.get("pattern")
                if type(pattern) is str and re.search(pattern, value) is None:
                    add(path)
        except (KeyError, TypeError, ValueError, re.error, RecursionError):
            add(path)
        finally:
            stack.remove(marker)

    visit(instance, schema, "$", 0)
    return sorted(set(errors))


def _matches_json_type(value: object, expected: object) -> bool:
    return {
        "array": type(value) is list,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "null": value is None,
        "number": type(value) in (int, float),
        "object": type(value) is dict,
        "string": type(value) is str,
    }.get(expected, False)


def _json_equal(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    return type(left) is type(right) and left == right


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _property_path(path: str, name: str) -> str:
    return path + "[" + json.dumps(name, ensure_ascii=True) + "]"


def _index_path(path: str, index: int) -> str:
    return path + "[%d]" % index


def _expected_parts(value: object, scene_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    if (
        type(value) is not dict
        or set(value) != {"schema", "scene_id", "source_facts", "approved_topology", "reference_coverage", "protected_unknowns"}
        or value.get("schema") != "neq.llm_staging_expected_inputs.v1"
        or value.get("scene_id") != scene_id
    ):
        return None
    source_facts = value.get("source_facts")
    topology = value.get("approved_topology")
    coverage = value.get("reference_coverage")
    protected = value.get("protected_unknowns")
    if any(type(item) is not dict for item in (source_facts, topology, coverage, protected)):
        return None
    if source_facts.get("scene_id") != scene_id or topology.get("scene_id") != scene_id or protected.get("scene_id") != scene_id:
        return None
    if type(source_facts.get("facts")) is not list or type(protected.get("unknowns")) is not list:
        return None
    source_required = (
        "schema", "source_identity", "source_reference", "source_file",
        "source_file_sha256", "source_packet_sha256", "source_packet_path",
    )
    if any(type(source_facts.get(key)) is not str or not source_facts[key] for key in source_required):
        return None
    if (
        source_facts.get("schema") != "neq.llm_staging_source_facts.v1"
        or re.fullmatch(r"[0-9a-f]{64}", source_facts["source_file_sha256"]) is None
        or re.fullmatch(r"[0-9a-f]{64}", source_facts["source_packet_sha256"]) is None
        or type(source_facts.get("guarded_content_markers")) is not list
    ):
        return None
    if protected.get("schema") != "neq.llm_staging_protected_unknowns.v1" or not protected["unknowns"]:
        return None
    fact_ids: set[str] = set()
    for row in source_facts["facts"]:
        if (
            type(row) is not dict
            or any(
                type(row.get(key)) is not str or not row[key]
                for key in ("fact_id", "source_pointer", "source_ref", "status", "audience")
            )
            or row.get("status") != "source_extracted"
            or row.get("audience") not in {
                "public_candidate_subject_to_semantic_review",
                "gm_guarded",
                "schematic_reference_only",
                "source_reference_only",
            }
            or row["fact_id"] in fact_ids
        ):
            return None
        fact_ids.add(row["fact_id"])
    for marker in source_facts["guarded_content_markers"]:
        if (
            type(marker) is not dict
            or any(
                type(marker.get(key)) is not str or not marker[key]
                for key in ("source_field", "source_pointer", "marker_id", "exact_value")
            )
        ):
            return None
    if any(
        type(topology.get(key)) is not list
        for key in ("compass_frames", "fixed_anchor_ids", "mobile_occupant_ids", "nodes")
    ):
        return None
    if any(
        type(topology.get(key)) is not str
        for key in ("module_id", "topology_id", "scope_id", "scene_node_id")
    ):
        return None
    role_bindings = topology.get("stage_role_bindings")
    role_kinds = topology.get("stage_role_entity_kinds")
    if (
        type(role_bindings) is not dict
        or any(type(role_bindings.get(role)) is not list for role in ("approach", "threshold", "focal_anchor", "usable_space"))
        or type(role_kinds) is not dict
        or any(type(role_kinds.get(role)) is not str for role in ("approach", "threshold", "focal_anchor", "usable_space"))
        or any(type(item) is not dict or type(item.get("id")) is not str or type(item.get("kind")) is not str for item in topology["nodes"])
        or any(not role_bindings[role] or any(type(item) is not str for item in role_bindings[role]) for role in ("approach", "threshold", "focal_anchor", "usable_space"))
        or any(type(item) is not str for item in topology["fixed_anchor_ids"] + topology["mobile_occupant_ids"])
    ):
        return None
    if any(
        type(item) is not dict
        or type(item.get("predicate")) is not str
        or item.get("status") not in ("unknown", "not_tested")
        for item in protected["unknowns"]
    ):
        return None
    return source_facts, topology, coverage, protected


def _approved_topology(value: dict[str, Any]) -> ApprovedTopology | None:
    try:
        return ApprovedTopology(
            topology_id=value["topology_id"],
            module_id=value["module_id"],
            scene_id=value["scene_id"],
            scope_id=value["scope_id"],
            compass_frames=tuple(value["compass_frames"]),
            fixed_anchor_ids=tuple(value["fixed_anchor_ids"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _source_provenance(source_facts: dict[str, Any]) -> dict[str, Any]:
    source_ref = source_facts["source_reference"]
    source_file = source_facts["source_file"]
    packet = source_facts["source_packet_path"]
    return {
        "source_ref": source_ref,
        "path": source_file,
        "section": packet.rsplit("/", 1)[-1].removesuffix(".json"),
        "sha256": source_facts["source_file_sha256"],
        "source_kind": "published_module",
        "legacy_truth_verified": False,
    }


def _nonpublic_entity_ids(
    source_facts: dict[str, Any], topology: dict[str, Any]
) -> set[str]:
    module_id = topology.get("module_id")
    nodes = {
        item.get("id")
        for item in topology.get("nodes", [])
        if type(item) is dict and type(item.get("id")) is str
    }
    guarded: set[str] = set()
    public: set[str] = set()

    def collect_names(value: object, result: list[str]) -> None:
        if type(value) is dict:
            for key, child in value.items():
                if key == "name" and type(child) is str:
                    result.append(child)
                collect_names(child, result)
        elif type(value) is list:
            for child in value:
                collect_names(child, result)

    rows = source_facts.get("facts")
    if type(module_id) is not str or type(rows) is not list:
        return guarded
    for row in rows:
        if type(row) is not dict:
            continue
        names: list[str] = []
        collect_names(row.get("value"), names)
        for name in names:
            local = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if local:
                candidate = module_id + ":entity:" + local
                if candidate in nodes:
                    if row.get("audience") == "public_candidate_subject_to_semantic_review":
                        public.add(candidate)
                    else:
                        guarded.add(candidate)
    return guarded - public


def _check_entity_bindings(
    fixture: dict[str, Any], topology: dict[str, Any], diagnostics: list[OutputDiagnostic]
) -> None:
    nodes = {item["id"]: item for item in topology["nodes"] if type(item) is dict and type(item.get("id")) is str}
    role_bindings = topology["stage_role_bindings"]
    role_kinds = topology["stage_role_entity_kinds"]
    required_fixed = topology["fixed_anchor_ids"]
    required_mobile = topology["mobile_occupant_ids"]
    fixed = fixture.get("fixed_anchors")
    mobile = fixture.get("initial_mobile_occupants")
    if type(fixed) is not list or type(mobile) is not list:
        diagnostics.append(OutputDiagnostic("ENTITY_COLLECTION_SHAPE", "schema", "$.fixture"))
        return
    fixed_ids = [item.get("id") for item in fixed if type(item) is dict]
    mobile_ids = [item.get("id") for item in mobile if type(item) is dict]
    if len(fixed_ids) != len(set(fixed_ids)) or set(fixed_ids) != set(required_fixed):
        diagnostics.append(OutputDiagnostic("FIXED_ANCHOR_SET_MISMATCH", "identity", "$.fixture.fixed_anchors"))
    if len(mobile_ids) != len(set(mobile_ids)) or set(mobile_ids) != set(required_mobile):
        diagnostics.append(OutputDiagnostic("MOBILE_OCCUPANT_SET_MISMATCH", "identity", "$.fixture.initial_mobile_occupants"))
    endpoint_kinds: dict[str, str] = {}
    for role, ids in role_bindings.items():
        for entity_id in ids:
            endpoint_kinds[entity_id] = role_kinds[role]
    for collection, path, ids in (
        (fixed, "$.fixture.fixed_anchors", required_fixed),
        (mobile, "$.fixture.initial_mobile_occupants", required_mobile),
    ):
        for index, entity in enumerate(collection):
            if type(entity) is not dict:
                continue
            entity_id = entity.get("id")
            expected_kind = endpoint_kinds.get(entity_id, nodes.get(entity_id, {}).get("kind"))
            if expected_kind is None or entity.get("kind") != expected_kind:
                diagnostics.append(OutputDiagnostic("ENTITY_KIND_MISMATCH", "identity", "%s[%d].kind" % (path, index)))
            if path.endswith("initial_mobile_occupants") and entity.get("kind") in ("pc", "player_character"):
                diagnostics.append(OutputDiagnostic("PRIOR_PC_CONTAMINATION", "identity", "%s[%d].kind" % (path, index)))


def _check_source_facts(
    fixture: dict[str, Any], source_facts: dict[str, Any], diagnostics: list[OutputDiagnostic]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    candidate = fixture.get("facts")
    if type(candidate) is not list:
        return {}, {}
    expected_rows = source_facts["facts"]
    expected = {
        item["fact_id"]: item
        for item in expected_rows
        if type(item) is dict and type(item.get("fact_id")) is str
    }
    actual: dict[str, dict[str, Any]] = {}
    for index, fact in enumerate(candidate):
        if type(fact) is not dict or type(fact.get("id")) is not str:
            continue
        fact_id = fact["id"]
        actual[fact_id] = fact
        provenance = fact.get("provenance")
        source_record = expected.get(fact_id)
        if source_record is None:
            if type(provenance) is dict and provenance.get("class") == "source_extracted":
                diagnostics.append(OutputDiagnostic("UNEXPECTED_SOURCE_FACT", "provenance", "$.fixture.facts[%d].id" % index))
            continue
        if type(provenance) is not dict or provenance.get("class") != "source_extracted":
            diagnostics.append(OutputDiagnostic("SOURCE_FACT_PROVENANCE_MISMATCH", "provenance", "$.fixture.facts[%d].provenance" % index))
            continue
        if (
            fact.get("status") != "known"
            or fact.get("value") != source_record.get("value")
            or provenance.get("source_refs") != [source_record.get("source_ref")]
        ):
            diagnostics.append(OutputDiagnostic("SOURCE_FACT_VALUE_MISMATCH", "provenance", "$.fixture.facts[%d]" % index))
    return actual, expected


def _check_protected_unknowns(
    fixture: dict[str, Any], protected: dict[str, Any], diagnostics: list[OutputDiagnostic]
) -> None:
    seams = fixture.get("extension_seams")
    observed = seams.get("unknown_metrics") if type(seams) is dict else None
    if observed != protected["unknowns"]:
        diagnostics.append(OutputDiagnostic("PROTECTED_UNKNOWNS_CHANGED", "unknowns", "$.fixture.extension_seams.unknown_metrics"))
    if type(observed) is not list:
        return
    for index, item in enumerate(observed):
        if type(item) is dict and item.get("status") == "not_tested" and item.get("predicate") != "linked_view_or_frontage":
            diagnostics.append(OutputDiagnostic("UNAPPROVED_NOT_TESTED_STATUS", "unknowns", "$.fixture.extension_seams.unknown_metrics[%d]" % index))


def _check_arrival(
    arrival: dict[str, Any],
    fixture: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    source_fact_records: dict[str, dict[str, Any]],
    source_facts: dict[str, Any],
    topology: dict[str, Any],
    diagnostics: list[OutputDiagnostic],
) -> None:
    segments = arrival.get("arrival_segments")
    claims_by_segment = arrival.get("claims")
    if type(segments) is not list or type(claims_by_segment) is not list or len(segments) != 3 or len(claims_by_segment) != 3:
        return
    expected_roles = ("approach", "threshold", "focal")
    group_map: dict[str, dict[str, Any]] = {}
    group_indexes: dict[str, int] = {}
    for index, group in enumerate(claims_by_segment):
        if type(group) is not dict or type(group.get("segment_id")) is not str or type(group.get("claims")) is not list:
            diagnostics.append(OutputDiagnostic("CLAIM_GROUP_INVALID", "provenance", "$.arrival.claims[%d]" % index))
            continue
        if group["segment_id"] in group_map:
            diagnostics.append(OutputDiagnostic("CLAIM_GROUP_DUPLICATE", "provenance", "$.arrival.claims[%d].segment_id" % index))
        group_map[group["segment_id"]] = group
        group_indexes[group["segment_id"]] = index
    if len(group_map) != 3:
        diagnostics.append(OutputDiagnostic("CLAIM_GROUP_SET_MISMATCH", "provenance", "$.arrival.claims"))

    seen_claim_ids: set[str] = set()
    forbidden = _FORBIDDEN_KNOWN_PREDICATES
    seams = fixture.get("extension_seams")
    fixture_extents = seams.get("multi_cell_extents") if type(seams) is dict else None
    usable_binding = topology["stage_role_bindings"]["usable_space"]
    if fixture_extents != [{"entity_id": usable_binding[0], "status": "known", "schematic_cells": [[0, 0]], "reason": None}]:
        diagnostics.append(OutputDiagnostic("SCHEMATIC_EXTENT_MISMATCH", "coverage", "$.fixture.extension_seams.multi_cell_extents"))
    for fact_index, (fact_id, fact) in enumerate(facts.items()):
        expected_source = source_fact_records.get(fact_id)
        fact_provenance = fact.get("provenance")
        is_exact_source_fact = (
            type(expected_source) is dict
            and type(fact_provenance) is dict
            and fact_provenance.get("class") == "source_extracted"
            and fact.get("value") == expected_source.get("value")
        )
        if (
            fact.get("status") == "known"
            and _normalize_predicate(fact.get("predicate")) in forbidden
            and not is_exact_source_fact
        ):
            diagnostics.append(OutputDiagnostic("PROTECTED_UNKNOWN_PROMOTED", "unknowns", "$.fixture.facts[%d]" % fact_index))
    protected_entity_ids = _nonpublic_entity_ids(source_facts, topology)

    for index, segment in enumerate(segments):
        if type(segment) is not dict:
            continue
        path = "$.arrival.arrival_segments[%d]" % index
        if segment.get("role") != expected_roles[index]:
            diagnostics.append(OutputDiagnostic("ARRIVAL_ROLE_ORDER", "render", path + ".role"))
        group = group_map.get(segment.get("id"))
        claims = group.get("claims") if type(group) is dict else None
        claim_group_index = group_indexes.get(segment.get("id"), index)
        if type(claims) is not list:
            diagnostics.append(OutputDiagnostic("ARRIVAL_CLAIMS_MISSING", "provenance", path + ".fact_ids"))
            continue
        claim_fact_ids: list[str] = []
        for claim_index, claim in enumerate(claims):
            claim_path = "$.arrival.claims[%d].claims[%d]" % (claim_group_index, claim_index)
            if type(claim) is not dict:
                continue
            claim_id = claim.get("id")
            if type(claim_id) is str:
                if claim_id in seen_claim_ids:
                    diagnostics.append(OutputDiagnostic("CLAIM_ID_DUPLICATE", "provenance", claim_path + ".id"))
                seen_claim_ids.add(claim_id)
            fact_id = claim.get("fact_id")
            if type(fact_id) is not str:
                diagnostics.append(OutputDiagnostic("CLAIM_FACT_ID_INVALID", "provenance", claim_path + ".fact_id"))
                continue
            claim_fact_ids.append(fact_id)
            fact = facts.get(fact_id)
            if fact is None:
                diagnostics.append(OutputDiagnostic("CLAIM_FACT_MISSING", "provenance", claim_path + ".fact_id"))
                continue
            binding = {
                "fact_id": fact_id,
                "predicate": fact.get("predicate"),
                "subject_id": fact.get("subject_id"),
                "object_id": fact.get("object_id"),
                "status": fact.get("status"),
                "value": fact.get("value"),
                "provenance": fact.get("provenance"),
            }
            if any(claim.get(key) != value for key, value in binding.items()):
                diagnostics.append(OutputDiagnostic("CLAIM_BINDING_MISMATCH", "provenance", claim_path))
            if claim.get("span") not in segment.get("text", ""):
                diagnostics.append(OutputDiagnostic("CLAIM_SPAN_MISMATCH", "render", claim_path + ".span"))
            source_record = source_fact_records.get(fact_id)
            if source_record is not None and source_record.get("audience") != "public_candidate_subject_to_semantic_review":
                diagnostics.append(OutputDiagnostic("NONPUBLIC_FACT_IN_ARRIVAL", "knowledge", claim_path + ".fact_id"))
            predicate = _normalize_predicate(fact.get("predicate"))
            is_exact_source_fact = (
                type(source_record) is dict
                and fact.get("provenance", {}).get("class") == "source_extracted"
                and fact.get("value") == source_record.get("value")
            )
            if fact.get("status") == "known" and predicate in forbidden and not is_exact_source_fact:
                diagnostics.append(OutputDiagnostic("PROTECTED_UNKNOWN_PROMOTED", "unknowns", claim_path + ".fact_id"))
            if any(claim.get(key) in protected_entity_ids for key in ("subject_id", "object_id")):
                diagnostics.append(OutputDiagnostic("NONPUBLIC_ENTITY_IN_ARRIVAL", "knowledge", claim_path))
            if claim.get("kind") == "invitation" and (
                claim.get("choice") != "open" or claim.get("success") != "unspecified"
            ):
                diagnostics.append(OutputDiagnostic("AGENCY_PRESCRIBED", "agency", claim_path))
        if segment.get("fact_ids") != claim_fact_ids:
            diagnostics.append(OutputDiagnostic("SEGMENT_FACT_BINDING_MISMATCH", "provenance", path + ".fact_ids"))

    _check_cue_states(arrival, facts, diagnostics)
    _check_next_section(arrival, diagnostics)


def _check_cue_states(
    arrival: dict[str, Any], facts: dict[str, dict[str, Any]], diagnostics: list[OutputDiagnostic]
) -> None:
    states = arrival.get("cue_states")
    expected_cues = ("light", "sound", "weather")
    if type(states) is not list or len(states) != len(expected_cues):
        diagnostics.append(OutputDiagnostic("CUE_STATES_SHAPE", "knowledge", "$.arrival.cue_states"))
        return
    for index, cue in enumerate(expected_cues):
        state = states[index]
        path = "$.arrival.cue_states[%d]" % index
        if type(state) is not dict or state.get("cue") != cue:
            diagnostics.append(OutputDiagnostic("CUE_ORDER_MISMATCH", "knowledge", path))
            continue
        status = state.get("status")
        fact_id = state.get("fact_id")
        if status == "not_applicable":
            if fact_id is not None or type(state.get("reason")) is not str or not state["reason"].strip():
                diagnostics.append(OutputDiagnostic("CUE_NONAPPLICABLE_INVALID", "knowledge", path))
        elif status == "unknown":
            if fact_id is not None or type(state.get("reason")) is not str or not state["reason"].strip():
                diagnostics.append(OutputDiagnostic("CUE_UNKNOWN_INVALID", "knowledge", path))
        elif status == "known":
            fact = facts.get(fact_id) if type(fact_id) is str else None
            if (
                fact is None
                or fact.get("predicate") != cue + "_gradient"
                or fact.get("status") != "known"
                or fact.get("provenance", {}).get("class") != "builder_authored"
            ):
                diagnostics.append(OutputDiagnostic("CUE_GRADIENT_UNSUPPORTED", "knowledge", path + ".fact_id"))
        else:
            diagnostics.append(OutputDiagnostic("CUE_STATUS_INVALID", "knowledge", path + ".status"))


def _check_next_section(arrival: dict[str, Any], diagnostics: list[OutputDiagnostic]) -> None:
    item = arrival.get("next_section")
    if type(item) is not dict:
        diagnostics.append(OutputDiagnostic("NEXT_SECTION_SHAPE", "knowledge", "$.arrival.next_section"))
        return
    provenance = item.get("provenance")
    if (
        item.get("status") != "unknown"
        or any(item.get(key) is not None for key in ("from_scene_id", "to_scene_id", "transition_fact_id", "perception_fact_id"))
        or type(provenance) is not dict
        or provenance.get("class") != "unknown"
        or provenance.get("source_refs") != []
        or type(item.get("reason")) is not str
        or not item["reason"].strip()
    ):
        diagnostics.append(OutputDiagnostic("NEXT_SECTION_NOT_PROTECTED_UNKNOWN", "unknowns", "$.arrival.next_section"))


def _check_guarded_markers(
    arrival: dict[str, Any], source_facts: dict[str, Any], diagnostics: list[OutputDiagnostic]
) -> None:
    markers = source_facts.get("guarded_content_markers")
    segments = arrival.get("arrival_segments")
    claims = arrival.get("claims")
    if type(markers) is not list or type(segments) is not list or type(claims) is not list:
        diagnostics.append(OutputDiagnostic("GUARDED_MARKER_INPUT_INVALID", "schema", "$.arrival"))
        return
    public_strings: list[str] = []
    for value in (segments, claims):
        _collect_strings(value, public_strings)
    for marker in markers:
        if type(marker) is not dict or type(marker.get("exact_value")) is not str:
            diagnostics.append(OutputDiagnostic("GUARDED_MARKER_INVALID", "schema", "$.expected.source_facts.guarded_content_markers"))
            return
        exact_value = marker["exact_value"]
        if exact_value and any(exact_value in text for text in public_strings):
            diagnostics.append(OutputDiagnostic("GUARDED_CONTENT_LEAK", "knowledge", "$.arrival"))


def _collect_strings(value: object, result: list[str]) -> None:
    if type(value) is str:
        result.append(value)
    elif type(value) is list:
        for item in value:
            _collect_strings(item, result)
    elif type(value) is dict:
        for item in value.values():
            _collect_strings(item, result)


def _normalize_predicate(value: object) -> str:
    if type(value) is not str:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _report(
    scene_id: str,
    artifact_hash: str | None,
    diagnostics: list[OutputDiagnostic],
    *,
    blocked: bool = False,
) -> OutputGateReport:
    unique = {(item.code, item.layer, item.path): item for item in diagnostics}
    ordered = tuple(sorted(unique.values(), key=lambda item: (item.layer, item.path, item.code)))
    if len(ordered) > _MAX_DIAGNOSTICS:
        ordered = ordered[:_MAX_DIAGNOSTICS] + (
            OutputDiagnostic("DIAGNOSTIC_LIMIT", "schema", "$output"),
        )
    deterministic = "BLOCKED" if blocked else ("PASS" if not ordered else "FAIL")
    return OutputGateReport(
        scene_id=scene_id,
        artifact_sha256=artifact_hash,
        deterministic_status=deterministic,
        semantic_review_status="PENDING",
        owner_rating_status="PENDING",
        scene_status="BLOCKED" if deterministic != "FAIL" else "FAIL",
        diagnostics=ordered,
    )


__all__ = ["OutputDiagnostic", "OutputGateReport", "extract_model_content", "validate_model_output"]
