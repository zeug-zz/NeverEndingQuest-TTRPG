#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free regression tests for repository path boundaries."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.repo_paths import (  # noqa: E402
    PathBoundaryError,
    repository_root,
    resolve_contained_path,
    resolve_repository_path,
)


class TestRepositoryPaths(unittest.TestCase):
    def test_root_is_derived_from_installed_source(self):
        self.assertEqual(repository_root(), PROJECT_ROOT)

    def test_alternate_cwd_does_not_change_repository_resolution(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                self.assertEqual(resolve_repository_path("data"), PROJECT_ROOT / "data")
            finally:
                os.chdir(original)

    def test_normal_relative_path_is_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "media" / "portrait.png"
            target.parent.mkdir()
            target.write_bytes(b"image")
            self.assertEqual(resolve_contained_path("media/portrait.png", root), target.resolve())

    def test_absolute_input_is_rejected_in_relative_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PathBoundaryError):
                resolve_contained_path(str(Path(directory) / "file.db"), directory)

    def test_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PathBoundaryError):
                resolve_contained_path("nested/../file.db", directory)
            with self.assertRaises(PathBoundaryError):
                resolve_contained_path("../outside.db", directory)

    def test_missing_final_target_is_allowed_but_missing_required_target_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "new" / "file.db"
            self.assertEqual(resolve_contained_path("new/file.db", directory), expected.resolve())
            with self.assertRaises(PathBoundaryError):
                resolve_contained_path("new/file.db", directory, allow_missing=False)

    def test_symlink_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / (root.name + "_outside")
            outside.write_text("outside", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(outside)
                with self.assertRaises(PathBoundaryError):
                    resolve_contained_path("link.txt", root)
            finally:
                outside.unlink()

    def test_symlink_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            (real / "file.db").write_text("db", encoding="utf-8")
            (root / "linked").symlink_to(real, target_is_directory=True)
            with self.assertRaises(PathBoundaryError):
                resolve_contained_path("linked/file.db", root)


if __name__ == "__main__":
    unittest.main()
