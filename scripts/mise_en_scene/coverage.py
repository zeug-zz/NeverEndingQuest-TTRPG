# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Offline positional-coverage checks against separate reference expectations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .contract import Diagnostic, validate_fixture


_ENTITY_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:entity:[a-z0-9][a-z0-9_-]{0,63}$"
)
_EXPECTATION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RELATIONSHIPS = {
    "approach_to_threshold": ("approach", "approach_to_threshold", "threshold"),
    "threshold_to_focal": ("threshold", "threshold_to_focal", "focal_anchor"),
}
_EXTENT_ROLES = ("path", "terrain", "boundary")
_MAX_ITEMS = 256
_MAX_CELLS = 256
_MAX_REASON_LENGTH = 4096


@dataclass(frozen=True)
class CoverageDiagnostic:
    """Stable diagnostic with a machine-readable code, path, and layer."""

    code: str
    path: str
    layer: str
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CoverageReport:
    """Separate schema validity from positional relationship coverage."""

    diagnostics: tuple[CoverageDiagnostic, ...]
    coverage_evaluated: bool

    @property
    def schema_diagnostics(self) -> tuple[CoverageDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.layer == "schema")

    @property
    def coverage_diagnostics(self) -> tuple[CoverageDiagnostic, ...]:
        return tuple(
            item
            for item in self.diagnostics
            if item.layer == "relationship_coverage" and item.code != "NOT_APPLICABLE"
        )

    @property
    def not_applicable(self) -> tuple[CoverageDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.code == "NOT_APPLICABLE")

    @property
    def schema_valid(self) -> bool:
        return not self.schema_diagnostics

    @property
    def coverage_valid(self) -> bool:
        return self.coverage_evaluated and not self.coverage_diagnostics

    @property
    def is_valid(self) -> bool:
        return self.schema_valid and self.coverage_valid


def validate_positional_coverage(
    fixture: object,
    reference_expected_coverage: object,
    approved_topology: object,
    consulted_source_refs: object = (),
) -> CoverageReport:
    """Validate fixture/coverage shapes, then check declared positional facts.

    The reference expectations are separate from the candidate so removing a
    fact or extent cannot remove its obligation. ``schema`` diagnostics cover
    malformed inputs; missing or unknown authored relationships use the
    ``relationship_coverage`` layer. The function is read-only and provider-free.
    """

    diagnostics: list[CoverageDiagnostic] = [
        _contract_diagnostic(item)
        for item in validate_fixture(fixture, approved_topology, consulted_source_refs).diagnostics
    ]
    expected, expected_errors = _parse_expectations(reference_expected_coverage)
    entities, extents, candidate_errors = _parse_candidate(fixture)
    diagnostics.extend(expected_errors)
    diagnostics.extend(candidate_errors)

    if any(item.layer == "schema" for item in diagnostics):
        return CoverageReport(tuple(diagnostics), coverage_evaluated=False)
    if type(fixture) is not dict:
        return CoverageReport(tuple(diagnostics), coverage_evaluated=False)

    _check_relations(expected["relations"], entities, fixture["facts"], diagnostics)
    _check_extents(expected["extents"], entities, extents, diagnostics)
    return CoverageReport(tuple(diagnostics), coverage_evaluated=True)


def _contract_diagnostic(value: Diagnostic) -> CoverageDiagnostic:
    return CoverageDiagnostic(value.code, value.path, "schema")


def _parse_expectations(value: object) -> tuple[dict[str, Any], list[CoverageDiagnostic]]:
    diagnostics: list[CoverageDiagnostic] = []
    normalized: dict[str, Any] = {"relations": {}, "extents": []}
    if type(value) is not dict:
        _add(diagnostics, "EXPECTATIONS_TYPE", "$expected", "schema")
        return normalized, diagnostics

    _shape(value, {"schema_version", "stage_relations", "extents", "usable_spaces"}, "$expected", diagnostics)
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        _add(diagnostics, "EXPECTATIONS_VERSION", "$expected.schema_version", "schema")

    _parse_relations(value.get("stage_relations"), normalized, diagnostics)
    seen_ids: set[str] = set()
    groups = value.get("extents")
    if type(groups) is not dict:
        _add(diagnostics, "EXTENT_EXPECTATIONS_TYPE", "$expected.extents", "schema")
    else:
        _shape(groups, set(_EXTENT_ROLES), "$expected.extents", diagnostics)
        for role in _EXTENT_ROLES:
            path = "$expected.extents." + role
            _parse_extent_group(groups.get(role), role, path, seen_ids, normalized, diagnostics)

    _parse_extent_group(
        value.get("usable_spaces"),
        "usable_space",
        "$expected.usable_spaces",
        seen_ids,
        normalized,
        diagnostics,
    )
    if not any(item["role"] == "usable_space" and item["status"] == "required" for item in normalized["extents"]):
        _add(diagnostics, "NO_REQUIRED_USABLE_SPACE", "$expected.usable_spaces", "relationship_coverage")
    return normalized, diagnostics


def _parse_relations(
    value: object,
    normalized: dict[str, Any],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    path = "$expected.stage_relations"
    if type(value) is not dict:
        _add(diagnostics, "RELATION_EXPECTATIONS_TYPE", path, "schema")
        return
    _shape(value, set(_RELATIONSHIPS), path, diagnostics)
    for name, (from_role, predicate, to_role) in _RELATIONSHIPS.items():
        item_path = path + "." + name
        item = value.get(name)
        if type(item) is not dict:
            _add(diagnostics, "RELATION_EXPECTATION_TYPE", item_path, "schema")
            continue
        status = item.get("status")
        if status == "required":
            _shape(item, {"status", "from_id", "to_id"}, item_path, diagnostics)
            from_id = _entity_id(item.get("from_id"), item_path + ".from_id", diagnostics)
            to_id = _entity_id(item.get("to_id"), item_path + ".to_id", diagnostics)
            if from_id is not None and to_id is not None:
                normalized["relations"][name] = {
                    "status": status,
                    "from_id": from_id,
                    "from_role": from_role,
                    "predicate": predicate,
                    "to_id": to_id,
                    "to_role": to_role,
                }
        elif status == "not_applicable":
            _shape(item, {"status", "reason"}, item_path, diagnostics)
            reason = _reason(item.get("reason"))
            if reason is None:
                _add(diagnostics, "NON_APPLICABLE_REASON", item_path + ".reason", "schema")
            else:
                normalized["relations"][name] = {
                    "status": status,
                    "reason": reason,
                    "predicate": predicate,
                }
        else:
            _add(diagnostics, "RELATION_EXPECTATION_STATUS", item_path + ".status", "schema")


def _parse_extent_group(
    value: object,
    role: str,
    path: str,
    seen_ids: set[str],
    normalized: dict[str, Any],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    if type(value) is not list:
        _add(diagnostics, "EXTENT_EXPECTATIONS_ARRAY", path, "schema")
        return
    if not value:
        _add(diagnostics, "EXTENT_EXPECTATION_REQUIRED", path, "schema")
        return
    if len(value) > _MAX_ITEMS:
        _add(diagnostics, "COLLECTION_LIMIT", path, "schema")
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        parsed = _parse_extent_expectation(item, role, item_path, diagnostics)
        if parsed is None:
            continue
        if parsed["id"] in seen_ids:
            _add(diagnostics, "DUPLICATE_EXPECTATION_ID", item_path + ".id", "schema")
            continue
        seen_ids.add(parsed["id"])
        normalized["extents"].append(parsed)


def _parse_extent_expectation(
    item: object,
    role: str,
    path: str,
    diagnostics: list[CoverageDiagnostic],
) -> dict[str, Any] | None:
    if type(item) is not dict:
        _add(diagnostics, "EXTENT_EXPECTATION_TYPE", path, "schema")
        return None
    status = item.get("status")
    if status == "not_applicable":
        _shape(item, {"id", "status", "reason"}, path, diagnostics)
        expectation_id = _expectation_id(item.get("id"), path + ".id", diagnostics)
        reason = _reason(item.get("reason"))
        if reason is None:
            _add(diagnostics, "NON_APPLICABLE_REASON", path + ".reason", "schema")
        if expectation_id is None or reason is None:
            return None
        return {"id": expectation_id, "role": role, "status": status, "reason": reason}
    if status != "required":
        _add(diagnostics, "EXTENT_EXPECTATION_STATUS", path + ".status", "schema")
        return None

    _shape(item, {"id", "entity_id", "status", "schematic_cells"}, path, diagnostics)
    expectation_id = _expectation_id(item.get("id"), path + ".id", diagnostics)
    entity_id = _entity_id(item.get("entity_id"), path + ".entity_id", diagnostics)
    minimum = 1 if role == "usable_space" else 2
    cells = _cells(item.get("schematic_cells"), path + ".schematic_cells", minimum, diagnostics)
    if expectation_id is None or entity_id is None or cells is None:
        return None
    return {
        "id": expectation_id,
        "entity_id": entity_id,
        "role": role,
        "status": status,
        "schematic_cells": cells,
    }


def _parse_candidate(
    fixture: object,
) -> tuple[dict[str, tuple[str, str, str]], dict[str, dict[str, Any]], list[CoverageDiagnostic]]:
    diagnostics: list[CoverageDiagnostic] = []
    entities: dict[str, tuple[str, str, str]] = {}
    extents: dict[str, dict[str, Any]] = {}
    if type(fixture) is not dict:
        return entities, extents, diagnostics

    for name in ("fixed_anchors", "initial_mobile_occupants"):
        values = fixture.get(name)
        if type(values) is not list:
            continue
        for index, item in enumerate(values[:_MAX_ITEMS]):
            if type(item) is dict and type(item.get("id")) is str and type(item.get("kind")) is str:
                entities[item["id"]] = (
                    item["kind"],
                    "$.%s[%d].kind" % (name, index),
                    name,
                )

    seams = fixture.get("extension_seams")
    values = seams.get("multi_cell_extents") if type(seams) is dict else None
    if type(values) is not list:
        _add(diagnostics, "COVERAGE_EXTENTS_ARRAY", "$.extension_seams.multi_cell_extents", "schema")
        return entities, extents, diagnostics
    path = "$.extension_seams.multi_cell_extents"
    if len(values) > _MAX_ITEMS:
        _add(diagnostics, "COLLECTION_LIMIT", path, "schema")
    for index, item in enumerate(values[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        parsed = _parse_candidate_extent(item, item_path, diagnostics)
        if parsed is None:
            continue
        entity_id = parsed["entity_id"]
        if entity_id in extents:
            _add(diagnostics, "DUPLICATE_EXTENT", item_path + ".entity_id", "schema")
        elif entity_id not in entities:
            _add(diagnostics, "EXTENT_REFERENCE", item_path + ".entity_id", "schema")
        else:
            parsed["path"] = item_path
            extents[entity_id] = parsed
    return entities, extents, diagnostics


def _parse_candidate_extent(
    item: object,
    path: str,
    diagnostics: list[CoverageDiagnostic],
) -> dict[str, Any] | None:
    if type(item) is not dict:
        _add(diagnostics, "COVERAGE_EXTENT_TYPE", path, "schema")
        return None
    _shape(item, {"entity_id", "status", "schematic_cells", "reason"}, path, diagnostics)
    entity_id = _entity_id(item.get("entity_id"), path + ".entity_id", diagnostics)
    status = item.get("status")
    if status not in ("known", "unknown", "not_applicable"):
        _add(diagnostics, "COVERAGE_EXTENT_STATUS", path + ".status", "schema")
        return None
    if status == "known":
        cells = _cells(item.get("schematic_cells"), path + ".schematic_cells", 0, diagnostics)
        reason = None
        if item.get("reason") is not None:
            _add(diagnostics, "UNEXPECTED_EXTENT_REASON", path + ".reason", "schema")
    else:
        cells = None
        reason = _reason(item.get("reason"))
        if item.get("schematic_cells") is not None:
            _add(diagnostics, "UNKNOWN_EXTENT_HAS_CELLS", path + ".schematic_cells", "schema")
        if reason is None:
            _add(diagnostics, "COVERAGE_EXTENT_REASON", path + ".reason", "schema")
    if entity_id is None or (status == "known" and cells is None):
        return None
    return {"entity_id": entity_id, "status": status, "schematic_cells": cells, "reason": reason}


def _check_relations(
    expected: dict[str, Any],
    entities: dict[str, tuple[str, str, str]],
    facts: list[object],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    for name, (from_role, predicate, to_role) in _RELATIONSHIPS.items():
        item = expected[name]
        path = "$expected.stage_relations." + name
        if item["status"] == "not_applicable":
            _add(diagnostics, "NOT_APPLICABLE", path, "relationship_coverage", stage="reference_expectation", relationship=name, reason=item["reason"])
            continue

        from_id, to_id = item["from_id"], item["to_id"]
        role_ok = _check_role(name, "from_id", from_id, from_role, entities, diagnostics)
        role_ok = _check_role(name, "to_id", to_id, to_role, entities, diagnostics) and role_ok
        matches = [
            (index, fact)
            for index, fact in enumerate(facts)
            if type(fact) is dict and fact.get("predicate") == predicate
        ]
        exact = [
            (index, fact)
            for index, fact in matches
            if fact.get("subject_id") == from_id and fact.get("object_id") == to_id
        ]
        details = {
            "stage": "candidate_authoring",
            "relationship": name,
            "from_id": from_id,
            "from_role": from_role,
            "predicate": predicate,
            "to_id": to_id,
            "to_role": to_role,
        }
        if not exact:
            if matches:
                for index, fact in matches:
                    _add(diagnostics, "RELATION_REFERENCE_MISMATCH", "$.facts[%d]" % index, "relationship_coverage", **details, fact_id=_text(fact.get("id")), observed_from_id=_text(fact.get("subject_id")), observed_to_id=_text(fact.get("object_id")))
            else:
                _add(diagnostics, "MISSING_RELATION", "$.facts", "relationship_coverage", **details)
        elif len(exact) > 1:
            _add(diagnostics, "AMBIGUOUS_RELATION", "$.facts", "relationship_coverage", **details, fact_ids=_json([fact.get("id") for _index, fact in exact]))
        elif role_ok and exact[0][1].get("status") == "unknown":
            index, fact = exact[0]
            _add(diagnostics, "RELATION_UNKNOWN", "$.facts[%d]" % index, "relationship_coverage", **details, fact_id=_text(fact.get("id")))


def _check_role(
    relationship: str,
    endpoint: str,
    entity_id: str,
    expected_role: str,
    entities: dict[str, tuple[str, str, str]],
    diagnostics: list[CoverageDiagnostic],
) -> bool:
    found = entities.get(entity_id)
    if found is None:
        _add(diagnostics, "UNRESOLVED_RELATION_ENDPOINT", "$.fixed_anchors", "relationship_coverage", stage="candidate_authoring", relationship=relationship, endpoint=endpoint, expected_id=entity_id, expected_role=expected_role)
        return False
    if found[0] != expected_role or found[2] != "fixed_anchors":
        _add(diagnostics, "ROLE_MISMATCH", found[1], "relationship_coverage", stage="candidate_authoring", relationship=relationship, expected_id=entity_id, expected_role=expected_role, observed_role=found[0], observed_collection=found[2])
        return False
    return True


def _check_extents(
    expected: list[dict[str, Any]],
    entities: dict[str, tuple[str, str, str]],
    actual_extents: dict[str, dict[str, Any]],
    diagnostics: list[CoverageDiagnostic],
) -> None:
    for item in expected:
        role, expectation_id = item["role"], item["id"]
        path = "$expected.%s[%s]" % ("usable_spaces" if role == "usable_space" else "extents." + role, expectation_id)
        if item["status"] == "not_applicable":
            _add(diagnostics, "NOT_APPLICABLE", path, "relationship_coverage", stage="reference_expectation", expectation_id=expectation_id, role=role, reason=item["reason"])
            continue

        entity_id = item["entity_id"]
        entity = entities.get(entity_id)
        if entity is None:
            _add(diagnostics, "UNRESOLVED_EXTENT_ID", "$.fixed_anchors", "relationship_coverage", stage="candidate_authoring", expectation_id=expectation_id, entity_id=entity_id, role=role)
        elif entity[0] != role or entity[2] != "fixed_anchors":
            _add(diagnostics, "ROLE_MISMATCH", entity[1], "relationship_coverage", stage="candidate_authoring", expectation_id=expectation_id, entity_id=entity_id, expected_role=role, observed_role=entity[0], observed_collection=entity[2])

        actual = actual_extents.get(entity_id)
        if actual is None:
            code = "MISSING_USABLE_SPACE" if role == "usable_space" else "MISSING_EXTENT"
            _add(diagnostics, code, "$.extension_seams.multi_cell_extents", "relationship_coverage", stage="candidate_authoring", expectation_id=expectation_id, entity_id=entity_id, role=role, expected_cells=_cells_json(item["schematic_cells"]))
            continue
        if actual["status"] != "known":
            code = "NOT_APPLICABLE_REQUIRED" if actual["status"] == "not_applicable" else ("USABLE_SPACE_UNKNOWN" if role == "usable_space" else "EXTENT_UNKNOWN")
            _add(diagnostics, code, actual["path"] + (".status" if actual["status"] == "not_applicable" else ".schematic_cells"), "relationship_coverage", stage="candidate_authoring", expectation_id=expectation_id, entity_id=entity_id, role=role, reason=actual["reason"])
            continue

        wanted, observed = set(item["schematic_cells"]), set(actual["schematic_cells"])
        details = {
            "stage": "candidate_authoring",
            "expectation_id": expectation_id,
            "entity_id": entity_id,
            "role": role,
            "expected_cells": _cells_json(item["schematic_cells"]),
            "observed_cells": _cells_json(actual["schematic_cells"]),
        }
        if wanted - observed:
            _add(diagnostics, "EXTENT_TRUNCATED", actual["path"] + ".schematic_cells", "relationship_coverage", **details, missing_cells=_cells_json(sorted(wanted - observed)))
        if observed - wanted:
            _add(diagnostics, "EXTENT_EXTRA_CELLS", actual["path"] + ".schematic_cells", "relationship_coverage", **details, extra_cells=_cells_json(sorted(observed - wanted)))


def _shape(
    value: dict[str, Any],
    expected: set[str],
    path: str,
    diagnostics: list[CoverageDiagnostic],
) -> None:
    if len(value) > 32:
        _add(diagnostics, "RECORD_LIMIT", path, "schema")
        return
    for key in sorted(expected - set(value)):
        _add(diagnostics, "MISSING_FIELD", path + "." + key, "schema")
    for key in value:
        if type(key) is not str:
            _add(diagnostics, "OBJECT_KEY_TYPE", path, "schema")
        elif key not in expected:
            _add(diagnostics, "UNKNOWN_FIELD", path + "." + key, "schema")


def _cells(
    value: object,
    path: str,
    minimum: int,
    diagnostics: list[CoverageDiagnostic],
) -> tuple[tuple[int, int], ...] | None:
    if type(value) is not list:
        _add(diagnostics, "CELL_LIST_TYPE", path, "schema")
        return None
    if len(value) > _MAX_CELLS:
        _add(diagnostics, "CELL_LIMIT", path, "schema")
        return None
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    valid = True
    for index, cell in enumerate(value):
        cell_path = "%s[%d]" % (path, index)
        if type(cell) is not list or len(cell) != 2:
            _add(diagnostics, "CELL_SHAPE", cell_path, "schema")
            valid = False
            continue
        if any(type(part) is not int for part in cell):
            _add(diagnostics, "CELL_COORDINATE", cell_path, "schema")
            valid = False
            continue
        coordinate = (cell[0], cell[1])
        if coordinate in seen:
            _add(diagnostics, "DUPLICATE_CELL", cell_path, "schema")
            valid = False
            continue
        seen.add(coordinate)
        cells.append(coordinate)
    if len(value) < minimum:
        _add(diagnostics, "CELL_COUNT", path, "schema")
        valid = False
    return tuple(cells) if valid else None


def _entity_id(value: object, path: str, diagnostics: list[CoverageDiagnostic]) -> str | None:
    if type(value) is not str or len(value) > 160 or _ENTITY_ID_RE.fullmatch(value) is None:
        _add(diagnostics, "ENTITY_ID", path, "schema")
        return None
    return value


def _expectation_id(value: object, path: str, diagnostics: list[CoverageDiagnostic]) -> str | None:
    if type(value) is not str or len(value) > 64 or _EXPECTATION_ID_RE.fullmatch(value) is None:
        _add(diagnostics, "EXPECTATION_ID", path, "schema")
        return None
    return value


def _reason(value: object) -> str | None:
    if type(value) is not str or not value.strip() or len(value) > _MAX_REASON_LENGTH:
        return None
    return value.strip()


def _add(
    diagnostics: list[CoverageDiagnostic],
    code: str,
    path: str,
    layer: str,
    **details: str,
) -> None:
    diagnostics.append(CoverageDiagnostic(code, path, layer, tuple(sorted(details.items()))))


def _text(value: object) -> str:
    return value if type(value) is str else _json(value)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _cells_json(cells: object) -> str:
    return _json([[cell[0], cell[1]] for cell in cells])
