# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Publication gate composer for three-dimensional source-fidelity composition.

Composes ready_status (pass/fail), publishable_status (pass/fail), and
source_fidelity_status (pass/degraded/blocked/unknown) into a single
final publishable determination.

All logic is deterministic. Zero LLM provider calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.enhanced_logger import info, warning as log_warning
from utils.toolkit_source_fidelity_benchmark import (
    STATUS_PASS,
    STATUS_DEGRADED,
    STATUS_BLOCKED,
    STATUS_UNKNOWN,
    worst_status,
)

# Feature flag: set by callers based on their config.
ENABLE_SOURCE_FIDELITY_ENFORCEMENT = True

# Severity ordering used for status normalization.
_FAIL_MAP: Dict[str, str] = {
    "pass": STATUS_PASS,
    "fail": STATUS_BLOCKED,
    "degraded": STATUS_DEGRADED,
    "blocked": STATUS_BLOCKED,
    "unknown": STATUS_UNKNOWN,
}


def _normalize_status(status: str, default: str = STATUS_UNKNOWN) -> str:
    """Normalize a status string to one of the four canonical values.

    Maps 'fail' -> 'blocked', 'pass' -> 'pass', 'degraded' -> 'degraded',
    'unknown' -> 'unknown', anything else -> default.
    """
    normalized = status.strip().lower()
    return _FAIL_MAP.get(normalized, default)


def compose_publication_gate(
    ready_status: str,
    publishable_status: str,
    source_fidelity_status: str = STATUS_UNKNOWN,
    enable_fidelity_flag: bool = True,
    waiver_active: bool = False,
) -> Dict[str, Any]:
    """Compose three publication dimensions into a single final verdict.

    Args:
        ready_status: "pass" or "fail" from readiness audit.
        publishable_status: "pass" or "fail" from publishability audit.
        source_fidelity_status: "pass", "degraded", "blocked", or "unknown".
        enable_fidelity_flag: Feature flag. When False, source_fidelity_status
            is treated as unknown.
        waiver_active: Whether an operator has accepted degraded fidelity.

    Returns:
        Dict with keys:
          final_status: The worst applicable status.
          publishable: True if final_status == pass.
          blocked: True if final_status == blocked.
          degraded: True if final_status == degraded.
          warnings: List of human-readable warning messages.
          blockers: List of human-readable blocker messages.
          source_fidelity_status: The effective fidelity status used.
          waiver_applied: Whether a waiver was applied.
    """
    rs = _normalize_status(ready_status)
    ps = _normalize_status(publishable_status)
    sf = _normalize_status(source_fidelity_status)

    # Feature flag: degrade fidelity to unknown when disabled
    if not enable_fidelity_flag:
        sf = STATUS_UNKNOWN

    # Waiver: only applies when fidelity is degraded and other gates pass
    effective_sf = sf
    if waiver_active and sf == STATUS_DEGRADED and rs == STATUS_PASS and ps == STATUS_PASS:
        effective_sf = STATUS_PASS
        log_warning(
            f"PUBLICATION_GATE: Source fidelity waiver applied "
            f"(degraded -> pass for this publication)",
            category="module_ingest",
        )

    # Compose using worst-status-wins
    composed = worst_status(rs, ps, effective_sf)

    warnings: List[str] = []
    blockers: List[str] = []

    if rs == STATUS_BLOCKED and ready_status.strip().lower() != "pass":
        blockers.append("Module is not structurally ready (readiness audit failed)")
    if ps == STATUS_BLOCKED and publishable_status.strip().lower() != "pass":
        blockers.append("Module is not publishable (publishability audit failed)")

    if sf == STATUS_BLOCKED:
        blockers.append(
            "Source fidelity is blocked: one or more benchmark categories "
            "fall below the degraded threshold"
        )
    elif sf == STATUS_DEGRADED:
        warnings.append(
            "Source fidelity is degraded: one or more benchmark categories "
            "fall below the pass threshold but above the degraded threshold"
        )

    if waiver_active and sf == STATUS_DEGRADED:
        warnings.append("Source fidelity waiver has been accepted by operator")

    publishable = composed == STATUS_PASS
    blocked = composed == STATUS_BLOCKED
    degraded = composed == STATUS_DEGRADED

    return {
        "final_status": composed,
        "publishable": publishable,
        "blocked": blocked,
        "degraded": degraded,
        "warnings": warnings,
        "blockers": blockers,
        "ready_status_effective": rs,
        "publishable_status_effective": ps,
        "source_fidelity_status_effective": effective_sf,
        "source_fidelity_raw": source_fidelity_status,
        "waiver_applied": waiver_active and sf == STATUS_DEGRADED and rs == STATUS_PASS and ps == STATUS_PASS,
    }


def compose_publishability_from_report(
    ready_status: str,
    publishable_status: str,
    source_fidelity_status: str = STATUS_UNKNOWN,
    enable_fidelity_flag: bool = True,
    waiver_active: bool = False,
) -> Dict[str, Any]:
    """Convenience wrapper that composes gate and returns a publishability audit
    compatible result dict with source_fidelity_status plus final outcome.

    This is the intended integration point for audit_module_publishability.py.
    """
    gate = compose_publication_gate(
        ready_status=ready_status,
        publishable_status=publishable_status,
        source_fidelity_status=source_fidelity_status,
        enable_fidelity_flag=enable_fidelity_flag,
        waiver_active=waiver_active,
    )

    # Determine the effective final publishable status
    if gate["blocked"]:
        final_publishable = "blocked"
    elif gate["degraded"]:
        final_publishable = "degraded"
    elif gate["publishable"]:
        final_publishable = "pass"
    else:
        final_publishable = "unknown"

    return {
        "source_fidelity_status": gate["source_fidelity_status_effective"],
        "source_fidelity_raw": gate["source_fidelity_raw"],
        "source_fidelity_blockers": [b for b in gate["blockers"] if "fidelity" in b.lower()],
        "source_fidelity_warnings": [w for w in gate["warnings"] if "fidelity" in w.lower()],
        "final_publishable_status": final_publishable,
        **gate,
    }


def status_from_boolean(passed: bool) -> str:
    """Convert a boolean pass/fail to status string."""
    return STATUS_PASS if passed else "fail"
