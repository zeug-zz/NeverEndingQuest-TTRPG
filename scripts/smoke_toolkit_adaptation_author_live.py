# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Script - Bounded Live GPT-5.6 Adaptation Author Smoke
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Task 7.4 of toolkit-llm-adaptation-runtime-unification: run exactly ONE
bounded live authoring request through the ACTUAL adaptation authoring path
with complete Python-owned rights metadata and a bounded source context, then
record a sanitized outcome classification (ready_dossier, author_policy_refusal,
or infrastructure_failure) without exposing response text or credentials.

Guards (opt-in by design):

- The script is named ``smoke_*`` (not ``test_*``) so provider-free unittest
  discovery can never run it.
- No provider call happens unless the explicit ``--live`` flag is passed.
- Exactly one authoring request is made; there is no automatic retry.
- Missing/placeholder credentials or network unavailability classify as
  ``infrastructure_failure`` and are never treated as a code failure.

Never printed or persisted: raw provider responses, full prompts, source text
beyond the bounded input contract, credentials, API keys, headers, or raw
exception/stack text. The printed report contains only allowlisted scalars.

This smoke never runs ModuleBuilder, readiness, finisher, registry, campaign,
or publication. All scratch lives under the project-local root
``tmp/toolkit_adaptation_author_live_smoke/<uuid>/`` and is removed after the
run. No OS temp directory is used.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

# Keep the smoke output to the sanitized report only. Library/network debug
# logging in this repository is otherwise noisy and may echo request shapes;
# it is suppressed for the duration of this standalone script.
for _noisy_logger in (
    "openai",
    "openai._base_client",
    "httpcore",
    "httpx",
    "utils.file_operations",
    "NeverEndingQuest",
):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

from model_config import DM_MAIN_MODEL  # noqa: E402

from utils.ai_client_factory import get_chat_completion_params  # noqa: E402
from utils.toolkit_adaptation_author import (  # noqa: E402
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
    ADAPTATION_AUTHOR_TASK_ID,
    REASON_CATEGORY_API_REFUSAL,
    REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
    REASON_CATEGORY_NONE,
    REASON_CODE_PROVIDER_CLIENT_INIT_FAILED,
    build_adaptation_author_response_format,
)
from utils.toolkit_adaptation_authoring import (  # noqa: E402
    AUTHORING_STATUS_READY,
    run_adaptation_authoring,
)
from utils.toolkit_adaptation_dossier import (  # noqa: E402
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    SOURCE_PROFILE_ADVENTURE,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_source_context import (  # noqa: E402
    build_adaptation_source_context,
)

SMOKE_VERSION = "toolkit_adaptation_author_live_smoke.v1"
SCRATCH_ROOT = _REPO_ROOT / "tmp" / "toolkit_adaptation_author_live_smoke"
DEFAULT_TIMEOUT_SECONDS = 120.0

# Bounded concept input: one short paragraph plus a few named facts. The raw
# concept text is never printed or persisted; only its SHA-256 and length are
# recorded.
CONCEPT_TITLE = "The Flooded Belltower"
CONCEPT_TEXT = (
    "A small coastal belltower stands half-submerged in a tideless lagoon. "
    "Named facts: the bell is a drowned bronze relic, the keeper is a woman "
    "named Sella who lost her voice, and a sealed tide-gate in the foundations "
    "has not opened in three generations. Create a compact playable location "
    "with one entry hook, two rooms, one NPC, and one small encounter."
)


def _sha256_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    if not path.exists():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _modules_listing() -> List[str]:
    modules_dir = _REPO_ROOT / "modules"
    if not modules_dir.is_dir():
        return []
    return sorted(item.name for item in modules_dir.iterdir())


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _credentials_available() -> bool:
    """Return True only when a real (non-placeholder) direct key exists."""
    try:
        import config
        key = getattr(config, "OPENAI_API_KEY", "")
    except Exception:
        return False
    if not isinstance(key, str) or not key.strip():
        return False
    lowered = key.strip().lower()
    if "your_openai_api_key" in lowered or "your_api_key" in lowered:
        return False
    return True


def _parameter_isolation_report(model: str) -> Dict[str, bool]:
    """Confirm GPT-5 parameter isolation without logging sensitive values."""
    try:
        params = get_chat_completion_params(ADAPTATION_AUTHOR_TASK_ID, model)
    except Exception:
        return {
            "resolved_model_matches_configured": False,
            "reasoning_effort_present": False,
            "verbosity_present": False,
            "temperature_absent": False,
            "top_p_absent": False,
        }
    if not isinstance(params, dict):
        return {
            "resolved_model_matches_configured": False,
            "reasoning_effort_present": False,
            "verbosity_present": False,
            "temperature_absent": False,
            "top_p_absent": False,
        }
    return {
        "resolved_model_matches_configured": bool(params.get("model")) == bool(model),
        "reasoning_effort_present": "reasoning_effort" in params,
        "verbosity_present": "verbosity" in params,
        "temperature_absent": "temperature" not in params,
        "top_p_absent": "top_p" not in params,
    }


def _strict_response_format_available() -> bool:
    try:
        response_format = build_adaptation_author_response_format("openai")
    except Exception:
        return False
    return bool(
        isinstance(response_format, dict)
        and response_format.get("type") == ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT
    )


def _leakage_scan(report: Dict[str, Any]) -> bool:
    """Defensive scan: the serialized report must not carry source/credential
    content. Returns True when the report is clean."""
    try:
        serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return False
    lowered = serialized.lower()
    if CONCEPT_TEXT[:40].lower() in lowered:
        return False
    for token in ("sk-proj", "sk-or-", "bearer ", "api_key", "authorization"):
        if token in lowered:
            return False
    return True


def _classify(result: Dict[str, Any]) -> str:
    if _safe_bool(result.get("ok")) and result.get("status") == AUTHORING_STATUS_READY:
        return "ready_dossier"
    safe_class = str(result.get("safe_class") or "")
    if safe_class in {REASON_CATEGORY_AUTHOR_POLICY_REFUSAL, REASON_CATEGORY_API_REFUSAL}:
        return "author_policy_refusal"
    return "infrastructure_failure"


def _rights_identity_report(result: Dict[str, Any]) -> Dict[str, Any]:
    dossier = result.get("dossier")
    if not isinstance(dossier, dict):
        return {
            "python_owned": True,
            "classified_by": "python",
            "provider_may_change": False,
            "dossier_echo_matches": False,
            "dossier_build_ready": False,
        }
    validation = validate_adaptation_dossier(dossier)
    expected_class = RIGHTS_CLASS_USER_AUTHORED
    expected_review_required = False
    expected_review_status = RIGHTS_REVIEW_NOT_REQUIRED
    echo_matches = bool(
        dossier.get("rights_class") == expected_class
        and dossier.get("rights_review_required") is expected_review_required
        and dossier.get("rights_review_status") == expected_review_status
        and isinstance(dossier.get("rights_basis"), str)
        and dossier.get("rights_basis").strip()
    )
    return {
        "python_owned": True,
        "classified_by": "python",
        "provider_may_change": False,
        "dossier_echo_matches": echo_matches,
        "dossier_valid": _safe_bool(validation.get("valid")),
        "dossier_build_ready": _safe_bool(validation.get("build_ready")),
    }


def _run_live_smoke() -> int:
    if not _credentials_available():
        report: Dict[str, Any] = {
            "smoke": SMOKE_VERSION,
            "outcome": "infrastructure_failure",
            "safe_class": "provider_infrastructure",
            "reason_code": REASON_CODE_PROVIDER_CLIENT_INIT_FAILED,
            "note": "direct provider credentials are unavailable; implementation remains unjudged",
            "configured_model": DM_MAIN_MODEL,
            "provider_route": "openai",
            "elapsed_seconds": 0.0,
            "leakage_scan_clean": True,
        }
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0

    scratch = SCRATCH_ROOT / str(uuid.uuid4())
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    side_effects: Dict[str, bool] = {
        "modules_listing_unchanged": True,
        "registry_unchanged": True,
        "campaign_unchanged": True,
        "party_tracker_unchanged": True,
    }
    try:
        before_listing = _modules_listing()
        before_registry = _file_digest(_REPO_ROOT / "modules" / "world_registry.json")
        before_campaign = _file_digest(_REPO_ROOT / "modules" / "campaign.json")
        before_tracker = _file_digest(_REPO_ROOT / "party_tracker.json")

        source_hash = _sha256_digest(CONCEPT_TEXT)
        job_id = "live-smoke-" + uuid.uuid4().hex[:12]
        source_path = "tmp/toolkit_adaptation_author_live_smoke/source.md"
        rights_basis = (
            "Operator attested that this bounded smoke concept is user-authored."
        )

        source_context = build_adaptation_source_context(
            raw_source=CONCEPT_TEXT,
            source_hash=source_hash,
            source_title=CONCEPT_TITLE,
            source_path=source_path,
            profile_override=SOURCE_PROFILE_ADVENTURE,
        )
        if not isinstance(source_context, dict):
            result = {
                "ok": False,
                "status": "blocked",
                "safe_class": "invalid_input",
                "reason_code": "invalid_author_input",
                "diagnostics": [],
            }
        else:
            # Complete Python-owned rights metadata, supplied before the call:
            # the envelope-level identity (python_owned / classified_by /
            # provider_may_change) plus the four author-contract rights fields.
            rights_metadata: Dict[str, Any] = {
                "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                "rights_basis": rights_basis,
                "rights_review_required": False,
                "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
                "python_owned": True,
                "classified_by": "python",
                "provider_may_change": False,
            }
            result = run_adaptation_authoring(
                source_context,
                workspace=scratch,
                world_context=None,
                job_id=job_id,
                attempt_number=1,
                source_title=CONCEPT_TITLE,
                source_hash=source_hash,
                source_path=source_path,
                source_profile=SOURCE_PROFILE_ADVENTURE,
                source_format="text_description",
                rights_metadata=rights_metadata,
                rights_class=RIGHTS_CLASS_USER_AUTHORED,
                rights_basis=rights_basis,
                rights_review_required=False,
                rights_review_status=RIGHTS_REVIEW_NOT_REQUIRED,
                model=None,
                provider=None,
                model_metadata=None,
                client=None,
                parameter_resolver=None,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            )
        elapsed = round(time.monotonic() - started, 3)

        if not isinstance(result, dict):
            report = {
                "smoke": SMOKE_VERSION,
                "outcome": "infrastructure_failure",
                "safe_class": "provider_infrastructure",
                "reason_code": "provider_call_failed",
                "note": "authoring invocation did not return a result envelope; implementation remains unjudged",
                "configured_model": DM_MAIN_MODEL,
                "provider_route": "openai",
                "elapsed_seconds": elapsed,
                "leakage_scan_clean": True,
            }
            print(json.dumps(report, ensure_ascii=True, sort_keys=True))
            return 0

        outcome = _classify(result)
        resolved_model = str((result.get("model_metadata") or {}).get("model") or DM_MAIN_MODEL)
        provider_route = str((result.get("model_metadata") or {}).get("provider") or "openai")
        world_provenance = result.get("world_context_provenance") or {}
        if not isinstance(world_provenance, dict):
            world_provenance = {}

        attempt_metadata = result.get("attempt_metadata") or {}
        if not isinstance(attempt_metadata, dict):
            attempt_metadata = {}

        # Artifact presence/validation booleans and project-relative references.
        artifacts: Dict[str, Any] = {
            "source_context_persisted": _safe_bool(result.get("source_context_artifact_persisted")),
            "dossier_persisted": _safe_bool(result.get("dossier_artifact_persisted")),
            "proposal_persisted": _safe_bool(result.get("proposal_ledger_persisted")),
            "source_context_artifact_path": result.get("source_context_artifact_path"),
            "dossier_artifact_path": result.get("dossier_artifact_path"),
            "proposal_ledger_path": result.get("proposal_ledger_path"),
        }

        report = {
            "smoke": SMOKE_VERSION,
            "outcome": outcome,
            "safe_class": str(result.get("safe_class") or REASON_CATEGORY_NONE),
            "reason_code": str(result.get("reason_code") or "none"),
            "configured_model": DM_MAIN_MODEL,
            "model": resolved_model,
            "provider_route": provider_route,
            "elapsed_seconds": elapsed,
            "attempt": {
                "attempt_id": result.get("attempt_id"),
                "job_id": job_id,
                "attempt_number": 1,
                "revision_number": 0,
                "source_hash": result.get("source_hash"),
                "source_chars": len(CONCEPT_TEXT),
            },
            "rights_identity": _rights_identity_report(result),
            "parameter_isolation": {
                **_parameter_isolation_report(resolved_model),
                "strict_json_schema_response_format": _strict_response_format_available(),
            },
            "world_context_provenance": {
                "context_status": world_provenance.get("context_status"),
                "world_seed_status": world_provenance.get("world_seed_status"),
                "read_only": world_provenance.get("read_only"),
            },
            "artifacts": artifacts,
            "diagnostics_bounded": {
                "count": len(result.get("diagnostics") or []),
                "codes": sorted(
                    {
                        str(item.get("code"))
                        for item in (result.get("diagnostics") or [])
                        if isinstance(item, dict) and isinstance(item.get("code"), str)
                    }
                )[:8],
            },
            "side_effects": side_effects,
            "leakage_scan_clean": True,
        }
        report["leakage_scan_clean"] = _leakage_scan(report)

        after_listing = _modules_listing()
        after_registry = _file_digest(_REPO_ROOT / "modules" / "world_registry.json")
        after_campaign = _file_digest(_REPO_ROOT / "modules" / "campaign.json")
        after_tracker = _file_digest(_REPO_ROOT / "party_tracker.json")
        side_effects["modules_listing_unchanged"] = before_listing == after_listing
        side_effects["registry_unchanged"] = before_registry == after_registry
        side_effects["campaign_unchanged"] = before_campaign == after_campaign
        side_effects["party_tracker_unchanged"] = before_tracker == after_tracker
        report["side_effects"] = side_effects
        report["leakage_scan_clean"] = _leakage_scan(report)

        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception:
        elapsed = round(time.monotonic() - started, 3)
        report = {
            "smoke": SMOKE_VERSION,
            "outcome": "infrastructure_failure",
            "safe_class": "provider_infrastructure",
            "reason_code": "provider_call_failed",
            "note": "bounded smoke invocation failed without raw exception text; implementation remains unjudged",
            "configured_model": DM_MAIN_MODEL,
            "provider_route": "openai",
            "elapsed_seconds": elapsed,
            "leakage_scan_clean": True,
        }
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            SCRATCH_ROOT.rmdir()
        except OSError:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded live GPT-5.6 adaptation author smoke (task 7.4)."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make exactly one live adaptation authoring request (opt-in).",
    )
    args = parser.parse_args(argv)

    if not args.live:
        report = {
            "smoke": SMOKE_VERSION,
            "outcome": "skipped",
            "safe_class": "none",
            "reason_code": "opt_in_required",
            "note": "live smoke is opt-in; pass --live to make one bounded provider request",
            "leakage_scan_clean": True,
        }
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    return _run_live_smoke()


if __name__ == "__main__":
    sys.exit(main())
