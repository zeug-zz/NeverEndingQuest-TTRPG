# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Typed active-PC selection checks for the future player runtime adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PlayerActivePCStatus = Literal["selected", "stale", "rejected"]


@dataclass(frozen=True, slots=True)
class PlayerActivePCSelection:
    """Canonical selection result without runtime queue-admission behavior."""

    status: PlayerActivePCStatus
    active_character: str
    revision: int
    reason: str | None = None


def select_player_active_pc(
    character_name: str,
    expected_revision: int,
) -> PlayerActivePCSelection:
    """Select a current party member only when its observed revision is current."""
    from utils.pc_manager import set_active_pc_checked

    result = set_active_pc_checked(character_name, expected_revision)
    if result.status in {"updated", "unchanged"}:
        return PlayerActivePCSelection(
            "selected", result.active_character, result.revision
        )
    if result.status == "stale":
        return PlayerActivePCSelection(
            "stale", result.active_character, result.revision, result.reason
        )
    return PlayerActivePCSelection(
        "rejected", result.active_character, result.revision, result.reason
    )
