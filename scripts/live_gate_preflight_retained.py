# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Reconcile a supervised row against its retained provider-free evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVIDENCE_BYTES = 2_000_000


class RetainedEvidenceError(ValueError):
    """Raised when retained row evidence is missing, inconsistent, or unsafe."""


def validate_retained_supervised_evidence(
    result: Mapping[str, Any],
    *,
    plan: Any,
    fixture_id: str,
    lifecycle: str,
    intended_identity: Mapping[str, Any],
    source_sha: str,
    row_run_id: str,
    preflight_run_id: str,
) -> dict[str, Any]:
    """Validate retained sidecars and return a summary derived from disk."""
    from scripts import live_gate_preflight_profile_runner as runner
    from scripts import live_gate_preflight_profiles as profiles

    if not _valid_run_identity(row_run_id) or not _valid_run_identity(preflight_run_id):
        raise RetainedEvidenceError("row evidence run identity is invalid")
    evidence_directory = (
        Path("tmp/router-rollout/live-gate-preflight")
        / preflight_run_id
        / "preflight"
        / "rows"
        / row_run_id
    )
    evidence_path = (evidence_directory / "profile-evidence.json").as_posix()
    digest = result.get("evidence_sha256")
    if (
        set(result) != {"evidence", "evidence_path", "evidence_sha256"}
        or result.get("evidence_path") != evidence_path
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
    ):
        raise RetainedEvidenceError("row evidence path or hash is invalid")
    evidence, _raw = _read_hashed_json(evidence_path, digest, "profile evidence")
    returned_evidence = result.get("evidence")
    if not isinstance(returned_evidence, Mapping) or not _strict_json_equal(
        dict(returned_evidence), evidence
    ):
        raise RetainedEvidenceError("returned profile summary differs from retained evidence")

    profile_id = next(
        (
            profile.get("profile_id")
            for profile in plan.lifecycle_profiles
            if profile.get("fixture_id") == fixture_id
        ),
        None,
    )
    if not isinstance(profile_id, str) or not profile_id:
        raise RetainedEvidenceError("declared fixture-party profile identity is missing")
    row_metadata = {
        plan.row_id: {
            "arm": plan.arm,
            "fixture_ids": list(plan.fixture_ids),
            "party_size": plan.party_size,
        }
    }
    try:
        profiles._validate_profile_evidence(
            PROJECT_ROOT,
            evidence_path=evidence_path,
            evidence_sha256=digest,
            profile_id=profile_id,
            fixture_id=fixture_id,
            party_size=plan.party_size,
            lifecycle=lifecycle,
            planned_row_ids=[plan.row_id],
            row_metadata=row_metadata,
            source_sha=source_sha,
            command=intended_identity.get("command"),
            pythonpath=intended_identity.get("pythonpath"),
            call_count=evidence.get("call_count"),
            call_sites=evidence.get("call_sites"),
            evidence_directory=PROJECT_ROOT / evidence_directory,
        )
    except profiles.ProfileValidationError as exc:
        raise RetainedEvidenceError(
            "retained profile evidence failed validation: %s" % exc
        ) from exc

    driver_exchange = evidence["driver_exchange"]
    call_count = evidence["call_count"]
    call_sites = evidence["call_sites"]
    controller_pid = evidence["process_census"]["controller_pid"]
    worker_pid = evidence["process_census"]["host_worker_pid"]
    worker_stop_proof = _read_and_validate_worker_shutdown(
        evidence,
        evidence_directory=evidence_directory,
        run_id=row_run_id,
        source_sha=source_sha,
        command=intended_identity.get("command"),
        pythonpath=intended_identity.get("pythonpath"),
        controller_pid=controller_pid,
        worker_pid=worker_pid,
        call_count=call_count,
        calls=evidence["calls"],
        profiles=profiles,
        runner=runner,
    )
    teardown_proof = _read_and_validate_teardown(
        evidence,
        evidence_directory=evidence_directory,
        evidence_path=evidence_path,
        row_run_id=row_run_id,
        preflight_run_id=preflight_run_id,
        source_sha=source_sha,
        controller_pid=controller_pid,
        worker_pid=worker_pid,
        worker_stop_proof=worker_stop_proof,
        runner=runner,
    )

    return {
        "outcome": "completed",
        "first_exchange": dict(driver_exchange),
        "call_count": call_count,
        "call_sites": [dict(site) for site in call_sites],
        "provider_environment_keys_blank": True,
        "proxy_values_blank": True,
        "real_project_config_loaded": False,
        "invocation_identity_status": "matched",
        "process_census_complete": True,
        "worker_teardown": {
            "server_stopped": True,
            "port_8360_free": True,
            "port_8370_free": True,
            "shared_live_window_lock_released": True,
            "guard_active": True,
            "call_count": call_count,
            "teardown_evidence_sha256": teardown_proof["sha256"],
        },
    }


def _read_and_validate_worker_shutdown(
    evidence: Mapping[str, Any],
    *,
    evidence_directory: Path,
    run_id: str,
    source_sha: str,
    command: Any,
    pythonpath: Any,
    controller_pid: int,
    worker_pid: int,
    call_count: int,
    calls: list[Any],
    profiles: Any,
    runner: Any,
) -> dict[str, Any]:
    worker_path = (evidence_directory / "worker-result.json").as_posix()
    request_path = (evidence_directory / "shutdown-request.json").as_posix()
    worker, worker_raw = _read_json(worker_path, "worker result")
    request, request_raw = _read_json(request_path, "shutdown request")
    worker_fields = {
        "schema_version",
        "run_id",
        "source_sha",
        "command",
        "pythonpath",
        "invocation_identity",
        "interpreter",
        "startup_canary_report",
        "guard_active",
        "provider_environment_keys_blank",
        "sandbox_provider_key_placeholder",
        "proxy_values_blank",
        "real_project_config_loaded",
        "sandbox_config_loaded",
        "startup_guard_from_sitecustomize",
        "sandbox_config_origin_guard_active",
        "server_returned",
        "interrupted",
        "graceful_shutdown_requested",
        "shutdown_request",
        "shutdown_signal_received_at_ns",
        "outcome",
        "failure_code",
        "stub_failure_code",
        "call_count",
        "calls",
    }
    if (
        set(worker) != worker_fields
        or type(worker.get("schema_version")) is not int
        or worker.get("schema_version") != 1
        or worker.get("run_id") != run_id
        or worker.get("source_sha") != source_sha
        or not _strict_json_equal(worker.get("command"), command)
        or worker.get("pythonpath") != pythonpath
        or not _strict_json_equal(
            worker.get("invocation_identity"), evidence.get("invocation_identity")
        )
        or not _strict_json_equal(
            worker.get("interpreter"), evidence.get("worker_interpreter")
        )
        or worker.get("guard_active") is not True
        or worker.get("provider_environment_keys_blank") is not True
        or worker.get("sandbox_provider_key_placeholder")
        != profiles.SANDBOX_PROVIDER_KEY_PLACEHOLDER
        or worker.get("proxy_values_blank") is not True
        or worker.get("real_project_config_loaded") is not False
        or worker.get("sandbox_config_loaded") is not True
        or worker.get("startup_guard_from_sitecustomize") is not True
        or worker.get("sandbox_config_origin_guard_active") is not True
        or type(worker.get("server_returned")) is not bool
        or worker.get("interrupted") is not True
        or worker.get("graceful_shutdown_requested") is not True
        or worker.get("outcome") != "completed"
        or worker.get("failure_code") is not None
        or worker.get("stub_failure_code") is not None
        or type(worker.get("call_count")) is not int
        or worker.get("call_count") != call_count
        or not _strict_json_equal(worker.get("calls"), calls)
    ):
        raise RetainedEvidenceError("retained worker result is incomplete or contradictory")

    received_at_ns = worker.get("shutdown_signal_received_at_ns")
    if (
        type(received_at_ns) is not int
        or not runner._valid_worker_shutdown_request(
            request,
            run_id=run_id,
            worker_pid=worker_pid,
            process_group_id=worker_pid,
            signal_number=int(signal.SIGINT),
            signal_received_at_ns=received_at_ns,
        )
        or request.get("controller_pid") != controller_pid
        or request.get("readiness_succeeded") is not True
        or request.get("exchange_succeeded") is not True
        or not _strict_json_equal(worker.get("shutdown_request"), request)
    ):
        raise RetainedEvidenceError("retained attributed shutdown request is invalid")

    shutdown = evidence.get("worker_shutdown")
    if (
        not isinstance(shutdown, Mapping)
        or shutdown.get("server_returned") is not worker["server_returned"]
        or shutdown.get("interrupted") is not worker["interrupted"]
        or shutdown.get("graceful_shutdown_requested")
        is not worker["graceful_shutdown_requested"]
        or type(shutdown.get("signal_received_at_ns")) is not int
        or shutdown.get("signal_received_at_ns") != received_at_ns
        or not _strict_json_equal(shutdown.get("request"), request)
    ):
        raise RetainedEvidenceError("retained worker shutdown summary differs from files")

    try:
        startup_report = json.loads(
            worker.get("startup_canary_report", ""),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise RetainedEvidenceError("retained worker startup canary report is malformed") from exc
    startup_canary = next(
        item
        for item in evidence["process_canaries"]
        if item.get("canary_stage") == "host-startup"
    )
    expected_report = {
        key: value for key, value in startup_canary.items() if key != "canary_stage"
    }
    if not _strict_json_equal(startup_report, expected_report):
        raise RetainedEvidenceError("retained worker startup canary differs from journal")

    return {
        "server_returned": worker["server_returned"],
        "interrupted": worker["interrupted"],
        "graceful_shutdown_requested": worker["graceful_shutdown_requested"],
        "signal_received_at_ns": received_at_ns,
        "shutdown_request": request,
        "shutdown_request_path": request_path,
        "shutdown_request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "worker_result_path": worker_path,
        "worker_result_sha256": hashlib.sha256(worker_raw).hexdigest(),
    }


def _read_and_validate_teardown(
    evidence: Mapping[str, Any],
    *,
    evidence_directory: Path,
    evidence_path: str,
    row_run_id: str,
    preflight_run_id: str,
    source_sha: str,
    controller_pid: int,
    worker_pid: int,
    worker_stop_proof: Mapping[str, Any],
    runner: Any,
) -> dict[str, str]:
    descriptor = evidence.get("teardown_evidence")
    expected_path = (evidence_directory / "teardown-evidence.json").as_posix()
    if (
        not isinstance(descriptor, Mapping)
        or set(descriptor) != {"path", "sha256"}
        or descriptor.get("path") != expected_path
        or not isinstance(descriptor.get("sha256"), str)
        or _SHA256.fullmatch(descriptor["sha256"]) is None
    ):
        raise RetainedEvidenceError("retained teardown evidence path or hash is invalid")
    sidecar, _sidecar_raw = _read_hashed_json(
        expected_path, descriptor["sha256"], "teardown evidence"
    )
    expected_fields = {
        "schema_version",
        "run_id",
        "preflight_run_id",
        "source_sha",
        "runner_source_sha256",
        "booking_id",
        "controller_pid",
        "worker_stop",
        "port_observations",
        "socket_census",
        "shared_lock",
    }
    runner_source_sha256 = hashlib.sha256(
        (PROJECT_ROOT / "scripts" / "live_gate_preflight_profile_runner.py").read_bytes()
    ).hexdigest()
    if (
        set(sidecar) != expected_fields
        or type(sidecar.get("schema_version")) is not int
        or sidecar.get("schema_version") != 1
        or sidecar.get("run_id") != row_run_id
        or sidecar.get("preflight_run_id") != preflight_run_id
        or sidecar.get("source_sha") != source_sha
        or sidecar.get("runner_source_sha256") != runner_source_sha256
        or sidecar.get("controller_pid") != controller_pid
        or not isinstance(sidecar.get("booking_id"), str)
        or runner._BOOKING_ID.fullmatch(sidecar.get("booking_id", "")) is None
    ):
        raise RetainedEvidenceError("retained teardown evidence identity differs")

    worker_stop = sidecar.get("worker_stop")
    worker_fields = {
        "observed",
        "worker_pid",
        "process_group_id",
        "stop_operation",
        "requested_signal",
        "shutdown_request_path",
        "shutdown_request_sha256",
        "worker_result_path",
        "worker_result_sha256",
        "server_returned",
        "interrupted",
        "graceful_shutdown_requested",
        "signal_received_at_ns",
        "returncode",
        "reaped",
        "observed_at_ns",
    }
    if (
        not isinstance(worker_stop, Mapping)
        or set(worker_stop) != worker_fields
        or worker_stop.get("observed") is not True
        or worker_stop.get("worker_pid") != worker_pid
        or worker_stop.get("process_group_id") != worker_pid
        or worker_stop.get("stop_operation") != "owned-process-group-wait"
        or worker_stop.get("requested_signal") != int(signal.SIGINT)
        or worker_stop.get("shutdown_request_path")
        != worker_stop_proof.get("shutdown_request_path")
        or worker_stop.get("shutdown_request_sha256")
        != worker_stop_proof.get("shutdown_request_sha256")
        or worker_stop.get("worker_result_path")
        != worker_stop_proof.get("worker_result_path")
        or worker_stop.get("worker_result_sha256")
        != worker_stop_proof.get("worker_result_sha256")
        or worker_stop.get("server_returned")
        is not worker_stop_proof.get("server_returned")
        or worker_stop.get("interrupted") is not True
        or worker_stop.get("graceful_shutdown_requested") is not True
        or worker_stop.get("signal_received_at_ns")
        != worker_stop_proof.get("signal_received_at_ns")
        or type(worker_stop.get("returncode")) is not int
        or worker_stop.get("returncode") != 0
        or worker_stop.get("reaped") is not True
        or type(worker_stop.get("observed_at_ns")) is not int
        or worker_stop.get("observed_at_ns")
        < worker_stop_proof.get("signal_received_at_ns", 0)
    ):
        raise RetainedEvidenceError("retained worker stop proof is missing or contradictory")

    observations = sidecar.get("port_observations")
    if not isinstance(observations, Mapping) or set(observations) != {"8360", "8370"}:
        raise RetainedEvidenceError("retained teardown port observations are incomplete")
    for port in (8360, 8370):
        observation = observations[str(port)]
        expected_observation_fields = {
            "schema_version",
            "method",
            "transport",
            "address",
            "port",
            "reuse_address",
            "observed_at_ns",
            "socket_created",
            "bind_attempted",
            "bind_succeeded",
            "socket_closed",
            "result",
            "error_errno",
            "error_type",
            "observation_complete",
        }
        if (
            not isinstance(observation, Mapping)
            or set(observation) != expected_observation_fields
            or type(observation.get("schema_version")) is not int
            or observation.get("schema_version") != 1
            or observation.get("method") != "exclusive-bind-close"
            or observation.get("transport") != "tcp"
            or observation.get("address") != "127.0.0.1"
            or type(observation.get("port")) is not int
            or observation.get("port") != port
            or observation.get("reuse_address") is not False
            or type(observation.get("observed_at_ns")) is not int
            or observation.get("observed_at_ns") <= 0
            or observation.get("result") != "free"
            or observation.get("socket_created") is not True
            or observation.get("bind_attempted") is not True
            or observation.get("bind_succeeded") is not True
            or observation.get("socket_closed") is not True
            or observation.get("error_errno") is not None
            or observation.get("error_type") is not None
            or observation.get("observation_complete") is not True
        ):
            raise RetainedEvidenceError(
                "retained teardown port %d is occupied or unobservable" % port
            )

    census_reference = sidecar.get("socket_census")
    census = evidence.get("process_census")
    samples = census.get("socket_pid_samples") if isinstance(census, Mapping) else None
    after_teardown = (
        samples[2]
        if isinstance(samples, list) and len(samples) == 3 and isinstance(samples[2], Mapping)
        else None
    )
    if (
        not isinstance(census_reference, Mapping)
        or set(census_reference)
        != {"phase", "path", "sha256", "observed", "pids", "listener_pids"}
        or census_reference.get("phase") != "after_teardown"
        or not isinstance(after_teardown, Mapping)
        or census_reference.get("path") != after_teardown.get("evidence_path")
        or census_reference.get("sha256") != after_teardown.get("evidence_sha256")
        or census_reference.get("observed") is not True
        or after_teardown.get("observed") is not True
        or census_reference.get("pids") != after_teardown.get("pids")
        or census_reference.get("listener_pids") != after_teardown.get("listener_pids")
        or census_reference.get("listener_pids") != []
    ):
        raise RetainedEvidenceError("retained teardown socket census is missing or contradictory")
    sample_path = census_reference.get("path")
    sample_sha256 = census_reference.get("sha256")
    if not isinstance(sample_path, str) or not isinstance(sample_sha256, str):
        raise RetainedEvidenceError("retained teardown socket census reference is invalid")
    sample, _sample_raw = _read_hashed_json(
        sample_path, sample_sha256, "after-teardown socket census"
    )
    rows = sample.get("run_owned_rows")
    if (
        sample.get("run_id") != row_run_id
        or sample.get("phase") != "after_teardown"
        or sample.get("observed") is not True
        or sample.get("failure_code") is not None
        or not isinstance(rows, list)
        or _active_listener_pids(rows, 8360)
        or _active_listener_pids(rows, 8370)
    ):
        raise RetainedEvidenceError("retained teardown census has an active listener or is unobservable")

    shared_lock = sidecar.get("shared_lock")
    lock_fields = {
        "release_attempted",
        "lock_directory_removed",
        "release_succeeded",
        "booking_record",
        "release_record",
        "durable_record",
    }
    if (
        not isinstance(shared_lock, Mapping)
        or set(shared_lock) != lock_fields
        or shared_lock.get("release_attempted") is not True
        or shared_lock.get("lock_directory_removed") is not True
        or shared_lock.get("release_succeeded") is not True
    ):
        raise RetainedEvidenceError("retained shared lock release is missing or incomplete")
    booking_record = shared_lock.get("booking_record")
    release_record = shared_lock.get("release_record")
    durable_reference = shared_lock.get("durable_record")
    release_timestamp = (
        runner._parse_utc_timestamp(release_record.get("released_at_utc"))
        if isinstance(release_record, Mapping)
        else None
    )
    if (
        not isinstance(booking_record, Mapping)
        or not isinstance(release_record, Mapping)
        or release_timestamp is None
        or not runner._valid_live_window_lock_record(booking_record, now=release_timestamp)
        or not runner._valid_lock_release_record(
            release_record, str(booking_record.get("booking_id", ""))
        )
        or not all(
            release_record.get(key) == value for key, value in booking_record.items()
        )
        or booking_record.get("run_id") != row_run_id
        or booking_record.get("source_sha") != source_sha
        or booking_record.get("fixture_id") != evidence.get("fixture_id")
        or booking_record.get("party_size") != evidence.get("party_size")
        or booking_record.get("lifecycle") != evidence.get("lifecycle")
        or booking_record.get("planned_row_id") != evidence.get("planned_row_id")
        or booking_record.get("booking_id") != sidecar.get("booking_id")
        or release_record.get("evidence_path") != evidence_path
        or release_record.get("teardown_evidence_path") != expected_path
        or release_record.get("server_stopped") is not True
        or release_record.get("ports_free")
        != {str(port): observations[str(port)].get("result") == "free" for port in (8360, 8370)}
        or release_record.get("after_teardown_socket_sample_observed") is not True
        or release_record.get("after_teardown_socket_pids")
        != census_reference.get("pids")
        or release_record.get("after_teardown_socket_sample_path")
        != census_reference.get("path")
        or release_record.get("after_teardown_socket_sample_sha256")
        != census_reference.get("sha256")
    ):
        raise RetainedEvidenceError("retained shared lock release record identity differs")
    actual_record, durable_digest = _read_durable_release_record(
        durable_reference, release_record=release_record, runner=runner
    )
    if not _strict_json_equal(actual_record, dict(release_record)):
        raise RetainedEvidenceError("durable shared lock release record differs from sidecar")
    summary = evidence.get("teardown")
    expected_summary = {
        "server_stopped": True,
        "port_8360_free": True,
        "port_8370_free": True,
        "lock_released": True,
    }
    if not _strict_json_equal(summary, expected_summary):
        raise RetainedEvidenceError("retained teardown summary contradicts independent proof")
    return {"sha256": descriptor["sha256"], "durable_record_sha256": durable_digest}


def _active_listener_pids(rows: list[Any], port: int) -> list[int]:
    listeners: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        local = row.get("local")
        if (
            row.get("protocol") in ("tcp", "tcp4", "tcp6")
            and row.get("state") == "LISTEN"
            and isinstance(local, Mapping)
            and local.get("port") == port
            and type(row.get("pid")) is int
        ):
            listeners.append(row["pid"])
    return listeners


def _read_durable_release_record(
    reference: Any,
    *,
    release_record: Mapping[str, Any],
    runner: Any,
) -> tuple[dict[str, Any], str]:
    fields = {"path", "byte_offset", "byte_length", "line_sha256"}
    if not isinstance(reference, Mapping) or set(reference) != fields:
        raise RetainedEvidenceError("durable shared lock release reference is invalid")
    expected_path = runner._git_common_directory() / "neq-coordination" / "bookings.log"
    try:
        expected_relative = expected_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as exc:
        raise RetainedEvidenceError("durable shared lock release path is outside the project") from exc
    if (
        reference.get("path") != expected_relative
        or type(reference.get("byte_offset")) is not int
        or reference.get("byte_offset") < 0
        or type(reference.get("byte_length")) is not int
        or reference.get("byte_length") < 2
        or reference.get("byte_length") > _MAX_EVIDENCE_BYTES
        or not isinstance(reference.get("line_sha256"), str)
        or _SHA256.fullmatch(reference["line_sha256"]) is None
    ):
        raise RetainedEvidenceError("durable shared lock release reference is unsafe")
    path = PROJECT_ROOT / expected_relative
    cursor = PROJECT_ROOT
    for part in PurePosixPath(expected_relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RetainedEvidenceError("durable shared lock release path traverses a symlink")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        offset = reference["byte_offset"]
        length = reference["byte_length"]
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size < offset + length:
            raise RetainedEvidenceError("durable shared lock release log is invalid")
        if offset:
            os.lseek(descriptor, offset - 1, os.SEEK_SET)
            if os.read(descriptor, 1) != b"\n":
                raise RetainedEvidenceError("durable shared lock release offset is not a line boundary")
        os.lseek(descriptor, offset, os.SEEK_SET)
        raw = os.read(descriptor, length)
        if len(raw) != length or not raw.endswith(b"\n"):
            raise RetainedEvidenceError("durable shared lock release line is incomplete")
    except RetainedEvidenceError:
        raise
    except OSError as exc:
        raise RetainedEvidenceError("durable shared lock release log is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != reference["line_sha256"]:
        raise RetainedEvidenceError("durable shared lock release line hash differs")
    record = _decode_json(raw[:-1], "durable shared lock release record")
    if (
        not isinstance(record, Mapping)
        or not _strict_json_equal(dict(record), dict(release_record))
        or json.dumps(dict(record), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n" != raw
    ):
        raise RetainedEvidenceError("durable shared lock release line is contradictory")
    return dict(record), digest


def _read_hashed_json(
    relative_path: str, digest: str, label: str
) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(relative_path, label)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RetainedEvidenceError("retained %s hash differs" % label)
    value = _decode_json(raw, label)
    if not isinstance(value, Mapping):
        raise RetainedEvidenceError("retained %s is not an object" % label)
    return dict(value), raw


def _read_json(relative_path: str, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(relative_path, label)
    value = _decode_json(raw, label)
    if not isinstance(value, Mapping):
        raise RetainedEvidenceError("retained %s is not an object" % label)
    return dict(value), raw


def _decode_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RetainedEvidenceError("retained %s is malformed" % label) from exc


def _read_bytes(relative_path: str, label: str) -> bytes:
    path = _safe_project_tmp_file(relative_path)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < 1
            or metadata.st_size > _MAX_EVIDENCE_BYTES
        ):
            raise RetainedEvidenceError(
                "retained %s file is not bounded regular evidence" % label
            )
        chunks: list[bytes] = []
        remaining = _MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64_000, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_EVIDENCE_BYTES:
            raise RetainedEvidenceError("retained %s exceeds the size limit" % label)
        return raw
    except RetainedEvidenceError:
        raise
    except OSError as exc:
        raise RetainedEvidenceError("retained %s file is unavailable" % label) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _safe_project_tmp_file(relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in relative_path
        or not relative.parts
        or relative.parts[0] != "tmp"
    ):
        raise RetainedEvidenceError("retained evidence path is unsafe")
    root = PROJECT_ROOT.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RetainedEvidenceError("retained evidence path traverses a symlink")
    try:
        candidate.parent.resolve(strict=True).relative_to(
            (root / "tmp").resolve(strict=True)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise RetainedEvidenceError("retained evidence path escapes tmp/") from exc
    return candidate


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _strict_json_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _reject_constant(value: str) -> Any:
    raise ValueError("invalid JSON constant: " + value)


def _valid_run_identity(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value
    ) is not None
