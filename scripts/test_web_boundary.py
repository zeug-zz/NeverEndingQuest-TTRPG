# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free tests for installed web host and Socket.IO boundaries."""

import unittest

from utils.web_boundary import resolve_socketio_origins, resolve_web_host


class TestWebBoundary(unittest.TestCase):
    def test_host_defaults_and_invalid_values_fail_closed(self):
        for value in (None, "", "   ", "0.0.0.0", "::", "http://example.com", "bad host"):
            self.assertEqual(resolve_web_host(value), "127.0.0.1")

    def test_local_and_explicit_lan_hosts(self):
        self.assertEqual(resolve_web_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(resolve_web_host("192.168.1.25"), "192.168.1.25")
        self.assertEqual(resolve_web_host("tabletop-laptop"), "tabletop-laptop")

    def test_default_origins_are_finite_and_keep_port(self):
        origins = resolve_socketio_origins(None, 9123)
        self.assertEqual(origins, [
            "http://localhost:9123",
            "http://127.0.0.1:9123",
            "http://[::1]:9123",
        ])
        self.assertNotIn("*", origins)

    def test_explicit_origins_are_preserved_without_expansion(self):
        origins = resolve_socketio_origins(["http://192.168.1.25:9123"], 9123)
        self.assertEqual(origins, ["http://192.168.1.25:9123"])

    def test_explicit_csv_origins_are_preserved_without_expansion(self):
        origins = resolve_socketio_origins(
            "http://192.168.1.25:9123, https://tabletop.example:9443", 9123
        )
        self.assertEqual(
            origins,
            ["http://192.168.1.25:9123", "https://tabletop.example:9443"],
        )

    def test_unsafe_or_malformed_origins_use_loopback_default(self):
        for value in ("", "*", ["http://192.168.1.25:9123", "*"], ["not-an-origin"]):
            origins = resolve_socketio_origins(value, 9123)
            self.assertEqual(origins[0], "http://localhost:9123")
            self.assertNotIn("*", origins)


if __name__ == "__main__":
    unittest.main()
