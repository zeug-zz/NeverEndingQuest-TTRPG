# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Runnable entry point for the supervised provider-free 26-row preflight.

Builds every input ``run_preflight_rows_supervised`` needs from existing
helpers and runs it in one of two modes:

* ``same-sha`` (default): the report stays bound to the current checkout HEAD.
* ``comparison``: the frozen application worktree SHA is the source SHA and the
  report is comparison-only (never booking eligible, no pilot evidence).

A host-load gate is applied before every lifecycle host launch by wrapping the
controller's ``prepare_sandbox`` interface. The module never fetches, never
contacts a provider, and starts hosts only through the controller.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts import live_gate_preflight_comparison_identity as identity_module
from scripts import live_gate_preflight_controller as controller
from scripts import live_gate_preflight_safety as safety
from scripts.live_gate_preflight_evidence import EVIDENCE_GATE
from scripts.live_gate_preflight_safety import current_invocation_identity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELAUNCH_ENV = "NEQ_PREFLIGHT_RUN_RELAUNCHED"
DEPENDENCY_LOCK = Path("requirements-lock.txt")
ONE_MINUTE_LOAD_LIMIT = 10.0
FIVE_MINUTE_LOAD_LIMIT = 20.0
DEFAULT_LOAD_WAIT_SECONDS = 30 * 60
LOAD_POLL_SECONDS = 60
MODES = ("same-sha", "comparison")
APPLICATIONS = (
    identity_module.APPLICATION_A_ROLE,
    identity_module.APPLICATION_B_ROLE,
)
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2
EXIT_LOAD_GATE = 3
_MAX_CHECKPOINT_FILE_BYTES = 1_000_000
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_ROUTING_PROVIDER = re.compile(r'^LLM_PROVIDER\s*=\s*"([A-Za-z0-9._/-]{1,64})"', re.M)
_ROUTING_PROFILE = re.compile(r'^ACTIVE_PROFILE\s*=\s*"([A-Za-z0-9._/-]{1,64})"', re.M)
_NON_FAILURE_CODES = frozenset({"comparison_only_not_booking_eligible"})


class PreflightRunError(ValueError):
    """Raised with a stable code when run inputs cannot be assembled safely."""


class LoadGateTimeout(RuntimeError):
    """Raised when host load stays above the owner limits for the wait bound."""


class LoadGate:
    """Wait for host load below the owner limits before any host start."""

    def __init__(
        self,
        *,
        max_wait_seconds: float = DEFAULT_LOAD_WAIT_SECONDS,
        poll_seconds: float = LOAD_POLL_SECONDS,
        getloadavg: Callable[[], tuple[float, float, float]] = os.getloadavg,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_wait = float(max_wait_seconds)
        self._poll = float(poll_seconds)
        self._getloadavg = getloadavg
        self._sleep = sleep
        self._clock = clock
        self.checks = 0
        self.timed_out = False
        self.last_sample: tuple[float, float] | None = None

    def _within_limits(self) -> bool:
        one, five, _fifteen = self._getloadavg()
        self.last_sample = (float(one), float(five))
        return one < ONE_MINUTE_LOAD_LIMIT and five < FIVE_MINUTE_LOAD_LIMIT

    def wait(self) -> None:
        """Return once load is acceptable; raise after the bounded wait."""
        started = self._clock()
        while True:
            self.checks += 1
            if self._within_limits():
                return
            if self._clock() - started + self._poll > self._max_wait:
                self.timed_out = True
                raise LoadGateTimeout("load_gate_timeout")
            self._sleep(self._poll)


def _gated_factory(
    original: Callable[..., controller.PreflightInterfaces], gate: LoadGate
) -> Callable[..., controller.PreflightInterfaces]:
    def factory(**kwargs: Any) -> controller.PreflightInterfaces:
        interfaces = original(**kwargs)
        prepare = interfaces.prepare_sandbox

        def gated_prepare(*args: Any, **inner: Any) -> Any:
            gate.wait()
            return prepare(*args, **inner)

        return dataclasses.replace(interfaces, prepare_sandbox=gated_prepare)

    return factory


@contextlib.contextmanager
def load_gated_controller(gate: LoadGate) -> Iterator[None]:
    """Gate every controller sandbox preparation (precedes each host launch)."""
    original = controller.supervised_preflight_interfaces
    controller.supervised_preflight_interfaces = _gated_factory(original, gate)
    try:
        yield
    finally:
        controller.supervised_preflight_interfaces = original


class PreflightSafetyCounters:
    """Provider-free counters read from retained guard journals and SP3 ledgers.

    ``upstream_provider_requests`` counts guard-denied network attempts in this
    run's row guard journals. The booking counters are read from the SP3 matrix
    ledgers (read-only): bookings, attempted row launches, and replacements.
    Unreadable sources raise, so the controller fails closed.
    """

    def __init__(self, run_id: str, *, project_root: Path = PROJECT_ROOT) -> None:
        self._rows_root = (
            project_root / "tmp/router-rollout" / EVIDENCE_GATE / run_id / "preflight" / "rows"
        )
        self._ledger_root = project_root / "tmp/router-rollout/mapping-pilot/sp3"

    def __call__(self) -> dict[str, int]:
        return {
            "upstream_provider_requests": self._denied_network_attempts(),
            **self._ledger_counters(),
        }

    def _denied_network_attempts(self) -> int:
        if not self._rows_root.is_dir():
            return 0
        total = 0
        for journal in sorted(self._rows_root.glob("*/guard-events.jsonl")):
            for line in journal.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if (
                    isinstance(event, Mapping)
                    and event.get("event_type") == "network_attempt"
                    and event.get("decision") == "denied"
                ):
                    total += 1
        return total

    def _ledger_counters(self) -> dict[str, int]:
        bookings = attempts = replacements = 0
        if self._ledger_root.is_dir():
            for ledger_path in sorted(self._ledger_root.glob("*/matrix_ledger.json")):
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                bookings += len(ledger.get("bookings", []))
                for slot in ledger.get("slots", []):
                    attempts += int(slot["execution"]["attempt_count"])
                    if slot.get("replacement") is not None:
                        replacements += 1
        return {
            "provider_budget_used": bookings,
            "live_attempts_used": attempts,
            "reserve_activations": replacements,
        }


def _routing_identity(root: Path) -> dict[str, str]:
    """Secret-free routing projection parsed from model_config.py text."""
    try:
        text = (root / "model_config.py").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PreflightRunError("routing_identity_unavailable") from exc
    provider = _ROUTING_PROVIDER.search(text)
    profile = _ROUTING_PROFILE.search(text)
    if provider is None or profile is None:
        raise PreflightRunError("routing_identity_unavailable")
    return {"provider": provider.group(1), "active_profile": profile.group(1)}


def _load_checkpoints(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        file_path = Path(path)
        if file_path.stat().st_size > _MAX_CHECKPOINT_FILE_BYTES:
            raise PreflightRunError("resume_checkpoints_file_invalid")
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except PreflightRunError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightRunError("resume_checkpoints_file_invalid") from exc
    if not isinstance(value, dict):
        raise PreflightRunError("resume_checkpoints_file_invalid")
    return value


def build_worker_identities(
    *,
    source_sha: str,
    run_id: str,
    resume_checkpoints: Mapping[str, Any] | None,
    comparison_identity: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """Return (per-row startup identities, extra per-lifecycle identities)."""
    rows, _reserves = controller._load_frozen_row_ids(None)
    row_ids = [str(row["row_id"]) for row in rows]
    profiles, _coverage = controller._load_profiles(row_ids)
    checkpoint_map = controller._validate_resume_checkpoint_map(
        resume_checkpoints, expected_row_ids=row_ids, profiles=profiles
    )
    workers: dict[str, dict[str, Any]] = {}
    lifecycles: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        row_id = str(row["row_id"])
        plan = controller._resolve_row_plan(
            row_id, prereg_root=None, expected_row=row, profiles=profiles
        )
        common = {
            "source_sha": source_sha,
            "preflight_run_id": run_id,
            "comparison_identity": comparison_identity,
        }
        workers[row_id] = controller.planned_worker_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id="pf-%s-%s" % (run_id, row_id),
            **common,
        )
        for index, fixture_id in enumerate(plan.fixture_ids):
            profile = controller._fixture_lifecycle_profile(plan, fixture_id)
            by_lifecycle: dict[str, dict[str, Any]] = {}
            if (
                fixture_id != plan.fixture_id
                and profile["startup"].get("status") == "measured-under-stub"
            ):
                by_lifecycle["startup"] = controller.planned_worker_identity(
                    plan,
                    fixture_id=fixture_id,
                    lifecycle="startup",
                    row_run_id=controller._lifecycle_run_id(
                        run_id, row_id, index, "startup", primary=False
                    ),
                    **common,
                )
            checkpoint = checkpoint_map.get(row_id, {}).get(fixture_id)
            if profile["resume"].get("status") == "measured-under-stub" and checkpoint:
                controller._validate_checkpoint_for_plan(plan, fixture_id, checkpoint)
                by_lifecycle["resume"] = controller.planned_worker_identity(
                    plan,
                    fixture_id=fixture_id,
                    lifecycle="resume",
                    row_run_id=controller._lifecycle_run_id(
                        run_id, row_id, index, "resume", primary=False
                    ),
                    resume_checkpoint_sha256=checkpoint["state_sha256"],
                    **common,
                )
            if by_lifecycle:
                lifecycles.setdefault(row_id, {})[fixture_id] = by_lifecycle
    return workers, lifecycles


def _git_head(root: Path) -> tuple[str, str]:
    try:
        sha = identity_module._git_output(root, ("rev-parse", "HEAD"))
        tree = identity_module._git_output(root, ("rev-parse", "HEAD^{tree}"))
    except identity_module.ComparisonIdentityError as exc:
        raise PreflightRunError("git_identity_unavailable") from exc
    if _SHA1.fullmatch(sha) is None or _SHA1.fullmatch(tree) is None:
        raise PreflightRunError("git_identity_unavailable")
    return sha, tree


def resolve_source(args: argparse.Namespace) -> tuple[str, Path, dict[str, Any] | None]:
    """Return (source_sha, checkout root used for routing, comparison identity)."""
    if args.mode == "same-sha":
        sha, tree = _git_head(PROJECT_ROOT)
        try:
            identity_module.verify_tool_tree(sha, tree, project_root=PROJECT_ROOT)
        except identity_module.ComparisonIdentityError as exc:
            raise PreflightRunError("worktree_dirty_or_unverifiable") from exc
        return sha, PROJECT_ROOT, None
    application = {
        identity_module.APPLICATION_A_ROLE: (
            identity_module.APPLICATION_A_SHA,
            identity_module.APPLICATION_A_TREE,
        ),
        identity_module.APPLICATION_B_ROLE: (
            identity_module.APPLICATION_B_SHA,
            identity_module.APPLICATION_B_TREE,
        ),
    }[args.application]
    try:
        identity = identity_module.build_comparison_identity(
            tool_sha=args.tool_sha,
            tool_tree=args.tool_tree,
            application_sha=application[0],
            application_tree=application[1],
        )
        identity_module.verify_tool_tree(
            args.tool_sha, args.tool_tree, project_root=PROJECT_ROOT
        )
        worktree = identity_module.verify_application_worktree(identity)
    except identity_module.ComparisonIdentityError as exc:
        raise PreflightRunError(str(exc)) from exc
    return application[0], worktree, identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the supervised provider-free 26-row preflight."
    )
    parser.add_argument("--mode", choices=MODES, default="same-sha")
    parser.add_argument("--application", choices=APPLICATIONS)
    parser.add_argument("--tool-sha")
    parser.add_argument("--tool-tree")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-checkpoints")
    parser.add_argument("--gate", default=EVIDENCE_GATE)
    parser.add_argument(
        "--load-wait-seconds", type=float, default=DEFAULT_LOAD_WAIT_SECONDS
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if controller._RUN_ID.fullmatch(args.run_id) is None:
        raise PreflightRunError("run_id_invalid")
    if args.gate != EVIDENCE_GATE:
        raise PreflightRunError("gate_unsupported")
    if args.load_wait_seconds < 0:
        raise PreflightRunError("load_wait_invalid")
    if args.mode == "same-sha":
        if args.application or args.tool_sha or args.tool_tree:
            raise PreflightRunError("comparison_arguments_not_allowed_in_same_sha")
        return
    if args.resume_checkpoints is not None:
        raise PreflightRunError("resume_checkpoints_refused_in_comparison")
    if not args.application or not args.tool_sha or not args.tool_tree:
        raise PreflightRunError("comparison_arguments_required")


def summarize(
    report: Mapping[str, Any], *, mode: str, run_id: str, source_sha: str | None
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in report.get("row_results", []):
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    summary = {
        "run_id": run_id,
        "mode": mode,
        "source_sha": source_sha,
        "status": report.get("status", "blocked"),
        "row_status_counts": counts,
        "preflight_evidence_path": report.get("preflight_evidence_path"),
        "booking_eligible": bool(report.get("booking_eligible", False)),
        "live_gate_pass": False,
    }
    if report.get("preflight_failure_code"):
        summary["preflight_failure_code"] = report["preflight_failure_code"]
    return summary


def _blocked(
    code: str, *, mode: str, run_id: str, source_sha: str | None = None
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": mode,
        "source_sha": source_sha,
        "status": "blocked",
        "block_reason": code,
        "row_status_counts": {},
        "preflight_evidence_path": None,
        "booking_eligible": False,
        "live_gate_pass": False,
    }


def execute(
    args: argparse.Namespace, *, gate: LoadGate | None = None
) -> tuple[dict[str, Any], int]:
    """Assemble inputs, run the supervised preflight, return (summary, exit)."""
    try:
        validate_args(args)
    except PreflightRunError as exc:
        return _blocked(str(exc), mode=args.mode, run_id=args.run_id), EXIT_USAGE
    gate = gate or LoadGate(max_wait_seconds=args.load_wait_seconds)
    source_sha: str | None = None
    try:
        source_sha, checkout, comparison_identity = resolve_source(args)
        checkpoints = _load_checkpoints(args.resume_checkpoints)
        workers, lifecycles = build_worker_identities(
            source_sha=source_sha,
            run_id=args.run_id,
            resume_checkpoints=checkpoints,
            comparison_identity=comparison_identity,
        )
        routing = _routing_identity(checkout)
        intended_invocation = current_invocation_identity()
    except (PreflightRunError, controller.PreflightControllerError) as exc:
        return (
            _blocked(
                str(exc).replace(" ", "_")[:100],
                mode=args.mode,
                run_id=args.run_id,
                source_sha=source_sha,
            ),
            EXIT_USAGE,
        )
    with load_gated_controller(gate):
        report = controller.run_preflight_rows_supervised(
            source_sha=source_sha,
            run_id=args.run_id,
            intended_worker_identities=workers,
            intended_lifecycle_identities=lifecycles,
            safety_counters=PreflightSafetyCounters(args.run_id),
            dependency_lock_path=DEPENDENCY_LOCK,
            routing_identity=routing,
            intended_invocation=intended_invocation,
            resume_checkpoints=checkpoints,
            comparison_identity=comparison_identity,
        )
    summary = summarize(
        report, mode=args.mode, run_id=args.run_id, source_sha=source_sha
    )
    if gate.timed_out:
        summary["status"] = "blocked"
        summary["block_reason"] = "LOAD_GATE"
        return summary, EXIT_LOAD_GATE
    failed = (
        report.get("status") not in ("completed", "unverified")
        or report.get("preflight_failure_code") not in (None, *_NON_FAILURE_CODES)
    )
    return summary, EXIT_BLOCKED if failed else EXIT_OK


def _guarded_startup_active(root: Path = PROJECT_ROOT) -> bool:
    """True only when this process was started under the dedicated startup guard."""
    try:
        if os.environ.get("PYTHONPATH") != safety.expected_guarded_pythonpath(root):
            return False
        safety.require_startup_guard_active()
    except (safety.NetworkGuardError, safety.SafetyConfigurationError, OSError):
        return False
    return True


def _emit(summary: Mapping[str, Any]) -> None:
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


def relaunch_guarded(
    args: argparse.Namespace,
    argv: Sequence[str],
    *,
    root: Path = PROJECT_ROOT,
    runner: Callable[..., Any] | None = None,
) -> int:
    """Re-run this module under the dedicated startup guard in a fresh tmp/ cwd."""
    import subprocess

    if os.environ.get(RELAUNCH_ENV) == "1":
        _emit(_blocked("guarded_relaunch_loop_refused", mode=args.mode, run_id=args.run_id))
        return EXIT_USAGE
    tmp_root = root / "tmp"
    cwd = tmp_root / ("live-gate-preflight-cwd-%s" % args.run_id)
    try:
        if tmp_root.is_symlink():
            raise PreflightRunError("guarded_relaunch_tmp_invalid")
        cwd.mkdir(parents=True)
    except FileExistsError:
        _emit(_blocked("guarded_relaunch_cwd_exists", mode=args.mode, run_id=args.run_id))
        return EXIT_USAGE
    except (PreflightRunError, OSError) as exc:
        _emit(_blocked(str(exc) if isinstance(exc, PreflightRunError)
                       else "guarded_relaunch_cwd_unavailable",
                       mode=args.mode, run_id=args.run_id))
        return EXIT_BLOCKED
    try:
        env = safety.build_guarded_environment(project_root=root, process_role="parent")
    except (safety.SafetyConfigurationError, OSError):
        _emit(_blocked("guarded_environment_unavailable", mode=args.mode, run_id=args.run_id))
        return EXIT_BLOCKED
    env[RELAUNCH_ENV] = "1"
    command = [
        str(root / ".venv" / "bin" / "python"),
        "-m",
        "scripts.live_gate_preflight_run",
        *argv,
    ]
    try:
        completed = (runner or subprocess.run)(
            command, cwd=str(cwd), env=env, check=False
        )
    except OSError:
        _emit(_blocked("guarded_relaunch_failed", mode=args.mode, run_id=args.run_id))
        return EXIT_BLOCKED
    return int(completed.returncode)


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv_list)
    if not _guarded_startup_active():
        try:
            validate_args(args)
        except PreflightRunError as exc:
            _emit(_blocked(str(exc), mode=args.mode, run_id=args.run_id))
            return EXIT_USAGE
        return relaunch_guarded(args, argv_list)
    summary, code = execute(args)
    _emit(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
