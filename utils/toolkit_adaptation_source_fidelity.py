# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Source Fidelity
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free source-fidelity reporting for the intentional LLM adaptation
lane. Adaptation does not promise literal source preservation, but Python
still records bounded evidence and fail-closes malformed or stale reports.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from utils.toolkit_adaptation_world_context import build_world_context_provenance


ADAPTATION_SOURCE_FIDELITY_CONTRACT_VERSION = (
    "toolkit_adaptation_source_fidelity.v1"
)
ADAPTATION_SOURCE_FIDELITY_STATUS = "not_applicable"
ADAPTATION_SOURCE_FIDELITY_EXPLANATION = (
    "Literal source fidelity is not applicable in llm_adaptation mode; "
    "intentional omissions, reinterpretations, and original NEQ content are allowed."
)

_VALID_EVIDENCE_STATUSES = frozenset(
    {"pass", "degraded", "blocked", "unknown", "not_applicable", "informational"}
)
_STATUS_ALIASES = {
    "fail": "blocked",
    "failed": "blocked",
    "error": "blocked",
    "warning": "degraded",
}
_MAX_TEXT_CHARS = 320
_MAX_PROVENANCE_CHARS = 160
_MAX_EVIDENCE_ITEMS = 24
_MAX_EVIDENCE_FIELDS = 8
_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _utc_now_iso() -> str:
    """Return an ASCII UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ascii_text(value: Any, limit: int = _MAX_TEXT_CHARS) -> str:
    """Return bounded, normalized ASCII text."""
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _bounded_sequence(value: Any) -> List[Any]:
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)[:_MAX_EVIDENCE_ITEMS]
    if value is None:
        return []
    return [value]


def _bounded_evidence_items(*values: Any) -> List[str]:
    """Serialize only small, useful mismatch signals."""
    result: List[str] = []
    seen = set()
    for raw in values:
        for item in _bounded_sequence(raw):
            if isinstance(item, Mapping):
                selected: Dict[str, Any] = {}
                for key in (
                    "category",
                    "code",
                    "status",
                    "message",
                    "reason",
                    "label",
                    "path",
                    "expected",
                    "actual",
                ):
                    if key in item and item[key] not in (None, ""):
                        selected[key] = _ascii_text(item[key], 120)
                if not selected:
                    continue
                try:
                    text = json.dumps(
                        selected,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    continue
            else:
                text = _ascii_text(item, _MAX_TEXT_CHARS)
            if text and text not in seen:
                seen.add(text)
                result.append(text)
            if len(result) >= _MAX_EVIDENCE_ITEMS:
                return result
    return result


def _status_token(value: Any) -> Optional[str]:
    raw = _ascii_text(value, 64).strip().lower()
    if not raw:
        return None
    raw = _STATUS_ALIASES.get(raw, raw)
    return raw if raw in _VALID_EVIDENCE_STATUSES else None


def _freshness_state(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve explicit freshness without treating malformed metadata as current."""
    has_metadata = "report_freshness" in report or "freshness" in report
    if not has_metadata and "freshness_state" not in report:
        return {"state": "current", "explicit": False, "valid": True}

    raw = report.get("report_freshness", report.get("freshness"))
    if isinstance(raw, Mapping):
        raw_state = raw.get("state", raw.get("freshness_state"))
    else:
        raw_state = raw
    if raw_state is None and "freshness_state" in report:
        raw_state = report.get("freshness_state")
    state = _ascii_text(raw_state, 64).strip().lower()
    if state in {"current", "authoritative", "degraded"}:
        return {"state": state, "explicit": True, "valid": True}
    if state == "stale":
        return {"state": "stale", "explicit": True, "valid": True}
    return {"state": state or "unknown", "explicit": True, "valid": False}


def _safe_provenance_value(
    value: Any, *, path: bool = False, limit: int = _MAX_PROVENANCE_CHARS
) -> str:
    text = _ascii_text(value, limit)
    if not text:
        return ""
    if path and (
        text.startswith("/")
        or "\\" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        return ""
    return text


def _build_provenance(
    *,
    attempt_metadata: Optional[Mapping[str, Any]],
    staging_target: Optional[Mapping[str, Any]],
    module_slug: str,
    stage: str,
) -> Dict[str, Any]:
    metadata = attempt_metadata if isinstance(attempt_metadata, Mapping) else {}
    target = staging_target if isinstance(staging_target, Mapping) else {}

    def value(key: str) -> Any:
        return metadata.get(key, target.get(key))

    provenance: Dict[str, Any] = {
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "stage": _safe_provenance_value(stage) or "adaptation_gate_composition",
        "module_slug": _safe_provenance_value(module_slug),
    }
    for key in ("attempt_id", "stage_id", "source_format", "dossier_artifact_path"):
        item = value(key)
        if key == "attempt_id":
            safe = _safe_provenance_value(item)
            if safe and not _ATTEMPT_ID_RE.fullmatch(safe):
                safe = ""
        elif key == "dossier_artifact_path":
            safe = _safe_provenance_value(item, path=True)
        else:
            safe = _safe_provenance_value(item)
        if safe:
            provenance[key] = safe

    source_path = _safe_provenance_value(value("source_path"), path=True)
    if source_path:
        provenance["source_path"] = source_path
    source_hash = _safe_provenance_value(value("source_hash"), limit=64)
    if source_hash and _SHA256_RE.fullmatch(source_hash):
        provenance["source_hash"] = source_hash.lower()
    for key in ("attempt_number", "revision_number"):
        item = value(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            provenance[key] = item
    provenance["world_context_provenance"] = build_world_context_provenance(metadata)
    return provenance


def _extract_evidence(
    evidence: Any,
    *,
    evidence_state: Optional[str],
    evidence_errors: Optional[Iterable[Any]],
    additional_evidence: Any,
) -> Dict[str, Any]:
    """Normalize legacy fidelity evidence without changing its meaning."""
    state = _ascii_text(evidence_state, 64).strip().lower() if evidence_state else ""
    errors = _bounded_evidence_items(evidence_errors)
    if state == "malformed":
        return {
            "state": "malformed",
            "status": "unknown",
            "freshness_state": "unknown",
            "mismatch_evidence": [],
            "errors": errors or ["source_fidelity_evidence_malformed"],
        }

    if evidence is None or state in {"missing_optional", "not_provided"}:
        return {
            "state": "not_provided",
            "status": "unknown",
            "freshness_state": "unknown",
            "mismatch_evidence": _bounded_evidence_items(additional_evidence),
            "errors": errors,
        }

    if isinstance(evidence, str):
        status = _status_token(evidence)
        if status is None:
            return {
                "state": "malformed",
                "status": "unknown",
                "freshness_state": "unknown",
                "mismatch_evidence": [],
                "errors": ["source_fidelity_evidence_status_invalid"],
            }
        return {
            "state": "provided",
            "status": status,
            "freshness_state": "current",
            "mismatch_evidence": _bounded_evidence_items(additional_evidence),
            "errors": errors,
        }

    if not isinstance(evidence, Mapping):
        return {
            "state": "malformed",
            "status": "unknown",
            "freshness_state": "unknown",
            "mismatch_evidence": [],
            "errors": ["source_fidelity_evidence_must_be_object"],
        }

    raw_status = evidence.get("source_fidelity_status", evidence.get("status"))
    status = _status_token(raw_status)
    if status is None:
        errors.append("source_fidelity_evidence_status_missing_or_invalid")
        status = "unknown"
        state = "malformed"
    else:
        state = "present"

    freshness = _freshness_state(evidence)
    if freshness["state"] == "stale":
        errors.append("source_fidelity_evidence_stale")
    elif not freshness["valid"]:
        errors.append("source_fidelity_evidence_freshness_invalid")

    mismatch_evidence = _bounded_evidence_items(
        evidence.get("categories"),
        evidence.get("category_results"),
        evidence.get("mismatches"),
        evidence.get("blockers"),
        evidence.get("warnings"),
        evidence.get("errors"),
        additional_evidence,
    )
    return {
        "state": state,
        "status": status,
        "freshness_state": freshness["state"],
        "mismatch_evidence": mismatch_evidence,
        "errors": _bounded_evidence_items(errors),
    }


def build_adaptation_source_fidelity_report(
    *,
    source_fidelity_evidence: Any = None,
    literal_mismatch_evidence: Any = None,
    evidence_state: Optional[str] = None,
    evidence_errors: Optional[Iterable[Any]] = None,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    staging_target: Optional[Mapping[str, Any]] = None,
    module_slug: str = "",
    stage: str = "adaptation_gate_composition",
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the explicit informational fidelity report for an adaptation.

    Literal mismatch evidence is retained as bounded provenance only. A
    malformed or stale evidence report remains a report-agreement blocker; it
    is never silently converted into a passing fidelity result.
    """
    evidence = _extract_evidence(
        source_fidelity_evidence,
        evidence_state=evidence_state,
        evidence_errors=evidence_errors,
        additional_evidence=literal_mismatch_evidence,
    )
    blockers = list(evidence.get("errors") or [])
    checked = checked_at or _utc_now_iso()
    provenance = _build_provenance(
        attempt_metadata=attempt_metadata,
        staging_target=staging_target,
        module_slug=module_slug,
        stage=stage,
    )
    report: Dict[str, Any] = {
        "contract_version": ADAPTATION_SOURCE_FIDELITY_CONTRACT_VERSION,
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "source_fidelity_status": ADAPTATION_SOURCE_FIDELITY_STATUS,
        "source_fidelity_effective_status": ADAPTATION_SOURCE_FIDELITY_STATUS,
        "status": "informational",
        "informational": True,
        "literal_source_fidelity_required": False,
        "explanation": ADAPTATION_SOURCE_FIDELITY_EXPLANATION,
        "literal_mismatch_evidence": list(evidence.get("mismatch_evidence") or []),
        "evidence": {
            "state": evidence.get("state", "not_provided"),
            "source_fidelity_status": evidence.get("status", "unknown"),
            "freshness_state": evidence.get("freshness_state", "unknown"),
            "errors": list(evidence.get("errors") or []),
        },
        "provenance": provenance,
        "report_freshness": {
            "state": "current" if not blockers else "degraded",
            "authoritative": True,
            "stage": provenance.get("stage", stage),
            "attempt_id": provenance.get("attempt_id", ""),
            "written_at": checked,
        },
        "checked_at": checked,
        "report_agreement": {
            "status": "blocked" if blockers else "pass_through",
            "blocking": bool(blockers),
            "blockers": blockers[:_MAX_EVIDENCE_ITEMS],
        },
    }
    return report


def evaluate_adaptation_source_fidelity(
    **kwargs: Any,
) -> Dict[str, Any]:
    """Evaluate adaptation fidelity and return a bounded gate-facing envelope."""
    report = build_adaptation_source_fidelity_report(**kwargs)
    blockers = list(report["report_agreement"].get("blockers") or [])
    return {
        "status": "blocked" if blockers else ADAPTATION_SOURCE_FIDELITY_STATUS,
        "effective_status": "blocked" if blockers else "pass_through",
        "blocking": bool(blockers),
        "blockers": blockers,
        "source_fidelity_status": ADAPTATION_SOURCE_FIDELITY_STATUS,
        "report": report,
    }


def validate_adaptation_source_fidelity_report(report: Any) -> Dict[str, Any]:
    """Validate the report identity without treating evidence as a gate pass."""
    diagnostics: List[str] = []
    if not isinstance(report, Mapping):
        return {"valid": False, "diagnostics": ["report_must_be_object"]}
    if report.get("contract_version") != ADAPTATION_SOURCE_FIDELITY_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    if report.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        diagnostics.append("adaptation_mode_invalid")
    if report.get("source_fidelity_status") != ADAPTATION_SOURCE_FIDELITY_STATUS:
        diagnostics.append("source_fidelity_status_must_be_not_applicable")
    if report.get("informational") is not True:
        diagnostics.append("informational_marker_missing")
    if not isinstance(report.get("explanation"), str) or not report.get("explanation"):
        diagnostics.append("explanation_missing")
    if not isinstance(report.get("provenance"), Mapping):
        diagnostics.append("provenance_missing")
    freshness = report.get("report_freshness")
    if not isinstance(freshness, Mapping) or freshness.get("state") not in {
        "current",
        "degraded",
    }:
        diagnostics.append("report_freshness_invalid")
    return {"valid": not diagnostics, "diagnostics": diagnostics}


__all__ = [
    "ADAPTATION_MODE_LLM",
    "ADAPTATION_SOURCE_FIDELITY_CONTRACT_VERSION",
    "ADAPTATION_SOURCE_FIDELITY_EXPLANATION",
    "ADAPTATION_SOURCE_FIDELITY_STATUS",
    "build_adaptation_source_fidelity_report",
    "evaluate_adaptation_source_fidelity",
    "validate_adaptation_source_fidelity_report",
]
