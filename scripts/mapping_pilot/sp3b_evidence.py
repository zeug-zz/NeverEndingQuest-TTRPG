# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fail-closed H2 evidence correlation and chronological zone-event storage.

This module is deliberately independent of the SP3b launcher/runtime seams.
It neither invokes nor fabricates provider, server, seeder, or socket activity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# This is the existing SP3b per-row provider-attempt ceiling, not a new budget.
MAX_ROUTER_RECEIPTS = 35
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ROW_ID = re.compile(r"^SP3B-(0(?:1[2-9]))$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_ZONE_EVENT_KINDS = frozenset(("movement_hint", "enemy_phase", "unknown"))
_MOVEMENT_HINT_STATUSES = frozenset(("valid", "missing", "invalid"))
_ENEMY_PHASE_STATUSES = frozenset(
    ("held", "joined", "moved", "moved_and_joined")
)
class SP3BEvidenceError(ValueError):
    """Raised when evidence is missing, inconsistent, unsafe, or unordered."""


def correlate_k2_02(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Validate complete deterministic K2-02 correlation and return a summary.

    A zero-length receipt list is accepted only when the bounded observer's
    complete lifecycle and K2-02 step windows are independently present and
    internally consistent. No receipt, response, hint, or latency is created.
    """
    _require_mapping(evidence, "K2-02 evidence")
    _require_keys(
        evidence,
        {
            "identity",
            "consumed_input",
            "actor",
            "actual_action",
            "canonical_state",
            "request_observer",
            "receipts",
        },
        "K2-02 evidence",
    )

    identity = _validate_k2_identity(evidence["identity"])
    expected_actor, expected_utterance, script_step_ids = _frozen_k2_02_contract(
        identity["party_size"]
    )
    consumed = _validate_consumed_input(
        evidence["consumed_input"], expected_utterance
    )
    actor = _validate_actor(evidence["actor"], expected_actor)
    action = _validate_actual_action(
        evidence["actual_action"], expected_actor, expected_utterance
    )
    observer, receipts, step_window = _validate_request_observer(
        evidence["request_observer"],
        evidence["receipts"],
        identity,
        script_step_ids,
    )
    before, after = _validate_canonical_state(
        evidence["canonical_state"], step_window
    )

    return {
        "evidence_status": "recorded",
        "identity": copy.deepcopy(identity),
        "consumed_input": {
            **copy.deepcopy(consumed),
            "actor_id": actor["actor_id"],
            "actor_name": actor["name"],
        },
        "resolved_actor": copy.deepcopy(actor),
        "actual_action": {
            "status": action["status"],
            "input_text": action["input_text"],
            "actor_name": action["actor_name"],
            "source": action["source"],
            "parser_source": action["parser_source"],
            "apply_source": action["apply_source"],
            "parse_result": copy.deepcopy(action["parse_result"]),
            "applied_event": copy.deepcopy(action["applied_event"]),
        },
        "canonical_state": {
            "before": copy.deepcopy(before),
            "after": copy.deepcopy(after),
            "canonical_files_unchanged": True,
        },
        "request_coverage": {
            "status": "complete",
            "observer_source": observer["source"],
            "observer_window": {
                "started_at_utc": observer["started_at_utc"],
                "finished_at_utc": observer["finished_at_utc"],
                "observer_errors": observer["observer_errors"],
            },
            "step_window": copy.deepcopy(step_window),
            "receipt_count": len(receipts),
            "receipt_sequences": [record["sequence"] for record in receipts],
            "receipts": copy.deepcopy(receipts),
            "k2_02_request_count": 0,
            "max_receipts": observer["max_receipts"],
        },
        "model_call_status": "N/A (deterministic, no model call)",
    }


def append_zone_event(
    evidence_root: str | Path,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically append one linked zone event without replacing prior records.

    ``evidence_root`` must already exist below the project-local ``tmp/``.
    Event time is supplied by the source observer; it is never synthesized.
    """
    normalized = _validate_zone_event(event, sequence=None)
    root = _resolve_evidence_root(evidence_root)
    event_directory = _zone_event_directory(root, normalized, create=True)

    from utils.file_operations import atomic_writer, safe_write_json

    lock_key = str(event_directory / ".sequence")
    _reject_path_symlinks(root, event_directory / ".sequence.lock")
    acquired = False
    try:
        if atomic_writer.acquire_lock(lock_key) is None:
            raise SP3BEvidenceError("zone evidence sequence lock is unavailable")
        acquired = True
        previous = _read_zone_records(event_directory, normalized, allow_empty=True)
        if previous:
            previous_time = _parse_timestamp(
                previous[-1]["observed_at_utc"], "prior zone event time"
            )
            event_time = _parse_timestamp(
                normalized["observed_at_utc"], "zone event time"
            )
            if event_time <= previous_time:
                raise SP3BEvidenceError(
                    "zone event time must be strictly later than the prior event"
                )
        sequence = len(previous) + 1
        record = _validate_zone_event(
            {**normalized, "sequence": sequence}, sequence=sequence
        )
        target = event_directory / ("record-%08d.json" % sequence)
        _reject_path_symlinks(root, target)
        if target.exists() or target.is_symlink():
            raise SP3BEvidenceError("zone event record already exists; overwrite refused")
        if not safe_write_json(
            str(target),
            record,
            create_backup=False,
            acquire_lock=True,
            json_kwargs={
                "ensure_ascii": True,
                "sort_keys": True,
                "allow_nan": False,
                "separators": (",", ":"),
            },
        ):
            raise SP3BEvidenceError("atomic zone event write failed")
        return copy.deepcopy(record)
    finally:
        if acquired:
            atomic_writer.release_lock(lock_key)


def read_zone_events(
    evidence_root: str | Path,
    *,
    run_id: str,
    row_id: str,
    row_run_id: str,
    lifecycle_id: str,
) -> list[dict[str, Any]]:
    """Read a non-empty, contiguous, identity-bound chronological event trace.

    Empty traces raise rather than becoming a zero-contradiction or success
    result. Callers must record explicit unknown events when a source is absent.
    """
    identity = _validate_event_identity(
        {
            "run_id": run_id,
            "row_id": row_id,
            "row_run_id": row_run_id,
            "lifecycle_id": lifecycle_id,
            "step_id": "reader",
            "actor_id": "reader",
        }
    )
    root = _resolve_evidence_root(evidence_root)
    event_directory = _zone_event_directory(root, identity, create=False)
    from utils.file_operations import atomic_writer

    lock_key = str(event_directory / ".sequence")
    _reject_path_symlinks(root, event_directory / ".sequence.lock")
    acquired = False
    try:
        if atomic_writer.acquire_lock(lock_key) is None:
            raise SP3BEvidenceError("zone evidence read lock is unavailable")
        acquired = True
        records = _read_zone_records(event_directory, identity, allow_empty=False)
    finally:
        if acquired:
            atomic_writer.release_lock(lock_key)
    return copy.deepcopy(records)


def _validate_k2_identity(value: Any) -> dict[str, Any]:
    _require_mapping(value, "K2-02 identity")
    _require_keys(
        value,
        {
            "run_id",
            "row_id",
            "source_cell",
            "row_run_id",
            "lifecycle_id",
            "step_id",
            "party_size",
        },
        "K2-02 identity",
    )
    run_id = _require_token(value.get("run_id"), "run_id")
    if not run_id.startswith("sp3b-"):
        raise SP3BEvidenceError("K2-02 run_id must be a new SP3b run identity")
    row_id = value.get("row_id")
    match = _ROW_ID.fullmatch(row_id) if isinstance(row_id, str) else None
    if match is None:
        raise SP3BEvidenceError("K2-02 row_id must identify SP3B-012 through SP3B-019")
    row_number = int(match.group(1))
    expected_cell = "C%02d" % (row_number - 11)
    source_cell = value.get("source_cell")
    if source_cell != expected_cell:
        raise SP3BEvidenceError("K2-02 row/source-cell linkage is invalid")
    row_run_id = _require_token(value.get("row_run_id"), "row_run_id")
    lifecycle_id = _require_token(value.get("lifecycle_id"), "lifecycle_id")
    if value.get("step_id") != "K2-02":
        raise SP3BEvidenceError("K2-02 step identity is invalid")
    party_size = value.get("party_size")
    if type(party_size) is not int or party_size not in (1, 4):
        raise SP3BEvidenceError("K2-02 party_size must be exactly 1 or 4")
    expected_party_size = 1 if row_number <= 15 else 4
    if party_size != expected_party_size:
        raise SP3BEvidenceError("K2-02 party size does not match the frozen row binding")
    return {
        "run_id": run_id,
        "row_id": row_id,
        "source_cell": expected_cell,
        "row_run_id": row_run_id,
        "lifecycle_id": lifecycle_id,
        "step_id": "K2-02",
        "party_size": party_size,
    }


def _frozen_k2_02_contract(
    party_size: int,
) -> tuple[str, str, frozenset[str]]:
    from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT, verify_manifest

    hashes = verify_manifest(DEFAULT_PREREG_ROOT)
    relative = "scripts/combat.json"
    if relative not in hashes:
        raise SP3BEvidenceError("frozen combat script is not manifest-bound")
    path = DEFAULT_PREREG_ROOT / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SP3BEvidenceError("frozen combat script cannot be read") from exc
    turns = payload.get("turns") if isinstance(payload, Mapping) else None
    if not isinstance(turns, list):
        raise SP3BEvidenceError("frozen combat script is malformed")
    step_ids: set[str] = {"startup"}
    for turn in turns:
        if not isinstance(turn, Mapping):
            raise SP3BEvidenceError("frozen combat script contains a malformed step")
        step_id = turn.get("id")
        if not isinstance(step_id, str) or not _TOKEN.fullmatch(step_id) or step_id in step_ids:
            raise SP3BEvidenceError("frozen combat script step IDs are invalid or duplicated")
        step_ids.add(step_id)
    matches = [
        row
        for row in turns
        if isinstance(row, Mapping) and row.get("id") == "K2-02"
    ]
    if len(matches) != 1:
        raise SP3BEvidenceError("frozen combat script must contain one K2-02 step")
    row = matches[0]
    actor_payload = row.get("actor")
    actor_name = (
        actor_payload.get("party_%d" % party_size)
        if isinstance(actor_payload, Mapping)
        else None
    )
    utterance = row.get("utterance")
    if (
        not isinstance(actor_name, str)
        or not actor_name.strip()
        or actor_name != actor_name.strip()
        or not isinstance(utterance, str)
        or not utterance.strip()
        or utterance != utterance.strip()
    ):
        raise SP3BEvidenceError("frozen K2-02 actor or utterance is malformed")
    return actor_name, utterance, frozenset(step_ids)


def _validate_consumed_input(value: Any, utterance: str) -> dict[str, Any]:
    _require_mapping(value, "consumed input")
    _require_keys(
        value,
        {"status", "step_id", "text", "source"},
        "consumed input",
    )
    if (
        value.get("status") != "consumed"
        or value.get("step_id") != "K2-02"
        or value.get("text") != utterance
        or value.get("source") != "core.combat.turn.prepare_combat_normal_turn"
    ):
        raise SP3BEvidenceError("K2-02 consumed input is missing or unlinked")
    return dict(value)


def _validate_actor(value: Any, expected_name: str) -> dict[str, Any]:
    _require_mapping(value, "resolved actor")
    _require_keys(value, {"actor_id", "name", "source"}, "resolved actor")
    if (
        value.get("name") != expected_name
        or value.get("actor_id") != expected_name
        or value.get("source") != "core.combat.decisions.resolve_pc_action_actor"
    ):
        raise SP3BEvidenceError("K2-02 resolved actor is missing or does not match the fixture")
    return dict(value)


def _validate_actual_action(
    value: Any, actor_name: str, utterance: str
) -> dict[str, Any]:
    _require_mapping(value, "actual deterministic action")
    _require_keys(
        value,
        {
            "status",
            "input_text",
            "actor_name",
            "source",
            "parser_source",
            "apply_source",
            "parse_result",
            "applied_event",
        },
        "actual deterministic action",
    )
    if (
        value.get("status") != "handled"
        or value.get("input_text") != utterance
        or value.get("actor_name") != actor_name
        or value.get("source") != "core.combat.decisions.run_pc_action_decision"
        or value.get("parser_source")
        != "utils.combat_pc_action_parser.parse_pc_phase_action"
        or value.get("apply_source")
        != "utils.combat_pc_action_parser.apply_pc_phase_parse_result"
    ):
        raise SP3BEvidenceError("K2-02 deterministic action was not applied as observed")

    parse_result = value.get("parse_result")
    _require_mapping(parse_result, "deterministic parser result")
    _require_keys(
        parse_result,
        {
            "handled",
            "kind",
            "mechanical_feedback",
            "spoken_narration",
            "log_msg",
            "ledger_event",
            "fallback_reason",
            "target_name",
            "parsed_attack_roll",
            "parsed_heal_amount",
            "weapon_name",
            "character_updates",
            "encounter_ops",
            "changes_text",
        },
        "deterministic parser result",
    )
    output_text = parse_result.get("spoken_narration")
    if (
        parse_result.get("handled") is not True
        or parse_result.get("kind") != "movement"
        or not isinstance(output_text, str)
        or not output_text.startswith("Dungeon Master: ")
        or len(output_text) > 4096
        or parse_result.get("mechanical_feedback") is not None
        or parse_result.get("fallback_reason") != ""
        or parse_result.get("target_name") is not None
        or parse_result.get("parsed_attack_roll") is not None
        or parse_result.get("parsed_heal_amount") is not None
        or parse_result.get("weapon_name") is not None
        or parse_result.get("character_updates") != []
        or parse_result.get("encounter_ops") != []
        or parse_result.get("changes_text") != ""
    ):
        raise SP3BEvidenceError("K2-02 deterministic output is missing or unlinked")

    log_msg = parse_result.get("log_msg")
    if (
        not isinstance(log_msg, str)
        or not log_msg.startswith("[ALREADY_APPLIED]")
        or actor_name not in log_msg
        or len(log_msg) > 4096
    ):
        raise SP3BEvidenceError("K2-02 parser action log is missing or unlinked")

    ledger_event = parse_result.get("ledger_event")
    _require_mapping(ledger_event, "parser ledger event")
    _require_keys(ledger_event, {"kind", "facts"}, "parser ledger event")
    if ledger_event.get("kind") != "movement" or ledger_event.get("facts") != {}:
        raise SP3BEvidenceError("K2-02 parser movement event facts are inconsistent")

    applied_event = value.get("applied_event")
    _require_mapping(applied_event, "applied movement event")
    _require_keys(
        applied_event,
        {
            "kind",
            "actor_name",
            "target_name",
            "facts",
            "narration",
            "mechanics_already_applied",
        },
        "applied movement event",
    )
    if (
        applied_event.get("kind") != "movement"
        or applied_event.get("actor_name") != actor_name
        or applied_event.get("target_name") is not None
        or applied_event.get("facts") != {}
        or applied_event.get("narration")
        != output_text.replace("Dungeon Master: ", "")
        or applied_event.get("mechanics_already_applied") is not True
    ):
        raise SP3BEvidenceError("K2-02 applied movement event is inconsistent")
    return dict(value)


def _validate_request_observer(
    value: Any,
    receipt_values: Any,
    identity: Mapping[str, Any],
    script_step_ids: frozenset[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    _require_mapping(value, "request observer coverage")
    _require_keys(
        value,
        {
            "status",
            "source",
            "run_id",
            "row_id",
            "row_run_id",
            "lifecycle_id",
            "started_at_utc",
            "finished_at_utc",
            "max_receipts",
            "receipt_count",
            "receipt_sequences",
            "observer_errors",
            "step",
        },
        "request observer coverage",
    )
    for key in ("run_id", "row_id", "row_run_id", "lifecycle_id"):
        if value.get(key) != identity[key]:
            raise SP3BEvidenceError("request observer %s linkage is invalid" % key)
    if (
        value.get("status") != "complete"
        or value.get("source")
        != "scripts.mapping_pilot.server.install_router_receipt_observer"
        or type(value.get("observer_errors")) is not int
        or value.get("observer_errors") != 0
    ):
        raise SP3BEvidenceError("complete request-observer coverage is unavailable")

    started = _parse_timestamp(value.get("started_at_utc"), "observer start")
    finished = _parse_timestamp(value.get("finished_at_utc"), "observer finish")
    if finished <= started:
        raise SP3BEvidenceError("request-observer window is not strictly ordered")

    max_receipts = value.get("max_receipts")
    if (
        type(max_receipts) is not int
        or max_receipts < 1
        or max_receipts > MAX_ROUTER_RECEIPTS
    ):
        raise SP3BEvidenceError("request-observer receipt bound is invalid")
    if not isinstance(receipt_values, Sequence) or isinstance(
        receipt_values, (str, bytes)
    ):
        raise SP3BEvidenceError("router receipt evidence must be a sequence")
    if len(receipt_values) > max_receipts:
        raise SP3BEvidenceError("router receipts exceed the observer bound")
    receipt_count = value.get("receipt_count")
    if type(receipt_count) is not int or receipt_count != len(receipt_values):
        raise SP3BEvidenceError("request-observer receipt count is incomplete")
    sequences = value.get("receipt_sequences")
    expected_sequences = list(range(1, receipt_count + 1))
    if sequences != expected_sequences:
        raise SP3BEvidenceError("request-observer receipt sequence coverage is incomplete")

    step = value.get("step")
    _require_mapping(step, "K2-02 observer step window")
    _require_keys(
        step,
        {"step_id", "status", "started_at_utc", "finished_at_utc", "request_count"},
        "K2-02 observer step window",
    )
    if step.get("step_id") != "K2-02" or step.get("status") != "complete":
        raise SP3BEvidenceError("K2-02 observer step window is incomplete")
    step_start = _parse_timestamp(step.get("started_at_utc"), "K2-02 step start")
    step_finish = _parse_timestamp(step.get("finished_at_utc"), "K2-02 step finish")
    if (
        step_finish <= step_start
        or step_start < started
        or step_finish > finished
    ):
        raise SP3BEvidenceError("K2-02 step is outside the complete observer window")

    receipts: list[dict[str, Any]] = []
    attempt_ids: set[str] = set()
    matching_step_receipts = 0
    for expected_sequence, raw in enumerate(receipt_values, start=1):
        _require_mapping(raw, "router receipt")
        record = dict(raw)
        if (
            record.get("event_type") != "router_receipt"
            or record.get("row_run_id") != identity["row_run_id"]
            or record.get("lifecycle_id") != identity["lifecycle_id"]
            or type(record.get("sequence")) is not int
            or record.get("sequence") != expected_sequence
        ):
            raise SP3BEvidenceError("router receipt identity or sequence is invalid")
        call_id = _require_token(record.get("call_id"), "receipt call_id")
        attempt_id = _require_token(record.get("attempt_id"), "receipt attempt_id")
        step_id = record.get("script_step_id")
        if not isinstance(step_id, str) or step_id not in script_step_ids:
            raise SP3BEvidenceError("router receipt step attribution is missing or unknown")
        if attempt_id in attempt_ids:
            raise SP3BEvidenceError("router receipt attempt_id is duplicated")
        attempt_ids.add(attempt_id)
        attribution = record.get("attribution")
        expected = record.get("provider_call_expected")
        if (
            record.get("attribution_status") != "recorded"
            or type(expected) is not bool
        ):
            raise SP3BEvidenceError("router receipt attribution is incomplete")
        if attribution == "model_bearing_turn":
            if expected is not True:
                raise SP3BEvidenceError("model receipt lacks step attribution")
        elif attribution == "lifecycle_control":
            if expected is not False:
                raise SP3BEvidenceError("lifecycle receipt has an invalid request expectation")
        else:
            raise SP3BEvidenceError("router receipt has unknown attribution")
        if step_id == "K2-02":
            matching_step_receipts += 1
        record["call_id"] = call_id
        receipts.append(record)

    request_count = step.get("request_count")
    if (
        type(request_count) is not int
        or request_count != matching_step_receipts
        or matching_step_receipts != 0
    ):
        raise SP3BEvidenceError("K2-02 has a model request or inconsistent request count")
    return dict(value), receipts, dict(step)


def _validate_canonical_state(
    value: Any,
    step_window: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_mapping(value, "canonical before/after state")
    _require_keys(value, {"before", "after"}, "canonical before/after state")
    before = _validate_state_snapshot(value.get("before"))
    after = _validate_state_snapshot(value.get("after"))
    step_start = _parse_timestamp(step_window["started_at_utc"], "K2-02 step start")
    step_finish = _parse_timestamp(step_window["finished_at_utc"], "K2-02 step finish")
    before_time = _parse_timestamp(before["captured_at_utc"], "canonical before time")
    after_time = _parse_timestamp(after["captured_at_utc"], "canonical after time")
    if before_time >= step_start or after_time <= step_finish:
        raise SP3BEvidenceError("canonical state snapshots do not bracket K2-02")
    if before["snapshot"] != after["snapshot"]:
        raise SP3BEvidenceError(
            "K2-02 deterministic movement changed canonical mechanical state"
        )
    return before, after


def _validate_state_snapshot(value: Any) -> dict[str, Any]:
    _require_mapping(value, "canonical state snapshot")
    _require_keys(value, {"captured_at_utc", "snapshot"}, "canonical state snapshot")
    _parse_timestamp(value.get("captured_at_utc"), "canonical state snapshot time")
    snapshot = value.get("snapshot")
    _require_mapping(snapshot, "canonical sandbox state hash")
    _require_keys(snapshot, {"status", "sha256", "files"}, "canonical sandbox state hash")
    if snapshot.get("status") != "recorded":
        raise SP3BEvidenceError("canonical sandbox state hash is not recorded")
    _require_sha256(snapshot.get("sha256"), "canonical sandbox state sha256")
    files = snapshot.get("files")
    _require_mapping(files, "canonical sandbox state file hashes")
    if not files or len(files) > 4096:
        raise SP3BEvidenceError("canonical sandbox state file set is empty or over-bound")

    has_party_tracker = False
    has_character = False
    has_area = False
    has_encounter = False
    normalized_files: dict[str, str] = {}
    for path, digest in files.items():
        if (
            not isinstance(path, str)
            or not path.isascii()
            or path.startswith("/")
            or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise SP3BEvidenceError("canonical sandbox state path is unsafe")
        _require_sha256(digest, "canonical file sha256")
        is_character = bool(re.fullmatch(r"characters/[A-Za-z0-9._-]+\.json", path))
        is_area = bool(
            re.fullmatch(
                r"modules/Mapping_Pilot_Arena/areas/[A-Za-z0-9._-]+\.json",
                path,
            )
        )
        is_encounter = bool(
            re.fullmatch(
                r"(?:modules/encounters|encounters)/[A-Za-z0-9._-]+\.json",
                path,
            )
        )
        is_module_plot = path == "modules/Mapping_Pilot_Arena/module_plot.json"
        if path == "party_tracker.json":
            has_party_tracker = True
        elif is_character:
            has_character = True
        elif is_area:
            has_area = True
        elif is_encounter:
            has_encounter = True
        elif not is_module_plot:
            raise SP3BEvidenceError("canonical sandbox state contains an unrecognized source path")
        normalized_files[path] = digest
    if not (has_party_tracker and has_character and has_area and has_encounter):
        raise SP3BEvidenceError(
            "canonical combat state must include party, character, area, and encounter files"
        )
    canonical = json.dumps(
        normalized_files,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if hashlib.sha256(canonical.encode("ascii")).hexdigest() != snapshot["sha256"]:
        raise SP3BEvidenceError("canonical sandbox state hash does not match its file hashes")
    return {
        "captured_at_utc": value["captured_at_utc"],
        "snapshot": {
            "status": "recorded",
            "sha256": snapshot["sha256"],
            "files": normalized_files,
        },
    }


def _validate_zone_event(
    value: Mapping[str, Any], *, sequence: int | None
) -> dict[str, Any]:
    _require_mapping(value, "zone event")
    expected = {
        "run_id",
        "row_id",
        "row_run_id",
        "lifecycle_id",
        "step_id",
        "actor_id",
        "kind",
        "source",
        "observed_at_utc",
        "payload",
    }
    if sequence is not None:
        expected.add("sequence")
    _require_keys(value, expected, "zone event")
    identity = _validate_event_identity(value)
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _ZONE_EVENT_KINDS:
        raise SP3BEvidenceError("zone event kind is not allowlisted")
    _parse_timestamp(value.get("observed_at_utc"), "zone event time")
    source = _validate_event_source(value.get("source"), kind)
    payload = _validate_zone_payload(kind, value.get("payload"), identity["actor_id"])
    if source.get("status") == "missing" and source.get("reason") != payload.get("reason"):
        raise SP3BEvidenceError("missing zone source and unknown payload reasons differ")
    record = {
        **identity,
        "kind": kind,
        "source": source,
        "observed_at_utc": value["observed_at_utc"],
        "payload": payload,
    }
    if sequence is not None:
        if type(value.get("sequence")) is not int or value.get("sequence") != sequence:
            raise SP3BEvidenceError("zone event record sequence is invalid")
        record["sequence"] = sequence
    _ensure_json_value(record, "zone event")
    return record


def _validate_event_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("run_id", "row_id", "row_run_id", "lifecycle_id", "step_id", "actor_id")
    result: dict[str, Any] = {}
    for field in fields:
        result[field] = _require_token(value.get(field), "zone event %s" % field)
    if not result["run_id"].startswith("sp3b-"):
        raise SP3BEvidenceError("zone event run_id must be SP3b-scoped")
    row_match = re.fullmatch(r"SP3B-(0(?:1[2-9]))", result["row_id"])
    if row_match is None:
        raise SP3BEvidenceError("zone event row_id must be SP3B-012 through SP3B-019")
    return result


def _validate_event_source(value: Any, kind: str) -> dict[str, Any]:
    _require_mapping(value, "zone event source")
    status = value.get("status")
    if status == "missing":
        _require_keys(value, {"status", "kind", "reference", "reason"}, "missing event source")
        if (
            kind != "unknown"
            or value.get("kind") is not None
            or value.get("reference") is not None
        ):
            raise SP3BEvidenceError("a missing source must be represented as explicit unknown")
        _require_reason(value.get("reason"), "missing source reason")
        return dict(value)
    _require_keys(value, {"status", "kind", "reference"}, "zone event source")
    expected_kind = {
        "movement_hint": "movement_hint_observer_record",
        "enemy_phase": "applied_enemy_phase_result",
        "unknown": "unknown_evidence_source",
    }[kind]
    if status != "recorded" or value.get("kind") != expected_kind:
        raise SP3BEvidenceError("zone event source is missing or has the wrong kind")
    reference = value.get("reference")
    if (
        not isinstance(reference, str)
        or not reference
        or len(reference) > 240
        or reference.startswith("/")
        or "\\" in reference
        or any(part in ("", ".", "..") for part in reference.split("/"))
        or not reference.isascii()
    ):
        raise SP3BEvidenceError("zone event source reference is invalid")
    return dict(value)


def _validate_zone_payload(kind: str, value: Any, actor_id: str) -> dict[str, Any]:
    _require_mapping(value, "zone event payload")
    if kind == "movement_hint":
        _require_keys(value, {"status", "hint", "reason"}, "movement hint payload")
        status = value.get("status")
        hint = value.get("hint")
        reason = value.get("reason")
        if not isinstance(status, str) or status not in _MOVEMENT_HINT_STATUSES:
            raise SP3BEvidenceError("movement hint status is invalid")
        if status == "valid":
            _validate_hint_payload(hint)
            if reason is not None:
                raise SP3BEvidenceError("valid movement hint cannot have an unknown reason")
        else:
            if status == "missing" and hint is not None:
                raise SP3BEvidenceError("missing movement hint cannot contain a hint payload")
            if status == "invalid" and hint is not None:
                _ensure_json_value(hint, "invalid movement hint payload")
            _require_reason(reason, "movement hint missing/invalid reason")
        return copy.deepcopy(dict(value))

    if kind == "enemy_phase":
        _require_keys(value, {"status", "applied", "fact", "reason"}, "enemy phase payload")
        status = value.get("status")
        if status == "applied":
            fact = value.get("fact")
            _require_mapping(fact, "applied enemy phase fact")
            _require_keys(
                fact,
                {
                    "actor_id",
                    "status",
                    "from_zone",
                    "to_zone",
                    "target_actor_id",
                    "path",
                    "reason",
                },
                "applied enemy phase fact",
            )
            fact_actor = _require_token(fact.get("actor_id"), "enemy phase actor_id")
            if (
                value.get("applied") is not True
                or fact_actor != actor_id
                or not isinstance(fact.get("status"), str)
                or fact.get("status") not in _ENEMY_PHASE_STATUSES
                or value.get("reason") is not None
            ):
                raise SP3BEvidenceError("enemy phase event is not an applied actor fact")
            _validate_enemy_fact(fact)
        else:
            if status not in ("missing", "invalid", "unknown"):
                raise SP3BEvidenceError("enemy phase status is invalid")
            if value.get("applied") is not False or value.get("fact") is not None:
                raise SP3BEvidenceError("unavailable enemy phase cannot contain applied facts")
            _require_reason(value.get("reason"), "enemy phase unknown reason")
        return copy.deepcopy(dict(value))

    _require_keys(value, {"subject", "status", "reason"}, "unknown zone payload")
    if value.get("subject") not in ("movement_hint", "enemy_phase") or value.get("status") != "unknown":
        raise SP3BEvidenceError("unknown zone event must name its missing evidence subject")
    _require_reason(value.get("reason"), "unknown zone evidence reason")
    if actor_id != "unknown" and not _TOKEN.fullmatch(actor_id):
        raise SP3BEvidenceError("unknown zone event actor linkage is invalid")
    return copy.deepcopy(dict(value))


def _validate_hint_payload(value: Any) -> None:
    _require_mapping(value, "valid movement hint")
    _require_keys(value, {"from", "to", "disengage", "cover_sought"}, "valid movement hint")
    for key in ("from", "to"):
        _require_token(value.get(key), "movement hint %s" % key)
    if type(value.get("disengage")) is not bool:
        raise SP3BEvidenceError("movement hint disengage must be boolean")
    cover = value.get("cover_sought")
    if cover is not None:
        _require_token(cover, "movement hint cover_sought")


def _validate_enemy_fact(value: Mapping[str, Any]) -> None:
    for key in ("from_zone", "to_zone", "reason"):
        _require_token(value.get(key), "enemy phase %s" % key)
    target = value.get("target_actor_id")
    if target is not None:
        _require_token(target, "enemy phase target actor")
    path = value.get("path")
    if (
        not isinstance(path, Sequence)
        or isinstance(path, (str, bytes))
        or not path
    ):
        raise SP3BEvidenceError("applied enemy phase path is missing")
    normalized_path = [_require_token(item, "enemy phase path zone") for item in path]
    if normalized_path[0] != value["from_zone"] or normalized_path[-1] != value["to_zone"]:
        raise SP3BEvidenceError("applied enemy phase path does not match its endpoints")
    if len(set(normalized_path)) != len(normalized_path):
        raise SP3BEvidenceError("applied enemy phase path contains a repeated zone")
    if value["status"] in ("held", "joined"):
        if value["from_zone"] != value["to_zone"] or len(normalized_path) != 1:
            raise SP3BEvidenceError("held/joined enemy phase fact changed zones")
    elif value["from_zone"] == value["to_zone"] or len(normalized_path) < 2:
        raise SP3BEvidenceError("moving enemy phase fact did not change zones")
    if value["status"] in ("joined", "moved", "moved_and_joined") and target is None:
        raise SP3BEvidenceError("enemy phase target actor is missing")


def _zone_event_directory(
    root: Path, identity: Mapping[str, Any], *, create: bool
) -> Path:
    directory = (
        root
        / "mapping_pilot"
        / "zone_events"
        / str(identity["row_run_id"])
        / str(identity["lifecycle_id"])
    )
    _reject_path_symlinks(root, directory)
    if create:
        current = root
        for part in directory.relative_to(root).parts:
            current = current / part
            _reject_path_symlinks(root, current)
            current.mkdir(exist_ok=True)
            if not current.is_dir():
                raise SP3BEvidenceError("zone event path component is not a directory")
    elif not directory.is_dir():
        raise SP3BEvidenceError("zone event trace is missing")
    _reject_path_symlinks(root, directory)
    return directory


def _read_zone_records(
    directory: Path,
    identity: Mapping[str, Any],
    *,
    allow_empty: bool,
) -> list[dict[str, Any]]:
    if not directory.is_dir() or directory.is_symlink():
        raise SP3BEvidenceError("zone event directory is unavailable or unsafe")
    entries = list(directory.iterdir())
    if any(
        entry.name != ".sequence.lock"
        and re.fullmatch(r"record-[0-9]{8}\.json", entry.name) is None
        for entry in entries
    ):
        raise SP3BEvidenceError("zone event directory contains an unexpected artifact")
    paths = sorted(
        (entry for entry in entries if entry.name.startswith("record-")),
        key=lambda item: item.name,
    )
    expected_names = ["record-%08d.json" % index for index in range(1, len(paths) + 1)]
    if [path.name for path in paths] != expected_names:
        raise SP3BEvidenceError("zone event records are not contiguous and ordered")
    if not paths and not allow_empty:
        raise SP3BEvidenceError("empty zone trace cannot establish success or zero contradictions")
    output: list[dict[str, Any]] = []
    previous_time: datetime | None = None
    for index, path in enumerate(paths, start=1):
        if path.is_symlink() or not path.is_file():
            raise SP3BEvidenceError("zone event record path is unsafe")
        try:
            raw = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise SP3BEvidenceError("zone event record is invalid JSON") from exc
        record = _validate_zone_event(raw, sequence=index)
        for key in ("run_id", "row_id", "row_run_id", "lifecycle_id"):
            if record[key] != identity[key]:
                raise SP3BEvidenceError("zone event %s linkage changed" % key)
        event_time = _parse_timestamp(record["observed_at_utc"], "zone event time")
        if previous_time is not None and event_time <= previous_time:
            raise SP3BEvidenceError("zone event timestamps are not strictly increasing")
        previous_time = event_time
        output.append(record)
    return output


def _resolve_evidence_root(value: str | Path) -> Path:
    requested = Path(value)
    if not requested.is_absolute():
        if ".." in requested.parts or "\\" in str(value):
            raise SP3BEvidenceError("zone evidence root is unsafe")
        requested = PROJECT_ROOT / requested
    try:
        root = requested.resolve(strict=True)
        project_tmp = (PROJECT_ROOT / "tmp").resolve(strict=True)
        root.relative_to(project_tmp)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SP3BEvidenceError("zone evidence root must be inside project-local tmp/") from exc
    if requested != root or not root.is_dir():
        raise SP3BEvidenceError("zone evidence root is not a canonical directory")
    return root


def _reject_path_symlinks(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SP3BEvidenceError("zone evidence path escaped its runtime root") from exc
    current = root
    if root.is_symlink():
        raise SP3BEvidenceError("zone evidence root is a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SP3BEvidenceError("zone evidence path contains a symlink")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise SP3BEvidenceError("%s must be a UTC ISO timestamp" % label)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SP3BEvidenceError("%s is not a valid UTC timestamp" % label) from exc
    return parsed


def _require_mapping(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise SP3BEvidenceError("%s must be an object" % label)


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SP3BEvidenceError("%s fields are incomplete or unexpected" % label)


def _require_token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise SP3BEvidenceError("%s is missing or invalid" % label)
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SP3BEvidenceError("%s is missing or invalid" % label)
    return value


def _require_reason(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or not value.isascii()
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,159}", value)
    ):
        raise SP3BEvidenceError("%s is required" % label)
    return value


def _ensure_json_value(value: Any, label: str) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise SP3BEvidenceError("%s is not bounded JSON data" % label) from exc
    if len(encoded) > 16384:
        raise SP3BEvidenceError("%s exceeds the evidence size bound" % label)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value: %s" % value)
