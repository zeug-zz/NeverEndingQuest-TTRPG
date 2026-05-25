# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Backstage Audit - Accurate-Ingest Read-Only Audit Input Collector
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPECTED_ARTIFACT_KEYS: Dict[str, str] = {
    "accurate_ingest_benchmark_report": "accurate_ingest_benchmark_report.json",
    "toolkit_build_report": "toolkit_build_report.json",
    "validation_report": "validation_report.json",
    "source_fidelity_report": "source_fidelity_report.json",
    "build_fidelity_report": "build_fidelity_report.json",
}

COMPACT_STATUS_FIELDS: List[str] = [
    "status",
    "ready_status",
    "publishable_status",
    "source_fidelity_status",
    "effective_publishable_status",
    "summary",
    "error",
]

def _compute_file_hash(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest for a file, or None on failure."""
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return None

def _extract_compact_status(data: Any) -> Dict[str, Any]:
    """Extract known compact status fields from parsed JSON data."""
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in COMPACT_STATUS_FIELDS if k in data}

def summarize_report_artifact(path: Path, artifact_key: str) -> Dict[str, Any]:
    """Produce a compact evidence summary for one report artifact.

    Args:
        path: Filesystem path to the report artifact.
        artifact_key: Logical key identifying the artifact type.

    Returns:
        Dict with artifact key, path, exists, parse_status, compact status,
        hash (when exists and computable), and error text (when parse fails).
    """
    summary: Dict[str, Any] = {
        "artifact_key": artifact_key,
        "path": str(path),
        "exists": False,
        "parse_status": "missing",
    }

    if not path.exists():
        return summary

    summary["exists"] = True
    summary["hash"] = _compute_file_hash(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        summary["parse_status"] = "invalid_json"
        summary["error"] = str(e)
        return summary
    except (OSError, PermissionError) as e:
        summary["parse_status"] = "read_error"
        summary["error"] = str(e)
        return summary

    summary["parse_status"] = "ok"
    compact = _extract_compact_status(data)
    if compact:
        summary["compact"] = compact

    return summary

def collect_accurate_ingest_audit_inputs(module_dir: str) -> Dict[str, Any]:
    """Collect accurate-ingest audit input artifacts for a module directory.

    This is a read-only operation that discovers and summarizes existing
    deterministic report artifacts without mutating any files.

    Args:
        module_dir: Filesystem path to the module directory.

    Returns:
        Dict with status ("ok" or "failed"), module_path, collected_at, and
        artifacts list. Each artifact summary is compact; raw report bodies
        are not embedded.
    """
    result: Dict[str, Any] = {
        "status": "ok",
        "module_path": str(module_dir),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [],
    }

    path = Path(module_dir).resolve()

    if not path.exists():
        result["status"] = "failed"
        result["error"] = f"module_directory_not_found:{module_dir}"
        return result

    if not path.is_dir():
        result["status"] = "failed"
        result["error"] = f"module_path_not_a_directory:{module_dir}"
        return result

    for key, filename in EXPECTED_ARTIFACT_KEYS.items():
        artifact_path = path / filename
        summary = summarize_report_artifact(artifact_path, key)
        result["artifacts"].append(summary)

    return result


def _find_artifact_by_key(artifacts: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    """Find an artifact summary by its artifact_key in the artifacts list."""
    for art in artifacts:
        if art.get("artifact_key") == key:
            return art
    return None


def _severity_for_status(status: Optional[str]) -> str:
    """Map a status value to a finding severity."""
    if status is None:
        return "info"
    if status in ("blocked", "fail", "failed", "error"):
        return "blocker"
    if status in ("degraded", "warning"):
        return "warning"
    return "info"


def _build_artifact_presence_findings(artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build findings for missing or unparseable artifacts."""
    findings: List[Dict[str, Any]] = []
    for art in artifacts:
        key = art.get("artifact_key", "unknown")
        if not art.get("exists"):
            findings.append({
                "domain": "artifact_presence",
                "severity": "warning",
                "message": f"Expected artifact '{key}' is missing",
                "evidence_keys": [key],
            })
        elif art.get("parse_status") != "ok":
            error_detail = art.get("error", "unknown error")
            findings.append({
                "domain": "artifact_presence",
                "severity": "blocker",
                "message": f"Expected artifact '{key}' exists but is unparseable: {error_detail}",
                "evidence_keys": [key],
            })
    return findings


def _build_domain_status_finding(
    domain: str, artifact_key: str,
    status_field: str, artifacts: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build a single domain finding from an artifact's compact status field."""
    art = _find_artifact_by_key(artifacts, artifact_key)
    if not art or not art.get("exists") or art.get("parse_status") != "ok":
        return None
    compact_data = art.get("compact", {})
    if not isinstance(compact_data, dict):
        return None
    value = compact_data.get(status_field)
    if value is None:
        return None
    severity = _severity_for_status(str(value))
    return {
        "domain": domain,
        "severity": severity,
        "message": f"{domain}: {status_field}={value}",
        "evidence_keys": [artifact_key],
    }


def _build_validation_finding(artifacts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build validation finding from status or summary compact fields."""
    art = _find_artifact_by_key(artifacts, "validation_report")
    if not art or not art.get("exists") or art.get("parse_status") != "ok":
        return None

    compact_data = art.get("compact", {})
    if not isinstance(compact_data, dict):
        return None

    status = compact_data.get("status")
    if status is not None:
        severity = _severity_for_status(str(status))
        return {
            "domain": "validation",
            "severity": severity,
            "message": f"validation: status={status}",
            "evidence_keys": ["validation_report"],
        }

    summary = compact_data.get("summary")
    if isinstance(summary, dict):
        total_failed = summary.get("total_failed")
        severity = "blocker" if isinstance(total_failed, int) and total_failed > 0 else "info"
        return {
            "domain": "validation",
            "severity": severity,
            "message": f"validation: summary total_failed={total_failed}",
            "evidence_keys": ["validation_report"],
        }

    return None


def _build_report_consistency_findings(artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build findings for cross-artifact report disagreements."""
    findings: List[Dict[str, Any]] = []
    art_by_key: Dict[str, Dict[str, Any]] = {}
    for a in artifacts:
        art_by_key[a.get("artifact_key", "")] = a

    sf_art = art_by_key.get("source_fidelity_report", {})
    bench_art = art_by_key.get("accurate_ingest_benchmark_report", {})
    tb_art = art_by_key.get("toolkit_build_report", {})

    sf_compact = sf_art.get("compact", {}) if isinstance(sf_art.get("compact"), dict) else {}
    bench_compact = bench_art.get("compact", {}) if isinstance(bench_art.get("compact"), dict) else {}
    tb_compact = tb_art.get("compact", {}) if isinstance(tb_art.get("compact"), dict) else {}

    source_key = "source_fidelity_report"
    sf_status = sf_compact.get("source_fidelity_status")
    if sf_status is None:
        source_key = "accurate_ingest_benchmark_report"
        sf_status = bench_compact.get("source_fidelity_status")
    pub_status = tb_compact.get("publishable_status")
    tool_status = tb_compact.get("status")

    if sf_status == "pass" and (pub_status == "fail" or tool_status == "failed"):
        findings.append({
            "domain": "report_consistency",
            "severity": "blocker",
            "message": (
                f"source_fidelity_status=pass but "
                f"publishable_status={pub_status}, tool_status={tool_status}"
            ),
            "evidence_keys": [source_key, "toolkit_build_report"],
        })

    return findings


def build_audit_findings(collection_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build grouped domain findings from a collection result.

    Args:
        collection_result: Output of collect_accurate_ingest_audit_inputs().

    Returns:
        List of finding dicts with domain, severity, message, and evidence_keys.
    """
    findings: List[Dict[str, Any]] = []

    if collection_result.get("status") == "failed":
        error_msg = collection_result.get("error", "unknown failure")
        findings.append({
            "domain": "artifact_presence",
            "severity": "blocker",
            "message": f"Module access failed: {error_msg}",
            "evidence_keys": [],
        })
        return findings

    artifacts = collection_result.get("artifacts", [])

    findings.extend(_build_artifact_presence_findings(artifacts))

    domain_checks = [
        ("source_fidelity", "source_fidelity_report", "source_fidelity_status"),
        ("source_fidelity", "accurate_ingest_benchmark_report", "source_fidelity_status"),
        ("build_fidelity", "build_fidelity_report", "status"),
        ("readiness", "toolkit_build_report", "ready_status"),
        ("semantic_publishability", "toolkit_build_report", "publishable_status"),
        ("semantic_publishability", "toolkit_build_report", "effective_publishable_status"),
    ]

    for domain, artifact_key, field in domain_checks:
        finding = _build_domain_status_finding(domain, artifact_key, field, artifacts)
        if finding:
            findings.append(finding)

    validation_finding = _build_validation_finding(artifacts)
    if validation_finding:
        findings.append(validation_finding)

    findings.extend(_build_report_consistency_findings(artifacts))

    return findings
