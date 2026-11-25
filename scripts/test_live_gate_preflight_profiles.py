# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for profile coverage, provenance, stubbing, and safety."""

from __future__ import annotations

import argparse
import ast
import copy
import errno
import hashlib
import io
import importlib
import json
import os
import re
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
from scripts import live_gate_preflight_profiles as preflight_profiles
from scripts import live_gate_preflight_retained as retained_evidence
from scripts.live_gate_preflight_profiles import (
    AUTHORIZATION_RULING_ID,
    FIXTURE_IDS,
    PROFILE_PATH,
    PROFILE_SET_ID,
    PROJECT_ROOT,
    ProfileValidationError,
    copy_profile_document,
    load_profile_coverage,
    _is_exact_historic_profile_evidence,
    _valid_command,
    _valid_controller_command,
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
    compare_invocation_identity,
    expected_guarded_pythonpath,
    require_startup_guard_active,
    validate_guard_event_records,
    validate_sandbox_config_location,
    _startup_canary_environment_digest,
    _startup_environment_digest,
    _validate_canary_launch,
)
from scripts.live_gate_preflight_stub import FailClosedRouterStub, RouterStubError
from scripts import live_gate_preflight_stub as preflight_stub
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
from scripts.live_gate_preflight_comparison_identity import (
    APPLICATION_A_SHA,
    APPLICATION_A_TREE,
    build_comparison_identity,
)


_LEGACY_LIFECYCLE_FIELDS = {
    "status",
    "call_count",
    "call_sites",
    "source_sha",
    "command",
    "pythonpath",
    "evidence_path",
    "evidence_sha256",
}


def _content_bound_from_legacy(
    profile: dict, entry: dict, *, required: bool
) -> dict:
    """Convert a test-built evidence-bound lifecycle into the declaration shape."""
    hashes = preflight_profiles.tool_file_hashes()
    return {
        "status": "measured-under-stub",
        "required": required,
        "fixture_id": profile["fixture_id"],
        "party_size": profile["party_size"],
        "call_count": entry["call_count"],
        "call_sites": copy.deepcopy(entry["call_sites"]),
        "stub_sha256": {
            "path": preflight_profiles.STUB_FILE,
            "sha256": hashes[preflight_profiles.STUB_FILE],
        },
        "driver_sha256": [
            {"path": path, "sha256": hashes[path]}
            for path in preflight_profiles.DRIVER_FILES
        ],
        "provenance": {
            "run_id": "legacy-fixture-run",
            "evidence_sha256": entry["evidence_sha256"],
        },
    }


def _to_content_bound(document: dict) -> tuple[dict, list]:
    converted = copy.deepcopy(document)
    pending = []
    for profile in converted["profiles"]:
        for lifecycle in ("startup", "resume"):
            entry = profile.get(lifecycle)
            if isinstance(entry, dict) and set(entry) == _LEGACY_LIFECYCLE_FIELDS:
                pending.append((profile, lifecycle, dict(entry)))
                profile[lifecycle] = _content_bound_from_legacy(
                    profile,
                    entry,
                    required=profile[lifecycle].get(
                        "required",
                        lifecycle == "startup"
                        or profile["fixture_id"] == "interior_tavern",
                    ),
                )
    return converted, pending


def validate_profile_document(
    document: Any, *, expected_source_sha: str | None = None
) -> dict:
    """Validate a declaration; evidence-bound fixtures also get run-evidence checks.

    Test fixtures built from retained or synthetic run evidence carry the legacy
    evidence fields. The production declaration no longer does, so the fixture
    is converted to the content-bound shape for declaration validation and the
    run evidence is validated directly with ``_validate_profile_evidence``.
    """
    converted, pending = _to_content_bound(document)
    coverage = preflight_profiles.validate_profile_document(converted)
    row_metadata = preflight_profiles._load_expected_row_pairs(PROJECT_ROOT)[
        "row_metadata"
    ]
    for profile, lifecycle, entry in pending:
        if expected_source_sha is not None and entry["source_sha"] != expected_source_sha:
            raise ProfileValidationError(
                "measured lifecycle source SHA does not match expected source"
            )
        preflight_profiles._validate_profile_evidence(
            PROJECT_ROOT,
            evidence_path=entry["evidence_path"],
            evidence_sha256=entry["evidence_sha256"],
            profile_id=profile["profile_id"],
            fixture_id=profile["fixture_id"],
            party_size=profile["party_size"],
            lifecycle=lifecycle,
            planned_row_ids=profile["planned_row_ids"],
            row_metadata=row_metadata,
            source_sha=entry["source_sha"],
            command=entry["command"],
            pythonpath=entry["pythonpath"],
            call_count=entry["call_count"],
            call_sites=entry["call_sites"],
        )
    return coverage


def _sandbox_host_identity(project_root: Path) -> dict[str, Any]:
    run_id = "pf-profile-sandbox-01"
    with mock.patch.object(
        profile_runner,
        "_repository_python",
        return_value=str(project_root / ".venv" / "bin" / "python"),
    ):
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
    return {
        "command": command,
        "working_directory": str(project_root / "tmp" / "combat_capture"),
        "pythonpath": expected_guarded_pythonpath(project_root),
    }


def _sandbox_identity_cli_args(project_root: Path) -> list[str]:
    identity = json.dumps(
        _sandbox_host_identity(project_root), ensure_ascii=True, sort_keys=True
    )
    return [
        "--lifecycle",
        "startup",
        "--source-sha",
        "a" * 40,
        "--run-id",
        "pf-profile-sandbox-01",
        "--intended-host-identity-json",
        identity,
    ]


def _raise_summary_child_retention_error(*_args: object, **_kwargs: object) -> None:
    error = retained_evidence.RetainedEvidenceError(
        "summary child final output differs from last write"
    )
    error.retained_artifacts = [{"role": "script_source"}]
    raise error


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



BASELINE_PROFILE_PATH = (
    PROJECT_ROOT / "scripts" / "fixtures" / "live_gate_preflight_profiles_all_missing.json"
)


def copy_baseline_profile_document() -> dict[str, Any]:
    """Detached copy of the committed all-MISSING baseline declaration.

    Baseline/synthetic tests use this so they do not depend on the measured
    declarations that scripts/live_gate_preflight_profiles.json now carries.
    """
    return json.loads(BASELINE_PROFILE_PATH.read_text(encoding="utf-8"))

class TestLiveGatePreflightProfiles(unittest.TestCase):
    def test_controller_command_allows_only_multiline_code_argument(self) -> None:
        command = ["/venv/bin/python", "-P", "-c", "print('one')\nprint('two')"]
        self.assertTrue(_valid_controller_command(command))
        self.assertFalse(_valid_command(command))
        self.assertEqual(command[3], "print('one')\nprint('two')")
        digest = hashlib.sha256(
            json.dumps(command, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()
        self.assertNotEqual(
            digest,
            hashlib.sha256(
                json.dumps(command[:3] + [command[3].replace("\n", " ")], separators=(",", ":")).encode("ascii")
            ).hexdigest(),
        )

    def test_controller_command_rejects_other_controls_and_secrets(self) -> None:
        base = ["/venv/bin/python", "-P", "-c", "print('ok')\nprint('next')"]
        for mutation in (
            lambda value: value.__setitem__(0, "/host\npython"),
            lambda value: value.__setitem__(1, "-P\n"),
            lambda value: value.__setitem__(3, "print('a')\r\nprint('b')"),
            lambda value: value.__setitem__(3, "print('a')\tprint('b')"),
            lambda value: value.__setitem__(3, "print('a')\x7f"),
            lambda value: value.__setitem__(3, "token=supersecretvalue"),
        ):
            command = list(base)
            mutation(command)
            self.assertFalse(_valid_controller_command(command), repr(command))
        altered = list(base)
        altered[3] += "\nprint('altered')"
        self.assertNotEqual(
            hashlib.sha256(json.dumps(base, separators=(",", ":")).encode()).hexdigest(),
            hashlib.sha256(json.dumps(altered, separators=(",", ":")).encode()).hexdigest(),
        )

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
        document = copy_baseline_profile_document()
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
        document = copy_baseline_profile_document()
        document["profiles"].pop()
        with self.assertRaisesRegex(ProfileValidationError, "exactly eight"):
            validate_profile_document(document)

        document = copy_baseline_profile_document()
        document["profiles"][0].pop("startup")
        with self.assertRaisesRegex(
            ProfileValidationError, "fixture-party profile fields are malformed"
        ):
            validate_profile_document(document)

    def test_unsupported_status_and_pair_are_rejected(self) -> None:
        document = copy_baseline_profile_document()
        document["profiles"][0]["resume"]["status"] = "inferred"
        with self.assertRaisesRegex(ProfileValidationError, "unsupported lifecycle"):
            validate_profile_document(document)

        document = copy_baseline_profile_document()
        document["profiles"][0]["fixture_id"] = "unsupported_fixture"
        with self.assertRaisesRegex(ProfileValidationError, "unsupported fixture-party"):
            validate_profile_document(document)

    def test_source_hash_or_row_binding_drift_is_rejected(self) -> None:
        document = copy_baseline_profile_document()
        document["source_binding"]["counterbalance_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProfileValidationError, "source binding"):
            validate_profile_document(document)

        document = copy_baseline_profile_document()
        document["profiles"][0]["planned_row_ids"].append("R01")
        with self.assertRaisesRegex(ProfileValidationError, "planned-row binding"):
            validate_profile_document(document)

    def test_measured_profile_requires_stub_source_call_sites_and_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            new_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(new_evidence["invocation_identity"]["status"], "matched")
            schema_path = PROFILE_PATH.with_name("live_gate_preflight_profiles.schema.json")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(_to_content_bound(document)[0])
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

    def test_summary_child_sidecar_hash_is_reconciled_with_profile_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-child-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._measured_document(Path(evidence_directory))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            child = evidence["adv_summary_child"]
            child_sidecar = PROJECT_ROOT / child["evidence_path"]
            self.assertEqual(child_sidecar.read_bytes(), b"")
            validate_profile_document(document, expected_source_sha="a" * 40)

            child["evidence_sha256"] = "0" * 64
            self._persist_profile_evidence(document, evidence_path, evidence)
            with self.assertRaisesRegex(
                ProfileValidationError, "summary child evidence hash differs"
            ):
                validate_profile_document(document, expected_source_sha="a" * 40)

    def test_historic_identity_exception_is_exactly_pinned_and_tamper_resistant(
        self,
    ) -> None:
        records = (
            {
                "path": "tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-tower-p1-startup-01/profile-evidence.json",
                "sha256": "8908c2e325e0e2289789d4baeda721a553c809e1c9f5b4d99086f0f9f8b71a19",
                "profile_id": "transition_tower_approach:p1",
                "fixture_id": "transition_tower_approach",
                "party_size": 1,
                "lifecycle": "startup",
                "source_sha": "7e874277c6bd69de2e13e1282ea0f8a0cda10290",
                "planned_row_id": "E04",
                "arm": "D",
                "run_id": "fr11-tower-p1-startup-01",
            },
            {
                "path": "tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-tower-p4-startup-01/profile-evidence.json",
                "sha256": "ee0fe4018769f3e125dc3bfe7ce228111088c55027b2fa8ae6417ef33c867046",
                "profile_id": "transition_tower_approach:p4",
                "fixture_id": "transition_tower_approach",
                "party_size": 4,
                "lifecycle": "startup",
                "source_sha": "021a55463ec86d76eeb6fa2b9ca5fc458f1725b6",
                "planned_row_id": "E13",
                "arm": "D",
                "run_id": "fr11-tower-p4-startup-01",
            },
            {
                "path": "tmp/router-rollout/live-gate-preflight/profile-characterization/fr11-combat-p4-startup-01/profile-evidence.json",
                "sha256": "40f328d3d5c877a56aa13065585790081f9abcca0a6f679ac1b047d80b47f1c9",
                "profile_id": "combat_stage_tavern_zones:p4",
                "fixture_id": "combat_stage_tavern_zones",
                "party_size": 4,
                "lifecycle": "startup",
                "source_sha": "17d63b0787ca3048e9d181432bbca9c89aa4105e",
                "planned_row_id": "C05",
                "arm": "D",
                "run_id": "fr11-combat-p4-startup-01",
            },
        )
        self.assertEqual(len(records), 3)
        for record in records:
            with self.subTest(run_id=record["run_id"]):
                evidence = {
                    "authorization_ruling_id": AUTHORIZATION_RULING_ID,
                    **{key: value for key, value in record.items() if key != "path" and key != "sha256"},
                }
                arguments = {
                    "evidence_path": record["path"],
                    "evidence_sha256": record["sha256"],
                    "profile_id": record["profile_id"],
                    "fixture_id": record["fixture_id"],
                    "party_size": record["party_size"],
                    "lifecycle": record["lifecycle"],
                    "source_sha": record["source_sha"],
                }
                self.assertTrue(_is_exact_historic_profile_evidence(evidence, **arguments))

                wrong_path = dict(arguments)
                wrong_path["evidence_path"] = record["path"] + ".copy"
                self.assertFalse(
                    _is_exact_historic_profile_evidence(evidence, **wrong_path)
                )
                wrong_hash = dict(arguments)
                wrong_hash["evidence_sha256"] = "0" * 64
                self.assertFalse(
                    _is_exact_historic_profile_evidence(evidence, **wrong_hash)
                )

                for field in (
                    "profile_id",
                    "fixture_id",
                    "party_size",
                    "lifecycle",
                    "source_sha",
                    "planned_row_id",
                    "arm",
                    "run_id",
                ):
                    tampered = dict(evidence)
                    value = tampered[field]
                    tampered[field] = value + 1 if type(value) is int else "tampered"
                    self.assertFalse(
                        _is_exact_historic_profile_evidence(tampered, **arguments),
                        "accepted tampered %s for %s" % (field, record["run_id"]),
                    )
                if record["party_size"] == 1:
                    tampered_party_size = dict(evidence)
                    tampered_party_size["party_size"] = True
                    self.assertFalse(
                        _is_exact_historic_profile_evidence(
                            tampered_party_size, **arguments
                        ),
                        "accepted bool party size for %s" % record["run_id"],
                    )

    def test_retained_p4_historic_evidence_still_passes_full_validation(self) -> None:
        records = (
            (
                "tmp/router-rollout/live-gate-preflight/profile-characterization/"
                "fr11-tower-p4-startup-01/profile-evidence.json",
                "ee0fe4018769f3e125dc3bfe7ce228111088c55027b2fa8ae6417ef33c867046",
                "021a55463ec86d76eeb6fa2b9ca5fc458f1725b6",
                "transition_tower_approach:p4",
            ),
            (
                "tmp/router-rollout/live-gate-preflight/profile-characterization/"
                "fr11-combat-p4-startup-01/profile-evidence.json",
                "40f328d3d5c877a56aa13065585790081f9abcca0a6f679ac1b047d80b47f1c9",
                "17d63b0787ca3048e9d181432bbca9c89aa4105e",
                "combat_stage_tavern_zones:p4",
            ),
        )
        checked = 0
        for relative_path, expected_hash, expected_source, profile_id in records:
            evidence_path = Path(relative_path)
            if not evidence_path.is_file():
                continue
            with self.subTest(profile_id=profile_id):
                raw = evidence_path.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_hash)
                evidence = json.loads(raw.decode("utf-8"))
                self.assertEqual(evidence["source_sha"], expected_source)
                document = copy_baseline_profile_document()
                profile = next(
                    item for item in document["profiles"] if item["profile_id"] == profile_id
                )
                profile["startup"] = {
                    "status": "measured-under-stub",
                    "call_count": evidence["call_count"],
                    "call_sites": evidence["call_sites"],
                    "source_sha": evidence["source_sha"],
                    "command": evidence["command"],
                    "pythonpath": evidence["pythonpath"],
                    "evidence_path": relative_path,
                    "evidence_sha256": expected_hash,
                }
                coverage = validate_profile_document(
                    document, expected_source_sha=expected_source
                )
                self.assertTrue(coverage["structural_row_coverage_complete"])
                self.assertFalse(coverage["measured_lifecycle_complete"])
                self.assertFalse(coverage["booking_eligible"])
                checked += 1
        if checked == 0:
            missing = [
                str(PROJECT_ROOT / relative_path)
                for relative_path, _expected_hash, _expected_source, _profile_id in records
                if not (PROJECT_ROOT / relative_path).is_file()
            ]
            self.skipTest("missing required path(s): %s" % ", ".join(missing))

    def test_retained_real_startup_evidence_validates_offline(self) -> None:
        evidence_path = Path(
            "tmp/router-rollout/live-gate-preflight/profile-characterization/"
            "fr11-tower-p1-startup-01/profile-evidence.json"
        )
        if not evidence_path.is_file():
            self.skipTest("missing required path: %s" % (PROJECT_ROOT / evidence_path))
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

        document = copy_baseline_profile_document()
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

        with tempfile.TemporaryDirectory(
            prefix="legacy-profile-copy-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            copied_evidence = Path(temp_root) / "profile-evidence.json"
            copied_evidence.write_bytes(raw)
            profile["startup"]["evidence_path"] = copied_evidence.relative_to(
                PROJECT_ROOT
            ).as_posix()
            with self.assertRaisesRegex(
                ProfileValidationError, "invocation identity is missing"
            ):
                validate_profile_document(
                    document, expected_source_sha=evidence["source_sha"]
                )

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
            tampered = json.loads(original.decode("utf-8"))
            tampered["invocation_identity"]["status"] = "blocked"
            self._write_evidence(evidence_path, tampered)
            with self.assertRaisesRegex(ProfileValidationError, "hash does not match"):
                validate_profile_document(document)

            evidence_path.write_bytes(original)
            evidence = json.loads(original.decode("utf-8"))
            evidence["fixture_id"] = "landscape_village"
            self._write_evidence(evidence_path, evidence)
            startup["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ProfileValidationError, "identity or safety state differs"):
                validate_profile_document(document)

    def test_profile_invocation_identity_must_match_worker_observations(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-invocation-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            cases = (
                ("command", "worker canaries"),
                ("working_directory", "worker canaries"),
                ("pythonpath", "routed worker calls"),
                ("receipt", "not a secret-safe match"),
            )
            for field, message in cases:
                with self.subTest(field=field):
                    document, evidence_path = self._measured_document(
                        Path(evidence_directory)
                    )
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                    if field == "command":
                        evidence["process_canaries"][1]["command"][-1] += "-mismatch"
                    elif field == "working_directory":
                        evidence["process_canaries"][1]["working_directory"] = (
                            "/private/capture-secret-path"
                        )
                    elif field == "pythonpath":
                        evidence["calls"][0]["pythonpath"] += os.pathsep + "other-root"
                    else:
                        evidence["invocation_identity"]["status"] = "blocked"
                        evidence["invocation_identity"]["mismatches"] = [
                            {"field": "command"}
                        ]
                    self._persist_profile_evidence(document, evidence_path, evidence)
                    with self.assertRaisesRegex(ProfileValidationError, message) as raised:
                        validate_profile_document(document)
                    self.assertNotIn(
                        "/private/capture-secret-path", str(raised.exception)
                    )

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
        document = copy_baseline_profile_document()
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

    def test_checkpoint_profile_evidence_accepts_late_guarded_children(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-checkpoint-late-child-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_directory:
            document, evidence_path = self._checkpoint_run_with_late_child(
                Path(evidence_directory)
            )

            coverage = validate_profile_document(document)

        self.assertTrue(coverage["structural_row_coverage_complete"])

    def test_late_guard_startup_relaxation_is_checkpoint_only_and_fail_closed(
        self,
    ) -> None:
        cases = (
            ("ordinary-startup", False, "host_ready", lambda pids: pids),
            (
                "checkpoint-missing-before-host",
                True,
                "host_ready",
                lambda pids: [pid for pid in pids if pid != 10002],
            ),
            (
                "checkpoint-unknown-host-ready-pid",
                True,
                "host_ready",
                lambda pids: sorted([*pids, 19999]),
            ),
            (
                "checkpoint-missing-row-pid",
                True,
                "host_ready",
                lambda pids: [pid for pid in pids if pid != 10003],
            ),
            (
                "checkpoint-incomplete-after-teardown",
                True,
                "after_teardown",
                lambda pids: [pid for pid in pids if pid != 10004],
            ),
        )
        with tempfile.TemporaryDirectory(
            prefix="profile-evidence-checkpoint-negative-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            for name, checkpoint_run, phase, mutate_pids in cases:
                with self.subTest(name=name):
                    evidence_directory = Path(temp_root) / name
                    evidence_directory.mkdir()
                    document, evidence_path = self._checkpoint_run_with_late_child(
                        evidence_directory,
                        checkpoint_run=checkpoint_run,
                    )
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                    sample, sidecar_path, sidecar = self._read_profile_socket_sidecar(
                        evidence, phase
                    )
                    sidecar["guard_startup_pids"] = mutate_pids(
                        sidecar["guard_startup_pids"]
                    )
                    self._write_profile_socket_sidecar(
                        sample, sidecar_path, sidecar
                    )
                    self._persist_profile_evidence(
                        document, evidence_path, evidence
                    )

                    with self.assertRaisesRegex(
                        ProfileValidationError,
                        "socket sample guard ownership differs",
                    ):
                        validate_profile_document(document)

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

    def _checkpoint_run_with_late_child(
        self,
        evidence_directory: Path,
        *,
        checkpoint_run: bool = True,
    ) -> tuple[dict[str, Any], Path]:
        document, evidence_path = self._measured_document(evidence_directory)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if checkpoint_run:
            self._add_synthetic_checkpoint(evidence)
        self._add_late_guarded_child(evidence)
        self._persist_profile_evidence(document, evidence_path, evidence)
        return document, evidence_path

    def _add_synthetic_checkpoint(self, evidence: dict[str, Any]) -> None:
        row_id = evidence["planned_row_id"]
        run_id = evidence["run_id"]
        fixture_id = evidence["fixture_id"]
        party_size = evidence["party_size"]
        source_sha = evidence["source_sha"]
        row_metadata = preflight_profiles._load_expected_row_pairs(
            PROJECT_ROOT
        )["row_metadata"][row_id]
        checkpoint_root = (
            "tmp/router-rollout/live-gate-preflight-checkpoints/"
            "%s/%s/%s-p%d" % (run_id, row_id, fixture_id, party_size)
        )
        checkpoint_directory = PROJECT_ROOT / checkpoint_root
        checkpoint_run_directory = checkpoint_directory.parents[1]
        checkpoint_run_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, checkpoint_run_directory, ignore_errors=True)

        travel = {
            "step_id": "checkpoint-step-01",
            "source_location_id": "INTERIOR_01",
            "source_runtime_location_id": "INTERIOR_01",
            "target_source_location_id": "INTERIOR_02",
            "target_location_id": "INTERIOR_02",
            "response_counts": {
                "travel_action_responses": 1,
                "gameplay_validation_responses": 1,
                "transition_validation_responses": 1,
                "transition_narration_responses": 1,
            },
            "response_call_sequences": {
                "travel_action": 2,
                "transition_validation": 3,
                "gameplay_validation": 4,
                "transition_narration": 5,
            },
            "complete": True,
        }
        state_sha256 = "c" * 64
        descriptor = {
            "checkpoint_root": checkpoint_root,
            "state_sha256": state_sha256,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": row_metadata["arm"],
            "fixed_seed": row_metadata["fixed_seed"],
        }
        attestation = {
            "schema_version": 1,
            "source_sha": source_sha,
            "run_id": run_id,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": row_metadata["arm"],
            "fixed_seed": row_metadata["fixed_seed"],
            "step_id": travel["step_id"],
            "source_location_id": travel["source_location_id"],
            "source_runtime_location_id": travel["source_runtime_location_id"],
            "target_source_location_id": travel["target_source_location_id"],
            "target_location_id": travel["target_location_id"],
            "initial_location_id": travel["source_runtime_location_id"],
            "final_location_id": travel["target_location_id"],
            "initial_state_sha256": "b" * 64,
            "state_sha256": state_sha256,
            "initial_time": "day-1 08:00",
            "final_time": "day-1 08:05",
            "travel_proof": travel,
            "persistence": {
                "host_stopped_before_checkpoint": True,
                "canonical_state_hash_verified": True,
                "resume_state_validation": "passed",
            },
            "checkpoint_root": checkpoint_root,
        }
        checkpoint_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        attestation_path = checkpoint_directory / "attestation.json"
        attestation_bytes = json.dumps(
            attestation, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        attestation_path.write_bytes(attestation_bytes)
        evidence.update(
            {
                "checkpoint_travel": travel,
                "resume_checkpoint": descriptor,
                "checkpoint_attestation": {
                    "path": checkpoint_root + "/attestation.json",
                    "sha256": hashlib.sha256(attestation_bytes).hexdigest(),
                },
            }
        )

    def _add_late_guarded_child(self, evidence: dict[str, Any]) -> None:
        run_id = evidence["run_id"]
        child_pid = 10004
        worker_pid = evidence["process_census"]["host_worker_pid"]
        events = self._read_profile_guard_events(evidence)
        worker_startup = next(
            event
            for event in events
            if event.get("event_type") == "guard_startup"
            and event.get("pid") == worker_pid
        )
        child_command_sha256 = "d" * 64
        child_startup = {
            **worker_startup,
            "sequence": 1,
            "pid": child_pid,
            "process_group_id": worker_pid,
            "command_sha256": child_command_sha256,
            "observed_at_ns": worker_startup["observed_at_ns"] + 1,
        }
        child_connect = _guard_network_event(
            child_pid,
            run_id,
            "192.0.2.1",
            8360,
            role="host",
            decision="denied",
            sequence=2,
        )
        child_connect["process_group_id"] = worker_pid
        child_subprocess = _guard_subprocess_attempt_event(
            child_pid, run_id, role="host", sequence=3
        )
        child_subprocess["process_group_id"] = worker_pid
        child_started = _guard_child_started_event(
            worker_pid,
            child_pid,
            run_id,
            process_role="host",
            process_group_id=worker_pid,
            sequence=4,
        )
        child_started["command_sha256"] = child_command_sha256
        events.extend(
            [child_started, child_startup, child_connect, child_subprocess]
        )
        self._write_profile_guard_events(evidence, events)

        census = evidence["process_census"]
        census["python_child_pids"] = [child_pid]
        census["python_pids"] = sorted(
            set(census["launched_pids"])
            | set(census["socket_owner_pids"])
            | set(census["guarded_pids"])
            | {child_pid}
        )
        census["guarded_pids"] = sorted(
            {*census["guarded_pids"], child_pid}
        )
        for phase in ("before_host", "host_ready", "after_teardown"):
            sample, sidecar_path, sidecar = self._read_profile_socket_sidecar(
                evidence, phase
            )
            if phase == "after_teardown":
                sidecar["run_process_pids"] = sorted(
                    {*sidecar["run_process_pids"], child_pid}
                )
                sidecar["guard_startup_pids"] = sorted(
                    {*sidecar["guard_startup_pids"], child_pid}
                )
            self._write_profile_socket_sidecar(
                sample, sidecar_path, sidecar
            )

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
        document = copy_baseline_profile_document()
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
        child_evidence_path = evidence_directory / "adv-summary-child.jsonl"
        child_evidence_path.write_bytes(b"")
        child_evidence = {
            "schema_version": 1,
            "adapter_installed": True,
            "launch_count": 0,
            "launches": [],
            "calls": [],
            "failure_code": None,
            "evidence_path": child_evidence_path.relative_to(PROJECT_ROOT).as_posix(),
            "evidence_sha256": hashlib.sha256(b"").hexdigest(),
            "record_count": 0,
        }
        controller_cwd = str(evidence_directory.resolve())
        host_cwd = str(PROJECT_ROOT / "tmp" / "combat_capture")
        worker_identity = {
            "command": host_command,
            "working_directory": host_cwd,
            "pythonpath": pythonpath,
        }
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
            "invocation_identity": compare_invocation_identity(
                worker_identity, worker_identity
            ),
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
            "adv_summary_child": child_evidence,
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
            "combat_main",
            "dm_main",
            "adventure_summary",
            "dm_validation",
        }
        self.assertEqual(set(payload["responses"]), expected_tasks)
        self.assertEqual(payload["call_count"], len(expected_tasks) + 3)
        self.assertEqual(
            {call["task"] for call in payload["calls"][:-3]},
            expected_tasks,
        )
        self.assertEqual(len(payload["calls"][:-3]), len(expected_tasks))
        self.assertEqual(
            [call["task"] for call in payload["calls"][-3:]],
            ["combat_main", "combat_main", "unlisted_task"],
        )
        self.assertEqual(payload["calls"][-1]["task"], "unlisted_task")
        self.assertTrue(payload["unsupported_call_rejected"])
        self.assertEqual(payload["failure_code"], "router_task_has_no_stub_response")
        self.assertEqual(
            payload["combat_main_repeated_responses"],
            [payload["responses"]["combat_main"]] * 2,
        )
        adventure_summary = payload["responses"]["adventure_summary"]
        self.assertIsInstance(adventure_summary, str)
        self.assertEqual(
            adventure_summary,
            "The provider-free response records the scripted conversation. "
            "It adds no events beyond the supplied history.",
        )
        self.assertEqual(adventure_summary, adventure_summary.strip())

        responses = {
            task: json.loads(response)
            for task, response in payload["responses"].items()
            if task != "adventure_summary"
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
        self.assertEqual(
            set(responses["combat_main"]), {"narration", "combat_round", "actions"}
        )
        self.assertIsInstance(responses["combat_main"]["narration"], str)
        self.assertTrue(responses["combat_main"]["narration"].strip())
        self.assertIs(type(responses["combat_main"]["combat_round"]), int)
        self.assertEqual(responses["combat_main"]["combat_round"], 1)
        self.assertEqual(responses["combat_main"]["actions"], [])
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
        with tempfile.TemporaryDirectory(
            prefix="profile-host-canary-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            fixture_root = Path(temporary_root).resolve()
            sandbox = fixture_root / "sandbox"
            sandbox.mkdir()
            sandbox_relative = sandbox.relative_to(PROJECT_ROOT).as_posix()
            run_id = "canary-e01-p1-" + uuid.uuid4().hex[:12]
            run_directory = (
                PROJECT_ROOT
                / profile_runner.PROFILE_EVIDENCE_ROOT
                / run_id
            )
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
                    f"    {sandbox_relative!r},",
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
                self.assertEqual(
                    report["interpreter"]["executable"], _repository_python()
                )
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

    def _summary_child_adapter_fixture(
        self, sandbox: Path, run_id: str
    ) -> tuple[Path, Path, dict[str, str], list[str]]:
        script = sandbox / "core" / "ai" / "adv_summary.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(PROJECT_ROOT / "core" / "ai" / "adv_summary.py", script)
        evidence_directory = (
            PROJECT_ROOT / profile_runner.PROFILE_EVIDENCE_ROOT / run_id
        )
        evidence_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, evidence_directory, ignore_errors=True)
        guard_events_path = evidence_directory / "guard-events.jsonl"
        guard_events_path.write_bytes(b"")
        evidence_path = evidence_directory / "adv-summary-child.jsonl"
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": expected_guarded_pythonpath(PROJECT_ROOT),
            preflight_stub.RUN_ID_ENV: run_id,
            preflight_stub.GUARD_EVENTS_PATH_ENV: str(guard_events_path),
            preflight_stub.PROCESS_ROLE_ENV: "host",
            preflight_stub.ENABLE_GUARD_ENV: "1",
            preflight_stub.REQUIRE_STARTUP_GUARD_ENV: "1",
            preflight_stub.ACTIVE_GUARD_ENV: "1",
            preflight_stub.EXPECTED_PYTHON_ENV: _repository_python(),
            preflight_stub.EXPECTED_PREFIX_ENV: str(PROJECT_ROOT / ".venv"),
        }
        command = [
            _repository_python(),
            str(script),
            "modules/conversation_history/conversation_history.json",
            "current_location.json",
            "A quiet moment",
            "area_01",
        ]
        return script, evidence_path, environment, command

    def _prepare_real_adv_summary_sandbox(self) -> tuple[Path, str, str]:
        sandbox = PROJECT_ROOT / "tmp" / "combat_capture"
        if sandbox.exists() or sandbox.is_symlink():
            self.skipTest("tmp/combat_capture already exists; refusing to replace it")
        sandbox.mkdir()
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        shutil.copytree(PROJECT_ROOT / "utils", sandbox / "utils")
        for relative in (
            "core/__init__.py",
            "core/ai/__init__.py",
            "core/ai/adv_summary.py",
            "core/managers/__init__.py",
            "core/managers/status_manager.py",
            "schemas/loca_schema.json",
            "schemas/journal_schema.json",
            "modules/Capture_Arena/areas/CTR001.json",
        ):
            source = PROJECT_ROOT / relative
            destination = sandbox / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        area_path = sandbox / "modules" / "Capture_Arena" / "areas" / "CTR001.json"
        area = json.loads(area_path.read_text(encoding="utf-8"))
        location_name = "Waystone Gate"
        if not any(
            isinstance(location, dict) and location.get("name") == location_name
            for location in area.get("locations", [])
        ):
            self.fail("Capture_Arena Waystone Gate fixture is unavailable")

        (sandbox / "party_tracker.json").write_text(
            json.dumps(
                {
                    "module": "Capture_Arena",
                    "worldConditions": {
                        "year": "1",
                        "month": "Hammer",
                        "day": "1",
                        "time": "09:00",
                    },
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (sandbox / "current_location.json").write_text(
            json.dumps({"name": location_name}, ensure_ascii=True),
            encoding="utf-8",
        )
        (sandbox / "journal.json").write_text(
            json.dumps({"entries": []}, ensure_ascii=True),
            encoding="utf-8",
        )
        history_path = (
            sandbox
            / "modules"
            / "conversation_history"
            / "conversation_history.json"
        )
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps(
                [
                    {
                        "role": "assistant",
                        "content": "The party entered the Waystone Gate.",
                    },
                    {"role": "user", "content": "We look around the yard."},
                ],
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        return sandbox, location_name, str(area.get("areaId") or "CTR001")

    def test_real_guarded_adv_summary_child_returns_and_persists(self) -> None:
        required_area = PROJECT_ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001.json"
        if not required_area.is_file():
            self.skipTest("missing required path: %s" % required_area)
        sandbox, location_name, area_id = self._prepare_real_adv_summary_sandbox()
        run_id = "summary-child-real-" + uuid.uuid4().hex[:12]
        evidence_directory = PROJECT_ROOT / GUARD_EVENT_ROOT / run_id
        evidence_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, evidence_directory, ignore_errors=True)
        guard_events_path = evidence_directory / "guard-events.jsonl"
        guard_events_path.write_bytes(b"")
        child_evidence_path = evidence_directory / "adv-summary-child.jsonl"
        child_command = [
            _repository_python(),
            str(sandbox / "core" / "ai" / "adv_summary.py"),
            "modules/conversation_history/conversation_history.json",
            "current_location.json",
            location_name,
            area_id,
        ]
        source_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

        def run_git_for_test(
            command: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[Any]:
            self.assertEqual(command[:2], ["git", "show"])
            return subprocess.run(command, **kwargs)

        git_guard_patch = mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=run_git_for_test,
        )
        git_guard_patch.start()
        self.addCleanup(git_guard_patch.stop)
        environment = build_guarded_environment(
            {"PATH": os.environ.get("PATH", "")},
            project_root=PROJECT_ROOT,
            process_role="host",
            run_id=run_id,
            guard_events_path=guard_events_path,
        )
        wrapper_code = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from scripts.live_gate_preflight_stub import "
            "install_adv_summary_preflight_host_interceptor\n"
            "sandbox = Path.cwd()\n"
            "interceptor = install_adv_summary_preflight_host_interceptor(\n"
            f"    source_sha={source_sha!r}, sandbox_root=sandbox,\n"
            "    evidence_path=Path(sys.argv[2])\n"
            ")\n"
            "try:\n"
            "    results = []\n"
            "    for _ in range(2):\n"
            "        result = interceptor._run_adv_summary(\n"
            "            json.loads(sys.argv[1]), check=True, capture_output=True, text=True\n"
            "        )\n"
            "        results.append(result.returncode)\n"
            "    print(json.dumps({\n"
            "        'pid': os.getpid(), 'launches': interceptor.launches,\n"
            "        'calls': interceptor.calls, 'failure_code': interceptor.failure_code,\n"
            "        'returncodes': results,\n"
            "    }, sort_keys=True, separators=(',', ':')))\n"
            "finally:\n"
            "    interceptor.cleanup()\n"
        )
        with tempfile.TemporaryDirectory(
            prefix="summary-child-driver-", dir=PROJECT_ROOT / "tmp"
        ) as driver_directory:
            driver_path = Path(driver_directory) / "driver.py"
            driver_path.write_text(wrapper_code, encoding="ascii")
            process = subprocess.Popen(
                [
                    _repository_python(),
                    str(driver_path),
                    json.dumps(child_command),
                    str(child_evidence_path),
                ],
                cwd=sandbox,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                self.fail(
                    "real guarded summary child timed out; "
                    + (stderr[-2000:] if stderr else "")
                )
        self.assertEqual(process.returncode, 0, stderr[-4000:])
        wrapper_result = json.loads(stdout.strip().splitlines()[-1])
        self.assertIsNone(wrapper_result["failure_code"])
        self.assertEqual(wrapper_result["returncodes"], [0, 0])
        self.assertEqual(len(wrapper_result["launches"]), 2)
        self.assertTrue(
            all(
                launch["summary_child_succeeded"]
                for launch in wrapper_result["launches"]
            )
        )
        self.assertEqual(
            [
                launch["call_evidence_count"]
                for launch in wrapper_result["launches"]
            ],
            [2, 2],
        )
        self.assertEqual(
            [call["response_kind"] for call in wrapper_result["calls"]],
            ["summary_text", "location_json", "summary_text", "location_json"],
        )

        child_records = preflight_stub._read_adv_summary_child_records(
            child_evidence_path
        )
        self.assertEqual(len(child_records), 2)
        self.assertEqual(len({record["pid"] for record in child_records}), 2)
        for record in child_records:
            self.assertTrue(record["summary_output_persisted"])
            self.assertFalse(record["provider_request_attempted"])
            self.assertEqual(record["router_call_count"], 2)
            self.assertEqual(record["discarded_json_writes"], [])
            self.assertEqual(len(record["canonical_writes"]), 6)
            self.assertEqual(
                [write["sequence"] for write in record["canonical_writes"]],
                [1, 2, 3, 4, 5, 6],
            )
            self.assertEqual(
                {write["path"] for write in record["canonical_writes"]},
                {
                    "summary_dump.json",
                    "trimmed_summary_dump.json",
                    "dialogue_summary.json",
                    "journal.json",
                    "modules/Capture_Arena/areas/%s.json" % area_id,
                },
            )
            self.assertEqual(
                len(
                    {
                        write["retained_artifact"]["path"]
                        for write in record["canonical_writes"]
                    }
                ),
                6,
            )
        record = child_records[-1]
        validator_args = {
            "run_id": run_id,
            "command_sha256": wrapper_result["launches"][0]["command_sha256"],
            "environment_sha256": wrapper_result["launches"][0][
            "environment_sha256"
            ],
            "source_sha": source_sha,
            "pythonpath": environment["PYTHONPATH"],
            "script_sha256": hashlib.sha256(
                (sandbox / "core" / "ai" / "adv_summary.py").read_bytes()
            ).hexdigest(),
            "working_directory": str(sandbox),
            "interpreter": wrapper_result["launches"][0]["interpreter"],
        }
        self.assertTrue(
            preflight_stub._validate_adv_summary_child_record(record, **validator_args)
        )

        blocked = dict(record)
        blocked["stub_failure_code"] = "router_task_has_no_stub_response"
        self.assertFalse(
            preflight_stub._validate_adv_summary_child_record(blocked, **validator_args)
        )
        failed = dict(wrapper_result["launches"][0])
        failed["returncode"] = 1
        self.assertNotEqual(failed["returncode"], 0)
        discarded = dict(record)
        discarded["canonical_writes"] = []
        discarded["summary_output_persisted"] = False
        self.assertFalse(
            preflight_stub._validate_adv_summary_child_record(
                discarded, **validator_args
            )
        )

        launch = wrapper_result["launches"][0]
        raw_evidence = child_evidence_path.read_bytes()
        guard_events = [
            json.loads(line)
            for line in guard_events_path.read_text(encoding="ascii").splitlines()
            if line
        ]
        profile_child_evidence = {
            "schema_version": 1,
            "adapter_installed": True,
            "launch_count": len(wrapper_result["launches"]),
            "launches": wrapper_result["launches"],
            "calls": wrapper_result["calls"],
            "failure_code": None,
            "evidence_path": child_evidence_path.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "evidence_sha256": hashlib.sha256(raw_evidence).hexdigest(),
            "record_count": len(child_records),
        }
        retained_artifacts = retained_evidence.retain_summary_child_artifacts(
            sandbox,
            evidence_directory,
            run_id=run_id,
            summary_child=profile_child_evidence,
        )
        self.assertIsInstance(retained_artifacts, dict)
        profile_validator_args = {
            "run_id": run_id,
            "source_sha": source_sha,
            "pythonpath": environment["PYTHONPATH"],
            "worker_pid": wrapper_result["pid"],
            "worker_interpreter": launch["interpreter"],
            "guard_events": guard_events,
            "evidence_directory": evidence_directory,
            "retained_artifacts": retained_artifacts,
        }
        expected_parent_launch_pids = sorted(
            process_pid
            for launch_record in wrapper_result["launches"]
            for process_pid in (
                launch_record["prelaunch_canary_pid"],
                launch_record["child_pid"],
            )
        )
        command_hash = wrapper_result["launches"][0]["command_sha256"]
        parent_events = [
            event for event in guard_events if event["pid"] == wrapper_result["pid"]
        ]
        self.assertEqual(
            sorted(
                event["child_pid"]
                for event in parent_events
                if event["event_type"] == "subprocess_started"
                and event["command_sha256"] == command_hash
            ),
            expected_parent_launch_pids,
        )
        self.assertEqual(
            sum(
                event["event_type"] == "subprocess_attempt"
                and event["decision"] == "allowed"
                and event["command_sha256"] == command_hash
                for event in parent_events
            ),
            len(expected_parent_launch_pids),
        )
        shutil.rmtree(sandbox)
        self.assertFalse(sandbox.exists())
        original_safe_source_path = preflight_profiles._safe_source_path
        changed_source_path = evidence_directory / "changed-adv_summary.py"
        changed_source_path.write_bytes(b"# changed live source\n")

        def reject_live_source(
            root: Path, relative: str | Path, label: str
        ) -> Path:
            if Path(relative).as_posix() == "core/ai/adv_summary.py":
                raise ProfileValidationError("live source is unavailable")
            return original_safe_source_path(root, relative, label)

        def return_changed_live_source(
            root: Path, relative: str | Path, label: str
        ) -> Path:
            if Path(relative).as_posix() == "core/ai/adv_summary.py":
                return changed_source_path
            return original_safe_source_path(root, relative, label)

        for source_state, resolver in (
            ("unavailable", reject_live_source),
            ("changed", return_changed_live_source),
        ):
            with self.subTest(live_source=source_state), mock.patch.object(
                preflight_profiles,
                "_safe_source_path",
                side_effect=resolver,
            ):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    profile_child_evidence,
                    **profile_validator_args,
                )

        failed_profile_evidence = json.loads(
            json.dumps(profile_child_evidence, ensure_ascii=True)
        )
        failed_profile_evidence["launches"][0]["returncode"] = 1
        with self.assertRaisesRegex(
            ProfileValidationError, "summary child launch identity differs"
        ):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                failed_profile_evidence,
                **profile_validator_args,
            )

        source_artifact = next(
            item
            for item in retained_artifacts["artifacts"]
            if item["role"] == "script_source"
        )
        source_artifact_path = PROJECT_ROOT / source_artifact["path"]
        original_source_artifact = source_artifact_path.read_bytes()
        tampered_source_artifact = original_source_artifact + b"\n# tampered\n"
        missing_source_manifest = json.loads(
            json.dumps(retained_artifacts, ensure_ascii=True)
        )
        missing_source_manifest["artifacts"] = [
            item
            for item in missing_source_manifest["artifacts"]
            if item["role"] != "script_source"
        ]
        with self.assertRaisesRegex(
            ProfileValidationError, "summary child retained artifacts are incomplete"
        ):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **{
                    **profile_validator_args,
                    "retained_artifacts": missing_source_manifest,
                },
            )
        try:
            source_artifact_path.write_bytes(tampered_source_artifact)
            with self.assertRaisesRegex(
                ProfileValidationError, "summary child retained artifact hash differs"
            ):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    profile_child_evidence,
                    **profile_validator_args,
                )

            tampered_manifest = json.loads(
                json.dumps(retained_artifacts, ensure_ascii=True)
            )
            tampered_descriptor = next(
                item
                for item in tampered_manifest["artifacts"]
                if item["role"] == "script_source"
            )
            tampered_descriptor["sha256"] = hashlib.sha256(
                tampered_source_artifact
            ).hexdigest()
            tampered_descriptor["size_bytes"] = len(tampered_source_artifact)
            tampered_validator_args = {
                **profile_validator_args,
                "retained_artifacts": tampered_manifest,
            }
            with self.assertRaisesRegex(
                ProfileValidationError,
                "retained summary child source differs from declared source SHA",
            ):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    profile_child_evidence,
                    **tampered_validator_args,
                )
        finally:
            source_artifact_path.write_bytes(original_source_artifact)

        wrong_source_args = {
            **profile_validator_args,
            "source_sha": "a" * 40,
        }
        with self.assertRaisesRegex(
            ProfileValidationError,
            "trusted summary child source identity is unavailable",
        ):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **wrong_source_args,
            )

        from scripts import live_gate_preflight_profile_runner as profile_runner

        trusted_source_snapshot = (
            source_sha,
            profile_runner._git_source_bytes_at_sha(
                source_sha, "core/ai/adv_summary.py"
            ),
        )
        with mock.patch.object(
            profile_runner,
            "_git_source_bytes_at_sha",
            side_effect=AssertionError("late Git source lookup"),
        ):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **{
                    **profile_validator_args,
                    "trusted_summary_source": trusted_source_snapshot,
                },
            )
            with self.assertRaisesRegex(
                ProfileValidationError,
                "trusted summary child source snapshot identity differs",
            ):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    profile_child_evidence,
                    **{
                        **profile_validator_args,
                        "trusted_summary_source": (
                            "b" * 40,
                            trusted_source_snapshot[1],
                        ),
                    },
                )

        final_artifact = next(
            item
            for item in retained_artifacts["artifacts"]
            if item["role"] == "final_output"
        )
        final_path = PROJECT_ROOT / final_artifact["path"]
        original_final = final_path.read_bytes()
        final_path.unlink()
        with self.assertRaisesRegex(ProfileValidationError, "missing or escapes"):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **profile_validator_args,
            )
        final_path.write_bytes(original_final)

        first_snapshot = (
            PROJECT_ROOT
            / child_records[0]["canonical_writes"][0]["retained_artifact"]["path"]
        )
        original_snapshot = first_snapshot.read_bytes()
        first_snapshot.write_bytes(original_snapshot + b" ")
        with self.assertRaisesRegex(ProfileValidationError, "hash differs"):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **profile_validator_args,
            )
        first_snapshot.write_bytes(original_snapshot)

        replacement = evidence_directory / "replacement-artifact.json"
        replacement.write_bytes(original_final)
        final_path.unlink()
        final_path.symlink_to(replacement)
        with self.assertRaisesRegex(ProfileValidationError, "symlink"):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                profile_child_evidence,
                **profile_validator_args,
            )
        final_path.unlink()
        final_path.write_bytes(original_final)
        replacement.unlink()

        traversed_profile_evidence = json.loads(
            json.dumps(profile_child_evidence, ensure_ascii=True)
        )
        traversed_record = dict(child_records[0])
        traversed_record["canonical_writes"] = [
            dict(write) for write in traversed_record["canonical_writes"]
        ]
        traversed_record["canonical_writes"][0]["retained_artifact"] = dict(
            traversed_record["canonical_writes"][0]["retained_artifact"]
        )
        traversed_record["canonical_writes"][0]["retained_artifact"]["path"] = (
            evidence_directory.relative_to(PROJECT_ROOT).as_posix()
            + "/../../outside.json"
        )
        traversed_raw = b"".join(
            json.dumps(
                record_value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
            for record_value in (traversed_record, child_records[1])
        )
        original_records_raw = child_evidence_path.read_bytes()
        child_evidence_path.write_bytes(traversed_raw)
        traversed_profile_evidence["evidence_sha256"] = hashlib.sha256(
            traversed_raw
        ).hexdigest()
        with self.assertRaisesRegex(
            ProfileValidationError, "retained write provenance differs"
        ):
            preflight_profiles._validate_adv_summary_child_evidence(
                PROJECT_ROOT,
                traversed_profile_evidence,
                **profile_validator_args,
            )
        child_evidence_path.write_bytes(original_records_raw)

        for rejected_record in (blocked, discarded):
            rejected_raw = (
                json.dumps(
                    rejected_record,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
                + b"\n"
            )
            child_evidence_path.write_bytes(rejected_raw)
            rejected_profile_evidence = dict(profile_child_evidence)
            rejected_profile_evidence["evidence_sha256"] = hashlib.sha256(
                rejected_raw
            ).hexdigest()
            with self.assertRaises(ProfileValidationError):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    rejected_profile_evidence,
                    **profile_validator_args,
                )
        child_evidence_path.write_bytes(raw_evidence)

    def test_summary_child_retention_accepts_host_journal_rewrite_after_child(
        self,
    ) -> None:
        required_area = PROJECT_ROOT / "modules" / "Capture_Arena" / "areas" / "CTR001.json"
        if not required_area.is_file():
            self.skipTest("missing required path: %s" % required_area)
        sandbox, location_name, area_id = self._prepare_real_adv_summary_sandbox()
        run_id = "summary-child-journal-rewrite-" + uuid.uuid4().hex[:12]
        evidence_directory = PROJECT_ROOT / GUARD_EVENT_ROOT / run_id
        evidence_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, evidence_directory, ignore_errors=True)
        guard_events_path = evidence_directory / "guard-events.jsonl"
        guard_events_path.write_bytes(b"")
        child_evidence_path = evidence_directory / "adv-summary-child.jsonl"
        child_command = [
            _repository_python(),
            str(sandbox / "core" / "ai" / "adv_summary.py"),
            "modules/conversation_history/conversation_history.json",
            "current_location.json",
            location_name,
            area_id,
        ]
        source_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        git_guard_patch = mock.patch(
            "scripts.live_gate_preflight_safety.run_guarded_subprocess",
            side_effect=lambda command, **kwargs: subprocess.run(command, **kwargs),
        )
        git_guard_patch.start()
        self.addCleanup(git_guard_patch.stop)
        environment = build_guarded_environment(
            {"PATH": os.environ.get("PATH", "")},
            project_root=PROJECT_ROOT,
            process_role="host",
            run_id=run_id,
            guard_events_path=guard_events_path,
        )
        wrapper_code = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from scripts.live_gate_preflight_stub import "
            "install_adv_summary_preflight_host_interceptor\n"
            "sandbox = Path.cwd()\n"
            "interceptor = install_adv_summary_preflight_host_interceptor(\n"
            f"    source_sha={source_sha!r}, sandbox_root=sandbox,\n"
            "    evidence_path=Path(sys.argv[2])\n"
            ")\n"
            "try:\n"
            "    result = interceptor._run_adv_summary(\n"
            "        json.loads(sys.argv[1]), check=True, capture_output=True, text=True\n"
            "    )\n"
            "    print(json.dumps({\n"
            "        'pid': os.getpid(), 'launches': interceptor.launches,\n"
            "        'calls': interceptor.calls, 'failure_code': interceptor.failure_code,\n"
            "        'returncode': result.returncode,\n"
            "    }, sort_keys=True, separators=(',', ':')))\n"
            "finally:\n"
            "    interceptor.cleanup()\n"
        )
        with tempfile.TemporaryDirectory(
            prefix="summary-child-journal-rewrite-", dir=PROJECT_ROOT / "tmp"
        ) as driver_directory:
            driver_path = Path(driver_directory) / "driver.py"
            driver_path.write_text(wrapper_code, encoding="ascii")
            process = subprocess.Popen(
                [
                    _repository_python(),
                    str(driver_path),
                    json.dumps(child_command),
                    str(child_evidence_path),
                ],
                cwd=sandbox,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                self.fail(
                    "real guarded summary child timed out; "
                    + (stderr[-2000:] if stderr else "")
                )
        self.assertEqual(process.returncode, 0, stderr[-4000:])
        wrapper_result = json.loads(stdout.strip().splitlines()[-1])
        self.assertIsNone(wrapper_result["failure_code"])
        self.assertEqual(wrapper_result["returncode"], 0)

        child_records = preflight_stub._read_adv_summary_child_records(
            child_evidence_path
        )
        self.assertEqual(len(child_records), 1)

        # Simulate the host's own in-process location-transition journal
        # write (core/ai/cumulative_summary.py update_journal_with_summary)
        # running after the child subprocess has already exited and
        # recorded its own last write.
        journal_path = sandbox / "journal.json"
        original_journal = journal_path.read_bytes()
        rewritten_journal = json.dumps(
            {"entries": [{"source": "host_checkpoint_rewrite"}]},
            ensure_ascii=True,
        ).encode("ascii")
        self.assertNotEqual(rewritten_journal, original_journal)
        journal_path.write_bytes(rewritten_journal)

        raw_evidence = child_evidence_path.read_bytes()
        profile_child_evidence = {
            "schema_version": 1,
            "adapter_installed": True,
            "launch_count": 1,
            "launches": wrapper_result["launches"],
            "calls": wrapper_result["calls"],
            "failure_code": None,
            "evidence_path": child_evidence_path.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "evidence_sha256": hashlib.sha256(raw_evidence).hexdigest(),
            "record_count": len(child_records),
        }
        retained_artifacts = retained_evidence.retain_summary_child_artifacts(
            sandbox,
            evidence_directory,
            run_id=run_id,
            summary_child=profile_child_evidence,
        )
        self.assertIsInstance(retained_artifacts, dict)

        journal_artifact = next(
            item
            for item in retained_artifacts["artifacts"]
            if item.get("source_path") == "tmp/combat_capture/journal.json"
        )
        self.assertFalse(journal_artifact["final_write_matches_last_write"])
        self.assertEqual(
            journal_artifact["provenance"],
            "host_rewrote_after_child_final_state_before_cleanup",
        )
        self.assertEqual(
            journal_artifact["sha256"], hashlib.sha256(rewritten_journal).hexdigest()
        )
        self.assertNotEqual(
            journal_artifact["sha256"], journal_artifact["last_write"]["sha256"]
        )
        other_final_outputs = [
            item
            for item in retained_artifacts["artifacts"]
            if item.get("role") == "final_output"
            and item.get("source_path") != "tmp/combat_capture/journal.json"
        ]
        self.assertTrue(other_final_outputs)
        for item in other_final_outputs:
            self.assertTrue(item["final_write_matches_last_write"])
            self.assertEqual(
                item["provenance"],
                "canonical_json_write_final_state_before_cleanup",
            )

        guard_events = [
            json.loads(line)
            for line in guard_events_path.read_text(encoding="ascii").splitlines()
            if line
        ]
        preflight_profiles._validate_adv_summary_child_evidence(
            PROJECT_ROOT,
            profile_child_evidence,
            run_id=run_id,
            source_sha=source_sha,
            pythonpath=environment["PYTHONPATH"],
            worker_pid=wrapper_result["pid"],
            worker_interpreter=wrapper_result["launches"][0]["interpreter"],
            guard_events=guard_events,
            evidence_directory=evidence_directory,
            retained_artifacts=retained_artifacts,
        )

    def test_summary_child_subprocess_reconciliation_counts_canary_and_child(
        self,
    ) -> None:
        worker_pid = 51001
        canary_pid = 51002
        child_pid = 51003
        command_hash = "a" * 64
        expected = {command_hash: [canary_pid, child_pid]}

        def launch_events(pids: list[int]) -> list[dict[str, Any]]:
            events: list[dict[str, Any]] = []
            sequence = 1
            for pid in pids:
                events.extend(
                    (
                        {
                            "pid": worker_pid,
                            "sequence": sequence,
                            "event_type": "subprocess_attempt",
                            "decision": "allowed",
                            "command_sha256": command_hash,
                        },
                        {
                            "pid": worker_pid,
                            "sequence": sequence + 1,
                            "event_type": "subprocess_started",
                            "command_sha256": command_hash,
                            "child_pid": pid,
                        },
                    )
                )
                sequence += 2
            return events

        preflight_profiles._validate_summary_child_subprocess_authorization(
            launch_events([canary_pid, child_pid]),
            worker_pid=worker_pid,
            expected_children_by_hash=expected,
        )

        with self.assertRaisesRegex(
            ProfileValidationError,
            "summary child subprocess authorization is not reconciled",
        ):
            preflight_profiles._validate_summary_child_subprocess_authorization(
                launch_events([child_pid]),
                worker_pid=worker_pid,
                expected_children_by_hash=expected,
            )

        with self.assertRaisesRegex(
            ProfileValidationError,
            "summary child subprocess authorization is not reconciled",
        ):
            preflight_profiles._validate_summary_child_subprocess_authorization(
                launch_events([canary_pid, child_pid, child_pid + 1]),
                worker_pid=worker_pid,
                expected_children_by_hash=expected,
            )

    def test_summary_child_source_hash_is_checked_before_module_execution(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="summary-child-source-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            sandbox_source = sandbox / "utils" / "llm_router.py"
            sandbox_source.parent.mkdir()
            trusted_source = PROJECT_ROOT / "utils" / "llm_router.py"
            shutil.copyfile(trusted_source, sandbox_source)
            identity = {
                "working_directory": str(sandbox),
                "source_root": str(PROJECT_ROOT),
            }
            hook = preflight_stub._AdvSummaryChildImportHook()
            verified = hook._verified_module_source(
                "utils.llm_router", str(sandbox_source), identity
            )
            hook.verified_sources["utils.llm_router"] = verified
            with mock.patch.object(
                preflight_stub, "_ADV_SUMMARY_CHILD_RECEIPT", identity
            ):
                hook.verify_source_before_execution(
                    "utils.llm_router", str(sandbox_source)
                )

            sandbox_source.write_text(
                sandbox_source.read_text(encoding="utf-8") + "\n# altered\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ImportError, "hash differs"):
                hook._verified_module_source(
                    "utils.llm_router", str(sandbox_source), identity
                )

    def test_summary_child_interceptor_rejects_altered_script_and_command(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="summary-child-launch-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            interceptor: Any = None
            try:
                with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    try:
                        script.write_text(
                            script.read_text(encoding="utf-8") + "\n# altered\n",
                            encoding="utf-8",
                        )
                        with mock.patch.object(
                            preflight_stub,
                            "run_startup_process_canary",
                        ) as canary:
                            with self.assertRaisesRegex(
                                RouterStubError, "script differs"
                            ):
                                interceptor._run_adv_summary(
                                    command,
                                    check=True,
                                    capture_output=True,
                                    text=True,
                                )
                            canary.assert_not_called()
                        self.assertEqual(
                            interceptor.failure_code,
                            "summary_child_script_identity_mismatch",
                        )
                    finally:
                        interceptor.cleanup()
            finally:
                os.chdir(original_cwd)

        with tempfile.TemporaryDirectory(
            prefix="summary-child-command-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            _script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            interceptor: Any = None
            try:
                with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    try:
                        altered = list(command)
                        altered[2] = "other-history.json"
                        with mock.patch.object(
                            preflight_stub,
                            "run_startup_process_canary",
                        ) as canary:
                            with self.assertRaisesRegex(
                                RouterStubError, "command identity differs"
                            ):
                                interceptor._run_adv_summary(
                                    altered,
                                    check=True,
                                    capture_output=True,
                                    text=True,
                                )
                            canary.assert_not_called()
                        self.assertEqual(
                            interceptor.failure_code,
                            "summary_child_command_identity_mismatch",
                        )
                    finally:
                        interceptor.cleanup()
            finally:
                os.chdir(original_cwd)

    def test_summary_child_interceptor_rejects_a_blocked_launch_record(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="summary-child-authorized-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            interceptor: Any = None
            original_subprocess_run: Any = None
            try:
                with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    original_subprocess_run = interceptor.original_run
                    canary_pid = 45001
                    child_pid = 45002
                    interpreter = {
                        "executable": command[0],
                        "prefix": environment[preflight_stub.EXPECTED_PREFIX_ENV],
                        "base_prefix": sys.base_prefix,
                    }
                    canary = {
                        "command": command,
                        "command_sha256": preflight_stub._command_sha256(command),
                        "working_directory": str(sandbox),
                        "process_role": "host",
                        "pid": canary_pid,
                        "startup_observed_at_ns": 123456,
                        "guard_active": True,
                        "non_loopback_connect_denied": True,
                        "subprocess_launch_denied": True,
                        "environment_sha256": "e" * 64,
                        "interpreter": interpreter,
                    }
                    script_sha256 = hashlib.sha256(script.read_bytes()).hexdigest()
                    child_record = {
                        "schema_version": 1,
                        "run_id": run_id,
                        "pid": child_pid,
                        "process_group_id": os.getpgrp(),
                        "process_role": "host",
                        "command_sha256": canary["command_sha256"],
                        "environment_sha256": canary["environment_sha256"],
                        "startup_observed_at_ns": 234567,
                        "interpreter": interpreter,
                        "source_sha": "a" * 40,
                        "pythonpath": environment["PYTHONPATH"],
                        "script_sha256": script_sha256,
                        "working_directory": str(sandbox),
                        "router_call_count": 1,
                        "task": "adventure_summary",
                        "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
                        "source_line": 42,
                        "source_file_sha256": script_sha256,
                        "stub_failure_code": "router_task_has_no_stub_response",
                        "expected_summary_call_blocked": True,
                        "provider_request_attempted": False,
                        "summary_output_persisted": False,
                        "discarded_json_writes": [
                            {
                                "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
                                "basename": name,
                            }
                            for name in (
                                "summary_dump.json",
                                "trimmed_summary_dump.json",
                                "dialogue_summary.json",
                            )
                        ],
                    }

                    def fail_after_record(*_args: Any, **_kwargs: Any) -> None:
                        evidence_path.write_bytes(
                            json.dumps(
                                child_record,
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("ascii")
                            + b"\n"
                        )
                        raise subprocess.CalledProcessError(1, command)

                    original_run = mock.Mock(side_effect=fail_after_record)
                    interceptor.original_run = original_run
                    authorization = mock.MagicMock()
                    with mock.patch.object(
                        preflight_stub,
                        "run_startup_process_canary",
                        return_value=canary,
                    ), mock.patch.object(
                        preflight_stub,
                        "authorize_subprocess_launch",
                        return_value=authorization,
                    ) as authorize:
                        with self.assertRaises(subprocess.CalledProcessError):
                            interceptor._run_adv_summary(
                                command,
                                check=True,
                                capture_output=True,
                                text=True,
                            )

                    authorize.assert_called_once()
                    authorized_command = authorize.call_args.args[0]
                    authorized_options = authorize.call_args.kwargs
                    self.assertEqual(authorized_command, command)
                    self.assertEqual(authorized_options["cwd"], str(sandbox))
                    self.assertEqual(
                        authorized_options["env"][preflight_stub.ADV_SUMMARY_CHILD_MODE_ENV],
                        preflight_stub.ADV_SUMMARY_CHILD_MODE,
                    )
                    original_run.assert_called_once()
                    self.assertEqual(
                        interceptor.failure_code, "summary_child_process_failed"
                    )
                    self.assertEqual(interceptor.launches[0]["child_pid"], child_pid)
                    self.assertFalse(
                        interceptor.launches[0]["summary_child_succeeded"]
                    )
                    self.assertEqual(interceptor.launches[0]["returncode"], 1)
                    self.assertEqual(len(interceptor.calls), 0)
                    self.assertEqual(
                        preflight_stub._read_adv_summary_child_records(evidence_path),
                        [child_record],
                    )
            finally:
                if interceptor is not None:
                    if original_subprocess_run is not None:
                        interceptor.original_run = original_subprocess_run
                    interceptor.cleanup()
                os.chdir(original_cwd)

    def test_summary_child_interceptor_does_not_launch_without_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="summary-child-unauthorized-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            _script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            interceptor: Any = None
            original_subprocess_run: Any = None
            try:
                with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    original_subprocess_run = interceptor.original_run
                    canary = {
                        "command": command,
                        "command_sha256": preflight_stub._command_sha256(command),
                        "working_directory": str(sandbox),
                        "process_role": "host",
                        "pid": 46001,
                        "startup_observed_at_ns": 123456,
                        "guard_active": True,
                        "non_loopback_connect_denied": True,
                        "subprocess_launch_denied": True,
                        "environment_sha256": "f" * 64,
                        "interpreter": {
                            "executable": command[0],
                            "prefix": environment[preflight_stub.EXPECTED_PREFIX_ENV],
                            "base_prefix": sys.base_prefix,
                        },
                    }
                    original_run = mock.Mock()
                    interceptor.original_run = original_run
                    with mock.patch.object(
                        preflight_stub,
                        "run_startup_process_canary",
                        return_value=canary,
                    ), mock.patch.object(
                        preflight_stub,
                        "authorize_subprocess_launch",
                        side_effect=NetworkGuardError("one-use authorization absent"),
                    ) as authorize:
                        with self.assertRaisesRegex(
                            NetworkGuardError, "one-use authorization absent"
                        ):
                            interceptor._run_adv_summary(
                                command,
                                check=True,
                                capture_output=True,
                                text=True,
                            )
                    authorize.assert_called_once()
                    original_run.assert_not_called()
                    self.assertEqual(
                        interceptor.failure_code,
                        "summary_child_launch_failed_NetworkGuardError",
                    )
                    self.assertIsNone(
                        interceptor.launches[0]["child_pid"]
                    )
            finally:
                if interceptor is not None:
                    if original_subprocess_run is not None:
                        interceptor.original_run = original_subprocess_run
                    interceptor.cleanup()
                os.chdir(original_cwd)

    def test_summary_child_hooks_refuse_missing_network_guard(self) -> None:
        meta_path_before = list(sys.meta_path)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            preflight_stub, "_ADV_SUMMARY_CHILD_HOOK", None
        ):
            with self.assertRaisesRegex(
                RouterStubError, "active sanitized network guard"
            ):
                preflight_stub.install_adv_summary_preflight_child_hooks()
        self.assertEqual(sys.meta_path, meta_path_before)

    def test_summary_child_interceptor_rejects_secrets_and_bad_canary(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="summary-child-guards-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            _script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            try:
                with mock.patch.dict(
                    os.environ,
                    {**environment, "SYNTHETIC_API_KEY": "do-not-leak"},
                    clear=True,
                ), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    try:
                        with mock.patch.object(
                            preflight_stub, "run_startup_process_canary"
                        ) as canary:
                            with self.assertRaisesRegex(
                                RouterStubError, "not secret-free"
                            ) as raised:
                                interceptor._run_adv_summary(
                                    command,
                                    check=True,
                                    capture_output=True,
                                    text=True,
                                )
                            canary.assert_not_called()
                            self.assertNotIn("do-not-leak", str(raised.exception))
                        self.assertEqual(
                            interceptor.failure_code,
                            "summary_child_environment_contains_secret",
                        )
                    finally:
                        interceptor.cleanup()
            finally:
                os.chdir(original_cwd)

        with tempfile.TemporaryDirectory(
            prefix="summary-child-canary-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox = Path(temp_root)
            run_id = "summary-child-test-" + uuid.uuid4().hex[:12]
            _script, evidence_path, environment, command = (
                self._summary_child_adapter_fixture(sandbox, run_id)
            )
            original_cwd = Path.cwd()
            os.chdir(sandbox)
            try:
                with mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(preflight_stub, "_require_network_guard"), \
                    mock.patch.object(preflight_stub, "require_startup_guard_active"), \
                    mock.patch.object(preflight_stub, "require_current_invocation_matches_startup"), \
                    mock.patch.object(preflight_stub, "require_sanitized_environment"):
                    interceptor = (
                        preflight_stub.install_adv_summary_preflight_host_interceptor(
                            source_sha="a" * 40,
                            sandbox_root=sandbox,
                            evidence_path=evidence_path,
                        )
                    )
                    canary_record = {
                        "command": command,
                        "command_sha256": "0" * 64,
                        "working_directory": str(sandbox),
                        "process_role": "host",
                        "pid": 12345,
                        "startup_observed_at_ns": 123456,
                        "guard_active": True,
                        "non_loopback_connect_denied": True,
                        "subprocess_launch_denied": True,
                        "environment_sha256": "e" * 64,
                        "interpreter": {
                            "executable": command[0],
                            "prefix": environment[preflight_stub.EXPECTED_PREFIX_ENV],
                            "base_prefix": sys.base_prefix,
                        },
                    }
                    try:
                        with mock.patch.object(
                            preflight_stub,
                            "run_startup_process_canary",
                            return_value=canary_record,
                        ), mock.patch.object(
                            preflight_stub,
                            "authorize_subprocess_launch",
                            side_effect=AssertionError("unauthorized launch reached Popen"),
                        ):
                            with self.assertRaisesRegex(
                                RouterStubError, "startup canary did not reconcile"
                            ):
                                interceptor._run_adv_summary(
                                    command,
                                    check=True,
                                    capture_output=True,
                                    text=True,
                                )
                        self.assertIsNone(
                            interceptor.launches[0]["prelaunch_canary_pid"]
                        )
                        self.assertEqual(
                            interceptor.failure_code,
                            "summary_child_launch_failed_RouterStubError",
                        )
                    finally:
                        interceptor.cleanup()
            finally:
                os.chdir(original_cwd)

    def test_summary_child_record_rejects_legacy_blocked_evidence(
        self,
    ) -> None:
        run_id = "summary-child-record-" + uuid.uuid4().hex[:12]
        command_sha256 = "a" * 64
        environment_sha256 = "b" * 64
        script_sha256 = "c" * 64
        interpreter = {
            "executable": _repository_python(),
            "prefix": str(PROJECT_ROOT / ".venv"),
            "base_prefix": sys.base_prefix,
        }
        record = {
            "schema_version": 1,
            "run_id": run_id,
            "pid": 12345,
            "process_group_id": 12300,
            "process_role": "host",
            "command_sha256": command_sha256,
            "environment_sha256": environment_sha256,
            "startup_observed_at_ns": 123456,
            "interpreter": interpreter,
            "source_sha": "d" * 40,
            "pythonpath": expected_guarded_pythonpath(PROJECT_ROOT),
            "script_sha256": script_sha256,
            "working_directory": str(PROJECT_ROOT / "tmp" / "combat_capture"),
            "router_call_count": 1,
            "task": "adventure_summary",
            "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
            "source_line": 42,
            "source_file_sha256": script_sha256,
            "stub_failure_code": "router_task_has_no_stub_response",
            "expected_summary_call_blocked": True,
            "provider_request_attempted": False,
            "summary_output_persisted": False,
            "discarded_json_writes": [
                {
                    "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
                    "basename": name,
                }
                for name in (
                    "summary_dump.json",
                    "trimmed_summary_dump.json",
                    "dialogue_summary.json",
                )
            ],
        }
        validator = preflight_stub._validate_adv_summary_child_record
        validation = {
            "run_id": run_id,
            "command_sha256": command_sha256,
            "environment_sha256": environment_sha256,
            "source_sha": "d" * 40,
            "pythonpath": expected_guarded_pythonpath(PROJECT_ROOT),
            "script_sha256": script_sha256,
            "working_directory": record["working_directory"],
            "interpreter": interpreter,
        }
        self.assertFalse(validator(record, **validation))

        bad_canary = dict(record)
        bad_canary["startup_observed_at_ns"] = 0
        self.assertFalse(validator(bad_canary, **validation))
        bad_interpreter = dict(record)
        bad_interpreter["interpreter"] = {**interpreter, "prefix": "/wrong"}
        self.assertFalse(validator(bad_interpreter, **validation))
        bad_writes = dict(record)
        bad_writes["discarded_json_writes"] = record["discarded_json_writes"][:2]
        self.assertFalse(validator(bad_writes, **validation))

    def test_summary_child_validator_rejects_blocked_unpersisted_evidence(self) -> None:
        run_id = "summary-child-reconcile-" + uuid.uuid4().hex[:12]
        worker_pid = 12300
        prelaunch_pid = 12344
        child_pid = 12345
        command_sha256 = "a" * 64
        environment_sha256 = "b" * 64
        source_sha = "d" * 40
        working_directory = str(PROJECT_ROOT / "tmp" / "combat_capture")
        pythonpath = expected_guarded_pythonpath(PROJECT_ROOT)
        script_sha256 = hashlib.sha256(
            (PROJECT_ROOT / "core" / "ai" / "adv_summary.py").read_bytes()
        ).hexdigest()
        interpreter = {
            "executable": _repository_python(),
            "prefix": str(PROJECT_ROOT / ".venv"),
            "base_prefix": sys.base_prefix,
        }

        def event(
            pid: int,
            sequence: int,
            event_type: str,
            *,
            command_hash: str | None = None,
            child: int | None = None,
            child_is_python: bool | None = None,
            decision: str | None = None,
        ) -> dict[str, Any]:
            value: dict[str, Any] = {
                "schema_version": 1,
                "sequence": sequence,
                "event_type": event_type,
                "pid": pid,
                "process_group_id": worker_pid,
                "process_role": "host",
                "run_id": run_id,
                "observed_at_ns": 10_000 + pid + sequence,
                "operation": None,
                "decision": None,
                "target_host": None,
                "target_port": None,
                "target_host_sha256": None,
                "command_sha256": None,
                "child_pid": None,
                "child_is_python": None,
                "guard_active": None,
                "interpreter": None,
                "working_directory": None,
            }
            if event_type == "guard_startup":
                value.update(
                    {
                        "command_sha256": command_sha256,
                        "guard_active": True,
                        "interpreter": interpreter,
                        "working_directory": working_directory,
                    }
                )
            elif event_type == "network_attempt":
                value.update(
                    {
                        "operation": "connect",
                        "decision": "denied",
                        "target_host": "192.0.2.1",
                        "target_port": 8360,
                    }
                )
            elif event_type == "subprocess_attempt":
                value.update(
                    {
                        "operation": "Popen",
                        "decision": decision or "denied",
                        "command_sha256": command_hash or "f" * 64,
                    }
                )
            elif event_type == "subprocess_started":
                value.update(
                    {
                        "operation": "Popen",
                        "decision": "started",
                        "command_sha256": command_hash,
                        "child_pid": child,
                        "child_is_python": child_is_python,
                    }
                )
            return value

        guard_events: list[dict[str, Any]] = []
        worker_events = [
            event(worker_pid, 1, "guard_startup"),
            event(worker_pid, 2, "network_attempt"),
            event(worker_pid, 3, "subprocess_attempt"),
        ]
        for child_index, child in enumerate((prelaunch_pid, child_pid)):
            sequence = 4 + child_index * 2
            worker_events.extend(
                (
                    event(
                        worker_pid,
                        sequence,
                        "subprocess_attempt",
                        command_hash=command_sha256,
                        decision="allowed",
                    ),
                    event(
                        worker_pid,
                        sequence + 1,
                        "subprocess_started",
                        command_hash=command_sha256,
                        child=child,
                        child_is_python=True,
                    ),
                )
            )
        guard_events.extend(worker_events)
        guard_events.extend(
            event(pid, sequence, event_type)
            for pid in (prelaunch_pid, child_pid)
            for sequence, event_type in enumerate(
                ("guard_startup", "network_attempt", "subprocess_attempt"), start=1
            )
        )

        record = {
            "schema_version": 1,
            "run_id": run_id,
            "pid": child_pid,
            "process_group_id": worker_pid,
            "process_role": "host",
            "command_sha256": command_sha256,
            "environment_sha256": environment_sha256,
            "startup_observed_at_ns": 40_000,
            "interpreter": interpreter,
            "source_sha": source_sha,
            "pythonpath": pythonpath,
            "script_sha256": script_sha256,
            "working_directory": working_directory,
            "router_call_count": 1,
            "task": "adventure_summary",
            "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
            "source_line": 42,
            "source_file_sha256": script_sha256,
            "stub_failure_code": "router_task_has_no_stub_response",
            "expected_summary_call_blocked": True,
            "provider_request_attempted": False,
            "summary_output_persisted": False,
            "discarded_json_writes": [
                {
                    "source_file": "tmp/combat_capture/core/ai/adv_summary.py",
                    "basename": name,
                }
                for name in (
                    "summary_dump.json",
                    "trimmed_summary_dump.json",
                    "dialogue_summary.json",
                )
            ],
        }
        launch = {
            "sequence": 1,
            "command_sha256": command_sha256,
            "script_sha256": script_sha256,
            "working_directory": working_directory,
            "parent_pid": worker_pid,
            "parent_process_group_id": worker_pid,
            "prelaunch_canary_pid": prelaunch_pid,
            "prelaunch_startup_observed_at_ns": 30_000,
            "child_pid": child_pid,
            "child_process_group_id": worker_pid,
            "environment_sha256": environment_sha256,
            "interpreter": interpreter,
            "returncode": 1,
            "call_evidence_count": 1,
            "expected_blocked_summary_call": True,
        }
        call = {
            "sequence": 1,
            "task": "adventure_summary",
            "source_file": record["source_file"],
            "source_line": record["source_line"],
            "source_file_sha256": script_sha256,
            "source_sha": source_sha,
            "command_sha256": command_sha256,
            "environment_sha256": environment_sha256,
            "process_id": child_pid,
            "process_role": "adv_summary_child",
        }
        with tempfile.TemporaryDirectory(
            prefix="summary-child-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            evidence_directory = Path(temp_root)
            sidecar = evidence_directory / "adv-summary-child.jsonl"
            raw = (
                json.dumps(
                    record,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
                + b"\n"
            )
            sidecar.write_bytes(raw)
            evidence = {
                "schema_version": 1,
                "adapter_installed": True,
                "launch_count": 1,
                "launches": [launch],
                "calls": [call],
                "failure_code": None,
                "evidence_path": sidecar.relative_to(PROJECT_ROOT).as_posix(),
                "evidence_sha256": hashlib.sha256(raw).hexdigest(),
                "record_count": 1,
            }
            with self.assertRaises(ProfileValidationError):
                preflight_profiles._validate_adv_summary_child_evidence(
                    PROJECT_ROOT,
                    evidence,
                    run_id=run_id,
                    source_sha=source_sha,
                    pythonpath=pythonpath,
                    worker_pid=worker_pid,
                    worker_interpreter=interpreter,
                    guard_events=guard_events,
                    evidence_directory=evidence_directory,
                )

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
            "after_teardown_socket_sample_path": (
                "tmp/profile-lock-test/socket-sample-after_teardown.json"
            ),
            "after_teardown_socket_sample_sha256": "a" * 64,
            "evidence_path": "tmp/profile-lock-test/profile-evidence.json",
            "teardown_evidence_schema_version": 1,
            "teardown_evidence_path": "tmp/profile-lock-test/teardown-evidence.json",
        }
        release.update(overrides)
        return release

    @staticmethod
    def _listener_census(port: int, listener_pids: list[int] | None = None) -> dict:
        pids = [] if listener_pids is None else list(listener_pids)
        output = b"lsof listener fixture\n" if pids else b""
        identity = {
            "observer": "lsof",
            "census_method": "tcp-listen",
            "port": port,
            "command": [
                profile_runner.LSOF_EXECUTABLE,
                "-nP",
                "-iTCP:%d" % port,
                "-sTCP:LISTEN",
            ],
            "returncode": 0 if pids else 1,
            "stdout_byte_count": len(output),
            "stdout_sha256": hashlib.sha256(output).hexdigest(),
        }
        return {
            "schema_version": 1,
            "method": "lsof-tcp-listen",
            "port": port,
            **identity,
            "identity_sha256": profile_runner._canonical_json_sha256(identity),
            "observed": True,
            "parseable": True,
            "listener_pids": pids,
            "failure_code": None,
        }

    @staticmethod
    def _bind_observation(port: int, result: str = "free") -> dict:
        occupied = result == "occupied"
        return {
            "schema_version": 1,
            "method": "exclusive-bind-close",
            "transport": "tcp",
            "address": "127.0.0.1",
            "port": port,
            "reuse_address": False,
            "observed_at_ns": 1,
            "socket_created": True,
            "bind_attempted": True,
            "bind_succeeded": not occupied,
            "socket_closed": True,
            "result": result,
            "error_errno": errno.EADDRINUSE if occupied else None,
            "error_type": "OSError" if occupied else None,
            "observation_complete": True,
        }

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

    def test_e04_shape_accepts_guarded_controller_time_wait_through_teardown(
        self,
    ) -> None:
        run_id = "e04-synthetic-controller-time-wait"
        controller_pid = 24586
        host_prelaunch_pid = 24587
        host_pid = 24588
        working_directory = "tmp/e04-synthetic-fixture"
        command = [_repository_python(), "-m", "scripts.live_gate_preflight_profile_runner"]

        def process_scope(
            *,
            selector: str,
            pid: int,
            process_role: str,
            launch_source: str,
        ) -> dict[str, Any]:
            return profile_runner._make_process_scope(
                selector=selector,
                pid=pid,
                process_group_id=pid,
                process_role=process_role,
                launch_source=launch_source,
                command=command,
                environment_sha256="a" * 64,
                working_directory=working_directory,
            )

        process_scopes = [
            process_scope(
                selector="pid",
                pid=controller_pid,
                process_role="parent",
                launch_source="controller-startup-canary",
            ),
            process_scope(
                selector="process_group",
                pid=host_prelaunch_pid,
                process_role="host",
                launch_source="host-prelaunch-canary-session",
            ),
            process_scope(
                selector="process_group",
                pid=host_pid,
                process_role="host",
                launch_source="host-worker-start-new-session",
            ),
        ]
        guard_events = [
            _guard_startup_event(
                controller_pid,
                run_id,
                role="parent",
                working_directory=working_directory,
            ),
            _guard_child_started_event(
                controller_pid,
                host_prelaunch_pid,
                run_id,
                process_role="parent",
                process_group_id=controller_pid,
            ),
            _guard_child_started_event(
                controller_pid,
                host_pid,
                run_id,
                process_role="parent",
                process_group_id=controller_pid,
                sequence=3,
            ),
            _guard_startup_event(
                host_prelaunch_pid,
                run_id,
                role="host",
                working_directory=working_directory,
            ),
            _guard_startup_event(
                host_pid,
                run_id,
                role="host",
                working_directory=working_directory,
            ),
        ]
        controller_time_wait_row = {
            "protocol": "tcp4",
            "pid": controller_pid,
            "local": {"host": "127.0.0.1", "port": 51110},
            "foreign": {"host": "127.0.0.1", "port": profile_runner.HOST_PORT},
            "state": "TIME_WAIT",
        }
        host_listener_row = {
            "protocol": "tcp4",
            "pid": host_pid,
            "local": {"host": "0.0.0.0", "port": profile_runner.HOST_PORT},
            "foreign": {"host": "0.0.0.0", "port": 0},
            "state": "LISTEN",
        }

        def census_sample(phase: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "phase": phase,
                "port": profile_runner.HOST_PORT,
                "observed": True,
                "pids": sorted({row["pid"] for row in rows}),
                "listener_pids": profile_runner._host_ready_listener_pids(rows),
                "failure_code": None,
            }

        before_host = census_sample("before_host", [])
        host_ready = census_sample(
            "host_ready", [controller_time_wait_row, host_listener_row]
        )
        after_teardown = census_sample("after_teardown", [controller_time_wait_row])
        self.assertEqual(controller_time_wait_row["state"], "TIME_WAIT")
        self.assertEqual(host_ready["pids"], [controller_pid, host_pid])
        self.assertEqual(host_ready["listener_pids"], [host_pid])
        self.assertEqual(after_teardown["pids"], [controller_pid])
        self.assertEqual(after_teardown["listener_pids"], [])

        self.assertTrue(
            profile_runner._host_ready_listener_is_authorized(
                host_ready,
                host_pid=host_pid,
                guard_events=guard_events,
                expected_run_id=run_id,
            )
        )
        self.assertTrue(
            profile_runner._after_teardown_socket_sample_is_clean(
                after_teardown,
                controller_pid=controller_pid,
                guard_events=guard_events,
                expected_run_id=run_id,
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
            expected_run_id=run_id,
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
                expected_run_id=run_id,
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
                expected_run_id=run_id,
            )
        )
        self.assertFalse(
            profile_runner._host_ready_listener_is_authorized(
                host_ready,
                host_pid=host_pid,
                guard_events=guard_events,
                expected_run_id="different-run-id",
            )
        )
        self.assertFalse(
            profile_runner._after_teardown_socket_sample_is_clean(
                after_teardown,
                controller_pid=controller_pid,
                guard_events=guard_events,
                expected_run_id="different-run-id",
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
            probe.close.assert_called_once()
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
        probes[0].close.assert_called_once()

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

    def test_exclusive_bind_observation_retains_free_occupied_and_unknown_details(
        self,
    ) -> None:
        free_probe = mock.MagicMock()
        occupied_probe = mock.MagicMock()
        unknown_probe = mock.MagicMock()
        occupied_probe.bind.side_effect = OSError(errno.EADDRINUSE, "in use")
        unknown_probe.bind.side_effect = OSError(errno.EACCES, "denied")
        with mock.patch.object(
            profile_runner.socket,
            "socket",
            side_effect=[free_probe, occupied_probe, unknown_probe],
        ):
            free = profile_runner._exclusive_bind_port_observation(8360)
            occupied = profile_runner._exclusive_bind_port_observation(8360)
            unknown = profile_runner._exclusive_bind_port_observation(8370)

        self.assertEqual(free["result"], "free")
        self.assertTrue(free["bind_succeeded"])
        self.assertTrue(free["socket_closed"])
        self.assertTrue(free["observation_complete"])
        self.assertEqual(occupied["result"], "occupied")
        self.assertEqual(occupied["error_errno"], errno.EADDRINUSE)
        self.assertTrue(occupied["socket_closed"])
        self.assertTrue(occupied["observation_complete"])
        self.assertEqual(unknown["result"], "unobservable")
        self.assertEqual(unknown["error_errno"], errno.EACCES)
        self.assertFalse(unknown["observation_complete"])
        for observation in (free, occupied, unknown):
            self.assertEqual(observation["method"], "exclusive-bind-close")
            self.assertFalse(observation["reuse_address"])

        unexpected_probe = mock.MagicMock()
        unexpected_probe.bind.side_effect = RuntimeError("unexpected bind failure")
        with mock.patch.object(
            profile_runner.socket, "socket", return_value=unexpected_probe
        ):
            unexpected = profile_runner._exclusive_bind_port_observation(8360)
        self.assertEqual(unexpected["result"], "unobservable")
        self.assertEqual(unexpected["error_type"], "RuntimeError")
        self.assertTrue(unexpected["socket_closed"])

    def test_teardown_wait_retries_only_after_clean_census_and_proves_both_ports(
        self,
    ) -> None:
        class FakeClock:
            now_ns = 1_000_000_000
            sleeps: list[float] = []

            @classmethod
            def monotonic_ns(cls) -> int:
                return cls.now_ns

            @classmethod
            def sleep(cls, seconds: float) -> None:
                cls.sleeps.append(seconds)
                cls.now_ns += int(seconds * 1_000_000_000)

        bind_attempt = 0

        def bind_observations() -> dict[int, dict]:
            nonlocal bind_attempt
            bind_attempt += 1
            return {
                8360: self._bind_observation(
                    8360, "occupied" if bind_attempt == 1 else "free"
                ),
                8370: self._bind_observation(8370),
            }

        with (
            mock.patch.object(
                profile_runner,
                "_listener_census_observation",
                side_effect=lambda port, **_kwargs: self._listener_census(port),
            ) as census,
            mock.patch.object(
                profile_runner,
                "_required_port_observations",
                side_effect=bind_observations,
            ) as binds,
        ):
            evidence = profile_runner._wait_for_teardown_ports(
                lock_held=True,
                monotonic_ns=FakeClock.monotonic_ns,
                sleeper=FakeClock.sleep,
            )

        self.assertEqual(evidence["status"], "ports_free")
        self.assertIsNone(evidence["failure_code"])
        self.assertEqual(evidence["elapsed_monotonic_ns"], 1_000_000_000)
        self.assertEqual(len(evidence["attempts"]), 2)
        self.assertEqual(
            evidence["attempts"][1]["started_monotonic_ns"]
            - evidence["attempts"][0]["started_monotonic_ns"],
            1_000_000_000,
        )
        self.assertEqual(
            evidence["initial"]["port_observations"]["8360"]["result"],
            "occupied",
        )
        self.assertEqual(
            evidence["final"]["port_observations"],
            {
                "8360": self._bind_observation(8360),
                "8370": self._bind_observation(8370),
            },
        )
        for attempt in evidence["attempts"]:
            self.assertEqual(set(attempt["listener_census"]), {"8360", "8370"})
            self.assertEqual(set(attempt["port_observations"]), {"8360", "8370"})
            self.assertTrue(
                all(
                    item["listener_pids"] == []
                    for item in attempt["listener_census"].values()
                )
            )
        self.assertEqual(FakeClock.sleeps, [1.0])
        self.assertEqual(census.call_count, 4)
        self.assertEqual(binds.call_count, 2)

    def test_listener_census_distinguishes_empty_malformed_and_active_output(self) -> None:
        empty_output = b""
        empty_command = {
            "returncode": 1,
            "stdout_byte_count": 0,
            "stdout_sha256": hashlib.sha256(empty_output).hexdigest(),
        }
        with mock.patch.object(
            profile_runner,
            "_run_observer_command",
            return_value=(empty_command, empty_output, True),
        ):
            empty = profile_runner._listener_census_observation(8360)
        self.assertTrue(empty["observed"])
        self.assertEqual(empty["listener_pids"], [])

        malformed_command = {
            "returncode": 0,
            "stdout_byte_count": 0,
            "stdout_sha256": hashlib.sha256(empty_output).hexdigest(),
        }
        with mock.patch.object(
            profile_runner,
            "_run_observer_command",
            return_value=(malformed_command, empty_output, True),
        ):
            malformed = profile_runner._listener_census_observation(8360)
        self.assertFalse(malformed["observed"])
        self.assertEqual(malformed["failure_code"], "listener_census_malformed")

        listener_output = (
            b"COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            b"Python 123 user 3u IPv4 0x1 0t0 TCP "
            b"127.0.0.1:8360 (LISTEN)\n"
        )
        listener_command = {
            "returncode": 0,
            "stdout_byte_count": len(listener_output),
            "stdout_sha256": hashlib.sha256(listener_output).hexdigest(),
        }
        with mock.patch.object(
            profile_runner,
            "_run_observer_command",
            return_value=(listener_command, listener_output, True),
        ):
            active = profile_runner._listener_census_observation(8360)
        self.assertTrue(active["observed"])
        self.assertEqual(active["listener_pids"], [123])

    def test_teardown_wait_fails_closed_on_listener_malformed_census_and_bind_error(
        self,
    ) -> None:
        def run_wait(census_value: object, bind_value: dict | None = None) -> dict:
            now_ns = 10

            def monotonic_ns() -> int:
                return now_ns

            def observe(port: int, **_kwargs: object) -> object:
                return (
                    census_value(port)
                    if callable(census_value)
                    else census_value
                )

            with (
                mock.patch.object(
                    profile_runner,
                    "_listener_census_observation",
                    side_effect=observe,
                ),
                mock.patch.object(
                    profile_runner,
                    "_required_port_observations",
                    return_value=(
                        {
                            port: self._bind_observation(port)
                            for port in profile_runner.REQUIRED_PORTS
                        }
                        if bind_value is None
                        else bind_value
                    ),
                ) as binds,
            ):
                result = profile_runner._wait_for_teardown_ports(
                    lock_held=True,
                    monotonic_ns=monotonic_ns,
                    sleeper=lambda _seconds: None,
                )
            return result

        listener = run_wait(self._listener_census(8360, [123]))
        self.assertEqual(listener["failure_code"], "teardown_listener_present")
        self.assertEqual(len(listener["attempts"]), 1)

        malformed = run_wait({"schema_version": 1, "observed": True})
        self.assertEqual(
            malformed["failure_code"], "teardown_listener_census_malformed"
        )

        unavailable = run_wait(
            profile_runner._unobserved_listener_census(
                8360, "listener_census_unavailable"
            )
        )
        self.assertEqual(
            unavailable["failure_code"],
            "teardown_listener_census_unobservable",
        )

        early_sleep = run_wait(
            lambda port: self._listener_census(port),
            {
                8360: self._bind_observation(8360, "occupied"),
                8370: self._bind_observation(8370),
            },
        )
        self.assertEqual(
            early_sleep["failure_code"], "teardown_wait_sleep_returned_early"
        )

        unexpected = run_wait(
            lambda port: self._listener_census(port),
            {
                8360: self._bind_observation(8360, "unobservable"),
                8370: self._bind_observation(8370),
            },
        )
        self.assertEqual(
            unexpected["failure_code"], "teardown_port_bind_unexpected_error"
        )

    def test_teardown_wait_timeout_is_bounded_and_polls_at_most_once_per_second(
        self,
    ) -> None:
        now_ns = 50_000_000
        poll_starts: list[int] = []

        def monotonic_ns() -> int:
            return now_ns

        def sleeper(seconds: float) -> None:
            nonlocal now_ns
            self.assertLessEqual(seconds, 1.0)
            now_ns += int(seconds * 1_000_000_000)

        def occupied_bind_observations() -> dict[int, dict]:
            return {
                8360: self._bind_observation(8360, "occupied"),
                8370: self._bind_observation(8370),
            }

        original_census = self._listener_census

        def census(port: int, **_kwargs: object) -> dict:
            if port == 8360:
                poll_starts.append(now_ns)
            return original_census(port)

        with (
            mock.patch.object(
                profile_runner, "_listener_census_observation", side_effect=census
            ),
            mock.patch.object(
                profile_runner,
                "_required_port_observations",
                side_effect=occupied_bind_observations,
            ),
        ):
            evidence = profile_runner._wait_for_teardown_ports(
                lock_held=True, monotonic_ns=monotonic_ns, sleeper=sleeper
            )

        self.assertEqual(evidence["failure_code"], "teardown_port_wait_timeout")
        self.assertEqual(
            evidence["elapsed_monotonic_ns"],
            profile_runner.TEARDOWN_PORT_WAIT_TIMEOUT_NS,
        )
        self.assertEqual(len(evidence["attempts"]), 75)
        self.assertTrue(
            all(
                later - earlier >= 1_000_000_000
                for earlier, later in zip(poll_starts, poll_starts[1:])
            )
        )

    def test_teardown_wait_refuses_to_run_without_lock(self) -> None:
        with (
            mock.patch.object(profile_runner, "_listener_census_observation") as census,
            mock.patch.object(
                profile_runner, "_required_port_observations"
            ) as binds,
        ):
            evidence = profile_runner._wait_for_teardown_ports(
                lock_held=False,
                monotonic_ns=lambda: 10,
                sleeper=lambda _seconds: None,
            )
        self.assertEqual(evidence["failure_code"], "teardown_wait_lock_not_held")
        census.assert_not_called()
        binds.assert_not_called()

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
        summary_source_relative = "core/ai/adv_summary.py"
        self.assertIn(relative, profile_runner._SOURCE_BOUND_FILES)
        self.assertIn(summary_source_relative, profile_runner._SOURCE_BOUND_FILES)
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

            (project / relative).write_bytes(committed[relative])
            (project / summary_source_relative).write_bytes(b"changed summary source")
            shown_sources.clear()
            with mock.patch.object(profile_runner, "PROJECT_ROOT", project), mock.patch.object(
                profile_runner, "_git_output", return_value=source_sha
            ), mock.patch(
                "scripts.live_gate_preflight_safety.run_guarded_subprocess",
                side_effect=fake_git,
            ), self.assertRaisesRegex(
                CharacterizationError, "source_file_differs_from_declared_sha"
            ):
                profile_runner._verify_source_identity(source_sha)
            self.assertIn(
                source_sha + ":" + summary_source_relative,
                shown_sources,
            )

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
                self.returncode: int | None = None

            def poll(self) -> int | None:
                return self.return_code

        created_locks: list[object] = []
        checkpoint_copy_lock_states: list[bool] = []

        class FakeLock:
            def __init__(self, _common_directory: Path, record: dict) -> None:
                self.record = dict(record)
                self.held = False
                self.release_record: dict | None = None
                self.released = False
                self.release_attempted = False
                self.release_succeeded = False
                self.lock_directory_removed = False
                self.release_log_reference: dict | None = None
                created_locks.append(self)

            def acquire(self) -> bool:
                self.held = True
                return True

            def release(self, record: dict) -> bool:
                self.release_record = dict(record)
                self.released = True
                self.held = False
                self.release_attempted = True
                self.release_succeeded = True
                self.lock_directory_removed = True
                self.release_log_reference = {
                    "path": "tmp/fake-bookings.log",
                    "byte_offset": 0,
                    "byte_length": 2,
                    "line_sha256": "a" * 64,
                }
                return True

        with tempfile.TemporaryDirectory(
            prefix="profile-parent-flow-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            workspace = Path(temp_root)
            sandbox = workspace / "sandbox"
            sandbox.mkdir()
            (sandbox / "config.py").write_text("", encoding="utf-8")
            (sandbox / "party_tracker.json").write_text(
                json.dumps(
                    {
                        "worldConditions": {
                            "currentLocationId": "MP01",
                            "time": "Day 1, 08:00",
                        }
                    }
                ),
                encoding="utf-8",
            )
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
                *,
                socket_census_fails: bool = False,
                teardown_listener_present: bool = False,
                create_checkpoint: bool = False,
                checkpoint_copy_fails: bool = False,
                adv_summary_child: dict | None = None,
                retained_summary_child_artifacts: dict | None = None,
                checkpoint_travel_exchange_fails: bool = False,
                summary_child_retention_fails: bool = False,
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
                monotonic_now_ns = 1_000_000_000

                def monotonic_ns() -> int:
                    nonlocal monotonic_now_ns
                    monotonic_now_ns += 1
                    return monotonic_now_ns

                def sleep_seconds(seconds: float) -> None:
                    nonlocal monotonic_now_ns
                    monotonic_now_ns += int(seconds * 1_000_000_000)

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
                    "adv_summary_child": adv_summary_child,
                }

                def record_launch(*_args: object, **_kwargs: object) -> FakeProcess:
                    events.append("worker-launch")
                    return FakeProcess()

                def record_stop(process: FakeProcess) -> bool:
                    process.return_code = 0
                    process.returncode = 0
                    return True

                def record_worker_result(path: Path) -> dict:
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
                    worker_result = {
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
                    Path(path).write_text(
                        json.dumps(
                            worker_result,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        encoding="ascii",
                    )
                    return worker_result

                def record_ready(*_args: object, **_kwargs: object) -> bool:
                    events.append("listener-ready")
                    return True

                def record_exchange(**_kwargs: object) -> dict:
                    events.append("driver-exchange")
                    return exchange

                def record_socket_sample(phase: str, **_kwargs: object) -> dict:
                    if socket_census_fails and phase == "after_teardown":
                        raise RuntimeError("synthetic census failure")
                    sample = {
                        "phase": phase,
                        "port": 8360,
                        "observed": True,
                        "pids": [12345] if phase == "host_ready" else [],
                        "listener_pids": [12345] if phase == "host_ready" else [],
                        "failure_code": None,
                    }
                    sample_path = run_directory / ("socket-sample-%s.json" % phase)
                    raw_sample = json.dumps(
                        sample, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                    ).encode("ascii")
                    sample_path.write_bytes(raw_sample)
                    return {
                        **sample,
                        "evidence_path": sample_path.relative_to(PROJECT_ROOT).as_posix(),
                        "evidence_sha256": hashlib.sha256(raw_sample).hexdigest(),
                    }

                def record_listener_census(port: int, **_kwargs: object) -> dict:
                    if teardown_listener_present and port == profile_runner.HOST_PORT:
                        return self._listener_census(port, [54321])
                    return self._listener_census(port)

                def record_port_check(port: int) -> bool:
                    checked_ports.append(port)
                    return True

                def record_port_observations() -> dict[int, dict]:
                    observations = {}
                    for port in profile_runner.REQUIRED_PORTS:
                        checked_ports.append(port)
                        observations[port] = {
                            "schema_version": 1,
                            "method": "exclusive-bind-close",
                            "transport": "tcp",
                            "address": "127.0.0.1",
                            "port": port,
                            "reuse_address": False,
                            "observed_at_ns": 2_000_003,
                            "socket_created": True,
                            "bind_attempted": True,
                            "bind_succeeded": True,
                            "socket_closed": True,
                            "result": "free",
                            "error_errno": None,
                            "error_type": None,
                            "observation_complete": True,
                        }
                    return observations

                def retain_checkpoint(**_kwargs: object) -> tuple[dict, dict]:
                    checkpoint_copy_lock_states.append(created_locks[-1].held)
                    if checkpoint_copy_fails:
                        raise CharacterizationError("checkpoint_copy_failed")
                    return (
                        {
                            "checkpoint_root": "tmp/fake-resume-checkpoint",
                            "state_sha256": "c" * 64,
                        },
                        {"state_sha256": "c" * 64},
                    )

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
                                    "source_location_id": "MPV2_LOC_TAVERN",
                                    "source_runtime_location_id": "MP01",
                                    "target_source_location_id": "MPV2_LOC_VILLAGE_GREEN",
                                    "target_location_id": "MP02",
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
                            profile_runner,
                            "_validate_checkpoint_travel_exchange",
                            side_effect=(
                                CharacterizationError(
                                    "checkpoint_travel_call_path_mismatch"
                                )
                                if checkpoint_travel_exchange_fails
                                else None
                            ),
                            return_value={
                                "step_id": "E01-01",
                                "source_location_id": "MPV2_LOC_TAVERN",
                                "source_runtime_location_id": "MP01",
                                "target_source_location_id": "MPV2_LOC_VILLAGE_GREEN",
                                "target_location_id": "MP02",
                                "response_counts": {
                                    "travel_action_responses": 1,
                                    "gameplay_validation_responses": 1,
                                    "transition_validation_responses": 1,
                                    "transition_narration_responses": 1,
                                },
                                "complete": True,
                            },
                        ),
                        mock.patch(
                            "scripts.live_gate_preflight_retained.retain_summary_child_artifacts",
                            side_effect=(
                                _raise_summary_child_retention_error
                                if summary_child_retention_fails
                                else (
                                    (lambda *_args, **_kwargs: retained_summary_child_artifacts)
                                    if adv_summary_child is not None
                                    else None
                                )
                            ),
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_retain_moved_resume_checkpoint",
                            side_effect=retain_checkpoint,
                        ),
                        mock.patch(
                            "scripts.mapping_pilot.launcher._canonical_state_sha256",
                            return_value="b" * 64,
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
                            profile_runner,
                            "_required_port_observations",
                            side_effect=record_port_observations,
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_listener_census_observation",
                            side_effect=record_listener_census,
                        ),
                        mock.patch.object(
                            profile_runner.time,
                            "monotonic_ns",
                            side_effect=monotonic_ns,
                        ),
                        mock.patch.object(
                            profile_runner.time, "sleep", side_effect=sleep_seconds
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_worker_result_path_for_run",
                            side_effect=lambda _run_id, _preflight_run_id: (
                                run_directory / "worker-result.json"
                            ),
                        ),
                        mock.patch.object(
                            profile_runner,
                            "_worker_shutdown_request_path_for_run",
                            side_effect=lambda _run_id, _preflight_run_id: (
                                run_directory / "shutdown-request.json"
                            ),
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
                        create_resume_checkpoint=create_checkpoint,
                        planned_row_id="E01",
                        arm="A",
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
                [8360, 8370, 8360, 8370],
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
            with self.assertRaisesRegex(
                CharacterizationError,
                "process_census_after_teardown_failed_RuntimeError",
            ):
                run_characterization(
                    "census-failure",
                    driver_success,
                    socket_census_fails=True,
                )
            self.assertTrue(created_locks[-1].held)

            with self.assertRaisesRegex(
                CharacterizationError, "teardown_listener_present"
            ):
                run_characterization(
                    "teardown-listener-present",
                    driver_success,
                    teardown_listener_present=True,
                )
            self.assertTrue(created_locks[-1].held)
            failed_profile_path = (
                evidence_root
                / "teardown-listener-present"
                / "profile-evidence.json"
            )
            failed_profile = json.loads(
                failed_profile_path.read_text(encoding="utf-8")
            )
            failed_teardown_descriptor = failed_profile["teardown_evidence"]
            failed_teardown_path = (
                PROJECT_ROOT / failed_teardown_descriptor["path"]
            )
            self.assertEqual(
                failed_teardown_descriptor["sha256"],
                hashlib.sha256(failed_teardown_path.read_bytes()).hexdigest(),
            )
            failed_teardown = json.loads(
                failed_teardown_path.read_text(encoding="utf-8")
            )
            self.assertEqual(failed_teardown["schema_version"], 2)
            self.assertEqual(
                failed_profile["failure_code"], "teardown_listener_present"
            )
            self.assertEqual(failed_profile["outcome"], "failed")
            self.assertFalse(failed_profile["teardown"]["lock_released"])
            self.assertFalse(failed_teardown["shared_lock"]["release_attempted"])
            self.assertFalse(failed_teardown["shared_lock"]["release_succeeded"])
            self.assertFalse(failed_teardown["shared_lock"]["lock_directory_removed"])
            self.assertIsNone(failed_teardown["shared_lock"]["release_record"])
            self.assertIsNone(failed_teardown["shared_lock"]["durable_record"])
            failed_wait = failed_teardown["teardown_wait"]
            self.assertEqual(failed_wait["status"], "failed")
            self.assertEqual(
                failed_wait["failure_code"], "teardown_listener_present"
            )
            self.assertEqual(failed_wait["initial"], failed_wait["final"])
            self.assertEqual(len(failed_wait["attempts"]), 1)
            failed_attempt = failed_wait["final"]
            self.assertEqual(
                failed_attempt["port_observations"],
                {"8360": None, "8370": None},
            )
            self.assertEqual(
                failed_attempt["listener_census"]["8360"]["listener_pids"],
                [54321],
            )
            self.assertIsNone(
                failed_attempt["listener_census"]["8370"]
            )
            final_process_census = failed_wait["final_process_census"]
            self.assertEqual(final_process_census["phase"], "after_teardown")
            self.assertTrue(final_process_census["observed"])
            self.assertEqual(
                final_process_census["listener_pids"], []
            )
            self.assertEqual(
                failed_teardown["socket_census"]["path"],
                final_process_census["path"],
            )
            self.assertEqual(
                failed_teardown["socket_census"]["sha256"],
                final_process_census["sha256"],
            )
            self.assertEqual(
                failed_teardown["socket_census"]["listener_pids"], []
            )
            final_sample = failed_profile["process_census"]["socket_pid_samples"][-1]
            self.assertEqual(
                final_process_census["path"], final_sample["evidence_path"]
            )
            self.assertEqual(
                final_process_census["sha256"], final_sample["evidence_sha256"]
            )
            self.assertGreater(
                final_process_census["observed_monotonic_ns"],
                failed_wait["completed_monotonic_ns"],
            )

            checkpoint_evidence, _, _ = run_characterization(
                "checkpoint-copy-held",
                driver_success,
                create_checkpoint=True,
            )
            self.assertIs(checkpoint_copy_lock_states[-1], True)
            self.assertIs(created_locks[-1].held, False)
            self.assertIs(checkpoint_evidence["teardown"]["lock_released"], True)
            checkpoint_teardown_path = (
                PROJECT_ROOT / checkpoint_evidence["teardown_evidence"]["path"]
            )
            checkpoint_teardown = json.loads(
                checkpoint_teardown_path.read_text(encoding="utf-8")
            )
            self.assertIs(
                checkpoint_teardown["shared_lock"]["release_succeeded"], True
            )

            with self.assertRaisesRegex(
                CharacterizationError, "checkpoint_copy_failed"
            ):
                run_characterization(
                    "checkpoint-copy-failure",
                    driver_success,
                    create_checkpoint=True,
                    checkpoint_copy_fails=True,
                )
            self.assertIs(checkpoint_copy_lock_states[-1], True)
            self.assertIs(created_locks[-1].held, False)
            failed_checkpoint_teardown_path = (
                evidence_root
                / "checkpoint-copy-failure"
                / "teardown-evidence.json"
            )
            failed_checkpoint_teardown = json.loads(
                failed_checkpoint_teardown_path.read_text(encoding="utf-8")
            )
            self.assertIs(
                failed_checkpoint_teardown["shared_lock"]["release_succeeded"],
                True,
            )

            summary_child_fixture = {
                "launch_count": 1,
                "record_count": 1,
                "launches": [{"child_pid": 1}],
            }
            retained_fixture = {
                "schema_version": 1,
                "run_id": "summary-child-failure",
                "capture_phase": "after_child_before_cleanup",
                "artifacts": [{"role": "script_source"}],
            }
            with self.assertRaisesRegex(
                CharacterizationError, "checkpoint_travel_call_path_mismatch"
            ):
                run_characterization(
                    "summary-child-failure",
                    driver_success,
                    create_checkpoint=True,
                    checkpoint_travel_exchange_fails=True,
                    adv_summary_child=summary_child_fixture,
                    retained_summary_child_artifacts=retained_fixture,
                )
            summary_child_failure_evidence = json.loads(
                (
                    evidence_root / "summary-child-failure" / "profile-evidence.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(summary_child_failure_evidence["outcome"], "failed")
            self.assertEqual(
                summary_child_failure_evidence["failure_code"],
                "checkpoint_travel_call_path_mismatch",
            )
            self.assertEqual(
                summary_child_failure_evidence["summary_child_artifacts"],
                retained_fixture,
            )
            self.assertEqual(
                summary_child_failure_evidence["summary_child_retention"],
                {
                    "succeeded": True,
                    "failure_code": None,
                    "partial_artifact_count": len(retained_fixture["artifacts"]),
                },
            )

            # Retention itself failing must not be masked by the earlier
            # checkpoint-travel failure_code: the primary failure_code stays
            # the first failure, but the retention failure is still recorded
            # distinctly in its own evidence object.
            with self.assertRaisesRegex(
                CharacterizationError, "checkpoint_travel_call_path_mismatch"
            ):
                run_characterization(
                    "summary-child-retention-failure",
                    driver_success,
                    create_checkpoint=True,
                    checkpoint_travel_exchange_fails=True,
                    adv_summary_child=summary_child_fixture,
                    summary_child_retention_fails=True,
                )
            retention_failure_evidence = json.loads(
                (
                    evidence_root
                    / "summary-child-retention-failure"
                    / "profile-evidence.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(retention_failure_evidence["outcome"], "failed")
            self.assertEqual(
                retention_failure_evidence["failure_code"],
                "checkpoint_travel_call_path_mismatch",
            )
            self.assertNotIn(
                "summary_child_artifacts", retention_failure_evidence
            )
            self.assertEqual(
                retention_failure_evidence["summary_child_retention"],
                {
                    "succeeded": False,
                    "failure_code": (
                        "summary child final output differs from last write"
                    ),
                    "partial_artifact_count": 1,
                },
            )

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
        project_config = PROJECT_ROOT / "config.py"
        if not project_config.is_file():
            self.skipTest("missing required path: %s" % project_config)
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

            for lifecycle in ("startup", "resume"):
                for outcome in (
                    "caught",
                    "propagated",
                    "reject",
                    "natural",
                    "wrong_request",
                ):
                    with self.subTest(lifecycle=lifecycle, outcome=outcome):
                        run_id = (
                            "profile-worker-"
                            + sandbox.name.rsplit("-", 1)[-1]
                            + "-"
                            + lifecycle
                            + "-"
                            + outcome
                        )
                        run_directory = (
                            PROJECT_ROOT / profile_runner.PROFILE_EVIDENCE_ROOT / run_id
                        )
                        run_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
                        self.addCleanup(shutil.rmtree, run_directory, ignore_errors=True)
                        guard_events_path = run_directory / "guard-events.jsonl"
                        guard_events_path.write_bytes(b"")
                        environment = build_guarded_sandbox_environment(
                            relative_sandbox,
                            project_root=PROJECT_ROOT,
                            source_environment={"PATH": os.environ.get("PATH", "")},
                            process_role="host",
                            run_id=run_id,
                            guard_events_path=guard_events_path,
                        )
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
                        child_evidence = result["adv_summary_child"]
                        child_sidecar = PROJECT_ROOT / child_evidence["evidence_path"]
                        self.assertTrue(child_evidence["adapter_installed"])
                        self.assertIsNone(child_evidence["failure_code"])
                        self.assertEqual(child_evidence["launch_count"], 0)
                        self.assertEqual(child_evidence["calls"], [])
                        self.assertEqual(child_sidecar.read_bytes(), b"")
                        self.assertEqual(
                            child_evidence["evidence_sha256"],
                            hashlib.sha256(b"").hexdigest(),
                        )
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
                            st_dev=metadata.st_dev,
                            st_ino=metadata.st_ino,
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
            self.assertEqual((end - start).total_seconds(), 1800)
            self.assertEqual(record["frozen_caps"]["window_hours"], 0.5)
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
            log_reference = lock.release_log_reference
            self.assertIsNotNone(log_reference)
            log_bytes = log_path.read_bytes()
            release_bytes = log_bytes[
                log_reference["byte_offset"] : log_reference["byte_offset"]
                + log_reference["byte_length"]
            ]
            self.assertEqual(
                hashlib.sha256(release_bytes).hexdigest(),
                log_reference["line_sha256"],
            )
            self.assertEqual(log_reference["path"], log_path.relative_to(PROJECT_ROOT).as_posix())

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
            start + timedelta(seconds=1801)
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
            self._release_record(
                record, after_teardown_socket_pids=[12345, 12345]
            ),
            self._release_record(
                record, after_teardown_socket_pids=[{"pid": 12345}]
            ),
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

    def test_live_window_lock_release_schema_dispatch_is_strict(self) -> None:
        record = self._lock_record(run_id="release-schema-dispatch")
        legacy = self._release_record(record)
        version_two = self._release_record(
            record,
            teardown_evidence_schema_version=2,
            teardown_wait_schema_version=1,
            teardown_wait_sha256="a" * 64,
            teardown_wait_elapsed_monotonic_ns=75_000_000_000,
            teardown_wait_completed_monotonic_ns=100,
            after_teardown_socket_sample_observed_monotonic_ns=101,
        )

        self.assertTrue(
            profile_runner._valid_lock_release_record(legacy, record["booking_id"])
        )
        self.assertTrue(
            profile_runner._valid_lock_release_record(
                version_two, record["booking_id"]
            )
        )
        self.assertFalse(
            profile_runner._valid_lock_release_record(
                {**legacy, "teardown_wait_schema_version": 1},
                record["booking_id"],
            )
        )
        self.assertFalse(
            profile_runner._valid_lock_release_record(
                {**version_two, "teardown_wait_sha256": None},
                record["booking_id"],
            )
        )
        self.assertFalse(
            profile_runner._valid_lock_release_record(
                {**version_two, "teardown_evidence_schema_version": 3},
                record["booking_id"],
            )
        )

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

    def test_live_window_lock_does_not_release_through_replaced_coordination_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="profile-lock-coordination-replaced-", dir=PROJECT_ROOT / "tmp"
        ) as temp_directory:
            common_directory = Path(temp_directory)
            record = self._lock_record(run_id="coordination-replaced")
            lock = _ProfileCharacterizationLock(common_directory, record)
            self.assertTrue(lock.acquire())
            coordination = common_directory / "neq-coordination"
            original = common_directory / "neq-coordination-original"
            original_holder = coordination / "live-window.lock" / "holder.json"
            original_holder_bytes = original_holder.read_bytes()
            coordination.rename(original)
            coordination.mkdir(mode=0o700)

            self.assertFalse(lock.release(self._release_record(record)))
            self.assertEqual(
                (original / "live-window.lock" / "holder.json").read_bytes(),
                original_holder_bytes,
            )
            self.assertFalse((coordination / "live-window.lock").exists())

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


class TestCheckpointTravelPreparation(unittest.TestCase):
    def test_frozen_travel_turns_are_party_bound_and_combat_has_none(self) -> None:
        from scripts.seed_combat_capture import _party_names

        expected_steps = {
            "interior_tavern": "E4-07",
            "landscape_village": "E3-01",
            "transition_tower_approach": "E3-03",
        }
        for fixture_id, expected_step in expected_steps.items():
            for party_size in (1, 4):
                with self.subTest(fixture_id=fixture_id, party_size=party_size):
                    plan, _profile = sandbox_preparation._load_profile_seed_plan(
                        fixture_id, party_size, None
                    )
                    script_path = (
                        PROJECT_ROOT
                        / "plans"
                        / "v2-mapping-pilot-prereg"
                        / str(plan["counterbalance"]["script"])
                    )
                    script = json.loads(script_path.read_text(encoding="utf-8"))
                    turn = profile_runner._resolve_checkpoint_travel_turn(
                        script=script,
                        fixture_id=fixture_id,
                        party_size=party_size,
                        members=_party_names(party_size),
                        source_location_id=plan["source_location_id"],
                    )
                    self.assertIsNotNone(turn)
                    self.assertEqual(turn["step_id"], expected_step)
                    self.assertEqual(
                        turn["source_runtime_location_id"],
                        LOCATION_ID_MAP[plan["source_location_id"]],
                    )
                    self.assertNotEqual(
                        turn["source_location_id"],
                        turn["source_runtime_location_id"],
                    )

        combat_plan, _profile = sandbox_preparation._load_profile_seed_plan(
            "combat_stage_tavern_zones", 1, None
        )
        combat_script_path = (
            PROJECT_ROOT
            / "plans"
            / "v2-mapping-pilot-prereg"
            / str(combat_plan["counterbalance"]["script"])
        )
        combat_script = json.loads(
            combat_script_path.read_text(encoding="utf-8")
        )
        self.assertIsNone(
            profile_runner._resolve_checkpoint_travel_turn(
                script=combat_script,
                fixture_id="combat_stage_tavern_zones",
                party_size=1,
                members=_party_names(1),
                source_location_id=combat_plan["source_location_id"],
            )
        )

    def test_checkpoint_seed_location_uses_canonical_runtime_mapping(self) -> None:
        from scripts.seed_combat_capture import _party_names

        plan, _profile = sandbox_preparation._load_profile_seed_plan(
            "interior_tavern", 1, "E01"
        )
        script_path = (
            PROJECT_ROOT
            / "plans"
            / "v2-mapping-pilot-prereg"
            / str(plan["counterbalance"]["script"])
        )
        script = json.loads(script_path.read_text(encoding="utf-8"))
        turn = profile_runner._resolve_checkpoint_travel_turn(
            script=script,
            fixture_id="interior_tavern",
            party_size=1,
            members=_party_names(1),
            source_location_id=plan["source_location_id"],
        )
        self.assertIsInstance(turn, dict)
        source_runtime_id = LOCATION_ID_MAP[plan["source_location_id"]]
        self.assertNotEqual(plan["source_location_id"], source_runtime_id)
        self.assertEqual(
            profile_runner._validate_checkpoint_seed_location(
                source_runtime_id, turn
            ),
            source_runtime_id,
        )

        for current_location_id in (
            plan["source_location_id"],
            "MP999",
        ):
            with self.subTest(current_location_id=current_location_id):
                with self.assertRaisesRegex(
                    CharacterizationError, "checkpoint_seed_location_mismatch"
                ):
                    profile_runner._validate_checkpoint_seed_location(
                        current_location_id, turn
                    )

        mismapped_turn = {
            **turn,
            "source_runtime_location_id": "MP999",
        }
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_seed_location_mismatch"
        ):
            profile_runner._validate_checkpoint_seed_location(
                source_runtime_id, mismapped_turn
            )

    def test_public_supervised_row_path_explicitly_requests_one_checkpoint(self) -> None:
        characterized: list[argparse.Namespace] = []

        def characterize(args: argparse.Namespace) -> tuple[dict, str, str]:
            characterized.append(args)
            return {"outcome": "completed"}, "tmp/evidence.json", "a" * 64

        with mock.patch.object(
            profile_runner, "_characterize", side_effect=characterize
        ):
            result = profile_runner.supervise_preflight_row(
                fixture_id="interior_tavern",
                party_size=1,
                planned_row_id="E01",
                arm="A",
                source_sha="b" * 40,
                row_run_id="checkpoint-primary-run",
                preflight_run_id="checkpoint-primary",
                create_resume_checkpoint=True,
            )
        self.assertEqual(result["evidence"]["outcome"], "completed")
        self.assertEqual(len(characterized), 1)
        self.assertIs(characterized[0].create_resume_checkpoint, True)

        with mock.patch.object(profile_runner, "_characterize") as characterize_mock:
            with self.assertRaisesRegex(
                CharacterizationError, "row_preflight_identity_invalid"
            ):
                profile_runner.supervise_preflight_row(
                    fixture_id="combat_stage_tavern_zones",
                    party_size=1,
                    planned_row_id="C01",
                    arm="A",
                    source_sha="b" * 40,
                    row_run_id="checkpoint-combat-run",
                    preflight_run_id="checkpoint-primary",
                    create_resume_checkpoint=True,
                )
        characterize_mock.assert_not_called()

    def _make_checkpoint_sandbox(self, parent: Path) -> dict[str, Any]:
        from scripts.mapping_pilot import launcher

        project_root = parent / "isolated-project"
        (project_root / "tmp").mkdir(parents=True)
        sandbox_root = project_root / profile_runner.SANDBOX_RELATIVE
        sandbox_root.mkdir()
        plan, _profile = sandbox_preparation._load_profile_seed_plan(
            "interior_tavern", 1, "E01"
        )
        module_payloads, expected_payloads = (
            sandbox_preparation._load_profile_seed_inputs(PROJECT_ROOT)
        )
        written = sandbox_preparation._write_fixture_module(
            sandbox_root, plan, module_payloads, expected_payloads
        )
        metadata = sandbox_preparation._write_seed_state(
            PROJECT_ROOT,
            sandbox_root,
            plan,
            written["module_payloads"],
            written["mapping"],
        )
        (sandbox_root / "config.py").write_text(
            sandbox_preparation._SYNTHETIC_CONFIG, encoding="ascii"
        )
        script_path = (
            PROJECT_ROOT
            / "plans"
            / "v2-mapping-pilot-prereg"
            / str(plan["counterbalance"]["script"])
        )
        script = json.loads(script_path.read_text(encoding="utf-8"))
        travel_turn = profile_runner._resolve_checkpoint_travel_turn(
            script=script,
            fixture_id="interior_tavern",
            party_size=1,
            members=metadata["party"]["members"],
            source_location_id=plan["source_location_id"],
        )
        self.assertIsInstance(travel_turn, dict)
        tracker = json.loads(
            (sandbox_root / "party_tracker.json").read_text(encoding="utf-8")
        )
        initial_time = tracker["worldConditions"]["time"]
        return {
            "project_root": project_root,
            "sandbox_root": sandbox_root,
            "plan": plan,
            "metadata": metadata,
            "module_payloads": written["module_payloads"],
            "travel_turn": travel_turn,
            "tracker": tracker,
            "initial_time": initial_time,
            "initial_state_sha256": launcher._canonical_state_sha256(sandbox_root),
            "launcher": launcher,
        }

    @staticmethod
    def _travel_proof(turn: dict[str, Any]) -> dict[str, Any]:
        return {
            "step_id": turn["step_id"],
            "source_location_id": turn["source_location_id"],
            "source_runtime_location_id": turn["source_runtime_location_id"],
            "target_source_location_id": turn["target_source_location_id"],
            "target_location_id": turn["target_location_id"],
            "response_counts": {
                "travel_action_responses": 1,
                "gameplay_validation_responses": 1,
                "transition_validation_responses": 1,
                "transition_narration_responses": 1,
            },
            "response_call_sequences": {
                "travel_action": 2,
                "transition_validation": 3,
                "gameplay_validation": 4,
                "transition_narration": 5,
            },
            "complete": True,
        }

    def _move_synthetic_fixture(self, state: dict[str, Any]) -> None:
        turn = state["travel_turn"]
        area_id, area_payload, target = sandbox_preparation._runtime_location(
            state["module_payloads"], turn["target_location_id"]
        )
        world = state["tracker"]["worldConditions"]
        world["currentLocationId"] = turn["target_location_id"]
        world["currentLocation"] = target["name"]
        world["currentAreaId"] = area_id
        world["currentArea"] = area_payload["areaName"]
        world["time"] = state["initial_time"] + " synthetic travel"
        profile_runner._write_json(
            state["sandbox_root"] / "party_tracker.json", state["tracker"]
        )

    def test_travel_resolver_binds_actual_startup_and_travel_call_sequences(self) -> None:
        turn = {
            "step_id": "E3-01",
            "utterance": "We follow the detour into the Old Watchtower Approach. What is around us in this second area?",
            "character": "Acheron",
            "source_location_id": "MPV2_LOC_VILLAGE_GREEN",
            "source_runtime_location_id": "MP02",
            "target_source_location_id": "MPV2_LOC_TOWER_APPROACH",
            "target_location_id": "MP03",
            "target_location_name": "Old Watchtower Approach",
            "time_minutes": 10,
        }
        resolver = profile_runner._checkpoint_travel_response_resolver(turn)
        response = profile_runner._checkpoint_travel_response(turn)
        call_pairs = (
            ("travel_narration", "core/generators/module_stitcher.py"),
            ("safety_review", "core/generators/module_stitcher.py"),
            ("travel_narration", "core/generators/module_stitcher.py"),
            ("safety_review", "core/generators/module_stitcher.py"),
            ("action_prediction", "utils/action_predictor.py"),
            ("dm_main", "main.py"),
            ("dm_validation", "core/ai/action_handler.py"),
            ("action_prediction", "utils/action_predictor.py"),
            ("dm_main", "main.py"),
            ("dm_main", "core/ai/transition_validator.py"),
            ("dm_validation", "main.py"),
            ("dm_main", "core/ai/action_handler.py"),
            ("adventure_summary", "core/ai/cumulative_summary.py"),
            ("adventure_summary", "core/ai/cumulative_summary.py"),
            ("adventure_summary", "core/ai/cumulative_summary.py"),
        )
        call_kwargs = {
            6: {
                "messages": [
                    {
                        "role": "user",
                        "content": "The party pauses and takes in the scene.",
                    }
                ]
            },
            9: {
                "messages": [
                    {"role": "user", "content": turn["utterance"]}
                ]
            },
            10: {
                "messages": [
                    {
                        "role": "user",
                        "content": turn["utterance"]
                        + " "
                        + turn["target_location_id"],
                    }
                ]
            },
            11: {"messages": [{"role": "assistant", "content": response}]},
        }
        resolved = [
            resolver(task, source_file, (), call_kwargs.get(sequence, {}))
            for sequence, (task, source_file) in enumerate(call_pairs, start=1)
        ]
        self.assertIsNone(resolved[5])
        self.assertIsNone(resolved[6])
        self.assertEqual(resolved[8], response)
        self.assertIsNotNone(resolved[9])
        self.assertIsNotNone(resolved[10])
        self.assertIsNotNone(resolved[11])
        self.assertEqual(
            resolver.proof()["response_call_sequences"],
            {
                "travel_action": 9,
                "transition_validation": 10,
                "gameplay_validation": 11,
                "transition_narration": 12,
            },
        )
        calls = [
            {"sequence": sequence, "task": task, "source_file": source_file}
            for sequence, (task, source_file) in enumerate(call_pairs, start=1)
        ]
        result = {
            "outcome": "completed",
            "failure_code": None,
            "stub_failure_code": None,
            "call_count": len(calls),
            "calls": calls,
            "checkpoint_travel": resolver.proof(),
        }
        driver_exchange = {
            "status": "completed",
            "step_id": turn["step_id"],
            "active_character_set": True,
            "turn_completed": True,
            "turn_timed_out": False,
            "game_output_count": 1,
        }
        proof = profile_runner._validate_checkpoint_travel_exchange(
            result, travel_turn=turn, driver_exchange=driver_exchange
        )
        expected_proof = self._travel_proof(turn)
        expected_proof["response_call_sequences"] = {
            "travel_action": 9,
            "transition_validation": 10,
            "gameplay_validation": 11,
            "transition_narration": 12,
        }
        self.assertEqual(proof, expected_proof)

        out_of_order = {
            **result,
            "calls": [dict(call) for call in result["calls"]],
        }
        out_of_order["calls"][9]["task"], out_of_order["calls"][9]["source_file"] = (
            out_of_order["calls"][10]["task"],
            out_of_order["calls"][10]["source_file"],
        )
        out_of_order["calls"][10]["task"], out_of_order["calls"][10]["source_file"] = (
            result["calls"][9]["task"],
            result["calls"][9]["source_file"],
        )
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_travel_call_order_mismatch"
        ):
            profile_runner._validate_checkpoint_travel_exchange(
                out_of_order, travel_turn=turn, driver_exchange=driver_exchange
            )

        duplicate = {
            **result,
            "calls": [
                *[dict(call) for call in result["calls"]],
                {"sequence": 16, "task": "dm_main", "source_file": "main.py"},
            ],
            "call_count": 16,
        }
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_travel_call_path_mismatch"
        ):
            profile_runner._validate_checkpoint_travel_exchange(
                duplicate, travel_turn=turn, driver_exchange=driver_exchange
            )

        missing = {
            **result,
            "calls": [
                {**call, "sequence": sequence}
                for sequence, call in enumerate(
                    (call for call in result["calls"] if call["sequence"] != 9),
                    start=1,
                )
            ],
            "call_count": len(result["calls"]) - 1,
        }
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_travel_call_path_mismatch"
        ):
            profile_runner._validate_checkpoint_travel_exchange(
                missing, travel_turn=turn, driver_exchange=driver_exchange
            )

        forged = {
            **result,
            "checkpoint_travel": {
                **result["checkpoint_travel"],
                "response_call_sequences": {
                    **result["checkpoint_travel"]["response_call_sequences"],
                    "travel_action": 6,
                },
            },
        }
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_travel_call_path_mismatch"
        ):
            profile_runner._validate_checkpoint_travel_exchange(
                forged, travel_turn=turn, driver_exchange=driver_exchange
            )

        old_wrong_shape_calls = [dict(call) for call in result["calls"]]
        old_wrong_shape_calls[6]["task"] = "dm_validation"
        old_wrong_shape_calls[6]["source_file"] = "main.py"
        old_wrong_shape = {
            **result,
            "calls": old_wrong_shape_calls,
        }
        with self.assertRaisesRegex(
            CharacterizationError, "checkpoint_travel_call_path_mismatch"
        ):
            profile_runner._validate_checkpoint_travel_exchange(
                old_wrong_shape, travel_turn=turn, driver_exchange=driver_exchange
            )

    def test_checkpoint_travel_resolver_rejects_out_of_order_and_duplicate_calls(
        self,
    ) -> None:
        turn = {
            "step_id": "E4-07",
            "utterance": "We leave through the open front entrance into the village green.",
            "character": "Acheron",
            "source_location_id": "MPV2_LOC_TAVERN",
            "source_runtime_location_id": "MP01",
            "target_source_location_id": "MPV2_LOC_VILLAGE_GREEN",
            "target_location_id": "MP02",
            "target_location_name": "Village Green",
            "time_minutes": 5,
        }
        transition_messages = {
            "messages": [
                {
                    "role": "user",
                    "content": turn["utterance"] + " " + turn["target_location_id"],
                }
            ]
        }
        validation_messages = {
            "messages": [
                {
                    "role": "assistant",
                    "content": profile_runner._checkpoint_travel_response(turn),
                }
            ]
        }
        travel_messages = {"messages": [{"role": "user", "content": turn["utterance"]}]}

        resolver = profile_runner._checkpoint_travel_response_resolver(turn)
        with self.assertRaisesRegex(
            RouterStubError, "transition validation call is out of sequence"
        ):
            resolver(
                "dm_main",
                "core/ai/transition_validator.py",
                (),
                transition_messages,
            )
        self.assertFalse(resolver.proof()["complete"])

        resolver = profile_runner._checkpoint_travel_response_resolver(turn)
        self.assertIsNotNone(
            resolver("dm_main", "main.py", (), travel_messages)
        )
        with self.assertRaisesRegex(
            RouterStubError, "gameplay validation call is out of sequence"
        ):
            resolver("dm_validation", "main.py", (), validation_messages)
        self.assertEqual(
            resolver.proof()["response_counts"],
            {
                "travel_action_responses": 1,
                "gameplay_validation_responses": 0,
                "transition_validation_responses": 0,
                "transition_narration_responses": 0,
            },
        )

        resolver = profile_runner._checkpoint_travel_response_resolver(turn)
        self.assertIsNotNone(
            resolver("dm_main", "main.py", (), travel_messages)
        )
        self.assertIsNotNone(
            resolver(
                "dm_main",
                "core/ai/transition_validator.py",
                (),
                transition_messages,
            )
        )
        with self.assertRaisesRegex(
            RouterStubError, "transition validation call is out of sequence"
        ):
            resolver(
                "dm_main",
                "core/ai/transition_validator.py",
                (),
                transition_messages,
            )
        self.assertEqual(resolver.proof()["response_counts"]["transition_validation_responses"], 1)
        self.assertFalse(resolver.proof()["complete"])

        resolver = profile_runner._checkpoint_travel_response_resolver(turn)
        self.assertIsNotNone(
            resolver("dm_main", "main.py", (), travel_messages)
        )
        with self.assertRaisesRegex(
            RouterStubError, "scripted travel response was already consumed"
        ):
            resolver("dm_main", "main.py", (), travel_messages)
        self.assertEqual(
            resolver.proof()["response_counts"]["travel_action_responses"], 1
        )
        self.assertFalse(resolver.proof()["complete"])

    def test_retained_checkpoint_attests_normalized_moved_state_and_detects_tampering(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="checkpoint-travel-valid-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            state = self._make_checkpoint_sandbox(Path(temp_root))
            self._move_synthetic_fixture(state)
            with mock.patch.object(
                profile_runner, "PROJECT_ROOT", state["project_root"]
            ):
                descriptor, attestation_ref = (
                    profile_runner._retain_moved_resume_checkpoint(
                        sandbox=state["sandbox_root"],
                        fixture_id="interior_tavern",
                        party_size=1,
                        planned_row_id="E01",
                        arm="A",
                        source_sha="a" * 40,
                        run_id="checkpoint-travel-valid",
                        travel_turn=state["travel_turn"],
                        travel_proof=self._travel_proof(state["travel_turn"]),
                        initial_state_sha256=state["initial_state_sha256"],
                        initial_time=state["initial_time"],
                        project_root=state["project_root"],
                    )
                )
            checkpoint_root = state["project_root"] / descriptor["checkpoint_root"]
            self.assertNotEqual(checkpoint_root.resolve(), state["sandbox_root"].resolve())
            self.assertEqual(
                state["launcher"]._canonical_state_sha256(checkpoint_root),
                descriptor["state_sha256"],
            )
            attestation_path = state["project_root"] / attestation_ref["path"]
            self.assertEqual(
                hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
                attestation_ref["sha256"],
            )
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
            self.assertEqual(attestation["row_id"], "E01")
            self.assertEqual(attestation["fixture_id"], "interior_tavern")
            self.assertEqual(
                attestation["travel_proof"],
                self._travel_proof(state["travel_turn"]),
            )
            self.assertEqual(attestation["party_size"], 1)
            self.assertEqual(attestation["arm"], "A")
            self.assertEqual(attestation["fixed_seed"], 5101)
            self.assertEqual(
                attestation["source_runtime_location_id"],
                LOCATION_ID_MAP[state["travel_turn"]["source_location_id"]],
            )
            self.assertNotEqual(
                attestation["source_location_id"],
                attestation["initial_location_id"],
            )
            self.assertEqual(
                attestation["initial_location_id"],
                state["travel_turn"]["source_runtime_location_id"],
            )
            self.assertEqual(
                attestation["final_location_id"],
                state["travel_turn"]["target_location_id"],
            )
            self.assertTrue(
                attestation["persistence"]["canonical_state_hash_verified"]
            )

            tracker_path = checkpoint_root / "party_tracker.json"
            tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
            tracker["synthetic_tamper_marker"] = True
            profile_runner._write_json(tracker_path, tracker)
            with self.assertRaisesRegex(
                sandbox_preparation.SandboxPreparationError,
                "resume checkpoint state hash differs",
            ):
                sandbox_preparation._install_row_resume_checkpoint(
                    state["project_root"],
                    state["sandbox_root"],
                    state["plan"],
                    descriptor,
                    expected_sha256=descriptor["state_sha256"],
                )

    def test_checkpoint_retention_fails_closed_for_unchanged_or_wrong_location(
        self,
    ) -> None:
        for mode in (
            "unchanged",
            "wrong-location",
            "wrong-source-runtime-mapping",
            "wrong-source-identity",
            "unchanged-hash",
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="checkpoint-travel-invalid-", dir=PROJECT_ROOT / "tmp"
            ) as temp_root:
                state = self._make_checkpoint_sandbox(Path(temp_root))
                if mode != "unchanged":
                    self._move_synthetic_fixture(state)
                if mode == "wrong-location":
                    state["tracker"]["worldConditions"]["currentLocationId"] = (
                        "MP999"
                    )
                    profile_runner._write_json(
                        state["sandbox_root"] / "party_tracker.json",
                        state["tracker"],
                    )
                elif mode == "wrong-source-runtime-mapping":
                    state["travel_turn"]["source_runtime_location_id"] = "MP999"
                elif mode == "wrong-source-identity":
                    state["metadata"]["mapping"]["source_location_id"] = (
                        "MPV2_LOC_VILLAGE_GREEN"
                    )
                    profile_runner._write_json(
                        state["sandbox_root"] / "mapping_pilot" / "seed_metadata.json",
                        state["metadata"],
                    )
                with mock.patch.object(
                    profile_runner, "PROJECT_ROOT", state["project_root"]
                ):
                    if mode == "unchanged-hash":
                        from scripts.mapping_pilot import launcher

                        patcher = mock.patch.object(
                            launcher,
                            "_canonical_state_sha256",
                            return_value=state["initial_state_sha256"],
                        )
                    else:
                        patcher = nullcontext()
                    with patcher:
                        with self.assertRaises(CharacterizationError) as raised:
                            profile_runner._retain_moved_resume_checkpoint(
                                sandbox=state["sandbox_root"],
                                fixture_id="interior_tavern",
                                party_size=1,
                                planned_row_id="E01",
                                arm="A",
                                source_sha="a" * 40,
                                run_id="checkpoint-travel-invalid-" + mode,
                                travel_turn=state["travel_turn"],
                                travel_proof=self._travel_proof(
                                    state["travel_turn"]
                                ),
                                initial_state_sha256=state[
                                    "initial_state_sha256"
                                ],
                                initial_time=state["initial_time"],
                                project_root=state["project_root"],
                            )
                expected_code = (
                    "checkpoint_state_hash_unchanged"
                    if mode == "unchanged-hash"
                    else (
                        "checkpoint_creation_identity_invalid"
                        if mode == "wrong-source-runtime-mapping"
                        else (
                            "checkpoint_seed_identity_mismatch"
                            if mode == "wrong-source-identity"
                            else "checkpoint_travel_state_not_persisted"
                        )
                    )
                )
                self.assertEqual(raised.exception.code, expected_code)

    def test_checkpoint_creation_rejects_missing_guard_and_reserve_rows(self) -> None:
        from scripts.live_gate_preflight_controller import _load_frozen_row_ids

        args = argparse.Namespace(
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            source_sha="a" * 40,
            run_id="checkpoint-guard-test",
            resume_checkpoint_sha256=None,
            planned_row_id="E01",
            arm="A",
            lifecycle_id="checkpoint-guard-test_s",
            preflight_run_id=None,
            create_resume_checkpoint=True,
        )
        unguarded_environment = {
            "NEQ_PREFLIGHT_STARTUP_GUARD_REQUIRED": "",
            "NEQ_PREFLIGHT_NETWORK_GUARD": "",
            "NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE": "",
            "NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE": "",
            "NEQ_PREFLIGHT_ENV_SANITIZED": "",
            "NEQ_PREFLIGHT_CONNECT_CANARY_DENIED": "",
            "NEQ_PREFLIGHT_SUBPROCESS_CANARY_DENIED": "",
        }
        with mock.patch.object(
            profile_runner, "_require_safe_project_root", return_value=PROJECT_ROOT
        ), mock.patch.dict(os.environ, unguarded_environment):
            with self.assertRaisesRegex(
                CharacterizationError, "parent_startup_guard_inactive"
            ):
                profile_runner._characterize(args)

        _planned, reserve_rows = _load_frozen_row_ids(None)
        with self.assertRaisesRegex(
            CharacterizationError, "row_preflight_identity_invalid"
        ):
            profile_runner.supervise_preflight_row(
                fixture_id="interior_tavern",
                party_size=1,
                planned_row_id=reserve_rows[0],
                arm="A",
                source_sha="a" * 40,
                row_run_id="checkpoint-reserve-row",
                preflight_run_id="checkpoint-reserve-preflight",
                create_resume_checkpoint=True,
            )


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
                    "identity_cli = json.loads(sys.argv[2])",
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
                    "sys.argv = [str(entrypoint), '--prepare', '--fixture-id', 'interior_tavern', '--party-size', '1', '--planned-row-id', 'E01', *identity_cli]",
                    "try:",
                    "    runpy.run_path(str(entrypoint), run_name='__main__')",
                    "except SystemExit as exc:",
                    "    if exc.code not in (None, 0, 1):",
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
                [
                    _repository_python(),
                    "-c",
                    audit_code,
                    str(project),
                    json.dumps(_sandbox_identity_cli_args(project)),
                ],
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
            preparation_line = next(
                line for line in completed.stdout.splitlines() if line.startswith("{")
            )
            preparation = json.loads(preparation_line)
            self.assertEqual(preparation["status"], "prepared")
            self.assertEqual(preparation["invocation_identity"]["status"], "matched")
            self.assertTrue((project / "tmp" / "combat_capture" / "config.py").is_file())

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
                    *_sandbox_identity_cli_args(project),
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
                    *_sandbox_identity_cli_args(project),
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
            "scripts/live_gate_preflight_profile_runner.py",
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
        venv_python = project / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("synthetic interpreter identity\n", encoding="ascii")
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
        run_id=(
            "profile-worker-"
            + sandbox.name.rsplit("-", 1)[-1]
            + "-"
            + lifecycle
            + "-"
            + outcome
        ),
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
        create_resume_checkpoint=False,
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


class TestContentBoundDeclarations(unittest.TestCase):
    """Declarations bind to call-site content and stub/driver hashes, not a SHA."""

    SITE_A = "scripts/live_gate_preflight_controller.py"
    SITE_B = "scripts/live_gate_preflight_stub.py"

    def setUp(self) -> None:
        self.tool_hashes = preflight_profiles.tool_file_hashes()
        self.site_hashes = {
            path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
            for path in (self.SITE_A, self.SITE_B)
        }

    def _sites(self) -> list[dict]:
        return [
            {
                "source_file": self.SITE_A,
                "source_line": 10,
                "source_file_sha256": self.site_hashes[self.SITE_A],
                "count": 2,
            },
            {
                "source_file": self.SITE_B,
                "source_line": 20,
                "source_file_sha256": self.site_hashes[self.SITE_B],
                "count": 1,
            },
        ]

    def _declaration(self) -> dict:
        return {
            "status": "measured-under-stub",
            "required": True,
            "fixture_id": "interior_tavern",
            "party_size": 1,
            "call_count": 3,
            "call_sites": self._sites(),
            "stub_sha256": {
                "path": preflight_profiles.STUB_FILE,
                "sha256": self.tool_hashes[preflight_profiles.STUB_FILE],
            },
            "driver_sha256": [
                {"path": path, "sha256": self.tool_hashes[path]}
                for path in preflight_profiles.DRIVER_FILES
            ],
            "provenance": {"run_id": "fr11-run-01", "evidence_sha256": "e" * 64},
        }

    def _document(self, declaration: dict) -> dict:
        document = copy_baseline_profile_document()
        document["profiles"][0]["startup"] = declaration
        return document

    def _match(self, declaration, *, count=3, sites=None, tool_hashes=None) -> dict:
        return preflight_profiles.match_lifecycle_declaration(
            declaration,
            observed_call_count=count,
            observed_call_sites=self._sites() if sites is None else sites,
            observed_tool_hashes=self.tool_hashes if tool_hashes is None else tool_hashes,
        )

    def test_declaration_shape_validates_against_schema_and_loader(self) -> None:
        document = self._document(self._declaration())
        schema_path = PROFILE_PATH.with_name("live_gate_preflight_profiles.schema.json")
        Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(
            document
        )
        coverage = preflight_profiles.validate_profile_document(document)
        self.assertFalse(coverage["measured_lifecycle_complete"])
        self.assertFalse(coverage["booking_eligible"])

    def test_declaration_is_not_bound_to_the_current_tree_or_a_sha(self) -> None:
        declaration = self._declaration()
        declaration["call_sites"][0]["source_file_sha256"] = "1" * 64
        declaration["stub_sha256"]["sha256"] = "2" * 64
        # Shape-valid even though no hash equals the working tree.
        preflight_profiles.validate_profile_document(self._document(declaration))
        for removed in ("source_sha", "command", "pythonpath", "evidence_path"):
            declaration[removed] = "x"
            with self.assertRaisesRegex(ProfileValidationError, "fields are malformed"):
                preflight_profiles.validate_profile_document(self._document(declaration))
            del declaration[removed]

    def test_exact_match_passes(self) -> None:
        result = self._match(self._declaration())
        self.assertEqual(result["kinds"], [])
        self.assertEqual(result["differences"], {})

    def test_call_site_file_hash_change_is_file_hash_mismatch(self) -> None:
        sites = self._sites()
        sites[0]["source_file_sha256"] = "9" * 64
        result = self._match(self._declaration(), sites=sites)
        self.assertEqual(result["kinds"], ["file_hash_mismatch"])
        self.assertEqual(
            result["differences"]["file_hashes"],
            [
                {
                    "path": self.SITE_A,
                    "expected": self.site_hashes[self.SITE_A],
                    "observed": ["9" * 64],
                }
            ],
        )

    def test_stub_hash_change_is_stub_hash_mismatch(self) -> None:
        changed = dict(self.tool_hashes)
        changed[preflight_profiles.STUB_FILE] = "8" * 64
        result = self._match(self._declaration(), tool_hashes=changed)
        self.assertEqual(result["kinds"], ["stub_hash_mismatch"])
        self.assertEqual(result["differences"]["stub_hash"]["observed"], "8" * 64)

    def test_driver_hash_change_is_driver_hash_mismatch(self) -> None:
        changed = dict(self.tool_hashes)
        driver = preflight_profiles.DRIVER_FILES[1]
        changed[driver] = "7" * 64
        result = self._match(self._declaration(), tool_hashes=changed)
        self.assertEqual(result["kinds"], ["driver_hash_mismatch"])
        self.assertEqual(result["differences"]["driver_hashes"][0]["path"], driver)

    def test_missing_tool_hash_never_matches(self) -> None:
        result = self._match(self._declaration(), tool_hashes={})
        self.assertEqual(result["kinds"], ["stub_hash_mismatch", "driver_hash_mismatch"])

    def test_extra_observed_site_is_call_sites_mismatch(self) -> None:
        sites = self._sites() + [
            {
                "source_file": self.SITE_B,
                "source_line": 99,
                "source_file_sha256": self.site_hashes[self.SITE_B],
                "count": 1,
            }
        ]
        result = self._match(self._declaration(), count=4, sites=sites)
        self.assertIn("call_sites_mismatch", result["kinds"])
        self.assertEqual(
            result["differences"]["call_sites"]["extra"],
            [{"source_file": self.SITE_B, "source_line": 99}],
        )

    def test_missing_observed_site_is_call_sites_mismatch(self) -> None:
        result = self._match(self._declaration(), count=2, sites=self._sites()[:1])
        self.assertEqual(result["kinds"], ["call_sites_mismatch", "total_mismatch"])
        self.assertEqual(
            result["differences"]["call_sites"]["missing"],
            [{"source_file": self.SITE_B, "source_line": 20}],
        )

    def test_count_change_is_call_sites_mismatch(self) -> None:
        sites = self._sites()
        sites[0]["count"] = 3
        result = self._match(self._declaration(), count=3, sites=sites)
        self.assertEqual(result["kinds"], ["call_sites_mismatch"])
        self.assertEqual(
            result["differences"]["call_sites"]["count_changes"],
            [
                {
                    "source_file": self.SITE_A,
                    "source_line": 10,
                    "expected": 2,
                    "observed": 3,
                }
            ],
        )

    def test_total_mismatch_alone_is_reported(self) -> None:
        result = self._match(self._declaration(), count=4)
        self.assertEqual(result["kinds"], ["total_mismatch"])
        self.assertEqual(result["differences"]["total"], {"expected": 3, "observed": 4})

    def test_absolute_path_is_rejected_everywhere(self) -> None:
        mutations = (
            lambda d: d["call_sites"][0].__setitem__("source_file", "/Users/x/a.py"),
            lambda d: d["stub_sha256"].__setitem__("path", "/abs/stub.py"),
            lambda d: d["provenance"].__setitem__("run_id", "/abs"),
            lambda d: d.__setitem__("note", "C:\\work\\a.py"),
        )
        for mutate in mutations:
            declaration = self._declaration()
            mutate(declaration)
            with self.assertRaisesRegex(ProfileValidationError, "absolute path"):
                preflight_profiles.validate_profile_document(self._document(declaration))

    def test_tmp_path_is_rejected(self) -> None:
        for mutate in (
            lambda d: d["call_sites"][0].__setitem__("source_file", "tmp/x/a.py"),
            lambda d: d["driver_sha256"][0].__setitem__("path", "scripts/tmp/a.py"),
            lambda d: d["provenance"].__setitem__("evidence_path", "tmp/router/e.json"),
        ):
            declaration = self._declaration()
            mutate(declaration)
            with self.assertRaisesRegex(ProfileValidationError, "tmp/ path"):
                preflight_profiles.validate_profile_document(self._document(declaration))

    def test_parent_traversal_path_is_rejected(self) -> None:
        declaration = self._declaration()
        declaration["call_sites"][0]["source_file"] = "scripts/../config.py"
        with self.assertRaisesRegex(ProfileValidationError, "not a safe repository-relative"):
            preflight_profiles.validate_profile_document(self._document(declaration))

    def test_counts_must_sum_and_pair_must_match(self) -> None:
        declaration = self._declaration()
        declaration["call_count"] = 4
        with self.assertRaisesRegex(ProfileValidationError, "do not sum"):
            preflight_profiles.validate_profile_document(self._document(declaration))
        declaration = self._declaration()
        declaration["party_size"] = 4
        with self.assertRaisesRegex(ProfileValidationError, "fixture-party binding"):
            preflight_profiles.validate_profile_document(self._document(declaration))

    def test_missing_lifecycles_remain_valid(self) -> None:
        coverage = preflight_profiles.validate_profile_document(copy_baseline_profile_document())
        self.assertFalse(coverage["measured_lifecycle_complete"])

    def test_startup_is_required_and_missing_resume_is_optional(self) -> None:
        document = copy_baseline_profile_document()
        profile = document["profiles"][0]
        profile["startup"]["required"] = False
        with self.assertRaisesRegex(ProfileValidationError, "startup lifecycle"):
            preflight_profiles.validate_profile_document(document)

        document = copy_baseline_profile_document()
        profile = document["profiles"][0]
        profile["resume"]["required"] = True
        with self.assertRaisesRegex(ProfileValidationError, "MISSING resume"):
            preflight_profiles.validate_profile_document(document)

    def test_optional_missing_resume_does_not_make_rows_unverified(self) -> None:
        document = copy_baseline_profile_document()
        for profile in document["profiles"]:
            startup = self._declaration()
            startup["fixture_id"] = profile["fixture_id"]
            startup["party_size"] = profile["party_size"]
            profile["startup"] = startup
            if profile["fixture_id"] == "landscape_village":
                profile["resume"] = {
                    "status": "MISSING",
                    "required": False,
                    "reason": "extra resume coverage not measured",
                }
            elif profile["fixture_id"] == "combat_stage_tavern_zones":
                profile["resume"] = {
                    "status": "MISSING",
                    "required": False,
                    "reason": "resume is not applicable to combat",
                }
            else:
                resume = self._declaration()
                resume["fixture_id"] = profile["fixture_id"]
                resume["party_size"] = profile["party_size"]
                resume["required"] = profile["fixture_id"] == "interior_tavern"
                profile["resume"] = resume

        coverage = preflight_profiles.validate_profile_document(document)

        self.assertEqual(coverage["unverified_row_ids"], [])
        self.assertTrue(coverage["measured_lifecycle_complete"])

    def test_declaration_from_evidence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="declaration-from-evidence-", dir=PROJECT_ROOT / "tmp"
        ) as directory:
            evidence = {
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "run_id": "fr11-roundtrip-01",
                "outcome": "completed",
                "failure_code": None,
                "call_count": 3,
                "call_sites": self._sites(),
            }
            path = Path(directory) / "profile-evidence.json"
            raw = json.dumps(evidence).encode("utf-8")
            path.write_bytes(raw)
            declaration = preflight_profiles.declaration_from_evidence(path)
            self.assertEqual(declaration, self._declaration() | {
                "provenance": {
                    "run_id": "fr11-roundtrip-01",
                    "evidence_sha256": hashlib.sha256(raw).hexdigest(),
                }
            })
            self.assertNotIn("tmp/", json.dumps(declaration))
            preflight_profiles.validate_profile_document(self._document(declaration))
            self.assertEqual(self._match(declaration)["kinds"], [])

            evidence["call_sites"][0]["source_file"] = "tmp/leak/a.py"
            path.write_bytes(json.dumps(evidence).encode("utf-8"))
            with self.assertRaisesRegex(ProfileValidationError, "tmp/ path"):
                preflight_profiles.declaration_from_evidence(path)
            evidence["call_sites"][0]["source_file"] = "/abs/a.py"
            path.write_bytes(json.dumps(evidence).encode("utf-8"))
            with self.assertRaisesRegex(ProfileValidationError, "absolute path"):
                preflight_profiles.declaration_from_evidence(path)
            evidence["call_sites"][0]["source_file"] = self.SITE_A
            evidence["outcome"] = "failed"
            path.write_bytes(json.dumps(evidence).encode("utf-8"))
            with self.assertRaisesRegex(ProfileValidationError, "did not complete"):
                preflight_profiles.declaration_from_evidence(path)


class TestCheckpointProfileEvidenceValidation(unittest.TestCase):
    """Require exact row, seed, path, and travel bindings for retained checkpoints."""

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory(
            prefix="checkpoint-profile-evidence-", dir=PROJECT_ROOT / "tmp"
        )
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _fixture(
        self,
        *,
        travel_changes: dict[str, Any] | None = None,
        attestation_changes: dict[str, Any] | None = None,
        descriptor_changes: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        run_id = "pf-checkpoint-profile-E01-f1-c"
        row_id = "E01"
        fixture_id = "interior_tavern"
        party_size = 1
        checkpoint_root = (
            "tmp/router-rollout/live-gate-preflight-checkpoints/"
            "%s/%s/%s-p%d" % (run_id, row_id, fixture_id, party_size)
        )
        travel = {
            "step_id": "step-01",
            "source_location_id": "TAVERN_01",
            "source_runtime_location_id": "TAVERN_01",
            "target_source_location_id": "TAVERN_02",
            "target_location_id": "TAVERN_02",
            "response_counts": {
                "travel_action_responses": 1,
                "gameplay_validation_responses": 1,
                "transition_validation_responses": 1,
                "transition_narration_responses": 1,
            },
            "response_call_sequences": {
                "travel_action": 2,
                "transition_validation": 3,
                "gameplay_validation": 4,
                "transition_narration": 5,
            },
            "complete": True,
        }
        if travel_changes:
            travel.update(travel_changes)
        descriptor = {
            "checkpoint_root": checkpoint_root,
            "state_sha256": "c" * 64,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": "A",
            "fixed_seed": 5101,
        }
        if descriptor_changes:
            descriptor.update(descriptor_changes)
        attestation = {
            "schema_version": 1,
            "source_sha": "a" * 40,
            "run_id": run_id,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": "A",
            "fixed_seed": 5101,
            "step_id": travel["step_id"],
            "source_location_id": travel["source_location_id"],
            "source_runtime_location_id": travel["source_runtime_location_id"],
            "target_source_location_id": travel["target_source_location_id"],
            "target_location_id": travel["target_location_id"],
            "initial_location_id": travel["source_runtime_location_id"],
            "final_location_id": travel["target_location_id"],
            "initial_state_sha256": "b" * 64,
            "state_sha256": descriptor["state_sha256"],
            "initial_time": "day-1 08:00",
            "final_time": "day-1 08:05",
            "travel_proof": dict(travel),
            "persistence": {
                "host_stopped_before_checkpoint": True,
                "canonical_state_hash_verified": True,
                "resume_state_validation": "passed",
            },
            "checkpoint_root": checkpoint_root,
        }
        if attestation_changes:
            attestation.update(attestation_changes)
        relative_attestation = checkpoint_root + "/attestation.json"
        attestation_path = self.root.joinpath(*Path(relative_attestation).parts)
        attestation_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(
            attestation, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        attestation_path.write_bytes(raw)
        evidence = {
            "run_id": run_id,
            "planned_row_id": row_id,
            "checkpoint_travel": travel,
            "resume_checkpoint": descriptor,
            "checkpoint_attestation": {
                "path": relative_attestation,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        }
        metadata = {
            row_id: {
                "arm": "A",
                "fixture_ids": [fixture_id],
                "party_size": party_size,
                "fixed_seed": 5101,
            }
        }
        return evidence, metadata

    def _validate(
        self,
        evidence: dict[str, Any],
        metadata: dict[str, dict[str, Any]],
    ) -> None:
        preflight_profiles._validate_profile_checkpoint_evidence(
            self.root,
            evidence=evidence,
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            row_metadata=metadata,
            source_sha="a" * 40,
        )

    def test_valid_row_bound_checkpoint_is_accepted(self) -> None:
        evidence, metadata = self._fixture()
        self._validate(evidence, metadata)

    def test_checkpoint_path_must_bind_to_run_row_and_fixture(self) -> None:
        evidence, metadata = self._fixture(
            descriptor_changes={
                "checkpoint_root": (
                    "tmp/router-rollout/live-gate-preflight-checkpoints/"
                    "another-run/E01/interior_tavern-p1"
                )
            }
        )
        with self.assertRaisesRegex(ProfileValidationError, "checkpoint path is invalid"):
            self._validate(evidence, metadata)

    def test_checkpoint_travel_sequence_must_be_complete_and_ordered(self) -> None:
        evidence, metadata = self._fixture(
            travel_changes={
                "response_call_sequences": {
                    "travel_action": 2,
                    "transition_validation": 2,
                    "gameplay_validation": 4,
                    "transition_narration": 5,
                }
            }
        )
        with self.assertRaisesRegex(
            ProfileValidationError, "checkpoint identity is invalid"
        ):
            self._validate(evidence, metadata)

    def test_checkpoint_attestation_must_match_row_seed_and_travel(self) -> None:
        evidence, metadata = self._fixture(
            attestation_changes={"fixed_seed": 5102}
        )
        with self.assertRaisesRegex(
            ProfileValidationError, "checkpoint attestation differs"
        ):
            self._validate(evidence, metadata)


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
        combat_main_repeated_responses = [stub("combat_main") for _ in range(2)]
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
                    "combat_main_repeated_responses": combat_main_repeated_responses,
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


class TestCheckedInProfileDeclarations(unittest.TestCase):
    """Pins the real measured declarations in the checked-in profile file."""

    COMBAT_FIXTURE = "combat_stage_tavern_zones"

    @staticmethod
    def _sha256(relative_path: str) -> str:
        return hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest()

    def _profiles(self) -> list[dict]:
        return copy_profile_document()["profiles"]

    def test_checked_in_declaration_loads_with_startup_measured_for_all_eight_pairs(
        self,
    ) -> None:
        coverage = load_profile_coverage()
        self.assertTrue(coverage["structural_row_coverage_complete"])
        profiles = self._profiles()
        self.assertEqual(len(profiles), 8)
        for profile in profiles:
            startup = profile["startup"]
            expected = 2 if profile["fixture_id"] == self.COMBAT_FIXTURE else 9
            with self.subTest(profile=profile["profile_id"]):
                self.assertEqual(startup["status"], "measured-under-stub")
                self.assertEqual(startup["call_count"], expected)

    def test_checked_in_resume_is_measured_for_six_non_combat_pairs_only(self) -> None:
        profiles = self._profiles()
        measured = [p for p in profiles if p["resume"]["status"] == "measured-under-stub"]
        missing = [p for p in profiles if p["resume"]["status"] == "MISSING"]
        self.assertEqual(len(measured), 6)
        self.assertEqual(len(missing), 2)
        for profile in measured:
            with self.subTest(profile=profile["profile_id"]):
                self.assertNotEqual(profile["fixture_id"], self.COMBAT_FIXTURE)
                self.assertEqual(profile["resume"]["call_count"], 9)
        for profile in missing:
            with self.subTest(profile=profile["profile_id"]):
                self.assertEqual(profile["fixture_id"], self.COMBAT_FIXTURE)
                self.assertIn("NOT APPLICABLE", profile["resume"]["reason"])

    def test_checked_in_declaration_has_no_absolute_or_tmp_paths_or_forbidden_keys(
        self,
    ) -> None:
        text = PROFILE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("tmp/", text)
        self.assertIsNone(re.search(r'"(/|[A-Za-z]:[\\/])', text))
        forbidden = {"source_sha", "command", "pythonpath", "evidence_path"}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                self.assertFalse(forbidden & set(value), sorted(forbidden & set(value)))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(json.loads(text))

    def test_measured_hashes_match_working_tree_so_edits_force_remeasure(self) -> None:
        checked = 0
        for profile in self._profiles():
            for lifecycle in ("startup", "resume"):
                declaration = profile[lifecycle]
                if declaration["status"] != "measured-under-stub":
                    continue
                label = profile["profile_id"] + ":" + lifecycle
                entries = [declaration["stub_sha256"], *declaration["driver_sha256"]]
                for entry in entries:
                    checked += 1
                    self.assertEqual(
                        entry["sha256"],
                        self._sha256(entry["path"]),
                        label + ": " + entry["path"] + " changed since measurement; "
                        "re-measure the lifecycle profile and update the declaration",
                    )
                for site in declaration["call_sites"]:
                    checked += 1
                    self.assertEqual(
                        site["source_file_sha256"],
                        self._sha256(site["source_file"]),
                        label + ": " + site["source_file"] + " changed since "
                        "measurement; re-measure the lifecycle profile",
                    )
        self.assertGreater(checked, 0)

    def test_checked_in_required_coverage_is_complete_but_not_booking_eligible(self) -> None:
        coverage = load_profile_coverage()
        self.assertTrue(coverage["measured_lifecycle_complete"])
        self.assertFalse(coverage["booking_eligible"])
        self.assertEqual(coverage["unverified_row_ids"], [])


class TestWorkerHostCommandComparisonIdentity(unittest.TestCase):
    """Worker and launch sides must declare the same comparison-mode command."""

    RUNNER_PATH = PROJECT_ROOT / "scripts" / "live_gate_preflight_profile_runner.py"

    def _identity(self) -> dict[str, Any]:
        return build_comparison_identity(
            tool_sha="a" * 40,
            tool_tree="b" * 40,
            application_sha=APPLICATION_A_SHA,
            application_tree=APPLICATION_A_TREE,
        )

    def _command(self, comparison_identity: dict[str, Any] | None) -> list[str]:
        return profile_runner._host_command(
            fixture_id="combat_stage_tavern_zones",
            party_size=1,
            lifecycle="startup",
            source_sha=APPLICATION_A_SHA,
            run_id="comparison-worker-identity",
            planned_row_id="C01",
            arm="A",
            lifecycle_id="comparison-worker-identity_s",
            resume_checkpoint_sha256=None,
            comparison_identity=comparison_identity,
        )

    def test_comparison_identity_pair_is_declared_in_host_command(self) -> None:
        identity = self._identity()
        plain = self._command(None)
        command = self._command(identity)
        self.assertNotIn("--comparison-identity-json", plain)
        self.assertEqual(len(command), len(plain) + 2)
        self.assertEqual(command[: len(plain)], plain)
        flag_index = command.index("--comparison-identity-json")
        self.assertEqual(flag_index, len(plain))
        self.assertEqual(json.loads(command[flag_index + 1]), identity)

    def test_both_host_command_call_sites_forward_comparison_identity(self) -> None:
        # The worker entry is one large function and cannot run hermetically,
        # so pin the keyword at both declared-command sites from the AST.
        tree = ast.parse(self.RUNNER_PATH.read_text(encoding="utf-8"))
        sites = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_host_command"
        ]
        self.assertEqual(len(sites), 2)
        for site in sites:
            keywords = {keyword.arg: keyword.value for keyword in site.keywords}
            with self.subTest(line=site.lineno):
                self.assertIn("comparison_identity", keywords)
                self.assertEqual(
                    ast.unparse(keywords["comparison_identity"]),
                    "getattr(args, 'comparison_identity_json', None)",
                )


if __name__ == "__main__":
    unittest.main()
