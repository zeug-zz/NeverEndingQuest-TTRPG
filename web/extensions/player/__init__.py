# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Isolated player-facing ASGI application and explicit listener lifecycle."""

from .app import PlayerApplication, create_app
from .active_pc import PlayerActivePCSelection, select_player_active_pc
from .constants import PLAYER_HOST, PLAYER_NAMESPACE, PLAYER_PORT
from .gateway import (
    PlayerGateway,
    PlayerInputAdmission,
    PlayerInputCommand,
    PlayerSnapshot,
    UnavailablePlayerGateway,
)
from .listener import PlayerListener

__all__ = [
    "PLAYER_HOST",
    "PLAYER_NAMESPACE",
    "PLAYER_PORT",
    "PlayerActivePCSelection",
    "PlayerApplication",
    "PlayerGateway",
    "PlayerInputAdmission",
    "PlayerInputCommand",
    "PlayerListener",
    "PlayerSnapshot",
    "UnavailablePlayerGateway",
    "create_app",
    "select_player_active_pc",
]
