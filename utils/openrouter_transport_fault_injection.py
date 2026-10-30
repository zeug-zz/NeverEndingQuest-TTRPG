# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""One-shot OpenRouter transport failure for isolated G9 captures only."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from utils.repo_paths import repository_root


_LOGGER = logging.getLogger(__name__)
_INJECTION_LOCK = threading.Lock()
_INJECTED = False
_LOGGED_REJECTIONS = set()


class OpenRouterTransportFaultInjected(ConnectionError):
    """Bounded synthetic connection failure authorized for one G9 sandbox call."""


def _log_rejection(reason: str) -> None:
    if reason in _LOGGED_REJECTIONS:
        return
    _LOGGED_REJECTIONS.add(reason)
    try:
        _LOGGER.error("OPENROUTER_TRANSPORT_FAULT_INJECTION_REJECTED: %s", reason)
    except Exception:
        pass


def _resolved_runtime_root() -> Path:
    return Path(repository_root()).resolve(strict=True)


def _is_isolated_capture_root(runtime_root: Path) -> bool:
    for capture_root in (runtime_root, *runtime_root.parents):
        if capture_root.name != "combat_capture" or capture_root.parent.name != "tmp":
            continue
        repository = capture_root.parent.parent
        if ((repository / "AGENTS.md").is_file() and
                (repository / "model_config.py").is_file()):
            return True
    return False


def maybe_inject_openrouter_transport_failure(transport_provider: str) -> bool:
    """Raise once for OpenRouter only when a flag and the real sandbox root agree.

    The flag is deliberately checked before path resolution. A disabled or
    unavailable flag does not inspect the environment, filesystem, or runtime
    root. Direct OpenAI fallback requests are never eligible.
    """
    if transport_provider != "openrouter":
        return False
    try:
        import model_config
    except ImportError:
        return False
    if getattr(model_config, "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED", False) is not True:
        return False

    try:
        runtime_root = _resolved_runtime_root()
    except Exception:
        _log_rejection("runtime_root_unavailable")
        return False
    if not _is_isolated_capture_root(runtime_root):
        _log_rejection("runtime_root_outside_tmp_combat_capture")
        return False

    global _INJECTED
    with _INJECTION_LOCK:
        if _INJECTED:
            return False
        _INJECTED = True
    try:
        _LOGGER.warning("OPENROUTER_TRANSPORT_FAULT_INJECTED: one-shot G9 connection failure")
    except Exception:
        pass
    raise OpenRouterTransportFaultInjected(
        "controlled transient OpenRouter transport connection failure"
    )


__all__ = [
    "OpenRouterTransportFaultInjected",
    "maybe_inject_openrouter_transport_failure",
]
