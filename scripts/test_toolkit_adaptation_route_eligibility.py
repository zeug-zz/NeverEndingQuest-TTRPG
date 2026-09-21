# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free eligibility and route decision tests for the toolkit LLM
adaptation lane (task 1.3 of toolkit-llm-adaptation-runtime-unification).

Verifies:

  * exact boolean True selects the background ``llm_adaptation`` route for
    eligible upload_markdown, upload_pdf, and text_description inputs;
  * missing, invalid, or exact boolean False flags resolve eligible inputs
    to the explicit legacy route and require no adaptation artifacts;
  * unsupported or invalid input metadata resolves to an explicit
    ineligible (legacy-safe) outcome;
  * a selected adaptation route is authoritative: the no-downgrade authority
    marker reports ``fallback_allowed=False``, and invalid selected-route
    metadata fails closed instead of silently resolving to legacy;
  * upload source kind/hash/title, rights, and attempt identity fields are
    preserved where supplied, and text descriptions are classified
    ``user_authored`` by Python without letting a model infer rights.

No GUI selector is involved: the operator feature flag is the only route
selector. All tests are provider-free and never rely on the live
``model_config.ENABLE_LLM_ADAPTATION`` operator value; every behavioral test
passes an explicit override or patches the module attribute.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_config as adaptation_config
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LEGACY_ACCURATE_INGEST,
    BUILD_MODE_LLM_ADAPTATION,
    INPUT_KIND_TEXT_DESCRIPTION,
    INPUT_KIND_UPLOAD_MARKDOWN,
    INPUT_KIND_UPLOAD_PDF,
    MAX_TEXT_DESCRIPTION_CHARS,
    ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED,
    ROUTE_AUTHORITY_REASON_INELIGIBLE_SAFE,
    ROUTE_AUTHORITY_REASON_LEGACY_EXPLICIT,
    ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID,
    ROUTE_DECISION_CONTRACT_VERSION,
    ROUTE_DECISION_STATUS_ADAPTATION,
    ROUTE_DECISION_STATUS_FAILED_CLOSED,
    ROUTE_DECISION_STATUS_INELIGIBLE,
    ROUTE_DECISION_STATUS_LEGACY,
    ROUTING_REASON_ATTEMPT_IDENTITY_INVALID,
    ROUTING_REASON_DISABLED,
    ROUTING_REASON_INPUT_KIND_UNSUPPORTED,
    ROUTING_REASON_REQUESTED_AND_ENABLED,
    ROUTING_REASON_RIGHTS_MISSING,
    ROUTING_REASON_RIGHTS_REVIEW_REQUIRED,
    ROUTING_REASON_TEXT_DESCRIPTION_MISSING,
    ROUTING_REASON_TEXT_DESCRIPTION_OVERSIZED,
    ROUTING_REASON_TEXT_NAME_INVALID,
    ROUTING_REASON_TEXT_NAME_MISSING,
    ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING,
    ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH,
    ROUTING_STATUS_ENABLED,
    ROUTING_STATUS_LEGACY,
    VALID_INPUT_KINDS,
    adaptation_enabled,
    resolve_adaptation_input_route,
    validate_adaptation_route_decision,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    RIGHTS_CLASS_LICENSED,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_NOT_REQUIRED,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTATION_CONFIG_PATH = REPO_ROOT / "utils" / "toolkit_adaptation_config.py"

SOURCE_HASH = "a" * 64
ELIGIBLE_UPLOAD_KINDS = (INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF)
ELIGIBLE_INPUT_KINDS = ELIGIBLE_UPLOAD_KINDS + (INPUT_KIND_TEXT_DESCRIPTION,)


def _valid_upload_kwargs(kind=INPUT_KIND_UPLOAD_MARKDOWN, **overrides):
    kwargs = {
        "input_kind": kind,
        "enabled_override": True,
        "source_kind": kind,
        "source_hash": SOURCE_HASH,
        "source_title": "Eligible Adventure Fixture",
        "rights_class": RIGHTS_CLASS_USER_AUTHORED,
        "rights_basis": "uploader_declared_user_authored",
        "rights_review_required": False,
        "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
        "attempt_id": "attempt-001",
        "job_id": "eligibility-job-001",
        "attempt_number": 1,
    }
    kwargs.update(overrides)
    return kwargs

def _valid_text_kwargs(**overrides):
    kwargs = {
        "input_kind": INPUT_KIND_TEXT_DESCRIPTION,
        "enabled_override": True,
        "module_name": "Eligible_Text_Adventure",
        "description": "A bounded magic shop adventure for the fixture suite.",
        "job_id": "eligibility-text-job",
        "attempt_number": 1,
    }
    kwargs.update(overrides)
    return kwargs


def _upload_decision(kind=INPUT_KIND_UPLOAD_MARKDOWN, **overrides):
    return resolve_adaptation_input_route(**_valid_upload_kwargs(kind=kind, **overrides))


def _text_decision(**overrides):
    return resolve_adaptation_input_route(**_valid_text_kwargs(**overrides))


class TestEnabledFlagSelectsAdaptation(unittest.TestCase):
    """Exact True selects the background adaptation route for eligible inputs."""

    def test_eligible_upload_markdown_selects_adaptation(self):
        for kind in ELIGIBLE_UPLOAD_KINDS:
            with self.subTest(input_kind=kind):
                decision = _upload_decision(kind=kind)
                self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)
                self.assertEqual(decision["route_selected"], BUILD_MODE_LLM_ADAPTATION)
                self.assertEqual(decision["route_selected"], ADAPTATION_MODE_LLM)
                self.assertEqual(
                    decision["reason"], ROUTING_REASON_REQUESTED_AND_ENABLED
                )
                self.assertIs(decision["fallback_allowed"], False)
                self.assertIs(decision["adaptation_artifacts_required"], True)
                self.assertEqual(
                    decision["flag_resolution"]["status"], ROUTING_STATUS_ENABLED
                )
                self.assertEqual(decision["eligibility"]["eligible"], True)

    def test_eligible_text_description_selects_adaptation(self):
        decision = _text_decision()
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(decision["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(
            decision["reason"], ROUTING_REASON_REQUESTED_AND_ENABLED
        )
        self.assertIs(decision["adaptation_artifacts_required"], True)

    def test_selected_adaptation_marker_is_authoritative(self):
        marker = validate_adaptation_route_decision(_upload_decision())
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertIs(marker["authoritative"], True)
        self.assertIs(marker["fallback_allowed"], False)
        self.assertIs(marker["adaptation_artifacts_required"], True)
        self.assertEqual(marker["reason"], ROUTE_AUTHORITY_REASON_ADAPTATION_SELECTED)


class TestDisabledMissingInvalidPreserveLegacy(unittest.TestCase):
    """Missing, invalid, or exact False flags preserve the legacy route."""

    def test_exact_false_preserves_legacy_for_all_eligible_inputs(self):
        for kind in ELIGIBLE_INPUT_KINDS:
            with self.subTest(input_kind=kind):
                if kind == INPUT_KIND_TEXT_DESCRIPTION:
                    decision = _text_decision(enabled_override=False)
                else:
                    decision = _upload_decision(kind=kind, enabled_override=False)
                self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_LEGACY)
                self.assertEqual(
                    decision["route_selected"], BUILD_MODE_LEGACY_ACCURATE_INGEST
                )
                self.assertEqual(decision["reason"], ROUTING_REASON_DISABLED)
                self.assertIs(decision["adaptation_artifacts_required"], False)
                self.assertEqual(
                    decision["flag_resolution"]["status"], ROUTING_STATUS_LEGACY
                )
                self.assertEqual(decision["eligibility"]["eligible"], True)

    def test_missing_flag_preserves_legacy_for_all_eligible_inputs(self):
        import model_config as model_config_module

        saved = getattr(model_config_module, "ENABLE_LLM_ADAPTATION", None)
        had_flag = hasattr(model_config_module, "ENABLE_LLM_ADAPTATION")
        if had_flag:
            del model_config_module.ENABLE_LLM_ADAPTATION
        try:
            self.assertIs(adaptation_enabled(), False)
            for kind in ELIGIBLE_INPUT_KINDS:
                with self.subTest(input_kind=kind):
                    if kind == INPUT_KIND_TEXT_DESCRIPTION:
                        decision = _text_decision(enabled_override=None)
                    else:
                        decision = _upload_decision(kind=kind, enabled_override=None)
                    self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_LEGACY)
                    self.assertEqual(decision["reason"], ROUTING_REASON_DISABLED)
                    self.assertIs(decision["adaptation_artifacts_required"], False)
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION = saved

    def test_invalid_flag_values_preserve_legacy_for_all_eligible_inputs(self):
        for junk in ("yes", "1", 1, 0, [], {}, 3.5):
            for kind in ELIGIBLE_INPUT_KINDS:
                with self.subTest(value=repr(junk), input_kind=kind):
                    if kind == INPUT_KIND_TEXT_DESCRIPTION:
                        decision = _text_decision(enabled_override=junk)
                    else:
                        decision = _upload_decision(kind=kind, enabled_override=junk)
                    self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_LEGACY)
                    self.assertEqual(decision["reason"], ROUTING_REASON_DISABLED)
                    self.assertIs(decision["adaptation_artifacts_required"], False)

    def test_legacy_decision_requires_no_adaptation_artifacts(self):
        marker = validate_adaptation_route_decision(
            _text_decision(enabled_override=False)
        )
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_LEGACY)
        self.assertIs(marker["authoritative"], True)
        self.assertIs(marker["adaptation_artifacts_required"], False)
        self.assertEqual(marker["reason"], ROUTE_AUTHORITY_REASON_LEGACY_EXPLICIT)


class TestUploadEligibility(unittest.TestCase):
    """Approved upload eligibility requires source identity plus rights."""

    def test_upload_missing_source_hash_is_ineligible(self):
        decision = _upload_decision(source_hash=None)
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertEqual(
            decision["route_selected"], BUILD_MODE_LEGACY_ACCURATE_INGEST
        )
        self.assertIn(
            ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING,
            decision["eligibility"]["reasons"],
        )
        self.assertIs(decision["adaptation_artifacts_required"], False)

    def test_upload_invalid_source_hash_is_ineligible(self):
        decision = _upload_decision(source_hash="not-a-sha256")
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_UPLOAD_SOURCE_IDENTITY_MISSING,
            decision["eligibility"]["reasons"],
        )

    def test_upload_missing_rights_is_ineligible(self):
        decision = _upload_decision(rights_class=None)
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_RIGHTS_MISSING, decision["eligibility"]["reasons"]
        )

    def test_upload_restricted_rights_remains_review_gated(self):
        decision = _upload_decision(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            rights_review_required=True,
            rights_review_status="pending",
        )
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_RIGHTS_REVIEW_REQUIRED,
            decision["eligibility"]["reasons"],
        )
        self.assertEqual(decision["route_selected"], BUILD_MODE_LEGACY_ACCURATE_INGEST)

    def test_upload_source_kind_mismatch_is_ineligible(self):
        decision = _upload_decision(
            input_kind=INPUT_KIND_UPLOAD_MARKDOWN,
            source_kind=INPUT_KIND_UPLOAD_PDF,
        )
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_UPLOAD_SOURCE_KIND_MISMATCH,
            decision["eligibility"]["reasons"],
        )

    def test_upload_invalid_attempt_identity_is_ineligible(self):
        decision = _upload_decision(attempt_id="../escape")
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_ATTEMPT_IDENTITY_INVALID,
            decision["eligibility"]["reasons"],
        )

    def test_upload_user_authored_eligible_and_preserves_identity(self):
        decision = _upload_decision()
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(decision["source_identity"]["source_kind"], INPUT_KIND_UPLOAD_MARKDOWN)
        self.assertEqual(decision["source_identity"]["source_hash"], SOURCE_HASH)
        self.assertEqual(
            decision["source_identity"]["source_hash_provenance"],
            "explicit_argument",
        )
        self.assertEqual(
            decision["source_identity"]["source_title"],
            "Eligible Adventure Fixture",
        )
        self.assertEqual(
            decision["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertIs(decision["rights"]["python_owned"], True)
        self.assertEqual(decision["rights"]["classified_by"], "python")
        self.assertEqual(decision["attempt"]["attempt_id"], "attempt-001")
        self.assertEqual(decision["attempt"]["job_id"], "eligibility-job-001")
        self.assertEqual(decision["attempt"]["attempt_number"], 1)

    def test_upload_licensed_eligible(self):
        decision = _upload_decision(rights_class=RIGHTS_CLASS_LICENSED)
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)

    def test_upload_identity_preserved_in_legacy_resolution(self):
        decision = _upload_decision(enabled_override=False)
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_LEGACY)
        self.assertEqual(decision["source_identity"]["source_hash"], SOURCE_HASH)
        self.assertEqual(
            decision["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )


class TestTextEligibility(unittest.TestCase):
    """Valid text description requires a module name plus bounded text."""

    def test_text_missing_module_name_is_ineligible(self):
        decision = _text_decision(module_name=None)
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_TEXT_NAME_MISSING, decision["eligibility"]["reasons"]
        )

    def test_text_invalid_module_name_is_ineligible(self):
        for bad_name in ("My Module", "../escape", "a/b"):
            with self.subTest(module_name=bad_name):
                decision = _text_decision(module_name=bad_name)
                self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
                self.assertIn(
                    ROUTING_REASON_TEXT_NAME_INVALID,
                    decision["eligibility"]["reasons"],
                )

    def test_text_empty_description_is_ineligible(self):
        for empty in ("", "   ", None):
            with self.subTest(description=repr(empty)):
                decision = _text_decision(description=empty)
                self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
                self.assertIn(
                    ROUTING_REASON_TEXT_DESCRIPTION_MISSING,
                    decision["eligibility"]["reasons"],
                )

    def test_text_oversized_description_is_ineligible(self):
        decision = _text_decision(description="x" * (MAX_TEXT_DESCRIPTION_CHARS + 1))
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_TEXT_DESCRIPTION_OVERSIZED,
            decision["eligibility"]["reasons"],
        )

    def test_text_valid_input_selects_adaptation(self):
        decision = _text_decision()
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(decision["text_input"]["module_name"], "Eligible_Text_Adventure")
        self.assertIs(decision["text_input"]["description_bounded"], True)
        self.assertGreater(decision["text_input"]["description_chars"], 0)
        self.assertEqual(decision["eligibility"]["eligible"], True)

    def test_text_bytes_description_is_eligible(self):
        decision = _text_decision(description="A byte description.".encode("utf-8"))
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertIs(decision["text_input"]["description_bounded"], True)

    def test_text_rights_are_python_classified_user_authored(self):
        decision = _text_decision()
        self.assertEqual(
            decision["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertEqual(
            decision["rights"]["rights_basis"], "user_submitted_text_description"
        )
        self.assertIs(decision["rights"]["python_owned"], True)
        self.assertEqual(decision["rights"]["classified_by"], "python")

    def test_text_supplied_restricted_rights_remains_review_gated(self):
        decision = _text_decision(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            rights_review_required=True,
            rights_review_status="pending",
        )
        self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
        self.assertIn(
            ROUTING_REASON_RIGHTS_REVIEW_REQUIRED,
            decision["eligibility"]["reasons"],
        )


class TestUnsupportedInputKinds(unittest.TestCase):
    """Unsupported input metadata resolves to an ineligible legacy-safe outcome."""

    def test_unsupported_kinds_are_ineligible_legacy_safe(self):
        for junk in ("upload_docx", "audio_clip", None, 123, ["upload_markdown"]):
            with self.subTest(input_kind=repr(junk)):
                decision = resolve_adaptation_input_route(
                    junk, enabled_override=True
                )
                self.assertEqual(decision["status"], ROUTE_DECISION_STATUS_INELIGIBLE)
                self.assertEqual(
                    decision["route_selected"], BUILD_MODE_LEGACY_ACCURATE_INGEST
                )
                self.assertIn(
                    ROUTING_REASON_INPUT_KIND_UNSUPPORTED,
                    decision["eligibility"]["reasons"],
                )
                self.assertIs(decision["adaptation_artifacts_required"], False)

    def test_unsupported_kind_marker_is_legacy_safe(self):
        decision = resolve_adaptation_input_route("upload_docx", enabled_override=True)
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_LEGACY)
        self.assertIs(marker["authoritative"], True)
        self.assertIs(marker["adaptation_artifacts_required"], False)
        self.assertEqual(marker["reason"], ROUTE_AUTHORITY_REASON_INELIGIBLE_SAFE)


class TestNoDowngradeAuthority(unittest.TestCase):
    """A selected adaptation route can never silently downgrade to legacy."""

    def test_tampered_fallback_allowed_fails_closed(self):
        decision = _upload_decision()
        decision["fallback_allowed"] = True
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertIs(marker["authoritative"], False)
        self.assertIs(marker["fallback_allowed"], False)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(marker["reason"], ROUTE_AUTHORITY_REASON_SELECTED_ROUTE_INVALID)
        self.assertIn("fallback_not_allowed_invariant_violated", marker["diagnostics"])

    def test_adaptation_missing_upload_identity_fails_closed(self):
        decision = _upload_decision()
        decision["source_identity"]["source_hash"] = ""
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("selected_upload_source_identity_missing", marker["diagnostics"])

    def test_adaptation_invalid_attempt_identity_fails_closed(self):
        decision = _upload_decision()
        decision["attempt"]["attempt_id"] = "../escape"
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("selected_attempt_identity_invalid", marker["diagnostics"])

    def test_adaptation_rights_not_python_owned_fails_closed(self):
        decision = _upload_decision()
        decision["rights"]["python_owned"] = False
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("selected_route_rights_not_python_owned", marker["diagnostics"])

    def test_adaptation_text_missing_description_fails_closed(self):
        decision = _text_decision()
        decision["text_input"]["description_bounded"] = False
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("selected_text_description_not_bounded", marker["diagnostics"])

    def test_non_mapping_decision_fails_closed(self):
        marker = validate_adaptation_route_decision("llm_adaptation")
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertIs(marker["authoritative"], False)
        self.assertIs(marker["fallback_allowed"], False)
        self.assertEqual(marker["route_selected"], BUILD_MODE_LLM_ADAPTATION)

    def test_unknown_status_fails_closed(self):
        marker = validate_adaptation_route_decision(
            {
                "contract_version": ROUTE_DECISION_CONTRACT_VERSION,
                "status": "mystery",
                "route_selected": BUILD_MODE_LEGACY_ACCURATE_INGEST,
                "fallback_allowed": False,
            }
        )
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertIs(marker["authoritative"], False)
        self.assertIn("route_decision_status_invalid", marker["diagnostics"])

    def test_wrong_contract_version_fails_closed(self):
        decision = _text_decision()
        decision["contract_version"] = "toolkit_adaptation_route_decision.old"
        marker = validate_adaptation_route_decision(decision)
        self.assertEqual(marker["status"], ROUTE_DECISION_STATUS_FAILED_CLOSED)
        self.assertIn("contract_version_invalid", marker["diagnostics"])


class TestDecisionBoundedAndDeterministic(unittest.TestCase):
    """Decisions are bounded, deterministic, and provider/GUI-free."""

    def test_decision_contains_no_raw_description_content(self):
        secret = "RAW_DESCRIPTION_MARKER_9f8e7d6c"
        decision = _text_decision(description="prefix " + secret + " suffix")
        encoded = json.dumps(decision)
        self.assertNotIn(secret, encoded)
        self.assertEqual(
            decision["text_input"]["description_chars"], len("prefix " + secret + " suffix")
        )

    def test_decision_is_deterministic(self):
        first = json.dumps(_upload_decision(), sort_keys=True)
        second = json.dumps(_upload_decision(), sort_keys=True)
        self.assertEqual(first, second)
        text_first = json.dumps(_text_decision(), sort_keys=True)
        text_second = json.dumps(_text_decision(), sort_keys=True)
        self.assertEqual(text_first, text_second)

    def test_resolver_has_no_model_or_gui_parameters(self):
        source = ADAPTATION_CONFIG_PATH.read_text(encoding="utf-8")
        signature = source.split("def resolve_adaptation_input_route(", 1)[1]
        signature = signature.split(") -> Dict[str, Any]:", 1)[0]
        for required in (
            "input_kind",
            "enabled_override",
            "module_name",
            "description",
            "source_hash",
            "source_kind",
        ):
            with self.subTest(parameter=required):
                self.assertIn(required, signature)
        lowered = signature.lower()
        for forbidden in ("model", "provider", "gui", "llm"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)

    def test_all_supported_kinds_are_documented(self):
        self.assertEqual(
            VALID_INPUT_KINDS,
            (INPUT_KIND_UPLOAD_MARKDOWN, INPUT_KIND_UPLOAD_PDF, INPUT_KIND_TEXT_DESCRIPTION),
        )


class TestRouteEligibilityHygiene(unittest.TestCase):
    """Changed artifacts follow SPDX, ASCII, and no-provider/path rules."""

    FORBIDDEN_TOKENS = (
        "openai",
        "create_chat_client",
        "httpx",
        "requests.get",
        "urllib.request",
        "http.client",
    )

    def test_changed_files_are_ascii_only(self):
        for path in (ADAPTATION_CONFIG_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            non_ascii = [ch for ch in text if ord(ch) >= 128]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_changed_python_files_have_spdx_header(self):
        for path in (ADAPTATION_CONFIG_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertIn("SPDX-FileCopyrightText", text)
            self.assertIn("SPDX-License-Identifier", text)

    def test_route_selection_modules_never_use_providers(self):
        text = ADAPTATION_CONFIG_PATH.read_text(encoding="utf-8")
        for token in self.FORBIDDEN_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_no_os_temp_or_absolute_scratch_paths(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("def test_no_os_temp_or_absolute_scratch_paths", 1)[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)

    @patch("model_config.ENABLE_LLM_ADAPTATION", True)
    def test_suite_never_relies_on_the_live_operator_flag(self):
        # Even when the live operator flag is True, every behavioral test in
        # this suite uses explicit overrides. This test only confirms the
        # override contract still resolves deterministically.
        self.assertIs(adaptation_enabled(enabled_override=True), True)
        self.assertIs(adaptation_enabled(enabled_override=False), False)
        self.assertIs(adaptation_enabled(enabled_override="junk"), False)


if __name__ == "__main__":
    unittest.main()
