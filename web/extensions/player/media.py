# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Resolve opaque player media IDs through a server-owned root registry."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .limits import MAX_PLAYER_MEDIA_BYTES

_MEDIA_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_ROOT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def player_portrait_media_id(character_name: object) -> str | None:
    """Return a stable opaque portrait ID; MediaRegistry still controls access."""
    if not isinstance(character_name, str):
        return None
    name = character_name.strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or not name.isprintable()
    ):
        return None
    try:
        if len(name.encode("utf-8")) > 128:
            return None
        digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:32]
    except UnicodeEncodeError:
        return None
    return f"pc-{digest}"


@dataclass(frozen=True, slots=True)
class MediaRegistration:
    """A server-owned media ID and a relative path beneath one approved root."""

    root_id: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class PlayerMedia:
    """Bounded media bytes and a server-selected safe content type."""

    body: bytes
    content_type: str


class MediaRegistry:
    """Resolve only registered IDs and never expose a path to the caller."""

    def __init__(
        self,
        approved_roots: Mapping[str, str | Path] | None = None,
        registrations: Mapping[str, MediaRegistration] | None = None,
    ) -> None:
        roots: dict[str, Path] = {}
        for root_id, root_path in (approved_roots or {}).items():
            if not isinstance(root_id, str) or _ROOT_ID_RE.fullmatch(root_id) is None:
                raise ValueError("invalid media root identifier")
            try:
                resolved_root = Path(root_path).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("approved media root is unavailable") from exc
            if not resolved_root.is_dir():
                raise ValueError("approved media root must be a directory")
            roots[root_id] = resolved_root

        selected_registrations: dict[str, MediaRegistration] = {}
        for media_id, registration in (registrations or {}).items():
            if not isinstance(media_id, str) or _MEDIA_ID_RE.fullmatch(media_id) is None:
                raise ValueError("invalid media identifier")
            if not isinstance(registration, MediaRegistration):
                raise ValueError("media registration must use MediaRegistration")
            if registration.root_id not in roots:
                raise ValueError("media registration references an unknown root")
            selected_registrations[media_id] = registration

        self._roots = roots
        self._registrations = selected_registrations

    def read(self, media_id: object) -> PlayerMedia | None:
        """Read one small approved image, returning None for every denial."""
        if not isinstance(media_id, str) or _MEDIA_ID_RE.fullmatch(media_id) is None:
            return None
        registration = self._registrations.get(media_id)
        if registration is None:
            return None
        root = self._roots.get(registration.root_id)
        if root is None:
            return None
        relative = registration.relative_path
        if not isinstance(relative, str) or not relative or "\\" in relative:
            return None
        relative_path = PurePosixPath(relative)
        if relative_path.is_absolute() or any(
            part in ("", ".", "..") for part in relative_path.parts
        ):
            return None

        try:
            target = (root / Path(*relative_path.parts)).resolve(strict=True)
            target.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None

        content_type = _MEDIA_TYPES.get(target.suffix.casefold())
        if content_type is None:
            return None

        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PLAYER_MEDIA_BYTES:
                return None
            with os.fdopen(descriptor, "rb") as media_file:
                descriptor = None
                body = media_file.read(MAX_PLAYER_MEDIA_BYTES + 1)
            if len(body) > MAX_PLAYER_MEDIA_BYTES:
                return None
            return PlayerMedia(body=body, content_type=content_type)
        except (OSError, ValueError):
            return None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
