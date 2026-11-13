# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Persist secret-free identity and qualification evidence for preflight runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.live_gate_preflight_safety import (
    SafetyConfigurationError,
    compare_invocation_identity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_GATE = "live-gate-preflight"
EVIDENCE_ROOT = Path("tmp/router-rollout")
REPORT_NAME = "preflight.json"
PF_CHECKS = (
    "PF1",
    "PF2",
    "PF3",
    "PF4",
    "PF5",
    "PF6",
    "PF7",
    "PF8",
    "PF9",
)
_SOURCE_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GATE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential|authorization|proxy)",
    re.IGNORECASE,
)
_MAX_REPORT_BYTES = 4_000_000
_MAX_RETAINED_EVIDENCE_BYTES = 2_000_000
_PROVIDER_FREE_FIELDS = (
    "upstream_provider_requests_delta",
    "provider_budget_used_delta",
    "live_attempts_used_delta",
    "reserve_activations_delta",
)
_TEARDOWN_FIELDS = (
    "host_stopped",
    "server_stopped",
    "port_8360_free",
    "port_8370_free",
    "shared_live_window_lock_released",
)


class PreflightEvidenceError(ValueError):
    """Raised when evidence paths or their atomic write cannot be trusted."""


def dependency_lock_sha256(
    path: str | Path | None = Path("requirements-lock.txt"),
) -> str:
    """Hash the exact in-repository dependency lock without persisting its bytes."""
    if path is None:
        raise PreflightEvidenceError("dependency lock path is missing")
    project = PROJECT_ROOT.resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project / candidate
    try:
        relative = candidate.relative_to(project)
    except ValueError as exc:
        raise PreflightEvidenceError("dependency lock path is outside the project") from exc
    if relative.name != "requirements-lock.txt" or ".." in relative.parts:
        raise PreflightEvidenceError("dependency lock path is invalid")
    _reject_symlink_components(project, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_REPORT_BYTES:
            raise PreflightEvidenceError("dependency lock file is invalid")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64_000)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise PreflightEvidenceError("dependency lock file is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def routing_identity_sha256(identity: Mapping[str, Any]) -> str:
    """Hash a canonical routing-policy projection after rejecting secret fields."""
    if not isinstance(identity, Mapping) or not identity:
        raise PreflightEvidenceError("routing identity is missing")
    _validate_secret_free_json(identity)
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def write_preflight_evidence(
    *,
    run_id: str,
    source_sha: Any,
    routing_identity: Any,
    intended_invocation: Any,
    observed_invocation: Any,
    row_report: Any,
    dependency_lock_path: str | Path | None = None,
    entrypoint_failure_code: str | None = None,
    gate: str = EVIDENCE_GATE,
) -> str:
    """Write one immutable, preflight-only report below the required evidence root.

    Invalid or incomplete observations are retained as BLOCKED evidence. The
    function does not run a host, acquire a lock, contact a provider, or book a
    live attempt.
    """
    report_path = _report_path(gate, run_id, create_parent=True)
    document = _build_preflight_document(
        gate=gate,
        run_id=run_id,
        source_sha=source_sha,
        dependency_lock_path=dependency_lock_path,
        routing_identity=routing_identity,
        intended_invocation=intended_invocation,
        observed_invocation=observed_invocation,
        row_report=row_report,
        entrypoint_failure_code=entrypoint_failure_code,
    )
    payload = _canonical_json(document) + b"\n"
    if len(payload) > _MAX_REPORT_BYTES:
        raise PreflightEvidenceError("preflight evidence exceeds the size limit")
    _write_new_atomic(report_path, payload)
    return report_path.relative_to(PROJECT_ROOT).as_posix()


def check_booking_eligibility(
    *,
    run_id: str,
    proposed_identity: Any,
    gate: str = EVIDENCE_GATE,
) -> dict[str, Any]:
    """Check exact identity against complete preflight evidence without booking."""
    try:
        report_path = _report_path(gate, run_id, create_parent=False)
        document = _read_json_file(report_path, _MAX_REPORT_BYTES)
    except PreflightEvidenceError:
        return {
            "status": "BLOCKED",
            "eligible": False,
            "identity_match": False,
            "mismatches": [],
            "reasons": ["preflight_evidence_missing_or_invalid"],
            "booking_ruling_issued": False,
            "live_gate_pass": False,
        }

    candidate, invalid_fields = _candidate_identity(proposed_identity)
    recorded = document.get("identity") if isinstance(document, Mapping) else None
    mismatches = list(invalid_fields)
    if isinstance(recorded, Mapping) and isinstance(candidate, Mapping):
        for field in (
            "source_sha",
            "dependency_lock_sha256",
            "routing_identity_sha256",
            "invocation_identity_sha256",
        ):
            if candidate.get(field) != recorded.get(field):
                mismatches.append(field)
    else:
        mismatches.extend(
            field
            for field in (
                "source_sha",
                "dependency_lock_sha256",
                "routing_identity_sha256",
                "invocation_identity_sha256",
            )
            if field not in mismatches
        )
    mismatches = sorted(set(mismatches))

    report_ready = _report_is_ready(document, gate=gate, run_id=run_id)
    eligible = report_ready and not mismatches
    reasons = []
    if not report_ready:
        reasons.append("preflight_report_not_ready")
    if mismatches:
        reasons.append("identity_mismatch_or_invalid")
    return {
        "status": "READY_FOR_BOOKING" if eligible else "BLOCKED",
        "eligible": eligible,
        "identity_match": not mismatches,
        "mismatches": mismatches,
        "reasons": reasons,
        "booking_ruling_issued": False,
        "live_gate_pass": False,
    }


def _build_preflight_document(
    *,
    gate: str,
    run_id: str,
    source_sha: Any,
    dependency_lock_path: str | Path | None,
    routing_identity: Any,
    intended_invocation: Any,
    observed_invocation: Any,
    row_report: Any,
    entrypoint_failure_code: str | None,
) -> dict[str, Any]:
    selected_source_sha = source_sha if _valid_sha(source_sha, _SOURCE_SHA) else None
    try:
        lock_sha256 = dependency_lock_sha256(dependency_lock_path)
    except PreflightEvidenceError:
        lock_sha256 = None
    try:
        route_sha256 = routing_identity_sha256(routing_identity)
    except (PreflightEvidenceError, TypeError, ValueError):
        route_sha256 = None

    invocation = _invocation_record(intended_invocation, observed_invocation)
    supervised_evidence = _is_supervised_row_report(row_report)
    row_report_mapping = (
        row_report
        if supervised_evidence and isinstance(row_report, Mapping)
        else {}
    )
    expected_row_ids = _frozen_row_ids()
    row_outcomes, row_shape_valid = _row_outcomes(
        row_report_mapping,
        expected_row_ids=expected_row_ids,
        run_id=run_id,
        gate=gate,
    )
    provider_free = _provider_free_result(row_report_mapping.get("provider_free"))
    identity_fields_valid = (
        selected_source_sha is not None
        and lock_sha256 is not None
        and route_sha256 is not None
        and invocation.get("sha256") is not None
        and invocation.get("status") == "matched"
    )
    source_matches_rows = (
        row_report_mapping.get("source_sha") == selected_source_sha
        and row_report_mapping.get("report_type") == "provider-free-row-preflight"
    )

    all_rows_completed = bool(expected_row_ids) and len(row_outcomes) == len(expected_row_ids)
    all_rows_completed = all_rows_completed and all(
        _row_is_complete(row) for row in row_outcomes
    )
    row_coverage_complete = (
        row_shape_valid
        and row_report_mapping.get("status") == "completed"
        and row_report_mapping.get("planned_row_count") == len(expected_row_ids)
        and row_report_mapping.get("planned_row_ids") == expected_row_ids
        and row_report_mapping.get("attempted_row_ids") == expected_row_ids
        and row_report_mapping.get("fully_covered_row_ids") == expected_row_ids
        and row_report_mapping.get("replacement_only_rows_activated") == []
        and all_rows_completed
    )
    fixture_resolution_complete = all(
        row.get("fixture_resolution_status") == "validated" for row in row_outcomes
    ) and row_coverage_complete
    lifecycle_profiles_complete = all(
        row.get("lifecycle_profile_status") == "matched" for row in row_outcomes
    ) and row_coverage_complete
    transport_complete = all(
        row.get("transport_status") == "completed"
        and row.get("first_exchange_status") == "completed"
        for row in row_outcomes
    ) and row_coverage_complete
    teardown_record = _teardown_from_rows(
        row_outcomes, complete=supervised_evidence and row_coverage_complete
    )
    infra_count = (
        0
        if supervised_evidence
        and row_coverage_complete
        and row_report_mapping.get("status") == "completed"
        else None
    )
    checks = {
        "PF1": _pf_status(invocation.get("status") == "matched", invocation.get("status")),
        "PF2": _pf_status(row_coverage_complete, row_report_mapping.get("attempted_row_ids")),
        "PF3": _pf_status(fixture_resolution_complete, row_report_mapping.get("row_results")),
        "PF4": _pf_status(lifecycle_profiles_complete, row_report_mapping.get("row_results")),
        "PF5": _pf_status(transport_complete, row_report_mapping.get("row_results")),
        "PF6": "MISSING",
        "PF7": _pf_status(
            row_coverage_complete and len(expected_row_ids) > 1,
            row_report_mapping.get("attempted_row_ids"),
        ),
        "PF8": _pf_status(
            identity_fields_valid and source_matches_rows,
            selected_source_sha,
        ),
        "PF9": teardown_record["status"],
    }
    pf_status = (
        "PASS"
        if all(check == "PASS" for check in checks.values())
        else "FAIL"
        if any(check == "FAIL" for check in checks.values())
        else "MISSING"
    )
    provider_status = provider_free.get("status")
    ready = (
        identity_fields_valid
        and source_matches_rows
        and supervised_evidence
        and pf_status == "PASS"
        and provider_status == "PASS"
        and infra_count == 0
        and teardown_record["status"] == "PASS"
        and row_coverage_complete
        and fixture_resolution_complete
        and lifecycle_profiles_complete
        and transport_complete
        and entrypoint_failure_code is None
    )
    return {
        "schema_version": 1,
        "report_type": "provider-free-live-gate-preflight",
        "preflight_only": True,
        "gate": gate,
        "run_id": run_id,
        "evidence_path": (
            EVIDENCE_ROOT / gate / run_id / "preflight" / REPORT_NAME
        ).as_posix(),
        "identity": {
            "status": "matched" if identity_fields_valid and source_matches_rows else "blocked",
            "source_sha": selected_source_sha,
            "dependency_lock_sha256": lock_sha256,
            "routing_identity_sha256": route_sha256,
            "invocation_identity_sha256": invocation.get("sha256"),
        },
        "execution_provenance": (
            "supervised-retained-evidence"
            if supervised_evidence
            else "unverified"
        ),
        "entrypoint_failure_code": _safe_code(entrypoint_failure_code),
        "invocation_identity": invocation,
        "row_coverage": {
            "status": "complete" if row_coverage_complete else "incomplete",
            "source_sha": row_report_mapping.get("source_sha")
            if _valid_sha(row_report_mapping.get("source_sha"), _SOURCE_SHA)
            else None,
            "planned_row_ids": expected_row_ids,
            "attempted_row_ids": _safe_row_id_list(
                row_report_mapping.get("attempted_row_ids"), expected_row_ids
            ),
            "row_outcomes": row_outcomes,
        },
        "provider_free": provider_free,
        "infrastructure_failure_count": infra_count,
        "pf_checks": checks,
        "pf_status": pf_status,
        "teardown": teardown_record,
        "preflight_status": "READY_FOR_BOOKING" if ready else "BLOCKED",
        "booking_eligible": ready,
        "booking_ruling_issued": False,
        "live_gate_pass": False,
        "pilot_evidence_written": False,
    }


def _row_outcomes(
    report: Mapping[str, Any],
    *,
    expected_row_ids: list[str],
    run_id: str,
    gate: str,
) -> tuple[list[dict[str, Any]], bool]:
    raw_rows = report.get("row_results")
    if not isinstance(raw_rows, list):
        raw_rows = []
    by_id: dict[str, Mapping[str, Any]] = {}
    valid = True
    for row in raw_rows:
        if not isinstance(row, Mapping):
            valid = False
            continue
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id not in expected_row_ids or row_id in by_id:
            valid = False
            continue
        by_id[row_id] = row
    outcomes: list[dict[str, Any]] = []
    for row_id in expected_row_ids:
        row = by_id.get(row_id)
        if row is None:
            outcomes.append(
                {
                    "row_id": row_id,
                    "status": "MISSING",
                    "failure_code": "row_outcome_missing",
                    "lifecycle_results": [],
                }
            )
            continue
        lifecycle_results: list[dict[str, Any]] = []
        raw_lifecycles = row.get("lifecycle_results")
        if isinstance(raw_lifecycles, list):
            for lifecycle in raw_lifecycles:
                if isinstance(lifecycle, Mapping):
                    lifecycle_results.append(
                        _sanitize_lifecycle_result(
                            lifecycle,
                            gate=gate,
                            run_id=run_id,
                        )
                    )
                else:
                    valid = False
        else:
            valid = False
        outcomes.append(
            {
                "row_id": row_id,
                "status": row.get("status")
                if row.get("status") in ("completed", "blocked", "transport_completed_unverified")
                else "invalid",
                "failure_code": _safe_code(row.get("failure_code")),
                "fixture_ids": _safe_fixture_id_list(row.get("fixture_ids")),
                "party_size": row.get("party_size")
                if type(row.get("party_size")) is int and row.get("party_size") in (1, 4)
                else None,
                "fixture_resolution_status": row.get("fixture_resolution")
                if row.get("fixture_resolution") in ("validated", "failed")
                else "missing",
                "transport_status": row.get("transport_status")
                if row.get("transport_status") in ("completed", "not_started", "incomplete")
                else "missing",
                "first_exchange_status": _exchange_status(row.get("first_exchange")),
                "lifecycle_profile_status": row.get("lifecycle_profile_status")
                if row.get("lifecycle_profile_status") in ("matched", "mismatched", "unverified")
                else "missing",
                "invocation_identity_status": _safe_identity_status(
                    row.get("invocation_identity")
                ),
                "lifecycle_results": lifecycle_results,
            }
        )
    return outcomes, valid


def _sanitize_lifecycle_result(
    result: Mapping[str, Any], *, gate: str, run_id: str
) -> dict[str, Any]:
    profile_check = result.get("profile_check")
    profile_status = (
        profile_check.get("status")
        if isinstance(profile_check, Mapping)
        and profile_check.get("status") in ("matched", "mismatched", "unverified")
        else "missing"
    )
    teardown = result.get("worker_teardown")
    teardown_summary = {
        field: teardown.get(field) is True if isinstance(teardown, Mapping) else False
        for field in (
            "server_stopped",
            "port_8360_free",
            "port_8370_free",
            "shared_live_window_lock_released",
            "guard_active",
        )
    }
    call_count = teardown.get("call_count") if isinstance(teardown, Mapping) else None
    if type(call_count) is not int or call_count < 0:
        call_count = None
    row_run_id = result.get("run_id")
    expected_evidence_path = (
        EVIDENCE_ROOT
        / gate
        / run_id
        / "preflight"
        / "rows"
        / str(row_run_id)
        / "profile-evidence.json"
    ).as_posix()
    evidence_path = result.get("retained_evidence_path")
    evidence_sha = result.get("retained_evidence_sha256")
    evidence_valid = (
        evidence_path == expected_evidence_path
        and isinstance(evidence_sha, str)
        and _SHA256.fullmatch(evidence_sha) is not None
        and _retained_evidence_matches(evidence_path, evidence_sha)
    )
    exchange = result.get("first_exchange")
    return {
        "fixture_id": result.get("fixture_id")
        if isinstance(result.get("fixture_id"), str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", result["fixture_id"])
        else None,
        "lifecycle": result.get("lifecycle")
        if result.get("lifecycle") in ("startup", "resume")
        else None,
        "run_id": row_run_id
        if isinstance(row_run_id, str) and _RUN_ID.fullmatch(row_run_id) is not None
        else None,
        "transport_status": result.get("transport_status")
        if result.get("transport_status") in ("completed", "incomplete")
        else "missing",
        "profile_status": profile_status,
        "first_exchange_status": _exchange_status(exchange),
        "sandbox_cleanup": result.get("sandbox_cleanup") is True,
        "worker_teardown": {**teardown_summary, "call_count": call_count},
        "retained_evidence_path": evidence_path if evidence_valid else None,
        "retained_evidence_sha256": evidence_sha if evidence_valid else None,
        "retained_evidence_status": "verified" if evidence_valid else "missing_or_invalid",
    }


def _row_is_complete(row: Mapping[str, Any]) -> bool:
    if set(row) != {
        "row_id",
        "status",
        "failure_code",
        "fixture_ids",
        "party_size",
        "fixture_resolution_status",
        "transport_status",
        "first_exchange_status",
        "lifecycle_profile_status",
        "invocation_identity_status",
        "lifecycle_results",
    }:
        return False
    lifecycle_results = row.get("lifecycle_results")
    if not isinstance(lifecycle_results, list) or not lifecycle_results:
        return False
    expected_lifecycles = {
        (fixture_id, lifecycle)
        for fixture_id in row.get("fixture_ids", [])
        if isinstance(fixture_id, str)
        for lifecycle in ("startup", "resume")
    }
    observed_lifecycles: list[tuple[str, str]] = []
    for item in lifecycle_results:
        if not isinstance(item, Mapping):
            return False
        fixture_id = item.get("fixture_id")
        lifecycle = item.get("lifecycle")
        if not isinstance(fixture_id, str) or lifecycle not in ("startup", "resume"):
            return False
        observed_lifecycles.append((fixture_id, lifecycle))
    if (
        not expected_lifecycles
        or len(observed_lifecycles) != len(expected_lifecycles)
        or set(observed_lifecycles) != expected_lifecycles
    ):
        return False
    return (
        row.get("status") == "completed"
        and row.get("failure_code") is None
        and isinstance(row.get("fixture_ids"), list)
        and bool(row.get("fixture_ids"))
        and all(
            isinstance(fixture_id, str)
            and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", fixture_id)
            is not None
            for fixture_id in row["fixture_ids"]
        )
        and type(row.get("party_size")) is int
        and row.get("party_size") in (1, 4)
        and row.get("fixture_resolution_status") == "validated"
        and row.get("transport_status") == "completed"
        and row.get("first_exchange_status") == "completed"
        and row.get("lifecycle_profile_status") == "matched"
        and row.get("invocation_identity_status") == "matched"
        and isinstance(lifecycle_results, list)
        and bool(lifecycle_results)
        and all(
            isinstance(item, Mapping)
            and set(item)
            == {
                "fixture_id",
                "lifecycle",
                "run_id",
                "transport_status",
                "profile_status",
                "first_exchange_status",
                "sandbox_cleanup",
                "worker_teardown",
                "retained_evidence_path",
                "retained_evidence_sha256",
                "retained_evidence_status",
            }
            and item.get("fixture_id") in row["fixture_ids"]
            and item.get("lifecycle") in ("startup", "resume")
            and isinstance(item.get("run_id"), str)
            and _RUN_ID.fullmatch(item["run_id"]) is not None
            and item.get("transport_status") == "completed"
            and item.get("profile_status") == "matched"
            and item.get("first_exchange_status") == "completed"
            and item.get("sandbox_cleanup") is True
            and item.get("retained_evidence_status") == "verified"
            and isinstance(item.get("worker_teardown"), Mapping)
            and set(item["worker_teardown"])
            == {
                "server_stopped",
                "port_8360_free",
                "port_8370_free",
                "shared_live_window_lock_released",
                "guard_active",
                "call_count",
            }
            and all(
                item["worker_teardown"].get(field) is True
                for field in (
                    "server_stopped",
                    "port_8360_free",
                    "port_8370_free",
                    "shared_live_window_lock_released",
                    "guard_active",
                )
            )
            and type(item["worker_teardown"].get("call_count")) is int
            and item["worker_teardown"]["call_count"] >= 0
            for item in lifecycle_results
        )
    )


def _provider_free_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"status": "MISSING", "counters": {}}
    counters: dict[str, int | None] = {}
    for field in _PROVIDER_FREE_FIELDS:
        count = value.get(field)
        counters[field] = count if type(count) is int and count >= 0 else None
    stub_calls = value.get("router_stub_calls")
    counters["router_stub_calls"] = (
        stub_calls if type(stub_calls) is int and stub_calls >= 0 else None
    )
    if any(counters[field] is None for field in _PROVIDER_FREE_FIELDS):
        status = "MISSING"
    elif any(counters[field] != 0 for field in _PROVIDER_FREE_FIELDS):
        status = "FAIL"
    elif counters["router_stub_calls"] is None:
        status = "MISSING"
    elif counters["router_stub_calls"] == 0:
        status = "FAIL"
    else:
        status = "PASS"
    return {"status": status, "counters": counters}


def _teardown_from_rows(
    rows: list[Mapping[str, Any]], *, complete: bool
) -> dict[str, Any]:
    lifecycle_results = [
        lifecycle
        for row in rows
        for lifecycle in row.get("lifecycle_results", [])
        if isinstance(lifecycle, Mapping)
    ]
    checks = {field: False for field in _TEARDOWN_FIELDS}
    if not lifecycle_results:
        return {"status": "MISSING", "checks": checks}

    worker_checks = {
        "server_stopped": all(
            isinstance(item.get("worker_teardown"), Mapping)
            and item["worker_teardown"].get("server_stopped") is True
            for item in lifecycle_results
        ),
        "port_8360_free": all(
            isinstance(item.get("worker_teardown"), Mapping)
            and item["worker_teardown"].get("port_8360_free") is True
            for item in lifecycle_results
        ),
        "port_8370_free": all(
            isinstance(item.get("worker_teardown"), Mapping)
            and item["worker_teardown"].get("port_8370_free") is True
            for item in lifecycle_results
        ),
        "shared_live_window_lock_released": all(
            isinstance(item.get("worker_teardown"), Mapping)
            and item["worker_teardown"].get("shared_live_window_lock_released") is True
            for item in lifecycle_results
        ),
    }
    checks.update(
        {
            "host_stopped": worker_checks["server_stopped"],
            "server_stopped": worker_checks["server_stopped"],
            "port_8360_free": worker_checks["port_8360_free"],
            "port_8370_free": worker_checks["port_8370_free"],
            "shared_live_window_lock_released": worker_checks[
                "shared_live_window_lock_released"
            ],
        }
    )
    explicit_failure = any(
        isinstance(item.get("worker_teardown"), Mapping)
        and any(
            item["worker_teardown"].get(field) is False
            for field in (
                "server_stopped",
                "port_8360_free",
                "port_8370_free",
                "shared_live_window_lock_released",
            )
        )
        for item in lifecycle_results
    )
    status = (
        "FAIL"
        if explicit_failure
        else "PASS"
        if complete and all(checks.values())
        else "MISSING"
    )
    return {"status": status, "checks": checks}


def _invocation_record(intended: Any, observed: Any) -> dict[str, Any]:
    if intended is None or observed is None:
        return {
            "status": "missing",
            "sha256": None,
            "fields_compared": [],
            "mismatches": [],
        }
    try:
        evidence = compare_invocation_identity(intended, observed)
        digest = _invocation_sha256(intended)
    except (SafetyConfigurationError, TypeError, ValueError):
        return {
            "status": "invalid",
            "sha256": None,
            "fields_compared": [],
            "mismatches": [],
        }
    return {
        "status": evidence["status"],
        "sha256": digest,
        "fields_compared": list(evidence["fields_compared"]),
        "mismatches": [
            {key: value for key, value in mismatch.items() if key == "field"}
            for mismatch in evidence["mismatches"]
        ],
    }


def _invocation_sha256(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise PreflightEvidenceError("invocation identity is invalid")
    normalized = {
        "command": list(value["command"]),
        "working_directory": value["working_directory"],
        "pythonpath": value["pythonpath"],
    }
    return hashlib.sha256(_canonical_json(normalized)).hexdigest()


def _candidate_identity(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    fields = (
        "source_sha",
        "dependency_lock_sha256",
        "routing_identity",
        "invocation_identity",
    )
    if not isinstance(value, Mapping) or set(value) != set(fields):
        return None, list(fields)
    result: dict[str, Any] = {}
    invalid: list[str] = []
    if _valid_sha(value.get("source_sha"), _SOURCE_SHA):
        result["source_sha"] = value["source_sha"]
    else:
        invalid.append("source_sha")
    lock_sha = value.get("dependency_lock_sha256")
    if _valid_sha(lock_sha, _SHA256):
        result["dependency_lock_sha256"] = lock_sha
    else:
        invalid.append("dependency_lock_sha256")
    try:
        result["routing_identity_sha256"] = routing_identity_sha256(
            value.get("routing_identity")
        )
    except (PreflightEvidenceError, TypeError, ValueError):
        invalid.append("routing_identity_sha256")
    try:
        compare_invocation_identity(
            value.get("invocation_identity"), value.get("invocation_identity")
        )
        result["invocation_identity_sha256"] = _invocation_sha256(
            value.get("invocation_identity")
        )
    except (SafetyConfigurationError, PreflightEvidenceError, TypeError, ValueError):
        invalid.append("invocation_identity_sha256")
    return result, invalid


def _report_is_ready(document: Any, *, gate: str, run_id: str) -> bool:
    if not isinstance(document, Mapping):
        return False
    identity = document.get("identity")
    invocation = document.get("invocation_identity")
    coverage = document.get("row_coverage")
    rows = coverage.get("row_outcomes") if isinstance(coverage, Mapping) else None
    expected = _frozen_row_ids()
    if (
        not expected
        or _contains_sensitive_field(document)
        or set(document)
        != {
            "schema_version",
            "report_type",
            "preflight_only",
            "gate",
            "run_id",
            "evidence_path",
            "identity",
            "execution_provenance",
            "entrypoint_failure_code",
            "invocation_identity",
            "row_coverage",
            "provider_free",
            "infrastructure_failure_count",
            "pf_checks",
            "pf_status",
            "teardown",
            "preflight_status",
            "booking_eligible",
            "booking_ruling_issued",
            "live_gate_pass",
            "pilot_evidence_written",
        }
        or type(document.get("schema_version")) is not int
        or document.get("schema_version") != 1
        or document.get("report_type") != "provider-free-live-gate-preflight"
        or document.get("preflight_only") is not True
        or document.get("gate") != gate
        or document.get("run_id") != run_id
        or document.get("evidence_path")
        != (EVIDENCE_ROOT / gate / run_id / "preflight" / REPORT_NAME).as_posix()
        or document.get("preflight_status") != "READY_FOR_BOOKING"
        or document.get("booking_eligible") is not True
        or document.get("booking_ruling_issued") is not False
        or document.get("live_gate_pass") is not False
        or document.get("pilot_evidence_written") is not False
        or document.get("pf_status") != "PASS"
        or document.get("entrypoint_failure_code") is not None
        or not isinstance(identity, Mapping)
        or set(identity)
        != {
            "status",
            "source_sha",
            "dependency_lock_sha256",
            "routing_identity_sha256",
            "invocation_identity_sha256",
        }
        or identity.get("status") != "matched"
        or any(
            not _valid_sha(identity.get(field), pattern)
            for field, pattern in (
                ("source_sha", _SOURCE_SHA),
                ("dependency_lock_sha256", _SHA256),
                ("routing_identity_sha256", _SHA256),
                ("invocation_identity_sha256", _SHA256),
            )
        )
        or not isinstance(invocation, Mapping)
        or set(invocation)
        != {"status", "sha256", "fields_compared", "mismatches"}
        or invocation.get("status") != "matched"
        or invocation.get("sha256") != identity.get("invocation_identity_sha256")
        or invocation.get("fields_compared")
        != ["command", "working_directory", "pythonpath"]
        or invocation.get("mismatches") != []
        or not isinstance(coverage, Mapping)
        or set(coverage)
        != {
            "status",
            "source_sha",
            "planned_row_ids",
            "attempted_row_ids",
            "row_outcomes",
        }
        or coverage.get("status") != "complete"
        or coverage.get("source_sha") != identity.get("source_sha")
        or coverage.get("planned_row_ids") != expected
        or coverage.get("attempted_row_ids") != expected
        or not isinstance(rows, list)
        or len(rows) != len(expected)
        or [row.get("row_id") for row in rows if isinstance(row, Mapping)] != expected
        or any(not isinstance(row, Mapping) or not _row_is_complete(row) for row in rows)
        or type(document.get("infrastructure_failure_count")) is not int
        or document.get("infrastructure_failure_count") != 0
        or not isinstance(document.get("provider_free"), Mapping)
        or document["provider_free"].get("status") != "PASS"
        or not _provider_free_is_complete(document["provider_free"])
        or not isinstance(document.get("teardown"), Mapping)
        or document["teardown"].get("status") != "PASS"
        or not _teardown_is_complete(document["teardown"])
        or not isinstance(document.get("pf_checks"), Mapping)
        or set(document["pf_checks"]) != set(PF_CHECKS)
        or any(document["pf_checks"].get(check) != "PASS" for check in PF_CHECKS)
        or document.get("execution_provenance") != "supervised-retained-evidence"
    ):
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        for lifecycle in row.get("lifecycle_results", []):
            if not isinstance(lifecycle, Mapping):
                return False
            evidence_path = lifecycle.get("retained_evidence_path")
            expected_path = (
                EVIDENCE_ROOT
                / gate
                / run_id
                / "preflight"
                / "rows"
                / str(lifecycle.get("run_id"))
                / "profile-evidence.json"
            ).as_posix()
            if (
                evidence_path != expected_path
                or lifecycle.get("retained_evidence_status") != "verified"
                or not _retained_evidence_matches(
                    evidence_path, lifecycle.get("retained_evidence_sha256")
                )
            ):
                return False
    return True


def _provider_free_is_complete(value: Mapping[str, Any]) -> bool:
    counters = value.get("counters")
    return (
        set(value) == {"status", "counters"}
        and isinstance(counters, Mapping)
        and set(counters) == {*_PROVIDER_FREE_FIELDS, "router_stub_calls"}
        and all(type(counters.get(field)) is int and counters[field] == 0 for field in _PROVIDER_FREE_FIELDS)
        and type(counters.get("router_stub_calls")) is int
        and counters["router_stub_calls"] > 0
    )


def _teardown_is_complete(value: Mapping[str, Any]) -> bool:
    checks = value.get("checks")
    return (
        set(value) == {"status", "checks"}
        and isinstance(checks, Mapping)
        and set(checks) == set(_TEARDOWN_FIELDS)
        and all(checks.get(field) is True for field in _TEARDOWN_FIELDS)
    )


def _contains_sensitive_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            not isinstance(key, str)
            or _SECRET_FIELD.search(key) is not None
            or _contains_sensitive_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_field(child) for child in value)
    return False


def _is_supervised_row_report(value: Any) -> bool:
    try:
        from scripts import live_gate_preflight_controller as controller
    except ImportError:
        return False
    return (
        type(value) is controller._SupervisedPreflightReport
        and getattr(value, "_attestation", None)
        is controller._SUPERVISED_REPORT_TOKEN
        and value.get("execution_provenance") == "supervised-retained-evidence"
    )


def _report_path(gate: str, run_id: str, *, create_parent: bool) -> Path:
    if not isinstance(gate, str) or _GATE_ID.fullmatch(gate) is None:
        raise PreflightEvidenceError("preflight gate identity is invalid")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise PreflightEvidenceError("preflight run identity is invalid")
    project = PROJECT_ROOT.resolve(strict=True)
    if (project / "tmp").is_symlink():
        raise PreflightEvidenceError("project tmp directory is unsafe")
    relative = EVIDENCE_ROOT / gate / run_id / "preflight"
    directory = project / relative
    if create_parent:
        cursor = project
        for part in relative.parts:
            cursor = cursor / part
            try:
                cursor.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise PreflightEvidenceError("preflight evidence directory is unavailable") from exc
            try:
                metadata = cursor.lstat()
            except OSError as exc:
                raise PreflightEvidenceError("preflight evidence directory is unavailable") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise PreflightEvidenceError("preflight evidence path is unsafe")
    else:
        _reject_symlink_components(project, relative)
        if not directory.is_dir():
            raise PreflightEvidenceError("preflight evidence directory is unavailable")
    return directory / REPORT_NAME


def _write_new_atomic(path: Path, payload: bytes) -> None:
    temporary = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise PreflightEvidenceError("preflight evidence write was incomplete")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(temporary, path)
        os.unlink(temporary)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise PreflightEvidenceError("preflight evidence already exists") from exc
    except OSError as exc:
        raise PreflightEvidenceError("preflight evidence atomic write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json_file(path: Path, maximum_bytes: int) -> dict[str, Any]:
    try:
        relative = path.relative_to(PROJECT_ROOT.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PreflightEvidenceError("preflight evidence path is invalid") from exc
    _reject_symlink_components(PROJECT_ROOT.resolve(strict=True), relative)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
            or metadata.st_size < 1
            or metadata.st_size > maximum_bytes
            or (callable(get_uid) and metadata.st_uid != get_uid())
        ):
            raise PreflightEvidenceError("preflight evidence file is invalid")
        data = bytearray()
        while len(data) <= maximum_bytes:
            chunk = os.read(descriptor, min(64_000, maximum_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > maximum_bytes:
            raise PreflightEvidenceError("preflight evidence file is too large")
        parsed = json.loads(
            data.decode("ascii"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(parsed, dict):
            raise PreflightEvidenceError("preflight evidence document is invalid")
        return parsed
    except PreflightEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PreflightEvidenceError("preflight evidence cannot be read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _retained_evidence_matches(path_value: Any, expected_sha256: Any) -> bool:
    if (
        not isinstance(path_value, str)
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
    ):
        return False
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    try:
        project = PROJECT_ROOT.resolve(strict=True)
        _reject_symlink_components(project, relative)
        descriptor = os.open(
            project / relative, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o077
                or metadata.st_size < 1
                or metadata.st_size > _MAX_RETAINED_EVIDENCE_BYTES
            ):
                return False
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 64_000)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest() == expected_sha256
        finally:
            os.close(descriptor)
    except (OSError, PreflightEvidenceError, RuntimeError, ValueError):
        return False


def _reject_symlink_components(root: Path, relative: Path) -> None:
    if relative.is_absolute() or ".." in relative.parts:
        raise PreflightEvidenceError("preflight evidence path is invalid")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PreflightEvidenceError("preflight evidence path is invalid") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PreflightEvidenceError("preflight evidence path traverses a symlink")


def _frozen_row_ids() -> list[str]:
    try:
        from scripts.live_gate_preflight_controller import _load_frozen_row_ids

        rows, _reserves = _load_frozen_row_ids(None)
    except Exception:
        return []
    return [str(row["row_id"]) for row in rows]


def _safe_row_id_list(value: Any, expected: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return [row_id for row_id in value if isinstance(row_id, str) and row_id in expected]


def _safe_fixture_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", item)
    ]


def _safe_identity_status(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "missing"
    status = value.get("status")
    return status if status in ("matched", "blocked") else "invalid"


def _exchange_status(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "missing"
    status = value.get("status")
    return status if status in ("completed", "failed") else "missing"


def _safe_code(value: Any) -> str | None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) is None:
        return None
    return value


def _pf_status(condition: bool, evidence: Any) -> str:
    if condition:
        return "PASS"
    return "MISSING" if evidence is None else "FAIL"


def _valid_sha(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _validate_secret_free_json(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise PreflightEvidenceError("routing identity nesting is too deep")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_FIELD.search(key):
                raise PreflightEvidenceError("routing identity contains a sensitive field")
            _validate_secret_free_json(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_secret_free_json(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    raise PreflightEvidenceError("routing identity contains a non-JSON value")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PreflightEvidenceError("preflight evidence is not canonical JSON") from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")
