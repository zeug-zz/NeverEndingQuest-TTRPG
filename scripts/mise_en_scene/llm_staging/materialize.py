# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

#!/usr/bin/env python3
"""Materialize the frozen, source-bound inputs for the LLM staging study."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
STAGING_ROOT = REPO_ROOT / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging"
SCENE_SOURCE_MANIFEST = STAGING_ROOT / "scenes.json"
PROTOCOL_PATH = REPO_ROOT / "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.md"
PROTOCOL_DIR = PROTOCOL_PATH.parent
FROZEN_ROOT = PROTOCOL_DIR
SCENE_SOURCE_MANIFEST = FROZEN_ROOT / "scenes.json"
AVAILABILITY_NOTE = FROZEN_ROOT / "availability-check-20261108.json"
CURRENT_AVAILABILITY_NOTE = FROZEN_ROOT / "availability-check.json"

APPROVED_SCENES = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)

_PUBLIC_FIELDS = {
    "locationId", "name", "type", "description", "aliases", "features", "npcs",
}
_GM_FIELDS = {
    "monsters", "doors", "traps", "encounters", "dmInstructions", "dcChecks",
    "plotHooks", "lootTable", "accessibility", "adventureSummary",
}
_SCHEMATIC_FIELDS = {"coordinates", "tactical_grid"}
_LOCATION_FACT_FIELDS = (
    "locationId", "name", "type", "description", "coordinates", "connectivity",
    "areaConnectivity", "areaConnectivityId", "aliases", "tactical_grid", "npcs",
    "monsters", "lootTable", "plotHooks", "dmInstructions", "doors", "traps",
    "dcChecks", "accessibility", "dangerLevel", "features", "encounters",
    "adventureSummary",
)
_ROOM_FACT_FIELDS = (
    "id", "type", "connections", "coordinates", "directions", "tags", "purpose",
    "landmark", "dangerLevel", "name",
)
_SOURCE_UNKNOWN_CATEGORIES = (
    ("interior_compass_bearings", "No selected source field establishes compass bearings within the room."),
    ("metric_distance_and_scale", "Room coordinates and tactical-grid labels are schematic and establish no metric."),
    ("access_beyond_explicit_records", "Connections do not establish a door, access, or traversability; use only explicit source door/access facts."),
    ("visibility_and_sensory_range", "The selected source packet does not establish range, line of sight, audibility, or sensory reach."),
    ("sensory_gradients", "Ambient description does not by itself establish a light, sound, or weather gradient."),
    ("movement_cost_and_legality", "This study makes no movement-cost or mechanical-legality ruling."),
    ("prior_runtime_party", "Prior-play PCs and their positions are not supplied and must not be authored."),
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _source_ref(source_file: str, pointer: str) -> str:
    lowered = source_file.lower()
    pointer_slug = _slug(pointer.replace("/", "-"))
    return "source:" + lowered.replace("_bu.json", "") + "/" + pointer_slug


def _audience(field: str) -> str:
    if field in _GM_FIELDS:
        return "gm_guarded"
    if field in _SCHEMATIC_FIELDS:
        return "schematic_reference_only"
    if field in _PUBLIC_FIELDS:
        return "public_candidate_subject_to_semantic_review"
    return "source_reference_only"


def _make_fact(
    module_id: str,
    scene_local: str,
    source_file: str,
    pointer: str,
    value: Any,
    audience: str,
) -> dict[str, Any]:
    pointer_hash = hashlib.sha256(pointer.encode("utf-8")).hexdigest()[:12]
    local = _slug(scene_local)[:32] + "-" + pointer_hash
    return {
        "fact_id": module_id + ":fact:" + local,
        "source_pointer": source_file + "#" + pointer,
        "source_ref": _source_ref(source_file, scene_local + "/" + pointer),
        "status": "source_extracted",
        "value": value,
        "audience": audience,
    }


def _scene_entities(scene: dict[str, Any], location: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    module_id = scene["scene_id"].split(":", 1)[0]
    fixed: list[dict[str, str]] = []
    mobile: list[dict[str, str]] = []
    for field in ("features", "doors"):
        values = location.get(field, [])
        if type(values) is list:
            for index, item in enumerate(values):
                name = item.get("name") if type(item) is dict else None
                if type(name) is str and name:
                    fixed.append({"id": module_id + ":entity:" + _slug(name), "kind": field[:-1]})
                elif field == "features" and type(item) is dict:
                    fixed.append({"id": module_id + ":entity:feature-" + str(index + 1), "kind": "feature"})
    for field in ("npcs", "monsters"):
        values = location.get(field, [])
        if type(values) is list:
            for index, item in enumerate(values):
                name = item.get("name") if type(item) is dict else None
                if type(name) is str and name:
                    mobile.append({"id": module_id + ":entity:" + _slug(name), "kind": field[:-1]})
                elif type(item) is dict:
                    mobile.append({"id": module_id + ":entity:" + field[:-1] + "-" + str(index + 1), "kind": field[:-1]})
    if "circular sigil" in str(location.get("description", "")).lower():
        fixed.append({"id": module_id + ":entity:circular-sigil", "kind": "feature"})
    return _dedupe_entities(fixed), _dedupe_entities(mobile)


def _dedupe_entities(values: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if item["id"] not in seen:
            result.append(item)
            seen.add(item["id"])
    return result


def _candidate_focal_ids(scene: dict[str, Any], location: dict[str, Any], module_id: str) -> list[str]:
    if scene["location_id"] == "I02":
        return [module_id + ":entity:trapped-miner-derval", module_id + ":entity:runic-pleas"]
    if scene["location_id"] == "I03":
        return [module_id + ":entity:cracked-dais", module_id + ":entity:banners"]
    return [module_id + ":entity:grand-archway", module_id + ":entity:circular-sigil"]


def _guarded_markers(location: dict[str, Any]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []

    def collect(value: Any, pointer: str, field: str) -> None:
        if type(value) is str:
            if value:
                if len(value) > 4096:
                    raise ValueError("guarded marker exceeds the validator limit: " + field)
                markers.append({
                    "source_field": field,
                    "source_pointer": pointer,
                    "marker_id": field + "-" + str(len(markers) + 1),
                    "exact_value": value,
                })
            return
        if type(value) is dict:
            for key in sorted(value):
                collect(value[key], pointer + "." + str(key), field)
        elif type(value) is list:
            for index, child in enumerate(value):
                collect(child, pointer + "[" + str(index) + "]", field)

    for field in sorted(_GM_FIELDS):
        if field in location:
            collect(location[field], "locations[locationId=" + str(location.get("locationId")) + "]." + field, field)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in markers:
        key = (item["source_field"], item["exact_value"])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    if len(unique) > 32:
        raise ValueError("guarded content exceeds the exact-marker validator limit")
    for index, item in enumerate(unique, start=1):
        item["marker_id"] = item["source_field"] + "-" + str(index)
    return unique


def _make_scene_artifacts(
    scene: dict[str, Any], source_file: str, source_raw: bytes, source: dict[str, Any]
) -> dict[str, Any]:
    module_id, _separator, scene_local = scene["scene_id"].partition(":scene:")
    location = next(row for row in source["locations"] if row.get("locationId") == scene["location_id"])
    room = next(row for row in source["map"]["rooms"] if row.get("id") == scene["location_id"])
    packet = {"location": location, "map_room": room}
    packet_bytes = _canonical_bytes(packet)
    actual_source_hash = _sha256_bytes(source_raw)
    actual_packet_hash = _sha256_bytes(packet_bytes)
    if actual_source_hash != scene["source_file_sha256"]:
        raise ValueError("source file hash mismatch for " + scene["scene_id"])
    if actual_packet_hash != scene["source_packet_sha256"]:
        raise ValueError("canonical source packet hash mismatch for " + scene["scene_id"])

    scene_key = scene["scene_id"].replace(":", "__")
    packet_path = PROTOCOL_DIR / "source-packets" / (scene_key + ".json")
    _write(packet_path, packet_bytes)

    facts: list[dict[str, Any]] = []
    for field in _LOCATION_FACT_FIELDS:
        if field in location:
            facts.append(_make_fact(
                module_id, scene_local, source_file, "locations[locationId=" + scene["location_id"] + "]." + field,
                location[field], _audience(field),
            ))
    for field in _ROOM_FACT_FIELDS:
        if field in room:
            facts.append(_make_fact(
                module_id, scene_local, source_file, "map.rooms[id=" + scene["location_id"] + "]." + field,
                room[field], "public_candidate_subject_to_semantic_review" if field not in ("coordinates",) else "schematic_reference_only",
            ))

    source_facts = {
        "schema": "neq.llm_staging_source_facts.v1",
        "scene_id": scene["scene_id"],
        "source_identity": scene["source_identity"],
        "source_reference": scene["source_reference"],
        "source_file": source_file,
        "source_file_sha256": actual_source_hash,
        "source_packet_sha256": actual_packet_hash,
        "source_packet_path": str(packet_path.relative_to(REPO_ROOT)),
        "facts": facts,
        "guarded_content_markers": _guarded_markers(location),
    }

    fixed_entities, mobile_entities = _scene_entities(scene, location)
    scene_entity_id = module_id + ":entity:location-" + scene["location_id"].lower()
    neighbor_ids = [module_id + ":entity:room-" + str(value).lower() for value in room.get("connections", [])]
    if not neighbor_ids:
        raise ValueError("approved scene has no explicit map-connected approach candidate: " + scene["scene_id"])
    usable_space_id = module_id + ":entity:usable-space-" + scene["location_id"].lower()
    stage_focal_ids = [
        candidate for candidate in _candidate_focal_ids(scene, location, module_id)
        if candidate in {item["id"] for item in fixed_entities}
    ]
    if not stage_focal_ids:
        raise ValueError("approved topology has no fixed focal anchor candidate: " + scene["scene_id"])
    fixed_anchor_ids = [scene_entity_id, *neighbor_ids, *[item["id"] for item in fixed_entities], usable_space_id]
    source_nodes = [
        {"id": scene_entity_id, "kind": "threshold", "source_ref": scene["source_reference"]},
    ]
    source_nodes.extend(
        {"id": neighbor_id, "kind": "approach", "source_ref": scene["source_reference"], "source_status": "connected_room_id_only"}
        for neighbor_id in neighbor_ids
    )
    source_nodes.extend(
        {"id": item["id"], "kind": item["kind"], "source_ref": scene["source_reference"]}
        for item in fixed_entities + mobile_entities if item["id"] != scene_entity_id
    )
    source_nodes.append({
        "id": usable_space_id,
        "kind": "usable_space",
        "source_status": "builder_authored_role_slot_not_a_source_entity",
        "source_ref": None,
    })
    topology = {
        "schema": "neq.llm_staging_approved_topology.v1",
        "scene_id": scene["scene_id"],
        "module_id": module_id,
        "topology_id": module_id + ":topology:" + _slug(scene["location_id"]),
        "scope_id": module_id + ":scope:" + _slug(scene["area_id"]),
        "compass_frames": [],
        "scene_node_id": scene_entity_id,
        "nodes": source_nodes,
        "source_connections": [
            {"from": scene_entity_id, "to": neighbor_id, "relation": "map_connected", "source_ref": scene["source_reference"]}
            for neighbor_id in neighbor_ids
        ],
        "explicit_map_directions": [
            {"from": scene_entity_id, "direction": direction, "to": module_id + ":entity:room-" + str(target).lower(), "source_ref": scene["source_reference"]}
            for direction, target in sorted(room.get("directions", {}).items())
        ],
        "internal_layout_edges": [],
        "fixed_anchor_ids": fixed_anchor_ids,
        "mobile_occupant_ids": [item["id"] for item in mobile_entities],
        "stage_role_bindings": {
            "approach": neighbor_ids,
            "threshold": [scene_entity_id],
            "focal_anchor": stage_focal_ids,
            "usable_space": [usable_space_id],
        },
        "stage_role_entity_kinds": {
            "approach": "approach",
            "threshold": "threshold",
            "focal_anchor": "focal_anchor",
            "usable_space": "usable_space",
        },
        "builder_authored_role_slots": [
            {"id": usable_space_id, "role": "usable_space", "scope": "schematic only; no metric extent"}
        ],
        "builder_authored_relation_policy": {
            "approach_to_threshold": "required staging claim; must use listed nodes and be marked builder_authored unless directly source-supported",
            "threshold_to_focal": "required staging claim; must use listed nodes and be marked builder_authored unless directly source-supported",
            "may_add_nodes_or_source_connections": False,
            "coordinates_are_metric_or_compass_evidence": False,
        },
    }

    focal_ids = stage_focal_ids
    first_approach_id = neighbor_ids[0]
    first_focal_id = next((candidate for candidate in focal_ids if candidate in {item["id"] for item in fixed_entities}), None)
    if first_focal_id is None:
        raise ValueError("approved topology has no focal anchor candidate: " + scene["scene_id"])
    coverage = {
        "schema_version": 1,
        "stage_relations": {
            "approach_to_threshold": {
                "status": "required",
                "from_id": first_approach_id,
                "to_id": scene_entity_id,
            },
            "threshold_to_focal": {
                "status": "required",
                "from_id": scene_entity_id,
                "to_id": first_focal_id,
            },
        },
        "extents": {
            "path": [{"id": "scene_path", "status": "not_applicable", "reason": "The selected packet establishes no multi-cell path extent; a map connection alone has no internal path or traversal semantics."}],
            "terrain": [{"id": "scene_terrain", "status": "not_applicable", "reason": "The selected packet lists features but establishes no multi-cell terrain placement or extent."}],
            "boundary": [{"id": "scene_boundary", "status": "not_applicable", "reason": "The selected packet establishes no multi-cell boundary or schematic extent."}],
        },
        "usable_spaces": [{
            "id": "scene_usable_space",
            "entity_id": usable_space_id,
            "status": "required",
            "schematic_cells": [[0, 0]],
        }],
    }

    unknowns = {
        "schema": "neq.llm_staging_protected_unknowns.v1",
        "scene_id": scene["scene_id"],
        "unknowns": [
            {"predicate": predicate, "status": "unknown", "reason": reason}
            for predicate, reason in _SOURCE_UNKNOWN_CATEGORIES
        ] + [
            {"predicate": "public_paraphrase_of_guarded_content", "status": "unknown", "reason": "Exact marker scans do not detect semantic paraphrases; Overseer semantic review is mandatory."},
            {"predicate": "linked_view_or_frontage", "status": "not_tested", "reason": "The approved sample has no linked-view/frontage test."},
        ],
        "guarded_content_markers": source_facts["guarded_content_markers"],
        "protected_unknowns_must_not_be_promoted": True,
        "source_packet_sha256": actual_packet_hash,
    }

    expected_inputs = {
        "schema": "neq.llm_staging_expected_inputs.v1",
        "scene_id": scene["scene_id"],
        "source_facts": source_facts,
        "approved_topology": topology,
        "reference_coverage": coverage,
        "protected_unknowns": unknowns,
    }
    expected_path = PROTOCOL_DIR / "expected" / (scene_key + ".json")
    _write(expected_path, _pretty_bytes(expected_inputs))

    return {
        "scene_id": scene["scene_id"],
        "source_identity": scene["source_identity"],
        "manual_lineage_review": "PENDING",
        "manual_lineage_review_required_before_call": True,
        "source_reference": scene["source_reference"],
        "source_file_path": source_file,
        "source_file_sha256": actual_source_hash,
        "source_packet_path": str(packet_path.relative_to(REPO_ROOT)),
        "source_packet_sha256": actual_packet_hash,
        "expected_inputs_path": str(expected_path.relative_to(REPO_ROOT)),
        "expected_inputs_sha256": _sha256_bytes(expected_path.read_bytes()),
    }


def _hash_path(relative_path: str) -> str:
    return _sha256_bytes((REPO_ROOT / relative_path).read_bytes())


def main() -> None:
    source_manifest = json.loads(SCENE_SOURCE_MANIFEST.read_text(encoding="utf-8"))
    selected = {item["scene_id"]: item for item in source_manifest["scenes"]}
    if tuple(item for item in APPROVED_SCENES if item in selected) != APPROVED_SCENES:
        raise ValueError("approved scene selection is incomplete")

    scene_records: list[dict[str, Any]] = []
    for scene_id in APPROVED_SCENES:
        scene = selected[scene_id]
        source_file = scene["source_reference"].split("#", 1)[0]
        source_raw = (REPO_ROOT / source_file).read_bytes()
        source = json.loads(source_raw.decode("utf-8"))
        scene_records.append(_make_scene_artifacts(scene, source_file, source_raw, source))

    old_availability = json.loads(AVAILABILITY_NOTE.read_text(encoding="utf-8"))
    if old_availability.get("verdict") != "UNCONFIRMED" or old_availability.get("generation_calls") != 0:
        raise ValueError("expected historical availability note is not fail-closed")

    availability_dir = STAGING_ROOT / "availability-check"
    attestation_path = availability_dir / "attestation.json"
    raw_listing_path = availability_dir / "model-listing.json"
    attestation_bytes = attestation_path.read_bytes()
    attestation = json.loads(attestation_bytes.decode("utf-8"))
    raw_listing = raw_listing_path.read_bytes()
    raw_hash = _sha256_bytes(raw_listing)
    if (
        attestation.get("schema") != "neq.openrouter_model_availability.v1"
        or attestation.get("verdict") != "CONFIRMED"
        or attestation.get("requested_model_id") != "openai/gpt-6-luna"
        or attestation.get("exact_model_id_present") is not True
        or attestation.get("request_count") != 1
        or attestation.get("generation_calls") != 0
        or attestation.get("raw_listing_sha256") != raw_hash
        or attestation.get("raw_listing_path") != "availability-check/model-listing.json"
    ):
        raise ValueError("saved replacement availability evidence failed validation")
    listing = json.loads(raw_listing.decode("utf-8"))
    rows = listing.get("data") if type(listing) is dict else None
    if type(rows) is not list or not any(
        type(row) is dict and row.get("id") == "openai/gpt-6-luna" for row in rows
    ):
        raise ValueError("saved availability listing lacks the exact model ID")
    _write(CURRENT_AVAILABILITY_NOTE, attestation_bytes)

    frozen_paths = [
        str(SCENE_SOURCE_MANIFEST.relative_to(REPO_ROOT)),
        str(PROTOCOL_PATH.relative_to(REPO_ROOT)),
        "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/llm-staging-protocol/protocol.draft.md",
        str((FROZEN_ROOT / "system-prompt.txt").relative_to(REPO_ROOT)),
        str((FROZEN_ROOT / "task-prompt.txt").relative_to(REPO_ROOT)),
        str((FROZEN_ROOT / "output-contract.schema.json").relative_to(REPO_ROOT)),
        str((FROZEN_ROOT / "generation-parameters.json").relative_to(REPO_ROOT)),
        str(AVAILABILITY_NOTE.relative_to(REPO_ROOT)),
        str(CURRENT_AVAILABILITY_NOTE.relative_to(REPO_ROOT)),
        "scripts/mise_en_scene/llm_staging/materialize.py",
        "scripts/mise_en_scene/llm_staging/__init__.py",
        "scripts/mise_en_scene/llm_staging/availability.py",
        "scripts/mise_en_scene/llm_staging/client.py",
        "scripts/mise_en_scene/llm_staging/transport.py",
        "scripts/mise_en_scene/llm_staging/output_gates.py",
        "scripts/test_mise_en_scene_llm_staging.py",
    ]
    frozen_paths.extend(
        path
        for row in scene_records
        for path in (row["source_packet_path"], row["expected_inputs_path"])
    )
    validator_paths = [
        "scripts/mise_en_scene/contract.py",
        "scripts/mise_en_scene/coverage.py",
        "scripts/mise_en_scene/arrival.py",
        "scripts/mise_en_scene/diagnostics.py",
        "scripts/mise_en_scene/identity.py",
    ]
    hashes = {path: _hash_path(path) for path in frozen_paths + validator_paths}
    manifest = {
        "schema": "neq.llm_staging_manifest.v1",
        "status": "FROZEN_FOR_OVERSEER_REVIEW",
        "execution_status": "NOT_STARTED",
        "execution_authorized": False,
        "owner_ruling": {
            "reference": "S ruling 2026-11-08T20:41:09Z item 2",
            "selected_scene_ids": list(APPROVED_SCENES),
            "provider": "openrouter",
            "model": "openai/gpt-6-luna",
            "generation_attempt_cap": 3,
            "one_attempt_per_scene": True,
            "fallbacks_retries_tools_disabled": True,
            "other_27_attempts_authorized": False,
            "both_owner_rating_axes_minimum": 4,
            "overseer_review_before_owner_access": True,
            "study_pass_requires_all_three_scenes": True,
            "linked_view_frontage_tested": False,
        },
        "attempt_order": list(APPROVED_SCENES),
        "availability": {
            "status": "CONFIRMED",
            "historical_check_path": str(AVAILABILITY_NOTE.relative_to(REPO_ROOT)),
            "historical_check_sha256": _sha256_bytes(AVAILABILITY_NOTE.read_bytes()),
            "historical_verdict": "UNCONFIRMED",
            "current_check_path": str(CURRENT_AVAILABILITY_NOTE.relative_to(REPO_ROOT)),
            "current_check_sha256": _sha256_bytes(CURRENT_AVAILABILITY_NOTE.read_bytes()),
            "raw_listing_path": str(raw_listing_path.relative_to(REPO_ROOT)),
            "raw_listing_sha256": raw_hash,
            "request_count": attestation["request_count"],
            "performed_utc": attestation["performed_utc"],
            "replacement_get_authority_confirmed": True,
            "generation_calls": 0,
        },
        "privacy": {
            "credentials_read_by_client": False,
            "credentials_logged_or_stored": False,
            "raw_output_access_order": ["overseer", "owner_after_semantic_review"],
            "run_directory_mode": "0700",
            "ledger_mode": "0600",
        },
        "artifacts": hashes,
        "validator_interfaces": {path: hashes[path] for path in validator_paths},
        "scenes": scene_records,
        "calls_made": 0,
        "last_updated": "2026-11-09",
    }
    manifest_path = FROZEN_ROOT / "staging-manifest.json"
    _write(manifest_path, _pretty_bytes(manifest))
    print("staging artifacts materialized; provider calls: 0")
    print("manifest sha256: " + _sha256_bytes(manifest_path.read_bytes()))


if __name__ == "__main__":
    main()
