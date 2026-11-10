# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3 request construction and rendered-source parity."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

from . import protocol
from .contract import (
    ContractError,
    _read_bound_reference as _read_canonical_reference,
    audit_rule_parity,
    load_scene_binding,
)


_REQUEST_FIELDS = frozenset(
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
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
_SECTION_MARKERS = {
    "input_refs": (
        "<<<STUDY3_INPUT_REFS_JSON_BEGIN>>>",
        "<<<STUDY3_INPUT_REFS_JSON_END>>>",
        "S3-EXACT-INPUT-REFERENCES",
    ),
    "topology_binding": (
        "<<<STUDY3_TOPOLOGY_BINDING_JSON_BEGIN>>>",
        "<<<STUDY3_TOPOLOGY_BINDING_JSON_END>>>",
        "S3-STAGE-ROLE-CANDIDATES",
    ),
    "public_base_fact_ids": (
        "<<<STUDY3_PUBLIC_BASE_FACT_IDS_JSON_BEGIN>>>",
        "<<<STUDY3_PUBLIC_BASE_FACT_IDS_JSON_END>>>",
        "S3-CLAIM-FACT-REFERENCES",
    ),
    "source_packet": (
        "<<<STUDY3_SOURCE_PACKET_JSON_BEGIN>>>",
        "<<<STUDY3_SOURCE_PACKET_JSON_END>>>",
        "HOST-CANONICAL-HASH-INTEGRITY",
    ),
    "expected_bundle": (
        "<<<STUDY3_EXPECTED_BUNDLE_JSON_BEGIN>>>",
        "<<<STUDY3_EXPECTED_BUNDLE_JSON_END>>>",
        "S3-PROTECTED-UNKNOWNS",
    ),
    "model_contract": (
        "<<<STUDY3_MODEL_CONTRACT_JSON_BEGIN>>>",
        "<<<STUDY3_MODEL_CONTRACT_JSON_END>>>",
        "S3-AUTHORED-ID-NAMESPACE",
    ),
    "output_schema": (
        "<<<STUDY3_OUTPUT_SCHEMA_JSON_BEGIN>>>",
        "<<<STUDY3_OUTPUT_SCHEMA_JSON_END>>>",
        "S3-ROOT-FIELDS",
    ),
}


class RequestBuildError(ValueError):
    """Raised when the pinned Study 3 request cannot be rendered safely."""


class RequestParityError(RequestBuildError):
    """Raised when the actual request messages diverge from frozen declarations."""

    def __init__(self, code: str, rule_id: str, pointer: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.rule_id = rule_id
        self.pointer = pointer


def build_request(scene_id: str) -> dict[str, Any]:
    """Build and audit the exact OpenRouter chat-completions JSON payload.

    This function performs only local, hash-verified reads. It creates no client,
    ledger, allocation, credential access, or network call.
    """

    request = _assemble_request(scene_id)
    audit_request_parity(scene_id, request)
    return request


def request_transport_metadata(scene_id: str) -> dict[str, Any]:
    """Return frozen host transport settings separately from the JSON payload."""

    _approved_scene(scene_id)
    config, config_bytes = _load_generation_config()
    cap = config["attempt_cap"]
    return {
        "study_id": config["study_id"],
        "scene_id": scene_id,
        "provider": config["provider"],
        "endpoint": config["endpoint"],
        "timeout_seconds": config["timeout_seconds"],
        "transport_constraints": deepcopy(config["transport_constraints"]),
        "attempt_cap_identity": cap["identity"],
        "attempt_cap": cap["total"],
        "attempts_per_scene": cap["per_scene"],
        "scene_order": tuple(cap["scene_order"]),
        "generation_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    }


def audit_request_parity(scene_id: str, request: object) -> None:
    """Audit declarations extracted from the actual request messages.

    The validator parity audit receives the rendered system message, the exact
    model-contract/schema sections, the user-visible bindings, and the canonical
    expected bundle. It does not treat an unseen local contract file as the
    source of parity.
    """

    row = _approved_scene(scene_id)
    if type(request) is not dict or set(request) != _REQUEST_FIELDS:
        raise RequestParityError(
            "REQUEST_ENVELOPE_FIELDS_INVALID", "S3-REQUEST-ENVELOPE", "/"
        )
    messages = request.get("messages")
    if (
        type(messages) is not list
        or len(messages) != 2
        or type(messages[0]) is not dict
        or type(messages[1]) is not dict
        or set(messages[0]) != {"role", "content"}
        or set(messages[1]) != {"role", "content"}
        or messages[0].get("role") != "system"
        or messages[1].get("role") != "user"
        or type(messages[0].get("content")) is not str
        or type(messages[1].get("content")) is not str
    ):
        raise RequestParityError(
            "REQUEST_MESSAGES_INVALID", "S3-REQUEST-MESSAGES", "/messages"
        )

    system_message = messages[0]["content"]
    user_message = messages[1]["content"]
    if _PLACEHOLDER_RE.search(system_message) or _PLACEHOLDER_RE.search(user_message):
        raise RequestParityError(
            "REQUEST_PLACEHOLDER_UNRESOLVED", "S3-REQUEST-MESSAGES", "/messages"
        )

    sections: dict[str, str] = {}
    for name, (_begin, _end, rule_id) in _SECTION_MARKERS.items():
        sections[name] = _extract_section(user_message, name, rule_id)

    input_refs = _parse_json_object(
        sections["input_refs"], "REQUEST_INPUT_REFS_INVALID", "S3-EXACT-INPUT-REFERENCES"
    )
    topology_doc = _parse_json_object(
        sections["topology_binding"],
        "REQUEST_TOPOLOGY_BINDING_INVALID",
        "S3-STAGE-ROLE-CANDIDATES",
    )
    public_base_fact_ids = _parse_json_value(
        sections["public_base_fact_ids"],
        "REQUEST_PUBLIC_FACT_IDS_INVALID",
        "S3-CLAIM-FACT-REFERENCES",
    )
    if type(public_base_fact_ids) is not list:
        raise RequestParityError(
            "REQUEST_PUBLIC_FACT_IDS_INVALID", "S3-CLAIM-FACT-REFERENCES"
        )
    source_packet = _parse_json_object(
        sections["source_packet"],
        "REQUEST_SOURCE_PACKET_INVALID",
        "HOST-CANONICAL-HASH-INTEGRITY",
    )
    expected_bundle = _parse_json_object(
        sections["expected_bundle"],
        "REQUEST_EXPECTED_BUNDLE_INVALID",
        "S3-PROTECTED-UNKNOWNS",
    )
    model_contract = _parse_json_object(
        sections["model_contract"],
        "REQUEST_MODEL_CONTRACT_INVALID",
        "S3-AUTHORED-ID-NAMESPACE",
    )
    rendered_schema = _parse_json_object(
        sections["output_schema"],
        "REQUEST_OUTPUT_SCHEMA_INVALID",
        "S3-ROOT-FIELDS",
    )

    actual_binding = {
        "scene_id": input_refs.get("scene_id"),
        "module_id": topology_doc.get("module_id"),
        "input_refs": input_refs,
        "topology_node_ids": topology_doc.get("topology_node_ids"),
        "stage_role_candidates": topology_doc.get("stage_role_candidates"),
        "public_base_fact_ids": public_base_fact_ids,
    }
    bindings_override = {"scenes": [{} for _ in protocol.SCENE_ORDER]}
    bindings_override["scenes"][protocol.SCENE_ORDER.index(scene_id)] = actual_binding

    source_overrides = {
        "system_prompt": {
            "lines": {
                str(index): line
                for index, line in enumerate(system_message.splitlines(), 1)
            }
        },
        "rendered_schema": rendered_schema,
        "model_contract": model_contract,
        "input_bindings": bindings_override,
        "expected_bundle": expected_bundle,
        "task_prompt": {
            "lines": {
                str(index): line
                for index, line in enumerate(user_message.splitlines(), 1)
            }
        },
    }
    try:
        issues = audit_rule_parity(scene_id, source_overrides=source_overrides)
    except (ContractError, OSError, ValueError, TypeError, KeyError, RecursionError):
        raise RequestParityError(
            "REQUEST_PARITY_AUDIT_FAILED",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/messages",
        ) from None
    if issues:
        issue = issues[0]
        raise RequestParityError(issue.code, issue.rule_id, issue.pointer)

    module_id = row["module_id"]
    expected_namespace = module_id + ":fact:study3-authored:<suffix>"
    expected_pattern = (
        "^"
        + re.escape(module_id)
        + r":fact:study3-authored:[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    if expected_namespace not in system_message or expected_pattern not in system_message:
        raise RequestParityError(
            "REQUEST_DECLARATION_MISSING",
            "S3-AUTHORED-ID-NAMESPACE",
            "/messages/0/content",
        )
    if (
        "literal JSON boolean true" not in system_message
        or "approach -> threshold" not in system_message
        or "threshold -> focal_anchor" not in system_message
    ):
        raise RequestParityError(
            "REQUEST_DECLARATION_MISSING",
            "S3-APPROACH-RELATION-TRUE",
            "/messages/0/content",
        )

    try:
        binding = load_scene_binding(scene_id)
        canonical_source = _read_canonical_reference(row["input_refs"]["source_packet"])
        canonical_expected = _read_canonical_reference(row["input_refs"]["expected_bundle"])
        model_contract_bytes = protocol._read_artifact("model_contract")
        config, _config_bytes = _load_generation_config()
        expected_system = protocol.render_system_prompt(scene_id)
        expected_schema_json = protocol.render_output_schema_json(scene_id)
        protocol._read_artifact("task_prompt_template")
    except (ContractError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise RequestParityError(
            "REQUEST_FROZEN_SOURCE_UNAVAILABLE",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/messages",
        ) from None

    if input_refs != row["input_refs"] or input_refs != dict(binding.input_refs):
        raise RequestParityError(
            "REQUEST_INPUT_BINDING_MISMATCH",
            "S3-EXACT-INPUT-REFERENCES",
            "/messages/1/input_refs",
        )
    expected_topology = {
        "module_id": row["module_id"],
        "topology_node_ids": row["topology_node_ids"],
        "stage_role_candidates": row["stage_role_candidates"],
    }
    if topology_doc != expected_topology:
        raise RequestParityError(
            "REQUEST_TOPOLOGY_BINDING_MISMATCH",
            "S3-STAGE-ROLE-CANDIDATES",
            "/messages/1/topology_binding",
        )
    if public_base_fact_ids != row["public_base_fact_ids"]:
        raise RequestParityError(
            "REQUEST_PUBLIC_FACT_IDS_MISMATCH",
            "S3-CLAIM-FACT-REFERENCES",
            "/messages/1/public_base_fact_ids",
        )
    if sections["source_packet"].encode("utf-8") != canonical_source:
        raise RequestParityError(
            "REQUEST_SOURCE_PACKET_MESSAGE_MISMATCH",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/messages/1/source_packet",
        )
    if sections["expected_bundle"].encode("utf-8") != canonical_expected:
        raise RequestParityError(
            "REQUEST_EXPECTED_BUNDLE_MESSAGE_MISMATCH",
            "S3-PROTECTED-UNKNOWNS",
            "/messages/1/expected_bundle",
        )
    if sections["model_contract"].encode("utf-8") != model_contract_bytes:
        raise RequestParityError(
            "REQUEST_MODEL_CONTRACT_MESSAGE_MISMATCH",
            "S3-AUTHORED-ID-NAMESPACE",
            "/messages/1/model_contract",
        )
    if sections["output_schema"] != expected_schema_json:
        raise RequestParityError(
            "REQUEST_OUTPUT_SCHEMA_MESSAGE_MISMATCH",
            "S3-ROOT-FIELDS",
            "/messages/1/output_schema",
        )
    if system_message != expected_system:
        raise RequestParityError(
            "REQUEST_SYSTEM_MESSAGE_MISMATCH",
            "S3-REQUEST-MESSAGES",
            "/messages/0/content",
        )

    expected_user_hash = _rendered_scene_hash(scene_id, "user_message_sha256")
    if hashlib.sha256(user_message.encode("utf-8")).hexdigest() != expected_user_hash:
        raise RequestParityError(
            "REQUEST_USER_MESSAGE_HASH_MISMATCH",
            "S3-REQUEST-MESSAGES",
            "/messages/1/content",
        )
    expected_request = {
        "model": config["model_id"],
        "messages": messages,
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "frequency_penalty": config["frequency_penalty"],
        "presence_penalty": config["presence_penalty"],
        "max_tokens": config["max_tokens"],
        "stream": config["stream"],
        "response_format": config["response_format"],
        "tools": config["tools"],
        "tool_choice": config["tool_choice"],
        "provider": config["provider_options"],
    }
    if not _same_json_value(request, expected_request):
        raise RequestParityError(
            "REQUEST_ENVELOPE_VALUE_MISMATCH", "S3-REQUEST-ENVELOPE", "/"
        )
    if (
        config["provider"] != "openrouter"
        or config["endpoint"] != "https://openrouter.ai/api/v1/chat/completions"
        or type(config["max_tokens"]) is not int
        or config["max_tokens"] != 16384
        or type(config["timeout_seconds"]) is not int
        or config["timeout_seconds"] != 720
        or config["provider_options"] != {"allow_fallbacks": False}
        or config["transport_constraints"]
        != {"retries": 0, "reruns": 0, "redirects": False, "continuation": False}
        or config["stream"] is not False
        or config["tools"] != []
        or config["tool_choice"] != "none"
        or config["dispatch_authorized"] is not False
    ):
        raise RequestParityError(
            "REQUEST_FROZEN_ENVELOPE_INVALID", "S3-REQUEST-ENVELOPE", "/"
        )

def _assemble_request(
    scene_id: str,
) -> dict[str, Any]:
    row = _approved_scene(scene_id)
    binding = load_scene_binding(scene_id)
    config, _config_bytes = _load_generation_config()
    try:
        task_template = protocol._read_artifact("task_prompt_template").decode("utf-8")
        model_contract_bytes = protocol._read_artifact("model_contract")
        source_packet_bytes = _read_canonical_reference(row["input_refs"]["source_packet"])
        expected_bundle_bytes = _read_canonical_reference(row["input_refs"]["expected_bundle"])
        model_contract_text = model_contract_bytes.decode("utf-8")
        source_packet_text = source_packet_bytes.decode("utf-8")
        expected_bundle_text = expected_bundle_bytes.decode("utf-8")
        system_message = protocol.render_system_prompt(scene_id)
        schema_json = protocol.render_output_schema_json(scene_id)
    except (ContractError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise RequestBuildError("STUDY3_REQUEST_SOURCE_INVALID") from None

    topology_binding = {
        "module_id": row["module_id"],
        "topology_node_ids": row["topology_node_ids"],
        "stage_role_candidates": row["stage_role_candidates"],
    }
    substitutions = {
        "{{SCENE_ID}}": scene_id,
        "{{INPUT_REFS_JSON}}": _canonical_json(row["input_refs"]),
        "{{TOPOLOGY_BINDING_JSON}}": _canonical_json(topology_binding),
        "{{PUBLIC_BASE_FACT_IDS_JSON}}": _canonical_json(row["public_base_fact_ids"]),
        "{{SOURCE_PACKET_JSON}}": source_packet_text,
        "{{EXPECTED_BUNDLE_JSON}}": expected_bundle_text,
        "{{MODEL_CONTRACT_JSON}}": model_contract_text,
        "{{OUTPUT_SCHEMA_JSON}}": schema_json,
    }
    user_message = _render_template(task_template, substitutions)
    request = {
        "model": config["model_id"],
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
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
    if tuple(row["input_refs"].keys()) != tuple(binding.input_refs.keys()):
        raise RequestBuildError("STUDY3_REQUEST_BINDING_ORDER_INVALID")
    return request


def _render_template(template: str, substitutions: Mapping[str, str]) -> str:
    rendered = template
    for placeholder, value in substitutions.items():
        if rendered.count(placeholder) != 1:
            raise RequestBuildError("STUDY3_TASK_PROMPT_PLACEHOLDER_INVALID")
        begin_or_end_markers = tuple(
            marker
            for begin, end, _rule_id in _SECTION_MARKERS.values()
            for marker in (begin, end)
        )
        if any(marker in value for marker in begin_or_end_markers):
            raise RequestBuildError("STUDY3_TASK_PROMPT_SECTION_COLLISION")
        rendered = rendered.replace(placeholder, value)
    if _PLACEHOLDER_RE.search(rendered):
        raise RequestBuildError("STUDY3_TASK_PROMPT_PLACEHOLDER_UNRESOLVED")
    return rendered


def _extract_section(user_message: str, name: str, rule_id: str) -> str:
    begin, end, _mapped_rule = _SECTION_MARKERS[name]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        code = "REQUEST_" + name.upper() + "_SECTION_MISSING"
        raise RequestParityError(code, rule_id, "/messages/1/" + name)
    start = user_message.index(begin) + len(begin)
    finish = user_message.index(end)
    if finish < start:
        raise RequestParityError(
            "REQUEST_SECTION_ORDER_INVALID", rule_id, "/messages/1/" + name
        )
    contents = user_message[start:finish]
    if contents.startswith("\n"):
        contents = contents[1:]
    if contents.endswith("\n"):
        contents = contents[:-1]
    if not contents:
        code = "REQUEST_" + name.upper() + "_SECTION_EMPTY"
        raise RequestParityError(code, rule_id, "/messages/1/" + name)
    return contents


def _parse_json_object(text: str, code: str, rule_id: str) -> dict[str, Any]:
    value = _parse_json_value(text, code, rule_id)
    if type(value) is not dict:
        raise RequestParityError(code, rule_id)
    return value


def _parse_json_value(text: str, code: str, rule_id: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        raise RequestParityError(code, rule_id) from None
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _reject_nonfinite_constant(_value: str) -> None:
    raise ValueError("non-finite value")


def _load_generation_config() -> tuple[dict[str, Any], bytes]:
    try:
        raw = protocol._read_artifact("generation_config")
        config = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise RequestBuildError("STUDY3_GENERATION_CONFIG_INVALID") from None
    if type(config) is not dict:
        raise RequestBuildError("STUDY3_GENERATION_CONFIG_INVALID")
    expected_fields = {
        "schema",
        "study_id",
        "preparation_only",
        "dispatch_authorized",
        "endpoint",
        "provider",
        "model_id",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "max_tokens",
        "timeout_seconds",
        "response_format",
        "stream",
        "tools",
        "tool_choice",
        "provider_options",
        "transport_constraints",
        "attempt_cap",
        "approval",
        "cost_estimates",
    }
    if set(config) != expected_fields:
        raise RequestBuildError("STUDY3_GENERATION_CONFIG_FIELDS_INVALID")
    return config, raw


def _approved_scene(scene_id: str) -> dict[str, Any]:
    if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
        raise RequestBuildError("STUDY3_SCENE_NOT_APPROVED")
    try:
        bindings = protocol.load_input_bindings()
    except (OSError, ValueError, TypeError, KeyError):
        raise RequestBuildError("STUDY3_INPUT_BINDINGS_INVALID") from None
    rows = bindings.get("scenes")
    if type(rows) is not list or len(rows) != len(protocol.SCENE_ORDER):
        raise RequestBuildError("STUDY3_INPUT_BINDINGS_INVALID")
    row = next(
        (item for item in rows if type(item) is dict and item.get("scene_id") == scene_id),
        None,
    )
    if type(row) is not dict:
        raise RequestBuildError("STUDY3_SCENE_BINDING_MISSING")
    return row


def _rendered_scene_hash(scene_id: str, field: str) -> str:
    manifest = protocol._load_manifest()
    records = manifest.get("rendered_scene_artifacts")
    if type(records) is not list:
        raise RequestParityError(
            "STUDY3_RENDERED_ARTIFACT_BINDING_INVALID",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/rendered_scene_artifacts",
        )
    record = next(
        (
            item
            for item in records
            if type(item) is dict and item.get("scene_id") == scene_id
        ),
        None,
    )
    digest = record.get(field) if type(record) is dict else None
    if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise RequestParityError(
            "STUDY3_RENDERED_ARTIFACT_BINDING_INVALID",
            "HOST-CANONICAL-HASH-INTEGRITY",
            "/rendered_scene_artifacts",
        )
    return digest


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
        raise RequestBuildError("STUDY3_REQUEST_JSON_INVALID") from None


def _same_json_value(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


__all__ = [
    "RequestBuildError",
    "RequestParityError",
    "audit_request_parity",
    "build_request",
    "request_transport_metadata",
]
