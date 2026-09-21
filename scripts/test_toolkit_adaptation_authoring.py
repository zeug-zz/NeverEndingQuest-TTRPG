# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the adaptation authoring preflight contract."""

import copy
import inspect
import json
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
    persist_adaptation_artifact,
)
from utils.toolkit_adaptation_authoring import (
    AUTHORING_STATUS_BLOCKED,
    AUTHORING_STATUS_READY,
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
    REASON_CODE_NONE,
    REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH,
    prepare_adaptation_authoring_preflight,
    run_adaptation_authoring,
)
from utils.toolkit_adaptation_source_context import build_adaptation_source_context


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_authoring_contract"
SOURCE_HASH = "a" * 64
SOURCE_PATH = "scripts/fixtures/toolkit_adaptation_catalogue.md"


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _response(content: Optional[str] = None, *, refusal: Optional[str] = None) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], model="mock-adaptation-model", id="request-author-1")


class FakeCompletions:
    def __init__(self, response: Any = None, error: Optional[Exception] = None, events=None) -> None:
        self.response = response
        self.error = error
        self.events = events if events is not None else []
        self.calls = []

    def create(self, **kwargs: Any) -> Any:
        self.events.append("provider")
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, error: Optional[Exception] = None, events=None) -> None:
        self.completions = FakeCompletions(response=response, error=error, events=events)
        self.chat = SimpleNamespace(completions=self.completions)


class TestAdaptationAuthoringPreflight(unittest.TestCase):
    """The authoring lane persists evidence before exposing a handoff."""

    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        self.fixture = _load_fixture()
        self.context = build_adaptation_source_context(
            source_summary={
                "source_title": "The Lantern Catalogue",
                "summary": "A bounded catalogue source.",
                "source_hash": SOURCE_HASH,
                "source_path": SOURCE_PATH,
            },
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )
        self.rights = {
            "rights_class": "user_authored",
            "rights_basis": "Operator attested that the uploaded source is user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _run(self, *, attempt_number: int = 1, response: Any = None, error=None, resolver=None, persister=None, events=None, world_context=None):
        client = FakeClient(response=response, error=error, events=events)
        return run_adaptation_authoring(
            self.context,
            workspace=WORKSPACE,
            job_id="authoring-fixture",
            attempt_number=attempt_number,
            rights_metadata=self.rights,
            model="mock-adaptation-model",
            provider="fixture",
            client=client,
            world_context=world_context,
            parameter_resolver=resolver or (lambda task_id, model: {"model": model, "temperature": 0.2}),
            artifact_persister=persister,
        ), client

    def test_valid_authoring_persists_preflight_and_handoff_provenance(self) -> None:
        result, _ = self._run(response=_response(json.dumps(self.fixture)))

        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertTrue(result["handoff_ready"])
        self.assertTrue(result["module_builder_allowed"])
        self.assertFalse(result["module_builder_started"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["registry_mutated"])

        source_path = get_adaptation_artifact_path(
            WORKSPACE, result["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
        )
        dossier_path = get_adaptation_artifact_path(
            WORKSPACE, result["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertTrue(source_path.exists())
        self.assertTrue(dossier_path.exists())
        source_artifact = load_adaptation_artifact(
            WORKSPACE, result["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
        )
        dossier_artifact = load_adaptation_artifact(
            WORKSPACE, result["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        for artifact in (source_artifact, dossier_artifact):
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact["attempt_id"], result["attempt_id"])
            self.assertEqual(artifact["provenance"]["source_hash"], SOURCE_HASH)
            self.assertEqual(artifact["provenance"]["source_path"], SOURCE_PATH)
            self.assertEqual(artifact["provenance"]["rights_class"], "user_authored")
            self.assertEqual(artifact["provenance"]["rights_review_status"], "not_required")
            self.assertEqual(artifact["provenance"]["adaptation_mode"], "llm_adaptation")
            self.assertEqual(artifact["provenance"]["model_metadata"]["model"], "mock-adaptation-model")
        self.assertEqual(dossier_artifact["payload"], self.fixture)

    def test_source_context_is_persisted_before_provider_call(self) -> None:
        events = []

        def recording_persister(workspace: Path, artifact: Dict[str, Any]) -> bool:
            events.append("persist:" + artifact["artifact_kind"])
            return persist_adaptation_artifact(workspace, artifact)

        result, _ = self._run(
            response=_response(json.dumps(self.fixture)),
            persister=recording_persister,
            events=events,
        )

        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertLess(events.index("persist:source_context"), events.index("provider"))
        self.assertLess(events.index("provider"), events.index("persist:adaptation_dossier"))

    def test_world_seed_provenance_reaches_reports_without_raw_world_state(self) -> None:
        world_context = {
            "context_version": "toolkit_adaptation_world_context.v1",
            "context_status": "available",
            "fallback_status": "none",
            "world_seed_status": "available",
            "world_seed_version": "fixture.v2",
            "world_seed_hash": "d" * 64,
            "context_hash": "e" * 64,
            "read_only": True,
            "provider_free": True,
            "campaign_model": {"summary": "must not be persisted"},
            "active_pressures": [{"summary": "must not be persisted"}],
            "registry_context": {"modules": {"Hidden": {"summary": "must not be persisted"}}},
            "approved_module_seeds": [{"content": {"summary": "must not be persisted"}}],
        }
        result, _ = self._run(
            response=_response(json.dumps(self.fixture)),
            world_context=world_context,
        )

        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertEqual(result["world_seed_version"], "fixture.v2")
        self.assertEqual(result["world_seed_hash"], "d" * 64)
        for kind in (ARTIFACT_KIND_SOURCE_CONTEXT, ARTIFACT_KIND_ADAPTATION_DOSSIER):
            artifact = load_adaptation_artifact(WORKSPACE, result["attempt_id"], kind)
            self.assertEqual(artifact["provenance"]["world_seed_version"], "fixture.v2")
            self.assertEqual(artifact["provenance"]["world_seed_hash"], "d" * 64)
            self.assertFalse(artifact["provenance"]["world_context_provenance"]["canon_write_allowed"])
            self.assertNotIn("must not be persisted", json.dumps(artifact, sort_keys=True))

    def test_refusal_provider_parameter_and_invalid_response_are_blocked(self) -> None:
        cases = [
            ("refusal", _response(json.dumps({**self.fixture, "status": "refused"})), None, None),
            ("provider", None, RuntimeError("provider unavailable"), None),
            ("parameter", _response(json.dumps(self.fixture)), None, lambda task_id, model: (_ for _ in ()).throw(RuntimeError("parameter failure"))),
            ("invalid", _response("not-json"), None, None),
        ]
        for index, (label, response, error, resolver) in enumerate(cases, 1):
            with self.subTest(label=label):
                result, _ = self._run(
                    attempt_number=index,
                    response=response,
                    error=error,
                    resolver=resolver,
                )
                self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
                self.assertFalse(result["ok"])
                self.assertFalse(result["module_builder_allowed"])
                self.assertFalse(result["completed"])
                self.assertTrue(result["failure_artifact_persisted"])
                failure_path = get_adaptation_artifact_path(
                    WORKSPACE, result["attempt_id"], ARTIFACT_KIND_FAILURE_REPORT
                )
                self.assertTrue(failure_path.exists())
                self.assertIsNotNone(
                    load_adaptation_artifact(
                        WORKSPACE, result["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
                    )
                )
                self.assertIsNone(
                    load_adaptation_artifact(
                        WORKSPACE, result["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
                    )
                )

    def test_dossier_persistence_failure_is_blocked_and_recorded(self) -> None:
        def fail_dossier_persist(workspace: Path, artifact: Dict[str, Any]) -> bool:
            if artifact["artifact_kind"] == ARTIFACT_KIND_ADAPTATION_DOSSIER:
                return False
            return persist_adaptation_artifact(workspace, artifact)

        result, _ = self._run(
            response=_response(json.dumps(self.fixture)),
            persister=fail_dossier_persist,
        )

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["completed"])
        self.assertTrue(result["failure_artifact_persisted"])
        self.assertIsNotNone(
            load_adaptation_artifact(
                WORKSPACE, result["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
            )
        )
        self.assertIsNotNone(
            load_adaptation_artifact(
                WORKSPACE, result["attempt_id"], ARTIFACT_KIND_FAILURE_REPORT
            )
        )
        self.assertIsNone(
            load_adaptation_artifact(
                WORKSPACE, result["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
            )
        )

    def test_attempts_are_isolated_and_same_attempt_is_idempotent(self) -> None:
        first, first_client = self._run(
            attempt_number=1,
            response=_response(json.dumps(self.fixture)),
        )
        second, second_client = self._run(
            attempt_number=2,
            response=_response(json.dumps(self.fixture)),
        )
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        self.assertTrue(
            get_adaptation_artifact_path(
                WORKSPACE, first["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
            ).exists()
        )
        self.assertTrue(
            get_adaptation_artifact_path(
                WORKSPACE, second["attempt_id"], ARTIFACT_KIND_SOURCE_CONTEXT
            ).exists()
        )

        replay, replay_client = self._run(
            attempt_number=1,
            response=_response(json.dumps(self.fixture)),
        )
        self.assertEqual(replay["status"], AUTHORING_STATUS_BLOCKED)
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["completed"])
        self.assertEqual(replay_client.completions.calls, [])
        self.assertEqual(first["attempt_id"], replay["attempt_id"])
        self.assertEqual(len(first_client.completions.calls), 1)
        self.assertEqual(len(second_client.completions.calls), 1)

    def test_failed_authoring_does_not_touch_preexisting_module_or_registry_data(self) -> None:
        module_dir = WORKSPACE / "modules" / "Existing_Module"
        module_dir.mkdir(parents=True, exist_ok=True)
        context_path = module_dir / "module_context.json"
        marker_path = module_dir / "toolkit_build_report.json"
        registry_path = WORKSPACE / "modules" / "world_registry.json"
        context_path.write_text('{"module": "existing"}', encoding="utf-8")
        marker_path.write_text('{"status": "published"}', encoding="utf-8")
        registry_path.write_text('{"modules": ["Existing_Module"]}', encoding="utf-8")
        before = {
            path: path.read_bytes()
            for path in (context_path, marker_path, registry_path)
        }

        result, _ = self._run(response=_response("invalid-json"))

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["completed"])
        self.assertFalse(result["module_builder_started"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse(
            (WORKSPACE / "adaptation_attempts" / result["attempt_id"] / "module_context.json").exists()
        )

    def test_invalid_rights_blocks_before_provider_and_no_completed_module(self) -> None:
        events = []
        client = FakeClient(response=_response(json.dumps(self.fixture)), events=events)
        result = run_adaptation_authoring(
            self.context,
            workspace=WORKSPACE,
            job_id="rights-fixture",
            model="mock-adaptation-model",
            client=client,
            parameter_resolver=lambda task_id, model: {"model": model},
            rights_class="third_party_copyright_restricted",
            rights_basis="Review is pending.",
            rights_review_required=False,
            rights_review_status="not_required",
        )
        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["completed"])
        self.assertEqual(events, [])
        self.assertFalse((WORKSPACE / "modules").exists())

    def test_preflight_contract_is_provider_free_and_does_not_import_module_builder(self) -> None:
        import utils.toolkit_adaptation_authoring as authoring

        source = inspect.getsource(authoring)
        self.assertNotIn("from core.generators.module_builder", source)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)
        preflight = prepare_adaptation_authoring_preflight(
            self.context,
            workspace=WORKSPACE,
            job_id="preflight-only",
            rights_metadata=self.rights,
            model="mock-adaptation-model",
            client=object(),
        )
        self.assertTrue(preflight["source_context_artifact_persisted"])
        self.assertFalse(preflight.get("module_builder_started", False))
        self.assertFalse(preflight.get("completed", False))


class TestAdaptationAuthoringRightsBasisEchoContract(unittest.TestCase):
    """Production-shaped rights_basis exact-echo regression (task 2.1).

    With Python-owned rights_basis set to the canonical upload token
    ``user_authored_uploaded_adventure``, an exact provider echo is accepted,
    while a dossier that replaces the token with prose is rejected with the
    bounded ``rights_or_provenance_mismatch`` finding on ``rights_basis``.
    """

    CANONICAL_UPLOAD_RIGHTS_BASIS = "user_authored_uploaded_adventure"
    PROSE_PARAPHRASE_RIGHTS_BASIS = (
        "The operator attested that the uploaded source is user-authored."
    )

    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        self.fixture = _load_fixture()
        self.context = build_adaptation_source_context(
            source_summary={
                "source_title": "The Lantern Catalogue",
                "summary": "A bounded catalogue source.",
                "source_hash": SOURCE_HASH,
                "source_path": SOURCE_PATH,
            },
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _run(self, *, provider_rights_basis: str) -> Tuple[Dict[str, Any], FakeClient]:
        # Python-owned rights stay canonical for every run; only the injected
        # provider dossier varies so the echo contract is exercised exactly.
        rights = {
            "rights_class": "user_authored",
            "rights_basis": self.CANONICAL_UPLOAD_RIGHTS_BASIS,
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }
        dossier = copy.deepcopy(self.fixture)
        dossier["rights_basis"] = provider_rights_basis
        client = FakeClient(response=_response(json.dumps(dossier)))
        result = run_adaptation_authoring(
            self.context,
            workspace=WORKSPACE,
            job_id="rights-basis-echo-fixture",
            rights_metadata=rights,
            model="mock-adaptation-model",
            provider="fixture",
            client=client,
            parameter_resolver=lambda task_id, model: {"model": model, "temperature": 0.2},
        )
        return result, client

    def test_exact_rights_basis_echo_passes(self) -> None:
        result, _ = self._run(provider_rights_basis=self.CANONICAL_UPLOAD_RIGHTS_BASIS)

        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertTrue(result["handoff_ready"])
        self.assertTrue(result["module_builder_allowed"])
        self.assertFalse(result["module_builder_started"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_NONE)
        self.assertEqual(result["reason_code"], REASON_CODE_NONE)
        self.assertEqual(
            result["dossier"]["rights_basis"], self.CANONICAL_UPLOAD_RIGHTS_BASIS
        )
        self.assertEqual(result["dossier"]["rights_class"], "user_authored")

    def test_prose_paraphrase_produces_rights_or_provenance_mismatch(self) -> None:
        result, _ = self._run(provider_rights_basis=self.PROSE_PARAPHRASE_RIGHTS_BASIS)

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result.get("handoff_ready"))
        self.assertFalse(result["module_builder_allowed"])
        self.assertFalse(result["module_builder_started"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(
            result["reason_code"], REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH
        )
        self.assertEqual(result["safe_class"], REASON_CATEGORY_RIGHTS_OR_PROVENANCE)
        self.assertFalse(result["revision_eligible"])
        self.assertTrue(result["failure_artifact_persisted"])
        diagnostics = result.get("diagnostics") or []
        self.assertTrue(
            any(
                isinstance(item, Mapping)
                and item.get("path") == "rights_basis"
                and "provenance" in str(item.get("message") or "")
                for item in diagnostics
            ),
            f"no diagnostic names rights_basis: {diagnostics!r}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
