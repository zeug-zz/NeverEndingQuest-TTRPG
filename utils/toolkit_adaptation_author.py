# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit LLM Adaptation Author
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider runner and fail-closed response parser for the adaptation dossier
handoff. This module calls only the repository chat-client factory, keeps the
author prompt on disk as the single prompt contract, and never writes files,
module state, registry state, or campaign state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from model_config import DM_MAIN_MODEL
except Exception:  # pragma: no cover - defensive import for provider-free use
    DM_MAIN_MODEL = "gpt-4.1-2025-04-14"

from utils.ai_client_factory import create_chat_client, get_chat_completion_params
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_FAILED,
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    ADAPTATION_DOSSIER_VERSION,
    DIAGNOSTIC_CODE_INVALID_JSON,
    RIGHTS_CLASS_RESTRICTED,
    VALID_RIGHTS_CLASSES,
    VALID_SOURCE_PROFILES,
    load_adaptation_dossier_schema,
    parse_adaptation_dossier,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance


ADAPTATION_AUTHOR_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "toolkit"
    / "adaptation_author_prompt.txt"
)
ADAPTATION_AUTHOR_PROMPT_NAME = "adaptation_author_prompt.txt"
ADAPTATION_AUTHOR_TASK_ID = "toolkit_adaptation_author"
ADAPTATION_AUTHOR_DEFAULT_TIMEOUT_SECONDS = 120

# The prompt and dossier schema already bound individual creative fields. The
# runner adds request/response caps so a provider cannot turn one attempt into
# an unbounded prompt or diagnostic payload.
MAX_AUTHOR_INPUT_CHARS = 24000
MAX_AUTHOR_INPUT_TEXT_CHARS = 1200
MAX_AUTHOR_RESPONSE_CHARS = 200000
MAX_DIAGNOSTIC_CHARS = 240
MAX_ATTEMPT_ID_CHARS = 64

# Strict GPT-family structured-output contract. The author request defaults to
# the OpenAI-compatible ``json_schema`` response format using a deterministic
# strict derivation of the repository dossier schema. The ``json_object``
# fallback is narrowly documented for routed third-party provider profiles
# (``openrouter``) where schema-strict response_format support is not
# guaranteed across routed model families. The Python dossier parser remains
# the final authority under either contract; provider schema compliance is
# never build or publication success.
ADAPTATION_AUTHOR_RESPONSE_FORMAT_VERSION = "toolkit_adaptation_author_response_format.v1"
ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME = "toolkit_adaptation_dossier"
ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT = "json_schema"
ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY = "json_object"
MAX_RESPONSE_FORMAT_SCHEMA_CHARS = 60000
_STRICT_RESPONSE_FORMAT_PROVIDERS = frozenset({"openai", "injected"})

RUNNER_STATUS_SUCCESS = "success"
RUNNER_STATUS_INVALID_MODEL_RESPONSE = "invalid_model_response"
RUNNER_STATUS_REFUSED = "refused"
RUNNER_STATUS_PROVIDER_FAILED = "provider_failed"
RUNNER_STATUS_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
RUNNER_STATUS_INVALID_INPUT = "invalid_input"
RUNNER_STATUS_PROMPT_FAILED = "prompt_failed"

OUTCOME_VALID = "valid"
OUTCOME_INVALID_MODEL_RESPONSE = "invalid_model_response"
OUTCOME_EXPLICIT_REFUSAL = "explicit_refusal"
OUTCOME_PROVIDER_FAILURE = "provider_failure"
OUTCOME_PARAMETER_RESOLUTION_FAILURE = "parameter_resolution_failure"
OUTCOME_INVALID_INPUT = "invalid_input"
OUTCOME_PROMPT_FAILURE = "prompt_failure"

FAILURE_CLASS_NONE = "none"
FAILURE_CLASS_MODEL_RESPONSE = "model_response"
FAILURE_CLASS_REFUSAL = "refusal"
FAILURE_CLASS_PARAMETER_RESOLUTION = "parameter_resolution"
FAILURE_CLASS_PROVIDER = "provider"
FAILURE_CLASS_TIMEOUT = "timeout"
FAILURE_CLASS_QUOTA = "quota"
FAILURE_CLASS_DEPENDENCY = "dependency"
FAILURE_CLASS_FILE = "file"

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_CODE_INVALID_INPUT = "invalid_input"
DIAGNOSTIC_CODE_PROMPT_FAILED = "prompt_failed"
DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
DIAGNOSTIC_CODE_MARKDOWN_FENCE = "markdown_fence_rejected"
DIAGNOSTIC_CODE_NON_ASCII_RESPONSE = "non_ascii_response"
DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE = "response_too_large"
DIAGNOSTIC_CODE_INVALID_PROVENANCE = "invalid_provenance"
DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY = "dossier_not_build_ready"
DIAGNOSTIC_CODE_DOSSIER_REFUSED = "dossier_refused"
DIAGNOSTIC_CODE_DOSSIER_FAILED = "dossier_failed"
DIAGNOSTIC_CODE_PROVIDER_REFUSAL = "provider_refusal"
DIAGNOSTIC_CODE_PROVIDER_FAILED = "provider_failed"
DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
DIAGNOSTIC_CODE_INVALID_PARAMS = "invalid_params"

# Safe reason categories for author/runtime diagnostics (task 3.2). These are
# stable, allowlisted classification labels that distinguish the failure
# families without ever exposing raw provider/refusal text, credentials, full
# prompts, or arbitrary response bodies. ``safe_class``/``reason_code`` are
# additive fields on result payloads; existing ``status``/``outcome``/
# ``failure_class`` keys and aliases remain unchanged for callers and tests.
REASON_CATEGORY_NONE = "none"
REASON_CATEGORY_API_REFUSAL = "api_refusal"
REASON_CATEGORY_AUTHOR_POLICY_REFUSAL = "author_policy_refusal"
REASON_CATEGORY_QUOTA = "quota"
REASON_CATEGORY_TIMEOUT = "timeout"
REASON_CATEGORY_DEPENDENCY = "dependency"
REASON_CATEGORY_PARAMETER_RESOLUTION = "parameter_resolution"
REASON_CATEGORY_INVALID_MODEL_RESPONSE = "invalid_model_response"
REASON_CATEGORY_RIGHTS_OR_PROVENANCE = "rights_or_provenance"
REASON_CATEGORY_DOSSIER_VALIDATION = "dossier_validation"
REASON_CATEGORY_PROVIDER_INFRASTRUCTURE = "provider_infrastructure"
REASON_CATEGORY_INVALID_INPUT = "invalid_input"
REASON_CATEGORY_PROMPT_FAILURE = "prompt_failure"
REASON_CATEGORY_FILE_IO = "file_io"
VALID_REASON_CATEGORIES = (
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_API_REFUSAL,
    REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
    REASON_CATEGORY_QUOTA,
    REASON_CATEGORY_TIMEOUT,
    REASON_CATEGORY_DEPENDENCY,
    REASON_CATEGORY_PARAMETER_RESOLUTION,
    REASON_CATEGORY_INVALID_MODEL_RESPONSE,
    REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
    REASON_CATEGORY_DOSSIER_VALIDATION,
    REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
    REASON_CATEGORY_INVALID_INPUT,
    REASON_CATEGORY_PROMPT_FAILURE,
    REASON_CATEGORY_FILE_IO,
)

REASON_CODE_NONE = "none"
REASON_CODE_PROVIDER_API_REFUSAL = "provider_api_refusal"
REASON_CODE_DOSSIER_REFUSED = "dossier_refused"
REASON_CODE_QUOTA_EXCEEDED = "quota_exceeded"
REASON_CODE_REQUEST_TIMEOUT = "request_timeout"
REASON_CODE_DEPENDENCY_IMPORT_FAILED = "dependency_import_failed"
REASON_CODE_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
REASON_CODE_INVALID_PARAMS = "invalid_params"
REASON_CODE_RESPONSE_FORMAT_FAILED = "response_format_failed"
REASON_CODE_INVALID_MODEL_RESPONSE = "invalid_model_response"
REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH = "rights_or_provenance_mismatch"
REASON_CODE_DOSSIER_VALIDATION_FAILED = "dossier_validation_failed"
REASON_CODE_DOSSIER_NOT_BUILD_READY = "dossier_not_build_ready"
REASON_CODE_DOSSIER_FAILED = "dossier_failed"
REASON_CODE_PROVIDER_CALL_FAILED = "provider_call_failed"
REASON_CODE_PROVIDER_CLIENT_INIT_FAILED = "provider_client_init_failed"
REASON_CODE_INVALID_AUTHOR_INPUT = "invalid_author_input"
REASON_CODE_AUTHOR_PROMPT_FAILED = "author_prompt_failed"
REASON_CODE_FILE_IO_FAILED = "file_io_failed"
REASON_CODE_INVALID_TIMEOUT = "invalid_timeout"

_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "raw_prompt",
        "raw_response",
        "secret",
        "token",
    }
)
_PATH_KEYS = frozenset(
    {
        "file_path",
        "module_dir",
        "output_directory",
        "path",
        "source_path",
    }
)
_ATTEMPT_METADATA_KEYS = (
    "attempt_id",
    "attempt_number",
    "revision_number",
    "job_id",
    "source_title",
    "source_hash",
    "source_profile",
    "rights_class",
    "rights_basis",
    "rights_review_required",
    "rights_review_status",
    "adaptation_mode",
    "provider",
    "world_seed_status",
    "world_seed_version",
    "world_seed_hash",
    "world_context_status",
    "world_context_version",
    "world_context_hash",
    "context_hash",
    "world_context_selected_module",
    "world_context_read_only",
)
_RESERVED_REQUEST_KEYS = frozenset(
    {"messages", "response_format", "timeout", "stream"}
)
_WORLD_CONTEXT_STATUS_VALUES = frozenset({"available", "fallback", "unavailable"})
_WORLD_SEED_STATUS_VALUES = frozenset({"available", "unavailable", "invalid"})
_WORLD_CONTEXT_SOURCE_KEYS = frozenset(
    {
        "world_context",
        "world_narrative_context",
        "campaign_model",
        "active_pressures",
        "registry_context",
        "approved_module_seeds",
    }
)


def _ascii_text(value: Any, limit: int = MAX_DIAGNOSTIC_CHARS) -> str:
    """Return a bounded ASCII diagnostic value without raw provider text."""
    text = str(value).encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(
    code: str,
    message: str,
    path: str = "",
) -> Dict[str, str]:
    """Build one bounded, ASCII-only diagnostic."""
    return {
        "code": _ascii_text(code, 80),
        "message": _ascii_text(message),
        "path": _ascii_text(path, 160),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def _bounded_value(value: Any, depth: int = 0) -> Any:
    """Copy request context with bounded containers and no sensitive keys."""
    if depth > 4:
        return "[bounded-depth]"
    if isinstance(value, str):
        return value[:MAX_AUTHOR_INPUT_TEXT_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for raw_key in list(value.keys())[:32]:
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            key_lower = key.lower()
            if not key or key_lower in _SENSITIVE_KEYS or key_lower in _PATH_KEYS:
                continue
            result[key[:80]] = _bounded_value(value[raw_key], depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth + 1) for item in list(value)[:32]]
    return _ascii_text(value, MAX_AUTHOR_INPUT_TEXT_CHARS)


def _prepare_attempt_metadata(
    attempt_metadata: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Keep only bounded attempt identity and provenance fields."""
    if attempt_metadata is None:
        return {}, []
    if not isinstance(attempt_metadata, Mapping):
        return {}, [_diagnostic(DIAGNOSTIC_CODE_INVALID_INPUT, "attempt_metadata must be an object")]

    metadata: Dict[str, Any] = {}
    diagnostics: List[Dict[str, str]] = []
    for key in _ATTEMPT_METADATA_KEYS:
        if key not in attempt_metadata:
            continue
        value = attempt_metadata.get(key)
        if key == "attempt_id":
            if not isinstance(value, str) or not _ATTEMPT_ID_RE.fullmatch(value):
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "attempt_id must be a safe lowercase identifier",
                        key,
                    )
                )
                continue
            metadata[key] = value[:MAX_ATTEMPT_ID_CHARS]
        elif key == "source_hash":
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "source_hash must be a lowercase SHA-256 digest",
                        key,
                    )
                )
                continue
            metadata[key] = value
        elif key in {"source_profile"}:
            if value not in VALID_SOURCE_PROFILES:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "source_profile is not a supported adaptation profile",
                        key,
                    )
                )
                continue
            metadata[key] = value
        elif key == "rights_class":
            if value not in VALID_RIGHTS_CLASSES:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "rights_class is not a supported rights value",
                        key,
                    )
                )
                continue
            metadata[key] = value
        elif key in {"world_seed_status"}:
            if value not in _WORLD_SEED_STATUS_VALUES:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "world_seed_status is not supported",
                        key,
                    )
                )
            else:
                metadata[key] = value
        elif key in {"world_context_status"}:
            if value not in _WORLD_CONTEXT_STATUS_VALUES:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "world_context_status is not supported",
                        key,
                    )
                )
            else:
                metadata[key] = value
        elif key in {"world_seed_hash", "world_context_hash", "context_hash"}:
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        f"{key} must be a lowercase SHA-256 digest",
                        key,
                    )
                )
            else:
                metadata[key] = value
        elif key in {"world_context_read_only"}:
            if value is not True:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        "world_context_read_only must be true",
                        key,
                    )
                )
            else:
                metadata[key] = True
        elif key in {"attempt_number", "revision_number"}:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_INPUT,
                        f"{key} must be a non-negative integer",
                        key,
                    )
                )
                continue
            metadata[key] = value
        elif isinstance(value, (str, bool, int, float)):
            metadata[key] = _bounded_value(value)
        else:
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_INPUT,
                    f"{key} must be a bounded scalar",
                    key,
                )
            )
    return metadata, diagnostics


def _world_context_candidate(
    source_context: Mapping[str, Any],
    world_context: Any,
) -> Any:
    """Resolve an optional task-6.1 pack without retaining it in the request."""
    if world_context is not None:
        return world_context
    for key in ("world_context", "world_narrative_context"):
        value = source_context.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _world_context_metadata(provenance: Mapping[str, Any]) -> Dict[str, Any]:
    """Map the read-only provenance envelope to scalar attempt metadata."""
    values: Dict[str, Any] = {
        "world_seed_status": provenance.get("world_seed_status"),
        "world_seed_version": provenance.get("world_seed_version"),
        "world_seed_hash": provenance.get("world_seed_hash"),
        "world_context_status": provenance.get("context_status"),
        "world_context_version": provenance.get("context_version"),
        "world_context_hash": provenance.get("context_hash"),
        "context_hash": provenance.get("context_hash"),
        "world_context_selected_module": provenance.get("selected_module"),
        "world_context_read_only": provenance.get("read_only"),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _prepare_author_request_metadata(
    source_context: Mapping[str, Any],
    attempt_metadata: Optional[Mapping[str, Any]],
    world_context: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    """Prepare Python-owned metadata and the scalar-only world envelope."""
    raw_metadata = dict(attempt_metadata or {}) if isinstance(attempt_metadata, Mapping) else attempt_metadata
    candidate = _world_context_candidate(source_context, world_context)
    provenance = build_world_context_provenance(candidate if candidate is not None else raw_metadata)
    if not isinstance(raw_metadata, Mapping):
        raw_metadata = attempt_metadata
    merged = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
    # A supplied pack is authoritative over caller-provided duplicate seed
    # fields.  This keeps the prompt/report identity tied to the selected pack.
    merged.update(_world_context_metadata(provenance))
    metadata, diagnostics = _prepare_attempt_metadata(merged)
    return metadata, provenance, diagnostics


def _strip_world_context(value: Any, depth: int = 0) -> Any:
    """Remove raw world-state keys before source context serialization."""
    if depth > 4:
        return "[bounded-depth]"
    if isinstance(value, Mapping):
        cleaned: Dict[str, Any] = {}
        for raw_key, child in list(value.items())[:32]:
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            lowered = key.lower()
            if (
                lowered in _WORLD_CONTEXT_SOURCE_KEYS
                or lowered.startswith("world_seed")
                or lowered.startswith("world_context")
                or lowered == "context_hash"
            ):
                continue
            cleaned[key] = _strip_world_context(child, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [_strip_world_context(item, depth + 1) for item in list(value)[:32]]
    return value


def _load_author_prompt() -> str:
    """Load the authoring contract; no divergent inline prompt is allowed."""
    text = ADAPTATION_AUTHOR_PROMPT_PATH.read_text(encoding="utf-8")
    if not text or not text.strip():
        raise ValueError("adaptation author prompt is empty")
    if not text.isascii():
        raise ValueError("adaptation author prompt is not ASCII")
    return text


def _serialize_author_input(
    source_context: Mapping[str, Any],
    attempt_metadata: Mapping[str, Any],
    world_context_provenance: Mapping[str, Any],
) -> str:
    """Serialize bounded source/profile context for the provider request."""
    payload = {
        "attempt_metadata": _bounded_value(attempt_metadata),
        "source_context": _bounded_value(_strip_world_context(source_context)),
        "world_context_provenance": _bounded_value(world_context_provenance),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > MAX_AUTHOR_INPUT_CHARS:
        encoded = json.dumps(
            {
                "attempt_metadata": _bounded_value(attempt_metadata),
                "source_context": {
                    "status": "bounded_truncation",
                    "note": "Source context exceeded the author request bound.",
                },
                "world_context_provenance": _bounded_value(world_context_provenance),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    return "ADAPTATION_AUTHOR_INPUT:\n" + encoded


def build_adaptation_author_messages(
    source_context: Mapping[str, Any],
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    *,
    world_context: Any = None,
) -> List[Dict[str, str]]:
    """Build the two-message adaptation author request without provider I/O."""
    if not isinstance(source_context, Mapping):
        raise ValueError("source_context must be an object")
    metadata, world_provenance, diagnostics = _prepare_author_request_metadata(
        source_context,
        attempt_metadata,
        world_context,
    )
    if diagnostics:
        raise ValueError("attempt_metadata is invalid")
    return [
        {"role": "system", "content": _load_author_prompt()},
        {
            "role": "user",
            "content": _serialize_author_input(source_context, metadata, world_provenance),
        },
    ]


def _find_non_ascii(value: Any, path: str = "") -> Optional[str]:
    """Return the first dossier path containing a non-ASCII string."""
    if isinstance(value, str) and not value.isascii():
        return path or "response"
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            found = _find_non_ascii(item, child)
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_non_ascii(item, f"{path}[{index}]")
            if found:
                return found
    return None


def _identity_diagnostics(
    dossier: Mapping[str, Any],
    attempt_metadata: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Reject provider changes to Python-owned provenance identity fields."""
    diagnostics: List[Dict[str, str]] = []
    for key in ("source_hash", "source_title", "source_profile", "rights_class"):
        expected = attempt_metadata.get(key)
        if expected is None:
            continue
        if dossier.get(key) != expected:
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PROVENANCE,
                    f"dossier {key} does not match attempt metadata",
                    key,
                )
            )
    if dossier.get("rights_class") == RIGHTS_CLASS_RESTRICTED:
        # The dossier parser checks the complete rights relationship. This
        # explicit check keeps the author result fail-closed even if the
        # parser is used in an environment without jsonschema.
        if dossier.get("rights_review_required") is not True:
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PROVENANCE,
                    "restricted rights class requires review",
                    "rights_review_required",
                )
            )
    return diagnostics


def _invalid_parse_result(
    diagnostics: List[Dict[str, str]],
    *,
    dossier_validation: Optional[Dict[str, Any]] = None,
    dossier: Optional[Dict[str, Any]] = None,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    status: str = RUNNER_STATUS_INVALID_MODEL_RESPONSE,
    outcome: str = OUTCOME_INVALID_MODEL_RESPONSE,
    failure_class: str = FAILURE_CLASS_MODEL_RESPONSE,
    error: str = "invalid_model_response",
    safe_class: str = REASON_CATEGORY_INVALID_MODEL_RESPONSE,
    reason_code: str = REASON_CODE_INVALID_MODEL_RESPONSE,
    revision_eligible: bool = False,
    retryable: bool = False,
    terminal: bool = True,
) -> Dict[str, Any]:
    metadata = dict(attempt_metadata or {})
    world_provenance = build_world_context_provenance(metadata)
    return {
        "status": status,
        "outcome": outcome,
        "ok": status == RUNNER_STATUS_SUCCESS,
        "failure_class": failure_class,
        "safe_class": safe_class,
        "reason_code": reason_code,
        "revision_eligible": bool(revision_eligible),
        "retryable": bool(retryable),
        "terminal": bool(terminal),
        "attempt_id": metadata.get("attempt_id"),
        "source_hash": metadata.get("source_hash"),
        "attempt_metadata": deepcopy(metadata),
        "world_context_provenance": world_provenance,
        "world_context_status": world_provenance.get("context_status"),
        "world_context_version": world_provenance.get("context_version"),
        "world_context_hash": world_provenance.get("context_hash"),
        "context_hash": world_provenance.get("context_hash"),
        "world_seed_status": world_provenance.get("world_seed_status"),
        "world_seed_version": world_provenance.get("world_seed_version"),
        "world_seed_hash": world_provenance.get("world_seed_hash"),
        "dossier": deepcopy(dossier) if dossier is not None else None,
        "dossier_status": (dossier or {}).get("status"),
        "dossier_validation": deepcopy(dossier_validation),
        "diagnostics": list(diagnostics),
        "error": error,
    }


def _reason_from_diagnostics(
    diagnostics: Any,
) -> Tuple[str, str]:
    """Derive a bounded reason category/code from diagnostic codes.

    Rights/provenance contradictions and explicit dossier statuses win over
    the generic invalid-response category so operators can distinguish them
    without any raw provider text.
    """
    codes: set[str] = set()
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        for item in diagnostics:
            if isinstance(item, Mapping):
                code = item.get("code")
                if isinstance(code, str) and code:
                    codes.add(code)
    if DIAGNOSTIC_CODE_INVALID_PROVENANCE in codes:
        return REASON_CATEGORY_RIGHTS_OR_PROVENANCE, REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH
    if DIAGNOSTIC_CODE_DOSSIER_REFUSED in codes:
        return REASON_CATEGORY_AUTHOR_POLICY_REFUSAL, REASON_CODE_DOSSIER_REFUSED
    if DIAGNOSTIC_CODE_DOSSIER_FAILED in codes:
        return REASON_CATEGORY_DOSSIER_VALIDATION, REASON_CODE_DOSSIER_FAILED
    if DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY in codes:
        return REASON_CATEGORY_DOSSIER_VALIDATION, REASON_CODE_DOSSIER_NOT_BUILD_READY
    return REASON_CATEGORY_INVALID_MODEL_RESPONSE, REASON_CODE_INVALID_MODEL_RESPONSE


def parse_adaptation_author_response(
    raw_response: Any,
    *,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse one strict provider response through the real dossier contract.

    Only raw JSON text or UTF-8 bytes are accepted at this boundary. Markdown
    fences, prose wrappers, non-object JSON, non-ASCII dossier content,
    schema failures, provenance mismatches, and non-build-ready dossiers all
    fail closed. No provider or filesystem operation is performed here.
    """
    metadata, metadata_diagnostics = _prepare_attempt_metadata(attempt_metadata)
    if metadata_diagnostics:
        return _invalid_parse_result(
            metadata_diagnostics,
            attempt_metadata=metadata,
            safe_class=REASON_CATEGORY_INVALID_INPUT,
            reason_code=REASON_CODE_INVALID_AUTHOR_INPUT,
            error="invalid_author_input",
        )

    if isinstance(raw_response, bytes):
        try:
            raw_response = raw_response.decode("utf-8")
        except UnicodeDecodeError:
            return _invalid_parse_result(
                [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "response is not valid UTF-8")],
                attempt_metadata=metadata,
            )
    if not isinstance(raw_response, str):
        return _invalid_parse_result(
            [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "response must be raw JSON text")],
            attempt_metadata=metadata,
        )

    text = raw_response.strip()
    if len(text) > MAX_AUTHOR_RESPONSE_CHARS:
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE,
                    "provider response exceeds the bounded response size",
                )
            ],
            attempt_metadata=metadata,
        )
    if "```" in text:
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_MARKDOWN_FENCE,
                    "markdown code fences are not accepted",
                )
            ],
            attempt_metadata=metadata,
        )
    if not text.isascii():
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_NON_ASCII_RESPONSE,
                    "provider response must contain ASCII characters only",
                )
            ],
            attempt_metadata=metadata,
        )

    dossier_validation = parse_adaptation_dossier(text)
    diagnostics = list(dossier_validation.get("diagnostics") or [])
    dossier = dossier_validation.get("dossier")
    if not dossier_validation.get("valid") or not isinstance(dossier, dict):
        # A raw JSON parse failure is an invalid model response; only JSON
        # that parses but fails schema/cross-field validation is a dossier
        # validation failure.
        parse_codes = {
            str(item.get("code"))
            for item in diagnostics
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
        }
        if DIAGNOSTIC_CODE_INVALID_JSON in parse_codes:
            reason_class = REASON_CATEGORY_INVALID_MODEL_RESPONSE
            reason_code = REASON_CODE_INVALID_MODEL_RESPONSE
        else:
            reason_class = REASON_CATEGORY_DOSSIER_VALIDATION
            reason_code = REASON_CODE_DOSSIER_VALIDATION_FAILED
        return _invalid_parse_result(
            diagnostics,
            dossier_validation=dossier_validation,
            dossier=dossier if isinstance(dossier, dict) else None,
            attempt_metadata=metadata,
            safe_class=reason_class,
            reason_code=reason_code,
        )

    non_ascii_path = _find_non_ascii(dossier)
    if non_ascii_path:
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CODE_NON_ASCII_RESPONSE,
                "dossier contains non-ASCII text",
                non_ascii_path,
            )
        )
    try:
        dossier_size = len(json.dumps(dossier, ensure_ascii=True, separators=(",", ":")))
    except (TypeError, ValueError):
        dossier_size = MAX_AUTHOR_RESPONSE_CHARS + 1
    if dossier_size > MAX_AUTHOR_RESPONSE_CHARS:
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE,
                "dossier exceeds the bounded response size",
            )
        )
    diagnostics.extend(_identity_diagnostics(dossier, metadata))
    if diagnostics:
        reason_class, reason_code = _reason_from_diagnostics(diagnostics)
        return _invalid_parse_result(
            diagnostics,
            dossier_validation=dossier_validation,
            dossier=dossier,
            attempt_metadata=metadata,
            safe_class=reason_class,
            reason_code=reason_code,
        )

    dossier_status = dossier.get("status")
    if dossier_status == ADAPTATION_DOSSIER_STATUS_REFUSED:
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_DOSSIER_REFUSED,
                    "adaptation author returned status=refused",
                )
            ],
            dossier_validation=dossier_validation,
            dossier=dossier,
            attempt_metadata=metadata,
            status=RUNNER_STATUS_REFUSED,
            outcome=OUTCOME_EXPLICIT_REFUSAL,
            failure_class=FAILURE_CLASS_REFUSAL,
            error="adaptation_author_refused",
            safe_class=REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
            reason_code=REASON_CODE_DOSSIER_REFUSED,
        )
    if dossier_status == ADAPTATION_DOSSIER_STATUS_FAILED:
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_DOSSIER_FAILED,
                    "adaptation author returned status=failed",
                )
            ],
            dossier_validation=dossier_validation,
            dossier=dossier,
            attempt_metadata=metadata,
            safe_class=REASON_CATEGORY_DOSSIER_VALIDATION,
            reason_code=REASON_CODE_DOSSIER_FAILED,
        )
    if dossier_status != ADAPTATION_DOSSIER_STATUS_READY or not dossier_validation.get(
        "build_ready"
    ):
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY,
                    "dossier is valid JSON but is not build-ready",
                )
            ],
            dossier_validation=dossier_validation,
            dossier=dossier,
            attempt_metadata=metadata,
            safe_class=REASON_CATEGORY_DOSSIER_VALIDATION,
            reason_code=REASON_CODE_DOSSIER_NOT_BUILD_READY,
        )

    world_provenance = build_world_context_provenance(metadata)
    return {
        "status": RUNNER_STATUS_SUCCESS,
        "outcome": OUTCOME_VALID,
        "ok": True,
        "failure_class": FAILURE_CLASS_NONE,
        "safe_class": REASON_CATEGORY_NONE,
        "reason_code": REASON_CODE_NONE,
        "revision_eligible": False,
        "retryable": False,
        "terminal": False,
        "attempt_id": metadata.get("attempt_id"),
        "source_hash": metadata.get("source_hash") or dossier.get("source_hash"),
        "attempt_metadata": deepcopy(metadata),
        "world_context_provenance": world_provenance,
        "world_context_status": world_provenance.get("context_status"),
        "world_context_version": world_provenance.get("context_version"),
        "world_context_hash": world_provenance.get("context_hash"),
        "context_hash": world_provenance.get("context_hash"),
        "world_seed_status": world_provenance.get("world_seed_status"),
        "world_seed_version": world_provenance.get("world_seed_version"),
        "world_seed_hash": world_provenance.get("world_seed_hash"),
        "dossier": deepcopy(dossier),
        "dossier_status": dossier_status,
        "dossier_validation": deepcopy(dossier_validation),
        "diagnostics": [],
        "error": None,
    }


def _get_field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    try:
        return getattr(value, key, default)
    except Exception:
        return default


def _extract_response_parts(response: Any) -> Tuple[Optional[str], bool, Dict[str, str]]:
    """Extract content/refusal/model metadata without retaining provider data."""
    choices = _get_field(response, "choices")
    response_metadata: Dict[str, str] = {}
    response_model = _get_field(response, "model")
    if isinstance(response_model, str) and response_model.strip():
        response_metadata["model"] = _ascii_text(response_model, 160)
    response_id = _get_field(response, "id")
    if isinstance(response_id, str) and response_id.strip():
        response_metadata["request_id"] = _ascii_text(response_id, 200)
    if not isinstance(choices, (list, tuple)) or not choices:
        return None, False, response_metadata
    first = choices[0]
    message = _get_field(first, "message")
    refusal = _get_field(message, "refusal")
    finish_reason = _get_field(first, "finish_reason")
    if refusal or finish_reason in {"refusal", "content_filter"}:
        return None, True, response_metadata
    content = _get_field(message, "content")
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            return None, False, response_metadata
    if not isinstance(content, str) or not content.strip():
        return None, False, response_metadata
    return content, False, response_metadata


def _infer_provider(
    attempt_metadata: Mapping[str, Any],
    params: Mapping[str, Any],
    model: str,
    client_injected: bool,
) -> str:
    configured = attempt_metadata.get("provider")
    if isinstance(configured, str) and configured.strip():
        return _ascii_text(configured.strip().lower(), 120)
    if params.get("use_openrouter") is True:
        return "openrouter"
    lowered_model = model.lower()
    if lowered_model.startswith(("moonshotai/", "anthropic/", "google/")):
        return "openrouter"
    if lowered_model.startswith(("gpt-", "openai/")):
        return "openai"
    if client_injected:
        return "injected"
    return "openai"


def _safe_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    """Return request parameter metadata with secret-like values removed."""
    safe: Dict[str, Any] = {}
    for key, value in params.items():
        if not isinstance(key, str) or key.lower() in _SENSITIVE_KEYS:
            continue
        safe[key] = _bounded_value(value)
    return safe


def _classify_provider_exception(exc: Exception) -> Tuple[str, bool]:
    """Classify provider failures without exposing exception text."""
    lowered = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return FAILURE_CLASS_TIMEOUT, True
    if any(token in lowered for token in ("quota", "rate limit", "429", "billing", "insufficient_quota")):
        return FAILURE_CLASS_QUOTA, True
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return FAILURE_CLASS_DEPENDENCY, False
    return FAILURE_CLASS_PROVIDER, any(
        token in lowered
        for token in (
            "connection",
            "503",
            "502",
            "504",
            "unavailable",
            "overloaded",
        )
    )


def _reason_for_failure_class(
    failure_class: str,
    *,
    client_init: bool = False,
) -> Tuple[str, str]:
    """Map a classified failure class to a bounded safe reason category/code.

    Timeout, quota, and dependency classes map to their named categories;
    every other provider failure (connection, service availability, generic
    API error) maps to the bounded ``provider_infrastructure`` category. Raw
    exception or refusal text is never carried here.
    """
    if failure_class == FAILURE_CLASS_TIMEOUT:
        return REASON_CATEGORY_TIMEOUT, REASON_CODE_REQUEST_TIMEOUT
    if failure_class == FAILURE_CLASS_QUOTA:
        return REASON_CATEGORY_QUOTA, REASON_CODE_QUOTA_EXCEEDED
    if failure_class == FAILURE_CLASS_DEPENDENCY:
        return REASON_CATEGORY_DEPENDENCY, REASON_CODE_DEPENDENCY_IMPORT_FAILED
    if failure_class == FAILURE_CLASS_REFUSAL:
        return REASON_CATEGORY_API_REFUSAL, REASON_CODE_PROVIDER_API_REFUSAL
    if client_init:
        return (
            REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
            REASON_CODE_PROVIDER_CLIENT_INIT_FAILED,
        )
    return (
        REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
        REASON_CODE_PROVIDER_CALL_FAILED,
    )


def _base_run_metadata(
    attempt_metadata: Mapping[str, Any],
    provider: str,
    model: str,
) -> Dict[str, Any]:
    world_provenance = build_world_context_provenance(attempt_metadata)
    return {
        "attempt_id": attempt_metadata.get("attempt_id"),
        "source_hash": attempt_metadata.get("source_hash"),
        "attempt_metadata": deepcopy(dict(attempt_metadata)),
        "world_context_provenance": world_provenance,
        "world_context_status": world_provenance.get("context_status"),
        "world_context_version": world_provenance.get("context_version"),
        "world_context_hash": world_provenance.get("context_hash"),
        "context_hash": world_provenance.get("context_hash"),
        "world_seed_status": world_provenance.get("world_seed_status"),
        "world_seed_version": world_provenance.get("world_seed_version"),
        "world_seed_hash": world_provenance.get("world_seed_hash"),
        "provider": _ascii_text(provider, 120),
        "model": _ascii_text(model, 160),
        "task_id": ADAPTATION_AUTHOR_TASK_ID,
        "prompt_contract": ADAPTATION_AUTHOR_PROMPT_NAME,
    }


def _strict_schema_node(node: Any) -> Any:
    """Return a deterministic strict-mode compatible copy of one schema node.

    OpenAI-family strict structured output requires ``additionalProperties:
    false`` on every object and every property listed in ``properties`` to be
    present in ``required``. The repository dossier schema already uses
    ``additionalProperties: false``; this transform marks every property as
    required and keeps the schema vocabulary inside the supported strict
    subset (``$ref``/``definitions`` remain untouched). Only ASCII structure
    is produced; the returned schema is a copy and never mutates the loaded
    dossier schema.
    """
    if isinstance(node, Mapping):
        result: Dict[str, Any] = {}
        for key, value in node.items():
            if key == "$schema":
                # Draft-07 meta marker is not part of a provider response
                # schema and is omitted from the derived copy.
                continue
            result[key] = _strict_schema_node(value)
        properties = result.get("properties")
        if isinstance(properties, Mapping):
            result["required"] = sorted(properties.keys())
            result["additionalProperties"] = False
        for key in ("definitions", "$defs"):
            definitions = result.get(key)
            if isinstance(definitions, Mapping):
                result[key] = {
                    name: _strict_schema_node(definition)
                    for name, definition in definitions.items()
                }
        return result
    if isinstance(node, list):
        return [_strict_schema_node(item) for item in node]
    return node


def build_adaptation_author_response_format(provider: str) -> Dict[str, Any]:
    """Build the strict structured-output contract for the author request.

    Direct OpenAI GPT-family and injected profiles receive the ``json_schema``
    response format with a strict derivation of the repository
    ``toolkit_adaptation_dossier.v1`` schema. Routed third-party profiles
    (``openrouter``) receive the narrowly documented ``json_object`` fallback
    because schema-strict response_format support is not guaranteed across
    routed model families. The Python dossier parser stays the final schema
    and cross-field validator under either contract; provider schema
    compliance is never publication success.

    The result is deterministic and bounded: schema identity must match the
    dossier version and the serialized schema must stay under the response
    format size bound. Any failure raises ValueError so the runner can fail
    closed before the provider call.
    """
    if str(provider).strip().lower() not in _STRICT_RESPONSE_FORMAT_PROVIDERS:
        return {"type": ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY}

    schema = load_adaptation_dossier_schema()
    if not isinstance(schema, Mapping):
        raise ValueError("adaptation dossier schema must be an object")
    strict_schema = _strict_schema_node(schema)
    identity = str(strict_schema.get("$id") or "")
    if ADAPTATION_DOSSIER_VERSION not in identity:
        raise ValueError(
            "adaptation dossier schema identity is not " + ADAPTATION_DOSSIER_VERSION
        )
    encoded = json.dumps(
        strict_schema,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > MAX_RESPONSE_FORMAT_SCHEMA_CHARS:
        raise ValueError("adaptation dossier response schema exceeds the bounded size")
    return {
        "type": ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
        "json_schema": {
            "name": ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME,
            "strict": True,
            "schema": strict_schema,
        },
    }


def run_llm_adaptation_author(
    source_context: Mapping[str, Any],
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    *,
    client: Optional[Any] = None,
    model: Optional[str] = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = ADAPTATION_AUTHOR_DEFAULT_TIMEOUT_SECONDS,
    world_context: Any = None,
) -> Dict[str, Any]:
    """Run the adaptation author with injectable client/model/parameters.

    ``source_context`` is already bounded context supplied by the caller; this
    runner does not perform source extraction or profile inference. The model
    returns a strict dossier string which is passed to the real dossier parser.
    The request uses the strict GPT-family structured-output contract built
    from the repository dossier schema (with the narrowly documented provider
    fallback); the Python dossier parser remains the final authority. Provider
    failures never invoke a semantic retry and no result writes files.
    """
    if not isinstance(source_context, Mapping):
        metadata, metadata_diagnostics = _prepare_attempt_metadata(attempt_metadata)
        metadata = dict(metadata)
        metadata_diagnostics = list(metadata_diagnostics)
    else:
        metadata, world_provenance, metadata_diagnostics = _prepare_author_request_metadata(
            source_context,
            attempt_metadata,
            world_context,
        )
    if metadata_diagnostics or not isinstance(source_context, Mapping):
        diagnostics = list(metadata_diagnostics)
        if not isinstance(source_context, Mapping):
            diagnostics.append(
                _diagnostic(DIAGNOSTIC_CODE_INVALID_INPUT, "source_context must be an object")
            )
        return _invalid_parse_result(
            diagnostics,
            attempt_metadata=metadata,
            status=RUNNER_STATUS_INVALID_INPUT,
            outcome=OUTCOME_INVALID_INPUT,
            failure_class=FAILURE_CLASS_FILE,
            error="invalid_author_input",
            safe_class=REASON_CATEGORY_INVALID_INPUT,
            reason_code=REASON_CODE_INVALID_AUTHOR_INPUT,
        )

    try:
        messages = build_adaptation_author_messages(
            source_context,
            metadata,
            world_context=world_provenance if isinstance(source_context, Mapping) else None,
        )
    except Exception:
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_PROMPT_FAILED,
                    "adaptation author prompt could not be loaded",
                )
            ],
            attempt_metadata=metadata,
            status=RUNNER_STATUS_PROMPT_FAILED,
            outcome=OUTCOME_PROMPT_FAILURE,
            failure_class=FAILURE_CLASS_FILE,
            error="adaptation_author_prompt_failed",
            safe_class=REASON_CATEGORY_PROMPT_FAILURE,
            reason_code=REASON_CODE_AUTHOR_PROMPT_FAILED,
        )

    requested_model = model if model is not None else DM_MAIN_MODEL
    if not isinstance(requested_model, str) or not requested_model.strip():
        return _invalid_parse_result(
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PARAMS,
                    "model must be a non-empty string",
                )
            ],
            attempt_metadata=metadata,
            status=RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
            outcome=OUTCOME_PARAMETER_RESOLUTION_FAILURE,
            failure_class=FAILURE_CLASS_PARAMETER_RESOLUTION,
            error="param_resolution_failed",
            safe_class=REASON_CATEGORY_PARAMETER_RESOLUTION,
            reason_code=REASON_CODE_INVALID_PARAMS,
        )
    requested_model = requested_model.strip()
    provider_hint = _infer_provider(metadata, {}, requested_model, client is not None)
    resolver = parameter_resolver or get_chat_completion_params

    try:
        params = resolver(ADAPTATION_AUTHOR_TASK_ID, requested_model)
        if not isinstance(params, Mapping):
            raise TypeError("parameter resolver must return an object")
        params = dict(params)
        if not params.get("model") or not isinstance(params.get("model"), str):
            raise ValueError("resolved parameters must include a model")
        invalid_keys = _RESERVED_REQUEST_KEYS.intersection(params.keys())
        if invalid_keys:
            raise ValueError("parameter resolver returned reserved request keys")
        if any(not isinstance(key, str) for key in params):
            raise ValueError("parameter resolver returned a non-string key")
    except Exception:
        base = _base_run_metadata(metadata, provider_hint, requested_model)
        base.update(
            {
                "status": RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
                "outcome": OUTCOME_PARAMETER_RESOLUTION_FAILURE,
                "ok": False,
                "failure_class": FAILURE_CLASS_PARAMETER_RESOLUTION,
                "safe_class": REASON_CATEGORY_PARAMETER_RESOLUTION,
                "reason_code": REASON_CODE_PARAM_RESOLUTION_FAILED,
                "terminal": True,
                "params_used": {},
                "diagnostics": [
                    _diagnostic(
                        DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
                        "chat parameter resolution failed",
                    )
                ],
                "dossier": None,
                "dossier_status": None,
                "dossier_validation": None,
                "response_metadata": {},
                "error": "param_resolution_failed",
                "retryable": False,
                "revision_eligible": False,
            }
        )
        return base

    resolved_model = str(params["model"])
    provider = _infer_provider(metadata, params, resolved_model, client is not None)
    if timeout_seconds is not None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            base = _base_run_metadata(metadata, provider, resolved_model)
            base.update(
                {
                    "status": RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
                    "outcome": OUTCOME_PARAMETER_RESOLUTION_FAILURE,
                    "ok": False,
                    "failure_class": FAILURE_CLASS_PARAMETER_RESOLUTION,
                    "safe_class": REASON_CATEGORY_PARAMETER_RESOLUTION,
                    "reason_code": REASON_CODE_INVALID_TIMEOUT,
                    "terminal": True,
                    "params_used": _safe_params(params),
                    "diagnostics": [
                        _diagnostic(
                            DIAGNOSTIC_CODE_INVALID_PARAMS,
                            "timeout_seconds must be a positive finite number",
                        )
                    ],
                    "dossier": None,
                    "dossier_status": None,
                    "dossier_validation": None,
                    "response_metadata": {},
                    "error": "invalid_timeout",
                    "retryable": False,
                    "revision_eligible": False,
                }
            )
            return base

    try:
        response_format = build_adaptation_author_response_format(provider)
    except Exception:
        base = _base_run_metadata(metadata, provider, resolved_model)
        base.update(
            {
                "status": RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
                "outcome": OUTCOME_PARAMETER_RESOLUTION_FAILURE,
                "ok": False,
                "failure_class": FAILURE_CLASS_PARAMETER_RESOLUTION,
                "safe_class": REASON_CATEGORY_PARAMETER_RESOLUTION,
                "reason_code": REASON_CODE_RESPONSE_FORMAT_FAILED,
                "terminal": True,
                "params_used": _safe_params(params),
                "diagnostics": [
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_PARAMS,
                        "adaptation author response format could not be built",
                    )
                ],
                "dossier": None,
                "dossier_status": None,
                "dossier_validation": None,
                "response_metadata": {},
                "error": "response_format_failed",
                "retryable": False,
                "revision_eligible": False,
            }
        )
        return base

    if client is None:
        try:
            client = create_chat_client()
        except Exception as exc:
            failure_class, retryable = _classify_provider_exception(exc)
            reason_class, reason_code = _reason_for_failure_class(
                failure_class, client_init=True
            )
            base = _base_run_metadata(metadata, provider, resolved_model)
            base.update(
                {
                    "status": RUNNER_STATUS_PROVIDER_FAILED,
                    "outcome": OUTCOME_PROVIDER_FAILURE,
                    "ok": False,
                    "failure_class": failure_class,
                    "provider_error_class": failure_class,
                    "safe_class": reason_class,
                    "reason_code": reason_code,
                    "retryable": retryable,
                    "terminal": failure_class == FAILURE_CLASS_DEPENDENCY,
                    "params_used": _safe_params(params),
                    "diagnostics": [
                        _diagnostic(
                            DIAGNOSTIC_CODE_PROVIDER_FAILED,
                            f"provider client initialization failed ({failure_class})",
                        )
                    ],
                    "dossier": None,
                    "dossier_status": None,
                    "dossier_validation": None,
                    "response_metadata": {},
                    "error": f"provider_failed:{failure_class}",
                    "revision_eligible": False,
                }
            )
            return base

    request_kwargs: Dict[str, Any] = dict(params)
    request_kwargs["messages"] = messages
    request_kwargs["response_format"] = response_format
    if timeout_seconds is not None:
        request_kwargs["timeout"] = timeout_seconds

    try:
        response = client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        failure_class, retryable = _classify_provider_exception(exc)
        reason_class, reason_code = _reason_for_failure_class(failure_class)
        base = _base_run_metadata(metadata, provider, resolved_model)
        base.update(
            {
                "status": RUNNER_STATUS_PROVIDER_FAILED,
                "outcome": OUTCOME_PROVIDER_FAILURE,
                "ok": False,
                "failure_class": failure_class,
                "provider_error_class": failure_class,
                "safe_class": reason_class,
                "reason_code": reason_code,
                "retryable": retryable,
                "terminal": failure_class == FAILURE_CLASS_DEPENDENCY,
                "params_used": _safe_params(params),
                "diagnostics": [
                    _diagnostic(
                        DIAGNOSTIC_CODE_PROVIDER_FAILED,
                        f"provider call failed ({failure_class})",
                    )
                ],
                "dossier": None,
                "dossier_status": None,
                "dossier_validation": None,
                "response_metadata": {},
                "error": f"provider_failed:{failure_class}",
                "revision_eligible": False,
            }
        )
        return base

    raw_content, provider_refusal, response_metadata = _extract_response_parts(response)
    if provider_refusal:
        base = _base_run_metadata(metadata, provider, resolved_model)
        base.update(
            {
                "status": RUNNER_STATUS_REFUSED,
                "outcome": OUTCOME_EXPLICIT_REFUSAL,
                "ok": False,
                "failure_class": FAILURE_CLASS_REFUSAL,
                "safe_class": REASON_CATEGORY_API_REFUSAL,
                "reason_code": REASON_CODE_PROVIDER_API_REFUSAL,
                "terminal": True,
                "params_used": _safe_params(params),
                "diagnostics": [
                    _diagnostic(
                        DIAGNOSTIC_CODE_PROVIDER_REFUSAL,
                        "provider returned an explicit refusal",
                    )
                ],
                "dossier": None,
                "dossier_status": None,
                "dossier_validation": None,
                "response_metadata": response_metadata,
                "error": "provider_refused",
                "retryable": False,
                "revision_eligible": False,
            }
        )
        if response_metadata.get("model"):
            base["model"] = response_metadata["model"]
        return base

    if raw_content is None:
        base = _base_run_metadata(metadata, provider, resolved_model)
        base.update(
            {
                "status": RUNNER_STATUS_INVALID_MODEL_RESPONSE,
                "outcome": OUTCOME_INVALID_MODEL_RESPONSE,
                "ok": False,
                "failure_class": FAILURE_CLASS_MODEL_RESPONSE,
                "safe_class": REASON_CATEGORY_INVALID_MODEL_RESPONSE,
                "reason_code": REASON_CODE_INVALID_MODEL_RESPONSE,
                "terminal": True,
                "params_used": _safe_params(params),
                "diagnostics": [
                    _diagnostic(
                        DIAGNOSTIC_CODE_INVALID_JSON,
                        "provider response did not contain a JSON content string",
                    )
                ],
                "dossier": None,
                "dossier_status": None,
                "dossier_validation": None,
                "response_metadata": response_metadata,
                "error": "invalid_model_response",
                "retryable": False,
                "revision_eligible": False,
            }
        )
        return base

    parsed = parse_adaptation_author_response(
        raw_content,
        attempt_metadata=metadata,
    )
    result = dict(parsed)
    parsed_source_hash = result.get("source_hash")
    result.update(
        _base_run_metadata(metadata, provider, resolved_model)
    )
    result["params_used"] = _safe_params(params)
    result["response_metadata"] = response_metadata
    result["source_hash"] = metadata.get("source_hash") or parsed_source_hash
    result["request"] = {
        "task_id": ADAPTATION_AUTHOR_TASK_ID,
        "timeout_seconds": timeout_seconds,
        "response_format": response_format.get("type"),
        "response_format_strict": bool(
            response_format.get("json_schema", {}).get("strict")
        ),
        "response_schema": (
            ADAPTATION_DOSSIER_VERSION
            if response_format.get("type") == ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT
            else None
        ),
        "parameter_keys": sorted(_safe_params(params).keys()),
    }
    if response_metadata.get("model"):
        result["model"] = response_metadata["model"]
    return result


# Short aliases keep the standalone utility convenient for callers while the
# explicit LLM name remains the canonical API used by future orchestration.
run_adaptation_author = run_llm_adaptation_author
run_toolkit_adaptation_author = run_llm_adaptation_author
parse_adaptation_response = parse_adaptation_author_response


__all__ = [
    "ADAPTATION_AUTHOR_DEFAULT_TIMEOUT_SECONDS",
    "ADAPTATION_AUTHOR_PROMPT_NAME",
    "ADAPTATION_AUTHOR_PROMPT_PATH",
    "ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY",
    "ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT",
    "ADAPTATION_AUTHOR_RESPONSE_FORMAT_VERSION",
    "ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME",
    "ADAPTATION_AUTHOR_TASK_ID",
    "DIAGNOSTIC_CODE_DOSSIER_FAILED",
    "DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY",
    "DIAGNOSTIC_CODE_DOSSIER_REFUSED",
    "DIAGNOSTIC_CODE_INVALID_JSON",
    "DIAGNOSTIC_CODE_INVALID_PARAMS",
    "DIAGNOSTIC_CODE_INVALID_PROVENANCE",
    "DIAGNOSTIC_CODE_MARKDOWN_FENCE",
    "DIAGNOSTIC_CODE_NON_ASCII_RESPONSE",
    "DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED",
    "DIAGNOSTIC_CODE_PROVIDER_FAILED",
    "DIAGNOSTIC_CODE_PROVIDER_REFUSAL",
    "DIAGNOSTIC_CODE_PROMPT_FAILED",
    "DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE",
    "OUTCOME_EXPLICIT_REFUSAL",
    "OUTCOME_INVALID_MODEL_RESPONSE",
    "OUTCOME_PARAMETER_RESOLUTION_FAILURE",
    "OUTCOME_PROVIDER_FAILURE",
    "OUTCOME_VALID",
    "REASON_CATEGORY_API_REFUSAL",
    "REASON_CATEGORY_AUTHOR_POLICY_REFUSAL",
    "REASON_CATEGORY_DEPENDENCY",
    "REASON_CATEGORY_DOSSIER_VALIDATION",
    "REASON_CATEGORY_FILE_IO",
    "REASON_CATEGORY_INVALID_INPUT",
    "REASON_CATEGORY_INVALID_MODEL_RESPONSE",
    "REASON_CATEGORY_NONE",
    "REASON_CATEGORY_PARAMETER_RESOLUTION",
    "REASON_CATEGORY_PROMPT_FAILURE",
    "REASON_CATEGORY_PROVIDER_INFRASTRUCTURE",
    "REASON_CATEGORY_QUOTA",
    "REASON_CATEGORY_RIGHTS_OR_PROVENANCE",
    "REASON_CATEGORY_TIMEOUT",
    "REASON_CODE_AUTHOR_PROMPT_FAILED",
    "REASON_CODE_DEPENDENCY_IMPORT_FAILED",
    "REASON_CODE_DOSSIER_FAILED",
    "REASON_CODE_DOSSIER_NOT_BUILD_READY",
    "REASON_CODE_DOSSIER_REFUSED",
    "REASON_CODE_DOSSIER_VALIDATION_FAILED",
    "REASON_CODE_FILE_IO_FAILED",
    "REASON_CODE_INVALID_AUTHOR_INPUT",
    "REASON_CODE_INVALID_MODEL_RESPONSE",
    "REASON_CODE_INVALID_PARAMS",
    "REASON_CODE_INVALID_TIMEOUT",
    "REASON_CODE_NONE",
    "REASON_CODE_PARAM_RESOLUTION_FAILED",
    "REASON_CODE_PROVIDER_API_REFUSAL",
    "REASON_CODE_PROVIDER_CALL_FAILED",
    "REASON_CODE_PROVIDER_CLIENT_INIT_FAILED",
    "REASON_CODE_QUOTA_EXCEEDED",
    "REASON_CODE_REQUEST_TIMEOUT",
    "REASON_CODE_RESPONSE_FORMAT_FAILED",
    "REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH",
    "VALID_REASON_CATEGORIES",
    "RUNNER_STATUS_INVALID_INPUT",
    "RUNNER_STATUS_INVALID_MODEL_RESPONSE",
    "RUNNER_STATUS_PARAM_RESOLUTION_FAILED",
    "RUNNER_STATUS_PROMPT_FAILED",
    "RUNNER_STATUS_PROVIDER_FAILED",
    "RUNNER_STATUS_REFUSED",
    "RUNNER_STATUS_SUCCESS",
    "build_adaptation_author_messages",
    "build_adaptation_author_response_format",
    "parse_adaptation_author_response",
    "parse_adaptation_response",
    "run_adaptation_author",
    "run_llm_adaptation_author",
    "run_toolkit_adaptation_author",
]
