# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Chat Generate Image Response Format Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Tests for chat image generation response-format compatibility,
covering base64 image data, URL responses, explicit error handling,
and frontend loading-state recovery.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGenerateImageSourceContracts(unittest.TestCase):
    """Source-contract tests for the chat image handler."""

    @staticmethod
    def _read_web_interface_source() -> str:
        web_interface_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "web",
            "web_interface.py",
        )
        with open(web_interface_path, "r") as handle:
            return handle.read()

    def test_handler_uses_convert_helper(self):
        """Handler uses conversion helper, not direct response field access."""
        source = self._read_web_interface_source()
        self.assertIn("convert_image_response_payload(response)", source)
        self.assertNotIn("response.data[0].url", source)

    def test_handler_uses_url_source_guard_for_requests_get(self):
        """requests.get is routed through URL source guard."""
        source = self._read_web_interface_source()
        if "requests.get" in source:
            req_pos = source.index("requests.get")
            guard_pos = source.find('elif image_source == "url"')
            self.assertGreater(guard_pos, 0)
            self.assertLess(guard_pos, req_pos)

    def test_handler_emits_browser_source(self):
        """Handler emits browser_source through image_url field."""
        source = self._read_web_interface_source()
        self.assertIn("'image_url': browser_source", source)


class TestConvertImageResponsePayloadHelper(unittest.TestCase):
    """Behavior tests for pure response conversion helper."""

    def test_base64_payload_returns_data_url_and_bytes(self):
        """Helper returns browser_source/image_bytes/source for base64 responses."""
        import base64 as b64
        from utils.image_response_payload import convert_image_response_payload

        raw = b"png-bytes"
        encoded = b64.b64encode(raw).decode("ascii")

        mock_response = MagicMock()
        mock_data_point = MagicMock(url=None, b64_json=encoded)
        mock_response.data = [mock_data_point]

        payload = convert_image_response_payload(mock_response)
        self.assertEqual(payload["source"], "base64")
        self.assertEqual(payload["image_bytes"], raw)
        self.assertTrue(payload["browser_source"].startswith("data:image/png;base64,"))

    def test_url_payload_returns_url_source(self):
        """Helper returns URL browser source and no bytes for URL responses."""
        from utils.image_response_payload import convert_image_response_payload

        url = "https://example.com/image.png"
        mock_response = MagicMock()
        mock_data_point = MagicMock(url=url, b64_json=None)
        mock_response.data = [mock_data_point]

        payload = convert_image_response_payload(mock_response)
        self.assertEqual(payload["source"], "url")
        self.assertIsNone(payload["image_bytes"])
        self.assertEqual(payload["browser_source"], url)

    def test_missing_data_raises_value_error(self):
        """Helper raises ValueError when neither url nor b64_json exists."""
        from utils.image_response_payload import convert_image_response_payload

        mock_response = MagicMock()
        mock_data_point = MagicMock(url=None, b64_json=None)
        mock_response.data = [mock_data_point]

        with self.assertRaises(ValueError):
            convert_image_response_payload(mock_response)

    def test_invalid_base64_raises_value_error(self):
        """Helper raises ValueError for invalid base64 payloads."""
        from utils.image_response_payload import convert_image_response_payload

        mock_response = MagicMock()
        mock_data_point = MagicMock(url=None, b64_json="***not-base64***")
        mock_response.data = [mock_data_point]

        with self.assertRaises(ValueError):
            convert_image_response_payload(mock_response)


class TestExtractImageDataHelper(unittest.TestCase):
    """Test the extract_image_data helper function."""

    def test_extract_url_b64_both_present(self):
        """Helper returns both url and b64_json when both present."""
        from utils.image_response_payload import extract_image_data

        mock_response = MagicMock()
        mock_data_point = MagicMock(
            url="https://example.com/img.png",
            b64_json="aGVsbG8=",
        )
        mock_response.data = [mock_data_point]

        url, b64 = extract_image_data(mock_response)
        self.assertEqual(url, "https://example.com/img.png")
        self.assertEqual(b64, "aGVsbG8=")

    def test_extract_neither_present(self):
        """Helper returns (None, None) when neither field present."""
        from utils.image_response_payload import extract_image_data

        mock_response = MagicMock()
        mock_response.data = []

        url, b64 = extract_image_data(mock_response)
        self.assertIsNone(url)
        self.assertIsNone(b64)

    def test_extract_url_only(self):
        """Helper returns url and None for URL-only response."""
        from utils.image_response_payload import extract_image_data

        mock_response = MagicMock()
        mock_data_point = MagicMock(url="https://example.com/img.png", b64_json=None)
        mock_response.data = [mock_data_point]

        url, b64 = extract_image_data(mock_response)
        self.assertEqual(url, "https://example.com/img.png")
        self.assertIsNone(b64)


class TestGenerateImageFrontendErrorHandler(unittest.TestCase):
    """Frontend source-contract tests for loading-state recovery."""

    def test_error_handler_selector_matches_loading_image_class(self):
        """Error handler uses loading-image class and removes it."""
        html_path = os.path.join(
            os.path.dirname(__file__), "..", "web", "templates", "game_interface.html"
        )

        with open(html_path, "r") as handle:
            html_source = handle.read()

        self.assertIn("classList.add('loading-image')", html_source)

        error_handler_start = html_source.index("socket.on('image_generation_error'")
        error_handler_end = html_source.index("});", error_handler_start) + 3
        error_block = html_source[error_handler_start:error_handler_end]

        self.assertIn("loading-image", error_block)
        self.assertNotIn("'.loading'", error_block)
        self.assertIn("classList.remove('loading-image')", error_block)

    def test_image_generated_handler_uses_loading_image(self):
        """image_generated handler also uses loading-image class."""
        html_path = os.path.join(
            os.path.dirname(__file__), "..", "web", "templates", "game_interface.html"
        )

        with open(html_path, "r") as handle:
            html_source = handle.read()

        start = html_source.index("socket.on('image_generated'")
        end = html_source.index("});", start) + 3
        block = html_source[start:end]

        self.assertIn("loading-image", block)
        self.assertIn("classList.remove('loading-image')", block)


if __name__ == "__main__":
    unittest.main()
