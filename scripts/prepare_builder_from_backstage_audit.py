#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
"""Builder audit briefing - load, validate, and produce compact builder brief from a backstage audit run."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_ARTIFACTS: List[str] = [
    "run.json",
    "evidence.json",
    "audit_report.json",
    "recommendation.json",
]

TASK_ID_ARTIFACTS: List[str] = [
    "run",
    "audit_report",
    "recommendation",
]


class AuditRunError(Exception):
    """Base exception for audit run loading/validation errors."""


class MissingArtifactError(AuditRunError):
    """Raised when a required audit artifact cannot be found."""


class TaskIdentityError(AuditRunError):
    """Raised when audit artifacts have inconsistent task IDs."""


def load_audit_run_artifacts(run_dir: Path) -> Dict[str, Any]:
    """Load and validate the four required audit artifacts from a run directory.

    Args:
        run_dir: Path to an audit run directory containing run.json, evidence.json,
                 audit_report.json, and recommendation.json.

    Returns:
        Dict with keys: run, evidence, audit_report, recommendation, task_id,
        module_slug, paths.

    Raises:
        MissingArtifactError: If any required artifact is missing.
        TaskIdentityError: If task IDs across required artifacts are inconsistent.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise MissingArtifactError(f"Audit run directory not found: {run_dir}")

    artifacts: Dict[str, Any] = {}
    paths: Dict[str, str] = {}

    for artifact_name in REQUIRED_ARTIFACTS:
        artifact_path = run_dir / artifact_name
        if not artifact_path.is_file():
            raise MissingArtifactError(
                f"Missing required audit artifact: {artifact_name} at {artifact_path}"
            )
        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                key = artifact_name.replace(".json", "")
                artifacts[key] = json.load(f)
                paths[key] = str(artifact_path)
        except json.JSONDecodeError as e:
            raise MissingArtifactError(
                f"Invalid JSON in required artifact {artifact_name}: {e}"
            )

    task_ids: Dict[str, str] = {}
    for key in TASK_ID_ARTIFACTS:
        tid = artifacts[key].get("task_id")
        if not tid:
            raise TaskIdentityError(
                f"Missing task_id field in {key}.json"
            )
        task_ids[key] = tid

    unique_ids = set(task_ids.values())
    if len(unique_ids) != 1:
        raise TaskIdentityError(
            f"Task ID mismatch across audit artifacts: "
            f"run.json task_id={task_ids['run']}, "
            f"audit_report.json task_id={task_ids['audit_report']}, "
            f"recommendation.json task_id={task_ids['recommendation']}"
        )

    task_id = task_ids["run"]
    module_slug = artifacts["run"].get("module_slug", "")

    return {
        "run": artifacts["run"],
        "evidence": artifacts["evidence"],
        "audit_report": artifacts["audit_report"],
        "recommendation": artifacts["recommendation"],
        "task_id": task_id,
        "module_slug": module_slug,
        "paths": paths,
    }


def _grouped_finding_counts(grouped_findings: Dict[str, List]) -> Dict[str, int]:
    """Count findings per domain from grouped_findings dict."""
    return {domain: len(items) for domain, items in grouped_findings.items()}


def _compact_evidence_refs(
    audit_report: Dict[str, Any],
    recommendation: Dict[str, Any],
) -> List[str]:
    """Return ordered unique evidence refs from audit report and recommendation."""
    refs: List[str] = []
    for source_refs in (
        audit_report.get("evidence_refs", []),
        recommendation.get("evidence_refs", []),
    ):
        if not isinstance(source_refs, list):
            continue
        for ref in source_refs:
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref)
    return refs


def _compact_text(value: Any, limit: int = 240) -> str:
    """Return bounded single-line text for compact briefing output."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[:limit - 3].rstrip() + "..."


def _compact_top_findings(
    findings: List[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Return compact top findings without copying full report bodies."""
    compact: List[Dict[str, Any]] = []
    for finding in findings:
        if len(compact) >= limit:
            break
        if not isinstance(finding, dict):
            continue

        evidence_refs = finding.get("evidence_refs", finding.get("evidence_keys", []))
        if not isinstance(evidence_refs, list):
            evidence_refs = []

        compact.append({
            "domain": finding.get("domain", ""),
            "severity": finding.get("severity", ""),
            "message": _compact_text(finding.get("message", "")),
            "evidence_refs": [
                ref for ref in evidence_refs
                if isinstance(ref, str) and ref
            ],
        })
    return compact


LANE_MAPPING: Dict[str, Dict[str, str]] = {
    "investigate_disagreement": {
        "lane": "diagnose_reports",
        "rationale": "Report disagreement detected; investigation needed.",
    },
    "repair_artifacts": {
        "lane": "repair_artifacts",
        "rationale": "Artifact repair required.",
    },
    "openspec_work": {
        "lane": "openspec_work",
        "rationale": "OpenSpec specification work required.",
    },
    "review_warnings": {
        "lane": "review_warnings",
        "rationale": "Non-blocking warnings should be reviewed.",
    },
    "no_action": {
        "lane": "no_action",
        "rationale": "Audit passed; no action required.",
    },
}

_UNKNOWN_LANE: str = "diagnose_reports"
_UNKNOWN_RATIONALE: str = "Unrecognized recommendation; defaulting to diagnosis."


def classify_builder_lane(
    recommended_action: str,
    evidence_refs: List[str],
) -> Dict[str, Any]:
    """Classify builder lane from a recommended action.

    Args:
        recommended_action: The recommended_action string from the audit.
        evidence_refs: Evidence references from the audit (copied into output).

    Returns:
        Dict with keys: builder_lane, builder_lane_rationale, builder_lane_evidence_refs.

    The returned dict is designed to be unpacked into builder_brief.json.
    """
    entry = LANE_MAPPING.get(recommended_action)
    if entry is not None:
        return {
            "builder_lane": entry["lane"],
            "builder_lane_rationale": entry["rationale"],
            "builder_lane_evidence_refs": evidence_refs,
        }
    return {
        "builder_lane": _UNKNOWN_LANE,
        "builder_lane_rationale": _UNKNOWN_RATIONALE,
        "builder_lane_evidence_refs": evidence_refs,
    }


def build_builder_brief(loaded: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact JSON-ready builder brief from loaded audit artifacts.

    Args:
        loaded: Return value from load_audit_run_artifacts().

    Returns:
        Dict suitable for serialization as builder_brief.json.
    """
    audit_report = loaded["audit_report"]
    recommendation = loaded["recommendation"]

    evidence_refs = _compact_evidence_refs(audit_report, recommendation)
    lane_classification = classify_builder_lane(
        recommendation.get("recommended_action", ""),
        evidence_refs,
    )

    return {
        "task_id": loaded["task_id"],
        "module_slug": loaded["module_slug"],
        "audit_output_dir": audit_report.get("output_dir", loaded["run"].get("output_dir", "")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommended_action": recommendation.get("recommended_action"),
        "reason": recommendation.get("reason"),
        "evidence_refs": evidence_refs,
        "finding_count": audit_report.get("finding_count", 0),
        "counts_by_severity": audit_report.get("counts_by_severity", {}),
        "grouped_finding_counts": _grouped_finding_counts(
            audit_report.get("grouped_findings", {})
        ),
        "top_findings": _compact_top_findings(audit_report.get("findings", [])),
        "report_consistency_summary": audit_report.get("report_consistency_summary", {}),
        "source_artifact_paths": dict(loaded["paths"]),
        **lane_classification,
    }


def _write_json_atomic(data: Dict[str, Any], path: Path) -> None:
    """Write a JSON file atomically using a temp file and rename."""
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp = Path(f.name)
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if tmp is not None and tmp.exists():
            tmp.unlink()
        raise


def write_builder_brief_json(run_dir: Path) -> Dict[str, Any]:
    """Load audit run, build a builder brief, and write builder_brief.json.

    Args:
        run_dir: Path to an audit run directory.

    Returns:
        The builder brief dict that was written.

    Raises:
        MissingArtifactError: If required artifacts are missing.
        TaskIdentityError: If task IDs are inconsistent.
    """
    loaded = load_audit_run_artifacts(run_dir)
    brief = build_builder_brief(loaded)
    _write_json_atomic(brief, run_dir / "builder_brief.json")
    return brief


def _lane_text(builder_lane: Any) -> str:
    """Render builder_lane value as display text."""
    if builder_lane is None:
        return "pending"
    return str(builder_lane)


def build_builder_prompt_context(brief: Dict[str, Any]) -> str:
    """Build a compact markdown prompt context string from a builder brief dict.

    Args:
        brief: The builder brief dict (from build_builder_brief or read from
               builder_brief.json).

    Returns:
        Markdown string suitable for builder_prompt_context.md.
    """
    severity_lines = ", ".join(
        f"{k}: {v}" for k, v in brief.get("counts_by_severity", {}).items()
    )
    domain_lines = ", ".join(
        f"{k}: {v}" for k, v in brief.get("grouped_finding_counts", {}).items()
    )
    rec_summary = brief.get("report_consistency_summary", {})
    top_findings = brief.get("top_findings", [])

    lines: List[str] = [
        "# Builder Prompt Context",
        "",
        "## Module Summary",
        "",
        f"- **Module:** {brief.get('module_slug', 'unknown')}",
        f"- **Task:** {brief.get('task_id', 'unknown')}",
        f"- **Audit Output Dir:** {brief.get('audit_output_dir', '')}",
        f"- **Generated:** {brief.get('generated_at', '')}",
        f"- **Builder Lane:** {_lane_text(brief.get('builder_lane'))}",
        f"- **Rationale:** {brief.get('builder_lane_rationale', '')}",
        "",
        "## Recommendation",
        "",
        f"**Action:** {brief.get('recommended_action', 'none')}",
        f"**Reason:** {brief.get('reason', 'none')}",
    ]

    refs = brief.get("evidence_refs", [])
    if refs:
        lines.append(f"**Evidence Refs:** {', '.join(refs)}")

    lines.extend([
        "",
        "## Finding Summary",
        "",
        f"- **Total Findings:** {brief.get('finding_count', 0)}",
        f"- **By Severity:** {severity_lines}",
    ])

    if domain_lines:
        lines.append(f"- **By Domain:** {domain_lines}")

    lines.extend([
        "",
        "## Top Findings",
        "",
    ])

    if isinstance(top_findings, list) and top_findings:
        for finding in top_findings:
            if not isinstance(finding, dict):
                continue
            lines.append(
                f"- **{finding.get('severity', 'unknown')}** "
                f"[{finding.get('domain', 'unknown')}]: "
                f"{finding.get('message', '')}"
            )
            evidence_refs = finding.get("evidence_refs", [])
            if evidence_refs:
                lines.append(f"  - Evidence: {', '.join(evidence_refs)}")
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Report Consistency Summary",
        "",
    ])

    if isinstance(rec_summary, dict):
        for key, value in rec_summary.items():
            if key == "findings" and isinstance(value, list):
                lines.append(f"- **{key}:** {len(value)} entries")
            else:
                lines.append(f"- **{key}:** {value}")

    lines.extend([
        "",
        "## Advisory",
        "",
        "> This brief is advisory and cannot override deterministic gates.",
        "> Evidence references point to source artifacts from the backstage audit run.",
        "",
    ])

    return "\n".join(lines)


def write_builder_prompt_context_md(run_dir: Path) -> str:
    """Load or build a builder brief, emit builder_prompt_context.md, return the markdown text.

    If builder_brief.json already exists in run_dir, it is reused.
    Otherwise the four audit artifacts are loaded and a fresh brief is generated.

    Args:
        run_dir: Path to an audit run directory.

    Returns:
        The markdown text that was written.

    Raises:
        MissingArtifactError: If required artifacts are missing.
        TaskIdentityError: If task IDs are inconsistent.
    """
    brief_path = run_dir / "builder_brief.json"
    if brief_path.is_file():
        with open(brief_path, "r", encoding="utf-8") as f:
            brief = json.load(f)
    else:
        brief = write_builder_brief_json(run_dir)

    md = build_builder_prompt_context(brief)
    (run_dir / "builder_prompt_context.md").write_text(md, encoding="utf-8")
    return md
