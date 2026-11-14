# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Counting, fail-closed router stub for later isolated characterization."""

from __future__ import annotations

import copy
import hashlib
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from scripts.live_gate_preflight_safety import NetworkGuardError, require_guard_active


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SECRET_ARGUMENT = re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)
_SAFE_TASK = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
DEFAULT_MAX_CALLS = 256


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
        del args, kwargs
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
