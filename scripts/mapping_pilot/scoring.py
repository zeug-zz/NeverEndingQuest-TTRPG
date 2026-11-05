# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free scoring for preregistered mapping-pilot row data.

Public APIs are ``score_row``, ``score_matrix``, ``pre_request_guard``, and
``serialize_scoring_report``. Row mappings use ``row_id``, ``arm``, ``block``,
``party``, ``script``, ``repeat``, ``completed``, ``attempt_count``, and
``elapsed_seconds`` plus structured ``spatial_references``,
``spatial_contradictions``, ``knowledge_leakage_count``, ``assistant_turns``,
``continuity_assertions``, ``observed_combat_rounds``, serialized
``zone_ledger_observations``, ``regression_guards``, ``rubric_ratings``,
``sketch_test``, ``model_turns``, and ``provider_calls``. Each model turn owns
its classifier calls, so their tokens and cost are attributed to that turn.

This module does not classify prose, call a provider, infer missing ratings or
measurements, or issue the primary's live verdict.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from typing import Any, Optional


ROW_ATTEMPT_CAP = 35
MATRIX_ATTEMPT_CAP = 800
ROW_WALL_TIME_CAP_SECONDS = 25 * 60
MATRIX_WALL_TIME_CAP_SECONDS = 6 * 60 * 60
INTENT_OUTCOMES = ("exact", "acceptable", "wrong", "refused", "clarified")
REGRESSION_GUARDS = (
    "mechanics_errors",
    "character_knowledge_violations",
    "validation_retries",
    "failed_turns",
)
CONTINUITY_CHECKS = (
    "return_journey",
    "changed_back_door",
    "viewpoint_switch",
)
RUBRIC_DIMENSIONS = {
    1: "sense_of_place",
    2: "imaginability",
    3: "natural_use",
    4: "actionability",
    5: "continuity",
    6: "combat_clarity_and_flow",
}
_UNKNOWN_MODEL_LABELS = frozenset(("", "unknown", "openrouter/auto"))
_UNKNOWN = "unknown"
_NOT_ESTIMABLE = "not estimable"
_MISSING = "missing"


def pre_request_guard(
    row_attempts: Optional[int],
    row_elapsed_seconds: Optional[float],
    matrix_attempts: Optional[int],
    matrix_elapsed_seconds: Optional[float],
) -> dict[str, Any]:
    """Return allow/refuse without incrementing or clamping actual counters.

    Missing counters fail closed. A request is refused at equality with any
    hard cap, so a caller cannot send one more request after reaching a limit.
    """
    attempts = {
        "row_attempts": _checked_count(row_attempts, "row_attempts"),
        "matrix_attempts": _checked_count(matrix_attempts, "matrix_attempts"),
    }
    elapsed = {
        "row_elapsed_seconds": _checked_seconds(
            row_elapsed_seconds, "row_elapsed_seconds"
        ),
        "matrix_elapsed_seconds": _checked_seconds(
            matrix_elapsed_seconds, "matrix_elapsed_seconds"
        ),
    }
    reasons: list[str] = []
    if any(value is None for value in attempts.values()):
        reasons.append("attempt_count_unknown")
    if any(value is None for value in elapsed.values()):
        reasons.append("wall_time_unknown")
    if attempts["row_attempts"] is not None and attempts["row_attempts"] >= ROW_ATTEMPT_CAP:
        reasons.append("row_attempt_cap")
    if (
        attempts["matrix_attempts"] is not None
        and attempts["matrix_attempts"] >= MATRIX_ATTEMPT_CAP
    ):
        reasons.append("matrix_attempt_cap")
    if (
        elapsed["row_elapsed_seconds"] is not None
        and elapsed["row_elapsed_seconds"] >= ROW_WALL_TIME_CAP_SECONDS
    ):
        reasons.append("row_wall_time_cap")
    if (
        elapsed["matrix_elapsed_seconds"] is not None
        and elapsed["matrix_elapsed_seconds"] >= MATRIX_WALL_TIME_CAP_SECONDS
    ):
        reasons.append("matrix_wall_time_cap")
    reasons.sort()
    return {
        "decision": "allow" if not reasons else "refuse",
        "allowed": not reasons,
        "reasons": reasons,
        "actual_counts": {
            "row_attempts": attempts["row_attempts"]
            if attempts["row_attempts"] is not None
            else _UNKNOWN,
            "row_elapsed_seconds": _number_output(
                elapsed["row_elapsed_seconds"]
            )
            if elapsed["row_elapsed_seconds"] is not None
            else _UNKNOWN,
            "matrix_attempts": attempts["matrix_attempts"]
            if attempts["matrix_attempts"] is not None
            else _UNKNOWN,
            "matrix_elapsed_seconds": _number_output(
                elapsed["matrix_elapsed_seconds"]
            )
            if elapsed["matrix_elapsed_seconds"] is not None
            else _UNKNOWN,
        },
        "caps": {
            "row_attempts": ROW_ATTEMPT_CAP,
            "matrix_attempts": MATRIX_ATTEMPT_CAP,
            "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
            "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
        },
    }


def score_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Score one structured row without reading narrative text or runtime state.

    Row input fields are described in the module docstring and covered by the
    adjacent tests. Missing measures remain ``unknown`` or ``missing``; explicit
    zero denominators produce the literal ``not estimable`` for rates.
    """
    normalized = _validate_row(row)
    return _score_validated_row(normalized)


def _score_validated_row(normalized: Mapping[str, Any]) -> dict[str, Any]:
    cap_accounting = _row_cap_accounting(normalized)
    return {
        "row_id": normalized["row_id"],
        "arm": normalized["arm"],
        "block": normalized["block"],
        "party": normalized["party"],
        "script": normalized["script"],
        "repeat": normalized["repeat"],
        "completed": normalized["completed"]
        if normalized["completed"] is not None
        else _UNKNOWN,
        "measures": {
            "spatial": _spatial_measure(normalized),
            "knowledge_leakage": _knowledge_measure(normalized),
            "continuity": _continuity_measure(normalized),
            "combat": _combat_measure(normalized),
            "rubric": _rubric_measure(normalized),
            "sketch_test": _sketch_measure(normalized),
            "cost": _cost_measure(normalized),
            "attempts_per_row": cap_accounting["actual_attempts"],
        },
        "regression_guards": _guard_counts(normalized),
        "cap_accounting": cap_accounting,
    }


def score_matrix(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Score rows, aggregate cap/route accounting, and evaluate fixed decisions."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("rows must be a sequence of row objects")
    normalized_rows = [_validate_row(row) for row in rows]
    identifiers = [row["row_id"] for row in normalized_rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("row_id values must be unique")
    normalized_rows.sort(key=lambda item: item["row_id"])
    scored_rows = [_score_validated_row(row) for row in normalized_rows]
    return {
        "schema": "mapping-pilot-scoring-v1",
        "caps": {
            "row_attempts": ROW_ATTEMPT_CAP,
            "matrix_attempts": MATRIX_ATTEMPT_CAP,
            "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
            "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
        },
        "rows": scored_rows,
        "primary_verdict": "not issued",
        "matrix_cap_accounting": _matrix_cap_accounting(normalized_rows),
        "route_by_arm": _route_by_arm(normalized_rows),
        "route_confounds": _route_confounds(normalized_rows),
        "regression_guard_comparisons": _regression_guard_comparisons(
            normalized_rows
        ),
        "decision_rules": _decision_rules(normalized_rows),
    }


def serialize_scoring_report(report: Mapping[str, Any]) -> str:
    """Serialize a scoring report as deterministic, ASCII-only compact JSON."""
    try:
        return json.dumps(
            report,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("scoring report must contain finite JSON data") from exc


def _validate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValueError("each scoring row must be an object")
    row_id = row.get("row_id")
    if not isinstance(row_id, str) or not row_id or row_id != row_id.strip():
        raise ValueError("row_id must be non-empty text")
    arm = _optional_text(row, "arm") or _UNKNOWN
    block = _optional_text(row, "block") or _UNKNOWN
    party = _optional_text(row, "party") or _UNKNOWN
    script = _optional_text(row, "script") or _UNKNOWN
    repeat = _checked_count(row.get("repeat"), "repeat")
    if repeat is not None and repeat < 1:
        raise ValueError("repeat must be positive when supplied")
    completed_value = row.get("completed")
    if completed_value is not None and not isinstance(completed_value, bool):
        raise ValueError("completed must be a boolean when supplied")
    _validate_observations(row)
    return {
        "source": row,
        "row_id": row_id,
        "arm": arm,
        "block": block,
        "party": party,
        "script": script,
        "repeat": repeat,
        "completed": completed_value,
        "attempt_count": _checked_count(
            row.get("attempt_count"), "attempt_count"
        ),
        "elapsed_seconds": _checked_seconds(
            row.get("elapsed_seconds"), "elapsed_seconds"
        ),
        "spatial_references": _checked_count(
            row.get("spatial_references"), "spatial_references"
        ),
        "spatial_contradictions": _checked_count(
            row.get("spatial_contradictions"), "spatial_contradictions"
        ),
        "knowledge_leakage_count": _checked_count(
            row.get("knowledge_leakage_count"), "knowledge_leakage_count"
        ),
        "assistant_turns": _checked_count(row.get("assistant_turns"), "assistant_turns"),
        "observed_combat_rounds": _checked_count(
            row.get("observed_combat_rounds"), "observed_combat_rounds"
        ),
    }


def _validate_observations(row: Mapping[str, Any]) -> None:
    raw = row.get("zone_ledger_observations")
    if raw is None:
        return
    if not isinstance(raw, str):
        raise ValueError("zone_ledger_observations must be serialized JSON text")
    try:
        observations = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("zone_ledger_observations is not valid JSON") from exc
    if not isinstance(observations, list):
        raise ValueError("zone_ledger_observations must serialize a list")
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            raise ValueError("zone ledger observation %d must be an object" % index)
        if observation.get("kind") == "contradiction_claim":
            if not isinstance(observation.get("contradiction"), bool):
                raise ValueError(
                    "zone ledger contradiction observation %d needs a boolean" % index
                )
        if observation.get("kind") == "movement_parse_outcome":
            classification = observation.get("classification")
            if classification is not None and classification not in INTENT_OUTCOMES:
                raise ValueError(
                    "zone ledger movement observation %d has an unknown outcome"
                    % index
                )


def _optional_text(row: Mapping[str, Any], key: str) -> Optional[str]:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("%s must be non-empty text when supplied" % key)
    return value


def _checked_count(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("%s must be a non-negative integer when supplied" % label)
    return value


def _checked_seconds(value: Any, label: str) -> Optional[Fraction]:
    if value is None:
        return None
    seconds = _as_fraction(value, label)
    if seconds < 0:
        raise ValueError("%s cannot be negative" % label)
    return seconds


def _as_fraction(value: Any, label: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("%s must be a finite number" % label)
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("%s must be a finite number" % label) from exc
    if not decimal_value.is_finite():
        raise ValueError("%s must be a finite number" % label)
    return Fraction(decimal_value)


def _number_output(value: Optional[Fraction]) -> Any:
    if value is None:
        return _UNKNOWN
    if value.denominator == 1:
        return value.numerator
    return float(value)


def _scaled_rate(
    numerator: Optional[int], denominator: Optional[int], scale: int
) -> Any:
    if denominator == 0:
        return _NOT_ESTIMABLE
    if numerator is None or denominator is None:
        return _UNKNOWN
    return _number_output(Fraction(numerator * scale, denominator))


def _spatial_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    references = row["spatial_references"]
    contradictions = row["spatial_contradictions"]
    if references is not None and contradictions is not None and contradictions > references:
        raise ValueError("spatial_contradictions cannot exceed spatial_references")
    return {
        "spatial_references": references if references is not None else _UNKNOWN,
        "spatial_contradictions": contradictions
        if contradictions is not None
        else _UNKNOWN,
        "contradictions_per_100_references": _scaled_rate(
            contradictions, references, 100
        ),
    }


def _knowledge_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    leakage = row["knowledge_leakage_count"]
    turns = row["assistant_turns"]
    return {
        "leakage_count": leakage if leakage is not None else _UNKNOWN,
        "assistant_turns": turns if turns is not None else _UNKNOWN,
        "leakage_per_100_assistant_turns": _scaled_rate(leakage, turns, 100),
    }


def _continuity_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    source = row["source"]
    raw = source.get("continuity_assertions")
    results: dict[str, Any] = {}
    for check in CONTINUITY_CHECKS:
        if not isinstance(raw, Mapping) or check not in raw:
            results[check] = {"status": _MISSING, "assertions": _MISSING}
            continue
        assertions = raw[check]
        if isinstance(assertions, bool):
            values = [assertions]
        elif isinstance(assertions, Sequence) and not isinstance(
            assertions, (str, bytes)
        ):
            values = list(assertions)
        else:
            raise ValueError("continuity_assertions.%s must be booleans" % check)
        if not values:
            results[check] = {"status": _NOT_ESTIMABLE, "assertions": []}
            continue
        if any(not isinstance(value, bool) for value in values):
            raise ValueError("continuity_assertions.%s must contain booleans" % check)
        results[check] = {
            "status": "pass" if all(values) else "fail",
            "assertions": values,
        }
    return results


def _combat_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    observations = _zone_observations(row["source"])
    rounds = row["observed_combat_rounds"]
    if observations is None:
        contradiction_count: Any = _UNKNOWN
        contradiction_categories: Any = _UNKNOWN
        outcome_counts: Any = _UNKNOWN
        observed_outcomes: Any = _UNKNOWN
        unclassified_outcomes: Any = _UNKNOWN
    else:
        category_counts: Counter[str] = Counter()
        contradiction_count_int = 0
        movement_records: list[Mapping[str, Any]] = []
        for observation in observations:
            if observation.get("kind") == "contradiction_claim" and observation.get(
                "contradiction"
            ) is True:
                contradiction_count_int += 1
                category = observation.get("category")
                if isinstance(category, str) and category:
                    category_counts[category] += 1
            elif observation.get("kind") == "movement_parse_outcome":
                movement_records.append(observation)
        contradiction_count = contradiction_count_int
        contradiction_categories = {
            category: category_counts[category] for category in sorted(category_counts)
        }
        counts = {outcome: 0 for outcome in INTENT_OUTCOMES}
        unclassified = 0
        for observation in movement_records:
            classification = observation.get("classification")
            if classification is None:
                unclassified += 1
            else:
                counts[classification] += 1
        outcome_counts = counts
        observed_outcomes = len(movement_records)
        unclassified_outcomes = unclassified

    intent_total = observed_outcomes
    intent_complete = (
        isinstance(intent_total, int)
        and intent_total == 4
        and isinstance(unclassified_outcomes, int)
        and unclassified_outcomes == 0
    )
    if intent_complete:
        intent_successes = outcome_counts["exact"] + outcome_counts["acceptable"]
        intent_accuracy: Any = _number_output(Fraction(intent_successes * 100, 4))
    else:
        intent_successes = _UNKNOWN
        intent_accuracy = _UNKNOWN
    return {
        "zone_contradictions": contradiction_count,
        "zone_contradiction_categories": contradiction_categories,
        "observed_rounds": rounds if rounds is not None else _UNKNOWN,
        "contradictions_per_10_rounds": _scaled_rate(
            contradiction_count
            if isinstance(contradiction_count, int)
            else None,
            rounds,
            10,
        ),
        "intent_parse": {
            "expected_utterances": 4,
            "observed_utterances": observed_outcomes,
            "unclassified_utterances": unclassified_outcomes,
            "outcome_counts": outcome_counts,
            "exact_or_acceptable_count": intent_successes,
            "exact_or_acceptable_percent": intent_accuracy,
            "status": "complete" if intent_complete else _UNKNOWN,
        },
    }


def _zone_observations(row: Mapping[str, Any]) -> Optional[list[Mapping[str, Any]]]:
    raw = row.get("zone_ledger_observations")
    if raw is None:
        return None
    observations = json.loads(raw)
    return observations


def _rubric_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    values = _rubric_values(row["source"])
    by_dimension: dict[str, Any] = {}
    for dimension in sorted(RUBRIC_DIMENSIONS):
        value = values.get(dimension)
        by_dimension[str(dimension)] = (
            _number_output(value) if value is not None else _MISSING
        )
    first_five = [values.get(dimension) for dimension in range(1, 6)]
    mean: Any = _MISSING
    if all(value is not None for value in first_five):
        mean = _number_output(sum(first_five, Fraction(0)) / 5)
    return {
        "dimensions": by_dimension,
        "mean_dimensions_1_to_5": mean,
    }


def _rubric_values(row: Mapping[str, Any]) -> dict[int, Optional[Fraction]]:
    raw = row.get("rubric_ratings")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("rubric_ratings must be an object")
    values: dict[int, Fraction] = {}
    for key, value in raw.items():
        dimension = _rubric_dimension(key)
        if dimension in values:
            raise ValueError("rubric_ratings repeats dimension %d" % dimension)
        rating = _as_fraction(value, "rubric rating")
        if rating < 1 or rating > 5:
            raise ValueError("rubric ratings must be between 1 and 5")
        values[dimension] = rating
    return {dimension: values.get(dimension) for dimension in RUBRIC_DIMENSIONS}


def _rubric_dimension(key: Any) -> int:
    if isinstance(key, int) and not isinstance(key, bool):
        dimension = key
    elif isinstance(key, str):
        if key.isdigit():
            dimension = int(key)
        else:
            matches = [
                number
                for number, name in RUBRIC_DIMENSIONS.items()
                if key == name
            ]
            dimension = matches[0] if len(matches) == 1 else -1
    else:
        dimension = -1
    if dimension not in RUBRIC_DIMENSIONS:
        raise ValueError("rubric dimension must be 1 through 6")
    return dimension


def _sketch_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row["source"].get("sketch_test")
    if raw is None:
        return _MISSING
    if not isinstance(raw, Mapping):
        raise ValueError("sketch_test must be an object")
    correct = _checked_count(raw.get("anchors_correct"), "anchors_correct")
    total = _checked_count(raw.get("anchors_total"), "anchors_total")
    if correct is not None and total is not None and correct > total:
        raise ValueError("anchors_correct cannot exceed anchors_total")
    owner_rating = raw.get("owner_rating")
    if owner_rating is None:
        rating_output: Any = _MISSING
    else:
        rating = _as_fraction(owner_rating, "sketch owner_rating")
        rating_output = _number_output(rating)
    return {
        "anchors_correct": correct if correct is not None else _UNKNOWN,
        "anchors_total": total if total is not None else _UNKNOWN,
        "anchor_placement_percent": _scaled_rate(correct, total, 100),
        "owner_rating": rating_output,
    }


def _cost_measure(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_turns = row["source"].get("model_turns")
    if raw_turns is None:
        return {
            "model_bearing_turns": _UNKNOWN,
            "input_tokens_total": _UNKNOWN,
            "output_tokens_total": _UNKNOWN,
            "input_tokens_per_model_turn": _UNKNOWN,
            "output_tokens_per_model_turn": _UNKNOWN,
            "input_tokens_by_model_turn": _UNKNOWN,
            "output_tokens_by_model_turn": _UNKNOWN,
            "p50_turn_latency_seconds": _UNKNOWN,
            "p95_turn_latency_seconds": _UNKNOWN,
            "turn_latency_seconds": _UNKNOWN,
            "classifier_call_count": _UNKNOWN,
            "classifier_latency_total_seconds": _UNKNOWN,
            "classifier_latency_by_model_turn_seconds": _UNKNOWN,
            "classifier_p50_latency_seconds": _UNKNOWN,
            "classifier_p95_latency_seconds": _UNKNOWN,
            "total_cost_usd": _UNKNOWN,
            "cost_usd_per_model_turn": _UNKNOWN,
        }
    if not isinstance(raw_turns, Sequence) or isinstance(raw_turns, (str, bytes)):
        raise ValueError("model_turns must be a list")
    turns = list(raw_turns)
    if any(not isinstance(turn, Mapping) for turn in turns):
        raise ValueError("each model turn must be an object")

    total_input = 0
    total_output = 0
    input_complete = True
    output_complete = True
    cost_total = Fraction(0)
    cost_complete = True
    turn_latencies: list[Fraction] = []
    turn_latency_values: list[Any] = []
    input_by_turn: list[Any] = []
    output_by_turn: list[Any] = []
    classifier_latency_by_turn: list[Any] = []
    latency_complete = True
    classifier_latencies: list[Fraction] = []
    classifier_count = 0
    classifier_shape_complete = True
    classifier_latency_complete = True

    for turn_index, turn in enumerate(turns):
        turn_input = _checked_count(turn.get("input_tokens"), "input_tokens")
        turn_output = _checked_count(turn.get("output_tokens"), "output_tokens")
        allocated_input = turn_input
        allocated_output = turn_output
        allocated_classifier_latency = Fraction(0)
        allocated_classifier_latency_complete = True
        if turn_input is None:
            input_complete = False
        else:
            total_input += turn_input
        if turn_output is None:
            output_complete = False
        else:
            total_output += turn_output
        turn_cost = _optional_cost(turn.get("cost_usd"), "cost_usd")
        if turn_cost is None:
            cost_complete = False
        else:
            cost_total += turn_cost
        turn_latency = _checked_seconds(
            turn.get("latency_seconds"), "latency_seconds"
        )
        if turn_latency is None:
            latency_complete = False
            turn_latency_values.append(_UNKNOWN)
        else:
            turn_latencies.append(turn_latency)
            turn_latency_values.append(_number_output(turn_latency))

        if "classifier_calls" not in turn or turn.get("classifier_calls") is None:
            classifier_shape_complete = False
            input_complete = False
            output_complete = False
            cost_complete = False
            classifier_latency_complete = False
            allocated_classifier_latency_complete = False
            allocated_input = None
            allocated_output = None
            input_by_turn.append(_UNKNOWN)
            output_by_turn.append(_UNKNOWN)
            classifier_latency_by_turn.append(_UNKNOWN)
            continue
        raw_classifiers = turn.get("classifier_calls")
        if not isinstance(raw_classifiers, Sequence) or isinstance(
            raw_classifiers, (str, bytes)
        ):
            raise ValueError(
                "model_turns[%d].classifier_calls must be a list" % turn_index
            )
        for classifier in raw_classifiers:
            if not isinstance(classifier, Mapping):
                raise ValueError("each classifier call must be an object")
            classifier_count += 1
            classifier_input = _checked_count(
                classifier.get("input_tokens"), "classifier input_tokens"
            )
            classifier_output = _checked_count(
                classifier.get("output_tokens"), "classifier output_tokens"
            )
            if classifier_input is None:
                input_complete = False
                allocated_input = None
            else:
                total_input += classifier_input
                if allocated_input is not None:
                    allocated_input += classifier_input
            if classifier_output is None:
                output_complete = False
                allocated_output = None
            else:
                total_output += classifier_output
                if allocated_output is not None:
                    allocated_output += classifier_output
            classifier_cost = _optional_cost(
                classifier.get("cost_usd"), "classifier cost_usd"
            )
            if classifier_cost is None:
                cost_complete = False
            else:
                cost_total += classifier_cost
            classifier_latency = _checked_seconds(
                classifier.get("latency_seconds"),
                "classifier latency_seconds",
            )
            if classifier_latency is None:
                classifier_latency_complete = False
                allocated_classifier_latency_complete = False
            else:
                classifier_latencies.append(classifier_latency)
                allocated_classifier_latency += classifier_latency

        input_by_turn.append(
            allocated_input if allocated_input is not None else _UNKNOWN
        )
        output_by_turn.append(
            allocated_output if allocated_output is not None else _UNKNOWN
        )
        classifier_latency_by_turn.append(
            _number_output(allocated_classifier_latency)
            if allocated_classifier_latency_complete
            else _UNKNOWN
        )

    turn_count = len(turns)
    if turn_count == 0:
        input_average: Any = _NOT_ESTIMABLE
        output_average: Any = _NOT_ESTIMABLE
        cost_average: Any = _NOT_ESTIMABLE
        total_cost_output: Any = _NOT_ESTIMABLE
    else:
        input_average = (
            _number_output(Fraction(total_input, turn_count))
            if input_complete
            else _UNKNOWN
        )
        output_average = (
            _number_output(Fraction(total_output, turn_count))
            if output_complete
            else _UNKNOWN
        )
        total_cost_output = (
            _number_output(cost_total) if cost_complete else _UNKNOWN
        )
        cost_average = (
            _number_output(cost_total / turn_count) if cost_complete else _UNKNOWN
        )
    return {
        "model_bearing_turns": turn_count,
        "input_tokens_total": total_input if input_complete else _UNKNOWN,
        "output_tokens_total": total_output if output_complete else _UNKNOWN,
        "input_tokens_per_model_turn": input_average,
        "output_tokens_per_model_turn": output_average,
        "input_tokens_by_model_turn": input_by_turn,
        "output_tokens_by_model_turn": output_by_turn,
        "p50_turn_latency_seconds": _percentile_output(
            turn_latencies, latency_complete, Fraction(1, 2)
        ),
        "p95_turn_latency_seconds": _percentile_output(
            turn_latencies, latency_complete, Fraction(95, 100)
        ),
        "turn_latency_seconds": turn_latency_values,
        "classifier_call_count": classifier_count
        if classifier_shape_complete
        else _UNKNOWN,
        "classifier_latency_total_seconds": _classifier_latency_total(
            classifier_latencies,
            classifier_count,
            classifier_shape_complete,
            classifier_latency_complete,
        ),
        "classifier_latency_by_model_turn_seconds": classifier_latency_by_turn
        if classifier_shape_complete
        else _UNKNOWN,
        "classifier_p50_latency_seconds": _percentile_output(
            classifier_latencies,
            classifier_shape_complete and classifier_latency_complete,
            Fraction(1, 2),
        ),
        "classifier_p95_latency_seconds": _percentile_output(
            classifier_latencies,
            classifier_shape_complete and classifier_latency_complete,
            Fraction(95, 100),
        ),
        "total_cost_usd": total_cost_output,
        "cost_usd_per_model_turn": cost_average,
    }


def _optional_cost(value: Any, label: str) -> Optional[Fraction]:
    if value is None:
        return None
    amount = _as_fraction(value, label)
    if amount < 0:
        raise ValueError("%s cannot be negative" % label)
    return amount


def _classifier_latency_total(
    values: Sequence[Fraction],
    count: int,
    shape_complete: bool,
    latency_complete: bool,
) -> Any:
    if not shape_complete or not latency_complete:
        return _UNKNOWN
    if count == 0:
        return _NOT_ESTIMABLE
    if len(values) != count:
        return _UNKNOWN
    return _number_output(sum(values, Fraction(0)))


def _percentile_output(
    values: Sequence[Fraction], complete: bool, percentile: Fraction
) -> Any:
    if not complete:
        return _UNKNOWN
    if not values:
        return _NOT_ESTIMABLE
    ordered = sorted(values)
    rank = (percentile.numerator * len(ordered) + percentile.denominator - 1) // percentile.denominator
    return _number_output(ordered[rank - 1])


def _guard_counts(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row["source"].get("regression_guards")
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("regression_guards must be an object")
    return {
        name: _checked_count(raw.get(name), name)
        if raw.get(name) is not None
        else _UNKNOWN
        for name in REGRESSION_GUARDS
    }


def _row_cap_accounting(row: Mapping[str, Any]) -> dict[str, Any]:
    attempts = row["attempt_count"]
    elapsed = row["elapsed_seconds"]
    attempt_hit: Any = _UNKNOWN if attempts is None else attempts >= ROW_ATTEMPT_CAP
    time_hit: Any = _UNKNOWN if elapsed is None else elapsed >= ROW_WALL_TIME_CAP_SECONDS
    if attempt_hit is True or time_hit is True or attempt_hit == _UNKNOWN or time_hit == _UNKNOWN:
        disposition = "BLOCKED"
    else:
        disposition = "within_caps"
    return {
        "actual_attempts": attempts if attempts is not None else _UNKNOWN,
        "actual_wall_time_seconds": _number_output(elapsed)
        if elapsed is not None
        else _UNKNOWN,
        "row_attempt_cap": ROW_ATTEMPT_CAP,
        "row_wall_time_cap_seconds": ROW_WALL_TIME_CAP_SECONDS,
        "attempt_cap_reached": attempt_hit,
        "wall_time_cap_reached": time_hit,
        "disposition": disposition,
    }


def _matrix_cap_accounting(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    attempts = [row["attempt_count"] for row in rows]
    elapsed = [row["elapsed_seconds"] for row in rows]
    actual_attempts: Any = (
        sum(attempts) if all(value is not None for value in attempts) else _UNKNOWN
    )
    actual_elapsed: Any = (
        sum(elapsed, Fraction(0))
        if all(value is not None for value in elapsed)
        else _UNKNOWN
    )
    attempt_hit: Any = (
        _UNKNOWN
        if actual_attempts == _UNKNOWN
        else actual_attempts >= MATRIX_ATTEMPT_CAP
    )
    time_hit: Any = (
        _UNKNOWN
        if actual_elapsed == _UNKNOWN
        else actual_elapsed >= MATRIX_WALL_TIME_CAP_SECONDS
    )
    disposition = (
        "BLOCKED"
        if attempt_hit is True
        or time_hit is True
        or attempt_hit == _UNKNOWN
        or time_hit == _UNKNOWN
        else "within_caps"
    )
    return {
        "actual_attempts": actual_attempts,
        "actual_wall_time_seconds": _number_output(actual_elapsed)
        if actual_elapsed != _UNKNOWN
        else _UNKNOWN,
        "matrix_attempt_cap": MATRIX_ATTEMPT_CAP,
        "matrix_wall_time_cap_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
        "attempt_cap_reached": attempt_hit,
        "wall_time_cap_reached": time_hit,
        "disposition": disposition,
    }


def _route_by_arm(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    arms = sorted({row["arm"] for row in rows})
    return {arm: _route_arm_summary([row for row in rows if row["arm"] == arm]) for arm in arms}


def _route_arm_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    attempt_values = [row["attempt_count"] for row in rows]
    denominator_known = all(value is not None for value in attempt_values)
    denominator = sum(attempt_values) if denominator_known else None
    route_values: dict[str, list[str]] = {
        "requested_model": [],
        "resolved_model": [],
        "transport": [],
        "provider": [],
        "observed_upstream_provider": [],
        "fallback_status": [],
    }
    fallback_values: list[Optional[bool]] = []
    recorded_count = 0
    missing_route_count = 0
    for row in rows:
        source = row["source"]
        raw_calls = source.get("provider_calls")
        if raw_calls is None:
            calls: list[Mapping[str, Any]] = []
        elif isinstance(raw_calls, Sequence) and not isinstance(raw_calls, (str, bytes)):
            calls = list(raw_calls)
        else:
            raise ValueError("provider_calls must be a list")
        if any(not isinstance(call, Mapping) for call in calls):
            raise ValueError("each provider call must be an object")
        attempts = row["attempt_count"]
        if attempts is not None and len(calls) > attempts:
            raise ValueError("provider_calls cannot exceed attempt_count")
        recorded_count += len(calls)
        for call in calls:
            route_values["requested_model"].append(
                _route_label(call.get("requested_model"))
            )
            resolved = _resolved_model_label(call.get("resolved_model"))
            route_values["resolved_model"].append(resolved)
            route_values["transport"].append(_route_label(call.get("transport")))
            route_values["provider"].append(_route_label(call.get("provider")))
            route_values["observed_upstream_provider"].append(
                _route_label(call.get("observed_upstream_provider"))
            )
            fallback = _fallback_value(call.get("fallback"))
            fallback_values.append(fallback)
            route_values["fallback_status"].append(
                "fallback"
                if fallback is True
                else "direct"
                if fallback is False
                else _UNKNOWN
            )
        if attempts is not None:
            missing = attempts - len(calls)
            missing_route_count += missing
            for _index in range(missing):
                for values in route_values.values():
                    values.append(_UNKNOWN)
                fallback_values.append(None)

    if denominator_known:
        route_status = "complete"
    else:
        route_status = "partial"
    if denominator is not None:
        for field in route_values:
            if len(route_values[field]) != denominator:
                raise ValueError("route accounting does not match actual attempts")

    distributions = {
        field: _distribution(route_values[field], denominator)
        for field in sorted(route_values)
    }
    fallback_known = sum(value is not None for value in fallback_values)
    fallback_true = sum(value is True for value in fallback_values)
    fallback_false = sum(value is False for value in fallback_values)
    if denominator == 0:
        fallback_share: dict[str, Any] = {
            "status": _NOT_ESTIMABLE,
            "share": _NOT_ESTIMABLE,
            "fallback_calls": 0,
            "direct_calls": 0,
            "unknown_calls": 0,
            "denominator": 0,
        }
    elif denominator is None:
        fallback_share = {
            "status": _UNKNOWN,
            "share": _UNKNOWN,
            "fallback_calls": fallback_true,
            "direct_calls": fallback_false,
            "unknown_calls": len(fallback_values) - fallback_known,
            "known_calls": fallback_known,
            "denominator": _UNKNOWN,
        }
    elif fallback_known != denominator:
        fallback_share = {
            "status": "partial",
            "share": _UNKNOWN,
            "known_status_share": _percentage_payload(
                Fraction(fallback_true, fallback_known)
            )
            if fallback_known
            else _UNKNOWN,
            "fallback_calls": fallback_true,
            "direct_calls": fallback_false,
            "unknown_calls": denominator - fallback_known,
            "known_calls": fallback_known,
            "denominator": denominator,
        }
    else:
        fallback_share = {
            "status": "complete",
            "share": _percentage_payload(Fraction(fallback_true, denominator)),
            "fallback_calls": fallback_true,
            "direct_calls": fallback_false,
            "unknown_calls": 0,
            "denominator": denominator,
        }

    unknown_model_count = route_values["resolved_model"].count(_UNKNOWN)
    if denominator == 0:
        unknown_model_share: dict[str, Any] = {
            "status": _NOT_ESTIMABLE,
            "share": _NOT_ESTIMABLE,
            "unknown_model_calls": 0,
            "denominator": 0,
        }
    elif denominator is None:
        unknown_model_share = {
            "status": _UNKNOWN,
            "share": _UNKNOWN,
            "unknown_model_calls": unknown_model_count,
            "denominator": _UNKNOWN,
        }
    else:
        unknown_model_share = {
            "status": "complete",
            "share": _percentage_payload(
                Fraction(unknown_model_count, denominator)
            ),
            "unknown_model_calls": unknown_model_count,
            "denominator": denominator,
        }
    return {
        "status": route_status,
        "actual_attempts": denominator if denominator is not None else _UNKNOWN,
        "recorded_provider_calls": recorded_count,
        "calls_missing_route_observations": missing_route_count
        if denominator_known
        else _UNKNOWN,
        "distributions": distributions,
        "fallback_share": fallback_share,
        "unknown_model_share": unknown_model_share,
    }


def _distribution(values: Sequence[str], denominator: Optional[int]) -> dict[str, Any]:
    counts = Counter(values)
    labels = sorted(counts)
    result: dict[str, Any] = {}
    for label in labels:
        count = counts[label]
        share: Any
        if denominator is None:
            share = _UNKNOWN
        elif denominator == 0:
            share = _NOT_ESTIMABLE
        else:
            share = _percentage_payload(Fraction(count, denominator))
        result[label] = {"count": count, "share": share}
    return result


def _route_label(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return _UNKNOWN
    if value.strip().lower() == "unknown":
        return _UNKNOWN
    return value.strip()


def _resolved_model_label(value: Any) -> str:
    if not isinstance(value, str):
        return _UNKNOWN
    normalized = value.strip()
    if normalized.lower() in _UNKNOWN_MODEL_LABELS:
        return _UNKNOWN
    return normalized


def _fallback_value(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "fallback":
            return True
        if normalized == "direct":
            return False
    return None


def _route_confounds(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_arm = _route_by_arm(rows)
    baseline = by_arm.get("A")
    comparisons: dict[str, Any] = {}
    for arm in sorted(name for name in by_arm if name != "A"):
        candidate = by_arm[arm]
        comparisons[arm] = _compare_route_arms(baseline, candidate)
    return {
        "baseline_arm": "A",
        "per_arm": by_arm,
        "comparisons": comparisons,
    }


def _compare_route_arms(
    baseline: Optional[Mapping[str, Any]], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    if baseline is None:
        return {
            "status": _UNKNOWN,
            "resolved_model_share_differences": _UNKNOWN,
            "flagged_models": _UNKNOWN,
            "fallback_share_difference": _UNKNOWN,
            "unknown_model_share_difference": _UNKNOWN,
        }
    base_distribution = baseline["distributions"]["resolved_model"]
    candidate_distribution = candidate["distributions"]["resolved_model"]
    base_denominator = _distribution_denominator(baseline)
    candidate_denominator = _distribution_denominator(candidate)
    labels = sorted(
        (set(base_distribution) | set(candidate_distribution)) - {_UNKNOWN}
    )
    differences: dict[str, Any] = {}
    flagged: list[str] = []
    for label in labels:
        if not base_denominator or not candidate_denominator:
            difference_result: dict[str, Any] = {
                "status": _NOT_ESTIMABLE
                if base_denominator == 0 or candidate_denominator == 0
                else _UNKNOWN,
                "arm_a_share": _NOT_ESTIMABLE
                if base_denominator == 0
                else _UNKNOWN,
                "candidate_share": _NOT_ESTIMABLE
                if candidate_denominator == 0
                else _UNKNOWN,
                "absolute_difference": _NOT_ESTIMABLE,
                "flagged_at_10_percentage_points": _UNKNOWN,
            }
        else:
            base_count = base_distribution.get(label, {}).get("count", 0)
            candidate_count = candidate_distribution.get(label, {}).get("count", 0)
            base_share = Fraction(base_count, base_denominator)
            candidate_share = Fraction(candidate_count, candidate_denominator)
            difference = abs(candidate_share - base_share)
            flagged_value = difference >= Fraction(1, 10)
            if flagged_value:
                flagged.append(label)
            difference_result = {
                "status": "estimated",
                "arm_a_share": _percentage_payload(base_share),
                "candidate_share": _percentage_payload(candidate_share),
                "absolute_difference": _percentage_payload(difference),
                "flagged_at_10_percentage_points": flagged_value,
            }
        differences[label] = difference_result
    return {
        "status": "estimated" if base_denominator and candidate_denominator else _UNKNOWN,
        "resolved_model_share_differences": differences,
        "flagged_models": flagged,
        "fallback_share_difference": _share_difference(
            baseline["fallback_share"], candidate["fallback_share"]
        ),
        "unknown_model_share_difference": _share_difference(
            baseline["unknown_model_share"], candidate["unknown_model_share"]
        ),
    }


def _distribution_denominator(route: Mapping[str, Any]) -> Optional[int]:
    value = route.get("actual_attempts")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _share_fraction(share: Mapping[str, Any]) -> Optional[Fraction]:
    if share.get("status") != "complete":
        return None
    payload = share.get("share")
    if not isinstance(payload, Mapping):
        return None
    return Fraction(payload["numerator"], payload["denominator"])


def _share_difference(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    base_value = _share_fraction(baseline)
    candidate_value = _share_fraction(candidate)
    if base_value is None or candidate_value is None:
        status = (
            _NOT_ESTIMABLE
            if baseline.get("status") == _NOT_ESTIMABLE
            or candidate.get("status") == _NOT_ESTIMABLE
            else _UNKNOWN
        )
        return {
            "status": status,
            "difference": status,
            "any_difference": _UNKNOWN,
            "arm_a_share": baseline.get("share", _UNKNOWN),
            "candidate_share": candidate.get("share", _UNKNOWN),
        }
    difference = candidate_value - base_value
    return {
        "status": "different" if difference else "same",
        "difference": _percentage_payload(difference),
        "any_difference": bool(difference),
        "arm_a_share": baseline["share"],
        "candidate_share": candidate["share"],
    }


def _regression_guard_comparisons(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    exploration_groups = _complete_groups(rows, "exploration", ("A", "B", "D"))
    combat_groups = _complete_groups(rows, "combat", ("A", "D"))
    exploration: dict[str, Any] = {}
    for candidate in ("B", "D"):
        exploration[candidate] = _compare_guards(
            exploration_groups, "A", candidate
        )
    combat = {"D": _compare_guards(combat_groups, "A", "D")}
    return {
        "exploration": exploration,
        "combat": combat,
    }


def _compare_guards(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], baseline_arm: str, candidate_arm: str
) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    for guard in REGRESSION_GUARDS:
        base_values = [_guard_value(group[baseline_arm], guard) for group in groups]
        candidate_values = [_guard_value(group[candidate_arm], guard) for group in groups]
        if not groups or any(value is None for value in base_values + candidate_values):
            comparisons[guard] = {
                "status": _NOT_ESTIMABLE,
                "arm_a_count": _NOT_ESTIMABLE if not groups else _UNKNOWN,
                "candidate_count": _NOT_ESTIMABLE if not groups else _UNKNOWN,
                "maximum_allowed_candidate_count": _NOT_ESTIMABLE,
            }
            continue
        base_total = sum(value for value in base_values if value is not None)
        candidate_total = sum(value for value in candidate_values if value is not None)
        maximum = base_total + 1
        comparisons[guard] = {
            "status": "pass" if candidate_total <= maximum else "fail",
            "arm_a_count": base_total,
            "candidate_count": candidate_total,
            "difference": candidate_total - base_total,
            "maximum_allowed_candidate_count": maximum,
        }
    return comparisons


def _guard_value(row: Mapping[str, Any], guard: str) -> Optional[int]:
    value = _guard_counts(row).get(guard)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decision_rules(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exploration_groups = _complete_groups(rows, "exploration", ("A", "B", "D"))
    combat_groups = _complete_groups(rows, "combat", ("A", "D"))
    candidate = _select_exploration_candidate(exploration_groups)
    selected_arm = candidate["selected_arm"]
    if selected_arm in ("B", "D"):
        s2 = _evaluate_s2(exploration_groups, selected_arm)
    else:
        s2 = {
            "outcome": "inconclusive",
            "selected_arm": _UNKNOWN,
            "reason": "no deterministically selectable candidate",
        }
    zone_results = {
        arm: _evaluate_zone_rule(combat_groups, arm) for arm in ("A", "D")
    }
    return {
        "b_vs_d": candidate,
        "s2_spatial_packet": s2,
        "zones_close_enough": {
            "outcome": zone_results["D"]["outcome"],
            "decision_arm": "D",
            "by_arm": zone_results,
        },
    }


def _complete_groups(
    rows: Sequence[Mapping[str, Any]], block: str, required_arms: Sequence[str]
) -> list[dict[str, Mapping[str, Any]]]:
    candidates: dict[tuple[str, ...], dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        if row["block"].lower() != block or row["arm"] not in required_arms:
            continue
        if row["completed"] is not True:
            continue
        cap = _row_cap_accounting(row)
        if cap["disposition"] != "within_caps":
            continue
        party = row["party"]
        repeat = row["repeat"]
        if party == _UNKNOWN or repeat is None:
            continue
        if block == "exploration":
            script = row["script"]
            if script == _UNKNOWN:
                continue
            key = (party, script, str(repeat))
        else:
            key = (party, str(repeat))
        candidates[key][row["arm"]].append(row)
    complete: list[dict[str, Mapping[str, Any]]] = []
    for key in sorted(candidates):
        arms = candidates[key]
        if all(len(arms.get(arm, [])) == 1 for arm in required_arms):
            complete.append({arm: arms[arm][0] for arm in required_arms})
    return complete


def _select_exploration_candidate(
    groups: Sequence[Mapping[str, Mapping[str, Any]]]
) -> dict[str, Any]:
    rubric_delta = _paired_rubric_delta(groups, "D", "B")
    contradiction_reduction = _pooled_reduction(groups, "B", "D")
    rubric_better = _threshold_result(rubric_delta, Fraction(1, 2), "at_least")
    contradictions_better = _threshold_result(
        contradiction_reduction, Fraction(25), "at_least"
    )
    if rubric_better == "pass" or contradictions_better == "pass":
        selected = "D"
        outcome = "D_better"
        provisional = False
    elif rubric_better == _NOT_ESTIMABLE and contradictions_better == _NOT_ESTIMABLE:
        selected = "B"
        outcome = "inconclusive"
        provisional = True
    else:
        selected = "B"
        outcome = "B_default"
        provisional = False
    return {
        "outcome": outcome,
        "selected_arm": selected,
        "selection_is_provisional": provisional,
        "complete_matched_cells": len(groups),
        "d_minus_b_mean_rubric_points": rubric_delta,
        "rubric_threshold": rubric_better,
        "b_to_d_contradiction_reduction_percent": contradiction_reduction,
        "contradiction_threshold": contradictions_better,
    }


def _paired_rubric_delta(
    groups: Sequence[Mapping[str, Mapping[str, Any]]],
    minuend_arm: str,
    subtrahend_arm: str,
) -> Any:
    if not groups:
        return _NOT_ESTIMABLE
    deltas: list[Fraction] = []
    for group in groups:
        minuend = _rubric_mean(group[minuend_arm])
        subtrahend = _rubric_mean(group[subtrahend_arm])
        if minuend is None or subtrahend is None:
            return _NOT_ESTIMABLE
        deltas.append(minuend - subtrahend)
    mean = sum(deltas, Fraction(0)) / len(deltas)
    return _fraction_payload(mean)


def _rubric_mean(row: Mapping[str, Any]) -> Optional[Fraction]:
    ratings = _rubric_values(row["source"])
    values = [ratings.get(dimension) for dimension in range(1, 6)]
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Fraction(0)) / 5


def _pooled_reduction(
    groups: Sequence[Mapping[str, Mapping[str, Any]]],
    baseline_arm: str,
    candidate_arm: str,
) -> Any:
    if not groups:
        return _NOT_ESTIMABLE
    baseline = _pooled_spatial_rate(groups, baseline_arm)
    candidate = _pooled_spatial_rate(groups, candidate_arm)
    if baseline is None or candidate is None or baseline == 0:
        return _NOT_ESTIMABLE
    reduction = Fraction(100) * (baseline - candidate) / baseline
    return _fraction_payload(reduction)


def _pooled_spatial_rate(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], arm: str
) -> Optional[Fraction]:
    references: list[int] = []
    contradictions: list[int] = []
    for group in groups:
        row = group[arm]
        if row["spatial_references"] is None or row["spatial_contradictions"] is None:
            return None
        references.append(row["spatial_references"])
        contradictions.append(row["spatial_contradictions"])
    denominator = sum(references)
    if denominator == 0:
        return None
    return Fraction(sum(contradictions), denominator)


def _threshold_result(value: Any, threshold: Fraction, comparison: str) -> str:
    if value == _NOT_ESTIMABLE:
        return _NOT_ESTIMABLE
    if not isinstance(value, Mapping):
        return _UNKNOWN
    fraction = Fraction(value["numerator"], value["denominator"])
    if comparison == "at_least":
        return "pass" if fraction >= threshold else "fail"
    if comparison == "at_most":
        return "pass" if fraction <= threshold else "fail"
    raise ValueError("unsupported threshold comparison")


def _evaluate_s2(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], candidate_arm: str
) -> dict[str, Any]:
    if not groups:
        return {
            "outcome": "inconclusive",
            "selected_arm": candidate_arm,
            "reason": _NOT_ESTIMABLE,
            "complete_matched_cells": 0,
        }
    contradiction_reduction = _pooled_reduction(groups, "A", candidate_arm)
    contradiction_result = _threshold_result(
        contradiction_reduction, Fraction(50), "at_least"
    )
    rubric_delta = _paired_rubric_delta(groups, candidate_arm, "A")
    candidate_rubric_mean = _unweighted_rubric_mean(groups, candidate_arm)
    rubric_result = _rubric_gate(rubric_delta, candidate_rubric_mean)
    guard_comparison = _compare_guards(groups, "A", candidate_arm)
    guard_result = _all_guard_results(guard_comparison)
    input_token_comparison = _compare_input_tokens(groups, candidate_arm)
    latency_comparison = _compare_p95_latency(groups, candidate_arm)
    criteria = {
        "contradiction_reduction_at_least_50_percent": contradiction_result,
        "rubric_mean_increase_1_or_candidate_mean_4": rubric_result,
        "regression_guards_within_one_incident": guard_result,
        "input_tokens_per_turn_at_most_115_percent_of_a": input_token_comparison[
            "status"
        ],
        "p95_latency_at_most_110_percent_of_a": latency_comparison["status"],
    }
    if all(value == "pass" for value in criteria.values()):
        outcome = "adopt"
        reason = "all preregistered S2 criteria pass"
    else:
        outcome = "inconclusive"
        reason = "one or more preregistered criteria fail or are not estimable"
    return {
        "outcome": outcome,
        "selected_arm": candidate_arm,
        "reason": reason,
        "complete_matched_cells": len(groups),
        "criteria": criteria,
        "contradiction_reduction_percent": contradiction_reduction,
        "rubric_mean_increase_points": rubric_delta,
        "candidate_rubric_mean": candidate_rubric_mean,
        "regression_guards": guard_comparison,
        "input_tokens_per_turn": input_token_comparison,
        "p95_latency_seconds": latency_comparison,
    }


def _rubric_gate(delta: Any, candidate_mean: Any) -> str:
    if delta == _NOT_ESTIMABLE and candidate_mean == _NOT_ESTIMABLE:
        return _NOT_ESTIMABLE
    delta_pass = False
    mean_pass = False
    if isinstance(delta, Mapping):
        delta_pass = Fraction(delta["numerator"], delta["denominator"]) >= 1
    if isinstance(candidate_mean, Mapping):
        mean_pass = Fraction(
            candidate_mean["numerator"], candidate_mean["denominator"]
        ) >= 4
    if delta_pass or mean_pass:
        return "pass"
    if delta == _NOT_ESTIMABLE or candidate_mean == _NOT_ESTIMABLE:
        return _NOT_ESTIMABLE
    return "fail"


def _unweighted_rubric_mean(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], arm: str
) -> Any:
    if not groups:
        return _NOT_ESTIMABLE
    means = [_rubric_mean(group[arm]) for group in groups]
    if any(value is None for value in means):
        return _NOT_ESTIMABLE
    mean = sum((value for value in means if value is not None), Fraction(0)) / len(means)
    return _fraction_payload(mean)


def _all_guard_results(comparison: Mapping[str, Any]) -> str:
    values = [item["status"] for item in comparison.values()]
    if any(value == "fail" for value in values):
        return "fail"
    if all(value == "pass" for value in values):
        return "pass"
    return _NOT_ESTIMABLE


def _compare_input_tokens(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], candidate_arm: str
) -> dict[str, Any]:
    if not groups:
        return {
            "status": _NOT_ESTIMABLE,
            "arm_a": _NOT_ESTIMABLE,
            "candidate": _NOT_ESTIMABLE,
        }
    values: dict[str, tuple[int, int]] = {}
    for arm in ("A", candidate_arm):
        token_total = 0
        turn_total = 0
        for group in groups:
            cost = _cost_measure(group[arm])
            total = cost["input_tokens_total"]
            turns = cost["model_bearing_turns"]
            if not isinstance(total, int) or not isinstance(turns, int):
                return {
                    "status": _UNKNOWN,
                    "arm_a": _UNKNOWN,
                    "candidate": _UNKNOWN,
                }
            token_total += total
            turn_total += turns
        if turn_total == 0:
            return {
                "status": _NOT_ESTIMABLE,
                "arm_a": _NOT_ESTIMABLE,
                "candidate": _NOT_ESTIMABLE,
            }
        values[arm] = (token_total, turn_total)
    baseline = Fraction(*values["A"])
    candidate = Fraction(*values[candidate_arm])
    passes = candidate <= Fraction(115, 100) * baseline
    return {
        "status": "pass" if passes else "fail",
        "arm_a": _fraction_payload(baseline),
        "candidate": _fraction_payload(candidate),
        "maximum_candidate": _fraction_payload(Fraction(115, 100) * baseline),
    }


def _compare_p95_latency(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], candidate_arm: str
) -> dict[str, Any]:
    if not groups:
        return {
            "status": _NOT_ESTIMABLE,
            "arm_a": _NOT_ESTIMABLE,
            "candidate": _NOT_ESTIMABLE,
        }
    arm_values: dict[str, list[Fraction]] = {"A": [], candidate_arm: []}
    for group in groups:
        for arm in ("A", candidate_arm):
            raw_turns = group[arm]["source"].get("model_turns")
            if not isinstance(raw_turns, Sequence) or isinstance(raw_turns, (str, bytes)):
                return {
                    "status": _UNKNOWN,
                    "arm_a": _UNKNOWN,
                    "candidate": _UNKNOWN,
                }
            if not raw_turns:
                continue
            for turn in raw_turns:
                if not isinstance(turn, Mapping):
                    raise ValueError("each model turn must be an object")
                latency = _checked_seconds(turn.get("latency_seconds"), "latency_seconds")
                if latency is None:
                    return {
                        "status": _UNKNOWN,
                        "arm_a": _UNKNOWN,
                        "candidate": _UNKNOWN,
                    }
                arm_values[arm].append(latency)
    if not arm_values["A"] or not arm_values[candidate_arm]:
        return {
            "status": _NOT_ESTIMABLE,
            "arm_a": _NOT_ESTIMABLE,
            "candidate": _NOT_ESTIMABLE,
        }
    baseline = _nearest_rank(arm_values["A"], Fraction(95, 100))
    candidate = _nearest_rank(arm_values[candidate_arm], Fraction(95, 100))
    passes = candidate <= Fraction(110, 100) * baseline
    return {
        "status": "pass" if passes else "fail",
        "arm_a": _fraction_payload(baseline),
        "candidate": _fraction_payload(candidate),
        "maximum_candidate": _fraction_payload(Fraction(110, 100) * baseline),
        "method": "nearest-rank ceil(0.95*n)",
    }


def _nearest_rank(values: Sequence[Fraction], percentile: Fraction) -> Fraction:
    ordered = sorted(values)
    rank = (
        percentile.numerator * len(ordered) + percentile.denominator - 1
    ) // percentile.denominator
    return ordered[rank - 1]


def _evaluate_zone_rule(
    groups: Sequence[Mapping[str, Mapping[str, Any]]], arm: str
) -> dict[str, Any]:
    arm_rows = [group[arm] for group in groups]
    if not arm_rows:
        return {
            "outcome": "inconclusive",
            "zone_contradictions_per_10_rounds": _NOT_ESTIMABLE,
            "intent_success_percent": _NOT_ESTIMABLE,
            "complete_matched_combat_rows": 0,
        }
    zone_contradictions = 0
    rounds = 0
    zone_complete = True
    intent_successes = 0
    intent_rows_complete = True
    for row in arm_rows:
        data = _combat_measure(row)
        if not isinstance(data["zone_contradictions"], int) or not isinstance(
            data["observed_rounds"], int
        ):
            zone_complete = False
        else:
            zone_contradictions += data["zone_contradictions"]
            rounds += data["observed_rounds"]
        intent = data["intent_parse"]
        if intent["status"] != "complete":
            intent_rows_complete = False
        else:
            intent_successes += intent["exact_or_acceptable_count"]

    if not zone_complete:
        zone_rate: Any = _UNKNOWN
        zone_result = _UNKNOWN
    elif rounds == 0:
        zone_rate = _NOT_ESTIMABLE
        zone_result = _NOT_ESTIMABLE
    else:
        zone_rate = _fraction_payload(Fraction(zone_contradictions * 10, rounds))
        zone_result = "pass" if zone_contradictions * 10 <= rounds else "fail"

    if not intent_rows_complete:
        intent_rate: Any = _UNKNOWN
        intent_result = _UNKNOWN
    else:
        intent_denominator = 4 * len(arm_rows)
        intent_rate = _fraction_payload(
            Fraction(intent_successes * 100, intent_denominator)
        )
        intent_result = (
            "pass"
            if Fraction(intent_successes, intent_denominator) >= Fraction(9, 10)
            else "fail"
        )
    if zone_result == "fail" or intent_result == "fail":
        outcome = "fail"
    elif zone_result == "pass" and intent_result == "pass":
        outcome = "pass"
    else:
        outcome = "inconclusive"
    return {
        "outcome": outcome,
        "complete_matched_combat_rows": len(arm_rows),
        "zone_contradictions": zone_contradictions if zone_complete else _UNKNOWN,
        "observed_rounds": rounds if zone_complete else _UNKNOWN,
        "zone_contradictions_per_10_rounds": zone_rate,
        "zone_contradiction_threshold": zone_result,
        "exact_or_acceptable_count": intent_successes
        if intent_rows_complete
        else _UNKNOWN,
        "intent_parse_denominator": 4 * len(arm_rows),
        "intent_success_percent": intent_rate,
        "intent_threshold": intent_result,
    }


def _fraction_payload(value: Fraction) -> dict[str, Any]:
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    formatted_value = format(
        decimal_value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f"
    )
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "value": formatted_value,
    }


def _percentage_payload(value: Fraction) -> dict[str, Any]:
    payload = _fraction_payload(value)
    percentage = Decimal(value.numerator * 100) / Decimal(value.denominator)
    payload["percentage"] = format(
        percentage.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f"
    )
    return payload
