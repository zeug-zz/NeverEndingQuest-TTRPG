# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Configuration
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free feature configuration and routing resolution for the LLM-led
adaptation lane.

This module only resolves configuration, eligibility, and routing decisions.
It does not call a provider, write files, run ModuleBuilder, validate a
module, or claim publication.

The adaptation lane is disabled by default. While disabled, every adaptation
route request resolves to the explicit legacy accurate-ingest route, so
existing accurate-ingest routing and diagnostics remain available and
unchanged. Invalid or missing configuration fails safely to that same legacy
behavior.

Input-kind eligibility and route resolution (task 1.3) stay Python-owned and
deterministic: an eligible upload (Markdown or PDF with source identity and
Python-owned rights) or an eligible text description (module name plus
non-empty bounded description) selects the background ``llm_adaptation``
route only when the operator flag is exactly True. Missing, invalid, or
False flags resolve eligible inputs to the explicit legacy route and require
no adaptation artifacts. Unsupported or invalid input metadata resolves to
an explicit ineligible (legacy-safe) outcome, and a selected adaptation
route is authoritative: it can never silently downgrade to legacy.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
)

# Safe default: the adaptation lane is OFF until rollout explicitly enables it.
ENABLE_LLM_ADAPTATION_DEFAULT = False
CANONICAL_MONSTER_GENERATION_DEFAULT = False

# Build-mode identifiers for routing decisions.
BUILD_MODE_LLM_ADAPTATION = ADAPTATION_MODE_LLM  # "llm_adaptation"
BUILD_MODE_LEGACY_ACCURATE_INGEST = "accurate_ingest_legacy"

# Explicit legacy accurate-ingest build modes that remain routable today.
# The adaptation lane never silently replaces any of these routes; they stay
# available as the explicit legacy and diagnostic path.
LEGACY_ACCURATE_INGEST_BUILD_MODES = frozenset({
    "source_enhanced_modulebuilder",
    "source_blueprint_modulebuilder",
    "blueprint_seed_fallback",
    "blueprint_seed_preview",
    "blueprint_seed_support",
    "packet_workspace_v1",
    "packet_workspace_v2",
    "legacy_builder_narrative_v1",
})

# Routing resolution statuses and reasons.
ROUTING_STATUS_ENABLED = "enabled"
ROUTING_STATUS_LEGACY = "legacy"
ROUTING_REASON_REQUESTED_AND_ENABLED = "requested_and_enabled"
ROUTING_REASON_NOT_REQUESTED = "not_requested"
ROUTING_REASON_INVALID_REQUEST = "invalid_request"
ROUTING_REASON_DISABLED = "disabled"


def _coerce_enabled_flag(value: Any) -> bool:
    """Strictly coerce an enablement value to a safe boolean.

    Only real booleans are accepted. Any other value (None, strings,
    numbers, containers) fails safely to the documented default of False,
    so invalid or missing configuration always resolves to legacy behavior.
    """
    if isinstance(value, bool):
        return value
    return ENABLE_LLM_ADAPTATION_DEFAULT


def adaptation_enabled(enabled_override: Any = None) -> bool:
    """Resolve whether the LLM adaptation lane is enabled.

    Args:
        enabled_override: Optional explicit value, used by thin route hooks
            and tests. When None, the value is read from
            model_config.ENABLE_LLM_ADAPTATION.

    Returns:
        True only when the resolved value is exactly a boolean True.
        Missing, invalid, or non-boolean configuration returns False.
    """
    if enabled_override is not None:
        return _coerce_enabled_flag(enabled_override)
    try:
        from model_config import ENABLE_LLM_ADAPTATION
    except Exception:
        return ENABLE_LLM_ADAPTATION_DEFAULT
    return _coerce_enabled_flag(ENABLE_LLM_ADAPTATION)


def canonical_monster_generation_enabled(enabled_override: Any = None) -> bool:
    """Resolve the separate canonical-stat generation opt-in strictly.

    Only the operator value on ``model_config`` (or an explicit test override)
    is authoritative.  Truthy strings, numbers, provider metadata, and
    missing configuration never enable canonical generation.
    """
    if enabled_override is not None:
        return enabled_override is True
    try:
        from model_config import ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION
    except Exception:
        return CANONICAL_MONSTER_GENERATION_DEFAULT
    return ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION is True


def resolve_adaptation_routing(
    requested_mode: Any = None,
    enabled_override: Any = None,
) -> Dict[str, Any]:
    """Resolve a requested build route against the adaptation feature flag.

    While adaptation is disabled (the default), any request for the
    adaptation mode resolves to the explicit legacy accurate-ingest route so
    existing routing behavior is preserved exactly. When adaptation is
    enabled and the request is valid, the route resolves to the adaptation
    build mode.

    Args:
        requested_mode: Optional requested build mode string. Only
            BUILD_MODE_LLM_ADAPTATION is a valid adaptation request; any
            other value resolves to legacy.
        enabled_override: Optional explicit enablement value. When None the
            value is read from model_config.ENABLE_LLM_ADAPTATION.

    Returns:
        Deterministic resolution dict with keys: status ("enabled" or
        "legacy"), mode (resolved build mode), legacy_mode, requested_mode,
        and reason.
    """
    requested = requested_mode if isinstance(requested_mode, str) else None
    enabled = adaptation_enabled(enabled_override=enabled_override)

    if requested != BUILD_MODE_LLM_ADAPTATION:
        if requested_mode:
            reason = ROUTING_REASON_INVALID_REQUEST
        else:
            reason = ROUTING_REASON_NOT_REQUESTED
        return {
            "status": ROUTING_STATUS_LEGACY,
            "mode": BUILD_MODE_LEGACY_ACCURATE_INGEST,
            "legacy_mode": BUILD_MODE_LEGACY_ACCURATE_INGEST,
            "requested_mode": requested,
            "reason": reason,
        }

    if not enabled:
        return {
            "status": ROUTING_STATUS_LEGACY,
            "mode": BUILD_MODE_LEGACY_ACCURATE_INGEST,
            "legacy_mode": BUILD_MODE_LEGACY_ACCURATE_INGEST,
            "requested_mode": requested,
            "reason": ROUTING_REASON_DISABLED,
        }

    return {
        "status": ROUTING_STATUS_ENABLED,
        "mode": BUILD_MODE_LLM_ADAPTATION,
        "legacy_mode": BUILD_MODE_LEGACY_ACCURATE_INGEST,
        "requested_mode": requested,
        "reason": ROUTING_REASON_REQUESTED_AND_ENABLED,
    }


def is_llm_adaptation_build_mode(mode: Any) -> bool:
    """True when the given mode is the LLM adaptation build mode."""
    return mode == BUILD_MODE_LLM_ADAPTATION


def is_legacy_accurate_ingest_build_mode(mode: Any) -> bool:
    """True when the given mode is an explicit legacy accurate-ingest mode."""
    return mode in LEGACY_ACCURATE_INGEST_BUILD_MODES


# ---------------------------------------------------------------------------
# Task 1.3: input-kind eligibility and route decision resolution.
#
# These constants mirror the input-kind string identities used by the
# task 1.2 runtime envelope boundary (web/extensions/
# toolkit_adaptation_runtime.py). The decision layer only resolves routes;
# the envelope remains the assembly boundary and is never duplicated here.
# ---------------------------------------------------------------------------

ROUTE_DECISION_CONTRACT_VERSION = "toolkit_adaptation_route_decision.v1"

INPUT_KIND_UPLOAD_MARKDOWN = "upload_markdown"
INPUT_KIND_UPLOAD_PDF = "upload_pdf"
INPUT_KIND_TEXT_DESCRIPTION = "text_description"
VALID_INPUT_KINDS = (
    INPUT_KIND_UPLOAD_MARKDOWN,
    INPUT_KIND_UPLOAD_PDF,
    INPUT_KIND_TEXT_DESCRIPTION,
)

ROUTE_DECISION_STATUS_ADAPTATION = "adaptation"
ROUTE_DECISION_STATUS_LEGACY = "legacy"
ROUTE_DECISION_STATUS_INELIGIBLE = "ineligible"
ROUTE_DECISION_STATUS_FAILED_CLOSED = "failed_closed"

# Eligibility / decision reasons (deterministic, bounded, ASCII).
ROUTING_REASON_INPUT_KIND_UNSUPPORTED = "input_kind_unsupported"
ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH = "upload_source_kind_mismatch"
ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING = "upload_source_identity_missing"
ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_INVALID = "upload_source_identity_invalid"
ROUTING_REASON_RIGHTS_MISSING = "rights_missing"
ROUTING_REASON_RIGHTS_REVIEW_REQUIRED = "rights_review_required"
ROUTING_REASON_RIGHTS_REVIEW_CONTRADICTION = "rights_review_contradiction"
ROUTING_REASON_RIGHTS_METADATA_INVALID = "rights_metadata_invalid"
ROUTING_REASON_TEXT_NAME_MISSING = "text_description_name_missing"
ROUTING_REASON_TEXT_NAME_INVALID = "text_description_name_invalid"
ROUTING_REASON_TEXT_DESCRIPTION_MISSING = "text_description_missing"
ROUTING_REASON_TEXT_DESCRIPTION_INVALID = "text_description_invalid"
ROUTING_REASON_TEXT_DESCRIPTION_OVERSIZED = "text_description_oversized"
ROUTING_REASON_ATTEMPT_IDENTITY_INVALID = "attempt_identity_invalid"
ROUTING_REASON_JOB_IDENTITY_INVALID = "job_identity_invalid"
ROUTING_REASON_ATTEMPT_NUMBER_INVALID = "attempt_number_invalid"

# No-downgrade authority reasons for validate_adaptation_route_decision().
ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED = "adaptation_selected_authoritative"
ROUTE_AUTHORITY_REASON_LEGACY_EXPLICIT = "legacy_selected_explicit"
ROUTE_AUTHORITY_REASON_INELIGIBLE_SAFE = "ineligible_legacy_safe"
ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID = "selected_route_metadata_invalid"

# Bounds mirror the runtime envelope boundaries so both layers agree.
MAX_TEXT_DESCRIPTION_CHARS = 200_000
MAX_ROUTE_SOURCE_TITLE_CHARS = 240
MAX_ROUTE_RIGHTS_BASIS_CHARS = 500
MAX_ROUTE_JOB_ID_CHARS = 160

# Python-owned rights basis for text descriptions. The LLM is never asked to
# infer rights; user-submitted text is classified by Python as user-authored.
TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS = "user_submitted_text_description"

_SHA256_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _is_sha256_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_DIGEST_RE.fullmatch(value.strip().lower()))


def _is_safe_attempt_id(value: Any) -> bool:
    return isinstance(value, str) and ".." not in value and bool(_ATTEMPT_ID_RE.fullmatch(value))


def _bounded_text(value: Any, limit: int) -> Tuple[str, bool]:
    """Return bounded ASCII text and whether it was truncated."""
    text = str(value or "").encode("ascii", "replace").decode("ascii").strip()
    if len(text) <= limit:
        return text, False
    marker = " [truncated]"
    keep = max(0, limit - len(marker))
    return text[:keep].rstrip() + marker, True


def _base_route_decision(input_kind: str) -> Dict[str, Any]:
    """Return a deterministic base decision dict with safe empty defaults."""
    return {
        "contract_version": ROUTE_DECISION_CONTRACT_VERSION,
        "status": ROUTE_DECISION_STATUS_INELIGIBLE,
        "route_selected": BUILD_MODE_LEGACY_ACCURATE_INGEST,
        "input_kind": input_kind,
        "fallback_allowed": False,
        "adaptation_artifacts_required": False,
        "flag_resolution": None,
        "eligibility": {"eligible": False, "reasons": []},
        "source_identity": {
            "source_kind": None,
            "source_hash": "",
            "source_hash_provenance": "",
            "source_title": "",
        },
        "rights": {
            "rights_class": None,
            "rights_basis": "",
            "rights_review_required": None,
            "rights_review_status": None,
            "python_owned": True,
            "classified_by": "python",
        },
        "attempt": {"attempt_id": None, "job_id": None, "attempt_number": 1},
        "text_input": {
            "module_name": "",
            "description_bounded": False,
            "description_chars": 0,
        },
        "reason": ROUTING_REASON_INPUT_KIND_UNSUPPORTED,
        "diagnostics": [],
    }


def resolve_adaptation_input_route(
    input_kind: Any,
    enabled_override: Any = None,
    *,
    module_name: Any = None,
    description: Any = None,
    source_kind: Any = None,
    source_hash: Any = None,
    source_title: Any = None,
    rights_class: Any = None,
    rights_basis: Any = None,
    rights_review_required: Any = None,
    rights_review_status: Any = None,
    attempt_id: Any = None,
    job_id: Any = None,
    attempt_number: Any = 1,
) -> Dict[str, Any]:
    """Resolve the background build route for one supported Toolkit input.

    The decision is Python-owned and deterministic. Input eligibility is
    validated first, then the operator feature flag is resolved:

      * approved/upload-eligible Markdown and PDF uploads require a source
        identity (lowercase SHA-256 digest) and Python-owned rights
        classification (``user_authored`` or approved licensed/project-owned);
        restricted or missing rights remain review-gated and ineligible;
      * valid text-description input requires a path-safe module name plus
        non-empty bounded description text; rights are classified as
        ``user_authored`` by Python and the model is never asked to infer
        rights;
      * an exact boolean True flag selects the background ``llm_adaptation``
        route for every eligible input, with ``fallback_allowed=False``;
      * a missing, invalid, or exact boolean False flag resolves eligible
        inputs to the explicit legacy route requiring no adaptation
        artifacts;
      * unsupported or invalid input metadata resolves to an explicit
        ineligible (legacy-safe) outcome.

    Supplied upload source kind/hash/title, rights, and attempt identity
    fields are preserved in the decision. This function never calls a
    provider and never includes raw source content in its output.
    """
    kind = ""
    if isinstance(input_kind, str):
        kind = input_kind.strip().lower()

    flag_resolution = resolve_adaptation_routing(
        BUILD_MODE_LLM_ADAPTATION,
        enabled_override=enabled_override,
    )

    if kind not in VALID_INPUT_KINDS:
        decision = _base_route_decision(kind)
        decision["flag_resolution"] = flag_resolution
        decision["eligibility"] = {
            "eligible": False,
            "reasons": [ROUTING_REASON_INPUT_KIND_UNSUPPORTED],
        }
        decision["reason"] = ROUTING_REASON_INPUT_KIND_UNSUPPORTED
        decision["diagnostics"] = [
            {
                "code": ROUTING_REASON_INPUT_KIND_UNSUPPORTED,
                "message": "input kind is not supported",
            }
        ]
        return decision

    decision = _base_route_decision(kind)
    eligibility_reasons: List[str] = []
    diagnostics: List[Dict[str, str]] = []

    def _ineligible(code: str, message: str) -> None:
        eligibility_reasons.append(code)
        diagnostics.append({"code": code, "message": message})

    source_identity: Dict[str, Any] = decision["source_identity"]
    rights: Dict[str, Any] = decision["rights"]
    attempt: Dict[str, Any] = decision["attempt"]
    text_input: Dict[str, Any] = decision["text_input"]

    # ---- Input-kind specific eligibility ----------------------------------
    if kind in (INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF):
        if source_kind is not None:
            if isinstance(source_kind, str) and source_kind.strip():
                provided_kind = source_kind.strip().lower()
                if provided_kind != kind:
                    _ineligible(
                        ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH,
                        "upload source kind does not match the input kind",
                    )
                else:
                    source_identity["source_kind"] = provided_kind
            else:
                _ineligible(
                    ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH,
                    "upload source kind must be text matching the input kind",
                )
        if source_hash is None or not _is_sha256_digest(source_hash):
            _ineligible(
                ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING,
                "upload source hash is required for adaptation eligibility",
            )
        else:
            source_identity["source_hash"] = str(source_hash).strip().lower()
            source_identity["source_hash_provenance"] = "explicit_argument"
        if isinstance(source_title, str) and source_title.strip():
            source_identity["source_title"] = _bounded_text(
                source_title, MAX_ROUTE_SOURCE_TITLE_CHARS
            )[0]
    elif kind == INPUT_KIND_TEXT_DESCRIPTION:
        if module_name is None or not isinstance(module_name, str) or not module_name.strip():
            _ineligible(
                ROUTING_REASON_TEXT_NAME_MISSING,
                "text description requires a non-empty module name",
            )
        elif not _MODULE_SLUG_RE.fullmatch(module_name.strip()):
            _ineligible(
                ROUTING_REASON_TEXT_NAME_INVALID,
                "text description module name is not path-safe",
            )
        else:
            text_input["module_name"] = module_name.strip()
        if description is None:
            _ineligible(
                ROUTING_REASON_TEXT_DESCRIPTION_MISSING,
                "text description requires non-empty description text",
            )
        elif isinstance(description, (str, bytes)):
            raw_description: Optional[str] = None
            if isinstance(description, bytes):
                try:
                    raw_description = description.decode("utf-8")
                except UnicodeDecodeError:
                    _ineligible(
                        ROUTING_REASON_TEXT_DESCRIPTION_INVALID,
                        "text description is not valid UTF-8",
                    )
            else:
                raw_description = description
            if raw_description is not None:
                if raw_description.strip():
                    text_input["description_chars"] = len(raw_description)
                    if len(raw_description) > MAX_TEXT_DESCRIPTION_CHARS:
                        _ineligible(
                            ROUTING_REASON_TEXT_DESCRIPTION_OVERSIZED,
                            "text description exceeds the bounded length",
                        )
                    else:
                        text_input["description_bounded"] = True
                else:
                    _ineligible(
                        ROUTING_REASON_TEXT_DESCRIPTION_MISSING,
                        "text description requires non-empty description text",
                    )
        else:
            _ineligible(
                ROUTING_REASON_TEXT_DESCRIPTION_INVALID,
                "text description must be text or UTF-8 bytes",
            )

    # ---- Python-owned rights resolution ------------------------------------
    resolved_rights_class = rights_class
    resolved_rights_basis = rights_basis
    resolved_review_required = rights_review_required
    resolved_review_status = rights_review_status
    if kind == INPUT_KIND_TEXT_DESCRIPTION and resolved_rights_class is None:
        resolved_rights_class = RIGHTS_CLASS_USER_AUTHORED
        resolved_rights_basis = resolved_rights_basis or TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS
        resolved_review_required = False if resolved_review_required is None else resolved_review_required
        resolved_review_status = (
            RIGHTS_REVIEW_NOT_REQUIRED
            if resolved_review_status is None
            else resolved_review_status
        )

    rights["rights_class"] = resolved_rights_class
    rights["rights_review_required"] = resolved_review_required
    rights["rights_review_status"] = resolved_review_status
    if isinstance(resolved_rights_basis, str):
        rights["rights_basis"] = _bounded_text(
            resolved_rights_basis, MAX_ROUTE_RIGHTS_BASIS_CHARS
        )[0]

    if resolved_rights_class is None:
        _ineligible(ROUTING_REASON_RIGHTS_MISSING, "rights class is required for eligibility")
    elif resolved_rights_class not in VALID_RIGHTS_CLASSES:
        _ineligible(ROUTING_REASON_RIGHTS_METADATA_INVALID, "rights class is unsupported")
    elif resolved_rights_class == RIGHTS_CLASS_RESTRICTED:
        _ineligible(
            ROUTING_REASON_RIGHTS_REVIEW_REQUIRED,
            "restricted source remains review-gated",
        )
    if not isinstance(resolved_rights_basis, str) or not resolved_rights_basis.strip():
        _ineligible(ROUTING_REASON_RIGHTS_METADATA_INVALID, "rights basis is required")
    if not isinstance(resolved_review_required, bool):
        _ineligible(ROUTING_REASON_RIGHTS_METADATA_INVALID, "rights review requirement must be boolean")
    if resolved_review_status not in VALID_RIGHTS_REVIEW_STATUSES:
        _ineligible(ROUTING_REASON_RIGHTS_METADATA_INVALID, "rights review status is unsupported")
    if resolved_rights_class == RIGHTS_CLASS_RESTRICTED and resolved_review_required is not True:
        _ineligible(
            ROUTING_REASON_RIGHTS_REVIEW_CONTRADICTION,
            "restricted source requires rights review",
        )
    if resolved_review_required is True and resolved_review_status == RIGHTS_REVIEW_NOT_REQUIRED:
        _ineligible(
            ROUTING_REASON_RIGHTS_REVIEW_CONTRADICTION,
            "required review cannot be not_required",
        )
    if resolved_review_required is False and resolved_review_status in {
        RIGHTS_REVIEW_PENDING,
        RIGHTS_REVIEW_REJECTED,
    }:
        _ineligible(
            ROUTING_REASON_RIGHTS_REVIEW_CONTRADICTION,
            "non-required review cannot be pending or rejected",
        )

    # ---- Attempt / job identity preservation -------------------------------
    if attempt_id is not None:
        if _is_safe_attempt_id(attempt_id):
            attempt["attempt_id"] = attempt_id
        else:
            _ineligible(
                ROUTING_REASON_ATTEMPT_IDENTITY_INVALID,
                "attempt identity is not path-safe",
            )
    if job_id is not None:
        if isinstance(job_id, str) and job_id.strip():
            attempt["job_id"] = _bounded_text(job_id.strip(), MAX_ROUTE_JOB_ID_CHARS)[0]
        else:
            _ineligible(ROUTING_REASON_JOB_IDENTITY_INVALID, "job identity must be text")
    if attempt_number is not None:
        if (
            not isinstance(attempt_number, bool)
            and isinstance(attempt_number, int)
            and 1 <= attempt_number <= 1_000_000
        ):
            attempt["attempt_number"] = attempt_number
        else:
            _ineligible(
                ROUTING_REASON_ATTEMPT_NUMBER_INVALID,
                "attempt number is outside the supported range",
            )

    # ---- Route selection ----------------------------------------------------
    eligible = not eligibility_reasons
    if not eligible:
        status = ROUTE_DECISION_STATUS_INELIGIBLE
        route_selected = BUILD_MODE_LEGACY_ACCURATE_INGEST
        reason = eligibility_reasons[0]
        adaptation_artifacts_required = False
    elif flag_resolution["status"] == ROUTING_STATUS_ENABLED:
        status = ROUTE_DECISION_STATUS_ADAPTATION
        route_selected = BUILD_MODE_LLM_ADAPTATION
        reason = ROUTING_REASON_REQUESTED_AND_ENABLED
        adaptation_artifacts_required = True
    else:
        status = ROUTE_DECISION_STATUS_LEGACY
        route_selected = BUILD_MODE_LEGACY_ACCURATE_INGEST
        reason = str(flag_resolution.get("reason") or ROUTING_REASON_DISABLED)
        adaptation_artifacts_required = False

    decision["status"] = status
    decision["route_selected"] = route_selected
    decision["fallback_allowed"] = False
    decision["adaptation_artifacts_required"] = adaptation_artifacts_required
    decision["flag_resolution"] = flag_resolution
    decision["eligibility"] = {"eligible": eligible, "reasons": eligibility_reasons}
    decision["reason"] = reason
    decision["diagnostics"] = diagnostics
    return decision


def _validate_adaptation_selection_metadata(decision: Mapping[str, Any]) -> List[str]:
    """Fail-closed checks for a decision that claims an adaptation selection."""
    diagnostics: List[str] = []
    kind = decision.get("input_kind")
    if kind not in VALID_INPUT_KINDS:
        diagnostics.append("selected_input_kind_invalid")
        return diagnostics

    flag_resolution = decision.get("flag_resolution")
    if not isinstance(flag_resolution, Mapping) or flag_resolution.get("status") != ROUTING_STATUS_ENABLED:
        diagnostics.append("selected_route_flag_resolution_invalid")

    eligibility = decision.get("eligibility")
    if not isinstance(eligibility, Mapping) or eligibility.get("eligible") is not True:
        diagnostics.append("selected_route_not_eligible")

    rights = decision.get("rights")
    if not isinstance(rights, Mapping):
        diagnostics.append("selected_route_rights_missing")
    else:
        if rights.get("python_owned") is not True:
            diagnostics.append("selected_route_rights_not_python_owned")
        if rights.get("classified_by") != "python":
            diagnostics.append("selected_route_rights_not_python_classified")

    if kind in (INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF):
        source_identity = decision.get("source_identity")
        if not isinstance(source_identity, Mapping) or not _is_sha256_digest(
            source_identity.get("source_hash")
        ):
            diagnostics.append("selected_upload_source_identity_missing")
    elif kind == INPUT_KIND_TEXT_DESCRIPTION:
        text_input = decision.get("text_input")
        if not isinstance(text_input, Mapping):
            diagnostics.append("selected_text_input_missing")
        else:
            module_name = text_input.get("module_name")
            if not isinstance(module_name, str) or not _MODULE_SLUG_RE.fullmatch(module_name):
                diagnostics.append("selected_text_module_name_invalid")
            if text_input.get("description_bounded") is not True:
                diagnostics.append("selected_text_description_not_bounded")
            description_chars = text_input.get("description_chars")
            if not isinstance(description_chars, int) or description_chars < 1:
                diagnostics.append("selected_text_description_missing")

    attempt = decision.get("attempt")
    if isinstance(attempt, Mapping):
        attempt_id = attempt.get("attempt_id")
        if attempt_id is not None and not _is_safe_attempt_id(attempt_id):
            diagnostics.append("selected_attempt_identity_invalid")
        attempt_number = attempt.get("attempt_number")
        if (
            isinstance(attempt_number, bool)
            or not isinstance(attempt_number, int)
            or not 1 <= attempt_number <= 1_000_000
        ):
            diagnostics.append("selected_attempt_number_invalid")
    else:
        diagnostics.append("selected_attempt_identity_missing")

    if decision.get("fallback_allowed") is not False:
        diagnostics.append("fallback_not_allowed_invariant_violated")
    if decision.get("adaptation_artifacts_required") is not True:
        diagnostics.append("adaptation_artifacts_required_missing")
    return diagnostics


def _authority_marker(
    *,
    route_selected: str,
    authoritative: bool,
    status: str,
    reason: str,
    diagnostics: List[str],
    adaptation_artifacts_required: bool,
) -> Dict[str, Any]:
    """Return the bounded no-downgrade authority marker for a decision."""
    return {
        "contract_version": ROUTE_DECISION_CONTRACT_VERSION,
        "route_selected": route_selected,
        "status": status,
        "authoritative": authoritative,
        "fallback_allowed": False,
        "adaptation_artifacts_required": adaptation_artifacts_required,
        "reason": reason,
        "diagnostics": diagnostics,
    }


def validate_adaptation_route_decision(value: Any) -> Dict[str, Any]:
    """Validate a route decision and expose its no-downgrade authority marker.

    A selected adaptation route is authoritative: the marker always reports
    ``fallback_allowed=False`` and never resolves a selected adaptation to
    legacy. Invalid or missing selected-route metadata fails closed with
    ``status=failed_closed`` instead of silently degrading. Legacy and
    ineligible decisions are explicit selections that require no adaptation
    artifacts.
    """
    if not isinstance(value, Mapping):
        return _authority_marker(
            route_selected=BUILD_MODE_LLM_ADAPTATION,
            authoritative=False,
            status=ROUTE_DECISION_STATUS_FAILED_CLOSED,
            reason=ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID,
            diagnostics=["route_decision_must_be_object"],
            adaptation_artifacts_required=True,
        )

    diagnostics: List[str] = []
    if value.get("contract_version") != ROUTE_DECISION_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    if value.get("fallback_allowed") is not False:
        diagnostics.append("fallback_not_allowed_invariant_violated")

    status = value.get("status")
    route_selected = value.get("route_selected")
    if status == ROUTE_DECISION_STATUS_ADAPTATION:
        diagnostics.extend(_validate_adaptation_selection_metadata(value))
        if route_selected != BUILD_MODE_LLM_ADAPTATION:
            diagnostics.append("adaptation_route_selection_missing")
    elif status in (ROUTE_DECISION_STATUS_LEGACY, ROUTE_DECISION_STATUS_INELIGIBLE):
        if route_selected != BUILD_MODE_LEGACY_ACCURATE_INGEST:
            diagnostics.append("legacy_route_selection_missing")
        if value.get("adaptation_artifacts_required") is not False:
            diagnostics.append("legacy_requires_adaptation_artifacts")
    else:
        diagnostics.append("route_decision_status_invalid")

    if diagnostics:
        reported_route = route_selected
        if reported_route not in (BUILD_MODE_LLM_ADAPTATION, BUILD_MODE_LEGACY_ACCURATE_INGEST):
            reported_route = BUILD_MODE_LLM_ADAPTATION
        return _authority_marker(
            route_selected=reported_route,
            authoritative=False,
            status=ROUTE_DECISION_STATUS_FAILED_CLOSED,
            reason=ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID,
            diagnostics=diagnostics,
            adaptation_artifacts_required=(reported_route == BUILD_MODE_LLM_ADAPTATION),
        )

    if status in (ROUTE_DECISION_STATUS_LEGACY, ROUTE_DECISION_STATUS_INELIGIBLE):
        return _authority_marker(
            route_selected=BUILD_MODE_LEGACY_ACCURATE_INGEST,
            authoritative=True,
            status=ROUTE_DECISION_STATUS_LEGACY,
            reason=(
                ROUTE_AUTHORITY_REASON_INELIGIBLE_SAFE
                if status == ROUTE_DECISION_STATUS_INELIGIBLE
                else ROUTE_AUTHORITY_REASON_LEGACY_EXPLICIT
            ),
            diagnostics=[],
            adaptation_artifacts_required=False,
        )
    return _authority_marker(
        route_selected=BUILD_MODE_LLM_ADAPTATION,
        authoritative=True,
        status=ROUTE_DECISION_STATUS_ADAPTATION,
        reason=ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED,
        diagnostics=[],
        adaptation_artifacts_required=True,
    )


__all__ = [
    "BUILD_MODE_LEGACY_ACCURATE_INGEST",
    "BUILD_MODE_LLM_ADAPTATION",
    "ENABLE_LLM_ADAPTATION_DEFAULT",
    "INPUT_KIND_TEXT_DESCRIPTION",
    "INPUT_KIND_UPLOAD_MARKDOWN",
    "INPUT_KIND_UPLOAD_PDF",
    "LEGACY_ACCURATE_INGEST_BUILD_MODES",
    "MAX_TEXT_DESCRIPTION_CHARS",
    "ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED",
    "ROUTE_AUTHORITY_REASON_INELIGIBLE_SAFE",
    "ROUTE_AUTHORITY_REASON_LEGACY_EXPLICIT",
    "ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID",
    "ROUTE_DECISION_CONTRACT_VERSION",
    "ROUTE_DECISION_STATUS_ADAPTATION",
    "ROUTE_DECISION_STATUS_FAILED_CLOSED",
    "ROUTE_DECISION_STATUS_INELIGIBLE",
    "ROUTE_DECISION_STATUS_LEGACY",
    "ROUTING_REASON_ATTEMPT_IDENTITY_INVALID",
    "ROUTING_REASON_ATTEMPT_NUMBER_INVALID",
    "ROUTING_REASON_DISABLED",
    "ROUTING_REASON_INPUT_KIND_UNSUPPORTED",
    "ROUTING_REASON_INVALID_REQUEST",
    "ROUTING_REASON_JOB_IDENTITY_INVALID",
    "ROUTING_REASON_NOT_REQUESTED",
    "ROUTING_REASON_REQUESTED_AND_ENABLED",
    "ROUTING_REASON_RIGHTS_METADATA_INVALID",
    "ROUTING_REASON_RIGHTS_MISSING",
    "ROUTING_REASON_RIGHTS_REVIEW_CONTRADICTION",
    "ROUTING_REASON_RIGHTS_REVIEW_REQUIRED",
    "ROUTING_REASON_TEXT_DESCRIPTION_INVALID",
    "ROUTING_REASON_TEXT_DESCRIPTION_MISSING",
    "ROUTING_REASON_TEXT_DESCRIPTION_OVERSIZED",
    "ROUTING_REASON_TEXT_NAME_INVALID",
    "ROUTING_REASON_TEXT_NAME_MISSING",
    "ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_INVALID",
    "ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING",
    "ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH",
    "ROUTING_STATUS_ENABLED",
    "ROUTING_STATUS_LEGACY",
    "TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS",
    "VALID_INPUT_KINDS",
    "adaptation_enabled",
    "is_legacy_accurate_ingest_build_mode",
    "is_llm_adaptation_build_mode",
    "resolve_adaptation_input_route",
    "resolve_adaptation_routing",
    "validate_adaptation_route_decision",
]
