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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVIDENCE_BYTES = 2_000_000
_MAX_PROFILE_ARTIFACT_BYTES = 512_000
_AREA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_MODULE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}$")


def retain_summary_child_artifacts(
    sandbox_root: Path,
    evidence_directory: Path,
    *,
    run_id: str,
    summary_child: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Retain summary-child inputs and outputs before the sandbox is removed."""
    if (
        not _valid_run_identity(run_id)
        or not isinstance(summary_child, Mapping)
        or type(summary_child.get("launch_count")) is not int
        or type(summary_child.get("record_count")) is not int
    ):
        raise RetainedEvidenceError("summary child retention identity is invalid")
    launches = summary_child.get("launches")
    if not isinstance(launches, list) or len(launches) != summary_child["launch_count"]:
        raise RetainedEvidenceError("summary child retention launches are malformed")
    if summary_child["launch_count"] == 0:
        if summary_child["record_count"] != 0 or launches:
            raise RetainedEvidenceError("summary child empty retention is contradictory")
        return None

    sandbox_relative = PurePosixPath("tmp/combat_capture")
    sandbox = _safe_project_tmp_directory(sandbox_relative.as_posix())
    try:
        requested_sandbox = sandbox_root.absolute()
        if requested_sandbox != sandbox:
            raise RetainedEvidenceError("summary child sandbox identity differs")
        evidence_relative = evidence_directory.absolute().relative_to(PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RetainedEvidenceError("summary child evidence directory is unsafe") from exc
    if not evidence_relative.parts or evidence_relative.parts[0] != "tmp":
        raise RetainedEvidenceError("summary child evidence directory is outside tmp/")
    evidence_directory_path = _safe_project_tmp_directory(
        evidence_relative.as_posix()
    )
    expected_child_evidence_path = (
        evidence_relative / "adv-summary-child.jsonl"
    ).as_posix()
    if summary_child.get("evidence_path") != expected_child_evidence_path:
        raise RetainedEvidenceError("summary child evidence path differs")
    child_raw = _read_bounded_capture_file(
        expected_child_evidence_path, "summary child evidence"
    )
    if (
        hashlib.sha256(child_raw).hexdigest()
        != summary_child.get("evidence_sha256")
    ):
        raise RetainedEvidenceError("summary child evidence hash differs")
    records = _decode_json_lines(child_raw, "summary child evidence")
    if (
        len(records) != summary_child["record_count"]
        or len(records) != summary_child["launch_count"]
    ):
        raise RetainedEvidenceError("summary child evidence record count differs")

    tracker_source = (sandbox_relative / "party_tracker.json").as_posix()
    tracker_raw = _read_bounded_capture_file(
        tracker_source, "summary child party tracker"
    )
    tracker = _decode_json(tracker_raw, "summary child party tracker")
    module_name = tracker.get("module") if isinstance(tracker, Mapping) else None
    if (
        not isinstance(module_name, str)
        or not module_name.strip()
        or _SAFE_MODULE.fullmatch(module_name) is None
    ):
        raise RetainedEvidenceError("summary child module identity differs")
    module_name = module_name.replace(" ", "_")
    if module_name in (".", ".."):
        raise RetainedEvidenceError("summary child module identity differs")

    artifacts: list[dict[str, Any]] = []
    try:
        return _retain_summary_child_artifacts(
            sandbox_relative,
            evidence_relative,
            evidence_directory_path,
            run_id=run_id,
            launches=launches,
            records=records,
            module_name=module_name,
            tracker_raw=tracker_raw,
            tracker_source=tracker_source,
            artifacts=artifacts,
        )
    except RetainedEvidenceError as exc:
        exc.retained_artifacts = list(artifacts)
        raise


def _retain_summary_child_artifacts(
    sandbox_relative: PurePosixPath,
    evidence_relative: PurePosixPath,
    evidence_directory_path: Path,
    *,
    run_id: str,
    launches: list[Any],
    records: list[dict[str, Any]],
    module_name: str,
    tracker_raw: bytes,
    tracker_source: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    writes_by_source: dict[str, dict[str, Any]] = {}
    for launch, record in zip(launches, records):
        if (
            not isinstance(launch, Mapping)
            or not isinstance(record, Mapping)
            or record.get("run_id") != run_id
            or type(record.get("pid")) is not int
            or launch.get("child_pid") != record.get("pid")
            or type(record.get("area_id")) is not str
            or _AREA_ID.fullmatch(record["area_id"]) is None
        ):
            raise RetainedEvidenceError("summary child launch/record identity differs")
        area_id = record["area_id"]
        preferred_area = (
            sandbox_relative
            / "modules"
            / module_name
            / "areas"
            / (area_id + ".json")
        ).as_posix()
        legacy_area = (
            sandbox_relative / "modules" / module_name / (area_id + ".json")
        ).as_posix()
        area_source = _first_existing_capture_file(
            preferred_area, legacy_area, "summary child area"
        )
        write_items = record.get("canonical_writes")
        if not isinstance(write_items, list) or len(write_items) != 6:
            raise RetainedEvidenceError("summary child canonical writes are incomplete")
        expected_counts = {
            "tmp/combat_capture/summary_dump.json": 1,
            "tmp/combat_capture/trimmed_summary_dump.json": 1,
            "tmp/combat_capture/dialogue_summary.json": 1,
            "tmp/combat_capture/journal.json": 1,
            area_source: 2,
        }
        observed_counts: dict[str, int] = {}
        for sequence, write in enumerate(write_items, start=1):
            if not isinstance(write, Mapping):
                raise RetainedEvidenceError("summary child canonical write is malformed")
            relative_source = write.get("path")
            if (
                not isinstance(relative_source, str)
                or not relative_source
                or PurePosixPath(relative_source).is_absolute()
                or ".." in PurePosixPath(relative_source).parts
                or "\\" in relative_source
            ):
                raise RetainedEvidenceError("summary child write source path is unsafe")
            source_path = (sandbox_relative / relative_source).as_posix()
            if source_path not in expected_counts:
                raise RetainedEvidenceError("summary child canonical write path differs")
            artifact = write.get("retained_artifact")
            _validate_write_artifact_descriptor(
                artifact,
                write=write,
                evidence_relative=evidence_relative,
                run_id=run_id,
                source_path=source_path,
                process_id=record["pid"],
                source_sha=record.get("source_sha"),
                command_sha256=record.get("command_sha256"),
                sequence=sequence,
            )
            observed_counts[source_path] = observed_counts.get(source_path, 0) + 1
            writes_by_source[source_path] = {
                "process_id": record["pid"],
                "sequence": sequence,
                "sha256": write.get("sha256"),
                "size_bytes": write.get("size_bytes"),
            }
        if observed_counts != expected_counts:
            raise RetainedEvidenceError("summary child canonical write set differs")

    script_source_path = (
        sandbox_relative / "core" / "ai" / "adv_summary.py"
    ).as_posix()
    script_source_raw = _read_bounded_capture_file(
        script_source_path, "summary child source"
    )
    script_source_destination = (
        evidence_relative
        / "retained"
        / "summary-child"
        / "source"
        / "adv_summary.py"
    ).as_posix()
    artifacts.append(
        _copy_capture_artifact(
            script_source_raw,
            source_path=script_source_path,
            destination_path=script_source_destination,
            evidence_directory=evidence_directory_path,
            run_id=run_id,
            role="script_source",
            provenance="sandbox_executed_source_before_cleanup",
        )
    )
    tracker_destination = (
        evidence_relative / "retained" / "summary-child" / "party-tracker.json"
    ).as_posix()
    artifacts.append(
        _copy_capture_artifact(
            tracker_raw,
            source_path=tracker_source,
            destination_path=tracker_destination,
            evidence_directory=evidence_directory_path,
            run_id=run_id,
            role="party_tracker",
            provenance="sandbox_state_after_child_before_cleanup",
        )
    )
    journal_source_path = (sandbox_relative / "journal.json").as_posix()
    for source_path, last_write in sorted(writes_by_source.items()):
        raw = _read_bounded_capture_file(source_path, "summary child final output")
        matches_last_write = (
            len(raw) == last_write["size_bytes"]
            and hashlib.sha256(raw).hexdigest() == last_write["sha256"]
        )
        if not matches_last_write and source_path != journal_source_path:
            # journal.json is the only canonical write the host legitimately
            # rewrites after the child exits (checkpoint/location-transition
            # journal updates); every other file here is child-exclusive.
            raise RetainedEvidenceError(
                "summary child final output differs from last write"
            )
        source_relative = PurePosixPath(source_path).relative_to(sandbox_relative)
        source_hash = hashlib.sha256(source_path.encode("ascii")).hexdigest()[:16]
        destination_path = (
            evidence_relative
            / "retained"
            / "summary-child"
            / "final"
            / (source_hash + "-" + source_relative.name)
        ).as_posix()
        provenance = (
            "canonical_json_write_final_state_before_cleanup"
            if matches_last_write
            else "host_rewrote_after_child_final_state_before_cleanup"
        )
        artifact = _copy_capture_artifact(
            raw,
            source_path=source_path,
            destination_path=destination_path,
            evidence_directory=evidence_directory_path,
            run_id=run_id,
            role="final_output",
            provenance=provenance,
        )
        artifact["last_write"] = dict(last_write)
        artifact["final_write_matches_last_write"] = matches_last_write
        artifacts.append(artifact)

    return {
        "schema_version": 1,
        "run_id": run_id,
        "capture_phase": "after_child_before_cleanup",
        "artifacts": artifacts,
    }


def _validate_write_artifact_descriptor(
    artifact: Any,
    *,
    write: Mapping[str, Any],
    evidence_relative: Path,
    run_id: str,
    source_path: str,
    process_id: int,
    source_sha: Any,
    command_sha256: Any,
    sequence: int,
) -> None:
    fields = {
        "path",
        "source_path",
        "sha256",
        "size_bytes",
        "run_id",
        "source_sha",
        "command_sha256",
        "process_id",
        "process_role",
        "write_sequence",
        "provenance",
    }
    expected_path = (
        evidence_relative / ("adv-summary-write-%d-%d.json" % (process_id, sequence))
    ).as_posix()
    if (
        not isinstance(artifact, Mapping)
        or set(artifact) != fields
        or artifact.get("path") != expected_path
        or artifact.get("source_path") != source_path
        or artifact.get("sha256") != write.get("sha256")
        or type(artifact.get("size_bytes")) is not int
        or artifact.get("size_bytes") != write.get("size_bytes")
        or artifact.get("run_id") != run_id
        or artifact.get("source_sha") != source_sha
        or artifact.get("command_sha256") != command_sha256
        or artifact.get("process_id") != process_id
        or artifact.get("process_role") != "host"
        or artifact.get("write_sequence") != sequence
        or artifact.get("provenance") != "guarded_canonical_json_writer"
    ):
        raise RetainedEvidenceError("summary child write provenance differs")
    raw = _read_bounded_capture_file(expected_path, "summary child write snapshot")
    if (
        len(raw) != write.get("size_bytes")
        or hashlib.sha256(raw).hexdigest() != write.get("sha256")
    ):
        raise RetainedEvidenceError("summary child write snapshot hash differs")


def _copy_capture_artifact(
    raw: bytes,
    *,
    source_path: str,
    destination_path: str,
    evidence_directory: Path,
    run_id: str,
    role: str,
    provenance: str,
) -> dict[str, Any]:
    relative_destination = PurePosixPath(destination_path)
    if (
        relative_destination.is_absolute()
        or ".." in relative_destination.parts
        or "\\" in destination_path
        or not relative_destination.parts
        or relative_destination.parts[0] != "tmp"
    ):
        raise RetainedEvidenceError("summary child retained artifact path is unsafe")
    evidence_relative = PurePosixPath(
        evidence_directory.relative_to(PROJECT_ROOT).as_posix()
    )
    try:
        relative_destination.relative_to(evidence_relative)
    except ValueError as exc:
        raise RetainedEvidenceError("summary child artifact escapes row evidence") from exc
    target = PROJECT_ROOT.joinpath(*relative_destination.parts)
    parent = target.parent
    relative_parent = parent.relative_to(PROJECT_ROOT)
    cursor = PROJECT_ROOT
    for part in relative_parent.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RetainedEvidenceError("summary child artifact path traverses a symlink")
        if not cursor.exists():
            try:
                cursor.mkdir(mode=0o700)
            except FileExistsError:
                pass
        if not cursor.is_dir():
            raise RetainedEvidenceError("summary child artifact parent is invalid")
    if target.exists() or target.is_symlink():
        raise RetainedEvidenceError("summary child retained artifact already exists")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        created = True
        metadata = os.fstat(descriptor)
        current_uid = os.getuid() if hasattr(os, "getuid") else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
        ):
            raise RetainedEvidenceError("summary child retained artifact is invalid")
        offset = 0
        while offset < len(raw):
            count = os.write(descriptor, raw[offset:])
            if count <= 0:
                raise RetainedEvidenceError("summary child retained artifact is incomplete")
            offset += count
        os.fsync(descriptor)
    except RetainedEvidenceError:
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    except OSError as exc:
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        raise RetainedEvidenceError("summary child retained artifact write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return {
        "role": role,
        "source_path": source_path,
        "path": destination_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "run_id": run_id,
        "provenance": provenance,
    }


def _first_existing_capture_file(
    preferred: str, legacy: str, label: str
) -> str:
    for relative_path in (preferred, legacy):
        candidate = PROJECT_ROOT.joinpath(*PurePosixPath(relative_path).parts)
        cursor = PROJECT_ROOT
        missing = False
        for part in PurePosixPath(relative_path).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RetainedEvidenceError("%s path traverses a symlink" % label)
            if not cursor.exists():
                missing = True
                break
        if not missing and candidate.is_file():
            return relative_path
    raise RetainedEvidenceError("%s file is unavailable" % label)


def _decode_json_lines(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        values = [
            _decode_json(line, label)
            for line in raw.splitlines()
            if line
        ]
    except RetainedEvidenceError:
        raise
    if len(values) != len(raw.splitlines()) or any(
        not isinstance(value, Mapping) for value in values
    ):
        raise RetainedEvidenceError("%s is malformed" % label)
    return [dict(value) for value in values]


def _read_bounded_capture_file(relative_path: str, label: str) -> bytes:
    path = _safe_project_tmp_file(relative_path)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        current_uid = os.getuid() if hasattr(os, "getuid") else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
            or metadata.st_size < 1
            or metadata.st_size > _MAX_PROFILE_ARTIFACT_BYTES
        ):
            raise RetainedEvidenceError("retained %s file is invalid" % label)
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise RetainedEvidenceError("retained %s is incomplete" % label)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    except RetainedEvidenceError:
        raise
    except OSError as exc:
        raise RetainedEvidenceError("retained %s is unavailable" % label) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _safe_project_tmp_directory(relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in relative_path
        or not relative.parts
        or relative.parts[0] != "tmp"
    ):
        raise RetainedEvidenceError("retained evidence directory is unsafe")
    root = PROJECT_ROOT.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RetainedEvidenceError("retained evidence directory traverses a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to((root / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RetainedEvidenceError("retained evidence directory is unavailable") from exc
    if not resolved.is_dir():
        raise RetainedEvidenceError("retained evidence path is not a directory")
    return resolved


class RetainedEvidenceError(ValueError):
    """Raised when retained row evidence is missing, inconsistent, or unsafe."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.retained_artifacts: list[dict[str, Any]] = []


@dataclass(frozen=True)
class RetainedValidationSnapshot:
    """Immutable Git-derived inputs captured before the row journal is bound."""

    source_sha: str
    summary_source_bytes: bytes
    git_common_directory: Path


def capture_retained_validation_snapshot(source_sha: str) -> RetainedValidationSnapshot:
    """Capture Git-backed validation inputs before row supervision hashes its journal."""
    from scripts import live_gate_preflight_profile_runner as runner
    from scripts import live_gate_preflight_safety as safety

    if safety._GUARD_EVENT_SINK is not None:
        raise RetainedEvidenceError(
            "retained validation snapshot must precede guard-event journal binding"
        )
    try:
        summary_source_bytes = runner._git_source_bytes_at_sha(
            source_sha, "core/ai/adv_summary.py"
        )
        git_common_directory = runner._git_common_directory()
    except runner.CharacterizationError as exc:
        raise RetainedEvidenceError(
            "retained validation snapshot is unavailable"
        ) from exc
    return RetainedValidationSnapshot(
        source_sha=source_sha,
        summary_source_bytes=summary_source_bytes,
        git_common_directory=git_common_directory,
    )


def _validate_retained_validation_snapshot(
    snapshot: Any, *, source_sha: str
) -> RetainedValidationSnapshot:
    if (
        not isinstance(snapshot, RetainedValidationSnapshot)
        or not isinstance(source_sha, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_sha) is None
        or snapshot.source_sha != source_sha
        or not isinstance(snapshot.summary_source_bytes, bytes)
        or not snapshot.summary_source_bytes
        or len(snapshot.summary_source_bytes) > _MAX_PROFILE_ARTIFACT_BYTES
        or not isinstance(snapshot.git_common_directory, Path)
    ):
        raise RetainedEvidenceError("retained validation snapshot identity differs")
    try:
        project_root = PROJECT_ROOT.resolve(strict=True)
        common_directory = snapshot.git_common_directory.resolve(strict=True)
        relative = common_directory.relative_to(project_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RetainedEvidenceError(
            "retained validation snapshot common directory is unsafe"
        ) from exc
    if not relative.parts or common_directory != snapshot.git_common_directory:
        raise RetainedEvidenceError(
            "retained validation snapshot common directory is unsafe"
        )
    cursor = project_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RetainedEvidenceError(
                "retained validation snapshot common directory is unsafe"
            )
    return snapshot


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
    comparison_identity: Mapping[str, Any] | None = None,
    validation_snapshot: RetainedValidationSnapshot | None = None,
) -> dict[str, Any]:
    """Validate retained sidecars and return a summary derived from disk."""
    from scripts import live_gate_preflight_profile_runner as runner
    from scripts import live_gate_preflight_profiles as profiles

    if not _valid_run_identity(row_run_id) or not _valid_run_identity(preflight_run_id):
        raise RetainedEvidenceError("row evidence run identity is invalid")
    if validation_snapshot is not None:
        validation_snapshot = _validate_retained_validation_snapshot(
            validation_snapshot, source_sha=source_sha
        )
    evidence_directory = (
        Path("tmp/router-rollout/live-gate-preflight")
        / preflight_run_id
        / "preflight"
        / "rows"
        / row_run_id
    )
    evidence_path = (evidence_directory / "profile-evidence.json").as_posix()
    digest = result.get("evidence_sha256")
    if comparison_identity is not None:
        from scripts.live_gate_preflight_comparison_identity import (
            ComparisonIdentityError,
            validate_comparison_identity,
        )

        try:
            comparison_identity = validate_comparison_identity(
                comparison_identity, expected_application_sha=source_sha
            )
        except ComparisonIdentityError as exc:
            raise RetainedEvidenceError(
                "comparison-only source identity is invalid"
            ) from exc
    expected_result_fields = {"evidence", "evidence_path", "evidence_sha256"}
    if comparison_identity is not None:
        expected_result_fields.add("comparison_identity")
    if (
        set(result) != expected_result_fields
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
    journal_descriptor = evidence.get("guard_event_journal")
    expected_journal_path = (evidence_directory / "guard-events.jsonl").as_posix()
    if (
        not isinstance(journal_descriptor, Mapping)
        or journal_descriptor.get("path") != expected_journal_path
        or not isinstance(journal_descriptor.get("sha256"), str)
        or _SHA256.fullmatch(journal_descriptor["sha256"]) is None
    ):
        raise RetainedEvidenceError("retained guard-event journal identity is invalid")
    journal_raw_before = _read_bytes(expected_journal_path, "guard-event journal")
    if hashlib.sha256(journal_raw_before).hexdigest() != journal_descriptor["sha256"]:
        raise RetainedEvidenceError("retained guard-event journal hash differs")

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
            "fixed_seed": plan.fixed_seed,
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
            trusted_summary_source=(
                (
                    validation_snapshot.source_sha,
                    validation_snapshot.summary_source_bytes,
                )
                if validation_snapshot is not None
                else None
            ),
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
        comparison_identity=comparison_identity,
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
        comparison_identity=comparison_identity,
        git_common_directory=(
            validation_snapshot.git_common_directory
            if validation_snapshot is not None
            else None
        ),
    )
    journal_raw_after = _read_bytes(expected_journal_path, "guard-event journal")
    if journal_raw_after != journal_raw_before:
        raise RetainedEvidenceError(
            "retained guard-event journal changed during reconciliation"
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
        **(
            {"comparison_identity": dict(comparison_identity)}
            if comparison_identity is not None
            else {}
        ),
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
    comparison_identity: Mapping[str, Any] | None,
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
        "adv_summary_child",
    }
    checkpoint_evidence_fields = {
        "checkpoint_travel",
        "resume_checkpoint",
        "checkpoint_attestation",
    }
    checkpoint_fields_present = checkpoint_evidence_fields.intersection(evidence)
    checkpoint_run = bool(checkpoint_fields_present)
    if checkpoint_run and checkpoint_fields_present != checkpoint_evidence_fields:
        raise RetainedEvidenceError("retained checkpoint evidence is incomplete")
    if checkpoint_run:
        worker_fields.add("checkpoint_travel")
    if comparison_identity is not None:
        worker_fields.add("comparison_identity")
    if (
        set(worker) != worker_fields
        or type(worker.get("schema_version")) is not int
        or worker.get("schema_version") != 1
        or worker.get("run_id") != run_id
        or worker.get("source_sha") != source_sha
        or (
            comparison_identity is not None
            and not _strict_json_equal(
                worker.get("comparison_identity"), dict(comparison_identity)
            )
        )
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
        or not _strict_json_equal(
            worker.get("adv_summary_child"), evidence.get("adv_summary_child")
        )
        or (
            checkpoint_run
            and not _strict_json_equal(
                worker.get("checkpoint_travel"), evidence.get("checkpoint_travel")
            )
        )
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
    comparison_identity: Mapping[str, Any] | None,
    git_common_directory: Path | None,
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
    sidecar_schema_version = sidecar.get("schema_version")
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
    if sidecar_schema_version == 2:
        expected_fields.add("teardown_wait")
    if comparison_identity is not None:
        expected_fields.add("comparison_identity")
    runner_source_sha256 = hashlib.sha256(
        (PROJECT_ROOT / "scripts" / "live_gate_preflight_profile_runner.py").read_bytes()
    ).hexdigest()
    if (
        set(sidecar) != expected_fields
        or type(sidecar.get("schema_version")) is not int
        or sidecar_schema_version not in (1, 2)
        or sidecar.get("run_id") != row_run_id
        or sidecar.get("preflight_run_id") != preflight_run_id
        or sidecar.get("source_sha") != source_sha
        or (
            comparison_identity is not None
            and not _strict_json_equal(
                sidecar.get("comparison_identity"), dict(comparison_identity)
            )
        )
        or sidecar.get("runner_source_sha256") != runner_source_sha256
        or sidecar.get("controller_pid") != controller_pid
        or not isinstance(sidecar.get("booking_id"), str)
        or runner._BOOKING_ID.fullmatch(sidecar.get("booking_id", "")) is None
    ):
        raise RetainedEvidenceError("retained teardown evidence identity differs")

    teardown_wait: Mapping[str, Any] | None = None
    if sidecar_schema_version == 2:
        teardown_wait = sidecar.get("teardown_wait")
        _validate_teardown_wait_evidence(
            teardown_wait,
            sidecar=sidecar,
            evidence=evidence,
            runner=runner,
        )

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
    if sidecar_schema_version == 2 and (
        teardown_wait is None
        or not _strict_json_equal(
            observations,
            teardown_wait["final"]["port_observations"],
        )
    ):
        raise RetainedEvidenceError(
            "retained teardown final bind observations contradict wait evidence"
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

    wait_sha256 = (
        hashlib.sha256(
            json.dumps(
                dict(teardown_wait),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        if teardown_wait is not None
        else None
    )
    final_wait_census = (
        teardown_wait.get("final_process_census")
        if isinstance(teardown_wait, Mapping)
        else None
    )

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
        or release_record.get("teardown_evidence_schema_version")
        != sidecar_schema_version
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
        or (
            sidecar_schema_version == 2
            and (
                release_record.get("teardown_wait_schema_version") != 1
                or release_record.get("teardown_wait_sha256") != wait_sha256
                or release_record.get("teardown_wait_elapsed_monotonic_ns")
                != teardown_wait.get("elapsed_monotonic_ns")
                or release_record.get("teardown_wait_completed_monotonic_ns")
                != teardown_wait.get("completed_monotonic_ns")
                or release_record.get(
                    "after_teardown_socket_sample_observed_monotonic_ns"
                )
                != final_wait_census.get("observed_monotonic_ns")
            )
        )
    ):
        raise RetainedEvidenceError("retained shared lock release record identity differs")
    actual_record, durable_digest = _read_durable_release_record(
        durable_reference,
        release_record=release_record,
        runner=runner,
        git_common_directory=git_common_directory,
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


def _validate_teardown_wait_evidence(
    value: Any,
    *,
    sidecar: Mapping[str, Any],
    evidence: Mapping[str, Any],
    runner: Any,
) -> None:
    fields = {
        "schema_version",
        "clock",
        "lock_held",
        "status",
        "failure_code",
        "timeout_ns",
        "poll_interval_ns",
        "started_monotonic_ns",
        "completed_monotonic_ns",
        "elapsed_monotonic_ns",
        "attempts",
        "initial",
        "final",
        "final_process_census",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RetainedEvidenceError("retained teardown wait evidence is malformed")
    started_ns = value.get("started_monotonic_ns")
    completed_ns = value.get("completed_monotonic_ns")
    elapsed_ns = value.get("elapsed_monotonic_ns")
    attempts = value.get("attempts")
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("clock") != "time.monotonic_ns"
        or value.get("lock_held") is not True
        or value.get("status") != "ports_free"
        or value.get("failure_code") is not None
        or type(value.get("timeout_ns")) is not int
        or value.get("timeout_ns") != 75_000_000_000
        or type(value.get("poll_interval_ns")) is not int
        or value.get("poll_interval_ns") != 1_000_000_000
        or type(started_ns) is not int
        or started_ns < 0
        or type(completed_ns) is not int
        or completed_ns < started_ns
        or type(elapsed_ns) is not int
        or elapsed_ns != completed_ns - started_ns
        or elapsed_ns > value.get("timeout_ns")
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= 75
    ):
        raise RetainedEvidenceError("retained teardown wait identity is invalid")

    attempt_fields = {
        "started_monotonic_ns",
        "completed_monotonic_ns",
        "listener_census",
        "port_observations",
    }
    previous_attempt: Mapping[str, Any] | None = None
    for attempt in attempts:
        if not isinstance(attempt, Mapping) or set(attempt) != attempt_fields:
            raise RetainedEvidenceError("retained teardown wait attempt is malformed")
        attempt_started_ns = attempt.get("started_monotonic_ns")
        attempt_completed_ns = attempt.get("completed_monotonic_ns")
        if (
            type(attempt_started_ns) is not int
            or attempt_started_ns < started_ns
            or attempt_started_ns > completed_ns
            or type(attempt_completed_ns) is not int
            or attempt_completed_ns < attempt_started_ns
            or attempt_completed_ns > completed_ns
        ):
            raise RetainedEvidenceError("retained teardown wait timing is invalid")
        if previous_attempt is not None:
            previous_started_ns = previous_attempt["started_monotonic_ns"]
            previous_completed_ns = previous_attempt["completed_monotonic_ns"]
            if (
                attempt_started_ns - previous_started_ns < 1_000_000_000
                or attempt_started_ns < previous_completed_ns
            ):
                raise RetainedEvidenceError(
                    "retained teardown wait polling exceeded its bound"
                )

        listener_census = attempt.get("listener_census")
        port_observations = attempt.get("port_observations")
        if (
            not isinstance(listener_census, Mapping)
            or set(listener_census) != {"8360", "8370"}
            or not isinstance(port_observations, Mapping)
            or set(port_observations) != {"8360", "8370"}
        ):
            raise RetainedEvidenceError(
                "retained teardown wait observations are incomplete"
            )
        for port in (8360, 8370):
            census = listener_census[str(port)]
            _validate_teardown_listener_census(census, port=port, runner=runner)
            if census.get("listener_pids") != []:
                raise RetainedEvidenceError(
                    "retained teardown wait observed a listener"
                )
            kind = runner._teardown_port_observation_kind(
                port_observations[str(port)], port
            )
            if kind not in ("free", "occupied"):
                raise RetainedEvidenceError(
                    "retained teardown wait bind observation is incomplete"
                )
        if previous_attempt is not None and not any(
            runner._teardown_port_observation_kind(
                previous_attempt["port_observations"][str(port)], port
            )
            == "occupied"
            for port in (8360, 8370)
        ):
            raise RetainedEvidenceError(
                "retained teardown wait retried without an occupied bind"
            )
        previous_attempt = attempt

    if (
        not _strict_json_equal(value.get("initial"), attempts[0])
        or not _strict_json_equal(value.get("final"), attempts[-1])
        or attempts[-1].get("completed_monotonic_ns") != completed_ns
        or any(
            runner._teardown_port_observation_kind(
                attempts[-1]["port_observations"][str(port)], port
            )
            != "free"
            for port in (8360, 8370)
        )
    ):
        raise RetainedEvidenceError(
            "retained teardown wait initial or final proof differs"
        )

    final_census = value.get("final_process_census")
    final_census_fields = {
        "phase",
        "path",
        "sha256",
        "observed",
        "listener_pids",
        "observed_monotonic_ns",
    }
    census_reference = sidecar.get("socket_census")
    process_census = evidence.get("process_census")
    samples = (
        process_census.get("socket_pid_samples")
        if isinstance(process_census, Mapping)
        else None
    )
    final_sample = (
        samples[2]
        if isinstance(samples, list)
        and len(samples) == 3
        and isinstance(samples[2], Mapping)
        else None
    )
    if (
        not isinstance(final_census, Mapping)
        or set(final_census) != final_census_fields
        or final_census.get("phase") != "after_teardown"
        or not runner._valid_evidence_path(final_census.get("path"))
        or not isinstance(final_census.get("sha256"), str)
        or _SHA256.fullmatch(final_census.get("sha256", "")) is None
        or final_census.get("observed") is not True
        or final_census.get("listener_pids") != []
        or type(final_census.get("observed_monotonic_ns")) is not int
        or final_census["observed_monotonic_ns"] <= completed_ns
        or not isinstance(census_reference, Mapping)
        or final_census.get("path") != census_reference.get("path")
        or final_census.get("sha256") != census_reference.get("sha256")
        or final_census.get("observed") is not census_reference.get("observed")
        or final_census.get("listener_pids")
        != census_reference.get("listener_pids")
        or not isinstance(final_sample, Mapping)
        or final_sample.get("phase") != "after_teardown"
        or final_sample.get("evidence_path") != final_census.get("path")
        or final_sample.get("evidence_sha256") != final_census.get("sha256")
        or final_sample.get("observed") is not True
        or final_sample.get("listener_pids") != []
    ):
        raise RetainedEvidenceError(
            "retained teardown final census is missing or predates the wait"
        )


def _validate_teardown_listener_census(
    value: Any,
    *,
    port: int,
    runner: Any,
) -> None:
    fields = {
        "schema_version",
        "method",
        "port",
        "observer",
        "census_method",
        "command",
        "returncode",
        "stdout_byte_count",
        "stdout_sha256",
        "identity_sha256",
        "observed",
        "parseable",
        "listener_pids",
        "failure_code",
    }
    command = [
        runner.LSOF_EXECUTABLE,
        "-nP",
        "-iTCP:%d" % port,
        "-sTCP:LISTEN",
    ]
    identity = {
        "observer": "lsof",
        "census_method": "tcp-listen",
        "port": port,
        "command": command,
        "returncode": value.get("returncode")
        if isinstance(value, Mapping)
        else None,
        "stdout_byte_count": value.get("stdout_byte_count")
        if isinstance(value, Mapping)
        else None,
        "stdout_sha256": value.get("stdout_sha256")
        if isinstance(value, Mapping)
        else None,
    }
    raw_identity = json.dumps(
        identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    pids = value.get("listener_pids") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value) != fields
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("method") != "lsof-tcp-listen"
        or type(value.get("port")) is not int
        or value.get("port") != port
        or value.get("observer") != "lsof"
        or value.get("census_method") != "tcp-listen"
        or value.get("command") != command
        or type(value.get("returncode")) is not int
        or value.get("returncode") not in (0, 1)
        or type(value.get("stdout_byte_count")) is not int
        or value.get("stdout_byte_count") < 0
        or not isinstance(value.get("stdout_sha256"), str)
        or _SHA256.fullmatch(value.get("stdout_sha256", "")) is None
        or value.get("identity_sha256")
        != hashlib.sha256(raw_identity).hexdigest()
        or value.get("observed") is not True
        or value.get("parseable") is not True
        or not isinstance(pids, list)
        or any(type(pid) is not int or pid <= 0 for pid in pids)
        or pids != sorted(set(pids))
        or value.get("failure_code") is not None
        or (
            value.get("returncode") == 1
            and value.get("stdout_byte_count") != 0
        )
        or (
            value.get("returncode") == 0
            and value.get("stdout_byte_count") == 0
        )
    ):
        raise RetainedEvidenceError(
            "retained teardown listener census identity is malformed"
        )


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
    git_common_directory: Path | None = None,
) -> tuple[dict[str, Any], str]:
    fields = {"path", "byte_offset", "byte_length", "line_sha256"}
    if not isinstance(reference, Mapping) or set(reference) != fields:
        raise RetainedEvidenceError("durable shared lock release reference is invalid")
    if git_common_directory is None:
        common_directory = runner._git_common_directory()
    else:
        try:
            root = PROJECT_ROOT.resolve(strict=True)
            common_directory = git_common_directory.resolve(strict=True)
            relative_common = common_directory.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RetainedEvidenceError(
                "durable shared lock release path is outside the project"
            ) from exc
        if not relative_common.parts or common_directory != git_common_directory:
            raise RetainedEvidenceError(
                "durable shared lock release path is unsafe"
            )
    expected_path = common_directory / "neq-coordination" / "bookings.log"
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
