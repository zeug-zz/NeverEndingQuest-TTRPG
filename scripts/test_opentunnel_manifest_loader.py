# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline security tests for the OpenTunnel runtime manifest."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.network_packaging.manifest import load_pinned_manifest
from web.extensions.opentunnel_sharing import runtime_manifest
from web.extensions.opentunnel_sharing.companion import (
    CompanionResolution,
    resolve_companion,
)
from web.extensions.opentunnel_sharing.runtime_manifest import (
    MAX_RUNTIME_MANIFEST_BYTES,
    ManifestError,
    load_companion_manifest,
    write_runtime_manifest,
)
from web.extensions.opentunnel_sharing.service import (
    _ProductionComposition,
    create_production_player_sharing_service,
    load_companion_manifest as load_service_companion_manifest,
)

_ROOT = Path(__file__).resolve().parents[1]
_PINNED_MANIFEST = _ROOT / "packaging/opentunnel-v0.6.2.manifest.json"
_PLATFORMS = {
    "darwin-arm64": "opentunnel-darwin-arm64",
    "linux-arm64": "opentunnel-linux-arm64",
}
_IDENTITIES = {
    "darwin-arm64": ("Darwin", "arm64"),
    "linux-arm64": ("Linux", "aarch64"),
}


class OpenTunnelRuntimeManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)
        self.pinned_manifest = load_pinned_manifest(_PINNED_MANIFEST)

    def _root(self, name: str = "install") -> Path:
        root = self.scratch / name
        root.mkdir()
        return root

    def _manifest_path(self, root: Path) -> Path:
        directory = root / "runtime/opentunnel/v0.6.2"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "manifest.json"

    def _document(
        self,
        platforms: dict[str, dict[str, str]] | None = None,
        *,
        schema: str = runtime_manifest.RUNTIME_MANIFEST_SCHEMA,
        version: str = runtime_manifest.RUNTIME_MANIFEST_VERSION,
    ) -> dict[str, object]:
        selected = platforms or {
            "linux-arm64": {
                "asset_stem": _PLATFORMS["linux-arm64"],
                "sha256": "a" * 64,
            }
        }
        return {"schema": schema, "version": version, "platforms": selected}

    def _write(self, root: Path, content: bytes, *, mode: int = 0o644) -> Path:
        path = self._manifest_path(root)
        path.write_bytes(content)
        path.chmod(mode)
        return path

    def _assert_invalid(self, content: bytes, *, mode: int = 0o644) -> None:
        root = self._root("invalid-%d" % len(list(self.scratch.iterdir())))
        self._write(root, content, mode=mode)
        with self.assertRaises(ManifestError) as raised:
            load_companion_manifest(root)
        self.assertEqual(raised.exception.reason, "invalid_manifest")
        self.assertLessEqual(len(str(raised.exception)), 32)

    def test_reads_strict_single_platform_mapping_and_service_export(self) -> None:
        root = self._root()
        content = json.dumps(self._document(), separators=(",", ":")).encode("ascii")
        self._write(root, content)

        loaded = load_companion_manifest(root)

        self.assertEqual(
            dict(loaded),
            {
                "linux-arm64": {
                    "asset_stem": "opentunnel-linux-arm64",
                    "sha256": "a" * 64,
                }
            },
        )
        self.assertEqual(dict(load_service_companion_manifest(root)), dict(loaded))
        with self.assertRaises(TypeError):
            loaded["linux-arm64"] = {}  # type: ignore[index]

    def test_rejects_missing_extra_and_invalid_schema_fields(self) -> None:
        document = self._document()
        for label, changed in (
            ("missing top-level", {key: value for key, value in document.items() if key != "schema"}),
            ("extra top-level", {**document, "unexpected": True}),
            (
                "missing platform field",
                self._document({"linux-arm64": {"asset_stem": _PLATFORMS["linux-arm64"]}}),
            ),
            (
                "extra platform field",
                self._document(
                    {
                        "linux-arm64": {
                            "asset_stem": _PLATFORMS["linux-arm64"],
                            "sha256": "a" * 64,
                            "extra": "value",
                        }
                    }
                ),
            ),
        ):
            with self.subTest(case=label):
                self._assert_invalid(json.dumps(changed).encode("ascii"))

    def test_rejects_duplicate_json_keys(self) -> None:
        duplicate = (
            '{"schema":"%s","schema":"%s","version":"0.6.2",'
            '"platforms":{"linux-arm64":{"asset_stem":"opentunnel-linux-arm64",'
            '"sha256":"%s"}}}'
            % (
                runtime_manifest.RUNTIME_MANIFEST_SCHEMA,
                runtime_manifest.RUNTIME_MANIFEST_SCHEMA,
                "a" * 64,
            )
        )
        self._assert_invalid(duplicate.encode("ascii"))

    def test_rejects_digest_platform_and_asset_stem_violations(self) -> None:
        invalid_entries = (
            {
                "asset_stem": _PLATFORMS["linux-arm64"],
                "sha256": "A" * 64,
            },
            {
                "asset_stem": _PLATFORMS["linux-arm64"],
                "sha256": "a" * 63,
            },
            {
                "asset_stem": "../outside",
                "sha256": "a" * 64,
            },
            {
                "asset_stem": _PLATFORMS["darwin-arm64"],
                "sha256": "a" * 64,
            },
        )
        for index, entry in enumerate(invalid_entries):
            with self.subTest(entry=index):
                self._assert_invalid(
                    json.dumps(self._document({"linux-arm64": entry})).encode("ascii")
                )
        self._assert_invalid(
            json.dumps(
                self._document(
                    {
                        "windows-arm64": {
                            "asset_stem": "opentunnel-linux-arm64",
                            "sha256": "a" * 64,
                        }
                    }
                )
            ).encode("ascii")
        )

    def test_rejects_wrong_schema_version_non_object_and_non_json_constants(self) -> None:
        cases = (
            json.dumps(self._document(schema="wrong.schema")).encode("ascii"),
            json.dumps(self._document(version="0.6.3")).encode("ascii"),
            b"[]",
            b"null",
            b'{"schema":NaN}',
        )
        for index, content in enumerate(cases):
            with self.subTest(case=index):
                self._assert_invalid(content)

    def test_missing_manifest_is_distinct_and_uninstalled_service_is_missing_asset(self) -> None:
        root = self._root()
        with self.assertRaises(ManifestError) as raised:
            load_companion_manifest(root)
        self.assertEqual(raised.exception.reason, "manifest_missing")

        composition = _ProductionComposition(
            object(),  # type: ignore[arg-type]
            lambda: True,
            companion_manifest=None,
            install_root=root,
            state_root=root / "state",
            state_root_provider=None,
            install_marker=None,
            profile="neq-share",
            player_build_root=None,
        )
        resolution = composition._resolve_companion()
        self.assertEqual(resolution.state, "missing_asset")
        self.assertEqual(resolution.reason, "manifest_missing")

        self._write(root, b"{}")
        corrupt_resolution = composition._resolve_companion()
        self.assertEqual(corrupt_resolution.state, "invalid_manifest")
        self.assertEqual(corrupt_resolution.reason, "invalid_manifest")

    def test_construction_is_lazy_offline_and_explicit_injection_wins(self) -> None:
        root = self._root()
        with mock.patch(
            "web.extensions.opentunnel_sharing.service.load_companion_manifest",
            side_effect=AssertionError("construction must not read the manifest"),
        ) as reader:
            service = create_production_player_sharing_service(
                gateway=object(),  # type: ignore[arg-type]
                local_runtime_check=lambda: True,
                install_root=root,
                state_root=root / "state",
            )
        reader.assert_not_called()
        self.assertFalse((root / "runtime").exists())
        missing_resolution = service._deps.resolve_companion()
        self.assertEqual(missing_resolution.state, "missing_asset")
        self.assertEqual(missing_resolution.reason, "manifest_missing")
        self.assertFalse((root / "runtime").exists())

        injected = {
            "linux-arm64": {
                "asset_stem": "opentunnel-linux-arm64",
                "sha256": hashlib.sha256(b"injected executable").hexdigest(),
            }
        }
        with mock.patch(
            "web.extensions.opentunnel_sharing.service.load_companion_manifest",
            side_effect=AssertionError("explicit injection must take precedence"),
        ) as reader:
            with mock.patch(
                "web.extensions.opentunnel_sharing.service.resolve_companion",
                return_value=CompanionResolution("resolved", "resolved"),
            ) as resolver:
                injected_composition = _ProductionComposition(
                    object(),  # type: ignore[arg-type]
                    lambda: True,
                    companion_manifest=injected,
                    install_root=root,
                    state_root=root / "state",
                    state_root_provider=None,
                    install_marker=None,
                    profile="neq-share",
                    player_build_root=None,
                )
                resolution = injected_composition._resolve_companion()
        reader.assert_not_called()
        self.assertIs(resolver.call_args.args[1], injected)
        self.assertEqual(resolution.state, "resolved")

    def test_rejects_symlink_manifest_and_manifest_directory_escape(self) -> None:
        root = self._root("symlink-manifest")
        path = self._manifest_path(root)
        target = self.scratch / "outside-manifest.json"
        target.write_bytes(json.dumps(self._document()).encode("ascii"))
        path.symlink_to(target)
        with self.assertRaises(ManifestError):
            load_companion_manifest(root)

        escaped_root = self._root("escaped-install")
        outside_version = self.scratch / "outside-version"
        outside_version.mkdir()
        (outside_version / "manifest.json").write_bytes(
            json.dumps(self._document()).encode("ascii")
        )
        (escaped_root / "runtime/opentunnel").mkdir(parents=True)
        (escaped_root / "runtime/opentunnel/v0.6.2").symlink_to(
            outside_version, target_is_directory=True
        )
        with self.assertRaises(ManifestError):
            load_companion_manifest(escaped_root)

    def test_rejects_virtual_environment_roots_wrong_owner_writable_and_oversize(self) -> None:
        for index, directory_name in enumerate((".venv", "venv")):
            with self.subTest(environment=directory_name):
                root = self.scratch / directory_name / ("install-%d" % index)
                root.mkdir(parents=True)
                self._write(
                    root,
                    json.dumps(self._document()).encode("ascii"),
                )
                with self.assertRaises(ManifestError):
                    load_companion_manifest(root)

        root = self._root("world-writable")
        content = json.dumps(self._document()).encode("ascii")
        self._write(root, content, mode=0o666)
        with self.assertRaises(ManifestError):
            load_companion_manifest(root)

        owner_root = self._root("wrong-owner")
        self._write(owner_root, content)
        with mock.patch.object(runtime_manifest.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ManifestError):
                load_companion_manifest(owner_root)

        oversized_root = self._root("oversized")
        oversized = content + b" " * (MAX_RUNTIME_MANIFEST_BYTES + 1)
        self._write(oversized_root, oversized)
        with self.assertRaises(ManifestError):
            load_companion_manifest(oversized_root)

    def test_writer_round_trip_resolves_both_approved_platforms_and_merges(self) -> None:
        root = self._root()
        binaries: dict[str, Path] = {}
        for key, stem in _PLATFORMS.items():
            binary = root / "runtime/opentunnel/v0.6.2" / stem / "opentunnel"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(("fixture-" + key).encode("ascii"))
            binary.chmod(0o755)
            binaries[key] = binary
            write_runtime_manifest(root, self.pinned_manifest, key)

        loaded = load_companion_manifest(root)
        self.assertEqual(set(loaded), set(_PLATFORMS))
        for key, (system, machine) in _IDENTITIES.items():
            with self.subTest(platform=key):
                pin = self.pinned_manifest.platforms[key]
                self.assertEqual(loaded[key]["asset_stem"], pin.asset_stem)
                self.assertEqual(loaded[key]["sha256"], pin.sha256)
                resolution = resolve_companion(
                    root,
                    loaded,
                    system=system,
                    machine=machine,
                )
                self.assertEqual(resolution.state, "resolved")
                self.assertEqual(resolution.path, binaries[key].resolve())

        metadata = (root / "runtime/opentunnel/v0.6.2/manifest.json").lstat()
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o644)

    def test_writer_failure_leaves_original_manifest_and_no_temporary_file(self) -> None:
        root = self._root()
        original = json.dumps(self._document(), separators=(",", ":")).encode("ascii")
        path = self._write(root, original)

        with mock.patch.object(runtime_manifest.os, "replace", side_effect=OSError("test failure")):
            with self.assertRaises(ManifestError):
                write_runtime_manifest(root, self.pinned_manifest, "darwin-arm64")

        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob(".manifest.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
