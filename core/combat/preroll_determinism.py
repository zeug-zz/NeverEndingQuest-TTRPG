# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Default-off deterministic preroll dependencies for isolated G7 captures."""

from __future__ import annotations

import logging
import os
import random
import re
import threading
from typing import Any, Callable, Optional, Tuple

import model_config
from core.combat import turn_fault_injection


# TABLETOP MODE: Keep seeded dice local to this dependency bundle; never reseed
# or otherwise mutate the process-wide random generator.
PREROLL_SEED_ENV = "NEQ_COMBAT_PREROLL_SEED"
_SEED_PATTERN = re.compile(r"^[0-9]{1,20}$")
_MAX_SEED = (1 << 64) - 1
_LOGGER = logging.getLogger(__name__)
_LOGGED_REJECTIONS = set()
_REJECTION_LOCK = threading.Lock()


def _log_rejection(reason: str) -> None:
    """Emit one bounded diagnostic for each rejected fixture-seed class."""
    with _REJECTION_LOCK:
        if reason in _LOGGED_REJECTIONS:
            return
        _LOGGED_REJECTIONS.add(reason)
    try:
        _LOGGER.error("COMBAT_PREROLL_SEED_REJECTED: %s", reason)
    except Exception:
        pass


def _parse_seed(value: str) -> Optional[int]:
    if not isinstance(value, str) or not _SEED_PATTERN.fullmatch(value):
        return None
    seed = int(value)
    if seed > _MAX_SEED:
        return None
    return seed


def build_preroll_dependencies(
    generate_prerolls: Callable[..., str],
    random_int: Callable[[int, int], int],
) -> Tuple[Callable[..., str], Callable[[int, int], int]]:
    """Return production dependencies unless an authorized G7 seed is present.

    Activation requires the existing default-off turn-commit injection flag,
    the same repository-local ``tmp/combat_capture`` root check as fault
    injection, and a valid decimal seed. The fallback returns the original
    callables by identity so ordinary combat keeps its historical random path.
    """
    if model_config.COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED is not True:
        return generate_prerolls, random_int

    raw_seed = os.environ.get(PREROLL_SEED_ENV)
    if raw_seed is None:
        return generate_prerolls, random_int

    try:
        runtime_root = turn_fault_injection._resolved_runtime_root()
    except Exception:
        _log_rejection("runtime_root_unavailable")
        return generate_prerolls, random_int
    try:
        if not turn_fault_injection._is_isolated_capture_root(runtime_root):
            _log_rejection("runtime_root_outside_tmp_combat_capture")
            return generate_prerolls, random_int
    except Exception:
        _log_rejection("runtime_root_invalid")
        return generate_prerolls, random_int

    seed = _parse_seed(raw_seed)
    if seed is None:
        _log_rejection("invalid_preroll_seed")
        return generate_prerolls, random_int

    local_rng = random.Random(seed)

    def seeded_generate_prerolls(encounter_data: Any, round_num: Any = None) -> str:
        return generate_prerolls(
            encounter_data,
            round_num=round_num,
            rng=local_rng,
        )

    return seeded_generate_prerolls, local_rng.randint


__all__ = ["PREROLL_SEED_ENV", "build_preroll_dependencies"]
