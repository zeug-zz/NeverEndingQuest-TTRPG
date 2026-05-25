# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Backstage Agent CLI - Read-Only Audit Runner
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from utils.accurate_ingest_backstage_audit import collect_accurate_ingest_audit_inputs, build_audit_findings


DEFAULT_OUTPUT_BASE = "data/agent_runs/accurate_ingest_audit"


def _parse_json_stdout(stdout: str) -> tuple:
    stripped = stdout.strip()
    if not stripped:
        return ("empty", {})
    try:
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            return ("invalid_json", {})
        return ("ok", parsed)
    except (json.JSONDecodeError, ValueError):
        return ("invalid_json", {})


def _compact_benchmark_summary(parsed: dict) -> dict:
    return {
        "source_fidelity_status": parsed.get("source_fidelity_status"),
        "passed": parsed.get("passed"),
        "degraded": parsed.get("degraded"),
        "blocked": parsed.get("blocked"),
        "module_slug": parsed.get("module_slug"),
        "benchmark_version": parsed.get("benchmark_version"),
    }


def _preview_text(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def run_benchmark_command(module_slug: str, run_dir: Path) -> dict:
    cmd_out_dir = run_dir / "command_outputs" / "benchmark"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "benchmark_accurate_ingest.py"),
        "--module", module_slug,
        "--json",
        "--out", str(cmd_out_dir),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_parse_status": "empty",
            "stderr_preview": "command timed out",
            "parsed_summary": None,
        }
    except Exception as e:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_parse_status": "empty",
            "stderr_preview": str(e),
            "parsed_summary": None,
        }
    parse_status, parsed = _parse_json_stdout(proc.stdout)
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout_parse_status": parse_status,
        "stderr_preview": _preview_text(proc.stderr),
        "parsed_summary": _compact_benchmark_summary(parsed) if parse_status == "ok" else None,
    }


def _compact_publishability_summary(parsed: dict) -> dict:
    gates = parsed.get("publication_gates", {}) or {}
    semantic_audit = gates.get("semantic_audit", {}) or {}
    semantic_probes = gates.get("semantic_probes", {}) or {}
    blocking_errors = parsed.get("blocking_errors") or []
    warnings = parsed.get("warnings") or []
    return {
        "ready_status": parsed.get("ready_status"),
        "publishable_status": parsed.get("publishable_status"),
        "source_fidelity_status": parsed.get("source_fidelity_status"),
        "effective_publishable_status": parsed.get("effective_publishable_status"),
        "exit_code": parsed.get("exit_code"),
        "blocking_error_count": len(blocking_errors),
        "warning_count": len(warnings),
        "semantic_audit_status": semantic_audit.get("status"),
        "semantic_probes_status": semantic_probes.get("status"),
    }


def run_publishability_command(module_slug: str) -> dict:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "audit_module_publishability.py"),
        "--module", module_slug,
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_parse_status": "empty",
            "stderr_preview": "command timed out",
            "parsed_summary": None,
        }
    except Exception as e:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_parse_status": "empty",
            "stderr_preview": str(e),
            "parsed_summary": None,
        }
    parse_status, parsed = _parse_json_stdout(proc.stdout)
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout_parse_status": parse_status,
        "stderr_preview": _preview_text(proc.stderr),
        "parsed_summary": _compact_publishability_summary(parsed) if parse_status == "ok" else None,
    }


def make_task_id() -> str:
    now = datetime.now()
    return now.strftime("audit_%Y%m%d_%H%M%S_%f")


def write_json_atomic(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix=".tmp_",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def counts_by_severity(findings: list) -> dict:
    counts: Counter = Counter()
    for f in findings:
        sev = f.get("severity", "info")
        if sev not in ("blocker", "warning", "info"):
            sev = "info"
        counts[sev] += 1
    return dict(counts)


def collect_evidence_refs(findings: list) -> list:
    seen: set = set()
    refs: list = []
    for f in findings:
        for key in f.get("evidence_keys", []):
            if key not in seen:
                seen.add(key)
                refs.append(key)
    return refs


def _group_findings_by_domain(findings: list) -> dict:
    """Group findings by their domain field."""
    grouped = {}
    for f in findings:
        domain = f.get("domain", "unknown")
        grouped.setdefault(domain, []).append(f)
    return grouped


def _build_report_consistency_summary(findings: list) -> dict:
    """Build a compact summary of report_consistency findings."""
    consistency = [f for f in findings if f.get("domain") == "report_consistency"]
    return {
        "count": len(consistency),
        "blocker_count": sum(1 for f in consistency if f.get("severity") == "blocker"),
        "warning_count": sum(1 for f in consistency if f.get("severity") == "warning"),
        "findings": consistency,
        "evidence_refs": collect_evidence_refs(consistency),
    }


def build_recommendation(findings: list) -> dict:
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    warnings = [f for f in findings if f.get("severity") == "warning"]

    consistency_blockers = [f for f in blockers if f.get("domain") == "report_consistency"]
    presence_blockers = [f for f in blockers if f.get("domain") == "artifact_presence"]
    other_blockers = [f for f in blockers if f.get("domain") not in ("report_consistency", "artifact_presence")]

    evidence_refs = collect_evidence_refs(findings)

    if consistency_blockers:
        return {
            "recommended_action": "investigate_disagreement",
            "reason": f"{len(consistency_blockers)} report-consistency blocker(s) found",
            "evidence_refs": evidence_refs,
        }
    if presence_blockers:
        return {
            "recommended_action": "openspec_work",
            "reason": f"{len(presence_blockers)} artifact-presence blocker(s) found",
            "evidence_refs": evidence_refs,
        }
    if other_blockers:
        return {
            "recommended_action": "repair_artifacts",
            "reason": f"{len(other_blockers)} non-consistency non-presence blocker(s) found",
            "evidence_refs": evidence_refs,
        }
    if warnings:
        return {
            "recommended_action": "review_warnings",
            "reason": f"{len(warnings)} warning(s) found, no blockers",
            "evidence_refs": evidence_refs,
        }

    return {
        "recommended_action": "no_action",
        "reason": "no findings requiring action",
        "evidence_refs": [],
    }


def _build_command_findings(command_name: str, evidence: dict) -> list:
    exit_code = evidence.get("exit_code", -1)
    parse_status = evidence.get("stdout_parse_status", "empty")
    evidence_key = f"commands.{command_name}"

    if parse_status == "ok" and exit_code == 0:
        return []

    if exit_code == -1:
        return [{
            "domain": "command_execution",
            "severity": "blocker",
            "message": f"{command_name} command: stdout_parse_status={parse_status}; exit_code={exit_code}",
            "evidence_keys": [evidence_key],
        }]

    problems = []
    if parse_status != "ok":
        problems.append(f"stdout_parse_status={parse_status}")
    if exit_code != 0:
        problems.append(f"exit_code={exit_code}")

    if parse_status != "ok" and exit_code == 0:
        severity = "warning"
    else:
        severity = "blocker"

    return [{
        "domain": "command_execution",
        "severity": severity,
        "message": f"{command_name} command: {'; '.join(problems)}",
        "evidence_keys": [evidence_key],
    }]


def run_accurate_ingest_audit(
    module_slug: str, output_dir: Path,
    include_benchmark_command: bool = False,
    include_publishability_command: bool = False,
) -> dict:
    module_path = REPO_ROOT / "modules" / module_slug

    collected = collect_accurate_ingest_audit_inputs(str(module_path))

    findings = build_audit_findings(collected)

    task_id = make_task_id()
    run_dir = output_dir / task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    benchmark_evidence = None
    if include_benchmark_command:
        benchmark_evidence = run_benchmark_command(module_slug, run_dir)
        findings.extend(_build_command_findings("benchmark", benchmark_evidence))

    publishability_evidence = None
    if include_publishability_command:
        publishability_evidence = run_publishability_command(module_slug)
        findings.extend(_build_command_findings("publishability", publishability_evidence))

    run_payload = {
        "task_id": task_id,
        "module_slug": module_slug,
        "module_path": str(module_path),
        "output_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": "accurate-ingest-audit",
        "status": "completed",
    }

    evidence_payload = dict(collected)
    commands_dict = {}
    if include_benchmark_command and benchmark_evidence:
        commands_dict["benchmark"] = benchmark_evidence
    if include_publishability_command and publishability_evidence:
        commands_dict["publishability"] = publishability_evidence
    if commands_dict:
        evidence_payload["commands"] = commands_dict

    recommendation = build_recommendation(findings)
    recommendation["task_id"] = task_id
    recommendation["module_slug"] = module_slug

    audit_payload = {
        "task_id": task_id,
        "module_slug": module_slug,
        "finding_count": len(findings),
        "counts_by_severity": counts_by_severity(findings),
        "findings": findings,
        "evidence_refs": collect_evidence_refs(findings),
        "grouped_findings": _group_findings_by_domain(findings),
        "report_consistency_summary": _build_report_consistency_summary(findings),
        "next_step_recommendation": {
            "recommended_action": recommendation.get("recommended_action"),
            "reason": recommendation.get("reason"),
            "evidence_refs": recommendation.get("evidence_refs", []),
        },
    }

    write_json_atomic(run_payload, run_dir / "run.json")
    write_json_atomic(evidence_payload, run_dir / "evidence.json")
    write_json_atomic(audit_payload, run_dir / "audit_report.json")
    write_json_atomic(recommendation, run_dir / "recommendation.json")

    return {
        "task_id": task_id,
        "output_dir": str(run_dir),
        "status": collected.get("status", "completed"),
        "blockers": sum(1 for f in findings if f.get("severity") == "blocker"),
        "warnings": sum(1 for f in findings if f.get("severity") == "warning"),
        "recommended_action": recommendation.get("recommended_action"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run_backstage_agent.py",
        description="NeverEndingQuest backstage agent - read-only audit CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    audit_parser = subparsers.add_parser("accurate-ingest-audit", help="Run accurate-ingest audit for a module")
    audit_parser.add_argument("--module", required=True, help="Module slug (directory name under modules/)")
    audit_parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / DEFAULT_OUTPUT_BASE),
        help=f"Output directory base (default: {DEFAULT_OUTPUT_BASE}/<task_id>/)",
    )
    audit_parser.add_argument(
        "--include-benchmark-command",
        action="store_true",
        default=False,
        help="Run and capture benchmark command evidence",
    )
    audit_parser.add_argument(
        "--include-publishability-command",
        action="store_true",
        default=False,
        help="Run and capture publishability command evidence",
    )

    args = parser.parse_args()

    if args.subcommand == "accurate-ingest-audit":
        module_slug = args.module
        module_path = REPO_ROOT / "modules" / module_slug

        if not module_path.exists() or not module_path.is_dir():
            print(f"Error: module directory not found: {module_path}", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output_dir)
        result = run_accurate_ingest_audit(
            module_slug, output_dir,
            include_benchmark_command=args.include_benchmark_command,
            include_publishability_command=args.include_publishability_command,
        )

        print(
            f"Audit complete: task_id={result['task_id']} | "
            f"output_dir={result['output_dir']} | "
            f"blockers={result['blockers']} warnings={result['warnings']} | "
            f"recommendation={result['recommended_action']}"
        )


if __name__ == "__main__":
    main()
