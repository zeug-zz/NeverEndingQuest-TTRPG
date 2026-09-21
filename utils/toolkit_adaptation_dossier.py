# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Dossier Contract
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free parsing, normalization, and validation for the versioned
LLM-to-ModuleBuilder adaptation dossier handoff.

This utility validates a creative handoff only. It does not call a provider,
write files, run ModuleBuilder, validate a module, or claim publication.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from jsonschema import Draft7Validator
except Exception:  # pragma: no cover - dependency availability is environment-specific
    Draft7Validator = None  # type: ignore[assignment,misc]


ADAPTATION_DOSSIER_VERSION = "toolkit_adaptation_dossier.v1"
ADAPTATION_DOSSIER_SCHEMA_VERSION = ADAPTATION_DOSSIER_VERSION
ADAPTATION_MODE_LLM = "llm_adaptation"
ADAPTATION_NOTICE = "Adapted for NEQ-TTRPG"

ADAPTATION_DOSSIER_STATUS_READY = "ready"
ADAPTATION_DOSSIER_STATUS_REFUSED = "refused"
ADAPTATION_DOSSIER_STATUS_FAILED = "failed"
VALID_ADAPTATION_DOSSIER_STATUSES = (
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    ADAPTATION_DOSSIER_STATUS_FAILED,
)

SOURCE_PROFILE_ADVENTURE = "adventure"
SOURCE_PROFILE_CATALOGUE = "catalogue"
SOURCE_PROFILE_LOCATION = "location"
SOURCE_PROFILE_LORE = "lore"
SOURCE_PROFILE_ENCOUNTER = "encounter"
SOURCE_PROFILE_SANDBOX = "sandbox"
VALID_SOURCE_PROFILES = (
    SOURCE_PROFILE_ADVENTURE,
    SOURCE_PROFILE_CATALOGUE,
    SOURCE_PROFILE_LOCATION,
    SOURCE_PROFILE_LORE,
    SOURCE_PROFILE_ENCOUNTER,
    SOURCE_PROFILE_SANDBOX,
)

# These values intentionally match the existing Homebrew upload contract.
RIGHTS_CLASS_USER_AUTHORED = "user_authored"
RIGHTS_CLASS_LICENSED = "licensed_or_project_owned"
RIGHTS_CLASS_RESTRICTED = "third_party_copyright_restricted"
VALID_RIGHTS_CLASSES = (
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_CLASS_LICENSED,
    RIGHTS_CLASS_RESTRICTED,
)

RIGHTS_REVIEW_NOT_REQUIRED = "not_required"
RIGHTS_REVIEW_PENDING = "pending"
RIGHTS_REVIEW_APPROVED = "approved"
RIGHTS_REVIEW_REJECTED = "rejected"
VALID_RIGHTS_REVIEW_STATUSES = (
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_APPROVED,
    RIGHTS_REVIEW_REJECTED,
)

RESULT_STATUS_VALID = "valid"
RESULT_STATUS_INVALID = "invalid"
PUBLICATION_STATUS_NOT_EVALUATED = "not_evaluated"

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
DIAGNOSTIC_CODE_INVALID_TYPE = "invalid_type"
DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD = "missing_required_field"
DIAGNOSTIC_CODE_INVALID_ENUM = "invalid_enum"
DIAGNOSTIC_CODE_INVALID_VALUE = "invalid_value"
DIAGNOSTIC_CODE_INVALID_SOURCE_HASH = "invalid_source_hash"
DIAGNOSTIC_CODE_INVALID_LEVEL_RANGE = "invalid_level_range"
DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA = "invalid_rights_metadata"
DIAGNOSTIC_CODE_UNEXPECTED_FIELD = "unexpected_field"
DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE = "schema_unavailable"

REQUIRED_ADAPTATION_DOSSIER_FIELDS = (
    "version",
    "status",
    "adaptation_mode",
    "source_title",
    "adapted_title",
    "source_hash",
    "source_profile",
    "module_tone",
    "level_range",
    "starting_location",
    "areas",
    "plot_objective",
    "plot_progression",
    "npc_seeds",
    "encounter_seeds",
    "item_seeds",
    "retained_source_elements",
    "omitted_source_elements",
    "original_adaptation_elements",
    "world_narrative_hooks",
    "continuity_hints",
    "rights_class",
    "rights_basis",
    "rights_review_required",
    "rights_review_status",
    "adaptation_notice",
    "assumptions",
    "warnings",
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "toolkit_adaptation_dossier_schema.json"
)
_MISSING_PROPERTY_RE = re.compile(r"'([^']+)' is a required property")


def _ascii_text(value: Any, limit: int = 240) -> str:
    """Return a bounded ASCII diagnostic string."""
    text = str(value).encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(
    code: str,
    message: str,
    path: str = "",
) -> Dict[str, str]:
    """Build one deterministic, ASCII-only validation diagnostic."""
    return {
        "code": code,
        "message": _ascii_text(message),
        "path": _ascii_text(path, limit=160),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def get_adaptation_dossier_schema_path() -> Path:
    """Return the repository-local schema path without reading or writing it."""
    return SCHEMA_PATH


def load_adaptation_dossier_schema() -> Dict[str, Any]:
    """Load and return a copy of the adaptation dossier JSON schema."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("adaptation dossier schema must be a JSON object")
    return deepcopy(schema)


def _normalize_value(value: Any) -> Any:
    """Recursively trim textual values without mutating the caller."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return deepcopy(value)


def normalize_adaptation_dossier(
    dossier: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a deterministic copy of a mapping-shaped dossier.

    Normalization is deliberately narrow: it trims strings and canonicalizes
    enum-like fields to lowercase. It does not add defaults, repair missing
    fields, infer source content, or alter creative values.
    """
    if not isinstance(dossier, Mapping):
        return {}

    normalized = _normalize_value(dict(dossier))
    for field_name in (
        "version",
        "status",
        "adaptation_mode",
        "source_profile",
        "rights_class",
        "rights_review_status",
    ):
        value = normalized.get(field_name)
        if isinstance(value, str):
            normalized[field_name] = value.lower()

    source_hash = normalized.get("source_hash")
    if isinstance(source_hash, str):
        normalized["source_hash"] = source_hash.lower()
    return normalized


def _path_to_string(path: Sequence[Any]) -> str:
    return ".".join(str(part) for part in path)


def _schema_error_code(error: Any) -> str:
    keyword = getattr(error, "validator", "")
    if keyword == "required":
        return DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD
    if keyword == "enum":
        return DIAGNOSTIC_CODE_INVALID_ENUM
    if keyword == "type":
        return DIAGNOSTIC_CODE_INVALID_TYPE
    if keyword == "additionalProperties":
        return DIAGNOSTIC_CODE_UNEXPECTED_FIELD
    if keyword == "pattern" and list(getattr(error, "absolute_path", [])) == [
        "source_hash"
    ]:
        return DIAGNOSTIC_CODE_INVALID_SOURCE_HASH
    return DIAGNOSTIC_CODE_INVALID_VALUE


def _schema_error_path(error: Any) -> str:
    path_parts = list(getattr(error, "absolute_path", []))
    message = str(getattr(error, "message", ""))
    if getattr(error, "validator", "") == "required":
        match = _MISSING_PROPERTY_RE.search(message)
        if match:
            path_parts.append(match.group(1))
    return _path_to_string(path_parts)


def _schema_diagnostics(dossier: Dict[str, Any]) -> List[Dict[str, str]]:
    """Validate a normalized mapping against the machine-checkable schema."""
    if Draft7Validator is None:
        return [
            _diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE,
                "jsonschema dependency is unavailable",
            )
        ]

    try:
        validator = Draft7Validator(load_adaptation_dossier_schema())
        errors = sorted(
            validator.iter_errors(dossier),
            key=lambda error: (
                tuple(str(part) for part in getattr(error, "absolute_path", [])),
                str(getattr(error, "validator", "")),
                str(getattr(error, "message", "")),
            ),
        )
    except Exception as exc:
        return [
            _diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE,
                "adaptation dossier schema could not be loaded: " + _ascii_text(exc),
            )
        ]

    return [
        _diagnostic(
            _schema_error_code(error),
            str(getattr(error, "message", "schema validation failed")),
            _schema_error_path(error),
        )
        for error in errors
    ]


def _semantic_diagnostics(dossier: Dict[str, Any]) -> List[Dict[str, str]]:
    """Apply cross-field checks that JSON Schema draft-07 cannot express."""
    diagnostics: List[Dict[str, str]] = []

    level_range = dossier.get("level_range")
    if isinstance(level_range, dict):
        minimum = level_range.get("min")
        maximum = level_range.get("max")
        if (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_LEVEL_RANGE,
                    "level_range.min must not exceed level_range.max",
                    "level_range",
                )
            )

    plot_progression = dossier.get("plot_progression")
    if isinstance(plot_progression, list):
        orders = [
            item.get("order")
            for item in plot_progression
            if isinstance(item, dict) and "order" in item
        ]
        if len(orders) != len(set(orders)):
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_VALUE,
                    "plot_progression.order values must be unique",
                    "plot_progression",
                )
            )

    review_required = dossier.get("rights_review_required")
    review_status = dossier.get("rights_review_status")
    rights_class = dossier.get("rights_class")
    if rights_class == RIGHTS_CLASS_RESTRICTED and review_required is not True:
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA,
                "restricted rights class requires rights_review_required=true",
                "rights_review_required",
            )
        )
    if review_required is True and review_status == RIGHTS_REVIEW_NOT_REQUIRED:
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA,
                "rights_review_required=true cannot use rights_review_status=not_required",
                "rights_review_status",
            )
        )
    if review_required is False and review_status in {
        RIGHTS_REVIEW_PENDING,
        RIGHTS_REVIEW_REJECTED,
    }:
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA,
                "rights_review_required=false cannot use pending or rejected review status",
                "rights_review_status",
            )
        )

    return diagnostics


def _build_result(
    normalized: Optional[Dict[str, Any]],
    diagnostics: List[Dict[str, str]],
) -> Dict[str, Any]:
    valid = not diagnostics and normalized is not None
    dossier_status = normalized.get("status") if normalized else None
    rights_ready = bool(
        normalized
        and (
            (
                normalized.get("rights_class") != RIGHTS_CLASS_RESTRICTED
                and normalized.get("rights_review_required") is False
            )
            or (
                normalized.get("rights_review_required") is True
                and normalized.get("rights_review_status") == RIGHTS_REVIEW_APPROVED
            )
        )
    )
    build_ready = bool(
        valid
        and dossier_status == ADAPTATION_DOSSIER_STATUS_READY
        and rights_ready
    )
    return {
        "valid": valid,
        "status": RESULT_STATUS_VALID if valid else RESULT_STATUS_INVALID,
        "dossier": deepcopy(normalized) if valid else None,
        "dossier_status": dossier_status,
        "diagnostics": diagnostics,
        "build_ready": build_ready,
        "publication_status": PUBLICATION_STATUS_NOT_EVALUATED,
    }


def validate_adaptation_dossier(dossier: Any) -> Dict[str, Any]:
    """Validate a mapping-shaped dossier without provider or file side effects.

    The return value is always a structured result. A valid result means only
    that the dossier contract is satisfied; ``publication_status`` remains
    ``not_evaluated`` and no publication success is asserted.
    """
    if not isinstance(dossier, Mapping):
        return _build_result(
            None,
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_TYPE,
                    "adaptation dossier must be a JSON object",
                )
            ],
        )

    normalized = normalize_adaptation_dossier(dossier)
    diagnostics = _schema_diagnostics(normalized)
    # Run safe cross-field checks even when an unrelated field has a schema
    # error so one response can expose all actionable contract failures.
    diagnostics.extend(_semantic_diagnostics(normalized))
    return _build_result(normalized, diagnostics)


def _parse_json_value(raw_response: Any) -> Tuple[Optional[Any], List[Dict[str, str]]]:
    """Decode strict JSON input and return structured parse diagnostics."""
    if isinstance(raw_response, bytes):
        try:
            raw_response = raw_response.decode("utf-8")
        except UnicodeDecodeError:
            return None, [
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    "raw response is not valid UTF-8 JSON",
                )
            ]

    if isinstance(raw_response, Mapping):
        return deepcopy(dict(raw_response)), []
    if not isinstance(raw_response, str):
        return None, [
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_TYPE,
                "raw response must be a JSON string, bytes, or object",
            )
        ]

    text = raw_response.strip()
    if not text:
        return None, [
            _diagnostic(DIAGNOSTIC_CODE_INVALID_JSON, "raw response is empty")
        ]

    try:
        parsed = json.loads(
            text,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("non-standard JSON constant: " + value)
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, [
            _diagnostic(
                DIAGNOSTIC_CODE_INVALID_JSON,
                "json.loads failed: " + _ascii_text(exc),
            )
        ]
    return parsed, []


def parse_adaptation_dossier(raw_response: Any) -> Dict[str, Any]:
    """Parse and validate a raw provider-shaped dossier response.

    This function accepts strict JSON text or an already-decoded mapping for
    provider-free tests. It never calls a provider, writes a file, or claims a
    completed publication. Malformed, non-object, incomplete, and invalid
    enum/type responses return ``valid=false`` with deterministic diagnostics.
    """
    parsed, parse_diagnostics = _parse_json_value(raw_response)
    if parse_diagnostics:
        return _build_result(None, parse_diagnostics)
    if not isinstance(parsed, Mapping):
        return _build_result(
            None,
            [
                _diagnostic(
                    DIAGNOSTIC_CODE_INVALID_TYPE,
                    "top-level JSON value must be an object",
                )
            ],
        )
    return validate_adaptation_dossier(parsed)


def parse_and_validate_adaptation_dossier(raw_response: Any) -> Dict[str, Any]:
    """Explicit alias for callers that prefer a combined API name."""
    return parse_adaptation_dossier(raw_response)


def is_valid_adaptation_dossier(dossier: Any) -> bool:
    """Return whether a decoded dossier satisfies the v1 contract."""
    return bool(validate_adaptation_dossier(dossier).get("valid"))


__all__ = [
    "ADAPTATION_DOSSIER_SCHEMA_VERSION",
    "ADAPTATION_DOSSIER_STATUS_FAILED",
    "ADAPTATION_DOSSIER_STATUS_READY",
    "ADAPTATION_DOSSIER_STATUS_REFUSED",
    "ADAPTATION_DOSSIER_VERSION",
    "ADAPTATION_MODE_LLM",
    "ADAPTATION_NOTICE",
    "DIAGNOSTIC_CODE_INVALID_ENUM",
    "DIAGNOSTIC_CODE_INVALID_JSON",
    "DIAGNOSTIC_CODE_INVALID_LEVEL_RANGE",
    "DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA",
    "DIAGNOSTIC_CODE_INVALID_SOURCE_HASH",
    "DIAGNOSTIC_CODE_INVALID_TYPE",
    "DIAGNOSTIC_CODE_INVALID_VALUE",
    "DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD",
    "DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE",
    "DIAGNOSTIC_CODE_UNEXPECTED_FIELD",
    "REQUIRED_ADAPTATION_DOSSIER_FIELDS",
    "RIGHTS_CLASS_LICENSED",
    "RIGHTS_CLASS_RESTRICTED",
    "RIGHTS_CLASS_USER_AUTHORED",
    "RIGHTS_REVIEW_APPROVED",
    "RIGHTS_REVIEW_NOT_REQUIRED",
    "RIGHTS_REVIEW_PENDING",
    "RIGHTS_REVIEW_REJECTED",
    "SOURCE_PROFILE_ADVENTURE",
    "SOURCE_PROFILE_CATALOGUE",
    "SOURCE_PROFILE_ENCOUNTER",
    "SOURCE_PROFILE_LOCATION",
    "SOURCE_PROFILE_LORE",
    "SOURCE_PROFILE_SANDBOX",
    "VALID_ADAPTATION_DOSSIER_STATUSES",
    "VALID_RIGHTS_CLASSES",
    "VALID_RIGHTS_REVIEW_STATUSES",
    "VALID_SOURCE_PROFILES",
    "get_adaptation_dossier_schema_path",
    "is_valid_adaptation_dossier",
    "load_adaptation_dossier_schema",
    "normalize_adaptation_dossier",
    "parse_adaptation_dossier",
    "parse_and_validate_adaptation_dossier",
    "validate_adaptation_dossier",
]
