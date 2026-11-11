# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Build a deterministic, validated tarball from an existing player dist."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from scripts.network_packaging.player_assets_manifest import (
    MAX_PLAYER_BUNDLE_METADATA_BYTES,
    PLAYER_BUNDLE_METADATA_SCHEMA,
    PlayerAssetsManifestError,
    parse_player_bundle_metadata,
)
from web.extensions.player.assets import (
    MAX_MANIFEST_BYTES,
    MAX_PLAYER_ASSET_BYTES,
    MAX_PLAYER_SHELL_BYTES,
    PlayerClientAssetsError,
    load_player_client_assets,
)

_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
_SOURCE_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
_MAX_DIST_BYTES = (
    MAX_MANIFEST_BYTES + MAX_PLAYER_SHELL_BYTES + MAX_PLAYER_ASSET_BYTES
)


@dataclass(frozen=True, slots=True)
class BundleBuildResult:
    """Paths and immutable metadata emitted by one deterministic build."""

    tarball_path: Path
    metadata_path: Path
    metadata: Mapping[str, object]


def build_bundle(
    dist_dir: Path,
    output_dir: Path,
    *,
    git_tag: str,
    source_commit: str,
) -> BundleBuildResult:
    """Validate and package a prebuilt player tree without invoking Node."""
    if not isinstance(git_tag, str) or _TAG_RE.fullmatch(git_tag) is None:
        raise ValueError("git tag must match v<major>.<minor>.<patch>")
    if (
        not isinstance(source_commit, str)
        or _SOURCE_COMMIT_RE.fullmatch(source_commit) is None
    ):
        raise ValueError("source commit must contain 40 hexadecimal digits")

    version = git_tag[1:]
    selected_dist = Path(dist_dir)
    selected_output = Path(output_dir)
    _ensure_output_directory(selected_output)
    files = _snapshot_player_tree(selected_dist, selected_output)
    tarball = _deterministic_tarball(files)
    outer_digest = hashlib.sha256(tarball).hexdigest()
    manifest_digest = hashlib.sha256(files["player-manifest.json"]).hexdigest()
    metadata: dict[str, object] = {
        "schema": PLAYER_BUNDLE_METADATA_SCHEMA,
        "version": version,
        "git_tag": git_tag,
        "source_commit": source_commit,
        "outer_sha256": outer_digest,
        "outer_size": len(tarball),
        "player_manifest_sha256": manifest_digest,
        "client_build_id": files["__client_build_id__"].decode("ascii"),
    }
    parse_player_bundle_metadata(metadata)
    metadata_bytes = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode(
        "ascii"
    )
    if len(metadata_bytes) > MAX_PLAYER_BUNDLE_METADATA_BYTES:
        raise ValueError("generated sidecar exceeds its size bound")

    tarball_name = "neq-player-bundle-" + version + ".tar.gz"
    metadata_name = "neq-player-bundle-" + version + ".metadata.json"
    tarball_path = selected_output / tarball_name
    metadata_path = selected_output / metadata_name
    _write_output_atomically(tarball_path, tarball)
    try:
        _write_output_atomically(metadata_path, metadata_bytes)
    except OSError:
        tarball_path.unlink(missing_ok=True)
        raise

    return BundleBuildResult(
        tarball_path=tarball_path,
        metadata_path=metadata_path,
        metadata=metadata,
    )


def _snapshot_player_tree(dist_dir: Path, scratch_parent: Path) -> dict[str, bytes]:
    selected = Path(dist_dir)
    try:
        selected_metadata = selected.lstat()
    except OSError as exc:
        raise ValueError("player dist is unavailable") from exc
    if stat.S_ISLNK(selected_metadata.st_mode) or not stat.S_ISDIR(
        selected_metadata.st_mode
    ):
        raise ValueError("player dist must be a real directory")
    dist_root = selected.resolve(strict=True)

    manifest_bytes = _read_regular_file(
        dist_root / "player-manifest.json", MAX_MANIFEST_BYTES
    )
    try:
        manifest = json.loads(
            manifest_bytes.decode("ascii"), object_pairs_hook=_unique_json_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("player manifest JSON is invalid") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), dict):
        raise ValueError("player manifest does not declare its asset map")
    asset_names = set(manifest["assets"])
    if any(
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        for name in asset_names
    ):
        raise ValueError("player manifest contains an unsafe asset name")
    expected_names = {"index.html", "player-manifest.json", *asset_names}
    actual_names: set[str] = set()
    try:
        for entry in dist_root.iterdir():
            metadata = entry.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("player dist contains a link or non-regular entry")
            actual_names.add(entry.name)
    except OSError as exc:
        raise ValueError("player dist could not be read") from exc
    if actual_names != expected_names:
        raise ValueError("player dist has missing or unexpected files")

    limits = {
        "index.html": MAX_PLAYER_SHELL_BYTES,
        "player-manifest.json": MAX_MANIFEST_BYTES,
    }
    snapshot: dict[str, bytes] = {}
    total_bytes = 0
    for name in sorted(expected_names):
        body = manifest_bytes if name == "player-manifest.json" else _read_regular_file(
            dist_root / name,
            limits.get(name, MAX_PLAYER_ASSET_BYTES),
        )
        total_bytes += len(body)
        if total_bytes > _MAX_DIST_BYTES:
            raise ValueError("player dist exceeds its total size bound")
        snapshot[name] = body

    try:
        with tempfile.TemporaryDirectory(
            prefix=".player-bundle-validate-", dir=str(scratch_parent)
        ) as temporary:
            validation_root = Path(temporary)
            for name, body in snapshot.items():
                (validation_root / name).write_bytes(body)
            verified = load_player_client_assets(validation_root)
            if verified.client_build_id != manifest.get("client_build_id"):
                raise ValueError("player manifest build identity did not validate")
    except (OSError, PlayerClientAssetsError, TypeError, ValueError) as exc:
        raise ValueError("player dist failed the Python asset-loader validation") from exc

    # Keep the verified identity alongside the bytes without adding it to the archive.
    snapshot["__client_build_id__"] = verified.client_build_id.encode("ascii")
    return snapshot


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("player dist file is missing or unsafe") from exc
    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 0:
            raise ValueError("player dist entry is not a regular file")
        if metadata.st_size > max_bytes:
            raise ValueError("player dist file exceeds its size bound")
        with os.fdopen(file_descriptor, "rb") as stream:
            file_descriptor = -1
            body = stream.read(max_bytes + 1)
        if len(body) != metadata.st_size or len(body) > max_bytes:
            raise ValueError("player dist file changed while reading")
        return body
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _deterministic_tarball(files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    archive_files = {
        name: body
        for name, body in files.items()
        if name != "__client_build_id__"
    }
    if not archive_files:
        raise ValueError("player dist is empty")
    with gzip.GzipFile(
        filename="", fileobj=output, mode="wb", mtime=0, compresslevel=9
    ) as compressed:
        with tarfile.open(
            fileobj=compressed,
            mode="w",
            format=tarfile.PAX_FORMAT,
        ) as archive:
            for name in sorted(archive_files):
                body = archive_files[name]
                member = tarfile.TarInfo(name)
                member.size = len(body)
                member.mode = 0o644
                member.uid = 0
                member.gid = 0
                member.uname = ""
                member.gname = ""
                member.mtime = 0
                member.pax_headers = {}
                archive.addfile(member, io.BytesIO(body))
    return output.getvalue()


def _ensure_output_directory(path: Path) -> None:
    selected = Path(path)
    try:
        selected_metadata = selected.lstat()
    except FileNotFoundError:
        selected.mkdir(parents=True, mode=0o755)
        selected_metadata = selected.lstat()
    if stat.S_ISLNK(selected_metadata.st_mode) or not stat.S_ISDIR(
        selected_metadata.st_mode
    ):
        raise ValueError("output directory must be a real directory")


def _write_output_atomically(path: Path, contents: bytes) -> None:
    temporary_path = path.with_name(path.name + ".part")
    file_descriptor = os.open(
        temporary_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(contents)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """Build release artifacts from dist; this command never invokes npm."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="web/frontend/dist")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_bundle(
            Path(args.dist),
            Path(args.output_dir),
            git_tag=args.tag,
            source_commit=args.source_commit,
        )
    except (OSError, PlayerAssetsManifestError, PlayerClientAssetsError, TypeError, ValueError):
        print("Player bundle build: rejected")
        return 1
    print("Player bundle build: complete " + result.tarball_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
