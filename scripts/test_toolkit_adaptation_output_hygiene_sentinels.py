# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Sentinel regression coverage for the adaptation output boundary.

This suite is provider-free.  Its late logger tests intentionally create
provider children and handlers after provider safety setup, which is the
failure mode that ordinary startup-only logging tests cannot cover.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.provider_log_safety import (
    ProviderLogRedactionFilter,
    configure_provider_log_safety,
)
from utils.toolkit_adaptation_failure_packet import build_adaptation_failure_packet
from utils.toolkit_adaptation_output_safety import (
    AdaptationOutputSafety,
    MAX_EVENT_CHARS,
    MAX_TAIL_CHARS,
    project_gui_payload,
    project_persisted_diagnostic,
)
from web.extensions.toolkit_adaptation_job_reporting import (
    build_adaptation_job_status,
    sanitize_adaptation_job_for_public,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / "tmp" / "toolkit_adaptation_output_hygiene_sentinels"


class AdaptationOutputHygieneSentinelTest(unittest.TestCase):
    def setUp(self) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.absolute_path = str((SCRATCH / "absolute-artifact.lock").resolve())
        self.sentinels = (
            "SOURCE_SENTINEL_5_1",
            "PROMPT_SENTINEL_5_1",
            "PROVIDER_RESPONSE_SENTINEL_5_1",
            "RAW_PROVIDER_PAYLOAD_SENTINEL_5_1",
            "credential-token-5-1",
            "authorization-marker-5-1",
            "sk_live_sentinel_5_1",
            self.absolute_path,
            "LOCK_PATH_SENTINEL_5_1",
            "STDOUT_SENTINEL_5_1",
            "STDERR_SENTINEL_5_1",
        )

    def tearDown(self) -> None:
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def _assert_no_sentinels(self, value: object) -> None:
        encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True)
        self.assertTrue(encoded.isascii())
        for sentinel in self.sentinels:
            self.assertNotIn(sentinel, encoded)

    def test_stdout_stderr_progress_and_gui_are_safe_and_bounded(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        progress = []
        gui = []
        unsafe = " ".join(self.sentinels)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with AdaptationOutputSafety(
                phase="adaptation_validation",
                status="running",
                progress_callback=progress.append,
                gui_callback=gui.append,
                redirect_streams=True,
            ) as scope:
                print(unsafe)
                print("STDERR_SENTINEL_5_1", file=sys.stderr)
                event = scope.emit({
                    "phase": "adaptation_monster_guardrail",
                    "status": "blocked",
                    "code": "monster_closure_unresolved",
                    "message": unsafe,
                    "count": 999999999999,
                    "attempt": 999999999999,
                    "revision": 999,
                    "raw_payload": unsafe,
                })
        combined = stdout.getvalue() + stderr.getvalue()
        self._assert_no_sentinels(combined)
        self._assert_no_sentinels(progress)
        self._assert_no_sentinels(gui)
        self.assertIn("captured_output_suppressed", combined)
        self.assertEqual(event["code"], "monster_closure_unresolved")
        self.assertEqual(event["status"], "blocked")
        self.assertLessEqual(event["count"], 2_000_000_000)
        self.assertLessEqual(event["attempt"], 1_000_000)
        self.assertLessEqual(event["revision"], 100)
        self.assertLessEqual(len(json.dumps(event, ensure_ascii=True)), MAX_EVENT_CHARS)
        self.assertLessEqual(len(progress), 3)
        self.assertLessEqual(len(gui), 3)

    def test_persisted_tails_and_failure_packet_keep_codes_without_payloads(self) -> None:
        raw_tail = "\n".join(self.sentinels) + "\n" + ("verbose diagnostic " * 500)
        diagnostic = project_persisted_diagnostic({
            "phase": "adaptation_build",
            "status": "blocked",
            "code": "monster_closure_unresolved",
            "stdout_tail": raw_tail,
            "stderr_tail": raw_tail,
            "exception": raw_tail,
            "provider_failure": raw_tail,
        })
        diagnostic_path = SCRATCH / "diagnostic.json"
        diagnostic_path.write_text(json.dumps(diagnostic, ensure_ascii=True, sort_keys=True), encoding="ascii")
        persisted = diagnostic_path.read_text(encoding="ascii")
        self._assert_no_sentinels(persisted)
        self.assertFalse(diagnostic["raw_provider_payload_exposed"])
        self.assertLessEqual(len(diagnostic["stdout_tail"]), MAX_TAIL_CHARS)
        self.assertLessEqual(len(diagnostic["stderr_tail"]), MAX_TAIL_CHARS)

        packet = build_adaptation_failure_packet(
            {"gates": {"mechanical_closure": {
                "status": "blocked",
                "errors": [{"code": "monster_closure_unresolved", "message": raw_tail}],
            }}},
            attempt_metadata={
                "attempt_id": "adapt-001-sentinel",
                "attempt_number": 1,
                "revision_number": 0,
                "source_hash": "a" * 64,
                "source_path": "tmp/source.md",
                "adaptation_mode": "llm_adaptation",
            },
            staging_target={"path": "tmp/staging", "reference_only": True},
            repo_root=REPO_ROOT,
        )
        packet_path = SCRATCH / "failure_packet.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=True, sort_keys=True), encoding="ascii")
        self._assert_no_sentinels(packet_path.read_text(encoding="ascii"))
        self.assertFalse(packet["raw_provider_payload_exposed"])
        self.assertEqual(packet["failure_code"], "monster_closure_unresolved")

    def test_late_provider_loggers_and_handlers_cannot_bypass_adaptation_boundary(self) -> None:
        configure_provider_log_safety()
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.DEBUG)
        root_output = io.StringIO()
        root_handler = logging.StreamHandler(root_output)
        root_handler.setLevel(logging.DEBUG)
        provider_loggers = [logging.getLogger(name) for name in (
            "openai.late_sentinel", "httpx.late_sentinel", "httpcore.late_sentinel",
        )]
        app_logger = logging.getLogger("NeverEndingQuest.late_application_sentinel")
        app_output = io.StringIO()
        app_handler = logging.StreamHandler(app_output)
        app_handler.setLevel(logging.DEBUG)
        old_app_handlers = list(app_logger.handlers)
        old_app_propagate = app_logger.propagate
        try:
            root.addHandler(root_handler)
            app_logger.handlers = [app_handler]
            app_logger.propagate = False
            with AdaptationOutputSafety(phase="adaptation_build", status="running"):
                for logger in provider_loggers:
                    logger.setLevel(logging.DEBUG)
                    logger.warning(
                        "provider payload %s %s",
                        "PROMPT_SENTINEL_5_1",
                        "PROVIDER_RESPONSE_SENTINEL_5_1",
                        extra={
                            "messages": "SOURCE_SENTINEL_5_1",
                            "authorization": "Bearer authorization-marker-5-1",
                            "headers": {"token": "credential-token-5-1"},
                            "request_id": "request-safe-5-1",
                        },
                    )
                app_logger.error("application source SOURCE_SENTINEL_5_1")
            self._assert_no_sentinels(root_output.getvalue())
            self._assert_no_sentinels(app_output.getvalue())
            self.assertIn("provider_payload_suppressed", root_output.getvalue())
            self.assertIn("application_log", app_output.getvalue())
        finally:
            root.removeHandler(root_handler)
            app_logger.handlers = old_app_handlers
            app_logger.propagate = old_app_propagate
            root.setLevel(old_level)
            for logger in provider_loggers:
                logger.handlers.clear()
                logger.setLevel(logging.NOTSET)

    def test_late_provider_filter_preserves_adaptation_projection(self) -> None:
        """A late provider filter must not replace the bounded adaptation event."""
        configure_provider_log_safety()
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.DEBUG)
        output = io.StringIO()
        late_handler = logging.StreamHandler(output)
        late_handler.setLevel(logging.DEBUG)
        # Install this after provider safety setup to model a late root
        # handler/filter created by file-operation logging configuration.
        late_handler.addFilter(ProviderLogRedactionFilter())
        provider = logging.getLogger("httpx.late_projection_sentinel")
        old_level_provider = provider.level
        old_propagate = provider.propagate
        old_handlers = list(provider.handlers)
        try:
            root.addHandler(late_handler)
            provider.handlers = []
            provider.propagate = True
            provider.setLevel(logging.DEBUG)
            with AdaptationOutputSafety(phase="adaptation_build", status="running"):
                provider.debug(
                    "provider payload SOURCE_SENTINEL_5_1",
                    extra={
                        "messages": "PROMPT_SENTINEL_5_1",
                        "response_body": "PROVIDER_RESPONSE_SENTINEL_5_1",
                    },
                )
            captured = output.getvalue()
            self._assert_no_sentinels(captured)
            self.assertIn("provider_payload_suppressed", captured)
            self.assertNotIn("PROVIDER_PAYLOAD_REDACTED", captured)
        finally:
            root.removeHandler(late_handler)
            provider.handlers = old_handlers
            provider.setLevel(old_level_provider)
            provider.propagate = old_propagate
            root.setLevel(old_level)

    def test_adaptation_job_and_public_gui_payload_keep_failure_visibility(self) -> None:
        job = {
            "adaptation_mode": "llm_adaptation",
            "status": "blocked",
            "stage": "adaptation_monster_guardrail",
            "attempt_id": "adapt-001-sentinel",
            "attempt_number": 1,
            "revision_number": 0,
            "failure_classification": {
                "failure_class": "mechanical",
                "code": "monster_closure_unresolved",
                "stage": "adaptation_monster_guardrail",
                "diagnostics": [{"code": "monster_closure_unresolved", "message": " ".join(self.sentinels)}],
            },
        }
        summary = build_adaptation_job_status(job)
        public = sanitize_adaptation_job_for_public(job)
        gui = project_gui_payload({
            "phase": summary["phase"],
            "status": "blocked",
            "code": summary["failure_code"],
            "message": summary["status_text"],
            "attempt": summary["attempt_number"],
            "revision": summary["revision_number"],
            "raw_provider_payload": " ".join(self.sentinels),
        })
        self._assert_no_sentinels(summary)
        self._assert_no_sentinels(public)
        self._assert_no_sentinels(gui)
        self.assertEqual(summary["failure_code"], "monster_closure_unresolved")
        self.assertIn(summary["phase"], {"adaptation_blocked", "adaptation_monster_guardrail"})
        self.assertFalse(summary["raw_provider_payload_exposed"])
        self.assertFalse(public["raw_provider_payload_exposed"])
        self.assertLessEqual(len(json.dumps(public, ensure_ascii=True)), 20_000)

    def test_legacy_safe_diagnostics_remain_visible_outside_adaptation_scope(self) -> None:
        output = io.StringIO()
        logger = logging.getLogger("legacy-output-hygiene-sentinel")
        old_handlers = list(logger.handlers)
        old_propagate = logger.propagate
        old_level = logger.level
        handler = logging.StreamHandler(output)
        try:
            logger.handlers = [handler]
            logger.propagate = False
            logger.setLevel(logging.INFO)
            logger.info("SAFE_LEGACY_DIAGNOSTIC")
            self.assertIn("SAFE_LEGACY_DIAGNOSTIC", output.getvalue())
            self.assertNotIn("contract_version", output.getvalue())
        finally:
            logger.handlers = old_handlers
            logger.propagate = old_propagate
            logger.setLevel(old_level)


if __name__ == "__main__":
    unittest.main(verbosity=2)
