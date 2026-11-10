# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3 delta parsing, semantic validation, and rule-to-source auditing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from . import protocol


# TABLETOP MODE: Isolated, provider-free Study 3 contract validator.
MAX_DELTA_BYTES = 65536
_UNSET = object()
_ROOT_FIELDS = (
    "schema",
    "input_refs",
    "fixture_deltas",
    "stage_role_bindings",
    "claims",
    "arrival_prose",
)
_REFERENCE_FIELDS = (
    "scene_id",
    "source_packet",
    "expected_bundle",
    "topology",
    "gate_canonical_context",
)
_REFERENCE_NAMES = _REFERENCE_FIELDS[1:]
_FACT_FIELDS = ("fact_id", "subject_id", "predicate", "object_id", "value")
_ROLE_NAMES = ("approach", "threshold", "focal_anchor", "usable_space")
_ARRIVAL_ROLES = ("approach", "threshold", "focal")
_CLAIM_FIELDS = ("id", "fact_id", "kind", "span", "choice", "success")
_PREDICATES = (
    "approach_to_threshold",
    "threshold_to_focal",
    "usable_space",
    "light_gradient",
    "sound_gradient",
    "weather_gradient",
    "visible_affordance",
)
_FACT_VALUE_SHAPES = (
    {"type": "string", "max_length": 512},
    {"type": "boolean"},
    {"type": "null"},
    {
        "type": "object",
        "kind": "entity_ref",
        "only_fields": ("kind", "entity_id"),
        "closed": True,
        "entity_id": "EXACT_SCENE_TOPOLOGY_NODE_ID",
    },
    {
        "type": "object",
        "kind": "fact_ref",
        "only_fields": ("kind", "fact_id"),
        "closed": True,
        "fact_id": "PUBLIC_BASE_FACT_ID_OR_STUDY3_AUTHORED_FACT_ID",
    },
)
_FACT_VALUE_SCHEMA = (
    {"type": "string", "maxLength": 512},
    {"type": "boolean"},
    {"type": "null"},
    {"$ref": "#/$defs/entity_ref_value"},
    {"$ref": "#/$defs/fact_ref_value"},
)
_UNKNOWN_PREDICATE_MAP = MappingProxyType(
    {"sensory_gradients": frozenset(("light_gradient", "sound_gradient", "weather_gradient"))}
)
_AGENCY_PATTERNS = (
    re.compile(r"\b(?:you|the party|the players?)\s+(?:choose|chose|decide|decided|select|selected)\b", re.I),
    re.compile(r"\b(?:you|the party|the players?)\s+(?:succeed|succeeds|succeeded)\b", re.I),
    re.compile(r"\b(?:you|the party|the players?)\s+successfully\s+\w+\b", re.I),
)


class _DuplicateKey(ValueError):
    pass


class _NonFinite(ValueError):
    pass


@dataclass(frozen=True)
class SourcePointer:
    """A source declaration that must remain paired with an output rule."""

    artifact: str
    pointer: str
    expected: Any = _UNSET
    contains: str | None = None
    binding_key: str | None = None
    expected_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class RuleSpec:
    """Stable rule ID, executable check association, and declaration sources."""

    rule_id: str
    check_id: str
    summary: str
    sources: tuple[SourcePointer, ...]
    category: str = "output_contract"


@dataclass(frozen=True)
class RuleParityIssue:
    """Metadata-only rule-map discrepancy."""

    code: str
    rule_id: str
    category: str
    artifact: str
    pointer: str


class ContractError(ValueError):
    """A bounded validation error exposing only a code, pointer, and rule ID."""

    def __init__(self, code: str, rule_id: str, path: str = "") -> None:
        self.code = code
        self.rule_id = rule_id
        self.path = _bounded(path)
        super().__init__(code)

    @property
    def diagnostic(self) -> Mapping[str, str]:
        return MappingProxyType(
            {"code": self.code, "path": self.path, "rule_id": self.rule_id}
        )


@dataclass(frozen=True)
class SceneBinding:
    """Immutable scene-specific references and canonical input allowlists."""

    scene_id: str
    module_id: str
    input_refs: Mapping[str, Any]
    topology_node_ids: tuple[str, ...]
    role_candidates: Mapping[str, tuple[str, ...]]
    public_base_fact_ids: tuple[str, ...]
    base_fact_ids: frozenset[str]
    unknown_predicates: frozenset[str]
    guarded_markers: tuple[str, ...]
    expected_bundle: Mapping[str, Any]

    @property
    def topology_ids(self) -> frozenset[str]:
        return frozenset(self.topology_node_ids)

    @property
    def authored_fact_pattern(self) -> str:
        return "^" + re.escape(self.module_id) + r":fact:study3-authored:[A-Za-z0-9][A-Za-z0-9._-]*$"

    @property
    def claim_id_pattern(self) -> str:
        return "^" + re.escape(self.scene_id) + r":claim:[A-Za-z0-9][A-Za-z0-9._-]*$"


def _src(
    artifact: str,
    pointer: str,
    *,
    expected: Any = _UNSET,
    contains: str | None = None,
    binding_key: str | None = None,
    expected_keys: tuple[str, ...] | None = None,
) -> SourcePointer:
    return SourcePointer(artifact, pointer, expected, contains, binding_key, expected_keys)


def _rule(rule_id: str, check_id: str, summary: str, *sources: SourcePointer) -> RuleSpec:
    return RuleSpec(rule_id, check_id, summary, tuple(sources))


# One entry for each independently meaningful output-facing validator rule.
# Pointers use JSON Pointer syntax; /scenes/*/ selects the active frozen scene.
OUTPUT_RULE_MAP: tuple[RuleSpec, ...] = (
    _rule(
        "S3-JSON-OBJECT", "parse", "Require one UTF-8 JSON object.",
        _src("system_prompt", "/lines/1", contains="Return exactly one JSON object"),
        _src("rendered_schema", "/type", expected="object"),
    ),
    _rule(
        "S3-JSON-BYTE-LIMIT", "parse", "Reject payloads over 65,536 UTF-8 bytes.",
        _src("model_contract", "/output_contract/json/payload_max_bytes", expected=65536),
        _src("system_prompt", "/lines/3", contains="65,536 UTF-8 bytes"),
    ),
    _rule(
        "S3-JSON-DUPLICATE-KEYS", "parse", "Reject duplicate JSON object keys.",
        _src("model_contract", "/output_contract/json/duplicate_object_keys", expected="REJECT"),
        _src("system_prompt", "/lines/3", contains="Duplicate JSON object keys"),
    ),
    _rule(
        "S3-JSON-NONFINITE", "parse", "Reject non-finite JSON values.",
        _src("model_contract", "/output_contract/json/non_finite_numbers", expected="REJECT"),
        _src("system_prompt", "/lines/3", contains="non-finite values"),
    ),
    _rule(
        "S3-JSON-NUMBERS", "schema", "Reject numeric fact values.",
        _src("model_contract", "/output_contract/json/numeric_values", expected="NOT_ALLOWED"),
        _src("rendered_schema", "/$defs/fact_value/oneOf/0/type", expected="string"),
        _src("rendered_schema", "/$defs/fact_value/oneOf/1/type", expected="boolean"),
        _src("rendered_schema", "/$defs/fact_value/oneOf/2/type", expected="null"),
        _src("system_prompt", "/lines/3", contains="numbers, and arbitrary objects or arrays as fact values are invalid"),
    ),
    _rule(
        "S3-ROOT-FIELDS", "schema", "Require exactly the six declared root fields and a closed root.",
        _src("model_contract", "/output_contract/root/only_fields", binding_key="root_fields"),
        _src("model_contract", "/output_contract/root/closed", expected=True),
        _src("model_contract", "/output_contract/root/schema_value", expected="neq.llm_staging_study3_delta.v1"),
        _src("rendered_schema", "/properties", expected_keys=_ROOT_FIELDS),
        _src("rendered_schema", "/required", binding_key="root_fields"),
        _src("rendered_schema", "/properties/schema/const", expected="neq.llm_staging_study3_delta.v1"),
        _src("rendered_schema", "/additionalProperties", expected=False),
        _src("system_prompt", "/lines/3", contains="The only root fields are"),
    ),
    _rule(
        "S3-NESTED-CLOSED-OBJECTS", "schema", "Close all nested output objects.",
        _src("model_contract", "/output_contract/unknown_keys", expected="REJECT_AT_ROOT_AND_EVERY_NESTED_OBJECT"),
        *tuple(
            _src("rendered_schema", "/$defs/" + name + "/additionalProperties", expected=False)
            for name in (
                "input_refs", "source_packet_ref", "expected_bundle_ref", "topology_ref",
                "gate_canonical_context_ref", "entity_ref_value", "fact_ref_value",
                "authored_fact", "fixture_deltas", "stage_role_bindings", "claim",
                "claim_group", "arrival_approach", "arrival_threshold", "arrival_focal",
            )
        ),
    ),
    _rule(
        "S3-REFERENCE-KEYS-BOUNDS", "schema", "Close reference objects and bound IDs and SHA-256 values.",
        _src("model_contract", "/output_contract/input_refs/only_fields", binding_key="reference_fields"),
        _src("model_contract", "/output_contract/input_refs/closed", expected=True),
        _src("model_contract", "/output_contract/input_refs/reference_names", expected=_REFERENCE_NAMES),
        _src("model_contract", "/output_contract/input_refs/reference_fields", expected=("id", "sha256")),
        _src("model_contract", "/output_contract/input_refs/scene_id", expected="EXACT_SCENE_BINDING"),
        _src("rendered_schema", "/$defs/input_refs/properties", expected_keys=_REFERENCE_FIELDS),
        _src("rendered_schema", "/$defs/input_refs/required", expected=_REFERENCE_FIELDS),
        _src("model_contract", "/output_contract/input_refs/reference_id_length/min", expected=1),
        _src("model_contract", "/output_contract/input_refs/reference_id_length/max", expected=512),
        _src("model_contract", "/output_contract/input_refs/sha256_pattern", expected="^[0-9a-f]{64}$"),
        *tuple(
             source
             for name in ("source_packet", "expected_bundle", "topology", "gate_canonical_context")
             for source in (
                 _src("rendered_schema", "/$defs/" + name + "_ref/required", expected=("id", "sha256")),
                 _src("rendered_schema", "/$defs/" + name + "_ref/properties/id/minLength", expected=1),
                _src("rendered_schema", "/$defs/" + name + "_ref/properties/id/maxLength", expected=512),
                _src("rendered_schema", "/$defs/" + name + "_ref/properties/sha256/pattern", expected="^[0-9a-f]{64}$"),
            )
        ),
        _src("system_prompt", "/lines/3", contains="lowercase 64-character SHA-256 values"),
    ),
    _rule(
        "S3-EXACT-INPUT-REFERENCES", "references", "Bind all reference IDs and hashes to canonical scene inputs.",
        _src("model_contract", "/output_contract/input_refs/values", expected="EXACT_STUDY3_INPUT_BINDING; NO MODEL-SUPPLIED AUTHORITY"),
        _src("input_bindings", "/scenes/*/input_refs", binding_key="input_refs"),
        _src("rendered_schema", "/$defs/input_refs/properties/scene_id/const", binding_key="input_refs.scene_id"),
        *tuple(
            source
            for name in _REFERENCE_NAMES
            for source in (
                _src("rendered_schema", "/$defs/" + name + "_ref/properties/id/const", binding_key="input_refs." + name + ".id"),
                _src("rendered_schema", "/$defs/" + name + "_ref/properties/sha256/const", binding_key="input_refs." + name + ".sha256"),
            )
        ),
        _src("system_prompt", "/lines/3", contains="Do not change, omit, or invent an input reference"),
    ),
    _rule(
        "S3-AUTHORED-ID-NAMESPACE", "facts", "Require anchored module-qualified Study 3 authored IDs.",
        _src("model_contract", "/output_contract/authored_fact/fact_id_namespace_template", expected="<module_id>:fact:study3-authored:<suffix>"),
        _src("model_contract", "/output_contract/authored_fact/fact_id_regex_template", expected="^<escaped_module_id>:fact:study3-authored:[A-Za-z0-9][A-Za-z0-9._-]*$"),
        _src("system_prompt", "/lines/5", contains="module-qualified namespace"),
        _src("rendered_schema", "/$defs/authored_fact/properties/fact_id/pattern", binding_key="authored_fact_pattern"),
        _src("input_bindings", "/scenes/*/module_id", binding_key="module_id"),
    ),
    _rule(
        "S3-AUTHORED-ID-LIMIT-UNIQUE", "facts", "Bound authored IDs to 256 characters and require uniqueness.",
        _src("model_contract", "/output_contract/authored_fact/fact_id_max_length", expected=256),
        _src("rendered_schema", "/$defs/authored_fact/properties/fact_id/maxLength", expected=256),
        _src("model_contract", "/output_contract/fixture_deltas/facts/authored_fact_ids_unique", expected=True),
        _src("system_prompt", "/lines/5", contains="Use a unique suffix"),
    ),
    _rule(
        "S3-NO-BASE-FACT-OVERWRITE", "overwrite", "Reject authored IDs colliding with any source/base fact.",
        _src("model_contract", "/output_contract/authored_fact/fact_id_must_not_equal_any_source_or_base_fact_id", expected=True),
        _src("input_bindings", "/scenes/*/public_base_fact_ids", binding_key="public_base_fact_ids"),
        _src("expected_bundle", "/source_facts/facts", binding_key="base_fact_ids"),
        _src("system_prompt", "/lines/5", contains="never reuse any source/base fact ID"),
    ),
    _rule(
        "S3-FACT-FIELDS", "schema", "Allow only five authored fact fields.",
        _src("model_contract", "/output_contract/authored_fact/only_fields", binding_key="fact_fields"),
        _src("model_contract", "/output_contract/authored_fact/closed", expected=True),
        _src("rendered_schema", "/$defs/authored_fact/properties", expected_keys=_FACT_FIELDS),
        _src("rendered_schema", "/$defs/authored_fact/required", expected=_FACT_FIELDS),
        _src("system_prompt", "/lines/5", contains="The only authored fact fields are"),
    ),
    _rule(
        "S3-PREDICATE-ALLOWLIST", "facts", "Allow only the seven declared predicates.",
        _src("model_contract", "/output_contract/authored_fact/predicate_enum", binding_key="predicates"),
        _src("rendered_schema", "/$defs/authored_fact/properties/predicate/enum", binding_key="predicates"),
        _src("system_prompt", "/lines/5", contains="The only predicates are"),
    ),
    _rule(
        "S3-FACT-VALUE-SHAPES", "facts", "Restrict values to bounded strings, booleans, null, and closed references.",
        _src("model_contract", "/output_contract/authored_fact/value_shapes", expected=_FACT_VALUE_SHAPES),
        _src("model_contract", "/output_contract/authored_fact/arbitrary_objects_and_arrays", expected="REJECT"),
        _src("rendered_schema", "/$defs/fact_value/oneOf", expected=_FACT_VALUE_SCHEMA),
        _src("rendered_schema", "/$defs/fact_value/oneOf/0/maxLength", expected=512),
        _src("rendered_schema", "/$defs/entity_ref_value/required", expected=("kind", "entity_id")),
        _src("rendered_schema", "/$defs/fact_ref_value/required", expected=("kind", "fact_id")),
        _src("rendered_schema", "/$defs/entity_ref_value/additionalProperties", expected=False),
        _src("rendered_schema", "/$defs/fact_ref_value/additionalProperties", expected=False),
        _src("system_prompt", "/lines/7", contains="The only fact value shapes are"),
    ),
    _rule(
        "S3-ENTITY-REFERENCE-SCOPE", "entity_references", "Resolve entity references only against scene topology IDs.",
        _src("model_contract", "/output_contract/authored_fact/value_shapes/3/entity_id", expected="EXACT_SCENE_TOPOLOGY_NODE_ID"),
        _src("input_bindings", "/scenes/*/topology_node_ids", binding_key="topology_node_ids"),
        _src("rendered_schema", "/$defs/entity_ref_value/properties/entity_id/enum", binding_key="topology_node_ids"),
        _src("rendered_schema", "/$defs/authored_fact/properties/subject_id/enum", binding_key="topology_node_ids"),
        _src("rendered_schema", "/$defs/authored_fact/properties/object_id/anyOf", binding_key="object_id_schema"),
    ),
    _rule(
        "S3-FACT-REFERENCE-SCOPE", "facts", "Resolve fact references only to public base or this-delta authored facts.",
        _src("model_contract", "/output_contract/authored_fact/value_shapes/4/fact_id", expected="PUBLIC_BASE_FACT_ID_OR_STUDY3_AUTHORED_FACT_ID"),
        _src("input_bindings", "/scenes/*/public_base_fact_ids", binding_key="public_base_fact_ids"),
        _src("rendered_schema", "/$defs/fact_ref_value/properties/fact_id", binding_key="fact_reference_schema"),
        _src("rendered_schema", "/$defs/claim/properties/fact_id", binding_key="fact_reference_schema"),
        _src("system_prompt", "/lines/7", contains="public base fact ID or a Study 3 authored fact ID"),
    ),
    _rule(
        "S3-FACT-COUNT-BOUNDS", "facts", "Require 2-64 authored facts.",
        _src("model_contract", "/output_contract/fixture_deltas/facts/min_items", expected=2),
        _src("model_contract", "/output_contract/fixture_deltas/facts/max_items", expected=64),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/minItems", expected=2),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/maxItems", expected=64),
    ),
    _rule(
        "S3-STAGE-ROLE-FIELDS", "roles", "Require the exact four stage role names.",
        _src("model_contract", "/output_contract/stage_role_bindings/only_fields", binding_key="role_names"),
        _src("model_contract", "/output_contract/stage_role_bindings/closed", expected=True),
        _src("model_contract", "/output_contract/stage_role_bindings/role_order", binding_key="role_names"),
        _src("rendered_schema", "/$defs/stage_role_bindings/properties", expected_keys=_ROLE_NAMES),
        _src("rendered_schema", "/$defs/stage_role_bindings/required", expected=_ROLE_NAMES),
        _src("system_prompt", "/lines/7", contains="The only stage_role_bindings fields are approach, threshold, focal_anchor, and usable_space"),
    ),
    _rule(
        "S3-STAGE-ROLE-BOUNDS-UNIQUE", "roles", "Require 1-16 unique IDs per role.",
        _src("model_contract", "/output_contract/stage_role_bindings/each_role/min_items", expected=1),
        _src("model_contract", "/output_contract/stage_role_bindings/each_role/max_items", expected=16),
        _src("model_contract", "/output_contract/stage_role_bindings/each_role/unique_ids", expected=True),
        *tuple(
            source
            for role in _ROLE_NAMES
            for source in (
                _src("rendered_schema", "/$defs/stage_role_bindings/properties/" + role + "/minItems", expected=1),
                _src("rendered_schema", "/$defs/stage_role_bindings/properties/" + role + "/maxItems", expected=16),
                _src("rendered_schema", "/$defs/stage_role_bindings/properties/" + role + "/uniqueItems", expected=True),
            )
        ),
        _src("system_prompt", "/lines/7", contains="1 to 16 unique IDs"),
    ),
    _rule(
        "S3-STAGE-ROLE-CANDIDATES", "roles", "Restrict each role to its exact canonical candidate IDs.",
        _src("model_contract", "/output_contract/stage_role_bindings/each_role/ids", expected="ONLY_THE_EXACT_SCENE_ROLE_CANDIDATES"),
        _src("model_contract", "/output_contract/stage_role_bindings/topology_mutation", expected="REJECT"),
        _src("input_bindings", "/scenes/*/stage_role_candidates", binding_key="role_candidates"),
        *tuple(
            _src("rendered_schema", "/$defs/stage_role_bindings/properties/" + role + "/items/enum", binding_key="role_candidates." + role)
            for role in _ROLE_NAMES
        ),
        _src("system_prompt", "/lines/7", contains="Each is a non-empty list of 1 to 16 unique IDs chosen only from that role's exact topology candidates"),
    ),
    _rule(
        "S3-APPROACH-RELATION-TRUE", "facts", "Require one selected approach-to-threshold relation with literal true.",
        _src("model_contract", "/output_contract/stage_relations/0/value/const", expected=True),
        _src("model_contract", "/output_contract/stage_relations/0/required_count", expected=1),
        _src("model_contract", "/output_contract/stage_relations/0/subject_role", expected="approach"),
        _src("model_contract", "/output_contract/stage_relations/0/object_role", expected="threshold"),
        _src("model_contract", "/output_contract/stage_relations/0/subject_object_must_be_member_of_selected_role_bindings", expected=True),
        _src("rendered_schema", "/$defs/authored_fact/allOf/0/then/properties/value/const", expected=True),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/allOf/0/minContains", expected=1),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/allOf/0/maxContains", expected=1),
        _src("system_prompt", "/lines/5", contains="approach -> threshold"),
        _src("system_prompt", "/lines/5", contains="each endpoint must be selected in its corresponding stage_role_bindings list"),
        _src("system_prompt", "/lines/5", contains="literal JSON boolean true"),
    ),
    _rule(
        "S3-THRESHOLD-RELATION-TRUE", "facts", "Require one selected threshold-to-focal relation with literal true.",
        _src("model_contract", "/output_contract/stage_relations/1/value/const", expected=True),
        _src("model_contract", "/output_contract/stage_relations/1/required_count", expected=1),
        _src("model_contract", "/output_contract/stage_relations/1/subject_role", expected="threshold"),
        _src("model_contract", "/output_contract/stage_relations/1/object_role", expected="focal_anchor"),
        _src("model_contract", "/output_contract/stage_relations/1/subject_object_must_be_member_of_selected_role_bindings", expected=True),
        _src("rendered_schema", "/$defs/authored_fact/allOf/1/then/properties/value/const", expected=True),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/allOf/1/minContains", expected=1),
        _src("rendered_schema", "/$defs/fixture_deltas/properties/facts/allOf/1/maxContains", expected=1),
        _src("system_prompt", "/lines/5", contains="threshold -> focal_anchor"),
        _src("system_prompt", "/lines/5", contains="each endpoint must be selected in its corresponding stage_role_bindings list"),
        _src("system_prompt", "/lines/5", contains="literal JSON boolean true"),
    ),
    _rule(
        "S3-USABLE-SPACE-ROLE", "facts", "Require usable_space fact subjects in the selected role binding.",
        _src("model_contract", "/output_contract/usable_space_subject_must_be_member_of_selected_role_binding", expected=True),
        _src("input_bindings", "/scenes/*/stage_role_candidates/usable_space", binding_key="role_candidates.usable_space"),
        _src("system_prompt", "/lines/5", contains="usable_space fact subject must be selected"),
    ),
    _rule(
        "S3-CLAIM-GROUPS-ORDER-LIMIT", "claims", "Require three ordered claim groups and at most 32 claims per group.",
        _src("model_contract", "/output_contract/claims/exact_group_count", expected=3),
        _src("model_contract", "/output_contract/claims/group_role_order", binding_key="arrival_roles"),
        _src("model_contract", "/output_contract/claims/max_claims_per_group", expected=32),
        _src("model_contract", "/output_contract/claims/groups_closed", expected=True),
        _src("rendered_schema", "/$defs/claim_group/properties", expected_keys=("segment_id", "items")),
        _src("rendered_schema", "/$defs/claim_group/required", expected=("segment_id", "items")),
        _src("rendered_schema", "/$defs/claims/minItems", expected=3),
        _src("rendered_schema", "/$defs/claims/maxItems", expected=3),
        _src("rendered_schema", "/$defs/claim_group/properties/items/maxItems", expected=32),
        _src("system_prompt", "/lines/9", contains="exactly three closed groups in approach, threshold, focal order"),
    ),
    _rule(
        "S3-CLAIM-SEGMENT-BINDING", "claims", "Bind each claim group to its exact scene-qualified segment in order.",
        _src("model_contract", "/output_contract/claims/group_role_order", binding_key="arrival_roles"),
        _src("rendered_schema", "/$defs/claims/prefixItems/0/properties/segment_id/const", binding_key="arrival_id.approach"),
        _src("rendered_schema", "/$defs/claims/prefixItems/1/properties/segment_id/const", binding_key="arrival_id.threshold"),
        _src("rendered_schema", "/$defs/claims/prefixItems/2/properties/segment_id/const", binding_key="arrival_id.focal"),
        _src("system_prompt", "/lines/9", contains="exact substring of the bound arrival segment"),
    ),
    _rule(
        "S3-CLAIM-ID-UNIQUE-BOUNDS", "claims", "Require unique scene-qualified claim IDs up to 512 characters.",
        _src("model_contract", "/output_contract/claims/claim_id/max_length", expected=512),
        _src("model_contract", "/output_contract/claims/claim_id/unique", expected=True),
        _src("model_contract", "/output_contract/claims/claim_id/pattern_template", expected="^<escaped_scene_id>:claim:[A-Za-z0-9][A-Za-z0-9._-]*$"),
        _src("rendered_schema", "/$defs/claim/properties/id/minLength", expected=1),
        _src("rendered_schema", "/$defs/claim/properties/id/maxLength", expected=512),
        _src("rendered_schema", "/$defs/claim/properties/id/pattern", binding_key="claim_id_pattern"),
    ),
    _rule(
        "S3-CLAIM-FIELDS", "claims", "Allow only six declared claim fields.",
        _src("model_contract", "/output_contract/claims/claim_only_fields", binding_key="claim_fields"),
        _src("rendered_schema", "/$defs/claim/properties", expected_keys=_CLAIM_FIELDS),
        _src("rendered_schema", "/$defs/claim/required", expected=_CLAIM_FIELDS),
        _src("system_prompt", "/lines/9", contains="Each claim contains only id, fact_id, kind, span, choice, and success"),
    ),
    _rule(
        "S3-CLAIM-FACT-REFERENCES", "claims", "Allow claims to refer only to public base or this-delta authored facts.",
        _src("model_contract", "/output_contract/claims/fact_id", expected="PUBLIC_BASE_FACT_ID_OR_THIS_DELTA_AUTHORED_FACT_ID"),
        _src("model_contract", "/output_contract/claims/no_unbound_or_prose_only_public_fact_claims", expected=True),
        _src("input_bindings", "/scenes/*/public_base_fact_ids", binding_key="public_base_fact_ids"),
        _src("rendered_schema", "/$defs/claim/properties/fact_id", binding_key="fact_reference_schema"),
        _src("system_prompt", "/lines/9", contains="fact_id must reference a public base fact or a fact authored in this delta"),
    ),
    _rule(
        "S3-CLAIM-SPANS", "claims", "Require bounded exact-substring spans from their bound segments.",
        _src("model_contract", "/output_contract/claims/span/min_length", expected=1),
        _src("model_contract", "/output_contract/claims/span/max_length", expected=512),
        _src("model_contract", "/output_contract/claims/span/must_be_exact_substring_of_bound_segment", expected=True),
        _src("rendered_schema", "/$defs/claim/properties/span/minLength", expected=1),
        _src("rendered_schema", "/$defs/claim/properties/span/maxLength", expected=512),
        _src("system_prompt", "/lines/9", contains="span is 1 to 512 characters"),
    ),
    _rule(
        "S3-CLAIM-AGENCY", "claims", "Enforce exact invitation and factual claim agency values.",
        _src("model_contract", "/output_contract/claims/agency/invitation/choice", expected="open"),
        _src("model_contract", "/output_contract/claims/agency/invitation/success", expected="unspecified"),
        _src("model_contract", "/output_contract/claims/agency/factual/choice", expected=None),
        _src("model_contract", "/output_contract/claims/agency/factual/success", expected=None),
        _src("model_contract", "/output_contract/claims/kind_enum", expected=("factual", "invitation")),
        _src("rendered_schema", "/$defs/claim/properties/kind/enum", expected=("factual", "invitation")),
        _src("rendered_schema", "/$defs/claim/properties/choice/enum", expected=("open", None)),
        _src("rendered_schema", "/$defs/claim/properties/success/enum", expected=("unspecified", None)),
        _src("rendered_schema", "/$defs/claim/allOf/0/then/properties/choice/const", expected="open"),
        _src("rendered_schema", "/$defs/claim/allOf/0/then/properties/success/const", expected="unspecified"),
        _src("rendered_schema", "/$defs/claim/allOf/1/then/properties/choice/const", expected=None),
        _src("rendered_schema", "/$defs/claim/allOf/1/then/properties/success/const", expected=None),
        _src("system_prompt", "/lines/9", contains="choice `open`, and success `unspecified`"),
        _src("system_prompt", "/lines/9", contains="with choice and success both null"),
    ),
    _rule(
        "S3-ARRIVAL-ORDER-IDS-LIMITS", "claims", "Require three ordered closed arrival segments with bounded exact IDs and text.",
        _src("model_contract", "/output_contract/arrival_prose/exact_segment_count", expected=3),
        _src("model_contract", "/output_contract/arrival_prose/role_order", binding_key="arrival_roles"),
        _src("model_contract", "/output_contract/arrival_prose/text_length/min", expected=1),
        _src("model_contract", "/output_contract/arrival_prose/text_length/max", expected=512),
        _src("model_contract", "/output_contract/arrival_prose/segment_only_fields", expected=("id", "role", "text")),
        _src("model_contract", "/output_contract/arrival_prose/segment_closed", expected=True),
        _src("model_contract", "/output_contract/arrival_prose/id_template", expected="<scene_id>:arrival:<role>"),
        _src("model_contract", "/output_contract/arrival_prose/id_max_length", expected=512),
        _src("model_contract", "/output_contract/arrival_prose/text", expected="BOUNDED_PROSE_ONLY; CLAIMS_BIND_CHECKABLE_SPANS_TO_FACT_IDS"),
        _src("rendered_schema", "/$defs/arrival_prose/minItems", expected=3),
        _src("rendered_schema", "/$defs/arrival_prose/maxItems", expected=3),
        _src("rendered_schema", "/$defs/arrival_approach/properties/role/const", expected="approach"),
        _src("rendered_schema", "/$defs/arrival_threshold/properties/role/const", expected="threshold"),
        _src("rendered_schema", "/$defs/arrival_focal/properties/role/const", expected="focal"),
        *tuple(
            source
            for role in _ARRIVAL_ROLES
            for source in (
                _src("rendered_schema", "/$defs/arrival_" + role + "/required", expected=("id", "role", "text")),
            )
        ),
        *tuple(
            source
            for name, role in (("approach", "approach"), ("threshold", "threshold"), ("focal", "focal"))
            for source in (
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties", expected_keys=("id", "role", "text")),
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties/id/minLength", expected=1),
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties/id/maxLength", expected=512),
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties/id/const", binding_key="arrival_id." + role),
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties/text/minLength", expected=1),
                _src("rendered_schema", "/$defs/arrival_" + name + "/properties/text/maxLength", expected=512),
            )
        ),
        _src("system_prompt", "/lines/11", contains="exactly three closed segments in approach, threshold, focal order"),
    ),
    _rule(
        "S3-PROSE-AGENCY", "claims", "Reject direct prose assertions taking player choice or success away.",
        _src("model_contract", "/output_contract/claims/agency/prose_must_not_assert_player_choice_or_success", expected=True),
        _src("system_prompt", "/lines/11", contains="do not assert a player choice or successful outcome"),
    ),
    _rule(
        "S3-PROTECTED-UNKNOWNS", "protected", "Preserve canonical unknowns and block explicitly unmapped sensory gradients.",
        _src("model_contract", "/output_contract/protected_unknowns", expected="REMAIN_UNKNOWN; DO_NOT_PROMOTE_OR_INFER"),
        _src("expected_bundle", "/protected_unknowns/protected_unknowns_must_not_be_promoted", expected=True),
        _src("expected_bundle", "/protected_unknowns/unknowns", binding_key="unknown_predicates"),
        _src("system_prompt", "/lines/13", contains="Preserve every unprovided or protected-unknown state as unknown"),
    ),
    _rule(
        "S3-GUARDED-CONTENT-MARKERS", "protected", "Reject exact guarded source markers in public output text.",
        _src("model_contract", "/output_contract/source_base_topology_or_protected_unknown_overwrite", expected="REJECT"),
        _src("expected_bundle", "/protected_unknowns/guarded_content_markers", binding_key="guarded_markers"),
        _src("system_prompt", "/lines/13", contains="Keep private, guarded, schematic-only, and source-reference-only content out of public claims and prose"),
    ),
    _rule(
        "S3-DELTA-ONLY-OVERWRITE", "schema", "Allow only delta fields and reject source, base, topology, or unknown replacement.",
        _src("model_contract", "/output_contract/fixture_deltas/only_fields", expected=("facts",)),
        _src("model_contract", "/output_contract/fixture_deltas/closed", expected=True),
        _src("model_contract", "/output_contract/fixture_deltas/no_source_base_facts_entities_topology_provenance_or_canonical_extension_fields", expected=True),
        _src("model_contract", "/output_contract/source_base_topology_or_protected_unknown_overwrite", expected="REJECT"),
        _src("rendered_schema", "/$defs/fixture_deltas/properties", expected_keys=("facts",)),
        _src("rendered_schema", "/$defs/fixture_deltas/required", expected=("facts",)),
        _src("system_prompt", "/lines/3", contains="no source/base fact, entity, topology, provenance, canonical extension, or protected-unknown replacement"),
    ),
)

HOST_RULE_MAP: tuple[RuleSpec, ...] = (
    RuleSpec("HOST-PROJECT-PATH-BOUNDARY", "safe_read", "Reject absolute, traversing, symlinked, or non-project paths.", (), "host_safety_integrity"),
    RuleSpec("HOST-CANONICAL-HASH-INTEGRITY", "canonical_integrity", "Require exact pinned protocol and canonical-input bytes.", (), "host_safety_integrity"),
)

@dataclass
class _ValidationContext:
    raw: bytes
    scene_id: str
    binding: SceneBinding
    payload: dict[str, Any] | None = None

    def reject(self, code: str, rule_id: str, path: str = "") -> None:
        raise ContractError(code, rule_id, path)


def _check_parse(context: _ValidationContext) -> None:
    if len(context.raw) > MAX_DELTA_BYTES:
        context.reject("OUTPUT_BYTE_LIMIT", "S3-JSON-BYTE-LIMIT")
    try:
        value = json.loads(
            context.raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonfinite_constant,
        )
    except UnicodeDecodeError:
        context.reject("OUTPUT_UTF8_INVALID", "S3-JSON-OBJECT")
    except _DuplicateKey:
        context.reject("OUTPUT_DUPLICATE_KEY", "S3-JSON-DUPLICATE-KEYS")
    except _NonFinite:
        context.reject("OUTPUT_NONFINITE_NUMBER", "S3-JSON-NONFINITE")
    except (json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        context.reject("OUTPUT_JSON_INVALID", "S3-JSON-OBJECT")
    if type(value) is not dict:
        context.reject("OUTPUT_JSON_OBJECT_REQUIRED", "S3-JSON-OBJECT")
    context.payload = value


def _check_schema(context: _ValidationContext) -> None:
    assert context.payload is not None
    try:
        schema = protocol.render_output_schema(context.scene_id)
        Draft202012Validator.check_schema(schema)
        error = next(Draft202012Validator(schema).iter_errors(context.payload), None)
    except (SchemaError, RecursionError, TypeError, ValueError, KeyError, AttributeError):
        context.reject("OUTPUT_SCHEMA_INVALID", "S3-ROOT-FIELDS")
    if error is not None:
        context.reject(
            "OUTPUT_SCHEMA_REJECTED",
            _schema_rule_id(error, context.payload),
            _pointer_from_parts(error.absolute_path),
        )


def _check_base_overwrites(context: _ValidationContext) -> None:
    assert context.payload is not None
    fixture = context.payload.get("fixture_deltas")
    facts = fixture.get("facts") if type(fixture) is dict else None
    if type(facts) is not list:
        return
    for index, fact in enumerate(facts):
        if type(fact) is not dict:
            continue
        fact_id = fact.get("fact_id")
        if type(fact_id) is str and fact_id in context.binding.base_fact_ids:
            context.reject(
                "BASE_FACT_OVERWRITE",
                "S3-NO-BASE-FACT-OVERWRITE",
                "/fixture_deltas/facts/" + str(index) + "/fact_id",
            )


def _check_topology_references(context: _ValidationContext) -> None:
    assert context.payload is not None
    fixture = context.payload.get("fixture_deltas")
    facts = fixture.get("facts") if type(fixture) is dict else None
    if type(facts) is not list:
        return
    topology_ids = context.binding.topology_ids
    for index, fact in enumerate(facts):
        if type(fact) is not dict:
            continue
        path = "/fixture_deltas/facts/" + str(index)
        subject = fact.get("subject_id")
        if type(subject) is str and subject not in topology_ids:
            context.reject("UNKNOWN_TOPOLOGY_ID", "S3-ENTITY-REFERENCE-SCOPE", path + "/subject_id")
        object_id = fact.get("object_id")
        if type(object_id) is str and object_id not in topology_ids:
            context.reject("UNKNOWN_TOPOLOGY_ID", "S3-ENTITY-REFERENCE-SCOPE", path + "/object_id")
        value = fact.get("value")
        if (
            type(value) is dict
            and set(value) == {"kind", "entity_id"}
            and value.get("kind") == "entity_ref"
        ):
            entity_id = value.get("entity_id")
            if type(entity_id) is str and entity_id not in topology_ids:
                context.reject("ENTITY_REFERENCE_INVALID", "S3-ENTITY-REFERENCE-SCOPE", path + "/value/entity_id")


def _check_references(context: _ValidationContext) -> None:
    assert context.payload is not None
    observed = context.payload.get("input_refs")
    if _json_equal(observed, context.binding.input_refs):
        return
    code = "INPUT_REFERENCE_MISMATCH"
    if type(observed) is dict:
        for name in _REFERENCE_NAMES:
            left = observed.get(name)
            right = context.binding.input_refs.get(name)
            if type(left) is dict and isinstance(right, Mapping):
                if left.get("id") != right.get("id"):
                    code = "INPUT_REFERENCE_ID_MISMATCH"
                    break
                if left.get("sha256") != right.get("sha256"):
                    code = "INPUT_REFERENCE_HASH_MISMATCH"
                    break
    context.reject(code, "S3-EXACT-INPUT-REFERENCES", "/input_refs")


def _check_roles(context: _ValidationContext) -> None:
    assert context.payload is not None
    roles = context.payload.get("stage_role_bindings")
    if type(roles) is not dict or set(roles) != set(_ROLE_NAMES):
        context.reject("STAGE_ROLE_BINDING_INVALID", "S3-STAGE-ROLE-FIELDS", "/stage_role_bindings")
    for role in _ROLE_NAMES:
        ids = roles.get(role)
        candidates = context.binding.role_candidates[role]
        if (
            type(ids) is not list
            or not 1 <= len(ids) <= 16
            or any(type(value) is not str or value not in candidates for value in ids)
            or len(ids) != len(set(ids))
        ):
            context.reject("STAGE_ROLE_CANDIDATE_INVALID", "S3-STAGE-ROLE-CANDIDATES", "/stage_role_bindings/" + role)


def _check_facts(context: _ValidationContext) -> None:
    assert context.payload is not None
    fixture = context.payload.get("fixture_deltas")
    facts = fixture.get("facts") if type(fixture) is dict else None
    if type(facts) is not list or not 2 <= len(facts) <= 64:
        context.reject("AUTHORED_FACT_COUNT_INVALID", "S3-FACT-COUNT-BOUNDS", "/fixture_deltas/facts")

    authored_ids: set[str] = set()
    for index, fact in enumerate(facts):
        path = "/fixture_deltas/facts/" + str(index)
        if type(fact) is not dict or set(fact) != set(_FACT_FIELDS):
            context.reject("AUTHORED_FACT_FIELDS_INVALID", "S3-FACT-FIELDS", path)
        fact_id = fact.get("fact_id")
        if (
            type(fact_id) is not str
            or len(fact_id) > 256
            or re.fullmatch(context.binding.authored_fact_pattern, fact_id) is None
        ):
            context.reject("AUTHORED_FACT_ID_INVALID", "S3-AUTHORED-ID-NAMESPACE", path + "/fact_id")
        if fact_id in authored_ids:
            context.reject("AUTHORED_FACT_ID_DUPLICATE", "S3-AUTHORED-ID-LIMIT-UNIQUE", path + "/fact_id")
        authored_ids.add(fact_id)

    roles = context.payload.get("stage_role_bindings")
    relation_counts = {"approach_to_threshold": 0, "threshold_to_focal": 0}
    valid_fact_refs = set(context.binding.public_base_fact_ids) | authored_ids
    for index, fact in enumerate(facts):
        path = "/fixture_deltas/facts/" + str(index)
        predicate = fact.get("predicate")
        if type(predicate) is not str or predicate not in _PREDICATES:
            context.reject("AUTHORED_PREDICATE_INVALID", "S3-PREDICATE-ALLOWLIST", path + "/predicate")
        subject = fact.get("subject_id")
        object_id = fact.get("object_id")
        if predicate == "approach_to_threshold":
            relation_counts[predicate] += 1
            if subject not in roles["approach"] or object_id not in roles["threshold"] or fact.get("value") is not True:
                context.reject("STAGE_RELATION_INVALID", "S3-APPROACH-RELATION-TRUE", path)
        elif predicate == "threshold_to_focal":
            relation_counts[predicate] += 1
            if subject not in roles["threshold"] or object_id not in roles["focal_anchor"] or fact.get("value") is not True:
                context.reject("STAGE_RELATION_INVALID", "S3-THRESHOLD-RELATION-TRUE", path)
        elif predicate == "usable_space" and subject not in roles["usable_space"]:
            context.reject("STAGE_RELATION_INVALID", "S3-USABLE-SPACE-ROLE", path + "/subject_id")
        _check_fact_value(context, fact.get("value"), valid_fact_refs, path + "/value")

    for predicate, count in relation_counts.items():
        if count != 1:
            rule_id = "S3-APPROACH-RELATION-TRUE" if predicate == "approach_to_threshold" else "S3-THRESHOLD-RELATION-TRUE"
            context.reject("STAGE_RELATION_COUNT_INVALID", rule_id, "/fixture_deltas/facts")


def _check_fact_value(context: _ValidationContext, value: object, valid_fact_refs: set[str], path: str) -> None:
    if type(value) is str:
        if len(value) > 512:
            context.reject("FACT_VALUE_LENGTH_INVALID", "S3-FACT-VALUE-SHAPES", path)
        return
    if type(value) is bool or value is None:
        return
    if type(value) is dict:
        if set(value) == {"kind", "entity_id"} and value.get("kind") == "entity_ref":
            entity_id = value.get("entity_id")
            if type(entity_id) is not str or entity_id not in context.binding.topology_ids:
                context.reject("ENTITY_REFERENCE_INVALID", "S3-ENTITY-REFERENCE-SCOPE", path)
            return
        if set(value) == {"kind", "fact_id"} and value.get("kind") == "fact_ref":
            fact_id = value.get("fact_id")
            if type(fact_id) is not str or fact_id not in valid_fact_refs:
                context.reject("FACT_VALUE_REFERENCE_INVALID", "S3-FACT-REFERENCE-SCOPE", path)
            return
    context.reject("FACT_VALUE_SHAPE_INVALID", "S3-FACT-VALUE-SHAPES", path)


def _check_claims(context: _ValidationContext) -> None:
    assert context.payload is not None
    claims = context.payload.get("claims")
    arrivals = context.payload.get("arrival_prose")
    if type(claims) is not list or len(claims) != 3:
        context.reject("CLAIM_GROUP_COUNT_INVALID", "S3-CLAIM-GROUPS-ORDER-LIMIT", "/claims")
    if type(arrivals) is not list or len(arrivals) != 3:
        context.reject("ARRIVAL_SEGMENT_COUNT_INVALID", "S3-ARRIVAL-ORDER-IDS-LIMITS", "/arrival_prose")

    segment_ids: list[str] = []
    segment_text: dict[str, str] = {}
    public_text: list[str] = []
    for index, (role, segment) in enumerate(zip(_ARRIVAL_ROLES, arrivals)):
        path = "/arrival_prose/" + str(index)
        expected_id = context.scene_id + ":arrival:" + role
        if type(segment) is not dict or set(segment) != {"id", "role", "text"} or segment.get("id") != expected_id or segment.get("role") != role:
            context.reject("ARRIVAL_ROLE_BINDING_INVALID", "S3-ARRIVAL-ORDER-IDS-LIMITS", path)
        text = segment.get("text")
        if type(text) is not str or not 1 <= len(text) <= 512:
            context.reject("ARRIVAL_TEXT_LENGTH_INVALID", "S3-ARRIVAL-ORDER-IDS-LIMITS", path + "/text")
        segment_ids.append(expected_id)
        segment_text[expected_id] = text
        public_text.append(text)

    if [group.get("segment_id") for group in claims if type(group) is dict] != segment_ids:
        context.reject("CLAIM_SEGMENT_BINDING_INVALID", "S3-CLAIM-SEGMENT-BINDING", "/claims")
    facts = context.payload["fixture_deltas"]["facts"]
    authored_ids = {fact["fact_id"] for fact in facts}
    valid_fact_ids = set(context.binding.public_base_fact_ids) | authored_ids
    seen_claim_ids: set[str] = set()
    for group_index, group in enumerate(claims):
        group_path = "/claims/" + str(group_index)
        if type(group) is not dict or set(group) != {"segment_id", "items"}:
            context.reject("CLAIM_GROUP_FIELDS_INVALID", "S3-CLAIM-GROUPS-ORDER-LIMIT", group_path)
        items = group.get("items")
        if type(items) is not list or len(items) > 32:
            context.reject("CLAIM_GROUP_LIMIT_INVALID", "S3-CLAIM-GROUPS-ORDER-LIMIT", group_path + "/items")
        text = segment_text[group["segment_id"]]
        for item_index, claim in enumerate(items):
            path = group_path + "/items/" + str(item_index)
            if type(claim) is not dict or set(claim) != set(_CLAIM_FIELDS):
                context.reject("CLAIM_FIELDS_INVALID", "S3-CLAIM-ID-UNIQUE-BOUNDS", path)
            claim_id = claim.get("id")
            if type(claim_id) is not str or len(claim_id) > 512 or re.fullmatch(context.binding.claim_id_pattern, claim_id) is None:
                context.reject("CLAIM_ID_INVALID", "S3-CLAIM-ID-UNIQUE-BOUNDS", path + "/id")
            if claim_id in seen_claim_ids:
                context.reject("CLAIM_ID_DUPLICATE", "S3-CLAIM-ID-UNIQUE-BOUNDS", path + "/id")
            seen_claim_ids.add(claim_id)
            fact_id = claim.get("fact_id")
            if type(fact_id) is not str or fact_id not in valid_fact_ids:
                context.reject("CLAIM_FACT_REFERENCE_INVALID", "S3-CLAIM-FACT-REFERENCES", path + "/fact_id")
            span = claim.get("span")
            if type(span) is not str or not 1 <= len(span) <= 512 or span not in text:
                context.reject("CLAIM_SPAN_INVALID", "S3-CLAIM-SPANS", path + "/span")
            public_text.append(span)
            kind = claim.get("kind")
            if kind == "invitation":
                if claim.get("choice") != "open" or claim.get("success") != "unspecified":
                    context.reject("INVITATION_AGENCY_INVALID", "S3-CLAIM-AGENCY", path)
            elif kind == "factual":
                if claim.get("choice") is not None or claim.get("success") is not None:
                    context.reject("FACTUAL_AGENCY_INVALID", "S3-CLAIM-AGENCY", path)
            else:
                context.reject("CLAIM_KIND_INVALID", "S3-CLAIM-AGENCY", path + "/kind")

    combined_text = "\n".join(public_text)
    if any(pattern.search(combined_text) for pattern in _AGENCY_PATTERNS):
        context.reject("PROSE_AGENCY_ASSERTION", "S3-PROSE-AGENCY", "/arrival_prose")


def _check_protected(context: _ValidationContext) -> None:
    assert context.payload is not None
    facts = context.payload["fixture_deltas"]["facts"]
    for index, fact in enumerate(facts):
        for unknown_name, protected_predicates in _UNKNOWN_PREDICATE_MAP.items():
            if unknown_name in context.binding.unknown_predicates and fact.get("predicate") in protected_predicates:
                context.reject("PROTECTED_UNKNOWN_PROMOTION", "S3-PROTECTED-UNKNOWNS", "/fixture_deltas/facts/" + str(index) + "/predicate")

    public_strings = [fact["value"] for fact in facts if type(fact.get("value")) is str]
    public_strings.extend(segment["text"] for segment in context.payload["arrival_prose"])
    public_strings.extend(claim["span"] for group in context.payload["claims"] for claim in group["items"])
    for marker in context.binding.guarded_markers:
        if marker and any(marker in text for text in public_strings):
            context.reject("GUARDED_MARKER_IN_PUBLIC_DELTA", "S3-GUARDED-CONTENT-MARKERS", "/arrival_prose")


_OUTPUT_CHECKS: Mapping[str, Callable[[_ValidationContext], None]] = MappingProxyType(
    {
        "parse": _check_parse,
        "overwrite": _check_base_overwrites,
        "entity_references": _check_topology_references,
        "schema": _check_schema,
        "references": _check_references,
        "roles": _check_roles,
        "facts": _check_facts,
        "claims": _check_claims,
        "protected": _check_protected,
    }
)


def _run_output_checks(
    context: _ValidationContext,
    checks: Mapping[str, Callable[[_ValidationContext], None]],
) -> None:
    for check in checks.values():
        check(context)


def rule_inventory() -> tuple[Mapping[str, Any], ...]:
    """Return stable output rules and separately categorized host controls."""

    rows: list[Mapping[str, Any]] = []
    for rule in OUTPUT_RULE_MAP + HOST_RULE_MAP:
        rows.append(
            MappingProxyType(
                {
                    "rule_id": rule.rule_id,
                    "category": rule.category,
                    "check_id": rule.check_id,
                    "summary": rule.summary,
                    "source_pointers": tuple(
                        source.artifact + "#" + source.pointer for source in rule.sources
                    ),
                }
            )
        )
    return tuple(rows)


def audit_rule_parity(
    scene_id: str,
    *,
    source_overrides: Mapping[str, Any] | None = None,
    validator_rules: tuple[RuleSpec, ...] | None = None,
    validator_checks: Mapping[str, Any] | None = None,
) -> tuple[RuleParityIssue, ...]:
    """Check rule/check registration and exact request/schema/input declarations.

    Overrides are in-memory test seams for semantic mutations; this function
    never writes protocol or canonical-input files.
    """

    binding = load_scene_binding(scene_id)
    sources = _load_rule_sources(scene_id, binding)
    for name, value in (source_overrides or {}).items():
        if name in sources:
            sources[name] = value
    rules = OUTPUT_RULE_MAP if validator_rules is None else validator_rules
    checks = _OUTPUT_CHECKS if validator_checks is None else validator_checks
    issues: list[RuleParityIssue] = []
    known_rule_ids = {row.rule_id for row in OUTPUT_RULE_MAP}
    seen: set[str] = set()
    rules_by_check: dict[str, int] = {}
    for rule in rules:
        if rule.rule_id in seen:
            issues.append(RuleParityIssue("DUPLICATE_RULE_ID", rule.rule_id, rule.category, "validator", ""))
        seen.add(rule.rule_id)
        rules_by_check[rule.check_id] = rules_by_check.get(rule.check_id, 0) + 1
        if rule.category != "output_contract":
            issues.append(RuleParityIssue("OUTPUT_RULE_MISCLASSIFIED", rule.rule_id, rule.category, "validator", ""))
        if rule.rule_id not in known_rule_ids:
            issues.append(RuleParityIssue("UNMAPPED_VALIDATOR_RULE", rule.rule_id, rule.category, "validator", rule.check_id))
        if rule.check_id not in checks:
            issues.append(RuleParityIssue("RULE_CHECK_MISSING", rule.rule_id, rule.category, "validator", rule.check_id))
        if not rule.sources:
            issues.append(RuleParityIssue("OUTPUT_RULE_WITHOUT_SOURCE", rule.rule_id, rule.category, "", ""))
        for source in rule.sources:
            document = sources.get(source.artifact, _UNSET)
            found, observed = _resolve_pointer(document, source.pointer, protocol.SCENE_ORDER.index(scene_id))
            if document is _UNSET or not found:
                issues.append(RuleParityIssue("SOURCE_DECLARATION_MISSING", rule.rule_id, rule.category, source.artifact, source.pointer))
                continue
            expected = source.expected
            if source.binding_key is not None:
                try:
                    expected = _binding_value(binding, source.binding_key)
                except (KeyError, TypeError):
                    issues.append(RuleParityIssue("RULE_SOURCE_BINDING_UNKNOWN", rule.rule_id, rule.category, source.artifact, source.pointer))
                    continue
                if source.binding_key in ("base_fact_ids", "unknown_predicates", "guarded_markers"):
                    observed = _project_bound_rows(source.binding_key, observed)
            if expected is not _UNSET and not _same_value(observed, expected):
                issues.append(RuleParityIssue("SOURCE_DECLARATION_CHANGED", rule.rule_id, rule.category, source.artifact, source.pointer))
            if source.expected_keys is not None and (
                not isinstance(observed, Mapping)
                or set(observed) != set(source.expected_keys)
            ):
                issues.append(RuleParityIssue("SOURCE_DECLARATION_KEYS_CHANGED", rule.rule_id, rule.category, source.artifact, source.pointer))
            if source.contains is not None and (type(observed) is not str or source.contains not in observed):
                issues.append(RuleParityIssue("REQUEST_DECLARATION_MISSING", rule.rule_id, rule.category, source.artifact, source.pointer))

    for missing_rule_id in sorted(known_rule_ids - seen):
        issues.append(RuleParityIssue("RULE_MAP_ENTRY_MISSING", missing_rule_id, "output_contract", "validator", ""))

    for check_id in checks:
        if check_id not in rules_by_check:
            issues.append(RuleParityIssue("UNMAPPED_VALIDATOR_CHECK", "UNMAPPED-VALIDATOR-CHECK", "output_contract", "validator", str(check_id)))
    for rule in HOST_RULE_MAP:
        if rule.category != "host_safety_integrity" or rule.check_id not in _HOST_CHECKS or rule.sources:
            issues.append(RuleParityIssue("HOST_RULE_MAP_INVALID", rule.rule_id, rule.category, "host", rule.check_id))
    for missing_host_check in sorted(set(_HOST_CHECKS) - {rule.check_id for rule in HOST_RULE_MAP}):
        issues.append(RuleParityIssue("UNMAPPED_HOST_CHECK", "UNMAPPED-HOST-CHECK", "host_safety_integrity", "host", missing_host_check))
    return tuple(issues)


def validate_delta_payload(output_bytes: object, *, scene_id: str) -> Mapping[str, Any]:
    """Validate one output and return a recursively immutable JSON value."""

    if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
        raise ContractError("SCENE_NOT_APPROVED", "S3-JSON-OBJECT", "/scene_id")
    if type(output_bytes) is not bytes:
        raise ContractError("OUTPUT_BYTES_INVALID", "S3-JSON-OBJECT")
    if len(output_bytes) > MAX_DELTA_BYTES:
        raise ContractError("OUTPUT_BYTE_LIMIT", "S3-JSON-BYTE-LIMIT")
    _ensure_check_registry()
    binding = load_scene_binding(scene_id)
    issues = audit_rule_parity(scene_id)
    if issues:
        issue = issues[0]
        raise ContractError("RULE_MAP_PARITY_FAILED", issue.rule_id, issue.pointer)
    context = _ValidationContext(output_bytes, scene_id, binding)
    _run_output_checks(context, _OUTPUT_CHECKS)
    if context.payload is None:
        raise ContractError("OUTPUT_JSON_INVALID", "S3-JSON-OBJECT")
    return _freeze_json(context.payload)


def load_scene_binding(scene_id: str) -> SceneBinding:
    """Load, hash-check, and freeze the scene's bound canonical inputs."""

    if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
        raise ContractError("SCENE_NOT_APPROVED", "S3-JSON-OBJECT", "/scene_id")
    docs = _load_verified_protocol_documents()
    bindings = docs["input_bindings"]
    scenes = bindings.get("scenes")
    if type(scenes) is not list:
        raise ContractError("INPUT_BINDINGS_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/scenes")
    row = next((item for item in scenes if type(item) is dict and item.get("scene_id") == scene_id), None)
    if type(row) is not dict:
        raise ContractError("SCENE_BINDING_MISSING", "HOST-CANONICAL-HASH-INTEGRITY", "/scenes")
    refs = row.get("input_refs")
    if type(refs) is not dict or set(refs) != set(_REFERENCE_FIELDS):
        raise ContractError("SCENE_BINDING_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/input_refs")

    source_bytes = _read_bound_reference(refs["source_packet"])
    expected_bytes = _read_bound_reference(refs["expected_bundle"])
    source_packet = _parse_object(source_bytes, host=True)
    expected = _parse_object(expected_bytes, host=True)
    topology = expected.get("approved_topology")
    source_facts = expected.get("source_facts")
    protected = expected.get("protected_unknowns")
    if (
        expected.get("schema") != "neq.llm_staging_expected_inputs.v1"
        or expected.get("scene_id") != scene_id
        or type(topology) is not dict
        or type(source_facts) is not dict
        or type(protected) is not dict
        or type(source_packet.get("location")) is not dict
        or source_facts.get("source_packet_path") != refs["source_packet"].get("id")
        or source_facts.get("source_packet_sha256") != refs["source_packet"].get("sha256")
    ):
        raise ContractError("CANONICAL_INPUT_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/expected_bundle")

    topology_hash = hashlib.sha256(_canonical_json_bytes(topology)).hexdigest()
    if (
        topology.get("scene_id") != scene_id
        or topology.get("module_id") != row.get("module_id")
        or topology.get("topology_id") != refs.get("topology", {}).get("id")
        or topology_hash != refs.get("topology", {}).get("sha256")
        or refs.get("gate_canonical_context", {}).get("id") != scene_id + "#gate-canonical-context:" + str(topology.get("topology_id"))
        or refs.get("gate_canonical_context", {}).get("sha256") != topology_hash
    ):
        raise ContractError("CANONICAL_TOPOLOGY_BINDING_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/approved_topology")

    nodes = topology.get("nodes")
    raw_roles = topology.get("stage_role_bindings")
    node_binding = row.get("topology_node_ids")
    role_binding = row.get("stage_role_candidates")
    if type(nodes) is not list or type(raw_roles) is not dict or type(node_binding) is not list or type(role_binding) is not dict:
        raise ContractError("CANONICAL_TOPOLOGY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/approved_topology")
    node_ids: list[str] = []
    for node in nodes:
        if type(node) is not dict or type(node.get("id")) is not str:
            raise ContractError("CANONICAL_TOPOLOGY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/approved_topology/nodes")
        node_ids.append(node["id"])
    if len(node_ids) != len(set(node_ids)) or node_binding != node_ids or set(raw_roles) != set(_ROLE_NAMES) or set(role_binding) != set(_ROLE_NAMES):
        raise ContractError("CANONICAL_TOPOLOGY_BINDING_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/stage_role_candidates")
    roles: dict[str, tuple[str, ...]] = {}
    for role in _ROLE_NAMES:
        raw_values = raw_roles.get(role)
        if (
            type(raw_values) is not list
            or not raw_values
            or any(type(value) is not str or value not in set(node_ids) for value in raw_values)
            or len(raw_values) != len(set(raw_values))
            or role_binding.get(role) != raw_values
        ):
            raise ContractError("CANONICAL_TOPOLOGY_BINDING_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/stage_role_candidates/" + role)
        roles[role] = tuple(raw_values)

    facts = source_facts.get("facts")
    public_binding = row.get("public_base_fact_ids")
    if type(facts) is not list or type(public_binding) is not list:
        raise ContractError("CANONICAL_FACTS_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts/facts")
    base_ids: list[str] = []
    public_ids: list[str] = []
    for fact in facts:
        if type(fact) is not dict or type(fact.get("fact_id")) is not str:
            raise ContractError("CANONICAL_FACTS_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts/facts")
        base_ids.append(fact["fact_id"])
        if fact.get("audience") == "public_candidate_subject_to_semantic_review":
            public_ids.append(fact["fact_id"])
    if len(base_ids) != len(set(base_ids)) or public_binding != public_ids:
        raise ContractError("CANONICAL_FACT_BINDING_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/public_base_fact_ids")

    if protected.get("protected_unknowns_must_not_be_promoted") is not True:
        raise ContractError("CANONICAL_UNKNOWN_POLICY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/protected_unknowns")
    unknown_rows = protected.get("unknowns")
    marker_rows = protected.get("guarded_content_markers")
    if type(unknown_rows) is not list or type(marker_rows) is not list:
        raise ContractError("CANONICAL_UNKNOWN_POLICY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/protected_unknowns")
    unknowns: set[str] = set()
    for item in unknown_rows:
        if type(item) is not dict or type(item.get("predicate")) is not str:
            raise ContractError("CANONICAL_UNKNOWN_POLICY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/protected_unknowns/unknowns")
        if item.get("status") == "unknown":
            unknowns.add(item["predicate"])
    markers: list[str] = []
    for item in marker_rows:
        if type(item) is not dict or type(item.get("exact_value")) is not str:
            raise ContractError("CANONICAL_UNKNOWN_POLICY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/protected_unknowns/guarded_content_markers")
        markers.append(item["exact_value"])

    return SceneBinding(
        scene_id=scene_id,
        module_id=row["module_id"],
        input_refs=_freeze_json(refs),
        topology_node_ids=tuple(node_ids),
        role_candidates=MappingProxyType(roles),
        public_base_fact_ids=tuple(public_ids),
        base_fact_ids=frozenset(base_ids),
        unknown_predicates=frozenset(unknowns),
        guarded_markers=tuple(markers),
        expected_bundle=_freeze_json(expected),
    )


def _load_rule_sources(scene_id: str, binding: SceneBinding) -> dict[str, Any]:
    docs = _load_verified_protocol_documents()
    try:
        schema = protocol.render_output_schema(scene_id)
        system_prompt = protocol.render_system_prompt(scene_id)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ContractError("RENDERED_REQUEST_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/rendered_scene_artifacts") from None
    return {
        "model_contract": docs["model_contract"],
        "input_bindings": docs["input_bindings"],
        "expected_bundle": binding.expected_bundle,
        "rendered_schema": schema,
        "system_prompt": {"lines": {str(index): line for index, line in enumerate(system_prompt.splitlines(), 1)}},
        "task_prompt": {"lines": {str(index): line for index, line in enumerate(docs["task_prompt_template"].splitlines(), 1)}},
    }


def _load_verified_protocol_documents() -> dict[str, Any]:
    root = protocol.PROTOCOL_RELATIVE
    manifest_bytes = _safe_project_read(root + "/staging-manifest.json")
    if hashlib.sha256(manifest_bytes).hexdigest() != protocol.STUDY3_MANIFEST_SHA256:
        raise ContractError("STUDY3_MANIFEST_HASH_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/staging-manifest.json")
    manifest = _parse_object(manifest_bytes, host=True)
    if manifest.get("schema") != "neq.llm_staging_study3_manifest.v1" or manifest.get("study_id") != protocol.STUDY_ID or tuple(manifest.get("scene_order", ())) != protocol.SCENE_ORDER:
        raise ContractError("STUDY3_MANIFEST_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/staging-manifest.json")
    paths = {
        "model_contract": ("model_contract", root + "/model-contract.json"),
        "input_bindings": ("input_bindings", root + "/input-bindings.json"),
        "schema_template": ("schema_template", root + "/output-contract.schema.json"),
        "system_prompt_template": ("system_prompt_template", root + "/system-prompt.txt"),
        "task_prompt_template": ("task_prompt_template", root + "/task-prompt.txt"),
    }
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not dict:
        raise ContractError("STUDY3_ARTIFACT_BINDING_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/artifacts")
    raw_docs: dict[str, bytes] = {}
    for name, (manifest_name, path) in paths.items():
        record = artifacts.get(manifest_name)
        if type(record) is not dict or record.get("path") != path or type(record.get("sha256")) is not str:
            raise ContractError("STUDY3_ARTIFACT_BINDING_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/artifacts/" + name)
        raw = _safe_project_read(path)
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ContractError("STUDY3_ARTIFACT_HASH_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/artifacts/" + name)
        raw_docs[name] = raw
    try:
        documents = {
            "model_contract": _parse_object(raw_docs["model_contract"], host=True),
            "input_bindings": _parse_object(raw_docs["input_bindings"], host=True),
            "schema_template": _parse_object(raw_docs["schema_template"], host=True),
            "system_prompt_template": raw_docs["system_prompt_template"].decode("utf-8"),
            "task_prompt_template": raw_docs["task_prompt_template"].decode("utf-8"),
        }
    except UnicodeDecodeError:
        raise ContractError("STUDY3_PROTOCOL_UTF8_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/protocol") from None
    contract_bindings = documents["model_contract"].get("canonical_bindings")
    bindings_doc = documents["input_bindings"]
    scene_rows = bindings_doc.get("scenes")
    bound_scene_order = (
        tuple(row.get("scene_id") for row in scene_rows if type(row) is dict)
        if type(scene_rows) is list
        else None
    )
    if (
        type(contract_bindings) is not dict
        or contract_bindings.get("artifact_path") != paths["input_bindings"][1]
        or contract_bindings.get("artifact_sha256") != hashlib.sha256(raw_docs["input_bindings"]).hexdigest()
        or bindings_doc.get("schema") != "neq.llm_staging_study3_input_bindings.v1"
        or bindings_doc.get("study_id") != protocol.STUDY_ID
        or bound_scene_order != protocol.SCENE_ORDER
    ):
        raise ContractError("STUDY3_INPUT_BINDINGS_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/input-bindings.json")
    return documents


def _read_bound_reference(reference: object) -> bytes:
    if type(reference) is not dict:
        raise ContractError("CANONICAL_REFERENCE_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/input_refs")
    path = reference.get("id")
    digest = reference.get("sha256")
    if type(path) is not str or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ContractError("CANONICAL_REFERENCE_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/input_refs")
    raw = _safe_project_read(path)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ContractError("CANONICAL_INPUT_HASH_MISMATCH", "HOST-CANONICAL-HASH-INTEGRITY", "/input_refs")
    return raw


def _safe_project_read(relative_path: str, *, root: Path | None = None) -> bytes:
    """Read a project-relative regular file; reject traversal and symlinks."""

    base = protocol.REPO_ROOT if root is None else root
    if type(relative_path) is not str or not relative_path or "\\" in relative_path:
        raise ContractError("PROJECT_PATH_REJECTED", "HOST-PROJECT-PATH-BOUNDARY")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or pure.as_posix() != relative_path or any(part in ("", ".", "..") for part in relative_path.split("/")):
        raise ContractError("PROJECT_PATH_REJECTED", "HOST-PROJECT-PATH-BOUNDARY")
    try:
        root_path = base.resolve(strict=True)
        current = root_path
        for part in pure.parts:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ContractError("PROJECT_PATH_REJECTED", "HOST-PROJECT-PATH-BOUNDARY")
        resolved = current.resolve(strict=True)
        resolved.relative_to(root_path)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ContractError("PROJECT_FILE_INVALID", "HOST-PROJECT-PATH-BOUNDARY")
        return resolved.read_bytes()
    except ContractError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise ContractError("PROJECT_FILE_UNAVAILABLE", "HOST-PROJECT-PATH-BOUNDARY") from None


_HOST_CHECKS: Mapping[str, Callable[..., Any]] = MappingProxyType(
    {"safe_read": _safe_project_read, "canonical_integrity": _load_verified_protocol_documents}
)


def _parse_object(raw: bytes, *, host: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        if host:
            raise ContractError("CANONICAL_JSON_INVALID", "HOST-CANONICAL-HASH-INTEGRITY") from None
        raise
    if type(value) is not dict:
        if host:
            raise ContractError("CANONICAL_JSON_OBJECT_REQUIRED", "HOST-CANONICAL-HASH-INTEGRITY")
        raise ValueError("json object required")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise _NonFinite("non-finite value")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _NonFinite("non-finite number")
    return number


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ContractError("CANONICAL_TOPOLOGY_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "/approved_topology") from None


def _binding_value(binding: SceneBinding, key: str) -> Any:
    values: dict[str, Any] = {
        "root_fields": _ROOT_FIELDS,
        "reference_fields": _REFERENCE_FIELDS,
        "fact_fields": _FACT_FIELDS,
        "claim_fields": _CLAIM_FIELDS,
        "role_names": _ROLE_NAMES,
        "arrival_roles": _ARRIVAL_ROLES,
        "predicates": _PREDICATES,
        "input_refs": binding.input_refs,
        "module_id": binding.module_id,
        "topology_node_ids": binding.topology_node_ids,
        "role_candidates": binding.role_candidates,
        "public_base_fact_ids": binding.public_base_fact_ids,
        "base_fact_ids": tuple(sorted(binding.base_fact_ids)),
        "unknown_predicates": tuple(sorted(binding.unknown_predicates)),
        "guarded_markers": binding.guarded_markers,
        "authored_fact_pattern": binding.authored_fact_pattern,
        "claim_id_pattern": binding.claim_id_pattern,
        "object_id_schema": {
            "anyOf": [
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "enum": list(binding.topology_node_ids),
                },
                {"type": "null"},
            ]
        }["anyOf"],
        "fact_reference_schema": {
            "anyOf": [
                {"type": "string", "enum": list(binding.public_base_fact_ids)},
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "pattern": binding.authored_fact_pattern,
                },
            ]
        },
        "arrival_id.approach": binding.scene_id + ":arrival:approach",
        "arrival_id.threshold": binding.scene_id + ":arrival:threshold",
        "arrival_id.focal": binding.scene_id + ":arrival:focal",
        "role_candidates.usable_space": binding.role_candidates["usable_space"],
    }
    if key.startswith("input_refs."):
        current: Any = binding.input_refs
        for part in key.split(".")[1:]:
            current = current[part]
        return current
    if key.startswith("role_candidates."):
        return binding.role_candidates[key.split(".", 1)[1]]
    return values[key]


def _project_bound_rows(binding_key: str, rows: Any) -> Any:
    if not isinstance(rows, (list, tuple)):
        return rows
    if binding_key == "base_fact_ids":
        return tuple(sorted(row.get("fact_id") for row in rows if isinstance(row, Mapping) and type(row.get("fact_id")) is str))
    if binding_key == "unknown_predicates":
        return tuple(sorted(row.get("predicate") for row in rows if isinstance(row, Mapping) and row.get("status") == "unknown" and type(row.get("predicate")) is str))
    if binding_key == "guarded_markers":
        return tuple(row.get("exact_value") for row in rows if isinstance(row, Mapping) and type(row.get("exact_value")) is str)
    return rows


def _resolve_pointer(document: Any, pointer: str, scene_index: int) -> tuple[bool, Any]:
    if pointer == "":
        return True, document
    if not pointer.startswith("/"):
        return False, None
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if token == "*":
            token = str(scene_index)
        if isinstance(current, Mapping):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, (list, tuple)):
            if not token.isdigit() or int(token) >= len(current):
                return False, None
            current = current[int(token)]
        else:
            return False, None
    return True, current


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_same_value(left[key], right[key]) for key in right)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _json_equal(left: Any, right: Any) -> bool:
    return _same_value(left, right)


def _schema_rule_id(error: Any, payload: Mapping[str, Any]) -> str:
    path = tuple(error.absolute_path)
    schema_path = tuple(error.absolute_schema_path)
    validator = error.validator
    if path and path[0] == "input_refs":
        if validator == "const":
            return "S3-EXACT-INPUT-REFERENCES"
        return "S3-REFERENCE-KEYS-BOUNDS"
    if path and path[0] == "fixture_deltas":
        if "allOf" in schema_path and 0 in schema_path:
            return "S3-APPROACH-RELATION-TRUE"
        if "allOf" in schema_path and 1 in schema_path:
            return "S3-THRESHOLD-RELATION-TRUE"
        if "predicate" in path:
            return "S3-PREDICATE-ALLOWLIST"
        if "fact_id" in path:
            return "S3-AUTHORED-ID-NAMESPACE" if validator == "pattern" else "S3-AUTHORED-ID-LIMIT-UNIQUE"
        if "subject_id" in path or "object_id" in path:
            return "S3-ENTITY-REFERENCE-SCOPE"
        if "value" in path:
            return "S3-FACT-VALUE-SHAPES"
        if validator in ("minItems", "maxItems", "contains", "minContains", "maxContains"):
            return "S3-FACT-COUNT-BOUNDS"
        if validator == "additionalProperties" or validator == "required":
            return "S3-FACT-FIELDS" if len(path) > 2 else "S3-DELTA-ONLY-OVERWRITE"
        return "S3-FACT-FIELDS"
    if path and path[0] == "stage_role_bindings":
        if len(path) <= 1 or validator in ("additionalProperties", "required"):
            return "S3-STAGE-ROLE-FIELDS"
        if validator in ("minItems", "maxItems", "uniqueItems"):
            return "S3-STAGE-ROLE-BOUNDS-UNIQUE"
        return "S3-STAGE-ROLE-CANDIDATES"
    if path and path[0] == "claims":
        if len(path) == 1 or validator in ("minItems", "maxItems") and "items" not in path:
            return "S3-CLAIM-GROUPS-ORDER-LIMIT"
        if "segment_id" in path:
            return "S3-CLAIM-SEGMENT-BINDING"
        if "id" in path:
            return "S3-CLAIM-ID-UNIQUE-BOUNDS"
        if "fact_id" in path:
            return "S3-CLAIM-FACT-REFERENCES"
        if "span" in path:
            return "S3-CLAIM-SPANS"
        if "choice" in path or "success" in path or "kind" in path:
            return "S3-CLAIM-AGENCY"
        if validator in ("additionalProperties", "required"):
            return "S3-CLAIM-FIELDS" if "items" in path else "S3-CLAIM-GROUPS-ORDER-LIMIT"
        return "S3-CLAIM-GROUPS-ORDER-LIMIT"
    if path and path[0] == "arrival_prose":
        return "S3-ARRIVAL-ORDER-IDS-LIMITS"
    return "S3-ROOT-FIELDS"


def _pointer_from_parts(parts: object) -> str:
    if not isinstance(parts, (list, tuple)):
        return ""
    encoded: list[str] = []
    for part in parts[:12]:
        value = str(part).replace("~", "~0").replace("/", "~1")
        encoded.append("".join(char for char in value if char.isprintable())[:32])
    return "/" + "/".join(encoded) if encoded else ""


def _bounded(value: str) -> str:
    return "".join(char for char in value if char.isprintable())[:160] if type(value) is str else ""


def _freeze_json(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_json(item) for item in value)
    return value


def _ensure_check_registry() -> None:
    mapped = {rule.check_id for rule in OUTPUT_RULE_MAP}
    if mapped != set(_OUTPUT_CHECKS):
        raise ContractError("RULE_MAP_INCOMPLETE", "UNMAPPED-VALIDATOR-CHECK", "/validator_checks")
    host_mapped = {rule.check_id for rule in HOST_RULE_MAP}
    if host_mapped != set(_HOST_CHECKS):
        raise ContractError("HOST_RULE_MAP_INCOMPLETE", "HOST-CANONICAL-HASH-INTEGRITY", "/host_checks")


__all__ = [
    "ContractError",
    "HOST_RULE_MAP",
    "OUTPUT_RULE_MAP",
    "RuleParityIssue",
    "RuleSpec",
    "SceneBinding",
    "audit_rule_parity",
    "load_scene_binding",
    "rule_inventory",
    "validate_delta_payload",
]
