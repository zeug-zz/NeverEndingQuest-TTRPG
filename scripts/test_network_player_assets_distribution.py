# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline security and reproducibility tests for player asset distribution."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import socket
import stat
import tarfile
import tempfile
import unittest
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from unittest import mock

from scripts.network_packaging import (
    build_player_bundle,
    opentunnel_installer,
    player_assets_installer as installer,
)
from scripts.network_packaging.player_assets_manifest import (
    MAX_PLAYER_BUNDLE_BYTES,
    PLAYER_BUNDLE_METADATA_SCHEMA,
    PLAYER_RELEASE_BASE,
    PlayerAssetPin,
    PlayerAssetsManifest,
    PlayerAssetsManifestError,
    load_player_assets_manifest,
    parse_player_assets_manifest,
    parse_player_bundle_metadata,
    release_asset_url,
    sidecar_for_pin,
)
from web.extensions.player.assets import load_player_client_assets

_SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_JS_NAME = "player-AbCdEfGh.js"
_CSS_NAME = "player-Style1234.css"
_JS_BODY = b"window.playerBundle = true;\n"
_CSS_BODY = b"body{font-family:system-ui,sans-serif}\n"
_CSRF_PLACEHOLDER = "__NEQ_PRELOGIN_CSRF_NONCE__"


class FakeDownloader:
    def __init__(
        self,
        files: dict[str, bytes | BaseException],
        *,
        oversized: set[str] | None = None,
    ) -> None:
        self.files = files
        self.calls: list[tuple[str, Path, int, int]] = []
        self.oversized = oversized or set()

    def __call__(
        self,
        url: str,
        destination: Path,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> None:
        self.calls.append((url, destination, timeout_seconds, max_bytes))
        if url not in self.files:
            raise FileNotFoundError("fake 404")
        value = self.files[url]
        if isinstance(value, BaseException):
            raise value
        body = value + b"x" if url in self.oversized else value
        destination.write_bytes(body)


class FakeRedirectResponse:
    def __init__(self, body: bytes, final_url: str) -> None:
        self._stream = io.BytesIO(body)
        self._final_url = final_url
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self) -> "FakeRedirectResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self._stream.close()

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class FakeRedirectOpener:
    def __init__(
        self,
        redirect_handler: opentunnel_installer._ReleaseRedirectHandler,
        body: bytes,
        redirect_chain: list[str],
        header_checks: list[bool],
    ) -> None:
        self.redirect_handler = redirect_handler
        self.body = body
        self.redirect_chain = redirect_chain
        self.header_checks = header_checks
        self.initial_urls: list[str] = []

    def open(
        self, request: urllib.request.Request, *, timeout: int
    ) -> FakeRedirectResponse:
        if timeout <= 0:
            raise AssertionError("expected bounded fake timeout")
        self.initial_urls.append(request.full_url)
        self.header_checks.append(
            opentunnel_installer._has_sensitive_headers(request)
        )
        current = request
        for location in self.redirect_chain:
            current = self.redirect_handler.redirect_request(
                current, None, 302, "Found", {}, location
            )
            self.header_checks.append(
                opentunnel_installer._has_sensitive_headers(current)
            )
        return FakeRedirectResponse(self.body, current.full_url)


class NetworkPlayerAssetsDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="network-player-assets-", dir="tmp"
        )
        self.addCleanup(self._temporary.cleanup)
        self.scratch = Path(self._temporary.name)
        self.dist = self.scratch / "dist-source"
        _make_player_bundle(self.dist)
        self.output = self.scratch / "build-output"
        self.build = build_player_bundle.build_bundle(
            self.dist,
            self.output,
            git_tag="v1.2.3",
            source_commit=_SOURCE_COMMIT,
        )
        self.archive = self.build.tarball_path.read_bytes()
        self.metadata_bytes = self.build.metadata_path.read_bytes()
        self.pin = _pin_from_metadata(self.build.metadata)
        self.registry = _registry(self.pin)
        self.bundle_url = release_asset_url(self.pin, self.pin.release_asset_name)
        self.metadata_url = release_asset_url(self.pin, self.pin.metadata_asset_name)
        self._network_guards = [
            mock.patch.object(
                socket,
                "socket",
                side_effect=AssertionError("player asset tests must not open sockets"),
            ),
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("player asset tests must not use urlopen"),
            ),
            mock.patch.object(
                urllib.request.OpenerDirector,
                "open",
                side_effect=AssertionError("player asset tests must not download"),
            ),
        ]
        for guard in self._network_guards:
            guard.start()
            self.addCleanup(guard.stop)

    def _root(self, name: str = "install") -> Path:
        root = self.scratch / name
        root.mkdir()
        return root

    def _files(
        self,
        *,
        archive: bytes | None = None,
        metadata: bytes | None = None,
        include_metadata: bool = True,
        include_archive: bool = True,
    ) -> dict[str, bytes | BaseException]:
        result: dict[str, bytes | BaseException] = {}
        if include_metadata:
            result[self.metadata_url] = (
                self.metadata_bytes if metadata is None else metadata
            )
        if include_archive:
            result[self.bundle_url] = self.archive if archive is None else archive
        return result

    def _install(
        self,
        root: Path,
        *,
        registry: PlayerAssetsManifest | None = None,
        files: dict[str, bytes | BaseException] | None = None,
        downloader: FakeDownloader | None = None,
        version: str = "1.2.3",
    ) -> tuple[installer.InstallResult, FakeDownloader]:
        selected_downloader = downloader or FakeDownloader(
            self._files() if files is None else files
        )
        result = installer.install_player_assets(
            root,
            version,
            self.registry if registry is None else registry,
            downloader=selected_downloader,
        )
        return result, selected_downloader

    def _new_release(
        self,
        version: str,
        *,
        js_body: bytes,
    ) -> tuple[PlayerAssetPin, PlayerAssetsManifest, dict[str, bytes]]:
        dist = self.scratch / ("dist-" + version)
        _make_player_bundle(dist, js_body=js_body)
        output = self.scratch / ("output-" + version)
        build = build_player_bundle.build_bundle(
            dist,
            output,
            git_tag="v" + version,
            source_commit=(version.replace(".", "") * 14)[:40],
        )
        pin = _pin_from_metadata(build.metadata)
        files = {
            release_asset_url(pin, pin.metadata_asset_name): build.metadata_path.read_bytes(),
            release_asset_url(pin, pin.release_asset_name): build.tarball_path.read_bytes(),
        }
        return pin, _registry(pin), files

    def _assert_staging_empty(self, root: Path) -> None:
        staging = root / "web/frontend/.player-assets-staging"
        if staging.exists():
            self.assertEqual(list(staging.iterdir()), [])
        self.assertEqual(list(root.rglob("*.part")), [])
        self.assertFalse((root / "web/frontend/.player-assets-install.lock").exists())

    def test_builder_is_reproducible_and_metadata_binds_release_identity(self) -> None:
        first_tar = self.build.tarball_path.read_bytes()
        first_metadata = self.build.metadata_path.read_bytes()
        second = build_player_bundle.build_bundle(
            self.dist,
            self.output,
            git_tag="v1.2.3",
            source_commit=_SOURCE_COMMIT,
        )
        self.assertEqual(second.tarball_path.read_bytes(), first_tar)
        self.assertEqual(second.metadata_path.read_bytes(), first_metadata)

        metadata = json.loads(first_metadata)
        self.assertEqual(
            set(metadata),
            {
                "schema",
                "version",
                "git_tag",
                "source_commit",
                "outer_sha256",
                "outer_size",
                "player_manifest_sha256",
                "client_build_id",
            },
        )
        self.assertNotIn("built_at", metadata)
        self.assertEqual(metadata["schema"], PLAYER_BUNDLE_METADATA_SCHEMA)
        self.assertEqual(metadata["version"], "1.2.3")
        self.assertEqual(metadata["git_tag"], "v1.2.3")
        self.assertEqual(metadata["source_commit"], _SOURCE_COMMIT)
        self.assertEqual(metadata["outer_sha256"], hashlib.sha256(first_tar).hexdigest())
        self.assertEqual(metadata["outer_size"], len(first_tar))
        self.assertEqual(
            metadata["player_manifest_sha256"],
            hashlib.sha256((self.dist / "player-manifest.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(metadata["client_build_id"], load_player_client_assets(self.dist).client_build_id)
        self.assertEqual(
            second.tarball_path.name,
            "neq-player-bundle-1.2.3.tar.gz",
        )
        self.assertEqual(
            second.metadata_path.name,
            "neq-player-bundle-1.2.3.metadata.json",
        )
        with tarfile.open(fileobj=io.BytesIO(first_tar), mode="r:gz") as archive:
            members = archive.getmembers()
        self.assertEqual([member.name for member in members], sorted(member.name for member in members))
        for member in members:
            with self.subTest(member=member.name):
                self.assertEqual(member.mtime, 0)
                self.assertEqual(member.uid, 0)
                self.assertEqual(member.gid, 0)
                self.assertEqual(member.mode, 0o644)

    def test_builder_rejects_invalid_tag_commit_modified_missing_and_extra_inputs(self) -> None:
        for tag, commit in (
            ("1.2.3", _SOURCE_COMMIT),
            ("v1.2", _SOURCE_COMMIT),
            ("v1.2.3", "a" * 39),
            ("v1.2.3", "g" * 40),
        ):
            with self.subTest(tag=tag, commit=commit):
                with self.assertRaises(ValueError):
                    build_player_bundle.build_bundle(
                        self.dist,
                        self.scratch / "bad-output",
                        git_tag=tag,
                        source_commit=commit,
                    )

        modified = self.scratch / "modified-dist"
        _make_player_bundle(modified)
        (modified / _JS_NAME).write_bytes(b"changed asset")
        with self.assertRaises(ValueError):
            build_player_bundle.build_bundle(
                modified,
                self.scratch / "modified-output",
                git_tag="v1.2.3",
                source_commit=_SOURCE_COMMIT,
            )

        missing = self.scratch / "missing-dist"
        _make_player_bundle(missing)
        (missing / _CSS_NAME).unlink()
        with self.assertRaises(ValueError):
            build_player_bundle.build_bundle(
                missing,
                self.scratch / "missing-output",
                git_tag="v1.2.3",
                source_commit=_SOURCE_COMMIT,
            )

        extra = self.scratch / "extra-dist"
        _make_player_bundle(extra)
        (extra / "unexpected.txt").write_bytes(b"unexpected")
        with self.assertRaises(ValueError):
            build_player_bundle.build_bundle(
                extra,
                self.scratch / "extra-output",
                git_tag="v1.2.3",
                source_commit=_SOURCE_COMMIT,
            )

    def test_initial_registry_and_strict_registry_and_sidecar_loaders(self) -> None:
        registry_path = Path("packaging/player-assets.manifest.json")
        self.assertEqual(json.loads(registry_path.read_text(encoding="ascii")), {"versions": {}})
        self.assertEqual(load_player_assets_manifest(registry_path).versions, {})
        valid = _registry_document(self.pin)
        parsed = parse_player_assets_manifest(valid)
        self.assertEqual(parsed.versions["1.2.3"], self.pin)
        self.assertEqual(
            release_asset_url(self.pin, self.pin.release_asset_name),
            PLAYER_RELEASE_BASE + "v1.2.3/neq-player-bundle-1.2.3.tar.gz",
        )
        with self.assertRaises(PlayerAssetsManifestError):
            release_asset_url(self.pin, "../other.tar.gz")

        mutations: list[Callable[[dict[str, Any]], None]] = [
            lambda doc: doc.update({"extra": True}),
            lambda doc: doc["versions"]["1.2.3"].update({"extra": True}),
            lambda doc: doc["versions"]["1.2.3"].update({"tag": "v1.2.4"}),
            lambda doc: doc["versions"]["1.2.3"].update({"source_commit": "a" * 39}),
            lambda doc: doc["versions"]["1.2.3"].update({"outer_sha256": "A" * 64}),
            lambda doc: doc["versions"]["1.2.3"].update({"size": True}),
            lambda doc: doc["versions"]["1.2.3"].update({"client_build_id": "z" * 32}),
            lambda doc: doc["versions"]["1.2.3"].update(
                {"release_asset_name": "neq-player-bundle-1.2.3.zip"}
            ),
            lambda doc: doc["versions"].update({"v1.2.3": doc["versions"].pop("1.2.3")}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(registry=index):
                document = json.loads(json.dumps(valid))
                mutate(document)
                with self.assertRaises(PlayerAssetsManifestError):
                    parse_player_assets_manifest(document)

        with tempfile.TemporaryDirectory(dir="tmp") as temporary:
            duplicate_path = Path(temporary) / "duplicate.json"
            duplicate_path.write_text(
                '{"versions": {}, "versions": {}}', encoding="ascii"
            )
            with self.assertRaises(PlayerAssetsManifestError):
                load_player_assets_manifest(duplicate_path)

        sidecar = sidecar_for_pin(self.pin)
        self.assertEqual(parse_player_bundle_metadata(sidecar).version, "1.2.3")
        for key in ("built_at", "unexpected"):
            with self.subTest(sidecar=key):
                invalid_sidecar = dict(sidecar)
                invalid_sidecar[key] = "not allowed"
                with self.assertRaises(PlayerAssetsManifestError):
                    parse_player_bundle_metadata(invalid_sidecar)
        with self.assertRaises(PlayerAssetsManifestError):
            parse_player_bundle_metadata(
                '{"schema":1,"schema":1,"version":"1.2.3"}'
            )

    def test_install_valid_bundle_and_preserve_campaign_sentinels(self) -> None:
        root = self._root()
        sentinels = {
            root / "modules/campaign/sentinel.txt": b"campaign unchanged",
            root / "characters/hero.json": b"character unchanged",
            root / "party_tracker.json": b"party unchanged",
            root / "runtime/opentunnel/profiles/other.json": b"profile unchanged",
        }
        for path, body in sentinels.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

        result, downloader = self._install(root)

        self.assertEqual(result.reason, "installed")
        installed = root / "web/frontend/dist"
        verified = load_player_client_assets(installed)
        self.assertEqual(verified.client_build_id, self.pin.client_build_id)
        self.assertEqual(
            hashlib.sha256((installed / "player-manifest.json").read_bytes()).hexdigest(),
            self.pin.player_manifest_sha256,
        )
        for path, body in sentinels.items():
            self.assertEqual(path.read_bytes(), body)
        self.assertEqual(len(downloader.calls), 2)
        self.assertEqual(
            [call[0] for call in downloader.calls],
            [self.metadata_url, self.bundle_url],
        )
        self.assertTrue(
            all(call[2] == installer.MAX_DOWNLOAD_TIMEOUT_SECONDS for call in downloader.calls)
        )
        self.assertTrue(
            all(call[3] > 0 and call[3] <= MAX_PLAYER_BUNDLE_BYTES for call in downloader.calls)
        )
        self.assertFalse((root / "web/frontend/dist.previous").exists())
        self._assert_staging_empty(root)

    def test_sidecar_and_archive_digest_tampering_is_rejected(self) -> None:
        root = self._root("bad-sidecar")
        sidecar = json.loads(self.metadata_bytes)
        sidecar["outer_sha256"] = "0" * 64
        result, downloader = self._install(
            root,
            files=self._files(metadata=_json_bytes(sidecar)),
        )
        self.assertEqual(result.reason, "metadata_mismatch")
        self.assertEqual(len(downloader.calls), 1)
        self.assertFalse((root / "web/frontend/dist").exists())

        root = self._root("bad-outer")
        corrupt_archive = self.archive[:-1] + bytes([self.archive[-1] ^ 1])
        result, _downloader = self._install(
            root,
            files=self._files(archive=corrupt_archive),
        )
        self.assertEqual(result.reason, "checksum_mismatch")
        self.assertFalse((root / "web/frontend/dist").exists())

        update_root = self._root("bad-update-before-swap")
        first, _first_downloader = self._install(update_root)
        self.assertEqual(first.reason, "installed")
        old_tree = {
            path.name: path.read_bytes()
            for path in (update_root / "web/frontend/dist").iterdir()
        }
        new_pin, new_registry, new_files = self._new_release(
            "1.2.4", js_body=b"window.badArchive = true;\n"
        )
        new_bundle_url = release_asset_url(new_pin, new_pin.release_asset_name)
        valid_new_archive = new_files[new_bundle_url]
        assert isinstance(valid_new_archive, bytes)
        bad_archive = valid_new_archive[:-1] + bytes([valid_new_archive[-1] ^ 1])
        new_files[new_bundle_url] = bad_archive
        update, _update_downloader = self._install(
            update_root,
            registry=new_registry,
            files=new_files,
            version="1.2.4",
        )
        self.assertEqual(update.reason, "checksum_mismatch")
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in (update_root / "web/frontend/dist").iterdir()
            },
            old_tree,
        )
        self.assertFalse((update_root / "web/frontend/dist.previous").exists())

    def test_modified_missing_extra_manifest_and_build_id_cases_are_rejected(self) -> None:
        cases: list[tuple[str, bytes, PlayerAssetsManifest]] = []

        modified_files = _read_tar_files(self.archive)
        modified_files[_JS_NAME] = b"modified asset body"
        modified_archive = _tar_bytes(modified_files)
        modified_pin, _modified_metadata = _repin_archive(self.pin, modified_archive)
        cases.append(
            ("modified asset", modified_archive, _registry(modified_pin))
        )

        missing_files = _read_tar_files(self.archive)
        del missing_files[_CSS_NAME]
        missing_archive = _tar_bytes(missing_files)
        missing_pin, _missing_metadata = _repin_archive(self.pin, missing_archive)
        cases.append(("missing asset", missing_archive, _registry(missing_pin)))

        extra_files = _read_tar_files(self.archive)
        extra_files["unexpected.txt"] = b"extra"
        extra_archive = _tar_bytes(extra_files)
        extra_pin, _extra_metadata = _repin_archive(self.pin, extra_archive)
        cases.append(("extra file", extra_archive, _registry(extra_pin)))

        wrong_manifest_pin = replace(self.pin, player_manifest_sha256="0" * 64)
        cases.append(("manifest digest mismatch", self.archive, _registry(wrong_manifest_pin)))

        wrong_build_pin = replace(self.pin, client_build_id="0" * 32)
        cases.append(("wrong client build id", self.archive, _registry(wrong_build_pin)))

        for index, (label, archive, registry) in enumerate(cases):
            with self.subTest(case=label):
                pin = registry.versions["1.2.3"]
                metadata = _json_bytes(sidecar_for_pin(pin))
                root = self._root("tree-mismatch-%d" % index)
                result, _downloader = self._install(
                    root,
                    registry=registry,
                    files={
                        release_asset_url(pin, pin.metadata_asset_name): metadata,
                        release_asset_url(pin, pin.release_asset_name): archive,
                    },
                )
                self.assertIn(result.reason, {"asset_mismatch", "unsafe_archive"})
                self.assertFalse((root / "web/frontend/dist").exists())


    def test_unsafe_archive_entries_and_oversized_archive_are_rejected(self) -> None:
        unsafe_archives = {
            "parent traversal": _tar_with_entry("../escape.txt", b"escape"),
            "absolute path": _tar_with_entry("/escape.txt", b"escape"),
            "symlink": _tar_with_symlink(),
            "hardlink": _tar_with_hardlink(),
            "device": _tar_with_device(),
            "oversized member": _tar_with_entry(
                "index.html", b"x" * (8 * 1024 * 1024 + 1)
            ),
        }
        for index, (label, archive) in enumerate(unsafe_archives.items()):
            with self.subTest(case=label):
                pin, metadata = _repin_archive(self.pin, archive)
                root = self._root("unsafe-%d" % index)
                result, _downloader = self._install(
                    root,
                    registry=_registry(pin),
                    files={
                        release_asset_url(pin, pin.metadata_asset_name): metadata,
                        release_asset_url(pin, pin.release_asset_name): archive,
                    },
                )
                self.assertEqual(result.reason, "unsafe_archive")
                self.assertFalse((root / "web/frontend/dist").exists())

        root = self._root("oversized")
        downloader = FakeDownloader(self._files(), oversized={self.bundle_url})
        result, _ = self._install(root, downloader=downloader)
        self.assertEqual(result.reason, "download_failed")
        self.assertFalse((root / "web/frontend/dist").exists())
        self._assert_staging_empty(root)

    def test_missing_asset_download_and_explicit_cli_consent_fail_closed(self) -> None:
        root = self._root("missing-download")
        result, downloader = self._install(
            root,
            files=self._files(include_archive=False),
        )
        self.assertEqual(result.reason, "download_failed")
        self.assertEqual(len(downloader.calls), 2)
        self.assertFalse((root / "web/frontend/dist").exists())
        self._assert_staging_empty(root)

        cli_root = self._root("cli-no-consent")
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            result_code = installer.main(
                ["--install-root", str(cli_root), "--version", "1.2.3"]
            )
        self.assertEqual(result_code, 2)
        self.assertIn("explicit --install required", output.getvalue())
        self.assertEqual(list(cli_root.iterdir()), [])

    def test_install_is_idempotent_refuses_virtual_environments_and_is_offline(self) -> None:
        root = self._root("idempotent")
        first, _downloader = self._install(root)
        self.assertEqual(first.reason, "installed")
        dist_before = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }
        second, no_download = self._install(root, downloader=FakeDownloader({}))
        self.assertEqual(second.reason, "already_installed")
        self.assertEqual(no_download.calls, [])
        self.assertEqual(
            {path.name: path.read_bytes() for path in (root / "web/frontend/dist").iterdir()},
            dist_before,
        )

        recovered_root = self._root("interrupted-swap-recovery")
        first, _downloader = self._install(recovered_root)
        self.assertEqual(first.reason, "installed")
        os.replace(
            recovered_root / "web/frontend/dist",
            recovered_root / "web/frontend/dist.previous",
        )
        recovered, no_download = self._install(
            recovered_root, downloader=FakeDownloader({})
        )
        self.assertEqual(recovered.reason, "already_installed")
        self.assertEqual(no_download.calls, [])
        self.assertTrue((recovered_root / "web/frontend/dist").is_dir())
        self.assertFalse((recovered_root / "web/frontend/dist.previous").exists())

        for directory in (".venv", "venv"):
            venv_root = self.scratch / directory / "install"
            venv_root.mkdir(parents=True)
            result, downloader = self._install(
                venv_root,
                downloader=FakeDownloader(self._files()),
            )
            self.assertEqual(result.reason, "install_failed")
            self.assertEqual(downloader.calls, [])

    def test_update_retains_previous_through_verification_and_then_completes(self) -> None:
        root = self._root("update")
        old_result, _old_downloader = self._install(root)
        self.assertEqual(old_result.reason, "installed")
        old_bytes = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }

        new_pin, new_registry, new_files = self._new_release(
            "1.2.4", js_body=b"window.updatedBundle = true;\n"
        )
        original_inspect = installer._inspect_tree_or_missing
        observed_previous = False

        def observe_previous(path: Path) -> Any:
            nonlocal observed_previous
            result = original_inspect(path)
            if (
                Path(path) == root / "web/frontend/dist"
                and (root / "web/frontend/dist.previous").exists()
            ):
                observed_previous = True
            return result

        with mock.patch.object(
            installer, "_inspect_tree_or_missing", side_effect=observe_previous
        ):
            result, _downloader = self._install(
                root,
                registry=new_registry,
                files=new_files,
                version="1.2.4",
            )
        self.assertEqual(result.reason, "installed")
        self.assertTrue(observed_previous)
        previous = root / "web/frontend/dist.previous"
        self.assertEqual(
            {path.name: path.read_bytes() for path in previous.iterdir()}, old_bytes
        )
        current_bytes = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }
        self.assertNotEqual(current_bytes, old_bytes)

        _newest_pin, newest_registry, newest_files = self._new_release(
            "1.2.5", js_body=b"window.newestBundle = true;\n"
        )
        result, _downloader = self._install(
            root,
            registry=newest_registry,
            files=newest_files,
            version="1.2.5",
        )
        self.assertEqual(result.reason, "installed")
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in (root / "web/frontend/dist.previous").iterdir()
            },
            current_bytes,
        )

    def test_rollback_when_old_tree_moves_but_candidate_promotion_fails(self) -> None:
        root = self._root("rollback-promotion")
        first, _downloader = self._install(root)
        self.assertEqual(first.reason, "installed")
        _new_pin, new_registry, new_files = self._new_release(
            "1.2.4", js_body=b"window.promotionFailure = true;\n"
        )
        original = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }
        original_replace = installer.os.replace

        def fail_candidate_promotion(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> None:
            if Path(source).name == "candidate" and Path(destination) == root / "web/frontend/dist":
                raise OSError("simulated promotion failure")
            original_replace(source, destination)

        with mock.patch.object(installer.os, "replace", side_effect=fail_candidate_promotion):
            result, _downloader = self._install(
                root,
                registry=new_registry,
                files=new_files,
                version="1.2.4",
            )
        self.assertEqual(result.reason, "rolled_back")
        self.assertEqual(
            {path.name: path.read_bytes() for path in (root / "web/frontend/dist").iterdir()},
            original,
        )
        self.assertFalse((root / "web/frontend/dist.previous").exists())
        self._assert_staging_empty(root)

    def test_rollback_when_post_swap_validation_fails(self) -> None:
        root = self._root("rollback-validation")
        first, _downloader = self._install(root)
        self.assertEqual(first.reason, "installed")
        _new_pin, new_registry, new_files = self._new_release(
            "1.2.4", js_body=b"window.validationFailure = true;\n"
        )
        original = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }
        original_inspect = installer._inspect_tree_or_missing

        def fail_after_swap(path: Path) -> Any:
            if (
                Path(path) == root / "web/frontend/dist"
                and (root / "web/frontend/dist.previous").exists()
            ):
                raise ValueError("simulated post-swap validation failure")
            return original_inspect(path)

        with mock.patch.object(
            installer, "_inspect_tree_or_missing", side_effect=fail_after_swap
        ):
            result, _downloader = self._install(
                root,
                registry=new_registry,
                files=new_files,
                version="1.2.4",
            )
        self.assertEqual(result.reason, "rolled_back")
        self.assertEqual(
            {path.name: path.read_bytes() for path in (root / "web/frontend/dist").iterdir()},
            original,
        )
        self.assertFalse((root / "web/frontend/dist.previous").exists())
        self._assert_staging_empty(root)

    def test_rollback_if_first_rename_moves_old_tree_then_raises(self) -> None:
        root = self._root("rollback-first-rename")
        first, _downloader = self._install(root)
        self.assertEqual(first.reason, "installed")
        _new_pin, new_registry, new_files = self._new_release(
            "1.2.4", js_body=b"window.firstRenameFailure = true;\n"
        )
        original = {
            path.name: path.read_bytes()
            for path in (root / "web/frontend/dist").iterdir()
        }
        original_replace = installer.os.replace

        def move_then_fail(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> None:
            original_replace(source, destination)
            if (
                Path(source) == root / "web/frontend/dist"
                and Path(destination) == root / "web/frontend/dist.previous"
            ):
                raise OSError("simulated first-rename error")

        with mock.patch.object(installer.os, "replace", side_effect=move_then_fail):
            result, _downloader = self._install(
                root,
                registry=new_registry,
                files=new_files,
                version="1.2.4",
            )
        self.assertEqual(result.reason, "rolled_back")
        self.assertEqual(
            {path.name: path.read_bytes() for path in (root / "web/frontend/dist").iterdir()},
            original,
        )
        self.assertFalse((root / "web/frontend/dist.previous").exists())

    def test_shared_download_guards_redirects_hosts_and_proxy_environment_offline(self) -> None:
        base = PLAYER_RELEASE_BASE + self.pin.tag
        asset_url = release_asset_url(self.pin, self.pin.metadata_asset_name)
        allowed_assets = frozenset(
            {self.pin.metadata_asset_name, self.pin.release_asset_name}
        )
        allowed_redirect = "https://release-assets.githubusercontent.com/signed/file?sig=x"
        header_checks: list[bool] = []
        openers: list[FakeRedirectOpener] = []

        def build_opener(*handlers: object) -> FakeRedirectOpener:
            redirect_handler = next(
                item
                for item in handlers
                if isinstance(item, opentunnel_installer._ReleaseRedirectHandler)
            )
            opener = FakeRedirectOpener(
                redirect_handler,
                self.metadata_bytes,
                [allowed_redirect],
                header_checks,
            )
            openers.append(opener)
            return opener

        destination = self.scratch / "redirect.part"
        with mock.patch.object(urllib.request, "build_opener", side_effect=build_opener):
            installer.download_player_release_asset(
                asset_url,
                destination,
                release_url=base,
                asset_names=allowed_assets,
                timeout_seconds=10,
                max_bytes=64 * 1024,
            )
        self.assertEqual(destination.read_bytes(), self.metadata_bytes)
        self.assertEqual(openers[0].initial_urls, [asset_url])
        self.assertTrue(all(not item for item in header_checks))

        bad_urls = (
            "http://github.com/zeug-zz/NeverEndingQuest-TTRPG/releases/download/v1.2.3/"
            + self.pin.metadata_asset_name,
            "https://evil.example/zeug-zz/NeverEndingQuest-TTRPG/releases/download/v1.2.3/"
            + self.pin.metadata_asset_name,
            base + "/../" + self.pin.metadata_asset_name,
        )
        for bad_url in bad_urls:
            with self.subTest(url=bad_url):
                with self.assertRaises(opentunnel_installer.DownloadSecurityError):
                    installer.download_player_release_asset(
                        bad_url,
                        self.scratch / "never.part",
                        release_url=base,
                        asset_names=allowed_assets,
                        timeout_seconds=10,
                        max_bytes=64 * 1024,
                    )

        rejected_redirects = (
            "http://release-assets.githubusercontent.com/signed/file?sig=x",
            "https://evil.example/signed/file?sig=x",
            "https://github.com.evil.example/signed/file?sig=x",
        )
        for index, rejected in enumerate(rejected_redirects):
            with self.subTest(redirect=rejected):
                captured: list[FakeRedirectOpener] = []

                def rejected_opener(*handlers: object) -> FakeRedirectOpener:
                    redirect_handler = next(
                        item
                        for item in handlers
                        if isinstance(item, opentunnel_installer._ReleaseRedirectHandler)
                    )
                    opener = FakeRedirectOpener(
                        redirect_handler,
                        self.metadata_bytes,
                        [rejected],
                        [],
                    )
                    captured.append(opener)
                    return opener

                with mock.patch.object(
                    urllib.request, "build_opener", side_effect=rejected_opener
                ):
                    with self.assertRaises(opentunnel_installer.DownloadSecurityError):
                        installer.download_player_release_asset(
                            asset_url,
                            self.scratch / ("rejected-%d.part" % index),
                            release_url=base,
                            asset_names=allowed_assets,
                            timeout_seconds=10,
                            max_bytes=64 * 1024,
                        )

        captured_handlers: list[object] = []

        class OfflineOpener:
            def open(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("offline tripwire")

        def offline_build_opener(*handlers: object) -> OfflineOpener:
            captured_handlers.extend(handlers)
            return OfflineOpener()

        with (
            mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:8080"}),
            mock.patch.object(
                urllib.request, "build_opener", side_effect=offline_build_opener
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "offline tripwire"):
                installer.download_player_release_asset(
                    asset_url,
                    self.scratch / "proxy.part",
                    release_url=base,
                    asset_names=allowed_assets,
                    timeout_seconds=10,
                    max_bytes=64 * 1024,
                )
        proxy_handlers = [
            handler
            for handler in captured_handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})


def _make_player_bundle(
    root: Path,
    *,
    js_body: bytes = _JS_BODY,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    asset_bodies = {_JS_NAME: js_body, _CSS_NAME: _CSS_BODY}
    records: dict[str, dict[str, object]] = {}
    for asset_name, body in asset_bodies.items():
        content_type = (
            "text/javascript; charset=utf-8"
            if asset_name.endswith(".js")
            else "text/css; charset=utf-8"
        )
        (root / asset_name).write_bytes(body)
        records[asset_name] = {
            "file": asset_name,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "content_type": content_type,
        }
    rows = "".join(
        "%s\t%s\n" % (name, records[name]["sha256"])
        for name in sorted(records)
    )
    build_id = hashlib.sha256(rows.encode("ascii")).hexdigest()[:32]
    shell = (
        "<!doctype html>\n"
        "<html lang=\"en\"><head>"
        "<meta name=\"neq-client-build\" content=\"%s\">" % build_id
        + "<meta name=\"neq-protocol-version\" content=\"1\">"
        + "<link rel=\"stylesheet\" href=\"/static/player/%s\">" % _CSS_NAME
        + "<script type=\"module\" src=\"/static/player/%s\"></script>" % _JS_NAME
        + "</head><body><main><h1>Player login</h1>"
        + "<form method=\"post\" action=\"/api/player/login\">"
        + "<input type=\"hidden\" name=\"csrf_token\" value=\"%s\">"
        % _CSRF_PLACEHOLDER
        + "<label>Password <input type=\"password\" name=\"password\" required></label>"
        + "<button type=\"submit\">Log in</button></form></main>"
        + "<div id=\"root\"></div></body></html>"
    ).encode("ascii")
    (root / "index.html").write_bytes(shell)
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "protocol_version": 1,
        "client_build_id": build_id,
        "shell": {
            "file": "index.html",
            "sha256": hashlib.sha256(shell).hexdigest(),
            "bytes": len(shell),
            "content_type": "text/html; charset=utf-8",
        },
        "assets": records,
    }
    (root / "player-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    return manifest


def _pin_from_metadata(metadata: dict[str, object]) -> PlayerAssetPin:
    version = str(metadata["version"])
    return PlayerAssetPin(
        version=version,
        tag=str(metadata["git_tag"]),
        source_commit=str(metadata["source_commit"]),
        outer_sha256=str(metadata["outer_sha256"]),
        size=int(metadata["outer_size"]),
        player_manifest_sha256=str(metadata["player_manifest_sha256"]),
        client_build_id=str(metadata["client_build_id"]),
        release_asset_name="neq-player-bundle-" + version + ".tar.gz",
        metadata_asset_name="neq-player-bundle-" + version + ".metadata.json",
    )


def _registry(pin: PlayerAssetPin) -> PlayerAssetsManifest:
    return parse_player_assets_manifest(_registry_document(pin))


def _registry_document(pin: PlayerAssetPin) -> dict[str, object]:
    return {
        "versions": {
            pin.version: {
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


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("ascii")


def _repin_archive(
    pin: PlayerAssetPin, archive: bytes
) -> tuple[PlayerAssetPin, bytes]:
    updated = replace(
        pin,
        outer_sha256=hashlib.sha256(archive).hexdigest(),
        size=len(archive),
    )
    return updated, _json_bytes(sidecar_for_pin(updated))


def _read_tar_files(archive_bytes: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            assert source is not None
            result[member.name] = source.read()
    return result


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(files):
                body = files[name]
                member = tarfile.TarInfo(name)
                member.size = len(body)
                member.mode = 0o644
                member.mtime = 0
                archive.addfile(member, io.BytesIO(body))
    return output.getvalue()


def _tar_with_entry(name: str, body: bytes) -> bytes:
    return _tar_bytes({name: body})


def _tar_with_symlink() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo("index.html")
        member.type = tarfile.SYMTYPE
        member.linkname = "target"
        archive.addfile(member)
    return output.getvalue()


def _tar_with_hardlink() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo("index.html")
        member.type = tarfile.LNKTYPE
        member.linkname = "target"
        archive.addfile(member)
    return output.getvalue()


def _tar_with_device() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo("index.html")
        member.type = tarfile.CHRTYPE
        member.devmajor = 1
        member.devminor = 3
        archive.addfile(member)
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
