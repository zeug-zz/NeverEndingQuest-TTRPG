# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Development-only Builder-arrival fixtures G, H, and I."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


_SOURCE_PATH = "plans/v2-mapping-pilot-owner-feedback.md"
_METADATA = {
    "authorship": "builder_authored_initial_scene",
    "development_only": True,
    "held_out": False,
    "legacy_truth_verified": False,
    "llm_builder_tested": False,
}
_GUARDED_CAMP_PAYLOAD = "The cold fire pit has an unspecified surprise."
_CUES = ("light", "sound", "weather")


def make_staged_arrival_fixtures() -> dict[str, dict[str, Any]]:
    """Return fresh G/H/I Builder-authored fixtures and separate references.

    G, H, and I are owner-feedback examples for development only. They are not
    holdouts, legacy-truth records, or evidence of LLM Builder capability.
    """

    return {
        key: _make_fixture(spec)
        for key, spec in _SCENE_SPECS.items()
    }


def _make_fixture(spec: dict[str, Any]) -> dict[str, Any]:
    facts = copy.deepcopy(spec["facts"])
    fact_map = {fact["id"]: fact for fact in facts}
    segments: list[dict[str, Any]] = []
    expected_segments: list[dict[str, Any]] = []
    candidate_claims: list[dict[str, Any]] = []
    for segment_spec in spec["segments"]:
        claim_records = [
            _claim(claim_spec, fact_map)
            for claim_spec in segment_spec["claims"]
        ]
        fact_ids = [claim["fact_id"] for claim in claim_records]
        segment = {
            "id": segment_spec["id"],
            "role": segment_spec["role"],
            "text": segment_spec["text"],
            "fact_ids": fact_ids,
        }
        segments.append(segment)
        candidate_claims.append(
            {"segment_id": segment["id"], "claims": copy.deepcopy(claim_records)}
        )
        expected_segments.append(
            {
                "id": segment["id"],
                "role": segment["role"],
                "text_sha256": hashlib.sha256(segment["text"].encode("utf-8")).hexdigest(),
                "fact_ids": list(fact_ids),
                "claims": copy.deepcopy(claim_records),
            }
        )

    topology = copy.deepcopy(spec["topology"])
    fixture_id = spec["scene_id"]
    candidate = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "facts": facts,
        "topology": topology,
        "arrival_segments": segments,
    }

    reference_facts = copy.deepcopy(spec["facts"])
    reference_topology = copy.deepcopy(spec["topology"])
    public_ids = [fact["id"] for fact in reference_facts if fact["audience"] == "public"]
    all_ids = [fact["id"] for fact in reference_facts]
    topology_ids = {
        "scene_nodes": [item["id"] for item in reference_topology["scene_nodes"]],
        "links": [item["id"] for item in reference_topology["links"]],
        "schematic_layout": [item["anchor_id"] for item in reference_topology["schematic_layout"]],
    }
    projection_reference = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "fact_digests": {
            fact["id"]: _sha256(fact) for fact in reference_facts
        },
        "scope": {
            "audience_fact_ids": {"public": public_ids, "gm_narrator": all_ids},
            "topology_record_ids": {
                "public": copy.deepcopy(topology_ids),
                "gm_narrator": copy.deepcopy(topology_ids),
            },
        },
        "topology_by_audience": {
            "public": copy.deepcopy(reference_topology),
            "gm_narrator": copy.deepcopy(reference_topology),
        },
        "arrival_approvals": [
            {
                "id": segment["id"],
                "role": segment["role"],
                "text_sha256": hashlib.sha256(segment["text"].encode("utf-8")).hexdigest(),
                "fact_ids": list(segment["fact_ids"]),
            }
            for segment in segments
        ],
    }

    provenance = copy.deepcopy(spec["source_provenance"])
    arrival_candidate = {
        "fixture_id": fixture_id,
        "source_provenance": copy.deepcopy(provenance),
        "metadata": copy.deepcopy(_METADATA),
        "orientation": copy.deepcopy(spec["orientation"]),
        "cue_states": copy.deepcopy(spec["cue_states"]),
        "next_section": copy.deepcopy(spec["next_section"]),
        "claims": candidate_claims,
    }
    arrival_reference = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "facts": reference_facts,
        "topology": reference_topology,
        "source_provenance": provenance,
        "metadata": copy.deepcopy(_METADATA),
        "orientation": copy.deepcopy(spec["orientation"]),
        "approved_compass_frames": [spec["orientation"]["frame"]],
        "cue_states": copy.deepcopy(spec["cue_states"]),
        "next_section": copy.deepcopy(spec["next_section"]),
        "segments": expected_segments,
        "guarded_markers": copy.deepcopy(spec["guarded_markers"]),
    }
    return {
        "candidate": candidate,
        "reference": projection_reference,
        "arrival_candidate": arrival_candidate,
        "arrival_reference": arrival_reference,
    }


def _claim(spec: dict[str, Any], facts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fact = facts[spec["fact_id"]]
    return {
        "id": spec["id"],
        "kind": spec["kind"],
        "fact_id": fact["id"],
        "predicate": fact["predicate"],
        "subject_id": fact["subject_id"],
        "object_id": fact["object_id"],
        "status": fact["status"],
        "value": fact["value"],
        "provenance": copy.deepcopy(fact["provenance"]),
        "span": spec["span"],
        "choice": "open" if spec["kind"] == "invitation" else None,
        "success": "unspecified" if spec["kind"] == "invitation" else None,
    }


def _fact(
    scene_id: str,
    local_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    value: str | None,
    source_ref: str,
    *,
    status: str = "known",
    audience: str = "public",
    knowledge_status: str = "known",
    provenance_class: str = "builder_authored",
) -> dict[str, Any]:
    if status == "unknown":
        provenance_class = "unknown"
        value = None
        source_refs: list[str] = []
    else:
        source_refs = [source_ref]
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
        "provenance": {"class": provenance_class, "source_refs": source_refs},
    }


def _position_fact(
    scene_id: str, anchor_id: str, row: int, column: int, source_ref: str
) -> dict[str, Any]:
    local_id = anchor_id.rsplit(":", 1)[-1]
    return _fact(
        scene_id,
        "position-" + local_id,
        anchor_id,
        "anchor_position",
        scene_id,
        "row=%d,column=%d" % (row, column),
        source_ref,
    )


def _source_provenance(
    appendix: str, section: str, digest: str
) -> dict[str, Any]:
    return {
        "source_ref": "source:owner-feedback-appendix-" + appendix.lower(),
        "path": _SOURCE_PATH,
        "section": section,
        "sha256": digest,
        "source_kind": "owner_feedback",
        "legacy_truth_verified": False,
    }


def _orientation(source_ref: str) -> dict[str, Any]:
    return {
        "status": "known",
        "frame": "north_up",
        "provenance": {"class": "builder_authored", "source_refs": [source_ref]},
    }


def _fact_id(local_id: str) -> str:
    return "mapping_fixture:fact:" + local_id


def _entity_id(local_id: str) -> str:
    return "mapping_fixture:entity:" + local_id


def _scene_id(local_id: str) -> str:
    return "mapping_fixture:scene:" + local_id


def _claim_spec(
    local_id: str, kind: str, fact_local_id: str, span: str
) -> dict[str, Any]:
    return {
        "id": "arrival-claim-" + local_id,
        "kind": kind,
        "fact_id": _fact_id(fact_local_id),
        "span": span,
    }


def _sha256(value: object) -> str:
    text = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _cave_spec() -> dict[str, Any]:
    scene = _scene_id("cave_arrival")
    next_scene = _scene_id("first_cave_passage")
    approach, threshold, focal = map(
        _entity_id, ("cave_approach", "cave_threshold", "first_passage")
    )
    source = "source:owner-feedback-appendix-g"
    facts = [
        _fact(scene, "g-approach-threshold", approach, "approach_to_threshold", threshold, "The blighted forest path reaches the low cave mouth.", source),
        _fact(scene, "g-approach-surface", approach, "scene_feature", scene, "The low mouth is cut into rain-black limestone.", source),
        _fact(scene, "g-threshold-focal", threshold, "threshold_to_focal", focal, "The low mouth opens onto a first passage that bends out of sight.", source),
        _fact(scene, "g-light-gradient", threshold, "light_gradient", focal, "Grey daylight dwindles at the mouth into faint phosphorescence along wet passage walls and floor.", source),
        _fact(scene, "g-sound-gradient", scene, "sound_gradient", focal, "Thunder rolls over the forest; an indistinct whisper seems to travel outward from within the cave.", source),
        _fact(scene, "g-weather-gradient", scene, "weather_gradient", threshold, "Storm remains over the corrupted forest approach and behind the cave mouth.", source),
        _fact(scene, "g-transition", scene, "transition_to_next_section", next_scene, "The cave mouth opens into the first passage; the passage bends out of sight.", source),
        _fact(scene, "g-perception", threshold, "perception_of_next_section", next_scene, "The first passage is visible from the threshold only until its bend.", source),
        _fact(scene, "g-visible-affordance", focal, "visible_affordance", scene, "Faint fungi and the water-darkened lip are visible at the mouth from the approach.", source),
        _position_fact(scene, approach, 2, 1, source),
        _position_fact(scene, threshold, 1, 1, source),
        _position_fact(scene, focal, 0, 1, source),
    ]
    topology = {
        "scene_nodes": [
            {"id": scene, "label": "Forest cave threshold", "knowledge_status": "known"},
            {"id": next_scene, "label": "First cave passage", "knowledge_status": "known"},
        ],
        "links": [
            {"id": _fact_id("g-transition"), "from_scene_id": scene, "to_scene_id": next_scene, "relation": "leads_to"}
        ],
        "schematic_layout": [
            {"scene_id": scene, "anchor_id": approach, "label": "approach", "row": 2, "column": 1},
            {"scene_id": scene, "anchor_id": threshold, "label": "threshold", "row": 1, "column": 1},
            {"scene_id": scene, "anchor_id": focal, "label": "focal", "row": 0, "column": 1},
        ],
    }
    approach_text = "The blighted forest path reaches the low mouth. The low mouth is cut into rain-black limestone."
    threshold_text = "At the lip, grey daylight dwindles into faint phosphorescence along wet stone; thunder remains over the forest, and an indistinct whisper drifts outward. The first passage bends from view."
    focal_text = "Faint fungi and the water-darkened lip draw the eye; they invite a closer look, while the next move remains open."
    sections = "### G. Cave threshold: forest-to-cavern mise-en-scene (NC01, review #14)"
    return {
        "scene_id": scene,
        "facts": facts,
        "topology": topology,
        "source_provenance": _source_provenance("G", sections, "f30cab950fa7b35e328e4c40db4c457dfca0a43ad5911d8bca2950ec247a1646"),
        "orientation": _orientation(source),
        "cue_states": [
            {"cue": "light", "status": "known", "fact_id": _fact_id("g-light-gradient"), "reason": None},
            {"cue": "sound", "status": "known", "fact_id": _fact_id("g-sound-gradient"), "reason": None},
            {"cue": "weather", "status": "known", "fact_id": _fact_id("g-weather-gradient"), "reason": None},
        ],
        "next_section": {
            "status": "known",
            "from_scene_id": scene,
            "to_scene_id": next_scene,
            "transition_fact_id": _fact_id("g-transition"),
            "perception_fact_id": _fact_id("g-perception"),
            "perception_status": "partially_visible",
            "reason": None,
        },
        "segments": [
            {"id": "g-arrival-approach", "role": "approach", "text": approach_text, "claims": [
                _claim_spec("g-stage-approach", "stage_relation", "g-approach-threshold", "The blighted forest path reaches the low mouth"),
                _claim_spec("g-approach-surface", "scene_feature", "g-approach-surface", "The low mouth is cut into rain-black limestone."),
            ]},
            {"id": "g-arrival-threshold", "role": "threshold", "text": threshold_text, "claims": [
                _claim_spec("g-stage-focal", "stage_relation", "g-threshold-focal", "The first passage bends from view."),
                _claim_spec("g-light", "cue_gradient", "g-light-gradient", "grey daylight dwindles into faint phosphorescence along wet stone"),
                _claim_spec("g-sound", "cue_gradient", "g-sound-gradient", "thunder remains over the forest, and an indistinct whisper drifts outward"),
                _claim_spec("g-weather", "cue_gradient", "g-weather-gradient", "thunder remains over the forest"),
                _claim_spec("g-transition", "transition", "g-transition", "The first passage bends from view."),
                _claim_spec("g-perception", "transition", "g-perception", "The first passage bends from view."),
            ]},
            {"id": "g-arrival-focal", "role": "focal", "text": focal_text, "claims": [
                _claim_spec("g-invitation", "invitation", "g-visible-affordance", "Faint fungi and the water-darkened lip draw the eye; they invite a closer look"),
            ]},
        ],
        "guarded_markers": [],
    }


def _camp_spec() -> dict[str, Any]:
    scene = _scene_id("camp_clearing")
    approach, threshold, focal = map(
        _entity_id, ("camp_approach", "clearing_edge", "cold_fire_pit")
    )
    research, sleeping, supply = map(
        _entity_id, ("research_tent", "sleeping_tent", "supply_tent")
    )
    source = "source:owner-feedback-appendix-h"
    facts = [
        _fact(scene, "h-approach-threshold", approach, "approach_to_threshold", threshold, "The southern approach aligns with the canonical clearing entry.", source),
        _fact(scene, "h-threshold-focal", threshold, "threshold_to_focal", focal, "The clear southern way leads toward the cold central fire pit.", source),
        _fact(scene, "h-clearing-boundary", scene, "scene_feature", scene, "Forest bounds the clearing while the outer cells also hold clearing ground.", source),
        _fact(scene, "h-cold-fire-pit", focal, "scene_feature", scene, "A cold fire pit has blackened stones, grey ash, and trampled ground at the center.", source),
        _fact(scene, "h-research-tent", research, "scene_feature", scene, "A torn research tent and loose papers and equipment sit by the northwestern tree line.", source),
        _fact(scene, "h-sleeping-tent", sleeping, "scene_feature", scene, "A sleeping tent slumps to the northeast with split canvas and scattered bedding.", source),
        _fact(scene, "h-supply-tent", supply, "scene_feature", scene, "A collapsed supply tent spills abandoned equipment toward the western open ground.", source),
        _fact(scene, "h-visible-affordance", research, "visible_affordance", scene, "The tents and scattered camp objects are visible from the clearing and invite examination.", source),
        _fact(scene, "h-weather-unknown", scene, "weather_gradient", scene, None, source, status="unknown"),
        _fact(scene, "h-guard-trigger", scene, "trigger_condition", scene, "attempt_fire_lighting", source, audience="gm_only", provenance_class="source_extracted"),
        _fact(scene, "h-guard-effect-unknown", scene, "trigger_effect", scene, None, source, status="unknown", audience="gm_only"),
        _position_fact(scene, approach, 3, 1, source),
        _position_fact(scene, threshold, 2, 1, source),
        _position_fact(scene, focal, 1, 1, source),
        _position_fact(scene, research, 0, 0, source),
        _position_fact(scene, sleeping, 0, 2, source),
        _position_fact(scene, supply, 1, 0, source),
    ]
    topology = {
        "scene_nodes": [{"id": scene, "label": "Wooded camp clearing", "knowledge_status": "known"}],
        "links": [],
        "schematic_layout": [
            {"scene_id": scene, "anchor_id": approach, "label": "approach", "row": 3, "column": 1},
            {"scene_id": scene, "anchor_id": threshold, "label": "threshold", "row": 2, "column": 1},
            {"scene_id": scene, "anchor_id": focal, "label": "focal", "row": 1, "column": 1},
            {"scene_id": scene, "anchor_id": research, "label": "tent", "row": 0, "column": 0},
            {"scene_id": scene, "anchor_id": sleeping, "label": "tent", "row": 0, "column": 2},
            {"scene_id": scene, "anchor_id": supply, "label": "tent", "row": 1, "column": 0},
        ],
    }
    approach_text = "The trees draw back around the clearing, though branches crowd its edges; a southern path opens through them."
    threshold_text = "A clear way from the southern edge leads toward a cold fire pit at the center, ringed by blackened stones and grey ash."
    focal_text = "A torn research tent sags by the northwestern tree line, a sleeping tent slumps to the northeast, and a collapsed supply tent spills equipment westward. The tents and scattered objects invite closer examination; no particular choice or outcome is decided here."
    section = "### Appendix H. Abandoned research camp: investigation mise-en-scene"
    return {
        "scene_id": scene,
        "facts": facts,
        "topology": topology,
        "source_provenance": _source_provenance("H", section, "1ac15c0a677848705d5e54e0f9d13c1f39662685154f27ca31fb82e7b3ea6568"),
        "orientation": _orientation(source),
        "cue_states": [
            {"cue": "light", "status": "not_applicable", "fact_id": None, "reason": "Appendix H supplies no light gradient for this arrival."},
            {"cue": "sound", "status": "not_applicable", "fact_id": None, "reason": "Appendix H supplies no sound gradient for this arrival."},
            {"cue": "weather", "status": "unknown", "fact_id": _fact_id("h-weather-unknown"), "reason": "Appendix H does not establish weather."},
        ],
        "next_section": {
            "status": "not_applicable",
            "from_scene_id": None,
            "to_scene_id": None,
            "transition_fact_id": None,
            "perception_fact_id": None,
            "perception_status": None,
            "reason": "Appendix H stages the clearing arrival but supplies no next-section topology.",
        },
        "segments": [
            {"id": "h-arrival-approach", "role": "approach", "text": approach_text, "claims": [
                _claim_spec("h-stage-approach", "stage_relation", "h-approach-threshold", "a southern path opens through them"),
                _claim_spec("h-boundary", "scene_feature", "h-clearing-boundary", "The trees draw back around the clearing, though branches crowd its edges"),
            ]},
            {"id": "h-arrival-threshold", "role": "threshold", "text": threshold_text, "claims": [
                _claim_spec("h-stage-focal", "stage_relation", "h-threshold-focal", threshold_text),
                _claim_spec("h-fire-pit", "scene_feature", "h-cold-fire-pit", "a cold fire pit at the center, ringed by blackened stones and grey ash"),
            ]},
            {"id": "h-arrival-focal", "role": "focal", "text": focal_text, "claims": [
                _claim_spec("h-research-tent", "scene_feature", "h-research-tent", "A torn research tent sags by the northwestern tree line"),
                _claim_spec("h-sleeping-tent", "scene_feature", "h-sleeping-tent", "a sleeping tent slumps to the northeast"),
                _claim_spec("h-supply-tent", "scene_feature", "h-supply-tent", "a collapsed supply tent spills equipment westward"),
                _claim_spec("h-invitation", "invitation", "h-visible-affordance", "The tents and scattered objects invite closer examination"),
            ]},
        ],
        "guarded_markers": [
            {"fact_id": _fact_id("h-guard-trigger"), "values": [_GUARDED_CAMP_PAYLOAD, "attempt_fire_lighting"]}
        ],
    }


def _voidstone_spec() -> dict[str, Any]:
    scene = _scene_id("voidstone_approach")
    next_scene = _scene_id("summit_clearing")
    approach, threshold, focal = map(
        _entity_id, ("southern_ascent", "stone_gap", "voidstone_altar")
    )
    source = "source:owner-feedback-appendix-i"
    facts = [
        _fact(scene, "i-approach-threshold", approach, "approach_to_threshold", threshold, "The southern ascent reaches the gap between standing stones.", source),
        _fact(scene, "i-threshold-focal", threshold, "threshold_to_focal", focal, "The gap opens onto a summit clearing with the Voidstone altar at its center.", source),
        _fact(scene, "i-transition", scene, "transition_to_next_section", next_scene, "The southern gap opens toward the summit clearing.", source),
        _fact(scene, "i-perception", threshold, "perception_of_next_section", next_scene, "The summit clearing and central altar are visible beyond the southern gap.", source),
        _fact(scene, "i-stone-ring", scene, "scene_feature", focal, "Weathered standing stones enclose the summit clearing; twisted sentinel trees rise beyond them.", source),
        _fact(scene, "i-channels", focal, "scene_feature", scene, "Channels divide the ground around the altar and spread outward between stones and roots.", source),
        _fact(scene, "i-distortion", focal, "perceptual_distortion", scene, "Air immediately around the altar distorts its edges; the far side of the circle seems briefly displaced, then settles when the gaze shifts.", source),
        _fact(scene, "i-visible-affordance", focal, "visible_affordance", scene, "Bare summit ground leaves room around the altar; the rim, channels, and central stone remain visible points of interest.", source),
        _fact(scene, "i-weather-unknown", scene, "weather_gradient", scene, None, source, status="unknown"),
        _position_fact(scene, approach, 3, 1, source),
        _position_fact(scene, threshold, 2, 1, source),
        _position_fact(next_scene, focal, 1, 1, source),
    ]
    topology = {
        "scene_nodes": [
            {"id": scene, "label": "Southern summit ascent", "knowledge_status": "known"},
            {"id": next_scene, "label": "Voidstone summit clearing", "knowledge_status": "known"},
        ],
        "links": [
            {"id": _fact_id("i-transition"), "from_scene_id": scene, "to_scene_id": next_scene, "relation": "visible_transition"}
        ],
        "schematic_layout": [
            {"scene_id": scene, "anchor_id": approach, "label": "approach", "row": 3, "column": 1},
            {"scene_id": scene, "anchor_id": threshold, "label": "threshold", "row": 2, "column": 1},
            {"scene_id": next_scene, "anchor_id": focal, "label": "focal", "row": 1, "column": 1},
        ],
    }
    approach_text = "The southern ascent reaches a gap between weathered standing stones; a bare summit lies beyond."
    threshold_text = "Beyond the gap, standing stones enclose the clearing and twisted sentinel trees rise outside them. The Voidstone altar stands at the center, with channels spreading outward across the ground."
    focal_text = "Air immediately around the altar distorts its edges; the far side of the circle seems briefly displaced, then settles when the gaze shifts. Bare ground leaves room around the altar, with the rim and channels visible as points of interest; the next move remains open."
    section = "### Appendix I. Voidstone hilltop: climactic mise-en-scene (NC05, #16)"
    return {
        "scene_id": scene,
        "facts": facts,
        "topology": topology,
        "source_provenance": _source_provenance("I", section, "b75af1dd9d25497e117ae5b0b2f3d5604b25734d301c4526057069cb87116c8a"),
        "orientation": _orientation(source),
        "cue_states": [
            {"cue": "light", "status": "not_applicable", "fact_id": None, "reason": "Appendix I supplies no light gradient for this arrival."},
            {"cue": "sound", "status": "not_applicable", "fact_id": None, "reason": "Appendix I supplies no sound gradient for this arrival."},
            {"cue": "weather", "status": "unknown", "fact_id": _fact_id("i-weather-unknown"), "reason": "Appendix I does not establish weather."},
        ],
        "next_section": {
            "status": "known",
            "from_scene_id": scene,
            "to_scene_id": next_scene,
            "transition_fact_id": _fact_id("i-transition"),
            "perception_fact_id": _fact_id("i-perception"),
            "perception_status": "visible",
            "reason": None,
        },
        "segments": [
            {"id": "i-arrival-approach", "role": "approach", "text": approach_text, "claims": [
                _claim_spec("i-stage-approach", "stage_relation", "i-approach-threshold", "The southern ascent reaches a gap between weathered standing stones"),
            ]},
            {"id": "i-arrival-threshold", "role": "threshold", "text": threshold_text, "claims": [
                _claim_spec("i-stage-focal", "stage_relation", "i-threshold-focal", "The Voidstone altar stands at the center"),
                _claim_spec("i-transition", "transition", "i-transition", "Beyond the gap"),
                _claim_spec("i-perception", "transition", "i-perception", "Beyond the gap"),
                _claim_spec("i-stone-ring", "scene_feature", "i-stone-ring", "standing stones enclose the clearing and twisted sentinel trees rise outside them"),
                _claim_spec("i-channels", "scene_feature", "i-channels", "channels spreading outward across the ground"),
            ]},
            {"id": "i-arrival-focal", "role": "focal", "text": focal_text, "claims": [
                _claim_spec("i-distortion", "scene_feature", "i-distortion", "Air immediately around the altar distorts its edges; the far side of the circle seems briefly displaced, then settles when the gaze shifts"),
                _claim_spec("i-invitation", "invitation", "i-visible-affordance", "Bare ground leaves room around the altar, with the rim and channels visible as points of interest"),
            ]},
        ],
        "guarded_markers": [],
    }


_SCENE_SPECS = {"G": _cave_spec(), "H": _camp_spec(), "I": _voidstone_spec()}
