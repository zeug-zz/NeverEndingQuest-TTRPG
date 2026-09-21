# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free contracts for the adaptation output safety boundary."""

from __future__ import annotations

import io
import json
import logging
import unittest

from utils.toolkit_adaptation_output_safety import (
    AdaptationOutputSafety,
    AdaptationOutputSafetyFilter,
    is_adaptation_output_active,
    project_diagnostic,
    project_gui_payload,
    project_progress,
    project_safe_event,
)


class AdaptationOutputSafetyTest(unittest.TestCase):
    def test_projection_is_deterministic_ascii_and_bounded(self) -> None:
        payload = {
            "phase": "adaptation_validation", "status": "blocked",
            "code": "monster_closure_unresolved", "message": "A useful status",
            "count": 999999999999, "attempt": 999999999, "revision": 999,
        }
        first = project_progress(payload)
        second = project_progress(payload)
        self.assertEqual(first, second)
        encoded = json.dumps(first, ensure_ascii=True, sort_keys=True)
        self.assertLessEqual(len(encoded), 2_000)
        self.assertTrue(encoded.isascii())
        self.assertEqual(first["code"], "monster_closure_unresolved")
        self.assertLessEqual(first["count"], 2_000_000_000)
        self.assertLessEqual(first["revision"], 100)

    def test_sensitive_values_do_not_survive_any_projection(self) -> None:
        raw = {
            "phase": "adaptation_build", "status": "failed", "code": "provider_failed",
            "message": "SOURCE_SENTINEL PROMPT_SENTINEL PROVIDER_RESPONSE_SENTINEL "
                       "authorization=Bearer secret-token /Users/test/project/lock",
        }
        for projection in (project_progress(raw), project_gui_payload(raw), project_diagnostic(raw)):
            encoded = json.dumps(projection, ensure_ascii=True, sort_keys=True)
            for sentinel in ("SOURCE_SENTINEL", "PROMPT_SENTINEL", "PROVIDER_RESPONSE_SENTINEL", "secret-token", "/Users/test"):
                self.assertNotIn(sentinel, encoded)
            self.assertFalse(projection["raw_provider_payload_exposed"])

    def test_allowed_fields_and_terminal_code_are_preserved(self) -> None:
        result = project_safe_event(
            phase="adaptation_monster_guardrail", status="blocked",
            code="monster_closure_unresolved", message="closure failed",
            count=2, percentage=50, attempt=1, revision=0,
        )
        self.assertEqual(result["phase"], "adaptation_build")
        self.assertEqual(result["code"], "monster_closure_unresolved")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["revision"], 0)
        self.assertEqual(set(result), {
            "contract_version", "event_type", "phase", "status", "code", "message",
            "count", "percentage", "attempt", "revision", "raw_provider_payload_exposed",
        })

    def test_callback_gui_and_persistence_seams_receive_safe_shapes(self) -> None:
        progress = []
        gui = []
        with AdaptationOutputSafety(
            phase="adaptation_validation", status="running",
            progress_callback=progress.append, gui_callback=gui.append,
        ) as scope:
            self.assertTrue(is_adaptation_output_active())
            event = scope.emit({"code": "monster_closure_unresolved", "message": "PROMPT_SENTINEL"})
            diagnostic = scope.diagnostic({"code": "failure", "message": "safe"})
        self.assertFalse(is_adaptation_output_active())
        self.assertEqual(progress, [event])
        self.assertEqual(gui, [event])
        self.assertEqual(diagnostic["event_type"], "adaptation_diagnostic")
        self.assertEqual(diagnostic["message"], "safe")

    def test_stdout_and_stderr_context_are_bounded(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            with AdaptationOutputSafety(
                phase="adaptation_build", status="running", redirect_streams=True,
            ):
                print("SOURCE_SENTINEL /Users/test/lock")
                import sys
                print("PROVIDER_RESPONSE_SENTINEL", file=sys.stderr)
        combined = output.getvalue() + error.getvalue()
        self.assertNotIn("SOURCE_SENTINEL", combined)
        self.assertNotIn("PROVIDER_RESPONSE_SENTINEL", combined)
        self.assertIn("captured_output_suppressed", combined)

    def test_logger_filter_is_scoped_and_legacy_scope_is_inactive(self) -> None:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "SOURCE_SENTINEL", (), None)
        self.assertTrue(AdaptationOutputSafetyFilter().filter(record))
        self.assertEqual(record.msg, "SOURCE_SENTINEL")
        with AdaptationOutputSafety(phase="adaptation_build"):
            record = logging.LogRecord("test", logging.ERROR, __file__, 1, "SOURCE_SENTINEL", (), None)
            self.assertTrue(AdaptationOutputSafetyFilter().filter(record))
            self.assertNotIn("SOURCE_SENTINEL", str(record.msg))
            self.assertTrue(str(record.msg).isascii())


if __name__ == "__main__":
    unittest.main()
