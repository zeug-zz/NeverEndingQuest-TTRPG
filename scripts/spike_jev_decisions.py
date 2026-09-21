#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Jev Phase 0 decision spike (action-required classification).

Runs the System One / Jev Noul question "does this input require a
state-changing action?" against a labeled eval set and reports agreement,
confusion, latency, token usage, and a confidence-threshold recommendation.

Modes:
  - fixture : built-in cases with a fake transport. No network. Used by tests.
  - live    : real OpenRouter Decisions API calls. Requires OPENROUTER_API_KEY
              in the environment or config.OPENROUTER_API_KEY.

The spike never mutates game state and never prints credential values.
Provider-free tests live in scripts/test_jev_decision_spike.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

JEV_MODEL = "typesafe/jev-1.13"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
QUESTION_ID = "action_required"
PRICE_PER_INPUT_TOKEN_USD = 0.042 / 1_000_000.0

DEFAULT_EVAL = REPO_ROOT / "debug" / "jev" / "eval_set.jsonl"
DEFAULT_OUT = REPO_ROOT / "debug" / "jev" / "phase0_report.json"

DEFAULT_THRESHOLDS = (0.3, 0.5, 0.7, 0.8, 0.9, 0.95)
DEFAULT_AGREEMENT_MIN = 0.95
DEFAULT_FN_RATE_MAX = 0.05
SAMPLE_SIZE_WARNING_BELOW = 20

STATE_MODE_FULL = "full"
STATE_MODE_PLAYER_TAIL = "player-tail"

FIXTURE_CASES: List[Dict[str, Any]] = [
    {"case_id": "fix-001", "source": "fixture", "state": "I pick up the sword.", "label_requires_actions": True, "probability": 0.97},
    {"case_id": "fix-002", "source": "fixture", "state": "I go to the tavern.", "label_requires_actions": True, "probability": 0.93},
    {"case_id": "fix-003", "source": "fixture", "state": "What's in this room?", "label_requires_actions": False, "probability": 0.04},
    {"case_id": "fix-004", "source": "fixture", "state": "I tell the guard about the bandits.", "label_requires_actions": False, "probability": 0.18},
    {"case_id": "fix-005", "source": "fixture", "state": "I take a long rest.", "label_requires_actions": False, "probability": 0.55},
    {"case_id": "fix-006", "source": "fixture", "state": "I rolled a natural 20!", "label_requires_actions": True, "probability": 0.86},
    {"case_id": "fix-007", "source": "fixture", "state": "Aye, let's do it.", "label_requires_actions": True, "probability": 0.72},
    {"case_id": "fix-008", "source": "fixture", "state": "Who can you spare?", "label_requires_actions": True, "probability": 0.9},
]


def build_questions() -> Dict[str, Any]:
    """Build the typed question map for the action-required decision."""
    return {
        QUESTION_ID: {
            "type": "noul",
            "instructions": (
                "Does this game input require the narrator to emit a state-changing "
                "game action (any action other than updateTime), per the criteria?"
            ),
            "criteria": {
                "true": (
                    "The input commits to or reports a tracked state change: inventory or "
                    "equipment change, movement or location transition, combat or encounter "
                    "initiation, spell or ability use, party membership change, storage "
                    "interaction, quest or plot progression, level-up, dice-roll outcome, "
                    "search or investigation action, or a mechanical error correction."
                ),
                "false": (
                    "The input is a question, description request, rules question, pure "
                    "in-character dialogue, planning discussion without commitment, or a "
                    "simple rest request handled by the formulaic rest path."
                ),
            },
        }
    }


def _load_config_key() -> Optional[str]:
    """Read config.OPENROUTER_API_KEY without logging its value."""
    try:
        import config  # type: ignore

        value = getattr(config, "OPENROUTER_API_KEY", "") or ""
    except Exception:
        return None
    value = str(value).strip()
    return value or None


def resolve_api_key(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Resolve the OpenRouter key from environment first, then config."""
    source_env = env if env is not None else os.environ
    value = (source_env.get("OPENROUTER_API_KEY") or "").strip()
    if value:
        return value
    return _load_config_key()


def _load_optional_config_values() -> Tuple[Optional[str], Optional[str]]:
    """Read optional OpenRouter ranking headers from config."""
    try:
        import config  # type: ignore

        referer = getattr(config, "OPENROUTER_HTTP_REFERER", "") or ""
        title = getattr(config, "OPENROUTER_APP_TITLE", "") or ""
        return (str(referer).strip() or None, str(title).strip() or None)
    except Exception:
        return (None, None)


def parse_decision_response(payload: Any, question_id: str = QUESTION_ID) -> Tuple[Optional[float], Dict[str, Any]]:
    """Defensively parse a System One response into (probability, usage)."""
    if not isinstance(payload, dict):
        return None, {}
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None, usage
    answer = answers.get(question_id)
    probability: Optional[float] = None
    if isinstance(answer, bool):
        probability = 1.0 if answer else 0.0
    elif isinstance(answer, (int, float)):
        probability = float(answer)
    elif isinstance(answer, str):
        try:
            probability = float(answer)
        except ValueError:
            probability = None
    elif isinstance(answer, dict):
        for key in ("noul", "value", "answer", "probability", "p"):
            candidate = answer.get(key)
            if isinstance(candidate, bool):
                probability = 1.0 if candidate else 0.0
                break
            if isinstance(candidate, (int, float)):
                probability = float(candidate)
                break
            if isinstance(candidate, str):
                try:
                    probability = float(candidate)
                    break
                except ValueError:
                    continue
    if probability is None:
        return None, usage
    probability = max(0.0, min(1.0, probability))
    return probability, usage


def extract_usage_tokens(usage: Dict[str, Any]) -> int:
    """Extract input token count from either documented usage key."""
    for key in ("input_tokens", "prompt_tokens"):
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def estimate_cost_usd(input_tokens: int) -> float:
    """Estimate USD cost for a given input token count at the Jev list price."""
    return float(input_tokens) * PRICE_PER_INPUT_TOKEN_USD


def derive_player_tail(state: str) -> str:
    """Return the final player utterance when present, else the full state."""
    marker = state.rfind("Player: ")
    if marker == -1:
        return state
    tail = state[marker:].strip()
    if len(tail) < 10:
        return state
    return tail


def _percentile(values: List[float], fraction: float) -> float:
    """Return a simple percentile (0.0 when empty)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def latency_stats(values: List[float]) -> Dict[str, float]:
    """Return mean/p50/p90 latency stats in milliseconds."""
    if not values:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0}
    return {
        "mean_ms": round(sum(values) / len(values), 2),
        "p50_ms": round(_percentile(values, 0.5), 2),
        "p90_ms": round(_percentile(values, 0.9), 2),
    }


def confusion_at(results: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """Compute confusion counts and rates at a probability threshold."""
    true_positive = true_negative = false_positive = false_negative = 0
    for result in results:
        probability = result.get("probability")
        if probability is None:
            continue
        predicted = float(probability) >= threshold
        label = bool(result.get("label"))
        if label and predicted:
            true_positive += 1
        elif label and not predicted:
            false_negative += 1
        elif not label and predicted:
            false_positive += 1
        else:
            true_negative += 1
    total = true_positive + true_negative + false_positive + false_negative
    positives = true_positive + false_negative
    negatives = true_negative + false_positive
    return {
        "threshold": round(float(threshold), 4),
        "total": total,
        "tp": true_positive,
        "tn": true_negative,
        "fp": false_positive,
        "fn": false_negative,
        "agreement": round((true_positive + true_negative) / total, 4) if total else 0.0,
        "fn_rate": round(false_negative / positives, 4) if positives else 0.0,
        "fp_rate": round(false_positive / negatives, 4) if negatives else 0.0,
    }


def build_sweep(results: List[Dict[str, Any]], thresholds: Tuple[float, ...]) -> List[Dict[str, Any]]:
    """Compute confusion rows for every threshold."""
    return [confusion_at(results, threshold) for threshold in thresholds]


def recommend_threshold(
    sweep: List[Dict[str, Any]],
    agreement_min: float = DEFAULT_AGREEMENT_MIN,
    fn_rate_max: float = DEFAULT_FN_RATE_MAX,
) -> Dict[str, Any]:
    """Pick the most permissive threshold that clears the gate, else the safest row."""
    eligible = [
        row
        for row in sweep
        if row.get("total", 0) > 0
        and row.get("agreement", 0.0) >= agreement_min
        and row.get("fn_rate", 1.0) <= fn_rate_max
    ]
    if eligible:
        chosen = min(eligible, key=lambda row: row.get("threshold", 1.0))
        passed = True
    elif sweep:
        chosen = min(
            sweep,
            key=lambda row: (
                row.get("fn_rate", 1.0),
                -row.get("agreement", 0.0),
                row.get("threshold", 1.0),
            ),
        )
        passed = False
    else:
        chosen = {
            "threshold": 0.0,
            "total": 0,
            "tp": 0,
            "tn": 0,
            "fp": 0,
            "fn": 0,
            "agreement": 0.0,
            "fn_rate": 0.0,
            "fp_rate": 0.0,
        }
        passed = False
    return {
        "agreement_min": agreement_min,
        "fn_rate_max": fn_rate_max,
        "passed": passed,
        "recommended_threshold": chosen.get("threshold", 0.0),
        "agreement": chosen.get("agreement", 0.0),
        "fn_rate": chosen.get("fn_rate", 0.0),
        "fp_rate": chosen.get("fp_rate", 0.0),
        "tp": chosen.get("tp", 0),
        "tn": chosen.get("tn", 0),
        "fp": chosen.get("fp", 0),
        "fn": chosen.get("fn", 0),
        "evaluated": chosen.get("total", 0),
    }


def _source_breakdown(results: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """Agreement per eval source at a fixed threshold."""
    sources = sorted({str(r.get("source", "unknown")) for r in results})
    breakdown: Dict[str, Any] = {}
    for source in sources:
        subset = [r for r in results if str(r.get("source", "unknown")) == source]
        row = confusion_at(subset, threshold)
        breakdown[source] = {
            "total": row["total"],
            "agreement": row["agreement"],
            "fn": row["fn"],
            "fp": row["fp"],
        }
    return breakdown


def _strength_breakdown(results: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """Agreement per label strength at a fixed threshold."""
    strengths = sorted({str(r.get("label_strength", "unknown")) for r in results})
    breakdown: Dict[str, Any] = {}
    for strength in strengths:
        subset = [r for r in results if str(r.get("label_strength", "unknown")) == strength]
        row = confusion_at(subset, threshold)
        breakdown[strength] = {
            "total": row["total"],
            "agreement": row["agreement"],
            "fn": row["fn"],
            "fp": row["fp"],
        }
    return breakdown


class FakeTransport:
    """Deterministic transport for fixture mode and tests."""

    def __init__(self, probabilities: Dict[str, float]):
        self._probabilities = dict(probabilities)
        self.calls: List[str] = []

    def decide(self, state: str, case_id: str) -> Dict[str, Any]:
        self.calls.append(case_id)
        probability = self._probabilities.get(case_id)
        if probability is None:
            return {"probability": None, "input_tokens": 0, "error": "fixture_missing"}
        return {
            "probability": float(probability),
            "input_tokens": max(1, len(state) // 4),
            "error": None,
        }


class GptPredictorTransport:
    """Baseline transport wrapping the incumbent GPT action predictor.

    Used by ``--mode baseline`` to score the current production decision on the
    same eval set, so Jev results can be interpreted against a control.
    Token counts are estimated (the predictor returns no usage data).
    """

    PROMPT_TOKEN_ESTIMATE = 1500

    def __init__(self, predictor: Any = None):
        self._predictor = predictor

    def _resolve(self) -> Any:
        if self._predictor is not None:
            return self._predictor
        from utils.action_predictor import predict_actions_required  # type: ignore

        return predict_actions_required

    def decide(self, state: str, case_id: str) -> Dict[str, Any]:
        try:
            prediction = self._resolve()(state)
        except Exception as exc:
            return {"probability": None, "input_tokens": 0, "error": "predictor_error: {}".format(type(exc).__name__)}
        requires_actions = bool((prediction or {}).get("requires_actions"))
        return {
            "probability": 1.0 if requires_actions else 0.0,
            "input_tokens": max(1, len(state) // 4) + self.PROMPT_TOKEN_ESTIMATE,
            "error": None,
        }


class LiveTransport:
    """OpenRouter Decisions API transport."""
    def __init__(self, api_key: str, timeout: float = 30.0, referer: Optional[str] = None, title: Optional[str] = None):
        self._api_key = api_key
        self._timeout = timeout
        self._url = OPENROUTER_DECISIONS_URL
        self._referer = referer
        self._title = title

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": "Bearer {}".format(self._api_key),
            "Content-Type": "application/json",
        }
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-Title"] = self._title
        return headers

    def decide(self, state: str, case_id: str) -> Dict[str, Any]:
        payload = {
            "model": JEV_MODEL,
            "state": state,
            "questions": build_questions(),
        }
        try:
            response = requests.post(
                self._url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            return {"probability": None, "input_tokens": 0, "error": "request_error: {}".format(type(exc).__name__)}
        if response.status_code != 200:
            detail = ""
            try:
                detail = " | " + " ".join(str(response.text).split())[:200]
            except Exception:
                detail = ""
            return {
                "probability": None,
                "input_tokens": 0,
                "error": "http_{}{}".format(response.status_code, detail),
            }
        try:
            body = response.json()
        except ValueError:
            return {"probability": None, "input_tokens": 0, "error": "invalid_json"}
        probability, usage = parse_decision_response(body, QUESTION_ID)
        if probability is None:
            return {"probability": None, "input_tokens": extract_usage_tokens(usage), "error": "missing_answer"}
        return {
            "probability": probability,
            "input_tokens": extract_usage_tokens(usage),
            "error": None,
        }


def run_eval(
    cases: List[Dict[str, Any]],
    transport: Any,
    state_mode: str = STATE_MODE_FULL,
) -> List[Dict[str, Any]]:
    """Run every case through the transport and collect per-case results."""
    results: List[Dict[str, Any]] = []
    for case in cases:
        state = str(case.get("state", ""))
        if state_mode == STATE_MODE_PLAYER_TAIL:
            state = derive_player_tail(state)
        started = time.perf_counter()
        outcome = transport.decide(state, str(case.get("case_id", "")))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        results.append(
            {
                "case_id": case.get("case_id", ""),
                "source": case.get("source", "unknown"),
                "label": bool(case.get("label_requires_actions")),
                "label_strength": case.get("label_strength", "unknown"),
                "probability": outcome.get("probability"),
                "decision": (
                    None
                    if outcome.get("probability") is None
                    else bool(float(outcome["probability"]) >= 0.5)
                ),
                "input_tokens": int(outcome.get("input_tokens") or 0),
                "latency_ms": round(elapsed_ms, 2),
                "state_chars_sent": len(state),
                "error": outcome.get("error"),
            }
        )
    return results


def build_report(
    results: List[Dict[str, Any]],
    mode: str,
    eval_path: str,
    state_mode: str,
    thresholds: Tuple[float, ...] = DEFAULT_THRESHOLDS,
    agreement_min: float = DEFAULT_AGREEMENT_MIN,
    fn_rate_max: float = DEFAULT_FN_RATE_MAX,
    token_source: str = "api",
) -> Dict[str, Any]:
    """Build the Phase 0 gate report from per-case results."""
    successful = [r for r in results if r.get("probability") is not None]
    errors = [r for r in results if r.get("probability") is None]
    sweep = build_sweep(successful, thresholds)
    gate = recommend_threshold(sweep, agreement_min=agreement_min, fn_rate_max=fn_rate_max)
    gate["sample_size_warning"] = len(successful) < SAMPLE_SIZE_WARNING_BELOW
    input_tokens_total = sum(int(r.get("input_tokens") or 0) for r in successful)
    estimated_cost = estimate_cost_usd(input_tokens_total)
    cost_per_1k = (estimated_cost * 1000.0 / len(successful)) if successful else 0.0
    return {
        "schema": "jev_phase0_report.v1",
        "mode": mode,
        "model": JEV_MODEL,
        "endpoint": OPENROUTER_DECISIONS_URL,
        "question_id": QUESTION_ID,
        "eval_path": eval_path,
        "state_mode": state_mode,
        "cases_total": len(results),
        "evaluated": len(successful),
        "errors": len(errors),
        "error_cases": [
            {"case_id": r.get("case_id"), "error": r.get("error")} for r in errors
        ][:20],
        "gate": gate,
        "thresholds": sweep,
        "latency": latency_stats([float(r.get("latency_ms") or 0.0) for r in successful]),
        "usage": {
            "input_tokens_total": input_tokens_total,
            "token_source": token_source,
            "estimated_cost_usd": round(estimated_cost, 6),
            "cost_per_1k_decisions_usd": round(cost_per_1k, 6),
        },
        "by_source": _source_breakdown(successful, float(gate.get("recommended_threshold", 0.5))),
        "by_strength": _strength_breakdown(successful, float(gate.get("recommended_threshold", 0.5))),
        "cases": [
            {
                "case_id": r.get("case_id"),
                "source": r.get("source"),
                "label": r.get("label"),
                "label_strength": r.get("label_strength"),
                "probability": r.get("probability"),
                "latency_ms": r.get("latency_ms"),
                "input_tokens": r.get("input_tokens"),
                "state_chars_sent": r.get("state_chars_sent"),
                "error": r.get("error"),
            }
            for r in results
        ],
    }


def write_report(path: Path, report: Dict[str, Any]) -> None:
    """Write the report JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")


def load_eval_cases(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL eval cases, skipping malformed lines."""
    cases: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return cases
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            cases.append(record)
    return cases


def print_report_summary(report: Dict[str, Any]) -> None:
    """Print an ASCII gate summary and threshold sweep."""
    gate = report.get("gate", {})
    print("[JEV PHASE0] mode={} state_mode={} model={}".format(report.get("mode"), report.get("state_mode"), report.get("model")))
    print("[JEV PHASE0] evaluated={}/{} errors={}".format(report.get("evaluated"), report.get("cases_total"), report.get("errors")))
    print(
        "[JEV PHASE0] GATE passed={} threshold={} agreement={} fn_rate={} fp_rate={} (tp={} tn={} fp={} fn={})".format(
            gate.get("passed"),
            gate.get("recommended_threshold"),
            gate.get("agreement"),
            gate.get("fn_rate"),
            gate.get("fp_rate"),
            gate.get("tp"),
            gate.get("tn"),
            gate.get("fp"),
            gate.get("fn"),
        )
    )
    print("[JEV PHASE0] threshold sweep:")
    for row in report.get("thresholds", []):
        print(
            "  t={} agreement={} fn_rate={} fp_rate={} tp={} tn={} fp={} fn={}".format(
                row.get("threshold"),
                row.get("agreement"),
                row.get("fn_rate"),
                row.get("fp_rate"),
                row.get("tp"),
                row.get("tn"),
                row.get("fp"),
                row.get("fn"),
            )
        )
    usage = report.get("usage", {})
    latency = report.get("latency", {})
    print(
        "[JEV PHASE0] input_tokens={} est_cost_usd={} cost_per_1k={}".format(
            usage.get("input_tokens_total"),
            usage.get("estimated_cost_usd"),
            usage.get("cost_per_1k_decisions_usd"),
        )
    )
    print(
        "[JEV PHASE0] latency mean_ms={} p50_ms={} p90_ms={}".format(
            latency.get("mean_ms"), latency.get("p50_ms"), latency.get("p90_ms")
        )
    )
    print("[JEV PHASE0] by_source={}".format(json.dumps(report.get("by_source", {}), sort_keys=True)))
    print("[JEV PHASE0] by_strength={}".format(json.dumps(report.get("by_strength", {}), sort_keys=True)))
    if report.get("error_cases"):
        print("[JEV PHASE0] first_errors={}".format(json.dumps(report.get("error_cases")[:3], sort_keys=True)))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint. Returns 0 on success, 2 on configuration error."""
    parser = argparse.ArgumentParser(description="Jev Phase 0 action-required decision spike.")
    parser.add_argument("--mode", choices=("fixture", "baseline", "live"), default="fixture")
    parser.add_argument("--eval", default=str(DEFAULT_EVAL), help="JSONL eval set path (live mode)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="report JSON output path")
    parser.add_argument("--limit", type=int, default=0, help="max cases to run (0 = all)")
    parser.add_argument("--state-mode", choices=(STATE_MODE_FULL, STATE_MODE_PLAYER_TAIL), default=STATE_MODE_FULL)
    parser.add_argument("--threshold", type=float, default=None, help="report gate at a single threshold")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout seconds (live)")
    parser.add_argument("--dry-run", action="store_true", help="print the live request plan without calling the API")
    args = parser.parse_args(argv)

    if args.mode == "fixture":
        cases = [dict(case) for case in FIXTURE_CASES]
        probabilities = {case["case_id"]: float(case["probability"]) for case in FIXTURE_CASES}
        transport: Any = FakeTransport(probabilities)
        eval_path = "fixture"
        token_source = "estimated"
    elif args.mode == "baseline":
        eval_path = args.eval
        if not Path(args.eval).exists():
            print("[JEV PHASE0] ERROR: eval set not found: {}".format(args.eval))
            return 2
        cases = load_eval_cases(Path(args.eval))
        transport = GptPredictorTransport()
        token_source = "estimated"
    else:
        eval_path = args.eval
        if args.dry_run:
            cases = load_eval_cases(Path(args.eval)) if Path(args.eval).exists() else []
            print("[JEV PHASE0] dry-run mode=live eval={} cases={}".format(args.eval, len(cases)))
            print("[JEV PHASE0] endpoint={} model={} state_mode={}".format(OPENROUTER_DECISIONS_URL, JEV_MODEL, args.state_mode))
            print("[JEV PHASE0] request_keys=model,state,questions question_id={}".format(QUESTION_ID))
            return 0
        if not Path(args.eval).exists():
            print("[JEV PHASE0] ERROR: eval set not found: {}".format(args.eval))
            return 2
        cases = load_eval_cases(Path(args.eval))
        api_key = resolve_api_key()
        if not api_key:
            print("[JEV PHASE0] ERROR: no OpenRouter key found (env OPENROUTER_API_KEY or config.OPENROUTER_API_KEY)")
            return 2
        referer, title = _load_optional_config_values()
        transport = LiveTransport(api_key, timeout=args.timeout, referer=referer, title=title)
        token_source = "api"

    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("[JEV PHASE0] ERROR: no cases to evaluate")
        return 2

    results = run_eval(cases, transport, state_mode=args.state_mode)
    thresholds = (args.threshold,) if args.threshold is not None else DEFAULT_THRESHOLDS
    report = build_report(
        results,
        mode=args.mode,
        eval_path=eval_path,
        state_mode=args.state_mode,
        thresholds=thresholds,
        token_source=token_source,
    )
    write_report(Path(args.out), report)
    print_report_summary(report)
    print("[JEV PHASE0] report={}".format(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
