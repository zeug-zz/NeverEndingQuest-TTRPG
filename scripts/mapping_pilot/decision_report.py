# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Compose immutable, evidence-linked SP4 decision reports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    MANIFEST_NAME,
    PROJECT_ROOT,
    verify_manifest,
)
from scripts.mapping_pilot.review import (
    DEFAULT_REVIEW_KEY_ROOT,
    DEFAULT_REVIEW_ROOT,
    RATINGS_FILENAME,
    REVIEW_MANIFEST_FILENAME,
    RATING_LOCK_FILENAME,
    release_condition_key,
)
from scripts.mapping_pilot.scoring import score_matrix


DEFAULT_SP3_ROOT = Path("tmp/router-rollout/mapping-pilot/sp3")
DEFAULT_D1_ROOT = Path("tmp/router-rollout/mapping-pilot/d1")
DEFAULT_M1_ROOT = Path("tmp/router-rollout/mapping-pilot/m1")
DEFAULT_REPORT_ROOT = Path("tmp/router-rollout/mapping-pilot/sp4")
REPORT_FILENAME = "decision_report.json"
REPORT_MANIFEST_FILENAME = "manifest.json"

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SLOT_STATUSES = frozenset(("PASS", "FAIL", "BLOCKED", "missing"))
_OWNER_AUDIT_FIELDS = ("owner_correct", "owner_incorrect", "owner_invented")
_RUBRIC_FIELDS = (
    ("sense_of_place", 1),
    ("imaginability", 2),
    ("natural_use", 3),
    ("actionability", 4),
    ("continuity", 5),
    ("combat_clarity_and_flow", 6),
)


class DecisionReportError(ValueError):
    """Raised when report inputs are invalid or unsafe."""


_HANDOFF_FIELDS: dict[str, dict[str, str]] = {
    "location.name": {
        "consumer": "Spatial projection names the current persistent location for narration and map context.",
        "meaning": "Authored name text; no numeric unit.",
        "ownership": "S1 schema/query contract; Builder MB1/MB2 generation requirements.",
    },
    "location.orientation": {
        "consumer": "The compact area-orientation line and the party's origin/facing support bearings and return continuity.",
        "meaning": "Categorical origin/facing or bearing; not metric coordinates.",
        "ownership": "S1 schema/query contract; Builder MB1/MB2 generation requirements.",
    },
    "exit.exists": {
        "consumer": "Projection and exit behavior distinguish supported routes from absent or unknown facts.",
        "meaning": "Authored graph/exit claim; absence is not asserted as nonexistence.",
        "ownership": "S1 graph contract; Builder MB1/MB2 generation; S3 backfill feasibility.",
    },
    "exit.side": {
        "consumer": "The narration can identify a perceived exit by a stable side, such as the north door.",
        "meaning": "Categorical schematic side; not a coordinate or distance.",
        "ownership": "S1 schema/query contract; Builder MB1/MB2 generation; S3 owner-audited backfill.",
    },
    "exit.known_destination_location_id": {
        "consumer": "Movement and continuity use a destination only when the authored graph binds it.",
        "meaning": "Module-scoped location ID or explicit unknown; never infer a destination.",
        "ownership": "S1 graph contract; Builder MB1/MB2 generation; S3 owner-audited backfill.",
    },
    "exit.destination_knowledge": {
        "consumer": "Narration preserves what the party knows beyond an exit.",
        "meaning": "Known/unknown state; unknown remains explicit.",
        "ownership": "S1 knowledge-filtered projection; Builder MB1/MB2 generation.",
    },
    "exit.state": {
        "consumer": "Players can act on whether a route is open, blocked, locked, or otherwise changed.",
        "meaning": "Authored state description; no unstated mechanical inference.",
        "ownership": "S1 projection; Builder MB1/MB2 generation; S3 owner-audited backfill.",
    },
    "exit.feature_id": {
        "consumer": "Stable feature identity links a door or route to the location projection.",
        "meaning": "Stable module-scoped feature ID.",
        "ownership": "S1 schema/query contract; Builder MB1/MB2 generation.",
    },
    "feature.name": {
        "consumer": "Named landmarks give the scene persistent anchors players can remember and use.",
        "meaning": "Authored or proposed label; proposal is not an authored fact.",
        "ownership": "S1 projection; Builder MB1/MB2 generation; S3 owner-audited backfill.",
    },
    "feature.position": {
        "consumer": "Schematic projection places landmarks so players can picture and act in the scene.",
        "meaning": "Schematic sector when supported; metric position is unknown unless explicitly authored. No exhaustive grid is assumed.",
        "ownership": "S1 projection/schema decision; Builder MB1/MB2 generation; S3 feasibility.",
    },
    "feature.reachable": {
        "consumer": "Projection separates reachable routes from visible-but-unreachable landmarks.",
        "meaning": "Reachability claim; unknown stays explicit and is not inferred from visibility.",
        "ownership": "S1 projection/query contract; Builder MB1/MB2 generation.",
    },
    "feature.state": {
        "consumer": "Continuity preserves committed feature changes across movement and save/resume.",
        "meaning": "Authored or persisted state; no metric unit.",
        "ownership": "S1 canonical state/projection contract; Builder MB1/MB2 generation.",
    },
    "visibility.perceivable": {
        "consumer": "Knowledge-filtered projections expose only facts the party can currently perceive or knows.",
        "meaning": "Perceivable/not-perceivable claim; source or owner evidence required.",
        "ownership": "S1 audience projection; Builder MB1/MB2 generation; S3 owner-audited backfill.",
    },
    "visibility.perceivable_facts": {
        "consumer": "Narration and map projections preserve visible facts without leaking hidden information.",
        "meaning": "Fact text; visibility is not inferred from proposal presence.",
        "ownership": "S1 knowledge-filtered projection; Builder MB1/MB2 generation.",
    },
    "visibility.hidden_facts": {
        "consumer": "Hidden facts remain outside player-facing projection until learned or perceived.",
        "meaning": "Fact text with explicit hidden/knowledge boundary.",
        "ownership": "S1 audience projection; Builder MB1/MB2 generation.",
    },
    "authored_distance": {
        "consumer": "A distance may be used only where the source authors one; pilot layout positions remain schematic.",
        "meaning": "Metric unit is unknown unless the authored source supplies it; otherwise not applicable.",
        "ownership": "S1 representation decision; Builder MB1/MB2 generation; S3 backfill feasibility.",
    },
}


class _InputCollector:
    def __init__(self) -> None:
        self._inputs: dict[str, dict[str, Any]] = {}

    def read(self, path: Path, role: str) -> bytes:
        absolute = path if path.is_absolute() else PROJECT_ROOT / path
        relative = _project_relative(absolute, "input path")
        _reject_symlink_components(PROJECT_ROOT / relative)
        try:
            payload = (PROJECT_ROOT / relative).read_bytes()
        except OSError as exc:
            raise DecisionReportError("cannot read input: %s" % relative.as_posix()) from exc
        record = self._inputs.setdefault(
            relative.as_posix(), {"path": relative.as_posix(), "roles": []}
        )
        digest = hashlib.sha256(payload).hexdigest()
        prior = record.get("sha256")
        if prior is not None and prior != digest:
            raise DecisionReportError("input changed while report was being assembled")
        record["sha256"] = digest
        if role not in record["roles"]:
            record["roles"].append(role)
        return payload

    def json(self, path: Path, role: str) -> dict[str, Any]:
        payload = self.read(path, role)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DecisionReportError("invalid JSON input: %s" % path) from exc
        if not isinstance(value, dict):
            raise DecisionReportError("JSON input must be an object: %s" % path)
        return value

    def records(self) -> list[dict[str, Any]]:
        return [
            {**record, "roles": sorted(record["roles"])}
            for _path, record in sorted(self._inputs.items())
        ]


def create_decision_report(
    run_id: str,
    *,
    score_rows_path: str | Path | None = None,
    sp3_run_id: str | None = None,
    d1_run_id: str | None = None,
    m1_run_id: str | None = None,
    review_run_id: str | None = None,
    execution_root: str | Path = DEFAULT_SP3_ROOT,
    d1_root: str | Path = DEFAULT_D1_ROOT,
    m1_root: str | Path = DEFAULT_M1_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    review_key_root: str | Path = DEFAULT_REVIEW_KEY_ROOT,
    output_root: str | Path = DEFAULT_REPORT_ROOT,
) -> Path:
    """Write one immutable report and return its project-relative directory.

    All run roots are project-relative paths below ``tmp/``. The frozen
    preregistration is verified before scoring; absent optional evidence remains
    explicit. Tests can inject isolated roots below project ``tmp/``.
    """
    _validate_token(run_id, "run_id")
    for value, label in (
        (sp3_run_id, "sp3_run_id"),
        (d1_run_id, "d1_run_id"),
        (m1_run_id, "m1_run_id"),
        (review_run_id, "review_run_id"),
    ):
        if value is not None:
            _validate_token(value, label)

    collector = _InputCollector()
    frozen = _load_frozen_inputs(collector)
    slots, ledger_status = _load_sp3_slots(
        collector, frozen["counterbalance"]["rows"], sp3_run_id, execution_root
    )
    d1 = _load_d1(collector, d1_run_id, d1_root)
    m1 = _load_m1(collector, m1_run_id, m1_root)
    live_ratings = _load_live_ratings(
        collector, review_run_id, review_root, review_key_root, frozen["counterbalance"]["rows"]
    )
    score_rows, score_input_status = _load_score_rows(collector, score_rows_path)
    _validate_score_rows_against_slots(score_rows, slots, ledger_status)

    factual_rows = [_without_owner_ratings(row) for row in score_rows]
    factual_matrix = score_matrix(factual_rows)
    decision_rows = _apply_live_ratings(factual_rows, live_ratings["by_row"])
    decision_matrix = score_matrix(decision_rows)

    recommendations = _recommendations(
        decision_matrix["decision_rules"], d1, m1
    )
    report = {
        "schema_version": 1,
        "report_run_id": run_id,
        "stage_1": {"status": "waived", "ratings": "not scored"},
        "input_status": {
            "sp3_ledger": ledger_status,
            "score_rows": score_input_status,
            "d1": d1["status"],
            "d1_owner_audit": d1["owner_audit_status"],
            "m1": m1["status"],
            "m1_owner_ratings": m1["ratings"]["status"],
            "live_transcript_ratings": live_ratings["status"],
        },
        "sp3_slots": {
            "run_id": sp3_run_id,
            "status_counts": _count_statuses(slots),
            "slots": slots,
        },
        "questions": _build_questions(
            decision_matrix["decision_rules"],
            factual_matrix,
            live_ratings,
            d1,
            m1,
        ),
        "recommendations": recommendations,
        "scoring": {
            "contract": "scripts.mapping_pilot.scoring.score_matrix",
            "factual_matrix": factual_matrix,
            "decision_rules_with_locked_live_ratings": decision_matrix[
                "decision_rules"
            ],
            "human_ratings_are_reported_separately": True,
        },
        "human_ratings": {
            "live_transcripts": live_ratings["summary"],
            "m1_sketches": m1["ratings"],
        },
        "d1": d1["summary"],
        "module_builder_handoff": {
            "authority": "plans/v2-narrative-overview.md#sp4-handoff-to-the-module-builder",
            "status": d1["status"],
            "sample_scope": d1["sample_scope"],
            "columns": [
                "spatial_fact_or_field",
                "consuming_projection_behavior_and_player_relevance",
                "proposed_field_units_and_schematic_or_metric_meaning",
                "authored_presence_missing_and_ambiguous_counts_with_denominators",
                "authored_derived_new_authoring_or_unknown_status",
                "ownership_and_follow_up",
                "d1_source_proposal_validation_evidence",
                "owner_audit_status",
            ],
            "rows": d1["handoff_rows"],
        },
        "implementation_inputs": _implementation_inputs(recommendations, d1, m1),
        "owner_gate": {
            "format_choice": "pending/not provided",
            "combat_granularity_and_enforcement_choice": "pending/not provided",
            "data_pipeline_choice": "pending/not provided",
            "adr_acceptance": "not part of this report; no acceptance implied",
        },
        "decision_rule_sources": frozen["rule_sources"],
        "input_hashes": collector.records(),
    }

    _ensure_json_value(report)
    report_bytes = json.dumps(
        report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False
    ).encode("ascii") + b"\n"
    output_rel, output_absolute = _tmp_root(output_root, "output_root")
    report_directory_rel = output_rel / run_id
    report_directory = PROJECT_ROOT / report_directory_rel
    _reject_symlink_components(report_directory)
    if report_directory.exists():
        raise FileExistsError("SP4 report run already exists")
    report_directory.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(report_directory)
    report_directory.mkdir(exist_ok=False)
    report_path = report_directory / REPORT_FILENAME
    with report_path.open("xb") as report_file:
        report_file.write(report_bytes)
    manifest = {
        "schema_version": 1,
        "complete": True,
        "report_run_id": run_id,
        "report_file": REPORT_FILENAME,
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "input_hashes": report["input_hashes"],
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False
    ).encode("ascii") + b"\n"
    with (report_directory / REPORT_MANIFEST_FILENAME).open("xb") as manifest_file:
        manifest_file.write(manifest_bytes)
    del output_absolute
    return report_directory_rel


def _load_frozen_inputs(collector: _InputCollector) -> dict[str, Any]:
    prereg_root = DEFAULT_PREREG_ROOT
    verified = verify_manifest(prereg_root)
    manifest_path = prereg_root / MANIFEST_NAME
    collector.read(manifest_path, "frozen preregistration manifest")
    frozen_payloads: dict[str, bytes] = {}
    for relative, expected in sorted(verified.items()):
        path = prereg_root / PurePosixPath(relative)
        payload = collector.read(path, "frozen preregistration input")
        if hashlib.sha256(payload).hexdigest() != expected:
            raise DecisionReportError("frozen preregistration hash changed")
        frozen_payloads[relative] = payload
    try:
        counterbalance = json.loads(frozen_payloads["counterbalance.json"].decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise DecisionReportError("frozen counterbalance is invalid") from exc
    if (
        not isinstance(counterbalance, Mapping)
        or not isinstance(counterbalance.get("rows"), list)
        or len(counterbalance["rows"]) != 30
    ):
        raise DecisionReportError("frozen counterbalance must contain 30 rows")

    rule_sources: list[dict[str, str]] = []
    for relative in (
        "plans/v2-mapping-pilot.md",
        "plans/v2-mapping-pilot-prereg/README.md",
        "plans/v2-mapping-pilot-prereg/rubric.md",
    ):
        payload = collector.read(PROJECT_ROOT / relative, "frozen decision-rule source")
        rule_sources.append(
            {"path": relative, "sha256": hashlib.sha256(payload).hexdigest()}
        )
    scoring_path = Path(__file__).resolve().with_name("scoring.py")
    scoring_payload = collector.read(scoring_path, "scoring implementation")
    rule_sources.append(
        {
            "path": _project_relative(scoring_path, "scoring implementation").as_posix(),
            "sha256": hashlib.sha256(scoring_payload).hexdigest(),
        }
    )
    return {"counterbalance": counterbalance, "rule_sources": rule_sources}


def _load_sp3_slots(
    collector: _InputCollector,
    frozen_rows: Sequence[Mapping[str, Any]],
    run_id: str | None,
    execution_root: str | Path,
) -> tuple[list[dict[str, Any]], str]:
    slots_by_id: dict[str, Mapping[str, Any]] = {}
    ledger_status = "pending/not provided"
    if run_id is not None:
        root_rel, _root_absolute = _tmp_root(execution_root, "execution_root")
        ledger_path = PROJECT_ROOT / root_rel / run_id / "matrix_ledger.json"
        if ledger_path.is_file():
            ledger = collector.json(ledger_path, "SP3 matrix ledger")
            if ledger.get("run_id") != run_id:
                raise DecisionReportError("SP3 ledger run ID does not match")
            raw_slots = ledger.get("slots")
            if not isinstance(raw_slots, list):
                raise DecisionReportError("SP3 ledger has no slot list")
            for slot in raw_slots:
                if not isinstance(slot, Mapping) or not isinstance(slot.get("row_id"), str):
                    raise DecisionReportError("SP3 ledger contains an invalid slot")
                if slot["row_id"] in slots_by_id:
                    raise DecisionReportError("SP3 ledger contains duplicate slots")
                if slot.get("status") not in _SLOT_STATUSES:
                    raise DecisionReportError("SP3 ledger contains an invalid slot status")
                slots_by_id[slot["row_id"]] = slot
            if list(slots_by_id) != [str(row["row_id"]) for row in frozen_rows]:
                raise DecisionReportError("SP3 ledger does not match frozen slot order")
            ledger_status = "provided"
        else:
            ledger_status = "pending/not provided; ledger file is absent"

    slots: list[dict[str, Any]] = []
    for frozen in frozen_rows:
        row_id = str(frozen["row_id"])
        actual = slots_by_id.get(row_id)
        if actual is None:
            status = "missing"
            reason = "no SP3 ledger provided" if run_id is None else "SP3 ledger file is absent"
            evidence_path = None
        else:
            status = str(actual["status"])
            reason = actual.get("reason")
            evidence_path = actual.get("evidence_path")
            if actual.get("row_type") != frozen.get("row_type"):
                raise DecisionReportError("SP3 ledger slot identity differs from frozen schedule")
        slots.append(
            {
                "row_id": row_id,
                "run_order": frozen.get("run_order"),
                "row_type": frozen.get("row_type"),
                "block": frozen.get("block"),
                "arm": frozen.get("arm"),
                "party": frozen.get("party"),
                "script": frozen.get("script"),
                "repeat": frozen.get("repeat"),
                "status": status,
                "reason": reason,
                "evidence_path": evidence_path,
                "replacement": actual.get("replacement") if actual is not None else None,
            }
        )
    return slots, ledger_status


def _load_d1(
    collector: _InputCollector, run_id: str | None, d1_root: str | Path
) -> dict[str, Any]:
    if run_id is None:
        return _empty_d1("pending/not provided")
    root_rel, _root_absolute = _tmp_root(d1_root, "d1_root")
    directory = PROJECT_ROOT / root_rel / run_id
    names = (
        "selection.json",
        "d1_attempt_ledger.json",
        "d1_audit_sheet.json",
        "d1_owner_audit.csv",
    )
    paths = {name: directory / name for name in names}
    if not directory.is_dir() or any(not path.is_file() for path in paths.values()):
        return _empty_d1("pending/not provided; D1 artifacts are incomplete", run_id)

    selection = collector.json(paths["selection.json"], "D1 sample selection")
    ledger = collector.json(paths["d1_attempt_ledger.json"], "D1 attempt ledger")
    audit = collector.json(paths["d1_audit_sheet.json"], "D1 validation and owner audit")
    owner_bytes = collector.read(paths["d1_owner_audit.csv"], "D1 owner audit input")
    if selection.get("run_id") != run_id:
        raise DecisionReportError("D1 selection run ID does not match")
    attempts = ledger.get("attempts")
    audit_proposals = audit.get("proposals")
    selected = selection.get("locations")
    if not all(isinstance(value, list) for value in (attempts, audit_proposals, selected)):
        raise DecisionReportError("D1 artifacts have invalid row collections")
    selection_by_key, descriptor_by_key = _validate_d1_selection(
        selected, ledger.get("selection"), audit.get("selection")
    )
    if len(attempts) > 60 or len(audit_proposals) != len(attempts):
        raise DecisionReportError("D1 attempt and audit counts do not match")
    if audit.get("attempt_count") != len(attempts):
        raise DecisionReportError("D1 audit attempt count does not match its ledger")
    if ledger.get("selection_fingerprint") != audit.get("selection_fingerprint"):
        raise DecisionReportError("D1 selection fingerprints differ across artifacts")

    attempts_by_number: dict[int, Mapping[str, Any]] = {}
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise DecisionReportError("D1 attempt ledger contains an invalid attempt")
        attempt_number = _parse_int(attempt.get("attempt_number"))
        if attempt_number is None or attempt_number in attempts_by_number:
            raise DecisionReportError("D1 attempt numbers are invalid or duplicated")
        attempts_by_number[attempt_number] = attempt
        _validate_d1_attempt_sources(attempt, descriptor_by_key)
    if set(attempts_by_number) != set(range(1, len(attempts) + 1)):
        raise DecisionReportError("D1 attempt numbers are not sequential")

    audit_rows_by_attempt: dict[int, Mapping[str, Any]] = {}
    for row in audit_proposals:
        if not isinstance(row, Mapping):
            raise DecisionReportError("D1 audit contains an invalid proposal row")
        attempt_number = _parse_int(row.get("attempt_number"))
        if attempt_number is None or attempt_number in audit_rows_by_attempt:
            raise DecisionReportError("D1 audit attempt numbers are invalid or duplicated")
        audit_rows_by_attempt[attempt_number] = row
        attempt = attempts_by_number.get(attempt_number)
        if attempt is None or row.get("location_key") != attempt.get("location_key"):
            raise DecisionReportError("D1 audit proposal does not match its attempt")
        source_evidence = row.get("source_evidence")
        if not isinstance(source_evidence, Mapping):
            raise DecisionReportError("D1 audit proposal has no source evidence")
        if (
            source_evidence.get("source_references") != attempt.get("source_references")
            or source_evidence.get("source_sha256") != attempt.get("source_sha256")
        ):
            raise DecisionReportError("D1 audit source evidence differs from its attempt")
    if set(audit_rows_by_attempt) != set(attempts_by_number):
        raise DecisionReportError("D1 audit and attempt entries do not match")

    owner_rows = _parse_csv(owner_bytes, "D1 owner audit CSV")
    if not owner_rows:
        raise DecisionReportError("D1 owner audit CSV has no claim rows")
    if len({row.get("claim_id") for row in owner_rows}) != len(owner_rows):
        raise DecisionReportError("D1 owner audit claim IDs are not unique")
    for owner_row in owner_rows:
        attempt_number = _parse_int(owner_row.get("attempt_number"))
        attempt = attempts_by_number.get(attempt_number) if attempt_number is not None else None
        if attempt is None or owner_row.get("location_key") != attempt.get("location_key"):
            raise DecisionReportError("D1 owner claim does not match its attempt")
        source_references = _parse_json_cell(owner_row.get("authored_source_reference"), None)
        source_hashes = _parse_json_cell(owner_row.get("authored_source_sha256"), None)
        if (
            source_references != attempt.get("source_references")
            or source_hashes != attempt.get("source_sha256")
        ):
            raise DecisionReportError("D1 owner claim source evidence differs from its attempt")

    owner_counts = _owner_audit_counts(owner_rows)
    owner_precision = audit.get("owner_precision")
    if not isinstance(owner_precision, Mapping):
        owner_precision = {}
    precision_percent = _valid_percent(owner_precision.get("percent"))
    precision_numerator = _nonnegative_int(owner_precision.get("numerator"))
    precision_denominator = _nonnegative_int(owner_precision.get("denominator"))
    precision_available = (
        precision_percent is not None
        and precision_numerator is not None
        and precision_denominator is not None
        and precision_denominator > 0
    )
    owner_precision_result = {
        "status": "provided"
        if precision_available
        else "pending/not provided"
        if owner_counts["audited_claims"] == 0
        else "partial",
        "numerator": precision_numerator,
        "denominator": precision_denominator,
        "percent": precision_percent,
        "notes": owner_precision.get("notes", ""),
    }
    invented_exit_count = _audited_invented_exit_count(owner_rows, owner_counts)
    automated_count = audit.get("invented_exit_count")
    automated_count_label = "automated graph-validator count; not owner-audited"
    if not isinstance(automated_count, int) or isinstance(automated_count, bool):
        automated_count = audit.get("invented_exit_count_known_lower_bound")
        automated_count_label = "automated graph-validator known lower bound; not owner-audited"
    if not isinstance(automated_count, int) or isinstance(automated_count, bool):
        automated_count = None

    sample_versions = []
    for key in sorted(selection_by_key):
        location = selection_by_key[key]
        descriptor = descriptor_by_key[key]
        sample_versions.append(
            {
                "location_key": "%s:%s"
                % (location.get("module_slug"), location.get("location_id")),
                "module_slug": location.get("module_slug"),
                "location_id": location.get("location_id"),
                "source_paths": location.get("source_paths", []),
                "source_sha256": location.get("source_sha256", {}),
                "d1_source_references": descriptor.get("source_references", []),
                "d1_source_sha256": descriptor.get("source_sha256", {}),
            }
        )
    sample_scope = {
        "selected_location_count": len(selected),
        "denominator": len(selected),
        "module_counts": dict(selection.get("module_quotas", {})),
        "source_commit": selection.get("commit"),
        "sampled_module_location_versions": sample_versions,
        "prevalence_note": "D1 is a selected sample, not a corpus-wide prevalence estimate.",
    }
    handoff_rows = _build_handoff_rows(
        owner_rows,
        attempts_by_number,
        audit_rows_by_attempt,
        len(selected),
        owner_counts["status"],
    )
    return {
        "status": "provided",
        "run_id": run_id,
        "sample_scope": sample_scope,
        "owner_precision": owner_precision_result,
        "owner_audit_status": owner_counts["status"],
        "owner_audit_counts": owner_counts,
        "owner_invented_exit_count": invented_exit_count,
        "automated_validator_invented_exit_count": {
            "value": automated_count,
            "label": automated_count_label,
            "evaluable": audit.get("invented_exit_count_evaluable") is True,
            "unresolved_graph_checks": audit.get("unresolved_graph_checks"),
        },
        "handoff_rows": handoff_rows,
        "summary": {
            "run_id": run_id,
            "owner_precision": owner_precision_result,
            "owner_audit_status": owner_counts["status"],
            "automated_validator_invented_exit_count": automated_count,
            "automated_validator_count_label": automated_count_label,
            "owner_invented_exit_count": invented_exit_count,
            "attempt_count": len(attempts),
            "validated_count": sum(1 for row in attempts if row.get("status") == "validated"),
            "invalid_layout_count": sum(1 for row in attempts if row.get("status") == "invalid_layout"),
            "unresolved_graph_checks": audit.get("unresolved_graph_checks"),
        },
    }


def _validate_d1_selection(
    selected: Sequence[Any], ledger_selection: Any, audit_selection: Any
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    """Bind the human-facing selection record to D1's compact source descriptor.

    ``selection.json`` carries sample metadata and ``modules/...`` paths, while
    the durable cartographer ledger stores sorted ``location_key`` descriptors
    with module-relative source references. They are related artifacts, not
    byte-for-byte copies.
    """
    if not isinstance(ledger_selection, list) or audit_selection != ledger_selection:
        raise DecisionReportError("D1 source selection differs across artifacts")
    if not selected or len(selected) > 30 or len(ledger_selection) != len(selected):
        raise DecisionReportError("D1 selected sample size is invalid")

    selected_by_key: dict[str, Mapping[str, Any]] = {}
    for location in selected:
        if not isinstance(location, Mapping):
            raise DecisionReportError("D1 selection contains an invalid location")
        module_slug = location.get("module_slug")
        location_id = location.get("location_id")
        if (
            not isinstance(module_slug, str)
            or not _SAFE_TOKEN.fullmatch(module_slug)
            or not module_slug
            or not isinstance(location_id, str)
            or not location_id
            or "/" in location_id
            or "\\" in location_id
        ):
            raise DecisionReportError("D1 selected location identity is invalid")
        key = "%s:%s" % (module_slug, location_id)
        if key in selected_by_key:
            raise DecisionReportError("D1 selection contains duplicate locations")
        paths = location.get("source_paths")
        hashes = location.get("source_sha256")
        if not isinstance(paths, list) or len(paths) != 1 or not isinstance(hashes, Mapping):
            raise DecisionReportError("D1 selected location source path/hash is invalid")
        source_path = paths[0]
        if not isinstance(source_path, str) or set(hashes) != {source_path}:
            raise DecisionReportError("D1 selected location source path/hash differs")
        parsed = PurePosixPath(source_path)
        if (
            parsed.is_absolute()
            or parsed.as_posix() != source_path
            or ".." in parsed.parts
            or "\\" in source_path
            or len(parsed.parts) != 4
            or parsed.parts[0] != "modules"
            or parsed.parts[1] != module_slug
            or parsed.parts[2] != "areas"
            or not parsed.parts[3].endswith("_BU.json")
        ):
            raise DecisionReportError("D1 selected source path is unsafe or unexpected")
        digest = hashes[source_path]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise DecisionReportError("D1 selected source hash is invalid")
        selected_by_key[key] = location

    descriptors: dict[str, Mapping[str, Any]] = {}
    for descriptor in ledger_selection:
        if not isinstance(descriptor, Mapping):
            raise DecisionReportError("D1 source descriptor is invalid")
        key = descriptor.get("location_key")
        references = descriptor.get("source_references")
        hashes = descriptor.get("source_sha256")
        if (
            not isinstance(key, str)
            or key not in selected_by_key
            or key in descriptors
            or not isinstance(references, list)
            or not references
            or any(not isinstance(reference, str) for reference in references)
            or not isinstance(hashes, Mapping)
            or set(references) != set(hashes)
            or len(references) != len(set(references))
        ):
            raise DecisionReportError("D1 source descriptor identity or evidence is invalid")
        module_slug = key.split(":", 1)[0]
        selected_location = selected_by_key[key]
        source_path = selected_location["source_paths"][0]
        source_reference = "/".join(PurePosixPath(source_path).parts[1:])
        if source_reference not in references:
            raise DecisionReportError("D1 descriptor omits the selected authored area")
        for reference in references:
            if (
                not isinstance(reference, str)
                or not reference
                or PurePosixPath(reference).is_absolute()
                or PurePosixPath(reference).as_posix() != reference
                or ".." in PurePosixPath(reference).parts
                or "\\" in reference
                or not PurePosixPath(reference).parts
                or PurePosixPath(reference).parts[0] != module_slug
            ):
                raise DecisionReportError("D1 source reference is unsafe or outside its module")
            digest = hashes[reference]
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise DecisionReportError("D1 source reference hash is invalid")
        if hashes[source_reference] != selected_location["source_sha256"][source_path]:
            raise DecisionReportError("D1 selected area hash differs from its source descriptor")
        descriptors[key] = descriptor
    if set(descriptors) != set(selected_by_key):
        raise DecisionReportError("D1 source descriptors do not match the selected sample")
    return selected_by_key, descriptors


def _validate_d1_attempt_sources(
    attempt: Mapping[str, Any], descriptors: Mapping[str, Mapping[str, Any]]
) -> None:
    key = attempt.get("location_key")
    descriptor = descriptors.get(key) if isinstance(key, str) else None
    if descriptor is None:
        raise DecisionReportError("D1 attempt is outside the selected sample")
    if (
        attempt.get("module_slug") != key.split(":", 1)[0]
        or attempt.get("location_id") != key.split(":", 1)[1]
        or attempt.get("source_references") != descriptor.get("source_references")
        or attempt.get("source_sha256") != descriptor.get("source_sha256")
    ):
        raise DecisionReportError("D1 attempt source evidence differs from the selection")


def _empty_d1(status: str, run_id: str | None = None) -> dict[str, Any]:
    pending = {"status": "pending/not provided", "numerator": None, "denominator": None, "percent": None, "notes": ""}
    return {
        "status": status,
        "run_id": run_id,
        "sample_scope": {
            "selected_location_count": 0,
            "denominator": 0,
            "module_counts": {},
            "source_commit": None,
            "sampled_module_location_versions": [],
            "prevalence_note": "No D1 sample was provided.",
        },
        "owner_precision": pending,
        "owner_audit_status": "pending/not provided",
        "owner_audit_counts": {"status": "pending/not provided", "total_claims": 0, "audited_claims": 0},
        "owner_invented_exit_count": None,
        "automated_validator_invented_exit_count": {
            "value": None,
            "label": "automated graph-validator count; not owner-audited",
            "evaluable": False,
            "unresolved_graph_checks": None,
        },
        "handoff_rows": _build_handoff_rows([], {}, {}, 0, "pending/not provided"),
        "summary": {
            "run_id": run_id,
            "owner_precision": pending,
            "owner_audit_status": "pending/not provided",
            "automated_validator_invented_exit_count": None,
            "automated_validator_count_label": "not owner-audited",
            "owner_invented_exit_count": None,
            "attempt_count": 0,
            "validated_count": 0,
            "invalid_layout_count": 0,
            "unresolved_graph_checks": None,
        },
    }


def _build_handoff_rows(
    owner_rows: Sequence[Mapping[str, str]],
    attempts: Mapping[int, Mapping[str, Any]],
    audit_rows: Mapping[int, Mapping[str, Any]],
    sample_count: int,
    owner_status: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in owner_rows:
        grouped[_handoff_field(row)].append(row)
    for field in _HANDOFF_FIELDS:
        grouped.setdefault(field, [])

    results = []
    for field in sorted(grouped):
        claims = grouped[field]
        locations = sorted({row.get("location_key", "") for row in claims if row.get("location_key")})
        metadata = _HANDOFF_FIELDS.get(
            field,
            {
                "consumer": "D1 proposal field; consuming behavior is not mapped by the frozen pilot contract.",
                "meaning": "Proposed value only; units and authored meaning remain unknown.",
                "ownership": "S1/Builder follow-up requires the separate contract review; no implementation is authorized here.",
            },
        )
        evidence = []
        for claim in claims[:3]:
            attempt_number = _parse_int(claim.get("attempt_number"))
            attempt = attempts.get(attempt_number, {}) if attempt_number is not None else {}
            audit = audit_rows.get(attempt_number, {}) if attempt_number is not None else {}
            source_refs = _parse_json_cell(claim.get("authored_source_reference"), [])
            source_hashes = _parse_json_cell(claim.get("authored_source_sha256"), {})
            graph_check = audit.get("graph_check", {})
            evidence.append(
                {
                    "claim_id": claim.get("claim_id"),
                    "location_key": claim.get("location_key"),
                    "attempt_number": attempt_number,
                    "proposal_field": claim.get("claim_field"),
                    "entity_id": claim.get("entity_id"),
                    "proposal_value": _parse_json_cell(
                        claim.get("proposed_claim"), claim.get("proposed_claim")
                    ),
                    "proposal_is_authored_fact": False,
                    "source_references": source_refs,
                    "source_sha256": source_hashes,
                    "validation_status": audit.get("status", attempt.get("status", "not assessed")),
                    "validation_issue_count": len(audit.get("validation_issues", []))
                    if isinstance(audit.get("validation_issues"), list)
                    else None,
                    "graph_check_evaluable": graph_check.get("evaluable")
                    if isinstance(graph_check, Mapping)
                    else None,
                    "graph_check_issue_count": len(graph_check.get("issues", []))
                    if isinstance(graph_check, Mapping) and isinstance(graph_check.get("issues"), list)
                    else None,
                    "owner_judgment": {
                        "status": "provided"
                        if _claim_has_owner_status(claim)
                        else "pending/not provided",
                        "correct": (claim.get("owner_correct") or "").strip() or None,
                        "incorrect": (claim.get("owner_incorrect") or "").strip() or None,
                        "invented": (claim.get("owner_invented") or "").strip() or None,
                        "notes": (claim.get("owner_notes") or "").strip() or None,
                    },
                }
            )
        audited = sum(1 for row in claims if _claim_has_owner_status(row))
        sample_denominator = sample_count
        results.append(
            {
                "spatial_fact_or_field": field,
                "consuming_projection_behavior_and_player_relevance": metadata["consumer"],
                "proposed_field_units_and_schematic_or_metric_meaning": metadata["meaning"],
                "authored_presence_missing_and_ambiguous_counts_with_denominators": {
                    "d1_proposal_claims": len(claims),
                    "locations_with_proposal": len(locations),
                    "sample_location_denominator": sample_denominator,
                    "authored_presence_count": "not assessed",
                    "missing_count": "not assessed",
                    "ambiguous_count": "not assessed",
                    "reason": "D1 exports proposed claims, source references and validation results, but no field-by-field authored-presence ledger. Proposal presence is not authored presence.",
                },
                "authored_derived_new_authoring_or_unknown_status": {
                    "status": "unknown",
                    "reason": "The D1 evidence does not classify this field as authored, safely derived, or requiring new authoring.",
                },
                "ownership_and_follow_up": metadata["ownership"],
                "d1_source_proposal_validation_evidence": {
                    "sample_claim_count": len(claims),
                    "owner_audited_claim_count": audited,
                    "owner_audit_status": owner_status,
                    "claims": evidence,
                    "additional_claims_linked_by_input_hash": max(0, len(claims) - len(evidence)),
                },
                "owner_audit_status": owner_status if claims else "pending/not provided",
            }
        )
    return results


def _handoff_field(row: Mapping[str, str]) -> str:
    category = row.get("claim_category", "unknown")
    pointer = row.get("claim_field", "")
    parts = [part for part in pointer.split("/") if part]
    leaf = parts[-1] if parts else "unknown"
    if category == "exit_side":
        return "exit.side"
    if category == "visibility_perceivability_sightline":
        if leaf == "perceivable":
            return "visibility.perceivable"
        if "hidden_facts" in parts:
            return "visibility.hidden_facts"
        if "perceivable_facts" in parts:
            return "visibility.perceivable_facts"
        return "visibility." + leaf
    if category == "orientation":
        return "location.orientation"
    if category == "location":
        return "location." + leaf
    if category == "fact":
        if "hidden_facts" in parts:
            return "visibility.hidden_facts"
        if "perceivable_facts" in parts:
            return "visibility.perceivable_facts"
    if category == "authored_distance":
        return "authored_distance"
    if category in ("exit", "feature", "npc", "fact"):
        return category + "." + leaf
    return category + "." + leaf


def _owner_audit_counts(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    audited = sum(1 for row in rows if _claim_has_owner_status(row))
    if audited == 0:
        status = "pending/not provided"
    elif audited == len(rows):
        status = "complete"
    else:
        status = "partial"
    return {"status": status, "total_claims": len(rows), "audited_claims": audited}


def _audited_invented_exit_count(
    rows: Sequence[Mapping[str, str]], counts: Mapping[str, Any]
) -> int | None:
    exit_rows = [row for row in rows if row.get("claim_category") == "exit"]
    if counts.get("status") != "complete" or not exit_rows:
        return None
    invented = {
        (row.get("location_key", ""), row.get("entity_id", ""))
        for row in exit_rows
        if (row.get("owner_invented") or "").strip()
    }
    return len(invented)


def _claim_has_owner_status(row: Mapping[str, str]) -> bool:
    return sum(1 for name in _OWNER_AUDIT_FIELDS if (row.get(name) or "").strip()) == 1


def _load_m1(
    collector: _InputCollector, run_id: str | None, m1_root: str | Path
) -> dict[str, Any]:
    if run_id is None:
        return _empty_m1("pending/not provided")
    root_rel, _root_absolute = _tmp_root(m1_root, "m1_root")
    directory = PROJECT_ROOT / root_rel / run_id
    manifest_path = directory / "manifest.json"
    ratings_path = directory / "ratings.csv"
    if not manifest_path.is_file() or not ratings_path.is_file():
        return _empty_m1("pending/not provided; M1 artifacts are incomplete", run_id)
    manifest = collector.json(manifest_path, "M1 manifest")
    if manifest.get("run_id") != run_id or manifest.get("completion") != "complete":
        raise DecisionReportError("M1 manifest is incomplete or mismatched")
    artifact_hashes = manifest.get("artifact_sha256")
    sketches = manifest.get("sketches")
    if not isinstance(artifact_hashes, Mapping) or not isinstance(sketches, list):
        raise DecisionReportError("M1 manifest has invalid artifact records")
    collector.read(ratings_path, "M1 owner ratings")
    for name, expected in sorted(artifact_hashes.items()):
        if not isinstance(name, str) or not _safe_relative_filename(name):
            raise DecisionReportError("M1 manifest contains an unsafe artifact path")
        path = directory / name
        payload = collector.read(path, "M1 packet artifact")
        if not isinstance(expected, str) or hashlib.sha256(payload).hexdigest() != expected:
            raise DecisionReportError("M1 artifact hash does not match manifest")
    ratings_bytes = collector.read(ratings_path, "M1 owner ratings")
    rating_rows = _parse_csv(ratings_bytes, "M1 ratings CSV")
    sketch_ids = [
        sketch.get("sketch_id") for sketch in sketches if isinstance(sketch, Mapping)
    ]
    if len(sketch_ids) != len(sketches) or len(set(sketch_ids)) != len(sketch_ids):
        raise DecisionReportError("M1 sketch identities are invalid")
    ratings_by_id = {row.get("sketch_id"): row for row in rating_rows}
    if set(ratings_by_id) != set(sketch_ids):
        raise DecisionReportError("M1 ratings do not match manifest sketches")

    parsed: dict[str, list[int]] = {"legibility_1_5": [], "usefulness_1_5": []}
    rated_rows = 0
    for sketch_id in sketch_ids:
        row = ratings_by_id[sketch_id]
        values = {}
        for field in parsed:
            raw = (row.get(field) or "").strip()
            values[field] = _rating_value(raw, "M1 " + field) if raw else None
            if values[field] is not None:
                parsed[field].append(values[field])
        if all(values.values()):
            rated_rows += 1
    total_rows = len(sketch_ids)
    populated_cells = sum(len(values) for values in parsed.values())
    if populated_cells == 0:
        rating_status = "pending/not provided"
    elif rated_rows == total_rows:
        rating_status = "complete"
    else:
        rating_status = "partial"
    means = {
        field: round(sum(values) / len(values), 4) if values else None
        for field, values in parsed.items()
    }
    return {
        "status": "provided",
        "run_id": run_id,
        "ratings": {
            "status": rating_status,
            "rated_sketches": rated_rows,
            "sketch_denominator": total_rows,
            "legibility_mean": means["legibility_1_5"],
            "usefulness_mean": means["usefulness_1_5"],
            "threshold": "mean >= 3.5 for both legibility and usefulness",
            "input_path": (root_rel / run_id / "ratings.csv").as_posix(),
        },
        "summary": {
            "run_id": run_id,
            "ratings_status": rating_status,
            "rated_sketches": rated_rows,
            "sketch_denominator": total_rows,
            "legibility_mean": means["legibility_1_5"],
            "usefulness_mean": means["usefulness_1_5"],
        },
    }


def _empty_m1(status: str, run_id: str | None = None) -> dict[str, Any]:
    ratings = {
        "status": "pending/not provided",
        "rated_sketches": 0,
        "sketch_denominator": 0,
        "legibility_mean": None,
        "usefulness_mean": None,
        "threshold": "mean >= 3.5 for both legibility and usefulness",
        "input_path": None,
    }
    return {
        "status": status,
        "run_id": run_id,
        "ratings": ratings,
        "summary": {
            "run_id": run_id,
            "ratings_status": "pending/not provided",
            "rated_sketches": 0,
            "sketch_denominator": 0,
            "legibility_mean": None,
            "usefulness_mean": None,
        },
    }


def _load_live_ratings(
    collector: _InputCollector,
    review_run_id: str | None,
    review_root: str | Path,
    review_key_root: str | Path,
    frozen_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if review_run_id is None:
        return {
            "status": "pending/not provided",
            "by_row": {},
            "summary": {
                "status": "pending/not provided",
                "review_run_id": None,
                "reviewer_label": None,
                "locked_at": None,
                "rated_response_count": 0,
                "response_denominator": 0,
                "by_arm_sense_of_place": {},
            },
        }
    review_rel, _ = _tmp_root(review_root, "review_root")
    key_rel, _ = _tmp_root(review_key_root, "review_key_root")
    packet_directory = PROJECT_ROOT / review_rel / review_run_id
    key_directory = PROJECT_ROOT / key_rel / review_run_id
    packet_manifest = collector.json(
        packet_directory / REVIEW_MANIFEST_FILENAME, "locked live review manifest"
    )
    packet_files = packet_manifest.get("files")
    if not isinstance(packet_files, Mapping):
        raise DecisionReportError("live review manifest has no packet file map")
    for filename, expected in sorted(packet_files.items()):
        if not isinstance(filename, str) or not _safe_relative_filename(filename):
            raise DecisionReportError("live review manifest has an unsafe file path")
        payload = collector.read(packet_directory / filename, "locked live review packet")
        if not isinstance(expected, str) or hashlib.sha256(payload).hexdigest() != expected:
            raise DecisionReportError("live review packet hash does not match manifest")
    collector.read(packet_directory / RATING_LOCK_FILENAME, "live rating lock")
    key_manifest = collector.json(
        key_directory / REVIEW_MANIFEST_FILENAME, "condition-key manifest"
    )
    key_files = key_manifest.get("files")
    if not isinstance(key_files, Mapping):
        raise DecisionReportError("condition-key manifest has no file map")
    for filename, expected in sorted(key_files.items()):
        if not isinstance(filename, str) or not _safe_relative_filename(filename):
            raise DecisionReportError("condition-key manifest has an unsafe file path")
        payload = collector.read(key_directory / filename, "locked condition key")
        if not isinstance(expected, str) or hashlib.sha256(payload).hexdigest() != expected:
            raise DecisionReportError("condition-key hash does not match manifest")
    try:
        condition_key = release_condition_key(
            review_run_id, output_root=review_rel, key_root=key_rel
        )
    except (OSError, ValueError) as exc:
        raise DecisionReportError("live ratings are not validly locked") from exc
    ratings_bytes = collector.read(
        packet_directory / RATINGS_FILENAME, "locked live transcript ratings"
    )
    rating_rows = _parse_csv(ratings_bytes, "live transcript ratings CSV")
    rating_by_response = {row.get("response_id"): row for row in rating_rows}
    units = condition_key.get("response_units")
    if not isinstance(units, list) or len(rating_by_response) != len(units):
        raise DecisionReportError("locked ratings and condition key do not match")
    frozen_by_id = {str(row["row_id"]): row for row in frozen_rows}
    by_row: dict[str, dict[str, Any]] = {}
    sense_by_arm: dict[str, list[int]] = defaultdict(list)
    rated_responses = 0
    populated_scores = 0
    not_rateable_responses = 0
    for unit in units:
        if not isinstance(unit, Mapping):
            raise DecisionReportError("condition key contains an invalid response unit")
        response_id = unit.get("response_id")
        row_id = unit.get("row")
        rating = rating_by_response.get(response_id)
        frozen = frozen_by_id.get(str(row_id))
        if not isinstance(rating, Mapping) or frozen is None:
            raise DecisionReportError("locked rating response is not bound to a frozen row")
        if unit.get("arm") != frozen.get("arm"):
            raise DecisionReportError("condition key arm differs from frozen schedule")
        if (rating.get("not_rateable") or "").strip().casefold() == "not rateable":
            scores: dict[str, int] = {}
            row_status = "not rateable"
            not_rateable_responses += 1
        else:
            scores = {}
            for name, dimension in _RUBRIC_FIELDS:
                raw = (rating.get(name + "_1_5") or "").strip()
                if raw:
                    scores[str(dimension)] = _rating_value(raw, name)
            populated_scores += len(scores)
            applicable = (1, 2, 3, 4, 5) if frozen.get("block") == "exploration" else (1, 2, 3, 4, 5, 6)
            row_status = "complete" if all(str(value) in scores for value in applicable) else "partial"
        if str(row_id) in by_row:
            raise DecisionReportError("locked review contains duplicate row ratings")
        by_row[str(row_id)] = {
            "response_id": response_id,
            "arm": unit.get("arm"),
            "row_id": row_id,
            "status": row_status,
            "scores": scores,
        }
        if scores.get("1") is not None:
            sense_by_arm[str(unit.get("arm"))].append(scores["1"])
        if row_status == "complete":
            rated_responses += 1
    lock = collector.json(packet_directory / RATING_LOCK_FILENAME, "live rating lock")
    ratings_status = (
        "pending/not provided"
        if populated_scores == 0 and not not_rateable_responses
        else "complete"
        if rated_responses == len(units)
        else "partial"
    )
    arm_summary = {
        arm: {
            "mean": round(sum(values) / len(values), 4) if values else None,
            "rated_rows": len(values),
        }
        for arm, values in sorted(sense_by_arm.items())
    }
    return {
        "status": ratings_status,
        "by_row": by_row,
        "summary": {
            "status": ratings_status,
            "review_run_id": review_run_id,
            "reviewer_label": lock.get("reviewer_label"),
            "locked_at": lock.get("locked_at"),
            "rated_response_count": rated_responses,
            "not_rateable_response_count": not_rateable_responses,
            "response_denominator": len(units),
            "by_arm_sense_of_place": arm_summary,
        },
    }


def _load_score_rows(
    collector: _InputCollector, path_value: str | Path | None
) -> tuple[list[dict[str, Any]], str]:
    if path_value is None:
        return [], "pending/not provided"
    relative, absolute = _tmp_path(path_value, "score_rows_path")
    payload = collector.read(absolute, "SP3 score input rows")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DecisionReportError("score input file is invalid JSON") from exc
    rows = raw.get("rows") if isinstance(raw, Mapping) else raw
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise DecisionReportError("score input must be a row list or an object with rows")
    return [dict(row) for row in rows], "provided: %s" % relative.as_posix()


def _validate_score_rows_against_slots(
    rows: Sequence[Mapping[str, Any]], slots: Sequence[Mapping[str, Any]], ledger_status: str
) -> None:
    if not rows:
        return
    if ledger_status != "provided":
        raise DecisionReportError("score rows cannot be used without an SP3 ledger")
    status_by_id = {str(slot["row_id"]): slot["status"] for slot in slots}
    for row in rows:
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id not in status_by_id:
            raise DecisionReportError("score row does not match a frozen SP3 slot")
        if status_by_id[row_id] == "missing":
            raise DecisionReportError("score row has no corresponding SP3 attempt")


def _without_owner_ratings(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.pop("rubric_ratings", None)
    sketch = result.get("sketch_test")
    if isinstance(sketch, Mapping):
        sketch_copy = dict(sketch)
        sketch_copy.pop("owner_rating", None)
        result["sketch_test"] = sketch_copy
    return result


def _apply_live_ratings(
    rows: Sequence[Mapping[str, Any]], ratings_by_row: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for row in rows:
        current = dict(row)
        rating = ratings_by_row.get(str(current.get("row_id")))
        if rating is not None and rating.get("status") != "not rateable":
            current["rubric_ratings"] = dict(rating.get("scores", {}))
        results.append(current)
    return results


def _recommendations(
    decision_rules: Mapping[str, Any], d1: Mapping[str, Any], m1: Mapping[str, Any]
) -> list[dict[str, Any]]:
    candidate = decision_rules.get("b_vs_d", {})
    s2 = decision_rules.get("s2_spatial_packet", {})
    zones = decision_rules.get("zones_close_enough", {})
    zone_d = zones.get("by_arm", {}).get("D", {}) if isinstance(zones, Mapping) else {}
    s2_outcome = s2.get("outcome") if isinstance(s2, Mapping) else None
    if s2_outcome == "adopt":
        exploration_rec = "retain"
    else:
        exploration_rec = "inconclusive"
    bvd_outcome = candidate.get("outcome") if isinstance(candidate, Mapping) else None
    format_rec = "retain" if bvd_outcome in ("D_better", "B_default") else "inconclusive"
    selected_arm = candidate.get("selected_arm") if isinstance(candidate, Mapping) else None
    if bvd_outcome == "inconclusive":
        selected_arm = None
    zone_outcome = zones.get("outcome") if isinstance(zones, Mapping) else None
    zone_rec = {"pass": "retain", "fail": "revise"}.get(zone_outcome, "inconclusive")

    precision = d1.get("owner_precision", {})
    invented = d1.get("owner_invented_exit_count")
    if (
        isinstance(precision, Mapping)
        and precision.get("status") == "provided"
        and isinstance(precision.get("percent"), (int, float))
        and precision.get("percent") >= 85
        and invented == 0
    ):
        backfill_rec = "retain"
    elif (
        isinstance(precision, Mapping)
        and precision.get("status") == "provided"
        and isinstance(precision.get("percent"), (int, float))
        and (precision.get("percent") < 85 or (isinstance(invented, int) and invented > 0))
    ):
        backfill_rec = "reject"
    else:
        backfill_rec = "inconclusive"

    m1_ratings = m1.get("ratings", {})
    if isinstance(m1_ratings, Mapping) and m1_ratings.get("status") == "complete":
        legibility = m1_ratings.get("legibility_mean")
        usefulness = m1_ratings.get("usefulness_mean")
        map_rec = "retain" if legibility >= 3.5 and usefulness >= 3.5 else "revise"
    else:
        map_rec = "inconclusive"

    return [
        {
            "decision": "exploration_packet",
            "recommendation": exploration_rec,
            "choice": s2.get("selected_arm")
            if isinstance(s2, Mapping) and s2_outcome == "adopt"
            else None,
            "rule_outcome": s2_outcome or "not evaluated",
            "basis": "S2 is retained only when all frozen spatial-packet criteria pass; otherwise this report does not choose between revise and inconclusive.",
            "evidence": ["scoring.decision_rules_with_locked_live_ratings.s2_spatial_packet"],
        },
        {
            "decision": "format",
            "recommendation": format_rec,
            "choice": selected_arm,
            "rule_outcome": bvd_outcome or "not evaluated",
            "basis": "D is selected only by a frozen B-versus-D threshold; B is the frozen cheaper default only when the comparison is estimable.",
            "evidence": ["scoring.decision_rules_with_locked_live_ratings.b_vs_d"],
        },
        {
            "decision": "zone_combat",
            "recommendation": zone_rec,
            "choice": None,
            "rule_outcome": zone_outcome or "not evaluated",
            "basis": "The frozen zone/intent thresholds guide SC1 follow-up; no combat granularity or enforcement choice is made here.",
            "zone_evidence": zone_d,
            "evidence": ["scoring.decision_rules_with_locked_live_ratings.zones_close_enough"],
        },
        {
            "decision": "published_module_backfill",
            "recommendation": backfill_rec,
            "choice": "backfill" if backfill_rec == "retain" else None,
            "rule_outcome": "owner audit required: precision >= 85% and zero invented exits",
            "owner_precision": precision,
            "automated_validator_count": d1.get("automated_validator_invented_exit_count"),
            "owner_invented_exit_count": invented,
            "basis": "Automated graph-validator counts are not owner-audited precision and cannot satisfy the backfill gate.",
            "evidence": ["d1.owner_precision", "d1.automated_validator_invented_exit_count"],
        },
        {
            "decision": "shared_map",
            "recommendation": map_rec,
            "choice": "shared map" if map_rec == "retain" else None,
            "rule_outcome": "M1 means >= 3.5 for legibility and usefulness",
            "ratings": m1_ratings,
            "basis": "The S4 threshold is applied only to complete M1 owner ratings; otherwise the shared-map decision remains inconclusive.",
            "evidence": ["human_ratings.m1_sketches"],
        },
    ]


def _build_questions(
    decision_rules: Mapping[str, Any],
    factual_matrix: Mapping[str, Any],
    live_ratings: Mapping[str, Any],
    d1: Mapping[str, Any],
    m1: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = factual_matrix.get("rows", [])
    factual_status = "provided" if rows else "not evaluated"
    return [
        {
            "id": "Q1",
            "question": "Does the spatial packet improve the sense of a coherent, persistent place?",
            "status": live_ratings.get("summary", {}).get("status", "pending/not provided"),
            "human_evidence": live_ratings.get("summary", {}).get("by_arm_sense_of_place", {}),
            "factual_context": _factual_context(rows, ("spatial", "continuity", "knowledge_leakage")),
            "recommendation_ref": "exploration_packet",
        },
        {
            "id": "Q2",
            "question": "Which exploration representation, B or D, is supported by the frozen comparison?",
            "status": "provided" if decision_rules.get("b_vs_d", {}).get("complete_matched_cells", 0) else "not evaluated",
            "result": decision_rules.get("b_vs_d", {"outcome": "inconclusive", "reason": "not evaluated"}),
            "recommendation_ref": "format",
        },
        {
            "id": "Q3",
            "question": "Do the D-arm combat zone contradictions and movement-intent parses meet the frozen close-enough rule?",
            "status": decision_rules.get("zones_close_enough", {}).get("outcome", "inconclusive"),
            "result": decision_rules.get("zones_close_enough", {"outcome": "inconclusive"}),
            "recommendation_ref": "zone_combat",
        },
        {
            "id": "Q4",
            "question": "Does the owner-audited D1 evidence authorize published-module backfill?",
            "status": d1.get("owner_precision", {}).get("status", "pending/not provided"),
            "result": {
                "owner_precision": d1.get("owner_precision"),
                "owner_audit_status": d1.get("owner_audit_status"),
                "automated_validator_invented_exit_count": d1.get("automated_validator_invented_exit_count"),
                "owner_invented_exit_count": d1.get("owner_invented_exit_count"),
            },
            "recommendation_ref": "published_module_backfill",
        },
        {
            "id": "Q5",
            "question": "Do the M1 shared-map sketches meet the frozen legibility and usefulness threshold?",
            "status": m1.get("ratings", {}).get("status", "pending/not provided"),
            "result": m1.get("ratings", {}),
            "recommendation_ref": "shared_map",
        },
        {
            "id": "Q6",
            "question": "What are the measured token, latency, retry, attempt, and route-confound results?",
            "status": factual_status,
            "result": {
                "matrix_cap_accounting": factual_matrix.get("matrix_cap_accounting"),
                "route_by_arm": factual_matrix.get("route_by_arm"),
                "route_confounds": factual_matrix.get("route_confounds"),
                "rows": [
                    {
                        "row_id": row.get("row_id"),
                        "arm": row.get("arm"),
                        "attempts_per_row": row.get("measures", {}).get("attempts_per_row"),
                        "input_tokens_per_model_turn": row.get("measures", {}).get("cost", {}).get("input_tokens_per_model_turn"),
                        "output_tokens_per_model_turn": row.get("measures", {}).get("cost", {}).get("output_tokens_per_model_turn"),
                        "p95_turn_latency_seconds": row.get("measures", {}).get("cost", {}).get("p95_turn_latency_seconds"),
                        "validation_retries": row.get("regression_guards", {}).get("validation_retries"),
                    }
                    for row in rows
                ],
                "note": "No additional threshold is introduced by Q6.",
            },
            "recommendation_ref": "exploration_packet",
        },
    ]


def _factual_context(
    scored_rows: Sequence[Mapping[str, Any]], measures: Sequence[str]
) -> list[dict[str, Any]]:
    return [
        {
            "row_id": row.get("row_id"),
            "arm": row.get("arm"),
            "measures": {
                name: row.get("measures", {}).get(name) for name in measures
            },
        }
        for row in scored_rows
    ]


def _implementation_inputs(
    recommendations: Sequence[Mapping[str, Any]], d1: Mapping[str, Any], m1: Mapping[str, Any]
) -> dict[str, Any]:
    by_decision = {item["decision"]: item for item in recommendations}
    return {
        "S1": {
            "status": "contract input; owner/schema decision pending",
            "input": "Represent stable location identity, origin/facing, schematic anchors, exit side/state/destination knowledge, reachability, and perception boundaries. Preserve unknown/not-applicable explicitly; use metric distances only when authored.",
            "module_builder_gap_table": "module_builder_handoff.rows",
            "evidence": ["d1.sample_scope", "module_builder_handoff.rows"],
        },
        "S2": {
            "status": by_decision["exploration_packet"]["recommendation"],
            "candidate": by_decision["exploration_packet"].get("choice"),
            "format_comparison": by_decision["format"]["recommendation"],
            "format_candidate": by_decision["format"].get("choice"),
            "evidence": ["Q1", "Q2", "Q6"],
        },
        "SC1": {
            "status": by_decision["zone_combat"]["recommendation"],
            "zone_rule_evidence": by_decision["zone_combat"].get("zone_evidence"),
            "owner_enforcement_choice": "pending/not provided",
            "evidence": ["Q3"],
        },
        "S3": {
            "status": by_decision["published_module_backfill"]["recommendation"],
            "owner_precision": d1.get("owner_precision"),
            "automated_validator_count": d1.get("automated_validator_invented_exit_count"),
            "owner_invented_exit_count": d1.get("owner_invented_exit_count"),
            "evidence": ["Q4", "module_builder_handoff.rows"],
        },
        "S4": {
            "status": by_decision["shared_map"]["recommendation"],
            "ratings": m1.get("ratings"),
            "evidence": ["Q5"],
        },
    }


def _count_statuses(slots: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in ("PASS", "FAIL", "BLOCKED", "missing")}
    for slot in slots:
        status = slot.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def _parse_csv(payload: bytes, label: str) -> list[dict[str, str]]:
    try:
        text = payload.decode("ascii")
    except UnicodeError as exc:
        raise DecisionReportError("%s must be ASCII" % label) from exc
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise DecisionReportError("%s has no header" % label)
    try:
        reader = csv.DictReader(io.StringIO("\n".join(lines), newline=""))
        if not reader.fieldnames:
            raise DecisionReportError("%s has no header" % label)
        return [dict(row) for row in reader]
    except csv.Error as exc:
        raise DecisionReportError("%s is invalid" % label) from exc


def _parse_json_cell(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _rating_value(raw: str, label: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise DecisionReportError("%s must be a whole-number rating" % label) from exc
    if str(value) != raw.strip() or value < 1 or value > 5:
        raise DecisionReportError("%s must be from 1 through 5" % label)
    return value


def _valid_percent(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 100:
        return None
    return value


def _nonnegative_int(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _parse_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _safe_relative_filename(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in value
    )


def _tmp_root(value: str | Path, label: str) -> tuple[Path, Path]:
    relative = _tmp_relative(value, label)
    return relative, PROJECT_ROOT / relative


def _tmp_path(value: str | Path, label: str) -> tuple[Path, Path]:
    raw = Path(value)
    if raw.is_absolute():
        relative = _project_relative(raw, label)
    else:
        relative = raw
    if not relative.parts or relative.parts[0] != "tmp":
        raise DecisionReportError("%s must be below project tmp/" % label)
    if ".." in relative.parts or "\\" in str(value):
        raise DecisionReportError("%s is unsafe" % label)
    absolute = PROJECT_ROOT / relative
    _reject_symlink_components(absolute)
    return relative, absolute


def _tmp_relative(value: str | Path, label: str) -> Path:
    return _tmp_path(value, label)[0]


def _project_relative(path: Path, label: str) -> Path:
    if ".." in path.parts:
        raise DecisionReportError("%s is unsafe" % label)
    try:
        absolute = Path(os.path.abspath(os.fspath(path)))
        relative = absolute.relative_to(PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DecisionReportError("%s must remain inside the project" % label) from exc
    if ".." in relative.parts:
        raise DecisionReportError("%s is unsafe" % label)
    return relative


def _reject_symlink_components(path: Path) -> None:
    relative = _project_relative(path, "path")
    current = PROJECT_ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise DecisionReportError("symlinked paths are not accepted")


def _validate_token(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise DecisionReportError("%s must be a safe path token" % label)


def _ensure_json_value(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DecisionReportError("report contains non-finite or non-JSON data") from exc
