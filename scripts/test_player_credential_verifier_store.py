# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free filesystem and redaction tests for the N1 verifier store."""

from __future__ import annotations

import ast
import copy
import dataclasses
import io
import json
import logging
import os
import pickle
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing import profile_state, verifier_store
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    ProfileLayout,
    prepare_profile,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    MAX_VERIFIER_FILE_BYTES,
    VERIFIER_FILENAME,
    VERIFIER_SCHEMA,
    IssuedCredential,
    VerifierStoreError,
    issue_credential,
    load_verifier,
    revoke_access,
    rotate_credential,
    verifier_status,
)
from web.extensions.player.auth import PlayerSecurity
from web.extensions.player.limits import MAX_PASSWORD_BYTES


class PlayerCredentialVerifierStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(self._temporary_directory.cleanup)
        self.scratch = Path(self._temporary_directory.name)
        self.fake_install = self.scratch / "install-root"
        self.fake_install.mkdir(mode=0o700)
        self.state_root = self.scratch / "state"
        self._repo_patcher = mock.patch.object(
            profile_state, "_REPOSITORY_ROOT", self.fake_install
        )
        self._install_patcher = mock.patch.object(
            profile_state, "_INSTALL_ROOT", self.fake_install
        )
        self._repo_patcher.start()
        self._install_patcher.start()
        self.addCleanup(self._install_patcher.stop)
        self.addCleanup(self._repo_patcher.stop)
        self.layout = self._prepare_layout()

    def _prepare_layout(self) -> ProfileLayout:
        prepared = prepare_profile(
            self.state_root,
            install_marker="test-install-marker",
            profile=DEFAULT_PROFILE,
            create=True,
        )
        self.assertEqual(prepared.state, "ready")
        self.assertIsNotNone(prepared.layout)
        assert prepared.layout is not None
        return prepared.layout

    def _verifier_path(self) -> Path:
        return self.layout.verifier_dir / VERIFIER_FILENAME

    def _files_below(self, root: Path) -> list[Path]:
        found: list[Path] = []
        for current, _directories, files in os.walk(root, followlinks=False):
            found.extend(Path(current) / name for name in files)
        return found

    def _assert_no_secret_substrings(self, secret: str, root: Path) -> None:
        fragments = [secret[index : index + 8].encode("ascii") for index in range(len(secret) - 7)]
        for path in self._files_below(root):
            if path.is_symlink():
                continue
            contents = path.read_bytes()
            self.assertNotIn(secret.encode("ascii"), contents, msg="credential persisted")
            for fragment in fragments:
                self.assertNotIn(fragment, contents, msg="credential fragment persisted")

    @staticmethod
    def _snapshot(path: Path) -> tuple[int, int, int, int, bytes | str]:
        metadata = os.lstat(path)
        content: bytes | str
        if stat.S_ISLNK(metadata.st_mode):
            content = os.readlink(path)
        else:
            content = path.read_bytes()
        return (
            stat.S_IMODE(metadata.st_mode),
            metadata.st_uid,
            metadata.st_ino,
            metadata.st_mtime_ns,
            content,
        )

    def test_issue_stores_only_verifier_and_n1_accepts_only_revealed_password(self) -> None:
        environment_before = dict(os.environ)
        argv_before = list(sys.argv)
        output = io.StringIO()
        error_output = io.StringIO()
        log_output = io.StringIO()
        handler = logging.StreamHandler(log_output)
        root_logger = logging.getLogger()
        prior_level = root_logger.level
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
        try:
            with (
                mock.patch.object(os, "putenv", side_effect=AssertionError("putenv used")),
                mock.patch.object(
                    subprocess, "Popen", side_effect=AssertionError("subprocess used")
                ),
                mock.patch.object(
                    subprocess, "run", side_effect=AssertionError("subprocess used")
                ),
                mock.patch.object(
                    subprocess, "call", side_effect=AssertionError("subprocess used")
                ),
                mock.patch.object(
                    verifier_store.secrets,
                    "token_urlsafe",
                    wraps=verifier_store.secrets.token_urlsafe,
                ) as token_factory,
                mock.patch("sys.stdout", output),
                mock.patch("sys.stderr", error_output),
            ):
                issued = issue_credential(self.layout)
                token_factory.assert_called_once_with(32)
                credential = issued.reveal()
                loaded_for_logging = load_verifier(self.layout)
                token_factory.assert_called_once_with(32)
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(prior_level)
            handler.close()

        self.assertEqual(dict(os.environ), environment_before)
        self.assertEqual(sys.argv, argv_before)
        self.assertNotIn(credential, repr(os.environ), msg="credential placed in environment")
        self.assertNotIn(credential, repr(sys.argv), msg="credential placed in argv")
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error_output.getvalue(), "")
        self.assertEqual(log_output.getvalue(), "")
        self.assertNotIn(credential, log_output.getvalue(), msg="credential logged")
        logged_verifier = loaded_for_logging.raw_verifier
        self.assertIsNotNone(logged_verifier)
        assert logged_verifier is not None
        self.assertNotIn(logged_verifier, log_output.getvalue(), msg="verifier logged")

        path = self._verifier_path()
        metadata = path.lstat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.getuid())
        record = json.loads(path.read_text(encoding="ascii"))
        self.assertEqual(
            set(record),
            {"schema", "verifier", "issued_at", "generation", "profile"},
        )
        self.assertEqual(record["schema"], VERIFIER_SCHEMA)
        self.assertEqual(record["generation"], 1)
        self.assertEqual(record["profile"], self.layout.profile)
        self.assertNotIn(
            credential.encode("ascii"),
            path.read_bytes(),
            msg="credential persisted",
        )
        self.assertLessEqual(len(credential.encode("ascii")), MAX_PASSWORD_BYTES)
        self._assert_no_secret_substrings(credential, self.scratch)

        loaded = loaded_for_logging
        self.assertEqual(loaded.state, "present")
        self.assertEqual(loaded.raw_verifier, record["verifier"])
        self.assertIsNotNone(loaded.verifier)
        assert loaded.verifier is not None and loaded.raw_verifier is not None
        self.assertTrue(loaded.verifier.verify(credential))
        self.assertFalse(loaded.verifier.verify("wrong player credential"))
        security = PlayerSecurity(lambda: loaded.raw_verifier)
        self.assertTrue(security.verify_password(credential))
        self.assertFalse(security.verify_password("wrong player credential"))
        self.assertNotIn(loaded.raw_verifier, repr(loaded), msg="verifier exposed by repr")
        status = verifier_status(self.layout)
        self.assertEqual((status.generation, status.issued_at), (1, record["issued_at"]))
        self.assertNotIn("verifier", {field.name for field in dataclasses.fields(status)})
        self.assertNotIn(loaded.raw_verifier, repr(status), msg="verifier exposed in status")

        with self.assertRaises(VerifierStoreError) as blocked:
            issue_credential(self.layout)
        self.assertEqual((blocked.exception.state, blocked.exception.reason), ("present", "credential_already_present"))

    def test_issued_credential_is_redacted_nonserializable_and_one_shot(self) -> None:
        secret = "k" * 43
        with mock.patch.object(verifier_store.secrets, "token_urlsafe", return_value=secret):
            issued = issue_credential(self.layout)

        self.assertIsInstance(issued, IssuedCredential)
        for representation in (
            repr(issued),
            str(issued),
            format(issued),
            format(issued, ">80s"),
        ):
            self.assertEqual(representation, "<redacted>")
            self.assertNotIn(secret, representation, msg="credential exposed by representation")
        with self.assertRaises(TypeError):
            vars(issued)
        with self.assertRaises(TypeError):
            pickle.dumps(issued)
        with self.assertRaises(TypeError):
            copy.copy(issued)
        with self.assertRaises(TypeError):
            copy.deepcopy(issued)
        with self.assertRaises(TypeError):
            dataclasses.asdict(issued)
        with self.assertRaises(TypeError):
            json.dumps(issued)

        revealed = issued.reveal()
        self.assertEqual(revealed, secret)
        self.assertIsNone(getattr(issued, "_IssuedCredential__plaintext"))
        with self.assertRaisesRegex(RuntimeError, "credential_already_revealed"):
            issued.reveal()
        self.assertEqual(repr(issued), "<redacted>")

    def test_load_round_trip_and_absent_state_are_bounded(self) -> None:
        absent = load_verifier(self.layout)
        self.assertEqual((absent.state, absent.reason), ("absent", "absent"))
        self.assertIsNone(absent.verifier)
        self.assertIsNone(absent.raw_verifier)
        self.assertIsNone(absent.generation)

        issue_credential(self.layout)
        loaded = load_verifier(self.layout)
        self.assertEqual((loaded.state, loaded.reason), ("present", "present"))
        self.assertIsNotNone(loaded.verifier)
        self.assertIsNotNone(loaded.raw_verifier)
        self.assertEqual(loaded.generation, 1)
        self.assertLessEqual(len(loaded.reason), 40)

    def test_strict_invalid_records_are_not_repaired_or_removed(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        original = json.loads(path.read_text(encoding="ascii"))

        duplicate = (
            '{"schema":"neq.player_verifier.v1","schema":"neq.player_verifier.v1",'
            f'"verifier":{json.dumps(original["verifier"])},'
            f'"issued_at":{json.dumps(original["issued_at"])},'
            f'"generation":{original["generation"]},'
            f'"profile":{json.dumps(original["profile"])}}}'
        ).encode("ascii")
        wrong_type = {**original, "generation": True}
        variants = (
            ("corrupt", b"{not-json"),
            ("duplicate", duplicate),
            ("extra", json.dumps({**original, "extra": 1}).encode("ascii")),
            ("oversize", b"x" * (MAX_VERIFIER_FILE_BYTES + 1)),
            ("schema", json.dumps({**original, "schema": "wrong"}).encode("ascii")),
            ("profile", json.dumps({**original, "profile": "other-profile"}).encode("ascii")),
            ("verifier", json.dumps({**original, "verifier": "not-a-verifier"}).encode("ascii")),
            ("type", json.dumps(wrong_type).encode("ascii")),
        )
        for name, contents in variants:
            with self.subTest(record_variant=name):
                path.write_bytes(contents)
                path.chmod(0o600)
                before = self._snapshot(path)
                loaded = load_verifier(self.layout)
                self.assertEqual(loaded.state, "invalid")
                self.assertLessEqual(len(loaded.reason), 40)
                self.assertEqual(self._snapshot(path), before)

        path.write_bytes(b"{not-json")
        path.chmod(0o600)
        before_issue = self._snapshot(path)
        with self.assertRaises(VerifierStoreError) as blocked:
            issue_credential(self.layout)
        self.assertEqual(blocked.exception.state, "invalid")
        self.assertEqual(self._snapshot(path), before_issue)
        self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

    def test_wrong_mode_symlink_and_foreign_uid_are_unsafe_and_block_issuance(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        path.chmod(0o640)
        before = self._snapshot(path)
        self._assert_unsafe_and_blocked()
        self.assertEqual(self._snapshot(path), before)

        path.chmod(0o600)
        target = self.scratch / "verifier-target"
        target.write_bytes(path.read_bytes())
        target.chmod(0o600)
        target_before = self._snapshot(target)
        path.unlink()
        path.symlink_to(target)
        link_before = self._snapshot(path)
        self._assert_unsafe_and_blocked()
        self.assertEqual(self._snapshot(path), link_before)
        self.assertEqual(self._snapshot(target), target_before)

    def test_injected_foreign_file_uid_is_unsafe_and_untouched(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        before = self._snapshot(path)
        original_fstat = os.fstat

        def foreign_file_owner(descriptor: int) -> os.stat_result:
            metadata = original_fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                return metadata
            values = list(metadata)
            values[4] = os.getuid() + 1000
            return os.stat_result(values)

        with mock.patch.object(verifier_store.os, "fstat", side_effect=foreign_file_owner):
            self._assert_unsafe_and_blocked()
        self.assertEqual(self._snapshot(path), before)

    def _assert_unsafe_and_blocked(self) -> None:
        loaded = load_verifier(self.layout)
        self.assertEqual(loaded.state, "unsafe")
        self.assertLessEqual(len(loaded.reason), 40)
        with self.assertRaises(VerifierStoreError) as blocked:
            issue_credential(self.layout)
        self.assertEqual(blocked.exception.state, "unsafe")

    def test_verifier_directory_mode_or_symlink_is_unsafe_and_untouched(self) -> None:
        directory = self.layout.verifier_dir
        directory.chmod(0o750)
        before_mode = stat.S_IMODE(directory.lstat().st_mode)
        loaded = load_verifier(self.layout)
        self.assertEqual(loaded.state, "unsafe")
        with self.assertRaises(VerifierStoreError) as blocked:
            issue_credential(self.layout)
        self.assertEqual(blocked.exception.state, "unsafe")
        self.assertEqual(stat.S_IMODE(directory.lstat().st_mode), before_mode)

        directory.chmod(0o700)
        directory.rmdir()
        outside = self.scratch / "outside-verifier-dir"
        outside.mkdir(mode=0o700)
        directory.symlink_to(outside, target_is_directory=True)
        link_before = self._snapshot(directory)
        self.assertEqual(load_verifier(self.layout).state, "unsafe")
        with self.assertRaises(VerifierStoreError):
            issue_credential(self.layout)
        self.assertEqual(self._snapshot(directory), link_before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_rotation_revokes_before_replace_and_increments_generation(self) -> None:
        first = issue_credential(self.layout)
        old_password = first.reveal()
        old_bytes = self._verifier_path().read_bytes()
        old_verifier = load_verifier(self.layout).raw_verifier
        events: list[str] = []

        def revoke() -> None:
            events.append("revoke")
            current = load_verifier(self.layout)
            self.assertEqual(current.state, "present")
            self.assertEqual(current.raw_verifier, old_verifier)
            self.assertEqual(self._verifier_path().read_bytes(), old_bytes)
            self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

        rotated = rotate_credential(self.layout, revoke)
        events.append("returned")
        new_password = rotated.reveal()
        loaded = load_verifier(self.layout)
        self.assertEqual(events, ["revoke", "returned"])
        self.assertEqual(loaded.state, "present")
        self.assertEqual(loaded.generation, 2)
        self.assertNotEqual(loaded.raw_verifier, old_verifier)
        self.assertIsNotNone(loaded.verifier)
        assert loaded.verifier is not None
        self.assertTrue(loaded.verifier.verify(new_password))
        self.assertFalse(loaded.verifier.verify(old_password))

    def test_revoke_failure_preserves_old_verifier_and_creates_no_temp_file(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        before = self._snapshot(path)

        def fail_revoke() -> None:
            raise ValueError("untrusted callback detail")

        with mock.patch.object(
            verifier_store.secrets, "token_urlsafe", wraps=verifier_store.secrets.token_urlsafe
        ) as token_factory:
            with self.assertRaises(VerifierStoreError) as blocked:
                rotate_credential(self.layout, fail_revoke)
        self.assertEqual(blocked.exception.reason, "revoke_failed")
        self.assertNotIn("untrusted callback detail", str(blocked.exception))
        token_factory.assert_not_called()
        self.assertEqual(self._snapshot(path), before)
        self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

    def test_atomic_replace_failure_preserves_old_file_and_cleans_temp(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        before = self._snapshot(path)
        with mock.patch.object(
            verifier_store.os, "replace", side_effect=OSError("injected")
        ):
            with self.assertRaises(VerifierStoreError) as blocked:
                rotate_credential(self.layout, lambda: None)
        self.assertEqual(blocked.exception.reason, "verifier_replace_failed")
        self.assertEqual(self._snapshot(path), before)
        self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

    def test_temp_creation_uses_exclusive_create_without_deleting_collision(self) -> None:
        temp_name = ".player_verifier." + ("a" * 32) + ".tmp"
        collision = self.layout.verifier_dir / temp_name
        collision.write_bytes(b"owned by another operation")
        collision.chmod(0o600)
        before = self._snapshot(collision)
        with mock.patch.object(verifier_store.secrets, "token_hex", return_value="a" * 32):
            with self.assertRaises(VerifierStoreError) as blocked:
                issue_credential(self.layout)
        self.assertEqual(blocked.exception.reason, "verifier_temp_create_failed")
        self.assertEqual(self._snapshot(collision), before)
        self.assertFalse(self._verifier_path().exists())

    def test_revoke_access_calls_back_first_and_removes_only_safe_file(self) -> None:
        issue_credential(self.layout)
        path = self._verifier_path()
        existing_bytes = path.read_bytes()
        events: list[str] = []

        def revoke() -> None:
            events.append("revoke")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), existing_bytes)

        result = revoke_access(self.layout, revoke)
        self.assertEqual(events, ["revoke"])
        self.assertEqual((result.state, result.reason), ("absent", "absent"))
        self.assertFalse(path.exists())
        self.assertEqual(load_verifier(self.layout).state, "absent")
        self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

        issue_credential(self.layout)
        before_failed_revoke = self._snapshot(path)

        def fail_revoke() -> None:
            raise RuntimeError("callback failure detail")

        with self.assertRaises(VerifierStoreError) as callback_failure:
            revoke_access(self.layout, fail_revoke)
        self.assertEqual(callback_failure.exception.reason, "revoke_failed")
        self.assertEqual(self._snapshot(path), before_failed_revoke)
        self.assertEqual(list(self.layout.verifier_dir.glob(".player_verifier.*.tmp")), [])

        path.chmod(0o640)
        unsafe_before = self._snapshot(path)
        callback_calls: list[str] = []
        unsafe_result = revoke_access(self.layout, lambda: callback_calls.append("revoke"))
        self.assertEqual(callback_calls, ["revoke"])
        self.assertEqual(unsafe_result.state, "unsafe")
        self.assertEqual(self._snapshot(path), unsafe_before)

    def test_module_imports_no_process_network_or_logging_modules(self) -> None:
        source_path = Path(verifier_store.__file__)
        tree = ast.parse(source_path.read_text(encoding="ascii"))
        forbidden = {"subprocess", "socket", "urllib", "keyring", "logging"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertTrue(imported.isdisjoint(forbidden))

        forbidden_calls = {"print", "putenv", "getenv", "system", "popen"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)
                elif isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
