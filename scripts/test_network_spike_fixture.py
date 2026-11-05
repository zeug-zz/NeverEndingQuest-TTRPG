# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Unit tests for the inert network spike fixture authentication helpers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "network_spike"))
import fixture_auth


class TestPassword(unittest.TestCase):
    def test_password_comparison(self):
        expected = "correct horse"
        self.assertTrue(fixture_auth.check_password(expected, expected))
        for supplied in ("wrong", None, "", expected[:-1], expected + "x"):
            with self.subTest(supplied=supplied):
                self.assertFalse(fixture_auth.check_password(supplied, expected))


class TestSessionSigner(unittest.TestCase):
    def test_expiry_and_tampering(self):
        now = [1000]
        signer = fixture_auth.SessionSigner(60, key=b"k" * 32, clock=lambda: now[0])
        token = signer.issue()
        self.assertTrue(signer.verify(token))
        now[0] = 1059
        self.assertTrue(signer.verify(token))
        now[0] = 1060
        self.assertFalse(signer.verify(token))

        payload, signature = token.split(".")
        changed_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
        changed_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        now[0] = 1000
        self.assertFalse(signer.verify(changed_payload + "." + signature))
        self.assertFalse(signer.verify(payload + "." + changed_signature))
        self.assertFalse(fixture_auth.SessionSigner(60, key=b"z" * 32).verify(token))

    def test_malformed_and_future_tokens(self):
        signer = fixture_auth.SessionSigner(60, key=b"k" * 32, clock=lambda: 1000)
        for token in ("", "a", "a.b.c", None, "x" * 2000):
            with self.subTest(token=token):
                self.assertFalse(signer.verify(token))
        future = fixture_auth.SessionSigner(60, key=b"k" * 32, clock=lambda: 1100)
        self.assertFalse(signer.verify(future.issue()))

    def test_token_part_length_is_bounded_before_decoding(self):
        oversized = "-" * 100000
        too_long_valid_alphabet = "A" * (fixture_auth._MAX_TOKEN_PART_CHARS + 4)
        self.assertIsNone(fixture_auth._decode_token_part(oversized))
        self.assertIsNone(fixture_auth._decode_token_part(too_long_valid_alphabet))

    def test_default_key_is_shared_only_within_process(self):
        first = fixture_auth.SessionSigner(60)
        second = fixture_auth.SessionSigner(60)
        self.assertTrue(second.verify(first.issue()))
        self.assertFalse(fixture_auth.SessionSigner(60, key=b"x" * 32).verify(first.issue()))

    def test_ttl_validation(self):
        for ttl in (0, True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                fixture_auth.SessionSigner(ttl)


class TestHostAndOrigin(unittest.TestCase):
    def test_host_validation(self):
        allowed = ["good.example"]
        self.assertTrue(fixture_auth.validate_host("good.example", allowed))
        self.assertTrue(fixture_auth.validate_host("GOOD.EXAMPLE", allowed))
        for host in ("evil.example", None, "", "good.example, evil.example", "good.example "):
            with self.subTest(host=host):
                self.assertFalse(fixture_auth.validate_host(host, allowed))
        self.assertTrue(fixture_auth.validate_host("127.0.0.1:8370", ["127.0.0.1:8370"]))

    def test_origin_validation(self):
        allowed = ["https://good.example"]
        self.assertTrue(fixture_auth.validate_origin("https://good.example", allowed, True))
        for origin in (
            "https://evil.example", "http://good.example", "https://good.example:444",
            "null", "https://good.example/x", "https://u@good.example",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(fixture_auth.validate_origin(origin, allowed, True))
        self.assertFalse(fixture_auth.validate_origin(None, allowed, True))
        self.assertTrue(fixture_auth.validate_origin(None, allowed, False))


class TestRequestHeaders(unittest.TestCase):
    def test_forwarding_headers_are_ignored(self):
        headers = {
            "Host": "good.example", "X-Forwarded-Host": "evil.example",
            "Forwarded": "host=evil.example", "X-Forwarded-Proto": "http",
            "X-Forwarded-For": "1.2.3.4",
        }
        host, origin = fixture_auth.extract_host_origin(headers)
        self.assertEqual((host, origin), ("good.example", None))
        self.assertTrue(fixture_auth.validate_host(host, ["good.example"]))
        host, _ = fixture_auth.extract_host_origin({"X-Forwarded-Host": "evil.example"})
        self.assertIsNone(host)
        self.assertFalse(fixture_auth.validate_host(host, ["good.example"]))

    def test_bytes_and_duplicate_identity_headers(self):
        self.assertEqual(
            fixture_auth.extract_host_origin({b"hOsT": b"good.example", b"ORIGIN": b"https://good.example"}),
            ("good.example", "https://good.example"),
        )
        with self.assertRaises(ValueError):
            fixture_auth.extract_host_origin({"Host": "a", "host": "b"})


class TestCookies(unittest.TestCase):
    def test_cookie_attributes_and_validation(self):
        cookie = fixture_auth.build_session_cookie("s", "abc", 600)
        self.assertTrue(cookie.startswith("s=abc;"))
        for attribute in ("Secure", "HttpOnly", "SameSite=Strict", "Max-Age=600", "Path=/"):
            self.assertIn(attribute, cookie)
        with self.assertRaises(ValueError):
            fixture_auth.build_session_cookie("s", "a;b", 600)
        with self.assertRaises(ValueError):
            fixture_auth.build_session_cookie("s", "abc", -1)
        cleared = fixture_auth.clear_session_cookie("s")
        self.assertIn("Max-Age=0", cleared)
        for attribute in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cleared)


class TestLoopbackBind(unittest.TestCase):
    def test_only_ipv4_loopback_is_allowed(self):
        self.assertIsNone(fixture_auth.ensure_loopback_bind("127.0.0.1"))
        for host in ("0.0.0.0", "localhost", "::", "::1", "192.168.1.5", ""):
            with self.subTest(host=host), self.assertRaises(ValueError):
                fixture_auth.ensure_loopback_bind(host)


if __name__ == "__main__":
    unittest.main(verbosity=2)
