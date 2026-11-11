# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Strict, offline reader for the pinned OpenTunnel source manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

UPSTREAM_TAG = "v0.6.2"
UPSTREAM_COMMIT = "1ad859e17924ec3f6741cbc4cdb54ce381c9007c"
UPSTREAM_RELEASE_URL = (
    "https://github.com/anomalyco/opentunnel/releases/download/" + UPSTREAM_TAG
)
MIT_TEXT_POINTER = "https://opensource.org/license/mit/"
MIT_NOTICE = "OpenTunnel v0.6.2 is distributed under the MIT License."

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ASSET_NAME_RE = re.compile(r"opentunnel-(?:darwin|linux)-arm64\.tar\.gz\Z")
_ASSET_STEM_RE = re.compile(r"opentunnel-(?:darwin|linux)-arm64\Z")
_SUPPORTED_ASSETS = {
    ("darwin", "arm64"): (
        "opentunnel-darwin-arm64.tar.gz",
        "opentunnel-darwin-arm64",
    ),
    ("linux", "arm64"): (
        "opentunnel-linux-arm64.tar.gz",
        "opentunnel-linux-arm64",
    ),
}
_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "upstream_tag",
        "upstream_commit",
        "release_url",
        "sha256sums_provenance",
        "license_notice",
        "platforms",
    }
)
_CHECKSUM_PROVENANCE_KEYS = frozenset({"url", "sha256", "size_bytes", "source"})
_LICENSE_NOTICE_KEYS = frozenset({"spdx_id", "notice", "text_pointer"})
_PLATFORM_KEYS = frozenset(
    {
        "os",
        "arch",
        "asset_name",
        "asset_stem",
        "archive_size_bytes",
        "archive_sha256",
        "executable_size_bytes",
        "sha256",
        "runtime_path",
    }
)


class ManifestError(ValueError):
    """Raised when a pinned source manifest is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class ChecksumProvenance:
    """Identity and local provenance for the release's SHA256SUMS file."""

    url: str
    sha256: str
    size_bytes: int
    source: str


@dataclass(frozen=True, slots=True)
class LicenseNotice:
    """Machine-readable MIT notice and pointer to the license text."""

    spdx_id: str
    notice: str
    text_pointer: str


@dataclass(frozen=True, slots=True)
class PlatformPin:
    """Archive and extracted-executable pins for one approved platform."""

    os: str
    arch: str
    asset_name: str
    asset_stem: str
    archive_size_bytes: int
    archive_sha256: str
    executable_size_bytes: int
    sha256: str
    runtime_path: str

    @property
    def platform_key(self) -> str:
        """Return the companion resolver's normalized platform key."""
        return self.os + "-" + self.arch


@dataclass(frozen=True, slots=True)
class PinnedManifest:
    """Validated immutable view of the committed source manifest."""

    version: str
    upstream_tag: str
    upstream_commit: str
    release_url: str
    sha256sums_provenance: ChecksumProvenance
    license_notice: LicenseNotice
    platforms: Mapping[str, PlatformPin]


def load_pinned_manifest(path: Path) -> PinnedManifest:
    """Load a JSON manifest and reject every unsupported or ambiguous field.

    This reader performs no network access. Duplicate keys at any JSON object
    level, additional schema fields, unsupported platform pairs, and pin/path
    inconsistencies fail closed with :class:`ManifestError`.
    """
    try:
        with Path(path).open("r", encoding="utf-8") as manifest_file:
            document = json.load(
                manifest_file,
                object_pairs_hook=_reject_duplicate_keys,
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ManifestError) as exc:
        raise ManifestError("unable to read a valid pinned manifest") from exc

    return _parse_manifest(document)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_manifest(document: object) -> PinnedManifest:
    _require_keys(document, _TOP_LEVEL_KEYS, "manifest")
    assert isinstance(document, dict)

    version = _require_string(document["version"], "version")
    upstream_tag = _require_string(document["upstream_tag"], "upstream_tag")
    upstream_commit = _require_string(
        document["upstream_commit"], "upstream_commit"
    )
    release_url = _require_string(document["release_url"], "release_url")

    if version != "0.6.2":
        raise ManifestError("unsupported companion version")
    if upstream_tag != UPSTREAM_TAG or upstream_commit != UPSTREAM_COMMIT:
        raise ManifestError("upstream release identity does not match the pin")
    _validate_release_url(release_url)

    checksum_provenance = _parse_checksum_provenance(
        document["sha256sums_provenance"], release_url
    )
    license_notice = _parse_license_notice(document["license_notice"])
    platforms = _parse_platforms(document["platforms"])

    return PinnedManifest(
        version=version,
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
        release_url=release_url,
        sha256sums_provenance=checksum_provenance,
        license_notice=license_notice,
        platforms=MappingProxyType(platforms),
    )


def _parse_checksum_provenance(
    value: object, release_url: str
) -> ChecksumProvenance:
    _require_keys(value, _CHECKSUM_PROVENANCE_KEYS, "sha256sums_provenance")
    assert isinstance(value, dict)

    url = _require_string(value["url"], "sha256sums_provenance.url")
    digest = _require_sha256(value["sha256"], "sha256sums_provenance.sha256")
    size_bytes = _require_positive_int(
        value["size_bytes"], "sha256sums_provenance.size_bytes"
    )
    source = _require_string(value["source"], "sha256sums_provenance.source")
    if not source.strip():
        raise ManifestError("SHA256SUMS provenance source must not be empty")
    if url != release_url + "/SHA256SUMS":
        raise ManifestError("SHA256SUMS URL does not match the pinned release")

    return ChecksumProvenance(
        url=url,
        sha256=digest,
        size_bytes=size_bytes,
        source=source,
    )


def _parse_license_notice(value: object) -> LicenseNotice:
    _require_keys(value, _LICENSE_NOTICE_KEYS, "license_notice")
    assert isinstance(value, dict)

    spdx_id = _require_string(value["spdx_id"], "license_notice.spdx_id")
    notice = _require_string(value["notice"], "license_notice.notice")
    text_pointer = _require_string(
        value["text_pointer"], "license_notice.text_pointer"
    )
    if (
        spdx_id != "MIT"
        or notice != MIT_NOTICE
        or text_pointer != MIT_TEXT_POINTER
    ):
        raise ManifestError("license notice must identify MIT and its text pointer")
    return LicenseNotice(
        spdx_id=spdx_id,
        notice=notice,
        text_pointer=text_pointer,
    )


def _parse_platforms(value: object) -> dict[str, PlatformPin]:
    if not isinstance(value, list) or len(value) != len(_SUPPORTED_ASSETS):
        raise ManifestError("platforms must contain exactly the two approved pairs")

    platforms: dict[str, PlatformPin] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for index, raw_entry in enumerate(value):
        _require_keys(raw_entry, _PLATFORM_KEYS, "platforms[%d]" % index)
        assert isinstance(raw_entry, dict)

        os_name = _require_string(raw_entry["os"], "platforms.os")
        arch = _require_string(raw_entry["arch"], "platforms.arch")
        pair = (os_name, arch)
        expected_assets = _SUPPORTED_ASSETS.get(pair)
        if expected_assets is None:
            raise ManifestError("unsupported platform pair")
        if pair in seen_pairs:
            raise ManifestError("duplicate platform pair")
        seen_pairs.add(pair)

        asset_name = _require_string(raw_entry["asset_name"], "platforms.asset_name")
        asset_stem = _require_string(raw_entry["asset_stem"], "platforms.asset_stem")
        if _ASSET_NAME_RE.fullmatch(asset_name) is None:
            raise ManifestError("asset name is not allowlisted")
        if _ASSET_STEM_RE.fullmatch(asset_stem) is None:
            raise ManifestError("asset stem is not allowlisted")
        if (asset_name, asset_stem) != expected_assets:
            raise ManifestError("asset name or stem does not match its platform")

        archive_size_bytes = _require_positive_int(
            raw_entry["archive_size_bytes"], "platforms.archive_size_bytes"
        )
        archive_sha256 = _require_sha256(
            raw_entry["archive_sha256"], "platforms.archive_sha256"
        )
        executable_size_bytes = _require_positive_int(
            raw_entry["executable_size_bytes"], "platforms.executable_size_bytes"
        )
        executable_sha256 = _require_sha256(raw_entry["sha256"], "platforms.sha256")
        runtime_path = _require_string(raw_entry["runtime_path"], "platforms.runtime_path")
        expected_runtime_path = (
            "runtime/opentunnel/v0.6.2/" + asset_stem + "/opentunnel"
        )
        if runtime_path != expected_runtime_path:
            raise ManifestError("runtime path does not match its platform asset stem")

        platform_key = os_name + "-" + arch
        platforms[platform_key] = PlatformPin(
            os=os_name,
            arch=arch,
            asset_name=asset_name,
            asset_stem=asset_stem,
            archive_size_bytes=archive_size_bytes,
            archive_sha256=archive_sha256,
            executable_size_bytes=executable_size_bytes,
            sha256=executable_sha256,
            runtime_path=runtime_path,
        )

    if seen_pairs != set(_SUPPORTED_ASSETS):
        raise ManifestError("platforms must contain both approved pairs")
    return platforms


def _validate_release_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ManifestError("release URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.path != "/anomalyco/opentunnel/releases/download/" + UPSTREAM_TAG
        or parsed.query
        or parsed.fragment
        or value != UPSTREAM_RELEASE_URL
    ):
        raise ManifestError("release URL must be the pinned GitHub tag download base")


def _require_keys(value: object, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ManifestError("%s has missing, extra, or invalid keys" % label)


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ManifestError("%s must be a string" % label)
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ManifestError("%s must be a positive integer" % label)
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ManifestError("%s must be 64 lowercase hexadecimal characters" % label)
    return value
