# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Final Reconciliation
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

BRIEF_VERSION = "accurate_ingest_final_reconciliation_brief.v1"
REPORT_VERSION = "accurate_ingest_final_reconciliation_report.v1"

DEFAULT_EDITABLE_SURFACES = [
    "module_context.json",
    "module_plot.json",
    "areas/",
    "monsters/",
]

DEFAULT_INSTRUCTIONS = (
    "Editorial blockers indicate source-fidelity mismatches that do not prevent "
    "module playability. Review the blockers below and either accept reconciliation "
    "or return to fix the source fidelity gaps. Accepted reconciliation records "
    "effective status as reconciled_degraded with playable publication candidate."
)


def _normalize_classification(classification: Any) -> Dict[str, Any]:
    """Normalize classification input, returning a safe fallback for malformed input."""
    if not isinstance(classification, dict):
        return {
            "status": "unknown",
            "fatal_blockers": [],
            "editorial_blockers": [],
            "warnings": [{
                "type": "invalid_classification",
                "message": f"classification is not a dict: {type(classification).__name__}",
                "category": "input_validation",
            }],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 0,
            "editorial_count": 0,
            "original_refusal_reason": "",
            "report_paths": {},
        }
    return classification


def build_final_reconciliation_brief(
    classification: Dict[str, Any],
    job_id: str = "",
    module_name: str = "",
    module_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a final reconciliation brief dict from classifier output.

    The brief describes editorial blockers and surfaces that may need
    manual review before final reconciliation is accepted.

    Args:
        classification: Classifier output dict from classify_final_build_blockers()
        job_id: Optional job identifier
        module_name: Optional module name/slug
        module_dir: Optional module directory path

    Returns:
        Brief dict ready for persistence or downstream consumption
    """
    module_dir_str = str(module_dir) if module_dir is not None else ""
    classification = _normalize_classification(classification)

    trigger = "editorial_blockers_present" if classification.get("editorial_count", 0) > 0 else "no_editorial_blockers"

    return {
        "version": BRIEF_VERSION,
        "job_id": job_id,
        "module_name": module_name,
        "module_dir": module_dir_str,
        "trigger": trigger,
        "classification_status": classification.get("status", "unknown"),
        "editorial_blockers": classification.get("editorial_blockers", []),
        "fatal_blockers": classification.get("fatal_blockers", []),
        "warnings": classification.get("warnings", []),
        "original_refusal_reason": classification.get("original_refusal_reason", ""),
        "report_paths": classification.get("report_paths", {}),
        "source_excerpts": [],
        "generated_module_summary": {},
        "editable_surfaces": list(DEFAULT_EDITABLE_SURFACES),
        "instructions": DEFAULT_INSTRUCTIONS,
    }


def build_final_reconciliation_report(
    classification: Dict[str, Any],
    accepted_reconciliation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a final reconciliation report dict from classifier output.

    Determines reconciliation status and playable publication candidacy
    based on blocker classification and optionally accepted reconciliation.

    Args:
        classification: Classifier output dict from classify_final_build_blockers()
        accepted_reconciliation: Optional accepted reconciliation fixture

    Returns:
        Report dict with reconciliation status and effective source-fidelity status
    """
    classification = _normalize_classification(classification)
    status = classification.get("status", "unknown")
    fatal_count = classification.get("fatal_count", 0)
    editorial_count = classification.get("editorial_count", 0)
    has_accepted = accepted_reconciliation is not None

    # Determine reconciliation status and effective fields
    if status == "unknown":
        report_status = "failed"
        reconciliation_status = "invalid_classification"
        source_fidelity_effective_status = "blocked"
        playable_publication_candidate = False
    elif status in ("fatal", "mixed"):
        report_status = "blocked" if fatal_count > 0 else "failed"
        reconciliation_status = "not_applicable"
        source_fidelity_effective_status = "blocked"
        playable_publication_candidate = False
    elif status == "editorial":
        if has_accepted:
            report_status = "accepted"
            reconciliation_status = "accepted"
            source_fidelity_effective_status = "reconciled_degraded"
            playable_publication_candidate = True
        else:
            report_status = "required"
            reconciliation_status = "pending"
            source_fidelity_effective_status = "blocked"
            playable_publication_candidate = False
    elif status == "no_blockers":
        report_status = "not_required"
        reconciliation_status = "not_required"
        source_fidelity_effective_status = "pass"
        playable_publication_candidate = True
    else:
        report_status = "failed"
        reconciliation_status = "invalid_classification"
        source_fidelity_effective_status = "blocked"
        playable_publication_candidate = False

    decisions = []
    if has_accepted:
        decisions.append("accepted_final_reconciliation")

    return {
        "version": REPORT_VERSION,
        "status": report_status,
        "reconciliation_status": reconciliation_status,
        "source_fidelity_effective_status": source_fidelity_effective_status,
        "playable_publication_candidate": playable_publication_candidate,
        "decisions": decisions,
        "validation_after_reconciliation": {},
        "publishability_after_reconciliation": {},
        "report_agreement_after_reconciliation": {},
        "notes": [],
    }


def should_persist_final_reconciliation_brief(classification: Any) -> bool:
    """Determine whether a final reconciliation brief should be persisted.

    True only when classification is editorial-only with no fatal blockers
    and reconciliation is possible.

    Args:
        classification: Classifier output dict or malformed input

    Returns:
        True if a brief should be persisted, False otherwise
    """
    classification = _normalize_classification(classification)
    return (
        classification.get("status") == "editorial"
        and classification.get("fatal_count", 0) == 0
        and classification.get("editorial_count", 0) > 0
        and classification.get("can_attempt_final_reconciliation", False)
    )


def persist_final_reconciliation_brief(
    workspace_dir: Path,
    brief: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist a final reconciliation brief to the workspace.

    Writes final_reconciliation_brief.json atomically using a temp-file +
    replace strategy.

    Args:
        workspace_dir: Directory to write the brief into
        brief: Brief dict from build_final_reconciliation_brief()

    Returns:
        Result dict with status, path, bytes, and optional error
    """
    target_path = workspace_dir / "final_reconciliation_brief.json"

    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json",
            prefix=".tmp_final_reconciliation_brief_",
            dir=str(workspace_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(brief, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(target_path))
            written_bytes = target_path.stat().st_size
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return {
            "status": "written",
            "path": str(target_path),
            "bytes": written_bytes,
            "error": None,
        }
    except Exception as e:
        return {
            "status": "failed",
            "path": str(target_path),
            "bytes": 0,
            "error": str(e),
        }


def persist_final_reconciliation_report(
    workspace_dir: Path,
    report: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist a final reconciliation report to the workspace.

    Writes final_reconciliation_report.json atomically via tempfile + os.replace.

    Args:
        workspace_dir: Directory to write the report into
        report: Report dict from build_final_reconciliation_report()

    Returns:
        Result dict with status, path, bytes, and optional error
    """
    target_path = workspace_dir / "final_reconciliation_report.json"

    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json",
            prefix=".tmp_final_reconciliation_report_",
            dir=str(workspace_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(target_path))
            written_bytes = target_path.stat().st_size
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return {
            "status": "written",
            "path": str(target_path),
            "bytes": written_bytes,
            "error": None,
        }
    except Exception as e:
        return {
            "status": "failed",
            "path": str(target_path),
            "bytes": 0,
            "error": str(e),
        }


def load_final_reconciliation_report(workspace_dir: Path) -> Optional[Dict[str, Any]]:
    """Load final_reconciliation_report.json from workspace if present.
    
    Returns None if missing, malformed, or unreadable.
    """
    path = workspace_dir / "final_reconciliation_report.json"
    try:
        if not path.exists() or not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)
        if not isinstance(report, dict):
            return None
        return report
    except Exception:
        return None


def is_final_reconciliation_accepted(report: Dict[str, Any]) -> bool:
    """Check whether a final reconciliation report is in accepted state.
    
    Returns True only when report.status == "accepted" and
    reconciliation_status == "accepted" and source_fidelity_effective_status
    == "reconciled_degraded" and playable_publication_candidate is True.
    """
    if not isinstance(report, dict):
        return False
    return (
        report.get("status") == "accepted"
        and report.get("reconciliation_status") == "accepted"
        and report.get("source_fidelity_effective_status") == "reconciled_degraded"
        and report.get("playable_publication_candidate") is True
    )
