# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Source Fidelity Benchmark
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic benchmark fixture contract and scoring for
accurate-ingest source fidelity measurement.

This module is provider-agnostic and contains no LLM calls.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.enhanced_logger import debug, error, info, warning

# Status constants used for both per-category and aggregate results.
STATUS_PASS = "pass"
STATUS_DEGRADED = "degraded"
STATUS_BLOCKED = "blocked"
STATUS_UNKNOWN = "unknown"

VALID_STATUSES = frozenset({STATUS_PASS, STATUS_DEGRADED, STATUS_BLOCKED, STATUS_UNKNOWN})

# Status precedence: blocked > degraded > pass > unknown
_PRECEDENCE: Dict[str, int] = {
    STATUS_BLOCKED: 0,
    STATUS_DEGRADED: 1,
    STATUS_PASS: 2,
    STATUS_UNKNOWN: 3,
}

# Required fixture top-level keys.
_REQUIRED_FIXTURE_KEYS = frozenset({
    "benchmark_version",
    "module_slug",
    "expectations",
    "publication_thresholds",
})

# Required expectation category keys.
_REQUIRED_EXPECTATION_KEYS = frozenset({
    "npc_preservation",
    "location_preservation",
    "puzzle_preservation",
    "lore_preservation",
    "tone_preservation",
})

# Required publication threshold keys.
_REQUIRED_THRESHOLD_KEYS = frozenset({
    "pass",
    "degraded",
})

# Per-category field names within thresholds.
_THRESHOLD_CATEGORY_KEYS = frozenset({
    "npc_preservation",
    "location_preservation",
    "puzzle_preservation",
    "lore_preservation",
    "tone_preservation",
})


def worst_status(*statuses: str) -> str:
    """Return the worst (most severe) status from precedence ordering.

    Args:
        *statuses: One or more status strings (pass, degraded, blocked, unknown).

    Returns:
        The most severe status present. Unknown is least severe.

    Raises:
        ValueError: If any status is not a valid status constant.
    """
    if not statuses:
        return STATUS_UNKNOWN
    for s in statuses:
        if s not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {s}")
    worst = STATUS_UNKNOWN
    for s in statuses:
        if _PRECEDENCE.get(s, 3) < _PRECEDENCE.get(worst, 3):
            worst = s
    return worst


def _validate_is_number(value: Any, path: str) -> Optional[str]:
    """Validate that value is a number (int or float) in range [0, 1]."""
    if not isinstance(value, (int, float)):
        return f"{path}: expected number, got {type(value).__name__}"
    if value < 0 or value > 1:
        return f"{path}: expected value in [0, 1], got {value}"
    return None


def validate_benchmark_fixture(fixture: Dict[str, Any]) -> List[str]:
    """Validate benchmark fixture structure and values.

    Returns a list of error messages. An empty list means the fixture is valid.
    """
    errors: List[str] = []

    # Top-level keys
    for key in _REQUIRED_FIXTURE_KEYS:
        if key not in fixture:
            errors.append(f"Missing required top-level key: {key}")

    if not errors and "expectations" in fixture:
        expectations = fixture["expectations"]
        if not isinstance(expectations, dict):
            errors.append("expectations: expected dict")
        else:
            for key in _REQUIRED_EXPECTATION_KEYS:
                if key not in expectations:
                    errors.append(f"expectations: missing required category: {key}")

    if not errors and "publication_thresholds" in fixture:
        thresholds = fixture["publication_thresholds"]
        if not isinstance(thresholds, dict):
            errors.append("publication_thresholds: expected dict")
        else:
            for key in _REQUIRED_THRESHOLD_KEYS:
                if key not in thresholds:
                    errors.append(f"publication_thresholds: missing required key: {key}")
            for level_key in _REQUIRED_THRESHOLD_KEYS:
                level = thresholds.get(level_key)
                if not isinstance(level, dict):
                    if level_key in thresholds:
                        errors.append(f"publication_thresholds.{level_key}: expected dict")
                    continue
                for cat_key in _THRESHOLD_CATEGORY_KEYS:
                    val = level.get(cat_key)
                    if val is None:
                        errors.append(
                            f"publication_thresholds.{level_key}: missing {cat_key}"
                        )
                    elif cat_key == "tone_preservation":
                        if not isinstance(val, str):
                            errors.append(
                                f"publication_thresholds.{level_key}.{cat_key}: "
                                f"expected string, got {type(val).__name__}"
                            )
                    else:
                        err = _validate_is_number(
                            val,
                            f"publication_thresholds.{level_key}.{cat_key}",
                        )
                        if err:
                            errors.append(err)

    # Validate the thresholds level key order: pass must be <= degraded numerically
    # for categories that use numbers.
    if not errors and "publication_thresholds" in fixture:
        thresholds = fixture["publication_thresholds"]
        pass_level = thresholds.get("pass", {})
        degraded_level = thresholds.get("degraded", {})
        for cat_key in ("npc_preservation", "location_preservation",
                        "puzzle_preservation", "lore_preservation"):
            pv = pass_level.get(cat_key)
            dv = degraded_level.get(cat_key)
            if isinstance(pv, (int, float)) and isinstance(dv, (int, float)):
                if pv >= dv:
                    pass
                else:
                    errors.append(
                        f"publication_thresholds: pass.{cat_key} ({pv}) "
                        f"must be >= degraded.{cat_key} ({dv})"
                    )

    return errors


def load_benchmark_fixture(path: Path) -> Optional[Dict[str, Any]]:
    """Load and validate a benchmark fixture JSON file.

    Returns the parsed fixture dict, or None if the file is missing,
    unreadable, or fails validation. Errors are logged.
    """
    if not path.exists() or not path.is_file():
        debug(f"BENCHMARK: Fixture not found: {path}", category="module_ingest")
        return None

    try:
        raw = path.read_text(encoding="utf-8")
        fixture = json.loads(raw)
    except Exception as exc:
        error(f"BENCHMARK: Failed to read fixture {path}: {exc}", category="module_ingest")
        return None

    if not isinstance(fixture, dict):
        error(f"BENCHMARK: Fixture {path} is not a JSON object", category="module_ingest")
        return None

    validation_errors = validate_benchmark_fixture(fixture)
    if validation_errors:
        for err in validation_errors:
            error(f"BENCHMARK: Fixture validation error: {err}", category="module_ingest")
        return None

    return fixture


# -- Per-category scoring result shape --

_SCORE_RESULT_KEYS = frozenset({
    "category",
    "status",
    "score",
    "expected",
    "actual",
    "details",
})


def make_score_result(
    category: str,
    status: str,
    score: Optional[float] = None,
    expected: Any = None,
    actual: Any = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic per-category score result dict.

    Args:
        category: Category name (e.g. npc_preservation).
        status: pass, degraded, blocked, or unknown.
        score: Numeric score 0.0 to 1.0 (None for unknown/tone).
        expected: The expected threshold value.
        actual: The actual measured value.
        details: Optional additional metadata dict.

    Returns:
        A dict with standardised score result keys.
    """
    return {
        "category": category,
        "status": status,
        "score": score,
        "expected": expected,
        "actual": actual,
        "details": details or {},
    }


def derive_category_status(
    actual_value: Any,
    pass_threshold: Any,
    degraded_threshold: Any,
    category_key: str,
) -> str:
    """Derive deterministic category status from actual vs threshold values.

    Args:
        actual_value: The measured value for this category.
        pass_threshold: The threshold required for pass status.
        degraded_threshold: The threshold required for degraded status.
        category_key: Category name for tone-specific handling.

    Returns:
        pass, degraded, or blocked.
    """
    # Tone category uses string matching
    if category_key == "tone_preservation":
        expected_tone = str(pass_threshold or "").strip().lower()
        actual_tone = str(actual_value or "").strip().lower()
        if actual_tone == expected_tone:
            return STATUS_PASS
        blocked_tone = str(degraded_threshold or "").strip().lower()
        if actual_tone == blocked_tone:
            return STATUS_BLOCKED
        return STATUS_DEGRADED

    # Numeric categories
    try:
        actual_float = float(actual_value) if actual_value is not None else None
    except (TypeError, ValueError):
        return STATUS_UNKNOWN

    if actual_float is None:
        return STATUS_UNKNOWN

    try:
        pass_f = float(pass_threshold) if pass_threshold is not None else 1.0
        degraded_f = float(degraded_threshold) if degraded_threshold is not None else 0.0
    except (TypeError, ValueError):
        return STATUS_UNKNOWN

    if actual_float >= pass_f:
        return STATUS_PASS
    if actual_float >= degraded_f:
        return STATUS_DEGRADED
    return STATUS_BLOCKED


def compute_aggregate_status(category_results: List[Dict[str, Any]]) -> str:
    """Compute the aggregate (worst-category-wins) source fidelity status.

    Args:
        category_results: List of per-category score result dicts.

    Returns:
        The worst (most severe) status across all categories.
        If no categories are provided, returns unknown.
    """
    if not category_results:
        return STATUS_UNKNOWN
    statuses = [r.get("status", STATUS_UNKNOWN) for r in category_results]
    return worst_status(*statuses)


def build_aggregate_result(
    category_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a structured aggregate benchmark result.

    Combines per-category results into a single aggregate with:
      - source_fidelity_status: the worst-category status.
      - category_results: the full list of per-category dicts.
      - passed: True if status is pass, False otherwise.
      - degraded: True if status is degraded, False otherwise.
      - blocked: True if status is blocked, False otherwise.
    """
    aggregate = compute_aggregate_status(category_results)
    return {
        "source_fidelity_status": aggregate,
        "category_results": list(category_results),
        "passed": aggregate == STATUS_PASS,
        "degraded": aggregate == STATUS_DEGRADED,
        "blocked": aggregate == STATUS_BLOCKED,
    }
