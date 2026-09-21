# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for the toolkit adaptation dossier."""

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_dossier as dossier_contract
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_FAILED,
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    ADAPTATION_DOSSIER_VERSION,
    ADAPTATION_MODE_LLM,
    ADAPTATION_NOTICE,
    DIAGNOSTIC_CODE_INVALID_ENUM,
    DIAGNOSTIC_CODE_INVALID_JSON,
    DIAGNOSTIC_CODE_INVALID_LEVEL_RANGE,
    DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA,
    DIAGNOSTIC_CODE_INVALID_SOURCE_HASH,
    DIAGNOSTIC_CODE_INVALID_TYPE,
    DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD,
    DIAGNOSTIC_CODE_UNEXPECTED_FIELD,
    PUBLICATION_STATUS_NOT_EVALUATED,
    REQUIRED_ADAPTATION_DOSSIER_FIELDS,
    VALID_ADAPTATION_DOSSIER_STATUSES,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
    VALID_SOURCE_PROFILES,
    parse_adaptation_dossier,
    validate_adaptation_dossier,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_FIXTURE_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)


def _load_fixture():
    with VALID_FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _diagnostic_codes(result):
    return {item.get("code") for item in result.get("diagnostics", [])}


class TestAdaptationDossierSchema(unittest.TestCase):
    """The dossier schema exposes a strict, versioned handoff contract."""

    def test_schema_file_is_machine_checkable(self):
        schema = dossier_contract.load_adaptation_dossier_schema()
        self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")
        self.assertEqual(schema["$id"].split("/")[-1], "toolkit_adaptation_dossier.v1.json")
        self.assertEqual(schema["properties"]["version"]["enum"], [ADAPTATION_DOSSIER_VERSION])
        self.assertEqual(
            schema["properties"]["adaptation_mode"]["enum"],
            [ADAPTATION_MODE_LLM],
        )
        self.assertEqual(
            schema["properties"]["adaptation_notice"]["enum"],
            [ADAPTATION_NOTICE],
        )

    def test_required_fields_cover_authoring_contract(self):
        schema = dossier_contract.load_adaptation_dossier_schema()
        self.assertEqual(
            tuple(schema["required"]),
            REQUIRED_ADAPTATION_DOSSIER_FIELDS,
        )
        self.assertNotIn("puzzle_or_trial_seeds", schema["required"])
        self.assertTrue(schema["additionalProperties"] is False)

    def test_source_profiles_statuses_and_rights_values_are_explicit(self):
        schema = dossier_contract.load_adaptation_dossier_schema()
        self.assertEqual(
            tuple(schema["properties"]["source_profile"]["enum"]),
            VALID_SOURCE_PROFILES,
        )
        self.assertEqual(
            tuple(schema["properties"]["status"]["enum"]),
            VALID_ADAPTATION_DOSSIER_STATUSES,
        )
        self.assertEqual(
            tuple(schema["properties"]["rights_class"]["enum"]),
            VALID_RIGHTS_CLASSES,
        )
        self.assertEqual(
            tuple(schema["properties"]["rights_review_status"]["enum"]),
            VALID_RIGHTS_REVIEW_STATUSES,
        )


class TestAdaptationDossierParser(unittest.TestCase):
    """The provider-free parser is fail-closed and returns diagnostics."""

    def setUp(self):
        self.fixture = _load_fixture()

    def test_valid_mapping_is_normalized_and_usable_for_build(self):
        original = copy.deepcopy(self.fixture)
        result = parse_adaptation_dossier(self.fixture)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["dossier_status"], ADAPTATION_DOSSIER_STATUS_READY)
        self.assertTrue(result["build_ready"])
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["publication_status"], PUBLICATION_STATUS_NOT_EVALUATED)
        self.assertNotIn("publication_success", result)
        self.assertEqual(self.fixture, original)

    def test_valid_json_string_is_accepted(self):
        result = parse_adaptation_dossier(json.dumps(self.fixture, sort_keys=True))
        self.assertTrue(result["valid"])
        self.assertEqual(result["dossier"]["source_profile"], "catalogue")

    def test_missing_optional_puzzle_seeds_remains_valid(self):
        payload = copy.deepcopy(self.fixture)
        payload.pop("puzzle_or_trial_seeds")
        result = parse_adaptation_dossier(payload)
        self.assertTrue(result["valid"])

    def test_status_values_are_known_but_only_ready_is_build_ready(self):
        for status in (
            ADAPTATION_DOSSIER_STATUS_REFUSED,
            ADAPTATION_DOSSIER_STATUS_FAILED,
        ):
            payload = copy.deepcopy(self.fixture)
            payload["status"] = status
            result = parse_adaptation_dossier(payload)
            self.assertTrue(result["valid"])
            self.assertFalse(result["build_ready"])
            self.assertEqual(result["dossier_status"], status)

    def test_malformed_json_is_rejected(self):
        result = parse_adaptation_dossier('{"version":')
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_JSON, _diagnostic_codes(result))

    def test_empty_json_is_rejected(self):
        result = parse_adaptation_dossier("")
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_JSON, _diagnostic_codes(result))

    def test_non_object_json_is_rejected(self):
        result = parse_adaptation_dossier("[]")
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_TYPE, _diagnostic_codes(result))

    def test_incomplete_dossier_reports_missing_fields(self):
        payload = {"version": ADAPTATION_DOSSIER_VERSION}
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD, _diagnostic_codes(result))
        messages = " ".join(item["message"] for item in result["diagnostics"])
        self.assertIn("adapted_title", messages)
        self.assertIn("rights_class", messages)

    def test_unknown_status_profile_and_rights_enum_values_are_rejected(self):
        for field, value in (
            ("status", "complete"),
            ("source_profile", "catalog"),
            ("rights_class", "unknown_rights"),
            ("rights_review_status", "unknown_review"),
        ):
            payload = copy.deepcopy(self.fixture)
            payload[field] = value
            result = parse_adaptation_dossier(payload)
            self.assertFalse(result["valid"], field)
            self.assertIn(DIAGNOSTIC_CODE_INVALID_ENUM, _diagnostic_codes(result))

    def test_wrong_adaptation_mode_and_extra_field_are_rejected(self):
        payload = copy.deepcopy(self.fixture)
        payload["adaptation_mode"] = "accurate_ingest"
        payload["unexpected"] = True
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        codes = _diagnostic_codes(result)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_ENUM, codes)
        self.assertIn(DIAGNOSTIC_CODE_UNEXPECTED_FIELD, codes)

    def test_source_hash_and_level_range_are_rejected_when_malformed(self):
        payload = copy.deepcopy(self.fixture)
        payload["source_hash"] = "not-a-sha256"
        payload["level_range"] = {"min": 8, "max": 2}
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        codes = _diagnostic_codes(result)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_HASH, codes)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_LEVEL_RANGE, codes)

    def test_wrong_nested_types_are_rejected(self):
        payload = copy.deepcopy(self.fixture)
        payload["areas"] = "not an array"
        payload["plot_objective"] = []
        payload["rights_review_required"] = "false"
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_TYPE, _diagnostic_codes(result))

    def test_missing_rights_metadata_and_inconsistent_review_are_rejected(self):
        for field in (
            "rights_class",
            "rights_basis",
            "rights_review_required",
            "rights_review_status",
        ):
            payload = copy.deepcopy(self.fixture)
            payload.pop(field)
            result = parse_adaptation_dossier(payload)
            self.assertFalse(result["valid"], field)
            codes = _diagnostic_codes(result)
            self.assertTrue(
                DIAGNOSTIC_CODE_MISSING_REQUIRED_FIELD in codes
                or DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA in codes
            )

        payload = copy.deepcopy(self.fixture)
        payload["rights_review_required"] = True
        payload["rights_review_status"] = "not_required"
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA, _diagnostic_codes(result))

        payload = copy.deepcopy(self.fixture)
        payload["rights_class"] = "third_party_copyright_restricted"
        payload["rights_review_required"] = False
        payload["rights_review_status"] = "not_required"
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_RIGHTS_METADATA, _diagnostic_codes(result))

    def test_exact_adaptation_notice_is_required(self):
        payload = copy.deepcopy(self.fixture)
        payload["adaptation_notice"] = "Adapted for NeverEndingQuest"
        result = parse_adaptation_dossier(payload)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_INVALID_ENUM, _diagnostic_codes(result))

    def test_normalization_does_not_repair_missing_or_invalid_content(self):
        payload = copy.deepcopy(self.fixture)
        payload["source_title"] = "  The Lantern Catalogue  "
        payload.pop("areas")
        normalized = dossier_contract.normalize_adaptation_dossier(payload)
        self.assertEqual(normalized["source_title"], "The Lantern Catalogue")
        self.assertNotIn("areas", normalized)
        result = validate_adaptation_dossier(normalized)
        self.assertFalse(result["valid"])


class TestProviderFreeBoundary(unittest.TestCase):
    """The contract utility has no provider or persistence responsibilities."""

    def test_source_has_no_provider_or_write_dependencies(self):
        source = inspect.getsource(dossier_contract)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("safe_write_json", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("openai", source.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
