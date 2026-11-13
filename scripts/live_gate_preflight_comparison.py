# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Compare offline row-result snapshots for the frozen SP3 source set.

This utility never resolves a Git ref, fetches, launches a checkout or host,
books a run, contacts a provider, touches a port, or writes evidence. It checks
local commit-object availability with lazy fetching disabled. The caller must
pass the full SHA frozen by separate origin/main preparation. Both source
snapshots are read from project-relative tmp/ and must contain digest-bound
outcomes for the same 26 planned rows. Each row-results.json records schema
version, snapshot role, source SHA, the frozen counterbalance digest, exact
planned/reserve identities, and ordered row outcomes. Outcome digests computed
by row_outcome_sha256() validate internal consistency only; they do not attest
that a guarded host ran. Until retained per-source run evidence is reconciled,
well-formed snapshots are diagnostic-only and always remain BLOCKED. Only the
seven expected old-control NameErrors are exposed; other exception details are
ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
OLD_CONTROL_SHA = "5999af374ded4f56b21b25d68fc10f9520444b51"
PLANNING_BASE_SHA = "8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624"
EXPECTED_NAMEERROR_ROWS = ("E06", "E13", "E14", "E15", "E16", "E17", "E18")
EXPECTED_RESERVE_ROWS = ("R01", "R02", "R03", "R04")
SNAPSHOT_ROOT = Path(
    "tmp/router-rollout/live-gate-preflight/comparison/snapshots"
)
SNAPSHOT_NAME = "row-results.json"
SNAPSHOT_TYPE = "live-gate-preflight-comparison-snapshot"
REPORT_TYPE = "offline-live-gate-preflight-comparison"
MAX_SNAPSHOT_BYTES = 4_000_000
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID = re.compile(r"^(?:E[0-9]{2}|C[0-9]{2})$")


class ComparisonError(ValueError):
    """A safe, structured fail-closed comparison error."""

    def __init__(self, code: str, *, affected_rows: Sequence[str] = ()) -> None:
        self.code = code
        self.affected_rows = tuple(affected_rows)
        super().__init__(code)


@dataclass(frozen=True)
class FrozenRowSource:
    """Authoritative planned/reserve row identities and source digest."""

    planned_row_ids: tuple[str, ...]
    reserve_row_ids: tuple[str, ...]
    counterbalance_sha256: str


def row_outcome_sha256(
    *,
    source_sha: str,
    row_source_sha256: str,
    row_id: str,
    outcome: str,
    exception_type: str | None,
) -> str:
    """Return the canonical integrity digest for one frozen-row outcome."""
    canonical = {
        "schema_version": 1,
        "source_sha": source_sha,
        "row_source_sha256": row_source_sha256,
        "row_id": row_id,
        "outcome": outcome,
        "exception_type": exception_type,
    }
    try:
        payload = json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ComparisonError("row_outcome_digest_input_invalid") from exc
    return hashlib.sha256(payload).hexdigest()


def load_frozen_row_source() -> FrozenRowSource:
    """Load the manifest-verified frozen counterbalance without side effects."""
    from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT, verify_manifest

    try:
        manifest_entries = verify_manifest(DEFAULT_PREREG_ROOT)
        counterbalance_path = DEFAULT_PREREG_ROOT / "counterbalance.json"
        raw = counterbalance_path.read_bytes()
        counterbalance_sha256 = hashlib.sha256(raw).hexdigest()
        if manifest_entries.get("counterbalance.json") != counterbalance_sha256:
            raise ComparisonError("frozen_counterbalance_hash_mismatch")
        document = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ComparisonError:
        raise
    except Exception as exc:
        raise ComparisonError("frozen_row_source_unavailable") from exc

    if not isinstance(document, Mapping):
        raise ComparisonError("frozen_row_source_invalid")
    rows = document.get("rows")
    if (
        type(document.get("planned_rows")) is not int
        or document.get("planned_rows") != 26
        or type(document.get("reserve_rows")) is not int
        or document.get("reserve_rows") != 4
        or type(document.get("total_rows")) is not int
        or document.get("total_rows") != 30
        or not isinstance(rows, list)
        or len(rows) != 30
    ):
        raise ComparisonError("frozen_row_source_counts_invalid")

    planned: list[tuple[int, str]] = []
    reserves: list[tuple[int, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ComparisonError("frozen_row_source_row_invalid")
        row_id = row.get("row_id")
        run_order = row.get("run_order")
        if (
            not isinstance(row_id, str)
            or not isinstance(run_order, int)
            or isinstance(run_order, bool)
            or row_id in seen
        ):
            raise ComparisonError("frozen_row_source_identity_invalid")
        seen.add(row_id)
        if row.get("row_type") == "planned":
            if _ROW_ID.fullmatch(row_id) is None or row_id.startswith("R"):
                raise ComparisonError("frozen_planned_row_identity_invalid")
            planned.append((run_order, row_id))
        elif row.get("row_type") == "replacement_only":
            if not row_id.startswith("R"):
                raise ComparisonError("frozen_reserve_row_identity_invalid")
            reserves.append((run_order, row_id))
        else:
            raise ComparisonError("frozen_row_type_invalid")

    planned.sort()
    reserves.sort()
    planned_ids = tuple(row_id for _order, row_id in planned)
    reserve_ids = tuple(row_id for _order, row_id in reserves)
    if (
        len(planned_ids) != 26
        or tuple(order for order, _row_id in planned) != tuple(range(1, 27))
        or reserve_ids != EXPECTED_RESERVE_ROWS
        or tuple(order for order, _row_id in reserves) != (27, 28, 29, 30)
    ):
        raise ComparisonError("frozen_row_source_order_invalid")
    return FrozenRowSource(
        planned_row_ids=planned_ids,
        reserve_row_ids=reserve_ids,
        counterbalance_sha256=counterbalance_sha256,
    )


def load_lifecycle_profile_coverage(main_sha: str) -> Mapping[str, Any]:
    """Load current-main-bound preflight profiles using the existing validator."""
    from scripts.live_gate_preflight_profiles import load_profile_coverage

    return load_profile_coverage(expected_source_sha=main_sha)


def compare_local_snapshots(
    main_sha: str,
    *,
    row_source_loader: Callable[[], FrozenRowSource] | None = None,
    profile_coverage_loader: Callable[[str], Mapping[str, Any]] | None = None,
    commit_availability_loader: Callable[[str], bool] | None = None,
    snapshot_reader: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Validate offline snapshot diagnostics without attesting host execution.

    Injectable readers make the contract hermetic-testable. There is no host
    execution, network/fetch, Git-ref lookup, evidence-writing, booking, or port
    boundary; local commit availability uses a read-only Git object query.
    Self-authored snapshot digests are not retained run evidence, so this public
    function can return diagnostics but cannot return a verified comparison.
    """
    _validate_main_sha(main_sha)
    load_rows = row_source_loader or load_frozen_row_source
    load_profiles = profile_coverage_loader or load_lifecycle_profile_coverage
    check_commit = commit_availability_loader or _local_commit_available
    read_snapshot = snapshot_reader or _local_snapshot_reader

    try:
        row_source = load_rows()
    except ComparisonError:
        raise
    except Exception as exc:
        raise ComparisonError("frozen_row_source_unavailable") from exc
    _validate_row_source(row_source)

    try:
        profile_coverage = load_profiles(main_sha)
    except Exception as exc:
        raise ComparisonError("lifecycle_profile_coverage_unavailable") from exc
    _require_complete_profiles(profile_coverage, row_source)

    for source_sha in (OLD_CONTROL_SHA, main_sha):
        try:
            locally_available = check_commit(source_sha)
        except Exception as exc:
            raise ComparisonError("source_commit_unavailable_locally") from exc
        if locally_available is not True:
            raise ComparisonError("source_commit_unavailable_locally")

    old_document, old_snapshot_sha = _read_and_validate_snapshot(
        OLD_CONTROL_SHA,
        expected_role="pre-105-control",
        row_source=row_source,
        expected_row_ids=row_source.planned_row_ids,
        snapshot_reader=read_snapshot,
    )
    main_document, main_snapshot_sha = _read_and_validate_snapshot(
        main_sha,
        expected_role="frozen-origin-main",
        row_source=row_source,
        expected_row_ids=row_source.planned_row_ids,
        snapshot_reader=read_snapshot,
    )

    old_rows = _index_and_validate_outcomes(old_document, row_source)
    main_rows = _index_and_validate_outcomes(main_document, row_source)
    expected_errors = set(EXPECTED_NAMEERROR_ROWS)
    missing_errors = tuple(
        row_id
        for row_id in EXPECTED_NAMEERROR_ROWS
        if not _is_nameerror(old_rows[row_id])
    )
    if missing_errors:
        raise ComparisonError(
            "expected_old_control_nameerror_missing", affected_rows=missing_errors
        )

    current_nameerrors = tuple(
        row_id
        for row_id in EXPECTED_NAMEERROR_ROWS
        if _is_nameerror(main_rows[row_id])
    )
    if current_nameerrors:
        raise ComparisonError(
            "frozen_main_nameerror_present", affected_rows=current_nameerrors
        )

    unexpected_nameerrors = tuple(
        row_id
        for row_id in row_source.planned_row_ids
        if row_id not in expected_errors
        and (_is_nameerror(old_rows[row_id]) or _is_nameerror(main_rows[row_id]))
    )
    if unexpected_nameerrors:
        raise ComparisonError(
            "unexpected_nameerror_outside_target_rows",
            affected_rows=unexpected_nameerrors,
        )

    name_errors = [
        {
            "row_id": row_id,
            "exception_type": "NameError",
            "outcome_sha256": old_rows[row_id]["outcome_sha256"],
        }
        for row_id in EXPECTED_NAMEERROR_ROWS
    ]
    return {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "status": "BLOCKED",
        "comparison_verified": False,
        "error_code": "retained_source_execution_verification_missing",
        "old_control_source_sha": OLD_CONTROL_SHA,
        "frozen_origin_main_sha": main_sha,
        "row_source_sha256": row_source.counterbalance_sha256,
        "planned_row_count": 26,
        "replacement_only_row_ids": list(row_source.reserve_row_ids),
        "replacement_only_rows_activated": [],
        "diagnostic_only": True,
        "host_execution_verified": False,
        "retained_source_verification": "MISSING",
        "guarded_per_source_run_reconciliation": "MISSING",
        "snapshot_diagnostics": {
            "snapshot_structure_validated": True,
            "old_control_snapshot_sha256": old_snapshot_sha,
            "frozen_main_snapshot_sha256": main_snapshot_sha,
            "claimed_old_control_nameerror_rows": [
                item["row_id"] for item in name_errors
            ],
            "claimed_frozen_main_nameerror_rows": [],
            "claimed_unexpected_nameerror_rows": [],
            "planned_row_ids": list(row_source.planned_row_ids),
        },
        "preflight_only": True,
        "booking_eligible": False,
        "live_gate_pass": False,
        "pilot_evidence_written": False,
    }


def _local_commit_available(source_sha: str) -> bool:
    """Check the local Git object database without permitting lazy fetches."""
    if _SHA1.fullmatch(source_sha) is None:
        return False
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    try:
        completed = subprocess.run(
            ["git", "cat-file", "-e", source_sha + "^{commit}"],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _validate_main_sha(main_sha: Any) -> None:
    if not isinstance(main_sha, str) or _SHA1.fullmatch(main_sha) is None:
        raise ComparisonError("frozen_origin_main_sha_must_be_full_sha1")
    if main_sha in (OLD_CONTROL_SHA, PLANNING_BASE_SHA):
        raise ComparisonError("comparison_target_is_not_frozen_origin_main")


def _validate_row_source(row_source: Any) -> None:
    if (
        not isinstance(row_source, FrozenRowSource)
        or not isinstance(row_source.planned_row_ids, tuple)
        or not isinstance(row_source.reserve_row_ids, tuple)
        or any(not isinstance(row_id, str) for row_id in row_source.planned_row_ids)
        or len(row_source.planned_row_ids) != 26
        or len(set(row_source.planned_row_ids)) != 26
        or not set(EXPECTED_NAMEERROR_ROWS).issubset(row_source.planned_row_ids)
        or any(
            _ROW_ID.fullmatch(row_id) is None or row_id.startswith("R")
            for row_id in row_source.planned_row_ids
        )
        or row_source.reserve_row_ids != EXPECTED_RESERVE_ROWS
        or not isinstance(row_source.counterbalance_sha256, str)
        or _SHA256.fullmatch(row_source.counterbalance_sha256) is None
    ):
        raise ComparisonError("frozen_row_source_invalid")


def _require_complete_profiles(
    coverage: Any, row_source: FrozenRowSource
) -> None:
    if not isinstance(coverage, Mapping):
        raise ComparisonError("lifecycle_profile_coverage_invalid")
    if (
        coverage.get("structural_row_coverage_complete") is not True
        or coverage.get("planned_row_count") != 26
        or coverage.get("planned_row_ids") != list(row_source.planned_row_ids)
        or coverage.get("fixture_party_pair_count") != 8
        or coverage.get("replacement_only_rows_activated") != []
    ):
        raise ComparisonError("lifecycle_profile_coverage_invalid")
    if (
        coverage.get("measured_lifecycle_complete") is not True
        or coverage.get("unverified_row_ids") != []
    ):
        raise ComparisonError("lifecycle_profile_measurements_missing")


def _read_and_validate_snapshot(
    source_sha: str,
    *,
    expected_role: str,
    row_source: FrozenRowSource,
    expected_row_ids: tuple[str, ...],
    snapshot_reader: Callable[[str], bytes],
) -> tuple[dict[str, Any], str]:
    try:
        raw = snapshot_reader(source_sha)
    except ComparisonError:
        raise
    except Exception as exc:
        raise ComparisonError("source_snapshot_unavailable_locally") from exc
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_SNAPSHOT_BYTES:
        raise ComparisonError("source_snapshot_invalid")
    snapshot_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ComparisonError("source_snapshot_invalid") from exc
    if not isinstance(document, Mapping):
        raise ComparisonError("source_snapshot_invalid")

    if (
        type(document.get("schema_version")) is not int
        or document.get("schema_version") != 1
        or document.get("snapshot_type") != SNAPSHOT_TYPE
        or document.get("snapshot_role") != expected_role
        or document.get("source_sha") != source_sha
        or document.get("row_source_sha256") != row_source.counterbalance_sha256
        or document.get("planned_row_ids") != list(expected_row_ids)
        or document.get("replacement_only_row_ids")
        != list(row_source.reserve_row_ids)
        or document.get("replacement_only_rows_activated") != []
        or not isinstance(document.get("row_results"), list)
        or len(document["row_results"]) != len(expected_row_ids)
    ):
        raise ComparisonError("source_snapshot_identity_or_coverage_invalid")
    return dict(document), snapshot_sha256


def _index_and_validate_outcomes(
    document: Mapping[str, Any], row_source: FrozenRowSource
) -> dict[str, dict[str, Any]]:
    row_results = document.get("row_results")
    if not isinstance(row_results, list):
        raise ComparisonError("source_snapshot_outcomes_invalid")
    indexed: dict[str, dict[str, Any]] = {}
    observed_order: list[str] = []
    for row in row_results:
        if not isinstance(row, Mapping):
            raise ComparisonError("source_snapshot_outcomes_invalid")
        row_id = row.get("row_id")
        outcome = row.get("outcome")
        exception_type = row.get("exception_type")
        digest = row.get("outcome_sha256")
        if (
            not isinstance(row_id, str)
            or row_id not in row_source.planned_row_ids
            or row_id in indexed
            or outcome not in ("completed", "exception")
            or (outcome == "completed" and exception_type is not None)
            or (
                outcome == "exception"
                and (not isinstance(exception_type, str) or not exception_type)
            )
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise ComparisonError("source_snapshot_outcome_invalid")
        expected_digest = row_outcome_sha256(
            source_sha=str(document["source_sha"]),
            row_source_sha256=str(document["row_source_sha256"]),
            row_id=row_id,
            outcome=str(outcome),
            exception_type=exception_type,
        )
        if digest != expected_digest:
            raise ComparisonError("source_snapshot_outcome_digest_mismatch")
        indexed[row_id] = {
            "outcome": outcome,
            "exception_type": exception_type,
            "outcome_sha256": digest,
        }
        observed_order.append(row_id)
    if tuple(observed_order) != row_source.planned_row_ids:
        raise ComparisonError("source_snapshot_planned_row_order_invalid")
    return indexed


def _is_nameerror(row: Mapping[str, Any]) -> bool:
    return row.get("outcome") == "exception" and row.get("exception_type") == "NameError"


def _local_snapshot_reader(source_sha: str) -> bytes:
    """Read one bounded snapshot below the fixed project-local tmp root."""
    if _SHA1.fullmatch(source_sha) is None:
        raise ComparisonError("snapshot_source_sha_invalid")
    root = PROJECT_ROOT.resolve(strict=True)
    if (root / "tmp").is_symlink() or not (root / "tmp").is_dir():
        raise ComparisonError("project_tmp_unavailable_or_unsafe")
    relative = SNAPSHOT_ROOT / source_sha / SNAPSHOT_NAME
    path = root / relative
    cursor = root
    try:
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ComparisonError("source_snapshot_path_unsafe")
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to((root / "tmp").resolve(strict=True))
    except ComparisonError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ComparisonError("source_snapshot_unavailable_locally") from exc

    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size < 1
            or metadata.st_size > MAX_SNAPSHOT_BYTES
        ):
            raise ComparisonError("source_snapshot_invalid")
        chunks: list[bytes] = []
        remaining = MAX_SNAPSHOT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64_000, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ComparisonError("source_snapshot_invalid")
        return raw
    except ComparisonError:
        raise
    except OSError as exc:
        raise ComparisonError("source_snapshot_unavailable_locally") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant: " + value)


def _blocked_report(error: ComparisonError) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "status": "BLOCKED",
        "comparison_verified": False,
        "error_code": error.code,
        "preflight_only": True,
        "host_execution_verified": False,
        "retained_source_verification": "MISSING",
        "guarded_per_source_run_reconciliation": "MISSING",
        "booking_eligible": False,
        "live_gate_pass": False,
        "pilot_evidence_written": False,
    }
    if error.affected_rows:
        report["affected_row_ids"] = list(error.affected_rows)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--main-sha",
        required=True,
        help="full origin/main SHA frozen by separate, immediate preparation",
    )
    args = parser.parse_args(argv)
    try:
        report = compare_local_snapshots(args.main_sha)
    except ComparisonError as exc:
        report = _blocked_report(exc)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
