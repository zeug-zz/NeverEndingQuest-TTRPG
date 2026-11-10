# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Filesystem-isolated tests for the private OpenTunnel profile layout."""

from __future__ import annotations

import ast
import builtins
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing import profile_state
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    PROFILE_OWNER_FILENAME,
    PROFILE_OWNER_SCHEMA,
    ProfileLayout,
    companion_environment,
    default_state_root,
    prepare_profile,
)


class OpenTunnelProfileStateTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)
        self.fake_repository = self.scratch / "install-root"
        self.fake_repository.mkdir(mode=0o700)
        self.state_root = self.scratch / "s"

    def _prepare(
        self,
        *,
        state_root: Path | None = None,
        profile: str = DEFAULT_PROFILE,
        install_marker: str = "install-marker-1",
        create: bool = True,
    ) -> profile_state.ProfileState:
        with (
            mock.patch.object(
                profile_state, "_REPOSITORY_ROOT", self.fake_repository
            ),
            mock.patch.object(profile_state, "_INSTALL_ROOT", self.fake_repository),
        ):
            return prepare_profile(
                self.state_root if state_root is None else state_root,
                install_marker=install_marker,
                profile=profile,
                create=create,
            )

    @staticmethod
    def _mkdir_private(path: Path) -> None:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _mode(path: Path) -> int:
        return stat.S_IMODE(path.lstat().st_mode)

    def test_fresh_profile_is_private_and_has_exact_owner_metadata(self) -> None:
        result = self._prepare()
        self.assertEqual((result.state, result.reason), ("ready", "ready"))
        self.assertIsInstance(result.layout, ProfileLayout)
        assert result.layout is not None

        expected_dirs = (
            self.state_root,
            self.state_root / "neq",
            self.state_root / "neq/opentunnel",
            result.layout.profile_root,
            result.layout.config_home,
            result.layout.data_home,
            result.layout.state_home,
            result.layout.runtime_dir,
            result.layout.verifier_dir,
        )
        for directory in expected_dirs:
            with self.subTest(directory=directory.name):
                metadata = directory.lstat()
                self.assertTrue(stat.S_ISDIR(metadata.st_mode))
                self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o700)
                self.assertEqual(metadata.st_uid, os.getuid())

        owner_metadata = result.layout.owner_file.lstat()
        self.assertTrue(stat.S_ISREG(owner_metadata.st_mode))
        self.assertEqual(stat.S_IMODE(owner_metadata.st_mode), 0o600)
        self.assertEqual(owner_metadata.st_uid, os.getuid())
        owner = json.loads(result.layout.owner_file.read_text(encoding="ascii"))
        self.assertEqual(
            set(owner),
            {"schema", "profile", "created_at", "neq_install_marker", "uid"},
        )
        self.assertEqual(owner["schema"], PROFILE_OWNER_SCHEMA)
        self.assertEqual(owner["profile"], DEFAULT_PROFILE)
        self.assertEqual(owner["neq_install_marker"], "install-marker-1")
        self.assertEqual(owner["uid"], os.getuid())
        self.assertTrue(owner["created_at"].endswith("Z"))
        self.assertFalse(
            {"password", "secret", "token", "url", "tunnel_id"}.intersection(owner)
        )
        self.assertTrue(
            result.layout.socket_path.as_posix().startswith(
                result.layout.profile_root.as_posix() + "/"
            )
        )

    def test_second_prepare_is_idempotent_and_create_false_does_not_change_files(self) -> None:
        first = self._prepare()
        self.assertEqual(first.state, "ready")
        assert first.layout is not None
        owner_bytes = first.layout.owner_file.read_bytes()
        owner_stat = first.layout.owner_file.lstat()

        second = self._prepare()
        self.assertEqual(second.state, "ready")
        assert second.layout is not None
        self.assertEqual(second.layout.owner_file.read_bytes(), owner_bytes)
        self.assertEqual(second.layout.owner_file.lstat().st_ino, owner_stat.st_ino)

        snapshot = self._filesystem_snapshot(second.layout.profile_root)
        check_only = self._prepare(create=False)
        self.assertEqual(check_only.state, "ready")
        self.assertEqual(
            self._filesystem_snapshot(second.layout.profile_root), snapshot
        )

    def test_create_false_absent_does_not_create_anything(self) -> None:
        absent_root = self.scratch / "s2"
        before = self._filesystem_snapshot(self.scratch)
        result = self._prepare(state_root=absent_root, create=False)
        self.assertEqual(result.state, "absent")
        self.assertFalse(absent_root.exists())
        self.assertEqual(self._filesystem_snapshot(self.scratch), before)

    def test_existing_wrong_mode_directory_is_rejected_without_repair(self) -> None:
        self.state_root.mkdir(mode=0o700)
        self.state_root.chmod(0o750)
        result = self._prepare()
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(self._mode(self.state_root), 0o750)
        self.assertFalse((self.state_root / "neq").exists())

    def test_rejects_symlinked_state_root_profile_and_subdirectory(self) -> None:
        target = self.scratch / "root-target"
        target.mkdir(mode=0o700)
        symlink_root = self.scratch / "root-link"
        symlink_root.symlink_to(target, target_is_directory=True)
        symlink_result = self._prepare(state_root=symlink_root)
        self.assertEqual(symlink_result.state, "unsafe_path")
        self.assertEqual(list(target.iterdir()), [])

        base_root = self.scratch / "p"
        base_root.mkdir(mode=0o700)
        self._mkdir_private(base_root / "neq")
        self._mkdir_private(base_root / "neq/opentunnel")
        outside_profile = self.scratch / "outside-profile"
        outside_profile.mkdir(mode=0o700)
        profile_link = base_root / "neq/opentunnel" / DEFAULT_PROFILE
        profile_link.symlink_to(outside_profile, target_is_directory=True)
        profile_result = self._prepare(state_root=base_root)
        self.assertEqual(profile_result.state, "unsafe_path")
        self.assertEqual(list(outside_profile.iterdir()), [])

        valid = self._prepare()
        self.assertEqual(valid.state, "ready")
        assert valid.layout is not None
        config_path = valid.layout.config_home
        config_path.rmdir()
        outside_config = self.scratch / "outside-config"
        outside_config.mkdir(mode=0o700)
        config_path.symlink_to(outside_config, target_is_directory=True)
        subdir_result = self._prepare(create=False)
        self.assertEqual(subdir_result.state, "unsafe_path")
        self.assertEqual(list(outside_config.iterdir()), [])

    def test_rejects_repository_venv_and_campaign_roots_without_creation(self) -> None:
        install_root = Path(profile_state._INSTALL_ROOT)
        candidates = (
            install_root / ".venv" / "opentunnel-state-test",
            install_root / "modules" / "opentunnel-state-test",
            install_root / "characters" / "opentunnel-state-test",
            install_root / "party_tracker.json" / "opentunnel-state-test",
            install_root / "tmp" / "opentunnel-state-test",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                result = prepare_profile(
                    candidate,
                    install_marker="install-marker-1",
                    create=True,
                )
                self.assertEqual(result.state, "unsafe_path")
                self.assertFalse(candidate.exists())

    def test_rejects_bad_slug_and_install_marker(self) -> None:
        for profile in ("", "NEQ", "../other", "bad_slug", "ends-", "x" * 33):
            with self.subTest(profile=profile):
                result = self._prepare(profile=profile)
                self.assertEqual(result.state, "invalid")
                self.assertEqual(result.reason, "profile_slug_invalid")
        result = self._prepare(install_marker="https://example.test/token")
        self.assertEqual(result.state, "invalid")
        self.assertEqual(result.reason, "install_marker_invalid")

    def test_foreign_or_invalid_owner_metadata_is_never_repaired(self) -> None:
        valid = self._prepare()
        self.assertEqual(valid.state, "ready")
        assert valid.layout is not None
        owner_path = valid.layout.owner_file
        original = json.loads(owner_path.read_text(encoding="ascii"))

        variants = (
            ("other_profile", {**original, "profile": "other-profile"}, 0o600),
            ("other_uid", {**original, "uid": os.getuid() + 1000}, 0o600),
            ("wrong_schema", {**original, "schema": "wrong.schema"}, 0o600),
            ("corrupt", None, 0o600),
            ("oversized", None, 0o600),
            ("wrong_mode", original, 0o644),
        )
        for name, value, mode in variants:
            with self.subTest(owner_variant=name):
                if name == "corrupt":
                    owner_path.write_bytes(b"{not-json")
                elif name == "oversized":
                    owner_path.write_bytes(b"x" * (profile_state.MAX_OWNER_FILE_BYTES + 1))
                else:
                    owner_path.write_text(
                        json.dumps(value, sort_keys=True), encoding="ascii"
                    )
                owner_path.chmod(mode)
                before = self._path_snapshot(owner_path)
                result = self._prepare()
                self.assertEqual(result.state, "foreign_or_invalid")
                self.assertLessEqual(len(result.reason), 40)
                self.assertEqual(self._path_snapshot(owner_path), before)
                owner_path.unlink()
                owner_path.write_text(json.dumps(original), encoding="ascii")
                owner_path.chmod(0o600)

        owner_stat = owner_path.lstat()
        self.assertFalse(
            profile_state._owner_metadata_matches(
                owner_path,
                profile=DEFAULT_PROFILE,
                install_marker="install-marker-1",
                uid=os.getuid() + 1000,
                expected_lstat=owner_stat,
            )
        )

        owner_path.unlink()
        external_owner = self.scratch / "external-owner.json"
        external_owner.write_text(json.dumps(original), encoding="ascii")
        external_owner.chmod(0o600)
        owner_path.symlink_to(external_owner)
        link_before = os.lstat(owner_path)
        external_before = self._path_snapshot(external_owner)
        result = self._prepare()
        self.assertEqual(result.state, "foreign_or_invalid")
        self.assertTrue(stat.S_ISLNK(os.lstat(owner_path).st_mode))
        self.assertEqual(os.lstat(owner_path).st_ino, link_before.st_ino)
        self.assertEqual(self._path_snapshot(external_owner), external_before)

    def test_atomic_owner_write_failure_leaves_no_temporary_file(self) -> None:
        with (
            mock.patch.object(
                profile_state.os,
                "replace",
                side_effect=OSError("injected replace failure"),
            ),
            mock.patch.object(
                profile_state, "_REPOSITORY_ROOT", self.fake_repository
            ),
            mock.patch.object(
                profile_state, "_INSTALL_ROOT", self.fake_repository
            ),
        ):
            result = prepare_profile(
                self.state_root,
                install_marker="install-marker-1",
                create=True,
            )
        self.assertEqual(result.state, "invalid")
        profile_root = self.state_root / "neq/opentunnel" / DEFAULT_PROFILE
        self.assertFalse((profile_root / PROFILE_OWNER_FILENAME).exists())
        self.assertFalse(any(profile_root.glob(".profile_owner.*.tmp")))

    def test_unix_socket_path_limit_fails_closed_without_fallback(self) -> None:
        parent = self.scratch / ("a" * 44)
        parent.mkdir(mode=0o700)
        long_root = parent / ("b" * 42)
        result = self._prepare(state_root=long_root)
        self.assertEqual(result.state, "unsafe_path")
        self.assertEqual(result.reason, "runtime_socket_path_too_long")
        self.assertFalse(long_root.exists())

    def test_companion_environment_contains_only_isolated_home_and_xdg_paths(self) -> None:
        result = self._prepare()
        self.assertEqual(result.state, "ready")
        assert result.layout is not None
        environment = companion_environment(result.layout)
        self.assertEqual(
            set(environment),
            {
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR",
            },
        )
        self.assertNotIn("PATH", environment)
        self.assertNotIn("API_KEY", environment)
        self.assertEqual(environment["HOME"], str(result.layout.data_home))
        self.assertEqual(environment["XDG_DATA_HOME"], str(result.layout.data_home))

    def test_default_state_root_uses_xdg_and_rejects_protected_locations(self) -> None:
        xdg_state = self.scratch / "custom-state"
        xdg_data = self.scratch / "custom-data"
        home = self.scratch / "user-home"
        with (
            mock.patch.object(profile_state, "_REPOSITORY_ROOT", self.fake_repository),
            mock.patch.object(profile_state, "_INSTALL_ROOT", self.fake_repository),
        ):
            self.assertEqual(
                default_state_root({"XDG_STATE_HOME": str(xdg_state)}), xdg_state
            )
            self.assertEqual(
                default_state_root({"XDG_DATA_HOME": str(xdg_data)}),
                xdg_data.parent / "state",
            )
            self.assertEqual(default_state_root({}, home=home), home / ".local/state")
        with self.assertRaisesRegex(ValueError, "unsafe_state_root"):
            default_state_root(
                {"XDG_STATE_HOME": str(Path(profile_state._INSTALL_ROOT) / "modules")}
            )
        with self.assertRaisesRegex(ValueError, "unsafe_state_root"):
            default_state_root({"XDG_STATE_HOME": "relative/state"})

    def test_unrelated_profile_and_repository_campaign_sentinels_are_not_accessed(self) -> None:
        for directory in (
            self.state_root,
            self.state_root / "neq",
            self.state_root / "neq/opentunnel",
        ):
            self._mkdir_private(directory)
        unrelated = self.state_root / "neq/opentunnel/unrelated-profile"
        self._mkdir_private(unrelated)
        unrelated_sentinel = unrelated / "private-sentinel"
        unrelated_sentinel.write_text("unrelated profile secret", encoding="ascii")
        unrelated_sentinel.chmod(0o600)

        campaign_root = self.fake_repository / "modules"
        characters_root = self.fake_repository / "characters"
        campaign_root.mkdir(mode=0o700)
        characters_root.mkdir(mode=0o700)
        sentinels = (
            campaign_root / "module_plot.json",
            characters_root / "character.json",
            self.fake_repository / "party_tracker.json",
        )
        for sentinel in sentinels:
            sentinel.write_text("repository campaign sentinel", encoding="ascii")

        watched = (unrelated, unrelated_sentinel, *sentinels)
        before = {str(path): self._path_snapshot(path) for path in watched}
        accesses: list[tuple[str, str]] = []
        original_open = builtins.open
        original_scandir = os.scandir
        original_listdir = os.listdir
        original_stat = os.stat
        original_lstat = os.lstat

        def _path_text(value: object) -> str:
            try:
                return os.path.abspath(os.fspath(value))  # type: ignore[arg-type]
            except TypeError:
                return "<non-path>"

        def tracked_open(file: object, *args: object, **kwargs: object) -> object:
            accesses.append(("open", _path_text(file)))
            return original_open(file, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_scandir(path: object = ".") -> object:
            accesses.append(("scandir", _path_text(path)))
            return original_scandir(path)  # type: ignore[arg-type,return-value]

        def tracked_listdir(path: object = ".") -> list[str]:
            accesses.append(("listdir", _path_text(path)))
            return original_listdir(path)  # type: ignore[arg-type]

        def tracked_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            accesses.append(("stat", _path_text(path)))
            return original_stat(path, *args, **kwargs)  # type: ignore[arg-type]

        def tracked_lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            accesses.append(("lstat", _path_text(path)))
            return original_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

        with (
            mock.patch.object(profile_state, "_REPOSITORY_ROOT", self.fake_repository),
            mock.patch.object(profile_state, "_INSTALL_ROOT", self.fake_repository),
            mock.patch.object(builtins, "open", tracked_open),
            mock.patch.object(os, "scandir", tracked_scandir),
            mock.patch.object(os, "listdir", tracked_listdir),
            mock.patch.object(os, "stat", tracked_stat),
            mock.patch.object(os, "lstat", tracked_lstat),
        ):
            result = prepare_profile(
                self.state_root,
                install_marker="install-marker-1",
                create=True,
            )

        self.assertEqual(result.state, "ready")
        watched_paths = {os.path.abspath(os.fspath(path)) for path in watched}
        forbidden_accesses = [
            (operation, path)
            for operation, path in accesses
            if path in watched_paths
            or path.startswith(os.path.abspath(os.fspath(unrelated)) + os.sep)
        ]
        self.assertEqual(forbidden_accesses, [])
        self.assertFalse(any(operation in {"scandir", "listdir"} for operation, _ in accesses))
        for path in watched:
            self.assertEqual(self._path_snapshot(path), before[str(path)])

    def test_invalid_profile_metadata_is_bounded(self) -> None:
        result = self._prepare(install_marker="install-marker-1")
        self.assertEqual(result.state, "ready")
        assert result.layout is not None
        altered = self._prepare(install_marker="another-install")
        self.assertEqual(altered.state, "foreign_or_invalid")
        self.assertLessEqual(len(altered.reason), 40)

    def test_invalid_owner_does_not_cause_missing_profile_dirs_to_be_created(self) -> None:
        result = self._prepare()
        self.assertEqual(result.state, "ready")
        assert result.layout is not None
        result.layout.owner_file.write_text("{}", encoding="ascii")
        config_home = result.layout.config_home
        config_home.rmdir()

        invalid = self._prepare()
        self.assertEqual(invalid.state, "foreign_or_invalid")
        self.assertFalse(config_home.exists())

    def test_module_has_no_process_or_network_imports(self) -> None:
        source_path = Path(profile_state.__file__)
        tree = ast.parse(source_path.read_text(encoding="ascii"))
        forbidden = {"subprocess", "socket", "urllib", "requests", "httpx"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertTrue(imported.isdisjoint(forbidden))

    @staticmethod
    def _path_snapshot(path: Path) -> tuple[int, int, int, bytes | str | None]:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            content: bytes | str | None = os.readlink(path)
        elif stat.S_ISREG(metadata.st_mode):
            content = path.read_bytes()
        else:
            content = None
        return (
            stat.S_IMODE(metadata.st_mode),
            metadata.st_uid,
            metadata.st_mtime_ns,
            content,
        )

    @classmethod
    def _filesystem_snapshot(
        cls, root: Path
    ) -> dict[str, tuple[int, int, int, bytes | str | None]]:
        if not root.exists():
            return {}
        snapshot: dict[str, tuple[int, int, int, bytes | str | None]] = {}
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            snapshot[str(current_path)] = cls._path_snapshot(current_path)
            for name in dirs + files:
                item = current_path / name
                snapshot[str(item)] = cls._path_snapshot(item)
        return snapshot


if __name__ == "__main__":
    unittest.main()
