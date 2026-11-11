# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the pinned OpenTunnel v0.6.2 source manifest."""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.network_packaging.manifest import ManifestError, load_pinned_manifest
from web.extensions.opentunnel_sharing.companion import resolve_companion

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _ROOT / "packaging/opentunnel-v0.6.2.manifest.json"
_COMMIT = "1ad859e17924ec3f6741cbc4cdb54ce381c9007c"
_SHA256SUMS_DIGEST = "1b2e3d3f4aeec8526678fbeec46075b9ec6fe484dc6c3328514ed4205b5d55c6"
_PLATFORM_PINS = {
    "darwin-arm64": {
        "os": "darwin",
        "arch": "arm64",
        "asset_name": "opentunnel-darwin-arm64.tar.gz",
        "asset_stem": "opentunnel-darwin-arm64",
        "archive_size_bytes": 2743327,
        "archive_sha256": "3f4cf4d316db0e341b2995fd5cd44ba79a78aaee534f32199969152397c9e504",
        "executable_size_bytes": 5511264,
        "sha256": "39991ec74bc79e13917d5e7bc309870f7925d364808b33ec535fef2fc29eeaf8",
        "runtime_path": (
            "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
        ),
    },
    "linux-arm64": {
        "os": "linux",
        "arch": "arm64",
        "asset_name": "opentunnel-linux-arm64.tar.gz",
        "asset_stem": "opentunnel-linux-arm64",
        "archive_size_bytes": 2905242,
        "archive_sha256": "3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293",
        "executable_size_bytes": 5716056,
        "sha256": "7876ca698377c11b56781e5577258aa6b73ae763a062fbcdebfa14df2d9edac1",
        "runtime_path": "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64/opentunnel",
    },
}
_TOP_LEVEL_KEYS = {
    "version",
    "upstream_tag",
    "upstream_commit",
    "release_url",
    "sha256sums_provenance",
    "license_notice",
    "platforms",
}


class NetworkPackageManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)

    def _read_source_document(self) -> dict[str, Any]:
        with _MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def _write_document(self, document: dict[str, Any]) -> Path:
        path = self.scratch / "manifest.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def _assert_invalid(self, document: dict[str, Any]) -> None:
        with self.assertRaises(ManifestError):
            load_pinned_manifest(self._write_document(document))

    def test_committed_manifest_has_exact_schema_and_n0_pins(self) -> None:
        manifest = load_pinned_manifest(_MANIFEST_PATH)
        source = self._read_source_document()

        self.assertEqual(set(source), _TOP_LEVEL_KEYS)
        self.assertEqual(manifest.version, "0.6.2")
        self.assertEqual(manifest.upstream_tag, "v0.6.2")
        self.assertEqual(manifest.upstream_commit, _COMMIT)
        self.assertEqual(
            manifest.release_url,
            "https://github.com/anomalyco/opentunnel/releases/download/v0.6.2",
        )
        self.assertEqual(
            source["sha256sums_provenance"],
            {
                "url": manifest.release_url + "/SHA256SUMS",
                "sha256": _SHA256SUMS_DIGEST,
                "size_bytes": 382,
                "source": "N0 local cache: tmp/n0/release/SHA256SUMS",
            },
        )
        self.assertEqual(manifest.license_notice.spdx_id, "MIT")
        self.assertEqual(
            manifest.license_notice.text_pointer,
            "https://opensource.org/license/mit/",
        )
        self.assertEqual(
            set(manifest.platforms), {"darwin-arm64", "linux-arm64"}
        )
        self.assertEqual(len(source["platforms"]), 2)
        for platform_key, expected in _PLATFORM_PINS.items():
            with self.subTest(platform=platform_key):
                self.assertEqual(source["platforms"][list(_PLATFORM_PINS).index(platform_key)], expected)
                actual = manifest.platforms[platform_key]
                for field, expected_value in expected.items():
                    self.assertEqual(getattr(actual, field), expected_value)

    def test_duplicate_json_keys_are_rejected_at_any_object_level(self) -> None:
        source = _MANIFEST_PATH.read_text(encoding="utf-8")
        duplicate_documents = (
            source.replace(
                '"version": "0.6.2",',
                '"version": "0.6.2",\n  "version": "0.6.2",',
                1,
            ),
            source.replace(
                '"spdx_id": "MIT",',
                '"spdx_id": "MIT",\n    "spdx_id": "MIT",',
                1,
            ),
        )
        for index, duplicate in enumerate(duplicate_documents):
            with self.subTest(level=index):
                path = self.scratch / ("duplicate-%d.json" % index)
                path.write_text(duplicate, encoding="utf-8")
                with self.assertRaises(ManifestError):
                    load_pinned_manifest(path)

    def test_missing_and_extra_top_level_keys_are_rejected(self) -> None:
        missing = self._read_source_document()
        del missing["version"]
        self._assert_invalid(missing)

        extra = self._read_source_document()
        extra["comment"] = "not part of the schema"
        self._assert_invalid(extra)

    def test_malformed_digests_and_size_types_are_rejected(self) -> None:
        for field, value in (
            ("archive_sha256", "A" * 64),
            ("archive_sha256", "a" * 63),
            ("sha256", "g" * 64),
            ("sha256", 1),
        ):
            document = self._read_source_document()
            document["platforms"][0][field] = value
            with self.subTest(field=field, value=str(value)[:8]):
                self._assert_invalid(document)

        document = self._read_source_document()
        document["platforms"][0]["archive_size_bytes"] = True
        self._assert_invalid(document)

    def test_only_the_two_approved_platform_pairs_are_accepted(self) -> None:
        for os_name, arch in (
            ("darwin", "x64"),
            ("linux", "x64"),
            ("windows", "arm64"),
        ):
            document = self._read_source_document()
            document["platforms"][0]["os"] = os_name
            document["platforms"][0]["arch"] = arch
            with self.subTest(os=os_name, arch=arch):
                self._assert_invalid(document)

        document = self._read_source_document()
        document["platforms"].append(dict(document["platforms"][0]))
        self._assert_invalid(document)

    def test_bad_urls_asset_names_and_runtime_paths_are_rejected(self) -> None:
        for url in (
            "http://github.com/anomalyco/opentunnel/releases/download/v0.6.2",
            "https://evil.example/anomalyco/opentunnel/releases/download/v0.6.2",
            "https://github.com/anomalyco/opentunnel/releases/download/v0.6.1",
            "https://github.com/anomalyco/opentunnel/releases/download/v0.6.2?x=1",
            "https://[invalid-host]/anomalyco/opentunnel/releases/download/v0.6.2",
        ):
            document = self._read_source_document()
            document["release_url"] = url
            with self.subTest(url=url):
                self._assert_invalid(document)

        document = self._read_source_document()
        document["platforms"][0]["asset_name"] = "../opentunnel-darwin-arm64.tar.gz"
        self._assert_invalid(document)

        document = self._read_source_document()
        document["platforms"][0]["asset_stem"] = "opentunnel-darwin-x64"
        self._assert_invalid(document)

        document = self._read_source_document()
        document["platforms"][0]["runtime_path"] = "../../outside/opentunnel"
        self._assert_invalid(document)

    def test_checksum_and_license_provenance_are_exactly_shaped(self) -> None:
        document = self._read_source_document()
        document["sha256sums_provenance"]["extra"] = True
        self._assert_invalid(document)

        document = self._read_source_document()
        document["sha256sums_provenance"]["sha256"] = "B" * 64
        self._assert_invalid(document)

        document = self._read_source_document()
        document["sha256sums_provenance"]["url"] = "https://evil.example/SHA256SUMS"
        self._assert_invalid(document)

        document = self._read_source_document()
        document["license_notice"]["spdx_id"] = "Apache-2.0"
        self._assert_invalid(document)

        document = self._read_source_document()
        document["license_notice"]["notice"] = "Different license notice"
        self._assert_invalid(document)

    def test_manifest_asset_stems_resolve_through_existing_companion_contract(self) -> None:
        manifest = load_pinned_manifest(_MANIFEST_PATH)
        resolver_manifest = {
            platform_key: {
                "asset_stem": pin.asset_stem,
                "sha256": pin.sha256,
            }
            for platform_key, pin in manifest.platforms.items()
        }

        for platform_key, pin in manifest.platforms.items():
            with self.subTest(platform=platform_key):
                install_root = self.scratch / platform_key
                executable = install_root / pin.runtime_path
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_bytes(b"offline companion fixture")
                executable.chmod(0o755)
                system = "Darwin" if pin.os == "darwin" else "Linux"
                result = resolve_companion(
                    install_root,
                    resolver_manifest,
                    system=system,
                    machine="arm64",
                )
                self.assertEqual(result.state, "resolved")
                self.assertEqual(result.path, executable.resolve())
                self.assertEqual(result.expected_sha256, pin.sha256)

    def test_runtime_is_ignored_but_source_manifest_is_not(self) -> None:
        runtime_result = subprocess.run(
            [
                "git",
                "check-ignore",
                "-v",
                "runtime/opentunnel/v0.6.2/manifest.json",
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(runtime_result.returncode, 0, runtime_result.stderr)
        self.assertIn("/runtime/", runtime_result.stdout)

        source_result = subprocess.run(
            ["git", "check-ignore", "-v", "packaging/opentunnel-v0.6.2.manifest.json"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(source_result.returncode, 1, source_result.stdout)
        self.assertEqual(source_result.stdout, "")

    def test_manifest_reader_and_tests_do_not_import_network_clients(self) -> None:
        forbidden_imports = {"requests", "httpx", "socket", "urllib.request"}
        for path in (
            _ROOT / "scripts/network_packaging/manifest.py",
            Path(__file__).resolve(),
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported.add(node.module)
            self.assertFalse(
                forbidden_imports.intersection(imported),
                "%s imports a network client" % path,
            )


if __name__ == "__main__":
    unittest.main()
