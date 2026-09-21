# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Failure Classification
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded classification for the LLM adaptation lane.  The
classifier describes a failure for later Python orchestration; it never
decides that a module is publishable and never performs a retry, revision, or
file mutation.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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


FAILURE_CLASSIFICATION_CONTRACT_VERSION = (
    "toolkit_adaptation_failure_classification.v1"
)

FAILURE_GROUP_INFRASTRUCTURE = "infrastructure"
FAILURE_GROUP_CONTENT = "content"
FAILURE_GROUP_POLICY = "policy"
FAILURE_GROUP_PUBLICATION = "publication"
FAILURE_GROUP_UNKNOWN = "unknown"
VALID_FAILURE_GROUPS = (
    FAILURE_GROUP_INFRASTRUCTURE,
    FAILURE_GROUP_CONTENT,
    FAILURE_GROUP_POLICY,
    FAILURE_GROUP_PUBLICATION,
    FAILURE_GROUP_UNKNOWN,
)

CLASSIFICATION_STATUS_RETRYABLE = "retryable"
CLASSIFICATION_STATUS_REVISION_ELIGIBLE = "revision_eligible"
CLASSIFICATION_STATUS_BLOCKED = "blocked"
CLASSIFICATION_STATUS_TERMINAL = "terminal"
VALID_CLASSIFICATION_STATUSES = (
    CLASSIFICATION_STATUS_RETRYABLE,
    CLASSIFICATION_STATUS_REVISION_ELIGIBLE,
    CLASSIFICATION_STATUS_BLOCKED,
    CLASSIFICATION_STATUS_TERMINAL,
)

REVISION_BUDGET_DECISION_NOT_APPLICABLE = "not_applicable"
REVISION_BUDGET_DECISION_OPT_IN_REQUIRED = "explicit_opt_in_required"
REVISION_BUDGET_DECISION_ELIGIBLE = "eligible"
REVISION_BUDGET_DECISION_EXHAUSTED = "exhausted"
REVISION_BUDGET_DECISION_TERMINAL = "terminal_failure"
VALID_REVISION_BUDGET_DECISIONS = (
    REVISION_BUDGET_DECISION_NOT_APPLICABLE,
    REVISION_BUDGET_DECISION_OPT_IN_REQUIRED,
    REVISION_BUDGET_DECISION_ELIGIBLE,
    REVISION_BUDGET_DECISION_EXHAUSTED,
    REVISION_BUDGET_DECISION_TERMINAL,
)

INFRASTRUCTURE_FAILURE_CLASSES = frozenset(
    {
        FAILURE_CLASS_PROVIDER,
        FAILURE_CLASS_FILE,
        FAILURE_CLASS_DEPENDENCY,
        FAILURE_CLASS_QUOTA,
        FAILURE_CLASS_TIMEOUT,
    }
)
CONTENT_FAILURE_CLASSES = frozenset(
    {FAILURE_CLASS_MECHANICAL, FAILURE_CLASS_SEMANTIC}
)
POLICY_FAILURE_CLASSES = frozenset({FAILURE_CLASS_RIGHTS})
PUBLICATION_FAILURE_CLASSES = frozenset({FAILURE_CLASS_PUBLICATION})
REVISION_ELIGIBLE_CLASSES = frozenset(
    {FAILURE_CLASS_MECHANICAL, FAILURE_CLASS_SEMANTIC}
)

DEFAULT_MAX_SEMANTIC_REVISIONS = 1
MAX_SEMANTIC_REVISIONS = 2
MAX_ATTEMPT_ID_CHARS = 64
MAX_REVISION_NUMBER = 100
MAX_LABEL_CHARS = 96
MAX_CODE_CHARS = 120
MAX_MESSAGE_CHARS = 320
MAX_SIGNAL_CHARS = 240
MAX_INPUT_ITEMS = 24

_SAFE_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_WHITESPACE_RE = re.compile(r"\s+")
_TIMEOUT_RE = re.compile(
    r"\b(?:timeout(?:error)?|timed[ _-]?out|deadline[ _-]?exceeded|read[ _-]?timeout|connect[ _-]?timeout)\b|\b504\b",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(
    r"\b(?:quota(?:error)?|rate[ _-]?limit(?:error)?|too[ _-]?many[ _-]?requests|insufficient[ _-]?quota|billing)\b|\b429\b",
    re.IGNORECASE,
)
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_KEY_TOKEN_RE = re.compile(r"(?i)\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{7,}")
_PROMPT_PAYLOAD_RE = re.compile(
    r"(?i)(?:raw[_ -]?prompt|raw[_ -]?response|prompt[_ -]?content|response[_ -]?content)\s*[:=]\s*[^\n]+"
)

_SENSITIVE_INPUT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "content",
        "credential",
        "credentials",
        "password",
        "prompt",
        "raw_prompt",
        "raw_response",
        "response",
        "response_content",
        "response_text",
        "secret",
        "token",
    }
)
_SIGNAL_KEYS = frozenset(
    {
        "failure_class",
        "class",
        "category",
        "error_class",
        "provider_error_class",
        "status",
        "outcome",
        "code",
        "error_code",
        "gate",
        "domain",
        "stage",
        "failed_stage",
        "phase",
        "message",
        "reason",
        "detail",
        "error",
        "type",
        "exception_type",
        "rights_class",
        "rights_review_required",
        "rights_review_status",
        "publication_status",
        "build_status",
        "retryable",
        "terminal",
        "revision_eligible",
        "semantic_revision_eligible",
        "allow_semantic_revision",
        "revision_opt_in",
        "max_revisions",
        "revision_number",
        "attempt_id",
        "failure_kind",
        "content_reason",
        "hard_failure_reason",
        "source_grounded",
    }
)

_CLASS_ALIASES = {
    "provider": FAILURE_CLASS_PROVIDER,
    "provider_failed": FAILURE_CLASS_PROVIDER,
    "provider_failure": FAILURE_CLASS_PROVIDER,
    "api": FAILURE_CLASS_PROVIDER,
    "api_failure": FAILURE_CLASS_PROVIDER,
    "model": FAILURE_CLASS_PROVIDER,
    "model_response": FAILURE_CLASS_PROVIDER,
    "invalid_model_response": FAILURE_CLASS_PROVIDER,
    "refusal": FAILURE_CLASS_PROVIDER,
    "provider_refusal": FAILURE_CLASS_PROVIDER,
    "file": FAILURE_CLASS_FILE,
    "filesystem": FAILURE_CLASS_FILE,
    "file_error": FAILURE_CLASS_FILE,
    "io": FAILURE_CLASS_FILE,
    "io_error": FAILURE_CLASS_FILE,
    "persistence": FAILURE_CLASS_FILE,
    "artifact_persistence": FAILURE_CLASS_FILE,
    "prompt_failure": FAILURE_CLASS_FILE,
    "invalid_input": FAILURE_CLASS_FILE,
    "staging": FAILURE_CLASS_FILE,
    "missing_file": FAILURE_CLASS_FILE,
    "dependency": FAILURE_CLASS_DEPENDENCY,
    "dependency_missing": FAILURE_CLASS_DEPENDENCY,
    "missing_dependency": FAILURE_CLASS_DEPENDENCY,
    "import_error": FAILURE_CLASS_DEPENDENCY,
    "module_not_found": FAILURE_CLASS_DEPENDENCY,
    "parameter_resolution": FAILURE_CLASS_DEPENDENCY,
    "parameter_resolution_failure": FAILURE_CLASS_DEPENDENCY,
    "param_resolution": FAILURE_CLASS_DEPENDENCY,
    "param_resolution_failed": FAILURE_CLASS_DEPENDENCY,
    "quota": FAILURE_CLASS_QUOTA,
    "rate_limit": FAILURE_CLASS_QUOTA,
    "rate_limited": FAILURE_CLASS_QUOTA,
    "timeout": FAILURE_CLASS_TIMEOUT,
    "timed_out": FAILURE_CLASS_TIMEOUT,
    "rights": FAILURE_CLASS_RIGHTS,
    "rights_review": FAILURE_CLASS_RIGHTS,
    "policy": FAILURE_CLASS_RIGHTS,
    "mechanical": FAILURE_CLASS_MECHANICAL,
    "schema": FAILURE_CLASS_MECHANICAL,
    "schema_validation": FAILURE_CLASS_MECHANICAL,
    "structural": FAILURE_CLASS_MECHANICAL,
    "readiness": FAILURE_CLASS_MECHANICAL,
    "topology": FAILURE_CLASS_MECHANICAL,
    "semantic": FAILURE_CLASS_SEMANTIC,
    "semantic_gate": FAILURE_CLASS_SEMANTIC,
    "semantic_authority": FAILURE_CLASS_SEMANTIC,
    "semantic_probe": FAILURE_CLASS_SEMANTIC,
    "continuity": FAILURE_CLASS_SEMANTIC,
    "content": FAILURE_CLASS_SEMANTIC,
    "publication": FAILURE_CLASS_PUBLICATION,
    "publication_failure": FAILURE_CLASS_PUBLICATION,
    "registry": FAILURE_CLASS_PUBLICATION,
    "markdown": FAILURE_CLASS_PUBLICATION,
    "report_agreement": FAILURE_CLASS_PUBLICATION,
    "unknown": FAILURE_CLASS_UNKNOWN,
}

_DEFAULT_RETRYABLE = {
    FAILURE_CLASS_PROVIDER: True,
    FAILURE_CLASS_FILE: False,
    FAILURE_CLASS_DEPENDENCY: False,
    FAILURE_CLASS_QUOTA: True,
    FAILURE_CLASS_TIMEOUT: True,
    FAILURE_CLASS_RIGHTS: False,
    FAILURE_CLASS_MECHANICAL: False,
    FAILURE_CLASS_SEMANTIC: False,
    FAILURE_CLASS_PUBLICATION: False,
    FAILURE_CLASS_UNKNOWN: False,
}
_DEFAULT_TERMINAL = {
    FAILURE_CLASS_PROVIDER: False,
    FAILURE_CLASS_FILE: True,
    FAILURE_CLASS_DEPENDENCY: True,
    FAILURE_CLASS_QUOTA: False,
    FAILURE_CLASS_TIMEOUT: False,
    FAILURE_CLASS_RIGHTS: True,
    FAILURE_CLASS_MECHANICAL: True,
    FAILURE_CLASS_SEMANTIC: True,
    FAILURE_CLASS_PUBLICATION: True,
    FAILURE_CLASS_UNKNOWN: True,
}


def _ascii_text(value: Any, limit: int) -> str:
    """Return bounded, whitespace-normalized ASCII text with secrets removed."""
    if value is None:
        return ""
    text = str(value).replace("\x00", " ")
    text = _PROMPT_PAYLOAD_RE.sub("[REDACTED_PAYLOAD]", text)
    text = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED_CREDENTIAL]", text)
    text = _KEY_TOKEN_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _safe_label(value: Any, default: str = "unknown") -> str:
    text = _ascii_text(value, MAX_LABEL_CHARS)
    return text or default


def _safe_code(value: Any) -> str:
    text = _ascii_text(value, MAX_CODE_CHARS)
    return text or "unclassified_failure"


def _safe_attempt_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()[:MAX_ATTEMPT_ID_CHARS]
    return candidate if _SAFE_ATTEMPT_ID_RE.fullmatch(candidate) else ""


def _safe_non_negative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if value < 0 or value > MAX_REVISION_NUMBER:
        return default
    return value


def _safe_max_revisions(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_MAX_SEMANTIC_REVISIONS
    if value < 0 or value > MAX_SEMANTIC_REVISIONS:
        return DEFAULT_MAX_SEMANTIC_REVISIONS
    return value


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _mapping_value(mapping: Mapping[str, Any], *keys: str) -> Tuple[Any, bool]:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()], True
    return None, False


def _metadata_value(
    raw: Mapping[str, Any],
    metadata: Optional[Mapping[str, Any]],
    *keys: str,
) -> Any:
    value, present = _mapping_value(raw, *keys)
    if present:
        return value
    if isinstance(metadata, Mapping):
        value, present = _mapping_value(metadata, *keys)
        if present:
            return value
    nested, present = _mapping_value(raw, "attempt_metadata", "metadata")
    if isinstance(nested, Mapping):
        value, present = _mapping_value(nested, *keys)
        if present:
            return value
    return None


def _scalar_text(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return _ascii_text(value, MAX_SIGNAL_CHARS)
    return ""


def _collect_info(raw_failure: Any) -> Dict[str, Any]:
    """Collect only known scalar signals; never copy arbitrary provider data."""
    info: Dict[str, Any] = {
        "source": "unknown",
        "signals": [],
        "fields": {},
        "message": "",
    }
    if isinstance(raw_failure, BaseException):
        info["source"] = "exception"
        info["fields"] = {
            "exception_type": type(raw_failure).__name__,
            "message": str(raw_failure),
        }
        return info
    if isinstance(raw_failure, str):
        info["source"] = "message"
        info["fields"] = {"message": raw_failure}
        return info
    if not isinstance(raw_failure, Mapping):
        if raw_failure is not None:
            info["source"] = "object"
            info["fields"] = {"type": type(raw_failure).__name__}
        return info

    info["source"] = "payload"
    fields: Dict[str, Any] = {}
    for raw_key, value in list(raw_failure.items())[:MAX_INPUT_ITEMS]:
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip().lower()
        if key in _SENSITIVE_INPUT_KEYS or key not in _SIGNAL_KEYS:
            continue
        if isinstance(value, Mapping):
            for nested_key, nested_value in list(value.items())[:MAX_INPUT_ITEMS]:
                normalized_nested_key = str(nested_key).strip().lower()
                if normalized_nested_key in _SENSITIVE_INPUT_KEYS:
                    continue
                if normalized_nested_key in _SIGNAL_KEYS:
                    scalar = _scalar_text(nested_value)
                    if scalar:
                        fields.setdefault(normalized_nested_key, scalar)
            continue
        scalar = _scalar_text(value)
        if scalar or isinstance(value, bool):
            fields[key] = value if isinstance(value, bool) else scalar

    diagnostics = raw_failure.get("diagnostics")
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        for item in list(diagnostics)[:8]:
            if not isinstance(item, Mapping):
                continue
            for key in ("code", "category", "gate", "message", "reason"):
                value, present = _mapping_value(item, key)
                if not present or key in _SENSITIVE_INPUT_KEYS:
                    continue
                scalar = _scalar_text(value)
                if scalar:
                    fields.setdefault(key, scalar)

    info["fields"] = fields
    return info


def _normalized_token(value: Any) -> str:
    text = _ascii_text(value, MAX_SIGNAL_CHARS).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _class_from_value(value: Any) -> Optional[str]:
    token = _normalized_token(value)
    if not token:
        return None
    if token in _CLASS_ALIASES:
        return _CLASS_ALIASES[token]
    if token in VALID_FAILURE_CLASSES:
        return token
    for marker, failure_class in (
        ("timeout", FAILURE_CLASS_TIMEOUT),
        ("quota", FAILURE_CLASS_QUOTA),
        ("rate_limit", FAILURE_CLASS_QUOTA),
        ("dependency", FAILURE_CLASS_DEPENDENCY),
        ("import", FAILURE_CLASS_DEPENDENCY),
        ("file", FAILURE_CLASS_FILE),
        ("persist", FAILURE_CLASS_FILE),
        ("rights", FAILURE_CLASS_RIGHTS),
        ("copyright", FAILURE_CLASS_RIGHTS),
        ("policy", FAILURE_CLASS_RIGHTS),
        ("publication", FAILURE_CLASS_PUBLICATION),
        ("registry", FAILURE_CLASS_PUBLICATION),
        ("markdown", FAILURE_CLASS_PUBLICATION),
        ("mechanical", FAILURE_CLASS_MECHANICAL),
        ("schema", FAILURE_CLASS_MECHANICAL),
        ("structural", FAILURE_CLASS_MECHANICAL),
        ("semantic", FAILURE_CLASS_SEMANTIC),
        ("continuity", FAILURE_CLASS_SEMANTIC),
        ("provider", FAILURE_CLASS_PROVIDER),
        ("model_response", FAILURE_CLASS_PROVIDER),
    ):
        if marker in token:
            return failure_class
    return None


def _provider_specific_class(fields: Mapping[str, Any]) -> Optional[str]:
    """Return timeout/quota before generic provider classification."""
    provider_values: List[str] = []
    for key in (
        "exception_type",
        "provider_error_class",
        "error_class",
        "status",
        "outcome",
        "code",
        "error_code",
        "error",
        "message",
        "detail",
        "reason",
    ):
        value = fields.get(key)
        if value is not None:
            provider_values.append(_scalar_text(value))
    combined = " ".join(provider_values)
    if _TIMEOUT_RE.search(combined):
        return FAILURE_CLASS_TIMEOUT
    if _QUOTA_RE.search(combined):
        return FAILURE_CLASS_QUOTA
    return None


def _explicit_class(fields: Mapping[str, Any]) -> Tuple[Optional[str], str]:
    for key in (
        "failure_class",
        "provider_error_class",
        "error_class",
        "category",
        "type",
        "status",
        "outcome",
        "code",
        "error_code",
        "gate",
        "domain",
    ):
        value = fields.get(key)
        failure_class = _class_from_value(value)
        if failure_class is not None:
            return failure_class, key
    return None, ""


def _inferred_class(fields: Mapping[str, Any]) -> Optional[str]:
    rights_values = " ".join(
        _scalar_text(fields.get(key))
        for key in ("rights_class", "rights_review_status", "message", "reason", "detail")
    )
    if fields.get("rights_review_required") is True or re.search(
        r"(?i)rights|copyright|license|policy|restricted|legal review",
        rights_values,
    ):
        return FAILURE_CLASS_RIGHTS

    publication_values = " ".join(
        _scalar_text(fields.get(key))
        for key in ("publication_status", "message", "reason", "detail", "gate")
    )
    if fields.get("publication_status") in {"failed", "blocked"} or re.search(
        r"(?i)publication|registry|markdown|report_agreement|campaign visibility|publish",
        publication_values,
    ):
        return FAILURE_CLASS_PUBLICATION

    provider_specific = _provider_specific_class(fields)
    if provider_specific is not None:
        return provider_specific

    combined = " ".join(
        _scalar_text(fields.get(key))
        for key in (
            "message",
            "reason",
            "detail",
            "error",
            "gate",
            "domain",
            "status",
            "outcome",
            "exception_type",
        )
    )
    for pattern, failure_class in (
        (r"(?i)missing dependency|dependency|module not found|no module named|import error|importerror|modulenotfounderror|jsonschema", FAILURE_CLASS_DEPENDENCY),
        (r"(?i)file not found|filenotfounderror|permissionerror|permission denied|no such file|filesystem|write failed|read failed|artifact .*failed|path error", FAILURE_CLASS_FILE),
        (r"(?i)mechanical|schema|structural|readiness|topology|reference integrity|closure", FAILURE_CLASS_MECHANICAL),
        (r"(?i)semantic|continuity|coherence|content gate|semantic probe", FAILURE_CLASS_SEMANTIC),
        (r"(?i)provider|model|api|client", FAILURE_CLASS_PROVIDER),
    ):
        if re.search(pattern, combined):
            return failure_class
    return None


def _resolve_failure_class(info: Mapping[str, Any]) -> Tuple[str, str]:
    fields = info.get("fields") if isinstance(info.get("fields"), Mapping) else {}
    explicit, explicit_source = _explicit_class(fields)
    provider_specific = _provider_specific_class(fields)

    # A provider quota or timeout is more specific than a generic provider
    # status.  Content, rights, and publication gate labels remain authoritative
    # when they explicitly identify a completed gate failure.
    if provider_specific is not None and explicit not in {
        FAILURE_CLASS_RIGHTS,
        FAILURE_CLASS_MECHANICAL,
        FAILURE_CLASS_SEMANTIC,
        FAILURE_CLASS_PUBLICATION,
    }:
        return provider_specific, "provider_specific"
    if explicit is not None:
        return explicit, "explicit_" + explicit_source
    inferred = _inferred_class(fields)
    if inferred is not None:
        return inferred, "inferred"
    return FAILURE_CLASS_UNKNOWN, "unknown"


def _failure_message(
    fields: Mapping[str, Any],
    failure_class: str,
) -> str:
    if fields.get("refusal") or fields.get("status") in {"refused", "provider_refusal"}:
        return "Provider refusal was classified without retaining provider text."
    for key in ("message", "reason", "detail", "error"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            safe = _ascii_text(value, MAX_MESSAGE_CHARS)
            if safe and "[REDACTED_PAYLOAD]" not in safe:
                return safe
    return "Adaptation failure classified as " + failure_class + "."


def _revision_opt_in(
    fields: Mapping[str, Any],
    explicit_value: Any,
) -> bool:
    if explicit_value is not None:
        return _coerce_bool(explicit_value) is True
    for key in (
        "revision_eligible",
        "semantic_revision_eligible",
        "allow_semantic_revision",
        "revision_opt_in",
    ):
        value = _coerce_bool(fields.get(key))
        if value is not None:
            return value
    return False


def _metadata_for_classification(
    raw_failure: Any,
    attempt_metadata: Optional[Mapping[str, Any]],
    *,
    attempt_id: Any,
    revision_number: Any,
    stage: Any,
    domain: Any,
) -> Dict[str, Any]:
    raw_mapping = raw_failure if isinstance(raw_failure, Mapping) else {}
    resolved_attempt_id = attempt_id
    if resolved_attempt_id is None:
        resolved_attempt_id = _metadata_value(raw_mapping, attempt_metadata, "attempt_id")
    resolved_revision = revision_number
    if resolved_revision is None:
        resolved_revision = _metadata_value(raw_mapping, attempt_metadata, "revision_number")
    resolved_stage = stage
    if resolved_stage is None:
        resolved_stage = _metadata_value(raw_mapping, attempt_metadata, "failed_stage", "stage", "phase")
    resolved_domain = domain
    if resolved_domain is None:
        resolved_domain = _metadata_value(raw_mapping, attempt_metadata, "domain", "gate")
    return {
        "attempt_id": _safe_attempt_id(resolved_attempt_id),
        "revision_number": _safe_non_negative_int(resolved_revision),
        "stage": _safe_label(resolved_stage),
        "domain": _safe_label(resolved_domain),
    }


def classify_adaptation_failure(
    raw_failure: Any,
    *,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    attempt_id: Any = None,
    revision_number: Any = None,
    stage: Any = None,
    domain: Any = None,
    revision_eligible: Any = None,
    max_revisions: Any = None,
) -> Dict[str, Any]:
    """Return a deterministic, bounded classification for one failure.

    Infrastructure classes never consume the semantic revision budget. Rights
    and publication failures are terminal and fail closed. Mechanical and
    semantic failures require an explicit ``revision_eligible`` marker and a
    remaining bounded budget before they can consume one revision.
    """
    info = _collect_info(raw_failure)
    fields = info.get("fields") if isinstance(info.get("fields"), Mapping) else {}
    failure_class, class_source = _resolve_failure_class(info)
    if failure_class not in VALID_FAILURE_CLASSES:
        failure_class = FAILURE_CLASS_UNKNOWN

    metadata = _metadata_for_classification(
        raw_failure,
        attempt_metadata,
        attempt_id=attempt_id,
        revision_number=revision_number,
        stage=stage,
        domain=domain,
    )
    resolved_revision = metadata["revision_number"]
    raw_max_revisions = max_revisions
    if raw_max_revisions is None:
        raw_max_revisions = _metadata_value(
            raw_failure if isinstance(raw_failure, Mapping) else {},
            attempt_metadata,
            "max_revisions",
        )
    max_budget = _safe_max_revisions(raw_max_revisions)
    explicit_opt_in = _revision_opt_in(fields, revision_eligible)
    raw_terminal = _coerce_bool(fields.get("terminal"))
    raw_retryable = _coerce_bool(fields.get("retryable"))

    is_infrastructure = failure_class in INFRASTRUCTURE_FAILURE_CLASSES
    is_policy = failure_class in POLICY_FAILURE_CLASSES
    is_publication = failure_class in PUBLICATION_FAILURE_CLASSES
    is_revision_class = failure_class in REVISION_ELIGIBLE_CLASSES
    failure_kind = _normalized_token(fields.get("failure_kind"))
    hard_failure = failure_kind in {
        "hard",
        "infrastructure",
        "policy",
        "publication",
    }
    if hard_failure:
        is_revision_class = False
    budget_available = resolved_revision < max_budget

    if is_infrastructure:
        revision_budget_decision = REVISION_BUDGET_DECISION_NOT_APPLICABLE
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_policy:
        revision_budget_decision = REVISION_BUDGET_DECISION_TERMINAL
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_publication:
        revision_budget_decision = REVISION_BUDGET_DECISION_TERMINAL
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_revision_class and not explicit_opt_in:
        revision_budget_decision = REVISION_BUDGET_DECISION_OPT_IN_REQUIRED
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_revision_class and raw_terminal is True:
        revision_budget_decision = REVISION_BUDGET_DECISION_TERMINAL
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_revision_class and not budget_available:
        revision_budget_decision = REVISION_BUDGET_DECISION_EXHAUSTED
        semantic_revision_eligible = False
        consumes_budget = False
    elif is_revision_class:
        revision_budget_decision = REVISION_BUDGET_DECISION_ELIGIBLE
        semantic_revision_eligible = True
        # Eligibility is not consumption.  The accepted revision worker owns
        # budget accounting; classifying the initial failure must not spend it.
        consumes_budget = False
    else:
        revision_budget_decision = REVISION_BUDGET_DECISION_NOT_APPLICABLE
        semantic_revision_eligible = False
        consumes_budget = False

    if is_policy or is_publication or failure_class == FAILURE_CLASS_UNKNOWN:
        terminal = True
        retryable = False
    elif semantic_revision_eligible:
        terminal = False
        retryable = True
    else:
        terminal = raw_terminal if raw_terminal is not None else _DEFAULT_TERMINAL[failure_class]
        retryable = raw_retryable if raw_retryable is not None else _DEFAULT_RETRYABLE[failure_class]
        if terminal:
            retryable = False

    if revision_budget_decision == REVISION_BUDGET_DECISION_OPT_IN_REQUIRED:
        classification_status = CLASSIFICATION_STATUS_BLOCKED
    elif semantic_revision_eligible:
        classification_status = CLASSIFICATION_STATUS_REVISION_ELIGIBLE
    elif terminal:
        classification_status = CLASSIFICATION_STATUS_TERMINAL
    elif retryable:
        classification_status = CLASSIFICATION_STATUS_RETRYABLE
    else:
        classification_status = CLASSIFICATION_STATUS_BLOCKED

    fields_for_code = (
        fields.get("code")
        or fields.get("error_code")
        or fields.get("status")
        or failure_class
    )
    return {
        "contract_version": FAILURE_CLASSIFICATION_CONTRACT_VERSION,
        "failure_class": failure_class,
        "failure_group": (
            FAILURE_GROUP_INFRASTRUCTURE
            if is_infrastructure
            else FAILURE_GROUP_POLICY
            if is_policy
            else FAILURE_GROUP_PUBLICATION
            if is_publication
            else FAILURE_GROUP_CONTENT
            if is_revision_class
            else FAILURE_GROUP_UNKNOWN
        ),
        "classification_source": class_source,
        "failure_kind": "hard" if hard_failure else "content" if is_revision_class else "terminal",
        "classification_status": classification_status,
        "attempt_id": metadata["attempt_id"],
        "revision_number": resolved_revision,
        "stage": metadata["stage"],
        "domain": metadata["domain"],
        "code": _safe_code(fields_for_code),
        "message": _failure_message(fields, failure_class),
        "retryable": bool(retryable),
        "terminal": bool(terminal),
        "blocked": bool(terminal or not consumes_budget),
        "semantic_revision_eligible": bool(semantic_revision_eligible),
        "revision_eligible": bool(semantic_revision_eligible),
        "next_revision_eligible": bool(semantic_revision_eligible and budget_available),
        "consumes_semantic_revision_budget": bool(consumes_budget),
        "semantic_revision_budget_consumed": bool(consumes_budget),
        "revision_budget": {
            "current_revision": resolved_revision,
            "max_revisions": max_budget,
            "remaining_before_failure": max(0, max_budget - resolved_revision),
            "explicit_opt_in": bool(explicit_opt_in),
            "decision": revision_budget_decision,
        },
        "publication_allowed": False,
        "advisory": True,
        "raw_input_retained": False,
    }


def normalize_adaptation_failure(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Compatibility name for callers that want classification normalization."""
    return classify_adaptation_failure(*args, **kwargs)


def classify_failure(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Short alias for the adaptation failure classifier."""
    return classify_adaptation_failure(*args, **kwargs)


def is_infrastructure_failure(classification: Mapping[str, Any]) -> bool:
    """Return whether a classification belongs to the infrastructure group."""
    return isinstance(classification, Mapping) and classification.get("failure_class") in INFRASTRUCTURE_FAILURE_CLASSES


def should_consume_semantic_revision_budget(classification: Mapping[str, Any]) -> bool:
    """Return the explicit budget decision without performing orchestration."""
    return bool(
        isinstance(classification, Mapping)
        and classification.get("consumes_semantic_revision_budget") is True
    )


__all__ = [
    "FAILURE_CLASSIFICATION_CONTRACT_VERSION",
    "FAILURE_CLASS_PROVIDER",
    "FAILURE_CLASS_FILE",
    "FAILURE_CLASS_DEPENDENCY",
    "FAILURE_CLASS_QUOTA",
    "FAILURE_CLASS_TIMEOUT",
    "FAILURE_CLASS_RIGHTS",
    "FAILURE_CLASS_MECHANICAL",
    "FAILURE_CLASS_SEMANTIC",
    "FAILURE_CLASS_PUBLICATION",
    "FAILURE_CLASS_UNKNOWN",
    "VALID_FAILURE_CLASSES",
    "FAILURE_GROUP_INFRASTRUCTURE",
    "FAILURE_GROUP_CONTENT",
    "FAILURE_GROUP_POLICY",
    "FAILURE_GROUP_PUBLICATION",
    "FAILURE_GROUP_UNKNOWN",
    "VALID_FAILURE_GROUPS",
    "CLASSIFICATION_STATUS_RETRYABLE",
    "CLASSIFICATION_STATUS_REVISION_ELIGIBLE",
    "CLASSIFICATION_STATUS_BLOCKED",
    "CLASSIFICATION_STATUS_TERMINAL",
    "VALID_CLASSIFICATION_STATUSES",
    "REVISION_BUDGET_DECISION_NOT_APPLICABLE",
    "REVISION_BUDGET_DECISION_OPT_IN_REQUIRED",
    "REVISION_BUDGET_DECISION_ELIGIBLE",
    "REVISION_BUDGET_DECISION_EXHAUSTED",
    "REVISION_BUDGET_DECISION_TERMINAL",
    "VALID_REVISION_BUDGET_DECISIONS",
    "INFRASTRUCTURE_FAILURE_CLASSES",
    "CONTENT_FAILURE_CLASSES",
    "POLICY_FAILURE_CLASSES",
    "PUBLICATION_FAILURE_CLASSES",
    "REVISION_ELIGIBLE_CLASSES",
    "DEFAULT_MAX_SEMANTIC_REVISIONS",
    "MAX_SEMANTIC_REVISIONS",
    "MAX_MESSAGE_CHARS",
    "classify_adaptation_failure",
    "normalize_adaptation_failure",
    "classify_failure",
    "is_infrastructure_failure",
    "should_consume_semantic_revision_budget",
]
