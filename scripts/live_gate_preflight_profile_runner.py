# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Primary-operated, bounded characterization of startup and resume paths.

This runner consumes an already prepared ``tmp/combat_capture`` copy. Launch it
with the dedicated preflight guard directory first on ``PYTHONPATH``, followed
by the repository root, and use the repository venv. It never seeds fixtures
or changes the checked-in profile declaration. Each invocation measures one
fixture-party pair and one lifecycle, retaining separate evidence.
"""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import ipaddress
import importlib.abc
import importlib.machinery
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_EVIDENCE_ROOT = Path(
    "tmp/router-rollout/live-gate-preflight/profile-characterization"
)
SANDBOX_RELATIVE = Path("tmp/combat_capture")
AUTHORIZATION_RULING_ID = "neq-w1-fr11-profiles-characterization-20261112"
HOST_PORT = 8360
PLAYER_PORT = 8370
REQUIRED_PORTS = (HOST_PORT, PLAYER_PORT)
NETSTAT_EXECUTABLE = "/usr/sbin/netstat"
LSOF_EXECUTABLE = "/usr/sbin/lsof"
STARTUP_TIMEOUT_SECONDS = 60.0
STOP_TIMEOUT_SECONDS = 12.0
OBSERVER_TIMEOUT_SECONDS = 3.0
MAX_OBSERVER_OUTPUT_BYTES = 32768
MAX_NETSTAT_OUTPUT_BYTES = 8_000_000
MAX_NETSTAT_ROWS = 100_000
MAX_CHARACTERIZATION_ATTEMPTS = 16
LIVE_WINDOW_HOURS = 1
MAX_LIVE_WINDOW_HOURS = 8
LIVE_WINDOW_HOLDER = "N agent-run"
LIVE_WINDOW_BOOKING_ROLE = "N"
PROFILE_CHARACTERIZATION_FROZEN_CAPS = {
    "max_characterization_attempts": MAX_CHARACTERIZATION_ATTEMPTS,
    "max_attempts_per_profile_lifecycle": 1,
    "provider_requests": 0,
    "live_attempt_allowance": 0,
    "startup_timeout_seconds": STARTUP_TIMEOUT_SECONDS,
    "stop_timeout_seconds": STOP_TIMEOUT_SECONDS,
    "observer_timeout_seconds": OBSERVER_TIMEOUT_SECONDS,
    "window_hours": LIVE_WINDOW_HOURS,
}
_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    "combat_stage_tavern_zones",
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA1_OR_SHA256 = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NETSTAT_OWNER_PATTERN = re.compile(
    rb":(?P<pid>[0-9]+)\s+(?P<field1>[0-9a-f]{5})\s+"
    rb"(?P<field2>[0-9a-f]{8})\s+(?P<field3>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_NETSTAT_OWNER_PID_CANDIDATE_PATTERN = re.compile(rb":(?P<pid>[0-9]+)(?=\s|$)")
_BOOKING_ID = re.compile(
    r"^live-gate-preflight-[NS]-[0-9]{8}T[0-9]{6}Z$"
)
_KNOWN_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)
_SECRET_ENV_NAME = re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)
_PROXY_ENV_NAME = re.compile(r"(?:^|_)PROXY$", re.IGNORECASE)
_SOURCE_BOUND_FILES = (
    "scripts/live_gate_preflight_profile_runner.py",
    "scripts/live_gate_preflight_sandbox.py",
    "scripts/live_gate_preflight_profiles.py",
    "scripts/live_gate_preflight_profiles.json",
    "scripts/live_gate_preflight_profiles.schema.json",
    "scripts/live_gate_preflight_safety.py",
    "scripts/live_gate_preflight_stub.py",
    "scripts/sitecustomize.py",
    "scripts/live_gate_preflight_guard/sitecustomize.py",
)


class CharacterizationError(RuntimeError):
    """Raised when a run cannot safely produce a measured profile."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CharacterizationError("live_window_timestamp_invalid")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        return None
    return parsed


def _build_live_window_lock_record(
    *,
    run_id: str,
    fixture_id: str,
    party_size: int,
    lifecycle: str,
    planned_row_id: str,
    source_sha: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise CharacterizationError("live_window_timestamp_invalid")
    start = instant.astimezone(timezone.utc).replace(microsecond=0)
    end = start + timedelta(hours=LIVE_WINDOW_HOURS)
    booking_timestamp = start.strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": 1,
        "holder": LIVE_WINDOW_HOLDER,
        "gate": "live-gate-preflight",
        "run_id": run_id,
        "booking_id": "live-gate-preflight-%s-%s"
        % (LIVE_WINDOW_BOOKING_ROLE, booking_timestamp),
        "authorizing_ruling": AUTHORIZATION_RULING_ID,
        "window_start": _format_utc_timestamp(start),
        "window_end": _format_utc_timestamp(end),
        "frozen_caps": dict(PROFILE_CHARACTERIZATION_FROZEN_CAPS),
        "ports": list(REQUIRED_PORTS),
        "fixture_id": fixture_id,
        "party_size": party_size,
        "lifecycle": lifecycle,
        "planned_row_id": planned_row_id,
        "source_sha": source_sha,
    }


def _matches_frozen_caps(value: Any) -> bool:
    expected = PROFILE_CHARACTERIZATION_FROZEN_CAPS
    if not isinstance(value, Mapping) or set(value) != set(expected):
        return False
    return all(
        type(value[key]) is type(expected_value)
        and value[key] == expected_value
        for key, expected_value in expected.items()
    )


def _valid_live_window_lock_record(value: Any, *, now: datetime | None = None) -> bool:
    required_fields = {
        "schema_version",
        "holder",
        "gate",
        "run_id",
        "booking_id",
        "authorizing_ruling",
        "window_start",
        "window_end",
        "frozen_caps",
        "ports",
        "fixture_id",
        "party_size",
        "lifecycle",
        "planned_row_id",
        "source_sha",
    }
    if not isinstance(value, Mapping) or set(value) != required_fields:
        return False
    start = _parse_utc_timestamp(value.get("window_start"))
    end = _parse_utc_timestamp(value.get("window_end"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return False
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("holder") != LIVE_WINDOW_HOLDER
        or value.get("gate") != "live-gate-preflight"
        or not isinstance(value.get("run_id"), str)
        or _SAFE_RUN_ID.fullmatch(str(value.get("run_id"))) is None
        or not isinstance(value.get("booking_id"), str)
        or _BOOKING_ID.fullmatch(str(value.get("booking_id"))) is None
        or not isinstance(value.get("authorizing_ruling"), str)
        or value.get("authorizing_ruling") != AUTHORIZATION_RULING_ID
        or not _matches_frozen_caps(value.get("frozen_caps"))
        or value.get("ports") != list(REQUIRED_PORTS)
        or value.get("fixture_id") not in _FIXTURE_IDS
        or type(value.get("party_size")) is not int
        or value.get("party_size") not in (1, 4)
        or value.get("lifecycle") not in ("startup", "resume")
        or not isinstance(value.get("planned_row_id"), str)
        or _SAFE_RUN_ID.fullmatch(str(value.get("planned_row_id"))) is None
        or not isinstance(value.get("source_sha"), str)
        or _SHA1_OR_SHA256.fullmatch(str(value.get("source_sha"))) is None
        or start is None
        or end is None
    ):
        return False
    expected_booking_id = "live-gate-preflight-%s-%s" % (
        LIVE_WINDOW_BOOKING_ROLE,
        start.strftime("%Y%m%dT%H%M%SZ"),
    )
    duration = (end - start).total_seconds()
    current_utc = current.astimezone(timezone.utc)
    return bool(
        value.get("booking_id") == expected_booking_id
        and 0 < duration <= MAX_LIVE_WINDOW_HOURS * 60 * 60
        and duration <= LIVE_WINDOW_HOURS * 60 * 60
        and start <= current_utc < end
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure one real mapping-pilot startup or resume path using the "
            "fail-closed preflight stub. Requires a prepared tmp/combat_capture."
        )
    )
    parser.add_argument("--fixture-id", choices=_FIXTURE_IDS)
    parser.add_argument("--party-size", type=int, choices=(1, 4))
    parser.add_argument("--lifecycle", choices=("startup", "resume"))
    parser.add_argument("--source-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--resume-checkpoint-sha256")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--planned-row-id", help=argparse.SUPPRESS)
    parser.add_argument("--arm", choices=("A", "B", "D"), help=argparse.SUPPRESS)
    parser.add_argument("--lifecycle-id", help=argparse.SUPPRESS)
    if argv is None and len(sys.argv) > 1 and sys.argv[1] == "--worker":
        args = parser.parse_args(sys.argv[1:])
    else:
        args = parser.parse_args(argv)
    if args.worker:
        required = (
            args.fixture_id,
            args.party_size,
            args.lifecycle,
            args.source_sha,
            args.run_id,
            args.planned_row_id,
            args.arm,
            args.lifecycle_id,
        )
        if any(value is None for value in required):
            parser.error("internal worker identity is incomplete")
        return args
    if any(
        value is None
        for value in (args.fixture_id, args.party_size, args.lifecycle, args.source_sha)
    ):
        parser.error(
            "--fixture-id, --party-size, --lifecycle, and --source-sha are required"
        )
    if args.lifecycle == "resume":
        if not isinstance(args.resume_checkpoint_sha256, str) or not _SHA256.fullmatch(
            args.resume_checkpoint_sha256
        ):
            parser.error("--resume requires --resume-checkpoint-sha256 with a SHA-256")
    elif args.resume_checkpoint_sha256 is not None:
        parser.error("--resume-checkpoint-sha256 is only valid for --lifecycle resume")
    return args


def _require_safe_project_root() -> Path:
    try:
        root = PROJECT_ROOT.resolve(strict=True)
        current = Path.cwd().resolve(strict=True)
        tmp_root = root / "tmp"
        current.relative_to(tmp_root.resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise CharacterizationError("isolated_controller_root_unavailable") from exc
    except ValueError as exc:
        raise CharacterizationError("controller_must_start_in_project_tmp") from exc
    if (
        current in (tmp_root.resolve(strict=True), root)
        or root.is_symlink()
        or tmp_root.is_symlink()
    ):
        raise CharacterizationError("controller_must_start_in_isolated_tmp_directory")
    return root


def _require_safe_worker_root() -> Path:
    try:
        root = PROJECT_ROOT.resolve(strict=True)
        sandbox = (root / SANDBOX_RELATIVE).resolve(strict=True)
        current = Path.cwd().resolve(strict=True)
        sandbox.relative_to((root / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise CharacterizationError("sandbox_worker_root_unavailable") from exc
    if (
        current != sandbox
        or (root / "tmp").is_symlink()
        or (root / SANDBOX_RELATIVE).is_symlink()
    ):
        raise CharacterizationError("worker_must_start_in_isolated_sandbox")
    return root


def _require_parent_startup_guard() -> None:
    _require_process_startup_guard(
        PROJECT_ROOT / "scripts" / "live_gate_preflight_guard" / "sitecustomize.py",
        expected_role="parent",
        failure_code="parent_startup_guard_inactive",
    )


def _validate_startup_canary_record(
    report: Any,
    *,
    process_role: str,
    command: Sequence[str],
    cwd: str | Path,
    environment_sha256: str,
    expected_pid: int | None = None,
) -> dict[str, Any]:
    """Require complete startup evidence before accepting a process launch."""
    if not isinstance(report, Mapping):
        raise CharacterizationError("startup_canary_report_invalid")
    selected_command = list(command)
    expected_command_sha256 = hashlib.sha256(
        json.dumps(selected_command, ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()
    pid = report.get("pid")
    startup_observed_at_ns = report.get("startup_observed_at_ns")
    interpreter = report.get("interpreter")
    if (
        report.get("process_role") != process_role
        or type(pid) is not int
        or pid <= 0
        or (expected_pid is not None and pid != expected_pid)
        or type(startup_observed_at_ns) is not int
        or startup_observed_at_ns <= 0
        or report.get("command") != selected_command
        or report.get("command_sha256") != expected_command_sha256
        or report.get("environment_sha256") != environment_sha256
        or report.get("working_directory") != str(Path(cwd))
        or report.get("guard_active") is not True
        or report.get("non_loopback_connect_denied") is not True
        or report.get("subprocess_launch_denied") is not True
        or not isinstance(interpreter, Mapping)
        or interpreter.get("executable") != str(PROJECT_ROOT / ".venv" / "bin" / "python")
        or interpreter.get("prefix") != str(PROJECT_ROOT / ".venv")
        or not isinstance(interpreter.get("base_prefix"), str)
        or interpreter.get("prefix") == interpreter.get("base_prefix")
    ):
        raise CharacterizationError("startup_canary_report_invalid")
    return dict(report)


def _require_worker_startup_guard() -> None:
    _require_process_startup_guard(
        PROJECT_ROOT / "scripts" / "live_gate_preflight_guard" / "sitecustomize.py",
        expected_role="host",
        failure_code="host_startup_guard_inactive",
    )


def _require_process_startup_guard(
    expected_sitecustomize: Path, *, expected_role: str, failure_code: str
) -> None:
    """Check startup-installed safety without importing project application code."""
    from scripts.live_gate_preflight_safety import (
        CANARY_REPORT_ENV,
        PROCESS_ROLE_ENV,
        current_invocation_command,
        require_startup_guard_active,
    )

    if (
        os.environ.get("NEQ_PREFLIGHT_STARTUP_GUARD_REQUIRED") != "1"
        or os.environ.get("NEQ_PREFLIGHT_NETWORK_GUARD") != "1"
        or os.environ.get("NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE") != "1"
        or os.environ.get("NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE") != "1"
        or os.environ.get("NEQ_PREFLIGHT_ENV_SANITIZED") != "1"
        or os.environ.get("NEQ_PREFLIGHT_CONNECT_CANARY_DENIED") != "1"
        or os.environ.get("NEQ_PREFLIGHT_SUBPROCESS_CANARY_DENIED") != "1"
    ):
        raise CharacterizationError(failure_code)
    try:
        require_startup_guard_active()
    except Exception as exc:
        raise CharacterizationError(failure_code) from exc
    startup_module = sys.modules.get("sitecustomize")
    startup_path = getattr(startup_module, "__file__", None)
    guard_module = sys.modules.get("scripts.live_gate_preflight_safety")
    try:
        observed_sitecustomize = Path(startup_path).resolve(strict=True)
        expected_path = expected_sitecustomize.resolve(strict=True)
        observed_guard = Path(getattr(guard_module, "__file__", None)).resolve(strict=True)
        expected_guard = PROJECT_ROOT / "scripts" / "live_gate_preflight_safety.py"
        expected_site_bytes = expected_path.read_bytes()
        expected_guard_bytes = expected_guard.read_bytes()
        observed_site_bytes = observed_sitecustomize.read_bytes()
        observed_guard_bytes = observed_guard.read_bytes()
    except (OSError, RuntimeError, TypeError) as exc:
        raise CharacterizationError(failure_code) from exc
    if (
        observed_sitecustomize != expected_path
        or observed_site_bytes != expected_site_bytes
        or observed_guard != expected_guard
        or observed_guard_bytes != expected_guard_bytes
        or not getattr(guard_module, "_GUARD_INSTALLED", False)
        or not getattr(guard_module, "_SUBPROCESS_GUARD_INSTALLED", False)
        or getattr(guard_module, "subprocess").Popen
        is not getattr(guard_module, "_GuardedPopen")
    ):
        raise CharacterizationError(failure_code)
    expected_pythonpath = os.pathsep.join(
        (
            str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
            str(PROJECT_ROOT),
        )
    )
    if os.environ.get("PYTHONPATH") != expected_pythonpath:
        raise CharacterizationError("pythonpath_identity_invalid")
    _require_repository_venv()
    try:
        canary_report = json.loads(os.environ.get(CANARY_REPORT_ENV, ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CharacterizationError("startup_canary_report_invalid") from exc
    actual_command = current_invocation_command()
    command_sha256 = hashlib.sha256(
        json.dumps(actual_command, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    if (
        not isinstance(canary_report, Mapping)
        or os.environ.get(PROCESS_ROLE_ENV) != expected_role
        or canary_report.get("process_role") != expected_role
        or type(canary_report.get("pid")) is not int
        or canary_report.get("pid") != os.getpid()
        or type(canary_report.get("startup_observed_at_ns")) is not int
        or canary_report.get("startup_observed_at_ns") <= 0
        or canary_report.get("command") != actual_command
        or canary_report.get("command_sha256") != command_sha256
        or canary_report.get("guard_active") is not True
        or canary_report.get("non_loopback_connect_denied") is not True
        or canary_report.get("subprocess_launch_denied") is not True
        or canary_report.get("interpreter") != _interpreter_identity()
        or not isinstance(canary_report.get("command_sha256"), str)
        or _SHA256.fullmatch(str(canary_report.get("environment_sha256", ""))) is None
        or canary_report.get("working_directory") != str(Path.cwd())
    ):
        raise CharacterizationError("startup_canary_report_invalid")
    if "config" in sys.modules:
        raise CharacterizationError("configuration_loaded_before_characterization")
    if any(os.environ.get(name, "") for name in _KNOWN_PROVIDER_KEYS):
        raise CharacterizationError("provider_keys_not_blank")
    for name, value in os.environ.items():
        if (_SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name)) and value:
            raise CharacterizationError("preflight_environment_not_sanitized")


def _require_repository_venv() -> None:
    """Require the exact venv invocation and its project-owned sys.prefix."""
    expected_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    expected_prefix = str(PROJECT_ROOT / ".venv")
    if (
        sys.executable != expected_python
        or sys.prefix != expected_prefix
        or sys.prefix == sys.base_prefix
    ):
        raise CharacterizationError("runner_must_use_repository_venv")


def _interpreter_identity() -> dict[str, str]:
    return {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }


class _SandboxConfigOriginGuard(importlib.abc.MetaPathFinder):
    """Refuse imports of config.py unless resolution points inside the sandbox."""

    def __init__(self, sandbox: Path) -> None:
        self.sandbox_config = sandbox / "config.py"

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: Any = None,
    ) -> Any:
        del target
        if fullname != "config":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        origin = getattr(spec, "origin", None)
        try:
            resolved_origin = Path(origin).resolve(strict=True)
            expected = self.sandbox_config.resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise ImportError("sandbox config origin is unavailable") from exc
        if resolved_origin != expected:
            raise ImportError("real project config.py is forbidden in preflight")
        return spec


def _install_sandbox_config_guard(sandbox: Path) -> _SandboxConfigOriginGuard:
    existing = sys.modules.get("config")
    if existing is not None:
        origin = getattr(existing, "__file__", None)
        try:
            if Path(origin).resolve(strict=True) != (sandbox / "config.py").resolve(strict=True):
                raise CharacterizationError("real_project_config_was_already_loaded")
        except (OSError, RuntimeError, TypeError) as exc:
            raise CharacterizationError("sandbox_config_origin_unavailable") from exc
    guard = _SandboxConfigOriginGuard(sandbox)
    sys.meta_path.insert(0, guard)
    return guard


def _remove_import_guard(guard: _SandboxConfigOriginGuard | None) -> None:
    if guard is None:
        return
    try:
        sys.meta_path.remove(guard)
    except ValueError:
        return


def _configure_sandbox_import_paths(root: Path, sandbox: Path) -> None:
    """Bind the host tooling package to root while keeping sandbox imports first."""
    root_text = str(root)
    sandbox_text = str(sandbox)
    if "scripts" not in sys.modules:
        sys.path.insert(0, root_text)
        try:
            package = importlib.import_module("scripts")
        finally:
            try:
                sys.path.remove(root_text)
            except ValueError:
                pass
    else:
        package = sys.modules["scripts"]
    package_path = getattr(package, "__file__", None)
    try:
        expected_package_directory = (root / "scripts").resolve(strict=True)
        if package_path is not None:
            expected_package = (expected_package_directory / "__init__.py").resolve(strict=True)
            if Path(package_path).resolve(strict=True) != expected_package:
                raise CharacterizationError("project_scripts_package_source_mismatch")
        else:
            locations = getattr(package, "__path__", ())
            resolved_locations = {
                Path(location).resolve(strict=True) for location in locations
            }
            if expected_package_directory not in resolved_locations:
                raise CharacterizationError("project_scripts_package_source_mismatch")
            package.__path__ = [str(expected_package_directory)]
            package_spec = getattr(package, "__spec__", None)
            if package_spec is not None:
                package_spec.submodule_search_locations = package.__path__
    except (OSError, RuntimeError, TypeError) as exc:
        raise CharacterizationError("project_scripts_package_unavailable") from exc

    filtered: list[str] = []
    for entry in sys.path:
        try:
            resolved = Path(entry or Path.cwd()).resolve(strict=False)
        except (OSError, RuntimeError):
            filtered.append(entry)
            continue
        if resolved not in (root, sandbox):
            filtered.append(entry)
    sys.path[:] = filtered
    sys.path.insert(0, sandbox_text)
    sys.path.insert(1, root_text)


def _git_output(arguments: Sequence[str], *, timeout: float = 10.0) -> str:
    from scripts.live_gate_preflight_safety import run_guarded_subprocess

    try:
        completed = run_guarded_subprocess(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CharacterizationError("git_identity_unavailable") from exc
    if completed.returncode != 0:
        raise CharacterizationError("git_identity_unavailable")
    return completed.stdout.strip()


def _verify_source_identity(source_sha: str) -> None:
    if not isinstance(source_sha, str) or _SHA1_OR_SHA256.fullmatch(source_sha) is None:
        raise CharacterizationError("source_sha_invalid")
    observed = _git_output(("rev-parse", "HEAD"))
    if observed != source_sha:
        raise CharacterizationError("source_sha_differs_from_head")
    try:
        from scripts.live_gate_preflight_safety import run_guarded_subprocess

        completed = run_guarded_subprocess(
            ["git", "diff", "--quiet", "HEAD", "--"],
            cwd=PROJECT_ROOT,
            check=False,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CharacterizationError("source_tree_identity_unavailable") from exc
    if completed.returncode != 0:
        raise CharacterizationError("tracked_source_tree_is_dirty")
    for relative in _SOURCE_BOUND_FILES:
        path = PROJECT_ROOT / relative
        try:
            current_bytes = path.read_bytes()
            committed = run_guarded_subprocess(
                ["git", "show", "%s:%s" % (source_sha, relative)],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                timeout=10.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CharacterizationError("source_file_identity_unavailable") from exc
        if committed.returncode != 0 or committed.stdout != current_bytes:
            raise CharacterizationError("source_file_differs_from_declared_sha")
    _require_repository_venv()


def _safe_project_file(relative: str | Path, label: str) -> Path:
    raw = PurePosixPath(str(relative))
    if (
        raw.is_absolute()
        or ".." in raw.parts
        or "\\" in str(relative)
        or not raw.parts
    ):
        raise CharacterizationError(label + "_path_invalid")
    candidate = PROJECT_ROOT.joinpath(*raw.parts)
    cursor = PROJECT_ROOT
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CharacterizationError(label + "_path_invalid")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise CharacterizationError(label + "_path_unavailable") from exc
    if not resolved.is_file():
        raise CharacterizationError(label + "_path_unavailable")
    return resolved


def _read_json(path: Path, label: str) -> Any:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 2_000_000:
            raise CharacterizationError(label + "_invalid")
        raw = os.read(descriptor, 2_000_001)
        if len(raw) > 2_000_000:
            raise CharacterizationError(label + "_invalid")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except CharacterizationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CharacterizationError(label + "_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non_standard_json_value:" + value)


def _validate_prepared_sandbox(
    *,
    fixture_id: str,
    party_size: int,
    lifecycle: str,
    resume_checkpoint_sha256: str | None,
) -> tuple[Path, str, str, str, dict[str, str]]:
    from scripts.live_gate_preflight_profiles import (
        copy_profile_document,
        load_profile_coverage,
    )
    from scripts.live_gate_preflight_safety import validate_sandbox_config_location
    from scripts.mapping_pilot import launcher

    coverage = load_profile_coverage(expected_source_sha=None)
    if coverage["fixture_party_pair_count"] != 8 or coverage["replacement_only_rows_activated"]:
        raise CharacterizationError("profile_declaration_coverage_invalid")
    profiles = copy_profile_document().get("profiles")
    profile = next(
        (
            row
            for row in profiles
            if isinstance(row, Mapping)
            and row.get("fixture_id") == fixture_id
            and row.get("party_size") == party_size
        ),
        None,
    )
    if not isinstance(profile, Mapping):
        raise CharacterizationError("fixture_party_profile_missing")

    sandbox = PROJECT_ROOT / SANDBOX_RELATIVE
    if sandbox.is_symlink() or not sandbox.is_dir():
        raise CharacterizationError("prepared_sandbox_unavailable")
    sandbox = sandbox.resolve(strict=True)
    try:
        sandbox.relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise CharacterizationError("prepared_sandbox_path_invalid") from exc
    if (PROJECT_ROOT / "tmp").is_symlink():
        raise CharacterizationError("prepared_sandbox_path_invalid")
    config_path = validate_sandbox_config_location(
        SANDBOX_RELATIVE / "config.py",
        sandbox_root=SANDBOX_RELATIVE,
        project_root=PROJECT_ROOT,
    )
    if config_path != sandbox / "config.py":
        raise CharacterizationError("prepared_sandbox_config_invalid")
    _require_synthetic_sandbox_config(config_path)

    metadata_path = _safe_project_file(
        SANDBOX_RELATIVE / "mapping_pilot" / "seed_metadata.json",
        "sandbox_seed_metadata",
    )
    metadata = _read_json(metadata_path, "sandbox_seed_metadata")
    if not isinstance(metadata, Mapping) or metadata.get("fixture_id") != fixture_id:
        raise CharacterizationError("prepared_sandbox_fixture_mismatch")
    party = metadata.get("party")
    members = party.get("members") if isinstance(party, Mapping) else None
    if (
        not isinstance(party, Mapping)
        or party.get("size") != party_size
        or not isinstance(members, list)
        or len(members) != party_size
        or any(not isinstance(member, str) or not member.strip() for member in members)
    ):
        raise CharacterizationError("prepared_sandbox_party_mismatch")
    counterbalance = metadata.get("counterbalance")
    if not isinstance(counterbalance, Mapping):
        raise CharacterizationError("prepared_sandbox_row_metadata_invalid")
    row_id = counterbalance.get("row_id")
    if (
        not isinstance(row_id, str)
        or row_id not in profile.get("planned_row_ids", [])
        or counterbalance.get("row_type") != "planned"
    ):
        raise CharacterizationError("prepared_sandbox_must_use_bound_planned_row")
    frozen_path = _safe_project_file(
        "plans/v2-mapping-pilot-prereg/counterbalance.json",
        "frozen_counterbalance",
    )
    frozen = _read_json(frozen_path, "frozen_counterbalance")
    rows = frozen.get("rows") if isinstance(frozen, Mapping) else None
    frozen_row = next(
        (
            row
            for row in rows or []
            if isinstance(row, Mapping) and row.get("row_id") == row_id
        ),
        None,
    )
    if (
        not isinstance(frozen_row, Mapping)
        or frozen_row.get("row_type") != "planned"
        or frozen_row.get("party") != party_size
        or frozen_row.get("arm") != metadata.get("arm")
        or frozen_row.get("script") != counterbalance.get("script")
    ):
        raise CharacterizationError("prepared_sandbox_row_binding_mismatch")
    script_path = _safe_project_file(
        Path("plans/v2-mapping-pilot-prereg") / str(frozen_row["script"]),
        "frozen_script",
    )
    script = _read_json(script_path, "frozen_script")
    if fixture_id not in script.get("fixture_ids", []):
        raise CharacterizationError("prepared_sandbox_script_fixture_mismatch")
    turns = script.get("turns")
    first_turn = turns[0] if isinstance(turns, list) and turns else None
    actor = first_turn.get("actor") if isinstance(first_turn, Mapping) else None
    character = actor.get("party_%d" % party_size) if isinstance(actor, Mapping) else None
    step_id = first_turn.get("id") if isinstance(first_turn, Mapping) else None
    utterance = first_turn.get("utterance") if isinstance(first_turn, Mapping) else None
    if (
        not isinstance(step_id, str)
        or not _SAFE_RUN_ID.fullmatch(step_id)
        or not isinstance(utterance, str)
        or not utterance.strip()
        or not isinstance(character, str)
        or character not in members
    ):
        raise CharacterizationError("prepared_sandbox_first_scripted_turn_invalid")
    if (
        counterbalance.get("fixed_seed") != metadata.get("effective_seed")
        or frozen_row.get("fixed_seed") != metadata.get("effective_seed")
    ):
        raise CharacterizationError("prepared_sandbox_seed_binding_mismatch")

    resume = lifecycle == "resume"
    try:
        launcher.validate_sandbox(
            sandbox,
            arm=str(metadata.get("arm")),
            fixture_id=fixture_id,
            party_size=party_size,
            resume=resume,
            resume_checkpoint_sha256=resume_checkpoint_sha256,
            project_root=PROJECT_ROOT,
        )
    except Exception as exc:
        raise CharacterizationError("prepared_sandbox_validation_failed") from exc
    return (
        sandbox,
        row_id,
        str(metadata["arm"]),
        profile["profile_id"],
        {
            "step_id": step_id,
            "utterance": utterance,
            "character": character,
        },
    )


def _require_synthetic_sandbox_config(config_path: Path) -> None:
    """Require exact synthetic config bytes before any characterization launch."""
    from scripts.live_gate_preflight_sandbox import _SYNTHETIC_CONFIG

    if config_path.is_symlink() or not config_path.is_file():
        raise CharacterizationError("prepared_sandbox_config_invalid")
    try:
        observed = config_path.read_bytes()
    except OSError as exc:
        raise CharacterizationError("prepared_sandbox_config_unavailable") from exc
    if observed != _SYNTHETIC_CONFIG.encode("ascii"):
        raise CharacterizationError("prepared_sandbox_config_identity_mismatch")


def _git_common_directory() -> Path:
    raw = _git_output(("rev-parse", "--git-common-dir"))
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise CharacterizationError("shared_live_window_lock_outside_repository") from exc
    if not resolved.is_dir() or path.is_symlink():
        raise CharacterizationError("shared_live_window_lock_unavailable")
    return resolved


def _append_lock_log(path: Path, record: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
        ):
            raise OSError("live_window_booking_log_invalid")
        os.fchmod(descriptor, 0o600)
        line = json.dumps(
            dict(record), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii") + b"\n"
        _write_all(descriptor, line)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            raise OSError("short_write")
        offset += written


class _ProfileCharacterizationLock:
    """Small, exclusive adapter for the shared git-common-dir live-window lock."""

    def __init__(self, common_directory: Path, holder_record: Mapping[str, Any]) -> None:
        self.coordination_directory = common_directory / "neq-coordination"
        self.lock_directory = self.coordination_directory / "live-window.lock"
        self.holder_record = dict(holder_record)
        booking_id = holder_record.get("booking_id")
        self.booking_id = booking_id if isinstance(booking_id, str) else ""
        self.acquired = False
        self.recorded = False
        self.lock_identity: tuple[int, int] | None = None
        self.holder_identity: tuple[int, int] | None = None

    def acquire(self) -> bool:
        if not _valid_live_window_lock_record(self.holder_record):
            return False
        if self.coordination_directory.is_symlink():
            return False
        try:
            self.coordination_directory.mkdir(mode=0o700, parents=False, exist_ok=True)
            coordination_metadata = self.coordination_directory.lstat()
            get_uid = getattr(os, "getuid", None)
            current_uid = get_uid() if callable(get_uid) else None
            if (
                not stat.S_ISDIR(coordination_metadata.st_mode)
                or (current_uid is not None and coordination_metadata.st_uid != current_uid)
                or (
                    os.name == "posix"
                    and stat.S_IMODE(coordination_metadata.st_mode) & 0o022
                )
            ):
                return False
            self.lock_directory.mkdir(mode=0o700, exist_ok=False)
            lock_metadata = self.lock_directory.lstat()
            if not stat.S_ISDIR(lock_metadata.st_mode):
                return False
            self.lock_identity = (lock_metadata.st_dev, lock_metadata.st_ino)
        except (FileExistsError, OSError):
            return False
        self.acquired = True
        holder_path = self.lock_directory / "holder.json"
        try:
            descriptor = os.open(
                holder_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                holder_metadata = os.fstat(descriptor)
                self.holder_identity = (holder_metadata.st_dev, holder_metadata.st_ino)
                raw = json.dumps(
                    self.holder_record,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii") + b"\n"
                _write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _append_lock_log(self.coordination_directory / "bookings.log", self.holder_record)
        except (OSError, TypeError, ValueError):
            self._remove_owned_holder()
            return False
        self.recorded = True
        return True

    def release(self, release_record: Mapping[str, Any]) -> bool:
        if not self.acquired or not self.recorded:
            return False
        holder_path = self.lock_directory / "holder.json"
        try:
            lock_metadata = self.lock_directory.lstat()
            if (
                not stat.S_ISDIR(lock_metadata.st_mode)
                or self.lock_identity != (lock_metadata.st_dev, lock_metadata.st_ino)
            ):
                return False
            metadata = holder_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or self.holder_identity != (metadata.st_dev, metadata.st_ino)
            ):
                return False
            holder = _read_json(holder_path, "live_window_holder")
            release_identity = (
                {key: release_record.get(key) for key in self.holder_record}
                if isinstance(release_record, Mapping)
                else None
            )
            if (
                not isinstance(holder, Mapping)
                or dict(holder) != self.holder_record
                or holder.get("booking_id") != self.booking_id
                or not _valid_live_window_lock_record(holder)
                or release_identity != self.holder_record
                or not _valid_lock_release_record(release_record, self.booking_id)
            ):
                return False
            _append_lock_log(self.coordination_directory / "bookings.log", release_record)
            holder_path.unlink()
            self.lock_directory.rmdir()
        except (OSError, CharacterizationError, ValueError):
            return False
        self.acquired = False
        self.recorded = False
        self.lock_identity = None
        self.holder_identity = None
        return True

    def _remove_owned_holder(self) -> None:
        if not self.acquired:
            return
        try:
            lock_metadata = self.lock_directory.lstat()
            if (
                not stat.S_ISDIR(lock_metadata.st_mode)
                or self.lock_identity != (lock_metadata.st_dev, lock_metadata.st_ino)
            ):
                return
            holder_path = self.lock_directory / "holder.json"
            holder_metadata = holder_path.lstat()
            if (
                stat.S_ISREG(holder_metadata.st_mode)
                and self.holder_identity == (holder_metadata.st_dev, holder_metadata.st_ino)
            ):
                holder_path.unlink()
            self.lock_directory.rmdir()
        except OSError:
            return
        self.acquired = False
        self.lock_identity = None
        self.holder_identity = None


def _port_state(port: int) -> tuple[bool, bool]:
    """Return (listener observed, observation complete) using loopback only."""
    listener = False
    for family, address in (
        (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::1", port, 0, 0)),
    ):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                result = probe.connect_ex(address)
        except OSError as exc:
            if exc.errno in (
                errno.EAFNOSUPPORT,
                errno.EPROTONOSUPPORT,
                getattr(errno, "EPFNOSUPPORT", -1),
            ):
                continue
            return listener, False
        if result == 0:
            listener = True
        elif result not in (
            errno.ECONNREFUSED,
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            errno.EAFNOSUPPORT,
            errno.EPROTONOSUPPORT,
        ):
            return listener, False
    return listener, True


def _port_is_free(port: int) -> bool:
    if type(port) is not int or port not in REQUIRED_PORTS:
        return False
    listener, socket_observed = _port_state(port)
    _listener_processes, process_observed = _listener_pids(port)
    return socket_observed and process_observed and not listener and not _listener_processes


def _required_port_status() -> dict[int, bool]:
    """Verify both ports reserved by the shared live-window lock."""
    return {port: _port_is_free(port) for port in REQUIRED_PORTS}


def _ports_are_free(status: Mapping[int, bool]) -> bool:
    return set(status) == set(REQUIRED_PORTS) and all(
        status.get(port) is True for port in REQUIRED_PORTS
    )


def _port_failure_code(status: Mapping[int, bool], phase: str) -> str | None:
    for port in REQUIRED_PORTS:
        if status.get(port) is not True:
            return "port_%d_not_free_%s" % (port, phase)
    return None


def _valid_evidence_path(value: Any) -> bool:
    if not isinstance(value, str) or "\\" in value:
        return False
    path = PurePosixPath(value)
    return bool(
        not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) >= 2
        and path.parts[0] == "tmp"
    )


def _valid_lock_release_record(value: Any, booking_id: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    release_time = _parse_utc_timestamp(value.get("released_at_utc"))
    start = _parse_utc_timestamp(value.get("window_start"))
    end = _parse_utc_timestamp(value.get("window_end"))
    ports_free = value.get("ports_free")
    return bool(
        value.get("event") == "released"
        and value.get("booking_id") == booking_id
        and release_time is not None
        and start is not None
        and end is not None
        and start <= release_time <= end
        and value.get("server_stopped") is True
        and value.get("after_teardown_socket_sample_observed") is True
        and value.get("after_teardown_socket_pids") == []
        and isinstance(ports_free, Mapping)
        and dict(ports_free) == {str(port): True for port in REQUIRED_PORTS}
        and _valid_evidence_path(value.get("evidence_path"))
    )


def _observer_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return b""


def _run_observer_command(
    command: Sequence[str],
    *,
    empty_result_is_success: bool = False,
    max_output_bytes: int = MAX_OBSERVER_OUTPUT_BYTES,
) -> tuple[dict[str, Any], bytes, bool]:
    """Run one bounded local observer and retain a bounded raw output prefix."""
    from scripts.live_gate_preflight_safety import run_guarded_subprocess

    stdout = b""
    stderr = b""
    returncode: int | None = None
    failure: str | None = None
    try:
        completed = run_guarded_subprocess(
            list(command),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            timeout=OBSERVER_TIMEOUT_SECONDS,
        )
        returncode = completed.returncode
        stdout = _observer_bytes(completed.stdout)
        stderr = _observer_bytes(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = _observer_bytes(exc.stdout)
        stderr = _observer_bytes(exc.stderr)
        failure = "timeout"
    except OSError as exc:
        failure = type(exc).__name__

    stdout_truncated = len(stdout) > max_output_bytes
    stderr_truncated = len(stderr) > MAX_OBSERVER_OUTPUT_BYTES
    stdout_prefix = stdout[:min(max_output_bytes, MAX_OBSERVER_OUTPUT_BYTES)]
    stderr_prefix = stderr[:MAX_OBSERVER_OUTPUT_BYTES]
    empty_success = (
        empty_result_is_success
        and returncode == 1
        and not stdout
        and not stderr
    )
    command_observed = bool(
        failure is None
        and (returncode == 0 or empty_success)
        and not stdout_truncated
        and not stderr_truncated
        and not stderr
    )
    evidence = {
        "command": list(command),
        "returncode": returncode,
        "failure": failure,
        "stdout_byte_count": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_truncated": stdout_truncated,
        "stdout_prefix_base64": base64.b64encode(stdout_prefix).decode("ascii"),
        "stderr_byte_count": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_truncated": stderr_truncated,
        "stderr_prefix_base64": base64.b64encode(stderr_prefix).decode("ascii"),
        "observed": command_observed,
    }
    return evidence, stdout, command_observed


def _parse_lsof_listener_pids(raw: bytes, *, port: int) -> tuple[set[int], bool]:
    """Parse only numeric lsof TCP LISTEN rows for the requested lock port."""
    if not isinstance(raw, bytes):
        return set(), False
    pids: set[int] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        header = line.split()
        if len(header) >= 2 and header[0:2] == [b"COMMAND", b"PID"]:
            continue
        fields = line.split(None, 8)
        if len(fields) != 9:
            return set(), False
        try:
            pid = int(fields[1].decode("ascii"))
            name = fields[8].decode("ascii")
        except (UnicodeError, ValueError):
            return set(), False
        if (
            pid <= 0
            or fields[4] not in (b"IPv4", b"IPv6")
            or fields[7] != b"TCP"
        ):
            return set(), False
        name_fields = name.split()
        if (
            len(name_fields) != 2
            or name_fields[1] != "(LISTEN)"
            or ":" not in name_fields[0]
        ):
            return set(), False
        _host, port_text = name_fields[0].rsplit(":", 1)
        if not _host or not port_text.isdecimal() or int(port_text) != port:
            return set(), False
        pids.add(pid)
    return pids, True


def _listener_pids(port: int) -> tuple[set[int], bool]:
    """Observe listeners on a reserved port across all local interfaces."""
    if type(port) is not int or port not in REQUIRED_PORTS:
        return set(), False
    command = [
        LSOF_EXECUTABLE,
        "-nP",
        "-iTCP:%d" % port,
        "-sTCP:LISTEN",
    ]
    _command_evidence, raw_output, command_observed = _run_observer_command(
        command, empty_result_is_success=True
    )
    if not command_observed:
        return set(), False
    pids, parseable = _parse_lsof_listener_pids(raw_output, port=port)
    return pids, parseable


def _parse_netstat_endpoint(value: bytes) -> dict[str, Any] | None:
    """Parse one numeric macOS netstat endpoint; the final dot separates port."""
    try:
        text = value.decode("ascii")
    except UnicodeError:
        return None
    if text == "*.*":
        return {"host": "*", "port": None}
    if text.startswith("*."):
        host = "*"
        raw_port = text[2:]
    elif "." in text:
        host, raw_port = text.rsplit(".", 1)
    else:
        return None
    if raw_port == "*" and host == "*":
        return {"host": "*", "port": None}
    if not raw_port.isdecimal():
        return None
    port = int(raw_port)
    if not 0 <= port <= 65535:
        return None
    if host != "*":
        address_host = host.split("%", 1)[0]
        try:
            address = ipaddress.ip_address(address_host)
        except ValueError:
            return None
        host = str(address)
    return {"host": host, "port": port}


def _parse_netstat_census(
    raw: bytes, *, run_pids: set[int]
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    """Filter process ownership before parsing or retaining any endpoint."""
    if not isinstance(raw, bytes) or len(raw) > MAX_NETSTAT_OUTPUT_BYTES:
        return [], {}, False
    rows: list[dict[str, Any]] = []
    counts = {
        "internet_rows": 0,
        "unattributed_rows": 0,
        "pid_zero_rows": 0,
        "foreign_process_rows": 0,
        "run_pid_rows": 0,
        "malformed_run_pid_rows": 0,
    }
    lines = raw.splitlines()
    if len(lines) > MAX_NETSTAT_ROWS:
        return [], counts, False
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        protocol = tokens[0].lower()
        if protocol not in (b"tcp", b"tcp4", b"tcp6", b"udp", b"udp4", b"udp6"):
            continue
        counts["internet_rows"] += 1

        # netstat's process name may contain spaces. Match its PID marker and
        # fixed-width trailing fields directly in bytes before touching tokens 3/4.
        owner_match = _NETSTAT_OWNER_PATTERN.search(line)
        owner_suffix_start = 6 if protocol.startswith(b"tcp") else 5
        owner_suffix = b" ".join(tokens[owner_suffix_start:])
        candidate_matches = list(_NETSTAT_OWNER_PID_CANDIDATE_PATTERN.finditer(owner_suffix))
        if not candidate_matches and protocol.startswith(b"tcp") and len(tokens) > 5:
            # A missing TCP state token is malformed, but its process suffix
            # still identifies an owned row that must fail closed.
            candidate_matches = list(
                _NETSTAT_OWNER_PID_CANDIDATE_PATTERN.finditer(b" ".join(tokens[5:]))
            )
        if owner_match is None:
            if not candidate_matches:
                counts["unattributed_rows"] += 1
                continue
            pid = int(candidate_matches[-1].group("pid"))
        else:
            pid = int(owner_match.group("pid"))
        if pid == 0:
            counts["pid_zero_rows"] += 1
            continue
        if pid not in run_pids:
            counts["foreign_process_rows"] += 1
            continue

        counts["run_pid_rows"] += 1
        if owner_match is None:
            counts["malformed_run_pid_rows"] += 1
            return [], counts, False
        is_tcp = protocol.startswith(b"tcp")
        if len(tokens) < (6 if is_tcp else 5):
            counts["malformed_run_pid_rows"] += 1
            return [], counts, False
        local_endpoint = _parse_netstat_endpoint(tokens[3])
        foreign_endpoint = _parse_netstat_endpoint(tokens[4])
        if local_endpoint is None or foreign_endpoint is None:
            counts["malformed_run_pid_rows"] += 1
            return [], counts, False
        state: str | None = None
        if is_tcp:
            try:
                state = tokens[5].decode("ascii")
            except UnicodeError:
                counts["malformed_run_pid_rows"] += 1
                return [], counts, False
            if not state or not state.isascii() or not state.replace("_", "").isalpha():
                counts["malformed_run_pid_rows"] += 1
                return [], counts, False
        rows.append(
            {
                "pid": pid,
                "protocol": protocol.decode("ascii"),
                "local": local_endpoint,
                "foreign": foreign_endpoint,
                "state": state,
            }
        )
    return rows, counts, True


def _non_loopback_endpoint(endpoint: Mapping[str, Any]) -> bool:
    host = endpoint.get("host")
    if not isinstance(host, str) or host == "*":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not address.is_loopback


def _foreign_endpoint_recorded(
    pid: int,
    endpoint: Mapping[str, Any],
    guard_events: Sequence[Mapping[str, Any]],
) -> bool:
    host = endpoint.get("host")
    port = endpoint.get("port")
    if not isinstance(host, str) or type(port) is not int:
        return False
    return any(
        event.get("event_type") == "network_attempt"
        and event.get("pid") == pid
        and event.get("target_host") == host
        and event.get("target_port") == port
        for event in guard_events
    )


def _discard_observer_output(evidence: dict[str, Any]) -> None:
    """Keep aggregate hashes but never persist raw socket or error output."""
    evidence["stdout_prefix_base64"] = ""
    evidence["stderr_prefix_base64"] = ""


def _make_process_scope(
    *,
    selector: str,
    pid: int,
    process_group_id: int,
    process_role: str,
    launch_source: str,
    command: Sequence[str],
    environment_sha256: str,
    working_directory: str | Path,
) -> dict[str, Any]:
    """Build a scope from an independently verified launch or startup identity."""
    command_sha256 = hashlib.sha256(
        json.dumps(list(command), ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()
    working_directory_sha256 = hashlib.sha256(
        str(working_directory).encode("utf-8")
    ).hexdigest()
    scope = {
        "selector": selector,
        "pid": pid,
        "process_group_id": process_group_id,
        "process_role": process_role,
        "launch_source": launch_source,
        "command_sha256": command_sha256,
        "environment_sha256": environment_sha256,
        "working_directory_sha256": working_directory_sha256,
    }
    if not _valid_process_scope(scope):
        raise CharacterizationError("process_scope_identity_invalid")
    return scope


def _valid_process_scope(scope: Any) -> bool:
    if not isinstance(scope, Mapping) or set(scope) != {
        "selector",
        "pid",
        "process_group_id",
        "process_role",
        "launch_source",
        "command_sha256",
        "environment_sha256",
        "working_directory_sha256",
    }:
        return False
    selector = scope.get("selector")
    pid = scope.get("pid")
    process_group_id = scope.get("process_group_id")
    process_role = scope.get("process_role")
    launch_source = scope.get("launch_source")
    return bool(
        selector in ("pid", "process_group")
        and type(pid) is int
        and pid > 0
        and type(process_group_id) is int
        and process_group_id > 0
        and process_role in ("parent", "host")
        and isinstance(launch_source, str)
        and (
            (
                selector == "pid"
                and process_role == "parent"
                and launch_source == "controller-startup-canary"
            )
            or (
                selector == "process_group"
                and process_role == "host"
                and pid == process_group_id
                and launch_source
                in (
                    "host-prelaunch-canary-session",
                    "host-worker-start-new-session",
                )
            )
        )
        and all(
            isinstance(scope.get(name), str)
            and _SHA256.fullmatch(scope[name]) is not None
            for name in (
                "command_sha256",
                "environment_sha256",
                "working_directory_sha256",
            )
        )
    )


def _write_socket_sample_evidence(
    run_directory: Path, phase: str, evidence: Mapping[str, Any]
) -> None:
    if phase not in ("before_host", "host_ready", "after_teardown"):
        raise CharacterizationError("socket_sample_phase_invalid")
    if run_directory.is_symlink():
        raise CharacterizationError("socket_sample_evidence_path_invalid")
    try:
        resolved_directory = run_directory.resolve(strict=True)
        resolved_directory.relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise CharacterizationError("socket_sample_evidence_path_invalid") from exc
    if not resolved_directory.is_dir():
        raise CharacterizationError("socket_sample_evidence_path_invalid")
    evidence_path = resolved_directory / ("socket-sample-%s.json" % phase)
    if evidence_path.exists() or evidence_path.is_symlink():
        raise CharacterizationError("socket_sample_evidence_already_exists")
    _write_json(evidence_path, evidence)


def _socket_pid_sample(
    phase: str,
    *,
    run_directory: Path,
    process_scopes: Sequence[Mapping[str, Any]],
    guard_events: Sequence[Mapping[str, Any]] | None = None,
    guard_events_complete: bool = True,
) -> dict[str, Any]:
    """Census netstat rows after PID filtering, retaining only run-owned rows."""
    from scripts.live_gate_preflight_safety import validate_guard_event_records

    if phase not in ("before_host", "host_ready", "after_teardown"):
        raise CharacterizationError("socket_sample_phase_invalid")
    run_id = run_directory.name
    evidence: dict[str, Any] = {
        "schema_version": 3,
        "run_id": run_id,
        "phase": phase,
        "observer": "netstat -anv -W -p tcp and udp; PID filter precedes endpoint parsing",
        "process_scopes": [],
        "run_process_pids": [],
        "guard_startup_pids": [],
        "protocol_samples": [],
        "aggregate_counts": {
            "internet_rows": 0,
            "unattributed_rows": 0,
            "pid_zero_rows": 0,
            "foreign_process_rows": 0,
            "run_pid_rows": 0,
            "malformed_run_pid_rows": 0,
        },
        "run_owned_rows": [],
        "pids": [],
        "observed": False,
        "failure_code": None,
    }
    scopes = list(process_scopes)
    events = list(guard_events or [])
    if not scopes:
        evidence["failure_code"] = "process_scope_identity_missing"
    elif any(not _valid_process_scope(scope) for scope in scopes):
        evidence["failure_code"] = "process_scope_identity_invalid"
    else:
        evidence["process_scopes"] = [dict(scope) for scope in scopes]
    if (
        not events
        or not guard_events_complete
        or not validate_guard_event_records(events, expected_run_id=run_id)
    ):
        evidence["failure_code"] = "guard_event_evidence_incomplete"

    launch_pids = {
        int(scope["pid"])
        for scope in scopes
        if _valid_process_scope(scope)
    }
    event_pids = {
        int(event["pid"])
        for event in events
        if type(event.get("pid")) is int and event.get("pid") > 0
    }
    child_process_pids = {
        int(event["child_pid"])
        for event in events
        if event.get("event_type") == "subprocess_started"
        and type(event.get("child_pid")) is int
        and event.get("child_pid") > 0
    }
    run_pids = launch_pids | event_pids | child_process_pids
    startup_pids = {
        int(event["pid"])
        for event in events
        if event.get("event_type") == "guard_startup"
        and type(event.get("pid")) is int
    }
    evidence["run_process_pids"] = sorted(run_pids)
    evidence["guard_startup_pids"] = sorted(startup_pids)

    rows: list[dict[str, Any]] = []
    observed = bool(scopes) and evidence["failure_code"] is None
    commands = (
        ("tcp", [NETSTAT_EXECUTABLE, "-anv", "-W", "-p", "tcp"]),
        ("udp", [NETSTAT_EXECUTABLE, "-anv", "-W", "-p", "udp"]),
    )
    if observed:
        for protocol, command in commands:
            command_evidence, raw_output, command_observed = _run_observer_command(
                command, max_output_bytes=MAX_NETSTAT_OUTPUT_BYTES
            )
            _discard_observer_output(command_evidence)
            parsed_rows, counts, parseable = _parse_netstat_census(
                raw_output, run_pids=run_pids
            )
            evidence["protocol_samples"].append(
                {
                    "protocol": protocol,
                    "command_evidence": command_evidence,
                    "counts": counts,
                    "parseable": parseable,
                }
            )
            for key, count in counts.items():
                evidence["aggregate_counts"][key] += count
            if not command_observed:
                observed = False
                evidence["failure_code"] = "netstat_observation_incomplete"
                break
            if not parseable:
                observed = False
                evidence["failure_code"] = "netstat_run_pid_row_malformed"
                break
            rows.extend(parsed_rows)

    owners = {int(row["pid"]) for row in rows}
    evidence["run_owned_rows"] = rows
    evidence["pids"] = sorted(owners)
    missing_startup_pids = owners - startup_pids
    if missing_startup_pids:
        observed = False
        evidence["failure_code"] = "socket_owner_missing_guard_startup_event"
    for row in rows:
        foreign = row["foreign"]
        if _non_loopback_endpoint(foreign) and not _foreign_endpoint_recorded(
            int(row["pid"]), foreign, events
        ):
            observed = False
            evidence["failure_code"] = "unguarded_non_loopback_socket"
            break
    evidence["observed"] = observed
    if observed:
        evidence["failure_code"] = None
    try:
        _write_socket_sample_evidence(run_directory, phase, evidence)
    except (CharacterizationError, OSError):
        observed = False
        evidence["observed"] = False
        evidence["failure_code"] = "socket_sample_evidence_write_failed"
    return {
        "phase": phase,
        "port": HOST_PORT,
        "observed": observed,
        "pids": sorted(owners),
        "failure_code": evidence["failure_code"],
    }


def _make_process_census(
    *,
    process_canaries: Sequence[Mapping[str, Any]],
    process: subprocess.Popen[bytes] | None,
    driver_exchange: Mapping[str, Any] | None,
    socket_pid_samples: Sequence[Mapping[str, Any]],
    process_scopes: Sequence[Mapping[str, Any]],
    guard_events: Sequence[Mapping[str, Any]],
    expected_run_id: str,
) -> dict[str, Any]:
    from scripts.live_gate_preflight_safety import validate_guard_event_records

    reports = {
        report.get("canary_stage"): report
        for report in process_canaries
        if isinstance(report, Mapping)
    }
    controller = reports.get("controller-startup")
    host_prelaunch = reports.get("host-prelaunch")
    host_startup = reports.get("host-startup")
    controller_pid = controller.get("pid") if isinstance(controller, Mapping) else None
    driver_pid = (
        driver_exchange.get("process_pid")
        if isinstance(driver_exchange, Mapping)
        else None
    )
    host_prelaunch_pid = (
        host_prelaunch.get("pid") if isinstance(host_prelaunch, Mapping) else None
    )
    host_worker_pid = process.pid if process is not None else None

    expected_scopes = {
        "controller-startup-canary": (
            "pid",
            controller_pid,
            "parent",
        ),
        "host-prelaunch-canary-session": (
            "process_group",
            host_prelaunch_pid,
            "host",
        ),
        "host-worker-start-new-session": (
            "process_group",
            host_worker_pid,
            "host",
        ),
    }
    scopes_by_source = {
        scope.get("launch_source"): scope
        for scope in process_scopes
        if _valid_process_scope(scope)
    }
    launch_scopes_complete = (
        len(process_scopes) == len(expected_scopes)
        and set(scopes_by_source) == set(expected_scopes)
        and all(
            scopes_by_source[source].get("selector") == expected[0]
            and scopes_by_source[source].get("pid") == expected[1]
            and scopes_by_source[source].get("process_role") == expected[2]
            and (
                expected[0] != "process_group"
                or scopes_by_source[source].get("process_group_id") == expected[1]
            )
            for source, expected in expected_scopes.items()
        )
    )

    launched_pids = {
        pid
        for pid in (controller_pid, host_prelaunch_pid, host_worker_pid)
        if type(pid) is int and pid > 0
    }
    canary_pids = {
        report.get("pid")
        for report in process_canaries
        if type(report.get("pid")) is int and report.get("pid") > 0
    }
    guarded_pids = {
        int(event["pid"])
        for event in guard_events
        if event.get("event_type") == "guard_startup"
        and type(event.get("pid")) is int
        and event.get("pid") > 0
    }
    child_python_pids = {
        int(event["child_pid"])
        for event in guard_events
        if event.get("event_type") == "subprocess_started"
        and event.get("child_is_python") is True
        and type(event.get("child_pid")) is int
        and event.get("child_pid") > 0
    }
    socket_owner_pids = {
        pid
        for sample in socket_pid_samples
        for pid in sample.get("pids", [])
        if type(pid) is int and pid > 0
    }
    python_pids = launched_pids | child_python_pids | socket_owner_pids | guarded_pids
    uncovered_pids = python_pids - guarded_pids
    guard_events_valid = validate_guard_event_records(
        list(guard_events), expected_run_id=expected_run_id
    )
    expected_phases = ("before_host", "host_ready", "after_teardown")
    samples_complete = (
        len(socket_pid_samples) == len(expected_phases)
        and all(
            sample.get("phase") == phase
            and sample.get("port") == HOST_PORT
            and sample.get("observed") is True
            and isinstance(sample.get("pids"), list)
            and all(type(pid) is int and pid > 0 for pid in sample["pids"])
            for sample, phase in zip(socket_pid_samples, expected_phases)
        )
    )
    sample_pids = {
        sample.get("phase"): set(sample.get("pids", []))
        for sample in socket_pid_samples
        if isinstance(sample, Mapping)
    }
    startup_records_complete = (
        isinstance(controller, Mapping)
        and isinstance(host_prelaunch, Mapping)
        and isinstance(host_startup, Mapping)
        and host_worker_pid is not None
        and host_startup.get("pid") == host_worker_pid
        and driver_pid == controller_pid
    )
    socket_ownership_complete = (
        sample_pids.get("before_host") == set()
        and bool(host_worker_pid)
        and host_worker_pid in sample_pids.get("host_ready", set())
        and sample_pids.get("after_teardown") == set()
    )
    return {
        "controller_pid": controller_pid,
        "driver_pid": driver_pid,
        "host_prelaunch_pid": host_prelaunch_pid,
        "host_worker_pid": host_worker_pid,
        "launched_pids": sorted(launched_pids),
        "socket_owner_pids": sorted(socket_owner_pids),
        "python_child_pids": sorted(child_python_pids),
        "python_pids": sorted(python_pids),
        "guarded_pids": sorted(guarded_pids),
        "canary_pids": sorted(canary_pids),
        "uncovered_pids": sorted(uncovered_pids),
        "guard_events_valid": guard_events_valid,
        "socket_pid_samples": [dict(sample) for sample in socket_pid_samples],
        "complete": bool(
            startup_records_complete
            and launch_scopes_complete
            and samples_complete
            and socket_ownership_complete
            and guard_events_valid
            and canary_pids.issubset(guarded_pids)
            and not uncovered_pids
        ),
    }


def _wait_until_ready(process: subprocess.Popen[bytes], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        listener, observed = _port_state(HOST_PORT)
        if not observed:
            return False
        if listener:
            return True
        time.sleep(0.1)
    return False


def _stop_owned_process(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return True
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGINT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=STOP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=5.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if process.poll() is None:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                return False
    return process.poll() is not None


def _host_command(
    *,
    fixture_id: str,
    party_size: int,
    lifecycle: str,
    source_sha: str,
    run_id: str,
    planned_row_id: str,
    arm: str,
    lifecycle_id: str,
    resume_checkpoint_sha256: str | None,
) -> list[str]:
    command = [
        _repository_python(),
        "-P",
        "-m",
        "scripts.live_gate_preflight_profile_runner",
        "--worker",
        "--fixture-id",
        fixture_id,
        "--party-size",
        str(party_size),
        "--lifecycle",
        lifecycle,
        "--source-sha",
        source_sha,
        "--run-id",
        run_id,
        "--planned-row-id",
        planned_row_id,
        "--arm",
        arm,
        "--lifecycle-id",
        lifecycle_id,
    ]
    if resume_checkpoint_sha256 is not None:
        command.extend(("--resume-checkpoint-sha256", resume_checkpoint_sha256))
    return command


def _make_profile_driver(
    *, party_size: int, transcript_path: Path, runtime_root: Path
) -> Any:
    from scripts.mapping_pilot.row_runner import SocketScriptDriver

    return SocketScriptDriver(
        party_size=party_size,
        transcript_path=transcript_path,
        runtime_root=str(runtime_root),
    )


def _drive_profile_exchange(
    *,
    party_size: int,
    runtime_root: Path,
    transcript_path: Path,
    first_turn: Mapping[str, str],
    driver_factory: Any = None,
) -> dict[str, Any]:
    """Start the real capture driver and require one completed scripted exchange."""
    _require_parent_startup_guard()
    factory = driver_factory or _make_profile_driver
    driver: Any = None
    start_ready = False
    character_set = False
    turn_completed = False
    turn_timed_out = False
    game_output_count = 0
    failure_code: str | None = None
    try:
        driver = factory(
            party_size=party_size,
            transcript_path=transcript_path,
            runtime_root=runtime_root,
        )
        readiness = driver.start()
        start_ready = isinstance(readiness, Mapping) and readiness.get("ready") is True
        if not start_ready:
            failure_code = "capture_driver_start_not_ready"
        else:
            character = first_turn.get("character")
            if not isinstance(character, str) or not character.strip():
                failure_code = "capture_driver_character_invalid"
            else:
                character_set = driver.set_active_character(character) is True
                if not character_set:
                    failure_code = "capture_driver_character_selection_failed"
                else:
                    turn = driver.send_turn(
                        first_turn["step_id"],
                        first_turn["utterance"],
                        character,
                    )
                    if not isinstance(turn, Mapping):
                        failure_code = "capture_driver_exchange_result_invalid"
                    else:
                        turn_completed = turn.get("completed") is True
                        turn_timed_out = turn.get("timed_out") is True
                        output_count = turn.get("game_output_count")
                        if type(output_count) is int and output_count >= 0:
                            game_output_count = output_count
                        if not turn_completed or turn_timed_out or game_output_count < 1:
                            failure_code = "capture_driver_first_exchange_incomplete"
    except Exception as exc:
        failure_code = "capture_driver_failed_" + type(exc).__name__
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception as exc:
                failure_code = failure_code or "capture_driver_teardown_failed_" + type(exc).__name__

    return {
        "status": "completed" if failure_code is None else "failed",
        "process_pid": os.getpid(),
        "step_id": first_turn.get("step_id"),
        "start_ready": start_ready,
        "active_character_set": character_set,
        "turn_completed": turn_completed,
        "turn_timed_out": turn_timed_out,
        "game_output_count": game_output_count,
        "failure_code": failure_code,
    }


def _repository_python() -> str:
    python_path = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python_path.exists() or not python_path.is_file():
        raise CharacterizationError("repository_venv_missing")
    return str(python_path)


def _make_evidence_sites(calls: list[Any]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, int, str], int] = {}
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        source_file = call.get("source_file")
        source_line = call.get("source_line")
        source_hash = call.get("source_file_sha256")
        if (
            isinstance(source_file, str)
            and type(source_line) is int
            and isinstance(source_hash, str)
            and _SHA256.fullmatch(source_hash)
        ):
            key = (source_file, source_line, source_hash)
            counts[key] = counts.get(key, 0) + 1
    return [
        {
            "source_file": source_file,
            "source_line": source_line,
            "source_file_sha256": source_hash,
            "count": count,
        }
        for (source_file, source_line, source_hash), count in sorted(counts.items())
    ]


def _worker_result_path(run_id: str) -> Path:
    return PROJECT_ROOT / PROFILE_EVIDENCE_ROOT / run_id / "worker-result.json"


def _ensure_run_directory(run_id: str) -> Path:
    tmp_root = PROJECT_ROOT / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise CharacterizationError("project_tmp_unavailable")
    relative = PROFILE_EVIDENCE_ROOT / run_id
    cursor = PROJECT_ROOT
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CharacterizationError("profile_evidence_path_invalid")
    directory = PROJECT_ROOT / relative
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CharacterizationError("run_id_already_exists") from exc
    except OSError as exc:
        raise CharacterizationError("profile_evidence_directory_unavailable") from exc
    return directory


def _read_guard_events_for_run(
    run_directory: Path, run_id: str
) -> tuple[list[dict[str, Any]], bytes, bool]:
    from scripts.live_gate_preflight_safety import (
        SafetyConfigurationError,
        read_guard_event_journal,
    )

    try:
        events, raw = read_guard_event_journal(
            run_directory / "guard-events.jsonl", run_id=run_id
        )
    except SafetyConfigurationError:
        return [], b"", False
    return events, raw, True


def _claim_characterization_attempt(
    evidence_root: Path,
    run_directory: Path,
    attempt_record: Mapping[str, Any],
) -> None:
    """Allow at most one measured attempt per fixture-party lifecycle pair."""
    requested_profile = attempt_record.get("profile_id")
    requested_lifecycle = attempt_record.get("lifecycle")
    attempts = 0
    try:
        children = list(evidence_root.iterdir())
    except OSError as exc:
        raise CharacterizationError("profile_attempt_history_unavailable") from exc
    for child in children:
        if child.is_symlink():
            raise CharacterizationError("profile_attempt_history_unsafe")
        if not child.is_dir():
            continue
        marker = child / "attempt.json"
        if not marker.exists():
            continue
        if marker.is_symlink() or not marker.is_file():
            raise CharacterizationError("profile_attempt_history_unsafe")
        prior = _read_json(marker, "profile_attempt")
        if not isinstance(prior, Mapping):
            raise CharacterizationError("profile_attempt_history_invalid")
        attempts += 1
        if (
            prior.get("profile_id") == requested_profile
            and prior.get("lifecycle") == requested_lifecycle
        ):
            raise CharacterizationError("profile_lifecycle_already_attempted")
    if attempts >= MAX_CHARACTERIZATION_ATTEMPTS:
        raise CharacterizationError("profile_characterization_attempt_limit_reached")
    if run_directory.parent.resolve(strict=True) != evidence_root.resolve(strict=True):
        raise CharacterizationError("profile_attempt_directory_invalid")
    marker_path = run_directory / "attempt.json"
    if marker_path.exists() or marker_path.is_symlink():
        raise CharacterizationError("profile_attempt_marker_already_exists")
    _write_json(marker_path, attempt_record)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    from utils.file_operations import safe_write_json

    if not safe_write_json(
        str(path),
        dict(value),
        create_backup=False,
        acquire_lock=True,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    ):
        raise CharacterizationError("profile_evidence_write_failed")


def _read_worker_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = _read_json(path, "worker_result")
    return dict(value) if isinstance(value, Mapping) else None


def _characterize(args: argparse.Namespace) -> tuple[dict[str, Any], str, str]:
    previous_sys_path = list(sys.path)
    root = _require_safe_project_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    config_guard: _SandboxConfigOriginGuard | None = None
    process_canaries: list[dict[str, Any]] = []
    process_scopes: list[dict[str, Any]] = []
    controller_startup: dict[str, Any] = {}
    guarded_environment: dict[str, str] = {}
    run_directory: Path | None = None
    runner_command: list[str] = []
    command: list[str] = []
    try:
        _require_parent_startup_guard()
        if args.run_id is None:
            args.run_id = "pf-" + uuid.uuid4().hex[:24]
        if not isinstance(args.run_id, str) or _SAFE_RUN_ID.fullmatch(args.run_id) is None:
            raise CharacterizationError("run_id_invalid")
        sandbox = root / SANDBOX_RELATIVE
        _configure_sandbox_import_paths(root, sandbox)
        config_guard = _install_sandbox_config_guard(sandbox)
        _verify_source_identity(args.source_sha)
        sandbox, planned_row_id, arm, profile_id, first_turn = _validate_prepared_sandbox(
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
        )
        run_directory = _ensure_run_directory(args.run_id)
        guard_events_path = run_directory / "guard-events.jsonl"
        from scripts.live_gate_preflight_safety import configure_guard_event_sink

        configure_guard_event_sink(guard_events_path, run_id=args.run_id)
        lifecycle_id = args.run_id + ("_s" if args.lifecycle == "startup" else "_r")
        command = _host_command(
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            source_sha=args.source_sha,
            run_id=args.run_id,
            planned_row_id=planned_row_id,
            arm=arm,
            lifecycle_id=lifecycle_id,
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
        )
        from scripts.live_gate_preflight_safety import (
            CANARY_REPORT_ENV,
            _startup_canary_environment_digest,
            _startup_environment_digest,
            _startup_environment_snapshot,
            build_guarded_sandbox_environment,
            current_invocation_command,
            run_startup_process_canary,
        )

        actual_runner_command = current_invocation_command()
        from scripts.live_gate_preflight_stub import _redact_command

        runner_command = _redact_command(actual_runner_command)
        if runner_command != actual_runner_command:
            raise CharacterizationError("runner_command_contains_sensitive_argument")

        guarded_environment = build_guarded_sandbox_environment(
            SANDBOX_RELATIVE,
            project_root=root,
            source_environment=os.environ,
            process_role="host",
            run_id=args.run_id,
            guard_events_path=guard_events_path,
        )
        host_environment_sha256 = _startup_canary_environment_digest(
            guarded_environment
        )
        expected_pythonpath = os.pathsep.join(
            (
                str(root / "scripts" / "live_gate_preflight_guard"),
                str(root),
            )
        )
        if guarded_environment.get("PYTHONPATH") != expected_pythonpath:
            raise CharacterizationError("pythonpath_identity_invalid")
        try:
            controller_report = json.loads(os.environ[CANARY_REPORT_ENV])
        except (KeyError, json.JSONDecodeError) as exc:
            raise CharacterizationError("startup_canary_report_invalid") from exc
        controller_startup = _validate_startup_canary_record(
            controller_report,
            process_role="parent",
            command=runner_command,
            cwd=Path.cwd(),
            environment_sha256=_startup_environment_digest(
                _startup_environment_snapshot()
            ),
            expected_pid=os.getpid(),
        )
        try:
            host_prelaunch = run_startup_process_canary(
                command=command,
                cwd=sandbox,
                env=guarded_environment,
            )
        except Exception as exc:
            raise CharacterizationError("host_prelaunch_canary_failed") from exc
        host_prelaunch = _validate_startup_canary_record(
            host_prelaunch,
            process_role="host",
            command=command,
            cwd=sandbox,
            environment_sha256=host_environment_sha256,
        )
        process_canaries = [
            {"canary_stage": "controller-startup", **controller_startup},
            {"canary_stage": "host-prelaunch", **host_prelaunch},
        ]
        process_scopes = [
            _make_process_scope(
                selector="pid",
                pid=os.getpid(),
                process_group_id=os.getpgrp(),
                process_role="parent",
                launch_source="controller-startup-canary",
                command=controller_startup["command"],
                environment_sha256=controller_startup["environment_sha256"],
                working_directory=controller_startup["working_directory"],
            ),
            _make_process_scope(
                selector="process_group",
                pid=host_prelaunch["pid"],
                process_group_id=host_prelaunch["pid"],
                process_role="host",
                launch_source="host-prelaunch-canary-session",
                command=host_prelaunch["command"],
                environment_sha256=host_prelaunch["environment_sha256"],
                working_directory=host_prelaunch["working_directory"],
            ),
        ]

        common_directory = _git_common_directory()
        lock_record = _build_live_window_lock_record(
            run_id=args.run_id,
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            planned_row_id=planned_row_id,
            source_sha=args.source_sha,
        )
        lock = _ProfileCharacterizationLock(common_directory, lock_record)
        if not lock.acquire():
            raise CharacterizationError("shared_live_window_lock_unavailable")
    except BaseException:
        _remove_import_guard(config_guard)
        sys.path[:] = previous_sys_path
        raise

    process: subprocess.Popen[bytes] | None = None
    server_stopped = True
    port_free = False
    port_status = {port: False for port in REQUIRED_PORTS}
    lock_released = False
    ready = False
    driver_exchange: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    failure_code: str | None = None
    evidence: dict[str, Any] | None = None
    guard_events: list[dict[str, Any]] = []
    guard_events_raw = b""
    guard_events_complete = False
    host_startup: dict[str, Any] | None = None
    socket_pid_samples: list[dict[str, Any]] = []
    process_census: dict[str, Any] | None = None
    try:
        if run_directory is None:
            raise CharacterizationError("profile_evidence_directory_unavailable")
        guard_events, _journal_bytes, journal_complete = _read_guard_events_for_run(
            run_directory, args.run_id
        )
        pre_host_sample = _socket_pid_sample(
            "before_host",
            run_directory=run_directory,
            process_scopes=process_scopes,
            guard_events=guard_events,
            guard_events_complete=journal_complete,
        )
        socket_pid_samples.append(pre_host_sample)
        port_status = _required_port_status()
        before_start_failure = _port_failure_code(port_status, "before_start")
        if before_start_failure is not None:
            raise CharacterizationError(before_start_failure)
        if not pre_host_sample["observed"] or pre_host_sample["pids"]:
            raise CharacterizationError("process_census_before_host_invalid")
        from scripts.live_gate_preflight_safety import (
            authorize_subprocess_launch,
        )
        if any(
            report.get("guard_active") is not True
            or report.get("non_loopback_connect_denied") is not True
            or report.get("subprocess_launch_denied") is not True
            for report in process_canaries
        ):
            raise CharacterizationError("startup_canary_failed_closed")
        _claim_characterization_attempt(
            run_directory.parent,
            run_directory,
            {
                "schema_version": 1,
                "run_id": args.run_id,
                "profile_id": profile_id,
                "fixture_id": args.fixture_id,
                "party_size": args.party_size,
                "lifecycle": args.lifecycle,
                "planned_row_id": planned_row_id,
                "source_sha": args.source_sha,
                "attempted_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        if os.name != "posix":
            raise CharacterizationError("process_group_identity_unavailable")
        with authorize_subprocess_launch(
            command, cwd=sandbox, env=guarded_environment
        ):
            process = subprocess.Popen(
                command,
                cwd=sandbox,
                env=guarded_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        process_scopes.append(
            _make_process_scope(
                selector="process_group",
                pid=process.pid,
                process_group_id=process.pid,
                process_role="host",
                launch_source="host-worker-start-new-session",
                command=command,
                environment_sha256=host_environment_sha256,
                working_directory=sandbox,
            )
        )
        ready = _wait_until_ready(process, STARTUP_TIMEOUT_SECONDS)
        guard_events, _journal_bytes, guard_events_complete = _read_guard_events_for_run(
            run_directory, args.run_id
        )
        ready_sample = _socket_pid_sample(
            "host_ready",
            run_directory=run_directory,
            process_scopes=process_scopes,
            guard_events=guard_events,
            guard_events_complete=guard_events_complete,
        )
        socket_pid_samples.append(ready_sample)
        if not ready_sample["observed"] or (
            ready and ready_sample["pids"] != [process.pid]
        ):
            failure_code = "process_census_host_owner_invalid"
        if not ready:
            failure_code = failure_code or "host_startup_not_ready"
        else:
            driver_exchange = _drive_profile_exchange(
                party_size=args.party_size,
                runtime_root=sandbox,
                transcript_path=run_directory / "driver-transcript.txt",
                first_turn=first_turn,
            )
            if driver_exchange.get("status") != "completed":
                failure_code = str(
                    driver_exchange.get("failure_code")
                    or "capture_driver_first_exchange_incomplete"
                )
        if not _stop_owned_process(process):
            server_stopped = False
            failure_code = failure_code or "host_server_stop_failed"
        else:
            server_stopped = process.poll() is not None
        port_status = _required_port_status()
        port_free = _ports_are_free(port_status)
        if not port_free:
            failure_code = failure_code or _port_failure_code(
                port_status, "after_stop"
            )
        result = _read_worker_result(_worker_result_path(args.run_id))
        if result is None:
            failure_code = failure_code or "host_worker_result_missing"
        elif (
            result.get("run_id") != args.run_id
            or result.get("source_sha") != args.source_sha
            or result.get("command") != command
            or result.get("pythonpath") != expected_pythonpath
        ):
            failure_code = failure_code or "host_worker_identity_mismatch"
        elif result.get("interpreter") != _interpreter_identity():
            failure_code = failure_code or "host_interpreter_identity_mismatch"
        elif result.get("guard_active") is not True:
            failure_code = failure_code or "host_network_guard_inactive"
        elif result.get("startup_guard_from_sitecustomize") is not True:
            failure_code = failure_code or "host_startup_guard_not_initialized"
        elif result.get("sandbox_config_origin_guard_active") is not True:
            failure_code = failure_code or "sandbox_config_origin_guard_inactive"
        elif result.get("provider_keys_blank") is not True:
            failure_code = failure_code or "provider_keys_not_blank"
        elif result.get("proxy_values_blank") is not True:
            failure_code = failure_code or "proxy_values_not_blank"
        elif result.get("real_project_config_loaded") is not False:
            failure_code = failure_code or "real_project_config_loaded"
        elif result.get("sandbox_config_loaded") is not True:
            failure_code = failure_code or "sandbox_config_identity_invalid"
        elif result.get("outcome") != "completed":
            failure_code = failure_code or str(result.get("failure_code") or "host_lifecycle_failed")
        elif type(result.get("call_count")) is not int or not isinstance(
            result.get("calls"), list
        ) or result.get("call_count") != len(result["calls"]):
            failure_code = failure_code or "router_call_log_incomplete"
        elif result.get("call_count") < 1:
            failure_code = failure_code or "router_call_missing"
        elif result.get("stub_failure_code") is not None:
            failure_code = failure_code or "router_stub_rejected_call"
        elif driver_exchange is None or driver_exchange.get("status") != "completed":
            failure_code = failure_code or "capture_driver_first_exchange_incomplete"
        if isinstance(result, Mapping):
            try:
                worker_canary = json.loads(result.get("startup_canary_report", ""))
            except (TypeError, json.JSONDecodeError):
                worker_canary = None
            if process is None or not isinstance(worker_canary, Mapping):
                failure_code = failure_code or "host_startup_canary_report_invalid"
            else:
                try:
                    host_startup = _validate_startup_canary_record(
                        worker_canary,
                        process_role="host",
                        command=command,
                        cwd=sandbox,
                        environment_sha256=host_environment_sha256,
                        expected_pid=process.pid,
                    )
                except CharacterizationError:
                    failure_code = failure_code or "host_startup_canary_report_invalid"
                else:
                    if (
                        host_startup.get("interpreter") != result.get("interpreter")
                        or host_startup.get("environment_sha256")
                        != host_environment_sha256
                    ):
                        failure_code = failure_code or "host_startup_canary_report_invalid"
                    else:
                        process_canaries.append(
                            {"canary_stage": "host-startup", **host_startup}
                        )
        if not ready:
            failure_code = failure_code or "host_startup_not_ready"
    except CharacterizationError as exc:
        failure_code = failure_code or exc.code
    except Exception as exc:
        failure_code = failure_code or "characterization_failed_" + type(exc).__name__
    finally:
        if process is not None and process.poll() is None:
            if not _stop_owned_process(process):
                server_stopped = False
                failure_code = failure_code or "host_server_stop_failed"
            else:
                server_stopped = process.poll() is not None
        port_status = _required_port_status()
        port_free = _ports_are_free(port_status)
        if not port_free:
            failure_code = failure_code or _port_failure_code(
                port_status, "after_teardown"
            )
        if run_directory is None:
            failure_code = failure_code or "socket_sample_evidence_directory_unavailable"
        else:
            guard_events, _journal_bytes, journal_complete = _read_guard_events_for_run(
                run_directory, args.run_id
            )
            socket_pid_samples.append(
                _socket_pid_sample(
                    "after_teardown",
                    run_directory=run_directory,
                    process_scopes=process_scopes,
                    guard_events=guard_events,
                    guard_events_complete=journal_complete,
                )
            )
        after_teardown_sample = (
            socket_pid_samples[-1]
            if socket_pid_samples
            and socket_pid_samples[-1].get("phase") == "after_teardown"
            else None
        )
        after_teardown_sample_complete = bool(
            isinstance(after_teardown_sample, Mapping)
            and after_teardown_sample.get("observed") is True
            and after_teardown_sample.get("pids") == []
        )
        if not server_stopped or not port_free:
            failure_code = failure_code or "host_teardown_unverified"
        if not after_teardown_sample_complete:
            failure_code = failure_code or "process_census_after_teardown_invalid"
        if server_stopped and port_free and after_teardown_sample_complete:
            evidence_path = (
                (run_directory / "profile-evidence.json").relative_to(root).as_posix()
                if run_directory is not None
                else ""
            )
            lock_released = lock.release(
                {
                    **lock_record,
                    "event": "released",
                    "released_at_utc": _format_utc_timestamp(
                        datetime.now(timezone.utc)
                    ),
                    "server_stopped": True,
                    "ports_free": {
                        str(port): port_status[port] for port in REQUIRED_PORTS
                    },
                    "after_teardown_socket_sample_observed": True,
                    "after_teardown_socket_pids": [],
                    "evidence_path": evidence_path,
                }
            )
        if not lock_released:
            failure_code = failure_code or "shared_live_window_lock_release_failed"
        _remove_import_guard(config_guard)
        sys.path[:] = previous_sys_path

    if run_directory is not None:
        guard_events, guard_events_raw, guard_events_complete = _read_guard_events_for_run(
            run_directory, args.run_id
        )
    if not guard_events_complete:
        failure_code = failure_code or "guard_event_journal_incomplete"

    process_census = _make_process_census(
        process_canaries=process_canaries,
        process=process,
        driver_exchange=driver_exchange,
        socket_pid_samples=socket_pid_samples,
        process_scopes=process_scopes,
        guard_events=guard_events,
        expected_run_id=args.run_id,
    )
    if not process_census["complete"]:
        failure_code = failure_code or "process_census_incomplete"

    if run_directory is not None:
        calls = result.get("calls") if isinstance(result, Mapping) else []
        if not isinstance(calls, list):
            calls = []
        call_count = result.get("call_count") if isinstance(result, Mapping) else 0
        if type(call_count) is not int or call_count < 0:
            call_count = len(calls)
        command_sites = _make_evidence_sites(calls)
        evidence = {
            "schema_version": 1,
            "authorization_ruling_id": AUTHORIZATION_RULING_ID,
            "profile_id": profile_id,
            "fixture_id": args.fixture_id,
            "party_size": args.party_size,
            "lifecycle": args.lifecycle,
            "planned_row_id": planned_row_id,
            "arm": arm,
            "sandbox_root": SANDBOX_RELATIVE.as_posix(),
            "run_id": args.run_id,
            "source_sha": args.source_sha,
            "command": command,
            "working_directory": SANDBOX_RELATIVE.as_posix(),
            "pythonpath": guarded_environment.get("PYTHONPATH", ""),
            "process_canaries": sorted(
                process_canaries,
                key=lambda report: report.get("canary_stage", ""),
            ),
            "guard_event_journal": {
                "path": (run_directory / "guard-events.jsonl").relative_to(root).as_posix(),
                "sha256": hashlib.sha256(guard_events_raw).hexdigest(),
                "event_count": len(guard_events),
                "complete": guard_events_complete,
            },
            "process_census": process_census,
            "controller_interpreter": _interpreter_identity(),
            "worker_interpreter": (
                result.get("interpreter") if isinstance(result, Mapping) else None
            ),
            "network_guard_active": (
                result.get("guard_active")
                if isinstance(result, Mapping)
                else None
            ),
            "provider_keys_blank": (
                result.get("provider_keys_blank")
                if isinstance(result, Mapping)
                else None
            ),
            "proxy_values_blank": (
                result.get("proxy_values_blank")
                if isinstance(result, Mapping)
                else None
            ),
            "real_project_config_loaded": (
                result.get("real_project_config_loaded")
                if isinstance(result, Mapping)
                else None
            ),
            "sandbox_config_loaded": (
                result.get("sandbox_config_loaded")
                if isinstance(result, Mapping)
                else None
            ),
            "startup_guard_from_sitecustomize": (
                result.get("startup_guard_from_sitecustomize")
                if isinstance(result, Mapping)
                else None
            ),
            "sandbox_config_origin_guard_active": (
                result.get("sandbox_config_origin_guard_active")
                if isinstance(result, Mapping)
                else None
            ),
            "driver_exchange": driver_exchange,
            "outcome": "completed" if failure_code is None else "failed",
            "calls": calls,
            "call_count": call_count,
            "call_sites": command_sites,
            "host_command": command,
            "runner_command": runner_command,
            "failure_code": failure_code,
            "teardown": {
                "server_stopped": server_stopped,
                "port_8360_free": port_status.get(HOST_PORT) is True,
                "lock_released": lock_released,
            },
        }
        evidence_path = run_directory / "profile-evidence.json"
        _write_json(evidence_path, evidence)
        evidence_relative = evidence_path.relative_to(root).as_posix()
        evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    else:
        evidence_relative = ""
        evidence_sha256 = ""

    if failure_code is not None or evidence is None:
        raise CharacterizationError(failure_code or "profile_not_measured")
    return evidence, evidence_relative, evidence_sha256


def _lock_holder_for_worker(args: argparse.Namespace) -> Mapping[str, Any]:
    common_directory = _git_common_directory()
    holder_path = common_directory / "neq-coordination" / "live-window.lock" / "holder.json"
    if holder_path.is_symlink() or not holder_path.is_file():
        raise CharacterizationError("shared_live_window_lock_missing")
    holder = _read_json(holder_path, "live_window_holder")
    if (
        not isinstance(holder, Mapping)
        or not _valid_live_window_lock_record(holder)
        or holder.get("authorizing_ruling") != AUTHORIZATION_RULING_ID
        or holder.get("gate") != "live-gate-preflight"
        or holder.get("run_id") != args.run_id
        or holder.get("source_sha") != args.source_sha
        or holder.get("fixture_id") != args.fixture_id
        or holder.get("party_size") != args.party_size
        or holder.get("lifecycle") != args.lifecycle
        or holder.get("planned_row_id") != args.planned_row_id
    ):
        raise CharacterizationError("shared_live_window_lock_identity_mismatch")
    return holder


def _activate_sandbox_sitecustomize(sandbox: Path) -> None:
    try:
        from scripts.live_gate_preflight_safety import (
            activate_preflight_safety,
            require_startup_guard_from,
        )

        del sandbox
        expected_sitecustomize = (
            PROJECT_ROOT / "scripts" / "live_gate_preflight_guard" / "sitecustomize.py"
        )
        require_startup_guard_from(expected_sitecustomize, require_local_guard=False)
        activate_preflight_safety()
        require_startup_guard_from(expected_sitecustomize)
    except CharacterizationError:
        raise
    except Exception as exc:
        raise CharacterizationError("host_startup_guard_inactive") from exc


def _provider_free_client_factory(*_args: Any, **_kwargs: Any) -> None:
    """Keep import-time host globals from constructing provider SDK clients."""


def _worker(args: argparse.Namespace) -> int:
    try:
        _require_worker_startup_guard()
    except CharacterizationError as exc:
        startup_guard_failure = exc.code
    else:
        startup_guard_failure = None
    try:
        root = _require_safe_worker_root()
    except CharacterizationError as exc:
        root = PROJECT_ROOT
        worker_root_failure = exc.code
    else:
        worker_root_failure = None
    sandbox = root / SANDBOX_RELATIVE
    server_returned = False
    interrupted = False
    failure_code: str | None = None
    stub: Any = None
    command: list[str] | None = None
    startup_guard_from_sitecustomize = False
    sandbox_config_origin_guard_active = False
    config_guard: _SandboxConfigOriginGuard | None = None
    previous_sys_path = list(sys.path)
    try:
        if startup_guard_failure is not None:
            raise CharacterizationError(startup_guard_failure)
        if worker_root_failure is not None:
            raise CharacterizationError(worker_root_failure)
        _configure_sandbox_import_paths(root, sandbox)
        _activate_sandbox_sitecustomize(sandbox)
        from scripts.live_gate_preflight_safety import require_guard_active
        from scripts.live_gate_preflight_stub import FailClosedRouterStub

        require_guard_active()
        startup_guard_from_sitecustomize = True
        config_guard = _install_sandbox_config_guard(sandbox)
        sandbox_config_origin_guard_active = config_guard in sys.meta_path
        expected_pythonpath = os.pathsep.join(
            (
                str(root / "scripts" / "live_gate_preflight_guard"),
                str(root),
            )
        )
        if os.environ.get("PYTHONPATH") != expected_pythonpath:
            raise CharacterizationError("pythonpath_identity_invalid")
        _verify_source_identity(args.source_sha)
        command = _host_command(
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            source_sha=args.source_sha,
            run_id=args.run_id,
            planned_row_id=args.planned_row_id,
            arm=args.arm,
            lifecycle_id=args.lifecycle_id,
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
        )
        from scripts.live_gate_preflight_safety import current_invocation_command

        actual_command = current_invocation_command()
        if actual_command != command:
            raise CharacterizationError("host_command_identity_mismatch")
        _lock_holder_for_worker(args)
        from scripts.mapping_pilot import server

        server_path = Path(server.__file__).resolve(strict=True)
        if server_path != root / "scripts" / "mapping_pilot" / "server.py":
            raise CharacterizationError("mapping_pilot_server_source_mismatch")

        sys.path.insert(0, str(sandbox))
        try:
            from utils import ai_client_factory, llm_router

            router_path = Path(llm_router.__file__).resolve(strict=True)
            if router_path != sandbox / "utils" / "llm_router.py":
                raise CharacterizationError("sandbox_router_source_mismatch")
            factory_path = Path(ai_client_factory.__file__).resolve(strict=True)
            if factory_path != sandbox / "utils" / "ai_client_factory.py":
                raise CharacterizationError(
                    "sandbox_provider_factory_source_mismatch"
                )
            router = getattr(llm_router, "llm", None)
            original_call = getattr(router, "call", None)
            if not callable(original_call):
                raise CharacterizationError("sandbox_router_unavailable")
            original_create_chat_client = getattr(
                ai_client_factory, "create_chat_client", None
            )
            if not callable(original_create_chat_client):
                raise CharacterizationError(
                    "sandbox_provider_factory_unavailable"
                )
            stub = FailClosedRouterStub(
                source_sha=args.source_sha,
                responses={
                    "dm_main": (
                        '{"narration":"The party pauses and takes in the scene.",'
                        '"actions":[]}'
                    )
                },
                command=command,
                pythonpath=os.environ.get("PYTHONPATH", ""),
                source_root=sandbox,
            )
            router.call = stub
            # main.py and core.combat.combat_manager.py create module-level
            # clients during import. The sandbox has blank keys, so router-call
            # stubbing alone still lets OpenAI client construction abort startup.
            # Keep those globals inert; routed gameplay calls use the fail-closed
            # stub above, and no SDK client or credential is created.
            ai_client_factory.create_chat_client = _provider_free_client_factory
            try:
                try:
                    server.launch_worker(
                        arm=args.arm,
                        fixture_id=args.fixture_id,
                        party_size=args.party_size,
                        row_run_id=args.run_id,
                        lifecycle_id=args.lifecycle_id,
                        resume=args.lifecycle == "resume",
                        resume_checkpoint_sha256=args.resume_checkpoint_sha256,
                        runtime_root=SANDBOX_RELATIVE,
                    )
                    server_returned = True
                    interrupted = False
                except KeyboardInterrupt:
                    server_returned = False
                    interrupted = True
                except BaseException as exc:
                    server_returned = False
                    interrupted = False
                    failure_code = "host_exception_" + type(exc).__name__
            finally:
                ai_client_factory.create_chat_client = original_create_chat_client
                if getattr(router, "call", None) is stub:
                    router.call = original_call
        finally:
            if sys.path and sys.path[0] == str(sandbox):
                sys.path.pop(0)
    except BaseException as exc:
        server_returned = False
        interrupted = False
        failure_code = (
            exc.code if isinstance(exc, CharacterizationError)
            else "host_exception_" + type(exc).__name__
        )
    finally:
        _remove_import_guard(config_guard)
        sys.path[:] = previous_sys_path

    root_text = str(PROJECT_ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from scripts.live_gate_preflight_safety import ACTIVE_GUARD_ENV, require_guard_active

    try:
        require_guard_active()
        guard_active = os.environ.get(ACTIVE_GUARD_ENV) == "1"
    except Exception:
        guard_active = False
    provider_keys_blank = all(os.environ.get(name, "") == "" for name in _KNOWN_PROVIDER_KEYS)
    proxy_values_blank = all(
        not name.upper().endswith("_PROXY") or value == ""
        for name, value in os.environ.items()
    )
    config_module = sys.modules.get("config")
    config_path = getattr(config_module, "__file__", None)
    real_project_config_loaded = False
    sandbox_config_loaded = False
    if isinstance(config_path, (str, os.PathLike)):
        try:
            resolved_config = Path(config_path).resolve(strict=True)
            real_project_config_loaded = resolved_config == (root / "config.py").resolve(
                strict=True
            )
            sandbox_config_loaded = resolved_config == (sandbox / "config.py").resolve(
                strict=True
            )
        except (OSError, RuntimeError):
            real_project_config_loaded = True
    if not sandbox_config_loaded and failure_code is None:
        failure_code = "sandbox_config_identity_invalid"
    stub_failure_code = getattr(stub, "failure_code", None)
    calls = list(getattr(stub, "calls", []))
    call_count = getattr(stub, "call_count", len(calls))
    if type(call_count) is not int or call_count < 1:
        if failure_code is None:
            failure_code = "router_call_missing"
    completed = (
        interrupted
        and not server_returned
        and failure_code is None
        and guard_active
        and provider_keys_blank
        and proxy_values_blank
        and not real_project_config_loaded
        and sandbox_config_loaded
        and startup_guard_from_sitecustomize
        and sandbox_config_origin_guard_active
        and type(call_count) is int
        and call_count >= 1
        and call_count == len(calls)
        and stub_failure_code is None
    )
    result = {
        "schema_version": 1,
        "run_id": args.run_id,
        "source_sha": args.source_sha,
        "command": command,
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "interpreter": _interpreter_identity(),
        "startup_canary_report": os.environ.get(
            "NEQ_PREFLIGHT_STARTUP_CANARY_REPORT", ""
        ),
        "guard_active": guard_active,
        "provider_keys_blank": provider_keys_blank,
        "proxy_values_blank": proxy_values_blank,
        "real_project_config_loaded": real_project_config_loaded,
        "sandbox_config_loaded": sandbox_config_loaded,
        "startup_guard_from_sitecustomize": startup_guard_from_sitecustomize,
        "sandbox_config_origin_guard_active": sandbox_config_origin_guard_active,
        "server_returned": server_returned,
        "interrupted": interrupted,
        "outcome": "completed" if completed else "failed",
        "failure_code": failure_code or stub_failure_code,
        "stub_failure_code": stub_failure_code,
        "call_count": call_count,
        "calls": calls,
    }
    try:
        _write_json(_worker_result_path(args.run_id), result)
    except Exception:
        return 2
    return 0 if completed else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.worker:
        return _worker(args)
    try:
        evidence, evidence_path, evidence_sha256 = _characterize(args)
    except CharacterizationError as exc:
        print("[FAIL] profile_characterization=" + exc.code, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": evidence["outcome"],
                "profile_id": evidence["profile_id"],
                "fixture_id": evidence["fixture_id"],
                "party_size": evidence["party_size"],
                "lifecycle": evidence["lifecycle"],
                "call_count": evidence["call_count"],
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha256,
                "booking_eligible": False,
                "failure_code": evidence.get("failure_code"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0 if evidence["outcome"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
