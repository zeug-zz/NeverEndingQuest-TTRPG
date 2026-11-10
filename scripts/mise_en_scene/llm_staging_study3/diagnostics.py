# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Collect-all, metadata-only Study 2 delta diagnostics for Study 3 parity."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from . import contract, protocol


# TABLETOP MODE: Cross-version diagnostics only; never mutate or re-score Study 2.
DIAGNOSTIC_LABEL = "DIAGNOSTIC_NOT_STUDY_RESULT"
DIAGNOSTIC_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3-prep"
)
STUDY2_RUN_ID = "study2-20261109T210130Z"
STUDY2_SOURCE_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study2/runs/" + STUDY2_RUN_ID
)
STUDY2_COPY_RELATIVE = (
    DIAGNOSTIC_ROOT_RELATIVE
    + "/collect-all-"
    + STUDY2_RUN_ID
    + "/"
    + DIAGNOSTIC_LABEL
)
STUDY2_FILENAMES = ("01-delta.json", "02-delta.json", "03-delta.json")
STUDY2_SCHEMA_ID = "neq.llm_staging_study2_delta.v1"
_AGENCY_PATTERNS = (
    re.compile(r"\b(?:you|the party|the players?)\s+(?:choose|chose|decide|decided|select|selected)\b", re.I),
    re.compile(r"\b(?:you|the party|the players?)\s+(?:succeed|succeeds|succeeded)\b", re.I),
    re.compile(r"\b(?:you|the party|the players?)\s+successfully\s+\w+\b", re.I),
)
_ROLE_NAMES = ("approach", "threshold", "focal_anchor", "usable_space")
_ARRIVAL_ROLES = ("approach", "threshold", "focal")
_PREDICATES = frozenset(
    (
        "approach_to_threshold",
        "threshold_to_focal",
        "usable_space",
        "light_gradient",
        "sound_gradient",
        "weather_gradient",
        "visible_affordance",
    )
)
_FACT_FIELDS = frozenset(("fact_id", "subject_id", "predicate", "object_id", "value"))
_CLAIM_FIELDS = frozenset(("id", "fact_id", "kind", "span", "choice", "success"))
_ROOT_FIELDS = frozenset(
    ("schema", "input_refs", "fixture_deltas", "stage_role_bindings", "claims", "arrival_prose")
)
_KNOWN_PATH_TOKENS = frozenset(
    _ROOT_FIELDS
    | _FACT_FIELDS
    | _CLAIM_FIELDS
    | {
        "facts",
        "items",
        "segment_id",
        "role",
        "text",
        "id",
        "scene_id",
        "source_packet",
        "expected_bundle",
        "topology",
        "gate_canonical_context",
        "sha256",
        "entity_id",
        "kind",
        "approach",
        "threshold",
        "focal",
        "focal_anchor",
        "usable_space",
    }
)
_CHECK_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "parse": ("raw_bytes",),
    "schema": ("parse", "study3_protocol_integrity", "scene_binding"),
    "references": ("parse", "scene_binding", "input_refs.shape"),
    "overwrite": ("parse", "fixture_deltas.facts[]"),
    "entity_references": ("parse", "scene_binding", "fixture_deltas.facts[]"),
    "roles": ("parse", "stage_role_bindings.shape"),
    "facts": ("parse", "fixture_deltas.facts[]"),
    "claims": ("parse", "claims[]", "arrival_prose[]"),
    "protected": ("parse", "scene_binding", "public_delta_text"),
}


def _rule_lookup() -> dict[str, contract.RuleSpec]:
    return {item.rule_id: item for item in contract.OUTPUT_RULE_MAP + contract.HOST_RULE_MAP}


_RULES_BY_ID = _rule_lookup()
_RULE_IDS_BY_CHECK: Mapping[str, tuple[str, ...]] = {
    check_id: tuple(rule.rule_id for rule in contract.OUTPUT_RULE_MAP if rule.check_id == check_id)
    for check_id in _CHECK_DEPENDENCIES
    if check_id != "parse"
}
_RULE_IDS_BY_CHECK = {
    **_RULE_IDS_BY_CHECK,
    "parse": tuple(rule.rule_id for rule in contract.OUTPUT_RULE_MAP if rule.check_id == "parse"),
}


class _Collector:
    """Accumulate bounded diagnostics without retaining output values or prose."""

    def __init__(self) -> None:
        self.findings: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.migrations: dict[tuple[str, str], dict[str, Any]] = {}
        self.checked_rules: set[str] = set()
        self.blocked_rules: dict[str, list[dict[str, str]]] = {}
        self.check_errors: dict[str, str] = {}
        self.completed_checks: set[str] = set()
        self.current_check_id: str | None = None
        self.unmapped_rule_failures: dict[tuple[str, str, str, str], dict[str, str]] = {}

    def checked(self, *rule_ids: str) -> None:
        for rule_id in rule_ids:
            if rule_id not in _RULES_BY_ID:
                self._record_unmapped_rule(rule_id, "checked", "")
            else:
                self.checked_rules.add(rule_id)

    def _record_unmapped_rule(self, rule_id: str, operation: str, path: str) -> None:
        safe_rule_id = _safe_metadata(rule_id, 80) or "UNAVAILABLE"
        safe_operation = _safe_metadata(operation, 24) or "UNAVAILABLE"
        safe_check_id = _safe_metadata(self.current_check_id or "precheck", 40) or "precheck"
        bounded_path = _bounded_pointer(path)
        key = (safe_rule_id, safe_operation, safe_check_id, bounded_path)
        self.unmapped_rule_failures[key] = {
            "code": "UNMAPPED_RULE_ID",
            "reported_rule_id": safe_rule_id,
            "operation": safe_operation,
            "check_id": safe_check_id,
            "path": bounded_path,
            "status": "BLOCKED",
            "dependency": "rule_map",
            "reason": "The diagnostic assertion has no declared rule-map entry.",
        }

    def blocked(
        self,
        rule_id: str,
        dependency: str,
        reason: str,
        path: str = "",
    ) -> None:
        if rule_id not in _RULES_BY_ID:
            self._record_unmapped_rule(rule_id, "blocked", path)
            return
        item = {
            "dependency": _safe_metadata(dependency, 80),
            "reason": _safe_metadata(reason, 120),
            "path": _bounded_pointer(path),
        }
        rows = self.blocked_rules.setdefault(rule_id, [])
        if item not in rows:
            rows.append(item)

    def violation(self, rule_id: str, code: str, path: str = "") -> None:
        spec = _RULES_BY_ID.get(rule_id)
        if spec is None:
            self._record_unmapped_rule(rule_id, "violation", path)
            return
        self.checked(rule_id)
        bounded_path = _bounded_pointer(path)
        key = (rule_id, bounded_path, code)
        if key in self.findings:
            self.findings[key]["occurrences"] += 1
            return
        self.findings[key] = {
            "code": code,
            "rule_id": rule_id,
            "category": spec.category,
            "path": bounded_path,
            "occurrences": 1,
            "source_pointers": _source_pointers(spec),
        }

    def migration(
        self,
        rule_id: str,
        path: str,
        *,
        legacy_sources: tuple[str, ...],
        reason: str,
    ) -> None:
        spec = _RULES_BY_ID.get(rule_id)
        if spec is None:
            self._record_unmapped_rule(rule_id, "migration", path)
            return
        bounded_path = _bounded_pointer(path)
        key = (rule_id, bounded_path)
        if key not in self.migrations:
            self.migrations[key] = {
                "code": "PROTOCOL_VERSION_OR_NAMESPACE_MIGRATION",
                "rule_id": rule_id,
                "category": "protocol_version_or_namespace_migration",
                "source_category": spec.category,
                "path": bounded_path,
                "occurrences": 1,
                "source_pointers": _source_pointers(spec),
                "legacy_source_pointers": list(legacy_sources),
                "reason": reason[:180],
                "finding_suppressed": False,
            }
        else:
            self.migrations[key]["occurrences"] += 1

    def finish_check(self, check_id: str) -> None:
        self.completed_checks.add(check_id)

    def failed_check(self, check_id: str, error_type: str) -> None:
        reason = "CHECK_EXECUTION_ERROR_" + error_type
        self.check_errors[check_id] = reason
        for rule_id in _RULE_IDS_BY_CHECK.get(check_id, ()):
            self.blocked(rule_id, "check:" + check_id, reason)

    def report(self, *, scene_id: str, source_name: str, copy_path_checked: bool) -> dict[str, Any]:
        coverage: list[dict[str, Any]] = []
        for rule in contract.OUTPUT_RULE_MAP + contract.HOST_RULE_MAP:
            blocked = self.blocked_rules.get(rule.rule_id, [])
            was_checked = rule.rule_id in self.checked_rules
            if was_checked and blocked:
                status = "PARTIAL"
            elif was_checked:
                status = "EVALUATED"
            else:
                status = "NOT_EVALUATED"
                if not blocked:
                    dependency = rule.check_id if rule.check_id in _CHECK_DEPENDENCIES else "host_integrity"
                    self.blocked(
                        rule.rule_id,
                        dependency,
                        "No completed diagnostic assertion was available for this mapped rule.",
                    )
                    blocked = self.blocked_rules[rule.rule_id]
            coverage.append(
                {
                    "rule_id": rule.rule_id,
                    "category": rule.category,
                    "check_id": rule.check_id,
                    "status": status,
                    "source_pointers": _source_pointers(rule),
                    "blocked_dependencies": sorted(
                        blocked,
                        key=lambda item: (item["dependency"], item["path"], item["reason"]),
                    ),
                }
            )

        checks: list[dict[str, Any]] = []
        for check_id, dependencies in _CHECK_DEPENDENCIES.items():
            related = [row for row in coverage if row["check_id"] == check_id]
            if check_id in self.check_errors:
                status = "NOT_EVALUATED" if not any(row["status"] != "NOT_EVALUATED" for row in related) else "PARTIAL"
            elif not related or all(row["status"] == "NOT_EVALUATED" for row in related):
                status = "NOT_EVALUATED"
            elif any(row["status"] in ("PARTIAL", "NOT_EVALUATED") for row in related):
                status = "PARTIAL"
            else:
                status = "EVALUATED"
            checks.append(
                {
                    "check_id": check_id,
                    "status": status,
                    "dependencies": list(dependencies),
                    "reason": self.check_errors.get(check_id),
                }
            )

        findings = sorted(
            self.findings.values(),
            key=lambda item: (item["rule_id"], item["path"], item["code"]),
        )
        migrations = sorted(
            self.migrations.values(),
            key=lambda item: (item["rule_id"], item["path"]),
        )
        not_evaluated = sum(row["status"] == "NOT_EVALUATED" for row in coverage)
        partial = sum(row["status"] == "PARTIAL" for row in coverage)
        integrity_failures = sorted(
            self.unmapped_rule_failures.values(),
            key=lambda item: (item["reported_rule_id"], item["operation"], item["path"]),
        )
        hydration_dependencies = ["task_2_2_study3_hydration_not_implemented"]
        if findings:
            hydration_dependencies.insert(0, "study3_output_contract_findings")
        return {
            "label": DIAGNOSTIC_LABEL,
            "result_kind": "metadata_only_cross_protocol_diagnostic",
            "scene_id": scene_id,
            "source_copy_name": source_name,
            "copy_path_checked": copy_path_checked,
            "status": "DIAGNOSTIC_ONLY_NOT_A_STUDY_VERDICT",
            "rule_inventory_size": len(coverage),
            "output_rule_count": len(contract.OUTPUT_RULE_MAP),
            "host_rule_count": len(contract.HOST_RULE_MAP),
            "summary": {
                "finding_records": len(findings),
                "finding_occurrences": sum(row["occurrences"] for row in findings),
                "migration_difference_records": len(migrations),
                "migration_difference_occurrences": sum(row["occurrences"] for row in migrations),
                "rules_not_evaluated": not_evaluated,
                "rules_partially_evaluated": partial,
                "unmapped_rule_failures": len(integrity_failures),
            },
            "findings": findings,
            "migration_differences": migrations,
            "checks": checks,
            "rule_coverage": coverage,
            "diagnostic_integrity": {
                "status": "BLOCKED" if integrity_failures else "PASS",
                "blocked_unmapped_rule_failures": integrity_failures,
            },
            "downstream_pipeline": {
                "hydration": {
                    "status": "NOT_EVALUATED",
                    "dependencies": hydration_dependencies,
                    "reason": "Task 2.2 hydration is not implemented; contract findings also block hydration for this delta." if findings else "Task 2.2 hydration is not implemented and is outside Task 1.4.",
                },
                "full_unchanged_safety_gates": {
                    "status": "NOT_EVALUATED",
                    "dependencies": ["study3_hydration"],
                    "reason": "The complete downstream gate chain is not implemented or exercised by Task 1.4.",
                },
            },
            "interpretation": {
                "study2_verdict_changed": False,
                "study_result": False,
                "finite_examples_prove_no_hidden_rule": False,
                "raw_payload_evaluated_unchanged": True,
                "migration_annotations_suppress_findings": False,
            },
        }


def diagnose_delta_bytes(
    output_bytes: object,
    *,
    scene_id: str,
    source_name: str = "in-memory-delta",
) -> dict[str, Any]:
    """Collect independently evaluable Study 3 findings from one byte string.

    This byte-level API does not claim filesystem-path evaluation. The file-runner
    below adds a host path-boundary result after it has safely opened a labeled copy.
    """

    return _diagnose_delta_bytes(
        output_bytes,
        scene_id=scene_id,
        source_name=source_name,
        copy_path_checked=False,
    )


def _diagnose_delta_bytes(
    output_bytes: object,
    *,
    scene_id: str,
    source_name: str,
    copy_path_checked: bool,
) -> dict[str, Any]:
    collector = _Collector()
    binding: contract.SceneBinding | None = None
    canonical_error: str | None = None
    if type(scene_id) is str and scene_id in protocol.SCENE_ORDER:
        try:
            binding = contract.load_scene_binding(scene_id)
            collector.checked("HOST-CANONICAL-HASH-INTEGRITY")
        except (contract.ContractError, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            canonical_error = getattr(error, "code", "CANONICAL_INPUT_UNAVAILABLE")
            collector.violation(
                "HOST-CANONICAL-HASH-INTEGRITY",
                "CANONICAL_INTEGRITY_UNAVAILABLE",
            )
            collector.blocked(
                "HOST-CANONICAL-HASH-INTEGRITY",
                "study3_protocol_integrity",
                canonical_error,
            )
    else:
        canonical_error = "SCENE_NOT_APPROVED"
        collector.violation("HOST-CANONICAL-HASH-INTEGRITY", "SCENE_BINDING_UNAVAILABLE", "/scene_id")
        collector.blocked(
            "HOST-CANONICAL-HASH-INTEGRITY",
            "scene_id",
            canonical_error,
        )

    if copy_path_checked:
        collector.checked("HOST-PROJECT-PATH-BOUNDARY")
    else:
        collector.blocked(
            "HOST-PROJECT-PATH-BOUNDARY",
            "diagnostic_input_path",
            "Byte-level diagnostic received no filesystem path to evaluate.",
        )

    raw: bytes | None = output_bytes if type(output_bytes) is bytes else None
    payload: dict[str, Any] | None = None
    parse_error: str | None = None
    parser_rules = _RULE_IDS_BY_CHECK["parse"]
    if raw is None:
        collector.violation("S3-JSON-OBJECT", "OUTPUT_BYTES_INVALID")
        parse_error = "OUTPUT_BYTES_INVALID"
        for rule_id in parser_rules:
            if rule_id != "S3-JSON-OBJECT":
                collector.blocked(rule_id, "parse", parse_error)
    elif len(raw) > contract.MAX_DELTA_BYTES:
        collector.violation("S3-JSON-BYTE-LIMIT", "OUTPUT_BYTE_LIMIT")
        parse_error = "OUTPUT_BYTE_LIMIT"
        for rule_id in parser_rules:
            if rule_id != "S3-JSON-BYTE-LIMIT":
                collector.blocked(rule_id, "parse", parse_error)
    else:
        try:
            decoded = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=_parse_finite_float,
                parse_constant=_reject_nonfinite_constant,
            )
        except UnicodeDecodeError:
            collector.violation("S3-JSON-OBJECT", "OUTPUT_UTF8_INVALID")
            parse_error = "OUTPUT_UTF8_INVALID"
        except _DuplicateKey:
            collector.violation("S3-JSON-DUPLICATE-KEYS", "OUTPUT_DUPLICATE_KEY")
            parse_error = "OUTPUT_DUPLICATE_KEY"
        except _NonFinite:
            collector.violation("S3-JSON-NONFINITE", "OUTPUT_NONFINITE_NUMBER")
            parse_error = "OUTPUT_NONFINITE_NUMBER"
        except (json.JSONDecodeError, ValueError, RecursionError, OverflowError):
            collector.violation("S3-JSON-OBJECT", "OUTPUT_JSON_INVALID")
            parse_error = "OUTPUT_JSON_INVALID"
        else:
            if type(decoded) is not dict:
                collector.violation("S3-JSON-OBJECT", "OUTPUT_JSON_OBJECT_REQUIRED")
                parse_error = "OUTPUT_JSON_OBJECT_REQUIRED"
            else:
                payload = decoded
                collector.checked(*parser_rules)

        if parse_error is not None:
            for rule_id in parser_rules:
                if rule_id not in collector.checked_rules:
                    collector.blocked(rule_id, "parse", parse_error)

    if payload is None:
        for rule in contract.OUTPUT_RULE_MAP:
            if rule.check_id != "parse":
                collector.blocked(rule.rule_id, "parse", parse_error or "JSON payload unavailable.")
        if canonical_error is None:
            collector.checked("HOST-CANONICAL-HASH-INTEGRITY")
        collector.finish_check("parse")
        return collector.report(
            scene_id=scene_id if type(scene_id) is str else "",
            source_name=source_name,
            copy_path_checked=copy_path_checked,
        )

    collector.finish_check("parse")
    if binding is None:
        for rule in contract.OUTPUT_RULE_MAP:
            if rule.check_id != "parse":
                collector.blocked(rule.rule_id, "scene_binding", canonical_error or "Canonical binding unavailable.")
        return collector.report(
            scene_id=scene_id,
            source_name=source_name,
            copy_path_checked=copy_path_checked,
        )

    for rule_id, path, legacy_sources, reason in _protocol_version_annotations(payload):
        collector.migration(
            rule_id,
            path,
            legacy_sources=legacy_sources,
            reason=reason,
        )

    _run_check(collector, "schema", lambda: _check_schema(collector, payload, scene_id))
    _run_check(collector, "references", lambda: _check_references(collector, payload, binding))
    _run_check(collector, "overwrite", lambda: _check_overwrites(collector, payload, binding))
    _run_check(collector, "entity_references", lambda: _check_entity_references(collector, payload, binding))
    _run_check(collector, "roles", lambda: _check_roles(collector, payload, binding))
    _run_check(collector, "facts", lambda: _check_facts(collector, payload, binding))
    _run_check(collector, "claims", lambda: _check_claims(collector, payload, binding))
    _run_check(collector, "protected", lambda: _check_protected(collector, payload, binding))
    return collector.report(
        scene_id=scene_id,
        source_name=source_name,
        copy_path_checked=copy_path_checked,
    )


def _run_check(collector: _Collector, check_id: str, check: Callable[[], None]) -> None:
    previous_check_id = collector.current_check_id
    collector.current_check_id = check_id
    try:
        check()
    except Exception as error:  # Diagnostics must fail closed rather than crash on malformed rows.
        collector.failed_check(check_id, type(error).__name__)
    else:
        collector.finish_check(check_id)
    finally:
        collector.current_check_id = previous_check_id


def _protocol_version_annotations(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, str, tuple[str, ...], str], ...]:
    """Describe the declared schema-version difference without rewriting data."""

    if payload.get("schema") != STUDY2_SCHEMA_ID:
        return ()
    return (
        (
            "S3-ROOT-FIELDS",
            "/schema",
            ("study2_output_schema#/properties/schema/const",),
            "Frozen Study 2 and Study 3 declare different schema identifiers.",
        ),
    )


def _check_schema(collector: _Collector, payload: dict[str, Any], scene_id: str) -> None:
    rules = _RULE_IDS_BY_CHECK["schema"]
    try:
        schema = protocol.render_output_schema(scene_id)
        Draft202012Validator.check_schema(schema)
        errors = Draft202012Validator(schema).iter_errors(payload)
        for error in errors:
            rule_id = contract._schema_rule_id(error, payload)
            collector.violation(rule_id, "SCHEMA_CONSTRAINT_VIOLATION", _path_from_parts(error.absolute_path))
    except (SchemaError, RecursionError, TypeError, ValueError, KeyError, AttributeError, contract.ContractError) as error:
        reason = getattr(error, "code", "SCHEMA_OR_PROTOCOL_UNAVAILABLE")
        for rule_id in rules:
            collector.blocked(rule_id, "schema_and_study3_protocol", reason)
        collector.check_errors["schema"] = "SCHEMA_EVALUATION_UNAVAILABLE"
        return
    collector.checked(*rules)


def _check_references(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    rule_id = "S3-EXACT-INPUT-REFERENCES"
    observed = payload.get("input_refs")
    if type(observed) is not dict:
        collector.blocked(rule_id, "input_refs.object", "The input_refs object is missing or not an object.", "/input_refs")
        return
    expected = binding.input_refs
    if "scene_id" not in observed or type(observed.get("scene_id")) is not str:
        collector.blocked(rule_id, "input_refs.scene_id", "The scene_id value is missing or not a string.", "/input_refs/scene_id")
    else:
        collector.checked(rule_id)
        if observed["scene_id"] != binding.scene_id:
            collector.violation(rule_id, "INPUT_REFERENCE_MISMATCH", "/input_refs/scene_id")
    for name in ("source_packet", "expected_bundle", "topology", "gate_canonical_context"):
        ref = observed.get(name)
        expected_ref = expected.get(name)
        if type(ref) is not dict or not isinstance(expected_ref, Mapping):
            collector.blocked(rule_id, "input_refs." + name, "The reference object is missing or not an object.", "/input_refs/" + name)
            continue
        for field in ("id", "sha256"):
            path = "/input_refs/" + name + "/" + field
            if field not in ref or type(ref.get(field)) is not str:
                collector.blocked(rule_id, "input_refs." + name + "." + field, "The reference value is missing or not a string.", path)
                continue
            collector.checked(rule_id)
            if ref[field] != expected_ref.get(field):
                collector.violation(rule_id, "INPUT_REFERENCE_MISMATCH", path)


def _facts_list(payload: Mapping[str, Any]) -> tuple[list[Any] | None, str]:
    fixture = payload.get("fixture_deltas")
    if type(fixture) is not dict:
        return None, "fixture_deltas object is missing or invalid."
    facts = fixture.get("facts")
    if type(facts) is not list:
        return None, "fixture_deltas.facts array is missing or invalid."
    return facts, ""


def _check_overwrites(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    facts, reason = _facts_list(payload)
    if facts is None:
        collector.blocked("S3-NO-BASE-FACT-OVERWRITE", "fixture_deltas.facts[]", reason, "/fixture_deltas/facts")
        return
    rule_id = "S3-NO-BASE-FACT-OVERWRITE"
    if not facts:
        collector.checked(rule_id)
    for index, fact in enumerate(facts):
        path = f"/fixture_deltas/facts/{index}/fact_id"
        if type(fact) is not dict or type(fact.get("fact_id")) is not str:
            collector.blocked(rule_id, "fact.fact_id", "A string fact_id is required to check overwrite collisions.", path)
            continue
        collector.checked(rule_id)
        if fact["fact_id"] in binding.base_fact_ids:
            collector.violation(rule_id, "BASE_FACT_OVERWRITE", path)


def _check_entity_references(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    facts, reason = _facts_list(payload)
    rule_id = "S3-ENTITY-REFERENCE-SCOPE"
    if facts is None:
        collector.blocked(rule_id, "fixture_deltas.facts[]", reason, "/fixture_deltas/facts")
        return
    topology = binding.topology_ids
    if not facts:
        collector.checked(rule_id)
    for index, fact in enumerate(facts):
        base_path = f"/fixture_deltas/facts/{index}"
        if type(fact) is not dict:
            collector.blocked(rule_id, "fact.object", "A fact object is required for topology-reference checks.", base_path)
            continue
        for field in ("subject_id", "object_id"):
            path = base_path + "/" + field
            if field not in fact:
                collector.blocked(rule_id, "fact." + field, "The topology-reference field is missing.", path)
            elif field == "object_id" and fact[field] is None:
                collector.checked(rule_id)
            elif type(fact[field]) is not str:
                collector.blocked(rule_id, "fact." + field, "A topology ID or permitted null object_id is required.", path)
            else:
                collector.checked(rule_id)
                if fact[field] not in topology:
                    collector.violation(rule_id, "UNKNOWN_TOPOLOGY_ID", path)
        value = fact.get("value")
        if type(value) is dict and value.get("kind") == "entity_ref":
            entity_id = value.get("entity_id")
            path = base_path + "/value/entity_id"
            if type(entity_id) is not str:
                collector.blocked(rule_id, "value.entity_ref.entity_id", "The entity reference target is missing or not a string.", path)
            else:
                collector.checked(rule_id)
                if entity_id not in topology:
                    collector.violation(rule_id, "ENTITY_REFERENCE_INVALID", path)
        elif type(value) is not dict:
            collector.checked(rule_id)
        elif value.get("kind") != "entity_ref":
            collector.checked(rule_id)


def _check_roles(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    roles = payload.get("stage_role_bindings")
    fields_rule = "S3-STAGE-ROLE-FIELDS"
    bounds_rule = "S3-STAGE-ROLE-BOUNDS-UNIQUE"
    candidates_rule = "S3-STAGE-ROLE-CANDIDATES"
    if type(roles) is not dict:
        reason = "stage_role_bindings object is missing or invalid."
        for rule_id in (fields_rule, bounds_rule, candidates_rule):
            collector.blocked(rule_id, "stage_role_bindings.object", reason, "/stage_role_bindings")
        return

    collector.checked(fields_rule)
    if set(roles) != set(_ROLE_NAMES):
        collector.violation(fields_rule, "STAGE_ROLE_FIELDS_INVALID", "/stage_role_bindings")

    for role in _ROLE_NAMES:
        path = "/stage_role_bindings/" + role
        ids = roles.get(role)
        if type(ids) is not list:
            collector.blocked(bounds_rule, "stage_role_bindings." + role, "The role candidate list is missing or invalid.", path)
            collector.blocked(candidates_rule, "stage_role_bindings." + role, "The role candidate list is missing or invalid.", path)
            continue

        collector.checked(bounds_rule)
        if not 1 <= len(ids) <= 16:
            collector.violation(bounds_rule, "STAGE_ROLE_BOUNDS_OR_DUPLICATE", path)
        if all(type(value) is str for value in ids):
            if len(ids) != len(set(ids)):
                collector.violation(bounds_rule, "STAGE_ROLE_BOUNDS_OR_DUPLICATE", path)
        else:
            collector.blocked(bounds_rule, "role_id.string", "Role-list uniqueness depends on all IDs being strings.", path)

        collector.checked(candidates_rule)
        for index, value in enumerate(ids):
            item_path = path + "/" + str(index)
            if type(value) is not str:
                collector.blocked(candidates_rule, "role_id.string", "A role candidate must be a string.", item_path)
                continue
            collector.checked(candidates_rule)
            if value not in binding.role_candidates[role]:
                collector.violation(candidates_rule, "STAGE_ROLE_CANDIDATE_INVALID", item_path)


def _check_facts(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    facts, reason = _facts_list(payload)
    fact_rule_ids = (
        "S3-AUTHORED-ID-NAMESPACE",
        "S3-AUTHORED-ID-LIMIT-UNIQUE",
        "S3-PREDICATE-ALLOWLIST",
        "S3-FACT-VALUE-SHAPES",
        "S3-FACT-REFERENCE-SCOPE",
        "S3-FACT-COUNT-BOUNDS",
        "S3-APPROACH-RELATION-TRUE",
        "S3-THRESHOLD-RELATION-TRUE",
        "S3-USABLE-SPACE-ROLE",
    )
    if facts is None:
        for rule_id in fact_rule_ids:
            collector.blocked(rule_id, "fixture_deltas.facts[]", reason, "/fixture_deltas/facts")
        return

    if not facts:
        collector.checked(
            "S3-AUTHORED-ID-NAMESPACE",
            "S3-AUTHORED-ID-LIMIT-UNIQUE",
            "S3-PREDICATE-ALLOWLIST",
            "S3-FACT-VALUE-SHAPES",
            "S3-FACT-REFERENCE-SCOPE",
            "S3-USABLE-SPACE-ROLE",
        )

    count_rule = "S3-FACT-COUNT-BOUNDS"
    collector.checked(count_rule)
    if not 2 <= len(facts) <= 64:
        collector.violation(count_rule, "AUTHORED_FACT_COUNT_INVALID", "/fixture_deltas/facts")

    authored_pattern = binding.authored_fact_pattern
    authored_ids: set[str] = set()
    for fact in facts:
        if type(fact) is dict:
            fact_id = fact.get("fact_id")
            if (
                type(fact_id) is str
                and len(fact_id) <= 256
                and re.fullmatch(authored_pattern, fact_id) is not None
            ):
                authored_ids.add(fact_id)
    seen_ids: set[str] = set()
    predicate_values: list[tuple[int, str]] = []
    predicate_complete = True
    for index, fact in enumerate(facts):
        base_path = f"/fixture_deltas/facts/{index}"
        if type(fact) is not dict:
            for rule_id in fact_rule_ids:
                if rule_id != count_rule:
                    collector.blocked(rule_id, "fact.object", "The fact row is missing or not an object.", base_path)
            predicate_complete = False
            continue

        fact_id = fact.get("fact_id")
        id_path = base_path + "/fact_id"
        if type(fact_id) is not str:
            collector.blocked("S3-AUTHORED-ID-NAMESPACE", "fact.fact_id", "A string fact_id is required.", id_path)
            collector.blocked("S3-AUTHORED-ID-LIMIT-UNIQUE", "fact.fact_id", "A string fact_id is required.", id_path)
        else:
            collector.checked("S3-AUTHORED-ID-NAMESPACE", "S3-AUTHORED-ID-LIMIT-UNIQUE")
            if len(fact_id) > 256:
                collector.violation("S3-AUTHORED-ID-LIMIT-UNIQUE", "AUTHORED_FACT_ID_TOO_LONG", id_path)
            elif re.fullmatch(authored_pattern, fact_id) is None:
                collector.violation("S3-AUTHORED-ID-NAMESPACE", "AUTHORED_FACT_ID_INVALID", id_path)
            if fact_id in seen_ids:
                collector.violation("S3-AUTHORED-ID-LIMIT-UNIQUE", "AUTHORED_FACT_ID_DUPLICATE", id_path)
            seen_ids.add(fact_id)

        predicate = fact.get("predicate")
        predicate_path = base_path + "/predicate"
        if type(predicate) is not str:
            collector.blocked("S3-PREDICATE-ALLOWLIST", "fact.predicate", "The predicate is missing or not a string.", predicate_path)
            predicate_complete = False
        else:
            collector.checked("S3-PREDICATE-ALLOWLIST")
            predicate_values.append((index, predicate))
            if predicate not in _PREDICATES:
                collector.violation("S3-PREDICATE-ALLOWLIST", "AUTHORED_PREDICATE_INVALID", predicate_path)

        value_present = "value" in fact
        value = fact.get("value")
        value_path = base_path + "/value"
        valid_base_or_authored = set(binding.public_base_fact_ids) | authored_ids
        if not value_present:
            collector.blocked("S3-FACT-VALUE-SHAPES", "fact.value", "The fact value is missing.", value_path)
            collector.blocked("S3-FACT-REFERENCE-SCOPE", "fact.value", "The fact value is missing.", value_path)
        else:
            _check_fact_value(collector, value, valid_base_or_authored, value_path)

    role_bindings = payload.get("stage_role_bindings")
    roles_available = type(role_bindings) is dict and all(
        type(role_bindings.get(role)) is list
        and all(type(item) is str for item in role_bindings.get(role, []))
        for role in _ROLE_NAMES
    )
    relation_counts = {"approach_to_threshold": 0, "threshold_to_focal": 0}
    relation_rows: dict[str, list[tuple[int, Mapping[str, Any]]]] = {
        "approach_to_threshold": [],
        "threshold_to_focal": [],
    }
    for index, predicate in predicate_values:
        if predicate in relation_counts:
            relation_counts[predicate] += 1
            row = facts[index]
            if type(row) is dict:
                relation_rows[predicate].append((index, row))
                relation_rule = "S3-APPROACH-RELATION-TRUE" if predicate == "approach_to_threshold" else "S3-THRESHOLD-RELATION-TRUE"
                path = f"/fixture_deltas/facts/{index}"
                if "value" not in row:
                    collector.blocked(relation_rule, "fact.value", "A literal JSON boolean value is required.", path + "/value")
                else:
                    collector.checked(relation_rule)
                    if row.get("value") is not True:
                        collector.violation(relation_rule, "STAGE_RELATION_VALUE_NOT_LITERAL_TRUE", path + "/value")

                if not roles_available:
                    collector.blocked(relation_rule, "stage_role_bindings.selected_roles", "Role membership depends on valid selected role lists.", path)
                else:
                    subject_role, object_role = (
                        ("approach", "threshold")
                        if predicate == "approach_to_threshold"
                        else ("threshold", "focal_anchor")
                    )
                    subject, object_id = row.get("subject_id"), row.get("object_id")
                    if type(subject) is not str or type(object_id) is not str:
                        collector.blocked(relation_rule, "fact.subject_id/object_id", "Relation endpoints must be strings before role membership can be evaluated.", path)
                    else:
                        collector.checked(relation_rule)
                        if subject not in role_bindings[subject_role] or object_id not in role_bindings[object_role]:
                            collector.violation(relation_rule, "STAGE_RELATION_ROLE_MEMBERSHIP_INVALID", path)
        elif predicate == "usable_space":
            rule_id = "S3-USABLE-SPACE-ROLE"
            path = f"/fixture_deltas/facts/{index}/subject_id"
            if not roles_available:
                collector.blocked(rule_id, "stage_role_bindings.usable_space", "Role membership depends on a valid selected usable_space list.", path)
            elif type(facts[index]) is not dict or type(facts[index].get("subject_id")) is not str:
                collector.blocked(rule_id, "fact.subject_id", "A string subject_id is required for usable-space membership.", path)
            else:
                collector.checked(rule_id)
                if facts[index]["subject_id"] not in role_bindings["usable_space"]:
                    collector.violation(rule_id, "USABLE_SPACE_ROLE_INVALID", path)

    for predicate, rule_id in (
        ("approach_to_threshold", "S3-APPROACH-RELATION-TRUE"),
        ("threshold_to_focal", "S3-THRESHOLD-RELATION-TRUE"),
    ):
        if not predicate_complete:
            collector.blocked(rule_id, "all_fact_predicates", "A missing or invalid fact predicate prevents complete relation-count evaluation.", "/fixture_deltas/facts")
        else:
            collector.checked(rule_id)
            if relation_counts[predicate] != 1:
                collector.violation(rule_id, "STAGE_RELATION_COUNT_INVALID", "/fixture_deltas/facts")


def _check_fact_value(
    collector: _Collector,
    value: object,
    valid_fact_refs: set[str],
    path: str,
) -> None:
    shape_rule = "S3-FACT-VALUE-SHAPES"
    reference_rule = "S3-FACT-REFERENCE-SCOPE"
    if type(value) is str:
        collector.checked(shape_rule, reference_rule)
        if len(value) > 512:
            collector.violation(shape_rule, "FACT_VALUE_LENGTH_INVALID", path)
    elif type(value) is bool or value is None:
        collector.checked(shape_rule, reference_rule)
    elif type(value) is dict:
        keys = set(value)
        kind = value.get("kind")
        if kind == "entity_ref" and keys == {"kind", "entity_id"}:
            collector.checked(shape_rule, reference_rule)
        elif kind == "fact_ref" and keys == {"kind", "fact_id"}:
            collector.checked(shape_rule)
            fact_id = value.get("fact_id")
            if type(fact_id) is not str:
                collector.blocked(reference_rule, "value.fact_ref.fact_id", "The fact reference target is missing or not a string.", path + "/fact_id")
            else:
                collector.checked(reference_rule)
                if fact_id not in valid_fact_refs:
                    collector.violation(reference_rule, "FACT_VALUE_REFERENCE_INVALID", path + "/fact_id")
        else:
            collector.checked(shape_rule)
            collector.blocked(reference_rule, "value.reference_shape", "The value is not a complete closed fact_ref object.", path)
            collector.violation(shape_rule, "FACT_VALUE_SHAPE_INVALID", path)
    else:
        collector.checked(shape_rule)
        collector.blocked(reference_rule, "value.reference_shape", "A non-reference value has no fact-reference target to evaluate.", path)
        collector.violation(shape_rule, "FACT_VALUE_SHAPE_INVALID", path)


def _check_claims(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    claims = payload.get("claims")
    arrivals = payload.get("arrival_prose")
    group_rule = "S3-CLAIM-GROUPS-ORDER-LIMIT"
    segment_rule = "S3-CLAIM-SEGMENT-BINDING"
    claim_id_rule = "S3-CLAIM-ID-UNIQUE-BOUNDS"
    fields_rule = "S3-CLAIM-FIELDS"
    fact_ref_rule = "S3-CLAIM-FACT-REFERENCES"
    span_rule = "S3-CLAIM-SPANS"
    agency_rule = "S3-CLAIM-AGENCY"
    arrival_rule = "S3-ARRIVAL-ORDER-IDS-LIMITS"
    prose_rule = "S3-PROSE-AGENCY"

    claims_available = type(claims) is list
    arrivals_available = type(arrivals) is list
    facts, facts_reason = _facts_list(payload)
    if not claims_available:
        for rule_id in (group_rule, segment_rule, claim_id_rule, fields_rule, fact_ref_rule, span_rule, agency_rule):
            collector.blocked(rule_id, "claims[]", "The claims array is missing or invalid.", "/claims")
    else:
        collector.checked(group_rule)
        if len(claims) != 3:
            collector.violation(group_rule, "CLAIM_GROUP_COUNT_INVALID", "/claims")
    claim_items_complete = claims_available
    claim_item_count = 0
    if not arrivals_available:
        collector.blocked(arrival_rule, "arrival_prose[]", "The arrival_prose array is missing or invalid.", "/arrival_prose")
        collector.blocked(prose_rule, "arrival_prose[].text", "The public arrival text is unavailable.", "/arrival_prose")
    else:
        collector.checked(arrival_rule)
        if len(arrivals) != 3:
            collector.violation(arrival_rule, "ARRIVAL_SEGMENT_COUNT_INVALID", "/arrival_prose")

    segment_text: dict[int, str] = {}
    prose_complete = arrivals_available
    if arrivals_available:
        for index, segment in enumerate(arrivals):
            path = f"/arrival_prose/{index}"
            if index >= len(_ARRIVAL_ROLES):
                collector.violation(arrival_rule, "ARRIVAL_SEGMENT_COUNT_INVALID", path)
                continue
            role = _ARRIVAL_ROLES[index]
            if type(segment) is not dict:
                collector.blocked(arrival_rule, "arrival_prose.segment.object", "An arrival segment object is required.", path)
                prose_complete = False
                continue
            segment_id = segment.get("id")
            observed_role = segment.get("role")
            if type(segment_id) is not str or type(observed_role) is not str:
                collector.blocked(arrival_rule, "arrival_prose.id_and_role", "String id and role fields are required.", path)
                prose_complete = False
            else:
                collector.checked(arrival_rule)
                if segment_id != binding.scene_id + ":arrival:" + role or observed_role != role:
                    collector.violation(arrival_rule, "ARRIVAL_ROLE_BINDING_INVALID", path)
            text = segment.get("text")
            if type(text) is not str:
                collector.blocked(arrival_rule, "arrival_prose.text", "A string text field is required.", path + "/text")
                prose_complete = False
            else:
                collector.checked(arrival_rule)
                segment_text[index] = text
                if not 1 <= len(text) <= 512:
                    collector.violation(arrival_rule, "ARRIVAL_TEXT_LENGTH_INVALID", path + "/text")

    if claims_available:
        expected_segment_ids = [binding.scene_id + ":arrival:" + role for role in _ARRIVAL_ROLES]
        seen_claim_ids: set[str] = set()
        base_ids = set(binding.public_base_fact_ids)
        if facts is None:
            collector.blocked(fact_ref_rule, "fixture_deltas.facts[]", facts_reason, "/fixture_deltas/facts")
        else:
            for fact in facts:
                if type(fact) is dict and type(fact.get("fact_id")) is str:
                    fact_id = fact["fact_id"]
                    if re.fullmatch(binding.authored_fact_pattern, fact_id) is not None and len(fact_id) <= 256:
                        base_ids.add(fact_id)
        for group_index, group in enumerate(claims):
            group_path = f"/claims/{group_index}"
            if type(group) is not dict:
                claim_items_complete = False
                collector.blocked(group_rule, "claims.group.object", "A claim group object is required.", group_path)
                collector.blocked(segment_rule, "claims.group.segment_id", "A string group segment_id is required.", group_path + "/segment_id")
                collector.blocked(fields_rule, "claims.group.items[]", "Claim item fields depend on an object group.", group_path)
                continue
            segment_id = group.get("segment_id")
            if type(segment_id) is not str:
                collector.blocked(segment_rule, "claims.group.segment_id", "A string group segment_id is required.", group_path + "/segment_id")
            else:
                collector.checked(segment_rule)
                expected = expected_segment_ids[group_index] if group_index < len(expected_segment_ids) else ""
                if segment_id != expected:
                    collector.violation(segment_rule, "CLAIM_SEGMENT_BINDING_INVALID", group_path + "/segment_id")
            items = group.get("items")
            if type(items) is not list:
                claim_items_complete = False
                collector.blocked(group_rule, "claims.group.items[]", "The claim group items array is missing or invalid.", group_path + "/items")
                continue
            collector.checked(group_rule)
            claim_item_count += len(items)
            if len(items) > 32:
                collector.violation(group_rule, "CLAIM_GROUP_LIMIT_INVALID", group_path + "/items")
            for item_index, claim in enumerate(items):
                path = group_path + "/items/" + str(item_index)
                if type(claim) is not dict:
                    claim_items_complete = False
                    for rule_id in (fields_rule, claim_id_rule, fact_ref_rule, span_rule, agency_rule):
                        collector.blocked(rule_id, "claim.object", "A claim object is required.", path)
                    continue
                collector.checked(fields_rule)
                if set(claim) != set(_CLAIM_FIELDS):
                    collector.violation(fields_rule, "CLAIM_FIELDS_INVALID", path)

                claim_id = claim.get("id")
                id_path = path + "/id"
                if type(claim_id) is not str:
                    collector.blocked(claim_id_rule, "claim.id", "A string claim id is required.", id_path)
                else:
                    collector.checked(claim_id_rule)
                    if len(claim_id) > 512 or re.fullmatch(binding.claim_id_pattern, claim_id) is None:
                        collector.violation(claim_id_rule, "CLAIM_ID_INVALID", id_path)
                    if claim_id in seen_claim_ids:
                        collector.violation(claim_id_rule, "CLAIM_ID_DUPLICATE", id_path)
                    seen_claim_ids.add(claim_id)

                fact_id = claim.get("fact_id")
                fact_path = path + "/fact_id"
                if facts is None:
                    collector.blocked(fact_ref_rule, "fixture_deltas.facts[]", facts_reason, fact_path)
                elif type(fact_id) is not str:
                    collector.blocked(fact_ref_rule, "claim.fact_id", "A string fact reference is required.", fact_path)
                else:
                    collector.checked(fact_ref_rule)
                    if fact_id not in base_ids:
                        collector.violation(fact_ref_rule, "CLAIM_FACT_REFERENCE_INVALID", fact_path)

                span = claim.get("span")
                span_path = path + "/span"
                if type(span) is not str:
                    collector.blocked(span_rule, "claim.span", "A string claim span is required.", span_path)
                    prose_complete = False
                else:
                    collector.checked(span_rule)
                    if not 1 <= len(span) <= 512:
                        collector.violation(span_rule, "CLAIM_SPAN_INVALID", span_path)
                    if group_index not in segment_text:
                        collector.blocked(span_rule, "arrival_prose[].text", "Exact-substring validation requires the bound arrival segment text.", span_path)
                        prose_complete = False
                    elif span not in segment_text[group_index]:
                        collector.violation(span_rule, "CLAIM_SPAN_INVALID", span_path)

                kind = claim.get("kind")
                if kind == "invitation":
                    collector.checked(agency_rule)
                    if claim.get("choice") != "open" or claim.get("success") != "unspecified":
                        collector.violation(agency_rule, "INVITATION_AGENCY_INVALID", path)
                elif kind == "factual":
                    collector.checked(agency_rule)
                    if claim.get("choice") is not None or claim.get("success") is not None:
                        collector.violation(agency_rule, "FACTUAL_AGENCY_INVALID", path)
                elif "kind" in claim:
                    collector.checked(agency_rule)
                    collector.violation(agency_rule, "CLAIM_KIND_INVALID", path + "/kind")
                    collector.blocked(
                        agency_rule,
                        "claim.kind",
                        "Choice and success requirements depend on a supported claim kind.",
                        path + "/kind",
                    )
                else:
                    collector.blocked(agency_rule, "claim.kind", "The kind field is missing.", path + "/kind")

        if claim_items_complete and claim_item_count == 0:
            collector.checked(claim_id_rule, fields_rule, span_rule, agency_rule)
            if facts is not None:
                collector.checked(fact_ref_rule)

    if prose_complete:
        collector.checked(prose_rule)
        public_text: list[str] = list(segment_text.values())
        if claims_available:
            for group in claims:
                if type(group) is not dict or type(group.get("items")) is not list:
                    prose_complete = False
                    break
                for claim in group["items"]:
                    if type(claim) is not dict or type(claim.get("span")) is not str:
                        prose_complete = False
                        break
                    public_text.append(claim["span"])
        if prose_complete and any(pattern.search("\n".join(public_text)) for pattern in _AGENCY_PATTERNS):
            collector.violation(prose_rule, "PROSE_AGENCY_ASSERTION", "/arrival_prose")
        elif not prose_complete:
            collector.blocked(prose_rule, "public_claim_spans", "Agency scan requires all evaluated public text fields to be strings.", "/claims")
    else:
        collector.blocked(prose_rule, "public_claim_spans", "Agency scan requires all evaluated public text fields to be strings.", "/arrival_prose")


def _check_protected(
    collector: _Collector,
    payload: dict[str, Any],
    binding: contract.SceneBinding,
) -> None:
    unknown_rule = "S3-PROTECTED-UNKNOWNS"
    marker_rule = "S3-GUARDED-CONTENT-MARKERS"
    facts, facts_reason = _facts_list(payload)
    if facts is None:
        collector.blocked(unknown_rule, "fixture_deltas.facts[]", facts_reason, "/fixture_deltas/facts")
    else:
        if not facts:
            collector.checked(unknown_rule)
        unknown_map = {
            "sensory_gradients": frozenset(("light_gradient", "sound_gradient", "weather_gradient"))
        }
        for index, fact in enumerate(facts):
            path = f"/fixture_deltas/facts/{index}/predicate"
            if type(fact) is not dict or type(fact.get("predicate")) is not str:
                collector.blocked(unknown_rule, "fact.predicate", "A string predicate is required for protected-unknown checks.", path)
                continue
            collector.checked(unknown_rule)
            for unknown_name, predicates in unknown_map.items():
                if unknown_name in binding.unknown_predicates and fact["predicate"] in predicates:
                    collector.violation(unknown_rule, "PROTECTED_UNKNOWN_PROMOTION", path)

    public_strings: list[tuple[str, str]] = []
    public_complete = True
    if facts is not None:
        for index, fact in enumerate(facts):
            if type(fact) is not dict:
                public_complete = False
                continue
            value = fact.get("value")
            if type(value) is str:
                public_strings.append((value, f"/fixture_deltas/facts/{index}/value"))
            elif value is None or type(value) in (bool, int, float, list, dict):
                continue
            else:
                public_complete = False
    arrivals = payload.get("arrival_prose")
    if type(arrivals) is list:
        for index, segment in enumerate(arrivals):
            if type(segment) is dict and type(segment.get("text")) is str:
                public_strings.append((segment["text"], f"/arrival_prose/{index}/text"))
            else:
                public_complete = False
    else:
        public_complete = False
    claims = payload.get("claims")
    if type(claims) is list:
        for group_index, group in enumerate(claims):
            if type(group) is not dict or type(group.get("items")) is not list:
                public_complete = False
                continue
            for item_index, claim in enumerate(group["items"]):
                if type(claim) is dict and type(claim.get("span")) is str:
                    public_strings.append((claim["span"], f"/claims/{group_index}/items/{item_index}/span"))
                else:
                    public_complete = False
    else:
        public_complete = False

    if not public_complete:
        collector.blocked(marker_rule, "public_delta_text", "Guarded-marker scan requires structurally available public text fields.", "/")
    else:
        collector.checked(marker_rule)
        for marker in binding.guarded_markers:
            if type(marker) is not str or not marker:
                continue
            for text, path in public_strings:
                if marker in text:
                    collector.violation(marker_rule, "GUARDED_MARKER_IN_PUBLIC_DELTA", path)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate object key")
        result[key] = value
    return result


class _DuplicateKey(ValueError):
    pass


class _NonFinite(ValueError):
    pass


def _reject_nonfinite_constant(value: str) -> None:
    raise _NonFinite("non-finite number")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _NonFinite("non-finite number")
    return number


def _source_pointers(rule: contract.RuleSpec) -> list[str]:
    return [source.artifact + "#" + source.pointer for source in rule.sources]


def _safe_metadata(value: str, max_length: int) -> str:
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:[]-"
    result = "".join(character for character in value if character in allowed)
    return result[:max_length]


def _path_from_parts(parts: object) -> str:
    if isinstance(parts, (str, bytes)):
        return ""
    try:
        part_values = tuple(parts)
    except TypeError:
        return ""
    encoded: list[str] = []
    for part in part_values[:12]:
        if type(part) is int and part >= 0:
            token = str(part)
        elif type(part) is str and part in _KNOWN_PATH_TOKENS:
            token = part
        else:
            token = "<unknown-key>"
        token = token.replace("~", "~0").replace("/", "~1")
        encoded.append(token)
    return _bounded_pointer("/" + "/".join(encoded) if encoded else "/")


def _bounded_pointer(path: str) -> str:
    if type(path) is not str:
        return ""
    if path == "/":
        return "/"
    parts = path.split("/")
    safe: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            safe.append(part[:8])
            continue
        if part in _KNOWN_PATH_TOKENS or part in ("<unknown-key>", "<unavailable>"):
            safe.append(part)
        else:
            safe.append("<unknown-key>")
    return ("/" + "/".join(safe))[:160] if safe else ""


def _safe_read_project_file(relative_path: str, root: Path) -> bytes:
    pure = PurePosixPath(relative_path)
    if (
        type(relative_path) is not str
        or not relative_path
        or "\\" in relative_path
        or pure.is_absolute()
        or pure.as_posix() != relative_path
        or any(part in ("", ".", "..") for part in relative_path.split("/"))
    ):
        raise ValueError("PROJECT_PATH_REJECTED")
    resolved_root = root.resolve(strict=True)
    current = resolved_root
    try:
        for part in pure.parts:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError("PROJECT_PATH_REJECTED")
        resolved = current.resolve(strict=True)
        resolved.relative_to(resolved_root)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError("PROJECT_FILE_INVALID")
        return resolved.read_bytes()
    except ValueError:
        raise
    except (OSError, RuntimeError):
        raise ValueError("PROJECT_FILE_UNAVAILABLE") from None


def _ensure_project_directory(relative_path: str, root: Path) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or pure.as_posix() != relative_path or any(part in ("", ".", "..") for part in relative_path.split("/")):
        raise ValueError("PROJECT_PATH_REJECTED")
    resolved_root = root.resolve(strict=True)
    current = resolved_root
    for part in pure.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if stat.S_ISLNK(current.lstat().st_mode) or not current.is_dir():
                raise ValueError("PROJECT_PATH_REJECTED")
        else:
            current.mkdir()
    resolved = current.resolve(strict=True)
    resolved.relative_to(resolved_root)
    return resolved


def run_study2_collect_all(*, report_filename: str = "collect-all-report.json") -> dict[str, Any]:
    """Diagnose only the three fixed, labeled, byte-preserving Study 2 copies.

    Existing copies are read only. Missing copies are made once from the fixed
    authorized source paths; an existing mismatched copy is never overwritten.
    The only generated file is the metadata-only report in the approved prep tree.
    """

    root = protocol.REPO_ROOT
    if re.fullmatch(r"[a-z0-9-]+\.json", report_filename) is None:
        raise ValueError("DIAGNOSTIC_REPORT_NAME_REJECTED")
    run_relative = DIAGNOSTIC_ROOT_RELATIVE + "/collect-all-" + STUDY2_RUN_ID
    copy_dir_relative = STUDY2_COPY_RELATIVE
    run_dir = _ensure_project_directory(run_relative, root)
    copy_dir = _ensure_project_directory(copy_dir_relative, root)
    report_relative = run_relative + "/" + report_filename
    report_path = root / report_relative
    if report_path.exists() or report_path.is_symlink():
        raise ValueError("DIAGNOSTIC_REPORT_ALREADY_EXISTS")

    copies: list[dict[str, Any]] = []
    for index, filename in enumerate(STUDY2_FILENAMES):
        source_relative = STUDY2_SOURCE_RELATIVE + "/" + filename
        copy_relative = STUDY2_COPY_RELATIVE + "/" + filename
        source_bytes = _safe_read_project_file(source_relative, root)
        copy_file = copy_dir / filename
        if copy_file.exists() or copy_file.is_symlink():
            copy_bytes = _safe_read_project_file(copy_relative, root)
            if copy_bytes != source_bytes:
                raise ValueError("EXISTING_DIAGNOSTIC_COPY_MISMATCH")
        else:
            copy_file.write_bytes(source_bytes)
            copy_bytes = _safe_read_project_file(copy_relative, root)
        if copy_bytes != source_bytes:
            raise ValueError("DIAGNOSTIC_COPY_NOT_BYTE_IDENTICAL")

        copies.append(
            {
                "scene_id": protocol.SCENE_ORDER[index],
                "source_path": source_relative,
                "copy_path": copy_relative,
                "source_bytes_before": len(source_bytes),
                "source_sha256_before": hashlib.sha256(source_bytes).hexdigest(),
                "copy_bytes_before": len(copy_bytes),
                "copy_sha256_before": hashlib.sha256(copy_bytes).hexdigest(),
                "byte_identical_before": True,
                "_copy_bytes": copy_bytes,
            }
        )

    delta_reports: list[dict[str, Any]] = []
    for copy in copies:
        delta_reports.append(
            _diagnose_delta_bytes(
                copy["_copy_bytes"],
                scene_id=copy["scene_id"],
                source_name=Path(copy["copy_path"]).name,
                copy_path_checked=True,
            )
        )

    copy_integrity: list[dict[str, Any]] = []
    originals_unchanged = True
    copies_unchanged = True
    for copy in copies:
        source_after = _safe_read_project_file(copy["source_path"], root)
        copy_after = _safe_read_project_file(copy["copy_path"], root)
        source_same = (
            len(source_after) == copy["source_bytes_before"]
            and hashlib.sha256(source_after).hexdigest() == copy["source_sha256_before"]
        )
        copy_same = (
            len(copy_after) == copy["copy_bytes_before"]
            and hashlib.sha256(copy_after).hexdigest() == copy["copy_sha256_before"]
            and copy_after == copy["_copy_bytes"]
        )
        originals_unchanged = originals_unchanged and source_same
        copies_unchanged = copies_unchanged and copy_same
        copy_integrity.append(
            {
                "source_path": copy["source_path"],
                "copy_path": copy["copy_path"],
                "source_bytes_before": copy["source_bytes_before"],
                "source_sha256_before": copy["source_sha256_before"],
                "source_bytes_after": len(source_after),
                "source_sha256_after": hashlib.sha256(source_after).hexdigest(),
                "copy_bytes_before": copy["copy_bytes_before"],
                "copy_sha256_before": copy["copy_sha256_before"],
                "copy_bytes_after": len(copy_after),
                "copy_sha256_after": hashlib.sha256(copy_after).hexdigest(),
                "source_unchanged": source_same,
                "copy_unchanged": copy_same,
                "status": "PASS" if source_same and copy_same else "BLOCKED",
            }
        )

    report = {
        "label": DIAGNOSTIC_LABEL,
        "result_kind": "metadata_only_cross_protocol_diagnostic",
        "diagnostic_run_id": "collect-all-" + STUDY2_RUN_ID,
        "study2_frozen_verdict_changed": False,
        "study3_result": False,
        "finite_examples_prove_no_hidden_rule": False,
        "rule_inventory_counts": {
            "output_contract_rules": len(contract.OUTPUT_RULE_MAP),
            "host_safety_integrity_rules": len(contract.HOST_RULE_MAP),
            "total_rules": len(contract.OUTPUT_RULE_MAP) + len(contract.HOST_RULE_MAP),
        },
        "diagnostic_integrity": {
            "status": "BLOCKED"
            if any(delta["diagnostic_integrity"]["status"] == "BLOCKED" for delta in delta_reports)
            else "PASS",
            "blocked_unmapped_rule_failures": [
                {
                    "scene_id": delta["scene_id"],
                    "source_copy_name": delta["source_copy_name"],
                    **failure,
                }
                for delta in delta_reports
                for failure in delta["diagnostic_integrity"]["blocked_unmapped_rule_failures"]
            ],
        },
        "downstream_pipeline": {
            "hydration": {
                "status": "NOT_EVALUATED",
                "dependency": "task_2_2_study3_hydration_not_implemented",
            },
            "full_unchanged_safety_gates": {
                "status": "NOT_EVALUATED",
                "dependency": "task_2_2_hydration_and_downstream_gate_chain",
            },
        },
        "source_files": [
            {key: value for key, value in row.items() if key != "_copy_bytes"}
            for row in copies
        ],
        "copy_integrity": copy_integrity,
        "originals_unchanged": originals_unchanged,
        "copies_unchanged": copies_unchanged,
        "overall_copy_integrity": "PASS" if originals_unchanged and copies_unchanged else "BLOCKED",
        "rule_inventory": _inventory_rows(delta_reports[0]["rule_coverage"] if delta_reports else []),
        "deltas": delta_reports,
    }
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n"
    report_path.write_text(serialized, encoding="utf-8")
    return report


def _inventory_rows(coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": row["rule_id"],
            "category": row["category"],
            "check_id": row["check_id"],
            "source_pointers": row["source_pointers"],
        }
        for row in coverage
    ]


__all__ = [
    "DIAGNOSTIC_LABEL",
    "DIAGNOSTIC_ROOT_RELATIVE",
    "diagnose_delta_bytes",
    "run_study2_collect_all",
]
