# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline security and transaction tests for the OpenTunnel installer."""

from __future__ import annotations

import ast
import hashlib
import io
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

from scripts.network_packaging import opentunnel_installer as installer
from scripts.network_packaging.manifest import PinnedManifest, load_pinned_manifest
from web.extensions.opentunnel_sharing.companion import (
    resolve_companion,
    verify_companion_digest,
)

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_MANIFEST = _ROOT / "packaging/opentunnel-v0.6.2.manifest.json"
_PLATFORM_IDENTITY = {
    "darwin-arm64": ("Darwin", "arm64"),
    "linux-arm64": ("Linux", "aarch64"),
}
_RELEASE = "https://github.com/anomalyco/opentunnel/releases/download/v0.6.2"


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
        value = self.files[url]
        if isinstance(value, BaseException):
            if isinstance(value, KeyboardInterrupt):
                raise value
            raise value
        payload = value + b"x" if url in self.oversized else value
        destination.write_bytes(payload)


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
        redirect_handler: installer._ReleaseRedirectHandler,
        bodies: dict[str, bytes],
        redirect_chains: dict[str, list[str]],
        header_checks: list[bool],
    ) -> None:
        self.redirect_handler = redirect_handler
        self.bodies = bodies
        self.redirect_chains = redirect_chains
        self.header_checks = header_checks
        self.initial_urls: list[str] = []

    def open(self, request: urllib.request.Request, *, timeout: int) -> FakeRedirectResponse:
        if timeout <= 0:
            raise AssertionError("fake opener expected a bounded timeout")
        self.initial_urls.append(request.full_url)
        self.header_checks.append(installer._has_sensitive_headers(request))
        current = request
        for location in self.redirect_chains.get(request.full_url, []):
            current = self.redirect_handler.redirect_request(
                current,
                None,
                302,
                "Found",
                {},
                location,
            )
            self.header_checks.append(installer._has_sensitive_headers(current))
        return FakeRedirectResponse(self.bodies[request.full_url], current.full_url)


class NetworkCompanionInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)

        self._network_guards = [
            mock.patch.object(
                socket,
                "socket",
                side_effect=AssertionError("installer tests must not open sockets"),
            ),
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("installer tests must not use urlopen"),
            ),
            mock.patch.object(
                urllib.request.OpenerDirector,
                "open",
                side_effect=AssertionError("installer tests must not download"),
            ),
        ]
        for guard in self._network_guards:
            guard.start()
            self.addCleanup(guard.stop)

    def _fixture(
        self,
        platform_key: str = "linux-arm64",
        *,
        executable: bytes | None = None,
        archive: bytes | None = None,
        sums_text: str | None = None,
        manifest: PinnedManifest | None = None,
    ) -> tuple[PinnedManifest, bytes, bytes, bytes, FakeDownloader]:
        source_manifest = manifest or load_pinned_manifest(_SOURCE_MANIFEST)
        pin = source_manifest.platforms[platform_key]
        executable_bytes = executable or (b"offline OpenTunnel fixture " + platform_key.encode())
        archive_member = (
            "opentunnel"
            if platform_key == "darwin-arm64"
            else pin.asset_stem + "/opentunnel"
        )
        archive_bytes = archive or _tar_bytes(archive_member, executable_bytes)
        archive_digest = hashlib.sha256(archive_bytes).hexdigest()
        if sums_text is None:
            sums_text = "%s  %s\n" % (archive_digest, pin.asset_name)
        sums_bytes = sums_text.encode("ascii")
        sums_digest = hashlib.sha256(sums_bytes).hexdigest()
        updated_pin = replace(
            pin,
            archive_size_bytes=len(archive_bytes),
            archive_sha256=archive_digest,
            executable_size_bytes=len(executable_bytes),
            sha256=hashlib.sha256(executable_bytes).hexdigest(),
        )
        updated_platforms = dict(source_manifest.platforms)
        updated_platforms[platform_key] = updated_pin
        updated_manifest = replace(
            source_manifest,
            sha256sums_provenance=replace(
                source_manifest.sha256sums_provenance,
                sha256=sums_digest,
                size_bytes=len(sums_bytes),
            ),
            platforms=MappingProxyType(updated_platforms),
        )
        downloader = FakeDownloader(
            {
                updated_manifest.sha256sums_provenance.url: sums_bytes,
                _RELEASE + "/" + updated_pin.asset_name: archive_bytes,
            }
        )
        return updated_manifest, archive_bytes, executable_bytes, sums_bytes, downloader

    def _install(
        self,
        root: Path,
        manifest: PinnedManifest,
        downloader: Callable[..., object],
        platform_key: str = "linux-arm64",
    ) -> installer.InstallResult:
        system, machine = _PLATFORM_IDENTITY[platform_key]
        return installer.install_companion(
            root,
            manifest,
            platform_key=platform_key,
            downloader=downloader,
            system=system,
            machine=machine,
        )

    def _install_with_fake_redirects(
        self,
        root: Path,
        manifest: PinnedManifest,
        bodies: dict[str, bytes],
        redirect_chains: dict[str, list[str]],
    ) -> tuple[installer.InstallResult, list[FakeRedirectOpener], list[bool]]:
        openers: list[FakeRedirectOpener] = []
        header_checks: list[bool] = []

        def build_opener(*handlers: object) -> FakeRedirectOpener:
            handler = next(
                item
                for item in handlers
                if isinstance(item, installer._ReleaseRedirectHandler)
            )
            opener = FakeRedirectOpener(
                handler, bodies, redirect_chains, header_checks
            )
            openers.append(opener)
            return opener

        def downloader(
            url: str,
            destination: Path,
            *,
            timeout_seconds: int,
            max_bytes: int,
        ) -> None:
            installer.download_release_asset(
                url,
                destination,
                release_url=manifest.release_url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )

        with mock.patch.object(
            urllib.request, "build_opener", side_effect=build_opener
        ):
            result = self._install(root, manifest, downloader)
        return result, openers, header_checks

    def _assert_stage_empty(self, root: Path) -> None:
        stage_root = root / "runtime/opentunnel/.staging"
        if stage_root.exists():
            self.assertEqual(list(stage_root.iterdir()), [])
        self.assertEqual(list(root.rglob("*.part")), [])

    def _root(self, name: str = "install") -> Path:
        root = self.scratch / name
        root.mkdir()
        return root

    def test_success_for_both_approved_platforms_and_install_contract(self) -> None:
        for platform_key in _PLATFORM_IDENTITY:
            with self.subTest(platform=platform_key):
                root = self._root(platform_key)
                manifest, _archive, executable, _sums, downloader = self._fixture(
                    platform_key
                )
                campaign = root / "modules/campaign-sentinel.txt"
                character = root / "characters/character-sentinel.txt"
                tracker = root / "party_tracker.json"
                other_profile = root / "runtime/opentunnel/profiles/other-profile.json"
                campaign.parent.mkdir()
                character.parent.mkdir()
                other_profile.parent.mkdir(parents=True)
                campaign.write_text("campaign stays", encoding="ascii")
                character.write_text("character stays", encoding="ascii")
                tracker.write_text("{\"party\":\"unchanged\"}", encoding="ascii")
                other_profile.write_text("profile stays", encoding="ascii")
                sentinel_bytes = (
                    campaign.read_bytes(),
                    character.read_bytes(),
                    tracker.read_bytes(),
                    other_profile.read_bytes(),
                )

                result = self._install(root, manifest, downloader, platform_key)

                self.assertEqual(result.reason, "installed")
                pin = manifest.platforms[platform_key]
                installed = root / pin.runtime_path
                metadata = installed.lstat()
                self.assertTrue(stat.S_ISREG(metadata.st_mode))
                self.assertFalse(stat.S_ISLNK(metadata.st_mode))
                self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o755)
                self.assertEqual(installed.read_bytes(), executable)
                system, machine = _PLATFORM_IDENTITY[platform_key]
                resolved = resolve_companion(
                    root,
                    {
                        key: {"asset_stem": item.asset_stem, "sha256": item.sha256}
                        for key, item in manifest.platforms.items()
                    },
                    system=system,
                    machine=machine,
                )
                self.assertEqual(resolved.state, "resolved")
                self.assertEqual(resolved.path, installed.resolve())
                self.assertTrue(verify_companion_digest(installed, pin.sha256))
                self.assertEqual(
                    (
                        campaign.read_bytes(),
                        character.read_bytes(),
                        tracker.read_bytes(),
                        other_profile.read_bytes(),
                    ),
                    sentinel_bytes,
                )
                self.assertEqual(len(downloader.calls), 2)
                self.assertTrue(
                    all(call[2] == installer.MAX_DOWNLOAD_TIMEOUT_SECONDS for call in downloader.calls)
                )
                self.assertEqual(
                    downloader.calls[0][3],
                    manifest.sha256sums_provenance.size_bytes,
                )
                self.assertEqual(
                    downloader.calls[1][3],
                    pin.archive_size_bytes,
                )
                self._assert_stage_empty(root)

    def test_archive_digest_mismatch_with_manifest_pin_is_rejected(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        pin = manifest.platforms["linux-arm64"]
        altered_pin = replace(pin, archive_sha256="0" * 64)
        platforms = dict(manifest.platforms)
        platforms["linux-arm64"] = altered_pin
        manifest = replace(manifest, platforms=MappingProxyType(platforms))
        root = self._root()

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "checksum_mismatch")
        self.assertEqual(len(downloader.calls), 2)
        self._assert_stage_empty(root)

    def test_archive_digest_mismatch_with_exact_sha256sums_entry_is_rejected(self) -> None:
        source = load_pinned_manifest(_SOURCE_MANIFEST)
        pin = source.platforms["linux-arm64"]
        executable = b"valid fixture executable"
        archive = _tar_bytes("opentunnel", executable)
        actual_digest = hashlib.sha256(archive).hexdigest()
        wrong_sums = "%s  %s\n" % ("0" * 64, pin.asset_name)
        sums_bytes = wrong_sums.encode("ascii")
        # Keep the local archive pin correct while pinning the wrong fetched sums file.
        pin = replace(
            pin,
            archive_size_bytes=len(archive),
            archive_sha256=actual_digest,
            executable_size_bytes=len(executable),
            sha256=hashlib.sha256(executable).hexdigest(),
        )
        platforms = dict(source.platforms)
        platforms["linux-arm64"] = pin
        manifest = replace(
            source,
            platforms=MappingProxyType(platforms),
            sha256sums_provenance=replace(
                source.sha256sums_provenance,
                sha256=hashlib.sha256(sums_bytes).hexdigest(),
                size_bytes=len(sums_bytes),
            ),
        )
        downloader = FakeDownloader(
            {
                manifest.sha256sums_provenance.url: sums_bytes,
                _RELEASE + "/" + pin.asset_name: archive,
            }
        )
        root = self._root()

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "sums_mismatch")
        self._assert_stage_empty(root)

    def test_tampered_sha256sums_provenance_digest_is_rejected(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        sums_url = manifest.sha256sums_provenance.url
        original_sums = downloader.files[sums_url]
        assert isinstance(original_sums, bytes)
        downloader.files[sums_url] = b"!" * len(original_sums)
        root = self._root()

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "sums_mismatch")
        self.assertEqual(len(downloader.calls), 1)
        self._assert_stage_empty(root)

    def test_executable_digest_mismatch_is_rejected_before_activation(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        pin = manifest.platforms["linux-arm64"]
        altered_pin = replace(pin, sha256="f" * 64)
        platforms = dict(manifest.platforms)
        platforms["linux-arm64"] = altered_pin
        manifest = replace(manifest, platforms=MappingProxyType(platforms))
        root = self._root()

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "executable_mismatch")
        self.assertFalse((root / pin.runtime_path).exists())
        self._assert_stage_empty(root)

    def test_unsafe_archive_members_are_rejected_and_stage_is_cleaned(self) -> None:
        manifest_base, _archive, _executable, _sums, _downloader = self._fixture()
        executable = b"executable fixture"
        unsafe_archives = {
            "parent traversal": _tar_bytes("../opentunnel", executable),
            "absolute path": _tar_bytes("/opentunnel", executable),
            "symlink": _tar_with_link(executable, hard=False),
            "hardlink": _tar_with_link(executable, hard=True),
            "device": _tar_with_device(),
            "oversized member": _tar_bytes("opentunnel", b"x" * 17),
            "extra file": _tar_with_extra(executable),
            "missing executable": _tar_with_named_file("not-opentunnel", executable),
            "member count cap": _tar_with_many_members(executable),
        }
        for label, archive in unsafe_archives.items():
            with self.subTest(case=label):
                root = self._root("unsafe-" + label.replace(" ", "-"))
                manifest, archive, _binary, sums, _ = self._fixture(
                    executable=executable,
                    archive=archive,
                )
                # Pin the unexpected-size archive to its actual digest so extraction
                # validation, rather than the outer checksum, is the rejection point.
                pin = manifest.platforms["linux-arm64"]
                if label == "oversized member":
                    original_validate = installer._validate_tar_members

                    def validate_with_small_cap(members: list[tarfile.TarInfo], pin: Any) -> tarfile.TarInfo:
                        with mock.patch.object(installer, "MAX_EXTRACTED_BYTES", 16):
                            return original_validate(members, pin)

                    with mock.patch.object(
                        installer,
                        "_validate_tar_members",
                        side_effect=validate_with_small_cap,
                    ):
                        result = self._install(
                            root, manifest, _downloader_for(manifest, archive, sums)
                        )
                elif label == "member count cap":
                    with mock.patch.object(installer, "MAX_ARCHIVE_MEMBERS", 2):
                        result = self._install(
                            root, manifest, _downloader_for(manifest, archive, sums)
                        )
                else:
                    result = self._install(
                        root, manifest, _downloader_for(manifest, archive, sums)
                    )
                self.assertEqual(result.reason, "unsafe_archive")
                self.assertFalse((root / pin.runtime_path).exists())
                self._assert_stage_empty(root)

    def test_download_oversize_and_timeout_fail_closed(self) -> None:
        manifest, archive, _executable, sums, _downloader = self._fixture()
        sums_url = manifest.sha256sums_provenance.url
        archive_url = _RELEASE + "/" + manifest.platforms["linux-arm64"].asset_name
        cases = (
            FakeDownloader({sums_url: sums, archive_url: archive}, oversized={archive_url}),
            FakeDownloader({sums_url: TimeoutError("raw timeout"), archive_url: archive}),
        )
        for index, downloader in enumerate(cases):
            with self.subTest(case=index):
                root = self._root("download-failure-%d" % index)
                result = self._install(root, manifest, downloader)
                self.assertEqual(result.reason, "download_failed")
                self._assert_stage_empty(root)

    def test_unsupported_platform_pairs_fail_before_download(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        root = self._root()
        for platform_key, system, machine in (
            ("darwin-x86_64", "Darwin", "x86_64"),
            ("linux-x64", "Linux", "x86_64"),
            ("windows-arm64", "Windows", "arm64"),
            ("linux-arm64", "Linux", "x86_64"),
        ):
            with self.subTest(platform=platform_key, machine=machine):
                result = installer.install_companion(
                    root,
                    manifest,
                    platform_key=platform_key,
                    downloader=downloader,
                    system=system,
                    machine=machine,
                )
                self.assertEqual(result.reason, "unsupported_platform")
        self.assertEqual(downloader.calls, [])

    def test_virtual_environment_install_roots_are_rejected(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        for directory in (".venv", "venv"):
            with self.subTest(directory=directory):
                root = self.scratch / directory / "install"
                root.mkdir(parents=True)
                result = self._install(root, manifest, downloader)
                self.assertEqual(result.reason, "install_failed")
        self.assertEqual(downloader.calls, [])

    def test_staging_directory_must_be_private_and_owner_controlled(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        root = self._root()
        staging_root = root / "runtime/opentunnel/.staging"
        staging_root.mkdir(parents=True)
        staging_root.chmod(0o755)

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "install_failed")
        self.assertEqual(downloader.calls, [])
        self.assertEqual(list(staging_root.iterdir()), [])

        staging_root.chmod(0o700)
        with mock.patch.object(installer.os, "getuid", return_value=os.getuid() + 1):
            owner_result = self._install(root, manifest, downloader)
        self.assertEqual(owner_result.reason, "install_failed")
        self.assertEqual(downloader.calls, [])

    def test_idempotent_rerun_verifies_digest_without_download(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        root = self._root()
        first = self._install(root, manifest, downloader)
        self.assertEqual(first.reason, "installed")
        call_count = len(downloader.calls)

        no_download = FakeDownloader({})
        second = self._install(root, manifest, no_download)

        self.assertEqual(second.reason, "already_installed")
        self.assertEqual(no_download.calls, [])
        self.assertEqual(len(downloader.calls), call_count)
        self._assert_stage_empty(root)

    def test_update_retains_previous_until_new_asset_is_verified_then_removes_it(self) -> None:
        root = self._root()
        old_manifest, _old_archive, old_executable, _old_sums, old_downloader = self._fixture(
            executable=b"old verified executable"
        )
        self.assertEqual(self._install(root, old_manifest, old_downloader).reason, "installed")

        new_manifest, _new_archive, new_executable, _new_sums, new_downloader = self._fixture(
            executable=b"new verified executable",
            manifest=old_manifest,
        )
        # The helper builds the new checksums and executable pin from its input,
        # retaining the old platform matrix as a base.
        prior = root / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64.previous"
        original_resolver = installer.resolve_companion
        saw_previous_during_candidate_check = False

        def observe_resolve(*args: Any, **kwargs: Any) -> Any:
            nonlocal saw_previous_during_candidate_check
            answer = original_resolver(*args, **kwargs)
            if answer.state == "resolved" and answer.expected_sha256 == new_manifest.platforms["linux-arm64"].sha256:
                if (root / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64").exists():
                    saw_previous_during_candidate_check = prior.exists()
            return answer

        with mock.patch.object(installer, "resolve_companion", side_effect=observe_resolve):
            result = self._install(root, new_manifest, new_downloader)

        self.assertEqual(result.reason, "installed")
        self.assertTrue(saw_previous_during_candidate_check)
        self.assertEqual(
            (root / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64/opentunnel").read_bytes(),
            new_executable,
        )
        self.assertFalse(prior.exists())
        self.assertNotEqual(old_executable, new_executable)
        self._assert_stage_empty(root)

    def test_failed_update_rolls_back_and_restores_prior_digest(self) -> None:
        root = self._root()
        old_manifest, _old_archive, old_executable, _old_sums, old_downloader = self._fixture(
            executable=b"old verified executable"
        )
        self.assertEqual(self._install(root, old_manifest, old_downloader).reason, "installed")
        new_manifest, _archive, _new_executable, _sums, new_downloader = self._fixture(
            executable=b"new executable that will fail verification",
            manifest=old_manifest,
        )
        original_verify = installer.verify_companion_digest
        new_digest = new_manifest.platforms["linux-arm64"].sha256

        def fail_new_candidate(path: Path, expected_sha256: str) -> bool:
            if expected_sha256 == new_digest:
                return False
            return original_verify(path, expected_sha256)

        with mock.patch.object(
            installer, "verify_companion_digest", side_effect=fail_new_candidate
        ):
            result = self._install(root, new_manifest, new_downloader)

        self.assertEqual(result.reason, "rolled_back")
        restored = root / old_manifest.platforms["linux-arm64"].runtime_path
        self.assertEqual(restored.read_bytes(), old_executable)
        self.assertTrue(
            verify_companion_digest(
                restored, old_manifest.platforms["linux-arm64"].sha256
            )
        )
        resolution = resolve_companion(
            root,
            {
                "linux-arm64": {
                    "asset_stem": old_manifest.platforms["linux-arm64"].asset_stem,
                    "sha256": old_manifest.platforms["linux-arm64"].sha256,
                }
            },
            system="Linux",
            machine="aarch64",
        )
        self.assertEqual(resolution.state, "resolved")
        self.assertFalse(
            (root / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64.previous").exists()
        )
        self._assert_stage_empty(root)

    def test_downloader_interruption_cleans_partial_staging(self) -> None:
        manifest, archive, _executable, sums, downloader = self._fixture()
        archive_url = _RELEASE + "/" + manifest.platforms["linux-arm64"].asset_name
        downloader.files[archive_url] = RuntimeError("private raw failure")
        root = self._root()

        result = self._install(root, manifest, downloader)

        self.assertEqual(result.reason, "download_failed")
        self.assertEqual(len(downloader.calls), 2)
        self.assertGreater(len(archive), 0)
        self._assert_stage_empty(root)

    def test_keyboard_interrupt_propagates_after_stage_cleanup(self) -> None:
        manifest, _archive, _executable, _sums, downloader = self._fixture()
        downloader.files[manifest.sha256sums_provenance.url] = KeyboardInterrupt()
        root = self._root()

        with self.assertRaises(KeyboardInterrupt):
            self._install(root, manifest, downloader)
        self._assert_stage_empty(root)

    def test_cli_refuses_without_explicit_install_flag(self) -> None:
        root = self._root()
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            result = installer.main(["--install-root", str(root)])
        self.assertEqual(result, 2)
        self.assertIn("explicit --install required", output.getvalue())
        self.assertEqual(list(root.iterdir()), [])

    def test_cli_prints_only_bounded_install_result(self) -> None:
        root = self._root()
        output = io.StringIO()
        with (
            mock.patch("sys.stdout", output),
            mock.patch.object(installer.platform, "system", return_value="Linux"),
            mock.patch.object(installer.platform, "machine", return_value="aarch64"),
            mock.patch.object(
                installer,
                "install_companion",
                return_value=installer.InstallResult("download_failed", "linux-arm64"),
            ) as install_mock,
        ):
            result = installer.main(["--install-root", str(root), "--install"])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "OpenTunnel installation: download_failed\n")
        self.assertNotIn("https://", output.getvalue())
        self.assertNotIn("raw", output.getvalue())
        install_mock.assert_called_once()

    def test_github_release_redirect_chain_succeeds_with_signed_cdn_url(self) -> None:
        manifest, archive, _executable, sums, _ = self._fixture()
        sums_url = manifest.sha256sums_provenance.url
        archive_url = _RELEASE + "/" + manifest.platforms["linux-arm64"].asset_name
        bodies = {sums_url: sums, archive_url: archive}
        redirect_chains = {
            sums_url: [
                "https://release-assets.githubusercontent.com/signed/SHA256SUMS?sig=one",
                "https://github-releases.githubusercontent.com/signed/SHA256SUMS?sig=two",
                "https://objects.githubusercontent.com/signed/SHA256SUMS?sig=three",
            ],
            archive_url: [
                "https://release-assets.githubusercontent.com/signed/opentunnel.tar.gz?sig=asset"
            ],
        }
        root = self._root()

        result, openers, header_checks = self._install_with_fake_redirects(
            root, manifest, bodies, redirect_chains
        )

        self.assertEqual(result.reason, "installed")
        self.assertEqual(len(openers), 2)
        self.assertTrue(all(not has_sensitive for has_sensitive in header_checks))
        initial_urls = [url for opener in openers for url in opener.initial_urls]
        self.assertEqual(initial_urls, [sums_url, archive_url])
        self.assertTrue(all(url.startswith("https://github.com/") for url in initial_urls))
        self.assertEqual(len(redirect_chains[sums_url]), installer.MAX_REDIRECTS)
        self._assert_stage_empty(root)

    def test_rejected_redirects_return_download_failed_and_clean_parts(self) -> None:
        manifest, archive, _executable, sums, _ = self._fixture()
        sums_url = manifest.sha256sums_provenance.url
        archive_url = _RELEASE + "/" + manifest.platforms["linux-arm64"].asset_name
        bodies = {sums_url: sums, archive_url: archive}
        rejected_urls = {
            "http downgrade": "http://github.com/anomalyco/opentunnel/releases/download/v0.6.2/SHA256SUMS",
            "other host": "https://evil.example/signed/SHA256SUMS?sig=x",
            "userinfo": "https://user@release-assets.githubusercontent.com/signed/SHA256SUMS?sig=x",
            "non-443 port": "https://release-assets.githubusercontent.com:444/signed/SHA256SUMS?sig=x",
            "cdn subdomain": "https://cdn.release-assets.githubusercontent.com/signed/SHA256SUMS?sig=x",
            "github suffix trick": "https://github.com.evil.example/signed/SHA256SUMS?sig=x",
        }
        for label, rejected_url in rejected_urls.items():
            with self.subTest(case=label):
                root = self._root("redirect-" + label.replace(" ", "-"))
                result, _openers, header_checks = self._install_with_fake_redirects(
                    root,
                    manifest,
                    bodies,
                    {sums_url: [rejected_url]},
                )
                self.assertEqual(result.reason, "download_failed")
                self.assertTrue(all(not has_sensitive for has_sensitive in header_checks))
                self._assert_stage_empty(root)

    def test_redirect_loop_and_excess_chain_are_bounded(self) -> None:
        manifest, archive, _executable, sums, _ = self._fixture()
        sums_url = manifest.sha256sums_provenance.url
        archive_url = _RELEASE + "/" + manifest.platforms["linux-arm64"].asset_name
        bodies = {sums_url: sums, archive_url: archive}
        chains = {
            "loop": [
                "https://release-assets.githubusercontent.com/signed/SHA256SUMS?sig=one",
                sums_url,
            ],
            "too-many": [
                "https://release-assets.githubusercontent.com/signed/SHA256SUMS?sig=one",
                "https://github-releases.githubusercontent.com/signed/SHA256SUMS?sig=two",
                "https://objects.githubusercontent.com/signed/SHA256SUMS?sig=three",
                "https://release-assets.githubusercontent.com/signed/SHA256SUMS?sig=four",
            ],
        }
        for label, chain in chains.items():
            with self.subTest(case=label):
                root = self._root("redirect-chain-" + label)
                result, _openers, header_checks = self._install_with_fake_redirects(
                    root, manifest, bodies, {sums_url: chain}
                )
                self.assertEqual(result.reason, "download_failed")
                self.assertTrue(all(not has_sensitive for has_sensitive in header_checks))
                self._assert_stage_empty(root)

    def test_redirect_handler_removes_auth_and_cookie_headers(self) -> None:
        handler = installer._ReleaseRedirectHandler()
        request = urllib.request.Request(
            _RELEASE + "/SHA256SUMS",
            headers={"Authorization": "private", "Cookie": "session=private"},
        )
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://release-assets.githubusercontent.com/signed/SHA256SUMS?sig=x",
        )
        self.assertIsNotNone(redirected)
        self.assertFalse(installer._has_sensitive_headers(redirected))

    def test_initial_download_url_rejects_non_https_and_wrong_host(self) -> None:
        for bad_url in (
            "http://github.com/anomalyco/opentunnel/releases/download/v0.6.2/SHA256SUMS",
            "https://evil.example/anomalyco/opentunnel/releases/download/v0.6.2/SHA256SUMS",
        ):
            with self.subTest(url=bad_url):
                with self.assertRaises(installer.DownloadSecurityError):
                    installer._validate_download_url(bad_url, _RELEASE)

    def test_real_downloader_ignores_proxy_environment(self) -> None:
        captured_handlers: list[object] = []

        class Opener:
            def open(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("offline opener tripwire")

        def capture_opener(*handlers: object) -> Opener:
            captured_handlers.extend(handlers)
            return Opener()

        destination = self.scratch / "never-downloaded.part"
        with (
            mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:8080"}),
            mock.patch.object(
                urllib.request, "build_opener", side_effect=capture_opener
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "offline opener tripwire"):
                installer.download_release_asset(
                    _RELEASE + "/SHA256SUMS",
                    destination,
                    release_url=_RELEASE,
                    timeout_seconds=10,
                    max_bytes=1024,
                )
        proxy_handlers = [
            handler
            for handler in captured_handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})
        self.assertFalse(destination.exists())

    def test_installer_and_test_source_use_no_subprocess_or_shell(self) -> None:
        for path in (Path(installer.__file__), Path(__file__)):
            tree = ast.parse(path.read_text(encoding="ascii"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
            self.assertNotIn("subprocess", imported)
            self.assertNotIn("commands", imported)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertFalse(
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "os"
                        and node.func.attr == "system",
                        "installer code must not run a shell",
                    )


def _tar_bytes(member_name: str, executable: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(executable)
        member.mode = 0o755
        archive.addfile(member, io.BytesIO(executable))
    return output.getvalue()


def _tar_with_named_file(name: str, body: bytes) -> bytes:
    return _tar_bytes(name, body)


def _tar_with_extra(executable: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        binary = tarfile.TarInfo("opentunnel")
        binary.size = len(executable)
        archive.addfile(binary, io.BytesIO(executable))
        extra_body = b"unexpected"
        extra = tarfile.TarInfo("README.txt")
        extra.size = len(extra_body)
        archive.addfile(extra, io.BytesIO(extra_body))
    return output.getvalue()


def _tar_with_link(executable: bytes, *, hard: bool) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        link = tarfile.TarInfo("opentunnel")
        link.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
        link.linkname = "target"
        archive.addfile(link)
    return output.getvalue()


def _tar_with_device() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        device = tarfile.TarInfo("opentunnel")
        device.type = tarfile.CHRTYPE
        device.devmajor = 1
        device.devminor = 3
        archive.addfile(device)
    return output.getvalue()


def _tar_with_many_members(executable: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        binary = tarfile.TarInfo("opentunnel")
        binary.size = len(executable)
        archive.addfile(binary, io.BytesIO(executable))
        for index in range(3):
            directory = tarfile.TarInfo("empty-%d" % index)
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
    return output.getvalue()


def _downloader_for(
    manifest: PinnedManifest, archive: bytes, sums: bytes
) -> FakeDownloader:
    pin = manifest.platforms["linux-arm64"]
    return FakeDownloader(
        {
            manifest.sha256sums_provenance.url: sums,
            _RELEASE + "/" + pin.asset_name: archive,
        }
    )


if __name__ == "__main__":
    unittest.main()
