# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Shared report-agreement composer for toolkit publication readiness.

Consumes current report payloads (benchmark, source_fidelity, validation,
publishability audit, toolkit build) and produces a structured agreement
result. Blocks contradictions, stale metadata, and missing reports.

All logic is deterministic. Zero LLM provider calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Canonical status values
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_DEGRADED = "degraded"

# Valid freshness_states for authoritative/current reports (degraded content is still current)
FRESH_STATES = ("current", "authoritative", "degraded")


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_status(value: Any) -> str:
    """Normalize a status string to one of the canonical values."""
    raw = str(value or "").strip().lower()
    if raw in {"pass", "success", "ok"}:
        return STATUS_PASS
    if raw in {"blocked", "fail", "failed", "error"}:
        return STATUS_BLOCKED
    if raw in {"degraded", "warning", "warn", "reconciled_degraded"}:
        return STATUS_DEGRADED
    if raw in {"stale", "unknown"}:
        return raw
    return STATUS_UNKNOWN


def _normalize_freshness(freshness: Any) -> str:
    """Extract freshness_state from a freshness metadata blob."""
    if isinstance(freshness, dict):
        return str(freshness.get("state", freshness.get("freshness_state", "unknown")) or "unknown").strip().lower()
    if isinstance(freshness, str):
        return freshness.strip().lower()
    return "unknown"


def _load_report(report_path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON report file from disk, returning None if missing/invalid."""
    if not report_path.exists() or not report_path.is_file():
        return None
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _extract_from_report(report: Dict[str, Any], *keys: str) -> str:
    """Extract the first present, non-empty value from a report dict."""
    for key in keys:
        value = report.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return STATUS_UNKNOWN


def _derive_validation_status(report: Dict[str, Any]) -> str:
    """Derive validation pass/fail from common validation report shapes.

    Checks:
    1. report.status or report.overall_status (explicit top-level)
    2. report.summary.total_failed == 0 -> pass
    3. report.summary.total_failed > 0 -> fail/blocked
    """
    explicit = _extract_from_report(report, "status", "overall_status")
    if explicit != STATUS_UNKNOWN:
        return explicit

    summary = report.get("summary", {})
    if isinstance(summary, dict):
        total_failed = summary.get("total_failed")
        if total_failed is not None:
            try:
                if int(total_failed) == 0:
                    return STATUS_PASS
                if int(total_failed) > 0:
                    return STATUS_BLOCKED
            except (ValueError, TypeError):
                pass

    return STATUS_UNKNOWN


def _report_is_fresh(report: Dict[str, Any]) -> bool:
    """Check whether a report's freshness metadata indicates it is current.
    
    Legacy reports without freshness metadata are treated as current
    if they exist on disk with clear status fields (fail-open default).
    """
    freshness = report.get("report_freshness", report.get("freshness", {}))
    state = _normalize_freshness(freshness)

    # Explicit freshness metadata present
    if state not in ("", "unknown"):
        if state in FRESH_STATES:
            return True
        if state == "stale":
            return False

    freshness_state = str(report.get("freshness_state", "") or "").strip().lower()
    if freshness_state in FRESH_STATES:
        return True
    if freshness_state == "stale":
        return False

    # Legacy report: no freshness metadata at all.
    # Treat as current if it has a meaningful status or timestamp (fail-open).
    has_status = bool(
        report.get("status")
        or report.get("source_fidelity_status")
        or report.get("overall_status")
        or report.get("summary")
        or report.get("timestamp")
        or report.get("generated_at")
    )
    if has_status:
        return True

    return False


def _check_required_reports_present(
    module_dir: Path,
) -> Tuple[List[str], List[str]]:
    """Check which required reports are present/missing.

    Returns (present, missing) lists of report type names.
    """
    report_paths = {
        "validation": module_dir / "validation_report.json",
        "source_fidelity": module_dir / "source_fidelity_report.json",
        "publishability": module_dir / "toolkit_build_report.json",
    }

    present = []
    missing = []
    for rtype, path in report_paths.items():
        if path.exists() and path.is_file():
            present.append(rtype)
        else:
            missing.append(rtype)
    return present, missing


def compose_report_agreement(
    *,
    source_fidelity_status: str = STATUS_UNKNOWN,
    validation_status: str = STATUS_UNKNOWN,
    ready_status: str = STATUS_UNKNOWN,
    publishable_status: str = STATUS_UNKNOWN,
    effective_publishable_status: str = STATUS_UNKNOWN,
    toolkit_top_level_status: str = STATUS_UNKNOWN,
    toolkit_publishability_stage_status: Optional[str] = None,
    source_fidelity_effective_status: Optional[str] = None,
    final_reconciliation_accepted: bool = False,
    final_reconciliation_status: Optional[str] = None,
    report_freshness_states: Optional[Dict[str, str]] = None,
    missing_reports: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compose a report-agreement result from individual status values.

    This is the low-level composer. Callers that load from disk should
    use compose_report_agreement_from_module_dir() instead.

    Args:
        source_fidelity_status: "pass", "blocked", "degraded", "unknown"
        validation_status: "pass", "blocked", "unknown"
        ready_status: "pass", "fail", "unknown"
        publishable_status: "pass", "fail", "unknown"
        effective_publishable_status: "pass", "fail", "unknown"
        toolkit_top_level_status: Status from toolkit_build_report.json top level
        toolkit_publishability_stage_status: Status from stages.publishability
        report_freshness_states: Dict of report_type -> freshness_state
        missing_reports: List of missing report type names

    Returns:
        Dict with status, blockers, diagnostics, playable_publication_status,
        internal_coherent, and playedable fields.
    """
    sf = _normalize_status(source_fidelity_status)
    vs = _normalize_status(validation_status)
    rs = _normalize_status(ready_status)
    ps = _normalize_status(publishable_status)
    eps = _normalize_status(effective_publishable_status)
    tts = _normalize_status(toolkit_top_level_status)
    tps = _normalize_status(toolkit_publishability_stage_status) if toolkit_publishability_stage_status else None

    blockers: List[str] = []
    diagnostics: List[str] = []

    # Step 5.1: normalize effective fidelity and reconciliation status
    sfe_effective = source_fidelity_effective_status or sf
    sfe_normalized = _normalize_status(sfe_effective)
    # Preserve original effective string for output (e.g. "reconciled_degraded")
    sfe = sfe_effective if source_fidelity_effective_status else sf
    frs = (
        final_reconciliation_status
        if final_reconciliation_status else "not_applicable"
    )
    source_fidelity_reconciled = (
        final_reconciliation_accepted
        and str(sfe_effective).strip().lower() == "reconciled_degraded"
    )
    if source_fidelity_reconciled:
        diagnostics.append(
            "source_fidelity_reconciled: accepted final reconciliation, "
            "effective source fidelity is degraded (not clean pass)"
        )

    internal_coherent = True

    # 1) Required reports present
    if missing_reports:
        for mr in missing_reports:
            blockers.append(f"missing_report:{mr}")
            diagnostics.append(f"Required report '{mr}' not found on disk")
        internal_coherent = False

    # 2) Freshness check
    freshen_states = report_freshness_states or {}
    for rtype, fstate in freshen_states.items():
        if _normalize_freshness(fstate) not in FRESH_STATES:
            blockers.append(f"stale_report:{rtype}:{fstate}")
            diagnostics.append(f"Report '{rtype}' freshness state is '{fstate}' (expected current)")
            internal_coherent = False

    # 3) Contradiction: source_fidelity pass but validation fail
    if sf == STATUS_PASS and vs == STATUS_BLOCKED:
        blockers.append("contradiction:source_fidelity_pass_validation_fail")
        diagnostics.append(
            "source_fidelity_status=pass but validation_status=blocked -- "
            "source fidelity cannot pass with failed validation"
        )
        internal_coherent = False

    # 4) Contradiction: validation pass but publishability fail
    if vs == STATUS_PASS and ps == STATUS_BLOCKED:
        blockers.append("contradiction:validation_pass_publishability_fail")
        diagnostics.append(
            "validation_status=pass but publishable_status=blocked -- "
            "validation pass should imply publishability pass if no semantic blockers"
        )
        internal_coherent = False

    # 5) Contradiction: ready pass but publishability fail
    if rs == STATUS_PASS and ps == STATUS_BLOCKED:
        blockers.append("contradiction:ready_pass_publishability_fail")
        diagnostics.append(
            "ready_status=pass but publishable_status=blocked -- "
            "structural readiness must be met for publishability"
        )
        internal_coherent = False

    # 6) toolkit top-level failed/blocked but publishable/effective says pass
    if tts in (STATUS_BLOCKED, STATUS_FAILED) and eps == STATUS_PASS:
        blockers.append("contradiction:toolkit_failed_effective_pass")
        diagnostics.append(
            f"toolkit top-level status={tts} but effective_publishable_status=pass -- "
            "top-level failure contradicts effective publishability"
        )
        internal_coherent = False

    if tts in (STATUS_BLOCKED, STATUS_FAILED) and ps == STATUS_PASS:
        blockers.append("contradiction:toolkit_failed_publishable_pass")
        diagnostics.append(
            f"toolkit top-level status={tts} but publishable_status=pass -- "
            "top-level failure contradicts publishability pass"
        )
        internal_coherent = False

    # 7) toolkit top-level pass but nested publishability stage says fail
    if tts == STATUS_PASS and tps is not None and tps == STATUS_BLOCKED:
        blockers.append("contradiction:toolkit_pass_nested_publishability_fail")
        diagnostics.append(
            "toolkit top-level status=pass but stages.publishability.status=blocked -- "
            "nested publishability failure contradicts top-level pass"
        )
        internal_coherent = False

    # 8) effective_publishable pass but publishable_status fail
    if eps == STATUS_PASS and ps == STATUS_BLOCKED:
        blockers.append("contradiction:effective_pass_publishability_fail")
        diagnostics.append(
            "effective_publishable_status=pass but publishable_status=blocked -- "
            "effective pass cannot exist when publishability failed"
        )
        internal_coherent = False

    # 9) Determine overall agreement status
    if blockers:
        agreement_status = STATUS_BLOCKED
    elif missing_reports or any(
        _normalize_freshness(f) not in FRESH_STATES
        for f in freshen_states.values()
    ):
        agreement_status = STATUS_STALE
    elif not internal_coherent:
        agreement_status = STATUS_FAILED
    else:
        agreement_status = STATUS_PASS

    # 10) Determine playable_publication_status
    if agreement_status != STATUS_PASS:
        playable = STATUS_BLOCKED
    elif sf != STATUS_PASS and not source_fidelity_reconciled:
        playable = STATUS_BLOCKED
    elif rs != STATUS_PASS:
        playable = STATUS_BLOCKED
    elif vs != STATUS_PASS:
        playable = STATUS_BLOCKED
    elif ps != STATUS_PASS:
        playable = STATUS_BLOCKED
    elif eps != STATUS_PASS:
        playable = STATUS_BLOCKED
    else:
        playable = STATUS_PASS

    return {
        "status": agreement_status,
        "internal_coherent": internal_coherent,
        "source_fidelity_status": sf,
        "source_fidelity_effective_status": sfe,
        "final_reconciliation_accepted": final_reconciliation_accepted,
        "final_reconciliation_status": frs,
        "source_fidelity_reconciled": source_fidelity_reconciled,
        "validation_status": vs,
        "ready_status": rs,
        "publishable_status": ps,
        "effective_publishable_status": eps,
        "playable_publication_status": playable,
        "blockers": blockers,
        "diagnostics": diagnostics,
        "missing_reports": missing_reports or [],
        "stale_reports": [
            rtype for rtype, fstate in freshen_states.items()
            if _normalize_freshness(fstate) not in FRESH_STATES
        ],
        "checked_at": _utc_now_iso(),
    }


def compose_report_agreement_from_module_dir(
    module_dir: Path,
) -> Dict[str, Any]:
    """Load reports from a module directory and compose agreement result.

    Reads:
    - modules/<slug>/validation_report.json
    - modules/<slug>/source_fidelity_report.json
    - modules/<slug>/toolkit_build_report.json

    Falls back to accurate_ingest_benchmark_report.json for source_fidelity
    if source_fidelity_report.json is missing.

    Legacy reports without freshness metadata are treated as current
    if they have meaningful status fields (fail-open default).

    Args:
        module_dir: Path to the module directory.

    Returns:
        Same result shape as compose_report_agreement().
    """
    validation_report = _load_report(module_dir / "validation_report.json")
    source_fidelity_report = _load_report(module_dir / "source_fidelity_report.json")
    toolkit_report = _load_report(module_dir / "toolkit_build_report.json")

    # Fallback: benchmark report for source fidelity
    if source_fidelity_report is None:
        benchmark_report = _load_report(
            module_dir / "accurate_ingest_benchmark_report.json"
        )
        if benchmark_report is not None:
            source_fidelity_report = {
                "source_fidelity_status": benchmark_report.get(
                    "source_fidelity_status", "unknown"
                ),
            }

    # Extract statuses
    sf_status = _extract_from_report(
        source_fidelity_report or {}, "source_fidelity_status"
    )
    vs_status = _derive_validation_status(validation_report or {})
    rs_status = _extract_from_report(toolkit_report or {}, "ready_status")
    ps_status = _extract_from_report(toolkit_report or {}, "publishable_status")
    eps_status = _extract_from_report(
        toolkit_report or {}, "effective_publishable_status"
    )
    tts = _extract_from_report(toolkit_report or {}, "status")

    # Toolkit nested publishability stage status
    tps = None
    if toolkit_report:
        stages = toolkit_report.get("stages", {})
        pub_stage = stages.get("publishability", {}) if isinstance(stages, dict) else {}
        if isinstance(pub_stage, dict) and pub_stage.get("status"):
            tps = str(pub_stage["status"]).strip().lower()

    # Missing reports: check for required report files on disk
    _, missing = _check_required_reports_present(module_dir)

    # Stale reports: only mark as stale if _report_is_fresh returns False.
    # Legacy reports without freshness metadata pass _report_is_fresh
    # if they have meaningful status fields (fail-open default).
    stale_reports: List[str] = []
    for rtype, report in [
        ("validation", validation_report),
        ("source_fidelity", source_fidelity_report),
        ("toolkit_build", toolkit_report),
    ]:
        if report and not _report_is_fresh(report):
            stale_reports.append(rtype)

    # Build freshness states for compose_report_agreement.
    # Use the stale_reports list: reports in stale_reports get "stale" state.
    freshness_states: Dict[str, str] = {}
    if stale_reports:
        for rtype in stale_reports:
            freshness_states[rtype] = "stale"

    # Step 5.1: load accepted final reconciliation report if present
    final_rec_accepted = False
    final_rec_status = None
    sfe_status = None
    try:
        from utils.toolkit_final_reconciliation import (
            load_final_reconciliation_report,
            is_final_reconciliation_accepted,
        )
        recon_report = load_final_reconciliation_report(module_dir)
        if recon_report is not None and is_final_reconciliation_accepted(recon_report):
            final_rec_accepted = True
            final_rec_status = recon_report.get("status")
            sfe_status = recon_report.get("source_fidelity_effective_status")
    except Exception:
        pass

    return compose_report_agreement(
        source_fidelity_status=sf_status,
        validation_status=vs_status,
        ready_status=rs_status,
        publishable_status=ps_status,
        effective_publishable_status=eps_status,
        toolkit_top_level_status=tts,
        toolkit_publishability_stage_status=tps,
        source_fidelity_effective_status=sfe_status,
        final_reconciliation_accepted=final_rec_accepted,
        final_reconciliation_status=final_rec_status,
        report_freshness_states=freshness_states if freshness_states else None,
        missing_reports=missing if missing else None,
    )
