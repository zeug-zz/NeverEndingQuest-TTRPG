# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free writer for unique, fail-closed mapping-pilot evidence bundles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Union

from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    verify_manifest,
)
from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
)


DEFAULT_EVIDENCE_ROOT = Path("tmp/router-rollout/mapping-pilot")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_GIT_SHA_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|private[_-]?key|credential|secret|password|authorization|token)",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(?:api[_-]?key|private[_-]?key|credential|password|authorization|"
    r"access[_-]?token|refresh[_-]?token|secret|\btoken)\s*[:=]\s*[^\s,;]+|"
    r"\bbearer\s+[A-Za-z0-9._~+/-]+=*|config\.py",
    re.IGNORECASE,
)
_SAFE_SCORING_FIELDS = frozenset(
    (
        "input_tokens_total",
        "output_tokens_total",
        "input_tokens_per_model_turn",
        "output_tokens_per_model_turn",
        "input_tokens_by_model_turn",
        "output_tokens_by_model_turn",
        "input_tokens_per_turn_at_most_115_percent_of_a",
        "input_tokens_per_turn",
    )
)
_RECORD_NAME = re.compile(r"^record-[0-9]{8}\.json$")

_REQUIRED_ROW_FIELDS = (
    "row_id",
    "fixture_id",
    "script_id",
    "scenario_id",
    "arm",
    "party",
    "seed",
)
_REQUIRED_ARTIFACTS = (
    "exact_packets",
    "transcript",
    "state_snapshots",
    "zone_trace",
    "expected_observed_checks",
    "cap_counts",
    "logs",
    "router_receipts",
    "scoring",
)
_FIXTURE_PATHS = {
    "interior_tavern": "fixtures/interior_tavern.json",
    "landscape_village": "fixtures/landscape_village.json",
    "transition_tower_approach": "fixtures/transition_tower_approach.json",
    "combat_stage_tavern_zones": "fixtures/combat_stage_tavern.json",
}
_ARTIFACT_FILENAMES = {
    "row": "row.json",
    "provenance": "provenance.json",
    "exact_packets": "exact_packets.json",
    "transcript": "transcript.txt",
    "state_snapshots": "state_snapshots.json",
    "zone_trace": "zone_trace.json",
    "expected_observed_checks": "checks.json",
    "cap_counts": "cap_counts.json",
    "logs": "server_logs.txt",
    "router_receipts": "router_receipts.json",
    "scoring": "scoring.json",
    "verdict": "verdict.json",
}


class EvidenceBundleError(ValueError):
    """Raised when evidence is unsafe, incomplete, or cannot be finalized."""


def load_turn_packet_evidence(
    evidence_directory: Union[str, Path],
) -> dict[str, Any]:
    """Read adapter ``record-*.json`` files as an exact-packets evidence item.

    Only the adapter's JSON record files are read; no neighboring files (including
    ``config.py``) are copied. An absent or empty record directory is returned as
    explicitly missing evidence so a BLOCKED bundle can preserve that fact.
    """
    relative_directory, absolute_directory = _project_tmp_path(
        evidence_directory, "turn evidence directory"
    )
    del relative_directory
    _reject_symlink_components(absolute_directory)
    if not absolute_directory.is_dir():
        raise EvidenceBundleError("turn evidence directory is unavailable")

    records: list[dict[str, Any]] = []
    try:
        entries = sorted(absolute_directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise EvidenceBundleError("turn evidence directory cannot be listed") from exc

    for entry in entries:
        if not _RECORD_NAME.fullmatch(entry.name):
            continue
        if entry.is_symlink() or not entry.is_file():
            raise EvidenceBundleError("turn evidence record is unsafe")
        _reject_symlink_components(entry)
        try:
            record = json.loads(
                entry.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise EvidenceBundleError("turn evidence record is invalid") from exc
        if not isinstance(record, Mapping):
            raise EvidenceBundleError("turn evidence record must be an object")
        _reject_secret_payload(record)
        records.append(dict(record))

    status = _turn_evidence_status(records)
    return {"evidence_status": status, "records": records}


def create_evidence_bundle(
    gate: str,
    run_id: str,
    *,
    row: Mapping[str, Any],
    provenance: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    verdict: str,
    base_root: Optional[Union[str, Path]] = None,
    prereg_root: Optional[Union[str, Path]] = None,
) -> Path:
    """Write one immutable row bundle and return its project-relative path.

    ``provenance`` requires ``source_identity`` (``git_head_sha``, ``branch``,
    ``dirty``, and ``worktree``), ``input_paths`` (verified ``fixture``,
    ``script``, and ``scenario`` paths from the frozen preregistration manifest),
    ``route_identity`` (requested and resolved per-call lists), and
    ``evidence_kind`` (``live``, ``prompt-only``, or ``offline``). Required
    ``artifacts`` are listed in ``_REQUIRED_ARTIFACTS``. JSON artifacts are
    written with ``safe_write_json``; transcript and log text are ASCII-safe.

    ``base_root`` is an injectable project-relative root beneath ``tmp/`` for
    tests. The default is ``tmp/router-rollout/mapping-pilot``. A directory is
    considered complete only when its final ``manifest.json`` exists; if an
    artifact write fails, the partial directory is retained without that
    manifest and cannot be reused or mistaken for a completed bundle.
    """
    _validate_token(gate, "gate")
    _validate_token(run_id, "run_id")
    if verdict not in ("PASS", "FAIL", "BLOCKED"):
        raise EvidenceBundleError("verdict must be PASS, FAIL, or BLOCKED")
    if not isinstance(row, Mapping) or not isinstance(provenance, Mapping):
        raise EvidenceBundleError("row and provenance must be objects")
    if not isinstance(artifacts, Mapping):
        raise EvidenceBundleError("artifacts must be an object")
    if Path.cwd().resolve() != PROJECT_ROOT:
        raise EvidenceBundleError("evidence bundles must be written from the project root")

    _reject_secret_payload(row)
    _reject_secret_payload(provenance)
    _reject_secret_payload(artifacts)
    normalized_row = _validate_row(row)
    normalized_provenance, input_hashes = _validate_provenance(
        provenance, normalized_row, prereg_root
    )
    normalized_artifacts = _validate_artifacts(artifacts)
    packet_status = _turn_evidence_status(
        normalized_artifacts["exact_packets"]["records"],
        arm=normalized_row["arm"],
        declared_status=normalized_artifacts["exact_packets"].get("evidence_status"),
    )
    declared_packet_status = normalized_artifacts["exact_packets"].get("evidence_status")
    if declared_packet_status == "degraded":
        packet_status = "degraded"
    elif declared_packet_status == "not_applicable":
        if normalized_row["arm"] != "A" or not _valid_arm_a_noop_record(
            normalized_artifacts["exact_packets"]["records"]
        ):
            packet_status = "missing"
        else:
            packet_status = "not_applicable"
    elif declared_packet_status not in (None, "recorded"):
        packet_status = "missing"
    normalized_artifacts["exact_packets"]["evidence_status"] = packet_status
    _validate_verdict(
        verdict,
        normalized_provenance,
        normalized_artifacts,
        packet_status,
        normalized_row,
    )

    relative_root = _normalize_base_root(base_root)
    absolute_root = PROJECT_ROOT / relative_root
    _reject_symlink_components(absolute_root)
    _ensure_directory(absolute_root)
    absolute_gate_directory = absolute_root / gate
    _ensure_directory(absolute_gate_directory)
    _reject_duplicate_row(absolute_gate_directory, normalized_row["row_id"])

    relative_bundle = relative_root / gate / run_id
    absolute_bundle = PROJECT_ROOT / relative_bundle
    try:
        absolute_bundle.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise EvidenceBundleError("run-id bundle already exists; reuse is refused") from exc
    except OSError as exc:
        raise EvidenceBundleError("bundle directory cannot be created") from exc

    _reject_symlink_components(absolute_bundle)
    payloads: dict[str, Any] = {
        "row": normalized_row,
        "provenance": {
            **normalized_provenance,
            "input_hashes": input_hashes,
        },
        **normalized_artifacts,
        "verdict": {
            "verdict": verdict,
            "turn_evidence_status": packet_status,
        },
    }
    try:
        for name in (
            "row",
            "provenance",
            "exact_packets",
            "transcript",
            "state_snapshots",
            "zone_trace",
            "expected_observed_checks",
            "cap_counts",
            "logs",
            "router_receipts",
            "scoring",
            "verdict",
        ):
            filename = _ARTIFACT_FILENAMES[name]
            target_relative = relative_bundle / filename
            target_absolute = PROJECT_ROOT / target_relative
            _reject_symlink_components(target_absolute)
            if target_absolute.exists():
                raise EvidenceBundleError("bundle artifact path already exists")
            if name in ("transcript", "logs"):
                _write_ascii_text(target_relative, payloads[name])
            else:
                _write_json(target_relative, payloads[name])

        file_hashes = _hash_bundle_files(absolute_bundle)
        manifest = {
            "format": "mapping-pilot-evidence-v1",
            "complete": True,
            "gate": gate,
            "run_id": run_id,
            "row_id": normalized_row["row_id"],
            "verdict": verdict,
            "evidence_kind": normalized_provenance["evidence_kind"],
            "turn_evidence_status": packet_status,
            "files": file_hashes,
        }
        manifest_relative = relative_bundle / "manifest.json"
        manifest_absolute = PROJECT_ROOT / manifest_relative
        _reject_symlink_components(manifest_absolute)
        if manifest_absolute.exists():
            raise EvidenceBundleError("final manifest path already exists")
        _write_json(manifest_relative, manifest)
    except Exception:
        # Do not remove a partial directory: absence of the final manifest marks
        # it incomplete and preserves the evidence of the failed write attempt.
        raise

    return relative_bundle


def _validate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in _REQUIRED_ROW_FIELDS if field not in row]
    if missing:
        raise EvidenceBundleError("row is missing required identity fields")
    normalized = dict(row)
    for field in ("row_id", "fixture_id", "script_id", "scenario_id", "arm"):
        _validate_token(normalized[field], field)
    if not isinstance(normalized["party"], str) or not normalized["party"].strip():
        raise EvidenceBundleError("party must be non-empty text")
    seed = normalized["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise EvidenceBundleError("seed must be a non-negative integer")
    _ensure_json_value(normalized, "row")
    return normalized


def _validate_provenance(
    provenance: Mapping[str, Any],
    row: Mapping[str, Any],
    prereg_root: Optional[Union[str, Path]],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    source = provenance.get("source_identity")
    if not isinstance(source, Mapping):
        raise EvidenceBundleError("source_identity is required")
    for field in ("git_head_sha", "branch", "dirty", "worktree"):
        if field not in source:
            raise EvidenceBundleError("source_identity is incomplete")
    if not isinstance(source["git_head_sha"], str) or not _GIT_SHA_PATTERN.fullmatch(
        source["git_head_sha"]
    ):
        raise EvidenceBundleError("git_head_sha must be a full hexadecimal commit id")
    if not isinstance(source["branch"], str) or not source["branch"].strip():
        raise EvidenceBundleError("branch must be non-empty text")
    if any(ord(character) < 32 for character in source["branch"]):
        raise EvidenceBundleError("branch must not contain control characters")
    if not isinstance(source["dirty"], bool):
        raise EvidenceBundleError("dirty must be a boolean")
    if not isinstance(source["worktree"], str) or not source["worktree"].strip():
        raise EvidenceBundleError("worktree must be non-empty text")

    input_paths = provenance.get("input_paths")
    if not isinstance(input_paths, Mapping):
        raise EvidenceBundleError("input_paths is required")
    if set(input_paths) != {"fixture", "script", "scenario"}:
        raise EvidenceBundleError("input_paths must name fixture, script, and scenario")
    verified = verify_manifest(prereg_root)
    resolved_paths: dict[str, str] = {}
    input_hashes: dict[str, dict[str, str]] = {}
    required_prefixes = {"fixture": "fixtures/", "script": "scripts/", "scenario": "scripts/"}
    for category, prefix in required_prefixes.items():
        raw_path = input_paths[category]
        if not isinstance(raw_path, str):
            raise EvidenceBundleError("preregistration input path must be text")
        parsed = PurePosixPath(raw_path)
        if (
            not raw_path
            or parsed.is_absolute()
            or ".." in parsed.parts
            or "." in parsed.parts
            or "\\" in raw_path
            or not raw_path.startswith(prefix)
        ):
            raise EvidenceBundleError("preregistration input path is unsafe")
        expected_hash = verified.get(raw_path)
        if expected_hash is None:
            raise EvidenceBundleError("preregistration input is not in MANIFEST.sha256")
        resolved_paths[category] = raw_path
        input_hashes[category] = {"path": raw_path, "sha256": expected_hash}
    if resolved_paths["fixture"] != _FIXTURE_PATHS.get(row["fixture_id"]):
        raise EvidenceBundleError("fixture identity does not match its preregistration path")
    prereg_directory = Path(prereg_root) if prereg_root is not None else DEFAULT_PREREG_ROOT
    if not prereg_directory.is_absolute():
        prereg_directory = PROJECT_ROOT / prereg_directory
    script_file = prereg_directory / resolved_paths["script"]
    try:
        script_payload = json.loads(script_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceBundleError("preregistered script is invalid") from exc
    if not isinstance(script_payload, Mapping) or script_payload.get("script_id") != row["script_id"]:
        raise EvidenceBundleError("script identity does not match its preregistration file")

    evidence_kind = provenance.get("evidence_kind")
    if evidence_kind not in ("live", "prompt-only", "offline"):
        raise EvidenceBundleError("evidence_kind must be live, prompt-only, or offline")
    route_identity = provenance.get("route_identity")
    if not isinstance(route_identity, Mapping):
        raise EvidenceBundleError("route_identity is required")
    if set(route_identity) != {"requested", "resolved"}:
        raise EvidenceBundleError("route_identity must contain requested and resolved")
    requested = _validate_route_records(route_identity["requested"], "requested")
    resolved = _validate_route_records(route_identity["resolved"], "resolved")

    normalized = dict(provenance)
    normalized["source_identity"] = dict(source)
    normalized["input_paths"] = resolved_paths
    normalized["route_identity"] = {"requested": requested, "resolved": resolved}
    normalized["evidence_kind"] = evidence_kind
    _ensure_json_value(normalized, "provenance")
    return normalized, input_hashes


def _validate_route_records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EvidenceBundleError("%s route identity must be a per-call list" % label)
    records: list[dict[str, Any]] = []
    for record in value:
        if not isinstance(record, Mapping):
            raise EvidenceBundleError("each %s route identity must be an object" % label)
        records.append(dict(record))
    return records


def _validate_artifacts(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    missing = [name for name in _REQUIRED_ARTIFACTS if name not in artifacts]
    extras = set(artifacts) - set(_REQUIRED_ARTIFACTS)
    if missing:
        raise EvidenceBundleError("required evidence artifacts are missing")
    if extras:
        raise EvidenceBundleError("unexpected evidence artifact names are not accepted")
    normalized = dict(artifacts)
    if not isinstance(normalized["exact_packets"], Mapping):
        raise EvidenceBundleError("exact_packets must contain adapter evidence records")
    packet_payload = dict(normalized["exact_packets"])
    records = packet_payload.get("records")
    if not isinstance(records, list):
        raise EvidenceBundleError("exact_packets.records must be a list")
    for record in records:
        if not isinstance(record, Mapping):
            raise EvidenceBundleError("each exact packet record must be an object")
        _verify_packet_record(record)
    packet_payload["records"] = [dict(record) for record in records]
    normalized["exact_packets"] = packet_payload

    for name in ("transcript", "logs"):
        if not isinstance(normalized[name], str) or not normalized[name].strip():
            raise EvidenceBundleError("%s text artifact must be non-empty" % name)
    if not isinstance(normalized["expected_observed_checks"], list):
        raise EvidenceBundleError("expected_observed_checks must be a list")
    if not normalized["expected_observed_checks"]:
        raise EvidenceBundleError("expected_observed_checks must not be empty")
    for check in normalized["expected_observed_checks"]:
        if not isinstance(check, Mapping) or not {
            "expected",
            "observed",
            "passed",
        }.issubset(check):
            raise EvidenceBundleError("each check requires expected, observed, and passed")
        if not isinstance(check["passed"], bool):
            raise EvidenceBundleError("check passed values must be booleans")
    if not isinstance(normalized["cap_counts"], Mapping):
        raise EvidenceBundleError("cap_counts must be an object")
    _validate_cap_counts(normalized["cap_counts"])

    receipts = normalized["router_receipts"]
    if not isinstance(receipts, Mapping):
        raise EvidenceBundleError("router_receipts must be an object")
    receipt_records = receipts.get("records")
    if not isinstance(receipt_records, list) or any(
        not isinstance(record, Mapping) for record in receipt_records
    ):
        raise EvidenceBundleError("router_receipts.records must be a list of objects")
    receipt_status = receipts.get("evidence_status")
    if receipt_status not in ("recorded", "degraded", "missing"):
        raise EvidenceBundleError("router_receipts evidence_status is invalid")
    for count_name in ("attempt_count", "provider_call_expected_false_observed"):
        count = receipts.get(count_name)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise EvidenceBundleError("router_receipts counts must be non-negative integers")
    attempt_ids = {
        record.get("attempt_id")
        for record in receipt_records
        if isinstance(record.get("attempt_id"), str) and record.get("attempt_id")
    }
    if receipts["attempt_count"] != len(attempt_ids):
        raise EvidenceBundleError("router_receipts attempt_count does not match its records")
    unexpected_receipts: set[tuple[str, Any]] = set()
    for index, record in enumerate(receipt_records):
        if record.get("provider_call_expected") is not False:
            continue
        attempt_id = record.get("attempt_id")
        sequence = record.get("sequence")
        if isinstance(attempt_id, str) and attempt_id:
            identity = ("attempt", attempt_id)
        elif isinstance(sequence, int) and not isinstance(sequence, bool):
            identity = ("sequence", sequence)
        else:
            identity = ("record", index)
        unexpected_receipts.add(identity)
    if receipts["provider_call_expected_false_observed"] != len(unexpected_receipts):
        raise EvidenceBundleError(
            "router_receipts unexpected-call count does not match its records"
        )
    if not isinstance(normalized["scoring"], Mapping):
        raise EvidenceBundleError("scoring must contain the scorer output")

    for name in ("state_snapshots", "zone_trace"):
        value = normalized[name]
        if value is None or (
            isinstance(value, (Mapping, list, tuple, str)) and len(value) == 0
        ):
            raise EvidenceBundleError("%s must be present or explicitly described" % name)
    _ensure_json_value(normalized["exact_packets"], "exact_packets")
    _ensure_json_value(normalized["state_snapshots"], "state_snapshots")
    _ensure_json_value(normalized["zone_trace"], "zone_trace")
    _ensure_json_value(normalized["expected_observed_checks"], "expected_observed_checks")
    _ensure_json_value(normalized["cap_counts"], "cap_counts")
    _ensure_json_value(normalized["router_receipts"], "router_receipts")
    _ensure_json_value(normalized["scoring"], "scoring")
    return normalized


def _validate_cap_counts(cap_counts: Mapping[str, Any]) -> None:
    required_values = (
        "row_attempts",
        "row_elapsed_seconds",
        "matrix_attempts",
        "matrix_elapsed_seconds",
        "caps",
    )
    if any(name not in cap_counts for name in required_values):
        raise EvidenceBundleError("cap_counts must include actual row/matrix counts and caps")
    caps = cap_counts["caps"]
    expected_caps = {
        "row_attempts": ROW_ATTEMPT_CAP,
        "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
        "matrix_attempts": MATRIX_ATTEMPT_CAP,
        "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
    }
    if not isinstance(caps, Mapping) or dict(caps) != expected_caps:
        raise EvidenceBundleError("cap_counts must preserve the preregistered caps")
    for name in required_values[:-1]:
        value = cap_counts[name]
        if value == "unknown":
            continue
        if name.endswith("attempts"):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise EvidenceBundleError("attempt counts must be non-negative integers or unknown")
        elif (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise EvidenceBundleError("elapsed counts must be non-negative numbers or unknown")


def _validate_verdict(
    verdict: str,
    provenance: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    packet_status: str,
    row: Mapping[str, Any],
) -> None:
    if verdict != "PASS":
        return
    router_receipts = artifacts["router_receipts"]
    if router_receipts.get("evidence_status") != "recorded":
        raise EvidenceBundleError("PASS requires recorded router receipt evidence")
    if router_receipts.get("provider_call_expected_false_observed") != 0:
        raise EvidenceBundleError("PASS is forbidden after an unexpected lifecycle provider call")
    if packet_status == "not_applicable" and row.get("arm") == "A":
        if not _valid_arm_a_noop_record(artifacts["exact_packets"]["records"]):
            raise EvidenceBundleError("arm A requires an explicit no-op observation")
    elif packet_status != "recorded":
        raise EvidenceBundleError("PASS is forbidden when turn evidence is degraded or missing")
    route_identity = provenance["route_identity"]
    requested = route_identity["requested"]
    resolved = route_identity["resolved"]
    if not requested or not resolved or len(requested) != len(resolved):
        raise EvidenceBundleError("PASS requires requested and resolved routes for every call")
    for route in requested + resolved:
        if (
            not isinstance(route.get("model"), str)
            or not route["model"].strip()
            or not isinstance(route.get("provider"), str)
            or not route["provider"].strip()
            or route.get("fallback") is None
        ):
            raise EvidenceBundleError("PASS requires complete per-call route identity")
        if any(
            isinstance(route.get(field), str)
            and route[field].strip().lower() in ("unknown", "missing", "not recorded")
            for field in ("model", "provider", "fallback")
        ):
            raise EvidenceBundleError("PASS cannot use unknown route identity")

    checks = artifacts["expected_observed_checks"]
    if not checks or any(check["passed"] is not True for check in checks):
        raise EvidenceBundleError("PASS requires every expected/observed check to pass")
    cap_counts = artifacts["cap_counts"]
    limits = {
        "row_attempts": ROW_ATTEMPT_CAP,
        "row_elapsed_seconds": ROW_WALL_TIME_CAP_SECONDS,
        "matrix_attempts": MATRIX_ATTEMPT_CAP,
        "matrix_elapsed_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
    }
    for name, limit in limits.items():
        value = cap_counts[name]
        if value == "unknown" or value >= limit:
            raise EvidenceBundleError("PASS requires known counts below every cap")
    for name in ("transcript", "logs", "state_snapshots", "zone_trace"):
        if _has_missing_status(artifacts[name]):
            raise EvidenceBundleError("PASS is forbidden when required evidence is marked missing")


def _turn_evidence_status(
    records: Sequence[Mapping[str, Any]],
    *,
    arm: Optional[str] = None,
    declared_status: Any = None,
) -> str:
    if (
        arm == "A"
        and declared_status == "not_applicable"
        and _valid_arm_a_noop_record(records)
    ):
        return "not_applicable"
    if any(record.get("evidence_status") == "degraded" for record in records):
        return "degraded"
    if not records:
        return "missing"
    packet_records = [record for record in records if record.get("event_type") == "packet_use"]
    if not packet_records:
        return "missing"
    if any(not _packet_record_is_complete(record) for record in packet_records):
        return "missing"
    if any(record.get("evidence_status") != "recorded" for record in records):
        return "missing"
    return "recorded"


def _valid_arm_a_noop_record(records: Sequence[Mapping[str, Any]]) -> bool:
    return (
        len(records) == 1
        and records[0].get("event_type") == "arm_a_noop"
        and records[0].get("adapter_installed") is False
        and records[0].get("evidence_status") == "recorded"
    )


def _packet_record_is_complete(record: Mapping[str, Any]) -> bool:
    if record.get("packet_status") != "present":
        return False
    packet = record.get("packet_ascii")
    packet_hash = record.get("packet_sha256")
    if not isinstance(packet, str) or not isinstance(packet_hash, str):
        return False
    try:
        packet_bytes = packet.encode("ascii")
    except UnicodeEncodeError:
        raise EvidenceBundleError("packet evidence must preserve ASCII packet bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", packet_hash):
        raise EvidenceBundleError("packet evidence hash must be a lowercase SHA-256")
    if hashlib.sha256(packet_bytes).hexdigest() != packet_hash:
        raise EvidenceBundleError("packet evidence hash does not match exact packet bytes")
    return True


def _verify_packet_record(record: Mapping[str, Any]) -> None:
    if record.get("event_type") == "packet_use" and record.get("packet_status") == "present":
        _packet_record_is_complete(record)


def _validate_token(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or value in (".", "..")
        or not _TOKEN_PATTERN.fullmatch(value)
    ):
        raise EvidenceBundleError("%s must be a safe path token" % label)


def _normalize_base_root(base_root: Optional[Union[str, Path]]) -> Path:
    raw = DEFAULT_EVIDENCE_ROOT if base_root is None else Path(base_root)
    if "\\" in str(raw) or ".." in raw.parts:
        raise EvidenceBundleError("bundle root must be a safe project-relative tmp path")
    if raw.is_absolute():
        try:
            relative = raw.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise EvidenceBundleError("bundle root must be beneath the project tmp directory") from exc
    else:
        relative = raw
    if not relative.parts or relative.parts[0] != "tmp":
        raise EvidenceBundleError("bundle root must be beneath the project tmp directory")
    if "." in relative.parts:
        raise EvidenceBundleError("bundle root must not contain dot components")
    return relative


def _project_tmp_path(
    path: Union[str, Path], label: str
) -> tuple[Path, Path]:
    raw = Path(path)
    if "\\" in str(raw) or ".." in raw.parts:
        raise EvidenceBundleError("%s must use a project-relative tmp path" % label)
    if raw.is_absolute():
        try:
            relative = raw.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise EvidenceBundleError("%s must be beneath project tmp" % label) from exc
    else:
        relative = raw
    if not relative.parts or relative.parts[0] != "tmp":
        raise EvidenceBundleError("%s must be beneath project tmp" % label)
    return relative, PROJECT_ROOT / relative


def _ensure_directory(path: Path) -> None:
    _reject_symlink_components(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvidenceBundleError("evidence directory cannot be created") from exc
    _reject_symlink_components(path)
    if not path.is_dir():
        raise EvidenceBundleError("evidence path is not a directory")
    try:
        path.resolve(strict=True).relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvidenceBundleError("evidence path escaped project tmp") from exc


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                raise EvidenceBundleError("mapping-pilot evidence paths must not traverse symlinks")
        except OSError as exc:
            raise EvidenceBundleError("mapping-pilot evidence path cannot be inspected") from exc


def _reject_duplicate_row(gate_directory: Path, row_id: str) -> None:
    if not gate_directory.exists():
        return
    try:
        children = sorted(gate_directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise EvidenceBundleError("gate evidence directory cannot be listed") from exc
    for child in children:
        if child.is_symlink():
            raise EvidenceBundleError("existing gate evidence contains a symlink")
        if not child.is_dir():
            continue
        row_path = child / _ARTIFACT_FILENAMES["row"]
        manifest_path = child / "manifest.json"
        if row_path.is_symlink() or manifest_path.is_symlink():
            raise EvidenceBundleError("existing bundle metadata is unsafe")
        if not row_path.exists():
            if manifest_path.exists():
                raise EvidenceBundleError("existing bundle has no row identity")
            raise EvidenceBundleError("incomplete bundle has no row identity; reuse is refused")
        try:
            existing_row = json.loads(
                row_path.read_text(encoding="ascii"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise EvidenceBundleError("existing bundle row identity is invalid") from exc
        if not isinstance(existing_row, Mapping) or not isinstance(
            existing_row.get("row_id"), str
        ):
            raise EvidenceBundleError("existing bundle row identity is invalid")
        if existing_row["row_id"] == row_id:
            raise EvidenceBundleError("row_id already has a bundle in this gate")


def _hash_bundle_files(bundle_directory: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    try:
        entries = sorted(bundle_directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise EvidenceBundleError("bundle directory cannot be inspected") from exc
    expected_names = set(_ARTIFACT_FILENAMES.values())
    actual_names: set[str] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise EvidenceBundleError("bundle contains an unsafe artifact")
        if entry.name not in expected_names:
            raise EvidenceBundleError("bundle contains an unexpected artifact")
        actual_names.add(entry.name)
        hashes[entry.name] = hashlib.sha256(entry.read_bytes()).hexdigest()
    if actual_names != expected_names - {"manifest.json"}:
        raise EvidenceBundleError("bundle is missing a required artifact")
    return hashes


def _write_json(relative_path: Path, payload: Any) -> None:
    _ensure_json_value(payload, relative_path.name)
    from utils.file_operations import safe_write_json

    wrote = safe_write_json(
        str(relative_path),
        payload,
        create_backup=False,
        acquire_lock=True,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    )
    if not wrote:
        raise EvidenceBundleError("atomic JSON artifact write failed")


def _write_ascii_text(relative_path: Path, value: str) -> None:
    encoded = value.encode("ascii", errors="backslashreplace")
    try:
        with relative_path.open("xb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise EvidenceBundleError("text artifact write failed") from exc


def _ensure_json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EvidenceBundleError("%s must contain finite JSON data" % label) from exc


def _reject_secret_payload(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if _SECRET_FIELD.search(str(key)) and normalized_key not in _SAFE_SCORING_FIELDS:
                raise EvidenceBundleError("secret-like fields are not allowed in evidence")
            _reject_secret_payload(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _reject_secret_payload(child)
        return
    if isinstance(value, Path):
        if value.name.lower() == "config.py":
            raise EvidenceBundleError("config.py content is not an evidence artifact")
        return
    if isinstance(value, str) and _SECRET_TEXT.search(value):
        raise EvidenceBundleError("secret-like text is not allowed in evidence")
    if isinstance(value, bytes):
        try:
            text = value.decode("ascii")
        except UnicodeDecodeError:
            return
        if _SECRET_TEXT.search(text):
            raise EvidenceBundleError("secret-like text is not allowed in evidence")


def _has_missing_status(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in ("status", "evidence_status") and isinstance(child, str):
                if child.strip().lower() in ("missing", "degraded", "incomplete", "unknown"):
                    return True
            if _has_missing_status(child):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_has_missing_status(child) for child in value)
    return False


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value")
