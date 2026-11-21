# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Opt-in interpreter startup guard for provider-free preflight children."""

from __future__ import annotations

import json
import importlib.abc
import importlib.machinery
import os
import sys
from pathlib import Path
from typing import Any


_CONFIG_IMPORT_ORIGIN_GUARD: Any = None
_STARTUP_ENVIRONMENT: dict[str, str] | None = None


class _ConfigImportOriginGuard(importlib.abc.MetaPathFinder):
    """Allow config imports only from the synthetic capture sandbox."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.project_config = project_root / "config.py"
        self.project_tmp = project_root / "tmp"
        self.sandbox_root = project_root / "tmp" / "combat_capture"
        self.sandbox_config = self.sandbox_root / "config.py"

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: Any = None,
    ) -> Any:
        del target
        if fullname != "config":
            return None

        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        origin = getattr(spec, "origin", None)
        try:
            resolved_origin = Path(origin).resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise ImportError("preflight config import origin is unavailable") from exc

        if resolved_origin == self.project_config:
            raise ImportError("real project config.py is forbidden during preflight")

        try:
            if (
                self.project_tmp.is_symlink()
                or self.sandbox_root.is_symlink()
                or self.sandbox_config.is_symlink()
            ):
                raise ImportError("preflight sandbox config path traverses a symlink")
            expected_sandbox_config = self.sandbox_config.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ImportError("preflight sandbox config origin is unavailable") from exc
        if resolved_origin != expected_sandbox_config or not expected_sandbox_config.is_file():
            raise ImportError("config imports are restricted to the synthetic sandbox")
        return spec


def _install_config_import_origin_guard() -> None:
    global _CONFIG_IMPORT_ORIGIN_GUARD
    if _CONFIG_IMPORT_ORIGIN_GUARD is not None:
        if _CONFIG_IMPORT_ORIGIN_GUARD not in sys.meta_path:
            raise RuntimeError("preflight config import guard was removed")
        return
    if "config" in sys.modules:
        raise RuntimeError("config was imported before the preflight origin guard")

    startup_module = sys.modules.get("sitecustomize")
    startup_origin = getattr(startup_module, "__file__", None)
    if not isinstance(startup_origin, (str, os.PathLike)):
        raise RuntimeError("preflight startup hook origin is unavailable")
    startup_path = Path(startup_origin)
    if startup_path.is_symlink():
        raise RuntimeError("preflight startup hook must not be a symlink")
    startup_path = startup_path.resolve(strict=True)
    project_root_text = os.environ.get("NEQ_PREFLIGHT_PROJECT_ROOT", "")
    guard_directory_text = os.environ.get("NEQ_PREFLIGHT_GUARD_DIRECTORY", "")
    if not project_root_text or not guard_directory_text:
        raise RuntimeError("preflight project and guard identities are unavailable")
    project_root = Path(project_root_text).resolve(strict=True)
    expected_guard_directory = project_root / "scripts" / "live_gate_preflight_guard"
    expected_sitecustomize = expected_guard_directory / "sitecustomize.py"
    expected_pythonpath = os.pathsep.join((str(expected_guard_directory), str(project_root)))
    if (
        not project_root.is_dir()
        or Path(guard_directory_text) != expected_guard_directory
        or startup_path != expected_sitecustomize
        or os.environ.get("PYTHONPATH") != expected_pythonpath
    ):
        raise RuntimeError("preflight dedicated guard path identity is invalid")

    guard = _ConfigImportOriginGuard(project_root)
    sys.meta_path.insert(0, guard)
    _CONFIG_IMPORT_ORIGIN_GUARD = guard


def activate_preflight_guard() -> None:
    global _STARTUP_ENVIRONMENT
    try:
        if (
            os.environ.get("NEQ_PREFLIGHT_STARTUP_GUARD_REQUIRED") != "1"
            or os.environ.get("NEQ_PREFLIGHT_NETWORK_GUARD") != "1"
        ):
            raise RuntimeError("preflight startup guard switch is missing")
        _install_config_import_origin_guard()

        from scripts.live_gate_preflight_safety import (
            ACTIVE_GUARD_ENV,
            CANARY_REPORT_ENV,
            CONNECT_CANARY_ENV,
            ENABLE_GUARD_ENV,
            REQUIRE_STARTUP_GUARD_ENV,
            SANITIZED_ENV,
            STARTUP_GUARD_ENV,
            SUBPROCESS_CANARY_ENV,
            activate_preflight_safety,
            record_startup_guard_event,
            run_startup_canaries,
            sanitized_environment_snapshot,
        )

        os.environ.pop(STARTUP_GUARD_ENV, None)
        if (
            os.environ.get(ENABLE_GUARD_ENV) != "1"
            or os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        ):
            raise RuntimeError("preflight startup guard switch is missing")
        activate_preflight_safety()
        record_startup_guard_event()
        _STARTUP_ENVIRONMENT = sanitized_environment_snapshot()
        report = run_startup_canaries()
        os.environ[CONNECT_CANARY_ENV] = "1"
        os.environ[SUBPROCESS_CANARY_ENV] = "1"
        os.environ[CANARY_REPORT_ENV] = json.dumps(
            report, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        os.environ["NEQ_PREFLIGHT_SYS_EXECUTABLE"] = report["interpreter"]["executable"]
        os.environ["NEQ_PREFLIGHT_SYS_PREFIX"] = report["interpreter"]["prefix"]
        os.environ["NEQ_PREFLIGHT_SYS_BASE_PREFIX"] = report["interpreter"]["base_prefix"]
        os.environ[STARTUP_GUARD_ENV] = "1"
        _exit_if_canary_requested(report)
    except BaseException:
        raise SystemExit("preflight startup guard installation failed closed") from None


def _exit_if_canary_requested(report: dict[str, Any]) -> None:
    """Emit one actual startup record and exit before application entrypoint."""
    from scripts.live_gate_preflight_safety import (
        CANARY_REPORT_FD,
        CANARY_SIGNAL,
        CANARY_SIGNAL_FD,
    )

    present: list[int] = []
    for descriptor in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
        try:
            os.fstat(descriptor)
        except OSError:
            continue
        present.append(descriptor)
    if not present:
        return
    if len(present) != 2:
        raise RuntimeError("preflight startup canary descriptors are incomplete")

    import select

    readable, _writable, _exceptional = select.select(
        [CANARY_SIGNAL_FD], [], [], 1.0
    )
    if not readable or os.read(CANARY_SIGNAL_FD, len(CANARY_SIGNAL)) != CANARY_SIGNAL:
        raise RuntimeError("preflight startup canary signal is invalid")
    payload = json.dumps(
        report, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"
    offset = 0
    while offset < len(payload):
        written = os.write(CANARY_REPORT_FD, payload[offset:])
        if written <= 0:
            raise RuntimeError("preflight startup canary report write failed")
        offset += written
    os._exit(0)
