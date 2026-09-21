# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the minimal text-description attempt workspace
(task 2.2 of toolkit-llm-adaptation-runtime-unification).

The suite locks the Python-owned adapter in
web/extensions/toolkit_adaptation_runtime.py:

  * a valid text-description build request (path-safe module name plus a
    bounded non-empty concept) creates an attempt-scoped, project-relative
    workspace containing only the bounded concept input and the minimum
    normalized packet/metadata required by the existing adaptation packet
    builder (normalized packet, approved review snapshot, builder narrative,
    attempt metadata, bounded runtime envelope, and workspace manifest);
  * the concept is classified as Python-owned ``user_authored`` with a stable
    lowercase SHA-256 source identity, attempt identity, source kind, and
    world-context fallback/provenance preserved;
  * the handoff exposes an output/staging target that is not
    ``modules/<name>`` before publication; no direct module success is
    claimed and no module/registry/campaign state is mutated;
  * invalid module names, empty/oversized concepts, unsafe paths, existing
    workspaces, and write/serialization failures fail closed with bounded
    diagnostics;
  * output is deterministic and byte-stable for identical inputs.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_attempt_workspace/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The helper
never calls a provider, never runs ModuleBuilder, never reserves or writes
the final staging target, and never touches ``modules/``, the registry,
campaign, or runtime state.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_artifacts import build_attempt_id
from utils.toolkit_adaptation_config import MAX_TEXT_DESCRIPTION_CHARS
from utils.toolkit_adaptation_dossier import (
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_NOT_REQUIRED,
)
from utils.toolkit_adaptation_world_context import build_world_narrative_context
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    get_workspace_files,
    load_normalized_packet_artifact,
    validate_review_packet,
)
from web.extensions.toolkit_homebrew_packet_builder import (
    _derive_builder_shape,
    derive_packet_module_name,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_attempt_workspace"
RUNTIME_MODULE_PATH = REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"

MODULE_NAME = "Sunken_Lighthouse"
CONCEPT = (
    "The Sunken Lighthouse: a storm-wracked keep where the tide never leaves. "
    "Three floors of flooded halls hide the drowned bell, the keeper's ledger, "
    "and the light that was never lit. The party must descend before the "
    "spring tide strands them in the dark."
)
CONCEPT_HASH = hashlib.sha256(CONCEPT.encode("utf-8")).hexdigest()

EXPECTED_FILENAMES = sorted(
    {
        runtime.CONCEPT_SOURCE_FILENAME,
        runtime.BUILDER_NARRATIVE_FILENAME,
        runtime.NORMALIZED_PACKET_FILENAME,
        runtime.REVIEW_SNAPSHOT_FILENAME,
        runtime.ATTEMPT_METADATA_FILENAME,
        runtime.RUNTIME_ENVELOPE_FILENAME,
        runtime.WORKSPACE_MANIFEST_FILENAME,
    }
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _FixtureWorldProvider:
    """Read-only provider backed by provided values (no file access)."""

    def build(self, **kwargs: Any) -> Dict[str, Any]:
        return build_world_narrative_context(
            campaign_model={"summary": "A fixture world."},
            active_pressures=[{"summary": "The tide is rising.", "priority": 3}],
            registry_context={"world_name": "Fixture World", "modules": {}},
            approved_module_seeds=[],
        )


class _BrokenWorldProvider:
    def build(self, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("provider failure")


class _Base(unittest.TestCase):
    """Shared scratch-root isolation and build helper."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspace_root = (
            "tmp/toolkit_text_description_attempt_workspace/"
            + self.scratch.name
            + "/workspaces"
        )
        self.staging_root = (
            "tmp/toolkit_text_description_attempt_workspace/"
            + self.scratch.name
            + "/staging"
        )

    def _build(self, concept: Any = CONCEPT, **overrides: Any) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "workspace_root": self.workspace_root,
            "staging_root": self.staging_root,
        }
        options.update(overrides)
        return runtime.build_text_description_attempt_workspace(
            MODULE_NAME, concept, **options
        )

    def _workspace_abs(self, manifest: Dict[str, Any]) -> Path:
        workspace = manifest.get("workspace")
        if not isinstance(workspace, Mapping):
            self.fail("manifest has no workspace")
        return REPO_ROOT.joinpath(*Path(str(workspace.get("path"))).parts)

    def _assert_failed_closed(self, result: Dict[str, Any], *codes: str) -> None:
        self.assertEqual(result["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)
        self.assertIsNone(result["workspace"])
        self.assertIsNone(result["envelope"])
        found = {str(item.get("code")) for item in result.get("diagnostics", [])}
        for code in codes:
            self.assertIn(code, found, result.get("diagnostics"))
        # A failed-closed workspace satisfies its own mirror contract.
        validation = runtime.validate_text_description_attempt_workspace(result)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)

    def _assert_no_attempt_dirs_left(self) -> None:
        """Cleanup only removes the attempt directory; parents may remain."""
        workspace_root_abs = REPO_ROOT.joinpath(*Path(self.workspace_root).parts)
        children = list(workspace_root_abs.iterdir()) if workspace_root_abs.exists() else []
        self.assertEqual(children, [])


class TestReadyWorkspaceContract(_Base):
    def test_ready_status_and_workspace_path(self) -> None:
        manifest = self._build()
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        self.assertEqual(manifest["input_kind"], runtime.INPUT_KIND_TEXT_DESCRIPTION)
        self.assertEqual(manifest["source_kind"], runtime.TEXT_DESCRIPTION_SOURCE_KIND)
        workspace_path = str(manifest["workspace"]["path"])
        self.assertTrue(workspace_path.startswith(self.workspace_root + "/"))
        self.assertTrue(workspace_path.endswith(manifest["attempt"]["attempt_id"]))
        self.assertNotIn("modules/", workspace_path)
        self.assertNotIn("characters/", workspace_path)
        self.assertNotIn("data/", workspace_path)

    def test_all_artifact_files_persisted_and_parse(self) -> None:
        manifest = self._build()
        files = manifest["workspace"]["files"]
        self.assertEqual(len(files), 7)
        for key in (
            "concept_source",
            "builder_narrative",
            "normalized_packet",
            "review_snapshot",
            "attempt_metadata",
            "runtime_envelope",
            "workspace_manifest",
        ):
            self.assertIn(key, files)
            path = REPO_ROOT.joinpath(*Path(files[key]).parts)
            self.assertTrue(path.exists(), files[key])
        for key in (
            "normalized_packet",
            "review_snapshot",
            "attempt_metadata",
            "runtime_envelope",
            "workspace_manifest",
        ):
            with open(REPO_ROOT.joinpath(*Path(files[key]).parts), encoding="utf-8") as handle:
                json.load(handle)

    def test_concept_files_bounded_and_exact(self) -> None:
        manifest = self._build()
        files = manifest["workspace"]["files"]
        concept_source = REPO_ROOT.joinpath(*Path(files["concept_source"]).parts)
        narrative = REPO_ROOT.joinpath(*Path(files["builder_narrative"]).parts)
        self.assertEqual(concept_source.read_text(encoding="utf-8"), CONCEPT)
        self.assertEqual(narrative.read_text(encoding="utf-8"), CONCEPT)
        self.assertLessEqual(len(CONCEPT), MAX_TEXT_DESCRIPTION_CHARS)

    def test_normalized_packet_reviewable(self) -> None:
        manifest = self._build()
        files = manifest["workspace"]["files"]
        packet = json.loads(
            REPO_ROOT.joinpath(*Path(files["normalized_packet"]).parts).read_text(encoding="utf-8")
        )
        ok, error = validate_review_packet(packet)
        self.assertTrue(ok, error)
        self.assertEqual(packet["source_hash"], CONCEPT_HASH)
        self.assertEqual(packet["normalization_state"], "normalized")
        self.assertEqual(packet["title"], MODULE_NAME)
        self.assertEqual(packet["source_rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(
            str(packet.get("source_path")),
            str(manifest["workspace"]["path"]) + "/" + runtime.CONCEPT_SOURCE_FILENAME,
        )

    def test_review_snapshot_approved_with_matching_identity(self) -> None:
        manifest = self._build()
        files = manifest["workspace"]["files"]
        snapshot = json.loads(
            REPO_ROOT.joinpath(*Path(files["review_snapshot"]).parts).read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["decision"], REVIEW_DECISION_APPROVE)
        self.assertEqual(snapshot["packet_identity"]["source_hash"], CONCEPT_HASH)
        self.assertEqual(snapshot["source_rights_class"], RIGHTS_CLASS_USER_AUTHORED)

    def test_envelope_ready_and_identity_preserved(self) -> None:
        manifest = self._build()
        envelope = manifest["envelope"]
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_READY)
        self.assertEqual(envelope["input_kind"], runtime.INPUT_KIND_TEXT_DESCRIPTION)
        self.assertEqual(envelope["source_identity"]["source_hash"], CONCEPT_HASH)
        self.assertEqual(
            envelope["source_identity"]["source_hash_provenance"], "explicit_argument"
        )
        self.assertEqual(envelope["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertTrue(envelope["rights"]["python_owned"])
        self.assertFalse(envelope["rights"]["provider_may_change"])
        self.assertEqual(envelope["attempt"]["attempt_id"], manifest["attempt"]["attempt_id"])
        self.assertIsInstance(envelope["source_context"], dict)
        self.assertEqual(envelope["source_context_status"], "available")

    def test_rights_python_owned_user_authored(self) -> None:
        manifest = self._build()
        rights = manifest["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(rights["rights_basis"], runtime.TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS)
        self.assertFalse(rights["rights_review_required"])
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertTrue(rights["python_owned"])
        self.assertEqual(rights["classified_by"], runtime.TEXT_DESCRIPTION_CLASSIFIED_BY)
        self.assertFalse(rights["provider_may_change"])
        metadata = manifest["packet_metadata"]
        self.assertEqual(metadata["classified_by"], runtime.TEXT_DESCRIPTION_CLASSIFIED_BY)
        self.assertEqual(metadata["source_rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertTrue(metadata["workspace_review_approved"])
        self.assertEqual(metadata["review_decision"], REVIEW_DECISION_APPROVE)
        self.assertTrue(metadata["concept_bounded"])
        self.assertEqual(metadata["concept_chars"], len(CONCEPT))

    def test_attempt_identity_derived_and_preserved(self) -> None:
        manifest = self._build(job_id="job-7", attempt_number=2)
        expected = build_attempt_id(CONCEPT_HASH, 2, "job-7")
        self.assertEqual(manifest["attempt"]["attempt_id"], expected)
        self.assertEqual(manifest["attempt"]["attempt_number"], 2)
        self.assertEqual(manifest["attempt"]["revision_number"], 0)
        self.assertEqual(manifest["attempt"]["job_id"], "job-7")
        self.assertEqual(manifest["envelope"]["attempt"]["attempt_id"], expected)

    def test_output_isolated_staging_not_modules(self) -> None:
        manifest = self._build()
        output = manifest["output"]
        self.assertFalse(output["published_to_modules"])
        self.assertFalse(output["direct_module_write_required"])
        self.assertFalse(output["staging_reserved"])
        self.assertEqual(output["module_name"], MODULE_NAME)
        self.assertEqual(output["staging_root"], self.staging_root)
        staging_target = str(output["staging_target_path"])
        self.assertTrue(staging_target.startswith(self.staging_root + "/"))
        self.assertIn(manifest["attempt"]["attempt_id"], staging_target)
        self.assertTrue(staging_target.endswith("revision_000"))
        self.assertNotIn("modules/", staging_target)

    def test_no_module_directory_created(self) -> None:
        manifest = self._build()
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)

    def test_manifest_validates_round_trip(self) -> None:
        manifest = self._build()
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertEqual(validation["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)

    def test_serialized_manifest_bounded(self) -> None:
        manifest = self._build()
        encoded = runtime.serialize_text_description_attempt_workspace(manifest)
        self.assertLessEqual(len(encoded), runtime.MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS)
        self.assertEqual(
            json.loads(encoded),
            json.loads(
                REPO_ROOT.joinpath(
                    *Path(manifest["workspace"]["files"]["workspace_manifest"]).parts
                ).read_text(encoding="utf-8")
            ),
        )

    def test_workspace_contains_only_expected_files(self) -> None:
        manifest = self._build()
        workspace_abs = self._workspace_abs(manifest)
        self.assertEqual(sorted(p.name for p in workspace_abs.iterdir()), EXPECTED_FILENAMES)

    def test_default_roots_are_project_relative_scratch(self) -> None:
        self.assertEqual(
            runtime.DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT, "tmp/toolkit-text-workspaces"
        )
        self.assertEqual(runtime.DEFAULT_ADAPTATION_STAGING_ROOT, "tmp/adaptation-staging")
        self.assertTrue(
            runtime.DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT.startswith("tmp/")
        )
        self.assertNotIn("modules/", runtime.DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT)


class TestPacketBuilderConsumability(_Base):
    def test_packet_consumed_by_existing_builder_shape(self) -> None:
        manifest = self._build()
        packet = load_normalized_packet_artifact(self._workspace_abs(manifest))
        self.assertEqual(derive_packet_module_name(packet), MODULE_NAME)
        shape = _derive_builder_shape(packet)
        self.assertEqual(shape["module_name"], MODULE_NAME)
        self.assertIn("num_areas", shape)
        self.assertIn("locations_per_area", shape)

    def test_enabled_output_target_isolated_from_legacy_modules_path(self) -> None:
        # The legacy packet shape writes to ./modules/<name>; the adaptation
        # handoff must redirect the enabled path to isolated staging instead
        # and never claim direct module publication.
        manifest = self._build()
        packet = load_normalized_packet_artifact(self._workspace_abs(manifest))
        legacy_shape = _derive_builder_shape(packet)
        self.assertTrue(str(legacy_shape["output_directory"]).startswith("./modules/"))
        output = manifest["output"]
        self.assertFalse(output["published_to_modules"])
        self.assertFalse(output["staging_reserved"])
        staging_target = str(output["staging_target_path"])
        self.assertNotIn("modules/", staging_target)
        self.assertTrue(staging_target.startswith(self.staging_root + "/"))
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())

    def test_review_snapshot_satisfies_packet_builder_contract(self) -> None:
        manifest = self._build()
        workspace_abs = self._workspace_abs(manifest)
        snapshot = json.loads(
            (workspace_abs / runtime.REVIEW_SNAPSHOT_FILENAME).read_text(encoding="utf-8")
        )
        packet = load_normalized_packet_artifact(workspace_abs)
        self.assertEqual(str(snapshot["decision"]).lower(), "approve")
        packet_hash = str(packet.get("source_hash") or "").strip()
        snapshot_hash = str(snapshot.get("packet_identity", {}).get("source_hash") or "").strip()
        self.assertEqual(snapshot_hash, packet_hash)


class TestDeterminismAndIdentity(_Base):
    def test_rebuild_produces_identical_manifest(self) -> None:
        first = self._build(job_id="job-det", attempt_number=1)
        first_serialized = runtime.serialize_text_description_attempt_workspace(first)
        first_workspace = str(first["workspace"]["path"])
        shutil.rmtree(self._workspace_abs(first))
        second = self._build(job_id="job-det", attempt_number=1)
        self.assertEqual(str(second["workspace"]["path"]), first_workspace)
        self.assertEqual(
            runtime.serialize_text_description_attempt_workspace(second),
            first_serialized,
        )

    def test_source_hash_matches_concept_across_surfaces(self) -> None:
        manifest = self._build()
        self.assertEqual(manifest["source_identity"]["source_hash"], CONCEPT_HASH)
        self.assertEqual(manifest["packet_metadata"]["source_hash"], CONCEPT_HASH)
        self.assertEqual(manifest["envelope"]["source_identity"]["source_hash"], CONCEPT_HASH)
        self.assertEqual(
            manifest["source_identity"]["source_hash_provenance"], "explicit_argument"
        )

    def test_attempt_id_stable_with_job_and_number(self) -> None:
        manifest = self._build(job_id="job-x", attempt_number=3)
        self.assertEqual(
            manifest["attempt"]["attempt_id"],
            build_attempt_id(CONCEPT_HASH, 3, "job-x"),
        )

    def test_revision_uses_distinct_staging_target(self) -> None:
        first = self._build(revision_number=0)
        self.assertTrue(str(first["output"]["staging_target_path"]).endswith("revision_000"))
        workspace_abs = self._workspace_abs(first)
        shutil.rmtree(workspace_abs)
        second = self._build(revision_number=1)
        self.assertEqual(second["attempt"]["attempt_id"], first["attempt"]["attempt_id"])
        self.assertTrue(str(second["output"]["staging_target_path"]).endswith("revision_001"))
        self.assertEqual(second["attempt"]["revision_number"], 1)


class TestWorldContextProvenance(_Base):
    def test_supplied_context_provenance(self) -> None:
        pack = build_world_narrative_context(
            campaign_model={"summary": "A fixture world."},
            active_pressures=[{"summary": "The tide is rising.", "priority": 3}],
            registry_context={"world_name": "Fixture World", "modules": {}},
            approved_module_seeds=[],
        )
        manifest = self._build(world_context=pack)
        self.assertEqual(manifest["world_context_evidence"], "supplied_context")
        world = manifest["world_context"]
        self.assertEqual(world.get("context_status"), "fallback")
        self.assertEqual(world.get("fallback_status"), "seed_data_unavailable")
        self.assertTrue(world.get("read_only"))
        self.assertEqual(manifest["world_context_status"], "fallback")
        # The envelope carries the same canonical provenance.
        self.assertEqual(
            manifest["envelope"]["world_context"],
            world,
        )

    def test_provider_object_evidence(self) -> None:
        manifest = self._build(world_context_provider=_FixtureWorldProvider())
        self.assertEqual(manifest["world_context_evidence"], "provider")
        self.assertEqual(manifest["world_context"].get("read_only"), True)
        self.assertIn("context_status", manifest["world_context"])

    def test_broken_provider_explicit_unavailable_fallback(self) -> None:
        manifest = self._build(world_context_provider=_BrokenWorldProvider())
        self.assertEqual(manifest["world_context_evidence"], "provider_failed")
        self.assertEqual(manifest["world_context_status"], "unavailable")
        self.assertEqual(manifest["world_context_fallback_status"], "seed_data_unavailable")
        found = {str(item.get("code")) for item in manifest.get("diagnostics", [])}
        self.assertIn("world_context_unavailable", found)
        envelope_world = manifest["envelope"]["world_context"]
        self.assertEqual(envelope_world.get("context_status"), "unavailable")
        self.assertTrue(envelope_world.get("read_only"))

    def test_no_context_explicit_unavailable_fallback(self) -> None:
        manifest = self._build()
        self.assertEqual(manifest["world_context_evidence"], "unavailable")
        self.assertEqual(manifest["world_context_status"], "unavailable")
        self.assertEqual(manifest["world_context_fallback_status"], "seed_data_unavailable")
        # No world-seed grounding is claimed.
        self.assertEqual(
            manifest["envelope"]["world_context"].get("world_seed_status"),
            "unavailable",
        )


class TestFailClosedInvalidInputs(_Base):
    def _assert_no_workspace_left(self) -> None:
        scratch_root_abs = REPO_ROOT.joinpath(*Path(self.workspace_root).parts)
        self.assertFalse(scratch_root_abs.exists())

    def test_invalid_module_names(self) -> None:
        for name in ("", "   ", "..", "../x", "a/b", "a b", "a\\b", "x" * 121, "1bad!", ".hidden"):
            result = self._build_module_name(name)
            self._assert_failed_closed(result, "module_name_invalid")
            self._assert_no_workspace_left()

    def _build_module_name(self, name: str) -> Dict[str, Any]:
        return runtime.build_text_description_attempt_workspace(
            name,
            CONCEPT,
            workspace_root=self.workspace_root,
            staging_root=self.staging_root,
        )

    def test_empty_and_missing_concept(self) -> None:
        for concept in (None, "", "   ", b"", b"   "):
            result = self._build(concept=concept)
            self._assert_failed_closed(result, "concept_empty")
            self._assert_no_workspace_left()

    def test_oversized_concept(self) -> None:
        oversized = "x" * (MAX_TEXT_DESCRIPTION_CHARS + 1)
        result = self._build(concept=oversized)
        self._assert_failed_closed(result, "concept_oversized")
        self._assert_no_workspace_left()

    def test_invalid_concept_types(self) -> None:
        for concept in (123, ["text"], {"text": "x"}):
            result = self._build(concept=concept)
            self._assert_failed_closed(result, "concept_invalid_type")
            self._assert_no_workspace_left()

    def test_invalid_utf8_concept(self) -> None:
        result = self._build(concept=b"\xff\xfe\x00bad")
        self._assert_failed_closed(result, "concept_invalid_utf8")
        self._assert_no_workspace_left()

    def test_invalid_attempt_number(self) -> None:
        for value in (0, -1, True, "1"):
            result = self._build(attempt_number=value)
            self._assert_failed_closed(result, "attempt_number_invalid")
            self._assert_no_workspace_left()

    def test_invalid_revision_number(self) -> None:
        for value in (-1, True, "0"):
            result = self._build(revision_number=value)
            self._assert_failed_closed(result, "revision_number_invalid")
            self._assert_no_workspace_left()

    def test_attempt_id_mismatch(self) -> None:
        result = self._build(attempt_id="adapt-001-000000000000000000000000")
        self._assert_failed_closed(result, "attempt_id_mismatch")
        self._assert_no_workspace_left()

    def test_invalid_attempt_id_shape(self) -> None:
        for value in ("../evil", "UPPER"):
            result = self._build(attempt_id=value)
            self._assert_failed_closed(result, "attempt_id_invalid")
            self._assert_no_workspace_left()
        # Valid-format but mismatched identity fails closed as a mismatch.
        result = self._build(attempt_id="adapt-001-000000000000000000000000")
        self._assert_failed_closed(result, "attempt_id_mismatch")
        self._assert_no_workspace_left()

    def test_invalid_job_id(self) -> None:
        result = self._build(job_id=123)
        self._assert_failed_closed(result, "job_id_invalid")
        self._assert_no_workspace_left()

    def test_unsafe_workspace_roots(self) -> None:
        for root in ("/tmp/x", "modules/foo", "characters/x", "data/x", "../x", ""):
            result = self._build(workspace_root=root)
            self._assert_failed_closed(result, "workspace_root_unsafe")
            self._assert_no_workspace_left()

    def test_unsafe_staging_roots(self) -> None:
        for root in ("/tmp/x", "../x", ""):
            result = self._build(staging_root=root)
            self._assert_failed_closed(result, "staging_root_unsafe")
            self._assert_no_workspace_left()
        for root in ("modules/foo", "data/x"):
            result = self._build(staging_root=root)
            self._assert_failed_closed(result, "staging_target_invalid")
            self._assert_no_workspace_left()

    def test_failed_closed_mirror_validates(self) -> None:
        result = self._build_module_name("")
        validation = runtime.validate_text_description_attempt_workspace(result)
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertEqual(validation["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)
        self.assertEqual(validation["workspace"]["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)


class TestWriteFailureFailClosed(_Base):
    def test_safe_write_json_false_fails_closed_and_cleans(self) -> None:
        with mock.patch(
            "web.extensions.toolkit_adaptation_runtime.safe_write_json",
            return_value=False,
        ):
            result = self._build()
        self._assert_failed_closed(result, "workspace_persist_failed")
        self._assert_no_attempt_dirs_left()

    def test_safe_write_json_raises_fails_closed_and_cleans(self) -> None:
        with mock.patch(
            "web.extensions.toolkit_adaptation_runtime.safe_write_json",
            side_effect=OSError("disk full"),
        ):
            result = self._build()
        self._assert_failed_closed(result, "workspace_persist_failed")
        self._assert_no_attempt_dirs_left()

    def test_concept_text_write_failure_fails_closed_and_cleans(self) -> None:
        with mock.patch("pathlib.Path.write_text", side_effect=OSError("read only")):
            result = self._build()
        self._assert_failed_closed(result, "workspace_persist_failed")
        self._assert_no_attempt_dirs_left()

    def test_existing_workspace_fails_closed(self) -> None:
        first = self._build()
        self.assertEqual(first["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        second = self._build()
        self._assert_failed_closed(second, "workspace_exists")
        # The existing workspace is untouched by the refused attempt.
        workspace_abs = self._workspace_abs(first)
        self.assertTrue(workspace_abs.exists())
        self.assertEqual(sorted(p.name for p in workspace_abs.iterdir()), EXPECTED_FILENAMES)


class TestNoModuleRegistryCampaignMutation(_Base):
    def test_modules_listing_unchanged(self) -> None:
        modules_dir = REPO_ROOT / "modules"
        before = set(p.name for p in modules_dir.iterdir()) if modules_dir.exists() else set()
        self._build()
        after = set(p.name for p in modules_dir.iterdir()) if modules_dir.exists() else set()
        self.assertNotIn(MODULE_NAME, after)
        self.assertEqual(after, before)

    def test_staging_target_not_created(self) -> None:
        manifest = self._build()
        self.assertFalse(manifest["output"]["staging_reserved"])
        staging_root_abs = REPO_ROOT.joinpath(*Path(self.staging_root).parts)
        self.assertFalse(staging_root_abs.exists())

    def test_registry_and_campaign_untouched(self) -> None:
        sentinels = (
            REPO_ROOT / "modules" / "world_registry.json",
            REPO_ROOT / "modules" / "campaign.json",
        )
        before = {}
        for sentinel in sentinels:
            if sentinel.exists():
                before[str(sentinel)] = sentinel.stat().st_mtime_ns
        self._build()
        for sentinel in sentinels:
            if str(sentinel) in before:
                self.assertEqual(sentinel.stat().st_mtime_ns, before[str(sentinel)])

    def test_workspace_bounded_to_expected_artifacts(self) -> None:
        manifest = self._build()
        workspace_abs = self._workspace_abs(manifest)
        self.assertEqual(sorted(p.name for p in workspace_abs.iterdir()), EXPECTED_FILENAMES)
        for file_path in manifest["workspace"]["files"].values():
            self.assertNotIn("modules/", file_path)


class TestNoProviderOrNetwork(_Base):
    def test_no_provider_or_builder_calls(self) -> None:
        with mock.patch("utils.ai_client_factory.create_chat_client") as client:
            with mock.patch("core.generators.module_builder.ModuleBuilder") as builder:
                manifest = self._build()
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        client.assert_not_called()
        builder.assert_not_called()

    def test_source_has_no_network_or_os_temp_tripwires(self) -> None:
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        for token in (
            "tempfile",
            "/tmp",
            "socketio",
            "requests.",
            "urllib",
            "from openai",
            "import openai",
            "http.client",
        ):
            self.assertNotIn(token, source)

    def test_no_absolute_paths_in_manifest(self) -> None:
        manifest = self._build()
        serialized = runtime.serialize_text_description_attempt_workspace(manifest)
        self.assertNotIn("/tmp", serialized)
        self.assertNotIn("/Users", serialized)
        self.assertNotIn(str(REPO_ROOT), serialized)


class TestTamperedManifestRejected(_Base):
    def _ready_manifest(self) -> Dict[str, Any]:
        return self._build()

    def test_published_to_modules_tamper_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["output"]["published_to_modules"] = True
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("published_to_modules_invalid", validation["diagnostics"])

    def test_rights_relabel_tamper_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["rights"]["rights_class"] = RIGHTS_CLASS_RESTRICTED
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("rights_class_invalid", validation["diagnostics"])

    def test_module_name_tamper_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["packet_metadata"]["module_name"] = "../evil"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("module_name_invalid", validation["diagnostics"])

    def test_attempt_id_tamper_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["attempt"]["attempt_id"] = "adapt-001-000000000000000000000000"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("attempt_id_mismatch", validation["diagnostics"])

    def test_staging_target_inside_modules_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["output"]["staging_target_path"] = "modules/Evil"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("staging_target_in_modules", validation["diagnostics"])

    def test_workspace_file_inside_modules_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["workspace"]["files"]["concept_source"] = "modules/Evil/source.md"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("workspace_file_in_modules", validation["diagnostics"])

    def test_absolute_workspace_path_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["workspace"]["path"] = "/absolute/path"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("workspace_path_unsafe", validation["diagnostics"])

    def test_model_classified_rights_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["rights"]["classified_by"] = "model"
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("rights_not_python_classified", validation["diagnostics"])

    def test_junk_envelope_rejected(self) -> None:
        manifest = self._ready_manifest()
        manifest["envelope"] = {"status": "invalid", "contract_version": "junk"}
        validation = runtime.validate_text_description_attempt_workspace(manifest)
        self.assertFalse(validation["valid"])
        self.assertIn("envelope_invalid", validation["diagnostics"])


class TestSourceHygiene(unittest.TestCase):
    def test_ascii_only_source(self) -> None:
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        non_ascii = [char for char in source if ord(char) > 127]
        self.assertEqual(non_ascii, [])

    def test_spdx_header_present(self) -> None:
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText: 2024 MoonlightByte", source)
        self.assertIn("SPDX-License-Identifier: Fair-Source-1.0", source)

    def test_public_api_exported(self) -> None:
        for name in (
            "TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION",
            "TEXT_DESCRIPTION_WORKSPACE_STATUS_READY",
            "TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED",
            "DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT",
            "MAX_WORKSPACE_MANIFEST_SERIALIZED_CHARS",
            "CONCEPT_SOURCE_FILENAME",
            "BUILDER_NARRATIVE_FILENAME",
            "NORMALIZED_PACKET_FILENAME",
            "REVIEW_SNAPSHOT_FILENAME",
            "ATTEMPT_METADATA_FILENAME",
            "RUNTIME_ENVELOPE_FILENAME",
            "WORKSPACE_MANIFEST_FILENAME",
            "TEXT_DESCRIPTION_CLASSIFIED_BY",
            "TEXT_DESCRIPTION_SOURCE_KIND",
            "build_text_description_attempt_workspace",
            "serialize_text_description_attempt_workspace",
            "validate_text_description_attempt_workspace",
        ):
            self.assertIn(name, runtime.__all__)

    def test_aliases_discoverable(self) -> None:
        self.assertIs(
            runtime.assemble_text_description_attempt_workspace,
            runtime.build_text_description_attempt_workspace,
        )
        self.assertIs(
            runtime.prepare_text_description_attempt_workspace,
            runtime.build_text_description_attempt_workspace,
        )
        self.assertIs(
            runtime.build_text_attempt_workspace,
            runtime.build_text_description_attempt_workspace,
        )

    def test_contract_version(self) -> None:
        self.assertEqual(
            runtime.TEXT_DESCRIPTION_ATTEMPT_WORKSPACE_CONTRACT_VERSION,
            "toolkit_text_description_attempt_workspace.v1",
        )
        self.assertNotIn("modules", runtime.DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT)
        self.assertNotIn("/tmp", runtime.DEFAULT_TEXT_DESCRIPTION_WORKSPACE_ROOT)


if __name__ == "__main__":
    unittest.main()
