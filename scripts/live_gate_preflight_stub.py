# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Counting, fail-closed router stub for later isolated characterization."""

from __future__ import annotations

import atexit
import copy
import hashlib
import importlib.abc
import importlib.machinery
import inspect
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from scripts.live_gate_preflight_safety import (
    ACTIVE_GUARD_ENV,
    ADV_SUMMARY_CHILD_COMMAND_SHA_ENV,
    ADV_SUMMARY_CHILD_CWD_ENV,
    ADV_SUMMARY_CHILD_EVIDENCE_ENV,
    ADV_SUMMARY_CHILD_MODE,
    ADV_SUMMARY_CHILD_MODE_ENV,
    ADV_SUMMARY_CHILD_SOURCE_ROOT_ENV,
    ADV_SUMMARY_CHILD_SOURCE_SHA_ENV,
    CANARY_REPORT_ENV,
    ENABLE_GUARD_ENV,
    EXPECTED_PYTHON_ENV,
    EXPECTED_PREFIX_ENV,
    GUARD_DIRECTORY_ENV,
    GUARD_EVENTS_PATH_ENV,
    PROCESS_ROLE_ENV,
    PROJECT_ROOT_ENV,
    REQUIRE_STARTUP_GUARD_ENV,
    RUN_ID_ENV,
    STARTUP_GUARD_ENV,
    NetworkGuardError,
    _validate_guard_event_path,
    authorize_subprocess_launch,
    current_invocation_command,
    require_current_invocation_matches_startup,
    require_guard_active,
    require_sanitized_environment,
    require_startup_guard_active,
    run_startup_process_canary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SECRET_ARGUMENT = re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)
_SAFE_TASK = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
DEFAULT_MAX_CALLS = 256
_AREA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CHILD_EVIDENCE_MAX_BYTES = 131_072
_CHILD_SNAPSHOT_MAX_BYTES = 512_000
_CHILD_EVIDENCE_MAX_RECORDS = 8
_SUMMARY_DUMP_NAMES = frozenset(
    ("summary_dump.json", "trimmed_summary_dump.json", "dialogue_summary.json")
)
_ADV_SUMMARY_CHILD_HOOK: "_AdvSummaryChildImportHook | None" = None
_ADV_SUMMARY_CHILD_STUB: FailClosedRouterStub | None = None
_ADV_SUMMARY_CHILD_RECEIPT: dict[str, Any] | None = None
_ADV_SUMMARY_CHILD_EVIDENCE_PATH: Path | None = None
_ADV_SUMMARY_CHILD_SANDBOX: Path | None = None
_ADV_SUMMARY_CHILD_SOURCE_ROOT: Path | None = None
_ADV_SUMMARY_CHILD_RUNTIME_READY = False
_ADV_SUMMARY_CHILD_ORIGINAL_REMOVE: Callable[..., Any] | None = None
_ADV_SUMMARY_CHILD_ORIGINAL_DUMP: Callable[..., Any] | None = None
_ADV_SUMMARY_CHILD_CALLS: list[dict[str, Any]] = []
_ADV_SUMMARY_CHILD_WRITES: list[dict[str, Any]] = []
_ADV_SUMMARY_CHILD_EXPECTED_AREA_PATH: str | None = None
_ADV_SUMMARY_CHILD_EXIT_HOOK_REGISTERED = False
_ADV_SUMMARY_CHILD_EXIT_RECORDED = False
_ADV_SUMMARY_RESPONSE = (
    "The provider-free response records the scripted conversation. "
    "It adds no events beyond the supplied history."
)


class RouterStubError(RuntimeError):
    """Raised for invalid identity or a call without a declared stub response."""


class FailClosedRouterStub:
    """Return only explicit test responses and retain metadata for every call.

    Prompt, response, and caller keyword values are never recorded. An unknown
    task is still counted before it is rejected.
    """

    def __init__(
        self,
        *,
        source_sha: str,
        responses: Mapping[str, Any],
        response_resolver: (
            Callable[
                [str, str | None, Sequence[Any], Mapping[str, Any]], Any
            ]
            | None
        ) = None,
        command: Sequence[str] | None = None,
        pythonpath: str | None = None,
        source_root: str | Path = PROJECT_ROOT,
        max_calls: int = DEFAULT_MAX_CALLS,
    ) -> None:
        _require_network_guard()
        if not isinstance(source_sha, str) or _SHA.fullmatch(source_sha) is None:
            raise RouterStubError("a full source SHA is required")
        if not isinstance(responses, Mapping) or any(
            not isinstance(task, str) or not task for task in responses
        ):
            raise RouterStubError("stub responses must be keyed by non-empty task names")
        if response_resolver is not None and not callable(response_resolver):
            raise RouterStubError("stub response resolver is invalid")
        selected_command = list(sys.argv if command is None else command)
        if not selected_command or any(not isinstance(part, str) for part in selected_command):
            raise RouterStubError("command identity is invalid")
        selected_pythonpath = os.environ.get("PYTHONPATH", "") if pythonpath is None else pythonpath
        if not isinstance(selected_pythonpath, str):
            raise RouterStubError("PYTHONPATH identity is invalid")
        if type(max_calls) is not int or max_calls < 1 or max_calls > DEFAULT_MAX_CALLS:
            raise RouterStubError("router call bound is invalid")
        try:
            selected_source_root = Path(source_root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RouterStubError("router source root is unavailable") from exc
        if not selected_source_root.is_dir():
            raise RouterStubError("router source root is unavailable")

        self.source_sha = source_sha
        self.responses = copy.deepcopy(dict(responses))
        self.response_resolver = response_resolver
        self.command = _redact_command(selected_command)
        self.pythonpath = selected_pythonpath
        self.source_root = selected_source_root
        self.max_calls = max_calls
        self.calls: list[dict[str, Any]] = []
        self.attempt_count = 0
        self.failure_code: str | None = None

    @property
    def call_count(self) -> int:
        return self.attempt_count

    def __call__(self, task: str, *args: Any, **kwargs: Any) -> Any:
        _require_network_guard()
        self.attempt_count += 1
        call_site = _caller_location(self.source_root)
        task_value = task if isinstance(task, str) and _SAFE_TASK.fullmatch(task) else "<invalid-task>"
        source_sha256 = _source_file_sha256(self.source_root, call_site[0])
        record = {
            "sequence": self.call_count,
            "task": task_value,
            "source_file": call_site[0],
            "source_line": call_site[1],
            "source_file_sha256": source_sha256,
            "source_sha": self.source_sha,
            "command": list(self.command),
            "pythonpath": self.pythonpath,
        }
        if len(self.calls) < self.max_calls:
            self.calls.append(record)
        else:
            self.failure_code = "router_call_limit_exceeded"
            raise RouterStubError("router call limit exceeded")

        if call_site[0] is None or call_site[1] is None:
            self.failure_code = "router_call_source_unavailable"
            raise RouterStubError("router call source attribution is unavailable")
        if source_sha256 is None:
            self.failure_code = "router_call_source_hash_unavailable"
            raise RouterStubError("router call source hash is unavailable")
        if not isinstance(task, str) or not _SAFE_TASK.fullmatch(task) or task not in self.responses:
            self.failure_code = "router_task_has_no_stub_response"
            raise RouterStubError("router task has no explicit stub response")
        if self.response_resolver is not None:
            try:
                resolved_response = self.response_resolver(
                    task, call_site[0], args, kwargs
                )
            except RouterStubError:
                self.failure_code = "router_response_resolver_rejected_call"
                raise
            if resolved_response is not None:
                return copy.deepcopy(resolved_response)
        return copy.deepcopy(self.responses[task])


def install_fail_closed_router_stub(
    router: Any, stub: FailClosedRouterStub
) -> Callable[[], None]:
    """Replace a router call boundary with the guarded explicit-response stub.

    The returned cleanup restores the original callable only while the stub is
    still installed. A changed boundary is reported as an error rather than
    silently restoring over an unexpected mutation.
    """
    _require_network_guard()
    if not isinstance(stub, FailClosedRouterStub):
        raise RouterStubError("router boundary requires a fail-closed stub")
    original_call = getattr(router, "call", None)
    if not callable(original_call) or original_call is stub:
        raise RouterStubError("sandbox router call boundary is unavailable")
    try:
        setattr(router, "call", stub)
    except Exception as exc:
        raise RouterStubError("sandbox router stub installation failed") from exc
    if getattr(router, "call", None) is not stub:
        try:
            setattr(router, "call", original_call)
        except Exception:
            pass
        raise RouterStubError("sandbox router stub installation failed")

    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        if getattr(router, "call", None) is not stub:
            raise RouterStubError("sandbox router stub boundary changed")
        try:
            setattr(router, "call", original_call)
        except Exception as exc:
            raise RouterStubError("sandbox router stub cleanup failed") from exc
        cleaned = True

    return cleanup


def _caller_location(source_root: Path) -> tuple[str | None, int | None]:
    this_file = Path(__file__).resolve()
    for frame in inspect.stack(context=0)[1:]:
        candidate = Path(frame.filename)
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(source_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved == this_file:
            continue
        return relative.as_posix(), frame.lineno
    return None, None


def _source_file_sha256(source_root: Path, source_file: str | None) -> str | None:
    if not isinstance(source_file, str):
        return None
    relative = Path(source_file)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = source_root.joinpath(*relative.parts)
    cursor = source_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(source_root)
        if not resolved.is_file():
            return None
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except (OSError, RuntimeError, ValueError):
        return None


def _redact_command(command: Sequence[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for argument in command:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        if _SECRET_ARGUMENT.search(argument):
            if "=" in argument:
                result.append(argument.split("=", 1)[0] + "=<redacted>")
            else:
                result.append(argument)
                redact_next = True
        else:
            result.append(argument)
    return result


def _require_network_guard() -> None:
    try:
        require_guard_active()
    except NetworkGuardError as exc:
        raise RouterStubError("router stub requires the active sanitized network guard") from exc


def _command_sha256(command: Sequence[str]) -> str:
    return hashlib.sha256(
        json.dumps(list(command), ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()


def _safe_file_sha256(path: Path, *, expected_root: Path) -> str:
    cursor = expected_root
    try:
        relative = path.relative_to(expected_root)
    except ValueError as exc:
        raise RouterStubError("summary child source escaped its root") from exc
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RouterStubError("summary child source traverses a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(expected_root)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RouterStubError("summary child source is not a regular file")
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RouterStubError("summary child source is unavailable") from exc


def _validated_child_source_root(root: Path, candidate: Path) -> Path:
    if not os.fspath(candidate):
        raise RouterStubError("summary child source root is missing")
    if candidate.is_symlink():
        raise RouterStubError("summary child source root is a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        if resolved != root:
            relative = resolved.relative_to(root / "tmp")
            if not relative.parts:
                raise RouterStubError("summary child source root is invalid")
            cursor = root
            for part in ("tmp", *relative.parts):
                cursor = cursor / part
                if cursor.is_symlink():
                    raise RouterStubError(
                        "summary child source root traverses a symlink"
                    )
    except RouterStubError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RouterStubError("summary child source root is unavailable") from exc
    if not resolved.is_dir():
        raise RouterStubError("summary child source root is not a directory")
    return resolved


def _adv_summary_child_evidence_path(*, run_id: str) -> Path:
    guard_events_path = os.environ.get(GUARD_EVENTS_PATH_ENV, "")
    try:
        validated_guard_path = _validate_guard_event_path(guard_events_path, run_id)
    except Exception as exc:
        raise RouterStubError("summary child guard-event identity is invalid") from exc
    expected = validated_guard_path.with_name("adv-summary-child.jsonl")
    configured = os.environ.get(ADV_SUMMARY_CHILD_EVIDENCE_ENV)
    if configured is not None and configured != str(expected):
        raise RouterStubError("summary child evidence path is invalid")
    return expected


def _validate_adv_summary_child_identity() -> dict[str, Any]:
    """Bind the child adapter to one exact adv_summary.py interpreter invocation."""
    _require_network_guard()
    if (
        os.environ.get(ADV_SUMMARY_CHILD_MODE_ENV) != ADV_SUMMARY_CHILD_MODE
        or os.environ.get(ENABLE_GUARD_ENV) != "1"
        or os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(ACTIVE_GUARD_ENV) != "1"
        or os.environ.get(PROCESS_ROLE_ENV) != "host"
    ):
        raise RouterStubError("summary child mode or startup guard is unavailable")
    try:
        require_sanitized_environment()
        require_startup_guard_active()
    except Exception as exc:
        raise RouterStubError("summary child startup guard is unavailable") from exc

    root = Path(os.environ.get(PROJECT_ROOT_ENV, ""))
    try:
        root = root.resolve(strict=True)
        cwd = Path.cwd().resolve(strict=True)
        expected_cwd = (root / "tmp" / "combat_capture").resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RouterStubError("summary child working directory is unavailable") from exc
    source_root_text = os.environ.get(ADV_SUMMARY_CHILD_SOURCE_ROOT_ENV, "")
    if not source_root_text:
        raise RouterStubError("summary child source root is missing")
    source_root = _validated_child_source_root(root, Path(source_root_text))
    command = current_invocation_command()
    expected_python = str(root / ".venv" / "bin" / "python")
    expected_prefix = str(root / ".venv")
    expected_guard = str(root / "scripts" / "live_gate_preflight_guard")
    expected_pythonpath = os.pathsep.join((expected_guard, str(root)))
    if (
        root != PROJECT_ROOT
        or cwd != expected_cwd
        or os.environ.get(ADV_SUMMARY_CHILD_CWD_ENV) != str(cwd)
        or os.environ.get(EXPECTED_PYTHON_ENV) != expected_python
        or os.environ.get(EXPECTED_PREFIX_ENV) != expected_prefix
        or os.environ.get(GUARD_DIRECTORY_ENV) != expected_guard
        or os.environ.get("PYTHONPATH") != expected_pythonpath
        or not isinstance(command, list)
        or len(command) != 6
        or command[0] != expected_python
        or command[1] != str(cwd / "core" / "ai" / "adv_summary.py")
        or command[2] != "modules/conversation_history/conversation_history.json"
        or command[3] != "current_location.json"
        or not command[4]
        or len(command[4]) > 512
        or "\x00" in command[4]
        or "\n" in command[4]
        or "\r" in command[4]
        or _AREA_ID.fullmatch(command[5]) is None
    ):
        raise RouterStubError("summary child command or environment identity differs")

    source_sha = os.environ.get(ADV_SUMMARY_CHILD_SOURCE_SHA_ENV, "")
    expected_command_sha = os.environ.get(ADV_SUMMARY_CHILD_COMMAND_SHA_ENV, "")
    if (
        _SHA.fullmatch(source_sha) is None
        or expected_command_sha != _command_sha256(command)
    ):
        raise RouterStubError("summary child source or command hash is invalid")

    script_path = cwd / "core" / "ai" / "adv_summary.py"
    repository_script = source_root / "core" / "ai" / "adv_summary.py"
    script_sha256 = _safe_file_sha256(script_path, expected_root=root)
    if script_sha256 != _safe_file_sha256(
        repository_script, expected_root=source_root
    ):
        raise RouterStubError("summary child script differs from the bound source")
    evidence_path = _adv_summary_child_evidence_path(
        run_id=os.environ.get(RUN_ID_ENV, "")
    )
    if os.environ.get(ADV_SUMMARY_CHILD_EVIDENCE_ENV) != str(evidence_path):
        raise RouterStubError("summary child evidence environment is invalid")
    if not evidence_path.is_file() or evidence_path.is_symlink():
        raise RouterStubError("summary child evidence file is unavailable")

    return {
        "run_id": os.environ.get(RUN_ID_ENV, ""),
        "command": command,
        "command_sha256": expected_command_sha,
        "source_sha": source_sha,
        "source_root": source_root,
        "script_sha256": script_sha256,
        "working_directory": str(cwd),
        "pythonpath": expected_pythonpath,
        "evidence_path": evidence_path,
    }


def _append_adv_summary_child_evidence(
    path: Path, value: Mapping[str, Any], *, run_id: str
) -> None:
    if path != _adv_summary_child_evidence_path(run_id=run_id):
        raise RouterStubError("summary child evidence destination changed")
    payload = json.dumps(
        dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii") + b"\n"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        )
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
            or metadata.st_size + len(payload) > _CHILD_EVIDENCE_MAX_BYTES
        ):
            raise RouterStubError("summary child evidence file is invalid")
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise RouterStubError("summary child evidence write was incomplete")
        os.fsync(descriptor)
    except OSError as exc:
        raise RouterStubError("summary child evidence write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _normalize_child_location_name(value: str) -> str:
    return re.sub(r"^Room\s+\d+\s*:\s*", "", value.strip(), flags=re.IGNORECASE)


def _child_expected_area_path(identity: Mapping[str, Any]) -> str:
    sandbox = Path(identity["working_directory"]).resolve(strict=True)
    command = identity.get("command")
    if not isinstance(command, list) or len(command) != 6:
        raise RouterStubError("summary child area command is invalid")
    area_id = command[5]
    if not isinstance(area_id, str) or _AREA_ID.fullmatch(area_id) is None:
        raise RouterStubError("summary child area identity is invalid")
    tracker_path = sandbox / "party_tracker.json"
    try:
        tracker = json.loads(
            _read_child_json_bytes(
                tracker_path, sandbox_root=sandbox
            ).decode("utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RouterStubError) as exc:
        raise RouterStubError("summary child party tracker is unavailable") from exc
    module_name = tracker.get("module") if isinstance(tracker, Mapping) else None
    if not isinstance(module_name, str) or not module_name.strip():
        raise RouterStubError("summary child module identity is unavailable")
    module_name = module_name.replace(" ", "_")
    if (
        module_name in (".", "..")
        or "/" in module_name
        or "\\" in module_name
        or "\x00" in module_name
    ):
        raise RouterStubError("summary child module identity is invalid")
    relative_candidates = (
        Path("modules") / module_name / "areas" / (area_id + ".json"),
        Path("modules") / module_name / (area_id + ".json"),
    )
    for relative in relative_candidates:
        cursor = sandbox
        safe = True
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                safe = False
                break
        if safe and cursor.is_file():
            return relative.as_posix()
    raise RouterStubError("summary child area file is unavailable")


def _child_summary_location(identity: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    command = identity.get("command")
    if not isinstance(command, list) or len(command) != 6:
        raise RouterStubError("summary child location command is invalid")
    expected_name = _normalize_child_location_name(command[4])
    sandbox = Path(identity["working_directory"]).resolve(strict=True)
    area_path = sandbox / _child_expected_area_path(identity)
    try:
        area = json.loads(_read_child_json_bytes(area_path).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RouterStubError) as exc:
        raise RouterStubError("summary child area data is unavailable") from exc
    locations = area.get("locations") if isinstance(area, Mapping) else None
    if not isinstance(locations, list):
        raise RouterStubError("summary child area locations are invalid")
    matches = [
        location
        for location in locations
        if isinstance(location, Mapping)
        and (
            location.get("name") == expected_name
            or (
                isinstance(location.get("name"), str)
                and _normalize_child_location_name(location["name"])
                == expected_name
            )
            or location.get("source_room_title") == expected_name
        )
    ]
    if len(matches) != 1:
        raise RouterStubError("summary child leaving location is unresolved")
    return expected_name, dict(matches[0])


def _validated_child_json_destination(filepath: Any) -> str:
    sandbox = _ADV_SUMMARY_CHILD_SANDBOX
    expected_area_path = _ADV_SUMMARY_CHILD_EXPECTED_AREA_PATH
    if sandbox is None or expected_area_path is None:
        raise RouterStubError("summary child sandbox is unavailable")
    try:
        supplied = Path(os.fspath(filepath))
        if supplied.is_absolute():
            relative = supplied.relative_to(sandbox)
        else:
            relative = supplied
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise RouterStubError("summary child JSON destination is invalid")
        relative_text = relative.as_posix()
        if (
            relative_text not in _SUMMARY_DUMP_NAMES
            and relative_text != "journal.json"
            and relative_text != expected_area_path
        ):
            raise RouterStubError("summary child JSON destination is invalid")
        cursor = sandbox
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RouterStubError("summary child JSON destination is invalid")
        cursor.parent.resolve(strict=True).relative_to(sandbox.resolve(strict=True))
        if cursor.exists() and not cursor.is_file():
            raise RouterStubError("summary child JSON destination is not a file")
    except RouterStubError:
        raise
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        raise RouterStubError("summary child JSON destination is invalid") from exc
    return relative_text


def _read_child_json_bytes(
    path: Path, *, sandbox_root: Path | None = None
) -> bytes:
    sandbox = _ADV_SUMMARY_CHILD_SANDBOX if sandbox_root is None else sandbox_root
    if sandbox is None:
        raise RouterStubError("summary child sandbox is unavailable")
    descriptor: int | None = None
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(sandbox.resolve(strict=True))
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
            or metadata.st_size > 512_000
        ):
            raise RouterStubError("summary child persisted JSON is invalid")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                raise RouterStubError("summary child persisted JSON is incomplete")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    except RouterStubError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RouterStubError("summary child persisted JSON is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _child_json_write_sandboxed(data: Any, filepath: Any, **kwargs: Any) -> bool:
    _require_network_guard()
    source_file, source_line = _caller_location(PROJECT_ROOT)
    if (
        source_file != "tmp/combat_capture/core/ai/adv_summary.py"
        or type(source_line) is not int
    ):
        raise RouterStubError("unexpected JSON writer in summary child")
    original_dump = _ADV_SUMMARY_CHILD_ORIGINAL_DUMP
    if not callable(original_dump):
        raise RouterStubError("summary child canonical JSON writer is unavailable")
    relative_path = _validated_child_json_destination(filepath)
    if len(_ADV_SUMMARY_CHILD_WRITES) >= 16:
        raise RouterStubError("summary child JSON write limit exceeded")
    result = original_dump(data, filepath, **kwargs)
    if result is not True:
        raise OSError("canonical summary child JSON write did not complete")
    sandbox = _ADV_SUMMARY_CHILD_SANDBOX
    if sandbox is None:
        raise RouterStubError("summary child sandbox is unavailable")
    raw = _read_child_json_bytes(sandbox / Path(relative_path))
    sequence = len(_ADV_SUMMARY_CHILD_WRITES) + 1
    identity = _ADV_SUMMARY_CHILD_RECEIPT
    if not isinstance(identity, Mapping):
        raise RouterStubError("summary child identity is unavailable")
    retained_artifact = _write_adv_summary_child_snapshot(
        raw,
        identity=identity,
        source_path=relative_path,
        write_sequence=sequence,
    )
    _ADV_SUMMARY_CHILD_WRITES.append(
        {
            "sequence": sequence,
            "source_file": source_file,
            "source_line": source_line,
            "path": relative_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "retained_artifact": retained_artifact,
        }
    )
    return result


def _write_adv_summary_child_snapshot(
    raw: bytes,
    *,
    identity: Mapping[str, Any],
    source_path: str,
    write_sequence: int,
) -> dict[str, Any]:
    """Retain each actual canonical write before a later write can replace it."""
    evidence_path = _ADV_SUMMARY_CHILD_EVIDENCE_PATH
    run_id = identity.get("run_id")
    pid = os.getpid()
    digest = hashlib.sha256(raw).hexdigest()
    if (
        evidence_path is None
        or not isinstance(run_id, str)
        or run_id != os.environ.get(RUN_ID_ENV)
        or type(write_sequence) is not int
        or write_sequence < 1
        or not isinstance(source_path, str)
        or _SHA.fullmatch(digest) is None
        or len(raw) < 1
        or len(raw) > _CHILD_SNAPSHOT_MAX_BYTES
    ):
        raise RouterStubError("summary child retained artifact identity is invalid")
    try:
        evidence_path = evidence_path.resolve(strict=True)
        expected_evidence = _adv_summary_child_evidence_path(run_id=run_id)
        if evidence_path != expected_evidence.resolve(strict=True):
            raise RouterStubError("summary child retained artifact directory differs")
        directory = evidence_path.parent
        project_tmp = (PROJECT_ROOT / "tmp").resolve(strict=True)
        directory.resolve(strict=True).relative_to(project_tmp)
        cursor = project_tmp
        for part in directory.relative_to(project_tmp).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RouterStubError(
                    "summary child retained artifact directory traverses a symlink"
                )
    except RouterStubError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RouterStubError("summary child retained artifact directory is unsafe") from exc

    relative_source = PurePosixPath(source_path)
    if (
        relative_source.is_absolute()
        or not relative_source.parts
        or ".." in relative_source.parts
        or "\\" in source_path
    ):
        raise RouterStubError("summary child retained artifact source is unsafe")
    artifact_path = directory / (
        "adv-summary-write-%d-%d.json" % (pid, write_sequence)
    )
    if artifact_path.exists() or artifact_path.is_symlink():
        raise RouterStubError("summary child retained artifact already exists")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            artifact_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        created = True
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
        ):
            raise RouterStubError("summary child retained artifact file is invalid")
        view = memoryview(raw)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise RouterStubError(
                    "summary child retained artifact write was incomplete"
                )
            written += count
        os.fsync(descriptor)
    except RouterStubError:
        if created:
            try:
                artifact_path.unlink()
            except OSError:
                pass
        raise
    except OSError as exc:
        if created:
            try:
                artifact_path.unlink()
            except OSError:
                pass
        raise RouterStubError("summary child retained artifact write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    return {
        "path": artifact_path.relative_to(PROJECT_ROOT).as_posix(),
        "source_path": "tmp/combat_capture/" + relative_source.as_posix(),
        "sha256": digest,
        "size_bytes": len(raw),
        "run_id": run_id,
        "source_sha": identity.get("source_sha"),
        "command_sha256": identity.get("command_sha256"),
        "process_id": pid,
        "process_role": "host",
        "write_sequence": write_sequence,
        "provenance": "guarded_canonical_json_writer",
    }


def _child_remove_guard(path: Any, *args: Any, **kwargs: Any) -> Any:
    original_remove = _ADV_SUMMARY_CHILD_ORIGINAL_REMOVE
    if original_remove is None:
        raise RouterStubError("summary child remove guard is unavailable")
    source_file, _source_line = _caller_location(PROJECT_ROOT)
    if source_file == "tmp/combat_capture/core/ai/adv_summary.py":
        try:
            relative_path = _validated_child_json_destination(path)
        except RouterStubError as exc:
            raise RouterStubError(
                "unexpected summary child removal destination"
            ) from exc
        if relative_path != "summary_dump.json":
            raise RouterStubError("unexpected summary child removal destination")
    return original_remove(path, *args, **kwargs)


class _AdvSummaryChildResponseResolver:
    """Return bounded deterministic responses for the two summary calls."""

    def __init__(
        self, *, location: Mapping[str, Any], leaving_location_name: str
    ) -> None:
        self.location = copy.deepcopy(dict(location))
        self.leaving_location_name = leaving_location_name

    def __call__(
        self,
        task: str,
        source_file: str | None,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
    ) -> str:
        del args
        sequence = len(_ADV_SUMMARY_CHILD_CALLS) + 1
        messages = kwargs.get("messages")
        if (
            task != "adventure_summary"
            or source_file != "tmp/combat_capture/core/ai/adv_summary.py"
            or kwargs.get("json_output") is not False
            or not isinstance(messages, list)
            or any(not isinstance(message, Mapping) for message in messages)
        ):
            raise RouterStubError("summary child router call differs from production")
        if sequence == 1:
            if (
                kwargs.get("json_contract", False) is not False
                or len(messages) != 2
                or messages[0].get("role") != "system"
                or messages[1].get("role") != "user"
            ):
                raise RouterStubError("summary generation call shape differs")
            return _ADV_SUMMARY_RESPONSE
        if sequence == 2:
            if (
                kwargs.get("json_contract") is not True
                or len(messages) != 1
                or messages[0].get("role") != "system"
                or not isinstance(messages[0].get("content"), str)
                or "Current Location JSON:" not in messages[0]["content"]
                or self.location.get("name") != self.leaving_location_name
            ):
                raise RouterStubError("summary location-update call shape differs")
            location = copy.deepcopy(self.location)
            location["adventureSummary"] = _ADV_SUMMARY_RESPONSE
            return json.dumps(
                location, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
        raise RouterStubError("summary child router call limit exceeded")


def _child_summary_outputs_persisted(
    *,
    identity: Mapping[str, Any],
    calls: Sequence[Mapping[str, Any]],
    writes: Sequence[Mapping[str, Any]],
) -> bool:
    if len(calls) != 2 or len(writes) != 6:
        return False
    if (
        [call.get("sequence") for call in calls] != [1, 2]
        or [call.get("response_kind") for call in calls]
        != ["summary_text", "location_json"]
        or any(call.get("failure_code") is not None for call in calls)
    ):
        return False
    try:
        expected_area = _child_expected_area_path(identity)
        expected_counts = {
            "summary_dump.json": 1,
            "trimmed_summary_dump.json": 1,
            "dialogue_summary.json": 1,
            "journal.json": 1,
            expected_area: 2,
        }
        observed_counts: dict[str, int] = {}
        latest_writes: dict[str, Mapping[str, Any]] = {}
        sandbox = Path(identity["working_directory"]).resolve(strict=True)
        for index, write in enumerate(writes, start=1):
            path_text = write.get("path")
            digest = write.get("sha256")
            size_bytes = write.get("size_bytes")
            if (
                type(write.get("sequence")) is not int
                or write.get("sequence") != index
                or write.get("source_file")
                != "tmp/combat_capture/core/ai/adv_summary.py"
                or type(write.get("source_line")) is not int
                or write.get("source_line") <= 0
                or not isinstance(path_text, str)
                or not isinstance(digest, str)
                or _SHA.fullmatch(digest) is None
                or type(size_bytes) is not int
                or size_bytes <= 0
            ):
                return False
            observed_counts[path_text] = observed_counts.get(path_text, 0) + 1
            latest_writes[path_text] = write

        if observed_counts != expected_counts:
            return False
        for path_text, write in latest_writes.items():
            raw = _read_child_json_bytes(
                sandbox / Path(path_text), sandbox_root=sandbox
            )
            if (
                len(raw) != write.get("size_bytes")
                or hashlib.sha256(raw).hexdigest() != write.get("sha256")
            ):
                return False
            parsed = json.loads(raw.decode("utf-8"))
            if path_text in _SUMMARY_DUMP_NAMES and not isinstance(parsed, list):
                return False

        summary_digest = calls[0].get("response_sha256")
        if not isinstance(summary_digest, str) or _SHA.fullmatch(summary_digest) is None:
            return False
        journal = json.loads(
            _read_child_json_bytes(
                sandbox / "journal.json", sandbox_root=sandbox
            ).decode("utf-8")
        )
        entries = journal.get("entries") if isinstance(journal, Mapping) else None
        if not isinstance(entries, list) or not entries:
            return False
        latest = entries[-1]
        if (
            not isinstance(latest, Mapping)
            or latest.get("location")
            != _normalize_child_location_name(identity["command"][4])
            or not isinstance(latest.get("summary"), str)
            or hashlib.sha256(latest["summary"].encode("utf-8")).hexdigest()
            != summary_digest
        ):
            return False

        area = json.loads(
            _read_child_json_bytes(
                sandbox / expected_area, sandbox_root=sandbox
            ).decode("utf-8")
        )
        locations = area.get("locations") if isinstance(area, Mapping) else None
        leaving_name = _normalize_child_location_name(identity["command"][4])
        matching = [
            location
            for location in locations or []
            if isinstance(location, Mapping)
            and (
                location.get("name") == leaving_name
                or (
                    isinstance(location.get("name"), str)
                    and _normalize_child_location_name(location["name"])
                    == leaving_name
                )
                or location.get("source_room_title") == leaving_name
            )
        ]
        if len(matching) != 1:
            return False
        adventure_summary = matching[0].get("adventureSummary")
        return (
            isinstance(adventure_summary, str)
            and hashlib.sha256(adventure_summary.encode("utf-8")).hexdigest()
            == summary_digest
        )
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError, RuntimeError, ValueError, RouterStubError):
        return False


def _record_adv_summary_child_exit() -> None:
    global _ADV_SUMMARY_CHILD_EXIT_RECORDED
    identity = _ADV_SUMMARY_CHILD_RECEIPT
    path = _ADV_SUMMARY_CHILD_EVIDENCE_PATH
    if _ADV_SUMMARY_CHILD_EXIT_RECORDED or not isinstance(identity, Mapping) or path is None:
        return
    canary_report: Mapping[str, Any] | None = None
    try:
        report = json.loads(os.environ.get(CANARY_REPORT_ENV, ""))
        if isinstance(report, Mapping):
            canary_report = report
    except (TypeError, json.JSONDecodeError):
        canary_report = None
    if not isinstance(canary_report, Mapping):
        raise RouterStubError("summary child startup canary report is unavailable")
    stub = _ADV_SUMMARY_CHILD_STUB
    persisted = _child_summary_outputs_persisted(
        identity=identity,
        calls=_ADV_SUMMARY_CHILD_CALLS,
        writes=_ADV_SUMMARY_CHILD_WRITES,
    )
    failure_code = (
        stub.failure_code
        if stub is not None and stub.failure_code is not None
        else None if persisted else "summary_child_path_incomplete"
    )
    record = {
        "schema_version": 1,
        "run_id": identity["run_id"],
        "pid": os.getpid(),
        "process_group_id": os.getpgrp(),
        "process_role": os.environ.get(PROCESS_ROLE_ENV, ""),
        "command_sha256": identity["command_sha256"],
        "environment_sha256": canary_report.get("environment_sha256"),
        "startup_observed_at_ns": canary_report.get("startup_observed_at_ns"),
        "interpreter": canary_report.get("interpreter"),
        "source_sha": identity["source_sha"],
        "pythonpath": identity["pythonpath"],
        "script_sha256": identity["script_sha256"],
        "working_directory": identity["working_directory"],
        "area_id": identity["command"][5],
        "leaving_location_name": identity["command"][4],
        "router_call_count": stub.call_count if stub is not None else 0,
        "calls": list(_ADV_SUMMARY_CHILD_CALLS),
        "stub_failure_code": failure_code,
        "provider_request_attempted": False,
        "summary_output_persisted": persisted,
        "canonical_writes": list(_ADV_SUMMARY_CHILD_WRITES),
        "discarded_json_writes": [],
    }
    _append_adv_summary_child_evidence(
        path, record, run_id=str(identity["run_id"])
    )
    _ADV_SUMMARY_CHILD_EXIT_RECORDED = True


def _adv_summary_child_router_call(
    task: str, *args: Any, **kwargs: Any
) -> Any:
    stub = _ADV_SUMMARY_CHILD_STUB
    if not isinstance(stub, FailClosedRouterStub):
        raise RouterStubError("summary child router stub is unavailable")
    previous_count = stub.call_count
    try:
        response = stub(task, *args, **kwargs)
    except BaseException:
        if stub.call_count == previous_count + 1 and stub.calls:
            call = stub.calls[-1]
            _ADV_SUMMARY_CHILD_CALLS.append(
                {
                    "sequence": stub.call_count,
                    "task": call.get("task"),
                    "source_file": call.get("source_file"),
                    "source_line": call.get("source_line"),
                    "source_file_sha256": call.get("source_file_sha256"),
                    "response_kind": (
                        "summary_text"
                        if stub.call_count == 1
                        else "location_json"
                    ),
                    "response_sha256": None,
                    "failure_code": stub.failure_code or "summary_stub_call_failed",
                }
            )
        raise
    if (
        stub.call_count != previous_count + 1
        or stub.call_count > 2
        or not isinstance(response, str)
        or not response.strip()
    ):
        stub.failure_code = "summary_stub_response_invalid"
        raise RouterStubError("summary child stub response is invalid")
    call = stub.calls[-1]
    response_bytes = response.encode("utf-8")
    if len(response_bytes) > _CHILD_EVIDENCE_MAX_BYTES:
        stub.failure_code = "summary_stub_response_too_large"
        raise RouterStubError("summary child stub response is too large")
    response_kind = "summary_text" if stub.call_count == 1 else "location_json"
    if response_kind == "location_json":
        try:
            response_value = json.loads(response)
        except json.JSONDecodeError as exc:
            stub.failure_code = "summary_stub_location_response_invalid"
            raise RouterStubError("summary child location response is invalid") from exc
        canonical_response = json.dumps(
            response_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        response_value_sha256 = hashlib.sha256(canonical_response).hexdigest()
    else:
        response_value_sha256 = hashlib.sha256(response_bytes).hexdigest()
    _ADV_SUMMARY_CHILD_CALLS.append(
        {
            "sequence": stub.call_count,
            "task": call.get("task"),
            "source_file": call.get("source_file"),
            "source_line": call.get("source_line"),
            "source_file_sha256": call.get("source_file_sha256"),
            "response_kind": response_kind,
            "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "response_value_sha256": response_value_sha256,
            "failure_code": None,
        }
    )
    return response


class _AdvSummaryChildImportHook(importlib.abc.MetaPathFinder):
    """Patch only the router and JSON writer imported by adv_summary.py."""

    _TARGETS = frozenset(("utils.encoding_utils", "utils.llm_router"))

    def __init__(self) -> None:
        self.installed: set[str] = set()
        self.verified_sources: dict[str, Path] = {}

    def _activate_runtime(self) -> Mapping[str, Any]:
        global _ADV_SUMMARY_CHILD_CALLS
        global _ADV_SUMMARY_CHILD_EVIDENCE_PATH
        global _ADV_SUMMARY_CHILD_EXPECTED_AREA_PATH
        global _ADV_SUMMARY_CHILD_EXIT_HOOK_REGISTERED
        global _ADV_SUMMARY_CHILD_EXIT_RECORDED
        global _ADV_SUMMARY_CHILD_ORIGINAL_REMOVE
        global _ADV_SUMMARY_CHILD_RECEIPT
        global _ADV_SUMMARY_CHILD_RUNTIME_READY
        global _ADV_SUMMARY_CHILD_SANDBOX
        global _ADV_SUMMARY_CHILD_SOURCE_ROOT
        global _ADV_SUMMARY_CHILD_WRITES

        if _ADV_SUMMARY_CHILD_RUNTIME_READY:
            identity = _validate_adv_summary_child_identity()
            if identity != _ADV_SUMMARY_CHILD_RECEIPT:
                raise RouterStubError("summary child identity changed after startup")
            return identity
        if _ADV_SUMMARY_CHILD_HOOK is not self or self not in sys.meta_path:
            raise RouterStubError("summary child import guard is unavailable")
        identity = _validate_adv_summary_child_identity()
        try:
            require_current_invocation_matches_startup()
        except Exception as exc:
            raise RouterStubError(
                "summary child invocation changed after startup"
            ) from exc
        if _ADV_SUMMARY_CHILD_ORIGINAL_REMOVE is not None:
            raise RouterStubError("summary child remove guard was already installed")

        _ADV_SUMMARY_CHILD_RECEIPT = identity
        _ADV_SUMMARY_CHILD_EVIDENCE_PATH = identity["evidence_path"]
        _ADV_SUMMARY_CHILD_SANDBOX = Path(identity["working_directory"])
        _ADV_SUMMARY_CHILD_SOURCE_ROOT = Path(identity["source_root"])
        _ADV_SUMMARY_CHILD_CALLS = []
        _ADV_SUMMARY_CHILD_WRITES = []
        _ADV_SUMMARY_CHILD_EXPECTED_AREA_PATH = _child_expected_area_path(identity)
        _ADV_SUMMARY_CHILD_EXIT_RECORDED = False
        if not _ADV_SUMMARY_CHILD_EXIT_HOOK_REGISTERED:
            atexit.register(_record_adv_summary_child_exit)
            _ADV_SUMMARY_CHILD_EXIT_HOOK_REGISTERED = True
        _ADV_SUMMARY_CHILD_ORIGINAL_REMOVE = os.remove
        os.remove = _child_remove_guard  # type: ignore[assignment]
        if os.remove is not _child_remove_guard:
            raise RouterStubError("summary child remove guard installation failed")
        _ADV_SUMMARY_CHILD_RUNTIME_READY = True
        return identity

    def find_spec(
        self, fullname: str, path: Any = None, target: Any = None
    ) -> Any:
        del target
        if fullname not in self._TARGETS:
            return None
        identity = self._activate_runtime()
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        loader = getattr(spec, "loader", None)
        if spec is None or not callable(getattr(loader, "exec_module", None)):
            raise ImportError("preflight summary child import target is unavailable")
        origin = getattr(spec, "origin", None)
        if not isinstance(origin, (str, os.PathLike)):
            raise ImportError("preflight summary child module origin is unavailable")
        self.verified_sources[fullname] = self._verified_module_source(
            fullname, origin, identity
        )
        spec.loader = _AdvSummaryChildLoader(loader, self, fullname)
        return spec

    def _verified_module_source(
        self, fullname: str, origin: Any, identity: Mapping[str, Any]
    ) -> Path:
        sandbox = Path(identity["working_directory"])
        source_root = Path(identity["source_root"])
        relative_module = Path(*fullname.split(".")).with_suffix(".py")
        expected = sandbox / relative_module
        trusted_source = source_root / relative_module
        if not isinstance(origin, (str, os.PathLike)):
            raise ImportError("preflight summary child module origin is unavailable")
        try:
            imported_source = Path(origin).resolve(strict=True)
            if imported_source != expected.resolve(strict=True):
                raise ImportError("preflight summary child module source differs")
        except (OSError, RuntimeError) as exc:
            raise ImportError(
                "preflight summary child module source is unavailable"
            ) from exc
        if _safe_file_sha256(
            imported_source, expected_root=sandbox
        ) != _safe_file_sha256(trusted_source, expected_root=source_root):
            raise ImportError("preflight summary child module hash differs")
        return imported_source

    def verify_source_before_execution(self, fullname: str, origin: Any) -> None:
        identity = _ADV_SUMMARY_CHILD_RECEIPT
        if not isinstance(identity, Mapping):
            raise ImportError("preflight summary child identity is unavailable")
        verified = self._verified_module_source(fullname, origin, identity)
        if verified != self.verified_sources.get(fullname):
            raise ImportError("preflight summary child source changed before execution")

    def patch_loaded_module(self, fullname: str, module: Any) -> None:
        global _ADV_SUMMARY_CHILD_ORIGINAL_DUMP
        global _ADV_SUMMARY_CHILD_STUB
        if fullname not in self._TARGETS:
            raise RouterStubError("summary child import target is unsupported")
        identity = _ADV_SUMMARY_CHILD_RECEIPT
        sandbox = _ADV_SUMMARY_CHILD_SANDBOX
        source_root = _ADV_SUMMARY_CHILD_SOURCE_ROOT
        if (
            not isinstance(identity, Mapping)
            or sandbox is None
            or source_root is None
        ):
            raise RouterStubError("summary child module roots are unavailable")
        relative_module = Path(*fullname.split(".")).with_suffix(".py")
        expected = sandbox / relative_module
        trusted_source = source_root / relative_module
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, (str, os.PathLike)):
            raise RouterStubError("summary child imported module origin is unavailable")
        module_path = Path(origin)
        try:
            imported_source = module_path.resolve(strict=True)
            if (
                imported_source != expected.resolve(strict=True)
                or imported_source != self.verified_sources.get(fullname)
            ):
                raise RouterStubError("summary child imported module source differs")
        except (OSError, RuntimeError) as exc:
            raise RouterStubError("summary child imported module source is unavailable") from exc
        if _safe_file_sha256(
            imported_source, expected_root=sandbox
        ) != _safe_file_sha256(trusted_source, expected_root=source_root):
            raise RouterStubError("summary child imported module hash differs")

        if fullname == "utils.encoding_utils":
            original_dump = getattr(module, "safe_json_dump", None)
            if not callable(original_dump):
                raise RouterStubError("summary child JSON writer is unavailable")
            _ADV_SUMMARY_CHILD_ORIGINAL_DUMP = original_dump
            module.safe_json_dump = _child_json_write_sandboxed
            if module.safe_json_dump is not _child_json_write_sandboxed:
                raise RouterStubError("summary child JSON writer guard failed")
        else:
            router = getattr(module, "llm", None)
            if not callable(getattr(router, "call", None)):
                raise RouterStubError("summary child router boundary is unavailable")
            identity = _ADV_SUMMARY_CHILD_RECEIPT
            if not isinstance(identity, Mapping):
                raise RouterStubError("summary child invocation identity is unavailable")
            leaving_name, location = _child_summary_location(identity)
            stub = FailClosedRouterStub(
                source_sha=str(identity["source_sha"]),
                responses={"adventure_summary": _ADV_SUMMARY_RESPONSE},
                response_resolver=_AdvSummaryChildResponseResolver(
                    location=location,
                    leaving_location_name=leaving_name,
                ),
                command=identity["command"],
                pythonpath=str(identity["pythonpath"]),
                source_root=PROJECT_ROOT,
                max_calls=2,
            )
            _ADV_SUMMARY_CHILD_STUB = stub
            router.call = _adv_summary_child_router_call
            if router.call is not _adv_summary_child_router_call:
                raise RouterStubError("summary child router guard failed")
        self.installed.add(fullname)
        if self.installed == self._TARGETS and self in sys.meta_path:
            sys.meta_path.remove(self)


class _AdvSummaryChildLoader(importlib.abc.Loader):
    def __init__(
        self, loader: Any, hook: _AdvSummaryChildImportHook, fullname: str
    ) -> None:
        self.loader = loader
        self.hook = hook
        self.fullname = fullname

    def create_module(self, spec: Any) -> Any:
        create_module = getattr(self.loader, "create_module", None)
        return create_module(spec) if callable(create_module) else None

    def exec_module(self, module: Any) -> None:
        self.hook.verify_source_before_execution(
            self.fullname,
            getattr(getattr(module, "__spec__", None), "origin", None),
        )
        self.loader.exec_module(module)
        self.hook.patch_loaded_module(self.fullname, module)


def install_adv_summary_preflight_child_hooks() -> None:
    """Defer child validation until sitecustomize has completed its canary."""
    global _ADV_SUMMARY_CHILD_HOOK

    _require_network_guard()
    if (
        os.environ.get(ADV_SUMMARY_CHILD_MODE_ENV) != ADV_SUMMARY_CHILD_MODE
        or os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(PROCESS_ROLE_ENV) != "host"
    ):
        raise RouterStubError("summary child startup mode is invalid")
    try:
        require_sanitized_environment()
    except Exception as exc:
        raise RouterStubError("summary child environment is not sanitized") from exc
    if _ADV_SUMMARY_CHILD_HOOK is not None:
        if (
            _ADV_SUMMARY_CHILD_HOOK not in sys.meta_path
            and _ADV_SUMMARY_CHILD_HOOK.installed
            != _ADV_SUMMARY_CHILD_HOOK._TARGETS
        ):
            raise RouterStubError("summary child import guard was removed")
        return

    hook = _AdvSummaryChildImportHook()
    if any(fullname in sys.modules for fullname in hook._TARGETS):
        raise RouterStubError("summary child modules were imported before the guard")
    sys.meta_path.insert(0, hook)
    _ADV_SUMMARY_CHILD_HOOK = hook


def _is_adv_summary_command(value: Any) -> bool:
    candidates: Sequence[Any]
    if isinstance(value, (list, tuple)):
        candidates = value
    else:
        candidates = (value,)
    for item in candidates:
        if isinstance(item, str) and (
            item == "adv_summary.py" or item.endswith("/adv_summary.py")
        ):
            return True
    return False


def _prepare_child_evidence_file(path: Path) -> None:
    cursor = PROJECT_ROOT
    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise RouterStubError("summary child evidence path escaped the project") from exc
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RouterStubError("summary child evidence path traverses a symlink")
    if not path.parent.is_dir():
        raise RouterStubError("summary child evidence directory is unavailable")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise RouterStubError("summary child evidence file cannot be initialized") from exc
    else:
        os.close(descriptor)


def _read_adv_summary_child_records(path: Path) -> list[dict[str, Any]]:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > _CHILD_EVIDENCE_MAX_BYTES
        ):
            raise RouterStubError("summary child evidence file is invalid")
        raw = os.read(descriptor, _CHILD_EVIDENCE_MAX_BYTES + 1)
        if len(raw) > _CHILD_EVIDENCE_MAX_BYTES or (raw and not raw.endswith(b"\n")):
            raise RouterStubError("summary child evidence file is incomplete")
        records: list[dict[str, Any]] = []
        for line in raw.splitlines():
            value = json.loads(line.decode("ascii"), object_pairs_hook=_unique_json_object)
            if not isinstance(value, Mapping):
                raise RouterStubError("summary child evidence record is invalid")
            records.append(dict(value))
            if len(records) > _CHILD_EVIDENCE_MAX_RECORDS:
                raise RouterStubError("summary child evidence record limit exceeded")
        return records
    except RouterStubError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RouterStubError("summary child evidence cannot be read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate summary child evidence key")
        result[key] = value
    return result


class AdvSummaryPreflightHostInterceptor:
    """Canary and authorize only the exact adv_summary.py child launch."""

    def __init__(
        self,
        *,
        source_sha: str,
        sandbox_root: str | Path,
        evidence_path: str | Path,
    ) -> None:
        _require_network_guard()
        require_startup_guard_active()
        require_current_invocation_matches_startup()
        require_sanitized_environment()
        if (
            os.environ.get(PROCESS_ROLE_ENV) != "host"
            or _SHA.fullmatch(source_sha) is None
        ):
            raise RouterStubError("summary child host identity is invalid")
        self.source_sha = source_sha
        self.sandbox_root = Path(sandbox_root).resolve(strict=True)
        project_tmp = PROJECT_ROOT / "tmp"
        if project_tmp.is_symlink() or not project_tmp.is_dir():
            raise RouterStubError("summary child host temporary root is unavailable")
        try:
            self.sandbox_root.relative_to(project_tmp.resolve(strict=True))
        except ValueError as exc:
            raise RouterStubError(
                "summary child host is outside the project temporary root"
            ) from exc
        cursor = project_tmp
        for part in self.sandbox_root.relative_to(project_tmp.resolve(strict=True)).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RouterStubError("summary child host sandbox traverses a symlink")
        if Path.cwd().resolve(strict=True) != self.sandbox_root:
            raise RouterStubError("summary child host working directory differs")
        self.row_command = _redact_command(current_invocation_command())
        self.row_pythonpath = os.environ.get("PYTHONPATH", "")
        self.run_id = os.environ.get(RUN_ID_ENV, "")
        self.evidence_path = Path(evidence_path)
        if self.evidence_path != _adv_summary_child_evidence_path(run_id=self.run_id):
            raise RouterStubError("summary child host evidence path is invalid")
        _prepare_child_evidence_file(self.evidence_path)
        self.original_run = subprocess.run
        self.launches: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.failure_code: str | None = None
        self._active = True

        def guarded_run(*args: Any, **kwargs: Any) -> Any:
            candidate = args[0] if args else None
            if not _is_adv_summary_command(candidate):
                return self.original_run(*args, **kwargs)
            return self._run_adv_summary(*args, **kwargs)

        self._guarded_run = guarded_run
        subprocess.run = guarded_run  # type: ignore[assignment]
        if subprocess.run is not guarded_run:
            raise RouterStubError("summary child host interceptor installation failed")

    def _run_adv_summary(self, *args: Any, **kwargs: Any) -> Any:
        if self.failure_code is not None:
            raise RouterStubError("summary child host interceptor is already failed")
        if len(self.launches) >= _CHILD_EVIDENCE_MAX_RECORDS:
            self.failure_code = "summary_child_launch_limit_exceeded"
            raise RouterStubError("summary child launch limit exceeded")
        if (
            len(args) != 1
            or set(kwargs) != {"check", "capture_output", "text"}
            or kwargs.get("check") is not True
            or kwargs.get("capture_output") is not True
            or kwargs.get("text") is not True
        ):
            self.failure_code = "summary_child_run_options_mismatch"
            raise RouterStubError("summary child subprocess.run options differ")
        command_value = args[0]
        if (
            not isinstance(command_value, (list, tuple))
            or len(command_value) != 6
            or any(not isinstance(item, str) for item in command_value)
        ):
            self.failure_code = "summary_child_command_invalid"
            raise RouterStubError("summary child command is invalid")
        command = list(command_value)
        expected_script = str(self.sandbox_root / "core" / "ai" / "adv_summary.py")
        if (
            command[0] != os.environ.get(EXPECTED_PYTHON_ENV)
            or command[0] != sys.executable
            or command[1] != expected_script
            or command[2] != "modules/conversation_history/conversation_history.json"
            or command[3] != "current_location.json"
            or not command[4]
            or len(command[4]) > 512
            or "\x00" in command[4]
            or "\n" in command[4]
            or "\r" in command[4]
            or _AREA_ID.fullmatch(command[5]) is None
        ):
            self.failure_code = "summary_child_command_identity_mismatch"
            raise RouterStubError("summary child command identity differs")

        script_path = self.sandbox_root / "core" / "ai" / "adv_summary.py"
        repository_script = PROJECT_ROOT / "core" / "ai" / "adv_summary.py"
        try:
            script_sha256 = _safe_file_sha256(
                script_path, expected_root=PROJECT_ROOT
            )
            if script_sha256 != _safe_file_sha256(
                repository_script, expected_root=PROJECT_ROOT
            ):
                raise RouterStubError("summary child script differs from the source")
        except RouterStubError:
            self.failure_code = "summary_child_script_identity_mismatch"
            raise

        effective_cwd = str(self.sandbox_root)
        child_env = dict(os.environ)
        # This startup handshake is set by sitecustomize after its canary and
        # is removed before every process computes its own startup identity.
        # Do not propagate the parent process's post-canary marker to the
        # child prelaunch environment.
        child_env.pop(STARTUP_GUARD_ENV, None)
        child_env[ADV_SUMMARY_CHILD_MODE_ENV] = ADV_SUMMARY_CHILD_MODE
        child_env[ADV_SUMMARY_CHILD_SOURCE_SHA_ENV] = self.source_sha
        child_env[ADV_SUMMARY_CHILD_SOURCE_ROOT_ENV] = str(PROJECT_ROOT)
        child_env[ADV_SUMMARY_CHILD_COMMAND_SHA_ENV] = _command_sha256(command)
        child_env[ADV_SUMMARY_CHILD_CWD_ENV] = effective_cwd
        child_env[ADV_SUMMARY_CHILD_EVIDENCE_ENV] = str(self.evidence_path)
        for name, value in child_env.items():
            if (
                ("SECRET" in name.upper() or "TOKEN" in name.upper()
                 or "PASSWORD" in name.upper() or "API_KEY" in name.upper()
                 or name.upper().endswith("_PROXY"))
                and value
            ):
                self.failure_code = "summary_child_environment_contains_secret"
                raise RouterStubError("summary child environment is not secret-free")

        launch: dict[str, Any] = {
            "sequence": len(self.launches) + 1,
            "command_sha256": child_env[ADV_SUMMARY_CHILD_COMMAND_SHA_ENV],
            "script_sha256": script_sha256,
            "working_directory": effective_cwd,
            "parent_pid": os.getpid(),
            "parent_process_group_id": os.getpgrp(),
            "prelaunch_canary_pid": None,
            "prelaunch_startup_observed_at_ns": None,
            "child_pid": None,
            "child_process_group_id": None,
            "environment_sha256": None,
            "interpreter": None,
            "returncode": None,
            "call_evidence_count": 0,
            "summary_child_succeeded": False,
        }
        self.launches.append(launch)
        before_records = _read_adv_summary_child_records(self.evidence_path)
        try:
            canary = run_startup_process_canary(
                command=command,
                cwd=effective_cwd,
                env=child_env,
            )
            if (
                canary.get("command") != command
                or canary.get("command_sha256") != launch["command_sha256"]
                or canary.get("working_directory") != effective_cwd
                or canary.get("process_role") != "host"
                or type(canary.get("pid")) is not int
                or canary.get("pid") <= 0
                or type(canary.get("startup_observed_at_ns")) is not int
                or canary.get("startup_observed_at_ns") <= 0
                or canary.get("guard_active") is not True
                or canary.get("non_loopback_connect_denied") is not True
                or canary.get("subprocess_launch_denied") is not True
                or not isinstance(canary.get("environment_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", canary["environment_sha256"]) is None
                or canary.get("interpreter")
                != {
                    "executable": command[0],
                    "prefix": os.environ.get(EXPECTED_PREFIX_ENV),
                    "base_prefix": sys.base_prefix,
                }
            ):
                raise RouterStubError("summary child startup canary did not reconcile")
            launch["prelaunch_canary_pid"] = canary.get("pid")
            launch["prelaunch_startup_observed_at_ns"] = canary.get(
                "startup_observed_at_ns"
            )
            launch["environment_sha256"] = canary.get("environment_sha256")
            launch["interpreter"] = dict(canary["interpreter"])

            try:
                with authorize_subprocess_launch(
                    command, cwd=effective_cwd, env=child_env
                ):
                    completed = self.original_run(
                        command,
                        cwd=effective_cwd,
                        env=child_env,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
            except subprocess.CalledProcessError as exc:
                launch["returncode"] = exc.returncode
                records = _read_adv_summary_child_records(self.evidence_path)
                new_records = records[len(before_records):]
                if len(new_records) == 1:
                    launch["child_pid"] = new_records[0].get("pid")
                    launch["child_process_group_id"] = new_records[0].get(
                        "process_group_id"
                    )
                    child_calls = new_records[0].get("calls")
                    if isinstance(child_calls, list):
                        launch["call_evidence_count"] = len(child_calls)
                self.failure_code = "summary_child_process_failed"
                raise
            launch["returncode"] = getattr(completed, "returncode", None)
            records = _read_adv_summary_child_records(self.evidence_path)
            new_records = records[len(before_records):]
            if len(new_records) != 1:
                self.failure_code = "summary_child_call_evidence_missing"
                raise RouterStubError("summary child evidence record is missing")
            record = new_records[0]
            valid = _validate_adv_summary_child_record(
                record,
                run_id=self.run_id,
                command_sha256=launch["command_sha256"],
                environment_sha256=launch["environment_sha256"],
                source_sha=self.source_sha,
                pythonpath=child_env.get("PYTHONPATH", ""),
                script_sha256=script_sha256,
                working_directory=effective_cwd,
                interpreter=launch["interpreter"],
            )
            launch["child_pid"] = record.get("pid")
            launch["child_process_group_id"] = record.get("process_group_id")
            child_calls = record.get("calls")
            launch["call_evidence_count"] = (
                len(child_calls) if isinstance(child_calls, list) else 0
            )
            if not valid:
                self.failure_code = "summary_child_call_evidence_invalid"
                raise RouterStubError("summary child success evidence is invalid")
            if (
                launch["returncode"] != 0
                or record.get("pid") == launch["prelaunch_canary_pid"]
                or record.get("process_group_id")
                != launch["parent_process_group_id"]
            ):
                self.failure_code = "summary_child_process_identity_or_exit_invalid"
                raise RouterStubError("summary child process identity or exit differs")
            launch["summary_child_succeeded"] = True
            for call in child_calls:
                self.calls.append(
                    {
                        "sequence": len(self.calls) + 1,
                        "task": call["task"],
                        "source_file": call["source_file"],
                        "source_line": call["source_line"],
                        "source_file_sha256": call["source_file_sha256"],
                        "source_sha": self.source_sha,
                        "command_sha256": launch["command_sha256"],
                        "environment_sha256": launch["environment_sha256"],
                        "process_id": record["pid"],
                        "process_role": "adv_summary_child",
                        "response_kind": call["response_kind"],
                        "response_sha256": call["response_sha256"],
                    }
                )
            return completed
        except BaseException as exc:
            if self.failure_code is None:
                self.failure_code = (
                    "summary_child_launch_failed_" + type(exc).__name__
                )
            raise

    def cleanup(self) -> None:
        if not self._active:
            return
        if subprocess.run is not self._guarded_run:
            self.failure_code = self.failure_code or "summary_child_interceptor_replaced"
            raise RouterStubError("summary child host interceptor changed")
        subprocess.run = self.original_run  # type: ignore[assignment]
        self._active = False


def _validate_adv_summary_child_record(
    record: Mapping[str, Any],
    *,
    run_id: str,
    command_sha256: str,
    environment_sha256: Any,
    source_sha: str,
    pythonpath: str,
    script_sha256: str,
    working_directory: str,
    interpreter: Mapping[str, Any],
) -> bool:
    record_fields = {
        "schema_version",
        "run_id",
        "pid",
        "process_group_id",
        "process_role",
        "command_sha256",
        "environment_sha256",
        "startup_observed_at_ns",
        "interpreter",
        "source_sha",
        "pythonpath",
        "script_sha256",
        "working_directory",
        "area_id",
        "leaving_location_name",
        "router_call_count",
        "calls",
        "stub_failure_code",
        "provider_request_attempted",
        "summary_output_persisted",
        "canonical_writes",
        "discarded_json_writes",
    }
    call_fields = {
        "sequence",
        "task",
        "source_file",
        "source_line",
        "source_file_sha256",
        "response_kind",
        "response_sha256",
        "response_value_sha256",
        "failure_code",
    }
    write_fields = {
        "sequence",
        "source_file",
        "source_line",
        "path",
        "sha256",
        "size_bytes",
        "retained_artifact",
    }
    retained_artifact_fields = {
        "path",
        "source_path",
        "sha256",
        "size_bytes",
        "run_id",
        "source_sha",
        "command_sha256",
        "process_id",
        "process_role",
        "write_sequence",
        "provenance",
    }
    record_interpreter = record.get("interpreter")
    calls = record.get("calls")
    writes = record.get("canonical_writes")
    discarded = record.get("discarded_json_writes")
    valid_interpreter = (
        isinstance(record_interpreter, Mapping)
        and set(record_interpreter) == {"executable", "prefix", "base_prefix"}
        and all(
            isinstance(record_interpreter.get(key), str)
            for key in record_interpreter
        )
    )
    if not (
        set(record) == record_fields
        and type(record.get("schema_version")) is int
        and record.get("schema_version") == 1
        and record.get("run_id") == run_id
        and type(record.get("pid")) is int
        and record.get("pid", 0) > 0
        and type(record.get("process_group_id")) is int
        and record.get("process_group_id", 0) > 0
        and record.get("process_role") == "host"
        and record.get("command_sha256") == command_sha256
        and isinstance(record.get("command_sha256"), str)
        and _SHA.fullmatch(record["command_sha256"]) is not None
        and record.get("environment_sha256") == environment_sha256
        and isinstance(record.get("environment_sha256"), str)
        and _SHA.fullmatch(record["environment_sha256"]) is not None
        and type(record.get("startup_observed_at_ns")) is int
        and record.get("startup_observed_at_ns", 0) > 0
        and valid_interpreter
        and isinstance(interpreter, Mapping)
        and dict(record_interpreter) == dict(interpreter)
        and record.get("source_sha") == source_sha
        and record.get("pythonpath") == pythonpath
        and record.get("script_sha256") == script_sha256
        and isinstance(record.get("script_sha256"), str)
        and _SHA.fullmatch(record["script_sha256"]) is not None
        and record.get("working_directory") == working_directory
        and isinstance(record.get("area_id"), str)
        and _AREA_ID.fullmatch(record["area_id"]) is not None
        and isinstance(record.get("leaving_location_name"), str)
        and 0 < len(record["leaving_location_name"]) <= 512
        and type(record.get("router_call_count")) is int
        and record.get("router_call_count") == 2
        and isinstance(calls, list)
        and len(calls) == 2
        and record.get("stub_failure_code") is None
        and record.get("provider_request_attempted") is False
        and record.get("summary_output_persisted") is True
        and isinstance(writes, list)
        and len(writes) == 6
        and all(
            isinstance(item, Mapping)
            and set(item) == write_fields
            and isinstance(item.get("retained_artifact"), Mapping)
            and set(item["retained_artifact"]) == retained_artifact_fields
            and isinstance(item["retained_artifact"].get("path"), str)
            and item["retained_artifact"]["path"].startswith("tmp/")
            and item["retained_artifact"].get("source_path")
            == "tmp/combat_capture/" + str(item.get("path"))
            and item["retained_artifact"].get("sha256") == item.get("sha256")
            and item["retained_artifact"].get("size_bytes") == item.get("size_bytes")
            and item["retained_artifact"].get("run_id") == run_id
            and item["retained_artifact"].get("source_sha") == source_sha
            and item["retained_artifact"].get("command_sha256")
            == command_sha256
            and item["retained_artifact"].get("process_id") == record.get("pid")
            and item["retained_artifact"].get("process_role") == "host"
            and item["retained_artifact"].get("write_sequence")
            == item.get("sequence")
            and item["retained_artifact"].get("provenance")
            == "guarded_canonical_json_writer"
            for item in writes
        )
        and isinstance(discarded, list)
        and not discarded
    ):
        return False

    expected_call_kinds = ("summary_text", "location_json")
    for index, (call, response_kind) in enumerate(
        zip(calls, expected_call_kinds), start=1
    ):
        if (
            not isinstance(call, Mapping)
            or set(call) != call_fields
            or type(call.get("sequence")) is not int
            or call.get("sequence") != index
            or call.get("task") != "adventure_summary"
            or call.get("source_file")
            != "tmp/combat_capture/core/ai/adv_summary.py"
            or type(call.get("source_line")) is not int
            or call.get("source_line", 0) <= 0
            or call.get("source_file_sha256") != script_sha256
            or call.get("response_kind") != response_kind
            or not isinstance(call.get("response_sha256"), str)
            or _SHA.fullmatch(call["response_sha256"]) is None
            or not isinstance(call.get("response_value_sha256"), str)
            or _SHA.fullmatch(call["response_value_sha256"]) is None
            or call.get("failure_code") is not None
        ):
            return False
        if (
            response_kind == "summary_text"
            and call.get("response_sha256") != call.get("response_value_sha256")
        ):
            return False

    identity = {
        "working_directory": working_directory,
        "command": ["", "", "", "", record["leaving_location_name"], record["area_id"]],
    }
    return _child_summary_outputs_persisted(
        identity=identity,
        calls=calls,
        writes=writes,
    )


def install_adv_summary_preflight_host_interceptor(
    *,
    source_sha: str,
    sandbox_root: str | Path,
    evidence_path: str | Path,
) -> AdvSummaryPreflightHostInterceptor:
    """Install the canary-first, exact one-use child launch adapter."""
    return AdvSummaryPreflightHostInterceptor(
        source_sha=source_sha,
        sandbox_root=sandbox_root,
        evidence_path=evidence_path,
    )
