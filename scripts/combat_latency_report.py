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
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


EVENT_TYPES = {"stage", "provider", "compression", "file_operation", "decision", "combat_observation"}
DECISION_POINTS = {"pc_phase_parser", "combat_command_fast_path"}

G5_P1_LATENCY_REGRESSION_FACTOR = 1.10
G5_P1_LATENCY_REGRESSION_OPERATOR = "<= before*%.2f" % G5_P1_LATENCY_REGRESSION_FACTOR
G5R_MEDIAN_BATCH_WORK_ONLY_MS = 15000.0
G5R_BATCH_WRITE_LIMIT = 3
G5T_PROVIDER_CALL_LIMIT = 2
G5T_PLAN_CALLS = 1
G5T_NARRATION_CALLS = 1
G5T_VALIDATION_CALLS = 0
G5T_MEDIAN_BATCH_WORK_ONLY_MS = 15000.0
G5T_BATCH_FIXED_WRITE_BUDGET = 2
G5T_PARTY_SIZES = (1, 4)
G5T_RUNS_PER_PARTY = 3
G5T_PREFETCH_PROVIDER_SITE = "combat_tactical_prefetch"
G5T_PREFETCH_REQUEST_KINDS = frozenset({"initial", "replan"})
G5T_PREFETCH_SUBMISSION_OUTCOMES = frozenset({"submitted", "replan_submitted"})
G5T_PREFETCH_TRACE_STATUSES = frozenset({
    "prefetch_hit", "prefetch_stale", "prefetch_none", "standing_orders_unavailable",
})
G5T_STANDING_ORDERS_TRACE_OUTCOMES = frozenset({
    "submitted", "replan_submitted", "standing_orders",
    "standing_orders_unavailable", "invalidated",
})
G5T_EXIT_FLOW_PROVIDER_SITES = frozenset({
    "compression", "combat_compression", "combat_dialogue_summary", "main_dm",
})
G5T_BEHAVIOR_CHECKS = (
    "commander_squad_follows_orders",
    "self_preservation_removal",
    "cover_changes_effective_ac",
    "cover_expiration",
)
G5_TARGETS = {
    "pc_action_llm_p50_seconds": {"operator": "<=", "threshold": 8.0},
    "pc_action_fast_p50_seconds": {"operator": "<", "threshold": 1.0},
    "enemy_batch_p50_seconds": {"operator": "<=", "threshold": 15.0},
    "pc_action_fast_provider_calls": {"operator": "<=", "threshold": 1},
    "pc_action_llm_provider_calls": {"operator": "<=", "threshold": 2},
    "enemy_batch_provider_calls": {"operator": "==", "threshold": 1},
    "file_writes_per_combat_turn": {"operator": "<=", "threshold": 3},
    "p4_round_latency_improvement": {"operator": ">=", "threshold": 0.30},
    "p1_no_latency_regression": {"operator": G5_P1_LATENCY_REGRESSION_OPERATOR,
                                  "threshold": G5_P1_LATENCY_REGRESSION_FACTOR},
    "p1_no_provider_call_regression": {"operator": "<= before", "threshold": None},
    "p1_no_file_write_regression": {"operator": "<= before", "threshold": None},
    "phase_provider_calls_no_increase": {"operator": "<= before", "threshold": None},
    "phase_file_writes_no_increase": {"operator": "<= before", "threshold": None},
}
G5_EXPECTED_PROVIDER = "open" + "ai"
G5_EXPECTED_MODEL = "gpt-6-luna"
G5_PHASES = ("PC_PHASE", "ENEMY_PHASE")


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
    combat_observations: List[Dict[str, Any]] = []
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
        elif event_type == "combat_observation":
            combat_observations.append(record)

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
        "combat_observations": combat_observations,
        "nl_fast_path": nl_fast_path,
        "fixtures": list(fixtures.values()),
    }


def _g5_is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _g5_summary(values: Iterable[Any]) -> Optional[float]:
    numbers = [float(value) for value in values if _g5_is_number(value)]
    return round(statistics.median(numbers), 3) if numbers else None


def _g5_complete_action_p50(metrics: Dict[str, Any]) -> Optional[float]:
    rows = metrics.get("actions", [])
    values = [row.get("work_only_ms") for row in rows]
    if not values or not all(_g5_is_number(value) for value in values):
        return None
    return _g5_summary(values)


def _g5_check(name: str, observed: Any, operator: str, threshold: Any,
              reason: Optional[str] = None) -> Dict[str, Any]:
    status = "BLOCKED"
    if reason is None and _g5_is_number(observed) and _g5_is_number(threshold):
        passed = {
            "<=": observed <= threshold,
            "<": observed < threshold,
            "==": observed == threshold,
            ">=": observed >= threshold,
        }.get(operator)
        if passed is not None:
            status = "PASS" if passed else "FAIL"
        else:
            reason = "unsupported_comparison_operator"
    elif reason is None:
        reason = "required_metric_unavailable"
    return {"target": name, "observed": observed, "operator": operator,
            "threshold": threshold, "status": status, "reason": reason}


def _g5_comparison_check(name: str, after: Any, before: Any,
                         reason: Optional[str] = None,
                         before_factor: float = 1.0) -> Dict[str, Any]:
    if before_factor == G5_P1_LATENCY_REGRESSION_FACTOR:
        operator = G5_P1_LATENCY_REGRESSION_OPERATOR
    elif before_factor == 1.0:
        operator = "<= before"
    else:
        operator = "<= before*%.2f" % before_factor
    threshold = (round(before * before_factor, 6)
                 if _g5_is_number(before) else before)
    if reason is None and _g5_is_number(after) and _g5_is_number(before):
        return {"target": name, "observed": after, "before": before,
                "operator": operator, "threshold": threshold,
                "before_factor": before_factor,
                "status": "PASS" if after <= threshold else "FAIL", "reason": None}
    return {"target": name, "observed": after, "before": before,
            "operator": operator, "threshold": threshold,
            "before_factor": before_factor, "status": "BLOCKED",
            "reason": reason or "required_comparison_metric_unavailable"}


def _saved_receipt_projection_matches(saved: Any, current: Any, expected_run_id: Any,
                                     legacy_runtime_receipts: Any, *,
                                     allow_legacy_missing_run_id: bool) -> bool:
    """Compare saved receipts exactly, allowing only the mirrored pre-run_id shape."""
    compare_keys = ("status", "reason", "counts", "legacy_observations")
    if (not isinstance(saved, dict) or not isinstance(current, dict) or
            any(saved.get(key) != current.get(key) for key in compare_keys)):
        return False
    if (not isinstance(expected_run_id, str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", expected_run_id)):
        return False

    saved_rows = saved.get("receipts")
    current_rows = current.get("receipts")
    if (not isinstance(saved_rows, list) or not isinstance(current_rows, list) or
            len(saved_rows) != len(current_rows) or
            any(not isinstance(row, dict) for row in saved_rows + current_rows) or
            any(row.get("run_id") != expected_run_id for row in current_rows)):
        return False

    if all("run_id" in row for row in saved_rows):
        return saved_rows == current_rows

    # Older captures persisted the same receipt rows in both places but before
    # the projection added run_id. Requiring both copies to retain that exact
    # old shape avoids treating a missing field in a current manifest as legacy.
    if (not allow_legacy_missing_run_id or not saved_rows or
            any("run_id" in row for row in saved_rows) or
            not isinstance(legacy_runtime_receipts, list) or
            len(legacy_runtime_receipts) != len(saved_rows) or
            any(not isinstance(row, dict) or "run_id" in row
                for row in legacy_runtime_receipts) or
            legacy_runtime_receipts != saved_rows):
        return False

    return all(
        {key: value for key, value in current_row.items() if key != "run_id"} == saved_row
        for saved_row, current_row in zip(saved_rows, current_rows)
    )


def _g5_load_bundle(raw_run_dir: Any, run_root: Optional[Path] = None,
                    expected_gate: str = "g5",
                    allow_legacy_saved_receipt_projection: bool = False) -> Dict[str, Any]:
    """Read and validate one G5 bundle without trusting manifest status labels."""
    from scripts import capture_evidence
    from scripts.combat_latency_fixtures import build_g5_fixture_metadata, build_gate_profile

    errors: List[str] = []
    try:
        run_dir = Path(str(raw_run_dir))
        if not run_dir.is_absolute():
            run_dir = capture_evidence.PROJECT_ROOT / run_dir
        allowed_root = Path(run_root) if run_root is not None else capture_evidence.G5_RUN_ROOT
        if not allowed_root.is_absolute():
            allowed_root = capture_evidence.PROJECT_ROOT / allowed_root
        if (not capture_evidence._inside(run_dir, allowed_root) or
                run_dir.resolve() == allowed_root.resolve() or
                capture_evidence._has_symlink_component(run_dir, capture_evidence.PROJECT_TMP)):
            return {"run_dir": str(run_dir), "errors": ["unsafe_g5_run_directory"]}
        if not run_dir.is_dir():
            return {"run_dir": str(run_dir), "errors": ["missing_g5_run_directory"]}
    except (OSError, RuntimeError, TypeError, ValueError):
        return {"run_dir": str(raw_run_dir), "errors": ["invalid_g5_run_directory"]}

    manifest, manifest_error = capture_evidence.load_bundle_json(run_dir, "manifest.json")
    if manifest_error or not isinstance(manifest, dict):
        return {"run_dir": str(run_dir), "errors": ["manifest:%s" % (manifest_error or "invalid")]}

    gate = manifest.get("gate")
    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    party_size = party.get("size")
    if gate != expected_gate:
        errors.append("wrong_gate:%s" % (gate if gate is not None else "missing"))
    if scenario.get("id") != "combat-smoke":
        errors.append("wrong_scenario:%s" % (scenario.get("id") or "missing"))
    if party_size not in (1, 4):
        errors.append("unsupported_or_missing_party_size")

    g5 = manifest.get("g5") if isinstance(manifest.get("g5"), dict) else {}
    identity = g5.get("identity") if isinstance(g5.get("identity"), dict) else {}
    fixture = g5.get("fixture") if isinstance(g5.get("fixture"), dict) else {}
    if party_size in (1, 4):
        expected_fixture = build_g5_fixture_metadata(party_size)
        if fixture != expected_fixture:
            errors.append("fixed_fixture_identity_mismatch")
        profile = build_gate_profile("g5", "combat-smoke", party_size)
        expected_contract = {key: profile.get(key) for key in
                             ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
        expected_contract["gate"] = expected_gate
        if scenario.get("profile_contract") != expected_contract:
            errors.append("scenario_profile_mismatch")
        expected_scenario_hash = hashlib.sha256(
            json.dumps(expected_contract, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if scenario.get("sha256") != expected_scenario_hash:
            errors.append("scenario_profile_hash_mismatch")

    run_id = manifest.get("run_id")
    if (not isinstance(run_id, str) or run_id != run_dir.name or
            identity.get("run_id") != run_id):
        errors.append("run_id_missing_or_mismatched")
    if (manifest.get("evidence_kind") != "live-candidate" or
            manifest.get("live_eligible") is not True or
            (manifest.get("transport") or {}).get("client_source") != "socketio.Client"):
        errors.append("synthetic_or_ineligible_evidence")

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_hashes = source.get("relevant_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        errors.append("source_digest_missing")
        calculated_source_digest = None
    else:
        calculated_source_digest = hashlib.sha256(
            json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if identity.get("source_digest") != calculated_source_digest:
            errors.append("source_digest_mismatch")

    if not isinstance(identity.get("source_digest"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", identity.get("source_digest", "")):
        errors.append("invalid_source_digest")
    seed = manifest.get("seed") if isinstance(manifest.get("seed"), dict) else {}
    seed_id = identity.get("seed_id")
    if (not isinstance(seed_id, str) or not re.fullmatch(r"[0-9a-f]{64}", seed_id) or
            seed_id != seed.get("seed_id") or seed_id != seed.get("seed_profile_sha256")):
        errors.append("seed_identity_missing_or_mismatched")
    profile_seed = seed.get("profile_seed")
    if isinstance(profile_seed, dict):
        calculated_seed = hashlib.sha256(json.dumps(profile_seed, sort_keys=True).encode("utf-8")).hexdigest()
        if calculated_seed != seed_id:
            errors.append("seed_profile_hash_mismatch")
    else:
        errors.append("seed_profile_missing")

    configuration = manifest.get("configuration") if isinstance(manifest.get("configuration"), dict) else {}
    actual = configuration.get("actual_runtime") if isinstance(configuration.get("actual_runtime"), dict) else {}
    configured_runtime = g5.get("configured_runtime") if isinstance(g5.get("configured_runtime"), dict) else {}
    configured_provider = configured_runtime.get("configured_provider")
    configured_model = configured_runtime.get("configured_model")
    if (configured_runtime.get("status") != "ok" or
            configured_runtime.get("provenance") != "sandbox model_config.py AST literals" or
            not re.fullmatch(r"[0-9a-f]{64}", str(configured_runtime.get("model_config_sha256", "")))):
        errors.append("configured_identity_sandbox_ast_missing_or_invalid")
    if (identity.get("configured_provider") != configured_provider or
            identity.get("configured_model") != configured_model):
        errors.append("g5_configured_identity_mismatch")
    actual_provider = actual.get("provider")
    actual_model = actual.get("response_model")
    if configured_provider != G5_EXPECTED_PROVIDER:
        errors.append("configured_provider_mismatch_or_missing")
    if configured_model != G5_EXPECTED_MODEL:
        errors.append("configured_model_mismatch_or_missing")
    if actual_provider != G5_EXPECTED_PROVIDER:
        errors.append("actual_provider_mismatch_or_missing")
    if actual_model != G5_EXPECTED_MODEL:
        errors.append("actual_model_mismatch_or_missing")
    if identity.get("provider") != actual_provider or identity.get("model") != actual_model:
        errors.append("g5_actual_identity_mismatch")
    if identity.get("measurement_method") != fixture.get("measurement_method"):
        errors.append("measurement_method_mismatch")

    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    integrity = capture_evidence._artifact_integrity(run_dir, manifest, artifacts)
    errors.extend("artifact_integrity:%s" % reason for reason in integrity.get("failures", []))
    loaded = integrity.get("loaded", {})
    if artifacts.get("required_evidence_status") != "ok":
        errors.append("required_evidence_degraded_or_missing")
    checks_document = loaded.get("checks")
    check_rows = checks_document.get("checks") if isinstance(checks_document, dict) else None
    checks_source = "bundle_artifact"
    if not isinstance(check_rows, list) or not check_rows:
        errors.append("required_checks_missing")
    else:
        trace_observations = loaded.get("observations", [])
        has_enemy_resolution_decision = any(
            isinstance(event, dict)
            and event.get("event_type") == "decision"
            and event.get("decision_point") == "enemy_batch_resolution"
            for event in trace_observations
        )
        has_saved_resolver_checks = all(
            sum(1 for row in check_rows
                if isinstance(row, dict) and row.get("id") == check_id) == 1
            for check_id in (
                "final_response_validation_truth",
                "accepted_logical_batch_once",
            )
        )
        if (has_enemy_resolution_decision and party_size in (1, 4)
                and has_saved_resolver_checks
                and loaded.get("before_snapshot") is not None
                and loaded.get("after_snapshot") is not None):
            resolver_check_ids = {
                "final_response_validation_truth",
                "accepted_logical_batch_once",
            }
            try:
                check_profile = build_gate_profile(
                    expected_gate, scenario.get("id"), party_size,
                    scenario.get("branch") or "", scenario.get("phase") or "",
                )
                step_rows, step_errors = capture_evidence.load_step_snapshots(run_dir, manifest)
                check_artifacts = dict(artifacts)
                check_artifacts["trace_position_errors"] = loaded.get("trace_position_errors", [])
                check_artifacts["trace_provider_events"] = loaded.get("trace_provider_events", [])
                recomputed_checks = capture_evidence.observed_checks(
                    check_profile,
                    loaded["before_snapshot"],
                    loaded["after_snapshot"],
                    check_artifacts,
                    step_rows,
                    trace_observations,
                )
                recomputed_by_id = {
                    check_id: [row for row in recomputed_checks if row.get("id") == check_id]
                    for check_id in resolver_check_ids
                }
                saved_counts = {
                    check_id: sum(
                        1 for row in check_rows
                        if isinstance(row, dict) and row.get("id") == check_id
                    )
                    for check_id in resolver_check_ids
                }
                if any(saved_counts[check_id] != 1
                       or len(recomputed_by_id[check_id]) != 1
                       for check_id in resolver_check_ids):
                    errors.extend(
                        "required_checks_missing:%s" % check_id
                        for check_id in sorted(resolver_check_ids)
                        if saved_counts[check_id] != 1
                        or len(recomputed_by_id[check_id]) != 1
                    )
                else:
                    check_rows = [
                        recomputed_by_id[row.get("id")][0]
                        if isinstance(row, dict) and row.get("id") in resolver_check_ids
                        else row
                        for row in check_rows
                    ]
                    checks_source = "resolver_trace_recomputed"
                if step_errors:
                    # Step artifacts remain independently gated by integrity;
                    # never turn a missing step pair into resolver evidence.
                    errors.append("resolver_check_step_snapshots_incomplete")
            except Exception:
                errors.append("resolver_check_recomputation_failed")
        failed_required_checks = sorted({
            str(row.get("id") or "unknown") for row in check_rows
            if isinstance(row, dict) and row.get("required", True) and row.get("status") != "PASS"
        })
        if any(not isinstance(row, dict) for row in check_rows):
            failed_required_checks.append("unknown")
        errors.extend("required_checks_not_passed:%s" % check_id
                      for check_id in sorted(set(failed_required_checks)))

    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    for key in ("timeouts", "step_caps_reached", "idle_settle_caps_reached",
                "blocked_step_attempts", "blocked_control_attempts"):
        value = counts.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append("capture_count_unavailable:%s" % key)
        elif value:
            errors.append("capture_timeout_or_cap:%s" % key)

    trace_errors = loaded.get("trace_position_errors", [])
    positions = loaded.get("trace_positions", [])
    trace_windows = g5.get("trace_windows") if isinstance(g5.get("trace_windows"), dict) else None
    projection = capture_evidence.project_g5_trace(positions, run_id, trace_errors, trace_windows)
    if projection.get("status") != "PASS":
        errors.append("trace_attribution:%s" % str(projection.get("reason")))
    receipt_projection = capture_evidence.project_g4_receipts(positions, expected_run_id=run_id)
    saved_receipt_projection = manifest.get("receipt_projection")
    if not _saved_receipt_projection_matches(
            saved_receipt_projection, receipt_projection, run_id,
            actual.get("receipts"),
            allow_legacy_missing_run_id=allow_legacy_saved_receipt_projection):
        errors.append("saved_receipt_projection_mismatch")
    receipt_rows = receipt_projection.get("receipts", [])
    receipt_providers = sorted({row.get("provider") for row in receipt_rows
                                if isinstance(row, dict) and row.get("provider")})
    receipt_models = sorted({row.get("resolved_model") for row in receipt_rows
                             if isinstance(row, dict) and row.get("resolved_model")})
    derived_actual_provider = receipt_providers[0] if len(receipt_providers) == 1 else None
    derived_actual_model = receipt_models[0] if len(receipt_models) == 1 else None
    if receipt_projection.get("status") != "ok":
        errors.append("actual_provider_receipts_not_pass:%s" % str(receipt_projection.get("reason")))
    if actual_provider != derived_actual_provider:
        errors.append("actual_provider_trace_receipt_mismatch")
    if actual_model != derived_actual_model:
        errors.append("actual_model_trace_receipt_mismatch")
    saved_projection = g5.get("trace_attribution")
    projection_compare_keys = ("status", "reason", "counts", "actual_runtime", "observed_rounds",
                               "observed_enemy_batches", "work_units", "window_buckets",
                               "provider_receipts", "assignments", "window_errors")

    def trace_projection_comparison_view(value: Any) -> Dict[str, Any]:
        """Ignore additive legacy labels when checking older saved G5 projections."""
        if not isinstance(value, dict):
            return {}
        view = {key: value.get(key) for key in projection_compare_keys}
        if isinstance(view.get("counts"), dict):
            view["counts"] = {key: item for key, item in view["counts"].items()
                              if key not in ("legacy_provider_observations",
                                             "legacy_provider_elapsed_ms")}
        for field in ("work_units", "window_buckets"):
            rows = view.get(field)
            if isinstance(rows, list):
                view[field] = [{key: item for key, item in row.items()
                                if key not in ("legacy_provider_calls",
                                               "legacy_provider_elapsed_ms")}
                               if isinstance(row, dict) else row
                               for row in rows]
        rows = view.get("provider_receipts")
        if isinstance(rows, list):
            view["provider_receipts"] = [
                {key: item for key, item in row.items()
                 if key not in ("classification", "identity_status")}
                if isinstance(row, dict) else row for row in rows
            ]
        return view

    if (not isinstance(saved_projection, dict) or
            trace_projection_comparison_view(saved_projection) !=
            trace_projection_comparison_view(projection)):
        errors.append("saved_trace_attribution_mismatch")
    if actual.get("status") != "PASS":
        errors.append("actual_runtime_trace_status_not_pass")
    if projection.get("counts", {}).get("unattributed_provider_calls_in_measured_span") != 0:
        errors.append("unattributed_provider_calls")
    if projection.get("counts", {}).get("unattributed_file_writes_in_measured_span") != 0:
        errors.append("unattributed_file_writes")

    receipts = g5.get("receipts")
    expected_steps = fixture.get("steps") if isinstance(fixture.get("steps"), list) else []
    if not isinstance(receipts, list) or len(receipts) != len(expected_steps):
        errors.append("step_receipts_missing_or_incomplete")
        receipts = receipts if isinstance(receipts, list) else []
    for index, expected_step in enumerate(expected_steps):
        receipt = receipts[index] if index < len(receipts) and isinstance(receipts[index], dict) else None
        if receipt is None:
            continue
        if receipt.get("step") != index + 1:
            errors.append("step_receipt_index_mismatch:%d" % (index + 1))
        expected_unit = {"type": expected_step.get("unit_type"), "id": expected_step.get("unit_id"),
                         "round": expected_step.get("round")}
        if receipt.get("work_unit") != expected_unit:
            errors.append("step_receipt_work_unit_mismatch:%d" % (index + 1))
        frame = receipt.get("trace_window") if isinstance(receipt.get("trace_window"), dict) else {}
        windows_step = (trace_windows.get("steps", [])[index]
                        if isinstance(trace_windows, dict) and isinstance(trace_windows.get("steps"), list)
                        and index < len(trace_windows.get("steps", [])) else {})
        if (windows_step.get("unit_id") != expected_unit["id"] or
                windows_step.get("unit_type") != expected_unit["type"] or
                windows_step.get("start_epoch_ms") != frame.get("start_epoch_ms") or
                windows_step.get("end_epoch_ms") != frame.get("end_epoch_ms") or
                frame.get("unit_id") != expected_unit["id"] or
                frame.get("unit_type") != expected_unit["type"] or
                frame.get("round") != expected_unit["round"] or
                frame.get("step") != index + 1):
            errors.append("step_receipt_trace_window_mismatch:%d" % (index + 1))
        for duration_key, reason_key in (("work_only_ms", "work_only_reason"),
                                         ("quiet_window_elapsed_ms", "quiet_window_reason")):
            duration = receipt.get(duration_key)
            if duration is None:
                reason = receipt.get(reason_key)
                if not isinstance(reason, str) or not reason:
                    errors.append("step_receipt_missing_timing_reason:%d:%s" %
                                  (index + 1, duration_key))
            elif not _g5_is_number(duration) or duration < 0:
                errors.append("step_receipt_invalid_timing:%d:%s" % (index + 1, duration_key))
        if receipt.get("timed_out") is not False:
            errors.append("step_receipt_timeout:%d" % (index + 1))
        if receipt.get("cap_reached") is not False:
            errors.append("step_receipt_cap:%d" % (index + 1))

    return {
        "run_dir": str(run_dir), "run_id": run_id, "party_size": party_size,
        "manifest": manifest, "fixture": fixture, "identity": identity,
        "configured_provider": configured_provider, "configured_model": configured_model,
        "actual_provider": derived_actual_provider, "actual_model": derived_actual_model,
        "trace_events": positions, "trace_projection": projection,
        "receipt_projection": receipt_projection, "receipts": receipts,
        "checks": check_rows, "checks_source": checks_source,
        "errors": sorted(set(errors)),
    }


def _g5_identity_mismatches(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    mismatches: List[str] = []
    if before.get("party_size") != after.get("party_size"):
        mismatches.append("party_size")
    before_fixture, after_fixture = before.get("fixture", {}), after.get("fixture", {})
    for key in ("fixture_id", "version", "party_size", "steps_sha256", "scripted_step_count",
                "measurement_method", "steps", "work_units"):
        if before_fixture.get(key) != after_fixture.get(key):
            mismatches.append("fixture_%s" % key)
    for key in ("seed_id",):
        if before.get("identity", {}).get(key) != after.get("identity", {}).get(key):
            mismatches.append(key)
    for key in ("configured_provider", "configured_model", "actual_provider", "actual_model"):
        if before.get(key) != after.get(key):
            mismatches.append(key)
    if before.get("identity", {}).get("measurement_method") != after.get("identity", {}).get("measurement_method"):
        mismatches.append("measurement_method")
    if before.get("run_id") == after.get("run_id") or before.get("run_dir") == after.get("run_dir"):
        mismatches.append("before_after_run_not_distinct")
    return mismatches


def _g5_extract_rates(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    validation_events = []
    nl_events = []
    for event in events:
        if event.get("event_type") != "decision":
            continue
        point = str(event.get("decision_point", "")).lower()
        if "validation" in point:
            validation_events.append(event)
        if point == "pc_phase_parser":
            nl_events.append(event)

    if not validation_events:
        validation = {"total_events": None, "skipped": {"count": None, "rate": None,
                         "reason": "no_validation_routing_events"},
                      "llm_path": {"count": None, "rate": None,
                                   "reason": "no_validation_routing_events"},
                      "skip_reasons": {}, "reason": "no_validation_routing_events"}
    else:
        skipped = 0
        llm_path = 0
        unclassified = 0
        reasons: Dict[str, int] = {}
        for event in validation_events:
            outcome = str(event.get("outcome", "")).lower()
            skip = event.get("skip_llm_validation") is True or outcome in ("skip", "skipped")
            not_skip = event.get("skip_llm_validation") is False or outcome in ("llm", "validate", "not_skipped")
            if skip:
                skipped += 1
                reason = event.get("reason") or event.get("skip_reason")
                if isinstance(reason, str) and reason:
                    reasons[reason[:80]] = reasons.get(reason[:80], 0) + 1
            elif not_skip:
                llm_path += 1
            else:
                unclassified += 1
        total = len(validation_events)
        validation = {
            "total_events": total,
            "skipped": {"count": skipped if skipped else None,
                        "rate": round(skipped / total, 6) if skipped else None,
                        "reason": None if skipped else "outcome_not_observed"},
            "llm_path": {"count": llm_path if llm_path else None,
                         "rate": round(llm_path / total, 6) if llm_path else None,
                         "reason": None if llm_path else "outcome_not_observed"},
            "unclassified_events": unclassified if unclassified else None,
            "skip_reasons": {key: reasons[key] for key in sorted(reasons)},
            "reason": None,
        }

    nl_categories = ("hit", "miss", "false_positive", "llm_fallback", "unavailable")
    if not nl_events:
        nl = {"total_events": None, "outcomes": {
            name: {"count": None, "rate": None, "reason": "no_nl_decision_events"}
            for name in nl_categories}, "reason": "no_nl_decision_events"}
    else:
        counts = {name: 0 for name in nl_categories}
        for event in nl_events:
            source = str(event.get("decision_source", "")).lower()
            explicit_outcome = event.get("outcome")
            if explicit_outcome in ("hit", "miss", "false_positive", "unavailable"):
                counts[explicit_outcome] += 1
            elif "outcome" not in event and source == "deterministic":
                # Legacy deterministic parser events are emitted only after
                # deterministic application succeeds; fallback source alone
                # cannot distinguish miss, false-positive, or unavailability.
                counts["hit"] += 1

            llm_fallback = event.get("llm_fallback")
            if not isinstance(llm_fallback, bool):
                llm_fallback = source == "llm_fallback"
            if llm_fallback:
                counts["llm_fallback"] += 1
        total = len(nl_events)
        outcomes = {}
        for name in nl_categories:
            count = counts[name]
            outcomes[name] = {"count": count if count else None,
                              "rate": round(count / total, 6) if count else None,
                              "reason": None if count else "outcome_not_observed"}
        nl = {"total_events": total, "outcomes": outcomes, "reason": None}
    return {"validation_skip": validation, "nl_fast_path": nl}


def _g5_summarize_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    fixture = bundle.get("fixture", {})
    expected_work_units: List[Dict[str, Any]] = []
    units = fixture.get("work_units", {}) if isinstance(fixture.get("work_units"), dict) else {}
    for unit_type, list_key in (("action", "actions"), ("batch", "batches"),
                                ("control", "controls")):
        rows = units.get(list_key, [])
        if isinstance(rows, list):
            expected_work_units.extend({"type": unit_type, **row} for row in rows if isinstance(row, dict))

    projection = bundle.get("trace_projection", {})
    projected_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in projection.get("work_units", []) if isinstance(projection.get("work_units"), list) else []:
        if not isinstance(row, dict) or row.get("type") not in ("action", "batch", "control"):
            continue
        projected_groups[(row["type"], row.get("id"))] = row
    expected_keys = {(row["type"], row.get("unit_id")) for row in expected_work_units}
    errors: List[str] = []
    if projection.get("status") != "PASS":
        errors.append("trace_window_projection_not_pass")
    for unit_type, unit_id in projected_groups:
        if (unit_type, unit_id) not in expected_keys:
            errors.append("unexpected_work_unit:%s:%s" % (unit_type, unit_id))

    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for unit in expected_work_units:
        key = (unit["type"], unit.get("unit_id"))
        observed = projected_groups.get(key)
        if observed is None:
            errors.append("work_unit_window_missing:%s:%s" % key)
        grouped[key] = {
            "type": unit["type"], "id": unit.get("unit_id"), "round": unit.get("round"),
            "provider_calls": observed.get("provider_calls", 0) if observed else 0,
            "legacy_provider_calls": observed.get("legacy_provider_calls", 0) if observed else 0,
            "legacy_provider_elapsed_ms": observed.get("legacy_provider_elapsed_ms", 0.0) if observed else 0.0,
            "file_writes": observed.get("file_writes", 0) if observed else 0,
        }
    phase_counts = {phase: {"provider_calls": 0, "legacy_provider_calls": 0,
                            "legacy_provider_elapsed_ms": 0.0,
                            "file_writes": 0} for phase in G5_PHASES}
    for (unit_type, _), row in grouped.items():
        phase = "PC_PHASE" if unit_type == "action" else "ENEMY_PHASE" if unit_type == "batch" else None
        if phase:
            phase_counts[phase]["provider_calls"] += row["provider_calls"]
            phase_counts[phase]["legacy_provider_calls"] += row["legacy_provider_calls"]
            phase_counts[phase]["legacy_provider_elapsed_ms"] += row["legacy_provider_elapsed_ms"]
            phase_counts[phase]["file_writes"] += row["file_writes"]

    receipt_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for receipt in bundle.get("receipts", []):
        work_unit = receipt.get("work_unit") if isinstance(receipt, dict) else None
        if not isinstance(work_unit, dict) or work_unit.get("type") not in ("action", "batch", "control"):
            continue
        key = (work_unit["type"], work_unit.get("id"))
        receipt_groups.setdefault(key, []).append(receipt)

    decisions: Dict[str, List[Dict[str, Any]]] = {}
    assignments = projection.get("assignments", []) if isinstance(projection.get("assignments"), list) else []
    for index, event in enumerate(bundle.get("trace_events", [])):
        if not isinstance(event, dict) or event.get("event_type") != "decision":
            continue
        assignment = assignments[index] if index < len(assignments) else {}
        if assignment.get("work_unit_type") == "action" and isinstance(assignment.get("work_unit_id"), str):
            decisions.setdefault(assignment["work_unit_id"], []).append(event)

    action_rows = []
    batch_rows = []
    control_rows = []
    for unit in expected_work_units:
        unit_type, unit_id = unit["type"], unit.get("unit_id")
        key = (unit_type, unit_id)
        receipts = receipt_groups.get(key, [])
        if not receipts:
            errors.append("work_unit_timing_receipts_missing:%s:%s" % (unit_type, unit_id))
        work_values = [row.get("work_only_ms") for row in receipts]
        quiet_values = [row.get("quiet_window_elapsed_ms") for row in receipts]
        work_ms = (round(sum(float(value) for value in work_values), 3)
                   if receipts and all(_g5_is_number(value) and value >= 0 for value in work_values) else None)
        quiet_ms = (round(sum(float(value) for value in quiet_values), 3)
                    if receipts and all(_g5_is_number(value) and value >= 0 for value in quiet_values) else None)
        if work_ms is None:
            errors.append("work_only_timing_unavailable:%s:%s" % (unit_type, unit_id))
        if quiet_ms is None:
            errors.append("quiet_window_timing_unavailable:%s:%s" % (unit_type, unit_id))
        calls = grouped[key]["provider_calls"]
        classification = None
        if unit_type == "action":
            if calls > 0:
                classification = "llm"
            elif any(event.get("decision_source") == "deterministic" or
                     event.get("outcome") == "hit" for event in decisions.get(unit_id, [])):
                classification = "fast"
            else:
                errors.append("pc_action_unclassifiable:%s" % unit_id)
        row = {**grouped[key], "work_only_ms": work_ms, "quiet_window_elapsed_ms": quiet_ms,
               "classification": classification}
        (action_rows if unit_type == "action" else batch_rows if unit_type == "batch" else control_rows).append(row)

    action_rows.sort(key=lambda row: (row.get("round", 0), row.get("id", "")))
    batch_rows.sort(key=lambda row: (row.get("round", 0), row.get("id", "")))
    control_rows.sort(key=lambda row: (row.get("round", 0), row.get("id", "")))
    rounds = sorted({row["round"] for row in action_rows + batch_rows
                     if isinstance(row.get("round"), int) and not isinstance(row.get("round"), bool)})
    round_rows = []
    for round_number in rounds:
        round_units = [row for row in action_rows + batch_rows if row.get("round") == round_number]
        round_work = (round(sum(row["work_only_ms"] for row in round_units), 3)
                      if round_units and all(_g5_is_number(row.get("work_only_ms")) for row in round_units) else None)
        round_quiet = (round(sum(row["quiet_window_elapsed_ms"] for row in round_units), 3)
                       if round_units and all(_g5_is_number(row.get("quiet_window_elapsed_ms")) for row in round_units) else None)
        round_rows.append({"round": round_number, "action_count": sum(row["type"] == "action" for row in round_units),
                           "batch_count": sum(row["type"] == "batch" for row in round_units),
                           "provider_calls": sum(row["provider_calls"] for row in round_units),
                           "legacy_provider_calls": sum(row["legacy_provider_calls"] for row in round_units),
                           "legacy_provider_elapsed_ms": round(sum(
                               row["legacy_provider_elapsed_ms"] for row in round_units), 3),
                           "file_writes": sum(row["file_writes"] for row in round_units),
                           "work_only_ms": round_work, "quiet_window_elapsed_ms": round_quiet})

    action_classes = {name: [row for row in action_rows if row.get("classification") == name]
                      for name in ("fast", "llm")}
    def complete_summary(rows: List[Dict[str, Any]], field: str) -> Optional[float]:
        values = [row.get(field) for row in rows]
        if not values or not all(_g5_is_number(value) for value in values):
            return None
        return _g5_summary(values)

    return {
        "errors": sorted(set(errors)), "actions": action_rows, "batches": batch_rows,
        "controls": control_rows,
        "legacy_provider_observations": projection.get("counts", {}).get(
            "legacy_provider_observations", 0),
        "legacy_provider_elapsed_ms": projection.get("counts", {}).get(
            "legacy_provider_elapsed_ms", 0.0),
        "phase_counts": phase_counts, "rounds": round_rows,
        "pc_action_p50_work_only_seconds": {
            name: (round(complete_summary(rows, "work_only_ms") / 1000.0, 6)
                   if complete_summary(rows, "work_only_ms") is not None else None)
            for name, rows in action_classes.items()},
        "pc_action_p50_quiet_window_seconds": {
            name: (round(complete_summary(rows, "quiet_window_elapsed_ms") / 1000.0, 6)
                   if complete_summary(rows, "quiet_window_elapsed_ms") is not None else None)
            for name, rows in action_classes.items()},
        "enemy_batch_p50_work_only_seconds": (
            round(complete_summary(batch_rows, "work_only_ms") / 1000.0, 6)
            if complete_summary(batch_rows, "work_only_ms") is not None else None),
        "enemy_batch_p50_quiet_window_seconds": (
            round(complete_summary(batch_rows, "quiet_window_elapsed_ms") / 1000.0, 6)
            if complete_summary(batch_rows, "quiet_window_elapsed_ms") is not None else None),
        "rates": _g5_extract_rates(bundle.get("trace_events", [])),
    }


def _g5_add_bundle_checks(targets: List[Dict[str, Any]], party_size: int,
                          before: Dict[str, Any], after: Dict[str, Any],
                          before_metrics: Dict[str, Any], after_metrics: Dict[str, Any]) -> List[str]:
    blocked: List[str] = []
    for role, bundle, metrics in (("before", before, before_metrics), ("after", after, after_metrics)):
        for reason in bundle.get("errors", []) + metrics.get("errors", []):
            blocked.append("p%d_%s:%s" % (party_size, role, reason))

    for classification, target_name, operator, threshold in (
        ("llm", "pc_action_llm_p50_seconds", "<=", 8.0),
        ("fast", "pc_action_fast_p50_seconds", "<", 1.0),
    ):
        rows = [row for row in after_metrics.get("actions", []) if row.get("classification") == classification]
        if rows:
            observed = after_metrics["pc_action_p50_work_only_seconds"][classification]
            target = _g5_check(target_name, observed, operator, threshold)
            target.update({"party_size": party_size, "action_count": len(rows), "timing_source": "work_only_ms"})
        elif after_metrics.get("errors"):
            target = _g5_check(target_name, None, operator, threshold, "action_classification_or_timing_unavailable")
            target.update({"party_size": party_size, "action_count": None, "timing_source": "work_only_ms"})
        else:
            target = {"target": target_name, "observed": None, "operator": operator,
                      "threshold": threshold, "status": "NOT_APPLICABLE", "reason": "no_actions_in_path",
                      "party_size": party_size, "action_count": 0, "timing_source": "work_only_ms"}
        targets.append(target)

    for row in after_metrics.get("actions", []):
        limit = 1 if row.get("classification") == "fast" else 2
        name = "pc_action_fast_provider_calls" if limit == 1 else "pc_action_llm_provider_calls"
        target = _g5_check(name, row.get("provider_calls"), "<=", limit)
        target.update({"party_size": party_size, "work_unit_id": row.get("id"),
                       "classification": row.get("classification")})
        targets.append(target)
    for row in after_metrics.get("batches", []):
        target = _g5_check("enemy_batch_provider_calls", row.get("provider_calls"), "==", 1)
        target.update({"party_size": party_size, "work_unit_id": row.get("id")})
        targets.append(target)
    batch_rows = after_metrics.get("batches", [])
    if batch_rows:
        batch_latency = _g5_check(
            "enemy_batch_p50_seconds", after_metrics.get("enemy_batch_p50_work_only_seconds"), "<=", 15.0,
            None if after_metrics.get("enemy_batch_p50_work_only_seconds") is not None
            else "enemy_batch_work_only_timing_unavailable",
        )
        batch_latency.update({"party_size": party_size, "batch_count": len(batch_rows),
                              "timing_source": "work_only_ms"})
    else:
        batch_latency = _g5_check("enemy_batch_p50_seconds", None, "<=", 15.0,
                                  "enemy_batch_work_unit_missing")
        batch_latency.update({"party_size": party_size, "batch_count": 0,
                              "timing_source": "work_only_ms"})
    targets.append(batch_latency)
    if after_metrics.get("rounds"):
        max_writes = max(row["file_writes"] for row in
                         after_metrics.get("actions", []) + after_metrics.get("batches", []))
        write_target = _g5_check("file_writes_per_combat_turn", max_writes, "<=", 3)
        write_target.update({"party_size": party_size, "scope": "per_action_or_enemy_batch",
                             "work_unit_counts": [
                                 {"type": row["type"], "id": row["id"], "file_writes": row["file_writes"]}
                                 for row in after_metrics.get("actions", []) + after_metrics.get("batches", [])
                             ]})
        targets.append(write_target)
    else:
        write_target = _g5_check("file_writes_per_combat_turn", None, "<=", 3, "round_write_counts_unavailable")
        write_target.update({"party_size": party_size})
        targets.append(write_target)

    if party_size == 1:
        before_p50 = _g5_complete_action_p50(before_metrics)
        after_p50 = _g5_complete_action_p50(after_metrics)
        latency = _g5_comparison_check(
            "p1_no_latency_regression",
            round(after_p50 / 1000.0, 6) if after_p50 is not None else None,
            round(before_p50 / 1000.0, 6) if before_p50 is not None else None,
            "p1_action_p50_unavailable" if before_p50 is None or after_p50 is None else None,
            before_factor=G5_P1_LATENCY_REGRESSION_FACTOR,
        )
        latency.update({"party_size": party_size, "timing_source": "work_only_ms"})
        targets.append(latency)
        for target_name, field in (("p1_no_provider_call_regression", "provider_calls"),
                                   ("p1_no_file_write_regression", "file_writes")):
            before_count = sum(row[field] for row in before_metrics.get("actions", []) + before_metrics.get("batches", []))
            after_count = sum(row[field] for row in after_metrics.get("actions", []) + after_metrics.get("batches", []))
            target = _g5_comparison_check(target_name, after_count, before_count)
            target.update({"party_size": party_size})
            targets.append(target)

    if party_size == 4:
        def complete_round(metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            for row in metrics.get("rounds", []):
                if row.get("round") == 1 and row.get("action_count") == 8 and row.get("batch_count") == 1:
                    return row
            return None
        before_round, after_round = complete_round(before_metrics), complete_round(after_metrics)
        if (before_round is None or after_round is None or
                not _g5_is_number(before_round.get("work_only_ms")) or
                not _g5_is_number(after_round.get("work_only_ms")) or before_round["work_only_ms"] <= 0):
            target = _g5_check("p4_round_latency_improvement", None, ">=", 0.30,
                               "complete_round_work_only_timing_unavailable")
        else:
            improvement = (before_round["work_only_ms"] - after_round["work_only_ms"]) / before_round["work_only_ms"]
            target = _g5_check("p4_round_latency_improvement", round(improvement, 6), ">=", 0.30)
        target.update({"party_size": party_size, "before_round_work_only_ms":
                       before_round.get("work_only_ms") if before_round else None,
                       "after_round_work_only_ms": after_round.get("work_only_ms") if after_round else None,
                        "complete_round": "8 scripted PC steps + 1 enemy batch", "timing_source": "work_only_ms"})
        targets.append(target)

    before_phases = before_metrics.get("phase_counts", {})
    after_phases = after_metrics.get("phase_counts", {})
    phase_deltas = []
    unit_deltas = []
    for phase in G5_PHASES:
        left, right = before_phases.get(phase, {}), after_phases.get(phase, {})
        row = {"phase": phase,
               "before_provider_calls": left.get("provider_calls"),
               "after_provider_calls": right.get("provider_calls"),
               "provider_call_delta": right.get("provider_calls", 0) - left.get("provider_calls", 0),
               "before_file_writes": left.get("file_writes"),
               "after_file_writes": right.get("file_writes"),
               "file_write_delta": right.get("file_writes", 0) - left.get("file_writes", 0)}
        phase_deltas.append(row)
        for metric, delta_key, target_name in (
                ("provider_calls", "provider_call_delta", "phase_provider_calls_no_increase"),
                ("file_writes", "file_write_delta", "phase_file_writes_no_increase")):
            target = _g5_check(target_name, row[delta_key], "<=", 0)
            target.update({"party_size": party_size, "phase": phase, "metric": metric})
            targets.append(target)

    before_units = {(row["type"], row["id"]): row for row in
                    before_metrics.get("actions", []) + before_metrics.get("batches", [])}
    after_units = {(row["type"], row["id"]): row for row in
                   after_metrics.get("actions", []) + after_metrics.get("batches", [])}
    for unit_type, unit_id in sorted(set(before_units) | set(after_units)):
        left, right = before_units.get((unit_type, unit_id), {}), after_units.get((unit_type, unit_id), {})
        unit_deltas.append({"work_unit_type": unit_type, "work_unit_id": unit_id,
                            "before_provider_calls": left.get("provider_calls"),
                            "after_provider_calls": right.get("provider_calls"),
                            "provider_call_delta": (right.get("provider_calls", 0) -
                                                    left.get("provider_calls", 0)),
                            "before_file_writes": left.get("file_writes"),
                            "after_file_writes": right.get("file_writes"),
                            "file_write_delta": (right.get("file_writes", 0) -
                                                 left.get("file_writes", 0))})
    return blocked, {"phases": phase_deltas, "work_units": unit_deltas}


def evaluate_g5_comparison(before_dirs: Iterable[Any], after_dirs: Iterable[Any]) -> Dict[str, Any]:
    """Evaluate exactly matched P1/P4 G5 bundles; G1 remains historical context only."""
    before_inputs = list(before_dirs) if not isinstance(before_dirs, (str, bytes, Path)) else [before_dirs]
    after_inputs = list(after_dirs) if not isinstance(after_dirs, (str, bytes, Path)) else [after_dirs]
    blocking_reasons: List[str] = []
    if len(before_inputs) != 2:
        blocking_reasons.append("before_role_requires_exactly_two_bundles")
    if len(after_inputs) != 2:
        blocking_reasons.append("after_role_requires_exactly_two_bundles")
    loaded = [("before", _g5_load_bundle(path)) for path in before_inputs]
    loaded.extend(("after", _g5_load_bundle(path)) for path in after_inputs)
    seen_paths: Dict[str, int] = {}
    seen_runs: Dict[str, int] = {}
    parties: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
    for role, bundle in loaded:
        run_dir = bundle.get("run_dir", "")
        seen_paths[run_dir] = seen_paths.get(run_dir, 0) + 1
        run_id = bundle.get("run_id")
        if isinstance(run_id, str):
            seen_runs[run_id] = seen_runs.get(run_id, 0) + 1
        for reason in bundle.get("errors", []):
            blocking_reasons.append("%s:%s:%s" % (role, run_id or "unknown_run", reason))
        party_size = bundle.get("party_size")
        if party_size in (1, 4):
            parties.setdefault(party_size, {"before": [], "after": []})[role].append(bundle)
    if any(count > 1 for count in seen_paths.values()):
        blocking_reasons.append("duplicate_bundle_path_or_role")
    if any(count > 1 for count in seen_runs.values()):
        blocking_reasons.append("duplicate_run_id")
    if any(bundle.get("party_size") not in (1, 4) for _, bundle in loaded):
        blocking_reasons.append("missing_or_invalid_party_role")

    targets: List[Dict[str, Any]] = []
    comparisons: List[Dict[str, Any]] = []
    for party_size in (1, 4):
        roles = parties.get(party_size, {"before": [], "after": []})
        if len(roles["before"]) != 1:
            blocking_reasons.append("p%d_before_role_missing_or_duplicate" % party_size)
        if len(roles["after"]) != 1:
            blocking_reasons.append("p%d_after_role_missing_or_duplicate" % party_size)
        if len(roles["before"]) != 1 or len(roles["after"]) != 1:
            comparisons.append({"party_size": party_size, "status": "BLOCKED",
                                "blocking_reasons": ["before_after_pair_missing_or_duplicate"]})
            continue
        before, after = roles["before"][0], roles["after"][0]
        mismatches = _g5_identity_mismatches(before, after)
        for mismatch in mismatches:
            blocking_reasons.append("p%d_identity_mismatch:%s" % (party_size, mismatch))
        before_metrics, after_metrics = _g5_summarize_bundle(before), _g5_summarize_bundle(after)
        pair_blocked, deltas = _g5_add_bundle_checks(
            targets, party_size, before, after, before_metrics, after_metrics
        )
        blocking_reasons.extend(pair_blocked)
        comparison = {
            "party_size": party_size,
            "fixture_id": before.get("fixture", {}).get("fixture_id"),
            "before_run_id": before.get("run_id"), "after_run_id": after.get("run_id"),
            "identity_match": {"matched": not mismatches, "mismatches": mismatches,
                               "party_size": party_size,
                               "fixture_script_sha256": before.get("fixture", {}).get("steps_sha256"),
                               "seed_id": before.get("identity", {}).get("seed_id"),
                               "configured_provider": before.get("configured_provider"),
                               "configured_model": before.get("configured_model"),
                               "actual_provider": before.get("actual_provider"),
                               "actual_model": before.get("actual_model"),
                               "measurement_method": before.get("identity", {}).get("measurement_method"),
                               "source_digest_before": before.get("identity", {}).get("source_digest"),
                               "source_digest_after": after.get("identity", {}).get("source_digest"),
                               "source_digest_changed": (before.get("identity", {}).get("source_digest") !=
                                                         after.get("identity", {}).get("source_digest")),
                               "source_digest_note": "source changes are recorded, not used as a matching key"},
            "before": before_metrics, "after": after_metrics,
            "phase_deltas": deltas["phases"], "work_unit_deltas": deltas["work_units"],
            "rates": {"before": before_metrics.get("rates"), "after": after_metrics.get("rates")},
        }
        comparisons.append(comparison)

    p4 = next((row for row in comparisons if row.get("party_size") == 4), {})
    p4_before, p4_after = p4.get("before", {}), p4.get("after", {})
    if p4_before and p4_after:
        before_round = next((row for row in p4_before.get("rounds", [])
                             if row.get("round") == 1 and row.get("action_count") == 8 and
                             row.get("batch_count") == 1), None)
        after_round = next((row for row in p4_after.get("rounds", [])
                            if row.get("round") == 1 and row.get("action_count") == 8 and
                            row.get("batch_count") == 1), None)
        # The target row is emitted by the party evaluator; this explicit summary
        # keeps work-only and quiet-window values side by side for reviewers.
        round_timing = {"before_work_only_ms": before_round.get("work_only_ms") if before_round else None,
                        "after_work_only_ms": after_round.get("work_only_ms") if after_round else None,
                        "before_quiet_window_elapsed_ms": before_round.get("quiet_window_elapsed_ms") if before_round else None,
                        "after_quiet_window_elapsed_ms": after_round.get("quiet_window_elapsed_ms") if after_round else None,
                        "work_only_is_gating_metric": True, "quiet_window_is_gating_metric": False}
    else:
        round_timing = {"before_work_only_ms": None, "after_work_only_ms": None,
                        "before_quiet_window_elapsed_ms": None, "after_quiet_window_elapsed_ms": None,
                        "work_only_is_gating_metric": True, "quiet_window_is_gating_metric": False,
                        "reason": "p4_pair_unavailable"}

    failed_targets = [target for target in targets if target.get("status") == "FAIL"]
    blocked_targets = [target for target in targets if target.get("status") == "BLOCKED"]
    if blocking_reasons or blocked_targets:
        automated_status = "BLOCKED"
    elif failed_targets:
        automated_status = "FAIL"
    else:
        automated_status = "READY_FOR_PRIMARY_REVIEW"
    return {
        "automated_status": automated_status,
        "primary_verdict": "PENDING",
        "gate": "g5",
        "comparison_method": "matched_g5_before_after",
        "fixed_targets": G5_TARGETS,
        "party_comparisons": comparisons,
        "targets": targets,
        "p4_complete_round_timing": round_timing,
        "target_misses": [{"target": row.get("target"), "party_size": row.get("party_size"),
                           "work_unit_id": row.get("work_unit_id"), "phase": row.get("phase"),
                           "metric": row.get("metric"), "observed": row.get("observed"),
                           "threshold": row.get("threshold")} for row in failed_targets],
        "blocking_reasons": sorted(set(blocking_reasons + [
            "required_target_metric_unavailable:%s:p%s" % (row.get("target"), row.get("party_size"))
            for row in blocked_targets])),
        "g1_historical_context": {"label": "historical G1 gpt-5.6-luna evidence",
                                  "used_as_baseline": False,
                                  "comparison_baseline": "matched G5 before bundle only"},
    }


def render_g5_comparison(report: Dict[str, Any]) -> str:
    """Render a compact, text-free G5 comparison table for review."""
    lines = ["Combat G5 comparison [%s]" % report.get("automated_status", "BLOCKED"),
             "target | party | observed | rule | status"]
    for row in report.get("targets", []):
        lines.append("%s | P%s | %s | %s %s | %s" % (
            row.get("target"), row.get("party_size", "-"), _value(row.get("observed")),
            row.get("operator"), _value(row.get("threshold")), row.get("status")))
    for comparison in report.get("party_comparisons", []):
        after = comparison.get("after", {}) if isinstance(comparison, dict) else {}
        legacy_count = after.get("legacy_provider_observations", 0)
        if not isinstance(legacy_count, int) or isinstance(legacy_count, bool) or legacy_count <= 0:
            continue
        lines.append("P%s legacy compression provider observations: %d (included in total provider calls; excluded from core receipts)" %
                     (comparison.get("party_size", "-"), legacy_count))
        for row in after.get("actions", []) + after.get("batches", []):
            if row.get("legacy_provider_calls", 0):
                lines.append("  %s %s: %d legacy provider call(s), %.3f ms observed" % (
                    row.get("type"), row.get("id"), row.get("legacy_provider_calls"),
                    row.get("legacy_provider_elapsed_ms", 0.0)))
    if report.get("blocking_reasons"):
        lines.append("Blocking reasons: %s" % ", ".join(report["blocking_reasons"]))
    return "\n".join(lines)


def _g5r_canonical_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _g5r_snapshot_pc_hp(snapshot: Any, party_roster: Any) -> Dict[str, Any]:
    """Extract an unambiguous HP observation for each PC and retain file targets."""
    if not isinstance(snapshot, dict):
        return {"hp_by_pc": {}, "errors": ["snapshot_not_object"]}
    if not isinstance(party_roster, list) or not party_roster:
        return {"hp_by_pc": {}, "errors": ["party_roster_unavailable"]}
    roster: Dict[str, str] = {}
    errors: List[str] = []
    for raw_name in party_roster:
        if not isinstance(raw_name, str) or not raw_name.strip():
            errors.append("party_roster_invalid_name")
            continue
        canonical = _g5r_canonical_name(raw_name)
        if not canonical or canonical in roster:
            errors.append("party_roster_identity_ambiguous")
            continue
        roster[canonical] = raw_name

    candidates: Dict[str, Dict[str, Any]] = {}

    def collect(source_name: str, rows: Any) -> None:
        if isinstance(rows, list):
            iterable = [(str(row.get("name") or ""), row) for row in rows if isinstance(row, dict)]
        elif isinstance(rows, dict):
            iterable = list(rows.items())
        else:
            errors.append("snapshot_%s_characters_unavailable" % source_name)
            return
        for raw_key, value in iterable:
            if not isinstance(value, dict):
                continue
            name = value.get("name")
            if not isinstance(name, str) or not name.strip():
                key_name = Path(str(raw_key)).stem
                name = key_name
            canonical = _g5r_canonical_name(name)
            if canonical not in roster:
                continue
            hp = value.get("hitPoints")
            if not _g5_is_number(hp):
                errors.append("snapshot_hp_unavailable:%s:%s" % (source_name, roster[canonical]))
                continue
            target = str(raw_key)
            if not target.startswith("characters/"):
                target = "characters/%s.json" % _g5r_canonical_name(name)
            candidates.setdefault(canonical, {}).setdefault("observations", []).append(
                {"source": source_name, "target": target, "hit_points": float(hp)}
            )

    records = snapshot.get("records")
    projection = snapshot.get("mechanical_projection")
    collect("records", records)
    projection_characters = projection.get("characters") if isinstance(projection, dict) else None
    collect("mechanical_projection", projection_characters)

    hp_by_pc: Dict[str, Any] = {}
    for canonical, display_name in roster.items():
        observations = candidates.get(canonical, {}).get("observations", [])
        if not observations:
            errors.append("snapshot_pc_missing:%s" % display_name)
            continue
        hp_values = {row["hit_points"] for row in observations}
        targets = {row["target"] for row in observations}
        if len(hp_values) != 1:
            errors.append("snapshot_hp_sources_disagree:%s" % display_name)
            continue
        if len(targets) != 1:
            errors.append("snapshot_pc_target_ambiguous:%s" % display_name)
            continue
        hp_by_pc[canonical] = {"name": display_name, "target": next(iter(targets)),
                               "hit_points": next(iter(hp_values))}
    return {"hp_by_pc": hp_by_pc, "errors": sorted(set(errors))}


def _g5r_derive_batch_attribution(bundle: Dict[str, Any], require_resolver: bool = False) -> Dict[str, Any]:
    """Derive damaged-PC targets, retry requests, resolver outcome, and raw batch work."""
    errors: List[str] = []
    fixture = bundle.get("fixture") if isinstance(bundle.get("fixture"), dict) else {}
    manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    batch_steps = [row for row in fixture.get("steps", [])
                   if isinstance(row, dict) and row.get("unit_type") == "batch"]
    if len(batch_steps) != 1:
        errors.append("enemy_batch_step_missing_or_ambiguous")
        return {"status": "BLOCKED", "errors": errors}
    batch_step = batch_steps[0]
    unit = {"type": "batch", "id": batch_step.get("unit_id")}
    receipts = bundle.get("receipts") if isinstance(bundle.get("receipts"), list) else []
    matching_receipts = [row for row in receipts if isinstance(row, dict) and row.get("work_unit") == {
        "type": "batch", "id": batch_step.get("unit_id"), "round": batch_step.get("round")
    }]
    if len(matching_receipts) != 1:
        errors.append("enemy_batch_receipt_missing_or_ambiguous")
        receipt = {}
    else:
        receipt = matching_receipts[0]
    window = receipt.get("trace_window") if isinstance(receipt.get("trace_window"), dict) else {}
    start_ms, end_ms = window.get("start_epoch_ms"), window.get("end_epoch_ms")
    if (not _g5_is_number(start_ms) or not _g5_is_number(end_ms) or start_ms > end_ms):
        errors.append("enemy_batch_trace_window_unavailable")
        start_ms, end_ms = None, None
    else:
        start_ms, end_ms = float(start_ms), float(end_ms)

    events = bundle.get("trace_events") if isinstance(bundle.get("trace_events"), list) else []
    in_window: List[Dict[str, Any]] = []
    if start_ms is not None:
        for event in events:
            if not isinstance(event, dict):
                continue
            timestamp = event.get("recorded_at_ms")
            if _g5_is_number(timestamp) and start_ms <= float(timestamp) <= end_ms:
                in_window.append(event)
    in_window.sort(key=lambda event: float(event.get("recorded_at_ms", 0)))
    provider_events = [event for event in in_window if event.get("event_type") == "provider"]
    provider_calls = len(provider_events) if start_ms is not None else None
    narration_calls = 0
    validation_calls = 0
    for event in provider_events:
        site = event.get("site") or event.get("task")
        if not isinstance(site, str) or not site:
            errors.append("enemy_batch_provider_site_unavailable")
        elif site == "combat_main":
            narration_calls += 1
        elif site == "combat_validation":
            validation_calls += 1

    metrics = _g5_summarize_bundle(bundle)
    batch_rows = [row for row in metrics.get("batches", []) if row.get("id") == unit["id"]]
    if len(batch_rows) != 1:
        errors.append("enemy_batch_trace_projection_missing_or_ambiguous")
        projected_calls = projected_writes = None
    else:
        projected_calls = batch_rows[0].get("provider_calls")
        projected_writes = batch_rows[0].get("file_writes")
    if provider_calls is not None and _g5_is_number(projected_calls) and provider_calls != projected_calls:
        errors.append("enemy_batch_provider_call_attribution_mismatch")

    physical_write_events = [event for event in in_window
                             if event.get("event_type") == "file_operation" and
                             event.get("category") == "write" and
                             event.get("site") == "enemy_batch_write"]
    malformed_physical_writes = [event for event in physical_write_events
                                 if event.get("target_kind") not in ("history", "character", "encounter") or
                                 not isinstance(event.get("target_id"), str) or not event.get("target_id")]
    if malformed_physical_writes:
        errors.append("enemy_batch_physical_write_event_malformed")
    if physical_write_events:
        raw_writes = len(physical_write_events)
        write_accounting = "physical_enemy_batch_write_events"
    elif require_resolver:
        raw_writes = None
        write_accounting = None
        errors.append("enemy_batch_physical_write_events_missing")
    elif _g5_is_number(projected_writes) and projected_writes > 0:
        raw_writes = int(projected_writes)
        write_accounting = "legacy_trace_projection_file_writes"
    else:
        raw_writes = None
        write_accounting = None
        errors.append("enemy_batch_write_count_unavailable")

    resolver_events = [event for event in in_window if event.get("event_type") == "decision" and
                       event.get("decision_point") == "enemy_batch_resolution"]
    resolver_outcome = None
    resolver_reason = None
    resolver_batch_id = None
    if len(resolver_events) == 1:
        resolver_outcome = resolver_events[0].get("decision_outcome")
        resolver_reason = resolver_events[0].get("decision_reason")
        resolver_batch_id = resolver_events[0].get("batch_id")
        if resolver_outcome not in ("resolver_supported", "whole_batch_fallback", "resolver_disabled"):
            errors.append("enemy_batch_resolver_outcome_invalid")
        if require_resolver and (not isinstance(resolver_reason, str) or not resolver_reason):
            errors.append("enemy_batch_resolver_reason_unavailable")
        if require_resolver and (not isinstance(resolver_batch_id, str) or not resolver_batch_id):
            errors.append("enemy_batch_resolver_correlation_unavailable")
    elif require_resolver:
        errors.append("enemy_batch_resolver_decision_missing_or_ambiguous")
    if resolver_batch_id:
        for event in physical_write_events:
            if event.get("batch_id") != resolver_batch_id:
                errors.append("enemy_batch_physical_write_correlation_mismatch")

    snapshot_refs = artifacts.get("step_snapshots") if isinstance(artifacts.get("step_snapshots"), list) else []
    before_ref = "snapshots/step-%03d-before.json" % int(batch_step.get("index", 0))
    after_ref = "snapshots/step-%03d-after.json" % int(batch_step.get("index", 0))
    if before_ref not in snapshot_refs or after_ref not in snapshot_refs:
        errors.append("enemy_batch_before_after_snapshot_reference_missing")
        before_snapshot = after_snapshot = None
    else:
        from scripts import capture_evidence
        run_dir = Path(str(bundle.get("run_dir", "")))
        before_snapshot, before_error = capture_evidence.load_bundle_json(run_dir, before_ref)
        after_snapshot, after_error = capture_evidence.load_bundle_json(run_dir, after_ref)
        if before_error or after_error:
            errors.append("enemy_batch_snapshot_load_failed:%s:%s" % (
                before_error or "ok", after_error or "ok"))
    roster = party.get("roster")
    before_hp = _g5r_snapshot_pc_hp(before_snapshot, roster)
    after_hp = _g5r_snapshot_pc_hp(after_snapshot, roster)
    errors.extend("before_%s" % reason for reason in before_hp["errors"])
    errors.extend("after_%s" % reason for reason in after_hp["errors"])
    changed_targets: List[Dict[str, str]] = []
    if not before_hp["errors"] and not after_hp["errors"]:
        for canonical, before_row in before_hp["hp_by_pc"].items():
            after_row = after_hp["hp_by_pc"].get(canonical)
            if after_row is None:
                errors.append("after_snapshot_pc_missing:%s" % before_row["name"])
                continue
            if before_row["target"] != after_row["target"]:
                errors.append("snapshot_pc_target_changed:%s" % before_row["name"])
                continue
            if before_row["hit_points"] != after_row["hit_points"]:
                changed_targets.append({"name": before_row["name"], "target": before_row["target"]})

    retry_count: Optional[int] = None
    retry_methods: List[str] = []
    pending_validation: Optional[Dict[str, Any]] = None
    retry_count_value = 0
    retry_evidence_usable = True
    for event in in_window:
        event_type = event.get("event_type")
        if event_type == "provider":
            site = event.get("site") or event.get("task")
            if site == "combat_validation":
                if pending_validation is not None:
                    errors.append("validator_retry_sequence_ambiguous")
                    retry_evidence_usable = False
                pending_validation = {"result": None, "event": event}
            elif site == "combat_main" and pending_validation is not None:
                explicit_cause = event.get("retry_cause") == "validator_rejection"
                validation_result = pending_validation.get("result")
                if explicit_cause and validation_result is True:
                    errors.append("validator_retry_cause_conflicts_with_accepted_validation")
                    retry_evidence_usable = False
                elif explicit_cause or validation_result is False:
                    retry_count_value += 1
                    retry_methods.append("explicit_retry_cause" if explicit_cause else
                                         "failed_validation_result_followed_by_combat_main")
                elif validation_result is None:
                    # Earlier trace versions omitted the result observation; a subsequent
                    # combat_main request in the same batch is the observable retry edge.
                    retry_count_value += 1
                    retry_methods.append("combat_main_after_validation_without_result_observation")
                pending_validation = None
            elif site == "combat_main" and event.get("retry_cause") == "validator_rejection":
                errors.append("validator_retry_missing_preceding_validation")
                retry_evidence_usable = False
        elif event_type == "combat_observation" and event.get("observation") == "combat_validation_result":
            if pending_validation is None:
                errors.append("validation_result_missing_preceding_validation")
                retry_evidence_usable = False
                continue
            accepted = event.get("validation_accepted")
            if not isinstance(accepted, bool):
                errors.append("validation_result_outcome_unavailable")
                retry_evidence_usable = False
            else:
                pending_validation["result"] = accepted
    if pending_validation is not None and pending_validation.get("result") is None:
        errors.append("validator_outcome_unattributed_at_batch_end")
        retry_evidence_usable = False
    if retry_evidence_usable:
        retry_count = retry_count_value
    if not retry_methods and retry_count == 0:
        retry_methods.append("ordered_batch_trace_no_validator_rejection_retry")

    work_only_ms = receipt.get("work_only_ms")
    if not _g5_is_number(work_only_ms) or work_only_ms < 0:
        errors.append("enemy_batch_work_only_timing_unavailable")
        work_only_ms = None
    return {
        "status": "BLOCKED" if errors else "OBSERVED",
        "batch_step": batch_step.get("index"), "work_unit_id": unit["id"],
        "trace_window": {"start_epoch_ms": start_ms, "end_epoch_ms": end_ms},
        "work_only_ms": work_only_ms,
        "provider_calls": provider_calls, "narration_provider_calls": narration_calls,
        "validation_provider_calls": validation_calls,
        "raw_file_writes": raw_writes, "write_accounting": write_accounting,
        "resolver_outcome": resolver_outcome, "resolver_reason": resolver_reason,
        "resolver_supported": resolver_outcome == "resolver_supported" if resolver_outcome else None,
        "changed_pc_targets": sorted(changed_targets, key=lambda row: row["target"]),
        "changed_pc_target_count": len(changed_targets) if not before_hp["errors"] and not after_hp["errors"] else None,
        "validator_rejection_retry_count": retry_count,
        "retry_derivation_methods": sorted(set(retry_methods)),
        "errors": sorted(set(errors)),
    }


def _g5r_median(values: Iterable[Any]) -> Optional[float]:
    rows = list(values)
    if not rows or not all(_g5_is_number(value) for value in rows):
        return None
    return round(float(statistics.median(float(value) for value in rows)), 3)


def _g5r_round_one(metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((row for row in metrics.get("rounds", [])
                 if row.get("round") == 1 and row.get("action_count") == 8 and
                 row.get("batch_count") == 1), None)


def _g5r_phase_observations(metrics: Dict[str, Any], attribution: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for phase in G5_PHASES:
        source = metrics.get("phase_counts", {}).get(phase, {})
        providers, writes = source.get("provider_calls"), source.get("file_writes")
        if phase == "ENEMY_PHASE" and _g5_is_number(attribution.get("raw_file_writes")):
            writes = attribution["raw_file_writes"]
        if metrics.get("errors"):
            providers = None
            writes = None
        result[phase] = {"provider_calls": providers, "file_writes": writes}
    return result


def evaluate_g5r_comparison(before_dirs: Iterable[Any],
                            after_runs_by_party: Dict[int, Iterable[Any]]) -> Dict[str, Any]:
    """Evaluate three G5R runs per party against the fixed matched G5 reference."""
    from scripts import capture_evidence

    before_inputs = (list(before_dirs) if not isinstance(before_dirs, (str, bytes, Path))
                     else [before_dirs])
    blocking_reasons: List[str] = []
    if len(before_inputs) != 2:
        blocking_reasons.append("before_role_requires_exactly_two_g5_bundles")
    baseline_bundles = [
        _g5_load_bundle(path, allow_legacy_saved_receipt_projection=True)
        for path in before_inputs
    ]
    baseline_by_party: Dict[int, List[Dict[str, Any]]] = {1: [], 4: []}
    seen_paths: Dict[str, int] = {}
    seen_runs: Dict[str, int] = {}
    for bundle in baseline_bundles:
        path = bundle.get("run_dir", "")
        seen_paths[path] = seen_paths.get(path, 0) + 1
        run_id = bundle.get("run_id")
        if isinstance(run_id, str):
            seen_runs[run_id] = seen_runs.get(run_id, 0) + 1
        party_size = bundle.get("party_size")
        if party_size in baseline_by_party:
            baseline_by_party[party_size].append(bundle)
        for error in bundle.get("errors", []):
            blocking_reasons.append("g5_reference:%s:%s" % (run_id or "unknown_run", error))

    raw_after: Dict[int, List[Any]] = {1: [], 4: []}
    if not isinstance(after_runs_by_party, dict):
        blocking_reasons.append("after_runs_by_party_unavailable")
    else:
        for party_size in (1, 4):
            values = after_runs_by_party.get(party_size, after_runs_by_party.get(str(party_size), []))
            if isinstance(values, (str, bytes, Path)):
                values = [values]
            try:
                raw_after[party_size] = list(values)
            except TypeError:
                blocking_reasons.append("p%d_after_run_list_invalid" % party_size)
    g5r_root = capture_evidence.PROJECT_TMP / "router-rollout" / "g5r"
    after_by_party: Dict[int, List[Dict[str, Any]]] = {1: [], 4: []}
    for party_size in (1, 4):
        if len(raw_after[party_size]) != 3:
            blocking_reasons.append("p%d_after_role_requires_exactly_three_bundles" % party_size)
        for path in raw_after[party_size]:
            bundle = _g5_load_bundle(
                path, run_root=g5r_root, expected_gate="g5r",
                allow_legacy_saved_receipt_projection=True,
            )
            after_by_party[party_size].append(bundle)
            run_id = bundle.get("run_id")
            run_path = bundle.get("run_dir", "")
            seen_paths[run_path] = seen_paths.get(run_path, 0) + 1
            if isinstance(run_id, str):
                seen_runs[run_id] = seen_runs.get(run_id, 0) + 1
            if bundle.get("party_size") not in (None, party_size):
                blocking_reasons.append("p%d_after_run_party_size_mismatch:%s" %
                                        (party_size, run_id or "unknown_run"))
            for error in bundle.get("errors", []):
                blocking_reasons.append("p%d_after_run:%s:%s" %
                                        (party_size, run_id or "unknown_run", error))
    if any(count > 1 for count in seen_paths.values()):
        blocking_reasons.append("duplicate_bundle_path_or_role")
    if any(count > 1 for count in seen_runs.values()):
        blocking_reasons.append("duplicate_run_id")

    targets: List[Dict[str, Any]] = []
    party_comparisons: List[Dict[str, Any]] = []
    deviations: List[Dict[str, Any]] = []
    for party_size in (1, 4):
        baseline_rows = baseline_by_party[party_size]
        after_rows = after_by_party[party_size]
        if len(baseline_rows) != 1:
            blocking_reasons.append("p%d_g5_reference_missing_or_duplicate" % party_size)
            baseline = baseline_rows[0] if baseline_rows else {}
        else:
            baseline = baseline_rows[0]
        before_metrics = _g5_summarize_bundle(baseline) if baseline else {}
        before_attr = _g5r_derive_batch_attribution(baseline) if baseline else {
            "status": "BLOCKED", "errors": ["g5_reference_unavailable"]}
        for error in before_metrics.get("errors", []):
            blocking_reasons.append("p%d_g5_reference:%s" % (party_size, error))
        for error in before_attr.get("errors", []):
            blocking_reasons.append("p%d_g5_reference_attribution:%s" % (party_size, error))

        run_rows: List[Dict[str, Any]] = []
        metrics_rows: List[Dict[str, Any]] = []
        attr_rows: List[Dict[str, Any]] = []
        identity_mismatches: Dict[str, List[str]] = {}
        for bundle in after_rows:
            run_id = bundle.get("run_id") or "unknown_run"
            metric = _g5_summarize_bundle(bundle)
            attr = _g5r_derive_batch_attribution(bundle, require_resolver=True)
            metrics_rows.append(metric)
            attr_rows.append(attr)
            mismatches = _g5_identity_mismatches(baseline, bundle) if baseline else ["g5_reference_missing"]
            identity_mismatches[run_id] = mismatches
            for mismatch in mismatches:
                blocking_reasons.append("p%d_after_identity:%s:%s" % (party_size, run_id, mismatch))
            for error in metric.get("errors", []):
                blocking_reasons.append("p%d_after_metrics:%s:%s" % (party_size, run_id, error))
            for error in attr.get("errors", []):
                blocking_reasons.append("p%d_after_attribution:%s:%s" % (party_size, run_id, error))
            if attr.get("resolver_outcome") and attr.get("resolver_outcome") != "resolver_supported":
                deviations.append({"party_size": party_size, "run_id": run_id,
                                   "work_unit_id": attr.get("work_unit_id"),
                                   "outcome": attr.get("resolver_outcome"),
                                   "reason": attr.get("resolver_reason") or "unsupported_batch"})
            run_rows.append({"run_id": run_id, "run_dir": bundle.get("run_dir"),
                             "identity_mismatches": mismatches,
                             "batch": attr,
                             "pc_action_llm_p50_work_only_ms": _g5_run_action_p50(metric, "llm"),
                             "complete_round_one_work_only_ms": (
                                 _g5r_round_one(metric) or {}).get("work_only_ms"),
                             "phase_counts": _g5r_phase_observations(metric, attr)})

        run_count_ok = len(after_rows) == 3
        if run_count_ok and len({row.get("run_id") for row in after_rows}) != 3:
            blocking_reasons.append("p%d_after_run_ids_not_distinct" % party_size)
        all_after_attrs_valid = bool(attr_rows) and all(
            attr.get("status") == "OBSERVED" and
            _g5_is_number(attr.get("validator_rejection_retry_count")) and
            _g5_is_number(attr.get("changed_pc_target_count")) for attr in attr_rows)
        before_attrs_valid = (before_attr.get("status") != "BLOCKED" and
                              _g5_is_number(before_attr.get("validator_rejection_retry_count")) and
                              _g5_is_number(before_attr.get("changed_pc_target_count")))

        batch_latencies = [row.get("work_only_ms") for row in attr_rows]
        median_batch_latency = _g5r_median(batch_latencies) if run_count_ok else None
        latency_target = _g5_check(
            "enemy_batch_median_work_only_ms", median_batch_latency, "<=",
            G5R_MEDIAN_BATCH_WORK_ONLY_MS,
            "three_run_enemy_batch_timing_unavailable" if median_batch_latency is None else None,
        )
        latency_target.update({"party_size": party_size,
                               "run_values_ms": batch_latencies,
                               "run_count": len(batch_latencies), "timing_source": "work_only_ms"})
        targets.append(latency_target)

        for field, target_name, operator, threshold in (
                ("narration_provider_calls", "enemy_batch_narration_provider_calls", "==", 1),
                ("validation_provider_calls", "enemy_batch_validation_provider_calls", "==", 0),
                ("provider_calls", "enemy_batch_provider_calls", "==", 1),
                ("raw_file_writes", "enemy_batch_raw_file_writes", "<=", G5R_BATCH_WRITE_LIMIT)):
            for run, attr in zip(run_rows, attr_rows):
                target = _g5_check(target_name, attr.get(field), operator, threshold,
                                   "batch_observation_unavailable" if attr.get(field) is None else None)
                target.update({"party_size": party_size, "run_id": run.get("run_id"),
                               "work_unit_id": attr.get("work_unit_id"),
                               "raw_observation": attr.get(field),
                               "write_accounting": attr.get("write_accounting") if field == "raw_file_writes" else None})
                targets.append(target)

        for run, attr in zip(run_rows, attr_rows):
            if attr.get("resolver_outcome") is None:
                target = _g5_check("enemy_batch_resolver_supported", None, "==", 1,
                                   "resolver_outcome_unavailable")
            else:
                target = _g5_check("enemy_batch_resolver_supported",
                                   1 if attr.get("resolver_supported") else 0, "==", 1)
            target.update({"party_size": party_size, "run_id": run.get("run_id"),
                           "work_unit_id": attr.get("work_unit_id"),
                           "resolver_outcome": attr.get("resolver_outcome"),
                           "deviation_reason": attr.get("resolver_reason")})
            targets.append(target)

        before_phase = _g5r_phase_observations(before_metrics, before_attr)
        after_phases = [_g5r_phase_observations(metric, attr)
                        for metric, attr in zip(metrics_rows, attr_rows)]
        median_phases: Dict[str, Dict[str, Any]] = {}
        phase_deltas: List[Dict[str, Any]] = []
        retry_before = before_attr.get("validator_rejection_retry_count")
        changed_before = before_attr.get("changed_pc_target_count")
        retry_after_values = [attr.get("validator_rejection_retry_count") for attr in attr_rows]
        changed_after_values = [attr.get("changed_pc_target_count") for attr in attr_rows]
        retry_after = _g5r_median(retry_after_values) if run_count_ok else None
        changed_after = _g5r_median(changed_after_values) if run_count_ok else None
        retry_delta = (retry_after - retry_before
                       if before_attrs_valid and all_after_attrs_valid and retry_after is not None else None)
        changed_delta = (changed_after - changed_before
                         if before_attrs_valid and all_after_attrs_valid and changed_after is not None else None)
        for phase in G5_PHASES:
            median_phases[phase] = {}
            for field in ("provider_calls", "file_writes"):
                after_values = [row.get(phase, {}).get(field) for row in after_phases]
                observed_after = _g5r_median(after_values) if run_count_ok else None
                observed_before = before_phase.get(phase, {}).get(field)
                raw_delta = (observed_after - observed_before
                             if _g5_is_number(observed_after) and _g5_is_number(observed_before) else None)
                if field == "provider_calls" and phase == "ENEMY_PHASE":
                    adjustment = retry_delta
                elif field == "file_writes" and phase == "ENEMY_PHASE":
                    adjustment = changed_delta
                else:
                    adjustment = 0 if raw_delta is not None else None
                normalized_delta = raw_delta - adjustment if raw_delta is not None and adjustment is not None else None
                median_phases[phase][field] = observed_after
                target_name = "phase_%s_%s_no_increase" % (
                    phase.lower(), "provider_calls" if field == "provider_calls" else "file_writes")
                reason = None
                if raw_delta is None:
                    reason = "phase_comparison_metric_unavailable"
                elif adjustment is None:
                    reason = "normalization_attribution_unavailable"
                target = _g5_check(target_name, normalized_delta, "<=", 0, reason)
                target.update({"party_size": party_size, "phase": phase, "metric": field,
                               "before": observed_before, "after_median": observed_after,
                               "raw_delta": raw_delta, "normalization_adjustment": adjustment,
                               "normalized_delta": normalized_delta})
                targets.append(target)
                phase_deltas.append({"phase": phase, "metric": field,
                                     "before": observed_before, "after_median": observed_after,
                                     "raw_delta": raw_delta, "normalization_adjustment": adjustment,
                                     "normalized_delta": normalized_delta})

        before_total_calls = sum(before_phase.get(phase, {}).get("provider_calls", 0)
                                 for phase in G5_PHASES) if all(
                                     _g5_is_number(before_phase.get(phase, {}).get("provider_calls"))
                                     for phase in G5_PHASES) else None
        after_total_calls = sum(median_phases.get(phase, {}).get("provider_calls", 0)
                                for phase in G5_PHASES) if all(
                                    _g5_is_number(median_phases.get(phase, {}).get("provider_calls"))
                                    for phase in G5_PHASES) else None
        before_total_writes = sum(before_phase.get(phase, {}).get("file_writes", 0)
                                  for phase in G5_PHASES) if all(
                                      _g5_is_number(before_phase.get(phase, {}).get("file_writes"))
                                      for phase in G5_PHASES) else None
        after_total_writes = sum(median_phases.get(phase, {}).get("file_writes", 0)
                                 for phase in G5_PHASES) if all(
                                     _g5_is_number(median_phases.get(phase, {}).get("file_writes"))
                                     for phase in G5_PHASES) else None
        raw_call_delta = (after_total_calls - before_total_calls
                          if after_total_calls is not None and before_total_calls is not None else None)
        raw_write_delta = (after_total_writes - before_total_writes
                           if after_total_writes is not None and before_total_writes is not None else None)
        normalized_call_delta = (raw_call_delta - retry_delta
                                 if raw_call_delta is not None and retry_delta is not None else None)
        normalized_write_delta = (raw_write_delta - changed_delta
                                  if raw_write_delta is not None and changed_delta is not None else None)
        for target_name, raw_delta, normalized_delta in (
                ("p1_no_provider_call_regression", raw_call_delta, normalized_call_delta),
                ("p1_no_file_write_regression", raw_write_delta, normalized_write_delta)):
            target = _g5_check(target_name, normalized_delta, "<=", 0,
                               "normalization_attribution_unavailable" if normalized_delta is None else None)
            target.update({"party_size": party_size, "before_total": before_total_calls if "provider" in target_name else before_total_writes,
                           "after_median_total": after_total_calls if "provider" in target_name else after_total_writes,
                           "raw_delta": raw_delta,
                           "normalization_adjustment": retry_delta if "provider" in target_name else changed_delta,
                           "normalized_delta": normalized_delta})
            if party_size == 1:
                targets.append(target)

        if party_size == 1:
            before_action_p50 = _g5_complete_action_p50(before_metrics)
            after_action_p50_values = [_g5_complete_action_p50(metric) for metric in metrics_rows]
            after_action_p50 = _g5r_median(after_action_p50_values) if run_count_ok else None
            latency = _g5_comparison_check(
                "p1_no_latency_regression", after_action_p50 / 1000.0 if after_action_p50 is not None else None,
                before_action_p50 / 1000.0 if before_action_p50 is not None else None,
                "p1_action_p50_unavailable" if before_action_p50 is None or after_action_p50 is None else None,
                before_factor=G5_P1_LATENCY_REGRESSION_FACTOR,
            )
            latency.update({"party_size": party_size, "before_p50_ms": before_action_p50,
                            "after_run_p50_ms": after_action_p50_values,
                            "after_median_p50_ms": after_action_p50,
                            "timing_source": "work_only_ms"})
            targets.append(latency)

        if party_size == 4:
            before_round = _g5r_round_one(before_metrics)
            after_round_values = [(_g5r_round_one(metric) or {}).get("work_only_ms")
                                  for metric in metrics_rows]
            after_round_median = _g5r_median(after_round_values) if run_count_ok else None
            if (before_round is None or not _g5_is_number(before_round.get("work_only_ms")) or
                    before_round["work_only_ms"] <= 0 or after_round_median is None):
                round_target = _g5_check("p4_round_latency_improvement", None, ">=", 0.30,
                                         "complete_round_work_only_timing_unavailable")
                improvement = None
            else:
                improvement = (before_round["work_only_ms"] - after_round_median) / before_round["work_only_ms"]
                round_target = _g5_check("p4_round_latency_improvement", round(improvement, 6), ">=", 0.30)
            round_target.update({"party_size": party_size,
                                 "before_round_work_only_ms": before_round.get("work_only_ms") if before_round else None,
                                 "after_run_work_only_ms": after_round_values,
                                 "after_median_work_only_ms": after_round_median,
                                 "complete_round": "8 scripted PC steps + 1 enemy batch",
                                 "timing_source": "work_only_ms"})
            targets.append(round_target)

        party_deviations = [row for row in deviations if row.get("party_size") == party_size]
        party_blocked = (len(baseline_rows) != 1 or len(after_rows) != 3 or
                         bool(baseline.get("errors")) or bool(before_metrics.get("errors")) or
                         bool(before_attr.get("errors")))
        for bundle, metric, attr, run in zip(after_rows, metrics_rows, attr_rows, run_rows):
            if (bundle.get("errors") or metric.get("errors") or attr.get("errors") or
                    run.get("identity_mismatches")):
                party_blocked = True
        if len({row.get("run_id") for row in after_rows}) != len(after_rows):
            party_blocked = True
        comparison = {
            "party_size": party_size,
            "status": "BLOCKED" if party_blocked else "PENDING",
            "g5_reference_run_id": baseline.get("run_id"),
            "g5_reference_metrics": before_metrics,
            "g5_reference_batch_attribution": before_attr,
            "after_runs": run_rows,
            "medians": {
                "enemy_batch_work_only_ms": median_batch_latency,
                "validator_rejection_retry_count": retry_after,
                "changed_pc_target_count": changed_after,
                "phase_counts": median_phases,
                "pc_action_llm_p50_work_only_ms": (
                    _g5r_median([row.get("pc_action_llm_p50_work_only_ms") for row in run_rows])
                    if run_count_ok else None),
                "complete_round_one_work_only_ms": (
                    _g5r_median([row.get("complete_round_one_work_only_ms") for row in run_rows])
                    if run_count_ok else None),
            },
            "normalization": {
                "raw_provider_call_delta": raw_call_delta,
                "validator_rejection_retry_delta": retry_delta,
                "normalized_provider_call_delta": normalized_call_delta,
                "raw_file_write_delta": raw_write_delta,
                "changed_pc_target_delta": changed_delta,
                "normalized_file_write_delta": normalized_write_delta,
                "phase_deltas": phase_deltas,
            },
            "deviations": party_deviations,
            "identity_mismatches": identity_mismatches,
        }
        party_comparisons.append(comparison)

    failed_targets = [row for row in targets if row.get("status") == "FAIL"]
    blocked_targets = [row for row in targets if row.get("status") == "BLOCKED"]
    if blocking_reasons or blocked_targets:
        automated_status = "BLOCKED"
    elif failed_targets:
        automated_status = "FAIL"
    else:
        automated_status = "READY_FOR_PRIMARY_REVIEW"
    for comparison in party_comparisons:
        if comparison.get("status") == "BLOCKED":
            continue
        party_targets = [row for row in targets if row.get("party_size") == comparison["party_size"]]
        if any(row.get("status") == "BLOCKED" for row in party_targets):
            comparison["status"] = "BLOCKED"
        elif any(row.get("status") == "FAIL" for row in party_targets):
            comparison["status"] = "FAIL"
        else:
            comparison["status"] = "READY_FOR_PRIMARY_REVIEW"
    return {
        "automated_status": automated_status, "primary_verdict": "PENDING", "gate": "g5r",
        "comparison_method": "three_run_g5r_outcome_normalized",
        "fixed_targets": {"enemy_batch_median_work_only_ms": {
            "operator": "<=", "threshold": G5R_MEDIAN_BATCH_WORK_ONLY_MS},
            "enemy_batch_raw_file_writes": {"operator": "<=", "threshold": G5R_BATCH_WRITE_LIMIT},
            "enemy_batch_provider_calls": {"operator": "==", "threshold": 1},
            "enemy_batch_validation_provider_calls": {"operator": "==", "threshold": 0}},
        "party_comparisons": party_comparisons, "targets": targets,
        "unsupported_batch_deviations": deviations,
        "target_misses": [{"target": row.get("target"), "party_size": row.get("party_size"),
                           "run_id": row.get("run_id"), "observed": row.get("observed"),
                           "threshold": row.get("threshold"), "raw_delta": row.get("raw_delta"),
                           "normalized_delta": row.get("normalized_delta")}
                          for row in failed_targets],
        "blocking_reasons": sorted(set(blocking_reasons + [
            "required_target_metric_unavailable:%s:p%s" % (row.get("target"), row.get("party_size"))
            for row in blocked_targets])),
    }


def _g5_run_action_p50(metrics: Dict[str, Any], classification: str) -> Optional[float]:
    rows = [row for row in metrics.get("actions", []) if row.get("classification") == classification]
    values = [row.get("work_only_ms") for row in rows]
    if not values or not all(_g5_is_number(value) for value in values):
        return None
    return _g5_summary(values)


def render_g5r_comparison(report: Dict[str, Any]) -> str:
    """Render G5R targets while retaining raw and normalized comparison values."""
    lines = ["Combat G5R comparison [%s]" % report.get("automated_status", "BLOCKED"),
             "target | party | run | observed | raw delta | normalized delta | rule | status"]
    for row in report.get("targets", []):
        lines.append("%s | P%s | %s | %s | %s | %s | %s %s | %s" % (
            row.get("target"), row.get("party_size", "-"), row.get("run_id", "-"),
            _value(row.get("observed")), _value(row.get("raw_delta")),
            _value(row.get("normalized_delta")), row.get("operator"),
            _value(row.get("threshold")), row.get("status")))
    for deviation in report.get("unsupported_batch_deviations", []):
        lines.append("P%s unsupported batch %s: %s (%s)" % (
            deviation.get("party_size"), deviation.get("work_unit_id"),
            deviation.get("outcome"), deviation.get("reason")))
    if report.get("blocking_reasons"):
        lines.append("Blocking reasons: %s" % ", ".join(report["blocking_reasons"]))
    return "\n".join(lines)


def _g5t_load_bundle(raw_run_dir: Any, run_root: Optional[Path] = None,
                     expected_mode: str = "primary") -> Dict[str, Any]:
    """Load one isolated G5T evidence bundle without trusting saved verdicts."""
    from scripts import capture_evidence

    errors: List[str] = []
    try:
        run_dir = Path(str(raw_run_dir))
        if not run_dir.is_absolute():
            run_dir = capture_evidence.PROJECT_ROOT / run_dir
        allowed_root = (Path(run_root) if run_root is not None else
                        capture_evidence.PROJECT_TMP / "router-rollout" / "g5t")
        if not allowed_root.is_absolute():
            allowed_root = capture_evidence.PROJECT_ROOT / allowed_root
        if (not capture_evidence._inside(run_dir, allowed_root) or
                run_dir.resolve() == allowed_root.resolve() or
                capture_evidence._has_symlink_component(run_dir, capture_evidence.PROJECT_TMP)):
            return {"run_dir": str(run_dir), "errors": ["unsafe_g5t_run_directory"]}
        if not run_dir.is_dir():
            return {"run_dir": str(run_dir), "errors": ["missing_g5t_run_directory"]}
    except (OSError, RuntimeError, TypeError, ValueError):
        return {"run_dir": str(raw_run_dir), "errors": ["invalid_g5t_run_directory"]}

    manifest, manifest_error = capture_evidence.load_bundle_json(run_dir, "manifest.json")
    if manifest_error or not isinstance(manifest, dict):
        return {"run_dir": str(run_dir), "errors": ["manifest:%s" % (manifest_error or "invalid")]}

    if manifest.get("gate") != "g5t":
        errors.append("wrong_gate:%s" % (manifest.get("gate") or "missing"))
    party = manifest.get("party") if isinstance(manifest.get("party"), dict) else {}
    party_size = party.get("size")
    if party_size not in G5T_PARTY_SIZES:
        errors.append("unsupported_or_missing_party_size")
        expected_scenario = None
    else:
        expected_scenario = "g5t-commander-p%d" % party_size
    scenario = manifest.get("scenario") if isinstance(manifest.get("scenario"), dict) else {}
    scenario_id = scenario.get("id")
    if scenario_id != expected_scenario:
        errors.append("wrong_or_missing_commander_scenario:%s" % (scenario_id or "missing"))

    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or run_id != run_dir.name:
        errors.append("run_id_missing_or_mismatched")
    if (manifest.get("evidence_kind") != "live-candidate" or
            manifest.get("live_eligible") is not True or
            (manifest.get("transport") or {}).get("client_source") != "socketio.Client"):
        errors.append("synthetic_or_ineligible_evidence")

    g5t = manifest.get("g5t") if isinstance(manifest.get("g5t"), dict) else {}
    capture_mode = g5t.get("capture_mode", g5t.get("mode", "primary"))
    if g5t.get("prefetch_enabled") is True:
        capture_mode = "prefetch"
    if capture_mode != expected_mode:
        errors.append("g5t_capture_mode_mismatch:%s" % (capture_mode or "missing"))

    fixture = g5t.get("fixture") if isinstance(g5t.get("fixture"), dict) else {}
    fixture_id = fixture.get("id", fixture.get("fixture_id"))
    if fixture_id is not None and fixture_id != expected_scenario:
        errors.append("g5t_fixture_identity_mismatch")
    raw_steps = fixture.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = fixture.get("batches")
    batch_steps: List[Dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for index, row in enumerate(raw_steps, 1):
            if not isinstance(row, dict):
                errors.append("g5t_fixture_step_malformed:%d" % index)
                continue
            unit_type = row.get("unit_type", row.get("type", "batch"))
            if unit_type != "batch":
                continue
            unit_id = row.get("unit_id", row.get("id"))
            round_number = row.get("round")
            if (not isinstance(unit_id, str) or not unit_id or
                    not isinstance(round_number, int) or isinstance(round_number, bool) or
                    round_number < 1):
                errors.append("g5t_fixture_batch_identity_invalid:%d" % index)
                continue
            batch_steps.append({
                "unit_id": unit_id,
                "round": round_number,
                "batch_id": row.get("trace_batch_id", row.get("batch_id", "enemy:r%d" % round_number)),
            })
    if not batch_steps:
        errors.append("g5t_commander_batch_steps_missing")
    step_ids = [row["unit_id"] for row in batch_steps]
    if len(step_ids) != len(set(step_ids)):
        errors.append("g5t_commander_batch_steps_duplicate")

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_hashes = source.get("relevant_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        source_digest = None
        errors.append("source_digest_missing")
    else:
        source_digest = hashlib.sha256(
            json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identity = g5t.get("identity") if isinstance(g5t.get("identity"), dict) else {}
        if identity.get("source_digest") not in (None, source_digest):
            errors.append("g5t_source_digest_mismatch")

    configuration = manifest.get("configuration") if isinstance(manifest.get("configuration"), dict) else {}
    actual = configuration.get("actual_runtime") if isinstance(configuration.get("actual_runtime"), dict) else {}
    transport = manifest.get("transport") if isinstance(manifest.get("transport"), dict) else {}
    provider = actual.get("provider") or transport.get("declared_provider")
    model = actual.get("response_model") or transport.get("resolved_response_model")
    if not isinstance(provider, str) or not provider:
        errors.append("actual_provider_identity_missing")
    if not isinstance(model, str) or not model:
        errors.append("actual_model_identity_missing")

    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    artifact_hashes = manifest.get("artifact_sha256")
    artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
    loaded_artifacts: Dict[str, Any] = {}
    artifact_paths: Dict[str, str] = {}
    for name in ("trace", "checks", "report", "before_snapshot", "after_snapshot"):
        reference = artifacts.get(name)
        candidate, reference_error = capture_evidence._bundle_file(run_dir, reference)
        if reference_error or candidate is None:
            errors.append("artifact_%s:%s" % (name, reference_error or "missing"))
            continue
        artifact_paths[name] = str(reference)
        raw, read_error = capture_evidence._safe_read_bytes(candidate, run_dir)
        if read_error or raw is None:
            errors.append("artifact_%s:%s" % (name, read_error or "unreadable"))
            continue
        if name != "checks":
            expected_hash = artifact_hashes.get(reference)
            if not isinstance(expected_hash, str) or hashlib.sha256(raw).hexdigest() != expected_hash:
                errors.append("artifact_%s:hash_missing_or_mismatch" % name)
        if name == "trace":
            trace_start = manifest.get("trace_start_offset")
            trace_span = manifest.get("trace_span")
            trace_copy = artifacts.get("trace_copy")
            if (not isinstance(trace_start, dict) or trace_start.get("status") != "captured" or
                    not isinstance(trace_start.get("source_byte_offset"), int) or
                    isinstance(trace_start.get("source_byte_offset"), bool)):
                errors.append("g5t_trace_start_offset_unavailable")
                offset = 0
            else:
                offset = trace_start["source_byte_offset"]
            if (not isinstance(trace_span, dict) or trace_span.get("status") != "copied" or
                    trace_span.get("offset_before_bytes") != offset or
                    trace_span.get("span_bytes") != len(raw)):
                errors.append("g5t_trace_span_missing_or_inconsistent")
            if (not isinstance(trace_copy, dict) or trace_copy.get("status") != "copied" or
                    trace_copy.get("source_records") != trace_copy.get("destination_records")):
                errors.append("g5t_trace_copy_missing_or_inconsistent")
            if not raw:
                errors.append("g5t_trace_empty")
            try:
                records = []
                for line_number, line in enumerate(raw.decode("ascii").splitlines(), 1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not _valid_record(value):
                        errors.append("g5t_trace_invalid_record:%d" % line_number)
                        continue
                    if value.get("run_id") != run_id:
                        errors.append("g5t_trace_run_id_mismatch:%d" % line_number)
                    records.append(value)
                loaded_artifacts["trace_records"] = records
                positioned, position_errors = capture_evidence.parse_trace_positions(candidate, offset)
                if position_errors:
                    errors.extend("g5t_%s" % reason for reason in position_errors)
                loaded_artifacts["trace_events"] = positioned
            except (UnicodeError, ValueError):
                errors.append("g5t_trace_malformed")
        else:
            try:
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    errors.append("artifact_%s:not_object" % name)
                else:
                    loaded_artifacts[name] = value
            except (UnicodeError, ValueError):
                errors.append("artifact_%s:malformed_json" % name)

    report_doc = loaded_artifacts.get("report")
    trace_records = loaded_artifacts.get("trace_records", [])
    report_input = report_doc.get("input") if isinstance(report_doc, dict) else None
    if (not isinstance(report_doc, dict) or report_doc.get("status") != "ok" or
            not isinstance(report_input, dict) or
            report_input.get("total_records") != len(trace_records) or
            report_input.get("malformed_count") != 0):
        errors.append("g5t_saved_trace_report_missing_or_degraded")
    elif report_doc.get("combat_observations") != [
            row for row in trace_records if row.get("event_type") == "combat_observation"]:
        errors.append("g5t_saved_trace_report_observation_mismatch")

    receipts = g5t.get("receipts")
    if not isinstance(receipts, list):
        receipts = manifest.get("receipts")
    if not isinstance(receipts, list):
        receipts = []
        errors.append("g5t_batch_receipts_missing")
    # A valid tactical outcome can end combat before later scripted batches.
    # The driver emits explicit skipped receipts for that branch; those planned
    # but unexecuted batches are not missing timing observations.
    skipped_batch_ids = {
        row.get("work_unit", {}).get("id")
        for row in receipts if isinstance(row, dict) and row.get("status") == "skipped" and
        row.get("skip_reason") == "combat_ended" and isinstance(row.get("work_unit"), dict) and
        row.get("work_unit", {}).get("type") == "batch"
    }
    if skipped_batch_ids:
        batch_steps = [row for row in batch_steps if row.get("unit_id") not in skipped_batch_ids]

    return {
        "run_dir": str(run_dir), "run_id": run_id if isinstance(run_id, str) else None,
        "party_size": party_size, "scenario_id": scenario_id, "capture_mode": capture_mode,
        "provider": provider, "model": model, "source_digest": source_digest,
        "manifest": manifest, "fixture": fixture, "batch_steps": batch_steps,
        "receipts": receipts, "trace_events": loaded_artifacts.get("trace_events", []),
        "trace_records": trace_records, "checks": loaded_artifacts.get("checks"),
        "before_snapshot": loaded_artifacts.get("before_snapshot"),
        "after_snapshot": loaded_artifacts.get("after_snapshot"),
        "artifact_paths": artifact_paths, "errors": sorted(set(errors)),
    }


def _g5t_evidence_refs(run_dir: str, references: Any, *,
                       allow_after_run_fallback: bool = False) -> Tuple[List[str], List[str]]:
    """Accept only existing, bundle-relative evidence references."""
    from scripts import capture_evidence

    if not isinstance(references, list) or not references:
        return [], ["evidence_references_missing"]
    valid: List[str] = []
    errors: List[str] = []
    root = Path(run_dir)
    for reference in references:
        candidate, error = capture_evidence._bundle_file(root, reference)
        if (error == "missing_file" and allow_after_run_fallback and
                isinstance(reference, str) and
                re.fullmatch(r"snapshots/step-[0-9]{3}-after\.json", reference)):
            fallback_ref = "snapshots/after-run.json"
            fallback_candidate, fallback_error = capture_evidence._bundle_file(
                root, fallback_ref
            )
            if fallback_candidate is not None and fallback_error is None:
                valid.append(fallback_ref)
                continue
        if error or candidate is None:
            errors.append("evidence_reference_invalid:%s" % (reference if isinstance(reference, str) else "invalid"))
        else:
            valid.append(str(reference))
    return valid, errors


def _g5t_load_snapshot(bundle: Dict[str, Any], reference: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Read one bundle-relative G5T snapshot without trusting its reference."""
    from scripts import capture_evidence

    run_dir = bundle.get("run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        return None, "run_directory_unavailable"
    return capture_evidence.load_bundle_json(Path(run_dir), reference)


def _g5t_derive_cover_checks(
    bundle: Dict[str, Any], actor_names: Dict[str, str], before_creatures: Any,
    after_creatures: Any,
) -> Dict[str, Any]:
    """Recompute cover evidence from the covered-step snapshots and trace."""
    from scripts import capture_evidence

    trace_events = bundle.get("trace_events") if isinstance(bundle.get("trace_events"), list) else []
    cover_events = [event for event in trace_events
                    if isinstance(event, dict) and
                    event.get("event_type") == "combat_observation" and
                    event.get("observation") == "combat_cover_outcome"]
    target_ids = [actor_id for actor_id, name in actor_names.items()
                  if " ".join(name.split()).casefold() == "goblin squad b"]
    target_actor_id = target_ids[0] if len(target_ids) == 1 else None
    artifact_paths = bundle.get("artifact_paths")
    artifact_paths = artifact_paths if isinstance(artifact_paths, dict) else {}
    trace_ref = artifact_paths.get("trace")
    after_ref = artifact_paths.get("after_snapshot")
    errors: List[str] = []

    try:
        if __package__:
            from scripts.combat_latency_fixtures import build_g5t_script_steps
        else:
            from combat_latency_fixtures import build_g5t_script_steps
        scripted_steps = build_g5t_script_steps(bundle.get("party_size"))
        covered_steps = [row for row in scripted_steps
                         if isinstance(row.get("label"), str) and
                         row["label"].endswith("covered-target attack")]
    except (ImportError, TypeError, ValueError):
        covered_steps = []

    cover_status = "BLOCKED"
    cover_observed: Dict[str, Any] = {
        "base_ac": None, "cover_bonus": None, "effective_ac": None,
        "attack_effective_ac": None,
    }
    cover_refs: List[str] = []
    if len(covered_steps) != 1:
        errors.append("g5t_cover_attack_step_identity_unavailable")
    else:
        covered_step = covered_steps[0]
        step_number = covered_step.get("step")
        if not isinstance(step_number, int) or isinstance(step_number, bool) or step_number < 1:
            errors.append("g5t_cover_attack_step_identity_unavailable")
        else:
            before_ref = "snapshots/step-%03d-before.json" % step_number
            step_after_ref = "snapshots/step-%03d-after.json" % step_number
            cover_refs = [value for value in (trace_ref, before_ref, step_after_ref)
                          if isinstance(value, str) and value]
            receipts = [
                row for row in bundle.get("receipts", [])
                if isinstance(row, dict) and (
                    row.get("script_step") == step_number or
                    (isinstance(row.get("work_unit"), dict) and
                     row["work_unit"].get("id") == covered_step.get("unit_id"))
                )
            ]
            if len(receipts) == 1 and receipts[0].get("status") == "skipped":
                if receipts[0].get("skip_reason") in ("combat_ended", "target_inactive"):
                    cover_status = "NOT_OBSERVED"
                else:
                    errors.append("g5t_cover_attack_skip_reason_unavailable")
            elif len(receipts) != 1 or receipts[0].get("status") != "sent":
                errors.append("g5t_cover_attack_receipt_missing_or_ambiguous")
            else:
                before_step, before_error = _g5t_load_snapshot(bundle, before_ref)
                after_step, after_error = _g5t_load_snapshot(bundle, step_after_ref)
                if before_error or after_error or not isinstance(before_step, dict) or not isinstance(after_step, dict):
                    errors.append("g5t_cover_step_snapshot_unavailable")
                else:
                    before_observation = before_step.get("observation")
                    after_observation = after_step.get("observation")
                    before_observation = before_observation if isinstance(before_observation, dict) else {}
                    after_observation = after_observation if isinstance(after_observation, dict) else {}
                    step_records = capture_evidence._step_records(before_step)
                    step_tracker = step_records.get("party_tracker.json", {})
                    step_world = step_tracker.get("worldConditions")
                    step_encounter = capture_evidence._selected_encounter(before_step)
                    step_creatures = step_encounter.get("creatures")
                    target_rows = [row for row in step_creatures or []
                                   if isinstance(row, dict) and
                                   " ".join(str(row.get("name", "")).split()).casefold() ==
                                   "goblin squad b"]
                    applied = [event for event in cover_events
                               if event.get("cover_state") == "applied" and
                               event.get("actor_id") == target_actor_id]
                    cover_seen = bool(applied) or any(
                        isinstance(row, dict) and
                        (row.get("coverFeatureId") or row.get("coverType"))
                        for row in target_rows
                    )
                    if not cover_seen:
                        cover_status = "NOT_OBSERVED"
                    elif (len(target_rows) != 1 or target_actor_id is None or
                          before_observation.get("label") != covered_step.get("label") or
                          not isinstance(step_world, dict) or
                          step_world.get("activeCombatEncounter") != bundle.get("scenario_id")):
                        errors.append("g5t_cover_attack_snapshot_identity_unavailable")
                    elif before_observation.get("input") != covered_step.get("input"):
                        cover_status = "FAIL"
                        errors.append("g5t_cover_effective_ac_assertion_failed")
                    else:
                        target = target_rows[0]
                        base_ac = target.get("armorClass")
                        cover_type = target.get("coverType")
                        feature_id = target.get("coverFeatureId")
                        bonus = {"half": 2, "three_quarters": 5}.get(cover_type)
                        effective_ac = (base_ac + bonus
                                        if _g5_is_number(base_ac) and bonus is not None else None)
                        cover_observed.update({
                            "base_ac": base_ac, "cover_bonus": bonus,
                            "effective_ac": effective_ac,
                        })
                        applied_matches = [event for event in applied
                                           if event.get("feature_id") == feature_id and
                                           event.get("cover_type") == cover_type]
                        output_rows = after_observation.get("actual_backend_outputs")
                        output_text = "\n".join(
                            row.get("content", "") for row in output_rows
                            if isinstance(row, dict) and isinstance(row.get("content"), str)
                        ) if isinstance(output_rows, list) else ""
                        comparisons = re.findall(
                            r"Rolled\s+(\d+)\s+vs AC\s+(\d+)", output_text, re.IGNORECASE
                        )
                        expected_command = re.fullmatch(
                            r"/att\s+Goblin Squad B\s+(\d+)\s+training blade",
                            str(covered_step.get("input", "")), re.IGNORECASE,
                        )
                        actual_command = re.fullmatch(
                            r"/att\s+Goblin Squad B\s+(\d+)\s+training blade",
                            str(before_observation.get("input", "")), re.IGNORECASE,
                        )
                        attack_roll = int(comparisons[0][0]) if len(comparisons) == 1 else None
                        attack_ac = int(comparisons[0][1]) if len(comparisons) == 1 else None
                        attack_hit = bool(re.search(r"\bHit(?:s)?\b", output_text, re.IGNORECASE))
                        attack_miss = bool(re.search(r"\bMiss(?:ed)?\b", output_text, re.IGNORECASE))
                        result_matches = (
                            _g5_is_number(effective_ac) and attack_roll is not None and
                            ((attack_hit and not attack_miss and attack_roll >= effective_ac) or
                             (attack_miss and not attack_hit and attack_roll < effective_ac))
                        )
                        cover_observed["attack_effective_ac"] = attack_ac
                        if (not feature_id or not cover_type or bonus is None or
                                not _g5_is_number(base_ac)):
                            cover_status = "FAIL"
                            errors.append("g5t_cover_effective_ac_assertion_failed")
                        elif applied and len(applied_matches) != 1:
                            cover_status = "FAIL"
                            errors.append("g5t_cover_effective_ac_assertion_failed")
                        elif len(comparisons) != 1 or expected_command is None or actual_command is None:
                            errors.append("g5t_cover_attack_comparison_unavailable")
                        elif (actual_command.group(1) != expected_command.group(1) or
                              attack_roll != int(expected_command.group(1)) or
                              attack_ac != effective_ac or not result_matches):
                            cover_status = "FAIL"
                            errors.append("g5t_cover_effective_ac_assertion_failed")
                        else:
                            cover_status = "PASS"

    checked_cover_refs, cover_ref_errors = _g5t_evidence_refs(
        bundle.get("run_dir", ""), cover_refs
    ) if cover_refs else ([], [])
    errors.extend("g5t_%s" % reason for reason in cover_ref_errors)
    if cover_ref_errors and cover_status not in ("FAIL", "NOT_OBSERVED"):
        cover_status = "BLOCKED"

    cover_expired = [event for event in cover_events
                     if event.get("cover_state") == "expired" and
                     event.get("actor_id") == target_actor_id]
    before_cover = [row for row in before_creatures or []
                    if isinstance(row, dict) and
                    " ".join(str(row.get("name", "")).split()).casefold() ==
                    "goblin squad b"]
    after_cover = [row for row in after_creatures or []
                   if isinstance(row, dict) and
                   " ".join(str(row.get("name", "")).split()).casefold() ==
                   "goblin squad b"]
    after_snapshot = bundle.get("after_snapshot")
    after_records = capture_evidence._step_records(after_snapshot)
    final_tracker = after_records.get("party_tracker.json", {})
    final_world = final_tracker.get("worldConditions")
    active_after = (final_world.get("activeCombatEncounter")
                    if isinstance(final_world, dict) else "unavailable")
    base_after = after_cover[0].get("armorClass") if len(after_cover) == 1 else None
    cover_seen = bool(cover_expired) or any(
        isinstance(row, dict) and (row.get("coverFeatureId") or row.get("coverType"))
        for row in before_cover + after_cover
    )
    expiration_refs = [value for value in (trace_ref, after_ref)
                       if isinstance(value, str) and value]
    checked_expiration_refs, expiration_ref_errors = _g5t_evidence_refs(
        bundle.get("run_dir", ""), expiration_refs
    ) if expiration_refs else ([], [])
    errors.extend("g5t_%s" % reason for reason in expiration_ref_errors)
    inert_after_exit = active_after in (None, "")
    if not cover_seen:
        expiration_status = "NOT_OBSERVED"
        effective_after = None
    elif (len(after_cover) != 1 or not _g5_is_number(base_after) or
          final_tracker.get("status") != "ok" or not isinstance(final_world, dict)):
        expiration_status = "BLOCKED"
        effective_after = None
        errors.append("g5t_cover_expiration_observation_missing")
    elif not cover_expired:
        expiration_status = "BLOCKED"
        effective_after = None
        errors.append("g5t_cover_expiration_trace_missing")
    elif not inert_after_exit:
        expiration_status = "FAIL"
        effective_after = None
        errors.append("g5t_cover_expiration_assertion_failed")
    else:
        expiration_status = "PASS"
        effective_after = base_after

    return {
        "cover_check": {
            "status": cover_status, "observed": cover_observed,
            "evidence_refs": checked_cover_refs,
        },
        "expiration_check": {
            "status": expiration_status,
            "observed": {
                "base_ac": base_after,
                "effective_ac_after_exit": effective_after,
                "cover_inert_after_exit": inert_after_exit,
                "active_combat_encounter_after_run": active_after,
            },
            "evidence_refs": checked_expiration_refs,
        },
        "cover_events": cover_events,
        "cover_applied": [event for event in cover_events
                          if event.get("cover_state") == "applied" and
                          event.get("actor_id") == target_actor_id],
        "cover_expired": cover_expired,
        "errors": errors,
    }


def _g5t_check_rows(checks_doc: Any, check_id: str) -> List[Dict[str, Any]]:
    rows = checks_doc.get("checks") if isinstance(checks_doc, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("id") == check_id]


def _g5t_run_local_actor_names(creatures: Any) -> Dict[str, str]:
    """Rebuild trace actor IDs from the run snapshot without importing runtime code."""
    if not isinstance(creatures, list):
        return {}
    by_identity: Dict[Tuple[str, str], Tuple[str, str]] = {}
    ambiguous = set()
    next_index = 1
    for creature in creatures[:128]:
        if not isinstance(creature, dict):
            continue
        kind, name = creature.get("type"), creature.get("name")
        if not isinstance(kind, str) or not isinstance(name, str) or not name.strip() or len(name) > 128:
            continue
        kind = kind.strip().casefold()
        if kind == "pc":
            kind = "player"
        if kind not in {"enemy", "player", "npc"}:
            continue
        key = (kind, " ".join(name.split()).casefold())
        if key in by_identity:
            by_identity.pop(key, None)
            ambiguous.add(key)
            continue
        if key in ambiguous or next_index > 32:
            continue
        actor_id = "actor_%d" % next_index
        by_identity[key] = (actor_id, name)
        next_index += 1
    return {actor_id: name for (kind, _), (actor_id, name) in by_identity.items()
            if kind == "enemy"}


def _g5t_batch_check(bundle: Dict[str, Any], check_id: str, batch_id: str,
                     batch_count: int) -> Dict[str, Any]:
    rows = _g5t_check_rows(bundle.get("checks"), check_id)
    candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for row in rows:
        observations = row.get("observations")
        if isinstance(observations, list):
            candidates.extend((row, observation) for observation in observations
                              if isinstance(observation, dict) and observation.get("batch_id") == batch_id)
        elif row.get("batch_id") == batch_id:
            candidates.append((row, row))
        elif batch_count == 1:
            candidates.append((row, row))
    if len(candidates) != 1:
        return {"status": "BLOCKED", "errors": ["check_missing_or_ambiguous:%s" % check_id]}
    row, observed = candidates[0]
    status = observed.get("status", row.get("status"))
    references = observed.get("evidence_refs", row.get("evidence_refs"))
    refs, ref_errors = _g5t_evidence_refs(
        bundle.get("run_dir", ""), references, allow_after_run_fallback=True
    )
    errors = list(ref_errors)
    if status not in ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "NOT_OBSERVED"):
        errors.append("check_status_unavailable:%s" % check_id)
    return {"status": "BLOCKED" if ref_errors or status not in
            ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "NOT_OBSERVED") else status,
            "observed": observed.get("observed", observed), "evidence_refs": refs,
            "errors": errors}


def _g5t_run_check(bundle: Dict[str, Any], check_id: str) -> Dict[str, Any]:
    rows = _g5t_check_rows(bundle.get("checks"), check_id)
    if len(rows) != 1:
        return {"status": "BLOCKED", "errors": ["check_missing_or_ambiguous:%s" % check_id]}
    row = rows[0]
    observed = row.get("observed") if isinstance(row.get("observed"), dict) else row
    refs, ref_errors = _g5t_evidence_refs(bundle.get("run_dir", ""), row.get("evidence_refs"))
    status = row.get("status")
    errors = list(ref_errors)
    if status not in ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "NOT_OBSERVED"):
        errors.append("check_status_unavailable:%s" % check_id)
    return {"status": "BLOCKED" if ref_errors or status not in
            ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "NOT_OBSERVED") else status,
            "observed": observed, "evidence_refs": refs, "errors": errors}


def _g5t_batch_provider_kind(event: Dict[str, Any]) -> Optional[str]:
    """Return the counted G5T request class, excluding post-batch work."""
    site = event.get("site") or event.get("task")
    purpose = event.get("purpose")
    if purpose == "combat_enemy_batch_commander_plan" or site == "combat_tactical_plan":
        return "plan"
    if purpose == "combat_enemy_batch_narration":
        return "narration"
    if purpose == "combat_validation" or site == "combat_validation":
        return "validation"
    if site == "combat_main":
        return "narration"
    return None


def _g5t_exit_flow_provider_calls(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve exit-flow provider receipts from the entire bundle trace."""
    events = bundle.get("trace_events") if isinstance(bundle.get("trace_events"), list) else []
    calls: List[Dict[str, Any]] = []
    by_batch: Dict[str, Dict[str, int]] = {}
    unattributed: List[Dict[str, Any]] = []
    receipt_fields = (
        "call_id", "attempt_id", "attempt_number", "recorded_at_ms", "batch_id",
        "site", "task", "purpose", "provider", "requested_model", "resolved_model",
        "elapsed_ms", "outcome",
    )
    for event in events:
        if (not isinstance(event, dict) or event.get("event_type") != "provider" or
                event.get("site") not in G5T_EXIT_FLOW_PROVIDER_SITES):
            continue
        receipt = {key: event.get(key) for key in receipt_fields if key in event}
        if receipt.get("site") == "combat_compression":
            # G6's router trace site maps to the established exit-flow label.
            receipt["site"] = "compression"
        calls.append(receipt)
        batch_id, site = receipt.get("batch_id"), receipt.get("site")
        if isinstance(batch_id, str) and batch_id:
            batch_counts = by_batch.setdefault(batch_id, {})
            batch_counts[site] = batch_counts.get(site, 0) + 1
        else:
            unattributed.append(receipt)
    return {
        "total_calls": len(calls),
        "by_batch": {batch_id: {site: sites[site] for site in sorted(sites)}
                     for batch_id, sites in sorted(by_batch.items())},
        "calls": calls,
        "unattributed_calls": unattributed,
    }


def _g5t_batch_observation(bundle: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
    """Attribute provider attempts, writes, validation and legality to one batch."""
    errors: List[str] = []
    unit_id, round_number, batch_id = step.get("unit_id"), step.get("round"), step.get("batch_id")
    receipts = bundle.get("receipts") if isinstance(bundle.get("receipts"), list) else []
    matching_receipts = [row for row in receipts if isinstance(row, dict) and
                         isinstance(row.get("work_unit"), dict) and
                         row["work_unit"].get("type") == "batch" and
                         row["work_unit"].get("id") == unit_id and
                         row["work_unit"].get("round") == round_number]
    if len(matching_receipts) != 1:
        errors.append("g5t_batch_receipt_missing_or_ambiguous:%s" % unit_id)
        receipt: Dict[str, Any] = {}
    else:
        receipt = matching_receipts[0]
    window = receipt.get("trace_window") if isinstance(receipt.get("trace_window"), dict) else {}
    start_ms, end_ms = window.get("start_epoch_ms"), window.get("end_epoch_ms")
    if (not _g5_is_number(start_ms) or not _g5_is_number(end_ms) or
            start_ms < 0 or end_ms < start_ms):
        errors.append("g5t_batch_trace_window_unavailable:%s" % unit_id)
        start_ms = end_ms = None
    else:
        start_ms, end_ms = float(start_ms), float(end_ms)

    events = bundle.get("trace_events") if isinstance(bundle.get("trace_events"), list) else []
    in_window: List[Dict[str, Any]] = []
    if start_ms is not None:
        for event in events:
            if not isinstance(event, dict):
                continue
            timestamp = event.get("recorded_at_ms")
            if (_g5_is_number(timestamp) and start_ms <= float(timestamp) <= end_ms and
                    event.get("batch_id") == batch_id):
                in_window.append(event)
            elif (event.get("batch_id") == batch_id and timestamp is None):
                errors.append("g5t_batch_event_timestamp_missing:%s" % unit_id)

    plan_results = [event for event in in_window if event.get("event_type") == "combat_observation" and
                    event.get("observation") == "combat_tactical_plan_result"]
    decisions = [event for event in in_window if event.get("event_type") == "decision" and
                 event.get("decision_point") == "enemy_batch_resolution"]
    plan_result = plan_results[0] if len(plan_results) == 1 else {}
    decision = decisions[0] if len(decisions) == 1 else {}
    decision_source = decision.get("decision_source")
    rule_tier_deviation = (len(decisions) == 1 and
                           decision_source in ("deterministic", "llm_fallback", "jev"))

    # The run-local batch id is the durable ownership link. Use it even when
    # post-output provider work lands after an older capture's quiet-window end.
    provider_events = [
        event for event in events
        if event.get("event_type") == "provider"
        and event.get("batch_id") == batch_id
        and event.get("site") != G5T_PREFETCH_PROVIDER_SITE
    ]
    # trace_provider_call records the plan call at a call-level site, while the
    # receipt observer records each raw SDK attempt (including router retries).
    # Prefer observer attempts when present so the same request is not counted twice.
    observer_events = [event for event in provider_events
                       if isinstance(event.get("attempt_id"), str) and event.get("attempt_id")]
    attempts_by_id: Dict[str, Dict[str, Any]] = {}
    for event in observer_events:
        attempt_id = event["attempt_id"]
        previous = attempts_by_id.get(attempt_id)
        if previous is None or (
                previous.get("purpose") is None and event.get("purpose") is not None):
            attempts_by_id[attempt_id] = event
    attempts = list(attempts_by_id.values())
    unkeyed_events = [event for event in provider_events
                       if not (isinstance(event.get("attempt_id"), str) and event.get("attempt_id"))]
    plan_markers = [event for event in unkeyed_events
                    if event.get("site") == "combat_tactical_plan"]
    unkeyed_other = [event for event in unkeyed_events
                     if event.get("site") != "combat_tactical_plan" and
                     event.get("site") not in G5T_EXIT_FLOW_PROVIDER_SITES]
    if unkeyed_other:
        errors.append("g5t_provider_attempt_identity_missing:%s" % unit_id)
        attempts.extend(unkeyed_other)
    plan_attempts = [event for event in attempts
                     if event.get("purpose") == "combat_enemy_batch_commander_plan"]
    if plan_markers and not plan_attempts:
        # The direct site record is the only available raw-call evidence in
        # older/partial trace versions; keep it visible rather than zero-fill.
        attempts.extend(plan_markers)
    elif len(plan_markers) > 1:
        errors.append("g5t_plan_call_marker_ambiguous:%s" % unit_id)

    counted_attempts: List[Tuple[Dict[str, Any], str]] = []
    for event in attempts:
        request_kind = _g5t_batch_provider_kind(event)
        if request_kind is None:
            site = event.get("site") or event.get("task")
            if site not in G5T_EXIT_FLOW_PROVIDER_SITES:
                errors.append("g5t_batch_provider_kind_unavailable:%s" % unit_id)
            continue
        counted_attempts.append((event, request_kind))

    provider_calls_by_site: Dict[str, int] = {}
    plan_calls = 0
    narration_calls = 0
    validation_calls = 0
    provider_site_missing = False
    for event, request_kind in counted_attempts:
        site = event.get("site") or event.get("task")
        if not isinstance(site, str) or not site:
            provider_site_missing = True
            errors.append("g5t_provider_site_unavailable:%s" % unit_id)
            continue
        provider_calls_by_site[site] = provider_calls_by_site.get(site, 0) + 1
        if request_kind == "plan":
            plan_calls += 1
        elif request_kind == "narration":
            narration_calls += 1
        elif request_kind == "validation":
            validation_calls += 1

    provider_calls: Optional[int] = (
        0 if rule_tier_deviation else
        len(counted_attempts) if counted_attempts and not provider_site_missing else None
    )
    if provider_calls is None:
        errors.append("g5t_raw_provider_attempts_unavailable:%s" % unit_id)
    if plan_calls == 0 and not rule_tier_deviation:
        errors.append("g5t_plan_provider_attempt_missing:%s" % unit_id)
    if narration_calls == 0 and not rule_tier_deviation:
        errors.append("g5t_narration_provider_attempt_missing:%s" % unit_id)
    if rule_tier_deviation:
        plan_calls = narration_calls = validation_calls = 0
        provider_calls_by_site = {}

    batch_events = [event for event in events if event.get("batch_id") == batch_id]
    character_apply_events = [
        event for event in batch_events
        if event.get("event_type") == "combat_observation"
        and event.get("observation") == "combat_apply_result"
        and event.get("domain") == "character"
    ]
    persisted_character_events = [
        event for event in batch_events
        if event.get("event_type") == "combat_observation"
        and event.get("observation") == "combat_apply_persisted_state"
        and event.get("domain") == "character"
    ]
    after_snapshot = bundle.get("after_snapshot")
    after_records = (after_snapshot.get("records")
                     if isinstance(after_snapshot, dict) else None)
    after_records = after_records if isinstance(after_records, dict) else {}
    changed_character_names = set()
    character_change_evidence_valid = True
    for event in character_apply_events:
        if event.get("applied") is not True:
            continue
        target = event.get("target")
        operations = event.get("ops")
        if not isinstance(target, str) or not target.strip():
            character_change_evidence_valid = False
            continue
        target_key = " ".join(target.split()).casefold()
        if not isinstance(operations, list):
            if event.get("operation") != "update_character_info_prose":
                character_change_evidence_valid = False
                continue
            changes = event.get("changes")
            persisted_matches = [row for row in persisted_character_events
                                 if " ".join(str(row.get("target", "")).split()).casefold() ==
                                 target_key]
            final_matches = [state for path, state in after_records.items()
                             if isinstance(path, str) and path.startswith("characters/") and
                             isinstance(state, dict) and
                             " ".join(str(state.get("name", "")).split()).casefold() ==
                             target_key]
            persisted_state = (persisted_matches[0].get("persisted_state")
                               if len(persisted_matches) == 1 else None)
            final_state = final_matches[0] if len(final_matches) == 1 else None
            state_fields = ("name", "status", "hitPoints", "maxHitPoints")
            state_matches = (
                isinstance(persisted_state, dict) and isinstance(final_state, dict) and
                all(field in persisted_state and field in final_state and
                    persisted_state.get(field) == final_state.get(field)
                    for field in state_fields)
            )
            if (not isinstance(changes, str) or not changes.strip() or
                    len(persisted_matches) != 1 or not state_matches):
                character_change_evidence_valid = False
                continue
            changed_character_names.add(target_key)
            continue
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("op") != "hp_delta":
                character_change_evidence_valid = False
                continue
            delta = operation.get("delta")
            if not isinstance(delta, int) or isinstance(delta, bool):
                character_change_evidence_valid = False
                continue
            if delta != 0:
                changed_character_names.add(" ".join(target.split()).casefold())

    physical_writes = [event for event in events
                       if event.get("event_type") == "file_operation" and
                       event.get("category") == "write" and event.get("site") == "enemy_batch_write" and
                       event.get("batch_id") == batch_id]
    malformed_writes = [event for event in physical_writes
                        if event.get("target_kind") not in ("history", "character", "encounter") or
                        not isinstance(event.get("target_id"), str) or not event.get("target_id")]
    if malformed_writes and not rule_tier_deviation:
        errors.append("g5t_batch_raw_write_event_malformed:%s" % unit_id)
    raw_writes: Optional[int] = len(physical_writes) if physical_writes and not malformed_writes else None
    if raw_writes is None and not rule_tier_deviation:
        errors.append("g5t_batch_raw_writes_unavailable:%s" % unit_id)
    character_write_events = [
        event for event in physical_writes if event.get("target_kind") == "character"
    ]
    changed_character_count: Optional[int] = (
        len(changed_character_names) if character_change_evidence_valid else None
    )
    if character_write_events and not character_apply_events:
        changed_character_count = None
    if ((not character_change_evidence_valid or changed_character_count is None) and
            not rule_tier_deviation):
        errors.append("g5t_batch_changed_character_count_unavailable:%s" % unit_id)
    raw_write_limit = (
        G5T_BATCH_FIXED_WRITE_BUDGET + changed_character_count
        if changed_character_count is not None else None
    )
    write_counts = {
        kind: sum(event.get("target_kind") == kind for event in physical_writes)
        for kind in ("history", "character", "encounter")
    }

    if len(plan_results) != 1 and not rule_tier_deviation:
        errors.append("g5t_plan_result_missing_or_ambiguous:%s" % unit_id)
    if len(decisions) != 1:
        errors.append("g5t_commander_decision_missing_or_ambiguous:%s" % unit_id)
    plan_outcome = plan_result.get("tactical_plan_outcome")
    if (not rule_tier_deviation and
            plan_outcome not in ("accepted", "partially_defaulted", "rejected_all")):
        errors.append("g5t_plan_outcome_unavailable_or_invalid:%s" % unit_id)
    if decision_source != "llm_tactical" and not rule_tier_deviation:
        errors.append("g5t_decision_source_not_commander:%s" % unit_id)
    decision_plan_outcome = decision.get("tactical_plan_outcome")
    if (not rule_tier_deviation and decision_plan_outcome is not None and
            decision_plan_outcome != plan_outcome):
        errors.append("g5t_plan_outcome_trace_mismatch:%s" % unit_id)
    default_reasons = plan_result.get("default_reasons", decision.get("default_reasons"))
    if (not rule_tier_deviation and plan_outcome in ("partially_defaulted", "rejected_all") and
            not isinstance(default_reasons, list)):
        errors.append("g5t_plan_default_reasons_missing:%s" % unit_id)

    legality = (_g5t_batch_check(
        bundle, "applied_choice_legality", str(batch_id), len(bundle.get("batch_steps", []))
    ) if not rule_tier_deviation else {"status": "NOT_APPLICABLE", "errors": []})
    errors.extend("g5t_%s:%s" % (reason, unit_id) for reason in legality.get("errors", []))
    legality_observed = legality.get("observed")
    applied_count = legal_count = legality_percent = None
    if legality.get("status") == "NOT_APPLICABLE":
        pass
    elif isinstance(legality_observed, dict):
        applied_count = legality_observed.get("applied_choice_count")
        legal_count = legality_observed.get("legal_applied_choice_count")
        valid_counts = all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in (applied_count, legal_count)
        )
        if not valid_counts or applied_count == 0 or legal_count > applied_count:
            errors.append("g5t_applied_choice_legality_counts_invalid:%s" % unit_id)
        else:
            legality_percent = round(legal_count * 100.0 / applied_count, 6)
    elif not rule_tier_deviation:
        errors.append("g5t_applied_choice_legality_observation_missing:%s" % unit_id)
    if legality.get("status") == "BLOCKED" and not any(
            "applied_choice_legality" in reason for reason in errors):
        errors.append("g5t_applied_choice_legality_blocked:%s" % unit_id)

    work_only_ms = receipt.get("work_only_ms")
    if not _g5_is_number(work_only_ms) or work_only_ms < 0:
        errors.append("g5t_batch_work_only_timing_unavailable:%s" % unit_id)
        work_only_ms = None

    return {
        "status": "BLOCKED" if errors else "OBSERVED",
        "unit_id": unit_id, "round": round_number, "batch_id": batch_id,
        "work_only_ms": work_only_ms, "provider_calls": provider_calls,
        "counted_provider_calls": provider_calls,
        "counted_provider_calls_by_site": {key: provider_calls_by_site[key]
                                            for key in sorted(provider_calls_by_site)},
        "provider_calls_by_site": {key: provider_calls_by_site[key]
                                    for key in sorted(provider_calls_by_site)},
        "plan_provider_calls": plan_calls if plan_calls or rule_tier_deviation else None,
        "narration_provider_calls": narration_calls if narration_calls or rule_tier_deviation else None,
        "validation_provider_calls": validation_calls if attempts or rule_tier_deviation else None,
        "raw_file_writes": raw_writes,
        "raw_file_write_limit": raw_write_limit,
        "raw_file_write_status": (
            "NOT_APPLICABLE" if rule_tier_deviation and raw_writes is None else
            "BLOCKED" if raw_writes is None or raw_write_limit is None else
            "OBSERVED"
        ),
        "changed_character_count": changed_character_count,
        "write_target_counts": write_counts,
        "write_targets": [{"target_kind": event.get("target_kind"),
                            "target_id": event.get("target_id")}
                           for event in physical_writes if not malformed_writes],
        "decision_source": decision_source,
        "accepted_commander_batch": decision_source == "llm_tactical",
        "deviation": ({"kind": "rule_tier_fallback",
                       "decision_source": decision_source,
                       "decision_outcome": decision.get("decision_outcome"),
                       "decision_reason": decision.get("decision_reason"),
                       "work_unit_id": unit_id, "batch_id": batch_id}
                      if rule_tier_deviation else None),
        "tactical_plan_outcome": plan_outcome,
        "default_reasons": default_reasons if isinstance(default_reasons, list) else None,
        "applied_choice_count": applied_count, "legal_applied_choice_count": legal_count,
        "applied_choice_legality_percent": legality_percent,
        "applied_choice_legality_status": legality.get("status"),
        "legality_evidence_refs": legality.get("evidence_refs", []),
        "prefetch_statuses": sorted({event.get("prefetch_status") for event in in_window
                                      if event.get("event_type") == "combat_observation" and
                                      event.get("observation") == "combat_tactical_prefetch_status" and
                                      isinstance(event.get("prefetch_status"), str)} |
                                     ({plan_result.get("prefetch_status")}
                                      if isinstance(plan_result.get("prefetch_status"), str) else set())),
        "errors": sorted(set(errors)),
        "_events": in_window,
    }


def _g5t_squad_followthrough(batch_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate one bounded squad observation per commander-planned batch."""
    planned = [row for row in batch_rows if row.get("accepted_commander_batch") is True]
    observations: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not planned:
        return {
            "status": "BLOCKED", "followed_orders": None,
            "observations": [],
            "errors": ["g5t_commander_squad_observations_missing"],
        }

    saw_failure = False
    saw_blocked = False
    for batch in planned:
        batch_id = batch.get("batch_id")
        events = [event for event in batch.get("_events", [])
                  if isinstance(event, dict)
                  and event.get("event_type") == "combat_observation"
                  and event.get("observation") == "commander_squad_follows_orders"
                  and event.get("batch_id") == batch_id]
        if len(events) != 1:
            status = "BLOCKED"
            observed = None
            errors.append("g5t_commander_squad_observation_missing_or_ambiguous:%s" %
                          (batch_id or "unknown"))
        else:
            event = events[0]
            issued = event.get("issued_choice_count")
            applied = event.get("applied_choice_count")
            followed = event.get("followed_orders")
            valid_counts = (
                isinstance(issued, int) and not isinstance(issued, bool) and 0 <= issued <= 32
                and isinstance(applied, int) and not isinstance(applied, bool)
                and 0 <= applied <= issued
            )
            if not valid_counts or not isinstance(followed, bool) or (
                    followed and (issued == 0 or applied != issued)):
                status = "BLOCKED"
                observed = None
                errors.append("g5t_commander_squad_observation_malformed:%s" %
                              (batch_id or "unknown"))
            elif issued == 0:
                status = "NOT_APPLICABLE"
                observed = {
                    "applicability": "no_commander_plan_contribution",
                    "issued_choice_count": 0,
                    "applied_choice_count": 0,
                }
            else:
                status = "PASS" if followed else "FAIL"
                observed = {
                    "followed_orders": followed,
                    "issued_choice_count": issued,
                    "applied_choice_count": applied,
                }
        saw_failure = saw_failure or status == "FAIL"
        saw_blocked = saw_blocked or status == "BLOCKED"
        observations.append({"batch_id": batch_id, "status": status, "observed": observed})

    observed_statuses = [row["status"] for row in observations]
    aggregate_status = (
        "FAIL" if saw_failure else
        "BLOCKED" if saw_blocked else
        "PASS" if "PASS" in observed_statuses else
        "NOT_APPLICABLE"
    )
    followed_orders = (True if aggregate_status == "PASS" else
                       False if aggregate_status == "FAIL" else None)
    return {
        "status": aggregate_status,
        "followed_orders": followed_orders,
        "issued_choice_count": sum(
            row["observed"]["issued_choice_count"] for row in observations
            if isinstance(row.get("observed"), dict)
        ),
        "applied_choice_count": sum(
            row["observed"]["applied_choice_count"] for row in observations
            if isinstance(row.get("observed"), dict)
        ),
        "observations": observations,
        "errors": errors,
    }


def _g5t_run_behavior(bundle: Dict[str, Any], batch_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate required behavior checks and retain their evidence references."""
    from scripts import capture_evidence

    errors: List[str] = []
    batch_events = [event for row in batch_rows for event in row.get("_events", [])]
    trace_events = bundle.get("trace_events") if isinstance(bundle.get("trace_events"), list) else []
    self_events = [event for event in trace_events
                   if isinstance(event, dict) and event.get("event_type") == "combat_observation" and
                   event.get("observation") == "combat_self_preservation_outcome"]
    removal_check = _g5t_run_check(bundle, "self_preservation_removal")
    errors.extend("g5t_%s" % reason for reason in removal_check.get("errors", []))
    removal_rows: List[Dict[str, Any]] = []
    raw_removals = removal_check.get("observed", {}).get("observations")
    if not isinstance(raw_removals, list):
        errors.append("g5t_self_preservation_removal_observations_missing")
        raw_removals = []
    trace_by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for event in self_events:
        actor_id = event.get("actor_id")
        outcome = event.get("self_preservation_outcome")
        batch_id = event.get("batch_id")
        if (not isinstance(actor_id, str) or outcome not in ("fled", "surrendered") or
                not isinstance(batch_id, str)):
            errors.append("g5t_self_preservation_trace_event_malformed")
            continue
        trace_by_key.setdefault((actor_id, outcome, batch_id), []).append(event)

    before_snapshot = bundle.get("before_snapshot")
    after_snapshot = bundle.get("after_snapshot")
    before_creatures = capture_evidence._selected_encounter(before_snapshot).get("creatures")
    after_creatures = capture_evidence._selected_encounter(after_snapshot).get("creatures")
    actor_names = _g5t_run_local_actor_names(before_creatures)
    after_records = capture_evidence._step_records(after_snapshot)
    tracker_after = after_records.get("party_tracker.json", {})
    world_after = tracker_after.get("worldConditions")
    encounter_cleared = (
        tracker_after.get("status") == "ok" and isinstance(world_after, dict) and
        world_after.get("activeCombatEncounter") in (None, "")
    )
    auto_exit_batches = {
        event.get("batch_id") for event in trace_events
        if isinstance(event, dict) and event.get("event_type") == "combat_observation" and
        event.get("observation") == "xp_award" and event.get("source") == "auto_exit" and
        isinstance(event.get("batch_id"), str)
    }

    outcome_statuses: Dict[str, List[str]] = {"fled": [], "surrendered": []}
    seen_removal_keys = set()
    for row in raw_removals:
        if not isinstance(row, dict):
            errors.append("g5t_self_preservation_removal_observation_malformed")
            continue
        actor_id, outcome = row.get("actor_id"), row.get("outcome")
        batch_id = row.get("batch_id")
        identity_valid = (isinstance(actor_id, str) and isinstance(outcome, str) and
                          isinstance(batch_id, str))
        key = (actor_id if isinstance(actor_id, str) else "",
               outcome if isinstance(outcome, str) else "",
               batch_id if isinstance(batch_id, str) else "")
        if not identity_valid:
            errors.append("g5t_self_preservation_removal_observation_malformed")
        if isinstance(outcome, str) and outcome in outcome_statuses:
            outcome_statuses[outcome].append("BLOCKED")
        if key in seen_removal_keys:
            errors.append("g5t_self_preservation_removal_observation_ambiguous")
        seen_removal_keys.add(key)
        refs, ref_errors = _g5t_evidence_refs(bundle.get("run_dir", ""), row.get("evidence_refs"))
        errors.extend("g5t_%s" % reason for reason in ref_errors)
        matching_events = trace_by_key.get(key, []) if identity_valid else []
        matched = len(matching_events) == 1
        if not matched:
            errors.append("g5t_self_preservation_trace_check_missing_or_ambiguous:%s" %
                          (actor_id or "unknown"))
        defeat_reason = row.get("defeat_reason", row.get("defeatReason"))
        encounter_status = row.get("encounter_status", row.get("status"))
        current_hit_points = row.get("current_hit_points", row.get("currentHitPoints"))
        state_evidence_available = (
            isinstance(current_hit_points, (int, float)) and
            not isinstance(current_hit_points, bool)
        )
        snapshot_match_count: Optional[int] = None
        actor_name = actor_names.get(actor_id) if isinstance(actor_id, str) else None
        if isinstance(actor_name, str) and isinstance(after_creatures, list):
            snapshot_matches = [creature for creature in after_creatures
                                if isinstance(creature, dict) and
                                " ".join(str(creature.get("name", "")).split()).casefold() ==
                                " ".join(actor_name.split()).casefold()]
            snapshot_match_count = len(snapshot_matches)
            if len(snapshot_matches) == 1:
                persisted = snapshot_matches[0]
                defeat_reason = persisted.get("defeatReason")
                encounter_status = persisted.get("status")
                current_hit_points = persisted.get("currentHitPoints")
                state_evidence_available = True
        hp_consistent = (_g5_is_number(current_hit_points) and current_hit_points >= 0)
        snapshot_state_available = snapshot_match_count == 1
        encounter_state_consistent = (
            encounter_status == "defeated" and defeat_reason == outcome and hp_consistent
        )
        if state_evidence_available and not snapshot_state_available:
            # Recompute from the explicit check values as well; old captures may
            # carry a stale false flag produced by the former HP==0 predicate.
            encounter_state_consistent = bool(
                encounter_status == "defeated" and defeat_reason == outcome and hp_consistent
            )
        actor_removed, target_removed, satisfied_by_exit = (
            capture_evidence._g5t_self_preservation_menu_removal(
                trace_events, actor_id, batch_id,
                actor_name=actor_name,
                encounter_cleared=encounter_cleared,
                auto_exit_batches=auto_exit_batches,
            )
        )
        capture_row_status = row.get("status")
        if (defeat_reason != outcome or encounter_status not in (None, "defeated") or
                actor_removed is False or target_removed is False or
                encounter_state_consistent is False and state_evidence_available or
                snapshot_match_count == 0):
            row_status = "FAIL"
            errors.append("g5t_self_preservation_assertion_failed:%s" % (actor_id or "unknown"))
        elif (not matched or snapshot_match_count == 0 or snapshot_match_count is not None and
              snapshot_match_count > 1 or not state_evidence_available or
              not encounter_state_consistent or
              (not satisfied_by_exit and
               (not isinstance(actor_removed, bool) or not isinstance(target_removed, bool)))):
            row_status = "BLOCKED"
        else:
            # A stored row-level status is diagnostic only; this report
            # re-evaluates the persisted encounter and exit evidence directly.
            row_status = "PASS"
        if row_status == "BLOCKED":
            errors.append("g5t_self_preservation_observation_unavailable")
        if isinstance(outcome, str) and outcome in outcome_statuses:
            outcome_statuses[outcome][-1] = row_status
        removal_rows.append({"actor_id": actor_id, "outcome": outcome,
                             "defeat_reason": defeat_reason,
                             "encounter_status": encounter_status,
                              "current_hit_points": current_hit_points,
                              "actor_removed_from_later_actor_menus": actor_removed,
                              "actor_removed_from_later_target_menus": target_removed,
                              "satisfied_by_exit": satisfied_by_exit,
                             "encounter_state_consistent": encounter_state_consistent,
                             "capture_row_status": capture_row_status,
                             "status": row_status,
                             "trace_observed": matched, "evidence_refs": refs})
    for key, trace_rows in trace_by_key.items():
        if len(trace_rows) != 1 or key not in seen_removal_keys:
            errors.append("g5t_self_preservation_trace_check_missing_or_ambiguous:%s" % key[0])
            if key[1] in outcome_statuses and not outcome_statuses[key[1]]:
                outcome_statuses[key[1]].append("BLOCKED")
    if removal_check.get("status") == "NOT_OBSERVED":
        if self_events or raw_removals:
            errors.append("g5t_self_preservation_not_observed_status_mismatch")
    elif removal_check.get("status") == "PASS" and not raw_removals and not self_events:
        errors.append("g5t_self_preservation_observation_missing")
    elif removal_check.get("status") == "FAIL" and not raw_removals and not self_events:
        errors.append("g5t_self_preservation_check_failed")
    elif removal_check.get("status") == "BLOCKED" and not raw_removals and not self_events:
        errors.append("g5t_self_preservation_check_blocked")
    self_preservation_by_outcome = {
        outcome: ("NOT_OBSERVED" if not statuses else
                  "FAIL" if "FAIL" in statuses else
                  "BLOCKED" if "BLOCKED" in statuses else "PASS")
        for outcome, statuses in outcome_statuses.items()
    }
    if removal_check.get("status") == "NOT_OBSERVED":
        self_preservation_status = "NOT_OBSERVED"
    elif any(status == "FAIL" for status in self_preservation_by_outcome.values()):
        self_preservation_status = "FAIL"
    elif any(status == "BLOCKED" for status in self_preservation_by_outcome.values()):
        self_preservation_status = "BLOCKED"
    elif any(status == "PASS" for status in self_preservation_by_outcome.values()):
        self_preservation_status = "PASS"
    else:
        self_preservation_status = "BLOCKED"

    squad_check = _g5t_run_check(bundle, "commander_squad_follows_orders")
    errors.extend("g5t_%s" % reason for reason in squad_check.get("errors", []))
    squad_trace = _g5t_squad_followthrough(batch_rows)
    errors.extend(squad_trace.get("errors", []))
    capture_squad_status = squad_check.get("status")
    squad_status = squad_trace.get("status")
    if squad_check.get("errors"):
        # A present-but-BLOCKED aggregate may describe an intentionally skipped
        # post-exit row, but missing or invalid check evidence must still block.
        squad_status = "BLOCKED"
    elif capture_squad_status not in (squad_status, "BLOCKED"):
        errors.append("g5t_commander_squad_capture_check_mismatch")
        squad_status = "BLOCKED"
    squad_followed: Optional[bool] = (
        squad_trace.get("followed_orders")
        if squad_status in ("PASS", "FAIL") else None
    )
    if squad_status == "FAIL" or squad_followed is False:
        errors.append("g5t_commander_squad_followed_orders_not_pass")

    cover_derived = _g5t_derive_cover_checks(
        bundle, actor_names, before_creatures, after_creatures
    )
    cover_check = cover_derived["cover_check"]
    errors.extend(cover_derived["errors"])
    cover_observed = cover_check.get("observed", {})
    base_ac = cover_observed.get("base_ac")
    cover_bonus = cover_observed.get("cover_bonus")
    effective_ac = cover_observed.get("effective_ac")
    attack_effective_ac = cover_observed.get("attack_effective_ac")
    cover_values_valid = all(_g5_is_number(value) for value in
                              (base_ac, cover_bonus, effective_ac, attack_effective_ac))
    cover_events = cover_derived["cover_events"]
    cover_applied = cover_derived["cover_applied"]
    cover_expired = cover_derived["cover_expired"]
    if cover_check.get("status") == "NOT_OBSERVED":
        cover_effective: Optional[bool] = None
        cover_effective_status = "NOT_OBSERVED"
    elif cover_check.get("status") == "FAIL":
        cover_effective = False
        cover_effective_status = "FAIL"
        errors.append("g5t_cover_effective_ac_assertion_failed")
    elif cover_check.get("status") == "BLOCKED" or not cover_values_valid:
        cover_effective = None
        cover_effective_status = "BLOCKED"
        errors.append("g5t_cover_effective_ac_observation_missing")
    else:
        cover_effective = bool(
            cover_bonus in (2, 5) and effective_ac == base_ac + cover_bonus and
            attack_effective_ac == effective_ac
        )
        cover_effective_status = "PASS" if cover_effective else "FAIL"
        if not cover_effective:
            errors.append("g5t_cover_effective_ac_assertion_failed")

    expiration_check = cover_derived["expiration_check"]
    expiration_observed = expiration_check.get("observed", {})
    base_after = expiration_observed.get("base_ac")
    effective_after = expiration_observed.get("effective_ac_after_exit")
    expiration_values_valid = _g5_is_number(base_after) and _g5_is_number(effective_after)
    if expiration_check.get("status") == "NOT_OBSERVED":
        expiration_proven: Optional[bool] = None
        expiration_status = "NOT_OBSERVED"
    elif expiration_check.get("status") == "FAIL":
        expiration_proven = False
        expiration_status = "FAIL"
        errors.append("g5t_cover_expiration_assertion_failed")
    elif expiration_check.get("status") == "BLOCKED" or not expiration_values_valid:
        expiration_proven: Optional[bool] = None
        expiration_status = "BLOCKED"
        errors.append("g5t_cover_expiration_observation_missing")
    elif not cover_expired:
        expiration_proven = None
        expiration_status = "BLOCKED"
        errors.append("g5t_cover_expiration_trace_missing")
    else:
        expiration_proven = bool(
            expiration_observed.get("cover_inert_after_exit") is True and
            base_after == effective_after
        )
        expiration_status = "PASS" if expiration_proven else "FAIL"
        if not expiration_proven:
            errors.append("g5t_cover_expiration_assertion_failed")

    removal_flags: Dict[str, Optional[int]] = {}
    for required_outcome in ("fled", "surrendered"):
        outcome_status = self_preservation_by_outcome[required_outcome]
        removal_flags[required_outcome] = (
            1 if outcome_status == "PASS" else
            0 if outcome_status == "FAIL" else None
        )

    return {
        "status": "BLOCKED" if any("missing" in error or "unavailable" in error or
                                    "ambiguous" in error or "mismatch" in error or
                                    "invalid" in error or "malformed" in error for error in errors)
                  else "FAIL" if errors else "OBSERVED",
        "commander_squad_follows_orders": {
            "status": squad_status, "followed_orders": squad_followed,
            "issued_choice_count": squad_trace.get("issued_choice_count"),
            "applied_choice_count": squad_trace.get("applied_choice_count"),
            "observations": squad_trace.get("observations", []),
            "evidence_refs": squad_check.get("evidence_refs", []),
        },
        "self_preservation": removal_rows,
        "self_preservation_status": self_preservation_status,
        "self_preservation_by_outcome": self_preservation_by_outcome,
        "cover_effective_ac": {
            "status": cover_effective_status,
            "base_ac": base_ac, "cover_bonus": cover_bonus, "effective_ac": effective_ac,
            "attack_effective_ac": attack_effective_ac,
            "evidence_refs": cover_check.get("evidence_refs", []),
            "cover_applied_events": [{"actor_id": row.get("actor_id"),
                                      "feature_id": row.get("feature_id"),
                                      "cover_type": row.get("cover_type")}
                                     for row in cover_applied],
        },
        "cover_expiration": {
            "status": expiration_status,
            "cover_expired_events": [{"actor_id": row.get("actor_id"),
                                      "feature_id": row.get("feature_id"),
                                      "cover_type": row.get("cover_type")}
                                     for row in cover_expired],
            "base_ac": base_after, "effective_ac_after_exit": effective_after,
            "cover_inert_after_exit": expiration_observed.get("cover_inert_after_exit"),
            "active_combat_encounter_after_run": expiration_observed.get(
                "active_combat_encounter_after_run"),
            "evidence_refs": expiration_check.get("evidence_refs", []),
        },
        "errors": sorted(set(errors)),
        "blocking_errors": sorted(set(
            error for error in errors
            if any(marker in error for marker in
                   ("missing", "unavailable", "ambiguous", "mismatch", "invalid", "malformed"))
        )),
    }


def _g5t_run_inputs(runs_by_party: Any, party_size: int,
                    blocking_reasons: List[str], label: str) -> List[Any]:
    if not isinstance(runs_by_party, dict):
        blocking_reasons.append("%s_runs_by_party_unavailable" % label)
        return []
    values = runs_by_party.get(party_size, runs_by_party.get(str(party_size), []))
    if isinstance(values, (str, bytes, Path)):
        return [values]
    try:
        return list(values)
    except TypeError:
        blocking_reasons.append("%s_p%d_run_list_invalid" % (label, party_size))
        return []


def _g5t_add_target(targets: List[Dict[str, Any]], name: str, observed: Any,
                    operator: str, threshold: Any, reason: Optional[str] = None,
                    **fields: Any) -> Dict[str, Any]:
    row = _g5_check(name, observed, operator, threshold, reason)
    row.update(fields)
    targets.append(row)
    return row


def _g5t_optional_prefetch_report(prefetch_runs_by_party: Any,
                                  run_root: Optional[Path]) -> Dict[str, Any]:
    """Report background submissions, provider attempts and outcomes separately."""
    if prefetch_runs_by_party is None:
        return {"status": "NOT_RUN", "party_comparisons": [], "outcomes": {},
                "blocking_reasons": []}
    from scripts import capture_evidence

    root = (Path(run_root) if run_root is not None else
            capture_evidence.PROJECT_TMP / "router-rollout" / "g5t")
    if not root.is_absolute():
        root = capture_evidence.PROJECT_ROOT / root
    blocking_reasons: List[str] = []
    outcomes: Dict[str, int] = {}
    request_outcomes: Dict[str, int] = {}
    party_rows = []
    total_requests = 0
    total_provider_calls = 0
    total_provider_attempts = 0
    cap_violations: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_paths = set()
    for party_size in G5T_PARTY_SIZES:
        raw_runs = _g5t_run_inputs(prefetch_runs_by_party, party_size, blocking_reasons, "prefetch")
        if len(raw_runs) != G5T_RUNS_PER_PARTY:
            blocking_reasons.append("prefetch_p%d_requires_three_bundles" % party_size)
        run_rows = []
        for raw_path in raw_runs:
            bundle = _g5t_load_bundle(raw_path, run_root=root, expected_mode="prefetch")
            run_id = bundle.get("run_id") or "unknown_run"
            if bundle.get("party_size") not in (None, party_size):
                blocking_reasons.append("prefetch_p%d_party_size_mismatch:%s" % (party_size, run_id))
            if bundle.get("errors"):
                blocking_reasons.extend("prefetch:%s:%s" % (run_id, error)
                                        for error in bundle["errors"])
            if run_id in seen_ids or bundle.get("run_dir") in seen_paths:
                blocking_reasons.append("prefetch_duplicate_run_identity:%s" % run_id)
            seen_ids.add(run_id)
            seen_paths.add(bundle.get("run_dir"))
            observed = []
            submissions_by_batch: Dict[str, Dict[str, str]] = {}
            provider_calls_by_batch: Dict[str, Dict[str, str]] = {}
            provider_attempts_by_batch: Dict[str, Dict[str, str]] = {}
            outcomes_by_batch: Dict[str, List[Dict[str, Any]]] = {}
            for event in bundle.get("trace_events", []):
                if not isinstance(event, dict):
                    continue
                if (event.get("event_type") == "combat_observation" and
                        event.get("observation") == "combat_tactical_prefetch_status"):
                    value = event.get("prefetch_status")
                    raw_standing_outcome = event.get("standing_orders_outcome")
                    standing_outcome = (
                        raw_standing_outcome if isinstance(raw_standing_outcome, str)
                        and raw_standing_outcome in G5T_STANDING_ORDERS_TRACE_OUTCOMES else None
                    )
                    if raw_standing_outcome is not None and standing_outcome is None:
                        blocking_reasons.append(
                            "prefetch_standing_orders_outcome_invalid:%s" % run_id
                        )
                    status_value = (
                        value if isinstance(value, str)
                        and value in G5T_PREFETCH_TRACE_STATUSES else None
                    )
                    if (status_value is not None and
                            standing_outcome not in G5T_PREFETCH_SUBMISSION_OUTCOMES):
                        outcomes[status_value] = outcomes.get(status_value, 0) + 1
                    elif value is not None:
                        if status_value is None:
                            blocking_reasons.append("prefetch_status_invalid:%s" % run_id)
                    if standing_outcome is not None:
                        request_outcomes[standing_outcome] = (
                            request_outcomes.get(standing_outcome, 0) + 1
                        )
                    raw_batch_id = event.get("batch_id")
                    batch_id = (
                        raw_batch_id if isinstance(raw_batch_id, str)
                        and 0 < len(raw_batch_id) <= 128 else None
                    )
                    raw_request_kind = event.get("request_kind")
                    request_kind_value = (
                        raw_request_kind if isinstance(raw_request_kind, str)
                        and raw_request_kind in G5T_PREFETCH_REQUEST_KINDS else None
                    )
                    raw_receipt_id = event.get("receipt_correlation_id")
                    receipt_id_value = (
                        raw_receipt_id if isinstance(raw_receipt_id, str)
                        and 0 < len(raw_receipt_id) <= 128 else None
                    )
                    outcome_row = {
                        "batch_id": batch_id,
                        "prefetch_status": status_value,
                        "standing_orders_outcome": standing_outcome,
                        "request_kind": request_kind_value,
                        "request_site": (
                            G5T_PREFETCH_PROVIDER_SITE
                            if event.get("request_site") == G5T_PREFETCH_PROVIDER_SITE else None
                        ),
                        "receipt_correlation_id": receipt_id_value,
                    }
                    observed.append(outcome_row)
                    if batch_id is not None:
                        outcomes_by_batch.setdefault(batch_id, []).append(outcome_row)
                    elif standing_outcome in G5T_PREFETCH_SUBMISSION_OUTCOMES:
                        blocking_reasons.append(
                            "prefetch_submission_batch_missing:%s" % run_id
                        )

                    if standing_outcome not in G5T_PREFETCH_SUBMISSION_OUTCOMES:
                        continue
                    request_kind = request_kind_value
                    request_site = event.get("request_site")
                    receipt_id = receipt_id_value
                    if (batch_id is None
                            or request_kind is None
                            or request_site != G5T_PREFETCH_PROVIDER_SITE
                            or receipt_id is None):
                        blocking_reasons.append(
                            "prefetch_submission_attribution_missing:%s" % run_id
                        )
                        continue
                    batch_submissions = submissions_by_batch.setdefault(batch_id, {})
                    previous_kind = batch_submissions.get(receipt_id)
                    if previous_kind is not None:
                        blocking_reasons.append(
                            "prefetch_submission_identity_duplicate:%s:%s" % (run_id, batch_id)
                        )
                    else:
                        batch_submissions[receipt_id] = request_kind
                elif (event.get("event_type") == "provider" and
                      event.get("site") == G5T_PREFETCH_PROVIDER_SITE):
                    batch_id = event.get("batch_id")
                    request_kind = event.get("request_kind")
                    request_site = event.get("request_site")
                    call_id = event.get("call_id")
                    attempt_id = event.get("attempt_id")
                    if (not isinstance(batch_id, str) or not 0 < len(batch_id) <= 128
                            or not isinstance(request_kind, str)
                            or request_kind not in G5T_PREFETCH_REQUEST_KINDS
                            or request_site != G5T_PREFETCH_PROVIDER_SITE
                            or not isinstance(call_id, str) or not 0 < len(call_id) <= 128
                            or not isinstance(attempt_id, str)
                            or not 0 < len(attempt_id) <= 128):
                        blocking_reasons.append(
                            "prefetch_provider_attribution_missing:%s" % run_id
                        )
                        continue
                    batch_calls = provider_calls_by_batch.setdefault(batch_id, {})
                    previous_kind = batch_calls.get(call_id)
                    if previous_kind is not None and previous_kind != request_kind:
                        blocking_reasons.append(
                            "prefetch_provider_call_identity_ambiguous:%s:%s" % (run_id, batch_id)
                        )
                    else:
                        batch_calls[call_id] = request_kind
                    batch_attempts = provider_attempts_by_batch.setdefault(batch_id, {})
                    previous_call = batch_attempts.get(attempt_id)
                    if previous_call is not None and previous_call != call_id:
                        blocking_reasons.append(
                            "prefetch_provider_attempt_identity_ambiguous:%s:%s" % (run_id, batch_id)
                        )
                    else:
                        batch_attempts[attempt_id] = call_id

            batch_ids = sorted(set(submissions_by_batch) | set(provider_calls_by_batch)
                               | set(provider_attempts_by_batch) | set(outcomes_by_batch))
            batch_rows = []
            run_request_count = 0
            run_provider_call_count = 0
            run_provider_attempt_count = 0
            for batch_id in batch_ids:
                submissions = submissions_by_batch.get(batch_id, {})
                provider_calls = provider_calls_by_batch.get(batch_id, {})
                provider_attempts = provider_attempts_by_batch.get(batch_id, {})
                request_counts = {
                    kind: sum(1 for value in submissions.values() if value == kind)
                    for kind in sorted(G5T_PREFETCH_REQUEST_KINDS)
                }
                call_counts = {
                    kind: sum(1 for value in provider_calls.values() if value == kind)
                    for kind in sorted(G5T_PREFETCH_REQUEST_KINDS)
                }
                attempt_counts = {
                    kind: sum(
                        1 for attempt_id, call_id in provider_attempts.items()
                        if provider_calls.get(call_id) == kind
                    )
                    for kind in sorted(G5T_PREFETCH_REQUEST_KINDS)
                }
                request_count = len(submissions)
                provider_call_count = len(provider_calls)
                provider_attempt_count = len(provider_attempts)
                run_request_count += request_count
                run_provider_call_count += provider_call_count
                run_provider_attempt_count += provider_attempt_count
                if request_count > 2:
                    violation = {
                        "run_id": run_id, "party_size": party_size,
                        "batch_id": batch_id, "request_count": request_count,
                        "limit": 2,
                    }
                    cap_violations.append(violation)
                batch_rows.append({
                    "batch_id": batch_id,
                    "request_site": G5T_PREFETCH_PROVIDER_SITE,
                    "request_count": request_count,
                    "request_counts_by_kind": request_counts,
                    "provider_call_count": provider_call_count,
                    "provider_calls_by_kind": call_counts,
                    "provider_attempt_count": provider_attempt_count,
                    "provider_attempts_by_kind": attempt_counts,
                    "outcomes": outcomes_by_batch.get(batch_id, []),
                })
            total_requests += run_request_count
            total_provider_calls += run_provider_call_count
            total_provider_attempts += run_provider_attempt_count
            run_rows.append({"run_id": run_id, "run_dir": bundle.get("run_dir"),
                             "party_size": party_size, "outcomes": observed,
                             "batches": batch_rows,
                             "background_request_count": run_request_count,
                             "background_provider_call_count": run_provider_call_count,
                             "background_provider_attempt_count": run_provider_attempt_count,
                             "errors": bundle.get("errors", [])})
        party_rows.append({
            "party_size": party_size,
            "runs": run_rows,
            "background_request_count": sum(
                row["background_request_count"] for row in run_rows
            ),
            "background_provider_call_count": sum(
                row["background_provider_call_count"] for row in run_rows
            ),
            "background_provider_attempt_count": sum(
                row["background_provider_attempt_count"] for row in run_rows
            ),
        })
    if not outcomes and not request_outcomes:
        blocking_reasons.append("prefetch_lifecycle_observations_missing")
    if total_requests == 0:
        blocking_reasons.append("prefetch_request_submissions_missing")
    if cap_violations:
        status = "FAIL"
    elif blocking_reasons:
        status = "BLOCKED"
    else:
        status = "OBSERVED"
    return {"status": status, "party_comparisons": party_rows,
            "outcomes": {key: outcomes[key] for key in sorted(outcomes)},
            "request_outcomes": {
                key: request_outcomes[key] for key in sorted(request_outcomes)
            },
            "background_request_site": G5T_PREFETCH_PROVIDER_SITE,
            "background_request_count": total_requests,
            "background_provider_call_count": total_provider_calls,
            "background_provider_attempt_count": total_provider_attempts,
            "cap_violations": cap_violations,
            "blocking_reasons": sorted(set(blocking_reasons))}


def evaluate_g5t_comparison(
    after_runs_by_party: Dict[int, Iterable[Any]],
    prefetch_runs_by_party: Optional[Dict[int, Iterable[Any]]] = None,
    run_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluate G5T primary commander evidence and optionally report prefetch separately.

    Each primary party shape requires three isolated G5T run bundles. The
    party-level latency observation is the median of that run's observed
    commander-batch work-only values; the target is the median of the three
    run-level observations. Missing trace or capture observations remain
    unavailable and block rather than being treated as zero.
    """
    from scripts import capture_evidence

    root = (Path(run_root) if run_root is not None else
            capture_evidence.PROJECT_TMP / "router-rollout" / "g5t")
    if not root.is_absolute():
        root = capture_evidence.PROJECT_ROOT / root
    blocking_reasons: List[str] = []
    targets: List[Dict[str, Any]] = []
    party_comparisons: List[Dict[str, Any]] = []
    all_runs: List[Dict[str, Any]] = []
    seen_run_ids: Dict[str, int] = {}
    seen_paths: Dict[str, int] = {}

    for party_size in G5T_PARTY_SIZES:
        raw_runs = _g5t_run_inputs(after_runs_by_party, party_size, blocking_reasons, "primary")
        if len(raw_runs) != G5T_RUNS_PER_PARTY:
            blocking_reasons.append("p%d_primary_requires_exactly_three_bundles" % party_size)
        run_rows: List[Dict[str, Any]] = []
        run_level_values: List[Optional[float]] = []
        for raw_path in raw_runs:
            bundle = _g5t_load_bundle(raw_path, run_root=root, expected_mode="primary")
            run_id = bundle.get("run_id") or "unknown_run"
            run_path = bundle.get("run_dir", "")
            seen_paths[run_path] = seen_paths.get(run_path, 0) + 1
            if isinstance(bundle.get("run_id"), str):
                seen_run_ids[run_id] = seen_run_ids.get(run_id, 0) + 1
            if bundle.get("party_size") not in (None, party_size):
                blocking_reasons.append("p%d_primary_party_size_mismatch:%s" % (party_size, run_id))
            for error in bundle.get("errors", []):
                blocking_reasons.append("p%d_run:%s:%s" % (party_size, run_id, error))

            batch_rows = [_g5t_batch_observation(bundle, step)
                          for step in bundle.get("batch_steps", [])]
            for batch in batch_rows:
                for error in batch.get("errors", []):
                    blocking_reasons.append("p%d_run:%s:%s" % (party_size, run_id, error))
                observed_targets = []
                if batch.get("raw_file_write_status") != "NOT_APPLICABLE":
                    observed_targets.append((
                        "commander_batch_raw_file_writes", batch.get("raw_file_writes"),
                        "<=", batch.get("raw_file_write_limit"),
                    ))
                if not batch.get("deviation"):
                    observed_targets.extend([
                        ("commander_batch_provider_calls", batch.get("provider_calls"),
                         "<=", G5T_PROVIDER_CALL_LIMIT),
                        ("commander_batch_plan_provider_calls", batch.get("plan_provider_calls"),
                         "==", G5T_PLAN_CALLS),
                        ("commander_batch_narration_provider_calls", batch.get("narration_provider_calls"),
                         "==", G5T_NARRATION_CALLS),
                        ("commander_batch_validation_provider_calls", batch.get("validation_provider_calls"),
                         "==", G5T_VALIDATION_CALLS),
                    ])
                    if batch.get("applied_choice_legality_status") != "NOT_APPLICABLE":
                        observed_targets.append((
                            "applied_choice_legality_percent",
                            batch.get("applied_choice_legality_percent"), "==", 100.0,
                        ))
                for name, observed, operator, threshold in observed_targets:
                    reason = (
                        "batch_observation_unavailable"
                        if observed is None or threshold is None else None
                    )
                    _g5t_add_target(
                        targets, name, observed, operator, threshold, reason,
                        party_size=party_size, run_id=run_id,
                        work_unit_id=batch.get("unit_id"), batch_id=batch.get("batch_id"),
                        raw_observation=observed,
                    )

            timing_values = [row.get("work_only_ms") for row in batch_rows]
            run_latency = (_g5_summary(timing_values)
                           if timing_values and all(_g5_is_number(value) for value in timing_values)
                           else None)
            if run_latency is None:
                blocking_reasons.append("p%d_run:%s:g5t_run_level_work_only_latency_unavailable" %
                                        (party_size, run_id))
            run_level_values.append(run_latency)

            behavior = _g5t_run_behavior(bundle, batch_rows)
            if behavior.get("status") == "BLOCKED":
                blocking_reasons.extend("p%d_run:%s:%s" % (party_size, run_id, error)
                                        for error in behavior.get("errors", []))
            self_rows = behavior.get("self_preservation", [])

            behavior_flags = {
                "commander_squad_follows_orders": (
                    None if behavior.get("commander_squad_follows_orders", {}).get("followed_orders") is None
                    else int(behavior["commander_squad_follows_orders"]["followed_orders"])),
                "fled_actor_target_removal": (
                    1 if behavior.get("self_preservation_by_outcome", {}).get("fled") == "PASS" else
                    0 if behavior.get("self_preservation_by_outcome", {}).get("fled") == "FAIL" else None),
                "surrendered_actor_target_removal": (
                    1 if behavior.get("self_preservation_by_outcome", {}).get("surrendered") == "PASS" else
                    0 if behavior.get("self_preservation_by_outcome", {}).get("surrendered") == "FAIL" else None),
                "cover_effective_ac": (
                    1 if behavior.get("cover_effective_ac", {}).get("status") == "PASS" else
                    0 if behavior.get("cover_effective_ac", {}).get("status") == "FAIL" else None),
                "cover_expiration": (
                    1 if behavior.get("cover_expiration", {}).get("status") == "PASS" else
                    0 if behavior.get("cover_expiration", {}).get("status") == "FAIL" else None),
            }
            behavior_component_statuses = {
                "commander_squad_follows_orders": behavior.get(
                    "commander_squad_follows_orders", {}).get("status"),
                "fled_actor_target_removal": behavior.get("self_preservation_by_outcome", {}).get("fled"),
                "surrendered_actor_target_removal": behavior.get("self_preservation_by_outcome", {}).get("surrendered"),
                "cover_effective_ac": behavior.get("cover_effective_ac", {}).get("status"),
                "cover_expiration": behavior.get("cover_expiration", {}).get("status"),
            }
            for name, observed in behavior_flags.items():
                reason = None
                component_status = behavior_component_statuses.get(name)
                if component_status == "NOT_APPLICABLE":
                    continue
                if observed is None and component_status == "NOT_OBSERVED":
                    target = {
                        "target": name, "observed": None, "operator": "==",
                        "threshold": 1, "status": "NOT_OBSERVED",
                        "reason": "model_chosen_outcome_not_observed_in_run",
                        "party_size": party_size, "run_id": run_id,
                        "evidence": behavior.get(name, behavior.get("errors", [])),
                    }
                    targets.append(target)
                    continue
                if observed is None:
                    reason = "behavior_observation_unavailable"
                target = _g5t_add_target(
                    targets, name, observed, "==", 1, reason,
                    party_size=party_size, run_id=run_id,
                    evidence=behavior.get(name, behavior.get("errors", [])),
                )
                if target.get("status") == "FAIL" and behavior.get("status") == "FAIL":
                    # A measured failed assertion is a gate failure, not missing data.
                    pass

            prefetch_outcomes = sorted({status for row in batch_rows
                                        for status in row.get("prefetch_statuses", [])})
            exit_flow_calls = _g5t_exit_flow_provider_calls(bundle)
            run_row = {
                "run_id": run_id, "run_dir": run_path,
                "scenario_id": bundle.get("scenario_id"), "party_size": party_size,
                "provider": bundle.get("provider"), "model": bundle.get("model"),
                "source_digest": bundle.get("source_digest"),
                "batch_observations": [{key: value for key, value in row.items() if key != "_events"}
                                        for row in batch_rows],
                "exit_flow_provider_calls": exit_flow_calls,
                "run_level_work_only_ms": run_latency,
                "behavioral_evidence": behavior,
                "prefetch_outcomes": prefetch_outcomes,
                "errors": sorted(set(bundle.get("errors", []) +
                                      [error for row in batch_rows for error in row.get("errors", [])] +
                                      behavior.get("blocking_errors", []))),
            }
            run_rows.append(run_row)
            all_runs.append(run_row)

        if len(run_rows) == G5T_RUNS_PER_PARTY and len({row.get("run_id") for row in run_rows}) != G5T_RUNS_PER_PARTY:
            blocking_reasons.append("p%d_primary_run_ids_not_distinct" % party_size)
        if len(run_rows) == G5T_RUNS_PER_PARTY:
            outcome_keys = (
                "fled_actor_target_removal", "surrendered_actor_target_removal",
                "cover_effective_ac", "cover_expiration",
            )
            for outcome_key in outcome_keys:
                observed_once = False
                for run_row in run_rows:
                    behavior = run_row.get("behavioral_evidence", {})
                    if outcome_key == "fled_actor_target_removal":
                        status = behavior.get("self_preservation_by_outcome", {}).get("fled")
                    elif outcome_key == "surrendered_actor_target_removal":
                        status = behavior.get("self_preservation_by_outcome", {}).get("surrendered")
                    else:
                        status = behavior.get(outcome_key, {}).get("status")
                    if status in ("PASS", "FAIL"):
                        observed_once = True
                        break
                if not observed_once:
                    blocking_reasons.append(
                        "g5t_outcome_not_observed_across_runs:%s:p%d" %
                        (outcome_key, party_size)
                    )
        median_latency = (_g5_summary(run_level_values)
                          if len(run_level_values) == G5T_RUNS_PER_PARTY and
                          all(_g5_is_number(value) for value in run_level_values) else None)
        latency_target = _g5_check(
            "median_batch_work_only_ms", median_latency, "<=",
            G5T_MEDIAN_BATCH_WORK_ONLY_MS,
            "three_run_median_batch_work_only_unavailable" if median_latency is None else None,
        )
        latency_target.update({"party_size": party_size,
                               "run_values_ms": run_level_values,
                               "run_count": len(run_level_values),
                               "timing_source": "median_of_run_level_commander_batch_medians"})
        targets.append(latency_target)

        party_target_rows = [row for row in targets if row.get("party_size") == party_size]
        local_prefix = "p%d_run:" % party_size
        coverage_items = (
            "fled_actor_target_removal", "surrendered_actor_target_removal",
            "cover_effective_ac", "cover_expiration",
        )
        coverage_blocked = any(
            reason == "g5t_outcome_not_observed_across_runs:%s:p%d" %
            (item, party_size)
            for item in coverage_items for reason in blocking_reasons
        )
        party_blocked = (len(run_rows) != G5T_RUNS_PER_PARTY or
                         any(row.get("errors") for row in run_rows) or
                         any(reason.startswith(local_prefix) for reason in blocking_reasons) or
                         coverage_blocked)
        if party_blocked:
            party_status = "BLOCKED"
        elif any(row.get("status") == "BLOCKED" for row in party_target_rows):
            party_status = "BLOCKED"
        elif any(row.get("status") == "FAIL" for row in party_target_rows):
            party_status = "FAIL"
        else:
            party_status = "READY_FOR_PRIMARY_REVIEW"
        party_comparisons.append({
            "party_size": party_size, "status": party_status,
            "after_runs": run_rows,
            "run_level_work_only_ms": run_level_values,
            "median_batch_work_only_ms": median_latency,
            "commander_behavior_references": [
                {"run_id": row.get("run_id"), "behavioral_evidence": row.get("behavioral_evidence")}
                for row in run_rows
            ],
        })

    if any(count > 1 for count in seen_paths.values()):
        blocking_reasons.append("duplicate_g5t_bundle_path")
    if any(count > 1 for count in seen_run_ids.values()):
        blocking_reasons.append("duplicate_g5t_run_id")
    digests = {row.get("source_digest") for row in all_runs if row.get("source_digest")}
    if len(digests) != 1 or any(row.get("source_digest") is None for row in all_runs):
        blocking_reasons.append("g5t_runs_not_on_one_observed_source_revision")
    runtime_identities = {(row.get("provider"), row.get("model")) for row in all_runs
                          if row.get("provider") and row.get("model")}
    if len(runtime_identities) > 1:
        blocking_reasons.append("g5t_provider_or_model_identity_changed_between_runs")

    failed_targets = [row for row in targets if row.get("status") == "FAIL"]
    blocked_targets = [row for row in targets if row.get("status") == "BLOCKED"]
    if blocking_reasons or blocked_targets:
        automated_status = "BLOCKED"
    elif failed_targets:
        automated_status = "FAIL"
    else:
        automated_status = "READY_FOR_PRIMARY_REVIEW"
    for comparison in party_comparisons:
        if comparison.get("status") == "BLOCKED":
            continue
        local = [row for row in targets if row.get("party_size") == comparison["party_size"]]
        if any(row.get("status") == "BLOCKED" for row in local):
            comparison["status"] = "BLOCKED"
        elif any(row.get("status") == "FAIL" for row in local):
            comparison["status"] = "FAIL"

    prefetch = _g5t_optional_prefetch_report(prefetch_runs_by_party, root)
    return {
        "gate": "g5t", "automated_status": automated_status,
        "primary_verdict": "PENDING",
        "comparison_method": "three_run_g5t_commander_batch_observations",
        "fixed_targets": {
            "commander_batch_provider_calls": {"operator": "<=", "threshold": G5T_PROVIDER_CALL_LIMIT},
            "commander_batch_plan_provider_calls": {"operator": "==", "threshold": G5T_PLAN_CALLS},
            "commander_batch_narration_provider_calls": {"operator": "==", "threshold": G5T_NARRATION_CALLS},
            "commander_batch_validation_provider_calls": {"operator": "==", "threshold": G5T_VALIDATION_CALLS},
            "commander_batch_raw_file_writes": {
                "operator": "<=",
                "threshold": "2 + distinct characters whose canonical state changed",
            },
            "median_batch_work_only_ms": {"operator": "<=", "threshold": G5T_MEDIAN_BATCH_WORK_ONLY_MS},
            "applied_choice_legality_percent": {"operator": "==", "threshold": 100.0},
        },
        "party_comparisons": party_comparisons, "targets": targets,
        "commander_behavior_references": [
            {"run_id": row.get("run_id"), "party_size": row.get("party_size"),
             "references": row.get("behavioral_evidence")}
            for row in all_runs
        ],
        "optional_prefetch": prefetch,
        "target_misses": [{"target": row.get("target"), "party_size": row.get("party_size"),
                           "run_id": row.get("run_id"), "work_unit_id": row.get("work_unit_id"),
                           "observed": row.get("observed"), "threshold": row.get("threshold")}
                          for row in failed_targets],
        "blocking_reasons": sorted(set(blocking_reasons + [
            "required_g5t_metric_unavailable:%s:p%s" % (row.get("target"), row.get("party_size"))
            for row in blocked_targets
        ])),
    }


def render_g5t_comparison(report: Dict[str, Any]) -> str:
    """Render G5T absolute targets and behavior references independently of G5R."""
    lines = ["Combat G5T comparison [%s]" % report.get("automated_status", "BLOCKED"),
             "target | party | run | batch | observed | rule | status"]
    for row in report.get("targets", []):
        lines.append("%s | P%s | %s | %s | %s | %s %s | %s" % (
            row.get("target"), row.get("party_size", "-"), row.get("run_id", "-"),
            row.get("work_unit_id", row.get("batch_id", "-")),
            _value(row.get("observed")), row.get("operator"),
            _value(row.get("threshold")), row.get("status")))
    lines.append("Run-level work-only latency and medians")
    for party in report.get("party_comparisons", []):
        lines.append("  P%s runs=%s median_ms=%s" % (
            party.get("party_size"),
            ", ".join(_value(value) for value in party.get("run_level_work_only_ms", [])),
            _value(party.get("median_batch_work_only_ms"))))
        for run in party.get("after_runs", []):
            for batch in run.get("batch_observations", []):
                lines.append("  %s %s counted_calls=%s calls_by_site=%s writes=%s/%s latency_ms=%s plan=%s defaults=%s" % (
                    run.get("run_id"), batch.get("batch_id"),
                    _value(batch.get("counted_provider_calls", batch.get("provider_calls"))),
                    json.dumps(batch.get("provider_calls_by_site", {}), sort_keys=True),
                    _value(batch.get("raw_file_writes")), _value(batch.get("raw_file_write_limit")),
                    _value(batch.get("work_only_ms")),
                    _value(batch.get("tactical_plan_outcome")),
                    _value(batch.get("default_reasons"))))
            exit_flow = run.get("exit_flow_provider_calls", {})
            lines.append("  %s exit_flow_calls=%s by_batch=%s" % (
                run.get("run_id"), _value(exit_flow.get("total_calls")),
                json.dumps(exit_flow.get("by_batch", {}), sort_keys=True)))
            for call in exit_flow.get("calls", []):
                lines.append("    exit_flow %s %s purpose=%s elapsed_ms=%s attempt=%s" % (
                    call.get("batch_id", "unattributed"), call.get("site"),
                    call.get("purpose"), _value(call.get("elapsed_ms")),
                    call.get("attempt_id", call.get("call_id", "unavailable"))))
    optional = report.get("optional_prefetch", {})
    if optional.get("status", "NOT_RUN") == "NOT_RUN":
        lines.append("Optional prefetch [NOT_RUN]: {}")
    else:
        lines.append("Optional prefetch [%s]: background_requests=%s site=%s provider_calls=%s "
                     "provider_attempts=%s outcomes=%s request_outcomes=%s cap_violations=%s" % (
            optional.get("status"), _value(optional.get("background_request_count")),
            optional.get("background_request_site", "unavailable"),
            _value(optional.get("background_provider_call_count")),
            _value(optional.get("background_provider_attempt_count")),
            json.dumps(optional.get("outcomes", {}), sort_keys=True),
            json.dumps(optional.get("request_outcomes", {}), sort_keys=True),
            json.dumps(optional.get("cap_violations", []), sort_keys=True)))
        for party in optional.get("party_comparisons", []):
            for run in party.get("runs", []):
                for batch in run.get("batches", []):
                    lines.append("  prefetch P%s %s %s requests=%s by_kind=%s provider_calls=%s "
                                 "attempts=%s outcomes=%s" % (
                        party.get("party_size"), run.get("run_id"), batch.get("batch_id"),
                        _value(batch.get("request_count")),
                        json.dumps(batch.get("request_counts_by_kind", {}), sort_keys=True),
                        _value(batch.get("provider_call_count")),
                        _value(batch.get("provider_attempt_count")),
                        json.dumps(batch.get("outcomes", []), sort_keys=True)))
    if optional.get("blocking_reasons"):
        lines.append("Optional prefetch diagnostics: %s" % ", ".join(optional["blocking_reasons"]))
    if report.get("blocking_reasons"):
        lines.append("Blocking reasons: %s" % ", ".join(report["blocking_reasons"]))
    return "\n".join(lines)


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
    lines.append("Combat state observations: %d" % len(report.get("combat_observations", [])))
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
