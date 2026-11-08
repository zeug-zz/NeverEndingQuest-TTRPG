# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free arithmetic over explicitly supplied mise-en-scene scores."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SCENE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}:scene:[a-z0-9][a-z0-9_-]{0,63}$")
_CONDITIONS = {"A", "B", "C", "D"}
_AXES = {"legibility", "usefulness"}
_ROLES = {"owner", "independent_advisory", "author_self_review"}
_PHASES = {"calibration", "holdout"}
_MAX_RECORDS = 4096
_NOTICE = "supplied records, roles not authenticated, no scoring authorization"


class CalibrationError(ValueError):
    """Stable validation error for caller-supplied score records."""

    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(code + " at " + path)


def _metric(scores: list[tuple[int, int]]) -> dict[str, Any]:
    n = len(scores)
    exact = sum(left == right for left, right in scores)
    within = sum(abs(left - right) <= 1 for left, right in scores)
    error = sum(abs(left - right) for left, right in scores)
    estimable = n >= 6
    return {
        "paired_n": n,
        "paired_denominator": n,
        "exact_count": exact,
        "exact_denominator": n,
        "exact_agreement": exact / n if estimable else None,
        "within_one_count": within,
        "within_one_denominator": n,
        "within_one_agreement": within / n if estimable else None,
        "sum_absolute_error": error,
        "mae": error / n if estimable else None,
        "status": "CALIBRATED_SUPPLIED_PAIRS_ONLY" if estimable else "UNCALIBRATED_NOT_ESTIMABLE",
    }

def summarize_supplied_scores(records: object) -> dict[str, Any]:
    """Summarize validated scores; this function never collects or authenticates them."""

    if type(records) is not list or len(records) > _MAX_RECORDS:
        raise CalibrationError("RECORDS_LIMIT", "$.records")
    expected = {
        "artifact_sha256", "scene_id", "condition", "axis", "role", "rater", "score", "phase"
    }
    seen: set[tuple[str, str, str, str]] = set()
    artifact_metadata: dict[str, tuple[str, str]] = {}
    entries: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        path = "$.records[%d]" % index
        if type(raw) is not dict or set(raw) != expected:
            raise CalibrationError("RECORD_FIELDS", path)
        item = dict(raw)
        if type(item["artifact_sha256"]) is not str or not _HASH_RE.fullmatch(item["artifact_sha256"]):
            raise CalibrationError("ARTIFACT_SHA256", path + ".artifact_sha256")
        if type(item["scene_id"]) is not str or not _SCENE_RE.fullmatch(item["scene_id"]):
            raise CalibrationError("SCENE_ID", path + ".scene_id")
        if type(item["condition"]) is not str or item["condition"] not in _CONDITIONS:
            raise CalibrationError("CONDITION", path + ".condition")
        if type(item["axis"]) is not str or item["axis"] not in _AXES:
            raise CalibrationError("AXIS", path + ".axis")
        if type(item["role"]) is not str or item["role"] not in _ROLES:
            raise CalibrationError("ROLE", path + ".role")
        if type(item["phase"]) is not str or item["phase"] not in _PHASES:
            raise CalibrationError("PHASE", path + ".phase")
        rater = item["rater"]
        if type(rater) is not str or not rater or not rater.isascii() or len(rater) > 128:
            raise CalibrationError("RATER", path + ".rater")
        if type(item["score"]) is not int or not 1 <= item["score"] <= 5:
            raise CalibrationError("SCORE", path + ".score")
        metadata = (item["scene_id"], item["condition"])
        old_metadata = artifact_metadata.setdefault(item["artifact_sha256"], metadata)
        if old_metadata != metadata:
            raise CalibrationError("ARTIFACT_METADATA_CONFLICT", path + ".artifact_sha256")
        key = (item["role"], item["phase"], item["artifact_sha256"], item["axis"])
        if key in seen:
            raise CalibrationError("DUPLICATE_SCORE", path)
        seen.add(key)
        entries.append(item)

    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    owner_values: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    paired: dict[tuple[str, str, str], list[tuple[int, int]]] = defaultdict(list)
    unpaired: dict[tuple[str, str, str], int] = defaultdict(int)
    calibration_pairs_by_axis: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for item in entries:
        axis = item["axis"]
        unpaired[(item["role"], item["phase"], axis)] += 1
        if item["role"] == "owner":
            owner_values[(item["phase"], item["condition"], axis, item["scene_id"])].append(item["score"])
        if item["role"] in {"owner", "independent_advisory"}:
            group_key = (item["phase"], item["artifact_sha256"], axis)
            grouped[group_key][item["role"]] = item
    pair_rows = []
    for (phase, artifact_hash, axis), roles in sorted(grouped.items()):
        owner = roles.get("owner")
        advisory = roles.get("independent_advisory")
        if owner is not None and advisory is not None:
            pair_rows.append({
                "phase": phase, "artifact_sha256": artifact_hash,
                "scene_id": owner["scene_id"], "condition": owner["condition"],
                "axis": axis, "owner_score": owner["score"],
                "independent_advisory_score": advisory["score"],
            })
            paired[(phase, owner["condition"], axis)].append(
                (owner["score"], advisory["score"])
            )
            unpaired[("owner", phase, axis)] -= 1
            unpaired[("independent_advisory", phase, axis)] -= 1
            if phase == "calibration":
                calibration_pairs_by_axis[axis].append(
                    (owner["score"], advisory["score"])
                )

    metrics = {
        phase: {
            condition: {
                axis: _metric(paired[(phase, condition, axis)])
                for axis in sorted(_AXES)
            }
            for condition in sorted(_CONDITIONS)
        }
        for phase in sorted(_PHASES)
    }
    calibration_by_axis = {
        axis: _metric(calibration_pairs_by_axis[axis]) for axis in sorted(_AXES)
    }
    owner_summary: dict[str, Any] = {}
    for (phase, condition, axis, scene_id), values in sorted(owner_values.items()):
        owner_summary.setdefault(phase, {}).setdefault(condition, {}).setdefault(axis, {})[scene_id] = {
            "count": len(values), "mean": sum(values) / len(values),
            "minimum": min(values), "maximum": max(values),
        }
    owner_condition_totals: dict[str, Any] = {}
    for phase in sorted(_PHASES):
        for condition in sorted(_CONDITIONS):
            for axis in sorted(_AXES):
                values = [
                    item["score"] for item in entries
                    if item["role"] == "owner" and item["phase"] == phase
                    and item["condition"] == condition and item["axis"] == axis
                ]
                owner_condition_totals.setdefault(phase, {}).setdefault(condition, {})[axis] = {
                    "count": len(values),
                    "mean": sum(values) / len(values) if values else None,
                    "minimum": min(values) if values else None,
                    "maximum": max(values) if values else None,
                }
    return {
        "notice": _NOTICE,
        "scoring_authorized": False,
        "paired_metrics": metrics,
        "calibration_by_axis": calibration_by_axis,
        "paired_items": pair_rows,
        "unpaired_counts": [
            {"role": role, "phase": phase, "axis": axis, "count": count}
            for (role, phase, axis), count in sorted(unpaired.items())
        ],
        "author_self_reviews": [
            {key: item[key] for key in sorted(expected)}
            for item in sorted(entries, key=lambda row: (row["phase"], row["artifact_sha256"], row["axis"], row["rater"]))
            if item["role"] == "author_self_review"
        ],
        "owner_scores_by_condition": owner_summary,
        "owner_condition_totals": owner_condition_totals,
    }
