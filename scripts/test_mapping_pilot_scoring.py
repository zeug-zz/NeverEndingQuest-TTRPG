# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for preregistered mapping-pilot scoring."""

from __future__ import annotations

import json
import pathlib
import sys
import unittest
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    REGRESSION_GUARDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
    pre_request_guard,
    score_matrix,
    score_row,
    serialize_scoring_report,
)


def _ledger_observations(
    outcomes: tuple[str | None, ...] = ("exact", "exact", "acceptable", "wrong"),
    *,
    contradiction: bool = True,
) -> str:
    observations: list[dict[str, Any]] = [
        {
            "kind": "contradiction_claim",
            "category": "false_elevation_cover_or_engagement_relation",
            "contradiction": contradiction,
        }
    ]
    observations.extend(
        {"kind": "movement_parse_outcome", "classification": outcome}
        for outcome in outcomes
    )
    return json.dumps(observations, sort_keys=True, separators=(",", ":"))


def _turn(
    input_tokens: int = 100,
    output_tokens: int = 50,
    latency_seconds: float = 10.0,
    cost_usd: float = 0.01,
    classifier_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_seconds": latency_seconds,
        "cost_usd": cost_usd,
        "classifier_calls": classifier_calls if classifier_calls is not None else [],
    }


def _base_row(row_id: str = "E01", arm: str = "A", **updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_id": row_id,
        "arm": arm,
        "block": "exploration",
        "party": "P1",
        "script": "interior.json",
        "repeat": 1,
        "completed": True,
        "attempt_count": 1,
        "elapsed_seconds": 10,
        "spatial_references": 10,
        "spatial_contradictions": 1,
        "knowledge_leakage_count": 0,
        "assistant_turns": 4,
        "continuity_assertions": {
            "return_journey": [True, True],
            "changed_back_door": [True],
            "viewpoint_switch": [True, True],
        },
        "observed_combat_rounds": 10,
        "zone_ledger_observations": _ledger_observations(),
        "regression_guards": {name: 0 for name in REGRESSION_GUARDS},
        "model_turns": [_turn()],
        "provider_calls": [],
        "rubric_ratings": {str(number): 3 for number in range(1, 7)},
    }
    row.update(updates)
    return row


class MappingPilotScoringTests(unittest.TestCase):
    def test_section_7_1_objective_measures_and_serialized_ledger(self) -> None:
        row = _base_row(
            spatial_references=20,
            spatial_contradictions=3,
            knowledge_leakage_count=1,
            assistant_turns=4,
            observed_combat_rounds=20,
            zone_ledger_observations=_ledger_observations(
                ("exact", "acceptable", "wrong", "refused")
            ),
        )
        scored = score_row(row)
        measures = scored["measures"]
        self.assertEqual(measures["spatial"]["contradictions_per_100_references"], 15)
        self.assertEqual(
            measures["knowledge_leakage"]["leakage_per_100_assistant_turns"], 25
        )
        self.assertEqual(measures["continuity"]["return_journey"]["status"], "pass")
        self.assertEqual(measures["continuity"]["changed_back_door"]["status"], "pass")
        self.assertEqual(measures["continuity"]["viewpoint_switch"]["status"], "pass")
        combat = measures["combat"]
        self.assertEqual(combat["zone_contradictions"], 1)
        self.assertEqual(combat["zone_contradiction_categories"], {
            "false_elevation_cover_or_engagement_relation": 1
        })
        self.assertEqual(combat["contradictions_per_10_rounds"], 0.5)
        self.assertEqual(combat["intent_parse"]["outcome_counts"]["exact"], 1)
        self.assertEqual(combat["intent_parse"]["outcome_counts"]["acceptable"], 1)
        self.assertEqual(combat["intent_parse"]["exact_or_acceptable_percent"], 50)

    def test_rates_with_zero_denominator_are_not_estimable_and_missing_is_unknown(self) -> None:
        zero = score_row(
            _base_row(
                spatial_references=0,
                spatial_contradictions=0,
                assistant_turns=0,
                knowledge_leakage_count=0,
                observed_combat_rounds=0,
            )
        )["measures"]
        self.assertEqual(zero["spatial"]["contradictions_per_100_references"], "not estimable")
        self.assertEqual(
            zero["knowledge_leakage"]["leakage_per_100_assistant_turns"],
            "not estimable",
        )
        self.assertEqual(zero["combat"]["contradictions_per_10_rounds"], "not estimable")

        missing = score_row(
            _base_row(
                spatial_references=None,
                spatial_contradictions=None,
                knowledge_leakage_count=None,
                assistant_turns=None,
                observed_combat_rounds=None,
                zone_ledger_observations=None,
            )
        )["measures"]
        self.assertEqual(missing["spatial"]["contradictions_per_100_references"], "unknown")
        self.assertEqual(
            missing["knowledge_leakage"]["leakage_per_100_assistant_turns"], "unknown"
        )
        self.assertEqual(missing["combat"]["zone_contradictions"], "unknown")

    def test_unclassified_or_missing_ledger_outcomes_are_not_zero_successes(self) -> None:
        partial = score_row(
            _base_row(
                zone_ledger_observations=_ledger_observations(
                    ("exact", None, "acceptable")
                )
            )
        )["measures"]["combat"]["intent_parse"]
        self.assertEqual(partial["observed_utterances"], 3)
        self.assertEqual(partial["unclassified_utterances"], 1)
        self.assertEqual(partial["exact_or_acceptable_percent"], "unknown")

        missing = score_row(_base_row(zone_ledger_observations=None))["measures"]["combat"]
        self.assertEqual(missing["zone_contradictions"], "unknown")
        self.assertEqual(missing["intent_parse"]["outcome_counts"], "unknown")

    def test_scorer_requires_serialized_zone_ledger_observations(self) -> None:
        with self.assertRaisesRegex(ValueError, "serialized JSON"):
            score_row(_base_row(zone_ledger_observations=[]))
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            score_row(_base_row(zone_ledger_observations="{"))

    def test_human_ratings_are_inputs_and_absent_ratings_stay_missing(self) -> None:
        missing = score_row(_base_row(rubric_ratings=None))["measures"]["rubric"]
        self.assertEqual(set(missing["dimensions"].values()), {"missing"})
        self.assertEqual(missing["mean_dimensions_1_to_5"], "missing")
        provided = score_row(
            _base_row(rubric_ratings={"1": 1, "2": 2, "3": 3, "4": 4, "5": 5})
        )["measures"]["rubric"]
        self.assertEqual(provided["dimensions"]["6"], "missing")
        self.assertEqual(provided["mean_dimensions_1_to_5"], 3)
        self.assertEqual(score_row(_base_row(sketch_test=None))["measures"]["sketch_test"], "missing")

    def test_sketch_anchor_accuracy_uses_only_supplied_counts_and_zero_is_not_estimable(self) -> None:
        result = score_row(
            _base_row(sketch_test={"anchors_correct": 3, "anchors_total": 4})
        )["measures"]["sketch_test"]
        self.assertEqual(result["anchor_placement_percent"], 75)
        self.assertEqual(result["owner_rating"], "missing")
        empty = score_row(
            _base_row(sketch_test={"anchors_correct": 0, "anchors_total": 0})
        )["measures"]["sketch_test"]
        self.assertEqual(empty["anchor_placement_percent"], "not estimable")

    def test_unknown_and_incomplete_token_cost_and_latency_data_never_become_zero(self) -> None:
        result = score_row(
            _base_row(model_turns=[{
                "input_tokens": None,
                "output_tokens": 30,
                "latency_seconds": None,
                "cost_usd": None,
                "classifier_calls": [{
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "latency_seconds": None,
                    "cost_usd": None,
                }],
            }])
        )["measures"]["cost"]
        self.assertEqual(result["input_tokens_total"], "unknown")
        self.assertEqual(result["input_tokens_per_model_turn"], "unknown")
        self.assertEqual(result["output_tokens_per_model_turn"], 32)
        self.assertEqual(result["p50_turn_latency_seconds"], "unknown")
        self.assertEqual(result["p95_turn_latency_seconds"], "unknown")
        self.assertEqual(result["classifier_latency_total_seconds"], "unknown")
        self.assertEqual(result["total_cost_usd"], "unknown")
        self.assertEqual(result["cost_usd_per_model_turn"], "unknown")

    def test_classifier_tokens_and_cost_are_allocated_to_triggering_turn(self) -> None:
        result = score_row(
            _base_row(
                model_turns=[_turn(
                    100,
                    50,
                    10,
                    0.01,
                    [{
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "latency_seconds": 2,
                        "cost_usd": 0.02,
                    }],
                )]
            )
        )["measures"]["cost"]
        self.assertEqual(result["input_tokens_total"], 120)
        self.assertEqual(result["output_tokens_total"], 55)
        self.assertEqual(result["input_tokens_per_model_turn"], 120)
        self.assertEqual(result["output_tokens_per_model_turn"], 55)
        self.assertEqual(result["classifier_call_count"], 1)
        self.assertEqual(result["classifier_latency_total_seconds"], 2)
        self.assertEqual(result["input_tokens_by_model_turn"], [120])
        self.assertEqual(result["output_tokens_by_model_turn"], [55])
        self.assertEqual(result["classifier_latency_by_model_turn_seconds"], [2])
        self.assertEqual(result["total_cost_usd"], 0.03)

    def test_latency_percentiles_use_nearest_rank_and_empty_turns_are_not_estimable(self) -> None:
        turns = [_turn(latency_seconds=value) for value in range(1, 21)]
        cost = score_row(_base_row(model_turns=turns))["measures"]["cost"]
        self.assertEqual(cost["p50_turn_latency_seconds"], 10)
        self.assertEqual(cost["p95_turn_latency_seconds"], 19)
        empty = score_row(_base_row(model_turns=[]))["measures"]["cost"]
        self.assertEqual(empty["p50_turn_latency_seconds"], "not estimable")
        self.assertEqual(empty["total_cost_usd"], "not estimable")

    def test_regression_guards_are_independent_and_not_blended(self) -> None:
        rows = [
            _base_row("E01-A", "A", regression_guards={name: 0 for name in REGRESSION_GUARDS}),
            _base_row("E01-B", "B", regression_guards={
                "mechanics_errors": 2,
                "character_knowledge_violations": 0,
                "validation_retries": 0,
                "failed_turns": 0,
            }),
            _base_row("E01-D", "D", regression_guards={name: 0 for name in REGRESSION_GUARDS}),
        ]
        report = score_matrix(rows)
        b_guards = report["regression_guard_comparisons"]["exploration"]["B"]
        self.assertEqual(b_guards["mechanics_errors"]["status"], "fail")
        self.assertEqual(b_guards["character_knowledge_violations"]["status"], "pass")
        self.assertEqual(b_guards["validation_retries"]["status"], "pass")
        self.assertEqual(b_guards["failed_turns"]["status"], "pass")
        self.assertEqual(report["rows"][1]["regression_guards"]["mechanics_errors"], 2)

    def test_pre_request_guard_refuses_at_every_attempt_and_time_cap(self) -> None:
        row_attempt_cap = pre_request_guard(
            ROW_ATTEMPT_CAP,
            0,
            0,
            0,
        )
        self.assertEqual(row_attempt_cap["decision"], "refuse")
        self.assertIn("row_attempt_cap", row_attempt_cap["reasons"])
        self.assertEqual(row_attempt_cap["actual_counts"]["row_attempts"], 35)

        matrix_attempt_cap = pre_request_guard(
            0,
            0,
            MATRIX_ATTEMPT_CAP,
            0,
        )
        self.assertEqual(matrix_attempt_cap["decision"], "refuse")
        self.assertIn("matrix_attempt_cap", matrix_attempt_cap["reasons"])
        self.assertEqual(matrix_attempt_cap["actual_counts"]["matrix_attempts"], 800)

        row_time_cap = pre_request_guard(
            0,
            ROW_WALL_TIME_CAP_SECONDS,
            0,
            0,
        )
        self.assertIn("row_wall_time_cap", row_time_cap["reasons"])
        matrix_time_cap = pre_request_guard(
            0,
            0,
            0,
            MATRIX_WALL_TIME_CAP_SECONDS,
        )
        self.assertIn("matrix_wall_time_cap", matrix_time_cap["reasons"])

    def test_pre_request_guard_allows_below_caps_and_preserves_overages(self) -> None:
        allowed = pre_request_guard(34, 1499, 799, 21599)
        self.assertEqual(allowed["decision"], "allow")
        refused = pre_request_guard(36, 1501, 812, 21605)
        self.assertEqual(refused["decision"], "refuse")
        self.assertEqual(refused["actual_counts"], {
            "row_attempts": 36,
            "row_elapsed_seconds": 1501,
            "matrix_attempts": 812,
            "matrix_elapsed_seconds": 21605,
        })
        unknown = pre_request_guard(None, 0, 0, 0)
        self.assertEqual(unknown["decision"], "refuse")
        self.assertIn("attempt_count_unknown", unknown["reasons"])

    def test_row_and_matrix_cap_accounting_preserve_actual_counts_and_block(self) -> None:
        row = _base_row(
            attempt_count=ROW_ATTEMPT_CAP,
            elapsed_seconds=ROW_WALL_TIME_CAP_SECONDS,
        )
        scored = score_row(row)
        self.assertEqual(scored["cap_accounting"]["disposition"], "BLOCKED")
        self.assertEqual(scored["cap_accounting"]["actual_attempts"], 35)
        self.assertEqual(scored["cap_accounting"]["actual_wall_time_seconds"], 1500)
        matrix = score_matrix([_base_row("E01", "A", attempt_count=800)])
        self.assertEqual(matrix["matrix_cap_accounting"]["disposition"], "BLOCKED")
        self.assertEqual(matrix["matrix_cap_accounting"]["actual_attempts"], 800)

    def test_cap_accounting_unknown_is_blocked_not_pass(self) -> None:
        scored = score_row(_base_row(attempt_count=None, elapsed_seconds=None))
        self.assertEqual(scored["cap_accounting"]["disposition"], "BLOCKED")
        matrix = score_matrix([_base_row("E01", "A", attempt_count=None)])
        self.assertEqual(matrix["matrix_cap_accounting"]["disposition"], "BLOCKED")

    def test_resolved_model_imbalance_uses_exact_ten_percentage_point_threshold(self) -> None:
        a_calls = [
            {"resolved_model": "model-x", "fallback": False} for _ in range(1)
        ] + [
            {"resolved_model": "model-y", "fallback": False} for _ in range(9)
        ]
        b_calls = [
            {"resolved_model": "model-x", "fallback": True} for _ in range(4)
        ] + [
            {"resolved_model": "model-y", "fallback": False} for _ in range(15)
        ] + [{"resolved_model": "openrouter/auto", "fallback": False}]
        report = score_matrix([
            _base_row("E01-A", "A", attempt_count=10, provider_calls=a_calls),
            _base_row("E01-B", "B", attempt_count=20, provider_calls=b_calls),
        ])
        comparison = report["route_confounds"]["comparisons"]["B"]
        self.assertIn("model-x", comparison["flagged_models"])
        self.assertIn("model-y", comparison["flagged_models"])
        self.assertEqual(
            comparison["resolved_model_share_differences"]["model-x"][
                "absolute_difference"
            ]["percentage"],
            "10.0000",
        )
        self.assertTrue(comparison["resolved_model_share_differences"]["model-x"][
            "flagged_at_10_percentage_points"
        ])
        self.assertEqual(
            report["route_by_arm"]["B"]["unknown_model_share"]["unknown_model_calls"],
            1,
        )

    def test_resolved_model_difference_below_ten_points_is_not_flagged(self) -> None:
        report = score_matrix([
            _base_row(
                "E01-A",
                "A",
                attempt_count=3,
                provider_calls=[
                    {"resolved_model": "model-x"},
                    {"resolved_model": "model-y"},
                    {"resolved_model": "model-y"},
                ],
            ),
            _base_row(
                "E01-B",
                "B",
                attempt_count=4,
                provider_calls=[
                    {"resolved_model": "model-x"},
                    {"resolved_model": "model-y"},
                    {"resolved_model": "model-y"},
                    {"resolved_model": "model-y"},
                ],
            ),
        ])
        comparison = report["route_confounds"]["comparisons"]["B"]
        model_x = comparison["resolved_model_share_differences"]["model-x"]
        self.assertEqual(model_x["absolute_difference"]["numerator"], 1)
        self.assertEqual(model_x["absolute_difference"]["denominator"], 12)
        self.assertFalse(model_x["flagged_at_10_percentage_points"])
        self.assertNotIn("model-x", comparison["flagged_models"])

    def test_all_auto_empty_none_and_unknown_resolved_models_are_unknown(self) -> None:
        rows = [
            _base_row(
                "E01-A",
                "A",
                attempt_count=4,
                provider_calls=[
                    {"resolved_model": value, "fallback": False}
                    for value in ("openrouter/auto", "", None, "unknown")
                ],
            )
        ]
        route = score_matrix(rows)["route_by_arm"]["A"]
        self.assertEqual(
            route["distributions"]["resolved_model"]["unknown"]["count"], 4
        )
        self.assertEqual(route["unknown_model_share"]["share"]["numerator"], 1)
        self.assertEqual(route["unknown_model_share"]["share"]["denominator"], 1)

    def test_fallback_and_unknown_model_share_differences_are_reported(self) -> None:
        rows = [
            _base_row(
                "E01-A",
                "A",
                attempt_count=4,
                provider_calls=[
                    {"resolved_model": "model-x", "fallback": False}
                    for _ in range(4)
                ],
            ),
            _base_row(
                "E01-B",
                "B",
                attempt_count=4,
                provider_calls=[
                    {"resolved_model": "unknown", "fallback": True},
                    {"resolved_model": "model-x", "fallback": False},
                    {"resolved_model": "model-x", "fallback": False},
                    {"resolved_model": "model-x", "fallback": False},
                ],
            ),
        ]
        report = score_matrix(rows)
        comparison = report["route_confounds"]["comparisons"]["B"]
        self.assertEqual(comparison["fallback_share_difference"]["status"], "different")
        self.assertTrue(comparison["fallback_share_difference"]["any_difference"])
        self.assertEqual(
            comparison["unknown_model_share_difference"]["status"], "different"
        )
        self.assertTrue(
            comparison["unknown_model_share_difference"]["any_difference"]
        )
        self.assertIn("requested_model", report["route_by_arm"]["A"]["distributions"])
        self.assertIn("provider", report["route_by_arm"]["A"]["distributions"])
        self.assertIn("observed_upstream_provider", report["route_by_arm"]["A"]["distributions"])

    def test_incomplete_route_and_fallback_data_are_reported_partial_not_as_zero(self) -> None:
        report = score_matrix([
            _base_row(
                "E01-A",
                "A",
                attempt_count=2,
                provider_calls=[{"resolved_model": "model-x"}],
            ),
            _base_row(
                "E01-B",
                "B",
                attempt_count=2,
                provider_calls=[{"resolved_model": "model-x"}],
            ),
        ])
        route_a = report["route_by_arm"]["A"]
        self.assertEqual(route_a["fallback_share"]["status"], "partial")
        self.assertEqual(route_a["fallback_share"]["share"], "unknown")
        comparison = report["route_confounds"]["comparisons"]["B"]
        self.assertEqual(comparison["fallback_share_difference"]["status"], "unknown")

    def test_fixed_decision_rules_use_complete_matches_and_preregistered_thresholds(self) -> None:
        rows = []
        for arm, contradictions, rating, tokens, latency in (
            ("A", 40, 3, 100, 10),
            ("B", 30, 3.5, 112, 10.5),
            ("D", 20, 4, 115, 11),
        ):
            rows.append(_base_row(
                "E01-" + arm,
                arm,
                spatial_references=100,
                spatial_contradictions=contradictions,
                rubric_ratings={str(number): rating for number in range(1, 6)},
                model_turns=[_turn(input_tokens=tokens, latency_seconds=latency)],
            ))
        for arm in ("A", "D"):
            rows.append(_base_row(
                "C01-" + arm,
                arm,
                block="combat",
                script="combat.json",
                observed_combat_rounds=10,
                zone_ledger_observations=_ledger_observations(
                    ("exact", "exact", "acceptable", "exact")
                ),
            ))
        report = score_matrix(rows)
        rules = report["decision_rules"]
        self.assertEqual(rules["b_vs_d"]["outcome"], "D_better")
        self.assertEqual(rules["b_vs_d"]["selected_arm"], "D")
        self.assertEqual(rules["s2_spatial_packet"]["outcome"], "adopt")
        self.assertTrue(all(
            result == "pass"
            for result in rules["s2_spatial_packet"]["criteria"].values()
        ))
        self.assertEqual(rules["zones_close_enough"]["outcome"], "pass")

    def test_missing_decision_evidence_is_inconclusive_and_b_is_only_provisional(self) -> None:
        rows = [
            _base_row("E01-A", "A", rubric_ratings=None, spatial_references=0,
                      spatial_contradictions=0),
            _base_row("E01-B", "B", rubric_ratings=None, spatial_references=0,
                      spatial_contradictions=0),
            _base_row("E01-D", "D", rubric_ratings=None, spatial_references=0,
                      spatial_contradictions=0),
        ]
        rules = score_matrix(rows)["decision_rules"]
        self.assertEqual(rules["b_vs_d"]["outcome"], "inconclusive")
        self.assertEqual(rules["b_vs_d"]["selected_arm"], "B")
        self.assertTrue(rules["b_vs_d"]["selection_is_provisional"])
        self.assertEqual(rules["s2_spatial_packet"]["outcome"], "inconclusive")

    def test_serialization_is_sorted_compact_ascii_and_deterministic(self) -> None:
        report = score_matrix([_base_row("E02", "A"), _base_row("E01", "A")])
        first = serialize_scoring_report(report)
        self.assertEqual(first, serialize_scoring_report(report))
        first.encode("ascii")
        self.assertTrue(first.startswith('{"caps":'))
        self.assertEqual(
            [row["row_id"] for row in report["rows"]], ["E01", "E02"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
