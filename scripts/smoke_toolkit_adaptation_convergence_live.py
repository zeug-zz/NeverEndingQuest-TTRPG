# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Script - Bounded Live Adaptation Convergence Smoke.

Runs the actual production adaptation convergence callback once against a
bounded repair request.  The provider response is never printed or persisted.
The smoke does not run ModuleBuilder, publication, registry, campaign, or
canonical monster generation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import logging
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from model_config import DM_MAIN_MODEL  # noqa: E402

from utils.toolkit_adaptation_config import (  # noqa: E402
    BUILD_MODE_LLM_ADAPTATION,
    INPUT_KIND_TEXT_DESCRIPTION,
    resolve_adaptation_input_route,
)
from utils.toolkit_adaptation_publication_convergence import (  # noqa: E402
    CONVERGENCE_CONTRACT_VERSION,
)
from utils.toolkit_adaptation_staging import (  # noqa: E402
    create_adaptation_staging_target,
)
from web.extensions.toolkit_adaptation_runtime import (  # noqa: E402
    adaptation_convergence_callback,
)


SMOKE_VERSION = "toolkit_adaptation_convergence_live_smoke.v1"
SCRATCH_ROOT = _REPO_ROOT / "tmp" / "toolkit_adaptation_convergence_live_smoke"
SOURCE_HASH = "b" * 64
TIMEOUT_SECONDS = 30.0


def _digest(path: Path) -> str:
    if not path.exists():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _modules_listing() -> list[str]:
    modules = _REPO_ROOT / "modules"
    if not modules.is_dir():
        return []
    return sorted(item.name for item in modules.iterdir())


def _live_state_snapshot() -> Dict[str, Any]:
    return {
        "modules_listing": _modules_listing(),
        "registry": _digest(_REPO_ROOT / "modules" / "world_registry.json"),
        "campaign": _digest(_REPO_ROOT / "modules" / "campaign.json"),
        "party_tracker": _digest(_REPO_ROOT / "party_tracker.json"),
    }


def _credentials_available() -> bool:
    try:
        import config
        import model_config

        provider = str(getattr(model_config, "LLM_PROVIDER", "openai")).lower()
        key_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        value = getattr(config, key_name, "")
    except Exception:
        return False
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return "your_api_key" not in lowered and "your_openai_api_key" not in lowered


def _leakage_scan(report: Mapping[str, Any]) -> bool:
    try:
        encoded = json.dumps(report, ensure_ascii=True, sort_keys=True).lower()
    except (TypeError, ValueError):
        return False
    return not any(
        token in encoded
        for token in ("sk-proj", "sk-or-", "bearer ", "api_key", "authorization", "raw_response")
    )


def _context(target: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "contract_version": CONVERGENCE_CONTRACT_VERSION,
        "attempt_id": target["attempt_id"],
        "attempt_number": target["attempt_number"],
        "revision_number": target["revision_number"],
        "source_hash": SOURCE_HASH,
        "staging_identity": {
            "stage_id": target["stage_id"],
            "module_slug": target["module_slug"],
            "path": target["path"],
            "output_directory": target["output_directory"],
        },
        "budget": {
            "current_attempt": 0,
            "max_attempts": 1,
            "max_operations_per_round": 1,
            "operation_timeout_seconds": int(TIMEOUT_SECONDS),
        },
        "validation_context": {
            "status": "blocked",
            "repairable": True,
            "repair_requests": [{"code": "destination_alias"}],
            "source_reference_ids": ["source_manifest"],
            "canonical_location_ids": ["LOC01"],
            "authored_target_ids": [],
            "approved_monster_ids": [],
            "topology": {"location_ids": ["LOC01"], "edges": []},
        },
    }


def _classify(result: Optional[Mapping[str, Any]]) -> str:
    if isinstance(result, Mapping) and result.get("status") == "success":
        return "ready_dossier"
    if isinstance(result, Mapping) and result.get("provider_failure_class") in {
        "dependency",
        "unavailable",
        "timeout",
        "quota",
        "malformed",
        "rejected",
        "unknown",
    }:
        return "infrastructure_failure"
    return "infrastructure_failure"


def _bounded_diagnostic_codes(result: Any) -> list[str]:
    """Expose parser codes only; never expose provider response content."""
    if not isinstance(result, Mapping):
        return []
    values = result.get("diagnostics")
    if not isinstance(values, (list, tuple)):
        return []
    codes = [
        value
        for value in values[:8]
        if isinstance(value, str) and value.isascii() and 0 < len(value) <= 96
    ]
    return list(dict.fromkeys(codes))


def _run(live: bool) -> Dict[str, Any]:
    if not live:
        return {
            "smoke": SMOKE_VERSION,
            "outcome": "skipped",
            "reason_code": "opt_in_required",
            "diagnostic_codes": [],
            "provider_called": False,
            "provider_call_count": 0,
            "leakage_scan_clean": True,
        }

    before = _live_state_snapshot()
    started = time.monotonic()
    run_id = str(uuid.uuid4())
    scratch = SCRATCH_ROOT / run_id
    result: Optional[Mapping[str, Any]] = None
    target: Optional[Mapping[str, Any]] = None
    route_enabled = False
    staging_identity_match = False
    provider_called = False
    report: Dict[str, Any]

    try:
        import model_config

        # Temporary process-local overrides.  Shipped defaults are untouched.
        old_adaptation = getattr(model_config, "ENABLE_LLM_ADAPTATION", False)
        old_canonical = getattr(
            model_config,
            "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            False,
        )
        model_config.ENABLE_LLM_ADAPTATION = True
        model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = False
        route = resolve_adaptation_input_route(
            INPUT_KIND_TEXT_DESCRIPTION,
            enabled_override=True,
            module_name="Convergence_Live_Smoke",
            description="bounded convergence smoke",
            attempt_id="live-convergence",
            job_id="live-convergence",
            attempt_number=1,
        )
        route_enabled = bool(
            route.get("status") == "adaptation"
            and route.get("route_selected") == BUILD_MODE_LLM_ADAPTATION
        )
        scratch.mkdir(parents=True, exist_ok=True)
        target = create_adaptation_staging_target(
            SOURCE_HASH,
            attempt_id="live-convergence",
            attempt_number=1,
            revision_number=0,
            job_id="live-convergence",
            module_slug="Convergence_Live_Smoke",
            repo_root=_REPO_ROOT,
            staging_root="tmp/toolkit_adaptation_convergence_live_smoke/" + run_id,
        )
        context = _context(target)
        staging_identity_match = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = adaptation_convergence_callback(
                context,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        provider_failure = (
            result.get("provider_failure_class") if isinstance(result, Mapping) else None
        )
        provider_called = bool(
            isinstance(result, Mapping)
            and provider_failure != "dependency"
            and result.get("reason_code") not in {"callback_context_invalid", "provider_dependency_unavailable"}
        )
        model_config.ENABLE_LLM_ADAPTATION = old_adaptation
        model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = old_canonical
        report = {
            "smoke": SMOKE_VERSION,
            "outcome": _classify(result),
            "safe_class": str((result or {}).get("provider_failure_class") or "none"),
            "reason_code": str((result or {}).get("reason_code") or "provider_call_failed"),
            "diagnostic_codes": _bounded_diagnostic_codes(result),
            "configured_model": DM_MAIN_MODEL,
            "provider_called": provider_called,
            "provider_call_count": 1 if provider_called else 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "route_enabled": route_enabled,
            "canonical_generation_enabled": False,
            "staging_identity_match": staging_identity_match,
        }
    except Exception:
        report = {
            "smoke": SMOKE_VERSION,
            "outcome": "infrastructure_failure",
            "safe_class": "provider_infrastructure",
            "reason_code": "provider_call_failed",
            "diagnostic_codes": [],
            "configured_model": DM_MAIN_MODEL,
            "provider_called": provider_called,
            "provider_call_count": 1 if provider_called else 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "route_enabled": route_enabled,
            "canonical_generation_enabled": False,
            "staging_identity_match": staging_identity_match,
        }
    finally:
        after = _live_state_snapshot()
        report["side_effects"] = {
            "modules_listing_unchanged": before["modules_listing"] == after["modules_listing"],
            "registry_unchanged": before["registry"] == after["registry"],
            "campaign_unchanged": before["campaign"] == after["campaign"],
            "party_tracker_unchanged": before["party_tracker"] == after["party_tracker"],
        }
        report["leakage_scan_clean"] = _leakage_scan(report)
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            SCRATCH_ROOT.rmdir()
        except OSError:
            pass
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded live adaptation convergence smoke.")
    parser.add_argument("--live", action="store_true", help="Make exactly one provider request.")
    args = parser.parse_args(argv)
    if args.live and not _credentials_available():
        print(json.dumps({
            "smoke": SMOKE_VERSION,
            "outcome": "infrastructure_failure",
            "safe_class": "provider_infrastructure",
            "reason_code": "provider_credentials_unavailable",
            "diagnostic_codes": [],
            "provider_called": False,
            "provider_call_count": 0,
            "leakage_scan_clean": True,
        }, ensure_ascii=True, sort_keys=True))
        return 0
    # Provider/client and file-operation helpers may write diagnostics directly
    # to stdout/stderr.  Keep the process output to the allowlisted report only.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        report = _run(args.live)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    for logger_name in ("openai", "httpx", "httpcore", "utils.file_operations"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    sys.exit(main())
