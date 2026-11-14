# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic contract tests for the offline live-gate comparison utility."""

from __future__ import annotations

import argparse
import http.client
import io
import json
import socket
import subprocess
import sys
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import live_gate_preflight_comparison as comparison


MAIN_SHA = "a" * 40
EXPECTED_NAMEERRORS = set(comparison.EXPECTED_NAMEERROR_ROWS)


class LiveGatePreflightComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.row_source = comparison.load_frozen_row_source()

    def _snapshot(
        self,
        source_sha: str,
        *,
        role: str,
        nameerrors: set[str] | None = None,
        other_errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        nameerrors = nameerrors or set()
        other_errors = other_errors or {}
        rows = []
        for row_id in self.row_source.planned_row_ids:
            exception_type = (
                "NameError"
                if row_id in nameerrors
                else other_errors.get(row_id)
            )
            outcome = "exception" if exception_type is not None else "completed"
            rows.append(
                {
                    "row_id": row_id,
                    "outcome": outcome,
                    "exception_type": exception_type,
                    "outcome_sha256": comparison.row_outcome_sha256(
                        source_sha=source_sha,
                        row_source_sha256=self.row_source.counterbalance_sha256,
                        row_id=row_id,
                        outcome=outcome,
                        exception_type=exception_type,
                    ),
                    "exception_message": "ignored\r\t\x7f API_KEY=not-output",
                    "credential": "not-output",
                }
            )
        return {
            "schema_version": 1,
            "snapshot_type": comparison.SNAPSHOT_TYPE,
            "snapshot_role": role,
            "source_sha": source_sha,
            "row_source_sha256": self.row_source.counterbalance_sha256,
            "planned_row_ids": list(self.row_source.planned_row_ids),
            "replacement_only_row_ids": list(self.row_source.reserve_row_ids),
            "replacement_only_rows_activated": [],
            "row_results": rows,
            "secret_metadata": "ignored\r\t\x7f PASSWORD=not-output",
        }

    @staticmethod
    def _encode_snapshot(document: dict[str, Any]) -> bytes:
        return json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    def _boundaries(
        self,
        *,
        old_snapshot: dict[str, Any] | None = None,
        main_snapshot: dict[str, Any] | None = None,
        profile_coverage: dict[str, Any] | None = None,
        missing_commit_sha: str | None = None,
        missing_sha: str | None = None,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        counts = {"rows": 0, "profiles": 0, "commits": 0, "snapshots": 0}
        coverage = profile_coverage if profile_coverage is not None else {
            "structural_row_coverage_complete": True,
            "planned_row_count": 26,
            "planned_row_ids": list(self.row_source.planned_row_ids),
            "fixture_party_pair_count": 8,
            "replacement_only_rows_activated": [],
            "measured_lifecycle_complete": True,
            "unverified_row_ids": [],
        }
        documents = {
            comparison.OLD_CONTROL_SHA: (
                old_snapshot
                if old_snapshot is not None
                else self._snapshot(
                    comparison.OLD_CONTROL_SHA,
                    role="pre-105-control",
                    nameerrors=EXPECTED_NAMEERRORS,
                )
            ),
            MAIN_SHA: (
                main_snapshot
                if main_snapshot is not None
                else self._snapshot(MAIN_SHA, role="frozen-origin-main")
            ),
        }

        def load_rows() -> comparison.FrozenRowSource:
            counts["rows"] += 1
            return self.row_source

        def load_profiles(source_sha: str) -> dict[str, Any]:
            counts["profiles"] += 1
            self.assertEqual(source_sha, MAIN_SHA)
            return coverage

        def check_commit(source_sha: str) -> bool:
            counts["commits"] += 1
            return source_sha != missing_commit_sha

        def read_snapshot(source_sha: str) -> bytes:
            counts["snapshots"] += 1
            if source_sha == missing_sha or source_sha not in documents:
                raise FileNotFoundError(source_sha)
            return self._encode_snapshot(documents[source_sha])

        return counts, {
            "row_source_loader": load_rows,
            "profile_coverage_loader": load_profiles,
            "commit_availability_loader": check_commit,
            "snapshot_reader": read_snapshot,
        }

    def _compare(self, boundaries: dict[str, Any]) -> dict[str, Any]:
        return comparison.compare_local_snapshots(MAIN_SHA, **boundaries)

    def test_authoritative_source_is_exactly_26_planned_and_four_reserves(self) -> None:
        self.assertEqual(len(self.row_source.planned_row_ids), 26)
        self.assertEqual(self.row_source.reserve_row_ids, comparison.EXPECTED_RESERVE_ROWS)
        self.assertEqual(self.row_source.planned_row_ids[5], "E06")
        self.assertEqual(
            self.row_source.planned_row_ids[12:18],
            ("E13", "E14", "E15", "E16", "E17", "E18"),
        )
        self.assertRegex(self.row_source.counterbalance_sha256, r"^[0-9a-f]{64}$")

    def test_unreconciled_snapshot_claims_are_diagnostic_only_and_never_write(self) -> None:
        counts, boundaries = self._boundaries()
        forbidden_effects = dict.fromkeys(
            ("host", "provider", "ports", "network", "pilot_evidence"),
            0,
        )

        def tripwire(effect: str) -> Any:
            def reject(*_args: Any, **_kwargs: Any) -> None:
                forbidden_effects[effect] += 1
                raise AssertionError(effect + " boundary used")

            return reject

        with (
            mock.patch.object(socket, "socket", side_effect=tripwire("ports")),
            mock.patch.object(
                socket, "create_connection", side_effect=tripwire("ports")
            ),
            mock.patch.object(subprocess, "Popen", side_effect=tripwire("host")),
            mock.patch.object(subprocess, "run", side_effect=tripwire("host")),
            mock.patch.object(
                urllib.request, "urlopen", side_effect=tripwire("network")
            ),
            mock.patch.object(
                http.client.HTTPConnection,
                "connect",
                side_effect=tripwire("provider"),
            ),
            mock.patch.object(
                Path, "write_bytes", side_effect=tripwire("pilot_evidence")
            ),
            mock.patch.object(
                Path, "write_text", side_effect=tripwire("pilot_evidence")
            ),
            mock.patch.object(Path, "mkdir", side_effect=tripwire("pilot_evidence")),
        ):
            report = self._compare(boundaries)

        self.assertEqual(
            counts, {"rows": 1, "profiles": 1, "commits": 2, "snapshots": 2}
        )
        self.assertEqual(forbidden_effects, dict.fromkeys(forbidden_effects, 0))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["comparison_verified"])
        self.assertEqual(
            report["error_code"],
            "retained_source_execution_verification_missing",
        )
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["host_execution_verified"])
        self.assertEqual(report["retained_source_verification"], "MISSING")
        self.assertEqual(
            report["guarded_per_source_run_reconciliation"], "MISSING"
        )
        self.assertEqual(report["old_control_source_sha"], comparison.OLD_CONTROL_SHA)
        self.assertEqual(report["frozen_origin_main_sha"], MAIN_SHA)
        self.assertEqual(
            report["snapshot_diagnostics"][
                "claimed_old_control_nameerror_rows"
            ],
            list(comparison.EXPECTED_NAMEERROR_ROWS),
        )
        self.assertEqual(
            report["snapshot_diagnostics"]["claimed_frozen_main_nameerror_rows"],
            [],
        )
        self.assertEqual(report["planned_row_count"], 26)
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["live_gate_pass"])
        self.assertFalse(report["pilot_evidence_written"])
        rendered = json.dumps(report, ensure_ascii=True)
        for ignored in ("not-output", "PASSWORD", "API_KEY", "ignored", "\\r", "\\t"):
            self.assertNotIn(ignored, rendered)
        self.assertNotIn("PASS", rendered)
        self.assertNotIn("COMPARISON_VERIFIED", rendered)

    def test_missing_profile_measurement_blocks_before_opening_snapshots(self) -> None:
        coverage = {
            "structural_row_coverage_complete": True,
            "planned_row_count": 26,
            "planned_row_ids": list(self.row_source.planned_row_ids),
            "fixture_party_pair_count": 8,
            "replacement_only_rows_activated": [],
            "measured_lifecycle_complete": False,
            "unverified_row_ids": list(self.row_source.planned_row_ids),
        }
        counts, boundaries = self._boundaries(profile_coverage=coverage)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "lifecycle_profile_measurements_missing")
        self.assertEqual(
            counts, {"rows": 1, "profiles": 1, "commits": 0, "snapshots": 0}
        )

    def test_missing_local_source_snapshot_blocks(self) -> None:
        counts, boundaries = self._boundaries(missing_sha=MAIN_SHA)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "source_snapshot_unavailable_locally")
        self.assertEqual(counts["snapshots"], 2)

    def test_missing_local_commit_blocks_before_reading_snapshots(self) -> None:
        counts, boundaries = self._boundaries(missing_commit_sha=MAIN_SHA)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "source_commit_unavailable_locally")
        self.assertEqual(
            counts, {"rows": 1, "profiles": 1, "commits": 2, "snapshots": 0}
        )

    def test_default_commit_check_uses_local_cat_file_with_lazy_fetch_disabled(self) -> None:
        completed = SimpleNamespace(returncode=0)
        with mock.patch.object(
            comparison.subprocess, "run", return_value=completed
        ) as run:
            self.assertTrue(comparison._local_commit_available(MAIN_SHA))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["git", "cat-file", "-e", MAIN_SHA + "^{commit}"])
        self.assertEqual(kwargs["cwd"], comparison.PROJECT_ROOT)
        self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("GIT_DIR", kwargs["env"])
        self.assertNotIn("GIT_CONFIG_COUNT", kwargs["env"])
        self.assertEqual(kwargs["timeout"], 10.0)

    def test_missing_expected_old_nameerror_fails_closed(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS - {"E06"},
        )
        _counts, boundaries = self._boundaries(old_snapshot=old)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "expected_old_control_nameerror_missing")
        self.assertEqual(caught.exception.affected_rows, ("E06",))

    def test_current_main_nameerror_cannot_be_reported_as_verified(self) -> None:
        current = self._snapshot(
            MAIN_SHA,
            role="frozen-origin-main",
            nameerrors={"E06"},
        )
        _counts, boundaries = self._boundaries(main_snapshot=current)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "frozen_main_nameerror_present")
        self.assertEqual(caught.exception.affected_rows, ("E06",))

    def test_wrong_or_symbolic_comparison_sha_is_rejected_before_reading(self) -> None:
        for invalid_sha in (
            comparison.OLD_CONTROL_SHA,
            comparison.PLANNING_BASE_SHA,
            "HEAD",
            "not-a-full-sha",
        ):
            with self.subTest(invalid_sha=invalid_sha):
                counts, boundaries = self._boundaries()
                with self.assertRaises(comparison.ComparisonError):
                    comparison.compare_local_snapshots(invalid_sha, **boundaries)
                self.assertEqual(
                    counts,
                    {"rows": 0, "profiles": 0, "commits": 0, "snapshots": 0},
                )

    def test_tampered_row_outcome_digest_is_rejected(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS,
        )
        old["row_results"][5]["outcome"] = "completed"
        old["row_results"][5]["exception_type"] = None
        _counts, boundaries = self._boundaries(old_snapshot=old)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "source_snapshot_outcome_digest_mismatch")

    def test_non_nameerror_outcomes_are_omitted_from_blocked_diagnostics(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS,
            other_errors={"E01": "ImportError"},
        )
        old["row_results"][0]["exception_message"] = "TOKEN=do-not-print\r\t\x7f"
        current = self._snapshot(
            MAIN_SHA,
            role="frozen-origin-main",
            other_errors={"C08": "RuntimeError"},
        )
        current["row_results"][-1]["exception_message"] = "PASSWORD=do-not-print"
        _counts, boundaries = self._boundaries(
            old_snapshot=old,
            main_snapshot=current,
        )
        report = self._compare(boundaries)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["comparison_verified"])
        rendered = json.dumps(report, ensure_ascii=True)
        for omitted in (
            "ImportError",
            "RuntimeError",
            "do-not-print",
            "PASSWORD",
            "TOKEN",
        ):
            self.assertNotIn(omitted, rendered)

    def test_self_hashed_fabricated_snapshots_block_through_public_and_cli_paths(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS,
        )
        current = self._snapshot(MAIN_SHA, role="frozen-origin-main")
        _counts, boundaries = self._boundaries(
            old_snapshot=old,
            main_snapshot=current,
        )

        public_report = self._compare(boundaries)
        self.assertEqual(public_report["status"], "BLOCKED")
        self.assertFalse(public_report["comparison_verified"])
        self.assertEqual(
            public_report["error_code"],
            "retained_source_execution_verification_missing",
        )

        coverage = {
            "structural_row_coverage_complete": True,
            "planned_row_count": 26,
            "planned_row_ids": list(self.row_source.planned_row_ids),
            "fixture_party_pair_count": 8,
            "replacement_only_rows_activated": [],
            "measured_lifecycle_complete": True,
            "unverified_row_ids": [],
        }
        documents = {
            comparison.OLD_CONTROL_SHA: old,
            MAIN_SHA: current,
        }

        def fake_snapshot_reader(source_sha: str) -> bytes:
            return self._encode_snapshot(documents[source_sha])

        output = io.StringIO()
        with (
            mock.patch.object(
                comparison, "load_frozen_row_source", return_value=self.row_source
            ),
            mock.patch.object(
                comparison, "load_lifecycle_profile_coverage", return_value=coverage
            ),
            mock.patch.object(comparison, "_local_commit_available", return_value=True),
            mock.patch.object(
                comparison, "_local_snapshot_reader", side_effect=fake_snapshot_reader
            ),
            redirect_stdout(output),
        ):
            exit_code = comparison.main(["--main-sha", MAIN_SHA])

        cli_document = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(cli_document["status"], "BLOCKED")
        self.assertFalse(cli_document["comparison_verified"])
        self.assertFalse(cli_document["host_execution_verified"])
        self.assertEqual(cli_document["retained_source_verification"], "MISSING")
        self.assertEqual(
            cli_document["error_code"],
            "retained_source_execution_verification_missing",
        )
        self.assertNotIn("COMPARISON_VERIFIED", output.getvalue())

    def test_unexpected_nameerror_outside_target_rows_fails_closed(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS | {"C01"},
        )
        _counts, boundaries = self._boundaries(old_snapshot=old)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(
            caught.exception.code, "unexpected_nameerror_outside_target_rows"
        )
        self.assertEqual(caught.exception.affected_rows, ("C01",))

    def test_reserve_activation_and_incomplete_rows_are_rejected(self) -> None:
        old = self._snapshot(
            comparison.OLD_CONTROL_SHA,
            role="pre-105-control",
            nameerrors=EXPECTED_NAMEERRORS,
        )
        old["replacement_only_rows_activated"] = ["R01"]
        _counts, boundaries = self._boundaries(old_snapshot=old)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "source_snapshot_identity_or_coverage_invalid")

        old["replacement_only_rows_activated"] = []
        old["row_results"].pop()
        _counts, boundaries = self._boundaries(old_snapshot=old)
        with self.assertRaises(comparison.ComparisonError) as caught:
            self._compare(boundaries)
        self.assertEqual(caught.exception.code, "source_snapshot_identity_or_coverage_invalid")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--main-sha")
    arguments, unittest_arguments = parser.parse_known_args()
    if arguments.main_sha is not None:
        try:
            comparison._validate_main_sha(arguments.main_sha)
        except comparison.ComparisonError as exc:
            parser.error(exc.code)
        MAIN_SHA = arguments.main_sha
    unittest.main(argv=[sys.argv[0], *unittest_arguments])
