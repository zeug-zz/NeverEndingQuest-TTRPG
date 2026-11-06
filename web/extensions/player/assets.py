# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Load and verify the complete player client bundle before listener startup."""

from __future__ import annotations

import hashlib
import html.parser
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, NoReturn

DEFAULT_PLAYER_BUILD_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dist"
MANIFEST_FILENAME = "player-manifest.json"
SHELL_FILENAME = "index.html"
PRELOGIN_CSRF_PLACEHOLDER = b"__NEQ_PRELOGIN_CSRF_NONCE__"

MAX_MANIFEST_BYTES = 64 * 1024
MAX_PLAYER_SHELL_BYTES = 1024 * 1024
MAX_PLAYER_ASSET_COUNT = 64
MAX_PLAYER_ASSET_BYTES = 8 * 1024 * 1024

_ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_HASHED_FILENAME_PATTERN = re.compile(
    r"^.+-[A-Za-z0-9_-]{8,}\.(?:css|js|png|svg|woff2)$"
)
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_BUILD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_ASSET_CONTENT_TYPES = MappingProxyType(
    {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
    }
)
_TOP_LEVEL_FIELDS = frozenset(
    {"manifest_version", "protocol_version", "client_build_id", "shell", "assets"}
)
_FILE_FIELDS = frozenset({"file", "sha256", "bytes", "content_type"})


class PlayerClientAssetsError(RuntimeError):
    """A bounded failure identifying why the player bundle was not accepted."""

    _MESSAGES = MappingProxyType(
        {
            "missing_bundle": "player client bundle is unavailable",
            "missing_manifest": "player client manifest is missing",
            "invalid_manifest": "player client manifest is invalid",
            "unsupported_version": "player client bundle version is unsupported",
            "incomplete_bundle": "player client bundle is incomplete",
            "invalid_asset": "player client bundle contains an invalid asset",
        }
    )

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            code = "invalid_manifest"
        self.code = code
        super().__init__(self._MESSAGES[code])


@dataclass(frozen=True)
class VerifiedPlayerAsset:
    """One manifest-listed asset held as verified immutable bytes."""

    content_type: bytes
    body: bytes


@dataclass(frozen=True)
class VerifiedPlayerClientAssets:
    """The verified shell and finite manifest asset map for one listener."""

    shell_document: bytes
    shell_content_type: bytes
    client_build_id: str
    protocol_version: int
    assets: Mapping[str, VerifiedPlayerAsset]


class _ShellAssetReferenceParser(html.parser.HTMLParser):
    """Reject shell script/style references not backed by the exact manifest."""

    def __init__(self, asset_ids: frozenset[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._asset_ids = asset_ids
        self._inside_script = False
        self.script_count = 0
        self.references_valid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._inside_script = True
            self.script_count += 1
        if tag not in {"script", "link"}:
            return
        source_attr = "src" if tag == "script" else "href"
        values = [value for name, value in attrs if name == source_attr]
        if len(values) != 1 or values[0] is None:
            self.references_valid = False
            return
        url = values[0]
        prefix = "/static/player/"
        if not url.startswith(prefix):
            self.references_valid = False
            return
        asset_id = url[len(prefix):]
        if (
            not _is_valid_asset_id(asset_id)
            or "%" in url
            or "?" in url
            or "#" in url
            or asset_id not in self._asset_ids
        ):
            self.references_valid = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_script and data.strip():
            self.references_valid = False


def load_player_client_assets(
    build_root: str | os.PathLike[str] | None = None,
) -> VerifiedPlayerClientAssets:
    """Validate every manifest entry and retain its bytes for safe serving."""
    try:
        selected_root = (
            DEFAULT_PLAYER_BUILD_ROOT if build_root is None else Path(build_root)
        )
        root = selected_root.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        _raise_assets_error("missing_bundle")
    if not root.is_dir():
        _raise_assets_error("missing_bundle")

    root_fd: int | None = None
    try:
        root_fd = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        manifest_bytes = _read_regular_file(
            root_fd,
            MANIFEST_FILENAME,
            MAX_MANIFEST_BYTES,
            missing_code="missing_manifest",
        )
        manifest = _parse_manifest(manifest_bytes)
        verified = _verify_manifest(root_fd, manifest)
        return verified
    except PlayerClientAssetsError:
        raise
    except (OSError, OverflowError, RecursionError, TypeError, ValueError):
        _raise_assets_error("invalid_manifest")
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _read_regular_file(
    root_fd: int,
    filename: str,
    max_bytes: int,
    *,
    missing_code: str,
    expected_bytes: int | None = None,
) -> bytes:
    """Read one safe flat file relative to the already-open build directory."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_fd = os.open(filename, flags, dir_fd=root_fd)
    except FileNotFoundError:
        _raise_assets_error(missing_code)
    except (OSError, ValueError):
        _raise_assets_error("invalid_asset")

    try:
        file_info = os.fstat(file_fd)
        if not stat.S_ISREG(file_info.st_mode):
            _raise_assets_error("invalid_asset")
        if file_info.st_size < 0 or file_info.st_size > max_bytes:
            _raise_assets_error("invalid_asset")
        if expected_bytes is not None and file_info.st_size != expected_bytes:
            _raise_assets_error("incomplete_bundle")
        initial_size = file_info.st_size
        with os.fdopen(file_fd, "rb") as asset_file:
            file_fd = -1
            body = asset_file.read(max_bytes + 1)
        if len(body) > max_bytes:
            _raise_assets_error("invalid_asset")
        if len(body) != initial_size:
            _raise_assets_error("incomplete_bundle")
        if expected_bytes is not None and len(body) != expected_bytes:
            _raise_assets_error("incomplete_bundle")
        return body
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def _parse_manifest(manifest_bytes: bytes) -> dict[str, Any]:
    try:
        manifest_text = manifest_bytes.decode("ascii")
        value = json.loads(manifest_text, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _raise_assets_error("invalid_manifest")
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_FIELDS:
        _raise_assets_error("invalid_manifest")
    if type(value.get("manifest_version")) is not int or type(
        value.get("protocol_version")
    ) is not int:
        _raise_assets_error("invalid_manifest")
    if value["manifest_version"] != 1 or value["protocol_version"] != 1:
        _raise_assets_error("unsupported_version")
    return value


def _verify_manifest(
    root_fd: int,
    manifest: Mapping[str, Any],
) -> VerifiedPlayerClientAssets:
    build_id = manifest.get("client_build_id")
    if not isinstance(build_id, str) or not _BUILD_ID_PATTERN.fullmatch(build_id):
        _raise_assets_error("invalid_manifest")

    shell_record = manifest.get("shell")
    asset_records = manifest.get("assets")
    if not isinstance(shell_record, dict) or set(shell_record) != _FILE_FIELDS:
        _raise_assets_error("invalid_manifest")
    if not isinstance(asset_records, dict) or not asset_records:
        _raise_assets_error("incomplete_bundle")
    if len(asset_records) > MAX_PLAYER_ASSET_COUNT:
        _raise_assets_error("invalid_manifest")

    shell_bytes_expected = _validate_file_record(
        shell_record,
        filename=SHELL_FILENAME,
        expected_content_type="text/html; charset=utf-8",
        max_bytes=MAX_PLAYER_SHELL_BYTES,
        require_hashed_name=False,
    )
    shell = _read_regular_file(
        root_fd,
        SHELL_FILENAME,
        MAX_PLAYER_SHELL_BYTES,
        missing_code="incomplete_bundle",
        expected_bytes=shell_bytes_expected,
    )
    if not _matches_digest(shell, shell_record["sha256"]):
        _raise_assets_error("invalid_asset")
    if not shell or not shell.isascii():
        _raise_assets_error("invalid_asset")

    verified_assets: dict[str, VerifiedPlayerAsset] = {}
    total_bytes = 0
    digest_rows: list[tuple[str, str]] = []
    for asset_id, record in asset_records.items():
        if not _is_valid_asset_id(asset_id):
            _raise_assets_error("invalid_manifest")
        if not isinstance(record, dict) or set(record) != _FILE_FIELDS:
            _raise_assets_error("invalid_manifest")
        extension = Path(asset_id).suffix.lower()
        expected_content_type = _ASSET_CONTENT_TYPES.get(extension)
        if expected_content_type is None:
            _raise_assets_error("invalid_asset")
        expected_bytes = _validate_file_record(
            record,
            filename=asset_id,
            expected_content_type=expected_content_type,
            max_bytes=MAX_PLAYER_ASSET_BYTES,
            require_hashed_name=True,
        )
        total_bytes += expected_bytes
        if total_bytes > MAX_PLAYER_ASSET_BYTES:
            _raise_assets_error("invalid_manifest")
        body = _read_regular_file(
            root_fd,
            asset_id,
            MAX_PLAYER_ASSET_BYTES,
            missing_code="incomplete_bundle",
            expected_bytes=expected_bytes,
        )
        digest = record["sha256"]
        if not _matches_digest(body, digest):
            _raise_assets_error("invalid_asset")
        verified_assets[asset_id] = VerifiedPlayerAsset(
            content_type=expected_content_type.encode("ascii"),
            body=body,
        )
        digest_rows.append((asset_id, digest))

    expected_build_id = hashlib.sha256(
        "".join(f"{asset_id}\t{digest}\n" for asset_id, digest in sorted(digest_rows)).encode(
            "ascii"
        )
    ).hexdigest()[:32]
    if build_id != expected_build_id:
        _raise_assets_error("invalid_manifest")
    if not _shell_metadata_matches(shell, build_id):
        _raise_assets_error("invalid_manifest")
    if shell.count(PRELOGIN_CSRF_PLACEHOLDER) != 1:
        _raise_assets_error("incomplete_bundle")

    parser = _ShellAssetReferenceParser(frozenset(verified_assets))
    try:
        parser.feed(shell.decode("ascii"))
        parser.close()
    except (ValueError, RecursionError):
        _raise_assets_error("invalid_asset")
    if not parser.references_valid or parser.script_count == 0:
        _raise_assets_error("incomplete_bundle")

    return VerifiedPlayerClientAssets(
        shell_document=shell,
        shell_content_type=b"text/html; charset=utf-8",
        client_build_id=build_id,
        protocol_version=1,
        assets=MappingProxyType(verified_assets),
    )


def _validate_file_record(
    record: Mapping[str, Any],
    *,
    filename: str,
    expected_content_type: str,
    max_bytes: int,
    require_hashed_name: bool,
) -> int:
    if record.get("file") != filename:
        _raise_assets_error("invalid_manifest")
    if require_hashed_name and not _HASHED_FILENAME_PATTERN.fullmatch(filename):
        _raise_assets_error("invalid_manifest")
    digest = record.get("sha256")
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        _raise_assets_error("invalid_manifest")
    byte_length = record.get("bytes")
    if type(byte_length) is not int or byte_length < 0 or byte_length > max_bytes:
        _raise_assets_error("invalid_manifest")
    if record.get("content_type") != expected_content_type:
        _raise_assets_error("invalid_manifest")
    return byte_length


def _shell_metadata_matches(shell: bytes, build_id: str) -> bool:
    escaped_build_id = re.escape(build_id.encode("ascii"))
    build_pattern = re.compile(
        rb'<meta\s+name=["\']neq-client-build["\']\s+'
        rb'content=["\']' + escaped_build_id + rb'["\']\s*/?>',
        re.IGNORECASE,
    )
    protocol_pattern = re.compile(
        rb'<meta\s+name=["\']neq-protocol-version["\']\s+'
        rb'content=["\']1["\']\s*/?>',
        re.IGNORECASE,
    )
    return bool(build_pattern.search(shell) and protocol_pattern.search(shell))


def _matches_digest(body: bytes, expected_digest: object) -> bool:
    return isinstance(expected_digest, str) and hashlib.sha256(body).hexdigest() == expected_digest


def _is_valid_asset_id(asset_id: object) -> bool:
    return (
        isinstance(asset_id, str)
        and asset_id not in {".", ".."}
        and _ASSET_ID_PATTERN.fullmatch(asset_id) is not None
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def _raise_assets_error(code: str) -> NoReturn:
    raise PlayerClientAssetsError(code) from None
