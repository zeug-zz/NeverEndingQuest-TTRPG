# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the text-description adaptation worker seam
(task 5.1 of toolkit-llm-adaptation-runtime-unification).

The suite locks the pre-ModuleBuilder adaptation branch of the legacy
text-description build worker:

  * when ``ENABLE_LLM_ADAPTATION`` is exactly True and the input is eligible,
    the seam resolves the Python-owned ``text_description`` route, builds the
    bounded project-relative attempt workspace, and invokes the shared
    adaptation authoring adapter exactly once before any ModuleBuilder/module
    write;
  * a ready Python-validated dossier preserves attempt/source/rights/world-
    context/staging/workspace identity for the downstream shared publication
    transaction (task 5.2) and never writes to ``modules/<name>``;
  * authoring refusal, invalid/missing workspace, invalid dossier, invalid
    route authority, and infrastructure failure fail closed with an explicit
    adaptation outcome and never fall through to direct legacy generation;
  * missing, invalid, or exactly False flags (and ineligible inputs) keep the
    legacy direct-builder route: the seam returns None and no adaptation
    artifact is required;
  * provider/network work stays behind injected author runners/clients and no
    OS-temporary scratch or absolute temp path is used.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_worker_seam/<uuid>/`` and are removed
deterministically via addCleanup. Real module/registry/campaign sentinels are
byte-checked to prove no direct ``modules/<name>`` write occurs before the
later publication transaction.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.extensions.toolkit_text_adaptation_worker as worker
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_worker_seam"
WORKER_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_text_adaptation_worker.py"
)
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()
MODULE_NAME = "Sunken_Lighthouse"


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata produced by the authoring preflight."""
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        error: Optional[Exception] = None,
        refused: bool = False,
        invalid_dossier: bool = False,
    ) -> None:
        self.calls: list = []
        self.dossier_builder = dossier_builder
        self.error = error
        self.refused = refused
        self.invalid_dossier = invalid_dossier

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append((deepcopy(dict(attempt_metadata or {})), dict(kwargs)))
        if self.error is not None:
            raise self.error
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "diagnostics": [
                    {"code": "dossier_refused", "message": "adaptation author refused the source"}
                ],
                "dossier": None,
            }
        if self.invalid_dossier:
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": {"status": "ready", "adapted_title": "not a real dossier"},
                "diagnostics": [],
            }
        dossier = (
            self.dossier_builder(dict(attempt_metadata or {}))
            if self.dossier_builder
            else None
        )
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-seam-1"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


_REAL_WORKSPACE_BUILDER = worker.build_text_description_attempt_workspace
_REAL_STAGING_CREATOR = worker.create_adaptation_staging_target


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspaces_root = "tmp/toolkit_text_description_worker_seam" + "/" + self.scratch.name + "/workspaces"
        self.staging_root = "tmp/toolkit_text_description_worker_seam" + "/" + self.scratch.name + "/staging"
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        )
        self._flag_patch.start()
        self.addCleanup(self._stop_flag_patch)

    def _stop_flag_patch(self) -> None:
        self._flag_patch.stop()

    def _enable_adaptation(self) -> None:
        """Set the operator flag to exactly True for one test."""
        self._flag_patch.stop()
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self._flag_patch.start()

    def _real_build_into_scratch(self, module_name: str, concept: Any, **kwargs: Any) -> Dict[str, Any]:
        """Wrap the real workspace builder so scratch stays project-local."""
        return _REAL_WORKSPACE_BUILDER(
            module_name,
            concept,
            workspace_root=self.workspaces_root,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _real_staging_into_scratch(self, source_hash: str, **kwargs: Any) -> Dict[str, Any]:
        """Wrap the real staging reservation so scratch stays project-local."""
        kwargs.pop("staging_root", None)
        return _REAL_STAGING_CREATOR(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _run_seam(self, **seam_kwargs: Any) -> Optional[Dict[str, Any]]:
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ):
            return worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None, **seam_kwargs
            )

    def _run_seam_with_runner(self, runner: FakeAuthorRunner) -> Optional[Dict[str, Any]]:
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=self._real_staging_into_scratch,
        ):
            return worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                None,
                author_runner=runner,
                model="mock-adaptation-model",
            )

    def _real_module_sentinels(self) -> Dict[str, Any]:
        """Snapshot real modules/ listing plus registry/campaign bytes."""
        modules_dir = REPO_ROOT / "modules"
        listing: list = []
        if modules_dir.exists():
            listing = sorted(
                str(p.relative_to(REPO_ROOT))
                for p in modules_dir.rglob("*")
                if p.is_file()
            )
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        registry_bytes = registry_path.read_bytes() if registry_path.exists() else None
        campaign_bytes = campaign_path.read_bytes() if campaign_path.exists() else None
        return {
            "listing": listing,
            "registry_bytes": registry_bytes,
            "campaign_bytes": campaign_bytes,
        }

    def _assert_real_sentinels_unchanged(self, snapshot: Dict[str, Any]) -> None:
        modules_dir = REPO_ROOT / "modules"
        listing = (
            sorted(str(p.relative_to(REPO_ROOT)) for p in modules_dir.rglob("*") if p.is_file())
            if modules_dir.exists()
            else []
        )
        self.assertEqual(listing, snapshot["listing"], "modules/ listing changed")
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        self.assertEqual(
            registry_path.read_bytes() if registry_path.exists() else None,
            snapshot["registry_bytes"],
        )
        self.assertEqual(
            campaign_path.read_bytes() if campaign_path.exists() else None,
            snapshot["campaign_bytes"],
        )
        self.assertFalse(
            (REPO_ROOT / "modules" / MODULE_NAME).exists(),
            "no direct modules/<name> write is allowed before publication",
        )


class TestSeamLegacyRoutes(_ProjectLocalScratchMixin, unittest.TestCase):
    """Missing/invalid/False flags and ineligible inputs keep legacy."""

    def test_exact_false_flag_returns_none(self) -> None:
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None, author_runner=runner
            )
        self.assertIsNone(result)
        self.assertEqual(len(runner.calls), 0)

    def test_missing_flag_returns_none(self) -> None:
        had_flag = hasattr(model_config_module, "ENABLE_LLM_ADAPTATION")
        saved = getattr(model_config_module, "ENABLE_LLM_ADAPTATION", None)
        if had_flag:
            del model_config_module.ENABLE_LLM_ADAPTATION
        try:
            with patch.object(
                worker,
                "build_text_description_attempt_workspace",
                side_effect=self._real_build_into_scratch,
            ):
                result = worker.run_text_description_adaptation_seam(
                    MODULE_NAME, FIXTURE_TEXT, None
                )
            self.assertIsNone(result)
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION = saved

    def test_invalid_flag_values_return_none(self) -> None:
        for junk in ("yes", "1", 1, 0, [], {}, 3.5):
            with self.subTest(value=repr(junk)):
                self._flag_patch.stop()
                self._flag_patch = patch.object(
                    model_config_module, "ENABLE_LLM_ADAPTATION", junk
                )
                self._flag_patch.start()
                result = worker.run_text_description_adaptation_seam(
                    MODULE_NAME, FIXTURE_TEXT, None
                )
                self.assertIsNone(result)

    def test_enabled_but_empty_description_returns_none(self) -> None:
        self._enable_adaptation()
        result = worker.run_text_description_adaptation_seam(
            MODULE_NAME, "   ", None
        )
        self.assertIsNone(result)

    def test_enabled_but_invalid_module_name_returns_none(self) -> None:
        self._enable_adaptation()
        result = worker.run_text_description_adaptation_seam(
            "Bad Module Name!", FIXTURE_TEXT, None
        )
        self.assertIsNone(result)

    def test_enabled_but_oversized_description_returns_none(self) -> None:
        self._enable_adaptation()
        from utils import toolkit_adaptation_config

        with patch.object(toolkit_adaptation_config, "MAX_TEXT_DESCRIPTION_CHARS", 10):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None
            )
        self.assertIsNone(result)

    def test_legacy_path_requires_no_adaptation_artifacts(self) -> None:
        from utils.toolkit_adaptation_artifacts import build_attempt_id

        result = self._run_seam()
        self.assertIsNone(result)
        attempt_id = build_attempt_id(FIXTURE_HASH, 1, "")
        self.assertFalse(
            (REPO_ROOT / "tmp" / "toolkit-text-workspaces" / attempt_id).exists(),
            "legacy path must not create a text-description attempt workspace",
        )
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())


class TestSeamReadyHandoff(_ProjectLocalScratchMixin, unittest.TestCase):
    """Enabled success reaches only the adaptation handoff seam."""

    def test_enabled_ready_handoff_preserves_identity(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_seam_with_runner(runner)

        self.assertIsNotNone(result)
        self.assertEqual(
            result["outcome"], worker.TEXT_WORKER_OUTCOME_AUTHORING_READY
        )
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_READY)
        self.assertEqual(
            result["contract_version"],
            worker.TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        )
        self.assertEqual(
            result["route_decision"]["status"], "adaptation"
        )
        self.assertIs(result["route_decision"]["fallback_allowed"], False)

        handoff = result["adaptation_handoff"]
        self.assertEqual(handoff["module_name"], MODULE_NAME)
        self.assertEqual(handoff["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["source_title"], MODULE_NAME)
        attempt = handoff["attempt"]
        self.assertTrue(attempt["attempt_id"])
        self.assertEqual(attempt["attempt_number"], 1)
        self.assertEqual(attempt["revision_number"], 0)
        self.assertEqual(handoff["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertIs(handoff["rights"]["python_owned"], True)
        self.assertIs(handoff["rights"]["provider_may_change"], False)
        # Canonical bounded world-context provenance with explicit fallback.
        self.assertEqual(handoff["world_context"]["fallback_status"], "seed_data_unavailable")
        self.assertIs(handoff["world_context"]["read_only"], True)
        self.assertIs(handoff["world_context"]["raw_context_included"], False)
        self.assertIs(handoff["world_context"]["provider_free"], True)
        # Dossier artifact reference persisted atomically inside the workspace.
        self.assertTrue(handoff["dossier_artifact_path"])
        self.assertTrue(handoff["dossier_artifact_path"].endswith("dossier.json"))
        self.assertIn("toolkit_text_description_worker_seam", handoff["workspace_path"])
        self.assertNotIn("modules/", handoff["workspace_path"])
        # Reserved staging target is project-relative and never under modules.
        self.assertIn("toolkit_text_description_worker_seam", handoff["staging_target_path"])
        self.assertNotIn("modules/", handoff["staging_target_path"])
        self.assertIs(result["route_decision"]["adaptation_artifacts_required"], True)

        # The ready dossier is Python-validated and build-ready.
        from utils.toolkit_adaptation_dossier import validate_adaptation_dossier

        dossier_validation = validate_adaptation_dossier(handoff["dossier"])
        self.assertTrue(dossier_validation["valid"])
        self.assertTrue(dossier_validation["build_ready"])

        # Staging target reserved on disk with metadata.
        staging_abs = REPO_ROOT.joinpath(*Path(handoff["staging_target_path"]).parts)
        self.assertTrue(staging_abs.is_dir())
        metadata_path = staging_abs / "staging_metadata.json"
        self.assertTrue(metadata_path.exists())

        # Authoring invoked exactly once with Python-owned attempt metadata.
        self.assertEqual(len(runner.calls), 1)
        attempt_metadata = runner.calls[0][0]
        self.assertEqual(attempt_metadata["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(attempt_metadata["source_hash"], FIXTURE_HASH)

        # Dossier artifact persisted inside the attempt workspace.
        workspace_abs = REPO_ROOT.joinpath(*Path(handoff["workspace_path"]).parts)
        dossier_artifact = load_adaptation_artifact(
            workspace_abs, attempt["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)

        self._assert_real_sentinels_unchanged(sentinels)

    def test_enabled_ready_handoff_never_touches_direct_builder(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_seam_with_runner(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_AUTHORING_READY)
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())
        self._assert_real_sentinels_unchanged(sentinels)

    def test_enabled_ready_handoff_authoring_invoked_exactly_once(self) -> None:
        self._enable_adaptation()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_seam_with_runner(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_AUTHORING_READY)
        self.assertEqual(len(runner.calls), 1)


class TestSeamBlockedPaths(_ProjectLocalScratchMixin, unittest.TestCase):
    """Selected adaptation failures fail closed before direct legacy."""

    def _assert_blocked(self, result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        self.assertIsNotNone(result)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_FAILED_CLOSED)
        self.assertEqual(
            result["route_decision"]["route_selected"], "llm_adaptation"
        )
        return result

    def test_author_policy_refusal_blocks(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run_seam_with_runner(runner)
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "dossier_refused")
        self.assertEqual(len(runner.calls), 1)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_authoring_infrastructure_failure_blocks(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt,
            error=RuntimeError("provider timeout"),
        )
        result = self._run_seam_with_runner(runner)
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "text_description_authoring_infrastructure_failure")
        self.assertEqual(len(runner.calls), 1)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_invalid_dossier_blocks(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(invalid_dossier=True)
        result = self._run_seam_with_runner(runner)
        result = self._assert_blocked(result)
        self.assertTrue(result["reason_code"])
        self._assert_real_sentinels_unchanged(sentinels)

    def test_workspace_failure_blocks_before_authoring(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        failed_manifest = {
            "contract_version": "toolkit_text_description_attempt_workspace.v1",
            "status": "failed_closed",
            "diagnostics": [
                {"code": "concept_empty", "message": "text description concept is required"}
            ],
        }
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            return_value=failed_manifest,
        ):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None, author_runner=runner
            )
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "text_description_workspace_failed")
        self.assertEqual(len(runner.calls), 0)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_workspace_infrastructure_failure_blocks(self) -> None:
        self._enable_adaptation()
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=OSError("disk full"),
        ):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None
            )
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "text_description_workspace_infrastructure_failure")

    def test_invalid_route_authority_blocks(self) -> None:
        self._enable_adaptation()
        tampered = {
            "contract_version": "toolkit_adaptation_route_decision.v1",
            "status": "adaptation",
            "route_selected": "llm_adaptation",
            "input_kind": "text_description",
            "fallback_allowed": False,
            "adaptation_artifacts_required": True,
            "flag_resolution": {"status": "enabled"},
            "eligibility": {"eligible": True, "reasons": []},
            "rights": {"python_owned": False, "classified_by": "model"},
            "text_input": {"module_name": MODULE_NAME, "description_bounded": True, "description_chars": 10},
            "attempt": {"attempt_id": None, "attempt_number": 1},
        }
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        with patch.object(worker, "resolve_adaptation_input_route", return_value=tampered):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None, author_runner=runner
            )
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "adaptation_route_authority_invalid")
        self.assertEqual(len(runner.calls), 0)

    def test_staging_reservation_failure_blocks_after_ready_dossier(self) -> None:
        self._enable_adaptation()
        sentinels = self._real_module_sentinels()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=RuntimeError("staging target exists"),
        ):
            result = worker.run_text_description_adaptation_seam(
                MODULE_NAME, FIXTURE_TEXT, None, author_runner=runner
            )
        result = self._assert_blocked(result)
        self.assertEqual(result["reason_code"], "adaptation_staging_reservation_failed")
        self.assertEqual(len(runner.calls), 1)
        self._assert_real_sentinels_unchanged(sentinels)


class TestSeamHygiene(unittest.TestCase):
    """ASCII, SPDX, path policy, and provider-free source contracts."""

    def test_worker_module_has_spdx_header_and_all_exports(self) -> None:
        source = WORKER_MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText: 2024 MoonlightByte", source)
        self.assertIn("SPDX-License-Identifier: Fair-Source-1.0", source)
        self.assertIn("__all__", source)

    def test_worker_module_is_ascii_only(self) -> None:
        source = WORKER_MODULE_PATH.read_text(encoding="utf-8")
        try:
            source.encode("ascii")
        except UnicodeEncodeError as exc:
            self.fail(f"non-ASCII bytes in worker module: {exc}")

    def test_worker_module_has_no_provider_network_or_host_tokens(self) -> None:
        source = WORKER_MODULE_PATH.read_text(encoding="utf-8")
        # Prose may legitimately name ModuleBuilder, so lock only the precise
        # import/call shapes that would actually invoke the builder.
        forbidden = (
            "tempfile",
            "/tmp",
            "socketio",
            "start_build",
            "simulate_build_process",
            "web_interface",
            "create_chat_client",
            "requests.get",
            "urllib.request",
            "openai",
            "OpenAI",
            "completions.create",
            "from core.generators.module_builder import",
            "import module_builder",
            "ModuleBuilder(",
            "module_builder.build_module(",
        )
        for token in forbidden:
            self.assertNotIn(token, source, f"forbidden token present: {token}")

    def test_worker_module_never_imports_the_builder(self) -> None:
        import ast

        tree = ast.parse(WORKER_MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("module_builder", node.module or "")
                self.assertNotIn("web_interface", node.module or "")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("module_builder", alias.name)
                    self.assertNotIn("web_interface", alias.name)

    def test_this_suite_uses_only_project_local_scratch(self) -> None:
        # Only the part of this file before the hygiene self-scan tokens may
        # be scanned; the self-scan token tuples legitimately name tempfile
        # and /tmp inside this suite itself.
        source = Path(__file__).read_text(encoding="utf-8")
        scan_source = source.split("class TestSeamHygiene", 1)[0]
        self.assertNotIn("tempfile", scan_source)
        self.assertNotIn("/tmp", scan_source)
        self.assertIn("tmp/toolkit_text_description_worker_seam", scan_source)

    def test_this_suite_never_imports_provider_modules(self) -> None:
        import_lines = [
            line.strip()
            for line in Path(__file__).read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        for token in (
            "import openai",
            "import httpx",
            "import requests",
            "import socketio",
            "import urllib",
            "import http",
            "import socket",
            "import aiohttp",
            "import websockets",
            "import tempfile",
            "from openai",
            "from requests",
            "from socketio",
        ):
            self.assertNotIn(token, imports)


if __name__ == "__main__":
    unittest.main()
