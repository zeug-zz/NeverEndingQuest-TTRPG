# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Read-only, hash-bound Study 3b protocol and generation configuration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from . import isolation

REPO_ROOT = Path(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)
STUDY_ID = "mise-en-scene-study3b-20261111"
PROTOCOL_VERSION = "neq.llm_staging_study3b_delta.v1"
MODEL_ID = "openai/gpt-6-luna"
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
MANIFEST_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3b-hydration-parity/"
    "protocol/staging-manifest.json"
)
PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3b-hydration-parity/"
    "protocol/protocol.md"
)
GENERATION_CONFIG_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3b-hydration-parity/"
    "protocol/generation-config.json"
)
MANIFEST_SHA256 = "70fcfde97e0ccdd4641004cbd3fb35e9ade9d3babc8619292c480305d95793fa"
PROTOCOL_SHA256 = "0fe80b51a652d7d44127a966b0794bada2912de86178243e3397d9949367fcf6"
GENERATION_CONFIG_SHA256 = "071c0a40ab2450e8d9bf0222ad5e604e17dda2743774c8b9a717938901027c78"

SOURCE_STUDY_ID = "mise-en-scene-study3-20261110"
SOURCE_STUDY3_MANIFEST_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3-contract-parity/"
    "protocol/staging-manifest.json"
)
SOURCE_STUDY3_PROTOCOL_RELATIVE = (
    "openspec/changes/v2-mise-en-scene-study3-contract-parity/"
    "protocol/protocol.md"
)
SOURCE_STUDY3_MANIFEST_SHA256 = (
    "15f2d9b6752c0f29adb48e6b597d0739600f107cb5574121bfdb4b6023581858"
)
SOURCE_STUDY3_PROTOCOL_SHA256 = (
    "61bf6d5011eb72822d0d42beb815a512b36896022b93d38687120ec4c827886e"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACTS = {
    "protocol": (PROTOCOL_RELATIVE, PROTOCOL_SHA256),
    "generation_config": (GENERATION_CONFIG_RELATIVE, GENERATION_CONFIG_SHA256),
}


class Study3bProtocolError(ValueError):
    """Metadata-only protocol failure with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def load_manifest() -> dict[str, Any]:
    """Load the exact Study 3b manifest after verifying its pinned digest."""

    try:
        raw = _safe_project_read(MANIFEST_RELATIVE)
    except (OSError, ValueError):
        raise Study3bProtocolError("STUDY3B_MANIFEST_UNAVAILABLE") from None
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise Study3bProtocolError("STUDY3B_MANIFEST_HASH_MISMATCH")
    manifest = _parse_json(raw, "STUDY3B_MANIFEST_INVALID")
    validate_manifest(manifest)
    _verify_source_provenance(manifest)
    return manifest


def validate_manifest(manifest: object) -> None:
    """Reject identity, order, attempt-cap, provenance, or artifact drift."""

    expected_fields = {
        "schema",
        "study_id",
        "protocol_version",
        "status",
        "software_preparation_readiness",
        "dispatch_authorized",
        "scene_order",
        "attempt_cap",
        "source_provenance",
        "artifacts",
        "hash_canonicalization",
    }
    if type(manifest) is not dict or set(manifest) != expected_fields:
        raise Study3bProtocolError("STUDY3B_MANIFEST_FIELDS_INVALID")
    if (
        manifest.get("schema") != "neq.llm_staging_study3b_manifest.v1"
        or manifest.get("study_id") != STUDY_ID
        or manifest.get("protocol_version") != PROTOCOL_VERSION
        or manifest.get("status") != "CONTRACT_PREPARATION_ONLY"
        or manifest.get("software_preparation_readiness") != "PENDING"
        or manifest.get("dispatch_authorized") is not False
        or manifest.get("scene_order") != list(SCENE_ORDER)
    ):
        raise Study3bProtocolError("STUDY3B_MANIFEST_IDENTITY_INVALID")

    expected_cap = {
        "identity": STUDY_ID,
        "total": 3,
        "per_scene": 1,
        "scene_order": list(SCENE_ORDER),
    }
    if not _same_json_value(manifest.get("attempt_cap"), expected_cap):
        raise Study3bProtocolError("STUDY3B_MANIFEST_ATTEMPT_CAP_INVALID")

    expected_source = {
        "study_id": SOURCE_STUDY_ID,
        "manifest": {
            "path": SOURCE_STUDY3_MANIFEST_RELATIVE,
            "sha256": SOURCE_STUDY3_MANIFEST_SHA256,
        },
        "protocol": {
            "path": SOURCE_STUDY3_PROTOCOL_RELATIVE,
            "sha256": SOURCE_STUDY3_PROTOCOL_SHA256,
        },
    }
    if not _same_json_value(manifest.get("source_provenance"), expected_source):
        raise Study3bProtocolError("STUDY3B_SOURCE_PROVENANCE_INVALID")

    artifacts = manifest.get("artifacts")
    expected_artifact_names = set(_ARTIFACTS)
    if type(artifacts) is not dict or set(artifacts) != expected_artifact_names:
        raise Study3bProtocolError("STUDY3B_MANIFEST_ARTIFACTS_INVALID")
    for role, (expected_path, expected_hash) in _ARTIFACTS.items():
        record = artifacts.get(role)
        if (
            type(record) is not dict
            or set(record) != {"path", "sha256"}
            or record.get("path") != expected_path
            or record.get("sha256") != expected_hash
            or type(record.get("sha256")) is not str
            or _SHA256_RE.fullmatch(record["sha256"]) is None
        ):
            raise Study3bProtocolError("STUDY3B_MANIFEST_ARTIFACT_BINDING_INVALID")

    if manifest.get("hash_canonicalization") != (
        "Protocol and configuration hashes cover exact stored UTF-8 bytes; "
        "manifest SHA-256 is pinned by the Study 3b protocol module."
    ):
        raise Study3bProtocolError("STUDY3B_MANIFEST_HASH_POLICY_INVALID")


def load_protocol_text() -> str:
    """Return protocol text only when the manifest-pinned bytes match."""

    raw = _read_artifact("protocol")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise Study3bProtocolError("STUDY3B_PROTOCOL_ENCODING_INVALID") from None


def load_generation_config() -> dict[str, Any]:
    """Load and validate the immutable Study 3b request/transport envelope."""

    load_protocol_text()
    raw = _read_artifact("generation_config")
    config = _parse_json(raw, "STUDY3B_GENERATION_CONFIG_INVALID")
    validate_generation_config(config)
    return config


def validate_generation_config(config: object) -> None:
    """Reject any change to generation, identity, order, or transport limits."""

    expected = {
        "schema": "neq.llm_staging_study3b_generation_config.v1",
        "study_id": STUDY_ID,
        "protocol_version": PROTOCOL_VERSION,
        "preparation_only": True,
        "dispatch_authorized": False,
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "provider": "openrouter",
        "model_id": MODEL_ID,
        "temperature": 1.0,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "max_tokens": 16384,
        "timeout_seconds": 720,
        "response_format": {"type": "json_object"},
        "stream": False,
        "tools": [],
        "tool_choice": "none",
        "provider_options": {"allow_fallbacks": False},
        "transport_constraints": {
            "retries": 0,
            "reruns": 0,
            "fallback": False,
            "availability_get": False,
            "redirects": False,
            "continuation": False,
        },
        "attempt_cap": {
            "identity": STUDY_ID,
            "total": 3,
            "per_scene": 1,
            "scene_order": list(SCENE_ORDER),
        },
        "cost_limit_usd": "0.05",
    }
    if not _same_json_value(config, expected):
        raise Study3bProtocolError("STUDY3B_GENERATION_CONFIG_DRIFT")


def _verify_source_provenance(manifest: dict[str, Any]) -> None:
    source = manifest["source_provenance"]
    for name, expected_path, expected_hash in (
        (
            "manifest",
            SOURCE_STUDY3_MANIFEST_RELATIVE,
            SOURCE_STUDY3_MANIFEST_SHA256,
        ),
        (
            "protocol",
            SOURCE_STUDY3_PROTOCOL_RELATIVE,
            SOURCE_STUDY3_PROTOCOL_SHA256,
        ),
    ):
        record = source[name]
        if record["path"] != expected_path or record["sha256"] != expected_hash:
            raise Study3bProtocolError("STUDY3B_SOURCE_PROVENANCE_INVALID")
        try:
            raw = _safe_project_read(expected_path)
        except (OSError, ValueError):
            raise Study3bProtocolError("STUDY3B_SOURCE_ARTIFACT_UNAVAILABLE") from None
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise Study3bProtocolError("STUDY3B_SOURCE_ARTIFACT_HASH_MISMATCH")


def _read_artifact(role: str) -> bytes:
    path_hash = _ARTIFACTS.get(role)
    if path_hash is None:
        raise Study3bProtocolError("STUDY3B_ARTIFACT_ROLE_INVALID")
    manifest = load_manifest()
    record = manifest["artifacts"][role]
    try:
        raw = _safe_project_read(record["path"])
    except (OSError, ValueError):
        raise Study3bProtocolError("STUDY3B_ARTIFACT_UNAVAILABLE") from None
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise Study3bProtocolError("STUDY3B_ARTIFACT_HASH_MISMATCH")
    return raw


def _parse_json(raw: bytes, error_code: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        raise Study3bProtocolError(error_code) from None


def _safe_project_read(relative_path: str) -> bytes:
    """Read a regular repository file without path traversal or symlinks."""

    try:
        return isolation._read_project_file(REPO_ROOT, relative_path)
    except ValueError:
        raise
    except isolation.BaselineScopeError:
        raise ValueError("STUDY3B_PATH_REJECTED") from None
    except OSError:
        raise ValueError("STUDY3B_ARTIFACT_UNAVAILABLE") from None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite value")


def _same_json_value(left: Any, right: Any) -> bool:
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(
            _same_json_value(left[key], right[key]) for key in right
        )
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


__all__ = [
    "GENERATION_CONFIG_SHA256",
    "MANIFEST_SHA256",
    "MODEL_ID",
    "PROTOCOL_VERSION",
    "SCENE_ORDER",
    "STUDY_ID",
    "Study3bProtocolError",
    "load_generation_config",
    "load_manifest",
    "load_protocol_text",
    "validate_generation_config",
    "validate_manifest",
]
