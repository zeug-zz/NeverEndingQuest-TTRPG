# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Fail-closed, cross-process provider-attempt budget for isolated N2 runs."""

from __future__ import annotations

import contextlib
import importlib
import ipaddress
import json
import os
import re
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from utils.repo_paths import PathBoundaryError, repository_root, resolve_contained_path


PROVIDER_ATTEMPT_BUDGET_ENV = "NEQ_PROVIDER_ATTEMPT_BUDGET"
PROVIDER_ATTEMPT_LEDGER_ENV = "NEQ_PROVIDER_ATTEMPT_LEDGER"
PROVIDER_ATTEMPT_RUN_ID_ENV = "NEQ_PROVIDER_ATTEMPT_RUN_ID"
MAX_PROVIDER_ATTEMPT_BUDGET = 30
_LEDGER_SCHEMA_VERSION = 1
_MAX_LEDGER_BYTES = 1024 * 1024
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


class ProviderAttemptBudgetConfigurationError(RuntimeError):
    """Raised during startup when an enabled budget cannot be safely installed."""


class ProviderAttemptBudgetUnavailable(BaseException):
    """Fail-closed transport sentinel for ledger or reservation failures."""


class ProviderAttemptBudgetExceeded(BaseException):
    """Fail-closed sentinel that must bypass SDK retry and fallback handlers."""

    def __init__(self, reservation_number: int, budget: int) -> None:
        self.reservation_number = reservation_number
        self.budget = budget
        super().__init__(
            "provider attempt budget exhausted ({0} reservations; dispatch #{1} refused)".format(
                budget, reservation_number
            )
        )


@dataclass(frozen=True)
class _BudgetConfig:
    runtime_root: Path
    ledger_path: Path
    budget: int
    run_id: str


_ACTIVATION_LOCK = threading.RLock()
_ACTIVE_CONFIG: Optional[_BudgetConfig] = None
_ACTIVATION_ERROR: Optional[BaseException] = None


def _is_isolated_capture_root(runtime_root: Path) -> bool:
    """Match the existing N2 capture-root proof without consulting cwd."""
    for capture_root in (runtime_root, *runtime_root.parents):
        if capture_root.name != "combat_capture" or capture_root.parent.name != "tmp":
            continue
        repository = capture_root.parent.parent
        if (repository / "AGENTS.md").is_file() and (repository / "model_config.py").is_file():
            return True
    return False


def _configuration_from_environment() -> Optional[_BudgetConfig]:
    configured_names = (
        PROVIDER_ATTEMPT_BUDGET_ENV,
        PROVIDER_ATTEMPT_LEDGER_ENV,
        PROVIDER_ATTEMPT_RUN_ID_ENV,
    )
    if not any(name in os.environ for name in configured_names):
        return None

    if any(name not in os.environ for name in configured_names):
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt budget activation is partial; refusing startup"
        )

    budget_text = os.environ[PROVIDER_ATTEMPT_BUDGET_ENV]
    if not re.fullmatch(r"[0-9]+", budget_text):
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt budget must be a positive decimal integer"
        )
    budget = int(budget_text)
    if budget < 1 or budget > MAX_PROVIDER_ATTEMPT_BUDGET:
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt budget must be between 1 and 30"
        )

    run_id = os.environ[PROVIDER_ATTEMPT_RUN_ID_ENV]
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt run ID is invalid; refusing startup"
        )

    try:
        runtime_root = repository_root().resolve(strict=True)
    except Exception as exc:
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt runtime root is unavailable; refusing startup"
        ) from exc
    if not _is_isolated_capture_root(runtime_root):
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt budget is enabled outside tmp/combat_capture; refusing startup"
        )

    ledger_text = os.environ[PROVIDER_ATTEMPT_LEDGER_ENV]
    ledger_input = Path(ledger_text)
    if not ledger_input.is_absolute():
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt ledger must be an absolute sandbox path"
        )
    try:
        ledger_path = resolve_contained_path(
            ledger_input,
            runtime_root,
            relative_only=False,
            allow_missing=True,
            reject_symlinks=True,
        )
        ledger_path.relative_to(runtime_root / "tmp" / "n2")
    except (PathBoundaryError, ValueError) as exc:
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt ledger must remain below sandbox tmp/n2"
        ) from exc
    if ledger_path == runtime_root / "tmp" / "n2":
        raise ProviderAttemptBudgetConfigurationError(
            "provider attempt ledger must name a file below sandbox tmp/n2"
        )

    return _BudgetConfig(runtime_root, ledger_path, budget, run_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_ledger_path(config: _BudgetConfig) -> None:
    try:
        safe_path = resolve_contained_path(
            config.ledger_path,
            config.runtime_root,
            relative_only=False,
            allow_missing=True,
            reject_symlinks=True,
        )
    except PathBoundaryError as exc:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger path is unsafe; dispatch refused"
        ) from exc
    if safe_path != config.ledger_path:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger path changed; dispatch refused"
        )


@contextlib.contextmanager
def _locked_ledger(config: _BudgetConfig) -> Iterator[int]:
    descriptor: Optional[int] = None
    fcntl: Any = None
    try:
        fcntl = importlib.import_module("fcntl")
        config.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        _validate_ledger_path(config)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is not None:
            flags |= nofollow
        elif config.ledger_path.is_symlink():
            raise OSError("provider attempt ledger must not be a symlink")
        descriptor = os.open(config.ledger_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        file_stat = os.fstat(descriptor)
        path_stat = os.lstat(config.ledger_path)
        if not stat.S_ISREG(file_stat.st_mode) or (
            file_stat.st_dev,
            file_stat.st_ino,
        ) != (path_stat.st_dev, path_stat.st_ino):
            raise OSError("provider attempt ledger is not a stable regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except Exception as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger is unavailable; dispatch refused"
        ) from exc

    try:
        yield descriptor
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except Exception as exc:
            raise ProviderAttemptBudgetUnavailable(
                "provider attempt ledger lock could not be released; dispatch refused"
            ) from exc
        finally:
            os.close(descriptor)


def _read_records(descriptor: int, config: _BudgetConfig) -> list[dict[str, Any]]:
    file_size = os.fstat(descriptor).st_size
    if file_size > _MAX_LEDGER_BYTES:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger exceeded its size bound; dispatch refused"
        )
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = file_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65_536))
        if not chunk:
            raise ProviderAttemptBudgetUnavailable(
                "provider attempt ledger changed while locked; dispatch refused"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    contents = b"".join(chunks)
    if not contents:
        return []
    if not contents.endswith(b"\n"):
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger has an incomplete record; dispatch refused"
        )
    try:
        lines = contents.decode("ascii").splitlines()
        records = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger is malformed; dispatch refused"
        ) from exc
    if not records or not isinstance(records[0], dict):
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger header is missing; dispatch refused"
        )
    header = records[0]
    if (header.get("event") != "header" or
            header.get("schema_version") != _LEDGER_SCHEMA_VERSION or
            header.get("budget") != config.budget or
            header.get("run_id") != config.run_id):
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger identity does not match activation; dispatch refused"
        )

    reservation_count = 0
    activation_count = 0
    for record in records[1:]:
        if (not isinstance(record, dict) or
                record.get("schema_version") != _LEDGER_SCHEMA_VERSION or
                record.get("budget") != config.budget or
                record.get("run_id") != config.run_id):
            raise ProviderAttemptBudgetUnavailable(
                "provider attempt ledger contains an invalid record; dispatch refused"
            )
        event = record.get("event")
        if event == "activated":
            if (record.get("transport_guard") != "httpx-client-single-request" or
                    not isinstance(record.get("pid"), int) or
                    isinstance(record.get("pid"), bool) or record.get("pid") < 1):
                raise ProviderAttemptBudgetUnavailable(
                    "provider attempt activation record is invalid; dispatch refused"
                )
            activation_count += 1
        elif event == "reservation":
            if activation_count == 0:
                raise ProviderAttemptBudgetUnavailable(
                    "provider attempt ledger has no activation before reservation; dispatch refused"
                )
            reservation_count += 1
            if record.get("reservation_number") != reservation_count:
                raise ProviderAttemptBudgetUnavailable(
                    "provider attempt reservation sequence is invalid; dispatch refused"
                )
        elif event == "refusal":
            if (activation_count == 0 or reservation_count < config.budget or
                    record.get("reservation_number") != config.budget + 1 or
                    record.get("reason") != "budget_exhausted"):
                raise ProviderAttemptBudgetUnavailable(
                    "provider attempt refusal record is invalid; dispatch refused"
                )
        else:
            raise ProviderAttemptBudgetUnavailable(
                "provider attempt ledger contains an unknown event; dispatch refused"
            )
    if reservation_count > config.budget:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt ledger exceeded its configured budget; dispatch refused"
        )
    return records


def _append_record(descriptor: int, record: dict[str, Any]) -> None:
    contents = (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")
    offset = 0
    while offset < len(contents):
        offset += os.write(descriptor, contents[offset:])
    os.fsync(descriptor)


def _record_base(event: str, config: _BudgetConfig) -> dict[str, Any]:
    return {
        "event": event,
        "schema_version": _LEDGER_SCHEMA_VERSION,
        "pid": os.getpid(),
        "timestamp_utc": _utc_now(),
        "budget": config.budget,
        "run_id": config.run_id,
    }


def _append_activation(config: _BudgetConfig) -> None:
    with _locked_ledger(config) as descriptor:
        records = _read_records(descriptor, config)
        if not records:
            header = {
                "event": "header",
                "schema_version": _LEDGER_SCHEMA_VERSION,
                "budget": config.budget,
                "run_id": config.run_id,
            }
            _append_record(descriptor, header)
        activation = _record_base("activated", config)
        activation["transport_guard"] = "httpx-client-single-request"
        _append_record(descriptor, activation)


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip("[]").rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _safe_path(request: Any) -> str:
    path = str(request.url.path)
    path = "".join(character for character in path if character >= " " and character != "\x7f")
    return path[:512]


def _reserve_request(request: Any) -> None:
    config = _ACTIVE_CONFIG
    if config is None:
        return

    host = str(request.url.host)
    if _is_loopback_host(host):
        return

    method = str(request.method).upper()[:16]
    path = _safe_path(request)
    try:
        with _locked_ledger(config) as descriptor:
            records = _read_records(descriptor, config)
            if not records or not any(record.get("event") == "activated" for record in records):
                raise ProviderAttemptBudgetUnavailable(
                    "provider attempt ledger was not activated; dispatch refused"
                )
            reservation_count = sum(
                record.get("event") == "reservation" for record in records
            )
            if reservation_count >= config.budget:
                refusal = _record_base("refusal", config)
                refusal.update({
                    "reservation_number": reservation_count + 1,
                    "reason": "budget_exhausted",
                    "host": host[:253],
                    "method": method,
                    "path": path,
                })
                _append_record(descriptor, refusal)
                raise ProviderAttemptBudgetExceeded(
                    reservation_count + 1, config.budget
                )

            reservation = _record_base("reservation", config)
            reservation.update({
                "reservation_number": reservation_count + 1,
                "host": host[:253],
                "method": method,
                "path": path,
            })
            _append_record(descriptor, reservation)
    except (ProviderAttemptBudgetExceeded, ProviderAttemptBudgetUnavailable):
        raise
    except Exception as exc:
        raise ProviderAttemptBudgetUnavailable(
            "provider attempt reservation failed; dispatch refused"
        ) from exc


def _install_httpx_guard() -> None:
    try:
        import httpx
    except Exception as exc:
        raise ProviderAttemptBudgetConfigurationError(
            "HTTPX is unavailable for provider attempt enforcement"
        ) from exc

    sync_method = getattr(httpx.Client, "_send_single_request", None)
    async_method = getattr(httpx.AsyncClient, "_send_single_request", None)
    if not callable(sync_method) or not callable(async_method):
        raise ProviderAttemptBudgetConfigurationError(
            "HTTPX dispatch hooks are unavailable; refusing startup"
        )

    if not getattr(sync_method, "_neq_provider_attempt_guard", False):
        original_sync_method = sync_method

        def guarded_sync_send(self: Any, request: Any) -> Any:
            _reserve_request(request)
            return original_sync_method(self, request)

        guarded_sync_send._neq_provider_attempt_guard = True  # type: ignore[attr-defined]
        httpx.Client._send_single_request = guarded_sync_send

    if not getattr(async_method, "_neq_provider_attempt_guard", False):
        original_async_method = async_method

        async def guarded_async_send(self: Any, request: Any) -> Any:
            _reserve_request(request)
            return await original_async_method(self, request)

        guarded_async_send._neq_provider_attempt_guard = True  # type: ignore[attr-defined]
        httpx.AsyncClient._send_single_request = guarded_async_send


# TABLETOP MODE: Install the sandbox-only guard at the shared HTTPX dispatch seam;
# the bounded file lock makes router retries, direct SDK calls, and child processes share one cap.
def activate_provider_attempt_budget() -> Optional[Path]:
    """Activate only for an explicit, validated isolated-capture environment.

    With no activation variables this performs no path resolution, filesystem
    access, HTTPX import, or transport patch. Partial or invalid activation
    raises before the application can start serving requests.
    """
    global _ACTIVE_CONFIG, _ACTIVATION_ERROR
    with _ACTIVATION_LOCK:
        if _ACTIVATION_ERROR is not None:
            raise ProviderAttemptBudgetConfigurationError(
                "provider attempt budget activation previously failed; refusing startup"
            ) from _ACTIVATION_ERROR
        config = _configuration_from_environment()
        if config is None:
            return None
        if _ACTIVE_CONFIG is not None:
            if config != _ACTIVE_CONFIG:
                raise ProviderAttemptBudgetConfigurationError(
                    "provider attempt budget activation changed within one process"
                )
            return config.ledger_path

        _ACTIVE_CONFIG = config
        try:
            _install_httpx_guard()
            _append_activation(config)
        except BaseException as exc:
            _ACTIVATION_ERROR = exc
            raise
        return config.ledger_path


__all__ = [
    "MAX_PROVIDER_ATTEMPT_BUDGET",
    "PROVIDER_ATTEMPT_BUDGET_ENV",
    "PROVIDER_ATTEMPT_LEDGER_ENV",
    "PROVIDER_ATTEMPT_RUN_ID_ENV",
    "ProviderAttemptBudgetConfigurationError",
    "ProviderAttemptBudgetExceeded",
    "ProviderAttemptBudgetUnavailable",
    "activate_provider_attempt_budget",
]
