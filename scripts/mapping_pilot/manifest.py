# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fail-closed SHA-256 verification for frozen mapping-pilot inputs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Union


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREREG_ROOT = PROJECT_ROOT / "plans" / "v2-mapping-pilot-prereg"
MANIFEST_NAME = "MANIFEST.sha256"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestVerificationError(ValueError):
    """Raised when the frozen manifest or one of its entries cannot be verified."""

    def __init__(self, relative_path: str, reason: str) -> None:
        self.relative_path = relative_path
        self.reason = reason
        super().__init__("%s: %s" % (reason, relative_path))


def _source_root(prereg_root: Optional[Union[str, Path]]) -> Path:
    if prereg_root is None:
        candidate = DEFAULT_PREREG_ROOT
    else:
        candidate = Path(prereg_root)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _parse_manifest(manifest_path: Path) -> Dict[str, str]:
    try:
        lines = manifest_path.read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise ManifestVerificationError(MANIFEST_NAME, "cannot read manifest") from exc
    except UnicodeError as exc:
        raise ManifestVerificationError(MANIFEST_NAME, "manifest is not ASCII") from exc

    records: Dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        fields = line.split(None, 1)
        if len(fields) != 2:
            raise ManifestVerificationError(
                "%s:%d" % (MANIFEST_NAME, line_number), "malformed manifest entry"
            )
        expected_hash, raw_path = fields
        relative_path = raw_path.strip()
        parsed_path = PurePosixPath(relative_path)
        if (
            not _SHA256_PATTERN.fullmatch(expected_hash)
            or not relative_path
            or parsed_path.is_absolute()
            or ".." in parsed_path.parts
            or "\\" in relative_path
            or "." in parsed_path.parts
        ):
            raise ManifestVerificationError(
                relative_path or ("%s:%d" % (MANIFEST_NAME, line_number)),
                "malformed or unsafe manifest entry",
            )
        if relative_path in records:
            raise ManifestVerificationError(relative_path, "duplicate manifest entry")
        records[relative_path] = expected_hash.lower()

    if not records:
        raise ManifestVerificationError(MANIFEST_NAME, "manifest has no entries")
    return records


def verify_manifest(
    prereg_root: Optional[Union[str, Path]] = None,
) -> Dict[str, str]:
    """Verify every listed path and return its normalized relative path and SHA-256.

    The manifest is intentionally not self-hashed. All paths are interpreted as
    POSIX paths relative to the preregistration directory and are prevented from
    escaping it, including through symlinks.
    """
    root = _source_root(prereg_root)
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManifestVerificationError(MANIFEST_NAME, "missing or unsafe manifest")

    records = _parse_manifest(manifest_path)
    for relative_path, expected_hash in records.items():
        source_path = root.joinpath(*PurePosixPath(relative_path).parts)
        try:
            resolved_path = source_path.resolve(strict=True)
            resolved_path.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ManifestVerificationError(relative_path, "missing or unsafe file") from exc
        if not resolved_path.is_file():
            raise ManifestVerificationError(relative_path, "missing file")
        try:
            actual_hash = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ManifestVerificationError(relative_path, "cannot read file") from exc
        if actual_hash != expected_hash:
            raise ManifestVerificationError(relative_path, "SHA-256 mismatch")
    return records
