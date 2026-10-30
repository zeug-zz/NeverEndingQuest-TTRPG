# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Latency Trace Tests - Provider-free writer coverage.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import io
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import model_config
from utils import combat_latency_trace
from scripts.combat_latency_fixtures import (
    ONE_PC_ENEMY_NAME,
    ONE_PC_NAME,
    build_mp_fixture,
    build_one_pc_fixture,
    run_mp_fixture,
    run_one_pc_fixture,
)
from scripts import combat_latency_report


class CombatLatencyTraceTests(unittest.TestCase):
    def test_disabled_gate_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False):
                self.assertFalse(combat_latency_trace.emit_trace_event("stage", path=path))
            self.assertFalse(path.exists())

    def test_enabled_writer_appends_jsonl(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "nested" / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(
                    combat_latency_trace.emit_trace_event(
                        "decision",
                        path=path,
                        turn=2,
                        mode="mp",
                    )
                )
            record = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual(record["event_type"], "decision")
            self.assertEqual(record["turn"], 2)

    def test_concurrent_emits_leave_each_line_intact(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                threads = [
                    threading.Thread(
                        target=lambda value=value: [
                            combat_latency_trace.emit_trace_event(
                                "stage", path=path, sequence=value
                            )
                            for _ in range(20)
                        ]
                    )
                    for value in range(8)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            lines = path.read_text(encoding="ascii").splitlines()
            self.assertEqual(len(lines), 160)
            for line in lines:
                self.assertEqual(json.loads(line)["event_type"], "stage")

    def test_unwritable_destination_fails_open(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                self.assertFalse(
                    combat_latency_trace.emit_trace_event(
                        "file_operation", path=Path(directory), category="read"
                    )
                )

    def test_decision_event_fields_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(
                    combat_latency_trace.emit_trace_event(
                        "decision",
                        path=path,
                        decision_point="pc_phase_parser",
                        decision_source="deterministic",
                        decision_latency_ms=1.5,
                        provider_call_avoided=True,
                    )
                )
            record = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual(record["decision_source"], "deterministic")
            self.assertTrue(record["provider_call_avoided"])

    def test_trace_decision_sources_and_latency(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                for source in ("deterministic", "llm_fallback", "jev"):
                    self.assertTrue(
                        combat_latency_trace.trace_decision(
                            "combat_command_fast_path",
                            source,
                            time.perf_counter(),
                            source == "deterministic",
                        )
                    )
            records = [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]
            self.assertEqual(
                [record["decision_source"] for record in records],
                ["deterministic", "llm_fallback", "jev"],
            )
            self.assertTrue(all(record["decision_latency_ms"] >= 0 for record in records))

    def test_invalid_decision_source_emits_no_record(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertFalse(
                    combat_latency_trace.trace_decision(
                        "pc_phase_parser", "invalid", time.perf_counter(), False
                    )
                )
            self.assertFalse(path.exists())

    def test_disabled_decision_gate_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertFalse(
                    combat_latency_trace.trace_decision(
                        "pc_phase_parser", "deterministic", time.perf_counter(), True
                    )
                )
            self.assertFalse(path.exists())

    def test_stage_provider_compression_and_file_helpers(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"

            class Usage:
                prompt_tokens = 11
                completion_tokens = 7
                total_tokens = 18

            class Response:
                usage = Usage()

            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                started_at = time.perf_counter()
                self.assertTrue(combat_latency_trace.trace_stage("turn_start", started_at))
                self.assertTrue(combat_latency_trace.trace_provider_call("combat_main", started_at, Response()))
                self.assertTrue(combat_latency_trace.trace_compression_event("compress", True, False, started_at))
                self.assertTrue(combat_latency_trace.trace_file_operation("read", "encounter_load"))

            records = [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]
            self.assertEqual([record["event_type"] for record in records], ["stage", "provider", "compression", "file_operation"])
            self.assertEqual(records[1]["total_tokens"], 18)
            self.assertTrue(records[2]["call_occurred"])
            self.assertEqual(records[3]["category"], "read")

    def test_provider_helper_preserves_missing_usage(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"

            class ResponseWithoutUsage:
                pass

            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(
                    combat_latency_trace.trace_provider_call(
                        "combat_validation", time.perf_counter(), ResponseWithoutUsage()
                    )
                )
            record = json.loads(path.read_text(encoding="ascii"))
            self.assertNotIn("prompt_tokens", record)
            self.assertNotIn("completion_tokens", record)
            self.assertNotIn("total_tokens", record)

    def test_disabled_helpers_do_no_usage_extraction_or_write(self) -> None:
        class ExplodingResponse:
            @property
            def usage(self):
                raise AssertionError("usage must not be inspected while tracing is disabled")

        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertFalse(combat_latency_trace.trace_stage("turn_end", time.perf_counter()))
                self.assertFalse(combat_latency_trace.trace_provider_call("combat_main", time.perf_counter(), ExplodingResponse()))
                self.assertFalse(combat_latency_trace.trace_compression_event("compress", False, True))
                self.assertFalse(combat_latency_trace.trace_file_operation("write", "encounter_save"))
            self.assertFalse(path.exists())

    def test_context_is_included_and_event_fields_win(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(combat_latency_trace.set_trace_context(combat_round=2, phase="PC_PHASE", mode="mp"))
                self.assertTrue(combat_latency_trace.trace_stage("turn_start", time.perf_counter(), mode="one_pc"))
                self.assertTrue(combat_latency_trace.trace_provider_call("combat_main", time.perf_counter()))
                self.assertTrue(combat_latency_trace.trace_compression_event("compress", False, True))
                records = [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]
                for record in records:
                    self.assertEqual(record["combat_round"], 2)
                    self.assertEqual(record["phase"], "PC_PHASE")
                self.assertEqual(records[0]["mode"], "one_pc")

    def test_context_overwrite_and_bounded_values(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(combat_latency_trace.set_trace_context(combat_round=1, mode="one_pc"))
                self.assertTrue(combat_latency_trace.set_trace_context(combat_round=3, mode="mp", detail="x" * 1000))
                self.assertTrue(combat_latency_trace.trace_stage("turn_start", time.perf_counter()))
                record = json.loads(path.read_text(encoding="ascii"))
                self.assertEqual(record["combat_round"], 3)
                self.assertEqual(record["mode"], "mp")
                self.assertLessEqual(len(record["detail"]), combat_latency_trace.MAX_VALUE_CHARS)

    def test_disabled_context_does_no_work_and_does_not_leak(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertFalse(combat_latency_trace.set_trace_context(combat_round=99, mode="mp"))
                self.assertFalse(combat_latency_trace.trace_stage("turn_end", time.perf_counter()))
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                combat_latency_trace, "DEFAULT_TRACE_PATH", path
            ):
                self.assertTrue(combat_latency_trace.set_trace_context())
                self.assertTrue(combat_latency_trace.trace_stage("turn_start", time.perf_counter()))
                record = json.loads(path.read_text(encoding="ascii"))
                self.assertNotIn("combat_round", record)
                self.assertNotIn("mode", record)

    def test_mp_fixture_tracing_enabled_captures_invariants(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            fixture = build_mp_fixture()
            trace_path = Path(directory) / "mp-trace.jsonl"
            try:
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
                ):
                    result = run_mp_fixture(fixture)

                self.assertEqual(result["rounds_completed"], 3)
                self.assertEqual(result["enemy_batches"], 1)
                self.assertEqual(result["pc_names"], ["Acheron", "Merisiel", "Kira", "Vitreol"])
                self.assertEqual(len(set(name.lower() for name in result["pc_names"])), 4)
                self.assertEqual(len(result["queue_names"]), 6)
                self.assertTrue(trace_path.exists())

                records = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
                self.assertTrue(records)
                self.assertTrue(all("event_type" in record for record in records))
                decisions = [record for record in records if record["event_type"] == "decision"]
                self.assertTrue(
                    any(
                        record.get("decision_point") == "combat_command_fast_path"
                        and record.get("decision_source") in ("deterministic", "llm_fallback")
                        for record in decisions
                    )
                )
                self.assertTrue(any(record["event_type"] == "file_operation" for record in records))
                compression_records = [
                    record
                    for record in records
                    if record["event_type"] == "compression"
                    and record.get("site") == "combat_message_compressor"
                ]
                self.assertTrue(compression_records)
                self.assertTrue(
                    any(record.get("cache_hit") is False and record.get("call_occurred") is True
                        for record in compression_records)
                )
                self.assertTrue(
                    any(record.get("cache_hit") is True and record.get("call_occurred") is False
                        for record in compression_records)
                )
            finally:
                fixture["tempdir"].cleanup()

    def test_mp_fixture_tracing_disabled_has_same_outcome_without_trace(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            enabled_fixture = build_mp_fixture()
            fixture = build_mp_fixture()
            enabled_trace_path = Path(directory) / "mp-trace-enabled-reference.jsonl"
            trace_path = Path(directory) / "mp-trace-disabled.jsonl"
            try:
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", enabled_trace_path
                ):
                    enabled_result = run_mp_fixture(enabled_fixture)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
                ):
                    result = run_mp_fixture(fixture)

                self.assertFalse(trace_path.exists())
                self.assertEqual(result, enabled_result)
                self.assertEqual(result["rounds_completed"], 3)
                self.assertEqual(result["enemy_batches"], 1)
                self.assertEqual(result["pc_names"], ["Acheron", "Merisiel", "Kira", "Vitreol"])
                self.assertEqual(len(set(name.lower() for name in result["pc_names"])), 4)
                self.assertEqual(len(result["queue_names"]), 6)
            finally:
                enabled_fixture["tempdir"].cleanup()
                fixture["tempdir"].cleanup()

    def test_one_pc_fixture_tracing_enabled_captures_invariants(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            fixture = build_one_pc_fixture()
            trace_path = Path(directory) / "one-pc-trace.jsonl"
            try:
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
                ):
                    result = run_one_pc_fixture(fixture)

                self.assertEqual(result["mode"], "one_pc")
                self.assertEqual(result["rounds_completed"], 1)
                self.assertEqual(result["pc_names"], [ONE_PC_NAME])
                self.assertEqual(result["enemy_names"], [ONE_PC_ENEMY_NAME])
                self.assertEqual(result["queue_names"].count(ONE_PC_NAME), 1)
                self.assertEqual(result["queue_names"].count(ONE_PC_ENEMY_NAME), 1)
                self.assertTrue(result["pc_phase_complete"])
                self.assertTrue(result["enemy_phase_complete"])
                self.assertTrue(trace_path.exists())

                records = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
                self.assertTrue(records)
                self.assertTrue(any(record["event_type"] == "decision" for record in records))
                self.assertTrue(any(record["event_type"] == "file_operation" for record in records))
            finally:
                fixture["tempdir"].cleanup()

    def test_one_pc_fixture_tracing_disabled_has_same_outcome_without_trace(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            enabled_fixture = build_one_pc_fixture()
            fixture = build_one_pc_fixture()
            enabled_trace_path = Path(directory) / "one-pc-trace-enabled-reference.jsonl"
            trace_path = Path(directory) / "one-pc-trace-disabled.jsonl"
            try:
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", enabled_trace_path
                ):
                    enabled_result = run_one_pc_fixture(enabled_fixture)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", False), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
                ):
                    result = run_one_pc_fixture(fixture)

                self.assertFalse(trace_path.exists())
                self.assertEqual(result, enabled_result)
                self.assertEqual(result["rounds_completed"], 1)
                self.assertEqual(result["pc_names"], [ONE_PC_NAME])
                self.assertEqual(result["enemy_names"], [ONE_PC_ENEMY_NAME])
            finally:
                enabled_fixture["tempdir"].cleanup()
                fixture["tempdir"].cleanup()


class CombatLatencyReportTests(unittest.TestCase):
    def _write_records(self, directory: str, records: list) -> Path:
        path = Path(directory) / "trace.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="ascii")
        return path

    def test_report_aggregates_observed_measurements_and_missing_tokens(self) -> None:
        records = [
            {"event_type": "stage", "stage": "turn", "elapsed_ms": 10, "fixture": "synthetic", "mode": "mp"},
            {"event_type": "stage", "stage": "turn", "elapsed_ms": 30, "fixture": "synthetic", "mode": "mp"},
            {"event_type": "provider", "site": "combat_main", "elapsed_ms": 20, "prompt_tokens": 4, "total_tokens": 9, "fixture": "synthetic", "mode": "mp"},
            {"event_type": "provider", "site": "combat_main", "elapsed_ms": 40, "fixture": "synthetic", "mode": "mp"},
            {"event_type": "compression", "site": "compress", "call_occurred": True, "cache_hit": False, "elapsed_ms": 5},
            {"event_type": "compression", "site": "compress", "call_occurred": False, "cache_hit": True},
            {"event_type": "file_operation", "site": "encounter", "category": "read"},
            {"event_type": "file_operation", "site": "encounter", "category": "write"},
            {"event_type": "decision", "decision_point": "pc_phase_parser", "decision_source": "deterministic", "decision_latency_ms": 2, "provider_call_avoided": True},
            {"event_type": "decision", "decision_point": "combat_command_fast_path", "decision_source": "llm_fallback", "decision_latency_ms": 8, "provider_call_avoided": False},
        ]
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            report = combat_latency_report.build_report(self._write_records(directory, records))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["stages"]["turn"]["count"], 2)
        self.assertEqual(report["providers"]["combat_main"]["calls"], 2)
        self.assertEqual(report["providers"]["combat_main"]["token_sums"], {"prompt_tokens": 4, "total_tokens": 9})
        self.assertEqual(report["compression"]["compress"]["cache_hits"], 1)
        self.assertEqual(report["file_operations"]["encounter"], {"read": 1, "write": 1})
        self.assertEqual(report["nl_fast_path"], {"hit": 1, "miss": 1})

    def test_report_counts_malformed_lines_without_aborting(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text('{"event_type":"stage","stage":"x","elapsed_ms":1}\nnot json\n', encoding="ascii")
            report = combat_latency_report.build_report(path)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["input"]["total_records"], 1)
        self.assertEqual(report["input"]["malformed_count"], 1)
        self.assertEqual(report["input"]["malformed_line_numbers"], [2])

    def test_report_cli_missing_file_exits_two_with_bounded_diagnostic(self) -> None:
        result = subprocess.run([sys.executable, "scripts/combat_latency_report.py", "--trace", "tmp/does-not-exist.jsonl"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertLess(len(result.stderr), 1000)
        self.assertIn("unable to read", result.stderr)

    def test_empty_trace_is_degraded_but_successful(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text("", encoding="ascii")
            report = combat_latency_report.build_report(path)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["input"]["total_records"], 0)

    def test_report_module_imports_no_runtime_or_provider_modules(self) -> None:
        source = Path("scripts/combat_latency_report.py").read_text(encoding="ascii")
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("combat_manager", source)
        self.assertNotIn("combat_latency_trace", source)

    def test_report_runs_against_mp_fixture_trace(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as directory:
            fixture = build_mp_fixture()
            trace_path = Path(directory) / "fixture-trace.jsonl"
            try:
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), patch.object(
                    combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path
                ):
                    run_mp_fixture(fixture)
                report = combat_latency_report.build_report(trace_path)
            finally:
                fixture["tempdir"].cleanup()
        self.assertIn("combat_command_fast_path/deterministic", report["decisions"])
        self.assertIn("combat_latency_baseline", report["input"]["fixtures"])


if __name__ == "__main__":
    unittest.main()
