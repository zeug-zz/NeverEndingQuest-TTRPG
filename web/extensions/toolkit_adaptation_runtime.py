# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit adaptation runtime envelope.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Python-owned runtime envelope and adapter boundary for the explicit LLM
adaptation lane (task 1.2 of toolkit-llm-adaptation-runtime-unification).

This module normalizes every supported Toolkit input into one deterministic,
bounded envelope:

  * input kind: upload_markdown, upload_pdf, or text_description;
  * a stable lowercase SHA-256 source identity with bounded source context;
  * Python-owned rights class, review requirement, and review status;
  * attempt / job / revision identity;
  * bounded world-context provenance and fallback status;
  * project-relative staging metadata without credentials or raw source.

The adapter only assembles metadata and serializes the envelope. It never
calls a provider, executes a module build, evaluates gates, touches the
registry, campaign, or rollback state, and it never includes raw source,
credentials, full prompts, or arbitrary absolute paths.

Provider metadata is advisory and allowlisted: the provider may echo the
Python-owned rights fields but can never change them. Contradictory rights,
unsafe paths, invalid hashes or attempt identities, and raw-source fields
fail closed with bounded diagnostics.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.file_operations import safe_write_json
from utils.toolkit_adaptation_artifacts import build_attempt_id
from utils.toolkit_adaptation_author import (
    REASON_CODE_NONE,
    REASON_CODE_PROVIDER_CALL_FAILED,
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
    VALID_REASON_CATEGORIES,
)
from utils.toolkit_adaptation_authoring import (
    AUTHORING_STATUS_BLOCKED,
    AUTHORING_STATUS_READY,
    run_adaptation_authoring,
)
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    MAX_TEXT_DESCRIPTION_CHARS,
    ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_provenance import MODEL_METADATA_KEYS
from utils.toolkit_adaptation_publication_convergence import (
    CONVERGENCE_CONTRACT_VERSION,
)
from utils.toolkit_adaptation_source_context import (
    ASSEMBLY_STATUS_INVALID,
    MAX_RAW_SOURCE_CHARS,
    build_adaptation_source_context,
    serialize_adaptation_source_context,
)
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    VALID_STAGING_STATES,
    get_adaptation_staging_target_path,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_homebrew_upload_contract import (
    PACKET_CONTRACT_VERSION,
    REVIEW_DECISION_APPROVE,
    REVIEW_DECISION_REJECT,
    SOURCE_RIGHTS_RESTRICTED,
    VALID_SOURCE_RIGHTS_CLASSES,
    build_review_snapshot,
    compute_sha256,
    get_workspace_files,
    load_json_artifact,
    load_normalized_packet_artifact,
    load_source_graph_artifact,
    load_source_manifest_artifact,
    validate_review_packet,
)
from utils.toolkit_source_manifest import build_source_manifest


RUNTIME_ENVELOPE_CONTRACT_VERSION = "toolkit_adaptation_runtime_envelope.v1"

INPUT_KIND_UPLOAD_MARKDOWN = "upload_markdown"
INPUT_KIND_UPLOAD_PDF = "upload_pdf"
INPUT_KIND_TEXT_DESCRIPTION = "text_description"
VALID_INPUT_KINDS = (
    INPUT_KIND_UPLOAD_MARKDOWN,
    INPUT_KIND_UPLOAD_PDF,
    INPUT_KIND_TEXT_DESCRIPTION,
)

ENVELOPE_STATUS_READY = "ready"
ENVELOPE_STATUS_INVALID = "invalid"

# Envelope-wide serialized bound. The bounded source context keeps its own
# smaller bound; this cap covers the whole handoff envelope.
MAX_ENVELOPE_SERIALIZED_CHARS = 32_000
MAX_SOURCE_TITLE_CHARS = 240
MAX_RAW_SOURCE_ACCEPT_CHARS = 200_000
MAX_RIGHTS_BASIS_CHARS = 500
MAX_JOB_ID_CHARS = 160
MAX_MODEL_METADATA_TEXT_CHARS = 160
MAX_PATH_CHARS = 512
MAX_DIAGNOSTICS = 12
MAX_DIAGNOSTIC_TEXT = 320

# Production convergence callback bounds.  Provider execution is limited to one
# bounded proposal request; Python remains the validation and staging boundary.
MAX_CONVERGENCE_CALLBACK_DIAGNOSTICS = 8
MAX_CONVERGENCE_PROVIDER_RESPONSE_CHARS = 16_000
DEFAULT_CONVERGENCE_PROVIDER_TIMEOUT_SECONDS = 30
ADAPTATION_CONVERGENCE_TASK_ID = "toolkit_adaptation_convergence"
CONVERGENCE_PROVIDER_SYSTEM_PROMPT = (
    "Return exactly one JSON object and no other text. The accepted envelope "
    "has only these top-level keys: status, proposal, operation, reason_code, "
    "failure_class. Do not add any other top-level key. For one bounded "
    "convergence operation, a successful response MUST use this exact shape: "
    '{"status":"success","proposal":{"operation":"resolve_destination_alias"}}. '
    "The proposal value must be one mapping containing one operation only. Use "
    'status="accepted" only as an equivalent success status. Use status="rejected" '
    "or status=\"failed\" when Python should not consider the proposal ready. "
    "Do not include paths, raw source, credentials, registry state, campaign "
    "state, prompts, or tracebacks."
)
_REPAIR_REQUEST_FIELDS = frozenset(
    {
        "repairable_blockers",
        "repairable_findings",
        "repair_requests",
        "proposal_request",
        "proposal_requests",
        "operation",
        "request",
    }
)
_CONVERGENCE_CONTEXT_FIELDS = frozenset(
    {
        "status",
        "repairable",
        "ambiguous_phrase",
        "candidates",
        "source_references",
        "allowed_operations",
        "confidence_threshold",
        "operation_budget",
        "timeout_seconds",
        "source_reference_ids",
        "canonical_location_ids",
        "authored_target_ids",
        "approved_monster_ids",
        "approved_monster_identities",
        "monster_reference_keys",
        "quantity_bounds",
        "topology",
    }
    | _REPAIR_REQUEST_FIELDS
)
_CONVERGENCE_CALLBACK_FIELDS = frozenset(
    {
        "contract_version",
        "attempt_id",
        "attempt_number",
        "revision_number",
        "source_hash",
        "budget",
        "validation_context",
        "operation",
        "request",
        "proposal_request",
        "staging_identity",
    }
)

TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS = "user_submitted_text_description"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")

_FORBIDDEN_SOURCE_KEYS = frozenset(
    {
        "raw_source",
        "raw_source_text",
        "source_text",
        "source_content",
        "full_source",
        "full_text",
        "raw_markdown",
        "raw_pdf",
    }
)
_FORBIDDEN_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "credentials",
        "token",
        "bearer",
    }
)
_FORBIDDEN_PROMPT_KEYS = frozenset(
    {
        "messages",
        "instructions",
        "system_prompt",
        "user_prompt",
        "raw_prompt",
        "raw_response",
        "prompt",
    }
)
_RIGHTS_KEYS = frozenset(
    {
        "rights_class",
        "rights_basis",
        "rights_review_required",
        "rights_review_status",
    }
)
_PATH_FIELDS = frozenset(
    {
        "path",
        "output_directory",
        "metadata_path",
        "staging_root",
        "source_path",
    }
)

_SCAN_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|token|credential)\s*[:=]\s*[^\s,;]+"
)
_SCAN_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SCAN_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")

# Supplementary redaction for the envelope guarantee: the scaffold's bounded
# excerpt redaction can leave a bare token value after "Authorization:
# Bearer ..." or "Bearer ..." has already been replaced. The adapter scrubs
# those residuals so no credential value survives in the serialized envelope.
_REDACTED_LEFTOVER_RE = re.compile(
    r"(?i)((?:\[redacted credential\]|Bearer \[redacted\]))\s+[A-Za-z0-9._~+/=-]{4,}"
)
_PROMPT_LINE_RE = re.compile(
    r"(?im)^\s*(?:system|developer|assistant|user)[_ -]?(?:prompt|message)?\s*[:=].*$"
)

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_SEVERITY_WARNING = "warning"


def _ascii_text(value: Any, limit: int = MAX_DIAGNOSTIC_TEXT) -> Tuple[str, bool, int]:
    """Return bounded, single-line-safe ASCII text."""
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char if char in "\n\t" or ord(char) >= 32 else " " for char in text)
    text = text.encode("ascii", "replace").decode("ascii").strip()
    original_length = len(text)
    if len(text) <= limit:
        return text, False, original_length
    marker = " [truncated]"
    keep = max(0, limit - len(marker))
    return text[:keep].rstrip() + marker, True, original_length


def _diagnostic(code: str, message: str, severity: str = DIAGNOSTIC_SEVERITY_ERROR) -> Dict[str, str]:
    text, _, _ = _ascii_text(message, MAX_DIAGNOSTIC_TEXT)
    return {"code": code, "message": text, "severity": severity}


def _scrub_bounded_context(value: Any) -> Any:
    """Remove residual credential material from a bounded source context.

    The scaffold already redacts credentials when it builds the context. This
    deterministic supplementary pass removes bare token values left behind by
    that redaction so the serialized runtime envelope never exposes them.
    """

    def _scrub_string(text: str) -> str:
        scrubbed = _PROMPT_LINE_RE.sub("[redacted source instruction]", text)
        scrubbed = _REDACTED_LEFTOVER_RE.sub(r"\1", scrubbed)
        scrubbed = _SCAN_BEARER_RE.sub("Bearer [redacted]", scrubbed)
        scrubbed = _SCAN_OPENAI_KEY_RE.sub("[redacted]", scrubbed)
        scrubbed = _SCAN_CREDENTIAL_RE.sub("[redacted credential]", scrubbed)
        scrubbed = _REDACTED_LEFTOVER_RE.sub(r"\1", scrubbed)
        return scrubbed

    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, list):
        return [_scrub_bounded_context(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _scrub_bounded_context(item) for key, item in value.items()}
    return value


def _error(code: str, message: str) -> Dict[str, str]:
    return _diagnostic(code, message, DIAGNOSTIC_SEVERITY_ERROR)


def _warning(code: str, message: str) -> Dict[str, str]:
    return _diagnostic(code, message, DIAGNOSTIC_SEVERITY_WARNING)


def _canonical_json(value: Any) -> str:
    """Serialize with stable key ordering and no NaN/Infinity."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _is_safe_attempt_id(value: Any) -> bool:
    if not isinstance(value, str) or ".." in value:
        return False
    return bool(_ATTEMPT_ID_RE.fullmatch(value))


def _safe_project_relative_path(value: Any) -> Tuple[Optional[str], bool]:
    """Return a project-relative POSIX path and whether the input was unsafe."""
    if value is None:
        return None, False
    if isinstance(value, Mapping):
        value = value.get("path")
    if not isinstance(value, (str, Path)):
        return None, True
    raw = str(value).strip()
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith("/")
        or _DRIVE_PATH_RE.match(raw)
    ):
        return None, True
    raw, _, _ = _ascii_text(raw, MAX_PATH_CHARS)
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None, True
    return PurePosixPath(*parts).as_posix(), False


def _invalid_envelope(input_kind: str, diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    """Return a deterministic fail-closed envelope for invalid inputs."""
    return {
        "contract_version": RUNTIME_ENVELOPE_CONTRACT_VERSION,
        "status": ENVELOPE_STATUS_INVALID,
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "input_kind": input_kind or "",
        "source_identity": {
            "source_title": "",
            "source_title_provenance": "fallback",
            "source_hash": "",
            "source_hash_provenance": "",
            "source_path": None,
            "source_path_policy": "source path omitted",
        },
        "source_context": None,
        "source_context_status": "unavailable",
        "rights": {
            "rights_class": None,
            "rights_basis": "",
            "rights_review_required": None,
            "rights_review_status": None,
            "python_owned": True,
            "provider_may_change": False,
        },
        "attempt": {
            "attempt_id": "",
            "attempt_number": 0,
            "revision_number": 0,
            "job_id": None,
        },
        "world_context": build_world_context_provenance(None),
        "staging": {"reserved": False, "isolated": True},
        "model_metadata": {},
        "policy": {
            "raw_source_included": False,
            "source_text_bounded": False,
            "credentials_redacted": True,
            "prompt_material_included": False,
            "provider_may_change_rights": False,
            "staging_project_relative": False,
            "world_context_read_only": True,
        },
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }


def build_adaptation_runtime_envelope(
    input_kind: str,
    *,
    source_text: Any = None,
    source_title: Optional[str] = None,
    source_hash: Optional[str] = None,
    source_path: Optional[str] = None,
    source_summary: Any = None,
    source_manifest: Any = None,
    normalized_packet: Any = None,
    source_graph: Any = None,
    source_profile: Optional[str] = None,
    source_context: Optional[Mapping[str, Any]] = None,
    rights_metadata: Optional[Mapping[str, Any]] = None,
    rights_class: Optional[str] = None,
    rights_basis: Optional[str] = None,
    rights_review_required: Optional[bool] = None,
    rights_review_status: Optional[str] = None,
    job_id: str = "",
    attempt_number: int = 1,
    attempt_id: Optional[str] = None,
    revision_number: int = 0,
    world_context: Any = None,
    staging_metadata: Optional[Mapping[str, Any]] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    provider_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize one Toolkit input into the bounded adaptation runtime envelope.

    The returned envelope carries Python-owned rights, stable source identity,
    bounded source context, attempt identity, world-context provenance, and
    project-relative staging metadata. Provider metadata is allowlisted and can
    never change rights. Invalid inputs fail closed with ``status=invalid`` and
    bounded diagnostics; this function never raises for bad input.
    """
    diagnostics: List[Dict[str, str]] = []

    kind = ""
    if isinstance(input_kind, str):
        kind = input_kind.strip().lower()
    if kind not in VALID_INPUT_KINDS:
        return _invalid_envelope(
            kind,
            [_error("invalid_input_kind", "input kind is not supported")],
        )

    # ---- Raw source (for hashing and bounded context only) ----------------
    raw_text = ""
    if source_text is not None:
        if isinstance(source_text, bytes):
            try:
                raw_text = source_text.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(_error("raw_source_invalid_utf8", "raw source is not valid UTF-8"))
        elif isinstance(source_text, str):
            raw_text = source_text
        else:
            diagnostics.append(_error("raw_source_invalid_type", "raw source must be text or UTF-8 bytes"))
    if kind == INPUT_KIND_TEXT_DESCRIPTION and not raw_text.strip():
        diagnostics.append(_error("source_text_empty", "text description requires non-empty source text"))
    if raw_text and len(raw_text) > MAX_RAW_SOURCE_ACCEPT_CHARS:
        diagnostics.append(
            _warning(
                "raw_source_oversized",
                "raw source exceeds the accept bound and is only retained as a bounded excerpt",
            )
        )

    # ---- Stable lowercase SHA-256 source identity -------------------------
    explicit_hash = None
    if source_hash is not None:
        if isinstance(source_hash, str):
            explicit_hash = source_hash
        else:
            diagnostics.append(_error("source_hash_invalid", "source hash must be a lowercase SHA-256 digest"))
    context_hash = None
    if isinstance(source_context, Mapping):
        candidate = source_context.get("source_hash")
        if isinstance(candidate, str):
            context_hash = candidate

    resolved_hash = ""
    hash_provenance = ""
    raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else ""
    for label, candidate in (("explicit_argument", explicit_hash), ("source_context", context_hash)):
        if candidate is None:
            continue
        normalized = candidate.strip().lower()
        if not _is_sha256(normalized):
            if label == "explicit_argument":
                diagnostics.append(_error("source_hash_invalid", "source hash must be a lowercase SHA-256 digest"))
            else:
                diagnostics.append(_warning("source_hash_reference_invalid", "a source context hash reference was ignored"))
            continue
        resolved_hash = normalized
        hash_provenance = label
        break
    if raw_digest:
        if resolved_hash and resolved_hash != raw_digest:
            diagnostics.append(_error("source_hash_mismatch", "provided source hash does not match the raw source"))
        elif not resolved_hash:
            resolved_hash = raw_digest
            hash_provenance = "raw_source"
    if not resolved_hash:
        diagnostics.append(_error("source_hash_missing", "source hash is unavailable"))

    # ---- Project-relative source path -------------------------------------
    safe_path = None
    if source_path is not None:
        safe_path, unsafe_path = _safe_project_relative_path(source_path)
        if unsafe_path:
            diagnostics.append(_error("source_path_unsafe", "source path must be project-relative"))
    path_policy = "source path omitted" if safe_path is None else "source path referenced when project-relative"

    # ---- Bounded source title ---------------------------------------------
    title = ""
    title_provenance = ""
    if isinstance(source_title, str) and source_title.strip():
        title, _, _ = _ascii_text(source_title, MAX_SOURCE_TITLE_CHARS)
        title_provenance = "explicit_argument"
    if not title and isinstance(source_context, Mapping):
        candidate = source_context.get("source_title")
        if isinstance(candidate, str) and candidate.strip():
            title, _, _ = _ascii_text(candidate, MAX_SOURCE_TITLE_CHARS)
            title_provenance = "source_context"
    if not title and safe_path:
        title, _, _ = _ascii_text(Path(safe_path).stem.replace("_", " "), MAX_SOURCE_TITLE_CHARS)
        title_provenance = "source_reference"
    if not title:
        title = "Untitled readable source"
        title_provenance = "fallback"

    # ---- Python-owned rights metadata -------------------------------------
    rights_map: Dict[str, Any] = {}
    if rights_metadata is not None:
        if isinstance(rights_metadata, Mapping):
            rights_map = dict(rights_metadata)
        else:
            diagnostics.append(_error("rights_metadata_invalid_type", "rights_metadata must be an object"))

    resolved_rights_class = rights_class if rights_class is not None else rights_map.get("rights_class")
    resolved_rights_basis = rights_basis if rights_basis is not None else rights_map.get("rights_basis")
    resolved_review_required = (
        rights_review_required
        if rights_review_required is not None
        else rights_map.get("rights_review_required")
    )
    resolved_review_status = (
        rights_review_status
        if rights_review_status is not None
        else rights_map.get("rights_review_status")
    )
    if kind == INPUT_KIND_TEXT_DESCRIPTION and resolved_rights_class is None:
        resolved_rights_class = RIGHTS_CLASS_USER_AUTHORED
        resolved_rights_basis = resolved_rights_basis or TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS
        resolved_review_required = False if resolved_review_required is None else resolved_review_required
        resolved_review_status = RIGHTS_REVIEW_NOT_REQUIRED if resolved_review_status is None else resolved_review_status

    if resolved_rights_class not in VALID_RIGHTS_CLASSES:
        diagnostics.append(_error("rights_class_invalid", "rights_class is unsupported"))
    if not isinstance(resolved_rights_basis, str) or not resolved_rights_basis.strip():
        diagnostics.append(_error("rights_basis_missing", "rights_basis is required"))
    if not isinstance(resolved_review_required, bool):
        diagnostics.append(_error("rights_review_required_invalid", "rights_review_required must be boolean"))
    if resolved_review_status not in VALID_RIGHTS_REVIEW_STATUSES:
        diagnostics.append(_error("rights_review_status_invalid", "rights_review_status is unsupported"))
    if resolved_rights_class == RIGHTS_CLASS_RESTRICTED and resolved_review_required is not True:
        diagnostics.append(_error("rights_review_contradiction", "restricted source requires rights review"))
    if resolved_review_required is True and resolved_review_status == RIGHTS_REVIEW_NOT_REQUIRED:
        diagnostics.append(_error("rights_review_contradiction", "required review cannot be not_required"))
    if resolved_review_required is False and resolved_review_status in {RIGHTS_REVIEW_PENDING, RIGHTS_REVIEW_REJECTED}:
        diagnostics.append(_error("rights_review_contradiction", "non-required review cannot be pending or rejected"))

    # ---- Attempt / job / revision identity --------------------------------
    safe_job_id = ""
    if job_id is None or job_id == "":
        safe_job_id = ""
    elif isinstance(job_id, str):
        safe_job_id, _, _ = _ascii_text(job_id.strip(), MAX_JOB_ID_CHARS)
    else:
        diagnostics.append(_error("job_id_invalid", "job_id must be text"))

    attempt_number_valid = (
        not isinstance(attempt_number, bool)
        and isinstance(attempt_number, int)
        and 1 <= attempt_number <= 1_000_000
    )
    if not attempt_number_valid:
        diagnostics.append(_error("attempt_number_invalid", "attempt_number is outside the supported range"))
    revision_number_valid = (
        not isinstance(revision_number, bool)
        and isinstance(revision_number, int)
        and 0 <= revision_number <= 100
    )
    if not revision_number_valid:
        diagnostics.append(_error("revision_number_invalid", "revision_number is outside the supported range"))

    resolved_attempt_id = ""
    if attempt_id is not None:
        if _is_safe_attempt_id(attempt_id):
            resolved_attempt_id = attempt_id
        else:
            diagnostics.append(_error("attempt_id_invalid", "attempt_id is not path-safe"))
    derived_attempt_id = None
    if resolved_hash:
        try:
            derived_attempt_id = build_attempt_id(
                resolved_hash,
                attempt_number if attempt_number_valid else 1,
                safe_job_id,
            )
        except Exception:
            diagnostics.append(_error("attempt_identity_failed", "attempt identity could not be created"))
    if not resolved_attempt_id and derived_attempt_id:
        resolved_attempt_id = derived_attempt_id
    if attempt_id is not None and _is_safe_attempt_id(attempt_id) and derived_attempt_id:
        if attempt_id != derived_attempt_id:
            diagnostics.append(_error("attempt_id_mismatch", "attempt_id does not match the source identity"))

    # ---- Bounded world-context provenance ---------------------------------
    world_provenance = build_world_context_provenance(world_context)

    # ---- Model / provider task metadata (no credentials, no rights) -------
    if model_metadata is not None and not isinstance(model_metadata, Mapping):
        diagnostics.append(_error("model_metadata_invalid_type", "model_metadata must be an object"))
    if provider_metadata is not None and not isinstance(provider_metadata, Mapping):
        diagnostics.append(_error("model_metadata_invalid_type", "provider_metadata must be an object"))
    merged_provider: Dict[str, Any] = {}
    if isinstance(model_metadata, Mapping):
        merged_provider.update(dict(model_metadata))
    if isinstance(provider_metadata, Mapping):
        merged_provider.update(dict(provider_metadata))

    python_rights_values = {
        "rights_class": resolved_rights_class,
        "rights_basis": resolved_rights_basis,
        "rights_review_required": resolved_review_required,
        "rights_review_status": resolved_review_status,
    }
    model_fields: Dict[str, Any] = {}
    for key, value in merged_provider.items():
        if not isinstance(key, str):
            continue
        lowered = key.strip().lower()
        if lowered in _RIGHTS_KEYS:
            if value != python_rights_values.get(key):
                diagnostics.append(_error("provider_rights_override_rejected", "provider metadata cannot change Python-owned rights"))
            continue
        if lowered in _FORBIDDEN_CREDENTIAL_KEYS or lowered in _FORBIDDEN_PROMPT_KEYS:
            diagnostics.append(_warning("provider_metadata_unsafe_key_dropped", "provider metadata credential or prompt field was dropped"))
            continue
        if lowered in _FORBIDDEN_SOURCE_KEYS:
            diagnostics.append(_warning("provider_metadata_unsafe_key_dropped", "provider metadata raw source field was dropped"))
            continue
        if key not in MODEL_METADATA_KEYS:
            diagnostics.append(_warning("provider_metadata_key_not_allowlisted", "provider metadata key was not allowlisted"))
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            diagnostics.append(_error("provider_metadata_value_invalid", "provider metadata values must be bounded scalars"))
            continue
        if isinstance(value, float) and not math.isfinite(value):
            diagnostics.append(_error("provider_metadata_value_invalid", "provider metadata values must be finite scalars"))
            continue
        if isinstance(value, str):
            if not value.strip():
                diagnostics.append(_warning("provider_metadata_empty_value_dropped", "provider metadata empty value was dropped"))
                continue
            model_fields[key] = _ascii_text(value.strip(), MAX_MODEL_METADATA_TEXT_CHARS)[0]
        else:
            model_fields[key] = value

    # ---- Project-relative staging metadata --------------------------------
    staging: Dict[str, Any] = {"reserved": False, "isolated": True}
    staging_paths_ok = True
    if staging_metadata is not None:
        if not isinstance(staging_metadata, Mapping):
            diagnostics.append(_error("staging_metadata_invalid_type", "staging_metadata must be an object"))
        else:
            staging["reserved"] = True
            for field in ("staging_root", "path", "output_directory", "metadata_path"):
                raw = staging_metadata.get(field)
                if raw in (None, ""):
                    continue
                relative_path, unsafe_path = _safe_project_relative_path(raw)
                if unsafe_path:
                    diagnostics.append(_error("staging_path_unsafe", "staging " + field + " must be project-relative"))
                    staging_paths_ok = False
                else:
                    staging[field] = relative_path
            stage_id = staging_metadata.get("stage_id")
            if stage_id is not None:
                if isinstance(stage_id, str) and stage_id.strip():
                    staging["stage_id"] = _ascii_text(stage_id.strip(), 160)[0]
                else:
                    diagnostics.append(_error("staging_identity_invalid", "staging stage_id is invalid"))
            completion_state = staging_metadata.get("completion_state")
            if completion_state is not None:
                if completion_state in VALID_STAGING_STATES:
                    staging["completion_state"] = completion_state
                else:
                    diagnostics.append(_error("staging_state_invalid", "staging completion state is invalid"))
            module_slug = staging_metadata.get("module_slug")
            if module_slug not in (None, ""):
                if isinstance(module_slug, str) and _MODULE_SLUG_RE.fullmatch(module_slug):
                    staging["module_slug"] = module_slug
                else:
                    diagnostics.append(_error("staging_module_slug_invalid", "staging module_slug is not path-safe"))
            staging_hash = staging_metadata.get("source_hash")
            if staging_hash not in (None, ""):
                if isinstance(staging_hash, str) and _is_sha256(staging_hash.strip().lower()):
                    if resolved_hash and staging_hash.strip().lower() != resolved_hash:
                        diagnostics.append(_error("staging_identity_mismatch", "staging source hash does not match the envelope"))
                else:
                    diagnostics.append(_error("staging_identity_invalid", "staging source hash is invalid"))
            staging_attempt = staging_metadata.get("attempt_id")
            if staging_attempt not in (None, ""):
                if isinstance(staging_attempt, str) and _is_safe_attempt_id(staging_attempt):
                    if resolved_attempt_id and staging_attempt != resolved_attempt_id:
                        diagnostics.append(_error("staging_identity_mismatch", "staging attempt identity does not match the envelope"))
                else:
                    diagnostics.append(_error("staging_identity_invalid", "staging attempt identity is invalid"))

    # ---- Bounded source context -------------------------------------------
    bounded_context = None
    if source_context is not None:
        if not isinstance(source_context, Mapping):
            diagnostics.append(_error("source_context_invalid_type", "source_context must be an object"))
        else:
            forbidden = sorted(key for key in _FORBIDDEN_SOURCE_KEYS if key in source_context)
            if forbidden:
                diagnostics.append(_error("raw_source_field_in_source_context", "raw source content is not allowed in source context"))
            else:
                try:
                    serialize_adaptation_source_context(source_context)
                    bounded_context = _scrub_bounded_context(deepcopy(dict(source_context)))
                except ValueError:
                    diagnostics.append(_error("source_context_too_large", "source context exceeds its serialized bound"))
    elif (
        raw_text
        or source_summary is not None
        or source_manifest is not None
        or normalized_packet is not None
        or source_graph is not None
    ):
        # The deterministic source manifest is derived from a pre-scrubbed
        # copy of the raw text so credential values that the manifest builder
        # could otherwise split away from their redaction markers never enter
        # the advisory evidence. The raw text itself is still hashed and
        # bounded untouched, preserving the stable source identity.
        manifest_input = source_manifest
        if manifest_input is None and raw_text:
            try:
                manifest_input = build_source_manifest(
                    _scrub_bounded_context(raw_text),
                    safe_path or "",
                    resolved_hash or raw_digest,
                )
            except Exception:
                manifest_input = None
        built = build_adaptation_source_context(
            raw_source=raw_text or None,
            source_summary=source_summary,
            source_manifest=manifest_input,
            normalized_packet=normalized_packet,
            source_graph=source_graph,
            source_path=safe_path,
            source_hash=resolved_hash or None,
            source_title=title,
            profile_override=source_profile,
        )
        if built.get("assembly_status") == ASSEMBLY_STATUS_INVALID:
            diagnostics.append(_error("source_context_invalid", "bounded source context assembly is invalid"))
        bounded_context = _scrub_bounded_context(built)
    else:
        diagnostics.append(_warning("source_context_missing", "no bounded source context material was supplied"))

    context_status = "unavailable"
    if isinstance(bounded_context, Mapping):
        context_status = bounded_context.get("context_status")
        if context_status not in {"available", "referenced", "unavailable"}:
            context_status = "unavailable"

    # ---- Policy flags ------------------------------------------------------
    source_text_bounded = bool(
        isinstance(bounded_context, Mapping)
        and any(
            isinstance(record, Mapping) and record.get("kind") == "raw_source_excerpt"
            for record in bounded_context.get("source_inputs", [])
        )
    )
    policy: Dict[str, Any] = {
        "raw_source_included": False,
        "source_text_bounded": source_text_bounded,
        "credentials_redacted": True,
        "prompt_material_included": False,
        "provider_may_change_rights": False,
        "staging_project_relative": bool(staging.get("reserved")) and staging_paths_ok,
        "world_context_read_only": world_provenance.get("read_only") is True,
    }

    # ---- Assemble ----------------------------------------------------------
    envelope: Dict[str, Any] = {
        "contract_version": RUNTIME_ENVELOPE_CONTRACT_VERSION,
        "status": ENVELOPE_STATUS_INVALID,
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "input_kind": kind,
        "source_identity": {
            "source_title": title,
            "source_title_provenance": title_provenance,
            "source_hash": resolved_hash,
            "source_hash_provenance": hash_provenance,
            "source_path": safe_path,
            "source_path_policy": path_policy,
        },
        "source_context": bounded_context,
        "source_context_status": context_status,
        "rights": {
            "rights_class": resolved_rights_class,
            "rights_basis": (
                _ascii_text(resolved_rights_basis, MAX_RIGHTS_BASIS_CHARS)[0]
                if isinstance(resolved_rights_basis, str)
                else ""
            ),
            "rights_review_required": resolved_review_required,
            "rights_review_status": resolved_review_status,
            "python_owned": True,
            "provider_may_change": False,
        },
        "attempt": {
            "attempt_id": resolved_attempt_id,
            "attempt_number": attempt_number if attempt_number_valid else 0,
            "revision_number": revision_number if revision_number_valid else 0,
            "job_id": safe_job_id or None,
        },
        "world_context": world_provenance,
        "staging": staging,
        "model_metadata": model_fields,
        "policy": policy,
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }

    has_errors = any(
        isinstance(item, Mapping) and item.get("severity") == DIAGNOSTIC_SEVERITY_ERROR
        for item in envelope["diagnostics"]
    )
    if not has_errors:
        envelope["status"] = ENVELOPE_STATUS_READY

    if len(_canonical_json(envelope)) > MAX_ENVELOPE_SERIALIZED_CHARS:
        diagnostics.append(_error("envelope_too_large", "runtime envelope exceeds its serialized bound"))
        envelope["diagnostics"] = diagnostics[:MAX_DIAGNOSTICS]
        envelope["status"] = ENVELOPE_STATUS_INVALID
    return envelope


def serialize_adaptation_runtime_envelope(envelope: Mapping[str, Any]) -> str:
    """Return deterministic canonical JSON for an assembled envelope."""
    if not isinstance(envelope, Mapping):
        raise ValueError("adaptation runtime envelope must be an object")
    encoded = _canonical_json(envelope)
    if len(encoded) > MAX_ENVELOPE_SERIALIZED_CHARS:
        raise ValueError("adaptation runtime envelope exceeds its serialized bound")
    return encoded


def _walk_unsafe_keys(value: Any, diagnostics: List[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if (
                lowered in _FORBIDDEN_SOURCE_KEYS
                or lowered in _FORBIDDEN_CREDENTIAL_KEYS
                or lowered in _FORBIDDEN_PROMPT_KEYS
            ):
                diagnostics.append("unsafe_field_" + lowered)
            _walk_unsafe_keys(item, diagnostics)
    elif isinstance(value, list):
        for item in value:
            _walk_unsafe_keys(item, diagnostics)


def _walk_unsafe_paths(value: Any, diagnostics: List[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PATH_FIELDS and isinstance(item, str) and item:
                relative_path, unsafe_path = _safe_project_relative_path(item)
                if unsafe_path:
                    diagnostics.append("unsafe_path_field_" + str(key))
            _walk_unsafe_paths(item, diagnostics)
    elif isinstance(value, list):
        for item in value:
            _walk_unsafe_paths(item, diagnostics)


def validate_adaptation_runtime_envelope(value: Any) -> Dict[str, Any]:
    """Validate an envelope round trip and guarantee no raw/credential leakage."""
    diagnostics: List[str] = []
    if not isinstance(value, Mapping):
        return {"valid": False, "status": ENVELOPE_STATUS_INVALID, "diagnostics": ["envelope_must_be_object"], "envelope": None}
    if value.get("contract_version") != RUNTIME_ENVELOPE_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    if value.get("status") not in {ENVELOPE_STATUS_READY, ENVELOPE_STATUS_INVALID}:
        diagnostics.append("status_invalid")
    if value.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        diagnostics.append("adaptation_mode_invalid")
    if value.get("input_kind") not in VALID_INPUT_KINDS:
        diagnostics.append("input_kind_invalid")

    identity = value.get("source_identity")
    if not isinstance(identity, Mapping):
        diagnostics.append("source_identity_missing")
    else:
        if not _is_sha256(identity.get("source_hash")):
            diagnostics.append("source_hash_invalid")
        source_path = identity.get("source_path")
        if source_path is not None:
            relative_path, unsafe_path = _safe_project_relative_path(source_path)
            if unsafe_path:
                diagnostics.append("source_path_unsafe")

    rights = value.get("rights")
    if not isinstance(rights, Mapping):
        diagnostics.append("rights_missing")
    else:
        rights_class_value = rights.get("rights_class")
        if rights_class_value not in VALID_RIGHTS_CLASSES:
            diagnostics.append("rights_class_invalid")
        if not isinstance(rights.get("rights_basis"), str) or not rights.get("rights_basis"):
            diagnostics.append("rights_basis_missing")
        if not isinstance(rights.get("rights_review_required"), bool):
            diagnostics.append("rights_review_required_invalid")
        if rights.get("rights_review_status") not in VALID_RIGHTS_REVIEW_STATUSES:
            diagnostics.append("rights_review_status_invalid")
        if rights_class_value == RIGHTS_CLASS_RESTRICTED and rights.get("rights_review_required") is not True:
            diagnostics.append("rights_review_contradiction")
        if rights.get("rights_review_required") is True and rights.get("rights_review_status") == RIGHTS_REVIEW_NOT_REQUIRED:
            diagnostics.append("rights_review_contradiction")
        if rights.get("rights_review_required") is False and rights.get("rights_review_status") in {
            RIGHTS_REVIEW_PENDING,
            RIGHTS_REVIEW_REJECTED,
        }:
            diagnostics.append("rights_review_contradiction")
        if rights.get("python_owned") is not True:
            diagnostics.append("rights_not_python_owned")

    attempt = value.get("attempt")
    if not isinstance(attempt, Mapping):
        diagnostics.append("attempt_missing")
    else:
        if not _is_safe_attempt_id(attempt.get("attempt_id")):
            diagnostics.append("attempt_id_invalid")
        attempt_number = attempt.get("attempt_number")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or not 1 <= attempt_number <= 1_000_000:
            diagnostics.append("attempt_number_invalid")
        revision_number = attempt.get("revision_number")
        if isinstance(revision_number, bool) or not isinstance(revision_number, int) or not 0 <= revision_number <= 100:
            diagnostics.append("revision_number_invalid")
        job_id = attempt.get("job_id")
        if job_id is not None and (not isinstance(job_id, str) or len(job_id) > MAX_JOB_ID_CHARS):
            diagnostics.append("job_id_invalid")
        if _is_safe_attempt_id(attempt.get("attempt_id")) and _is_sha256(identity.get("source_hash")) and isinstance(attempt_number, int):
            try:
                derived = build_attempt_id(
                    identity["source_hash"],
                    attempt_number,
                    str(job_id or ""),
                )
            except Exception:
                derived = None
            if derived and derived != attempt.get("attempt_id"):
                diagnostics.append("attempt_id_mismatch")

    world = value.get("world_context")
    if not isinstance(world, Mapping):
        diagnostics.append("world_context_missing")
    elif build_world_context_provenance(world) != dict(world):
        diagnostics.append("world_context_not_canonical")

    staging = value.get("staging")
    if not isinstance(staging, Mapping):
        diagnostics.append("staging_missing")
    else:
        if staging.get("reserved") is True:
            for field in ("staging_root", "path", "output_directory", "metadata_path"):
                raw = staging.get(field)
                if raw in (None, ""):
                    continue
                relative_path, unsafe_path = _safe_project_relative_path(raw)
                if unsafe_path:
                    diagnostics.append("staging_path_unsafe_" + field)
            completion_state = staging.get("completion_state")
            if completion_state is not None and completion_state not in VALID_STAGING_STATES:
                diagnostics.append("staging_state_invalid")

    model = value.get("model_metadata")
    if not isinstance(model, Mapping):
        diagnostics.append("model_metadata_missing")
    else:
        for key, item in model.items():
            if key not in MODEL_METADATA_KEYS:
                diagnostics.append("model_metadata_key_not_allowlisted")
                break
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                diagnostics.append("model_metadata_value_not_scalar")
                break
            if isinstance(item, float) and not math.isfinite(item):
                diagnostics.append("model_metadata_value_not_scalar")
                break

    policy = value.get("policy")
    if not isinstance(policy, Mapping):
        diagnostics.append("policy_missing")
    else:
        if policy.get("raw_source_included") is not False:
            diagnostics.append("raw_source_policy_invalid")
        if policy.get("provider_may_change_rights") is not False:
            diagnostics.append("provider_rights_policy_invalid")

    source_context = value.get("source_context")
    if source_context is not None:
        if not isinstance(source_context, Mapping):
            diagnostics.append("source_context_invalid")
        else:
            try:
                serialize_adaptation_source_context(source_context)
            except ValueError:
                diagnostics.append("source_context_too_large")

    _walk_unsafe_keys(value, diagnostics)
    _walk_unsafe_paths(value, diagnostics)
    try:
        encoded = _canonical_json(value)
        if len(encoded) > MAX_ENVELOPE_SERIALIZED_CHARS:
            diagnostics.append("envelope_too_large")
        if _SCAN_OPENAI_KEY_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_BEARER_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_CREDENTIAL_RE.search(encoded):
            diagnostics.append("credential_value_present")
    except (TypeError, ValueError):
        diagnostics.append("envelope_not_serializable")

    return {
        "valid": not diagnostics,
        "status": ENVELOPE_STATUS_READY if not diagnostics else ENVELOPE_STATUS_INVALID,
        "diagnostics": diagnostics[: MAX_DIAGNOSTICS * 4],
        "envelope": deepcopy(dict(value)) if not diagnostics else None,
    }


def adaptation_convergence_callback(
    context: Mapping[str, Any],
    *,
    client: Any = None,
    client_factory: Optional[Callable[[], Any]] = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: float = DEFAULT_CONVERGENCE_PROVIDER_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Inspect one bounded convergence request before any provider boundary.

    The packet-builder convergence seam supplies the current staging identity,
    budget, and optional bounded validation context.  A normal staged build has
    no repair request, so this adapter returns the existing callback success
    shape deterministically and without importing or invoking a provider.  A
    repairable request crosses only the bounded provider proposal boundary; it
    never falls through to legacy generation.

    This function does not validate or apply proposals.  The existing
    convergence runner remains the Python-owned validation and staging boundary.
    """

    identity: Dict[str, Any] = {}

    def _failure(
        reason_code: str,
        diagnostics: Sequence[str],
        *,
        provider_failure_class: Optional[str] = None,
        failure_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "failed",
            "reason_code": reason_code,
            "operation": None,
            "diagnostics": list(dict.fromkeys(diagnostics))[:MAX_CONVERGENCE_CALLBACK_DIAGNOSTICS],
        }
        if provider_failure_class:
            result["provider_failure_class"] = provider_failure_class
        if failure_class:
            result["failure_class"] = failure_class
        result.update(identity)
        return result

    def _provider_failure(exc: Any, *, client_initialization: bool = False) -> Dict[str, Any]:
        lowered = f"{type(exc).__name__} {exc}".lower()
        if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
            return _failure(
                "provider_timeout",
                ("provider_timeout",),
                provider_failure_class="timeout",
                failure_class="timeout",
            )
        if any(token in lowered for token in ("quota", "rate limit", "429", "billing", "insufficient_quota")):
            return _failure(
                "provider_quota",
                ("provider_quota",),
                provider_failure_class="quota",
                failure_class="quota",
            )
        if client_initialization and isinstance(exc, (ImportError, ModuleNotFoundError)):
            return _failure(
                "provider_dependency_unavailable",
                ("provider_dependency",),
                provider_failure_class="unavailable",
                failure_class="dependency",
            )
        if client_initialization:
            return _failure(
                "provider_dependency_unavailable",
                ("provider_client_initialization",),
                provider_failure_class="unavailable",
                failure_class="dependency",
            )
        if any(token in lowered for token in ("connection", "503", "502", "504", "unavailable", "overloaded")):
            return _failure(
                "provider_unavailable",
                ("provider_unavailable",),
                provider_failure_class="unavailable",
                failure_class="unavailable",
            )
        return _failure(
            "provider_unknown",
            ("provider_unknown",),
            provider_failure_class="unknown",
            failure_class="unknown",
        )

    def _response_content(response: Any) -> Any:
        if isinstance(response, Mapping):
            return response
        choices = getattr(response, "choices", None)
        if not isinstance(choices, (list, tuple)) or len(choices) != 1:
            raise ValueError("provider response shape is invalid")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            raise ValueError("provider response content is invalid")
        if not content.strip() or len(content) > MAX_CONVERGENCE_PROVIDER_RESPONSE_CHARS:
            raise ValueError("provider response exceeds its bound")
        try:
            return json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider response JSON is invalid") from exc

    def _proposal_result(response: Any) -> Dict[str, Any]:
        try:
            payload = _response_content(response)
        except Exception:
            return _failure(
                "provider_response_malformed",
                ("provider_response_malformed",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        if not isinstance(payload, Mapping):
            return _failure(
                "provider_response_malformed",
                ("provider_response_malformed",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        allowed = {"status", "proposal", "operation", "reason_code", "failure_class"}
        if set(payload) - allowed:
            return _failure(
                "provider_response_malformed",
                ("provider_response_fields_invalid",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"success", "accepted", "rejected", "failed", "malformed", "invalid"}:
            return _failure(
                "provider_response_malformed",
                ("provider_response_status_invalid",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        if status in {"malformed", "invalid"}:
            return _failure(
                "provider_response_malformed",
                ("provider_response_malformed",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        if status in {"rejected", "failed"}:
            return _failure(
                "provider_proposal_rejected",
                ("provider_proposal_rejected",),
                provider_failure_class="rejected",
                failure_class="rejected",
            )
        proposal = payload.get("proposal", payload.get("operation"))
        if status not in {"success", "accepted"} or not isinstance(proposal, Mapping):
            return _failure(
                "provider_response_malformed",
                ("provider_proposal_missing",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        encoded = _canonical_json(proposal)
        if len(encoded) > MAX_CONVERGENCE_PROVIDER_RESPONSE_CHARS:
            return _failure(
                "provider_response_malformed",
                ("provider_proposal_too_large",),
                provider_failure_class="malformed",
                failure_class="malformed",
            )
        unsafe_keys: List[str] = []
        unsafe_paths: List[str] = []
        _walk_unsafe_keys(proposal, unsafe_keys)
        _walk_unsafe_paths(proposal, unsafe_paths)
        if unsafe_keys or unsafe_paths:
            return _failure(
                "provider_proposal_rejected",
                ("provider_proposal_unsafe",),
                provider_failure_class="rejected",
                failure_class="rejected",
            )
        return {
            "status": "success",
            "reason_code": "provider_proposal_ready",
            "proposal": deepcopy(dict(proposal)),
            "operation": None,
            "diagnostics": [],
            **identity,
        }

    def _bounded_request() -> Dict[str, Any]:
        validation = context.get("validation_context")
        request: Dict[str, Any] = {
            "contract_version": CONVERGENCE_CONTRACT_VERSION,
            **{
                key: deepcopy(value)
                for key, value in identity.items()
                if key != "staging_identity"
            },
            "budget": deepcopy(dict(budget)),
        }
        for field in ("operation", "request", "proposal_request"):
            value = context.get(field)
            if value is not None:
                request[field] = deepcopy(value)
        if isinstance(validation, Mapping):
            request["validation_context"] = {
                key: deepcopy(value)
                for key, value in validation.items()
                if key in _CONVERGENCE_CONTEXT_FIELDS
            }
        encoded = _canonical_json(request)
        if len(encoded) > MAX_CONVERGENCE_PROVIDER_RESPONSE_CHARS:
            raise ValueError("bounded convergence request exceeds its bound")
        unsafe_keys: List[str] = []
        unsafe_paths: List[str] = []
        _walk_unsafe_keys(request, unsafe_keys)
        _walk_unsafe_paths(request, unsafe_paths)
        if unsafe_keys or unsafe_paths:
            raise ValueError("bounded convergence request contains unsafe fields")
        return request

    def _provider_call(request: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            from model_config import DM_MAIN_MODEL
            from utils.ai_client_factory import create_chat_client, get_chat_completion_params

            if client is not None:
                resolved_client = client
            else:
                try:
                    resolved_client = (
                        client_factory() if client_factory is not None else create_chat_client()
                    )
                except Exception as exc:
                    return _provider_failure(exc, client_initialization=True)
            resolver = parameter_resolver or get_chat_completion_params
            try:
                params = resolver(ADAPTATION_CONVERGENCE_TASK_ID, DM_MAIN_MODEL)
            except Exception as exc:
                return _provider_failure(exc, client_initialization=True)
            if not isinstance(params, Mapping) or not isinstance(params.get("model"), str):
                return _failure(
                    "provider_dependency_unavailable",
                    ("provider_parameter_resolution",),
                    provider_failure_class="unavailable",
                    failure_class="dependency",
                )
            params = dict(params)
            if any(key in params for key in ("messages", "timeout", "response_format")):
                return _failure(
                    "provider_dependency_unavailable",
                    ("provider_parameter_resolution",),
                    provider_failure_class="unavailable",
                    failure_class="dependency",
                )
            messages = [
                {
                    "role": "system",
                    "content": CONVERGENCE_PROVIDER_SYSTEM_PROMPT,
                },
                {"role": "user", "content": _canonical_json(request)},
            ]
            response = resolved_client.chat.completions.create(
                messages=messages,
                timeout=timeout_seconds,
                response_format={"type": "json_object"},
                **params,
            )
            return _proposal_result(response)
        except Exception as exc:
            return _provider_failure(exc)

    if not isinstance(context, Mapping):
        return _failure("callback_context_invalid", ("callback_context_invalid",))
    if context.get("contract_version") != CONVERGENCE_CONTRACT_VERSION:
        return _failure("callback_context_invalid", ("contract_version_invalid",))
    unexpected_context_fields = set(context) - _CONVERGENCE_CALLBACK_FIELDS
    if unexpected_context_fields:
        return _failure("callback_context_invalid", ("context_fields_invalid",))

    identity_fields = ("attempt_id", "attempt_number", "revision_number", "source_hash")
    identity = {field: context.get(field) for field in identity_fields}
    if not _is_safe_attempt_id(identity["attempt_id"]):
        return _failure("callback_context_invalid", ("attempt_id_invalid",))
    if (
        isinstance(identity["attempt_number"], bool)
        or not isinstance(identity["attempt_number"], int)
        or identity["attempt_number"] < 0
    ):
        return _failure("callback_context_invalid", ("attempt_number_invalid",))
    if (
        isinstance(identity["revision_number"], bool)
        or not isinstance(identity["revision_number"], int)
        or identity["revision_number"] < 0
    ):
        return _failure("callback_context_invalid", ("revision_number_invalid",))
    if not _is_sha256(identity["source_hash"]):
        return _failure("callback_context_invalid", ("source_hash_invalid",))

    staging_identity = context.get("staging_identity")
    if not isinstance(staging_identity, Mapping):
        return _failure("callback_context_invalid", ("staging_identity_invalid",))
    stage_id = staging_identity.get("stage_id")
    module_slug = staging_identity.get("module_slug", "")
    stage_path, stage_path_unsafe = _safe_project_relative_path(staging_identity.get("path"))
    output_path, output_path_unsafe = _safe_project_relative_path(
        staging_identity.get("output_directory")
    )
    if (
        stage_path_unsafe
        or output_path_unsafe
        or not isinstance(stage_id, str)
        or stage_id != f"{identity['attempt_id']}:revision_{identity['revision_number']:03d}"
        or not isinstance(module_slug, str)
        or (module_slug and not _MODULE_SLUG_RE.fullmatch(module_slug))
        or stage_path is None
        or output_path != stage_path
        or f"{identity['attempt_id']}/revision_{identity['revision_number']:03d}" not in stage_path
    ):
        return _failure("callback_context_invalid", ("staging_identity_invalid",))
    identity["staging_identity"] = {
        "stage_id": stage_id,
        "module_slug": module_slug,
        "path": stage_path,
        "output_directory": output_path,
    }

    budget = context.get("budget")
    if not isinstance(budget, Mapping):
        return _failure("callback_context_invalid", ("budget_invalid",))
    current_attempt = budget.get("current_attempt")
    if isinstance(current_attempt, bool) or not isinstance(current_attempt, int) or current_attempt < 0:
        return _failure("callback_context_invalid", ("current_attempt_invalid",))

    validation_context = context.get("validation_context")
    repairable = False
    for field in ("operation", "request", "proposal_request"):
        value = context.get(field)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            return _failure("callback_context_invalid", (field + "_invalid",))
        repairable = repairable or bool(value)
    if validation_context is None:
        pass
    elif not isinstance(validation_context, Mapping):
        return _failure("callback_context_invalid", ("validation_context_invalid",))
    elif validation_context.get("status") == "invalid":
        return _failure("callback_context_invalid", ("validation_context_invalid",))
    else:
        if set(validation_context) - _CONVERGENCE_CONTEXT_FIELDS:
            return _failure("callback_context_invalid", ("validation_context_fields_invalid",))
        if "repairable" in validation_context and not isinstance(validation_context["repairable"], bool):
            return _failure("callback_context_invalid", ("repairable_flag_invalid",))
        for field in _REPAIR_REQUEST_FIELDS:
            if field not in validation_context:
                continue
            value = validation_context.get(field)
            if field in {"proposal_request", "operation", "request"}:
                if value is None or value == {}:
                    continue
                if not isinstance(value, Mapping):
                    return _failure("callback_context_invalid", (field + "_invalid",))
                repairable = bool(value)
                continue
            if not isinstance(value, (list, tuple)):
                return _failure("callback_context_invalid", (field + "_invalid",))
            repairable = repairable or bool(value)
        repairable = repairable or validation_context.get("repairable", False)

    if repairable:
        try:
            return _provider_call(_bounded_request())
        except Exception:
            return _failure("provider_context_invalid", ("provider_context_invalid",))

    result = {
        "status": "success",
        "reason_code": "no_repairable_blocker",
        "operation": None,
        "diagnostics": [],
        **identity,
    }
    return result


# ---------------------------------------------------------------------------
# Task 2.1 - Approved upload workspace handoff
#
# Python-owned upload adapter at the shared runtime boundary. It accepts an
# approved upload workspace plus the supplied source kind, upload rights
# classification, job/attempt metadata, and an optional read-only
# world-context input, loads the normalized packet and source artifacts from
# the workspace, and assembles the bounded adaptation source context through
# the task 1.2 envelope seam (build_adaptation_runtime_envelope, which reuses
# build_adaptation_source_context and build_world_context_provenance).
#
# The helper never calls a provider, never invokes the module builder, never
# reserves a final staging/publication target, and never writes files. Raw
# source never reaches provider-facing context unbounded. Unsupported,
# unapproved, missing, or invalid workspace/packet inputs fail closed with
# bounded diagnostics. Source hash, source kind, supplied upload rights
# classification/review state, attempt identity, and canonical world-context
# provenance (including the explicit unavailable fallback) are preserved.
# ---------------------------------------------------------------------------

UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION = "toolkit_upload_adaptation_handoff.v1"

HANDOFF_STATUS_READY = "ready"
HANDOFF_STATUS_FAILED_CLOSED = "failed_closed"

UPLOAD_SOURCE_KIND_MARKDOWN = "markdown"
UPLOAD_SOURCE_KIND_PDF = "pdf"
VALID_UPLOAD_SOURCE_KINDS = frozenset(
    {UPLOAD_SOURCE_KIND_MARKDOWN, UPLOAD_SOURCE_KIND_PDF}
)

# Upload job states in which a workspace may be handed to adaptation
# authoring. Mirrors the upload lifecycle transitions observed in the Toolkit
# upload job routes (auto-approve, operator review approve, overwrite
# confirmation, and readiness handoff all land in one of these states).
APPROVED_UPLOAD_REVIEW_STATES = frozenset(
    {
        "approved_for_build",
        "awaiting_overwrite_confirmation",
        "ready_for_finishing",
    }
)

# Aligned with the Toolkit intake cap (20 MiB) so a workspace that somehow
# exceeds intake is rejected before the source text is parsed.
MAX_UPLOAD_SOURCE_BYTES = 20_000_000

MAX_HANDOFF_SERIALIZED_CHARS = 36_000

UPLOAD_RIGHTS_BASIS_BY_CLASS = {
    "user_authored": "user_authored_uploaded_adventure",
    "licensed_or_project_owned": "licensed_or_project_owned_upload",
    "third_party_copyright_restricted": "third_party_copyright_restricted_upload",
}


def _resolve_upload_workspace(value: Any) -> Tuple[Optional[Path], str, str]:
    """Resolve an upload workspace path inside the repository.

    Returns ``(workspace_path, relative_posix, error_code)``. The workspace
    must be project-relative or resolve inside the repository; absolute paths
    outside the repository fail closed so the adapter never reads arbitrary
    host paths.
    """
    repo_root = Path(__file__).resolve().parents[2]
    if isinstance(value, Mapping):
        value = value.get("path")
    if not isinstance(value, (str, Path)):
        return None, "", "workspace_invalid"
    raw = str(value).strip()
    if not raw or "\x00" in raw or "\\" in raw:
        return None, "", "workspace_invalid"

    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve(strict=False).relative_to(repo_root.resolve())
        except ValueError:
            return None, "", "workspace_outside_repo"
        workspace = repo_root / relative
        relative_posix = PurePosixPath(*relative.parts).as_posix()
    else:
        normalized = PurePosixPath(raw)
        if not normalized.parts or any(part in {"", ".", ".."} for part in normalized.parts):
            return None, "", "workspace_invalid"
        workspace = repo_root.joinpath(*normalized.parts)
        relative_posix = normalized.as_posix()

    if not workspace.exists():
        return None, "", "workspace_missing"
    if not workspace.is_dir():
        return None, "", "workspace_invalid"
    return workspace, relative_posix, ""


def build_upload_adaptation_handoff(
    workspace: Any,
    *,
    source_kind: str,
    source_rights_class: str,
    review_state: str,
    job_id: str = "",
    attempt_number: int = 1,
    attempt_id: Optional[str] = None,
    revision_number: int = 0,
    source_title: Optional[str] = None,
    source_path: Optional[str] = None,
    rights_basis: Optional[str] = None,
    rights_review_required: Optional[bool] = None,
    rights_review_status: Optional[str] = None,
    world_context: Any = None,
    world_context_provider: Any = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    provider_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the bounded adaptation handoff for an approved upload workspace.

    Inputs:
      * ``workspace``: the approved upload artifact workspace (project-relative
        or an absolute path inside the repository);
      * ``source_kind``: ``markdown`` or ``pdf`` (``upload_markdown`` /
        ``upload_pdf`` accepted and normalized deterministically);
      * ``source_rights_class``: the Python-owned upload rights classification
        (``user_authored``, ``licensed_or_project_owned``, or
        ``third_party_copyright_restricted``); packet/snapshot fields can never
        relabel it;
      * ``review_state``: the upload job state; only approved states proceed;
      * job/attempt/revision identity and optional read-only world context (a
        prebuilt pack/provenance mapping or a provider object with ``build()``).

    The normalized packet, source_original.md, persisted source manifest, and
    persisted source graph are loaded from the workspace and passed through
    the task 1.2 runtime envelope seam, which assembles the bounded source
    context via ``build_adaptation_source_context`` and canonical world-context
    provenance via ``build_world_context_provenance``.

    Returns a deterministic handoff mapping. ``status`` is ``ready`` only when
    every gate passed; otherwise it is ``failed_closed`` with bounded
    diagnostics and ``envelope`` is ``None``. This function never raises for
    bad input, never calls a provider, never invokes the module builder, and never
    reserves final staging/publication targets.
    """
    diagnostics: List[Dict[str, str]] = []
    fatal = False

    def _fail(code: str, message: str) -> None:
        nonlocal fatal
        fatal = True
        diagnostics.append(_error(code, message))

    # ---- Workspace resolution --------------------------------------------
    workspace_path: Optional[Path] = None
    workspace_rel = ""
    workspace_files = None
    resolved_workspace, workspace_rel, workspace_error = _resolve_upload_workspace(
        workspace
    )
    if workspace_error:
        _fail(workspace_error, "upload workspace is unavailable or unsafe")
    else:
        workspace_path = resolved_workspace
        try:
            workspace_files = get_workspace_files(workspace_path)
        except Exception:
            workspace_files = None
            _fail("workspace_invalid", "upload workspace files could not be resolved")

    # ---- Source kind normalization ---------------------------------------
    kind = ""
    source_kind_normalized = ""
    if isinstance(source_kind, str):
        candidate_kind = source_kind.strip().lower()
        if candidate_kind in {UPLOAD_SOURCE_KIND_MARKDOWN, INPUT_KIND_UPLOAD_MARKDOWN}:
            kind = INPUT_KIND_UPLOAD_MARKDOWN
            source_kind_normalized = UPLOAD_SOURCE_KIND_MARKDOWN
        elif candidate_kind in {UPLOAD_SOURCE_KIND_PDF, INPUT_KIND_UPLOAD_PDF}:
            kind = INPUT_KIND_UPLOAD_PDF
            source_kind_normalized = UPLOAD_SOURCE_KIND_PDF
    if not kind:
        _fail("unsupported_source_kind", "upload source kind must be markdown or pdf")

    # ---- Approval / review state -----------------------------------------
    review_state_normalized = str(review_state or "").strip().lower()
    approved = review_state_normalized in APPROVED_UPLOAD_REVIEW_STATES
    review_evidence = ""
    packet: Dict[str, Any] = {}
    if not approved:
        _fail("upload_not_approved", "upload workspace is not in an approved review state")
    elif workspace_files is not None:
        snapshot: Dict[str, Any] = {}
        try:
            raw_snapshot = load_json_artifact(workspace_files["ui_review_snapshot"])
            if isinstance(raw_snapshot, Mapping):
                snapshot = dict(raw_snapshot)
        except Exception:
            snapshot = {}
        snapshot_decision = str(snapshot.get("decision") or "").strip().lower()
        if snapshot_decision == REVIEW_DECISION_REJECT:
            _fail("upload_review_rejected", "upload workspace review rejected the source")
            review_evidence = "snapshot_reject"
        elif snapshot_decision == REVIEW_DECISION_APPROVE:
            review_evidence = "snapshot_approve"
        else:
            review_evidence = "supplied_review_state"
        snapshot_rights = snapshot.get("source_rights_class")
        if (
            snapshot_rights not in (None, "")
            and str(snapshot_rights).strip().lower() != str(source_rights_class or "").strip().lower()
        ):
            diagnostics.append(
                _warning(
                    "snapshot_rights_relabel_rejected",
                    "review snapshot rights class cannot relabel Python-owned rights",
                )
            )

        # ---- Normalized packet -------------------------------------------
        try:
            raw_packet = load_normalized_packet_artifact(workspace_path)
            if isinstance(raw_packet, Mapping):
                packet = dict(raw_packet)
        except Exception:
            packet = {}
        if not packet:
            _fail("packet_missing", "normalized packet artifact is missing or invalid")
        else:
            packet_valid, packet_error = validate_review_packet(dict(packet))
            if not packet_valid:
                _fail(
                    "packet_invalid",
                    "normalized packet is not build-ready: " + str(packet_error or "invalid"),
                )
            packet_rights = packet.get("source_rights_class")
            if (
                packet_rights not in (None, "")
                and str(packet_rights).strip().lower() != str(source_rights_class or "").strip().lower()
            ):
                diagnostics.append(
                    _warning(
                        "packet_rights_relabel_rejected",
                        "normalized packet rights class cannot relabel Python-owned rights",
                    )
                )

    # ---- Source file, size guard, and hash --------------------------------
    file_hash = ""
    raw_text = ""
    if not fatal and workspace_files is not None:
        source_file = workspace_files["source_original"]
        try:
            if not source_file.exists() or not source_file.is_file():
                _fail("source_original_missing", "upload source_original.md is unavailable")
            else:
                size_bytes = source_file.stat().st_size
                if size_bytes > MAX_UPLOAD_SOURCE_BYTES:
                    _fail("source_too_large", "upload source exceeds the accepted size bound")
                else:
                    file_hash = compute_sha256(source_file)
                    packet_hash = str(packet.get("source_hash") or "").strip().lower()
                    if packet_hash and file_hash and packet_hash != file_hash:
                        _fail(
                            "source_hash_mismatch",
                            "normalized packet source hash does not match the uploaded source",
                        )
                    try:
                        raw_text = source_file.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        _fail("raw_source_invalid_utf8", "upload source is not valid UTF-8")
                    except OSError:
                        _fail("source_unreadable", "upload source could not be read")
        except OSError:
            _fail("workspace_invalid", "upload workspace files could not be read")

    resolved_hash = file_hash or (
        str(packet.get("source_hash") or "").strip().lower()
        if isinstance(packet, Mapping)
        else ""
    )

    # ---- Python-owned rights ----------------------------------------------
    rights_class = ""
    if isinstance(source_rights_class, str):
        rights_class = source_rights_class.strip().lower()
    if rights_class not in VALID_SOURCE_RIGHTS_CLASSES:
        _fail("source_rights_class_invalid", "supplied upload rights classification is unsupported")

    rights_basis_resolved = ""
    review_required_resolved: Optional[bool] = None
    review_status_resolved = ""
    if not fatal:
        rights_basis_resolved = (
            rights_basis.strip()
            if isinstance(rights_basis, str) and rights_basis.strip()
            else UPLOAD_RIGHTS_BASIS_BY_CLASS.get(rights_class, "uploaded_adventure")
        )
        review_required_resolved = (
            rights_review_required
            if rights_review_required is not None
            else rights_class == SOURCE_RIGHTS_RESTRICTED
        )
        review_status_resolved = (
            rights_review_status
            if rights_review_status is not None
            else (
                RIGHTS_REVIEW_PENDING
                if rights_class == SOURCE_RIGHTS_RESTRICTED
                else RIGHTS_REVIEW_NOT_REQUIRED
            )
        )

    # ---- Optional read-only world context ---------------------------------
    world_provenance = build_world_context_provenance(None)
    world_evidence = "unavailable"
    if world_context is not None:
        world_provenance = build_world_context_provenance(world_context)
        world_evidence = "supplied_context"
    elif world_context_provider is not None:
        try:
            provider = world_context_provider
            pack = provider.build() if hasattr(provider, "build") else provider()
            if not isinstance(pack, Mapping):
                raise TypeError("world context provider returned a non-object")
            world_provenance = build_world_context_provenance(pack)
            world_evidence = "provider"
        except Exception:
            world_provenance = build_world_context_provenance(None)
            diagnostics.append(
                _warning(
                    "world_context_unavailable",
                    "world context provider failed; explicit unavailable fallback used",
                )
            )
            world_evidence = "provider_failed"

    # ---- Advisory source material from the workspace ----------------------
    manifest: Optional[Mapping[str, Any]] = None
    graph: Optional[Mapping[str, Any]] = None
    if not fatal and workspace_path is not None:
        try:
            loaded_manifest = load_source_manifest_artifact(workspace_path)
            if isinstance(loaded_manifest, Mapping) and loaded_manifest:
                manifest = loaded_manifest
        except Exception:
            manifest = None
        try:
            loaded_graph = load_source_graph_artifact(workspace_path)
            if isinstance(loaded_graph, Mapping) and loaded_graph:
                graph = loaded_graph
        except Exception:
            graph = None

    title = ""
    if isinstance(source_title, str) and source_title.strip():
        title = source_title.strip()
    elif isinstance(packet.get("title"), str) and packet.get("title", "").strip():
        title = str(packet.get("title") or "").strip()

    summary = ""
    if isinstance(packet.get("adventure_summary"), str) and packet.get("adventure_summary", "").strip():
        summary = str(packet.get("adventure_summary") or "").strip()
    elif isinstance(packet.get("description"), str) and packet.get("description", "").strip():
        summary = str(packet.get("description") or "").strip()

    source_path_value = ""
    if isinstance(source_path, str) and source_path.strip():
        source_path_value = source_path.strip()
    elif workspace_rel:
        source_path_value = workspace_rel + "/source_original.md"

    # ---- Assemble through the task 1.2 envelope seam ----------------------
    envelope: Dict[str, Any] = {}
    if not fatal:
        envelope = build_adaptation_runtime_envelope(
            kind,
            source_text=raw_text,
            source_title=title,
            source_hash=resolved_hash or None,
            source_path=source_path_value,
            source_summary=summary,
            source_manifest=manifest,
            normalized_packet=dict(packet) if packet else None,
            source_graph=graph,
            rights_class=rights_class,
            rights_basis=rights_basis_resolved,
            rights_review_required=review_required_resolved,
            rights_review_status=review_status_resolved,
            job_id=job_id,
            attempt_number=attempt_number,
            attempt_id=attempt_id,
            revision_number=revision_number,
            world_context=world_provenance,
            model_metadata=model_metadata,
            provider_metadata=provider_metadata,
        )
        if envelope.get("status") != ENVELOPE_STATUS_READY:
            fatal = True
            for item in envelope.get("diagnostics", []):
                if isinstance(item, Mapping):
                    diagnostics.append(
                        _diagnostic(
                            str(item.get("code") or "envelope_invalid"),
                            str(item.get("message") or "runtime envelope is invalid"),
                            str(item.get("severity") or DIAGNOSTIC_SEVERITY_ERROR),
                        )
                    )
            envelope = {}

    # ---- Identity preservation evidence -----------------------------------
    packet_identity: Dict[str, Any] = {}
    if isinstance(packet, Mapping) and packet:
        packet_identity = {
            "packet_version": str(packet.get("packet_version") or ""),
            "normalization_state": str(packet.get("normalization_state") or ""),
            "title": str(packet.get("title") or ""),
            "source_hash": str(packet.get("source_hash") or "").strip().lower(),
        }
    packet_hash_preserved = False
    rights_preserved = False
    if not fatal:
        envelope_hash = str(envelope.get("source_identity", {}).get("source_hash") or "")
        packet_hash_preserved = bool(
            packet_identity.get("source_hash")
            and packet_identity["source_hash"] == file_hash
            and envelope_hash == file_hash
        )
        envelope_rights_class = str(envelope.get("rights", {}).get("rights_class") or "")
        rights_preserved = envelope_rights_class == rights_class

    handoff: Dict[str, Any] = {
        "contract_version": UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION,
        "status": HANDOFF_STATUS_READY if not fatal else HANDOFF_STATUS_FAILED_CLOSED,
        "input_kind": kind,
        "source_kind": source_kind_normalized,
        "upload_evidence": {
            "workspace": workspace_rel,
            "review_state": review_state_normalized,
            "review_evidence": review_evidence,
            "approved": approved,
            "packet_identity": packet_identity,
            "packet_source_hash_preserved": packet_hash_preserved,
            "source_rights_preserved": rights_preserved,
            "world_context_status": str(world_provenance.get("context_status") or ""),
            "world_context_fallback_status": str(world_provenance.get("fallback_status") or ""),
        },
        "world_context": world_provenance,
        "world_context_evidence": world_evidence,
        "envelope": envelope if not fatal else None,
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }
    return handoff


def serialize_upload_adaptation_handoff(handoff: Mapping[str, Any]) -> str:
    """Return deterministic canonical JSON for an upload handoff."""
    if not isinstance(handoff, Mapping):
        raise ValueError("upload adaptation handoff must be an object")
    encoded = _canonical_json(handoff)
    if len(encoded) > MAX_HANDOFF_SERIALIZED_CHARS:
        raise ValueError("upload adaptation handoff exceeds its serialized bound")
    return encoded


def validate_upload_adaptation_handoff(value: Any) -> Dict[str, Any]:
    """Validate an upload handoff round trip and its ready-state contract."""
    diagnostics: List[str] = []
    if not isinstance(value, Mapping):
        return {
            "valid": False,
            "status": HANDOFF_STATUS_FAILED_CLOSED,
            "diagnostics": ["handoff_must_be_object"],
            "handoff": None,
        }
    if value.get("contract_version") != UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    status = value.get("status")
    if status not in {HANDOFF_STATUS_READY, HANDOFF_STATUS_FAILED_CLOSED}:
        diagnostics.append("status_invalid")
    if value.get("source_kind") not in VALID_UPLOAD_SOURCE_KINDS:
        diagnostics.append("source_kind_invalid")

    world = value.get("world_context")
    if not isinstance(world, Mapping):
        diagnostics.append("world_context_missing")
    elif build_world_context_provenance(world) != dict(world):
        diagnostics.append("world_context_not_canonical")

    evidence = value.get("upload_evidence")
    if not isinstance(evidence, Mapping):
        diagnostics.append("upload_evidence_missing")

    if status == HANDOFF_STATUS_READY:
        if value.get("input_kind") not in {INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF}:
            diagnostics.append("input_kind_invalid")
        envelope = value.get("envelope")
        if not isinstance(envelope, Mapping):
            diagnostics.append("envelope_missing")
        else:
            envelope_result = validate_adaptation_runtime_envelope(envelope)
            if not envelope_result.get("valid"):
                diagnostics.append("envelope_invalid")
        if not isinstance(evidence, Mapping):
            diagnostics.append("upload_evidence_missing")
        elif evidence.get("packet_source_hash_preserved") is not True:
            diagnostics.append("packet_source_hash_not_preserved")
        elif evidence.get("source_rights_preserved") is not True:
            diagnostics.append("source_rights_not_preserved")
        elif evidence.get("approved") is not True:
            diagnostics.append("handoff_not_approved")
    else:
        if value.get("envelope") is not None:
            diagnostics.append("failed_closed_handoff_has_envelope")
        items = value.get("diagnostics")
        if not isinstance(items, list) or not items:
            diagnostics.append("failed_closed_handoff_missing_diagnostics")

    _walk_unsafe_keys(value, diagnostics)
    _walk_unsafe_paths(value, diagnostics)
    try:
        encoded = _canonical_json(value)
        if len(encoded) > MAX_HANDOFF_SERIALIZED_CHARS:
            diagnostics.append("handoff_too_large")
        if _SCAN_OPENAI_KEY_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_BEARER_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_CREDENTIAL_RE.search(encoded):
            diagnostics.append("credential_value_present")
    except (TypeError, ValueError):
        diagnostics.append("handoff_not_serializable")

    resolved_status = (
        HANDOFF_STATUS_READY if not diagnostics else HANDOFF_STATUS_FAILED_CLOSED
    )
    if not diagnostics and value.get("status") == HANDOFF_STATUS_FAILED_CLOSED:
        # A failed-closed handoff that satisfies its own contract is still a
        # failed-closed handoff; the validator mirrors the handoff's status.
        resolved_status = HANDOFF_STATUS_FAILED_CLOSED

    return {
        "valid": not diagnostics,
        "status": resolved_status,
        "diagnostics": diagnostics[: MAX_DIAGNOSTICS * 4],
        "handoff": deepcopy(dict(value)) if not diagnostics else None,
    }


# ---------------------------------------------------------------------------
# Task 2.2 - Minimal text-description attempt workspace
#
# Python-owned adapter that converts a valid text-description build request
# into an attempt-scoped, project-relative workspace containing only the
# bounded concept input and the minimum normalized packet/metadata required by
# the existing adaptation packet builder. The enabled path never writes
# directly to ``modules/<name>``: provisional module output belongs to the
# reserved adaptation staging target, and this helper only *references* the
# deterministic (unreserved) staging path so later stages can reserve it.
#
# The concept is classified as Python-owned ``user_authored`` rights with a
# stable lowercase SHA-256 source identity, the task 1.2 bounded runtime
# envelope is assembled through the shared seam, and bounded artifacts are
# persisted atomically under the attempt workspace. The helper never calls a
# provider, never runs the module build pipeline, never reserves or writes the final
# staging target, and never touches modules/, the registry, campaign, or
# runtime state. Invalid input, unsafe paths, an existing workspace, and
# write/serialization failures fail closed with bounded diagnostics.
# ---------------------------------------------------------------------------

TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION = (
    "toolkit_text_description_attempt_workspace.v1"
)
TEXT_DESCRIPTION_WORKSPACE_STATUS_READY = "ready"
TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED = "failed_closed"

# Project-relative scratch root for text-description attempt workspaces. The
# default never points at modules/, characters/, data/, or any OS temp root.
DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT = "tmp/toolkit-text-workspaces"
MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS = 48_000

CONCEPT_SOURCE_FILENAME = "source_original.md"
BUILDER_NARRATIVE_FILENAME = "builder_narrative.txt"
NORMALIZED_PACKET_FILENAME = "normalized_packet.json"
REVIEW_SNAPSHOT_FILENAME = "ui_review_snapshot.json"
ATTEMPT_METADATA_FILENAME = "attempt_metadata.json"
RUNTIME_ENVELOPE_FILENAME = "runtime_envelope.json"
WORKSPACE_MANIFEST_FILENAME = "workspace_manifest.json"

TEXT_DESCRIPTION_CLASSIFIED_BY = "python"
TEXT_DESCRIPTION_SOURCE_KIND = "text_description"
TEXT_DESCRIPTION_WORKSPACE_NORMALIZATION_STATE = "normalized"


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp for attempt metadata."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _repo_root_value(repo_root: Optional[Path]) -> Path:
    """Resolve the trusted project root used for derived workspace paths."""
    if repo_root is None:
        return Path(__file__).resolve().parents[2]
    return Path(repo_root).resolve()


def _is_within_path(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is equal to or below ``parent``."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_scratch_root(scratch_root: Any, repo_root: Path) -> Tuple[Path, str]:
    """Validate a project-relative workspace root outside live runtime roots.

    Returns ``(absolute_root, relative_posix)`` or raises ``ValueError``.
    The scratch root must be project-relative and must not live inside
    ``modules/``, ``characters/``, or ``data/`` so an attempt workspace can
    never shadow a live module or runtime directory.
    """
    relative, unsafe = _safe_project_relative_path(scratch_root)
    if relative is None or unsafe:
        raise ValueError("scratch root must be project-relative")
    root = repo_root.joinpath(*PurePosixPath(relative).parts).resolve()
    if not _is_within_path(root, repo_root):
        raise ValueError("scratch root resolves outside the project")
    for forbidden in ("modules", "characters", "data"):
        if _is_within_path(root, (repo_root / forbidden).resolve()):
            raise ValueError(f"scratch root cannot be inside {forbidden}")
    return root, relative


def _failed_workspace_result(diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    """Return a deterministic fail-closed workspace result."""
    return {
        "contract_version": TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION,
        "status": TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED,
        "input_kind": INPUT_KIND_TEXT_DESCRIPTION,
        "source_kind": TEXT_DESCRIPTION_SOURCE_KIND,
        "workspace": None,
        "packet_metadata": None,
        "attempt": None,
        "source_identity": None,
        "rights": None,
        "world_context": build_world_context_provenance(None),
        "world_context_status": "unavailable",
        "world_context_fallback_status": "unavailable",
        "world_context_evidence": "unavailable",
        "envelope": None,
        "output": {
            "published_to_modules": False,
            "direct_module_write_required": False,
            "staging_reserved": False,
        },
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }


def build_text_description_attempt_workspace(
    module_name: str,
    concept: Any,
    *,
    job_id: str = "",
    attempt_number: int = 1,
    attempt_id: Optional[str] = None,
    revision_number: int = 0,
    source_title: Optional[str] = None,
    world_context: Any = None,
    world_context_provider: Any = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    provider_metadata: Optional[Mapping[str, Any]] = None,
    workspace_root: str = DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT,
    staging_root: str = DEFAULT_ADAPTATION_STAGING_ROOT,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the minimal attempt workspace for a text-description build request.

    Inputs:
      * ``module_name``: path-safe module slug (``^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$``);
      * ``concept``: non-empty bounded narrative/concept text or UTF-8 bytes;
      * job/attempt/revision identity and optional read-only world context (a
        prebuilt provenance pack or a provider object with ``build()``);
      * ``workspace_root`` / ``staging_root``: project-relative scratch roots
        (never inside modules/, characters/, or data/).

    The helper computes the stable lowercase SHA-256 concept identity, derives
    the attempt identity, assembles the task 1.2 bounded runtime envelope,
    persists the bounded concept and the minimum normalized packet/review
    snapshot/builder-narrative artifacts, and returns a deterministic handoff.
    The enabled path writes nothing under ``modules/<name>``: ``output``
    references the deterministic (unreserved) adaptation staging target.

    Returns a ``status=ready`` manifest, or ``status=failed_closed`` with
    bounded diagnostics and no workspace. This function never raises for bad
    input, never calls a provider, never runs the module build pipeline, and never
    reserves or writes the final staging target.
    """
    diagnostics: List[Dict[str, str]] = []
    fatal = False

    def _fail(code: str, message: str) -> None:
        nonlocal fatal
        fatal = True
        diagnostics.append(_error(code, message))

    # ---- Path-safe module name --------------------------------------------
    safe_module_name = ""
    if isinstance(module_name, str):
        candidate = module_name.strip()
        if _MODULE_SLUG_RE.fullmatch(candidate):
            safe_module_name = candidate
        else:
            _fail("module_name_invalid", "module name is not path-safe")
    else:
        _fail("module_name_invalid", "module name is required")

    # ---- Bounded non-empty concept ----------------------------------------
    raw_concept = ""
    if concept is None:
        _fail("concept_empty", "text description concept is required")
    elif isinstance(concept, bytes):
        try:
            raw_concept = concept.decode("utf-8")
        except UnicodeDecodeError:
            _fail("concept_invalid_utf8", "concept is not valid UTF-8")
    elif isinstance(concept, str):
        raw_concept = concept
    else:
        _fail("concept_invalid_type", "concept must be text or UTF-8 bytes")
    if not fatal:
        if not raw_concept.strip():
            _fail("concept_empty", "text description concept is required")
        elif len(raw_concept) > MAX_TEXT_DESCRIPTION_CHARS:
            _fail("concept_oversized", "concept exceeds the bounded description length")

    # ---- Job / attempt / revision identity --------------------------------
    safe_job_id = ""
    if job_id is None or job_id == "":
        safe_job_id = ""
    elif isinstance(job_id, str):
        safe_job_id, _, _ = _ascii_text(job_id.strip(), MAX_JOB_ID_CHARS)
    else:
        _fail("job_id_invalid", "job_id must be text")

    attempt_number_valid = (
        not isinstance(attempt_number, bool)
        and isinstance(attempt_number, int)
        and 1 <= attempt_number <= 1_000_000
    )
    if not attempt_number_valid:
        _fail("attempt_number_invalid", "attempt_number is outside the supported range")
    revision_number_valid = (
        not isinstance(revision_number, bool)
        and isinstance(revision_number, int)
        and 0 <= revision_number <= 100
    )
    if not revision_number_valid:
        _fail("revision_number_invalid", "revision_number is outside the supported range")

    if fatal:
        return _failed_workspace_result(diagnostics)

    # ---- Stable source identity and attempt identity ----------------------
    concept_text = raw_concept
    source_hash = hashlib.sha256(concept_text.encode("utf-8")).hexdigest()

    resolved_attempt_id = ""
    if attempt_id is not None:
        if _is_safe_attempt_id(attempt_id):
            resolved_attempt_id = attempt_id
        else:
            _fail("attempt_id_invalid", "attempt_id is not path-safe")
    derived_attempt_id = ""
    try:
        derived_attempt_id = build_attempt_id(
            source_hash,
            attempt_number if attempt_number_valid else 1,
            safe_job_id,
        )
    except Exception:
        _fail("attempt_identity_failed", "attempt identity could not be created")
    if not resolved_attempt_id and derived_attempt_id:
        resolved_attempt_id = derived_attempt_id
    if (
        attempt_id is not None
        and _is_safe_attempt_id(attempt_id)
        and derived_attempt_id
        and attempt_id != derived_attempt_id
    ):
        _fail("attempt_id_mismatch", "attempt_id does not match the concept identity")

    # ---- Project-relative scratch roots -----------------------------------
    repo_root_path = _repo_root_value(repo_root)
    workspace_root_path: Optional[Path] = None
    workspace_root_rel = ""
    if not fatal:
        try:
            workspace_root_path, workspace_root_rel = _validate_scratch_root(
                workspace_root, repo_root_path
            )
        except Exception as exc:
            _fail("workspace_root_unsafe", "workspace root is unsafe: " + str(exc))
    staging_root_rel = ""
    staging_root_unsafe = False
    if not fatal:
        staging_root_rel, staging_root_unsafe = _safe_project_relative_path(staging_root)
        if staging_root_unsafe:
            _fail("staging_root_unsafe", "staging root must be project-relative")

    # ---- Deterministic (unreserved) staging target ------------------------
    staging_target_path = ""
    if not fatal:
        try:
            staging_target_abs = get_adaptation_staging_target_path(
                source_hash=source_hash,
                attempt_id=resolved_attempt_id or None,
                attempt_number=attempt_number if attempt_number_valid else 1,
                revision_number=revision_number if revision_number_valid else 0,
                job_id=safe_job_id,
                staging_root=staging_root,
                repo_root=repo_root_path,
            )
            staging_target_path = staging_target_abs.relative_to(repo_root_path).as_posix()
        except Exception as exc:
            _fail("staging_target_invalid", "adaptation staging target is invalid: " + str(exc))

    # ---- Attempt workspace relative path ----------------------------------
    workspace_rel = ""
    if not fatal:
        workspace_rel = PurePosixPath(workspace_root_rel, resolved_attempt_id).as_posix()
        relative_check, unsafe_check = _safe_project_relative_path(workspace_rel)
        if unsafe_check or relative_check is None:
            _fail("workspace_path_unsafe", "attempt workspace path is not project-relative")

    if fatal:
        return _failed_workspace_result(diagnostics)

    # ---- Python-owned rights for text descriptions ------------------------
    rights_map: Dict[str, Any] = {
        "rights_class": RIGHTS_CLASS_USER_AUTHORED,
        "rights_basis": TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS,
        "rights_review_required": False,
        "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
    }

    # ---- Read-only world-context provenance -------------------------------
    world_provenance = build_world_context_provenance(None)
    world_evidence = "unavailable"
    if world_context is not None:
        world_provenance = build_world_context_provenance(world_context)
        world_evidence = "supplied_context"
    elif world_context_provider is not None:
        try:
            provider = world_context_provider
            pack = provider.build() if hasattr(provider, "build") else provider()
            if not isinstance(pack, Mapping):
                raise TypeError("world context provider returned a non-object")
            world_provenance = build_world_context_provenance(pack)
            world_evidence = "provider"
        except Exception:
            world_provenance = build_world_context_provenance(None)
            diagnostics.append(
                _warning(
                    "world_context_unavailable",
                    "world context provider failed; explicit unavailable fallback used",
                )
            )
            world_evidence = "provider_failed"

    # ---- Bounded narrative title ------------------------------------------
    title = safe_module_name
    if isinstance(source_title, str) and source_title.strip():
        bounded_title, _, _ = _ascii_text(source_title.strip(), MAX_SOURCE_TITLE_CHARS)
        if bounded_title:
            title = bounded_title

    # ---- Task 1.2 bounded runtime envelope --------------------------------
    envelope: Dict[str, Any] = {}
    if not fatal:
        envelope = build_adaptation_runtime_envelope(
            INPUT_KIND_TEXT_DESCRIPTION,
            source_text=concept_text,
            source_title=title,
            source_hash=source_hash,
            source_path=workspace_rel + "/" + CONCEPT_SOURCE_FILENAME,
            rights_class=rights_map["rights_class"],
            rights_basis=rights_map["rights_basis"],
            rights_review_required=rights_map["rights_review_required"],
            rights_review_status=rights_map["rights_review_status"],
            job_id=safe_job_id,
            attempt_number=attempt_number if attempt_number_valid else 1,
            attempt_id=resolved_attempt_id or None,
            revision_number=revision_number if revision_number_valid else 0,
            world_context=world_provenance,
            model_metadata=model_metadata,
            provider_metadata=provider_metadata,
        )
        if envelope.get("status") != ENVELOPE_STATUS_READY:
            fatal = True
            for item in envelope.get("diagnostics", []):
                if isinstance(item, Mapping):
                    diagnostics.append(
                        _diagnostic(
                            str(item.get("code") or "envelope_invalid"),
                            str(item.get("message") or "runtime envelope is invalid"),
                            str(item.get("severity") or DIAGNOSTIC_SEVERITY_ERROR),
                        )
                    )
            envelope = {}

    # ---- Minimum normalized packet metadata -------------------------------
    packet: Dict[str, Any] = {}
    if not fatal:
        packet = {
            "packet_version": PACKET_CONTRACT_VERSION,
            "normalization_state": TEXT_DESCRIPTION_WORKSPACE_NORMALIZATION_STATE,
            "source_path": workspace_rel + "/" + CONCEPT_SOURCE_FILENAME,
            "source_hash": source_hash,
            "title": safe_module_name,
            "author": "",
            "description": "",
            "adventure_summary": "",
            "module_tone": "",
            "acts": [],
            "locations": [],
            "connectivity_hints": [],
            "encounter_seeds": [],
            "npc_seeds": [],
            "monster_refs": [],
            "plot_progression": [],
            "continuity_hints": [],
            "media_hints": [],
            "assumptions": [
                "Text-description concept for the LLM adaptation lane; "
                "bounded concept material lives in the attempt workspace."
            ],
            "warnings": [],
            "source_rights_class": RIGHTS_CLASS_USER_AUTHORED,
        }
        packet_ok, packet_error = validate_review_packet(packet)
        if not packet_ok:
            _fail("packet_invalid", "minimum normalized packet is not reviewable: " + str(packet_error))

    if fatal:
        return _failed_workspace_result(diagnostics)

    snapshot = build_review_snapshot(
        job_id=safe_job_id or "text-description",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=RIGHTS_CLASS_USER_AUTHORED,
    )

    attempt_metadata: Dict[str, Any] = {
        "contract_version": TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION,
        "status": TEXT_DESCRIPTION_WORKSPACE_STATUS_READY,
        "input_kind": INPUT_KIND_TEXT_DESCRIPTION,
        "source_kind": TEXT_DESCRIPTION_SOURCE_KIND,
        "module_name": safe_module_name,
        "title": title,
        "source_hash": source_hash,
        "source_hash_provenance": "explicit_argument",
        "attempt": {
            "attempt_id": resolved_attempt_id,
            "attempt_number": attempt_number if attempt_number_valid else 1,
            "revision_number": revision_number if revision_number_valid else 0,
            "job_id": safe_job_id or None,
        },
        "rights": rights_map,
        "world_context": world_provenance,
        "world_context_status": str(world_provenance.get("context_status") or ""),
        "world_context_fallback_status": str(world_provenance.get("fallback_status") or ""),
        "world_context_evidence": world_evidence,
        "classified_by": TEXT_DESCRIPTION_CLASSIFIED_BY,
        "concept_chars": len(concept_text),
        "concept_bounded": True,
        "created_at": _utc_now_iso(),
    }

    manifest: Dict[str, Any] = {
        "contract_version": TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION,
        "status": TEXT_DESCRIPTION_WORKSPACE_STATUS_READY,
        "input_kind": INPUT_KIND_TEXT_DESCRIPTION,
        "source_kind": TEXT_DESCRIPTION_SOURCE_KIND,
        "workspace": {
            "path": workspace_rel,
            "created": True,
            "files": {
                "concept_source": workspace_rel + "/" + CONCEPT_SOURCE_FILENAME,
                "builder_narrative": workspace_rel + "/" + BUILDER_NARRATIVE_FILENAME,
                "normalized_packet": workspace_rel + "/" + NORMALIZED_PACKET_FILENAME,
                "review_snapshot": workspace_rel + "/" + REVIEW_SNAPSHOT_FILENAME,
                "attempt_metadata": workspace_rel + "/" + ATTEMPT_METADATA_FILENAME,
                "runtime_envelope": workspace_rel + "/" + RUNTIME_ENVELOPE_FILENAME,
                "workspace_manifest": workspace_rel + "/" + WORKSPACE_MANIFEST_FILENAME,
            },
        },
        "packet_metadata": {
            "packet_version": str(packet.get("packet_version") or ""),
            "normalization_state": str(packet.get("normalization_state") or ""),
            "module_name": safe_module_name,
            "title": title,
            "source_hash": source_hash,
            "source_hash_provenance": "explicit_argument",
            "source_rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS,
            "rights_review_required": False,
            "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
            "classified_by": TEXT_DESCRIPTION_CLASSIFIED_BY,
            "review_decision": REVIEW_DECISION_APPROVE,
            "workspace_review_approved": True,
            "concept_chars": len(concept_text),
            "concept_bounded": True,
        },
        "attempt": {
            "attempt_id": resolved_attempt_id,
            "attempt_number": attempt_number if attempt_number_valid else 1,
            "revision_number": revision_number if revision_number_valid else 0,
            "job_id": safe_job_id or None,
        },
        "source_identity": {
            "source_title": title,
            "source_hash": source_hash,
            "source_hash_provenance": "explicit_argument",
            "source_kind": TEXT_DESCRIPTION_SOURCE_KIND,
            "source_path": workspace_rel + "/" + CONCEPT_SOURCE_FILENAME,
        },
        "rights": {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS,
            "rights_review_required": False,
            "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
            "python_owned": True,
            "classified_by": TEXT_DESCRIPTION_CLASSIFIED_BY,
            "provider_may_change": False,
        },
        "world_context": world_provenance,
        "world_context_status": str(world_provenance.get("context_status") or ""),
        "world_context_fallback_status": str(world_provenance.get("fallback_status") or ""),
        "world_context_evidence": world_evidence,
        "envelope": envelope,
        "output": {
            "published_to_modules": False,
            "direct_module_write_required": False,
            "staging_root": staging_root_rel or "",
            "staging_target_path": staging_target_path or "",
            "staging_reserved": False,
            "module_name": safe_module_name,
        },
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }

    # ---- Persist bounded artifacts atomically -----------------------------
    workspace_path = repo_root_path.joinpath(*PurePosixPath(workspace_rel).parts)
    if workspace_path.exists():
        _fail(
            "workspace_exists",
            "attempt workspace already exists for this attempt and revision",
        )
        return _failed_workspace_result(diagnostics)
    try:
        workspace_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _fail(
            "workspace_exists",
            "attempt workspace already exists for this attempt and revision",
        )
        return _failed_workspace_result(diagnostics)
    except Exception:
        _fail("workspace_persist_failed", "attempt workspace could not be created")
        return _failed_workspace_result(diagnostics)

    try:
        (workspace_path / CONCEPT_SOURCE_FILENAME).write_text(concept_text, encoding="utf-8")
        (workspace_path / BUILDER_NARRATIVE_FILENAME).write_text(concept_text, encoding="utf-8")
        if not safe_write_json(
            str(workspace_path / NORMALIZED_PACKET_FILENAME), packet, create_backup=False
        ):
            raise OSError("normalized packet write failed")
        if not safe_write_json(
            str(workspace_path / REVIEW_SNAPSHOT_FILENAME), snapshot, create_backup=False
        ):
            raise OSError("review snapshot write failed")
        if not safe_write_json(
            str(workspace_path / ATTEMPT_METADATA_FILENAME),
            attempt_metadata,
            create_backup=False,
        ):
            raise OSError("attempt metadata write failed")
        if not safe_write_json(
            str(workspace_path / RUNTIME_ENVELOPE_FILENAME), envelope, create_backup=False
        ):
            raise OSError("runtime envelope write failed")
        # The manifest is validated and bounded before its own write.
        manifest_serialized = serialize_text_description_attempt_workspace(manifest)
        if not safe_write_json(
            str(workspace_path / WORKSPACE_MANIFEST_FILENAME),
            json.loads(manifest_serialized),
            create_backup=False,
        ):
            raise OSError("workspace manifest write failed")
    except Exception:
        # Only remove the attempt directory created by this call. Never walk
        # up to the scratch root or any live module path.
        shutil.rmtree(workspace_path, ignore_errors=True)
        _fail("workspace_persist_failed", "attempt workspace artifacts could not be persisted")
        return _failed_workspace_result(diagnostics)

    return manifest


def serialize_text_description_attempt_workspace(manifest: Mapping[str, Any]) -> str:
    """Return deterministic canonical JSON for an attempt workspace manifest."""
    if not isinstance(manifest, Mapping):
        raise ValueError("text description attempt workspace must be an object")
    encoded = _canonical_json(manifest)
    if len(encoded) > MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS:
        raise ValueError("text description attempt workspace exceeds its serialized bound")
    return encoded


def validate_text_description_attempt_workspace(value: Any) -> Dict[str, Any]:
    """Validate an attempt workspace manifest round trip.

    A ready manifest must preserve the path-safe module name, stable source
    hash, Python-owned ``user_authored`` rights, attempt identity, canonical
    world-context provenance, the valid bounded runtime envelope, and an
    isolated output target that never claims direct module publication. A
    failed-closed manifest only needs its bounded diagnostics and no envelope.
    """
    diagnostics: List[str] = []
    if not isinstance(value, Mapping):
        return {
            "valid": False,
            "status": TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED,
            "diagnostics": ["workspace_must_be_object"],
            "workspace": None,
        }
    if value.get("contract_version") != TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    status = value.get("status")
    if status not in {
        TEXT_DESCRIPTION_WORKSPACE_STATUS_READY,
        TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED,
    }:
        diagnostics.append("status_invalid")
    if value.get("input_kind") != INPUT_KIND_TEXT_DESCRIPTION:
        diagnostics.append("input_kind_invalid")
    if value.get("source_kind") != TEXT_DESCRIPTION_SOURCE_KIND:
        diagnostics.append("source_kind_invalid")

    is_ready = status == TEXT_DESCRIPTION_WORKSPACE_STATUS_READY
    if not is_ready:
        if value.get("envelope") is not None:
            diagnostics.append("failed_closed_workspace_has_envelope")
        items = value.get("diagnostics")
        if not isinstance(items, list) or not items:
            diagnostics.append("failed_closed_workspace_missing_diagnostics")
    else:
        packet_metadata = value.get("packet_metadata")
        if not isinstance(packet_metadata, Mapping):
            diagnostics.append("packet_metadata_missing")
        else:
            module_name = packet_metadata.get("module_name")
            if not isinstance(module_name, str) or not _MODULE_SLUG_RE.fullmatch(module_name):
                diagnostics.append("module_name_invalid")
            if not _is_sha256(packet_metadata.get("source_hash")):
                diagnostics.append("source_hash_invalid")
            if packet_metadata.get("source_rights_class") != RIGHTS_CLASS_USER_AUTHORED:
                diagnostics.append("rights_class_invalid")
            if packet_metadata.get("classified_by") != TEXT_DESCRIPTION_CLASSIFIED_BY:
                diagnostics.append("rights_not_python_classified")
            if packet_metadata.get("workspace_review_approved") is not True:
                diagnostics.append("workspace_review_not_approved")
            if packet_metadata.get("concept_bounded") is not True:
                diagnostics.append("concept_not_bounded")
            if (
                packet_metadata.get("normalization_state")
                != TEXT_DESCRIPTION_WORKSPACE_NORMALIZATION_STATE
            ):
                diagnostics.append("normalization_state_invalid")

        attempt = value.get("attempt")
        if not isinstance(attempt, Mapping):
            diagnostics.append("attempt_missing")
        else:
            if not _is_safe_attempt_id(attempt.get("attempt_id")):
                diagnostics.append("attempt_id_invalid")
            attempt_number = attempt.get("attempt_number")
            if (
                isinstance(attempt_number, bool)
                or not isinstance(attempt_number, int)
                or not 1 <= attempt_number <= 1_000_000
            ):
                diagnostics.append("attempt_number_invalid")
            revision_number = attempt.get("revision_number")
            if (
                isinstance(revision_number, bool)
                or not isinstance(revision_number, int)
                or not 0 <= revision_number <= 100
            ):
                diagnostics.append("revision_number_invalid")
            job_id = attempt.get("job_id")
            if job_id is not None and (
                not isinstance(job_id, str) or len(job_id) > MAX_JOB_ID_CHARS
            ):
                diagnostics.append("job_id_invalid")
            source_hash = (packet_metadata or {}).get("source_hash")
            if (
                _is_safe_attempt_id(attempt.get("attempt_id"))
                and _is_sha256(source_hash)
                and isinstance(attempt_number, int)
                and not isinstance(attempt_number, bool)
            ):
                try:
                    derived = build_attempt_id(
                        source_hash,
                        attempt_number,
                        str(job_id or ""),
                    )
                except Exception:
                    derived = None
                if derived and derived != attempt.get("attempt_id"):
                    diagnostics.append("attempt_id_mismatch")

        source_identity = value.get("source_identity")
        if not isinstance(source_identity, Mapping):
            diagnostics.append("source_identity_missing")
        else:
            if not _is_sha256(source_identity.get("source_hash")):
                diagnostics.append("source_hash_invalid")
            if source_identity.get("source_kind") != TEXT_DESCRIPTION_SOURCE_KIND:
                diagnostics.append("source_kind_invalid")
            source_path = source_identity.get("source_path")
            if source_path is not None:
                relative_path, unsafe_path = _safe_project_relative_path(source_path)
                if unsafe_path:
                    diagnostics.append("source_path_unsafe")

        rights = value.get("rights")
        if not isinstance(rights, Mapping):
            diagnostics.append("rights_missing")
        else:
            if rights.get("rights_class") != RIGHTS_CLASS_USER_AUTHORED:
                diagnostics.append("rights_class_invalid")
            if rights.get("python_owned") is not True:
                diagnostics.append("rights_not_python_owned")
            if rights.get("classified_by") != TEXT_DESCRIPTION_CLASSIFIED_BY:
                diagnostics.append("rights_not_python_classified")
            if rights.get("provider_may_change") is not False:
                diagnostics.append("rights_provider_policy_invalid")
            if rights.get("rights_review_required") is not False:
                diagnostics.append("rights_review_invalid")
            if rights.get("rights_review_status") != RIGHTS_REVIEW_NOT_REQUIRED:
                diagnostics.append("rights_review_status_invalid")

        world = value.get("world_context")
        if not isinstance(world, Mapping):
            diagnostics.append("world_context_missing")
        elif build_world_context_provenance(world) != dict(world):
            diagnostics.append("world_context_not_canonical")

        workspace = value.get("workspace")
        if not isinstance(workspace, Mapping):
            diagnostics.append("workspace_missing")
        else:
            workspace_path = workspace.get("path")
            relative_path, unsafe_path = _safe_project_relative_path(workspace_path)
            if unsafe_path:
                diagnostics.append("workspace_path_unsafe")
            if isinstance(workspace_path, str) and not workspace_path.startswith("tmp/"):
                diagnostics.append("workspace_not_project_relative")
            files = workspace.get("files")
            if not isinstance(files, Mapping) or not files:
                diagnostics.append("workspace_files_missing")
            else:
                for key, file_path in files.items():
                    if not isinstance(file_path, str):
                        diagnostics.append("workspace_file_path_invalid")
                        continue
                    relative_file, unsafe_file = _safe_project_relative_path(file_path)
                    if unsafe_file:
                        diagnostics.append("workspace_file_path_unsafe")
                    if isinstance(workspace_path, str) and not file_path.startswith(
                        workspace_path + "/"
                    ):
                        diagnostics.append("workspace_file_outside_workspace")
                    if file_path.startswith("modules/"):
                        diagnostics.append("workspace_file_in_modules")
            if workspace.get("created") is not True:
                diagnostics.append("workspace_not_created")

        output = value.get("output")
        if not isinstance(output, Mapping):
            diagnostics.append("output_missing")
        else:
            if output.get("published_to_modules") is not False:
                diagnostics.append("published_to_modules_invalid")
            if output.get("direct_module_write_required") is not False:
                diagnostics.append("direct_module_write_policy_invalid")
            if output.get("staging_reserved") is not False:
                diagnostics.append("staging_reserved_invalid")
            staging_target = output.get("staging_target_path")
            if staging_target not in (None, ""):
                relative_target, unsafe_target = _safe_project_relative_path(staging_target)
                if unsafe_target:
                    diagnostics.append("staging_target_path_unsafe")
                elif isinstance(staging_target, str) and staging_target.startswith("modules/"):
                    diagnostics.append("staging_target_in_modules")
            staging_root = output.get("staging_root")
            if staging_root not in (None, ""):
                relative_root, unsafe_root = _safe_project_relative_path(staging_root)
                if unsafe_root:
                    diagnostics.append("staging_root_unsafe")

        envelope = value.get("envelope")
        if not isinstance(envelope, Mapping):
            diagnostics.append("envelope_missing")
        else:
            envelope_result = validate_adaptation_runtime_envelope(envelope)
            if not envelope_result.get("valid"):
                diagnostics.append("envelope_invalid")

    _walk_unsafe_keys(value, diagnostics)
    _walk_unsafe_paths(value, diagnostics)
    try:
        encoded = _canonical_json(value)
        if len(encoded) > MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS:
            diagnostics.append("workspace_too_large")
        if _SCAN_OPENAI_KEY_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_BEARER_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_CREDENTIAL_RE.search(encoded):
            diagnostics.append("credential_value_present")
    except (TypeError, ValueError):
        diagnostics.append("workspace_not_serializable")

    resolved_status = (
        TEXT_DESCRIPTION_WORKSPACE_STATUS_READY
        if not diagnostics
        else TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED
    )
    if not diagnostics and value.get("status") == TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED:
        # A failed-closed workspace that satisfies its own contract remains a
        # failed-closed workspace; the validator mirrors the manifest status.
        resolved_status = TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED

    return {
        "valid": not diagnostics,
        "status": resolved_status,
        "diagnostics": diagnostics[: MAX_DIAGNOSTICS * 4],
        "workspace": deepcopy(dict(value)) if not diagnostics else None,
    }


# ---------------------------------------------------------------------------
# Task 2.3 - Shared adaptation authoring adapter entry points
#
# Python-owned runtime adapter entry points that route a ready upload handoff
# or a ready text-description attempt workspace through the existing
# ``run_adaptation_authoring()`` exactly once per attempt. The author
# provider/client/parameter resolver/runner are injectable seams; the returned
# dossier is Python-parsed/validated and persisted atomically through the
# existing adaptation artifact helpers inside authoring.
#
# Authoring failure (author-policy refusal, provider/API failure, invalid
# model response, dossier validation failure, or artifact persistence failure)
# returns an explicit blocked result before any ModuleBuilder or publication
# call and leaves no completed module, registry, or campaign side effect. A
# selected adaptation attempt never silently downgrades to the legacy route.
#
# These adapters only assemble inputs and forward to the completed authoring
# contract; they never duplicate the author parser, the provider parameter
# resolver, staging reservation, or any publication logic.
# ---------------------------------------------------------------------------

AUTHORING_ADAPTER_CONTRACT_VERSION = "toolkit_adaptation_authoring_adapter.v1"
AUTHORING_ADAPTER_STATUS_READY = "ready"
AUTHORING_ADAPTER_STATUS_BLOCKED = "blocked"
AUTHORING_ADAPTER_OUTCOME_HANDOFF_READY = "handoff_ready"
AUTHORING_ADAPTER_OUTCOME_BLOCKED = "blocked"

# The ready result carries the validated dossier, which is bounded by the
# dossier contract; this cap covers the whole adapter result envelope.
MAX_ADAPTER_RESULT_SERIALIZED_CHARS = 320_000

# Bounded source-format evidence for attempt metadata (never raw source).
SOURCE_FORMAT_BY_INPUT_KIND = {
    INPUT_KIND_UPLOAD_MARKDOWN: "markdown",
    INPUT_KIND_UPLOAD_PDF: "pdf",
    INPUT_KIND_TEXT_DESCRIPTION: "text_description",
}


def _bounded_adapter_diagnostics(value: Any) -> List[Dict[str, str]]:
    """Bound and normalize diagnostics from any adapter or authoring source."""
    result: List[Dict[str, str]] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in list(value)[:MAX_DIAGNOSTICS]:
            if isinstance(item, Mapping):
                result.append(
                    _diagnostic(
                        str(item.get("code") or "authoring_blocked"),
                        str(item.get("message") or "Adaptation authoring was blocked."),
                        str(item.get("severity") or DIAGNOSTIC_SEVERITY_ERROR),
                    )
                )
            elif item is not None:
                result.append(_error("authoring_blocked", str(item)))
    if not result:
        result.append(_error("authoring_blocked", "Adaptation authoring was blocked."))
    return result[:MAX_DIAGNOSTICS]


def _route_authority() -> Dict[str, Any]:
    """Return the deterministic no-downgrade route authority markers."""
    return {
        "selected_route": BUILD_MODE_LLM_ADAPTATION,
        "fallback_allowed": False,
        "route_authority": ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED,
        "adaptation_artifacts_required": True,
    }


def _blocked_adapter_result(
    input_kind: str,
    diagnostics: List[Dict[str, str]],
    *,
    attempt: Optional[Mapping[str, Any]] = None,
    source_identity: Optional[Mapping[str, Any]] = None,
    rights: Optional[Mapping[str, Any]] = None,
    world_context: Optional[Mapping[str, Any]] = None,
    staging: Optional[Mapping[str, Any]] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    authoring: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the deterministic fail-closed adapter result for one input."""
    authoring_block = dict(authoring or {})
    authoring_block.setdefault("authoring_attempted", False)
    authoring_block.setdefault("authoring_status", AUTHORING_STATUS_BLOCKED)
    authoring_block.setdefault("authoring_ok", False)
    authoring_block.setdefault("diagnostics", [])
    # Safe bounded diagnostics (task 3.2): blocked adapter results carry an
    # explicit (nullable) reason category/code and never claim revision
    # eligibility. No raw provider/refusal text is ever retained.
    authoring_block.setdefault("safe_class", None)
    authoring_block.setdefault("reason_code", None)
    authoring_block.setdefault("revision_eligible", False)
    # TABLETOP MODE: Task 2.5 keeps world-context provenance canonical on every
    # report surface. A blocked result that has no usable world context carries
    # the explicit unavailable fallback instead of an empty mapping, so attempt
    # reports never claim world-seed grounding they do not have.
    world_provenance = build_world_context_provenance(
        world_context if isinstance(world_context, Mapping) else None
    )
    return {
        "contract_version": AUTHORING_ADAPTER_CONTRACT_VERSION,
        "status": AUTHORING_ADAPTER_STATUS_BLOCKED,
        "outcome": AUTHORING_ADAPTER_OUTCOME_BLOCKED,
        "ok": False,
        "input_kind": input_kind,
        "route": _route_authority(),
        "attempt": deepcopy(dict(attempt or {})),
        "source_identity": deepcopy(dict(source_identity or {})),
        "rights": deepcopy(dict(rights or {})),
        "world_context": world_provenance,
        "staging": deepcopy(dict(staging or {})),
        "model_metadata": deepcopy(dict(model_metadata or {})),
        "authoring": authoring_block,
        "dossier": None,
        "guards": {
            "module_builder_allowed": False,
            "module_builder_started": False,
            "publication_started": False,
            "registry_mutated": False,
            "completed_module_artifacts": [],
            "selected_route_authoritative": True,
        },
        "diagnostics": diagnostics[:MAX_DIAGNOSTICS],
    }


def _resolve_authoring_workspace(
    reference: Any, repo_root: Path
) -> Tuple[Optional[Path], str]:
    """Resolve the authoring workspace from a project-relative reference.

    Returns ``(workspace_path, error_code)``. The reference must be a safe
    project-relative path to an existing directory; anything else fails
    closed so artifacts are never persisted outside the repository.
    """
    if reference is None:
        return None, "workspace_reference_missing"
    raw = str(reference).strip() if isinstance(reference, str) else ""
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith("/")
        or _DRIVE_PATH_RE.match(raw)
    ):
        return None, "workspace_reference_invalid"
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None, "workspace_reference_invalid"
    workspace = repo_root.joinpath(*parts)
    if not workspace.exists() or not workspace.is_dir():
        return None, "workspace_missing"
    return workspace, ""


def _run_envelope_authoring(
    envelope: Mapping[str, Any],
    *,
    input_kind: str,
    source_format: str,
    workspace_path: Path,
    model: Optional[str],
    provider: Optional[str],
    client: Any,
    parameter_resolver: Any,
    timeout_seconds: Optional[float],
    author_runner: Any,
    artifact_persister: Any,
    proposal_persister: Any,
    diagnostics: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Route one validated runtime envelope through the authoring contract.

    The envelope is the task 1.2 boundary: it already carries Python-owned
    attempt metadata, source identity/context, rights metadata, world-context
    provenance, and staging references. Only those bounded fields are
    forwarded to ``run_adaptation_authoring()``, which owns the provider call,
    dossier parsing/validation, and atomic artifact persistence. This helper
    never calls ModuleBuilder and never performs publication work.
    """
    envelope_result = validate_adaptation_runtime_envelope(envelope)
    if not envelope_result.get("valid"):
        diagnostics.append(_error("envelope_invalid", "runtime envelope is not valid for authoring"))
        return _blocked_adapter_result(input_kind, diagnostics)

    source_identity = envelope.get("source_identity")
    source_identity = source_identity if isinstance(source_identity, Mapping) else {}
    rights = envelope.get("rights")
    rights = rights if isinstance(rights, Mapping) else {}
    attempt = envelope.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    world_context = envelope.get("world_context")
    world_context = (
        world_context
        if isinstance(world_context, Mapping)
        else build_world_context_provenance(None)
    )
    staging = envelope.get("staging")
    staging = staging if isinstance(staging, Mapping) else {}
    model_metadata = envelope.get("model_metadata")
    model_metadata = model_metadata if isinstance(model_metadata, Mapping) else {}
    source_context = envelope.get("source_context")
    if not isinstance(source_context, Mapping):
        diagnostics.append(_error("source_context_invalid", "runtime envelope has no bounded source context"))
        return _blocked_adapter_result(
            input_kind,
            diagnostics,
            attempt=attempt,
            source_identity=source_identity,
            rights=rights,
            world_context=world_context,
            staging=staging,
            model_metadata=model_metadata,
        )

    attempt_mirror: Dict[str, Any] = {
        "attempt_id": str(attempt.get("attempt_id") or ""),
        "attempt_number": attempt.get("attempt_number"),
        "revision_number": attempt.get("revision_number"),
        "job_id": attempt.get("job_id"),
    }
    rights_mirror: Dict[str, Any] = {
        "rights_class": rights.get("rights_class"),
        "rights_basis": rights.get("rights_basis"),
        "rights_review_required": rights.get("rights_review_required"),
        "rights_review_status": rights.get("rights_review_status"),
        "python_owned": True,
        "provider_may_change": False,
    }

    resolved_model = model
    if resolved_model is None:
        candidate = model_metadata.get("model")
        resolved_model = candidate if isinstance(candidate, str) and candidate.strip() else None
    resolved_provider = provider
    if resolved_provider is None:
        candidate = model_metadata.get("provider")
        resolved_provider = candidate if isinstance(candidate, str) and candidate.strip() else None

    authoring_kwargs: Dict[str, Any] = {
        "workspace": workspace_path,
        "world_context": world_context,
        "job_id": str(attempt.get("job_id") or ""),
        "attempt_number": int(attempt.get("attempt_number") or 1),
        "source_title": str(source_identity.get("source_title") or ""),
        "source_hash": str(source_identity.get("source_hash") or ""),
        "source_path": str(source_identity.get("source_path") or ""),
        "source_profile": str(source_context.get("source_profile") or ""),
        "source_format": source_format,
        "rights_metadata": rights,
        "rights_class": rights.get("rights_class"),
        "rights_basis": rights.get("rights_basis"),
        "rights_review_required": rights.get("rights_review_required"),
        "rights_review_status": rights.get("rights_review_status"),
        "model": resolved_model,
        "provider": resolved_provider,
        "model_metadata": model_metadata,
        "client": client,
        "parameter_resolver": parameter_resolver,
        "timeout_seconds": timeout_seconds,
    }
    if artifact_persister is not None:
        authoring_kwargs["artifact_persister"] = artifact_persister
    if proposal_persister is not None:
        authoring_kwargs["proposal_persister"] = proposal_persister
    if author_runner is not None:
        authoring_kwargs["author_runner"] = author_runner

    try:
        authoring_result = run_adaptation_authoring(source_context, **authoring_kwargs)
    except Exception:
        authoring_result = None
    if authoring_result is None or not isinstance(authoring_result, Mapping):
        diagnostics.append(
            _error("authoring_adapter_failed", "adaptation authoring adapter failed to produce a result")
        )
        return _blocked_adapter_result(
            input_kind,
            diagnostics,
            attempt=attempt_mirror,
            source_identity=source_identity,
            rights=rights_mirror,
            world_context=world_context,
            staging=staging,
            model_metadata=model_metadata,
            authoring={
                "authoring_attempted": True,
                "authoring_status": AUTHORING_STATUS_BLOCKED,
                "authoring_ok": False,
                "diagnostics": [_error("authoring_adapter_failed", "adaptation authoring adapter failed")],
                "safe_class": REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
                "reason_code": REASON_CODE_PROVIDER_CALL_FAILED,
                "revision_eligible": False,
            },
        )

    authoring_ok = bool(authoring_result.get("ok"))
    authoring_block: Dict[str, Any] = {
        "authoring_attempted": True,
        "authoring_status": str(
            authoring_result.get("status") or AUTHORING_STATUS_BLOCKED
        ),
        "authoring_ok": authoring_ok,
        "attempt_id": str(authoring_result.get("attempt_id") or ""),
        "dossier_artifact_path": authoring_result.get("dossier_artifact_path"),
        "dossier_artifact_persisted": bool(
            authoring_result.get("dossier_artifact_persisted")
        ),
        "failure_artifact_path": authoring_result.get("failure_artifact_path"),
        "failure_artifact_persisted": bool(
            authoring_result.get("failure_artifact_persisted")
        ),
        "proposal_ledger_path": authoring_result.get("proposal_ledger_path"),
        "proposal_ledger_persisted": bool(
            authoring_result.get("proposal_ledger_persisted")
        ),
        "proposal_status": authoring_result.get("proposal_status"),
        "proposal_count": int(authoring_result.get("proposal_count") or 0),
        "idempotent_replay": bool(authoring_result.get("idempotent_replay")),
        "diagnostics": _bounded_adapter_diagnostics(authoring_result.get("diagnostics")),
        "safe_class": (
            authoring_result.get("safe_class")
            or REASON_CATEGORY_PROVIDER_INFRASTRUCTURE
        )
        if not authoring_ok
        else REASON_CATEGORY_NONE,
        "reason_code": (
            authoring_result.get("reason_code") or REASON_CODE_PROVIDER_CALL_FAILED
        )
        if not authoring_ok
        else REASON_CODE_NONE,
        "revision_eligible": bool(authoring_result.get("revision_eligible")),
        "retryable": bool(authoring_result.get("retryable")),
        "terminal": bool(authoring_result.get("terminal")),
    }

    result_diagnostics = list(diagnostics[:MAX_DIAGNOSTICS])
    if not authoring_ok:
        result_diagnostics = _bounded_adapter_diagnostics(
            authoring_result.get("diagnostics")
        )
        if not result_diagnostics:
            result_diagnostics = [
                _error("authoring_blocked", "Adaptation authoring was blocked.")
            ]

    return {
        "contract_version": AUTHORING_ADAPTER_CONTRACT_VERSION,
        "status": (
            AUTHORING_ADAPTER_STATUS_READY
            if authoring_ok
            else AUTHORING_ADAPTER_STATUS_BLOCKED
        ),
        "outcome": (
            AUTHORING_ADAPTER_OUTCOME_HANDOFF_READY
            if authoring_ok
            else AUTHORING_ADAPTER_OUTCOME_BLOCKED
        ),
        "ok": authoring_ok,
        "input_kind": input_kind,
        "route": _route_authority(),
        "attempt": attempt_mirror,
        "source_identity": deepcopy(dict(source_identity)),
        "rights": rights_mirror,
        "world_context": deepcopy(dict(world_context)),
        "staging": deepcopy(dict(staging)),
        "model_metadata": deepcopy(
            dict(authoring_result.get("model_metadata") or model_metadata)
        ),
        "authoring": authoring_block,
        "dossier": deepcopy(authoring_result.get("dossier")) if authoring_ok else None,
        "guards": {
            "module_builder_allowed": bool(
                authoring_result.get("module_builder_allowed")
            ),
            "module_builder_started": bool(
                authoring_result.get("module_builder_started")
            ),
            "publication_started": bool(authoring_result.get("publication_started")),
            "registry_mutated": bool(authoring_result.get("registry_mutated")),
            "completed_module_artifacts": list(
                authoring_result.get("completed_module_artifacts") or []
            ),
            "selected_route_authoritative": True,
        },
        "diagnostics": result_diagnostics[:MAX_DIAGNOSTICS],
    }


def run_upload_adaptation_authoring(
    handoff: Mapping[str, Any],
    *,
    workspace: Any = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    client: Any = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = 120,
    author_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    artifact_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
    proposal_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """Route one approved upload handoff through adaptation authoring.

    ``handoff`` is the ready task 2.1 upload handoff from
    ``build_upload_adaptation_handoff``. The adapter validates the handoff and
    its runtime envelope, resolves the attempt workspace (the handoff-recorded
    workspace or an explicit override), and invokes
    ``run_adaptation_authoring()`` exactly once through the injectable
    author provider/client/runner seam.

    A ready result carries the Python-validated dossier plus its atomic
    artifact references. Any authoring failure returns an explicit blocked
    result before ModuleBuilder or publication work and never silently
    downgrades to the legacy route.
    """
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(handoff, Mapping):
        return _blocked_adapter_result(
            INPUT_KIND_UPLOAD_MARKDOWN,
            [_error("handoff_invalid", "upload adaptation handoff must be an object")],
        )
    if handoff.get("contract_version") != UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION:
        return _blocked_adapter_result(
            str(handoff.get("input_kind") or INPUT_KIND_UPLOAD_MARKDOWN),
            [_error("handoff_contract_invalid", "upload adaptation handoff contract is unsupported")],
        )
    if handoff.get("status") != HANDOFF_STATUS_READY:
        return _blocked_adapter_result(
            str(handoff.get("input_kind") or INPUT_KIND_UPLOAD_MARKDOWN),
            _bounded_adapter_diagnostics(handoff.get("diagnostics")),
        )
    envelope = handoff.get("envelope")
    if not isinstance(envelope, Mapping):
        return _blocked_adapter_result(
            str(handoff.get("input_kind") or INPUT_KIND_UPLOAD_MARKDOWN),
            [_error("envelope_missing", "ready upload handoff has no runtime envelope")],
        )
    input_kind = str(envelope.get("input_kind") or handoff.get("input_kind") or INPUT_KIND_UPLOAD_MARKDOWN)
    source_format = SOURCE_FORMAT_BY_INPUT_KIND.get(input_kind, "markdown")

    repo_root = Path(__file__).resolve().parents[2]
    workspace_path: Optional[Path] = None
    if workspace is not None:
        resolved, _, workspace_error = _resolve_upload_workspace(workspace)
        if workspace_error:
            return _blocked_adapter_result(
                input_kind,
                [_error(workspace_error, "authoring workspace is unavailable or unsafe")],
            )
        workspace_path = resolved
    else:
        evidence = handoff.get("upload_evidence")
        reference = evidence.get("workspace") if isinstance(evidence, Mapping) else None
        workspace_path, workspace_error = _resolve_authoring_workspace(reference, repo_root)
        if workspace_error:
            return _blocked_adapter_result(
                input_kind,
                [_error(workspace_error, "authoring workspace could not be resolved")],
            )

    return _run_envelope_authoring(
        envelope,
        input_kind=input_kind,
        source_format=source_format,
        workspace_path=workspace_path,
        model=model,
        provider=provider,
        client=client,
        parameter_resolver=parameter_resolver,
        timeout_seconds=timeout_seconds,
        author_runner=author_runner,
        artifact_persister=artifact_persister,
        proposal_persister=proposal_persister,
        diagnostics=diagnostics,
    )


def run_text_description_adaptation_authoring(
    workspace_manifest: Mapping[str, Any],
    *,
    workspace: Any = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    client: Any = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = 120,
    author_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    artifact_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
    proposal_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """Route one ready text-description attempt workspace through authoring.

    ``workspace_manifest`` is the ready task 2.2 manifest from
    ``build_text_description_attempt_workspace``. The adapter validates the
    manifest and its runtime envelope, resolves the attempt workspace (the
    manifest-recorded workspace or an explicit override), and invokes
    ``run_adaptation_authoring()`` exactly once through the injectable author
    provider/client/runner seam.

    A ready result carries the Python-validated dossier plus its atomic
    artifact references. Any authoring failure returns an explicit blocked
    result before ModuleBuilder or publication work; the enabled path never
    writes directly to ``modules/<name>`` and never silently downgrades to
    the legacy route.
    """
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(workspace_manifest, Mapping):
        return _blocked_adapter_result(
            INPUT_KIND_TEXT_DESCRIPTION,
            [_error("workspace_manifest_invalid", "text-description workspace manifest must be an object")],
        )
    if workspace_manifest.get("contract_version") != TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION:
        return _blocked_adapter_result(
            INPUT_KIND_TEXT_DESCRIPTION,
            [_error("workspace_contract_invalid", "text-description workspace contract is unsupported")],
        )
    if workspace_manifest.get("status") != TEXT_DESCRIPTION_WORKSPACE_STATUS_READY:
        return _blocked_adapter_result(
            INPUT_KIND_TEXT_DESCRIPTION,
            _bounded_adapter_diagnostics(workspace_manifest.get("diagnostics")),
        )
    envelope = workspace_manifest.get("envelope")
    if not isinstance(envelope, Mapping):
        return _blocked_adapter_result(
            INPUT_KIND_TEXT_DESCRIPTION,
            [_error("envelope_missing", "ready text workspace has no runtime envelope")],
        )

    repo_root = Path(__file__).resolve().parents[2]
    workspace_path: Optional[Path] = None
    if workspace is not None:
        resolved, _, workspace_error = _resolve_upload_workspace(workspace)
        if workspace_error:
            return _blocked_adapter_result(
                INPUT_KIND_TEXT_DESCRIPTION,
                [_error(workspace_error, "authoring workspace is unavailable or unsafe")],
            )
        workspace_path = resolved
    else:
        workspace_block = workspace_manifest.get("workspace")
        reference = workspace_block.get("path") if isinstance(workspace_block, Mapping) else None
        workspace_path, workspace_error = _resolve_authoring_workspace(reference, repo_root)
        if workspace_error:
            return _blocked_adapter_result(
                INPUT_KIND_TEXT_DESCRIPTION,
                [_error(workspace_error, "authoring workspace could not be resolved")],
            )

    return _run_envelope_authoring(
        envelope,
        input_kind=INPUT_KIND_TEXT_DESCRIPTION,
        source_format=SOURCE_FORMAT_BY_INPUT_KIND[INPUT_KIND_TEXT_DESCRIPTION],
        workspace_path=workspace_path,
        model=model,
        provider=provider,
        client=client,
        parameter_resolver=parameter_resolver,
        timeout_seconds=timeout_seconds,
        author_runner=author_runner,
        artifact_persister=artifact_persister,
        proposal_persister=proposal_persister,
        diagnostics=diagnostics,
    )


def serialize_adaptation_authoring_result(result: Mapping[str, Any]) -> str:
    """Return deterministic canonical JSON for an adapter result."""
    if not isinstance(result, Mapping):
        raise ValueError("adaptation authoring result must be an object")
    encoded = _canonical_json(result)
    if len(encoded) > MAX_ADAPTER_RESULT_SERIALIZED_CHARS:
        raise ValueError("adaptation authoring result exceeds its serialized bound")
    return encoded


def validate_adaptation_authoring_result(value: Any) -> Dict[str, Any]:
    """Validate an adapter result round trip and its no-downgrade contract."""
    diagnostics: List[str] = []
    if not isinstance(value, Mapping):
        return {
            "valid": False,
            "status": AUTHORING_ADAPTER_STATUS_BLOCKED,
            "diagnostics": ["result_must_be_object"],
            "result": None,
        }
    if value.get("contract_version") != AUTHORING_ADAPTER_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    status = value.get("status")
    if status not in {AUTHORING_ADAPTER_STATUS_READY, AUTHORING_ADAPTER_STATUS_BLOCKED}:
        diagnostics.append("status_invalid")
    ok = value.get("ok")
    if not isinstance(ok, bool):
        diagnostics.append("ok_invalid")
    elif status == AUTHORING_ADAPTER_STATUS_READY and not ok:
        diagnostics.append("ready_result_not_ok")
    elif status == AUTHORING_ADAPTER_STATUS_BLOCKED and ok:
        diagnostics.append("blocked_result_ok")
    if value.get("input_kind") not in VALID_INPUT_KINDS:
        diagnostics.append("input_kind_invalid")

    route = value.get("route")
    if not isinstance(route, Mapping):
        diagnostics.append("route_missing")
    else:
        if route.get("selected_route") != BUILD_MODE_LLM_ADAPTATION:
            diagnostics.append("route_selected_invalid")
        if route.get("fallback_allowed") is not False:
            diagnostics.append("route_fallback_allowed_invalid")
        if route.get("route_authority") != ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED:
            diagnostics.append("route_authority_invalid")
        if route.get("adaptation_artifacts_required") is not True:
            diagnostics.append("route_artifacts_required_invalid")

    attempt = value.get("attempt")
    if not isinstance(attempt, Mapping):
        diagnostics.append("attempt_missing")
    else:
        if not _is_safe_attempt_id(attempt.get("attempt_id")):
            diagnostics.append("attempt_id_invalid")
        attempt_number = attempt.get("attempt_number")
        if (
            isinstance(attempt_number, bool)
            or not isinstance(attempt_number, int)
            or not 1 <= attempt_number <= 1_000_000
        ):
            diagnostics.append("attempt_number_invalid")
        revision_number = attempt.get("revision_number")
        if (
            isinstance(revision_number, bool)
            or not isinstance(revision_number, int)
            or not 0 <= revision_number <= 100
        ):
            diagnostics.append("revision_number_invalid")
        job_id = attempt.get("job_id")
        if job_id is not None and (
            not isinstance(job_id, str) or len(job_id) > MAX_JOB_ID_CHARS
        ):
            diagnostics.append("job_id_invalid")

    rights = value.get("rights")
    if not isinstance(rights, Mapping):
        diagnostics.append("rights_missing")
    else:
        if rights.get("python_owned") is not True:
            diagnostics.append("rights_not_python_owned")
        if rights.get("provider_may_change") is not False:
            diagnostics.append("rights_provider_policy_invalid")
        if rights.get("rights_class") not in VALID_RIGHTS_CLASSES:
            diagnostics.append("rights_class_invalid")
        if not isinstance(rights.get("rights_review_required"), bool):
            diagnostics.append("rights_review_required_invalid")
        if rights.get("rights_review_status") not in VALID_RIGHTS_REVIEW_STATUSES:
            diagnostics.append("rights_review_status_invalid")

    world = value.get("world_context")
    if not isinstance(world, Mapping):
        diagnostics.append("world_context_missing")
    elif build_world_context_provenance(world) != dict(world):
        diagnostics.append("world_context_not_canonical")

    guards = value.get("guards")
    if not isinstance(guards, Mapping):
        diagnostics.append("guards_missing")
    else:
        if guards.get("module_builder_started") is not False:
            diagnostics.append("module_builder_started_invalid")
        if guards.get("publication_started") is not False:
            diagnostics.append("publication_started_invalid")
        if guards.get("registry_mutated") is not False:
            diagnostics.append("registry_mutated_invalid")
        if guards.get("completed_module_artifacts") not in (None, []):
            diagnostics.append("completed_module_artifacts_invalid")
        if guards.get("selected_route_authoritative") is not True:
            diagnostics.append("route_authoritative_invalid")
        if not isinstance(guards.get("module_builder_allowed"), bool):
            diagnostics.append("module_builder_allowed_invalid")

    authoring = value.get("authoring")
    if not isinstance(authoring, Mapping):
        diagnostics.append("authoring_missing")
    else:
        if authoring.get("authoring_status") not in {
            AUTHORING_STATUS_READY,
            AUTHORING_STATUS_BLOCKED,
        }:
            diagnostics.append("authoring_status_invalid")
        if not isinstance(authoring.get("authoring_attempted"), bool):
            diagnostics.append("authoring_attempted_invalid")
        if not isinstance(authoring.get("authoring_ok"), bool):
            diagnostics.append("authoring_ok_invalid")
        # Safe bounded diagnostics (task 3.2): every authoring block carries an
        # explicit reason category/code, and author outcomes never consume the
        # semantic revision budget.
        if not isinstance(authoring.get("revision_eligible"), bool):
            diagnostics.append("authoring_revision_eligible_invalid")
        if "retryable" in authoring and not isinstance(authoring.get("retryable"), bool):
            diagnostics.append("authoring_retryable_invalid")
        if "terminal" in authoring and not isinstance(authoring.get("terminal"), bool):
            diagnostics.append("authoring_terminal_invalid")
        safe_class = authoring.get("safe_class")
        if safe_class is not None and safe_class not in VALID_REASON_CATEGORIES:
            diagnostics.append("authoring_safe_class_invalid")
        reason_code = authoring.get("reason_code")
        if reason_code is not None and (
            not isinstance(reason_code, str)
            or not reason_code
            or len(reason_code) > 96
            or not reason_code.isascii()
        ):
            diagnostics.append("authoring_reason_code_invalid")

    dossier = value.get("dossier")
    if status == AUTHORING_ADAPTER_STATUS_READY:
        if not isinstance(dossier, Mapping):
            diagnostics.append("ready_dossier_missing")
        else:
            dossier_result = validate_adaptation_dossier(dossier)
            if not dossier_result.get("valid"):
                diagnostics.append("dossier_invalid")
            elif not dossier_result.get("build_ready"):
                # A review-gated or restricted dossier is never build-ready; a
                # ready adapter result cannot carry one (task 2.4 review gating).
                diagnostics.append("dossier_not_build_ready")
            if isinstance(rights, Mapping):
                # Final rights identity preservation: the ready dossier must
                # echo the Python-owned rights mirror exactly. Provider output
                # can never relabel the classification or review state at this
                # boundary (task 2.4 no-relabel contract).
                for field in (
                    "rights_class",
                    "rights_basis",
                    "rights_review_required",
                    "rights_review_status",
                ):
                    if dossier.get(field) != rights.get(field):
                        diagnostics.append("dossier_rights_identity_mismatch")
                        break
        if not isinstance(authoring.get("dossier_artifact_path"), str) or not authoring.get("dossier_artifact_path"):
            diagnostics.append("dossier_artifact_path_missing")
        if authoring.get("dossier_artifact_persisted") is not True:
            diagnostics.append("dossier_artifact_not_persisted")
    else:
        if dossier is not None:
            diagnostics.append("blocked_result_has_dossier")
        items = value.get("diagnostics")
        if not isinstance(items, list) or not items:
            diagnostics.append("blocked_result_missing_diagnostics")

    _walk_unsafe_keys(value, diagnostics)
    _walk_unsafe_paths(value, diagnostics)
    try:
        encoded = _canonical_json(value)
        if len(encoded) > MAX_ADAPTER_RESULT_SERIALIZED_CHARS:
            diagnostics.append("result_too_large")
        if _SCAN_OPENAI_KEY_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_BEARER_RE.search(encoded):
            diagnostics.append("credential_value_present")
        if _SCAN_CREDENTIAL_RE.search(encoded):
            diagnostics.append("credential_value_present")
    except (TypeError, ValueError):
        diagnostics.append("result_not_serializable")

    return {
        "valid": not diagnostics,
        "status": (
            AUTHORING_ADAPTER_STATUS_READY
            if not diagnostics
            else AUTHORING_ADAPTER_STATUS_BLOCKED
        ),
        "diagnostics": diagnostics[: MAX_DIAGNOSTICS * 4],
        "result": deepcopy(dict(value)) if not diagnostics else None,
    }


# Discoverability aliases consistent with the other adaptation scaffold
# modules.
author_upload_adaptation = run_upload_adaptation_authoring
run_upload_authoring = run_upload_adaptation_authoring
author_text_description_adaptation = run_text_description_adaptation_authoring
run_text_authoring = run_text_description_adaptation_authoring
assemble_upload_adaptation_handoff = build_upload_adaptation_handoff
prepare_upload_adaptation_handoff = build_upload_adaptation_handoff
normalize_upload_adaptation_handoff = build_upload_adaptation_handoff


# Discoverability aliases consistent with the other adaptation scaffold
# modules.
assemble_text_description_attempt_workspace = build_text_description_attempt_workspace
prepare_text_description_attempt_workspace = build_text_description_attempt_workspace
build_text_attempt_workspace = build_text_description_attempt_workspace


# Discoverability aliases consistent with the other adaptation scaffold
# modules.
assemble_adaptation_runtime_envelope = build_adaptation_runtime_envelope
prepare_adaptation_runtime_envelope = build_adaptation_runtime_envelope
normalize_adaptation_runtime_envelope = build_adaptation_runtime_envelope


__all__ = [
    "APPROVED_UPLOAD_REVIEW_STATES",
    "ADAPTATION_CONVERGENCE_TASK_ID",
    "ATTEMPT_METADATA_FILENAME",
    "AUTHORING_ADAPTER_CONTRACT_VERSION",
    "AUTHORING_ADAPTER_OUTCOME_BLOCKED",
    "AUTHORING_ADAPTER_OUTCOME_HANDOFF_READY",
    "AUTHORING_ADAPTER_STATUS_BLOCKED",
    "AUTHORING_ADAPTER_STATUS_READY",
    "CONVERGENCE_CONTRACT_VERSION",
    "BUILDER_NARRATIVE_FILENAME",
    "CONCEPT_SOURCE_FILENAME",
    "DEFAULT_ADAPTATION_STAGING_ROOT",
    "DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT",
    "ENVELOPE_STATUS_INVALID",
    "ENVELOPE_STATUS_READY",
    "HANDOFF_STATUS_FAILED_CLOSED",
    "HANDOFF_STATUS_READY",
    "INPUT_KIND_TEXT_DESCRIPTION",
    "INPUT_KIND_UPLOAD_MARKDOWN",
    "INPUT_KIND_UPLOAD_PDF",
    "MAX_ADAPTER_RESULT_SERIALIZED_CHARS",
    "MAX_ENVELOPE_SERIALIZED_CHARS",
    "MAX_HANDOFF_SERIALIZED_CHARS",
    "MAX_JOB_ID_CHARS",
    "MAX_MODEL_METADATA_TEXT_CHARS",
    "MAX_RAW_SOURCE_ACCEPT_CHARS",
    "MAX_RIGHTS_BASIS_CHARS",
    "MAX_SOURCE_TITLE_CHARS",
    "MAX_UPLOAD_SOURCE_BYTES",
    "MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS",
    "NORMALIZED_PACKET_FILENAME",
    "REVIEW_SNAPSHOT_FILENAME",
    "RUNTIME_ENVELOPE_FILENAME",
    "RUNTIME_ENVELOPE_CONTRACT_VERSION",
    "TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION",
    "TEXT_DESCRIPTION_CLASSIFIED_BY",
    "TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS",
    "TEXT_DESCRIPTION_SOURCE_KIND",
    "TEXT_DESCRIPTION_WORKSPACE_NORMALIZATION_STATE",
    "TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED",
    "TEXT_DESCRIPTION_WORKSPACE_STATUS_READY",
    "UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION",
    "UPLOAD_SOURCE_KIND_MARKDOWN",
    "UPLOAD_SOURCE_KIND_PDF",
    "VALID_INPUT_KINDS",
    "VALID_UPLOAD_SOURCE_KINDS",
    "WORKSPACE_MANIFEST_FILENAME",
    "assemble_adaptation_runtime_envelope",
    "assemble_text_description_attempt_workspace",
    "assemble_upload_adaptation_handoff",
    "author_text_description_adaptation",
    "author_upload_adaptation",
    "build_adaptation_runtime_envelope",
    "adaptation_convergence_callback",
    "build_text_attempt_workspace",
    "build_text_description_attempt_workspace",
    "build_upload_adaptation_handoff",
    "normalize_adaptation_runtime_envelope",
    "normalize_upload_adaptation_handoff",
    "prepare_adaptation_runtime_envelope",
    "prepare_text_description_attempt_workspace",
    "prepare_upload_adaptation_handoff",
    "run_text_authoring",
    "run_text_description_adaptation_authoring",
    "run_upload_adaptation_authoring",
    "run_upload_authoring",
    "serialize_adaptation_authoring_result",
    "serialize_adaptation_runtime_envelope",
    "serialize_text_description_attempt_workspace",
    "serialize_upload_adaptation_handoff",
    "validate_adaptation_authoring_result",
    "validate_adaptation_runtime_envelope",
    "validate_text_description_attempt_workspace",
    "validate_upload_adaptation_handoff",
]
