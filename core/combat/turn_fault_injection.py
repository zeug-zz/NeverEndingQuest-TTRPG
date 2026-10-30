# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Sandbox-only process-stop injection for combat-turn commit boundaries.

The Capture_Arena driver selects one boundary by setting
``NEQ_COMBAT_FAULT_POINT`` in the sandbox server subprocess. Accepted values
are ``before_first_character_write``, ``after_character_write:<n>`` (1..256),
``after_encounter_write``, ``after_phase_sync``,
``during_success_publication``, and ``after_success_publication``. The driver
must clear the variable before starting the retained-state restart process.
The selector is read only when the feature flag is enabled and this installed
runtime root resolves inside the repository-local ``tmp/combat_capture/`` tree.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional

from utils.repo_paths import repository_root
import model_config


_LOGGER = logging.getLogger(__name__)
_FAULT_POINT_ENV = "NEQ_COMBAT_FAULT_POINT"
_MAX_FAULT_POINT_LENGTH = 64
_MAX_CHARACTER_WRITE_ORDINAL = 256
_CHARACTER_WRITE_PATTERN = re.compile(r"^after_character_write:([1-9][0-9]{0,2})$")
_SIMPLE_FAULT_POINTS = frozenset({
    "before_first_character_write",
    "after_encounter_write",
    "after_phase_sync",
    "during_success_publication",
    "after_success_publication",
})
_LOGGED_REJECTIONS = set()
_REJECTION_LOG_LOCK = threading.Lock()


class CombatTurnFaultInjected(BaseException):
    """Dedicated uncaught sentinel that stops only an authorized sandbox run."""

    def __init__(self, fault_point: str):
        self.fault_point = fault_point
        super().__init__("COMBAT_TURN_FAULT_INJECTED:%s" % fault_point)


def _log_rejection(reason: str) -> None:
    """Emit a bounded error once per rejection class without risking gameplay."""
    with _REJECTION_LOG_LOCK:
        if reason in _LOGGED_REJECTIONS:
            return
        _LOGGED_REJECTIONS.add(reason)
    try:
        _LOGGER.error("COMBAT_TURN_FAULT_INJECTION_REJECTED: %s", reason)
    except Exception:
        # Optional logging must not turn a rejected injection into a game error.
        pass


def _resolved_runtime_root() -> Path:
    """Resolve the application root from installed package location, not cwd."""
    return Path(repository_root()).resolve(strict=True)


def _is_isolated_capture_root(runtime_root: Path) -> bool:
    """Require a real repository-local tmp/combat_capture ancestor."""
    for capture_root in (runtime_root, *runtime_root.parents):
        if capture_root.name != "combat_capture" or capture_root.parent.name != "tmp":
            continue
        repository = capture_root.parent.parent
        if (repository / "AGENTS.md").is_file() and (repository / "model_config.py").is_file():
            return True
    return False


def _read_requested_fault_point() -> Optional[str]:
    """Read the capture selector; callers must pass both safety guards first."""
    return os.environ.get(_FAULT_POINT_ENV)


def _parse_fault_point(value: str) -> Optional[tuple[str, Optional[int]]]:
    if not isinstance(value, str) or not value or len(value) > _MAX_FAULT_POINT_LENGTH:
        return None
    if value in _SIMPLE_FAULT_POINTS:
        return value, None
    match = _CHARACTER_WRITE_PATTERN.fullmatch(value)
    if match is None:
        return None
    ordinal = int(match.group(1))
    if ordinal > _MAX_CHARACTER_WRITE_ORDINAL:
        return None
    return "after_character_write", ordinal


def maybe_inject_combat_turn_fault(
    boundary: str,
    *,
    ordinal: Optional[int] = None,
) -> bool:
    """Stop at a selected boundary only in an explicitly enabled capture copy.

    A disabled flag returns before resolving paths or reading environment
    variables. An enabled flag outside the isolated tree is rejected and logged
    before the selector is read. Returning False always means ordinary gameplay
    continues without changing state.
    """
    if model_config.COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED is not True:
        return False

    try:
        runtime_root = _resolved_runtime_root()
    except Exception:
        _log_rejection("runtime_root_unavailable")
        return False
    if not _is_isolated_capture_root(runtime_root):
        _log_rejection("runtime_root_outside_tmp_combat_capture")
        return False

    requested = _read_requested_fault_point()
    if requested is None or requested == "":
        return False
    parsed = _parse_fault_point(requested)
    if parsed is None:
        _log_rejection("invalid_fault_point")
        return False

    requested_boundary, requested_ordinal = parsed
    if boundary == "after_character_write":
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
            or ordinal > _MAX_CHARACTER_WRITE_ORDINAL
        ):
            _log_rejection("invalid_character_write_ordinal")
            return False
    elif boundary not in _SIMPLE_FAULT_POINTS:
        _log_rejection("unknown_runtime_boundary")
        return False

    if requested_boundary != boundary or requested_ordinal != ordinal:
        return False
    raise CombatTurnFaultInjected(requested)


__all__ = [
    "CombatTurnFaultInjected",
    "maybe_inject_combat_turn_fault",
]
