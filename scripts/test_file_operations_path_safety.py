#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - File Operations Path Safety
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

# SPDX-License-Identifier: Fair-Source-1.0

"""
Path-safety regression coverage for the [Errno 63] File name too long class.

This test guards the contract that final reconciliation artifact writes
(and any other `safe_write_json` callers) MUST NOT construct a lock or
temp path that embeds serialized JSON content from a payload accidentally
passed where a file path is expected.

The current bug in `utils.file_operations.safe_write_json` is that
`filepath = str(filepath)` silently converts a dict / list into a very
long string, which is then used to build `lock_path` and `temp_path`.
On macOS HFS+ and many other filesystems the resulting names exceed
the typical 255-character limit and trigger `[Errno 63] File name too
long` (or equivalent on Linux/Windows).

These tests do NOT depend on real OS path-length limits. They use
mocks to capture the actual path arguments passed to `os.open` and
`builtins.open` and assert that the captured path does NOT contain
any substring derived from `str(payload)`.

Expected state BEFORE Step 1.3 production fix:
  - "rejects_payload_as_filepath" tests FAIL (captured path contains
    str(payload) markers)
  - "lock_path_derivation" and "temp_path_derivation" tests PASS
  - "normal_usage" tests PASS

Expected state AFTER Step 1.3 production fix:
  - All tests PASS (the helper rejects non-path inputs before any
    lock or temp path is constructed)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.file_operations import AtomicFileWriter, safe_write_json
from utils.toolkit_final_reconciliation import (
    build_final_reconciliation_brief,
    build_final_reconciliation_report,
    persist_final_reconciliation_brief,
    persist_final_reconciliation_report,
)


def _editorial_classification():
    """Build a minimal editorial classification fixture for persist tests."""
    return {
        "status": "editorial",
        "fatal_blockers": [],
        "editorial_blockers": [
            {
                "type": "editorial",
                "message": "Required location 'X' not found in module",
                "category": "location",
            }
        ],
        "warnings": [],
        "can_attempt_final_reconciliation": True,
        "fatal_count": 0,
        "editorial_count": 1,
        "original_refusal_reason": "Required location 'X' not found in module",
        "report_paths": {},
    }


class _PathCapture:
    """Captures path arguments passed to os.open and builtins.open."""

    def __init__(self):
        self.os_open_paths = []
        self.builtins_open_paths = []

    def captured(self):
        out = [("os.open", p) for p in self.os_open_paths]
        out.extend(("open", p) for p in self.builtins_open_paths)
        return out


def _payload_markers(payload):
    """Return substrings that, if found in a path, prove the path was
    derived from str(payload).

    These are picked so that:
      - dict markers include the dict keys (e.g. "'a'")
      - list markers include the first list elements (e.g. "item_0")
      - string markers include the first 20 chars of the string

    All markers are guaranteed to be present in str(payload).
    """
    if isinstance(payload, dict):
        markers = []
        for k in list(payload.keys())[:3]:
            markers.append(f"'{k}'")
        for v in list(payload.values())[:1]:
            if isinstance(v, str) and len(v) > 20:
                markers.append(v[:20])
            elif isinstance(v, (int, float, bool)):
                markers.append(str(v))
    elif isinstance(payload, list):
        markers = [str(item) for item in payload[:3]]
    elif isinstance(payload, str):
        if len(payload) > 20:
            markers = [payload[:20]]
        else:
            markers = [payload]
    else:
        markers = []
    return [m for m in markers if m]


class TestSafeWriteJsonRejectsPayloadAsFilepath(unittest.TestCase):
    """Regression: lock/temp path must NOT be derived from str(payload).

    Bug: `safe_write_json(dict_or_list, data)` calls `str(payload)`
    inside `write_json` and then formats that string as the lock/temp
    file name, producing oversized filenames that trigger Errno 63 on
    macOS HFS+ and similar limits elsewhere.
    """

    # A dict that, when str()'d, is well over 255 chars.
    _DICT_PATH = {"a": "x" * 200, "b": "y" * 200}
    # A list that, when str()'d, is also over 255 chars.
    _LIST_PATH = ["item_" + str(i) for i in range(50)]
    # A serialized JSON-like string. The str() of a string is itself,
    # so this verifies that the helper must validate, not just str().
    _JSON_STRING_PATH = '{"large": "' + ("z" * 500) + '"}'

    def _capture_lock_and_temp_paths(self):
        """Patch os.open and builtins.open to capture paths without I/O."""
        cap = _PathCapture()

        def mock_os_open(path, *args, **kwargs):
            cap.os_open_paths.append(str(path))
            # Return a high fake fd so subsequent os.write / os.close
            # would fail with EBADF, which is caught by safe_write_json.
            return 999

        def mock_builtin_open(path, *args, **kwargs):
            cap.builtins_open_paths.append(str(path))
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.write = MagicMock()
            mock_file.flush = MagicMock()
            mock_file.fileno = MagicMock(return_value=999)
            return mock_file

        def mock_replace(src, dst):
            return None

        return (
            cap,
            patch("os.open", side_effect=mock_os_open),
            patch("builtins.open", side_effect=mock_builtin_open),
            patch("os.replace", side_effect=mock_replace),
        )

    def _assert_no_payload_markers_in_captured(self, captured, payload):
        """Assert no captured path contains any str(payload) marker.

        The spec allows two valid outcomes after the fix:

        1. Helper rejects non-path input before any os.open / builtins.open
           call, so ``captured`` is empty (the safer early-reject outcome).
        2. Helper falls through to lock/temp path construction, in which
           case every captured path must still be free of payload markers
           and bounded to < 255 characters.
        """
        markers = _payload_markers(payload)
        self.assertGreater(
            len(markers),
            0,
            "Test setup error: payload produced no markers; cannot verify bug contract.",
        )
        # Outcome 1 (safer): helper short-circuits, zero paths captured.
        # Outcome 2 (also valid): paths were captured but contain no payload markers.
        if not captured:
            return
        for source, path in captured:
            for marker in markers:
                self.assertNotIn(
                    marker,
                    path,
                    "{0} received path containing payload marker {1!r}: {2!r}".format(
                        source, marker, path[:80]
                    ),
                )
            # Bounded filesystem name contract.
            self.assertLess(
                len(path),
                255,
                "{0} path length {1} >= 255 chars (Errno 63 risk): {2!r}".format(
                    source, len(path), path[:80]
                ),
            )

    def test_dict_as_filepath_does_not_produce_payload_lock_or_temp_path(self):
        """A dict as filepath must not produce a lock/temp path containing str(dict) content."""
        cap, p1, p2, p3 = self._capture_lock_and_temp_paths()
        with p1, p2, p3:
            try:
                safe_write_json(self._DICT_PATH, {"actual": "data"})
            except Exception:
                pass
        self._assert_no_payload_markers_in_captured(cap.captured(), self._DICT_PATH)

    def test_list_as_filepath_does_not_produce_payload_lock_or_temp_path(self):
        """A list as filepath must not produce a lock/temp path containing str(list) content."""
        cap, p1, p2, p3 = self._capture_lock_and_temp_paths()
        with p1, p2, p3:
            try:
                safe_write_json(self._LIST_PATH, {"actual": "data"})
            except Exception:
                pass
        self._assert_no_payload_markers_in_captured(cap.captured(), self._LIST_PATH)

    def test_serialized_json_string_as_filepath_does_not_produce_payload_lock_or_temp_path(self):
        """A serialized JSON-like string as filepath must not be used verbatim in lock/temp path."""
        cap, p1, p2, p3 = self._capture_lock_and_temp_paths()
        with p1, p2, p3:
            try:
                safe_write_json(self._JSON_STRING_PATH, {"actual": "data"})
            except Exception:
                pass
        self._assert_no_payload_markers_in_captured(cap.captured(), self._JSON_STRING_PATH)


class TestAtomicWriterLockPathDerivation(unittest.TestCase):
    """Atomic writer lock path must be derived from filepath only."""

    def test_lock_path_is_filepath_plus_lock_suffix(self):
        """acquire_lock passes filepath + '.lock' to os.open and nothing else."""
        writer = AtomicFileWriter(max_retries=1, retry_delay=0)
        captured = []

        def mock_os_open(path, flags, *args, **kwargs):
            captured.append(str(path))
            # Simulate a lock conflict so acquire_lock retries / aborts
            raise FileExistsError("simulated lock conflict")

        with patch("os.open", side_effect=mock_os_open):
            try:
                writer.acquire_lock("/tmp/test_target.json", timeout=0.05)
            except Exception:
                pass

        self.assertGreater(len(captured), 0, "os.open should be invoked at least once")
        for path in captured:
            self.assertEqual(
                path,
                "/tmp/test_target.json.lock",
                "Lock path {0!r} should equal filepath + '.lock'".format(path),
            )


class TestAtomicWriterTempPathDerivation(unittest.TestCase):
    """Atomic writer temp path must be derived from filepath only."""

    def test_temp_path_is_filepath_plus_tmp_suffix(self):
        """write_json opens filepath + '.tmp' for write and nothing else."""
        writer = AtomicFileWriter(max_retries=1, retry_delay=0)
        captured = []

        def mock_builtin_open(path, *args, **kwargs):
            captured.append(str(path))
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.write = MagicMock()
            mock_file.flush = MagicMock()
            mock_file.fileno = MagicMock(return_value=999)
            return mock_file

        def mock_replace(src, dst):
            return None

        with patch("builtins.open", side_effect=mock_builtin_open), \
                patch("os.replace", side_effect=mock_replace):
            try:
                writer.write_json(
                    "/tmp/test_target.json",
                    {"a": 1},
                    create_backup=False,
                    acquire_lock=False,
                )
            except Exception:
                pass

        temp_paths = [p for p in captured if p.endswith(".tmp")]
        self.assertGreater(len(temp_paths), 0, "open() should be invoked with a .tmp path")
        for path in temp_paths:
            self.assertEqual(
                path,
                "/tmp/test_target.json.tmp",
                "Temp path {0!r} should equal filepath + '.tmp'".format(path),
            )


class TestNormalFinalReconciliationPersistUnaffected(unittest.TestCase):
    """Valid (workspace_dir, payload) usage must continue to work after the fix."""

    def test_persist_brief_with_valid_workspace_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            brief = build_final_reconciliation_brief(_editorial_classification())
            result = persist_final_reconciliation_brief(ws, brief)

            self.assertEqual(result["status"], "written")
            self.assertIsNone(result["error"])
            target = ws / "final_reconciliation_brief.json"
            self.assertTrue(target.exists())

            with open(target, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertIn("editorial_blockers", loaded)
            self.assertIn("version", loaded)

    def test_persist_report_with_valid_workspace_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            report = build_final_reconciliation_report(_editorial_classification())
            result = persist_final_reconciliation_report(ws, report)

            self.assertEqual(result["status"], "written")
            self.assertIsNone(result["error"])
            target = ws / "final_reconciliation_report.json"
            self.assertTrue(target.exists())

            with open(target, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertIn("status", loaded)
            self.assertIn("source_fidelity_effective_status", loaded)

    def test_safe_write_json_with_valid_string_path_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "test_artifact.json"
            result = safe_write_json(
                str(target),
                {"hello": "world"},
                create_backup=False,
                acquire_lock=False,
            )
            self.assertTrue(result)
            self.assertTrue(target.exists())
            with open(target, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, {"hello": "world"})

    def test_safe_write_json_with_valid_path_object_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "test_artifact.json"
            result = safe_write_json(
                target,
                {"hello": "world"},
                create_backup=False,
                acquire_lock=False,
            )
            self.assertTrue(result)
            self.assertTrue(target.exists())
            with open(target, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, {"hello": "world"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
