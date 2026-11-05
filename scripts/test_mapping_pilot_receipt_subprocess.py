#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free subprocess receipt integration regressions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.execution import (
    create_or_resume_ledger,
    reconcile_attempt_count,
    record_row_event,
)
from scripts.mapping_pilot.manifest import PROJECT_ROOT
from scripts.mapping_pilot import row_runner


class MappingPilotReceiptSubprocessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path("tmp") / ("mapping_pilot_receipt_test_" + uuid.uuid4().hex)
        self.run_id = "receipt-run-" + uuid.uuid4().hex[:8]
        self.row_run_id = "receipt-row-" + uuid.uuid4().hex[:8]
        self.lifecycle_id = self.row_run_id + "-s1"
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        shutil.rmtree(PROJECT_ROOT / self.base, ignore_errors=True)

    def _start_row(self) -> None:
        create_or_resume_ledger(self.run_id, ledger_root=self.base, now=self.now)
        for event, offset in (
            ("seed_started", 0),
            ("seed_completed", 1),
            ("sandbox_launched", 2),
        ):
            event_time = self.now + timedelta(seconds=offset)
            record_row_event(
                self.run_id,
                "E01",
                self.row_run_id,
                event,
                event_timestamp=event_time.isoformat().replace("+00:00", "Z"),
                ledger_root=self.base,
                now=event_time,
            )
        reconcile_attempt_count(
            self.run_id,
            "E01",
            self.row_run_id,
            0,
            ledger_root=self.base,
            now=self.now,
        )

    def test_child_bootstrap_records_receipts_once_with_usage_and_step_identity(self) -> None:
        self._start_row()
        sandbox = PROJECT_ROOT / self.base / "copied-sandbox"
        fake_utils = sandbox / "utils"
        fake_utils.mkdir(parents=True)
        (fake_utils / "__init__.py").write_text("", encoding="ascii")
        (fake_utils / "llm_router.py").write_text(
            """\
from types import SimpleNamespace
class LLMRouter:
    def _request_kwargs(self, *args, **kwargs): return {}
    @staticmethod
    def _disable_sdk_retries(client): return client
class Transport:
    def __init__(self): self.calls = 0
    def create(self, *args, **kwargs):
        self.calls += 1
        tasks = ("adv_summary", "cumulative_summary", "unknown_summary")
        receipt = SimpleNamespace(
            kind="response", call_id="child-%d" % self.calls,
            attempt_id="attempt-%d" % self.calls, attempt_number=1,
            task=tasks[self.calls - 1], tier="simple", profile="fake-profile",
            transport_retry=False, retry_tier=None, fallback=self.calls == 2,
            transport_provider="fake-transport",
            observed_upstream_provider="fake-provider",
            requested_model="openrouter/auto", resolved_model="fake/model",
            prompt_tokens=7, cached_tokens=0, completion_tokens=3,
            usage_complete=True, provider_reported_cost_usd=None, cost_usd=None,
            cost_provenance=None, cost_complete=False, error_type=None,
            elapsed_ms=4.0,
        )
        kwargs["observer"](receipt, {"prompt": "private prompt"})
        names = ("_llm_tracks_usage", "_llm_traces_provider",
                 "_llm_api_log_before_tracker", "_llm_g10_source_id",
                 "_llm_g10_endpoint")
        self.flags = [getattr(kwargs["observer"], name, None) for name in names]
        return "fake"
class FakeLLM:
    def __init__(self): self.transport = Transport()
    def call(self, *args, **kwargs):
        router = LLMRouter()
        router._request_kwargs()
        client = SimpleNamespace(chat=SimpleNamespace(completions=self.transport))
        guarded = router._disable_sdk_retries(client)
        return guarded.chat.completions.create(*args, **kwargs)
llm = FakeLLM()
""",
            encoding="ascii",
        )

        receipt_runtime = PROJECT_ROOT / self.base / "receipt-runtime"
        mapping_root = receipt_runtime / "mapping_pilot"
        mapping_root.mkdir(parents=True)
        step_path = mapping_root / "current_script_step.json"
        step_path.write_text(
            json.dumps({"step_id": "startup", "phase": "lifecycle_control",
                        "provider_call_expected": False}),
            encoding="ascii",
        )
        guard_directory = self.base / self.run_id / "runtime" / self.row_run_id
        (PROJECT_ROOT / guard_directory).mkdir(parents=True)
        context = {
            "run_id": self.run_id,
            "row_id": "E01",
            "row_run_id": self.row_run_id,
            "lifecycle_id": self.lifecycle_id,
            "ledger_root": self.base.as_posix(),
            "live_started_monotonic": time.monotonic(),
        }
        environment = os.environ.copy()
        environment.update(row_runner._request_guard_environment({
            "_request_guard_context": context,
            "_request_guard_directory": guard_directory.as_posix(),
        }))
        child_code = """\
import importlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import sitecustomize as guard
def deny_network(*args, **kwargs): raise AssertionError("network tripwire")
socket.socket.connect = deny_network
socket.create_connection = deny_network
sandbox = Path(sys.argv[1]).resolve(strict=True)
root = Path(sys.argv[2]).resolve(strict=True)
row_run_id, lifecycle_id = sys.argv[3:5]
guard._SERVER._safe_runtime_root = lambda _value: root
import utils
utils.__path__.insert(0, str(sandbox / "utils"))
utils.__path__.append(str(Path(guard._EXECUTION.PROJECT_ROOT) / "utils"))
router_module = importlib.import_module("utils.llm_router")
if Path(router_module.__file__).resolve() != sandbox / "utils" / "llm_router.py":
    raise AssertionError("copied router was not imported")
spec = importlib.util.spec_from_file_location("duplicate_server", guard._SERVER.__file__)
duplicate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(duplicate)
duplicate._safe_runtime_root = lambda _value: root
duplicate.install_router_receipt_observer(
    "tmp/combat_capture", row_run_id, lifecycle_id, router_module=router_module)
used = []
def usage_observer(receipt, _raw): used.append(receipt.call_id)
usage_observer._llm_tracks_usage = True
usage_observer._llm_traces_provider = True
usage_observer._llm_api_log_before_tracker = True
usage_observer._llm_g10_source_id = "usage-source"
usage_observer._llm_g10_endpoint = "usage-endpoint"
router_module.llm.call("fake", observer=usage_observer)
(root / "mapping_pilot/current_script_step.json").write_text(
    json.dumps({"step_id": "E1-01", "phase": "model_bearing_turn",
                "provider_call_expected": True}), encoding="ascii")
router_module.llm.call("fake", observer=usage_observer)
(root / "mapping_pilot/current_script_step.json").write_text(
    json.dumps({"phase": "unresolved"}), encoding="ascii")
router_module.llm.call("fake", observer=usage_observer)
print(json.dumps({"used": used, "calls": router_module.llm.transport.calls,
                  "flags": router_module.llm.transport.flags}))
"""
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(sandbox), str(receipt_runtime),
             self.row_run_id, self.lifecycle_id],
            cwd=str(sandbox), env=environment, capture_output=True, text=True,
            check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        child_result = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(child_result["used"], ["child-1", "child-2", "child-3"])
        self.assertEqual(child_result["calls"], 3)
        self.assertEqual(child_result["flags"], [
            True, True, True, "usage-source", "usage-endpoint"
        ])
        receipt_directory = mapping_root / "router_receipts" / self.row_run_id
        paths = sorted(receipt_directory.glob("record-*.json"))
        self.assertEqual([path.name for path in paths], [
            "record-00000001.json",
            "record-00000002.json",
            "record-00000003.json",
        ])
        receipts = [json.loads(path.read_text(encoding="ascii")) for path in paths]
        self.assertEqual([item["task"] for item in receipts], [
            "adv_summary", "cumulative_summary", "unknown_summary"
        ])
        self.assertTrue(all(
            item["row_run_id"] == self.row_run_id
            and item["lifecycle_id"] == self.lifecycle_id for item in receipts
        ))
        self.assertEqual(receipts[0]["script_step_id"], "startup")
        self.assertEqual(receipts[0]["attribution"], "lifecycle_control")
        self.assertEqual(receipts[1]["script_step_id"], "E1-01")
        self.assertEqual(receipts[1]["attribution"], "model_bearing_turn")
        self.assertEqual(receipts[1]["provider"], "fake-provider")
        self.assertEqual(receipts[1]["transport"], "fake-transport")
        self.assertEqual(receipts[1]["requested_model"], "openrouter/auto")
        self.assertEqual(receipts[1]["resolved_model"], "fake/model")
        self.assertTrue(receipts[1]["fallback"])
        self.assertEqual(receipts[2]["attribution"], "unknown")
        self.assertEqual(receipts[2]["attribution_status"], "missing")
        self.assertNotIn("private prompt", json.dumps(receipts, ensure_ascii=True))
        ledger = create_or_resume_ledger(self.run_id, ledger_root=self.base)
        execution = next(slot for slot in ledger["slots"] if slot["row_id"] == "E01")["execution"]
        self.assertEqual(execution["attempt_count"], 3)

    def test_receipt_sequences_are_unique_across_concurrent_processes(self) -> None:
        receipt_runtime = PROJECT_ROOT / self.base / "concurrent-runtime"
        mapping_root = receipt_runtime / "mapping_pilot"
        mapping_root.mkdir(parents=True)
        (mapping_root / "current_script_step.json").write_text(
            json.dumps({
                "step_id": "E1-01",
                "phase": "model_bearing_turn",
                "provider_call_expected": True,
            }),
            encoding="ascii",
        )
        row_run_id = "concurrent-receipt-row"
        lifecycle_id = "concurrent-receipt-row-s1"
        worker_count = 4
        calls_per_worker = 8
        child_code = """\
import sys
from pathlib import Path
from types import SimpleNamespace
from scripts.mapping_pilot import server

receipt_runtime = Path(sys.argv[1]).resolve(strict=True)
worker_id = sys.argv[2]
row_run_id = sys.argv[3]
lifecycle_id = sys.argv[4]
calls = int(sys.argv[5])
server._safe_runtime_root = lambda _value: receipt_runtime

class FakeRouter:
    def call(self, *args, **kwargs):
        for index in range(calls):
            receipt = SimpleNamespace(
                kind="response",
                call_id="%s-%03d" % (worker_id, index),
                attempt_id="attempt-%s-%03d" % (worker_id, index),
                attempt_number=1,
                task="narrative",
                tier="simple",
                profile="concurrent-test",
                transport_retry=False,
                retry_tier=None,
                fallback=False,
                transport_provider="fake-transport",
                observed_upstream_provider="fake-provider",
                requested_model="openrouter/auto",
                resolved_model="fake/model",
                prompt_tokens=1,
                cached_tokens=0,
                completion_tokens=1,
                usage_complete=True,
                provider_reported_cost_usd=None,
                cost_usd=None,
                cost_provenance=None,
                cost_complete=False,
                error_type=None,
                elapsed_ms=1.0,
            )
            kwargs["observer"](receipt, {"prompt": "private"})

router = FakeRouter()
cleanup = server.install_router_receipt_observer(
    "tmp/combat_capture",
    row_run_id,
    lifecycle_id,
    router_module=SimpleNamespace(llm=router),
)
try:
    router.call("fake")
finally:
    cleanup()
"""
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(receipt_runtime),
                    "worker-%d" % worker,
                    row_run_id,
                    lifecycle_id,
                    str(calls_per_worker),
                ],
                cwd=str(ROOT),
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for worker in range(worker_count)
        ]
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, msg=stderr + stdout)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        receipt_directory = mapping_root / "router_receipts" / row_run_id
        paths = sorted(receipt_directory.glob("record-*.json"))
        expected_count = worker_count * calls_per_worker
        self.assertEqual(len(paths), expected_count)
        self.assertEqual(
            [path.name for path in paths],
            ["record-%08d.json" % value for value in range(1, expected_count + 1)],
        )
        records = [json.loads(path.read_text(encoding="ascii")) for path in paths]
        expected_call_ids = {
            "worker-%d-%03d" % (worker, index)
            for worker in range(worker_count)
            for index in range(calls_per_worker)
        }
        call_ids = [record["call_id"] for record in records]
        self.assertEqual(len(set(call_ids)), expected_count)
        self.assertEqual(set(call_ids), expected_call_ids)
        self.assertEqual(
            [record["sequence"] for record in records],
            list(range(1, expected_count + 1)),
        )
        self.assertFalse((receipt_directory / ".sequence.lock").exists())
