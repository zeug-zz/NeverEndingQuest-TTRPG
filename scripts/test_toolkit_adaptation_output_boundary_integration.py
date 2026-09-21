# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free integration contracts for adaptation output projections."""

from __future__ import annotations

import io
import json
import logging
import queue
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from utils.toolkit_adaptation_output_safety import AdaptationOutputSafety
from web.extensions.toolkit_adaptation_job_reporting import (
    build_adaptation_job_status,
    sanitize_adaptation_job_for_public,
)


class AdaptationOutputBoundaryIntegrationTest(unittest.TestCase):
    def test_packet_build_worker_scope_contains_late_handlers(self) -> None:
        """The real packet-build wrapper must protect a worker thread seam."""
        from web.extensions import toolkit_homebrew_packet_builder as packet_builder

        output = io.StringIO()
        root = logging.getLogger()
        late_output = io.StringIO()
        late_handler = logging.StreamHandler(late_output)
        late_handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        worker_result = []

        def worker_build(*args, **kwargs):
            # This handler and these child loggers are deliberately created in
            # the worker after the packet-build scope has been entered.
            root.addHandler(late_handler)
            provider = logging.getLogger("httpx.adaptation_worker_late")
            application = logging.getLogger("NeverEndingQuest.adaptation_worker_late")
            provider.setLevel(logging.DEBUG)
            provider.warning(
                "request PROMPT_SENTINEL PROVIDER_RESPONSE_SENTINEL",
                extra={
                    "messages": "SOURCE_SENTINEL",
                    "authorization": "Bearer credential-token",
                    "request_id": "RAW_REQUEST_ID",
                },
            )
            application.error("application /Users/private/worker.lock SOURCE_SENTINEL")
            print("worker stdout /Users/private/worker.lock STDOUT_SENTINEL")
            return {"status": "success"}

        def run_worker() -> None:
            worker_result.append(
                packet_builder.run_toolkit_homebrew_packet_build(
                    "tmp/adaptation-worker", "adapt-worker",
                    adaptation_route=packet_builder.BUILD_MODE_LLM_ADAPTATION,
                    adaptation_dossier={},
                )
            )

        try:
            with redirect_stdout(output), patch.object(
                packet_builder, "_run_toolkit_homebrew_packet_build", worker_build
            ):
                thread = threading.Thread(target=run_worker)
                thread.start()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worker_result, [{"status": "success"}])
            emitted = output.getvalue() + late_output.getvalue()
            for sentinel in (
                "PROMPT_SENTINEL", "PROVIDER_RESPONSE_SENTINEL", "SOURCE_SENTINEL",
                "credential-token", "RAW_REQUEST_ID", "/Users/private/worker.lock",
                "STDOUT_SENTINEL",
            ):
                self.assertNotIn(sentinel, emitted)
            self.assertTrue(
                "provider_payload_suppressed" in emitted
                or "PROVIDER_PAYLOAD_REDACTED" in emitted
            )
            self.assertIn("application_log", emitted)
            self.assertIn("captured_output_suppressed", emitted)
        finally:
            root.removeHandler(late_handler)

    def test_generator_diagnostics_suppress_concept_and_response_sentinels(self) -> None:
        from core.generators.module_builder import BuilderConfig, ModuleBuilder
        from core.generators.module_generator import ModuleGenerator

        output = io.StringIO()
        builder = ModuleBuilder(BuilderConfig(output_directory="tmp/adaptation-output-test"))
        builder.build_mode = "llm_adaptation"
        builder.llm_adaptation = {"source": "SOURCE_SENTINEL"}
        generator = ModuleGenerator()
        generator.adaptation_mode = True
        with redirect_stdout(output):
            builder.log("Initial concept: SOURCE_SENTINEL PROMPT_SENTINEL")
            generator._adaptation_log(
                "provider_response_suppressed",
                "PROVIDER_RESPONSE_SENTINEL /Users/private/lock",
            )
        emitted = output.getvalue()
        for sentinel in (
            "SOURCE_SENTINEL",
            "PROMPT_SENTINEL",
            "PROVIDER_RESPONSE_SENTINEL",
            "/Users/private/lock",
        ):
            self.assertNotIn(sentinel, emitted)
        self.assertIn("module_builder_progress", emitted)
        self.assertIn("provider_response_suppressed", emitted)

    def test_legacy_generator_diagnostics_remain_active(self) -> None:
        from core.generators.module_builder import BuilderConfig, ModuleBuilder

        output = io.StringIO()
        builder = ModuleBuilder(BuilderConfig(output_directory="tmp/adaptation-output-test"))
        with redirect_stdout(output):
            builder.log("SAFE_LEGACY_DIAGNOSTIC")
        self.assertIn("SAFE_LEGACY_DIAGNOSTIC", output.getvalue())

    def test_web_capture_is_safe_only_inside_adaptation_scope(self) -> None:
        from web.web_interface import WebOutputCapture

        original = io.StringIO()
        captured = queue.Queue()
        stream = WebOutputCapture(captured, original)
        with redirect_stdout(io.StringIO()):
            with AdaptationOutputSafety(
                phase="adaptation_build", status="running", redirect_streams=False
            ):
                stream.write("SOURCE_SENTINEL PROVIDER_RESPONSE_SENTINEL /Users/private/lock\n")
                stream.flush()
        emitted = original.getvalue() + " ".join(
            item.get("content", "") for item in list(captured.queue)
        )
        self.assertNotIn("SOURCE_SENTINEL", emitted)
        self.assertNotIn("PROVIDER_RESPONSE_SENTINEL", emitted)
        self.assertIn("captured_output_suppressed", emitted)

    def test_job_report_projection_suppresses_raw_diagnostic_values(self) -> None:
        job = {
            "adaptation_mode": "llm_adaptation",
            "status": "blocked",
            "stage": "adaptation_monster_guardrail",
            "failure_classification": {
                "failure_class": "semantic",
                "code": "monster_closure_unresolved",
                "failed_stage": "monster_closure",
                "diagnostics": [{
                    "code": "monster_closure_unresolved",
                    "message": "SOURCE_SENTINEL PROMPT_SENTINEL PROVIDER_RESPONSE_SENTINEL",
                }],
            },
        }
        summary = build_adaptation_job_status(job)
        public = sanitize_adaptation_job_for_public(job)
        encoded = json.dumps({"summary": summary, "public": public}, sort_keys=True)
        for sentinel in (
            "SOURCE_SENTINEL",
            "PROMPT_SENTINEL",
            "PROVIDER_RESPONSE_SENTINEL",
        ):
            self.assertNotIn(sentinel, encoded)
        self.assertEqual(summary["failure_code"], "monster_closure_unresolved")
        self.assertFalse(summary["raw_provider_payload_exposed"])

    def test_legacy_logger_filter_is_inactive_outside_scope(self) -> None:
        record = logging.LogRecord("legacy", logging.INFO, __file__, 1, "SAFE_LEGACY", (), None)
        from utils.toolkit_adaptation_output_safety import AdaptationOutputSafetyFilter

        self.assertTrue(AdaptationOutputSafetyFilter().filter(record))
        self.assertEqual(record.msg, "SAFE_LEGACY")


if __name__ == "__main__":
    unittest.main()
