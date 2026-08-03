#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Tests for calendar normalization utility and prompt "Hammer" removal.
"""

import inspect
import json
import os
import tempfile
import unittest
from typing import Any, Dict


class TestCalendarNormalization(unittest.TestCase):
    """Tests for calendar normalization build-time behavior."""

    def _write_bu_file(self, module_dir: str, data: Dict[str, Any]) -> str:
        """Write party_tracker_BU.json and return its path."""
        path = os.path.join(module_dir, "party_tracker_BU.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def _write_runtime_file(self, module_dir: str, data: Dict[str, Any]) -> str:
        """Write party_tracker.json (runtime) and return its path."""
        path = os.path.join(module_dir, "party_tracker.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def _read_bu_month(self, module_dir: str) -> str:
        """Read month from party_tracker_BU.json."""
        path = os.path.join(module_dir, "party_tracker_BU.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("worldConditions", {}).get("month", "")

    def _read_runtime_month(self, module_dir: str) -> str:
        """Read month from party_tracker.json."""
        path = os.path.join(module_dir, "party_tracker.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("worldConditions", {}).get("month", "")

    def setUp(self):
        """Import the module under test, create temp directory."""
        from utils.calendar_normalization import normalize_party_calendar
        self._normalize = normalize_party_calendar
        self._tmpdir = tempfile.mkdtemp(prefix="test_cal_norm_")

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # --- Known invalid month tests ---

    def test_known_invalid_month_hammer_normalized(self):
        """Hammer -> Firstmonth, status changed, BU file updated."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Hammer",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["month_before"], "Hammer")
        self.assertEqual(result["month_after"], "Firstmonth")
        self.assertEqual(result["reason"], "month_normalized")
        self.assertEqual(self._read_bu_month(self._tmpdir), "Firstmonth")

    def test_known_invalid_month_alturiak_normalized(self):
        """Alturiak -> Coldmonth, status changed."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Alturiak",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["month_before"], "Alturiak")
        self.assertEqual(result["month_after"], "Coldmonth")
        self.assertEqual(result["reason"], "month_normalized")
        self.assertEqual(self._read_bu_month(self._tmpdir), "Coldmonth")

    # --- Valid month tests ---

    def test_valid_month_not_changed(self):
        """Already-valid month -> skipped, file unchanged."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Springmonth",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "month_already_valid")
        self.assertEqual(result["month_before"], "Springmonth")
        self.assertEqual(result["month_after"], "Springmonth")
        # File unchanged
        self.assertEqual(self._read_bu_month(self._tmpdir), "Springmonth")

    # --- Unknown invalid month tests ---

    def test_unknown_invalid_month_fails_closed(self):
        """Unknown invalid month -> status failed, file unchanged."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Frobnar",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "unknown_invalid_month")
        self.assertEqual(result["month_before"], "Frobnar")
        self.assertIsNone(result["month_after"])
        # File unchanged
        self.assertEqual(self._read_bu_month(self._tmpdir), "Frobnar")

    # --- Missing BU file tests ---

    def test_missing_party_tracker_BU_skipped(self):
        """No party_tracker_BU.json -> skipped."""
        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "party_tracker_BU_missing")
        self.assertIsNone(result["month_before"])
        self.assertIsNone(result["month_after"])

    # --- Runtime non-mutation tests ---

    def test_runtime_party_tracker_not_mutated(self):
        """party_tracker_BU.json changes, party_tracker.json unchanged."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Hammer",
                "year": 1492,
                "day": 1,
            },
        }
        runtime_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "Hammer",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)
        self._write_runtime_file(self._tmpdir, runtime_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "changed")
        self.assertEqual(self._read_bu_month(self._tmpdir), "Firstmonth")
        # Runtime file MUST NOT be changed
        self.assertEqual(self._read_runtime_month(self._tmpdir), "Hammer")

    # --- Empty / missing month tests ---

    def test_empty_month_normalized_to_default(self):
        """Empty month string -> defaulted to Firstmonth."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": "",
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["month_after"], "Firstmonth")
        self.assertEqual(result["reason"], "empty_month_defaulted")
        self.assertEqual(self._read_bu_month(self._tmpdir), "Firstmonth")

    def test_missing_month_key_normalized_to_default(self):
        """Missing month key -> defaulted to Firstmonth."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["month_after"], "Firstmonth")
        self.assertEqual(result["reason"], "empty_month_defaulted")
        self.assertEqual(self._read_bu_month(self._tmpdir), "Firstmonth")

    # --- Non-string month tests ---

    def test_non_string_month_fails_closed(self):
        """Integer month value -> status failed, file unchanged."""
        bu_data = {
            "module": "Test Module",
            "worldConditions": {
                "month": 42,
                "year": 1492,
                "day": 1,
            },
        }
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "non_string_month")
        # File unchanged
        with open(os.path.join(self._tmpdir, "party_tracker_BU.json"), "r") as f:
            saved = json.load(f)
        self.assertEqual(saved["worldConditions"]["month"], 42)

    # --- Invalid BU file tests ---

    def test_invalid_BU_file_fails_closed(self):
        """Non-dict BU file -> status failed."""
        path = os.path.join(self._tmpdir, "party_tracker_BU.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not valid json content")

        from utils.calendar_normalization import normalize_party_calendar
        result = normalize_party_calendar(self._tmpdir)

        self.assertEqual(result["status"], "failed")
        self.assertIn(result["reason"], ("invalid_BU_file", "write_failed"))

    def test_missing_world_conditions_fails_closed(self):
        """BU file missing worldConditions -> status failed."""
        bu_data = {"module": "Test Module", "partyMembers": []}
        self._write_bu_file(self._tmpdir, bu_data)

        result = self._normalize(self._tmpdir)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "worldConditions_missing")


class TestPromptHammerRemoval(unittest.TestCase):
    """Tests confirming prompt files no longer contain "Hammer" as a valid month default."""

    def _read_source(self, module_path: str) -> str:
        """Read source file and return content."""
        repo_root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        full_path = os.path.join(repo_root, module_path)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_module_builder_no_hammer_in_template(self):
        """module_builder.py template uses 'Firstmonth', not 'Hammer'."""
        source = self._read_source("core/generators/module_builder.py")
        self.assertIn('"month": "Firstmonth"', source)
        self.assertNotIn('"month": "Hammer"', source)

    def test_location_generator_no_hammer_in_example(self):
        """location_generator.py example uses 'Firstmonth', not 'Hammer'."""
        source = self._read_source("core/generators/location_generator.py")
        self.assertIn('"month": "Firstmonth"', source)
        self.assertNotIn('"month": "Hammer"', source)

    def test_seed_writer_default_not_hammer(self):
        """seed_writer.py default uses 'Firstmonth', not 'Hammer'."""
        source = self._read_source("utils/toolkit_blueprint_seed_writer.py")
        self.assertIn('else "Firstmonth"', source)
        self.assertNotIn('else "Hammer"', source)


if __name__ == "__main__":
    unittest.main()
