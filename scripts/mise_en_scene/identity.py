# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Bounded provider-free checks for linked scene identity and movement examples."""

from __future__ import annotations

import re
from typing import Any

from . import contract
from .contract import Diagnostic, ValidationResult


_ENTITY_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:entity:[a-z0-9][a-z0-9_-]{0,63}$"
)
_FACT_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:fact:[a-z0-9][a-z0-9_-]{0,63}$"
)
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_ITEMS = 64
_MAX_FIELDS = 32
_MAX_COORDINATE = 1_000_000
_DIRECTIONS = {"north", "east", "south", "west"}
_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
_BEARING_FIELDS = {
    "id",
    "from_view_id",
    "to_view_id",
    "direction",
    "compass_frame",
    "verification_basis",
}
_FORBIDDEN_SCENE_PREDICATES = {
    "access",
    "acoustic",
    "audibility",
    "audible",
    "audible_from",
    "ambient_sound",
    "door",
    "door_exists",
    "doorway",
    "distance",
    "entrance",
    "exit",
    "line_of_sight",
    "light",
    "light_gradient",
    "movement_cost",
    "perception",
    "scale",
    "sensory_reach",
    "sensory_gradient",
    "sight_line",
    "sightline",
    "sound",
    "sound_gradient",
    "sound_reach",
    "traversability",
    "traversable",
    "traversal",
    "visibility",
    "visibility_gradient",
    "visible",
    "visible_from",
    "weather",
    "weather_gradient",
}


def validate_linked_views(bundle: object) -> ValidationResult:
    """Check candidate view identities, frontages, and bearings against a reference.

    ``reference`` is independent fixture data, not a label copied from the
    candidate. Each view carries its own approved topology and is validated by
    the base fixture contract before cross-view references are considered.
    """

    diagnostics: list[Diagnostic] = []
    if type(bundle) is not dict:
        return ValidationResult((Diagnostic("BUNDLE_TYPE", "$"),))
    _shape(
        bundle,
        {
            "schema_version",
            "reference",
            "views",
            "identity_links",
            "frontages",
            "bearings",
            "metadata",
        },
        "$",
        diagnostics,
    )
    if type(bundle.get("schema_version")) is not int or bundle.get("schema_version") != 1:
        diagnostics.append(Diagnostic("SCHEMA_VERSION", "$.schema_version"))

    _validate_metadata(bundle.get("metadata"), diagnostics)
    reference = _parse_reference(bundle.get("reference"), diagnostics)
    views, view_contexts = _parse_views(bundle.get("views"), diagnostics)

    _validate_occurrences(
        reference, bundle.get("identity_links"), views, view_contexts, diagnostics
    )
    _validate_frontages(
        reference, bundle.get("frontages"), set(views), diagnostics
    )
    _validate_bearings(
        reference,
        bundle.get("bearings"),
        view_contexts,
        diagnostics,
    )
    _validate_forbidden_scene_facts(views, diagnostics)
    return ValidationResult(tuple(diagnostics))


def validate_occupant_movement(before: object, after: object) -> ValidationResult:
    """Validate a before/after mobile-occupant example without changing inputs.

    Fixed-anchor IDs, kinds, and schematic positions must be identical. Mobile
    occupant IDs and kinds remain stable, and at least one existing occupant's
    position must change. This demonstrates fixture semantics only; it does not
    move runtime state.
    """

    diagnostics: list[Diagnostic] = []
    before_state = _parse_movement_state(before, "$.before", diagnostics)
    after_state = _parse_movement_state(after, "$.after", diagnostics)
    if before_state is None or after_state is None:
        return ValidationResult(tuple(diagnostics))

    before_anchors, before_occupants = before_state
    after_anchors, after_occupants = after_state
    for anchor_id in sorted(before_anchors.keys() - after_anchors.keys()):
        diagnostics.append(
            Diagnostic("FIXED_ANCHOR_MISSING", "$.after.fixed_anchors")
        )
    for anchor_id in sorted(after_anchors.keys() - before_anchors.keys()):
        diagnostics.append(
            Diagnostic("FIXED_ANCHOR_ADDED", "$.after.fixed_anchors")
        )
    for anchor_id in sorted(before_anchors.keys() & after_anchors.keys()):
        old = before_anchors[anchor_id]
        new = after_anchors[anchor_id]
        if old[0] != new[0]:
            diagnostics.append(
                Diagnostic(
                    "FIXED_ANCHOR_CHANGED",
                    "$.after.fixed_anchors[%s].kind" % anchor_id,
                )
            )
        if old[1] != new[1]:
            diagnostics.append(
                Diagnostic(
                    "FIXED_ANCHOR_RELOCATED",
                    "$.after.fixed_anchors[%s].position" % anchor_id,
                )
            )

    missing_occupants = before_occupants.keys() - after_occupants.keys()
    added_occupants = after_occupants.keys() - before_occupants.keys()
    if missing_occupants or added_occupants:
        diagnostics.append(
            Diagnostic(
                "MOBILE_OCCUPANT_IDENTITY_CHANGED",
                "$.after.mobile_occupants",
            )
        )
    moved = False
    for occupant_id in sorted(before_occupants.keys() & after_occupants.keys()):
        old = before_occupants[occupant_id]
        new = after_occupants[occupant_id]
        if old[0] != new[0]:
            diagnostics.append(
                Diagnostic(
                    "MOBILE_OCCUPANT_KIND_CHANGED",
                    "$.after.mobile_occupants[%s].kind" % occupant_id,
                )
            )
        if old[1] != new[1]:
            moved = True
    if not moved:
        diagnostics.append(
            Diagnostic("MOBILE_OCCUPANT_NOT_MOVED", "$.after.mobile_occupants")
        )
    return ValidationResult(tuple(diagnostics))


def _validate_metadata(value: object, diagnostics: list[Diagnostic]) -> None:
    path = "$.metadata"
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return
    _shape(
        value,
        {
            "development_only",
            "held_out",
            "source_verified",
            "synthetic_party_metadata",
        },
        path,
        diagnostics,
    )
    if value.get("development_only") is not True:
        diagnostics.append(Diagnostic("DEVELOPMENT_ONLY_REQUIRED", path + ".development_only"))
    if value.get("held_out") is not False:
        diagnostics.append(Diagnostic("HELD_OUT_FIXTURE", path + ".held_out"))
    if value.get("source_verified") is not False:
        diagnostics.append(Diagnostic("SOURCE_VERIFICATION_CLAIM", path + ".source_verified"))

    party = value.get("synthetic_party_metadata")
    party_path = path + ".synthetic_party_metadata"
    if type(party) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", party_path))
        return
    _shape(party, {"party_shape", "member_count"}, party_path, diagnostics)
    party_shape = party.get("party_shape")
    member_count = party.get("member_count")
    if (
        type(party_shape) is not str
        or not party_shape
        or len(party_shape) > 16
        or not party_shape.isascii()
        or type(member_count) is not int
        or member_count < 1
        or member_count > _MAX_ITEMS
    ):
        diagnostics.append(Diagnostic("SYNTHETIC_PARTY_METADATA", party_path))


def _parse_reference(
    value: object, diagnostics: list[Diagnostic]
) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "entities": {},
        "occurrences": {},
        "frontages": {},
        "bearings": {},
    }
    path = "$.reference"
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return parsed
    _shape(value, {"canonical_entities", "occurrences", "frontages", "bearings"}, path, diagnostics)

    entities = value.get("canonical_entities")
    entity_path = path + ".canonical_entities"
    if type(entities) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", entity_path))
    else:
        if len(entities) > _MAX_ITEMS:
            diagnostics.append(Diagnostic("COLLECTION_LIMIT", entity_path))
        for index, item in enumerate(entities[:_MAX_ITEMS]):
            item_path = "%s[%d]" % (entity_path, index)
            if type(item) is not dict:
                diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
                continue
            _shape(item, {"id", "kind", "identity_scope"}, item_path, diagnostics)
            entity_id = _entity_id(item.get("id"), item_path + ".id", diagnostics)
            kind = item.get("kind")
            scope = item.get("identity_scope")
            if kind not in ("building", "frontage"):
                diagnostics.append(Diagnostic("CANONICAL_ENTITY_KIND", item_path + ".kind"))
            if scope not in ("shared", "view_local"):
                diagnostics.append(Diagnostic("IDENTITY_SCOPE", item_path + ".identity_scope"))
            if entity_id is not None:
                if entity_id in parsed["entities"]:
                    diagnostics.append(Diagnostic("DUPLICATE_CANONICAL_ID", item_path + ".id"))
                else:
                    parsed["entities"][entity_id] = {
                        "kind": kind,
                        "identity_scope": scope,
                        "path": item_path,
                    }

    occurrences = value.get("occurrences")
    occurrence_path = path + ".occurrences"
    if type(occurrences) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", occurrence_path))
    else:
        if len(occurrences) > _MAX_ITEMS:
            diagnostics.append(Diagnostic("COLLECTION_LIMIT", occurrence_path))
        for index, item in enumerate(occurrences[:_MAX_ITEMS]):
            item_path = "%s[%d]" % (occurrence_path, index)
            parsed_item = _parse_occurrence(item, item_path, diagnostics)
            if parsed_item is None:
                continue
            key = (parsed_item["view_id"], parsed_item["fixture_entity_id"])
            if key in parsed["occurrences"]:
                diagnostics.append(Diagnostic("DUPLICATE_REFERENCE_OCCURRENCE", item_path))
            else:
                parsed["occurrences"][key] = parsed_item["canonical_entity_id"]

    parsed["frontages"] = _parse_frontages(
        value.get("frontages"), path + ".frontages", diagnostics
    )
    parsed["bearings"] = _parse_bearings(
        value.get("bearings"), path + ".bearings", diagnostics
    )
    _validate_reference_scopes(parsed, diagnostics)
    return parsed


def _parse_views(
    value: object, diagnostics: list[Diagnostic]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    views: dict[str, dict[str, Any]] = {}
    contexts: dict[str, dict[str, Any]] = {}
    path = "$.views"
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return views, contexts
    if len(value) > _MAX_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
            continue
        _shape(item, {"id", "fixture", "approved_topology", "consulted_source_refs"}, item_path, diagnostics)
        view_id = _token(item.get("id"), item_path + ".id", diagnostics)
        if view_id is None:
            continue
        if view_id in views:
            diagnostics.append(Diagnostic("DUPLICATE_VIEW_ID", item_path + ".id"))
            continue
        views[view_id] = item

        topology = item.get("approved_topology")
        fixture = item.get("fixture")
        refs = item.get("consulted_source_refs")
        if type(topology) is not contract.ApprovedTopology:
            diagnostics.append(Diagnostic("APPROVED_TOPOLOGY_TYPE", item_path + ".approved_topology"))
        if type(refs) not in (list, tuple):
            diagnostics.append(Diagnostic("CONSULTED_SOURCE_REFS_TYPE", item_path + ".consulted_source_refs"))
        if type(topology) is contract.ApprovedTopology and type(refs) in (list, tuple):
            result = contract.validate_fixture(fixture, topology, refs)
            for diagnostic in result.diagnostics:
                if diagnostic.path.startswith("$."):
                    suffix = diagnostic.path[1:]
                elif diagnostic.path.startswith("$"):
                    suffix = "." + diagnostic.path[1:]
                else:
                    suffix = "." + diagnostic.path
                diagnostics.append(
                    Diagnostic(diagnostic.code, item_path + ".fixture" + suffix)
                )
        anchor_kinds: dict[str, str] = {}
        if type(fixture) is dict and type(fixture.get("fixed_anchors")) is list:
            if len(fixture["fixed_anchors"]) > _MAX_ITEMS:
                diagnostics.append(
                    Diagnostic(
                        "COLLECTION_LIMIT",
                        item_path + ".fixture.fixed_anchors",
                    )
                )
            for anchor_index, anchor in enumerate(fixture["fixed_anchors"][:_MAX_ITEMS]):
                if type(anchor) is dict and type(anchor.get("id")) is str and type(anchor.get("kind")) is str:
                    anchor_kinds[anchor["id"]] = anchor["kind"]
        orientation = None
        if type(fixture) is dict and type(fixture.get("scene")) is dict:
            orientation = fixture["scene"].get("orientation")
        contexts[view_id] = {
            "topology": topology if type(topology) is contract.ApprovedTopology else None,
            "anchor_kinds": anchor_kinds,
            "orientation": orientation,
            "path": item_path,
        }
    return views, contexts


def _validate_occurrences(
    reference: dict[str, Any],
    value: object,
    views: dict[str, dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    diagnostics: list[Diagnostic],
) -> None:
    path = "$.identity_links"
    candidates: dict[tuple[str, str], str] = {}
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        value = []
    elif len(value) > _MAX_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        parsed = _parse_occurrence(item, item_path, diagnostics)
        if parsed is None:
            continue
        key = (parsed["view_id"], parsed["fixture_entity_id"])
        canonical_id = parsed["canonical_entity_id"]
        if key in candidates:
            diagnostics.append(Diagnostic("DUPLICATE_IDENTITY_LINK", item_path))
        else:
            candidates[key] = canonical_id
        if canonical_id not in reference["entities"]:
            diagnostics.append(Diagnostic("UNKNOWN_CANONICAL_REFERENCE", item_path + ".canonical_entity_id"))
        if parsed["view_id"] not in views:
            diagnostics.append(Diagnostic("UNKNOWN_VIEW_REFERENCE", item_path + ".view_id"))
        context = contexts.get(parsed["view_id"])
        if context is not None:
            kind = context["anchor_kinds"].get(parsed["fixture_entity_id"])
            if kind is None:
                diagnostics.append(Diagnostic("UNKNOWN_FIXTURE_ENTITY_REFERENCE", item_path + ".fixture_entity_id"))
            elif canonical_id in reference["entities"]:
                expected_kind = reference["entities"][canonical_id]["kind"]
                if kind != expected_kind:
                    diagnostics.append(Diagnostic("ENTITY_KIND_MISMATCH", item_path + ".fixture_entity_id"))

    expected = reference["occurrences"]
    for key in sorted(expected):
        if key not in candidates:
            diagnostics.append(Diagnostic("IDENTITY_REFERENCE_MISSING", path))
        elif candidates[key] != expected[key]:
            diagnostics.append(Diagnostic("IDENTITY_REFERENCE_MISMATCH", path))
    for key in sorted(candidates):
        if key not in expected:
            diagnostics.append(Diagnostic("UNSUPPORTED_IDENTITY_LINK", path))

    seen_by_view: set[tuple[str, str]] = set()
    for (view_id, _fixture_entity_id), canonical_id in sorted(candidates.items()):
        assignment = (view_id, canonical_id)
        if assignment in seen_by_view:
            diagnostics.append(Diagnostic("DUPLICATE_CANONICAL_ASSIGNMENT", path))
        seen_by_view.add(assignment)

    for view_id, view in views.items():
        fixture = view.get("fixture")
        if type(fixture) is not dict or type(fixture.get("fixed_anchors")) is not list:
            continue
        actual_ids = {
            anchor.get("id")
            for anchor in fixture["fixed_anchors"][:_MAX_ITEMS]
            if type(anchor) is dict and type(anchor.get("id")) is str
        }
        expected_ids = {
            fixture_entity_id
            for expected_view, fixture_entity_id in expected
            if expected_view == view_id
        }
        for _anchor_id in sorted(actual_ids - expected_ids):
            diagnostics.append(Diagnostic("UNLINKED_FIXED_ANCHOR", "$.views[%s].fixture.fixed_anchors" % view_id))


def _validate_reference_scopes(
    reference: dict[str, Any], diagnostics: list[Diagnostic]
) -> None:
    views_by_entity: dict[str, set[str]] = {}
    assignments: set[tuple[str, str]] = set()
    for (view_id, _fixture_entity_id), canonical_id in reference["occurrences"].items():
        views_by_entity.setdefault(canonical_id, set()).add(view_id)
        if canonical_id not in reference["entities"]:
            diagnostics.append(Diagnostic("UNKNOWN_CANONICAL_REFERENCE", "$.reference.occurrences"))
        assignment = (view_id, canonical_id)
        if assignment in assignments:
            diagnostics.append(
                Diagnostic("DUPLICATE_REFERENCE_CANONICAL_ASSIGNMENT", "$.reference.occurrences")
            )
        assignments.add(assignment)
    for canonical_id, entity in reference["entities"].items():
        view_count = len(views_by_entity.get(canonical_id, set()))
        if entity["identity_scope"] == "shared" and view_count < 2:
            diagnostics.append(Diagnostic("SHARED_IDENTITY_NOT_LINKED", entity["path"] + ".identity_scope"))
        elif entity["identity_scope"] == "view_local" and view_count != 1:
            diagnostics.append(Diagnostic("VIEW_LOCAL_IDENTITY_NOT_DISTINCT", entity["path"] + ".identity_scope"))


def _validate_frontages(
    reference: dict[str, Any],
    value: object,
    view_ids: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    path = "$.frontages"
    candidates = _parse_frontages(value, path, diagnostics)
    expected = reference["frontages"]
    for frontage_id in sorted(expected):
        if frontage_id not in candidates:
            diagnostics.append(Diagnostic("FRONTAGE_REFERENCE_MISSING", path))
        elif candidates[frontage_id] != expected[frontage_id]:
            diagnostics.append(Diagnostic("FRONTAGE_REFERENCE_MISMATCH", path))
    for frontage_id in sorted(candidates.keys() - expected.keys()):
        diagnostics.append(Diagnostic("UNSUPPORTED_FRONTAGE", path))
    seen_frontage_entities: set[str] = set()
    for item in candidates.values():
        if item["view_id"] not in view_ids:
            diagnostics.append(Diagnostic("UNKNOWN_VIEW_REFERENCE", path))
        frontage_entity_id = item["frontage_entity_id"]
        if frontage_entity_id in seen_frontage_entities:
            diagnostics.append(Diagnostic("FRONTAGE_IDENTITY_COLLAPSED", path))
        seen_frontage_entities.add(frontage_entity_id)
        canonical = reference["entities"].get(frontage_entity_id)
        if canonical is None or canonical["kind"] != "frontage":
            diagnostics.append(Diagnostic("FRONTAGE_ENTITY_REFERENCE", path))
        building = reference["entities"].get(item["building_entity_id"])
        if building is None or building["kind"] != "building":
            diagnostics.append(Diagnostic("FRONTAGE_BUILDING_REFERENCE", path))


def _validate_bearings(
    reference: dict[str, Any],
    value: object,
    contexts: dict[str, dict[str, Any]],
    diagnostics: list[Diagnostic],
) -> None:
    path = "$.bearings"
    candidates = _parse_bearings(value, path, diagnostics)
    expected = reference["bearings"]
    for bearing_id in sorted(expected):
        if bearing_id not in candidates:
            diagnostics.append(Diagnostic("BEARING_REFERENCE_MISSING", path))
        elif candidates[bearing_id] != expected[bearing_id]:
            diagnostics.append(Diagnostic("BEARING_REFERENCE_MISMATCH", path))
    for bearing_id in sorted(candidates.keys() - expected.keys()):
        diagnostics.append(Diagnostic("UNSUPPORTED_BEARING", path))

    _check_reciprocal_bearings(reference["bearings"], "$.reference.bearings", diagnostics)
    _check_reciprocal_bearings(candidates, path, diagnostics)
    for record_map in (reference["bearings"], candidates):
        for bearing in record_map.values():
            from_view = bearing["from_view_id"]
            to_view = bearing["to_view_id"]
            frame = bearing["compass_frame"]
            if from_view not in contexts or to_view not in contexts:
                diagnostics.append(Diagnostic("UNKNOWN_VIEW_REFERENCE", path))
            if type(frame) is not str or not frame:
                continue
            for view_id in (from_view, to_view):
                context = contexts.get(view_id)
                if context is None:
                    continue
                topology = context["topology"]
                if topology is None or frame not in topology.compass_frames:
                    diagnostics.append(Diagnostic("UNAPPROVED_COMPASS_FRAME", path))
                    continue
                orientation = context["orientation"]
                if (
                    type(orientation) is not dict
                    or orientation.get("status") != "known"
                    or orientation.get("frame") != frame
                ):
                    diagnostics.append(Diagnostic("BEARING_FRAME_UNKNOWN", path))


def _check_reciprocal_bearings(
    bearings: dict[str, dict[str, str]],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    records = list(bearings.values())
    for item in records:
        direction = item["direction"]
        if type(direction) is not str or direction not in _DIRECTIONS:
            continue
        reciprocal = [
            other
            for other in records
            if other["from_view_id"] == item["to_view_id"]
            and other["to_view_id"] == item["from_view_id"]
            and other["compass_frame"] == item["compass_frame"]
        ]
        if not reciprocal:
            diagnostics.append(Diagnostic("MISSING_RECIPROCAL_BEARING", path))
        elif not any(other["direction"] == _OPPOSITE[direction] for other in reciprocal):
            diagnostics.append(Diagnostic("NONRECIPROCAL_BEARING", path))


def _parse_occurrence(
    item: object, path: str, diagnostics: list[Diagnostic]
) -> dict[str, str] | None:
    if type(item) is not dict:
        diagnostics.append(Diagnostic("ITEM_TYPE", path))
        return None
    _shape(item, {"view_id", "canonical_entity_id", "fixture_entity_id"}, path, diagnostics)
    view_id = _token(item.get("view_id"), path + ".view_id", diagnostics)
    canonical_id = _entity_id(item.get("canonical_entity_id"), path + ".canonical_entity_id", diagnostics)
    fixture_id = _entity_id(item.get("fixture_entity_id"), path + ".fixture_entity_id", diagnostics)
    if view_id is None or canonical_id is None or fixture_id is None:
        return None
    return {
        "view_id": view_id,
        "canonical_entity_id": canonical_id,
        "fixture_entity_id": fixture_id,
    }


def _parse_frontages(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return parsed
    if len(value) > _MAX_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
            continue
        _shape(item, {"id", "view_id", "frontage_entity_id", "building_entity_id"}, item_path, diagnostics)
        relation_id = _fact_id(item.get("id"), item_path + ".id", diagnostics)
        view_id = _token(item.get("view_id"), item_path + ".view_id", diagnostics)
        frontage_id = _entity_id(item.get("frontage_entity_id"), item_path + ".frontage_entity_id", diagnostics)
        building_id = _entity_id(item.get("building_entity_id"), item_path + ".building_entity_id", diagnostics)
        if None in (relation_id, view_id, frontage_id, building_id):
            continue
        if relation_id in parsed:
            diagnostics.append(Diagnostic("DUPLICATE_FRONTAGE_ID", item_path + ".id"))
        else:
            parsed[relation_id] = {
                "id": relation_id,
                "view_id": view_id,
                "frontage_entity_id": frontage_id,
                "building_entity_id": building_id,
            }
    return parsed


def _parse_bearings(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return parsed
    if len(value) > _MAX_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
            continue
        _shape(item, _BEARING_FIELDS, item_path, diagnostics)
        bearing_id = _fact_id(item.get("id"), item_path + ".id", diagnostics)
        from_view = _token(item.get("from_view_id"), item_path + ".from_view_id", diagnostics)
        to_view = _token(item.get("to_view_id"), item_path + ".to_view_id", diagnostics)
        direction = item.get("direction")
        frame = item.get("compass_frame")
        basis = item.get("verification_basis")
        if type(direction) is not str or direction not in _DIRECTIONS:
            diagnostics.append(Diagnostic("BEARING_DIRECTION", item_path + ".direction"))
        if type(frame) is not str or not _TOKEN_RE.fullmatch(frame):
            diagnostics.append(Diagnostic("BEARING_COMPASS_FRAME", item_path + ".compass_frame"))
        if basis != "synthetic_approved_compass_frame":
            diagnostics.append(Diagnostic("BEARING_VERIFICATION_BASIS", item_path + ".verification_basis"))
        if from_view is not None and from_view == to_view:
            diagnostics.append(Diagnostic("BEARING_SAME_VIEW", item_path))
        if bearing_id is None or from_view is None or to_view is None or type(frame) is not str:
            continue
        if bearing_id in parsed:
            diagnostics.append(Diagnostic("DUPLICATE_BEARING_ID", item_path + ".id"))
            continue
        parsed[bearing_id] = {
            "id": bearing_id,
            "from_view_id": from_view,
            "to_view_id": to_view,
            "direction": direction if type(direction) is str else "",
            "compass_frame": frame,
            "verification_basis": basis if type(basis) is str else "",
        }
    return parsed


def _validate_forbidden_scene_facts(
    views: dict[str, dict[str, Any]], diagnostics: list[Diagnostic]
) -> None:
    for view_id, view in views.items():
        fixture = view.get("fixture")
        if type(fixture) is not dict or type(fixture.get("facts")) is not list:
            continue
        if len(fixture["facts"]) > _MAX_ITEMS:
            diagnostics.append(
                Diagnostic(
                    "COLLECTION_LIMIT",
                    "$.views[%s].fixture.facts" % view_id,
                )
            )
        for index, fact in enumerate(fixture["facts"][:_MAX_ITEMS]):
            if (
                type(fact) is dict
                and type(fact.get("predicate")) is str
                and fact.get("predicate") in _FORBIDDEN_SCENE_PREDICATES
            ):
                diagnostics.append(
                    Diagnostic(
                        "UNSUPPORTED_SCENE_FACT",
                        "$.views[%s].fixture.facts[%d].predicate" % (view_id, index),
                    )
                )


def _parse_movement_state(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> tuple[dict[str, tuple[str, tuple[int, int] | None]], dict[str, tuple[str, tuple[int, int] | None]]] | None:
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return None
    _shape(value, {"fixed_anchors", "mobile_occupants"}, path, diagnostics)
    anchors = _parse_positioned_entities(
        value.get("fixed_anchors"), path + ".fixed_anchors", diagnostics
    )
    occupants = _parse_positioned_entities(
        value.get("mobile_occupants"), path + ".mobile_occupants", diagnostics
    )
    for entity_id in anchors.keys() & occupants.keys():
        diagnostics.append(Diagnostic("FIXED_MOBILE_ID_COLLISION", path))
    if not anchors:
        diagnostics.append(Diagnostic("FIXED_ANCHORS_REQUIRED", path + ".fixed_anchors"))
    if not occupants:
        diagnostics.append(Diagnostic("MOBILE_OCCUPANTS_REQUIRED", path + ".mobile_occupants"))
    return anchors, occupants


def _parse_positioned_entities(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> dict[str, tuple[str, tuple[int, int] | None]]:
    parsed: dict[str, tuple[str, tuple[int, int] | None]] = {}
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return parsed
    if len(value) > _MAX_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    for index, item in enumerate(value[:_MAX_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
            continue
        _shape(item, {"id", "kind", "position"}, item_path, diagnostics)
        entity_id = _entity_id(item.get("id"), item_path + ".id", diagnostics)
        kind = _token(item.get("kind"), item_path + ".kind", diagnostics)
        position = _position(item.get("position"), item_path + ".position", diagnostics)
        if entity_id is None or kind is None:
            continue
        if entity_id in parsed:
            diagnostics.append(Diagnostic("DUPLICATE_ENTITY_ID", item_path + ".id"))
        else:
            parsed[entity_id] = (kind, position)
    return parsed


def _position(
    value: object, path: str, diagnostics: list[Diagnostic]
) -> tuple[int, int] | None:
    if type(value) is not list or len(value) != 2:
        diagnostics.append(Diagnostic("POSITION_SHAPE", path))
        return None
    if any(type(part) is not int or abs(part) > _MAX_COORDINATE for part in value):
        diagnostics.append(Diagnostic("POSITION_COORDINATE", path))
        return None
    return (value[0], value[1])


def _shape(
    value: dict[str, Any], expected: set[str], path: str, diagnostics: list[Diagnostic]
) -> None:
    if len(value) > _MAX_FIELDS:
        diagnostics.append(Diagnostic("RECORD_LIMIT", path))
        return
    for key in sorted(expected - set(value)):
        diagnostics.append(Diagnostic("MISSING_FIELD", path + "." + key))
    for key in value:
        if type(key) is not str:
            diagnostics.append(Diagnostic("OBJECT_KEY_TYPE", path))
        elif key not in expected:
            diagnostics.append(Diagnostic("UNKNOWN_FIELD", path + "." + key))


def _entity_id(value: object, path: str, diagnostics: list[Diagnostic]) -> str | None:
    if type(value) is not str or len(value) > 160 or _ENTITY_ID_RE.fullmatch(value) is None:
        diagnostics.append(Diagnostic("ENTITY_ID", path))
        return None
    return value


def _fact_id(value: object, path: str, diagnostics: list[Diagnostic]) -> str | None:
    if type(value) is not str or len(value) > 160 or _FACT_ID_RE.fullmatch(value) is None:
        diagnostics.append(Diagnostic("FACT_ID", path))
        return None
    return value


def _token(value: object, path: str, diagnostics: list[Diagnostic]) -> str | None:
    if type(value) is not str or len(value) > 64 or _TOKEN_RE.fullmatch(value) is None:
        diagnostics.append(Diagnostic("TOKEN", path))
        return None
    return value
