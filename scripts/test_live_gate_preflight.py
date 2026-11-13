# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic invocation-boundary and provider-free router tests."""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.live_gate_preflight_stub as router_stub_module
from scripts import live_gate_preflight_sandbox as sandbox_preparation
from scripts import live_gate_preflight_profile_runner as profile_runner
import scripts.live_gate_preflight_safety as preflight_safety
from scripts.live_gate_preflight_safety import (
    NetworkGuardError,
    compare_invocation_identity,
    expected_guarded_pythonpath,
)
from scripts.live_gate_preflight_stub import (
    FailClosedRouterStub,
    RouterStubError,
    install_fail_closed_router_stub,
)


def _identity() -> dict[str, Any]:
    return {
        "command": [
            sys.executable,
            "-m",
            "scripts.mapping_pilot.worker",
            "--token=synthetic-secret-command-value",
        ],
        "working_directory": "/workspace/tmp/capture-secret-directory",
        "pythonpath": os.pathsep.join(
            (
                "/workspace/scripts/guard-secret-entry",
                "/workspace/repository-secret-root",
            )
        ),
    }


class TestRealSandboxPreparationBoundary(unittest.TestCase):
    @staticmethod
    def _seed_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        from scripts.mapping_pilot.fixtures import FIXTURE_FILES

        expected = {
            fixture_id: {
                "fixture_id": fixture_id,
                "source_file": source_file,
                "source_truth": {"fixture_id": fixture_id, "location_ids": ["SRC01"]},
            }
            for fixture_id, source_file in FIXTURE_FILES.items()
        }
        module_payloads = {
            "areas/MPA001.json": {
                "areaId": "MPA001",
                "areaName": "Synthetic Test Area",
                "locations": [{"locationId": "MP01", "name": "Synthetic Test Room"}],
            },
            "map_MPA001.json": {
                "rooms": [{"id": "MP01"}],
                "startRoom": "wrong-room",
            },
            "location_id_map.json": {"runtime_location_ids": {"SRC01": "MP01"}},
        }
        plan = {
            "fixture_id": "interior_tavern",
            "arm": "A",
            "party_size": 1,
            "effective_seed": 42,
            "fixture": {},
            "source_location_id": "SRC01",
            "runtime_location_id": "MP01",
            "counterbalance": {
                "row_id": "E01",
                "row_type": "planned",
                "block": 1,
                "script": "scripts/interior.json",
                "fixed_seed": 42,
            },
        }
        return plan, module_payloads, expected

    @staticmethod
    def _worker_identity(project_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
        run_id = "pf-seed-boundary-01"
        with mock.patch.object(
            profile_runner, "_repository_python", return_value=sys.executable
        ):
            command = profile_runner._host_command(
                fixture_id=str(plan["fixture_id"]),
                party_size=int(plan["party_size"]),
                lifecycle="startup",
                source_sha="a" * 40,
                run_id=run_id,
                planned_row_id=str(plan["counterbalance"]["row_id"]),
                arm=str(plan["arm"]),
                lifecycle_id=run_id + "_s",
                resume_checkpoint_sha256=None,
            )
        return {
            "command": command,
            "working_directory": str(project_root / "tmp" / "combat_capture"),
            "pythonpath": expected_guarded_pythonpath(project_root),
        }

    @staticmethod
    def _entrypoint_args(intended: dict[str, Any]) -> list[str]:
        return [
            "--prepare",
            "--fixture-id",
            "interior_tavern",
            "--party-size",
            "1",
            "--planned-row-id",
            "E01",
            "--lifecycle",
            "startup",
            "--source-sha",
            "a" * 40,
            "--run-id",
            "pf-seed-boundary-01",
            "--intended-host-identity-json",
            json.dumps(intended, ensure_ascii=True, sort_keys=True),
        ]

    def test_each_identity_mismatch_blocks_actual_seed_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="preflight-seed-mismatch-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            project = Path(temporary_root)
            (project / "tmp").mkdir()
            plan, module_payloads, expected_payloads = self._seed_inputs()
            planned = self._worker_identity(project, plan)
            mismatched_values = {
                "command": [*planned["command"], "--row=E02"],
                "working_directory": str(project / "other" / "capture-secret-directory"),
                "pythonpath": planned["pythonpath"] + os.pathsep + "/other/guard",
            }
            for field, changed_value in mismatched_values.items():
                with self.subTest(field=field):
                    intended = copy.deepcopy(planned)
                    intended[field] = changed_value
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(sandbox_preparation, "PROJECT_ROOT", project),
                        mock.patch.object(
                            sandbox_preparation, "_require_preparation_startup_guard"
                        ),
                        mock.patch.object(
                            sandbox_preparation,
                            "_load_profile_seed_plan",
                            return_value=(plan, {"profile_id": "interior_tavern:p1"}),
                        ),
                        mock.patch.object(
                            sandbox_preparation,
                            "_load_profile_seed_inputs",
                            return_value=(module_payloads, expected_payloads),
                        ),
                        mock.patch.object(
                            profile_runner, "_repository_python", return_value=sys.executable
                        ),
                        mock.patch.object(
                            sandbox_preparation, "_prepare_new_sandbox"
                        ) as seed,
                        redirect_stderr(stderr),
                        redirect_stdout(io.StringIO()),
                    ):
                        exit_code = sandbox_preparation.main(
                            self._entrypoint_args(intended)
                        )

                    self.assertEqual(exit_code, 1)
                    seed.assert_not_called()
                    self.assertFalse((project / "tmp" / "combat_capture").exists())
                    diagnostic = stderr.getvalue()
                    self.assertTrue(diagnostic.startswith("[FAIL] profile_sandbox="))
                    self.assertNotIn("capture-secret-directory", diagnostic)
                    failure = json.loads(diagnostic.split("=", 1)[1])
                    self.assertEqual(
                        failure["failure_code"], "invocation_identity_mismatch"
                    )
                    evidence = failure["identity_evidence"]
                    self.assertEqual(
                        [item["field"] for item in evidence["mismatches"]], [field]
                    )
                    self.assertEqual(evidence["status"], "blocked")

    def test_matching_identity_runs_original_seed_flow(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="preflight-seed-match-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            project = Path(temporary_root)
            (project / "tmp").mkdir()
            plan, module_payloads, expected_payloads = self._seed_inputs()
            identity = self._worker_identity(project, plan)
            from scripts.mapping_pilot import launcher

            original_seed = sandbox_preparation._prepare_new_sandbox
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(sandbox_preparation, "PROJECT_ROOT", project),
                mock.patch.object(
                    sandbox_preparation, "_require_preparation_startup_guard"
                ),
                mock.patch.object(
                    sandbox_preparation,
                    "_load_profile_seed_plan",
                    return_value=(plan, {"profile_id": "interior_tavern:p1"}),
                ) as load_plan,
                mock.patch.object(
                    sandbox_preparation,
                    "_load_profile_seed_inputs",
                    return_value=(module_payloads, expected_payloads),
                ),
                mock.patch.object(
                    profile_runner, "_repository_python", return_value=sys.executable
                ),
                mock.patch.object(sandbox_preparation, "_copy_runtime"),
                mock.patch.object(launcher, "validate_sandbox"),
                mock.patch.object(
                    sandbox_preparation,
                    "_prepare_new_sandbox",
                    wraps=original_seed,
                ) as seed,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = sandbox_preparation.main(
                    self._entrypoint_args(copy.deepcopy(identity))
                )

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0, stderr.getvalue())
            load_plan.assert_called_once_with("interior_tavern", 1, "E01")
            seed.assert_called_once()
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["invocation_identity"]["status"], "matched")
            sandbox = project / "tmp" / "combat_capture"
            self.assertTrue((sandbox / "config.py").is_file())
            self.assertTrue((sandbox / "mapping_pilot" / "seed_metadata.json").is_file())


class TestRealWorkerLaunchBoundary(unittest.TestCase):
    def test_each_identity_mismatch_blocks_actual_worker_launch(self) -> None:
        declared = {
            "command": [sys.executable, "-m", "worker", "--row", "E01"],
            "working_directory": str(PROJECT_ROOT / "tmp" / "combat_capture"),
            "pythonpath": os.pathsep.join(
                (
                    str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
                    str(PROJECT_ROOT),
                )
            ),
        }
        mismatched_values = {
            "command": [*declared["command"], "--row=E02"],
            "working_directory": str(PROJECT_ROOT / "tmp" / "other-worker"),
            "pythonpath": declared["pythonpath"] + os.pathsep + "other-root",
        }
        from scripts.mapping_pilot import server

        args = argparse.Namespace(
            worker=True,
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            source_sha="a" * 40,
            run_id="identity-worker-test",
            planned_row_id="E01",
            arm="A",
            lifecycle_id="identity-worker-test_s",
            resume_checkpoint_sha256=None,
        )

        for field, changed_value in mismatched_values.items():
            with self.subTest(field=field):
                intended = copy.deepcopy(declared)
                intended[field] = changed_value
                saved_result: dict[str, Any] = {}
                safe_environment = {
                    "PYTHONPATH": declared["pythonpath"],
                    **{name: "" for name in profile_runner._KNOWN_PROVIDER_KEYS},
                }
                with (
                    mock.patch.object(
                        profile_runner, "_require_worker_startup_guard"
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_require_safe_worker_root",
                        return_value=PROJECT_ROOT,
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_host_command",
                        return_value=declared["command"],
                    ),
                    mock.patch.object(
                        preflight_safety,
                        "current_invocation_identity",
                        return_value=intended,
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_write_json",
                        side_effect=lambda _path, value: saved_result.update(value),
                    ),
                    mock.patch.object(profile_runner.os, "environ", safe_environment),
                    mock.patch.object(server, "launch_worker") as launch,
                ):
                    exit_code = profile_runner.main(
                        [
                            "--worker",
                            "--fixture-id",
                            args.fixture_id,
                            "--party-size",
                            str(args.party_size),
                            "--lifecycle",
                            args.lifecycle,
                            "--source-sha",
                            args.source_sha,
                            "--run-id",
                            args.run_id,
                            "--planned-row-id",
                            args.planned_row_id,
                            "--arm",
                            args.arm,
                            "--lifecycle-id",
                            args.lifecycle_id,
                        ]
                    )

                self.assertEqual(exit_code, 1)
                self.assertEqual(saved_result["failure_code"], "invocation_identity_mismatch")
                self.assertEqual(saved_result["outcome"], "failed")
                self.assertEqual(saved_result["calls"], [])
                self.assertEqual(launch.call_count, 0)
                self.assertEqual(
                    [
                        item["field"]
                        for item in saved_result["invocation_identity"]["mismatches"]
                    ],
                    [field],
                )
                self.assertNotIn("other-root", repr(saved_result["invocation_identity"]))


class _CounterRouter:
    def __init__(self) -> None:
        self.upstream_requests = 0
        self.provider_budget_remaining = 3
        self.live_attempts_used = 1

    def call(self, _task: str, *_args: Any, **_kwargs: Any) -> str:
        self.upstream_requests += 1
        self.provider_budget_remaining -= 1
        self.live_attempts_used += 1
        return "upstream response"


class TestProviderFreeRouterBoundary(unittest.TestCase):
    @staticmethod
    def _make_stub() -> FailClosedRouterStub:
        with mock.patch.object(router_stub_module, "_require_network_guard"):
            return FailClosedRouterStub(
                source_sha="a" * 40,
                responses={"narration": {"text": "A declared test response."}},
                command=[sys.executable, "-m", "worker"],
                pythonpath=os.pathsep.join(("guard", "repository")),
            )

    def test_stub_response_does_not_reach_upstream_or_consume_counters(self) -> None:
        router = _CounterRouter()
        original_call = router.call
        stub = self._make_stub()
        counters_before = (
            router.upstream_requests,
            router.provider_budget_remaining,
            router.live_attempts_used,
        )

        with mock.patch.object(router_stub_module, "_require_network_guard"):
            cleanup = install_fail_closed_router_stub(router, stub)
        try:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                response = router.call("narration", prompt="not recorded")
        finally:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                cleanup()

        self.assertEqual(response, {"text": "A declared test response."})
        self.assertEqual(stub.call_count, 1)
        self.assertEqual(
            (
                router.upstream_requests,
                router.provider_budget_remaining,
                router.live_attempts_used,
            ),
            counters_before,
        )
        self.assertEqual(router.call, original_call)

    def test_unknown_router_task_fails_closed_without_upstream_use(self) -> None:
        router = _CounterRouter()
        stub = self._make_stub()
        with mock.patch.object(router_stub_module, "_require_network_guard"):
            cleanup = install_fail_closed_router_stub(router, stub)
        try:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                with self.assertRaisesRegex(
                    RouterStubError, "no explicit stub response"
                ):
                    router.call("undeclared_task")
        finally:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                cleanup()

        self.assertEqual(stub.call_count, 1)
        self.assertEqual(stub.failure_code, "router_task_has_no_stub_response")
        self.assertEqual(router.upstream_requests, 0)
        self.assertEqual(router.provider_budget_remaining, 3)
        self.assertEqual(router.live_attempts_used, 1)

    def test_router_stub_installation_requires_network_guard(self) -> None:
        router = _CounterRouter()
        original_call = router.call
        stub = self._make_stub()

        with mock.patch.object(
            router_stub_module,
            "require_guard_active",
            side_effect=NetworkGuardError("guard is unavailable"),
        ):
            with self.assertRaisesRegex(RouterStubError, "requires the active"):
                install_fail_closed_router_stub(router, stub)

        self.assertEqual(router.call, original_call)
        self.assertEqual(router.upstream_requests, 0)


class TestIdentityComparison(unittest.TestCase):
    def test_mismatch_evidence_names_fields_without_raw_identity_values(self) -> None:
        declared = _identity()
        intended = copy.deepcopy(declared)
        intended["working_directory"] = "/different/secret-path"

        evidence = compare_invocation_identity(declared, intended)

        self.assertEqual(evidence["status"], "blocked")
        self.assertEqual(evidence["mismatches"][0]["field"], "working_directory")
        serialized = repr(evidence)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("workspace", serialized)


if __name__ == "__main__":
    unittest.main()
