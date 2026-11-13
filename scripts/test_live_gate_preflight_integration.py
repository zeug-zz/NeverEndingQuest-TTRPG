# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic SP3 row-preflight integration tests; these are not live coverage."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import live_gate_preflight_controller as controller
from scripts.live_gate_preflight_controller import (
    PreflightInterfaces,
    _load_frozen_row_ids,
    _load_profiles,
    _resolve_row_plan,
    planned_worker_identity,
    run_preflight_rows,
)
from scripts import live_gate_preflight_sandbox as sandbox
from scripts import live_gate_preflight_profile_runner as profile_runner
from scripts import live_gate_preflight_safety as safety
from scripts.mapping_pilot import launcher, row_runner, server


SOURCE_SHA = "a" * 40
RUN_ID = "row-integration-test"


class _FakeDecodeScope:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeCaptureSession:
    """Fake the Socket.IO session boundary under the real script adapter."""

    def __init__(self, args: Any, sessions: list["_FakeCaptureSession"]) -> None:
        self.args = args
        self.sessions = sessions
        self.sessions.append(self)
        self.game_outputs: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str, str]] = []
        self.start_readiness = {"ready": True}
        self.disconnected = False
        self.transcript_closed = False

    def open_transcript(self) -> None:
        return None

    def connect(self) -> None:
        return None

    def start_session(self, *, require_ready_quiet: bool) -> bool:
        return require_ready_quiet

    def set_active_character(self, character: str) -> bool:
        return bool(character)

    def output_count(self) -> int:
        return len(self.game_outputs)

    def send_turn(self, step_id: str, utterance: str, character: str) -> Any:
        self.sent.append((step_id, utterance, character))
        self.game_outputs.append(
            {"payload": {"content": "provider-free stub response"}}
        )
        return SimpleNamespace(
            timed_out=False,
            backend_output_count=1,
            new_game_outputs=1,
            elapsed_seconds=0.01,
        )

    def disconnect(self) -> None:
        self.disconnected = True

    def close_transcript(self) -> None:
        self.transcript_closed = True


class _FakeServerLauncher:
    def __init__(self, row_id: str, launches: list[dict[str, Any]]) -> None:
        self.row_id = row_id
        self.launches = launches

    def launch(self, **kwargs: Any) -> Any:
        self.launches.append({"row_id": self.row_id, **kwargs})
        return SimpleNamespace(row_id=self.row_id)


class TestPreflightRowIntegration(unittest.TestCase):
    @staticmethod
    def _caller_declared_identity(
        plan: controller.PreflightRowPlan,
        *,
        fixture_id: str,
        lifecycle: str,
        row_run_id: str,
        resume_checkpoint_sha256: str | None = None,
    ) -> dict[str, Any]:
        lifecycle_id = row_run_id + ("_s" if lifecycle == "startup" else "_r")
        command = [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-P",
            "-m",
            "scripts.live_gate_preflight_profile_runner",
            "--worker",
            "--fixture-id",
            fixture_id,
            "--party-size",
            str(plan.party_size),
            "--lifecycle",
            lifecycle,
            "--source-sha",
            SOURCE_SHA,
            "--run-id",
            row_run_id,
            "--planned-row-id",
            plan.row_id,
            "--arm",
            plan.arm,
            "--lifecycle-id",
            lifecycle_id,
        ]
        if resume_checkpoint_sha256 is not None:
            command.extend(("--resume-checkpoint-sha256", resume_checkpoint_sha256))
        command.extend(("--preflight-run-id", RUN_ID))
        return {
            "command": command,
            "working_directory": str(PROJECT_ROOT / "tmp" / "combat_capture"),
            "pythonpath": os.pathsep.join(
                (
                    str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
                    str(PROJECT_ROOT),
                )
            ),
        }

    @staticmethod
    def _lifecycle_row_run_id(
        plan: controller.PreflightRowPlan, fixture_id: str, lifecycle: str
    ) -> str:
        base = "pf-%s-%s" % (RUN_ID, plan.row_id)
        if fixture_id == plan.fixture_id and lifecycle == "startup":
            return base
        suffix = "s" if lifecycle == "startup" else "r"
        return "%s-f%d-%s" % (base, plan.fixture_ids.index(fixture_id) + 1, suffix)

    def _lifecycle_identity_declaration(
        self,
        plan: controller.PreflightRowPlan,
        *,
        fixture_id: str,
        lifecycle: str,
        resume_checkpoint_sha256: str | None = None,
    ) -> dict[str, Any]:
        row_run_id = self._lifecycle_row_run_id(plan, fixture_id, lifecycle)
        return self._caller_declared_identity(
            plan,
            fixture_id=fixture_id,
            lifecycle=lifecycle,
            row_run_id=row_run_id,
            resume_checkpoint_sha256=resume_checkpoint_sha256,
        )

    @staticmethod
    def _fake_characterization(args: Any) -> tuple[dict[str, Any], str, str]:
        command = profile_runner._host_command(
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            source_sha=args.source_sha,
            run_id=args.run_id,
            planned_row_id=args.planned_row_id,
            arm=args.arm,
            lifecycle_id=args.run_id + ("_s" if args.lifecycle == "startup" else "_r"),
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
            preflight_run_id=args.preflight_run_id,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        evidence = {
            "outcome": "completed",
            "run_id": args.run_id,
            "source_sha": args.source_sha,
            "planned_row_id": args.planned_row_id,
            "fixture_id": args.fixture_id,
            "party_size": args.party_size,
            "lifecycle": args.lifecycle,
            "command": command,
            "working_directory": "tmp/combat_capture",
            "pythonpath": safety.expected_guarded_pythonpath(PROJECT_ROOT),
            "invocation_identity": {"status": "matched", "mismatches": []},
            "network_guard_active": True,
            "provider_environment_keys_blank": True,
            "proxy_values_blank": True,
            "real_project_config_loaded": False,
            "sandbox_config_loaded": True,
            "startup_guard_from_sitecustomize": True,
            "sandbox_config_origin_guard_active": True,
            "failure_code": None,
            "worker_shutdown": {
                "server_returned": True,
                "interrupted": True,
                "graceful_shutdown_requested": True,
                "request": {
                    "readiness_succeeded": True,
                    "exchange_succeeded": True,
                },
            },
            "teardown": {
                "server_stopped": True,
                "port_8360_free": True,
                "port_8370_free": True,
                "lock_released": True,
            },
            "calls": [{"stub": True}],
            "call_count": 1,
            "call_sites": [call_site],
            "driver_exchange": {
                "status": "completed",
                "turn_completed": True,
                "game_output_count": 1,
            },
        }
        evidence_path = (
            "tmp/router-rollout/live-gate-preflight/%s/preflight/rows/%s/"
            "profile-evidence.json" % (args.preflight_run_id, args.run_id)
        )
        return evidence, evidence_path, "b" * 64

    def _intended_identities(self) -> dict[str, dict[str, Any]]:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        identities: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_id = str(row["row_id"])
            plan = _resolve_row_plan(
                row_id,
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            row_run_id = "pf-%s-%s" % (RUN_ID, row_id)
            identities[row_id] = self._caller_declared_identity(
                plan,
                fixture_id=plan.fixture_id,
                lifecycle="startup",
                row_run_id=row_run_id,
            )
        return identities

    @staticmethod
    def _measured_lifecycle(
        call_site: dict[str, Any], *, source_sha: str = SOURCE_SHA
    ) -> dict[str, Any]:
        return {
            "status": "measured-under-stub",
            "source_sha": source_sha,
            "call_count": call_site["count"],
            "call_sites": [dict(call_site)],
        }

    @staticmethod
    def _checkpoint(
        *, row_id: str, fixture_id: str, party_size: int, arm: str, seed: int, sha: str
    ) -> dict[str, Any]:
        return {
            "checkpoint_root": "tmp/resume-checkpoints/%s/%s" % (row_id, fixture_id),
            "state_sha256": sha * 64,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": arm,
            "fixed_seed": seed,
        }

    def _fake_interfaces(
        self,
        sandbox_root: Path,
        *,
        prepared_rows: list[str],
        validated_rows: list[str],
        worker_rows: list[str],
        driver_sessions: list[row_runner.SocketScriptDriver],
        capture_sessions: list[_FakeCaptureSession],
        worker_launches: list[dict[str, Any]],
        identities: dict[str, dict[str, Any]],
        resolved_plans: list[controller.PreflightRowPlan],
        cleaned_rows: list[str] | None = None,
        observed_call_count: int = 1,
        observed_call_sites: list[dict[str, Any]] | None = None,
        use_guarded_adapter: bool = False,
        prepared_lifecycles: list[tuple[str, str, str]] | None = None,
        worker_lifecycles: list[tuple[str, str, str]] | None = None,
    ) -> tuple[PreflightInterfaces, Any]:
        from scripts import seed_combat_capture
        from scripts import combat_latency_fixtures

        party_names = {
            party_size: seed_combat_capture._party_names(party_size)
            for party_size in (1, 4)
        }
        module_payloads, expected_payloads = sandbox._load_profile_seed_inputs(
            PROJECT_ROOT
        )
        prepared_context: list[
            tuple[controller.PreflightRowPlan, controller.PreflightLifecycleInvocation]
        ] = []

        def prepare(
            plan: controller.PreflightRowPlan,
            invocation: controller.PreflightLifecycleInvocation,
            source_sha: str,
            preflight_run_id: str,
        ) -> dict[str, Any]:
            self.assertEqual(source_sha, SOURCE_SHA)
            self.assertEqual(preflight_run_id, RUN_ID)
            expected_identity = planned_worker_identity(
                plan,
                fixture_id=invocation.fixture_id,
                lifecycle=invocation.lifecycle,
                source_sha=source_sha,
                row_run_id=invocation.row_run_id,
                resume_checkpoint_sha256=(
                    invocation.resume_checkpoint.get("state_sha256")
                    if invocation.resume_checkpoint
                    else None
                ),
                preflight_run_id=preflight_run_id,
            )
            self.assertEqual(invocation.intended_identity, expected_identity)
            if invocation.fixture_id == plan.fixture_id and invocation.lifecycle == "startup":
                self.assertEqual(
                    invocation.intended_identity["command"],
                    identities[plan.row_id]["command"],
                )
            if prepared_lifecycles is not None:
                prepared_lifecycles.append(
                    (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                )
            self.assertFalse(plan.row_id.startswith("R"))
            prepared_context.append((plan, invocation))
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                invocation.fixture_id, plan.party_size, plan.row_id
            )
            area_id, _area, _location = sandbox._runtime_location(
                module_payloads, seed_plan["runtime_location_id"]
            )
            self.assertIn("areas/%s.json" % area_id, module_payloads)
            self.assertIn("map_%s.json" % area_id, module_payloads)
            source_map = module_payloads["location_id_map.json"]["runtime_location_ids"]
            self.assertEqual(
                source_map.get(seed_plan["source_location_id"]),
                seed_plan["runtime_location_id"],
            )
            expected_party = seed_combat_capture._party_names(plan.party_size)
            self.assertEqual(len(expected_party), plan.party_size)
            for member in expected_party:
                self.assertTrue(
                    combat_latency_fixtures.build_capture_character_payload(
                        member,
                        seed_combat_capture._party_initiative(member, plan.party_size),
                    )
                )
            if invocation.fixture_id == "combat_stage_tavern_zones":
                monster_path = sandbox._source_file(
                    PROJECT_ROOT,
                    "modules/Capture_Arena/monsters/goblin.json",
                    required=True,
                )
                self.assertIsNotNone(monster_path)
                monster = json.loads(monster_path.read_text(encoding="utf-8"))
                self.assertEqual(monster.get("name"), "Goblin")
            prepared_rows.append(plan.row_id)
            return {
                "status": "prepared",
                "sandbox_root": "tmp/combat_capture",
                "fixture_id": invocation.fixture_id,
                "party_size": plan.party_size,
                "planned_row_id": plan.row_id,
                "arm": plan.arm,
                "effective_seed": plan.fixed_seed,
            }

        def validate(
            runtime_root: Path,
            *,
            arm: str,
            fixture_id: str,
            party_size: int,
            resume: bool = False,
            resume_checkpoint_sha256: str | None = None,
            project_root: Path,
        ) -> launcher.ValidatedSandbox:
            del project_root
            plan, invocation = prepared_context[len(validated_rows)]
            self.assertEqual(resume, invocation.lifecycle == "resume")
            if resume:
                self.assertIsNotNone(resume_checkpoint_sha256)
            self.assertEqual(runtime_root, PROJECT_ROOT / "tmp" / "combat_capture")
            self.assertEqual(arm, plan.arm)
            self.assertEqual(fixture_id, invocation.fixture_id)
            self.assertEqual(party_size, plan.party_size)
            validated_rows.append(plan.row_id)
            metadata = {
                "fixture_id": invocation.fixture_id,
                "arm": plan.arm,
                "party": {
                    "size": plan.party_size,
                    "members": list(party_names[plan.party_size]),
                },
                "counterbalance": {
                    "row_id": plan.row_id,
                    "fixed_seed": plan.fixed_seed,
                    "row_type": "planned",
                },
                "mapping": {},
            }
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                invocation.fixture_id, plan.party_size, plan.row_id
            )
            area_id, _area, _location = sandbox._runtime_location(
                module_payloads, seed_plan["runtime_location_id"]
            )
            source_map = module_payloads["location_id_map.json"]["runtime_location_ids"]
            runtime_to_source = {
                runtime: source for source, runtime in source_map.items()
            }
            metadata["mapping"] = {
                "module": "mapping_pilot",
                "source_location_id": seed_plan["source_location_id"],
                "runtime_location_id": seed_plan["runtime_location_id"],
                "area_id": area_id,
                "id_map_file": "modules/mapping_pilot/location_id_map.json",
            }
            fixture_payloads = {
                selected: payload["source_truth"]
                for selected, payload in expected_payloads.items()
            }
            return launcher.ValidatedSandbox(
                root=sandbox_root,
                metadata=metadata,
                fixture_payloads=fixture_payloads,
                runtime_to_source=runtime_to_source,
            )

        def driver_factory(**kwargs: Any) -> row_runner.SocketScriptDriver:
            driver = row_runner.SocketScriptDriver(
                **kwargs,
                session_factory=lambda args: _FakeCaptureSession(args, capture_sessions),
            )
            driver_sessions.append(driver)
            return driver

        def supervise_row(
            plan: controller.PreflightRowPlan,
            seeded: dict[str, Any],
            invocation: controller.PreflightLifecycleInvocation,
            source_sha: str,
            preflight_run_id: str,
        ) -> dict[str, Any]:
            self.assertEqual(seeded["planned_row_id"], plan.row_id)
            self.assertEqual(seeded["fixture_id"], invocation.fixture_id)
            self.assertEqual(source_sha, SOURCE_SHA)
            self.assertEqual(preflight_run_id, RUN_ID)
            worker_rows.append(plan.row_id)
            if use_guarded_adapter:
                result = profile_runner.supervise_preflight_row(
                    fixture_id=invocation.fixture_id,
                    party_size=plan.party_size,
                    planned_row_id=plan.row_id,
                    arm=plan.arm,
                    source_sha=source_sha,
                    row_run_id=invocation.row_run_id,
                    lifecycle=invocation.lifecycle,
                    resume_checkpoint_sha256=(
                        invocation.resume_checkpoint.get("state_sha256")
                        if invocation.resume_checkpoint
                        else None
                    ),
                    preflight_run_id=preflight_run_id,
                )
                if worker_lifecycles is not None:
                    worker_lifecycles.append(
                        (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                    )
                return result
            worker = server.launch_worker(
                arm=plan.arm,
                fixture_id=invocation.fixture_id,
                party_size=plan.party_size,
                row_run_id=invocation.row_run_id,
                lifecycle_id=invocation.row_run_id
                + ("_s" if invocation.lifecycle == "startup" else "_r"),
                runtime_root="tmp/combat_capture",
                launcher=_FakeServerLauncher(plan.row_id, worker_launches),
            )
            self.assertEqual(worker.row_id, plan.row_id)
            if worker_lifecycles is not None:
                worker_lifecycles.append(
                    (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                )
            exchange = profile_runner._drive_profile_exchange(
                party_size=plan.party_size,
                runtime_root=PROJECT_ROOT / "tmp" / "combat_capture",
                transcript_path=(
                    PROJECT_ROOT
                    / "tmp"
                    / "preflight-integration"
                    / invocation.row_run_id
                    / "driver.txt"
                ),
                first_turn=plan.first_turn,
                driver_factory=driver_factory,
            )
            call_sites = observed_call_sites or [
                {
                    "source_file": "scripts/example_router_call.py",
                    "source_line": 1,
                    "source_file_sha256": "c" * 64,
                    "count": observed_call_count,
                }
            ]
            return {
                "evidence": {
                    "outcome": "completed",
                    "run_id": invocation.row_run_id,
                    "source_sha": source_sha,
                    "planned_row_id": plan.row_id,
                    "fixture_id": invocation.fixture_id,
                    "party_size": plan.party_size,
                    "lifecycle": invocation.lifecycle,
                    "command": invocation.intended_identity["command"],
                    "working_directory": "tmp/combat_capture",
                    "pythonpath": invocation.intended_identity["pythonpath"],
                    "invocation_identity": {"status": "matched", "mismatches": []},
                    "network_guard_active": True,
                    "provider_environment_keys_blank": True,
                    "proxy_values_blank": True,
                    "real_project_config_loaded": False,
                    "sandbox_config_loaded": True,
                    "startup_guard_from_sitecustomize": True,
                    "sandbox_config_origin_guard_active": True,
                    "failure_code": None,
                    "worker_shutdown": {
                        "server_returned": True,
                        "interrupted": True,
                        "graceful_shutdown_requested": True,
                        "request": {
                            "readiness_succeeded": True,
                            "exchange_succeeded": True,
                        },
                    },
                    "teardown": {
                        "server_stopped": True,
                        "port_8360_free": True,
                        "port_8370_free": True,
                        "lock_released": True,
                    },
                    "calls": [{"stub": True} for _ in range(observed_call_count)],
                    "call_count": observed_call_count,
                    "call_sites": call_sites,
                    "driver_exchange": exchange,
                },
                "evidence_path": (
                    "tmp/router-rollout/live-gate-preflight/%s/preflight/rows/%s/"
                    "profile-evidence.json" % (RUN_ID, invocation.row_run_id)
                ),
                "evidence_sha256": "b" * 64,
            }

        def cleanup_sandbox(
            plan: controller.PreflightRowPlan, _seeded: dict[str, Any]
        ) -> bool:
            if cleaned_rows is not None:
                cleaned_rows.append(plan.row_id)
            return True

        def counters() -> dict[str, int]:
            return {
                "upstream_provider_requests": 0,
                "provider_budget_used": 0,
                "live_attempts_used": 0,
                "reserve_activations": 0,
            }

        interfaces = PreflightInterfaces(
            prepare_sandbox=prepare,
            supervise_row=supervise_row,
            cleanup_sandbox=cleanup_sandbox,
            safety_counters=counters,
        )
        return interfaces, validate

    def _run_with_profiles(
        self,
        profile_map: dict[tuple[str, int], Any],
        coverage: dict[str, Any],
        *,
        observed_call_count: int = 1,
        observed_call_sites: list[dict[str, Any]] | None = None,
        resume_checkpoints: dict[str, dict[str, dict[str, Any]]] | None = None,
        intended_lifecycle_identities: dict[
            str, dict[str, dict[str, dict[str, Any]]]
        ]
        | None = None,
        use_guarded_adapter: bool = False,
    ) -> tuple[dict[str, Any], dict[str, list[Any]]]:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            )
            for row in rows
        ]
        observed: dict[str, list[Any]] = {
            "prepared": [],
            "validated": [],
            "workers": [],
            "cleaned": [],
            "drivers": [],
            "sessions": [],
            "launches": [],
            "prepared_lifecycles": [],
            "worker_lifecycles": [],
        }
        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-profiles-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, validate_sandbox = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=observed["prepared"],
                validated_rows=observed["validated"],
                worker_rows=observed["workers"],
                driver_sessions=observed["drivers"],
                capture_sessions=observed["sessions"],
                worker_launches=observed["launches"],
                identities=identities,
                resolved_plans=resolved_plans,
                cleaned_rows=observed["cleaned"],
                observed_call_count=observed_call_count,
                observed_call_sites=observed_call_sites,
                use_guarded_adapter=use_guarded_adapter,
                prepared_lifecycles=observed["prepared_lifecycles"],
                worker_lifecycles=observed["worker_lifecycles"],
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=Path(temp_root)),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox),
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
                mock.patch.object(
                    controller, "_load_profiles", return_value=(profile_map, coverage)
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    intended_lifecycle_identities=intended_lifecycle_identities,
                    interfaces=interfaces,
                    resume_checkpoints=resume_checkpoints,
                )
        return report, observed

    def test_all_26_planned_rows_cross_existing_sp3_interfaces(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            for row in rows
        ]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        cleaned_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-integration-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox_root = Path(temp_root)
            interfaces, validate_sandbox = self._fake_interfaces(
                sandbox_root,
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=resolved_plans,
                cleaned_rows=cleaned_rows,
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=sandbox_root),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox),
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["transport_status"], "completed")
        self.assertEqual(report["lifecycle_coverage_status"], "unverified")
        self.assertEqual(report["fully_covered_row_ids"], [])
        self.assertTrue(report["preflight_only"])
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["live_gate_pass"])
        self.assertFalse(report["pilot_evidence_written"])
        self.assertEqual(report["planned_row_count"], 26)
        self.assertEqual(report["attempted_row_ids"], report["planned_row_ids"])
        self.assertEqual(len(report["row_results"]), 26)
        self.assertEqual(report["replacement_only_row_ids"], ["R01", "R02", "R03", "R04"])
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertEqual(report["unverified_profile_row_ids"], report["planned_row_ids"])
        self.assertEqual(prepared_rows, report["planned_row_ids"])
        self.assertEqual(validated_rows, report["planned_row_ids"])
        self.assertEqual(worker_rows, report["planned_row_ids"])
        self.assertEqual(cleaned_rows, report["planned_row_ids"])
        self.assertEqual(len(driver_sessions), 26)
        self.assertTrue(
            all(isinstance(driver, row_runner.SocketScriptDriver) for driver in driver_sessions)
        )
        self.assertTrue(all(driver._closed for driver in driver_sessions))
        self.assertEqual(len(capture_sessions), 26)
        self.assertTrue(all(session.disconnected for session in capture_sessions))
        self.assertTrue(all(session.transcript_closed for session in capture_sessions))
        self.assertTrue(
            all(
                session.sent == [
                    (plan.first_turn["step_id"], plan.first_turn["utterance"], plan.first_turn["character"])
                ]
                and session.game_outputs[0]["payload"]["content"]
                == "provider-free stub response"
                for session, plan in zip(capture_sessions, resolved_plans)
            )
        )
        self.assertEqual([launch["row_id"] for launch in worker_launches], report["planned_row_ids"])

        disconnected_rows = {
            "E04", "E05", "E06", "E13", "E14", "E15", "E16", "E17", "E18"
        }
        observed_disconnected = {
            row["row_id"]
            for row in report["row_results"]
            if row["fixture_ids"] == ["landscape_village", "transition_tower_approach"]
        }
        self.assertEqual(observed_disconnected, disconnected_rows)
        self.assertEqual(
            {row["party_size"] for row in report["row_results"]}, {1, 4}
        )
        self.assertTrue(
            all(row["first_exchange"]["status"] == "completed" for row in report["row_results"])
        )
        self.assertTrue(
            all(
                row["worker_teardown"]["server_stopped"]
                and row["worker_teardown"]["port_8360_free"]
                and row["worker_teardown"]["port_8370_free"]
                and row["worker_teardown"]["shared_live_window_lock_released"]
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(row["lifecycle_profile_status"] == "unverified" for row in report["row_results"])
        )
        self.assertTrue(
            all(row["startup_profile_check"]["status"] == "unverified" for row in report["row_results"])
        )
        self.assertTrue(
            all(
                row["lifecycle_profile_checks"][row["fixture_id"]]["resume"][
                    "checkpoint_status"
                ]
                == "MISSING"
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(
                row["status"] == "transport_completed_unverified"
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(
                all(
                    profile["startup_status"] == "MISSING"
                    and profile["resume_status"] == "MISSING"
                    for profile in row["lifecycle_profiles"]
                )
                for row in report["row_results"]
            )
        )
        self.assertEqual(
            report["provider_free"],
            {
                "upstream_provider_requests_delta": 0,
                "provider_budget_used_delta": 0,
                "live_attempts_used_delta": 0,
                "reserve_activations_delta": 0,
                "router_stub_calls": 26,
            },
        )

    def test_invocation_mismatch_blocks_before_seeding_or_worker_launch(self) -> None:
        identities = self._intended_identities()
        identities["E01"] = dict(identities["E01"])
        identities["E01"]["command"] = [*identities["E01"]["command"], "--wrong-row"]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-identity-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox_root = Path(temp_root)
            interfaces, validate_sandbox = self._fake_interfaces(
                sandbox_root,
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=[],
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=sandbox_root),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox) as validate,
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(report["row_results"][0]["failure_code"], "invocation_identity_mismatch")
        self.assertEqual(report["row_results"][0]["invocation_identity"]["status"], "blocked")
        self.assertEqual(prepared_rows, [])
        self.assertEqual(validated_rows, [])
        self.assertEqual(worker_rows, [])
        self.assertEqual(driver_sessions, [])
        self.assertEqual(worker_launches, [])
        validate.assert_not_called()
        self.assertFalse(report["booking_eligible"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_missing_lifecycle_profile_blocks_before_sandbox_seed(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        profile_map.pop(("interior_tavern", 1))
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-profile-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, _validate = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=[],
            )
            with mock.patch.object(
                controller,
                "_load_profiles",
                return_value=(profile_map, coverage),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "fixture-party_lifecycle_profile_is_missing",
        )
        self.assertEqual(prepared_rows, [])
        self.assertEqual(validated_rows, [])
        self.assertEqual(worker_rows, [])
        self.assertEqual(worker_launches, [])
        self.assertEqual(driver_sessions, [])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_missing_fixture_payload_is_reported_and_never_covered(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            for row in rows
        ]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-fixture-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, validate_sandbox = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=resolved_plans,
            )

            def missing_fixture(*args: Any, **kwargs: Any) -> launcher.ValidatedSandbox:
                validated = validate_sandbox(*args, **kwargs)
                plan = next(
                    item for item in resolved_plans if item.row_id == validated_rows[-1]
                )
                payloads = dict(validated.fixture_payloads)
                payloads.pop(plan.fixture_ids[0], None)
                return launcher.ValidatedSandbox(
                    root=validated.root,
                    metadata=validated.metadata,
                    fixture_payloads=payloads,
                    runtime_to_source=validated.runtime_to_source,
                )

            with mock.patch.object(
                launcher, "validate_sandbox", side_effect=missing_fixture
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(report["row_results"][0]["failure_code"], "fixture_payload_missing")
        self.assertEqual(
            report["row_results"][0]["unresolved_reference"],
            "mapping_pilot/expected/interior_tavern.json",
        )
        self.assertEqual(prepared_rows, ["E01"])
        self.assertEqual(validated_rows, ["E01"])
        self.assertEqual(worker_rows, [])
        self.assertEqual(worker_launches, [])
        self.assertEqual(driver_sessions, [])
        self.assertFalse(report["booking_eligible"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_measured_startup_profile_matches_calls_but_resume_stays_unverified(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 1,
            "call_sites": [call_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            observed_call_sites=[call_site],
        )

        first_result = report["row_results"][0]
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(first_result["startup_profile_check"]["status"], "matched")
        self.assertTrue(first_result["startup_profile_check"]["call_sites_matched"])
        self.assertEqual(first_result["lifecycle_profile_status"], "unverified")
        self.assertEqual(first_result["status"], "transport_completed_unverified")
        self.assertEqual(
            first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"][
                "checkpoint_status"
            ],
            "MISSING",
        )
        self.assertEqual(observed["workers"], report["planned_row_ids"])
        self.assertEqual(observed["cleaned"], report["planned_row_ids"])

    def test_measured_startup_call_count_mismatch_blocks_and_cleans_sandbox(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        expected_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 2,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 2,
            "call_sites": [expected_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_call_count_mismatch",
        )
        self.assertEqual(observed["cleaned"], ["E01"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_measured_startup_call_site_mismatch_blocks(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        expected_site = {
            "source_file": "scripts/different_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 1,
            "call_sites": [expected_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_call_sites_mismatch",
        )
        self.assertEqual(observed["cleaned"], ["E01"])

    def test_measured_resume_without_row_checkpoint_stays_missing_and_unverified(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, _observed = self._run_with_profiles(profile_map, coverage)

        first_result = report["row_results"][0]
        resume_check = first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"]
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(first_result["transport_status"], "completed")
        self.assertEqual(first_result["status"], "transport_completed_unverified")
        self.assertEqual(resume_check["profile_status"], "MISSING")
        self.assertEqual(resume_check["checkpoint_status"], "MISSING")
        self.assertEqual(resume_check["reason"], "row_bound_resume_checkpoint_missing")
        self.assertFalse(
            any(
                item["lifecycle"] == "resume"
                for item in first_result["lifecycle_results"]
            )
        )

    def test_supplied_row_checkpoint_runs_guarded_resume_and_matches_profile(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = self._measured_lifecycle(call_site)
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(first.fixture_id, first.party_size)] = profile
        checkpoint = self._checkpoint(
            row_id="E01",
            fixture_id="interior_tavern",
            party_size=1,
            arm="A",
            seed=5101,
            sha="d",
        )
        resume_args: list[Any] = []

        def characterize(args: Any) -> tuple[dict[str, Any], str, str]:
            if args.lifecycle == "resume":
                resume_args.append(args)
            return self._fake_characterization(args)

        with mock.patch.object(profile_runner, "_characterize", side_effect=characterize):
            report, observed = self._run_with_profiles(
                profile_map,
                coverage,
                resume_checkpoints={"E01": {"interior_tavern": checkpoint}},
                intended_lifecycle_identities={
                    "E01": {
                        "interior_tavern": {
                            "resume": self._lifecycle_identity_declaration(
                                first,
                                fixture_id="interior_tavern",
                                lifecycle="resume",
                                resume_checkpoint_sha256="d" * 64,
                            )
                        }
                    }
                },
                use_guarded_adapter=True,
            )

        first_result = report["row_results"][0]
        resume_check = first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"]
        self.assertEqual(len(resume_args), 1)
        self.assertEqual(resume_args[0].lifecycle, "resume")
        self.assertEqual(resume_args[0].planned_row_id, "E01")
        self.assertEqual(resume_args[0].resume_checkpoint_sha256, "d" * 64)
        self.assertEqual(resume_check["status"], "matched")
        self.assertEqual(resume_check["checkpoint_status"], "matched_moved_checkpoint")
        self.assertEqual(resume_check["checkpoint_sha256"], "d" * 64)
        self.assertEqual(first_result["status"], "completed")
        self.assertEqual(first_result["lifecycle_coverage_status"], "matched")
        self.assertIn("E01", observed["workers"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_stale_resume_profile_source_blocks_resume(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["resume"] = self._measured_lifecycle(
            call_site, source_sha="f" * 40
        )
        profile_map[(first.fixture_id, first.party_size)] = profile
        checkpoint = self._checkpoint(
            row_id="E01",
            fixture_id="interior_tavern",
            party_size=1,
            arm="A",
            seed=5101,
            sha="d",
        )

        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            resume_checkpoints={"E01": {"interior_tavern": checkpoint}},
        )

        first_result = report["row_results"][0]
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(first_result["failure_code"], "resume_profile_source_mismatch")
        self.assertFalse(
            any(
                item["lifecycle"] == "resume"
                for item in first_result["lifecycle_results"]
            )
        )
        self.assertEqual(observed["cleaned"], ["E01"])

    def test_multi_fixture_row_runs_each_measured_fixture_lifecycle_independently(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        fixtures = ("landscape_village", "transition_tower_approach")
        for fixture_id in fixtures:
            profile = dict(profile_map[(fixture_id, 1)])
            profile["startup"] = self._measured_lifecycle(call_site)
            profile["resume"] = self._measured_lifecycle(call_site)
            profile_map[(fixture_id, 1)] = profile
        checkpoints = {
            "E04": {
                "landscape_village": self._checkpoint(
                    row_id="E04",
                    fixture_id="landscape_village",
                    party_size=1,
                    arm="D",
                    seed=5102,
                    sha="d",
                ),
                "transition_tower_approach": self._checkpoint(
                    row_id="E04",
                    fixture_id="transition_tower_approach",
                    party_size=1,
                    arm="D",
                    seed=5102,
                    sha="e",
                ),
            }
        }

        intended_lifecycle_identities: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            row_plan = _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            )
            for fixture_id in row_plan.fixture_ids:
                if fixture_id in fixtures and fixture_id != row_plan.fixture_id:
                    intended_lifecycle_identities.setdefault(row_plan.row_id, {}).setdefault(
                        fixture_id, {}
                    )["startup"] = self._lifecycle_identity_declaration(
                        row_plan,
                        fixture_id=fixture_id,
                        lifecycle="startup",
                    )
        e04_plan = _resolve_row_plan(
            "E04", prereg_root=None, expected_row=rows[3], profiles=profile_map
        )
        for fixture_id, checkpoint_sha in (
            ("landscape_village", "d" * 64),
            ("transition_tower_approach", "e" * 64),
        ):
            intended_lifecycle_identities.setdefault("E04", {}).setdefault(
                fixture_id, {}
            )["resume"] = self._lifecycle_identity_declaration(
                e04_plan,
                fixture_id=fixture_id,
                lifecycle="resume",
                resume_checkpoint_sha256=checkpoint_sha,
            )
        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            resume_checkpoints=checkpoints,
            intended_lifecycle_identities=intended_lifecycle_identities,
        )

        e04 = next(row for row in report["row_results"] if row["row_id"] == "E04")
        lifecycle_pairs = {
            (item["fixture_id"], item["lifecycle"])
            for item in e04["lifecycle_results"]
        }
        self.assertEqual(
            lifecycle_pairs,
            {
                ("landscape_village", "startup"),
                ("landscape_village", "resume"),
                ("transition_tower_approach", "startup"),
                ("transition_tower_approach", "resume"),
            },
        )
        self.assertEqual(e04["lifecycle_coverage_status"], "matched")
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertFalse(any(row_id.startswith("R") for row_id in observed["workers"]))
        self.assertIn(1, {row["party_size"] for row in report["row_results"]})
        self.assertIn(
            4,
            {row["party_size"] for row in report["row_results"]},
            [(row["row_id"], row.get("failure_code")) for row in report["row_results"]],
        )

    def test_secondary_and_resume_intent_mismatches_block_before_seed_or_launch(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        e04 = rows[3]

        for lifecycle in ("startup", "resume"):
            for field in ("command", "working_directory", "pythonpath"):
                with self.subTest(lifecycle=lifecycle, field=field):
                    profile_map, coverage = _load_profiles(
                        [row["row_id"] for row in rows]
                    )
                    plan = _resolve_row_plan(
                        "E04",
                        prereg_root=None,
                        expected_row=e04,
                        profiles=profile_map,
                    )
                    secondary_fixture = next(
                        fixture_id
                        for fixture_id in plan.fixture_ids
                        if fixture_id != plan.fixture_id
                    )
                    profile = dict(profile_map[(secondary_fixture, plan.party_size)])
                    profile[lifecycle] = self._measured_lifecycle(call_site)
                    profile_map[(secondary_fixture, plan.party_size)] = profile

                    checkpoints = None
                    checkpoint_sha256 = None
                    if lifecycle == "resume":
                        checkpoint = self._checkpoint(
                            row_id=plan.row_id,
                            fixture_id=secondary_fixture,
                            party_size=plan.party_size,
                            arm=plan.arm,
                            seed=plan.fixed_seed,
                            sha="d",
                        )
                        checkpoint_sha256 = checkpoint["state_sha256"]
                        checkpoints = {
                            plan.row_id: {secondary_fixture: checkpoint}
                        }

                    declaration = self._lifecycle_identity_declaration(
                        plan,
                        fixture_id=secondary_fixture,
                        lifecycle=lifecycle,
                        resume_checkpoint_sha256=checkpoint_sha256,
                    )
                    mutated = dict(declaration)
                    if field == "command":
                        mutated["command"] = [*declaration["command"], "--wrong-intent"]
                    elif field == "working_directory":
                        mutated["working_directory"] = str(
                            PROJECT_ROOT / "tmp" / "wrong-intended-cwd"
                        )
                    else:
                        mutated["pythonpath"] = declaration["pythonpath"] + os.pathsep + str(
                            PROJECT_ROOT / "tmp" / "wrong-intended-pythonpath"
                        )

                    report, observed = self._run_with_profiles(
                        profile_map,
                        coverage,
                        resume_checkpoints=checkpoints,
                        intended_lifecycle_identities={
                            plan.row_id: {
                                secondary_fixture: {lifecycle: mutated}
                            }
                        },
                    )

                    row_result = next(
                        result
                        for result in report["row_results"]
                        if result["row_id"] == plan.row_id
                    )
                    target = (plan.row_id, secondary_fixture, lifecycle)
                    self.assertEqual(
                        row_result["failure_code"], "invocation_identity_mismatch"
                    )
                    self.assertEqual(
                        row_result["lifecycle_invocation_identity_checks"][0]["check"][
                            "mismatches"
                        ][0]["field"],
                        field,
                    )
                    self.assertNotIn(target, observed["prepared_lifecycles"])
                    self.assertNotIn(target, observed["worker_lifecycles"])

    def test_missing_secondary_or_resume_intent_fails_closed_before_seed(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        e04 = rows[3]

        for lifecycle in ("startup", "resume"):
            with self.subTest(lifecycle=lifecycle):
                profile_map, coverage = _load_profiles(
                    [row["row_id"] for row in rows]
                )
                plan = _resolve_row_plan(
                    "E04",
                    prereg_root=None,
                    expected_row=e04,
                    profiles=profile_map,
                )
                secondary_fixture = next(
                    fixture_id
                    for fixture_id in plan.fixture_ids
                    if fixture_id != plan.fixture_id
                )
                profile = dict(profile_map[(secondary_fixture, plan.party_size)])
                profile[lifecycle] = self._measured_lifecycle(call_site)
                profile_map[(secondary_fixture, plan.party_size)] = profile
                checkpoints = None
                if lifecycle == "resume":
                    checkpoints = {
                        plan.row_id: {
                            secondary_fixture: self._checkpoint(
                                row_id=plan.row_id,
                                fixture_id=secondary_fixture,
                                party_size=plan.party_size,
                                arm=plan.arm,
                                seed=plan.fixed_seed,
                                sha="d",
                            )
                        }
                    }

                report, observed = self._run_with_profiles(
                    profile_map,
                    coverage,
                    resume_checkpoints=checkpoints,
                )

                row_result = next(
                    result
                    for result in report["row_results"]
                    if result["row_id"] == plan.row_id
                )
                target = (plan.row_id, secondary_fixture, lifecycle)
                self.assertEqual(
                    row_result["failure_code"],
                    "intended_lifecycle_identity_missing",
                )
                self.assertNotIn(target, observed["prepared_lifecycles"])
                self.assertNotIn(target, observed["worker_lifecycles"])

    def test_four_pc_resume_profile_runs_on_its_declared_row(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        four_pc_row = next(
            row
            for row in rows
            if _resolve_row_plan(
                row["row_id"],
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            ).party_size
            == 4
        )
        plan = _resolve_row_plan(
            four_pc_row["row_id"],
            prereg_root=None,
            expected_row=four_pc_row,
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(plan.fixture_id, 4)])
        profile["startup"] = self._measured_lifecycle(call_site)
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(plan.fixture_id, 4)] = profile
        checkpoint = self._checkpoint(
            row_id=plan.row_id,
            fixture_id=plan.fixture_id,
            party_size=4,
            arm=plan.arm,
            seed=plan.fixed_seed,
            sha="d",
        )
        resume_args: list[Any] = []

        def characterize(args: Any) -> tuple[dict[str, Any], str, str]:
            if args.lifecycle == "resume":
                resume_args.append(args)
            return self._fake_characterization(args)

        with mock.patch.object(profile_runner, "_characterize", side_effect=characterize):
            report, _observed = self._run_with_profiles(
                profile_map,
                coverage,
                resume_checkpoints={plan.row_id: {plan.fixture_id: checkpoint}},
                intended_lifecycle_identities={
                    plan.row_id: {
                        plan.fixture_id: {
                            "resume": self._lifecycle_identity_declaration(
                                plan,
                                fixture_id=plan.fixture_id,
                                lifecycle="resume",
                                resume_checkpoint_sha256=checkpoint["state_sha256"],
                            )
                        }
                    }
                },
                use_guarded_adapter=True,
            )

        row_result = next(
            result for result in report["row_results"] if result["row_id"] == plan.row_id
        )
        resume_result = next(
            result
            for result in row_result["lifecycle_results"]
            if result["lifecycle"] == "resume"
        )
        self.assertEqual(plan.party_size, 4)
        self.assertEqual(resume_args[0].party_size, 4)
        self.assertEqual(resume_args[0].planned_row_id, plan.row_id)
        self.assertEqual(resume_result["profile_check"]["status"], "matched")
        self.assertEqual(resume_result["profile_check"]["checkpoint_status"], "matched_moved_checkpoint")

    def test_supervised_adapter_uses_separate_non_characterization_scope(self) -> None:
        args_seen: list[Any] = []
        evidence = {"outcome": "completed"}
        with mock.patch.object(
            profile_runner,
            "_characterize",
            side_effect=lambda args: (args_seen.append(args) or evidence, "tmp/evidence", "d" * 64),
        ):
            result = profile_runner.supervise_preflight_row(
                fixture_id="interior_tavern",
                party_size=1,
                planned_row_id="E01",
                arm="A",
                source_sha=SOURCE_SHA,
                row_run_id="pf-row-integration-test-E01",
                preflight_run_id=RUN_ID,
                lifecycle="resume",
                resume_checkpoint_sha256="e" * 64,
            )

        self.assertIs(result["evidence"], evidence)
        self.assertEqual(args_seen[0].preflight_run_id, RUN_ID)
        self.assertEqual(args_seen[0].planned_row_id, "E01")
        self.assertEqual(args_seen[0].lifecycle, "resume")
        self.assertEqual(args_seen[0].resume_checkpoint_sha256, "e" * 64)
        with mock.patch.object(profile_runner, "_claim_characterization_attempt") as claim:
            claimed = profile_runner._claim_characterization_attempt_if_needed(
                args_seen[0],
                evidence_root=Path("tmp/unused"),
                run_directory=Path("tmp/unused/run"),
                attempt_record={},
            )
        self.assertFalse(claimed)
        claim.assert_not_called()

    def test_supervised_interfaces_bind_seed_worker_and_cleanup_apis(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        plan = _resolve_row_plan(
            "E01", prereg_root=None, expected_row=rows[0], profiles=profiles
        )
        row_run_id = "pf-%s-%s" % (RUN_ID, plan.row_id)
        identity = self._caller_declared_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id=row_run_id,
        )
        invocation = controller.PreflightLifecycleInvocation(
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id=row_run_id,
            intended_identity=identity,
        )
        counters = lambda: {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
        }
        interfaces = controller.supervised_preflight_interfaces(
            run_id=RUN_ID,
            safety_counters=counters,
        )
        seeded = {"status": "prepared", "fixture_id": plan.fixture_id}
        supervised = {"evidence": {"outcome": "completed"}}
        with (
            mock.patch.object(
                sandbox, "prepare_profile_sandbox", return_value=seeded
            ) as prepare,
            mock.patch.object(
                profile_runner, "supervise_preflight_row", return_value=supervised
            ) as supervise,
            mock.patch.object(
                sandbox, "remove_prepared_sandbox", return_value=True
            ) as cleanup,
        ):
            self.assertIs(
                interfaces.prepare_sandbox(
                    plan, invocation, SOURCE_SHA, RUN_ID
                ),
                seeded,
            )
            self.assertIs(
                interfaces.supervise_row(
                    plan, seeded, invocation, SOURCE_SHA, RUN_ID
                ),
                supervised,
            )
            self.assertTrue(interfaces.cleanup_sandbox(plan, seeded))

        self.assertEqual(prepare.call_args.kwargs["preflight_run_id"], RUN_ID)
        self.assertEqual(supervise.call_args.kwargs["preflight_run_id"], RUN_ID)
        self.assertEqual(cleanup.call_args.args[0]["row_id"], plan.row_id)

        multi_fixture_plan = _resolve_row_plan(
            "E04", prereg_root=None, expected_row=rows[3], profiles=profiles
        )
        self.assertGreater(len(multi_fixture_plan.fixture_ids), 1)
        later_fixture = multi_fixture_plan.fixture_ids[1]
        with mock.patch.object(
            sandbox, "remove_prepared_sandbox", return_value=True
        ) as cleanup:
            self.assertTrue(
                interfaces.cleanup_sandbox(
                    multi_fixture_plan,
                    {"status": "prepared", "fixture_id": later_fixture},
                )
            )
        self.assertEqual(cleanup.call_args.args[0]["fixture_id"], later_fixture)

    def test_resume_checkpoint_install_copies_only_row_bound_moved_state(self) -> None:
        from scripts.live_gate_preflight_sandbox import _install_row_resume_checkpoint

        with tempfile.TemporaryDirectory(
            prefix="preflight-resume-checkpoint-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project_root = Path(temp_root)
            checkpoint_root = project_root / "tmp" / "checkpoint"
            active_root = project_root / "tmp" / "active"
            active_root.mkdir(parents=True)
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                "interior_tavern", 1, "E01"
            )
            module_payloads, expected_payloads = sandbox._load_profile_seed_inputs(
                PROJECT_ROOT
            )
            written = sandbox._write_fixture_module(
                active_root, seed_plan, module_payloads, expected_payloads
            )
            metadata = sandbox._write_seed_state(
                PROJECT_ROOT,
                active_root,
                seed_plan,
                written["module_payloads"],
                written["mapping"],
            )
            shutil.copytree(active_root / "characters", checkpoint_root / "characters")
            shutil.copytree(
                active_root / "modules" / "Mapping_Pilot_Arena" / "areas",
                checkpoint_root / "modules" / "Mapping_Pilot_Arena" / "areas",
            )
            shutil.copy2(active_root / "party_tracker.json", checkpoint_root / "party_tracker.json")
            (checkpoint_root / "mapping_pilot").mkdir()
            shutil.copy2(
                active_root / "mapping_pilot" / "seed_metadata.json",
                checkpoint_root / "mapping_pilot" / "seed_metadata.json",
            )
            fixture = expected_payloads["interior_tavern"]["source_truth"]
            start_source = seed_plan["source_location_id"]
            start_location = next(
                item for item in fixture["locations"] if item["location_id"] == start_source
            )
            open_exits = [
                item
                for item in start_location.get("exits", [])
                if item.get("state") == "open"
                and item.get("destination_knowledge") == "known"
            ]
            self.assertEqual(len(open_exits), 1)
            destination_source = open_exits[0]["known_destination_location_id"]
            runtime_ids = module_payloads["location_id_map.json"]["runtime_location_ids"]
            destination_runtime = runtime_ids[destination_source]
            destination_area, destination_area_payload, destination_location = (
                sandbox._runtime_location(module_payloads, destination_runtime)
            )
            moved_tracker_path = checkpoint_root / "party_tracker.json"
            moved_tracker = json.loads(moved_tracker_path.read_text(encoding="utf-8"))
            moved_world = moved_tracker["worldConditions"]
            moved_world["currentLocationId"] = destination_runtime
            moved_world["currentLocation"] = destination_location.get("name")
            moved_world["currentAreaId"] = destination_area
            moved_world["currentArea"] = destination_area_payload.get("areaName")
            moved_tracker_path.write_text(
                json.dumps(moved_tracker, sort_keys=True), encoding="ascii"
            )
            checkpoint_sha = launcher._canonical_state_sha256(checkpoint_root)
            root_owner = project_root
            checkpoint = {
                "checkpoint_root": "tmp/checkpoint",
                "state_sha256": checkpoint_sha,
                "row_id": "E01",
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "arm": seed_plan["arm"],
                "fixed_seed": seed_plan["effective_seed"],
            }
            plan = {
                "counterbalance": seed_plan["counterbalance"],
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "arm": seed_plan["arm"],
                "effective_seed": seed_plan["effective_seed"],
            }

            def validate_resume(
                root: Path,
                *,
                arm: str,
                fixture_id: str,
                party_size: int,
                resume: bool,
                resume_checkpoint_sha256: str | None,
                project_root: Path,
            ) -> object:
                self.assertEqual(root, active_root)
                self.assertEqual(project_root, root_owner)
                self.assertEqual((fixture_id, party_size), ("interior_tavern", 1))
                self.assertEqual(arm, seed_plan["arm"])
                self.assertTrue(resume)
                self.assertEqual(resume_checkpoint_sha256, checkpoint_sha)
                self.assertEqual(launcher._canonical_state_sha256(root), checkpoint_sha)
                current_metadata = json.loads(
                    (root / "mapping_pilot" / "seed_metadata.json").read_text()
                )
                moved_tracker = json.loads((root / "party_tracker.json").read_text())
                world = moved_tracker["worldConditions"]
                id_map = json.loads(
                    (
                        root
                        / "modules"
                        / "Mapping_Pilot_Arena"
                        / "location_id_map.json"
                    ).read_text()
                )
                runtime_to_source = {
                    runtime_id: source_id
                    for source_id, runtime_id in id_map["runtime_location_ids"].items()
                }
                launcher._validate_resume_checkpoint(
                    root,
                    fixture_id="interior_tavern",
                    mapping=current_metadata["mapping"],
                    tracker=moved_tracker,
                    world=world,
                    runtime_to_source=runtime_to_source,
                    resume_checkpoint_sha256=checkpoint_sha,
                )
                return object()

            with mock.patch.object(launcher, "validate_sandbox", side_effect=validate_resume):
                _install_row_resume_checkpoint(
                    project_root,
                    active_root,
                    plan,
                    checkpoint,
                    expected_sha256=checkpoint_sha,
                )

    def test_row_guard_journal_is_scoped_to_preflight_row_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-journal-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = (
                Path(temp_root)
                / RUN_ID
                / "preflight"
                / "rows"
                / "pf-row-integration-test-E01"
            )
            run_directory.mkdir(parents=True)
            journal = run_directory / "guard-events.jsonl"
            with (
                mock.patch.object(safety, "PROJECT_ROOT", PROJECT_ROOT),
                mock.patch.object(
                    safety,
                    "ROW_PREFLIGHT_GUARD_ROOT",
                    Path(temp_root).relative_to(PROJECT_ROOT),
                ),
            ):
                self.assertEqual(
                    safety._validate_guard_event_path(
                        journal, "pf-row-integration-test-E01"
                    ),
                    journal,
                )
                with self.assertRaisesRegex(
                    safety.SafetyConfigurationError,
                    "guard-event path identity is invalid",
                ):
                    safety._validate_guard_event_path(journal, "different-row")


if __name__ == "__main__":
    unittest.main()
