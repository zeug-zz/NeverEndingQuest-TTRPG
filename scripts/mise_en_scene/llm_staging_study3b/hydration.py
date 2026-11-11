# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3b hydration adapter with complete per-scene inventory parity checks."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from ..llm_staging_study2 import hydration as study2_hydration
from . import contract as study3b_contract
from .inventory import (
    FactInventoryError,
    SceneFactInventory,
    _assert_inventory_matches_canonical,
    _to_plain,
    load_scene_inventory,
)
from .study3_compat import contract as study3_contract


ContractError = study3_contract.ContractError


def hydrate_delta_output(output_bytes: object, *, scene_id: str) -> dict[str, Any]:
    """Validate, hydrate in memory through Study 2, and enforce inventory parity."""

    try:
        inventory = load_scene_inventory(scene_id)
        validated = study3b_contract.validate_delta_payload(
            output_bytes, scene_id=scene_id, inventory=inventory
        )
        canonical = study2_hydration._load_canonical_inputs(scene_id)
    except FactInventoryError as error:
        raise ContractError(
            error.code, "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts"
        ) from None

    if (
        canonical.scene_id != inventory.scene_id
        or canonical.source_packet_id
        != inventory.source_binding["input_refs"]["source_packet"]["id"]
        or canonical.source_packet_sha256
        != inventory.source_binding["input_refs"]["source_packet"]["sha256"]
        or canonical.expected_bundle_id
        != inventory.source_binding["expected_bundle_path"]
        or canonical.expected_bundle_sha256
        != inventory.source_binding["expected_bundle_sha256"]
    ):
        raise ContractError(
            "STUDY3B_HYDRATION_SOURCE_BINDING_MISMATCH",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/source_facts",
        )

    expected_authored_fact_ids = _projected_authored_fact_ids(
        validated, inventory.module_id
    )
    try:
        hydrated = study2_hydration._hydrate_validated_delta(validated, canonical)
    except study2_hydration.ContractError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, RecursionError):
        raise ContractError(
            "STUDY3B_HYDRATION_SHAPE_INVALID", "HOST-CANONICAL-HASH-INTEGRITY", "$output"
        ) from None
    _remove_nonclaimable_source_facts(hydrated, inventory)
    audit_hydrated_inventory_parity(
        scene_id,
        hydrated,
        inventory=inventory,
        expected_authored_fact_ids=expected_authored_fact_ids,
    )
    return hydrated


def audit_hydrated_inventory_parity(
    scene_id: str,
    hydrated: object,
    *,
    inventory: SceneFactInventory | None = None,
    expected_authored_fact_ids: frozenset[str],
) -> None:
    """Reject any missing, extra, or changed canonical source fact projection."""

    if inventory is None:
        try:
            inventory = load_scene_inventory(scene_id)
        except FactInventoryError as error:
            raise ContractError(
                error.code, "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts"
            ) from None
    try:
        _assert_inventory_matches_canonical(inventory)
    except FactInventoryError as error:
        raise ContractError(
            error.code, "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts"
        ) from None
    if inventory.scene_id != scene_id:
        _reject("STUDY3B_HYDRATION_IDENTITY_MISMATCH", "/scene_id")
    if type(hydrated) is not dict:
        _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "$output")

    if (
        hydrated.get("scene_id") != inventory.scene_id
        or hydrated.get("schema") != "neq.llm_staging_output.v1"
    ):
        _reject("STUDY3B_HYDRATION_IDENTITY_MISMATCH", "/scene_id")
    fixture = hydrated.get("fixture")
    arrival = hydrated.get("arrival")
    if type(fixture) is not dict or type(arrival) is not dict:
        _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "$output")
    scene = fixture.get("scene")
    if type(scene) is not dict:
        _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "/fixture/scene")
    if (
        fixture.get("module_id") != inventory.module_id
        or scene.get("id") != inventory.scene_id
        or arrival.get("fixture_id") != inventory.scene_id
    ):
        _reject("STUDY3B_HYDRATION_IDENTITY_MISMATCH", "/fixture")

    extension = fixture.get("extension_seams")
    audience_rows = extension.get("audience_knowledge") if type(extension) is dict else None
    if type(audience_rows) is not list:
        _reject("STUDY3B_HYDRATION_RECORDS_MISSING", "/fixture/extension_seams/audience_knowledge")
    expected_audience_rows = [
        _record.to_audience_knowledge_record() for _record in inventory.records
    ]
    _require_equal(
        audience_rows,
        expected_audience_rows,
        "STUDY3B_HYDRATION_RECORD_PARITY_FAILED",
        "/fixture/extension_seams/audience_knowledge",
    )
    _require_equal(
        extension.get("unknown_metrics"),
        [_to_plain(row) for row in inventory.protected_unknowns],
        "STUDY3B_PROTECTED_UNKNOWN_STATE_CHANGED",
        "/fixture/extension_seams/unknown_metrics",
    )

    facts = fixture.get("facts")
    if type(facts) is not list:
        _reject("STUDY3B_HYDRATION_RECORDS_MISSING", "/fixture/facts")
    facts_by_id: dict[str, object] = {}
    for fact in facts:
        if type(fact) is not dict or type(fact.get("id")) is not str:
            _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "/fixture/facts")
        fact_id = fact["id"]
        if fact_id in facts_by_id:
            _reject("STUDY3B_HYDRATION_RECORD_PARITY_FAILED", "/fixture/facts")
        facts_by_id[fact_id] = fact
    source_fact_ids = {record.fact_id for record in inventory.records}
    expected_source_fact_ids = set(inventory.claim_reference_ids)
    observed_source_fact_ids = set(facts_by_id) & source_fact_ids
    if observed_source_fact_ids != expected_source_fact_ids:
        if observed_source_fact_ids - expected_source_fact_ids:
            _reject("STUDY3B_FACT_NOT_CLAIM_ELIGIBLE", "/fixture/facts")
        _reject("STUDY3B_HYDRATION_RECORDS_MISSING", "/fixture/facts")
    if type(expected_authored_fact_ids) is not frozenset or any(
        type(fact_id) is not str for fact_id in expected_authored_fact_ids
    ):
        _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "/fixture/facts")
    if set(facts_by_id) != expected_source_fact_ids | set(
        expected_authored_fact_ids
    ):
        _reject("STUDY3B_HYDRATION_RECORD_PARITY_FAILED", "/fixture/facts")
    for record in inventory.records:
        expected_fact = record.to_fixture_source_fact(inventory.scene_node_id)
        observed_fact = facts_by_id.get(record.fact_id)
        if expected_fact is None:
            if observed_fact is not None:
                _reject("STUDY3B_FACT_NOT_MATERIALIZABLE", "/fixture/facts")
            continue
        _require_equal(
            observed_fact,
            expected_fact,
            "STUDY3B_HYDRATION_RECORD_PARITY_FAILED",
            "/fixture/facts/" + record.fact_id,
        )

    source_facts = _source_facts(inventory)
    source_packet_path = inventory.source_binding["source_packet_path"]
    expected_provenance = {
        "source_ref": source_facts["source_reference"],
        "path": source_facts["source_file"],
        "section": source_packet_path.rsplit("/", 1)[-1].removesuffix(".json"),
        "sha256": source_facts["source_file_sha256"],
        "source_kind": "published_module",
        "legacy_truth_verified": False,
    }
    _require_equal(
        arrival.get("source_provenance"),
        expected_provenance,
        "STUDY3B_HYDRATION_SOURCE_BINDING_MISMATCH",
        "/arrival/source_provenance",
    )
    _require_equal(
        scene.get("orientation"),
        _unknown_orientation(),
        "STUDY3B_PROTECTED_UNKNOWN_STATE_CHANGED",
        "/fixture/scene/orientation",
    )
    _require_equal(
        arrival.get("orientation"),
        _unknown_orientation(),
        "STUDY3B_PROTECTED_UNKNOWN_STATE_CHANGED",
        "/arrival/orientation",
    )
    _require_equal(
        arrival.get("cue_states"),
        _unknown_cue_states(),
        "STUDY3B_PROTECTED_UNKNOWN_STATE_CHANGED",
        "/arrival/cue_states",
    )
    _require_equal(
        arrival.get("next_section"),
        _unknown_next_section(),
        "STUDY3B_PROTECTED_UNKNOWN_STATE_CHANGED",
        "/arrival/next_section",
    )


def _source_facts(inventory: SceneFactInventory) -> Mapping[str, Any]:
    """Read source provenance bound into the inventory fingerprint."""

    return {
        "source_reference": inventory.source_binding["source_reference"],
        "source_file": inventory.source_binding["source_file"],
        "source_file_sha256": inventory.source_binding["source_file_sha256"],
    }


def _remove_nonclaimable_source_facts(
    hydrated: dict[str, Any], inventory: SceneFactInventory
) -> None:
    """Keep non-public source rows out of the shared fixture fact table."""

    fixture = hydrated.get("fixture")
    facts = fixture.get("facts") if type(fixture) is dict else None
    if type(facts) is not list:
        _reject("STUDY3B_HYDRATION_RECORDS_MISSING", "/fixture/facts")
    source_ids = {record.fact_id for record in inventory.records}
    eligible_ids = set(inventory.claim_reference_ids)
    fixture["facts"] = [
        fact
        for fact in facts
        if not (
            type(fact) is dict
            and fact.get("id") in source_ids
            and fact.get("id") not in eligible_ids
        )
    ]


def _projected_authored_fact_ids(
    validated: Mapping[str, Any], module_id: str
) -> frozenset[str]:
    fixture_deltas = validated.get("fixture_deltas")
    facts = fixture_deltas.get("facts") if isinstance(fixture_deltas, Mapping) else None
    if type(facts) is not tuple:
        _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "/fixture_deltas/facts")
    projected_ids: set[str] = set()
    for fact in facts:
        fact_id = fact.get("fact_id") if isinstance(fact, Mapping) else None
        if type(fact_id) is not str:
            _reject("STUDY3B_HYDRATION_SHAPE_INVALID", "/fixture_deltas/facts")
        digest = hashlib.sha256(fact_id.encode("utf-8")).hexdigest()[:61]
        projected_ids.add(module_id + ":fact:s2-" + digest)
    return frozenset(projected_ids)


def _unknown_orientation() -> dict[str, Any]:
    return {
        "status": "unknown",
        "frame": None,
        "provenance": {"class": "unknown", "source_refs": []},
    }


def _unknown_cue_states() -> list[dict[str, Any]]:
    return [
        {
            "cue": cue,
            "status": "unknown",
            "fact_id": None,
            "reason": "No independent gradient fact is supplied.",
        }
        for cue in ("light", "sound", "weather")
    ]


def _unknown_next_section() -> dict[str, Any]:
    return {
        "status": "unknown",
        "from_scene_id": None,
        "to_scene_id": None,
        "transition_fact_id": None,
        "perception_fact_id": None,
        "provenance": {"class": "unknown", "source_refs": []},
        "reason": "No independently approved transition is supplied.",
    }


def _require_equal(
    observed: object, expected: object, code: str, path: str
) -> None:
    if not _same_json_value(observed, expected):
        _reject(code, path)


def _same_json_value(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


def _reject(code: str, path: str) -> None:
    raise ContractError(code, "HOST-CANONICAL-HASH-INTEGRITY", path)


__all__ = ["audit_hydrated_inventory_parity", "hydrate_delta_output"]
