# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Strict offline reader for pinned player-bundle release identities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

PLAYER_RELEASE_BASE = (
    "https://github.com/zeug-zz/NeverEndingQuest-TTRPG/releases/download/"
)
PLAYER_BUNDLE_METADATA_SCHEMA = 1
MAX_PLAYER_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_PLAYER_BUNDLE_METADATA_BYTES = 64 * 1024

_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
_SOURCE_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_BUILD_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_BUNDLE_NAME_RE = re.compile(
    r"neq-player-bundle-([0-9]+\.[0-9]+\.[0-9]+)\.tar\.gz\Z"
)
_METADATA_NAME_RE = re.compile(
    r"neq-player-bundle-([0-9]+\.[0-9]+\.[0-9]+)\.metadata\.json\Z"
)
_REGISTRY_KEYS = frozenset({"versions"})
_PIN_KEYS = frozenset(
    {
        "tag",
        "source_commit",
        "outer_sha256",
        "size",
        "player_manifest_sha256",
        "client_build_id",
        "release_asset_name",
        "metadata_asset_name",
    }
)
_SIDECAR_KEYS = frozenset(
    {
        "schema",
        "version",
        "git_tag",
        "source_commit",
        "outer_sha256",
        "outer_size",
        "player_manifest_sha256",
        "client_build_id",
    }
)


class PlayerAssetsManifestError(ValueError):
    """Raised when a registry or sidecar violates its exact contract."""


@dataclass(frozen=True, slots=True)
class PlayerAssetPin:
    """Immutable registry identity for one player-bundle release."""

    version: str
    tag: str
    source_commit: str
    outer_sha256: str
    size: int
    player_manifest_sha256: str
    client_build_id: str
    release_asset_name: str
    metadata_asset_name: str


@dataclass(frozen=True, slots=True)
class PlayerBundleMetadata:
    """Validated release sidecar binding the archive to its player tree."""

    schema: int
    version: str
    git_tag: str
    source_commit: str
    outer_sha256: str
    outer_size: int
    player_manifest_sha256: str
    client_build_id: str


@dataclass(frozen=True, slots=True)
class PlayerAssetsManifest:
    """Validated immutable view of the tracked release-pin registry."""

    versions: Mapping[str, PlayerAssetPin]


def load_player_assets_manifest(path: Path) -> PlayerAssetsManifest:
    """Read a registry file without network access or ambiguous JSON keys."""
    try:
        with Path(path).open("r", encoding="ascii") as manifest_file:
            document = json.load(
                manifest_file,
                object_pairs_hook=_reject_duplicate_keys,
            )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        PlayerAssetsManifestError,
    ) as exc:
        raise PlayerAssetsManifestError("unable to read a valid player registry") from exc
    return parse_player_assets_manifest(document)


def parse_player_assets_manifest(document: object) -> PlayerAssetsManifest:
    """Validate the registry object and freeze each release pin."""
    _require_keys(document, _REGISTRY_KEYS, "registry")
    assert isinstance(document, dict)
    raw_versions = document["versions"]
    if not isinstance(raw_versions, dict):
        raise PlayerAssetsManifestError("versions must be an object")

    versions: dict[str, PlayerAssetPin] = {}
    for version, raw_pin in raw_versions.items():
        if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
            raise PlayerAssetsManifestError("registry version key is invalid")
        _require_keys(raw_pin, _PIN_KEYS, "versions." + version)
        assert isinstance(raw_pin, dict)
        pin = _parse_pin(version, raw_pin)
        versions[version] = pin
    return PlayerAssetsManifest(MappingProxyType(versions))


def parse_player_bundle_metadata(
    document: bytes | str | object,
) -> PlayerBundleMetadata:
    """Parse and strictly validate a player bundle metadata sidecar."""
    if isinstance(document, bytes):
        try:
            document = document.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PlayerAssetsManifestError("sidecar must be ASCII JSON") from exc
    if isinstance(document, str):
        try:
            encoded_document = document.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PlayerAssetsManifestError("sidecar must be ASCII JSON") from exc
        if len(encoded_document) > MAX_PLAYER_BUNDLE_METADATA_BYTES:
            raise PlayerAssetsManifestError("sidecar exceeds its size bound")
        try:
            document = json.loads(document, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, PlayerAssetsManifestError) as exc:
            raise PlayerAssetsManifestError("sidecar JSON is invalid") from exc
    return _parse_sidecar(document)


def sidecar_for_pin(pin: PlayerAssetPin) -> dict[str, object]:
    """Return the canonical exact-schema metadata object for a registry pin."""
    return {
        "schema": PLAYER_BUNDLE_METADATA_SCHEMA,
        "version": pin.version,
        "git_tag": pin.tag,
        "source_commit": pin.source_commit,
        "outer_sha256": pin.outer_sha256,
        "outer_size": pin.size,
        "player_manifest_sha256": pin.player_manifest_sha256,
        "client_build_id": pin.client_build_id,
    }


def release_asset_url(pin: PlayerAssetPin, asset_name: str) -> str:
    """Resolve one pinned release name below the fixed fork download base."""
    if (
        not isinstance(pin, PlayerAssetPin)
        or not isinstance(pin.version, str)
        or not isinstance(pin.tag, str)
        or not isinstance(asset_name, str)
        or _VERSION_RE.fullmatch(pin.version) is None
        or pin.tag != "v" + pin.version
        or _TAG_RE.fullmatch(pin.tag) is None
        or pin.release_asset_name != "neq-player-bundle-" + pin.version + ".tar.gz"
        or pin.metadata_asset_name
        != "neq-player-bundle-" + pin.version + ".metadata.json"
        or asset_name not in {pin.release_asset_name, pin.metadata_asset_name}
    ):
        raise PlayerAssetsManifestError("release asset is not pinned")
    return PLAYER_RELEASE_BASE + pin.tag + "/" + asset_name


def _parse_pin(version: str, value: dict[str, object]) -> PlayerAssetPin:
    tag = _require_string(value["tag"], "tag")
    source_commit = _require_string(value["source_commit"], "source_commit")
    outer_sha256 = _require_sha256(value["outer_sha256"], "outer_sha256")
    size = _require_positive_int(value["size"], "size")
    manifest_sha256 = _require_sha256(
        value["player_manifest_sha256"], "player_manifest_sha256"
    )
    client_build_id = _require_string(value["client_build_id"], "client_build_id")
    bundle_name = _require_string(value["release_asset_name"], "release_asset_name")
    metadata_name = _require_string(value["metadata_asset_name"], "metadata_asset_name")

    if _TAG_RE.fullmatch(tag) is None or tag != "v" + version:
        raise PlayerAssetsManifestError("registry tag does not match its version")
    if _SOURCE_COMMIT_RE.fullmatch(source_commit) is None:
        raise PlayerAssetsManifestError("source_commit must contain 40 hex digits")
    if size > MAX_PLAYER_BUNDLE_BYTES:
        raise PlayerAssetsManifestError("bundle size exceeds its download bound")
    if _BUILD_ID_RE.fullmatch(client_build_id) is None:
        raise PlayerAssetsManifestError("client_build_id is invalid")
    bundle_match = _BUNDLE_NAME_RE.fullmatch(bundle_name)
    metadata_match = _METADATA_NAME_RE.fullmatch(metadata_name)
    if (
        bundle_match is None
        or metadata_match is None
        or bundle_match.group(1) != version
        or metadata_match.group(1) != version
    ):
        raise PlayerAssetsManifestError("release asset name does not match version")

    return PlayerAssetPin(
        version=version,
        tag=tag,
        source_commit=source_commit,
        outer_sha256=outer_sha256,
        size=size,
        player_manifest_sha256=manifest_sha256,
        client_build_id=client_build_id,
        release_asset_name=bundle_name,
        metadata_asset_name=metadata_name,
    )


def _parse_sidecar(document: object) -> PlayerBundleMetadata:
    _require_keys(document, _SIDECAR_KEYS, "sidecar")
    assert isinstance(document, dict)
    schema = document["schema"]
    if type(schema) is not int or schema != PLAYER_BUNDLE_METADATA_SCHEMA:
        raise PlayerAssetsManifestError("sidecar schema is unsupported")
    version = _require_string(document["version"], "version")
    tag = _require_string(document["git_tag"], "git_tag")
    source_commit = _require_string(document["source_commit"], "source_commit")
    outer_sha256 = _require_sha256(document["outer_sha256"], "outer_sha256")
    outer_size = _require_positive_int(document["outer_size"], "outer_size")
    manifest_sha256 = _require_sha256(
        document["player_manifest_sha256"], "player_manifest_sha256"
    )
    client_build_id = _require_string(document["client_build_id"], "client_build_id")

    if _VERSION_RE.fullmatch(version) is None or tag != "v" + version:
        raise PlayerAssetsManifestError("sidecar version and tag do not match")
    if _TAG_RE.fullmatch(tag) is None:
        raise PlayerAssetsManifestError("sidecar tag is invalid")
    if _SOURCE_COMMIT_RE.fullmatch(source_commit) is None:
        raise PlayerAssetsManifestError("sidecar source_commit is invalid")
    if outer_size > MAX_PLAYER_BUNDLE_BYTES:
        raise PlayerAssetsManifestError("sidecar bundle size exceeds its bound")
    if _BUILD_ID_RE.fullmatch(client_build_id) is None:
        raise PlayerAssetsManifestError("sidecar client_build_id is invalid")

    return PlayerBundleMetadata(
        schema=schema,
        version=version,
        git_tag=tag,
        source_commit=source_commit,
        outer_sha256=outer_sha256,
        outer_size=outer_size,
        player_manifest_sha256=manifest_sha256,
        client_build_id=client_build_id,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PlayerAssetsManifestError("duplicate JSON object key")
        result[key] = value
    return result


def _require_keys(value: object, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise PlayerAssetsManifestError(
            "%s has missing, extra, or invalid keys" % label
        )


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise PlayerAssetsManifestError("%s must be a string" % label)
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise PlayerAssetsManifestError("%s must be a positive integer" % label)
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PlayerAssetsManifestError(
            "%s must be 64 lowercase hexadecimal characters" % label
        )
    return value
