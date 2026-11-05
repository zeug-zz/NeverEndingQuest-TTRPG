# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Create partially blinded, provider-free live transcript review packets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.mapping_pilot.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    _ARTIFACT_FILENAMES,
)
from scripts.mapping_pilot.execution import (
    DEFAULT_EXECUTION_ROOT,
    LEDGER_FILENAME,
    create_or_resume_ledger,
)
from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    verify_manifest,
)


DEFAULT_REVIEW_ROOT = Path("tmp/router-rollout/mapping-pilot/review")
DEFAULT_REVIEW_KEY_ROOT = Path("tmp/router-rollout/mapping-pilot/review-key")
RATING_LOCK_FILENAME = "rating_lock.json"
RATINGS_FILENAME = "ratings.csv"
DISCLOSURE_FILENAME = "disclosure.txt"
REVIEW_MANIFEST_FILENAME = "manifest.json"
CONDITION_KEY_FILENAME = "condition_key.json"

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESPONSE_ID = re.compile(r"^[0-9a-f]{32}$")
_ROW_ID = re.compile(r"\b(?:E|C|R)\d{2}\b")
_STEP_ID = re.compile(r"\b[A-Z]\d+-\d+\b")
_MPV2_ID = re.compile(r"\bMPV2_[A-Za-z0-9_-]+\b")
_PACKET_HASH_FIELD = re.compile(
    r"\bpacket[ _-]?(?:sha[ _-]?256|hash)\b[\"']?\s*[:=]\s*[\"']?[^\s,;}\]]+",
    re.IGNORECASE,
)
_ANSWER_KEY_FIELD = re.compile(
    r"\b(?:fixture[ _-]?)?answer[ _-]?key\b[\"']?\s*[:=]\s*[\"']?[^\s,;}\]]+",
    re.IGNORECASE,
)
_ARM_LABEL = re.compile(
    r"\b(?:arm|condition|format)(?:[_ -]?label)?[\"']?\s*(?:[:=]\s*[\"']?|[- ]+)[ABD]\b",
    re.IGNORECASE,
)
_ROUTE_FIELD = re.compile(
    r"\b(?:model|provider|transport|route|fallback)(?:[_ -]reason)?[\"']?\s*[:=]\s*[\"']?[^\s,;}\]]+",
    re.IGNORECASE,
)
_ORDER_FIELD = re.compile(
    r"\b(?:row[_ -]?order|run[_ -]?order)[\"']?\s*[:=#]?\s*[\"']?\d+\b",
    re.IGNORECASE,
)
_TIMESTAMPED_EVENT = re.compile(r"^\[[^\]]+\]\s+\[([^\]]+)\]\s+(.*)$")
_UNTIMESTAMPED_EVENT = re.compile(r"^\[([a-z_]+)\]\s+(.*)$", re.IGNORECASE)
_TURN_START = re.compile(
    r"^step=(\d+)\s+start\b.*?\blabel=(\S+).*?\binput=(.*)$"
)
_TURN_TIMEOUT = re.compile(r"\bstep=(\d+)\b.*\btimeout=yes\b", re.IGNORECASE)
_TURN_DONE = re.compile(
    r"\bstep=(\d+)\s+done\b.*\btimeout=(yes|no)\b", re.IGNORECASE
)

_RUBRIC_DIMENSIONS = (
    ("sense_of_place", 1),
    ("imaginability", 2),
    ("natural_use", 3),
    ("actionability", 4),
    ("continuity", 5),
    ("combat_clarity_and_flow", 6),
)


class ReviewPacketError(ValueError):
    """Raised when review evidence is invalid, unsafe, or cannot be blinded."""


@dataclass
class _TranscriptTurn:
    """One model-bearing turn extracted from the CaptureSession transcript."""

    driver_step: int
    step_id: str
    prompt: str
    responses: list[str] = field(default_factory=list)
    timed_out: bool = False
    completed: bool = False


def create_review_packet(
    review_run_id: str,
    evidence_bundles: Sequence[str | Path],
    *,
    sp3_run_id: str,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    output_root: str | Path = DEFAULT_REVIEW_ROOT,
    key_root: str | Path = DEFAULT_REVIEW_KEY_ROOT,
    prereg_root: str | Path | None = None,
) -> Path:
    """Build a new blinded packet set from immutable live evidence bundles.

    A response unit is one complete row transcript rather than an individual
    assistant utterance. This matches the frozen row-level continuity and combat
    flow rubric; the separately held key records the covered turn ordinals.
    """
    _validate_token(review_run_id, "review_run_id")
    _validate_token(sp3_run_id, "sp3_run_id")
    if Path.cwd().resolve() != PROJECT_ROOT:
        raise ReviewPacketError("review packets must be built from the project root")
    if not isinstance(evidence_bundles, Sequence) or isinstance(
        evidence_bundles, (str, bytes)
    ):
        raise ReviewPacketError("evidence_bundles must be a sequence of bundle paths")
    if not evidence_bundles:
        raise ReviewPacketError("at least one response unit is required")

    output_root_rel = _project_tmp_relative(output_root, "output_root")
    key_root_rel = _project_tmp_relative(key_root, "key_root")
    ledger_root_rel = _project_tmp_relative(ledger_root, "ledger_root")
    output_dir_rel = output_root_rel / review_run_id
    key_dir_rel = key_root_rel / review_run_id
    output_dir = PROJECT_ROOT / output_dir_rel
    key_dir = PROJECT_ROOT / key_dir_rel
    if (
        output_dir_rel == key_dir_rel
        or output_dir_rel in key_dir_rel.parents
        or key_dir_rel in output_dir_rel.parents
    ):
        raise ReviewPacketError("packet and condition-key directories must be separate")
    _reject_symlink_components(output_dir)
    _reject_symlink_components(key_dir)
    if output_dir.exists() or key_dir.exists():
        raise FileExistsError("review run or condition-key directory already exists")

    ledger_path = PROJECT_ROOT / ledger_root_rel / sp3_run_id / LEDGER_FILENAME
    _reject_symlink_components(ledger_path)
    if not ledger_path.is_file():
        raise ReviewPacketError("SP3 execution ledger is missing")
    try:
        ledger = create_or_resume_ledger(sp3_run_id, ledger_root=ledger_root_rel)
    except (OSError, ValueError) as exc:
        raise ReviewPacketError("SP3 execution ledger is invalid") from exc
    slots = ledger.get("slots")
    if not isinstance(slots, list):
        raise ReviewPacketError("SP3 execution ledger has no slot list")
    slots_by_id = {
        slot["row_id"]: slot
        for slot in slots
        if isinstance(slot, Mapping) and isinstance(slot.get("row_id"), str)
    }

    prereg_path = _resolve_prereg_root(prereg_root)
    prereg_hashes = verify_manifest(prereg_path)
    source_order: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    seen_run_ids: set[str] = set()
    bundle_paths: set[str] = set()
    for bundle_value in evidence_bundles:
        bundle_rel = _evidence_bundle_path(bundle_value)
        if bundle_rel.as_posix() in bundle_paths:
            raise ReviewPacketError("duplicate evidence bundle path")
        bundle_paths.add(bundle_rel.as_posix())
        source = _read_evidence_bundle(bundle_rel)
        row_id = source["row"]["row_id"]
        row_run_id = source["manifest"]["run_id"]
        if row_id in seen_rows or row_run_id in seen_run_ids:
            raise ReviewPacketError("duplicate row or row-run evidence bundle")
        seen_rows.add(row_id)
        seen_run_ids.add(row_run_id)
        slot = slots_by_id.get(row_id)
        if slot is None:
            raise ReviewPacketError("evidence row is not in the SP3 execution ledger")
        expected_script = _effective_script_path(slot)
        expected_steps, script = _load_script_steps(
            expected_script, prereg_path, prereg_hashes
        )
        _validate_row_binding(source, slot, bundle_rel, script, expected_script)
        turns = _parse_transcript(source["transcript"])
        not_rateable_reason = _not_rateable_reason(
            turns,
            expected_steps,
            source["checks"],
            source["transcript"],
        )
        response_id = secrets.token_hex(16)
        source_order.append(
            {
                "response_id": response_id,
                "row": source["row"],
                "slot": slot,
                "manifest": source["manifest"],
                "turns": turns,
                "expected_steps": expected_steps,
                "not_rateable_reason": not_rateable_reason,
                "transcript": _render_transcript(turns),
                "checks": source["checks"],
                "provenance": source["provenance"],
                "receipts": source["receipts"],
                "exact_packets": source["exact_packets"],
            }
        )

    if len({item["response_id"] for item in source_order}) != len(source_order):
        raise ReviewPacketError("opaque response ID collision")
    source_order.sort(key=lambda item: item["slot"]["run_order"])
    packet_order = list(source_order)
    random.SystemRandom().shuffle(packet_order)
    if len(packet_order) > 1 and [item["response_id"] for item in packet_order] == [
        item["response_id"] for item in source_order
    ]:
        packet_order = packet_order[1:] + packet_order[:1]

    hidden_row_ids = {
        slot.get("row_id") for slot in slots if isinstance(slot, Mapping)
    }
    packet_files: dict[str, bytes] = {}
    condition_rows: list[dict[str, Any]] = []
    rating_rows: list[dict[str, str]] = []
    for item in packet_order:
        response_id = item["response_id"]
        row = item["row"]
        slot = item["slot"]
        expected_steps = item["expected_steps"]
        scrubbed = _scrub_transcript(
            item["transcript"],
            row,
            slot,
            item["manifest"],
            item["provenance"],
            item["receipts"],
            item["checks"],
            item["exact_packets"],
            hidden_row_ids,
            expected_steps,
        )
        packet_name = response_id + ".txt"
        packet_body = (
            "Response ID: %s\n\nTranscript:\n%s\n" % (response_id, scrubbed)
        ).encode("ascii")
        if _has_blinding_leak(packet_body.decode("ascii"), item, hidden_row_ids):
            raise ReviewPacketError("transcript could not be safely blinded")
        packet_files[packet_name] = packet_body

        rating_row = {"response_id": response_id}
        for dimension, _number in _RUBRIC_DIMENSIONS:
            rating_row[dimension + "_1_5"] = ""
            rating_row[dimension + "_evidence"] = ""
        rating_row["not_rateable"] = (
            "not rateable" if item["not_rateable_reason"] else ""
        )
        rating_row["not_rateable_reason"] = item["not_rateable_reason"] or ""
        rating_rows.append(rating_row)

        expected_ordinals = list(range(1, len(expected_steps) + 1))
        ordinal_by_step = {
            step_id: ordinal for ordinal, step_id in enumerate(expected_steps, start=1)
        }
        observed_ordinals = [
            ordinal_by_step[turn.step_id]
            for turn in item["turns"]
            if turn.step_id in ordinal_by_step
        ]
        condition_rows.append(
            {
                "response_id": response_id,
                "row": row["row_id"],
                "arm": row["arm"],
                "party": row["party"],
                "seed": row["seed"],
                "row_order": slot["run_order"],
                "evidence_run_id": item["manifest"]["run_id"],
                "turn": {
                    "expected_ordinals": expected_ordinals,
                    "observed_ordinals": observed_ordinals,
                },
            }
        )

    packet_files[RATINGS_FILENAME] = _build_ratings_csv(rating_rows)
    packet_files[DISCLOSURE_FILENAME] = (
        "Blinding is partial. Visible ASCII sketches can reveal the representation "
        "format and may therefore reveal a condition. Do not claim full blinding.\n"
    ).encode("ascii")
    condition_payload = {
        "schema_version": 1,
        "review_run_id": review_run_id,
        "response_units": condition_rows,
    }
    condition_bytes = _json_bytes(condition_payload)
    condition_manifest = {
        "schema_version": 1,
        "complete": True,
        "review_run_id": review_run_id,
        "files": {
            CONDITION_KEY_FILENAME: hashlib.sha256(condition_bytes).hexdigest()
        },
    }

    _ensure_safe_directory(output_dir_rel.parent)
    _ensure_safe_directory(key_dir_rel.parent)
    _reject_symlink_components(output_dir)
    _reject_symlink_components(key_dir)
    output_dir.mkdir(exist_ok=False)
    key_dir.mkdir(exist_ok=False)
    for filename, payload in packet_files.items():
        _write_new_bytes(output_dir_rel / filename, payload)
    _write_json(key_dir_rel / CONDITION_KEY_FILENAME, condition_payload)
    _write_json(key_dir_rel / REVIEW_MANIFEST_FILENAME, condition_manifest)

    packet_manifest = {
        "schema_version": 1,
        "complete": True,
        "review_run_id": review_run_id,
        "response_count": len(packet_order),
        "packet_order": [item["response_id"] for item in packet_order],
        "files": {
            filename: hashlib.sha256(payload).hexdigest()
            for filename, payload in sorted(packet_files.items())
        },
    }
    _write_json(output_dir_rel / REVIEW_MANIFEST_FILENAME, packet_manifest)
    return output_dir_rel


def release_condition_key(
    review_run_id: str,
    *,
    output_root: str | Path = DEFAULT_REVIEW_ROOT,
    key_root: str | Path = DEFAULT_REVIEW_KEY_ROOT,
) -> dict[str, Any]:
    """Return the condition key only after a valid owner-supplied rating lock."""
    _validate_token(review_run_id, "review_run_id")
    output_root_rel = _project_tmp_relative(output_root, "output_root")
    key_root_rel = _project_tmp_relative(key_root, "key_root")
    packet_dir = PROJECT_ROOT / output_root_rel / review_run_id
    key_dir = PROJECT_ROOT / key_root_rel / review_run_id
    if (
        packet_dir == key_dir
        or packet_dir in key_dir.parents
        or key_dir in packet_dir.parents
    ):
        raise ReviewPacketError("packet and condition-key directories must be separate")
    for path in (packet_dir, key_dir):
        _reject_symlink_components(path)
        if not path.is_dir():
            raise ReviewPacketError("review packet or condition-key directory is missing")

    packet_manifest = _read_json_file(packet_dir / REVIEW_MANIFEST_FILENAME)
    if (
        packet_manifest.get("schema_version") != 1
        or packet_manifest.get("complete") is not True
        or packet_manifest.get("review_run_id") != review_run_id
    ):
        raise ReviewPacketError("review packet manifest is incomplete or mismatched")
    response_ids = _verify_review_packet_artifacts(packet_dir, packet_manifest)
    ratings_path = packet_dir / RATINGS_FILENAME
    _reject_symlink_components(ratings_path)
    if not ratings_path.is_file():
        raise ReviewPacketError("ratings sheet is missing")
    ratings_bytes = ratings_path.read_bytes()
    ratings_hash = hashlib.sha256(ratings_bytes).hexdigest()
    _verify_rating_sheet_ids(ratings_bytes, response_ids)

    lock_path = packet_dir / RATING_LOCK_FILENAME
    _reject_symlink_components(lock_path)
    if not lock_path.is_file():
        raise ReviewPacketError("owner rating-lock record is required before unblinding")
    lock = _read_json_file(lock_path)
    required_lock_fields = {
        "schema_version",
        "review_run_id",
        "reviewer_label",
        "locked_at",
        "ratings_sha256",
    }
    if set(lock) != required_lock_fields or lock.get("schema_version") != 1:
        raise ReviewPacketError("rating-lock record fields are invalid")
    if lock.get("review_run_id") != review_run_id:
        raise ReviewPacketError("rating-lock record belongs to a different review run")
    reviewer_label = lock.get("reviewer_label")
    if not isinstance(reviewer_label, str) or not reviewer_label.strip():
        raise ReviewPacketError("rating-lock record requires a reviewer label")
    _validate_timestamp(lock.get("locked_at"))
    if (
        not isinstance(lock.get("ratings_sha256"), str)
        or not _SHA256.fullmatch(lock["ratings_sha256"])
        or lock["ratings_sha256"] != ratings_hash
    ):
        raise ReviewPacketError("rating-lock ratings hash does not match the locked sheet")

    key_path = key_dir / CONDITION_KEY_FILENAME
    key_manifest_path = key_dir / REVIEW_MANIFEST_FILENAME
    _reject_symlink_components(key_path)
    if not key_path.is_file():
        raise ReviewPacketError("condition key is missing")
    _reject_symlink_components(key_manifest_path)
    if not key_manifest_path.is_file():
        raise ReviewPacketError("condition-key manifest is missing")
    key_manifest = _read_json_file(key_manifest_path)
    if (
        key_manifest.get("schema_version") != 1
        or key_manifest.get("complete") is not True
        or key_manifest.get("review_run_id") != review_run_id
        or key_manifest.get("files")
        != {
            CONDITION_KEY_FILENAME: hashlib.sha256(key_path.read_bytes()).hexdigest()
        }
    ):
        raise ReviewPacketError("condition-key manifest is invalid")
    condition_key = _read_json_file(key_path)
    if (
        condition_key.get("schema_version") != 1
        or condition_key.get("review_run_id") != review_run_id
        or not isinstance(condition_key.get("response_units"), list)
    ):
        raise ReviewPacketError("condition key has an invalid shape")
    key_units = condition_key["response_units"]
    key_response_ids = [
        unit.get("response_id") for unit in key_units if isinstance(unit, Mapping)
    ]
    if (
        len(key_response_ids) != len(key_units)
        or key_response_ids != response_ids
        or any(
            not isinstance(unit.get("turn"), Mapping)
            or "expected_ordinals" not in unit["turn"]
            or "observed_ordinals" not in unit["turn"]
            for unit in key_units
        )
    ):
        raise ReviewPacketError("condition key response and turn mappings are invalid")
    return condition_key


def _verify_review_packet_artifacts(
    packet_dir: Path, packet_manifest: Mapping[str, Any]
) -> list[str]:
    files = packet_manifest.get("files")
    packet_order = packet_manifest.get("packet_order")
    response_count = packet_manifest.get("response_count")
    if (
        not isinstance(files, Mapping)
        or not isinstance(packet_order, list)
        or not packet_order
        or not isinstance(response_count, int)
        or isinstance(response_count, bool)
        or response_count != len(packet_order)
        or any(not isinstance(value, str) or not _RESPONSE_ID.fullmatch(value) for value in packet_order)
        or len(set(packet_order)) != len(packet_order)
    ):
        raise ReviewPacketError("review packet manifest response list is invalid")
    response_ids = list(packet_order)
    expected_files = {
        *(response_id + ".txt" for response_id in response_ids),
        RATINGS_FILENAME,
        DISCLOSURE_FILENAME,
    }
    if set(files) != expected_files:
        raise ReviewPacketError("review packet manifest artifact list is invalid")

    allowed_directory_entries = expected_files | {
        REVIEW_MANIFEST_FILENAME,
        RATING_LOCK_FILENAME,
    }
    try:
        entries = list(packet_dir.iterdir())
    except OSError as exc:
        raise ReviewPacketError("review packet directory cannot be listed") from exc
    if {entry.name for entry in entries} - allowed_directory_entries:
        raise ReviewPacketError("review packet directory contains unexpected artifacts")
    for entry in entries:
        _reject_symlink_components(entry)
        if not entry.is_file():
            raise ReviewPacketError("review packet directory contains a non-file artifact")

    for filename in expected_files:
        expected_hash = files.get(filename)
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise ReviewPacketError("review packet manifest contains an invalid artifact hash")
        artifact_path = packet_dir / filename
        if not artifact_path.is_file():
            raise ReviewPacketError("review packet artifact is missing")
        # Ratings are intentionally editable; the owner lock binds their final bytes.
        if filename != RATINGS_FILENAME and hashlib.sha256(
            artifact_path.read_bytes()
        ).hexdigest() != expected_hash:
            raise ReviewPacketError("review packet artifact hash does not match")
    return response_ids


def _verify_rating_sheet_ids(ratings_bytes: bytes, response_ids: Sequence[str]) -> None:
    expected_fields = ["response_id"]
    for dimension, _number in _RUBRIC_DIMENSIONS:
        expected_fields.extend((dimension + "_1_5", dimension + "_evidence"))
    expected_fields.extend(("not_rateable", "not_rateable_reason"))
    try:
        reader = csv.DictReader(io.StringIO(ratings_bytes.decode("ascii"), newline=""))
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ReviewPacketError("ratings sheet is invalid") from exc
    actual_ids = [row.get("response_id") for row in rows]
    if reader.fieldnames != expected_fields or actual_ids != list(response_ids):
        raise ReviewPacketError("ratings sheet does not match the locked response packets")


def _read_evidence_bundle(bundle_rel: Path) -> dict[str, Any]:
    bundle_path = PROJECT_ROOT / bundle_rel
    _reject_symlink_components(bundle_path)
    if not bundle_path.is_dir():
        raise ReviewPacketError("evidence bundle directory is missing")
    manifest = _read_json_file(bundle_path / "manifest.json")
    if (
        manifest.get("complete") is not True
        or not isinstance(manifest.get("run_id"), str)
        or manifest.get("run_id") != bundle_rel.name
        or not isinstance(manifest.get("row_id"), str)
        or str(manifest.get("gate", "")).lower() != "sp3"
    ):
        raise ReviewPacketError("evidence bundle manifest is incomplete or not SP3")
    _validate_token(manifest["run_id"], "evidence run_id")
    file_hashes = manifest.get("files")
    expected_files = set(_ARTIFACT_FILENAMES.values())
    if not isinstance(file_hashes, Mapping) or set(file_hashes) != expected_files:
        raise ReviewPacketError("evidence bundle manifest file list is incomplete")
    for filename, expected_hash in file_hashes.items():
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise ReviewPacketError("evidence bundle contains an invalid file hash")
        artifact_path = bundle_path / filename
        _reject_symlink_components(artifact_path)
        if not artifact_path.is_file():
            raise ReviewPacketError("evidence bundle artifact is missing")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != expected_hash:
            raise ReviewPacketError("evidence bundle artifact hash does not match")

    row = _read_json_file(bundle_path / _ARTIFACT_FILENAMES["row"])
    provenance = _read_json_file(bundle_path / _ARTIFACT_FILENAMES["provenance"])
    checks = _read_json_value(
        bundle_path / _ARTIFACT_FILENAMES["expected_observed_checks"]
    )
    receipts = _read_json_file(bundle_path / _ARTIFACT_FILENAMES["router_receipts"])
    exact_packets = _read_json_file(bundle_path / _ARTIFACT_FILENAMES["exact_packets"])
    verdict = _read_json_file(bundle_path / _ARTIFACT_FILENAMES["verdict"])
    if (
        row.get("row_id") != manifest["row_id"]
        or provenance.get("evidence_kind") != "live"
        or not isinstance(checks, list)
        or not isinstance(receipts, Mapping)
        or not isinstance(exact_packets, Mapping)
        or not isinstance(verdict, Mapping)
    ):
        raise ReviewPacketError("evidence bundle identities or artifact shapes are invalid")
    transcript_path = bundle_path / _ARTIFACT_FILENAMES["transcript"]
    try:
        transcript = transcript_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ReviewPacketError("evidence transcript is missing or not ASCII") from exc
    return {
        "manifest": dict(manifest),
        "row": dict(row),
        "provenance": dict(provenance),
        "checks": checks,
        "receipts": dict(receipts),
        "exact_packets": dict(exact_packets),
        "verdict": dict(verdict),
        "transcript": transcript,
    }


def _validate_row_binding(
    source: Mapping[str, Any],
    slot: Mapping[str, Any],
    bundle_rel: Path,
    script: Mapping[str, Any],
    expected_script: str,
) -> None:
    row = source["row"]
    row_id = row.get("row_id")
    run_id = source["manifest"].get("run_id")
    execution = slot.get("execution")
    if (
        slot.get("status") == "missing"
        or not isinstance(execution, Mapping)
        or execution.get("row_run_id") != run_id
        or slot.get("evidence_path") != bundle_rel.as_posix()
    ):
        raise ReviewPacketError("evidence bundle is not bound to its finalized SP3 ledger row")
    if row_id != slot.get("row_id") or row.get("seed") != slot.get("fixed_seed"):
        raise ReviewPacketError("evidence row identity does not match the SP3 ledger")
    classification = slot.get("pre_content_classification")
    review_sequence = slot.get("content_review_event_sequence")
    if (
        not isinstance(classification, Mapping)
        or classification.get("row_run_id") != run_id
        or not isinstance(classification.get("event_sequence"), int)
        or isinstance(classification.get("event_sequence"), bool)
        or not isinstance(review_sequence, int)
        or isinstance(review_sequence, bool)
        or classification["event_sequence"] >= review_sequence
        or not isinstance(slot.get("content_review_started_at"), str)
    ):
        raise ReviewPacketError(
            "SP3 pre-content classification and review ordering are required"
        )

    expected_arm, expected_party, slot_script = _effective_slot_cell(slot)
    input_paths = source["provenance"].get("input_paths")
    if (
        row.get("arm") != expected_arm
        or row.get("party") != "P%d" % expected_party
        or expected_script != slot_script
        or not isinstance(input_paths, Mapping)
        or input_paths.get("script") != expected_script
        or script.get("script_id") != row.get("script_id")
        or row.get("fixture_id") not in script.get("fixture_ids", [])
    ):
        raise ReviewPacketError("evidence condition does not match the frozen row")
    if "run_order" in row and row["run_order"] != slot.get("run_order"):
        raise ReviewPacketError("evidence row order does not match the SP3 ledger")


def _effective_slot_cell(slot: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    if slot.get("row_type") != "replacement_only":
        return slot.get("arm"), slot.get("party"), slot.get("script")
    replacement = slot.get("replacement")
    inherited = replacement.get("inherited_cell") if isinstance(replacement, Mapping) else None
    if not isinstance(inherited, Mapping):
        raise ReviewPacketError("reserve evidence has no activated inherited cell")
    return inherited.get("arm"), inherited.get("party"), inherited.get("script")


def _effective_script_path(slot: Mapping[str, Any]) -> str:
    _arm, _party, script = _effective_slot_cell(slot)
    if not isinstance(script, str):
        raise ReviewPacketError("SP3 ledger row has no effective frozen script path")
    return script


def _load_script_steps(
    script_path: Any,
    prereg_root: Path,
    prereg_hashes: Mapping[str, str],
) -> tuple[list[str], dict[str, Any]]:
    if not isinstance(script_path, str):
        raise ReviewPacketError("SP3 ledger row has no frozen script path")
    parsed = PurePosixPath(script_path)
    if (
        parsed.is_absolute()
        or not script_path.startswith("scripts/")
        or ".." in parsed.parts
        or "." in parsed.parts
        or "\\" in script_path
        or script_path not in prereg_hashes
    ):
        raise ReviewPacketError("SP3 ledger script path is not in the frozen manifest")
    path = prereg_root.joinpath(*parsed.parts)
    _reject_symlink_components(path)
    try:
        script = _read_json_file(path)
    except ReviewPacketError as exc:
        raise ReviewPacketError("frozen row script is invalid") from exc
    turns = script.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ReviewPacketError("frozen row script has no model-bearing turns")
    step_ids = [
        turn.get("id") for turn in turns if isinstance(turn, Mapping)
    ]
    if (
        len(step_ids) != len(turns)
        or any(not isinstance(step_id, str) or not step_id for step_id in step_ids)
        or len(set(step_ids)) != len(step_ids)
    ):
        raise ReviewPacketError("frozen row script turn identities are invalid")
    return step_ids, dict(script)


def _parse_transcript(transcript: str) -> list[_TranscriptTurn]:
    turns: list[_TranscriptTurn] = []
    turn_by_driver_step: dict[int, _TranscriptTurn] = {}
    continuation: tuple[str, int, int | None] | None = None
    current: _TranscriptTurn | None = None
    for line in transcript.splitlines():
        if line.startswith("[segment "):
            continuation = None
            continue
        event = _TIMESTAMPED_EVENT.match(line)
        if event is None:
            event = _UNTIMESTAMPED_EVENT.match(line)
        if event is None:
            if continuation is not None:
                _append_continuation(turns, continuation, line)
            continue
        kind = event.group(1).strip().lower()
        message = event.group(2)
        continuation = None
        if kind == "driver":
            start = _TURN_START.match(message)
            if start is not None:
                driver_step = int(start.group(1))
                turn = _TranscriptTurn(
                    driver_step=driver_step,
                    step_id=start.group(2),
                    prompt=start.group(3).strip(),
                )
                turns.append(turn)
                turn_by_driver_step[driver_step] = turn
                current = turn
                continuation = ("prompt", len(turns) - 1, None)
                continue
            done = _TURN_DONE.search(message)
            if done is not None:
                done_turn = turn_by_driver_step.get(int(done.group(1)))
                if done_turn is not None:
                    done_turn.completed = done.group(2).casefold() == "no"
                    done_turn.timed_out = done.group(2).casefold() == "yes"
                continue
            timeout = _TURN_TIMEOUT.search(message)
            if timeout is not None:
                timed_out_turn = turn_by_driver_step.get(int(timeout.group(1)))
                if timed_out_turn is not None:
                    timed_out_turn.timed_out = True
            continue
        if kind != "game_output" or current is None:
            continue
        output_type = re.search(r"(?:^|\s)type=([^\s]+)", message)
        if output_type is not None and output_type.group(1).casefold() in (
            "user-input",
            "user_input",
        ):
            continue
        content_at = message.find("content=")
        content = message[content_at + len("content=") :] if content_at >= 0 else message
        content = content.strip()
        if content:
            current.responses.append(content)
            continuation = ("response", len(turns) - 1, len(current.responses) - 1)
    return turns


def _append_continuation(
    turns: list[_TranscriptTurn],
    target: tuple[str, int, int | None],
    text: str,
) -> None:
    kind, turn_index, response_index = target
    if turn_index >= len(turns):
        return
    if kind == "prompt":
        turns[turn_index].prompt += "\n" + text
    elif response_index is not None and response_index < len(turns[turn_index].responses):
        turns[turn_index].responses[response_index] += "\n" + text


def _not_rateable_reason(
    turns: Sequence[_TranscriptTurn],
    expected_steps: Sequence[str],
    checks: Sequence[Any],
    transcript: str,
) -> str:
    reasons: list[str] = []
    if not transcript.strip() or "[missing]" in transcript.casefold():
        reasons.append("transcript missing")
    if len(turns) != len(expected_steps):
        reasons.append("one or more expected response turns are missing")
    if not turns:
        reasons.append("no response turns could be extracted")
    if any(turn.timed_out for turn in turns):
        reasons.append("one or more turns timed out")
    if any(not turn.completed for turn in turns):
        reasons.append("one or more turns are incomplete or truncated")
    if any(not any(response.strip() for response in turn.responses) for turn in turns):
        reasons.append("one or more turns have no backend output")

    turns_by_id = {turn.step_id: turn for turn in turns}
    for step_id in expected_steps:
        turn = turns_by_id.get(step_id)
        if turn is None:
            reasons.append("expected turn evidence is incomplete")
            break
    delivery_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for check in checks:
        if not isinstance(check, Mapping) or check.get("check_kind") != "delivery":
            continue
        check_id = check.get("check_id")
        if isinstance(check_id, str):
            for step_id in expected_steps:
                if check_id.startswith(step_id + "-"):
                    delivery_by_id.setdefault(step_id, []).append(check)
                    break
    for step_id in expected_steps:
        matching = delivery_by_id.get(step_id, [])
        if not matching:
            reasons.append("delivery evidence is missing for one or more turns")
            break
        for check in matching:
            observed = check.get("observed")
            if check.get("passed") is not True or not isinstance(observed, Mapping):
                reasons.append("delivery evidence marks a response incomplete or degraded")
                break
            output_count = observed.get("backend_output_count")
            if (
                observed.get("completed") is not True
                or observed.get("timed_out") is True
                or not isinstance(output_count, int)
                or isinstance(output_count, bool)
                or output_count <= 0
            ):
                reasons.append("delivery evidence marks a response missing or truncated")
                break
        if reasons and reasons[-1].startswith("delivery evidence"):
            break
    return "; ".join(dict.fromkeys(reasons))


def _render_transcript(turns: Sequence[_TranscriptTurn]) -> str:
    if not turns:
        return "Transcript unavailable."
    sections: list[str] = []
    for turn in turns:
        parts: list[str] = []
        if turn.prompt.strip():
            parts.append("Player: " + turn.prompt.strip())
        response = "\n".join(value.strip() for value in turn.responses if value.strip())
        if response:
            parts.append("Narrator: " + response)
        elif not parts:
            parts.append("Response unavailable.")
        sections.append("\n".join(parts))
    return "\n\n".join(sections)


def _scrub_transcript(
    transcript: str,
    row: Mapping[str, Any],
    slot: Mapping[str, Any],
    bundle_manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
    receipts: Mapping[str, Any],
    checks: Sequence[Any],
    exact_packets: Mapping[str, Any],
    hidden_row_ids: set[Any],
    expected_steps: Sequence[str],
) -> str:
    output = transcript
    sensitive: set[str] = set()
    for value in (
        row.get("row_id"),
        row.get("fixture_id"),
        row.get("script_id"),
        row.get("scenario_id"),
        bundle_manifest.get("run_id"),
        str(row.get("seed")) if row.get("seed") is not None else None,
        str(slot.get("run_order")) if slot.get("run_order") is not None else None,
    ):
        if isinstance(value, str) and value:
            sensitive.add(value)
    sensitive.update(value for value in hidden_row_ids if isinstance(value, str))
    sensitive.update(step_id for step_id in expected_steps if isinstance(step_id, str))

    for value in _nested_strings(checks):
        if len(value) >= 16:
            sensitive.add(value)
    for value in _route_metadata_strings(provenance.get("route_identity")):
        sensitive.add(value)
    sensitive.update(_route_metadata_strings(receipts))
    for value in _nested_strings(exact_packets):
        if _SHA256.fullmatch(value):
            sensitive.add(value)
        elif value.startswith("MPV2_") or _STEP_ID.fullmatch(value):
            sensitive.add(value)
    file_hashes = bundle_manifest.get("files")
    if isinstance(file_hashes, Mapping):
        sensitive.update(
            value for value in file_hashes.values() if isinstance(value, str)
        )

    for value in sorted(sensitive, key=len, reverse=True):
        if len(value) < 3:
            continue
        if re.fullmatch(r"[A-Za-z0-9._/-]+", value):
            pattern = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value)
            output = re.sub(pattern, "[withheld]", output, flags=re.IGNORECASE)
        else:
            output = output.replace(value, "[withheld]")
    output = _ROW_ID.sub("[withheld]", output)
    output = _STEP_ID.sub("[withheld]", output)
    output = _MPV2_ID.sub("[location withheld]", output)
    output = _PACKET_HASH_FIELD.sub("packet hash withheld", output)
    output = _ANSWER_KEY_FIELD.sub("fixture answer key withheld", output)
    output = _ARM_LABEL.sub("condition label withheld", output)
    output = _ROUTE_FIELD.sub("routing detail withheld", output)
    output = _ORDER_FIELD.sub("row order withheld", output)
    output = re.sub(
        r"(?i)\b(?:seed|random[ _-]?seed)[\"']?\s*[:=]\s*[\"']?\d+\b",
        "seed withheld",
        output,
    )
    output = re.sub(r"(?i)\b[0-9a-f]{64}\b", "[hash withheld]", output)
    return output.strip()


def _has_blinding_leak(
    transcript: str,
    item: Mapping[str, Any],
    hidden_row_ids: set[Any],
) -> bool:
    text = transcript.casefold()
    row = item["row"]
    manifest = item["manifest"]
    for value in (
        row.get("row_id"),
        row.get("fixture_id"),
        row.get("script_id"),
        row.get("scenario_id"),
        manifest.get("run_id"),
        str(row.get("seed")) if row.get("seed") is not None else None,
    ):
        if isinstance(value, str) and value and value.casefold() in text:
            return True
    if (
        _ROW_ID.search(transcript)
        or _STEP_ID.search(transcript)
        or _MPV2_ID.search(transcript)
        or _PACKET_HASH_FIELD.search(transcript)
        or _ANSWER_KEY_FIELD.search(transcript)
    ):
        return True
    if re.search(r"(?i)\b[0-9a-f]{64}\b", transcript):
        return True
    if _ARM_LABEL.search(transcript) or _ROUTE_FIELD.search(transcript) or _ORDER_FIELD.search(transcript):
        return True
    for value in hidden_row_ids:
        if isinstance(value, str) and re.search(
            r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value),
            transcript,
            re.IGNORECASE,
        ):
            return True
    for value in _route_metadata_strings(item["provenance"].get("route_identity")):
        if len(value) >= 4 and re.search(
            r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value),
            transcript,
            re.IGNORECASE,
        ):
            return True
    for value in _route_metadata_strings(item["receipts"]):
        if len(value) >= 4 and re.search(
            r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value),
            transcript,
            re.IGNORECASE,
        ):
            return True
    for value in _nested_strings(item["exact_packets"]):
        if _SHA256.fullmatch(value) and value.casefold() in text:
            return True
        if value.startswith("MPV2_") and value.casefold() in text:
            return True
    bundle_hashes = manifest.get("files")
    if isinstance(bundle_hashes, Mapping) and any(
        isinstance(value, str) and value.casefold() in text
        for value in bundle_hashes.values()
    ):
        return True
    if any(
        len(value) >= 16 and value.casefold() in text
        for value in _nested_strings(item["checks"])
    ):
        return True
    return False


def _build_ratings_csv(rows: Sequence[Mapping[str, str]]) -> bytes:
    fieldnames = ["response_id"]
    for dimension, _number in _RUBRIC_DIMENSIONS:
        fieldnames.extend((dimension + "_1_5", dimension + "_evidence"))
    fieldnames.extend(("not_rateable", "not_rateable_reason"))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("ascii")


def _evidence_bundle_path(path: str | Path) -> Path:
    relative = _project_tmp_relative(path, "evidence bundle")
    root_parts = DEFAULT_EVIDENCE_ROOT.parts
    if (
        relative.parts[: len(root_parts)] != root_parts
        or len(relative.parts) < len(root_parts) + 2
    ):
        raise ReviewPacketError("evidence bundle must be beneath the mapping-pilot evidence root")
    _reject_symlink_components(PROJECT_ROOT / relative)
    return relative


def _project_tmp_relative(path: str | Path, label: str) -> Path:
    raw = Path(path)
    if (
        raw.is_absolute()
        or not raw.parts
        or raw.parts[0] != "tmp"
        or ".." in raw.parts
        or "." in raw.parts
        or "\\" in str(path)
    ):
        raise ReviewPacketError("%s must be a project-relative path beneath tmp/" % label)
    tmp_root = PROJECT_ROOT / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise ReviewPacketError("project tmp/ is missing or unsafe")
    candidate = PROJECT_ROOT / raw
    _reject_symlink_components(candidate)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReviewPacketError("%s escaped project tmp/" % label) from exc
    return raw


def _resolve_prereg_root(prereg_root: str | Path | None) -> Path:
    root = DEFAULT_PREREG_ROOT if prereg_root is None else Path(prereg_root)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReviewPacketError("frozen preregistration directory is unavailable") from exc
    if not resolved.is_dir():
        raise ReviewPacketError("frozen preregistration path is not a directory")
    return resolved


def _ensure_safe_directory(relative_path: Path) -> None:
    absolute = PROJECT_ROOT / relative_path
    _reject_symlink_components(absolute)
    absolute.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(absolute)
    if not absolute.is_dir():
        raise ReviewPacketError("review output parent is not a directory")


def _reject_symlink_components(path: Path) -> None:
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ReviewPacketError("mapping-pilot review paths must remain in the project") from exc
    current = PROJECT_ROOT
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ReviewPacketError("mapping-pilot review paths must not traverse symlinks")


def _read_json_file(path: Path) -> dict[str, Any]:
    value = _read_json_value(path)
    if not isinstance(value, dict):
        raise ReviewPacketError("review JSON input must be an object")
    return value


def _read_json_value(path: Path) -> Any:
    _reject_symlink_components(path)
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewPacketError("review JSON input is missing or invalid") from exc


def _write_json(relative_path: Path, value: Mapping[str, Any]) -> None:
    from utils.file_operations import safe_write_json

    if not safe_write_json(
        str(relative_path),
        dict(value),
        create_backup=False,
        acquire_lock=False,
        json_kwargs={"ensure_ascii": True, "indent": 2, "sort_keys": True, "allow_nan": False},
    ):
        raise OSError("atomic mapping-pilot review JSON write failed")


def _write_new_bytes(relative_path: Path, payload: bytes) -> None:
    absolute = PROJECT_ROOT / relative_path
    _reject_symlink_components(absolute)
    try:
        with absolute.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise ReviewPacketError("review packet artifact write failed") from exc


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False
    ).encode("ascii") + b"\n"


def _nested_strings(value: Any) -> set[str]:
    output: set[str] = set()
    if isinstance(value, Mapping):
        for child in value.values():
            output.update(_nested_strings(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            output.update(_nested_strings(child))
    elif isinstance(value, str) and value:
        output.add(value)
    return output


def _route_metadata_strings(value: Any) -> set[str]:
    route_fields = {
        "model",
        "model_id",
        "requested_model",
        "resolved_model",
        "provider",
        "transport",
        "route",
        "fallback",
        "fallback_reason",
    }
    output: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in route_fields and isinstance(child, str) and child:
                output.add(child)
            else:
                output.update(_route_metadata_strings(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            output.update(_route_metadata_strings(child))
    return output


def _validate_token(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or value in (".", "..")
        or not _SAFE_TOKEN.fullmatch(value)
    ):
        raise ReviewPacketError("%s must be a safe path token" % label)


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ReviewPacketError("rating-lock timestamp must be ISO-8601 text")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewPacketError("rating-lock timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReviewPacketError("rating-lock timestamp must include a timezone")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value: %s" % value)
