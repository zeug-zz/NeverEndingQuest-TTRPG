# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for the isolated SP3b control foundation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot import sp3b
from scripts.mapping_pilot.manifest import PROJECT_ROOT

PRODUCTION_CLOSEOUT_PATH = sp3b.PRIMARY_CLOSEOUT_RELATIVE_PATH
PRODUCTION_CLOSEOUT_SHA256 = sp3b.PRIMARY_CLOSEOUT_SHA256


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.instant = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self.value

    def wall_clock(self) -> datetime:
        with self._lock:
            return self.instant

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.value += seconds


class MappingPilotSP3BExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path("tmp") / ("sp3b_test_" + uuid.uuid4().hex)
        root_patch = mock.patch.object(sp3b, "DEFAULT_SP3B_ROOT", self.base)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.addCleanup(shutil.rmtree, PROJECT_ROOT / self.base, ignore_errors=True)
        self.baseline_relative_path = self.base / "synthetic-primary-closeout.json"
        self.baseline_path = PROJECT_ROOT / self.baseline_relative_path
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseline_path.write_bytes(self._baseline_fixture_bytes())
        path_patch = mock.patch.object(
            sp3b,
            "PRIMARY_CLOSEOUT_RELATIVE_PATH",
            self.baseline_relative_path,
        )
        path_patch.start()
        self.addCleanup(path_patch.stop)
        hash_patch = mock.patch.object(
            sp3b,
            "PRIMARY_CLOSEOUT_SHA256",
            hashlib.sha256(self.baseline_path.read_bytes()).hexdigest(),
        )
        hash_patch.start()
        self.addCleanup(hash_patch.stop)

        production_closeout = sp3b.PROJECT_ROOT / PRODUCTION_CLOSEOUT_PATH
        read_bytes = sp3b._read_bytes

        def forbid_historical_closeout(path: Path, label: str) -> bytes:
            if path == production_closeout:
                raise AssertionError("unit tests must not read the historical primary closeout")
            return read_bytes(path, label)

        baseline_read_patch = mock.patch.object(
            sp3b,
            "_read_bytes",
            side_effect=forbid_historical_closeout,
        )
        baseline_read_patch.start()
        self.addCleanup(baseline_read_patch.stop)
        self.clock = FakeClock()
        self.identity = self._identity_capture()

        # The control layer must stay disconnected from the live server and
        # socket launcher. Tests use injected identity/authorization callbacks.
        socket_patch = mock.patch.object(socket, "socket", side_effect=AssertionError("socket use forbidden"))
        popen_patch = mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process launch forbidden"))
        socket_patch.start()
        popen_patch.start()
        self.addCleanup(socket_patch.stop)
        self.addCleanup(popen_patch.stop)
        process_patch = mock.patch.object(
            subprocess,
            "run",
            side_effect=AssertionError("subprocess use forbidden in provider-free control tests"),
        )
        process_patch.start()
        self.addCleanup(process_patch.stop)
        forbidden_imports = {
            name: None
            for name in (
                "scripts.mapping_pilot.adapter",
                "scripts.mapping_pilot.execution",
                "scripts.mapping_pilot.launcher",
                "scripts.mapping_pilot.live_client",
                "scripts.mapping_pilot.row_runner",
                "scripts.mapping_pilot.scoring",
                "scripts.mapping_pilot.server",
                "utils.ai_client_factory",
                "utils.llm_router",
                "requests",
                "httpx",
            )
        }
        import_patch = mock.patch.dict(sys.modules, forbidden_imports)
        import_patch.start()
        self.addCleanup(import_patch.stop)

    @staticmethod
    def _baseline_fixture_bytes() -> bytes:
        return json.dumps(
            {
                "matrix_totals": {
                    "matrix_attempts": 513,
                    "matrix_elapsed_seconds": 3453.3628182079847,
                },
                "no_reserves_or_replays": True,
                "original_26_slot_records_unchanged": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    @staticmethod
    def _identity_capture() -> dict[str, Any]:
        digest = "a" * 64
        return {
            "source_commit_sha": "1" * 40,
            "source_tree_oid": "2" * 40,
            "source_content_sha256": digest,
            "status_digest_sha256": "b" * 64,
            "requirements_lock_sha256": "c" * 64,
            "interpreter": {
                "executable": "/repo/.venv/bin/python",
                "implementation": "cpython",
                "version": "3.13.0",
                "platform": "darwin",
            },
            "dependency_versions": {"pytest": "8.0.0"},
            "environment": {name: None for name in sp3b._SAFE_ENVIRONMENT},
            "requested_route": dict(sp3b._EXPECTED_REQUESTED_ROUTE),
            "static_route_config": {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_CHAT_MODEL": "provider/configured-model",
                "ENABLE_PROVIDER_FALLBACK": True,
                "OPENROUTER_STRATEGY": "auto",
                "OPENROUTER_FULL_MODEL": "provider/full-model",
                "OPENROUTER_MINI_MODEL": "provider/mini-model",
            },
            "prompt_hashes": {"prompts/mapping/system.md": digest},
            "tool_hashes": {"scripts/mapping_pilot/sp3b.py": digest},
            "source_hashes": {"scripts/mapping_pilot/sp3b.py": digest},
            "input_hashes": {"plans/v2-mapping-pilot-prereg/rubric.md": digest},
            "profile_hashes": {"plans/v2-mapping-pilot-prereg/rubric.md": digest},
            "tracked_source_file_count": 1,
        }

    def _make_execution(
        self,
        *,
        authorize: bool = True,
        identity_provider: Any = None,
    ) -> sp3b.SP3BExecution:
        provider = identity_provider or (lambda: copy.deepcopy(self.identity))

        def freeze_authorizer(freeze_hash: str, identity_hash: str) -> dict[str, Any]:
            return {
                "decision": "SP3B_FREEZE",
                "authorized": True,
                "checked": True,
                "amendment_sha256": sp3b.EXPECTED_AMENDMENT_SHA256,
                "freeze_sha256": freeze_hash,
                "execution_identity_sha256": identity_hash,
                "ruling_sha256": "d" * 64,
                "reviewer": "provider-free-test-fixture",
                "authorization_id": "test-freeze-authority",
            }

        return sp3b.SP3BExecution(
            "sp3b-test-run",
            identity_provider=provider,
            freeze_authorizer=freeze_authorizer if authorize else None,
            monotonic=self.clock.monotonic,
            wall_clock=self.clock.wall_clock,
        )

    @staticmethod
    def _safety() -> dict[str, float]:
        return {
            "measured_teardown_headroom_seconds": 10.0,
            "measured_window_seconds_remaining": 60.0,
        }

    def _complete_row(
        self,
        execution: sp3b.SP3BExecution,
        row_id: str,
        evidence: list[dict[str, str]],
        *,
        charge_attempt: bool = True,
    ) -> dict[str, Any]:
        safety = self._safety()
        execution.admit_row(row_id, **safety)
        execution.start_live_interval(row_id, **safety)
        if charge_attempt:
            attempt_id = "attempt-" + row_id.lower()
            execution.admit_provider_attempt(
                row_id,
                attempt_id,
                kind="model_turn",
                **safety,
            )
            execution.record_attempt_outcome(attempt_id, "error")
        execution.finish_live_interval(row_id)
        result = execution.classify_row(row_id, evidence)
        execution.finish_row(row_id, status="BLOCKED", reason_code="provider_free_test")
        return result

    def test_exact_approved_nineteen_row_schedule_and_frozen_manifest(self) -> None:
        bindings = sp3b.load_sp3b_bindings()
        self.assertEqual(
            [row["row_id"] for row in bindings["rows"]],
            ["SP3B-%03d" % index for index in range(1, 20)],
        )
        self.assertEqual(
            [row["source_cell"] for row in bindings["rows"]],
            [
                "E01", "E03", "E04", "E05", "E06", "E13", "E14", "E15",
                "E16", "E17", "E18", "C01", "C02", "C03", "C04", "C05",
                "C06", "C07", "C08",
            ],
        )
        self.assertEqual(len(bindings["manifest_entries"]), 10)
        self.assertEqual(bindings["manifest_sha256"], sp3b.EXPECTED_MANIFEST_SHA256)

    def test_production_baseline_binding_and_synthetic_fixture_semantics(self) -> None:
        self.assertEqual(
            PRODUCTION_CLOSEOUT_PATH.as_posix(),
            "tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/primary-collection-closeout.json",
        )
        self.assertEqual(
            PRODUCTION_CLOSEOUT_SHA256,
            "2c265cb7bfd5124c19a9ca15738ccfb1522f3455075c72b3f0b2f065b929c4e2",
        )
        self.assertEqual(sp3b.BASELINE_ATTEMPTS, 513)
        self.assertEqual(sp3b.BASELINE_LIVE_SECONDS, 3453.3628182079847)
        self.assertEqual(
            sp3b.load_budget_baseline(),
            {
                "source_path": self.baseline_relative_path.as_posix(),
                "source_sha256": hashlib.sha256(self._baseline_fixture_bytes()).hexdigest(),
                "matrix_attempts": 513,
                "matrix_elapsed_seconds": 3453.3628182079847,
            },
        )

    def test_missing_malformed_and_nonfinite_baselines_fail_closed(self) -> None:
        self.baseline_path.unlink()
        with self.assertRaisesRegex(sp3b.SP3BError, "missing"):
            sp3b.load_budget_baseline()

        invalid_payloads = (
            ("malformed-json", b"{"),
            (
                "nonfinite-total",
                b'{"matrix_totals":{"matrix_attempts":513,"matrix_elapsed_seconds":1e999},"no_reserves_or_replays":true,"original_26_slot_records_unchanged":true}',
            ),
            (
                "unknown-total",
                b'{"matrix_totals":{"matrix_attempts":513,"matrix_elapsed_seconds":null},"no_reserves_or_replays":true,"original_26_slot_records_unchanged":true}',
            ),
        )
        for label, payload in invalid_payloads:
            with self.subTest(case=label):
                self.baseline_path.write_bytes(payload)
                with mock.patch.object(
                    sp3b,
                    "PRIMARY_CLOSEOUT_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ):
                    with self.assertRaises(sp3b.SP3BError):
                        sp3b.load_budget_baseline()
        self.baseline_path.write_bytes(self._baseline_fixture_bytes())

    def test_changed_amendment_or_primary_baseline_fails_closed(self) -> None:
        with mock.patch.object(sp3b, "EXPECTED_AMENDMENT_SHA256", "0" * 64):
            with self.assertRaisesRegex(sp3b.SP3BError, "amendment bytes changed"):
                sp3b.load_sp3b_bindings()
        with mock.patch.object(sp3b, "PRIMARY_CLOSEOUT_SHA256", "0" * 64):
            with self.assertRaisesRegex(sp3b.SP3BError, "closeout hash changed"):
                sp3b.load_budget_baseline()

    def test_classification_is_pre_content_allowlisted_and_time_caps_are_unresolved(self) -> None:
        self.assertEqual(sp3b.classify_pre_content(None)["classification"], "UNRESOLVED")
        self.assertEqual(sp3b.classify_pre_content([])["classification"], "UNRESOLVED")
        self.assertEqual(
            sp3b.classify_pre_content(
                [{"kind": "timing", "code": "row_live_cap", "source": "tmp/evidence/row.json"}]
            )["classification"],
            "UNRESOLVED",
        )
        self.assertEqual(
            sp3b.classify_pre_content(
                [{"kind": "transport", "code": "dns_failed", "source": "tmp/evidence/row.json"}]
            )["classification"],
            "INFRASTRUCTURE",
        )
        self.assertEqual(
            sp3b.classify_pre_content(
                [{"kind": "provider_status", "code": "usable_response_returned", "source": "tmp/evidence/row.json"}]
            )["classification"],
            "CONTENT/RESULT",
        )
        rejected = sp3b.classify_pre_content(
            [{
                "kind": "provider_status",
                "code": "usable_response_returned",
                "source": "tmp/evidence/row.json",
                "response_text": "must not be accepted or persisted",
            }]
        )
        self.assertEqual(rejected["classification"], "UNRESOLVED")
        self.assertNotIn("response_text", json.dumps(rejected))
        malformed = sp3b.classify_pre_content(
            [{"kind": [], "code": "dns_failed", "source": "tmp/evidence/row.json"}]
        )
        self.assertEqual(malformed["classification"], "UNRESOLVED")

    def test_identity_path_filter_excludes_config_and_credential_material(self) -> None:
        from pathlib import PurePosixPath

        for raw in (
            "config.py",
            "local/config.toml",
            ".env.production",
            "secrets/provider.json",
            "private/openrouter_api_key.txt",
            ".aws/credentials",
        ):
            with self.subTest(path=raw):
                self.assertTrue(sp3b._is_sensitive_path(PurePosixPath(raw)))
        self.assertFalse(
            sp3b._is_sensitive_path(PurePosixPath("scripts/mapping_pilot/execution.py"))
        )

    def test_environment_identity_capture_is_provider_free_and_excludes_mutable_inputs(self) -> None:
        identity_root = PROJECT_ROOT / self.base / "identity-root"
        tracked = (
            "model_config.py",
            "requirements-lock.txt",
            "scripts/mapping_pilot/sp3b.py",
            "scripts/source_parent.py",
            "prompts/mapping/system.md",
            "config.py",
            ".env.production",
            "secrets/provider.json",
        )
        files = {
            "model_config.py": (
                'LLM_PROVIDER = "openrouter"\n'
                'OPENROUTER_CHAT_MODEL = "openrouter/auto"\n'
                "ENABLE_PROVIDER_FALLBACK = True\n"
                'OPENROUTER_STRATEGY = "auto"\n'
                'OPENROUTER_FULL_MODEL = "openrouter/full"\n'
                'OPENROUTER_MINI_MODEL = "openrouter/mini"\n'
            ),
            "requirements-lock.txt": "fixture-dep==1.2.3\n",
            "scripts/mapping_pilot/sp3b.py": "# runtime source fixture\n",
            "scripts/source_parent.py": "# runtime parent fixture\n",
            "prompts/mapping/system.md": "fixture prompt\n",
            "config.py": "API_KEY = 'must not be read'\n",
            ".env.production": "OPENROUTER_API_KEY=must-not-be-read\n",
            "secrets/provider.json": '{"token":"must not be read"}\n',
        }
        for relative, content in files.items():
            path = identity_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        mutable_sandbox = identity_root / "tmp" / "sandbox" / "areas" / "mutable.json"
        mutable_sandbox.parent.mkdir(parents=True, exist_ok=True)
        mutable_sandbox.write_text('{"state":"first"}', encoding="utf-8")

        bindings = sp3b.load_sp3b_bindings()
        baseline = sp3b.load_budget_baseline()
        git_outputs = {
            ("rev-parse", "HEAD"): "1" * 40,
            ("rev-parse", "HEAD^{tree}"): "2" * 40,
            ("status", "--porcelain=v1", "-z", "--untracked-files=all"): b"",
            ("ls-files", "-z"): b"\0".join(item.encode("ascii") for item in tracked) + b"\0",
        }

        def fake_git(arguments: list[str], *, raw: bool = False) -> Any:
            output = git_outputs[tuple(arguments)]
            return output

        with (
            mock.patch.object(sp3b, "PROJECT_ROOT", identity_root),
            mock.patch.object(sp3b, "_git_output", side_effect=fake_git),
            mock.patch.object(sp3b, "load_sp3b_bindings", return_value=bindings),
            mock.patch.object(sp3b, "load_budget_baseline", return_value=baseline),
            mock.patch.object(sp3b.importlib.metadata, "version", return_value="1.2.3"),
            mock.patch.dict(
                os.environ,
                {
                    "NEQ_OPEN_BROWSER": "0",
                    "PYTHONHASHSEED": "11",
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "TZ": "UTC",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "OPENROUTER_API_KEY": "secret-value-not-in-identity",
                },
                clear=True,
            ),
        ):
            real_read_bytes = sp3b._read_bytes
            sensitive_paths = {identity_root / path for path in ("config.py", ".env.production", "secrets/provider.json")}

            def allow_only_nonsecret_reads(path: Path, label: str) -> bytes:
                if path in sensitive_paths:
                    raise AssertionError("identity capture read excluded local credential material")
                return real_read_bytes(path, label)

            with mock.patch.object(sp3b, "_read_bytes", side_effect=allow_only_nonsecret_reads):
                first = sp3b.capture_environment_identity()
                self.assertEqual(first["requested_route"], sp3b._EXPECTED_REQUESTED_ROUTE)
                self.assertEqual(
                    first["static_route_config"],
                    {
                        "LLM_PROVIDER": "openrouter",
                        "OPENROUTER_CHAT_MODEL": "openrouter/auto",
                        "ENABLE_PROVIDER_FALLBACK": True,
                        "OPENROUTER_STRATEGY": "auto",
                        "OPENROUTER_FULL_MODEL": "openrouter/full",
                        "OPENROUTER_MINI_MODEL": "openrouter/mini",
                    },
                )
                self.assertEqual(first["environment"]["NEQ_OPEN_BROWSER"], "0")
                self.assertNotIn("OPENROUTER_API_KEY", first["environment"])
                self.assertNotIn("secret-value-not-in-identity", json.dumps(first))
                self.assertNotIn("config.py", first["source_hashes"])
                self.assertNotIn("secrets/provider.json", first["source_hashes"])
                self.assertIn("scripts/source_parent.py", first["source_hashes"])

                mutable_sandbox.write_text('{"state":"changed"}', encoding="utf-8")
                (identity_root / "config.py").write_text(
                    "API_KEY = 'changed-but-excluded'\n",
                    encoding="utf-8",
                )
                (identity_root / ".env.production").write_text(
                    "OPENROUTER_API_KEY=changed-but-excluded\n",
                    encoding="utf-8",
                )
                os.environ["OPENROUTER_API_KEY"] = "different-secret"
                second = sp3b.capture_environment_identity()
                self.assertEqual(first, second)

            (identity_root / "requirements-lock.txt").write_text(
                "missing-fixture-dep==9.9.9\n",
                encoding="ascii",
            )
            with mock.patch.object(
                sp3b.importlib.metadata,
                "version",
                side_effect=sp3b.importlib.metadata.PackageNotFoundError,
            ):
                with self.assertRaisesRegex(sp3b.SP3BError, "locked dependency is not installed"):
                    sp3b.capture_environment_identity()

    def test_draft_identity_is_immutable_and_requires_external_freeze_authority(self) -> None:
        execution = self._make_execution(authorize=False)
        ledger = execution.initialize()
        freeze = json.loads(execution.freeze_path.read_text(encoding="utf-8"))
        self.assertEqual(freeze["status"], "DRAFT")
        self.assertIs(freeze["execution_authorized"], False)
        self.assertEqual(ledger["totals"]["matrix_attempts"], sp3b.BASELINE_ATTEMPTS)
        self.assertEqual(ledger["totals"]["matrix_elapsed_seconds"], sp3b.BASELINE_LIVE_SECONDS)
        with self.assertRaisesRegex(sp3b.SP3BError, "verified external SP3b FREEZE"):
            execution.admit_row("SP3B-001", **self._safety())
        unchanged = execution.snapshot()
        self.assertEqual(unchanged["rows"][0]["state"], "unstarted")
        self.assertEqual(
            hashlib_sha256(execution.freeze_path.read_bytes()),
            ledger["freeze_artifact_sha256"],
        )

    def test_row_and_request_admission_require_headroom_and_stable_order(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        with self.assertRaisesRegex(sp3b.SP3BBudgetError, "positive measured reserve"):
            execution.admit_row(
                "SP3B-001",
                measured_teardown_headroom_seconds=0,
                measured_window_seconds_remaining=60,
            )
        with self.assertRaisesRegex(sp3b.SP3BBudgetError, "does not exceed teardown headroom"):
            execution.admit_row(
                "SP3B-001",
                measured_teardown_headroom_seconds=10,
                measured_window_seconds_remaining=10,
            )
        with self.assertRaises(sp3b.SP3BError):
            execution.admit_row("SP3B-002", **self._safety())
        with self.assertRaises(sp3b.SP3BError):
            execution.admit_row("E02", **self._safety())

        safety = self._safety()
        execution.admit_row("SP3B-001", **safety)
        execution.start_live_interval("SP3B-001", **safety)
        with self.assertRaises(sp3b.SP3BBudgetError):
            execution.admit_provider_attempt(
                "SP3B-001",
                "no-headroom",
                kind="retry",
                measured_teardown_headroom_seconds=0,
                measured_window_seconds_remaining=60,
            )
        self.assertEqual(execution.snapshot()["totals"]["sp3b_attempts"], 0)

    def test_identity_drift_permanently_stops_and_marks_unstarted_rows_missing(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        self.identity["source_content_sha256"] = "e" * 64
        with self.assertRaises(sp3b.SP3BIdentityDriftError):
            execution.snapshot()
        persisted = json.loads(execution.ledger_path.read_text(encoding="utf-8"))
        self.assertTrue(persisted["control"]["identity_stopped"])
        self.assertEqual(persisted["control"]["identity_stop_reason"], "immutable_execution_identity_changed")
        self.assertTrue(all(row["state"] == "missing" for row in persisted["rows"]))
        with self.assertRaises(sp3b.SP3BIdentityDriftError):
            execution.initialize()

    def test_identity_drift_allows_only_unclamped_bound_ledger_closeout(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        safety = self._safety()
        execution.admit_row("SP3B-001", **safety)
        execution.start_live_interval("SP3B-001", **safety)

        self.identity["source_content_sha256"] = "e" * 64
        with self.assertRaises(sp3b.SP3BIdentityDriftError):
            execution.admit_provider_attempt("SP3B-001", "drift-denied", kind="retry", **safety)
        with self.assertRaises(sp3b.SP3BIdentityDriftError):
            execution.admit_row("SP3B-002", **safety)
        with self.assertRaises(sp3b.SP3BIdentityDriftError):
            execution.record_restart("SP3B-001")

        persisted_before_clock_failure = execution.ledger_path.read_bytes()
        with mock.patch.object(execution, "_monotonic", return_value=math.nan):
            with self.assertRaisesRegex(sp3b.SP3BBudgetError, "monotonic clock"):
                execution.finish_live_interval("SP3B-001")
        self.assertEqual(execution.ledger_path.read_bytes(), persisted_before_clock_failure)

        execution._identity_provider = lambda: (_ for _ in ()).throw(
            AssertionError("latched identity stop must not recapture identity for closeout")
        )
        execution._freeze_authorizer = None
        self.clock.advance(1537.25)
        closed = execution.finish_live_interval("SP3B-001")
        self.assertEqual(closed["rows"][0]["live_elapsed_seconds"], 1537.25)
        self.assertEqual(closed["totals"]["sp3b_live_seconds"], 1537.25)
        self.assertTrue(closed["control"]["identity_stopped"])
        self.assertEqual(closed["attempts"], [])
        self.assertEqual(closed["rows"][0]["restart_events"], [])
        execution.classify_row(
            "SP3B-001",
            [{"kind": "timing", "code": "row_live_cap", "source": "tmp/evidence/cap.json"}],
        )
        execution.finish_row("SP3B-001", status="BLOCKED", reason_code="identity_drift")
        completed = execution.mark_unrun_missing(reason_code="identity_drift")
        self.assertEqual(completed["rows"][0]["state"], "terminal")
        self.assertTrue(all(row["state"] == "missing" for row in completed["rows"][1:]))
        self.assertEqual(completed["control"]["identity_stop_reason"], "immutable_execution_identity_changed")
        self.assertEqual(completed["totals"]["sp3b_attempts"], 0)

    def test_corrupt_durable_totals_block_real_attempt_admission(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        safety = self._safety()
        execution.admit_row("SP3B-001", **safety)
        execution.start_live_interval("SP3B-001", **safety)
        valid_bytes = execution.ledger_path.read_bytes()
        corruptions = (
            ("none", lambda ledger: ledger["totals"].update(matrix_attempts=None)),
            ("nonfinite", lambda ledger: ledger["totals"].update(matrix_elapsed_seconds=math.inf)),
            ("tampered", lambda ledger: ledger["totals"].update(sp3b_attempts=1)),
        )
        for label, corrupt in corruptions:
            with self.subTest(case=label):
                ledger = json.loads(valid_bytes.decode("utf-8"))
                corrupt(ledger)
                execution.ledger_path.write_text(
                    json.dumps(ledger, allow_nan=True, sort_keys=True),
                    encoding="utf-8",
                )
                with self.assertRaises(sp3b.SP3BError):
                    execution.admit_provider_attempt(
                        "SP3B-001",
                        "corrupt-" + label,
                        kind="retry",
                        **safety,
                    )
                execution.ledger_path.write_bytes(valid_bytes)
        self.assertEqual(json.loads(valid_bytes)["attempts"], [])

    def test_symlinked_ledger_or_freeze_blocks_real_attempt_admission(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        safety = self._safety()
        execution.admit_row("SP3B-001", **safety)
        execution.start_live_interval("SP3B-001", **safety)

        ledger_bytes = execution.ledger_path.read_bytes()
        ledger_target = execution.ledger_path.parent / "ledger-target.json"
        ledger_target.write_bytes(ledger_bytes)
        execution.ledger_path.unlink()
        execution.ledger_path.symlink_to(ledger_target)
        with self.assertRaisesRegex(sp3b.SP3BError, "symlink"):
            execution.admit_provider_attempt("SP3B-001", "ledger-link", kind="retry", **safety)
        self.assertEqual(ledger_target.read_bytes(), ledger_bytes)

        execution.ledger_path.unlink()
        execution.ledger_path.write_bytes(ledger_bytes)
        freeze_bytes = execution.freeze_path.read_bytes()
        freeze_target = execution.freeze_path.parent / "freeze-target.json"
        freeze_target.write_bytes(freeze_bytes)
        execution.freeze_path.unlink()
        execution.freeze_path.symlink_to(freeze_target)
        with self.assertRaisesRegex(sp3b.SP3BError, "symlink"):
            execution.admit_provider_attempt("SP3B-001", "freeze-link", kind="retry", **safety)
        self.assertEqual(freeze_target.read_bytes(), freeze_bytes)

    def test_cumulative_attempt_cap_is_atomic_under_concurrent_request_admission(self) -> None:
        with mock.patch.object(sp3b, "TOTAL_ATTEMPT_CAP", sp3b.BASELINE_ATTEMPTS + 1):
            execution = self._make_execution()
            execution.initialize()
            safety = self._safety()
            execution.admit_row("SP3B-001", **safety)
            execution.start_live_interval("SP3B-001", **safety)

            def admit(attempt_id: str) -> str:
                try:
                    execution.admit_provider_attempt(
                        "SP3B-001",
                        attempt_id,
                        kind="retry",
                        **safety,
                    )
                    return "charged"
                except sp3b.SP3BBudgetError:
                    return "refused"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(admit, ("parallel-a", "parallel-b")))
            self.assertCountEqual(results, ["charged", "refused"])
            ledger = execution.snapshot()
            self.assertEqual(ledger["totals"]["matrix_attempts"], sp3b.TOTAL_ATTEMPT_CAP)
            self.assertEqual(len(ledger["attempts"]), 1)
            self.assertEqual(ledger["rows"][0]["attempt_count"], 1)

    def test_per_row_attempt_and_live_caps_preserve_teardown_headroom(self) -> None:
        with mock.patch.object(sp3b, "ROW_ATTEMPT_CAP", 1):
            execution = self._make_execution()
            execution.initialize()
            safety = self._safety()
            execution.admit_row("SP3B-001", **safety)
            execution.start_live_interval("SP3B-001", **safety)
            execution.admit_provider_attempt("SP3B-001", "row-cap-one", kind="retry", **safety)
            with self.assertRaisesRegex(sp3b.SP3BBudgetError, "per-row attempt cap"):
                execution.admit_provider_attempt("SP3B-001", "row-cap-two", kind="fallback", **safety)
            self.assertEqual(execution.snapshot()["rows"][0]["attempt_count"], 1)

    def test_request_admission_preserves_row_teardown_headroom(self) -> None:
        with mock.patch.object(sp3b, "ROW_LIVE_SECONDS_CAP", 100.0):
            execution = self._make_execution()
            execution.initialize()
            safety = self._safety()
            execution.admit_row("SP3B-001", **safety)
            execution.start_live_interval("SP3B-001", **safety)
            self.clock.advance(90)
            with self.assertRaisesRegex(sp3b.SP3BBudgetError, "teardown headroom"):
                execution.admit_provider_attempt("SP3B-001", "row-time-boundary", kind="provider", **safety)
            self.assertEqual(execution.snapshot()["totals"]["sp3b_attempts"], 0)
            ledger = execution.finish_live_interval("SP3B-001")
            self.assertEqual(ledger["rows"][0]["live_elapsed_seconds"], 90)
            self.assertFalse(ledger["control"]["stopped"])

    def test_cumulative_live_time_cap_blocks_a_row_before_it_starts(self) -> None:
        with mock.patch.object(
            sp3b,
            "TOTAL_LIVE_SECONDS_CAP",
            sp3b.BASELINE_LIVE_SECONDS + 10.0,
        ):
            execution = self._make_execution()
            execution.initialize()
            with self.assertRaisesRegex(sp3b.SP3BBudgetError, "cumulative teardown headroom"):
                execution.admit_row(
                    "SP3B-001",
                    measured_teardown_headroom_seconds=10.0,
                    measured_window_seconds_remaining=60.0,
                )
            self.assertEqual(execution.snapshot()["rows"][0]["state"], "unstarted")

    def test_reached_row_time_cap_stops_and_allows_only_missing_closeout(self) -> None:
        with mock.patch.object(sp3b, "ROW_LIVE_SECONDS_CAP", 100.0):
            execution = self._make_execution()
            execution.initialize()
            safety = self._safety()
            execution.admit_row("SP3B-001", **safety)
            execution.start_live_interval("SP3B-001", **safety)
            self.clock.advance(100)
            stopped = execution.finish_live_interval("SP3B-001")
            self.assertTrue(stopped["control"]["stopped"])
            self.assertEqual(stopped["control"]["stop_reason"], "live_time_cap_reached_during_teardown")
            execution.classify_row(
                "SP3B-001",
                [{"kind": "timing", "code": "row_live_cap", "source": "tmp/evidence/cap.json"}],
            )
            execution.finish_row("SP3B-001", status="BLOCKED", reason_code="time_cap")
            closed = execution.mark_unrun_missing(reason_code="time_cap")
            self.assertTrue(all(row["state"] == "missing" for row in closed["rows"][1:]))
            self.assertEqual(closed["control"]["stop_reason"], "live_time_cap_reached_during_teardown")

    def test_stopping_the_run_marks_only_unrun_rows_missing_with_a_reason(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        self._complete_row(
            execution,
            "SP3B-001",
            [{"kind": "timing", "code": "row_timeout", "source": "tmp/evidence/timeout.json"}],
            charge_attempt=False,
        )
        ledger = execution.mark_unrun_missing(reason_code="operator_stop")
        self.assertTrue(ledger["control"]["stopped"])
        self.assertEqual(ledger["rows"][0]["state"], "terminal")
        self.assertTrue(all(row["state"] == "missing" for row in ledger["rows"][1:]))
        self.assertTrue(all(row["reason_code"] == "operator_stop" for row in ledger["rows"][1:]))

    def test_terminal_row_replay_is_rejected(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        evidence = [{"kind": "timing", "code": "row_timeout", "source": "tmp/evidence/timeout.json"}]
        self._complete_row(execution, "SP3B-001", evidence, charge_attempt=False)
        with self.assertRaisesRegex(sp3b.SP3BError, "immutable pre-content classification"):
            execution.finish_row("SP3B-001", status="BLOCKED", reason_code="replay")
        ledger = execution.snapshot()
        self.assertEqual(ledger["rows"][0]["state"], "terminal")
        self.assertEqual(ledger["rows"][0]["terminal_status"], "BLOCKED")

    def test_restart_time_is_inside_one_live_interval_and_error_attempt_stays_charged(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        safety = self._safety()
        execution.admit_row("SP3B-001", **safety)
        execution.start_live_interval("SP3B-001", **safety)
        execution.admit_provider_attempt("SP3B-001", "startup-error", kind="startup", **safety)
        execution.record_attempt_outcome("startup-error", "error")
        self.clock.advance(600)
        execution.record_restart("SP3B-001")
        self.clock.advance(700)
        ledger = execution.finish_live_interval("SP3B-001")
        self.assertEqual(ledger["rows"][0]["live_elapsed_seconds"], 1300)
        self.assertEqual(ledger["totals"]["sp3b_attempts"], 1)
        self.assertEqual(ledger["totals"]["sp3b_live_seconds"], 1300)
        self.assertEqual(len(ledger["rows"][0]["restart_events"]), 1)

    def test_three_mixed_infrastructure_results_pause_before_row_four_and_resume_is_checked(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        evidence = (
            [{"kind": "process", "code": "sandbox_boot_failed", "source": "tmp/evidence/one.json"}],
            [{"kind": "transport", "code": "tls_failed", "source": "tmp/evidence/two.json"}],
            [{"kind": "provider_status", "code": "http_429", "source": "tmp/evidence/three.json"}],
        )
        for index in range(3):
            self._complete_row(
                execution,
                "SP3B-%03d" % (index + 1),
                evidence[index],
            )
        ledger = execution.snapshot()
        self.assertTrue(ledger["control"]["paused"])
        self.assertEqual(
            ledger["control"]["infrastructure_failure_streak"],
            ["SP3B-001", "SP3B-002", "SP3B-003"],
        )
        self.assertEqual(ledger["totals"]["sp3b_attempts"], 3)
        self.assertEqual(ledger["control"]["pauses"][-1]["triggering_row_ids"], [
            "SP3B-001", "SP3B-002", "SP3B-003"
        ])
        with self.assertRaises(sp3b.SP3BPausedError):
            execution.admit_row("SP3B-004", **self._safety())
        with self.assertRaises(sp3b.SP3BPausedError):
            execution.authorize_resume({"checked": True})

        pause_id = ledger["control"]["pauses"][-1]["pause_id"]
        authorization = {
            "status": "OWNER_REVIEW_CHECKED",
            "checked": True,
            "resume_authorized": True,
            "sp3b_run_id": execution.run_id,
            "pause_id": pause_id,
            "reviewer": "owner-test-review",
            "authorization_id": "review-001",
            "evidence_sha256": "f" * 64,
        }
        resumed = execution.authorize_resume(authorization)
        self.assertFalse(resumed["control"]["paused"])
        self.assertEqual(resumed["control"]["infrastructure_failure_streak"], [])
        self.assertEqual(resumed["totals"]["sp3b_attempts"], 3)
        execution.admit_row("SP3B-004", **self._safety())

    def test_non_infrastructure_classification_breaks_infrastructure_streak(self) -> None:
        execution = self._make_execution()
        execution.initialize()
        decisions = (
            [{"kind": "process", "code": "listener_failed", "source": "tmp/evidence/one.json"}],
            [{"kind": "timing", "code": "row_live_cap", "source": "tmp/evidence/two.json"}],
            [{"kind": "transport", "code": "dns_failed", "source": "tmp/evidence/three.json"}],
            [{"kind": "provider_status", "code": "http_5xx", "source": "tmp/evidence/four.json"}],
            [{"kind": "process", "code": "sandbox_prepare_failed", "source": "tmp/evidence/five.json"}],
        )
        for index, evidence in enumerate(decisions, start=1):
            self._complete_row(execution, "SP3B-%03d" % index, evidence, charge_attempt=False)
        ledger = execution.snapshot()
        self.assertTrue(ledger["control"]["paused"])
        self.assertEqual(
            ledger["control"]["pauses"][-1]["triggering_row_ids"],
            ["SP3B-003", "SP3B-004", "SP3B-005"],
        )

    def test_default_ledger_root_cannot_be_changed_to_reset_the_cumulative_budget(self) -> None:
        with self.assertRaisesRegex(sp3b.SP3BError, "one stable cumulative ledger root"):
            sp3b.SP3BExecution(
                "sp3b-other-root",
                ledger_root=Path("tmp") / ("alternate_" + uuid.uuid4().hex),
                identity_provider=lambda: copy.deepcopy(self.identity),
            )
        execution = self._make_execution()
        execution.initialize()
        second_run = sp3b.SP3BExecution(
            "sp3b-another-run",
            identity_provider=lambda: copy.deepcopy(self.identity),
            monotonic=self.clock.monotonic,
            wall_clock=self.clock.wall_clock,
        )
        with self.assertRaises(sp3b.SP3BError):
            second_run.initialize()


class MappingPilotSP3BEvidenceTests(unittest.TestCase):
    """Provider-free H2 contracts; lifecycle-profile approval remains separate."""

    @classmethod
    def setUpClass(cls) -> None:
        from scripts.mapping_pilot import sp3b_evidence

        cls.evidence = sp3b_evidence

    def setUp(self) -> None:
        self.root = PROJECT_ROOT / "tmp" / ("sp3b_evidence_test_" + uuid.uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        socket_patch = mock.patch.object(
            socket, "socket", side_effect=AssertionError("socket use forbidden")
        )
        popen_patch = mock.patch.object(
            subprocess, "Popen", side_effect=AssertionError("process launch forbidden")
        )
        subprocess_patch = mock.patch.object(
            subprocess, "run", side_effect=AssertionError("subprocess use forbidden")
        )
        forbidden_imports = {
            name: None
            for name in (
                "scripts.mapping_pilot.server",
                "scripts.mapping_pilot.launcher",
                "scripts.mapping_pilot.live_client",
                "scripts.mapping_pilot.row_runner",
                "scripts.seed_combat_capture",
                "utils.ai_client_factory",
                "utils.llm_router",
                "requests",
                "httpx",
            )
        }
        imports_patch = mock.patch.dict(sys.modules, forbidden_imports)
        for patcher in (socket_patch, popen_patch, subprocess_patch, imports_patch):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _time(second: int, *, minute: int = 0) -> str:
        return "2026-11-06T12:%02d:%02d.000000Z" % (minute, second)

    def _k2_evidence(self, party_size: int = 1) -> dict[str, Any]:
        actor = "Acheron" if party_size == 1 else "Merisiel"
        row_number = 12 if party_size == 1 else 16
        row_id = "SP3B-%03d" % row_number
        run_id = "sp3b-evidence-test"
        row_run_id = "k2-row-run-%d" % party_size
        lifecycle_id = "k2-lifecycle-%d" % party_size
        state_files = {
            "party_tracker.json": "a" * 64,
            "characters/%s.json" % actor: "b" * 64,
            "modules/Mapping_Pilot_Arena/areas/area_01.json": "c" * 64,
            "modules/encounters/encounter_mpv2_k2_encounter.json": "d" * 64,
        }
        state_hash = hashlib_sha256(
            json.dumps(
                state_files,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        state_snapshot = {
            "status": "recorded",
            "sha256": state_hash,
            "files": copy.deepcopy(state_files),
        }
        observer = {
            "status": "complete",
            "source": "scripts.mapping_pilot.server.install_router_receipt_observer",
            "run_id": run_id,
            "row_id": row_id,
            "row_run_id": row_run_id,
            "lifecycle_id": lifecycle_id,
            "started_at_utc": self._time(0),
            "finished_at_utc": self._time(5),
            "max_receipts": 35,
            "receipt_count": 0,
            "receipt_sequences": [],
            "observer_errors": 0,
            "step": {
                "step_id": "K2-02",
                "status": "complete",
                "started_at_utc": self._time(1),
                "finished_at_utc": self._time(3),
                "request_count": 0,
            },
        }
        before = {
            "captured_at_utc": "2026-11-06T12:00:00.500000Z",
            "snapshot": copy.deepcopy(state_snapshot),
        }
        after = {
            "captured_at_utc": "2026-11-06T12:00:03.500000Z",
            "snapshot": copy.deepcopy(state_snapshot),
        }
        return {
            "identity": {
                "run_id": run_id,
                "row_id": row_id,
                "source_cell": "C%02d" % (row_number - 11),
                "row_run_id": row_run_id,
                "lifecycle_id": lifecycle_id,
                "step_id": "K2-02",
                "party_size": party_size,
            },
            "consumed_input": {
                "status": "consumed",
                "step_id": "K2-02",
                "text": "Disengage from melee.",
                "source": "core.combat.turn.prepare_combat_normal_turn",
            },
            "actor": {
                "actor_id": actor,
                "name": actor,
                "source": "core.combat.decisions.resolve_pc_action_actor",
            },
            "actual_action": {
                "status": "handled",
                "input_text": "Disengage from melee.",
                "actor_name": actor,
                "source": "core.combat.decisions.run_pc_action_decision",
                "parser_source": "utils.combat_pc_action_parser.parse_pc_phase_action",
                "apply_source": "utils.combat_pc_action_parser.apply_pc_phase_parse_result",
                "parse_result": {
                    "handled": True,
                    "kind": "movement",
                    "mechanical_feedback": None,
                    "spoken_narration": "Dungeon Master: %s disengages from melee." % actor,
                    "log_msg": "[ALREADY_APPLIED] [System: %s disengage.]" % actor,
                    "ledger_event": {"kind": "movement", "facts": {}},
                    "fallback_reason": "",
                    "target_name": None,
                    "parsed_attack_roll": None,
                    "parsed_heal_amount": None,
                    "weapon_name": None,
                    "character_updates": [],
                    "encounter_ops": [],
                    "changes_text": "",
                },
                "applied_event": {
                    "kind": "movement",
                    "actor_name": actor,
                    "target_name": None,
                    "facts": {},
                    "narration": "%s disengages from melee." % actor,
                    "mechanics_already_applied": True,
                },
            },
            "canonical_state": {"before": before, "after": after},
            "request_observer": observer,
            "receipts": [],
        }

    def _zone_event(
        self,
        *,
        kind: str = "movement_hint",
        second: int = 1,
        actor_id: str = "Acheron",
        row_run_id: str = "k2-zone-run",
        lifecycle_id: str = "k2-zone-lifecycle",
    ) -> dict[str, Any]:
        if kind == "movement_hint":
            source = {
                "status": "recorded",
                "kind": "movement_hint_observer_record",
                "reference": "mapping_pilot/movement_observations/%s/record-000001.json"
                % row_run_id,
            }
            payload = {
                "status": "valid",
                "hint": {
                    "from": "MPV2_Z_BAR",
                    "to": "MPV2_Z_ENTRY",
                    "disengage": True,
                    "cover_sought": "none",
                },
                "reason": None,
            }
            step_id = "K2-02"
        elif kind == "enemy_phase":
            actor_id = "MPV2_ENEMY_MELEE_ALPHA"
            source = {
                "status": "recorded",
                "kind": "applied_enemy_phase_result",
                "reference": "row_runner._apply_fixture_control/K2-03",
            }
            payload = {
                "status": "applied",
                "applied": True,
                "fact": {
                    "actor_id": actor_id,
                    "status": "moved",
                    "from_zone": "MPV2_Z_FLOOR",
                    "to_zone": "MPV2_Z_ENTRY",
                    "target_actor_id": "Acheron",
                    "path": ["MPV2_Z_FLOOR", "MPV2_Z_ENTRY"],
                    "reason": "advanced_one_fixture_adjacency_step",
                },
                "reason": None,
            }
            step_id = "K2-03"
        else:
            actor_id = "unknown"
            source = {
                "status": "missing",
                "kind": None,
                "reference": None,
                "reason": "movement_observer_record_missing",
            }
            payload = {
                "subject": "movement_hint",
                "status": "unknown",
                "reason": "movement_observer_record_missing",
            }
            kind = "unknown"
            step_id = "K2-04"
        return {
            "run_id": "sp3b-zone-test",
            "row_id": "SP3B-012",
            "row_run_id": row_run_id,
            "lifecycle_id": lifecycle_id,
            "step_id": step_id,
            "actor_id": actor_id,
            "kind": kind,
            "source": source,
            "observed_at_utc": "2026-11-06T12:00:%02d.000000Z" % second,
            "payload": payload,
        }

    def test_k2_02_correlation_is_valid_for_p1_and_p4(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                result = self.evidence.correlate_k2_02(self._k2_evidence(party_size))
                self.assertEqual(result["evidence_status"], "recorded")
                self.assertEqual(
                    result["model_call_status"],
                    "N/A (deterministic, no model call)",
                )
                self.assertEqual(result["request_coverage"]["receipt_count"], 0)
                self.assertEqual(result["request_coverage"]["k2_02_request_count"], 0)
                self.assertTrue(result["canonical_state"]["canonical_files_unchanged"])
                self.assertEqual(
                    result["canonical_state"]["before"]["snapshot"]["files"],
                    result["canonical_state"]["after"]["snapshot"]["files"],
                )

    def test_k2_02_n_a_is_step_scoped_not_a_zero_row_receipt_claim(self) -> None:
        payload = self._k2_evidence()
        payload["receipts"] = [
            {
                "event_type": "router_receipt",
                "row_run_id": "k2-row-run-1",
                "lifecycle_id": "k2-lifecycle-1",
                "sequence": 1,
                "call_id": "startup-call",
                "attempt_id": "startup-attempt",
                "attribution": "lifecycle_control",
                "attribution_status": "recorded",
                "provider_call_expected": False,
                "script_step_id": "startup",
            }
        ]
        payload["request_observer"]["receipt_count"] = 1
        payload["request_observer"]["receipt_sequences"] = [1]
        result = self.evidence.correlate_k2_02(payload)
        self.assertEqual(result["request_coverage"]["receipt_count"], 1)
        self.assertEqual(result["request_coverage"]["k2_02_request_count"], 0)
        self.assertEqual(result["request_coverage"]["receipts"][0]["script_step_id"], "startup")
        self.assertEqual(
            result["model_call_status"], "N/A (deterministic, no model call)"
        )

    def test_k2_02_uses_real_deterministic_disengage_parser_without_provider(self) -> None:
        from core.combat.decisions import run_pc_action_decision

        class FakeManager:
            def __init__(self) -> None:
                self.events: list[dict[str, Any]] = []

            def record_pc_phase_event(self, **event: Any) -> dict[str, Any]:
                self.events.append(dict(event))
                return dict(event)

        for actor in ("Acheron", "Merisiel"):
            with self.subTest(actor=actor):
                manager = FakeManager()
                traces: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
                result = run_pc_action_decision(
                    eligible=True,
                    clean_input="Disengage from melee.",
                    encounter_data={"creatures": []},
                    party_tracker_data={"partyMembers": [actor]},
                    actor_name=actor,
                    multi_pc_manager=manager,
                    encounter_id="k2-test-encounter",
                    decision_started_at=1.0,
                    trace_decision=lambda *args, **kwargs: traces.append((args, kwargs)),
                )
                self.assertEqual(result.status.value, "handled")
                self.assertEqual(result.parse_result["kind"], "movement")
                self.assertFalse(result.parse_result["encounter_ops"])
                self.assertFalse(result.parse_result["character_updates"])
                self.assertTrue(result.parse_result["spoken_narration"].startswith("Dungeon Master: "))
                self.assertEqual(manager.events[0]["kind"], "movement")
                self.assertEqual(manager.events[0]["actor_name"], actor)
                self.assertEqual(traces[-1][1]["llm_fallback"], False)
                party_size = 1 if actor == "Acheron" else 4
                payload = self._k2_evidence(party_size)
                payload["actual_action"] = {
                    "status": result.status.value,
                    "input_text": "Disengage from melee.",
                    "actor_name": result.actor_name,
                    "source": "core.combat.decisions.run_pc_action_decision",
                    "parser_source": "utils.combat_pc_action_parser.parse_pc_phase_action",
                    "apply_source": "utils.combat_pc_action_parser.apply_pc_phase_parse_result",
                    "parse_result": result.parse_result,
                    "applied_event": manager.events[0],
                }
                self.assertEqual(
                    self.evidence.correlate_k2_02(payload)["actual_action"]["parse_result"]["kind"],
                    "movement",
                )

    def test_zero_receipts_without_complete_observer_coverage_is_not_na(self) -> None:
        cases = []
        missing = self._k2_evidence()
        missing["request_observer"]["status"] = "missing"
        cases.append(missing)
        incomplete_step = self._k2_evidence()
        incomplete_step["request_observer"]["step"]["status"] = "missing"
        cases.append(incomplete_step)
        wrong_count = self._k2_evidence()
        wrong_count["request_observer"]["receipt_count"] = 1
        cases.append(wrong_count)
        over_bound = self._k2_evidence()
        over_bound["request_observer"]["max_receipts"] = 36
        cases.append(over_bound)
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(self.evidence.SP3BEvidenceError):
                    self.evidence.correlate_k2_02(payload)

    def test_k2_02_rejects_missing_or_mismatched_input_actor_and_action(self) -> None:
        cases = []
        wrong_input = self._k2_evidence()
        wrong_input["consumed_input"]["text"] = "Move away."
        cases.append(wrong_input)
        not_consumed = self._k2_evidence()
        not_consumed["consumed_input"]["status"] = "sent"
        cases.append(not_consumed)
        wrong_actor = self._k2_evidence()
        wrong_actor["actor"]["name"] = "Merisiel"
        cases.append(wrong_actor)
        wrong_action_input = self._k2_evidence()
        wrong_action_input["actual_action"]["input_text"] = "Move away."
        cases.append(wrong_action_input)
        declined = self._k2_evidence()
        declined["actual_action"]["status"] = "declined"
        cases.append(declined)
        missing_output = self._k2_evidence()
        missing_output["actual_action"]["parse_result"]["spoken_narration"] = ""
        cases.append(missing_output)
        wrong_applied_event = self._k2_evidence()
        wrong_applied_event["actual_action"]["applied_event"]["actor_name"] = "Merisiel"
        cases.append(wrong_applied_event)
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(self.evidence.SP3BEvidenceError):
                    self.evidence.correlate_k2_02(payload)

    def test_k2_02_rejects_bad_identity_canonical_state_and_fabricated_hint(self) -> None:
        wrong_row = self._k2_evidence()
        wrong_row["identity"]["source_cell"] = "C02"
        wrong_party = self._k2_evidence()
        wrong_party["identity"]["party_size"] = 4
        changed_state = self._k2_evidence()
        changed_files = changed_state["canonical_state"]["after"]["snapshot"]["files"]
        changed_files["party_tracker.json"] = "e" * 64
        changed_state["canonical_state"]["after"]["snapshot"]["sha256"] = hashlib_sha256(
            json.dumps(
                changed_files,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        missing_state = self._k2_evidence()
        del missing_state["canonical_state"]["after"]
        fabricated_hint = self._k2_evidence()
        fabricated_hint["movement_hint"] = {
            "from": "MPV2_Z_BAR",
            "to": "MPV2_Z_ENTRY",
            "disengage": True,
            "cover_sought": "none",
        }
        for payload in (wrong_row, wrong_party, changed_state, missing_state, fabricated_hint):
            with self.subTest(payload=payload):
                with self.assertRaises(self.evidence.SP3BEvidenceError):
                    self.evidence.correlate_k2_02(payload)

    def test_k2_02_requires_all_receipts_to_be_bounded_and_linked(self) -> None:
        wrong_link = self._k2_evidence()
        wrong_link["receipts"] = [
            {
                "event_type": "router_receipt",
                "row_run_id": "another-row-run",
                "lifecycle_id": "k2-lifecycle-1",
                "sequence": 1,
                "call_id": "call-startup",
                "attempt_id": "attempt-startup",
                "attribution": "lifecycle_control",
                "attribution_status": "recorded",
                "provider_call_expected": False,
                "script_step_id": None,
            }
        ]
        wrong_link["request_observer"]["receipt_count"] = 1
        wrong_link["request_observer"]["receipt_sequences"] = [1]

        unknown_attribution = self._k2_evidence()
        receipt = copy.deepcopy(wrong_link["receipts"][0])
        receipt["row_run_id"] = "k2-row-run-1"
        receipt["attribution"] = "unknown"
        unknown_attribution["receipts"] = [receipt]
        unknown_attribution["request_observer"]["receipt_count"] = 1
        unknown_attribution["request_observer"]["receipt_sequences"] = [1]

        target_call = self._k2_evidence()
        target_call["receipts"] = [
            {
                "event_type": "router_receipt",
                "row_run_id": "k2-row-run-1",
                "lifecycle_id": "k2-lifecycle-1",
                "sequence": 1,
                "call_id": "call-k2-02",
                "attempt_id": "attempt-k2-02",
                "attribution": "model_bearing_turn",
                "attribution_status": "recorded",
                "provider_call_expected": True,
                "script_step_id": "K2-02",
            }
        ]
        target_call["request_observer"]["receipt_count"] = 1
        target_call["request_observer"]["receipt_sequences"] = [1]
        target_call["request_observer"]["step"]["request_count"] = 1

        for payload in (wrong_link, unknown_attribution, target_call):
            with self.subTest(payload=payload):
                with self.assertRaises(self.evidence.SP3BEvidenceError):
                    self.evidence.correlate_k2_02(payload)

    def test_zone_events_persist_in_order_with_hint_enemy_phase_and_unknown(self) -> None:
        first = self.evidence.append_zone_event(self.root, self._zone_event(second=1))
        second = self.evidence.append_zone_event(
            self.root,
            self._zone_event(kind="enemy_phase", second=2),
        )
        third = self.evidence.append_zone_event(
            self.root,
            self._zone_event(kind="unknown", second=3),
        )
        records = self.evidence.read_zone_events(
            self.root,
            run_id="sp3b-zone-test",
            row_id="SP3B-012",
            row_run_id="k2-zone-run",
            lifecycle_id="k2-zone-lifecycle",
        )
        self.assertEqual([row["sequence"] for row in records], [1, 2, 3])
        self.assertEqual([row["kind"] for row in records], ["movement_hint", "enemy_phase", "unknown"])
        self.assertEqual(first["payload"]["hint"]["disengage"], True)
        self.assertIs(second["payload"]["applied"], True)
        self.assertEqual(third["source"]["status"], "missing")
        self.assertTrue(all(row["row_id"] == "SP3B-012" for row in records))
        self.assertTrue(all(row["lifecycle_id"] == "k2-zone-lifecycle" for row in records))

    def test_zone_events_reject_empty_success_missing_linkage_actor_or_source(self) -> None:
        directory = (
            self.root
            / "mapping_pilot"
            / "zone_events"
            / "k2-zone-run"
            / "k2-zone-lifecycle"
        )
        directory.mkdir(parents=True)
        with self.assertRaisesRegex(self.evidence.SP3BEvidenceError, "empty zone trace"):
            self.evidence.read_zone_events(
                self.root,
                run_id="sp3b-zone-test",
                row_id="SP3B-012",
                row_run_id="k2-zone-run",
                lifecycle_id="k2-zone-lifecycle",
            )

        missing_actor = self._zone_event()
        missing_actor["actor_id"] = None
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.append_zone_event(self.root, missing_actor)

        missing_source = self._zone_event()
        missing_source["source"] = {
            "status": "missing",
            "kind": None,
            "reference": None,
            "reason": "source_missing",
        }
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.append_zone_event(self.root, missing_source)

        unknown_source = self._zone_event(kind="unknown")
        unknown_source["source"]["reason"] = "movement_observer_record_missing"
        unknown_source["payload"]["reason"] = "movement_observer_record_missing"
        recorded = self.evidence.append_zone_event(self.root, unknown_source)
        self.assertEqual(recorded["kind"], "unknown")
        self.assertEqual(recorded["payload"]["status"], "unknown")

        mismatched_unknown = self._zone_event(kind="unknown", second=2)
        mismatched_unknown["source"]["reason"] = "enemy_phase_record_missing"
        with self.assertRaisesRegex(self.evidence.SP3BEvidenceError, "reasons differ"):
            self.evidence.append_zone_event(self.root, mismatched_unknown)

        unlinked = self._zone_event(second=2)
        unlinked["row_id"] = "SP3B-013"
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.append_zone_event(self.root, unlinked)

    def test_zone_events_reject_invalid_applied_facts_time_order_and_tampering(self) -> None:
        invalid_fact = self._zone_event(kind="enemy_phase", second=1)
        invalid_fact["payload"]["fact"]["path"] = []
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.append_zone_event(self.root, invalid_fact)

        missing_hint_with_payload = self._zone_event()
        missing_hint_with_payload["payload"] = {
            "status": "missing",
            "hint": {
                "from": "MPV2_Z_BAR",
                "to": "MPV2_Z_ENTRY",
                "disengage": True,
                "cover_sought": "none",
            },
            "reason": "observer_payload_missing",
        }
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.append_zone_event(self.root, missing_hint_with_payload)

        first = self.evidence.append_zone_event(self.root, self._zone_event(second=2))
        saved_first = (
            self.root
            / "mapping_pilot"
            / "zone_events"
            / "k2-zone-run"
            / "k2-zone-lifecycle"
            / "record-00000001.json"
        ).read_bytes()
        with self.assertRaisesRegex(self.evidence.SP3BEvidenceError, "strictly later"):
            self.evidence.append_zone_event(self.root, self._zone_event(second=2))
        self.evidence.append_zone_event(self.root, self._zone_event(second=3))
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(
            (
                self.root
                / "mapping_pilot"
                / "zone_events"
                / "k2-zone-run"
                / "k2-zone-lifecycle"
                / "record-00000001.json"
            ).read_bytes(),
            saved_first,
        )

        record_path = (
            self.root
            / "mapping_pilot"
            / "zone_events"
            / "k2-zone-run"
            / "k2-zone-lifecycle"
            / "record-00000001.json"
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["observed_at_utc"] = "2026-11-06T12:00:04.000000Z"
        record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        with self.assertRaises(self.evidence.SP3BEvidenceError):
            self.evidence.read_zone_events(
                self.root,
                run_id="sp3b-zone-test",
                row_id="SP3B-012",
                row_run_id="k2-zone-run",
                lifecycle_id="k2-zone-lifecycle",
            )

    def test_zone_event_atomic_write_failure_does_not_report_success(self) -> None:
        with mock.patch(
            "utils.file_operations.safe_write_json",
            return_value=False,
        ):
            with self.assertRaisesRegex(self.evidence.SP3BEvidenceError, "atomic"):
                self.evidence.append_zone_event(self.root, self._zone_event())
        event_directory = (
            self.root
            / "mapping_pilot"
            / "zone_events"
            / "k2-zone-run"
            / "k2-zone-lifecycle"
        )
        self.assertFalse(list(event_directory.glob("record-*.json")))


def hashlib_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    unittest.main()
