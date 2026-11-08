# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Deterministic, provider-free matched projections for supplied fixtures.

The API validates a candidate against a separately supplied fixture reference,
then filters audience-scoped records before rendering or exporting hashes. Its
arrival check accepts only exact approved fixture fragments; it is not a
general natural-language validator.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from . import knowledge


_AUDIENCES = {"public", "gm_narrator"}
_CONDITIONS = ("A", "B", "C", "D")
_FACT_KEYS = {
    "id",
    "scene_id",
    "subject_id",
    "predicate",
    "object_id",
    "status",
    "knowledge_status",
    "audience",
    "value",
    "provenance",
}
_PROVENANCE_KEYS = {"class", "source_refs"}
_TOPOLOGY_KEYS = {"scene_nodes", "links", "schematic_layout"}
_SCENE_NODE_KEYS = {"id", "label", "knowledge_status"}
_TOPOLOGY_LINK_KEYS = {"id", "from_scene_id", "to_scene_id", "relation"}
_LAYOUT_KEYS = {"scene_id", "anchor_id", "label", "row", "column"}
_ARRIVAL_KEYS = {"id", "role", "text", "fact_ids"}
_APPROVAL_KEYS = {"id", "role", "text_sha256", "fact_ids"}
_FACT_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:fact:[a-z0-9][a-z0-9_-]{0,63}$"
)
_SCENE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:scene:[a-z0-9][a-z0-9_-]{0,63}$"
)
_ENTITY_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:entity:[a-z0-9][a-z0-9_-]{0,63}$"
)
_SOURCE_REF_RE = re.compile(r"^source:[a-z0-9][a-z0-9._/-]{0,127}$")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SEGMENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KNOWLEDGE_STATUSES = {"known", "discovered", "visited", "rumoured"}
_PROVENANCE_CLASSES = {"source_extracted", "builder_authored", "unknown"}
_ARRIVAL_ROLES = ("approach", "threshold", "focal")
_MAX_FACTS = 64
_MAX_TEXT_LENGTH = 2048
_MAX_ARRIVAL_SEGMENTS = 8
_MAX_LAYOUT_COORDINATE = 10_000
_MAX_GRID_RECORDS = 64


class ProjectionError(ValueError):
    """Stable fail-closed error for malformed or mismatched projection inputs."""

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(code + " at " + path)


def canonical_json(value: object) -> str:
    """Return stable JSON for bounded fixture values, rejecting non-JSON data."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ProjectionError("CANONICAL_JSON_VALUE", "$") from exc


def build_matched_projections(
    candidate: object,
    reference: object,
    *,
    audience: object,
) -> dict[str, dict[str, Any]]:
    """Emit A/B/C/D outputs over one normalized, audience-filtered fact set.

    The caller supplies the candidate and independent reference separately.
    Candidate facts, full topology, and approved arrival fragments are checked
    against that reference before the allowlisted view is rendered. The
    reference is a bounded fixture contract, not an external trust service.
    """

    if type(audience) is not str or audience not in _AUDIENCES:
        raise ProjectionError("AUDIENCE_NOT_ALLOWLISTED", "$.audience")
    _validate_candidate_shape(candidate)
    _validate_reference_shape(reference, candidate)
    assert type(candidate) is dict
    assert type(reference) is dict

    all_facts = _validate_and_normalize_facts(
        candidate["facts"], reference, "gm_narrator"
    )
    all_topology = _normalize_topology(candidate["topology"])
    _validate_fact_references(all_facts, all_topology)
    _validate_fact_bindings(all_facts, reference)
    expected_all_topology = _normalize_topology(
        reference["topology_by_audience"]["gm_narrator"]
    )
    if canonical_json(all_topology) != canonical_json(expected_all_topology):
        raise ProjectionError("TOPOLOGY_BINDING_MISMATCH", "$.candidate.topology")

    try:
        scoped = knowledge.filter_scoped_fact_view(
            all_facts,
            all_topology,
            reference["scope"],
            audience=audience,
        )
    except knowledge.KnowledgeFixtureError as exc:
        raise ProjectionError(exc.code, exc.path) from exc
    visible_facts = _validate_and_normalize_facts(
        scoped["facts"], reference, audience
    )
    visible_topology = _normalize_topology(scoped["topology"])
    _validate_fact_references(visible_facts, visible_topology)
    expected_topology = _normalize_topology(
        reference["topology_by_audience"][audience]
    )
    if canonical_json(visible_topology) != canonical_json(expected_topology):
        raise ProjectionError(
            "SCOPED_TOPOLOGY_REFERENCE_MISMATCH",
            "$.reference.topology_by_audience." + audience,
        )

    visible_ids = {fact["id"] for fact in visible_facts}
    arrival_segments, arrival_bindings = _validate_arrival(
        candidate["arrival_segments"],
        reference["arrival_approvals"],
        visible_facts,
        visible_ids,
    )

    binding = _build_binding(candidate["fixture_id"], audience, visible_facts, visible_topology)
    outputs: dict[str, dict[str, Any]] = {}
    for condition in _CONDITIONS:
        content, content_type = _render_condition(
            condition,
            visible_facts,
            visible_topology,
            arrival_segments,
        )
        hashes = _build_hashes(condition, audience, content, binding)
        output: dict[str, Any] = {
            "condition": condition,
            "audience": audience,
            "content_type": content_type,
            "content": content,
            "binding": copy.deepcopy(binding),
            "hashes": hashes,
        }
        if condition == "D":
            output["staging_claim_bindings"] = copy.deepcopy(arrival_bindings)
        outputs[condition] = output
    return outputs


def _validate_candidate_shape(candidate: object) -> None:
    expected = {
        "schema_version",
        "fixture_id",
        "facts",
        "topology",
        "arrival_segments",
    }
    _record(candidate, expected, "$.candidate")
    assert type(candidate) is dict
    if type(candidate["schema_version"]) is not int or candidate["schema_version"] != 1:
        raise ProjectionError("SCHEMA_VERSION", "$.candidate.schema_version")
    if type(candidate["fixture_id"]) is not str or not _SCENE_ID_RE.fullmatch(candidate["fixture_id"]):
        raise ProjectionError("FIXTURE_ID", "$.candidate.fixture_id")


def _validate_reference_shape(reference: object, candidate: object) -> None:
    expected = {
        "schema_version",
        "fixture_id",
        "fact_digests",
        "scope",
        "topology_by_audience",
        "arrival_approvals",
    }
    _record(reference, expected, "$.reference")
    assert type(reference) is dict
    assert type(candidate) is dict
    if type(reference["schema_version"]) is not int or reference["schema_version"] != 1:
        raise ProjectionError("SCHEMA_VERSION", "$.reference.schema_version")
    if reference["fixture_id"] != candidate["fixture_id"]:
        raise ProjectionError("FIXTURE_ID_MISMATCH", "$.reference.fixture_id")
    topology_by_audience = reference["topology_by_audience"]
    _record(topology_by_audience, _AUDIENCES, "$.reference.topology_by_audience")
    scope = reference["scope"]
    _record(scope, {"audience_fact_ids", "topology_record_ids"}, "$.reference.scope")
    _record(scope["audience_fact_ids"], _AUDIENCES, "$.reference.scope.audience_fact_ids")
    _record(scope["topology_record_ids"], _AUDIENCES, "$.reference.scope.topology_record_ids")
    for audience in sorted(_AUDIENCES):
        ids = scope["audience_fact_ids"][audience]
        if type(ids) not in (list, tuple) or len(ids) > _MAX_FACTS:
            raise ProjectionError("SCOPED_FACT_IDS", "$.reference.scope.audience_fact_ids." + audience)
        if any(type(item) is not str or not _FACT_ID_RE.fullmatch(item) for item in ids):
            raise ProjectionError("SCOPED_FACT_ID", "$.reference.scope.audience_fact_ids." + audience)
        if len(set(ids)) != len(ids):
            raise ProjectionError("DUPLICATE_SCOPED_FACT_ID", "$.reference.scope.audience_fact_ids." + audience)
        _record(
            scope["topology_record_ids"][audience],
            _TOPOLOGY_KEYS,
            "$.reference.scope.topology_record_ids." + audience,
        )
        for group in sorted(_TOPOLOGY_KEYS):
            group_ids = scope["topology_record_ids"][audience][group]
            if type(group_ids) not in (list, tuple) or len(group_ids) > _MAX_FACTS:
                raise ProjectionError(
                    "SCOPED_TOPOLOGY_IDS",
                    "$.reference.scope.topology_record_ids." + audience + "." + group,
                )
            if any(type(item) is not str or not item for item in group_ids):
                raise ProjectionError(
                    "SCOPED_TOPOLOGY_ID",
                    "$.reference.scope.topology_record_ids." + audience + "." + group,
                )
            if len(set(group_ids)) != len(group_ids):
                raise ProjectionError(
                    "DUPLICATE_SCOPED_TOPOLOGY_ID",
                    "$.reference.scope.topology_record_ids." + audience + "." + group,
                )

    digests = reference["fact_digests"]
    if type(digests) is not dict or len(digests) > _MAX_FACTS:
        raise ProjectionError("FACT_DIGESTS", "$.reference.fact_digests")
    for fact_id, digest in digests.items():
        if type(fact_id) is not str or not _FACT_ID_RE.fullmatch(fact_id):
            raise ProjectionError("FACT_DIGEST_ID", "$.reference.fact_digests")
        if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
            raise ProjectionError("FACT_DIGEST", "$.reference.fact_digests." + fact_id)
    public_ids = set(scope["audience_fact_ids"]["public"])
    gm_ids = set(scope["audience_fact_ids"]["gm_narrator"])
    if not public_ids <= gm_ids or gm_ids != set(digests):
        raise ProjectionError("SCOPED_FACT_REFERENCE", "$.reference.scope.audience_fact_ids")
    if type(reference["arrival_approvals"]) not in (list, tuple):
        raise ProjectionError("ARRIVAL_APPROVALS_TYPE", "$.reference.arrival_approvals")
    if len(reference["arrival_approvals"]) > _MAX_ARRIVAL_SEGMENTS:
        raise ProjectionError("COLLECTION_LIMIT", "$.reference.arrival_approvals")


def _validate_and_normalize_facts(
    value: object, reference: dict[str, Any], audience: str
) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > _MAX_FACTS:
        raise ProjectionError("FACTS_TYPE", "$.candidate.facts")
    expected_ids = set(reference["scope"]["audience_fact_ids"][audience])
    facts_by_id: dict[str, dict[str, Any]] = {}
    for index, fact in enumerate(value):
        path = "$.candidate.facts[%d]" % index
        _record(fact, _FACT_KEYS, path)
        assert type(fact) is dict
        fact_id = fact["id"]
        if type(fact_id) is not str or not _FACT_ID_RE.fullmatch(fact_id):
            raise ProjectionError("FACT_ID", path + ".id")
        if fact_id in facts_by_id:
            raise ProjectionError("DUPLICATE_FACT_ID", path + ".id")
        if fact_id not in expected_ids:
            raise ProjectionError("UNAPPROVED_FACT_ID", path + ".id")
        _validate_fact(fact, path)
        facts_by_id[fact_id] = copy.deepcopy(fact)
    if facts_by_id.keys() != expected_ids:
        raise ProjectionError("FACT_SET_MISMATCH", "$.candidate.facts")

    public_ids = set(reference["scope"]["audience_fact_ids"]["public"])
    for fact_id, fact in facts_by_id.items():
        expected_audience = "public" if fact_id in public_ids else "gm_only"
        if fact["audience"] != expected_audience:
            raise ProjectionError("FACT_AUDIENCE_MISMATCH", "$.candidate.facts[" + fact_id + "].audience")
    return [facts_by_id[fact_id] for fact_id in sorted(facts_by_id)]


def _validate_fact_bindings(
    facts: list[dict[str, Any]], reference: dict[str, Any]
) -> None:
    for fact in facts:
        if _sha256(fact) != reference["fact_digests"][fact["id"]]:
            raise ProjectionError(
                "FACT_BINDING_MISMATCH",
                "$.candidate.facts[" + fact["id"] + "]",
            )


def _validate_fact(fact: dict[str, Any], path: str) -> None:
    for field in ("id",):
        if type(fact[field]) is not str:
            raise ProjectionError("FACT_ID", path + "." + field)
    if type(fact["scene_id"]) is not str or not _SCENE_ID_RE.fullmatch(fact["scene_id"]):
        raise ProjectionError("FACT_SCENE_ID", path + ".scene_id")
    for field in ("subject_id", "object_id"):
        value = fact[field]
        if type(value) is not str or not (
            _SCENE_ID_RE.fullmatch(value) or _ENTITY_ID_RE.fullmatch(value)
        ):
            raise ProjectionError("FACT_REFERENCE", path + "." + field)
    if type(fact["predicate"]) is not str or not _TOKEN_RE.fullmatch(fact["predicate"]):
        raise ProjectionError("FACT_PREDICATE", path + ".predicate")
    if type(fact["status"]) is not str or fact["status"] not in (
        "known",
        "unknown",
    ):
        raise ProjectionError("FACT_STATUS", path + ".status")
    if type(fact["knowledge_status"]) is not str or fact["knowledge_status"] not in _KNOWLEDGE_STATUSES:
        raise ProjectionError("KNOWLEDGE_STATUS", path + ".knowledge_status")
    if type(fact["audience"]) is not str or fact["audience"] not in (
        "public",
        "gm_only",
    ):
        raise ProjectionError("FACT_AUDIENCE", path + ".audience")
    if fact["status"] == "unknown":
        if fact["value"] is not None:
            raise ProjectionError("UNKNOWN_FACT_HAS_VALUE", path + ".value")
    elif type(fact["value"]) is not str or not fact["value"].strip() or len(fact["value"]) > _MAX_TEXT_LENGTH or not fact["value"].isascii():
        raise ProjectionError("KNOWN_FACT_VALUE", path + ".value")

    provenance = fact["provenance"]
    _record(provenance, _PROVENANCE_KEYS, path + ".provenance")
    provenance_class = provenance["class"]
    refs = provenance["source_refs"]
    if type(provenance_class) is not str or provenance_class not in _PROVENANCE_CLASSES:
        raise ProjectionError("PROVENANCE_CLASS", path + ".provenance.class")
    if type(refs) is not list or len(refs) > 16:
        raise ProjectionError("SOURCE_REFS_TYPE", path + ".provenance.source_refs")
    if any(type(ref) is not str or not _SOURCE_REF_RE.fullmatch(ref) for ref in refs):
        raise ProjectionError("SOURCE_REF", path + ".provenance.source_refs")
    if len(set(refs)) != len(refs):
        raise ProjectionError("DUPLICATE_SOURCE_REF", path + ".provenance.source_refs")
    if fact["status"] == "unknown":
        if provenance_class != "unknown" or refs:
            raise ProjectionError("UNKNOWN_PROVENANCE", path + ".provenance")
    elif provenance_class not in ("source_extracted", "builder_authored"):
        raise ProjectionError("KNOWN_PROVENANCE", path + ".provenance")
    if provenance_class == "source_extracted" and not refs:
        raise ProjectionError("MISSING_SOURCE_REF", path + ".provenance.source_refs")


def _normalize_topology(value: object) -> dict[str, Any]:
    _record(value, _TOPOLOGY_KEYS, "$.candidate.topology")
    assert type(value) is dict
    normalized: dict[str, Any] = {}
    group_specs = (
        ("scene_nodes", _SCENE_NODE_KEYS, "id"),
        ("links", _TOPOLOGY_LINK_KEYS, "id"),
        ("schematic_layout", _LAYOUT_KEYS, "anchor_id"),
    )
    for group, keys, sort_key in group_specs:
        items = value[group]
        if type(items) is not list or len(items) > _MAX_FACTS:
            raise ProjectionError("TOPOLOGY_GROUP_TYPE", "$.candidate.topology." + group)
        normalized_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            path = "$.candidate.topology.%s[%d]" % (group, index)
            _record(item, keys, path)
            assert type(item) is dict
            identifier = item[sort_key]
            if type(identifier) is not str or not identifier:
                raise ProjectionError("TOPOLOGY_RECORD_ID", path + "." + sort_key)
            if identifier in seen:
                raise ProjectionError("DUPLICATE_TOPOLOGY_ID", path + "." + sort_key)
            seen.add(identifier)
            record = copy.deepcopy(item)
            if group == "scene_nodes":
                if not _SCENE_ID_RE.fullmatch(record["id"]):
                    raise ProjectionError("TOPOLOGY_SCENE_ID", path + ".id")
                if (
                    type(record["label"]) is not str
                    or not record["label"].isascii()
                    or not record["label"].strip()
                    or len(record["label"]) > _MAX_TEXT_LENGTH
                ):
                    raise ProjectionError("TOPOLOGY_SCENE_LABEL", path + ".label")
                if type(record["knowledge_status"]) is not str or record["knowledge_status"] not in _KNOWLEDGE_STATUSES:
                    raise ProjectionError("TOPOLOGY_KNOWLEDGE_STATUS", path + ".knowledge_status")
            elif group == "links":
                if not _FACT_ID_RE.fullmatch(record["id"]):
                    raise ProjectionError("TOPOLOGY_LINK_ID", path + ".id")
                for field in ("from_scene_id", "to_scene_id"):
                    if type(record[field]) is not str or not _SCENE_ID_RE.fullmatch(record[field]):
                        raise ProjectionError("TOPOLOGY_LINK_SCENE_ID", path + "." + field)
                if type(record["relation"]) is not str or not _TOKEN_RE.fullmatch(record["relation"]):
                    raise ProjectionError("TOPOLOGY_LINK_RELATION", path + ".relation")
            else:
                if type(record["scene_id"]) is not str or not _SCENE_ID_RE.fullmatch(record["scene_id"]):
                    raise ProjectionError("LAYOUT_SCENE_ID", path + ".scene_id")
                if type(record["anchor_id"]) is not str or not _ENTITY_ID_RE.fullmatch(record["anchor_id"]):
                    raise ProjectionError("LAYOUT_ANCHOR_ID", path + ".anchor_id")
                if (
                    type(record["label"]) is not str
                    or len(record["label"]) > _MAX_TEXT_LENGTH
                    or not _TOKEN_RE.fullmatch(record["label"])
                ):
                    raise ProjectionError("LAYOUT_LABEL", path + ".label")
                for field in ("row", "column"):
                    coordinate = record[field]
                    if type(coordinate) is not int or abs(coordinate) > _MAX_LAYOUT_COORDINATE:
                        raise ProjectionError("LAYOUT_COORDINATE", path + "." + field)
            normalized_items.append(record)
        if group == "schematic_layout":
            normalized_items.sort(
                key=lambda record: (
                    record["scene_id"],
                    record["row"],
                    record["column"],
                    record["anchor_id"],
                )
            )
        else:
            normalized_items.sort(key=lambda record: record[sort_key])
        normalized[group] = normalized_items
    return normalized


def _validate_fact_references(
    facts: list[dict[str, Any]], topology: dict[str, Any]
) -> None:
    scene_ids = {node["id"] for node in topology["scene_nodes"]}
    entity_ids = {item["anchor_id"] for item in topology["schematic_layout"]}
    valid_ids = scene_ids | entity_ids
    fact_ids = {fact["id"] for fact in facts}
    for fact in facts:
        path = "$.candidate.facts[" + fact["id"] + "]"
        if fact["scene_id"] not in scene_ids:
            raise ProjectionError("FACT_SCENE_REFERENCE", path + ".scene_id")
        for field in ("subject_id", "object_id"):
            if fact[field] not in valid_ids:
                raise ProjectionError("UNKNOWN_FACT_REFERENCE", path + "." + field)
    for link in topology["links"]:
        if link["from_scene_id"] not in scene_ids or link["to_scene_id"] not in scene_ids:
            raise ProjectionError("TOPOLOGY_LINK_REFERENCE", "$.candidate.topology.links")
        if link["id"] not in fact_ids:
            raise ProjectionError("TOPOLOGY_LINK_FACT_REFERENCE", "$.candidate.topology.links")


def _validate_arrival(
    value: object,
    approvals: object,
    visible_facts: list[dict[str, Any]],
    visible_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if type(value) is not list or len(value) != len(_ARRIVAL_ROLES):
        raise ProjectionError("ARRIVAL_SEGMENTS", "$.candidate.arrival_segments")
    if type(approvals) not in (list, tuple) or len(approvals) != len(_ARRIVAL_ROLES):
        raise ProjectionError("ARRIVAL_APPROVALS", "$.reference.arrival_approvals")
    facts_by_id = {fact["id"]: fact for fact in visible_facts}
    segments: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for index, (segment, approval, expected_role) in enumerate(zip(value, approvals, _ARRIVAL_ROLES)):
        path = "$.candidate.arrival_segments[%d]" % index
        approval_path = "$.reference.arrival_approvals[%d]" % index
        _record(segment, _ARRIVAL_KEYS, path)
        _record(approval, _APPROVAL_KEYS, approval_path)
        assert type(segment) is dict and type(approval) is dict
        if segment["role"] != expected_role or approval["role"] != expected_role:
            raise ProjectionError("ARRIVAL_ROLE_ORDER", path + ".role")
        if segment["id"] != approval["id"]:
            raise ProjectionError("ARRIVAL_SEGMENT_ID", path + ".id")
        text = segment["text"]
        if type(text) is not str or not text.strip() or not text.isascii() or len(text) > 512:
            raise ProjectionError("ARRIVAL_TEXT", path + ".text")
        if type(approval["text_sha256"]) is not str or not _SHA256_RE.fullmatch(approval["text_sha256"]):
            raise ProjectionError("ARRIVAL_APPROVAL_DIGEST", approval_path + ".text_sha256")
        if type(approval["id"]) is not str or not _SEGMENT_ID_RE.fullmatch(approval["id"]):
            raise ProjectionError("ARRIVAL_APPROVAL_ID", approval_path + ".id")
        if _sha256_text(text) != approval["text_sha256"]:
            raise ProjectionError("ARRIVAL_TEXT_BINDING_MISMATCH", path + ".text")
        fact_ids = segment["fact_ids"]
        approved_ids = approval["fact_ids"]
        if (
            type(fact_ids) is not list
            or type(approved_ids) not in (list, tuple)
            or any(type(fact_id) is not str for fact_id in fact_ids)
            or any(type(fact_id) is not str for fact_id in approved_ids)
        ):
            raise ProjectionError("ARRIVAL_FACT_IDS", path + ".fact_ids")
        if fact_ids != list(approved_ids) or not fact_ids or any(fact_id not in visible_ids for fact_id in fact_ids):
            raise ProjectionError("ARRIVAL_FACT_BINDING_MISMATCH", path + ".fact_ids")
        provenance_bindings: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            fact = facts_by_id[fact_id]
            if fact["status"] != "known" or fact["audience"] != "public":
                raise ProjectionError("ARRIVAL_FACT_NOT_PUBLIC_KNOWN", path + ".fact_ids")
            provenance_bindings.append(
                {"fact_id": fact_id, "provenance": copy.deepcopy(fact["provenance"])}
            )
        segments.append({"id": segment["id"], "role": expected_role, "text": text})
        bindings.append(
            {
                "segment_id": segment["id"],
                "role": expected_role,
                "fact_ids": list(fact_ids),
                "provenance": provenance_bindings,
            }
        )
    return segments, bindings


def _build_binding(
    fixture_id: str,
    audience: str,
    facts: list[dict[str, Any]],
    topology: dict[str, Any],
) -> dict[str, Any]:
    provenance = [
        {"fact_id": fact["id"], "provenance": copy.deepcopy(fact["provenance"])}
        for fact in facts
    ]
    fact_digest = _sha256({"facts": facts})
    topology_digest = _sha256(topology)
    provenance_digest = _sha256(provenance)
    return {
        "fixture_id": fixture_id,
        "audience": audience,
        "facts": copy.deepcopy(facts),
        "topology": copy.deepcopy(topology),
        "fact_ids": [fact["id"] for fact in facts],
        "provenance": provenance,
        "fact_set_sha256": fact_digest,
        "topology_sha256": topology_digest,
        "provenance_sha256": provenance_digest,
    }


def _render_condition(
    condition: str,
    facts: list[dict[str, Any]],
    topology: dict[str, Any],
    arrival_segments: list[dict[str, Any]],
) -> tuple[str, str]:
    if condition == "B":
        return _render_prose(facts, topology), "text/plain"
    structured = canonical_json({"facts": facts, "topology": topology})
    if condition == "A":
        return structured, "application/json"
    grid = _render_grid(topology)
    content = structured + "\n\n" + grid
    if condition == "C":
        return content, "text/plain"
    arrival_text = "\n".join(segment["text"] for segment in arrival_segments)
    return (
        content
        + "\n\nBuilder-authored staged arrival (approved fixture fragments):\n"
        + arrival_text,
        "text/plain",
    )


def _render_prose(facts: list[dict[str, Any]], topology: dict[str, Any]) -> str:
    sentences: list[str] = []
    for fact in facts:
        value_text = "null" if fact["value"] is None else '"' + fact["value"] + '"'
        source_refs = ", ".join(fact["provenance"]["source_refs"]) or "none"
        sentences.append(
            "The fact record "
            + fact["id"]
            + " belongs to scene "
            + fact["scene_id"]
            + ". Its subject is "
            + fact["subject_id"]
            + ", its predicate is "
            + fact["predicate"]
            + ", and its object is "
            + fact["object_id"]
            + ". Its fact status is "
            + fact["status"]
            + "; its knowledge status is "
            + fact["knowledge_status"]
            + "; and its audience is "
            + fact["audience"]
            + ". Its exact recorded value text is "
            + value_text
            + ". Its provenance class is "
            + fact["provenance"]["class"]
            + "; its source references are "
            + source_refs
            + "."
        )
    for node in topology["scene_nodes"]:
        sentences.append(
            "Scene node "
            + node["id"]
            + ' is labeled "'
            + node["label"]
            + '" and has knowledge status '
            + node["knowledge_status"]
            + "."
        )
    for link in topology["links"]:
        sentences.append(
            "Topology link record "
            + link["id"]
            + " lists source scene endpoint "
            + link["from_scene_id"]
            + " and destination scene endpoint "
            + link["to_scene_id"]
            + ", with relation label "
            + link["relation"]
            + "."
        )
    for item in topology["schematic_layout"]:
        sentences.append(
            "Schematic position record for anchor "
            + item["anchor_id"]
            + ' in scene '
            + item["scene_id"]
            + ' is labeled "'
            + item["label"]
            + '" at schematic row '
            + str(item["row"])
            + " and schematic column "
            + str(item["column"])
            + "."
        )
    return "\n".join(sentences)


def _render_grid(topology: dict[str, Any]) -> str:
    layout = topology.get("schematic_layout")
    if type(layout) is not list or len(layout) > _MAX_GRID_RECORDS:
        raise ProjectionError("GRID_RECORD_LIMIT", "$.candidate.topology.schematic_layout")

    cells: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for item in layout:
        address = (item["scene_id"], item["row"], item["column"])
        cells.setdefault(address, []).append(item)
    lines = [
        "Sparse schematic addresses only; omitted coordinates carry no implication, and collocated anchors share an address. Rows and columns imply no adjacency, connection, compass, metric, access, doors, traversal, perception, or mechanics."
    ]
    for scene_id, row, column in sorted(cells):
        anchors = sorted(cells[(scene_id, row, column)], key=lambda item: item["anchor_id"])
        rendered_anchors = " and ".join(
            item["label"] + " (anchor " + item["anchor_id"] + ")"
            for item in anchors
        )
        lines.append(
            "Scene "
            + scene_id
            + ", schematic row "
            + str(row)
            + ", column "
            + str(column)
            + ": anchors "
            + rendered_anchors
            + "."
        )

    lines.extend(
        [
            "ASCII cell tables follow; '.' means unspecified only, not blocked, and says nothing about connection. Cell labels use short markers mapped to stable anchor IDs below each scene table.",
        ]
    )
    scene_ids = sorted({scene_id for scene_id, _, _ in cells})
    for scene_id in scene_ids:
        scene_cells = {
            (row, column): sorted(
                anchors, key=lambda item: item["anchor_id"]
            )
            for (cell_scene, row, column), anchors in cells.items()
            if cell_scene == scene_id
        }
        scene_anchors = sorted(
            (item for anchors in scene_cells.values() for item in anchors),
            key=lambda item: item["anchor_id"],
        )
        marker_by_anchor = {
            item["anchor_id"]: "%02d" % (index + 1)
            for index, item in enumerate(scene_anchors)
        }
        columns = sorted({column for _, column in scene_cells})
        rows = sorted({row for row, _ in scene_cells})
        rendered_cells = {
            address: ", ".join(
                item["label"] + "[" + marker_by_anchor[item["anchor_id"]] + "]"
                for item in anchors
            )
            for address, anchors in scene_cells.items()
        }
        header = ["row/col"] + [str(column) for column in columns]
        rendered_rows = [
            ["%+d" % row]
            + [rendered_cells.get((row, column), ".") for column in columns]
            for row in rows
        ]
        widths = [
            max(
                len(header[index]),
                *(len(row[index]) for row in rendered_rows),
            )
            for index in range(len(header))
        ]
        lines.append("ASCII cell table for scene " + scene_id + ":")
        lines.append(
            " | ".join(value.rjust(widths[index]) if index == 0 else value.ljust(widths[index]) for index, value in enumerate(header))
        )
        lines.append("-+-".join("-" * width for width in widths))
        for row in rendered_rows:
            lines.append(
                " | ".join(value.rjust(widths[index]) for index, value in enumerate(row))
            )
        lines.append("Legend for " + scene_id + ":")
        for item in scene_anchors:
            marker = marker_by_anchor[item["anchor_id"]]
            lines.append(
                "  " + marker + " = " + item["anchor_id"] + " (" + item["label"] + ")"
            )
    return "\n".join(lines)


def _build_hashes(
    condition: str,
    audience: str,
    content: str,
    binding: dict[str, Any],
) -> dict[str, str]:
    content_digest = _sha256_text(content)
    artifact_digest = _sha256(
        {
            "condition": condition,
            "audience": audience,
            "content": content,
            "fact_set_sha256": binding["fact_set_sha256"],
            "topology_sha256": binding["topology_sha256"],
            "provenance_sha256": binding["provenance_sha256"],
        }
    )
    return {
        "content_sha256": content_digest,
        "fact_set_sha256": binding["fact_set_sha256"],
        "topology_sha256": binding["topology_sha256"],
        "provenance_sha256": binding["provenance_sha256"],
        "artifact_sha256": artifact_digest,
    }


def _record(value: object, expected_keys: set[str], path: str) -> None:
    if type(value) is not dict:
        raise ProjectionError("OBJECT_TYPE", path)
    if len(value) > 32:
        raise ProjectionError("RECORD_LIMIT", path)
    if any(type(key) is not str for key in value):
        raise ProjectionError("OBJECT_KEY_TYPE", path)
    missing = sorted(expected_keys - set(value))
    if missing:
        raise ProjectionError("MISSING_FIELD", path + "." + missing[0])
    unknown = sorted(set(value) - expected_keys)
    if unknown:
        raise ProjectionError("UNKNOWN_FIELD", path + "." + unknown[0])


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
