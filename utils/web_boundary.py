# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free validation helpers for the local web server boundary."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Iterable, List
from urllib.parse import urlsplit


DEFAULT_WEB_HOST = "127.0.0.1"
_HOSTNAME_PART = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _valid_host(value: Any) -> bool:
    """Return whether value is a safe bind host without resolving DNS."""
    if not isinstance(value, str):
        return False
    host = value.strip()
    if not host or len(host) > 253 or any(char.isspace() for char in host):
        return False
    if host in {"0.0.0.0", "::", "[::]", "*"} or "/" in host:
        return False
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    if candidate.endswith("."):
        candidate = candidate[:-1]
    return bool(candidate) and all(_HOSTNAME_PART.fullmatch(part) for part in candidate.split("."))


def resolve_web_host(value: Any) -> str:
    """Return a validated bind host, failing closed to loopback."""
    return value.strip() if _valid_host(value) else DEFAULT_WEB_HOST


def _default_origins(port: Any) -> List[str]:
    """Build the finite loopback origin allowlist for a configured port."""
    try:
        normalized_port = int(port)
    except (TypeError, ValueError):
        normalized_port = 8357
    return [
        "http://localhost:{0}".format(normalized_port),
        "http://127.0.0.1:{0}".format(normalized_port),
        "http://[::1]:{0}".format(normalized_port),
    ]


def _origin_values(value: Any) -> Iterable[Any]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",")]
    if isinstance(value, (list, tuple, set)):
        return value
    return []


def _valid_origin(value: Any) -> bool:
    if not isinstance(value, str) or not value or value == "*" or any(char.isspace() for char in value):
        return False
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return False
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if not _valid_host(host) or port is None or port < 1 or port > 65535:
        return False
    return True


def resolve_socketio_origins(value: Any, port: Any) -> List[str]:
    """Return explicit safe origins or the finite loopback default.

    An invalid list is rejected as a whole so one malformed value cannot cause
    a wildcard fallback or partially trusted policy.
    """
    values = list(_origin_values(value))
    if not values or any(not _valid_origin(origin) for origin in values):
        return _default_origins(port)
    return [str(origin).strip() for origin in values]


__all__ = ["DEFAULT_WEB_HOST", "resolve_web_host", "resolve_socketio_origins"]
