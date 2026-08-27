# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free regression tests for web media path containment."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.media_paths import resolve_media_file  # noqa: E402
import web.web_interface as web_interface  # noqa: E402


class TestMediaPathHelper(unittest.TestCase):
    def test_safe_file_and_extension_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "portrait.png"
            target.write_bytes(b"image")
            self.assertEqual(resolve_media_file("portrait.png", root, allowed_extensions={".png"}), target.resolve())
            self.assertIsNone(resolve_media_file("portrait.png", root, allowed_extensions={".jpg"}))

    def test_traversal_absolute_and_symlink_targets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "safe.png"
            target.write_bytes(b"safe")
            outside = root.parent / (root.name + "_outside.png")
            outside.write_bytes(b"outside")
            try:
                self.assertIsNone(resolve_media_file("../" + outside.name, root))
                self.assertIsNone(resolve_media_file(str(outside), root))
                self.assertIsNone(resolve_media_file("C:\\outside.png", root))
                (root / "linked.png").symlink_to(outside)
                self.assertIsNone(resolve_media_file("linked.png", root))
                linked_dir = root / "linked_dir"
                linked_dir.symlink_to(root, target_is_directory=True)
                self.assertIsNone(resolve_media_file("linked_dir/safe.png", root))
            finally:
                outside.unlink()


class TestMediaRoutes(unittest.TestCase):
    def test_safe_module_file_uses_send_file(self):
        with patch.object(web_interface, "send_file", return_value="served") as sender:
            result = web_interface.serve_toolkit_module_media(
                "A_Pottsfield_Burial", "monsters", "tomb_rats.jpg"
            )
        self.assertEqual(result, "served")
        sender.assert_called_once()

    def test_static_fallback_preserves_safe_lookup(self):
        with patch.object(web_interface, "send_file", return_value="served") as sender:
            result = web_interface.serve_toolkit_module_media(
                "Module_That_Does_Not_Exist", "monsters", "owlbear.jpg"
            )
        self.assertEqual(result, "served")
        sender.assert_called_once()

    def test_invalid_media_type_and_unsafe_requests_do_not_send(self):
        with patch.object(web_interface, "send_file") as sender:
            self.assertEqual(web_interface.serve_module_media("monsters", "../party_tracker.json"), ("Media not found", 404))
            self.assertEqual(web_interface.serve_module_media("invalid", "owlbear.jpg"), ("Invalid media type", 404))
            self.assertEqual(web_interface.serve_toolkit_module_media("../", "monsters", "owlbear.jpg"), ("Not found", 404))
            self.assertEqual(web_interface.serve_video("../secret.mp4"), ("Video not found", 404))
            self.assertEqual(web_interface.serve_icon("/outside.png"), ("Not found", 404))
        sender.assert_not_called()

    def test_video_safe_file_is_served(self):
        with patch.object(web_interface, "send_file", return_value="served") as sender:
            result = web_interface.serve_video("owlbear.mp4")
        self.assertEqual(result, "served")
        sender.assert_called_once()


if __name__ == "__main__":
    unittest.main()
