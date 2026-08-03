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

import glob
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

BRIEF_VERSION = "accurate_ingest_final_reconciliation_brief.v1"
REPORT_VERSION = "accurate_ingest_final_reconciliation_report.v1"

# Preferred canonical surfaces for final-reconciliation patch targets.
# These are the only module artifact files the LLM final editor may modify:
#
#   module_context.json        -- main context (live, edit-safe)
#   module_context_BU.json     -- context canonical backup
#   module_plot_BU.json        -- plot canonical backup
#   areas/*_BU.json            -- per-area canonical backups
#   map_*.json                 -- static authored map files
#
# Runtime-only files (module_plot.json, live areas/*.json, monsters/*.json),
# source/middle pipeline artifacts (source_graph.json, source_manifest.json,
# normalized_packet.json, blueprint files, backstage audits, agent runs),
# and intermediate build artifacts remain FORBIDDEN patch targets regardless
# of what a brief's editable_surfaces advertises.  The LLM-side
# ``_is_forbidden_target()`` enforces this as a second layer of defense.
DEFAULT_EDITABLE_SURFACES = [
    "module_context.json",
    "module_context_BU.json",
    "module_plot_BU.json",
    "areas/*_BU.json",
    "map_*.json",
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


_MAX_EXCERPT_CHARS = 80
_MAX_EXCERPTS = 20


def _resolve_source_excerpts(
    classification: Dict[str, Any],
    source_graph: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Resolve bounded source excerpts from blocker source_atom_id fields.

    Iterates over editorial_blockers and fatal_blockers, looks up each
    blocker's ``source_atom_id`` in the source graph atom index, and
    returns compact excerpt entries.  Returns ``[]`` when no source_graph
    is provided, no blockers carry a ``source_atom_id``, or no atoms match.

    Args:
        classification: Classifier output dict with blocked lists.
        source_graph: Optional source graph dict with ``atoms`` list.

    Returns:
        List of excerpt dicts with keys: source_atom_id, atom_type, name,
        excerpt.  Bounded by ``_MAX_EXCERPTS`` entries and
        ``_MAX_EXCERPT_CHARS`` per excerpt.
    """
    if source_graph is None:
        return []
    atoms = source_graph.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        return []

    # Build a lookup index: atom id -> atom dict
    atom_index: Dict[str, Dict[str, Any]] = {}
    for atom in atoms:
        atom_id = atom.get("id")
        if atom_id and isinstance(atom_id, str):
            atom_index[atom_id] = atom

    excerpts: List[Dict[str, str]] = []
    blocker_classes = ("editorial_blockers", "fatal_blockers")

    for cls_name in blocker_classes:
        for blocker in classification.get(cls_name, []):
            if len(excerpts) >= _MAX_EXCERPTS:
                break
            source_atom_id = blocker.get("source_atom_id")
            if not source_atom_id or not isinstance(source_atom_id, str):
                continue
            atom = atom_index.get(source_atom_id)
            if atom is None:
                continue
            name = str(atom.get("name", ""))[:_MAX_EXCERPT_CHARS]
            summary = str(atom.get("summary", ""))[:_MAX_EXCERPT_CHARS]
            excerpts.append({
                "source_atom_id": source_atom_id,
                "atom_type": str(atom.get("type", "")),
                "name": name,
                "excerpt": summary,
            })
        if len(excerpts) >= _MAX_EXCERPTS:
            break

    return excerpts


def _build_generated_module_summary(
    module_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a compact summary of canonical module artifacts.

    Scans the module directory for area files, monster files, context,
    and plot artifacts.  Returns bounded counts and short lists only;
    does not embed entire module files.

    Args:
        module_dir: Optional module directory path.

    Returns:
        Compact summary dict with artifact counts and missing categories.
        Returns ``{}`` when module_dir is None or does not exist.
    """
    if module_dir is None or not module_dir.exists():
        return {}

    area_dir = module_dir / "areas"
    monsters_dir = module_dir / "monsters"
    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"

    # Count area BU files (canonical) and live area files
    area_bu_files = sorted(glob.glob(str(area_dir / "*_BU.json"))) if area_dir.is_dir() else []
    area_live_files = []
    if area_dir.is_dir():
        area_live_files = sorted(
            p for p in area_dir.glob("*.json")
            if not p.name.endswith("_BU.json")
        )

    # Count monster files
    monster_files = sorted(glob.glob(str(monsters_dir / "*.json"))) if monsters_dir.is_dir() else []

    # Check context and plot presence
    has_context = context_path.is_file()
    has_plot = plot_path.is_file()

    # Collect missing canonical categories
    missing_categories: List[str] = []
    if not has_context:
        missing_categories.append("module_context")
    if not has_plot:
        missing_categories.append("module_plot")
    if not area_bu_files and not area_live_files:
        missing_categories.append("areas")
    if not monster_files:
        missing_categories.append("monsters")

    return {
        "area_count": len(area_live_files) + len(area_bu_files),
        "area_bu_count": len(area_bu_files),
        "monster_count": len(monster_files),
        "has_module_context": has_context,
        "has_module_plot": has_plot,
        "missing_categories": missing_categories,
    }


def build_final_reconciliation_brief(
    classification: Dict[str, Any],
    job_id: str = "",
    module_name: str = "",
    module_dir: Optional[Path] = None,
    source_graph: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a final reconciliation brief dict from classifier output.

    The brief describes editorial blockers and surfaces that may need
    manual review before final reconciliation is accepted.

    When ``source_graph`` is supplied, ``source_excerpts`` is populated
    by resolving blocker ``source_atom_id`` fields against the source
    graph atom index.  When ``module_dir`` points to an existing module
    directory, ``generated_module_summary`` is populated with compact
    canonical artifact counts.

    Args:
        classification: Classifier output dict from classify_final_build_blockers()
        job_id: Optional job identifier
        module_name: Optional module name/slug
        module_dir: Optional module directory path
        source_graph: Optional source graph dict for evidence enrichment

    Returns:
        Brief dict ready for persistence or downstream consumption
    """
    module_dir_str = str(module_dir) if module_dir is not None else ""
    classification = _normalize_classification(classification)

    trigger = "editorial_blockers_present" if classification.get("editorial_count", 0) > 0 else "no_editorial_blockers"

    # Evidence enrichment
    source_excerpts = _resolve_source_excerpts(classification, source_graph)
    generated_module_summary = _build_generated_module_summary(module_dir)

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
        "source_excerpts": source_excerpts,
        "generated_module_summary": generated_module_summary,
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
