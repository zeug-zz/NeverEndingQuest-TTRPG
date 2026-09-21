# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Safe Adaptation Rebuild Directives
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free parsing and validation for the LLM adaptation rebuild
directive.  The directive is a declarative handoff for a later fresh build;
it is not a file patch, a filesystem command, or a publication decision.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_MODE_LLM,
    parse_adaptation_dossier,
)
from utils.toolkit_adaptation_failure_packet import (
    PACKET_STATUS_BLOCKED,
    validate_adaptation_failure_packet,
)
from utils.toolkit_adaptation_staging import (
    STAGING_STATE_RESERVED,
    validate_adaptation_staging_target,
)


ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION = (
    "toolkit_adaptation_rebuild_directive.v1"
)
REBUILD_DIRECTIVE_CONTRACT_VERSION = (
    ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION
)
REBUILD_DIRECTIVE_ACTION_FRESH_BUILD = "fresh_build"
REBUILD_DIRECTIVE_TARGET_STAGING = "staging"
REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER = "revised_dossier"

VALID_REBUILD_DIRECTIVE_SCOPES = (
    "semantic",
    "semantic_adaptation",
    "content",
)

MAX_DIRECTIVE_SERIALIZED_CHARS = 12_000
MAX_DIRECTIVE_REASON_CHARS = 800
MAX_DIRECTIVE_CONSTRAINTS = 8
MAX_DIRECTIVE_CONSTRAINT_CHARS = 400
MAX_REVISED_DOSSIER_CHARS = 48_000
MAX_DIAGNOSTICS = 32

DIRECTIVE_STATUS_VALID = "valid"
DIRECTIVE_STATUS_INVALID = "invalid"

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
DIAGNOSTIC_CODE_INVALID_TYPE = "invalid_type"
DIAGNOSTIC_CODE_DIRECTIVE_INVALID = "rebuild_directive_invalid"
DIAGNOSTIC_CODE_UNEXPECTED_FIELD = "unexpected_field"
DIAGNOSTIC_CODE_FORBIDDEN_FIELD = "forbidden_change_payload"
DIAGNOSTIC_CODE_UNSAFE_CONTENT = "unsafe_content"
DIAGNOSTIC_CODE_TARGET_INVALID = "rebuild_target_invalid"
DIAGNOSTIC_CODE_TARGET_REQUIRED = "staging_target_required"
DIAGNOSTIC_CODE_TARGET_NOT_RESERVED = "staging_target_not_reserved"
DIAGNOSTIC_CODE_TARGET_IDENTITY_MISMATCH = "staging_target_identity_mismatch"
DIAGNOSTIC_CODE_PACKET_INVALID = "failure_packet_invalid"
DIAGNOSTIC_CODE_DOSSIER_INVALID = "revised_dossier_invalid"
DIAGNOSTIC_CODE_DOSSIER_NOT_READY = "revised_dossier_not_ready"
DIAGNOSTIC_CODE_DOSSIER_TOO_LARGE = "revised_dossier_too_large"
DIAGNOSTIC_CODE_PROVENANCE_MISMATCH = "revision_provenance_mismatch"

_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_STAGE_ID_RE = re.compile(
    r"^(?P<attempt>[a-z0-9][a-z0-9._-]{0,63}):revision_(?P<revision>[0-9]{3})$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_URL_RE = re.compile(r"(?i)\b(?:https?|file|ftp|ssh)://")
_RUNTIME_TARGET_RE = re.compile(
    r"(?i)(?:world_registry\.json|campaign\.json|party_tracker\.json|"
    r"player_quests_[^\s,;]+|modules/[^\s,;]+|characters/[^\s,;]+|"
    r"encounters(?:/|\\)|data/runtime(?:/|\\))"
)
_SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)"
    r"\s*[:=]\s*[^\s,;]+|\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{7,}"
)
_EXECUTABLE_RE = re.compile(
    r"(?i)(?:\$\(|`|\b(?:bash|zsh|powershell|cmd|python|perl|ruby|node|"
    r"shell|subprocess|exec|eval|curl|wget|chmod|mkdir|touch|rm|"
    r"command|script|file[_ -]?patch|json[_ -]?path|target[_ -]?path|"
    r"module[_ -]?dir|output[_ -]?directory)\b)"
)

_DIRECTIVE_FIELDS = frozenset(
    {
        "version",
        "action",
        "target",
        "basis",
        "scope",
        "reason",
        "constraints",
        # ``guidance`` is retained only as a compatibility spelling for the
        # task-5.2 outer auditor contract.  Strict validation maps it to the
        # same bounded logical constraint surface.
        "guidance",
    }
)
_TARGET_FIELDS = frozenset(
    {
        "kind",
        "target_kind",
        "stage_id",
        "attempt_id",
        "attempt_number",
        "revision_number",
        "source_hash",
    }
)
_FORBIDDEN_FIELDS = frozenset(
    {
        "code",
        "command",
        "commands",
        "file_patch",
        "file_patches",
        "json_path",
        "module_dir",
        "operations",
        "ops",
        "output_directory",
        "patch",
        "patches",
        "path",
        "target_path",
        "write",
        "writes",
    }
)


def _ascii_text(value: Any, limit: int = 240) -> str:
    text = str(value).replace("\x00", " ").encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {
        "code": _ascii_text(code, 120),
        "message": _ascii_text(message, 280),
        "path": _ascii_text(path, 200),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def _result(
    *,
    valid: bool,
    directive: Optional[Mapping[str, Any]],
    plan: Optional[Mapping[str, Any]],
    dossier: Optional[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    ordered = sorted(
        (dict(item) for item in diagnostics),
        key=lambda item: (
            str(item.get("path", "")),
            str(item.get("code", "")),
            str(item.get("message", "")),
        ),
    )
    return {
        "valid": bool(valid),
        "status": DIRECTIVE_STATUS_VALID if valid else DIRECTIVE_STATUS_INVALID,
        "safe": bool(valid),
        "directive": deepcopy(dict(directive)) if isinstance(directive, Mapping) else None,
        "plan": deepcopy(dict(plan)) if valid and isinstance(plan, Mapping) else None,
        "dossier": deepcopy(dict(dossier)) if valid and isinstance(dossier, Mapping) else None,
        "diagnostics": ordered[:MAX_DIAGNOSTICS],
        "writes": [],
        "changed_files": [],
        "side_effects": False,
        "write_performed": False,
    }


def _parse_json_value(raw_directive: Any) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    if isinstance(raw_directive, Mapping):
        return deepcopy(dict(raw_directive)), []
    if isinstance(raw_directive, bytes):
        try:
            raw_directive = raw_directive.decode("utf-8")
        except UnicodeDecodeError:
            return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "directive is not valid UTF-8 JSON")]
    if not isinstance(raw_directive, str):
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_TYPE, "directive must be a JSON object or JSON text")]
    text = raw_directive.strip()
    if not text:
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "directive JSON is empty")]
    if len(text) > MAX_DIRECTIVE_SERIALIZED_CHARS:
        return None, [_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "directive exceeds its serialized size bound")]
    if not text.isascii():
        return None, [_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "directive must be ASCII-only")]
    if "```" in text:
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "markdown fences are not accepted")]
    try:
        parsed = json.loads(
            text,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("non-standard JSON constant: " + value)
            ),
        )
    except Exception:
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "directive is not valid JSON")]
    if not isinstance(parsed, dict):
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_TYPE, "directive JSON must be an object")]
    return deepcopy(parsed), []


def _unsafe_text(value: Any, path: str, *, target_text: bool = False) -> List[Dict[str, str]]:
    if not isinstance(value, str):
        return [_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "logical directive text must be a string", path)]
    diagnostics: List[Dict[str, str]] = []
    text = value.strip()
    if not text:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "logical directive text must not be empty", path))
        return diagnostics
    if len(text) > MAX_DIRECTIVE_CONSTRAINT_CHARS and not path.endswith("reason"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "logical constraint exceeds its size bound", path))
    if path.endswith("reason") and len(text) > MAX_DIRECTIVE_REASON_CHARS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "directive reason exceeds its size bound", path))
    if not text.isascii():
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "directive text must be ASCII-only", path))
    if _URL_RE.search(text):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "URLs are not allowed in a rebuild directive", path))
    if _SECRET_RE.search(text):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "credentials are not allowed in a rebuild directive", path))
    if _RUNTIME_TARGET_RE.search(text):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_FORBIDDEN_FIELD, "runtime targets are not allowed in a rebuild directive", path))
    if "\\" in text or ".." in text.split("/") or text.startswith("/") or _DRIVE_PATH_RE.match(text):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_FORBIDDEN_FIELD, "filesystem paths are not allowed in a rebuild directive", path))
    if _EXECUTABLE_RE.search(text):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_FORBIDDEN_FIELD, "executable instructions are not allowed in a rebuild directive", path))
    if target_text and text != REBUILD_DIRECTIVE_TARGET_STAGING:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target must be the logical staging target", path))
    return diagnostics


def _validate_identity_fields(
    target: Mapping[str, Any],
    diagnostics: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    unexpected = sorted(set(target) - _TARGET_FIELDS)
    for key in unexpected:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_FORBIDDEN_FIELD, "target contains an unsupported field", "target." + str(key)))
    if "kind" in target and "target_kind" in target:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target may use only one staging kind field", "target"))
    kind = target.get("kind", target.get("target_kind"))
    if kind != REBUILD_DIRECTIVE_TARGET_STAGING:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target kind must be staging", "target.kind"))
    required = ("stage_id", "attempt_id", "attempt_number", "revision_number", "source_hash")
    for key in required:
        if key not in target:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target identity field is required", "target." + key))

    attempt_id = target.get("attempt_id")
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target attempt_id is not path-safe", "target.attempt_id"))
    attempt_number = target.get("attempt_number")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or not 1 <= attempt_number <= 1_000_000:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target attempt_number is invalid", "target.attempt_number"))
    revision_number = target.get("revision_number")
    if isinstance(revision_number, bool) or not isinstance(revision_number, int) or not 0 <= revision_number <= 100:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target revision_number is invalid", "target.revision_number"))
    source_hash = target.get("source_hash")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target source_hash is invalid", "target.source_hash"))
    stage_id = target.get("stage_id")
    stage_match = _STAGE_ID_RE.fullmatch(stage_id) if isinstance(stage_id, str) else None
    if stage_match is None:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "target stage_id is invalid", "target.stage_id"))
    elif isinstance(attempt_id, str) and isinstance(revision_number, int):
        expected_stage_id = f"{attempt_id}:revision_{revision_number:03d}"
        if stage_id != expected_stage_id:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_IDENTITY_MISMATCH, "target stage_id does not match attempt and revision", "target.stage_id"))
    if diagnostics:
        return None
    return {
        "kind": REBUILD_DIRECTIVE_TARGET_STAGING,
        "stage_id": stage_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "revision_number": revision_number,
        "source_hash": source_hash,
    }


def validate_rebuild_directive_shape(
    directive: Any,
    *,
    require_identity: bool = False,
) -> List[Dict[str, str]]:
    """Validate only the JSON shape of an adaptation rebuild directive.

    This helper is intentionally filesystem-free.  The auditor response
    parser uses it to share the adaptation contract without importing or
    changing the legacy accurate-ingest patch validator.  Full safety
    validation additionally requires a Python-owned reserved staging target.
    """
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(directive, Mapping):
        return [_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "rebuild_directive must be an object", "rebuild_directive")]
    value = dict(directive)
    for key in sorted(set(value) - _DIRECTIVE_FIELDS):
        code = DIAGNOSTIC_CODE_FORBIDDEN_FIELD if key.lower() in _FORBIDDEN_FIELDS else DIAGNOSTIC_CODE_UNEXPECTED_FIELD
        diagnostics.append(_diagnostic(code, "rebuild directive contains an unsupported field", "rebuild_directive." + str(key)))
    if value.get("version") not in (None, ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "unsupported rebuild directive version", "rebuild_directive.version"))
    if value.get("action") != REBUILD_DIRECTIVE_ACTION_FRESH_BUILD:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "rebuild directive must request fresh_build", "rebuild_directive.action"))
    if value.get("basis") != REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "rebuild directive basis must be revised_dossier", "rebuild_directive.basis"))

    target = value.get("target")
    if isinstance(target, str):
        diagnostics.extend(_unsafe_text(target, "rebuild_directive.target", target_text=True))
    elif isinstance(target, Mapping):
        _validate_identity_fields(target, diagnostics)
    else:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_INVALID, "rebuild directive target must be staging or a staging identity object", "rebuild_directive.target"))

    constraints = value.get("constraints")
    guidance = value.get("guidance")
    if constraints is None and guidance is not None:
        constraints = guidance

    scope = value.get("scope")
    if scope is not None:
        if isinstance(scope, str):
            if scope.strip().lower() not in VALID_REBUILD_DIRECTIVE_SCOPES:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "scope is not an allowed logical scope", "rebuild_directive.scope"))
            diagnostics.extend(_unsafe_text(scope, "rebuild_directive.scope"))
        elif isinstance(scope, list) and 1 <= len(scope) <= 4:
            for index, item in enumerate(scope):
                if not isinstance(item, str) or item.strip().lower() not in VALID_REBUILD_DIRECTIVE_SCOPES:
                    diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "scope item is not an allowed logical scope", f"rebuild_directive.scope[{index}]"))
                elif isinstance(item, str):
                    diagnostics.extend(_unsafe_text(item, f"rebuild_directive.scope[{index}]"))
        else:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "scope must be a bounded logical value", "rebuild_directive.scope"))
    elif require_identity and constraints is None and guidance is None:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "strict rebuild directive requires scope", "rebuild_directive.scope"))

    reason = value.get("reason")
    if reason is not None:
        diagnostics.extend(_unsafe_text(reason, "rebuild_directive.reason"))
    elif require_identity and constraints is None and guidance is None:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "strict rebuild directive requires reason", "rebuild_directive.reason"))

    if constraints is not None:
        if not isinstance(constraints, list) or not 1 <= len(constraints) <= MAX_DIRECTIVE_CONSTRAINTS:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "constraints must be a bounded non-empty list", "rebuild_directive.constraints"))
        else:
            for index, item in enumerate(constraints):
                diagnostics.extend(_unsafe_text(item, f"rebuild_directive.constraints[{index}]"))
    elif require_identity:
        # Task 5.2 emitted the compatibility spelling ``guidance``.  It is
        # treated as the same bounded logical constraint list when the newer
        # scope/reason/constraints fields are absent.
        if guidance is not None:
            return diagnostics
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DIRECTIVE_INVALID, "strict rebuild directive requires constraints", "rebuild_directive.constraints"))

    return diagnostics


def _validate_packet_identity(
    failure_packet: Any,
    diagnostics: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(failure_packet, Mapping):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PACKET_INVALID, "failure_packet is required for strict directive validation", "failure_packet"))
        return None
    packet_result = validate_adaptation_failure_packet(failure_packet)
    if not packet_result.get("valid"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PACKET_INVALID, "failure_packet does not satisfy its bounded contract", "failure_packet"))
        return None
    if failure_packet.get("packet_status") != PACKET_STATUS_BLOCKED:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PACKET_INVALID, "failure_packet must be blocked", "failure_packet.packet_status"))
        return None
    attempt = failure_packet.get("attempt_metadata")
    if not isinstance(attempt, Mapping):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PACKET_INVALID, "failure_packet attempt metadata is missing", "failure_packet.attempt_metadata"))
        return None
    return dict(attempt)


def _validate_dossier_content(
    revised_dossier: Any,
    *,
    attempt: Mapping[str, Any],
    diagnostics: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    try:
        if isinstance(revised_dossier, Mapping):
            serialized = json.dumps(
                revised_dossier,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        else:
            serialized = str(revised_dossier)
    except (TypeError, ValueError):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_INVALID, "revised dossier is not JSON serializable", "revised_dossier"))
        return None
    if len(serialized) > MAX_REVISED_DOSSIER_CHARS:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_TOO_LARGE, "revised dossier exceeds its size bound", "revised_dossier"))
        return None
    if not serialized.isascii():
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "revised dossier must be ASCII-only", "revised_dossier"))
        return None
    parsed = parse_adaptation_dossier(revised_dossier)
    if not parsed.get("valid"):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_INVALID, "revised dossier does not satisfy its schema", "revised_dossier"))
        return None
    if not parsed.get("build_ready") or parsed.get("dossier", {}).get("status") != ADAPTATION_DOSSIER_STATUS_READY:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_DOSSIER_NOT_READY, "revised dossier must be ready for a build", "revised_dossier.status"))
        return None
    dossier = parsed.get("dossier") or {}
    expected_fields = (
        "source_hash",
        "source_title",
        "source_profile",
        "rights_class",
        "rights_basis",
        "rights_review_required",
        "rights_review_status",
        "adaptation_mode",
    )
    for field in expected_fields:
        if field in attempt and dossier.get(field) != attempt.get(field):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PROVENANCE_MISMATCH, "revised dossier changed Python-owned provenance", "revised_dossier." + field))
    return deepcopy(dossier)


def _safe_dossier_fields(value: Any, path: str = "", depth: int = 0) -> List[Dict[str, str]]:
    """Reject executable or direct-write payloads nested in dossier content."""
    if depth > 12:
        return [_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "revised dossier nesting is too deep", path)]
    if isinstance(value, Mapping):
        diagnostics: List[Dict[str, str]] = []
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in _FORBIDDEN_FIELDS:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_FORBIDDEN_FIELD, "revised dossier contains a forbidden executable field", f"{path}.{key_text}".strip(".")))
            diagnostics.extend(_safe_dossier_fields(child, f"{path}.{key_text}".strip("."), depth + 1))
        return diagnostics[:MAX_DIAGNOSTICS]
    if isinstance(value, list):
        if len(value) > 256:
            return [_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "revised dossier list is too large", path)]
        diagnostics = []
        for index, child in enumerate(value):
            diagnostics.extend(_safe_dossier_fields(child, f"{path}[{index}]", depth + 1))
            if len(diagnostics) >= MAX_DIAGNOSTICS:
                break
        return diagnostics[:MAX_DIAGNOSTICS]
    if isinstance(value, str):
        return _unsafe_text(value, path)
    if isinstance(value, float) and not math.isfinite(value):
        return [_diagnostic(DIAGNOSTIC_CODE_UNSAFE_CONTENT, "revised dossier contains a non-finite number", path)]
    return []


def _normalize_scope(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value]
    return value


def validate_adaptation_rebuild_directive(
    directive: Any,
    *,
    failure_packet: Optional[Mapping[str, Any]] = None,
    staging_target: Optional[Mapping[str, Any]] = None,
    revised_dossier: Any = None,
    repo_root: Optional[Path] = None,
    require_reserved: bool = True,
) -> Dict[str, Any]:
    """Validate a rebuild directive and return a later-build plan only.

    The function is fail-closed and performs no writes, cleanup, provider
    calls, or build/publication actions.  A strict validation requires a
    Python-owned failure packet and a staging target reserved by
    ``toolkit_adaptation_staging``.  The model may supply only logical
    identity and bounded semantic constraints; the filesystem path is
    derived from the trusted staging metadata.
    """
    shape_diagnostics = validate_rebuild_directive_shape(directive, require_identity=True)
    diagnostics = list(shape_diagnostics)
    if diagnostics:
        return _result(valid=False, directive=directive if isinstance(directive, Mapping) else None, plan=None, dossier=None, diagnostics=diagnostics)

    value = deepcopy(dict(directive))
    attempt = _validate_packet_identity(failure_packet, diagnostics)
    if attempt is None:
        return _result(valid=False, directive=value, plan=None, dossier=None, diagnostics=diagnostics)

    target_value = value.get("target")
    identity: Optional[Dict[str, Any]]
    if isinstance(target_value, Mapping):
        identity = _validate_identity_fields(target_value, diagnostics)
    elif target_value == REBUILD_DIRECTIVE_TARGET_STAGING and isinstance(staging_target, Mapping):
        # The task-5.2 response contract uses the logical string "staging".
        # The Python-owned target supplies the actual attempt/revision
        # identity; no model-supplied path is accepted in this compatibility
        # form.
        identity = _validate_identity_fields(
            {
                "target_kind": staging_target.get("target_kind"),
                "stage_id": staging_target.get("stage_id"),
                "attempt_id": staging_target.get("attempt_id"),
                "attempt_number": staging_target.get("attempt_number"),
                "revision_number": staging_target.get("revision_number"),
                "source_hash": staging_target.get("source_hash"),
            },
            diagnostics,
        )
    else:
        identity = None
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_REQUIRED, "strict validation requires a Python-resolved staging identity", "target"))
    if identity is None:
        return _result(valid=False, directive=value, plan=None, dossier=None, diagnostics=diagnostics)

    if staging_target is None:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_REQUIRED, "a Python-owned reserved staging target is required", "staging_target"))
        return _result(valid=False, directive=value, plan=None, dossier=None, diagnostics=diagnostics)

    try:
        validated_target = validate_adaptation_staging_target(
            staging_target,
            source_hash=identity["source_hash"],
            attempt_id=identity["attempt_id"],
            attempt_number=identity["attempt_number"],
            revision_number=identity["revision_number"],
            repo_root=repo_root,
            require_reserved=require_reserved,
        )
    except Exception as exc:
        code = DIAGNOSTIC_CODE_TARGET_NOT_RESERVED if require_reserved else DIAGNOSTIC_CODE_TARGET_INVALID
        diagnostics.append(_diagnostic(code, "staging target is not a valid reserved adaptation target: " + _ascii_text(exc), "staging_target"))
        return _result(valid=False, directive=value, plan=None, dossier=None, diagnostics=diagnostics)

    for key in ("stage_id", "attempt_id", "attempt_number", "revision_number", "source_hash"):
        actual_key = "target_kind" if key == "kind" else key
        expected = identity.get(key)
        actual = validated_target.get(actual_key)
        if expected != actual:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_IDENTITY_MISMATCH, "directive identity does not match the reserved staging target", "target." + key))
    if validated_target.get("completion_state") != STAGING_STATE_RESERVED:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_NOT_RESERVED, "staging target must remain reserved before the later build task", "staging_target.completion_state"))

    expected_revision = attempt.get("revision_number")
    if isinstance(expected_revision, int) and identity["revision_number"] <= expected_revision:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_TARGET_IDENTITY_MISMATCH, "revision target must be newer than the failed attempt", "target.revision_number"))
    for field in ("attempt_id", "attempt_number", "source_hash"):
        if field in attempt and identity[field] != attempt[field]:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_PROVENANCE_MISMATCH, "directive identity does not preserve attempt provenance", "target." + field))

    normalized_dossier: Optional[Dict[str, Any]] = None
    if revised_dossier is not None:
        dossier_diagnostics = _safe_dossier_fields(revised_dossier, "revised_dossier")
        diagnostics.extend(dossier_diagnostics)
        if not dossier_diagnostics:
            normalized_dossier = _validate_dossier_content(
                revised_dossier,
                attempt=attempt,
                diagnostics=diagnostics,
            )

    if diagnostics:
        return _result(valid=False, directive=value, plan=None, dossier=None, diagnostics=diagnostics)

    normalized_constraints = value.get("constraints")
    if normalized_constraints is None:
        normalized_constraints = list(value.get("guidance") or [])
    plan: Dict[str, Any] = {
        "contract_version": ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
        "action": REBUILD_DIRECTIVE_ACTION_FRESH_BUILD,
        "basis": REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER,
        "scope": _normalize_scope(value.get("scope", "semantic_adaptation")),
        "reason": value.get("reason", "bounded semantic adaptation rebuild"),
        "constraints": list(normalized_constraints),
        "target": identity,
        "attempt_id": identity["attempt_id"],
        "attempt_number": identity["attempt_number"],
        "revision_number": identity["revision_number"],
        "source_hash": identity["source_hash"],
        "stage_id": identity["stage_id"],
        # This path is derived from Python-owned staging metadata.  It is not
        # accepted from, or interpreted as, an LLM target path.
        "resolved_staging_path": validated_target.get("path"),
        "dossier_present": normalized_dossier is not None,
    }
    return _result(
        valid=True,
        directive=value,
        plan=plan,
        dossier=normalized_dossier,
        diagnostics=[],
    )


def parse_adaptation_rebuild_directive(
    raw_directive: Any,
    **validation_kwargs: Any,
) -> Dict[str, Any]:
    """Parse strict JSON and optionally run full safe directive validation."""
    parsed, diagnostics = _parse_json_value(raw_directive)
    if diagnostics:
        return _result(valid=False, directive=None, plan=None, dossier=None, diagnostics=diagnostics)
    if validation_kwargs:
        return validate_adaptation_rebuild_directive(parsed, **validation_kwargs)
    shape_diagnostics = validate_rebuild_directive_shape(parsed, require_identity=False)
    return _result(
        valid=not shape_diagnostics,
        directive=parsed,
        plan=None,
        dossier=None,
        diagnostics=shape_diagnostics,
    )


def parse_and_validate_adaptation_rebuild_directive(
    raw_directive: Any,
    **validation_kwargs: Any,
) -> Dict[str, Any]:
    """Explicit alias for the strict parse-and-validate operation."""
    return parse_adaptation_rebuild_directive(raw_directive, **validation_kwargs)


validate_safe_rebuild_directive = validate_adaptation_rebuild_directive
parse_safe_rebuild_directive = parse_adaptation_rebuild_directive


__all__ = [
    "ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION",
    "REBUILD_DIRECTIVE_CONTRACT_VERSION",
    "REBUILD_DIRECTIVE_ACTION_FRESH_BUILD",
    "REBUILD_DIRECTIVE_TARGET_STAGING",
    "REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER",
    "VALID_REBUILD_DIRECTIVE_SCOPES",
    "DIRECTIVE_STATUS_VALID",
    "DIRECTIVE_STATUS_INVALID",
    "DIAGNOSTIC_CODE_DOSSIER_INVALID",
    "DIAGNOSTIC_CODE_DOSSIER_NOT_READY",
    "DIAGNOSTIC_CODE_DOSSIER_TOO_LARGE",
    "DIAGNOSTIC_CODE_FORBIDDEN_FIELD",
    "DIAGNOSTIC_CODE_PROVENANCE_MISMATCH",
    "DIAGNOSTIC_CODE_TARGET_IDENTITY_MISMATCH",
    "DIAGNOSTIC_CODE_TARGET_INVALID",
    "DIAGNOSTIC_CODE_TARGET_NOT_RESERVED",
    "DIAGNOSTIC_CODE_TARGET_REQUIRED",
    "parse_adaptation_rebuild_directive",
    "parse_and_validate_adaptation_rebuild_directive",
    "parse_safe_rebuild_directive",
    "validate_adaptation_rebuild_directive",
    "validate_rebuild_directive_shape",
    "validate_safe_rebuild_directive",
]
