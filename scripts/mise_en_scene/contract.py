# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Pure-offline v1 fixture contract for scene authoring.

API: ``validate_fixture(fixture, approved_topology, consulted_source_refs)``
returns a stable tuple of ``Diagnostic(code, path)`` values. The fixture is a
JSON-shaped object with a module-qualified scene/scope, explicit orientation
state and provenance, relationship facts, separate fixed-anchor and initial-
mobile-occupant lists, and named extension seams. ``ApprovedTopology`` is a
separate frozen input; its ID binds the fixture to it but does not grant
approval by itself. Source-reference strings are accepted only when present in
the separately supplied consulted-reference collection; references do not
prove a fact's truth.

The validator checks structure, references, identity uniqueness, source-ref
membership, and orientation-frame compatibility only. It does not derive
metrics, access, doors, visibility, or other rules from schematic cells. The
extension seams reserve data shapes for multi-cell extents, stage relations,
audience knowledge, unknown metrics, and arrival claims without implementing
their later coverage or semantic checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


_MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_QUALIFIED_ID_RE = re.compile(
    r"^(?P<module>[a-z][a-z0-9_-]{0,63}):"
    r"(?P<kind>scene|scope|entity|fact|topology):"
    r"(?P<local>[a-z0-9][a-z0-9_-]{0,63})$"
)
_SOURCE_REF_RE = re.compile(r"^source:[a-z0-9][a-z0-9._/-]{0,127}$")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_FIXTURE_KEYS = {
    "schema_version",
    "module_id",
    "topology_id",
    "scene",
    "fixed_anchors",
    "initial_mobile_occupants",
    "facts",
    "extension_seams",
}
_SCENE_KEYS = {"id", "scope", "orientation"}
_SCOPE_KEYS = {"id", "kind"}
_ORIENTATION_KEYS = {"status", "frame", "provenance"}
_ENTITY_KEYS = {"id", "kind"}
_FACT_KEYS = {
    "id",
    "subject_id",
    "predicate",
    "object_id",
    "status",
    "value",
    "provenance",
}
_PROVENANCE_KEYS = {"class", "source_refs"}
_SEAM_KEYS = {
    "multi_cell_extents",
    "stage_relations",
    "unknown_metrics",
    "audience_knowledge",
    "arrival_claims",
}
_PROVENANCE_CLASSES = {"source_extracted", "builder_authored", "unknown"}
_MAX_COLLECTION_ITEMS = 256
_MAX_TEXT_LENGTH = 4096
_MAX_RECORD_FIELDS = 32
_MAX_EXTENSION_JSON_NODES = 2048
_MAX_EXTENSION_JSON_DEPTH = 12


@dataclass(frozen=True)
class ApprovedTopology:
    """Immutable approval input for one module-qualified scene and scope."""

    topology_id: str
    module_id: str
    scene_id: str
    scope_id: str
    compass_frames: tuple[str, ...]
    fixed_anchor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.module_id) is not str or not _MODULE_ID_RE.fullmatch(self.module_id):
            raise ValueError("module_id must be a lowercase module slug")
        _check_topology_id(self.topology_id, "topology", self.module_id)
        _check_topology_id(self.scene_id, "scene", self.module_id)
        _check_topology_id(self.scope_id, "scope", self.module_id)
        if type(self.compass_frames) is not tuple:
            raise TypeError("compass_frames must be a tuple")
        if len(self.compass_frames) > _MAX_COLLECTION_ITEMS:
            raise ValueError("compass_frames exceeds the fixture limit")
        if any(
            type(frame) is not str
            or len(frame) > 64
            or not _TOKEN_RE.fullmatch(frame)
            for frame in self.compass_frames
        ):
            raise ValueError("compass_frames must contain orientation tokens")
        if len(set(self.compass_frames)) != len(self.compass_frames):
            raise ValueError("compass_frames must be unique")
        if type(self.fixed_anchor_ids) is not tuple:
            raise TypeError("fixed_anchor_ids must be a tuple")
        if len(self.fixed_anchor_ids) > _MAX_COLLECTION_ITEMS:
            raise ValueError("fixed_anchor_ids exceeds the fixture limit")
        for anchor_id in self.fixed_anchor_ids:
            _check_topology_id(anchor_id, "entity", self.module_id)
        if len(set(self.fixed_anchor_ids)) != len(self.fixed_anchor_ids):
            raise ValueError("fixed_anchor_ids must be unique")


@dataclass(frozen=True)
class Diagnostic:
    """Stable fail-closed diagnostic with a machine-readable code and path."""

    code: str
    path: str


@dataclass(frozen=True)
class ValidationResult:
    """Immutable result of validating one supplied fixture."""

    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


def validate_fixture(
    fixture: object,
    approved_topology: object,
    consulted_source_refs: object = (),
    *,
    prior_pc_ids: object = (),
) -> ValidationResult:
    """Validate shape, references, provenance classes, and topology binding.

    The function is read-only. ``fixture`` must be composed of ordinary JSON
    objects/lists/scalars. ``consulted_source_refs`` is the caller's explicit
    list or tuple of source references actually consulted for this fixture.
    """

    diagnostics: list[Diagnostic] = []
    if type(approved_topology) is not ApprovedTopology:
        diagnostics.append(Diagnostic("APPROVED_TOPOLOGY_TYPE", "$approved_topology"))
        return ValidationResult(tuple(diagnostics))
    if type(consulted_source_refs) not in (list, tuple):
        diagnostics.append(
            Diagnostic("CONSULTED_SOURCE_REFS_TYPE", "$consulted_source_refs")
        )
        return ValidationResult(tuple(diagnostics))

    if type(prior_pc_ids) not in (list, tuple):
        diagnostics.append(Diagnostic("PRIOR_PC_IDS_TYPE", "$prior_pc_ids"))
        return ValidationResult(tuple(diagnostics))
    if len(prior_pc_ids) > _MAX_COLLECTION_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", "$prior_pc_ids"))
    prior_pcs: set[str] = set()
    for index, pc_id in enumerate(prior_pc_ids[:_MAX_COLLECTION_ITEMS]):
        path = "$prior_pc_ids[%d]" % index
        if type(pc_id) is not str or not _QUALIFIED_ID_RE.fullmatch(pc_id) or ":entity:" not in pc_id:
            diagnostics.append(Diagnostic("PRIOR_PC_ID", path))
        elif pc_id in prior_pcs:
            diagnostics.append(Diagnostic("DUPLICATE_PRIOR_PC_ID", path))
        else:
            prior_pcs.add(pc_id)

    consulted: set[str] = set()
    if len(consulted_source_refs) > _MAX_COLLECTION_ITEMS:
        diagnostics.append(
            Diagnostic("COLLECTION_LIMIT", "$consulted_source_refs")
        )
    for index, source_ref in enumerate(
        consulted_source_refs[:_MAX_COLLECTION_ITEMS]
    ):
        path = "$consulted_source_refs[%d]" % index
        if type(source_ref) is not str or not _SOURCE_REF_RE.fullmatch(source_ref):
            diagnostics.append(Diagnostic("INVALID_SOURCE_REF", path))
            continue
        if source_ref in consulted:
            diagnostics.append(Diagnostic("DUPLICATE_SOURCE_REF", path))
        consulted.add(source_ref)

    if type(fixture) is not dict:
        diagnostics.append(Diagnostic("FIXTURE_TYPE", "$"))
        return ValidationResult(tuple(diagnostics))

    _check_record_shape(fixture, _FIXTURE_KEYS, "$", diagnostics)
    if type(fixture.get("schema_version")) is not int or fixture.get("schema_version") != 1:
        diagnostics.append(Diagnostic("SCHEMA_VERSION", "$.schema_version"))

    module_id = fixture.get("module_id")
    if type(module_id) is not str or not _MODULE_ID_RE.fullmatch(module_id):
        diagnostics.append(Diagnostic("MODULE_ID", "$.module_id"))
        module_id = None
    elif module_id != approved_topology.module_id:
        diagnostics.append(Diagnostic("TOPOLOGY_MODULE_MISMATCH", "$.module_id"))

    topology_id = fixture.get("topology_id")
    if not _check_id(topology_id, "topology", module_id, "$.topology_id", diagnostics):
        topology_id = None
    elif topology_id != approved_topology.topology_id:
        diagnostics.append(Diagnostic("TOPOLOGY_ID_MISMATCH", "$.topology_id"))

    known_ids: set[str] = set()
    scene_id, scope_id = _validate_scene(
        fixture.get("scene"), module_id, approved_topology, consulted, diagnostics
    )
    if scene_id is not None:
        known_ids.add(scene_id)
    if scope_id is not None:
        known_ids.add(scope_id)

    fixed_ids = _validate_entities(
        fixture.get("fixed_anchors"),
        "$.fixed_anchors",
        module_id,
        diagnostics,
    )
    mobile_ids = _validate_entities(
        fixture.get("initial_mobile_occupants"),
        "$.initial_mobile_occupants",
        module_id,
        diagnostics,
    )
    for occupant_id, index in mobile_ids:
        kind = fixture["initial_mobile_occupants"][index].get("kind")
        if kind in ("pc", "player_character"):
            diagnostics.append(Diagnostic("PC_INITIAL_OCCUPANT", "$.initial_mobile_occupants[%d].kind" % index))
        if occupant_id in prior_pcs:
            diagnostics.append(Diagnostic("PRIOR_PC_INITIAL_OCCUPANT", "$.initial_mobile_occupants[%d].id" % index))
    known_ids.update(entity_id for entity_id, _index in fixed_ids)
    known_ids.update(entity_id for entity_id, _index in mobile_ids)

    approved_fixed_ids = set(approved_topology.fixed_anchor_ids)
    for anchor_id, index in fixed_ids:
        if anchor_id not in approved_fixed_ids:
            diagnostics.append(
                Diagnostic("UNAPPROVED_FIXED_ANCHOR", "$.fixed_anchors[%d].id" % index)
            )
    fixed_set = {entity_id for entity_id, _index in fixed_ids}
    for occupant_id, index in mobile_ids:
        if occupant_id in fixed_set or occupant_id in approved_fixed_ids:
            diagnostics.append(
                Diagnostic(
                    "FIXED_MOBILE_ID_COLLISION",
                    "$.initial_mobile_occupants[%d].id" % index,
                )
            )

    _validate_facts(
        fixture.get("facts"), module_id, known_ids, consulted, diagnostics
    )
    _validate_extension_seams(fixture.get("extension_seams"), diagnostics)
    return ValidationResult(tuple(diagnostics))


def _validate_scene(
    value: object,
    module_id: str | None,
    topology: ApprovedTopology,
    consulted: set[str],
    diagnostics: list[Diagnostic],
) -> tuple[str | None, str | None]:
    path = "$.scene"
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return None, None
    _check_record_shape(value, _SCENE_KEYS, path, diagnostics)
    scene_id = value.get("id")
    if _check_id(scene_id, "scene", module_id, path + ".id", diagnostics):
        if scene_id != topology.scene_id:
            diagnostics.append(Diagnostic("TOPOLOGY_SCENE_MISMATCH", path + ".id"))
    else:
        scene_id = None

    scope = value.get("scope")
    scope_id: str | None = None
    if type(scope) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path + ".scope"))
    else:
        _check_record_shape(scope, _SCOPE_KEYS, path + ".scope", diagnostics)
        candidate_scope_id = scope.get("id")
        if _check_id(candidate_scope_id, "scope", module_id, path + ".scope.id", diagnostics):
            scope_id = candidate_scope_id
            if scope_id != topology.scope_id:
                diagnostics.append(
                    Diagnostic("TOPOLOGY_SCOPE_MISMATCH", path + ".scope.id")
                )
        if not _valid_token(scope.get("kind")):
            diagnostics.append(Diagnostic("SCOPE_KIND", path + ".scope.kind"))

    _validate_orientation(
        value.get("orientation"), topology, consulted, diagnostics
    )
    return scene_id, scope_id


def _validate_orientation(
    value: object,
    topology: ApprovedTopology,
    consulted: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    path = "$.scene.orientation"
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return
    _check_record_shape(value, _ORIENTATION_KEYS, path, diagnostics)
    status = value.get("status")
    frame = value.get("frame")
    if status not in ("known", "unknown"):
        diagnostics.append(Diagnostic("ORIENTATION_STATUS", path + ".status"))
        status = None
    if status == "unknown":
        if frame is not None:
            diagnostics.append(Diagnostic("UNKNOWN_HAS_VALUE", path + ".frame"))
    elif status == "known":
        if not _valid_token(frame):
            diagnostics.append(Diagnostic("ORIENTATION_FRAME", path + ".frame"))
        elif frame not in topology.compass_frames:
            diagnostics.append(Diagnostic("ORIENTATION_CONFLICT", path + ".frame"))
    _validate_provenance(
        value.get("provenance"),
        path + ".provenance",
        status,
        consulted,
        diagnostics,
    )


def _validate_entities(
    value: object,
    path: str,
    module_id: str | None,
    diagnostics: list[Diagnostic],
) -> list[tuple[str, int]]:
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return []
    if len(value) > _MAX_COLLECTION_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    ids: list[tuple[str, int]] = []
    seen: set[str] = set()
    for index, item in enumerate(value[:_MAX_COLLECTION_ITEMS]):
        item_path = "%s[%d]" % (path, index)
        if type(item) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", item_path))
            continue
        _check_record_shape(item, _ENTITY_KEYS, item_path, diagnostics)
        entity_id = item.get("id")
        if not _check_id(entity_id, "entity", module_id, item_path + ".id", diagnostics):
            continue
        if entity_id in seen:
            diagnostics.append(Diagnostic("DUPLICATE_ID", item_path + ".id"))
        seen.add(entity_id)
        ids.append((entity_id, index))
        if not _valid_token(item.get("kind")):
            diagnostics.append(Diagnostic("ENTITY_KIND", item_path + ".kind"))
    return ids


def _validate_facts(
    value: object,
    module_id: str | None,
    known_ids: set[str],
    consulted: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    path = "$.facts"
    if type(value) is not list:
        diagnostics.append(Diagnostic("ARRAY_TYPE", path))
        return
    if len(value) > _MAX_COLLECTION_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path))
    seen: set[str] = set()
    for index, fact in enumerate(value[:_MAX_COLLECTION_ITEMS]):
        fact_path = "%s[%d]" % (path, index)
        if type(fact) is not dict:
            diagnostics.append(Diagnostic("ITEM_TYPE", fact_path))
            continue
        _check_record_shape(fact, _FACT_KEYS, fact_path, diagnostics)
        fact_id = fact.get("id")
        if _check_id(fact_id, "fact", module_id, fact_path + ".id", diagnostics):
            if fact_id in seen:
                diagnostics.append(Diagnostic("DUPLICATE_ID", fact_path + ".id"))
            seen.add(fact_id)
        for reference_key in ("subject_id", "object_id"):
            reference = fact.get(reference_key)
            reference_path = fact_path + "." + reference_key
            if type(reference) is not str:
                diagnostics.append(Diagnostic("REFERENCE_TYPE", reference_path))
            elif reference not in known_ids:
                diagnostics.append(Diagnostic("UNKNOWN_REFERENCE", reference_path))
        if not _valid_token(fact.get("predicate")):
            diagnostics.append(Diagnostic("FACT_PREDICATE", fact_path + ".predicate"))
        status = fact.get("status")
        if status not in ("known", "unknown"):
            diagnostics.append(Diagnostic("FACT_STATUS", fact_path + ".status"))
            status = None
        fact_value = fact.get("value")
        if status == "unknown" and fact_value is not None:
            diagnostics.append(Diagnostic("UNKNOWN_HAS_VALUE", fact_path + ".value"))
        elif status == "known" and not _valid_fact_value(fact_value):
            diagnostics.append(Diagnostic("FACT_VALUE", fact_path + ".value"))
        _validate_provenance(
            fact.get("provenance"),
            fact_path + ".provenance",
            status,
            consulted,
            diagnostics,
        )


def _validate_provenance(
    value: object,
    path: str,
    status: str | None,
    consulted: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return
    _check_record_shape(value, _PROVENANCE_KEYS, path, diagnostics)
    provenance_class = value.get("class")
    if (
        type(provenance_class) is not str
        or provenance_class not in _PROVENANCE_CLASSES
    ):
        diagnostics.append(Diagnostic("PROVENANCE_CLASS", path + ".class"))
        provenance_class = None
    source_refs = value.get("source_refs")
    if type(source_refs) is not list:
        diagnostics.append(Diagnostic("SOURCE_REFS_TYPE", path + ".source_refs"))
        source_refs = []
    elif len(source_refs) > _MAX_COLLECTION_ITEMS:
        diagnostics.append(Diagnostic("COLLECTION_LIMIT", path + ".source_refs"))

    seen: set[str] = set()
    for index, source_ref in enumerate(source_refs[:_MAX_COLLECTION_ITEMS]):
        ref_path = "%s.source_refs[%d]" % (path, index)
        if type(source_ref) is not str or not _SOURCE_REF_RE.fullmatch(source_ref):
            diagnostics.append(Diagnostic("INVALID_SOURCE_REF", ref_path))
            continue
        if source_ref in seen:
            diagnostics.append(Diagnostic("DUPLICATE_SOURCE_REF", ref_path))
        seen.add(source_ref)
        if source_ref not in consulted:
            diagnostics.append(Diagnostic("UNSUPPORTED_SOURCE_REF", ref_path))

    if provenance_class == "source_extracted" and not source_refs:
        diagnostics.append(Diagnostic("MISSING_SOURCE_REF", path + ".source_refs"))
    if status == "unknown" and provenance_class != "unknown":
        diagnostics.append(Diagnostic("UNKNOWN_PROVENANCE", path + ".class"))
    elif status == "known" and provenance_class not in (
        "source_extracted",
        "builder_authored",
    ):
        diagnostics.append(Diagnostic("KNOWN_PROVENANCE", path + ".class"))


def _validate_extension_seams(
    value: object, diagnostics: list[Diagnostic]
) -> None:
    path = "$.extension_seams"
    if type(value) is not dict:
        diagnostics.append(Diagnostic("OBJECT_TYPE", path))
        return
    _check_record_shape(value, _SEAM_KEYS, path, diagnostics)
    for seam_name in sorted(_SEAM_KEYS):
        seam_path = path + "." + seam_name
        items = value.get(seam_name)
        if type(items) is not list:
            diagnostics.append(Diagnostic("ARRAY_TYPE", seam_path))
            continue
        if len(items) > _MAX_COLLECTION_ITEMS:
            diagnostics.append(Diagnostic("COLLECTION_LIMIT", seam_path))
        for index, item in enumerate(items[:_MAX_COLLECTION_ITEMS]):
            if type(item) is not dict:
                diagnostics.append(
                    Diagnostic("ITEM_TYPE", "%s[%d]" % (seam_path, index))
                )
            elif not _is_bounded_json(item):
                diagnostics.append(
                    Diagnostic("EXTENSION_ITEM_SHAPE", "%s[%d]" % (seam_path, index))
                )


def _check_record_shape(
    value: dict[str, Any],
    expected_keys: set[str],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    if len(value) > _MAX_RECORD_FIELDS:
        diagnostics.append(Diagnostic("RECORD_LIMIT", path))
        return
    for key in sorted(expected_keys):
        if key not in value:
            diagnostics.append(Diagnostic("MISSING_FIELD", path + "." + key))
    for key in value:
        if type(key) is not str:
            diagnostics.append(Diagnostic("OBJECT_KEY_TYPE", path))
        elif key not in expected_keys:
            diagnostics.append(Diagnostic("UNKNOWN_FIELD", path + "." + key))


def _check_id(
    value: object,
    expected_kind: str,
    module_id: str | None,
    path: str,
    diagnostics: list[Diagnostic],
) -> bool:
    if type(value) is not str:
        diagnostics.append(Diagnostic("ID_TYPE", path))
        return False
    if len(value) > 160:
        diagnostics.append(Diagnostic("ID_LENGTH", path))
        return False
    match = _QUALIFIED_ID_RE.fullmatch(value)
    if (
        match is None
        or match.group("kind") != expected_kind
        or (module_id is not None and match.group("module") != module_id)
    ):
        diagnostics.append(Diagnostic("INVALID_ID", path))
        return False
    return True


def _check_topology_id(value: str, expected_kind: str, module_id: str) -> None:
    match = _QUALIFIED_ID_RE.fullmatch(value) if type(value) is str else None
    if (
        match is None
        or match.group("kind") != expected_kind
        or match.group("module") != module_id
    ):
        raise ValueError("topology IDs must be module-qualified with the expected kind")


def _valid_token(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 64
        and _TOKEN_RE.fullmatch(value) is not None
    )


def _valid_fact_value(value: object) -> bool:
    if value is None or type(value) in (str, bool, int):
        return value is None or (type(value) is not str or len(value) <= _MAX_TEXT_LENGTH)
    if type(value) is float:
        return math.isfinite(value)
    return False


def _is_bounded_json(value: object) -> bool:
    """Check opaque extension data without interpreting its scene semantics."""
    pending: list[tuple[object, int]] = [(value, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > _MAX_EXTENSION_JSON_NODES or depth > _MAX_EXTENSION_JSON_DEPTH:
            return False
        if current is None or type(current) in (bool, int):
            continue
        if type(current) is float:
            if not math.isfinite(current):
                return False
            continue
        if type(current) is str:
            if len(current) > _MAX_TEXT_LENGTH:
                return False
            continue
        if type(current) is list:
            if len(current) > _MAX_COLLECTION_ITEMS:
                return False
            pending.extend((item, depth + 1) for item in current)
            continue
        if type(current) is dict:
            if len(current) > _MAX_RECORD_FIELDS:
                return False
            if any(type(key) is not str or len(key) > 128 for key in current):
                return False
            pending.extend((item, depth + 1) for item in current.values())
            continue
        return False
    return True
