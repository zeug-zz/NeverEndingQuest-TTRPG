# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation World Proposals
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free normalization and atomic persistence for proposed world hooks and
continuations. Proposal ledgers are attempt-scoped review artifacts only. They
are never campaign canon, registry state, module publication state, or
mechanical state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance

try:
    from jsonschema import Draft7Validator
except Exception:  # pragma: no cover - dependency availability is environment-specific
    Draft7Validator = None  # type: ignore[assignment,misc]


ADAPTATION_PROPOSAL_CONTRACT_VERSION = "toolkit_adaptation_proposal.v1"
ADAPTATION_PROPOSAL_SCHEMA_VERSION = ADAPTATION_PROPOSAL_CONTRACT_VERSION
ADAPTATION_PROPOSAL_KIND = "world_narrative_proposals"
ADAPTATION_PROPOSAL_FILENAME = "world_narrative_proposals.json"

PROPOSAL_STATUS_PENDING_APPROVAL = "pending_approval"
PROPOSAL_STATUS_NO_PROPOSALS = "no_proposals"
VALID_PROPOSAL_STATUSES = (
    PROPOSAL_STATUS_PENDING_APPROVAL,
    PROPOSAL_STATUS_NO_PROPOSALS,
)
PROPOSAL_APPROVAL_STATUS_PENDING = "pending"
PROPOSAL_APPROVAL_PATH = "world_narrative_approval"
PROPOSAL_TYPE_WORLD_HOOK = "world_hook"
PROPOSAL_TYPE_CONTINUATION = "continuation"
VALID_PROPOSAL_TYPES = (PROPOSAL_TYPE_WORLD_HOOK, PROPOSAL_TYPE_CONTINUATION)

PROPOSAL_CONTEXT_AVAILABLE = "available"
PROPOSAL_CONTEXT_DEGRADED = "degraded"
PROPOSAL_CONTEXT_UNAVAILABLE = "unavailable"
PROPOSAL_CONTEXT_INVALID = "invalid"
VALID_PROPOSAL_CONTEXT_STATUSES = (
    PROPOSAL_CONTEXT_AVAILABLE,
    PROPOSAL_CONTEXT_DEGRADED,
    PROPOSAL_CONTEXT_UNAVAILABLE,
    PROPOSAL_CONTEXT_INVALID,
)

PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING = "warning"
PROPOSAL_DIAGNOSTIC_SEVERITY_ERROR = "error"
PROPOSAL_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE = "proposal_schema_unavailable"
PROPOSAL_DIAGNOSTIC_CODE_INVALID_DOSSIER = "proposal_dossier_invalid"
PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT = "proposal_attempt_invalid"
PROPOSAL_DIAGNOSTIC_CODE_INVALID_SOURCE = "proposal_source_invalid"
PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL = "proposal_invalid"
PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_FIELD = "proposal_unsafe_field"
PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_TEXT = "proposal_unsafe_text"
PROPOSAL_DIAGNOSTIC_CODE_DUPLICATE = "proposal_duplicate"
PROPOSAL_DIAGNOSTIC_CODE_TRUNCATED = "proposal_truncated"
PROPOSAL_DIAGNOSTIC_CODE_CONTEXT_DEGRADED = "proposal_context_degraded"
PROPOSAL_DIAGNOSTIC_CODE_HASH_MISMATCH = "proposal_hash_mismatch"
PROPOSAL_DIAGNOSTIC_CODE_LEDGER_PERSISTENCE = "proposal_ledger_persistence_failed"

MAX_PROPOSALS = 16
MAX_WORLD_HOOKS = 8
MAX_CONTINUATIONS = 8
MAX_CANDIDATE_SCAN = 64
MAX_DIAGNOSTICS = 24
MAX_TEXT_CHARS = 640
MAX_SOURCE_TITLE_CHARS = 4000
MAX_SOURCE_PATH_CHARS = 512
MAX_MODEL_METADATA_CHARS = 200
MAX_WORKSPACE_PATH_CHARS = 512

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "toolkit_adaptation_proposal_schema.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)"
    r"\s*[:=]\s*[^\s,;]+|\bBearer\s+[^\s,;]+"
)
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|\s)(?:/|[A-Za-z]:[\\/])")
_RUNTIME_WRITE_RE = re.compile(
    r"(?i)(?:world_registry\.json|campaign\.json|party_tracker\.json|"
    r"module_plot\.json|module_context\.json|set_hp|hp_delta|spell_slots)"
)
_SENSITIVE_WORKSPACE_PARTS = {
    "modules",
    "characters",
    "encounters",
    "world_registry.json",
    "campaign.json",
    "party_tracker.json",
}
_ALLOWED_MODEL_METADATA = frozenset(
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _ascii_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value).replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text).strip()
    text = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) <= limit:
        return text
    marker = " [truncated]"
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _diagnostic(
    code: str,
    message: str,
    path: str = "",
    severity: str = PROPOSAL_DIAGNOSTIC_SEVERITY_ERROR,
) -> Dict[str, str]:
    return {
        "code": _ascii_text(code, 120),
        "message": _ascii_text(message, 320),
        "path": _ascii_text(path, 160),
        "severity": severity if severity in {"warning", "error"} else "warning",
    }


def _bounded_diagnostics(values: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    unique: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        item = _diagnostic(
            str(value.get("code") or PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL),
            str(value.get("message") or "Invalid adaptation proposal."),
            str(value.get("path") or ""),
            str(value.get("severity") or "warning"),
        )
        unique[(item["code"], item["message"], item["path"], item["severity"])] = item
    ordered = sorted(unique.values(), key=lambda item: (item["code"], item["path"], item["message"]))
    return ordered[:MAX_DIAGNOSTICS]


def _safe_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _safe_attempt_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ATTEMPT_ID_RE.fullmatch(value)) and ".." not in value


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_SOURCE_PATH_CHARS:
        return False
    if value.startswith(("/", "\\")) or _DRIVE_PATH_RE.match(value) or "\\" in value:
        return False
    parts = PurePosixPath(value).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _unsafe_text(value: str) -> bool:
    return bool(_CREDENTIAL_RE.search(value) or _ABSOLUTE_PATH_RE.search(value) or _RUNTIME_WRITE_RE.search(value))


def _normalize_required_text(
    value: Any,
    path: str,
    diagnostics: List[Dict[str, str]],
    *,
    limit: int = MAX_TEXT_CHARS,
) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal text is required", path))
        return None
    raw = value.strip()
    if _unsafe_text(raw):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_TEXT, "proposal text contains a credential, runtime target, or unsafe path", path))
        return None
    normalized = _ascii_text(raw, limit)
    if len(raw) > limit:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_TRUNCATED, "proposal text was bounded", path, PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING))
    return normalized


def _normalize_optional_text(
    value: Any,
    path: str,
    diagnostics: List[Dict[str, str]],
    *,
    limit: int = MAX_TEXT_CHARS,
) -> Optional[str]:
    if value in (None, ""):
        return None
    return _normalize_required_text(value, path, diagnostics, limit=limit)


def _normalize_content(
    value: Any,
    proposal_type: str,
    path: str,
    diagnostics: List[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    if not isinstance(value, Mapping):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal entry must be an object", path))
        return None
    if proposal_type == PROPOSAL_TYPE_WORLD_HOOK:
        allowed = {"hook", "relationship", "proposed_follow_up"}
        required = ("hook", "relationship")
    else:
        allowed = {"hint", "scope", "related_module", "entity"}
        required = ("hint", "scope")
    unexpected = sorted(set(value) - allowed)
    for key in unexpected:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_FIELD, "proposal field is not allowlisted", f"{path}.{key}"))
    if unexpected:
        return None
    content: Dict[str, str] = {}
    for key in required:
        normalized = _normalize_required_text(value.get(key), f"{path}.{key}", diagnostics)
        if normalized is not None:
            content[key] = normalized
    for key in sorted(allowed - set(required)):
        normalized = _normalize_optional_text(value.get(key), f"{path}.{key}", diagnostics)
        if normalized is not None:
            content[key] = normalized
    if any(item.get("severity") == "error" and item.get("path", "").startswith(path) for item in diagnostics):
        return None
    return content


def _stable_input_key(value: Any) -> str:
    try:
        return _canonical_json(value)
    except (TypeError, ValueError):
        return _ascii_text(value, MAX_TEXT_CHARS)


def _proposal_id(
    attempt_id: str,
    revision_number: int,
    proposal_type: str,
    content: Mapping[str, str],
) -> str:
    prefix = "hook" if proposal_type == PROPOSAL_TYPE_WORLD_HOOK else "continuation"
    identity = {
        "attempt_id": attempt_id,
        "revision_number": revision_number,
        "proposal_type": proposal_type,
        "content": dict(content),
    }
    return prefix + "-" + _sha256(identity)[:24]


def _context_status(provenance: Mapping[str, Any]) -> str:
    context_status = provenance.get("context_status")
    seed_status = provenance.get("world_seed_status")
    if context_status == "available" and seed_status == "available":
        return PROPOSAL_CONTEXT_AVAILABLE
    if seed_status == "invalid":
        return PROPOSAL_CONTEXT_INVALID
    if context_status == "unavailable" or seed_status == "unavailable":
        return PROPOSAL_CONTEXT_UNAVAILABLE
    return PROPOSAL_CONTEXT_DEGRADED


def _normalize_model_metadata(value: Any, diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    if value in (None, {}):
        return {"provider": "not_recorded", "model": "not_recorded"}
    if not isinstance(value, Mapping):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "model metadata must be an object", "model_metadata"))
        return {"provider": "not_recorded", "model": "not_recorded"}
    unexpected = sorted(set(value) - _ALLOWED_MODEL_METADATA)
    for key in unexpected:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_FIELD, "model metadata field is not allowlisted", f"model_metadata.{key}"))
    result: Dict[str, Any] = {}
    for key in sorted(_ALLOWED_MODEL_METADATA):
        if key not in value:
            continue
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "model metadata value is invalid", f"model_metadata.{key}"))
            continue
        if isinstance(raw, float) and (raw != raw or raw in (float("inf"), float("-inf"))):
            diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "model metadata number is invalid", f"model_metadata.{key}"))
            continue
        if isinstance(raw, str):
            if _unsafe_text(raw):
                diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_TEXT, "model metadata contains unsafe text", f"model_metadata.{key}"))
                continue
            result[key] = _ascii_text(raw, MAX_MODEL_METADATA_CHARS)
        else:
            result[key] = raw
    result.setdefault("provider", "not_recorded")
    result.setdefault("model", "not_recorded")
    return result


def _schema_diagnostics(ledger: Mapping[str, Any]) -> List[Dict[str, str]]:
    if Draft7Validator is None:
        return [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE, "proposal schema dependency is unavailable")]
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
            schema = json.load(handle)
        validator = Draft7Validator(schema)
        errors = sorted(
            validator.iter_errors(ledger),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), str(error.message)),
        )
    except Exception as exc:
        return [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE, "proposal schema could not be loaded: " + _ascii_text(exc))]
    return [
        _diagnostic(
            PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL,
            str(error.message),
            ".".join(str(part) for part in error.absolute_path),
        )
        for error in errors
    ]


def _ledger_hash(ledger: Mapping[str, Any]) -> str:
    value = deepcopy(dict(ledger))
    value.pop("ledger_hash", None)
    return _sha256(value)


def _semantic_diagnostics(ledger: Mapping[str, Any]) -> List[Dict[str, str]]:
    diagnostics: List[Dict[str, str]] = []
    if ledger.get("approval_status") != PROPOSAL_APPROVAL_STATUS_PENDING:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal ledger must remain pending approval", "approval_status"))
    for field in ("approval_required", "auto_apply", "apply_allowed", "canon_write_allowed", "registry_write_allowed", "mechanical_write_allowed"):
        expected = True if field == "approval_required" else False
        if ledger.get(field) is not expected:
            diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal ledger has an unsafe application flag", field))
    if ledger.get("status") == PROPOSAL_STATUS_PENDING_APPROVAL and not ledger.get("proposals"):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "pending proposal ledger has no proposals", "proposals"))
    if ledger.get("status") == PROPOSAL_STATUS_NO_PROPOSALS and ledger.get("proposals"):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "empty proposal ledger contains proposals", "proposals"))
    proposals = ledger.get("proposals")
    if not isinstance(proposals, list):
        return diagnostics
    if ledger.get("proposal_count") != len(proposals):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal_count does not match proposals", "proposal_count"))
    expected_hooks = any(
        isinstance(item, Mapping) and item.get("proposal_type") == PROPOSAL_TYPE_WORLD_HOOK
        for item in proposals
    )
    expected_continuations = any(
        isinstance(item, Mapping) and item.get("proposal_type") == PROPOSAL_TYPE_CONTINUATION
        for item in proposals
    )
    if ledger.get("world_hooks_proposed") is not expected_hooks:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "world_hooks_proposed does not match the ledger", "world_hooks_proposed"))
    if ledger.get("continuations_proposed") is not expected_continuations:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "continuations_proposed does not match the ledger", "continuations_proposed"))
    identifiers = []
    for index, proposal in enumerate(proposals):
        path = f"proposals[{index}]"
        if not isinstance(proposal, Mapping):
            continue
        identifiers.append(proposal.get("proposal_id"))
        content = proposal.get("content")
        if isinstance(content, Mapping):
            expected = _proposal_id(
                str(ledger.get("attempt_id") or ""),
                int(ledger.get("revision_number") or 0),
                str(proposal.get("proposal_type") or ""),
                content,
            )
            if proposal.get("proposal_id") != expected:
                diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_HASH_MISMATCH, "proposal_id is not deterministic for its content", path + ".proposal_id"))
        if proposal.get("approval_status") != PROPOSAL_APPROVAL_STATUS_PENDING or proposal.get("apply_allowed") is not False:
            diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal is not pending and unapproved", path))
    if len(identifiers) != len(set(identifiers)):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_DUPLICATE, "proposal identifiers must be unique", "proposals"))
    if ledger.get("ledger_hash") != _ledger_hash(ledger):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_HASH_MISMATCH, "ledger_hash does not match the proposal ledger", "ledger_hash"))
    provenance = ledger.get("provenance")
    if isinstance(provenance, Mapping):
        world = provenance.get("world_context_provenance")
        if isinstance(world, Mapping):
            normalized_world = build_world_context_provenance(world)
            if normalized_world != dict(world):
                diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_HASH_MISMATCH, "world context provenance is not canonical", "provenance.world_context_provenance"))
            if normalized_world.get("canon_write_allowed") or normalized_world.get("registry_write_allowed") or normalized_world.get("mechanical_write_allowed"):
                diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_FIELD, "world context provenance permits a forbidden write", "provenance.world_context_provenance"))
            if ledger.get("context_status") != _context_status(normalized_world):
                diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_HASH_MISMATCH, "proposal context status does not match world provenance", "context_status"))
    for index, proposal in enumerate(proposals if isinstance(proposals, list) else []):
        content = proposal.get("content") if isinstance(proposal, Mapping) else None
        if isinstance(content, Mapping):
            for key, value in content.items():
                if isinstance(value, str) and _unsafe_text(value):
                    diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_UNSAFE_TEXT, "proposal text contains a credential, runtime target, or unsafe path", f"proposals[{index}].content.{key}"))
    return diagnostics


def validate_adaptation_proposal_ledger(ledger: Any) -> Dict[str, Any]:
    """Validate one proposal ledger without provider or write side effects."""
    if not isinstance(ledger, Mapping):
        return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal ledger must be an object")]}
    candidate = deepcopy(dict(ledger))
    diagnostics = _schema_diagnostics(candidate)
    diagnostics.extend(_semantic_diagnostics(candidate))
    diagnostics = _bounded_diagnostics(diagnostics)
    return {
        "valid": not diagnostics,
        "status": "valid" if not diagnostics else "invalid",
        "ledger": candidate if not diagnostics else None,
        "diagnostics": diagnostics,
    }


def _normalized_dossier(dossier: Mapping[str, Any], diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    candidate = dict(dossier)
    full_contract = any(key in candidate for key in ("version", "adaptation_mode", "source_hash", "adapted_title"))
    if not full_contract:
        return deepcopy(candidate)
    result = validate_adaptation_dossier(candidate)
    if not result.get("valid") or not isinstance(result.get("dossier"), Mapping):
        for item in result.get("diagnostics") or []:
            if isinstance(item, Mapping):
                diagnostics.append(_diagnostic(
                    PROPOSAL_DIAGNOSTIC_CODE_INVALID_DOSSIER,
                    str(item.get("message") or "adaptation dossier is invalid"),
                    str(item.get("path") or "dossier"),
                ))
        return {}
    return deepcopy(dict(result["dossier"]))


def _normalize_candidate_list(
    values: Any,
    *,
    proposal_type: str,
    source_field: str,
    diagnostics: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal source field must be a list", source_field))
        return []
    ordered = sorted(list(values)[:MAX_CANDIDATE_SCAN], key=_stable_input_key)
    if len(values) > MAX_CANDIDATE_SCAN:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_TRUNCATED, "proposal source field exceeded its scan bound", source_field, PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING))
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(ordered):
        content = _normalize_content(item, proposal_type, f"{source_field}[{index}]", diagnostics)
        if content is None:
            continue
        identity = _canonical_json(content)
        if identity in seen:
            diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_DUPLICATE, "duplicate proposal was removed", f"{source_field}[{index}]", PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING))
            continue
        seen.add(identity)
        normalized.append({"proposal_type": proposal_type, "source_field": source_field, "content": content})
    return normalized


def prepare_adaptation_proposal_ledger(
    dossier: Mapping[str, Any],
    *,
    attempt_metadata: Mapping[str, Any],
    world_context_provenance: Any = None,
    revision_number: Optional[int] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a validated proposal ledger result without writing it."""
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(dossier, Mapping):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_DOSSIER, "adaptation dossier must be an object", "dossier"))
        return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": _bounded_diagnostics(diagnostics)}
    if not isinstance(attempt_metadata, Mapping):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "attempt metadata must be an object", "attempt_metadata"))
        return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": _bounded_diagnostics(diagnostics)}

    normalized_dossier = _normalized_dossier(dossier, diagnostics)
    attempt_id = attempt_metadata.get("attempt_id")
    if not _safe_attempt_id(attempt_id):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "attempt_id is not path-safe", "attempt_metadata.attempt_id"))
    attempt_number = attempt_metadata.get("attempt_number", 1)
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or not 1 <= attempt_number <= 1_000_000:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "attempt_number is invalid", "attempt_metadata.attempt_number"))
        attempt_number = 1
    resolved_revision = attempt_metadata.get("revision_number", 0) if revision_number is None else revision_number
    if isinstance(resolved_revision, bool) or not isinstance(resolved_revision, int) or not 0 <= resolved_revision <= 100:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "revision_number is invalid", "revision_number"))
        resolved_revision = 0

    source_hash = attempt_metadata.get("source_hash") or normalized_dossier.get("source_hash")
    if not _safe_hash(source_hash):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_SOURCE, "source_hash must be a lowercase SHA-256 digest", "source_hash"))
        source_hash = "0" * 64
    else:
        source_hash = str(source_hash).lower()
    dossier_hash = normalized_dossier.get("source_hash")
    if dossier_hash not in (None, "") and dossier_hash != source_hash:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_SOURCE, "dossier source_hash does not match attempt provenance", "dossier.source_hash"))

    source_path = attempt_metadata.get("source_path")
    if not _safe_relative_path(source_path):
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_SOURCE, "source_path must be project-relative", "attempt_metadata.source_path"))
        source_path = "adaptation_inputs/unresolved_source"
    source_title = _normalize_required_text(
        attempt_metadata.get("source_title") or normalized_dossier.get("source_title") or "Adapted source",
        "source_title",
        diagnostics,
        limit=MAX_SOURCE_TITLE_CHARS,
    ) or "Adapted source"
    source_profile = _ascii_text(
        normalized_dossier.get("source_profile") or attempt_metadata.get("source_profile") or "unknown",
        32,
    ) or "unknown"
    adaptation_mode = attempt_metadata.get("adaptation_mode", ADAPTATION_MODE_LLM)
    if adaptation_mode != ADAPTATION_MODE_LLM:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "proposal ledger requires llm_adaptation mode", "adaptation_mode"))

    world_input = world_context_provenance
    if world_input is None:
        world_input = attempt_metadata.get("world_context_provenance") or attempt_metadata
    world = build_world_context_provenance(world_input)
    context_status = _context_status(world)
    if context_status != PROPOSAL_CONTEXT_AVAILABLE:
        diagnostics.append(_diagnostic(
            PROPOSAL_DIAGNOSTIC_CODE_CONTEXT_DEGRADED,
            "world context is unavailable or degraded; proposals are not grounded canon",
            "provenance.world_context_provenance",
            PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING,
        ))

    normalized_model = _normalize_model_metadata(
        model_metadata if model_metadata is not None else attempt_metadata.get("model_metadata"),
        diagnostics,
    )
    hooks = _normalize_candidate_list(
        normalized_dossier.get("world_narrative_hooks"),
        proposal_type=PROPOSAL_TYPE_WORLD_HOOK,
        source_field="world_narrative_hooks",
        diagnostics=diagnostics,
    )
    continuations = _normalize_candidate_list(
        normalized_dossier.get("continuity_hints"),
        proposal_type=PROPOSAL_TYPE_CONTINUATION,
        source_field="continuity_hints",
        diagnostics=diagnostics,
    )
    raw_hook_count = len(hooks)
    raw_continuation_count = len(continuations)
    hooks = hooks[:MAX_WORLD_HOOKS]
    continuations = continuations[:MAX_CONTINUATIONS]
    candidates = sorted(hooks + continuations, key=lambda item: (item["proposal_type"], _canonical_json(item["content"])))[:MAX_PROPOSALS]
    proposals: List[Dict[str, Any]] = []
    for candidate in candidates:
        proposal_type = str(candidate["proposal_type"])
        content = dict(candidate["content"])
        proposals.append({
            "proposal_id": _proposal_id(str(attempt_id or ""), int(resolved_revision), proposal_type, content),
            "proposal_type": proposal_type,
            "source_field": candidate["source_field"],
            "approval_status": PROPOSAL_APPROVAL_STATUS_PENDING,
            "apply_allowed": False,
            "content": content,
        })

    if raw_hook_count > MAX_WORLD_HOOKS or raw_continuation_count > MAX_CONTINUATIONS or raw_hook_count + raw_continuation_count > MAX_PROPOSALS:
        diagnostics.append(_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_TRUNCATED, "proposal ledger was bounded to its maximum proposal count", "proposals", PROPOSAL_DIAGNOSTIC_SEVERITY_WARNING))
    if diagnostics and any(item.get("severity") == "error" for item in diagnostics):
        return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": _bounded_diagnostics(diagnostics)}

    ledger: Dict[str, Any] = {
        "version": ADAPTATION_PROPOSAL_CONTRACT_VERSION,
        "kind": ADAPTATION_PROPOSAL_KIND,
        "attempt_id": str(attempt_id),
        "attempt_number": int(attempt_number),
        "revision_number": int(resolved_revision),
        "created_at": created_at or _utc_now_iso(),
        "status": PROPOSAL_STATUS_PENDING_APPROVAL if proposals else PROPOSAL_STATUS_NO_PROPOSALS,
        "context_status": context_status,
        "approval_status": PROPOSAL_APPROVAL_STATUS_PENDING,
        "approval_required": True,
        "approval_path": PROPOSAL_APPROVAL_PATH,
        "auto_apply": False,
        "apply_allowed": False,
        "canon_write_allowed": False,
        "registry_write_allowed": False,
        "mechanical_write_allowed": False,
        "world_hooks_proposed": any(item["proposal_type"] == PROPOSAL_TYPE_WORLD_HOOK for item in proposals),
        "continuations_proposed": any(item["proposal_type"] == PROPOSAL_TYPE_CONTINUATION for item in proposals),
        "proposal_count": len(proposals),
        "proposals": proposals,
        "provenance": {
            "source_title": source_title,
            "source_hash": source_hash,
            "source_path": str(source_path),
            "source_profile": source_profile,
            "adaptation_mode": ADAPTATION_MODE_LLM,
            "dossier_hash": _sha256(normalized_dossier),
            "world_context_provenance": world,
        },
        "model_metadata": normalized_model,
        "diagnostics": _bounded_diagnostics(diagnostics),
        "ledger_hash": "0" * 64,
    }
    if not _TIMESTAMP_RE.fullmatch(str(ledger["created_at"])):
        return {
            "valid": False,
            "status": "invalid",
            "ledger": None,
            "diagnostics": _bounded_diagnostics(diagnostics + [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_ATTEMPT, "created_at must be a UTC timestamp", "created_at")]),
        }
    ledger["ledger_hash"] = _ledger_hash(ledger)
    validation = validate_adaptation_proposal_ledger(ledger)
    if not validation.get("valid"):
        return validation
    return {"valid": True, "status": "valid", "ledger": ledger, "diagnostics": ledger["diagnostics"]}


def build_adaptation_proposal_ledger(
    dossier: Mapping[str, Any],
    *,
    attempt_metadata: Mapping[str, Any],
    world_context_provenance: Any = None,
    revision_number: Optional[int] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one validated, pending-only proposal ledger without writing it."""
    result = prepare_adaptation_proposal_ledger(
        dossier,
        attempt_metadata=attempt_metadata,
        world_context_provenance=world_context_provenance,
        revision_number=revision_number,
        model_metadata=model_metadata,
        created_at=created_at,
    )
    if not result.get("valid") or not isinstance(result.get("ledger"), Mapping):
        first = (result.get("diagnostics") or [{}])[0]
        raise ValueError(_ascii_text(first.get("message") or "invalid adaptation proposal ledger", 500))
    return deepcopy(dict(result["ledger"]))


def _resolve_workspace(workspace: Path) -> Path:
    candidate = Path(workspace)
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(_REPO_ROOT)
    except ValueError as exc:
        raise ValueError("proposal workspace must remain inside the repository") from exc
    if not relative.parts or len(relative.as_posix()) > MAX_WORKSPACE_PATH_CHARS:
        raise ValueError("proposal workspace is invalid")
    if any(part.lower() in _SENSITIVE_WORKSPACE_PARTS for part in relative.parts):
        raise ValueError("proposal workspace cannot be a live module or runtime state path")
    return resolved


def get_adaptation_proposal_path(
    workspace: Path,
    attempt_id: str,
    revision_number: int = 0,
) -> Path:
    """Return the attempt-scoped proposal path without creating it."""
    if not _safe_attempt_id(attempt_id):
        raise ValueError("attempt_id is not path-safe")
    if isinstance(revision_number, bool) or not isinstance(revision_number, int) or not 0 <= revision_number <= 100:
        raise ValueError("revision_number is outside the supported range")
    root = _resolve_workspace(workspace) / "adaptation_attempts" / attempt_id
    if revision_number:
        root = root / "revisions" / f"revision_{revision_number:03d}"
    return root / ADAPTATION_PROPOSAL_FILENAME


def persist_adaptation_proposal_ledger(
    workspace: Path,
    ledger: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> bool:
    """Persist a valid proposal ledger atomically inside its attempt workspace."""
    validation = validate_adaptation_proposal_ledger(ledger)
    if not validation.get("valid"):
        return False
    normalized = validation["ledger"]
    try:
        target = get_adaptation_proposal_path(
            workspace,
            str(normalized["attempt_id"]),
            int(normalized["revision_number"]),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    reservation: Optional[Path] = None
    try:
        if target.exists() and not overwrite:
            return False
        if not overwrite:
            reservation = Path(str(target) + ".reserve")
            fd = os.open(str(reservation), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            if target.exists():
                return False
        return bool(
            safe_write_json(
                str(target),
                normalized,
                create_backup=bool(overwrite),
                json_kwargs={"ensure_ascii": True, "sort_keys": True},
            )
        )
    except Exception:
        return False
    finally:
        if reservation is not None:
            try:
                reservation.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass


def load_adaptation_proposal_ledger(
    workspace: Path,
    attempt_id: str,
    revision_number: int = 0,
) -> Optional[Dict[str, Any]]:
    """Load one proposal ledger only when its contract remains valid."""
    try:
        path = get_adaptation_proposal_path(workspace, attempt_id, revision_number)
        raw = safe_read_json(str(path))
    except Exception:
        return None
    validation = validate_adaptation_proposal_ledger(raw)
    return validation.get("ledger") if validation.get("valid") else None


def parse_adaptation_proposal_ledger(raw: Any) -> Dict[str, Any]:
    """Parse strict JSON or a mapping into a validated proposal ledger."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal ledger is not valid UTF-8 JSON")]}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"valid": False, "status": "invalid", "ledger": None, "diagnostics": [_diagnostic(PROPOSAL_DIAGNOSTIC_CODE_INVALID_PROPOSAL, "proposal ledger JSON is invalid: " + _ascii_text(exc))]}
    return validate_adaptation_proposal_ledger(raw)


def guard_adaptation_proposal_application(
    ledger: Any,
    *,
    approval_record: Any = None,
) -> Dict[str, Any]:
    """Fail closed at the boundary before any future approval implementation.

    This function intentionally never returns an application authorization and
    never writes a file. A separate world-narrative approval path must consume
    the pending ledger and implement its own transaction in a later task.
    """
    validation = validate_adaptation_proposal_ledger(ledger)
    if not validation.get("valid"):
        return {
            "status": "invalid",
            "approved": False,
            "apply_allowed": False,
            "approval_required": True,
            "approval_path": PROPOSAL_APPROVAL_PATH,
            "diagnostics": validation.get("diagnostics", []),
        }
    normalized = validation["ledger"]
    if not normalized.get("proposals"):
        return {
            "status": PROPOSAL_STATUS_NO_PROPOSALS,
            "approved": False,
            "apply_allowed": False,
            "approval_required": True,
            "approval_path": PROPOSAL_APPROVAL_PATH,
            "ledger_hash": normalized.get("ledger_hash"),
            "diagnostics": [],
        }
    return {
        "status": "approval_required",
        "approved": False,
        "apply_allowed": False,
        "approval_required": True,
        "approval_path": PROPOSAL_APPROVAL_PATH,
        "ledger_hash": normalized.get("ledger_hash"),
        "proposal_ids": [item.get("proposal_id") for item in normalized.get("proposals", [])],
        "approval_record_ignored": approval_record is not None,
        "reason": "No adaptation task may apply world proposals; use the separate world-narrative approval path.",
        "diagnostics": [],
    }


__all__ = [
    "ADAPTATION_PROPOSAL_CONTRACT_VERSION",
    "ADAPTATION_PROPOSAL_FILENAME",
    "ADAPTATION_PROPOSAL_KIND",
    "ADAPTATION_PROPOSAL_SCHEMA_VERSION",
    "MAX_CONTINUATIONS",
    "MAX_PROPOSALS",
    "MAX_WORLD_HOOKS",
    "PROPOSAL_APPROVAL_PATH",
    "PROPOSAL_APPROVAL_STATUS_PENDING",
    "PROPOSAL_CONTEXT_AVAILABLE",
    "PROPOSAL_CONTEXT_DEGRADED",
    "PROPOSAL_CONTEXT_INVALID",
    "PROPOSAL_CONTEXT_UNAVAILABLE",
    "PROPOSAL_STATUS_NO_PROPOSALS",
    "PROPOSAL_STATUS_PENDING_APPROVAL",
    "PROPOSAL_TYPE_CONTINUATION",
    "PROPOSAL_TYPE_WORLD_HOOK",
    "build_adaptation_proposal_ledger",
    "get_adaptation_proposal_path",
    "guard_adaptation_proposal_application",
    "load_adaptation_proposal_ledger",
    "parse_adaptation_proposal_ledger",
    "persist_adaptation_proposal_ledger",
    "prepare_adaptation_proposal_ledger",
    "validate_adaptation_proposal_ledger",
]
