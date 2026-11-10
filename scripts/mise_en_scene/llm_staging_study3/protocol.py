# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Read-only helpers for rendering the frozen Study 3 protocol contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3-contract-parity/protocol"
)
PROTOCOL_ROOT = REPO_ROOT / PROTOCOL_RELATIVE
STUDY_ID = "mise-en-scene-study3-20261110"
MODEL_ID = "openai/gpt-6-luna"
STUDY3_MANIFEST_SHA256 = "15f2d9b6752c0f29adb48e6b597d0739600f107cb5574121bfdb4b6023581858"
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
_ARRIVAL_ROLES = ("approach", "threshold", "focal")
_STAGE_ROLES = ("approach", "threshold", "focal_anchor", "usable_space")
_ARTIFACT_PATHS = {
    "protocol": PROTOCOL_RELATIVE + "/protocol.md",
    "input_bindings": PROTOCOL_RELATIVE + "/input-bindings.json",
    "model_contract": PROTOCOL_RELATIVE + "/model-contract.json",
    "schema_template": PROTOCOL_RELATIVE + "/output-contract.schema.json",
    "system_prompt_template": PROTOCOL_RELATIVE + "/system-prompt.txt",
    "task_prompt_template": PROTOCOL_RELATIVE + "/task-prompt.txt",
    "generation_config": PROTOCOL_RELATIVE + "/generation-config.json",
}


def load_input_bindings() -> dict[str, Any]:
    """Load the fixed Study 3 bindings without reading model outputs or runtime state."""

    try:
        document = json.loads(_read_artifact("input_bindings").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("STUDY3_INPUT_BINDINGS_INVALID") from None
    if type(document) is not dict:
        raise ValueError("STUDY3_INPUT_BINDINGS_INVALID")
    if (
        document.get("schema") != "neq.llm_staging_study3_input_bindings.v1"
        or document.get("study_id") != STUDY_ID
        or tuple(row.get("scene_id") for row in document.get("scenes", []))
        != SCENE_ORDER
    ):
        raise ValueError("STUDY3_INPUT_BINDINGS_INVALID")
    return document


def render_system_prompt(scene_id: str) -> str:
    """Render only the module-specific namespace token in the system prompt."""

    binding = _scene_binding(scene_id)
    try:
        template = _read_artifact("system_prompt_template").decode("utf-8")
    except UnicodeError:
        raise ValueError("STUDY3_SYSTEM_PROMPT_INVALID") from None
    module_id = binding["module_id"]
    authored_prefix = module_id + ":fact:study3-authored:"
    substitutions = {
        "{{MODULE_ID}}": module_id,
        "{{AUTHORED_NAMESPACE}}": authored_prefix + "<suffix>",
        "{{AUTHORED_FACT_ID_PATTERN}}": _authored_fact_pattern(module_id),
    }
    for placeholder, replacement in substitutions.items():
        if template.count(placeholder) != 1:
            raise ValueError("STUDY3_SYSTEM_PROMPT_TEMPLATE_INVALID")
        template = template.replace(placeholder, replacement)
    if "{{" in template or "}}" in template:
        raise ValueError("STUDY3_SYSTEM_PROMPT_PLACEHOLDER_UNRESOLVED")
    _verify_rendered_hash(scene_id, "system_prompt_sha256", template.encode("utf-8"))
    return template


def render_output_schema(scene_id: str) -> dict[str, Any]:
    """Return the closed JSON Schema injected for this exact frozen scene."""

    binding = _scene_binding(scene_id)
    try:
        schema_template = json.loads(_read_artifact("schema_template").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("STUDY3_OUTPUT_SCHEMA_INVALID") from None
    if type(schema_template) is not dict:
        raise ValueError("STUDY3_OUTPUT_SCHEMA_INVALID")
    schema = deepcopy(schema_template)
    references = binding["input_refs"]

    refs_schema = schema["$defs"]["input_refs"]["properties"]
    refs_schema["scene_id"] = {"const": scene_id}
    for name in ("source_packet", "expected_bundle", "topology", "gate_canonical_context"):
        ref_schema = refs_schema[name]["$ref"]
        definition = schema["$defs"][ref_schema.rsplit("/", 1)[1]]["properties"]
        definition["id"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "const": references[name]["id"],
        }
        definition["sha256"] = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "const": references[name]["sha256"],
        }

    topology_ids = binding["topology_node_ids"]
    public_fact_ids = binding["public_base_fact_ids"]
    entity_ref = schema["$defs"]["entity_ref_value"]["properties"]["entity_id"]
    entity_ref["enum"] = topology_ids
    fact_id_schema = schema["$defs"]["authored_fact"]["properties"]["fact_id"]
    fact_id_schema["pattern"] = _authored_fact_pattern(binding["module_id"])

    for property_name in ("subject_id",):
        schema["$defs"]["authored_fact"]["properties"][property_name]["enum"] = topology_ids
    schema["$defs"]["authored_fact"]["properties"]["object_id"] = {
        "anyOf": [
            {"type": "string", "minLength": 1, "maxLength": 256, "enum": topology_ids},
            {"type": "null"},
        ]
    }
    for role in _STAGE_ROLES:
        schema["$defs"]["stage_role_bindings"]["properties"][role] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "enum": binding["stage_role_candidates"][role],
            },
        }

    authored_id = {
        "type": "string",
        "minLength": 1,
        "maxLength": 256,
        "pattern": _authored_fact_pattern(binding["module_id"]),
    }
    base_or_authored_fact_id = {
        "anyOf": [
            {"type": "string", "enum": public_fact_ids},
            authored_id,
        ]
    }
    schema["$defs"]["fact_ref_value"]["properties"]["fact_id"] = deepcopy(
        base_or_authored_fact_id
    )
    schema["$defs"]["claim"]["properties"]["fact_id"] = deepcopy(
        base_or_authored_fact_id
    )

    claim_id = schema["$defs"]["claim"]["properties"]["id"]
    claim_id["pattern"] = _claim_id_pattern(scene_id)
    for index, role in enumerate(_ARRIVAL_ROLES):
        segment_id = scene_id + ":arrival:" + role
        schema["$defs"]["claims"]["prefixItems"][index] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["segment_id", "items"],
            "properties": {
                "segment_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "const": segment_id,
                },
                "items": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {"$ref": "#/$defs/claim"},
                },
            },
        }
        schema["$defs"]["arrival_" + role]["properties"]["id"]["const"] = segment_id

    return schema


def render_output_schema_json(scene_id: str) -> str:
    """Serialize the exact injected schema with the protocol canonical form."""

    serialized = json.dumps(
        render_output_schema(scene_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    _verify_rendered_hash(
        scene_id,
        "output_schema_canonical_sha256",
        serialized.encode("utf-8"),
    )
    return serialized


def _scene_binding(scene_id: str) -> dict[str, Any]:
    if type(scene_id) is not str or scene_id not in SCENE_ORDER:
        raise ValueError("STUDY3_SCENE_NOT_APPROVED")
    for row in load_input_bindings()["scenes"]:
        if row["scene_id"] == scene_id:
            return row
    raise ValueError("STUDY3_SCENE_BINDING_MISSING")


def _load_manifest() -> dict[str, Any]:
    try:
        manifest_bytes = _safe_project_read(PROTOCOL_RELATIVE + "/staging-manifest.json")
        if hashlib.sha256(manifest_bytes).hexdigest() != STUDY3_MANIFEST_SHA256:
            raise ValueError("STUDY3_MANIFEST_HASH_MISMATCH")
        value = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("STUDY3_MANIFEST_INVALID") from None
    if (
        type(value) is not dict
        or value.get("schema") != "neq.llm_staging_study3_manifest.v1"
        or value.get("study_id") != STUDY_ID
        or tuple(value.get("scene_order", ())) != SCENE_ORDER
    ):
        raise ValueError("STUDY3_MANIFEST_INVALID")
    return value


def _read_artifact(role: str) -> bytes:
    manifest = _load_manifest()
    record = manifest.get("artifacts", {}).get(role)
    if (
        type(record) is not dict
        or record.get("path") != _ARTIFACT_PATHS.get(role)
        or type(record.get("sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
    ):
        raise ValueError("STUDY3_ARTIFACT_BINDING_INVALID")
    try:
        contents = _safe_project_read(record["path"])
    except (OSError, ValueError):
        raise ValueError("STUDY3_ARTIFACT_UNAVAILABLE") from None
    if hashlib.sha256(contents).hexdigest() != record["sha256"]:
        raise ValueError("STUDY3_ARTIFACT_HASH_MISMATCH")
    return contents


# TABLETOP MODE: Keep Study 3 protocol reads project-bound and hash-verified.
def _safe_project_read(relative_path: str) -> bytes:
    """Read a regular repository file without traversal or symlink components."""

    if (
        type(relative_path) is not str
        or not relative_path
        or "\\" in relative_path
        or any(part in ("", ".", "..") for part in relative_path.split("/"))
    ):
        raise ValueError("STUDY3_PATH_REJECTED")
    raw = Path(relative_path)
    if raw.is_absolute() or raw.as_posix() != relative_path:
        raise ValueError("STUDY3_PATH_REJECTED")
    try:
        root = REPO_ROOT.resolve(strict=True)
        current = root
        for part in raw.parts:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError("STUDY3_PATH_REJECTED")
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError("STUDY3_FILE_INVALID")
        return resolved.read_bytes()
    except ValueError:
        raise
    except (OSError, RuntimeError):
        raise ValueError("STUDY3_ARTIFACT_UNAVAILABLE") from None


def _verify_rendered_hash(scene_id: str, field: str, contents: bytes) -> None:
    manifest = _load_manifest()
    records = manifest.get("rendered_scene_artifacts")
    if type(records) is not list:
        raise ValueError("STUDY3_RENDERED_ARTIFACT_BINDING_INVALID")
    record = next(
        (row for row in records if type(row) is dict and row.get("scene_id") == scene_id),
        None,
    )
    expected_hash = record.get(field) if type(record) is dict else None
    if (
        type(expected_hash) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        or hashlib.sha256(contents).hexdigest() != expected_hash
    ):
        raise ValueError("STUDY3_RENDERED_ARTIFACT_HASH_MISMATCH")


def _authored_fact_pattern(module_id: str) -> str:
    return (
        "^"
        + re.escape(module_id)
        + r":fact:study3-authored:[A-Za-z0-9][A-Za-z0-9._-]*$"
    )


def _claim_id_pattern(scene_id: str) -> str:
    return "^" + re.escape(scene_id) + r":claim:[A-Za-z0-9][A-Za-z0-9._-]*$"


__all__ = [
    "MODEL_ID",
    "SCENE_ORDER",
    "STUDY_ID",
    "load_input_bindings",
    "render_output_schema",
    "render_output_schema_json",
    "render_system_prompt",
]
