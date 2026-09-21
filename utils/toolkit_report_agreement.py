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
from typing import Any, Dict, List, Mapping, Optional, Tuple

from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM

# Canonical status values
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_DEGRADED = "degraded"
STATUS_NOT_APPLICABLE = "not_applicable"

# Valid freshness_states for authoritative/current reports (degraded content is still current)
FRESH_STATES = ("current", "authoritative", "degraded")
ADAPTATION_REPORT_AGREEMENT_CONTRACT_VERSION = (
    "toolkit_adaptation_report_agreement.v1"
)
_ADAPTATION_FRESH_STATES = frozenset(FRESH_STATES)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _adaptation_artifact_identity(artifact: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract the bounded identity shared by attempt/publication reports."""
    provenance = artifact.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    payload = artifact.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    source_ref = payload.get("source_ref")
    source_ref = source_ref if isinstance(source_ref, Mapping) else {}
    source_hash = str(
        provenance.get("source_hash") or source_ref.get("sha256") or ""
    ).strip().lower()
    source_path = str(
        provenance.get("source_path") or source_ref.get("path") or ""
    ).strip()
    return {
        "attempt_id": str(artifact.get("attempt_id") or "").strip(),
        "attempt_number": artifact.get("attempt_number"),
        "revision_number": artifact.get("revision_number"),
        "source_hash": source_hash,
        "source_path": source_path,
        "source_title": str(provenance.get("source_title") or "").strip(),
    }


def _artifact_freshness_state(artifact: Mapping[str, Any]) -> str:
    freshness = artifact.get("report_freshness")
    if not isinstance(freshness, Mapping):
        return "unknown"
    return str(freshness.get("state") or "unknown").strip().lower()


def _artifact_status_matches_payload(
    artifact: Mapping[str, Any],
    *,
    kind: str,
    blockers: List[str],
) -> None:
    """Reject an artifact envelope whose status disagrees with its payload."""
    payload = artifact.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    if kind == "build_result":
        payload_status = str(payload.get("build_status") or "").strip().lower()
        envelope_status = str(artifact.get("status") or "").strip().lower()
        if payload_status and envelope_status != payload_status:
            blockers.append("contradiction:attempt_report_status_mismatch")
    elif kind == "publication_report":
        payload_status = str(payload.get("publication_status") or "").strip().lower()
        envelope_status = str(artifact.get("status") or "").strip().lower()
        if payload_status and envelope_status != payload_status:
            blockers.append("contradiction:publication_report_status_mismatch")


def _report_claim_is_completed(report: Any) -> bool:
    """Return whether a module/report surface claims publication completed."""
    if not isinstance(report, Mapping):
        return False
    status = str(report.get("status") or "").strip().lower()
    terminal = str(report.get("terminal_status") or "").strip().lower()
    publication = str(report.get("publication_status") or "").strip().lower()
    return (
        status in {"success", "completed", "published"}
        or terminal == "completed"
        or publication in {"completed", "published"}
    )


def compose_adaptation_report_agreement(
    attempt_report: Any,
    publication_report: Any = None,
    *,
    expected_attempt_id: Optional[str] = None,
    expected_source_hash: Optional[str] = None,
    expected_revision_number: Optional[int] = None,
    require_publication: bool = False,
    completion_claim: Optional[Mapping[str, Any]] = None,
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate correlated adaptation attempt/publication report claims.

    This strict contract is intentionally separate from the legacy report
    composer. It is used only by the explicit ``llm_adaptation`` lane and
    compares Python-owned artifact identity, source references, freshness, and
    completion status before a completed adaptation is surfaced.
    """
    from utils.toolkit_adaptation_artifacts import validate_adaptation_artifact

    blockers: List[str] = []
    diagnostics: List[str] = []
    stale_reports: List[str] = []

    attempt_result = validate_adaptation_artifact(attempt_report)
    if not attempt_result.get("valid"):
        blockers.append("attempt_report_invalid")
        diagnostics.extend(
            "attempt_report:" + str(item.get("code") or "invalid")
            for item in (attempt_result.get("diagnostics") or [])[:8]
            if isinstance(item, Mapping)
        )
        attempt = None
    else:
        attempt = attempt_result.get("artifact")

    publication = None
    if publication_report is not None:
        publication_result = validate_adaptation_artifact(publication_report)
        if not publication_result.get("valid"):
            blockers.append("publication_report_invalid")
            diagnostics.extend(
                "publication_report:" + str(item.get("code") or "invalid")
                for item in (publication_result.get("diagnostics") or [])[:8]
                if isinstance(item, Mapping)
            )
        else:
            publication = publication_result.get("artifact")
    elif require_publication:
        blockers.append("publication_report_missing")

    identities: Dict[str, Dict[str, Any]] = {}
    for label, artifact in (("attempt", attempt), ("publication", publication)):
        if not isinstance(artifact, Mapping):
            continue
        kind = str(artifact.get("artifact_kind") or "").strip().lower()
        expected_kind = "build_result" if label == "attempt" else "publication_report"
        if kind != expected_kind:
            blockers.append(f"{label}_report_kind_invalid")
        provenance = artifact.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("adaptation_mode") != ADAPTATION_MODE_LLM:
            blockers.append(f"{label}_report_adaptation_mode_invalid")
        identity = _adaptation_artifact_identity(artifact)
        identities[label] = identity
        if not identity["attempt_id"] or not identity["source_hash"] or not identity["source_path"]:
            blockers.append(f"{label}_report_source_identity_missing")

        freshness_state = _artifact_freshness_state(artifact)
        if freshness_state not in _ADAPTATION_FRESH_STATES:
            stale_reports.append(label)
            blockers.append(f"stale_report:{label}:{freshness_state}")
        _artifact_status_matches_payload(artifact, kind=kind, blockers=blockers)

    attempt_identity = identities.get("attempt")
    if attempt_identity:
        if expected_attempt_id and attempt_identity["attempt_id"] != str(expected_attempt_id).strip():
            blockers.append("contradiction:attempt_id_mismatch_expected")
        if expected_source_hash and attempt_identity["source_hash"] != str(expected_source_hash).strip().lower():
            blockers.append("contradiction:source_hash_mismatch_expected")
        if expected_revision_number is not None and attempt_identity["revision_number"] != expected_revision_number:
            blockers.append("contradiction:revision_number_mismatch_expected")

    publication_identity = identities.get("publication")
    if attempt_identity and publication_identity:
        for field in ("attempt_id", "attempt_number", "revision_number", "source_hash", "source_path"):
            if attempt_identity.get(field) != publication_identity.get(field):
                blockers.append(f"contradiction:{field}_mismatch_between_reports")

        attempt_created = str(attempt.get("created_at") or "")
        publication_created = str(publication.get("created_at") or "")
        if publication_created < attempt_created:
            stale_reports.append("publication")
            blockers.append("stale_report:publication_before_attempt")

    if isinstance(attempt, Mapping):
        attempt_payload = attempt.get("payload")
        attempt_payload = attempt_payload if isinstance(attempt_payload, Mapping) else {}
        build_status = str(attempt_payload.get("build_status") or "").strip().lower()
    else:
        build_status = ""

    publication_status = ""
    registry_verified = False
    if isinstance(publication, Mapping):
        publication_payload = publication.get("payload")
        publication_payload = publication_payload if isinstance(publication_payload, Mapping) else {}
        publication_status = str(publication_payload.get("publication_status") or "").strip().lower()
        registry = publication_payload.get("registry_evidence")
        registry = registry if isinstance(registry, Mapping) else {}
        registry_verified = registry.get("verified") is True and str(
            registry.get("status") or ""
        ).strip().lower() in {"pass", "success", "published"}

    if publication_status == "published":
        if build_status != "passed":
            blockers.append("contradiction:published_without_passed_attempt")
        if not registry_verified:
            blockers.append("contradiction:published_without_verified_registry")
        if not isinstance(publication, Mapping) or not isinstance(
            (publication.get("payload") or {}).get("published_at"), str
        ):
            blockers.append("publication_timestamp_missing")

    if _report_claim_is_completed(completion_claim):
        if publication_status != "published":
            blockers.append("contradiction:completed_claim_without_published_report")
        if build_status != "passed":
            blockers.append("contradiction:completed_claim_without_passed_attempt")
        if isinstance(completion_claim, Mapping):
            claim_mode = str(
                completion_claim.get("adaptation_mode")
                or (completion_claim.get("adaptation_provenance") or {}).get("adaptation_mode")
                or ""
            ).strip().lower()
            if claim_mode and claim_mode != ADAPTATION_MODE_LLM:
                blockers.append("contradiction:completion_claim_adaptation_mode")
            claim_freshness = _normalize_freshness(
                completion_claim.get("report_freshness", completion_claim.get("freshness", {}))
            )
            if claim_freshness not in _ADAPTATION_FRESH_STATES:
                stale_reports.append("completion_claim")
                blockers.append(f"stale_report:completion_claim:{claim_freshness}")

    checked = checked_at or _utc_now_iso()
    unique_blockers = list(dict.fromkeys(blockers))
    unique_diagnostics = list(dict.fromkeys(diagnostics))
    return {
        "contract_version": ADAPTATION_REPORT_AGREEMENT_CONTRACT_VERSION,
        "status": STATUS_BLOCKED if unique_blockers else STATUS_PASS,
        "internal_coherent": not bool(unique_blockers),
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "attempt_identity": attempt_identity or {},
        "publication_identity": publication_identity or {},
        "source_reference_agreement": bool(
            attempt_identity
            and publication_identity
            and attempt_identity.get("source_hash") == publication_identity.get("source_hash")
            and attempt_identity.get("source_path") == publication_identity.get("source_path")
        ) if publication_identity else bool(attempt_identity),
        "attempt_report_status": build_status or "unknown",
        "publication_report_status": publication_status or "not_provided",
        "registry_verified": registry_verified,
        "stale_reports": list(dict.fromkeys(stale_reports)),
        "blockers": unique_blockers,
        "diagnostics": unique_diagnostics,
        "checked_at": checked,
        "published_claim_verified": bool(
            publication_status == "published"
            and build_status == "passed"
            and registry_verified
            and not unique_blockers
        ),
    }


def compose_adaptation_report_identity_agreement(
    reports: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
    required_reports: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Any]:
    """Compare the shared identity on the current adaptation report set.

    This consumes the identity fields already emitted by adaptation callback,
    convergence, gate, and publication report surfaces.  It intentionally
    does not define another persisted envelope or alter the legacy agreement
    composer.  A missing, stale, or mismatched report is non-publishable.
    """

    labels = required_reports or (
        "callback",
        "convergence",
        "validation",
        "readiness",
        "semantic",
        "gameplay",
        "publication",
    )
    expected = {
        field: expected_identity.get(field)
        for field in (
            "attempt_id",
            "attempt_number",
            "revision_number",
            "source_hash",
            "staging_path",
        )
    }
    blockers: List[str] = []
    stale_reports: List[str] = []
    identities: Dict[str, Dict[str, Any]] = {}

    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    def _first(report: Mapping[str, Any], field: str) -> Any:
        for candidate in (
            report,
            _mapping(report.get("adaptation_provenance")),
            _mapping(report.get("provenance")),
            _mapping(report.get("identity")),
            _mapping(report.get("staging_identity")),
            _mapping(report.get("staging_reference")),
            _mapping(report.get("report_freshness")),
        ):
            if field in candidate and candidate.get(field) is not None:
                return candidate.get(field)
        return None

    def _path(report: Mapping[str, Any]) -> Any:
        for candidate in (
            report,
            _mapping(report.get("staging_identity")),
            _mapping(report.get("staging_reference")),
            _mapping(report.get("staging")),
            _mapping(report.get("report_freshness")),
        ):
            for field in ("staging_path", "path", "output_directory", "module_dir"):
                value = candidate.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    for label in labels:
        report = _mapping(reports.get(label))
        if not report:
            blockers.append("missing_report:" + label)
            continue
        freshness = _mapping(report.get("report_freshness"))
        if freshness and str(freshness.get("state") or "").strip().lower() not in FRESH_STATES:
            stale_reports.append(label)
            blockers.append("stale_report:" + label)
        identity = {
            "attempt_id": _first(report, "attempt_id"),
            "attempt_number": _first(report, "attempt_number"),
            "revision_number": _first(report, "revision_number"),
            "source_hash": _first(report, "source_hash"),
            "staging_path": _path(report),
        }
        identities[label] = identity
        for field, value in identity.items():
            if value != expected.get(field):
                blockers.append("identity_mismatch:%s:%s" % (label, field))

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "contract_version": ADAPTATION_REPORT_AGREEMENT_CONTRACT_VERSION,
        "status": STATUS_BLOCKED if unique_blockers else STATUS_PASS,
        "publication_allowed": not unique_blockers,
        "current_identity": dict(expected),
        "report_identities": identities,
        "stale_reports": list(dict.fromkeys(stale_reports)),
        "blockers": unique_blockers,
    }


def _normalize_status(value: Any) -> str:
    """Normalize a status string to one of the canonical values."""
    raw = str(value or "").strip().lower()
    if raw in {"pass", "success", "ok"}:
        return STATUS_PASS
    if raw in {"blocked", "fail", "failed", "error"}:
        return STATUS_BLOCKED
    if raw in {"degraded", "warning", "warn", "reconciled_degraded"}:
        return STATUS_DEGRADED
    if raw == STATUS_NOT_APPLICABLE:
        return STATUS_NOT_APPLICABLE
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
    source_fidelity_mode: Optional[str] = None,
    report_freshness_states: Optional[Dict[str, str]] = None,
    missing_reports: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compose a report-agreement result from individual status values.

    This is the low-level composer. Callers that load from disk should
    use compose_report_agreement_from_module_dir() instead.

    Args:
        source_fidelity_status: "pass", "blocked", "degraded", "unknown", "not_applicable"
        validation_status: "pass", "blocked", "unknown"
        ready_status: "pass", "fail", "unknown"
        publishable_status: "pass", "fail", "unknown"
        effective_publishable_status: "pass", "fail", "unknown"
        toolkit_top_level_status: Status from toolkit_build_report.json top level
        toolkit_publishability_stage_status: Status from stages.publishability
        source_fidelity_mode: Explicit source-fidelity mode. The
            ``not_applicable`` status is informational only for the explicit
            ``llm_adaptation`` mode.
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

    adaptation_fidelity_not_applicable = (
        sf == STATUS_NOT_APPLICABLE
        and str(source_fidelity_mode or "").strip().lower() == ADAPTATION_MODE_LLM
    )
    if sf == STATUS_NOT_APPLICABLE and not adaptation_fidelity_not_applicable:
        blockers.append("source_fidelity_not_applicable_without_adaptation_mode")
        diagnostics.append(
            "source_fidelity_status=not_applicable is valid only for the explicit "
            "llm_adaptation source-fidelity mode"
        )
        internal_coherent = False
    elif adaptation_fidelity_not_applicable:
        diagnostics.append(
            "source_fidelity_not_applicable: literal source preservation is not the "
            "adaptation objective"
        )
        if (
            source_fidelity_effective_status is not None
            and sfe_normalized != STATUS_NOT_APPLICABLE
        ):
            blockers.append(
                "contradiction:not_applicable_effective_source_fidelity_status"
            )
            diagnostics.append(
                "not_applicable source fidelity cannot be rewritten as a clean "
                "pass or another effective fidelity status"
            )
            internal_coherent = False

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
    elif (
        sf != STATUS_PASS
        and not source_fidelity_reconciled
        and not adaptation_fidelity_not_applicable
    ):
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
        "source_fidelity_mode": source_fidelity_mode,
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
    source_fidelity_path = module_dir / "source_fidelity_report.json"
    source_fidelity_report = _load_report(source_fidelity_path)
    source_fidelity_malformed = (
        source_fidelity_path.exists() and source_fidelity_report is None
    )
    toolkit_report = _load_report(module_dir / "toolkit_build_report.json")

    # Fallback: benchmark report for source fidelity
    if source_fidelity_report is None and not source_fidelity_malformed:
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
    if source_fidelity_malformed:
        missing.append("source_fidelity_malformed")

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
    sf_mode = None
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

    if isinstance(source_fidelity_report, dict):
        sf_mode = source_fidelity_report.get(
            "adaptation_mode", source_fidelity_report.get("source_fidelity_mode")
        )

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
        source_fidelity_mode=sf_mode,
        report_freshness_states=freshness_states if freshness_states else None,
        missing_reports=missing if missing else None,
    )
