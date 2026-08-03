# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit LLM Final Reconciliation
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

LLM Builder final editor runner and prompt assembly for the
accurate-ingest final editorial reconciliation pass.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import copy
import fnmatch
import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.ai_client_factory import (
    create_chat_client,
    get_chat_completion_params,
)
from utils.enhanced_logger import warning
from utils.file_operations import safe_read_json, safe_write_json

# ---------------------------------------------------------------------------
# Stable constants
# ---------------------------------------------------------------------------

FINAL_RECONCILIATION_PROMPT_PATH = (
    Path("prompts") / "toolkit" / "final_reconciliation_builder_prompt.txt"
)
FINAL_RECONCILIATION_TASK_ID = "toolkit_final_reconciliation"
FINAL_RECONCILIATION_PATCH_VERSION = (
    "accurate_ingest_final_reconciliation_patch.v1"
)
FINAL_RECONCILIATION_DEFAULT_TEMPERATURE = 0.2
FINAL_RECONCILIATION_DEFAULT_TIMEOUT_SECONDS = 120

# Required top-level keys for a valid final-reconciliation patch plan. These
# match the prompt and design contract (Step 2.1, Design Decision 2). Keys
# appear in prompt-declared order to make diagnostic output deterministic.
FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS = (
    "version",
    "status",
    "source_fidelity_claim",
    "publication_intent",
    "decisions",
    "file_patches",
)

# Allowed values for the top-level "status" field. Any other value
# is treated as missing-or-invalid by the parse helper.
FINAL_RECONCILIATION_PATCH_STATUS_READY = "ready"
FINAL_RECONCILIATION_PATCH_STATUS_REFUSED = "refused"
FINAL_RECONCILIATION_PATCH_STATUS_FAILED = "failed"

# Step 3.3: Source-fidelity-claim honesty constants. The archived
# boundary change requires accepted reconciliation to expose
# ``source_fidelity_effective_status: reconciled_degraded`` and
# forbids claiming a clean pass when the original source fidelity
# was blocked or degraded. The constants below are the source of
# truth for the Step 3.3 validation helper and the runner wiring.
FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED = (
    "reconciled_degraded"
)
# Variants that denote a clean source-fidelity pass. Any plan that
# carries one of these claims while claiming ``status: ready`` is
# rejected as a false clean claim. The set is intentionally broader
# than the strict prompt-declared value to catch LLM drift to
# equivalent clean-pass language.
FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS = (
    "pass",
    "clean_pass",
    "clean",
    "source_fidelity_pass",
)

# Status names emitted by run_llm_final_editor(...)
RUNNER_STATUS_SUCCESS = "success"
RUNNER_STATUS_PROVIDER_FAILED = "provider_failed"
RUNNER_STATUS_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
RUNNER_STATUS_INVALID_BRIEF = "invalid_brief"
RUNNER_STATUS_INVALID_JSON = "invalid_json"
RUNNER_STATUS_MISSING_REQUIRED_KEYS = "missing_required_keys"
RUNNER_STATUS_REFUSED_RECONCILIATION = "refused_reconciliation"
RUNNER_STATUS_FAILED_RECONCILIATION = "failed_reconciliation"
RUNNER_STATUS_INVALID_PATCH_CONTRACT = "invalid_patch_contract"

# Diagnostic severity tags. Kept ASCII-only and small so the structured
# diagnostics list can be cheaply serialized into reports and logs.
DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_SEVERITY_WARNING = "warning"

# Diagnostic codes. Each code is a stable, ASCII-only string emitted as
# diagnostics[].code. Add new codes here when a new failure class is
# introduced so downstream reports can key on them.
DIAGNOSTIC_CODE_INVALID_BRIEF = "invalid_brief"
DIAGNOSTIC_CODE_PROVIDER_FAILED = "provider_failed"
DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED = "param_resolution_failed"
DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS = "missing_required_keys"
DIAGNOSTIC_CODE_REFUSED_RECONCILIATION = "refused_reconciliation"
DIAGNOSTIC_CODE_FAILED_RECONCILIATION = "failed_reconciliation"
# Step 3.1: contract-validation diagnostic codes.
DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT = "invalid_patch_contract"
DIAGNOSTIC_CODE_UNSUPPORTED_VERSION = "unsupported_version"
DIAGNOSTIC_CODE_UNSUPPORTED_STATUS = "unsupported_status"
DIAGNOSTIC_CODE_INVALID_DECISIONS = "invalid_decisions"
DIAGNOSTIC_CODE_INVALID_FILE_PATCHES = "invalid_file_patches"
DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE = "unsupported_decision_type"
# Step 3.2: target-validation diagnostic codes.
DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET = "forbidden_patch_target"
DIAGNOSTIC_CODE_INVALID_PATCH_TARGET = "invalid_patch_target"
DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING = "editable_surfaces_missing"
# Step 3.3: source-fidelity-claim validation diagnostic code.
DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM = "invalid_source_fidelity_claim"
# Step 3.4: patch application diagnostic codes.
DIAGNOSTIC_CODE_INVALID_PATCH_PLAN = "invalid_patch_plan"
DIAGNOSTIC_CODE_INVALID_OP = "invalid_op"
DIAGNOSTIC_CODE_INVALID_JSON_PATH = "invalid_json_path"
DIAGNOSTIC_CODE_MISSING_MODULE_DIR = "missing_module_dir"
DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED = "target_file_read_failed"
DIAGNOSTIC_CODE_TARGET_FILE_WRITE_FAILED = "target_file_write_failed"
DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED = "patch_application_failed"
# Step 3.5: post-write JSON parse validation and parity mirror codes.
DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID = "written_json_invalid"
DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED = "parity_counterpart_write_failed"
# Step 4.1: schema-validation diagnostic codes. Two distinct codes so
# downstream reports can distinguish between a clean schema-validation
# failure (the validator ran and surfaced structured errors) and an
# exception in the schema-validation path itself (the validator
# crashed or could not be invoked).
DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR = "schema_validation_error"
# Step 4.2: publication-gate diagnostic codes. One per gate so
# downstream reports can key on the failing class:
# - readiness gate reported non-pass overall_status
# - publishability gate reported non-pass publishable_status
# - report agreement returned a blocked status (typically due to
#   contradictions across the input statuses)
# - any helper in the gate pipeline raised an exception
DIAGNOSTIC_CODE_GATE_READINESS_FAILED = "gate_readiness_failed"
DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED = "gate_publishability_failed"
DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED = (
    "gate_report_agreement_blocked"
)
DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION = "gate_helper_exception"
# Step 4.3: bounded-retry diagnostic codes. Two distinct codes so
# downstream reports can distinguish between "the failure was not a
# retryable class" and "the retry budget is exhausted after the
# second attempt also failed".
DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE = "retry_not_repairable"
DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"

# Step 4.1: schema-validation status names emitted by
# ``run_final_reconciliation_schema_validation(...)`` and surfaced
# through the orchestrator's ``schema_validation.status`` field.
# The four values cover the full lifecycle:
# - "pass": validator ran and reported no failed files.
# - "fail": validator ran and reported at least one failed file.
# - "error": validator could not be invoked or raised an exception.
# - "not_run": validation was skipped because the apply phase did
#   not produce any changes (used by the orchestrator only).
FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS = "pass"
FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL = "fail"
FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR = "error"
FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN = "not_run"

# Step 4.2: publication-gate status names emitted by
# ``run_final_reconciliation_publication_gates(...)`` and surfaced
# through the orchestrator's ``gates.status`` field. The four values
# cover the full lifecycle:
# - "pass": all three gates (readiness, publishability, report
#   agreement) returned pass.
# - "fail": one or more gates reported a non-pass status.
# - "error": a gate helper raised an exception and was caught
#   fail-closed.
# - "not_run": the gate phase was skipped because apply/schema did
#   not pass (used by the orchestrator only).
FINAL_RECONCILIATION_GATE_STATUS_PASS = "pass"
FINAL_RECONCILIATION_GATE_STATUS_FAIL = "fail"
FINAL_RECONCILIATION_GATE_STATUS_ERROR = "error"
FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN = "not_run"

# Step 4.2: the only accepted source-fidelity effective status
# emitted by an accepted final-reconciliation gate. The value matches
# the archived boundary's contract that accepted reconciliation MUST
# report ``source_fidelity_effective_status: reconciled_degraded``.
# Centralized here so the helper and the orchestrator emit the
# exact same string the boundary and report-agreement composer
# expect.
FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS = (
    "reconciled_degraded"
)
FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS = "accepted"

# Allowed decision types for a final-reconciliation patch plan. The list
# matches the prompt and design contract (Step 2.1; design.md "Patch
# Contract" section; prompt section "Allowed decision types"). The
# tuple is the source of truth and is exported for tests and for
# downstream code that needs to enumerate the allowed types.
FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM = "delete_bogus_atom"
FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM = "reclassify_atom"
FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING = "merge_into_existing"
FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE = (
    "preserve_as_dm_guidance"
)
FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT = (
    "create_missing_real_element"
)
FINAL_RECONCILIATION_DECISION_REFUSE = "refuse"

FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES = (
    FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
    FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
    FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING,
    FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
    FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
    FINAL_RECONCILIATION_DECISION_REFUSE,
)

# Allowed patch ops for a final-reconciliation file_patches entry. The
# list matches the prompt section "HARD RULES" item 7 and the design
# "Patch Contract" section. The tuple is the source of truth and is
# exported for tests and for downstream code that needs to enumerate
# the allowed ops.
FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY = "remove_key"
FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY = "rename_key"
FINAL_RECONCILIATION_PATCH_OP_SET_VALUE = "set_value"
FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY = "remove_array_entry"
FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING = "merge_into_existing"

FINAL_RECONCILIATION_ALLOWED_PATCH_OPS = (
    FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
    FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
    FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
    FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
    FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
)

# Step 3.4: Patch application status values emitted by
# ``apply_final_reconciliation_patch_plan(...)``.
FINAL_RECONCILIATION_APPLY_STATUS_APPLIED = "applied"
FINAL_RECONCILIATION_APPLY_STATUS_FAILED = "failed"

# Mock provider marker used when the runner is invoked with an
# injected raw-output override. The runner short-circuits the live
# provider path and returns this model name so downstream tests can
# distinguish a mock-driven result from a live-provider result.
RUNNER_MOCK_MODEL = "mock_provider"
RUNNER_MOCK_PARAMS_MARKER = {"mock_provider": True}

# Short ASCII-only fallback used only if the prompt file cannot be loaded.
# Kept minimal so the runner can still wire messages in degraded environments.
FINAL_RECONCILIATION_PROMPT_FALLBACK = (
    "You are a final editorial reconciliation assistant for the "
    "NeverEndingQuest accurate-ingest ModuleBuilder pipeline. "
    "Return VALID JSON ONLY matching the "
    "accurate_ingest_final_reconciliation_patch.v1 contract."
)

try:
    # model_config is the canonical source for the default OpenAI model.
    # Import defensively so this module can be imported in tests without the
    # full app configuration present.
    from model_config import DM_MAIN_MODEL
except Exception:  # pragma: no cover - defensive import
    DM_MAIN_MODEL = "gpt-4.1-2025-04-14"

# Repository root used to anchor the schema directory for
# ``ModuleValidator``. ``utils/toolkit_llm_final_reconciliation.py`` lives at
# ``<repo>/utils/`` so ``Path(__file__).resolve().parents[1]`` resolves to the
# repository root. The constant is module-internal (no test pinning) and is
# used only when ``run_final_reconciliation_schema_validation(...)`` is
# invoked. Tests mock ``ModuleValidator`` directly, so this constant does
# not need to be exported.
_TOOLKIT_FINAL_RECONCILIATION_REPO_ROOT = Path(
    __file__
).resolve().parents[1]

try:
    # ``ModuleValidator`` is the canonical schema-validation entry point. The
    # import is wrapped in try/except so the module can still be imported in
    # environments where the validation package is not on sys.path; tests
    # always mock ``ModuleValidator`` so the real class is not required.
    from core.validation.validate_module_files import ModuleValidator
except Exception:  # pragma: no cover - defensive import
    ModuleValidator = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _load_final_reconciliation_prompt() -> str:
    """Load the final-reconciliation prompt template from disk.

    Returns a short ASCII-only fallback string if the file is missing or
    unreadable so the runner can still wire messages in degraded
    environments. This runner is provider-aware; it does not interpret
    the prompt contents.
    """
    try:
        text = FINAL_RECONCILIATION_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: Prompt load failed: "
            f"{exc}; using fallback contract.",
            category="toolkit_final_reconciliation",
        )
        return FINAL_RECONCILIATION_PROMPT_FALLBACK
    if not text:
        return FINAL_RECONCILIATION_PROMPT_FALLBACK
    return text


def _serialize_brief(brief: Dict[str, Any]) -> str:
    """Return deterministic compact JSON serialization of the brief.

    Uses sort_keys=True for stable ordering across runs and
    ensure_ascii=True so the serialized payload is safe to round-trip
    through the same code paths that already gate the legacy
    builder/normalizer payloads.
    """
    return json.dumps(
        brief,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _build_chat_messages(brief: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build Chat Completions messages for the final reconciliation brief.

    Returns a list of two messages:

    - system/developer message: the prompt contract loaded from disk
    - user message: a labeled, deterministic JSON serialization of the
      brief

    The serialization helpers in this module are read-only and do NOT
    mutate the input brief.
    """
    system_content = _load_final_reconciliation_prompt()
    user_content = "FINAL_RECONCILIATION_BRIEF:\n" + _serialize_brief(brief)
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Response extraction helpers
# ---------------------------------------------------------------------------

def _extract_response_text(response: Any) -> str:
    """Best-effort extraction of model output text from a chat response.

    Returns an empty string when the response is malformed; downstream
    fail-closed validation (Step 2.4) is responsible for rejecting
    empty or invalid content.
    """
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        return str(content or "")
    except Exception:
        return ""


def _extract_response_model(response: Any, fallback_model: str) -> str:
    """Best-effort extraction of model name from a chat response.

    Returns the fallback model when the response does not carry one
    (e.g. when a mock client is used in tests).
    """
    try:
        model = getattr(response, "model", None)
        if isinstance(model, str) and model:
            return model
    except Exception:
        pass
    return fallback_model


# ---------------------------------------------------------------------------
# Structured diagnostics and JSON parse helpers (Step 2.4)
# ---------------------------------------------------------------------------

# Regex used to strip an optional markdown code fence (``` or ```json) from
# the LLM response. The capture group is the inner content between the
# fences. We deliberately keep this very small and fail-closed: if the
# outer fence markers are malformed, the regex returns None and the parse
# helper falls back to the verbatim text.
_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def _make_diagnostic(
    code: str,
    message: str,
    severity: str = DIAGNOSTIC_SEVERITY_ERROR,
) -> Dict[str, str]:
    """Build a single structured diagnostic dict.

    Args:
        code: Stable diagnostic code (one of the DIAGNOSTIC_CODE_*
            constants or a small custom ASCII-only string).
        message: Human-readable diagnostic message. Must be ASCII-only.
        severity: Either ``"error"`` (default) or ``"warning"``.

    Returns:
        ``{"code": <code>, "message": <message>, "severity": <severity>}``
    """
    return {
        "code": str(code),
        "message": str(message),
        "severity": str(severity),
    }


def _strip_optional_json_fence(raw_text: str) -> str:
    """Return the inner content of a single optional JSON markdown fence.

    Providers sometimes wrap the JSON object in ```` ```json ... ``` ````
    despite prompt instructions to emit raw JSON only. This helper
    strips a single outer fence pair when the body appears to be a
    well-formed JSON object (``{...}``).

    The function is intentionally small and safe:

    - Returns the input unchanged when the text is empty.
    - Returns the input unchanged when no outer fence is detected.
    - Returns the input unchanged when the inner content is not a
      balanced ``{...}`` JSON object.
    - Returns the stripped body otherwise.

    This avoids unsafe heuristics like scanning for any first ``{`` /
    last ``}`` substring in long outputs that may contain prose.
    """
    if not isinstance(raw_text, str):
        return ""
    text = raw_text.strip()
    if not text:
        return ""
    match = _JSON_FENCE_RE.match(text)
    if not match:
        return raw_text
    inner = match.group(1).strip()
    if not inner:
        return raw_text
    if not (inner.startswith("{") and inner.endswith("}")):
        return raw_text
    return inner


def _try_parse_patch_json(
    raw_text: str,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """Attempt to parse a strict JSON object from raw LLM response text.

    Returns ``(parsed_dict, diagnostics)``. On success ``parsed_dict`` is
    a ``dict`` and ``diagnostics`` is empty. On failure ``parsed_dict``
    is ``None`` and ``diagnostics`` contains a single
    ``invalid_json`` diagnostic with a short ASCII-only message
    describing the failure (truncated to avoid leaking the full prompt
    output into logs).

    The function NEVER mutates the caller and NEVER raises. It is
    fail-closed by design: any non-JSON, partial, or type-mismatched
    payload returns a single diagnostic.
    """
    if not isinstance(raw_text, str):
        return (
            None,
            [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    "raw_response_text is not a string",
                )
            ],
        )
    text = raw_text.strip()
    if not text:
        return (
            None,
            [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    "raw_response_text is empty",
                )
            ],
        )
    candidate = _strip_optional_json_fence(text)
    if not candidate.strip():
        return (
            None,
            [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    "raw_response_text contains no JSON content",
                )
            ],
        )
    try:
        parsed_obj = json.loads(candidate)
    except Exception as exc:
        # Truncate the message so logs and structured reports do not
        # contain the entire malformed LLM payload.
        msg = str(exc)
        if len(msg) > 200:
            msg = msg[:200] + "..."
        return (
            None,
            [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    f"json.loads failed: {msg}",
                )
            ],
        )
    if not isinstance(parsed_obj, dict):
        return (
            None,
            [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_JSON,
                    "top-level JSON value is not an object",
                )
            ],
        )
    return parsed_obj, []


def _validate_required_top_level_keys(
    parsed: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Return a list of ``missing_required_keys`` diagnostics.

    Iterates ``FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS`` in
    declared order and emits one diagnostic per missing key. The
    diagnostic message includes the missing key name so downstream
    reports can list every gap in a single pass.
    """
    diagnostics: List[Dict[str, str]] = []
    for key in FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS:
        if key not in parsed:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS,
                    f"missing required top-level key: {key}",
                )
            )
    return diagnostics


def _parse_runner_response(
    raw_text: str,
) -> Tuple[Optional[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Parse and validate a raw LLM response into a normalized result.

    Returns a tuple of ``(patch_plan, status, diagnostics)`` where:

    - ``patch_plan`` is the parsed JSON object on parse success
      (including when the editor returned ``refused`` or ``failed``);
      it is an empty dict on parse failure so the caller can still
      branch on truthiness.
    - ``status`` is one of:

      - ``RUNNER_STATUS_SUCCESS`` when the editor returned a
        ``status: ready`` patch plan with all required keys.
      - ``RUNNER_STATUS_INVALID_JSON`` when the response was empty,
        malformed, freeform prose, or not a JSON object.
      - ``RUNNER_STATUS_MISSING_REQUIRED_KEYS`` when the response
        parsed as a JSON object but at least one required top-level
        key is absent.
      - ``RUNNER_STATUS_REFUSED_RECONCILIATION`` when the editor
        returned ``status: refused`` with all required keys.
      - ``RUNNER_STATUS_FAILED_RECONCILIATION`` when the editor
        returned ``status: failed`` with all required keys.

    - ``diagnostics`` is the list of structured errors accumulated
      during parse. Empty when parse + validation + status all pass.

    The function NEVER mutates the caller and NEVER raises.
    """
    parsed, diagnostics = _try_parse_patch_json(raw_text)
    if parsed is None:
        # Parse failed; an ``invalid_json`` diagnostic is already in
        # ``diagnostics``. ``patch_plan`` is empty dict so callers
        # can still branch.
        return {}, RUNNER_STATUS_INVALID_JSON, diagnostics

    missing_diagnostics = _validate_required_top_level_keys(parsed)
    if missing_diagnostics:
        return (
            {},
            RUNNER_STATUS_MISSING_REQUIRED_KEYS,
            diagnostics + missing_diagnostics,
        )

    status_value = parsed.get("status")
    if not isinstance(status_value, str):
        return (
            parsed,
            RUNNER_STATUS_MISSING_REQUIRED_KEYS,
            diagnostics
            + [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS,
                    "top-level 'status' is not a string",
                )
            ],
        )

    if status_value == FINAL_RECONCILIATION_PATCH_STATUS_READY:
        # Step 3.1: gate success on the patch-contract validation. The
        # parsed object has all required top-level keys (verified
        # above), so the contract helper is safe to run.
        contract_valid, contract_diagnostics = (
            validate_final_reconciliation_patch_contract(parsed)
        )
        if not contract_valid:
            return (
                parsed,
                RUNNER_STATUS_INVALID_PATCH_CONTRACT,
                contract_diagnostics,
            )
        return parsed, RUNNER_STATUS_SUCCESS, []
    if status_value == FINAL_RECONCILIATION_PATCH_STATUS_REFUSED:
        refused_diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REFUSED_RECONCILIATION,
                "editor returned status=refused; patch plan preserved",
            )
        ]
        # Step 3.1: still run the contract helper to surface any
        # malformed decision/file-patch shape alongside the refusal.
        # The contract helper will not flag the status itself (refused
        # is in the allowlist) so this only appends shape diagnostics.
        _, contract_diagnostics = (
            validate_final_reconciliation_patch_contract(parsed)
        )
        return (
            parsed,
            RUNNER_STATUS_REFUSED_RECONCILIATION,
            refused_diagnostics + contract_diagnostics,
        )
    if status_value == FINAL_RECONCILIATION_PATCH_STATUS_FAILED:
        failed_diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_FAILED_RECONCILIATION,
                "editor returned status=failed; patch plan preserved",
            )
        ]
        # Step 3.1: same shape-diagnostics pass for failed plans.
        _, contract_diagnostics = (
            validate_final_reconciliation_patch_contract(parsed)
        )
        return (
            parsed,
            RUNNER_STATUS_FAILED_RECONCILIATION,
            failed_diagnostics + contract_diagnostics,
        )

    # Unknown string status value: treat as missing required keys to
    # fail closed while still preserving the parsed object for
    # inspection.
    return (
        parsed,
        RUNNER_STATUS_MISSING_REQUIRED_KEYS,
        diagnostics
        + [
            _make_diagnostic(
                DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS,
                f"unknown top-level 'status' value: {status_value!r}",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Patch contract validation (Step 3.1)
# ---------------------------------------------------------------------------

def validate_final_reconciliation_patch_contract(
    patch_plan: Any,
) -> Tuple[bool, List[Dict[str, str]]]:
    """Validate the strict shape of a parsed final-reconciliation patch plan.

    The patch contract is the bounded shape defined in the design.md
    "Patch Contract" section and the prompt section "Allowed decision
    types". This helper enforces ONLY the shape rules. It does NOT
    inspect file-patch targets, source-fidelity claims, or content
    fields like ``from``/``to``/``reason``; those concerns are owned
    by later Step 3.2 (file targets), Step 3.3 (source-fidelity
    claims), and Section 4 (validation loop).

    Validation rules (in order):

    1. ``patch_plan`` MUST be a ``dict``.
    2. ``version`` MUST equal
       :data:`FINAL_RECONCILIATION_PATCH_VERSION`
       (current pin: ``accurate_ingest_final_reconciliation_patch.v1``).
    3. ``status`` MUST be one of ``ready``, ``refused``, ``failed``
       (the three top-level statuses defined in
       :data:`FINAL_RECONCILIATION_PATCH_STATUS_READY` /
       :data:`FINAL_RECONCILIATION_PATCH_STATUS_REFUSED` /
       :data:`FINAL_RECONCILIATION_PATCH_STATUS_FAILED`).
    4. ``decisions`` MUST be a ``list``. Each entry MUST be a ``dict``
       with a string ``"decision"`` key whose value is one of
       :data:`FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES`.
    5. ``file_patches`` MUST be a ``list``. The list shape is the only
       thing checked here; ``file_patches[].path`` and other target
       fields are owned by Step 3.2.

    All rules are checked and reported. The function never short-circuits
    on the first violation so callers can surface every contract issue
    in a single pass.

    Args:
        patch_plan: A parsed final-reconciliation patch plan (typically
            the output of :func:`_try_parse_patch_json`). Any value is
            accepted; non-dict inputs are rejected with a single
            ``invalid_patch_contract`` diagnostic.

    Returns:
        Tuple ``(is_valid, diagnostics)``. ``is_valid`` is True only
        when every rule passes. ``diagnostics`` is the list of
        structured ``{"code", "message", "severity"}`` dicts
        accumulated during validation. The list is empty on a fully
        valid plan.

    Notes:
        The function NEVER mutates the input and NEVER raises.
    """
    diagnostics: List[Dict[str, str]] = []

    if not isinstance(patch_plan, dict):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT,
                "patch plan is not a dict",
            )
        )
        return False, diagnostics

    # Version pin.
    version_value = patch_plan.get("version")
    if version_value != FINAL_RECONCILIATION_PATCH_VERSION:
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_UNSUPPORTED_VERSION,
                f"unsupported patch plan version: {version_value!r}; "
                f"expected {FINAL_RECONCILIATION_PATCH_VERSION!r}",
            )
        )

    # Top-level status allowlist.
    status_value = patch_plan.get("status")
    if status_value not in (
        FINAL_RECONCILIATION_PATCH_STATUS_READY,
        FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
        FINAL_RECONCILIATION_PATCH_STATUS_FAILED,
    ):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_UNSUPPORTED_STATUS,
                f"unsupported top-level status: {status_value!r}",
            )
        )

    # decisions: list shape + per-entry shape.
    decisions = patch_plan.get("decisions")
    if not isinstance(decisions, list):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_DECISIONS,
                f"decisions is not a list (type={type(decisions).__name__})",
            )
        )
    else:
        for index, entry in enumerate(decisions):
            if not isinstance(entry, dict):
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_INVALID_DECISIONS,
                        f"decisions[{index}] is not a dict",
                    )
                )
                continue
            if "decision" not in entry:
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_INVALID_DECISIONS,
                        f"decisions[{index}] missing required 'decision' key",
                    )
                )
                continue
            decision_value = entry.get("decision")
            if not isinstance(decision_value, str):
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_INVALID_DECISIONS,
                        f"decisions[{index}].decision is not a string",
                    )
                )
                continue
            if (
                decision_value
                not in FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES
            ):
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE,
                        f"decisions[{index}] has unsupported decision "
                        f"type: {decision_value!r}",
                    )
                )

    # file_patches: list shape ONLY. file_patches[].path and other
    # target fields are owned by Step 3.2.
    file_patches = patch_plan.get("file_patches")
    if not isinstance(file_patches, list):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_FILE_PATCHES,
                f"file_patches is not a list (type={type(file_patches).__name__})",
            )
        )

    return (len(diagnostics) == 0), diagnostics


# ---------------------------------------------------------------------------
# Step 3.2: Patch target validation against editable_surfaces
# ---------------------------------------------------------------------------

# Runtime-only forbidden target patterns. Any target matching one of
# these is rejected before the editable_surfaces whitelist check, even
# if the brief happens to list it. Plain strings are matched as exact
# filenames; strings containing ``*`` are matched with ``fnmatch``;
# strings ending in ``/`` are matched as directory prefixes.
_FORBIDDEN_RUNTIME_TARGET_PATTERNS = (
    "module_plot.json",
    "party_tracker.json",
    "player_quests_*.json",
    "encounters/",
    "modules/world_registry.json",
    "modules/campaign.json",
)

# Source/middle pipeline artifact forbidden patterns. The LLM final
# editor must never rewrite source graph, source manifest, normalized
# packet, blueprint, backstage audit, or ingestion artifacts.
# NOTE: The blueprint pattern is intentionally ``*blueprint*.json``
# (not ``blueprint_*.json``) so it matches the production filenames
# ``builder_blueprint.json`` and ``builder_blueprint_report.json`` as
# well as any future variants like ``blueprint_v2.json`` or
# ``source_blueprint.json``. The previous literal-prefix pattern
# silently allowed the production blueprint artifacts to be patched,
# which violated the Step 5.3 front/middle immutability spec.
_FORBIDDEN_SOURCE_MIDDLE_PATTERNS = (
    "source_graph.json",
    "source_manifest.json",
    "normalized_packet.json",
    "*blueprint*.json",
    "accurate_ingest_audit_run/",
    "agent_runs/",
    "MODULE_SUMMARY.md",
)

# Carve-out for the ``areas/*.json`` rule. Live area files are
# runtime-only and must be rejected; canonical ``*_BU.json`` backups
# are whitelisted via the brief's editable_surfaces.
_FORBIDDEN_AREAS_BASENAME_MUST_NOT_END_WITH = (
    "_BU.json",
)


def _has_backslash(target: str) -> bool:
    """Return True if ``target`` contains a backslash character.

    Used to reject Windows-style separators on the safer cross-platform
    default. The forward-slash form is the only normalized form allowed
    in editable_surfaces entries.
    """
    return isinstance(target, str) and "\\" in target


def _is_absolute_path(target: str) -> bool:
    """Return True if ``target`` looks like an absolute filesystem path.

    Rejects POSIX absolute paths (leading ``/``) and Windows drive
    paths (any single letter followed by ``:``). ``C:`` is a drive
    reference without a separator and is also rejected.
    """
    if not isinstance(target, str) or not target:
        return False
    if target.startswith("/"):
        return True
    if (
        len(target) >= 2
        and target[1] == ":"
        and target[0].isalpha()
    ):
        return True
    return False


def _has_path_traversal(target: str) -> bool:
    """Return True if any forward-slash path component is exactly ``..``.

    Rejects ``..`` as a component rather than relying on
    ``posixpath.normpath`` collapsing traversal away, because the latter
    would silently turn ``foo/../bar`` into ``bar`` and miss the
    escape attempt. A literal ``..`` segment in the candidate target is
    always rejected.
    """
    if not isinstance(target, str) or not target:
        return False
    for part in target.split("/"):
        if part == "..":
            return True
    return False


def _matches_forbidden_pattern(
    target: str, pattern: str
) -> bool:
    """Return True if ``target`` matches a single forbidden pattern.

    Pattern forms:

    - Plain string: exact equality match.
    - String containing ``*``: ``fnmatch`` glob match.
    - String ending in ``/``: directory prefix match (``target ==
      prefix`` without trailing slash, or ``target.startswith(prefix)``).
    """
    if not isinstance(target, str) or not isinstance(pattern, str):
        return False
    if pattern.endswith("/"):
        prefix = pattern
        bare = pattern.rstrip("/")
        return target == bare or target.startswith(prefix)
    if "*" in pattern:
        return fnmatch.fnmatch(target, pattern)
    return target == pattern


def _is_forbidden_target(target: str) -> bool:
    """Return True if ``target`` matches any runtime-only or source/middle
    forbidden pattern.

    Areas-special-case: a target starting with ``areas/`` whose basename
    ends with ``.json`` is rejected unless the basename ends with
    ``_BU.json``. The carve-out exists so canonical area backups remain
    eligible for the editable_surfaces whitelist check.
    """
    if not isinstance(target, str) or not target:
        return False
    for pattern in _FORBIDDEN_RUNTIME_TARGET_PATTERNS:
        if _matches_forbidden_pattern(target, pattern):
            return True
    for pattern in _FORBIDDEN_SOURCE_MIDDLE_PATTERNS:
        if _matches_forbidden_pattern(target, pattern):
            return True
    # ``areas/*.json`` runtime carve-out. Only the ``.json``-ending
    # live files are forbidden; non-JSON entries or basename-less
    # directory references fall through to the whitelist.
    if target.startswith("areas/") or target == "areas":
        basename = target.rsplit("/", 1)[-1]
        if (
            basename.endswith(".json")
            and not basename.endswith(
                _FORBIDDEN_AREAS_BASENAME_MUST_NOT_END_WITH
            )
        ):
            return True
    return False


def _target_matches_editable_surface(target: str, surface: str) -> bool:
    """Return True if ``target`` matches a single editable_surfaces entry.

    Three match forms are supported to keep the brief's whitelist
    human-readable and flexible:

    - Exact match: ``target == surface``.
    - Directory prefix: ``surface.endswith("/")`` and
      ``target.startswith(surface)``.
    - Glob: ``fnmatch.fnmatch(target, surface)`` (covers
      ``areas/*_BU.json``, ``map_*.json``, etc.).
    """
    if not isinstance(target, str) or not isinstance(surface, str):
        return False
    if not target or not surface:
        return False
    if target == surface:
        return True
    if surface.endswith("/") and target.startswith(surface):
        return True
    if "*" in surface and fnmatch.fnmatch(target, surface):
        return True
    return False


def validate_final_reconciliation_patch_targets(
    patch_plan: Any,
    brief: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, str]]]:
    """Validate ``file_patches[].target_file`` against the brief's
    ``editable_surfaces`` whitelist.

    Pure helper: never mutates inputs, never reads or writes the
    filesystem, never calls a provider, and never raises. The function
    is fail-closed: any structural or content violation surfaces a
    structured diagnostic and ``is_valid`` is set to ``False``.

    Validation rules (in declared order):

    1. ``patch_plan`` MUST be a ``dict``. A non-dict plan is rejected
       with a single ``invalid_patch_target`` diagnostic.
    2. ``brief`` MUST be a ``dict``. A non-dict brief is rejected with
       a single ``invalid_patch_target`` diagnostic.
    3. If ``file_patches`` is not a list, the helper returns
       ``(True, [])`` so the contract helper's shape error (owned by
       Step 3.1) can be reported by its own diagnostic code without a
       confusing duplicate.
    4. If ``file_patches`` is empty, the helper returns ``(True, [])``
       WITHOUT requiring ``editable_surfaces``. This preserves the
       Step 3.1 behavior for plans that legitimately emit zero patches.
    5. If ``file_patches`` is non-empty, ``brief["editable_surfaces"]``
       MUST be a list of strings. A missing or wrong-type whitelist
       fails closed with a single ``editable_surfaces_missing``
       diagnostic.
    6. For each entry, the helper checks (in this order):
       - entry MUST be a ``dict``
       - ``target_file`` MUST be present and a string
       - the trimmed target MUST NOT be empty
       - the target MUST NOT contain a backslash
       - the target MUST NOT be an absolute path (``/x``,
         ``C:``/``C:\\x``/``C:/x``)
       - the target MUST NOT contain a ``..`` path component
       - the target MUST NOT be a runtime-only or source/middle
         forbidden pattern
       - the target MUST match at least one entry in
         ``editable_surfaces`` (exact, directory-prefix, or glob form)

    Every violation is reported in a single pass. The helper never
    short-circuits on the first violation so callers can surface every
    target issue at once.

    Args:
        patch_plan: A parsed final-reconciliation patch plan (typically
            the output of :func:`_try_parse_patch_json`).
        brief: The final reconciliation brief dict. The whitelist is
            read from ``brief.get("editable_surfaces")``.

    Returns:
        Tuple ``(is_valid, diagnostics)``. ``is_valid`` is True only
        when every rule passes. ``diagnostics`` is the list of
        structured ``{"code", "message", "severity"}`` dicts.
    """
    diagnostics: List[Dict[str, str]] = []

    if not isinstance(patch_plan, dict):
        return False, [
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_PATCH_TARGET,
                "patch plan is not a dict",
            )
        ]
    if not isinstance(brief, dict):
        return False, [
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_PATCH_TARGET,
                "brief is not a dict",
            )
        ]

    file_patches = patch_plan.get("file_patches")
    # Step 3.1 owns the file_patches LIST-shape check. When the shape is
    # wrong we return success so the contract helper can emit its own
    # ``invalid_file_patches`` diagnostic without a confusing duplicate
    # from this step.
    if not isinstance(file_patches, list):
        return True, []
    # Empty file_patches: no whitelist required (Step 3.1 behavior).
    if not file_patches:
        return True, []

    editable_surfaces = brief.get("editable_surfaces")
    if (
        not isinstance(editable_surfaces, list)
        or not editable_surfaces
        or not all(isinstance(s, str) and s for s in editable_surfaces)
    ):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING,
                "editable_surfaces is absent or not a non-empty list of "
                "strings; file_patches require an explicit whitelist",
            )
        )
        return False, diagnostics

    for index, entry in enumerate(file_patches):
        if not isinstance(entry, dict):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PATCH_TARGET,
                    f"file_patches[{index}] is not a dict",
                )
            )
            continue
        target = entry.get("target_file")
        if not isinstance(target, str):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PATCH_TARGET,
                    f"file_patches[{index}].target_file is missing or not a "
                    "string",
                )
            )
            continue
        # Local strip: do not mutate the input entry. Use the trimmed
        # value for downstream checks so a " " or "\n" target is
        # treated as empty without altering the caller's data.
        trimmed = target.strip()
        if not trimmed:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file is empty",
                )
            )
            continue
        if _has_backslash(trimmed):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file contains backslash: "
                    f"{trimmed!r}",
                )
            )
            continue
        if _is_absolute_path(trimmed):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file is an absolute path: "
                    f"{trimmed!r}",
                )
            )
            continue
        if _has_path_traversal(trimmed):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file contains path "
                    f"traversal: {trimmed!r}",
                )
            )
            continue
        if _is_forbidden_target(trimmed):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file is a forbidden target: "
                    f"{trimmed!r}",
                )
            )
            continue
        matched = False
        for surface in editable_surfaces:
            if _target_matches_editable_surface(trimmed, surface):
                matched = True
                break
        if not matched:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
                    f"file_patches[{index}].target_file is not in "
                    f"editable_surfaces: {trimmed!r}",
                )
            )
            continue

    return (len(diagnostics) == 0), diagnostics


# ---------------------------------------------------------------------------
# Step 3.3: Source-fidelity-claim validation
# ---------------------------------------------------------------------------

# Per the archived boundary contract, accepted reconciliation MUST
# not convert blocked source fidelity into a clean pass. The
# ``source_fidelity_effective_status`` in the report is fixed to
# ``reconciled_degraded`` whenever reconciliation is accepted, so
# the LLM's claimed ``source_fidelity_claim`` MUST match. This helper
# is the final-editor side of that contract: a ready plan claiming a
# clean pass is fail-closed before any patch can be applied.

# A string that names the expected accepted claim; used in the
# diagnostic message so reports can show the exact mismatched claim.
_EXPECTED_ACCEPTED_CLAIM = FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED


def _is_clean_pass_claim(value: Any) -> bool:
    """Return True if ``value`` is one of the known clean-pass claim
    variants.

    A clean-pass claim is any value that EXACTLY matches one of the
    strings in
    :data:`FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS`.
    The comparison is exact (case-sensitive) to keep the contract
    strict: ``"PASS"`` or ``"Clean_Pass"`` are NOT clean-pass claims
    and would be rejected as non-string-equal to
    ``reconciled_degraded``.

    Non-string values always return ``False`` so the missing/non-string
    diagnostic is reported by the main helper rather than this one.
    """
    if not isinstance(value, str):
        return False
    return value in FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS


def validate_final_reconciliation_source_fidelity_claim(
    patch_plan: Any,
    brief: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, str]]]:
    """Validate the LLM's ``source_fidelity_claim`` against the
    accepted-reconciliation contract.

    Pure helper: never mutates inputs, never reads or writes the
    filesystem, never calls a provider, and never raises. The helper
    is fail-closed for ``status: ready`` plans so an accepted
    reconciliation cannot claim a clean source-fidelity pass when
    the original source fidelity was blocked or degraded.

    Validation rules:

    1. ``patch_plan`` MUST be a ``dict``. A non-dict plan is
       rejected with a single ``invalid_source_fidelity_claim``
       diagnostic.
    2. ``brief`` MUST be a ``dict``. A non-dict brief is rejected
       with a single ``invalid_source_fidelity_claim`` diagnostic.
    3. When ``patch_plan`` does not have a parseable ``status``
       field (i.e. ``status`` is not one of
       ``ready`` / ``refused`` / ``failed``), the helper returns
       ``(True, [])`` so the contract helper (Step 3.1) can emit
       its own ``unsupported_status`` diagnostic without a
       confusing duplicate from this step.
    4. When ``status: ready``:
       - ``source_fidelity_claim`` MUST be present.
       - ``source_fidelity_claim`` MUST be a string.
       - ``source_fidelity_claim`` MUST equal
         ``reconciled_degraded`` EXACTLY.
       - Any value in
         :data:`FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS`
         is rejected as a false clean claim.
       - ``is_valid`` is False if any of the above fails.
    5. When ``status: refused`` or ``status: failed``:
       - The refused/failed semantics are PRESERVED. ``is_valid``
         remains True regardless of the claim value.
       - If the claim is a known clean-pass variant, a diagnostic
         is appended so downstream reports can surface the false
         claim without flipping the runner status.

    The helper never inspects the ``brief`` for source-fidelity
    fields in this step: the brief is accepted as a structural
    argument for the future-classification extension. Per the
    design, the LLM is responsible for reporting the original
    source-fidelity state via the claim, and the helper enforces
    the accepted-reconciliation invariant.

    Args:
        patch_plan: A parsed final-reconciliation patch plan.
        brief: The final reconciliation brief dict. Reserved for
            future source-fidelity cross-reference; not currently
            inspected.

    Returns:
        Tuple ``(is_valid, diagnostics)``. ``is_valid`` is True
        when the claim is acceptable for the current ``status``,
        False when a ``status: ready`` plan has a missing, wrong-
        type, or clean-pass claim. ``diagnostics`` is the list of
        structured ``{"code", "message", "severity"}`` dicts.
    """
    diagnostics: List[Dict[str, str]] = []

    if not isinstance(patch_plan, dict):
        return False, [
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                "patch plan is not a dict",
            )
        ]
    if not isinstance(brief, dict):
        return False, [
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                "brief is not a dict",
            )
        ]

    status_value = patch_plan.get("status")
    # When the top-level status is missing or unsupported, defer to
    # the contract helper (Step 3.1) which already emits the
    # ``unsupported_status`` diagnostic. Returning success here
    # avoids a confusing duplicate ``invalid_source_fidelity_claim``
    # on plans the contract helper is about to reject for an
    # unrelated reason.
    if status_value not in (
        FINAL_RECONCILIATION_PATCH_STATUS_READY,
        FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
        FINAL_RECONCILIATION_PATCH_STATUS_FAILED,
    ):
        return True, []

    # Ready plans: enforce the strict ``reconciled_degraded`` claim.
    if status_value == FINAL_RECONCILIATION_PATCH_STATUS_READY:
        if "source_fidelity_claim" not in patch_plan:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                    "ready plan missing required 'source_fidelity_claim'",
                )
            )
            return False, diagnostics
        claim_value = patch_plan.get("source_fidelity_claim")
        if not isinstance(claim_value, str):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                    f"ready plan 'source_fidelity_claim' is not a string "
                    f"(type={type(claim_value).__name__})",
                )
            )
            return False, diagnostics
        if _is_clean_pass_claim(claim_value):
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                    f"ready plan 'source_fidelity_claim' {claim_value!r} is "
                    f"a clean-pass variant; accepted reconciliation must "
                    f"claim {_EXPECTED_ACCEPTED_CLAIM!r}",
                )
            )
            return False, diagnostics
        if claim_value != _EXPECTED_ACCEPTED_CLAIM:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                    f"ready plan 'source_fidelity_claim' is "
                    f"{claim_value!r}; accepted reconciliation must claim "
                    f"{_EXPECTED_ACCEPTED_CLAIM!r}",
                )
            )
            return False, diagnostics
        # Valid ready claim.
        return True, []

    # Refused / failed plans: preserve semantics; append a diagnostic
    # when the claim is a known clean-pass variant so reports can
    # still surface the false claim without flipping the runner
    # status.
    claim_value = patch_plan.get("source_fidelity_claim")
    if _is_clean_pass_claim(claim_value):
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
                f"{status_value} plan carries clean-pass "
                f"'source_fidelity_claim' {claim_value!r}; accepted "
                f"reconciliation must claim "
                f"{_EXPECTED_ACCEPTED_CLAIM!r}",
            )
        )
    return True, diagnostics


# ---------------------------------------------------------------------------
# Step 3.4: Safe patch application
# ---------------------------------------------------------------------------
#
# Design goals (per design.md "Decision 3: Patch application is Python-gated"
# and the Step 3.4 task spec):
#
# - Python validates the entire patch plan before any module file is written.
# - All target JSON files are loaded into memory first, then all patches
#   are applied in-memory. Only after every patch has applied successfully
#   in memory does the writer phase begin.
# - The writer phase is the ONLY phase that touches the filesystem for
#   writes. Read failures during the load phase and application failures
#   during the in-memory phase both produce a ``failed`` result with zero
#   writes.
# - Inputs are never mutated. The plan, brief, and module dir are all
#   treated as read-only.
# - No partial writes from the application phase. A write-phase failure
#   on one file surfaces as ``failed`` and reports the failed file; the
#   other files may have already been written (documented as a
#   write-phase failure per the Step 3.4 task spec).

# Regex used to reject invalid JSON pointer escape sequences. Per RFC
# 6901, only ``~0`` (literal ``~``) and ``~1`` (literal ``/``) are valid.
# Any ``~`` followed by a character other than ``0`` or ``1`` is invalid.
_INVALID_JSON_POINTER_ESCAPE_RE = re.compile(r"~[^01]")


def _parse_json_path(json_path: Any) -> Optional[List[str]]:
    """Parse a JSON pointer style path into a list of segments.

    Supports the RFC 6901 subset used by the prompt: paths start with
    ``/`` and segments are separated by ``/``. The escape sequences
    ``~0`` and ``~1`` decode to ``~`` and ``/`` respectively; any other
    ``~``-escape is rejected.

    Args:
        json_path: A candidate JSON pointer string. Non-strings,
            empty strings, paths that do not start with ``/``, the
            single-character root path ``"/"``, and paths containing
            invalid escape sequences are rejected.

    Returns:
        A list of decoded path segments on success, or ``None`` on
        failure. A path with at least one segment is required so
        every op has a parent container to operate on.
    """
    if not isinstance(json_path, str):
        return None
    if len(json_path) < 2:
        return None
    if not json_path.startswith("/"):
        return None
    # The single-character root path has no segments; the op helpers
    # all need a parent container, so reject the root path here.
    if json_path == "/":
        return None
    if _INVALID_JSON_POINTER_ESCAPE_RE.search(json_path):
        return None
    raw_segments = json_path[1:].split("/")
    segments: List[str] = []
    for seg in raw_segments:
        # ``~1`` must be replaced before ``~0`` so a literal ``~01`` in
        # the path becomes ``/~1`` rather than ``~~1``.
        decoded = seg.replace("~1", "/").replace("~0", "~")
        segments.append(decoded)
    if not segments:
        return None
    return segments


def _resolve_parent(
    root: Any,
    segments: List[str],
) -> Tuple[Optional[Any], Optional[Any], List[Dict[str, str]]]:
    """Walk into ``root`` following ``segments[:-1]`` and return the parent.

    The returned ``last_segment`` is the segment the caller will use
    to address the value inside the parent. For list parents the caller
    is responsible for converting the string segment to an int.

    Args:
        root: The in-memory JSON root (dict or list, possibly ``None``).
        segments: The full JSON pointer path segments.

    Returns:
        Tuple ``(parent, last_segment, diagnostics)``. On success
        ``parent`` is the container (dict or list) and ``last_segment``
        is a string. On failure ``parent`` and ``last_segment`` are
        ``None`` and ``diagnostics`` carries a single
        ``patch_application_failed`` entry naming the failing segment.
    """
    diagnostics: List[Dict[str, str]] = []
    if not segments:
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "json_path has no segments",
            )
        )
        return None, None, diagnostics
    current: Any = root
    for index, seg in enumerate(segments[:-1]):
        if isinstance(current, dict):
            if seg not in current:
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                        f"json_path segment [{index}]={seg!r} not found in dict",
                    )
                )
                return None, None, diagnostics
            current = current[seg]
        elif isinstance(current, list):
            try:
                idx = int(seg)
            except (TypeError, ValueError):
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                        f"json_path segment [{index}]={seg!r} is not a valid array index",
                    )
                )
                return None, None, diagnostics
            if idx < 0 or idx >= len(current):
                diagnostics.append(
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                        f"json_path segment [{index}]={idx} out of array bounds (len={len(current)})",
                    )
                )
                return None, None, diagnostics
            current = current[idx]
        else:
            diagnostics.append(
                _make_diagnostic(
                    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                    f"json_path segment [{index}]={seg!r} cannot traverse non-container {type(current).__name__}",
                )
            )
            return None, None, diagnostics
    return current, segments[-1], diagnostics


def _apply_op(
    content: Any,
    op: str,
    segments: List[str],
    value: Any,
) -> List[Dict[str, str]]:
    """Dispatch a single patch op to the per-op helper.

    Returns a list of structured diagnostics. The list is empty on
    success; a non-empty list means the op failed and the caller MUST
    treat the entire patch plan as failed (no writes).
    """
    if op == FINAL_RECONCILIATION_PATCH_OP_SET_VALUE:
        return _apply_set_value_op(content, segments, value)
    if op == FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY:
        return _apply_remove_key_op(content, segments)
    if op == FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY:
        return _apply_rename_key_op(content, segments, value)
    if op == FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY:
        return _apply_remove_array_entry_op(content, segments)
    if op == FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING:
        return _apply_merge_into_existing_op(content, segments, value)
    return [
        _make_diagnostic(
            DIAGNOSTIC_CODE_INVALID_OP,
            f"unsupported op {op!r}",
        )
    ]


def _apply_set_value_op(
    content: Any,
    segments: List[str],
    value: Any,
) -> List[Dict[str, str]]:
    """Apply the ``set_value`` op to ``content`` in place.

    The parent must be a dict or a list. For dict parents the last
    segment may name an existing key (overwrite) or a new key
    (insert); the segment is always treated as a string. For list
    parents the last segment must parse as a non-negative int that is
    in bounds.
    """
    parent, last_segment, diagnostics = _resolve_parent(content, segments)
    if diagnostics:
        return diagnostics
    if isinstance(parent, dict):
        if not isinstance(last_segment, str) or not last_segment:
            return [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                    "set_value last_segment is not a non-empty string for dict parent",
                )
            ]
        parent[last_segment] = value
        return []
    if isinstance(parent, list):
        if not isinstance(last_segment, str):
            return [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                    "set_value last_segment is not a string for list parent",
                )
            ]
        try:
            idx = int(last_segment)
        except ValueError:
            return [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                    f"set_value last_segment {last_segment!r} is not a valid array index",
                )
            ]
        if idx < 0 or idx >= len(parent):
            return [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                    f"set_value index {idx} out of array bounds (len={len(parent)})",
                )
            ]
        parent[idx] = value
        return []
    return [
        _make_diagnostic(
            DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
            f"set_value parent is not a dict or list (type={type(parent).__name__})",
        )
    ]


def _apply_remove_key_op(
    content: Any,
    segments: List[str],
) -> List[Dict[str, str]]:
    """Apply the ``remove_key`` op to ``content`` in place.

    The parent MUST be a dict and the last segment MUST name an
    existing key. Otherwise the op fails closed with a structured
    diagnostic.
    """
    parent, last_segment, diagnostics = _resolve_parent(content, segments)
    if diagnostics:
        return diagnostics
    if not isinstance(parent, dict):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"remove_key parent is not a dict (type={type(parent).__name__})",
            )
        ]
    if not isinstance(last_segment, str) or not last_segment:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "remove_key last_segment is not a non-empty string",
            )
        ]
    if last_segment not in parent:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"remove_key key {last_segment!r} not found in parent dict",
            )
        ]
    del parent[last_segment]
    return []


def _apply_rename_key_op(
    content: Any,
    segments: List[str],
    value: Any,
) -> List[Dict[str, str]]:
    """Apply the ``rename_key`` op to ``content`` in place.

    The parent MUST be a dict, the last segment MUST name an existing
    key, ``value`` MUST be a non-empty string (the new key name), and
    the destination key MUST NOT already be present in the parent.
    All four conditions are enforced fail-closed.
    """
    parent, last_segment, diagnostics = _resolve_parent(content, segments)
    if diagnostics:
        return diagnostics
    if not isinstance(parent, dict):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"rename_key parent is not a dict (type={type(parent).__name__})",
            )
        ]
    if not isinstance(last_segment, str) or not last_segment:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "rename_key last_segment is not a non-empty string",
            )
        ]
    if last_segment not in parent:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"rename_key source key {last_segment!r} not found in parent dict",
            )
        ]
    if not isinstance(value, str) or not value:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "rename_key new_key is not a non-empty string",
            )
        ]
    if value in parent:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"rename_key destination key {value!r} already present in parent dict",
            )
        ]
    parent[value] = parent.pop(last_segment)
    return []


def _apply_remove_array_entry_op(
    content: Any,
    segments: List[str],
) -> List[Dict[str, str]]:
    """Apply the ``remove_array_entry`` op to ``content`` in place.

    The parent MUST be a list and the last segment MUST parse as a
    non-negative int in bounds.
    """
    parent, last_segment, diagnostics = _resolve_parent(content, segments)
    if diagnostics:
        return diagnostics
    if not isinstance(parent, list):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"remove_array_entry parent is not a list (type={type(parent).__name__})",
            )
        ]
    if not isinstance(last_segment, str):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "remove_array_entry last_segment is not a string",
            )
        ]
    try:
        idx = int(last_segment)
    except ValueError:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"remove_array_entry last_segment {last_segment!r} is not a valid array index",
            )
        ]
    if idx < 0 or idx >= len(parent):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"remove_array_entry index {idx} out of array bounds (len={len(parent)})",
            )
        ]
    del parent[idx]
    return []


def _apply_merge_into_existing_op(
    content: Any,
    segments: List[str],
    value: Any,
) -> List[Dict[str, str]]:
    """Apply the ``merge_into_existing`` op to ``content`` in place.

    The target (the value addressed by the full ``segments`` path) MUST
    be a dict and ``value`` MUST be a dict. The merge is shallow:
    ``value``'s keys are copied into the target via ``dict.update`` so
    any existing key in the target is replaced with ``value``'s
    corresponding value. When both target and value carry a dict for
    the same key, the value's dict REPLACES the target's dict rather
    than recursing; callers that need a deep merge must use
    ``set_value`` to write the merged sub-structure explicitly.
    """
    if not segments:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "merge_into_existing json_path has no segments",
            )
        ]
    if not isinstance(value, dict):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"merge_into_existing value is not a dict (type={type(value).__name__})",
            )
        ]
    # Walk the full path so we land on the target value, not its
    # parent. We re-use ``_resolve_parent`` plus one extra hop.
    parent, last_segment, diagnostics = _resolve_parent(content, segments)
    if diagnostics:
        return diagnostics
    if not isinstance(parent, dict):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"merge_into_existing parent is not a dict (type={type(parent).__name__})",
            )
        ]
    if not isinstance(last_segment, str) or not last_segment:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                "merge_into_existing last_segment is not a non-empty string",
            )
        ]
    target = parent.get(last_segment)
    if not isinstance(target, dict):
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                f"merge_into_existing target at {last_segment!r} is not a dict "
                f"(type={type(target).__name__ if not isinstance(target, dict) else 'dict'})",
            )
        ]
    # Shallow merge: ``dict.update`` overwrites existing keys with the
    # value's keys. This is the simplest and most predictable
    # contract; deep merge would require explicit policy on
    # list-typed values and recursive dict collisions.
    target.update(value)
    return []


# ---------------------------------------------------------------------------
# Step 3.5: Post-write JSON parse validation and BU/live parity helpers
# ---------------------------------------------------------------------------
#
# Canonical static authored file pairs that must stay in sync. These
# mirror the canonical vs runtime file families documented in
# ``AGENTS.md`` "Module Publication Git Contract":
#
# - ``module_context.json`` <-> ``module_context_BU.json`` (both canonical)
# - ``map_<base>.json`` <-> ``map_<base>_BU.json`` (both canonical;
#   ``map_*.json`` is static authored structure, not runtime state)
#
# The following pairs are NOT mirrored because one side is runtime-only:
#
# - ``areas/FOO.json`` (runtime, gitignored) is never written by the
#   final editor and was rejected by the Step 3.2 target validator.
# - ``module_plot.json`` (runtime, gitignored) is never written by the
#   final editor and was rejected by the Step 3.2 target validator.
# - ``party_tracker.json`` (runtime, gitignored) is never written.
# - ``player_quests_*.json`` (runtime, generated) is never written.

_PARITY_BASENAMES = frozenset({"module_context.json", "module_context_BU.json"})


def _compute_parity_counterpart(target: str) -> Optional[str]:
    """Compute the canonical parity counterpart for a given target file.

    The helper is pure, ASCII-only, and never raises. It preserves the
    caller-supplied target's directory prefix so a target like
    ``areas/module_context.json`` (hypothetical) would produce a
    counterpart of ``areas/module_context_BU.json``.

    Mirroring rules:

    - ``module_context.json`` <-> ``module_context_BU.json``
    - ``map_<base>.json`` <-> ``map_<base>_BU.json``
    - Any other target returns ``None`` (no parity rule applies).
      This deliberately excludes ``areas/FOO_BU.json`` (would map to
      runtime-only ``areas/FOO.json``) and ``module_plot_BU.json``
      (would map to runtime-only ``module_plot.json``).

    Args:
        target: Relative target path (e.g. ``module_context.json``,
            ``map_atlus.json``, ``areas/FOO_BU.json``).

    Returns:
        The relative counterpart path, or ``None`` if no parity rule
        applies.
    """
    if not isinstance(target, str) or not target:
        return None
    if "/" in target:
        dir_part, basename = target.rsplit("/", 1)
    else:
        dir_part, basename = "", target
    if basename in _PARITY_BASENAMES:
        counterpart_basename = (
            "module_context_BU.json"
            if basename == "module_context.json"
            else "module_context.json"
        )
    elif basename.startswith("map_") and basename.endswith(".json"):
        # Strip the ``.json`` extension to handle the stem. The
        # ``_BU`` marker is on the stem, not on the extension, so
        # splitting first avoids losing the extension.
        stem = basename[: -len(".json")]
        if stem.endswith("_BU"):
            counterpart_stem = stem[: -len("_BU")]
        else:
            counterpart_stem = stem + "_BU"
        counterpart_basename = counterpart_stem + ".json"
    else:
        return None
    if dir_part:
        return dir_part + "/" + counterpart_basename
    return counterpart_basename


def _should_mirror_parity_write(
    counterpart: str,
    module_dir: str,
    editable_surfaces: Any,
) -> bool:
    """Return True if the parity counterpart should be mirrored to.

    The mirror happens when one of the following holds:

    - The counterpart file already exists in the module directory
      (so the helper updates the existing canonical artifact).
    - The counterpart is explicitly listed in the brief's
      ``editable_surfaces`` (exact match, directory prefix, or glob).

    The helper is pure: it never mutates inputs, never reads or
    writes the filesystem (only ``os.path.isfile`` for the existence
    check), and never raises.

    Args:
        counterpart: Relative counterpart path produced by
            :func:`_compute_parity_counterpart`.
        module_dir: Absolute path to the module directory.
        editable_surfaces: The brief's ``editable_surfaces`` whitelist,
            or any value when the brief did not provide one.

    Returns:
        ``True`` if the counterpart should be mirrored, ``False``
        otherwise.
    """
    if not isinstance(counterpart, str) or not counterpart:
        return False
    if not isinstance(module_dir, str) or not module_dir:
        return False
    # Check 1: counterpart already exists in module directory.
    full_path = os.path.join(module_dir, counterpart)
    try:
        if os.path.isfile(full_path):
            return True
    except Exception:
        # ``os.path.isfile`` can raise on some platforms; treat as
        # "does not exist" and fall through to the whitelist check.
        pass
    # Check 2: counterpart is in editable_surfaces (exact, directory
    # prefix, or glob form, reusing the Step 3.2 helper).
    if isinstance(editable_surfaces, list):
        for surface in editable_surfaces:
            if not isinstance(surface, str) or not surface:
                continue
            if _target_matches_editable_surface(counterpart, surface):
                return True
    return False


def _validate_written_json(
    full_path: str, target: str
) -> List[Dict[str, str]]:
    """Re-open and parse a just-written JSON file to confirm it can be read.

    This is JSON parse validation only (per the Step 3.5 task spec);
    it does NOT run schema validation, readiness, or publishability
    gates. The helper is fail-closed: any non-string path, missing
    file, or non-parseable content returns a single
    ``written_json_invalid`` diagnostic naming the failing target and
    the full path the operator can inspect.

    The helper is pure: it never mutates inputs and never raises.

    Args:
        full_path: Absolute path to the just-written file.
        target: Relative target path used in the diagnostic message.

    Returns:
        An empty list on success; a list with a single
        ``written_json_invalid`` diagnostic on failure.
    """
    if not isinstance(full_path, str) or not full_path:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID,
                f"post-write validation: invalid full_path for target {target!r}",
            )
        ]
    try:
        loaded = safe_read_json(full_path)
    except Exception as exc:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID,
                (
                    f"post-write read failed for target {target!r} "
                    f"(full path: {full_path!r}): {exc}"
                ),
            )
        ]
    if loaded is None:
        return [
            _make_diagnostic(
                DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID,
                (
                    f"post-write JSON parse failed for target {target!r} "
                    f"(full path: {full_path!r})"
                ),
            )
        ]
    return []


def apply_final_reconciliation_patch_plan(
    patch_plan: Any,
    brief: Dict[str, Any],
    module_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply an accepted (status: ready) patch plan to canonical module JSON files.

    This is the Step 3.4 public helper. It runs the entire patch
    pipeline end to end: input shape checks, status check, the
    existing contract/target/source-fidelity validators, module-dir
    resolution, file loading into memory, in-memory patch application,
    and finally the atomic write phase. The helper is fail-closed at
    every boundary; any failure produces a ``failed`` result with
    diagnostics and zero writes from the application phase.

    Phase 1: Validation (no writes)
        - patch_plan MUST be a dict
        - brief MUST be a dict
        - patch_plan["status"] MUST be "ready"
        - Contract validation MUST pass
        - Target validation MUST pass
        - Source-fidelity-claim validation MUST pass

    Phase 2: Load targets into memory (no writes)
        - module_dir resolved from explicit argument or brief
        - Each unique target file loaded via safe_read_json once

    Phase 3: Apply patches in memory (no writes)
        - Patches are grouped by target_file (first-seen order)
        - For each file, patches are applied in declared order
        - Any per-op failure aborts the entire plan with zero writes

    Phase 4: Write changed files (filesystem writes)
        Step 3.4:
        - safe_write_json is called once per changed file
        - A write failure on one file surfaces as failed; earlier
          files in the write phase MAY have already been written
          (documented as write-phase failure; rollback is not
          attempted per the Step 3.4 task spec)

        Step 3.5 (post-write JSON parse validation):
        - After every successful safe_write_json, the just-written
          file is re-opened via safe_read_json to confirm it can be
          re-parsed as JSON
        - A post-write parse failure surfaces as failed with a
          ``written_json_invalid`` diagnostic
        - This is JSON parse validation only; schema validation is
          owned by Step 4.1

        Step 3.5 (BU/live parity mirror):
        - If the just-written target is one side of a canonical
          static authored pair (e.g. ``module_context.json`` <->
          ``module_context_BU.json`` or ``map_FOO.json`` <->
          ``map_FOO_BU.json``), the same post-patch content is
          mirrored to the counterpart
        - The mirror happens when the counterpart already exists in
          the module directory OR is explicitly listed in
          ``editable_surfaces`` (exact, directory-prefix, or glob
          form)
        - Runtime-only pairs (``areas/FOO_BU.json`` ->
          ``areas/FOO.json`` and ``module_plot_BU.json`` ->
          ``module_plot.json``) are NOT mirrored
        - A mirror write failure surfaces as failed with a
          ``parity_counterpart_write_failed`` diagnostic
        - The mirror is also subject to post-write JSON parse
          validation; a mirror parse failure surfaces the same
          ``written_json_invalid`` diagnostic
        - The mirror is skipped when both sides of a pair are in the
          patch plan (the second pass writes the counterpart in its
          own iteration)

    Args:
        patch_plan: A parsed final-reconciliation patch plan dict
            (typically the output of run_llm_final_editor(...)).
        brief: The final reconciliation brief dict. Used to look up
            ``editable_surfaces`` and (optionally) ``module_dir``.
        module_dir: Optional explicit module directory. When ``None``
            the helper falls back to ``brief["module_dir"]``. When
            provided, this argument takes precedence.

    Returns:
        A dict with three keys:

        - ``status``: either
          :data:`FINAL_RECONCILIATION_APPLY_STATUS_APPLIED` or
          :data:`FINAL_RECONCILIATION_APPLY_STATUS_FAILED`.
        - ``changed_files``: list of relative target paths that were
          actually written during the write phase. Always a fresh
          list (not a reference to any internal structure).
        - ``diagnostics``: list of structured
          ``{"code", "message", "severity"}`` dicts. Empty on success.
    """
    # ---- Phase 1: input shape + plan status + existing validations ----

    if not isinstance(patch_plan, dict):
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PATCH_PLAN,
                    "patch plan is not a dict",
                )
            ],
        }
    if not isinstance(brief, dict):
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PATCH_PLAN,
                    "brief is not a dict",
                )
            ],
        }
    plan_status = patch_plan.get("status")
    if plan_status != FINAL_RECONCILIATION_PATCH_STATUS_READY:
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_PATCH_PLAN,
                    f"patch plan status is not ready (status={plan_status!r})",
                )
            ],
        }

    # Reuse the existing Step 3.1 contract validator. Any shape or
    # version failure short-circuits to failed with zero writes.
    contract_valid, contract_diagnostics = (
        validate_final_reconciliation_patch_contract(patch_plan)
    )
    if not contract_valid:
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": list(contract_diagnostics),
        }

    # Reuse the Step 3.2 target validator. Empty diagnostics means
    # the target check passed (the helper returns ``(True, [])`` for
    # empty file_patches and for valid targets).
    target_valid, target_diagnostics = (
        validate_final_reconciliation_patch_targets(patch_plan, brief)
    )
    if not target_valid or target_diagnostics:
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": list(target_diagnostics),
        }

    # Reuse the Step 3.3 source-fidelity-claim validator. The
    # ``is_valid`` flag is True for refused/failed plans regardless
    # of claim, but we have already gated to ``status: ready`` above,
    # so a False here means a ready plan with a missing/clean claim.
    fidelity_valid, fidelity_diagnostics = (
        validate_final_reconciliation_source_fidelity_claim(patch_plan, brief)
    )
    if not fidelity_valid or fidelity_diagnostics:
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": list(fidelity_diagnostics),
        }

    # ---- Phase 1b: resolve module_dir ----

    effective_module_dir = module_dir
    if effective_module_dir is None:
        effective_module_dir = brief.get("module_dir")
    if not isinstance(effective_module_dir, str) or not effective_module_dir.strip():
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_MISSING_MODULE_DIR,
                    "module_dir is missing or not a non-empty string",
                )
            ],
        }
    effective_module_dir = effective_module_dir.strip()

    # ---- Phase 2: collect target files and patches (no writes) ----

    file_patches = patch_plan.get("file_patches")
    # An empty file_patches list is a valid empty patch plan; the
    # application phase produces no changes and the result is
    # ``applied`` with an empty changed_files list.
    if not isinstance(file_patches, list) or not file_patches:
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
            "changed_files": [],
            "diagnostics": [],
        }

    # Group patches by target_file, preserving first-seen order of
    # the target so writes happen in a stable, deterministic order.
    target_to_patches: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    target_order: List[str] = []
    for index, fp in enumerate(file_patches):
        if not isinstance(fp, dict):
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": [],
                "diagnostics": [
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                        f"file_patches[{index}] is not a dict",
                    )
                ],
            }
        target = fp.get("target_file")
        if not isinstance(target, str) or not target.strip():
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": [],
                "diagnostics": [
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
                        f"file_patches[{index}].target_file is missing or not a string",
                    )
                ],
            }
        target = target.strip()
        if target not in target_to_patches:
            target_to_patches[target] = []
            target_order.append(target)
        target_to_patches[target].append((index, fp))

    # ---- Phase 2b: load every target file into memory (no writes) ----

    target_contents: Dict[str, Any] = {}
    for target in target_order:
        full_path = os.path.join(effective_module_dir, target)
        loaded = safe_read_json(full_path)
        if loaded is None:
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": [],
                "diagnostics": [
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED,
                        f"failed to read target file: {target!r} (full path: {full_path!r})",
                    )
                ],
            }
        target_contents[target] = loaded

    # ---- Phase 3: apply every patch in memory (no writes) ----

    changed_targets: List[str] = []
    for target in target_order:
        content = target_contents[target]
        for index, fp in target_to_patches[target]:
            op = fp.get("op")
            json_path = fp.get("json_path")
            value = fp.get("value")

            if op not in FINAL_RECONCILIATION_ALLOWED_PATCH_OPS:
                return {
                    "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                    "changed_files": [],
                    "diagnostics": [
                        _make_diagnostic(
                            DIAGNOSTIC_CODE_INVALID_OP,
                            f"file_patches[{index}].op {op!r} is not in the allowed patch ops",
                        )
                    ],
                }
            if not isinstance(json_path, str) or not json_path:
                return {
                    "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                    "changed_files": [],
                    "diagnostics": [
                        _make_diagnostic(
                            DIAGNOSTIC_CODE_INVALID_JSON_PATH,
                            f"file_patches[{index}].json_path is missing or not a string",
                        )
                    ],
                }
            segments = _parse_json_path(json_path)
            if segments is None:
                return {
                    "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                    "changed_files": [],
                    "diagnostics": [
                        _make_diagnostic(
                            DIAGNOSTIC_CODE_INVALID_JSON_PATH,
                            f"file_patches[{index}].json_path is malformed: {json_path!r}",
                        )
                    ],
                }

            op_diagnostics = _apply_op(content, op, segments, value)
            if op_diagnostics:
                # Tag each diagnostic with the patch index, target,
                # op, and path so reports can attribute the failure
                # to a specific entry.
                decorated: List[Dict[str, str]] = []
                for diag in op_diagnostics:
                    decorated.append(
                        {
                            "code": diag["code"],
                            "message": (
                                f"file_patches[{index}] (target={target!r}, "
                                f"op={op!r}, path={json_path!r}): {diag['message']}"
                            ),
                            "severity": diag["severity"],
                        }
                    )
                return {
                    "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                    "changed_files": [],
                    "diagnostics": decorated,
                }
            if target not in changed_targets:
                changed_targets.append(target)

    # ---- Phase 4: write every changed file atomically ----
    #
    # Step 3.5 extends Phase 4 with two additional guarantees after a
    # successful ``safe_write_json``:
    #
    # 1. Post-write JSON parse validation: the just-written file is
    #    re-opened via ``safe_read_json`` to confirm the on-disk
    #    content is parseable. JSON parse failure is reported via
    #    ``DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID``. This is JSON parse
    #    validation only; schema validation is owned by Step 4.1.
    #
    # 2. BU/live parity mirror: if the just-written target is one
    #    side of a canonical static authored pair (e.g.
    #    ``module_context.json`` <-> ``module_context_BU.json`` or
    #    ``map_FOO.json`` <-> ``map_FOO_BU.json``), the same
    #    post-patch content is mirrored to the counterpart when the
    #    counterpart already exists in the module directory OR is
    #    explicitly listed in ``editable_surfaces``. The mirror
    #    itself is also subject to post-write JSON parse validation.
    #    Runtime-only pairs (``areas/FOO_BU.json`` ->
    #    ``areas/FOO.json`` and ``module_plot_BU.json`` ->
    #    ``module_plot.json``) are explicitly NOT mirrored.
    #
    # A parity mirror failure is reported via
    # ``DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED``. The mirror
    # is skipped when both sides of a pair are in the patch plan (the
    # second pass will write the counterpart in its own iteration).

    written_files: List[str] = []
    for target in changed_targets:
        full_path = os.path.join(effective_module_dir, target)
        success = safe_write_json(full_path, target_contents[target])
        if not success:
            # Write-phase failure. Earlier files in this phase may
            # have been written; we do not attempt rollback. The
            # application phase itself produced zero partial writes,
            # so the in-memory changes that were applied cannot leak
            # to disk for the failing file.
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": list(written_files),
                "diagnostics": [
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_TARGET_FILE_WRITE_FAILED,
                        f"failed to write target file: {target!r} (full path: {full_path!r})",
                    )
                ],
            }

        # Post-write JSON parse validation. The file is on disk; we
        # confirm it can be re-read as JSON before declaring the
        # write successful. The target is NOT added to
        # ``written_files`` on parse failure so the caller knows the
        # file is in an inconsistent state and should be re-driven
        # after operator inspection.
        post_write_diagnostics = _validate_written_json(full_path, target)
        if post_write_diagnostics:
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": list(written_files),
                "diagnostics": list(post_write_diagnostics),
            }
        written_files.append(target)

        # Parity mirror: write the same post-patch content to the
        # canonical parity counterpart when one exists and is not
        # already in the patch plan.
        counterpart = _compute_parity_counterpart(target)
        if counterpart is None:
            continue
        if counterpart in changed_targets:
            # Both sides are in the plan; the counterpart will be
            # written in its own iteration. Skipping here avoids
            # double-writing the same path.
            continue
        if not _should_mirror_parity_write(
            counterpart,
            effective_module_dir,
            brief.get("editable_surfaces", []),
        ):
            continue
        counterpart_full_path = os.path.join(
            effective_module_dir, counterpart
        )
        parity_success = safe_write_json(
            counterpart_full_path, target_contents[target]
        )
        if not parity_success:
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": list(written_files),
                "diagnostics": [
                    _make_diagnostic(
                        DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED,
                        (
                            f"failed to write parity counterpart: "
                            f"{counterpart!r} (full path: "
                            f"{counterpart_full_path!r})"
                        ),
                    )
                ],
            }
        # Post-write JSON parse validation on the parity mirror.
        parity_post_write = _validate_written_json(
            counterpart_full_path, counterpart
        )
        if parity_post_write:
            # The mirror file is on disk but cannot be re-read as
            # JSON. Report the diagnostic and DO NOT add the
            # counterpart to ``written_files`` for the same reason
            # as the main post-write failure above.
            return {
                "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
                "changed_files": list(written_files),
                "diagnostics": list(parity_post_write),
            }
        written_files.append(counterpart)

    return {
        "status": FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
        "changed_files": list(written_files),
        "diagnostics": [],
    }


# ---------------------------------------------------------------------------
# Step 4.1: Schema validation after patch application
# ---------------------------------------------------------------------------
#
# This step wires the canonical ``ModuleValidator`` into the final-editor
# pipeline. The contract is intentionally narrow:
#
# - ``ModuleValidator`` is invoked via the canonical
#   ``execute_full_validation(verbose=False)`` path so the helper inherits
#   every existing schema check.
# - The validator's raw ``results`` ``defaultdict`` is collapsed into a
#   compact, structured shape (status / success_rate / passed / failed /
#   errors) so reports and tests do not need to walk the full nested
#   structure.
# - The helper is fail-closed: any exception during validation surfaces
#   as ``status: "error"`` with a structured ``schema_validation_error``
#   diagnostic instead of propagating.
# - This step does NOT run readiness, publishability, or report-agreement
#   gates. Those are owned by Step 4.2.
# - This step does NOT persist any report. ``final_reconciliation_report.json``
#   persistence is owned by Step 4.4.


def _parse_validator_error_message(
    raw_message: Any,
) -> Tuple[Optional[str], str]:
    """Best-effort ``(file, message)`` extraction from a validator error.

    ``ModuleValidator`` produces error strings in several shapes depending
    on which check fired:

    - ``"<filename>: <error message>"`` (most file-type checks).
    - ``"<filename> (areas/): <error message>"`` (area files carry a
      path-info suffix).
    - ``"<filename>: room X connectivity references unknown room Y"``
      (runtime_room_reachability).
    - ``"<area_path>: <error message>"`` (path-prefixed errors).
    - A plain string with no ``:`` separator (rare; parity/spatial checks).

    The helper returns a conservative split: the substring before the
    first ``:`` is treated as the file portion (or ``None`` when no
    separator is present), and the remainder is the message. Whitespace
    is stripped on both halves. Non-string inputs are coerced to
    ``str(...)`` first so the helper never raises.

    The helper is pure and never mutates inputs.
    """
    if not isinstance(raw_message, str):
        try:
            raw_message = str(raw_message)
        except Exception:
            return None, ""
    if ":" not in raw_message:
        return None, raw_message.strip()
    file_part, _, remainder = raw_message.partition(":")
    file_part = file_part.strip()
    message = remainder.strip()
    if not file_part:
        return None, message
    return file_part, message


def collect_schema_validation_results(
    validator_results: Any,
) -> Dict[str, Any]:
    """Convert a ``ModuleValidator.results`` mapping into a compact shape.

    The ``ModuleValidator`` ``results`` attribute is a ``defaultdict`` whose
    values are dicts of the form::

        {"files": [...], "passed": N, "failed": N, "errors": [str, ...]}

    Many categories (e.g. ``"reference integrity"``, ``"connectivity"``)
    are scalars rather than file lists; the helper handles both shapes
    by summing ``passed`` / ``failed`` directly and by walking the
    ``errors`` list to extract compact ``category / file / message``
    triples.

    Output shape::

        {
            "status": "pass" | "fail",
            "success_rate": float,  # 0.0 - 1.0
            "passed": int,           # total files/checks passed
            "failed": int,           # total files/checks failed
            "errors": [
                {
                    "category": <results key>,
                    "file": <best-effort file portion> | None,
                    "message": <error message string>,
                },
                ...
            ],
        }

    Notes:
        - The helper is pure: it never mutates ``validator_results`` and
          never raises. Non-dict inputs collapse to an empty result.
        - ``success_rate`` is computed as ``passed / (passed + failed)``
          when at least one file/check was recorded; otherwise the rate
          is ``1.0`` (nothing failed) to mirror ``ModuleValidator.get_success_rate``.
        - The result is intentionally compact: it does NOT include the
          raw ``files`` lists, schema versions, or other details that
          would bloat downstream reports.

    Args:
        validator_results: The ``ModuleValidator.results`` attribute
            (typically a ``defaultdict`` but the helper accepts any
            ``dict``-like mapping).

    Returns:
        Compact dict with the shape documented above.
    """
    if not isinstance(validator_results, dict):
        return {
            "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
            "success_rate": 1.0,
            "passed": 0,
            "failed": 0,
            "errors": [],
        }

    total_passed = 0
    total_failed = 0
    compact_errors: List[Dict[str, Any]] = []

    for category, payload in validator_results.items():
        if not isinstance(payload, dict):
            # Some legacy categories may be bare scalars; skip them
            # without raising so the helper stays pure.
            continue
        try:
            total_passed += int(payload.get("passed", 0) or 0)
            total_failed += int(payload.get("failed", 0) or 0)
        except Exception:
            # Defensive: a malformed entry must not break the helper.
            continue
        raw_errors = payload.get("errors", [])
        if not isinstance(raw_errors, list):
            continue
        for raw_error in raw_errors:
            file_part, message = _parse_validator_error_message(raw_error)
            compact_errors.append(
                {
                    "category": str(category),
                    "file": file_part,
                    "message": message,
                }
            )

    total = total_passed + total_failed
    success_rate = (total_passed / total) if total > 0 else 1.0
    status = (
        FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        if total_failed == 0
        else FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL
    )
    return {
        "status": status,
        "success_rate": success_rate,
        "passed": total_passed,
        "failed": total_failed,
        "errors": compact_errors,
    }


def run_final_reconciliation_schema_validation(
    module_dir: Any,
) -> Dict[str, Any]:
    """Run canonical ``ModuleValidator`` against ``module_dir`` and
    return a compact structured result.

    The helper instantiates ``ModuleValidator(module_dir, repo_root)``
    (using the same root-anchored schema dir pattern as
    ``scripts/test_toolkit_homebrew_readiness_gate.py``) and calls
    ``execute_full_validation(verbose=False)``. The validator's raw
    ``results`` mapping is collapsed via
    :func:`collect_schema_validation_results` so the caller receives a
    compact shape that does not leak every nested file list.

    The helper is fail-closed:

    - When ``module_dir`` is missing, not a string, or not a
      non-empty path, the helper returns ``status: "error"`` with a
      ``schema_validation_error`` diagnostic and a zeroed counts shape.
    - When ``ModuleValidator`` is unavailable (defensive import path),
      the helper returns ``status: "error"`` with a
      ``schema_validation_error`` diagnostic.
    - When ``execute_full_validation`` raises, the helper catches the
      exception, emits a structured diagnostic naming the exception,
      and returns ``status: "error"`` with the partial result
      (``success_rate=0.0``, ``passed=0``, ``failed=0``,
      ``errors=[]``).

    The helper never mutates the filesystem beyond what
    ``ModuleValidator`` already does, and never raises.

    Args:
        module_dir: Absolute or repo-relative path to the module
            directory. Non-string and empty-string inputs are rejected
            with a structured diagnostic.

    Returns:
        A compact structured result. See
        :func:`collect_schema_validation_results` for the success-path
        shape. The error-path shape mirrors the success shape but
        carries ``status: "error"``, a non-empty ``diagnostics`` list,
        and the zeroed count fields.
    """
    base_error_shape: Dict[str, Any] = {
        "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        "success_rate": 0.0,
        "passed": 0,
        "failed": 0,
        "errors": [],
        "diagnostics": [],
    }

    if not isinstance(module_dir, str) or not module_dir.strip():
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
                "schema validation error: module_dir is missing or not a non-empty string",
            )
        ]
        result = dict(base_error_shape)
        result["diagnostics"] = diagnostics
        return result

    if ModuleValidator is None:
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
                "schema validation error: ModuleValidator is unavailable; "
                "the core.validation package could not be imported",
            )
        ]
        result = dict(base_error_shape)
        result["diagnostics"] = diagnostics
        return result

    try:
        validator = ModuleValidator(module_dir, str(_TOOLKIT_FINAL_RECONCILIATION_REPO_ROOT))
        validator.execute_full_validation(verbose=False)
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: schema validation raised: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
                f"schema validation error: ModuleValidator raised: {exc}",
            )
        ]
        result = dict(base_error_shape)
        result["diagnostics"] = diagnostics
        return result

    compact = collect_schema_validation_results(validator.results)
    # When the validator reports failures, the compact ``status`` is
    # "fail". Emit a structured diagnostic so the orchestrator and
    # downstream reports can key on the failure without walking the
    # ``errors`` list.
    if compact["status"] == FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL:
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
                (
                    f"schema validation failed for module_dir {module_dir!r}: "
                    f"{compact['failed']} file(s) failed; see errors for detail"
                ),
            )
        ]
    else:
        diagnostics = []
    return {
        "status": compact["status"],
        "success_rate": compact["success_rate"],
        "passed": compact["passed"],
        "failed": compact["failed"],
        "errors": list(compact["errors"]),
        "diagnostics": diagnostics,
    }


def apply_and_validate_final_reconciliation_patch_plan(
    patch_plan: Any,
    brief: Dict[str, Any],
    module_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a patch plan and run schema validation in one call.

    This is the Step 4.1 orchestration helper. The two phases are
    sequenced so callers can decide whether to read the apply result
    or the schema result independently:

    Phase 1: Apply
        - Delegates to :func:`apply_final_reconciliation_patch_plan`
          (Step 3.4 + Step 3.5 parity mirror + post-write JSON parse
          validation). The apply result is preserved verbatim in
          ``apply_result`` so callers can read ``changed_files`` and
          ``diagnostics`` without re-deriving them.

    Phase 2: Schema validation
        - Only runs when the apply phase produced
          ``status: "applied"``. When the apply phase failed (any
          non-applied status), schema validation is skipped and
          ``schema_validation`` is set to a small ``{"status":
          "not_run", "diagnostics": [...]}`` dict so callers can
          branch on the orchestrator's structure without None-checks
          per field.

    Overall status semantics:
        - ``"applied"`` when the apply phase succeeded AND the
          schema-validation phase returned ``status: "pass"``.
        - ``"failed"`` otherwise. The apply_result and
          schema_validation fields are still populated so callers
          can read whichever side failed.

    The helper does NOT attempt rollback in this step. When the
    apply phase succeeded but the schema phase failed, the writes
    from the apply phase remain on disk. Rollback is a Step 4.3
    concern.

    The helper preserves the existing
    :func:`apply_final_reconciliation_patch_plan` behavior: inputs
    are never mutated, and the same return shape is surfaced in
    ``apply_result`` so existing low-level unit tests stay green.

    Args:
        patch_plan: A parsed final-reconciliation patch plan dict.
            Forwarded verbatim to ``apply_final_reconciliation_patch_plan``.
        brief: The final reconciliation brief dict. Forwarded
            verbatim. The orchestrator does not read additional brief
            fields.
        module_dir: Optional explicit module directory. Forwarded
            verbatim to ``apply_final_reconciliation_patch_plan`` and
            also used as the target for schema validation.

    Returns:
        A dict with the following shape::

            {
                "status": "applied" | "failed",
                "apply_result": {
                    "status": "applied" | "failed",
                    "changed_files": [...],
                    "diagnostics": [...],
                },
                "schema_validation": {
                    "status": "pass" | "fail" | "error" | "not_run",
                    "success_rate": float,
                    "passed": int,
                    "failed": int,
                    "errors": [...],
                    "diagnostics": [...],
                },
                "diagnostics": [...],  # combined from both phases
            }
    """
    # ---- Phase 1: apply ----
    apply_result = apply_final_reconciliation_patch_plan(
        patch_plan, brief, module_dir=module_dir
    )

    # Snapshot the apply-phase diagnostics so we can combine them
    # with the schema-phase diagnostics at the end. The snapshot is
    # a fresh list (not a reference to the apply result's internals)
    # so subsequent edits do not mutate the apply result.
    apply_diagnostics = list(apply_result.get("diagnostics") or [])

    # ---- Phase 2: schema validation ----
    if apply_result.get("status") != FINAL_RECONCILIATION_APPLY_STATUS_APPLIED:
        # Apply did not produce changes; skip schema validation per
        # the Step 4.1 spec. Mark the schema_validation field as
        # ``not_run`` so callers can branch on the field's structure
        # without a None-check.
        schema_validation: Dict[str, Any] = {
            "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
            "success_rate": 0.0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "diagnostics": [],
        }
        overall_status = FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        return {
            "status": overall_status,
            "apply_result": apply_result,
            "schema_validation": schema_validation,
            "diagnostics": apply_diagnostics,
        }

    # Apply succeeded; resolve module_dir for the schema call. The
    # brief is not consulted here; the explicit argument and the
    # apply helper's own resolution are the source of truth.
    effective_module_dir = module_dir
    if effective_module_dir is None and isinstance(brief, dict):
        effective_module_dir = brief.get("module_dir")
    schema_validation = run_final_reconciliation_schema_validation(
        effective_module_dir
    )

    # Combine apply + schema diagnostics. The schema validation phase
    # never mutates the apply result, so the apply diagnostics list
    # can be reused as-is.
    schema_diagnostics = list(schema_validation.get("diagnostics") or [])
    combined_diagnostics = list(apply_diagnostics) + list(schema_diagnostics)

    # The overall status is "failed" whenever the schema validation
    # step produced a non-pass status (the apply phase already
    # passed).
    schema_status = schema_validation.get("status")
    if schema_status != FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS:
        overall_status = FINAL_RECONCILIATION_APPLY_STATUS_FAILED
    else:
        overall_status = FINAL_RECONCILIATION_APPLY_STATUS_APPLIED

    return {
        "status": overall_status,
        "apply_result": apply_result,
        "schema_validation": schema_validation,
        "diagnostics": combined_diagnostics,
    }


# ---------------------------------------------------------------------------
# Step 4.2: Post-accepted-reconciliation publication gates
# ---------------------------------------------------------------------------
#
# After patch application and schema validation pass, the final editor
# must re-run readiness, publishability, and report agreement. The
# three gates are run via the canonical CLI helpers and the report
# agreement composer; the helper composes their results in memory and
# returns a compact shape that downstream reports can persist or
# surface directly.
#
# The source-fidelity normalization in this step preserves the
# archived boundary's contract: accepted reconciliation records
# ``source_fidelity_effective_status: reconciled_degraded`` and must
# not turn a blocked source fidelity into a clean ``pass``. The
# effective status is passed verbatim to the report agreement
# composer so the downstream ``playable_publication_status`` field
# correctly reflects the reconciled_degraded state.
#
# Helper behavior:
#
# - Module slug is resolved from ``module_dir.name``; non-``PathLike``
#   inputs fail closed with a structured diagnostic.
# - The readiness, publishability, and report-agreement helpers may
#   each raise. The helper catches every exception in the gate
#   pipeline and surfaces a structured ``gate_helper_exception``
#   diagnostic plus an ``error`` status, so callers can branch on
#   the result without None-checks.
# - The raw reports from readiness and publishability are preserved
#   in the result so callers can inspect blocking_errors, fix_list,
#   and other downstream surfaces. The raw effective_publishable
#   status is also preserved in the ``publishability`` field for the
#   same reason; the normalization only affects the status used by
#   the report agreement composer.
# - Source-fidelity normalization: when the raw
#   ``effective_publishable_status`` is blocked/fail solely because
#   ``source_fidelity_status`` is blocked/degraded, and final
#   reconciliation is accepted, the helper normalizes the
#   effective status passed to the report agreement composer to
#   the canonical ``publishable_status``. This preserves the
#   source-fidelity honesty invariant from the archived boundary
#   (raw report keeps its source_fidelity_status; downstream
#   report can read ``source_fidelity_reconciled=True`` plus
#   ``effective_publishable_status=pass``).
# - Schema validation result, when provided, is normalized into the
#   report agreement's ``validation_status`` argument. The mapping is
#   pass -> pass, fail -> blocked, error -> blocked, not_run -> unknown,
#   missing -> unknown. The raw schema validation dict is preserved
#   in ``schema_validation`` so callers retain the structured counts
#   and error list.

# Defensive imports of the three gate helpers. Each is wrapped so the
# module can still be imported in environments where the supporting
# packages are unavailable; the helpers return ``None`` from the
# defensive-import sentinel, and the gate function checks for the
# sentinel and surfaces a structured error diagnostic. Tests always
# patch these import targets via ``unittest.mock.patch`` so the real
# implementations are never called.

try:
    from scripts.audit_module_readiness import audit_module_readiness
except Exception:  # pragma: no cover - defensive import
    audit_module_readiness = None  # type: ignore[assignment]

try:
    from scripts.audit_module_publishability import (
        audit_module_publishability,
    )
except Exception:  # pragma: no cover - defensive import
    audit_module_publishability = None  # type: ignore[assignment]

try:
    from utils.toolkit_report_agreement import compose_report_agreement
except Exception:  # pragma: no cover - defensive import
    compose_report_agreement = None  # type: ignore[assignment]


def _extract_gate_status(
    field_name: str,
    field_value: Any,
    default: str = "unknown",
) -> str:
    """Return a normalized gate status from a report field.

    The helper coerces the value to a lowercase string and falls back
    to ``default`` when the value is missing, empty, or non-string.
    The function never raises and never mutates inputs.

    Args:
        field_name: Field name (only used in log diagnostics, not
            in the returned status).
        field_value: The raw field value. May be a string, an int,
            a bool, or any value.
        default: The fallback status to return when ``field_value``
            is missing, empty, or non-string.

    Returns:
        The lowercase, stripped string value or ``default``.
    """
    del field_name  # Reserved for future diagnostic logging.
    if not isinstance(field_value, str):
        return default
    stripped = field_value.strip().lower()
    if not stripped:
        return default
    return stripped


def _normalize_schema_validation_to_validation_status(
    schema_validation: Any,
) -> str:
    """Map a ``schema_validation`` result to a report-agreement status.

    The mapping mirrors the Step 4.2 spec: ``pass`` -> ``pass``,
    ``fail`` or ``error`` -> ``blocked``, ``not_run`` -> ``unknown``,
    missing/None/non-dict -> ``unknown``.

    The helper is pure: it never mutates inputs and never raises.
    """
    if not isinstance(schema_validation, dict):
        return "unknown"
    raw_status = schema_validation.get("status")
    if not isinstance(raw_status, str):
        return "unknown"
    normalized = raw_status.strip().lower()
    if normalized == FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS:
        return "pass"
    if normalized in (
        FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
    ):
        return "blocked"
    if normalized == FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN:
        return "unknown"
    return "unknown"


def _compute_reconciled_publishable_status(
    publishability_report: Dict[str, Any],
) -> Tuple[str, bool]:
    """Decide whether the effective_publishable_status passed to the
    report agreement composer should be normalized.

    The function returns a tuple ``(effective_status, normalized)``:

    - ``normalized`` is True when the raw ``effective_publishable_status``
      is blocked/fail solely because ``source_fidelity_status`` is
      blocked/degraded, AND ``publishable_status`` is pass. In that
      case the returned ``effective_status`` is the raw
      ``publishable_status`` value, not the raw effective status.
    - Otherwise the raw effective status is returned unchanged and
      ``normalized`` is False.

    The check intentionally does NOT normalize when the raw
    ``publishable_status`` is fail. The "solely because of source
    fidelity" predicate requires the publishability gate itself
    to have passed. Otherwise, lowering the effective status to
    pass would hide a real publishability failure.

    The function never mutates inputs and never raises.
    """
    raw_effective = _extract_gate_status(
        "effective_publishable_status",
        publishability_report.get("effective_publishable_status", "unknown"),
    )
    raw_publishable = _extract_gate_status(
        "publishable_status",
        publishability_report.get("publishable_status", "unknown"),
    )
    raw_source_fidelity = _extract_gate_status(
        "source_fidelity_status",
        publishability_report.get("source_fidelity_status", "unknown"),
    )

    raw_effective_is_fail = raw_effective in {"blocked", "failed", "fail"}
    raw_publishable_is_pass = raw_publishable == "pass"
    raw_source_fidelity_is_blocked = raw_source_fidelity in {
        "blocked",
        "failed",
        "fail",
        "degraded",
    }

    if (
        raw_effective_is_fail
        and raw_publishable_is_pass
        and raw_source_fidelity_is_blocked
    ):
        return raw_publishable, True
    return raw_effective, False


def run_final_reconciliation_publication_gates(
    module_dir: Any,
    schema_validation: Optional[Dict[str, Any]] = None,
    source: str = "toolkit",
) -> Dict[str, Any]:
    """Run readiness, publishability, and report agreement after
    accepted reconciliation.

    The helper is the Step 4.2 post-accepted-reconciliation gate
    orchestrator. It runs the three gates in this fixed order:

    1. Readiness via :func:`audit_module_readiness` (uses ``source``
       to gate sidecar vs toolkit-provenance checks).
    2. Publishability via :func:`audit_module_publishability`
       (composed over readiness, semantic audit, semantic probes,
       source fidelity, and the publication gate composer).
    3. Report agreement in memory via
       :func:`compose_report_agreement` with the reconciliation
       facts pinned to the accepted-reconciliation contract.

    Args:
        module_dir: A ``Path``-like or string path to the module
            directory. The module slug is resolved from
            ``module_dir.name``. Non-``PathLike`` inputs fail closed.
        schema_validation: Optional schema-validation result from the
            Step 4.1 orchestrator (``apply_and_validate_...``). When
            provided, its ``status`` is normalized into the report
            agreement's ``validation_status`` argument. When missing,
            ``validation_status`` is set to ``unknown``.
        source: The readiness source. Passed through to both the
            readiness and publishability gates. Defaults to
            ``"toolkit"`` so the toolkit-mode sidecar / provenance
            branches are used; the legacy watcher behavior is
            reachable by passing ``"watcher"``.

    Returns:
        A compact structured result. Top-level keys::

            {
                "status": "pass" | "fail" | "error",
                "readiness": <raw readiness report dict>,
                "publishability": <raw publishability report dict>,
                "report_agreement": <compose_report_agreement output>,
                "diagnostics": [<structured diagnostics>],
                # Normalized status fields used by the report
                # agreement composer (so callers can read the same
                # values the composer saw without re-deriving them):
                "ready_status": "pass" | "fail" | "unknown",
                "publishable_status": "pass" | "fail" | "unknown",
                "effective_publishable_status": "pass" | "fail" | "unknown",
                "effective_publishable_status_normalized": bool,
                "validation_status": "pass" | "blocked" | "unknown",
                "source_fidelity_effective_status": "reconciled_degraded",
                "final_reconciliation_accepted": True,
                "final_reconciliation_status": "accepted",
            }

    The function never mutates inputs and never raises. Helper
    exceptions are caught fail-closed and surfaced as
    ``gate_helper_exception`` diagnostics.
    """
    base_error_shape: Dict[str, Any] = {
        "status": FINAL_RECONCILIATION_GATE_STATUS_ERROR,
        "readiness": {},
        "publishability": {},
        "report_agreement": {},
        "diagnostics": [],
        "ready_status": "unknown",
        "publishable_status": "unknown",
        "effective_publishable_status": "unknown",
        "effective_publishable_status_normalized": False,
        "validation_status": "unknown",
        "source_fidelity_effective_status": (
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
        ),
        "final_reconciliation_accepted": True,
        "final_reconciliation_status": (
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
        ),
    }

    if (
        not isinstance(module_dir, (str, Path))
        or (isinstance(module_dir, str) and not module_dir.strip())
    ):
        result = dict(base_error_shape)
        result["diagnostics"] = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
                "module_dir is missing or not a non-empty path",
            )
        ]
        return result

    module_path = Path(module_dir)
    module_slug = module_path.name

    # ---- Gate 1: readiness ----
    readiness_report: Dict[str, Any] = {}
    try:
        if audit_module_readiness is None:
            raise RuntimeError(
                "audit_module_readiness is unavailable; the script "
                "package could not be imported"
            )
        readiness_report = audit_module_readiness(
            module_slug, source=source
        )
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: readiness gate raised: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        result = dict(base_error_shape)
        result["diagnostics"] = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
                f"readiness gate raised: {exc}",
            )
        ]
        return result

    if not isinstance(readiness_report, dict):
        readiness_report = {}

    ready_status = _extract_gate_status(
        "overall_status",
        readiness_report.get("overall_status", "unknown"),
    )

    # ---- Gate 2: publishability ----
    publishability_report: Dict[str, Any] = {}
    try:
        if audit_module_publishability is None:
            raise RuntimeError(
                "audit_module_publishability is unavailable; the script "
                "package could not be imported"
            )
        publishability_report = audit_module_publishability(
            module_slug,
            module_path=str(module_path),
            source=source,
        )
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: publishability gate raised: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        result = dict(base_error_shape)
        result["readiness"] = dict(readiness_report)
        result["diagnostics"] = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
                f"publishability gate raised: {exc}",
            )
        ]
        return result

    if not isinstance(publishability_report, dict):
        publishability_report = {}

    publishable_status = _extract_gate_status(
        "publishable_status",
        publishability_report.get("publishable_status", "unknown"),
    )
    # Apply source-fidelity normalization on the effective status
    # before passing it to the report agreement composer.
    (
        effective_for_agreement,
        effective_was_normalized,
    ) = _compute_reconciled_publishable_status(publishability_report)
    raw_effective_status = _extract_gate_status(
        "effective_publishable_status",
        publishability_report.get(
            "effective_publishable_status", "unknown"
        ),
    )

    # ---- Gate 3: report agreement (in memory) ----
    validation_status_for_agreement = (
        _normalize_schema_validation_to_validation_status(schema_validation)
    )
    source_fidelity_status = _extract_gate_status(
        "source_fidelity_status",
        publishability_report.get("source_fidelity_status", "unknown"),
    )

    try:
        if compose_report_agreement is None:
            raise RuntimeError(
                "compose_report_agreement is unavailable; the report "
                "agreement package could not be imported"
            )
        agreement_result = compose_report_agreement(
            source_fidelity_status=source_fidelity_status,
            validation_status=validation_status_for_agreement,
            ready_status=ready_status,
            publishable_status=publishable_status,
            effective_publishable_status=effective_for_agreement,
            source_fidelity_effective_status=(
                FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
            ),
            final_reconciliation_accepted=True,
            final_reconciliation_status=(
                FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
            ),
        )
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: report agreement gate raised: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        result = dict(base_error_shape)
        result["readiness"] = dict(readiness_report)
        result["publishability"] = dict(publishability_report)
        result["diagnostics"] = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
                f"report agreement gate raised: {exc}",
            )
        ]
        return result

    if not isinstance(agreement_result, dict):
        agreement_result = {}

    # ---- Aggregate gate status and diagnostics ----
    gate_diagnostics: List[Dict[str, str]] = []
    gate_status = FINAL_RECONCILIATION_GATE_STATUS_PASS

    if ready_status != "pass":
        gate_status = FINAL_RECONCILIATION_GATE_STATUS_FAIL
        gate_diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_READINESS_FAILED,
                f"readiness gate status is {ready_status!r} (expected pass)",
            )
        )

    if publishable_status != "pass":
        gate_status = FINAL_RECONCILIATION_GATE_STATUS_FAIL
        gate_diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED,
                f"publishability gate status is {publishable_status!r} "
                "(expected pass)",
            )
        )

    agreement_status = _extract_gate_status(
        "agreement_status",
        agreement_result.get("status", "unknown"),
    )
    if agreement_status == "blocked":
        gate_status = FINAL_RECONCILIATION_GATE_STATUS_FAIL
        gate_diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED,
                "report agreement returned blocked status",
            )
        )

    return {
        "status": gate_status,
        "readiness": dict(readiness_report),
        "publishability": dict(publishability_report),
        "report_agreement": dict(agreement_result),
        "diagnostics": list(gate_diagnostics),
        "ready_status": ready_status,
        "publishable_status": publishable_status,
        "effective_publishable_status": effective_for_agreement,
        "effective_publishable_status_raw": raw_effective_status,
        "effective_publishable_status_normalized": (
            effective_was_normalized
        ),
        "validation_status": validation_status_for_agreement,
        "source_fidelity_effective_status": (
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
        ),
        "final_reconciliation_accepted": True,
        "final_reconciliation_status": (
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
        ),
    }


def apply_validate_and_gate_final_reconciliation_patch_plan(
    patch_plan: Any,
    brief: Dict[str, Any],
    module_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply, validate, and gate a final reconciliation patch plan.

    Step 4.2 orchestrator. Composes the Step 4.1
    :func:`apply_and_validate_final_reconciliation_patch_plan`
    orchestrator with the new
    :func:`run_final_reconciliation_publication_gates` helper:

    1. Calls the Step 4.1 orchestrator. The orchestrator runs the
       apply phase and, on apply success, the schema-validation
       phase.
    2. When the Step 4.1 orchestrator returns a non-``applied``
       status (apply failed OR schema validation failed), the gate
       phase is skipped and ``gates.status`` is set to
       ``not_run``. The helper does not re-run publishability,
       readiness, or report agreement on a broken apply result.
    3. When the Step 4.1 orchestrator returns ``applied``, the
       helper calls
       :func:`run_final_reconciliation_publication_gates` with
       the same ``module_dir`` argument and the schema-validation
       result carried over from Step 4.1.
    4. The overall result composes ``apply_result``,
       ``schema_validation``, and ``gates`` into a single stable
       shape, with a combined ``diagnostics`` list. The overall
       ``status`` is ``applied`` only when all three phases pass;
       otherwise it is ``failed``.

    The helper never mutates inputs and never raises. Helper
    exceptions inside the gate phase are caught by the underlying
    :func:`run_final_reconciliation_publication_gates` helper
    and surfaced as structured ``gate_helper_exception`` diagnostics
    plus a gate ``error`` status.

    Args:
        patch_plan: A parsed final-reconciliation patch plan dict.
            Forwarded verbatim to the Step 4.1 orchestrator.
        brief: The final reconciliation brief dict. Forwarded
            verbatim to the Step 4.1 orchestrator; the helper does
            not read additional brief fields.
        module_dir: Optional explicit module directory. Forwarded
            verbatim to the Step 4.1 orchestrator and used as the
            target for the gate phase. When ``None``, the brief's
            ``module_dir`` is used by the underlying helpers.

    Returns:
        A dict with the following shape::

            {
                "status": "applied" | "failed",
                "apply_result": <verbatim Step 4.1 apply_result>,
                "schema_validation": <verbatim Step 4.1 schema_validation>,
                "gates": {
                    "status": "pass" | "fail" | "error" | "not_run",
                    "readiness": <raw readiness report>,
                    "publishability": <raw publishability report>,
                    "report_agreement": <compose_report_agreement output>,
                    "diagnostics": [...],
                    "ready_status": "pass" | "fail" | "unknown",
                    "publishable_status": "pass" | "fail" | "unknown",
                    "effective_publishable_status": "pass" | "fail" | "unknown",
                    "effective_publishable_status_raw": "pass" | "fail" | "unknown",
                    "effective_publishable_status_normalized": bool,
                    "validation_status": "pass" | "blocked" | "unknown",
                    "source_fidelity_effective_status": "reconciled_degraded",
                    "final_reconciliation_accepted": True,
                    "final_reconciliation_status": "accepted",
                },
                "diagnostics": [...],  # combined from apply + schema + gates
            }

    Notes:
        - The function does NOT persist any report. ``final_reconciliation_report.json``
          persistence is owned by Step 4.4.
        - The function does NOT add a retry loop. Retry is owned by
          Step 4.3.
        - The function does NOT integrate with the packet builder or
          finisher. Integration is owned by Step 5.
    """
    # ---- Phase 1 + 2: apply and schema validation ----
    apply_validate_result = apply_and_validate_final_reconciliation_patch_plan(
        patch_plan, brief, module_dir=module_dir
    )
    apply_diagnostics = list(
        apply_validate_result.get("diagnostics") or []
    )
    schema_validation_payload = apply_validate_result.get(
        "schema_validation", {}
    )

    # ---- Phase 3: publication gates ----
    if apply_validate_result.get("status") != (
        FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
    ):
        gates_payload: Dict[str, Any] = {
            "status": FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
            "readiness": {},
            "publishability": {},
            "report_agreement": {},
            "diagnostics": [],
            "ready_status": "unknown",
            "publishable_status": "unknown",
            "effective_publishable_status": "unknown",
            "effective_publishable_status_raw": "unknown",
            "effective_publishable_status_normalized": False,
            "validation_status": "unknown",
            "source_fidelity_effective_status": (
                FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
            ),
            "final_reconciliation_accepted": True,
            "final_reconciliation_status": (
                FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
            ),
        }
        return {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "apply_result": apply_validate_result.get("apply_result", {}),
            "schema_validation": schema_validation_payload,
            "gates": gates_payload,
            "diagnostics": apply_diagnostics,
        }

    # Apply and schema both passed; run the publication gates with
    # the same effective module dir the Step 4.1 orchestrator used.
    effective_module_dir = module_dir
    if effective_module_dir is None and isinstance(brief, dict):
        effective_module_dir = brief.get("module_dir")

    gates_payload = run_final_reconciliation_publication_gates(
        effective_module_dir,
        schema_validation=schema_validation_payload,
    )
    gate_diagnostics = list(gates_payload.get("diagnostics") or [])

    # The overall status is ``applied`` only when the gate phase
    # also returns ``pass``. Any other gate status (fail or error)
    # becomes the overall ``failed``.
    overall_status = (
        FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
        if gates_payload.get("status")
        == FINAL_RECONCILIATION_GATE_STATUS_PASS
        else FINAL_RECONCILIATION_APPLY_STATUS_FAILED
    )

    combined_diagnostics = list(apply_diagnostics) + list(gate_diagnostics)
    return {
        "status": overall_status,
        "apply_result": apply_validate_result.get("apply_result", {}),
        "schema_validation": schema_validation_payload,
        "gates": gates_payload,
        "diagnostics": combined_diagnostics,
    }


# ---------------------------------------------------------------------------
# Step 4.3: Bounded-retry orchestrator constants
# ---------------------------------------------------------------------------
#
# The bounded-retry orchestrator adds at most one retry to the LLM
# Builder final editor when the post-reconciliation validation phase
# fails with repairable diagnostics. The retry budget is centralized
# as a single constant so the helper and tests can both reference it
# without drift. Per design.md "Decision 5: Retry budget is bounded"
# the system MUST allow at most one retry; infinite retries MUST NOT
# be possible.

# Hard upper bound on the number of retries (NOT including the
# initial attempt). The orchestrator therefore runs at most
# ``MAX_FINAL_RECONCILIATION_RETRIES + 1`` total attempts. Set to
# 1 to match the design contract.
MAX_FINAL_RECONCILIATION_RETRIES = 1

# Top-level orchestrator status names emitted by
# ``run_final_reconciliation_with_bounded_retry(...)``. The four
# values cover the full lifecycle:
# - "accepted": at least one attempt produced a fully-passed
#   apply/validate/gate result. ``accepted_result`` is populated.
# - "rejected": the orchestrator ran the bounded retry budget (or
#   less) and the final attempt did not produce a fully-passed
#   apply/validate/gate result. ``last_attempt_result`` is populated.
# - "not_retryable": the initial attempt failed in a class that
#   is not retryable (invalid JSON, missing required keys, forbidden
#   target, false source-fidelity claim, provider failure, refused
#   reconciliation, fatal apply failure). No retry was attempted.
# - "invalid_brief": the brief argument was not a dict. No attempt
#   was made.
FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED = "accepted"
FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED = "rejected"
FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE = "not_retryable"
FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF = "invalid_brief"


# ---------------------------------------------------------------------------
# Step 4.3: Bounded-retry orchestrator helpers
# ---------------------------------------------------------------------------


def _select_mock_provider_output_for_attempt(
    mock_provider_outputs: Any,
    attempt_index: int,
) -> Optional[Any]:
    """Pick the ``mock_provider_output`` value for one attempt.

    This is the test-only plumbing that lets
    :func:`run_final_reconciliation_with_bounded_retry` drive the
    underlying :func:`run_llm_final_editor` with a different raw
    response on each attempt without invoking the live provider.

    Supported shapes:

    - ``None`` (default): return ``None`` so the runner uses the
      live provider path.
    - ``list`` or ``tuple``: index by ``attempt_index`` and return
      that entry. If ``attempt_index`` is out of range, return the
      last entry. An empty list returns ``None`` (live provider).
    - Any other value: return it unchanged so callers can pass a
      single string and have it used for every attempt. This is the
      same shape :func:`run_llm_final_editor`'s ``mock_provider_output``
      parameter has always accepted.

    The function never mutates inputs and never raises.

    Args:
        mock_provider_outputs: The ``mock_provider_outputs`` argument
            supplied to the orchestrator.
        attempt_index: The zero-based attempt index (0 for the
            initial attempt, 1 for the retry).

    Returns:
        The value to pass as ``run_llm_final_editor(..., mock_provider_output=...)``,
        or ``None`` to use the live provider.
    """
    if mock_provider_outputs is None:
        return None
    if isinstance(mock_provider_outputs, (list, tuple)):
        if not mock_provider_outputs:
            return None
        if 0 <= attempt_index < len(mock_provider_outputs):
            return mock_provider_outputs[attempt_index]
        return mock_provider_outputs[-1]
    # Single value (str or other non-list scalar): reuse the same
    # value for every attempt. ``run_llm_final_editor`` coerces
    # non-strings via ``str(...)`` so this is safe to forward.
    return mock_provider_outputs


def _is_repairable_final_reconciliation_failure(
    apply_validate_gate_result: Any,
) -> bool:
    """Return True if the apply/validate/gate failure is repairable.

    The bounded-retry orchestrator only retries on a narrow class of
    failures per design.md "Decision 5: Retry budget is bounded" and
    the Step 4.3 task spec:

    Repairable: the apply phase produced
    :data:`FINAL_RECONCILIATION_APPLY_STATUS_APPLIED` and the
    schema-validation phase reported
    :data:`FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL` or
    :data:`FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR`.
    Schema validation is the post-apply gate that reflects the
    structure of the just-written module files, so a different
    editor attempt may produce a plan that writes compliant
    structure.

    NOT repairable: every other failure class. The orchestrator
    intentionally does NOT retry on:

    - invalid brief (caught at the orchestrator boundary)
    - provider failure, param resolution failure (LLM invocation
      itself failed; retrying with the same brief will not help)
    - invalid JSON, missing required keys, invalid patch contract
      (refused/failed/unsupported), forbidden target, false
      source-fidelity claim (the LLM's editor output was malformed;
      a fresh attempt may produce the same shape)
    - fatal apply-phase failures (input shape, missing module_dir,
      target read/write failures, parity mirror failures, op/path
      validation failures) -- a different LLM attempt may produce
      a different plan, but the spec marks these as fatal so the
      orchestrator must surface them without retrying
    - gate failures (readiness/publishability/report agreement).
      These are not LLM-editable: they reflect module-level
      structure that the final editor cannot change.

    The helper is pure: it never mutates inputs and never raises.
    Non-dict inputs return ``False`` (no retry).

    Args:
        apply_validate_gate_result: The combined apply/validate/gate
            result dict produced by the Step 4.2 orchestrator, or
            ``None`` when the runner itself failed (e.g. invalid
            JSON, refused, provider failure).

    Returns:
        ``True`` only when the failure is the schema-validation
        fail/error class described above. ``False`` otherwise.
    """
    if not isinstance(apply_validate_gate_result, dict):
        return False
    apply_result = apply_validate_gate_result.get("apply_result")
    if not isinstance(apply_result, dict):
        return False
    if apply_result.get("status") != FINAL_RECONCILIATION_APPLY_STATUS_APPLIED:
        return False
    schema_validation = apply_validate_gate_result.get("schema_validation")
    if not isinstance(schema_validation, dict):
        return False
    return schema_validation.get("status") in (
        FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
    )


def _build_final_reconciliation_retry_brief(
    brief: Dict[str, Any],
    previous_diagnostics: List[Dict[str, str]],
    attempt_index: int,
) -> Dict[str, Any]:
    """Build the retry brief for the bounded-retry orchestrator.

    The retry brief is a deep-copy of the original brief with a
    ``retry_context`` field appended. The LLM is expected to read
    the original brief fields plus the retry context and adjust its
    next patch plan to address the diagnostics listed in
    ``retry_context.previous_diagnostics``.

    The function never mutates the input brief and never raises.
    Non-dict ``brief`` inputs are returned as an empty dict so the
    orchestrator can detect the regression and fail closed; a
    missing ``attempt_index`` defaults to ``0``.

    Args:
        brief: The original (non-retry) brief dict. MUST be a dict.
        previous_diagnostics: List of structured diagnostics from
            the previous attempt. May be empty.
        attempt_index: The attempt number this retry brief is for
            (typically 1 for the first retry).

    Returns:
        A new dict containing every field of the original brief plus
        ``retry_context = {attempt_index, previous_diagnostics}``.
    """
    if not isinstance(brief, dict):
        return {}
    retry_brief = copy.deepcopy(brief)
    retry_brief["retry_context"] = {
        "attempt_index": int(attempt_index) if attempt_index is not None else 0,
        "previous_diagnostics": list(previous_diagnostics or []),
    }
    return retry_brief


def _summarize_attempt_for_orchestrator(
    attempt_index: int,
    runner_result: Dict[str, Any],
    apply_validate_gate_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compose a single attempt record for the orchestrator's
    ``attempts`` list.

    The helper is pure: it never mutates inputs and never raises.
    The summary carries everything the orchestrator needs to make
    a retry decision and to render an inspectable history.

    Args:
        attempt_index: The zero-based attempt index.
        runner_result: The dict returned by ``run_llm_final_editor``.
        apply_validate_gate_result: The dict returned by the Step
            4.2 orchestrator (``apply_validate_and_gate_...``), or
            ``None`` when the runner itself failed before the apply
            phase could be invoked.

    Returns:
        A new dict with stable keys:

        - ``attempt_index``: the index passed in
        - ``runner_status``: the runner's ``status`` string
        - ``apply_validate_gate``: the Step 4.2 result or ``None``
        - ``is_repairable``: the boolean from
          :func:`_is_repairable_final_reconciliation_failure`
        - ``diagnostics``: the combined runner + apply/validate/gate
          diagnostics list (deep-copy)
    """
    runner_diagnostics = list(
        (runner_result or {}).get("diagnostics") or []
    )
    av_diagnostics: List[Dict[str, str]] = []
    if isinstance(apply_validate_gate_result, dict):
        av_diagnostics = list(
            apply_validate_gate_result.get("diagnostics") or []
        )
    combined_diagnostics = av_diagnostics + runner_diagnostics
    return {
        "attempt_index": int(attempt_index),
        "runner_status": str(
            (runner_result or {}).get("status", "unknown")
        ),
        "apply_validate_gate": (
            dict(apply_validate_gate_result)
            if isinstance(apply_validate_gate_result, dict)
            else None
        ),
        "is_repairable": (
            _is_repairable_final_reconciliation_failure(
                apply_validate_gate_result
            )
        ),
        "diagnostics": combined_diagnostics,
    }


def run_final_reconciliation_with_bounded_retry(
    brief: Any,
    module_dir: Optional[str] = None,
    *,
    mock_provider_outputs: Optional[Any] = None,
    source: str = "toolkit",
) -> Dict[str, Any]:
    """Run the LLM Builder final editor with at most one retry.

    Step 4.3 high-level orchestrator. The helper composes
    :func:`run_llm_final_editor` (Step 2) with
    :func:`apply_validate_and_gate_final_reconciliation_patch_plan`
    (Step 4.2) and adds a bounded retry on top. The retry budget is
    :data:`MAX_FINAL_RECONCILIATION_RETRIES` (currently ``1``); the
    orchestrator therefore runs at most two total attempts (initial
    + one retry).

    The contract:

    1. When ``brief`` is not a dict, return
       :data:`FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF`
       with a structured ``invalid_brief`` diagnostic. No attempt is
       made.
    2. Attempt 0 calls :func:`run_llm_final_editor` with the
       original brief and the attempt-0 ``mock_provider_output``.
       When the runner does not return
       :data:`RUNNER_STATUS_SUCCESS`, no retry is attempted
       (runner failures are not retryable).
    3. When the runner succeeds, call
       :func:`apply_validate_and_gate_final_reconciliation_patch_plan`
       with the runner's ``patch_plan``. When the combined
       apply/validate/gate result is
       :data:`FINAL_RECONCILIATION_APPLY_STATUS_APPLIED`, return
       :data:`FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED`
       with the result pinned in ``accepted_result``.
    4. When the apply/validate/gate result is ``failed``, ask
       :func:`_is_repairable_final_reconciliation_failure` whether
       the failure is a repairable schema-validation class. When
       it is AND the retry budget has not been used, build a
       retry brief via
       :func:`_build_final_reconciliation_retry_brief` and call
       :func:`run_llm_final_editor` exactly one more time. The
       retry's outcome follows the same contract as attempt 0.
    5. The orchestrator never calls the runner more than two total
       attempts. After the second attempt completes (whether it
       accepted, failed, or was a non-retryable class), the
       orchestrator returns the appropriate terminal status.
    6. The function never mutates ``brief``. The retry brief is a
       deep-copy with a ``retry_context`` field appended.
    7. The function never persists a final report. Report
       persistence is owned by Step 4.4.
    8. The function never integrates with the packet builder or
       finisher. Integration is owned by Step 5.

    Args:
        brief: The final reconciliation brief dict. MUST be a dict
            (non-dict inputs fail closed before any attempt is made).
        module_dir: Optional explicit module directory. Forwarded
            verbatim to the apply/validate/gate helper.
        mock_provider_outputs: Test-only plumbing. When ``None``
            (default), the live provider is used. When a list or
            tuple, attempt 0 uses the first entry and the retry
            uses the second entry; if the list is shorter than
            ``attempt_index + 1``, the last entry is reused. A
            single non-list value is forwarded unchanged to every
            attempt. See
            :func:`_select_mock_provider_output_for_attempt` for the
            exact shape rules.
        source: Gate source. Passed through to
            :func:`apply_validate_and_gate_final_reconciliation_patch_plan`.

    Returns:
        A dict with the following stable shape::

            {
                "status": "accepted" | "rejected" | "not_retryable" | "invalid_brief",
                "accepted": bool,
                "retry_count": 0 | 1,
                "attempts": [
                    {
                        "attempt_index": 0 | 1,
                        "runner_status": <runner status string>,
                        "apply_validate_gate": <Step 4.2 result or None>,
                        "is_repairable": bool,
                        "diagnostics": [<combined runner + apply/validate/gate diagnostics>],
                    },
                    ...
                ],
                "accepted_result": <Step 4.2 result when accepted, else None>,
                "last_attempt_result": <Step 4.2 result from the final attempt or None>,
                "diagnostics": [<combined diagnostics from all attempts>],
                "error": <short error string when status != accepted, else None>,
            }

    Notes:
        The function NEVER mutates the input ``brief``. The retry
        brief is a deep-copy with a ``retry_context`` field added;
        the original brief is left untouched.
    """
    # ---- Boundary: non-dict brief fails closed before any attempt ----

    if not isinstance(brief, dict):
        return {
            "status": FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF,
            "accepted": False,
            "retry_count": 0,
            "attempts": [],
            "accepted_result": None,
            "last_attempt_result": None,
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_BRIEF,
                    "brief argument is not a dict",
                )
            ],
            "error": "brief_not_dict",
        }

    attempts: List[Dict[str, Any]] = []
    retry_count = 0
    accepted_result: Optional[Dict[str, Any]] = None
    # Step 4.4: capture the final successful patch plan in the
    # orchestrator's top-level result so downstream helpers (the
    # accepted-report builder) can read the LLM's decisions without
    # re-running the runner. The field is None for non-accepted
    # outcomes; callers can branch on the orchestrator's ``status``
    # to know whether to read it.
    accepted_patch_plan: Optional[Dict[str, Any]] = None
    last_attempt_result: Optional[Dict[str, Any]] = None
    final_status: str = FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED
    error_message: Optional[str] = None
    current_brief: Dict[str, Any] = brief

    for attempt_index in (0, 1):
        mock_output = _select_mock_provider_output_for_attempt(
            mock_provider_outputs, attempt_index
        )
        runner_result = run_llm_final_editor(
            current_brief, mock_provider_output=mock_output
        )

        apply_validate_gate_result: Optional[Dict[str, Any]] = None
        if runner_result.get("status") == RUNNER_STATUS_SUCCESS:
            apply_validate_gate_result = (
                apply_validate_and_gate_final_reconciliation_patch_plan(
                    runner_result.get("patch_plan") or {},
                    current_brief,
                    module_dir=module_dir,
                )
            )

        attempt_record = _summarize_attempt_for_orchestrator(
            attempt_index, runner_result, apply_validate_gate_result
        )
        attempts.append(attempt_record)

        if apply_validate_gate_result is not None:
            last_attempt_result = apply_validate_gate_result
            if apply_validate_gate_result.get(
                "status"
            ) == FINAL_RECONCILIATION_APPLY_STATUS_APPLIED:
                accepted_result = apply_validate_gate_result
                # Step 4.4: pin the final successful patch plan
                # alongside the accepted result so the report
                # builder can read its ``decisions`` list. A deep
                # copy is NOT used here; the runner already returns
                # a fresh dict it owns. We never mutate it.
                plan_value = runner_result.get("patch_plan") or {}
                if isinstance(plan_value, dict):
                    accepted_patch_plan = plan_value
                final_status = (
                    FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED
                )
                error_message = None
                break

        # Decide whether to retry. The retry budget is bounded to
        # ``MAX_FINAL_RECONCILIATION_RETRIES``; the orchestrator
        # therefore runs at most one retry. A retry is only
        # attempted when the failure is in the repairable
        # schema-validation class AND attempt_index is still below
        # the cap AND the runner itself succeeded (so the apply
        # phase actually produced a schema result to retry on).
        is_repairable = attempt_record["is_repairable"]
        if (
            is_repairable
            and attempt_index < MAX_FINAL_RECONCILIATION_RETRIES
            and apply_validate_gate_result is not None
        ):
            retry_count = 1
            # Build a fresh retry brief from the ORIGINAL brief plus
            # the previous attempt's diagnostics. The orchestrator
            # never mutates the caller's brief; the retry brief is
            # a deep-copy with a ``retry_context`` field added.
            current_brief = _build_final_reconciliation_retry_brief(
                brief,
                attempt_record["diagnostics"],
                attempt_index + 1,
            )
            # Loop continues for the retry attempt.
            continue

        # No retry: classify the terminal failure. Per the spec,
        # runner-side failures and non-repairable apply/validate/
        # gate failures are surfaced as "not_retryable" so the
        # caller can distinguish them from "retried but the
        # retry also failed". When the failure is non-repairable
        # on attempt 0 we set "not_retryable"; when the failure is
        # repairable but the budget is exhausted on attempt 1 we
        # set "rejected".
        if apply_validate_gate_result is None:
            # Runner failure: non-retryable per Step 4.3.
            final_status = (
                FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE
            )
            error_message = str(
                runner_result.get("status", "unknown")
            )
        elif attempt_index >= MAX_FINAL_RECONCILIATION_RETRIES:
            # Repairable but budget exhausted after the second
            # attempt: rejected.
            final_status = (
                FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED
            )
            error_message = "retry_budget_exhausted"
        else:
            # Non-repairable apply/validate/gate failure.
            final_status = (
                FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE
            )
            error_message = "non_repairable_failure"
        break

    # Combine diagnostics from every attempt into a single list.
    combined_diagnostics: List[Dict[str, str]] = []
    for attempt in attempts:
        combined_diagnostics.extend(attempt["diagnostics"])

    # When the terminal status is "rejected" because the budget
    # was exhausted, attach a structured budget-exhausted
    # diagnostic so downstream reports can render the boundary
    # clearly. We do NOT mutate the per-attempt diagnostic lists.
    if final_status == (
        FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED
    ) and retry_count >= MAX_FINAL_RECONCILIATION_RETRIES:
        combined_diagnostics = list(combined_diagnostics) + [
            _make_diagnostic(
                DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED,
                (
                    f"retry budget exhausted after "
                    f"{MAX_FINAL_RECONCILIATION_RETRIES + 1} attempts"
                ),
            )
        ]
    elif final_status == (
        FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE
    ):
        combined_diagnostics = list(combined_diagnostics) + [
            _make_diagnostic(
                DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE,
                (
                    "failure class is not repairable; no retry "
                    "attempted"
                ),
            )
        ]

    return {
        "status": final_status,
        "accepted": accepted_result is not None,
        "retry_count": int(retry_count),
        "attempts": list(attempts),
        "accepted_result": (
            dict(accepted_result)
            if isinstance(accepted_result, dict)
            else None
        ),
        # Step 4.4: surface the final successful patch plan so the
        # report builder can read its ``decisions`` list. ``None``
        # for non-accepted outcomes.
        "accepted_patch_plan": (
            dict(accepted_patch_plan)
            if isinstance(accepted_patch_plan, dict)
            else None
        ),
        "last_attempt_result": (
            dict(last_attempt_result)
            if isinstance(last_attempt_result, dict)
            else None
        ),
        "diagnostics": list(combined_diagnostics),
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# Step 4.4: Accepted final reconciliation report builder and persister
# ---------------------------------------------------------------------------
#
# Design goals (per design.md "Decision 4: Source fidelity remains honest"
# and the Step 4.4 task spec):
#
# - The accepted report MUST preserve source-fidelity honesty. The
#   archived boundary's contract says accepted reconciliation records
#   ``source_fidelity_effective_status: reconciled_degraded``; this
#   helper enforces that exact value.
# - The report MUST include the LLM's ``decisions`` from the final
#   successful patch plan so downstream GUI and audit reports can
#   render the editorial actions taken.
# - The report MUST include the apply-phase ``changed_files``, the
#   schema-validation outcome, the publishability outcome, and the
#   report-agreement outcome.
# - The report MUST NOT dump raw prompts, raw response text, raw
#   messages, or oversized diagnostics lists. Bounded helpers keep
#   the report compact.
# - The persist helper MUST fail closed when the orchestrator result
#   is not in the accepted state. No file is written for a
#   non-accepted result.
# - The persisted report MUST pass
#   ``utils.toolkit_final_reconciliation.is_final_reconciliation_accepted(...)``
#   so downstream boundary code and report-agreement consumers can
#   read it back without re-deriving acceptance.

# Step 4.4: stable status names for the build/persist helpers.
FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED = "accepted"
FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED = "blocked"
FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED = "not_accepted"
FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT = (
    "invalid_orchestrator_result"
)
FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN = "written"
FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED = "failed"
FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_NOT_ACCEPTED = "not_accepted"
FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_INVALID = "invalid"

# Step 4.4: diagnostic codes for build/persist failures. The
# ``not_accepted`` code lets downstream reports render a clear
# "reconciliation not yet accepted" message without leaking the
# internals of the helper that produced the report.
DIAGNOSTIC_CODE_REPORT_BUILD_FAILED = "report_build_failed"
DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED = "report_persist_failed"
DIAGNOSTIC_CODE_NOT_ACCEPTED = "not_accepted"

# Step 4.4: bounded report knobs. The accepted report is meant to be
# small enough to read and audit; these caps prevent a runaway
# decisions list or oversized diagnostic message from bloating the
# on-disk report. They are module-internal so a later step can
# adjust them without breaking tests that pin only the values that
# the design actually cares about.
FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS = 50
FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH = 200
FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS = 20

# The shared report version. We import the legacy constant from
# ``utils.toolkit_final_reconciliation`` so the report we persist
# here is byte-compatible with the version pin used by the archived
# boundary's report builder. The import is wrapped so the module
# remains importable in environments where the legacy helper is
# unavailable; tests that exercise this module always load the
# legacy helper so the sentinel is never hit in practice.
try:
    from utils.toolkit_final_reconciliation import (
        REPORT_VERSION as _LEGACY_REPORT_VERSION,
    )
except Exception:  # pragma: no cover - defensive import
    _LEGACY_REPORT_VERSION = (
        "accurate_ingest_final_reconciliation_report.v1"
    )


def _is_orchestrator_result_accepted(orchestrator_result: Any) -> bool:
    """Return True if ``orchestrator_result`` indicates accepted.

    A pure, ASCII-only helper used by the Step 4.4 report builder.
    The check is intentionally narrow: only an orchestrator result
    with ``status == "accepted"`` is considered accepted. A
    non-dict input always returns ``False``.

    The helper never mutates inputs and never raises.
    """
    if not isinstance(orchestrator_result, dict):
        return False
    return (
        orchestrator_result.get("status")
        == FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED
    )


def _extract_accepted_step42_payload(
    orchestrator_result: Any,
) -> Optional[Dict[str, Any]]:
    """Return the Step 4.2 accepted payload, or ``None``.

    The helper reads ``orchestrator_result["accepted_result"]`` and
    returns a fresh shallow copy so callers can mutate it without
    touching the orchestrator's internals. Non-dict inputs and
    missing/empty ``accepted_result`` fields return ``None``.

    The helper never mutates inputs and never raises.
    """
    if not isinstance(orchestrator_result, dict):
        return None
    accepted = orchestrator_result.get("accepted_result")
    if not isinstance(accepted, dict) or not accepted:
        return None
    return dict(accepted)


def _extract_accepted_patch_plan(
    orchestrator_result: Any,
) -> Optional[Dict[str, Any]]:
    """Return the accepted patch plan, or ``None``.

    The helper reads ``orchestrator_result["accepted_patch_plan"]``
    and returns a fresh shallow copy so callers can mutate it
    without touching the orchestrator's internals. Non-dict inputs
    and missing/empty ``accepted_patch_plan`` fields return
    ``None``.

    The helper never mutates inputs and never raises.
    """
    if not isinstance(orchestrator_result, dict):
        return None
    plan = orchestrator_result.get("accepted_patch_plan")
    if not isinstance(plan, dict) or not plan:
        return None
    return dict(plan)


def _truncate_diagnostics_for_report(
    diagnostics: Any,
) -> List[Dict[str, str]]:
    """Truncate a diagnostics list to the bounded report shape.

    The helper is pure, ASCII-only, and never raises. It enforces
    two caps from the Step 4.4 task spec:

    - At most :data:`FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS`
      items are kept.
    - Each item's ``message`` is truncated to
      :data:`FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH`
      characters with a trailing ``"..."`` marker.

    Non-dict items and items missing any of the ``code`` /
    ``message`` / ``severity`` keys are silently dropped. The
    helper never mutates inputs.

    Args:
        diagnostics: A list of structured diagnostic dicts (each
            with ``code``, ``message``, ``severity``) or any other
            value (treated as empty).

    Returns:
        A new list containing the bounded diagnostic dicts.
    """
    if not isinstance(diagnostics, list):
        return []
    bounded: List[Dict[str, str]] = []
    for entry in diagnostics:
        if len(bounded) >= FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS:
            break
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        message = entry.get("message")
        severity = entry.get("severity")
        if not isinstance(code, str) or not isinstance(message, str):
            continue
        if not isinstance(severity, str):
            severity = ""
        if (
            len(message)
            > FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH
        ):
            message = (
                message[
                    : FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH
                ]
                + "..."
            )
        bounded.append(
            {
                "code": code,
                "message": message,
                "severity": severity,
            }
        )
    return bounded


def _truncate_decisions_for_report(
    decisions: Any,
) -> List[Any]:
    """Truncate a patch-plan ``decisions`` list to the bounded report shape.

    The helper is pure, ASCII-only, and never raises. It enforces
    :data:`FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS` items.
    Items are returned as deep copies via ``dict(...)`` / ``list(...)``
    to keep the report fully decoupled from the original patch plan.

    Non-list inputs return ``[]``.
    """
    if not isinstance(decisions, list):
        return []
    bounded: List[Any] = []
    for entry in decisions:
        if len(bounded) >= FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS:
            break
        if isinstance(entry, dict):
            bounded.append(dict(entry))
        elif isinstance(entry, list):
            bounded.append(list(entry))
        else:
            bounded.append(entry)
    return bounded


def _build_accepted_report_base_shape() -> Dict[str, Any]:
    """Return the canonical base shape for a final reconciliation report.

    The shape mirrors the legacy ``build_final_reconciliation_report``
    output keys so the persisted file is compatible with the
    existing ``is_final_reconciliation_accepted`` check. The
    ``validation_after_reconciliation``,
    ``publishability_after_reconciliation``, and
    ``report_agreement_after_reconciliation`` fields use the same
    names as the legacy builder.

    The helper is pure and never mutates the caller's data.
    """
    return {
        "version": _LEGACY_REPORT_VERSION,
        "status": FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED,
        "reconciliation_status": FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED,
        "source_fidelity_effective_status": (
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
        ),
        "playable_publication_candidate": True,
        "decisions": [],
        "changed_files": [],
        "validation_after_reconciliation": {},
        "publishability_after_reconciliation": {},
        "report_agreement_after_reconciliation": {},
        "notes": [],
        "diagnostics": [],
    }


def _build_non_accepted_report_shape(
    status_value: str,
    diagnostics: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Return a non-accepted report shape for the build helper.

    The shape mirrors the legacy builder's "not accepted" output:
    ``status`` and ``reconciliation_status`` are set to
    ``status_value`` (typically ``"not_accepted"`` or
    ``"invalid_orchestrator_result"``), the source-fidelity
    effective status is ``"blocked"``, and the playable
    publication candidate is ``False``.

    The helper is pure and never mutates the caller's diagnostics.
    """
    return {
        "version": _LEGACY_REPORT_VERSION,
        "status": status_value,
        "reconciliation_status": status_value,
        "source_fidelity_effective_status": "blocked",
        "playable_publication_candidate": False,
        "decisions": [],
        "changed_files": [],
        "validation_after_reconciliation": {},
        "publishability_after_reconciliation": {},
        "report_agreement_after_reconciliation": {},
        "notes": [],
        "diagnostics": list(diagnostics),
    }


def build_accepted_final_reconciliation_report(
    orchestrator_result: Any,
    brief: Any,
) -> Dict[str, Any]:
    """Build an accepted final reconciliation report from the
    Step 4.3 orchestrator result.

    This is the Step 4.4 accepted-report builder. The helper
    consumes the bounded payload from
    :func:`run_final_reconciliation_with_bounded_retry` and emits a
    compact, source-fidelity-honest report dict that downstream
    GUI / audit / publication code can persist or render.

    Contract:

    - The helper returns a report dict whose ``status`` is one of:

      - ``"accepted"`` when ``orchestrator_result["status"]`` is
        ``"accepted"``. The returned report carries
        ``source_fidelity_effective_status="reconciled_degraded"``
        and ``playable_publication_candidate=True`` so it passes
        :func:`utils.toolkit_final_reconciliation.is_final_reconciliation_accepted`.
      - ``"not_accepted"`` when the orchestrator result is a dict
        whose ``status`` is not ``"accepted"``. The helper still
        returns a stable report shape with a single ``not_accepted``
        diagnostic; the persisted report would NOT pass
        ``is_final_reconciliation_accepted``.
      - ``"invalid_orchestrator_result"`` when the orchestrator
        result is not a dict. Same shape as ``not_accepted``
        with a single ``report_build_failed`` diagnostic.

    - The returned ``decisions`` list is a deep copy of the LLM's
      ``decisions`` from the final successful patch plan,
      truncated to
      :data:`FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS`.
    - The returned ``changed_files`` list is a copy of the
      apply-phase ``apply_result.changed_files`` for the accepted
      attempt.
    - The returned ``validation_after_reconciliation`` is a compact
      summary of the schema-validation result
      (``status`` / ``success_rate`` / ``passed`` / ``failed`` /
      ``error_count``); the raw ``errors`` list is intentionally
      excluded to keep the report compact.
    - The returned ``publishability_after_reconciliation`` carries
      the four publishability-related fields from the gates
      payload: ``publishable_status``,
      ``effective_publishable_status``,
      ``effective_publishable_status_raw``, and
      ``effective_publishable_status_normalized``.
    - The returned ``report_agreement_after_reconciliation`` carries
      ``status`` and ``playable_publication_status`` from the
      in-memory report-agreement output.
    - The returned ``notes`` and ``diagnostics`` lists are bounded
      copies of the gate-phase diagnostics (no raw prompt, no raw
      response text, no messages_used).

    The helper is pure: it NEVER mutates ``orchestrator_result`` or
    ``brief``. ``brief`` is currently reserved for future extension
    (e.g. a future step may want to fold the brief's
    ``original_refusal_reason`` into the report); the parameter is
    accepted today so the Step 5 packet builder can pass the
    original brief verbatim without a future signature change.

    Args:
        orchestrator_result: The dict returned by
            :func:`run_final_reconciliation_with_bounded_retry`. A
            non-dict input fails closed.
        brief: The original brief dict. Currently unused for
            reporting but accepted for future extension. A non-dict
            input is allowed (it is ignored) so the helper does
            not need to fail closed on a missing brief.

    Returns:
        A dict with the canonical final-reconciliation report
        shape.
    """
    del brief  # Reserved for future extension.

    if not isinstance(orchestrator_result, dict):
        diagnostics: List[Dict[str, str]] = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_BUILD_FAILED,
                "orchestrator result is not a dict",
            )
        ]
        return _build_non_accepted_report_shape(
            FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT,
            diagnostics,
        )

    if not _is_orchestrator_result_accepted(orchestrator_result):
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_NOT_ACCEPTED,
                (
                    "orchestrator result is not accepted; "
                    f"status={orchestrator_result.get('status')!r}"
                ),
            )
        ]
        return _build_non_accepted_report_shape(
            FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED,
            diagnostics,
        )

    # Accepted path. Read the two pieces of the orchestrator payload.
    accepted_step42 = _extract_accepted_step42_payload(orchestrator_result)
    accepted_patch_plan = _extract_accepted_patch_plan(orchestrator_result)

    # Start from the accepted base shape so every required key is
    # present and the source-fidelity contract is locked in.
    report = _build_accepted_report_base_shape()

    # ---- decisions (from the final successful patch plan) ----
    if accepted_patch_plan is not None:
        plan_decisions = accepted_patch_plan.get("decisions", [])
        report["decisions"] = _truncate_decisions_for_report(plan_decisions)

    # ---- changed_files (from the apply phase) ----
    if accepted_step42 is not None:
        apply_result = accepted_step42.get("apply_result", {})
        if isinstance(apply_result, dict):
            apply_changed = apply_result.get("changed_files", [])
            if isinstance(apply_changed, list):
                report["changed_files"] = list(apply_changed)

        # ---- validation_after_reconciliation (compact summary) ----
        schema_validation = accepted_step42.get("schema_validation", {})
        if isinstance(schema_validation, dict):
            errors_value = schema_validation.get("errors", [])
            error_count = (
                len(errors_value) if isinstance(errors_value, list) else 0
            )
            report["validation_after_reconciliation"] = {
                "status": schema_validation.get(
                    "status",
                    FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
                ),
                "success_rate": schema_validation.get("success_rate", 0.0),
                "passed": schema_validation.get("passed", 0),
                "failed": schema_validation.get("failed", 0),
                "error_count": error_count,
            }

        # ---- publishability_after_reconciliation ----
        # ---- report_agreement_after_reconciliation ----
        gates = accepted_step42.get("gates", {})
        if isinstance(gates, dict):
            report["publishability_after_reconciliation"] = {
                "publishable_status": gates.get(
                    "publishable_status", "unknown"
                ),
                "effective_publishable_status": gates.get(
                    "effective_publishable_status", "unknown"
                ),
                "effective_publishable_status_raw": gates.get(
                    "effective_publishable_status_raw", "unknown"
                ),
                "effective_publishable_status_normalized": bool(
                    gates.get("effective_publishable_status_normalized", False)
                ),
            }
            agreement_value = gates.get("report_agreement", {})
            if isinstance(agreement_value, dict):
                report["report_agreement_after_reconciliation"] = {
                    "status": agreement_value.get("status", "unknown"),
                    "playable_publication_status": agreement_value.get(
                        "playable_publication_status", "unknown"
                    ),
                }
            # ---- notes / diagnostics (bounded gate diagnostics) ----
            gate_diagnostics = gates.get("diagnostics", [])
            bounded_diagnostics = _truncate_diagnostics_for_report(
                gate_diagnostics
            )
            report["notes"] = list(bounded_diagnostics)
            report["diagnostics"] = list(bounded_diagnostics)

    return report


def build_blocked_final_reconciliation_report(
    orchestrator_result: Any,
    brief: Any,
) -> Dict[str, Any]:
    """Build a non-playable blocked final reconciliation report.

    This Step 4.5 helper makes failed or blocked reconciliation explicit
    without claiming playable publication. Accepted orchestrator results
    are delegated to :func:`build_accepted_final_reconciliation_report` so
    callers can use this as a unified outcome-report builder when desired.

    Non-accepted reports deliberately keep
    ``source_fidelity_effective_status`` as ``"blocked"`` rather than
    ``"reconciled_degraded"``. The latter is only valid once final
    reconciliation is accepted.
    """
    if _is_orchestrator_result_accepted(orchestrator_result):
        return build_accepted_final_reconciliation_report(
            orchestrator_result, brief
        )

    diagnostics: List[Dict[str, str]] = []
    validation_after: Dict[str, Any] = {}
    publishability_after: Dict[str, Any] = {}
    report_agreement_after: Dict[str, Any] = {}

    if isinstance(orchestrator_result, dict):
        diagnostics.extend(
            _truncate_diagnostics_for_report(
                orchestrator_result.get("diagnostics", [])
            )
        )
        attempts = orchestrator_result.get("attempts", [])
        if isinstance(attempts, list):
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                diagnostics.extend(
                    _truncate_diagnostics_for_report(
                        attempt.get("diagnostics", [])
                    )
                )
        last_attempt = orchestrator_result.get("last_attempt_result", {})
        if isinstance(last_attempt, dict):
            schema_validation = last_attempt.get("schema_validation", {})
            if isinstance(schema_validation, dict):
                validation_after = {
                    "status": schema_validation.get("status", "unknown"),
                    "success_rate": schema_validation.get("success_rate", 0.0),
                    "passed": schema_validation.get("passed", 0),
                    "failed": schema_validation.get("failed", 0),
                }
            gates = last_attempt.get("gates", {})
            if isinstance(gates, dict):
                publishability_after = {
                    "publishable_status": gates.get(
                        "publishable_status", "unknown"
                    ),
                    "effective_publishable_status": gates.get(
                        "effective_publishable_status", "unknown"
                    ),
                }
                agreement = gates.get("report_agreement", {})
                if isinstance(agreement, dict):
                    report_agreement_after = {
                        "status": agreement.get("status", "unknown"),
                        "playable_publication_status": agreement.get(
                            "playable_publication_status", "unknown"
                        ),
                    }
    else:
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_BUILD_FAILED,
                "orchestrator result is not a dict",
            )
        )

    if not diagnostics:
        status_value = (
            orchestrator_result.get("status", "unknown")
            if isinstance(orchestrator_result, dict)
            else "unknown"
        )
        diagnostics.append(
            _make_diagnostic(
                DIAGNOSTIC_CODE_NOT_ACCEPTED,
                f"final reconciliation not accepted; status={status_value!r}",
            )
        )

    diagnostics = _truncate_diagnostics_for_report(diagnostics)
    return {
        "version": _LEGACY_REPORT_VERSION,
        "status": FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED,
        "reconciliation_status": FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED,
        "source_fidelity_effective_status": "blocked",
        "playable_publication_candidate": False,
        "decisions": [],
        "changed_files": [],
        "validation_after_reconciliation": validation_after,
        "publishability_after_reconciliation": publishability_after,
        "report_agreement_after_reconciliation": report_agreement_after,
        "notes": list(diagnostics),
        "diagnostics": list(diagnostics),
    }


def persist_accepted_final_reconciliation_report(
    module_dir: Any,
    orchestrator_result: Any,
    brief: Any,
) -> Dict[str, Any]:
    """Build and persist an accepted final reconciliation report.

    The Step 4.4 persister. The helper composes
    :func:`build_accepted_final_reconciliation_report` with the
    existing provider-free
    :func:`utils.toolkit_final_reconciliation.persist_final_reconciliation_report`
    helper so the on-disk artifact is byte-compatible with the
    archived boundary's report contract.

    Contract:

    - The helper returns a dict with the stable shape::

        {
            "status": "written" | "failed" | "not_accepted" | "invalid_orchestrator_result",
            "path": <absolute path to the persisted file or None>,
            "report": <built report dict or None>,
            "error": <short error string or None>,
            "diagnostics": [list of structured diagnostics],
            "bytes": <bytes written or 0>,
        }

    - When ``orchestrator_result`` is not in the accepted state, the
      helper returns a structured failure WITHOUT writing a file.
      This is the "fail closed and write nothing" contract from the
      Step 4.4 task spec.
    - When the build helper returns an accepted report but the
      existing persistence helper returns a non-``"written"``
      status (e.g. due to a disk error or the ``module_dir``
      becoming invalid between the build and the persist), the
      persister returns ``"failed"`` with the underlying error
      surfaced via ``error`` and a structured ``report_persist_failed``
      diagnostic.
    - When the build helper returns an accepted report and the
      persistence helper returns ``"written"``, the persister
      returns ``"written"`` with ``path``, ``bytes``, and the
      built ``report``.

    The helper never mutates ``orchestrator_result`` or ``brief``.
    It never raises.

    Args:
        module_dir: A ``Path``-like or string path to the module
            directory. Non-``str`` / non-``PathLike`` inputs and
            empty values fail closed with a structured diagnostic.
        orchestrator_result: The dict returned by
            :func:`run_final_reconciliation_with_bounded_retry`. A
            non-dict input fails closed.
        brief: The original brief dict. Currently unused for
            persistence but accepted for future extension. A
            non-dict input is allowed (ignored).

    Returns:
        A dict with the stable shape documented above.
    """
    # ``brief`` is intentionally forwarded to the build helper so
    # Step 5 can extend the report to fold brief context. A prior
    # ``del brief`` left the local name unbound before the inner
    # call (UnboundLocalError) which crashed every persist call;
    # the parameter is therefore preserved and explicitly ignored
    # by the build helper for now.

    report = build_accepted_final_reconciliation_report(
        orchestrator_result, brief
    )

    if report.get("status") != FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED:
        return {
            "status": str(report.get("status") or "unknown"),
            "path": None,
            "report": report,
            "error": None,
            "diagnostics": list(report.get("diagnostics") or []),
            "bytes": 0,
        }

    # Validate module_dir. Reuse the same shape the Step 4.2 helper
    # uses for the publication-gate module_dir guard so the failure
    # path is consistent across helpers.
    if (
        not isinstance(module_dir, (str, Path))
        or (isinstance(module_dir, str) and not module_dir.strip())
    ):
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED,
                "module_dir is missing or not a non-empty path",
            )
        ]
        return {
            "status": FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
            "path": None,
            "report": report,
            "error": "module_dir is missing or not a non-empty path",
            "diagnostics": diagnostics,
            "bytes": 0,
        }

    # Persist via the existing provider-free helper. The helper
    # itself is fail-closed and returns a structured dict; we
    # convert exceptions into a structured failure so the caller
    # never has to catch.
    try:
        from utils.toolkit_final_reconciliation import (
            persist_final_reconciliation_report as _persist_helper,
        )
    except Exception as exc:  # pragma: no cover - defensive import
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED,
                (
                    "persist_final_reconciliation_report is unavailable; "
                    f"the toolkit_final_reconciliation package could not "
                    f"be imported: {exc}"
                ),
            )
        ]
        return {
            "status": FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
            "path": None,
            "report": report,
            "error": (
                "persist_final_reconciliation_report unavailable: "
                f"{exc}"
            ),
            "diagnostics": diagnostics,
            "bytes": 0,
        }

    try:
        result = _persist_helper(Path(module_dir), report)
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: persist raised: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED,
                f"persist_final_reconciliation_report raised: {exc}",
            )
        ]
        return {
            "status": FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
            "path": None,
            "report": report,
            "error": f"persist_final_reconciliation_report raised: {exc}",
            "diagnostics": diagnostics,
            "bytes": 0,
        }

    if not isinstance(result, dict) or result.get("status") != (
        FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN
    ):
        underlying_error = (
            result.get("error") if isinstance(result, dict) else None
        )
        underlying_status = (
            result.get("status") if isinstance(result, dict) else None
        )
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED,
                (
                    "persist_final_reconciliation_report returned "
                    f"status={underlying_status!r}: {underlying_error!r}"
                ),
            )
        ]
        return {
            "status": FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
            "path": (
                result.get("path") if isinstance(result, dict) else None
            ),
            "report": report,
            "error": underlying_error or "persist helper did not write",
            "diagnostics": diagnostics,
            "bytes": (
                int(result.get("bytes", 0) or 0)
                if isinstance(result, dict)
                else 0
            ),
        }

    return {
        "status": FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        "path": result.get("path"),
        "report": report,
        "error": None,
        "diagnostics": [],
        "bytes": int(result.get("bytes", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Final editor runner
# ---------------------------------------------------------------------------

def _apply_target_validation_to_runner_status(
    parser_status: str,
    parser_diagnostics: List[Dict[str, str]],
    patch_plan: Dict[str, Any],
    brief: Dict[str, Any],
) -> Tuple[str, List[Dict[str, str]]]:
    """Step 3.2 helper: run target validation and fold the result into
    the runner's status/diagnostics.

    The helper preserves the Step 3.1 status semantics for
    ``refused`` and ``failed`` editor plans (their original status is
    preserved) while escalating a successful ``ready`` plan to
    ``RUNNER_STATUS_INVALID_PATCH_CONTRACT`` when target validation
    fails. All target diagnostics are appended to the existing
    ``parser_diagnostics`` list regardless of branch so downstream
    reports can surface every issue at once.

    Earlier failure statuses (invalid_json / missing_required_keys /
    invalid_brief / provider_failed / param_resolution_failed) do not
    have a usable patch plan, so target validation is skipped and the
    inputs are returned unchanged.

    The helper is pure: it does not mutate ``patch_plan`` or ``brief``.

    Returns:
        Tuple ``(status, diagnostics)``.
    """
    if parser_status not in (
        RUNNER_STATUS_SUCCESS,
        RUNNER_STATUS_REFUSED_RECONCILIATION,
        RUNNER_STATUS_FAILED_RECONCILIATION,
    ):
        return parser_status, list(parser_diagnostics)

    targets_valid, target_diagnostics = (
        validate_final_reconciliation_patch_targets(patch_plan, brief)
    )
    if not target_diagnostics:
        return parser_status, list(parser_diagnostics)

    new_diagnostics = list(parser_diagnostics) + list(target_diagnostics)
    if parser_status == RUNNER_STATUS_SUCCESS:
        return RUNNER_STATUS_INVALID_PATCH_CONTRACT, new_diagnostics
    # ``refused`` and ``failed`` editor plans preserve their original
    # status; the target diagnostics ride along so the report can
    # still list them.
    return parser_status, new_diagnostics


def _apply_source_fidelity_claim_validation_to_runner_status(
    parser_status: str,
    parser_diagnostics: List[Dict[str, str]],
    patch_plan: Dict[str, Any],
    brief: Dict[str, Any],
) -> Tuple[str, List[Dict[str, str]]]:
    """Step 3.3 helper: run source-fidelity-claim validation and fold
    the result into the runner's status/diagnostics.

    The helper preserves the Step 3.1 status semantics for
    ``refused`` and ``failed`` editor plans (their original status
    is preserved) while escalating a successful ``ready`` plan to
    ``RUNNER_STATUS_INVALID_PATCH_CONTRACT`` when the
    source-fidelity claim violates the accepted-reconciliation
    contract. The choice to reuse ``invalid_patch_contract`` is
    documented in the design and tests; downstream reports key on
    the diagnostic code (``invalid_source_fidelity_claim``) rather
    than the runner status, so the aggregation is intentionally
    consistent with Steps 3.1 and 3.2.

    Earlier failure statuses (invalid_json / missing_required_keys /
    invalid_brief / provider_failed / param_resolution_failed) do
    not have a usable patch plan, so source-fidelity validation is
    skipped and the inputs are returned unchanged. The same skip
    applies to target-validation outcomes from Step 3.2: a plan
    that already escalated to ``invalid_patch_contract`` carries
    the contract/target diagnostics; running source-fidelity on
    top would only add noise without changing the status.

    The helper is pure: it does not mutate ``patch_plan`` or
    ``brief``.

    Returns:
        Tuple ``(status, diagnostics)``.
    """
    if parser_status not in (
        RUNNER_STATUS_SUCCESS,
        RUNNER_STATUS_REFUSED_RECONCILIATION,
        RUNNER_STATUS_FAILED_RECONCILIATION,
    ):
        return parser_status, list(parser_diagnostics)

    fidelity_valid, fidelity_diagnostics = (
        validate_final_reconciliation_source_fidelity_claim(patch_plan, brief)
    )
    if not fidelity_diagnostics:
        return parser_status, list(parser_diagnostics)

    new_diagnostics = list(parser_diagnostics) + list(fidelity_diagnostics)
    if parser_status == RUNNER_STATUS_SUCCESS and not fidelity_valid:
        # Ready plan with a false / missing / wrong-type claim
        # escalates to invalid_patch_contract so the runner's
        # status reflects a contract-level failure.
        return RUNNER_STATUS_INVALID_PATCH_CONTRACT, new_diagnostics
    # Refused / failed plans keep their original status; the
    # fidelity diagnostic rides along so reports can surface the
    # false clean claim without flipping the runner status.
    return parser_status, new_diagnostics


def _build_error_message_for_status(
    status: str,
    diagnostics: List[Dict[str, str]],
) -> Optional[str]:
    """Map a runner status to a short human-readable ``error`` string.

    The ``error`` field stays short and ASCII-only so logs and
    pre-existing tests that grep the field keep working. The richer,
    structured ``diagnostics`` list carries the full per-key detail.

    Returns ``None`` for ``RUNNER_STATUS_SUCCESS`` so the runner
    result has a uniform ``error: None`` shape on success.
    """
    if status == RUNNER_STATUS_SUCCESS:
        return None
    if status == RUNNER_STATUS_INVALID_BRIEF:
        # Preserve the existing exact string used in Step 2.2-2.3
        # tests so we do not need to broaden any of them.
        return "brief_not_dict"
    if status == RUNNER_STATUS_INVALID_JSON:
        return "invalid_json"
    if status == RUNNER_STATUS_MISSING_REQUIRED_KEYS:
        missing = [
            d.get("message", "")
            for d in diagnostics
            if d.get("code") == DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS
        ]
        if missing:
            return "missing_required_keys: " + "; ".join(missing)
        return "missing_required_keys"
    if status == RUNNER_STATUS_REFUSED_RECONCILIATION:
        return "refused_reconciliation"
    if status == RUNNER_STATUS_FAILED_RECONCILIATION:
        return "failed_reconciliation"
    if status == RUNNER_STATUS_INVALID_PATCH_CONTRACT:
        # Step 3.1: aggregate the contract-validation diagnostic
        # messages so the legacy ``error`` field carries the same
        # information as the structured ``diagnostics`` list, in a
        # short ASCII-only form.
        contract_messages = [
            d.get("message", "")
            for d in diagnostics
        ]
        if contract_messages:
            return "invalid_patch_contract: " + "; ".join(contract_messages)
        return "invalid_patch_contract"
    if status == RUNNER_STATUS_PROVIDER_FAILED:
        return "provider_failed"
    if status == RUNNER_STATUS_PARAM_RESOLUTION_FAILED:
        return "param_resolution_failed"
    # Generic fallback: do not invent a custom error string here;
    # the structured diagnostic list is the source of truth.
    return status


def run_llm_final_editor(
    brief: Dict[str, Any],
    *,
    temperature_override: Optional[float] = None,
    timeout_seconds: int = FINAL_RECONCILIATION_DEFAULT_TIMEOUT_SECONDS,
    mock_provider_output: Optional[str] = None,
) -> Dict[str, Any]:
    """Final-editor runner that consumes a final reconciliation brief.

    Creates a chat client using ``create_chat_client()`` and resolves
    flat Chat Completions kwargs using ``get_chat_completion_params(...)``
    for the ``toolkit_final_reconciliation`` task id. Sends the
    system+user message pair built from the brief and returns a
    structured result with the raw response text, model metadata, and
    a status string.

    When ``mock_provider_output`` is provided (not ``None``), the
    runner short-circuits the live provider path:

    - The brief is still validated as a dict.
    - Messages are still built so prompt/brief plumbing can be
      inspected in tests.
    - ``create_chat_client()`` and
      ``client.chat.completions.create(...)`` are NOT called.
    - ``get_chat_completion_params(...)`` is NOT called.
    - The injected ``mock_provider_output`` string is run through the
      same fail-closed JSON parser and diagnostics helper used on
      live-provider responses, so tests can drive both happy and
      failure paths without touching the network.

    This runner does NOT:

    - mutate the input brief (helpers are read-only by construction)
    - write files
    - call the packet builder or finisher
    - validate the patch plan beyond top-level shape and required
      keys (decision-type allowlists, file-patch target validation,
      and source-fidelity-claim validation are owned by Section 3)
    - apply any patches

    Those concerns are owned by later steps (Section 3 patch contract,
    Section 4 validation loop, Section 5 packet builder integration).

    Args:
        brief: Final reconciliation brief dict. Must be a dict.
        temperature_override: Optional temperature override passed to
            ``get_chat_completion_params(...)``. Ignored when
            ``mock_provider_output`` is provided.
        timeout_seconds: OpenAI client timeout in seconds. Defaults to
            120 to match the existing toolkit LLM callers. Ignored
            when ``mock_provider_output`` is provided.
        mock_provider_output: Optional injected raw response text.
            When not ``None``, the runner returns a result driven by
            this string instead of calling the live provider.
            Non-string values are coerced via ``str(...)``.

    Returns:
        Structured result dict with at minimum:

        - ``status``: one of ``success``, ``provider_failed``,
          ``param_resolution_failed``, ``invalid_brief``,
          ``invalid_json``, ``missing_required_keys``,
          ``refused_reconciliation``, ``failed_reconciliation``
        - ``raw_response_text``: model output text (may be empty for
          non-mock failure paths; equal to the injected output under
          the mock path)
        - ``model``: model name (resolved or from response), or
          ``"mock_provider"`` under the mock path
        - ``messages_used``: the chat messages list sent to the model
        - ``params_used``: the flat Chat Completions kwargs, or the
          mock marker dict under the mock path
        - ``patch_plan``: parsed JSON object when parse succeeded
          (including ``refused`` and ``failed`` editor status), or
          ``{}`` when parse failed
        - ``diagnostics``: list of structured error/warning dicts
          (each with ``code``, ``message``, ``severity``). Always
          present; empty on success.
        - ``error``: short ASCII error string when ``status`` is not
          ``success``, otherwise ``None``
    """
    if not isinstance(brief, dict):
        return {
            "status": RUNNER_STATUS_INVALID_BRIEF,
            "raw_response_text": "",
            "model": "",
            "messages_used": [],
            "params_used": {},
            "patch_plan": {},
            "diagnostics": [
                _make_diagnostic(
                    DIAGNOSTIC_CODE_INVALID_BRIEF,
                    "brief argument is not a dict",
                )
            ],
            "error": "brief_not_dict",
        }

    # Build messages. The brief is passed by reference; the helpers in
    # this module are read-only and do not mutate it.
    messages = _build_chat_messages(brief)

    # Mock provider short-circuit. The brief has already been
    # validated as a dict above. Live provider and param-resolution
    # calls are intentionally skipped so tests can verify the
    # prompt/brief plumbing without a live network call. The injected
    # raw output is still run through the fail-closed parser so the
    # mock path has the same shape as the live-provider path.
    if mock_provider_output is not None:
        raw_text = (
            mock_provider_output
            if isinstance(mock_provider_output, str)
            else str(mock_provider_output)
        )
        patch_plan, parser_status, parser_diagnostics = _parse_runner_response(
            raw_text
        )
        # Step 3.2: run target validation only when the parse produced
        # a usable plan (success / refused / failed). Earlier failure
        # statuses (invalid_json / missing_required_keys) do not have
        # a patch plan to validate, so this step is skipped.
        parser_status, parser_diagnostics = _apply_target_validation_to_runner_status(
            parser_status, parser_diagnostics, patch_plan, brief
        )
        # Step 3.3: run source-fidelity-claim validation only when the
        # parse produced a usable plan. Same skip semantics as Step 3.2.
        parser_status, parser_diagnostics = (
            _apply_source_fidelity_claim_validation_to_runner_status(
                parser_status, parser_diagnostics, patch_plan, brief
            )
        )
        return {
            "status": parser_status,
            "raw_response_text": raw_text,
            "model": RUNNER_MOCK_MODEL,
            "messages_used": messages,
            "params_used": dict(RUNNER_MOCK_PARAMS_MARKER),
            "patch_plan": patch_plan,
            "diagnostics": parser_diagnostics,
            "error": _build_error_message_for_status(
                parser_status, parser_diagnostics
            ),
        }

    # Resolve flat Chat Completions kwargs for the final-editor task.
    try:
        params = get_chat_completion_params(
            FINAL_RECONCILIATION_TASK_ID,
            DM_MAIN_MODEL,
            temperature_override=temperature_override,
        )
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: chat param resolution failed: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
                f"param resolution raised: {exc}",
            )
        ]
        return {
            "status": RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
            "raw_response_text": "",
            "model": "",
            "messages_used": messages,
            "params_used": {},
            "patch_plan": {},
            "diagnostics": diagnostics,
            "error": f"param_resolution_failed: {exc}",
        }

    # Call provider
    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            messages=messages,
            timeout=timeout_seconds,
            **params,
        )
    except Exception as exc:
        warning(
            "TOOLKIT_FINAL_RECONCILIATION: provider call failed: "
            f"{exc}",
            category="toolkit_final_reconciliation",
        )
        diagnostics = [
            _make_diagnostic(
                DIAGNOSTIC_CODE_PROVIDER_FAILED,
                f"provider call raised: {exc}",
            )
        ]
        return {
            "status": RUNNER_STATUS_PROVIDER_FAILED,
            "raw_response_text": "",
            "model": params.get("model", ""),
            "messages_used": messages,
            "params_used": params,
            "patch_plan": {},
            "diagnostics": diagnostics,
            "error": f"provider_failed: {exc}",
        }

    raw_text = _extract_response_text(response)
    model_used = _extract_response_model(response, params.get("model", ""))

    # Step 2.4: fail-closed parse + structured diagnostics.
    patch_plan, parser_status, parser_diagnostics = _parse_runner_response(
        raw_text
    )

    # Step 3.2: target validation against editable_surfaces (when the
    # parse produced a usable plan).
    parser_status, parser_diagnostics = _apply_target_validation_to_runner_status(
        parser_status, parser_diagnostics, patch_plan, brief
    )

    # Step 3.3: source-fidelity-claim validation (when the parse
    # produced a usable plan). Same skip semantics as Step 3.2.
    parser_status, parser_diagnostics = (
        _apply_source_fidelity_claim_validation_to_runner_status(
            parser_status, parser_diagnostics, patch_plan, brief
        )
    )

    return {
        "status": parser_status,
        "raw_response_text": raw_text,
        "model": model_used,
        "messages_used": messages,
        "params_used": params,
        "patch_plan": patch_plan,
        "diagnostics": parser_diagnostics,
        "error": _build_error_message_for_status(
            parser_status, parser_diagnostics
        ),
    }
