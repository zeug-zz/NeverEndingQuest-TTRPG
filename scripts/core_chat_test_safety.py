# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Process-wide fatal guards for focused core-chat contract suites.

Call ``arm_process_tripwires`` before importing a production owner. Writes are
permitted only beneath the repository-local ``tmp/`` scratch tree.
"""

import builtins
import copy
import importlib
import io
import logging
import logging.handlers
import os
import socket
import shutil
import unittest
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = (REPO_ROOT / "tmp").resolve()


class TripwireFailure(BaseException):
    """Fatal sentinel that cannot be swallowed by ordinary Exception handlers."""


def _failure(name):
    return TripwireFailure("core-chat tripwire: " + name)


def _deny(name):
    raise _failure(name)


def _inside_tmp(path):
    try:
        candidate = Path(os.fsdecode(path)).resolve()
        candidate.relative_to(TMP_ROOT)
        return True
    except (TypeError, ValueError, OSError):
        return False


def _inside_tmp_entry(path):
    """Check a directory entry without following its final symlink target."""
    try:
        candidate = Path(os.fsdecode(path))
        resolved_entry = candidate.parent.resolve() / candidate.name
        resolved_entry.relative_to(TMP_ROOT)
        return True
    except (TypeError, ValueError, OSError):
        return False


class _ProcessTripwires:
    def __init__(self):
        self.patchers = []
        self.calls = {}

    def _patch(self, name, target, **kwargs):
        try:
            patcher = mock.patch(target, side_effect=_failure(name), **kwargs)
            self.calls[name] = patcher.start()
            self.patchers.append(patcher)
        except (ImportError, AttributeError):
            return

    def arm(self):
        # Import optional transports before patching their import-time probes.
        for name in ("openai", "requests", "urllib3", "httpx", "socketio", "engineio"):
            try:
                importlib.import_module(name)
            except ImportError:
                pass

        # Owner imports construct the shared logger. Keep its file sink inert
        # under the outside-write guard; tests do not assert on log-file I/O.
        handler_patcher = mock.patch.object(
            logging.handlers, "RotatingFileHandler", lambda *args, **kwargs: logging.NullHandler()
        )
        handler_patcher.start()
        self.patchers.append(handler_patcher)

        for name, target in (
            ("openai.OpenAI", "openai.OpenAI"),
            ("socket.socket", "socket.socket"),
            ("socket.create_connection", "socket.create_connection"),
            ("urlopen", "urllib.request.urlopen"),
            ("urlretrieve", "urllib.request.urlretrieve"),
            ("http.request", "http.client.HTTPConnection.request"),
            ("https.request", "http.client.HTTPSConnection.request"),
            ("http.connect", "http.client.HTTPConnection.connect"),
            ("https.connect", "http.client.HTTPSConnection.connect"),
            ("requests.request", "requests.request"),
            ("requests.Session", "requests.sessions.Session"),
            ("requests.Session.request", "requests.sessions.Session.request"),
            ("httpx.Client", "httpx.Client"),
            ("httpx.AsyncClient", "httpx.AsyncClient"),
            ("httpx.Client.request", "httpx.Client.request"),
            ("httpx.Client.send", "httpx.Client.send"),
            ("httpx.AsyncClient.request", "httpx.AsyncClient.request"),
            ("httpx.AsyncClient.send", "httpx.AsyncClient.send"),
        ):
            self._patch(name, target)

        real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
        real_os_close = os.close
        real_mutations = {
            name: getattr(os, name)
            for name in ("mkdir", "makedirs", "remove", "unlink", "rmdir", "rename", "replace")
        }
        real_rmtree = shutil.rmtree
        real_symlink = os.symlink
        real_link = os.link
        real_os_path_mutations = {
            name: getattr(os, name) for name in ("chmod", "chown", "utime", "truncate")
        }
        real_shutil_mutations = {
            name: getattr(shutil, name)
            for name in ("copy", "copy2", "copyfile", "copytree", "copymode", "copystat", "move")
            if hasattr(shutil, name)
        }
        tracked_fds = {}

        def _fd_path(fd):
            """Return the still-live path provenance for a descriptor."""
            try:
                path, identity = tracked_fds[fd]
                current = os.fstat(fd)
                if (current.st_dev, current.st_ino) != identity:
                    tracked_fds.pop(fd, None)
                    return None
                named = os.stat(path)
                if (named.st_dev, named.st_ino) != identity:
                    tracked_fds.pop(fd, None)
                    return None
                return path
            except (KeyError, OSError, TypeError, ValueError):
                tracked_fds.pop(fd, None)
                return None

        def _path_at(path, dir_fd=None, *, follow_final=True):
            candidate = Path(os.fsdecode(path))
            if not candidate.is_absolute() and dir_fd is not None:
                base = _fd_path(dir_fd)
                if base is None:
                    return None
                candidate = base / candidate
            try:
                if follow_final:
                    return candidate.resolve()
                return candidate.parent.resolve() / candidate.name
            except (OSError, RuntimeError, ValueError):
                return None

        def _allowed_fd_path(path, dir_fd=None, *, entry=False, follow_final=True):
            resolved = _path_at(path, dir_fd, follow_final=follow_final)
            if resolved is None:
                return False
            return _inside_tmp_entry(resolved) if entry else _inside_tmp(resolved)

        def guarded_single_path(name, operation):
            def invoke(path, *args, **kwargs):
                dir_fd = kwargs.get("dir_fd")
                allowed = _inside_tmp_entry if name in ("remove", "unlink") else _inside_tmp
                if dir_fd is None:
                    permitted = allowed(path)
                else:
                    permitted = _allowed_fd_path(
                        path, dir_fd, entry=name in ("remove", "unlink"),
                        follow_final=name not in ("remove", "unlink"),
                    )
                if not permitted:
                    _deny("outside mutation: os." + name)
                return operation(path, *args, **kwargs)
            return invoke

        def guarded_two_paths(name, operation):
            def invoke(source, destination, *args, **kwargs):
                source_fd = kwargs.get("src_dir_fd")
                destination_fd = kwargs.get("dst_dir_fd")
                source_ok = (_inside_tmp_entry(source) if source_fd is None else
                             _allowed_fd_path(source, source_fd, entry=True, follow_final=False))
                destination_ok = (_inside_tmp_entry(destination) if destination_fd is None else
                                  _allowed_fd_path(destination, destination_fd, entry=True, follow_final=False))
                if not source_ok or not destination_ok:
                    _deny("outside mutation: os." + name)
                return operation(source, destination, *args, **kwargs)
            return invoke

        def guarded_symlink(source, destination, *args, **kwargs):
            # The link target may be external; creating the link itself must be in tmp.
            dir_fd = kwargs.get("dir_fd")
            allowed = (_inside_tmp_entry(destination) if dir_fd is None else
                       _allowed_fd_path(destination, dir_fd, entry=True, follow_final=False))
            if not allowed:
                _deny("outside mutation: os.symlink destination")
            return real_symlink(source, destination, *args, **kwargs)

        def guarded_link(source, destination, *args, **kwargs):
            source_fd = kwargs.get("src_dir_fd")
            destination_fd = kwargs.get("dst_dir_fd")
            # Hard-link sources follow their final symlink: validate the target
            # inode path rather than merely the in-tree symlink directory entry.
            source_ok = (_inside_tmp(source) if source_fd is None else
                         _allowed_fd_path(source, source_fd, follow_final=True))
            destination_ok = (_inside_tmp_entry(destination) if destination_fd is None else
                              _allowed_fd_path(destination, destination_fd, entry=True, follow_final=False))
            if not source_ok or not destination_ok:
                _deny("outside mutation: os.link")
            return real_link(source, destination, *args, **kwargs)

        def guarded_path_mutation(name, operation):
            def invoke(path, *args, **kwargs):
                dir_fd = kwargs.get("dir_fd")
                allowed = (_inside_tmp(path) if dir_fd is None else
                           _allowed_fd_path(path, dir_fd, follow_final=True))
                if not allowed:
                    _deny("outside mutation: os." + name)
                return operation(path, *args, **kwargs)
            return invoke

        def guarded_shutil(name, operation):
            def invoke(source, destination, *args, **kwargs):
                if not _inside_tmp(destination):
                    _deny("outside mutation: shutil." + name)
                if name == "move" and not _inside_tmp_entry(source):
                    _deny("outside mutation: shutil.move source")
                return operation(source, destination, *args, **kwargs)
            return invoke

        def guarded_rmtree(path, *args, **kwargs):
            if not _inside_tmp(path):
                _deny("outside mutation: shutil.rmtree")
            return real_rmtree(path, *args, **kwargs)

        def guarded_open(path, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+") and not _inside_tmp(path):
                _deny("outside write: builtins.open")
            return real_open(path, mode, *args, **kwargs)

        def guarded_io_open(path, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+") and not _inside_tmp(path):
                _deny("outside write: io.open")
            return real_io_open(path, mode, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            dir_fd = kwargs.get("dir_fd")
            if flags & write_flags and not (
                _inside_tmp(path) if dir_fd is None else
                _allowed_fd_path(path, dir_fd, follow_final=True)
            ):
                _deny("outside write: os.open")
            descriptor = real_os_open(path, flags, *args, **kwargs)
            try:
                resolved = _path_at(path, dir_fd, follow_final=True)
                info = os.fstat(descriptor)
                if resolved is not None:
                    tracked_fds[descriptor] = (resolved, (info.st_dev, info.st_ino))
            except (OSError, TypeError, ValueError):
                pass
            return descriptor

        def guarded_os_close(fd):
            try:
                return real_os_close(fd)
            finally:
                tracked_fds.pop(fd, None)

        for name, target, replacement in (
            ("builtins.open", "builtins.open", guarded_open),
            ("io.open", "io.open", guarded_io_open),
            ("os.open", "os.open", guarded_os_open),
        ):
            patcher = mock.patch(target, replacement)
            self.calls[name] = patcher.start()
            self.patchers.append(patcher)
        close_patcher = mock.patch("os.close", guarded_os_close)
        close_patcher.start()
        self.patchers.append(close_patcher)
        for name in ("mkdir", "makedirs", "remove", "unlink", "rmdir"):
            patcher = mock.patch("os." + name, guarded_single_path(name, real_mutations[name]))
            patcher.start()
            self.patchers.append(patcher)
        for name in ("rename", "replace"):
            patcher = mock.patch("os." + name, guarded_two_paths(name, real_mutations[name]))
            patcher.start()
            self.patchers.append(patcher)
        for name, target, replacement in (
            ("os.symlink", "os.symlink", guarded_symlink),
            ("os.link", "os.link", guarded_link),
            ("shutil.rmtree", "shutil.rmtree", guarded_rmtree),
        ):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.patchers.append(patcher)
        for name, operation in real_os_path_mutations.items():
            patcher = mock.patch("os." + name, guarded_path_mutation(name, operation))
            patcher.start()
            self.patchers.append(patcher)
        for name, operation in real_shutil_mutations.items():
            patcher = mock.patch("shutil." + name, guarded_shutil(name, operation))
            patcher.start()
            self.patchers.append(patcher)
        return self

    def assert_untouched(self, case):
        for name, guard in self.calls.items():
            if isinstance(guard, mock.Mock) and guard.call_count:
                # Do not let unittest.mock include repr(call_args) in an
                # assertion message: mocked SDK calls may contain secrets.
                case.fail("tripwire %s was invoked (%d call(s))" % (name, guard.call_count))


_ACTIVE = None


def arm_process_tripwires():
    """Arm once per unittest process; invoke before importing owner modules."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = _ProcessTripwires().arm()
    return _ACTIVE


class InMemoryUsageTracker:
    """Small process-local sink for router accounting in provider-free tests."""

    def __init__(self) -> None:
        self.records: List[Tuple[Any, Dict[str, Any]]] = []

    def track(self, response: Any, metadata: Dict[str, Any]) -> None:
        self.records.append((response, copy.deepcopy(metadata)))


def install_in_memory_usage_tracker(
    testcase: unittest.TestCase,
) -> InMemoryUsageTracker:
    """Keep accounting active while preventing tracker setup from reaching network."""
    import utils.llm_usage_tracker as usage_tracker

    tracker = InMemoryUsageTracker()
    patcher = mock.patch.object(
        usage_tracker,
        "get_global_tracker",
        return_value=tracker,
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return tracker
