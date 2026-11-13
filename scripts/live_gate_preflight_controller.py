# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Coordinate provider-free first-exchange checks for the frozen SP3 rows.

The controller deliberately does not use the booked row executor: it resolves
the frozen row through that executor's read-only resolver, then crosses the
existing preflight sandbox, launcher, guarded-worker, and capture-driver
boundaries through explicit interfaces. It never writes pilot evidence or
activates reserve slots. The worker interface must provide the existing
fail-closed preflight worker lifecycle.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from scripts.live_gate_preflight_safety import compare_invocation_identity
from scripts.mapping_pilot import launcher, row_runner
from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    verify_manifest,
)


_SOURCE_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CHECKPOINT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
_COUNTER_FIELDS = (
    "upstream_provider_requests",
    "provider_budget_used",
    "live_attempts_used",
    "reserve_activations",
)
_LIFECYCLES = ("startup", "resume")


class PreflightControllerError(ValueError):
    """Raised when frozen row or profile declarations are not trustworthy."""


class FixtureResolutionError(PreflightControllerError):
    """Raised with a safe relative reference when a seeded asset is unresolved."""

    def __init__(self, code: str, unresolved_reference: str) -> None:
        super().__init__(code)
        self.unresolved_reference = unresolved_reference


class PreflightLifecycleIdentityError(PreflightControllerError):
    """Carry only redacted invocation mismatch evidence to the row report."""

    def __init__(
        self,
        *,
        fixture_id: str,
        lifecycle: str,
        evidence: Mapping[str, Any],
    ) -> None:
        super().__init__("invocation_identity_mismatch")
        self.fixture_id = fixture_id
        self.lifecycle = lifecycle
        self.evidence = dict(evidence)


@dataclass(frozen=True)
class PreflightRowPlan:
    """Resolved, immutable inputs for one planned row's first exchange."""

    row_id: str
    row: Mapping[str, Any]
    script: Mapping[str, Any]
    fixture_id: str
    fixture_ids: tuple[str, ...]
    party_size: int
    arm: str
    fixed_seed: int
    first_turn: Mapping[str, str]
    lifecycle_profiles: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class PreflightLifecycleInvocation:
    """One source-bound fixture lifecycle launch, including its checkpoint."""

    fixture_id: str
    lifecycle: str
    row_run_id: str
    intended_identity: Mapping[str, Any]
    resume_checkpoint: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PreflightInterfaces:
    """Injected side-effect boundaries used by the row controller.

    ``supervise_row`` must use the guarded profile-runner worker, which delegates
    to ``mapping_pilot.server.launch_worker`` and the existing script driver.
    It must not call the pilot row executor or any live-booking API.
    """

    prepare_sandbox: Callable[
        [PreflightRowPlan, PreflightLifecycleInvocation, str, str], Mapping[str, Any]
    ]
    supervise_row: Callable[
        [
            PreflightRowPlan,
            Mapping[str, Any],
            PreflightLifecycleInvocation,
            str,
            str,
        ],
        Mapping[str, Any],
    ]
    cleanup_sandbox: Callable[[PreflightRowPlan, Mapping[str, Any]], bool]
    safety_counters: Callable[[], Mapping[str, Any]]


def supervised_preflight_interfaces(
    *,
    run_id: str,
    safety_counters: Callable[[], Mapping[str, Any]],
) -> PreflightInterfaces:
    """Bind row orchestration to the guarded sandbox and profile-runner APIs."""
    from scripts import live_gate_preflight_profile_runner as profile_runner
    from scripts import live_gate_preflight_sandbox as sandbox

    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise PreflightControllerError("preflight run ID is invalid")

    def prepare(
        plan: PreflightRowPlan,
        invocation: PreflightLifecycleInvocation,
        source_sha: str,
        preflight_run_id: str,
    ) -> Mapping[str, Any]:
        if preflight_run_id != run_id:
            raise PreflightControllerError("preflight run identity changed")
        checkpoint = invocation.resume_checkpoint
        return sandbox.prepare_profile_sandbox(
            invocation.fixture_id,
            plan.party_size,
            plan.row_id,
            lifecycle=invocation.lifecycle,
            source_sha=source_sha,
            run_id=invocation.row_run_id,
            intended_host_identity=invocation.intended_identity,
            resume_checkpoint_sha256=(
                checkpoint.get("state_sha256")
                if isinstance(checkpoint, Mapping)
                else None
            ),
            resume_checkpoint=checkpoint,
            preflight_run_id=preflight_run_id,
        )

    def supervise(
        plan: PreflightRowPlan,
        _seeded: Mapping[str, Any],
        invocation: PreflightLifecycleInvocation,
        source_sha: str,
        preflight_run_id: str,
    ) -> Mapping[str, Any]:
        if preflight_run_id != run_id:
            raise PreflightControllerError("preflight run identity changed")
        expected_identity = planned_worker_identity(
            plan,
            fixture_id=invocation.fixture_id,
            lifecycle=invocation.lifecycle,
            source_sha=source_sha,
            row_run_id=invocation.row_run_id,
            resume_checkpoint_sha256=(
                invocation.resume_checkpoint.get("state_sha256")
                if isinstance(invocation.resume_checkpoint, Mapping)
                else None
            ),
            preflight_run_id=preflight_run_id,
        )
        identity_evidence = compare_invocation_identity(
            expected_identity, invocation.intended_identity
        )
        if identity_evidence.get("status") != "matched":
            raise PreflightControllerError("invocation_identity_mismatch")
        return profile_runner.supervise_preflight_row(
            fixture_id=invocation.fixture_id,
            party_size=plan.party_size,
            planned_row_id=plan.row_id,
            arm=plan.arm,
            source_sha=source_sha,
            row_run_id=invocation.row_run_id,
            lifecycle=invocation.lifecycle,
            resume_checkpoint_sha256=(
                invocation.resume_checkpoint.get("state_sha256")
                if isinstance(invocation.resume_checkpoint, Mapping)
                else None
            ),
            preflight_run_id=preflight_run_id,
        )

    def cleanup(plan: PreflightRowPlan, seeded: Mapping[str, Any]) -> bool:
        fixture_id = seeded.get("fixture_id") if isinstance(seeded, Mapping) else None
        if fixture_id not in plan.fixture_ids:
            raise PreflightControllerError("cleanup_fixture_identity_mismatch")
        return sandbox.remove_prepared_sandbox(
            {
                "row_id": plan.row_id,
                "fixture_id": fixture_id,
                "party_size": plan.party_size,
                "arm": plan.arm,
                "fixed_seed": plan.fixed_seed,
            },
            seeded,
        )

    return PreflightInterfaces(
        prepare_sandbox=prepare,
        supervise_row=supervise,
        cleanup_sandbox=cleanup,
        safety_counters=safety_counters,
    )


def run_preflight_rows_supervised(
    *,
    source_sha: str,
    run_id: str,
    intended_worker_identities: Mapping[str, Mapping[str, Any]],
    safety_counters: Callable[[], Mapping[str, Any]],
    intended_lifecycle_identities: Mapping[
        str, Mapping[str, Mapping[str, Mapping[str, Any]]]
    ]
    | None = None,
    prereg_root: str | Path | None = None,
    resume_checkpoints: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the frozen rows through their real guarded worker/driver lifecycle."""
    return run_preflight_rows(
        source_sha=source_sha,
        run_id=run_id,
        intended_worker_identities=intended_worker_identities,
        intended_lifecycle_identities=intended_lifecycle_identities,
        interfaces=supervised_preflight_interfaces(
            run_id=run_id,
            safety_counters=safety_counters,
        ),
        prereg_root=prereg_root,
        resume_checkpoints=resume_checkpoints,
    )


def planned_worker_identity(
    plan: PreflightRowPlan,
    *,
    fixture_id: str | None = None,
    lifecycle: str = "startup",
    source_sha: str,
    row_run_id: str,
    resume_checkpoint_sha256: str | None = None,
    preflight_run_id: str | None = None,
) -> dict[str, Any]:
    """Build the trusted worker identity from the source-bound row plan."""
    from scripts import live_gate_preflight_sandbox as sandbox

    selected_fixture = fixture_id or plan.fixture_id
    if selected_fixture not in plan.fixture_ids or lifecycle not in _LIFECYCLES:
        raise PreflightControllerError("planned lifecycle fixture is invalid")
    try:
        seed_plan, _profile = sandbox._load_profile_seed_plan(
            selected_fixture, plan.party_size, plan.row_id
        )
        counterbalance = seed_plan.get("counterbalance")
        if (
            seed_plan.get("fixture_id") != selected_fixture
            or seed_plan.get("party_size") != plan.party_size
            or seed_plan.get("arm") != plan.arm
            or not isinstance(counterbalance, Mapping)
            or counterbalance.get("row_id") != plan.row_id
            or counterbalance.get("fixed_seed") != plan.fixed_seed
        ):
            raise PreflightControllerError("seed plan does not match the frozen row")
        invocation = sandbox._planned_worker_invocation(
            PROJECT_ROOT,
            seed_plan,
            lifecycle=lifecycle,
            source_sha=source_sha,
            run_id=row_run_id,
            resume_checkpoint_sha256=resume_checkpoint_sha256,
            preflight_run_id=preflight_run_id,
        )
    except PreflightControllerError:
        raise
    except Exception as exc:
        raise PreflightControllerError("planned worker identity is unavailable") from exc
    return invocation.identity()


def run_preflight_rows(
    *,
    source_sha: str,
    run_id: str,
    intended_worker_identities: Mapping[str, Mapping[str, Any]],
    interfaces: PreflightInterfaces,
    intended_lifecycle_identities: Mapping[
        str, Mapping[str, Mapping[str, Mapping[str, Any]]]
    ]
    | None = None,
    prereg_root: str | Path | None = None,
    resume_checkpoints: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Exercise frozen row transport and every supplied, declared lifecycle.

    A row's primary startup always supplies the required first transport
    exchange. Additional fixture startup and resume paths run only when they
    have a measured declaration; each such launch needs an independent
    row/fixture/lifecycle invocation declaration. Resume also requires an
    explicit row-bound checkpoint. Missing declarations/checkpoints remain
    unverified, not covered.
    """
    if not isinstance(source_sha, str) or _SOURCE_SHA.fullmatch(source_sha) is None:
        raise PreflightControllerError("source SHA is invalid")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise PreflightControllerError("preflight run ID is invalid")

    planned_rows, reserve_row_ids = _load_frozen_row_ids(prereg_root)
    expected_ids = [row["row_id"] for row in planned_rows]
    if not isinstance(intended_worker_identities, Mapping) or set(
        intended_worker_identities
    ) != set(expected_ids):
        raise PreflightControllerError(
            "intended worker identities must cover exactly the planned rows"
        )
    lifecycle_identity_map = _validate_intended_lifecycle_identity_map(
        intended_lifecycle_identities, expected_row_ids=expected_ids
    )

    profiles, profile_coverage = _load_profiles(expected_ids)
    checkpoint_map = _validate_resume_checkpoint_map(
        resume_checkpoints, expected_row_ids=expected_ids, profiles=profiles
    )
    counters_before = _read_safety_counters(interfaces.safety_counters)
    row_results: list[dict[str, Any]] = []
    failure_seen = False

    for frozen_row in planned_rows:
        row_id = str(frozen_row["row_id"])
        row_run_id = "pf-%s-%s" % (run_id, row_id)
        row_result: dict[str, Any] = {
            "row_id": row_id,
            "row_run_id": row_run_id,
            "status": "blocked",
            "booking_eligible": False,
            "failure_code": None,
        }
        plan: PreflightRowPlan | None = None
        profile_checks: dict[str, dict[str, Any]] = {}
        try:
            plan = _resolve_row_plan(
                row_id,
                prereg_root=prereg_root,
                expected_row=frozen_row,
                profiles=profiles,
            )
            row_lifecycle_identities = lifecycle_identity_map.get(row_id, {})
            if not set(row_lifecycle_identities).issubset(set(plan.fixture_ids)):
                raise PreflightControllerError(
                    "intended_lifecycle_identity_fixture_invalid"
                )
            for fixture_id, checkpoint in checkpoint_map.get(row_id, {}).items():
                _validate_checkpoint_for_plan(plan, fixture_id, checkpoint)
            intended_identity = intended_worker_identities[row_id]
            expected_identity = planned_worker_identity(
                plan,
                fixture_id=plan.fixture_id,
                lifecycle="startup",
                source_sha=source_sha,
                row_run_id=row_run_id,
                preflight_run_id=run_id,
            )
            identity_evidence = compare_invocation_identity(
                expected_identity, intended_identity
            )
            row_result.update(
                {
                    "fixture_id": plan.fixture_id,
                    "fixture_ids": list(plan.fixture_ids),
                    "party_size": plan.party_size,
                    "script_id": plan.script.get("script_id"),
                    "first_step_id": plan.first_turn["step_id"],
                    "first_character": plan.first_turn["character"],
                    "lifecycle_profiles": [
                        dict(item) for item in plan.lifecycle_profiles
                    ],
                    "lifecycle_profile_status": "unverified",
                    "invocation_identity": identity_evidence,
                    "transport_status": "not_started",
                    "lifecycle_coverage_status": "unverified",
                    "lifecycle_results": [],
                }
            )
            if identity_evidence["status"] != "matched":
                row_result["failure_code"] = "invocation_identity_mismatch"
                failure_seen = True
                row_results.append(row_result)
                break

            primary_transport_completed = False
            fixture_order = list(plan.fixture_ids)
            for fixture_index, fixture_id in enumerate(fixture_order):
                profile = _fixture_lifecycle_profile(plan, fixture_id)
                startup_declaration = profile.get("startup")
                startup_status = (
                    startup_declaration.get("status")
                    if isinstance(startup_declaration, Mapping)
                    else None
                )
                if startup_status not in ("MISSING", "measured-under-stub"):
                    raise PreflightControllerError("startup_profile_status_unsupported")
                if (
                    startup_status == "measured-under-stub"
                    and isinstance(startup_declaration, Mapping)
                    and startup_declaration.get("source_sha") != source_sha
                ):
                    raise PreflightControllerError("startup_profile_source_mismatch")
                run_startup = (
                    fixture_id == plan.fixture_id
                    or startup_status == "measured-under-stub"
                )
                if run_startup:
                    startup_run_id = _lifecycle_run_id(
                        run_id,
                        row_id,
                        fixture_index,
                        "startup",
                        primary=fixture_id == plan.fixture_id,
                    )
                    startup_identity = (
                        intended_identity
                        if fixture_id == plan.fixture_id
                        else _require_intended_lifecycle_identity(
                            lifecycle_identity_map,
                            row_id=row_id,
                            fixture_id=fixture_id,
                            lifecycle="startup",
                        )
                    )
                    startup_invocation = PreflightLifecycleInvocation(
                        fixture_id=fixture_id,
                        lifecycle="startup",
                        row_run_id=startup_run_id,
                        intended_identity=startup_identity,
                    )
                    startup_evidence = _run_lifecycle_invocation(
                        plan,
                        startup_invocation,
                        source_sha=source_sha,
                        preflight_run_id=run_id,
                        interfaces=interfaces,
                    )
                    startup_check = _compare_lifecycle_profile(
                        profile,
                        lifecycle="startup",
                        observed_call_count=startup_evidence["call_count"],
                        observed_call_sites=startup_evidence["call_sites"],
                        source_sha=source_sha,
                    )
                    profile_checks.setdefault(fixture_id, {})["startup"] = startup_check
                    row_result["lifecycle_results"].append(
                        {
                            "fixture_id": fixture_id,
                            "lifecycle": "startup",
                            "run_id": startup_run_id,
                            "transport_status": "completed",
                            "profile_check": startup_check,
                            "first_exchange": startup_evidence["first_exchange"],
                            "worker_teardown": startup_evidence["worker_teardown"],
                            "sandbox_cleanup": True,
                        }
                    )
                    if fixture_id == plan.fixture_id:
                        primary_transport_completed = True
                        row_result["first_exchange"] = startup_evidence["first_exchange"]
                        row_result["worker_teardown"] = startup_evidence["worker_teardown"]
                        row_result["transport_status"] = "completed"
                        row_result["fixture_resolution"] = "validated"
                        row_result["startup_profile_check"] = startup_check
                    if startup_check["status"] == "mismatched":
                        raise PreflightControllerError(startup_check["failure_code"])
                else:
                    profile_checks.setdefault(fixture_id, {})["startup"] = {
                        "status": "unverified",
                        "profile_status": startup_status or "MISSING",
                        "reason": (
                            startup_declaration.get("reason")
                            if isinstance(startup_declaration, Mapping)
                            else "startup_profile_missing"
                        ),
                    }

                resume_declaration = profile.get("resume")
                resume_status = (
                    resume_declaration.get("status")
                    if isinstance(resume_declaration, Mapping)
                    else None
                )
                checkpoint = checkpoint_map.get(row_id, {}).get(fixture_id)
                if (
                    resume_status == "measured-under-stub"
                    and isinstance(resume_declaration, Mapping)
                    and resume_declaration.get("source_sha") != source_sha
                ):
                    raise PreflightControllerError("resume_profile_source_mismatch")
                if resume_status == "measured-under-stub" and checkpoint is None:
                    profile_checks.setdefault(fixture_id, {})["resume"] = {
                        "status": "unverified",
                        "profile_status": "MISSING",
                        "checkpoint_status": "MISSING",
                        "reason": "row_bound_resume_checkpoint_missing",
                    }
                elif resume_status == "MISSING":
                    profile_checks.setdefault(fixture_id, {})["resume"] = {
                        "status": "unverified",
                        "profile_status": "MISSING",
                        "checkpoint_status": (
                            "supplied_but_not_used" if checkpoint is not None else "MISSING"
                        ),
                        "reason": (
                            resume_declaration.get("reason")
                            if isinstance(resume_declaration, Mapping)
                            else "resume_profile_missing"
                        ),
                    }
                elif resume_status != "measured-under-stub":
                    profile_checks.setdefault(fixture_id, {})["resume"] = {
                        "status": "mismatched",
                        "profile_status": resume_status,
                        "checkpoint_status": "not_checked",
                        "failure_code": "resume_profile_status_unsupported",
                    }
                    raise PreflightControllerError("resume_profile_status_unsupported")
                else:
                    resume_run_id = _lifecycle_run_id(
                        run_id,
                        row_id,
                        fixture_index,
                        "resume",
                        primary=False,
                    )
                    resume_identity = _require_intended_lifecycle_identity(
                        lifecycle_identity_map,
                        row_id=row_id,
                        fixture_id=fixture_id,
                        lifecycle="resume",
                    )
                    resume_invocation = PreflightLifecycleInvocation(
                        fixture_id=fixture_id,
                        lifecycle="resume",
                        row_run_id=resume_run_id,
                        intended_identity=resume_identity,
                        resume_checkpoint=checkpoint,
                    )
                    resume_evidence = _run_lifecycle_invocation(
                        plan,
                        resume_invocation,
                        source_sha=source_sha,
                        preflight_run_id=run_id,
                        interfaces=interfaces,
                    )
                    resume_check = _compare_lifecycle_profile(
                        profile,
                        lifecycle="resume",
                        observed_call_count=resume_evidence["call_count"],
                        observed_call_sites=resume_evidence["call_sites"],
                        source_sha=source_sha,
                    )
                    resume_check["checkpoint_status"] = "matched_moved_checkpoint"
                    resume_check["checkpoint_sha256"] = checkpoint["state_sha256"]
                    profile_checks.setdefault(fixture_id, {})["resume"] = resume_check
                    row_result["lifecycle_results"].append(
                        {
                            "fixture_id": fixture_id,
                            "lifecycle": "resume",
                            "run_id": resume_run_id,
                            "transport_status": "completed",
                            "profile_check": resume_check,
                            "first_exchange": resume_evidence["first_exchange"],
                            "worker_teardown": resume_evidence["worker_teardown"],
                            "sandbox_cleanup": True,
                        }
                    )
                    if resume_check["status"] == "mismatched":
                        raise PreflightControllerError(resume_check["failure_code"])

            if not primary_transport_completed:
                raise PreflightControllerError("primary_startup_transport_not_exercised")
            row_result["lifecycle_profile_checks"] = profile_checks
            row_result["lifecycle_profile_status"] = _lifecycle_profile_status(
                profile_checks
            )
            row_result["lifecycle_coverage_status"] = row_result[
                "lifecycle_profile_status"
            ]
        except Exception as exc:
            if row_result.get("failure_code") is None:
                row_result["failure_code"] = _failure_code(exc)
            if isinstance(exc, FixtureResolutionError):
                row_result["unresolved_reference"] = exc.unresolved_reference
            if isinstance(exc, PreflightLifecycleIdentityError):
                row_result.setdefault(
                    "lifecycle_invocation_identity_checks", []
                ).append(
                    {
                        "fixture_id": exc.fixture_id,
                        "lifecycle": exc.lifecycle,
                        "check": exc.evidence,
                    }
                )
            if profile_checks:
                row_result["lifecycle_profile_checks"] = profile_checks
                row_result["lifecycle_profile_status"] = _lifecycle_profile_status(
                    profile_checks
                )
                row_result["lifecycle_coverage_status"] = row_result[
                    "lifecycle_profile_status"
                ]
            failure_seen = True

        try:
            row_counters = _read_safety_counters(interfaces.safety_counters)
        except PreflightControllerError as exc:
            row_counters = counters_before
            row_result["failure_code"] = row_result.get("failure_code") or _failure_code(exc)
            failure_seen = True
        if row_counters != counters_before:
            row_result["failure_code"] = row_result.get("failure_code") or "preflight_counter_changed"
            failure_seen = True
        row_result["safety_counter_delta"] = _counter_delta(
            counters_before, row_counters
        )

        if row_result.get("failure_code") is None and row_result.get("transport_status") == "completed":
            row_result["status"] = (
                "completed"
                if row_result.get("lifecycle_coverage_status") == "matched"
                else "transport_completed_unverified"
            )
        row_results.append(row_result)
        if failure_seen:
            break

    counters_after = _read_safety_counters(interfaces.safety_counters)
    if counters_after != counters_before:
        failure_seen = True
    completed_rows = [row for row in row_results if row.get("status") == "completed"]
    transport_completed_rows = [
        row for row in row_results if row.get("transport_status") == "completed"
    ]
    unverified_rows = sorted(
        set(profile_coverage.get("unverified_row_ids", []))
        | {
            row["row_id"]
            for row in row_results
            if row.get("lifecycle_profile_status") != "matched"
        },
        key=expected_ids.index,
    )
    return {
        "schema_version": 1,
        "report_type": "provider-free-row-preflight",
        "preflight_only": True,
        "source_sha": source_sha,
        "run_id": run_id,
        "status": (
            "blocked"
            if failure_seen
            else "completed"
            if len(completed_rows) == 26
            else "unverified"
            if len(transport_completed_rows) == 26
            else "blocked"
        ),
        "transport_status": (
            "completed" if len(transport_completed_rows) == 26 else "incomplete"
        ),
        "lifecycle_coverage_status": (
            "matched" if len(completed_rows) == 26 else "unverified"
        ),
        "planned_row_count": 26,
        "planned_row_ids": expected_ids,
        "attempted_row_ids": [row["row_id"] for row in row_results],
        "row_results": row_results,
        "fully_covered_row_ids": [row["row_id"] for row in completed_rows],
        "transport_completed_row_ids": [
            row["row_id"] for row in transport_completed_rows
        ],
        "replacement_only_row_ids": reserve_row_ids,
        "replacement_only_rows_activated": [],
        "unverified_profile_row_ids": unverified_rows,
        "provider_free": {
            "upstream_provider_requests_delta": counters_after[
                "upstream_provider_requests"
            ]
            - counters_before["upstream_provider_requests"],
            "provider_budget_used_delta": counters_after["provider_budget_used"]
            - counters_before["provider_budget_used"],
            "live_attempts_used_delta": counters_after["live_attempts_used"]
            - counters_before["live_attempts_used"],
            "reserve_activations_delta": counters_after["reserve_activations"]
            - counters_before["reserve_activations"],
            "router_stub_calls": sum(
                int(lifecycle.get("worker_teardown", {}).get("call_count", 0))
                for row in row_results
                for lifecycle in row.get("lifecycle_results", [])
                if isinstance(lifecycle, Mapping)
                and isinstance(lifecycle.get("worker_teardown"), Mapping)
            ),
        },
        "pilot_evidence_written": False,
        "booking_eligible": False,
        "live_gate_pass": False,
        "profile_coverage": profile_coverage,
    }


def _load_frozen_row_ids(
    prereg_root: str | Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    root = Path(prereg_root) if prereg_root is not None else DEFAULT_PREREG_ROOT
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    verified = verify_manifest(root)
    if "counterbalance.json" not in verified:
        raise PreflightControllerError("counterbalance is not covered by the manifest")
    try:
        value = json.loads((root / "counterbalance.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightControllerError("frozen counterbalance cannot be read") from exc
    rows = value.get("rows") if isinstance(value, Mapping) else None
    if not isinstance(rows, list):
        raise PreflightControllerError("frozen counterbalance rows are malformed")
    planned = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("row_type") == "planned"
    ]
    reserves = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("row_type") == "replacement_only"
    ]
    if (
        value.get("planned_rows") != 26
        or value.get("reserve_rows") != 4
        or value.get("total_rows") != 30
        or len(rows) != 30
        or len(planned) != 26
        or len(reserves) != 4
    ):
        raise PreflightControllerError("frozen planned and reserve row counts changed")
    planned.sort(key=lambda row: row.get("run_order", 0))
    if [row.get("run_order") for row in planned] != list(range(1, 27)):
        raise PreflightControllerError("planned row order is not the frozen 1-26 sequence")
    if any(
        not isinstance(row.get("row_id"), str) or row["row_id"].startswith("R")
        for row in planned
    ):
        raise PreflightControllerError("replacement row appeared in the planned set")
    reserve_ids = [
        str(row.get("row_id"))
        for row in sorted(reserves, key=lambda row: row.get("run_order", 0))
    ]
    if any(not row_id.startswith("R") for row_id in reserve_ids):
        raise PreflightControllerError("replacement-only row identity is invalid")
    return planned, reserve_ids


def _load_profiles(
    expected_row_ids: list[str],
) -> tuple[dict[tuple[str, int], Mapping[str, Any]], dict[str, Any]]:
    from scripts.live_gate_preflight_profiles import (
        copy_profile_document,
        load_profile_coverage,
    )

    try:
        coverage = load_profile_coverage(expected_source_sha=None)
        document = copy_profile_document()
    except Exception as exc:
        raise PreflightControllerError("lifecycle profile declaration is invalid") from exc
    if (
        coverage.get("structural_row_coverage_complete") is not True
        or coverage.get("planned_row_ids") != expected_row_ids
        or coverage.get("planned_row_count") != 26
        or coverage.get("fixture_party_pair_count") != 8
        or coverage.get("replacement_only_rows_activated") != []
        or not isinstance(coverage.get("unverified_row_ids"), list)
        or any(row_id not in expected_row_ids for row_id in coverage["unverified_row_ids"])
    ):
        raise PreflightControllerError("lifecycle profile coverage differs from frozen rows")
    raw_profiles = document.get("profiles")
    if not isinstance(raw_profiles, list):
        raise PreflightControllerError("lifecycle profile declaration is malformed")
    profiles: dict[tuple[str, int], Mapping[str, Any]] = {}
    for profile in raw_profiles:
        if not isinstance(profile, Mapping):
            raise PreflightControllerError("lifecycle profile entry is malformed")
        pair = (profile.get("fixture_id"), profile.get("party_size"))
        if pair in profiles:
            raise PreflightControllerError("lifecycle profile pair is duplicated")
        profiles[pair] = profile
    return profiles, coverage


def _resolve_row_plan(
    row_id: str,
    *,
    prereg_root: str | Path | None,
    expected_row: Mapping[str, Any],
    profiles: Mapping[tuple[str, int], Mapping[str, Any]],
) -> PreflightRowPlan:
    try:
        row, script, fixture_id = row_runner._resolve_frozen_row(row_id, prereg_root)
    except Exception as exc:
        raise PreflightControllerError("frozen row resolution failed") from exc
    for key in ("row_id", "arm", "party", "fixed_seed", "script", "run_order", "row_type"):
        if row.get(key) != expected_row.get(key):
            raise PreflightControllerError(
                "row resolver differs from frozen counterbalance"
            )
    if row.get("row_type") != "planned" or row_id.startswith("R"):
        raise PreflightControllerError("replacement-only row cannot be exercised")
    fixture_ids = script.get("fixture_ids")
    turns = script.get("turns")
    party_size = row.get("party")
    if (
        not isinstance(fixture_ids, list)
        or not fixture_ids
        or any(not isinstance(item, str) for item in fixture_ids)
        or type(party_size) is not int
        or party_size not in (1, 4)
        or not isinstance(turns, list)
        or not turns
    ):
        raise PreflightControllerError("scripted row identity is malformed")
    first = turns[0]
    actor = first.get("actor") if isinstance(first, Mapping) else None
    character = actor.get("party_%d" % party_size) if isinstance(actor, Mapping) else None
    step_id = first.get("id") if isinstance(first, Mapping) else None
    utterance = first.get("utterance") if isinstance(first, Mapping) else None
    if (
        not isinstance(step_id, str)
        or not step_id
        or not isinstance(utterance, str)
        or not utterance.strip()
        or not isinstance(character, str)
        or not character.strip()
    ):
        raise PreflightControllerError("first scripted exchange is malformed")

    lifecycle_profiles: list[Mapping[str, Any]] = []
    for selected_fixture in fixture_ids:
        profile = profiles.get((selected_fixture, party_size))
        if (
            not isinstance(profile, Mapping)
            or row_id not in profile.get("planned_row_ids", [])
        ):
            raise PreflightControllerError("fixture-party lifecycle profile is missing")
        lifecycles: dict[str, Any] = {}
        for lifecycle in _LIFECYCLES:
            declared = profile.get(lifecycle)
            if not isinstance(declared, Mapping):
                raise PreflightControllerError("declared lifecycle profile is malformed")
            lifecycles[lifecycle] = declared.get("status")
        lifecycle_profiles.append(
            {
                "profile_id": profile.get("profile_id"),
                "fixture_id": selected_fixture,
                "party_size": party_size,
                "startup_status": lifecycles["startup"],
                "resume_status": lifecycles["resume"],
                "startup_call_count": (
                    profile["startup"].get("call_count")
                    if isinstance(profile.get("startup"), Mapping)
                    else None
                ),
                "startup_call_sites": (
                    [dict(site) for site in profile["startup"].get("call_sites", [])]
                    if isinstance(profile.get("startup"), Mapping)
                    and isinstance(profile["startup"].get("call_sites"), list)
                    else None
                ),
                "startup_reason": (
                    profile["startup"].get("reason")
                    if isinstance(profile.get("startup"), Mapping)
                    else None
                ),
                "startup": dict(profile["startup"]),
                "resume": dict(profile["resume"]),
                "resume_checkpoint_status": "not_supplied",
                "resume_reason": (
                    profile["resume"].get("reason")
                    if isinstance(profile.get("resume"), Mapping)
                    else None
                ),
            }
        )
    return PreflightRowPlan(
        row_id=row_id,
        row=row,
        script=script,
        fixture_id=fixture_id,
        fixture_ids=tuple(fixture_ids),
        party_size=party_size,
        arm=str(row["arm"]),
        fixed_seed=int(row["fixed_seed"]),
        first_turn={
            "step_id": step_id,
            "utterance": utterance,
            "character": character,
        },
        lifecycle_profiles=tuple(lifecycle_profiles),
    )


def _validate_seed_result(
    plan: PreflightRowPlan,
    seeded: Any,
    identity_evidence: Mapping[str, Any],
    *,
    fixture_id: str,
) -> None:
    if (
        not isinstance(seeded, Mapping)
        or seeded.get("status") != "prepared"
        or fixture_id not in plan.fixture_ids
        or seeded.get("fixture_id") != fixture_id
        or seeded.get("party_size") != plan.party_size
        or seeded.get("planned_row_id") != plan.row_id
        or seeded.get("arm") != plan.arm
        or seeded.get("effective_seed") != plan.fixed_seed
        or identity_evidence.get("status") != "matched"
    ):
        raise FixtureResolutionError(
            "seeded_fixture_identity_mismatch", "mapping_pilot/seed_metadata.json"
        )


def _validate_sandbox_result(
    plan: PreflightRowPlan,
    validated: Any,
    *,
    fixture_id: str,
) -> None:
    metadata = getattr(validated, "metadata", None)
    fixture_payloads = getattr(validated, "fixture_payloads", None)
    if isinstance(validated, Mapping):
        metadata = validated.get("metadata", metadata)
        fixture_payloads = validated.get("fixture_payloads", fixture_payloads)
    party = metadata.get("party") if isinstance(metadata, Mapping) else None
    counterbalance = metadata.get("counterbalance") if isinstance(metadata, Mapping) else None
    members = party.get("members") if isinstance(party, Mapping) else None
    mapping = metadata.get("mapping") if isinstance(metadata, Mapping) else None
    runtime_to_source = getattr(validated, "runtime_to_source", None)
    if isinstance(validated, Mapping):
        runtime_to_source = validated.get("runtime_to_source", runtime_to_source)
    if not isinstance(metadata, Mapping) or metadata.get("fixture_id") != fixture_id:
        raise FixtureResolutionError(
            "seed_metadata_fixture_mismatch", "mapping_pilot/seed_metadata.json"
        )
    if (
        not isinstance(party, Mapping)
        or party.get("size") != plan.party_size
        or not isinstance(members, list)
        or len(members) != plan.party_size
    ):
        raise FixtureResolutionError("party_record_mismatch", "party_tracker.json")
    if (
        not isinstance(counterbalance, Mapping)
        or counterbalance.get("row_id") != plan.row_id
        or counterbalance.get("fixed_seed") != plan.fixed_seed
    ):
        raise FixtureResolutionError(
            "counterbalance_metadata_mismatch", "mapping_pilot/seed_metadata.json"
        )
    if not isinstance(fixture_payloads, Mapping):
        raise FixtureResolutionError(
            "fixture_payloads_unavailable", "mapping_pilot/expected"
        )
    for expected_fixture_id in plan.fixture_ids:
        payload = fixture_payloads.get(expected_fixture_id)
        if (
            not isinstance(payload, Mapping)
            or payload.get("fixture_id") != expected_fixture_id
            or not isinstance(payload.get("location_ids"), list)
            or not payload.get("location_ids")
        ):
            raise FixtureResolutionError(
                "fixture_payload_missing",
                "mapping_pilot/expected/%s.json" % expected_fixture_id,
            )
    if (
        not isinstance(mapping, Mapping)
        or not isinstance(mapping.get("runtime_location_id"), str)
        or not isinstance(runtime_to_source, Mapping)
        or runtime_to_source.get(mapping["runtime_location_id"])
        != mapping.get("source_location_id")
        or mapping.get("id_map_file") != "modules/mapping_pilot/location_id_map.json"
    ):
        raise FixtureResolutionError(
            "location_mapping_unresolved", "modules/mapping_pilot/location_id_map.json"
        )


def _validate_supervised_result(
    result: Mapping[str, Any],
    *,
    plan: PreflightRowPlan,
    fixture_id: str,
    lifecycle: str,
    intended_identity: Mapping[str, Any],
    source_sha: str,
    row_run_id: str,
    preflight_run_id: str,
) -> dict[str, Any]:
    evidence = result.get("evidence")
    if not isinstance(evidence, Mapping):
        raise PreflightControllerError("guarded row evidence is unavailable")
    calls = evidence.get("calls")
    call_count = evidence.get("call_count")
    call_sites = evidence.get("call_sites")
    shutdown = evidence.get("worker_shutdown")
    shutdown_request = shutdown.get("request") if isinstance(shutdown, Mapping) else None
    invocation_identity = evidence.get("invocation_identity")
    teardown = evidence.get("teardown")
    driver_exchange = evidence.get("driver_exchange")
    expected_evidence_path = (
        "tmp/router-rollout/live-gate-preflight/%s/preflight/rows/%s/profile-evidence.json"
        % (preflight_run_id, row_run_id)
    )
    valid_call_sites = isinstance(call_sites, list) and all(
        isinstance(site, Mapping)
        and type(site.get("count")) is int
        and site["count"] > 0
        for site in call_sites
    )
    observed_site_total = (
        sum(site["count"] for site in call_sites)
        if valid_call_sites
        else None
    )
    if (
        evidence.get("outcome") != "completed"
        or evidence.get("run_id") != row_run_id
        or evidence.get("source_sha") != source_sha
        or evidence.get("planned_row_id") != plan.row_id
        or evidence.get("fixture_id") != fixture_id
        or evidence.get("party_size") != plan.party_size
        or evidence.get("lifecycle") != lifecycle
        or evidence.get("command") != intended_identity.get("command")
        or evidence.get("pythonpath") != intended_identity.get("pythonpath")
        or str(PROJECT_ROOT / str(evidence.get("working_directory", "")))
        != intended_identity.get("working_directory")
        or not isinstance(invocation_identity, Mapping)
        or invocation_identity.get("status") != "matched"
        or evidence.get("network_guard_active") is not True
        or evidence.get("provider_environment_keys_blank") is not True
        or evidence.get("proxy_values_blank") is not True
        or evidence.get("real_project_config_loaded") is not False
        or evidence.get("sandbox_config_loaded") is not True
        or evidence.get("startup_guard_from_sitecustomize") is not True
        or evidence.get("sandbox_config_origin_guard_active") is not True
        or evidence.get("failure_code") is not None
        or not isinstance(shutdown, Mapping)
        or shutdown.get("server_returned") is not True
        or shutdown.get("interrupted") is not True
        or shutdown.get("graceful_shutdown_requested") is not True
        or not isinstance(shutdown_request, Mapping)
        or shutdown_request.get("readiness_succeeded") is not True
        or shutdown_request.get("exchange_succeeded") is not True
        or not isinstance(teardown, Mapping)
        or teardown.get("server_stopped") is not True
        or teardown.get("port_8360_free") is not True
        or teardown.get("port_8370_free") is not True
        or teardown.get("lock_released") is not True
        or type(call_count) is not int
        or call_count < 1
        or not isinstance(calls, list)
        or call_count != len(calls)
        or not valid_call_sites
        or not isinstance(driver_exchange, Mapping)
        or driver_exchange.get("status") != "completed"
        or driver_exchange.get("turn_completed") is not True
        or type(driver_exchange.get("game_output_count")) is not int
        or driver_exchange["game_output_count"] < 1
        or result.get("evidence_path") != expected_evidence_path
        or not isinstance(result.get("evidence_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", result["evidence_sha256"]) is None
        or observed_site_total != call_count
    ):
        raise PreflightControllerError("guarded supervised row evidence is incomplete")
    return {
        "outcome": "completed",
        "first_exchange": dict(driver_exchange),
        "call_count": call_count,
        "call_sites": [dict(site) for site in call_sites],
        "provider_environment_keys_blank": True,
        "proxy_values_blank": True,
        "real_project_config_loaded": False,
        "invocation_identity_status": "matched",
        "worker_teardown": {
            "server_stopped": True,
            "port_8360_free": True,
            "port_8370_free": True,
            "shared_live_window_lock_released": True,
            "guard_active": True,
            "call_count": call_count,
        },
    }


def _run_lifecycle_invocation(
    plan: PreflightRowPlan,
    invocation: PreflightLifecycleInvocation,
    *,
    source_sha: str,
    preflight_run_id: str,
    interfaces: PreflightInterfaces,
) -> dict[str, Any]:
    """Prepare, validate, supervise, and clean one guarded lifecycle run."""
    checkpoint = invocation.resume_checkpoint
    checkpoint_sha256 = (
        checkpoint.get("state_sha256") if isinstance(checkpoint, Mapping) else None
    )
    expected_identity = planned_worker_identity(
        plan,
        fixture_id=invocation.fixture_id,
        lifecycle=invocation.lifecycle,
        source_sha=source_sha,
        row_run_id=invocation.row_run_id,
        resume_checkpoint_sha256=(
            str(checkpoint_sha256) if checkpoint_sha256 is not None else None
        ),
        preflight_run_id=preflight_run_id,
    )
    identity_evidence = compare_invocation_identity(
        expected_identity, invocation.intended_identity
    )
    if identity_evidence.get("status") != "matched":
        raise PreflightLifecycleIdentityError(
            fixture_id=invocation.fixture_id,
            lifecycle=invocation.lifecycle,
            evidence=identity_evidence,
        )

    seeded: Mapping[str, Any] | None = None
    try:
        from scripts.live_gate_preflight_safety import run_after_invocation_identity

        try:
            seeded, seed_identity = run_after_invocation_identity(
                expected_identity,
                invocation.intended_identity,
                lambda: interfaces.prepare_sandbox(
                    plan, invocation, source_sha, preflight_run_id
                ),
            )
        except Exception as exc:
            raise FixtureResolutionError(
                "sandbox_preparation_failed", "mapping_pilot/seed_metadata.json"
            ) from exc
        _validate_seed_result(
            plan,
            seeded,
            seed_identity,
            fixture_id=invocation.fixture_id,
        )
        if seeded.get("sandbox_root") != "tmp/combat_capture":
            raise FixtureResolutionError(
                "seeded_sandbox_root_mismatch", "tmp/combat_capture"
            )
        try:
            validated = launcher.validate_sandbox(
                PROJECT_ROOT / "tmp/combat_capture",
                arm=plan.arm,
                fixture_id=invocation.fixture_id,
                party_size=plan.party_size,
                resume=invocation.lifecycle == "resume",
                resume_checkpoint_sha256=(
                    str(checkpoint_sha256)
                    if invocation.lifecycle == "resume"
                    else None
                ),
                project_root=PROJECT_ROOT,
            )
        except Exception as exc:
            raise FixtureResolutionError(
                "launcher_sandbox_validation_failed", "launcher.validate_sandbox"
            ) from exc
        _validate_sandbox_result(
            plan,
            validated,
            fixture_id=invocation.fixture_id,
        )
        supervised = interfaces.supervise_row(
            plan,
            seeded,
            invocation,
            source_sha,
            preflight_run_id,
        )
        return _validate_supervised_result(
            supervised,
            plan=plan,
            fixture_id=invocation.fixture_id,
            lifecycle=invocation.lifecycle,
            intended_identity=invocation.intended_identity,
            source_sha=source_sha,
            row_run_id=invocation.row_run_id,
            preflight_run_id=preflight_run_id,
        )
    finally:
        if isinstance(seeded, Mapping):
            try:
                sandbox_clean = interfaces.cleanup_sandbox(plan, seeded)
            except Exception as exc:
                raise PreflightControllerError(
                    "sandbox_cleanup_failed_" + type(exc).__name__
                ) from exc
            if sandbox_clean is not True:
                raise PreflightControllerError("sandbox_cleanup_unverified")


def _fixture_lifecycle_profile(
    plan: PreflightRowPlan, fixture_id: str
) -> Mapping[str, Any]:
    profile = next(
        (item for item in plan.lifecycle_profiles if item.get("fixture_id") == fixture_id),
        None,
    )
    if not isinstance(profile, Mapping):
        raise PreflightControllerError("fixture-party lifecycle profile is missing")
    return profile


def _lifecycle_run_id(
    run_id: str,
    row_id: str,
    fixture_index: int,
    lifecycle: str,
    *,
    primary: bool,
) -> str:
    base = "pf-%s-%s" % (run_id, row_id)
    if primary and lifecycle == "startup":
        return base
    suffix = "s" if lifecycle == "startup" else "r"
    return "%s-f%d-%s" % (base, fixture_index + 1, suffix)


def _validate_intended_lifecycle_identity_map(
    value: Any, *, expected_row_ids: list[str]
) -> dict[str, dict[str, dict[str, Mapping[str, Any]]]]:
    """Validate caller declarations without manufacturing launch identities."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PreflightControllerError("intended_lifecycle_identity_map_malformed")
    expected_rows = set(expected_row_ids)
    normalized: dict[str, dict[str, dict[str, Mapping[str, Any]]]] = {}
    for row_id, fixture_map in value.items():
        if row_id not in expected_rows or not isinstance(fixture_map, Mapping):
            raise PreflightControllerError("intended_lifecycle_identity_row_invalid")
        normalized_fixture_map: dict[str, dict[str, Mapping[str, Any]]] = {}
        for fixture_id, lifecycle_map in fixture_map.items():
            if not isinstance(fixture_id, str) or not isinstance(lifecycle_map, Mapping):
                raise PreflightControllerError(
                    "intended_lifecycle_identity_fixture_invalid"
                )
            normalized_lifecycle_map: dict[str, Mapping[str, Any]] = {}
            for lifecycle, identity in lifecycle_map.items():
                if (
                    lifecycle not in _LIFECYCLES
                    or not isinstance(identity, Mapping)
                    or set(identity)
                    != {"command", "working_directory", "pythonpath"}
                ):
                    raise PreflightControllerError(
                        "intended_lifecycle_identity_declaration_invalid"
                    )
                normalized_lifecycle_map[str(lifecycle)] = identity
            normalized_fixture_map[fixture_id] = normalized_lifecycle_map
        normalized[str(row_id)] = normalized_fixture_map
    return normalized


def _require_intended_lifecycle_identity(
    identity_map: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]],
    *,
    row_id: str,
    fixture_id: str,
    lifecycle: str,
) -> Mapping[str, Any]:
    """Return an independent caller declaration for a launch or fail closed."""
    fixture_map = identity_map.get(row_id)
    lifecycle_map = fixture_map.get(fixture_id) if isinstance(fixture_map, Mapping) else None
    identity = lifecycle_map.get(lifecycle) if isinstance(lifecycle_map, Mapping) else None
    if not isinstance(identity, Mapping):
        raise PreflightControllerError("intended_lifecycle_identity_missing")
    return identity


def _validate_resume_checkpoint_map(
    value: Mapping[str, Mapping[str, Mapping[str, Any]]] | None,
    *,
    expected_row_ids: list[str],
    profiles: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PreflightControllerError("resume checkpoint map is malformed")
    result: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row_id, fixture_checkpoints in value.items():
        if row_id not in expected_row_ids or not isinstance(fixture_checkpoints, Mapping):
            raise PreflightControllerError("resume checkpoint row identity is invalid")
        selected: dict[str, Mapping[str, Any]] = {}
        for fixture_id, checkpoint in fixture_checkpoints.items():
            if not isinstance(fixture_id, str) or not isinstance(checkpoint, Mapping):
                raise PreflightControllerError("resume checkpoint fixture entry is malformed")
            matching_profiles = [
                profile
                for (candidate_fixture, _party), profile in profiles.items()
                if candidate_fixture == fixture_id
                and row_id in profile.get("planned_row_ids", [])
            ]
            if len(matching_profiles) != 1:
                raise PreflightControllerError("resume checkpoint fixture is not row-bound")
            _validate_checkpoint_shape(checkpoint)
            selected[fixture_id] = dict(checkpoint)
        result[row_id] = selected
    return result


def _validate_checkpoint_shape(checkpoint: Mapping[str, Any]) -> None:
    required = {
        "checkpoint_root",
        "state_sha256",
        "row_id",
        "fixture_id",
        "party_size",
        "arm",
        "fixed_seed",
    }
    if set(checkpoint) != required:
        raise PreflightControllerError("resume checkpoint fields are invalid")
    path_value = checkpoint.get("checkpoint_root")
    path = PurePosixPath(path_value) if isinstance(path_value, str) else None
    if (
        path is None
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in str(path_value)
        or not path.parts
        or path.parts[0] != "tmp"
        or path.as_posix() == "tmp/combat_capture"
        or not isinstance(checkpoint.get("state_sha256"), str)
        or _CHECKPOINT_SHA256.fullmatch(checkpoint["state_sha256"]) is None
    ):
        raise PreflightControllerError("resume checkpoint identity is invalid")


def _validate_checkpoint_for_plan(
    plan: PreflightRowPlan,
    fixture_id: str,
    checkpoint: Mapping[str, Any],
) -> None:
    _validate_checkpoint_shape(checkpoint)
    if (
        checkpoint.get("row_id") != plan.row_id
        or checkpoint.get("fixture_id") != fixture_id
        or checkpoint.get("party_size") != plan.party_size
        or checkpoint.get("arm") != plan.arm
        or type(checkpoint.get("fixed_seed")) is not int
        or checkpoint.get("fixed_seed") != plan.fixed_seed
    ):
        raise PreflightControllerError("resume checkpoint row binding mismatch")


def _compare_lifecycle_profile(
    profile: Mapping[str, Any],
    *,
    lifecycle: str,
    observed_call_count: int,
    observed_call_sites: list[Mapping[str, Any]],
    source_sha: str,
) -> dict[str, Any]:
    declaration = profile.get(lifecycle)
    if not isinstance(declaration, Mapping):
        return {
            "status": "unverified",
            "profile_status": "MISSING",
            "reason": lifecycle + "_profile_missing",
        }
    if declaration.get("status") == "MISSING":
        return {
            "status": "unverified",
            "profile_status": "MISSING",
            "reason": declaration.get("reason") or lifecycle + "_profile_missing",
            "observed_call_count": observed_call_count,
            "observed_call_sites": [dict(site) for site in observed_call_sites],
        }
    if declaration.get("status") != "measured-under-stub":
        return {
            "status": "mismatched",
            "failure_code": lifecycle + "_profile_status_unsupported",
        }
    if declaration.get("source_sha") != source_sha:
        return {
            "status": "mismatched",
            "failure_code": lifecycle + "_profile_source_mismatch",
            "expected_source_sha": declaration.get("source_sha"),
            "observed_source_sha": source_sha,
        }
    expected_count = declaration.get("call_count")
    expected_sites = declaration.get("call_sites")
    canonical_observed = [dict(site) for site in observed_call_sites]
    if type(expected_count) is not int or observed_call_count != expected_count:
        return {
            "status": "mismatched",
            "failure_code": lifecycle + "_profile_call_count_mismatch",
            "expected_call_count": expected_count,
            "observed_call_count": observed_call_count,
        }
    if expected_sites != canonical_observed:
        return {
            "status": "mismatched",
            "failure_code": lifecycle + "_profile_call_sites_mismatch",
            "expected_call_sites": expected_sites,
            "observed_call_sites": canonical_observed,
        }
    return {
        "status": "matched",
        "profile_status": "measured-under-stub",
        "expected_call_count": expected_count,
        "observed_call_count": observed_call_count,
        "call_sites_matched": True,
    }


def _lifecycle_profile_status(
    checks: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> str:
    statuses = [
        lifecycle_check.get("status")
        for by_lifecycle in checks.values()
        for lifecycle_check in by_lifecycle.values()
    ]
    if any(status == "mismatched" for status in statuses):
        return "mismatched"
    if statuses and all(status == "matched" for status in statuses):
        return "matched"
    return "unverified"


def _read_safety_counters(
    reader: Callable[[], Mapping[str, Any]],
) -> dict[str, int]:
    try:
        value = reader()
    except Exception as exc:
        raise PreflightControllerError("preflight safety counters are unavailable") from exc
    if not isinstance(value, Mapping):
        raise PreflightControllerError("preflight safety counters are malformed")
    result: dict[str, int] = {}
    for field in _COUNTER_FIELDS:
        count = value.get(field)
        if type(count) is not int or count < 0:
            raise PreflightControllerError("preflight safety counters are malformed")
        result[field] = count
    return result


def _counter_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {field: after[field] - before[field] for field in _COUNTER_FIELDS}


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, PreflightControllerError):
        return str(exc).replace(" ", "_")[:100]
    return "preflight_boundary_failed_" + type(exc).__name__
