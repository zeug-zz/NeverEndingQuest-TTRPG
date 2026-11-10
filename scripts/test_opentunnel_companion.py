# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for OpenTunnel companion resolution and digest pins."""

from __future__ import annotations

import ast
import hashlib
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing.companion import (
    DIGEST_CHUNK_SIZE,
    CompanionResolution,
    resolve_companion,
    verify_companion_digest,
)

_SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "web/extensions/opentunnel_sharing/companion.py"
)
_TEST_DIGEST = "a" * 64
_PLATFORM_MANIFEST = {
    "darwin-arm64": {
        "asset_stem": "opentunnel-darwin-arm64",
        "sha256": _TEST_DIGEST,
    },
    "linux-arm64": {
        "asset_stem": "opentunnel-linux-arm64",
        "sha256": _TEST_DIGEST,
    },
}


class OpenTunnelCompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)

    def _install_binary(
        self,
        *,
        stem: str = "opentunnel-linux-arm64",
        install_root: Path | None = None,
        executable: bool = True,
    ) -> tuple[Path, Path]:
        root = self.scratch / "install" if install_root is None else install_root
        binary = root / "runtime/opentunnel/v0.6.2" / stem / "opentunnel"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"pinned companion fixture")
        binary.chmod(0o755 if executable else 0o600)
        return root, binary

    def test_resolves_supported_platforms_and_architecture_aliases(self) -> None:
        cases = (
            ("Darwin", "arm64", "darwin-arm64"),
            ("Linux", "arm64", "linux-arm64"),
            ("Linux", "aarch64", "linux-arm64"),
            ("Darwin", "aarch64", "darwin-arm64"),
        )
        for system, machine, platform_key in cases:
            with self.subTest(system=system, machine=machine):
                stem = _PLATFORM_MANIFEST[platform_key]["asset_stem"]
                root, binary = self._install_binary(stem=stem)
                result = resolve_companion(
                    root,
                    _PLATFORM_MANIFEST,
                    system=system,
                    machine=machine,
                )
                self.assertEqual(result.state, "resolved")
                self.assertEqual(result.reason, "resolved")
                self.assertEqual(result.path, binary.resolve())
                self.assertEqual(result.expected_sha256, _TEST_DIGEST)

    def test_unsupported_platform_pairs_fail_before_manifest_lookup(self) -> None:
        manifest = {
            **_PLATFORM_MANIFEST,
            "darwin-x86_64": {"asset_stem": "unsupported", "sha256": _TEST_DIGEST},
            "windows-arm64": {"asset_stem": "unsupported", "sha256": _TEST_DIGEST},
        }
        cases = (
            ("Darwin", "x86_64"),
            ("Linux", "x86_64"),
            ("Windows", "arm64"),
            ("FreeBSD", "arm64"),
            ("Darwin", "unknown-arch"),
        )
        for system, machine in cases:
            with self.subTest(system=system, machine=machine):
                result = resolve_companion(
                    self.scratch,
                    manifest,
                    system=system,
                    machine=machine,
                )
                self.assertEqual(result.state, "unsupported_platform")
                self.assertEqual(result.reason, "unsupported_platform")
                self.assertIsNone(result.path)
                self.assertIsNone(result.expected_sha256)

    def test_reports_missing_binary_and_missing_manifest_entry(self) -> None:
        missing_binary = resolve_companion(
            self.scratch,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(missing_binary.state, "missing_asset")
        self.assertEqual(missing_binary.reason, "binary_missing")

        missing_entry = resolve_companion(
            self.scratch,
            {},
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(missing_entry.state, "missing_asset")
        self.assertEqual(missing_entry.reason, "manifest_entry_missing")

    def test_rejects_invalid_manifest_shapes_and_values(self) -> None:
        malformed_entries = (
            None,
            [],
            {"asset_stem": "opentunnel-linux-arm64"},
            {
                "asset_stem": "opentunnel-linux-arm64",
                "sha256": _TEST_DIGEST,
                "extra": "value",
            },
            {"asset_stem": "opentunnel-linux-arm64", "sha256": "g" * 64},
            {"asset_stem": "opentunnel-linux-arm64", "sha256": "A" * 64},
            {"asset_stem": "opentunnel-linux-arm64", "sha256": "a" * 63},
        )
        malformed_entries += tuple(
            {"asset_stem": stem, "sha256": _TEST_DIGEST}
            for stem in (
                "../escape",
                "..",
                "dir/name",
                "",
                "a b",
                "bad\x00stem",
                "x" * 65,
            )
        )
        for entry in malformed_entries:
            with self.subTest(entry=repr(entry)[:80]):
                result = resolve_companion(
                    self.scratch,
                    {"linux-arm64": entry},
                    system="Linux",
                    machine="arm64",
                )
                self.assertEqual(result.state, "invalid_manifest")
                self.assertEqual(result.reason, "invalid_manifest")
                self.assertIsNone(result.path)
                self.assertIsNone(result.expected_sha256)

        result = resolve_companion(
            self.scratch,
            None,  # type: ignore[arg-type]
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "invalid_manifest")

    def test_traversal_is_rejected_without_echoing_untrusted_path(self) -> None:
        malicious_stem = "../../outside/private"
        result = resolve_companion(
            self.scratch,
            {
                "linux-arm64": {
                    "asset_stem": malicious_stem,
                    "sha256": _TEST_DIGEST,
                }
            },
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "invalid_manifest")
        self.assertNotIn(malicious_stem, result.reason)
        self.assertIsNone(result.path)

    def test_rejects_symlinked_final_binary(self) -> None:
        root, binary = self._install_binary()
        target = self.scratch / "external-opentunnel"
        target.write_bytes(b"outside")
        binary.unlink()
        binary.symlink_to(target)

        result = resolve_companion(
            root,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(result.reason, "symlink_component")
        self.assertIsNone(result.path)

    def test_rejects_symlinked_intermediate_directory(self) -> None:
        root = self.scratch / "install"
        stem = "opentunnel-linux-arm64"
        outside_path = root / "staged" / stem / "opentunnel"
        outside_path.parent.mkdir(parents=True)
        outside_path.write_bytes(b"inside root but linked")
        outside_path.chmod(0o755)
        version_root = root / "runtime/opentunnel/v0.6.2"
        version_root.mkdir(parents=True)
        (version_root / stem).symlink_to(outside_path.parent, target_is_directory=True)

        result = resolve_companion(
            root,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(result.reason, "symlink_component")

    def test_rejects_symlink_escape_from_install_root(self) -> None:
        root = self.scratch / "install"
        outside = self.scratch / "outside"
        outside_binary = outside / "opentunnel-linux-arm64/opentunnel"
        outside_binary.parent.mkdir(parents=True)
        outside_binary.write_bytes(b"outside root")
        outside_binary.chmod(0o755)
        version_root = root / "runtime/opentunnel/v0.6.2"
        version_root.mkdir(parents=True)
        (version_root / "opentunnel-linux-arm64").symlink_to(
            outside_binary.parent,
            target_is_directory=True,
        )

        result = resolve_companion(
            root,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(result.reason, "symlink_component")
        self.assertIsNone(result.path)

    def test_rejects_install_root_inside_virtual_environment(self) -> None:
        for environment_name in (".venv", "venv"):
            with self.subTest(environment=environment_name):
                root, _binary = self._install_binary(
                    install_root=self.scratch / environment_name / "install"
                )
                result = resolve_companion(
                    root,
                    _PLATFORM_MANIFEST,
                    system="Linux",
                    machine="arm64",
                )
                self.assertEqual(result.state, "unsafe_path")
                self.assertEqual(result.reason, "venv_placement")
                self.assertIsNone(result.path)

    def test_rejects_directory_and_non_executable_file(self) -> None:
        root = self.scratch / "directory-install"
        binary = root / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64/opentunnel"
        binary.mkdir(parents=True)
        result = resolve_companion(
            root,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(result.reason, "not_regular_file")

        root, _binary = self._install_binary(executable=False)
        non_executable = resolve_companion(
            root,
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertEqual(non_executable.state, "unsafe_path")
        self.assertEqual(non_executable.reason, "not_executable")

    def test_path_poisoning_does_not_change_install_relative_resolution(self) -> None:
        root, binary = self._install_binary()
        fake_path = self.scratch / "fake-bin"
        fake_path.mkdir()
        fake_binary = fake_path / "opentunnel"
        fake_binary.write_text("fake path executable", encoding="ascii")
        fake_binary.chmod(0o755)

        with mock.patch.dict(os.environ, {"PATH": str(fake_path)}):
            result = resolve_companion(
                root,
                _PLATFORM_MANIFEST,
                system="Linux",
                machine="arm64",
            )
        self.assertEqual(result.state, "resolved")
        self.assertEqual(result.path, binary.resolve())
        self.assertNotEqual(result.path, fake_binary.resolve())

    def test_resolution_performs_no_network_or_subprocess_activity(self) -> None:
        root, _binary = self._install_binary()
        with (
            mock.patch.object(socket, "socket", side_effect=AssertionError("socket used")),
            mock.patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network used"),
            ),
            mock.patch.object(
                subprocess,
                "Popen",
                side_effect=AssertionError("subprocess used"),
            ),
            mock.patch.object(
                subprocess,
                "run",
                side_effect=AssertionError("subprocess used"),
            ),
        ):
            result = resolve_companion(
                root,
                _PLATFORM_MANIFEST,
                system="Linux",
                machine="arm64",
            )
        self.assertEqual(result.state, "resolved")

    def test_companion_digest_helper_matches_and_rejects_mismatches(self) -> None:
        path = self.scratch / "digest-fixture"
        body = b"companion bytes"
        path.write_bytes(body)
        expected = hashlib.sha256(body).hexdigest()
        self.assertTrue(verify_companion_digest(path, expected))
        self.assertFalse(verify_companion_digest(path, hashlib.sha256(b"other").hexdigest()))
        self.assertFalse(verify_companion_digest(path, "A" * 64))
        self.assertFalse(verify_companion_digest(self.scratch / "missing", expected))

    def test_companion_digest_helper_reads_only_bounded_chunks(self) -> None:
        path = self.scratch / "large-digest-fixture"
        body = b"x" * (DIGEST_CHUNK_SIZE * 2 + 17)
        path.write_bytes(body)
        expected = hashlib.sha256(body).hexdigest()
        original_open = Path.open
        observed_sizes: list[int] = []

        class ReadSpy:
            def __init__(self, stream: object) -> None:
                self._stream = stream

            def __enter__(self) -> "ReadSpy":
                self._stream.__enter__()  # type: ignore[attr-defined]
                return self

            def __exit__(self, *args: object) -> object:
                return self._stream.__exit__(*args)  # type: ignore[attr-defined]

            def read(self, size: int = -1) -> bytes:
                observed_sizes.append(size)
                self.assert_bounded(size)
                return self._stream.read(size)  # type: ignore[attr-defined,no-any-return]

            @staticmethod
            def assert_bounded(size: int) -> None:
                if size < 0 or size > DIGEST_CHUNK_SIZE:
                    raise AssertionError("digest helper requested an unbounded read")

        def tracked_open(
            path_arg: Path,
            mode: str = "r",
            buffering: int = -1,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> object:
            stream = original_open(
                path_arg,
                mode,
                buffering,
                encoding,
                errors,
                newline,
            )
            return ReadSpy(stream) if mode == "rb" else stream

        with mock.patch.object(Path, "open", tracked_open):
            self.assertTrue(verify_companion_digest(path, expected))
        self.assertGreaterEqual(len(observed_sizes), 3)
        self.assertTrue(all(size == DIGEST_CHUNK_SIZE for size in observed_sizes))

    def test_source_has_no_network_or_process_imports_or_path_lookup(self) -> None:
        source = _SOURCE_PATH.read_text(encoding="ascii")
        tree = ast.parse(source)
        forbidden = {"subprocess", "shutil", "urllib", "socket", "requests"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertTrue(imported.isdisjoint(forbidden))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "shutil"
                and node.func.attr == "which"
            ):
                self.fail("companion resolver must not call shutil.which")

    def test_failure_results_never_include_paths_or_digests(self) -> None:
        result = resolve_companion(
            self.scratch / "secret-install-path",
            _PLATFORM_MANIFEST,
            system="Linux",
            machine="arm64",
        )
        self.assertIsInstance(result, CompanionResolution)
        self.assertIsNone(result.path)
        self.assertIsNone(result.expected_sha256)
        self.assertLessEqual(len(result.reason), 40)
        self.assertNotIn("secret-install-path", result.reason)


if __name__ == "__main__":
    unittest.main()
