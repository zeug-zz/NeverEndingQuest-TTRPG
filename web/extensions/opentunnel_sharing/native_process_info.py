# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded native process introspection for OpenTunnel ownership checks."""

# TABLETOP MODE: This read-only boundary supplies positive host process identity.

from __future__ import annotations

import ctypes
import errno
import math
import os
import platform
import struct
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

MAX_PROCESS_COUNT = 32768
MAX_ARG_COUNT = 256
MAX_ARG_LENGTH = 4096
MAX_ARG_BYTES = 64 * 1024
MAX_PROCARGS_BYTES = 256 * 1024
MAX_EXECUTABLE_BYTES = 4096
MAX_COMM_BYTES = 256
MAX_PROC_FILE_BYTES = 64 * 1024
MAX_PID = (1 << 31) - 1
MAX_PROCESS_EPOCH = 253402300799.0

_PROC_ALL_PIDS = 1
_PROC_UID_ONLY = 4
_PROC_PIDTBSDINFO = 3
_CTL_KERN = 1
_KERN_PROCARGS2 = 49


@dataclass(frozen=True, slots=True, repr=False)
class ProcessInfo:
    """One bounded process observation; argv is intentionally hidden by repr."""

    pid: int
    ppid: int
    pgid: int
    uid: int
    start_time: float
    executable: str | None
    argv: tuple[str, ...] = field(repr=False)
    comm: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        try:
            numeric_start_time = float(self.start_time)
        except (OverflowError, TypeError, ValueError):
            raise ValueError("process_info_invalid") from None
        if (
            type(self.pid) is not int
            or self.pid <= 0
            or self.pid > MAX_PID
            or type(self.ppid) is not int
            or self.ppid < 0
            or type(self.pgid) is not int
            or self.pgid < 0
            or type(self.uid) is not int
            or self.uid < 0
            or isinstance(self.start_time, bool)
            or not isinstance(self.start_time, (int, float))
            or not math.isfinite(numeric_start_time)
            or numeric_start_time <= 0
            or numeric_start_time > MAX_PROCESS_EPOCH
            or (
                self.executable is not None
                and (
                    not isinstance(self.executable, str)
                    or not self.executable
                    or "\0" in self.executable
                    or not os.path.isabs(self.executable)
                )
            )
            or not isinstance(self.comm, str)
            or "\0" in self.comm
            or not isinstance(self.argv, tuple)
            or len(self.argv) > MAX_ARG_COUNT
        ):
            raise ValueError("process_info_invalid")
        try:
            if len(os.fsencode(self.comm)) > MAX_COMM_BYTES:
                raise ValueError("process_info_invalid")
            canonical_executable = None
            if self.executable is not None:
                if len(os.fsencode(self.executable)) > MAX_EXECUTABLE_BYTES:
                    raise ValueError("process_info_invalid")
                canonical_executable = os.path.realpath(self.executable)
                if len(os.fsencode(canonical_executable)) > MAX_EXECUTABLE_BYTES:
                    raise ValueError("process_info_invalid")
            total_argument_bytes = 0
            for argument in self.argv:
                if not isinstance(argument, str) or "\0" in argument:
                    raise ValueError("process_info_invalid")
                argument_size = len(os.fsencode(argument))
                if argument_size > MAX_ARG_LENGTH:
                    raise ValueError("process_info_invalid")
                total_argument_bytes += argument_size
                if total_argument_bytes > MAX_ARG_BYTES:
                    raise ValueError("process_info_invalid")
        except (OSError, TypeError, UnicodeError):
            raise ValueError("process_info_invalid") from None
        object.__setattr__(self, "start_time", numeric_start_time)
        object.__setattr__(self, "executable", canonical_executable)

    def __repr__(self) -> str:
        return "ProcessInfo(pid=%r, ppid=%r, pgid=%r, uid=%r, start_time=%r)" % (
            self.pid,
            self.ppid,
            self.pgid,
            self.uid,
            self.start_time,
        )


class ProcessInfoUnavailable(RuntimeError):
    """The native process listing or platform backend is unavailable."""

    def __init__(self, reason: str = "process_info_unavailable") -> None:
        if reason not in {
            "process_list_unavailable",
            "process_list_incomplete",
            "process_list_too_large",
            "process_info_unavailable",
            "unsupported_platform",
        }:
            reason = "process_info_unavailable"
        super().__init__(reason)
        self.reason = reason


class _ProcBsdInfo(ctypes.Structure):
    """Exact ``struct proc_bsdinfo`` layout from Darwin sys/proc_info.h."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def snapshot() -> tuple[ProcessInfo, ...]:
    """Return a bounded snapshot; uncertainty makes the whole census incomplete."""
    selected_platform = platform.system()
    if selected_platform == "Darwin":
        return _snapshot_darwin()
    if selected_platform == "Linux":
        return _snapshot_linux()
    raise ProcessInfoUnavailable("unsupported_platform")


def snapshot_current_user() -> tuple[ProcessInfo, ...]:
    """Return a complete bounded snapshot for the current OS user only."""
    selected_platform = platform.system()
    if selected_platform == "Darwin":
        return _snapshot_darwin(uid=os.getuid())
    if selected_platform == "Linux":
        return _snapshot_linux(uid=os.getuid())
    raise ProcessInfoUnavailable("unsupported_platform")


def lookup(pid: int) -> ProcessInfo | None:
    """Return one process observation, or None when that PID cannot be read."""
    if type(pid) is not int or pid <= 0 or pid > MAX_PID:
        return None
    selected_platform = platform.system()
    if selected_platform == "Darwin":
        try:
            return _lookup_darwin(pid)
        except ProcessInfoUnavailable:
            raise
        except (OSError, OverflowError, TypeError, ValueError):
            return None
    if selected_platform == "Linux":
        try:
            boot_time = _linux_boot_time()
        except (OSError, RuntimeError, ValueError):
            raise ProcessInfoUnavailable("process_info_unavailable") from None
        return _lookup_linux(pid, boot_time)
    raise ProcessInfoUnavailable("unsupported_platform")


def creation_token(info: ProcessInfo) -> str:
    """Return a stable opaque PID/start-time token shared by all callers."""
    if not isinstance(info, ProcessInfo):
        raise TypeError("process_info_required")
    start_microseconds = int(round(info.start_time * 1_000_000.0))
    return "pid-%d-start-us-%d" % (info.pid, start_microseconds)


def could_be_companion(info: ProcessInfo, companion_path: Path) -> bool | None:
    """Classify a possible companion without treating names as ownership proof.

    A known executable is compared only by its canonical path. When that path
    is unavailable, bounded process name/argv cues may identify a candidate;
    absent cues are conclusive only when the process name itself was readable.
    """
    if not isinstance(info, ProcessInfo):
        return None
    try:
        expected_executable = Path(companion_path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if info.executable is not None:
        try:
            observed_executable = Path(info.executable).resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        return observed_executable == expected_executable

    comm_available = bool(info.comm)
    comm_candidate = info.comm.casefold() == "opentunnel"
    argv_candidate = bool(
        info.argv
        and (
            Path(info.argv[0]).name.casefold() == "opentunnel"
            or str(expected_executable) in info.argv
        )
    )
    if comm_candidate or argv_candidate:
        return True
    if comm_available:
        return False
    return None


def legacy_creation_token(info: ProcessInfo) -> str | None:
    """Derive pre-native owner-record tokens for fail-closed compatibility."""
    if not isinstance(info, ProcessInfo):
        return None
    selected_platform = platform.system()
    if selected_platform == "Linux":
        try:
            ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
            boot_time = _linux_boot_time()
        except (OSError, ValueError, RuntimeError):
            return None
        if ticks_per_second <= 0:
            return None
        ticks = int(round((info.start_time - boot_time) * ticks_per_second))
        return str(ticks) if ticks >= 0 else None
    if selected_platform == "Darwin":
        try:
            selected = datetime.fromtimestamp(info.start_time)
        except (OverflowError, OSError, ValueError):
            return None
        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        return "%s %s %2d %02d:%02d:%02d %04d" % (
            weekdays[selected.weekday()],
            months[selected.month - 1],
            selected.day,
            selected.hour,
            selected.minute,
            selected.second,
            selected.year,
        )
    return None


def _snapshot_darwin(uid: int | None = None) -> tuple[ProcessInfo, ...]:
    pids = _darwin_pid_list(uid=uid)
    records: list[ProcessInfo] = []
    for pid in pids:
        try:
            info = _lookup_darwin(pid)
        except ProcessInfoUnavailable:
            raise
        except OSError as exc:
            if exc.errno in {errno.ESRCH, errno.ENOENT}:
                if _darwin_pid_is_absent(pid):
                    continue
                raise ProcessInfoUnavailable("process_list_incomplete") from None
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        except (OverflowError, TypeError, ValueError):
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        if info is None:
            if _darwin_pid_is_absent(pid):
                continue
            raise ProcessInfoUnavailable("process_list_incomplete")
        if uid is not None and info.uid != uid:
            raise ProcessInfoUnavailable("process_list_incomplete")
        records.append(info)
    return tuple(records)


def _darwin_pid_is_absent(pid: int) -> bool:
    """Confirm a listed PID disappeared before treating a probe race as benign."""
    try:
        # Check all UIDs: disappearance from the filtered list can also mean
        # that the process changed UID or the PID was reused by another user.
        return pid not in _darwin_pid_list()
    except (OSError, ProcessInfoUnavailable, OverflowError, TypeError, ValueError):
        return False


def _darwin_pid_list(uid: int | None = None) -> tuple[int, ...]:
    libproc = _darwin_libproc()
    if uid is not None and (type(uid) is not int or uid < 0 or uid > 0xFFFFFFFF):
        raise ProcessInfoUnavailable("process_info_unavailable")
    process_type = _PROC_ALL_PIDS if uid is None else _PROC_UID_ONLY
    process_typeinfo = 0 if uid is None else uid
    capacity = MAX_PROCESS_COUNT + 1
    buffer = (ctypes.c_int * capacity)()
    ctypes.set_errno(0)
    written = libproc.proc_listpids(
        process_type, process_typeinfo, ctypes.byref(buffer), ctypes.sizeof(buffer)
    )
    if written < 0:
        raise ProcessInfoUnavailable("process_list_unavailable")
    if written == 0:
        if ctypes.get_errno():
            raise ProcessInfoUnavailable("process_list_unavailable")
        return ()
    if written > ctypes.sizeof(buffer) or written % ctypes.sizeof(ctypes.c_int):
        raise ProcessInfoUnavailable("process_list_unavailable")
    count = written // ctypes.sizeof(ctypes.c_int)
    if count > MAX_PROCESS_COUNT:
        raise ProcessInfoUnavailable("process_list_too_large")
    return tuple(sorted({int(pid) for pid in buffer[:count] if pid > 0}))


def _lookup_darwin(pid: int) -> ProcessInfo | None:
    libproc = _darwin_libproc()
    first = _darwin_bsd_info(libproc, pid)
    if first.pbi_pid != pid:
        raise ProcessInfoUnavailable("process_list_incomplete")
    try:
        executable = _darwin_executable(libproc, pid)
    except (OSError, RuntimeError, TypeError, ValueError):
        executable = None
    try:
        argv = _darwin_argv(pid)
    except (
        OSError,
        ProcessInfoUnavailable,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        argv = ()
    second = _darwin_bsd_info(libproc, pid)
    first_start = (first.pbi_start_tvsec, first.pbi_start_tvusec)
    second_start = (second.pbi_start_tvsec, second.pbi_start_tvusec)
    if (
        second.pbi_pid != pid
        or first_start != second_start
        or first.pbi_uid != second.pbi_uid
    ):
        raise ProcessInfoUnavailable("process_list_incomplete")
    start_time = float(second.pbi_start_tvsec) + (
        float(second.pbi_start_tvusec) / 1_000_000.0
    )
    return _make_process_info(
        pid=pid,
        ppid=int(second.pbi_ppid),
        pgid=int(second.pbi_pgid),
        uid=int(second.pbi_uid),
        start_time=start_time,
        executable=executable,
        argv=argv,
        comm=_decode_comm(second.pbi_comm),
    )


def _darwin_bsd_info(libproc: ctypes.CDLL, pid: int) -> _ProcBsdInfo:
    result = _ProcBsdInfo()
    ctypes.set_errno(0)
    copied = libproc.proc_pidinfo(
        pid,
        _PROC_PIDTBSDINFO,
        0,
        ctypes.byref(result),
        ctypes.sizeof(result),
    )
    if copied != ctypes.sizeof(result):
        error_number = ctypes.get_errno() or errno.ESRCH
        raise OSError(error_number, "proc_pidinfo_unavailable")
    return result


def _darwin_executable(libproc: ctypes.CDLL, pid: int) -> str:
    buffer = ctypes.create_string_buffer(MAX_EXECUTABLE_BYTES)
    ctypes.set_errno(0)
    copied = libproc.proc_pidpath(pid, buffer, ctypes.sizeof(buffer))
    if copied <= 0 or copied >= ctypes.sizeof(buffer):
        error_number = ctypes.get_errno() or errno.ESRCH
        raise OSError(error_number, "proc_pidpath_unavailable")
    value = os.fsdecode(buffer.value)
    if not value:
        raise OSError(errno.EIO, "proc_pidpath_empty")
    return os.path.realpath(value)


def _darwin_argv(pid: int) -> tuple[str, ...]:
    libc = _darwin_libc()
    sysctl = libc.sysctl
    mib = (ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(0)
    ctypes.set_errno(0)
    result = sysctl(mib, 3, None, ctypes.byref(size), None, 0)
    if result != 0 or size.value <= 0 or size.value > MAX_PROCARGS_BYTES:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "kern_procargs2_size_unavailable")
    buffer = (ctypes.c_ubyte * size.value)()
    actual_size = ctypes.c_size_t(size.value)
    ctypes.set_errno(0)
    result = sysctl(
        mib, 3, ctypes.byref(buffer), ctypes.byref(actual_size), None, 0
    )
    if result != 0 or actual_size.value > size.value:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "kern_procargs2_unavailable")
    return _parse_darwin_procargs(bytes(buffer[: actual_size.value]))


@lru_cache(maxsize=1)
def _darwin_libproc() -> ctypes.CDLL:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_listpids.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
        )
        libproc.proc_listpids.restype = ctypes.c_int
        libproc.proc_pidinfo.argtypes = (
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        )
        libproc.proc_pidinfo.restype = ctypes.c_int
        libproc.proc_pidpath.argtypes = (
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        libproc.proc_pidpath.restype = ctypes.c_int
    except (OSError, AttributeError, TypeError, ValueError):
        raise ProcessInfoUnavailable("process_info_unavailable") from None
    return libproc


@lru_cache(maxsize=1)
def _darwin_libc() -> ctypes.CDLL:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.sysctl.argtypes = (
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        )
        libc.sysctl.restype = ctypes.c_int
    except (OSError, AttributeError, TypeError, ValueError):
        raise ProcessInfoUnavailable("process_info_unavailable") from None
    return libc


def _snapshot_linux(
    proc_root: Path = Path("/proc"), *, uid: int | None = None
) -> tuple[ProcessInfo, ...]:
    proc_root = Path(proc_root)
    if uid is not None and (type(uid) is not int or uid < 0):
        raise ProcessInfoUnavailable("process_info_unavailable")
    try:
        entries: list[int] = []
        for item in proc_root.iterdir():
            if item.name.isascii() and item.name.isdigit():
                entries.append(int(item.name))
                if len(entries) > MAX_PROCESS_COUNT:
                    raise ProcessInfoUnavailable("process_list_too_large")
    except ProcessInfoUnavailable:
        raise
    except OSError:
        raise ProcessInfoUnavailable("process_list_unavailable") from None
    try:
        boot_time = _linux_boot_time(proc_root)
    except (OSError, RuntimeError, ValueError):
        raise ProcessInfoUnavailable("process_list_unavailable") from None
    records: list[ProcessInfo] = []
    for pid in sorted(set(entries)):
        if uid is not None:
            try:
                process_owner = (proc_root / str(pid)).stat().st_uid
            except FileNotFoundError:
                # The PID directory itself disappeared after enumeration.
                continue
            except OSError:
                raise ProcessInfoUnavailable("process_list_incomplete") from None
            if process_owner != uid:
                continue
        info = _lookup_linux(
            pid,
            boot_time,
            strict=True,
            proc_root=proc_root,
            expected_uid=uid,
        )
        if info is not None:
            records.append(info)
    return tuple(records)


def _lookup_linux(
    pid: int,
    boot_time: int,
    *,
    strict: bool = False,
    proc_root: Path = Path("/proc"),
    expected_uid: int | None = None,
) -> ProcessInfo | None:
    process_dir = Path(proc_root) / str(pid)
    try:
        first_stat = _read_text(process_dir / "stat", MAX_PROC_FILE_BYTES)
        parent_pid, process_group, start_ticks = _parse_linux_stat(first_stat)
        status = _read_text(process_dir / "status", MAX_PROC_FILE_BYTES)
        uid = _parse_linux_uid(status)
        if expected_uid is not None and uid != expected_uid:
            if strict:
                raise ProcessInfoUnavailable("process_list_incomplete")
            return None
        try:
            comm = _read_comm(process_dir / "comm")
        except (OSError, TypeError, ValueError, UnicodeError):
            comm = ""
        try:
            executable = os.path.realpath(os.readlink(process_dir / "exe"))
            if (
                not os.path.isabs(executable)
                or len(os.fsencode(executable)) > MAX_EXECUTABLE_BYTES
            ):
                executable = None
        except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
            executable = None
        try:
            argv_payload = _read_bytes(process_dir / "cmdline", MAX_ARG_BYTES)
            argv = _parse_linux_cmdline(argv_payload)
        except (OSError, TypeError, ValueError, UnicodeError):
            argv = ()
        second_stat = _read_text(process_dir / "stat", MAX_PROC_FILE_BYTES)
        _parent_second, _group_second, start_ticks_second = _parse_linux_stat(
            second_stat
        )
        second_status = _read_text(process_dir / "status", MAX_PROC_FILE_BYTES)
        uid_second = _parse_linux_uid(second_status)
    except FileNotFoundError:
        if strict:
            try:
                process_dir.stat()
            except FileNotFoundError:
                return None
            except OSError:
                raise ProcessInfoUnavailable("process_list_incomplete") from None
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None
    except PermissionError:
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None
    except (OSError, OverflowError, TypeError, ValueError):
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None
    if start_ticks != start_ticks_second or uid != uid_second:
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete")
        return None
    try:
        ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError):
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None
    if ticks_per_second <= 0:
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete")
        return None
    try:
        start_time = _linux_start_epoch(start_ticks, boot_time, ticks_per_second)
    except ValueError:
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None
    try:
        return _make_process_info(
            pid=pid,
            ppid=parent_pid,
            pgid=process_group,
            uid=uid,
            start_time=start_time,
            executable=executable,
            argv=argv,
            comm=comm,
        )
    except (OverflowError, TypeError, ValueError):
        if strict:
            raise ProcessInfoUnavailable("process_list_incomplete") from None
        return None


def _linux_boot_time(proc_root: Path = Path("/proc")) -> int:
    contents = _read_text(Path(proc_root) / "stat", MAX_PROC_FILE_BYTES)
    for line in contents.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == "btime" and fields[1].isdigit():
            return int(fields[1])
    raise ValueError("proc_boot_time_unavailable")


def _parse_linux_stat(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) > MAX_PROC_FILE_BYTES:
        raise ValueError("proc_stat_invalid")
    closing_paren = value.rfind(")")
    if closing_paren < 0:
        raise ValueError("proc_stat_invalid")
    fields = value[closing_paren + 1 :].split()
    if len(fields) <= 19:
        raise ValueError("proc_stat_invalid")
    try:
        parent_pid = int(fields[1])
        process_group = int(fields[2])
        start_ticks = int(fields[19])
    except (TypeError, ValueError):
        raise ValueError("proc_stat_invalid") from None
    if parent_pid < 0 or process_group < 0 or start_ticks < 0:
        raise ValueError("proc_stat_invalid")
    return parent_pid, process_group, start_ticks


def _linux_start_epoch(start_ticks: int, boot_time: int, ticks_per_second: int) -> float:
    if (
        type(start_ticks) is not int
        or start_ticks < 0
        or type(boot_time) is not int
        or boot_time <= 0
        or type(ticks_per_second) is not int
        or ticks_per_second <= 0
    ):
        raise ValueError("proc_start_time_invalid")
    return float(boot_time) + (float(start_ticks) / ticks_per_second)


def _parse_linux_uid(value: str) -> int:
    """Read the effective UID, matching Darwin pbi_uid and proc directory ownership."""
    if not isinstance(value, str) or len(value) > MAX_PROC_FILE_BYTES:
        raise ValueError("proc_status_invalid")
    for line in value.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "Uid:":
            if not fields[2].isascii() or not fields[2].isdigit():
                break
            return int(fields[2])
    raise ValueError("proc_uid_unavailable")


def _read_comm(path: Path) -> str:
    payload = _read_bytes(path, MAX_COMM_BYTES)
    if payload.endswith(b"\n"):
        payload = payload[:-1]
    if b"\0" in payload:
        raise ValueError("process_comm_invalid")
    return os.fsdecode(payload)


def _decode_comm(value: bytes) -> str:
    if not isinstance(value, bytes) or len(value) > MAX_COMM_BYTES:
        raise ValueError("process_comm_invalid")
    return os.fsdecode(value.split(b"\0", 1)[0])


def _parse_linux_cmdline(value: bytes) -> tuple[str, ...]:
    if not isinstance(value, bytes) or len(value) > MAX_ARG_BYTES:
        raise ValueError("proc_cmdline_invalid")
    if not value:
        return ()
    arguments = value.split(b"\0")
    if arguments and arguments[-1] == b"":
        arguments.pop()
    return _bounded_argv(arguments)


def _parse_darwin_procargs(value: bytes) -> tuple[str, ...]:
    if not isinstance(value, bytes) or len(value) > MAX_PROCARGS_BYTES:
        raise ValueError("procargs_invalid")
    if len(value) < struct.calcsize("@i"):
        raise ValueError("procargs_invalid")
    argc = struct.unpack_from("@i", value, 0)[0]
    if argc < 0 or argc > MAX_ARG_COUNT:
        raise ValueError("procargs_invalid")
    if argc == 0:
        return ()
    executable_end = value.find(b"\0", struct.calcsize("@i"))
    if executable_end < 0:
        raise ValueError("procargs_invalid")
    cursor = executable_end + 1
    while cursor < len(value) and value[cursor] == 0:
        cursor += 1
    arguments: list[bytes] = []
    for _index in range(argc):
        end = value.find(b"\0", cursor)
        if end < 0:
            raise ValueError("procargs_invalid")
        arguments.append(value[cursor:end])
        cursor = end + 1
    return _bounded_argv(arguments)


def _bounded_argv(arguments: list[bytes] | tuple[bytes, ...]) -> tuple[str, ...]:
    if len(arguments) > MAX_ARG_COUNT:
        raise ValueError("process_argv_too_many")
    total_bytes = 0
    decoded: list[str] = []
    for argument in arguments:
        if not isinstance(argument, bytes) or len(argument) > MAX_ARG_LENGTH:
            raise ValueError("process_argv_item_too_large")
        total_bytes += len(argument)
        if total_bytes > MAX_ARG_BYTES:
            raise ValueError("process_argv_too_large")
        decoded.append(os.fsdecode(argument))
    return tuple(decoded)


def _read_text(path: Path, maximum: int) -> str:
    value = _read_bytes(path, maximum)
    return value.decode("ascii", "surrogateescape")


def _read_bytes(path: Path, maximum: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("process_info_field_too_large")
    return value


def _make_process_info(
    *,
    pid: int,
    ppid: int,
    pgid: int,
    uid: int,
    start_time: float,
    executable: str | None,
    argv: tuple[str, ...],
    comm: str,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        pgid=pgid,
        uid=uid,
        start_time=float(start_time),
        executable=executable,
        argv=argv,
        comm=comm,
    )
