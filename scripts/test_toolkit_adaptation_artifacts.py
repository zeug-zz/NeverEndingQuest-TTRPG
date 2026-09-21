# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for toolkit adaptation attempt artifacts."""

import copy
import inspect
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_artifacts as artifact_contract
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_PUBLICATION_REPORT,
    ARTIFACT_KIND_REVISION_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    ARTIFACT_STAGE_BUILD,
    ARTIFACT_STAGE_DRAFT,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_PUBLICATION,
    ARTIFACT_STAGE_REVISED,
    BUILD_STATUS_PASSED,
    FAILURE_CLASS_SEMANTIC,
    REVISION_DECISION_REVISE,
    build_adaptation_dossier_artifact,
    build_attempt_id,
    build_build_result_artifact,
    build_failure_report_artifact,
    build_publication_report_artifact,
    build_revision_report_artifact,
    build_source_context_artifact,
    get_adaptation_artifact_path,
    get_attempt_artifact_paths,
    load_adaptation_artifact,
    persist_adaptation_artifact,
    persist_build_result_artifact,
    parse_adaptation_artifact,
    validate_adaptation_artifact,
)
from utils.toolkit_adaptation_dossier import validate_adaptation_dossier


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_artifact_contract"
SOURCE_HASH = "a" * 64
SOURCE_PATH = "user_uploads/lantern_catalogue.md"


def _fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ref(path: str, digest: str = SOURCE_HASH, kind: str = "report") -> dict:
    return {
        "path": path,
        "sha256": digest,
        "kind": kind,
        "reference_only": True,
    }


class TestArtifactContract(unittest.TestCase):
    """All six artifacts share a strict attempt and provenance envelope."""

    def setUp(self):
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        self.attempt_id = build_attempt_id(SOURCE_HASH, 1, "fixture-job")
        self.dossier = _fixture()

    def tearDown(self):
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _source_context(self):
        return build_source_context_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            source_profile="catalogue",
            summary="A bounded catalogue summary, not the raw upload.",
            section_summaries=[
                {
                    "heading": "Item listings",
                    "summary": "Travel lights and one suspicious black lantern.",
                    "source_ref": {"path": SOURCE_PATH, "sha256": SOURCE_HASH},
                }
            ],
        )

    def _dossier_artifact(self):
        return build_adaptation_dossier_artifact(
            self.dossier,
            attempt_id=self.attempt_id,
            source_path=SOURCE_PATH,
            model_metadata={"provider": "fixture", "model": "provider_free"},
        )

    def _failure(self, revision_number=0):
        return build_failure_report_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            failure_class=FAILURE_CLASS_SEMANTIC,
            failed_stage=ARTIFACT_STAGE_BUILD,
            diagnostics=[
                {
                    "code": "semantic_gate_failed",
                    "message": "A bounded semantic gate rejected the candidate.",
                    "severity": "error",
                    "path": "semantic_authority",
                }
            ],
            revision_number=revision_number,
            summary="Candidate requires a bounded dossier revision.",
            recoverable=True,
            gate="semantic_authority",
        )

    def _revision(self):
        failure_path = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_FAILURE_REPORT
        )
        failure_ref_path = str(failure_path.relative_to(REPO_ROOT))
        revised_dossier_path = get_adaptation_artifact_path(
            WORKSPACE,
            self.attempt_id,
            ARTIFACT_KIND_ADAPTATION_DOSSIER,
            1,
        )
        return build_revision_report_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            revision_number=1,
            decision=REVISION_DECISION_REVISE,
            reason="Repair the semantic relationship between the shop hook and the encounter.",
            history=[
                {"revision_number": 0, "status": "failed", "reason": "semantic gate"},
                {"revision_number": 1, "status": "revised", "reason": "fresh rebuild requested"},
            ],
            failure_artifact_refs=[_ref(failure_ref_path, kind="failure_report")],
            revised_dossier_ref=_ref(
                str(revised_dossier_path.relative_to(REPO_ROOT)),
                kind="adaptation_dossier",
            ),
            rebuild_directive={
                "action": "fresh_build",
                "target": "staging",
                "target_path": "tmp/adaptation-staging/fixture-job/revision-001",
            },
        )

    def _build(self, revision_number=0):
        return build_build_result_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            staging_path="tmp/adaptation-staging/fixture-job/revision-001",
            build_status=BUILD_STATUS_PASSED,
            module_slug="Lantern_Market",
            gate_summary={"schema": "pass", "readiness": "pass"},
            module_artifacts=[
                _ref("tmp/adaptation-staging/fixture-job/revision-001/module_context_BU.json", kind="module_context")
            ],
            revision_number=revision_number,
            output_hash=SOURCE_HASH,
        )

    def _publication(self):
        readiness = {
            "schema": {"status": "pass", "report_path": "tmp/reports/schema.json"},
            "readiness": {"status": "pass", "report_path": "tmp/reports/readiness.json"},
            "semantic": {"status": "pass", "report_path": "tmp/reports/semantic.json"},
            "report_agreement": {"status": "pass", "report_path": "tmp/reports/agreement.json"},
            "markdown": {"status": "pass", "report_path": "tmp/reports/markdown.json"},
        }
        return build_publication_report_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            readiness_evidence=readiness,
            registry_evidence={
                "status": "not_run",
                "verified": False,
                "path": "modules/world_registry.json",
            },
            module_artifact_refs=[
                _ref("tmp/adaptation-staging/fixture-job/revision-001/module_context_BU.json", kind="module_context")
            ],
            source_fidelity_status="not_applicable",
        )

    def test_reports_carry_scalar_world_provenance_and_read_only_markers(self):
        world_provenance = {
            "context_version": "toolkit_adaptation_world_context.v1",
            "context_status": "available",
            "fallback_status": "none",
            "world_seed_status": "available",
            "world_seed_version": "fixture.v2",
            "world_seed_hash": "b" * 64,
            "context_hash": "c" * 64,
            "selected_module": "Lantern_Market",
            "read_only": True,
            "provider_free": True,
            "raw_context_included": False,
            "canon_write_allowed": False,
            "registry_write_allowed": False,
            "mechanical_write_allowed": False,
        }
        artifact = build_build_result_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            staging_path="tmp/adaptation-staging/fixture-job/revision-001",
            build_status=BUILD_STATUS_PASSED,
            module_slug="Lantern_Market",
            world_context_provenance=world_provenance,
        )
        self.assertTrue(validate_adaptation_artifact(artifact)["valid"])
        self.assertEqual(artifact["provenance"]["world_seed_version"], "fixture.v2")
        self.assertEqual(artifact["provenance"]["world_seed_hash"], "b" * 64)
        self.assertEqual(artifact["provenance"]["context_hash"], "c" * 64)
        self.assertTrue(artifact["provenance"]["world_context_read_only"])
        self.assertNotIn("campaign_model", json.dumps(artifact, sort_keys=True))

    def test_attempt_id_and_paths_are_stable_and_revision_scoped(self):
        self.assertEqual(self.attempt_id, build_attempt_id(SOURCE_HASH, 1, "fixture-job"))
        self.assertNotEqual(self.attempt_id, build_attempt_id(SOURCE_HASH, 2, "fixture-job"))
        paths = get_attempt_artifact_paths(WORKSPACE, self.attempt_id)
        self.assertEqual(set(paths), {
            ARTIFACT_KIND_SOURCE_CONTEXT,
            ARTIFACT_KIND_ADAPTATION_DOSSIER,
            ARTIFACT_KIND_FAILURE_REPORT,
            ARTIFACT_KIND_REVISION_REPORT,
            ARTIFACT_KIND_BUILD_RESULT,
            ARTIFACT_KIND_PUBLICATION_REPORT,
        })
        self.assertIn(self.attempt_id, str(paths[ARTIFACT_KIND_SOURCE_CONTEXT]))
        revised = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_BUILD_RESULT, 1
        )
        self.assertNotEqual(revised, paths[ARTIFACT_KIND_BUILD_RESULT])
        self.assertIn("revision_001", str(revised))

    def test_all_artifact_kinds_validate_with_distinct_stages(self):
        artifacts = [
            self._source_context(),
            self._dossier_artifact(),
            self._failure(),
            self._revision(),
            self._build(),
            self._publication(),
        ]
        expected_stages = [
            ARTIFACT_STAGE_DRAFT,
            ARTIFACT_STAGE_DRAFT,
            ARTIFACT_STAGE_FAILED,
            ARTIFACT_STAGE_REVISED,
            ARTIFACT_STAGE_BUILD,
            ARTIFACT_STAGE_PUBLICATION,
        ]
        for artifact, stage in zip(artifacts, expected_stages):
            result = validate_adaptation_artifact(artifact)
            self.assertTrue(result["valid"], result["diagnostics"])
            self.assertEqual(artifact["stage"], stage)
            self.assertEqual(artifact["attempt_id"], self.attempt_id)
            self.assertEqual(artifact["provenance"]["source_hash"], SOURCE_HASH)
            self.assertIn("model_metadata", artifact["provenance"])
            self.assertEqual(artifact["version"], "toolkit_adaptation_artifact.v1")

    def test_dossier_artifact_reuses_strict_dossier_validation(self):
        artifact = self._dossier_artifact()
        self.assertTrue(validate_adaptation_dossier(artifact["payload"])["valid"])
        broken = copy.deepcopy(artifact)
        broken["payload"]["areas"] = "not-an-array"
        result = validate_adaptation_artifact(broken)
        self.assertFalse(result["valid"])

    def test_source_context_rejects_raw_source_and_absolute_reference(self):
        artifact = self._source_context()
        artifact["payload"]["raw_source"] = "unbounded source text"
        result = validate_adaptation_artifact(artifact)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] == "unbounded_source_content" for item in result["diagnostics"]))

        bad = self._source_context()
        bad["payload"]["source_ref"]["path"] = "/private/source.md"
        self.assertFalse(validate_adaptation_artifact(bad)["valid"])

    def test_revision_requires_fresh_staging_and_preserves_history(self):
        artifact = self._revision()
        self.assertEqual(artifact["revision_number"], 1)
        self.assertEqual(artifact["payload"]["history"][0]["revision_number"], 0)
        broken = copy.deepcopy(artifact)
        broken["payload"]["fresh_staging_required"] = False
        self.assertFalse(validate_adaptation_artifact(broken)["valid"])

    def test_publication_contains_readiness_evidence_without_module_payload(self):
        artifact = self._publication()
        self.assertIn("readiness_evidence", artifact["payload"])
        self.assertNotIn("module_data", artifact["payload"])
        self.assertTrue(validate_adaptation_artifact(artifact)["valid"])

    def test_build_result_preserves_bounded_model_metadata(self):
        model_metadata = {
            "provider": "fixture",
            "model": "provider-free-builder",
            "parameter_profile": "adaptation_build",
        }
        artifact = build_build_result_artifact(
            attempt_id=self.attempt_id,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            staging_path="tmp/adaptation-staging/fixture-job/revision-001",
            build_status=BUILD_STATUS_PASSED,
            module_slug="Lantern_Market",
            model_metadata=model_metadata,
        )

        self.assertTrue(validate_adaptation_artifact(artifact)["valid"])
        self.assertEqual(artifact["provenance"]["model_metadata"], model_metadata)

    def test_persistence_is_atomic_and_loadable(self):
        artifact = self._source_context()
        self.assertTrue(persist_adaptation_artifact(WORKSPACE, artifact))
        path = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT
        )
        self.assertTrue(path.exists())
        loaded = load_adaptation_artifact(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT
        )
        self.assertEqual(loaded, artifact)
        self.assertFalse(Path(str(path) + ".reserve").exists())

    def test_plain_builder_result_uses_legacy_workspace_compatibility_boundary(self):
        build_result = {
            "status": "success",
            "stage": "build",
            "module_name": "Lantern_Market",
        }

        self.assertTrue(persist_build_result_artifact(WORKSPACE, build_result))
        persisted = json.loads((WORKSPACE / "build_result.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted, build_result)

    def test_existing_artifact_is_not_silently_overwritten(self):
        artifact = self._source_context()
        self.assertTrue(persist_adaptation_artifact(WORKSPACE, artifact))
        changed = copy.deepcopy(artifact)
        changed["payload"]["summary"] = "A different attempt summary."
        self.assertFalse(persist_adaptation_artifact(WORKSPACE, changed))
        loaded = load_adaptation_artifact(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT
        )
        self.assertEqual(loaded["payload"]["summary"], artifact["payload"]["summary"])

    def test_revision_artifact_uses_new_path_without_overwriting_initial_build(self):
        initial = self._build(0)
        revised = self._build(1)
        self.assertTrue(persist_adaptation_artifact(WORKSPACE, initial))
        self.assertTrue(persist_adaptation_artifact(WORKSPACE, revised))
        initial_path = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_BUILD_RESULT, 0
        )
        revised_path = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_BUILD_RESULT, 1
        )
        self.assertTrue(initial_path.exists())
        self.assertTrue(revised_path.exists())
        self.assertNotEqual(initial_path, revised_path)

    def test_write_failure_is_fail_safe(self):
        artifact = self._source_context()
        with patch.object(artifact_contract, "safe_write_json", return_value=False):
            self.assertFalse(persist_adaptation_artifact(WORKSPACE, artifact))
        path = get_adaptation_artifact_path(
            WORKSPACE, self.attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT
        )
        self.assertFalse(path.exists())

    def test_parser_rejects_malformed_artifact_json(self):
        result = parse_adaptation_artifact('{"version":')
        self.assertFalse(result["valid"])
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_json")

    def test_provider_free_boundary_and_no_raw_source_write(self):
        source = inspect.getsource(artifact_contract)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        self.assertIn("safe_write_json", source)
        self.assertNotIn("write_text", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
