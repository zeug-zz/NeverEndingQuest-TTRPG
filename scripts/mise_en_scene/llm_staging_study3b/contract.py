# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3b claim-reference contract layered on the unchanged Study 3 gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .study3_compat import contract as study3_contract
from .inventory import (
    FactInventoryError,
    SceneFactInventory,
    _assert_inventory_matches_canonical,
    load_scene_inventory,
)


ContractError = study3_contract.ContractError


def validate_delta_payload(
    output_bytes: object,
    *,
    scene_id: str,
    inventory: SceneFactInventory | None = None,
) -> Mapping[str, Any]:
    """Validate a delta and reject claims outside canonical materialization
    eligibility.
    """

    try:
        if inventory is None:
            inventory = load_scene_inventory(scene_id)
        _assert_inventory_matches_canonical(inventory)
        if inventory.scene_id != scene_id:
            raise FactInventoryError("STUDY3B_INVENTORY_IDENTITY_MISMATCH")
        validated = study3_contract.validate_delta_payload(
            output_bytes, scene_id=scene_id
        )
    except FactInventoryError as error:
        raise ContractError(
            error.code, "HOST-CANONICAL-HASH-INTEGRITY", "/source_facts"
        ) from None

    eligible = set(inventory.claim_reference_ids)
    public = set(inventory.public_fact_ids)
    all_source_ids = {record.fact_id for record in inventory.records}
    claims = validated.get("claims")
    if type(claims) is not tuple:
        raise ContractError(
            "STUDY3B_CLAIM_REFERENCES_INVALID", "S3-CLAIM-FACT-REFERENCES", "/claims"
        )
    fixture_deltas = validated.get("fixture_deltas")
    authored_rows = (
        fixture_deltas.get("facts") if isinstance(fixture_deltas, Mapping) else None
    )
    if type(authored_rows) is not tuple:
        raise ContractError(
            "STUDY3B_CLAIM_REFERENCES_INVALID",
            "S3-CLAIM-FACT-REFERENCES",
            "/fixture_deltas/facts",
        )
    authored_ids: set[str] = set()
    for authored in authored_rows:
        fact_id = authored.get("fact_id") if isinstance(authored, Mapping) else None
        if type(fact_id) is not str:
            raise ContractError(
                "STUDY3B_CLAIM_REFERENCES_INVALID",
                "S3-CLAIM-FACT-REFERENCES",
                "/fixture_deltas/facts",
            )
        authored_ids.add(fact_id)

    for group_index, group in enumerate(claims):
        if not isinstance(group, Mapping):
            raise ContractError(
                "STUDY3B_CLAIM_REFERENCES_INVALID",
                "S3-CLAIM-FACT-REFERENCES",
                "/claims/" + str(group_index),
            )
        items = group.get("items")
        if type(items) is not tuple:
            raise ContractError(
                "STUDY3B_CLAIM_REFERENCES_INVALID",
                "S3-CLAIM-FACT-REFERENCES",
                "/claims/" + str(group_index) + "/items",
            )
        for item_index, claim in enumerate(items):
            if not isinstance(claim, Mapping):
                raise ContractError(
                    "STUDY3B_CLAIM_REFERENCES_INVALID",
                    "S3-CLAIM-FACT-REFERENCES",
                    "/claims/" + str(group_index) + "/items/" + str(item_index),
                )
            fact_id = claim.get("fact_id")
            if fact_id in eligible or fact_id in authored_ids:
                continue
            if fact_id in all_source_ids and fact_id in public:
                raise ContractError(
                    "STUDY3B_FACT_NOT_MATERIALIZABLE",
                    "S3-CLAIM-FACT-REFERENCES",
                    "/claims/" + str(group_index) + "/items/" + str(item_index) + "/fact_id",
                )
            if fact_id in all_source_ids:
                raise ContractError(
                    "STUDY3B_FACT_NOT_CLAIM_ELIGIBLE",
                    "S3-CLAIM-FACT-REFERENCES",
                    "/claims/" + str(group_index) + "/items/" + str(item_index) + "/fact_id",
                )
            raise ContractError(
                "STUDY3B_CLAIM_REFERENCES_INVALID",
                "S3-CLAIM-FACT-REFERENCES",
                "/claims/" + str(group_index) + "/items/" + str(item_index) + "/fact_id",
            )
    return validated


__all__ = ["ContractError", "validate_delta_payload"]
