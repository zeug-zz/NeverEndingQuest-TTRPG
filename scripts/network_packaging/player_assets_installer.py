# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Explicit, pinned, transactional installer for prebuilt player assets."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from scripts.network_packaging import opentunnel_installer
from scripts.network_packaging.player_assets_manifest import (
    MAX_PLAYER_BUNDLE_BYTES,
    MAX_PLAYER_BUNDLE_METADATA_BYTES,
    PLAYER_RELEASE_BASE,
    PlayerAssetPin,
    PlayerAssetsManifest,
    PlayerAssetsManifestError,
    PlayerBundleMetadata,
    load_player_assets_manifest,
    parse_player_assets_manifest,
    parse_player_bundle_metadata,
    release_asset_url,
    sidecar_for_pin,
)
from web.extensions.player.assets import (
    MAX_MANIFEST_BYTES,
    MAX_PLAYER_ASSET_BYTES,
    MAX_PLAYER_ASSET_COUNT,
    MAX_PLAYER_SHELL_BYTES,
    PlayerClientAssetsError,
    load_player_client_assets,
)

MAX_DOWNLOAD_TIMEOUT_SECONDS = opentunnel_installer.MAX_DOWNLOAD_TIMEOUT_SECONDS
MAX_ARCHIVE_MEMBERS = MAX_PLAYER_ASSET_COUNT + 2
MAX_EXTRACTED_BYTES = (
    MAX_MANIFEST_BYTES + MAX_PLAYER_SHELL_BYTES + MAX_PLAYER_ASSET_BYTES
)
DOWNLOAD_CHUNK_BYTES = opentunnel_installer.DOWNLOAD_CHUNK_BYTES
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")

InstallReason = Literal[
    "installed",
    "already_installed",
    "invalid_version",
    "unknown_version",
    "download_failed",
    "metadata_mismatch",
    "checksum_mismatch",
    "unsafe_archive",
    "asset_mismatch",
    "install_failed",
    "rolled_back",
]


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Bounded result that never exposes raw errors, paths, or URLs."""

    reason: InstallReason
    version: str | None = None


@dataclass(frozen=True, slots=True)
class _TreeIdentity:
    manifest_sha256: str
    client_build_id: str


class _InstallFailure(Exception):
    def __init__(self, reason: InstallReason) -> None:
        super().__init__(reason)
        self.reason = reason


def install_player_assets(
    install_root: Path,
    version: str,
    registry: PlayerAssetsManifest,
    *,
    downloader: Callable[..., object],
) -> InstallResult:
    """Download, verify, and atomically activate one registry-pinned bundle."""
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        return InstallResult("invalid_version", None)
    if not isinstance(registry, PlayerAssetsManifest):
        return InstallResult("install_failed", version)
    pin = registry.versions.get(version)
    if pin is None:
        return InstallResult("unknown_version", version)
    if not _valid_pin(pin, version) or not callable(downloader):
        return InstallResult("install_failed", version)

    try:
        root = _validate_install_root(install_root)
        frontend = _ensure_directory_chain(root, ("web", "frontend"))
    except (OSError, RuntimeError, TypeError, ValueError):
        return InstallResult("install_failed", version)

    target_dir = frontend / "dist"
    previous_dir = frontend / "dist.previous"
    lock_path = frontend / ".player-assets-install.lock"
    lock_descriptor: int | None = None
    lock_identity: tuple[int, int] | None = None
    stage_dir: Path | None = None
    transaction_started = False
    previous_retained = False
    old_identity: _TreeIdentity | None = None
    prior_backup_identity: _TreeIdentity | None = None
    try:
        lock_descriptor, lock_identity = _acquire_install_lock(lock_path)
        old_identity = _inspect_tree_or_missing(target_dir)
        if old_identity is not None and _matches_pin(old_identity, pin):
            return InstallResult("already_installed", version)
        if _path_exists(previous_dir):
            prior_backup_identity = _inspect_tree_or_missing(previous_dir)
            if prior_backup_identity is None:
                raise _InstallFailure("install_failed")
            if old_identity is None:
                # Recover an interrupted prior swap before attempting another
                # install so the last verified bundle remains at the live path.
                os.replace(previous_dir, target_dir)
                old_identity = _inspect_tree_or_missing(target_dir)
                if old_identity != prior_backup_identity:
                    raise _InstallFailure("install_failed")
                prior_backup_identity = None
                if old_identity is not None and _matches_pin(old_identity, pin):
                    return InstallResult("already_installed", version)

        staging_root = frontend / ".player-assets-staging"
        _ensure_private_staging_root(staging_root)
        stage_dir = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        _verify_private_directory(stage_dir)

        metadata_part = stage_dir / (pin.metadata_asset_name + ".part")
        archive_part = stage_dir / (pin.release_asset_name + ".part")
        _download_with_bounds(
            downloader,
            release_asset_url(pin, pin.metadata_asset_name),
            metadata_part,
            MAX_PLAYER_BUNDLE_METADATA_BYTES,
        )
        try:
            metadata_bytes = _read_downloaded_file(
                metadata_part, MAX_PLAYER_BUNDLE_METADATA_BYTES
            )
            metadata = parse_player_bundle_metadata(metadata_bytes)
        except (OSError, PlayerAssetsManifestError, TypeError, ValueError):
            raise _InstallFailure("metadata_mismatch") from None
        if not _metadata_matches_pin(metadata, pin):
            raise _InstallFailure("metadata_mismatch")

        _download_with_bounds(
            downloader,
            release_asset_url(pin, pin.release_asset_name),
            archive_part,
            min(pin.size, MAX_PLAYER_BUNDLE_BYTES),
        )
        try:
            archive_size = _validate_downloaded_file(
                archive_part, MAX_PLAYER_BUNDLE_BYTES
            )
            archive_digest = _sha256_file(archive_part, MAX_PLAYER_BUNDLE_BYTES)
        except (OSError, ValueError):
            raise _InstallFailure("download_failed") from None
        if (
            archive_size != pin.size
            or archive_size != metadata.outer_size
            or not hmac.compare_digest(archive_digest, pin.outer_sha256)
            or not hmac.compare_digest(archive_digest, metadata.outer_sha256)
        ):
            raise _InstallFailure("checksum_mismatch")

        candidate_dir = stage_dir / "candidate"
        try:
            _safe_extract_archive(archive_part, candidate_dir)
        except (OSError, EOFError, tarfile.TarError, TypeError, ValueError):
            raise _InstallFailure("unsafe_archive") from None
        try:
            candidate_identity = _inspect_tree_or_missing(candidate_dir)
        except (OSError, PlayerClientAssetsError, TypeError, ValueError):
            raise _InstallFailure("asset_mismatch") from None
        if (
            candidate_identity is None
            or not _matches_pin(candidate_identity, pin)
        ):
            raise _InstallFailure("asset_mismatch")

        # Revalidate the old bundle immediately before activation so a changed
        # tree cannot be mistaken for the rollback candidate.
        current_identity = _inspect_tree_or_missing(target_dir)
        if current_identity != old_identity:
            raise _InstallFailure("install_failed")

        if old_identity is not None:
            if prior_backup_identity is not None:
                # Retain only the immediately previous verified bundle. The
                # current dist remains active until this older backup is gone.
                if _inspect_tree_or_missing(previous_dir) != prior_backup_identity:
                    raise _InstallFailure("install_failed")
                _remove_real_directory(previous_dir, frontend)
                prior_backup_identity = None
            _recheck_frontend_directory(frontend, root)
            try:
                os.replace(target_dir, previous_dir)
            finally:
                if _path_exists(previous_dir) and not _path_exists(target_dir):
                    previous_retained = True
                    transaction_started = True
        try:
            os.replace(candidate_dir, target_dir)
        finally:
            if _path_exists(target_dir) and not _path_exists(candidate_dir):
                transaction_started = True

        promoted_identity = _inspect_tree_or_missing(target_dir)
        if promoted_identity is None or not _matches_pin(promoted_identity, pin):
            raise _InstallFailure("asset_mismatch")
        if previous_retained and not _path_exists(previous_dir):
            raise _InstallFailure("install_failed")
        return InstallResult("installed", version)
    except _InstallFailure as exc:
        if transaction_started:
            rollback_ok = _rollback_install(
                frontend,
                target_dir,
                previous_dir,
                old_identity,
                previous_retained,
            )
            return InstallResult("rolled_back" if rollback_ok else "install_failed", version)
        return InstallResult(exc.reason, version)
    except KeyboardInterrupt:
        if transaction_started:
            _rollback_install(
                frontend,
                target_dir,
                previous_dir,
                old_identity,
                previous_retained,
            )
        raise
    except Exception:
        if transaction_started:
            rollback_ok = _rollback_install(
                frontend,
                target_dir,
                previous_dir,
                old_identity,
                previous_retained,
            )
            return InstallResult("rolled_back" if rollback_ok else "install_failed", version)
        return InstallResult("install_failed", version)
    finally:
        if stage_dir is not None:
            try:
                _cleanup_staging(stage_dir)
            except OSError:
                pass
        if lock_descriptor is not None and lock_identity is not None:
            _release_install_lock(lock_path, lock_descriptor, lock_identity)


def download_player_release_asset(
    url: str,
    destination: Path,
    *,
    release_url: str,
    asset_names: frozenset[str],
    timeout_seconds: int,
    max_bytes: int,
) -> None:
    """Use OpenTunnel's shared HTTPS, redirect, timeout, and proxy guards."""
    opentunnel_installer.download_pinned_github_release_asset(
        url,
        destination,
        release_url=release_url,
        asset_names=asset_names,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )


def _metadata_matches_pin(metadata: PlayerBundleMetadata, pin: PlayerAssetPin) -> bool:
    actual = {
        "schema": metadata.schema,
        "version": metadata.version,
        "git_tag": metadata.git_tag,
        "source_commit": metadata.source_commit,
        "outer_sha256": metadata.outer_sha256,
        "outer_size": metadata.outer_size,
        "player_manifest_sha256": metadata.player_manifest_sha256,
        "client_build_id": metadata.client_build_id,
    }
    return actual == sidecar_for_pin(pin)


def _valid_pin(pin: object, version: str) -> bool:
    if not isinstance(pin, PlayerAssetPin):
        return False
    try:
        parsed = parse_player_assets_manifest(
            {
                "versions": {
                    version: {
                        "tag": pin.tag,
                        "source_commit": pin.source_commit,
                        "outer_sha256": pin.outer_sha256,
                        "size": pin.size,
                        "player_manifest_sha256": pin.player_manifest_sha256,
                        "client_build_id": pin.client_build_id,
                        "release_asset_name": pin.release_asset_name,
                        "metadata_asset_name": pin.metadata_asset_name,
                    }
                }
            }
        )
    except (TypeError, ValueError):
        return False
    return parsed.versions.get(version) == pin


def _validate_install_root(install_root: Path) -> Path:
    path = Path(install_root).expanduser()
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("install root must be a real directory")
    root = path.resolve(strict=True)
    if _has_venv_component(root):
        raise ValueError("install root is inside a virtual environment")
    return root


def _ensure_directory_chain(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o755)
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("install directory is not a real directory")
        current.resolve(strict=True).relative_to(root)
    return current


def _acquire_install_lock(path: Path) -> tuple[int, tuple[int, int]]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    metadata = os.fstat(descriptor)
    return descriptor, (metadata.st_dev, metadata.st_ino)


def _release_install_lock(
    path: Path,
    descriptor: int,
    expected_identity: tuple[int, int],
) -> None:
    try:
        file_metadata = os.fstat(descriptor)
        path_metadata = Path(path).lstat()
        if (
            (file_metadata.st_dev, file_metadata.st_ino) == expected_identity
            and (path_metadata.st_dev, path_metadata.st_ino) == expected_identity
            and stat.S_ISREG(path_metadata.st_mode)
        ):
            Path(path).unlink()
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _ensure_private_staging_root(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700)
    _verify_private_directory(path)


def _verify_private_directory(path: Path) -> None:
    metadata = Path(path).lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("staging directory is not private and owner-controlled")


def _download_with_bounds(
    downloader: Callable[..., object],
    url: str,
    destination: Path,
    max_bytes: int,
) -> None:
    try:
        downloader(
            url,
            destination,
            timeout_seconds=MAX_DOWNLOAD_TIMEOUT_SECONDS,
            max_bytes=max_bytes,
        )
        _validate_downloaded_file(destination, max_bytes)
        destination.chmod(0o600)
    except Exception:
        raise _InstallFailure("download_failed") from None


def _read_downloaded_file(path: Path, max_bytes: int) -> bytes:
    metadata = Path(path).lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("download output is not a regular file")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise ValueError("download output exceeds its size bound")
    with Path(path).open("rb") as stream:
        body = stream.read(max_bytes + 1)
    if len(body) != metadata.st_size or len(body) > max_bytes:
        raise ValueError("download output changed while reading")
    return body


def _validate_downloaded_file(path: Path, max_bytes: int) -> int:
    metadata = Path(path).lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("download output is not a regular file")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise ValueError("download output exceeds its size bound")
    return metadata.st_size


def _safe_extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(mode=0o755, parents=False, exist_ok=False)
    seen_names: set[str] = set()
    total_bytes = 0
    member_count = 0
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive:
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBERS:
                raise ValueError("archive member count exceeds its cap")
            name = member.name
            path = PurePosixPath(name) if isinstance(name, str) else PurePosixPath("")
            if (
                not name
                or "\\" in name
                or path.is_absolute()
                or path.parts != (name,)
                or name in {".", ".."}
                or re.match(r"^[A-Za-z]:", name) is not None
                or name in seen_names
            ):
                raise ValueError("archive contains an unsafe or duplicate path")
            if (
                member.issym()
                or member.islnk()
                or member.isdev()
                or member.isdir()
                or not member.isfile()
                or getattr(member, "sparse", None)
                or any(key.startswith("GNU.sparse") for key in member.pax_headers)
            ):
                raise ValueError("archive contains a link or special file")
            if member.size < 0:
                raise ValueError("archive member size is invalid")
            total_bytes += member.size
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise ValueError("archive expanded size exceeds its cap")
            if member.size > max(MAX_PLAYER_ASSET_BYTES, MAX_PLAYER_SHELL_BYTES):
                raise ValueError("archive member exceeds its file-size cap")
            seen_names.add(name)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archive member could not be read")
            output_path = destination / name
            file_descriptor = os.open(
                output_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            written = 0
            try:
                with source, os.fdopen(file_descriptor, "wb") as output:
                    while True:
                        chunk = source.read(min(DOWNLOAD_CHUNK_BYTES, member.size - written + 1))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.size or written > MAX_EXTRACTED_BYTES:
                            raise ValueError("archive member exceeded its declared size")
                        output.write(chunk)
                if written != member.size:
                    raise ValueError("archive member size did not match its header")
            except BaseException:
                output_path.unlink(missing_ok=True)
                raise
            output_path.chmod(0o644)
    if not seen_names:
        raise ValueError("archive is empty")


def _inspect_tree_or_missing(path: Path) -> _TreeIdentity | None:
    try:
        root_metadata = Path(path).lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("player asset tree is not a real directory")
    tree_root = Path(path).resolve(strict=True)
    verified = load_player_client_assets(tree_root)
    expected_names = {
        "index.html",
        "player-manifest.json",
        *verified.assets.keys(),
    }
    actual_names: set[str] = set()
    for entry in tree_root.iterdir():
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("player asset tree has a link or non-regular entry")
        actual_names.add(entry.name)
    if actual_names != expected_names:
        raise ValueError("player asset tree has missing or unexpected files")
    manifest_bytes = _read_regular_file(
        tree_root / "player-manifest.json", MAX_MANIFEST_BYTES
    )
    return _TreeIdentity(
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        client_build_id=verified.client_build_id,
    )


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 0:
            raise ValueError("player asset is not a regular file")
        if metadata.st_size > max_bytes:
            raise ValueError("player asset exceeds its size bound")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            body = source.read(max_bytes + 1)
        if len(body) != metadata.st_size or len(body) > max_bytes:
            raise ValueError("player asset changed while reading")
        return body
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _matches_pin(identity: _TreeIdentity, pin: PlayerAssetPin) -> bool:
    return (
        hmac.compare_digest(identity.manifest_sha256, pin.player_manifest_sha256)
        and hmac.compare_digest(identity.client_build_id, pin.client_build_id)
    )


def _rollback_install(
    frontend: Path,
    target_dir: Path,
    previous_dir: Path,
    old_identity: _TreeIdentity | None,
    previous_retained: bool,
) -> bool:
    try:
        if _path_exists(target_dir):
            _remove_real_directory(target_dir, frontend)
        if not previous_retained:
            return old_identity is None
        if _path_exists(target_dir):
            return False
        os.replace(previous_dir, target_dir)
        restored_identity = _inspect_tree_or_missing(target_dir)
        return restored_identity == old_identity
    except (OSError, PlayerClientAssetsError, RuntimeError, TypeError, ValueError):
        return False


def _remove_real_directory(path: Path, expected_parent: Path) -> None:
    metadata = Path(path).lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("refusing to remove a non-directory player path")
    resolved = Path(path).resolve(strict=True)
    resolved.relative_to(expected_parent.resolve(strict=True))
    shutil.rmtree(resolved)


def _cleanup_staging(path: Path) -> None:
    metadata = Path(path).lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("staging path is unsafe")
    shutil.rmtree(path)


def _sha256_file(path: Path, max_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("file exceeds its size bound")
            digest.update(chunk)
    return digest.hexdigest()


def _path_exists(path: Path) -> bool:
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return False
    return True


def _recheck_frontend_directory(frontend: Path, root: Path) -> None:
    metadata = frontend.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("frontend directory changed before activation")
    frontend.resolve(strict=True).relative_to(root.resolve(strict=True))


def _has_venv_component(path: Path) -> bool:
    return any(part.casefold() in {".venv", "venv"} for part in path.parts)


def main(argv: list[str] | None = None) -> int:
    """Run the explicitly consented player bundle installer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    if not args.install:
        print("Player bundle installation: refused (explicit --install required)")
        return 2

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "packaging/player-assets.manifest.json"
    )
    try:
        registry = load_player_assets_manifest(manifest_path)
    except PlayerAssetsManifestError:
        print("Player bundle installation: install_failed")
        return 1
    pin = registry.versions.get(args.version)
    if pin is None:
        result = InstallResult("unknown_version", args.version)
    else:
        release_url = PLAYER_RELEASE_BASE + pin.tag
        names = frozenset({pin.release_asset_name, pin.metadata_asset_name})
        result = install_player_assets(
            Path(args.install_root),
            args.version,
            registry,
            downloader=lambda url, destination, *, timeout_seconds, max_bytes: download_player_release_asset(
                url,
                destination,
                release_url=release_url,
                asset_names=names,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
        )
    print("Player bundle installation: " + result.reason)
    return 0 if result.reason in {"installed", "already_installed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
