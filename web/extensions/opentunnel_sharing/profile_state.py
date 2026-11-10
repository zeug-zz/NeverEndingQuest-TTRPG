# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Create and validate private per-profile OpenTunnel state without side effects."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Mapping

DEFAULT_PROFILE = "neq-share"
PROFILE_OWNER_SCHEMA = "neq.opentunnel.profile_owner.v1"
PROFILE_OWNER_FILENAME = "profile_owner.json"
MAX_OWNER_FILE_BYTES = 4096
MAX_INSTALL_MARKER_CHARS = 128
MAX_UNIX_SOCKET_PATH = 104

ProfileStateName = Literal[
    "ready",
    "absent",
    "invalid",
    "foreign",
    "foreign_or_invalid",
    "unsafe_path",
]

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")
_INSTALL_MARKER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_VENV_COMPONENTS = frozenset({".venv", "venv"})
_LAYOUT_DIRS = ("config", "data", "state", "run", "verifier")
_INSTALL_ROOT = Path(__file__).resolve().parents[3]
_REPOSITORY_ROOT = _INSTALL_ROOT


@dataclass(frozen=True, slots=True)
class ProfileLayout:
    """Validated paths for one isolated OpenTunnel profile."""

    profile: str
    state_root: Path
    profile_root: Path
    config_home: Path
    data_home: Path
    state_home: Path
    runtime_dir: Path
    verifier_dir: Path
    owner_file: Path
    socket_path: Path


@dataclass(frozen=True, slots=True)
class ProfileState:
    """A bounded profile-state result; layout is present only when ready."""

    state: ProfileStateName
    reason: str
    layout: ProfileLayout | None = None


class _ProfileFailure(Exception):
    def __init__(self, state: ProfileStateName, reason: str) -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason


def default_state_root(
    environ: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Compute a safe per-user state root using XDG state/data or home fallback.

    XDG_STATE_HOME takes precedence. If it is absent, XDG_DATA_HOME/state is
    used; otherwise the XDG default of ~/.local/state applies. Unsafe locations
    are rejected rather than redirected to a temporary directory.
    """
    selected_env = os.environ if environ is None else environ
    if home is not None:
        selected_home = Path(home)
    elif selected_env.get("HOME"):
        selected_home = Path(selected_env["HOME"])
    else:
        selected_home = Path.home()
    if not selected_home.is_absolute():
        raise ValueError("unsafe_state_root")

    state_value = selected_env.get("XDG_STATE_HOME")
    data_value = selected_env.get("XDG_DATA_HOME")
    if state_value:
        candidate = _expand_user_path(state_value, selected_home)
    elif data_value:
        candidate = _expand_user_path(data_value, selected_home).parent / "state"
    else:
        candidate = selected_home / ".local" / "state"

    normalized = Path(os.path.abspath(os.fspath(candidate)))
    if (
        not normalized.is_absolute()
        or _is_forbidden_state_root(normalized)
        or _has_symlink_or_non_directory_ancestor(normalized)
    ):
        raise ValueError("unsafe_state_root")
    return normalized


def prepare_profile(
    state_root: Path,
    *,
    install_marker: str,
    profile: str = DEFAULT_PROFILE,
    create: bool,
) -> ProfileState:
    """Validate or create the dedicated private state for one OpenTunnel profile.

    The function touches only expected path components for the supplied profile;
    it never enumerates sibling profiles. Existing directories and ownership
    metadata with unexpected modes, owners, links, or values fail closed.
    """
    if not isinstance(create, bool):
        return _failure("invalid", "create_flag_invalid")
    if not isinstance(profile, str) or _PROFILE_RE.fullmatch(profile) is None:
        return _failure("invalid", "profile_slug_invalid")
    if (
        not isinstance(install_marker, str)
        or len(install_marker) > MAX_INSTALL_MARKER_CHARS
        or _INSTALL_MARKER_RE.fullmatch(install_marker) is None
    ):
        return _failure("invalid", "install_marker_invalid")

    try:
        uid = os.getuid()
    except (AttributeError, OSError):
        return _failure("invalid", "current_uid_unavailable")

    try:
        root_path = _validated_state_root_path(state_root)
        profile_root = root_path / "neq" / "opentunnel" / profile
        socket_path = profile_root / "run" / (profile + ".sock")
        if len(os.fsencode(os.fspath(socket_path))) >= MAX_UNIX_SOCKET_PATH:
            raise _ProfileFailure("unsafe_path", "runtime_socket_path_too_long")

        _ensure_state_root(root_path, uid, create=create)
        root_real = root_path.resolve(strict=True)
        directories = (
            root_path / "neq",
            root_path / "neq" / "opentunnel",
            profile_root,
        )
        profile_created = False
        for directory in directories:
            was_created = _ensure_private_directory(
                directory,
                uid,
                create=create,
                containment_root=root_real,
            )
            if directory == profile_root:
                profile_created = was_created

        profile_real = profile_root.resolve(strict=True)
        owner_file = profile_root / PROFILE_OWNER_FILENAME
        owner_metadata = _lstat_optional(owner_file)
        owner_is_new = owner_metadata is None
        if owner_is_new:
            if not create or not profile_created:
                raise _ProfileFailure(
                    "foreign_or_invalid", "owner_metadata_missing"
                )
        elif not _owner_metadata_matches(
            owner_file,
            profile=profile,
            install_marker=install_marker,
            uid=uid,
            expected_lstat=owner_metadata,
        ):
            raise _ProfileFailure(
                "foreign_or_invalid", "owner_metadata_foreign_or_invalid"
            )

        child_dirs: dict[str, Path] = {}
        for directory_name in _LAYOUT_DIRS:
            directory = profile_root / directory_name
            _ensure_private_directory(
                directory,
                uid,
                create=create,
                containment_root=profile_real,
            )
            child_dirs[directory_name] = directory.resolve(strict=True)

        if owner_is_new:
            owner_value = {
                "schema": PROFILE_OWNER_SCHEMA,
                "profile": profile,
                "created_at": _utc_now(),
                "neq_install_marker": install_marker,
                "uid": uid,
            }
            try:
                _write_owner_atomically(owner_file, owner_value, uid=uid)
            except (OSError, TypeError, ValueError):
                raise _ProfileFailure("invalid", "owner_write_failed") from None

        final_owner_metadata = _lstat_optional(owner_file)
        if final_owner_metadata is None or not _is_private_regular_file(
            final_owner_metadata, uid
        ):
            raise _ProfileFailure("foreign_or_invalid", "owner_metadata_invalid")
        if not _is_within(owner_file.resolve(strict=True), profile_real):
            raise _ProfileFailure("unsafe_path", "owner_file_outside_profile")

        layout = ProfileLayout(
            profile=profile,
            state_root=root_real,
            profile_root=profile_real,
            config_home=child_dirs["config"],
            data_home=child_dirs["data"],
            state_home=child_dirs["state"],
            runtime_dir=child_dirs["run"],
            verifier_dir=child_dirs["verifier"],
            owner_file=owner_file.resolve(strict=True),
            socket_path=child_dirs["run"] / (profile + ".sock"),
        )
        return ProfileState(state="ready", reason="ready", layout=layout)
    except _ProfileFailure as failure:
        return _failure(failure.state, failure.reason)
    except (OSError, RuntimeError, TypeError, ValueError):
        return _failure("invalid", "profile_state_unavailable")


def companion_environment(layout: ProfileLayout) -> dict[str, str]:
    """Return only the five isolated home/XDG variables; never inherit PATH."""
    return {
        "HOME": str(layout.data_home),
        "XDG_CONFIG_HOME": str(layout.config_home),
        "XDG_DATA_HOME": str(layout.data_home),
        "XDG_STATE_HOME": str(layout.state_home),
        "XDG_RUNTIME_DIR": str(layout.runtime_dir),
    }


def _expand_user_path(value: str, home: Path) -> Path:
    candidate = Path(value)
    if candidate == Path("~"):
        return home
    if value.startswith("~/"):
        return home / value[2:]
    if not candidate.is_absolute():
        raise ValueError("unsafe_state_root")
    return candidate


def _validated_state_root_path(state_root: Path) -> Path:
    try:
        candidate = Path(state_root).expanduser()
        if not candidate.is_absolute():
            raise _ProfileFailure("unsafe_path", "state_root_not_absolute")
        normalized = Path(os.path.abspath(os.fspath(candidate)))
    except (OSError, TypeError, ValueError):
        raise _ProfileFailure("unsafe_path", "state_root_invalid") from None

    if _is_forbidden_state_root(normalized):
        raise _ProfileFailure("unsafe_path", "state_root_forbidden_location")
    if _has_symlink_or_non_directory_ancestor(normalized):
        raise _ProfileFailure("unsafe_path", "state_root_symlink_or_ancestor")
    return normalized


def _has_symlink_or_non_directory_ancestor(path: Path) -> bool:
    cursor = Path(path.anchor)
    for index, component in enumerate(path.parts[1:]):
        cursor = cursor / component
        try:
            metadata = os.lstat(cursor)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if stat.S_ISLNK(metadata.st_mode):
            return True
        if index < len(path.parts[1:]) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return True
    return False


def _protected_roots() -> tuple[Path, ...]:
    return (
        _REPOSITORY_ROOT,
        _INSTALL_ROOT,
        _REPOSITORY_ROOT / "modules",
        _REPOSITORY_ROOT / "characters",
        _REPOSITORY_ROOT / "party_tracker.json",
    )


def _is_forbidden_state_root(path: Path) -> bool:
    if any(component in _VENV_COMPONENTS for component in path.parts):
        return True
    try:
        normalized = Path(os.path.abspath(os.fspath(path)))
        for protected in _protected_roots():
            protected_path = Path(os.path.abspath(os.fspath(protected)))
            if _is_within(normalized, protected_path) or _is_within(
                protected_path, normalized
            ):
                return True
    except (OSError, TypeError, ValueError):
        return True
    return False


def _ensure_state_root(path: Path, uid: int, *, create: bool) -> bool:
    """Ensure the injected root exists privately; return whether it was made."""
    missing: list[Path] = []
    cursor = path
    while True:
        metadata = _lstat_optional(cursor)
        if metadata is not None:
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise _ProfileFailure("unsafe_path", "state_root_not_directory")
            break
        missing.append(cursor)
        if cursor.parent == cursor:
            raise _ProfileFailure("unsafe_path", "state_root_parent_missing")
        cursor = cursor.parent

    if missing and not create:
        raise _ProfileFailure("absent", "profile_state_absent")
    created_root = False
    for directory in reversed(missing):
        created = _create_private_directory(directory, uid)
        if directory == path:
            created_root = created

    root_metadata = _lstat_optional(path)
    if root_metadata is None:
        raise _ProfileFailure("invalid", "state_root_missing")
    if not _is_private_directory(root_metadata, uid):
        if root_metadata.st_uid != uid:
            raise _ProfileFailure("foreign", "state_root_foreign_owner")
        raise _ProfileFailure("unsafe_path", "state_root_not_private")
    return created_root


def _ensure_private_directory(
    path: Path,
    uid: int,
    *,
    create: bool,
    containment_root: Path,
) -> bool:
    metadata = _lstat_optional(path)
    if metadata is None:
        if not create:
            raise _ProfileFailure("absent", "profile_state_absent")
        created = _create_private_directory(path, uid)
        metadata = _lstat_optional(path)
        if metadata is None:
            raise _ProfileFailure("invalid", "profile_directory_missing")
    else:
        created = False

    if stat.S_ISLNK(metadata.st_mode):
        raise _ProfileFailure("unsafe_path", "profile_directory_symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise _ProfileFailure("unsafe_path", "profile_component_not_directory")
    if metadata.st_uid != uid:
        raise _ProfileFailure("foreign", "profile_directory_foreign_owner")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise _ProfileFailure("unsafe_path", "profile_directory_not_private")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise _ProfileFailure("unsafe_path", "profile_directory_unavailable") from None
    if not _is_within(resolved, containment_root):
        raise _ProfileFailure("unsafe_path", "profile_directory_outside_root")
    return created


def _create_private_directory(path: Path, uid: int) -> bool:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        return False
    except OSError:
        raise _ProfileFailure("invalid", "profile_directory_create_failed") from None

    try:
        os.chmod(path, 0o700, follow_symlinks=False)
    except (NotImplementedError, TypeError):
        metadata = _lstat_optional(path)
        if metadata is None or stat.S_ISLNK(metadata.st_mode):
            raise _ProfileFailure("unsafe_path", "profile_directory_symlink") from None
        try:
            os.chmod(path, 0o700)
        except OSError:
            raise _ProfileFailure("invalid", "profile_directory_mode_failed") from None
    except OSError:
        raise _ProfileFailure("invalid", "profile_directory_mode_failed") from None

    metadata = _lstat_optional(path)
    if metadata is None or not _is_private_directory(metadata, uid):
        raise _ProfileFailure("unsafe_path", "profile_directory_verification_failed")
    return True


def _is_private_directory(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise _ProfileFailure("invalid", "profile_path_unavailable") from None


def _owner_metadata_matches(
    path: Path,
    *,
    profile: str,
    install_marker: str,
    uid: int,
    expected_lstat: os.stat_result,
) -> bool:
    if not _is_private_regular_file(expected_lstat, uid):
        return False
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        opened = os.fstat(descriptor)
        if (
            not _is_private_regular_file(opened, uid)
            or opened.st_dev != expected_lstat.st_dev
            or opened.st_ino != expected_lstat.st_ino
            or opened.st_size > MAX_OWNER_FILE_BYTES
        ):
            return False
        payload = bytearray()
        while len(payload) <= MAX_OWNER_FILE_BYTES:
            chunk = os.read(
                descriptor,
                min(1024, MAX_OWNER_FILE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_OWNER_FILE_BYTES:
            return False
    finally:
        os.close(descriptor)

    try:
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    expected_keys = {
        "schema",
        "profile",
        "created_at",
        "neq_install_marker",
        "uid",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        return False
    if (
        value.get("schema") != PROFILE_OWNER_SCHEMA
        or value.get("profile") != profile
        or value.get("neq_install_marker") != install_marker
        or type(value.get("uid")) is not int
        or value.get("uid") != uid
    ):
        return False
    return _is_utc_timestamp(value.get("created_at"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_owner_key")
        result[key] = value
    return result


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _is_private_regular_file(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size <= MAX_OWNER_FILE_BYTES
    )


def _write_owner_atomically(
    path: Path,
    value: Mapping[str, object],
    *,
    uid: int,
) -> None:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if len(payload) > MAX_OWNER_FILE_BYTES:
        raise ValueError("owner_metadata_too_large")

    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".profile_owner.", suffix=".tmp", dir=os.fspath(path.parent)
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_metadata = os.lstat(temporary_path)
        if not _is_private_regular_file(temporary_metadata, uid):
            raise OSError("owner_temp_not_private")
        if _lstat_optional(path) is not None:
            raise FileExistsError("owner_metadata_already_exists")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _failure(state: ProfileStateName, reason: str) -> ProfileState:
    return ProfileState(state=state, reason=reason[:40])
