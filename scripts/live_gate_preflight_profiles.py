# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Versioned, source-bound startup/resume profile validation for live preflight."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.mapping_pilot.manifest import verify_manifest
from scripts.live_gate_preflight_safety import expected_guarded_pythonpath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = Path(__file__).with_name("live_gate_preflight_profiles.json")
PREREG_ROOT = Path("plans/v2-mapping-pilot-prereg")
PROFILE_STATE_SOURCE = Path(
    "openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md"
)
PROFILE_SET_ID = "live-gate-preflight-call-profiles-v1"
AUTHORIZATION_RULING_ID = "neq-w1-fr11-profiles-characterization-20261112"
SCHEMA_VERSION = 1
EXPECTED_MANIFEST_SHA256 = "49d600b9a7080253d99aa66a725bd981a594afbc3fde76b5df70253219d59c07"
EXPECTED_COUNTERBALANCE_SHA256 = "ef680c1c9049d9c570c66a1fb337fcca664f87abbd4dcca81e6133be2539ff70"
EXPECTED_PROFILE_STATE_SHA256 = "27367f4b48865c601c54b6013fa67d40a6119215cd9114275f3151c505fa10a5"
REPORTED_PROFILE_REPORT_SHA256 = "75f4e9304652ebecc46390d94daa3f57f7a6eeba77840e8140610a3da2b702db"

FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    "combat_stage_tavern_zones",
)
PARTY_SIZES = (1, 4)
SCRIPT_PATHS = {
    "scripts/interior.json": "interior.json",
    "scripts/landscape.json": "landscape.json",
    "scripts/combat.json": "combat.json",
}
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SECRET_TEXT = re.compile(r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_SAFE_TASK = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PROFILE_EVIDENCE_MAX_BYTES = 512_000
_PROFILE_WORKING_DIRECTORY = "tmp/combat_capture"


class ProfileValidationError(ValueError):
    """Raised when profiles, source bindings, or planned-row coverage are invalid."""


def load_profile_coverage(
    profile_path: str | Path = PROFILE_PATH,
    *,
    project_root: str | Path = PROJECT_ROOT,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    """Read, validate, and summarize the frozen profile declaration."""
    root = Path(project_root).resolve(strict=True)
    requested_path = Path(profile_path)
    if requested_path.is_absolute():
        try:
            requested_path = requested_path.relative_to(root)
        except ValueError as exc:
            raise ProfileValidationError("profile declaration path escapes project") from exc
    path = _safe_source_path(root, requested_path, "profile declaration")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileValidationError("profile declaration cannot be read") from exc
    return validate_profile_document(
        document,
        project_root=root,
        expected_source_sha=expected_source_sha,
    )


def validate_profile_document(
    document: Any,
    *,
    project_root: str | Path = PROJECT_ROOT,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    """Validate all eight fixture-party pairs against the frozen 26-row source."""
    root = Path(project_root).resolve(strict=True)
    if not isinstance(document, Mapping):
        raise ProfileValidationError("profile declaration must be an object")
    _require_keys(
        document,
        {"schema_version", "profile_set_id", "authorization_ruling_id", "source_binding", "profiles"},
        "profile declaration",
    )
    if (
        type(document.get("schema_version")) is not int
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise ProfileValidationError("unsupported profile schema version")
    if document.get("profile_set_id") != PROFILE_SET_ID:
        raise ProfileValidationError("unsupported profile set")
    if document.get("authorization_ruling_id") != AUTHORIZATION_RULING_ID:
        raise ProfileValidationError("profile authorization ruling binding is invalid")

    source_binding = document.get("source_binding")
    _require_keys(
        source_binding,
        {
            "manifest_path",
            "manifest_sha256",
            "counterbalance_path",
            "counterbalance_sha256",
            "profile_state_source_path",
            "profile_state_source_sha256",
            "reported_profile_report_sha256",
            "profile_state_locator",
        },
        "source binding",
    )
    _validate_source_binding(source_binding, root)
    expected_rows = _load_expected_row_pairs(root)

    raw_profiles = document.get("profiles")
    if not isinstance(raw_profiles, list) or len(raw_profiles) != 8:
        raise ProfileValidationError("exactly eight fixture-party profile entries are required")

    seen_pairs: set[tuple[str, int]] = set()
    by_row: dict[str, list[str]] = {row_id: [] for row_id in expected_rows["planned_row_ids"]}
    pair_statuses: dict[str, dict[str, str]] = {}
    for profile in raw_profiles:
        _require_keys(
            profile,
            {"profile_id", "fixture_id", "party_size", "planned_row_ids", "source_binding_id", "startup", "resume"},
            "fixture-party profile",
        )
        fixture_id = profile.get("fixture_id")
        party_size = profile.get("party_size")
        if (
            not isinstance(fixture_id, str)
            or fixture_id not in FIXTURE_IDS
            or type(party_size) is not int
            or party_size not in PARTY_SIZES
        ):
            raise ProfileValidationError("unsupported fixture-party profile entry")
        pair = (fixture_id, party_size)
        if pair in seen_pairs:
            raise ProfileValidationError("duplicate fixture-party profile entry")
        seen_pairs.add(pair)
        expected_profile_id = "%s:p%d" % pair
        if profile.get("profile_id") != expected_profile_id:
            raise ProfileValidationError("fixture-party profile identity is invalid")
        if profile.get("source_binding_id") != "sp3-frozen-row-and-script-manifest-v1":
            raise ProfileValidationError("fixture-party profile source binding is invalid")

        row_ids = profile.get("planned_row_ids")
        expected_pair_rows = expected_rows["pair_rows"].get(pair)
        if not isinstance(row_ids, list) or row_ids != expected_pair_rows:
            raise ProfileValidationError("fixture-party planned-row binding differs from frozen source")
        for row_id in row_ids:
            if row_id not in by_row or row_id.startswith("R"):
                raise ProfileValidationError("profile references a reserve or unsupported row")
            by_row[row_id].append(expected_profile_id)

        startup_status = _validate_lifecycle_profile(
            profile.get("startup"),
            expected_source_sha=expected_source_sha,
            project_root=root,
            profile_id=expected_profile_id,
            fixture_id=fixture_id,
            party_size=party_size,
            lifecycle="startup",
            planned_row_ids=row_ids,
            row_metadata=expected_rows["row_metadata"],
        )
        resume_status = _validate_lifecycle_profile(
            profile.get("resume"),
            expected_source_sha=expected_source_sha,
            project_root=root,
            profile_id=expected_profile_id,
            fixture_id=fixture_id,
            party_size=party_size,
            lifecycle="resume",
            planned_row_ids=row_ids,
            row_metadata=expected_rows["row_metadata"],
        )
        pair_statuses[expected_profile_id] = {
            "startup": startup_status,
            "resume": resume_status,
        }

    expected_pair_keys = {
        (fixture_id, party_size)
        for fixture_id in FIXTURE_IDS
        for party_size in PARTY_SIZES
    }
    if seen_pairs != expected_pair_keys:
        raise ProfileValidationError("fixture-party profile pair coverage is incomplete")
    if set(expected_rows["pair_rows"]) != expected_pair_keys:
        raise ProfileValidationError("frozen source does not cover the required eight pairs")

    unverified_rows: list[str] = []
    for row_id, profile_ids in by_row.items():
        if not profile_ids:
            raise ProfileValidationError("planned row has no fixture-party profile binding")
        if any(
            pair_statuses[profile_id][lifecycle] != "measured-under-stub"
            for profile_id in profile_ids
            for lifecycle in ("startup", "resume")
        ):
            unverified_rows.append(row_id)

    all_planned_rows = expected_rows["planned_row_ids"]
    if sorted(by_row) != sorted(all_planned_rows):
        raise ProfileValidationError("planned-row profile coverage is incomplete")
    missing_pairs = [
        profile_id
        for profile_id, states in pair_statuses.items()
        if any(status == "MISSING" for status in states.values())
    ]
    blockers = ["profile coverage is not a booking authorization"]
    blockers.extend("missing lifecycle measurement: " + item for item in missing_pairs)
    return {
        "profile_set_id": PROFILE_SET_ID,
        "schema_version": SCHEMA_VERSION,
        "structural_row_coverage_complete": True,
        "planned_row_count": len(all_planned_rows),
        "planned_row_ids": list(all_planned_rows),
        "fixture_party_pair_count": len(seen_pairs),
        "profile_pair_ids": sorted(pair_statuses),
        "unverified_row_ids": unverified_rows,
        "replacement_only_rows_activated": [],
        "measured_lifecycle_complete": not missing_pairs,
        "booking_eligible": False,
        "booking_blockers": blockers,
    }


def _validate_source_binding(source_binding: Mapping[str, Any], root: Path) -> None:
    expected = {
        "manifest_path": (PREREG_ROOT / "MANIFEST.sha256").as_posix(),
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "counterbalance_path": (PREREG_ROOT / "counterbalance.json").as_posix(),
        "counterbalance_sha256": EXPECTED_COUNTERBALANCE_SHA256,
        "profile_state_source_path": PROFILE_STATE_SOURCE.as_posix(),
        "profile_state_source_sha256": EXPECTED_PROFILE_STATE_SHA256,
        "reported_profile_report_sha256": REPORTED_PROFILE_REPORT_SHA256,
        "profile_state_locator": "sp4-primary-report.md:105-117,148-149",
    }
    if dict(source_binding) != expected:
        raise ProfileValidationError("profile source binding does not match authoritative evidence")

    manifest_path = _safe_source_path(root, expected["manifest_path"], "frozen manifest")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
        raise ProfileValidationError("frozen manifest source hash changed")
    try:
        manifest_entries = verify_manifest(root / PREREG_ROOT)
    except Exception as exc:
        raise ProfileValidationError("frozen preregistration source verification failed") from exc
    counterbalance_path = _safe_source_path(root, expected["counterbalance_path"], "counterbalance")
    counterbalance_bytes = counterbalance_path.read_bytes()
    if hashlib.sha256(counterbalance_bytes).hexdigest() != EXPECTED_COUNTERBALANCE_SHA256:
        raise ProfileValidationError("frozen counterbalance source hash changed")
    if manifest_entries.get("counterbalance.json") != EXPECTED_COUNTERBALANCE_SHA256:
        raise ProfileValidationError("counterbalance is not bound by frozen manifest")

    report_path = _safe_source_path(root, PROFILE_STATE_SOURCE, "profile-state evidence")
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != EXPECTED_PROFILE_STATE_SHA256:
        raise ProfileValidationError("authoritative missing-profile report source hash changed")
    normalized_report = " ".join(report_bytes.decode("utf-8").split()).casefold()
    required_claims = (
        "zero attempted paths",
        "zero accepted profiles",
        "all eight fixture-party profile cases are missing",
        REPORTED_PROFILE_REPORT_SHA256,
    )
    if any(claim.casefold() not in normalized_report for claim in required_claims):
        raise ProfileValidationError("missing-profile source evidence no longer supports declaration")


def _load_expected_row_pairs(root: Path) -> dict[str, Any]:
    counterbalance_path = _safe_source_path(
        root, PREREG_ROOT / "counterbalance.json", "frozen counterbalance"
    )
    try:
        counterbalance = json.loads(counterbalance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileValidationError("frozen counterbalance cannot be read") from exc
    if not isinstance(counterbalance, Mapping):
        raise ProfileValidationError("frozen counterbalance is malformed")
    if (
        counterbalance.get("planned_rows") != 26
        or counterbalance.get("reserve_rows") != 4
        or counterbalance.get("total_rows") != 30
    ):
        raise ProfileValidationError("frozen 26-row and four-reserve counts changed")
    rows = counterbalance.get("rows")
    if not isinstance(rows, list) or len(rows) != 30:
        raise ProfileValidationError("frozen counterbalance must contain exactly 30 rows")

    seen_row_ids: set[str] = set()
    planned: list[Mapping[str, Any]] = []
    reserves: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ProfileValidationError("frozen counterbalance row is malformed")
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id in seen_row_ids:
            raise ProfileValidationError("frozen counterbalance row identity is invalid")
        seen_row_ids.add(row_id)
        if row.get("row_type") == "planned":
            planned.append(row)
        elif row.get("row_type") == "replacement_only":
            reserves.append(row_id)
        else:
            raise ProfileValidationError("unsupported frozen counterbalance row type")
    if len(planned) != 26 or reserves != ["R01", "R02", "R03", "R04"]:
        raise ProfileValidationError("planned rows or replacement-only reserves changed")
    planned.sort(key=lambda row: row.get("run_order", 0))
    if [row.get("run_order") for row in planned] != list(range(1, 27)):
        raise ProfileValidationError("planned-row order is not the frozen 1-26 sequence")

    pair_rows: dict[tuple[str, int], list[str]] = {}
    row_metadata: dict[str, dict[str, Any]] = {}
    planned_row_ids: list[str] = []
    for row in planned:
        row_id = row.get("row_id")
        party_size = row.get("party")
        script = row.get("script")
        if not isinstance(row_id, str) or row_id.startswith("R"):
            raise ProfileValidationError("replacement-only row appeared in planned set")
        if type(party_size) is not int or party_size not in PARTY_SIZES:
            raise ProfileValidationError("planned row has unsupported party size")
        if script not in SCRIPT_PATHS:
            raise ProfileValidationError("planned row references an unsupported script")
        script_path = _safe_source_path(
            root,
            PREREG_ROOT / script,
            "frozen planned script",
        )
        try:
            script_document = json.loads(script_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProfileValidationError("frozen planned script cannot be read") from exc
        fixture_ids = script_document.get("fixture_ids") if isinstance(script_document, Mapping) else None
        if (
            not isinstance(fixture_ids, list)
            or not fixture_ids
            or any(not isinstance(fixture_id, str) for fixture_id in fixture_ids)
            or any(fixture_id not in FIXTURE_IDS for fixture_id in fixture_ids)
            or len(set(fixture_ids)) != len(fixture_ids)
        ):
            raise ProfileValidationError("script fixture-party binding is unsupported")
        planned_row_ids.append(row_id)
        row_metadata[row_id] = {
            "party_size": party_size,
            "arm": row.get("arm"),
            "script": script,
            "fixture_ids": list(fixture_ids),
        }
        for fixture_id in fixture_ids:
            pair_rows.setdefault((fixture_id, party_size), []).append(row_id)
    return {
        "planned_row_ids": planned_row_ids,
        "pair_rows": pair_rows,
        "row_metadata": row_metadata,
    }


def _validate_lifecycle_profile(
    value: Any,
    *,
    expected_source_sha: str | None,
    project_root: Path,
    profile_id: str,
    fixture_id: str,
    party_size: int,
    lifecycle: str,
    planned_row_ids: list[str],
    row_metadata: Mapping[str, Mapping[str, Any]],
) -> str:
    if not isinstance(value, Mapping):
        raise ProfileValidationError("startup/resume profile must be an object")
    status = value.get("status")
    if status == "MISSING":
        _require_keys(value, {"status", "reason"}, "missing lifecycle profile")
        reason = value.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ProfileValidationError("MISSING lifecycle profile requires a reason")
        return "MISSING"
    if status != "measured-under-stub":
        raise ProfileValidationError("unsupported lifecycle profile status")
    _require_keys(
        value,
        {
            "status",
            "call_count",
            "call_sites",
            "source_sha",
            "command",
            "pythonpath",
            "evidence_path",
            "evidence_sha256",
        },
        "measured lifecycle profile",
    )
    call_count = value.get("call_count")
    call_sites = value.get("call_sites")
    source_sha = value.get("source_sha")
    command = value.get("command")
    pythonpath = value.get("pythonpath")
    evidence_path = value.get("evidence_path")
    evidence_sha256 = value.get("evidence_sha256")
    if type(call_count) is not int or call_count < 1:
        raise ProfileValidationError("measured lifecycle call count is invalid")
    if not isinstance(source_sha, str) or _SHA.fullmatch(source_sha) is None:
        raise ProfileValidationError("measured lifecycle source SHA is invalid")
    if expected_source_sha is not None and source_sha != expected_source_sha:
        raise ProfileValidationError("measured lifecycle source SHA does not match expected source")
    if not _valid_command(command):
        raise ProfileValidationError("measured lifecycle command is invalid or secret-bearing")
    if pythonpath != expected_guarded_pythonpath(project_root):
        raise ProfileValidationError(
            "measured lifecycle PYTHONPATH must put the dedicated guard before the repository root"
        )
    if (
        not isinstance(evidence_path, str)
        or not evidence_path.startswith("tmp/")
        or not isinstance(evidence_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None
    ):
        raise ProfileValidationError("measured lifecycle evidence binding is invalid")
    if not isinstance(call_sites, list):
        raise ProfileValidationError("measured lifecycle call-site list is invalid")
    observed_count = 0
    for call_site in call_sites:
        _require_keys(
            call_site,
            {"source_file", "source_line", "source_file_sha256", "count"},
            "router call site",
        )
        source_file = call_site.get("source_file")
        source_line = call_site.get("source_line")
        source_file_sha256 = call_site.get("source_file_sha256")
        site_count = call_site.get("count")
        if (
            not isinstance(source_file, str)
            or not isinstance(source_line, int)
            or isinstance(source_line, bool)
            or source_line < 1
            or not isinstance(source_file_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_file_sha256) is None
            or type(site_count) is not int
            or site_count < 1
        ):
            raise ProfileValidationError("measured router call-site provenance is invalid")
        source_path = _safe_source_path(project_root, source_file, "router call-site source")
        try:
            source_bytes = source_path.read_bytes()
            line_count = len(source_bytes.decode("utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise ProfileValidationError("router call-site source cannot be read") from exc
        if source_line > line_count:
            raise ProfileValidationError("router call-site line is outside source file")
        if hashlib.sha256(source_bytes).hexdigest() != source_file_sha256:
            raise ProfileValidationError("router call-site source hash differs")
        observed_count += site_count
    if observed_count != call_count:
        raise ProfileValidationError("measured lifecycle call-site counts do not sum to total")
    _validate_profile_evidence(
        project_root,
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha256,
        profile_id=profile_id,
        fixture_id=fixture_id,
        party_size=party_size,
        lifecycle=lifecycle,
        planned_row_ids=planned_row_ids,
        row_metadata=row_metadata,
        source_sha=source_sha,
        command=command,
        pythonpath=pythonpath,
        call_count=call_count,
        call_sites=call_sites,
    )
    return "measured-under-stub"


def _validate_profile_evidence(
    project_root: Path,
    *,
    evidence_path: str,
    evidence_sha256: str,
    profile_id: str,
    fixture_id: str,
    party_size: int,
    lifecycle: str,
    planned_row_ids: list[str],
    row_metadata: Mapping[str, Mapping[str, Any]],
    source_sha: str,
    command: list[str],
    pythonpath: str,
    call_count: int,
    call_sites: list[Any],
) -> None:
    """Verify a measured declaration against its retained, bounded call log."""
    path = _safe_source_path(project_root, evidence_path, "profile evidence")
    raw = _read_bounded_evidence(path)
    if hashlib.sha256(raw).hexdigest() != evidence_sha256:
        raise ProfileValidationError("profile evidence hash does not match declaration")
    try:
        evidence = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProfileValidationError("profile evidence is not valid JSON") from exc

    evidence_fields = {
        "schema_version",
        "authorization_ruling_id",
        "profile_id",
        "fixture_id",
        "party_size",
        "lifecycle",
        "planned_row_id",
        "arm",
        "sandbox_root",
        "run_id",
        "source_sha",
        "command",
        "working_directory",
        "pythonpath",
        "controller_interpreter",
        "worker_interpreter",
        "network_guard_active",
        "provider_keys_blank",
        "proxy_values_blank",
        "real_project_config_loaded",
        "sandbox_config_loaded",
        "startup_guard_from_sitecustomize",
        "sandbox_config_origin_guard_active",
        "process_canaries",
        "process_census",
        "driver_exchange",
        "outcome",
        "calls",
        "call_count",
        "call_sites",
        "host_command",
        "runner_command",
        "failure_code",
        "teardown",
    }
    _require_keys(evidence, evidence_fields, "profile evidence")
    if (
        type(evidence.get("schema_version")) is not int
        or evidence.get("schema_version") != 1
        or evidence.get("authorization_ruling_id") != AUTHORIZATION_RULING_ID
        or evidence.get("profile_id") != profile_id
        or evidence.get("fixture_id") != fixture_id
        or type(evidence.get("party_size")) is not int
        or evidence.get("party_size") != party_size
        or evidence.get("lifecycle") != lifecycle
        or evidence.get("planned_row_id") not in planned_row_ids
        or evidence.get("arm")
        != row_metadata.get(evidence.get("planned_row_id"), {}).get("arm")
        or evidence.get("fixture_id")
        not in row_metadata.get(evidence.get("planned_row_id"), {}).get("fixture_ids", [])
        or evidence.get("party_size")
        != row_metadata.get(evidence.get("planned_row_id"), {}).get("party_size")
        or evidence.get("sandbox_root") != "tmp/combat_capture"
        or not isinstance(evidence.get("run_id"), str)
        or _SAFE_RUN_ID.fullmatch(evidence["run_id"]) is None
        or evidence.get("source_sha") != source_sha
        or evidence.get("command") != command
        or evidence.get("working_directory") != _PROFILE_WORKING_DIRECTORY
        or evidence.get("pythonpath") != pythonpath
        or not _valid_interpreter_identity(
            evidence.get("controller_interpreter"), project_root
        )
        or not _valid_interpreter_identity(
            evidence.get("worker_interpreter"), project_root
        )
        or evidence.get("network_guard_active") is not True
        or evidence.get("provider_keys_blank") is not True
        or evidence.get("proxy_values_blank") is not True
        or evidence.get("real_project_config_loaded") is not False
        or evidence.get("sandbox_config_loaded") is not True
        or evidence.get("startup_guard_from_sitecustomize") is not True
        or evidence.get("sandbox_config_origin_guard_active") is not True
        or evidence.get("outcome") != "completed"
        or evidence.get("failure_code") is not None
    ):
        raise ProfileValidationError("profile evidence identity or safety state differs")

    process_canaries = evidence.get("process_canaries")
    if not isinstance(process_canaries, list) or len(process_canaries) != 3:
        raise ProfileValidationError("profile evidence process canaries are incomplete")
    expected_canaries = (
        ("controller-startup", "parent", evidence.get("runner_command")),
        ("host-prelaunch", "host", evidence.get("host_command")),
        ("host-startup", "host", evidence.get("host_command")),
    )
    canary_pids: list[int] = []
    host_environment_sha256: str | None = None
    for canary, (expected_stage, expected_role, expected_command) in zip(
        process_canaries, expected_canaries
    ):
        canary_fields = {
            "canary_stage",
            "process_role",
            "pid",
            "startup_observed_at_ns",
            "command",
            "command_sha256",
            "environment_sha256",
            "working_directory",
            "guard_active",
            "non_loopback_connect_denied",
            "subprocess_launch_denied",
            "interpreter",
        }
        _require_keys(canary, canary_fields, "startup process canary")
        canary_command = canary.get("command")
        command_sha256 = canary.get("command_sha256")
        environment_sha256 = canary.get("environment_sha256")
        working_directory = canary.get("working_directory")
        if (
            canary.get("canary_stage") != expected_stage
            or canary.get("process_role") != expected_role
            or type(canary.get("pid")) is not int
            or canary.get("pid") <= 0
            or type(canary.get("startup_observed_at_ns")) is not int
            or canary.get("startup_observed_at_ns") <= 0
            or canary_command != expected_command
            or not _valid_command(canary_command)
            or not isinstance(command_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", command_sha256) is None
            or hashlib.sha256(
                json.dumps(
                    canary_command, ensure_ascii=True, separators=(",", ":")
                ).encode("ascii")
            ).hexdigest()
            != command_sha256
            or not isinstance(environment_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", environment_sha256) is None
            or not isinstance(working_directory, str)
            or canary.get("guard_active") is not True
            or canary.get("non_loopback_connect_denied") is not True
            or canary.get("subprocess_launch_denied") is not True
        ):
            raise ProfileValidationError("profile evidence process canary identity differs")
        canary_pids.append(canary["pid"])
        expected_interpreter = (
            evidence.get("worker_interpreter")
            if expected_role == "host"
            else evidence.get("controller_interpreter")
        )
        if canary.get("interpreter") != expected_interpreter:
            raise ProfileValidationError("profile evidence process canary interpreter differs")
        if expected_role == "host":
            expected_cwd = str(project_root / "tmp" / "combat_capture")
            if working_directory != expected_cwd:
                raise ProfileValidationError("profile evidence host canary working directory differs")
            if expected_stage == "host-prelaunch":
                host_environment_sha256 = environment_sha256
            elif environment_sha256 != host_environment_sha256:
                raise ProfileValidationError(
                    "profile evidence host launch environment differs"
                )
        else:
            try:
                Path(working_directory).resolve(strict=True).relative_to(
                    project_root.resolve(strict=True)
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise ProfileValidationError(
                    "profile evidence controller canary working directory is unsafe"
                ) from exc
    if len(set(canary_pids)) != len(canary_pids):
        raise ProfileValidationError("profile evidence process canary pids are duplicated")
    process_census = evidence.get("process_census")
    census_fields = {
        "controller_pid",
        "driver_pid",
        "host_prelaunch_pid",
        "host_worker_pid",
        "launched_pids",
        "socket_owner_pids",
        "python_pids",
        "guarded_pids",
        "uncovered_pids",
        "socket_pid_samples",
        "complete",
    }
    _require_keys(process_census, census_fields, "process census")
    process_by_stage = {
        canary["canary_stage"]: canary for canary in process_canaries
    }
    controller_pid = process_by_stage["controller-startup"]["pid"]
    host_prelaunch_pid = process_by_stage["host-prelaunch"]["pid"]
    host_worker_pid = process_by_stage["host-startup"]["pid"]
    expected_samples = ("before_host", "host_ready", "after_teardown")
    samples = process_census.get("socket_pid_samples")
    if not isinstance(samples, list) or len(samples) != len(expected_samples):
        raise ProfileValidationError("profile evidence process census is incomplete")
    socket_owners: set[int] = set()
    sample_pids: dict[str, set[int]] = {}
    for sample, phase in zip(samples, expected_samples):
        if (
            not isinstance(sample, Mapping)
            or set(sample) != {"phase", "port", "observed", "pids"}
            or sample.get("phase") != phase
            or sample.get("port") != 8360
            or sample.get("observed") is not True
            or not isinstance(sample.get("pids"), list)
            or any(type(pid) is not int or pid <= 0 for pid in sample["pids"])
            or sample["pids"] != sorted(set(sample["pids"]))
        ):
            raise ProfileValidationError("profile evidence process census socket sample differs")
        sample_pids[phase] = set(sample["pids"])
        socket_owners.update(sample["pids"])
    launched_pids = sorted({controller_pid, host_prelaunch_pid, host_worker_pid})
    python_pids = sorted(set(launched_pids) | socket_owners)
    if (
        process_census.get("controller_pid") != controller_pid
        or process_census.get("driver_pid") != controller_pid
        or process_census.get("host_prelaunch_pid") != host_prelaunch_pid
        or process_census.get("host_worker_pid") != host_worker_pid
        or process_census.get("launched_pids") != launched_pids
        or process_census.get("socket_owner_pids") != sorted(socket_owners)
        or process_census.get("python_pids") != python_pids
        or process_census.get("guarded_pids") != sorted(canary_pids)
        or process_census.get("uncovered_pids") != []
        or process_census.get("complete") is not True
        or sample_pids.get("before_host") != set()
        or sample_pids.get("host_ready") != {host_worker_pid}
        or sample_pids.get("after_teardown") != set()
        or set(python_pids) != set(canary_pids)
    ):
        raise ProfileValidationError("profile evidence process census identity differs")
    driver_exchange = evidence.get("driver_exchange")
    if (
        not isinstance(driver_exchange, Mapping)
        or set(driver_exchange)
        != {
            "status",
            "step_id",
            "start_ready",
            "active_character_set",
            "turn_completed",
            "turn_timed_out",
            "game_output_count",
            "failure_code",
            "process_pid",
        }
        or driver_exchange.get("status") != "completed"
        or not isinstance(driver_exchange.get("step_id"), str)
        or _SAFE_RUN_ID.fullmatch(driver_exchange.get("step_id", "")) is None
        or driver_exchange.get("start_ready") is not True
        or driver_exchange.get("active_character_set") is not True
        or driver_exchange.get("turn_completed") is not True
        or driver_exchange.get("turn_timed_out") is not False
        or type(driver_exchange.get("game_output_count")) is not int
        or driver_exchange.get("game_output_count") < 1
        or driver_exchange.get("failure_code") is not None
        or driver_exchange.get("process_pid") != controller_pid
    ):
        raise ProfileValidationError("profile evidence lifecycle exchange is incomplete")

    for command_field in ("host_command", "runner_command"):
        command_value = evidence.get(command_field)
        if not _valid_command(command_value):
            raise ProfileValidationError("profile evidence command is invalid")
    if evidence.get("host_command") != command:
        raise ProfileValidationError("profile evidence host command differs")

    teardown = evidence.get("teardown")
    if teardown != {
        "server_stopped": True,
        "port_8360_free": True,
        "lock_released": True,
    }:
        raise ProfileValidationError("profile evidence teardown is incomplete")

    calls = evidence.get("calls")
    if not isinstance(calls, list) or len(calls) != call_count:
        raise ProfileValidationError("profile evidence call count differs")
    evidence_sites: dict[tuple[str, int, str], int] = {}
    call_fields = {
        "sequence",
        "task",
        "source_file",
        "source_line",
        "source_file_sha256",
        "source_sha",
        "command",
        "pythonpath",
    }
    for index, call in enumerate(calls, start=1):
        _require_keys(call, call_fields, "recorded router call")
        task = call.get("task")
        source_file = call.get("source_file")
        source_line = call.get("source_line")
        source_file_sha256 = call.get("source_file_sha256")
        if (
            type(call.get("sequence")) is not int
            or call.get("sequence") != index
            or not isinstance(task, str)
            or _SAFE_TASK.fullmatch(task) is None
            or not isinstance(source_file, str)
            or type(source_line) is not int
            or source_line < 1
            or not isinstance(source_file_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_file_sha256) is None
            or call.get("source_sha") != source_sha
            or call.get("command") != command
            or call.get("pythonpath") != pythonpath
        ):
            raise ProfileValidationError("profile evidence contains an invalid router call")
        source_path = _safe_source_path(project_root, source_file, "recorded router call source")
        try:
            source_bytes = source_path.read_bytes()
            line_count = len(source_bytes.decode("utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise ProfileValidationError("recorded router call source cannot be read") from exc
        if source_line > line_count:
            raise ProfileValidationError("recorded router call line is outside source file")
        if hashlib.sha256(source_bytes).hexdigest() != source_file_sha256:
            raise ProfileValidationError("recorded router call source hash differs")
        evidence_sites[(source_file, source_line, source_file_sha256)] = (
            evidence_sites.get((source_file, source_line, source_file_sha256), 0) + 1
        )

    normalized_sites = [
        {
            "source_file": source_file,
            "source_line": source_line,
            "source_file_sha256": source_file_sha256,
            "count": count,
        }
        for (source_file, source_line, source_file_sha256), count
        in sorted(evidence_sites.items())
    ]
    if (
        type(evidence.get("call_count")) is not int
        or evidence.get("call_count") != call_count
        or evidence.get("call_sites") != normalized_sites
        or call_sites != normalized_sites
    ):
        raise ProfileValidationError("profile evidence call-site summary differs")


def _valid_command(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(
            isinstance(part, str)
            and part
            and not _SECRET_TEXT.search(part)
            and not any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in value
        )
    )


def _valid_interpreter_identity(value: Any, project_root: Path) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "executable",
        "prefix",
        "base_prefix",
    }:
        return False
    expected_python = str(project_root / ".venv" / "bin" / "python")
    expected_prefix = str(project_root / ".venv")
    base_prefix = value.get("base_prefix")
    return (
        value.get("executable") == expected_python
        and value.get("prefix") == expected_prefix
        and isinstance(base_prefix, str)
        and bool(base_prefix)
        and base_prefix != expected_prefix
    )


def _read_bounded_evidence(path: Path) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < 1
            or metadata.st_size > _PROFILE_EVIDENCE_MAX_BYTES
        ):
            raise ProfileValidationError("profile evidence is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = _PROFILE_EVIDENCE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64_000, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _PROFILE_EVIDENCE_MAX_BYTES:
            raise ProfileValidationError("profile evidence exceeds the size limit")
        return raw
    except OSError as exc:
        raise ProfileValidationError("profile evidence cannot be read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value: %s" % value)


def _safe_source_path(root: Path, relative: str | Path, label: str) -> Path:
    raw = PurePosixPath(str(relative))
    if (
        raw.is_absolute()
        or ".." in raw.parts
        or "\\" in str(relative)
        or not raw.parts
    ):
        raise ProfileValidationError("%s path is unsafe" % label)
    candidate = root.joinpath(*raw.parts)
    if root.is_symlink():
        raise ProfileValidationError("%s path traverses a symlink" % label)
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ProfileValidationError("%s path traverses a symlink" % label)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProfileValidationError("%s path is missing or escapes project" % label) from exc
    if not resolved.is_file():
        raise ProfileValidationError("%s path is not a file" % label)
    return resolved


def _require_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProfileValidationError("%s fields are malformed" % label)


def copy_profile_document() -> dict[str, Any]:
    """Return a detached copy of the checked-in declaration for focused tests."""
    path = _safe_source_path(PROJECT_ROOT, PROFILE_PATH.relative_to(PROJECT_ROOT), "profile declaration")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileValidationError("profile declaration cannot be read") from exc
    if not isinstance(value, dict):
        raise ProfileValidationError("profile declaration must be an object")
    return copy.deepcopy(value)
