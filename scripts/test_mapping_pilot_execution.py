# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for the SP3 ledger and booking gate."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.execution import (
    BookingRequiredError,
    ExecutionLedgerError,
    activate_next_reserve,
    assert_row_start_allowed,
    authorize_provider_attempt,
    cap_snapshot,
    check_provider_request,
    create_or_resume_ledger,
    execute_booked_operation,
    get_reserve_assignment,
    mark_content_review_started,
    matrix_totals,
    record_booking,
    record_owner_review_and_resume,
    record_pre_content_classification,
    record_row_event,
    reconcile_attempt_count,
    release_booking,
    set_slot_status,
)
from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT, PROJECT_ROOT
from scripts.mapping_pilot.evidence import create_evidence_bundle
from scripts.mapping_pilot.row_runner import (
    DEFAULT_ROW_EVIDENCE_ROOT,
    RowRunnerHooks,
    _resolve_frozen_row,
    execute_row,
)
from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
    score_row,
)


class MappingPilotExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path("tmp") / ("mapping_pilot_execution_" + uuid.uuid4().hex)
        self.run_id = "pilot-run"
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        shutil.rmtree(PROJECT_ROOT / self.base, ignore_errors=True)
        for directory in getattr(self, "guard_directories", []):
            shutil.rmtree(PROJECT_ROOT / directory, ignore_errors=True)

    def _record_row_event(
        self,
        row_id: str,
        row_run_id: str,
        event: str,
        offset_seconds: float = 0,
        *,
        live_elapsed_seconds: float | None = None,
    ) -> dict[str, Any]:
        event_time = self.now + timedelta(seconds=offset_seconds)
        return record_row_event(
            self.run_id,
            row_id,
            row_run_id,
            event,
            event_timestamp=event_time.isoformat().replace("+00:00", "Z"),
            live_elapsed_seconds=live_elapsed_seconds,
            ledger_root=self.base,
            now=event_time,
        )

    def _start_live_row(
        self,
        row_id: str,
        row_run_id: str,
        *,
        seed_start_offset: float = 0,
        seed_complete_offset: float = 1,
        launch_offset: float = 2,
    ) -> None:
        self._record_row_event(row_id, row_run_id, "seed_started", seed_start_offset)
        self._record_row_event(row_id, row_run_id, "seed_completed", seed_complete_offset)
        self._record_row_event(row_id, row_run_id, "sandbox_launched", launch_offset)

    def _create_ledger(self) -> dict[str, Any]:
        return create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )

    def test_resolves_all_planned_frozen_rows_without_runtime_side_effects(self) -> None:
        counterbalance = json.loads(
            (DEFAULT_PREREG_ROOT / "counterbalance.json").read_text(encoding="ascii")
        )
        planned = [row for row in counterbalance["rows"] if row["row_type"] == "planned"]
        self.assertEqual(len(planned), 26)
        for frozen in planned:
            with self.subTest(row_id=frozen["row_id"]):
                row, script, fixture_id = _resolve_frozen_row(frozen["row_id"], None)
                expected_script = json.loads(
                    (DEFAULT_PREREG_ROOT / frozen["script"]).read_text(encoding="ascii")
                )
                self.assertEqual(row["script"], frozen["script"])
                self.assertEqual(row["party"], frozen["party"])
                self.assertEqual(row["fixed_seed"], frozen["fixed_seed"])
                self.assertEqual(script["script_id"], expected_script["script_id"])
                self.assertEqual(script["fixture_ids"], expected_script["fixture_ids"])
                self.assertEqual(fixture_id, expected_script["fixture_ids"][0])
        landscape, script, fixture_id = _resolve_frozen_row("E04", None)
        self.assertEqual(script["fixture_ids"], ["landscape_village", "transition_tower_approach"])
        self.assertEqual(fixture_id, "landscape_village")
        self.assertEqual(landscape["fixed_seed"], 5102)

    def test_frozen_row_rejects_unsupported_or_duplicate_fixture_ids(self) -> None:
        from scripts.mapping_pilot import row_runner

        for fixture_ids in (["unknown_fixture"], ["interior_tavern", "interior_tavern"]):
            with self.subTest(fixture_ids=fixture_ids):
                with mock.patch.object(row_runner, "verify_manifest", return_value={
                    "counterbalance.json": "hash", "scripts/test.json": "hash"
                }), mock.patch.object(
                    row_runner,
                    "_read_json",
                    side_effect=[
                        {"rows": [{"row_id": "E01", "row_type": "planned", "script": "scripts/test.json", "party": 1, "arm": "A", "fixed_seed": 1}]},
                        {"script_id": "test", "fixture_ids": fixture_ids, "turns": [], "model_bearing_turn_count": 0},
                    ],
                ):
                    with self.assertRaises(row_runner.RowExecutionError):
                        _resolve_frozen_row("E01", "unused")

    def _record_booking(
        self,
        *,
        confirmed: bool = True,
        booking_id: str = "overseer-booking-1",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        window_start = start or (self.now - timedelta(minutes=5))
        window_end = end or (self.now + timedelta(minutes=30))
        return record_booking(
            self.run_id,
            booking_id=booking_id,
            holder="Overseer: primary",
            window_start=window_start.isoformat().replace("+00:00", "Z"),
            window_end=window_end.isoformat().replace("+00:00", "Z"),
            network_non_overlap_confirmed=confirmed,
            ledger_root=self.base,
            now=self.now,
        )

    def _record_classified_failure(
        self,
        row_id: str,
        row_run_id: str,
        classification: str,
        evidence: list[dict[str, str]],
        *,
        status: str = "BLOCKED",
        offset_seconds: float = 0,
    ) -> dict[str, Any]:
        self._record_row_event(row_id, row_run_id, "seed_started", offset_seconds)
        self._record_row_event(
            row_id, row_run_id, "seed_completed", offset_seconds + 1
        )
        classification_at = self.now + timedelta(seconds=offset_seconds + 2)
        record_pre_content_classification(
            self.run_id,
            row_id,
            row_run_id,
            classification,
            reason="provider-free test classification from process metadata",
            evidence=evidence,
            ledger_root=self.base,
            now=classification_at,
        )
        marker_at = self.now + timedelta(seconds=offset_seconds + 3)
        mark_content_review_started(
            self.run_id,
            row_id,
            row_run_id,
            ledger_root=self.base,
            now=marker_at,
        )
        return set_slot_status(
            self.run_id,
            row_id,
            status,
            reason="provider-free classified failure",
            ledger_root=self.base,
            now=self.now + timedelta(seconds=offset_seconds + 4),
        )

    def test_ledger_uses_all_frozen_slots_in_manifest_order(self) -> None:
        ledger = self._create_ledger()
        counterbalance = json.loads(
            (DEFAULT_PREREG_ROOT / "counterbalance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(ledger["slots"]), 30)
        self.assertEqual(
            [slot["row_id"] for slot in ledger["slots"]],
            [row["row_id"] for row in counterbalance["rows"]],
        )
        self.assertEqual(
            [slot["run_order"] for slot in ledger["slots"]],
            [row["run_order"] for row in counterbalance["rows"]],
        )
        for slot, frozen in zip(ledger["slots"], counterbalance["rows"]):
            for key, value in frozen.items():
                self.assertEqual(slot[key], value)
            self.assertEqual(slot["status"], "missing")
        self.assertEqual(ledger["slots"][-4]["row_id"], "R01")

    def test_resume_preserves_terminal_rows_and_refuses_overwrite(self) -> None:
        self._create_ledger()
        completed = set_slot_status(
            self.run_id,
            "E01",
            "PASS",
            reason="row completed with required evidence",
            evidence_path="tmp/router-rollout/mapping-pilot/sp3/row-e01",
            ledger_root=self.base,
            now=self.now,
        )
        ledger_path = PROJECT_ROOT / self.base / self.run_id / "matrix_ledger.json"
        before_resume = ledger_path.read_bytes()
        resumed = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now + timedelta(minutes=1)
        )
        self.assertEqual(ledger_path.read_bytes(), before_resume)
        self.assertEqual(resumed["slots"][0], completed["slots"][0])
        self.assertEqual(resumed["slots"][0]["status"], "PASS")
        with self.assertRaisesRegex(ExecutionLedgerError, "immutable"):
            set_slot_status(
                self.run_id,
                "E01",
                "FAIL",
                reason="attempted overwrite",
                ledger_root=self.base,
                now=self.now,
            )
        self.assertEqual(ledger_path.read_bytes(), before_resume)

    def test_missing_booking_blocks_seed_and_launch_before_callbacks(self) -> None:
        self._create_ledger()
        effects: list[str] = []

        def fake_effect(name: str):
            def run(_booking: Any) -> str:
                effects.append(name)
                return name

            return run

        for operation in ("seed", "launch"):
            with self.subTest(operation=operation):
                with self.assertRaises(BookingRequiredError):
                    execute_booked_operation(
                        self.run_id,
                        operation,
                        fake_effect(operation),
                        ledger_root=self.base,
                        now=self.now,
                    )
        self.assertEqual(effects, [])

    def test_unconfirmed_or_expired_booking_blocks_side_effect(self) -> None:
        self._create_ledger()
        self._record_booking(confirmed=False)
        effects: list[str] = []
        with self.assertRaisesRegex(BookingRequiredError, "Network"):
            execute_booked_operation(
                self.run_id,
                "seed",
                lambda _booking: effects.append("seed"),
                ledger_root=self.base,
                now=self.now,
            )
        self.assertEqual(effects, [])

        self._create_ledger()  # Resume is read-only and does not repair a bad booking.
        later = self.now + timedelta(hours=1)
        with self.assertRaises(BookingRequiredError):
            execute_booked_operation(
                self.run_id,
                "launch",
                lambda _booking: effects.append("launch"),
                ledger_root=self.base,
                now=later,
            )
        self.assertEqual(effects, [])

    def test_valid_booking_allows_fake_seed_and_launch_then_release_blocks(self) -> None:
        self._create_ledger()
        recorded = self._record_booking()
        booking = recorded["bookings"][0]
        self.assertEqual(booking["booking_id"], "overseer-booking-1")
        self.assertEqual(booking["holder"], "Overseer: primary")
        self.assertTrue(booking["network_non_overlap_confirmed"])
        effects: list[str] = []

        for operation in ("seed", "launch"):
            result = execute_booked_operation(
                self.run_id,
                operation,
                lambda active, name=operation: effects.append(
                    "%s:%s" % (name, active["booking_id"])
                ),
                ledger_root=self.base,
                now=self.now,
            )
            self.assertIsNone(result)
        self.assertEqual(effects, [
            "seed:overseer-booking-1",
            "launch:overseer-booking-1",
        ])

        released = release_booking(
            self.run_id,
            "overseer-booking-1",
            release_timestamp=self.now.isoformat().replace("+00:00", "Z"),
            ledger_root=self.base,
            now=self.now,
        )
        self.assertEqual(
            released["bookings"][0]["release_timestamp"],
            self.now.isoformat().replace("+00:00", "Z"),
        )
        with self.assertRaises(BookingRequiredError):
            execute_booked_operation(
                self.run_id,
                "launch",
                lambda _booking: effects.append("after-release"),
                ledger_root=self.base,
                now=self.now,
            )
        self.assertEqual(len(effects), 2)

    def test_booking_windows_cannot_overlap_and_must_be_current(self) -> None:
        self._create_ledger()
        self._record_booking()
        release_booking(
            self.run_id,
            "overseer-booking-1",
            release_timestamp=self.now.isoformat().replace("+00:00", "Z"),
            ledger_root=self.base,
            now=self.now,
        )
        with self.assertRaisesRegex(ExecutionLedgerError, "overlap"):
            self._record_booking(
                booking_id="overseer-booking-2",
                start=self.now + timedelta(minutes=20),
                end=self.now + timedelta(hours=1),
            )
        with self.assertRaises(BookingRequiredError):
            execute_booked_operation(
                self.run_id,
                "seed",
                lambda _booking: self.fail("seed callback must not run"),
                ledger_root=self.base,
                now=self.now + timedelta(minutes=30),
            )

    def test_unsafe_ledger_roots_and_unknown_slots_are_rejected(self) -> None:
        for unsafe_root in ("tmp/../outside", "tmp/./unsafe", "tmp\\unsafe"):
            with self.subTest(unsafe_root=unsafe_root):
                with self.assertRaises(ExecutionLedgerError):
                    create_or_resume_ledger("unsafe", ledger_root=unsafe_root, now=self.now)
        self._create_ledger()
        with self.assertRaisesRegex(ExecutionLedgerError, "not a frozen slot"):
            set_slot_status(
                self.run_id,
                "E99",
                "FAIL",
                reason="not in frozen matrix",
                ledger_root=self.base,
                now=self.now,
            )

    def test_content_and_unresolved_failures_are_not_reserve_candidates(self) -> None:
        self._create_ledger()
        self._record_classified_failure(
            "E01",
            "content-failure-run",
            "CONTENT/RESULT",
            [
                {
                    "kind": "provider_status",
                    "code": "usable_response_returned",
                    "source": "tmp/pre-content/provider-receipts.json",
                }
            ],
            status="FAIL",
        )
        self._record_classified_failure(
            "E02",
            "unresolved-failure-run",
            "UNRESOLVED",
            [
                {
                    "kind": "timing",
                    "code": "row_timeout",
                    "source": "tmp/pre-content/process-timing.json",
                }
            ],
            status="BLOCKED",
            offset_seconds=10,
        )

        with self.assertRaisesRegex(ExecutionLedgerError, "no pre-content infrastructure"):
            activate_next_reserve(self.run_id, ledger_root=self.base, now=self.now)
        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        self.assertIsNone(ledger["slots"][-4]["replacement"])
        self.assertEqual(ledger["slots"][0]["status"], "FAIL")
        self.assertEqual(ledger["slots"][1]["status"], "BLOCKED")

    def test_infrastructure_classification_requires_qualifying_evidence_before_review(self) -> None:
        self._create_ledger()
        self._record_row_event("E01", "late-classification-run", "seed_started")
        self._record_row_event(
            "E01", "late-classification-run", "seed_completed", 1
        )
        with self.assertRaisesRegex(
            ExecutionLedgerError, "pre-content classification is required"
        ):
            mark_content_review_started(
                self.run_id,
                "E01",
                "late-classification-run",
                ledger_root=self.base,
                now=self.now + timedelta(seconds=2),
            )
        record_pre_content_classification(
            self.run_id,
            "E01",
            "late-classification-run",
            "INFRASTRUCTURE",
            reason="transport failed before content review",
            evidence=[
                {
                    "kind": "transport",
                    "code": "connection_reset",
                    "source": "tmp/pre-content/server.log",
                }
            ],
            ledger_root=self.base,
            now=self.now + timedelta(seconds=2),
        )
        mark_content_review_started(
            self.run_id,
            "E01",
            "late-classification-run",
            ledger_root=self.base,
            now=self.now + timedelta(seconds=3),
        )
        with self.assertRaisesRegex(ExecutionLedgerError, "immutable"):
            record_pre_content_classification(
                self.run_id,
                "E01",
                "late-classification-run",
                "CONTENT/RESULT",
                reason="late classification is refused",
                evidence=[
                    {
                        "kind": "provider_status",
                        "code": "usable_response_returned",
                        "source": "tmp/pre-content/provider-receipts.json",
                    }
                ],
                ledger_root=self.base,
                now=self.now + timedelta(seconds=4),
            )

        self._record_row_event("E02", "cap-only-run", "seed_started", 10)
        self._record_row_event("E02", "cap-only-run", "seed_completed", 11)
        with self.assertRaisesRegex(ExecutionLedgerError, "qualifying evidence"):
            record_pre_content_classification(
                self.run_id,
                "E02",
                "cap-only-run",
                "INFRASTRUCTURE",
                reason="the cap alone does not establish infrastructure failure",
                evidence=[
                    {
                        "kind": "timing",
                        "code": "row_live_cap",
                        "source": "tmp/pre-content/cap-counts.json",
                    }
                ],
                ledger_root=self.base,
                now=self.now + timedelta(seconds=12),
            )

    def test_three_infrastructure_failures_pause_until_explicit_owner_review(self) -> None:
        self._create_ledger()
        evidence = [
            {
                "kind": "transport",
                "code": "connection_reset",
                "source": "tmp/pre-content/server.log",
            }
        ]
        for index, row_id in enumerate(("E01", "E02", "E03")):
            self._record_classified_failure(
                row_id,
                "infra-run-%02d" % index,
                "INFRASTRUCTURE",
                evidence,
                status="BLOCKED",
                offset_seconds=index * 10,
            )

        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        self.assertTrue(ledger["control"]["paused"])
        self.assertEqual(ledger["control"]["pauses"][-1]["triggering_row_ids"], ["E01", "E02", "E03"])
        with self.assertRaisesRegex(ExecutionLedgerError, "paused pending owner review"):
            assert_row_start_allowed(
                self.run_id, "E04", ledger_root=self.base
            )
        with self.assertRaisesRegex(ExecutionLedgerError, "paused pending owner review"):
            self._record_row_event("E04", "paused-row-run", "seed_started", 35)
        with self.assertRaisesRegex(ExecutionLedgerError, "paused pending owner review"):
            activate_next_reserve(self.run_id, ledger_root=self.base, now=self.now)
        with self.assertRaisesRegex(ExecutionLedgerError, "reviewer_label"):
            record_owner_review_and_resume(
                self.run_id,
                reviewer_label=" ",
                note="Reviewed and authorized to resume",
                ledger_root=self.base,
                now=self.now + timedelta(seconds=40),
            )
        self.assertTrue(
            create_or_resume_ledger(
                self.run_id, ledger_root=self.base, now=self.now
            )["control"]["paused"]
        )

        resumed = record_owner_review_and_resume(
            self.run_id,
            reviewer_label="Overseer",
            note="Reviewed the three transport failures; resume approved",
            ledger_root=self.base,
            now=self.now + timedelta(seconds=41),
        )
        self.assertFalse(resumed["control"]["paused"])
        review = resumed["control"]["pauses"][-1]["owner_review"]
        self.assertEqual(review["reviewer_label"], "Overseer")
        self.assertEqual(review["note"], "Reviewed the three transport failures; resume approved")
        self.assertTrue(review["resume_authorized"])
        self.assertIsNone(assert_row_start_allowed(self.run_id, "E04", ledger_root=self.base))
        self._record_row_event("E04", "resumed-row-run", "seed_started", 42)
        ledger_after_start = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        resumed_slot = next(
            item for item in ledger_after_start["slots"] if item["row_id"] == "E04"
        )
        self.assertEqual(resumed_slot["execution"]["row_run_id"], "resumed-row-run")

    def test_unresolved_does_not_increment_or_reset_infrastructure_streak(self) -> None:
        self._create_ledger()
        infrastructure_evidence = [
            {
                "kind": "transport",
                "code": "connection_reset",
                "source": "tmp/pre-content/server.log",
            }
        ]
        result_evidence = [
            {
                "kind": "provider_status",
                "code": "usable_response_returned",
                "source": "tmp/pre-content/provider-receipts.json",
            }
        ]
        self._record_classified_failure(
            "E01", "streak-infra-1", "INFRASTRUCTURE", infrastructure_evidence
        )
        after_first_infrastructure = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )["control"]["infrastructure_failure_streak"]
        self._record_classified_failure(
            "E02", "streak-unresolved", "UNRESOLVED", [], offset_seconds=10
        )
        after_unresolved = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )["control"]["infrastructure_failure_streak"]
        self.assertEqual(after_unresolved, after_first_infrastructure)

        self._record_classified_failure(
            "E03",
            "streak-content-result",
            "CONTENT/RESULT",
            result_evidence,
            status="FAIL",
            offset_seconds=20,
        )
        self.assertEqual(
            create_or_resume_ledger(
                self.run_id, ledger_root=self.base, now=self.now
            )["control"]["infrastructure_failure_streak"],
            [],
        )

        for index, row_id in enumerate(("E04", "E05"), start=1):
            self._record_classified_failure(
                row_id,
                "streak-infra-after-content-%d" % index,
                "INFRASTRUCTURE",
                infrastructure_evidence,
                offset_seconds=30 + index * 10,
            )
        before_third_after_content = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        self.assertFalse(before_third_after_content["control"]["paused"])
        self.assertEqual(
            len(before_third_after_content["control"]["infrastructure_failure_streak"]),
            2,
        )
        self._record_classified_failure(
            "E06",
            "streak-infra-after-content-3",
            "INFRASTRUCTURE",
            infrastructure_evidence,
            offset_seconds=60,
        )
        paused = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )["control"]
        self.assertTrue(paused["paused"])
        self.assertEqual(
            paused["pauses"][-1]["triggering_row_ids"], ["E04", "E05", "E06"]
        )

    def test_reserve_slots_are_ordered_capped_and_keep_distinct_run_identity(self) -> None:
        self._create_ledger()
        infra_evidence = [
            {
                "kind": "process",
                "code": "sandbox_boot_failed",
                "source": "tmp/pre-content/server.log",
            }
        ]
        result_evidence = [
            {
                "kind": "provider_status",
                "code": "usable_response_returned",
                "source": "tmp/pre-content/provider-receipts.json",
            }
        ]
        expected_sources = ("E01", "E03", "E05", "E07")
        for index, row_id in enumerate(("E01", "E02", "E03", "E04", "E05", "E06", "E07")):
            self._record_classified_failure(
                row_id,
                "eligible-run-%02d" % index,
                "INFRASTRUCTURE" if row_id in expected_sources else "CONTENT/RESULT",
                infra_evidence if row_id in expected_sources else result_evidence,
                status="BLOCKED" if row_id in expected_sources else "FAIL",
                offset_seconds=index * 10,
            )

        for reserve_index, expected_source in enumerate(expected_sources, start=1):
            assignment = activate_next_reserve(
                self.run_id,
                ledger_root=self.base,
                now=self.now + timedelta(seconds=100 + reserve_index),
            )
            reserve_id = "R%02d" % reserve_index
            self.assertEqual(assignment["source_row_id"], expected_source)
            self.assertEqual(assignment["reserve_seed"], 5900 + reserve_index)
            self.assertNotEqual(
                assignment["replacement_run_id"],
                assignment["source_row_run_id"],
            )
            self.assertEqual(
                get_reserve_assignment(
                    self.run_id, reserve_id, ledger_root=self.base
                ),
                assignment,
            )
            reserve_slot = next(
                item
                for item in create_or_resume_ledger(
                    self.run_id, ledger_root=self.base, now=self.now
                )["slots"]
                if item["row_id"] == reserve_id
            )
            self.assertEqual(reserve_slot["row_id"], reserve_id)
            self.assertEqual(reserve_slot["fixed_seed"], 5900 + reserve_index)
            self.assertEqual(reserve_slot["run_order"], 26 + reserve_index)
            self.assertEqual(reserve_slot["arm"], "inherit")

            self._record_row_event(
                reserve_id,
                assignment["replacement_run_id"],
                "seed_started",
                200 + reserve_index * 10,
            )
            self._record_row_event(
                reserve_id,
                assignment["replacement_run_id"],
                "seed_completed",
                201 + reserve_index * 10,
            )
            record_pre_content_classification(
                self.run_id,
                reserve_id,
                assignment["replacement_run_id"],
                "CONTENT/RESULT",
                reason="replacement test ends as a retained result",
                evidence=result_evidence,
                ledger_root=self.base,
                now=self.now + timedelta(seconds=202 + reserve_index * 10),
            )
            mark_content_review_started(
                self.run_id,
                reserve_id,
                assignment["replacement_run_id"],
                ledger_root=self.base,
                now=self.now + timedelta(seconds=203 + reserve_index * 10),
            )
            set_slot_status(
                self.run_id,
                reserve_id,
                "FAIL",
                reason="replacement result retained",
                ledger_root=self.base,
                now=self.now + timedelta(seconds=204 + reserve_index * 10),
            )

        with self.assertRaisesRegex(ExecutionLedgerError, "all four frozen reserve slots"):
            activate_next_reserve(self.run_id, ledger_root=self.base, now=self.now)

    def test_attempt_guard_allows_last_in_cap_request_then_refuses_next(self) -> None:
        self._create_ledger()
        row_run_id = "row-attempt-boundary"
        self._start_live_row("E01", row_run_id)
        reconcile_attempt_count(
            self.run_id,
            "E01",
            row_run_id,
            ROW_ATTEMPT_CAP - 1,
            ledger_root=self.base,
            now=self.now,
        )

        last_allowed = authorize_provider_attempt(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=100.0,
            monotonic_now=100.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertTrue(last_allowed["allowed"])
        self.assertEqual(last_allowed["issued_attempt_count"], ROW_ATTEMPT_CAP)

        refused = authorize_provider_attempt(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=100.0,
            monotonic_now=100.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(refused["allowed"])
        self.assertIn("row_attempt_cap", refused["reasons"])
        self.assertEqual(refused["actual_counts"]["row_attempts"], ROW_ATTEMPT_CAP)
        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        execution = next(slot for slot in ledger["slots"] if slot["row_id"] == "E01")[
            "execution"
        ]
        self.assertEqual(execution["attempt_count"], ROW_ATTEMPT_CAP)
        self.assertIn("row_attempt_cap", execution["cap_stop"]["reasons"])

    def test_matrix_attempt_guard_refuses_at_exact_total_boundary(self) -> None:
        self._create_ledger()
        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        counted_slots = ledger["slots"][:23]
        for index, slot in enumerate(counted_slots):
            row_run_id = "counted-row-%02d" % index
            record_row_event(
                self.run_id,
                slot["row_id"],
                row_run_id,
                "seed_started",
                event_timestamp=self.now.isoformat().replace("+00:00", "Z"),
                ledger_root=self.base,
                now=self.now,
            )
            reconcile_attempt_count(
                self.run_id,
                slot["row_id"],
                row_run_id,
                ROW_ATTEMPT_CAP if index < 22 else 29,
                ledger_root=self.base,
                now=self.now,
            )
        row_id = ledger["slots"][23]["row_id"]
        row_run_id = "current-matrix-cap-row"
        self._start_live_row(row_id, row_run_id)
        self.assertEqual(
            cap_snapshot(
                self.run_id, row_id, ledger_root=self.base
            )["matrix_attempts"],
            MATRIX_ATTEMPT_CAP - 1,
        )

        last_allowed = authorize_provider_attempt(
            self.run_id,
            row_id,
            row_run_id,
            live_started_monotonic=40.0,
            monotonic_now=40.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertTrue(last_allowed["allowed"])
        refused = authorize_provider_attempt(
            self.run_id,
            row_id,
            row_run_id,
            live_started_monotonic=40.0,
            monotonic_now=40.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(refused["allowed"])
        self.assertIn("matrix_attempt_cap", refused["reasons"])
        self.assertEqual(refused["actual_counts"]["matrix_attempts"], MATRIX_ATTEMPT_CAP)

    def test_unknown_attempt_counters_refuse_provider_request(self) -> None:
        self._create_ledger()
        row_run_id = "row-unknown-count"
        self._start_live_row("E01", row_run_id)
        reconcile_attempt_count(
            self.run_id,
            "E01",
            row_run_id,
            None,
            ledger_root=self.base,
            now=self.now,
        )
        decision = check_provider_request(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=10.0,
            monotonic_now=10.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(decision["allowed"])
        self.assertIn("attempt_count_unknown", decision["reasons"])
        self.assertEqual(decision["actual_counts"]["row_attempts"], "unknown")
        self.assertEqual(decision["actual_counts"]["matrix_attempts"], "unknown")

    def test_row_time_guard_refuses_exact_boundary_and_unknown_time(self) -> None:
        self._create_ledger()
        row_run_id = "row-time-boundary"
        self._start_live_row("E01", row_run_id)
        just_below = check_provider_request(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=100.0,
            monotonic_now=100.0 + ROW_WALL_TIME_CAP_SECONDS - 0.001,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertTrue(just_below["allowed"])
        at_cap = check_provider_request(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=100.0,
            monotonic_now=100.0 + ROW_WALL_TIME_CAP_SECONDS,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(at_cap["allowed"])
        self.assertIn("row_wall_time_cap", at_cap["reasons"])

        unknown_time = check_provider_request(
            self.run_id,
            "E01",
            row_run_id,
            live_started_monotonic=None,
            monotonic_now=100.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(unknown_time["allowed"])
        self.assertIn("wall_time_unknown", unknown_time["reasons"])

    def test_unknown_completed_live_interval_fails_closed(self) -> None:
        self._create_ledger()
        row_run_id = "row-unknown-duration"
        self._start_live_row("E01", row_run_id)
        self._record_row_event(
            "E01", row_run_id, "teardown_completed", 3
        )

        totals = matrix_totals(self.run_id, ledger_root=self.base)
        snapshot = cap_snapshot(self.run_id, "E01", ledger_root=self.base)
        self.assertEqual(totals["matrix_elapsed_seconds"], "unknown")
        self.assertEqual(snapshot["row_elapsed_seconds"], "unknown")
        self.assertEqual(snapshot["matrix_elapsed_seconds"], "unknown")

    def test_matrix_time_guard_sums_row_intervals_at_exact_boundary(self) -> None:
        self._create_ledger()
        first_run_id = "row-long-complete"
        self._start_live_row("E01", first_run_id)
        self._record_row_event(
            "E01",
            first_run_id,
            "teardown_completed",
            3,
            live_elapsed_seconds=MATRIX_WALL_TIME_CAP_SECONDS - 1,
        )
        second_run_id = "row-final-second"
        self._start_live_row(
            "E02",
            second_run_id,
            seed_start_offset=86400,
            seed_complete_offset=86401,
            launch_offset=86402,
        )

        just_below = check_provider_request(
            self.run_id,
            "E02",
            second_run_id,
            live_started_monotonic=50.0,
            monotonic_now=50.999,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertTrue(just_below["allowed"])
        at_cap = check_provider_request(
            self.run_id,
            "E02",
            second_run_id,
            live_started_monotonic=50.0,
            monotonic_now=51.0,
            ledger_root=self.base,
            now=self.now,
        )
        self.assertFalse(at_cap["allowed"])
        self.assertIn("matrix_wall_time_cap", at_cap["reasons"])
        self.assertEqual(
            at_cap["actual_counts"]["matrix_elapsed_seconds"],
            MATRIX_WALL_TIME_CAP_SECONDS,
        )

    def test_matrix_totals_exclude_seed_pauses_and_finalization_time(self) -> None:
        self._create_ledger()
        self._record_booking(
            start=self.now - timedelta(minutes=1),
            end=self.now + timedelta(days=4),
        )
        execute_booked_operation(
            self.run_id,
            "seed",
            lambda _booking: None,
            ledger_root=self.base,
            now=self.now,
        )
        first_run_id = "row-interval-13"
        self._record_row_event("E01", first_run_id, "seed_started", 0)
        self._record_row_event("E01", first_run_id, "seed_completed", 600)
        self._record_row_event("E01", first_run_id, "sandbox_launched", 1200)
        self._record_row_event(
            "E01",
            first_run_id,
            "teardown_completed",
            1213,
            live_elapsed_seconds=13,
        )
        self._record_row_event("E01", first_run_id, "evidence_finalized", 86400)
        self._record_row_event("E01", first_run_id, "scored", 86401)

        second_run_id = "row-interval-17"
        self._record_row_event("E02", second_run_id, "seed_started", 172800)
        self._record_row_event("E02", second_run_id, "seed_completed", 172801)
        self._record_row_event("E02", second_run_id, "sandbox_launched", 172802)
        self._record_row_event(
            "E02",
            second_run_id,
            "teardown_completed",
            172819,
            live_elapsed_seconds=17,
        )
        self._record_row_event("E02", second_run_id, "evidence_finalized", 259200)
        self._record_row_event("E02", second_run_id, "scored", 259201)
        release_at = self.now + timedelta(days=3)
        released = release_booking(
            self.run_id,
            "overseer-booking-1",
            release_timestamp=release_at.isoformat().replace("+00:00", "Z"),
            ledger_root=self.base,
            now=release_at,
        )

        totals = matrix_totals(self.run_id, ledger_root=self.base)
        self.assertEqual(totals["matrix_elapsed_seconds"], 30.0)
        self.assertEqual(
            released["bookings"][0]["booked_window_elapsed_seconds"],
            3 * 24 * 60 * 60,
        )
        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=release_at
        )
        first_execution = ledger["slots"][0]["execution"]
        self.assertEqual(first_execution["timestamps"]["seed_started_at"], self.now.isoformat().replace("+00:00", "Z"))
        self.assertEqual(first_execution["timestamps"]["evidence_finalized_at"], (self.now + timedelta(seconds=86400)).isoformat().replace("+00:00", "Z"))
        self.assertEqual(first_execution["timestamps"]["scored_at"], (self.now + timedelta(seconds=86401)).isoformat().replace("+00:00", "Z"))

    def test_default_server_launch_injects_guard_bootstrap_without_starting_server(self) -> None:
        from scripts.mapping_pilot import row_runner

        relative_directory = self.base / self.run_id / "runtime" / "row-guard-test"
        (PROJECT_ROOT / relative_directory).mkdir(parents=True)
        context = {
            "run_id": self.run_id,
            "row_id": "E01",
            "row_run_id": "row-guard-test",
            "lifecycle_id": "row-guard-test-s1",
            "ledger_root": self.base.as_posix(),
            "live_started_monotonic": 42.0,
        }
        environment = row_runner._request_guard_environment(
            {
                "_request_guard_context": context,
                "_request_guard_directory": relative_directory.as_posix(),
            }
        )
        bootstrap = (
            PROJECT_ROOT / relative_directory / "sitecustomize.py"
        ).read_text(encoding="ascii")
        self.assertEqual(
            environment["NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT"],
            json.dumps(context, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(
            environment["PYTHONPATH"].split(os.pathsep)[0],
            str((PROJECT_ROOT / relative_directory).resolve()),
        )
        self.assertIn("authorize_provider_attempt", bootstrap)
        self.assertIn("check_provider_request", bootstrap)
        self.assertIn("_load_parent_execution", bootstrap)

    def test_request_guard_bootstrap_counts_before_fake_transport(self) -> None:
        from scripts.mapping_pilot import row_runner

        self._create_ledger()
        row_run_id = "row-bootstrap-boundary"
        self._start_live_row("E01", row_run_id)
        reconcile_attempt_count(
            self.run_id,
            "E01",
            row_run_id,
            ROW_ATTEMPT_CAP - 1,
            ledger_root=self.base,
            now=self.now,
        )
        guard_directory = self.base / self.run_id / "runtime" / row_run_id
        (PROJECT_ROOT / guard_directory).mkdir(parents=True)
        context = {
            "run_id": self.run_id,
            "row_id": "E01",
            "row_run_id": row_run_id,
            "lifecycle_id": "row-bootstrap-boundary-s1",
            "ledger_root": self.base.as_posix(),
            "live_started_monotonic": 42.0,
        }
        environment = row_runner._request_guard_environment(
            {
                "_request_guard_context": context,
                "_request_guard_directory": guard_directory.as_posix(),
            }
        )
        environment_name = "NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT"
        old_environment = os.environ.get(environment_name)
        os.environ[environment_name] = environment[environment_name]
        namespace: dict[str, Any] = {
            "__file__": str(
                PROJECT_ROOT / guard_directory / "sitecustomize.py"
            )
        }

        class FakeTransport:
            def __init__(self) -> None:
                self.calls = 0

            def create(self, *_args: Any, **_kwargs: Any) -> str:
                self.calls += 1
                return "fake response"

        class FakeClient:
            def __init__(self) -> None:
                self.chat = SimpleNamespace(completions=FakeTransport())

        try:
            with mock.patch.object(row_runner.time, "monotonic", return_value=42.0):
                exec(row_runner._REQUEST_GUARD_BOOTSTRAP, namespace)
                client = FakeClient()
                guarded_client = namespace["_GuardedClient"](client)
                guarded_create = guarded_client.chat.completions.create
                self.assertEqual(guarded_create("request"), "fake response")
                self.assertEqual(client.chat.completions.calls, 1)
                with self.assertRaises(namespace["_GuardStop"]):
                    guarded_create("over-cap request")
                self.assertEqual(client.chat.completions.calls, 1)
        finally:
            finder = namespace.get("_RouterFinder")
            if finder is not None and finder in sys.meta_path:
                sys.meta_path.remove(finder)
            if old_environment is None:
                os.environ.pop(environment_name, None)
            else:
                os.environ[environment_name] = old_environment

        ledger = create_or_resume_ledger(
            self.run_id, ledger_root=self.base, now=self.now
        )
        execution = next(
            slot for slot in ledger["slots"] if slot["row_id"] == "E01"
        )["execution"]
        self.assertEqual(execution["attempt_count"], ROW_ATTEMPT_CAP)
        self.assertIn("row_attempt_cap", execution["cap_stop"]["reasons"])

    def test_child_request_guard_uses_parent_ledger_from_copied_sandbox_cwd(self) -> None:
        from scripts.mapping_pilot import row_runner

        self._create_ledger()
        capped_run = "child-cap-row"
        self._start_live_row("E01", capped_run)
        reconcile_attempt_count(
            self.run_id, "E01", capped_run, ROW_ATTEMPT_CAP - 1,
            ledger_root=self.base, now=self.now,
        )
        sandbox = PROJECT_ROOT / self.base / "copied-sandbox-cwd"
        receipt_runtime = PROJECT_ROOT / self.base / "child-receipt-runtime"
        (receipt_runtime / "mapping_pilot").mkdir(parents=True)
        copied_mapping = sandbox / "scripts" / "mapping_pilot"
        copied_mapping.mkdir(parents=True)
        for name in ("execution.py", "manifest.py", "scoring.py"):
            shutil.copyfile(ROOT / "scripts" / "mapping_pilot" / name, copied_mapping / name)
        fake_utils = sandbox / "utils"
        fake_utils.mkdir()
        (fake_utils / "__init__.py").write_text("", encoding="ascii")
        (fake_utils / "llm_router.py").write_text(
            """\
class LLMRouter:
    def _request_kwargs(self, *args, **kwargs):
        return {"source": "copied-sandbox"}

    @staticmethod
    def _disable_sdk_retries(client):
        return client

class FakeLLM:
    def call(self, *args, **kwargs):
        return "fake summary"

llm = FakeLLM()
""",
            encoding="ascii",
        )

        child_code = r'''\
import importlib
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import sitecustomize as guard

def deny_network(*args, **kwargs):
    raise AssertionError("provider-free network tripwire")

socket.socket.connect = deny_network
socket.create_connection = deny_network
receipt_runtime = Path(sys.argv[1]).resolve(strict=True)
guard._SERVER._safe_runtime_root = lambda _value: receipt_runtime
sandbox = Path.cwd().resolve(strict=True)
sys.path.insert(0, str(sandbox))
import scripts.mapping_pilot as mapping_pilot
mapping_pilot.__path__ = [str(sandbox / "scripts" / "mapping_pilot")]
for name in ("execution", "manifest", "scoring"):
    sys.modules.pop("scripts.mapping_pilot." + name, None)
copied = importlib.import_module("scripts.mapping_pilot.execution")
copied_root = Path(copied.PROJECT_ROOT).resolve(strict=True)
guard_root = Path(guard._EXECUTION.PROJECT_ROOT).resolve(strict=True)
if copied_root != sandbox or copied_root == guard_root:
    raise AssertionError("copied sandbox import provenance was not exercised")
import utils
utils.__path__.append(str(guard_root / "utils"))
from utils.llm_router import LLMRouter

class FakeTransport:
    def __init__(self):
        self.calls = 0
    def create(self, *args, **kwargs):
        self.calls += 1
        return "fake response"

transport = FakeTransport()
client = SimpleNamespace(chat=SimpleNamespace(completions=transport))
router = LLMRouter()
guarded_client = router._disable_sdk_retries(client)
mode = sys.argv[2]
denied = False
try:
    router._request_kwargs()
    guarded_client.chat.completions.create("fake request")
except guard._GuardStop:
    denied = True
if mode == "cap" and not denied:
    try:
        router._request_kwargs()
        guarded_client.chat.completions.create("fake retry")
    except guard._GuardStop:
        denied = True
print(json.dumps({
    "denied": denied,
    "transport_calls": transport.calls,
    "copied_root": str(copied_root),
    "guard_root": str(guard_root),
    "guard_execution": str(Path(guard._EXECUTION.__file__).resolve()),
    "caps": guard._EXECUTION.cap_snapshot(
        guard._CONTEXT["run_id"], guard._CONTEXT["row_id"],
        ledger_root=guard._CONTEXT["ledger_root"],
    ),
}))
'''

        def run_child(
            row_id: str,
            row_run_id: str,
            mode: str,
            *,
            run_id: str | None = None,
            ledger_root: Path | None = None,
        ) -> dict[str, Any]:
            selected_run_id = run_id or self.run_id
            selected_ledger_root = ledger_root or self.base
            context = {
                "run_id": selected_run_id,
                "row_id": row_id,
                "row_run_id": row_run_id,
                "lifecycle_id": "lifecycle-" + row_run_id,
                "ledger_root": selected_ledger_root.as_posix(),
                "live_started_monotonic": time.monotonic(),
            }
            guard_directory = (
                selected_ledger_root / selected_run_id / "runtime" / row_run_id
            )
            (PROJECT_ROOT / guard_directory).mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment.update(row_runner._request_guard_environment({
                "_request_guard_context": context,
                "_request_guard_directory": guard_directory.as_posix(),
            }))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(receipt_runtime),
                    mode,
                ],
                cwd=str(sandbox), env=environment,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            return json.loads(result.stdout)

        capped = run_child("E01", capped_run, "cap")
        self.assertTrue(capped["denied"])
        self.assertEqual(capped["transport_calls"], 1)
        self.assertEqual(capped["copied_root"], str(sandbox))
        self.assertNotEqual(capped["guard_root"], capped["copied_root"])
        self.assertEqual(
            Path(capped["guard_execution"]),
            ROOT / "scripts" / "mapping_pilot" / "execution.py",
        )
        capped_ledger = create_or_resume_ledger(self.run_id, ledger_root=self.base)
        capped_execution = next(slot for slot in capped_ledger["slots"] if slot["row_id"] == "E01")["execution"]
        self.assertEqual(capped_execution["attempt_count"], ROW_ATTEMPT_CAP)
        self.assertIn("row_attempt_cap", capped_execution["cap_stop"]["reasons"])
        self.assertFalse((sandbox / "tmp").exists())

        unknown_matrix_id = "unknown-run"
        unknown_ledger_root = self.base / "unknown-ledger"
        create_or_resume_ledger(
            unknown_matrix_id, ledger_root=unknown_ledger_root, now=self.now
        )
        unknown_run = "child-unknown-row"
        for event, offset in (
            ("seed_started", 0),
            ("seed_completed", 1),
            ("sandbox_launched", 2),
        ):
            event_time = self.now + timedelta(seconds=offset)
            record_row_event(
                unknown_matrix_id,
                "E01",
                unknown_run,
                event,
                event_timestamp=event_time.isoformat().replace("+00:00", "Z"),
                ledger_root=unknown_ledger_root,
                now=event_time,
            )
        reconcile_attempt_count(
            unknown_matrix_id,
            "E01",
            unknown_run,
            None,
            ledger_root=unknown_ledger_root,
            now=self.now,
        )
        unknown = run_child(
            "E01",
            unknown_run,
            "unknown",
            run_id=unknown_matrix_id,
            ledger_root=unknown_ledger_root,
        )
        self.assertTrue(unknown["denied"])
        self.assertEqual(unknown["transport_calls"], 0)
        unknown_ledger = create_or_resume_ledger(
            unknown_matrix_id, ledger_root=unknown_ledger_root
        )
        unknown_execution = next(slot for slot in unknown_ledger["slots"] if slot["row_id"] == "E01")["execution"]
        self.assertIsNone(unknown_execution["attempt_count"])
        self.assertIn("attempt_count_unknown", unknown_execution["cap_stop"]["reasons"])
        self.assertFalse((sandbox / "tmp").exists())

        startup_code = """\
import os
from pathlib import Path

Path(os.environ["MAPPING_PILOT_APP_MARKER"]).write_text("started", encoding="ascii")

class FakeTransport:
    def create(self):
        Path(os.environ["MAPPING_PILOT_TRANSPORT_MARKER"]).write_text(
            "called", encoding="ascii"
        )

FakeTransport().create()
"""

        def assert_startup_denied(
            label: str,
            *,
            missing_context: bool = False,
            invalid_context: bool = False,
            invalid_source: bool = False,
            unsafe_root: bool = False,
        ) -> None:
            row_run_id = "startup-" + label
            run_id = "startup-denied-" + label
            ledger_root = self.base / "startup-denials"
            guard_directory = ledger_root / run_id / "runtime" / row_run_id
            (PROJECT_ROOT / guard_directory).mkdir(parents=True, exist_ok=True)
            context = {
                "run_id": run_id,
                "row_id": "E03",
                "row_run_id": row_run_id,
                "lifecycle_id": "lifecycle-" + row_run_id,
                "ledger_root": ledger_root.as_posix(),
                "live_started_monotonic": time.monotonic(),
            }
            environment = os.environ.copy()
            environment.update(row_runner._request_guard_environment({
                "_request_guard_context": context,
                "_request_guard_directory": guard_directory.as_posix(),
            }))
            if invalid_context:
                context["row_id"] = "../invalid"
                environment["NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT"] = json.dumps(
                    context, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                )
            if unsafe_root:
                context["ledger_root"] = "tmp/../outside"
                environment["NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT"] = json.dumps(
                    context, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                )
            if missing_context:
                environment.pop("NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT", None)
            if invalid_source:
                invalid_source_directory = sandbox / ("invalid-source-" + label)
                invalid_source_directory.mkdir()
                (invalid_source_directory / "sitecustomize.py").write_text(
                    row_runner._REQUEST_GUARD_BOOTSTRAP, encoding="ascii"
                )
                environment["PYTHONPATH"] = os.pathsep.join(
                    [
                        str(invalid_source_directory),
                        environment.get("PYTHONPATH", ""),
                    ]
                )

            app_marker = sandbox / (label + "-application.marker")
            transport_marker = sandbox / (label + "-transport.marker")
            environment["MAPPING_PILOT_APP_MARKER"] = str(app_marker)
            environment["MAPPING_PILOT_TRANSPORT_MARKER"] = str(transport_marker)
            result = subprocess.run(
                [sys.executable, "-c", startup_code],
                cwd=str(sandbox),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, msg=result.stdout)
            self.assertFalse(app_marker.exists(), msg=label)
            self.assertFalse(transport_marker.exists(), msg=label)
            self.assertFalse((sandbox / "tmp").exists(), msg=label)
            ledger_path = PROJECT_ROOT / ledger_root / run_id / "matrix_ledger.json"
            self.assertFalse(ledger_path.exists(), msg=label)

        assert_startup_denied("missing-context", missing_context=True)
        assert_startup_denied("unsafe-root", unsafe_root=True)
        assert_startup_denied("invalid-context", invalid_context=True)
        assert_startup_denied("invalid-source", invalid_source=True)

    def _run_injected_row(
        self,
        row_id: str,
        *,
        packet_status: str = "recorded",
        startup_receipt_status: str = "recorded",
        unexpected_at_startup: bool = False,
        unexpected_after_restart: bool = False,
        unexpected_before_first_model: bool = False,
        invalid_pre_model_attribution: bool = False,
        unexpected_at_e4_08_boundary: bool = False,
        state_mismatch_after_restart: bool = False,
        receipt_write_failed: bool = False,
        co_located_runtime_metadata: bool = False,
        live_time_cap: bool = False,
        pre_content_decision: dict[str, Any] | None = None,
        pre_content_exception: Exception | None = None,
        missing_checkpoint_after_e4_07: bool = False,
        prepared_run_id: str | None = None,
        prepared_row_run_id: str | None = None,
        prepared_ledger_root: Path | None = None,
        row_evidence_root: Path | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from scripts.mapping_pilot.manifest import PROJECT_ROOT as PILOT_ROOT

        run_id = prepared_run_id or ("runner-" + uuid.uuid4().hex[:10])
        row_run_id = prepared_row_run_id or ("row-" + uuid.uuid4().hex)
        ledger_root = prepared_ledger_root or (self.base / ("ledger-" + run_id))
        evidence_root = row_evidence_root or (self.base / ("evidence-" + run_id))
        if prepared_run_id is None:
            create_or_resume_ledger(run_id, ledger_root=ledger_root, now=self.now)
            record_booking(
                run_id,
                booking_id="booking-" + uuid.uuid4().hex[:8],
                holder="Overseer: provider-free test",
                window_start=(self.now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                window_end=(self.now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                network_non_overlap_confirmed=True,
                ledger_root=ledger_root,
                now=self.now,
            )

        trace: dict[str, Any] = {
            "contexts": [],
            "receipts": [],
            "servers_started": [],
            "server_identities": [],
            "servers_stopped": [],
            "drivers": [],
            "seed_calls": [],
            "scoring_inputs": [],
            "events": [],
            "pre_model_injected": False,
            "e4_08_injected": False,
        }

        def append_unexpected_lifecycle_receipt(
            segment: int, step_id: str
        ) -> None:
            sequence = len(trace["receipts"]) + 1
            trace["receipts"].append(
                {
                    "event_type": "router_receipt",
                    "row_run_id": row_run_id,
                    "lifecycle_id": row_run_id + "-s%d" % segment,
                    "sequence": sequence,
                    "kind": "response",
                    "call_id": "unexpected-call-%d" % sequence,
                    "attempt_id": "unexpected-attempt-%d" % sequence,
                    "attempt_number": 1,
                    "task": "narrative",
                    "tier": "simple",
                    "profile": "test",
                    "transport_retry": False,
                    "retry_tier": None,
                    "fallback": False,
                    "transport": "openrouter",
                    "provider": "openai",
                    "requested_model": "openrouter/auto",
                    "resolved_model": "openai/test-model",
                    "prompt_units": 10,
                    "cached_units": 0,
                    "completion_units": 5,
                    "usage_complete": True,
                    "provider_reported_cost_usd": 0.001,
                    "cost_usd": 0.001,
                    "cost_provenance": "provider",
                    "cost_complete": True,
                    "error_type": None,
                    "elapsed_ms": 10.0,
                    "attribution": "lifecycle_control",
                    "attribution_status": "recorded",
                    "script_step_id": step_id,
                    "provider_call_expected": False,
                }
            )

        class FakeDriver:
            def __init__(self, segment: int, transcript_path: Path) -> None:
                self.segment = segment
                self.transcript_path = transcript_path
                self.transcript = ""
                self.sent: list[str] = []

            def start(self) -> dict[str, Any]:
                if self.segment == 1 and unexpected_at_startup:
                    for _ in range(6):
                        append_unexpected_lifecycle_receipt(1, "startup")
                if self.segment == 2 and unexpected_after_restart:
                    append_unexpected_lifecycle_receipt(2, "E4-07")
                return {"ready": True}

            def set_active_character(self, _character: str) -> bool:
                return True

            def send_turn(
                self, step_id: str, _utterance: str, _character: str
            ) -> dict[str, Any]:
                self.sent.append(step_id)
                self.transcript += "[game_output] response for %s\n" % step_id
                context = trace["contexts"][-1]
                sequence = len(trace["receipts"]) + 1
                trace["receipts"].append(
                    {
                        "event_type": "router_receipt",
                        "row_run_id": row_run_id,
                        "lifecycle_id": context["lifecycle_id"],
                        "sequence": sequence,
                        "kind": "response",
                        "call_id": "call-%s" % step_id,
                        "attempt_id": "attempt-%s" % step_id,
                        "attempt_number": 1,
                        "task": "narrative",
                        "tier": "simple",
                        "profile": "test",
                        "transport_retry": False,
                        "retry_tier": None,
                        "fallback": False,
                        "transport": "openrouter",
                        "provider": "openai",
                        "requested_model": "openrouter/auto",
                        "resolved_model": "openai/test-model",
                        "prompt_units": 10,
                        "cached_units": 0,
                        "completion_units": 5,
                        "usage_complete": True,
                        "provider_reported_cost_usd": 0.001,
                        "cost_usd": 0.001,
                        "cost_provenance": "provider",
                        "cost_complete": True,
                        "error_type": None,
                        "elapsed_ms": 100.0,
                        "attribution": context["phase"],
                        "attribution_status": "recorded",
                        "script_step_id": context["step_id"],
                        "provider_call_expected": context["provider_call_expected"],
                    }
                )
                return {
                    "completed": True,
                    "timed_out": False,
                    "backend_output_count": 1,
                    "game_output_count": 1,
                    "elapsed_seconds": 0.1,
                    "output_text": "response",
                }

            def close(self) -> None:
                return None

        class FakeServer(dict[str, Any]):
            @property
            def log_path(self) -> Path:
                return Path(self["log_path"])

        def start_server(
            row: dict[str, Any], run_token: str, lifecycle_id: str, log_path: Path
        ) -> dict[str, Any]:
            trace["server_identities"].append(dict(row))
            if co_located_runtime_metadata:
                runtime_directory = Path(row["_request_guard_directory"])
                metadata_path = runtime_directory / "sitecustomize.py"
                if not metadata_path.exists():
                    metadata_path.write_text(
                        "provider-free runtime metadata\n", encoding="ascii"
                    )
            log_path.write_text(
                "mapping_pilot_router_receipt_write_failed\n"
                if receipt_write_failed
                else "",
                encoding="ascii",
            )
            server = FakeServer(
                run_token=run_token,
                lifecycle_id=lifecycle_id,
                log_path=log_path,
            )
            trace["servers_started"].append(server)
            return server

        def driver_factory(
            *, party_size: int, transcript_path: Path, runtime_root: str
        ) -> FakeDriver:
            del party_size, runtime_root
            driver = FakeDriver(len(trace["drivers"]) + 1, transcript_path)
            trace["drivers"].append(driver)
            return driver

        def write_context(_root: str, context: dict[str, Any]) -> None:
            lifecycle_id = row_run_id + (
                "-s2" if len(trace["servers_started"]) > 1 else "-s1"
            )
            trace["contexts"].append({**context, "lifecycle_id": lifecycle_id})
            if (
                unexpected_before_first_model
                and not trace["pre_model_injected"]
                and context.get("step_id") == "E1-01"
                and context.get("phase") == "lifecycle_control"
                and len(trace["drivers"]) == 1
                and not trace["drivers"][0].sent
            ):
                append_unexpected_lifecycle_receipt(1, "E1-01")
                if invalid_pre_model_attribution:
                    trace["receipts"][-1]["attribution"] = "unverified"
                trace["pre_model_injected"] = True
            if (
                unexpected_at_e4_08_boundary
                and not trace["e4_08_injected"]
                and context.get("step_id") == "E4-08"
                and context.get("phase") == "lifecycle_control"
                and len(trace["servers_started"]) > 1
            ):
                append_unexpected_lifecycle_receipt(2, "E4-08")
                trace["e4_08_injected"] = True

        packet = "Place: the tavern entrance opens toward the green."
        packet_record = {
            "format_version": 1,
            "lifecycle_id": row_run_id + "-s1",
            "sequence": 1,
            "context_id": "context-01",
            "turn_id": "turn-01",
            "turn_number": 1,
            "turn_kind": "normal",
            "event_type": "packet_use",
            "surface": "dm_note",
            "use_index": 1,
            "packet_status": "present",
            "packet_ascii": packet,
            "packet_sha256": hashlib.sha256(packet.encode("ascii")).hexdigest(),
            "evidence_status": "recorded",
        }
        packet_loader_status = packet_status
        packet_loader_records = [packet_record]
        if packet_status == "not_applicable":
            packet_loader_records = [
                {
                    "event_type": "arm_a_noop",
                    "adapter_installed": False,
                    "evidence_status": "recorded",
                }
            ]

        def load_packet_evidence(
            _root: str, _lifecycle_ids: list[str]
        ) -> dict[str, Any]:
            return {
                "evidence_status": packet_loader_status,
                "records": packet_loader_records,
            }

        def load_receipts(_run_token: str) -> dict[str, Any]:
            return {
                "evidence_status": startup_receipt_status,
                "records": list(trace["receipts"]),
            }

        def state_hasher(_root: str) -> dict[str, Any]:
            if (
                missing_checkpoint_after_e4_07
                and trace["drivers"]
                and trace["drivers"][0].sent
                and trace["drivers"][0].sent[-1] == "E4-07"
            ):
                return {"status": "missing", "sha256": None, "files": {}}
            state_hash = (
                "c" * 64
                if state_mismatch_after_restart and len(trace["servers_started"]) > 1
                else "a" * 64
            )
            return {
                "status": "recorded",
                "sha256": state_hash,
                "files": {"party_tracker.json": "b" * 64},
            }

        def scorer(row_data: dict[str, Any]) -> dict[str, Any]:
            trace["events"].append("score")
            trace["scoring_inputs"].append(dict(row_data))
            return score_row(row_data)

        def check_evaluator(step: dict[str, Any], _turn: dict[str, Any]) -> list[dict[str, Any]]:
            trace["events"].append("content_check")
            current = create_or_resume_ledger(
                run_id, ledger_root=ledger_root, now=self.now
            )
            current_slot = next(
                item for item in current["slots"] if item["row_id"] == row_id
            )
            classification = current_slot["pre_content_classification"]
            review_sequence = current_slot["content_review_event_sequence"]
            trace["checks_saw_review_marker"] = review_sequence is not None
            trace["checks_saw_prior_classification"] = (
                classification is None
                or classification["event_sequence"] < review_sequence
            )
            return [
                {"observed": "scripted evidence", "passed": True}
                for _check in step.get("expected_checks", [])
            ]

        def classify_pre_content(
            context: dict[str, Any]
        ) -> dict[str, Any] | None:
            trace["events"].append("pre_content_classification")
            trace["pre_content_context"] = dict(context)
            if pre_content_exception is not None:
                raise pre_content_exception
            return dict(pre_content_decision) if pre_content_decision is not None else None

        hooks = RowRunnerHooks(
            seed=lambda row: trace["seed_calls"].append(dict(row)) or 0,
            start_server=start_server,
            wait_server_ready=lambda _server, _timeout: True,
            stop_server=lambda server: trace["servers_stopped"].append(server),
            driver_factory=driver_factory,
            load_packet_evidence=load_packet_evidence,
            load_router_receipts=load_receipts,
            state_hasher=state_hasher,
            write_step_context=write_context,
            evidence_writer=create_evidence_bundle,
            scorer=scorer,
            check_evaluator=check_evaluator,
            pre_content_classifier=(
                classify_pre_content
                if pre_content_decision is not None or pre_content_exception is not None
                else None
            ),
            source_identity=lambda: {
                "git_head_sha": "a" * 40,
                "branch": "test/mapping-pilot",
                "dirty": False,
                "worktree": str(PILOT_ROOT),
            },
            monotonic=lambda: (
                100.0 + float(ROW_WALL_TIME_CAP_SECONDS)
                if live_time_cap and trace["drivers"] and trace["drivers"][0].sent
                else 100.0
            ),
            wall_clock=lambda: self.now,
        )
        with mock.patch.object(
            subprocess, "Popen", side_effect=AssertionError("real server must not start")
        ), mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("socket must not open")
        ):
            result = execute_row(
                run_id,
                row_id,
                row_run_id=row_run_id,
                ledger_root=ledger_root,
                evidence_root=evidence_root,
                hooks=hooks,
            )
        trace["ledger"] = create_or_resume_ledger(
            run_id, ledger_root=ledger_root, now=self.now
        )
        trace["evidence_root"] = evidence_root
        trace["row_run_id"] = row_run_id
        trace["run_id"] = run_id
        trace["ledger_root"] = ledger_root
        return result, trace

    def test_row_runner_p1_arm_a_and_p4_rows_preserve_noop_and_lifecycle_evidence(self) -> None:
        p1_result, p1_trace = self._run_injected_row("E01", packet_status="not_applicable")
        p4_result, p4_trace = self._run_injected_row("E07")

        self.assertEqual(p1_result["verdict"], "PASS")
        self.assertEqual(p1_result["party"], "P1")
        self.assertEqual(p1_result["seed"], 5101)
        self.assertEqual(p4_result["verdict"], "PASS")
        self.assertEqual(p4_result["party"], "P4")
        self.assertEqual(p4_result["seed"], 5103)
        for result, trace, expected_arm in (
            (p1_result, p1_trace, "A"),
            (p4_result, p4_trace, "B"),
        ):
            self.assertEqual(len(trace["seed_calls"]), 1)
            self.assertEqual(len(trace["servers_started"]), 2)
            self.assertEqual(len(trace["servers_stopped"]), 2)
            self.assertEqual(trace["servers_stopped"], trace["servers_started"])
            self.assertEqual(
                [server["lifecycle_id"] for server in trace["servers_started"]],
                [trace["row_run_id"] + "-s1", trace["row_run_id"] + "-s2"],
            )
            self.assertEqual(
                {server["run_token"] for server in trace["servers_started"]},
                {trace["row_run_id"]},
            )
            self.assertEqual(
                trace["drivers"][1].sent[-1], "E4-08"
            )
            self.assertEqual(
                result["lifecycle_checkpoint"]["saved_state_sha256"],
                result["lifecycle_checkpoint"]["resumed_state_sha256"],
            )
            self.assertNotIn("resume_checkpoint_sha256", trace["server_identities"][0])
            self.assertEqual(
                trace["server_identities"][1]["resume_checkpoint_sha256"],
                result["lifecycle_checkpoint"]["saved_state_sha256"],
            )
            bundle = Path(trace["evidence_root"]) / "sp3" / trace["row_run_id"]
            stored_row = json.loads((PROJECT_ROOT / bundle / "row.json").read_text(encoding="ascii"))
            self.assertEqual(stored_row["fixture_id"], "interior_tavern")
            self.assertEqual(stored_row["seed"], result["seed"])
            self.assertEqual(stored_row["script_id"], result["script_id"])
            self.assertEqual(stored_row["scenario_id"], result["script_id"])
            self.assertEqual(stored_row["party"], result["party"])
            self.assertEqual(stored_row["arm"], expected_arm)
        p1_packets = json.loads(
            (
                PROJECT_ROOT
                / p1_trace["evidence_root"]
                / "sp3"
                / p1_trace["row_run_id"]
                / "exact_packets.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(p1_packets["evidence_status"], "not_applicable")
        self.assertEqual(p1_packets["records"][0]["event_type"], "arm_a_noop")
        self.assertIn("provider_call_expected_false_observed=0", (
            PROJECT_ROOT
            / p1_trace["evidence_root"]
            / "sp3"
            / p1_trace["row_run_id"]
            / "server_logs.txt"
        ).read_text(encoding="ascii"))

    def test_row_bundle_root_is_separate_from_default_layout_ledger_and_runtime(self) -> None:
        mapping_root = self.base / "router-rollout" / "mapping-pilot"
        ledger_root = mapping_root / "sp3"
        evidence_root = mapping_root / "row-bundles"
        run_id = "co-located-" + uuid.uuid4().hex[:10]
        row_run_id = "row-" + uuid.uuid4().hex
        create_or_resume_ledger(run_id, ledger_root=ledger_root, now=self.now)
        record_booking(
            run_id,
            booking_id="booking-co-located",
            holder="Overseer: provider-free test",
            window_start=(self.now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            window_end=(self.now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            network_non_overlap_confirmed=True,
            ledger_root=ledger_root,
            now=self.now,
        )
        prior_runtime = ledger_root / run_id / "runtime" / "prior-row"
        prior_runtime.mkdir(parents=True)
        (prior_runtime / "sitecustomize.py").write_text(
            "provider-free prior runtime metadata\n", encoding="ascii"
        )

        result, trace = self._run_injected_row(
            "E07",
            prepared_run_id=run_id,
            prepared_row_run_id=row_run_id,
            prepared_ledger_root=ledger_root,
            row_evidence_root=evidence_root,
            co_located_runtime_metadata=True,
        )

        self.assertEqual(
            DEFAULT_ROW_EVIDENCE_ROOT,
            Path("tmp/router-rollout/mapping-pilot/row-bundles"),
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(
            result["evidence_path"],
            (evidence_root / "sp3" / row_run_id).as_posix(),
        )
        self.assertTrue(
            (ledger_root / run_id / "matrix_ledger.json").is_file()
        )
        self.assertTrue((prior_runtime / "sitecustomize.py").is_file())
        self.assertTrue(
            (
                ledger_root
                / run_id
                / "runtime"
                / row_run_id
                / "sitecustomize.py"
            ).is_file()
        )
        self.assertTrue(
            (
                PROJECT_ROOT
                / result["evidence_path"]
                / "manifest.json"
            ).is_file()
        )
        self.assertEqual(trace["evidence_root"], evidence_root)

    def test_row_runner_continues_after_unexpected_startup_receipts_but_blocks_pass(self) -> None:
        from scripts.mapping_pilot import row_runner

        _row, frozen_script, _fixture_id = row_runner._resolve_frozen_row("E01", None)
        expected_step_ids = [step["id"] for step in frozen_script["turns"]]
        result, trace = self._run_injected_row(
            "E01",
            packet_status="not_applicable",
            unexpected_at_startup=True,
        )

        self.assertEqual(result["driver_exit_code"], 0)
        self.assertEqual(trace["drivers"][0].sent + trace["drivers"][1].sent, expected_step_ids)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["provider_call_expected_false_observed"], 6)
        expected_attempts = len(expected_step_ids) + 6
        self.assertEqual(result["router_attempt_count"], expected_attempts)
        self.assertEqual(result["ledger_attempt_count"], expected_attempts)
        self.assertEqual(trace["scoring_inputs"][0]["attempt_count"], expected_attempts)
        self.assertEqual(len(trace["scoring_inputs"][0]["model_turns"]), len(expected_step_ids))
        self.assertEqual(len(trace["scoring_inputs"][0]["provider_calls"]), len(expected_step_ids))

        bundle = PROJECT_ROOT / result["evidence_path"]
        receipts = json.loads((bundle / "router_receipts.json").read_text(encoding="ascii"))
        counts = json.loads((bundle / "cap_counts.json").read_text(encoding="ascii"))
        logs = (bundle / "server_logs.txt").read_text(encoding="ascii")
        self.assertEqual(receipts["startup_provider_call_expected_false_observed"], 6)
        self.assertEqual(receipts["attempt_count"], expected_attempts)
        self.assertEqual(counts["row_attempts"], expected_attempts)
        self.assertIn("UnexpectedStartupProviderCall", logs)
        self.assertEqual(trace["ledger"]["slots"][0]["status"], "BLOCKED")

    def test_row_runner_missing_startup_receipts_still_fail_closed(self) -> None:
        result, trace = self._run_injected_row(
            "E01",
            packet_status="not_applicable",
            startup_receipt_status="missing",
        )

        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["driver_exit_code"], 1)
        self.assertEqual(trace["drivers"][0].sent, [])
        self.assertEqual(result["router_attempt_count"], 0)

    def test_row_runner_receipt_write_failure_still_stops_before_script(self) -> None:
        result, trace = self._run_injected_row(
            "E01",
            packet_status="not_applicable",
            receipt_write_failed=True,
        )

        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["driver_exit_code"], 1)
        self.assertEqual(trace["drivers"][0].sent, [])
        logs = (
            PROJECT_ROOT / result["evidence_path"] / "server_logs.txt"
        ).read_text(encoding="ascii")
        self.assertIn("RouterReceiptWriteFailed", logs)

    def test_row_runner_blocks_exit_zero_when_required_evidence_is_degraded(self) -> None:
        result, trace = self._run_injected_row("E07", packet_status="degraded")
        self.assertEqual(result["driver_exit_code"], 0)
        self.assertEqual(result["verdict"], "BLOCKED")
        slot = next(row for row in trace["ledger"]["slots"] if row["row_id"] == "E07")
        self.assertEqual(slot["status"], "BLOCKED")
        packet_artifact = json.loads(
            (
                PROJECT_ROOT
                / trace["evidence_root"]
                / "sp3"
                / trace["row_run_id"]
                / "exact_packets.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(packet_artifact["evidence_status"], "degraded")

    def test_row_runner_records_explicit_classification_before_content_checks(self) -> None:
        decision = {
            "classification": "CONTENT/RESULT",
            "reason": "usable model response was returned before review",
            "evidence": [
                {
                    "kind": "provider_status",
                    "code": "usable_response_returned",
                    "source": "tmp/pre-content/provider-receipts.json",
                }
            ],
        }
        result, trace = self._run_injected_row(
            "E07", pre_content_decision=decision
        )

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(
            trace["pre_content_context"]["router_receipt_status"], "recorded"
        )
        self.assertNotIn("transcript", trace["pre_content_context"])
        self.assertNotIn("output_text", trace["pre_content_context"])
        self.assertLess(
            trace["events"].index("pre_content_classification"),
            trace["events"].index("content_check"),
        )
        self.assertTrue(trace["checks_saw_review_marker"])
        self.assertTrue(trace["checks_saw_prior_classification"])
        slot = next(
            item
            for item in trace["ledger"]["slots"]
            if item["row_id"] == "E07"
        )
        self.assertEqual(
            slot["pre_content_classification"]["classification"],
            "CONTENT/RESULT",
        )
        self.assertLess(
            slot["pre_content_classification"]["event_sequence"],
            slot["content_review_event_sequence"],
        )
        cap_artifact = json.loads(
            (
                PROJECT_ROOT
                / trace["evidence_root"]
                / "sp3"
                / trace["row_run_id"]
                / "cap_counts.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(
            cap_artifact["pre_content_classification"]["classification"],
            "CONTENT/RESULT",
        )

    def test_row_runner_without_classifier_records_unresolved_before_review(self) -> None:
        result, trace = self._run_injected_row("E07")
        slot = next(
            item for item in trace["ledger"]["slots"] if item["row_id"] == "E07"
        )
        classification = slot["pre_content_classification"]

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(classification["classification"], "UNRESOLVED")
        self.assertEqual(classification["reason"], "no_classifier")
        self.assertEqual(classification["evidence"], [])
        self.assertEqual(classification["recorded_at"], "2026-11-05T12:00:00Z")
        self.assertFalse(classification["reserve_eligible"])
        self.assertLess(
            classification["event_sequence"], slot["content_review_event_sequence"]
        )
        self.assertTrue(trace["checks_saw_review_marker"])
        self.assertTrue(trace["checks_saw_prior_classification"])
        with self.assertRaisesRegex(
            ExecutionLedgerError, "no pre-content infrastructure"
        ):
            activate_next_reserve(
                trace["run_id"], ledger_root=trace["ledger_root"], now=self.now
            )

    def test_row_runner_classifier_exception_records_only_exception_type(self) -> None:
        exception_detail = "private classifier exception detail"
        _result, trace = self._run_injected_row(
            "E07",
            pre_content_exception=RuntimeError(exception_detail),
        )
        slot = next(
            item for item in trace["ledger"]["slots"] if item["row_id"] == "E07"
        )
        classification = slot["pre_content_classification"]
        log_text = (
            PROJECT_ROOT
            / trace["evidence_root"]
            / "sp3"
            / trace["row_run_id"]
            / "server_logs.txt"
        ).read_text(encoding="ascii")

        self.assertEqual(classification["classification"], "UNRESOLVED")
        self.assertEqual(classification["reason"], "RuntimeError")
        self.assertEqual(classification["evidence"], [])
        self.assertFalse(classification["reserve_eligible"])
        self.assertLess(
            classification["event_sequence"], slot["content_review_event_sequence"]
        )
        self.assertIn("error_type=RuntimeError", log_text)
        self.assertNotIn(exception_detail, log_text)

    def test_activated_reserve_runs_with_its_seed_and_does_not_overwrite_source(self) -> None:
        self.run_id = "reserve-run-" + uuid.uuid4().hex[:10]
        ledger_root = self.base
        self._create_ledger()
        self._record_booking(booking_id="reserve-booking")
        infra_evidence = [
            {
                "kind": "process",
                "code": "sandbox_boot_failed",
                "source": "tmp/pre-content/launcher.log",
            }
        ]
        self._record_classified_failure(
            "E01",
            "original-infra-row-run",
            "INFRASTRUCTURE",
            infra_evidence,
            status="BLOCKED",
        )
        original_before = next(
            item
            for item in create_or_resume_ledger(
                self.run_id, ledger_root=ledger_root, now=self.now
            )["slots"]
            if item["row_id"] == "E01"
        )
        assignment = activate_next_reserve(
            self.run_id,
            ledger_root=ledger_root,
            now=self.now + timedelta(seconds=10),
        )
        original_after_assignment = next(
            item
            for item in create_or_resume_ledger(
                self.run_id, ledger_root=ledger_root, now=self.now
            )["slots"]
            if item["row_id"] == "E01"
        )
        self.assertEqual(original_after_assignment, original_before)
        self.assertEqual(assignment["source_row_id"], "E01")
        self.assertEqual(assignment["source_row_run_id"], "original-infra-row-run")
        self.assertEqual(assignment["reserve_seed"], 5901)

        result, trace = self._run_injected_row(
            "R01",
            prepared_run_id=self.run_id,
            prepared_row_run_id=assignment["replacement_run_id"],
            prepared_ledger_root=ledger_root,
        )
        self.assertEqual(result["row_run_id"], assignment["replacement_run_id"])
        self.assertEqual(result["seed"], 5901)
        self.assertEqual(trace["seed_calls"][0]["row_id"], "R01")
        self.assertEqual(trace["seed_calls"][0]["seed"], 5901)
        bundle = Path(trace["evidence_root"]) / "sp3" / trace["row_run_id"]
        stored_row = json.loads(
            (PROJECT_ROOT / bundle / "row.json").read_text(encoding="ascii")
        )
        self.assertEqual(stored_row["row_id"], "R01")
        self.assertEqual(stored_row["replacement_for"], "E01")
        self.assertEqual(stored_row["source_row_run_id"], "original-infra-row-run")
        self.assertEqual(stored_row["seed"], 5901)
        self.assertEqual(stored_row["arm"], "A")
        self.assertEqual(stored_row["party"], "P1")

        final_ledger = create_or_resume_ledger(
            self.run_id, ledger_root=ledger_root, now=self.now
        )
        source_slot = next(item for item in final_ledger["slots"] if item["row_id"] == "E01")
        reserve_slot = next(item for item in final_ledger["slots"] if item["row_id"] == "R01")
        self.assertEqual(source_slot, original_before)
        self.assertEqual(reserve_slot["row_id"], "R01")
        self.assertEqual(reserve_slot["fixed_seed"], 5901)
        self.assertEqual(reserve_slot["replacement"]["replacement_run_id"], result["row_run_id"])
        self.assertEqual(reserve_slot["status"], "PASS")

    def test_live_cap_stops_row_preserves_raw_evidence_without_infra_classification(self) -> None:
        result, trace = self._run_injected_row("E07", live_time_cap=True)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(len(trace["servers_started"]), 1)
        self.assertEqual(trace["servers_stopped"], trace["servers_started"])
        self.assertIn("row_wall_time_cap", result["cap_stop"]["reasons"])
        self.assertEqual(
            result["ledger_attempt_count"],
            result["router_attempt_count"],
        )

        raw_evidence_path = result["cap_counts"]["raw_live_evidence_path"]
        self.assertIsInstance(raw_evidence_path, str)
        raw_evidence = json.loads(
            (PROJECT_ROOT / raw_evidence_path).read_text(encoding="ascii")
        )
        self.assertEqual(raw_evidence["row"]["row_id"], "E07")
        self.assertGreaterEqual(len(raw_evidence["router_receipts"]["records"]), 1)
        self.assertTrue(raw_evidence["transcript"])

        slot = next(
            row for row in trace["ledger"]["slots"] if row["row_id"] == "E07"
        )
        self.assertEqual(slot["status"], "BLOCKED")
        self.assertIn("live cap", slot["reason"])
        self.assertNotIn("infrastructure", slot["reason"].lower())
        self.assertEqual(
            slot["pre_content_classification"]["classification"], "UNRESOLVED"
        )
        self.assertFalse(slot["pre_content_classification"]["reserve_eligible"])
        self.assertEqual(
            slot["execution"]["timestamps"]["teardown_completed_at"],
            slot["execution"]["live_interval"]["ended_at"],
        )

    def test_row_runner_continues_after_unexpected_restart_receipt_but_blocks_pass(self) -> None:
        from scripts.mapping_pilot import row_runner

        _row, frozen_script, _fixture_id = row_runner._resolve_frozen_row("E07", None)
        expected_step_ids = [step["id"] for step in frozen_script["turns"]]
        result, trace = self._run_injected_row(
            "E07", unexpected_after_restart=True
        )
        self.assertEqual(result["lifecycle_checkpoint"]["status"], "degraded")
        self.assertTrue(result["lifecycle_checkpoint"]["resume_integrity_verified"])
        self.assertEqual(
            result["lifecycle_checkpoint"]["provider_call_expected_false_observed"],
            1,
        )
        self.assertEqual(
            trace["drivers"][0].sent + trace["drivers"][1].sent,
            expected_step_ids,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["provider_call_expected_false_observed"], 1)
        expected_attempts = len(expected_step_ids) + 1
        self.assertEqual(result["router_attempt_count"], expected_attempts)
        self.assertEqual(result["ledger_attempt_count"], expected_attempts)
        self.assertEqual(trace["scoring_inputs"][0]["attempt_count"], expected_attempts)
        self.assertEqual(len(trace["scoring_inputs"][0]["provider_calls"]), len(expected_step_ids))
        cap_artifact = json.loads(
            (
                PROJECT_ROOT
                / trace["evidence_root"]
                / "sp3"
                / trace["row_run_id"]
                / "cap_counts.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(cap_artifact["row_attempts"], expected_attempts)

        boundary_result, boundary_trace = self._run_injected_row(
            "E07", unexpected_at_e4_08_boundary=True
        )
        self.assertEqual(boundary_result["lifecycle_checkpoint"]["status"], "degraded")
        self.assertEqual(
            boundary_result["lifecycle_checkpoint"][
                "provider_call_expected_false_observed"
            ],
            1,
        )
        self.assertTrue(boundary_trace["e4_08_injected"])
        self.assertIn("E4-08", boundary_trace["drivers"][1].sent)
        self.assertEqual(boundary_result["verdict"], "BLOCKED")

    def test_row_runner_continues_after_attributable_pre_model_call_but_blocks_pass(self) -> None:
        from scripts.mapping_pilot import row_runner

        _row, frozen_script, _fixture_id = row_runner._resolve_frozen_row("E07", None)
        expected_step_ids = [step["id"] for step in frozen_script["turns"]]
        result, trace = self._run_injected_row(
            "E07", unexpected_before_first_model=True
        )
        self.assertEqual(result["driver_exit_code"], 0)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(
            trace["drivers"][0].sent + trace["drivers"][1].sent,
            expected_step_ids,
        )
        self.assertTrue(trace["pre_model_injected"])
        self.assertEqual(result["provider_call_expected_false_observed"], 1)
        self.assertEqual(
            result["router_attempt_count"], len(expected_step_ids) + 1
        )
        self.assertEqual(
            result["ledger_attempt_count"], len(expected_step_ids) + 1
        )

    def test_row_runner_stops_on_unattributed_pre_model_receipt(self) -> None:
        result, trace = self._run_injected_row(
            "E07",
            unexpected_before_first_model=True,
            invalid_pre_model_attribution=True,
        )
        self.assertEqual(result["driver_exit_code"], 1)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(trace["drivers"][0].sent, [])
        self.assertEqual(result["router_attempt_count"], 1)

    def test_row_runner_does_not_waive_restart_state_hash_mismatch(self) -> None:
        result, trace = self._run_injected_row(
            "E07", state_mismatch_after_restart=True
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["lifecycle_checkpoint"]["status"], "blocked")
        self.assertFalse(result["lifecycle_checkpoint"]["resume_integrity_verified"])
        self.assertFalse(result["lifecycle_checkpoint"]["state_hash_matches"])
        self.assertNotIn("E4-08", trace["drivers"][1].sent)

    def test_row_runner_refuses_restart_without_a_parent_checkpoint_hash(self) -> None:
        result, trace = self._run_injected_row(
            "E07", missing_checkpoint_after_e4_07=True
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["lifecycle_checkpoint"]["status"], "blocked")
        self.assertTrue(result["lifecycle_checkpoint"]["resume_checkpoint_missing"])
        self.assertEqual(len(trace["seed_calls"]), 1)
        self.assertEqual(len(trace["servers_started"]), 1)
        self.assertNotIn("E4-08", trace["drivers"][0].sent)

    def test_default_server_start_binds_resume_flags_to_saved_hash(self) -> None:
        from scripts.mapping_pilot import row_runner

        checkpoint = "b" * 64
        row = {
            "arm": "B",
            "fixture_id": "interior_tavern",
            "party": "P1",
            "resume_checkpoint_sha256": checkpoint,
        }
        log_path = PROJECT_ROOT / self.base / "resume-server.log"
        fake_process = SimpleNamespace(poll=lambda: None)
        with mock.patch.object(row_runner, "_request_guard_environment", return_value={}), mock.patch.object(
            subprocess, "Popen", return_value=fake_process
        ) as popen:
            owned = row_runner._start_owned_server(
                row, "row-resume", "row-resume-s2", log_path
            )
        try:
            command = popen.call_args.args[0]
            self.assertIn("--resume", command)
            checkpoint_index = command.index("--resume-checkpoint-sha256")
            self.assertEqual(command[checkpoint_index + 1], checkpoint)
            self.assertEqual(popen.call_args.kwargs["env"]["NEQ_OPEN_BROWSER"], "0")
        finally:
            owned.log_handle.close()

    def test_server_worker_requires_and_forwards_explicit_resume_checkpoint(self) -> None:
        from scripts.mapping_pilot import server

        sandbox = PROJECT_ROOT / self.base / "server-sandbox"
        sandbox.mkdir(parents=True)
        checkpoint = "c" * 64
        forwarded: list[dict[str, Any]] = []
        fake_launcher = SimpleNamespace(
            launch=lambda **kwargs: forwarded.append(dict(kwargs)) or "started"
        )
        with mock.patch.object(server, "_safe_runtime_root", return_value=sandbox):
            with self.assertRaisesRegex(ValueError, "checkpoint is missing"):
                server.launch_worker(
                    arm="B",
                    fixture_id="interior_tavern",
                    party_size=1,
                    row_run_id="server-resume-test",
                    resume=True,
                    launcher=fake_launcher,
                )
            self.assertEqual(forwarded, [])
            result = server.launch_worker(
                arm="B",
                fixture_id="interior_tavern",
                party_size=1,
                row_run_id="server-resume-test",
                resume=True,
                resume_checkpoint_sha256=checkpoint,
                launcher=fake_launcher,
            )
        self.assertEqual(result, "started")
        self.assertEqual(forwarded[0]["resume"], True)
        self.assertEqual(forwarded[0]["resume_checkpoint_sha256"], checkpoint)
        parsed = server._parse_args(
            [
                "--arm",
                "B",
                "--fixture-id",
                "interior_tavern",
                "--party-size",
                "1",
                "--row-run-id",
                "server-resume-test",
                "--resume",
                "--resume-checkpoint-sha256",
                checkpoint,
            ]
        )
        self.assertTrue(parsed.resume)
        self.assertEqual(parsed.resume_checkpoint_sha256, checkpoint)

    def test_server_receipt_observer_attributes_startup_and_model_turn_without_content(self) -> None:
        from scripts.mapping_pilot import server as server_module

        sandbox = PROJECT_ROOT / self.base / "receipt-sandbox"
        mapping_root = sandbox / "mapping_pilot"
        mapping_root.mkdir(parents=True)
        step_path = mapping_root / "current_script_step.json"
        step_path.write_text(
            json.dumps(
                {
                    "step_id": "startup",
                    "phase": "lifecycle_control",
                    "provider_call_expected": False,
                }
            ),
            encoding="ascii",
        )

        class FakeRouter:
            def __init__(self) -> None:
                self.call_count = 0

            def call(self, *_args: Any, **kwargs: Any) -> str:
                self.call_count += 1
                receipt = SimpleNamespace(
                    kind="response",
                    call_id="call-%d" % self.call_count,
                    attempt_id="attempt-%d" % self.call_count,
                    attempt_number=1,
                    task="narrative",
                    tier="simple",
                    profile="test-profile",
                    transport_retry=False,
                    retry_tier=None,
                    fallback=False,
                    transport_provider="openrouter",
                    observed_upstream_provider="openai",
                    requested_model="openrouter/auto",
                    resolved_model="openai/test-model",
                    prompt_tokens=10,
                    cached_tokens=0,
                    completion_tokens=5,
                    usage_complete=True,
                    provider_reported_cost_usd=0.001,
                    cost_usd=0.001,
                    cost_provenance="provider",
                    cost_complete=True,
                    error_type=None,
                    elapsed_ms=10.0,
                )
                kwargs["observer"](receipt, {"prompt": "must not be persisted"})
                return "response"

        fake_router = FakeRouter()
        with mock.patch.object(
            server_module, "_safe_runtime_root", return_value=sandbox
        ):
            cleanup = server_module.install_router_receipt_observer(
                "tmp/combat_capture",
                "row-receipt-test",
                "row-receipt-test-s1",
                router_module=SimpleNamespace(llm=fake_router),
            )
        try:
            fake_router.call("narrative", "ignored")
            step_path.write_text(
                json.dumps(
                    {
                        "step_id": "E1-01",
                        "phase": "model_bearing_turn",
                        "provider_call_expected": True,
                    }
                ),
                encoding="ascii",
            )
            fake_router.call("narrative", "ignored")
        finally:
            cleanup()
            cleanup()
        receipt_directory = mapping_root / "router_receipts" / "row-receipt-test"
        receipts = [
            json.loads(path.read_text(encoding="ascii"))
            for path in sorted(receipt_directory.glob("record-*.json"))
        ]
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0]["attribution"], "lifecycle_control")
        self.assertFalse(receipts[0]["provider_call_expected"])
        self.assertEqual(receipts[1]["attribution"], "model_bearing_turn")
        self.assertEqual(receipts[1]["script_step_id"], "E1-01")
        self.assertTrue(receipts[1]["provider_call_expected"])
        self.assertNotIn("prompt", receipts[1])
        self.assertNotIn("response", receipts[1])

    def test_arm_a_server_observation_is_an_explicit_noop_record(self) -> None:
        from scripts.mapping_pilot import server as server_module

        sandbox = PROJECT_ROOT / self.base / "arm-a-sandbox"
        sandbox.mkdir(parents=True)
        server_module._write_arm_a_noop_record(sandbox, "row-arm-a-s1")
        record_path = (
            sandbox
            / "mapping_pilot"
            / "turn_packet_evidence"
            / "row-arm-a-s1"
            / "record-00000001.json"
        )
        record = json.loads(record_path.read_text(encoding="ascii"))
        self.assertEqual(record["event_type"], "arm_a_noop")
        self.assertFalse(record["adapter_installed"])
        self.assertEqual(record["evidence_status"], "recorded")


if __name__ == "__main__":
    unittest.main()
