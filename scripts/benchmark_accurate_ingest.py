#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Deterministic accurate-ingest benchmark runner.

Compares ingested module artifacts against a benchmark fixture
and reports per-category and aggregate source-fidelity scores.

Zero LLM provider calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_source_fidelity_benchmark import (
    STATUS_PASS,
    STATUS_DEGRADED,
    STATUS_BLOCKED,
    STATUS_UNKNOWN,
    derive_category_status,
    load_benchmark_fixture,
    make_score_result,
    build_aggregate_result,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARKS_DIR = REPO_ROOT / "data" / "benchmarks"
BENCHMARK_FILENAME = "{module_slug}_benchmark.json"
REPORT_FILENAME = "accurate_ingest_benchmark_report.json"


def _load_module_json(module_path: Path, *subpath_parts: str) -> Optional[Dict[str, Any]]:
    target = module_path.joinpath(*subpath_parts)
    if not target.exists() or not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_location_descriptions(module_path: Path) -> List[str]:
    descriptions: List[str] = []
    area_dir = module_path / "areas"
    if not area_dir.is_dir():
        return descriptions
    for area_file in sorted(area_dir.glob("*.json")):
        if area_file.name.endswith("_BU.json"):
            continue
        area_data = _load_module_json(module_path, "areas", area_file.name)
        if area_data is None:
            continue
        for loc in area_data.get("locations", []):
            desc = (loc.get("description") or "").strip()
            if desc:
                descriptions.append(desc)
            name = (loc.get("name") or "").strip()
            if name:
                descriptions.append(f"[LOCATION] {name}")
    return descriptions


def _iter_plot_texts(module_path: Path) -> List[str]:
    texts: List[str] = []
    plot_data = _load_module_json(module_path, "module_plot.json")
    if plot_data:
        for pp in plot_data.get("plotPoints", []):
            desc = (pp.get("description") or "").strip()
            if desc:
                texts.append(desc)
            title = (pp.get("title") or "").strip()
            if title:
                texts.append(title)
            sq = pp.get("sideQuests", []) or []
            for s in sq:
                sd = (s.get("description") or "").strip()
                if sd:
                    texts.append(sd)
    return texts


def _iter_all_module_text(module_path: Path) -> str:
    parts: List[str] = []
    parts.extend(_iter_location_descriptions(module_path))
    parts.extend(_iter_plot_texts(module_path))
    ctx = _load_module_json(module_path, "module_context.json")
    if ctx:
        objective = ctx.get("plotObjective") or ctx.get("mainObjective") or ""
        if objective:
            parts.append(objective)
        for theme in ctx.get("themes", []):
            if isinstance(theme, str):
                parts.append(theme)
    return " ".join(parts)


def _get_thresholds(thresholds: Dict[str, Any], category: str) -> tuple:
    """Extract pass/degraded thresholds for a category from the thresholds dict."""
    pass_val = thresholds.get("pass", {}).get(category, 1.0)
    degraded_val = thresholds.get("degraded", {}).get(category, 1.0)
    return pass_val, degraded_val


def score_npc_preservation(module_path: Path, expectation: Dict[str, Any],
                           pass_threshold: float, degraded_threshold: float) -> Dict[str, Any]:
    source_npcs: List[str] = expectation.get("named_source_npcs", [])
    if not source_npcs:
        return make_score_result("npc_preservation", STATUS_UNKNOWN)
    raw_text = _iter_all_module_text(module_path).lower()
    found_names: List[str] = []
    for npc_name in source_npcs:
        name_lower = npc_name.lower()
        core_name = name_lower.split("(")[0].split(",")[0].strip()
        if core_name in raw_text:
            found_names.append(npc_name)
    actual = len(found_names)
    total = len(source_npcs)
    score = actual / total if total > 0 else 0.0
    details = {
        "total_source_npcs": total, "found_in_module": actual,
        "matched_names": found_names,
        "missing_names": [n for n in source_npcs if n not in found_names],
    }
    status = derive_category_status(score, pass_threshold, degraded_threshold, "npc_preservation")
    return make_score_result("npc_preservation", status, score=score,
                             expected=pass_threshold, actual=f"{actual}/{total}", details=details)


def score_location_preservation(module_path: Path, expectation: Dict[str, Any],
                                pass_threshold: float, degraded_threshold: float) -> Dict[str, Any]:
    source_locs: List[str] = expectation.get("source_locations", [])
    if not source_locs:
        return make_score_result("location_preservation", STATUS_UNKNOWN)
    descriptions = _iter_location_descriptions(module_path)
    combined = " ".join(descriptions).lower()
    allowed_mappings = expectation.get("allowed_mappings", {})
    found_names: List[str] = []
    for loc_name in source_locs:
        name_lower = loc_name.lower()
        if name_lower in combined:
            found_names.append(loc_name)
            continue
        mapped = allowed_mappings.get(loc_name)
        if mapped and mapped.lower() in combined:
            found_names.append(loc_name)
    actual = len(found_names)
    total = len(source_locs)
    score = actual / total if total > 0 else 0.0
    details = {
        "total_source_locations": total, "found_in_module": actual,
        "matched_names": found_names,
        "missing_names": [n for n in source_locs if n not in found_names],
    }
    status = derive_category_status(score, pass_threshold, degraded_threshold, "location_preservation")
    return make_score_result("location_preservation", status, score=score,
                             expected=pass_threshold, actual=f"{actual}/{total}", details=details)


def score_puzzle_preservation(module_path: Path, expectation: Dict[str, Any],
                              pass_threshold: float, degraded_threshold: float) -> Dict[str, Any]:
    required: List[str] = expectation.get("required_puzzles", [])
    if not required:
        return make_score_result("puzzle_preservation", STATUS_UNKNOWN)
    sources: Dict[str, str] = expectation.get("source_descriptions", {})
    combined = _iter_all_module_text(module_path).lower()
    found_puzzles: List[str] = []
    for puzzle_key in required:
        text_hint = sources.get(puzzle_key, puzzle_key).lower()
        words = set(re.sub(r"[^a-z\s]", "", text_hint).split())
        significant = {w for w in words if len(w) > 4}
        if not significant:
            significant = words
        match_count = sum(1 for w in significant if w in combined)
        thresh = max(1, len(significant) // 3)
        if match_count >= thresh:
            found_puzzles.append(puzzle_key)
    actual = len(found_puzzles)
    total = len(required)
    score = actual / total if total > 0 else 0.0
    details = {
        "total_source_puzzles": total, "found_in_module": actual,
        "matched": found_puzzles, "missing": [p for p in required if p not in found_puzzles],
    }
    status = derive_category_status(score, pass_threshold, degraded_threshold, "puzzle_preservation")
    return make_score_result("puzzle_preservation", status, score=score,
                             expected=pass_threshold, actual=f"{actual}/{total}", details=details)


def score_lore_preservation(module_path: Path, expectation: Dict[str, Any],
                            pass_threshold: float, degraded_threshold: float) -> Dict[str, Any]:
    required: List[str] = expectation.get("required_elements", [])
    if not required:
        return make_score_result("lore_preservation", STATUS_UNKNOWN)
    sources: Dict[str, str] = expectation.get("source_descriptions", {})
    combined = _iter_all_module_text(module_path).lower()
    found_elements: List[str] = []
    for element_key in required:
        text_hint = sources.get(element_key, element_key).lower()
        words = set(re.sub(r"[^a-z\s]", "", text_hint).split())
        significant = {w for w in words if len(w) > 4}
        if not significant:
            significant = words
        match_count = sum(1 for w in significant if w in combined)
        thresh = max(1, len(significant) // 3)
        if match_count >= thresh:
            found_elements.append(element_key)
    actual = len(found_elements)
    total = len(required)
    score = actual / total if total > 0 else 0.0
    details = {
        "total_source_lore_elements": total, "found_in_module": actual,
        "matched": found_elements, "missing": [e for e in required if e not in found_elements],
    }
    status = derive_category_status(score, pass_threshold, degraded_threshold, "lore_preservation")
    return make_score_result("lore_preservation", status, score=score,
                             expected=pass_threshold, actual=f"{actual}/{total}", details=details)


def score_tone_preservation(module_path: Path, expectation: Dict[str, Any],
                            pass_threshold: str, degraded_threshold: str) -> Dict[str, Any]:
    expected_tone: str = str(pass_threshold) if pass_threshold else expectation.get("expected_tone", "")
    blocked_replacement: str = str(degraded_threshold) if degraded_threshold else expectation.get("blocked_replacement", "")
    ctx = _load_module_json(module_path, "module_context.json")
    if ctx is None:
        return make_score_result("tone_preservation", STATUS_UNKNOWN)
    classification = ctx.get("classification_metadata", {})
    actual_tone_raw: str = classification.get("tone", "") or ctx.get("module_name", "")
    if not actual_tone_raw:
        descriptions = _iter_location_descriptions(module_path)
        combined = " ".join(descriptions) + " "
        combined += str(ctx.get("plotObjective", ""))
        combined += " ".join(str(t) for t in ctx.get("themes", []))
        actual_tone_raw = combined
    status = derive_category_status(actual_tone_raw, expected_tone, blocked_replacement, "tone_preservation")
    details = {
        "expected_tone": expected_tone, "blocked_replacement": blocked_replacement,
        "actual_tone_sample": actual_tone_raw[:300] if len(actual_tone_raw) > 300 else actual_tone_raw,
    }
    return make_score_result("tone_preservation", status,
                             expected=expected_tone, actual=actual_tone_raw[:100], details=details)


def run_benchmark(module_path: Path, fixture: Dict[str, Any]) -> Dict[str, Any]:
    expectations = fixture.get("expectations", {})
    thresholds = fixture.get("publication_thresholds", {})
    results: List[Dict[str, Any]] = []
    if "npc_preservation" in expectations:
        pt, dt = _get_thresholds(thresholds, "npc_preservation")
        results.append(score_npc_preservation(module_path, expectations["npc_preservation"], pt, dt))
    if "location_preservation" in expectations:
        pt, dt = _get_thresholds(thresholds, "location_preservation")
        results.append(score_location_preservation(module_path, expectations["location_preservation"], pt, dt))
    if "puzzle_preservation" in expectations:
        pt, dt = _get_thresholds(thresholds, "puzzle_preservation")
        results.append(score_puzzle_preservation(module_path, expectations["puzzle_preservation"], pt, dt))
    if "lore_preservation" in expectations:
        pt, dt = _get_thresholds(thresholds, "lore_preservation")
        results.append(score_lore_preservation(module_path, expectations["lore_preservation"], pt, dt))
    if "tone_preservation" in expectations:
        pt, dt = _get_thresholds(thresholds, "tone_preservation")
        results.append(score_tone_preservation(module_path, expectations["tone_preservation"], pt, dt))
    aggr = build_aggregate_result(results)
    aggr["benchmark_version"] = fixture.get("benchmark_version", "unknown")
    aggr["module_slug"] = fixture.get("module_slug", module_path.name)
    aggr["fixture_source_path"] = fixture.get("source_path", "")
    return aggr


def main() -> int:
    parser = argparse.ArgumentParser(description="Accurate-ingest benchmark runner")
    parser.add_argument("--module", default="", help="Module slug (under modules/)")
    parser.add_argument("--benchmark", default="", help="Benchmark fixture path or slug")
    parser.add_argument("--json", action="store_true", default=False, help="Output JSON report to stdout")
    parser.add_argument("--out", default="", help="Output directory for report file")
    args = parser.parse_args()

    if not args.module:
        print('[ERROR] --module is required', file=sys.stderr)
        return 1

    module_slug = args.module
    module_path = REPO_ROOT / "modules" / module_slug
    if not module_path.is_dir():
        print(f'[ERROR] Module directory not found: {module_path}', file=sys.stderr)
        return 1

    if args.benchmark:
        bench_path = Path(args.benchmark)
        if not bench_path.exists():
            bench_path = DEFAULT_BENCHMARKS_DIR / args.benchmark
            if not bench_path.suffix:
                bench_path = bench_path.with_suffix(".json")
        if not bench_path.exists():
            bench_path = DEFAULT_BENCHMARKS_DIR / BENCHMARK_FILENAME.format(module_slug=module_slug)
    else:
        bench_path = DEFAULT_BENCHMARKS_DIR / BENCHMARK_FILENAME.format(module_slug=module_slug)

    if not bench_path.exists():
        print(f"[ERROR] Benchmark fixture not found: {bench_path}", file=sys.stderr)
        return 1

    fixture = load_benchmark_fixture(bench_path)
    if fixture is None:
        print(f"[ERROR] Benchmark fixture failed validation: {bench_path}", file=sys.stderr)
        return 1

    report = run_benchmark(module_path, fixture)

    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = module_path
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / REPORT_FILENAME
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[OK] Benchmark report written to {report_path}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2))

    if report.get("passed"):
        return 0
    elif report.get("degraded"):
        return 1
    elif report.get("blocked"):
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
