# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic tests for the supervised preflight runner entry point."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import live_gate_preflight_comparison_identity as identity_module
from scripts import live_gate_preflight_controller as controller
from scripts import live_gate_preflight_run as run_module


SHA = "c" * 40
TREE = "d" * 40
RUN_ID = "run-entry-test"


def _args(*argv: str):
    return run_module.build_parser().parse_args(list(argv))


def _fake_report(status: str = "completed", **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "row_results": [{"row_id": "E%02d" % i, "status": "completed"} for i in range(26)],
        "preflight_evidence_path": "tmp/router-rollout/live-gate-preflight/x/preflight/report.json",
        "booking_eligible": False,
        "live_gate_pass": False,
        **extra,
    }


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _gate(loads: list[tuple[float, float, float]], wait: float = 1800) -> run_module.LoadGate:
    clock = _Clock()
    samples = iter(loads)
    last = [loads[-1]]

    def getloadavg() -> tuple[float, float, float]:
        try:
            last[0] = next(samples)
        except StopIteration:
            pass
        return last[0]

    gate = run_module.LoadGate(
        max_wait_seconds=wait,
        poll_seconds=60,
        getloadavg=getloadavg,
        sleep=clock.sleep,
        clock=clock,
    )
    gate.clock = clock  # type: ignore[attr-defined]
    return gate


class ArgumentValidationTests(unittest.TestCase):
    def _error(self, *argv: str) -> str:
        with self.assertRaises(run_module.PreflightRunError) as caught:
            run_module.validate_args(_args(*argv))
        return str(caught.exception)

    def test_run_id_is_required_by_parser(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            run_module.build_parser().parse_args([])

    def test_invalid_run_id_and_gate_refused(self) -> None:
        self.assertEqual(self._error("--run-id", "bad id"), "run_id_invalid")
        self.assertEqual(
            self._error("--run-id", RUN_ID, "--gate", "other"), "gate_unsupported"
        )

    def test_same_sha_rejects_comparison_arguments(self) -> None:
        self.assertEqual(
            self._error("--run-id", RUN_ID, "--tool-sha", SHA),
            "comparison_arguments_not_allowed_in_same_sha",
        )

    def test_comparison_requires_all_arguments(self) -> None:
        self.assertEqual(
            self._error("--run-id", RUN_ID, "--mode", "comparison"),
            "comparison_arguments_required",
        )

    def test_comparison_refuses_resume_checkpoints(self) -> None:
        self.assertEqual(
            self._error(
                "--run-id", RUN_ID, "--mode", "comparison",
                "--application", "frozen-origin-main",
                "--tool-sha", SHA, "--tool-tree", TREE,
                "--resume-checkpoints", "x.json",
            ),
            "resume_checkpoints_refused_in_comparison",
        )

    def test_unknown_application_rejected_by_parser(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            _args("--run-id", RUN_ID, "--mode", "comparison", "--application", "x")


class SourceResolutionTests(unittest.TestCase):
    def test_same_sha_uses_head_and_verifies_clean_tree(self) -> None:
        with (
            mock.patch.object(run_module, "_git_head", return_value=(SHA, TREE)),
            mock.patch.object(identity_module, "verify_tool_tree") as verify,
        ):
            sha, root, comparison = run_module.resolve_source(_args("--run-id", RUN_ID))
        self.assertEqual((sha, root, comparison), (SHA, PROJECT_ROOT, None))
        verify.assert_called_once_with(SHA, TREE, project_root=PROJECT_ROOT)

    def test_dirty_tree_is_refused(self) -> None:
        with (
            mock.patch.object(run_module, "_git_head", return_value=(SHA, TREE)),
            mock.patch.object(
                identity_module,
                "verify_tool_tree",
                side_effect=identity_module.ComparisonIdentityError(
                    "comparison_tool_worktree_dirty"
                ),
            ),
        ):
            with self.assertRaises(run_module.PreflightRunError) as caught:
                run_module.resolve_source(_args("--run-id", RUN_ID))
        self.assertEqual(str(caught.exception), "worktree_dirty_or_unverifiable")

    def test_comparison_builds_identity_for_each_application(self) -> None:
        for role, sha, tree in (
            (identity_module.APPLICATION_A_ROLE, identity_module.APPLICATION_A_SHA,
             identity_module.APPLICATION_A_TREE),
            (identity_module.APPLICATION_B_ROLE, identity_module.APPLICATION_B_SHA,
             identity_module.APPLICATION_B_TREE),
        ):
            with (
                mock.patch.object(identity_module, "verify_tool_tree") as tool,
                mock.patch.object(
                    identity_module, "verify_application_worktree",
                    return_value=Path("tmp/wt"),
                ) as app,
            ):
                got_sha, root, comparison = run_module.resolve_source(
                    _args("--run-id", RUN_ID, "--mode", "comparison",
                          "--application", role, "--tool-sha", SHA, "--tool-tree", TREE)
                )
            self.assertEqual(got_sha, sha)
            self.assertEqual(root, Path("tmp/wt"))
            self.assertEqual(comparison["application"],
                             {"role": role, "sha": sha, "tree": tree})
            self.assertEqual(comparison["tool"], {"sha": SHA, "tree": TREE})
            self.assertEqual(comparison["mode"], "comparison-only")
            tool.assert_called_once()
            app.assert_called_once()

    def test_comparison_tool_must_be_separate_commit(self) -> None:
        with self.assertRaises(run_module.PreflightRunError):
            run_module.resolve_source(
                _args("--run-id", RUN_ID, "--mode", "comparison",
                      "--application", "frozen-origin-main",
                      "--tool-sha", identity_module.APPLICATION_A_SHA,
                      "--tool-tree", TREE)
            )

    def test_comparison_verification_failure_blocks(self) -> None:
        with (
            mock.patch.object(
                identity_module, "verify_tool_tree",
                side_effect=identity_module.ComparisonIdentityError("comparison_tool_tree_mismatch"),
            ),
        ):
            with self.assertRaises(run_module.PreflightRunError) as caught:
                run_module.resolve_source(
                    _args("--run-id", RUN_ID, "--mode", "comparison",
                          "--application", "pre-105-control",
                          "--tool-sha", SHA, "--tool-tree", TREE)
                )
        self.assertEqual(str(caught.exception), "comparison_tool_tree_mismatch")


class LoadGateTests(unittest.TestCase):
    def test_proceeds_immediately_when_load_is_low(self) -> None:
        gate = _gate([(1.0, 2.0, 3.0)])
        gate.wait()
        self.assertEqual(gate.checks, 1)
        self.assertEqual(gate.clock.sleeps, [])

    def test_limits_are_exclusive_on_both_windows(self) -> None:
        for load in ((10.0, 1.0, 1.0), (1.0, 20.0, 1.0)):
            gate = _gate([load], wait=0)
            with self.assertRaises(run_module.LoadGateTimeout):
                gate.wait()

    def test_waits_then_proceeds(self) -> None:
        gate = _gate([(12.0, 5.0, 5.0), (11.0, 5.0, 5.0), (3.0, 4.0, 5.0)])
        gate.wait()
        self.assertEqual(gate.checks, 3)
        self.assertEqual(gate.clock.sleeps, [60, 60])
        self.assertFalse(gate.timed_out)

    def test_times_out_after_bound(self) -> None:
        gate = _gate([(50.0, 50.0, 50.0)], wait=300)
        with self.assertRaises(run_module.LoadGateTimeout):
            gate.wait()
        self.assertTrue(gate.timed_out)
        self.assertLessEqual(sum(gate.clock.sleeps), 300)


class GatedInterfacesTests(unittest.TestCase):
    def _fake_original(self, prepared: list[str]):
        def original(**_kwargs: Any) -> controller.PreflightInterfaces:
            return controller.PreflightInterfaces(
                prepare_sandbox=lambda plan, inv, sha, run: prepared.append(plan) or {},
                supervise_row=lambda *a: {},
                cleanup_sandbox=lambda *a: True,
                safety_counters=lambda: {},
            )

        return original

    def test_gate_runs_before_every_prepare_and_restores_factory(self) -> None:
        prepared: list[str] = []
        gate = _gate([(1.0, 1.0, 1.0)])
        original = controller.supervised_preflight_interfaces
        with mock.patch.object(
            controller, "supervised_preflight_interfaces", self._fake_original(prepared)
        ):
            patched = controller.supervised_preflight_interfaces
            with run_module.load_gated_controller(gate):
                interfaces = controller.supervised_preflight_interfaces(run_id=RUN_ID)
                for index in range(26):
                    interfaces.prepare_sandbox("row%d" % index, None, SHA, RUN_ID)
            self.assertIs(controller.supervised_preflight_interfaces, patched)
        self.assertEqual(gate.checks, 26)
        self.assertEqual(len(prepared), 26)
        self.assertIs(controller.supervised_preflight_interfaces, original)

    def test_timeout_blocks_before_any_prepare(self) -> None:
        prepared: list[str] = []
        gate = _gate([(99.0, 99.0, 99.0)], wait=0)
        with mock.patch.object(
            controller, "supervised_preflight_interfaces", self._fake_original(prepared)
        ):
            with run_module.load_gated_controller(gate):
                interfaces = controller.supervised_preflight_interfaces(run_id=RUN_ID)
                with self.assertRaises(run_module.LoadGateTimeout):
                    interfaces.prepare_sandbox("row", None, SHA, RUN_ID)
        self.assertEqual(prepared, [])


class InputAssemblyTests(unittest.TestCase):
    def test_all_26_rows_have_planned_identities_and_lifecycles(self) -> None:
        workers, lifecycles = run_module.build_worker_identities(
            source_sha=SHA, run_id=RUN_ID, resume_checkpoints=None,
            comparison_identity=None,
        )
        rows, _ = controller._load_frozen_row_ids(None)
        self.assertEqual(set(workers), {row["row_id"] for row in rows})
        self.assertEqual(len(workers), 26)
        for identity in workers.values():
            self.assertEqual(set(identity), {"command", "working_directory", "pythonpath"})
        for fixtures in lifecycles.values():
            for by_lifecycle in fixtures.values():
                self.assertEqual(set(by_lifecycle) - {"startup", "resume"}, set())
                self.assertNotIn("resume", by_lifecycle)
        self.assertTrue(lifecycles)

    def test_resume_identity_built_only_for_supplied_checkpoint(self) -> None:
        rows, _ = controller._load_frozen_row_ids(None)
        profiles, _ = controller._load_profiles([r["row_id"] for r in rows])
        for row in rows:
            plan = controller._resolve_row_plan(
                row["row_id"], prereg_root=None, expected_row=row, profiles=profiles
            )
            profile = controller._fixture_lifecycle_profile(plan, plan.fixture_id)
            if profile["resume"]["status"] == "measured-under-stub":
                break
        checkpoints = {
            plan.row_id: {
                plan.fixture_id: {
                    "checkpoint_root": "tmp/resume-checkpoints/x",
                    "state_sha256": "e" * 64,
                    "row_id": plan.row_id,
                    "fixture_id": plan.fixture_id,
                    "party_size": plan.party_size,
                    "arm": plan.arm,
                    "fixed_seed": plan.fixed_seed,
                }
            }
        }
        _workers, lifecycles = run_module.build_worker_identities(
            source_sha=SHA, run_id=RUN_ID, resume_checkpoints=checkpoints,
            comparison_identity=None,
        )
        resume = lifecycles[plan.row_id][plan.fixture_id]["resume"]
        self.assertIn("e" * 64, resume["command"])
        self.assertEqual(
            sum(
                "resume" in by_lifecycle
                for fixtures in lifecycles.values()
                for by_lifecycle in fixtures.values()
            ),
            1,
        )

    def test_mismatched_checkpoint_binding_is_refused(self) -> None:
        with self.assertRaises(controller.PreflightControllerError):
            run_module.build_worker_identities(
                source_sha=SHA, run_id=RUN_ID, comparison_identity=None,
                resume_checkpoints={"E01": {"bogus_fixture": {}}},
            )

    def test_routing_identity_is_secret_free_projection(self) -> None:
        routing = run_module._routing_identity(PROJECT_ROOT)
        self.assertEqual(set(routing), {"provider", "active_profile"})

    def test_missing_checkpoint_file_refused(self) -> None:
        with self.assertRaises(run_module.PreflightRunError):
            run_module._load_checkpoints("tmp/does-not-exist-checkpoints.json")


class CounterTests(unittest.TestCase):
    def test_denied_attempts_and_ledgers_are_counted(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as raw:
            root = Path(raw)
            rows = root / "tmp/router-rollout/live-gate-preflight" / RUN_ID / "preflight/rows/r1"
            rows.mkdir(parents=True)
            events = [
                {"event_type": "network_attempt", "decision": "allowed"},
                {"event_type": "network_attempt", "decision": "denied"},
                {"event_type": "guard_startup", "decision": None},
            ]
            (rows / "guard-events.jsonl").write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            ledger = root / "tmp/router-rollout/mapping-pilot/sp3/L"
            ledger.mkdir(parents=True)
            (ledger / "matrix_ledger.json").write_text(
                json.dumps(
                    {
                        "bookings": [{}],
                        "slots": [
                            {"execution": {"attempt_count": 2}, "replacement": None},
                            {"execution": {"attempt_count": 1}, "replacement": {"x": 1}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            counters = run_module.PreflightSafetyCounters(RUN_ID, project_root=root)()
        self.assertEqual(
            counters,
            {
                "upstream_provider_requests": 1,
                "provider_budget_used": 1,
                "live_attempts_used": 3,
                "reserve_activations": 1,
            },
        )

    def test_absent_sources_read_as_zero(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as raw:
            counters = run_module.PreflightSafetyCounters(
                RUN_ID, project_root=Path(raw)
            )()
        self.assertEqual(set(counters.values()), {0})

    def _upstream_count(self, events: list[dict[str, Any]]) -> int:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as raw:
            root = Path(raw)
            rows = root / "tmp/router-rollout/live-gate-preflight" / RUN_ID / "preflight/rows/r1"
            rows.mkdir(parents=True)
            (rows / "guard-events.jsonl").write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )
            counters = run_module.PreflightSafetyCounters(RUN_ID, project_root=root)()
        return counters["upstream_provider_requests"]

    @staticmethod
    def _canary(**overrides: Any) -> dict[str, Any]:
        event = {
            "event_type": "network_attempt",
            "operation": "connect",
            "decision": "denied",
            "target_host": "192.0.2.1",
            "target_port": 8360,
        }
        event.update(overrides)
        return event

    def test_startup_canary_probes_are_not_upstream_requests(self) -> None:
        allowed = {
            "event_type": "network_attempt",
            "operation": "connect",
            "decision": "allowed",
            "target_host": "127.0.0.1",
            "target_port": 8357,
        }
        events = [
            {"event_type": "guard_startup", "decision": None, "sequence": 1},
            self._canary(sequence=2),
            allowed,
            self._canary(sequence=3),
            self._canary(sequence=4),
            allowed,
        ]
        self.assertEqual(self._upstream_count(events), 0)

    def test_non_canary_denied_connect_is_counted(self) -> None:
        events = [
            self._canary(sequence=2),
            {
                "event_type": "network_attempt",
                "operation": "connect",
                "decision": "denied",
                "target_host": "203.0.113.5",
                "target_port": 443,
                "sequence": 3,
            },
        ]
        self.assertEqual(self._upstream_count(events), 1)

    def test_canary_exclusion_is_exact(self) -> None:
        cases = {
            "other port": self._canary(target_port=8361),
            "other operation": self._canary(operation="sendto"),
            "other host": self._canary(target_host="192.0.2.2"),
        }
        for label, event in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self._upstream_count([event]), 1)

    def test_unparsable_journal_still_raises(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as raw:
            root = Path(raw)
            rows = root / "tmp/router-rollout/live-gate-preflight" / RUN_ID / "preflight/rows/r1"
            rows.mkdir(parents=True)
            (rows / "guard-events.jsonl").write_text("{not json\n", encoding="utf-8")
            counters = run_module.PreflightSafetyCounters(RUN_ID, project_root=root)
            with self.assertRaises(json.JSONDecodeError):
                counters()


class ExecuteTests(unittest.TestCase):
    def _patches(self, report: dict[str, Any], *, comparison: bool = False):
        identity = None
        if comparison:
            identity = identity_module.build_comparison_identity(
                tool_sha=SHA, tool_tree=TREE,
                application_sha=identity_module.APPLICATION_A_SHA,
                application_tree=identity_module.APPLICATION_A_TREE,
            )
        source = (
            identity_module.APPLICATION_A_SHA if comparison else SHA,
            PROJECT_ROOT,
            identity,
        )
        run = mock.patch.object(
            controller, "run_preflight_rows_supervised", return_value=report
        )
        return (
            mock.patch.object(run_module, "resolve_source", return_value=source),
            mock.patch.object(
                run_module, "build_worker_identities", return_value=({}, {})
            ),
            run,
        )

    def _run(self, argv: list[str], report: dict[str, Any], **kw: Any):
        a, b, run = self._patches(report, **kw)
        with a, b, run as supervised:
            summary, code = run_module.execute(_args(*argv))
        return summary, code, supervised

    def test_same_sha_success_summary_and_inputs(self) -> None:
        summary, code, supervised = self._run(["--run-id", RUN_ID], _fake_report())
        self.assertEqual(code, 0)
        kwargs = supervised.call_args.kwargs
        self.assertEqual(kwargs["source_sha"], SHA)
        self.assertIsNone(kwargs["comparison_identity"])
        self.assertEqual(kwargs["dependency_lock_path"], Path("requirements-lock.txt"))
        self.assertEqual(
            set(kwargs["routing_identity"]), {"provider", "active_profile"}
        )
        self.assertTrue(callable(kwargs["safety_counters"]))
        self.assertEqual(
            summary,
            {
                "run_id": RUN_ID,
                "mode": "same-sha",
                "source_sha": SHA,
                "status": "completed",
                "row_status_counts": {"completed": 26},
                "preflight_evidence_path": _fake_report()["preflight_evidence_path"],
                "booking_eligible": False,
                "live_gate_pass": False,
            },
        )

    def test_comparison_passes_identity_and_source_is_application(self) -> None:
        summary, code, supervised = self._run(
            ["--run-id", RUN_ID, "--mode", "comparison",
             "--application", "frozen-origin-main",
             "--tool-sha", SHA, "--tool-tree", TREE],
            _fake_report(preflight_failure_code="comparison_only_not_booking_eligible"),
            comparison=True,
        )
        kwargs = supervised.call_args.kwargs
        self.assertEqual(kwargs["source_sha"], identity_module.APPLICATION_A_SHA)
        self.assertEqual(kwargs["comparison_identity"]["mode"], "comparison-only")
        self.assertIsNone(kwargs["resume_checkpoints"])
        self.assertEqual(code, 0)
        self.assertFalse(summary["booking_eligible"])
        self.assertFalse(summary["live_gate_pass"])

    def test_blocked_report_exits_nonzero(self) -> None:
        summary, code, _ = self._run(
            ["--run-id", RUN_ID],
            _fake_report("blocked", preflight_failure_code="x_failure"),
        )
        self.assertEqual(code, run_module.EXIT_BLOCKED)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["preflight_failure_code"], "x_failure")

    def test_unverified_report_is_not_a_failure(self) -> None:
        _summary, code, _ = self._run(["--run-id", RUN_ID], _fake_report("unverified"))
        self.assertEqual(code, 0)

    def test_load_gate_timeout_reports_load_gate_block(self) -> None:
        gate = _gate([(99.0, 99.0, 99.0)], wait=0)
        with self.assertRaises(run_module.LoadGateTimeout):
            gate.wait()
        a, b, run = self._patches(_fake_report("blocked"))
        with a, b, run:
            summary, code = run_module.execute(_args("--run-id", RUN_ID), gate=gate)
        self.assertEqual(code, run_module.EXIT_LOAD_GATE)
        self.assertEqual(summary["block_reason"], "LOAD_GATE")
        self.assertEqual(summary["status"], "blocked")

    def test_dirty_tree_blocks_without_running(self) -> None:
        with (
            mock.patch.object(
                run_module, "resolve_source",
                side_effect=run_module.PreflightRunError("worktree_dirty_or_unverifiable"),
            ),
            mock.patch.object(controller, "run_preflight_rows_supervised") as supervised,
        ):
            summary, code = run_module.execute(_args("--run-id", RUN_ID))
        self.assertEqual(code, run_module.EXIT_USAGE)
        self.assertEqual(summary["block_reason"], "worktree_dirty_or_unverifiable")
        supervised.assert_not_called()

    def test_invalid_arguments_block_without_running(self) -> None:
        with mock.patch.object(controller, "run_preflight_rows_supervised") as supervised:
            summary, code = run_module.execute(
                _args("--run-id", RUN_ID, "--mode", "comparison")
            )
        self.assertEqual(code, run_module.EXIT_USAGE)
        supervised.assert_not_called()
        self.assertEqual(summary["status"], "blocked")

    def test_main_prints_one_compact_json_line(self) -> None:
        a, b, run = self._patches(_fake_report())
        out = io.StringIO()
        with (
            a, b, run, redirect_stdout(out),
            mock.patch.object(run_module, "_guarded_startup_active", return_value=True),
        ):
            code = run_module.main(["--run-id", RUN_ID])
        self.assertEqual(code, 0)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn("/Users/", lines[0])
        self.assertFalse(json.loads(lines[0])["live_gate_pass"])


class _Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


class GuardedRelaunchTests(unittest.TestCase):
    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        guard = root / "scripts" / "live_gate_preflight_guard"
        guard.mkdir(parents=True)
        (root / "tmp").mkdir()
        return root

    def _main(self, argv: list[str], *, guarded: bool, env: dict[str, str] | None = None):
        out = io.StringIO()
        with (
            mock.patch.object(
                run_module, "_guarded_startup_active", return_value=guarded
            ),
            mock.patch.dict(os.environ, env or {}),
            redirect_stdout(out),
        ):
            code = run_module.main(argv)
        return code, out.getvalue()

    def test_unguarded_main_relaunches_with_guarded_env_cwd_and_args(self) -> None:
        root = self._root()
        calls: list[Any] = []

        def runner(command: list[str], **kwargs: Any) -> _Completed:
            calls.append((command, kwargs))
            return _Completed(7)

        args = _args("--run-id", RUN_ID)
        argv = ["--run-id", RUN_ID]
        os.environ.pop(run_module.RELAUNCH_ENV, None)
        code = run_module.relaunch_guarded(args, argv, root=root, runner=runner)
        self.assertEqual(code, 7)
        command, kwargs = calls[0]
        resolved = root.resolve()
        self.assertEqual(
            command,
            [str(root / ".venv/bin/python"), "-m",
             "scripts.live_gate_preflight_run", "--run-id", RUN_ID],
        )
        cwd = Path(kwargs["cwd"])
        self.assertEqual(cwd, root / "tmp" / ("live-gate-preflight-cwd-%s" % RUN_ID))
        self.assertTrue(cwd.is_dir())
        env = kwargs["env"]
        self.assertEqual(
            env["PYTHONPATH"], run_module.safety.expected_guarded_pythonpath(root)
        )
        self.assertEqual(env[run_module.safety.PROCESS_ROLE_ENV], "parent")
        self.assertEqual(env[run_module.RELAUNCH_ENV], "1")
        self.assertEqual(env[run_module.safety.PROJECT_ROOT_ENV], str(resolved))
        self.assertFalse(kwargs["check"])

    def test_existing_cwd_is_refused(self) -> None:
        root = self._root()
        (root / "tmp" / ("live-gate-preflight-cwd-%s" % RUN_ID)).mkdir()
        runner = mock.Mock()
        os.environ.pop(run_module.RELAUNCH_ENV, None)
        out = io.StringIO()
        with redirect_stdout(out):
            code = run_module.relaunch_guarded(
                _args("--run-id", RUN_ID), ["--run-id", RUN_ID], root=root, runner=runner
            )
        self.assertEqual(code, run_module.EXIT_USAGE)
        runner.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["block_reason"], "guarded_relaunch_cwd_exists")

    def test_relaunched_child_that_is_not_guarded_does_not_loop(self) -> None:
        root = self._root()
        runner = mock.Mock()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {run_module.RELAUNCH_ENV: "1"}), redirect_stdout(out):
            code = run_module.relaunch_guarded(
                _args("--run-id", RUN_ID), ["--run-id", RUN_ID], root=root, runner=runner
            )
        self.assertEqual(code, run_module.EXIT_USAGE)
        runner.assert_not_called()
        self.assertFalse(list((root / "tmp").iterdir()))

    def test_main_unguarded_invokes_relaunch_with_original_argv(self) -> None:
        with mock.patch.object(
            run_module, "relaunch_guarded", return_value=5
        ) as relaunch:
            code, _ = self._main(["--run-id", RUN_ID], guarded=False)
        self.assertEqual(code, 5)
        self.assertEqual(relaunch.call_args.args[1], ["--run-id", RUN_ID])

    def test_main_guarded_does_not_relaunch(self) -> None:
        with (
            mock.patch.object(run_module, "relaunch_guarded") as relaunch,
            mock.patch.object(
                run_module, "execute", return_value=({"status": "completed"}, 0)
            ),
        ):
            code, _ = self._main(["--run-id", RUN_ID], guarded=True)
        self.assertEqual(code, 0)
        relaunch.assert_not_called()

    def test_validation_precedes_relaunch_without_creating_directories(self) -> None:
        before = set((PROJECT_ROOT / "tmp").iterdir())
        for argv in (
            ["--run-id", "bad id!"],
            ["--run-id", RUN_ID, "--mode", "comparison"],
            ["--run-id", RUN_ID, "--mode", "comparison", "--application",
             "frozen-origin-main", "--tool-sha", SHA, "--tool-tree", TREE,
             "--resume-checkpoints", "x.json"],
        ):
            with mock.patch.object(run_module, "relaunch_guarded") as relaunch:
                code, text = self._main(argv, guarded=False)
            self.assertEqual(code, run_module.EXIT_USAGE)
            relaunch.assert_not_called()
            self.assertEqual(json.loads(text)["status"], "blocked")
        self.assertEqual(set((PROJECT_ROOT / "tmp").iterdir()), before)

    def test_guarded_startup_detection_fails_closed_when_plain(self) -> None:
        self.assertFalse(run_module._guarded_startup_active())


class GitOutputGuardTests(unittest.TestCase):
    def test_guarded_path_used_when_guard_active(self) -> None:
        completed = mock.Mock(returncode=0, stdout="abc\n")
        with (
            mock.patch.object(identity_module, "_preflight_guard_active", return_value=True),
            mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                return_value=completed,
            ) as guarded,
            mock.patch.object(identity_module.subprocess, "run") as plain,
        ):
            out = identity_module._git_output(PROJECT_ROOT, ("rev-parse", "HEAD"))
        self.assertEqual(out, "abc")
        plain.assert_not_called()
        command = guarded.call_args.args[0]
        self.assertEqual(command[:3], ["git", "-C", str(PROJECT_ROOT)])
        kwargs = guarded.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 10.0)
        self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
        self.assertFalse(kwargs["check"])

    def test_plain_path_used_when_guard_inactive(self) -> None:
        completed = mock.Mock(returncode=0, stdout="abc\n")
        with (
            mock.patch.object(identity_module, "_preflight_guard_active", return_value=False),
            mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess"
            ) as guarded,
            mock.patch.object(
                identity_module.subprocess, "run", return_value=completed
            ) as plain,
        ):
            out = identity_module._git_output(PROJECT_ROOT, ("rev-parse", "HEAD"))
        self.assertEqual(out, "abc")
        guarded.assert_not_called()
        plain.assert_called_once()

    def test_guarded_failure_stays_strict(self) -> None:
        with (
            mock.patch.object(identity_module, "_preflight_guard_active", return_value=True),
            mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=PermissionError("denied"),
            ),
        ):
            with self.assertRaises(identity_module.ComparisonIdentityError):
                identity_module._git_output(PROJECT_ROOT, ("status",))

    def test_guard_inactive_in_plain_process(self) -> None:
        self.assertFalse(identity_module._preflight_guard_active())


if __name__ == "__main__":
    unittest.main()
