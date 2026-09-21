# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Semantic Adaptation Auditor
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider runner and fail-closed response contract for the final semantic
adaptation audit. The auditor receives only the bounded Python-owned failure
packet and returns a revised dossier or declarative staging guidance. It never
patches files, writes module state, or publishes a module.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from jsonschema import Draft7Validator
except Exception:  # pragma: no cover - dependency availability is environment-specific
    Draft7Validator = None  # type: ignore[assignment,misc]

try:
    from model_config import DM_MAIN_MODEL
except Exception:  # pragma: no cover - provider-free import fallback
    DM_MAIN_MODEL = "gpt-4.1-2025-04-14"

from utils.ai_client_factory import create_chat_client, get_chat_completion_params
from utils.toolkit_adaptation_artifacts import (
    FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_MECHANICAL,
    FAILURE_CLASS_PROVIDER,
    FAILURE_CLASS_PUBLICATION,
    FAILURE_CLASS_QUOTA,
    FAILURE_CLASS_RIGHTS,
    FAILURE_CLASS_SEMANTIC,
    FAILURE_CLASS_TIMEOUT,
    FAILURE_CLASS_UNKNOWN,
    VALID_FAILURE_CLASSES,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_READY,
    parse_adaptation_dossier,
)
from utils.toolkit_adaptation_failure_packet import (
    MAX_PACKET_SERIALIZED_CHARS,
    validate_adaptation_failure_packet,
    serialize_adaptation_failure_packet,
)
from utils.toolkit_adaptation_rebuild_directive import (
    validate_rebuild_directive_shape,
    validate_adaptation_rebuild_directive,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance


ADAPTATION_AUDITOR_CONTRACT_VERSION = "toolkit_adaptation_auditor.v1"
ADAPTATION_AUDITOR_RESPONSE_VERSION = ADAPTATION_AUDITOR_CONTRACT_VERSION
ADAPTATION_AUDITOR_SCHEMA_VERSION = ADAPTATION_AUDITOR_CONTRACT_VERSION
ADAPTATION_AUDITOR_TASK_ID = "toolkit_adaptation_semantic_auditor"
ADAPTATION_AUDITOR_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "toolkit"
    / "adaptation_semantic_auditor_prompt.txt"
)
ADAPTATION_AUDITOR_RESPONSE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "toolkit_adaptation_auditor_response_schema.json"
)
ADAPTATION_AUDITOR_DEFAULT_TIMEOUT_SECONDS = 120

AUDITOR_DECISION_REVISE = "revise"
AUDITOR_DECISION_REFUSE = "refuse"
AUDITOR_DECISION_FAILED = "failed"
VALID_AUDITOR_DECISIONS = (
    AUDITOR_DECISION_REVISE,
    AUDITOR_DECISION_REFUSE,
    AUDITOR_DECISION_FAILED,
)

AUDITOR_STATUS_SUCCESS = "success"
AUDITOR_STATUS_REFUSED = "refused"
AUDITOR_STATUS_FAILED = "failed"
AUDITOR_STATUS_INVALID_INPUT = "invalid_input"
AUDITOR_STATUS_INVALID_MODEL_RESPONSE = "invalid_model_response"
AUDITOR_STATUS_PROVIDER_FAILED = "provider_failed"
AUDITOR_STATUS_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
AUDITOR_STATUS_PROMPT_FAILED = "prompt_failed"

AUDITOR_RESULT_STATUS_VALID = "valid"
AUDITOR_RESULT_STATUS_INVALID = "invalid"

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_CODE_INVALID_PACKET = "invalid_failure_packet"
DIAGNOSTIC_CODE_PACKET_NOT_BLOCKED = "failure_packet_not_blocked"
DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED = "auditor_not_authorized"
DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
DIAGNOSTIC_CODE_MARKDOWN_FENCE = "markdown_fence_rejected"
DIAGNOSTIC_CODE_NON_ASCII = "non_ascii_response"
DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE = "response_too_large"
DIAGNOSTIC_CODE_UNEXPECTED_FIELD = "unexpected_field"
DIAGNOSTIC_CODE_MISSING_FIELD = "missing_field"
DIAGNOSTIC_CODE_UNSUPPORTED_DECISION = "unsupported_decision"
DIAGNOSTIC_CODE_METADATA_MISMATCH = "metadata_mismatch"
DIAGNOSTIC_CODE_EVIDENCE_MISMATCH = "gate_evidence_mismatch"
DIAGNOSTIC_CODE_DOSSIER_INVALID = "revised_dossier_invalid"
DIAGNOSTIC_CODE_DOSSIER_NOT_READY = "revised_dossier_not_ready"
DIAGNOSTIC_CODE_DIRECTIVE_INVALID = "rebuild_directive_invalid"
DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN = "forbidden_change_payload"
DIAGNOSTIC_CODE_UNSAFE_CONTENT = "unsafe_content"
DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE = "response_schema_unavailable"
DIAGNOSTIC_CODE_PROVIDER_FAILED = "provider_failed"
DIAGNOSTIC_CODE_PROVIDER_REFUSAL = "provider_refusal"
DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED = "param_resolution_failed"

MAX_AUDITOR_INPUT_CHARS = MAX_PACKET_SERIALIZED_CHARS + 128
MAX_AUDITOR_RESPONSE_CHARS = 64_000
MAX_REVISED_DOSSIER_CHARS = 48_000
MAX_REASON_CHARS = 800
MAX_FAILURE_MESSAGE_CHARS = 800
MAX_GUIDANCE_ITEMS = 8
MAX_GUIDANCE_CHARS = 400
MAX_EVIDENCE_REFS = 32
MAX_MODEL_METADATA_CHARS = 200

_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)"
    r"\s*[:=]\s*[^\s,;]+|\bBearer\s+[^\s,;]+|\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{7,}"
)
_RAW_PAYLOAD_RE = re.compile(
    r"(?i)\b(?:raw[_ -]?(?:source|prompt|response)|full[_ -]?(?:source|prompt)|"
    r"source[_ -]?(?:content|text)|provider[_ -]?payload|response[_ -]?content)\b"
)
_RUNTIME_TARGET_RE = re.compile(
    r"(?i)(?:world_registry\.json|campaign\.json|party_tracker\.json|"
    r"player_quests_[^\s,;]+|encounters(?:/|\\)|modules/[^\s,;]+)"
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "campaign",
        "command",
        "commands",
        "credential",
        "credentials",
        "file_patch",
        "file_patches",
        "full_prompt",
        "full_source",
        "module_dir",
        "operations",
        "ops",
        "output_directory",
        "patch",
        "patches",
        "password",
        "prompt",
        "raw_prompt",
        "raw_response",
        "raw_source",
        "registry",
        "secret",
        "source_content",
        "source_text",
        "target_path",
        "token",
        "world_registry",
    }
)
_MODEL_METADATA_KEYS = frozenset(
    {
        "provider",
        "model",
        "model_version",
        "request_id",
        "parameter_profile",
        "temperature",
        "reasoning_effort",
        "verbosity",
    }
)
_RESERVED_REQUEST_KEYS = frozenset({"messages", "response_format", "timeout", "stream"})
_SEMANTIC_FAILURE_CLASSES = frozenset({FAILURE_CLASS_MECHANICAL, FAILURE_CLASS_SEMANTIC})
_VALID_FAILURE_STATUSES = frozenset(
    {
        "blocked",
        "failed",
        "invalid",
        "provider_failed",
        "parameter_resolution_failed",
        "timeout",
        "quota",
        "refused",
    }
)


def _ascii_text(value: Any, limit: int) -> str:
    text = str(value).replace("\x00", " ")
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {
        "code": _ascii_text(code, 120),
        "message": _ascii_text(message, 240),
        "path": _ascii_text(path, 200),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def load_adaptation_auditor_schema() -> Dict[str, Any]:
    """Load the response schema without any provider or state side effect."""
    with ADAPTATION_AUDITOR_RESPONSE_SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("adaptation auditor response schema must be an object")
    return deepcopy(schema)


def _load_adaptation_auditor_prompt() -> str:
    text = ADAPTATION_AUDITOR_PROMPT_PATH.read_text(encoding="utf-8")
    if not text or not text.strip():
        raise ValueError("adaptation auditor prompt is empty")
    if not text.isascii():
        raise ValueError("adaptation auditor prompt is not ASCII")
    return text


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _packet_identity(packet: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, str]]]:
    diagnostics: List[Dict[str, str]] = []
    attempt = packet.get("attempt_metadata")
    if not isinstance(attempt, Mapping):
        return None, [], [_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "attempt_metadata is required")]

    required = ("attempt_id", "stage", "revision_number", "source_hash", "model_metadata")
    for key in required:
        if key not in attempt:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "attempt metadata is missing " + key, key))
    source_hash = attempt.get("source_hash")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "source hash is invalid", "source_hash"))
    attempt_id = attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "attempt id is invalid", "attempt_id"))
    stage = attempt.get("stage")
    if not isinstance(stage, str) or not _STAGE_RE.fullmatch(stage):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "stage is invalid", "stage"))
    revision = attempt.get("revision_number")
    if isinstance(revision, bool) or not isinstance(revision, int) or not 0 <= revision <= 100:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "revision number is invalid", "revision_number"))
    model_metadata = attempt.get("model_metadata")
    if not isinstance(model_metadata, Mapping) or not isinstance(model_metadata.get("model"), str):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "model metadata is invalid", "model_metadata"))

    top_level_matches = {
        "attempt_id": packet.get("attempt_id"),
        "stage": packet.get("stage"),
        "revision_number": packet.get("revision_number"),
        "source_hash": packet.get("source_hash"),
    }
    for key, value in top_level_matches.items():
        if value != attempt.get(key):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "top-level packet metadata does not match attempt metadata", key))

    refs: List[Dict[str, Any]] = []
    seen = set()
    for collection_name in ("gate_statuses", "gate_findings"):
        collection = packet.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            reference = item.get("evidence_ref")
            if not isinstance(reference, Mapping):
                continue
            normalized = deepcopy(dict(reference))
            identity = _json_text(normalized)
            if identity not in seen:
                refs.append(normalized)
                seen.add(identity)
    refs.sort(key=_json_text)
    metadata = {
        "attempt_id": attempt.get("attempt_id"),
        "stage": attempt.get("stage"),
        "revision_number": attempt.get("revision_number"),
        "source_hash": attempt.get("source_hash"),
        "model_metadata": deepcopy(dict(model_metadata)) if isinstance(model_metadata, Mapping) else {},
    }
    metadata["world_context_provenance"] = build_world_context_provenance(
        packet.get("world_context_provenance") or attempt
    )
    return metadata, refs, diagnostics


def _world_context_result_fields(source: Any) -> Dict[str, Any]:
    """Return scalar-only world provenance for an auditor result envelope."""
    provenance = build_world_context_provenance(source)
    return {
        "world_context_provenance": provenance,
        "world_context_status": provenance.get("context_status"),
        "world_context_version": provenance.get("context_version"),
        "world_context_hash": provenance.get("context_hash"),
        "context_hash": provenance.get("context_hash"),
        "world_seed_status": provenance.get("world_seed_status"),
        "world_seed_version": provenance.get("world_seed_version"),
        "world_seed_hash": provenance.get("world_seed_hash"),
    }


def _packet_authorization(packet: Any) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    if not isinstance(packet, Mapping):
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "failure packet must be an object")]
    validation = validate_adaptation_failure_packet(packet)
    if not validation.get("valid"):
        diagnostics = [
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_PACKET,
                str(item.get("message") or "failure packet validation failed"),
                str(item.get("path") or ""),
            )
            for item in list(validation.get("diagnostics") or [])[:12]
            if isinstance(item, Mapping)
        ]
        return None, diagnostics or [_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "failure packet validation failed")]
    if packet.get("packet_status") != "blocked":
        return None, [_diagnostic(DIAGNOSTIC_CODE_PACKET_NOT_BLOCKED, "semantic auditor requires a blocked failure packet")]

    classification = packet.get("failure_classification")
    if not isinstance(classification, Mapping):
        return None, [_diagnostic(DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED, "failure classification is required")]

    metadata, refs, metadata_diagnostics = _packet_identity(packet)
    if metadata_diagnostics or metadata is None:
        return None, metadata_diagnostics or [_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "packet identity is invalid")]
    authorization = {
        "packet": deepcopy(dict(packet)),
        "metadata": metadata,
        "gate_evidence_refs": refs,
        "classification": deepcopy(dict(classification)),
    }
    failure_class = classification.get("failure_class")
    revision_budget = classification.get("revision_budget")
    budget_allows_revision = isinstance(revision_budget, Mapping) and revision_budget.get("decision") == "eligible"
    if budget_allows_revision and revision_budget.get("remaining_before_failure") is not None:
        remaining = revision_budget.get("remaining_before_failure")
        budget_allows_revision = isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 0
    if budget_allows_revision and revision_budget.get("remaining_revisions") is not None:
        remaining = revision_budget.get("remaining_revisions")
        budget_allows_revision = isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 0
    if (
        classification.get("failure_group") != "content"
        or failure_class not in _SEMANTIC_FAILURE_CLASSES
        or classification.get("semantic_revision_eligible") is not True
        or not budget_allows_revision
    ):
        return authorization, [_diagnostic(DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED, "failure is not eligible for semantic adaptation revision")]
    return authorization, []


def build_adaptation_auditor_messages(
    failure_packet: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Build the bounded system/user request for an eligible failure packet."""
    authorization, diagnostics = _packet_authorization(failure_packet)
    if diagnostics or authorization is None:
        raise ValueError(_ascii_text(diagnostics[0].get("message") if diagnostics else "invalid failure packet", 240))
    serialized = serialize_adaptation_failure_packet(authorization["packet"])
    user_content = "ADAPTATION_FAILURE_PACKET:\n" + serialized
    if len(user_content) > MAX_AUDITOR_INPUT_CHARS:
        raise ValueError("failure packet exceeds the auditor input bound")
    return [
        {"role": "system", "content": _load_adaptation_auditor_prompt()},
        {"role": "user", "content": user_content},
    ]


def _schema_diagnostics(value: Mapping[str, Any]) -> List[Dict[str, str]]:
    if Draft7Validator is None:
        return []
    try:
        validator = Draft7Validator(load_adaptation_auditor_schema())
        errors = sorted(
            validator.iter_errors(value),
            key=lambda item: (tuple(str(part) for part in item.absolute_path), str(item.validator), str(item.message)),
        )
    except Exception:
        return [_diagnostic(DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE, "auditor response schema could not be evaluated")]
    result: List[Dict[str, str]] = []
    for error in errors[:24]:
        path = ".".join(str(part) for part in error.absolute_path)
        result.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, str(error.message), path))
    return result


def _validate_reference(value: Any, path: str) -> List[Dict[str, str]]:
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(value, Mapping):
        return [_diagnostic(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, "evidence reference must be an object", path)]
    allowed = {"path", "sha256", "role", "reference_only"}
    for key in value:
        if key not in allowed:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected evidence reference field", path + "." + str(key)))
    if value.get("reference_only") is not True:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, "evidence reference must be reference_only", path))
    raw_path = value.get("path")
    if raw_path is not None:
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or raw_path.startswith("/")
            or _DRIVE_PATH_RE.match(raw_path)
            or "\\" in raw_path
            or any(part == ".." for part in raw_path.split("/"))
            or len(raw_path) > 240
        ):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "evidence path is not project-relative", path + ".path"))
    raw_hash = value.get("sha256")
    if raw_hash is not None and (not isinstance(raw_hash, str) or not _SHA256_RE.fullmatch(raw_hash)):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "evidence hash is invalid", path + ".sha256"))
    if value.get("role") is not None and (
        not isinstance(value.get("role"), str)
        or not value.get("role")
        or len(value.get("role", "")) > 80
    ):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "evidence role is invalid", path + ".role"))
    if raw_path in (None, "") and raw_hash in (None, ""):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, "evidence reference is empty", path))
    return diagnostics


def _scan_unsafe_content(value: Any, path: str = "", *, allow_reference_path: bool = False) -> List[Dict[str, str]]:
    diagnostics: List[Dict[str, str]] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            lowered = key.lower()
            child_path = f"{path}.{key}" if path else key
            if lowered in _FORBIDDEN_KEYS:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "forbidden response field", child_path))
            if lowered in {"path", "target", "target_path", "module_dir", "output_directory"} and not (
                allow_reference_path or child_path.startswith("gate_evidence_refs[")
            ):
                if lowered != "target" or path != "rebuild_directive":
                    diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "arbitrary runtime target is not allowed", child_path))
            diagnostics.extend(_scan_unsafe_content(child, child_path, allow_reference_path=child_path.startswith("gate_evidence_refs[")))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            diagnostics.extend(_scan_unsafe_content(child, f"{path}[{index}]", allow_reference_path=allow_reference_path))
    elif isinstance(value, str):
        if not value.isascii():
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_NON_ASCII, "response text must be ASCII-only", path))
        if _SECRET_RE.search(value) or _RAW_PAYLOAD_RE.search(value):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "credentials or raw provider/source content are not allowed", path))
        if not allow_reference_path and (
            value.startswith("/")
            or _DRIVE_PATH_RE.match(value)
            or value.startswith("../")
            or "\\" in value
            or _RUNTIME_TARGET_RE.search(value)
        ):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "runtime paths are not allowed in auditor content", path))
    return diagnostics


def _validate_model_metadata(value: Any, expected: Mapping[str, Any], path: str) -> List[Dict[str, str]]:
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(value, Mapping):
        return [_diagnostic(DIAGNOSTIC_CODE_MISSING_FIELD, "model_metadata must be an object", path)]
    if set(value) - _MODEL_METADATA_KEYS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "model_metadata contains an unknown field", path))
    if value.get("model") != expected.get("model"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "model metadata must be preserved exactly", path + ".model"))
    if _json_text(dict(value)) != _json_text(dict(expected)):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "model metadata must match the failure packet", path))
    for key, item in value.items():
        if isinstance(item, str) and len(item) > MAX_MODEL_METADATA_CHARS:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "model metadata text is too long", path + "." + str(key)))
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "model metadata must contain bounded scalars", path + "." + str(key)))
        if isinstance(item, float) and not math.isfinite(item):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "model metadata contains a non-finite number", path + "." + str(key)))
    return diagnostics


def _validate_rebuild_directive(value: Any) -> List[Dict[str, str]]:
    # The adaptation directive has its own bounded contract.  Keep this
    # response-level check shape-only; filesystem resolution is performed by
    # ``validate_adaptation_rebuild_directive`` with a Python-owned staging
    # target before any later build/write task.
    diagnostics = validate_rebuild_directive_shape(value, require_identity=False)
    return [
        _diagnostic(
            item.get("code", DIAGNOSTIC_CODE_DIRECTIVE_INVALID),
            item.get("message", "rebuild directive is invalid"),
            item.get("path", "rebuild_directive"),
        )
        for item in diagnostics
    ]


def _validate_failure(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, Mapping):
        return [_diagnostic(DIAGNOSTIC_CODE_MISSING_FIELD, "failed response requires a failure object", "failure")]
    allowed = {"class", "status", "code", "message"}
    diagnostics: List[Dict[str, str]] = []
    if set(value) - allowed:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "failure contains an unknown field", "failure"))
    if value.get("class") not in VALID_FAILURE_CLASSES:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "failure class is not allowlisted", "failure.class"))
    if value.get("status") not in _VALID_FAILURE_STATUSES:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "failure status is not allowlisted", "failure.status"))
    if not isinstance(value.get("code"), str) or not _CODE_RE.fullmatch(value.get("code", "")):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "failure code is invalid", "failure.code"))
    if not isinstance(value.get("message"), str) or not 1 <= len(value.get("message", "")) <= MAX_FAILURE_MESSAGE_CHARS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "failure message is invalid or too large", "failure.message"))
    return diagnostics


def _invalid_parse_result(
    metadata: Optional[Mapping[str, Any]],
    refs: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    result = {
        "valid": False,
        "status": AUDITOR_RESULT_STATUS_INVALID,
        "decision": AUDITOR_DECISION_FAILED,
        "outcome": AUDITOR_DECISION_FAILED,
        "ok": False,
        "attempt_id": (metadata or {}).get("attempt_id"),
        "stage": (metadata or {}).get("stage"),
        "revision_number": (metadata or {}).get("revision_number"),
        "source_hash": (metadata or {}).get("source_hash"),
        "model_metadata": deepcopy((metadata or {}).get("model_metadata") or {}),
        "gate_evidence_refs": deepcopy(list(refs)),
        "response": None,
        "diagnostics": [dict(item) for item in list(diagnostics)[:32]],
    }
    result.update(_world_context_result_fields(metadata or {}))
    return result


def _valid_parse_result(
    response: Mapping[str, Any],
    metadata: Mapping[str, Any],
    refs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    decision = str(response.get("decision"))
    result = {
        "valid": True,
        "status": AUDITOR_RESULT_STATUS_VALID,
        "decision": decision,
        "outcome": decision,
        "ok": decision == AUDITOR_DECISION_REVISE,
        "attempt_id": metadata.get("attempt_id"),
        "stage": metadata.get("stage"),
        "revision_number": metadata.get("revision_number"),
        "source_hash": metadata.get("source_hash"),
        "model_metadata": deepcopy(metadata.get("model_metadata") or {}),
        "gate_evidence_refs": deepcopy(list(refs)),
        "response": deepcopy(dict(response)),
        "diagnostics": [],
    }
    result.update(_world_context_result_fields(metadata))
    return result


def parse_adaptation_auditor_response(
    raw_response: Any,
    failure_packet: Mapping[str, Any],
    *,
    staging_target: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Parse one raw auditor response and reject unsafe revisions fail closed.

    ``staging_target`` is optional for compatibility with the task-5.2
    response-only parser.  When supplied, a rebuild directive is resolved
    through the strict adaptation staging validator before a later caller can
    start a build.  The parser itself never writes or cleans up a target.
    """
    authorization, packet_diagnostics = _packet_authorization(failure_packet)
    if packet_diagnostics or authorization is None:
        return _invalid_parse_result(None, [], packet_diagnostics)
    metadata = authorization["metadata"]
    expected_refs = authorization["gate_evidence_refs"]

    if isinstance(raw_response, bytes):
        try:
            raw_response = raw_response.decode("utf-8")
        except UnicodeDecodeError:
            return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "response is not valid UTF-8")])
    if not isinstance(raw_response, str):
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "response must be raw JSON text")])
    text = raw_response.strip()
    if len(text) > MAX_AUDITOR_RESPONSE_CHARS:
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE, "response exceeds its size bound")])
    if not text.isascii():
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_NON_ASCII, "response must contain ASCII characters only")])
    if "```" in text:
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_MARKDOWN_FENCE, "markdown fences are not accepted")])
    try:
        parsed = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-standard JSON constant: " + value)))
    except Exception:
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "response is not valid JSON")])
    if not isinstance(parsed, dict):
        return _invalid_parse_result(metadata, expected_refs, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "top-level JSON value must be an object")])

    diagnostics: List[Dict[str, str]] = []
    safe_rebuild_plan: Optional[Dict[str, Any]] = None
    allowed = {
        "version",
        "decision",
        "reason",
        "attempt_id",
        "stage",
        "revision_number",
        "source_hash",
        "model_metadata",
        "gate_evidence_refs",
        "revised_dossier",
        "rebuild_directive",
        "failure",
    }
    for key in sorted(set(parsed) - allowed):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected auditor response field", key))
    for key in ("version", "decision", "reason", "attempt_id", "stage", "revision_number", "source_hash", "model_metadata", "gate_evidence_refs"):
        if key not in parsed:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_MISSING_FIELD, "required auditor response field is missing", key))
    if parsed.get("version") != ADAPTATION_AUDITOR_CONTRACT_VERSION:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "unsupported auditor response version", "version"))
    if parsed.get("decision") not in VALID_AUDITOR_DECISIONS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSUPPORTED_DECISION, "decision must be revise, refuse, or failed", "decision"))
    if not isinstance(parsed.get("reason"), str) or not 1 <= len(parsed.get("reason", "")) <= MAX_REASON_CHARS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "reason is invalid or too large", "reason"))
    if parsed.get("attempt_id") != metadata.get("attempt_id"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "attempt_id must be preserved", "attempt_id"))
    if parsed.get("stage") != metadata.get("stage"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "stage must be preserved", "stage"))
    if parsed.get("revision_number") != metadata.get("revision_number"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "revision_number must be preserved", "revision_number"))
    if parsed.get("source_hash") != metadata.get("source_hash"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "source_hash must be preserved", "source_hash"))
    diagnostics.extend(_validate_model_metadata(parsed.get("model_metadata"), metadata.get("model_metadata") or {}, "model_metadata"))

    response_refs = parsed.get("gate_evidence_refs")
    if not isinstance(response_refs, list) or len(response_refs) > MAX_EVIDENCE_REFS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, "gate_evidence_refs must be a bounded list", "gate_evidence_refs"))
    else:
        for index, reference in enumerate(response_refs):
            diagnostics.extend(_validate_reference(reference, f"gate_evidence_refs[{index}]"))
        expected_serialized = sorted(_json_text(item) for item in expected_refs)
        actual_serialized = sorted(_json_text(item) for item in response_refs)
        if expected_serialized != actual_serialized:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, "gate evidence references must be echoed exactly", "gate_evidence_refs"))

    diagnostics.extend(_schema_diagnostics(parsed))
    diagnostics.extend(_scan_unsafe_content(parsed))

    decision = parsed.get("decision")
    if decision == AUDITOR_DECISION_REVISE:
        has_dossier = "revised_dossier" in parsed
        has_directive = "rebuild_directive" in parsed
        if has_dossier == has_directive:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_INVALID, "revise requires exactly one revised_dossier or rebuild_directive", "decision"))
        if "failure" in parsed:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "revise cannot include a failure payload", "failure"))
        if has_dossier:
            dossier = parsed.get("revised_dossier")
            try:
                dossier_size = len(_json_text(dossier))
            except Exception:
                dossier_size = MAX_REVISED_DOSSIER_CHARS + 1
            if dossier_size > MAX_REVISED_DOSSIER_CHARS:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE, "revised dossier exceeds its size bound", "revised_dossier"))
            dossier_result = parse_adaptation_dossier(dossier)
            if not dossier_result.get("valid"):
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_INVALID, "revised dossier does not satisfy the dossier schema", "revised_dossier"))
            elif not dossier_result.get("build_ready") or dossier_result.get("dossier", {}).get("status") != ADAPTATION_DOSSIER_STATUS_READY:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_NOT_READY, "revised dossier must be ready for a build", "revised_dossier.status"))
            else:
                normalized_dossier = dossier_result.get("dossier") or {}
                if normalized_dossier.get("source_hash") != metadata.get("source_hash"):
                    diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "revised dossier source_hash must match the packet", "revised_dossier.source_hash"))
                expected_attempt = failure_packet.get("attempt_metadata") or {}
                for key in ("source_title", "source_profile", "rights_class", "rights_basis", "rights_review_required", "rights_review_status", "adaptation_mode"):
                    if key in expected_attempt and normalized_dossier.get(key) != expected_attempt.get(key):
                        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_METADATA_MISMATCH, "revised dossier changed Python-owned provenance", "revised_dossier." + key))
        if has_directive:
            diagnostics.extend(_validate_rebuild_directive(parsed.get("rebuild_directive")))
            if staging_target is not None:
                safe_result = validate_adaptation_rebuild_directive(
                    parsed.get("rebuild_directive"),
                    failure_packet=failure_packet,
                    staging_target=staging_target,
                    repo_root=repo_root,
                )
                diagnostics.extend(
                    _diagnostic(
                        item.get("code", DIAGNOSTIC_CODE_DIRECTIVE_INVALID),
                        item.get("message", "rebuild directive is unsafe"),
                        item.get("path", "rebuild_directive"),
                    )
                    for item in safe_result.get("diagnostics", [])
                )
                if safe_result.get("valid"):
                    safe_rebuild_plan = safe_result.get("plan")
    elif decision == AUDITOR_DECISION_REFUSE:
        for key in ("revised_dossier", "rebuild_directive", "failure"):
            if key in parsed:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "refuse cannot include an executable change payload", key))
    elif decision == AUDITOR_DECISION_FAILED:
        if "revised_dossier" in parsed or "rebuild_directive" in parsed:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, "failed cannot include an executable change payload", "response"))
        diagnostics.extend(_validate_failure(parsed.get("failure")))

    if diagnostics:
        return _invalid_parse_result(metadata, expected_refs, diagnostics)
    result = _valid_parse_result(parsed, metadata, expected_refs)
    if safe_rebuild_plan is not None:
        result["rebuild_plan"] = deepcopy(safe_rebuild_plan)
    return result


def _extract_response_parts(response: Any) -> Tuple[Optional[str], bool, Dict[str, str]]:
    metadata: Dict[str, str] = {}
    try:
        model = getattr(response, "model", None)
        if isinstance(model, str) and model.strip():
            metadata["model"] = _ascii_text(model.strip(), 160)
        response_id = getattr(response, "id", None)
        if isinstance(response_id, str) and response_id.strip():
            metadata["request_id"] = _ascii_text(response_id.strip(), 200)
        choices = getattr(response, "choices", None)
        if not choices:
            return None, False, metadata
        message = getattr(choices[0], "message", None)
        refusal = getattr(message, "refusal", None)
        finish_reason = getattr(choices[0], "finish_reason", None)
        if refusal or finish_reason in {"refusal", "content_filter"}:
            return None, True, metadata
        content = getattr(message, "content", None)
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if not isinstance(content, str) or not content.strip():
            return None, False, metadata
        return content, False, metadata
    except Exception:
        return None, False, metadata


def _safe_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in params.items():
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_KEYS or lowered in {"extra_body", "api_key"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str):
                safe[str(key)] = _ascii_text(value, 200)
            elif isinstance(value, float) and not math.isfinite(value):
                continue
            else:
                safe[str(key)] = value
    return safe


def _provider_failure_class(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return FAILURE_CLASS_TIMEOUT
    if any(token in text for token in ("quota", "rate limit", "429", "billing", "insufficient_quota")):
        return FAILURE_CLASS_QUOTA
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return FAILURE_CLASS_DEPENDENCY
    if any(token in text for token in ("file", "path", "permission", "no such")):
        return FAILURE_CLASS_FILE
    return FAILURE_CLASS_PROVIDER


def _base_result(
    authorization: Mapping[str, Any],
    *,
    status: str,
    decision: str,
    diagnostics: Optional[Sequence[Mapping[str, Any]]] = None,
    response: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = authorization.get("metadata") or {}
    refs = authorization.get("gate_evidence_refs") or []
    result = {
        "status": status,
        "outcome": decision,
        "decision": decision,
        "ok": bool(status == AUDITOR_STATUS_SUCCESS and decision == AUDITOR_DECISION_REVISE),
        "attempt_id": metadata.get("attempt_id"),
        "stage": metadata.get("stage"),
        "revision_number": metadata.get("revision_number"),
        "source_hash": metadata.get("source_hash"),
        "model_metadata": deepcopy(metadata.get("model_metadata") or {}),
        "gate_evidence_refs": deepcopy(list(refs)),
        "response": deepcopy(dict(response)) if isinstance(response, Mapping) else None,
        "diagnostics": [dict(item) for item in list(diagnostics or [])[:32]],
    }
    result.update(_world_context_result_fields(authorization.get("packet") or metadata))
    return result


def _failure_payload(authorization: Mapping[str, Any], failure_class: str, status: str, code: str, message: str) -> Dict[str, Any]:
    metadata = authorization["metadata"]
    return {
        "version": ADAPTATION_AUDITOR_CONTRACT_VERSION,
        "decision": AUDITOR_DECISION_FAILED,
        "reason": _ascii_text(message, MAX_REASON_CHARS),
        "attempt_id": metadata["attempt_id"],
        "stage": metadata["stage"],
        "revision_number": metadata["revision_number"],
        "source_hash": metadata["source_hash"],
        "model_metadata": deepcopy(metadata["model_metadata"]),
        "gate_evidence_refs": deepcopy(authorization["gate_evidence_refs"]),
        "failure": {
            "class": failure_class if failure_class in VALID_FAILURE_CLASSES else FAILURE_CLASS_UNKNOWN,
            "status": status,
            "code": code if _CODE_RE.fullmatch(code) else "auditor_failed",
            "message": _ascii_text(message, MAX_FAILURE_MESSAGE_CHARS),
        },
    }


def _refusal_payload(authorization: Mapping[str, Any], reason: str) -> Dict[str, Any]:
    metadata = authorization["metadata"]
    return {
        "version": ADAPTATION_AUDITOR_CONTRACT_VERSION,
        "decision": AUDITOR_DECISION_REFUSE,
        "reason": _ascii_text(reason, MAX_REASON_CHARS),
        "attempt_id": metadata["attempt_id"],
        "stage": metadata["stage"],
        "revision_number": metadata["revision_number"],
        "source_hash": metadata["source_hash"],
        "model_metadata": deepcopy(metadata["model_metadata"]),
        "gate_evidence_refs": deepcopy(authorization["gate_evidence_refs"]),
    }


def run_llm_adaptation_auditor(
    failure_packet: Mapping[str, Any],
    *,
    client: Optional[Any] = None,
    model: Optional[str] = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = ADAPTATION_AUDITOR_DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Run the final auditor through injectable provider seams.

    Every terminal path exposes one of the three auditor decisions. Provider,
    parameter, and parser failures are represented as the safe ``failed``
    decision and never invoke a semantic retry themselves.
    """
    authorization, diagnostics = _packet_authorization(failure_packet)
    if diagnostics or authorization is None:
        if authorization is not None and any(
            item.get("code") == DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED
            for item in diagnostics
        ):
            response = _refusal_payload(
                authorization,
                "Python did not authorize semantic adaptation revision for this failure.",
            )
            result = _base_result(
                authorization,
                status=AUDITOR_STATUS_REFUSED,
                decision=AUDITOR_DECISION_REFUSE,
                response=response,
            )
            result["diagnostics"] = [dict(item) for item in diagnostics[:32]]
            return result
        fallback = {
            "status": AUDITOR_STATUS_INVALID_INPUT,
            "outcome": AUDITOR_DECISION_FAILED,
            "decision": AUDITOR_DECISION_FAILED,
            "ok": False,
            "response": None,
            "diagnostics": [dict(item) for item in diagnostics[:32]],
        }
        return fallback

    try:
        messages = build_adaptation_auditor_messages(authorization["packet"])
    except Exception:
        response = _failure_payload(authorization, FAILURE_CLASS_FILE, "failed", "auditor_prompt_failed", "auditor prompt or packet serialization failed")
        return _base_result(authorization, status=AUDITOR_STATUS_PROMPT_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_INVALID_PACKET, "auditor prompt or packet serialization failed")])

    requested_model = model if model is not None else DM_MAIN_MODEL
    if not isinstance(requested_model, str) or not requested_model.strip():
        response = _failure_payload(authorization, FAILURE_CLASS_DEPENDENCY, "invalid", "invalid_model", "auditor model resolution failed")
        return _base_result(authorization, status=AUDITOR_STATUS_PARAM_RESOLUTION_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED, "auditor model must be a non-empty string")])
    requested_model = requested_model.strip()
    resolver = parameter_resolver or get_chat_completion_params
    try:
        params = resolver(ADAPTATION_AUDITOR_TASK_ID, requested_model)
        if not isinstance(params, Mapping):
            raise TypeError("parameter resolver must return an object")
        params = dict(params)
        if not isinstance(params.get("model"), str) or not params.get("model"):
            raise ValueError("resolved parameters must include a model")
        if _RESERVED_REQUEST_KEYS.intersection(params):
            raise ValueError("resolved parameters contain reserved request keys")
        if any(not isinstance(key, str) for key in params):
            raise ValueError("resolved parameters contain a non-string key")
    except Exception:
        response = _failure_payload(authorization, FAILURE_CLASS_DEPENDENCY, "parameter_resolution_failed", "param_resolution_failed", "auditor chat parameter resolution failed")
        return _base_result(authorization, status=AUDITOR_STATUS_PARAM_RESOLUTION_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED, "auditor chat parameter resolution failed")])

    resolved_model = str(params["model"])
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
    ):
        response = _failure_payload(authorization, FAILURE_CLASS_DEPENDENCY, "invalid", "invalid_timeout", "auditor timeout parameter is invalid")
        return _base_result(authorization, status=AUDITOR_STATUS_PARAM_RESOLUTION_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED, "auditor timeout must be positive")])

    client_was_injected = client is not None
    if client is None:
        try:
            client = create_chat_client()
        except Exception as exc:
            failure_class = _provider_failure_class(exc)
            response = _failure_payload(authorization, failure_class, "provider_failed", "provider_client_failed", "auditor provider client initialization failed")
            return _base_result(authorization, status=AUDITOR_STATUS_PROVIDER_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PROVIDER_FAILED, "auditor provider client initialization failed")])

    request_kwargs: Dict[str, Any] = dict(params)
    request_kwargs.update({
        "messages": messages,
        "response_format": {"type": "json_object"},
    })
    if timeout_seconds is not None:
        request_kwargs["timeout"] = timeout_seconds
    try:
        provider_response = client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        failure_class = _provider_failure_class(exc)
        response = _failure_payload(authorization, failure_class, "provider_failed", "provider_call_failed", "auditor provider call failed")
        result = _base_result(authorization, status=AUDITOR_STATUS_PROVIDER_FAILED, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PROVIDER_FAILED, "auditor provider call failed")])
        result["params_used"] = _safe_params(params)
        return result

    raw_content, provider_refusal, response_metadata = _extract_response_parts(provider_response)
    if provider_refusal:
        response = _refusal_payload(authorization, "Provider refused the semantic audit request.")
        result = _base_result(authorization, status=AUDITOR_STATUS_REFUSED, decision=AUDITOR_DECISION_REFUSE, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_PROVIDER_REFUSAL, "provider returned an explicit refusal")])
    elif raw_content is None:
        response = _failure_payload(authorization, FAILURE_CLASS_PROVIDER, "failed", "invalid_model_response", "auditor provider returned no JSON content")
        result = _base_result(authorization, status=AUDITOR_STATUS_INVALID_MODEL_RESPONSE, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=[_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "auditor provider returned no JSON content")])
    else:
        parsed = parse_adaptation_auditor_response(raw_content, failure_packet)
        if not parsed.get("valid"):
            response = _failure_payload(authorization, FAILURE_CLASS_PROVIDER, "invalid", "invalid_auditor_response", "auditor response failed the Python safety contract")
            result = _base_result(authorization, status=AUDITOR_STATUS_INVALID_MODEL_RESPONSE, decision=AUDITOR_DECISION_FAILED, response=response, diagnostics=parsed.get("diagnostics"))
        else:
            decision = parsed["decision"]
            status = AUDITOR_STATUS_SUCCESS if decision == AUDITOR_DECISION_REVISE else AUDITOR_STATUS_REFUSED if decision == AUDITOR_DECISION_REFUSE else AUDITOR_STATUS_FAILED
            result = _base_result(authorization, status=status, decision=decision, response=parsed.get("response"), diagnostics=parsed.get("diagnostics"))
    result["params_used"] = _safe_params(params)
    result["provider"] = "injected" if client_was_injected else "configured"
    result["model"] = response_metadata.get("model", resolved_model)
    result["response_metadata"] = response_metadata
    result["request"] = {
        "task_id": ADAPTATION_AUDITOR_TASK_ID,
        "timeout_seconds": timeout_seconds,
        "response_format": "json_object",
        "parameter_keys": sorted(_safe_params(params).keys()),
    }
    return result


run_adaptation_auditor = run_llm_adaptation_auditor
parse_adaptation_auditor_response = parse_adaptation_auditor_response


__all__ = [
    "ADAPTATION_AUDITOR_CONTRACT_VERSION",
    "ADAPTATION_AUDITOR_DEFAULT_TIMEOUT_SECONDS",
    "ADAPTATION_AUDITOR_PROMPT_PATH",
    "ADAPTATION_AUDITOR_RESPONSE_SCHEMA_PATH",
    "ADAPTATION_AUDITOR_RESPONSE_VERSION",
    "ADAPTATION_AUDITOR_SCHEMA_VERSION",
    "ADAPTATION_AUDITOR_TASK_ID",
    "AUDITOR_DECISION_FAILED",
    "AUDITOR_DECISION_REFUSE",
    "AUDITOR_DECISION_REVISE",
    "AUDITOR_RESULT_STATUS_INVALID",
    "AUDITOR_RESULT_STATUS_VALID",
    "AUDITOR_STATUS_FAILED",
    "AUDITOR_STATUS_INVALID_INPUT",
    "AUDITOR_STATUS_INVALID_MODEL_RESPONSE",
    "AUDITOR_STATUS_PARAM_RESOLUTION_FAILED",
    "AUDITOR_STATUS_PROMPT_FAILED",
    "AUDITOR_STATUS_PROVIDER_FAILED",
    "AUDITOR_STATUS_REFUSED",
    "AUDITOR_STATUS_SUCCESS",
    "DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED",
    "DIAGNOSTIC_CODE_DOSSIER_INVALID",
    "DIAGNOSTIC_CODE_EVIDENCE_MISMATCH",
    "DIAGNOSTIC_CODE_INVALID_JSON",
    "DIAGNOSTIC_CODE_MARKDOWN_FENCE",
    "DIAGNOSTIC_CODE_METADATA_MISMATCH",
    "DIAGNOSTIC_CODE_PACKET_NOT_BLOCKED",
    "DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED",
    "DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN",
    "DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE",
    "DIAGNOSTIC_CODE_UNSUPPORTED_DECISION",
    "VALID_AUDITOR_DECISIONS",
    "build_adaptation_auditor_messages",
    "load_adaptation_auditor_schema",
    "parse_adaptation_auditor_response",
    "run_adaptation_auditor",
    "run_llm_adaptation_auditor",
]
