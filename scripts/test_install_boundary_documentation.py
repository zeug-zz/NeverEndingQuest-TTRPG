# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free source contracts for installed boundary documentation."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = (
    "README.md",
    "config_template.py",
    "LMSTUDIO_QUICKSTART.txt",
    "LMSTUDIO_SETUP.md",
)


class InstallBoundaryDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {path: (ROOT / path).read_text(encoding="utf-8") for path in DOC_PATHS}
        cls.combined = "\n".join(cls.docs.values())

    def test_local_web_defaults_and_explicit_lan_pair_are_documented(self):
        self.assertIn('WEB_HOST = "127.0.0.1"', self.combined)
        self.assertIn("WEB_PORT", self.combined)
        self.assertIn("WEB_CORS_ALLOWED_ORIGINS", self.combined)
        self.assertIn("WEB_HOST controls", self.combined)
        self.assertIn("specific", self.combined)
        self.assertIn("trusted", self.combined)

    def test_docs_reject_wildcard_cors_guidance(self):
        self.assertNotIn('cors_allowed_origins="*"', self.combined)
        self.assertNotIn("WEB_CORS_ALLOWED_ORIGINS = ['*']", self.combined)
        self.assertNotIn('WEB_CORS_ALLOWED_ORIGINS = ["*"]', self.combined)
        self.assertIn("Never use a wildcard", self.combined)

    def test_lmstudio_capture_is_explicit_and_disabled_by_default(self):
        self.assertIn("NEQ_LMSTUDIO_CAPTURE_PAYLOADS=true", self.combined)
        self.assertIn("absent, blank, false, or invalid", self.combined)
        self.assertIn("disabled by default", self.combined)
        self.assertNotIn("CAPTURE_LOGS = True", self.combined)
        self.assertNotIn("CAPTURE_LOGS = False", self.combined)
        self.assertIn("No payload logs are created by default", self.combined)


if __name__ == "__main__":
    unittest.main()
