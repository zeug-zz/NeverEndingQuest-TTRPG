# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for profile coverage, provenance, stubbing, and safety."""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import importlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import types
import uuid
import unittest
from contextlib import ExitStack, nullcontext, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

from jsonschema import Draft202012Validator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mapping_pilot.fixtures import (
    LOCATION_ID_MAP,
    build_fixture_payloads,
    load_verified_fixtures,
)
from scripts.live_gate_preflight_profiles import (
    FIXTURE_IDS,
    PROFILE_PATH,
    PROFILE_SET_ID,
    PROJECT_ROOT,
    ProfileValidationError,
    copy_profile_document,
    load_profile_coverage,
    validate_profile_document,
)
from scripts.live_gate_preflight_safety import (
    ENABLE_GUARD_ENV,
    CANARY_REPORT_ENV,
    CONNECT_CANARY_ENV,
    EXPECTED_PREFIX_ENV,
    EXPECTED_PYTHON_ENV,
    GUARD_EVENT_ROOT,
    GUARD_DIRECTORY,
    PROCESS_ROLES,
    PROCESS_ROLE_ENV,
    REQUIRE_STARTUP_GUARD_ENV,
    SANDBOX_PROVIDER_KEY_PLACEHOLDER,
    STARTUP_GUARD_ENV,
    SUBPROCESS_CANARY_ENV,
    NetworkGuardError,
    SafetyConfigurationError,
    build_guarded_environment,
    build_guarded_sandbox_environment,
    current_invocation_command,
    expected_guarded_pythonpath,
    require_startup_guard_active,
    validate_guard_event_records,
    validate_sandbox_config_location,
    _startup_canary_environment_digest,
    _startup_environment_digest,
    _validate_canary_launch,
)
from scripts.live_gate_preflight_stub import FailClosedRouterStub, RouterStubError
from scripts.live_gate_preflight_profile_runner import (
    CharacterizationError,
    _ProfileCharacterizationLock,
    _characterize,
    _drive_profile_exchange,
    _claim_characterization_attempt,
    _parse_args,
    _repository_python,
)
from scripts import live_gate_preflight_profile_runner as profile_runner
from scripts import live_gate_preflight_sandbox as sandbox_preparation


def _guard_startup_event(
    pid: int,
    run_id: str,
    *,
    role: str = "host",
    sequence: int = 1,
    process_group_id: int | None = None,
    command_sha256: str = "a" * 64,
    working_directory: str = "tmp/combat_capture",
    interpreter: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "event_type": "guard_startup",
        "pid": pid,
        "process_group_id": pid if process_group_id is None else process_group_id,
        "process_role": role,
        "run_id": run_id,
        "observed_at_ns": 1_000_000 + sequence,
        "operation": None,
        "decision": None,
        "target_host": None,
        "target_port": None,
        "target_host_sha256": None,
        "command_sha256": command_sha256,
        "child_pid": None,
        "child_is_python": None,
        "guard_active": True,
        "interpreter": interpreter
        or {
            "executable": str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "prefix": str(PROJECT_ROOT / ".venv"),
            "base_prefix": "/usr/local",
        },
        "working_directory": working_directory,
    }


def _guard_network_event(
    pid: int,
    run_id: str,
    host: str,
    port: int,
    *,
    role: str = "host",
    decision: str = "allowed",
    sequence: int = 2,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "event_type": "network_attempt",
        "pid": pid,
        "process_group_id": pid,
        "process_role": role,
        "run_id": run_id,
        "observed_at_ns": 1_000_000 + sequence,
        "operation": "connect",
        "decision": decision,
        "target_host": host,
        "target_port": port,
        "target_host_sha256": None,
        "command_sha256": None,
        "child_pid": None,
        "child_is_python": None,
        "guard_active": None,
        "interpreter": None,
        "working_directory": None,
    }


def _guard_subprocess_attempt_event(
    pid: int,
    run_id: str,
    *,
    role: str = "host",
    sequence: int = 3,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "event_type": "subprocess_attempt",
        "pid": pid,
        "process_group_id": pid,
        "process_role": role,
        "run_id": run_id,
        "observed_at_ns": 1_000_000 + sequence,
        "operation": "Popen",
        "decision": "denied",
        "target_host": None,
        "target_port": None,
        "target_host_sha256": None,
        "command_sha256": "b" * 64,
        "child_pid": None,
        "child_is_python": None,
        "guard_active": None,
        "interpreter": None,
        "working_directory": None,
    }


def _guard_child_started_event(
    pid: int,
    child_pid: int,
    run_id: str,
    *,
    process_role: str = "parent",
    process_group_id: int | None = None,
    sequence: int = 2,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "event_type": "subprocess_started",
        "pid": pid,
        "process_group_id": pid if process_group_id is None else process_group_id,
        "process_role": process_role,
        "run_id": run_id,
        "observed_at_ns": 1_000_000 + sequence,
        "operation": "Popen",
        "decision": "started",
        "target_host": None,
        "target_port": None,
        "target_host_sha256": None,
        "command_sha256": "b" * 64,
        "child_pid": child_pid,
        "child_is_python": True,
        "guard_active": None,
        "interpreter": None,
        "working_directory": None,
    }


def _netstat_row(
    protocol: str,
    pid: int,
    local: str,
    foreign: str,
    *,
    state: str | None = None,
    process_name: str = "python worker",
) -> bytes:
    fields = [protocol, "0", "0", local, foreign]
    if protocol.startswith("tcp"):
        fields.append(state or "ESTABLISHED")
    suffix = "%s:%d 00000 00000000 0000000000000000" % (process_name, pid)
    return (" ".join(fields) + " " + suffix + "\n").encode("ascii")


class TestLiveGatePreflightProfiles(unittest.TestCase):
    def test_prepared_sandbox_validation_uses_repository_anchored_path(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-controller-", dir=PROJECT_ROOT / "tmp"
        ) as controller_cwd:
            project = Path(controller_cwd) / "project"
            sandbox = project / "tmp" / "combat_capture"
            (sandbox / "mapping_pilot").mkdir(parents=True)
            (sandbox / "config.py").write_text("# synthetic test config\n", encoding="ascii")
            seed_metadata = {
                "fixture_id": "interior_tavern",
                "arm": "A",
                "effective_seed": 42,
                "party": {"size": 1, "members": ["PC-One"]},
                "counterbalance": {
                    "row_id": "E01",
                    "row_type": "planned",
                    "script": "scripts/interior.json",
                    "fixed_seed": 42,
                },
            }
            (sandbox / "mapping_pilot" / "seed_metadata.json").write_text(
                json.dumps(seed_metadata), encoding="utf-8"
            )
            counterbalance_path = (
                project / "plans" / "v2-mapping-pilot-prereg" / "counterbalance.json"
            )
            counterbalance_path.parent.mkdir(parents=True)
            counterbalance_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "row_id": "E01",
                                "row_type": "planned",
                                "party": 1,
                                "arm": "A",
                                "script": "scripts/interior.json",
                                "fixed_seed": 42,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            script_path = project / "plans" / "v2-mapping-pilot-prereg" / "scripts" / "interior.json"
            script_path.parent.mkdir()
            script_path.write_text(
                json.dumps(
                    {
                        "fixture_ids": ["interior_tavern"],
                        "turns": [
                            {
                                "id": "E01-01",
                                "utterance": "Describe the room.",
                                "actor": {"party_1": "PC-One"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(profile_runner, "PROJECT_ROOT", project), mock.patch(
                "scripts.mapping_pilot.launcher.validate_sandbox"
            ) as validate, mock.patch.object(
                profile_runner,
                "_require_synthetic_sandbox_config",
                return_value=SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            ), mock.patch("os.getcwd", return_value=controller_cwd):
                result = profile_runner._validate_prepared_sandbox(
                    fixture_id="interior_tavern",
                    party_size=1,
                    lifecycle="startup",
                    resume_checkpoint_sha256=None,
                )

        self.assertEqual(result[0], project / "tmp" / "combat_capture")
        self.assertEqual(validate.call_args.args[0], result[0])
        self.assertEqual(validate.call_args.kwargs["project_root"], project)

    def test_schema_and_versioned_profile_declaration_are_supported(self) -> None:
        document = copy_profile_document()
        schema_path = PROFILE_PATH.with_name("live_gate_preflight_profiles.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["profile_set_id"], PROFILE_SET_ID)

    def test_all_26_planned_rows_bind_to_eight_pairs_and_reserves_stay_out(self) -> None:
        coverage = load_profile_coverage()
        self.assertEqual(coverage["planned_row_count"], 26)
        self.assertEqual(coverage["fixture_party_pair_count"], 8)
        self.assertTrue(coverage["structural_row_coverage_complete"])
        self.assertEqual(coverage["replacement_only_rows_activated"], [])
        self.assertFalse(any(row_id.startswith("R") for row_id in coverage["planned_row_ids"]))
        self.assertEqual(coverage["planned_row_ids"][0], "E01")
        self.assertEqual(coverage["planned_row_ids"][-1], "C08")

    def test_missing_paths_are_explicit_unverified_and_never_booking_eligible(self) -> None:
        document = copy_profile_document()
        coverage = validate_profile_document(document)
        self.assertFalse(coverage["measured_lifecycle_complete"])
        self.assertFalse(coverage["booking_eligible"])
        self.assertEqual(coverage["unverified_row_ids"], coverage["planned_row_ids"])
        self.assertEqual(len(coverage["unverified_row_ids"]), 26)
        for profile in document["profiles"]:
            for lifecycle in ("startup", "resume"):
                self.assertEqual(profile[lifecycle]["status"], "MISSING")
                self.assertTrue(profile[lifecycle]["reason"])

    def test_missing_pair_entry_is_rejected(self) -> None:
        document = copy_profile_document()
        document["profiles"].pop()
        with self.assertRaisesRegex(ProfileValidationError, "exactly eight"):
            validate_profile_document(document)

    def test_unsupported_status_and_pair_are_rejected(self) -> None:
        document = copy_profile_document()
        document["profiles"][0]["resume"]["status"] = "inferred"
        with self.assertRaisesRegex(ProfileValidationError, "unsupported lifecycle"):
            validate_profile_document(document)

        document = copy_profile_document()
        document["profiles"][0]["fixture_id"] = "unsupported_fixture"
        with self.assertRaisesRegex(ProfileValidationError, "unsupported fixture-party"):
            validate_profile_document(document)

    def test_source_hash_or_row_binding_drift_is_rejected(self) -> None:
        document = copy_profile_document()
        document["source_binding"]["counterbalance_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProfileValidationError, "source binding"):
            validate_profile_document(document)

        document = copy_profile_document()
        document["profiles"][0]["planned_row_ids"].append("R01")
        with self.assertRaisesRegex(ProfileValidationError, "planned-row binding"):
            validate_profile_document(document)

    def test_measured_profile_requires_stub_source_call_sites_and_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            schema_path = PROFILE_PATH.with_name("live_gate_preflight_profiles.schema.json")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(document)
            validate_profile_document(document, expected_source_sha="a" * 40)
            with self.assertRaisesRegex(ProfileValidationError, "does not match"):
                validate_profile_document(document, expected_source_sha="b" * 40)

            startup = document["profiles"][0]["startup"]
            startup["call_sites"][0]["count"] = 2
            with self.assertRaisesRegex(ProfileValidationError, "do not sum"):
                validate_profile_document(document)

            startup["call_sites"][0]["count"] = 1
            startup["call_count"] = 2
            startup["call_sites"][0]["count"] = 2
            with self.assertRaisesRegex(ProfileValidationError, "evidence call count differs"):
                validate_profile_document(document)

            del evidence_path

    def test_retained_real_startup_evidence_validates_offline(self) -> None:
        evidence_path = Path(
            "tmp/router-rollout/live-gate-preflight/profile-characterization/"
            "fr11-tower-p1-startup-01/profile-evidence.json"
        )
        if not evidence_path.is_file():
            self.skipTest("retained FR-11 characterization evidence is unavailable")
        raw = evidence_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "8908c2e325e0e2289789d4baeda721a553c809e1c9f5b4d99086f0f9f8b71a19",
        )
        evidence = json.loads(raw.decode("utf-8"))
        self.assertEqual(
            evidence["source_sha"], "7e874277c6bd69de2e13e1282ea0f8a0cda10290"
        )
        self.assertEqual(evidence["call_count"], 9)

        document = copy_profile_document()
        profile = next(
            item
            for item in document["profiles"]
            if item["profile_id"] == "transition_tower_approach:p1"
        )
        profile["startup"] = {
            "status": "measured-under-stub",
            "call_count": evidence["call_count"],
            "call_sites": evidence["call_sites"],
            "source_sha": evidence["source_sha"],
            "command": evidence["command"],
            "pythonpath": evidence["pythonpath"],
            "evidence_path": evidence_path.as_posix(),
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        }

        coverage = validate_profile_document(
            document, expected_source_sha=evidence["source_sha"]
        )
        self.assertTrue(coverage["structural_row_coverage_complete"])
        self.assertFalse(coverage["measured_lifecycle_complete"])
        self.assertFalse(coverage["booking_eligible"])
        self.assertEqual(coverage["replacement_only_rows_activated"], [])

    def test_profile_evidence_rejects_invalid_embedded_startup_canaries(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-canary-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["process_canaries"][0]["guard_events"][1]["decision"] = "allowed"
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(
                ProfileValidationError, "process canary guard events are incomplete"
            ):
                validate_profile_document(document)

            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["process_canaries"][0]["guard_events"][0][
                "process_group_id"
            ] += 50
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(
                ProfileValidationError,
                "process canary guard events differ from journal",
            ):
                validate_profile_document(document)

    def test_profile_evidence_hash_and_identity_mismatches_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            startup = document["profiles"][0]["startup"]
            original = evidence_path.read_bytes()
            evidence_path.write_bytes(original + b" ")
            with self.assertRaisesRegex(ProfileValidationError, "hash does not match"):
                validate_profile_document(document)

            evidence_path.write_bytes(original)
            evidence = json.loads(original.decode("utf-8"))
            evidence["fixture_id"] = "landscape_village"
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "identity or safety state differs"):
                validate_profile_document(document)

    def test_profile_evidence_records_only_the_synthetic_provider_placeholder(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-placeholder-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(
                evidence["sandbox_provider_key_placeholder"],
                SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            )

            evidence["sandbox_provider_key_placeholder"] = "synthetic-key-must-not-survive"
            self._write_evidence(evidence_path, evidence)
            document["profiles"][0]["startup"]["evidence_sha256"] = hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(
                ProfileValidationError, "identity or safety state differs"
            ):
                validate_profile_document(document)

    def test_profile_evidence_requires_startup_guard_and_completed_exchange(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            startup = document["profiles"][0]["startup"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["driver_exchange"]["turn_completed"] = False
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "lifecycle exchange is incomplete"):
                validate_profile_document(document)

            evidence["driver_exchange"]["turn_completed"] = True
            evidence["startup_guard_from_sitecustomize"] = False
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "identity or safety state differs"):
                validate_profile_document(document)

    def test_profile_evidence_requires_attributed_graceful_worker_shutdown(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-shutdown-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            startup = document["profiles"][0]["startup"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(evidence["worker_shutdown"]["server_returned"])
            validate_profile_document(document)

            evidence["worker_shutdown"]["request"]["run_id"] = "wrong-run"
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(
                ProfileValidationError, "worker shutdown is incomplete"
            ):
                validate_profile_document(document)

            evidence["worker_shutdown"]["request"]["run_id"] = evidence["run_id"]
            evidence["worker_shutdown"]["graceful_shutdown_requested"] = False
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(
                ProfileValidationError, "worker shutdown is incomplete"
            ):
                validate_profile_document(document)

    def test_profile_evidence_requires_repository_venv_prefix_identity(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-venv-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["worker_interpreter"]["prefix"] = sys.base_prefix
            self._write_evidence(evidence_path, evidence)
            document["profiles"][0]["startup"]["evidence_sha256"] = hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(
                ProfileValidationError, "identity or safety state differs"
            ):
                validate_profile_document(document)

    def test_profile_evidence_requires_real_topology_and_complete_pid_census(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-census-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            startup = document["profiles"][0]["startup"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            original_evidence = json.loads(json.dumps(evidence))
            evidence["process_canaries"][1]["canary_stage"] = "driver"
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "process canary identity differs"):
                validate_profile_document(document)

            evidence = original_evidence
            evidence["process_census"]["uncovered_pids"] = [99999]
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "process census identity differs"):
                validate_profile_document(document)

    def test_profile_evidence_rejects_malformed_and_duplicate_key_json(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            profile = document["profiles"][0]["startup"]
            for raw in (
                b'{"schema_version":1,,}',
                b'{"schema_version":1,"schema_version":1}',
            ):
                evidence_path.write_bytes(raw)
                profile["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
                with self.assertRaisesRegex(ProfileValidationError, "not valid JSON"):
                    validate_profile_document(document)

    def test_profile_evidence_rechecks_callsite_file_hash_and_summary(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            startup = document["profiles"][0]["startup"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["calls"][0]["source_file_sha256"] = "0" * 64
            evidence["call_sites"][0]["source_file_sha256"] = "0" * 64
            startup["call_sites"][0]["source_file_sha256"] = "0" * 64
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "source hash differs"):
                validate_profile_document(document)

    def test_profile_evidence_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            linked_path = evidence_path.parent / "profile-evidence-link.json"
            linked_path.symlink_to(evidence_path.name)
            profile = document["profiles"][0]["startup"]
            profile["evidence_path"] = linked_path.relative_to(PROJECT_ROOT).as_posix()
            with self.assertRaisesRegex(ProfileValidationError, "traverses a symlink"):
                validate_profile_document(document)

    def test_call_profile_schema_is_strict_about_missing_fields(self) -> None:
        document = copy_profile_document()
        document["profiles"][0]["startup"]["call_count"] = 0
        with self.assertRaisesRegex(ProfileValidationError, "fields are malformed"):
            validate_profile_document(document)

    def test_profile_evidence_validates_socket_rows_and_guard_ownership_end_to_end(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-census-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            samples = evidence["process_census"]["socket_pid_samples"]
            host_ready = next(sample for sample in samples if sample["phase"] == "host_ready")
            after_teardown = next(
                sample for sample in samples if sample["phase"] == "after_teardown"
            )
            self.assertEqual(host_ready["pids"], [10001, 10003])
            self.assertEqual(host_ready["listener_pids"], [10003])
            self.assertEqual(after_teardown["pids"], [10001])
            self.assertEqual(after_teardown["listener_pids"], [])
            self.assertTrue(
                validate_profile_document(document)["structural_row_coverage_complete"]
            )

    def test_profile_evidence_accepts_guarded_host_child_listener(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-host-child-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            child_pid = 10004
            journal_path = PROJECT_ROOT / evidence["guard_event_journal"]["path"]
            guard_events = [
                json.loads(line)
                for line in journal_path.read_text(encoding="ascii").splitlines()
            ]
            worker_startup = next(
                event
                for event in guard_events
                if event.get("event_type") == "guard_startup" and event["pid"] == 10003
            )
            child_started = _guard_child_started_event(
                10003,
                child_pid,
                evidence["run_id"],
                process_role="host",
                process_group_id=10003,
                sequence=4,
            )
            child_startup = _guard_startup_event(
                child_pid,
                evidence["run_id"],
                role="host",
                process_group_id=10003,
                command_sha256="b" * 64,
                working_directory=str(PROJECT_ROOT / "tmp" / "combat_capture"),
            )
            self.assertEqual(worker_startup["sequence"], 1)
            guard_events.extend([child_started, child_startup])
            journal_raw = b"".join(
                json.dumps(
                    event, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ).encode("ascii")
                + b"\n"
                for event in guard_events
            )
            journal_path.write_bytes(journal_raw)
            evidence["guard_event_journal"]["sha256"] = hashlib.sha256(
                journal_raw
            ).hexdigest()
            evidence["guard_event_journal"]["event_count"] = len(guard_events)

            census = evidence["process_census"]
            for sample in census["socket_pid_samples"]:
                sidecar_path = PROJECT_ROOT / sample["evidence_path"]
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                if sample["phase"] == "host_ready":
                    listener = next(
                        row
                        for row in sidecar["run_owned_rows"]
                        if row["state"] == "LISTEN"
                    )
                    listener["pid"] = child_pid
                    sample["pids"] = sorted(
                        {row["pid"] for row in sidecar["run_owned_rows"]}
                    )
                    sample["listener_pids"] = [child_pid]
                    sidecar["pids"] = sample["pids"]
                if sample["phase"] != "before_host":
                    sidecar["run_process_pids"] = sorted(
                        {event["pid"] for event in guard_events}
                        | {
                            event["child_pid"]
                            for event in guard_events
                            if event.get("event_type") == "subprocess_started"
                        }
                        | {10001, 10002, 10003}
                    )
                    sidecar["guard_startup_pids"] = sorted(
                        event["pid"]
                        for event in guard_events
                        if event.get("event_type") == "guard_startup"
                    )
                sidecar_path.write_text(
                    json.dumps(
                        sidecar,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    encoding="ascii",
                )
                sample["evidence_sha256"] = hashlib.sha256(
                    sidecar_path.read_bytes()
                ).hexdigest()

            census["socket_owner_pids"] = [10001, child_pid]
            census["python_child_pids"] = [child_pid]
            census["python_pids"] = [10001, 10002, 10003, child_pid]
            census["guarded_pids"] = [10001, 10002, 10003, child_pid]
            self._persist_profile_evidence(document, evidence_path, evidence)
            self.assertTrue(
                validate_profile_document(document)["structural_row_coverage_complete"]
            )

    def test_profile_evidence_accepts_guarded_controller_child_sockets_before_host(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-controller-child-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            child_pid = 10004
            guard_events = self._read_profile_guard_events(evidence)
            guard_events.extend(
                [
                    _guard_child_started_event(
                        10001,
                        child_pid,
                        evidence["run_id"],
                        process_role="parent",
                        process_group_id=10001,
                        sequence=4,
                    ),
                    _guard_startup_event(
                        child_pid,
                        evidence["run_id"],
                        role="parent",
                        process_group_id=10001,
                        command_sha256="c" * 64,
                    ),
                ]
            )
            self._write_profile_guard_events(evidence, guard_events)

            for phase in ("before_host", "host_ready", "after_teardown"):
                sample, sidecar_path, sidecar = self._read_profile_socket_sidecar(
                    evidence, phase
                )
                sidecar["run_process_pids"] = sorted(
                    set(sidecar["run_process_pids"]) | {child_pid}
                )
                sidecar["guard_startup_pids"] = sorted(
                    set(sidecar["guard_startup_pids"]) | {child_pid}
                )
                if phase in ("before_host", "host_ready"):
                    sidecar["run_owned_rows"].append(
                        {
                            "foreign": {"host": "127.0.0.1", "port": 59638},
                            "local": {"host": "127.0.0.1", "port": 59637},
                            "pid": child_pid,
                            "protocol": "tcp4",
                            "state": "ESTABLISHED",
                        }
                    )
                self._write_profile_socket_sidecar(
                    sample, sidecar_path, sidecar
                )

            census = evidence["process_census"]
            census["socket_owner_pids"] = [10001, 10003, child_pid]
            census["python_child_pids"] = [child_pid]
            census["python_pids"] = [10001, 10002, 10003, child_pid]
            census["guarded_pids"] = [10001, 10002, 10003, child_pid]
            self._persist_profile_evidence(document, evidence_path, evidence)
            self.assertTrue(
                validate_profile_document(document)["structural_row_coverage_complete"]
            )

    def test_profile_evidence_rejects_controller_child_socket_without_startup(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-controller-child-unguarded-",
            dir=PROJECT_ROOT / "tmp",
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            child_pid = 10004
            guard_events = self._read_profile_guard_events(evidence)
            guard_events.append(
                _guard_child_started_event(
                    10001,
                    child_pid,
                    evidence["run_id"],
                    process_role="parent",
                    process_group_id=10001,
                    sequence=4,
                )
            )
            self._write_profile_guard_events(evidence, guard_events)
            for phase in ("host_ready", "after_teardown"):
                sample, sidecar_path, sidecar = self._read_profile_socket_sidecar(
                    evidence, phase
                )
                sidecar["run_process_pids"] = sorted(
                    set(sidecar["run_process_pids"]) | {child_pid}
                )
                if phase == "host_ready":
                    sidecar["run_owned_rows"].append(
                        {
                            "foreign": {"host": "127.0.0.1", "port": 59638},
                            "local": {"host": "127.0.0.1", "port": 59637},
                            "pid": child_pid,
                            "protocol": "tcp4",
                            "state": "ESTABLISHED",
                        }
                    )
                self._write_profile_socket_sidecar(
                    sample, sidecar_path, sidecar
                )
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(
                ProfileValidationError, "socket sample guard ownership differs"
            ):
                validate_profile_document(document)

    def test_profile_evidence_rejects_guarded_controller_child_as_host_listener(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-controller-listener-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            child_pid = 10004
            guard_events = self._read_profile_guard_events(evidence)
            guard_events.extend(
                [
                    _guard_child_started_event(
                        10001,
                        child_pid,
                        evidence["run_id"],
                        process_role="parent",
                        process_group_id=10001,
                        sequence=4,
                    ),
                    _guard_startup_event(
                        child_pid,
                        evidence["run_id"],
                        role="parent",
                        process_group_id=10001,
                        command_sha256="c" * 64,
                    ),
                ]
            )
            self._write_profile_guard_events(evidence, guard_events)
            for phase in ("host_ready", "after_teardown"):
                sample, sidecar_path, sidecar = self._read_profile_socket_sidecar(
                    evidence, phase
                )
                sidecar["run_process_pids"] = sorted(
                    set(sidecar["run_process_pids"]) | {child_pid}
                )
                sidecar["guard_startup_pids"] = sorted(
                    set(sidecar["guard_startup_pids"]) | {child_pid}
                )
                if phase == "host_ready":
                    sidecar["run_owned_rows"].append(
                        {
                            "foreign": {"host": "*", "port": None},
                            "local": {"host": "127.0.0.1", "port": 8360},
                            "pid": child_pid,
                            "protocol": "tcp4",
                            "state": "LISTEN",
                        }
                    )
                self._write_profile_socket_sidecar(
                    sample, sidecar_path, sidecar
                )
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(
                ProfileValidationError, "process census socket ownership differs"
            ):
                validate_profile_document(document)

    def test_profile_evidence_rejects_malformed_incomplete_and_unguarded_samples(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-census-invalid-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            sample = next(
                item
                for item in evidence["process_census"]["socket_pid_samples"]
                if item["phase"] == "host_ready"
            )
            sidecar_path = PROJECT_ROOT / sample["evidence_path"]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["run_owned_rows"][0]["local"]["port"] = "8360"
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(ProfileValidationError, "socket sample identity differs"):
                validate_profile_document(document)

            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["guard_event_journal"]["complete"] = False
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(ProfileValidationError, "guard-event journal is incomplete"):
                validate_profile_document(document)

            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            sample = next(
                item
                for item in evidence["process_census"]["socket_pid_samples"]
                if item["phase"] == "host_ready"
            )
            sidecar_path = PROJECT_ROOT / sample["evidence_path"]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            unguarded_pid = 19999
            sidecar["run_owned_rows"].append(
                {
                    "foreign": {"host": "*", "port": None},
                    "local": {"host": "127.0.0.1", "port": 8360},
                    "pid": unguarded_pid,
                    "protocol": "tcp4",
                    "state": "LISTEN",
                }
            )
            sidecar["run_owned_rows"].sort(key=lambda row: row["pid"])
            sidecar["pids"] = sorted({row["pid"] for row in sidecar["run_owned_rows"]})
            sidecar["aggregate_counts"]["internet_rows"] += 1
            sidecar["aggregate_counts"]["run_pid_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["internet_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["run_pid_rows"] += 1
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            sample["pids"] = sidecar["pids"]
            sample["listener_pids"] = [10003, unguarded_pid]
            sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(ProfileValidationError, "socket sample guard ownership differs"):
                validate_profile_document(document)

    def test_profile_evidence_rejects_spoofed_listener_and_surviving_host_socket(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-census-teardown-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            sample = next(
                item
                for item in evidence["process_census"]["socket_pid_samples"]
                if item["phase"] == "host_ready"
            )
            sidecar_path = PROJECT_ROOT / sample["evidence_path"]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["run_owned_rows"].append(
                {
                    "foreign": {"host": "*", "port": None},
                    "local": {"host": "127.0.0.1", "port": 8360},
                    "pid": 10001,
                    "protocol": "tcp4",
                    "state": "LISTEN",
                }
            )
            sidecar["run_owned_rows"].sort(key=lambda row: row["pid"])
            sidecar["aggregate_counts"]["internet_rows"] += 1
            sidecar["aggregate_counts"]["run_pid_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["internet_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["run_pid_rows"] += 1
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            sample["listener_pids"] = [10001, 10003]
            sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(ProfileValidationError, "socket ownership differs"):
                validate_profile_document(document)

            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            sample = next(
                item
                for item in evidence["process_census"]["socket_pid_samples"]
                if item["phase"] == "after_teardown"
            )
            sidecar_path = PROJECT_ROOT / sample["evidence_path"]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["run_owned_rows"].append(
                {
                    "foreign": {"host": "127.0.0.1", "port": 8360},
                    "local": {"host": "127.0.0.1", "port": 59644},
                    "pid": 10003,
                    "protocol": "tcp4",
                    "state": "ESTABLISHED",
                }
            )
            sidecar["run_owned_rows"].sort(key=lambda row: row["pid"])
            sidecar["pids"] = sorted({row["pid"] for row in sidecar["run_owned_rows"]})
            sidecar["aggregate_counts"]["internet_rows"] += 1
            sidecar["aggregate_counts"]["run_pid_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["internet_rows"] += 1
            sidecar["protocol_samples"][0]["counts"]["run_pid_rows"] += 1
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            sample["pids"] = sidecar["pids"]
            sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(ProfileValidationError, "socket ownership differs"):
                validate_profile_document(document)

    def _persist_profile_evidence(
        self, document: dict[str, Any], evidence_path: Path, evidence: dict[str, Any]
    ) -> None:
        self._write_evidence(evidence_path, evidence)
        document["profiles"][0]["startup"]["evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()

    def _read_profile_guard_events(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        path = PROJECT_ROOT / evidence["guard_event_journal"]["path"]
        return [
            json.loads(line)
            for line in path.read_text(encoding="ascii").splitlines()
        ]

    def _write_profile_guard_events(
        self, evidence: dict[str, Any], events: list[dict[str, Any]]
    ) -> None:
        journal = evidence["guard_event_journal"]
        path = PROJECT_ROOT / journal["path"]
        raw = b"".join(
            json.dumps(
                event, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
            + b"\n"
            for event in events
        )
        path.write_bytes(raw)
        journal["sha256"] = hashlib.sha256(raw).hexdigest()
        journal["event_count"] = len(events)

    def _read_profile_socket_sidecar(
        self, evidence: dict[str, Any], phase: str
    ) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        sample = next(
            item
            for item in evidence["process_census"]["socket_pid_samples"]
            if item["phase"] == phase
        )
        path = PROJECT_ROOT / sample["evidence_path"]
        return sample, path, json.loads(path.read_text(encoding="utf-8"))

    def _write_profile_socket_sidecar(
        self, sample: dict[str, Any], path: Path, sidecar: dict[str, Any]
    ) -> None:
        rows = sidecar["run_owned_rows"]
        sidecar["pids"] = sorted({row["pid"] for row in rows})
        sample["pids"] = sidecar["pids"]
        sample["listener_pids"] = profile_runner._host_ready_listener_pids(rows)
        count_fields = (
            "internet_rows",
            "unattributed_rows",
            "pid_zero_rows",
            "foreign_process_rows",
            "run_pid_rows",
            "malformed_run_pid_rows",
        )
        aggregate = {key: 0 for key in count_fields}
        for protocol_sample in sidecar["protocol_samples"]:
            protocol = protocol_sample["protocol"]
            protocol_rows = [
                row
                for row in rows
                if row["protocol"].startswith(protocol)
            ]
            counts = {key: 0 for key in count_fields}
            counts["internet_rows"] = len(protocol_rows)
            counts["run_pid_rows"] = len(protocol_rows)
            protocol_sample["counts"] = counts
            for key in count_fields:
                aggregate[key] += counts[key]
        sidecar["aggregate_counts"] = aggregate
        path.write_text(
            json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        sample["evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def _measured_document(self, evidence_directory: Path) -> tuple[dict, Path]:
        document = copy_profile_document()
        profile = document["profiles"][0]
        run_id = "profile-test-" + uuid.uuid4().hex[:12]
        run_directory = PROJECT_ROOT / GUARD_EVENT_ROOT / run_id
        run_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, run_directory, ignore_errors=True)
        source_file = "scripts/test_live_gate_preflight_profiles.py"
        source_hash = hashlib.sha256((PROJECT_ROOT / source_file).read_bytes()).hexdigest()
        command = [
            _repository_python(),
            "scripts/live_gate_preflight_profile_runner.py",
        ]
        host_command = profile_runner._host_command(
            fixture_id=profile["fixture_id"],
            party_size=profile["party_size"],
            lifecycle="startup",
            source_sha="a" * 40,
            run_id=run_id,
            planned_row_id=profile["planned_row_ids"][0],
            arm="A",
            lifecycle_id=run_id + "_s",
            resume_checkpoint_sha256=None,
        )
        pythonpath = expected_guarded_pythonpath(PROJECT_ROOT)
        call = {
            "sequence": 1,
            "task": "dm_main",
            "source_file": source_file,
            "source_line": 1,
            "source_file_sha256": source_hash,
            "source_sha": "a" * 40,
            "command": host_command,
            "pythonpath": pythonpath,
        }
        call_site = {
            "source_file": source_file,
            "source_line": 1,
            "source_file_sha256": source_hash,
            "count": 1,
        }
        evidence_path = evidence_directory / "profile-evidence.json"
        evidence_relative = evidence_path.relative_to(PROJECT_ROOT).as_posix()
        controller_cwd = str(evidence_directory.resolve())
        host_cwd = str(PROJECT_ROOT / "tmp" / "combat_capture")
        interpreter = {
            "executable": _repository_python(),
            "prefix": str(PROJECT_ROOT / ".venv"),
            "base_prefix": sys.base_prefix,
        }

        def canary(
            process_role: str,
            canary_stage: str,
            process_command: list[str],
            cwd: str,
            pid: int,
            environment_sha256: str,
        ) -> dict:
            return {
                "canary_stage": canary_stage,
                "process_role": process_role,
                "pid": pid,
                "startup_observed_at_ns": pid * 1000,
                "command": process_command,
                "command_sha256": hashlib.sha256(
                    json.dumps(
                        process_command,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest(),
                "environment_sha256": environment_sha256,
                "working_directory": cwd,
                "guard_active": True,
                "non_loopback_connect_denied": True,
                "subprocess_launch_denied": True,
                "interpreter": interpreter,
            }

        process_canaries = [
            canary(
                "parent", "controller-startup", command, controller_cwd, 10001, "a" * 64
            ),
            canary("host", "host-prelaunch", host_command, host_cwd, 10002, "b" * 64),
            canary("host", "host-startup", host_command, host_cwd, 10003, "b" * 64),
        ]
        canaries_by_stage = {
            report["canary_stage"]: report for report in process_canaries
        }
        guard_events = []
        for report in process_canaries:
            role = report["process_role"]
            pid = report["pid"]
            snapshot = [
                _guard_startup_event(
                    pid,
                    run_id,
                    role=role,
                    command_sha256=report["command_sha256"],
                    working_directory=report["working_directory"],
                    interpreter=report["interpreter"],
                ),
                _guard_network_event(
                    pid,
                    run_id,
                    "192.0.2.1",
                    8360,
                    role=role,
                    decision="denied",
                    sequence=2,
                ),
                _guard_subprocess_attempt_event(pid, run_id, role=role),
            ]
            report["guard_events_complete"] = True
            report["guard_events"] = [
                {**event, "run_id": ""} if role == "parent" else dict(event)
                for event in snapshot
            ]
            guard_events.extend(snapshot)

        def scope(
            stage: str,
            selector: str,
            process_group_id: int,
            role: str,
            launch_source: str,
        ) -> dict[str, Any]:
            report = canaries_by_stage[stage]
            return {
                "selector": selector,
                "pid": report["pid"],
                "process_group_id": process_group_id,
                "process_role": role,
                "launch_source": launch_source,
                "command_sha256": report["command_sha256"],
                "environment_sha256": report["environment_sha256"],
                "working_directory_sha256": hashlib.sha256(
                    report["working_directory"].encode("utf-8")
                ).hexdigest(),
            }

        process_scopes = [
            scope(
                "controller-startup", "pid", 10001, "parent", "controller-startup-canary"
            ),
            scope(
                "host-prelaunch",
                "process_group",
                10002,
                "host",
                "host-prelaunch-canary-session",
            ),
            scope(
                "host-startup",
                "process_group",
                10003,
                "host",
                "host-worker-start-new-session",
            ),
        ]
        rows_by_phase = {
            "before_host": [],
            "host_ready": [
                {
                    "foreign": {"host": "*", "port": None},
                    "local": {"host": "127.0.0.1", "port": 8360},
                    "pid": 10003,
                    "protocol": "tcp4",
                    "state": "LISTEN",
                },
                {
                    "foreign": {"host": "127.0.0.1", "port": 8360},
                    "local": {"host": "127.0.0.1", "port": 59635},
                    "pid": 10001,
                    "protocol": "tcp4",
                    "state": "TIME_WAIT",
                },
            ],
            "after_teardown": [
                {
                    "foreign": {"host": "127.0.0.1", "port": 8360},
                    "local": {"host": "127.0.0.1", "port": 59635},
                    "pid": 10001,
                    "protocol": "tcp4",
                    "state": "TIME_WAIT",
                }
            ],
        }
        pre_host_pids = {
            canaries_by_stage["controller-startup"]["pid"],
            canaries_by_stage["host-prelaunch"]["pid"],
        }
        event_phases = {
            "before_host": [
                event for event in guard_events if event["pid"] in pre_host_pids
            ],
            "host_ready": guard_events,
            "after_teardown": guard_events,
        }
        census_samples: list[dict[str, Any]] = []
        for phase in ("before_host", "host_ready", "after_teardown"):
            phase_events = event_phases[phase]
            phase_scopes = process_scopes[:2] if phase == "before_host" else process_scopes
            rows = rows_by_phase[phase]
            owners = sorted({row["pid"] for row in rows})
            listeners = sorted(profile_runner._host_ready_listener_pids(rows))
            aggregate_counts = {
                "internet_rows": len(rows),
                "unattributed_rows": 0,
                "pid_zero_rows": 0,
                "foreign_process_rows": 0,
                "run_pid_rows": len(rows),
                "malformed_run_pid_rows": 0,
            }
            protocol_samples = []
            for protocol in ("tcp", "udp"):
                counts = dict(aggregate_counts)
                if protocol == "udp":
                    counts = {key: 0 for key in aggregate_counts}
                protocol_samples.append(
                    {
                        "protocol": protocol,
                        "command_evidence": {
                            "command": ["/usr/sbin/netstat", "-anv", "-W", "-p", protocol],
                            "returncode": 0,
                            "failure": None,
                            "stdout_byte_count": 1,
                            "stdout_sha256": hashlib.sha256(
                                (phase + protocol).encode("ascii")
                            ).hexdigest(),
                            "stdout_truncated": False,
                            "stdout_prefix_base64": "",
                            "stderr_byte_count": 0,
                            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                            "stderr_truncated": False,
                            "stderr_prefix_base64": "",
                            "observed": True,
                        },
                        "counts": counts,
                        "parseable": True,
                    }
                )
            sidecar = {
                "schema_version": 3,
                "run_id": run_id,
                "phase": phase,
                "observer": "netstat -anv -W -p tcp and udp; PID filter precedes endpoint parsing",
                "process_scopes": phase_scopes,
                "run_process_pids": sorted(
                    {event["pid"] for event in phase_events}
                    | {
                        event["child_pid"]
                        for event in phase_events
                        if event.get("event_type") == "subprocess_started"
                    }
                    | {item["pid"] for item in phase_scopes}
                ),
                "guard_startup_pids": sorted(
                    event["pid"]
                    for event in phase_events
                    if event.get("event_type") == "guard_startup"
                ),
                "protocol_samples": protocol_samples,
                "aggregate_counts": aggregate_counts,
                "run_owned_rows": rows,
                "pids": owners,
                "observed": True,
                "failure_code": None,
            }
            sidecar_path = run_directory / ("socket-sample-%s.json" % phase)
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            census_samples.append(
                {
                    "phase": phase,
                    "port": 8360,
                    "observed": True,
                    "pids": owners,
                    "listener_pids": listeners,
                    "failure_code": None,
                    "evidence_path": sidecar_path.relative_to(PROJECT_ROOT).as_posix(),
                    "evidence_sha256": hashlib.sha256(
                        sidecar_path.read_bytes()
                    ).hexdigest(),
                }
            )
        guard_journal_path = run_directory / "guard-events.jsonl"
        guard_journal_raw = b"".join(
            json.dumps(
                event, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
            + b"\n"
            for event in guard_events
        )
        guard_journal_path.write_bytes(guard_journal_raw)
        socket_owner_pids = sorted(
            {pid for sample in census_samples for pid in sample["pids"]}
        )
        guarded_pids = sorted(report["pid"] for report in process_canaries)
        census = {
            "controller_pid": 10001,
            "driver_pid": 10001,
            "host_prelaunch_pid": 10002,
            "host_worker_pid": 10003,
            "launched_pids": [10001, 10002, 10003],
            "socket_owner_pids": socket_owner_pids,
            "python_child_pids": [],
            "python_pids": [10001, 10002, 10003],
            "guarded_pids": guarded_pids,
            "canary_pids": guarded_pids,
            "uncovered_pids": [],
            "guard_events_valid": True,
            "socket_pid_samples": census_samples,
            "complete": True,
        }
        evidence = {
            "schema_version": 1,
            "authorization_ruling_id": "neq-w1-fr11-profiles-characterization-20261112",
            "profile_id": profile["profile_id"],
            "fixture_id": profile["fixture_id"],
            "party_size": profile["party_size"],
            "lifecycle": "startup",
            "planned_row_id": profile["planned_row_ids"][0],
            "arm": "A",
            "sandbox_root": "tmp/combat_capture",
            "run_id": run_id,
            "source_sha": "a" * 40,
            "command": host_command,
            "working_directory": "tmp/combat_capture",
            "pythonpath": pythonpath,
            "process_canaries": process_canaries,
            "guard_event_journal": {
                "path": guard_journal_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": hashlib.sha256(guard_journal_raw).hexdigest(),
                "event_count": len(guard_events),
                "complete": True,
            },
            "process_census": census,
            "worker_shutdown": {
                "server_returned": True,
                "interrupted": True,
                "graceful_shutdown_requested": True,
                "signal_received_at_ns": 3_000_001,
                "request": {
                    "schema_version": 1,
                    "run_id": run_id,
                    "controller_pid": 10001,
                    "worker_pid": 10003,
                    "process_group_id": 10003,
                    "signal_number": int(signal.SIGINT),
                    "requested_at_ns": 3_000_000,
                    "readiness_succeeded": True,
                    "exchange_succeeded": True,
                },
            },
            "controller_interpreter": interpreter,
            "worker_interpreter": interpreter,
            "network_guard_active": True,
            "provider_environment_keys_blank": True,
            "sandbox_provider_key_placeholder": SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            "proxy_values_blank": True,
            "real_project_config_loaded": False,
            "sandbox_config_loaded": True,
            "startup_guard_from_sitecustomize": True,
            "sandbox_config_origin_guard_active": True,
            "driver_exchange": {
                "status": "completed",
                "step_id": "E01-01",
                "start_ready": True,
                "active_character_set": True,
                "turn_completed": True,
                "turn_timed_out": False,
                "game_output_count": 1,
                "failure_code": None,
                "process_pid": 10001,
            },
            "outcome": "completed",
            "calls": [call],
            "call_count": 1,
            "call_sites": [call_site],
            "host_command": host_command,
            "runner_command": command,
            "failure_code": None,
            "teardown": {
                "server_stopped": True,
                "port_8360_free": True,
                "lock_released": True,
            },
        }
        self._write_evidence(evidence_path, evidence)
        profile["startup"] = {
            "status": "measured-under-stub",
            "call_count": 1,
            "call_sites": [call_site],
            "source_sha": "a" * 40,
            "command": host_command,
            "pythonpath": pythonpath,
            "evidence_path": evidence_relative,
            "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        }
        return document, evidence_path

    @staticmethod
    def _write_evidence(path: Path, evidence: dict) -> None:
        path.write_text(
            json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )


class TestPreflightStubAndSafety(unittest.TestCase):
    def test_stub_counts_calls_and_records_source_command_sha_and_pythonpath(self) -> None:
        completed = self._run_guarded_test_child("--stub-probe")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["response"], {"text": "stubbed"})
        self.assertEqual(payload["call_count"], 2)
        call = payload["calls"][0]
        self.assertEqual(call["source_file"], "scripts/test_live_gate_preflight_profiles.py")
        self.assertGreater(call["source_line"], 0)
        self.assertEqual(call["source_sha"], "a" * 40)
        self.assertEqual(call["pythonpath"], expected_guarded_pythonpath(PROJECT_ROOT))
        self.assertEqual(call["command"][0], ".venv/bin/python")
        self.assertEqual(call["command"][2:], ["--api-key", "<redacted>"])
        self.assertTrue(payload["unsupported_call_rejected"])
        self.assertNotIn("synthetic-secret", completed.stdout)

    def test_stub_counts_then_rejects_unsupported_router_call(self) -> None:
        completed = self._run_guarded_test_child("--stub-probe")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["calls"][0]["sequence"], 1)
        self.assertEqual(payload["calls"][1]["sequence"], 2)
        self.assertEqual(payload["calls"][1]["task"], "unlisted_task")
        self.assertRegex(payload["calls"][0]["source_file_sha256"], r"^[0-9a-f]{64}$")

    def test_characterization_stub_covers_observed_tasks_with_source_shapes(self) -> None:
        completed = self._run_guarded_test_child("--profile-stub-probe")
        payload = json.loads(completed.stdout)
        expected_tasks = {
            "travel_narration",
            "safety_review",
            "action_prediction",
            "dm_main",
            "dm_validation",
        }
        self.assertEqual(set(payload["responses"]), expected_tasks)
        self.assertEqual(payload["call_count"], len(expected_tasks) + 1)
        self.assertEqual(
            {call["task"] for call in payload["calls"][:-1]},
            expected_tasks,
        )
        self.assertEqual(len(payload["calls"][:-1]), len(expected_tasks))
        self.assertEqual(payload["calls"][-1]["task"], "unlisted_task")
        self.assertTrue(payload["unsupported_call_rejected"])
        self.assertEqual(payload["failure_code"], "router_task_has_no_stub_response")

        responses = {
            task: json.loads(response)
            for task, response in payload["responses"].items()
        }
        self.assertEqual(
            set(responses["travel_narration"]), {"travelNarration", "dmGuidance"}
        )
        self.assertIsInstance(responses["safety_review"]["safe"], bool)
        self.assertIsInstance(responses["safety_review"]["reason"], str)
        self.assertIsInstance(responses["action_prediction"]["requires_actions"], bool)
        self.assertIsInstance(responses["action_prediction"]["reason"], str)
        self.assertEqual(
            set(responses["dm_main"]), {"narration", "actions"}
        )
        fixtures, source_hashes = load_verified_fixtures()
        module_payloads, _expected_payloads = build_fixture_payloads(
            fixtures, source_hashes
        )
        self.assertEqual(set(fixtures), set(FIXTURE_IDS))
        for fixture_id in FIXTURE_IDS:
            with self.subTest(fixture_id=fixture_id):
                source_location_ids = fixtures[fixture_id]["location_ids"]
                self.assertEqual(len(source_location_ids), 1)
                runtime_location_id = LOCATION_ID_MAP[source_location_ids[0]]
                matches = [
                    (payload, location)
                    for relative_path, payload in module_payloads.items()
                    if relative_path.startswith("areas/")
                    and not relative_path.endswith("_BU.json")
                    for location in payload.get("locations", [])
                    if location.get("locationId") == runtime_location_id
                ]
                self.assertEqual(len(matches), 1)
                area, location = matches[0]
                declaration = profile_runner._characterization_stub_responses(
                    fixture_id
                )
                start_location = json.loads(declaration["dm_validation"])
                self.assertEqual(
                    tuple(
                        start_location[key]
                        for key in (
                            "locationId",
                            "locationName",
                            "areaId",
                            "areaName",
                        )
                    ),
                    (
                        runtime_location_id,
                        location["name"],
                        area["areaId"],
                        area["areaName"],
                    ),
                )

        with self.assertRaises(CharacterizationError):
            profile_runner._characterization_stub_responses("unsupported_fixture")

    def test_stub_redacts_sensitive_command_arguments(self) -> None:
        completed = self._run_guarded_test_child("--stub-probe")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["calls"][0]["command"][2:], ["--api-key", "<redacted>"])
        self.assertNotIn("synthetic-secret", completed.stdout)

    def test_guarded_environment_never_copies_secret_or_proxy_values(self) -> None:
        source = {
            "PATH": "safe-path",
            "OPENROUTER_API_KEY": "must-not-copy",
            "CUSTOM_SECRET": "must-not-copy-either",
            "HTTPS_PROXY": "must-not-copy-proxy",
            "PYTHONPATH": "/unsafe/original",
            "HOME": "/not-copied",
        }
        environment = build_guarded_environment(source)
        self.assertEqual(environment["PATH"], "safe-path")
        self.assertEqual(environment["PYTHONPATH"], expected_guarded_pythonpath(PROJECT_ROOT))
        self.assertEqual(environment[PROCESS_ROLE_ENV], "parent")
        self.assertEqual(environment[EXPECTED_PYTHON_ENV], _repository_python())
        self.assertEqual(environment[EXPECTED_PREFIX_ENV], str(PROJECT_ROOT / ".venv"))
        self.assertEqual(
            environment["PYTHONPATH"].split(os.pathsep)[0],
            str(PROJECT_ROOT / GUARD_DIRECTORY),
        )
        self.assertEqual(environment[ENABLE_GUARD_ENV], "1")
        self.assertEqual(environment[REQUIRE_STARTUP_GUARD_ENV], "1")
        self.assertEqual(environment["OPENROUTER_API_KEY"], "")
        self.assertEqual(environment["CUSTOM_SECRET"], "")
        self.assertEqual(environment["HTTPS_PROXY"], "")
        self.assertNotIn("HOME", environment)
        self.assertNotIn("must-not-copy", repr(environment))

    def test_only_isolated_sandbox_config_location_is_accepted(self) -> None:
        accepted = validate_sandbox_config_location(
            "tmp/combat_capture/config.py",
            sandbox_root="tmp/combat_capture",
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(accepted, PROJECT_ROOT / "tmp/combat_capture/config.py")
        with self.assertRaisesRegex(SafetyConfigurationError, "copied sandbox config"):
            validate_sandbox_config_location(
                "config.py",
                sandbox_root="tmp/combat_capture",
                project_root=PROJECT_ROOT,
            )

    def test_dedicated_startup_guard_records_each_role_and_exact_environment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="preflight-guard-probe-", dir="tmp") as temp_root:
            relative_root = Path(temp_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            probe = Path(temp_root) / "guard_probe.py"
            probe.write_text(
                "import json, os, socket, subprocess, sys\n"
                "from scripts.live_gate_preflight_safety import NetworkGuardError, require_startup_guard_active, sanitized_environment_snapshot\n"
                "require_startup_guard_active()\n"
                "report = json.loads(os.environ['NEQ_PREFLIGHT_STARTUP_CANARY_REPORT'])\n"
                "class CanarySocket:\n"
                "    family = socket.AF_INET\n"
                "try:\n"
                "    socket.socket.connect(CanarySocket(), ('192.0.2.1', 8360))\n"
                "except NetworkGuardError:\n"
                "    connect_denied = True\n"
                "else:\n"
                "    connect_denied = False\n"
                "try:\n"
                "    subprocess.Popen([sys.executable, '-c', 'print(\"UNGUARDED_CHILD_RAN\")'])\n"
                "except NetworkGuardError:\n"
                "    child_denied = True\n"
                "else:\n"
                "    child_denied = False\n"
                "print(json.dumps({'report': report, 'connect_denied': connect_denied, 'child_denied': child_denied, 'identity': {'executable': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix}, 'environment': sanitized_environment_snapshot()}, sort_keys=True))\n",
                encoding="ascii",
            )
            command = [_repository_python(), str(probe)]
            for process_role in sorted(PROCESS_ROLES):
                with self.subTest(process_role=process_role):
                    environment = build_guarded_sandbox_environment(
                        relative_root,
                        project_root=PROJECT_ROOT,
                        source_environment={
                            "PATH": os.environ.get("PATH", ""),
                            "OPENROUTER_API_KEY": "synthetic-key-must-not-survive",
                            "HTTPS_PROXY": "synthetic-proxy-must-not-survive",
                        },
                        process_role=process_role,
                    )
                    completed = subprocess.run(
                        command,
                        cwd=relative_root,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    payload = json.loads(completed.stdout)
                    report = payload["report"]
                    self.assertEqual(report["process_role"], process_role)
                    self.assertEqual(report["command"], command)
                    self.assertEqual(
                        report["working_directory"], str(Path(temp_root).resolve())
                    )
                    self.assertRegex(report["command_sha256"], r"^[0-9a-f]{64}$")
                    self.assertRegex(report["environment_sha256"], r"^[0-9a-f]{64}$")
                    startup_environment = dict(payload["environment"])
                    for added_after_canary in (
                        CONNECT_CANARY_ENV,
                        SUBPROCESS_CANARY_ENV,
                        CANARY_REPORT_ENV,
                        STARTUP_GUARD_ENV,
                        "NEQ_PREFLIGHT_SYS_EXECUTABLE",
                        "NEQ_PREFLIGHT_SYS_PREFIX",
                        "NEQ_PREFLIGHT_SYS_BASE_PREFIX",
                    ):
                        startup_environment.pop(added_after_canary, None)
                    expected_environment_sha = hashlib.sha256(
                        json.dumps(
                            sorted(
                                (str(name), str(value))
                                for name, value in startup_environment.items()
                            ),
                            ensure_ascii=True,
                            separators=(",", ":"),
                        ).encode("ascii")
                    ).hexdigest()
                    self.assertEqual(
                        report["environment_sha256"],
                        expected_environment_sha,
                        json.dumps(
                            {
                                "expected_startup_environment": startup_environment,
                                "launch_environment": environment,
                            },
                            sort_keys=True,
                        ),
                    )
                    self.assertTrue(report["guard_active"])
                    self.assertTrue(report["non_loopback_connect_denied"])
                    self.assertTrue(report["subprocess_launch_denied"])
                    self.assertEqual(report["interpreter"], payload["identity"])
                    self.assertEqual(payload["identity"]["executable"], _repository_python())
                    self.assertEqual(
                        payload["identity"]["prefix"], str(PROJECT_ROOT / ".venv")
                    )
                    self.assertNotEqual(
                        payload["identity"]["prefix"],
                        payload["identity"]["base_prefix"],
                    )
                    self.assertTrue(payload["connect_denied"])
                    self.assertTrue(payload["child_denied"])
                    self.assertNotIn("UNGUARDED_CHILD_RAN", completed.stdout)
                    self.assertNotIn("synthetic-key-must-not-survive", completed.stdout)
                    self.assertNotIn("synthetic-proxy-must-not-survive", completed.stdout)

    def test_missing_dedicated_guard_path_fails_before_preflight_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="preflight-guard-missing-", dir="tmp") as temp_root:
            relative_root = Path(temp_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            probe = Path(temp_root) / "missing_guard_probe.py"
            probe.write_text(
                "from scripts.live_gate_preflight_safety import require_startup_guard_active\n"
                "require_startup_guard_active()\n"
                "print('PREFLIGHT_WORK_RAN')\n",
                encoding="ascii",
            )
            environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                process_role="parent",
            )
            environment["PYTHONPATH"] = str(PROJECT_ROOT)
            completed = subprocess.run(
                [_repository_python(), str(probe)],
                cwd=relative_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("PREFLIGHT_WORK_RAN", completed.stdout)
            self.assertNotIn("NEQ_PREFLIGHT_STARTUP_CANARY_REPORT", completed.stdout)
            self.assertIn("preflight startup guard", completed.stderr)

    def test_child_without_guard_environment_fails_closed_before_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="preflight-child-no-env-", dir="tmp") as temp_root:
            relative_root = Path(temp_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            probe = Path(temp_root) / "child_without_guard.py"
            probe.write_text(
                "from scripts.live_gate_preflight_profile_runner import _require_worker_startup_guard\n"
                "_require_worker_startup_guard()\n"
                "print('CHILD_ENTRYPOINT_RAN')\n",
                encoding="ascii",
            )
            child_environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(PROJECT_ROOT),
            }
            completed = subprocess.run(
                [_repository_python(), str(probe)],
                cwd=relative_root,
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("CHILD_ENTRYPOINT_RAN", completed.stdout)
            self.assertFalse(
                any(name.startswith("NEQ_PREFLIGHT_") for name in child_environment)
            )
            self.assertIn("host_startup_guard_inactive", completed.stderr)

    def test_required_startup_guard_rejects_a_missing_guard_switch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="preflight-guard-switch-", dir="tmp") as temp_root:
            relative_root = Path(temp_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            sandbox = PROJECT_ROOT / relative_root
            (sandbox / "preflight_switch_probe.py").write_text(
                "print('MAIN_MODULE_RAN')\n",
                encoding="utf-8",
            )
            environment = build_guarded_sandbox_environment(
                relative_root,
                project_root=PROJECT_ROOT,
                source_environment={"PATH": os.environ.get("PATH", "")},
                process_role="host",
            )
            environment[ENABLE_GUARD_ENV] = ""
            completed = subprocess.run(
                [_repository_python(), "-m", "preflight_switch_probe"],
                cwd=relative_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("MAIN_MODULE_RAN", completed.stdout)
            self.assertIn("preflight startup guard installation failed closed", completed.stderr)

    def test_guarded_environment_rejects_non_tmp_and_absolute_sandbox_paths(self) -> None:
        for unsafe_root in ("scripts", "tmp/../scripts", str(PROJECT_ROOT / "tmp")):
            with self.subTest(unsafe_root=unsafe_root):
                with self.assertRaisesRegex(SafetyConfigurationError, "project-relative under tmp"):
                    build_guarded_sandbox_environment(
                        unsafe_root,
                        project_root=PROJECT_ROOT,
                    )

    def test_startup_canary_rejects_command_and_environment_identity_drift(self) -> None:
        environment = build_guarded_environment(
            {"PATH": os.environ.get("PATH", "")},
            project_root=PROJECT_ROOT,
            process_role="host",
        )
        command = [_repository_python(), "-c", "pass"]
        _validate_canary_launch(command, str(PROJECT_ROOT), environment)

        with self.assertRaisesRegex(NetworkGuardError, "launch identity is invalid"):
            _validate_canary_launch(
                [getattr(sys, "_base_executable", sys.executable), "-c", "pass"],
                str(PROJECT_ROOT),
                environment,
            )

        altered_environment = dict(environment)
        altered_environment["PYTHONPATH"] = str(PROJECT_ROOT)
        with self.assertRaisesRegex(NetworkGuardError, "launch identity is invalid"):
            _validate_canary_launch(command, str(PROJECT_ROOT), altered_environment)

        with self.assertRaisesRegex(NetworkGuardError, "disables sitecustomize"):
            _validate_canary_launch(
                [_repository_python(), "-S", "-c", "pass"],
                str(PROJECT_ROOT),
                environment,
            )

    def test_exact_startup_process_canary_exits_before_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="preflight-process-canary-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            expected_cwd = str(Path(temporary_root).resolve())
            relative_root = Path(temporary_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            environment = build_guarded_sandbox_environment(
                relative_root,
                project_root=PROJECT_ROOT,
                source_environment={"PATH": os.environ.get("PATH", "")},
                process_role="parent",
            )
            command = [
                _repository_python(),
                str(Path(__file__).resolve()),
                "--startup-canary-probe",
            ]
            completed = subprocess.run(
                command,
                cwd=relative_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["process_role"], "parent")
        self.assertEqual(report["command"], command)
        self.assertEqual(report["working_directory"], expected_cwd)
        self.assertGreater(report["pid"], 0)
        self.assertGreater(report["startup_observed_at_ns"], 0)
        self.assertRegex(report["command_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(report["environment_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(report["guard_active"])
        self.assertTrue(report["non_loopback_connect_denied"])
        self.assertTrue(report["subprocess_launch_denied"])
        self.assertEqual(report["interpreter"]["executable"], _repository_python())
        self.assertEqual(report["interpreter"]["prefix"], str(PROJECT_ROOT / ".venv"))
        self.assertNotEqual(
            report["interpreter"]["prefix"], report["interpreter"]["base_prefix"]
        )
        self.assertNotIn("STARTUP_CANARY_ENTRYPOINT_RAN", completed.stdout)

    def test_startup_canary_digest_binds_runtime_injected_environment_values(self) -> None:
        environment = {"PYTHONPATH": expected_guarded_pythonpath()}
        runtime_environment = {
            "LC_CTYPE": "C.UTF-8",
            "__CF_USER_TEXT_ENCODING": "0x1F5:0:0",
        }

        digest = _startup_canary_environment_digest(
            environment, runtime_environment=runtime_environment
        )
        self.assertEqual(
            digest,
            _startup_environment_digest({**environment, **runtime_environment}),
        )
        self.assertNotEqual(
            digest,
            _startup_canary_environment_digest(
                environment,
                runtime_environment={**runtime_environment, "LC_CTYPE": "C"},
            ),
        )
        explicit_environment = {**environment, "LC_CTYPE": "explicit-locale"}
        self.assertEqual(
            _startup_canary_environment_digest(
                explicit_environment, runtime_environment=runtime_environment
            ),
            _startup_environment_digest(
                {
                    **explicit_environment,
                    "__CF_USER_TEXT_ENCODING": runtime_environment[
                        "__CF_USER_TEXT_ENCODING"
                    ],
                }
            ),
        )

    def test_actual_host_command_prelaunch_canary_exits_before_worker_entrypoint(
        self,
    ) -> None:
        sandbox = PROJECT_ROOT / "tmp" / "combat_capture"
        run_id = "canary-e01-p1"
        run_directory = (
            PROJECT_ROOT
            / "tmp/router-rollout/live-gate-preflight/profile-characterization"
            / run_id
        )
        self.assertTrue(sandbox.is_dir())
        self.assertFalse(run_directory.exists())

        host_command = profile_runner._host_command(
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            source_sha="8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624",
            run_id=run_id,
            planned_row_id="E01",
            arm="A",
            lifecycle_id="canary-e01-p1_s",
            resume_checkpoint_sha256=None,
        )
        self.assertEqual(
            host_command,
            [
                _repository_python(),
                "-P",
                "-m",
                "scripts.live_gate_preflight_profile_runner",
                "--worker",
                "--fixture-id",
                "interior_tavern",
                "--party-size",
                "1",
                "--lifecycle",
                "startup",
                "--source-sha",
                "8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624",
                "--run-id",
                run_id,
                "--planned-row-id",
                "E01",
                "--arm",
                "A",
                "--lifecycle-id",
                "canary-e01-p1_s",
            ],
        )
        controller_code = "\n".join(
            (
                "import json",
                "from scripts.live_gate_preflight_safety import _startup_canary_environment_digest, build_guarded_sandbox_environment, run_startup_process_canary",
                "from scripts.live_gate_preflight_profile_runner import CharacterizationError, _validate_startup_canary_record",
                f"command = {host_command!r}",
                "environment = build_guarded_sandbox_environment(",
                "    'tmp/combat_capture',",
                f"    project_root={str(PROJECT_ROOT)!r},",
                "    source_environment={},",
                "    process_role='host',",
                ")",
                f"report = run_startup_process_canary(command=command, cwd={str(sandbox)!r}, env=environment)",
                "expected_environment_sha256 = _startup_canary_environment_digest(environment)",
                f"validated = _validate_startup_canary_record(report, process_role='host', command=command, cwd={str(sandbox)!r}, environment_sha256=expected_environment_sha256)",
                "tampered_environment = dict(environment)",
                "tampered_environment['TMPDIR'] = 'tmp/not-the-launched-environment'",
                "tampered_environment_sha256 = _startup_canary_environment_digest(tampered_environment)",
                "try:",
                f"    _validate_startup_canary_record(report, process_role='host', command=command, cwd={str(sandbox)!r}, environment_sha256=tampered_environment_sha256)",
                "except CharacterizationError as exc:",
                "    tampered_environment_rejected = exc.code == 'startup_canary_report_invalid'",
                "else:",
                "    tampered_environment_rejected = False",
                "print(json.dumps({'command': command, 'report': report, 'expected_environment_sha256': expected_environment_sha256, 'runner_validation': bool(validated), 'tampered_environment_rejected': tampered_environment_rejected}, sort_keys=True))",
            )
        )
        controller_environment = build_guarded_environment(
            source_environment={},
            project_root=PROJECT_ROOT,
            process_role="parent",
        )
        created_parent_directories: list[Path] = []
        parent = run_directory.parent
        while not parent.exists():
            created_parent_directories.append(parent)
            parent = parent.parent
        run_directory.mkdir(parents=True)
        worker_result_path = run_directory / "worker-result.json"
        sentinel = b"startup canary must not enter the worker module\n"
        worker_result_path.write_bytes(sentinel)
        try:
            completed = subprocess.run(
                [_repository_python(), "-c", controller_code],
                cwd=PROJECT_ROOT / "tmp",
                env=controller_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            report = payload["report"]
            self.assertEqual(payload["command"], host_command)
            self.assertEqual(report["process_role"], "host")
            self.assertEqual(report["command"], host_command)
            self.assertEqual(
                report["environment_sha256"],
                payload["expected_environment_sha256"],
            )
            self.assertEqual(report["working_directory"], str(sandbox))
            self.assertGreater(report["startup_observed_at_ns"], 0)
            self.assertTrue(report["guard_active"])
            self.assertTrue(report["non_loopback_connect_denied"])
            self.assertTrue(report["subprocess_launch_denied"])
            self.assertEqual(report["interpreter"]["executable"], _repository_python())
            self.assertEqual(
                report["interpreter"]["prefix"], str(PROJECT_ROOT / ".venv")
            )
            self.assertNotEqual(
                report["interpreter"]["prefix"],
                report["interpreter"]["base_prefix"],
            )
            self.assertTrue(payload["runner_validation"])
            self.assertTrue(payload["tampered_environment_rejected"])
            self.assertEqual(worker_result_path.read_bytes(), sentinel)
        finally:
            shutil.rmtree(run_directory)
            for directory in created_parent_directories:
                directory.rmdir()

    def test_stub_refuses_to_initialize_without_guard(self) -> None:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(PROJECT_ROOT),
        }
        completed = subprocess.run(
            [
                _repository_python(),
                str(Path(__file__).resolve()),
                "--stub-without-guard-probe",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("guard-required", completed.stdout)

    def _run_guarded_test_child(self, mode: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="preflight-test-child-", dir="tmp") as temp_root:
            relative_root = Path(temp_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            environment = build_guarded_sandbox_environment(
                relative_root,
                project_root=PROJECT_ROOT,
                source_environment={"PATH": os.environ.get("PATH", "")},
            )
            completed = subprocess.run(
                [
                    _repository_python(),
                    str(Path(__file__).resolve()),
                    mode,
                ],
                cwd=relative_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr)
            return completed


class TestProfileCharacterizationRunner(unittest.TestCase):
    @staticmethod
    def _lock_record(**overrides: object) -> dict:
        record = profile_runner._build_live_window_lock_record(
            run_id="profile-lock-test",
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            planned_row_id="E01",
            source_sha="a" * 40,
        )
        record.update(overrides)
        return record

    @staticmethod
    def _release_record(record: dict, **overrides: object) -> dict:
        release = {
            **record,
            "event": "released",
            "released_at_utc": profile_runner._format_utc_timestamp(
                datetime.now(timezone.utc)
            ),
            "server_stopped": True,
            "ports_free": {"8360": True, "8370": True},
            "after_teardown_socket_sample_observed": True,
            "after_teardown_socket_pids": [],
            "evidence_path": "tmp/profile-lock-test/profile-evidence.json",
        }
        release.update(overrides)
        return release

    @staticmethod
    def _process_scope(
        *,
        selector: str = "process_group",
        pid: int = 24568,
        process_group_id: int | None = None,
        process_role: str = "host",
        launch_source: str = "host-worker-start-new-session",
    ) -> dict:
        selected_group = pid if process_group_id is None else process_group_id
        return profile_runner._make_process_scope(
            selector=selector,
            pid=pid,
            process_group_id=selected_group,
            process_role=process_role,
            launch_source=launch_source,
            command=[_repository_python(), "-m", "scripts.live_gate_preflight_profile_runner"],
            environment_sha256="a" * 64,
            working_directory="tmp/combat_capture",
        )

    def test_netstat_census_filters_pids_before_endpoint_parsing(self) -> None:
        run_pid = 24568
        foreign_pid = 98765
        run_id = "netstat-filter-test"
        foreign = _netstat_row(
            "tcp4", foreign_pid, "127.0.0.1.8357", "127.0.0.1.50000"
        )
        with mock.patch.object(
            profile_runner,
            "_parse_netstat_endpoint",
            wraps=profile_runner._parse_netstat_endpoint,
        ) as endpoint_parser:
            rows, counts, parseable = profile_runner._parse_netstat_census(
                foreign, run_pids={run_pid}
            )

        self.assertTrue(parseable)
        self.assertEqual(rows, [])
        self.assertEqual(counts["foreign_process_rows"], 1)
        endpoint_parser.assert_not_called()

        tcp_fixture = b"".join(
            (
                b"Active Internet connections\n",
                _netstat_row(
                    "tcp4", run_pid, "*.8360", "*.*", state="LISTEN", process_name="python host"
                ),
                _netstat_row(
                    "tcp6", run_pid, "::1.8360", "::1.51123", process_name="python host worker"
                ),
                _netstat_row(
                    "tcp4", foreign_pid, "127.0.0.1.8357", "127.0.0.1.50000"
                ),
                b"tcp4 0 0 127.0.0.1.8360 127.0.0.1.51124 ESTABLISHED\n",
                _netstat_row("tcp4", 0, "127.0.0.1.8357", "127.0.0.1.50001"),
            )
        )
        udp_fixture = _netstat_row(
            "udp4", run_pid, "127.0.0.1.8370", "*.*", process_name="python host"
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-filter-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            run_id = run_directory.name
            events = [_guard_startup_event(run_pid, run_id)]
            commands: list[list[str]] = []

            def observer(command: list[str], **_kwargs: object) -> object:
                commands.append(command)
                output = tcp_fixture if command[-1] == "tcp" else udp_fixture
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[self._process_scope(pid=run_pid)],
                    guard_events=events,
                )

            sidecar_path = run_directory / "socket-sample-host_ready.json"
            sidecar = sidecar_path.read_bytes()
            evidence = json.loads(sidecar.decode("utf-8"))

        self.assertTrue(sample["observed"])
        self.assertEqual(sample["pids"], [run_pid])
        self.assertEqual(
            commands,
            [
                [profile_runner.NETSTAT_EXECUTABLE, "-anv", "-W", "-p", "tcp"],
                [profile_runner.NETSTAT_EXECUTABLE, "-anv", "-W", "-p", "udp"],
            ],
        )
        self.assertEqual(evidence["aggregate_counts"]["foreign_process_rows"], 1)
        self.assertEqual(evidence["aggregate_counts"]["pid_zero_rows"], 1)
        self.assertEqual(evidence["aggregate_counts"]["unattributed_rows"], 1)
        self.assertEqual({row["pid"] for row in evidence["run_owned_rows"]}, {run_pid})
        self.assertEqual(
            {row["protocol"] for row in evidence["run_owned_rows"]},
            {"tcp4", "tcp6", "udp4"},
        )
        self.assertEqual(
            next(row for row in evidence["run_owned_rows"] if row["protocol"] == "tcp6")["foreign"],
            {"host": "::1", "port": 51123},
        )
        self.assertNotIn(str(foreign_pid).encode("ascii"), sidecar)
        self.assertNotIn(b"8357", sidecar)
        self.assertNotIn(b"python host", sidecar)
        self.assertTrue(all(not item["command_evidence"]["stdout_prefix_base64"] for item in evidence["protocol_samples"]))

    def test_retained_e04_host_ready_and_after_teardown_allow_guarded_controller_time_wait(
        self,
    ) -> None:
        retained_root = (
            PROJECT_ROOT
            / "tmp/router-rollout/live-gate-preflight/profile-characterization"
            / "fr11-e04-p1-startup-01"
        )
        retained_samples = {
            phase: json.loads(
                (retained_root / ("socket-sample-%s.json" % phase)).read_text(
                    encoding="ascii"
                )
            )
            for phase in ("before_host", "host_ready", "after_teardown")
        }
        guard_events = [
            json.loads(line)
            for line in (retained_root / "guard-events.jsonl")
            .read_text(encoding="ascii")
            .splitlines()
        ]
        process_scopes = retained_samples["host_ready"]["process_scopes"]
        scopes_by_source = {
            scope["launch_source"]: scope for scope in process_scopes
        }
        controller_pid = scopes_by_source["controller-startup-canary"]["pid"]
        host_prelaunch_pid = scopes_by_source["host-prelaunch-canary-session"]["pid"]
        host_pid = scopes_by_source["host-worker-start-new-session"]["pid"]

        def census_sample(phase: str) -> dict[str, Any]:
            evidence = retained_samples[phase]
            return {
                "phase": evidence["phase"],
                "port": 8360,
                "observed": evidence["observed"],
                "pids": evidence["pids"],
                "listener_pids": profile_runner._host_ready_listener_pids(
                    evidence["run_owned_rows"]
                ),
                "failure_code": evidence["failure_code"],
            }

        before_host = census_sample("before_host")
        host_ready = census_sample("host_ready")
        after_teardown = census_sample("after_teardown")
        self.assertIn(controller_pid, host_ready["pids"])
        self.assertEqual(host_ready["listener_pids"], [host_pid])
        self.assertEqual(after_teardown["pids"], [controller_pid])
        self.assertEqual(after_teardown["listener_pids"], [])

        self.assertTrue(
            profile_runner._host_ready_listener_is_authorized(
                host_ready,
                host_pid=host_pid,
                guard_events=guard_events,
                expected_run_id="fr11-e04-p1-startup-01",
            )
        )
        self.assertTrue(
            profile_runner._after_teardown_socket_sample_is_clean(
                after_teardown,
                controller_pid=controller_pid,
                guard_events=guard_events,
                expected_run_id="fr11-e04-p1-startup-01",
            )
        )

        census = profile_runner._make_process_census(
            process_canaries=[
                {"canary_stage": "controller-startup", "pid": controller_pid},
                {"canary_stage": "host-prelaunch", "pid": host_prelaunch_pid},
                {"canary_stage": "host-startup", "pid": host_pid},
            ],
            process=types.SimpleNamespace(pid=host_pid),
            driver_exchange={"process_pid": controller_pid},
            socket_pid_samples=[before_host, host_ready, after_teardown],
            process_scopes=process_scopes,
            guard_events=guard_events,
            expected_run_id="fr11-e04-p1-startup-01",
        )
        self.assertTrue(census["guard_events_valid"])
        self.assertEqual(census["uncovered_pids"], [])
        self.assertTrue(census["complete"])

        lingering_host_socket = {
            **after_teardown,
            "pids": sorted([controller_pid, host_pid]),
        }
        self.assertFalse(
            profile_runner._after_teardown_socket_sample_is_clean(
                lingering_host_socket,
                controller_pid=controller_pid,
                guard_events=guard_events,
                expected_run_id="fr11-e04-p1-startup-01",
            )
        )
        lingering_listener = {
            **after_teardown,
            "listener_pids": [controller_pid],
        }
        self.assertFalse(
            profile_runner._after_teardown_socket_sample_is_clean(
                lingering_listener,
                controller_pid=controller_pid,
                guard_events=guard_events,
                expected_run_id="fr11-e04-p1-startup-01",
            )
        )

    def test_host_ready_accepts_guarded_authorized_host_child_listener(self) -> None:
        run_id = "host-child-listener-test"
        host_pid = 24580
        child_pid = 24581
        child_startup = _guard_startup_event(child_pid, run_id, role="host")
        child_startup["process_group_id"] = host_pid
        guard_events = [
            _guard_startup_event(host_pid, run_id, role="host"),
            _guard_child_started_event(
                host_pid,
                child_pid,
                run_id,
                process_role="host",
                process_group_id=host_pid,
            ),
            child_startup,
        ]
        sample = {
            "phase": "host_ready",
            "port": 8360,
            "observed": True,
            "pids": [child_pid],
            "listener_pids": [child_pid],
            "failure_code": None,
        }

        self.assertTrue(
            profile_runner._host_ready_listener_is_authorized(
                sample,
                host_pid=host_pid,
                guard_events=guard_events,
                expected_run_id=run_id,
            )
        )

    def test_host_ready_rejects_absent_foreign_wrong_unguarded_and_malformed_listeners(
        self,
    ) -> None:
        host_pid = 24582
        controller_pid = 24583
        foreign_pid = 98767
        unguarded_child_pid = 24584

        def observe(
            tcp_fixture: bytes,
            *,
            include_controller: bool = False,
            include_unguarded_child: bool = False,
        ) -> tuple[dict, list[dict], str]:
            with tempfile.TemporaryDirectory(
                prefix="profile-host-ready-negative-", dir=PROJECT_ROOT / "tmp"
            ) as temp_root:
                run_directory = Path(temp_root)
                run_id = run_directory.name
                guard_events = [_guard_startup_event(host_pid, run_id, role="host")]
                process_scopes = [self._process_scope(pid=host_pid)]
                if include_controller:
                    guard_events.append(
                        _guard_startup_event(controller_pid, run_id, role="parent")
                    )
                    process_scopes.append(
                        self._process_scope(
                            selector="pid",
                            pid=controller_pid,
                            process_group_id=controller_pid,
                            process_role="parent",
                            launch_source="controller-startup-canary",
                        )
                    )
                if include_unguarded_child:
                    guard_events.append(
                        _guard_child_started_event(
                            host_pid,
                            unguarded_child_pid,
                            run_id,
                            process_role="host",
                            process_group_id=host_pid,
                        )
                    )

                def observer(command: list[str], **_kwargs: object) -> object:
                    output = tcp_fixture if command[-1] == "tcp" else b""
                    return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

                with mock.patch(
                    "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                    side_effect=observer,
                ):
                    sample = profile_runner._socket_pid_sample(
                        "host_ready",
                        run_directory=run_directory,
                        process_scopes=process_scopes,
                        guard_events=guard_events,
                    )
                return sample, guard_events, run_id

        absent, absent_events, absent_run_id = observe(b"")
        self.assertTrue(absent["observed"])
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                absent,
                host_pid=host_pid,
                guard_events=absent_events,
                expected_run_id=absent_run_id,
            )
        )

        wrong_owner, wrong_owner_events, wrong_owner_run_id = observe(
            _netstat_row(
                "tcp4",
                controller_pid,
                "127.0.0.1.8360",
                "*.*",
                state="LISTEN",
                process_name="python controller",
            ),
            include_controller=True,
        )
        self.assertTrue(wrong_owner["observed"])
        self.assertEqual(wrong_owner["listener_pids"], [controller_pid])
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                wrong_owner,
                host_pid=host_pid,
                guard_events=wrong_owner_events,
                expected_run_id=wrong_owner_run_id,
            )
        )

        foreign, foreign_events, foreign_run_id = observe(
            _netstat_row(
                "tcp4",
                foreign_pid,
                "127.0.0.1.8360",
                "*.*",
                state="LISTEN",
                process_name="foreign listener",
            )
        )
        self.assertTrue(foreign["observed"])
        self.assertEqual(foreign["pids"], [])
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                foreign,
                host_pid=host_pid,
                guard_events=foreign_events,
                expected_run_id=foreign_run_id,
            )
        )

        unguarded, unguarded_events, unguarded_run_id = observe(
            _netstat_row(
                "tcp4",
                host_pid,
                "127.0.0.1.8360",
                "*.*",
                state="LISTEN",
            )
            + _netstat_row(
                "tcp4",
                unguarded_child_pid,
                "127.0.0.1.51112",
                "127.0.0.1.51113",
                state="ESTABLISHED",
            ),
            include_unguarded_child=True,
        )
        self.assertFalse(unguarded["observed"])
        self.assertEqual(
            unguarded["failure_code"], "socket_owner_missing_guard_startup_event"
        )
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                unguarded,
                host_pid=host_pid,
                guard_events=unguarded_events,
                expected_run_id=unguarded_run_id,
            )
        )

        malformed, malformed_events, malformed_run_id = observe(
            _netstat_row(
                "tcp4",
                host_pid,
                "not-an-endpoint",
                "*.*",
                state="LISTEN",
            )
        )
        self.assertFalse(malformed["observed"])
        self.assertEqual(malformed["failure_code"], "netstat_run_pid_row_malformed")
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                malformed,
                host_pid=host_pid,
                guard_events=malformed_events,
                expected_run_id=malformed_run_id,
            )
        )

    def test_netstat_census_accepts_macos_owner_fields_after_required_triplet(self) -> None:
        run_pid = 98085
        tcp_row = (
            b"tcp4       0      0  127.0.0.1.55674        *.*                    "
            b"LISTEN                 0            0  131072  131072           "
            b"Python:98085  00000 00000002 0000000001c65a53 00000000 00000800 "
            b"     1      0 000000\n"
        )
        udp_row = (
            b"udp4 0 0 127.0.0.1.55674 *.* 0 0 131072 131072 Python:98085 "
            b"00000 00000002 0000000001c65a53 00000000 00000800 1 0 000000\n"
        )

        rows, counts, parseable = profile_runner._parse_netstat_census(
            tcp_row + udp_row, run_pids={run_pid}
        )

        self.assertTrue(parseable)
        self.assertEqual(counts["run_pid_rows"], 2)
        self.assertEqual(counts["malformed_run_pid_rows"], 0)
        self.assertEqual(
            [(row["protocol"], row["pid"], row["local"]) for row in rows],
            [
                ("tcp4", run_pid, {"host": "127.0.0.1", "port": 55674}),
                ("udp4", run_pid, {"host": "127.0.0.1", "port": 55674}),
            ],
        )
        self.assertEqual(rows[0]["state"], "LISTEN")
        self.assertIsNone(rows[1]["state"])

    def test_netstat_fails_closed_on_unrecorded_non_loopback_foreign_endpoint(self) -> None:
        run_pid = 24569
        fixture = _netstat_row(
            "tcp4", run_pid, "192.0.2.10.51111", "203.0.113.19.443"
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-unrecorded-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            events = [_guard_startup_event(run_pid, run_directory.name)]

            def observer(command: list[str], **_kwargs: object) -> object:
                output = fixture if command[-1] == "tcp" else b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[self._process_scope(pid=run_pid)],
                    guard_events=events,
                )
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(evidence["failure_code"], "unguarded_non_loopback_socket")
        self.assertEqual(evidence["run_owned_rows"][0]["foreign"], {
            "host": "203.0.113.19",
            "port": 443,
        })

    def test_netstat_fails_closed_when_run_socket_pid_has_no_startup_event(self) -> None:
        parent_pid = 24570
        child_pid = 24571
        fixture = _netstat_row(
            "tcp4", child_pid, "127.0.0.1.8360", "127.0.0.1.51112"
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-no-startup-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            events = [
                _guard_startup_event(parent_pid, run_directory.name, role="parent"),
                _guard_child_started_event(parent_pid, child_pid, run_directory.name),
            ]

            def observer(command: list[str], **_kwargs: object) -> object:
                output = fixture if command[-1] == "tcp" else b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[
                        self._process_scope(
                            selector="pid",
                            pid=parent_pid,
                            process_group_id=parent_pid,
                            process_role="parent",
                            launch_source="controller-startup-canary",
                        )
                    ],
                    guard_events=events,
                )
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(
            evidence["failure_code"], "socket_owner_missing_guard_startup_event"
        )
        self.assertEqual(evidence["pids"], [child_pid])

    def test_netstat_fails_closed_on_malformed_run_pid_row(self) -> None:
        run_pid = 24572
        malformed = b"tcp4 0 0 not-an-endpoint 127.0.0.1.51112 ESTABLISHED python worker:%d 00000 00000000 0000000000000000\n" % run_pid
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-malformed-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            events = [_guard_startup_event(run_pid, run_directory.name)]

            def observer(command: list[str], **_kwargs: object) -> object:
                output = malformed if command[-1] == "tcp" else b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[self._process_scope(pid=run_pid)],
                    guard_events=events,
                )
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(evidence["failure_code"], "netstat_run_pid_row_malformed")
        self.assertEqual(evidence["aggregate_counts"]["malformed_run_pid_rows"], 1)

    def test_netstat_fails_closed_on_malformed_run_pid_owner_suffix(self) -> None:
        run_pid = 24573
        malformed = (
            b"tcp4 0 0 not-an-endpoint 127.0.0.1.51112 ESTABLISHED "
            b"python worker:%d 00000 00000000\n" % run_pid
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-malformed-owner-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            events = [_guard_startup_event(run_pid, run_directory.name)]

            def observer(command: list[str], **_kwargs: object) -> object:
                output = malformed if command[-1] == "tcp" else b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[self._process_scope(pid=run_pid)],
                    guard_events=events,
                )
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(evidence["failure_code"], "netstat_run_pid_row_malformed")
        self.assertEqual(evidence["aggregate_counts"]["run_pid_rows"], 1)
        self.assertEqual(evidence["aggregate_counts"]["malformed_run_pid_rows"], 1)

    def test_netstat_fails_closed_on_nonfield_owner_trailing_suffix(self) -> None:
        run_pid = 24574
        malformed = (
            b"tcp4 0 0 127.0.0.1.8360 *.* LISTEN Python worker:%d "
            b"00000 00000002 0000000001c65a53 00000000 00000800 not-a-field\n"
            % run_pid
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-netstat-malformed-owner-tail-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            events = [_guard_startup_event(run_pid, run_directory.name)]

            def observer(command: list[str], **_kwargs: object) -> object:
                output = malformed if command[-1] == "tcp" else b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

            with mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=observer,
            ):
                sample = profile_runner._socket_pid_sample(
                    "host_ready",
                    run_directory=run_directory,
                    process_scopes=[self._process_scope(pid=run_pid)],
                    guard_events=events,
                )
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(evidence["failure_code"], "netstat_run_pid_row_malformed")
        self.assertEqual(evidence["aggregate_counts"]["run_pid_rows"], 1)
        self.assertEqual(evidence["aggregate_counts"]["malformed_run_pid_rows"], 1)

    def test_malformed_foreign_netstat_owner_is_filtered_before_endpoints(self) -> None:
        foreign_pid = 98766
        fixture = (
            b"tcp4 0 0 invalid-local invalid-foreign ESTABLISHED "
            b"foreign worker:%d 00000\n" % foreign_pid
        )
        with mock.patch.object(
            profile_runner,
            "_parse_netstat_endpoint",
            wraps=profile_runner._parse_netstat_endpoint,
        ) as endpoint_parser:
            rows, counts, parseable = profile_runner._parse_netstat_census(
                fixture, run_pids={24573}
            )

        self.assertTrue(parseable)
        self.assertEqual(rows, [])
        self.assertEqual(counts["foreign_process_rows"], 1)
        endpoint_parser.assert_not_called()

    def test_required_port_checks_use_exclusive_loopback_bind_without_reuse(self) -> None:
        probes = [mock.MagicMock(), mock.MagicMock()]
        for probe in probes:
            probe.__enter__.return_value = probe
            probe.__exit__.return_value = False

        with mock.patch.object(
            profile_runner.socket, "socket", side_effect=probes
        ) as socket_factory, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess"
        ) as observer:
            status = profile_runner._required_port_status()

        self.assertEqual(status, {8360: True, 8370: True})
        self.assertEqual(
            socket_factory.call_args_list,
            [
                mock.call(socket.AF_INET, socket.SOCK_STREAM),
                mock.call(socket.AF_INET, socket.SOCK_STREAM),
            ],
        )
        for probe, port in zip(probes, profile_runner.REQUIRED_PORTS):
            probe.setsockopt.assert_called_once_with(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 0
            )
            probe.bind.assert_called_once_with(("127.0.0.1", port))
            probe.__exit__.assert_called_once()
        observer.assert_not_called()

    def test_required_port_checks_treat_eaddrinuse_as_occupied(self) -> None:
        probes = [mock.MagicMock(), mock.MagicMock()]
        for probe in probes:
            probe.__enter__.return_value = probe
            probe.__exit__.return_value = False
        probes[0].bind.side_effect = OSError(errno.EADDRINUSE, "address in use")

        with mock.patch.object(profile_runner.socket, "socket", side_effect=probes):
            status = profile_runner._required_port_status()

        self.assertEqual(status, {8360: False, 8370: True})
        self.assertEqual(
            profile_runner._port_failure_code(status, "before_start"),
            "port_8360_not_free_before_start",
        )
        probes[0].__exit__.assert_called_once()

    def test_required_port_checks_fail_closed_for_inconclusive_bind_errors(self) -> None:
        probes = [mock.MagicMock(), mock.MagicMock()]
        for probe in probes:
            probe.__enter__.return_value = probe
            probe.__exit__.return_value = False
        probes[0].bind.side_effect = OSError(errno.EACCES, "bind denied")
        probes[1].bind.side_effect = OSError("unexpected bind failure")

        with mock.patch.object(profile_runner.socket, "socket", side_effect=probes):
            status = profile_runner._required_port_status()

        self.assertEqual(status, {8360: False, 8370: False})
        self.assertEqual(
            profile_runner._port_failure_code(status, "after_teardown"),
            "port_8360_not_free_after_teardown",
        )
        with mock.patch.object(profile_runner.socket, "socket") as socket_factory:
            self.assertFalse(profile_runner._port_is_free(8361))
        socket_factory.assert_not_called()

    def _obsolete_lsof_test_sanitized_environment_observer_sees_only_own_loopback_socket(self) -> None:
        self.assertTrue(Path(profile_runner.LSOF_EXECUTABLE).is_file())
        with tempfile.TemporaryDirectory(
            prefix="profile-actual-lsof-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = Path(temp_root)
            environment = build_guarded_environment(
                {"PATH": "/usr/bin:/bin"},
                project_root=PROJECT_ROOT,
                process_role="parent",
            )
            completed = subprocess.run(
                [
                    _repository_python(),
                    str(Path(__file__).resolve()),
                    "--lsof-process-scope-probe",
                    str(run_directory),
                ],
                cwd="tmp",
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )

            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["path"], "/usr/bin:/bin")
            self.assertTrue(payload["sample"]["observed"])
            self.assertEqual(payload["sample"]["pids"], [payload["pid"]])
            evidence = json.loads(
                (run_directory / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )
            command = evidence["owner_mappings"][0]["command_evidence"]["command"]
            self.assertEqual(command[0], profile_runner.LSOF_EXECUTABLE)
            self.assertIn("-w", command)
            self.assertIn(str(payload["pid"]), command)
            self.assertIn("-a", command)
            self.assertNotIn("shell", command)

    def _obsolete_lsof_test_socket_sample_maps_non_8360_socket_with_exact_process_group_scope(self) -> None:
        owner_pid = 24568
        lsof_output = (
            b"p24568\0g24568\0f12u\0tIPv4\0"
            b"n127.0.0.1:8361->127.0.0.1:51123\0\n"
        )
        commands: list[list[str]] = []

        def observer(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            return types.SimpleNamespace(returncode=0, stdout=lsof_output, stderr=b"")

        with tempfile.TemporaryDirectory(
            prefix="profile-non-listening-socket-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope()],
            )
            evidence = json.loads(
                (Path(temp_root) / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )
            sidecar_bytes = (
                Path(temp_root) / "socket-sample-host_ready.json"
            ).read_bytes()

        self.assertTrue(sample["observed"])
        self.assertEqual(sample["pids"], [owner_pid])
        self.assertEqual(len(commands), 1)
        self.assertEqual(
            commands[0],
            [
                profile_runner.LSOF_EXECUTABLE,
                "-w",
                "-nP",
                "-g",
                str(owner_pid),
                "-i",
                "-a",
                "-F0pfgtn",
            ],
        )
        self.assertIn(owner_pid, evidence["pids"])
        self.assertEqual(evidence["owner_mappings"][0]["socket_count"], 1)
        command_evidence = evidence["owner_mappings"][0]["command_evidence"]
        self.assertEqual(command_evidence["stdout_prefix_base64"], "")
        self.assertNotIn(b"8361", sidecar_bytes)

    def _obsolete_lsof_test_socket_sample_checks_pid_and_process_group_identity(self) -> None:
        controller_pid = 31001
        controller_pgid = 30000
        command = [
            profile_runner.LSOF_EXECUTABLE,
            "-w",
            "-nP",
            "-p",
            str(controller_pid),
            "-i",
            "-a",
            "-F0pfgtn",
        ]
        commands: list[list[str]] = []

        def observer(actual_command: list[str], **_kwargs: object) -> object:
            commands.append(actual_command)
            return types.SimpleNamespace(
                returncode=0,
                stdout=(
                    b"p31001\0g30000\0f12u\0tIPv4\0"
                    b"n127.0.0.1:8361->127.0.0.1:51123\0\n"
                ),
                stderr=b"",
            )

        scope = self._process_scope(
            selector="pid",
            pid=controller_pid,
            process_group_id=controller_pgid,
            process_role="parent",
            launch_source="controller-startup-canary",
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-pid-group-intersection-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[scope],
            )

        self.assertEqual(commands, [command])
        self.assertTrue(sample["observed"])
        self.assertEqual(sample["pids"], [controller_pid])

    def _obsolete_lsof_test_socket_sample_fails_closed_when_owner_record_is_incomplete(self) -> None:
        def observer(command: list[str], **_kwargs: object) -> object:
            return types.SimpleNamespace(
                returncode=0,
                stdout=b"p24569\0f12u\0n127.0.0.1:8360\0",
                stderr=b"",
            )

        with tempfile.TemporaryDirectory(
            prefix="profile-owner-map-incomplete-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope(pid=24569)],
            )
            evidence = json.loads(
                (Path(temp_root) / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        self.assertEqual(sample["pids"], [])
        self.assertFalse(evidence["owner_mappings"][0]["ownership_parseable"])
        self.assertEqual(evidence["failure_code"], "socket_owner_mapping_incomplete")

    def _obsolete_lsof_test_socket_sample_bounds_retained_raw_output_and_fails_closed_on_truncation(self) -> None:
        def observer(command: list[str], **_kwargs: object) -> object:
            output = (
                b"p24570\0g24570\0f12u\0tIPv4\0n*:"
                + b"9" * 16
                + b":8361\0"
            )
            return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

        with tempfile.TemporaryDirectory(
            prefix="profile-socket-output-bound-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch.object(
            profile_runner, "MAX_OBSERVER_OUTPUT_BYTES", 8
        ), mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope(pid=24570)],
            )
            evidence = json.loads(
                (Path(temp_root) / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(sample["observed"])
        command_evidence = evidence["owner_mappings"][0]["command_evidence"]
        self.assertTrue(command_evidence["stdout_truncated"])
        self.assertEqual(command_evidence["stdout_prefix_base64"], "")
        self.assertEqual(evidence["pids"], [])

    def _obsolete_lsof_test_socket_sample_with_unguarded_owner_fails_process_census(self) -> None:
        controller_pid = 10001
        host_prelaunch_pid = 10002
        host_worker_pid = 10003
        unguarded_pid = 10004
        lsof_output = (
            b"p10003\0g10003\0f12u\0tIPv4\0"
            b"n127.0.0.1:8360->127.0.0.1:51001\0\n"
            b"p10004\0g10003\0f13u\0tIPv4\0"
            b"n127.0.0.1:8361->127.0.0.1:51002\0\n"
        )

        def observer(command: list[str], **_kwargs: object) -> object:
            return types.SimpleNamespace(returncode=0, stdout=lsof_output, stderr=b"")

        with tempfile.TemporaryDirectory(
            prefix="profile-unguarded-owner-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            host_sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[
                    self._process_scope(pid=host_worker_pid),
                ],
            )

        process_scopes = [
            self._process_scope(
                selector="pid",
                pid=controller_pid,
                process_group_id=9000,
                process_role="parent",
                launch_source="controller-startup-canary",
            ),
            self._process_scope(
                pid=host_prelaunch_pid,
                launch_source="host-prelaunch-canary-session",
            ),
            self._process_scope(pid=host_worker_pid),
        ]
        census = profile_runner._make_process_census(
            process_canaries=[
                {"canary_stage": "controller-startup", "pid": controller_pid},
                {"canary_stage": "host-prelaunch", "pid": host_prelaunch_pid},
                {"canary_stage": "host-startup", "pid": host_worker_pid},
            ],
            process=types.SimpleNamespace(pid=host_worker_pid),
            driver_exchange={"process_pid": controller_pid},
            socket_pid_samples=[
                {"phase": "before_host", "port": 8360, "observed": True, "pids": []},
                host_sample,
                {"phase": "after_teardown", "port": 8360, "observed": True, "pids": []},
            ],
            process_scopes=process_scopes,
        )
        self.assertEqual(host_sample["pids"], [host_worker_pid, unguarded_pid])
        self.assertEqual(census["uncovered_pids"], [unguarded_pid])
        self.assertFalse(census["complete"])

    def _obsolete_lsof_test_socket_sample_requests_only_owned_group_and_persists_no_socket_names(self) -> None:
        target_pid = 10200
        lsof_output = (
            b"p10200\0g10200\0f12u\0tIPv6\0"
            b"n[::1]:8360->[::1]:51123\0\n"
        )
        commands: list[list[str]] = []
        expected_command = [
            profile_runner.LSOF_EXECUTABLE,
            "-w",
            "-nP",
            "-g",
            "10200",
            "-i",
            "-a",
            "-F0pfgtn",
        ]

        def observer(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            self.assertEqual(command, expected_command)
            self.assertNotIn("8357", command)
            self.assertNotIn("10201", command)
            return types.SimpleNamespace(returncode=0, stdout=lsof_output, stderr=b"")

        with tempfile.TemporaryDirectory(
            prefix="profile-forbidden-unrelated-port-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope(pid=target_pid)],
            )
            sidecar_path = Path(temp_root) / "socket-sample-host_ready.json"
            sidecar_bytes = sidecar_path.read_bytes()
            evidence = json.loads(sidecar_bytes.decode("utf-8"))

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0], expected_command)
        self.assertEqual(sample["pids"], [target_pid])
        self.assertTrue(sample["observed"])
        self.assertIsNone(evidence["failure_code"])
        self.assertEqual(evidence["pids"], [target_pid])
        self.assertEqual(
            evidence["owner_mappings"][0]["pids"],
            [target_pid],
        )
        self.assertTrue(evidence["owner_mappings"][0]["scope_valid"])
        self.assertNotIn(b"8357", sidecar_bytes)
        self.assertNotIn(b"10201", sidecar_bytes)
        self.assertNotIn(b"n[::1]", sidecar_bytes)
        self.assertNotIn(b"51123", sidecar_bytes)

    def _obsolete_lsof_test_socket_sample_rejects_and_scrubs_out_of_scope_8357_record(self) -> None:
        output = (
            b"p10201\0g10201\0f13u\0tIPv4\0"
            b"n127.0.0.1:8357->127.0.0.1:51124\0\n"
        )
        commands: list[list[str]] = []

        def observer(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            self.assertIn("-g", command)
            self.assertIn("10200", command)
            self.assertIn("-a", command)
            self.assertNotIn("8357", command)
            return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")

        with tempfile.TemporaryDirectory(
            prefix="profile-out-of-scope-observer-record-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope(pid=10200)],
            )
            sidecar_bytes = (
                Path(temp_root) / "socket-sample-host_ready.json"
            ).read_bytes()
            evidence = json.loads(sidecar_bytes.decode("utf-8"))

        self.assertEqual(len(commands), 1)
        self.assertFalse(sample["observed"])
        self.assertEqual(sample["pids"], [])
        self.assertEqual(evidence["failure_code"], "socket_observer_scope_violation")
        self.assertEqual(evidence["pids"], [])
        self.assertNotIn(b"8357", sidecar_bytes)
        self.assertNotIn(b"10201", sidecar_bytes)

    def _obsolete_lsof_test_socket_sample_rejects_unknown_scope_before_observing(self) -> None:
        scope = self._process_scope()
        scope["process_group_id"] = 99999
        observer = mock.Mock(side_effect=AssertionError("unknown groups cannot be queried"))
        with tempfile.TemporaryDirectory(
            prefix="profile-unknown-scope-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            observer,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[scope],
            )
            evidence = json.loads(
                (Path(temp_root) / "socket-sample-host_ready.json").read_text(
                    encoding="utf-8"
                )
            )
        observer.assert_not_called()
        self.assertFalse(sample["observed"])
        self.assertEqual(evidence["failure_code"], "process_scope_identity_invalid")

    def _obsolete_lsof_test_socket_sample_timeout_fails_closed_without_retaining_partial_output(self) -> None:
        def timeout(command: list[str], **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(command, 3, output=b"p10200\0g10200")

        with tempfile.TemporaryDirectory(
            prefix="profile-observer-timeout-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root, mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=timeout,
        ):
            sample = profile_runner._socket_pid_sample(
                "host_ready",
                run_directory=Path(temp_root),
                process_scopes=[self._process_scope(pid=10200)],
            )
            sidecar_bytes = (
                Path(temp_root) / "socket-sample-host_ready.json"
            ).read_bytes()
            evidence = json.loads(sidecar_bytes.decode("utf-8"))
        self.assertFalse(sample["observed"])
        self.assertEqual(sample["pids"], [])
        self.assertEqual(evidence["failure_code"], "socket_owner_observation_incomplete")
        self.assertNotIn(b"p10200", sidecar_bytes)
        self.assertNotIn(b"g10200", sidecar_bytes)

    def test_repository_venv_identity_rejects_resolved_system_interpreter(self) -> None:
        self.assertEqual(
            _repository_python(),
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        )
        with mock.patch.object(
            profile_runner.sys,
            "executable",
            str(Path(sys.base_prefix) / "bin" / "python"),
        ), mock.patch.object(
            profile_runner.sys, "prefix", sys.base_prefix
        ), mock.patch.object(
            profile_runner.sys, "base_prefix", sys.base_prefix
        ):
            with self.assertRaisesRegex(
                CharacterizationError, "runner_must_use_repository_venv"
            ):
                profile_runner._require_repository_venv()

    def test_startup_canary_record_rejects_pid_invocation_guard_and_venv_drift(self) -> None:
        command = [
            _repository_python(),
            "-P",
            "-m",
            "scripts.live_gate_preflight_profile_runner",
            "--worker",
        ]
        cwd = PROJECT_ROOT / "tmp" / "canary-identity"
        report = {
            "process_role": "host",
            "pid": 12345,
            "startup_observed_at_ns": 100,
            "command": command,
            "command_sha256": hashlib.sha256(
                json.dumps(command, ensure_ascii=True, separators=(",", ":")).encode(
                    "ascii"
                )
            ).hexdigest(),
            "environment_sha256": "a" * 64,
            "working_directory": str(cwd),
            "guard_active": True,
            "non_loopback_connect_denied": True,
            "subprocess_launch_denied": True,
            "interpreter": profile_runner._interpreter_identity(),
        }
        invalid_reports = {
            "pid": {**report, "pid": 12346},
            "command": {**report, "command": [*command, "--changed"]},
            "environment": {**report, "environment_sha256": "b" * 64},
            "working_directory": {**report, "working_directory": str(PROJECT_ROOT)},
            "guard": {**report, "guard_active": False},
            "connect_guard": {**report, "non_loopback_connect_denied": False},
            "subprocess_guard": {**report, "subprocess_launch_denied": False},
        }
        for name, field, value in (
            ("system_executable", "executable", getattr(sys, "_base_executable", "")),
            ("system_prefix", "prefix", sys.base_prefix),
        ):
            invalid_interpreter = dict(report["interpreter"])
            invalid_interpreter[field] = value
            invalid_reports[name] = {**report, "interpreter": invalid_interpreter}

        for name, invalid_report in invalid_reports.items():
            with self.subTest(identity=name):
                with self.assertRaisesRegex(
                    CharacterizationError, "startup_canary_report_invalid"
                ):
                    profile_runner._validate_startup_canary_record(
                        invalid_report,
                        process_role="host",
                        command=command,
                        cwd=cwd,
                        environment_sha256="a" * 64,
                        expected_pid=12345,
                    )

    def test_process_census_rejects_child_pid_without_startup_event(self) -> None:
        controller_pid = 10001
        host_prelaunch_pid = 10002
        host_worker_pid = 10003
        unguarded_child_pid = 10004
        run_id = "census-child-test"
        process_canaries = [
            {"canary_stage": "controller-startup", "pid": controller_pid},
            {"canary_stage": "host-prelaunch", "pid": host_prelaunch_pid},
            {"canary_stage": "host-startup", "pid": host_worker_pid},
        ]
        socket_pid_samples = [
            {"phase": "before_host", "port": 8360, "observed": True, "pids": []},
            {
                "phase": "host_ready",
                "port": 8360,
                "observed": True,
                "pids": [host_worker_pid, unguarded_child_pid],
            },
            {"phase": "after_teardown", "port": 8360, "observed": True, "pids": []},
        ]
        process_scopes = [
            self._process_scope(
                selector="pid",
                pid=controller_pid,
                process_group_id=9000,
                process_role="parent",
                launch_source="controller-startup-canary",
            ),
            self._process_scope(
                pid=host_prelaunch_pid,
                launch_source="host-prelaunch-canary-session",
            ),
            self._process_scope(pid=host_worker_pid),
        ]
        guard_events = [
            _guard_startup_event(controller_pid, run_id, role="parent"),
            _guard_child_started_event(controller_pid, unguarded_child_pid, run_id),
            _guard_startup_event(host_prelaunch_pid, run_id),
            _guard_startup_event(host_worker_pid, run_id),
        ]
        census = profile_runner._make_process_census(
            process_canaries=process_canaries,
            process=types.SimpleNamespace(pid=host_worker_pid),
            driver_exchange={"process_pid": controller_pid},
            socket_pid_samples=socket_pid_samples,
            process_scopes=process_scopes,
            guard_events=guard_events,
            expected_run_id=run_id,
        )
        self.assertEqual(census["uncovered_pids"], [unguarded_child_pid])
        self.assertFalse(census["complete"])

    def test_process_census_accepts_guarded_controller_child_socket_before_host(
        self,
    ) -> None:
        controller_pid = 10001
        host_prelaunch_pid = 10002
        host_worker_pid = 10003
        child_pid = 10004
        run_id = "census-controller-child-test"
        guard_events = [
            _guard_startup_event(controller_pid, run_id, role="parent"),
            _guard_child_started_event(
                controller_pid,
                child_pid,
                run_id,
                process_role="parent",
                process_group_id=controller_pid,
                sequence=2,
            ),
            _guard_startup_event(
                child_pid,
                run_id,
                role="parent",
                process_group_id=controller_pid,
            ),
            _guard_startup_event(host_prelaunch_pid, run_id, role="host"),
            _guard_startup_event(host_worker_pid, run_id, role="host"),
        ]
        census = profile_runner._make_process_census(
            process_canaries=[
                {"canary_stage": "controller-startup", "pid": controller_pid},
                {"canary_stage": "host-prelaunch", "pid": host_prelaunch_pid},
                {"canary_stage": "host-startup", "pid": host_worker_pid},
            ],
            process=types.SimpleNamespace(pid=host_worker_pid),
            driver_exchange={"process_pid": controller_pid},
            socket_pid_samples=[
                {
                    "phase": "before_host",
                    "port": 8360,
                    "observed": True,
                    "pids": [child_pid],
                    "listener_pids": [],
                    "failure_code": None,
                },
                {
                    "phase": "host_ready",
                    "port": 8360,
                    "observed": True,
                    "pids": [host_worker_pid],
                    "listener_pids": [host_worker_pid],
                    "failure_code": None,
                },
                {
                    "phase": "after_teardown",
                    "port": 8360,
                    "observed": True,
                    "pids": [],
                    "listener_pids": [],
                    "failure_code": None,
                },
            ],
            process_scopes=[
                self._process_scope(
                    selector="pid",
                    pid=controller_pid,
                    process_group_id=controller_pid,
                    process_role="parent",
                    launch_source="controller-startup-canary",
                ),
                self._process_scope(
                    pid=host_prelaunch_pid,
                    launch_source="host-prelaunch-canary-session",
                ),
                self._process_scope(pid=host_worker_pid),
            ],
            guard_events=guard_events,
            expected_run_id=run_id,
        )

        self.assertEqual(census["socket_owner_pids"], [host_worker_pid, child_pid])
        self.assertEqual(census["python_child_pids"], [child_pid])
        self.assertEqual(census["uncovered_pids"], [])
        self.assertTrue(census["complete"])

    def test_sandbox_preparer_is_bound_to_the_declared_source_sha(self) -> None:
        relative = "scripts/live_gate_preflight_sandbox.py"
        self.assertIn(relative, profile_runner._SOURCE_BOUND_FILES)
        source_sha = "a" * 40

        with tempfile.TemporaryDirectory(
            prefix="profile-source-binding-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            committed: dict[str, bytes] = {}
            for source_path in profile_runner._SOURCE_BOUND_FILES:
                path = project / source_path
                path.parent.mkdir(parents=True, exist_ok=True)
                committed[source_path] = ("committed:" + source_path).encode("ascii")
                path.write_bytes(committed[source_path])
            (project / relative).write_bytes(b"changed preparer bytes")
            (project / ".venv" / "bin").mkdir(parents=True)
            (project / ".venv" / "bin" / "python").write_bytes(b"venv sentinel")
            shown_sources: list[str] = []

            def fake_git(command: list[str], **_kwargs: object) -> types.SimpleNamespace:
                if command[:3] == ["git", "diff", "--quiet"]:
                    return types.SimpleNamespace(returncode=0, stdout=b"")
                if command[:2] == ["git", "show"]:
                    identity = command[2]
                    shown_sources.append(identity)
                    _, source_path = identity.split(":", 1)
                    return types.SimpleNamespace(
                        returncode=0,
                        stdout=committed[source_path],
                    )
                raise AssertionError("unexpected git command: %r" % command)

            with mock.patch.object(profile_runner, "PROJECT_ROOT", project), mock.patch.object(
                profile_runner, "_git_output", return_value=source_sha
            ), mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=fake_git,
            ), mock.patch.object(profile_runner, "_require_repository_venv"):
                with self.assertRaisesRegex(
                    CharacterizationError, "source_file_differs_from_declared_sha"
                ):
                    profile_runner._verify_source_identity(source_sha)

            self.assertIn(source_sha + ":" + relative, shown_sources)

    def test_tampered_synthetic_config_blocks_before_worker_launch(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-config-tamper-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            config_path = Path(temp_root) / "config.py"
            config_path.write_bytes(
                sandbox_preparation._SYNTHETIC_CONFIG.encode("ascii") + b"# changed\n"
            )
            args = argparse.Namespace(
                fixture_id="interior_tavern",
                party_size=1,
                lifecycle="startup",
                source_sha="a" * 40,
                run_id="synthetic-config-tamper",
                resume_checkpoint_sha256=None,
            )

            def validate_tampered_config(**_kwargs: object) -> None:
                profile_runner._require_synthetic_sandbox_config(config_path)

            with mock.patch.object(
                profile_runner, "_require_safe_project_root", return_value=PROJECT_ROOT
            ), mock.patch.object(
                profile_runner, "_require_parent_startup_guard"
            ), mock.patch.object(
                profile_runner, "_configure_sandbox_import_paths"
            ), mock.patch.object(
                profile_runner, "_install_sandbox_config_guard", return_value=None
            ), mock.patch.object(
                profile_runner, "_verify_source_identity"
            ), mock.patch.object(
                profile_runner,
                "_validate_prepared_sandbox",
                side_effect=validate_tampered_config,
            ), mock.patch.object(profile_runner.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    CharacterizationError,
                    "prepared_sandbox_config_identity_mismatch",
                ):
                    _characterize(args)
            popen.assert_not_called()

    def test_synthetic_config_records_placeholder_and_rejects_realish_key_values(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-config-placeholder-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            config_path = Path(temp_root) / "config.py"
            config_path.write_bytes(sandbox_preparation._SYNTHETIC_CONFIG.encode("ascii"))
            self.assertEqual(
                profile_runner._require_synthetic_sandbox_config(config_path),
                SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            )

            placeholder_assignment = (
                'OPENAI_API_KEY = "%s"' % SANDBOX_PROVIDER_KEY_PLACEHOLDER
            )
            config_path.write_text(
                sandbox_preparation._SYNTHETIC_CONFIG.replace(
                    placeholder_assignment,
                    'OPENAI_API_KEY = "not-a-real-key-but-not-the-approved-placeholder"',
                    1,
                ),
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                CharacterizationError,
                "prepared_sandbox_provider_key_placeholder_invalid",
            ):
                profile_runner._require_synthetic_sandbox_config(config_path)

    def test_parent_without_interpreter_startup_guard_fails_before_host_launch(self) -> None:
        original_sys_path = list(sys.path)
        environment = {
            "NEQ_PREFLIGHT_NETWORK_GUARD": "",
            "NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE": "",
            "NEQ_PREFLIGHT_ENV_SANITIZED": "",
            "NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE": "",
        }
        args = argparse.Namespace(
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            source_sha="a" * 40,
            run_id="guard-required",
            resume_checkpoint_sha256=None,
        )
        with mock.patch.dict(os.environ, environment), mock.patch.dict(
            sys.modules, {"sitecustomize": None}
        ), mock.patch.object(
            profile_runner, "_require_safe_project_root", return_value=PROJECT_ROOT
        ), mock.patch(
            "scripts.live_gate_preflight_profile_runner.subprocess.Popen",
            side_effect=AssertionError("host must not start without the startup guard"),
        ):
            with self.assertRaisesRegex(
                CharacterizationError, "parent_startup_guard_inactive"
            ):
                _characterize(args)
        self.assertEqual(sys.path, original_sys_path)

    def test_parent_launch_requires_guard_path_and_valid_startup_canary(self) -> None:
        runner_path = str(Path(profile_runner.__file__))
        base_arguments = [
            runner_path,
            "--fixture-id",
            "interior_tavern",
            "--party-size",
            "1",
            "--lifecycle",
            "startup",
            "--source-sha",
            "invalid-source-sha",
            "--run-id",
            "parent-canary",
        ]

        with tempfile.TemporaryDirectory(prefix="preflight-parent-good-", dir="tmp") as good_root:
            relative_good = Path(good_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            good_environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                process_role="parent",
            )
            good = subprocess.run(
                [_repository_python(), *base_arguments],
                cwd=relative_good,
                env=good_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(good.returncode, 1)
            self.assertIn("profile_characterization=source_sha_invalid", good.stderr)
            self.assertNotIn("host", good.stderr)

        with tempfile.TemporaryDirectory(prefix="preflight-parent-missing-", dir="tmp") as missing_root:
            relative_missing = Path(missing_root).resolve().relative_to(PROJECT_ROOT).as_posix()
            missing_environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                process_role="parent",
            )
            missing_environment["PYTHONPATH"] = str(PROJECT_ROOT)
            missing = subprocess.run(
                [_repository_python(), *base_arguments],
                cwd=relative_missing,
                env=missing_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn("profile_characterization=parent_startup_guard_inactive", missing.stderr)

    def test_worker_without_startup_guard_fails_before_host_launch(self) -> None:
        run_id = "worker-guard-missing-" + uuid.uuid4().hex[:12]
        evidence_directory = PROJECT_ROOT / profile_runner.PROFILE_EVIDENCE_ROOT / run_id
        evidence_directory.mkdir(parents=True, mode=0o700)
        try:
            with tempfile.TemporaryDirectory(prefix="preflight-worker-missing-", dir="tmp") as worker_root:
                command = profile_runner._host_command(
                    fixture_id="interior_tavern",
                    party_size=1,
                    lifecycle="startup",
                    source_sha="a" * 40,
                    run_id=run_id,
                    planned_row_id="E01",
                    arm="A",
                    lifecycle_id=run_id + "_s",
                    resume_checkpoint_sha256=None,
                )
                environment = build_guarded_environment(
                    {"PATH": os.environ.get("PATH", "")},
                    process_role="host",
                )
                environment["PYTHONPATH"] = str(PROJECT_ROOT)
                completed = subprocess.run(
                    command,
                    cwd=Path(worker_root).resolve().relative_to(PROJECT_ROOT).as_posix(),
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            result = json.loads((evidence_directory / "worker-result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["failure_code"], "host_startup_guard_inactive")
            self.assertEqual(result["outcome"], "failed")
            self.assertEqual(result["calls"], [])
            self.assertFalse(result["server_returned"])
            self.assertEqual(result["interpreter"]["executable"], _repository_python())
            self.assertEqual(result["interpreter"]["prefix"], str(PROJECT_ROOT / ".venv"))
        finally:
            result_path = evidence_directory / "worker-result.json"
            if result_path.exists():
                result_path.unlink()
            evidence_directory.rmdir()

    def test_resolved_system_interpreter_fails_startup_identity_canary(self) -> None:
        system_python = getattr(sys, "_base_executable", "")
        self.assertTrue(system_python)
        self.assertNotEqual(system_python, _repository_python())
        environment = build_guarded_environment(
            {"PATH": os.environ.get("PATH", "")},
            process_role="parent",
        )
        completed = subprocess.run(
            [system_python, "-c", "print('SYSTEM_INTERPRETER_MAIN_RAN')"],
            cwd="tmp",
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("SYSTEM_INTERPRETER_MAIN_RAN", completed.stdout)
        self.assertIn("preflight startup guard installation failed closed", completed.stderr)

    def test_characterization_drives_exchange_after_readiness_and_rejects_incomplete(self) -> None:
        class FakeProcess:
            pid = 12345

            def __init__(self) -> None:
                self.return_code: int | None = None

            def poll(self) -> int | None:
                return self.return_code

        created_locks: list[object] = []

        class FakeLock:
            def __init__(self, _common_directory: Path, record: dict) -> None:
                self.record = dict(record)
                self.release_record: dict | None = None
                self.released = False
                created_locks.append(self)

            def acquire(self) -> bool:
                return True

            def release(self, record: dict) -> bool:
                self.release_record = dict(record)
                self.released = True
                return True

        with tempfile.TemporaryDirectory(
            prefix="profile-parent-flow-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            workspace = Path(temp_root)
            sandbox = workspace / "sandbox"
            sandbox.mkdir()
            (sandbox / "config.py").write_text("", encoding="utf-8")
            evidence_root = workspace / "evidence"
            evidence_root.mkdir()
            events: list[str] = []
            driver_success = {
                "status": "completed",
                "step_id": "E01-01",
                "start_ready": True,
                "active_character_set": True,
                "turn_completed": True,
                "turn_timed_out": False,
                "game_output_count": 1,
                "failure_code": None,
                "process_pid": os.getpid(),
            }
            host_command = [
                _repository_python(),
                "scripts/live_gate_preflight_profile_runner.py",
                "--worker",
            ]
            pythonpath = expected_guarded_pythonpath(PROJECT_ROOT)
            host_environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                process_role="host",
            )

            def canary(
                process_role: str,
                command: list[str],
                cwd: str,
                pid: int,
                environment_sha256: str,
            ) -> dict:
                return {
                    "process_role": process_role,
                    "pid": pid,
                    "startup_observed_at_ns": pid * 1000,
                    "command": command,
                    "command_sha256": hashlib.sha256(
                        json.dumps(command, separators=(",", ":")).encode("ascii")
                    ).hexdigest(),
                    "environment_sha256": environment_sha256,
                    "working_directory": cwd,
                    "guard_active": True,
                    "non_loopback_connect_denied": True,
                    "subprocess_launch_denied": True,
                    "interpreter": profile_runner._interpreter_identity(),
                }

            runner_command = current_invocation_command()
            parent_canary = canary(
                "parent", runner_command, str(Path.cwd()), os.getpid(), "a" * 64
            )
            host_prelaunch_canary = canary(
                "host", host_command, str(sandbox), 24680, "b" * 64
            )
            host_startup_canary = canary(
                "host", host_command, str(sandbox), 12345, "b" * 64
            )
            missing_canary = object()

            def run_characterization(
                run_id: str,
                exchange: dict,
                host_canary_override: object = missing_canary,
            ) -> tuple[dict, list[str], list[int]]:
                run_directory = evidence_root / run_id
                run_directory.mkdir()
                run_guard_events = [
                    _guard_startup_event(
                        os.getpid(),
                        run_id,
                        role="parent",
                        process_group_id=os.getpgrp(),
                    ),
                    _guard_startup_event(24680, run_id),
                    _guard_startup_event(12345, run_id),
                ]
                checked_ports: list[int] = []
                call_result = {
                    "run_id": run_id,
                    "source_sha": "a" * 40,
                    "command": host_command,
                    "pythonpath": pythonpath,
                    "startup_canary_report": json.dumps(host_startup_canary),
                    "interpreter": profile_runner._interpreter_identity(),
                    "guard_active": True,
                    "startup_guard_from_sitecustomize": True,
                    "sandbox_config_origin_guard_active": True,
                    "provider_environment_keys_blank": True,
                    "sandbox_provider_key_placeholder": SANDBOX_PROVIDER_KEY_PLACEHOLDER,
                    "proxy_values_blank": True,
                    "real_project_config_loaded": False,
                    "sandbox_config_loaded": True,
                    "outcome": "completed",
                    "failure_code": None,
                    "call_count": 1,
                    "calls": [
                        {
                            "sequence": 1,
                            "task": "dm_main",
                            "source_file": "scripts/test_live_gate_preflight_profiles.py",
                            "source_line": 1,
                            "source_file_sha256": hashlib.sha256(
                                Path(__file__).read_bytes()
                            ).hexdigest(),
                            "source_sha": "a" * 40,
                            "command": host_command,
                            "pythonpath": pythonpath,
                        }
                    ],
                    "stub_failure_code": None,
                }

                def record_launch(*_args: object, **_kwargs: object) -> FakeProcess:
                    events.append("worker-launch")
                    return FakeProcess()

                def record_stop(process: FakeProcess) -> bool:
                    process.return_code = 0
                    return True

                def record_worker_result(_path: Path) -> dict:
                    request_path = run_directory / "shutdown-request.json"
                    request = (
                        json.loads(request_path.read_text(encoding="utf-8"))
                        if request_path.is_file()
                        else None
                    )
                    shutdown_accepted = (
                        isinstance(request, dict)
                        and request.get("readiness_succeeded") is True
                        and request.get("exchange_succeeded") is True
                    )
                    return {
                        **call_result,
                        "server_returned": True,
                        "interrupted": True,
                        "graceful_shutdown_requested": request is not None,
                        "shutdown_request": request,
                        "shutdown_signal_received_at_ns": (
                            request["requested_at_ns"] + 1
                            if request is not None
                            else None
                        ),
                        "outcome": "completed" if shutdown_accepted else "failed",
                        "failure_code": (
                            None
                            if shutdown_accepted
                            else "host_shutdown_prerequisites_not_met"
                        ),
                    }

                def record_ready(*_args: object, **_kwargs: object) -> bool:
                    events.append("listener-ready")
                    return True

                def record_exchange(**_kwargs: object) -> dict:
                    events.append("driver-exchange")
                    return exchange

                def record_socket_sample(phase: str, **_kwargs: object) -> dict:
                    return {
                        "phase": phase,
                        "port": 8360,
                        "observed": True,
                        "pids": [12345] if phase == "host_ready" else [],
                        "listener_pids": [12345] if phase == "host_ready" else [],
                        "failure_code": None,
                    }

                def record_port_check(port: int) -> bool:
                    checked_ports.append(port)
                    return True

                with ExitStack() as stack:
                    stack.enter_context(
                        mock.patch.object(
                            profile_runner,
                            "_require_safe_project_root",
                            return_value=PROJECT_ROOT,
                        )
                    )
                    stack.enter_context(
                        mock.patch.object(profile_runner, "_require_parent_startup_guard")
                    )
                    stack.enter_context(
                        mock.patch.object(profile_runner, "_verify_source_identity")
                    )
                    stack.enter_context(
                        mock.patch.object(
                            profile_runner,
                            "_validate_prepared_sandbox",
                            return_value=(
                                sandbox,
                                "E01",
                                "A",
                                "interior_tavern:p1",
                                {
                                    "step_id": "E01-01",
                                    "utterance": "Describe the room.",
                                    "character": "PC-One",
                                },
                                SANDBOX_PROVIDER_KEY_PLACEHOLDER,
                            ),
                        )
                    )
                    patches = (
                        mock.patch.object(
                            profile_runner, "_host_command", return_value=host_command
                        ),
                        mock.patch.object(
                            profile_runner, "_git_common_directory", return_value=workspace
                        ),
                        mock.patch.object(
                            profile_runner, "_ProfileCharacterizationLock", FakeLock
                        ),
                        mock.patch.object(
                            profile_runner, "_ensure_run_directory", return_value=run_directory
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety.configure_guard_event_sink"
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_read_guard_events_for_run",
                            return_value=(run_guard_events, b"synthetic guard events\n", True),
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_port_is_free",
                            side_effect=record_port_check,
                        ),
                        mock.patch.object(
                            profile_runner, "_claim_characterization_attempt", return_value=None
                        ),
                        mock.patch.object(
                            profile_runner, "_configure_sandbox_import_paths", return_value=None
                        ),
                        mock.patch.object(
                            profile_runner, "_install_sandbox_config_guard", return_value=None
                        ),
                        mock.patch.object(profile_runner, "_remove_import_guard"),
                        mock.patch.object(
                            profile_runner.subprocess, "Popen", side_effect=record_launch
                        ),
                        mock.patch.object(
                            profile_runner, "_wait_until_ready", side_effect=record_ready
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_drive_profile_exchange",
                            side_effect=record_exchange,
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_stop_owned_process",
                            side_effect=record_stop,
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_read_worker_result",
                            side_effect=record_worker_result,
                        ),
                        mock.patch.dict(
                            os.environ,
                            {
                                "NEQ_PREFLIGHT_STARTUP_CANARY_REPORT": json.dumps(
                                    parent_canary
                                )
                            },
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety._startup_environment_snapshot",
                            return_value={PROCESS_ROLE_ENV: "parent"},
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety._startup_environment_digest",
                            side_effect=lambda selected: (
                                "a" * 64
                                if selected.get(PROCESS_ROLE_ENV) == "parent"
                                else "b" * 64
                            ),
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety.run_startup_process_canary",
                            return_value=(
                                host_prelaunch_canary
                                if host_canary_override is missing_canary
                                else host_canary_override
                            ),
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety.authorize_subprocess_launch",
                            side_effect=lambda *_args, **_kwargs: nullcontext(),
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_write_json",
                            side_effect=lambda path, payload: Path(path).write_text(
                                json.dumps(payload), encoding="utf-8"
                            ),
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_safety.build_guarded_sandbox_environment",
                            return_value=host_environment,
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_socket_pid_sample",
                            side_effect=record_socket_sample,
                        ),
                    )
                    for patcher in patches:
                        stack.enter_context(patcher)
                    args = argparse.Namespace(
                        fixture_id="interior_tavern",
                        party_size=1,
                        lifecycle="startup",
                        source_sha="a" * 40,
                        run_id=run_id,
                        resume_checkpoint_sha256=None,
                    )
                    result = profile_runner._characterize(args)
                    return result[0], list(events), list(checked_ports)

            successful_evidence, successful_events, successful_port_checks = run_characterization(
                "positive-flow", driver_success
            )
            self.assertEqual(
                successful_events,
                ["worker-launch", "listener-ready", "driver-exchange"],
            )
            self.assertEqual(successful_evidence["driver_exchange"], driver_success)
            self.assertEqual(
                successful_evidence["worker_shutdown"]["graceful_shutdown_requested"],
                True,
            )
            self.assertIs(
                successful_evidence["worker_shutdown"]["server_returned"], True
            )
            self.assertTrue(
                successful_evidence["worker_shutdown"]["request"][
                    "readiness_succeeded"
                ]
            )
            self.assertTrue(
                successful_evidence["worker_shutdown"]["request"][
                    "exchange_succeeded"
                ]
            )
            self.assertEqual(
                successful_port_checks,
                [8360, 8370, 8360, 8370, 8360, 8370],
            )
            self.assertTrue(
                profile_runner._valid_live_window_lock_record(created_locks[-1].record)
            )
            self.assertEqual(
                created_locks[-1].release_record["ports_free"],
                {"8360": True, "8370": True},
            )
            self.assertTrue(
                created_locks[-1].release_record["evidence_path"].startswith("tmp/")
            )
            self.assertEqual(
                [
                    canary["canary_stage"]
                    for canary in successful_evidence["process_canaries"]
                ],
                ["controller-startup", "host-prelaunch", "host-startup"],
            )
            failed_exchange = {**driver_success, "status": "failed", "turn_completed": False,
                               "turn_timed_out": True, "game_output_count": 0,
                               "failure_code": "capture_driver_first_exchange_incomplete"}
            with self.assertRaisesRegex(
                CharacterizationError, "capture_driver_first_exchange_incomplete"
            ):
                run_characterization("negative-flow", failed_exchange)

            for run_id, invalid_canary in (
                ("missing-canary", None),
                (
                    "broken-canary",
                    {**host_prelaunch_canary, "subprocess_launch_denied": False},
                ),
            ):
                with self.subTest(canary=run_id):
                    events.clear()
                    with self.assertRaisesRegex(
                        CharacterizationError, "startup_canary_report_invalid"
                    ):
                        run_characterization(
                            run_id,
                            driver_success,
                            host_canary_override=invalid_canary,
                        )
                    self.assertNotIn("worker-launch", events)

    def test_resume_runner_requires_explicit_checkpoint_identity(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args(
                    [
                        "--fixture-id",
                        "interior_tavern",
                        "--party-size",
                        "1",
                        "--lifecycle",
                        "resume",
                        "--source-sha",
                        "a" * 40,
                    ]
                )
        parsed = _parse_args(
            [
                "--fixture-id",
                "interior_tavern",
                "--party-size",
                "1",
                "--lifecycle",
                "resume",
                "--source-sha",
                "a" * 40,
                "--resume-checkpoint-sha256",
                "b" * 64,
            ]
        )
        self.assertEqual(parsed.lifecycle, "resume")

    def test_driver_exchange_requires_start_selection_and_completed_output(self) -> None:
        class FakeDriver:
            def __init__(self, *, completes: bool) -> None:
                self.completes = completes
                self.calls: list[tuple] = []

            def start(self) -> dict:
                self.calls.append(("start",))
                return {"ready": True}

            def set_active_character(self, character: str) -> bool:
                self.calls.append(("character", character))
                return True

            def send_turn(self, step_id: str, utterance: str, character: str) -> dict:
                self.calls.append(("turn", step_id, utterance, character))
                return {
                    "completed": self.completes,
                    "timed_out": not self.completes,
                    "game_output_count": 1 if self.completes else 0,
                }

            def close(self) -> None:
                self.calls.append(("close",))

        successful = FakeDriver(completes=True)
        with mock.patch.object(profile_runner, "_require_parent_startup_guard"):
            result = _drive_profile_exchange(
                party_size=1,
                runtime_root=PROJECT_ROOT / "tmp",
                transcript_path=PROJECT_ROOT / "tmp" / "profile-driver.txt",
                first_turn={
                    "step_id": "E01-01",
                    "utterance": "Describe the room.",
                    "character": "PC-One",
                },
                driver_factory=lambda **_kwargs: successful,
            )
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["turn_completed"])
        self.assertEqual(result["game_output_count"], 1)
        self.assertEqual(successful.calls[-1], ("close",))

        timed_out = FakeDriver(completes=False)
        with mock.patch.object(profile_runner, "_require_parent_startup_guard"):
            failed = _drive_profile_exchange(
                party_size=4,
                runtime_root=PROJECT_ROOT / "tmp",
                transcript_path=PROJECT_ROOT / "tmp" / "profile-driver-failed.txt",
                first_turn={
                    "step_id": "E07-01",
                    "utterance": "Describe the room.",
                    "character": "PC-One",
                },
                driver_factory=lambda **_kwargs: timed_out,
            )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_code"], "capture_driver_first_exchange_incomplete")
        self.assertTrue(failed["turn_timed_out"])
        self.assertEqual(timed_out.calls[-1], ("close",))

    def test_worker_traverses_lifecycle_entrypoint_with_startup_guard_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profile-worker-", dir=PROJECT_ROOT / "tmp") as temp_root:
            sandbox = Path(temp_root).resolve()
            relative_sandbox = sandbox.relative_to(PROJECT_ROOT).as_posix()
            (sandbox / "model_config.py").write_text(
                'TEST_MODEL_SETTING = "synthetic"\n', encoding="ascii"
            )
            (sandbox / "config.py").write_text(
                sandbox_preparation._SYNTHETIC_CONFIG,
                encoding="ascii",
            )
            utils_directory = sandbox / "utils"
            utils_directory.mkdir()
            (utils_directory / "__init__.py").write_text(
                "from pathlib import Path\n"
                "__path__.append(str(Path(%r)))\n" % str(PROJECT_ROOT / "utils"),
                encoding="utf-8",
            )
            (utils_directory / "llm_router.py").write_text(
                "class Router:\n"
                "    def call(self, *args, **kwargs):\n"
                "        raise AssertionError('router stub was not installed')\n"
                "llm = Router()\n",
                encoding="utf-8",
            )
            (utils_directory / "ai_client_factory.py").write_text(
                "factory_calls = []\n"
                "class OpenAIError(RuntimeError):\n"
                "    pass\n"
                "def create_chat_client(*args, **kwargs):\n"
                "    factory_calls.append(True)\n"
                "    raise OpenAIError('synthetic empty-key client construction')\n"
                "ORIGINAL_FACTORY = create_chat_client\n",
                encoding="utf-8",
            )
            probe_directory = sandbox / "mapping_pilot"
            probe_directory.mkdir()
            probe_path = probe_directory / "profile_lifecycle_probe.py"
            probe_path.write_text(
                "def invoke(router, task):\n"
                "    return router.call(task, messages=[], json_output=True)\n",
                encoding="utf-8",
            )

            environment = build_guarded_sandbox_environment(
                relative_sandbox,
                project_root=PROJECT_ROOT,
                source_environment={"PATH": os.environ.get("PATH", "")},
                process_role="host",
            )
            for lifecycle in ("startup", "resume"):
                for outcome in (
                    "caught",
                    "propagated",
                    "reject",
                    "natural",
                    "wrong_request",
                ):
                    with self.subTest(lifecycle=lifecycle, outcome=outcome):
                        completed = subprocess.run(
                            [
                                _repository_python(),
                                str(Path(__file__).resolve()),
                                "--profile-worker-probe",
                                relative_sandbox,
                                lifecycle,
                                outcome,
                            ],
                            cwd=relative_sandbox,
                            env=environment,
                            check=False,
                            capture_output=True,
                            text=True,
                            start_new_session=True,
                            timeout=20,
                        )
                        payload = json.loads(completed.stdout)
                        expected_exit = (
                            0 if outcome in {"caught", "propagated"} else 1
                        )
                        self.assertEqual(
                            completed.returncode,
                            expected_exit,
                            completed.stdout + completed.stderr,
                        )
                        result = payload["worker_result"]
                        self.assertTrue(payload["startup_sitecustomize_verified"])
                        self.assertEqual(payload["entrypoint"]["lifecycle"], lifecycle)
                        self.assertEqual(result["startup_guard_from_sitecustomize"], True)
                        self.assertEqual(result["sandbox_config_origin_guard_active"], True)
                        self.assertEqual(
                            result["sandbox_provider_key_placeholder"],
                            SANDBOX_PROVIDER_KEY_PLACEHOLDER,
                        )
                        self.assertEqual(result["call_count"], 1, completed.stdout)
                        self.assertTrue(
                            payload["entrypoint"]["client_factory_result_is_none"]
                        )
                        self.assertEqual(
                            payload["entrypoint"]["original_factory_calls"], 0
                        )
                        self.assertTrue(
                            payload["entrypoint"]["provider_factory_restored"]
                        )
                        self.assertEqual(
                            result["interpreter"]["executable"], _repository_python()
                        )
                        self.assertEqual(
                            result["interpreter"]["prefix"], str(PROJECT_ROOT / ".venv")
                        )
                        self.assertNotEqual(
                            result["interpreter"]["prefix"],
                            result["interpreter"]["base_prefix"],
                        )
                        if outcome in {"caught", "propagated"}:
                            self.assertEqual(result["outcome"], "completed")
                            self.assertTrue(result["graceful_shutdown_requested"])
                            self.assertTrue(result["interrupted"])
                            self.assertIs(
                                result["server_returned"], outcome == "caught"
                            )
                            self.assertTrue(
                                result["shutdown_request"]["readiness_succeeded"]
                            )
                            self.assertTrue(
                                result["shutdown_request"]["exchange_succeeded"]
                            )
                            if outcome == "caught":
                                self.assertTrue(
                                    payload["entrypoint"][
                                        "server_caught_keyboard_interrupt"
                                    ]
                                )
                                self.assertIsInstance(
                                    result["shutdown_signal_received_at_ns"], int
                                )
                            self.assertEqual(
                                payload["entrypoint"]["stub_response"]["narration"],
                                "The party pauses and takes in the scene.",
                            )
                        elif outcome == "reject":
                            self.assertEqual(result["outcome"], "failed")
                            self.assertEqual(
                                result["stub_failure_code"],
                                "router_task_has_no_stub_response",
                            )
                            self.assertFalse(result["interrupted"])
                            self.assertFalse(result["graceful_shutdown_requested"])
                        elif outcome == "natural":
                            self.assertEqual(result["outcome"], "failed")
                            self.assertTrue(result["server_returned"])
                            self.assertFalse(result["interrupted"])
                            self.assertFalse(result["graceful_shutdown_requested"])
                            self.assertEqual(
                                result["failure_code"],
                                "host_server_returned_without_graceful_shutdown",
                            )
                        else:
                            self.assertEqual(result["outcome"], "failed")
                            self.assertTrue(result["server_returned"])
                            self.assertTrue(result["interrupted"])
                            self.assertFalse(result["graceful_shutdown_requested"])
                            self.assertIsNone(result["shutdown_request"])
                            self.assertEqual(
                                result["failure_code"],
                                "host_interrupt_without_shutdown_request",
                            )

    def test_live_window_lock_contention_preserves_existing_holder_and_log(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-lock-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            common_directory = Path(temp_directory)
            coordination = common_directory / "neq-coordination"
            lock_directory = coordination / "live-window.lock"
            lock_directory.mkdir(parents=True)
            holder_path = lock_directory / "holder.json"
            log_path = coordination / "bookings.log"
            holder_bytes = b'{"booking_id":"other-run"}\n'
            log_bytes = b'{"booking_id":"existing"}\n'
            holder_path.write_bytes(holder_bytes)
            log_path.write_bytes(log_bytes)

            lock = _ProfileCharacterizationLock(
                common_directory,
                self._lock_record(run_id="new-run"),
            )
            self.assertFalse(lock.acquire())
            self.assertEqual(holder_path.read_bytes(), holder_bytes)
            self.assertEqual(log_path.read_bytes(), log_bytes)

    def test_live_window_lock_accepts_shared_readable_directory_only(self) -> None:
        record = self._lock_record(run_id="profile-mode-test")
        real_lstat = Path.lstat
        for mode, expected in ((0o755, True), (0o775, False), (0o757, False)):
            with self.subTest(mode=oct(mode)), tempfile.TemporaryDirectory(
                prefix="profile-lock-mode-", dir=PROJECT_ROOT / "tmp"
            ) as temp_directory:
                common_directory = Path(temp_directory)
                coordination = common_directory / "neq-coordination"
                coordination.mkdir()
                lock = _ProfileCharacterizationLock(common_directory, record)

                def fake_lstat(path: Path) -> os.stat_result:
                    if path == coordination:
                        metadata = real_lstat(path)
                        return types.SimpleNamespace(
                            st_mode=(metadata.st_mode & ~0o777) | mode,
                            st_uid=metadata.st_uid,
                        )
                    return real_lstat(path)

                with mock.patch.object(Path, "lstat", fake_lstat):
                    acquired = lock.acquire()
                    self.assertEqual(acquired, expected)
                    if acquired:
                        self.assertTrue(
                            lock.release(self._release_record(record))
                        )
                self.assertFalse((coordination / "live-window.lock").exists())

    def test_live_window_lock_refuses_symlinked_coordination_directory(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-lock-symlink-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            common_directory = Path(temp_directory)
            target = common_directory / "target"
            target.mkdir()
            (common_directory / "neq-coordination").symlink_to(target, target_is_directory=True)
            lock = _ProfileCharacterizationLock(
                common_directory,
                self._lock_record(run_id="profile-symlink-test"),
            )
            self.assertFalse(lock.acquire())
            self.assertFalse((target / "live-window.lock").exists())

    def test_live_window_lock_records_and_releases_only_its_own_holder(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-lock-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            common_directory = Path(temp_directory)
            record = self._lock_record(run_id="profile-run-1")
            lock = _ProfileCharacterizationLock(common_directory, record)
            self.assertTrue(lock.acquire())
            holder_path = common_directory / "neq-coordination" / "live-window.lock" / "holder.json"
            log_path = common_directory / "neq-coordination" / "bookings.log"
            self.assertTrue(holder_path.is_file())
            booking_line, = log_path.read_text(encoding="utf-8").splitlines()
            holder_line = json.loads(booking_line)
            self.assertEqual(json.loads(holder_path.read_text(encoding="utf-8")), record)
            self.assertEqual(holder_line, record)
            self.assertRegex(
                record["booking_id"],
                r"^live-gate-preflight-N-[0-9]{8}T[0-9]{6}Z$",
            )
            start = profile_runner._parse_utc_timestamp(record["window_start"])
            end = profile_runner._parse_utc_timestamp(record["window_end"])
            self.assertIsNotNone(start)
            self.assertIsNotNone(end)
            self.assertLessEqual((end - start).total_seconds(), 8 * 60 * 60)
            self.assertEqual(record["ports"], [8360, 8370])
            self.assertEqual(record["holder"], "N agent-run")
            self.assertEqual(
                record["authorizing_ruling"],
                "neq-w1-fr11-profiles-characterization-20261112",
            )
            release_record = self._release_record(record)
            self.assertTrue(lock.release(release_record))
            self.assertFalse(holder_path.exists())
            self.assertFalse(holder_path.parent.exists())
            logged_release = json.loads(log_path.read_text(encoding="utf-8").splitlines()[1])
            self.assertEqual(logged_release, release_record)
            self.assertEqual(logged_release["ports_free"], {"8360": True, "8370": True})
            self.assertTrue(logged_release["evidence_path"].startswith("tmp/"))

    def test_live_window_lock_rejects_missing_or_invalid_holder_metadata(self) -> None:
        invalid_records = []
        missing_holder = self._lock_record(run_id="missing-holder")
        del missing_holder["holder"]
        invalid_records.append(missing_holder)
        wrong_ruling = self._lock_record(run_id="wrong-ruling")
        wrong_ruling["authorizing_ruling"] = "unapproved-ruling"
        invalid_records.append(wrong_ruling)
        wrong_ports = self._lock_record(run_id="wrong-ports")
        wrong_ports["ports"] = [8360]
        invalid_records.append(wrong_ports)
        wrong_caps = self._lock_record(run_id="wrong-caps")
        wrong_caps["frozen_caps"] = {"provider_requests": 1}
        invalid_records.append(wrong_caps)
        boolean_caps = self._lock_record(run_id="boolean-caps")
        boolean_caps["frozen_caps"]["provider_requests"] = False
        invalid_records.append(boolean_caps)
        long_window = self._lock_record(run_id="long-window")
        start = profile_runner._parse_utc_timestamp(long_window["window_start"])
        long_window["window_end"] = profile_runner._format_utc_timestamp(
            start + timedelta(hours=9)
        )
        invalid_records.append(long_window)
        malformed_window = self._lock_record(run_id="malformed-window")
        malformed_window["window_end"] = "not-a-utc-timestamp"
        invalid_records.append(malformed_window)

        for index, record in enumerate(invalid_records):
            with self.subTest(index=index), tempfile.TemporaryDirectory(
                prefix="profile-lock-invalid-", dir=PROJECT_ROOT / "tmp"
            ) as temp_directory:
                common_directory = Path(temp_directory)
                lock = _ProfileCharacterizationLock(common_directory, record)
                self.assertFalse(lock.acquire())
                self.assertFalse(
                    (common_directory / "neq-coordination" / "live-window.lock").exists()
                )
                self.assertFalse(
                    (common_directory / "neq-coordination" / "bookings.log").exists()
                )

    def test_live_window_lock_cannot_release_without_both_ports_and_evidence(self) -> None:
        record = self._lock_record(run_id="release-boundary")
        invalid_releases = (
            self._release_record(record, ports_free={"8360": True, "8370": False}),
            self._release_record(record, ports_free={"8360": True}),
            self._release_record(record, after_teardown_socket_sample_observed=False),
            self._release_record(record, after_teardown_socket_pids=[12345]),
            self._release_record(record, evidence_path="/outside/evidence.json"),
        )
        for index, release_record in enumerate(invalid_releases):
            with self.subTest(index=index), tempfile.TemporaryDirectory(
                prefix="profile-lock-release-blocked-", dir=PROJECT_ROOT / "tmp"
            ) as temp_directory:
                common_directory = Path(temp_directory)
                lock = _ProfileCharacterizationLock(common_directory, record)
                self.assertTrue(lock.acquire())
                holder_path = (
                    common_directory
                    / "neq-coordination"
                    / "live-window.lock"
                    / "holder.json"
                )
                log_path = common_directory / "neq-coordination" / "bookings.log"
                self.assertFalse(lock.release(release_record))
                self.assertTrue(holder_path.is_file())
                self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 1)
                self.assertTrue(lock.release(self._release_record(record)))

    def test_live_window_lock_does_not_release_a_replaced_holder(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-lock-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            common_directory = Path(temp_directory)
            record = self._lock_record(run_id="profile-run-2")
            lock = _ProfileCharacterizationLock(common_directory, record)
            self.assertTrue(lock.acquire())
            lock_directory = common_directory / "neq-coordination" / "live-window.lock"
            holder_path = lock_directory / "holder.json"
            replacement = lock_directory / "replacement.json"
            replacement_bytes = holder_path.read_bytes()
            replacement.write_bytes(replacement_bytes)
            holder_path.unlink()
            replacement.replace(holder_path)
            self.assertFalse(lock.release(self._release_record(record)))
            self.assertEqual(holder_path.read_bytes(), replacement_bytes)
            self.assertTrue(lock_directory.is_dir())

    def test_characterization_claim_allows_one_attempt_per_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-attempts-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            evidence_root = Path(temp_directory) / "profile-characterization"
            evidence_root.mkdir()
            first_run = evidence_root / "run-001"
            second_run = evidence_root / "run-002"
            first_run.mkdir()
            second_run.mkdir()
            record = {
                "schema_version": 1,
                "run_id": "run-001",
                "profile_id": "interior_tavern:p1",
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "lifecycle": "startup",
                "planned_row_id": "E01",
                "source_sha": "a" * 40,
                "attempted_at_utc": "2026-11-12T00:00:00+00:00",
            }
            _claim_characterization_attempt(evidence_root, first_run, record)
            duplicate = {**record, "run_id": "run-002"}
            with self.assertRaisesRegex(
                CharacterizationError, "already_attempted"
            ):
                _claim_characterization_attempt(evidence_root, second_run, duplicate)


class TestProfileSandboxPreparation(unittest.TestCase):
    def test_fake_provider_free_sandbox_uses_synthetic_config_without_launch(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size), tempfile.TemporaryDirectory(
                prefix="profile-sandbox-fixture-", dir=PROJECT_ROOT / "tmp"
            ) as temp_root:
                project = Path(temp_root)
                self._make_fake_runtime(project)
                source_config = project / "config.py"
                source_config.write_text(
                    "SOURCE_CONFIG_CANARY = 'source-config-canary'\n", encoding="utf-8"
                )
                plan, modules, expected = self._fake_seed_inputs(party_size)
                config_module_before = sys.modules.get("config")
                original_path_open = Path.open
                original_copy2 = sandbox_preparation.shutil.copy2

                def audited_path_open(path: Path, *args: object, **kwargs: object) -> object:
                    if path == source_config:
                        raise AssertionError("real project config must not be read")
                    return original_path_open(path, *args, **kwargs)

                def audited_copy2(source: object, destination: object, *args: object, **kwargs: object) -> object:
                    if Path(source) == source_config:
                        raise AssertionError("real project config must not be copied")
                    return original_copy2(source, destination, *args, **kwargs)

                with mock.patch.object(Path, "open", audited_path_open), mock.patch.object(
                    sandbox_preparation.shutil, "copy2", audited_copy2
                ), mock.patch("subprocess.Popen") as popen, mock.patch(
                    "subprocess.run"
                ) as run:
                    result = sandbox_preparation._prepare_new_sandbox(
                        project, plan, modules, expected
                    )

                sandbox = project / "tmp" / "combat_capture"
                config_text = (sandbox / "config.py").read_text(encoding="ascii")
                metadata = json.loads(
                    (sandbox / "mapping_pilot" / "seed_metadata.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(result["status"], "prepared")
                self.assertEqual(result["sandbox_root"], "tmp/combat_capture")
                self.assertEqual(result["fixture_id"], "interior_tavern")
                self.assertEqual(result["party_size"], party_size)
                self.assertEqual(result["planned_row_id"], "E01" if party_size == 1 else "E07")
                self.assertEqual(result["config_source"], "synthetic")
                self.assertEqual(
                    result["sandbox_provider_key_placeholder"],
                    SANDBOX_PROVIDER_KEY_PLACEHOLDER,
                )
                self.assertFalse(result["real_project_config_read_or_copied"])
                self.assertFalse(result["native_companion_started"])
                self.assertFalse(result["host_started"])
                self.assertEqual(config_text, sandbox_preparation._SYNTHETIC_CONFIG)
                for key_name in profile_runner._KNOWN_PROVIDER_KEYS:
                    self.assertIn(
                        '%s = "%s"' % (key_name, SANDBOX_PROVIDER_KEY_PLACEHOLDER),
                        config_text,
                    )
                self.assertNotIn("source-config-canary", config_text)
                self.assertFalse((sandbox / "config.py").is_symlink())
                self.assertEqual(metadata["fixture_id"], "interior_tavern")
                self.assertEqual(metadata["party"]["size"], party_size)
                self.assertEqual(len(metadata["party"]["members"]), party_size)
                self.assertEqual(metadata["counterbalance"]["row_type"], "planned")
                self.assertEqual(metadata["counterbalance"]["row_id"], result["planned_row_id"])
                self.assertEqual(metadata["mapping"]["source_location_id"], "SRC01")
                self.assertEqual(metadata["mapping"]["runtime_location_id"], "MP01")
                self.assertFalse((sandbox / "config_template.py").exists())
                self.assertIs(sys.modules.get("config"), config_module_before)
                popen.assert_not_called()
                run.assert_not_called()

    def test_unsupported_party_or_reserve_identity_fails_before_sandbox_creation(self) -> None:
        for change, expected_error in (
            ({"party_size": 2}, "fixture-party seed identity"),
            ({"party_size": True}, "fixture-party seed identity"),
            ({"counterbalance": {"row_id": "R01", "row_type": "replacement_only", "fixed_seed": 42}},
             "fixture-party seed identity"),
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory(
                prefix="profile-sandbox-invalid-", dir=PROJECT_ROOT / "tmp"
            ) as temp_root:
                project = Path(temp_root)
                self._make_fake_runtime(project)
                plan, modules, expected = self._fake_seed_inputs(1)
                plan.update(change)
                with self.assertRaisesRegex(
                    sandbox_preparation.SandboxPreparationError, expected_error
                ):
                    sandbox_preparation._prepare_new_sandbox(
                        project, plan, modules, expected
                    )
                self.assertFalse((project / "tmp" / "combat_capture").exists())

    def test_project_tmp_symlink_and_existing_sandbox_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-path-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            other_tmp = project / "other-tmp"
            other_tmp.mkdir()
            (project / "tmp").symlink_to(other_tmp, target_is_directory=True)
            with self.assertRaisesRegex(
                sandbox_preparation.SandboxPreparationError, "existing non-symlink"
            ):
                sandbox_preparation._target_path(project)

        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-existing-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            (project / "tmp").mkdir()
            existing = project / "tmp" / "combat_capture"
            existing.mkdir()
            marker = existing / "owner.txt"
            marker.write_text("preserve", encoding="ascii")
            with self.assertRaisesRegex(
                sandbox_preparation.SandboxPreparationError, "already exists"
            ):
                sandbox_preparation._target_path(project)
            self.assertEqual(marker.read_text(encoding="ascii"), "preserve")

    def test_source_tree_symlink_aborts_and_cleans_only_disposable_sandbox(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-symlink-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            self._make_fake_runtime(project)
            outside = project / "outside.txt"
            outside.write_text("not a source", encoding="ascii")
            (project / "core" / "linked.txt").symlink_to(outside)
            plan, modules, expected = self._fake_seed_inputs(1)

            with self.assertRaisesRegex(
                sandbox_preparation.SandboxPreparationError,
                "source tree contains a symlink",
            ):
                sandbox_preparation._prepare_new_sandbox(
                    project, plan, modules, expected
                )
            self.assertFalse((project / "tmp" / "combat_capture").exists())
            self.assertEqual(outside.read_text(encoding="ascii"), "not a source")

    def test_preparation_entrypoint_uses_dedicated_guard_and_never_accesses_project_config(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-subprocess-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            self._make_subprocess_project(project)
            source_config = project / "config.py"
            source_config_bytes = (
                b"# Synthetic access trap only; it contains no credentials.\n"
                b"SOURCE_CONFIG_COPY_CANARY = 'not-a-secret-test-marker'\n"
            )
            source_config.write_bytes(source_config_bytes)
            bootstrap = project / "tmp" / "bootstrap"
            bootstrap.mkdir()
            bootstrap_relative = bootstrap.resolve().relative_to(PROJECT_ROOT).as_posix()

            audit_code = "\n".join(
                (
                    "import json, os, runpy, sys",
                    "from pathlib import Path",
                    "project = Path(sys.argv[1]).resolve()",
                    "entrypoint = project / 'scripts' / 'live_gate_preflight_sandbox.py'",
                    "source_config = os.path.abspath(os.fspath(project / 'config.py'))",
                    "events = {'project_imports': [], 'project_config_accesses': 0, 'process_launches': 0}",
                    "original_stat = os.stat",
                    "original_lstat = os.lstat",
                    "def path_key(value):",
                    "    try:",
                    "        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(value))))",
                    "    except (TypeError, ValueError):",
                    "        return None",
                    "def reject_config_metadata(function):",
                    "    def guarded(path, *args, **kwargs):",
                    "        if path_key(path) == os.path.normcase(source_config):",
                    "            events['project_config_accesses'] += 1",
                    "            raise RuntimeError('project config metadata access trapped')",
                    "        return function(path, *args, **kwargs)",
                    "    return guarded",
                    "os.stat = reject_config_metadata(original_stat)",
                    "os.lstat = reject_config_metadata(original_lstat)",
                    "def audit(event, args):",
                    "    if event == 'open' and args and path_key(args[0]) == os.path.normcase(source_config):",
                    "        events['project_config_accesses'] += 1",
                    "        raise RuntimeError('project config read or copy trapped')",
                    "    if event == 'subprocess.Popen':",
                    "        events['process_launches'] += 1",
                    "        raise RuntimeError('preparation process launch trapped')",
                    "    if event == 'import' and args and str(args[0]).startswith('scripts'):",
                    "        startup = sys.modules.get('sitecustomize')",
                    "        origin = getattr(startup, '__file__', None)",
                    "        guard_active = (",
                    "            os.environ.get('NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE') == '1'",
                    "            and os.environ.get('NEQ_PREFLIGHT_ENV_SANITIZED') == '1'",
                    "            and os.environ.get('NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE') == '1'",
                    "            and origin is not None",
                    "            and Path(origin).resolve() == (Path(os.environ['NEQ_PREFLIGHT_GUARD_DIRECTORY']) / 'sitecustomize.py').resolve()",
                    "        )",
                    "        guard_implementation = sys.modules.get('scripts.sitecustomize')",
                    "        config_guard = getattr(guard_implementation, '_CONFIG_IMPORT_ORIGIN_GUARD', None)",
                    "        config_guard_active = (",
                    "            config_guard is not None",
                    "            and config_guard in sys.meta_path",
                    "            and getattr(config_guard, 'project_root', None) == project",
                    "        )",
                    "        events['project_imports'].append({",
                    "            'name': str(args[0]),",
                    "            'guard_active_before_import': guard_active,",
                    "            'config_guard_active_before_import': config_guard_active,",
                    "        })",
                    "        if not guard_active:",
                    "            raise RuntimeError('project helper import before startup guard')",
                    "        if not config_guard_active:",
                    "            raise RuntimeError('project helper import before config origin guard')",
                    "sys.addaudithook(audit)",
                    "sys.argv = [str(entrypoint), '--prepare', '--fixture-id', 'interior_tavern', '--party-size', '1', '--planned-row-id', 'E01']",
                    "try:",
                    "    runpy.run_path(str(entrypoint), run_name='__main__')",
                    "except SystemExit as exc:",
                    "    if exc.code not in (None, 0):",
                    "        raise",
                    "print('PREPARATION_AUDIT=' + json.dumps(events, sort_keys=True))",
                )
            )
            environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                project_root=project,
                interpreter_root=PROJECT_ROOT,
                process_role="parent",
            )
            completed = subprocess.run(
                [_repository_python(), "-c", audit_code, str(project)],
                cwd=bootstrap_relative,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit_line = next(
                line for line in completed.stdout.splitlines()
                if line.startswith("PREPARATION_AUDIT=")
            )
            audit = json.loads(audit_line.split("=", 1)[1])
            self.assertGreater(len(audit["project_imports"]), 0)
            self.assertTrue(
                all(item["guard_active_before_import"] for item in audit["project_imports"])
            )
            self.assertTrue(
                all(
                    item["config_guard_active_before_import"]
                    for item in audit["project_imports"]
                )
            )
            self.assertEqual(audit["project_config_accesses"], 0)
            self.assertEqual(audit["process_launches"], 0)
            self.assertEqual(source_config.read_bytes(), source_config_bytes)

            sandbox = project / "tmp" / "combat_capture"
            self.assertEqual(
                (sandbox / "config.py").read_bytes(),
                sandbox_preparation._SYNTHETIC_CONFIG.encode("ascii"),
            )
            self.assertFalse((sandbox / "config.py").is_symlink())
            for generated_file in sandbox.rglob("*"):
                if generated_file.is_file():
                    self.assertNotIn(
                        b"not-a-secret-test-marker", generated_file.read_bytes()
                    )
            self.assertIn('"status": "prepared"', completed.stdout)

    def test_preparation_origin_guard_blocks_helper_importing_project_config(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-config-import-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            self._make_subprocess_project(project)
            marker = project / "config-import-marker.txt"
            (project / "config.py").write_text(
                "from pathlib import Path\n"
                "Path(__file__).with_name('config-import-marker.txt').write_text("
                "'executed', encoding='ascii')\n",
                encoding="ascii",
            )
            helper = project / "scripts" / "live_gate_preflight_profiles.py"
            helper.write_text("import config\n", encoding="ascii")

            bootstrap = project / "tmp" / "bootstrap"
            bootstrap.mkdir()
            bootstrap_relative = bootstrap.resolve().relative_to(PROJECT_ROOT).as_posix()
            environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                project_root=project,
                interpreter_root=PROJECT_ROOT,
                process_role="parent",
            )
            completed = subprocess.run(
                [
                    _repository_python(),
                    str(project / "scripts" / "live_gate_preflight_sandbox.py"),
                    "--prepare",
                    "--fixture-id",
                    "interior_tavern",
                    "--party-size",
                    "1",
                    "--planned-row-id",
                    "E01",
                ],
                cwd=bootstrap_relative,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertIn(
                "real project config.py is forbidden during preflight",
                completed.stderr,
            )
            self.assertFalse(marker.exists())
            self.assertFalse((project / "tmp" / "combat_capture").exists())

    def test_preparation_entrypoint_fails_closed_without_dedicated_guard_path(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-sandbox-no-bootstrap-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project = Path(temp_root)
            self._make_subprocess_project(project)
            no_bootstrap = project / "tmp" / "no-bootstrap"
            no_bootstrap.mkdir()
            environment = build_guarded_environment(
                {"PATH": os.environ.get("PATH", "")},
                project_root=project,
                interpreter_root=PROJECT_ROOT,
                process_role="parent",
            )
            environment["PYTHONPATH"] = str(project)
            completed = subprocess.run(
                [
                    _repository_python(),
                    str(project / "scripts" / "live_gate_preflight_sandbox.py"),
                    "--prepare",
                    "--fixture-id",
                    "interior_tavern",
                    "--party-size",
                    "1",
                    "--planned-row-id",
                    "E01",
                ],
                cwd=no_bootstrap,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn(
                "preparation_requires_dedicated_startup_guard", completed.stderr
            )
            self.assertFalse((project / "tmp" / "combat_capture").exists())

    @staticmethod
    def _make_subprocess_project(project: Path) -> None:
        source_files = (
            "scripts/live_gate_preflight_sandbox.py",
            "scripts/sitecustomize.py",
            "scripts/live_gate_preflight_safety.py",
            "scripts/live_gate_preflight_guard/sitecustomize.py",
            "scripts/live_gate_preflight_profiles.py",
            "scripts/live_gate_preflight_profiles.json",
            "scripts/live_gate_preflight_profiles.schema.json",
            "scripts/seed_combat_capture.py",
            "scripts/capture_evidence.py",
            "scripts/combat_latency_fixtures.py",
            "scripts/mapping_pilot/__init__.py",
            "scripts/mapping_pilot/fixtures.py",
            "scripts/mapping_pilot/manifest.py",
            "scripts/mapping_pilot/launcher.py",
            "openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md",
        )
        for relative in source_files:
            source = PROJECT_ROOT / relative
            destination = project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        prereg_source = PROJECT_ROOT / "plans" / "v2-mapping-pilot-prereg"
        prereg_target = project / "plans" / "v2-mapping-pilot-prereg"
        for source in sorted(prereg_source.rglob("*")):
            if source.is_symlink():
                raise AssertionError("authoritative prereg source unexpectedly contains a symlink")
            relative = source.relative_to(prereg_source)
            destination = prereg_target / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)

        (project / "tmp").mkdir(parents=True, exist_ok=True)
        for filename in ("main.py", "run_web.py", "model_config.py", "debug_config.py", "VERSION"):
            (project / filename).write_text("# isolated synthetic runtime\n", encoding="ascii")
        for relative in (
            "core",
            "utils",
            "updates",
            "web",
            "prompts",
            "schemas",
            "templates",
            "icons",
            "modules/Capture_Arena",
        ):
            directory = project / relative
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "runtime.txt").write_text("synthetic", encoding="ascii")

        (project / "utils" / "__init__.py").write_text("", encoding="ascii")
        (project / "utils" / "file_operations.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "def safe_write_json(path, value, **kwargs):\n"
            "    options = kwargs.get('json_kwargs') or {}\n"
            "    Path(path).parent.mkdir(parents=True, exist_ok=True)\n"
            "    Path(path).write_text(json.dumps(value, **options), encoding='utf-8')\n"
            "    return True\n"
            "def safe_read_json(path, **_kwargs):\n"
            "    return json.loads(Path(path).read_text(encoding='utf-8'))\n",
            encoding="ascii",
        )
        (project / "utils" / "combat_latency_trace.py").write_text(
            "def build_work_unit_trace_context(*_args, **_kwargs): return {}\n"
            "def set_trace_context(*_args, **_kwargs): return None\n"
            "def trace_file_operation(*_args, **_kwargs): return None\n"
            "def trace_stage(*_args, **_kwargs): return None\n",
            encoding="ascii",
        )

    @staticmethod
    def _make_fake_runtime(project: Path) -> None:
        (project / "tmp").mkdir()
        for filename in ("main.py", "run_web.py", "model_config.py"):
            (project / filename).write_text("# fake runtime source\n", encoding="ascii")
        for relative in (
            "core",
            "utils",
            "updates",
            "web",
            "prompts",
            "schemas",
            "scripts",
            "modules/Capture_Arena",
        ):
            directory = project / relative
            directory.mkdir(parents=True)
            (directory / "runtime.txt").write_text("fake", encoding="ascii")

    @staticmethod
    def _fake_seed_inputs(party_size: int) -> tuple[dict, dict, dict]:
        from scripts.mapping_pilot.fixtures import FIXTURE_FILES

        fixture_ids = tuple(FIXTURE_FILES)
        expected = {
            fixture_id: {
                "fixture_id": fixture_id,
                "source_file": FIXTURE_FILES[fixture_id],
                "source_truth": {
                    "fixture_id": fixture_id,
                    "location_ids": ["SRC01"],
                },
            }
            for fixture_id in fixture_ids
        }
        modules = {
            "areas/MPA001.json": {
                "areaId": "MPA001",
                "areaName": "Synthetic Test Area",
                "locations": [{"locationId": "MP01", "name": "Synthetic Test Room"}],
            },
            "map_MPA001.json": {
                "rooms": [{"id": "MP01"}],
                "startRoom": "wrong-room",
            },
            "location_id_map.json": {
                "runtime_location_ids": {"SRC01": "MP01"},
            },
        }
        row_id = "E01" if party_size == 1 else "E07"
        plan = {
            "fixture_id": "interior_tavern",
            "arm": "A",
            "party_size": party_size,
            "effective_seed": 42,
            "fixture": {},
            "source_location_id": "SRC01",
            "runtime_location_id": "MP01",
            "counterbalance": {
                "row_id": row_id,
                "row_type": "planned",
                "block": 1,
                "script": "scripts/interior.json",
                "fixed_seed": 42,
            },
        }
        return plan, modules, expected


def _run_profile_worker_probe(
    sandbox_relative: str, lifecycle: str, outcome: str
) -> None:
    sandbox = PROJECT_ROOT / sandbox_relative
    sitecustomize_module = sys.modules.get("sitecustomize")
    startup_sitecustomize_verified = (
        getattr(sitecustomize_module, "__file__", None) is not None
        and Path(sitecustomize_module.__file__).resolve()
        == (
            PROJECT_ROOT
            / "scripts"
            / "live_gate_preflight_guard"
            / "sitecustomize.py"
        ).resolve()
        and os.environ.get("NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE") == "1"
    )

    for module_name in tuple(sys.modules):
        if module_name == "utils" or module_name.startswith("utils."):
            sys.modules.pop(module_name, None)

    runner_module = importlib.import_module("scripts.live_gate_preflight_profile_runner")
    runner_module.SANDBOX_RELATIVE = Path(sandbox_relative)
    runner_module._verify_source_identity = lambda _source_sha: None
    runner_module._lock_holder_for_worker = lambda _args: {}
    runner_module._worker_result_path = lambda _run_id: sandbox / "worker-result.json"
    original_shutdown_request_path = runner_module._worker_shutdown_request_path
    runner_module._worker_shutdown_request_path = (
        lambda _run_id: sandbox / "shutdown-request.json"
    )
    original_host_command = runner_module._host_command
    runner_module._host_command = lambda **_kwargs: current_invocation_command()

    server = importlib.import_module("scripts.mapping_pilot.server")
    launcher = importlib.import_module("scripts.mapping_pilot.launcher")
    server._safe_runtime_root = lambda _runtime_root: sandbox
    entrypoint: dict = {}

    def fake_server_runner(_web_interface: object) -> None:
        import config

        entrypoint["sandbox_config_loaded"] = (
            Path(config.__file__).resolve() == (sandbox / "config.py").resolve()
        )
        from utils import llm_router

        probe_path = sandbox / "mapping_pilot" / "profile_lifecycle_probe.py"
        namespace: dict = {}
        exec(compile(probe_path.read_text(encoding="utf-8"), str(probe_path), "exec"), namespace)
        task = "unlisted_task" if outcome == "reject" else "dm_main"
        response = namespace["invoke"](llm_router.llm, task)
        entrypoint["stub_response"] = json.loads(response)
        if outcome in {"caught", "propagated", "wrong_request"}:
            request = runner_module._worker_shutdown_request_record(
                run_id=args.run_id,
                controller_pid=max(1, os.getpid() - 1),
                worker_pid=os.getpid(),
                process_group_id=os.getpgrp(),
                readiness_succeeded=True,
                exchange_succeeded=True,
            )
            if outcome == "wrong_request":
                request["run_id"] = "wrong-" + args.run_id
            runner_module._write_json(
                runner_module._worker_shutdown_request_path(args.run_id), request
            )
            handler = signal.getsignal(signal.SIGINT)
            if outcome == "propagated":
                handler(signal.SIGINT, None)
            else:
                try:
                    handler(signal.SIGINT, None)
                except KeyboardInterrupt:
                    entrypoint["server_caught_keyboard_interrupt"] = True

    fake_module_files = {
        "web.web_interface": sandbox / "web" / "web_interface.py",
        "main": sandbox / "main.py",
        "core.combat.prompts": sandbox / "core" / "combat" / "prompts.py",
        "core.combat.combat_manager": sandbox / "core" / "combat" / "combat_manager.py",
    }
    for file_path in fake_module_files.values():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("# isolated module identity\n", encoding="utf-8")
    fake_module_files["main"].write_text(
        "from utils.ai_client_factory import create_chat_client\n"
        "client = create_chat_client()\n",
        encoding="utf-8",
    )
    adapter_path = sandbox / "scripts" / "mapping_pilot" / "adapter.py"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(
        "class SandboxPacketProvider:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n"
        "class Installation:\n"
        "    def uninstall(self):\n"
        "        pass\n"
        "def install_adapter(**kwargs):\n"
        "    return Installation()\n",
        encoding="utf-8",
    )
    fake_modules = {
        name: types.SimpleNamespace(__file__=str(file_path))
        for name, file_path in fake_module_files.items()
    }
    web_interface = fake_modules["web.web_interface"]
    web_interface.dm_main = types.SimpleNamespace(__file__=str(fake_module_files["main"]))
    web_interface.INSTALL_ROOT = sandbox
    web_interface._configured_web_port = 8360

    original_import_module = importlib.import_module
    original_validate_sandbox = launcher.validate_sandbox
    original_launch = launcher.launch
    original_server_runner = launcher._run_web_interface
    factory_module: list[Any] = []

    def fake_import_module(name: str, package: str | None = None) -> object:
        if name in fake_modules:
            if name == "web.web_interface":
                fake_modules[name].dm_main = original_import_module("main")
                from utils import ai_client_factory

                factory_module.append(ai_client_factory)
                entrypoint["client_factory_result_is_none"] = (
                    fake_modules[name].dm_main.client is None
                )
            return fake_modules[name]
        return original_import_module(name, package)

    def tracking_launch(**kwargs: object) -> object:
        entrypoint["fixture_id"] = kwargs.get("fixture_id")
        entrypoint["party_size"] = kwargs.get("party_size")
        entrypoint["lifecycle"] = "resume" if kwargs.get("resume") else "startup"
        entrypoint["resume_checkpoint_sha256"] = kwargs.get("resume_checkpoint_sha256")
        validated = launcher.ValidatedSandbox(
            root=sandbox,
            metadata={},
            fixture_payloads={},
            runtime_to_source={},
        )
        saved_validate_sandbox = launcher.validate_sandbox
        launcher.validate_sandbox = lambda *_args, **_kwargs: validated
        try:
            return original_launch(**kwargs)
        finally:
            launcher.validate_sandbox = saved_validate_sandbox

    importlib.import_module = fake_import_module
    launcher.launch = tracking_launch
    launcher._run_web_interface = fake_server_runner
    resume_checkpoint = "b" * 64 if lifecycle == "resume" else None
    args = argparse.Namespace(
        worker=True,
        fixture_id="interior_tavern",
        party_size=1,
        lifecycle=lifecycle,
        source_sha="a" * 40,
        run_id="profile-worker-" + lifecycle + "-" + outcome,
        planned_row_id="E01",
        arm="A",
        lifecycle_id=(
            "profile-worker-"
            + lifecycle
            + "-"
            + outcome
            + ("_r" if lifecycle == "resume" else "_s")
        ),
        resume_checkpoint_sha256=resume_checkpoint,
    )
    try:
        exit_code = runner_module._worker(args)
    finally:
        runner_module._host_command = original_host_command
        runner_module._worker_shutdown_request_path = original_shutdown_request_path
        importlib.import_module = original_import_module
        launcher.launch = original_launch
        launcher.validate_sandbox = original_validate_sandbox
        launcher._run_web_interface = original_server_runner
    if factory_module:
        factory = factory_module[0]
        entrypoint["original_factory_calls"] = len(factory.factory_calls)
        entrypoint["provider_factory_restored"] = (
            factory.create_chat_client is factory.ORIGINAL_FACTORY
        )
    worker_result = runner_module._read_json(
        sandbox / "worker-result.json", "worker_result"
    )
    print(
        json.dumps(
            {
                "exit_code": exit_code,
                "startup_sitecustomize_verified": startup_sitecustomize_verified,
                "entrypoint": entrypoint,
                "worker_result": worker_result,
            },
            sort_keys=True,
        )
    )
    raise SystemExit(exit_code)


def _run_probe_from_sitecustomize() -> None:
    if len(sys.argv) < 2:
        return
    mode = sys.argv[1]
    if mode == "--startup-canary-probe":
        from scripts.live_gate_preflight_safety import run_startup_process_canary

        report = run_startup_process_canary()
        print(json.dumps(report, sort_keys=True))
        raise SystemExit(0)
    if mode == "--profile-worker-probe":
        if len(sys.argv) != 5:
            raise SystemExit("profile worker probe arguments are incomplete")
        _run_profile_worker_probe(sys.argv[2], sys.argv[3], sys.argv[4])
    if mode == "--stub-probe":
        from scripts.live_gate_preflight_safety import activate_preflight_safety

        activate_preflight_safety()
        stub = FailClosedRouterStub(
            source_sha="a" * 40,
            responses={"dm_main": {"text": "stubbed"}},
            command=[
                ".venv/bin/python",
                "scripts/test_live_gate_preflight_profiles.py",
                "--api-key",
                "synthetic-secret",
            ],
            pythonpath=os.environ.get("PYTHONPATH", ""),
        )
        response = stub("dm_main")
        unsupported_call_rejected = False
        try:
            stub("unlisted_task")
        except RouterStubError:
            unsupported_call_rejected = True
        print(
            json.dumps(
                {
                    "response": response,
                    "call_count": stub.call_count,
                    "calls": stub.calls,
                    "unsupported_call_rejected": unsupported_call_rejected,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(0)
    if mode == "--profile-stub-probe":
        from scripts.live_gate_preflight_safety import activate_preflight_safety

        activate_preflight_safety()
        responses = profile_runner._characterization_stub_responses("interior_tavern")
        stub = FailClosedRouterStub(
            source_sha="a" * 40,
            responses=responses,
            command=[
                ".venv/bin/python",
                "scripts/test_live_gate_preflight_profiles.py",
                "--profile-stub-probe",
            ],
            pythonpath=os.environ.get("PYTHONPATH", ""),
        )
        returned = {task: stub(task) for task in responses}
        unsupported_call_rejected = False
        try:
            stub("unlisted_task")
        except RouterStubError:
            unsupported_call_rejected = True
        print(
            json.dumps(
                {
                    "responses": returned,
                    "call_count": stub.call_count,
                    "calls": stub.calls,
                    "failure_code": stub.failure_code,
                    "unsupported_call_rejected": unsupported_call_rejected,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(0)
    if mode == "--stub-without-guard-probe":
        try:
            FailClosedRouterStub(source_sha="a" * 40, responses={"dm_main": "ok"})
        except RouterStubError:
            print("guard-required")
            raise SystemExit(0)
        raise SystemExit(1)


_run_probe_from_sitecustomize()


if __name__ == "__main__":
    unittest.main()
