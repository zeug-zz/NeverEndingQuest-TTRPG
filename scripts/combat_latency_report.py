# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free reporting for bounded combat latency JSONL traces.

The command is read-only.  It exits 0 after producing a report, including a
degraded report for empty or partly malformed input, and exits 2 when the
trace cannot be read.  Use ``--json`` for a machine-readable report.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


EVENT_TYPES = {"stage", "provider", "compression", "file_operation", "decision"}
DECISION_POINTS = {"pc_phase_parser", "combat_command_fast_path"}


def _numbers(values: Iterable[Any]) -> List[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def _summary(values: Iterable[Any]) -> Dict[str, Any]:
    numbers = sorted(_numbers(values))
    if not numbers:
        return {"count": 0, "p50_ms": None, "p90_ms": None, "max_ms": None}
    return {
        "count": len(numbers),
        "p50_ms": statistics.median(numbers),
        "p90_ms": numbers[min(len(numbers) - 1, int((len(numbers) - 1) * 0.90))],
        "max_ms": max(numbers),
    }


def _valid_record(record: Any) -> bool:
    return isinstance(record, dict) and record.get("event_type") in EVENT_TYPES


def load_trace(path: Path) -> Tuple[List[Dict[str, Any]], int, List[int], Optional[str]]:
    """Load valid bounded records and return malformed line diagnostics."""
    records: List[Dict[str, Any]] = []
    malformed = 0
    malformed_lines: List[int] = []
    try:
        with path.open("r", encoding="ascii") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeError):
                    malformed += 1
                    if len(malformed_lines) < 5:
                        malformed_lines.append(line_number)
                    continue
                if not _valid_record(record):
                    malformed += 1
                    if len(malformed_lines) < 5:
                        malformed_lines.append(line_number)
                    continue
                records.append(record)
    except (OSError, UnicodeError) as error:
        return [], 0, [], str(error)
    return records, malformed, malformed_lines, None


def _context_values(records: Iterable[Dict[str, Any]], key: str) -> List[str]:
    return sorted({str(record[key]) for record in records if record.get(key) not in (None, "")})


def build_report(path: Path) -> Dict[str, Any]:
    records, malformed, malformed_lines, read_error = load_trace(path)
    if read_error:
        return {"status": "error", "path": str(path), "error": read_error}

    stages: Dict[str, Dict[str, Any]] = {}
    providers: Dict[str, Dict[str, Any]] = {}
    compression: Dict[str, Dict[str, Any]] = {}
    file_operations: Dict[str, Dict[str, int]] = {}
    decisions: Dict[str, Dict[str, Any]] = {}
    nl_fast_path = {"hit": 0, "miss": 0}
    fixtures: Dict[str, Dict[str, Any]] = {}

    for record in records:
        event_type = record["event_type"]
        fixture = str(record.get("fixture", ""))
        mode = str(record.get("mode", ""))
        fixture_key = "%s/%s" % (fixture or "unavailable", mode or "unavailable")
        fixture_row = fixtures.setdefault(
            fixture_key, {"fixture": fixture or None, "mode": mode or None, "records": 0,
                           "provider_calls": 0, "stage_count": 0, "decision_count": 0}
        )
        fixture_row["records"] += 1

        if event_type == "stage":
            name = str(record.get("stage", "unavailable"))
            row = stages.setdefault(name, {"timings": []})
            row["timings"].append(record.get("elapsed_ms"))
            fixture_row["stage_count"] += 1
        elif event_type == "provider":
            site = str(record.get("site", "unavailable"))
            row = providers.setdefault(site, {"latencies": [], "token_sums": {}, "token_counts": {}})
            if isinstance(record.get("elapsed_ms"), (int, float)):
                row["latencies"].append(record["elapsed_ms"])
            for token_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = record.get(token_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row["token_sums"][token_name] = row["token_sums"].get(token_name, 0) + value
                    row["token_counts"][token_name] = row["token_counts"].get(token_name, 0) + 1
            fixture_row["provider_calls"] += 1
        elif event_type == "compression":
            site = str(record.get("site", "unavailable"))
            row = compression.setdefault(site, {"records": 0, "calls": 0, "cache_hits": 0, "cache_misses": 0, "latencies": []})
            row["records"] += 1
            if record.get("call_occurred") is True:
                row["calls"] += 1
            if record.get("cache_hit") is True:
                row["cache_hits"] += 1
            elif record.get("cache_hit") is False:
                row["cache_misses"] += 1
            if isinstance(record.get("elapsed_ms"), (int, float)):
                row["latencies"].append(record["elapsed_ms"])
        elif event_type == "file_operation":
            site = str(record.get("site", "unavailable"))
            category = record.get("category")
            if category in ("read", "write"):
                row = file_operations.setdefault(site, {"read": 0, "write": 0})
                row[category] += 1
        elif event_type == "decision":
            point = str(record.get("decision_point", "unavailable"))
            source = str(record.get("decision_source", "unavailable"))
            key = "%s/%s" % (point, source)
            row = decisions.setdefault(key, {"decision_point": point, "decision_source": source, "count": 0, "latencies": [], "provider_avoided": 0})
            row["count"] += 1
            if isinstance(record.get("decision_latency_ms"), (int, float)):
                row["latencies"].append(record["decision_latency_ms"])
            if record.get("provider_call_avoided") is True:
                row["provider_avoided"] += 1
            if point in DECISION_POINTS and source in ("deterministic", "llm_fallback"):
                nl_fast_path["hit" if source == "deterministic" else "miss"] += 1
            fixture_row["decision_count"] += 1

    stage_output = {}
    for name, row in stages.items():
        stage_output[name] = _summary(row["timings"])

    provider_output = {}
    for site, row in providers.items():
        provider_output[site] = {"calls": len(row["latencies"]) if row["latencies"] else row.get("records", 0),
                                 "latency": _summary(row["latencies"]),
                                 "token_sums": {name: row["token_sums"][name] for name in row["token_sums"]},
                                 "token_observations": row["token_counts"]}

    compression_output = {}
    for site, row in compression.items():
        outcomes = row["cache_hits"] + row["cache_misses"]
        compression_output[site] = {
            "records": row["records"], "calls": row["calls"],
            "cache_hits": row["cache_hits"], "cache_misses": row["cache_misses"],
            "cache_hit_rate": (row["cache_hits"] / outcomes if outcomes else None),
            "latency": _summary(row["latencies"]) if row["latencies"] else None,
        }

    decision_output = {}
    for key, row in decisions.items():
        decision_output[key] = {"decision_point": row["decision_point"], "decision_source": row["decision_source"],
                                "count": row["count"], "latency": _summary(row["latencies"]),
                                "provider_call_avoided": row["provider_avoided"]}

    return {
        "status": "degraded" if malformed or not records else "ok",
        "path": str(path),
        "input": {"total_records": len(records), "malformed_count": malformed,
                   "malformed_line_numbers": malformed_lines, "fixtures": _context_values(records, "fixture"),
                   "modes": _context_values(records, "mode")},
        "stages": stage_output,
        "providers": provider_output,
        "compression": compression_output,
        "file_operations": file_operations,
        "decisions": decision_output,
        "nl_fast_path": nl_fast_path,
        "fixtures": list(fixtures.values()),
    }


def _value(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def render_report(report: Dict[str, Any]) -> str:
    if report.get("status") == "error":
        return "ERROR: unable to read %s: %s" % (report.get("path"), report.get("error"))
    inp = report["input"]
    lines = ["Combat latency report [%s]" % report["status"], "Input summary", "  path: %s" % report["path"],
             "  records: %s  malformed: %s" % (inp["total_records"], inp["malformed_count"]),
             "  fixtures: %s  modes: %s" % (_value(", ".join(inp["fixtures"]) or None), _value(", ".join(inp["modes"]) or None))]
    if inp["malformed_line_numbers"]:
        lines.append("  malformed line numbers (first 5): %s" % ", ".join(map(str, inp["malformed_line_numbers"])))
    lines += ["Stage timings", "  stage | count | p50_ms | p90_ms | max_ms"]
    for name, row in report["stages"].items():
        lines.append("  %s | %s | %s | %s | %s" % (name, row["count"], _value(row["p50_ms"]), _value(row["p90_ms"]), _value(row["max_ms"])))
    lines += ["Provider by site", "  site | calls | p50_ms | p90_ms | token sums (observed fields only)"]
    for site, row in report["providers"].items():
        latency = row["latency"]
        tokens = ", ".join("%s=%s" % item for item in row["token_sums"].items()) or "unavailable"
        lines.append("  %s | %s | %s | %s | %s" % (site, row["calls"], _value(latency["p50_ms"]), _value(latency["p90_ms"]), tokens))
    lines += ["Compression", "  site | records | calls | cache hits | cache misses | hit rate | p50_ms"]
    for site, row in report["compression"].items():
        latency = row["latency"]
        lines.append("  %s | %s | %s | %s | %s | %s | %s" % (site, row["records"], row["calls"], row["cache_hits"], row["cache_misses"], _value(row["cache_hit_rate"]), _value(latency["p50_ms"] if latency else None)))
    lines += ["File operations", "  site | reads | writes"]
    for site, row in report["file_operations"].items():
        lines.append("  %s | %s | %s" % (site, row["read"], row["write"]))
    lines += ["Decisions", "  decision point/source | count | p50_ms | provider avoided"]
    for key, row in report["decisions"].items():
        lines.append("  %s | %s | %s | %s" % (key, row["count"], _value(row["latency"]["p50_ms"]), row["provider_call_avoided"]))
    lines.append("  NL fast path: hits=%s misses=%s" % (report["nl_fast_path"]["hit"], report["nl_fast_path"]["miss"]))
    lines += ["Baseline fixture summaries", "  fixture/mode | records | provider calls | stage count | decision count"]
    for row in report["fixtures"]:
        lines.append("  %s/%s | %s | %s | %s | %s" % (_value(row["fixture"]), _value(row["mode"]), row["records"], row["provider_calls"], row["stage_count"], row["decision_count"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Report provider-free combat latency trace observations")
    parser.add_argument("--trace", type=Path, default=Path("debug") / "combat_turn_trace.jsonl")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = build_report(args.trace)
    if report.get("status") == "error":
        print(render_report(report), file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
