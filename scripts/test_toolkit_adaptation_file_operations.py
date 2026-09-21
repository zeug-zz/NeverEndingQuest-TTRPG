# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free file-operation output contracts for adaptation scope."""

from __future__ import annotations

import io
import logging
import os
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout

from utils.file_operations import safe_write_json
from utils.toolkit_adaptation_output_safety import AdaptationOutputSafety


TEST_ROOT = os.path.join("tmp", "task_2_1_file_operations")


class AdaptationFileOperationOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        os.makedirs(TEST_ROOT, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def test_adaptation_write_hides_lock_and_full_paths(self) -> None:
        target = os.path.join(TEST_ROOT, "lock_path_sentinel.json")
        absolute_target = os.path.abspath(target)
        output = io.StringIO()
        errors = io.StringIO()
        root = logging.getLogger()
        handler = logging.StreamHandler(output)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                with AdaptationOutputSafety(
                    phase="adaptation_build", status="running", redirect_streams=True
                ):
                    self.assertTrue(safe_write_json(target, {"status": "ok"}))
                    self.assertTrue(safe_write_json(target, {"status": "updated"}))
            emitted = output.getvalue() + errors.getvalue()
            self.assertNotIn(target, emitted)
            self.assertNotIn(absolute_target, emitted)
            self.assertNotIn(target + ".lock", emitted)
            self.assertNotIn("lock_path_sentinel", emitted)
            self.assertNotIn(".lock", emitted)
            self.assertNotIn("[FILE_OPS]", emitted)
            self.assertNotIn("Acquired lock for " + absolute_target, emitted)
            self.assertNotIn("Created backup: " + absolute_target, emitted)
            self.assertTrue(os.path.exists(target))
            self.assertTrue(os.path.exists(target + ".bak"))
            self.assertFalse(os.path.exists(target + ".lock"))
        finally:
            root.removeHandler(handler)

    def test_legacy_write_keeps_existing_safe_lock_diagnostics(self) -> None:
        target = os.path.join(TEST_ROOT, "legacy_diagnostic.json")
        with self.assertLogs("utils.file_operations", level="DEBUG") as captured:
            self.assertTrue(safe_write_json(target, {"status": "ok"}))
        emitted = "\n".join(captured.output)
        self.assertIn("Attempting to acquire lock for", emitted)
        self.assertIn("<path>", emitted)
        self.assertNotIn(os.path.abspath(target), emitted)
        self.assertNotIn("[FILE_OPS]", emitted)
        self.assertNotIn("SOURCE_SENTINEL", emitted)


if __name__ == "__main__":
    unittest.main()
