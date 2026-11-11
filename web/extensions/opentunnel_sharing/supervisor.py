# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Own one foreground OpenTunnel process without retaining raw output."""

from __future__ import annotations

import math
import os
import platform
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Literal, Mapping, Protocol, Sequence

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing import native_process_info as process_info
from web.extensions.opentunnel_sharing.profile_state import (
    ProfileLayout,
    companion_environment,
)

MAX_STARTUP_DEADLINE_SECONDS = 120.0
MAX_STOP_DEADLINE_SECONDS = 30.0
FAILURE_CLEANUP_DEADLINE_SECONDS = 2.0
OUTPUT_BUFFER_BYTES = 8 * 1024
OUTPUT_READ_BYTES = 4096
OUTPUT_DRAIN_POLL_SECONDS = 0.05
MAX_DIAGNOSTIC_COUNTER = (1 << 31) - 1
MAX_IDENTITY_FIELD_BYTES = 64 * 1024

SupervisorState = Literal["starting", "running", "exited", "failed", "stopped"]
ReasonCode = Literal[
    "launch_failed",
    "early_exit",
    "startup_timeout",
    "not_ready",
    "stop_timeout",
    "ownership_mismatch",
]
ReadinessResult = bool | Literal["ready", "pending", "not_ready"]
ReadinessProbe = Callable[[], ReadinessResult]


@dataclass(frozen=True, slots=True, repr=False)
class Identity:
    """Positive live-process facts, excluding argv/environment from repr."""

    pid: int
    creation_token: str
    executable_path: str
    argv: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    command_line: str = ""
    uid: int | None = None
    start_time: float | None = None
    legacy_creation_token: str | None = None

    def __repr__(self) -> str:
        return "Identity(pid=%r, uid=%r, profile_evidence=%r)" % (
            self.pid,
            self.uid,
            bool(self.argv or self.command_line),
        )


IdentityProbe = Callable[[int], Identity | None]


class CompanionProcess(Protocol):
    """Small process adapter; terminate and kill signal its private group."""

    @property
    def pid(self) -> int: ...

    @property
    def output_reader(self) -> BinaryIO | None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ProcessFactory(Protocol):
    """Injected seam for starting a process with the exact child environment."""

    def __call__(
        self, argv: Sequence[str], *, env: Mapping[str, str]
    ) -> CompanionProcess: ...


class _PopenCompanionProcess:
    """Adapt Popen to process-group signaling and the narrow protocol."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def output_reader(self) -> BinaryIO | None:
        return self._process.stdout

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def terminate(self) -> None:
        if os.getpgid(self._process.pid) != self._process.pid:
            raise ProcessLookupError("owned_process_group_mismatch")
        os.killpg(self._process.pid, signal.SIGTERM)

    def kill(self) -> None:
        if os.getpgid(self._process.pid) != self._process.pid:
            raise ProcessLookupError("owned_process_group_mismatch")
        os.killpg(self._process.pid, signal.SIGKILL)


def default_process_factory(
    argv: Sequence[str], *, env: Mapping[str, str]
) -> CompanionProcess:
    """Launch a new-session foreground child with no inherited environment."""
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=dict(env),
        start_new_session=True,
        close_fds=True,
        bufsize=0,
    )
    return _PopenCompanionProcess(process)


# TABLETOP MODE: Ownership probes use native process facts and fail closed.
def probe_process_identity(pid: int) -> Identity | None:
    """Return native executable, creation, argv, UID, and profile evidence."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        info = process_info.lookup(pid)
    except (OSError, RuntimeError, TypeError, ValueError, OverflowError):
        return None
    if info is None:
        return None
    if info.executable is None:
        return None
    environment: tuple[tuple[str, str], ...] = ()
    if platform.system() == "Linux":
        try:
            environment = _linux_process_environment(pid)
        except OSError:
            return None
        if environment is None:
            return None
    command_line = " ".join(info.argv)
    if len(command_line) > MAX_IDENTITY_FIELD_BYTES:
        return None
    return Identity(
        pid=info.pid,
        creation_token=process_info.creation_token(info),
        executable_path=info.executable,
        argv=info.argv,
        environment=environment,
        command_line=command_line,
        uid=info.uid,
        start_time=info.start_time,
        legacy_creation_token=process_info.legacy_creation_token(info),
    )


class OwnedCompanion:
    """Synchronous owner for one foreground companion and its bounded output."""

    def __init__(
        self,
        companion: CompanionResolution,
        layout: ProfileLayout,
        readiness_probe: ReadinessProbe,
        *,
        process_factory: ProcessFactory | None = None,
        identity_probe: IdentityProbe | None = None,
    ) -> None:
        if companion.state != "resolved" or companion.path is None:
            raise ValueError("companion_must_be_resolved")
        if not isinstance(layout, ProfileLayout):
            raise TypeError("profile_layout_required")
        if not callable(readiness_probe):
            raise TypeError("readiness_probe_required")
        try:
            binary_path = Path(companion.path).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("companion_path_unavailable") from None
        if not binary_path.is_file():
            raise ValueError("companion_path_not_file")

        self._binary_path = binary_path
        self._layout = layout
        self._argv = (str(binary_path), "serve", "--profile", layout.profile)
        self._environment = companion_environment(layout)
        self._readiness_probe = readiness_probe
        self._process_factory = process_factory or default_process_factory
        self._identity_probe = identity_probe or probe_process_identity

        self._process: CompanionProcess | None = None
        self._pid: int | None = None
        self._identity_token: str | None = None
        self._state: SupervisorState = "stopped"
        self._reason_code: ReasonCode | None = None
        self._exit_code_bucket: Literal["success", "failure", "signal"] | None = None
        self._reaped = True
        self._drain_thread: threading.Thread | None = None
        self._drain_joined = True
        self._output_buffer = bytearray()
        self._output_lock = threading.Lock()
        self._bytes_drained = 0
        self._lines_drained = 0
        self._ever_started = False

    @property
    def state(self) -> SupervisorState:
        """Return bounded state and notice an unexpected foreground exit."""
        self._refresh_exit_state()
        return self._state

    # TABLETOP MODE: Expose the fixed executable/profile for owned status probes.
    @property
    def executable_path(self) -> Path:
        """Return the resolved executable path for bounded profile status probes."""
        return self._binary_path

    @property
    def profile_layout(self) -> ProfileLayout:
        """Return the validated dedicated profile used by this child."""
        return self._layout

    @property
    def reason_code(self) -> ReasonCode | None:
        self._refresh_exit_state()
        return self._reason_code

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, deadline: float) -> SupervisorState:
        """Launch and wait for readiness within a bounded duration.

        The injected readiness probe must itself be non-blocking or bounded; its
        result is never accepted after the startup deadline.
        """
        _validate_deadline(deadline, MAX_STARTUP_DEADLINE_SECONDS)
        if self._ever_started:
            return self.state
        self._ever_started = True
        expires_at = time.monotonic() + deadline
        self._state = "starting"
        self._reason_code = None
        self._exit_code_bucket = None

        try:
            process = self._process_factory(self._argv, env=dict(self._environment))
            pid = process.pid
            if type(pid) is not int or pid <= 0:
                raise ValueError("process_pid_invalid")
        except Exception:
            self._state = "failed"
            self._reason_code = "launch_failed"
            self._reaped = True
            return self._state

        self._process = process
        self._pid = pid
        self._reaped = False
        if not self._start_output_drain(process.output_reader):
            self._fail_start("launch_failed")
            return self._state

        initial_exit = self._poll()
        if initial_exit is not None:
            self._exit_code_bucket = _bucket_exit_code(initial_exit)
            self._fail_start("early_exit")
            return self._state

        initial_identity = self._probe_identity()
        if not self._identity_matches(initial_identity, expected_token=None):
            self._fail_without_signalling("ownership_mismatch")
            return self._state
        assert initial_identity is not None
        self._identity_token = initial_identity.creation_token

        if time.monotonic() >= expires_at:
            self._fail_start("startup_timeout")
            return self._state
        while True:
            exit_code = self._poll()
            if exit_code is not None:
                self._exit_code_bucket = _bucket_exit_code(exit_code)
                self._fail_start("early_exit")
                return self._state
            try:
                readiness = self._readiness_probe()
            except Exception:
                readiness = "not_ready"
            if time.monotonic() > expires_at:
                self._fail_start("startup_timeout")
                return self._state
            if readiness is True or readiness == "ready":
                exit_code = self._poll()
                if exit_code is not None:
                    self._exit_code_bucket = _bucket_exit_code(exit_code)
                    self._fail_start("early_exit")
                    return self._state
                self._state = "running"
                return self._state
            if readiness == "not_ready":
                self._fail_start("not_ready")
                return self._state
            if readiness is not False and readiness != "pending":
                self._fail_start("not_ready")
                return self._state
            remaining = expires_at - time.monotonic()
            if remaining <= 0:
                self._fail_start("startup_timeout")
                return self._state
            time.sleep(min(OUTPUT_DRAIN_POLL_SECONDS, remaining))

    def stop(self, deadline: float) -> bool:
        """Stop only a positively identified child; return whether it was reaped."""
        _validate_deadline(deadline, MAX_STOP_DEADLINE_SECONDS)
        self._refresh_exit_state()
        if self._process is None:
            return True
        if self._reaped and self._drain_joined:
            return True
        return self._stop_owned_process(
            deadline,
            preserve_failure=self._state == "failed",
        )

    def diagnostics(self) -> dict[str, object]:
        """Return bounded lifecycle metadata and counters, never raw output."""
        state = self.state
        with self._output_lock:
            bytes_drained = self._bytes_drained
            lines_drained = self._lines_drained
        return {
            "state": state,
            "reason_code": self._reason_code,
            "exit_code_bucket": self._exit_code_bucket,
            "bytes_drained": bytes_drained,
            "lines_drained": lines_drained,
        }

    def _probe_identity(self) -> Identity | None:
        if self._pid is None:
            return None
        try:
            return self._identity_probe(self._pid)
        except Exception:
            return None

    def _identity_matches(
        self, identity: Identity | None, *, expected_token: str | None
    ) -> bool:
        if not isinstance(identity, Identity):
            return False
        if (
            type(identity.pid) is not int
            or self._pid is None
            or identity.pid != self._pid
            or type(identity.uid) is not int
            or identity.uid != os.getuid()
            or not isinstance(identity.creation_token, str)
            or not identity.creation_token
            or len(identity.creation_token) > 128
            or not isinstance(identity.executable_path, str)
            or not isinstance(identity.argv, tuple)
            or any(not isinstance(argument, str) for argument in identity.argv)
            or not isinstance(identity.environment, tuple)
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
                for item in identity.environment
            )
            or not isinstance(identity.command_line, str)
        ):
            return False
        if expected_token is not None and identity.creation_token != expected_token:
            return False
        try:
            observed_executable = Path(identity.executable_path).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        if observed_executable != self._binary_path:
            return False
        try:
            identity_environment = dict(identity.environment)
        except (TypeError, ValueError):
            return False
        environment_matches = bool(identity.environment) and (
            len(identity_environment) == len(identity.environment)
            and identity_environment == self._environment
        )
        arguments_match = identity.argv == self._argv
        command_line_matches = identity.command_line == " ".join(self._argv)
        profile_marker_matches = arguments_match or command_line_matches
        if identity.environment:
            return environment_matches and profile_marker_matches
        return command_line_matches

    def _start_output_drain(self, output_reader: BinaryIO | None) -> bool:
        if output_reader is None:
            return False
        thread = threading.Thread(
            target=self._drain_output,
            args=(output_reader,),
            name="opentunnel-output-%d" % self._pid,
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            return False
        self._drain_thread = thread
        self._drain_joined = False
        return True

    def _drain_output(self, output_reader: BinaryIO) -> None:
        try:
            while True:
                chunk = output_reader.read(OUTPUT_READ_BYTES)
                if not chunk or not isinstance(chunk, bytes):
                    return
                with self._output_lock:
                    self._bytes_drained = min(
                        MAX_DIAGNOSTIC_COUNTER,
                        self._bytes_drained + len(chunk),
                    )
                    self._lines_drained = min(
                        MAX_DIAGNOSTIC_COUNTER,
                        self._lines_drained + chunk.count(b"\n"),
                    )
                    if len(chunk) >= OUTPUT_BUFFER_BYTES:
                        self._output_buffer[:] = chunk[-OUTPUT_BUFFER_BYTES:]
                    else:
                        excess = max(
                            0,
                            len(self._output_buffer)
                            + len(chunk)
                            - OUTPUT_BUFFER_BYTES,
                        )
                        if excess:
                            del self._output_buffer[:excess]
                        self._output_buffer.extend(chunk)
        except (OSError, ValueError):
            return
        finally:
            try:
                output_reader.close()
            except (OSError, ValueError):
                pass

    def _fail_without_signalling(self, reason: ReasonCode) -> None:
        self._state = "failed"
        self._reason_code = reason
        self._reaped = self._process is None

    def _fail_start(self, reason: ReasonCode) -> None:
        self._state = "failed"
        self._reason_code = reason
        if self._process is None:
            self._reaped = True
            return
        if not self._stop_owned_process(
            FAILURE_CLEANUP_DEADLINE_SECONDS,
            preserve_failure=True,
        ) and self._reason_code != "ownership_mismatch":
            self._reason_code = "stop_timeout"

    def _stop_owned_process(self, deadline: float, *, preserve_failure: bool) -> bool:
        process = self._process
        if process is None:
            self._reaped = True
            return True
        expires_at = time.monotonic() + deadline

        exit_code = self._poll()
        if exit_code is None:
            if not self._verify_ownership_before_signal():
                return False
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            except OSError:
                self._set_stop_failure(preserve_failure)
                return self._reaped

            remaining = max(0.0, expires_at - time.monotonic())
            graceful_wait = min(remaining * 0.5, 2.0)
            completed = self._wait_and_reap(graceful_wait)
            if not completed:
                exit_code = self._poll()
                if exit_code is None:
                    if time.monotonic() >= expires_at:
                        self._set_stop_failure(preserve_failure)
                        return self._reaped
                    if not self._verify_ownership_before_signal():
                        return False
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    except OSError:
                        self._set_stop_failure(preserve_failure)
                        return self._reaped
                    remaining = max(0.0, expires_at - time.monotonic())
                    completed = self._wait_and_reap(remaining)
                else:
                    completed = self._wait_and_reap(
                        max(0.0, expires_at - time.monotonic())
                    )
        else:
            self._exit_code_bucket = _bucket_exit_code(exit_code)
            completed = self._wait_and_reap(
                max(0.0, expires_at - time.monotonic())
            )

        if not completed:
            self._set_stop_failure(preserve_failure)
            return self._reaped
        self._join_drain(max(0.0, expires_at - time.monotonic()))
        if not self._drain_joined:
            self._set_stop_failure(preserve_failure)
            return self._reaped
        if not preserve_failure:
            self._state = "stopped"
            self._reason_code = None
        return self._reaped

    def _verify_ownership_before_signal(self) -> bool:
        identity = self._probe_identity()
        if not self._identity_matches(identity, expected_token=self._identity_token):
            self._state = "failed"
            self._reason_code = "ownership_mismatch"
            return False
        return True

    def _wait_and_reap(self, timeout: float) -> bool:
        process = self._process
        if process is None:
            self._reaped = True
            return True
        try:
            exit_code = process.wait(timeout=max(0.0, timeout))
        except (subprocess.TimeoutExpired, TimeoutError):
            return False
        except OSError:
            return False
        self._exit_code_bucket = _bucket_exit_code(exit_code)
        self._reaped = True
        return True

    def _join_drain(self, timeout: float) -> None:
        thread = self._drain_thread
        if thread is None:
            self._drain_joined = True
            return
        thread.join(timeout=max(0.0, timeout))
        self._drain_joined = not thread.is_alive()

    def _set_stop_failure(self, preserve_failure: bool) -> None:
        self._state = "failed"
        if not preserve_failure or self._reason_code is None:
            self._reason_code = "stop_timeout"

    def _poll(self) -> int | None:
        process = self._process
        if process is None:
            return None
        try:
            return process.poll()
        except OSError:
            return None

    def _refresh_exit_state(self) -> None:
        if self._state != "running":
            return
        exit_code = self._poll()
        if exit_code is None:
            return
        self._state = "exited"
        self._exit_code_bucket = _bucket_exit_code(exit_code)
        self._wait_and_reap(0.0)
        self._join_drain(0.0)


def _validate_deadline(deadline: float, maximum: float) -> None:
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise ValueError("deadline_out_of_range")
    if (
        (isinstance(deadline, float) and not math.isfinite(deadline))
        or deadline <= 0
        or deadline > maximum
    ):
        raise ValueError("deadline_out_of_range")


def _bucket_exit_code(
    exit_code: int | None,
) -> Literal["success", "failure", "signal"] | None:
    if type(exit_code) is not int:
        return None
    if exit_code == 0:
        return "success"
    return "signal" if exit_code < 0 else "failure"


def _linux_process_environment(pid: int) -> tuple[tuple[str, str], ...] | None:
    environment_payload = _read_bounded(
        Path("/proc") / str(pid) / "environ", MAX_IDENTITY_FIELD_BYTES
    )
    if environment_payload is None:
        return None
    environment: list[tuple[str, str]] = []
    for item in environment_payload.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment.append((os.fsdecode(key), os.fsdecode(value)))
    return tuple(environment)


def _read_bounded(path: Path, maximum: int) -> bytes | None:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    return None if len(value) > maximum else value
