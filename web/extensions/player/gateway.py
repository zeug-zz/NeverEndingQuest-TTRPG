# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Typed seam for player commands and canonical, player-safe reads.

Implementations are supplied by later runtime-integration work. This module
deliberately has no mechanics, provider, or persistence dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol


AdmissionStatus = Literal["accepted", "busy", "stale", "rejected"]


@dataclass(frozen=True, slots=True)
class PlayerInputCommand:
    """Character-bound player input passed to the runtime admission seam."""

    request_id: str
    character_name: str
    active_character_revision: int
    text: str


@dataclass(frozen=True, slots=True)
class PlayerInputAdmission:
    """Typed command-admission result; it does not claim game completion."""

    request_id: str
    status: AdmissionStatus


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    """Player-safe projection read through the canonical state boundary."""

    revision: int
    projection: Mapping[str, object]


class PlayerGateway(Protocol):
    """Dependency-injected interface for canonical reads and runtime admission."""

    def admit_input(self, command: PlayerInputCommand) -> PlayerInputAdmission:
        """Submit one validated, character-bound input for queue admission."""

    def read_snapshot(self) -> PlayerSnapshot:
        """Return a bounded player-safe view from canonical state readers."""


class UnavailablePlayerGateway:
    """Fail closed until a runtime gateway is explicitly provided."""

    def admit_input(self, command: PlayerInputCommand) -> PlayerInputAdmission:
        del command
        raise RuntimeError("player runtime gateway is not configured")

    def read_snapshot(self) -> PlayerSnapshot:
        raise RuntimeError("player runtime gateway is not configured")
