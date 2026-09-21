#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free tests for the Jev Phase 0 eval tooling.

Covers scripts/extract_jev_eval_set.py and scripts/spike_jev_decisions.py.
No network calls are made: live transport paths use mocked responses, and
fixture mode uses the deterministic FakeTransport.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent


def _load_sibling_module(name: str, filename: str) -> Any:
    """Load a sibling script as a module without relying on package layout."""
    spec = importlib.util.spec_from_file_location(name, TEST_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


extractor = _load_sibling_module("extract_jev_eval_set", "extract_jev_eval_set.py")
spike = _load_sibling_module("spike_jev_decisions", "spike_jev_decisions.py")


def _assistant(actions: List[str]) -> str:
    return json.dumps({"narration": "text", "actions": [{"action": a} for a in actions]})


class TestActionParsing(unittest.TestCase):
    def test_filters_update_time(self) -> None:
        names = extractor._non_time_actions(_assistant(["updateTime", "requestRoll"]))
        self.assertEqual(names, ["requestRoll"])

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(extractor._non_time_actions("not json at all"))

    def test_missing_actions_returns_empty(self) -> None:
        self.assertEqual(extractor._non_time_actions(json.dumps({"narration": "x"})), [])

    def test_non_dict_actions_entry_ignored(self) -> None:
        payload = json.dumps({"actions": ["requestRoll", {"action": "rest"}]})
        self.assertEqual(extractor._non_time_actions(payload), ["rest"])


class TestExtractHistoryCases(unittest.TestCase):
    def _history(self) -> List[Dict[str, Any]]:
        return [
            {"role": "user", "content": "--- WORLD STATE ---\nCurrent location: X"},
            {"role": "assistant", "content": _assistant(["requestRoll", "updateTime"])},
            {"role": "user", "content": "I say hello to the guard."},
            {"role": "assistant", "content": _assistant(["updateTime"])},
            {"role": "user", "content": "Error Note: previous response failed validation"},
            {"role": "assistant", "content": "not json"},
        ]

    def test_extracts_labeled_pairs(self) -> None:
        cases, skipped = extractor.extract_history_cases(self._history())
        self.assertEqual(len(cases), 2)
        self.assertTrue(cases[0]["label_requires_actions"])
        self.assertFalse(cases[1]["label_requires_actions"])
        self.assertEqual(cases[0]["label_strength"], "strong")
        self.assertEqual(skipped["excluded_retry_correction_note"], 1)

    def test_skips_module_creation_prompt(self) -> None:
        history = [
            {"role": "user", "content": "You are a master storyteller, cartographer of myth and legend"},
            {"role": "assistant", "content": _assistant(["createNewModule"])},
        ]
        cases, skipped = extractor.extract_history_cases(history)
        self.assertEqual(cases, [])
        self.assertEqual(skipped["excluded_module_creation_prompt"], 1)

    def test_breaks_on_next_user_without_assistant(self) -> None:
        history = [
            {"role": "user", "content": "first turn"},
            {"role": "user", "content": "second turn"},
            {"role": "assistant", "content": _assistant(["requestRoll"])},
        ]
        cases, skipped = extractor.extract_history_cases(history)
        self.assertEqual(len(cases), 1)
        self.assertEqual(skipped["no_next_assistant"], 1)

    def test_skips_unparseable_assistant(self) -> None:
        history = [
            {"role": "user", "content": "a turn"},
            {"role": "assistant", "content": "plain narration, no json"},
        ]
        cases, skipped = extractor.extract_history_cases(history)
        self.assertEqual(cases, [])
        self.assertEqual(skipped["unparseable_assistant"], 1)

    def test_truncates_state(self) -> None:
        history = [
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": _assistant(["requestRoll"])},
        ]
        cases, _ = extractor.extract_history_cases(history, max_state_chars=10)
        self.assertTrue(cases[0]["truncated"])
        self.assertEqual(cases[0]["state_chars"], 10)

    def test_metadata_active_pc(self) -> None:
        history = [
            {"role": "user", "content": "a turn", "active_pc": "Acheron"},
            {"role": "assistant", "content": _assistant(["requestRoll"])},
        ]
        cases, _ = extractor.extract_history_cases(history)
        self.assertEqual(cases[0]["meta"].get("active_pc"), "Acheron")


class TestExtractRejectedCases(unittest.TestCase):
    def _records(self) -> List[Dict[str, Any]]:
        return [
            {
                "timestamp": "t1",
                "user_input": "I open the chest.",
                "rejected_response": _assistant(["updateCharacterInfo", "updateTime"]),
                "rejection_reason": "missing action",
                "module": "M",
                "location_id": "L1",
                "location_name": "Hall",
            },
            {"user_input": "I nod quietly.", "rejected_response": _assistant(["updateTime"])},
            {"user_input": "broken", "rejected_response": "not json"},
        ]

    def test_weak_labels(self) -> None:
        cases, skipped = extractor.extract_rejected_cases(self._records())
        self.assertEqual(len(cases), 2)
        self.assertTrue(cases[0]["label_requires_actions"])
        self.assertFalse(cases[1]["label_requires_actions"])
        self.assertEqual(cases[0]["label_strength"], "weak")
        self.assertEqual(skipped["unparseable_rejected_response"], 1)

    def test_metadata_captured(self) -> None:
        cases, _ = extractor.extract_rejected_cases(self._records())
        meta = cases[0]["meta"]
        self.assertEqual(meta.get("module"), "M")
        self.assertEqual(meta.get("location_id"), "L1")
        self.assertIn("rejection_reason", meta)


class TestDedupeAndSummary(unittest.TestCase):
    def test_dedupe_prefers_strong(self) -> None:
        weak = extractor._make_case("rej-1", "rejected_turns", "same state", True, "weak", "e", {}, 100)
        strong = extractor._make_case("hist-1", "conversation_history", "same state", True, "strong", "e", {}, 100)
        deduped, removed = extractor.dedupe_cases([weak, strong])
        self.assertEqual(removed, 1)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["label_strength"], "strong")

    def test_summary_counts(self) -> None:
        cases = [
            extractor._make_case("a", "conversation_history", "one", True, "strong", "e", {}, 100),
            extractor._make_case("b", "rejected_turns", "two", False, "weak", "e", {}, 100),
        ]
        summary = extractor.summarize_cases(cases, {})
        self.assertEqual(summary["total_cases"], 2)
        self.assertEqual(summary["by_label"]["requires_actions_true"], 1)
        self.assertEqual(summary["by_strength"]["strong"], 1)
        self.assertEqual(summary["state_chars"]["max"], 3)


class TestEvaluatorCLI(unittest.TestCase):
    def test_build_eval_set_and_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            history_path = tmp_path / "history.json"
            rejected_path = tmp_path / "rejected.jsonl"
            out_path = tmp_path / "eval.jsonl"
            history_path.write_text(
                json.dumps(
                    [
                        {"role": "user", "content": "I open the door."},
                        {"role": "assistant", "content": _assistant(["requestRoll"])},
                    ]
                ),
                encoding="utf-8",
            )
            rejected_path.write_text(
                json.dumps({"user_input": "I nod.", "rejected_response": _assistant(["updateTime"])}) + "\n",
                encoding="utf-8",
            )
            code = extractor.main(
                [
                    "--history",
                    str(history_path),
                    "--rejected",
                    str(rejected_path),
                    "--out",
                    str(out_path),
                ]
            )
            self.assertEqual(code, 0)
            lines = out_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_invalid_source_returns_error(self) -> None:
        self.assertEqual(extractor.main(["--sources", "history,bogus"]), 2)

    def test_parse_sources_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            extractor.parse_sources("nope")


class TestQuestions(unittest.TestCase):
    def test_question_shape(self) -> None:
        questions = spike.build_questions()
        self.assertIn(spike.QUESTION_ID, questions)
        question = questions[spike.QUESTION_ID]
        self.assertEqual(question["type"], "noul")
        self.assertIn("updateTime", question["instructions"])
        self.assertIn("true", question["criteria"])
        self.assertIn("false", question["criteria"])
        self.assertTrue(question["criteria"]["true"])
        self.assertTrue(question["criteria"]["false"])


class TestParseDecisionResponse(unittest.TestCase):
    def test_canonical_shape(self) -> None:
        payload = {
            "model": "jev-1.13.0",
            "answers": {"action_required": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 296, "output_tokens": 20},
        }
        probability, usage = spike.parse_decision_response(payload)
        self.assertAlmostEqual(probability, 0.95)
        self.assertEqual(spike.extract_usage_tokens(usage), 296)

    def test_direct_float(self) -> None:
        probability, _ = spike.parse_decision_response({"answers": {"action_required": 0.42}})
        self.assertAlmostEqual(probability, 0.42)

    def test_string_value_key(self) -> None:
        probability, _ = spike.parse_decision_response({"answers": {"action_required": {"value": "0.75"}}})
        self.assertAlmostEqual(probability, 0.75)

    def test_missing_answer(self) -> None:
        probability, _ = spike.parse_decision_response({"answers": {}})
        self.assertIsNone(probability)

    def test_non_dict_payload(self) -> None:
        probability, usage = spike.parse_decision_response("nope")
        self.assertIsNone(probability)
        self.assertEqual(usage, {})

    def test_clamps_out_of_range(self) -> None:
        probability, _ = spike.parse_decision_response({"answers": {"action_required": {"noul": 1.7}}})
        self.assertEqual(probability, 1.0)

    def test_bool_answer(self) -> None:
        probability, _ = spike.parse_decision_response({"answers": {"action_required": True}})
        self.assertEqual(probability, 1.0)

    def test_prompt_tokens_fallback(self) -> None:
        _, usage = spike.parse_decision_response(
            {"answers": {"action_required": {"noul": 0.5}}, "usage": {"prompt_tokens": 321}}
        )
        self.assertEqual(spike.extract_usage_tokens(usage), 321)


class TestPlayerTail(unittest.TestCase):
    def test_extracts_after_last_player_marker(self) -> None:
        state = "--- WORLD STATE ---\nCurrent location: X\nPlayer: [Acheron]: \"Let us search the chamber.\""
        tail = spike.derive_player_tail(state)
        self.assertTrue(tail.startswith("Player: "))
        self.assertNotIn("WORLD STATE", tail)

    def test_no_marker_returns_full_state(self) -> None:
        state = "I search the chamber for clues."
        self.assertEqual(spike.derive_player_tail(state), state)


class TestScoring(unittest.TestCase):
    def _results(self) -> List[Dict[str, Any]]:
        return [
            {"label": True, "probability": 0.9, "source": "conversation_history", "label_strength": "strong"},
            {"label": True, "probability": 0.4, "source": "conversation_history", "label_strength": "strong"},
            {"label": False, "probability": 0.1, "source": "rejected_turns", "label_strength": "weak"},
            {"label": False, "probability": 0.8, "source": "rejected_turns", "label_strength": "weak"},
        ]

    def test_confusion_matrix(self) -> None:
        row = spike.confusion_at(self._results(), 0.5)
        self.assertEqual((row["tp"], row["tn"], row["fp"], row["fn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(row["agreement"], 0.5)
        self.assertAlmostEqual(row["fn_rate"], 0.5)
        self.assertAlmostEqual(row["fp_rate"], 0.5)

    def test_lower_threshold_removes_false_negatives(self) -> None:
        row = spike.confusion_at(self._results(), 0.3)
        self.assertEqual((row["tp"], row["tn"], row["fp"], row["fn"]), (2, 1, 1, 0))
        self.assertAlmostEqual(row["fn_rate"], 0.0)

    def test_gate_pass_recommends_permissive_threshold(self) -> None:
        sweep = spike.build_sweep(self._results(), (0.3, 0.5, 0.95))
        gate = spike.recommend_threshold(sweep, agreement_min=0.75, fn_rate_max=0.0)
        self.assertTrue(gate["passed"])
        self.assertAlmostEqual(gate["recommended_threshold"], 0.3)

    def test_gate_fail_picks_safest_row(self) -> None:
        sweep = spike.build_sweep(self._results(), (0.5, 0.95))
        gate = spike.recommend_threshold(sweep, agreement_min=0.99, fn_rate_max=0.0)
        self.assertFalse(gate["passed"])
        self.assertAlmostEqual(gate["recommended_threshold"], 0.5)

    def test_latency_stats(self) -> None:
        stats = spike.latency_stats([100.0, 200.0, 300.0])
        self.assertAlmostEqual(stats["mean_ms"], 200.0)
        self.assertAlmostEqual(stats["p50_ms"], 200.0)
        self.assertAlmostEqual(stats["p90_ms"], 300.0)

    def test_cost_estimate(self) -> None:
        self.assertAlmostEqual(spike.estimate_cost_usd(1_000_000), 0.042)
        self.assertAlmostEqual(spike.estimate_cost_usd(0), 0.0)


class TestKeyResolution(unittest.TestCase):
    def test_repo_root_on_sys_path(self) -> None:
        import sys

        self.assertIn(str(spike.REPO_ROOT), sys.path)

    def test_env_precedence(self) -> None:
        key = spike.resolve_api_key({"OPENROUTER_API_KEY": "  abc  "})
        self.assertEqual(key, "abc")

    def test_config_fallback(self) -> None:
        with mock.patch.object(spike, "_load_config_key", return_value="cfg"):
            self.assertEqual(spike.resolve_api_key({}), "cfg")

    def test_none_when_absent(self) -> None:
        with mock.patch.object(spike, "_load_config_key", return_value=None):
            self.assertIsNone(spike.resolve_api_key({}))


class TestTransports(unittest.TestCase):
    def test_fake_transport_records_calls(self) -> None:
        transport = spike.FakeTransport({"x": 0.9})
        outcome = transport.decide("some state", "x")
        self.assertAlmostEqual(outcome["probability"], 0.9)
        self.assertEqual(transport.calls, ["x"])

    def test_fake_transport_missing_case(self) -> None:
        outcome = spike.FakeTransport({}).decide("s", "missing")
        self.assertIsNone(outcome["probability"])
        self.assertEqual(outcome["error"], "fixture_missing")

    def test_live_transport_parses_response(self) -> None:
        fake_response = mock.MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "answers": {"action_required": {"type": "noul", "noul": 0.88}},
            "usage": {"input_tokens": 123},
        }
        with mock.patch.object(spike.requests, "post", return_value=fake_response) as poster:
            transport = spike.LiveTransport("dummy-key")
            outcome = transport.decide("state", "case")
        self.assertAlmostEqual(outcome["probability"], 0.88)
        self.assertEqual(outcome["input_tokens"], 123)
        self.assertIsNone(outcome["error"])
        call_kwargs = poster.call_args.kwargs
        self.assertTrue(call_kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertEqual(call_kwargs["json"]["model"], spike.JEV_MODEL)
        self.assertIn("questions", call_kwargs["json"])

    def test_live_transport_http_error(self) -> None:
        fake_response = mock.MagicMock()
        fake_response.status_code = 401
        fake_response.text = "unauthorized"
        with mock.patch.object(spike.requests, "post", return_value=fake_response):
            outcome = spike.LiveTransport("dummy-key").decide("state", "case")
        self.assertIsNone(outcome["probability"])
        self.assertTrue(str(outcome["error"]).startswith("http_401"))


class TestGptBaselineTransport(unittest.TestCase):
    def test_true_prediction(self) -> None:
        transport = spike.GptPredictorTransport(predictor=lambda state: {"requires_actions": True, "reason": "x"})
        outcome = transport.decide("I open the door.", "case-1")
        self.assertEqual(outcome["probability"], 1.0)
        self.assertIsNone(outcome["error"])
        self.assertGreater(outcome["input_tokens"], 0)

    def test_false_prediction(self) -> None:
        transport = spike.GptPredictorTransport(predictor=lambda state: {"requires_actions": False})
        outcome = transport.decide("I say hello.", "case-2")
        self.assertEqual(outcome["probability"], 0.0)

    def test_predictor_error_is_contained(self) -> None:
        def _boom(state: str) -> Dict[str, Any]:
            raise RuntimeError("provider down")

        outcome = spike.GptPredictorTransport(predictor=_boom).decide("state", "case-3")
        self.assertIsNone(outcome["probability"])
        self.assertEqual(outcome["error"], "predictor_error: RuntimeError")

    def test_report_marks_estimated_token_source(self) -> None:
        report = spike.build_report([], mode="baseline", eval_path="x", state_mode="full", token_source="estimated")
        self.assertEqual(report["usage"]["token_source"], "estimated")


class TestRunAndReport(unittest.TestCase):
    def _fixture_results(self) -> List[Dict[str, Any]]:
        cases = [dict(case) for case in spike.FIXTURE_CASES]
        probabilities = {c["case_id"]: float(c["probability"]) for c in cases}
        return spike.run_eval(cases, spike.FakeTransport(probabilities))

    def test_run_eval_fields(self) -> None:
        results = self._fixture_results()
        self.assertEqual(len(results), len(spike.FIXTURE_CASES))
        first = results[0]
        for key in ("case_id", "label", "probability", "decision", "latency_ms", "state_chars_sent", "error"):
            self.assertIn(key, first)

    def test_report_shape(self) -> None:
        report = spike.build_report(self._fixture_results(), mode="fixture", eval_path="fixture", state_mode="full")
        self.assertEqual(report["schema"], "jev_phase0_report.v1")
        self.assertEqual(report["evaluated"], len(spike.FIXTURE_CASES))
        self.assertEqual(report["errors"], 0)
        self.assertIn("gate", report)
        self.assertIn("thresholds", report)
        self.assertIn("usage", report)
        self.assertIn("latency", report)
        self.assertTrue(report["gate"]["sample_size_warning"])

    def test_main_fixture_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "report.json"
            code = spike.main(["--mode", "fixture", "--out", str(out_path)])
            self.assertEqual(code, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "fixture")

    def test_live_mode_requires_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "eval.jsonl"
            eval_path.write_text(json.dumps(spike.FIXTURE_CASES[0]) + "\n", encoding="utf-8")
            with mock.patch.object(spike, "resolve_api_key", return_value=None):
                code = spike.main(
                    ["--mode", "live", "--eval", str(eval_path), "--out", str(Path(tmp) / "r.json")]
                )
            self.assertEqual(code, 2)

    def test_dry_run_makes_no_network_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "eval.jsonl"
            eval_path.write_text(json.dumps(spike.FIXTURE_CASES[0]) + "\n", encoding="utf-8")
            with mock.patch.object(spike.requests, "post", side_effect=AssertionError("network call in dry-run")):
                code = spike.main(
                    ["--mode", "live", "--dry-run", "--eval", str(eval_path), "--out", str(Path(tmp) / "r.json")]
                )
            self.assertEqual(code, 0)

    def test_player_tail_state_mode(self) -> None:
        cases = [
            {
                "case_id": "tail-1",
                "source": "fixture",
                "state": "--- WORLD STATE ---\nlong context\nPlayer: [X]: \"I draw my sword.\"",
                "label_requires_actions": True,
            }
        ]
        results = spike.run_eval(cases, spike.FakeTransport({"tail-1": 0.9}), state_mode="player-tail")
        self.assertEqual(results[0]["state_chars_sent"], len("Player: [X]: \"I draw my sword.\""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
