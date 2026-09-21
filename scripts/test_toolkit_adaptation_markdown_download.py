#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - Toolkit Adaptation Markdown Download (task 8.2)
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free regression tests for the adventure Markdown download contract
in web/web_interface.py (resolve_adventure_markdown_download and the
get_module_adventure_markdown route wrapper).

Covered behavior:
- A persisted module-local MODULE_SUMMARY.md is served verbatim; the
  provider/generator is never invoked for those requests.
- Exact persisted bytes/content and the attachment filename are preserved.
- A missing summary uses the documented bounded legacy fallback exactly once
  and caches the result so subsequent requests serve the persisted file.
- A missing summary without a generator returns a controlled unavailable
  response.
- Invalid persisted summaries (too short, raw JSON, error text, unreadable)
  return explicit controlled unavailable responses and are never
  regenerated.
- Invalid generated legacy output is not served and not cached.
- Nonexistent modules fail clearly before any generator invocation.
- Route-level smoke verifies the response mapping without touching real
  module artifacts or runtime registry/campaign files.

All tests use project-local temporary directories; no live provider call is
performed.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.web_interface import (
    _validate_download_summary,
    resolve_adventure_markdown_download,
)


VALID_SUMMARY = """# The Sunken Cartographer

## Introduction

The party descends beneath the flooded market to recover the last chart of
the drowned city before the tide claims it forever.

## Plot Overview

The tide warden holds the compass chamber and will not yield it without a
ransom of fresh charts.

## Locations

The archive entrance, the warden shrine, and the drowned ledger room form a
small playable descent.

## Credits

Adapted for NEQ-TTRPG
"""


class _RecordingGenerator:
    """Deterministic provider-free fake generator that records calls."""

    def __init__(self, output=VALID_SUMMARY):
        self.output = output
        self.calls = []

    def __call__(self, module_name):
        self.calls.append(module_name)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class _RejectingGenerator(_RecordingGenerator):
    """Generator that must never be called by a served download."""

    def __call__(self, module_name):
        raise AssertionError(
            "generator invoked for {} but a persisted/invalid path should "
            "never regenerate".format(module_name)
        )


class TempModuleCase(unittest.TestCase):
    """Create a project-local fixture module root under a temp directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="tt_adapt_md_")
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.modules_root = Path(self.tmpdir) / "modules"
        self.modules_root.mkdir(parents=True, exist_ok=True)

    def make_module(self, slug, summary=None):
        module_dir = self.modules_root / slug
        module_dir.mkdir(parents=True, exist_ok=True)
        if summary is not None:
            (module_dir / "MODULE_SUMMARY.md").write_text(
                summary, encoding="utf-8"
            )
        return module_dir


class TestPersistedSummaryServed(TempModuleCase):
    """Persisted MODULE_SUMMARY.md is served verbatim without regeneration."""

    SLUG = "Fixture_Alpha"

    def test_persisted_file_served_verbatim(self):
        self.make_module(self.SLUG, VALID_SUMMARY)
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root
        )
        self.assertEqual(result["kind"], "summary")
        self.assertEqual(result["source"], "persisted")
        self.assertEqual(result["content"], VALID_SUMMARY)
        self.assertEqual(
            result["bytes"], len(VALID_SUMMARY.encode("utf-8"))
        )
        self.assertEqual(result["filename"], "Fixture_Alpha_adventure.md")

    def test_no_generator_call_when_persisted_exists(self):
        self.make_module(self.SLUG, VALID_SUMMARY)
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "summary")
        self.assertEqual(result["source"], "persisted")
        self.assertEqual(result["content"], VALID_SUMMARY)
        # Repeated requests never regenerate either.
        second = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(second["source"], "persisted")
        self.assertEqual(generator.calls, [])

    def test_persisted_bytes_preserved_with_odd_whitespace(self):
        content = "# Odd Title\n\n## Sections\n\n" + ("x" * 120) + "\n"
        self.make_module(self.SLUG, content)
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root
        )
        self.assertEqual(result["source"], "persisted")
        self.assertEqual(result["content"], content)
        self.assertEqual(result["bytes"], len(content.encode("utf-8")))


class TestLegacyFallbackBehavior(TempModuleCase):
    """Missing summaries use the bounded legacy fallback exactly once."""

    SLUG = "Fixture_Beta"

    def test_missing_summary_generates_once_then_persisted(self):
        self.make_module(self.SLUG)
        generator = _RecordingGenerator(VALID_SUMMARY)
        first = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(first["kind"], "summary")
        self.assertEqual(first["source"], "generated_legacy")
        self.assertEqual(generator.calls, [self.SLUG])
        # Result cached to disk for subsequent requests.
        summary_path = self.modules_root / self.SLUG / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        self.assertEqual(summary_path.read_text(encoding="utf-8"), VALID_SUMMARY)

        second = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(second["source"], "persisted")
        self.assertEqual(second["content"], VALID_SUMMARY)
        self.assertEqual(generator.calls, [self.SLUG])

    def test_missing_summary_without_generator_is_unavailable(self):
        self.make_module(self.SLUG)
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 404)
        self.assertEqual(result["reason"], "module_summary_missing")
        self.assertEqual(result["module"], self.SLUG)

    def test_invalid_generated_output_not_served_or_cached(self):
        self.make_module(self.SLUG)
        generator = _RecordingGenerator("tiny")
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["reason"], "summary_too_short")
        summary_path = self.modules_root / self.SLUG / "MODULE_SUMMARY.md"
        self.assertFalse(summary_path.exists())

    def test_generator_exception_returns_controlled_unavailable(self):
        self.make_module(self.SLUG)
        generator = _RecordingGenerator(RuntimeError("provider boom"))
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["reason"], "generation_failed")
        self.assertIn("provider boom", result.get("detail", ""))


class TestInvalidPersistedSummary(TempModuleCase):
    """Invalid persisted artifacts fail clearly and are never regenerated."""

    SLUG = "Fixture_Gamma"

    def test_too_short_persisted_summary(self):
        self.make_module(self.SLUG, "tiny")
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["reason"], "summary_too_short")
        self.assertEqual(generator.calls, [])

    def test_raw_json_persisted_summary(self):
        self.make_module(
            self.SLUG,
            '{"error": "provider failed", "detail": "boom", "a": 1, "b": 2,'
            ' "pad": "' + ("x" * 120) + '"}',
        )
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["reason"], "summary_contains_raw_json")
        self.assertEqual(generator.calls, [])

    def test_error_text_persisted_summary(self):
        self.make_module(
            self.SLUG,
            VALID_SUMMARY + "\nTraceback (most recent call last):\n",
        )
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["reason"], "summary_contains_error_text")
        self.assertEqual(generator.calls, [])

    def test_unreadable_persisted_summary(self):
        module_dir = self.make_module(self.SLUG)
        (module_dir / "MODULE_SUMMARY.md").write_bytes(b"\xff\xfe\x00\x01")
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            self.SLUG, modules_root=self.modules_root, generator=generator
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["reason"], "module_summary_unreadable")
        self.assertEqual(generator.calls, [])


class TestModuleResolution(TempModuleCase):
    """Module identity and missing-module failure behavior."""

    def test_nonexistent_module_404_without_generator_call(self):
        generator = _RejectingGenerator()
        result = resolve_adventure_markdown_download(
            "ZzNoSuchFixtureModule_8x9",
            modules_root=self.modules_root,
            generator=generator,
        )
        self.assertEqual(result["kind"], "unavailable")
        self.assertEqual(result["status"], 404)
        self.assertEqual(result["reason"], "Module not found")
        self.assertEqual(generator.calls, [])

    def test_invalid_module_name_400(self):
        for bad_name in ("bad!name", "bad name?", "..", "a/b"):
            result = resolve_adventure_markdown_download(
                bad_name, modules_root=self.modules_root
            )
            self.assertEqual(result["kind"], "error", bad_name)
            self.assertEqual(result["status"], 400, bad_name)
            self.assertEqual(result["reason"], "Invalid module name", bad_name)

    def test_dash_and_space_names_normalize_to_slug(self):
        module_dir = self.make_module("Fixture_Delta", VALID_SUMMARY)
        self.assertTrue(module_dir.is_dir())
        result = resolve_adventure_markdown_download(
            "Fixture Delta",
            modules_root=self.modules_root,
        )
        self.assertEqual(result["kind"], "summary")
        self.assertEqual(result["source"], "persisted")
        self.assertEqual(result["filename"], "Fixture_Delta_adventure.md")


class TestDownloadValidityHelper(unittest.TestCase):
    """Direct unit coverage for _validate_download_summary."""

    def test_valid_summary_returns_none(self):
        self.assertIsNone(_validate_download_summary(VALID_SUMMARY))

    def test_non_text_and_empty_rejected(self):
        self.assertEqual(_validate_download_summary(None), "summary_empty")
        self.assertEqual(_validate_download_summary(123), "summary_empty")
        self.assertEqual(_validate_download_summary(""), "summary_empty")
        self.assertEqual(_validate_download_summary("   "), "summary_empty")

    def test_too_short_rejected(self):
        self.assertEqual(_validate_download_summary("x"), "summary_too_short")

    def test_raw_json_rejected(self):
        raw = (
            '{"error": "provider failed", "a": 1, "b": 2, "c": 3, "pad": "'
            + ("x" * 120)
            + '"}'
        )
        self.assertEqual(
            _validate_download_summary(raw), "summary_contains_raw_json"
        )

    def test_error_text_rejected(self):
        text = VALID_SUMMARY + "\nFile \"x.py\", line 12, in main\n"
        self.assertEqual(
            _validate_download_summary(text), "summary_contains_error_text"
        )

    def test_lone_surrogate_rejected(self):
        self.assertEqual(
            _validate_download_summary("\ud800" + ("x" * 120)),
            "summary_not_utf8",
        )


class TestRouteWrapper(unittest.TestCase):
    """Flask route-level mapping without touching real module artifacts."""

    def setUp(self):
        from web.web_interface import app

        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_summary_result_maps_to_download_response(self):
        payload = {
            "kind": "summary",
            "source": "persisted",
            "content": VALID_SUMMARY,
            "bytes": len(VALID_SUMMARY.encode("utf-8")),
            "filename": "Fixture_Alpha_adventure.md",
        }
        with patch(
            "web.web_interface.resolve_adventure_markdown_download",
            return_value=payload,
        ):
            response = self.client.get(
                "/api/toolkit/modules/Fixture_Alpha/adventure.md"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), VALID_SUMMARY)
        self.assertIn(
            "text/markdown", response.headers.get("Content-Type", "")
        )
        self.assertIn(
            'attachment; filename="Fixture_Alpha_adventure.md"',
            response.headers.get("Content-Disposition", ""),
        )

    def test_unavailable_result_maps_to_controlled_error(self):
        payload = {
            "kind": "unavailable",
            "status": 404,
            "reason": "module_summary_missing",
            "module": "Fixture_Beta",
        }
        with patch(
            "web.web_interface.resolve_adventure_markdown_download",
            return_value=payload,
        ):
            response = self.client.get(
                "/api/toolkit/modules/Fixture_Beta/adventure.md"
            )
        self.assertEqual(response.status_code, 404)
        body = response.get_json() or {}
        self.assertEqual(body.get("error"), "module_summary_missing")
        self.assertEqual(body.get("module"), "Fixture_Beta")

    def test_invalid_module_name_400(self):
        response = self.client.get(
            "/api/toolkit/modules/bad%21name/adventure.md"
        )
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_module_404(self):
        # Real route: module dir missing, so no generator is invoked and the
        # response is a controlled 404.
        response = self.client.get(
            "/api/toolkit/modules/ZzNoSuchFixtureModule_8x9/adventure.md"
        )
        self.assertEqual(response.status_code, 404)
        body = response.get_json() or {}
        self.assertEqual(body.get("error"), "Module not found")


if __name__ == "__main__":
    unittest.main()
