# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Study 3b request adapter driven by its immutable per-scene fact inventory."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from . import protocol as study3b_protocol
from .study3_compat import newrequest as study3_request
from .inventory import (
    FactInventoryError,
    SceneFactInventory,
    _assert_inventory_matches_canonical,
    load_scene_inventory,
)


_PUBLIC_FACTS_BEGIN = "<<<STUDY3B_PUBLIC_FACT_INVENTORY_JSON_BEGIN>>>"
_PUBLIC_FACTS_END = "<<<STUDY3B_PUBLIC_FACT_INVENTORY_JSON_END>>>"
_ENVELOPE_FIELDS = frozenset(
    {
        "model",
        "messages",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "max_tokens",
        "stream",
        "response_format",
        "tools",
        "tool_choice",
        "provider",
    }
)


class RequestParityError(ValueError):
    """Bounded failure when the Study 3b request diverges from its inventory."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_request(scene_id: str) -> dict[str, Any]:
    """Render a local Study 3b request without exposing guarded source payloads."""

    _approved_scene(scene_id)
    generation_config = study3b_protocol.load_generation_config()
    inventory = load_scene_inventory(scene_id)
    request = _assemble_request(
        scene_id,
        inventory=inventory,
        generation_config=generation_config,
    )
    audit_request_parity(scene_id, request, inventory=inventory)
    return request


def request_transport_metadata(scene_id: str) -> dict[str, Any]:
    """Return Study 3b identity and fixed transport limits, without dispatch."""

    _approved_scene(scene_id)
    config = study3b_protocol.load_generation_config()
    cap = config["attempt_cap"]
    return {
        "study_id": config["study_id"],
        "protocol_version": config["protocol_version"],
        "scene_id": scene_id,
        "provider": config["provider"],
        "endpoint": config["endpoint"],
        "model_id": config["model_id"],
        "timeout_seconds": config["timeout_seconds"],
        "dispatch_authorized": config["dispatch_authorized"],
        "transport_constraints": deepcopy(config["transport_constraints"]),
        "attempt_cap_identity": cap["identity"],
        "attempt_cap": cap["total"],
        "attempts_per_scene": cap["per_scene"],
        "scene_order": tuple(cap["scene_order"]),
        "manifest_sha256": study3b_protocol.MANIFEST_SHA256,
        "generation_config_sha256": study3b_protocol.GENERATION_CONFIG_SHA256,
    }


def audit_request_parity(
    scene_id: str,
    request: object,
    *,
    inventory: SceneFactInventory | None = None,
) -> None:
    """Require exact request equality with fresh source bindings and inventory."""

    if type(scene_id) is not str or scene_id not in study3b_protocol.SCENE_ORDER:
        raise RequestParityError("STUDY3B_SCENE_NOT_APPROVED")
    if type(request) is not dict or set(request) != _ENVELOPE_FIELDS:
        raise RequestParityError("STUDY3B_REQUEST_ENVELOPE_INVALID")
    try:
        config = study3b_protocol.load_generation_config()
        expected = _assemble_request(
            scene_id,
            inventory=inventory,
            generation_config=config,
        )
    except (FactInventoryError, study3b_protocol.Study3bProtocolError, ValueError, KeyError):
        raise RequestParityError("STUDY3B_REQUEST_SOURCE_INVALID") from None
    if not _same_json_value(request, expected):
        raise RequestParityError("STUDY3B_REQUEST_INVENTORY_PARITY_FAILED")


def _assemble_request(
    scene_id: str,
    *,
    inventory: SceneFactInventory | None = None,
    generation_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if type(scene_id) is not str or scene_id not in study3b_protocol.SCENE_ORDER:
        raise RequestParityError("STUDY3B_SCENE_NOT_APPROVED")
    if generation_config is None:
        generation_config = study3b_protocol.load_generation_config()
    else:
        study3b_protocol.validate_generation_config(generation_config)
    if inventory is None:
        inventory = load_scene_inventory(scene_id)
    _assert_inventory_matches_canonical(inventory)
    if inventory.scene_id != scene_id:
        raise RequestParityError("STUDY3B_REQUEST_IDENTITY_MISMATCH")

    # The Study 3 builder verifies frozen request inputs before this adapter
    # removes the full source/expected bundles from the Study 3b request.
    request = deepcopy(study3_request.build_request(scene_id))
    request.update(_generation_request_fields(generation_config))
    user_message = request["messages"][1]["content"]
    refs = _request_section_json(user_message, "input_refs")
    topology = _request_section_json(user_message, "topology_binding")
    safe_source_packet = {
        "scene_id": scene_id,
        "source_packet_ref": refs["source_packet"],
        "notice": "Use only the public fact inventory below; canonical source bytes stay host-owned.",
    }
    safe_expected_bundle = {
        "scene_id": scene_id,
        "expected_bundle_ref": refs["expected_bundle"],
        "inventory_sha256": inventory.inventory_sha256,
        "unknown_policy": "REMAIN_UNKNOWN; DO_NOT_PROMOTE_OR_INFER",
    }
    schema = _request_section_json(user_message, "output_schema")
    _restrict_claim_fact_ids(schema, inventory.claim_reference_ids)

    user_message = _replace_section(
        user_message, "source_packet", _canonical_json(safe_source_packet)
    )
    user_message = _replace_section(
        user_message, "expected_bundle", _canonical_json(safe_expected_bundle)
    )
    user_message = _replace_section(
        user_message,
        "public_base_fact_ids",
        _canonical_json(list(inventory.claim_reference_ids)),
    )
    user_message = _replace_section(
        user_message, "output_schema", _canonical_json(schema)
    )

    public_envelope = inventory.to_public_envelope()
    if topology.get("module_id") != inventory.module_id:
        raise RequestParityError("STUDY3B_REQUEST_IDENTITY_MISMATCH")
    user_message += (
        "\n\nStudy 3b public fact inventory (hash-bound; claim IDs are the only "
        "source facts eligible for claims):\n"
        + _PUBLIC_FACTS_BEGIN
        + "\n"
        + _canonical_json(public_envelope)
        + "\n"
        + _PUBLIC_FACTS_END
    )
    result = deepcopy(request)
    result["messages"][1]["content"] = user_message
    return result


def _generation_request_fields(config: dict[str, Any]) -> dict[str, Any]:
    """Copy only the pinned Study 3b generation envelope into the provider body."""

    return {
        "model": config["model_id"],
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "frequency_penalty": config["frequency_penalty"],
        "presence_penalty": config["presence_penalty"],
        "max_tokens": config["max_tokens"],
        "stream": config["stream"],
        "response_format": deepcopy(config["response_format"]),
        "tools": deepcopy(config["tools"]),
        "tool_choice": config["tool_choice"],
        "provider": deepcopy(config["provider_options"]),
    }


def _approved_scene(scene_id: str) -> None:
    if type(scene_id) is not str or scene_id not in study3b_protocol.SCENE_ORDER:
        raise RequestParityError("STUDY3B_SCENE_NOT_APPROVED")


def _restrict_claim_fact_ids(schema: dict[str, Any], fact_ids: tuple[str, ...]) -> None:
    try:
        refs = schema["$defs"]["fact_ref_value"]["properties"]["fact_id"]["anyOf"]
        claims = schema["$defs"]["claim"]["properties"]["fact_id"]["anyOf"]
        if (
            type(refs) is not list
            or not refs
            or type(claims) is not list
            or not claims
            or refs[0].get("enum") is None
            or claims[0].get("enum") is None
        ):
            raise KeyError("fact reference schema")
        refs[0]["enum"] = list(fact_ids)
        claims[0]["enum"] = list(fact_ids)
    except (AttributeError, IndexError, KeyError, TypeError):
        raise RequestParityError("STUDY3B_REQUEST_SCHEMA_BINDING_INVALID") from None


def _request_section_json(user_message: str, name: str) -> Any:
    begin, end, _rule_id = study3_request._SECTION_MARKERS[name]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        raise RequestParityError("STUDY3B_REQUEST_SECTION_INVALID")
    start = user_message.index(begin) + len(begin)
    finish = user_message.index(end)
    if finish < start:
        raise RequestParityError("STUDY3B_REQUEST_SECTION_INVALID")
    contents = user_message[start:finish]
    if contents.startswith("\n"):
        contents = contents[1:]
    if contents.endswith("\n"):
        contents = contents[:-1]
    try:
        return json.loads(contents)
    except (json.JSONDecodeError, ValueError, RecursionError):
        raise RequestParityError("STUDY3B_REQUEST_SECTION_INVALID") from None


def _replace_section(user_message: str, name: str, replacement: str) -> str:
    begin, end, _rule_id = study3_request._SECTION_MARKERS[name]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        raise RequestParityError("STUDY3B_REQUEST_SECTION_INVALID")
    begin_index = user_message.index(begin)
    payload_start = begin_index + len(begin)
    if user_message[payload_start : payload_start + 1] == "\n":
        payload_start += 1
    payload_end = user_message.index(end)
    if user_message[payload_end - 1 : payload_end] == "\n":
        payload_end -= 1
    return user_message[:payload_start] + replacement + user_message[payload_end:]


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError):
        raise RequestParityError("STUDY3B_REQUEST_JSON_INVALID") from None


def _same_json_value(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


__all__ = ["RequestParityError", "audit_request_parity", "build_request"]
