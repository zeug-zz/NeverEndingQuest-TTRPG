# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for blinded mapping-pilot transcript review packets."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import shutil
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    create_evidence_bundle,
)
from scripts.mapping_pilot.execution import (
    create_or_resume_ledger,
    mark_content_review_started,
    record_pre_content_classification,
    record_row_event,
    set_slot_status,
)
from scripts.mapping_pilot.manifest import DEFAULT_PREREG_ROOT
from scripts.mapping_pilot.review import (
    CONDITION_KEY_FILENAME,
    DISCLOSURE_FILENAME,
    RATINGS_FILENAME,
    RATING_LOCK_FILENAME,
    ReviewPacketError,
    create_review_packet,
    release_condition_key,
)
from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
)

_FIXTURE_BY_SCRIPT = {
    "scripts/interior.json": ("interior_tavern", "fixtures/interior_tavern.json"),
    "scripts/landscape.json": ("landscape_village", "fixtures/landscape_village.json"),
    "scripts/combat.json": (
        "combat_stage_tavern_zones",
        "fixtures/combat_stage_tavern.json",
    ),
}
_RATING_COLUMNS = (
    "sense_of_place_1_5",
    "sense_of_place_evidence",
    "imaginability_1_5",
    "imaginability_evidence",
    "natural_use_1_5",
    "natural_use_evidence",
    "actionability_1_5",
    "actionability_evidence",
    "continuity_1_5",
    "continuity_evidence",
    "combat_clarity_and_flow_1_5",
    "combat_clarity_and_flow_evidence",
)


class MappingPilotReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch_root = Path("tmp") / ("mapping-pilot-review-tests-" + uuid.uuid4().hex)
        cls.scratch_root.mkdir(parents=True, exist_ok=False)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.scratch_root, ignore_errors=True)

    def setUp(self) -> None:
        self.test_root = self.scratch_root / self._testMethodName
        self.test_root.mkdir(parents=True, exist_ok=False)
        self.sp3_run_id = "sp3-" + uuid.uuid4().hex
        self.ledger_root = self.test_root / "ledger"
        self.bundle_root = DEFAULT_EVIDENCE_ROOT / ("review-test-" + uuid.uuid4().hex)
        self.output_root = self.test_root / "packets"
        self.key_root = self.test_root / "keys"
        self.file_operations_logger = logging.getLogger("utils.file_operations")
        self.original_file_operations_level = self.file_operations_logger.level
        self.file_operations_logger.setLevel(logging.WARNING)
        self.addCleanup(
            self.file_operations_logger.setLevel,
            self.original_file_operations_level,
        )
        self._ledger = create_or_resume_ledger(
            self.sp3_run_id, ledger_root=self.ledger_root
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)
        shutil.rmtree(self.bundle_root, ignore_errors=True)

    def _slot(self, row_id: str) -> dict[str, Any]:
        return next(slot for slot in self._ledger["slots"] if slot["row_id"] == row_id)

    def _create_bundle(
        self,
        row_id: str,
        *,
        status: str = "PASS",
        response_state: str = "complete",
        pre_reviewed: bool = True,
    ) -> Path:
        slot = self._slot(row_id)
        row_run_id = "evidence-" + row_id.lower() + "-" + uuid.uuid4().hex[:8]
        script_path = slot["script"]
        script = json.loads(
            (DEFAULT_PREREG_ROOT / script_path).read_text(encoding="utf-8")
        )
        fixture_id, fixture_path = _FIXTURE_BY_SCRIPT[script_path]
        step_ids = [turn["id"] for turn in script["turns"]]
        expected_checks = self._delivery_checks(step_ids, response_state)
        packet_hash = hashlib.sha256(b"Exact fixture-derived spatial packet").hexdigest()
        transcript_ids = step_ids
        if response_state == "missing":
            transcript = "[missing] no driver transcript was captured for this row\n"
            transcript_ids = []
        elif response_state == "truncated":
            transcript_ids = step_ids[:-1]
            transcript = self._transcript(transcript_ids, row_id, slot, packet_hash)
        else:
            transcript = self._transcript(step_ids, row_id, slot, packet_hash)

        base = datetime.now(timezone.utc) + timedelta(
            seconds=slot["run_order"] * 1000
        )
        for event, seconds in (
            ("seed_started", 0),
            ("seed_completed", 1),
            ("sandbox_launched", 2),
            ("teardown_completed", 3),
            ("evidence_finalized", 4),
            ("scored", 5),
        ):
            event_time = base + timedelta(seconds=seconds)
            record_row_event(
                self.sp3_run_id,
                row_id,
                row_run_id,
                event,
                event_timestamp=event_time.isoformat(),
                live_elapsed_seconds=1.0 if event == "teardown_completed" else None,
                ledger_root=self.ledger_root,
                now=event_time,
            )

        row = {
            "row_id": row_id,
            "fixture_id": fixture_id,
            "script_id": script["script_id"],
            "scenario_id": script["script_id"],
            "arm": slot["arm"],
            "party": "P%d" % slot["party"],
            "seed": slot["fixed_seed"],
            "run_order": slot["run_order"],
        }
        provenance = {
            "source_identity": {
                "git_head_sha": "a" * 40,
                "branch": "feature/mapping-pilot-review-test",
                "dirty": False,
                "worktree": "review-test",
            },
            "input_paths": {
                "fixture": fixture_path,
                "script": script_path,
                "scenario": script_path,
            },
            "route_identity": {
                "requested": [
                    {
                        "call_id": "attempt-" + row_id,
                        "model": "openrouter/auto-hidden",
                        "provider": "openrouter-private",
                        "transport": "https-hidden",
                        "route": "route-hidden",
                        "fallback": False,
                    }
                ],
                "resolved": [
                    {
                        "call_id": "attempt-" + row_id,
                        "model": "openai/private-hidden-model",
                        "provider": "provider-private",
                        "transport": "https-hidden",
                        "route": "resolved-route-hidden",
                        "fallback": True,
                    }
                ],
            },
            "evidence_kind": "live",
        }
        if slot["arm"] == "A":
            exact_packets = {
                "evidence_status": "not_applicable",
                "records": [
                    {
                        "event_type": "arm_a_noop",
                        "adapter_installed": False,
                        "evidence_status": "recorded",
                    }
                ],
            }
        else:
            packet = "MAP: MPV2_F_TAVERN_BAR"
            exact_packets = {
                "evidence_status": "recorded",
                "records": [
                    {
                        "event_type": "packet_use",
                        "packet_status": "present",
                        "packet_ascii": packet,
                        "packet_sha256": hashlib.sha256(packet.encode("ascii")).hexdigest(),
                        "evidence_status": "recorded",
                    }
                ],
            }
            packet_hash = hashlib.sha256(packet.encode("ascii")).hexdigest()
            if response_state != "missing":
                transcript = self._transcript(transcript_ids, row_id, slot, packet_hash)

        checks = expected_checks
        checks.append(
            {
                "check_id": step_ids[0] + "-answer-key",
                "check_kind": "assertion",
                "expected": "Fixture answer key: THE_SECRET_FIXTURE_ANSWER_KEY",
                "observed": "Not part of the blinded review packet.",
                "passed": True,
            }
        )
        receipts = {
            "evidence_status": "recorded",
            "records": [
                {
                    "attempt_id": "attempt-" + row_id,
                    "sequence": 1,
                    "model": "openai/private-hidden-model",
                    "provider": "provider-private",
                    "transport": "https-hidden",
                    "route": "resolved-route-hidden",
                    "fallback": True,
                    "provider_call_expected": True,
                }
            ],
            "attempt_count": 1,
            "provider_call_expected_false_observed": 0,
        }
        artifacts = {
            "exact_packets": exact_packets,
            "transcript": transcript,
            "state_snapshots": {"status": "recorded", "before": "state-a", "after": "state-b"},
            "zone_trace": {"status": "not_applicable", "reason": "exploration row"},
            "expected_observed_checks": checks,
            "cap_counts": {
                "row_attempts": 8,
                "row_elapsed_seconds": 30,
                "matrix_attempts": 20,
                "matrix_elapsed_seconds": 60,
                "caps": {
                    "row_attempts": ROW_ATTEMPT_CAP,
                    "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
                    "matrix_attempts": MATRIX_ATTEMPT_CAP,
                    "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
                },
            },
            "logs": "Provider-free review test evidence.\n",
            "router_receipts": receipts,
            "scoring": {"status": "recorded", "schema": "mapping-pilot-test"},
        }
        verdict = "PASS" if status == "PASS" else "BLOCKED"
        bundle = create_evidence_bundle(
            "SP3",
            row_run_id,
            row=row,
            provenance=provenance,
            artifacts=artifacts,
            verdict=verdict,
            base_root=self.bundle_root,
        )

        if status == "PASS":
            if pre_reviewed:
                record_pre_content_classification(
                    self.sp3_run_id,
                    row_id,
                    row_run_id,
                    "CONTENT/RESULT",
                    reason="test transcript is available for content review",
                    evidence=[
                        {
                            "kind": "artifact_presence",
                            "code": "transcript_present",
                            "source": bundle.as_posix() + "/transcript.txt",
                        }
                    ],
                    ledger_root=self.ledger_root,
                    now=base + timedelta(seconds=6),
                )
                mark_content_review_started(
                    self.sp3_run_id,
                    row_id,
                    row_run_id,
                    ledger_root=self.ledger_root,
                    now=base + timedelta(seconds=7),
                )
            set_slot_status(
                self.sp3_run_id,
                row_id,
                "PASS",
                reason="complete provider-free review test row",
                evidence_path=bundle.as_posix(),
                ledger_root=self.ledger_root,
                now=base + timedelta(seconds=8),
            )
        else:
            record_pre_content_classification(
                self.sp3_run_id,
                row_id,
                row_run_id,
                "UNRESOLVED",
                reason="preserve unavailable or incomplete test response",
                evidence=[],
                ledger_root=self.ledger_root,
                now=base + timedelta(seconds=6),
            )
            mark_content_review_started(
                self.sp3_run_id,
                row_id,
                row_run_id,
                ledger_root=self.ledger_root,
                now=base + timedelta(seconds=7),
            )
            set_slot_status(
                self.sp3_run_id,
                row_id,
                "BLOCKED",
                reason="response is not suitable for rating",
                evidence_path=bundle.as_posix(),
                ledger_root=self.ledger_root,
                now=base + timedelta(seconds=8),
            )
        return bundle

    def _delivery_checks(
        self, step_ids: list[str], response_state: str
    ) -> list[dict[str, Any]]:
        checks = []
        for index, step_id in enumerate(step_ids):
            degraded = response_state == "degraded" and index == len(step_ids) - 1
            truncated = response_state == "truncated" and index == len(step_ids) - 1
            checks.append(
                {
                    "check_id": step_id + "-delivery",
                    "check_kind": "delivery",
                    "expected": "A completed response is available for rating.",
                    "observed": {
                        "completed": not truncated,
                        "timed_out": truncated,
                        "backend_output_count": 0 if truncated else 1,
                    },
                    "passed": not degraded and not truncated,
                }
            )
        return checks

    def _transcript(
        self,
        step_ids: list[str],
        row_id: str,
        slot: dict[str, Any],
        packet_hash: str,
    ) -> str:
        script = json.loads(
            (DEFAULT_PREREG_ROOT / slot["script"]).read_text(encoding="utf-8")
        )
        turn_by_id = {turn["id"]: turn for turn in script["turns"]}
        lines: list[str] = []
        for index, step_id in enumerate(step_ids, start=1):
            turn = turn_by_id[step_id]
            utterance = turn["utterance"]
            content = "The scene is coherent and the visible anchors remain stable."
            if index == 1:
                content += (
                    " row_id=%s arm=%s row_order=%s seed=%s model=openai/private-hidden-model"
                    " provider=provider-private transport=https-hidden route=resolved-route-hidden"
                    " fallback=yes packet_sha256=%s packet_hash=short-secret answer_key=XY"
                    " MPV2_F_TAVERN_BAR fixture_id=interior_tavern"
                    " script_id=interior_e1_e4 Fixture answer key: THE_SECRET_FIXTURE_ANSWER_KEY"
                    % (
                        row_id,
                        slot["arm"],
                        slot["run_order"],
                        slot["fixed_seed"],
                        packet_hash,
                    )
                )
            lines.extend(
                (
                    "[2026-11-06T00:00:00Z] [driver] step=%d start label=%s character=Acheron input=%s"
                    % (index, step_id, utterance),
                    "[2026-11-06T00:00:01Z] [game_output] type=output author=Narrator content=%s"
                    % content,
                    "[2026-11-06T00:00:02Z] [driver] step=%d done label=%s completed in 1.00s quiet-window=1.0 timeout=no new_game_output=1"
                    % (index, step_id),
                )
            )
        return "\n".join(lines) + "\n"

    def _build(self, review_run_id: str, row_ids: tuple[str, ...]) -> Path:
        bundles = [self._create_bundle(row_id) for row_id in row_ids]
        return create_review_packet(
            review_run_id,
            bundles,
            sp3_run_id=self.sp3_run_id,
            ledger_root=self.ledger_root,
            output_root=self.output_root,
            key_root=self.key_root,
        )

    def test_packet_is_blinded_ratings_are_blank_and_key_requires_owner_lock(self) -> None:
        review_run_id = "review-" + uuid.uuid4().hex[:12]
        packet_dir = self._build(review_run_id, ("E01", "E02"))
        key_dir = self.key_root / review_run_id
        self.assertTrue((key_dir / CONDITION_KEY_FILENAME).is_file())
        self.assertFalse((packet_dir / CONDITION_KEY_FILENAME).exists())
        self.assertNotEqual(packet_dir.resolve(), key_dir.resolve())

        packet_files = sorted(
            path for path in packet_dir.glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}\.txt", path.name)
        )
        self.assertEqual(len(packet_files), 2)
        response_ids = [path.stem for path in packet_files]
        self.assertEqual(len(set(response_ids)), 2)
        for response_id in response_ids:
            self.assertRegex(response_id, re.compile(r"^[0-9a-f]{32}$"))
        packet_manifest = json.loads(
            (packet_dir / "manifest.json").read_text(encoding="ascii")
        )
        self.assertEqual(set(packet_manifest["packet_order"]), set(response_ids))

        transcript_text = "\n".join(
            path.read_text(encoding="ascii").split("Transcript:\n", 1)[1]
            for path in packet_files
        )
        for hidden in (
            "E01",
            "E02",
            "arm=A",
            "arm=B",
            "row_order=",
            "seed=5101",
            "openrouter-private",
            "openai/private-hidden-model",
            "provider-private",
            "route-hidden",
            "fallback=yes",
            "packet_sha256",
            "packet_hash",
            "short-secret",
            "answer_key=xy",
            "MPV2_F_TAVERN_BAR",
            "interior_e1_e4",
            "THE_SECRET_FIXTURE_ANSWER_KEY",
        ):
            self.assertNotIn(hidden.casefold(), transcript_text.casefold())
        self.assertIsNone(re.search(r"(?i)\b[0-9a-f]{64}\b", transcript_text))
        disclosure = (packet_dir / DISCLOSURE_FILENAME).read_text("ascii")
        self.assertNotIn("Blinding is full", disclosure)
        self.assertIn("Blinding is partial", disclosure)
        self.assertIn("ASCII sketches can reveal", disclosure)

        with (packet_dir / RATINGS_FILENAME).open("r", encoding="ascii", newline="") as source:
            ratings = list(csv.DictReader(source))
        self.assertEqual({row["response_id"] for row in ratings}, set(response_ids))
        for row in ratings:
            self.assertTrue(all(row[column] == "" for column in _RATING_COLUMNS))
            self.assertEqual(row["not_rateable"], "")

        with self.assertRaisesRegex(ReviewPacketError, "rating-lock"):
            release_condition_key(
                review_run_id, output_root=self.output_root, key_root=self.key_root
            )
        self.assertFalse((packet_dir / RATING_LOCK_FILENAME).exists())

        ratings_bytes = (packet_dir / RATINGS_FILENAME).read_bytes()
        lock = {
            "schema_version": 1,
            "review_run_id": review_run_id,
            "reviewer_label": "owner-reviewer",
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "ratings_sha256": hashlib.sha256(ratings_bytes).hexdigest(),
        }
        (packet_dir / RATING_LOCK_FILENAME).write_text(
            json.dumps(lock, sort_keys=True), encoding="ascii"
        )
        key = release_condition_key(
            review_run_id, output_root=self.output_root, key_root=self.key_root
        )
        self.assertEqual(key["review_run_id"], review_run_id)
        self.assertEqual(len(key["response_units"]), 2)
        for unit in key["response_units"]:
            self.assertTrue(
                {"response_id", "row", "arm", "party", "seed", "row_order", "turn"}
                .issubset(unit)
            )
            self.assertEqual(unit["turn"]["expected_ordinals"], list(range(1, 9)))
            self.assertEqual(unit["turn"]["observed_ordinals"], list(range(1, 9)))

    def test_opaque_response_id_may_contain_seed_and_row_fragments(self) -> None:
        row_id = "E01"
        slot = self._slot(row_id)
        seed_fragment = str(slot["fixed_seed"])
        opaque_id = (seed_fragment + row_id.lower() + "a" * 32)[:32]
        self.assertRegex(opaque_id, re.compile(r"^[0-9a-f]{32}$"))

        review_run_id = "opaque-fragments-" + uuid.uuid4().hex[:8]
        with patch(
            "scripts.mapping_pilot.review.secrets.token_hex", return_value=opaque_id
        ):
            packet_dir = self._build(review_run_id, (row_id,))

        packet_path = packet_dir / (opaque_id + ".txt")
        packet_text = packet_path.read_text(encoding="ascii")
        header, transcript = packet_text.split("Transcript:\n", 1)
        self.assertIn("Response ID: " + opaque_id, header)
        self.assertNotIn(seed_fragment, transcript)
        self.assertNotIn(row_id, transcript)

    def test_genuine_seed_leak_in_scrubbed_transcript_is_rejected(self) -> None:
        row_id = "E01"
        seed = self._slot(row_id)["fixed_seed"]
        review_run_id = "seed-leak-" + uuid.uuid4().hex[:8]
        with (
            patch(
                "scripts.mapping_pilot.review.secrets.token_hex",
                return_value="a" * 32,
            ),
            patch(
                "scripts.mapping_pilot.review._scrub_transcript",
                return_value="Narrator: seed=%s" % seed,
            ),
        ):
            with self.assertRaisesRegex(
                ReviewPacketError, "transcript could not be safely blinded"
            ):
                self._build(review_run_id, (row_id,))

    def test_generated_response_id_must_be_opaque_32_hex(self) -> None:
        review_run_id = "invalid-response-id-" + uuid.uuid4().hex[:8]
        error_message = "generated response ID is not an opaque 32-hex token"
        with patch(
            "scripts.mapping_pilot.review.secrets.token_hex", return_value="not-opaque"
        ):
            with self.assertRaisesRegex(
                ReviewPacketError, error_message
            ):
                self._build(review_run_id, ("E01",))

    def test_missing_truncated_and_degraded_responses_are_not_rateable(self) -> None:
        row_states = (("E01", "missing"), ("E02", "truncated"), ("E03", "degraded"))
        bundles = [
            self._create_bundle(row_id, status="BLOCKED", response_state=response_state)
            for row_id, response_state in row_states
        ]
        review_run_id = "not-rateable-" + uuid.uuid4().hex[:10]
        packet_dir = create_review_packet(
            review_run_id,
            bundles,
            sp3_run_id=self.sp3_run_id,
            ledger_root=self.ledger_root,
            output_root=self.output_root,
            key_root=self.key_root,
        )
        with (packet_dir / RATINGS_FILENAME).open("r", encoding="ascii", newline="") as source:
            ratings = list(csv.DictReader(source))
        self.assertEqual(len(ratings), 3)
        for row in ratings:
            self.assertEqual(row["not_rateable"], "not rateable")
            self.assertTrue(row["not_rateable_reason"])
            self.assertTrue(all(row[column] == "" for column in _RATING_COLUMNS))

    def test_packet_and_key_roots_cannot_collide(self) -> None:
        bundle = self._create_bundle("E01")
        with self.assertRaisesRegex(ReviewPacketError, "must be separate"):
            create_review_packet(
                "root-collision-" + uuid.uuid4().hex[:8],
                [bundle],
                sp3_run_id=self.sp3_run_id,
                ledger_root=self.ledger_root,
                output_root=self.output_root,
                key_root=self.output_root,
            )

    def test_packet_builder_requires_pre_content_review_marker(self) -> None:
        bundle = self._create_bundle("E01", pre_reviewed=False)
        with self.assertRaisesRegex(ReviewPacketError, "pre-content classification"):
            create_review_packet(
                "unclassified-" + uuid.uuid4().hex[:8],
                [bundle],
                sp3_run_id=self.sp3_run_id,
                ledger_root=self.ledger_root,
                output_root=self.output_root,
                key_root=self.key_root,
            )

    def test_rating_lock_hash_must_match_owner_locked_sheet(self) -> None:
        review_run_id = "lock-hash-" + uuid.uuid4().hex[:8]
        packet_dir = self._build(review_run_id, ("E01",))
        lock = {
            "schema_version": 1,
            "review_run_id": review_run_id,
            "reviewer_label": "owner-reviewer",
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "ratings_sha256": "0" * 64,
        }
        (packet_dir / RATING_LOCK_FILENAME).write_text(
            json.dumps(lock, sort_keys=True), encoding="ascii"
        )
        with self.assertRaisesRegex(ReviewPacketError, "does not match"):
            release_condition_key(
                review_run_id, output_root=self.output_root, key_root=self.key_root
            )

    def test_rating_lock_requires_reviewer_and_timezone_timestamp(self) -> None:
        review_run_id = "lock-fields-" + uuid.uuid4().hex[:8]
        packet_dir = self._build(review_run_id, ("E01",))
        ratings_hash = hashlib.sha256(
            (packet_dir / RATINGS_FILENAME).read_bytes()
        ).hexdigest()
        invalid_locks = (
            {
                "schema_version": 1,
                "review_run_id": review_run_id,
                "reviewer_label": "  ",
                "locked_at": datetime.now(timezone.utc).isoformat(),
                "ratings_sha256": ratings_hash,
            },
            {
                "schema_version": 1,
                "review_run_id": review_run_id,
                "reviewer_label": "owner-reviewer",
                "locked_at": "2026-11-06T00:00:00",
                "ratings_sha256": ratings_hash,
            },
        )
        for lock in invalid_locks:
            with self.subTest(lock=lock):
                (packet_dir / RATING_LOCK_FILENAME).write_text(
                    json.dumps(lock, sort_keys=True), encoding="ascii"
                )
                with self.assertRaises(ReviewPacketError):
                    release_condition_key(
                        review_run_id,
                        output_root=self.output_root,
                        key_root=self.key_root,
                    )


if __name__ == "__main__":
    unittest.main()
