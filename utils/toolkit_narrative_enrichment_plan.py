# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Narrative Enrichment Placeholder Plan
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Artifact-only narrative enrichment planning for accurate-ingest builds.
This module defines the enrichment plan shape and source-lock rules.
It does NOT apply enrichment, call providers, or mutate module data.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.enhanced_logger import info

ENRICHMENT_PLAN_VERSION = "narrative_enrichment_plan.v1"

VALID_PROFILES = frozenset(
    {
        "none",
        "three_stance_single_turn",
        "five_playline_stateful",
        "custom",
    }
)

STATUS_NOT_REQUESTED = "not_requested"
STATUS_PLANNED = "planned"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

_ENRICHMENT_SOURCE_LOCK_FIELDS = [
    "required_npcs_locked",
    "required_locations_locked",
    "plot_topology_locked",
    "puzzle_rules_locked",
    "source_evidence_locked",
]


def _derive_source_fidelity_status(build_result: Dict[str, Any]) -> str:
    """Derive the source/build fidelity status from the build result payload."""
    bf = build_result.get("build_fidelity") or {}
    bf_status = str(bf.get("status") or "").strip().lower()
    if bf_status in ("blocked", "failed"):
        return bf_status
    if bf_status in ("pass", "degraded"):
        return bf_status
    overall = str(build_result.get("status") or "unknown").strip().lower()
    if overall in ("blocked", "failed", "success"):
        return overall if overall != "success" else "pass"
    return "unknown"


def _build_default_source_locks(source_fidelity_status: str) -> Dict[str, bool]:
    """Build source-lock state dict. All locks are active by default
    when fidelity is not blocked or failed."""
    locked = source_fidelity_status not in ("blocked", "failed")
    return {field: locked for field in _ENRICHMENT_SOURCE_LOCK_FIELDS}


def can_plan_enrichment(build_result: Dict[str, Any]) -> Tuple[bool, str]:
    """Check whether enrichment planning is allowed given build/source fidelity.

    Returns (True, "") or (False, reason).
    """
    bf = build_result.get("build_fidelity") or {}
    bf_status = str(bf.get("status") or "").strip().lower()
    if bf_status in ("blocked", "failed"):
        return (
            False,
            f"build_fidelity_{bf_status}:{bf.get('refusal_reason') or 'source_fidelity_blocked'}",
        )
    refusal = str(bf.get("refusal_reason") or "").strip()
    if refusal:
        return False, refusal
    overall = str(build_result.get("status") or "").strip().lower()
    if overall == "blocked":
        return False, "build_blocked"
    if overall == "failed":
        return False, "build_failed"
    return True, ""


def _validate_profile(profile: str) -> str:
    """Normalise and validate enrichment profile.

    Returns normalised profile for supported profiles.
    Returns 'none' for empty/blank input (defaulting).
    Returns the raw lowercased value for non-empty unsupported profiles
    so downstream callers can add blockers.
    """
    p = profile.strip().lower()
    if not p:
        return "none"
    if p in VALID_PROFILES:
        return p
    return p


def _is_non_none_profile(profile: str) -> bool:
    """Return True when profile is a non-default enrichment profile."""
    return _validate_profile(profile) not in ("none", "")


def load_fidelity_reports(
    build_result: Dict[str, Any],
    report_path: Optional[Path] = None,
    rollup_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Stub for loading persisted fidelity report/rollup from disk.
    Currently returns empty dicts - left as an extension point for a
    later implementation that reads persisted reports."""
    return {
        "build_fidelity": {},
        "source_fidelity": {},
        "report_path": str(report_path) if report_path else "",
        "rollup_path": str(rollup_path) if rollup_path else "",
    }


def build_enrichment_plan(
    build_result: Dict[str, Any],
    profile: str = "none",
    report_path: Optional[Path] = None,
    rollup_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a narrative enrichment plan artifact.

    Returns a deterministic plan dict with profile, status, source locks,
    blockers, and artifact references. Does NOT apply or generate enrichment.
    """
    plan_version = ENRICHMENT_PLAN_VERSION
    normalised_profile = _validate_profile(profile)
    source_ok, refusal = can_plan_enrichment(build_result)
    source_fidelity_status = _derive_source_fidelity_status(build_result)
    _non_none_requested = _is_non_none_profile(normalised_profile)
    source_locks = _build_default_source_locks(source_fidelity_status)

    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not source_ok:
        if _non_none_requested:
            blockers.append(
                {
                    "category": "source_fidelity",
                    "message": refusal or "source_fidelity_blocked",
                }
            )
    elif source_fidelity_status == "degraded" and _non_none_requested:
        warnings.append(
            {
                "category": "source_fidelity",
                "message": "source_fidelity_degraded",
            }
        )

    # Reject non-empty unsupported profiles with a blocker
    if normalised_profile and normalised_profile not in VALID_PROFILES:
        blockers.append(
            {
                "category": "invalid_profile",
                "message": f"unsupported enrichment profile: {normalised_profile}",
            }
        )

    status = _derive_plan_status(
        normalised_profile, source_ok, len(blockers) > 0, source_fidelity_status
    )

    fidelity_refs = load_fidelity_reports(build_result, report_path, rollup_path)

    plan: Dict[str, Any] = {
        "version": plan_version,
        "status": status,
        "profile": normalised_profile,
        "source_fidelity_status": source_fidelity_status,
        "can_apply": False,
        "auto_apply": False,
        "eligible_fields": [],
        "field_budgets": {},
        "source_locks": source_locks,
        "profile_notes": [],
        "blockers": blockers,
        "warnings": warnings,
        "artifact_refs": {
            "build_fidelity_report": fidelity_refs.get("report_path", ""),
            "source_fidelity_report": fidelity_refs.get("rollup_path", ""),
        },
    }

    info(
        (
            "NARRATIVE_ENRICHMENT: Built enrichment plan "
            f"profile={normalised_profile} status={status} "
            f"blockers={len(blockers)} warnings={len(warnings)}"
        ),
        category="module_ingest",
    )

    return plan


def _derive_plan_status(
    profile: str,
    source_ok: bool,
    has_blockers: bool,
    source_fidelity_status: str,
) -> str:
    """Derive deterministic plan status from inputs."""
    if profile == "none":
        return STATUS_SKIPPED
    if not source_ok or has_blockers:
        return STATUS_BLOCKED
    if source_fidelity_status in ("pass", "degraded"):
        return STATUS_PLANNED
    return STATUS_SKIPPED
