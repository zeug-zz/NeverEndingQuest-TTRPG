# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Authentication primitives for the inert N0 network spike fixture.

This module has no game-data dependencies and handles only fixture credentials,
session tokens, request identity headers, and browser cookie attributes.
"""

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from typing import Callable, Iterable, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit


_PROCESS_SESSION_KEY = secrets.token_bytes(32)
_TOKEN_PART_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_COOKIE_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_TOKEN_CLOCK_SKEW_SECONDS = 30
_MAX_TOKEN_CHARS = 1024
# A SHA-256 signature uses 43 unpadded base64url characters; reserve that and
# the separator under the existing total-token cap to derive the part limit.
_TOKEN_SIGNATURE_PART_CHARS = (hashlib.sha256().digest_size * 8 + 5) // 6
_MAX_TOKEN_PART_CHARS = _MAX_TOKEN_CHARS - 1 - _TOKEN_SIGNATURE_PART_CHARS


def check_password(supplied: Optional[str], expected: str) -> bool:
    """Compare fixture passwords without an early return for missing input."""
    candidate = supplied if isinstance(supplied, str) else ""
    candidate_bytes = candidate.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    matches = hmac.compare_digest(candidate_bytes, expected_bytes)
    return bool(matches & bool(candidate_bytes))


def _encode_token_part(value: bytes) -> str:
    """Encode one token component using unpadded URL-safe Base64."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_token_part(value: str) -> Optional[bytes]:
    """Strictly decode an unpadded URL-safe Base64 token component."""
    if (
        not value
        or len(value) > _MAX_TOKEN_PART_CHARS
        or any(character not in _TOKEN_PART_ALPHABET for character in value)
    ):
        return None
    padded = value + ("=" * (-len(value) % 4))
    try:
        return base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        return None


class SessionSigner:
    """Issue and verify short-lived HMAC-signed fixture session tokens."""

    def __init__(
        self,
        ttl_seconds: int,
        key: Optional[bytes] = None,
        clock: Callable[[], float] = time.time,
        clock_skew_seconds: int = _TOKEN_CLOCK_SKEW_SECONDS,
    ) -> None:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
            raise ValueError("ttl_seconds must be a positive integer")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        if not isinstance(clock_skew_seconds, int) or isinstance(
            clock_skew_seconds, bool
        ):
            raise ValueError("clock_skew_seconds must be a non-negative integer")
        if clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds must be a non-negative integer")
        if key is not None and (not isinstance(key, bytes) or not key):
            raise ValueError("key must be non-empty bytes")

        self._key = _PROCESS_SESSION_KEY if key is None else key
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._clock_skew_seconds = clock_skew_seconds

    def issue(self) -> str:
        """Return an opaque signed token expiring after the configured TTL."""
        issued_at = int(self._clock())
        if issued_at < 0:
            raise ValueError("clock must return a non-negative timestamp")
        expires_at = issued_at + self._ttl_seconds
        nonce = secrets.token_urlsafe(24)
        payload = f"{issued_at}:{expires_at}:{nonce}".encode("ascii")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return f"{_encode_token_part(payload)}.{_encode_token_part(signature)}"

    def verify(self, token: Optional[str]) -> bool:
        """Return whether a token is authentic, unexpired, and well-formed."""
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_CHARS:
            return False
        parts = token.split(".")
        if len(parts) != 2:
            return False

        payload = _decode_token_part(parts[0])
        supplied_signature = _decode_token_part(parts[1])
        if payload is None or supplied_signature is None:
            return False
        expected_signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False

        try:
            payload_text = payload.decode("ascii")
            issued_text, expires_text, nonce = payload_text.split(":")
            if (
                not issued_text.isdigit()
                or not expires_text.isdigit()
                or str(int(issued_text)) != issued_text
                or str(int(expires_text)) != expires_text
                or _NONCE_RE.fullmatch(nonce) is None
            ):
                return False
            issued_at = int(issued_text)
            expires_at = int(expires_text)
            now = int(self._clock())
        except (UnicodeDecodeError, ValueError, OverflowError):
            return False

        if issued_at < 0 or expires_at <= issued_at:
            return False
        if expires_at - issued_at != self._ttl_seconds:
            return False
        if issued_at > now + self._clock_skew_seconds:
            return False
        return now < expires_at


def _has_header_separators(value: str) -> bool:
    """Reject whitespace, commas, and control characters in identity headers."""
    return any(
        character.isspace()
        or character == ","
        or ord(character) < 32
        or ord(character) == 127
        for character in value
    )


def _as_values(values: Iterable[str]) -> Iterable[str]:
    """Treat a single configured string as one value, not an iterable of chars."""
    if isinstance(values, str):
        return (values,)
    return values


def validate_host(host_header: Optional[str], allowed_hosts: Iterable[str]) -> bool:
    """Match Host exactly, ignoring case and rejecting ambiguous header values."""
    if (
        not isinstance(host_header, str)
        or not host_header
        or _has_header_separators(host_header)
    ):
        return False
    host_value = host_header.casefold()
    for allowed_host in _as_values(allowed_hosts):
        if (
            isinstance(allowed_host, str)
            and allowed_host
            and not _has_header_separators(allowed_host)
            and host_value == allowed_host.casefold()
        ):
            return True
    return False


def _normalize_origin(origin: Optional[str]) -> Optional[str]:
    """Return a case-folded bare HTTP(S) origin, or None for invalid input."""
    if (
        not isinstance(origin, str)
        or not origin
        or origin.casefold() == "null"
        or _has_header_separators(origin)
        or "?" in origin
        or "#" in origin
        or "\\" in origin
    ):
        return None
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() not in ("http", "https")
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or origin.endswith(":")
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None
    return origin.casefold()


def validate_origin(
    origin_header: Optional[str],
    allowed_origins: Iterable[str],
    require: bool,
) -> bool:
    """Match a bare expected HTTP(S) origin; reject opaque ``null`` origins."""
    if origin_header is None:
        return not require
    origin_value = _normalize_origin(origin_header)
    if origin_value is None:
        return False
    for allowed_origin in _as_values(allowed_origins):
        if _normalize_origin(allowed_origin) == origin_value:
            return True
    return False


def extract_host_origin(
    headers: Mapping[Union[str, bytes], Union[str, bytes]],
) -> Tuple[Optional[str], Optional[str]]:
    """Extract Host and Origin only; Forwarded and X-Forwarded-* are ignored.

    Header names are matched case-insensitively. Duplicate Host or Origin keys
    are rejected rather than choosing an ambiguous value. Forwarding headers
    are deliberately never read and cannot establish request identity.
    """
    selected = {"host": None, "origin": None}
    seen = set()
    for raw_name, raw_value in headers.items():
        if isinstance(raw_name, bytes):
            name = raw_name.decode("latin-1").casefold()
        elif isinstance(raw_name, str):
            name = raw_name.casefold()
        else:
            continue
        if name not in selected:
            continue
        if name in seen:
            raise ValueError(f"duplicate {name} header")
        seen.add(name)
        if isinstance(raw_value, bytes):
            value = raw_value.decode("latin-1")
        elif isinstance(raw_value, str):
            value = raw_value
        else:
            raise ValueError(f"invalid {name} header value")
        selected[name] = value
    return selected["host"], selected["origin"]


def build_session_cookie(name: str, value: str, max_age: int) -> str:
    """Build a host-only session cookie with strict browser security attributes."""
    if not isinstance(name, str) or _COOKIE_NAME_RE.fullmatch(name) is None:
        raise ValueError("invalid cookie name")
    if not isinstance(value, str) or any(
        ord(character) < 33
        or ord(character) > 126
        or character in '\",;\\'
        for character in value
    ):
        raise ValueError("invalid cookie value")
    if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age < 0:
        raise ValueError("max_age must be a non-negative integer")
    return (
        f"{name}={value}; Path=/; Max-Age={max_age}; Secure; HttpOnly; "
        "SameSite=Strict"
    )


def clear_session_cookie(name: str) -> str:
    """Build an expired session cookie using the same security attributes."""
    return build_session_cookie(name, "", 0)


def ensure_loopback_bind(host: str) -> None:
    """Refuse every bind address except the fixture's exact IPv4 loopback."""
    if host != "127.0.0.1":
        raise ValueError("fixture bind host must be exactly 127.0.0.1")
