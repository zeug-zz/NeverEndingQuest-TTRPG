# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for bounded native process introspection."""

from __future__ import annotations

import ctypes
import errno
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing import native_process_info as process_info


class ProcessInfoTests(unittest.TestCase):
    def _self_info(self) -> process_info.ProcessInfo:
        try:
            info = process_info.lookup(os.getpid())
        except process_info.ProcessInfoUnavailable as exc:
            self.skipTest("native process backend unavailable: %s" % exc.reason)
        self.assertIsNotNone(info, "native observer could not read its own process")
        assert info is not None
        return info

    def test_self_introspection_matches_os_identity(self) -> None:
        info = self._self_info()
        self.assertEqual(info.pid, os.getpid())
        self.assertEqual(info.ppid, os.getppid())
        self.assertEqual(info.pgid, os.getpgid(os.getpid()))
        self.assertEqual(info.uid, os.getuid())
        self.assertTrue(Path(info.executable).is_absolute())
        self.assertEqual(os.path.realpath(info.executable), info.executable)
        self.assertTrue(os.access(info.executable, os.X_OK))
        self.assertTrue(info.argv)
        self.assertTrue(all(isinstance(argument, str) for argument in info.argv))
        self.assertNotIn("argv=", repr(info))

    def test_current_user_census_contains_this_process(self) -> None:
        if process_info.platform.system() not in {"Darwin", "Linux"}:
            self.skipTest("native process backend is unsupported on this platform")
        processes = process_info.snapshot_current_user()
        current = next((item for item in processes if item.pid == os.getpid()), None)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current.uid, os.getuid())
        self.assertIsInstance(current.comm, str)

    def test_spawned_child_has_native_parent_group_and_distinctive_argv(self) -> None:
        marker = "process-info-child-marker-64a9f3"
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", marker],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        try:
            try:
                info = process_info.lookup(child.pid)
            except process_info.ProcessInfoUnavailable as exc:
                self.skipTest("native process backend unavailable: %s" % exc.reason)
            self.assertIsNotNone(info, "native observer could not read a live child")
            assert info is not None
            self.assertEqual(info.pid, child.pid)
            self.assertEqual(info.ppid, os.getpid())
            self.assertEqual(info.pgid, os.getpgid(child.pid))
            self.assertEqual(info.uid, os.getuid())
            self.assertTrue(Path(info.executable).is_absolute())
            self.assertEqual(os.path.realpath(info.executable), info.executable)
            self.assertTrue(os.access(info.executable, os.X_OK))
            self.assertIn(marker, info.argv)
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3.0)

    def test_vanished_process_returns_none(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        child_pid = child.pid
        child.wait(timeout=3.0)
        self.assertIsNone(process_info.lookup(child_pid))

    def test_darwin_proc_bsdinfo_layout_matches_sdk_offsets(self) -> None:
        fields = process_info._ProcBsdInfo
        self.assertEqual(ctypes.sizeof(fields), 136)
        self.assertEqual(fields.pbi_ppid.offset, 16)
        self.assertEqual(fields.pbi_uid.offset, 20)
        self.assertEqual(fields.pbi_comm.offset, 48)
        self.assertEqual(fields.pbi_name.offset, 64)
        self.assertEqual(fields.pbi_pgid.offset, 100)
        self.assertEqual(fields.pbi_start_tvsec.offset, 120)
        self.assertEqual(fields.pbi_start_tvusec.offset, 128)

    def test_darwin_pid_enumeration_can_be_scoped_to_one_uid(self) -> None:
        class FakeLibproc:
            calls: list[tuple[int, int]] = []

            def proc_listpids(
                self, process_type: int, typeinfo: int, buffer: object, size: int
            ) -> int:
                self.calls.append((process_type, typeinfo))
                pids = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int))
                pids[0] = 101
                pids[1] = 0
                return 2 * ctypes.sizeof(ctypes.c_int)

        fake = FakeLibproc()
        with mock.patch.object(process_info, "_darwin_libproc", return_value=fake):
            self.assertEqual(process_info._darwin_pid_list(uid=501), (101,))
        self.assertEqual(fake.calls, [(4, 501)])

    def test_linux_proc_parsers_handle_parenthesized_comm_and_boot_time(self) -> None:
        fields = ["S", "1", "42"] + ["0"] * 16 + ["987654"]
        stat_line = "123 (worker ) name) " + " ".join(fields)
        self.assertEqual(process_info._parse_linux_stat(stat_line), (1, 42, 987654))
        self.assertEqual(
            process_info._parse_linux_uid("Name:\tworker\nUid:\t501\t501\t501\t501\n"),
            501,
        )
        self.assertEqual(
            process_info._parse_linux_uid("Uid:\t1000\t501\t1000\t501\n"),
            501,
        )
        self.assertEqual(process_info._linux_start_epoch(100, 1_700_000_000, 100), 1_700_000_001.0)

    def test_linux_backend_reads_bounded_proc_fixture_and_rejects_incomplete_scan(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            proc_root = Path(temporary_directory)
            boot_time = 1_700_000_000
            pid = 4242
            process_dir = proc_root / str(pid)
            process_dir.mkdir()
            stat_fields = ["S", str(os.getpid()), "77"] + ["0"] * 16 + ["987654"]
            (process_dir / "stat").write_bytes(
                ("%d (worker " % pid).encode("ascii")
                + b"\xff) "
                + " ".join(stat_fields).encode("ascii")
            )
            (process_dir / "status").write_text(
                "Name:\tworker\nUid:\t%d\t%d\t%d\t%d\n"
                % (os.getuid(), os.getuid(), os.getuid(), os.getuid()),
                encoding="ascii",
            )
            (process_dir / "comm").write_bytes(b"worker\n")
            (process_dir / "cmdline").write_bytes(b"/bin/worker\0--profile\0neq\0")
            os.symlink(sys.executable, process_dir / "exe")
            (proc_root / "stat").write_text("cpu 1\nbtime %d\n" % boot_time, encoding="ascii")
            with mock.patch.object(process_info.os, "sysconf", return_value=100):
                records = process_info._snapshot_linux(proc_root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].pid, pid)
            self.assertEqual(records[0].ppid, os.getpid())
            self.assertEqual(records[0].pgid, 77)
            self.assertEqual(records[0].uid, os.getuid())
            self.assertEqual(records[0].comm, "worker")
            self.assertEqual(records[0].argv, ("/bin/worker", "--profile", "neq"))
            self.assertEqual(records[0].start_time, boot_time + (987654 / 100))
            with (
                mock.patch.object(process_info.platform, "system", return_value="Linux"),
                mock.patch.object(process_info, "_linux_boot_time", return_value=boot_time),
                mock.patch.object(process_info.os, "sysconf", return_value=100),
            ):
                self.assertEqual(
                    process_info.legacy_creation_token(records[0]), "987654"
                )
                self.assertEqual(
                    process_info.creation_token(records[0]),
                    "pid-%d-start-us-%d"
                    % (pid, int(round(records[0].start_time * 1_000_000))),
                )

            other_process = proc_root / "4243"
            other_process.mkdir()
            other_fields = ["S", "1", "77"] + ["0"] * 16 + ["987655"]
            (other_process / "stat").write_text(
                "4243 (other-user) %s" % " ".join(other_fields), encoding="ascii"
            )
            (other_process / "status").write_text(
                "Uid:\t%d\t%d\t%d\t%d\n"
                % tuple([os.getuid() + 1] * 4),
                encoding="ascii",
            )
            original_stat = Path.stat

            def fixture_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
                if path == other_process:
                    return mock.Mock(st_uid=os.getuid() + 1)  # type: ignore[return-value]
                return original_stat(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "stat", new=fixture_stat),
                mock.patch.object(process_info.os, "sysconf", return_value=100),
            ):
                current_user_records = process_info._snapshot_linux(proc_root, uid=os.getuid())
            self.assertEqual(tuple(item.pid for item in current_user_records), (pid,))

            with mock.patch.object(
                process_info,
                "_lookup_linux",
                side_effect=process_info.ProcessInfoUnavailable("process_list_incomplete"),
            ):
                with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                    process_info._snapshot_linux(proc_root)
            self.assertEqual(raised.exception.reason, "process_list_incomplete")

    def test_linux_process_count_is_capped_before_snapshot_work(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            proc_root = Path(temporary_directory)
            (proc_root / "101").mkdir()
            (proc_root / "102").mkdir()
            with mock.patch.object(process_info, "MAX_PROCESS_COUNT", 1):
                with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                    process_info._snapshot_linux(proc_root)
        self.assertEqual(raised.exception.reason, "process_list_too_large")

    def test_linux_snapshot_skips_only_confirmed_process_exit_races(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            proc_root = Path(temporary_directory)
            (proc_root / "101").mkdir()
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info._lookup_linux(
                    101,
                    1_700_000_000,
                    strict=True,
                    proc_root=proc_root,
                )
            self.assertEqual(raised.exception.reason, "process_list_incomplete")
            self.assertIsNone(
                process_info._lookup_linux(
                    102,
                    1_700_000_000,
                    strict=True,
                    proc_root=proc_root,
                )
            )

    def test_linux_current_user_snapshot_rejects_uid_change(self) -> None:
        stat_fields = ["S", "1", "77"] + ["0"] * 16 + ["987654"]
        stat_value = "101 (worker) %s" % " ".join(stat_fields)
        status_value = "Uid:\t%d\t%d\t%d\t%d\n" % tuple(
            [os.getuid() + 1] * 4
        )
        with mock.patch.object(
            process_info, "_read_text", side_effect=(stat_value, status_value)
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info._lookup_linux(
                    101,
                    1_700_000_000,
                    strict=True,
                    expected_uid=os.getuid(),
                )
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

    def test_linux_unreadable_executable_and_argv_keep_core_record_complete(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            proc_root = Path(temporary_directory)
            pid = 101
            process_dir = proc_root / str(pid)
            process_dir.mkdir()
            stat_fields = ["S", "1", "77"] + ["0"] * 16 + ["987654"]
            (process_dir / "stat").write_text(
                "%d (opentunnel) %s" % (pid, " ".join(stat_fields)),
                encoding="ascii",
            )
            (process_dir / "status").write_text(
                "Uid:\t%d\t%d\t%d\t%d\n" % tuple([os.getuid()] * 4),
                encoding="ascii",
            )
            (process_dir / "comm").write_bytes(b"opentunnel\n")
            with mock.patch.object(process_info.os, "sysconf", return_value=100):
                info = process_info._lookup_linux(
                    pid,
                    1_700_000_000,
                    strict=True,
                    proc_root=proc_root,
                    expected_uid=os.getuid(),
                )
            self.assertIsNotNone(info)
            assert info is not None
            self.assertIsNone(info.executable)
            self.assertEqual(info.argv, ())
            self.assertEqual(info.comm, "opentunnel")

    def test_linux_unreadable_comm_keeps_census_record_indeterminate(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            proc_root = Path(temporary_directory)
            pid = 102
            process_dir = proc_root / str(pid)
            process_dir.mkdir()
            stat_fields = ["S", "1", "77"] + ["0"] * 16 + ["987655"]
            (process_dir / "stat").write_text(
                "%d (worker) %s" % (pid, " ".join(stat_fields)),
                encoding="ascii",
            )
            (process_dir / "status").write_text(
                "Uid:\t%d\t%d\t%d\t%d\n" % tuple([os.getuid()] * 4),
                encoding="ascii",
            )
            with (
                mock.patch.object(process_info.os, "sysconf", return_value=100),
                mock.patch.object(
                    process_info,
                    "_read_comm",
                    side_effect=PermissionError(errno.EPERM, "denied"),
                ),
            ):
                info = process_info._lookup_linux(
                    pid,
                    1_700_000_000,
                    strict=True,
                    proc_root=proc_root,
                    expected_uid=os.getuid(),
                )
            self.assertIsNotNone(info)
            assert info is not None
            self.assertIsNone(info.executable)
            self.assertEqual(info.argv, ())
            self.assertEqual(info.comm, "")
            self.assertIs(
                process_info.could_be_companion(info, Path("/bin/echo")), None
            )

    def test_linux_cmdline_and_darwin_procargs_are_bounded_and_ignore_environment(self) -> None:
        self.assertEqual(
            process_info._parse_linux_cmdline(b"/bin/tool\0--profile\0neq\0"),
            ("/bin/tool", "--profile", "neq"),
        )
        self.assertEqual(
            process_info._parse_darwin_procargs(
                struct.pack("@i", 2)
                + b"/bin/tool\0\0/bin/tool\0--profile\0NEQ_SECRET=value\0"
            ),
            ("/bin/tool", "--profile"),
        )
        with self.assertRaises(ValueError):
            process_info._parse_linux_cmdline(b"x" * (process_info.MAX_ARG_LENGTH + 1))
        with self.assertRaises(ValueError):
            process_info._parse_linux_cmdline(
                b"\0".join(b"x" for _ in range(process_info.MAX_ARG_COUNT + 1))
            )
        with self.assertRaises(ValueError):
            process_info._parse_darwin_procargs(
                struct.pack("@i", process_info.MAX_ARG_COUNT + 1) + b"/bin/tool\0"
            )

    def test_native_snapshot_fails_closed_on_per_pid_eperm_and_listing_failure(self) -> None:
        survivor = process_info.ProcessInfo(
            202,
            1,
            1,
            os.getuid(),
            1_700_000_000.0,
            "/bin/echo",
            ("/bin/echo",),
        )

        def per_pid(pid: int) -> process_info.ProcessInfo | None:
            if pid == 201:
                raise PermissionError(errno.EPERM, "denied")
            if pid == 202:
                return survivor
            return None

        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(process_info, "_darwin_pid_list", return_value=(201, 202, 203)),
            mock.patch.object(process_info, "_lookup_darwin", side_effect=per_pid),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info.snapshot()
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

        def raced(pid: int) -> process_info.ProcessInfo | None:
            if pid == 201:
                raise ProcessLookupError(errno.ESRCH, "process exited")
            return survivor if pid == 202 else None

        pid_lists = iter(((201, 202, 203), (202, 203), (202,)))
        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(
                process_info,
                "_darwin_pid_list",
                side_effect=lambda **_kwargs: next(pid_lists),
            ),
            mock.patch.object(process_info, "_lookup_darwin", side_effect=raced),
        ):
            self.assertEqual(process_info.snapshot(), (survivor,))

        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(process_info, "_darwin_pid_list", return_value=(203,)),
            mock.patch.object(process_info, "_lookup_darwin", return_value=None),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info.snapshot()
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(
                process_info,
                "_darwin_pid_list",
                side_effect=process_info.ProcessInfoUnavailable("process_list_unavailable"),
            ),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable):
                process_info.snapshot()

    def test_current_user_darwin_snapshot_rejects_identity_change(self) -> None:
        other_user = process_info.ProcessInfo(
            202,
            1,
            1,
            os.getuid() + 1,
            1_700_000_000.0,
            "/bin/echo",
            ("echo",),
        )
        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(process_info, "_darwin_pid_list", return_value=(202,)),
            mock.patch.object(process_info, "_lookup_darwin", return_value=other_user),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info.snapshot_current_user()
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

    def test_darwin_uid_change_between_identity_reads_is_incomplete(self) -> None:
        first = process_info._ProcBsdInfo()
        first.pbi_pid = 202
        first.pbi_ppid = 1
        first.pbi_uid = os.getuid()
        first.pbi_pgid = 202
        first.pbi_start_tvsec = 1_700_000_000
        second = process_info._ProcBsdInfo.from_buffer_copy(bytes(first))
        second.pbi_uid = os.getuid() + 1
        with (
            mock.patch.object(process_info, "_darwin_libproc", return_value=object()),
            mock.patch.object(
                process_info, "_darwin_bsd_info", side_effect=(first, second)
            ),
            mock.patch.object(process_info, "_darwin_executable", return_value="/bin/echo"),
            mock.patch.object(process_info, "_darwin_argv", return_value=("echo",)),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info._lookup_darwin(202)
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

    def test_darwin_filtered_census_does_not_call_uid_change_a_confirmed_exit(self) -> None:
        pid_lists = iter(((202,), (202,)))
        with (
            mock.patch.object(process_info.platform, "system", return_value="Darwin"),
            mock.patch.object(
                process_info,
                "_darwin_pid_list",
                side_effect=lambda **_kwargs: next(pid_lists),
            ),
            mock.patch.object(
                process_info,
                "_lookup_darwin",
                side_effect=ProcessLookupError(errno.ESRCH, "not visible to caller"),
            ),
        ):
            with self.assertRaises(process_info.ProcessInfoUnavailable) as raised:
                process_info.snapshot_current_user()
        self.assertEqual(raised.exception.reason, "process_list_incomplete")

    def test_darwin_readable_bsd_identity_tolerates_unavailable_path_and_argv(self) -> None:
        first = process_info._ProcBsdInfo()
        first.pbi_pid = 202
        first.pbi_ppid = 1
        first.pbi_uid = os.getuid()
        first.pbi_pgid = 202
        first.pbi_comm = b"opentunnel"
        first.pbi_start_tvsec = 1_700_000_000
        first.pbi_start_tvusec = 125_000
        second = process_info._ProcBsdInfo.from_buffer_copy(bytes(first))
        with (
            mock.patch.object(process_info, "_darwin_libproc", return_value=object()),
            mock.patch.object(
                process_info, "_darwin_bsd_info", side_effect=(first, second)
            ),
            mock.patch.object(
                process_info,
                "_darwin_executable",
                side_effect=PermissionError(errno.EPERM, "denied"),
            ),
            mock.patch.object(
                process_info,
                "_darwin_argv",
                side_effect=PermissionError(errno.EPERM, "denied"),
            ),
        ):
            info = process_info._lookup_darwin(202)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertIsNone(info.executable)
        self.assertEqual(info.argv, ())
        self.assertEqual(info.comm, "opentunnel")
        self.assertIs(process_info.could_be_companion(info, Path("/bin/echo")), True)

    def test_could_be_companion_requires_exact_known_path_and_uses_unknown_cues(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="tmp") as temporary_directory:
            root = Path(temporary_directory)
            companion = root / "opentunnel"
            companion.write_bytes(b"companion")
            other = root / "other"
            other.write_bytes(b"other")

            def make_info(
                executable: str | None, comm: str, argv: tuple[str, ...]
            ) -> process_info.ProcessInfo:
                return process_info.ProcessInfo(
                    101,
                    1,
                    101,
                    os.getuid(),
                    1_700_000_000.0,
                    executable,
                    argv,
                    comm,
                )

            self.assertIs(
                process_info.could_be_companion(
                    make_info(str(companion), "anything", ()), companion
                ),
                True,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(str(other), "opentunnel", ()), companion
                ),
                False,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(None, "opentunnel", ()), companion
                ),
                True,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(None, "python", (str(companion), "serve")), companion
                ),
                True,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(None, "python", ("python", str(companion))), companion
                ),
                True,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(None, "python", ("python", "worker.py")), companion
                ),
                False,
            )
            self.assertIs(
                process_info.could_be_companion(
                    make_info(
                        None,
                        "opentunnel-helper",
                        ("worker", "not-opentunnel"),
                    ),
                    companion,
                ),
                False,
            )
            self.assertIs(
                process_info.could_be_companion(make_info(None, "", ()), companion),
                None,
            )

    def test_creation_token_is_pid_and_microsecond_start_time(self) -> None:
        info = self._self_info()
        expected = "pid-%d-start-us-%d" % (
            info.pid,
            int(round(info.start_time * 1_000_000)),
        )
        self.assertEqual(process_info.creation_token(info), expected)


if __name__ == "__main__":
    unittest.main()
