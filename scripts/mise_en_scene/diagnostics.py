# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Stable offline diagnostics for supplied scene-fact lineage and renders."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


_FACT_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:fact:[a-z0-9][a-z0-9_-]{0,63}$"
)
_RELATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVENANCE_CLASSES = {"source_extracted", "builder_authored", "unknown"}
_CONDITIONS = ("A", "B", "C", "D")
_MAX_ITEMS = 64
_MAX_TEXT_LENGTH = 4096
_MAX_RENDER_LENGTH = 262144


@dataclass(frozen=True)
class StableDiagnostic:
    """Normalized deterministic diagnostic shared by offline validators."""

    code: str
    layer: str
    relation: str
    path: str
    severity: str = "error"


@dataclass(frozen=True)
class LineageReport:
    """Immutable source-to-render result; informational unknowns are not failures."""

    diagnostics: tuple[StableDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    @property
    def unknowns(self) -> tuple[StableDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "info")


def normalize_diagnostics(
    values: object,
    *,
    default_layer: str,
    relation: str = "",
) -> tuple[StableDiagnostic, ...]:
    """Adapt existing fixture diagnostics/exceptions to a stable common shape."""

    if type(values) not in (list, tuple):
        return (
            StableDiagnostic(
                "DIAGNOSTICS_TYPE", "schema", "", "$diagnostics", "error"
            ),
        )
    if len(values) > _MAX_ITEMS * 8:
        return (
            StableDiagnostic(
                "DIAGNOSTIC_LIMIT", "schema", "", "$diagnostics", "error"
            ),
        )

    normalized: list[StableDiagnostic] = []
    for index, value in enumerate(values):
        if type(value) is StableDiagnostic:
            normalized.append(value)
            continue
        code = getattr(value, "code", None)
        path = getattr(value, "path", None)
        if (
            type(code) is not str
            or not code
            or len(code) > 128
            or type(path) is not str
            or not path
            or len(path) > 4096
        ):
            normalized.append(
                StableDiagnostic(
                    "DIAGNOSTIC_SHAPE",
                    "schema",
                    "",
                    "$diagnostics[%d]" % index,
                    "error",
                )
            )
            continue

        item_layer = getattr(value, "layer", None)
        if type(item_layer) is not str or not item_layer:
            item_layer = default_layer
        item_relation = relation
        details = getattr(value, "details", ())
        if not item_relation and type(details) in (dict, tuple, list):
            try:
                detail_map = dict(details)
            except (TypeError, ValueError):
                detail_map = {}
            candidate_relation = detail_map.get(
                "relationship", detail_map.get("relation", "")
            )
            if type(candidate_relation) is str:
                item_relation = candidate_relation
        severity = getattr(value, "severity", None)
        if severity not in ("error", "warning", "info"):
            severity = "info" if code in ("NOT_APPLICABLE", "SOURCE_ABSENCE_UNKNOWN") else "error"
        normalized.append(
            StableDiagnostic(code, item_layer, item_relation, path, severity)
        )
    return tuple(sorted(normalized, key=_diagnostic_key))


def diagnose_guarded_content(
    rendered_content: object, protected_values: object
) -> tuple[StableDiagnostic, ...]:
    """Find exact protected markers in one bounded public-render text value.

    This is a fixture-bound leakage check, not a natural-language classifier.
    The protected values must come from the independent GM/reference fixture.
    """

    if (
        type(rendered_content) is not str
        or len(rendered_content) > _MAX_RENDER_LENGTH
        or not rendered_content.isascii()
    ):
        return (
            StableDiagnostic(
                "PROJECTION_CONTENT_INVALID",
                "schema",
                "",
                "$.projection.content",
            ),
        )
    if (
        type(protected_values) not in (list, tuple)
        or not protected_values
        or len(protected_values) > 32
        or any(
            type(value) is not str
            or not value
            or len(value) > _MAX_TEXT_LENGTH
            for value in protected_values
        )
    ):
        return (
            StableDiagnostic(
                "PROTECTED_VALUES_INVALID",
                "schema",
                "",
                "$.protected_values",
            ),
        )
    diagnostics = [
        StableDiagnostic(
            "GUARDED_CONTENT_LEAK",
            "projection",
            "guarded_knowledge",
            "$.projection.content",
        )
        for marker in protected_values
        if marker in rendered_content
    ]
    return tuple(sorted(diagnostics, key=_diagnostic_key))


def trace_fact_lineage(
    expectations: object,
    source_facts: object,
    extraction_facts: object,
    authoring_facts: object,
    projection_outputs: object,
    approved_content_hashes: object,
) -> LineageReport:
    """Trace independently expected facts through supplied offline stages.

    Expectations are keyed by qualified fact ID plus relation and state source
    support explicitly. Supported source facts must survive extraction,
    authoring, and every A/B/C/D render. A Builder-authored fact may originate
    after extraction but must be marked Builder-authored. An absent source fact
    with unknown authorship emits an informational unknown and fails only if a
    later stage promotes it to known.

    Projection facts are read from each actual output's ``binding.facts``. Their
    ID-list metadata is not treated as evidence. Each actual rendered content
    string must also match a separately supplied approved SHA-256 per condition;
    the output's self-reported hash alone is not trusted.
    """

    diagnostics: list[StableDiagnostic] = []
    expected = _parse_expectations(expectations, diagnostics)
    source = _parse_stage_facts(source_facts, "source", diagnostics)
    extracted = _parse_stage_facts(extraction_facts, "extraction", diagnostics)
    authored = _parse_stage_facts(authoring_facts, "authoring", diagnostics)
    projections = _parse_projection_outputs(
        projection_outputs, approved_content_hashes, diagnostics
    )
    if any(item.layer == "schema" for item in diagnostics):
        return LineageReport(tuple(sorted(diagnostics, key=_diagnostic_key)))

    for item in expected:
        fact_id = item["fact_id"]
        relation = item["relation"]
        source_status = item["source_status"]
        origin_class = item["origin_class"]
        if source_status == "absent" and origin_class == "unknown":
            diagnostics.append(
                StableDiagnostic(
                    "SOURCE_ABSENCE_UNKNOWN",
                    "source",
                    relation,
                    _fact_path("source", fact_id),
                    "info",
                )
            )
            _check_unknown_fact(source, "source", fact_id, relation, diagnostics)
            _check_unknown_fact(extracted, "extraction", fact_id, relation, diagnostics)
            _check_unknown_fact(authored, "authoring", fact_id, relation, diagnostics)
            for condition in _CONDITIONS:
                _check_unknown_fact(
                    projections[condition],
                    "projection",
                    fact_id,
                    relation,
                    diagnostics,
                    condition=condition,
                )
            continue

        if origin_class == "builder_authored":
            for stage, records in (("source", source), ("extraction", extracted)):
                record = records.get(fact_id)
                if record is not None:
                    diagnostics.append(
                        StableDiagnostic(
                            "BUILDER_FACT_PREAUTHORED",
                            stage,
                            relation,
                            record["path"],
                        )
                    )
            authored_fact = authored.get(fact_id)
            if authored_fact is None:
                diagnostics.append(
                    StableDiagnostic(
                        "AUTHORING_FACT_MISSING",
                        "authoring",
                        relation,
                        _fact_path("authoring", fact_id),
                    )
                )
                continue
            if authored_fact["predicate"] != relation:
                diagnostics.append(
                    _relation_mismatch("authoring", relation, authored_fact)
                )
                continue
            if (
                authored_fact["status"] != "known"
                or authored_fact["provenance"]["class"] != "builder_authored"
            ):
                diagnostics.append(
                    StableDiagnostic(
                        "BUILDER_AUTHORING_PROVENANCE",
                        "authoring",
                        relation,
                        authored_fact["path"] + ".provenance",
                    )
                )
                continue
            _check_projection_fact(
                authored_fact, projections, fact_id, relation, diagnostics
            )
            continue

        source_fact = source.get(fact_id)
        if source_fact is None:
            diagnostics.append(
                StableDiagnostic(
                    "SOURCE_FACT_MISSING",
                    "source",
                    relation,
                    _fact_path("source", fact_id),
                )
            )
            continue
        if source_fact["predicate"] != relation:
            diagnostics.append(_relation_mismatch("source", relation, source_fact))
            continue
        if (
            source_fact["status"] != "known"
            or source_fact["provenance"]["class"] != "source_extracted"
            or not source_fact["provenance"]["source_refs"]
        ):
            diagnostics.append(
                StableDiagnostic(
                    "SOURCE_FACT_INVALID",
                    "source",
                    relation,
                    source_fact["path"],
                )
            )
            continue

        extracted_fact = extracted.get(fact_id)
        if extracted_fact is None:
            diagnostics.append(
                StableDiagnostic(
                    "EXTRACTION_FACT_MISSING",
                    "extraction",
                    relation,
                    _fact_path("extraction", fact_id),
                )
            )
            continue
        if not _matches_fact(extracted_fact, source_fact, relation):
            diagnostics.append(
                _relation_mismatch("extraction", relation, extracted_fact)
                if extracted_fact["predicate"] != relation
                else _content_mismatch(
                    "extraction", relation, extracted_fact, expected=source_fact
                )
            )
            continue

        authored_fact = authored.get(fact_id)
        if authored_fact is None:
            diagnostics.append(
                StableDiagnostic(
                    "AUTHORING_FACT_MISSING",
                    "authoring",
                    relation,
                    _fact_path("authoring", fact_id),
                )
            )
            continue
        if not _matches_fact(authored_fact, source_fact, relation):
            diagnostics.append(
                _relation_mismatch("authoring", relation, authored_fact)
                if authored_fact["predicate"] != relation
                else _content_mismatch(
                    "authoring", relation, authored_fact, expected=source_fact
                )
            )
            continue
        _check_projection_fact(
            authored_fact, projections, fact_id, relation, diagnostics
        )

    return LineageReport(tuple(sorted(diagnostics, key=_diagnostic_key)))


def _parse_expectations(
    value: object, diagnostics: list[StableDiagnostic]
) -> list[dict[str, str]]:
    path = "$.expectations"
    if type(value) not in (list, tuple):
        diagnostics.append(StableDiagnostic("EXPECTATIONS_TYPE", "schema", "", path))
        return []
    if len(value) > _MAX_ITEMS:
        diagnostics.append(StableDiagnostic("COLLECTION_LIMIT", "schema", "", path))
    parsed: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict or set(item) != {
            "fact_id",
            "relation",
            "source_status",
            "origin_class",
        }:
            diagnostics.append(
                StableDiagnostic("EXPECTATION_SHAPE", "schema", "", item_path)
            )
            continue
        fact_id = item["fact_id"]
        relation = item["relation"]
        source_status = item["source_status"]
        origin_class = item["origin_class"]
        if type(fact_id) is not str or not _FACT_ID_RE.fullmatch(fact_id):
            diagnostics.append(
                StableDiagnostic(
                    "EXPECTATION_FACT_ID", "schema", "", item_path + ".fact_id"
                )
            )
        if type(relation) is not str or not _RELATION_RE.fullmatch(relation):
            diagnostics.append(
                StableDiagnostic(
                    "EXPECTATION_RELATION", "schema", "", item_path + ".relation"
                )
            )
        if source_status not in ("supported", "absent"):
            diagnostics.append(
                StableDiagnostic(
                    "EXPECTATION_SOURCE_STATUS",
                    "schema",
                    "",
                    item_path + ".source_status",
                )
            )
        if type(origin_class) is not str or origin_class not in _PROVENANCE_CLASSES:
            diagnostics.append(
                StableDiagnostic(
                    "EXPECTATION_ORIGIN_CLASS",
                    "schema",
                    "",
                    item_path + ".origin_class",
                )
            )
        if (
            source_status == "supported"
            and origin_class != "source_extracted"
        ) or (
            source_status == "absent"
            and origin_class == "source_extracted"
        ):
            diagnostics.append(
                StableDiagnostic(
                    "EXPECTATION_ORIGIN_CONFLICT",
                    "schema",
                    "",
                    item_path,
                )
            )
        if type(fact_id) is str and _FACT_ID_RE.fullmatch(fact_id):
            if fact_id in seen_ids:
                diagnostics.append(
                    StableDiagnostic(
                        "DUPLICATE_EXPECTATION_ID",
                        "schema",
                        relation if type(relation) is str else "",
                        item_path + ".fact_id",
                    )
                )
            seen_ids.add(fact_id)
        if (
            type(fact_id) is str
            and _FACT_ID_RE.fullmatch(fact_id)
            and type(relation) is str
            and _RELATION_RE.fullmatch(relation)
            and source_status in ("supported", "absent")
            and origin_class in _PROVENANCE_CLASSES
            and not (
                (source_status == "supported" and origin_class != "source_extracted")
                or (source_status == "absent" and origin_class == "source_extracted")
            )
        ):
            parsed.append(
                {
                    "fact_id": fact_id,
                    "relation": relation,
                    "source_status": source_status,
                    "origin_class": origin_class,
                }
            )
    return parsed


def _parse_stage_facts(
    value: object, layer: str, diagnostics: list[StableDiagnostic]
) -> dict[str, dict[str, Any]]:
    path = "$.%s.facts" % layer
    if type(value) not in (list, tuple):
        diagnostics.append(
            StableDiagnostic("FACTS_TYPE", "schema", "", path)
        )
        return {}
    if len(value) > _MAX_ITEMS:
        diagnostics.append(
            StableDiagnostic("COLLECTION_LIMIT", "schema", "", path)
        )
    parsed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        fact = _parse_fact(item, item_path, "schema", diagnostics)
        if fact is None:
            continue
        fact_id = fact["id"]
        if fact_id in parsed:
            diagnostics.append(
                StableDiagnostic(
                    "DUPLICATE_FACT_ID",
                    "schema",
                    fact["predicate"],
                    item_path + ".id",
                )
            )
            continue
        parsed[fact_id] = fact
    return parsed


def _parse_projection_outputs(
    outputs: object,
    approved_hashes: object,
    diagnostics: list[StableDiagnostic],
) -> dict[str, dict[str, dict[str, Any]]]:
    if type(outputs) is not dict:
        diagnostics.append(
            StableDiagnostic("PROJECTION_OUTPUTS_TYPE", "schema", "", "$.projection")
        )
        outputs = {}
    if type(approved_hashes) is not dict:
        diagnostics.append(
            StableDiagnostic(
                "APPROVED_RENDER_HASHES_TYPE", "schema", "", "$.approved_content_hashes"
            )
        )
        approved_hashes = {}
    if set(outputs) != set(_CONDITIONS):
        diagnostics.append(
            StableDiagnostic(
                "PROJECTION_CONDITIONS", "schema", "", "$.projection"
            )
        )
    if set(approved_hashes) != set(_CONDITIONS):
        diagnostics.append(
            StableDiagnostic(
                "APPROVED_RENDER_CONDITIONS",
                "schema",
                "",
                "$.approved_content_hashes",
            )
        )

    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for condition in _CONDITIONS:
        output = outputs.get(condition)
        condition_path = "$.projection." + condition
        if type(output) is not dict:
            diagnostics.append(
                StableDiagnostic(
                    "PROJECTION_OUTPUT_MISSING",
                    "projection",
                    "",
                    condition_path,
                )
            )
            normalized[condition] = {}
            continue
        content = output.get("content")
        content_path = condition_path + ".content"
        if (
            type(content) is not str
            or len(content) > _MAX_RENDER_LENGTH
            or not content.isascii()
        ):
            diagnostics.append(
                StableDiagnostic(
                    "PROJECTION_CONTENT_INVALID",
                    "schema",
                    "",
                    content_path,
                )
            )
        else:
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            approved = approved_hashes.get(condition)
            if type(approved) is not str or not _SHA256_RE.fullmatch(approved):
                diagnostics.append(
                    StableDiagnostic(
                        "APPROVED_RENDER_HASH_INVALID",
                        "schema",
                        "",
                        "$.approved_content_hashes." + condition,
                    )
                )
            elif digest != approved:
                diagnostics.append(
                    StableDiagnostic(
                        "PROJECTION_RENDER_MISMATCH",
                        "projection",
                        "rendered_content",
                        content_path,
                    )
                )
            hashes = output.get("hashes")
            declared = hashes.get("content_sha256") if type(hashes) is dict else None
            if declared != digest:
                diagnostics.append(
                    StableDiagnostic(
                        "PROJECTION_CONTENT_HASH_MISMATCH",
                        "projection",
                        "rendered_content",
                        content_path,
                    )
                )

        binding = output.get("binding")
        facts = binding.get("facts") if type(binding) is dict else None
        normalized[condition] = _parse_projection_facts(
            facts, condition, diagnostics
        )
    return normalized


def _parse_projection_facts(
    value: object,
    condition: str,
    diagnostics: list[StableDiagnostic],
) -> dict[str, dict[str, Any]]:
    path = "$.projection.%s.binding.facts" % condition
    if type(value) is not list or len(value) > _MAX_ITEMS:
        diagnostics.append(
            StableDiagnostic("PROJECTION_FACTS_TYPE", "schema", "", path)
        )
        return {}
    parsed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        item_path = "%s[%d]" % (path, index)
        fact = _parse_fact(item, item_path, "schema", diagnostics)
        if fact is None:
            continue
        fact_id = fact["id"]
        if fact_id in parsed:
            diagnostics.append(
                StableDiagnostic(
                    "DUPLICATE_FACT_ID",
                    "schema",
                    fact["predicate"],
                    item_path + ".id",
                )
            )
            continue
        parsed[fact_id] = fact
    return parsed


def _parse_fact(
    value: object,
    path: str,
    error_layer: str,
    diagnostics: list[StableDiagnostic],
) -> dict[str, Any] | None:
    if type(value) is not dict or len(value) > 32:
        diagnostics.append(StableDiagnostic("FACT_RECORD_SHAPE", error_layer, "", path))
        return None
    fact_id = value.get("id")
    predicate = value.get("predicate")
    if type(fact_id) is not str or not _FACT_ID_RE.fullmatch(fact_id):
        diagnostics.append(
            StableDiagnostic("FACT_ID", error_layer, "", path + ".id")
        )
        return None
    if type(predicate) is not str or not _RELATION_RE.fullmatch(predicate):
        diagnostics.append(
            StableDiagnostic("FACT_RELATION", error_layer, "", path + ".predicate")
        )
        return None
    for field in ("subject_id", "object_id"):
        if type(value.get(field)) is not str or len(value[field]) > 160:
            diagnostics.append(
                StableDiagnostic(
                    "FACT_REFERENCE", error_layer, predicate, path + "." + field
                )
            )
            return None
    status = value.get("status")
    if status not in ("known", "unknown"):
        diagnostics.append(
            StableDiagnostic("FACT_STATUS", error_layer, predicate, path + ".status")
        )
        return None
    fact_value = value.get("value")
    if type(fact_value) not in (str, bool, int, float, type(None)):
        diagnostics.append(
            StableDiagnostic("FACT_VALUE", error_layer, predicate, path + ".value")
        )
        return None
    if type(fact_value) is str and len(fact_value) > _MAX_TEXT_LENGTH:
        diagnostics.append(
            StableDiagnostic("FACT_VALUE", error_layer, predicate, path + ".value")
        )
        return None
    try:
        json.dumps(fact_value, allow_nan=False, ensure_ascii=True)
    except (TypeError, ValueError):
        diagnostics.append(
            StableDiagnostic("FACT_VALUE", error_layer, predicate, path + ".value")
        )
        return None

    provenance = value.get("provenance")
    if type(provenance) is not dict or len(provenance) > 8:
        diagnostics.append(
            StableDiagnostic(
                "FACT_PROVENANCE", error_layer, predicate, path + ".provenance"
            )
        )
        return None
    provenance_class = provenance.get("class")
    source_refs = provenance.get("source_refs")
    if (
        type(provenance_class) is not str
        or provenance_class not in _PROVENANCE_CLASSES
        or type(source_refs) is not list
        or len(source_refs) > 16
        or any(type(ref) is not str or len(ref) > 256 for ref in source_refs)
    ):
        diagnostics.append(
            StableDiagnostic(
                "FACT_PROVENANCE", error_layer, predicate, path + ".provenance"
            )
        )
        return None
    if status == "unknown" and fact_value is not None:
        diagnostics.append(
            StableDiagnostic(
                "UNKNOWN_FACT_HAS_VALUE", error_layer, predicate, path + ".value"
            )
        )
    return {
        "id": fact_id,
        "predicate": predicate,
        "subject_id": value["subject_id"],
        "object_id": value["object_id"],
        "status": status,
        "value": fact_value,
        "provenance": {
            "class": provenance_class,
            "source_refs": list(source_refs),
        },
        "path": path,
    }


def _check_unknown_fact(
    records: dict[str, dict[str, Any]],
    layer: str,
    fact_id: str,
    relation: str,
    diagnostics: list[StableDiagnostic],
    *,
    condition: str | None = None,
) -> None:
    fact = records.get(fact_id)
    if fact is None:
        if layer == "source":
            return
        if layer == "projection":
            code = "PROJECTION_UNKNOWN_MISSING"
            path = "$.projection.%s.binding.facts[%s]" % (condition, fact_id)
        else:
            code = {
                "extraction": "EXTRACTION_UNKNOWN_MISSING",
                "authoring": "AUTHORING_UNKNOWN_MISSING",
            }.get(layer)
            if code is None:
                return
            path = _fact_path(layer, fact_id)
        diagnostics.append(StableDiagnostic(code, layer, relation, path))
        return
    if fact["predicate"] != relation:
        diagnostics.append(_relation_mismatch(layer, relation, fact))
        return
    if layer == "source" and fact["status"] == "known":
        code = "SOURCE_SUPPORT_CONTRADICTION"
    elif fact["status"] == "known":
        code = "UNKNOWN_PROMOTED"
    elif (
        fact["value"] is not None
        or fact["provenance"]["class"] != "unknown"
        or fact["provenance"]["source_refs"]
    ):
        code = "UNKNOWN_RECORD_INVALID"
    else:
        return
    diagnostics.append(
        StableDiagnostic(
            code,
            layer,
            relation,
            fact["path"],
        )
    )


def _check_projection_fact(
    expected_fact: dict[str, Any],
    projections: dict[str, dict[str, dict[str, Any]]],
    fact_id: str,
    relation: str,
    diagnostics: list[StableDiagnostic],
) -> None:
    for condition in _CONDITIONS:
        observed = projections[condition].get(fact_id)
        if observed is None:
            diagnostics.append(
                StableDiagnostic(
                    "PROJECTION_FACT_MISSING",
                    "projection",
                    relation,
                    "$.projection.%s.binding.facts[%s]" % (condition, fact_id),
                )
            )
        elif not _matches_fact(observed, expected_fact, relation):
            diagnostics.append(
                _relation_mismatch("projection", relation, observed)
                if observed["predicate"] != relation
                else _content_mismatch(
                    "projection",
                    relation,
                    observed,
                    expected=expected_fact,
                )
            )


def _matches_fact(
    observed: dict[str, Any], expected: dict[str, Any], relation: str
) -> bool:
    return (
        observed["predicate"] == relation
        and all(
            observed[field] == expected[field]
            for field in ("id", "predicate", "subject_id", "object_id", "status", "value", "provenance")
        )
    )


def _content_mismatch(
    layer: str,
    relation: str,
    fact: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> StableDiagnostic:
    differing_field = next(
        field
        for field in (
            "status",
            "value",
            "subject_id",
            "object_id",
            "provenance",
        )
        if fact[field] != expected[field]
    )
    return StableDiagnostic(
        "FACT_CONTENT_MISMATCH",
        layer,
        relation,
        fact["path"] + "." + differing_field,
    )


def _relation_mismatch(
    layer: str,
    relation: str,
    fact: dict[str, Any],
) -> StableDiagnostic:
    return StableDiagnostic(
        "FACT_RELATION_MISMATCH",
        layer,
        relation,
        fact["path"] + ".predicate",
    )


def _fact_path(layer: str, fact_id: str) -> str:
    return "$.%s.facts[%s]" % (layer, fact_id)


def _diagnostic_key(item: StableDiagnostic) -> tuple[str, str, str, str, str]:
    return (item.layer, item.relation, item.path, item.code, item.severity)
