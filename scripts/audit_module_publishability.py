#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Standalone publishability audit layered over readiness and publication semantics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_module_readiness import audit_module_readiness
from scripts.module_semantic_authority_audit import audit_module_semantic_authority
from scripts.module_semantic_probe_harness import run_module_semantic_probes

try:
    from utils.enhanced_logger import warning
except ImportError:
    warning = None

# Feature flag import (fail-open: default to True)
try:
    from model_config import ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK
except ImportError:
    ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK = True


def _load_source_fidelity_status(module_path: Path) -> Dict[str, Any]:
    """Load source-fidelity status with precedence.

    Priority:
    1. module-level source_fidelity_report.json
    2. module-level accurate_ingest_benchmark_report.json
    3. synthetic unknown (legacy/default)
    """
    # Priority 1: Final module-level source-fidelity report
    # If it exists but is invalid, degrade to unknown -- do not fall through
    # to stale benchmark.
    final_report = module_path / "source_fidelity_report.json"
    if final_report.exists():
        try:
            with open(final_report, "r") as f:
                report = json.load(f)
            if isinstance(report, dict):
                return {
                    "source_fidelity_status": str(report.get("source_fidelity_status", "unknown") or "unknown"),
                    "category_results": list(report.get("categories", [])),
                }
        except Exception:
            if warning:
                warning(
                    f"SOURCE_FIDELITY: Invalid source_fidelity_report.json at {final_report} -- degrading to unknown",
                    category="validation",
                )
        else:
            if warning:
                warning(
                    f"SOURCE_FIDELITY: source_fidelity_report.json at {final_report} is not a dict -- degrading to unknown",
                    category="validation",
                )
        return {"source_fidelity_status": "unknown", "category_results": []}

    # Priority 2: Benchmark-specific report
    report_file = module_path / "accurate_ingest_benchmark_report.json"
    if not report_file.exists():
        return {"source_fidelity_status": "unknown", "category_results": []}
    try:
        with open(report_file, "r") as f:
            report = json.load(f)
        if not isinstance(report, dict):
            return {"source_fidelity_status": "unknown", "category_results": []}
        return {
            "source_fidelity_status": str(report.get("source_fidelity_status", "unknown") or "unknown"),
            "category_results": list(report.get("category_results", [])),
        }
    except Exception:
        return {"source_fidelity_status": "unknown", "category_results": []}


# Lazy import for gate composer to avoid circular imports at module level
_GATE_COMPOSER = None

_SOURCE_FIDELITY_REPORT_VERSION = "source_fidelity_report.v1"


def _build_source_fidelity_report_artifact(
    module_slug: str,
    module_path: Path,
    publishability_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a compact module-level source_fidelity_report.json payload.

    Args:
        module_slug: Module slug (e.g. The_Hidden_City_of_Numillian).
        module_path: Resolved module Path.
        publishability_report: The full output of audit_module_publishability().

    Returns:
        Dict suitable for writing to modules/<slug>/source_fidelity_report.json.
    """
    fidelity = publishability_report.get("source_fidelity_status", "unknown")
    categories = publishability_report.get("source_fidelity_categories", [])

    return {
        "report_version": _SOURCE_FIDELITY_REPORT_VERSION,
        "module_slug": module_slug,
        "module_path": str(module_path),
        "source_fidelity_status": str(fidelity or "unknown"),
        "categories": list(categories) if isinstance(categories, list) else [],
    }

def _get_gate_composer():
    global _GATE_COMPOSER
    if _GATE_COMPOSER is None:
        from utils.toolkit_publication_gate_composer import compose_publishability_from_report
        _GATE_COMPOSER = compose_publishability_from_report
    return _GATE_COMPOSER


def _resolve_module_path(module: str = "", module_path: str = "") -> Path:
    """Resolve module path from slug or explicit path."""
    if module_path:
        return Path(module_path)
    if module:
        return Path("modules") / module
    raise ValueError("Provide --module or --module-path")


def _build_fix_list(
    readiness_report: Dict[str, Any],
    semantic_audit: Dict[str, Any],
    semantic_probes: Dict[str, Any],
) -> List[str]:
    """Generate deterministic fix guidance for non-publishable modules."""
    fixes: List[str] = list(readiness_report.get("fix_list", []))

    semantic_audit_has_blocking = bool(semantic_audit.get("blocking_errors") or [])
    semantic_probes_has_blocking = bool(semantic_probes.get("blocking_errors") or [])

    if semantic_audit_has_blocking:
        fixes.append(
            "Fix semantic publication audit findings from scripts/module_semantic_authority_audit.py"
        )
    elif semantic_audit.get("status") != "pass":
        fixes.append(
            "Review semantic audit warnings/tooling debt and remediate if needed"
        )

    if semantic_probes_has_blocking:
        fixes.append(
            "Fix semantic probe harness findings from scripts/module_semantic_probe_harness.py"
        )
    elif semantic_probes.get("status") != "pass":
        fixes.append(
            "Review semantic probe warnings/tooling debt and remediate if needed"
        )

    readiness_toolkit_policy = readiness_report.get("toolkit_media_policy", {})
    if isinstance(readiness_toolkit_policy, dict):
        debt_count = int(readiness_toolkit_policy.get("structural_media_debt_count") or 0)
        if debt_count > 0:
            fixes.append(
                "Manual toolkit remediation required: Monster Management & Generator -> Generate Monster Images"
            )
            fixes.append(
                "Optional batch remediation: Module Media Generator -> one-click monster media generation"
            )

    deduped: List[str] = []
    seen = set()
    for item in fixes:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _collect_remediation_categories(
    *,
    source: str,
    readiness_report: Dict[str, Any],
    semantic_audit: Dict[str, Any],
    semantic_probes: Dict[str, Any],
    combined_blocking_errors: List[str],
    combined_warnings: List[str],
) -> List[str]:
    """Classify remediation paths for deterministic operator follow-up."""
    categories: List[str] = []

    readiness_gates = readiness_report.get("gates", {})
    sidecar_gate = readiness_gates.get("sidecar", {})
    sidecar_reason = str(sidecar_gate.get("reason", "") or "")

    if source == "toolkit" and sidecar_reason == "toolkit_provenance_missing":
        categories.append("provenance_ordering_bug")

    if (
        (source == "watcher" and sidecar_reason == "sidecar_missing")
        or (source == "toolkit" and sidecar_reason == "toolkit_provenance_module_mismatch")
        or (source == "toolkit" and sidecar_reason == "toolkit_provenance_invalid_shape")
    ):
        categories.append("legacy_provenance_gap")

    lowered_blocking = [str(item or "").lower() for item in combined_blocking_errors]
    lowered_warnings = [str(item or "").lower() for item in combined_warnings]

    if any(
        (
            "missing base media files" in item
            or "media/monsters" in item
            or "gameplay_gate_failed" in item
        )
        for item in lowered_blocking
    ):
        categories.append("structured_monster_media_missing")
        if source == "toolkit":
            categories.append("toolkit_manual_media_generation_required")

    readiness_toolkit_policy = readiness_report.get("toolkit_media_policy", {})
    readiness_media_debt_count = 0
    if isinstance(readiness_toolkit_policy, dict):
        readiness_media_debt_count = int(
            readiness_toolkit_policy.get("structural_media_debt_count") or 0
        )
    if readiness_media_debt_count > 0:
        categories.append("structured_monster_media_missing")
        if source == "toolkit":
            categories.append("toolkit_manual_media_generation_required")

    semantic_audit_has_blocking = bool(semantic_audit.get("blocking_errors") or [])
    semantic_probes_has_blocking = bool(semantic_probes.get("blocking_errors") or [])
    semantic_has_blocking = semantic_audit_has_blocking or semantic_probes_has_blocking

    if semantic_has_blocking:
        categories.append("semantic_publishability_blocking")

    if not semantic_has_blocking and (
        semantic_audit.get("status") != "pass" or semantic_probes.get("status") != "pass"
    ):
        categories.append("semantic_warning_only")

    if any(
        (
            "fixture_missing" in item
            or "probe_fixture" in item
            or "tooling debt" in item
            or "tooling_debt" in item
        )
        for item in lowered_warnings
    ):
        categories.append("semantic_tooling_debt")

    if (
        "structured_monster_media_missing" in categories
        and semantic_has_blocking
    ):
        categories.append("mixed_media_semantic_blocking")

    if (
        "structured_monster_media_missing" in categories
        and "semantic_warning_only" in categories
    ):
        categories.append("scene_entity_modeling_candidate")

    deduped: List[str] = []
    seen = set()
    for item in categories:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def audit_module_publishability(
    module_slug: str, module_path: str = "", source: str = "watcher"
) -> Dict[str, Any]:
    """Audit one module for layered readiness and publishability."""
    resolved_module_path = _resolve_module_path(
        module=module_slug, module_path=module_path
    )
    resolved_slug = module_slug or resolved_module_path.name

    readiness_report = audit_module_readiness(resolved_slug, source=source)
    semantic_audit = audit_module_semantic_authority(resolved_module_path)
    semantic_probes = run_module_semantic_probes(resolved_module_path)

    normalized_source = str(source or "watcher").strip().lower()
    ready_status = str(readiness_report.get("overall_status", "fail") or "fail")

    semantic_audit_blocking: List[str] = list(semantic_audit.get("blocking_errors", []))
    semantic_probe_blocking: List[str] = list(semantic_probes.get("blocking_errors", []))
    semantic_has_blocking = bool(semantic_audit_blocking or semantic_probe_blocking)

    blocking_errors: List[str] = []
    if ready_status != "pass":
        blocking_errors.append(
            "readiness_gate_failed: module is not structurally ready"
        )
    blocking_errors.extend(semantic_audit_blocking)
    blocking_errors.extend(semantic_probe_blocking)

    publishable_pass = ready_status == "pass" and not semantic_has_blocking
    publishable_status = "pass" if publishable_pass else "fail"

    warnings: List[str] = []
    warnings.extend(semantic_audit.get("warnings", []))
    warnings.extend(semantic_probes.get("warnings", []))

    remediation_categories = _collect_remediation_categories(
        source=normalized_source,
        readiness_report=readiness_report,
        semantic_audit=semantic_audit,
        semantic_probes=semantic_probes,
        combined_blocking_errors=blocking_errors,
        combined_warnings=warnings,
    )

    # Source-fidelity integration
    fidelity = _load_source_fidelity_status(resolved_module_path)
    source_fidelity_status = fidelity.get("source_fidelity_status", "unknown")
    category_results = fidelity.get("category_results", [])

    compose = _get_gate_composer()
    gate = compose(
        ready_status=ready_status,
        publishable_status=publishable_status,
        source_fidelity_status=source_fidelity_status,
        enable_fidelity_flag=ENABLE_ACCURATE_INGEST_FINAL_BENCHMARK,
    )

    # Only surface fidelity warnings/blockers if fidelity is meaningful
    if source_fidelity_status not in ("unknown", "pass"):
        for w in gate.get("source_fidelity_warnings", []):
            if w not in warnings:
                warnings.append(w)
        for b in gate.get("source_fidelity_blockers", []):
            if b not in blocking_errors:
                blocking_errors.append(b)

    # Determine effective publishable status including fidelity
    effective_publishable = gate.get("final_publishable_status", "unknown")

    return {
        "module": resolved_slug,
        "module_path": str(resolved_module_path),
        "source": normalized_source,
        "ready_status": ready_status,
        "publishable_status": publishable_status,
        "source_fidelity_status": source_fidelity_status,
        "source_fidelity_categories": category_results,
        "effective_publishable_status": effective_publishable,
        "readiness": readiness_report,
        "publication_gates": {
            "semantic_audit": semantic_audit,
            "semantic_probes": semantic_probes,
        },
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "remediation_categories": remediation_categories,
        "toolkit_media_policy": readiness_report.get("toolkit_media_policy", {}),
        "fix_list": _build_fix_list(readiness_report, semantic_audit, semantic_probes),
        "exit_code": 0 if effective_publishable == "pass" else 1,
    }


def _print_text_report(report: Dict[str, Any]) -> None:
    """Emit human-readable layered readiness/publishability report."""
    print("=" * 70)
    print("NEQ MODULE PUBLISHABILITY AUDIT")
    print("=" * 70)
    print(f"module: {report.get('module')}")
    print(f"ready_status: {report.get('ready_status')}")
    print(f"publishable_status: {report.get('publishable_status')}")
    print(f"source_fidelity_status: {report.get('source_fidelity_status', 'unknown')}")
    print("")

    readiness = report.get("readiness", {})
    print(f"readiness.overall_status: {readiness.get('overall_status')}")
    publication_gates = report.get("publication_gates", {})
    print(
        f"semantic_audit: {publication_gates.get('semantic_audit', {}).get('status')}"
    )
    print(
        f"semantic_probes: {publication_gates.get('semantic_probes', {}).get('status')}"
    )

    if report.get("blocking_errors"):
        print("\nblocking_errors:")
        for item in report["blocking_errors"]:
            print(f"- {item}")

    if report.get("fix_list"):
        print("\nfix_list:")
        for item in report["fix_list"]:
            print(f"- {item}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Audit module publishability")
    parser.add_argument("--module", default="", help="Module slug (under modules/)")
    parser.add_argument("--module-path", default="", help="Explicit module path")
    parser.add_argument(
        "--source",
        default="watcher",
        help="Readiness provenance source: watcher or toolkit",
    )
    parser.add_argument(
        "--json", action="store_true", default=False, help="Output JSON report"
    )
    args = parser.parse_args()

    try:
        report = audit_module_publishability(
            module_slug=args.module,
            module_path=args.module_path,
            source=args.source,
        )
    except ValueError as exc:
        report = {
            "ready_status": "fail",
            "publishable_status": "fail",
            "source_fidelity_status": "unknown",
            "blocking_errors": [str(exc)],
            "warnings": [],
            "fix_list": [],
            "exit_code": 1,
        }
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"[ERROR] {exc}")
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text_report(report)

    return int(report.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
