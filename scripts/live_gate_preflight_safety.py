# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fail-closed, opt-in network guard and child-environment builder.

The guard is intended for provider-free live-gate preflight processes only. It
permits numeric loopback sockets and blocks DNS names other than a synthetic
localhost mapping. It does not start a host, listener, or sandbox.
"""

from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Iterator, Sequence


ENABLE_GUARD_ENV = "NEQ_PREFLIGHT_NETWORK_GUARD"
ACTIVE_GUARD_ENV = "NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE"
SANITIZED_ENV = "NEQ_PREFLIGHT_ENV_SANITIZED"
STARTUP_GUARD_ENV = "NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE"
REQUIRE_STARTUP_GUARD_ENV = "NEQ_PREFLIGHT_STARTUP_GUARD_REQUIRED"
CONNECT_CANARY_ENV = "NEQ_PREFLIGHT_CONNECT_CANARY_DENIED"
SUBPROCESS_CANARY_ENV = "NEQ_PREFLIGHT_SUBPROCESS_CANARY_DENIED"
CANARY_REPORT_ENV = "NEQ_PREFLIGHT_STARTUP_CANARY_REPORT"
PROCESS_ROLE_ENV = "NEQ_PREFLIGHT_PROCESS_ROLE"
GUARD_DIRECTORY_ENV = "NEQ_PREFLIGHT_GUARD_DIRECTORY"
PROJECT_ROOT_ENV = "NEQ_PREFLIGHT_PROJECT_ROOT"
EXPECTED_PYTHON_ENV = "NEQ_PREFLIGHT_EXPECTED_PYTHON"
EXPECTED_PREFIX_ENV = "NEQ_PREFLIGHT_EXPECTED_PREFIX"
CANARY_SIGNAL_FD = 198
CANARY_REPORT_FD = 199
CANARY_SIGNAL = b"NEQ_PREFLIGHT_SITE_STARTUP_CANARY_V1\n"
GUARD_DIRECTORY = Path("scripts/live_gate_preflight_guard")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESS_ROLES = frozenset(("parent", "host"))
_SECRET_ENV_NAME = re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)
_PROXY_ENV_NAME = re.compile(r"(?:^|_)PROXY$", re.IGNORECASE)
_SAFE_ENV_NAMES = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONHASHSEED",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
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
_RUNTIME_INJECTED_ENV_NAMES = ("LC_CTYPE", "__CF_USER_TEXT_ENCODING")

class NetworkGuardError(PermissionError):
    """Raised before a non-loopback network or DNS operation is attempted."""


class SafetyConfigurationError(ValueError):
    """Raised when the isolated preflight environment is not safe to use."""


_GUARD_INSTALLED = False
_SUBPROCESS_GUARD_INSTALLED = False
_ORIGINAL_SOCKET_METHODS: dict[str, Any] = {}
_ORIGINAL_DNS_FUNCTIONS: dict[str, Any] = {}
_ORIGINAL_POPEN: Any = None
_GUARDED_SOCKET_METHODS: dict[str, Any] = {}
_GUARDED_DNS_FUNCTIONS: dict[str, Any] = {}
_SUBPROCESS_AUTHORIZATION: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("neq_preflight_subprocess_authorization", default=None)
)


class _GuardedPopen(subprocess.Popen):
    """Reject every child launch unless an exact, one-use authorization exists."""

    def __init__(self, args: Any, *positional: Any, **kwargs: Any) -> None:
        require_guard_active()
        authorization = _SUBPROCESS_AUTHORIZATION.get()
        if (
            authorization is None
            or authorization.get("used") is True
            or _command_tuple(args) != authorization.get("command")
            or _path_text(kwargs.get("cwd")) != authorization.get("cwd")
            or kwargs.get("env") != authorization.get("env")
            or tuple(kwargs.get("pass_fds", ())) != authorization.get("pass_fds")
            or kwargs.get("close_fds", True) is not authorization.get("close_fds")
            or kwargs.get("shell", False) is not False
            or kwargs.get("executable") is not None
            or kwargs.get("preexec_fn") is not None
        ):
            raise NetworkGuardError("unguarded or mismatched subprocess launch is denied")
        authorization["used"] = True
        super().__init__(args, *positional, **kwargs)


def build_guarded_environment(
    source_environment: Mapping[str, str] | None = None,
    *,
    project_root: str | Path = PROJECT_ROOT,
    process_role: str = "parent",
    interpreter_root: str | Path | None = None,
) -> dict[str, str]:
    """Build a minimal environment without copying secrets or proxy values.

    Only a small allowlist of non-secret values is copied. Secret-looking
    variable names are retained as blank values, and all proxy variables are
    blanked without reading their values. The dedicated guard directory is the
    first PYTHONPATH entry, followed by the repository root.
    """
    root = Path(project_root).resolve(strict=True)
    runtime_root = (
        root if interpreter_root is None else Path(interpreter_root).resolve(strict=True)
    )
    guard_directory = root / GUARD_DIRECTORY
    if guard_directory.is_symlink() or not guard_directory.is_dir():
        raise SafetyConfigurationError("dedicated preflight guard directory is unavailable")
    if process_role not in PROCESS_ROLES:
        raise SafetyConfigurationError("preflight process role is invalid")
    source = os.environ if source_environment is None else source_environment
    result: dict[str, str] = {}
    for name in _SAFE_ENV_NAMES:
        if name in source:
            result[name] = str(source[name])
    result["PYTHONPATH"] = os.pathsep.join((str(guard_directory), str(root)))
    result["NEQ_OPEN_BROWSER"] = "0"
    result["TMPDIR"] = "tmp"
    result["TEMP"] = "tmp"
    result["TMP"] = "tmp"
    result[ENABLE_GUARD_ENV] = "1"
    result[REQUIRE_STARTUP_GUARD_ENV] = "1"
    result[GUARD_DIRECTORY_ENV] = str(guard_directory)
    result[PROJECT_ROOT_ENV] = str(root)
    result[EXPECTED_PYTHON_ENV] = str(runtime_root / ".venv" / "bin" / "python")
    result[EXPECTED_PREFIX_ENV] = str(runtime_root / ".venv")
    result[PROCESS_ROLE_ENV] = process_role

    for name in source:
        if _SECRET_ENV_NAME.search(name) or name in _KNOWN_PROVIDER_KEYS:
            result[name] = ""
        if _PROXY_ENV_NAME.search(name):
            result[name] = ""
    for name in _KNOWN_PROVIDER_KEYS:
        result[name] = ""
    return result


def sanitize_current_environment() -> None:
    """Blank secret and proxy variables in-place without reading their values."""
    for name in tuple(os.environ):
        if _SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name):
            os.environ[name] = ""
    for name in _KNOWN_PROVIDER_KEYS:
        os.environ[name] = ""
    os.environ[SANITIZED_ENV] = "1"


def sanitized_environment_snapshot(
    source_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy environment identity while never reading secret/proxy values."""
    source = os.environ if source_environment is None else source_environment
    snapshot: dict[str, str] = {}
    for name in source:
        if _SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name):
            snapshot[name] = ""
        else:
            snapshot[name] = str(source[name])
    for name in _KNOWN_PROVIDER_KEYS:
        snapshot[name] = ""
    return snapshot


def activate_preflight_safety() -> None:
    """Sanitize this process and install the deny guard, idempotently."""
    if _GUARD_INSTALLED:
        require_guard_active()
        install_subprocess_deny_guard()
        return
    os.environ.pop(ACTIVE_GUARD_ENV, None)
    os.environ.pop(SANITIZED_ENV, None)
    sanitize_current_environment()
    install_network_deny_guard()
    install_subprocess_deny_guard()


def validate_sandbox_config_location(
    config_path: str | Path,
    *,
    sandbox_root: str | Path,
    project_root: str | Path,
) -> Path:
    """Require the config location to be the copied sandbox config, not config.py.

    This path-only check reads no configuration bytes. The later launcher must
    additionally require the copied file to exist and reject symlinks.
    """
    project = Path(project_root).resolve(strict=True)
    sandbox = Path(sandbox_root)
    config = Path(config_path)
    if sandbox.is_absolute() or config.is_absolute():
        raise SafetyConfigurationError("sandbox config paths must be project-relative")
    if ".." in sandbox.parts or ".." in config.parts:
        raise SafetyConfigurationError("sandbox config path traversal is forbidden")
    if sandbox != Path("tmp/combat_capture"):
        raise SafetyConfigurationError("sandbox root must be tmp/combat_capture")
    if config != sandbox / "config.py":
        raise SafetyConfigurationError("config path must be the copied sandbox config.py")

    tmp_root = project / "tmp"
    if tmp_root.is_symlink():
        raise SafetyConfigurationError("project tmp/ must not be a symlink")
    expected_root = project / sandbox
    expected_config = project / config
    if expected_root.is_symlink() or expected_config.is_symlink():
        raise SafetyConfigurationError("sandbox config path must not traverse symlinks")
    resolved_root = expected_root.resolve(strict=False)
    try:
        resolved_root.relative_to((project / "tmp").resolve(strict=False))
    except ValueError as exc:
        raise SafetyConfigurationError("sandbox root escapes project tmp/") from exc
    resolved_config = (project / config).resolve(strict=False)
    if resolved_config == project / "config.py":
        raise SafetyConfigurationError("real project config.py is forbidden")
    try:
        resolved_config.relative_to(resolved_root)
    except ValueError as exc:
        raise SafetyConfigurationError("sandbox config escapes the isolated copy") from exc
    return resolved_config


def validate_guarded_sandbox_path(
    sandbox_root: str | Path,
    *,
    project_root: str | Path,
) -> tuple[Path, Path]:
    """Validate a sandbox identity without modifying the capture copy."""
    project = Path(project_root).resolve(strict=True)
    raw_root = PurePosixPath(str(sandbox_root))
    if (
        raw_root.is_absolute()
        or ".." in raw_root.parts
        or "\\" in str(sandbox_root)
        or len(raw_root.parts) < 2
        or raw_root.parts[0] != "tmp"
    ):
        raise SafetyConfigurationError("sandbox root must be project-relative under tmp/")

    if raw_root.parts[0] != "tmp":
        raise SafetyConfigurationError("sandbox root must stay below project tmp/")
    guard_directory = project / GUARD_DIRECTORY
    if guard_directory.is_symlink() or not guard_directory.is_dir():
        raise SafetyConfigurationError("dedicated preflight guard directory is unavailable")
    return (GUARD_DIRECTORY / "sitecustomize.py", Path("scripts") / "sitecustomize.py")


def build_guarded_sandbox_environment(
    sandbox_root: str | Path,
    *,
    project_root: str | Path,
    source_environment: Mapping[str, str] | None = None,
    process_role: str = "host",
    interpreter_root: str | Path | None = None,
) -> dict[str, str]:
    """Build a guarded environment without touching any sandbox files."""
    validate_guarded_sandbox_path(sandbox_root, project_root=project_root)
    return build_guarded_environment(
        source_environment,
        project_root=project_root,
        process_role=process_role,
        interpreter_root=interpreter_root,
    )


def expected_guarded_pythonpath(project_root: str | Path = PROJECT_ROOT) -> str:
    """Return the exact dedicated-guard-then-repository-root path order."""
    root = Path(project_root).resolve(strict=True)
    return os.pathsep.join((str(root / GUARD_DIRECTORY), str(root)))


def install_subprocess_deny_guard() -> None:
    """Patch subprocess.Popen so only exact one-use authorized launches proceed."""
    global _SUBPROCESS_GUARD_INSTALLED, _ORIGINAL_POPEN
    if _SUBPROCESS_GUARD_INSTALLED:
        if subprocess.Popen is not _GuardedPopen:
            raise NetworkGuardError("preflight subprocess deny guard was replaced")
        return
    if subprocess.Popen is _GuardedPopen:
        _SUBPROCESS_GUARD_INSTALLED = True
        return
    _ORIGINAL_POPEN = subprocess.Popen
    subprocess.Popen = _GuardedPopen  # type: ignore[assignment]
    _SUBPROCESS_GUARD_INSTALLED = True


@contextmanager
def authorize_subprocess_launch(
    command: Sequence[str],
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
    pass_fds: Sequence[int] = (),
    close_fds: bool = True,
) -> Iterator[None]:
    """Authorize one exact Popen call, including inherited descriptors."""
    require_guard_active()
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")
    command_tuple = _command_tuple(command)
    if command_tuple is None:
        raise NetworkGuardError("authorized subprocess command is invalid")
    descriptor_tuple = tuple(pass_fds)
    if (
        any(type(descriptor) is not int or descriptor < 0 for descriptor in descriptor_tuple)
        or len(set(descriptor_tuple)) != len(descriptor_tuple)
        or type(close_fds) is not bool
        or (descriptor_tuple and not close_fds)
        or (descriptor_tuple and os.name != "posix")
    ):
        raise NetworkGuardError("authorized subprocess descriptor policy is invalid")
    authorization = {
        "command": command_tuple,
        "cwd": _path_text(cwd),
        "env": None if env is None else dict(env),
        "pass_fds": descriptor_tuple,
        "close_fds": close_fds,
        "used": False,
    }
    if _SUBPROCESS_AUTHORIZATION.get() is not None:
        raise NetworkGuardError("nested subprocess authorization is denied")
    token = _SUBPROCESS_AUTHORIZATION.set(authorization)
    try:
        yield
        if authorization.get("used") is not True:
            raise NetworkGuardError("authorized subprocess launch was not consumed")
    finally:
        _SUBPROCESS_AUTHORIZATION.reset(token)


def run_guarded_subprocess(
    command: Sequence[str],
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one locally authorized command through the guarded Popen boundary."""
    selected_env = None if env is None else dict(env)
    with authorize_subprocess_launch(command, cwd=cwd, env=selected_env):
        return subprocess.run(list(command), cwd=cwd, env=selected_env, **kwargs)


def run_startup_canaries(
    *,
    process_role: str | None = None,
    command: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Prove socket and exact-invocation subprocess denial before program entry."""
    require_guard_active()
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")
    selected_command = list(
        command if command is not None else current_invocation_command()
    )
    selected_cwd = os.fspath(cwd if cwd is not None else Path.cwd())
    selected_env = (
        sanitized_environment_snapshot() if env is None else dict(env)
    )
    if (
        not selected_command
        or any(
            not isinstance(part, str)
            or not part
            or _SECRET_ENV_NAME.search(part)
            for part in selected_command
        )
    ):
        raise NetworkGuardError("startup canary command identity is invalid")
    role = process_role or os.environ.get(PROCESS_ROLE_ENV, "")
    if role not in PROCESS_ROLES:
        raise NetworkGuardError("startup canary process role is invalid")

    try:
        socket.socket.connect(_CanarySocket(), ("192.0.2.1", 8360))
    except NetworkGuardError:
        connect_denied = True
    else:
        connect_denied = False

    subprocess_canary_command = [sys.executable, "-c", "pass"]
    subprocess_canary_environment = {
        "PATH": selected_env.get("PATH", ""),
        "PYTHONPATH": "",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        canary_child = subprocess.Popen(
            subprocess_canary_command,
            cwd=selected_cwd,
            env=subprocess_canary_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except NetworkGuardError:
        subprocess_denied = True
    else:
        subprocess_denied = False
        try:
            canary_child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            canary_child.kill()
            canary_child.wait(timeout=2.0)
        raise NetworkGuardError("preflight subprocess deny guard allowed its canary")
    if not connect_denied or not subprocess_denied:
        raise NetworkGuardError("preflight startup canary did not fail closed")

    interpreter = {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }
    if (
        interpreter["executable"] != os.environ.get(EXPECTED_PYTHON_ENV)
        or interpreter["prefix"] != os.environ.get(EXPECTED_PREFIX_ENV)
        or interpreter["prefix"] == interpreter["base_prefix"]
    ):
        raise NetworkGuardError("repository virtual-environment identity is invalid")
    command_digest = hashlib.sha256(
        json.dumps(selected_command, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    environment_digest = _startup_environment_digest(selected_env)
    return {
        "process_role": role,
        "pid": os.getpid(),
        "startup_observed_at_ns": time.time_ns(),
        "command": selected_command,
        "command_sha256": command_digest,
        "environment_sha256": environment_digest,
        "working_directory": selected_cwd,
        "guard_active": True,
        "non_loopback_connect_denied": connect_denied,
        "subprocess_launch_denied": subprocess_denied,
        "interpreter": interpreter,
    }


def run_startup_process_canary(
    *,
    command: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Run an exact-invocation clone that exits from dedicated sitecustomize.

    The canary signal and report use inherited file descriptors so the command,
    environment, and working directory remain identical to the eventual launch.
    """
    require_startup_guard_active()
    if os.name != "posix":
        raise NetworkGuardError("sitecustomize canary descriptors require POSIX")
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")

    selected_command = list(command if command is not None else current_invocation_command())
    selected_cwd = os.fspath(cwd if cwd is not None else Path.cwd())
    selected_env = (
        _startup_environment_snapshot() if env is None else dict(env)
    )
    _validate_canary_launch(selected_command, selected_cwd, selected_env)

    signal_read = signal_write = report_read = report_write = -1
    process: subprocess.Popen[bytes] | None = None
    fixed_fds: list[int] = []
    try:
        for descriptor in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            raise NetworkGuardError("reserved startup-canary descriptor is already open")

        signal_read, signal_write = os.pipe()
        report_read, report_write = os.pipe()
        signal_read = _move_from_reserved_descriptor(signal_read)
        signal_write = _move_from_reserved_descriptor(signal_write)
        report_read = _move_from_reserved_descriptor(report_read)
        report_write = _move_from_reserved_descriptor(report_write)
        os.dup2(signal_read, CANARY_SIGNAL_FD, inheritable=True)
        fixed_fds.append(CANARY_SIGNAL_FD)
        os.dup2(report_write, CANARY_REPORT_FD, inheritable=True)
        fixed_fds.append(CANARY_REPORT_FD)
        os.close(signal_read)
        signal_read = -1
        os.close(report_write)
        report_write = -1
        _write_all(signal_write, CANARY_SIGNAL)
        os.close(signal_write)
        signal_write = -1

        inherited = (CANARY_SIGNAL_FD, CANARY_REPORT_FD)
        with authorize_subprocess_launch(
            selected_command,
            cwd=selected_cwd,
            env=selected_env,
            pass_fds=inherited,
            close_fds=True,
        ):
            process = subprocess.Popen(
                selected_command,
                cwd=selected_cwd,
                env=selected_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=inherited,
                start_new_session=True,
            )
        for descriptor in fixed_fds:
            os.close(descriptor)
        fixed_fds.clear()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(process)
            raise NetworkGuardError("sitecustomize startup canary did not exit") from exc

        raw_report = _read_canary_report(report_read)
        if process.returncode != 0:
            raise NetworkGuardError("sitecustomize startup canary failed")
        try:
            report = json.loads(raw_report.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise NetworkGuardError("sitecustomize startup canary report is invalid") from exc
        _validate_canary_report(
            report,
            process_role=selected_env.get(PROCESS_ROLE_ENV),
            command=selected_command,
            cwd=selected_cwd,
            env=selected_env,
            process_id=process.pid,
        )
        return dict(report)
    except OSError as exc:
        raise NetworkGuardError("sitecustomize startup canary launch failed") from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        for descriptor in fixed_fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for descriptor in (signal_read, signal_write, report_read, report_write):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _startup_environment_snapshot() -> dict[str, str]:
    module = sys.modules.get("scripts.sitecustomize")
    saved = getattr(module, "_STARTUP_ENVIRONMENT", None)
    if not isinstance(saved, Mapping):
        raise NetworkGuardError("preflight startup environment snapshot is unavailable")
    return {str(name): str(value) for name, value in saved.items()}


def _validate_canary_launch(
    command: Sequence[str], cwd: str, env: Mapping[str, str]
) -> None:
    role = env.get(PROCESS_ROLE_ENV)
    expected_python = env.get(EXPECTED_PYTHON_ENV)
    expected_prefix = env.get(EXPECTED_PREFIX_ENV)
    project_root = env.get(PROJECT_ROOT_ENV)
    guard_directory = env.get(GUARD_DIRECTORY_ENV)
    pythonpath = env.get("PYTHONPATH", "")
    try:
        resolved_root = Path(project_root or "").resolve(strict=True)
        resolved_cwd = Path(cwd).resolve(strict=True)
        resolved_cwd.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError, TypeError):
        raise NetworkGuardError("startup canary launch identity is invalid") from None
    if (
        role not in PROCESS_ROLES
        or not isinstance(expected_python, str)
        or not expected_python
        or not isinstance(expected_prefix, str)
        or not expected_prefix
        or not isinstance(project_root, str)
        or not project_root
        or resolved_root != PROJECT_ROOT
        or expected_python != str(PROJECT_ROOT / ".venv" / "bin" / "python")
        or expected_prefix != str(PROJECT_ROOT / ".venv")
        or guard_directory != str(PROJECT_ROOT / GUARD_DIRECTORY)
        or pythonpath != os.pathsep.join((guard_directory, project_root))
        or not Path(guard_directory, "sitecustomize.py").is_file()
        or Path(guard_directory, "sitecustomize.py").is_symlink()
        or not Path(cwd).is_absolute()
        or not command
        or command[0] != expected_python
        or any(
            (_SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name)) and value
            for name, value in env.items()
        )
        or any(env.get(name, "") for name in _KNOWN_PROVIDER_KEYS)
    ):
        raise NetworkGuardError("startup canary launch identity is invalid")

    for argument in command[1:]:
        if argument in ("-m", "-c", "--") or not argument.startswith("-"):
            break
        if argument in ("-S", "-I", "-E", "--isolated", "--ignore-environment", "--no-site"):
            raise NetworkGuardError("startup canary command disables sitecustomize")
        if not argument.startswith("--") and any(flag in argument[1:] for flag in "SIE"):
            raise NetworkGuardError("startup canary command disables sitecustomize")


def _validate_canary_report(
    report: Any,
    *,
    process_role: Any,
    command: Sequence[str],
    cwd: str,
    env: Mapping[str, str],
    process_id: int,
) -> None:
    expected_environment_sha = _startup_canary_environment_digest(env)
    expected_command_sha = hashlib.sha256(
        json.dumps(list(command), ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    interpreter = report.get("interpreter") if isinstance(report, Mapping) else None
    if (
        not isinstance(report, Mapping)
        or report.get("process_role") != process_role
        or type(report.get("pid")) is not int
        or report.get("pid") != process_id
        or type(report.get("startup_observed_at_ns")) is not int
        or report.get("startup_observed_at_ns") <= 0
        or report.get("command") != list(command)
        or report.get("command_sha256") != expected_command_sha
        or report.get("environment_sha256") != expected_environment_sha
        or report.get("working_directory") != str(Path(cwd))
        or report.get("guard_active") is not True
        or report.get("non_loopback_connect_denied") is not True
        or report.get("subprocess_launch_denied") is not True
        or not isinstance(interpreter, Mapping)
        or interpreter.get("executable") != env.get(EXPECTED_PYTHON_ENV)
        or interpreter.get("prefix") != env.get(EXPECTED_PREFIX_ENV)
        or not isinstance(interpreter.get("base_prefix"), str)
        or interpreter.get("base_prefix") == interpreter.get("prefix")
    ):
        raise NetworkGuardError("sitecustomize startup canary evidence is incomplete")


def _startup_environment_digest(env: Mapping[str, str]) -> str:
    normalized = {
        str(name): "" if _SECRET_ENV_NAME.search(str(name)) or _PROXY_ENV_NAME.search(str(name))
        else str(value)
        for name, value in env.items()
    }
    normalized.pop(ACTIVE_GUARD_ENV, None)
    normalized.pop(SANITIZED_ENV, None)
    normalized[ACTIVE_GUARD_ENV] = "1"
    normalized[SANITIZED_ENV] = "1"
    return hashlib.sha256(
        json.dumps(
            sorted(normalized.items()), ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()


def _startup_canary_environment_digest(
    env: Mapping[str, str],
    *,
    runtime_environment: Mapping[str, str] | None = None,
) -> str:
    """Bind caller environment plus exact locale/runtime values injected at startup.

    CPython's locale coercion and macOS process startup can add LC_CTYPE and
    __CF_USER_TEXT_ENCODING even when Popen receives an explicit environment.
    The target hashes those effective values; the controller incorporates its
    own observed values into the expected hash rather than dropping them.
    """
    effective_environment = {str(name): str(value) for name, value in env.items()}
    runtime = os.environ if runtime_environment is None else runtime_environment
    for name in _RUNTIME_INJECTED_ENV_NAMES:
        if name not in effective_environment and name in runtime:
            effective_environment[name] = str(runtime[name])
    return _startup_environment_digest(effective_environment)


def _read_canary_report(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = 65_536
    while remaining > 0:
        chunk = os.read(descriptor, min(4096, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if not raw.endswith(b"\n") or len(raw) > 65_536:
        raise NetworkGuardError("sitecustomize startup canary report is incomplete")
    return raw[:-1]


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short_write")
        offset += written


def _move_from_reserved_descriptor(descriptor: int) -> int:
    if descriptor not in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
        return descriptor
    replacement = os.dup(descriptor)
    while replacement in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
        next_replacement = os.dup(replacement)
        os.close(replacement)
        replacement = next_replacement
    os.close(descriptor)
    return replacement


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def current_invocation_command() -> list[str]:
    """Return the invoked command with Python's reported executable identity.

    CPython may rewrite ``sys.orig_argv[0]`` to the resolved framework binary
    when launched through a venv symlink. ``sys.executable`` retains the venv
    path that was invoked, so use it for argv[0] while preserving every caller
    argument exactly.
    """
    original = getattr(sys, "orig_argv", None)
    if isinstance(original, (list, tuple)) and original:
        return [sys.executable, *(str(argument) for argument in original[1:])]
    return [sys.executable, *sys.argv]


class _CanarySocket:
    family = socket.AF_INET


def _command_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if any(not isinstance(part, str) or not part for part in value):
        return None
    return tuple(value)


def _path_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return os.fspath(value)
    except TypeError:
        return None


def require_guard_active() -> None:
    """Fail closed unless this interpreter installed the network guard."""
    if (
        not _GUARD_INSTALLED
        or os.environ.get(ACTIVE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise NetworkGuardError("preflight network guard is not active in this process")
    for name, guarded_method in _GUARDED_SOCKET_METHODS.items():
        if getattr(socket.socket, name, None) is not guarded_method:
            raise NetworkGuardError("preflight socket deny guard was replaced")
    for name, guarded_function in _GUARDED_DNS_FUNCTIONS.items():
        if getattr(socket, name, None) is not guarded_function:
            raise NetworkGuardError("preflight DNS deny guard was replaced")
    if (
        not _SUBPROCESS_GUARD_INSTALLED
        or subprocess.Popen is not _GuardedPopen
    ):
        raise NetworkGuardError("preflight subprocess deny guard is not active")


def require_sanitized_environment() -> None:
    """Require the characterization process to have no usable credentials or proxies."""
    if (
        os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(ENABLE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise SafetyConfigurationError("preflight environment sanitization is not active")
    for name, value in os.environ.items():
        if (_SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name)) and value:
            raise SafetyConfigurationError("preflight environment contains a secret or proxy")
    if any(os.environ.get(name, "") for name in _KNOWN_PROVIDER_KEYS):
        raise SafetyConfigurationError("preflight provider key is not blank")


def _require_startup_guard_markers() -> Path:
    if (
        os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(ENABLE_GUARD_ENV) != "1"
        or os.environ.get(STARTUP_GUARD_ENV) != "1"
    ):
        raise NetworkGuardError("preflight startup guard was not installed by sitecustomize")
    if (
        os.environ.get(ACTIVE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise NetworkGuardError("preflight startup guard markers are incomplete")

    startup_module = sys.modules.get("sitecustomize")
    startup_path = getattr(startup_module, "__file__", None)
    if not isinstance(startup_path, (str, os.PathLike)):
        raise NetworkGuardError("preflight sitecustomize origin is unavailable")
    try:
        return Path(startup_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise NetworkGuardError("preflight sitecustomize origin is unavailable") from exc


def require_startup_guard_active() -> None:
    """Require the deny guard to have been installed by sitecustomize."""
    _require_startup_guard_markers()
    require_guard_active()
    try:
        report = json.loads(os.environ.get(CANARY_REPORT_ENV, ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise NetworkGuardError("preflight startup canary report is unavailable") from exc
    if (
        os.environ.get(CONNECT_CANARY_ENV) != "1"
        or os.environ.get(SUBPROCESS_CANARY_ENV) != "1"
        or not isinstance(report, Mapping)
        or report.get("process_role") != os.environ.get(PROCESS_ROLE_ENV)
        or report.get("command") != current_invocation_command()
        or report.get("working_directory") != str(Path.cwd())
        or type(report.get("pid")) is not int
        or report.get("pid") != os.getpid()
        or type(report.get("startup_observed_at_ns")) is not int
        or report.get("startup_observed_at_ns") <= 0
        or report.get("interpreter")
        != {
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        }
        or report.get("guard_active") is not True
        or report.get("non_loopback_connect_denied") is not True
        or report.get("subprocess_launch_denied") is not True
    ):
        raise NetworkGuardError("preflight startup canary did not fail closed")
    command_sha256 = hashlib.sha256(
        json.dumps(
            report.get("command"), ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()
    try:
        environment_sha256 = _startup_environment_digest(
            _startup_environment_snapshot()
        )
    except NetworkGuardError:
        raise NetworkGuardError("preflight startup environment snapshot is unavailable") from None
    if (
        report.get("command_sha256") != command_sha256
        or report.get("environment_sha256") != environment_sha256
    ):
        raise NetworkGuardError("preflight startup canary identity is invalid")


def require_startup_guard_from(
    expected_sitecustomize: str | Path,
    *,
    require_local_guard: bool = True,
) -> None:
    """Require the interpreter-started sitecustomize to match an exact file."""
    observed = _require_startup_guard_markers()
    try:
        expected = Path(expected_sitecustomize).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise NetworkGuardError("preflight sitecustomize origin is unavailable") from exc
    if observed != expected:
        raise NetworkGuardError("preflight sitecustomize origin differs from the sandbox")
    if require_local_guard:
        require_startup_guard_active()


def install_network_deny_guard() -> None:
    """Patch socket entry points to allow only numeric loopback addresses."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        require_guard_active()
        return

    _ORIGINAL_SOCKET_METHODS["connect"] = socket.socket.connect
    _ORIGINAL_SOCKET_METHODS["connect_ex"] = socket.socket.connect_ex
    _ORIGINAL_SOCKET_METHODS["bind"] = socket.socket.bind
    _ORIGINAL_SOCKET_METHODS["sendto"] = socket.socket.sendto
    _ORIGINAL_DNS_FUNCTIONS["getaddrinfo"] = socket.getaddrinfo
    _ORIGINAL_DNS_FUNCTIONS["gethostbyname"] = socket.gethostbyname
    _ORIGINAL_DNS_FUNCTIONS["gethostbyname_ex"] = socket.gethostbyname_ex
    _ORIGINAL_DNS_FUNCTIONS["gethostbyaddr"] = socket.gethostbyaddr
    _ORIGINAL_DNS_FUNCTIONS["getnameinfo"] = socket.getnameinfo

    original_connect = _ORIGINAL_SOCKET_METHODS["connect"]
    original_connect_ex = _ORIGINAL_SOCKET_METHODS["connect_ex"]
    original_bind = _ORIGINAL_SOCKET_METHODS["bind"]
    original_sendto = _ORIGINAL_SOCKET_METHODS["sendto"]
    original_getaddrinfo = _ORIGINAL_DNS_FUNCTIONS["getaddrinfo"]

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        _require_loopback_socket_address(sock.family, address)
        return original_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        _require_loopback_socket_address(sock.family, address)
        return original_connect_ex(sock, address)

    def guarded_bind(sock: socket.socket, address: Any) -> Any:
        _require_loopback_socket_address(sock.family, address)
        return original_bind(sock, address)

    def guarded_sendto(sock: socket.socket, *args: Any) -> int:
        if not args:
            raise NetworkGuardError("socket sendto address is missing")
        _require_loopback_socket_address(sock.family, args[-1])
        return original_sendto(sock, *args)

    def guarded_getaddrinfo(
        host: Any,
        port: Any,
        family: int = 0,
        socktype: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        if isinstance(host, str) and host.casefold() == "localhost":
            return _localhost_addrinfo(port, family, socktype, proto, flags)
        if not _is_ip_loopback(host):
            raise NetworkGuardError("non-loopback DNS and network access are denied")
        results = original_getaddrinfo(host, port, family, socktype, proto, flags)
        if any(not _is_ip_loopback(item[4][0]) for item in results):
            raise NetworkGuardError("resolver returned a non-loopback address")
        return results

    def guarded_gethostbyname(host: str) -> str:
        if isinstance(host, str) and host.casefold() == "localhost":
            return "127.0.0.1"
        try:
            address = ipaddress.IPv4Address(host)
        except (ipaddress.AddressValueError, TypeError):
            raise NetworkGuardError("non-loopback DNS is denied") from None
        if not address.is_loopback:
            raise NetworkGuardError("non-loopback DNS is denied")
        return str(address)

    def guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        address = guarded_gethostbyname(host)
        return "localhost", [], [address]

    def guarded_gethostbyaddr(address: str) -> tuple[str, list[str], list[str]]:
        if not _is_ip_loopback(address):
            raise NetworkGuardError("non-loopback reverse DNS is denied")
        return "localhost", [], [str(address)]

    def guarded_getnameinfo(address: Any, flags: int) -> tuple[str, str]:
        if not isinstance(address, tuple) or not address or not _is_ip_loopback(address[0]):
            raise NetworkGuardError("non-loopback reverse DNS is denied")
        if not flags & getattr(socket, "NI_NUMERICHOST", 0):
            raise NetworkGuardError("reverse DNS lookups are denied")
        numeric_flags = flags | getattr(socket, "NI_NUMERICSERV", 0)
        return _ORIGINAL_DNS_FUNCTIONS["getnameinfo"](address, numeric_flags)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.socket.bind = guarded_bind  # type: ignore[method-assign]
    socket.socket.sendto = guarded_sendto  # type: ignore[method-assign]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]
    socket.gethostbyname_ex = guarded_gethostbyname_ex  # type: ignore[assignment]
    socket.gethostbyaddr = guarded_gethostbyaddr  # type: ignore[assignment]
    socket.getnameinfo = guarded_getnameinfo  # type: ignore[assignment]
    _GUARDED_SOCKET_METHODS.update(
        {
            "connect": guarded_connect,
            "connect_ex": guarded_connect_ex,
            "bind": guarded_bind,
            "sendto": guarded_sendto,
        }
    )
    _GUARDED_DNS_FUNCTIONS.update(
        {
            "getaddrinfo": guarded_getaddrinfo,
            "gethostbyname": guarded_gethostbyname,
            "gethostbyname_ex": guarded_gethostbyname_ex,
            "gethostbyaddr": guarded_gethostbyaddr,
            "getnameinfo": guarded_getnameinfo,
        }
    )
    _GUARD_INSTALLED = True
    os.environ[ACTIVE_GUARD_ENV] = "1"


def _require_loopback_socket_address(family: int, address: Any) -> None:
    if family not in (socket.AF_INET, socket.AF_INET6):
        raise NetworkGuardError("only IPv4 and IPv6 loopback sockets are permitted")
    if not isinstance(address, tuple) or not address or not _is_ip_loopback(address[0]):
        raise NetworkGuardError("only numeric loopback socket addresses are permitted")


def _is_ip_loopback(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _localhost_addrinfo(
    port: Any,
    family: int,
    socktype: int,
    proto: int,
    flags: int,
) -> list[tuple[Any, ...]]:
    del flags
    families = [socket.AF_INET, socket.AF_INET6]
    if family not in (0, socket.AF_UNSPEC):
        if family not in families:
            raise socket.gaierror(socket.EAI_FAMILY, "unsupported address family")
        families = [family]
    types = [socktype] if socktype else [socket.SOCK_STREAM, socket.SOCK_DGRAM]
    output: list[tuple[Any, ...]] = []
    for selected_family in families:
        for selected_type in types:
            selected_proto = proto
            if selected_proto == 0:
                if selected_type == socket.SOCK_STREAM:
                    selected_proto = socket.IPPROTO_TCP
                elif selected_type == socket.SOCK_DGRAM:
                    selected_proto = socket.IPPROTO_UDP
            if selected_family == socket.AF_INET:
                address = ("127.0.0.1", port)
            else:
                address = ("::1", port, 0, 0)
            output.append((selected_family, selected_type, selected_proto, "", address))
    return output
