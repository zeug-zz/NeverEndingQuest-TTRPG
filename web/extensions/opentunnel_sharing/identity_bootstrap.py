# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Explicit, once-per-profile OpenTunnel identity initialization.

This boundary is called only after an explicit facilitator action. It mints an
identity with service managers hidden from the companion, proves the temporary
daemon was stopped, and records completion only after all ownership checks pass.
If evidence is incomplete, no additional cleanup is attempted and any uncertain
resource is left untouched for facilitator review.
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, Sequence

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.profile_state import (
    ProfileLayout,
    companion_environment,
)

BOOTSTRAP_SCHEMA = "neq.opentunnel.bootstrap.v1"
BOOTSTRAP_MARKER_FILENAME = "identity_bootstrap.json"
MAX_BOOTSTRAP_MARKER_BYTES = 1024
MAX_COMMAND_OUTPUT_CHARS = 64 * 1024
MAX_RESULT_FACTS = 24
MAX_STATUS_TIMEOUT_SECONDS = 30.0
MAX_DOWN_TIMEOUT_SECONDS = 30.0
MAX_UP_TIMEOUT_SECONDS = 300.0
MAX_LOCK_TIMEOUT_SECONDS = 5.0
DEFAULT_UP_TIMEOUT_SECONDS = 120.0
DEFAULT_STATUS_TIMEOUT_SECONDS = 15.0
DEFAULT_DOWN_TIMEOUT_SECONDS = 15.0
DEFAULT_LOCK_TIMEOUT_SECONDS = 2.0
_PROCESS_SCAN_BYTES = 64 * 1024

BootstrapState = Literal[
    "not_confirmed",
    "refused",
    "marker_invalid",
    "already_initialized",
    "uncertain",
    "residual_found",
    "failed",
    "initialized",
]
ObservationState = Literal["absent", "present", "unknown"]
ObservationKind = Literal["service", "process", "helper"]
StatusParser = Callable[[str], "StatusEvidence"]

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")
_UTC_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z"
)
_HOST_RE = re.compile(
    r"(?i)(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"opentunnel\.xyz\Z"
)
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"'`]+")
_HOSTNAME_RE = re.compile(
    r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z][a-z0-9-]{1,62}\b"
)
_LONG_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_+/-])[A-Za-z0-9_+/-]{32,}={0,2}(?![A-Za-z0-9_+/-])"
)
_HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_TUNNEL_ID_RE = re.compile(
    r"(?i)(\btunnel[_ -]?id\s*[:=]\s*)[^\s,;]+"
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)(\b(?:password|passwd|secret|authorization|bearer|token)\s*[:=]\s*)"
    r"[^\s,;]+"
)
_KNOWN_OBSERVATION_BASES = frozenset(
    {
        "observed_user_view",
        "isolated_service_files_checked",
        "proc_scan_complete",
        "ps_snapshot_complete",
        "unresolvable_on_empty_path",
        "observation_failed",
        "invalid_observation",
    }
)
_INSTALL_MARKER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


@dataclass(frozen=True, slots=True, repr=False)
class RunResult:
    """Bounded command result whose output is never exposed through repr."""

    returncode: int | None
    bounded_output: str
    output_truncated: bool = False
    timed_out: bool = False

    def __repr__(self) -> str:
        return (
            "RunResult(returncode=%r, output_truncated=%r, timed_out=%r)"
            % (self.returncode, self.output_truncated, self.timed_out)
        )


@dataclass(frozen=True, slots=True)
class ProcessEvidence:
    """Three positive ownership predicates for a discovered process."""

    executable_matches: bool | None
    profile_matches: bool | None
    uid_matches: bool | None


@dataclass(frozen=True, slots=True)
class Observation:
    """A bounded observer result; no paths, labels, PIDs, or raw output."""

    state: ObservationState
    basis: str
    count: int = 0
    processes: tuple[ProcessEvidence, ...] = ()


class IdentityObserver(Protocol):
    """Read-only observations for the dedicated OpenTunnel profile."""

    def service_manager_entries(self, profile: str) -> Observation: ...

    def profile_processes(self, profile: str) -> Observation: ...

    def helper_processes(self) -> Observation: ...


@dataclass(frozen=True, slots=True)
class StatusEvidence:
    """Only the facts needed to accept the temporary identity daemon."""

    identity_confirmed: bool
    daemon_running: bool


@dataclass(frozen=True, slots=True, repr=False)
class BootstrapResult:
    """Bounded, credential-free result for the facilitator controller."""

    state: BootstrapState
    reason: str
    facts: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return "BootstrapResult(state=%r, reason=%r, facts=%r)" % (
            self.state,
            self.reason,
            self.facts,
        )


def redact(value: object, secrets_to_scrub: Sequence[str] = ()) -> str:
    """Redact URLs, hosts, tunnel identifiers, and credential-like tokens."""
    text = str(value)
    text = _URL_RE.sub("<url>", text)
    text = _TUNNEL_ID_RE.sub(r"\1<redacted>", text)
    text = _NAMED_SECRET_RE.sub(r"\1<redacted>", text)
    text = _HEX_TOKEN_RE.sub("<redacted-token>", text)
    text = _LONG_TOKEN_RE.sub("<redacted-token>", text)
    text = _HOSTNAME_RE.sub("<host>", text)
    for secret in sorted(
        (item for item in secrets_to_scrub if isinstance(item, str) and item),
        key=len,
        reverse=True,
    ):
        text = text.replace(secret, "<redacted>")
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text[:2048]


def parse_identity_status(output: str) -> StatusEvidence:
    """Parse N0's identity/status facts without retaining identity values."""
    if not isinstance(output, str) or len(output) > MAX_COMMAND_OUTPUT_CHARS:
        return StatusEvidence(False, False)
    hostname_match = re.search(r"(?im)^\s*Hostname:\s*(\S+)\s*$", output)
    hostname = hostname_match.group(1) if hostname_match else ""
    tunnel_id = re.search(
        r"(?im)^\s*Tunnel ID:\s*(\S+)\s*$", output
    ) or re.search(r"(?i)\btunnel[_ -]?id\s*[:=]\s*[^\s,;]+", output)
    service_match = re.search(r"(?im)^\s*Service:\s*(.+?)\s*$", output)
    service_line = service_match.group(1).strip() if service_match else ""
    pid_match = re.search(r"(?i)\bpid\s+([0-9]+)\b", service_line)
    pid_is_positive = bool(pid_match and int(pid_match.group(1)) > 0)
    stopped = service_line.casefold().startswith("stopped")
    return StatusEvidence(
        identity_confirmed=bool(hostname and _HOST_RE.fullmatch(hostname) and tunnel_id),
        daemon_running=bool(service_line and not stopped and pid_is_positive),
    )


def parse_launchctl_entries(output: str, profile: str) -> Observation:
    """Parse a bounded ``launchctl list`` fixture for profile-owned labels."""
    if not _valid_profile(profile) or not isinstance(output, str):
        return Observation("unknown", "invalid_observation")
    if len(output) > MAX_COMMAND_OUTPUT_CHARS:
        return Observation("unknown", "invalid_observation")
    matches = [
        line
        for line in output.splitlines()
        if "opentunnel" in line.casefold() and profile.casefold() in line.casefold()
    ]
    if matches:
        return Observation("present", "observed_user_view", len(matches))
    return Observation("absent", "observed_user_view")


def parse_systemd_unit_files(output: str, profile: str) -> Observation:
    """Parse a bounded ``systemctl --user list-unit-files`` fixture."""
    if not _valid_profile(profile) or not isinstance(output, str):
        return Observation("unknown", "invalid_observation")
    if len(output) > MAX_COMMAND_OUTPUT_CHARS:
        return Observation("unknown", "invalid_observation")
    matches = [
        line
        for line in output.splitlines()
        if "opentunnel" in line.casefold() and profile.casefold() in line.casefold()
    ]
    if matches:
        return Observation("present", "observed_user_view", len(matches))
    return Observation("absent", "observed_user_view")


def parse_ps_processes(
    output: str,
    *,
    profile: str,
    executable_path: Path,
    uid: int,
) -> Observation:
    """Parse fixed ``ps`` output into ownership booleans, not raw identities."""
    if (
        not _valid_profile(profile)
        or not isinstance(output, str)
        or len(output) > MAX_COMMAND_OUTPUT_CHARS
        or type(uid) is not int
        or uid < 0
    ):
        return Observation("unknown", "invalid_observation")
    try:
        expected_executable = Path(executable_path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return Observation("unknown", "invalid_observation")

    processes: list[ProcessEvidence] = []
    ambiguous = False
    for line in output.splitlines():
        match = re.match(r"^\s*([0-9]+)\s+([0-9]+)\s+(.+?)\s*$", line)
        if match is None:
            if "opentunnel" in line.casefold() or profile.casefold() in line.casefold():
                ambiguous = True
            continue
        observed_uid = int(match.group(2))
        command = match.group(3)
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            if "opentunnel" in command.casefold() or profile.casefold() in command.casefold():
                ambiguous = True
            continue
        if not argv:
            continue
        try:
            observed_executable = Path(argv[0]).resolve(strict=True)
            executable_matches: bool | None = observed_executable == expected_executable
        except (OSError, RuntimeError, TypeError, ValueError):
            executable_matches = False if "opentunnel" in command.casefold() else None
        profile_argument = _profile_argument(argv)
        command_mentions_profile = profile.casefold() in command.casefold()
        candidate = bool(
            executable_matches is True
            or "opentunnel" in command.casefold()
            or command_mentions_profile
        )
        if not candidate:
            continue
        if profile_argument is not None:
            profile_matches: bool | None = profile_argument == profile
        elif command_mentions_profile:
            profile_matches = True
        elif executable_matches is True:
            profile_matches = None
        else:
            continue
        if profile_matches is False:
            continue
        processes.append(
            ProcessEvidence(
                executable_matches=executable_matches,
                profile_matches=profile_matches,
                uid_matches=observed_uid == uid,
            )
        )

    if ambiguous:
        return Observation("unknown", "ps_snapshot_complete", len(processes), tuple(processes))
    if processes:
        return Observation("present", "ps_snapshot_complete", len(processes), tuple(processes))
    return Observation("absent", "ps_snapshot_complete")


def parse_linux_process_record(
    *,
    executable_path: str,
    argv: Sequence[str],
    environment: Mapping[str, str],
    observed_uid: int,
    profile: str,
    expected_executable: Path,
    expected_environment: Mapping[str, str],
) -> ProcessEvidence | None:
    """Parse one bounded procfs fixture without returning process identifiers."""
    if (
        not _valid_profile(profile)
        or type(observed_uid) is not int
        or observed_uid < 0
        or not isinstance(executable_path, str)
        or not isinstance(argv, Sequence)
        or isinstance(argv, (str, bytes))
        or any(not isinstance(item, str) for item in argv)
        or not isinstance(environment, Mapping)
    ):
        return None
    try:
        executable_matches = (
            Path(executable_path).resolve(strict=True)
            == Path(expected_executable).resolve(strict=True)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        executable_matches = False
    profile_argument = _profile_argument(argv)
    profile_environment_matches = all(
        environment.get(key) == value
        for key, value in expected_environment.items()
        if key != "PATH"
    )
    target_marker = profile_argument == profile or profile_environment_matches
    explicit_other_profile = profile_argument is not None and profile_argument != profile
    if explicit_other_profile:
        return None
    if not target_marker:
        return None if not executable_matches else ProcessEvidence(
            executable_matches=True,
            profile_matches=None,
            uid_matches=observed_uid == os.getuid(),
        )
    return ProcessEvidence(
        executable_matches=executable_matches,
        profile_matches=True,
        uid_matches=observed_uid == os.getuid(),
    )


def bootstrap_identity(
    layout: ProfileLayout,
    resolution: CompanionResolution,
    *,
    runner: Callable[[Sequence[str], Mapping[str, str], float], RunResult],
    observer: IdentityObserver,
    facilitator_confirmed: bool,
    status_parser: StatusParser = parse_identity_status,
    up_deadline: float = DEFAULT_UP_TIMEOUT_SECONDS,
    status_deadline: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
    down_deadline: float = DEFAULT_DOWN_TIMEOUT_SECONDS,
    lock_deadline: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> BootstrapResult:
    """Initialize one dedicated profile after an explicit facilitator action.

    The command order is ``--profile PROFILE up``, ``status``, then ``down``.
    A failed or timed-out up is followed by one read-only status probe. A single
    bounded down is allowed only when a successful status positively proves the
    temporary identity daemon is running. Otherwise no cleanup command is
    issued; possible resources remain untouched and the result is uncertain.
    """
    if facilitator_confirmed is not True:
        return _result("not_confirmed", "facilitator_confirmation_required")
    if not _layout_is_ready(layout):
        return _result("refused", "profile_layout_not_ready")
    if (
        not isinstance(resolution, CompanionResolution)
        or resolution.state != "resolved"
        or resolution.path is None
    ):
        return _result("refused", "companion_unresolved")
    try:
        original_executable = Path(resolution.path)
        executable = original_executable.resolve(strict=True)
        metadata = os.lstat(original_executable)
    except (OSError, RuntimeError, TypeError, ValueError):
        return _result("refused", "companion_unavailable")
    if (
        original_executable != executable
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not os.access(executable, os.X_OK)
        or not _expected_install_relative_path(executable)
    ):
        return _result("refused", "companion_not_executable")
    if not _deadlines_valid(
        up_deadline, status_deadline, down_deadline, lock_deadline
    ):
        return _result("refused", "deadline_invalid")
    if not callable(runner) or not callable(status_parser) or observer is None:
        return _result("refused", "bootstrap_dependency_invalid")

    marker_state = _read_marker(layout)
    if marker_state == "valid":
        return _result("already_initialized", "marker_valid")
    if marker_state == "invalid":
        return _result("marker_invalid", "marker_invalid")

    lock_fd = _open_owner_lock(layout)
    if lock_fd is None:
        return _result("uncertain", "profile_lock_unavailable")
    facts: list[str] = []
    try:
        if not _acquire_profile_lock(lock_fd, lock_deadline):
            return _result("uncertain", "profile_lock_timeout")
        marker_state = _read_marker(layout)
        if marker_state == "valid":
            return _result("already_initialized", "marker_valid")
        if marker_state == "invalid":
            return _result("marker_invalid", "marker_invalid")

        precheck = _observe_all(observer, layout.profile)
        facts.extend(_observation_fact("pre", kind, item) for kind, item in precheck)
        precheck_verdict = _assess_observations(precheck)
        if precheck_verdict != "absent":
            state: BootstrapState = (
                "residual_found" if precheck_verdict == "present" else "uncertain"
            )
            reason = "preexisting_owned_resource" if state == "residual_found" else "precheck_unproven"
            return _result(state, reason, facts)

        environment = companion_environment(layout)
        environment["PATH"] = ""
        if set(environment) != {
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_RUNTIME_DIR",
            "PATH",
        }:
            return _result("uncertain", "environment_allowlist_invalid", facts)
        facts.append("empty_path=true")

        up = _invoke_runner(
            runner,
            (str(executable), "--profile", layout.profile, "up"),
            environment,
            up_deadline,
        )
        facts.append("up=" + _command_fact(up))

        status = _invoke_runner(
            runner,
            (str(executable), "--profile", layout.profile, "status"),
            environment,
            status_deadline,
        )
        facts.append("status=" + _command_fact(status))
        status_evidence = _parse_status(status, status_parser)
        status_proves_daemon = bool(
            status.returncode == 0
            and not status.output_truncated
            and not status.timed_out
            and status_evidence is not None
            and status_evidence.identity_confirmed is True
            and status_evidence.daemon_running is True
        )
        facts.append("status_daemon_proven=" + _bool_fact(status_proves_daemon))

        if not status_proves_daemon:
            reason = "status_unproven" if _command_succeeded(up) else "up_failed_status_unproven"
            return _result("uncertain", reason, facts)

        down = _invoke_runner(
            runner,
            (str(executable), "--profile", layout.profile, "down"),
            environment,
            down_deadline,
        )
        facts.append("down=" + _command_fact(down))

        postcheck = _observe_all(observer, layout.profile)
        facts.extend(_observation_fact("post", kind, item) for kind, item in postcheck)
        postcheck_verdict = _assess_observations(postcheck)
        if postcheck_verdict != "absent":
            state = "residual_found" if postcheck_verdict == "present" else "uncertain"
            reason = "owned_resource_remains" if state == "residual_found" else "postcheck_unproven"
            return _result(state, reason, facts)
        if not _command_succeeded(down):
            return _result("failed", "down_failed", facts)
        if not _command_succeeded(up):
            return _result("failed", "up_failed", facts)

        if not _write_marker(layout):
            return _result("failed", "marker_write_failed", facts)
        return _result("initialized", "identity_initialized", facts)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(lock_fd)
        except OSError:
            pass


class DefaultCommandRunner:
    """Run a fixed argv with a strict timeout and bounded retained output."""

    def __call__(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        timeout: float,
    ) -> RunResult:
        if (
            not argv
            or any(not isinstance(item, str) or not item for item in argv)
            or not _valid_environment(env)
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            return RunResult(None, "")
        process: subprocess.Popen[bytes] | None = None
        output = bytearray()
        truncated = False
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=dict(env),
                shell=False,
                close_fds=True,
                bufsize=0,
            )
            assert process.stdout is not None
            os.set_blocking(process.stdout.fileno(), False)
            import selectors

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            expires_at = time.monotonic() + float(timeout)
            try:
                while selector.get_map():
                    remaining = expires_at - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("command_timeout")
                    events = selector.select(remaining)
                    for key, _mask in events:
                        try:
                            chunk = os.read(key.fd, 8192)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = MAX_COMMAND_OUTPUT_CHARS - len(output)
                        if available > 0:
                            output.extend(chunk[:available])
                        if len(chunk) > available:
                            truncated = True
                remaining = expires_at - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("command_timeout")
                returncode = process.wait(timeout=remaining)
                return RunResult(
                    returncode,
                    output.decode("utf-8", "replace"),
                    truncated,
                    False,
                )
            finally:
                selector.close()
        except (subprocess.TimeoutExpired, TimeoutError):
            if process is not None:
                self._stop_process(process)
            return RunResult(
                None,
                output.decode("utf-8", "replace"),
                truncated,
                True,
            )
        except OSError:
            if process is not None:
                self._stop_process(process)
            return RunResult(None, output.decode("utf-8", "replace"), truncated)
        finally:
            if process is not None and process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        try:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            return


class DefaultIdentityObserver:
    """Best-effort, read-only macOS/Linux service and process observations."""

    def __init__(
        self,
        layout: ProfileLayout,
        companion_path: Path,
        *,
        command_runner: Callable[[Sequence[str], Mapping[str, str], float], RunResult]
        | None = None,
        system_name: str | None = None,
        proc_root: Path = Path("/proc"),
    ) -> None:
        self._layout = layout
        self._companion_path = Path(companion_path)
        self._runner = command_runner or DefaultCommandRunner()
        self._system_name = platform.system() if system_name is None else system_name
        self._proc_root = Path(proc_root)

    def service_manager_entries(self, profile: str) -> Observation:
        if not _valid_profile(profile) or profile != self._layout.profile:
            return Observation("unknown", "invalid_observation")
        files = self._isolated_service_files(profile)
        if files.state == "present":
            return files
        if files.state == "unknown":
            return files

        if self._system_name == "Darwin":
            manager = "launchctl"
            argv = ("/bin/launchctl", "list")
            env = {
                "PATH": "",
                "HOME": str(self._layout.data_home),
                "LANG": "C",
                "LC_ALL": "C",
            }
            parser = parse_launchctl_entries
            manager_available = Path("/bin/launchctl").is_file()
        elif self._system_name == "Linux":
            manager = "systemctl"
            executable = shutil.which(manager, path=os.defpath)
            if executable is None:
                if (
                    _linux_no_service_manager_proof()
                    and _unresolvable_on_empty_path(manager)
                ):
                    return Observation("absent", "unresolvable_on_empty_path")
                return Observation("unknown", "observation_failed")
            argv = (executable, "--user", "list-unit-files", "opentunnel*")
            env = {
                "PATH": "",
                "HOME": str(self._layout.data_home),
                "XDG_CONFIG_HOME": str(self._layout.config_home),
                "XDG_RUNTIME_DIR": str(self._layout.runtime_dir),
                "LANG": "C",
                "LC_ALL": "C",
                "SYSTEMD_PAGER": "cat",
                "SYSTEMD_COLORS": "0",
            }
            parser = parse_systemd_unit_files
            manager_available = True
        else:
            return Observation("unknown", "observation_failed")

        if not manager_available:
            if _unresolvable_on_empty_path(manager):
                return Observation("absent", "unresolvable_on_empty_path")
            return Observation("unknown", "observation_failed")
        result = self._runner(argv, env, 10.0)
        if (
            isinstance(result, RunResult)
            and result.returncode == 0
            and not result.timed_out
            and not result.output_truncated
        ):
            parsed = parser(result.bounded_output, profile)
            if parsed.state == "present":
                return parsed
            if parsed.state == "absent":
                return Observation("absent", "observed_user_view")
        return Observation("unknown", "observation_failed")

    def profile_processes(self, profile: str) -> Observation:
        if not _valid_profile(profile) or profile != self._layout.profile:
            return Observation("unknown", "invalid_observation")
        if self._system_name == "Linux":
            return self._scan_linux_processes(profile, helpers=False)
        if self._system_name == "Darwin":
            result = self._run_ps()
            if result is None:
                return Observation("unknown", "observation_failed")
            return parse_ps_processes(
                result,
                profile=profile,
                executable_path=self._companion_path,
                uid=os.getuid(),
            )
        return Observation("unknown", "observation_failed")

    def helper_processes(self) -> Observation:
        profile = self._layout.profile
        if self._system_name == "Linux":
            return self._scan_linux_processes(profile, helpers=True)
        if self._system_name == "Darwin":
            result = self._run_ps()
            if result is None:
                return Observation("unknown", "observation_failed")
            return parse_ps_processes(
                result,
                profile=profile,
                executable_path=self._companion_path,
                uid=os.getuid(),
            )
        return Observation("unknown", "observation_failed")

    def _isolated_service_files(self, profile: str) -> Observation:
        if self._system_name == "Darwin":
            directories = (self._layout.data_home / "Library/LaunchAgents",)
        elif self._system_name == "Linux":
            directories = (self._layout.config_home / "systemd/user",)
        else:
            return Observation("unknown", "observation_failed")
        found = 0
        try:
            for directory in directories:
                try:
                    names = [entry.name for entry in directory.iterdir()]
                except FileNotFoundError:
                    continue
                for name in names:
                    lowered = name.casefold()
                    if "opentunnel" in lowered:
                        found += 1
        except OSError:
            return Observation("unknown", "observation_failed")
        if found:
            return Observation("present", "isolated_service_files_checked", found)
        return Observation("absent", "isolated_service_files_checked")

    def _run_ps(self) -> str | None:
        result = self._runner(
            ("/bin/ps", "-axo", "pid=,uid=,command="),
            {"PATH": "", "LC_ALL": "C"},
            10.0,
        )
        if (
            not isinstance(result, RunResult)
            or result.returncode != 0
            or result.timed_out
            or result.output_truncated
        ):
            return None
        return result.bounded_output

    def _scan_linux_processes(self, profile: str, *, helpers: bool) -> Observation:
        try:
            process_dirs = tuple(
                item for item in self._proc_root.iterdir() if item.name.isdigit()
            )
        except OSError:
            return Observation("unknown", "observation_failed")

        found: list[ProcessEvidence] = []
        uncertain = False
        expected_environment = {
            **companion_environment(self._layout),
            "PATH": "",
        }
        try:
            expected_executable = self._companion_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return Observation("unknown", "invalid_observation")
        for process_dir in process_dirs:
            try:
                observed_uid = _read_proc_uid(process_dir / "status")
            except OSError:
                observed_uid = None
            if observed_uid is None:
                try:
                    process_dir.stat()
                except FileNotFoundError:
                    continue
                except OSError:
                    uncertain = True
                    continue
                uncertain = True
                continue
            if observed_uid != os.getuid():
                continue
            try:
                comm = (process_dir / "comm").read_text(encoding="ascii").strip()
            except FileNotFoundError:
                continue
            except (OSError, UnicodeDecodeError):
                uncertain = True
                continue
            try:
                executable_text = os.readlink(process_dir / "exe")
                executable = Path(executable_text).resolve(strict=True)
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError, ValueError):
                uncertain = True
                continue
            executable_candidate = executable == expected_executable
            helper_candidate = "opentunnel" in comm.casefold() or "opentunnel" in executable.name.casefold()
            if not executable_candidate and not helper_candidate:
                continue
            try:
                argv_payload = _read_bounded_file(process_dir / "cmdline")
                environment_payload = _read_bounded_file(process_dir / "environ")
                if argv_payload is None or environment_payload is None:
                    uncertain = True
                    continue
                argv = tuple(
                    os.fsdecode(value)
                    for value in argv_payload.split(b"\0")
                    if value
                )
                environment: dict[str, str] = {}
                for item in environment_payload.split(b"\0"):
                    if b"=" not in item:
                        continue
                    key, value = item.split(b"=", 1)
                    environment[os.fsdecode(key)] = os.fsdecode(value)
            except OSError:
                uncertain = True
                continue
            evidence = parse_linux_process_record(
                executable_path=str(executable),
                argv=argv,
                environment=environment,
                observed_uid=observed_uid,
                profile=profile,
                expected_executable=expected_executable,
                expected_environment=expected_environment,
            )
            if evidence is None:
                continue
            if helpers and not helper_candidate:
                continue
            found.append(evidence)
        if uncertain:
            return Observation("unknown", "proc_scan_complete", len(found), tuple(found))
        if found:
            return Observation("present", "proc_scan_complete", len(found), tuple(found))
        return Observation("absent", "proc_scan_complete")


def _observe_all(
    observer: IdentityObserver, profile: str
) -> tuple[tuple[ObservationKind, Observation], ...]:
    observations: list[tuple[ObservationKind, Observation]] = []
    for kind, method in (
        ("service", lambda: observer.service_manager_entries(profile)),
        ("process", lambda: observer.profile_processes(profile)),
        ("helper", observer.helper_processes),
    ):
        try:
            observation = method()
        except Exception:
            observation = Observation("unknown", "observation_failed")
        if not isinstance(observation, Observation):
            observation = Observation("unknown", "invalid_observation")
        observations.append((kind, observation))
    return tuple(observations)


def _assess_observations(
    observations: Sequence[tuple[ObservationKind, Observation]],
) -> Literal["absent", "present", "unknown"]:
    saw_present = False
    for kind, observation in observations:
        if (
            observation.state not in {"absent", "present", "unknown"}
            or observation.basis not in _KNOWN_OBSERVATION_BASES
            or type(observation.count) is not int
            or observation.count < 0
            or observation.count > 10000
            or not isinstance(observation.processes, tuple)
        ):
            return "unknown"
        if observation.state == "unknown":
            return "unknown"
        if observation.state == "absent":
            if observation.count != 0 or observation.processes:
                return "unknown"
            if kind == "service" and observation.basis not in {
                "observed_user_view",
                "isolated_service_files_checked",
                "unresolvable_on_empty_path",
            }:
                return "unknown"
            if kind != "service" and observation.basis not in {
                "proc_scan_complete",
                "ps_snapshot_complete",
            }:
                return "unknown"
            if observation.basis == "unresolvable_on_empty_path" and kind != "service":
                return "unknown"
            continue
        if observation.count <= 0:
            return "unknown"
        if kind == "service":
            if observation.processes:
                return "unknown"
            saw_present = True
            continue
        if len(observation.processes) != observation.count:
            return "unknown"
        for process in observation.processes:
            if not isinstance(process, ProcessEvidence):
                return "unknown"
            if (
                process.executable_matches is not True
                or process.profile_matches is not True
                or process.uid_matches is not True
            ):
                return "unknown"
        saw_present = True
    return "present" if saw_present else "absent"


def _observation_fact(
    phase: str, kind: ObservationKind, observation: Observation
) -> str:
    state = observation.state if observation.state in {"absent", "present", "unknown"} else "unknown"
    basis = observation.basis if observation.basis in _KNOWN_OBSERVATION_BASES else "invalid_observation"
    count = observation.count if type(observation.count) is int and 0 <= observation.count <= 10000 else 0
    return "%s.%s=%s:%s:%d" % (phase, kind, state, basis, count)


def _read_marker(layout: ProfileLayout) -> Literal["absent", "valid", "invalid"]:
    marker = layout.state_home / BOOTSTRAP_MARKER_FILENAME
    try:
        path_metadata = os.lstat(marker)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "invalid"
    uid = _current_uid()
    if uid is None or not _is_private_regular_file(path_metadata, uid):
        return "invalid"
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return "invalid"
    try:
        descriptor = os.open(marker, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return "invalid"
    try:
        opened = os.fstat(descriptor)
        if not _is_private_regular_file(opened, uid) or not _same_file(opened, path_metadata):
            return "invalid"
        payload = bytearray()
        while len(payload) <= MAX_BOOTSTRAP_MARKER_BYTES:
            chunk = os.read(descriptor, min(256, MAX_BOOTSTRAP_MARKER_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_BOOTSTRAP_MARKER_BYTES:
            return "invalid"
    except OSError:
        return "invalid"
    finally:
        try:
            os.close(descriptor)
        except OSError:
            return "invalid"
    try:
        record = json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return "invalid"
    if (
        not isinstance(record, dict)
        or set(record) != {"schema", "profile", "completed_at"}
        or record.get("schema") != BOOTSTRAP_SCHEMA
        or record.get("profile") != layout.profile
        or not _valid_timestamp(record.get("completed_at"))
    ):
        return "invalid"
    return "valid"


def _write_marker(layout: ProfileLayout) -> bool:
    uid = _current_uid()
    if uid is None:
        return False
    directory = layout.state_home
    directory_fd = _open_private_directory(directory, uid)
    if directory_fd is None:
        return False
    temporary_name: str | None = None
    descriptor = -1
    marker_linked = False
    payload = json.dumps(
        {
            "schema": BOOTSTRAP_SCHEMA,
            "profile": layout.profile,
            "completed_at": _utc_now(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    try:
        if len(payload) > MAX_BOOTSTRAP_MARKER_BYTES:
            return False
        for _attempt in range(3):
            temporary_name = ".identity_bootstrap.%s.tmp" % os.urandom(8).hex()
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                temporary_name = None
                continue
            except OSError:
                return False
        if descriptor < 0 or temporary_name is None:
            return False
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        temporary_metadata = os.fstat(descriptor)
        if not _is_private_regular_file(temporary_metadata, uid):
            return False
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary_name,
            BOOTSTRAP_MARKER_FILENAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        marker_linked = True
        os.fsync(directory_fd)
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
        return _read_marker(layout) == "valid"
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_name is not None and not marker_linked:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _layout_is_ready(layout: object) -> bool:
    if not isinstance(layout, ProfileLayout) or not _valid_profile(layout.profile):
        return False
    uid = _current_uid()
    if uid is None:
        return False
    try:
        state_root = Path(layout.state_root)
        profile_root = Path(layout.profile_root)
        from web.extensions.opentunnel_sharing import profile_state

        if profile_state._is_forbidden_state_root(state_root):
            return False
        expected_profile = state_root / "neq" / "opentunnel" / layout.profile
        if (
            state_root.resolve(strict=True) != state_root
            or profile_root.resolve(strict=True) != expected_profile
            or profile_root != expected_profile
            or Path(layout.owner_file) != profile_root / "profile_owner.json"
            or Path(layout.config_home) != profile_root / "config"
            or Path(layout.data_home) != profile_root / "data"
            or Path(layout.state_home) != profile_root / "state"
            or Path(layout.runtime_dir) != profile_root / "run"
            or Path(layout.verifier_dir) != profile_root / "verifier"
            or Path(layout.socket_path) != profile_root / "run" / (layout.profile + ".sock")
        ):
            return False
        for directory in (
            state_root,
            state_root / "neq",
            state_root / "neq" / "opentunnel",
            profile_root,
            Path(layout.config_home),
            Path(layout.data_home),
            Path(layout.state_home),
            Path(layout.runtime_dir),
            Path(layout.verifier_dir),
        ):
            metadata = os.lstat(directory)
            if not _is_private_directory(metadata, uid):
                return False
            if directory.resolve(strict=True) != directory:
                return False
        owner_metadata = os.lstat(layout.owner_file)
        if not _is_private_regular_file(owner_metadata, uid):
            return False
        owner_record = _read_json_file(layout.owner_file, owner_metadata)
        return bool(
            isinstance(owner_record, dict)
            and set(owner_record)
            == {"schema", "profile", "created_at", "neq_install_marker", "uid"}
            and owner_record.get("schema") == "neq.opentunnel.profile_owner.v1"
            and owner_record.get("profile") == layout.profile
            and type(owner_record.get("uid")) is int
            and owner_record.get("uid") == uid
            and _valid_timestamp(owner_record.get("created_at"))
            and isinstance(owner_record.get("neq_install_marker"), str)
            and _INSTALL_MARKER_RE.fullmatch(owner_record["neq_install_marker"])
            is not None
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _open_owner_lock(layout: ProfileLayout) -> int | None:
    uid = _current_uid()
    if uid is None:
        return None
    try:
        metadata = os.lstat(layout.owner_file)
        if not _is_private_regular_file(metadata, uid):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(layout.owner_file, flags)
        opened = os.fstat(descriptor)
        if not _is_private_regular_file(opened, uid) or not _same_file(opened, metadata):
            os.close(descriptor)
            return None
        return descriptor
    except OSError:
        return None


def _acquire_profile_lock(descriptor: int, timeout: float) -> bool:
    expires_at = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= expires_at:
                return False
            time.sleep(min(0.025, max(0.0, expires_at - time.monotonic())))
        except OSError:
            return False


def _invoke_runner(
    runner: Callable[[Sequence[str], Mapping[str, str], float], RunResult],
    argv: Sequence[str],
    environment: Mapping[str, str],
    timeout: float,
) -> RunResult:
    try:
        result = runner(tuple(argv), dict(environment), timeout)
    except TimeoutError:
        return RunResult(None, "", timed_out=True)
    except OSError:
        return RunResult(None, "")
    except Exception:
        return RunResult(None, "")
    if (
        not isinstance(result, RunResult)
        or (result.returncode is not None and type(result.returncode) is not int)
        or not isinstance(result.bounded_output, str)
        or len(result.bounded_output) > MAX_COMMAND_OUTPUT_CHARS
        or type(result.output_truncated) is not bool
        or type(result.timed_out) is not bool
    ):
        return RunResult(None, "", output_truncated=True)
    return result


def _parse_status(result: RunResult, parser: StatusParser) -> StatusEvidence | None:
    if (
        result.returncode != 0
        or result.output_truncated
        or result.timed_out
        or len(result.bounded_output) > MAX_COMMAND_OUTPUT_CHARS
    ):
        return None
    try:
        evidence = parser(result.bounded_output)
    except Exception:
        return None
    if (
        not isinstance(evidence, StatusEvidence)
        or type(evidence.identity_confirmed) is not bool
        or type(evidence.daemon_running) is not bool
    ):
        return None
    return evidence


def _command_succeeded(result: RunResult) -> bool:
    return bool(
        result.returncode == 0
        and not result.output_truncated
        and not result.timed_out
    )


def _command_fact(result: RunResult) -> str:
    if result.timed_out:
        return "timeout"
    if result.returncode is None:
        return "unavailable"
    if result.output_truncated:
        return "truncated"
    return "success" if result.returncode == 0 else "failure"


def _deadlines_valid(
    up: float, status: float, down: float, lock: float
) -> bool:
    return all(
        _deadline_valid(value, maximum)
        for value, maximum in (
            (up, MAX_UP_TIMEOUT_SECONDS),
            (status, MAX_STATUS_TIMEOUT_SECONDS),
            (down, MAX_DOWN_TIMEOUT_SECONDS),
            (lock, MAX_LOCK_TIMEOUT_SECONDS),
        )
    )


def _deadline_valid(value: object, maximum: float) -> bool:
    return bool(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
        and value <= maximum
        and (not isinstance(value, float) or (value == value and abs(value) != float("inf")))
    )


def _valid_environment(environment: Mapping[str, str]) -> bool:
    return bool(
        isinstance(environment, Mapping)
        and all(
            isinstance(key, str)
            and isinstance(value, str)
            and "\0" not in key
            and "\0" not in value
            for key, value in environment.items()
        )
    )


def _valid_profile(profile: object) -> bool:
    return isinstance(profile, str) and _PROFILE_RE.fullmatch(profile) is not None


def _expected_install_relative_path(path: Path) -> bool:
    """Require the resolver's versioned runtime layout without following links."""
    if (
        path.name != "opentunnel"
        or path.parent.parent.name != "v0.6.2"
        or path.parent.parent.parent.name != "opentunnel"
        or path.parent.parent.parent.parent.name != "runtime"
        or not path.parent.name
    ):
        return False
    try:
        root = path.parents[4]
        if root.resolve(strict=True) != root:
            return False
        cursor = root
        for component in ("runtime", "opentunnel", "v0.6.2", path.parent.name, "opentunnel"):
            cursor = cursor / component
            metadata = os.lstat(cursor)
            if stat.S_ISLNK(metadata.st_mode):
                return False
        return cursor == path
    except (IndexError, OSError, RuntimeError, ValueError):
        return False


def _profile_argument(argv: Sequence[str]) -> str | None:
    for index, value in enumerate(argv[:-1]):
        if value == "--profile":
            return argv[index + 1]
    return None


def _read_bounded_file(path: Path) -> bytes | None:
    try:
        with path.open("rb") as stream:
            payload = stream.read(_PROCESS_SCAN_BYTES + 1)
    except OSError:
        return None
    return None if len(payload) > _PROCESS_SCAN_BYTES else payload


def _read_proc_uid(path: Path) -> int | None:
    payload = _read_bounded_file(path)
    if payload is None:
        return None
    for line in payload.splitlines():
        if line.startswith(b"Uid:"):
            fields = line.split()
            if len(fields) < 2 or not fields[1].isdigit():
                return None
            return int(fields[1])
    return None


def _unresolvable_on_empty_path(command: str) -> bool:
    if command not in {"launchctl", "systemctl"}:
        return False
    try:
        return shutil.which(command, path="") is None
    except (OSError, TypeError, ValueError):
        return False


def _linux_no_service_manager_proof() -> bool:
    """Prove the host has no systemd manager before using empty-PATH absence."""
    runtime = _path_presence(Path("/run/systemd/system"))
    if runtime is not False:
        return False
    runtime_dirs: list[Path] = []
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        xdg_path = Path(xdg_runtime).expanduser()
        if not xdg_path.is_absolute():
            return False
        runtime_dirs.append(xdg_path)
    uid = _current_uid()
    if uid is None:
        return False
    runtime_dirs.append(Path("/run/user") / str(uid))
    socket_presence: list[bool] = []
    for directory in runtime_dirs:
        presence = _path_presence(directory / "systemd/private")
        if presence is None or presence is True:
            return False
        socket_presence.append(presence)
    if not socket_presence or any(socket_presence):
        return False
    try:
        pid1_comm = Path("/proc/1/comm").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return False
    return pid1_comm.casefold() != "systemd"


def _path_presence(path: Path) -> bool | None:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return True


def _open_private_directory(path: Path, uid: int) -> int | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        return None
    try:
        before = os.lstat(path)
        if not _is_private_directory(before, uid):
            return None
        descriptor = os.open(
            path,
            os.O_RDONLY | nofollow | directory_flag | getattr(os, "O_CLOEXEC", 0),
        )
        after = os.fstat(descriptor)
        if not _is_private_directory(after, uid) or not _same_file(before, after):
            os.close(descriptor)
            return None
        return descriptor
    except OSError:
        return None


def _is_private_directory(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _is_private_regular_file(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size <= MAX_BOOTSTRAP_MARKER_BYTES
    )


def _read_json_file(path: Path, expected_metadata: os.stat_result) -> object | None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        opened = os.fstat(descriptor)
        uid = _current_uid()
        if (
            uid is None
            or not _is_private_regular_file(opened, uid)
            or not _same_file(opened, expected_metadata)
        ):
            return None
        payload = bytearray()
        while len(payload) <= MAX_BOOTSTRAP_MARKER_BYTES:
            chunk = os.read(descriptor, min(512, MAX_BOOTSTRAP_MARKER_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_BOOTSTRAP_MARKER_BYTES:
            return None
    except OSError:
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            return None
    try:
        return json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short_write")
        offset += written


def _current_uid() -> int | None:
    try:
        return os.getuid()
    except (AttributeError, OSError):
        return None


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non_finite_number")


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _bool_fact(value: bool) -> str:
    return "true" if value else "false"


def _result(
    state: BootstrapState, reason: str, facts: Sequence[str] = ()
) -> BootstrapResult:
    bounded_facts = tuple(str(item)[:128] for item in facts[:MAX_RESULT_FACTS])
    return BootstrapResult(state=state, reason=reason[:40], facts=bounded_facts)
