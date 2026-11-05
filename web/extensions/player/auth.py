# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Password verification, loopback request identity, and player sessions."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .constants import PLAYER_HOST, PLAYER_PORT
from .limiters import PlayerLimiters
from .limits import (
    MAX_ACTIVE_SESSIONS,
    MAX_CONCURRENT_PLAYER_SOCKETS,
    MAX_PRELOGIN_CHALLENGES,
    MAX_PASSWORD_BYTES,
)

PLAYER_PASSWORD_VERIFIER_ENV = "NEQ_PLAYER_PASSWORD_VERIFIER"
PLAYER_SESSION_COOKIE = "neq_player_session"
PRELOGIN_CSRF_COOKIE = "neq_player_prelogin"
SESSION_TTL_SECONDS = 4 * 60 * 60
PRELOGIN_CSRF_TTL_SECONDS = 5 * 60
SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16
SCRYPT_MAXMEM_BYTES = 64 * 1024 * 1024

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_VERIFIER_RE = re.compile(
    r"neq-scrypt\$v1\$32768\$8\$1\$([0-9a-f]{32})\$([0-9a-f]{64})\Z"
)
_COOKIE_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")


@dataclass(frozen=True, slots=True)
class ScryptCredentialVerifier:
    """Parsed verifier with the only supported scrypt parameter tuple."""

    salt: bytes
    derived_key: bytes

    def verify(self, password: str | None) -> bool:
        candidate = password if isinstance(password, str) else ""
        if len(candidate) > MAX_PASSWORD_BYTES:
            return False
        try:
            password_bytes = candidate.encode("utf-8")
            if len(password_bytes) > MAX_PASSWORD_BYTES:
                return False
            derived_key = hashlib.scrypt(
                password_bytes,
                salt=self.salt,
                n=SCRYPT_N,
                r=SCRYPT_R,
                p=SCRYPT_P,
                dklen=SCRYPT_DKLEN,
                maxmem=SCRYPT_MAXMEM_BYTES,
            )
        except (UnicodeEncodeError, ValueError, MemoryError):
            return False
        matches = hmac.compare_digest(derived_key, self.derived_key)
        return bool(matches & bool(candidate))


@dataclass(frozen=True, slots=True)
class PreloginChallenge:
    cookie_value: str
    csrf_nonce: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    cookie_value: str
    csrf_token: str
    expires_at: int
    session_epoch: str


@dataclass(frozen=True, slots=True)
class PlayerSessionIdentity:
    """Authenticated server identities bound to one live player session."""

    instance_id: str
    session_id: str
    session_epoch: str


@dataclass(slots=True)
class _SessionRecord:
    session_id: str
    expires_at: int
    csrf_token: str
    session_epoch: str
    sockets: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _SocketRecord:
    session_id: str
    host: str
    origin: str


def parse_verifier(value: str | None) -> ScryptCredentialVerifier | None:
    """Parse only the versioned production scrypt tuple; malformed values fail closed."""
    if not isinstance(value, str):
        return None
    match = _VERIFIER_RE.fullmatch(value)
    if match is None:
        return None
    try:
        salt = bytes.fromhex(match.group(1))
        derived_key = bytes.fromhex(match.group(2))
    except ValueError:
        return None
    if len(salt) != SCRYPT_SALT_BYTES or len(derived_key) != SCRYPT_DKLEN:
        return None
    return ScryptCredentialVerifier(salt=salt, derived_key=derived_key)


def make_verifier(password: str, *, salt: bytes | None = None) -> str:
    """Create a v1 verifier; ``salt`` exists only for deterministic tests."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    try:
        password_bytes = password.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("password must be valid UTF-8") from exc
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError("password exceeds the configured byte limit")
    selected_salt = secrets.token_bytes(SCRYPT_SALT_BYTES) if salt is None else salt
    if not isinstance(selected_salt, bytes) or len(selected_salt) != SCRYPT_SALT_BYTES:
        raise ValueError("salt must be exactly 16 bytes")
    derived_key = hashlib.scrypt(
        password_bytes,
        salt=selected_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM_BYTES,
    )
    return (
        f"neq-scrypt$v1${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{selected_salt.hex()}${derived_key.hex()}"
    )


def build_cookie(name: str, value: str, max_age: int) -> str:
    """Build a host-only, strict, secure cookie without a Domain attribute."""
    if not isinstance(name, str) or _COOKIE_NAME_RE.fullmatch(name) is None:
        raise ValueError("invalid cookie name")
    if not isinstance(value, str):
        raise ValueError("invalid cookie value")
    if any(
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


def header_values(headers: Iterable[tuple[object, object]], name: str) -> list[str]:
    """Return raw header values without consulting any forwarding headers."""
    selected: list[str] = []
    for raw_name, raw_value in headers:
        if isinstance(raw_name, bytes):
            normalized_name = raw_name.decode("latin-1").casefold()
        elif isinstance(raw_name, str):
            normalized_name = raw_name.casefold()
        else:
            continue
        if normalized_name != name.casefold():
            continue
        if isinstance(raw_value, bytes):
            selected.append(raw_value.decode("latin-1"))
        elif isinstance(raw_value, str):
            selected.append(raw_value)
        else:
            selected.append("")
    return selected


def extract_host_origin(
    headers: Iterable[tuple[object, object]],
) -> tuple[str | None, str | None, bool]:
    """Extract unique Host and Origin values, flagging duplicate identity headers."""
    hosts = header_values(headers, "host")
    origins = header_values(headers, "origin")
    if len(hosts) != 1 or len(origins) > 1:
        return None, None, False
    return hosts[0], origins[0] if origins else None, True


def cookie_value(headers: Iterable[tuple[object, object]], name: str) -> str | None:
    """Read exactly one cookie of ``name`` from an unambiguous Cookie header."""
    cookie_headers = header_values(headers, "cookie")
    if len(cookie_headers) != 1:
        return None
    found: str | None = None
    seen = False
    for item in cookie_headers[0].split(";"):
        cookie_name, separator, value = item.strip().partition("=")
        if not separator or cookie_name != name:
            continue
        if seen:
            return None
        seen = True
        found = value.strip()
    return found if seen else None


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a player password verifier")
    parser.add_argument(
        "--make-verifier",
        action="store_true",
        help="read a password from the terminal and print its versioned scrypt verifier",
    )
    args = parser.parse_args(argv)
    if not args.make_verifier:
        parser.error("--make-verifier is required")
    password = getpass.getpass("Player password: ")
    try:
        print(make_verifier(password))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


class PlayerSecurity:
    """Own per-listener credentials, sessions, CSRF proofs, and socket identities."""

    def __init__(
        self,
        verifier_provider: Callable[[], str | None] | None = None,
        *,
        port: int = PLAYER_PORT,
        clock: Callable[[], float] | None = None,
        limiters: PlayerLimiters | None = None,
    ) -> None:
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("player port must be between 1 and 65535")
        self._verifier_provider = (
            verifier_provider
            if verifier_provider is not None
            else lambda: os.environ.get(PLAYER_PASSWORD_VERIFIER_ENV)
        )
        selected_clock = time.time if clock is None else clock
        self.port = port
        self.clock = selected_clock
        self.limiters = (
            limiters
            if limiters is not None
            else PlayerLimiters(
                selected_clock,
                login_window=PlayerLimiters.process_login_window() if clock is None else None,
            )
        )
        self._lock = threading.RLock()
        self._active = True
        self._signing_key = secrets.token_bytes(32)
        self._server_instance_id = secrets.token_urlsafe(32)
        self._verifier = parse_verifier(self._verifier_provider())
        self._prelogin: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, _SessionRecord] = {}
        self._sockets: dict[str, _SocketRecord] = {}

    @property
    def expected_host(self) -> str:
        return f"{PLAYER_HOST}:{self.port}"

    @property
    def expected_origin(self) -> str:
        return f"http://{PLAYER_HOST}:{self.port}"

    @property
    def server_instance_id(self) -> str:
        with self._lock:
            return self._server_instance_id

    @property
    def active_session_count(self) -> int:
        with self._lock:
            self._prune_expired_sessions_locked()
            return len(self._sessions)

    @property
    def active_socket_count(self) -> int:
        with self._lock:
            self._prune_expired_sessions_locked()
            return len(self._sockets)

    def start_listener(self) -> None:
        """Rotate listener identity and clear every prior challenge/session."""
        try:
            verifier = parse_verifier(self._verifier_provider())
        except (OSError, ValueError):
            verifier = None
        with self._lock:
            self._prelogin.clear()
            self._sessions.clear()
            self._sockets.clear()
            self.limiters.clear_sessions()
            self._signing_key = secrets.token_bytes(32)
            self._server_instance_id = secrets.token_urlsafe(32)
            self._verifier = verifier
            self._active = True

    def stop_listener(self) -> list[str]:
        """Invalidate sessions and return socket IDs for transport disconnection."""
        with self._lock:
            socket_ids = list(self._sockets)
            self._active = False
            self._prelogin.clear()
            self._sessions.clear()
            self._sockets.clear()
            self.limiters.clear_sessions()
            return socket_ids

    def allow_login_attempt(self) -> bool:
        return self.limiters.allow_login_attempt()

    def verify_password(self, password: str | None) -> bool:
        verifier = self._verifier
        if verifier is None:
            return False
        return verifier.verify(password)

    def issue_prelogin_challenge(self) -> PreloginChallenge | None:
        now = self.clock()
        with self._lock:
            if not self._active:
                return None
            self._prune_prelogin_locked(now)
            if len(self._prelogin) >= MAX_PRELOGIN_CHALLENGES:
                return None
            cookie = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            expires_at = now + PRELOGIN_CSRF_TTL_SECONDS
            self._prelogin[cookie] = (nonce, expires_at)
            return PreloginChallenge(cookie, nonce, expires_at)

    def consume_prelogin_challenge(self, cookie: str | None, nonce: str | None) -> bool:
        now = self.clock()
        selected_cookie = cookie if isinstance(cookie, str) else ""
        selected_nonce = nonce if isinstance(nonce, str) else ""
        try:
            candidate_bytes = selected_nonce.encode("ascii")
        except UnicodeEncodeError:
            candidate_bytes = b""
        with self._lock:
            record = self._prelogin.pop(selected_cookie, None)
            if record is None:
                return False
            expected_nonce, expires_at = record
            matches = hmac.compare_digest(candidate_bytes, expected_nonce.encode("ascii"))
            return bool(matches & (now < expires_at) & self._active)

    def create_session(self) -> SessionGrant | None:
        now = self.clock()
        with self._lock:
            if not self._active:
                return None
            self._prune_expired_sessions_locked(now)
            if len(self._sessions) >= MAX_ACTIVE_SESSIONS:
                return None
            session_id = secrets.token_urlsafe(32)
            session_epoch = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = int(now) + SESSION_TTL_SECONDS
            cookie_value = self._sign_session_locked(session_id, expires_at)
            if not self.limiters.register_session(session_id, session_epoch):
                return None
            self._sessions[session_id] = _SessionRecord(
                session_id=session_id,
                expires_at=expires_at,
                csrf_token=csrf_token,
                session_epoch=session_epoch,
            )
            return SessionGrant(
                session_id=session_id,
                cookie_value=cookie_value,
                csrf_token=csrf_token,
                expires_at=expires_at,
                session_epoch=session_epoch,
            )

    def session_id_for_cookie(self, cookie: str | None) -> str | None:
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            record = self._session_from_cookie_locked(cookie)
            return None if record is None else record.session_id

    def session_context_for_cookie(self, cookie: str | None) -> PlayerSessionIdentity | None:
        """Return non-cookie session identities only for a current signed session."""
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            record = self._session_from_cookie_locked(cookie)
            if record is None:
                return None
            return PlayerSessionIdentity(
                instance_id=self._server_instance_id,
                session_id=record.session_id,
                session_epoch=record.session_epoch,
            )

    def csrf_is_valid(self, cookie: str | None, csrf_token: str | None) -> bool:
        now = self.clock()
        candidate = csrf_token if isinstance(csrf_token, str) else ""
        try:
            candidate_bytes = candidate.encode("ascii")
        except UnicodeEncodeError:
            candidate_bytes = b""
        with self._lock:
            self._prune_expired_sessions_locked(now)
            record = self._session_from_cookie_locked(cookie)
            if record is None:
                return False
            matches = hmac.compare_digest(candidate_bytes, record.csrf_token.encode("ascii"))
            return bool(matches & self._active)

    def revoke_session(self, cookie: str | None, csrf_token: str | None) -> list[str] | None:
        now = self.clock()
        candidate = csrf_token if isinstance(csrf_token, str) else ""
        try:
            candidate_bytes = candidate.encode("ascii")
        except UnicodeEncodeError:
            candidate_bytes = b""
        with self._lock:
            self._prune_expired_sessions_locked(now)
            record = self._session_from_cookie_locked(cookie)
            if record is None or not self._active:
                return None
            if not hmac.compare_digest(candidate_bytes, record.csrf_token.encode("ascii")):
                return None
            self._sessions.pop(record.session_id, None)
            self.limiters.close_session(record.session_id)
            socket_ids = list(record.sockets)
            for sid in socket_ids:
                self._sockets.pop(sid, None)
            return socket_ids

    def register_socket(
        self,
        sid: str,
        cookie: str | None,
        host: str | None,
        origin: str | None,
    ) -> bool:
        if not isinstance(sid, str) or not sid:
            return False
        if not self.request_identity_is_valid(host, origin, require_origin=True):
            return False
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            if not self._active:
                return False
            session = self._session_from_cookie_locked(cookie)
            if session is None:
                return False
            existing = self._sockets.get(sid)
            if existing is not None:
                return existing.session_id == session.session_id
            if len(self._sockets) >= MAX_CONCURRENT_PLAYER_SOCKETS:
                return False
            session.sockets.add(sid)
            self._sockets[sid] = _SocketRecord(session.session_id, host or "", origin or "")
            return True

    def authorize_socket_event(self, sid: str) -> bool:
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            socket_record = self._sockets.get(sid)
            if socket_record is None or not self._active:
                return False
            session = self._sessions.get(socket_record.session_id)
            return bool(
                session is not None
                and now < session.expires_at
                and socket_record.host == self.expected_host
                and socket_record.origin == self.expected_origin
            )

    def session_context_for_socket(self, sid: str) -> PlayerSessionIdentity | None:
        """Return the live authenticated context associated with a socket."""
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            socket_record = self._sockets.get(sid)
            if socket_record is None or not self._active:
                return None
            session = self._sessions.get(socket_record.session_id)
            if (
                session is None
                or now >= session.expires_at
                or socket_record.host != self.expected_host
                or socket_record.origin != self.expected_origin
            ):
                return None
            return PlayerSessionIdentity(
                instance_id=self._server_instance_id,
                session_id=session.session_id,
                session_epoch=session.session_epoch,
            )

    def authorized_socket_ids(self) -> list[str]:
        """Return only sockets bound to currently live, identity-valid sessions."""
        now = self.clock()
        with self._lock:
            self._prune_expired_sessions_locked(now)
            if not self._active:
                return []
            return [
                sid
                for sid, socket_record in self._sockets.items()
                if socket_record.host == self.expected_host
                and socket_record.origin == self.expected_origin
                and (session := self._sessions.get(socket_record.session_id)) is not None
                and now < session.expires_at
            ]

    def unregister_socket(self, sid: str) -> None:
        with self._lock:
            socket_record = self._sockets.pop(sid, None)
            if socket_record is None:
                return
            session = self._sessions.get(socket_record.session_id)
            if session is not None:
                session.sockets.discard(sid)

    def request_identity_is_valid(
        self,
        host: str | None,
        origin: str | None,
        *,
        require_origin: bool,
    ) -> bool:
        if host != self.expected_host:
            return False
        if origin is None:
            return not require_origin
        return origin == self.expected_origin

    def _sign_session_locked(self, session_id: str, expires_at: int) -> str:
        payload = f"v1|{self._server_instance_id}|{session_id}|{expires_at}".encode("ascii")
        signature = hmac.new(self._signing_key, payload, hashlib.sha256).digest()
        signature_text = _base64_urlsafe_encode(signature)
        return f"v1.{self._server_instance_id}.{session_id}.{expires_at}.{signature_text}"

    def _session_from_cookie_locked(self, cookie: str | None) -> _SessionRecord | None:
        if not self._active or not isinstance(cookie, str) or len(cookie) > 512:
            return None
        parts = cookie.split(".")
        if len(parts) != 5 or parts[0] != "v1" or parts[1] != self._server_instance_id:
            return None
        session_id = parts[2]
        expires_text = parts[3]
        signature_text = parts[4]
        if _TOKEN_RE.fullmatch(session_id) is None or _TOKEN_RE.fullmatch(signature_text) is None:
            return None
        if not expires_text.isascii() or not expires_text.isdigit() or len(expires_text) > 12:
            return None
        try:
            expires_at = int(expires_text)
        except ValueError:
            return None
        if str(expires_at) != expires_text:
            return None
        payload = f"v1|{self._server_instance_id}|{session_id}|{expires_at}".encode("ascii")
        expected_signature = hmac.new(self._signing_key, payload, hashlib.sha256).digest()
        expected_text = _base64_urlsafe_encode(expected_signature)
        if not hmac.compare_digest(signature_text, expected_text):
            return None
        record = self._sessions.get(session_id)
        if record is None or record.expires_at != expires_at or self.clock() >= expires_at:
            return None
        return record

    def _prune_prelogin_locked(self, now: float) -> None:
        expired = [cookie for cookie, (_nonce, expiry) in self._prelogin.items() if now >= expiry]
        for cookie in expired:
            self._prelogin.pop(cookie, None)

    def _prune_expired_sessions_locked(self, now: float | None = None) -> None:
        selected_now = self.clock() if now is None else now
        expired_ids = [
            session_id
            for session_id, record in self._sessions.items()
            if selected_now >= record.expires_at
        ]
        for session_id in expired_ids:
            record = self._sessions.pop(session_id, None)
            self.limiters.close_session(session_id)
            if record is None:
                continue
            for sid in record.sockets:
                self._sockets.pop(sid, None)


def _base64_urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


if __name__ == "__main__":
    raise SystemExit(_cli())
