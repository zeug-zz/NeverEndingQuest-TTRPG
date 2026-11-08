# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free helpers for hand-authored, reviewable holdout fixture specs.

The candidate and reference are generated separately from one reviewed spec.
Their independence is between the objects checked at projection time, not
between their authors or source of truth.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
from typing import Any

from . import projections


_AUDIENCES = ("public", "gm_narrator")
_TOPOLOGY_GROUPS = ("scene_nodes", "links", "schematic_layout")
_SPEC_KEYS = {
    "schema_version",
    "fixture_id",
    "facts",
    "topology",
    "topology_scope",
    "arrival_segments",
}
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
    "authorship",
    "provenance",
}
_UNKNOWN_FACT_KEYS = _FACT_KEYS - {"authorship"}
_PROVENANCE_KEYS = {"class", "source_refs"}
_TOPOLOGY_ID_FIELDS = {
    "scene_nodes": "id",
    "links": "id",
    "schematic_layout": "anchor_id",
}
_SOURCE_REF_RE = re.compile(r"^source:[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_MODULE_SOURCE_REF_RE = re.compile(r"^source:modules/[^/]+/.+\.json$")


class HoldoutFixtureError(ValueError):
    """Stable fail-closed error for malformed reviewed fixture specifications."""

    def __init__(self, code: str, path: str = "$", details: object | None = None) -> None:
        self.code = code
        self.path = path
        self.details = details
        super().__init__(code + " at " + path)


def make_projection_pair(
    spec: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a projection candidate and independent reference from one spec.

    A source-extracted fact must cite a repo-relative module JSON file, such as
    ``source:modules/The_Ancients_Lab/areas/BA001_BU.json``. Known fact specs
    explicitly set authorship to ``source`` or ``builder`` and the value must
    agree with the provenance class. Unknown facts use class ``unknown``, have
    no source refs, and omit authorship because no claim is being authored.

    The returned reference is derived from the reviewed spec itself: fact
    digests, audience allowlists, topology views, and arrival approvals are
    independently constructed rather than copied from the candidate. This
    provides object-level checking, not independent authorship.
    """

    if type(spec) is not dict:
        raise HoldoutFixtureError("SPEC_OBJECT", "$.spec")
    data = copy.deepcopy(spec)
    _require_record(data, _SPEC_KEYS, "$.spec")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise HoldoutFixtureError("SCHEMA_VERSION", "$.spec.schema_version")

    fixture_id = data["fixture_id"]
    if type(fixture_id) is not str:
        raise HoldoutFixtureError("FIXTURE_ID", "$.spec.fixture_id")

    facts_spec = data["facts"]
    if type(facts_spec) is not list or not facts_spec or len(facts_spec) > 64:
        raise HoldoutFixtureError("FACTS_TYPE", "$.spec.facts")
    candidate_facts = [
        _build_fact(fact_spec, "$.spec.facts[%d]" % index)
        for index, fact_spec in enumerate(facts_spec)
    ]
    reference_facts = [
        _build_fact(fact_spec, "$.spec.facts[%d]" % index)
        for index, fact_spec in enumerate(facts_spec)
    ]

    topology_spec = data["topology"]
    candidate_topology = _build_topology(topology_spec, "$.spec.topology")
    topology_scope = _build_topology_scope(
        data["topology_scope"], candidate_topology
    )
    arrival_segments = _build_arrival_segments(data["arrival_segments"])

    candidate = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "facts": candidate_facts,
        "topology": candidate_topology,
        "arrival_segments": arrival_segments,
    }

    # Build each reference field from the spec-derived values, not from candidate.
    reference_topology_source = _build_topology(
        topology_spec, "$.spec.topology"
    )
    topology_by_audience = {
        audience: _select_topology(
            reference_topology_source,
            topology_scope[audience],
            "$.spec.topology_scope." + audience,
        )
        for audience in _AUDIENCES
    }
    public_fact_ids = [
        fact["id"] for fact in reference_facts if fact["audience"] == "public"
    ]
    all_fact_ids = [fact["id"] for fact in reference_facts]
    reference = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "fact_digests": {
            fact["id"]: _hash_json(fact) for fact in reference_facts
        },
        "scope": {
            "audience_fact_ids": {
                "public": public_fact_ids,
                "gm_narrator": all_fact_ids,
            },
            "topology_record_ids": topology_scope,
        },
        "topology_by_audience": topology_by_audience,
        "arrival_approvals": _build_arrival_approvals(data["arrival_segments"]),
    }

    try:
        projections.build_matched_projections(
            candidate,
            reference,
            audience="public",
        )
    except projections.ProjectionError as exc:
        raise HoldoutFixtureError(
            "PROJECTION_INPUT_INVALID",
            exc.path,
            {"code": exc.code, "path": exc.path},
        ) from exc
    return candidate, reference


def _build_fact(value: object, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise HoldoutFixtureError("FACT_OBJECT", path)
    provenance = value.get("provenance")
    if type(provenance) is not dict:
        raise HoldoutFixtureError("PROVENANCE_OBJECT", path + ".provenance")
    provenance_class = provenance.get("class")
    status = value.get("status")
    expected_keys = (
        _UNKNOWN_FACT_KEYS if status == "unknown" else _FACT_KEYS
    )
    _require_record(value, expected_keys, path)
    _require_record(provenance, _PROVENANCE_KEYS, path + ".provenance")

    source_refs = provenance["source_refs"]
    if type(source_refs) is not list or len(source_refs) > 16:
        raise HoldoutFixtureError(
            "SOURCE_REFS_TYPE", path + ".provenance.source_refs"
        )
    for index, source_ref in enumerate(source_refs):
        ref_path = path + ".provenance.source_refs[%d]" % index
        if type(source_ref) is not str or not _SOURCE_REF_RE.fullmatch(source_ref):
            raise HoldoutFixtureError("SOURCE_REF", ref_path)
        if ".." in source_ref.split("/"):
            raise HoldoutFixtureError("SOURCE_REF_PATH", ref_path)
    if len(source_refs) != len(set(source_refs)):
        raise HoldoutFixtureError(
            "DUPLICATE_SOURCE_REF", path + ".provenance.source_refs"
        )

    if status == "unknown":
        if provenance_class != "unknown" or source_refs:
            raise HoldoutFixtureError(
                "UNKNOWN_PROVENANCE", path + ".provenance"
            )
        if value["value"] is not None:
            raise HoldoutFixtureError("UNKNOWN_FACT_HAS_VALUE", path + ".value")
    elif status == "known":
        authorship = value["authorship"]
        if type(authorship) is not str or authorship not in ("source", "builder"):
            raise HoldoutFixtureError("AUTHORSHIP", path + ".authorship")
        expected_class = (
            "source_extracted" if authorship == "source" else "builder_authored"
        )
        if provenance_class != expected_class:
            raise HoldoutFixtureError(
                "AUTHORSHIP_PROVENANCE_MISMATCH", path + ".provenance.class"
            )
        if provenance_class == "source_extracted":
            if not source_refs:
                raise HoldoutFixtureError(
                    "MISSING_SOURCE_REF", path + ".provenance.source_refs"
                )
            for ref in source_refs:
                _validate_module_source_ref(
                    ref, path + ".provenance.source_refs"
                )
        elif provenance_class != "builder_authored":
            raise HoldoutFixtureError(
                "KNOWN_PROVENANCE", path + ".provenance.class"
            )
    else:
        raise HoldoutFixtureError("FACT_STATUS", path + ".status")

    return {
        key: copy.deepcopy(value[key])
        for key in (
            "id",
            "scene_id",
            "subject_id",
            "predicate",
            "object_id",
            "status",
            "knowledge_status",
            "audience",
            "value",
        )
    } | {
        "provenance": {
            "class": provenance_class,
            "source_refs": copy.deepcopy(source_refs),
        }
    }


def _build_topology(value: object, path: str) -> dict[str, Any]:
    _require_record(value, set(_TOPOLOGY_GROUPS), path)
    assert type(value) is dict
    topology: dict[str, Any] = {}
    for group in _TOPOLOGY_GROUPS:
        records = value[group]
        if type(records) is not list or len(records) > 64:
            raise HoldoutFixtureError("TOPOLOGY_GROUP_TYPE", path + "." + group)
        topology[group] = copy.deepcopy(records)
    return topology


def _build_topology_scope(
    value: object, topology: dict[str, Any]
) -> dict[str, dict[str, list[str]]]:
    _require_record(value, set(_AUDIENCES), "$.spec.topology_scope")
    assert type(value) is dict
    all_ids: dict[str, set[str]] = {}
    for group in _TOPOLOGY_GROUPS:
        id_field = _TOPOLOGY_ID_FIELDS[group]
        records = topology[group]
        ids = [
            record.get(id_field) if type(record) is dict else None
            for record in records
        ]
        if any(type(record_id) is not str or not record_id for record_id in ids):
            raise HoldoutFixtureError(
                "TOPOLOGY_RECORD_ID", "$.spec.topology." + group
            )
        if len(ids) != len(set(ids)):
            raise HoldoutFixtureError(
                "DUPLICATE_TOPOLOGY_ID", "$.spec.topology." + group
            )
        all_ids[group] = set(ids)

    result: dict[str, dict[str, list[str]]] = {}
    for audience in _AUDIENCES:
        audience_path = "$.spec.topology_scope." + audience
        groups = _require_record(
            value[audience], set(_TOPOLOGY_GROUPS), audience_path
        )
        result[audience] = {}
        for group in _TOPOLOGY_GROUPS:
            path = audience_path + "." + group
            ids = groups[group]
            if type(ids) is not list or len(ids) > 64:
                raise HoldoutFixtureError("SCOPED_TOPOLOGY_IDS", path)
            if any(type(record_id) is not str for record_id in ids):
                raise HoldoutFixtureError("SCOPED_TOPOLOGY_ID", path)
            if len(ids) != len(set(ids)):
                raise HoldoutFixtureError("DUPLICATE_SCOPED_TOPOLOGY_ID", path)
            if not set(ids) <= all_ids[group]:
                raise HoldoutFixtureError("SCOPED_TOPOLOGY_ID_UNKNOWN", path)
            result[audience][group] = list(ids)

    for group in _TOPOLOGY_GROUPS:
        if set(result["gm_narrator"][group]) != all_ids[group]:
            raise HoldoutFixtureError(
                "GM_TOPOLOGY_SCOPE_INCOMPLETE",
                "$.spec.topology_scope.gm_narrator." + group,
            )
        if not set(result["public"][group]) <= set(result["gm_narrator"][group]):
            raise HoldoutFixtureError(
                "PUBLIC_TOPOLOGY_SCOPE_INVALID",
                "$.spec.topology_scope.public." + group,
            )
    return result


def _select_topology(
    topology: dict[str, Any],
    allowed_ids: dict[str, list[str]],
    path: str,
) -> dict[str, Any]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for group in _TOPOLOGY_GROUPS:
        id_field = _TOPOLOGY_ID_FIELDS[group]
        records = topology[group]
        records_by_id = {
            record[id_field]: record
            for record in records
            if type(record) is dict and id_field in record
        }
        try:
            selected[group] = [
                copy.deepcopy(records_by_id[record_id])
                for record_id in allowed_ids[group]
            ]
        except KeyError as exc:
            raise HoldoutFixtureError(
                "SCOPED_TOPOLOGY_ID_UNKNOWN", path + "." + group
            ) from exc
    return selected


def _build_arrival_segments(value: object) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) != 3:
        raise HoldoutFixtureError("ARRIVAL_SEGMENTS", "$.spec.arrival_segments")
    expected_keys = {"id", "role", "text", "fact_ids"}
    return [
        copy.deepcopy(
            _require_record(
                item,
                expected_keys,
                "$.spec.arrival_segments[%d]" % index,
            )
        )
        for index, item in enumerate(value)
    ]


def _build_arrival_approvals(value: object) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) != 3:
        raise HoldoutFixtureError("ARRIVAL_SEGMENTS", "$.spec.arrival_segments")
    approvals: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        path = "$.spec.arrival_segments[%d]" % index
        segment = _require_record(item, {"id", "role", "text", "fact_ids"}, path)
        text = segment["text"]
        if type(text) is not str:
            raise HoldoutFixtureError("ARRIVAL_TEXT", path + ".text")
        if not text.isascii():
            raise HoldoutFixtureError("ARRIVAL_TEXT", path + ".text")
        approvals.append(
            {
                "id": copy.deepcopy(segment["id"]),
                "role": copy.deepcopy(segment["role"]),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fact_ids": copy.deepcopy(segment["fact_ids"]),
            }
        )
    return approvals


def _hash_json(value: object) -> str:
    try:
        canonical = projections.canonical_json(value)
    except projections.ProjectionError as exc:
        raise HoldoutFixtureError("CANONICAL_JSON_VALUE", exc.path) from exc
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _validate_module_source_ref(source_ref: str, path: str) -> None:
    if not _MODULE_SOURCE_REF_RE.fullmatch(source_ref):
        raise HoldoutFixtureError("MODULE_SOURCE_REF_REQUIRED", path)
    relative_path = source_ref.removeprefix("source:")
    if ".." in relative_path.split("/"):
        raise HoldoutFixtureError("SOURCE_REF_PATH", path)

    repository_root = Path(__file__).resolve().parents[2]
    try:
        resolved_path = (repository_root / relative_path).resolve()
        resolved_path.relative_to(repository_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HoldoutFixtureError("SOURCE_REF_PATH", path) from exc
    if not resolved_path.is_file():
        raise HoldoutFixtureError("MODULE_SOURCE_FILE_MISSING", path)


def _require_record(
    value: object, expected_keys: set[str], path: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise HoldoutFixtureError("OBJECT_REQUIRED", path)
    if any(type(key) is not str for key in value):
        raise HoldoutFixtureError("OBJECT_KEY_TYPE", path)
    missing = sorted(expected_keys - set(value))
    if missing:
        raise HoldoutFixtureError("MISSING_FIELD", path + "." + missing[0])
    extra = sorted(set(value) - expected_keys)
    if extra:
        raise HoldoutFixtureError("UNKNOWN_FIELD", path + "." + extra[0])
    return value
