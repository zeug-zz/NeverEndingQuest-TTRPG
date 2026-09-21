# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the toolkit adaptation runtime envelope
(task 1.2 of toolkit-llm-adaptation-runtime-unification).

The suite locks the shared Python-owned runtime envelope and adapter boundary
in web/extensions/toolkit_adaptation_runtime.py:

  * input-kind normalization: upload_markdown, upload_pdf, text_description;
  * stable lowercase SHA-256 source identity with bounded source context;
  * Python-owned rights metadata that provider data can never override;
  * attempt / job / revision identity;
  * bounded world-context provenance and fallback status;
  * project-relative staging metadata without credentials or raw source;
  * deterministic canonical serialization (same logical input -> identical
    bytes) and explicit bounds, redaction, and fail-closed rejection.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_runtime_envelope/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The one
functional staging test reserves a real staging target inside that scratch
root through the existing staging helper and verifies the envelope carries
only the project-relative target path. No module, registry, campaign, or
runtime state is touched.

All tests are provider-free: they exercise the deterministic envelope builder,
the existing source-context / world-context / staging / attempt helpers, and
the local validator. No provider or network call occurs and no GUI mode is
required.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_artifacts import build_attempt_id
from utils.toolkit_adaptation_dossier import (
    RIGHTS_CLASS_LICENSED,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_APPROVED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
)
from utils.toolkit_adaptation_source_context import MAX_RAW_SOURCE_CHARS
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_adaptation_world_context import build_world_narrative_context

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_runtime_envelope"
RUNTIME_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"
)

FIXTURE_TEXT = "A modest adventure about the Sunken Lighthouse and its keeper."
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

UPLOAD_RIGHTS = {
    "rights_class": RIGHTS_CLASS_USER_AUTHORED,
    "rights_basis": "approved test upload fixture",
    "rights_review_required": False,
    "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _upload_envelope(**overrides: Any) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "input_kind": runtime.INPUT_KIND_UPLOAD_MARKDOWN,
        "source_text": FIXTURE_TEXT,
        "source_title": "Sunken Lighthouse",
        "source_path": "uploads/fixture.md",
        "source_summary": "Bounded summary for the envelope tests.",
        "rights_class": UPLOAD_RIGHTS["rights_class"],
        "rights_basis": UPLOAD_RIGHTS["rights_basis"],
        "rights_review_required": UPLOAD_RIGHTS["rights_review_required"],
        "rights_review_status": UPLOAD_RIGHTS["rights_review_status"],
        "job_id": "envelope-job",
    }
    options.update(overrides)
    return runtime.build_adaptation_runtime_envelope(**options)


def _text_envelope(**overrides: Any) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "input_kind": runtime.INPUT_KIND_TEXT_DESCRIPTION,
        "source_text": FIXTURE_TEXT,
        "source_title": "Text Concept",
    }
    options.update(overrides)
    return runtime.build_adaptation_runtime_envelope(**options)


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)


class TestInputKindNormalization(unittest.TestCase):
    """All supported input kinds normalize to a ready envelope."""

    def test_upload_markdown_ready(self):
        envelope = _upload_envelope()
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["input_kind"], runtime.INPUT_KIND_UPLOAD_MARKDOWN)

    def test_upload_pdf_ready(self):
        envelope = _upload_envelope(input_kind=runtime.INPUT_KIND_UPLOAD_PDF)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["input_kind"], runtime.INPUT_KIND_UPLOAD_PDF)

    def test_text_description_ready(self):
        envelope = _text_envelope()
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["input_kind"], runtime.INPUT_KIND_TEXT_DESCRIPTION)

    def test_kind_case_is_normalized(self):
        envelope = _upload_envelope(input_kind="Upload_Markdown")
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["input_kind"], runtime.INPUT_KIND_UPLOAD_MARKDOWN)

    def test_unsupported_kind_fails_closed(self):
        for bad_kind in ("upload_docx", "scanned_notes", ""):
            with self.subTest(input_kind=bad_kind):
                envelope = runtime.build_adaptation_runtime_envelope(bad_kind)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("invalid_input_kind", codes)

    def test_non_string_kind_fails_closed(self):
        for bad_kind in (None, 7, ["upload_markdown"]):
            with self.subTest(input_kind=repr(bad_kind)):
                envelope = runtime.build_adaptation_runtime_envelope(bad_kind)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)


class TestStableSourceIdentityAndHash(unittest.TestCase):
    """Source identity is a stable lowercase SHA-256 over the raw text."""

    def test_hash_is_lowercase_sha256_of_utf8_text(self):
        envelope = _upload_envelope()
        identity = envelope["source_identity"]
        self.assertEqual(identity["source_hash"], _sha256(FIXTURE_TEXT))
        self.assertEqual(identity["source_hash"], FIXTURE_HASH)
        self.assertEqual(identity["source_hash"], identity["source_hash"].lower())
        self.assertEqual(len(identity["source_hash"]), 64)
        self.assertEqual(identity["source_hash_provenance"], "raw_source")

    def test_same_text_same_hash(self):
        first = _upload_envelope()
        second = _upload_envelope()
        self.assertEqual(
            first["source_identity"]["source_hash"],
            second["source_identity"]["source_hash"],
        )

    def test_explicit_hash_preserved_when_matching(self):
        envelope = _upload_envelope(source_hash=FIXTURE_HASH)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["source_identity"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(
            envelope["source_identity"]["source_hash_provenance"], "explicit_argument"
        )

    def test_hash_mismatch_fails_closed(self):
        envelope = _upload_envelope(source_hash=_sha256("a different document"))
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_hash_mismatch", codes)

    def test_invalid_explicit_hash_fails_closed(self):
        for bad_hash in ("ABC" * 21, "abc", "0" * 63, 123456):
            with self.subTest(source_hash=repr(bad_hash)):
                envelope = _upload_envelope(source_hash=bad_hash)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("source_hash_invalid", codes)

    def test_bytes_input_hashes_identically(self):
        envelope = _upload_envelope(source_text=FIXTURE_TEXT.encode("utf-8"))
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["source_identity"]["source_hash"], FIXTURE_HASH)

    def test_hash_only_upload_is_ready_with_diagnosed_context(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_hash=FIXTURE_HASH,
            source_path="uploads/fixture.md",
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["source_identity"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(envelope["source_context"], None)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_context_missing", codes)

    def test_title_fallback_from_path_stem(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_title=None,
            source_hash=FIXTURE_HASH,
            source_path="uploads/adventure_manuscript.md",
        )
        self.assertEqual(
            envelope["source_identity"]["source_title"], "adventure manuscript"
        )
        self.assertEqual(
            envelope["source_identity"]["source_title_provenance"], "source_reference"
        )

    def test_title_default_when_absent(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_title=None,
            source_path=None,
            source_hash=FIXTURE_HASH,
        )
        self.assertEqual(
            envelope["source_identity"]["source_title"], "Untitled readable source"
        )

    def test_missing_hash_fails_closed(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_hash=None,
            source_path="uploads/fixture.md",
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_hash_missing", codes)


class TestDeterministicSerialization(unittest.TestCase):
    """Same logical input always serializes to identical canonical bytes."""

    def test_identical_inputs_identical_bytes(self):
        first = runtime.serialize_adaptation_runtime_envelope(_upload_envelope())
        second = runtime.serialize_adaptation_runtime_envelope(_upload_envelope())
        self.assertEqual(first, second)

    def test_key_order_does_not_change_serialization(self):
        envelope = _upload_envelope()
        baseline = runtime.serialize_adaptation_runtime_envelope(envelope)
        shuffled = deepcopy(dict(envelope))
        items = list(shuffled.items())
        shuffled = dict(reversed(items))
        self.assertEqual(runtime.serialize_adaptation_runtime_envelope(shuffled), baseline)

    def test_serialized_form_is_sorted_canonical_json(self):
        envelope = _upload_envelope()
        encoded = runtime.serialize_adaptation_runtime_envelope(envelope)
        parsed = json.loads(encoded)
        self.assertEqual(parsed, envelope)
        self.assertEqual(
            encoded,
            json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )

    def test_serialize_rejects_non_mapping(self):
        with self.assertRaises(ValueError):
            runtime.serialize_adaptation_runtime_envelope("not-an-envelope")


class TestPythonOwnedRightsMetadata(unittest.TestCase):
    """Rights are Python-owned; provider data can never override them."""

    def test_text_description_defaults_to_user_authored(self):
        envelope = _text_envelope()
        rights = envelope["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(rights["rights_review_required"], False)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertEqual(
            rights["rights_basis"], runtime.TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS
        )
        self.assertTrue(rights["python_owned"])
        self.assertIs(rights["provider_may_change"], False)

    def test_supplied_rights_preserved(self):
        envelope = _upload_envelope(
            rights_class=RIGHTS_CLASS_LICENSED,
            rights_basis="licensed for adaptation",
            rights_review_required=True,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        rights = envelope["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_LICENSED)
        self.assertEqual(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_APPROVED)

    def test_restricted_pending_is_valid_review_gated(self):
        envelope = _upload_envelope(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            rights_basis="third party material",
            rights_review_required=True,
            rights_review_status=RIGHTS_REVIEW_PENDING,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["rights"]["rights_class"], RIGHTS_CLASS_RESTRICTED)

    def test_restricted_without_review_fails_closed(self):
        envelope = _upload_envelope(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            rights_basis="third party material",
            rights_review_required=False,
            rights_review_status=RIGHTS_REVIEW_NOT_REQUIRED,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("rights_review_contradiction", codes)

    def test_required_review_cannot_be_not_required(self):
        envelope = _upload_envelope(
            rights_review_required=True,
            rights_review_status=RIGHTS_REVIEW_NOT_REQUIRED,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("rights_review_contradiction", codes)

    def test_non_required_review_cannot_be_pending_or_rejected(self):
        for status in (RIGHTS_REVIEW_PENDING, RIGHTS_REVIEW_REJECTED):
            with self.subTest(status=status):
                envelope = _upload_envelope(
                    rights_review_required=False,
                    rights_review_status=status,
                )
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("rights_review_contradiction", codes)

    def test_rights_metadata_mapping_honored(self):
        envelope = _upload_envelope(
            rights_class=None,
            rights_basis=None,
            rights_review_required=None,
            rights_review_status=None,
            rights_metadata={
                "rights_class": RIGHTS_CLASS_LICENSED,
                "rights_basis": "mapping supplied basis",
                "rights_review_required": True,
                "rights_review_status": RIGHTS_REVIEW_APPROVED,
            },
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["rights"]["rights_class"], RIGHTS_CLASS_LICENSED)
        self.assertEqual(envelope["rights"]["rights_basis"], "mapping supplied basis")

    def test_missing_rights_fail_closed_for_uploads(self):
        envelope = _upload_envelope(
            rights_class=None,
            rights_basis=None,
            rights_review_required=None,
            rights_review_status=None,
            rights_metadata=None,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("rights_class_invalid", codes)
        self.assertIn("rights_basis_missing", codes)

    def test_provider_echo_of_identical_rights_does_not_change_them(self):
        envelope = _upload_envelope(
            provider_metadata={
                "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                "rights_basis": "approved test upload fixture",
                "rights_review_required": False,
                "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
                "model": "gpt-5.6-luna",
                "provider": "openai",
            }
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(envelope["rights"]["rights_basis"], "approved test upload fixture")
        self.assertNotIn("rights_class", envelope["model_metadata"])
        self.assertEqual(envelope["model_metadata"]["model"], "gpt-5.6-luna")

    def test_provider_contradictory_rights_rejected_and_rights_unchanged(self):
        envelope = _upload_envelope(
            provider_metadata={
                "rights_class": RIGHTS_CLASS_LICENSED,
                "rights_basis": "provider says licensed",
                "model": "gpt-5.6-luna",
            }
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        self.assertEqual(envelope["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(
            envelope["rights"]["rights_basis"], "approved test upload fixture"
        )
        self.assertNotIn("rights_class", envelope["model_metadata"])
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("provider_rights_override_rejected", codes)
        self.assertTrue(envelope["policy"]["provider_may_change_rights"] is False)


class TestAttemptIdentity(unittest.TestCase):
    """Attempt / job / revision identity is deterministic and path-safe."""

    def test_derived_attempt_id_is_deterministic(self):
        first = _upload_envelope()
        second = _upload_envelope()
        expected = build_attempt_id(FIXTURE_HASH, 1, "envelope-job")
        self.assertEqual(first["attempt"]["attempt_id"], expected)
        self.assertEqual(
            first["attempt"]["attempt_id"], second["attempt"]["attempt_id"]
        )
        self.assertEqual(first["attempt"]["attempt_number"], 1)
        self.assertEqual(first["attempt"]["revision_number"], 0)
        self.assertEqual(first["attempt"]["job_id"], "envelope-job")

    def test_explicit_attempt_id_honored(self):
        expected = build_attempt_id(FIXTURE_HASH, 2, "custom-job")
        envelope = _upload_envelope(
            attempt_id=expected,
            attempt_number=2,
            job_id="custom-job",
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["attempt"]["attempt_id"], expected)

    def test_explicit_attempt_id_mismatch_fails_closed(self):
        wrong = build_attempt_id(FIXTURE_HASH, 3, "other-job")
        envelope = _upload_envelope(attempt_id=wrong, attempt_number=1, job_id="envelope-job")
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("attempt_id_mismatch", codes)

    def test_invalid_attempt_id_fails_closed(self):
        for bad_id in ("../escape", "UPPERCASE_ID", "has space", "a" * 80):
            with self.subTest(attempt_id=bad_id):
                envelope = _upload_envelope(attempt_id=bad_id)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("attempt_id_invalid", codes)

    def test_attempt_number_bounds(self):
        for bad_number in (0, -1, True, "2", 1_000_001, 3.5):
            with self.subTest(attempt_number=repr(bad_number)):
                envelope = _upload_envelope(attempt_number=bad_number)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("attempt_number_invalid", codes)
        for good_number in (1, 1_000_000, 42):
            with self.subTest(attempt_number=good_number):
                envelope = _upload_envelope(attempt_number=good_number)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
                self.assertEqual(envelope["attempt"]["attempt_number"], good_number)

    def test_revision_number_bounds(self):
        for bad_revision in (-1, 101, True, "3"):
            with self.subTest(revision_number=repr(bad_revision)):
                envelope = _upload_envelope(revision_number=bad_revision)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("revision_number_invalid", codes)
        for good_revision in (0, 5, 100):
            with self.subTest(revision_number=good_revision):
                envelope = _upload_envelope(revision_number=good_revision)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
                self.assertEqual(envelope["attempt"]["revision_number"], good_revision)

    def test_job_id_bounded(self):
        envelope = _upload_envelope(job_id="x" * 500)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertLessEqual(len(envelope["attempt"]["job_id"]), runtime.MAX_JOB_ID_CHARS)


class TestWorldContextProvenance(unittest.TestCase):
    """World context is bounded provenance only; no world content leaks."""

    def test_missing_world_context_becomes_explicit_fallback(self):
        envelope = _upload_envelope(world_context=None)
        world = envelope["world_context"]
        self.assertEqual(world["context_status"], "unavailable")
        self.assertEqual(world["fallback_status"], "seed_data_unavailable")
        self.assertEqual(world["world_seed_status"], "unavailable")
        self.assertTrue(world["read_only"])

    def test_provenance_shaped_input_normalized(self):
        envelope = _upload_envelope(
            world_context={
                "context_status": "available",
                "world_seed_status": "available",
                "world_seed_version": "module_narrative_seeds.v1",
                "world_seed_hash": "a" * 64,
            }
        )
        world = envelope["world_context"]
        self.assertEqual(world["context_status"], "available")
        self.assertEqual(world["world_seed_status"], "available")
        self.assertEqual(world["world_seed_hash"], "a" * 64)
        self.assertEqual(world["fallback_status"], "none")

    def test_full_pack_provenance_without_content_leak(self):
        pack = build_world_narrative_context(
            campaign_model={
                "campaign_id": "c-1",
                "summary": "A world summary",
                "tone": "grim",
            },
            active_pressures=[
                {
                    "thread_id": "t-1",
                    "thread_type": "pressure",
                    "status": "active",
                    "summary": "A pressure",
                }
            ],
            registry_context={
                "world_name": "Test World",
                "modules": {"M-1": {"module_name": "Module One"}},
            },
            approved_module_seeds=[
                {
                    "module_slug": "M-1",
                    "seed_type": "hook",
                    "approved": True,
                    "content": {"summary": "seed text"},
                }
            ],
        )
        envelope = _upload_envelope(world_context=pack)
        world = envelope["world_context"]
        self.assertEqual(world["context_status"], "available")
        self.assertEqual(world["world_seed_status"], "available")
        self.assertEqual(world["fallback_status"], "none")
        for leaked in (
            "campaign_model",
            "active_pressures",
            "registry_context",
            "approved_module_seeds",
            "component_status",
        ):
            self.assertNotIn(leaked, world)
        self.assertIn("context_hash", world)
        self.assertEqual(len(world["context_hash"]), 64)

    def test_fallback_pack_status(self):
        pack = build_world_narrative_context(
            campaign_model={"campaign_id": "c-1", "summary": "A world summary"},
            active_pressures=[
                {"thread_id": "t-1", "thread_type": "pressure", "status": "active", "summary": "A pressure"}
            ],
            registry_context={"world_name": "Test World"},
        )
        envelope = _upload_envelope(world_context=pack)
        world = envelope["world_context"]
        self.assertEqual(world["context_status"], "fallback")
        self.assertEqual(world["world_seed_status"], "unavailable")
        self.assertEqual(world["fallback_status"], "seed_data_unavailable")
        self.assertTrue(envelope["policy"]["world_context_read_only"])


class TestStagingMetadata(_ProjectLocalScratchMixin, unittest.TestCase):
    """Staging metadata is carried as project-relative references only."""

    def test_synthetic_target_carried(self):
        attempt = build_attempt_id(FIXTURE_HASH, 1, "envelope-job")
        target = {
            "stage_id": attempt + ":revision_000",
            "attempt_id": attempt,
            "source_hash": FIXTURE_HASH,
            "staging_root": "adaptation-staging",
            "path": "adaptation-staging/" + attempt + "/revision_000",
            "output_directory": "adaptation-staging/" + attempt + "/revision_000",
            "metadata_path": "adaptation-staging/" + attempt + "/revision_000/staging_metadata.json",
            "completion_state": "reserved",
            "module_slug": "Envelope_Fixture",
        }
        envelope = _upload_envelope(attempt_id=attempt, staging_metadata=target)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        staging = envelope["staging"]
        self.assertTrue(staging["reserved"])
        self.assertTrue(staging["isolated"])
        self.assertEqual(staging["path"], target["path"])
        self.assertEqual(staging["stage_id"], target["stage_id"])
        self.assertEqual(staging["completion_state"], "reserved")
        self.assertEqual(staging["module_slug"], "Envelope_Fixture")
        self.assertTrue(envelope["policy"]["staging_project_relative"])

    def test_no_staging_is_not_reserved(self):
        envelope = _upload_envelope(staging_metadata=None)
        self.assertEqual(envelope["staging"]["reserved"], False)
        self.assertTrue(envelope["staging"]["isolated"])

    def test_absolute_staging_path_fails_closed(self):
        target = {
            "staging_root": "adaptation-staging",
            "path": "/etc/adaptation/revision_000",
            "output_directory": "adaptation-staging/revision_000",
            "metadata_path": "adaptation-staging/revision_000/staging_metadata.json",
            "completion_state": "reserved",
        }
        envelope = _upload_envelope(staging_metadata=target)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("staging_path_unsafe", codes)
        self.assertNotIn("path", envelope["staging"])

    def test_staging_source_hash_mismatch_fails_closed(self):
        attempt = build_attempt_id(FIXTURE_HASH, 1, "envelope-job")
        target = {
            "stage_id": attempt + ":revision_000",
            "path": "adaptation-staging/" + attempt + "/revision_000",
            "output_directory": "adaptation-staging/" + attempt + "/revision_000",
            "metadata_path": "adaptation-staging/" + attempt + "/revision_000/staging_metadata.json",
            "completion_state": "reserved",
            "attempt_id": attempt,
            "source_hash": _sha256("some other document"),
        }
        envelope = _upload_envelope(attempt_id=attempt, staging_metadata=target)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("staging_identity_mismatch", codes)

    def test_staging_attempt_mismatch_fails_closed(self):
        target = {
            "stage_id": "adapt-002-ghijkl:revision_000",
            "path": "adaptation-staging/adapt-002-ghijkl/revision_000",
            "output_directory": "adaptation-staging/adapt-002-ghijkl/revision_000",
            "metadata_path": "adaptation-staging/adapt-002-ghijkl/revision_000/staging_metadata.json",
            "completion_state": "reserved",
            "attempt_id": "adapt-002-ghijkl",
        }
        envelope = _upload_envelope(staging_metadata=target)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("staging_identity_mismatch", codes)

    def test_invalid_completion_state_fails_closed(self):
        target = {
            "path": "adaptation-staging/x/revision_000",
            "output_directory": "adaptation-staging/x/revision_000",
            "metadata_path": "adaptation-staging/x/revision_000/staging_metadata.json",
            "completion_state": "exploded",
        }
        envelope = _upload_envelope(staging_metadata=target)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("staging_state_invalid", codes)

    def test_real_reservation_carried_as_project_relative(self):
        job_id = "envelope-staging-job"
        attempt = build_attempt_id(FIXTURE_HASH, 1, job_id)
        target = create_adaptation_staging_target(
            FIXTURE_HASH,
            attempt_id=attempt,
            revision_number=0,
            job_id=job_id,
            source_path="uploads/fixture.md",
            module_slug="Envelope_Fixture",
            staging_root="adaptation-staging",
            repo_root=self.scratch,
        )
        envelope = _upload_envelope(
            attempt_id=attempt,
            job_id=job_id,
            staging_metadata=target,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["staging"]["path"], target["path"])
        self.assertEqual(envelope["staging"]["stage_id"], target["stage_id"])
        self.assertEqual(envelope["staging"]["completion_state"], "reserved")
        serialized = runtime.serialize_adaptation_runtime_envelope(envelope)
        self.assertIn(target["path"], serialized)
        self.assertNotIn(str(self.scratch), serialized)


class TestBoundsAndLeakage(unittest.TestCase):
    """No raw source, credentials, prompts, or absolute paths leak."""

    SECRET_TEXT = (
        "The lighthouse keeper kept the ledger.\n"
        "system prompt: you are the dungeon master.\n"
        "api_key = sk-abcdef1234567890SECRETKEY\n"
        "Authorization: Bearer abcdef1234567890abcdef\n"
        "password: hunter2secret\n"
        "The vault key is shared only with the warden.\n"
    )
    LARGE_TAIL = "The hall stretches onward. " * 6000
    RAW_WITH_SECRETS = SECRET_TEXT + LARGE_TAIL + "END_OF_SECRET_MATERIAL_MARKER_9f3a"

    def test_credentials_and_prompts_never_leak(self):
        envelope = _upload_envelope(
            source_text=self.RAW_WITH_SECRETS,
            source_hash=_sha256(self.RAW_WITH_SECRETS),
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        serialized = runtime.serialize_adaptation_runtime_envelope(envelope)
        for token in (
            "sk-abcdef1234567890SECRETKEY",
            "abcdef1234567890abcdef",
            "hunter2secret",
            "system prompt: you are the dungeon master",
            "END_OF_SECRET_MATERIAL_MARKER_9f3a",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, serialized)
        self.assertIn("[redacted", serialized)
        self.assertFalse(envelope["policy"]["raw_source_included"])
        result = runtime.validate_adaptation_runtime_envelope(envelope)
        self.assertTrue(result["valid"])

    def test_raw_source_excerpt_bounded(self):
        envelope = _upload_envelope(
            source_text=self.RAW_WITH_SECRETS,
            source_hash=_sha256(self.RAW_WITH_SECRETS),
        )
        context = envelope["source_context"]
        excerpts = [
            record
            for record in context.get("source_inputs", [])
            if record.get("kind") == "raw_source_excerpt"
        ]
        self.assertEqual(len(excerpts), 1)
        self.assertLessEqual(excerpts[0]["included_chars"], MAX_RAW_SOURCE_CHARS)
        self.assertTrue(excerpts[0]["truncated"])
        self.assertTrue(envelope["policy"]["source_text_bounded"])

    def test_oversized_raw_source_is_diagnosed_and_bounded(self):
        oversized = "x" * (runtime.MAX_RAW_SOURCE_ACCEPT_CHARS + 1)
        envelope = _upload_envelope(
            source_text=oversized,
            source_hash=_sha256(oversized),
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("raw_source_oversized", codes)
        context = envelope["source_context"]
        excerpts = [
            record
            for record in context.get("source_inputs", [])
            if record.get("kind") == "raw_source_excerpt"
        ]
        self.assertLessEqual(excerpts[0]["included_chars"], MAX_RAW_SOURCE_CHARS)

    def test_raw_source_field_in_supplied_context_fails_closed(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_context={
                "source_hash": FIXTURE_HASH,
                "raw_source": "the entire raw upload",
            },
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("raw_source_field_in_source_context", codes)

    def test_provider_credential_fields_dropped(self):
        envelope = _upload_envelope(
            provider_metadata={
                "api_key": "sk-abcdef1234567890SECRETKEY",
                "token": "sk-abcdef1234567890SECRETKEY",
                "system_prompt": "the whole prompt text",
                "model": "gpt-5.6-luna",
            }
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertNotIn("api_key", envelope["model_metadata"])
        self.assertNotIn("token", envelope["model_metadata"])
        self.assertNotIn("system_prompt", envelope["model_metadata"])
        serialized = runtime.serialize_adaptation_runtime_envelope(envelope)
        self.assertNotIn("sk-abcdef1234567890SECRETKEY", serialized)
        self.assertNotIn("the whole prompt text", serialized)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("provider_metadata_unsafe_key_dropped", codes)

    def test_validate_catches_injected_raw_source_key(self):
        envelope = _upload_envelope()
        tampered = deepcopy(dict(envelope))
        tampered["raw_source"] = "entire raw upload"
        result = runtime.validate_adaptation_runtime_envelope(tampered)
        self.assertFalse(result["valid"])
        self.assertIn("unsafe_field_raw_source", result["diagnostics"])

    def test_validate_catches_injected_credential_value(self):
        envelope = _upload_envelope()
        tampered = deepcopy(dict(envelope))
        tampered["model_metadata"]["model"] = "sk-abcdef1234567890SECRETKEY"
        result = runtime.validate_adaptation_runtime_envelope(tampered)
        self.assertFalse(result["valid"])
        self.assertIn("credential_value_present", result["diagnostics"])


class TestInvalidFailClosed(unittest.TestCase):
    """Invalid inputs fail closed with bounded diagnostics; no exceptions."""

    def test_source_context_invalid_type(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_context="not-a-mapping",
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_context_invalid_type", codes)

    def test_source_context_too_large(self):
        envelope = _upload_envelope(
            source_text=None,
            source_summary=None,
            source_context={"source_hash": FIXTURE_HASH, "text": "y" * 20_000},
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_context_too_large", codes)

    def test_model_metadata_invalid_type(self):
        for bad in ("junk", 7, ["list"]):
            with self.subTest(model_metadata=repr(bad)):
                envelope = _upload_envelope(model_metadata=bad)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("model_metadata_invalid_type", codes)

    def test_model_metadata_boolean_and_nan_values_fail_closed(self):
        for bad_value in (True, float("nan"), {"nested": 1}):
            with self.subTest(value=repr(bad_value)):
                envelope = _upload_envelope(model_metadata={"temperature": bad_value})
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("provider_metadata_value_invalid", codes)

    def test_source_text_invalid_type(self):
        envelope = _upload_envelope(source_text=12345)
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("raw_source_invalid_type", codes)

    def test_empty_text_description_fails_closed(self):
        envelope = _text_envelope(source_text="   ")
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("source_text_empty", codes)

    def test_unsafe_source_path_fails_closed(self):
        for bad_path in ("/etc/passwd", "C:\\windows\\evil", "../escape.md", "a\\b.md"):
            with self.subTest(source_path=bad_path):
                envelope = _upload_envelope(source_path=bad_path)
                self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
                codes = [item["code"] for item in envelope["diagnostics"]]
                self.assertIn("source_path_unsafe", codes)
                self.assertIsNone(envelope["source_identity"]["source_path"])

    def test_rights_metadata_invalid_type(self):
        envelope = _upload_envelope(rights_metadata="nope")
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = [item["code"] for item in envelope["diagnostics"]]
        self.assertIn("rights_metadata_invalid_type", codes)


class TestValidateRoundTrip(unittest.TestCase):
    """validate_adaptation_runtime_envelope locks the round-trip contract."""

    def test_valid_envelope_round_trip(self):
        envelope = _upload_envelope()
        result = runtime.validate_adaptation_runtime_envelope(envelope)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(result["envelope"], envelope)

    def test_mutated_hash_invalid(self):
        envelope = _upload_envelope()
        envelope["source_identity"]["source_hash"] = "0" * 64
        self.assertFalse(runtime.validate_adaptation_runtime_envelope(envelope)["valid"])

    def test_mutated_input_kind_invalid(self):
        envelope = _upload_envelope()
        envelope["input_kind"] = "upload_docx"
        self.assertFalse(runtime.validate_adaptation_runtime_envelope(envelope)["valid"])

    def test_mutated_rights_invalid(self):
        envelope = _upload_envelope()
        envelope["rights"]["rights_class"] = RIGHTS_CLASS_RESTRICTED
        self.assertFalse(runtime.validate_adaptation_runtime_envelope(envelope)["valid"])

    def test_mutated_world_context_non_canonical_invalid(self):
        envelope = _upload_envelope()
        envelope["world_context"]["unexpected_junk"] = "leak"
        result = runtime.validate_adaptation_runtime_envelope(envelope)
        self.assertFalse(result["valid"])
        self.assertIn("world_context_not_canonical", result["diagnostics"])

    def test_mutated_staging_absolute_path_invalid(self):
        envelope = _upload_envelope(
            staging_metadata={
                "path": "adaptation-staging/x/revision_000",
                "output_directory": "adaptation-staging/x/revision_000",
                "metadata_path": "adaptation-staging/x/revision_000/staging_metadata.json",
                "completion_state": "reserved",
            }
        )
        envelope["staging"]["path"] = "/etc/passwd"
        result = runtime.validate_adaptation_runtime_envelope(envelope)
        self.assertFalse(result["valid"])
        self.assertIn("staging_path_unsafe_path", result["diagnostics"])

    def test_builder_invalid_envelope_does_not_validate(self):
        envelope = runtime.build_adaptation_runtime_envelope("unsupported_kind")
        result = runtime.validate_adaptation_runtime_envelope(envelope)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], runtime.ENVELOPE_STATUS_INVALID)


class TestNoProviderNetworkTripwire(unittest.TestCase):
    """The runtime envelope boundary never touches providers or host lifecycles."""

    FORBIDDEN_TOKENS = (
        "openai",
        "httpx",
        "requests.get",
        "urllib.request",
        "http.client",
        "socketio",
        # Task 2.3 added the authoring adapter to this module, which documents
        # the stop-before-ModuleBuilder contract in docstrings and carries the
        # authoring guard field names (module_builder_allowed / _started).
        # Only actual builder imports/instantiation/invocation are forbidden.
        "from core.generators.module_builder",
        "import module_builder",
        "ModuleBuilder(",
        "module_builder.build_module",
        "simulate_build_process",
        "start_build",
        "web_interface",
        "toolkit_homebrew_routes",
        "world_registry.json",
        "campaign.json",
    )

    def test_runtime_module_has_no_provider_or_lifecycle_tokens(self):
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        for token in self.FORBIDDEN_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_this_suite_never_imports_provider_modules(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        import_lines = [
            line
            for line in own_source.splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        for token in ("openai", "httpx", "requests", "create_chat_client", "socketio"):
            with self.subTest(token=token):
                self.assertNotIn(token, imports)


class TestRuntimeEnvelopeHygiene(unittest.TestCase):
    """Changed artifacts follow SPDX, ASCII, and path-policy rules."""

    CHANGED_PATHS = (
        RUNTIME_MODULE_PATH,
        Path(__file__),
    )

    def test_changed_files_are_ascii_only(self):
        for path in self.CHANGED_PATHS:
            text = path.read_text(encoding="utf-8")
            non_ascii = [ch for ch in text if ord(ch) >= 128]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_changed_python_files_have_spdx_header(self):
        for path in self.CHANGED_PATHS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("SPDX-FileCopyrightText", text)
            self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self):
        for path in self.CHANGED_PATHS:
            source = path.read_text(encoding="utf-8")
            scan = source.split("def test_no_os_temp_or_absolute_scratch_paths", 1)[0]
            for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, scan)

    def test_scratch_is_project_relative(self):
        self.assertIn('"tmp"', Path(__file__).read_text(encoding="utf-8"))
        self.assertIn("toolkit_adaptation_runtime_envelope", Path(__file__).read_text(encoding="utf-8"))
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))

    def test_no_gui_mode_surface(self):
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        for token in ("socketio", "<template", "start_build", "module_builder.html"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
