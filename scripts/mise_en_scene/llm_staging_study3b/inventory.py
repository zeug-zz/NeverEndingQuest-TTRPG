# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hash-bound immutable Study 3b per-scene source fact inventories."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any

from .study3_compat import contract as study3_contract
from .study3_compat import protocol as study3_protocol


INVENTORY_SCHEMA = "neq.llm_staging_study3b_fact_inventory.v1"
PUBLIC_AUDIENCE = "public_candidate_subject_to_semantic_review"
_SOURCE_FACT_FIELDS = frozenset(
    {"fact_id", "audience", "status", "value", "source_pointer", "source_ref"}
)
_MATERIALIZABLE_SCALAR_TYPES = (str, bool, int, float)


class FactInventoryError(ValueError):
    """A deterministic failure while loading or validating an inventory."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FactRecord:
    """One immutable canonical source fact, including identity and provenance."""

    fact_id: str
    audience: str
    status: str
    value: Any
    identity: Mapping[str, Any]
    provenance: Mapping[str, Any]
    source_binding: Mapping[str, Any]

    @property
    def is_request_public(self) -> bool:
        return self.audience == PUBLIC_AUDIENCE

    @property
    def fixture_materializable(self) -> bool:
        return self.is_request_public and self.status == "source_extracted" and (
            self.value is None or type(self.value) in _MATERIALIZABLE_SCALAR_TYPES
        )

    @property
    def claim_reference_eligible(self) -> bool:
        return self.is_request_public and self.fixture_materializable

    def to_request_record(self) -> dict[str, Any]:
        """Return the complete public record, never a guarded source record."""

        return {
            "fact_id": self.fact_id,
            "identity": _to_plain(self.identity),
            "audience": self.audience,
            "status": self.status,
            "value": _to_plain(self.value),
            "provenance": _to_plain(self.provenance),
            "source_binding": _to_plain(self.source_binding),
        }

    def to_audience_knowledge_record(self) -> dict[str, Any]:
        """Return the exact full-fixture representation used by Study 2."""

        return {
            "fact_id": self.fact_id,
            "audience": self.audience,
            "status": self.status,
            "source_pointer": self.provenance["source_pointer"],
            "source_ref": self.provenance["source_ref"],
            "value": _to_plain(self.value),
        }

    def to_fixture_source_fact(self, scene_node_id: str) -> dict[str, Any] | None:
        """Map eligible public scalar values into the shared fixture fact table.

        Composite values remain complete in ``audience_knowledge`` but the
        unchanged legacy fixture has no source-record encoding for them. Such
        values are consequently ineligible for claim references. Non-public
        records stay only in their audience-classified representation.
        """

        if not self.claim_reference_eligible:
            return None
        return {
            "id": self.fact_id,
            "subject_id": scene_node_id,
            "predicate": "source_record",
            "object_id": scene_node_id,
            "status": "known",
            "value": _to_plain(self.value),
            "provenance": {
                "class": "source_extracted",
                "source_refs": [self.provenance["source_ref"]],
            },
        }


@dataclass(frozen=True)
class SceneFactInventory:
    """One recursively immutable and content-hashed view of a scene's facts."""

    scene_id: str
    module_id: str
    scene_node_id: str
    source_binding: Mapping[str, Any]
    records: tuple[FactRecord, ...]
    protected_unknowns: tuple[Mapping[str, Any], ...]
    protected_unknown_policy: bool
    inventory_sha256: str
    _snapshot: Mapping[str, Any]

    @property
    def request_public_facts(self) -> tuple[FactRecord, ...]:
        return tuple(record for record in self.records if record.is_request_public)

    @property
    def public_fact_ids(self) -> tuple[str, ...]:
        return tuple(record.fact_id for record in self.request_public_facts)

    @property
    def claim_reference_ids(self) -> tuple[str, ...]:
        return tuple(
            record.fact_id
            for record in self.request_public_facts
            if record.claim_reference_eligible
        )

    def to_public_envelope(self) -> dict[str, Any]:
        """Expose public records plus the claim allowlist and their inventory hash."""

        _assert_inventory_matches_canonical(self)
        return {
            "schema": INVENTORY_SCHEMA,
            "scene_id": self.scene_id,
            "inventory_sha256": self.inventory_sha256,
            "source_binding": _to_plain(self.source_binding),
            "public_fact_records": [
                record.to_request_record() for record in self.request_public_facts
            ],
            "claim_reference_ids": list(self.claim_reference_ids),
        }


def load_scene_inventory(scene_id: str) -> SceneFactInventory:
    """Load one inventory from Study 3's hash-verified canonical scene binding."""

    if type(scene_id) is not str or scene_id not in study3_protocol.SCENE_ORDER:
        raise FactInventoryError("STUDY3B_SCENE_NOT_APPROVED")
    try:
        binding = study3_contract.load_scene_binding(scene_id)
    except study3_contract.ContractError as error:
        raise FactInventoryError(error.code) from None

    expected = _to_plain(binding.expected_bundle)
    source_facts = expected.get("source_facts")
    topology = expected.get("approved_topology")
    if (
        type(source_facts) is not dict
        or type(topology) is not dict
        or source_facts.get("scene_id") != scene_id
        or topology.get("scene_id") != scene_id
        or topology.get("module_id") != binding.module_id
    ):
        raise FactInventoryError("STUDY3B_CANONICAL_FACT_BINDING_INVALID")

    raw_facts = source_facts.get("facts")
    if type(raw_facts) is not list or not raw_facts:
        raise FactInventoryError("STUDY3B_CANONICAL_FACTS_INVALID")
    protected = expected.get("protected_unknowns")
    unknown_rows = protected.get("unknowns") if type(protected) is dict else None
    if (
        type(protected) is not dict
        or protected.get("protected_unknowns_must_not_be_promoted") is not True
        or type(unknown_rows) is not list
        or not unknown_rows
    ):
        raise FactInventoryError("STUDY3B_CANONICAL_UNKNOWN_STATES_INVALID")
    protected_unknowns: list[Mapping[str, Any]] = []
    seen_unknowns: set[str] = set()
    for unknown in unknown_rows:
        if (
            type(unknown) is not dict
            or type(unknown.get("predicate")) is not str
            or not unknown["predicate"]
            or unknown["predicate"] in seen_unknowns
            or type(unknown.get("status")) is not str
            or unknown["status"] not in {"unknown", "not_tested"}
        ):
            raise FactInventoryError("STUDY3B_CANONICAL_UNKNOWN_STATES_INVALID")
        seen_unknowns.add(unknown["predicate"])
        protected_unknowns.append(_freeze(_to_plain(unknown)))

    try:
        source_binding = {
            "input_refs": _to_plain(binding.input_refs),
            "source_packet_path": source_facts["source_packet_path"],
            "source_packet_sha256": source_facts["source_packet_sha256"],
            "expected_bundle_path": binding.input_refs["expected_bundle"]["id"],
            "expected_bundle_sha256": binding.input_refs["expected_bundle"]["sha256"],
            "source_file": source_facts["source_file"],
            "source_file_sha256": source_facts["source_file_sha256"],
            "source_identity": _to_plain(source_facts["source_identity"]),
            "source_reference": source_facts["source_reference"],
            "topology_id": topology["topology_id"],
            "topology_sha256": binding.input_refs["topology"]["sha256"],
        }
        scene_node_id = topology["scene_node_id"]
    except (KeyError, TypeError):
        raise FactInventoryError("STUDY3B_CANONICAL_FACT_BINDING_INVALID") from None
    if (
        source_binding["source_packet_path"]
        != binding.input_refs["source_packet"]["id"]
        or source_binding["source_packet_sha256"]
        != binding.input_refs["source_packet"]["sha256"]
        or type(scene_node_id) is not str
        or type(source_binding["source_file"]) is not str
        or type(source_binding["source_file_sha256"]) is not str
        or type(source_binding["source_reference"]) is not str
    ):
        raise FactInventoryError("STUDY3B_CANONICAL_FACT_BINDING_INVALID")

    records: list[FactRecord] = []
    seen_ids: set[str] = set()
    for raw_record in raw_facts:
        if type(raw_record) is not dict or set(raw_record) != _SOURCE_FACT_FIELDS:
            raise FactInventoryError("STUDY3B_CANONICAL_FACT_RECORD_INVALID")
        fact_id = raw_record.get("fact_id")
        audience = raw_record.get("audience")
        status = raw_record.get("status")
        source_pointer = raw_record.get("source_pointer")
        source_ref = raw_record.get("source_ref")
        if (
            type(fact_id) is not str
            or not fact_id
            or fact_id in seen_ids
            or type(audience) is not str
            or type(status) is not str
            or type(source_pointer) is not str
            or type(source_ref) is not str
        ):
            raise FactInventoryError("STUDY3B_CANONICAL_FACT_RECORD_INVALID")
        seen_ids.add(fact_id)
        identity = {
            "scene_id": scene_id,
            "module_id": binding.module_id,
            "fact_id": fact_id,
            "source_identity": source_binding["source_identity"],
        }
        provenance = {
            "source_pointer": source_pointer,
            "source_ref": source_ref,
            "source_reference": source_binding["source_reference"],
            "source_file": source_binding["source_file"],
            "source_file_sha256": source_binding["source_file_sha256"],
        }
        record_binding = {
            key: value
            for key, value in source_binding.items()
            if key not in {"source_identity", "source_reference"}
        }
        records.append(
            FactRecord(
                fact_id=fact_id,
                audience=audience,
                status=status,
                value=_freeze(_to_plain(raw_record.get("value"))),
                identity=_freeze(identity),
                provenance=_freeze(provenance),
                source_binding=_freeze(record_binding),
            )
        )

    public_ids = tuple(
        record.fact_id for record in records if record.audience == PUBLIC_AUDIENCE
    )
    if public_ids != tuple(binding.public_base_fact_ids):
        raise FactInventoryError("STUDY3B_PUBLIC_FACT_BINDING_MISMATCH")

    frozen_source_binding = _freeze(source_binding)
    frozen_records = tuple(records)
    snapshot_value = {
        "schema": INVENTORY_SCHEMA,
        "scene_id": scene_id,
        "module_id": binding.module_id,
        "scene_node_id": scene_node_id,
        "source_binding": source_binding,
        "facts": [record.to_request_record() for record in frozen_records],
        "protected_unknown_policy": True,
        "protected_unknowns": [_to_plain(row) for row in protected_unknowns],
    }
    snapshot = _freeze(snapshot_value)
    digest = hashlib.sha256(_canonical_json_bytes(snapshot_value)).hexdigest()
    inventory = SceneFactInventory(
        scene_id=scene_id,
        module_id=binding.module_id,
        scene_node_id=scene_node_id,
        source_binding=frozen_source_binding,
        records=frozen_records,
        protected_unknowns=tuple(protected_unknowns),
        protected_unknown_policy=True,
        inventory_sha256=digest,
        _snapshot=snapshot,
    )
    _validate_inventory(inventory)
    return inventory


def _validate_inventory(inventory: SceneFactInventory) -> None:
    if type(inventory) is not SceneFactInventory:
        raise FactInventoryError("STUDY3B_INVENTORY_TYPE_INVALID")
    try:
        snapshot = _to_plain(inventory._snapshot)
        matches = (
            type(snapshot) is dict
            and snapshot.get("schema") == INVENTORY_SCHEMA
            and snapshot.get("scene_id") == inventory.scene_id
            and snapshot.get("module_id") == inventory.module_id
            and snapshot.get("scene_node_id") == inventory.scene_node_id
            and snapshot.get("source_binding") == _to_plain(inventory.source_binding)
            and snapshot.get("facts")
            == [record.to_request_record() for record in inventory.records]
            and snapshot.get("protected_unknown_policy")
            is inventory.protected_unknown_policy
            and snapshot.get("protected_unknowns")
            == [_to_plain(row) for row in inventory.protected_unknowns]
            and inventory.protected_unknown_policy is True
            and hashlib.sha256(_canonical_json_bytes(snapshot)).hexdigest()
            == inventory.inventory_sha256
        )
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        matches = False
    if not matches:
        raise FactInventoryError("STUDY3B_INVENTORY_HASH_MISMATCH")


def _assert_inventory_matches_canonical(
    inventory: SceneFactInventory,
    *,
    canonical_inventory: SceneFactInventory | None = None,
) -> None:
    """Reject a self-consistent inventory whose facts differ from source bytes."""

    _validate_inventory(inventory)
    if canonical_inventory is None:
        try:
            canonical_inventory = load_scene_inventory(inventory.scene_id)
        except FactInventoryError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
            raise FactInventoryError("STUDY3B_CANONICAL_FACT_BINDING_INVALID") from None
    _validate_inventory(canonical_inventory)
    if (
        inventory.scene_id != canonical_inventory.scene_id
        or inventory.inventory_sha256 != canonical_inventory.inventory_sha256
        or _to_plain(inventory._snapshot) != _to_plain(canonical_inventory._snapshot)
    ):
        raise FactInventoryError("STUDY3B_INVENTORY_CANONICAL_MISMATCH")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _to_plain(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise FactInventoryError("STUDY3B_INVENTORY_JSON_INVALID") from None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_plain(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_to_plain(item) for item in value]
    if type(value) is dict:
        return {key: _to_plain(item) for key, item in value.items()}
    return value


__all__ = [
    "FactInventoryError",
    "FactRecord",
    "INVENTORY_SCHEMA",
    "PUBLIC_AUDIENCE",
    "SceneFactInventory",
    "_assert_inventory_matches_canonical",
    "load_scene_inventory",
]
