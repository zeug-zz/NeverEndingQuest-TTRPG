# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Small provider-free extraction and Builder fixture constructors."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import contract


_MODULE_ID = "mapping_fixture"
_SCENE_ID = "mapping_fixture:scene:arrival"
_SCOPE_ID = "mapping_fixture:scope:arrival"
_TOPOLOGY_ID = "mapping_fixture:topology:arrival-v1"
_LANDMARK_ID = "mapping_fixture:entity:landmark"
_SOURCE_REF = "source:fixture-landmark"
_CONSULTED_MATERIAL = "development fixture text establishing a landmark only"
_WORLD_CARDINAL_FRAME = "world_cardinal"
_CAMP_SOURCE_REF = "source:owner-feedback-appendix-h"
_CAMP_SOURCE_PATH = "plans/v2-mapping-pilot-owner-feedback.md"
_CAMP_SOURCE_SECTION = (
    "Appendix H. Abandoned research camp: investigation mise-en-scene"
)
_CAMP_SOURCE_SHA256 = "1ac15c0a677848705d5e54e0f9d13c1f39662685154f27ca31fb82e7b3ea6568"
_CAMP_FIXTURE_ID = "mapping_fixture:scene:abandoned_camp"
_CAMP_GUARD_ID = "mapping_fixture:fact:camp-surprise-guard"
_CAMP_GUARD_PAYLOAD = "The cold fire pit has an unspecified surprise."
_CAMP_PUBLIC_FACTS = (
    (
        "mapping_fixture:fact:camp-scope",
        "Forest bounds the clearing; the scene scope is the clearing and wooded boundary.",
    ),
    (
        "mapping_fixture:fact:camp-fire-pit",
        "A cold fire pit with blackened stones and grey ash occupies the center.",
    ),
    (
        "mapping_fixture:fact:camp-research-tent",
        "The research tent is at the northwest example location, with papers and equipment nearby.",
    ),
    (
        "mapping_fixture:fact:camp-sleeping-tent",
        "The sleeping tent is at the northeast example location, with bedding nearby.",
    ),
    (
        "mapping_fixture:fact:camp-supply-tent",
        "The collapsed supply tent is at the western example location, with equipment nearby.",
    ),
    (
        "mapping_fixture:fact:camp-seepage",
        "Dark seepage appears at the north, east, and southwest clearing edges.",
    ),
    (
        "mapping_fixture:fact:camp-approach",
        "The example approach is from the south and aligns with the canonical entry.",
    ),
)
_CAMP_SCHEMATIC_POSITIONS = {
    "approach": "S",
    "fire_pit": "C",
    "research_tent": "NW",
    "sleeping_tent": "NE",
    "supply_tent": "W",
}
_CAMP_UNKNOWN_MECHANICS = (
    "access",
    "audibility",
    "distance",
    "legality",
    "line_of_sight",
    "movement_cost",
    "scale",
    "travel_time",
)


def make_linked_two_scene_knowledge_fixture() -> dict[str, Any]:
    """Return a provider-free linked-scene projection bundle with a separate reference.

    The public forest-edge view includes visited/discovered facts and an explicit
    camp rumour. A GM-only route, trigger, and unknown effect connect a second
    scene, but their IDs and provenance are excluded from the public allowlist.
    Arrival fragments are fixture-authored and bound independently by exact
    hashes and fact IDs; this is not a general prose validator.
    """

    forest_scene = "mapping_fixture:scene:forest_edge"
    camp_scene = "mapping_fixture:scene:camp_clearing"
    approach_id = "mapping_fixture:entity:forest_approach"
    threshold_id = "mapping_fixture:entity:stone_threshold"
    focal_id = "mapping_fixture:entity:low_arch"
    public_source = "source:fixture-public-notes"
    rumour_source = "source:fixture-public-rumour"
    route_source = "source:fixture-gm-route"
    trigger_source = "source:fixture-gm-trigger"

    def fact(
        local_id: str,
        scene_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        value: str | None,
        *,
        status: str = "known",
        knowledge_status: str = "discovered",
        audience: str = "public",
        provenance_class: str = "builder_authored",
        source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "mapping_fixture:fact:" + local_id,
            "scene_id": scene_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "status": status,
            "knowledge_status": knowledge_status,
            "audience": audience,
            "value": value,
            "provenance": {
                "class": provenance_class,
                "source_refs": list(source_refs or []),
            },
        }

    facts = [
        fact(
            "forest-edge-visited",
            forest_scene,
            forest_scene,
            "scene_status",
            forest_scene,
            "The forest edge has been visited.",
            knowledge_status="visited",
            provenance_class="source_extracted",
            source_refs=[public_source],
        ),
        fact(
            "approach-threshold",
            forest_scene,
            approach_id,
            "approach_to_threshold",
            threshold_id,
            "A moss-dark path narrows at the stone threshold.",
        ),
        fact(
            "threshold-focal",
            forest_scene,
            threshold_id,
            "threshold_to_focal",
            focal_id,
            "Beyond the threshold, the path opens toward a low stone arch.",
        ),
        fact(
            "sound-gradient",
            forest_scene,
            threshold_id,
            "sound_gradient",
            focal_id,
            "A low murmur grows clearer as the arch nears.",
        ),
        fact(
            "light-gradient",
            forest_scene,
            threshold_id,
            "light_gradient",
            focal_id,
            "Warm light brightens just beyond the threshold.",
        ),
        fact(
            "visible-affordance",
            forest_scene,
            focal_id,
            "visible_affordance",
            forest_scene,
            "A broad stone ledge beside the arch offers a place to set an object.",
        ),
        fact(
            "weather-gradient-unknown",
            forest_scene,
            forest_scene,
            "weather_gradient",
            forest_scene,
            None,
            status="unknown",
            knowledge_status="known",
            provenance_class="unknown",
        ),
        fact(
            "camp-rumour",
            forest_scene,
            forest_scene,
            "rumour_about_place",
            forest_scene,
            "Travelers mention an old camp somewhere beyond the woods.",
            knowledge_status="rumoured",
            provenance_class="source_extracted",
            source_refs=[rumour_source],
        ),
        fact(
            "camp-route-secret",
            camp_scene,
            forest_scene,
            "route_to",
            camp_scene,
            "A narrow northern track reaches the camp clearing.",
            audience="gm_only",
            provenance_class="source_extracted",
            source_refs=[route_source],
        ),
        fact(
            "camp-trigger-secret",
            camp_scene,
            camp_scene,
            "trigger_condition",
            camp_scene,
            "attempt_fire_lighting",
            audience="gm_only",
            provenance_class="source_extracted",
            source_refs=[trigger_source],
        ),
        fact(
            "camp-effect-unknown",
            camp_scene,
            camp_scene,
            "trigger_effect",
            camp_scene,
            None,
            status="unknown",
            knowledge_status="known",
            audience="gm_only",
            provenance_class="unknown",
        ),
    ]
    topology = {
        "scene_nodes": [
            {"id": forest_scene, "label": "Forest edge", "knowledge_status": "visited"},
            {"id": camp_scene, "label": "Camp clearing", "knowledge_status": "known"},
        ],
        "links": [
            {
                "id": "mapping_fixture:fact:camp-route-secret",
                "from_scene_id": forest_scene,
                "to_scene_id": camp_scene,
                "relation": "route",
            }
        ],
        "schematic_layout": [
            {"scene_id": forest_scene, "anchor_id": approach_id, "label": "approach", "row": 0, "column": 0},
            {"scene_id": forest_scene, "anchor_id": threshold_id, "label": "threshold", "row": 0, "column": 1},
            {"scene_id": forest_scene, "anchor_id": focal_id, "label": "focal", "row": 0, "column": 2},
        ],
    }
    arrival_segments = [
        {
            "id": "arrival-approach",
            "role": "approach",
            "text": "A moss-dark path narrows toward the stone threshold.",
            "fact_ids": ["mapping_fixture:fact:approach-threshold"],
        },
        {
            "id": "arrival-threshold",
            "role": "threshold",
            "text": "Beyond it, the path opens beneath the low stone arch as a quiet murmur grows clearer.",
            "fact_ids": [
                "mapping_fixture:fact:threshold-focal",
                "mapping_fixture:fact:sound-gradient",
            ],
        },
        {
            "id": "arrival-focal",
            "role": "focal",
            "text": "Warm light gathers just beyond the arch, where a broad stone ledge offers a place to set an object.",
            "fact_ids": [
                "mapping_fixture:fact:light-gradient",
                "mapping_fixture:fact:visible-affordance",
            ],
        },
    ]
    public_ids = [fact_item["id"] for fact_item in facts if fact_item["audience"] == "public"]
    all_ids = [fact_item["id"] for fact_item in facts]
    public_topology_ids = {
        "scene_nodes": [forest_scene],
        "links": [],
        "schematic_layout": [approach_id, threshold_id, focal_id],
    }
    gm_topology_ids = {
        "scene_nodes": [forest_scene, camp_scene],
        "links": ["mapping_fixture:fact:camp-route-secret"],
        "schematic_layout": [approach_id, threshold_id, focal_id],
    }

    def selected_topology(allowed_ids: dict[str, list[str]]) -> dict[str, Any]:
        id_fields = {"scene_nodes": "id", "links": "id", "schematic_layout": "anchor_id"}
        return {
            group: [
                copy.deepcopy(next(item for item in topology[group] if item[id_fields[group]] == record_id))
                for record_id in allowed_ids[group]
            ]
            for group in ("scene_nodes", "links", "schematic_layout")
        }

    reference = {
        "schema_version": 1,
        "fixture_id": "mapping_fixture:scene:linked_arrival",
        "fact_digests": {
            item["id"]: hashlib.sha256(
                json.dumps(
                    item,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
            ).hexdigest()
            for item in facts
        },
        "scope": {
            "audience_fact_ids": {"public": public_ids, "gm_narrator": all_ids},
            "topology_record_ids": {
                "public": public_topology_ids,
                "gm_narrator": gm_topology_ids,
            },
        },
        "topology_by_audience": {
            "public": selected_topology(public_topology_ids),
            "gm_narrator": selected_topology(gm_topology_ids),
        },
        "arrival_approvals": [
            {
                "id": segment["id"],
                "role": segment["role"],
                "text_sha256": hashlib.sha256(segment["text"].encode("utf-8")).hexdigest(),
                "fact_ids": list(segment["fact_ids"]),
            }
            for segment in arrival_segments
        ],
    }
    candidate = {
        "schema_version": 1,
        "fixture_id": reference["fixture_id"],
        "facts": copy.deepcopy(facts),
        "topology": copy.deepcopy(topology),
        "arrival_segments": copy.deepcopy(arrival_segments),
    }
    return {"candidate": candidate, "reference": reference}


def make_guarded_camp_fixture() -> dict[str, Any]:
    """Return separate candidate and reference data for the guarded camp case.

    The arrangement is a Builder-authored development example, not extracted
    legacy truth. The owner-feedback source reference records the material
    consulted without claiming that its example layout was canonical module
    data.
    """

    source_provenance = {
        "source_ref": _CAMP_SOURCE_REF,
        "path": _CAMP_SOURCE_PATH,
        "section": _CAMP_SOURCE_SECTION,
        "sha256": _CAMP_SOURCE_SHA256,
        "source_kind": "owner_feedback",
        "legacy_truth_verified": False,
    }
    public_facts = [
        {
            "id": fact_id,
            "text": text,
            "audience": "public",
            "authorship": "builder_authored_example",
            "legacy_truth_verified": False,
            "source_refs": [_CAMP_SOURCE_REF],
        }
        for fact_id, text in _CAMP_PUBLIC_FACTS
    ]
    candidate = {
        "fixture_id": _CAMP_FIXTURE_ID,
        "public_facts": public_facts,
        "position_frame": "north_up_schematic",
        "schematic_positions": copy.deepcopy(_CAMP_SCHEMATIC_POSITIONS),
        "initial_mobile_occupants": [],
        "guarded_fact": {
            "id": _CAMP_GUARD_ID,
            "audience": "gm_only",
            "trigger_action": "attempt_fire_lighting",
            "payload": _CAMP_GUARD_PAYLOAD,
            "effect": {"status": "unknown", "value": None},
            "provenance_class": "source_extracted",
            "legacy_truth_verified": False,
            "source_refs": [_CAMP_SOURCE_REF],
        },
        "unknown_mechanics": [
            {"name": name, "status": "unknown", "value": None}
            for name in _CAMP_UNKNOWN_MECHANICS
        ],
        "source_provenance": copy.deepcopy(source_provenance),
        "metadata": {
            "development_only": True,
            "held_out": False,
            "legacy_truth_verified": False,
        },
    }
    guard_reference = {
        "fixture_id": _CAMP_FIXTURE_ID,
        "public_fact_ids": tuple(fact_id for fact_id, _text in _CAMP_PUBLIC_FACTS),
        "public_fact_digests": {
            fact_id: hashlib.sha256(text.encode("ascii")).hexdigest()
            for fact_id, text in _CAMP_PUBLIC_FACTS
        },
        "position_frame": "north_up_schematic",
        "schematic_positions": copy.deepcopy(_CAMP_SCHEMATIC_POSITIONS),
        "guarded_fact_id": _CAMP_GUARD_ID,
        "guarded_audience": "gm_only",
        "trigger_action": "attempt_fire_lighting",
        "effect_status": "unknown",
        "guarded_payload_sha256": hashlib.sha256(
            _CAMP_GUARD_PAYLOAD.encode("ascii")
        ).hexdigest(),
        "unknown_mechanic_names": _CAMP_UNKNOWN_MECHANICS,
        "source_provenance": copy.deepcopy(source_provenance),
    }
    return {"candidate": candidate, "guard_reference": guard_reference}


def make_extraction_fixture() -> dict[str, Any]:
    """Return extracted landmark facts and explicit unknowns in fresh containers."""
    return {
        "fixture": {
            "schema_version": 1,
            "module_id": _MODULE_ID,
            "topology_id": _TOPOLOGY_ID,
            "scene": {
                "id": _SCENE_ID,
                "scope": {"id": _SCOPE_ID, "kind": "exterior"},
                "orientation": {"status": "unknown", "frame": None, "provenance": {"class": "unknown", "source_refs": []}},
            },
            "fixed_anchors": [{"id": _LANDMARK_ID, "kind": "landmark"}],
            "initial_mobile_occupants": [],
            "facts": [
                {"id": "mapping_fixture:fact:landmark-present", "subject_id": _SCENE_ID, "predicate": "contains", "object_id": _LANDMARK_ID, "status": "known", "value": True, "provenance": {"class": "source_extracted", "source_refs": [_SOURCE_REF]}},
                *[
                    {"id": "mapping_fixture:fact:unknown-" + name, "subject_id": _SCENE_ID, "predicate": name, "object_id": _LANDMARK_ID, "status": "unknown", "value": None, "provenance": {"class": "unknown", "source_refs": []}}
                    for name in ("route", "bearing", "distance", "visibility", "access", "sensory_reach")
                ],
            ],
            "extension_seams": {"multi_cell_extents": [], "stage_relations": [], "unknown_metrics": [], "audience_knowledge": [], "arrival_claims": []},
        },
        "approved_topology": contract.ApprovedTopology(_TOPOLOGY_ID, _MODULE_ID, _SCENE_ID, _SCOPE_ID, ("north_up",), (_LANDMARK_ID, "mapping_fixture:entity:approach", "mapping_fixture:entity:threshold", "mapping_fixture:entity:focal")),
        "consulted_source_refs": (_SOURCE_REF,),
        "provenance_metadata": {"source_refs": {_SOURCE_REF: _CONSULTED_MATERIAL}, "development_only": True, "held_out": False, "legacy_fact_verified": False},
        "synthetic_evaluation_party": [],
    }


def make_builder_fixture() -> dict[str, Any]:
    """Return a fresh fixture with topology-bound authored staging relationships."""
    bundle = make_extraction_fixture()
    scene = bundle["fixture"]
    scene["fixed_anchors"].extend(
        {
            "id": "mapping_fixture:entity:" + role,
            "kind": "focal_anchor" if role == "focal" else role,
        }
        for role in ("approach", "threshold", "focal")
    )
    for fact_id, source, predicate, target in (
        ("arrival-approach", "approach", "approach_to_threshold", "threshold"),
        ("threshold-focal", "threshold", "threshold_to_focal", "focal"),
    ):
        scene["facts"].append({"id": "mapping_fixture:fact:" + fact_id, "subject_id": "mapping_fixture:entity:" + source, "predicate": predicate, "object_id": "mapping_fixture:entity:" + target, "status": "known", "value": "initial staging", "provenance": {"class": "builder_authored", "source_refs": []}})
    return copy.deepcopy(bundle)


def make_linked_tavern_fixture(party_shape: str = "P1") -> dict[str, Any]:
    """Return a synthetic linked-view fixture with explicit identity references.

    The east/west pair is verified only for internal consistency against the
    supplied synthetic compass frames. It is not source-verified geography.
    """

    party_counts = {"P1": 1, "P4": 4}
    if type(party_shape) is not str or party_shape not in party_counts:
        raise ValueError("party_shape must be P1 or P4 metadata")

    shared_tavern = "mapping_fixture:entity:shared_tavern"
    market_frontage = "mapping_fixture:entity:market_frontage"
    square_frontage = "mapping_fixture:entity:square_frontage"
    market_tavern_local = "mapping_fixture:entity:market_tavern_view"
    square_tavern_local = "mapping_fixture:entity:square_tavern_view"
    market_frontage_local = "mapping_fixture:entity:market_frontage_view"
    square_frontage_local = "mapping_fixture:entity:square_frontage_view"

    def make_view(view_id: str, tavern_id: str, frontage_id: str) -> dict[str, Any]:
        scene_id = "mapping_fixture:scene:" + view_id
        scope_id = "mapping_fixture:scope:" + view_id
        topology_id = "mapping_fixture:topology:" + view_id + "-v1"
        fixture = {
            "schema_version": 1,
            "module_id": _MODULE_ID,
            "topology_id": topology_id,
            "scene": {
                "id": scene_id,
                "scope": {"id": scope_id, "kind": "street_view"},
                "orientation": {
                    "status": "known",
                    "frame": _WORLD_CARDINAL_FRAME,
                    "provenance": {"class": "builder_authored", "source_refs": []},
                },
            },
            "fixed_anchors": [
                {"id": tavern_id, "kind": "building"},
                {"id": frontage_id, "kind": "frontage"},
            ],
            "initial_mobile_occupants": [],
            "facts": [],
            "extension_seams": {
                "multi_cell_extents": [],
                "stage_relations": [],
                "unknown_metrics": [],
                "audience_knowledge": [],
                "arrival_claims": [],
            },
        }
        topology = contract.ApprovedTopology(
            topology_id,
            _MODULE_ID,
            scene_id,
            scope_id,
            (_WORLD_CARDINAL_FRAME,),
            (tavern_id, frontage_id),
        )
        return {
            "id": view_id,
            "fixture": fixture,
            "approved_topology": topology,
            "consulted_source_refs": (),
        }

    entities = [
        {"id": shared_tavern, "kind": "building", "identity_scope": "shared"},
        {"id": market_frontage, "kind": "frontage", "identity_scope": "view_local"},
        {"id": square_frontage, "kind": "frontage", "identity_scope": "view_local"},
    ]
    occurrences = [
        {
            "view_id": "market",
            "canonical_entity_id": shared_tavern,
            "fixture_entity_id": market_tavern_local,
        },
        {
            "view_id": "market",
            "canonical_entity_id": market_frontage,
            "fixture_entity_id": market_frontage_local,
        },
        {
            "view_id": "square",
            "canonical_entity_id": shared_tavern,
            "fixture_entity_id": square_tavern_local,
        },
        {
            "view_id": "square",
            "canonical_entity_id": square_frontage,
            "fixture_entity_id": square_frontage_local,
        },
    ]
    frontages = [
        {
            "id": "mapping_fixture:fact:market_tavern_frontage",
            "view_id": "market",
            "frontage_entity_id": market_frontage,
            "building_entity_id": shared_tavern,
        },
        {
            "id": "mapping_fixture:fact:square_tavern_frontage",
            "view_id": "square",
            "frontage_entity_id": square_frontage,
            "building_entity_id": shared_tavern,
        },
    ]
    bearings = [
        {
            "id": "mapping_fixture:fact:market_east_of_square",
            "from_view_id": "market",
            "to_view_id": "square",
            "direction": "east",
            "compass_frame": _WORLD_CARDINAL_FRAME,
            "verification_basis": "synthetic_approved_compass_frame",
        },
        {
            "id": "mapping_fixture:fact:square_west_of_market",
            "from_view_id": "square",
            "to_view_id": "market",
            "direction": "west",
            "compass_frame": _WORLD_CARDINAL_FRAME,
            "verification_basis": "synthetic_approved_compass_frame",
        },
    ]
    reference = {
        "canonical_entities": entities,
        "occurrences": occurrences,
        "frontages": frontages,
        "bearings": bearings,
    }
    return {
        "schema_version": 1,
        "reference": copy.deepcopy(reference),
        "views": [
            make_view("market", market_tavern_local, market_frontage_local),
            make_view("square", square_tavern_local, square_frontage_local),
        ],
        "identity_links": copy.deepcopy(occurrences),
        "frontages": copy.deepcopy(frontages),
        "bearings": copy.deepcopy(bearings),
        "metadata": {
            "development_only": True,
            "held_out": False,
            "source_verified": False,
            "synthetic_party_metadata": {
                "party_shape": party_shape,
                "member_count": party_counts[party_shape],
            },
        },
    }


def make_fixed_anchor_mobile_occupant_fixture() -> dict[str, Any]:
    """Return a before/after example where only a stable NPC moves."""

    tavern_id = "mapping_fixture:entity:shared_tavern"
    frontage_id = "mapping_fixture:entity:market_frontage"
    occupant_id = "mapping_fixture:entity:innkeeper"
    fixed_anchors = [
        {"id": tavern_id, "kind": "building", "position": [0, 0]},
        {"id": frontage_id, "kind": "frontage", "position": [1, 0]},
    ]
    return {
        "before": {
            "fixed_anchors": copy.deepcopy(fixed_anchors),
            "mobile_occupants": [
                {"id": occupant_id, "kind": "npc", "position": [0, 1]}
            ],
        },
        "after": {
            "fixed_anchors": copy.deepcopy(fixed_anchors),
            "mobile_occupants": [
                {"id": occupant_id, "kind": "npc", "position": [0, 2]}
            ],
        },
    }
