# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the approved upload adaptation handoff
(task 2.1 of toolkit-llm-adaptation-runtime-unification).

The suite locks the Python-owned upload adapter in
web/extensions/toolkit_adaptation_runtime.py:

  * approved Markdown/PDF upload workspaces assemble bounded source context
    from the normalized packet, source file, manifest, and graph artifacts;
  * source hash, source kind, supplied upload rights classification/review
    state, job/attempt identity, and canonical world-context provenance are
    preserved;
  * unsupported/unapproved/missing/invalid workspace or packet inputs fail
    closed with bounded diagnostics;
  * no raw-source/credential leakage, deterministic output, no provider or
    network calls, and no final staging/publication reservation.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_upload_adaptation_handoff/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The handoff
helper never writes files and never touches modules/, the registry, campaign,
or runtime state.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

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
)
from utils.toolkit_adaptation_source_context import MAX_RAW_SOURCE_CHARS
from utils.toolkit_adaptation_world_context import build_world_narrative_context
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    REVIEW_DECISION_REJECT,
    SOURCE_RIGHTS_LICENSED,
    SOURCE_RIGHTS_RESTRICTED,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
    persist_source_graph_artifact,
    persist_source_manifest_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_upload_adaptation_handoff"
RUNTIME_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"
)

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

PACKET_LOCATIONS = [
    {"name": "Keeper's Quarters", "location": "tower", "description": "Rusted spyglass."},
    {"name": "Flooded Stairs", "location": "stairs", "description": "Dark water."},
]
PACKET_NPCS = [
    {"name": "Keeper Elowen", "role": "witness", "description": "Haunted keeper."},
]
PACKET_ENCOUNTERS = [
    {"name": "Drowned Bell Guard", "description": "Undead guardian."},
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _packet(
    *,
    source_hash: str = FIXTURE_HASH,
    rights: str = SOURCE_RIGHTS_USER_AUTHORED,
    title: str = "Sunken Lighthouse",
    normalization_state: str = "normalized",
    **extra: Any,
) -> Dict[str, Any]:
    packet: Dict[str, Any] = {
        "packet_version": "v1",
        "normalization_state": normalization_state,
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": title,
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": PACKET_LOCATIONS,
        "npc_seeds": PACKET_NPCS,
        "encounter_seeds": PACKET_ENCOUNTERS,
        "assumptions": ["Fixture packet for the upload handoff tests."],
        "source_rights_class": rights,
    }
    packet.update(extra)
    return packet


def _make_workspace(
    scratch: Path,
    *,
    packet: Optional[Dict[str, Any]] = None,
    text: str = FIXTURE_TEXT,
    text_bytes: Optional[bytes] = None,
    snapshot_decision: str = REVIEW_DECISION_APPROVE,
    write_snapshot: bool = True,
    write_source: bool = True,
    manifest: Optional[Dict[str, Any]] = None,
    graph: Optional[Dict[str, Any]] = None,
) -> Path:
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    if write_source:
        if text_bytes is not None:
            files["source_original"].write_bytes(text_bytes)
        else:
            files["source_original"].write_text(text, encoding="utf-8")
    resolved_packet = packet if packet is not None else _packet()
    persist_normalized_packet_artifact(workspace, resolved_packet)
    if manifest is not None:
        persist_source_manifest_artifact(workspace, manifest)
    if graph is not None:
        persist_source_graph_artifact(workspace, graph)
    if write_snapshot:
        snapshot = build_review_snapshot(
            job_id="job-1",
            decision=snapshot_decision,
            packet=resolved_packet,
            source_rights_class=str(
                resolved_packet.get("source_rights_class") or SOURCE_RIGHTS_USER_AUTHORED
            ),
        )
        persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


def _handoff(workspace: Path, **overrides: Any) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "source_kind": "markdown",
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
        "review_state": "approved_for_build",
        "job_id": "job-1",
    }
    options.update(overrides)
    return runtime.build_upload_adaptation_handoff(workspace, **options)


class _FixtureWorldProvider:
    """Read-only provider backed by provided values (no file access)."""

    def build(self, **kwargs: Any) -> Dict[str, Any]:
        return build_world_narrative_context(
            campaign_model={"summary": "A fixture world."},
            active_pressures=[{"summary": "The tide is rising.", "priority": 3}],
            registry_context={
                "world_name": "Fixture World",
                "modules": {"Test_Module": {"module_name": "Test Module"}},
            },
            approved_module_seeds=[
                {
                    "module_slug": "Test_Module",
                    "seed_type": "hook",
                    "approved": True,
                    "content": {"summary": "An approved fixture seed."},
                }
            ],
        )


class _BrokenWorldProvider:
    """Provider that always fails; the handoff must fall back explicitly."""

    def build(self, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("fixture provider failure")


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)


class TestApprovedMarkdownHandoff(_ProjectLocalScratchMixin, unittest.TestCase):
    """Approved Markdown workspaces produce a ready bounded handoff."""

    def test_markdown_handoff_ready(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["contract_version"], runtime.UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION)
        self.assertEqual(handoff["input_kind"], runtime.INPUT_KIND_UPLOAD_MARKDOWN)
        self.assertEqual(handoff["source_kind"], runtime.UPLOAD_SOURCE_KIND_MARKDOWN)
        self.assertIsNotNone(handoff["envelope"])
        self.assertEqual(handoff["envelope"]["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(
            handoff["envelope"]["staging"], {"reserved": False, "isolated": True}
        )

    def test_review_evidence_from_snapshot(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        evidence = handoff["upload_evidence"]
        self.assertTrue(evidence["approved"])
        self.assertEqual(evidence["review_state"], "approved_for_build")
        self.assertEqual(evidence["review_evidence"], "snapshot_approve")

    def test_source_hash_preserved_through_envelope(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        identity = handoff["envelope"]["source_identity"]
        self.assertEqual(identity["source_hash"], FIXTURE_HASH)
        self.assertEqual(identity["source_hash_provenance"], "explicit_argument")
        self.assertTrue(handoff["upload_evidence"]["packet_source_hash_preserved"])
        self.assertEqual(
            handoff["upload_evidence"]["packet_identity"]["source_hash"], FIXTURE_HASH
        )

    def test_rights_identity_preserved(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        self.assertEqual(
            handoff["envelope"]["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertTrue(handoff["envelope"]["rights"]["python_owned"])
        self.assertIs(handoff["envelope"]["rights"]["provider_may_change"], False)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_attempt_and_job_identity_preserved(self):
        workspace = _make_workspace(self.scratch)
        derived = build_attempt_id(FIXTURE_HASH, 2, "job-7")
        handoff = _handoff(
            workspace,
            attempt_number=2,
            attempt_id=derived,
            job_id="job-7",
            revision_number=1,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        attempt = handoff["envelope"]["attempt"]
        self.assertEqual(attempt["attempt_id"], derived)
        self.assertEqual(attempt["attempt_number"], 2)
        self.assertEqual(attempt["job_id"], "job-7")
        self.assertEqual(attempt["revision_number"], 1)

    def test_derived_attempt_id_consistent(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, job_id="job-1")
        derived = build_attempt_id(FIXTURE_HASH, 1, "job-1")
        self.assertEqual(handoff["envelope"]["attempt"]["attempt_id"], derived)

    def test_packet_context_is_bounded_and_typed(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        source_context = handoff["envelope"]["source_context"]
        self.assertEqual(source_context["context_status"], "available")
        self.assertEqual(source_context["source_hash"], FIXTURE_HASH)
        packet_metadata = source_context.get("packet_metadata") or {}
        self.assertEqual(len(packet_metadata.get("locations", [])), 2)
        self.assertEqual(len(packet_metadata.get("npc_seeds", [])), 1)
        self.assertEqual(len(packet_metadata.get("encounter_seeds", [])), 1)
        kinds = [
            record.get("kind")
            for record in source_context.get("source_inputs", [])
            if isinstance(record, dict)
        ]
        self.assertIn("normalized_packet", kinds)
        self.assertIn("raw_source_excerpt", kinds)

    def test_bounded_raw_source_excerpt(self):
        large_text = FIXTURE_TEXT + ("\nRepeated filler line for the excerpt bound.\n" * 2000)
        large_hash = _sha256(large_text)
        workspace = _make_workspace(self.scratch, text=large_text, packet=_packet(source_hash=large_hash))
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        source_context = handoff["envelope"]["source_context"]
        excerpts = [
            record
            for record in source_context.get("source_inputs", [])
            if isinstance(record, dict) and record.get("kind") == "raw_source_excerpt"
        ]
        self.assertEqual(len(excerpts), 1)
        self.assertLessEqual(excerpts[0]["included_chars"], MAX_RAW_SOURCE_CHARS)
        self.assertTrue(excerpts[0]["truncated"])
        self.assertTrue(handoff["envelope"]["policy"]["source_text_bounded"])
        self.assertIs(handoff["envelope"]["policy"]["raw_source_included"], False)

    def test_missing_manifest_and_graph_stay_optional(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)

    def test_persisted_manifest_and_graph_are_used(self):
        manifest = {
            "manifest_version": "source_manifest.v1",
            "summary": {"npc_candidates": 1, "location_candidates": 2},
            "location_candidates": [
                {"name": "Keeper's Quarters", "description": "Rusted spyglass.", "line_start": 2}
            ],
            "npc_candidates": [
                {"name": "Keeper Elowen", "description": "Haunted keeper.", "line_start": 3}
            ],
        }
        graph = {
            "atoms": [
                {"name": "Sunken Lighthouse", "type": "location", "summary": "Central ruin."}
            ]
        }
        workspace = _make_workspace(self.scratch, manifest=manifest, graph=graph)
        handoff = _handoff(workspace)
        source_context = handoff["envelope"]["source_context"]
        kinds = [
            record.get("kind")
            for record in source_context.get("source_inputs", [])
            if isinstance(record, dict)
        ]
        self.assertIn("source_manifest", kinds)
        self.assertIn("source_graph", kinds)


class TestApprovedPdfHandoff(_ProjectLocalScratchMixin, unittest.TestCase):
    """PDF workspaces normalize to the upload_pdf input kind."""

    def test_pdf_handoff_ready(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, source_kind="pdf")
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["input_kind"], runtime.INPUT_KIND_UPLOAD_PDF)
        self.assertEqual(handoff["source_kind"], runtime.UPLOAD_SOURCE_KIND_PDF)
        self.assertEqual(handoff["envelope"]["source_identity"]["source_hash"], FIXTURE_HASH)
        self.assertTrue(handoff["upload_evidence"]["packet_source_hash_preserved"])

    def test_upload_kind_aliases_normalize_deterministically(self):
        workspace = _make_workspace(self.scratch)
        for raw_kind, expected_kind in (
            ("markdown", runtime.INPUT_KIND_UPLOAD_MARKDOWN),
            ("upload_markdown", runtime.INPUT_KIND_UPLOAD_MARKDOWN),
            ("Markdown", runtime.INPUT_KIND_UPLOAD_MARKDOWN),
            ("pdf", runtime.INPUT_KIND_UPLOAD_PDF),
            ("upload_pdf", runtime.INPUT_KIND_UPLOAD_PDF),
            ("PDF", runtime.INPUT_KIND_UPLOAD_PDF),
        ):
            with self.subTest(source_kind=raw_kind):
                handoff = _handoff(workspace, source_kind=raw_kind)
                self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
                self.assertEqual(handoff["input_kind"], expected_kind)

    def test_unsupported_kind_fails_closed(self):
        workspace = _make_workspace(self.scratch)
        for bad_kind in ("docx", "scanned_notes", "", None, 7):
            with self.subTest(source_kind=repr(bad_kind)):
                handoff = _handoff(workspace, source_kind=bad_kind)
                self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
                self.assertIsNone(handoff["envelope"])
                codes = [item["code"] for item in handoff["diagnostics"]]
                self.assertIn("unsupported_source_kind", codes)


class TestSourceHashAndRightsPreservation(_ProjectLocalScratchMixin, unittest.TestCase):
    """Source hash and Python-owned rights cannot be relabeled or drift."""

    def test_packet_hash_mismatch_fails_closed(self):
        packet = _packet(source_hash=_sha256("different source text"))
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        self.assertIsNone(handoff["envelope"])
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("source_hash_mismatch", codes)

    def test_packet_rights_cannot_relabel_supplied_class(self):
        packet = _packet(rights=SOURCE_RIGHTS_RESTRICTED)
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(
            workspace,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            rights_review_status=RIGHTS_REVIEW_NOT_REQUIRED,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(
            handoff["envelope"]["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("packet_rights_relabel_rejected", codes)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_snapshot_rights_cannot_relabel_supplied_class(self):
        workspace = _make_workspace(self.scratch)
        files = get_workspace_files(workspace)
        snapshot = build_review_snapshot(
            job_id="job-1",
            decision=REVIEW_DECISION_APPROVE,
            packet=_packet(),
            source_rights_class=SOURCE_RIGHTS_RESTRICTED,
        )
        persist_review_snapshot_artifact(workspace, snapshot)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(
            handoff["envelope"]["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("snapshot_rights_relabel_rejected", codes)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_restricted_supplied_class_stays_review_gated(self):
        packet = _packet(rights=SOURCE_RIGHTS_RESTRICTED)
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(workspace, source_rights_class=SOURCE_RIGHTS_RESTRICTED)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_RESTRICTED)
        self.assertIs(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_PENDING)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_restricted_with_explicit_approved_review(self):
        packet = _packet(rights=SOURCE_RIGHTS_RESTRICTED)
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(
            workspace,
            source_rights_class=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(
            handoff["envelope"]["rights"]["rights_review_status"], RIGHTS_REVIEW_APPROVED
        )

    def test_rights_contradiction_fails_closed_via_envelope(self):
        packet = _packet(rights=SOURCE_RIGHTS_RESTRICTED)
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(
            workspace,
            source_rights_class=SOURCE_RIGHTS_RESTRICTED,
            rights_review_required=False,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        self.assertIsNone(handoff["envelope"])
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("rights_review_contradiction", codes)

    def test_invalid_supplied_rights_fails_closed(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, source_rights_class="public_domain_guess")
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("source_rights_class_invalid", codes)

    def test_attempt_identity_mismatch_fails_closed(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, attempt_id="adapt-999-wrong")
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("attempt_id_mismatch", codes)


class TestApprovalAndReviewStates(_ProjectLocalScratchMixin, unittest.TestCase):
    """Only approved review states proceed; rejection fails closed."""

    def test_all_approved_states_proceed(self):
        workspace = _make_workspace(self.scratch)
        for state in ("approved_for_build", "awaiting_overwrite_confirmation", "ready_for_finishing"):
            with self.subTest(review_state=state):
                handoff = _handoff(workspace, review_state=state)
                self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
                self.assertEqual(handoff["upload_evidence"]["review_state"], state)

    def test_unapproved_state_fails_closed(self):
        workspace = _make_workspace(self.scratch)
        for state in ("awaiting_review", "rejected", "queued", "", None):
            with self.subTest(review_state=repr(state)):
                handoff = _handoff(workspace, review_state=state)
                self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
                self.assertIsNone(handoff["envelope"])
                codes = [item["code"] for item in handoff["diagnostics"]]
                self.assertIn("upload_not_approved", codes)

    def test_rejected_snapshot_fails_closed_even_with_approved_state(self):
        workspace = _make_workspace(self.scratch, snapshot_decision=REVIEW_DECISION_REJECT)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("upload_review_rejected", codes)

    def test_missing_snapshot_uses_supplied_review_state(self):
        workspace = _make_workspace(self.scratch, write_snapshot=False)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["upload_evidence"]["review_evidence"], "supplied_review_state")


class TestWorldContext(_ProjectLocalScratchMixin, unittest.TestCase):
    """World context stays read-only with an explicit unavailable fallback."""

    def test_unavailable_world_context_is_explicit_fallback(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["world_context_evidence"], "unavailable")
        world = handoff["world_context"]
        self.assertEqual(world["context_status"], "unavailable")
        self.assertEqual(world["fallback_status"], "seed_data_unavailable")
        self.assertIs(world["read_only"], True)
        self.assertIs(handoff["envelope"]["policy"]["world_context_read_only"], True)

    def test_supplied_world_context_provenance(self):
        workspace = _make_workspace(self.scratch)
        pack = build_world_narrative_context(
            campaign_model={"summary": "A fixture world."},
            active_pressures=[{"summary": "The tide is rising.", "priority": 3}],
            registry_context={
                "world_name": "Fixture World",
                "modules": {"Test_Module": {"module_name": "Test Module"}},
            },
            approved_module_seeds=[
                {
                    "module_slug": "Test_Module",
                    "seed_type": "hook",
                    "approved": True,
                    "content": {"summary": "An approved fixture seed."},
                }
            ],
        )
        handoff = _handoff(workspace, world_context=pack)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["world_context_evidence"], "supplied_context")
        world = handoff["world_context"]
        self.assertEqual(world["context_status"], "available")
        self.assertEqual(world["fallback_status"], "none")
        self.assertIs(world["read_only"], True)
        self.assertEqual(
            handoff["envelope"]["world_context"],
            runtime.build_world_context_provenance(pack),
        )

    def test_provider_world_context(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, world_context_provider=_FixtureWorldProvider())
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["world_context_evidence"], "provider")
        self.assertEqual(handoff["world_context"]["context_status"], "available")
        self.assertIs(handoff["world_context"]["read_only"], True)

    def test_broken_provider_uses_explicit_fallback(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, world_context_provider=_BrokenWorldProvider())
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(handoff["world_context_evidence"], "provider_failed")
        self.assertEqual(handoff["world_context"]["fallback_status"], "seed_data_unavailable")
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("world_context_unavailable", codes)


class TestInvalidWorkspaceAndPacket(_ProjectLocalScratchMixin, unittest.TestCase):
    """Missing or invalid workspaces and packets fail closed with diagnostics."""

    def test_missing_workspace_fails_closed(self):
        handoff = _handoff(self.scratch / "missing")
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("workspace_missing", codes)

    def test_workspace_path_is_file_fails_closed(self):
        workspace_file = self.scratch / "not_a_dir"
        workspace_file.write_text("plain file", encoding="utf-8")
        self.addCleanup(workspace_file.unlink, missing_ok=True)
        handoff = _handoff(workspace_file)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("workspace_invalid", codes)

    def test_workspace_outside_repo_fails_closed(self):
        outside = REPO_ROOT.parent / "toolkit_upload_outside_workspace"
        handoff = _handoff(outside)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("workspace_outside_repo", codes)

    def test_packet_missing_fails_closed(self):
        workspace = _make_workspace(self.scratch)
        get_workspace_files(workspace)["normalized_packet"].unlink(missing_ok=True)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("packet_missing", codes)

    def test_invalid_packet_fails_closed(self):
        packet = _packet(normalization_state="placeholder")
        workspace = _make_workspace(self.scratch, packet=packet)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("packet_invalid", codes)

    def test_source_original_missing_fails_closed(self):
        workspace = _make_workspace(self.scratch, write_source=False)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("source_original_missing", codes)

    def test_non_utf8_source_fails_closed(self):
        raw_bytes = b"\xff\xfe\x00 invalid utf8 bytes"
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        packet = _packet(source_hash=file_hash)
        workspace = _make_workspace(self.scratch, packet=packet, text_bytes=raw_bytes)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("raw_source_invalid_utf8", codes)

    def test_oversized_source_fails_closed(self):
        large_text = "x" * 64
        packet = _packet(source_hash=_sha256(large_text))
        workspace = _make_workspace(self.scratch, text=large_text, packet=packet)
        with mock.patch.object(runtime, "MAX_UPLOAD_SOURCE_BYTES", 32):
            handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("source_too_large", codes)


class TestHandoffDeterminismAndValidation(_ProjectLocalScratchMixin, unittest.TestCase):
    """The handoff is byte-deterministic and validates under its contract."""

    def test_deterministic_serialization(self):
        workspace = _make_workspace(self.scratch)
        first = _handoff(workspace, job_id="job-1")
        second = _handoff(workspace, job_id="job-1")
        self.assertEqual(
            runtime.serialize_upload_adaptation_handoff(first),
            runtime.serialize_upload_adaptation_handoff(second),
        )
        self.assertIsNot(first, second)

    def test_ready_handoff_validates(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        result = runtime.validate_upload_adaptation_handoff(handoff)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["status"], runtime.HANDOFF_STATUS_READY)

    def test_failed_closed_handoff_validates(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, review_state="awaiting_review")
        result = runtime.validate_upload_adaptation_handoff(handoff)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)

    def test_invalid_handoff_detected(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        tampered = dict(handoff)
        tampered["upload_evidence"] = dict(handoff["upload_evidence"])
        tampered["upload_evidence"]["packet_source_hash_preserved"] = False
        result = runtime.validate_upload_adaptation_handoff(tampered)
        self.assertFalse(result["valid"])
        self.assertIn("packet_source_hash_not_preserved", result["diagnostics"])

    def test_helper_never_writes_workspace_files(self):
        workspace = _make_workspace(self.scratch)

        def _snapshot() -> set:
            return {
                str(path.relative_to(workspace))
                for path in workspace.rglob("*")
                if path.is_file()
            }

        before = _snapshot()
        handoff = _handoff(workspace)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(_snapshot(), before)

    def test_no_staging_or_publication_reservation(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        self.assertEqual(handoff["envelope"]["staging"]["reserved"], False)
        self.assertEqual(handoff["envelope"]["policy"]["staging_project_relative"], False)


class TestNoLeakageTripwire(_ProjectLocalScratchMixin, unittest.TestCase):
    """No raw-source, credential, prompt, or absolute-path leakage; no providers."""

    def test_serialized_handoff_has_no_credential_material(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace, provider_metadata={"model": "fixture-model"})
        encoded = runtime.serialize_upload_adaptation_handoff(handoff)
        lowered = encoded.lower()
        for pattern in ("sk-", "bearer ", "api_key", "apikey", "authorization", "password"):
            self.assertNotIn(pattern, lowered)

    def test_serialized_handoff_has_no_forbidden_source_keys(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        encoded = runtime.serialize_upload_adaptation_handoff(handoff)
        for key in ("raw_source", "raw_markdown", "raw_pdf", "full_source", "source_text"):
            self.assertNotIn('"' + key + '"', encoded)

    def test_no_absolute_paths_in_envelope(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        encoded = runtime.serialize_upload_adaptation_handoff(handoff)
        self.assertNotIn(str(REPO_ROOT), encoded)
        source_path = handoff["envelope"]["source_identity"]["source_path"]
        self.assertFalse(Path(source_path).is_absolute())
        self.assertTrue(source_path.endswith("source_original.md"))

    def test_envelope_round_trip_validates(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        envelope_result = runtime.validate_adaptation_runtime_envelope(handoff["envelope"])
        self.assertTrue(envelope_result["valid"], envelope_result["diagnostics"])

    def test_handoff_json_is_stable(self):
        workspace = _make_workspace(self.scratch)
        handoff = _handoff(workspace)
        parsed = json.loads(runtime.serialize_upload_adaptation_handoff(handoff))
        self.assertEqual(parsed["contract_version"], runtime.UPLOAD_ADAPTATION_HANDOFF_CONTRACT_VERSION)

    def test_runtime_module_has_no_provider_imports(self):
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        for pattern in ("import openai", "import requests", "from openai", "urllib", "http.client"):
            self.assertNotIn(pattern, source)


if __name__ == "__main__":
    unittest.main()
