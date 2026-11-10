# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Private storage for the existing N1 player credential verifier.

Credential creation and verification use the N1 scrypt implementation without
introducing another verifier format. These functions are synchronous; scrypt is
CPU-heavy, so async callers must offload them (for example with
``asyncio.to_thread``).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from web.extensions.player.auth import (
    ScryptCredentialVerifier,
    make_verifier,
    parse_verifier,
)
from web.extensions.player.limits import MAX_PASSWORD_BYTES

from . import profile_state
from .profile_state import ProfileLayout

VERIFIER_FILENAME = "player_verifier.json"
VERIFIER_SCHEMA = "neq.player_verifier.v1"
MAX_VERIFIER_FILE_BYTES = 4096
MAX_GENERATION = (1 << 63) - 1

VerifierStoreState = Literal["present", "absent", "invalid", "unsafe"]

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")
_CREDENTIAL_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_UTC_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z"
)
_STORE_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True, repr=False)
class VerifierLoad:
    """Bounded load state; verifier fields are intentionally omitted from repr."""

    state: VerifierStoreState
    reason: str
    verifier: ScryptCredentialVerifier | None = None
    raw_verifier: str | None = None
    generation: int | None = None
    issued_at: str | None = None

    def __repr__(self) -> str:
        return (
            "VerifierLoad("
            f"state={self.state!r}, reason={self.reason!r}, "
            f"generation={self.generation!r}, issued_at={self.issued_at!r})"
        )


@dataclass(frozen=True, slots=True)
class VerifierStatus:
    """Safe status projection that never includes parsed or raw verifier data."""

    state: VerifierStoreState
    reason: str
    generation: int | None = None
    issued_at: str | None = None


class IssuedCredential:
    """A one-shot plaintext holder with redacted representation and serialization."""

    __slots__ = ("__plaintext", "__revealed", "__lock")

    def __init__(self, plaintext: str) -> None:
        self.__plaintext: str | None = plaintext
        self.__revealed = False
        self.__lock = threading.Lock()

    def reveal(self) -> str:
        """Return the credential once, then clear this object's reference."""
        with self.__lock:
            if self.__revealed or self.__plaintext is None:
                raise RuntimeError("credential_already_revealed")
            plaintext = self.__plaintext
            self.__plaintext = None
            self.__revealed = True
            return plaintext

    def __repr__(self) -> str:
        return "<redacted>"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, _format_spec: str) -> str:
        return "<redacted>"

    def __reduce__(self) -> object:
        raise TypeError("issued credentials cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("issued credentials cannot be serialized")

    def __copy__(self) -> object:
        raise TypeError("issued credentials cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("issued credentials cannot be copied")

    def __del__(self) -> None:
        try:
            self.__plaintext = None
        except AttributeError:
            pass


class VerifierStoreError(RuntimeError):
    """A bounded storage failure that never echoes filesystem or secret values."""

    __slots__ = ("state", "reason")

    def __init__(self, state: VerifierStoreState, reason: str) -> None:
        self.state = state
        self.reason = reason[:40]
        super().__init__(f"{self.state}:{self.reason}")


@dataclass(frozen=True, slots=True, repr=False)
class _FileOutcome:
    load: VerifierLoad
    content: bytes | None = None
    metadata: os.stat_result | None = None
    safe_to_remove: bool = False


def issue_credential(layout: ProfileLayout) -> IssuedCredential:
    """Issue a credential only when no verifier exists; never replace implicitly.

    The returned object is the sole plaintext disclosure path. Rotation must use
    :func:`rotate_credential` so access revocation runs before replacement.
    """
    with _STORE_LOCK:
        current = _read_layout(layout)
        if current.load.state != "absent":
            _raise_load_error(current.load)
        return _issue_and_write(layout, generation=1, expected_content=None)


def rotate_credential(
    layout: ProfileLayout,
    revoke: Callable[[], None],
) -> IssuedCredential:
    """Rotate after successful revocation, preserving the old file on failure.

    The revoke callback runs before writing or accepting the new verifier. If it
    raises, the old verifier is left untouched and no temporary file is created.
    If no verifier exists, rotation creates generation 1 after the callback.
    """
    if not callable(revoke):
        raise VerifierStoreError("invalid", "revoke_callback_invalid")
    with _STORE_LOCK:
        current = _read_layout(layout)
        if current.load.state not in {"present", "absent"}:
            _raise_load_error(current.load)
        previous_generation = current.load.generation or 0
        if previous_generation >= MAX_GENERATION:
            raise VerifierStoreError("invalid", "generation_exhausted")
        try:
            revoke()
        except Exception:
            raise VerifierStoreError("invalid", "revoke_failed") from None
        return _issue_and_write(
            layout,
            generation=previous_generation + 1,
            expected_content=current.content,
        )


def load_verifier(layout: ProfileLayout) -> VerifierLoad:
    """Load a verifier without repairing or changing the profile store."""
    with _STORE_LOCK:
        return _read_layout(layout).load


def verifier_status(layout: ProfileLayout) -> VerifierStatus:
    """Return only bounded state, generation, and issuance time for diagnostics."""
    loaded = load_verifier(layout)
    return VerifierStatus(
        state=loaded.state,
        reason=loaded.reason,
        generation=loaded.generation,
        issued_at=loaded.issued_at,
    )


def revoke_access(
    layout: ProfileLayout,
    revoke: Callable[[], None],
) -> VerifierLoad:
    """Revoke sessions first, then remove only a safe verifier file.

    No verifier is written as part of revocation. Unsafe or oversized files are
    left untouched and returned as a bounded failure state.
    """
    if not callable(revoke):
        raise VerifierStoreError("invalid", "revoke_callback_invalid")
    with _STORE_LOCK:
        try:
            revoke()
        except Exception:
            raise VerifierStoreError("invalid", "revoke_failed") from None

        directory_fd, uid, reason = _open_layout_directory(layout)
        if directory_fd is None or uid is None:
            return _failure("unsafe", reason or "verifier_directory_unsafe")
        try:
            outcome = _read_file_at(directory_fd, uid, layout.profile)
            if outcome.load.state == "absent":
                return outcome.load
            if not outcome.safe_to_remove or outcome.metadata is None:
                return outcome.load
            try:
                current_metadata = os.stat(
                    VERIFIER_FILENAME,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return _failure("absent", "absent")
            except OSError:
                return _failure("unsafe", "verifier_file_unavailable")
            if not _same_file(current_metadata, outcome.metadata) or not _safe_file_metadata(
                current_metadata, uid
            ):
                return _failure("unsafe", "verifier_file_changed")
            try:
                os.unlink(VERIFIER_FILENAME, dir_fd=directory_fd)
            except FileNotFoundError:
                return _failure("absent", "absent")
            except OSError:
                return _failure("invalid", "verifier_remove_failed")
            _fsync_directory_best_effort(directory_fd)
            return _failure("absent", "absent")
        finally:
            os.close(directory_fd)


def _issue_and_write(
    layout: ProfileLayout,
    *,
    generation: int,
    expected_content: bytes | None,
) -> IssuedCredential:
    plaintext = ""
    verifier_string = ""
    payload = b""
    try:
        plaintext = secrets.token_urlsafe(32)
        if (
            not isinstance(plaintext, str)
            or _CREDENTIAL_RE.fullmatch(plaintext) is None
            or len(plaintext) > MAX_PASSWORD_BYTES
            or len(plaintext.encode("ascii")) > MAX_PASSWORD_BYTES
        ):
            raise VerifierStoreError("invalid", "credential_generation_failed")
        verifier_string = make_verifier(plaintext)
        parsed_verifier = parse_verifier(verifier_string)
        if parsed_verifier is None:
            raise VerifierStoreError("invalid", "verifier_generation_failed")
        issued_at = _utc_now()
        record = {
            "schema": VERIFIER_SCHEMA,
            "verifier": verifier_string,
            "issued_at": issued_at,
            "generation": generation,
            "profile": layout.profile,
        }
        payload = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        if len(payload) > MAX_VERIFIER_FILE_BYTES:
            raise VerifierStoreError("invalid", "verifier_record_too_large")
        _atomic_replace(layout, expected_content, payload)
        return IssuedCredential(plaintext)
    except VerifierStoreError:
        raise
    except Exception:
        raise VerifierStoreError("invalid", "verifier_write_failed") from None
    finally:
        # Best-effort removal of local references; immutable strings cannot be
        # reliably zeroized by Python.
        plaintext = ""
        verifier_string = ""
        payload = b""


def _atomic_replace(
    layout: ProfileLayout,
    expected_content: bytes | None,
    payload: bytes,
) -> None:
    directory_fd, uid, reason = _open_layout_directory(layout)
    if directory_fd is None or uid is None:
        raise VerifierStoreError("unsafe", reason or "verifier_directory_unsafe")

    temporary_name: str | None = None
    temporary_fd = -1
    temporary_created = False
    try:
        _ensure_expected_current(directory_fd, uid, layout.profile, expected_content)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise VerifierStoreError("unsafe", "nofollow_unavailable")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
        )
        temporary_name = ".player_verifier." + secrets.token_hex(16) + ".tmp"
        try:
            temporary_fd = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
            temporary_created = True
        except OSError:
            raise VerifierStoreError("invalid", "verifier_temp_create_failed") from None
        try:
            os.fchmod(temporary_fd, 0o600)
            with os.fdopen(temporary_fd, "wb") as stream:
                temporary_fd = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_metadata = os.fstat(stream.fileno())
                if not _safe_file_metadata(temporary_metadata, uid):
                    raise VerifierStoreError("unsafe", "verifier_temp_unsafe")
        except VerifierStoreError:
            raise
        except OSError:
            raise VerifierStoreError("invalid", "verifier_temp_write_failed") from None

        _ensure_expected_current(directory_fd, uid, layout.profile, expected_content)
        try:
            os.replace(
                temporary_name,
                VERIFIER_FILENAME,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_name = None
            temporary_created = False
        except OSError:
            raise VerifierStoreError("invalid", "verifier_replace_failed") from None
        _fsync_directory_best_effort(directory_fd)
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if temporary_name is not None and temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        os.close(directory_fd)


def _ensure_expected_current(
    directory_fd: int,
    uid: int,
    profile: str,
    expected_content: bytes | None,
) -> None:
    current = _read_file_at(directory_fd, uid, profile)
    if current.load.state == "unsafe":
        _raise_load_error(current.load)
    if current.load.state == "invalid":
        _raise_load_error(current.load)
    if expected_content is None:
        if current.load.state != "absent":
            raise VerifierStoreError("present", "credential_already_present")
        return
    if current.load.state != "present" or current.content != expected_content:
        raise VerifierStoreError("invalid", "verifier_changed")


def _read_layout(layout: ProfileLayout) -> _FileOutcome:
    directory_fd, uid, reason = _open_layout_directory(layout)
    if directory_fd is None or uid is None:
        return _FileOutcome(_failure("unsafe", reason or "verifier_directory_unsafe"))
    try:
        return _read_file_at(directory_fd, uid, layout.profile)
    finally:
        os.close(directory_fd)


def _open_layout_directory(
    layout: ProfileLayout,
) -> tuple[int | None, int | None, str | None]:
    try:
        if not isinstance(layout, ProfileLayout):
            return None, None, "layout_invalid"
        if not isinstance(layout.profile, str) or _PROFILE_RE.fullmatch(layout.profile) is None:
            return None, None, "layout_invalid"
        state_root = Path(layout.state_root)
        profile_root = Path(layout.profile_root)
        verifier_dir = Path(layout.verifier_dir)
        expected_profile_root = state_root / "neq" / "opentunnel" / layout.profile
        if (
            _normalized_path(profile_root) != _normalized_path(expected_profile_root)
            or _normalized_path(verifier_dir)
            != _normalized_path(profile_root / "verifier")
            or profile_state._is_forbidden_state_root(state_root)
        ):
            return None, None, "layout_unsafe"
        for path in (state_root, profile_root, verifier_dir):
            normalized = _normalized_path(path)
            if path.resolve(strict=True) != normalized:
                return None, None, "layout_symlink"
        try:
            uid = os.getuid()
        except (AttributeError, OSError):
            return None, None, "current_uid_unavailable"
        if not _private_directory_path(state_root, uid):
            return None, None, "state_root_unsafe"
        if not _private_directory_path(profile_root, uid):
            return None, None, "profile_directory_unsafe"
        if not _private_directory_path(verifier_dir, uid):
            return None, None, "verifier_directory_unsafe"
        verifier_metadata = os.lstat(verifier_dir)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory_flag is None:
            return None, None, "nofollow_unavailable"
        flags = os.O_RDONLY | nofollow | directory_flag | getattr(os, "O_CLOEXEC", 0)
        directory_fd = os.open(verifier_dir, flags)
        metadata = os.fstat(directory_fd)
        if not _safe_directory_metadata(metadata, uid) or not _same_file(
            metadata, verifier_metadata
        ):
            os.close(directory_fd)
            return None, None, "verifier_directory_unsafe"
        return directory_fd, uid, None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, None, "layout_unavailable"


def _private_directory_path(path: Path, uid: int) -> bool:
    try:
        return _safe_directory_metadata(os.lstat(path), uid)
    except OSError:
        return False


def _safe_directory_metadata(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _read_file_at(directory_fd: int, uid: int, profile: str) -> _FileOutcome:
    try:
        path_metadata = os.stat(
            VERIFIER_FILENAME,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return _FileOutcome(_failure("absent", "absent"))
    except OSError:
        return _FileOutcome(_failure("unsafe", "verifier_file_unavailable"))

    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        return _FileOutcome(_failure("unsafe", "verifier_file_not_regular"))
    if path_metadata.st_uid != uid:
        return _FileOutcome(_failure("unsafe", "verifier_file_owner_mismatch"))
    if stat.S_IMODE(path_metadata.st_mode) != 0o600:
        return _FileOutcome(_failure("unsafe", "verifier_file_not_private"))
    if path_metadata.st_size > MAX_VERIFIER_FILE_BYTES:
        return _FileOutcome(_failure("invalid", "verifier_file_too_large"))

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return _FileOutcome(_failure("unsafe", "nofollow_unavailable"))
    flags = (
        os.O_RDONLY
        | nofollow
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(VERIFIER_FILENAME, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return _FileOutcome(_failure("absent", "absent"))
    except OSError:
        return _FileOutcome(_failure("unsafe", "verifier_file_unavailable"))

    try:
        opened_metadata = os.fstat(descriptor)
        if (
            not _safe_file_metadata(opened_metadata, uid)
            or not _same_file(opened_metadata, path_metadata)
        ):
            return _FileOutcome(_failure("unsafe", "verifier_file_changed"))
        if opened_metadata.st_size > MAX_VERIFIER_FILE_BYTES:
            return _FileOutcome(_failure("invalid", "verifier_file_too_large"))
        payload = bytearray()
        while len(payload) <= MAX_VERIFIER_FILE_BYTES:
            chunk = os.read(
                descriptor,
                min(1024, MAX_VERIFIER_FILE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_VERIFIER_FILE_BYTES:
            return _FileOutcome(_failure("invalid", "verifier_file_too_large"))
        content = bytes(payload)
        loaded = _parse_record(content, profile)
        return _FileOutcome(
            loaded,
            content=content,
            metadata=opened_metadata,
            safe_to_remove=True,
        )
    except OSError:
        return _FileOutcome(_failure("unsafe", "verifier_file_unavailable"))
    finally:
        os.close(descriptor)


def _parse_record(content: bytes, profile: str) -> VerifierLoad:
    try:
        decoded = content.decode("ascii")
        record = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return _failure("invalid", "verifier_json_invalid")

    required_keys = {"schema", "verifier", "issued_at", "generation", "profile"}
    if not isinstance(record, dict) or set(record) != required_keys:
        return _failure("invalid", "verifier_record_shape_invalid")
    schema = record.get("schema")
    raw_verifier = record.get("verifier")
    issued_at = record.get("issued_at")
    generation = record.get("generation")
    stored_profile = record.get("profile")
    if schema != VERIFIER_SCHEMA or not isinstance(schema, str):
        return _failure("invalid", "verifier_schema_invalid")
    if not isinstance(raw_verifier, str):
        return _failure("invalid", "verifier_value_invalid")
    if not isinstance(issued_at, str) or not _valid_utc_timestamp(issued_at):
        return _failure("invalid", "issued_at_invalid")
    if (
        type(generation) is not int
        or generation < 1
        or generation > MAX_GENERATION
    ):
        return _failure("invalid", "generation_invalid")
    if not isinstance(stored_profile, str) or stored_profile != profile:
        return _failure("invalid", "profile_mismatch")
    parsed = parse_verifier(raw_verifier)
    if parsed is None:
        return _failure("invalid", "verifier_value_invalid")
    return VerifierLoad(
        state="present",
        reason="present",
        verifier=parsed,
        raw_verifier=raw_verifier,
        generation=generation,
        issued_at=issued_at,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non_finite_number")


def _safe_file_metadata(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size <= MAX_VERIFIER_FILE_BYTES
    )


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _normalized_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _fsync_directory_best_effort(directory_fd: int) -> None:
    try:
        os.fsync(directory_fd)
    except OSError:
        pass


def _failure(state: VerifierStoreState, reason: str) -> VerifierLoad:
    return VerifierLoad(state=state, reason=reason[:40])


def _raise_load_error(loaded: VerifierLoad) -> None:
    state: VerifierStoreState = loaded.state
    reason = loaded.reason
    if state == "present":
        reason = "credential_already_present"
    raise VerifierStoreError(state, reason)
