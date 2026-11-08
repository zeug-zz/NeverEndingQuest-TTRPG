# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Bounded supplied-claim checks and projections for staged arrivals.

This is a fixture protocol, not natural-language understanding. Candidate
prose and typed claims are checked against a separately supplied reference;
exact text hashes bind approved fragments while typed claim values are checked
against independent structured facts and topology.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from typing import Any


_ROLES = ("approach", "threshold", "focal")
_CUES = ("light", "sound", "weather")
_CUE_PREDICATES = {cue + "_gradient" for cue in _CUES}
_CLAIM_KEYS = {
    "id",
    "kind",
    "fact_id",
    "predicate",
    "subject_id",
    "object_id",
    "status",
    "value",
    "provenance",
    "span",
    "choice",
    "success",
}
_FACT_BINDING_FIELDS = (
    "id",
    "predicate",
    "subject_id",
    "object_id",
    "status",
    "value",
    "provenance",
)
_MAX_FACTS = 64
_MAX_RECORDS = 64
_MAX_TEXT = 4096
_MAX_SEGMENT_TEXT = 512


@dataclass(frozen=True)
class ArrivalDiagnostic:
    """Stable R10 diagnostic with a layer, path, and optional fact identity."""

    code: str
    layer: str
    path: str
    fact_id: str = ""


@dataclass(frozen=True)
class ArrivalReport:
    """Read-only validation result for one supplied arrival bundle."""

    diagnostics: tuple[ArrivalDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


class StagedArrivalError(ValueError):
    """Raised when an R10 bundle fails before projection."""

    def __init__(self, diagnostic: ArrivalDiagnostic) -> None:
        self.diagnostic = diagnostic
        self.code = diagnostic.code
        self.path = diagnostic.path
        self.fact_id = diagnostic.fact_id
        super().__init__(diagnostic.code + " at " + diagnostic.path)


def validate_staged_arrival(bundle: object, *, audience: object = "public") -> ArrivalReport:
    """Validate R10 claims against separate facts, topology, and approvals.

    The fixture contains the existing A/B/C/D projection pair plus separate
    arrival candidate/reference records. A reference is a bounded offline
    contract supplied by the caller, not an authorization service.
    """

    diagnostics: list[ArrivalDiagnostic] = []
    if type(audience) is not str or audience not in ("public", "gm_narrator"):
        _add(diagnostics, "AUDIENCE_NOT_ALLOWLISTED", "arrival", "$.audience")
        return _report(diagnostics)
    if type(bundle) is not dict or set(bundle) != {
        "candidate",
        "reference",
        "arrival_candidate",
        "arrival_reference",
    }:
        _add(diagnostics, "ARRIVAL_BUNDLE_SHAPE", "schema", "$.bundle")
        return _report(diagnostics)

    candidate = bundle["candidate"]
    projection_reference = bundle["reference"]
    arrival_candidate = bundle["arrival_candidate"]
    reference = bundle["arrival_reference"]
    if type(candidate) is not dict or type(projection_reference) is not dict:
        _add(diagnostics, "PROJECTION_INPUT_SHAPE", "schema", "$.candidate")
        return _report(diagnostics)
    if not _record(
        projection_reference,
        {
            "schema_version",
            "fixture_id",
            "fact_digests",
            "scope",
            "topology_by_audience",
            "arrival_approvals",
        },
        "$.reference",
        diagnostics,
    ):
        return _report(diagnostics)
    if not _record(
        arrival_candidate,
        {"fixture_id", "source_provenance", "metadata", "orientation", "cue_states", "next_section", "claims"},
        "$.arrival_candidate",
        diagnostics,
    ):
        return _report(diagnostics)
    if not _record(
        reference,
        {
            "schema_version",
            "fixture_id",
            "facts",
            "topology",
            "source_provenance",
            "metadata",
            "orientation",
            "approved_compass_frames",
            "cue_states",
            "next_section",
            "segments",
            "guarded_markers",
        },
        "$.arrival_reference",
        diagnostics,
    ):
        return _report(diagnostics)

    if type(reference["schema_version"]) is not int or reference["schema_version"] != 1:
        _add(diagnostics, "ARRIVAL_REFERENCE_VERSION", "schema", "$.arrival_reference.schema_version")
    if (
        type(candidate.get("fixture_id")) is not str
        or candidate.get("fixture_id") != reference["fixture_id"]
        or arrival_candidate.get("fixture_id") != reference["fixture_id"]
    ):
        _add(diagnostics, "ARRIVAL_FIXTURE_ID_MISMATCH", "projection", "$.candidate.fixture_id")

    expected_facts = _fact_map(reference["facts"], "$.arrival_reference.facts", diagnostics)
    candidate_facts = _fact_map(candidate.get("facts"), "$.candidate.facts", diagnostics)
    if len(expected_facts) > _MAX_FACTS or len(candidate_facts) > _MAX_FACTS:
        _add(diagnostics, "COLLECTION_LIMIT", "schema", "$.candidate.facts")
    _compare_facts(expected_facts, candidate_facts, diagnostics)

    topology = reference["topology"]
    if type(candidate.get("topology")) is not dict or type(topology) is not dict:
        _add(diagnostics, "ARRIVAL_TOPOLOGY_SHAPE", "schema", "$.candidate.topology")
    else:
        _compare_topology(candidate["topology"], topology, expected_facts, diagnostics)

    if candidate.get("fixture_id") != projection_reference.get("fixture_id"):
        _add(diagnostics, "PROJECTION_REFERENCE_FIXTURE_MISMATCH", "projection", "$.reference.fixture_id")
    _check_projection_reference(
        projection_reference, reference, expected_facts, diagnostics
    )

    _compare_exact(
        arrival_candidate.get("source_provenance"),
        reference["source_provenance"],
        "ARRIVAL_SOURCE_PROVENANCE_MISMATCH",
        "arrival",
        "$.arrival_candidate.source_provenance",
        diagnostics,
    )
    _compare_exact(
        arrival_candidate.get("metadata"),
        reference["metadata"],
        "ARRIVAL_METADATA_MISMATCH",
        "arrival",
        "$.arrival_candidate.metadata",
        diagnostics,
    )
    _validate_source_and_metadata(reference, expected_facts, diagnostics)
    orientation = _validate_orientation(
        arrival_candidate.get("orientation"),
        reference["orientation"],
        reference["approved_compass_frames"],
        reference["source_provenance"],
        diagnostics,
    )

    cue_states = _validate_cue_states(
        arrival_candidate.get("cue_states"),
        reference["cue_states"],
        expected_facts,
        diagnostics,
    )
    next_section = _validate_next_section(
        arrival_candidate.get("next_section"),
        reference["next_section"],
        expected_facts,
        topology,
        diagnostics,
    )
    segment_bindings = _validate_segments(
        candidate.get("arrival_segments"),
        arrival_candidate.get("claims"),
        reference["segments"],
        expected_facts,
        candidate_facts,
        audience,
        reference["guarded_markers"],
        diagnostics,
    )
    _validate_hierarchy(segment_bindings, diagnostics)

    return _report(diagnostics)


def build_staged_arrival_projections(
    bundle: object, *, audience: object = "public"
) -> dict[str, dict[str, Any]]:
    """Validate an R10 fixture, then return its matched A/B/C/D projections."""

    report = validate_staged_arrival(bundle, audience=audience)
    if not report.is_valid:
        raise StagedArrivalError(report.diagnostics[0])
    assert type(bundle) is dict

    from . import projections

    outputs = projections.build_matched_projections(
        bundle["candidate"], bundle["reference"], audience=audience
    )
    arrival_candidate = bundle["arrival_candidate"]
    arrival_reference = bundle["arrival_reference"]
    fact_map = {fact["id"]: fact for fact in bundle["candidate"]["facts"]}
    for condition, output in outputs.items():
        binding = {
            "fixture_id": arrival_reference["fixture_id"],
            "source_provenance": copy.deepcopy(arrival_candidate["source_provenance"]),
            "metadata": copy.deepcopy(arrival_candidate["metadata"]),
            "orientation": copy.deepcopy(arrival_candidate["orientation"]),
            "cue_states": copy.deepcopy(arrival_candidate["cue_states"]),
            "next_section": copy.deepcopy(arrival_candidate["next_section"]),
        }
        if condition == "D":
            binding["claims"] = _render_claim_bindings(
                arrival_candidate["claims"], fact_map
            )
        output["arrival_binding"] = binding
        output["arrival_sha256"] = hashlib.sha256(
            _canonical_json(binding).encode("ascii")
        ).hexdigest()
    return outputs


def _validate_source_and_metadata(
    reference: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    diagnostics: list[ArrivalDiagnostic],
) -> None:
    provenance = reference["source_provenance"]
    expected_fields = {
        "source_ref",
        "path",
        "section",
        "sha256",
        "source_kind",
        "legacy_truth_verified",
    }
    if not _record(provenance, expected_fields, "$.arrival_reference.source_provenance", diagnostics):
        return
    for key in ("source_ref", "path", "section"):
        value = provenance[key]
        if type(value) is not str or not value or len(value) > 512 or not value.isascii():
            _add(diagnostics, "ARRIVAL_SOURCE_PROVENANCE", "arrival", "$.arrival_reference.source_provenance." + key)
    digest = provenance["sha256"]
    if type(digest) is not str or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        _add(diagnostics, "ARRIVAL_SOURCE_HASH", "arrival", "$.arrival_reference.source_provenance.sha256")
    if provenance["source_kind"] != "owner_feedback" or provenance["legacy_truth_verified"] is not False:
        _add(diagnostics, "ARRIVAL_SOURCE_AUTHORITY", "arrival", "$.arrival_reference.source_provenance")

    metadata = reference["metadata"]
    metadata_fields = {
        "authorship",
        "development_only",
        "held_out",
        "legacy_truth_verified",
        "llm_builder_tested",
    }
    if not _record(metadata, metadata_fields, "$.arrival_reference.metadata", diagnostics):
        return
    if metadata != {
        "authorship": "builder_authored_initial_scene",
        "development_only": True,
        "held_out": False,
        "legacy_truth_verified": False,
        "llm_builder_tested": False,
    }:
        _add(diagnostics, "ARRIVAL_DEVELOPMENT_BOUNDARY", "arrival", "$.arrival_reference.metadata")

    source_ref = provenance.get("source_ref")
    for fact_id, fact in facts.items():
        fact_provenance = fact.get("provenance")
        if type(fact_provenance) is not dict:
            continue
        source_refs = fact_provenance.get("source_refs")
        if fact_provenance.get("class") == "builder_authored" and (
            type(source_refs) is not list or source_ref not in source_refs
        ):
            _add(
                diagnostics,
                "ARRIVAL_BUILDER_PROVENANCE_MISSING",
                "arrival",
                "$.arrival_reference.facts[" + fact_id + "].provenance.source_refs",
                fact_id,
            )


def _validate_orientation(
    candidate: object,
    reference: object,
    approved_frames: object,
    source_provenance: object,
    diagnostics: list[ArrivalDiagnostic],
) -> dict[str, Any]:
    fields = {"status", "frame", "provenance"}
    if not _record(reference, fields, "$.arrival_reference.orientation", diagnostics):
        return {}
    if not _record(candidate, fields, "$.arrival_candidate.orientation", diagnostics):
        return {}
    if candidate != reference:
        _add(diagnostics, "ARRIVAL_ORIENTATION_MISMATCH", "arrival", "$.arrival_candidate.orientation")

    if (
        type(approved_frames) is not list
        or len(approved_frames) > 16
        or any(type(frame) is not str or not frame or not frame.isascii() for frame in approved_frames)
        or len(set(frame for frame in approved_frames if type(frame) is str)) != len(approved_frames)
    ):
        _add(diagnostics, "ARRIVAL_COMPASS_FRAMES", "schema", "$.arrival_reference.approved_compass_frames")
        return copy.deepcopy(candidate)

    provenance = candidate["provenance"]
    if not _record(provenance, {"class", "source_refs"}, "$.arrival_candidate.orientation.provenance", diagnostics):
        return copy.deepcopy(candidate)
    if candidate["status"] == "unknown":
        if candidate["frame"] is not None or provenance["class"] != "unknown" or provenance["source_refs"]:
            _add(diagnostics, "ARRIVAL_ORIENTATION_UNKNOWN", "arrival", "$.arrival_candidate.orientation")
    elif candidate["status"] == "known":
        if candidate["frame"] not in approved_frames:
            _add(diagnostics, "ARRIVAL_ORIENTATION_FRAME_UNAPPROVED", "arrival", "$.arrival_candidate.orientation.frame")
        if provenance["class"] != "builder_authored":
            _add(diagnostics, "ARRIVAL_ORIENTATION_PROVENANCE", "arrival", "$.arrival_candidate.orientation.provenance.class")
        source_ref = source_provenance.get("source_ref") if type(source_provenance) is dict else None
        refs = provenance["source_refs"]
        if type(refs) is not list or source_ref not in refs:
            _add(diagnostics, "ARRIVAL_ORIENTATION_PROVENANCE", "arrival", "$.arrival_candidate.orientation.provenance.source_refs")
    else:
        _add(diagnostics, "ARRIVAL_ORIENTATION_STATUS", "arrival", "$.arrival_candidate.orientation.status")
    return copy.deepcopy(candidate)


def _validate_cue_states(
    candidate: object,
    reference: object,
    facts: dict[str, dict[str, Any]],
    diagnostics: list[ArrivalDiagnostic],
) -> list[dict[str, Any]]:
    if type(candidate) is not list or type(reference) is not list or len(candidate) != len(_CUES) or len(reference) != len(_CUES):
        _add(diagnostics, "ARRIVAL_CUE_STATES", "arrival", "$.arrival_candidate.cue_states")
        return []
    result: list[dict[str, Any]] = []
    for index, cue in enumerate(_CUES):
        path = "$.arrival_candidate.cue_states[%d]" % index
        expected_path = "$.arrival_reference.cue_states[%d]" % index
        expected_keys = {"cue", "status", "fact_id", "reason"}
        if not _record(reference[index], expected_keys, expected_path, diagnostics):
            continue
        if not _record(candidate[index], expected_keys, path, diagnostics):
            continue
        item = candidate[index]
        expected = reference[index]
        if item != expected or item.get("cue") != cue:
            _add(diagnostics, "ARRIVAL_CUE_STATE_MISMATCH", "arrival", path, _string(item.get("fact_id")))
            continue
        status = item["status"]
        fact_id = item["fact_id"]
        reason = item["reason"]
        if status == "not_applicable":
            if fact_id is not None or type(reason) is not str or not reason.strip() or len(reason) > _MAX_TEXT:
                _add(diagnostics, "ARRIVAL_CUE_NONAPPLICABLE", "arrival", path, _string(fact_id))
        elif status in ("known", "unknown"):
            fact = facts.get(fact_id) if type(fact_id) is str else None
            if fact is None:
                _add(diagnostics, "ARRIVAL_CUE_FACT_MISSING", "projection", path + ".fact_id", _string(fact_id))
            elif fact.get("predicate") != cue + "_gradient" or fact.get("status") != status:
                _add(diagnostics, "FABRICATED_CUE_GRADIENT", "projection", "$.candidate.facts[" + _string(fact_id) + "]", _string(fact_id))
            elif status == "known" and (
                fact.get("audience") != "public"
                or fact.get("provenance", {}).get("class") != "builder_authored"
                or type(fact.get("value")) is not str
            ):
                _add(diagnostics, "ARRIVAL_CUE_FACT_INVALID", "arrival", path + ".fact_id", _string(fact_id))
            elif status == "unknown" and (
                fact.get("value") is not None
                or fact.get("provenance", {}).get("class") != "unknown"
            ):
                _add(diagnostics, "FABRICATED_CUE_GRADIENT", "projection", "$.candidate.facts[" + _string(fact_id) + "]", _string(fact_id))
            if reason is not None and (type(reason) is not str or not reason.strip() or len(reason) > _MAX_TEXT):
                _add(diagnostics, "ARRIVAL_CUE_REASON", "arrival", path + ".reason", _string(fact_id))
        else:
            _add(diagnostics, "ARRIVAL_CUE_STATUS", "arrival", path + ".status", _string(fact_id))
        result.append(copy.deepcopy(item))
    return result


def _validate_next_section(
    candidate: object,
    reference: object,
    facts: dict[str, dict[str, Any]],
    topology: object,
    diagnostics: list[ArrivalDiagnostic],
) -> dict[str, Any]:
    fields = {
        "status",
        "from_scene_id",
        "to_scene_id",
        "transition_fact_id",
        "perception_fact_id",
        "perception_status",
        "reason",
    }
    if not _record(reference, fields, "$.arrival_reference.next_section", diagnostics):
        return {}
    if not _record(candidate, fields, "$.arrival_candidate.next_section", diagnostics):
        return {}
    if candidate != reference:
        _add(diagnostics, "ARRIVAL_TRANSITION_REFERENCE_MISMATCH", "arrival", "$.arrival_candidate.next_section", _string(candidate.get("transition_fact_id")))
        return {}
    if candidate["status"] == "not_applicable":
        if (
            any(candidate[key] is not None for key in ("from_scene_id", "to_scene_id", "transition_fact_id", "perception_fact_id", "perception_status"))
            or type(candidate["reason"]) is not str
            or not candidate["reason"].strip()
        ):
            _add(diagnostics, "ARRIVAL_TRANSITION_NONAPPLICABLE", "arrival", "$.arrival_candidate.next_section")
        return copy.deepcopy(candidate)
    if candidate["status"] != "known" or candidate["reason"] is not None:
        _add(diagnostics, "ARRIVAL_TRANSITION_STATUS", "arrival", "$.arrival_candidate.next_section.status", _string(candidate.get("transition_fact_id")))
        return copy.deepcopy(candidate)

    transition_id = candidate["transition_fact_id"]
    perception_id = candidate["perception_fact_id"]
    transition = facts.get(transition_id) if type(transition_id) is str else None
    perception = facts.get(perception_id) if type(perception_id) is str else None
    if transition is None or transition.get("predicate") != "transition_to_next_section" or transition.get("status") != "known":
        _add(diagnostics, "ARRIVAL_TRANSITION_FACT_INVALID", "projection", "$.candidate.facts[" + _string(transition_id) + "]", _string(transition_id))
    if perception is None or perception.get("predicate") != "perception_of_next_section" or perception.get("status") != "known":
        _add(diagnostics, "ARRIVAL_PERCEPTION_FACT_INVALID", "projection", "$.candidate.facts[" + _string(perception_id) + "]", _string(perception_id))
    if transition is not None and (
        transition.get("subject_id") != candidate["from_scene_id"]
        or transition.get("object_id") != candidate["to_scene_id"]
    ):
        _add(diagnostics, "ARRIVAL_TRANSITION_FACT_ENDPOINTS", "projection", "$.candidate.facts[" + _string(transition_id) + "]", _string(transition_id))
    if candidate["perception_status"] not in ("visible", "partially_visible"):
        _add(diagnostics, "ARRIVAL_PERCEPTION_STATUS", "arrival", "$.arrival_candidate.next_section.perception_status", _string(perception_id))

    if type(topology) is dict and transition is not None:
        link_id = transition["id"]
        matching = [item for item in topology.get("links", []) if type(item) is dict and item.get("id") == link_id]
        if len(matching) != 1 or matching[0].get("from_scene_id") != candidate["from_scene_id"] or matching[0].get("to_scene_id") != candidate["to_scene_id"]:
            _add(diagnostics, "ARRIVAL_TRANSITION_TOPOLOGY", "projection", "$.candidate.topology.links[" + _string(link_id) + "]", _string(link_id))
        elif matching[0].get("relation") not in ("leads_to", "visible_transition"):
            _add(diagnostics, "ARRIVAL_TRANSITION_TOPOLOGY", "projection", "$.candidate.topology.links[" + _string(link_id) + "].relation", _string(link_id))
    if perception is not None and perception.get("object_id") != candidate["to_scene_id"]:
        _add(diagnostics, "ARRIVAL_PERCEPTION_TARGET", "arrival", "$.candidate.facts[" + _string(perception_id) + "].object_id", _string(perception_id))
    if perception is not None and type(topology) is dict:
        perceived_from_scene = perception.get("subject_id")
        visible_source_anchor = perceived_from_scene == candidate["from_scene_id"] or any(
            type(item) is dict
            and item.get("scene_id") == candidate["from_scene_id"]
            and item.get("anchor_id") == perceived_from_scene
            for item in topology.get("schematic_layout", [])
        )
        if not visible_source_anchor:
            _add(diagnostics, "ARRIVAL_PERCEPTION_SOURCE", "arrival", "$.candidate.facts[" + _string(perception_id) + "].subject_id", _string(perception_id))
    return copy.deepcopy(candidate)


def _validate_segments(
    candidate_segments: object,
    candidate_claims: object,
    reference_segments: object,
    expected_facts: dict[str, dict[str, Any]],
    candidate_facts: dict[str, dict[str, Any]],
    audience: str,
    guarded_markers: object,
    diagnostics: list[ArrivalDiagnostic],
) -> list[dict[str, Any]]:
    if (
        type(candidate_segments) is not list
        or type(candidate_claims) is not list
        or type(reference_segments) is not list
        or len(candidate_segments) != 3
        or len(candidate_claims) != 3
        or len(reference_segments) != 3
    ):
        _add(diagnostics, "ARRIVAL_SEGMENTS", "schema", "$.candidate.arrival_segments")
        return []
    claim_groups: dict[str, dict[str, Any]] = {}
    for index, group in enumerate(candidate_claims):
        path = "$.arrival_candidate.claims[%d]" % index
        if not _record(group, {"segment_id", "claims"}, path, diagnostics):
            continue
        segment_id = group["segment_id"]
        if type(segment_id) is not str or segment_id in claim_groups:
            _add(diagnostics, "ARRIVAL_CLAIM_SEGMENT_ID", "schema", path + ".segment_id")
            continue
        claim_groups[segment_id] = group

    result: list[dict[str, Any]] = []
    if type(guarded_markers) is not list or len(guarded_markers) > 16:
        _add(diagnostics, "ARRIVAL_GUARDED_MARKERS", "schema", "$.arrival_reference.guarded_markers")
        guarded_markers = []
    for index, role in enumerate(_ROLES):
        segment = candidate_segments[index]
        expected = reference_segments[index]
        path = "$.candidate.arrival_segments[%d]" % index
        expected_path = "$.arrival_reference.segments[%d]" % index
        if not _record(segment, {"id", "role", "text", "fact_ids"}, path, diagnostics):
            continue
        if not _record(expected, {"id", "role", "text_sha256", "fact_ids", "claims"}, expected_path, diagnostics):
            continue
        if segment["role"] != role or expected["role"] != role or segment["id"] != expected["id"]:
            _add(diagnostics, "ARRIVAL_ROLE_ORDER", "render", path + ".role")
            continue
        text = segment["text"]
        if type(text) is not str or not text.strip() or len(text) > _MAX_SEGMENT_TEXT or not text.isascii():
            _add(diagnostics, "ARRIVAL_TEXT", "schema", path + ".text")
            continue
        segment_id = segment["id"]
        group = claim_groups.get(segment_id)
        if group is None:
            _add(diagnostics, "ARRIVAL_CLAIMS_MISSING", "arrival", "$.arrival_candidate.claims[" + segment_id + "]")
            continue
        approved_claims = expected["claims"]
        claims = group["claims"]
        if type(claims) is not list or type(approved_claims) is not list or len(claims) > 32 or len(claims) != len(approved_claims):
            _add(diagnostics, "ARRIVAL_CLAIMS_SHAPE", "schema", "$.arrival_candidate.claims[" + segment_id + "]")
            continue
        if segment["fact_ids"] != expected["fact_ids"] or type(segment["fact_ids"]) is not list:
            _add(diagnostics, "ARRIVAL_FACT_BINDING_MISMATCH", "render", path + ".fact_ids")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if type(expected["text_sha256"]) is not str or digest != expected["text_sha256"]:
            _add(diagnostics, "ARRIVAL_TEXT_BINDING_MISMATCH", "render", path + ".text")
        for guard in guarded_markers:
            if not _record(guard, {"fact_id", "values"}, "$.arrival_reference.guarded_markers", diagnostics):
                continue
            values = guard["values"]
            if type(values) is not list or len(values) > 16:
                _add(diagnostics, "ARRIVAL_GUARDED_MARKERS", "schema", "$.arrival_reference.guarded_markers")
                continue
            if audience == "public" and any(type(value) is str and value and value in text for value in values):
                _add(diagnostics, "GUARDED_CONTENT_LEAK", "render", path + ".text", _string(guard["fact_id"]))
        reference_fact_ids: set[str] = set()
        for claim_index, (claim, approved) in enumerate(zip(claims, approved_claims)):
            claim_path = "$.arrival_candidate.claims[" + segment_id + "][%d]" % claim_index
            if not _record(claim, _CLAIM_KEYS, claim_path, diagnostics):
                continue
            if not _record(approved, _CLAIM_KEYS, expected_path + ".claims[%d]" % claim_index, diagnostics):
                continue
            fact_id = claim["fact_id"] if type(claim["fact_id"]) is str else ""
            expected_fact = expected_facts.get(fact_id)
            actual_fact = candidate_facts.get(fact_id)
            if claim.get("kind") == "invitation" and (
                claim.get("choice") != "open" or claim.get("success") != "unspecified"
            ):
                _add(diagnostics, "ARRIVAL_AGENCY_VIOLATION", "arrival", claim_path + ".choice", fact_id)
            if claim.get("kind") == "cue_gradient" and (
                claim.get("status") != "known" or claim.get("value") is None
            ):
                _add(diagnostics, "FABRICATED_CUE_GRADIENT", "arrival", claim_path + ".value", fact_id)
            if claim != approved:
                code = "FABRICATED_CUE_GRADIENT" if _is_cue_predicate(claim.get("predicate")) else "ARRIVAL_CLAIM_BINDING_MISMATCH"
                differing_field = _first_difference(claim, approved)
                _add(diagnostics, code, "arrival", claim_path + "." + differing_field, fact_id)
            if expected_fact is None or actual_fact is None:
                _add(diagnostics, "ARRIVAL_CLAIM_FACT_MISSING", "projection", claim_path + ".fact_id", fact_id)
            else:
                for field in _FACT_BINDING_FIELDS:
                    expected_value = expected_fact.get(field)
                    claim_field = "fact_id" if field == "id" else field
                    if claim.get(claim_field) != expected_value:
                        code = "FABRICATED_CUE_GRADIENT" if _is_cue_predicate(expected_fact.get("predicate")) else "ARRIVAL_CLAIM_BINDING_MISMATCH"
                        _add(diagnostics, code, "arrival", claim_path + "." + claim_field, fact_id)
                        break
                    if actual_fact.get(field) != expected_value:
                        code = "FABRICATED_CUE_GRADIENT" if _is_cue_predicate(expected_fact.get("predicate")) else "ARRIVAL_FACT_MISMATCH"
                        _add(diagnostics, code, "projection", "$.candidate.facts[" + fact_id + "]." + field, fact_id)
                        break
            span = claim.get("span")
            if type(span) is not str or not span or len(span) > _MAX_TEXT or span not in text:
                _add(diagnostics, "ARRIVAL_CLAIM_SPAN", "render", claim_path + ".span", fact_id)
            if fact_id:
                if fact_id in reference_fact_ids:
                    _add(diagnostics, "ARRIVAL_CLAIM_DUPLICATE_FACT", "arrival", claim_path + ".fact_id", fact_id)
                reference_fact_ids.add(fact_id)
        if type(segment["fact_ids"]) is list:
            candidate_fact_ids = segment["fact_ids"]
            if any(type(fact_id) is not str for fact_id in candidate_fact_ids):
                _add(diagnostics, "ARRIVAL_FACT_BINDING_MISMATCH", "render", path + ".fact_ids")
            else:
                for fact_id in sorted(set(candidate_fact_ids) ^ reference_fact_ids):
                    _add(diagnostics, "ARRIVAL_CLAIM_FACT_SET_MISMATCH", "arrival", path + ".fact_ids", _string(fact_id))
        result.append({"id": segment_id, "role": role, "claims": copy.deepcopy(claims)})
    return result


def _validate_hierarchy(
    segment_bindings: list[dict[str, Any]], diagnostics: list[ArrivalDiagnostic]
) -> None:
    if len(segment_bindings) != 3:
        return
    first = segment_bindings[0]["claims"]
    second = segment_bindings[1]["claims"]
    if not any(type(item) is dict and item.get("kind") == "stage_relation" and item.get("predicate") == "approach_to_threshold" for item in first):
        _add(diagnostics, "ARRIVAL_HIERARCHY_MISSING", "arrival", "$.arrival_candidate.claims[" + segment_bindings[0]["id"] + "]")
    if not any(type(item) is dict and item.get("kind") == "stage_relation" and item.get("predicate") == "threshold_to_focal" for item in second):
        _add(diagnostics, "ARRIVAL_HIERARCHY_MISSING", "arrival", "$.arrival_candidate.claims[" + segment_bindings[1]["id"] + "]")
    if not any(type(item) is dict and item.get("kind") == "invitation" for item in segment_bindings[2]["claims"]):
        _add(diagnostics, "ARRIVAL_INVITATION_MISSING", "arrival", "$.arrival_candidate.claims[" + segment_bindings[2]["id"] + "]")


def _compare_facts(
    expected: dict[str, dict[str, Any]],
    observed: dict[str, dict[str, Any]],
    diagnostics: list[ArrivalDiagnostic],
) -> None:
    for fact_id in sorted(set(expected) | set(observed)):
        path = "$.candidate.facts[" + fact_id + "]"
        if fact_id not in observed:
            _add(diagnostics, "ARRIVAL_FACT_MISSING", "projection", path, fact_id)
            continue
        if fact_id not in expected:
            code = "FABRICATED_CUE_GRADIENT" if _is_cue_predicate(observed[fact_id].get("predicate")) else "ARRIVAL_FACT_UNAPPROVED"
            _add(diagnostics, code, "projection", path, fact_id)
            continue
        if observed[fact_id] != expected[fact_id]:
            field = _first_difference(observed[fact_id], expected[fact_id])
            code = "FABRICATED_CUE_GRADIENT" if _is_cue_predicate(expected[fact_id].get("predicate")) else "ARRIVAL_FACT_MISMATCH"
            _add(diagnostics, code, "projection", path + "." + field, fact_id)


def _compare_topology(
    observed: dict[str, Any],
    expected: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    diagnostics: list[ArrivalDiagnostic],
) -> None:
    groups = {
        "scene_nodes": "id",
        "links": "id",
        "schematic_layout": "anchor_id",
    }
    if set(observed) != set(groups) or set(expected) != set(groups):
        _add(diagnostics, "ARRIVAL_TOPOLOGY_SHAPE", "schema", "$.candidate.topology")
        return
    placement_fact_ids = {
        fact.get("subject_id"): fact_id
        for fact_id, fact in facts.items()
        if fact.get("predicate") == "anchor_position"
    }
    for group, id_key in groups.items():
        observed_map = _topology_map(observed.get(group), id_key, "$.candidate.topology." + group, diagnostics)
        expected_map = _topology_map(expected.get(group), id_key, "$.arrival_reference.topology." + group, diagnostics)
        for record_id in sorted(set(observed_map) | set(expected_map)):
            path = "$.candidate.topology." + group + "[" + record_id + "]"
            if record_id not in expected_map:
                _add(diagnostics, "ARRIVAL_TOPOLOGY_UNAPPROVED", "projection", path, record_id if group == "links" else "")
                continue
            if record_id not in observed_map:
                code = "ARRIVAL_ANCHOR_RELOCATED" if group == "schematic_layout" else "ARRIVAL_TOPOLOGY_MISMATCH"
                fact_id = placement_fact_ids.get(record_id, "") if group == "schematic_layout" else (record_id if group == "links" else "")
                _add(diagnostics, code, "projection", path, fact_id)
                continue
            if observed_map[record_id] != expected_map[record_id]:
                code = "ARRIVAL_ANCHOR_RELOCATED" if group == "schematic_layout" else "ARRIVAL_TOPOLOGY_MISMATCH"
                fact_id = placement_fact_ids.get(record_id, "") if group == "schematic_layout" else (record_id if group == "links" else "")
                _add(diagnostics, code, "projection", path, fact_id)


def _topology_map(
    value: object,
    id_key: str,
    path: str,
    diagnostics: list[ArrivalDiagnostic],
) -> dict[str, dict[str, Any]]:
    if type(value) is not list or len(value) > _MAX_RECORDS:
        _add(diagnostics, "ARRIVAL_TOPOLOGY_GROUP", "schema", path)
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict or type(item.get(id_key)) is not str:
            _add(diagnostics, "ARRIVAL_TOPOLOGY_RECORD", "schema", item_path)
            continue
        identifier = item[id_key]
        if identifier in result:
            _add(diagnostics, "ARRIVAL_TOPOLOGY_DUPLICATE", "schema", item_path + "." + id_key)
            continue
        result[identifier] = item
    return result


def _check_projection_reference(
    projection_reference: dict[str, Any],
    arrival_reference: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    diagnostics: list[ArrivalDiagnostic],
) -> None:
    expected_digests = {
        fact_id: hashlib.sha256(_canonical_json(fact).encode("ascii")).hexdigest()
        for fact_id, fact in facts.items()
    }
    if projection_reference.get("fact_digests") != expected_digests:
        _add(diagnostics, "ARRIVAL_REFERENCE_FACT_BINDING", "projection", "$.reference.fact_digests")
    expected_topology = arrival_reference["topology"]
    topology_by_audience = projection_reference.get("topology_by_audience")
    if type(topology_by_audience) is not dict:
        _add(diagnostics, "ARRIVAL_REFERENCE_TOPOLOGY_BINDING", "projection", "$.reference.topology_by_audience")
        topology_by_audience = {}
    for audience in ("public", "gm_narrator"):
        if topology_by_audience.get(audience) != expected_topology:
            _add(diagnostics, "ARRIVAL_REFERENCE_TOPOLOGY_BINDING", "projection", "$.reference.topology_by_audience." + audience)
    approvals = projection_reference.get("arrival_approvals")
    expected_segments = arrival_reference["segments"]
    if (
        type(approvals) is not list
        or type(expected_segments) is not list
        or len(approvals) != len(expected_segments)
    ):
        _add(diagnostics, "ARRIVAL_REFERENCE_APPROVALS", "projection", "$.reference.arrival_approvals")
        return
    for index, (approval, segment) in enumerate(zip(approvals, expected_segments)):
        path = "$.reference.arrival_approvals[%d]" % index
        expected_approval = {
            "id": segment.get("id"),
            "role": segment.get("role"),
            "text_sha256": segment.get("text_sha256"),
            "fact_ids": segment.get("fact_ids"),
        }
        if approval != expected_approval:
            _add(diagnostics, "ARRIVAL_REFERENCE_APPROVAL_MISMATCH", "projection", path)


def _fact_map(
    value: object, path: str, diagnostics: list[ArrivalDiagnostic]
) -> dict[str, dict[str, Any]]:
    if type(value) is not list or len(value) > _MAX_FACTS:
        _add(diagnostics, "ARRIVAL_FACTS_SHAPE", "schema", path)
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, fact in enumerate(value):
        item_path = "%s[%d]" % (path, index)
        if (
            type(fact) is not dict
            or len(fact) > 32
            or any(type(key) is not str for key in fact)
            or type(fact.get("id")) is not str
        ):
            _add(diagnostics, "ARRIVAL_FACT_SHAPE", "schema", item_path)
            continue
        fact_id = fact["id"]
        if fact_id in result:
            _add(diagnostics, "ARRIVAL_FACT_DUPLICATE", "schema", item_path + ".id", fact_id)
            continue
        result[fact_id] = fact
    return result


def _render_claim_bindings(
    claim_groups: list[dict[str, Any]], facts: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for group in claim_groups:
        for claim in group["claims"]:
            fact = facts[claim["fact_id"]]
            rendered.append(
                {
                    "segment_id": group["segment_id"],
                    "claim_id": claim["id"],
                    "kind": claim["kind"],
                    "span": claim["span"],
                    "fact_id": fact["id"],
                    "predicate": fact["predicate"],
                    "subject_id": fact["subject_id"],
                    "object_id": fact["object_id"],
                    "status": fact["status"],
                    "value": fact["value"],
                    "provenance": copy.deepcopy(fact["provenance"]),
                    "choice": claim["choice"],
                    "success": claim["success"],
                }
            )
    return rendered


def _compare_exact(
    observed: object,
    expected: object,
    code: str,
    layer: str,
    path: str,
    diagnostics: list[ArrivalDiagnostic],
) -> None:
    if observed != expected:
        _add(diagnostics, code, layer, path)


def _record(
    value: object,
    expected_keys: set[str],
    path: str,
    diagnostics: list[ArrivalDiagnostic],
) -> bool:
    if type(value) is not dict or len(value) > 32 or any(type(key) is not str for key in value):
        _add(diagnostics, "ARRIVAL_RECORD_SHAPE", "schema", path)
        return False
    if set(value) != expected_keys:
        differing = sorted(set(value) ^ expected_keys)
        _add(diagnostics, "ARRIVAL_RECORD_FIELDS", "schema", path + ("." + differing[0] if differing else ""))
        return False
    return True


def _first_difference(observed: dict[str, Any], expected: dict[str, Any]) -> str:
    for key in sorted(set(observed) | set(expected)):
        if observed.get(key) != expected.get(key):
            return key
    return "value"


def _is_cue_predicate(value: object) -> bool:
    return type(value) is str and value in _CUE_PREDICATES


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _string(value: object) -> str:
    return value if type(value) is str else ""


def _add(
    diagnostics: list[ArrivalDiagnostic],
    code: str,
    layer: str,
    path: str,
    fact_id: str = "",
) -> None:
    diagnostics.append(ArrivalDiagnostic(code, layer, path, fact_id))


def _report(diagnostics: list[ArrivalDiagnostic]) -> ArrivalReport:
    return ArrivalReport(
        tuple(sorted(diagnostics, key=lambda item: (item.layer, item.path, item.code, item.fact_id)))
    )
