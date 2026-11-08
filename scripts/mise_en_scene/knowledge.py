# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free scoped fact views and guarded-camp fixture filtering."""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any


_AUDIENCES = {"gm", "public_arrival", "public_map"}
_SCOPED_AUDIENCES = {"public", "gm_narrator"}
_SCOPED_TOPOLOGY_GROUPS = {"scene_nodes", "links", "schematic_layout"}
_GENERIC_FACT_ID_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}:fact:[a-z0-9][a-z0-9_-]{0,63}$"
)
_ACTIONS = {
    "arrival",
    "look",
    "investigate_tent",
    "investigate_research_tent",
    "investigate_sleeping_tent",
    "investigate_supply_tent",
    "attempt_fire_lighting",
}
_TRIGGER_ACTION = "attempt_fire_lighting"
_UNKNOWN_MECHANIC_NAMES = (
    "access",
    "audibility",
    "distance",
    "legality",
    "line_of_sight",
    "movement_cost",
    "scale",
    "travel_time",
)
_CAMP_FIXTURE_ID = "mapping_fixture:scene:abandoned_camp"
_CAMP_GUARDED_AUDIENCE = "gm_only"
_CAMP_GUARD_ID_RE = re.compile(
    r"^mapping_fixture:fact:[a-z0-9][a-z0-9_-]{0,63}$"
)
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ITEMS = 32
_MAX_TEXT_LENGTH = 2048
_SOURCE_PROVENANCE = {
    "source_ref": "source:owner-feedback-appendix-h",
    "path": "plans/v2-mapping-pilot-owner-feedback.md",
    "section": "Appendix H. Abandoned research camp: investigation mise-en-scene",
    "sha256": "1ac15c0a677848705d5e54e0f9d13c1f39662685154f27ca31fb82e7b3ea6568",
    "source_kind": "owner_feedback",
    "legacy_truth_verified": False,
}
_SCHEMATIC_POSITIONS = {
    "approach": "S",
    "fire_pit": "C",
    "research_tent": "NW",
    "sleeping_tent": "NE",
    "supply_tent": "W",
}
_REFERENCE_KEYS = {
    "fixture_id",
    "public_fact_ids",
    "public_fact_digests",
    "position_frame",
    "schematic_positions",
    "guarded_fact_id",
    "guarded_audience",
    "trigger_action",
    "effect_status",
    "guarded_payload_sha256",
    "unknown_mechanic_names",
    "source_provenance",
}
_CANDIDATE_KEYS = {
    "fixture_id",
    "public_facts",
    "position_frame",
    "schematic_positions",
    "initial_mobile_occupants",
    "guarded_fact",
    "unknown_mechanics",
    "source_provenance",
    "metadata",
}
_PUBLIC_FACT_KEYS = {
    "id",
    "text",
    "audience",
    "authorship",
    "legacy_truth_verified",
    "source_refs",
}
_GUARDED_FACT_KEYS = {
    "id",
    "audience",
    "trigger_action",
    "payload",
    "effect",
    "provenance_class",
    "legacy_truth_verified",
    "source_refs",
}


class KnowledgeFixtureError(ValueError):
    """Stable fail-closed error for malformed or unsafe knowledge fixtures."""

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(code + " at " + path)


def filter_scoped_fact_view(
    facts: object,
    topology: object,
    scope_reference: object,
    *,
    audience: object,
) -> dict[str, Any]:
    """Filter a bounded generic fact/topology view through a separate allowlist.

    This small offline seam is distinct from the guarded-camp fixture below.
    It copies only authorized fact IDs and topology record IDs into the result;
    callers must validate candidate content against their own fixture reference
    before rendering or hashing it.
    """

    if type(audience) is not str or audience not in _SCOPED_AUDIENCES:
        raise KnowledgeFixtureError("AUDIENCE_NOT_ALLOWLISTED", "$.audience")
    _record(
        scope_reference,
        {"audience_fact_ids", "topology_record_ids"},
        "$.scope_reference",
    )
    assert type(scope_reference) is dict
    fact_allowlists = scope_reference["audience_fact_ids"]
    topology_allowlists = scope_reference["topology_record_ids"]
    _record(fact_allowlists, _SCOPED_AUDIENCES, "$.scope_reference.audience_fact_ids")
    _record(
        topology_allowlists,
        _SCOPED_AUDIENCES,
        "$.scope_reference.topology_record_ids",
    )
    for scoped_audience in sorted(_SCOPED_AUDIENCES):
        scoped_ids = fact_allowlists[scoped_audience]
        if type(scoped_ids) not in (list, tuple) or len(scoped_ids) > 64:
            raise KnowledgeFixtureError(
                "SCOPED_FACT_IDS",
                "$.scope_reference.audience_fact_ids." + scoped_audience,
            )
        if any(
            type(item) is not str or not _GENERIC_FACT_ID_RE.fullmatch(item)
            for item in scoped_ids
        ):
            raise KnowledgeFixtureError(
                "SCOPED_FACT_ID",
                "$.scope_reference.audience_fact_ids." + scoped_audience,
            )
        if len(set(scoped_ids)) != len(scoped_ids):
            raise KnowledgeFixtureError(
                "DUPLICATE_SCOPED_FACT_ID",
                "$.scope_reference.audience_fact_ids." + scoped_audience,
            )
        _record(
            topology_allowlists[scoped_audience],
            _SCOPED_TOPOLOGY_GROUPS,
            "$.scope_reference.topology_record_ids." + scoped_audience,
        )
        for group in sorted(_SCOPED_TOPOLOGY_GROUPS):
            group_ids = topology_allowlists[scoped_audience][group]
            if type(group_ids) not in (list, tuple) or len(group_ids) > 64:
                raise KnowledgeFixtureError(
                    "SCOPED_TOPOLOGY_IDS",
                    "$.scope_reference.topology_record_ids."
                    + scoped_audience
                    + "."
                    + group,
                )
            if any(type(item) is not str or not item for item in group_ids):
                raise KnowledgeFixtureError(
                    "SCOPED_TOPOLOGY_ID",
                    "$.scope_reference.topology_record_ids."
                    + scoped_audience
                    + "."
                    + group,
                )
            if len(set(group_ids)) != len(group_ids):
                raise KnowledgeFixtureError(
                    "DUPLICATE_SCOPED_TOPOLOGY_ID",
                    "$.scope_reference.topology_record_ids."
                    + scoped_audience
                    + "."
                    + group,
                )
    if not set(fact_allowlists["public"]) <= set(fact_allowlists["gm_narrator"]):
        raise KnowledgeFixtureError(
            "SCOPED_FACT_REFERENCE", "$.scope_reference.audience_fact_ids"
        )
    allowed_fact_ids = fact_allowlists[audience]
    if type(facts) is not list or len(facts) > 64:
        raise KnowledgeFixtureError("FACTS_TYPE", "$.facts")
    facts_by_id: dict[str, dict[str, Any]] = {}
    for index, fact in enumerate(facts):
        path = "$.facts[%d]" % index
        if type(fact) is not dict or type(fact.get("id")) is not str:
            raise KnowledgeFixtureError("FACT_ID", path + ".id")
        fact_id = fact["id"]
        if not _GENERIC_FACT_ID_RE.fullmatch(fact_id):
            raise KnowledgeFixtureError("FACT_ID", path + ".id")
        if fact_id in facts_by_id:
            raise KnowledgeFixtureError("DUPLICATE_FACT_ID", path + ".id")
        facts_by_id[fact_id] = fact
    if set(facts_by_id) != set(fact_allowlists["gm_narrator"]):
        raise KnowledgeFixtureError("FACT_SET_MISMATCH", "$.facts")
    missing_facts = set(allowed_fact_ids) - set(facts_by_id)
    if missing_facts:
        raise KnowledgeFixtureError(
            "SCOPED_FACT_MISSING", "$.facts[" + sorted(missing_facts)[0] + "]"
        )

    if type(topology) is not dict:
        raise KnowledgeFixtureError("TOPOLOGY_TYPE", "$.topology")
    _record(topology, _SCOPED_TOPOLOGY_GROUPS, "$.topology")
    topology_allowlist = topology_allowlists[audience]
    _record(
        topology_allowlist,
        _SCOPED_TOPOLOGY_GROUPS,
        "$.scope_reference.topology_record_ids." + audience,
    )
    filtered_topology: dict[str, list[dict[str, Any]]] = {}
    for group in sorted(_SCOPED_TOPOLOGY_GROUPS):
        records = topology[group]
        allowed_ids = topology_allowlist[group]
        if type(records) is not list or len(records) > 64:
            raise KnowledgeFixtureError("TOPOLOGY_GROUP_TYPE", "$.topology." + group)
        record_id_key = "anchor_id" if group == "schematic_layout" else "id"
        records_by_id: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            path = "$.topology.%s[%d]" % (group, index)
            if type(record) is not dict or type(record.get(record_id_key)) is not str:
                raise KnowledgeFixtureError("TOPOLOGY_RECORD_ID", path)
            record_id = record[record_id_key]
            if record_id in records_by_id:
                raise KnowledgeFixtureError("DUPLICATE_TOPOLOGY_ID", path)
            records_by_id[record_id] = record
        if set(records_by_id) != set(topology_allowlists["gm_narrator"][group]):
            raise KnowledgeFixtureError("TOPOLOGY_SET_MISMATCH", "$.topology." + group)
        missing_records = set(allowed_ids) - set(records_by_id)
        if missing_records:
            raise KnowledgeFixtureError(
                "SCOPED_TOPOLOGY_RECORD_MISSING",
                "$.topology." + group + "[" + sorted(missing_records)[0] + "]",
            )
        filtered_topology[group] = [
            copy.deepcopy(records_by_id[record_id]) for record_id in allowed_ids
        ]

    return {
        "facts": [copy.deepcopy(facts_by_id[fact_id]) for fact_id in allowed_fact_ids],
        "topology": filtered_topology,
    }


def build_knowledge_view(
    candidate: object,
    guard_reference: object,
    *,
    audience: object,
    action: object,
) -> dict[str, Any]:
    """Build a small allowlisted view without resolving or activating effects.

    The public arrival/map surfaces return only reference-approved public fact
    IDs and text. The separately supplied guard reference, rather than a
    candidate visibility field, controls the GM-only boundary and trigger.
    """

    if type(audience) is not str or audience not in _AUDIENCES:
        raise KnowledgeFixtureError("AUDIENCE_NOT_ALLOWLISTED", "$.audience")
    if type(action) is not str or action not in _ACTIONS:
        raise KnowledgeFixtureError("ACTION_NOT_ALLOWLISTED", "$.action")

    reference = _validate_reference(guard_reference)
    _validate_candidate(candidate, reference)
    assert type(candidate) is dict
    public_facts = [
        {"id": item["id"], "text": item["text"]}
        for item in candidate["public_facts"]
    ]

    if audience in ("public_arrival", "public_map"):
        view: dict[str, Any] = {
            "audience": "public",
            "surface": "arrival" if audience == "public_arrival" else "map",
            "facts": public_facts,
        }
        if audience == "public_map":
            view["position_frame"] = candidate["position_frame"]
            view["schematic_positions"] = copy.deepcopy(
                candidate["schematic_positions"]
            )
        return view

    guard = candidate["guarded_fact"]
    return {
        "audience": "gm",
        "facts": copy.deepcopy(candidate["public_facts"]),
        "position_frame": candidate["position_frame"],
        "schematic_positions": copy.deepcopy(candidate["schematic_positions"]),
        "guarded_fact": {
            "id": guard["id"],
            "visibility": reference["guarded_audience"],
            "payload": guard["payload"],
            "trigger_action": reference["trigger_action"],
            "trigger_condition_met": action == reference["trigger_action"],
            "effect": copy.deepcopy(guard["effect"]),
            "provenance": {
                "class": guard["provenance_class"],
                "source_refs": copy.deepcopy(guard["source_refs"]),
            },
            "source_provenance": copy.deepcopy(candidate["source_provenance"]),
        },
        "unknown_mechanics": copy.deepcopy(candidate["unknown_mechanics"]),
        "metadata": copy.deepcopy(candidate["metadata"]),
    }


def classify_mechanics_authority(
    family_id: object,
    migrated_family_registry: object,
    *,
    runtime_contract_approved: object,
) -> str:
    """Label the owner boundary only; never decide or execute a mechanic.

    Firelight/Python-bridge ownership is reported only when both the supplied
    runtime contract is approved and the family is in the separately supplied
    migrated-family registry. All other valid family labels retain the Python
    guard. This function does not inspect a candidate or call an engine.
    """

    if type(family_id) is not str or not _TOKEN_RE.fullmatch(family_id):
        raise KnowledgeFixtureError("MECHANIC_FAMILY_ID", "$.family_id")
    if type(runtime_contract_approved) is not bool:
        raise KnowledgeFixtureError(
            "RUNTIME_APPROVAL_TYPE", "$.runtime_contract_approved"
        )
    if type(migrated_family_registry) is not tuple:
        raise KnowledgeFixtureError(
            "MIGRATED_FAMILY_REGISTRY_TYPE", "$.migrated_family_registry"
        )
    if len(migrated_family_registry) > _MAX_ITEMS:
        raise KnowledgeFixtureError(
            "COLLECTION_LIMIT", "$.migrated_family_registry"
        )

    seen: set[str] = set()
    for index, family in enumerate(migrated_family_registry):
        path = "$.migrated_family_registry[%d]" % index
        if type(family) is not str or not _TOKEN_RE.fullmatch(family):
            raise KnowledgeFixtureError("MECHANIC_FAMILY_ID", path)
        if family in seen:
            raise KnowledgeFixtureError("DUPLICATE_MECHANIC_FAMILY", path)
        seen.add(family)

    if runtime_contract_approved and family_id in seen:
        return "firelight_python_bridge"
    return "python_guard"


def _validate_reference(value: object) -> dict[str, Any]:
    path = "$.guard_reference"
    _record(value, _REFERENCE_KEYS, path)
    assert type(value) is dict
    if value["fixture_id"] != _CAMP_FIXTURE_ID:
        raise KnowledgeFixtureError("GUARD_REFERENCE_FIXTURE", path + ".fixture_id")

    public_ids = value["public_fact_ids"]
    if type(public_ids) is not tuple or not public_ids or len(public_ids) > _MAX_ITEMS:
        raise KnowledgeFixtureError("PUBLIC_FACT_REFERENCE", path + ".public_fact_ids")
    seen_public_ids: set[str] = set()
    for index, fact_id in enumerate(public_ids):
        item_path = path + ".public_fact_ids[%d]" % index
        if type(fact_id) is not str or not _CAMP_GUARD_ID_RE.fullmatch(fact_id):
            raise KnowledgeFixtureError("FACT_ID", item_path)
        if fact_id in seen_public_ids:
            raise KnowledgeFixtureError("DUPLICATE_FACT_ID", item_path)
        seen_public_ids.add(fact_id)

    guarded_fact_id = value["guarded_fact_id"]
    if (
        type(guarded_fact_id) is not str
        or not _CAMP_GUARD_ID_RE.fullmatch(guarded_fact_id)
    ):
        raise KnowledgeFixtureError("FACT_ID", path + ".guarded_fact_id")
    if guarded_fact_id in seen_public_ids:
        raise KnowledgeFixtureError("GUARDED_FACT_PUBLIC", path + ".guarded_fact_id")

    digests = value["public_fact_digests"]
    _record(digests, seen_public_ids, path + ".public_fact_digests")
    assert type(digests) is dict
    for fact_id in public_ids:
        if type(digests[fact_id]) is not str or not _SHA256_RE.fullmatch(digests[fact_id]):
            raise KnowledgeFixtureError(
                "PUBLIC_FACT_DIGEST", path + ".public_fact_digests." + fact_id
            )

    if value["guarded_audience"] != _CAMP_GUARDED_AUDIENCE:
        raise KnowledgeFixtureError("GUARD_REFERENCE_VISIBILITY", path + ".guarded_audience")
    if value["trigger_action"] != _TRIGGER_ACTION:
        raise KnowledgeFixtureError("GUARD_REFERENCE_TRIGGER", path + ".trigger_action")
    if value["effect_status"] != "unknown":
        raise KnowledgeFixtureError("GUARD_REFERENCE_EFFECT", path + ".effect_status")
    if value["position_frame"] != "north_up_schematic":
        raise KnowledgeFixtureError("POSITION_FRAME_REFERENCE", path + ".position_frame")
    if (
        type(value["guarded_payload_sha256"]) is not str
        or not _SHA256_RE.fullmatch(value["guarded_payload_sha256"])
    ):
        raise KnowledgeFixtureError(
            "GUARD_REFERENCE_PAYLOAD_DIGEST", path + ".guarded_payload_sha256"
        )
    if value["unknown_mechanic_names"] != _UNKNOWN_MECHANIC_NAMES:
        raise KnowledgeFixtureError(
            "UNKNOWN_MECHANIC_REFERENCE", path + ".unknown_mechanic_names"
        )
    _record(
        value["schematic_positions"],
        set(_SCHEMATIC_POSITIONS),
        path + ".schematic_positions",
    )
    if value["schematic_positions"] != _SCHEMATIC_POSITIONS:
        raise KnowledgeFixtureError(
            "SCHEMATIC_POSITION_REFERENCE", path + ".schematic_positions"
        )
    _source_provenance(value["source_provenance"], path + ".source_provenance")
    if value["source_provenance"] != _SOURCE_PROVENANCE:
        raise KnowledgeFixtureError(
            "SOURCE_PROVENANCE_REFERENCE", path + ".source_provenance"
        )
    return value


def _validate_candidate(candidate: object, reference: dict[str, Any]) -> None:
    path = "$.candidate"
    _record(candidate, _CANDIDATE_KEYS, path)
    assert type(candidate) is dict
    if candidate["fixture_id"] != reference["fixture_id"]:
        raise KnowledgeFixtureError("CAMP_FIXTURE_ID", path + ".fixture_id")
    _source_provenance(candidate["source_provenance"], path + ".source_provenance")
    if candidate["source_provenance"] != reference["source_provenance"]:
        raise KnowledgeFixtureError("SOURCE_PROVENANCE_MISMATCH", path + ".source_provenance")
    if candidate["position_frame"] != reference["position_frame"]:
        raise KnowledgeFixtureError("POSITION_FRAME_MISMATCH", path + ".position_frame")

    metadata = candidate["metadata"]
    _record(
        metadata,
        {"development_only", "held_out", "legacy_truth_verified"},
        path + ".metadata",
    )
    assert type(metadata) is dict
    if (
        metadata["development_only"] is not True
        or metadata["held_out"] is not False
        or metadata["legacy_truth_verified"] is not False
    ):
        raise KnowledgeFixtureError("CAMP_FIXTURE_METADATA", path + ".metadata")

    public_facts = candidate["public_facts"]
    if (
        type(public_facts) is not list
        or len(public_facts) > _MAX_ITEMS
        or len(public_facts) != len(reference["public_fact_ids"])
    ):
        raise KnowledgeFixtureError("PUBLIC_FACTS_TYPE", path + ".public_facts")
    for index, fact in enumerate(public_facts):
        fact_path = path + ".public_facts[%d]" % index
        _record(fact, _PUBLIC_FACT_KEYS, fact_path)
        assert type(fact) is dict
        fact_id = fact["id"]
        if fact_id != reference["public_fact_ids"][index]:
            raise KnowledgeFixtureError("PUBLIC_FACT_ID_MISMATCH", fact_path + ".id")
        if fact["audience"] != "public":
            raise KnowledgeFixtureError("PUBLIC_FACT_VISIBILITY", fact_path + ".audience")
        if fact["authorship"] != "builder_authored_example":
            raise KnowledgeFixtureError("CAMP_AUTHORSHIP", fact_path + ".authorship")
        if fact["legacy_truth_verified"] is not False:
            raise KnowledgeFixtureError(
                "CAMP_LEGACY_TRUTH_CLAIM", fact_path + ".legacy_truth_verified"
            )
        _source_refs(fact["source_refs"], fact_path + ".source_refs")
        text = fact["text"]
        if (
            type(text) is not str
            or not text.strip()
            or len(text) > _MAX_TEXT_LENGTH
            or not text.isascii()
        ):
            raise KnowledgeFixtureError("PUBLIC_FACT_TEXT", fact_path + ".text")
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        if digest != reference["public_fact_digests"][fact_id]:
            raise KnowledgeFixtureError("PUBLIC_FACT_CONTENT_MISMATCH", fact_path + ".text")

    _record(
        candidate["schematic_positions"],
        set(_SCHEMATIC_POSITIONS),
        path + ".schematic_positions",
    )
    if candidate["schematic_positions"] != reference["schematic_positions"]:
        raise KnowledgeFixtureError(
            "SCHEMATIC_POSITION_MISMATCH", path + ".schematic_positions"
        )
    occupants = candidate["initial_mobile_occupants"]
    if type(occupants) is not list:
        raise KnowledgeFixtureError("CAMP_OCCUPANTS_TYPE", path + ".initial_mobile_occupants")
    if occupants:
        raise KnowledgeFixtureError(
            "CAMP_INITIAL_OCCUPANTS_UNSUPPORTED", path + ".initial_mobile_occupants"
        )

    guard = candidate["guarded_fact"]
    guard_path = path + ".guarded_fact"
    _record(guard, _GUARDED_FACT_KEYS, guard_path)
    assert type(guard) is dict
    if guard["id"] != reference["guarded_fact_id"]:
        raise KnowledgeFixtureError("GUARDED_FACT_ID_MISMATCH", guard_path + ".id")
    if guard["audience"] != reference["guarded_audience"]:
        raise KnowledgeFixtureError("GUARDED_VISIBILITY_MISMATCH", guard_path + ".audience")
    if guard["trigger_action"] != reference["trigger_action"]:
        raise KnowledgeFixtureError("GUARDED_TRIGGER_MISMATCH", guard_path + ".trigger_action")
    payload = guard["payload"]
    if (
        type(payload) is not str
        or not payload.strip()
        or len(payload) > _MAX_TEXT_LENGTH
        or not payload.isascii()
        or hashlib.sha256(payload.encode("ascii")).hexdigest()
        != reference["guarded_payload_sha256"]
    ):
        raise KnowledgeFixtureError("GUARDED_PAYLOAD_MISMATCH", guard_path + ".payload")
    effect = guard["effect"]
    _record(effect, {"status", "value"}, guard_path + ".effect")
    assert type(effect) is dict
    if effect["status"] != "unknown" or effect["value"] is not None:
        raise KnowledgeFixtureError("PROTECTED_EFFECT_NOT_UNKNOWN", guard_path + ".effect")
    if guard["provenance_class"] != "source_extracted":
        raise KnowledgeFixtureError("GUARDED_PROVENANCE_CLASS", guard_path + ".provenance_class")
    if guard["legacy_truth_verified"] is not False:
        raise KnowledgeFixtureError(
            "CAMP_LEGACY_TRUTH_CLAIM", guard_path + ".legacy_truth_verified"
        )
    _source_refs(guard["source_refs"], guard_path + ".source_refs")

    unknown_mechanics = candidate["unknown_mechanics"]
    if (
        type(unknown_mechanics) is not list
        or len(unknown_mechanics) != len(reference["unknown_mechanic_names"])
    ):
        raise KnowledgeFixtureError("UNKNOWN_MECHANICS_TYPE", path + ".unknown_mechanics")
    for index, item in enumerate(unknown_mechanics):
        item_path = path + ".unknown_mechanics[%d]" % index
        _record(item, {"name", "status", "value"}, item_path)
        assert type(item) is dict
        if item["name"] != reference["unknown_mechanic_names"][index]:
            raise KnowledgeFixtureError("UNKNOWN_MECHANIC_NAME", item_path + ".name")
        if item["status"] != "unknown" or item["value"] is not None:
            raise KnowledgeFixtureError(
                "PROTECTED_MECHANIC_NOT_UNKNOWN", item_path
            )


def _source_provenance(value: object, path: str) -> None:
    _record(
        value,
        {
            "source_ref",
            "path",
            "section",
            "sha256",
            "source_kind",
            "legacy_truth_verified",
        },
        path,
    )
    assert type(value) is dict
    if type(value["sha256"]) is not str or not _SHA256_RE.fullmatch(value["sha256"]):
        raise KnowledgeFixtureError("SOURCE_SECTION_HASH", path + ".sha256")


def _source_refs(value: object, path: str) -> None:
    if type(value) is not list or value != [_SOURCE_PROVENANCE["source_ref"]]:
        raise KnowledgeFixtureError("CAMP_SOURCE_REFS", path)


def _record(value: object, expected: set[str], path: str) -> None:
    if type(value) is not dict:
        raise KnowledgeFixtureError("OBJECT_TYPE", path)
    if len(value) > 32:
        raise KnowledgeFixtureError("RECORD_LIMIT", path)
    if any(type(key) is not str for key in value):
        raise KnowledgeFixtureError("OBJECT_KEY_TYPE", path)
    missing = sorted(expected - set(value))
    if missing:
        raise KnowledgeFixtureError("MISSING_FIELD", path + "." + missing[0])
    unknown = sorted(set(value) - expected)
    if unknown:
        raise KnowledgeFixtureError("UNKNOWN_FIELD", path + "." + unknown[0])
