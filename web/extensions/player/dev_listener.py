"""Explicit host-owned opt-in for the N2 development player listener."""

from __future__ import annotations

import os
from collections.abc import Callable

from utils.enhanced_logger import warning

from .assets import PlayerClientAssetsError
from .auth import PLAYER_PASSWORD_VERIFIER_ENV, parse_verifier
from .constants import PLAYER_HOST, PLAYER_PORT
from .gateway import PlayerGateway
from .listener import PlayerListener

PLAYER_DEV_LISTENER_ENV = "NEQ_PLAYER_DEV_LISTENER"


def start_player_dev_listener(
    gateway_factory: Callable[[], PlayerGateway],
) -> PlayerListener | None:
    """Start the fixed loopback listener only with the exact approved opt-in."""
    if os.environ.get(PLAYER_DEV_LISTENER_ENV) != "1":
        return None

    listener: PlayerListener | None = None
    try:
        if parse_verifier(os.environ.get(PLAYER_PASSWORD_VERIFIER_ENV)) is None:
            _warn_startup("missing_or_invalid_verifier")
            return None

        listener = PlayerListener(gateway=gateway_factory())
        listener.start(host=PLAYER_HOST, port=PLAYER_PORT)
        return listener
    except PlayerClientAssetsError as exc:
        _stop_after_failed_start(listener)
        asset_code = exc.code if exc.code in {
            "missing_bundle",
            "missing_manifest",
            "invalid_manifest",
            "unsupported_version",
            "incomplete_bundle",
            "invalid_asset",
        } else "invalid_bundle"
        _warn_startup(f"assets_{asset_code}")
    except Exception:
        _stop_after_failed_start(listener)
        _warn_startup("startup_error")
    return None


def _stop_after_failed_start(listener: PlayerListener | None) -> None:
    if listener is None:
        return
    try:
        listener.stop()
    except Exception:
        # Startup remains best-effort; the host must continue even if cleanup
        # reports its own bounded failure.
        return


def _warn_startup(reason: str) -> None:
    warning(
        f"Player development listener unavailable ({reason}); local host play continues",
        category="player",
    )
