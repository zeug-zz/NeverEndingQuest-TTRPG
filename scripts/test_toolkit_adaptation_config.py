# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free feature configuration and routing tests for the toolkit
LLM adaptation lane (task 1.3).

Verifies that the shipped default is disabled, that invalid or missing
configuration fails safely to the documented legacy accurate-ingest
behavior, and that explicit legacy accurate-ingest routing remains
unchanged until rollout enables adaptation. The live operator
``model_config.ENABLE_LLM_ADAPTATION`` value is never assumed; every
behavioral test passes an explicit override or patches the module
attribute. All fixtures and generated scratch live under the project-local
``tmp/toolkit_adaptation_config/<uuid>/`` directory and are removed via
addCleanup; no OS temp directory is used.
"""

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
from utils import toolkit_adaptation_config as adaptation_config
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LEGACY_ACCURATE_INGEST,
    BUILD_MODE_LLM_ADAPTATION,
    ENABLE_LLM_ADAPTATION_DEFAULT,
    LEGACY_ACCURATE_INGEST_BUILD_MODES,
    ROUTING_REASON_DISABLED,
    ROUTING_REASON_INVALID_REQUEST,
    ROUTING_REASON_NOT_REQUESTED,
    ROUTING_REASON_REQUESTED_AND_ENABLED,
    ROUTING_STATUS_ENABLED,
    ROUTING_STATUS_LEGACY,
    adaptation_enabled,
    canonical_monster_generation_enabled,
    is_legacy_accurate_ingest_build_mode,
    is_llm_adaptation_build_mode,
    resolve_adaptation_routing,
)
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    create_adaptation_staging_target,
)
from web.extensions.toolkit_homebrew_packet_builder import (
    run_toolkit_homebrew_packet_build,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Project-local scratch root for fixtures and generated artifacts. The repo
# keeps its task scratch under tmp/ (git-ignored); each suite run gets a
# unique subdirectory that is removed in cleanup.
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_config"

# Valid lowercase SHA-256 source identity used by the dossier fixture and the
# packet source hash so the adaptation handoff source-hash check passes.
ADAPTATION_SOURCE_HASH = "a" * 64

FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)

# Matches the v2 blueprint version used by the existing toolkit routing tests.
VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"

_V2_BLUEPRINT = {
    "blueprint_version": VALID_V2_VERSION,
    "blueprint_status": "ready",
    "module": {"title": "Test Adaptation Fixture", "summary": "fixture"},
    "source_lock": {"canonical_names_locked": True},
    "area_plan": [],
    "location_roster": [],
    "npc_roster": [],
    "plot_graph": [],
    "puzzle_graph": [],
    "clue_graph": [],
    "encounter_plan": [],
    "item_roster": [],
    "tone_requirements": [],
    "source_refs": [],
    "warnings": [],
    "coverage": {},
    "enrichment_allowlist": {},
    "artifact_refs": {},
    "blockers": [],
}


def _create_workspace(tmpdir: str, source_hash: str) -> Path:
    """Create a minimal approved workspace with a ready v2 blueprint."""
    ws = Path(tmpdir) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    files = {
        "normalized_packet.json": {
            "packet_version": "packet.v1",
            "name": "pipeline-001",
            "title": "Test Adaptation Fixture",
            "description": "A test adventure for adaptation routing tests",
            "source_hash": source_hash,
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        },
        "ui_review_snapshot.json": {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": "adaptation-routing-job",
            "packet_identity": {"source_hash": source_hash},
        },
        "builder_blueprint.json": _V2_BLUEPRINT,
        "builder_blueprint_report.json": {
            "blueprint_status": "ready",
            "fidelity_status": "pass",
        },
        "builder_narrative.txt": "Test narrative for adaptation routing build",
    }
    for filename, content in files.items():
        path = ws / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(content) if isinstance(content, dict) else content,
            encoding="utf-8",
        )
    return ws


def _load_fixture_dossier() -> Dict[str, Any]:
    """Load the repository's validated build-ready dossier fixture."""
    with FIXTURE_DOSSIER_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _fixture_provenance(attempt_id: str) -> Dict[str, Any]:
    """Bounded attempt/model provenance for the enabled adaptation handoff."""
    return {
        "attempt_id": attempt_id,
        "attempt_number": 1,
        "revision_number": 0,
        "job_id": "adaptation-routing-job",
        "source_path": "uploads/fixture.md",
        "source_format": "upload_markdown",
        "model_metadata": {"provider": "openai", "model": "gpt-5.6-luna"},
    }


class TestAdaptationFeatureConfiguration(unittest.TestCase):
    """The adaptation lane is configurable with a safe shipped default."""

    def test_config_default_constant_is_false(self):
        self.assertIs(ENABLE_LLM_ADAPTATION_DEFAULT, False)

    def test_resolver_is_safe_under_explicit_overrides(self):
        # The resolver never depends on the live operator value for its
        # contract: explicit overrides drive the outcome deterministically.
        self.assertIs(adaptation_enabled(enabled_override=True), True)
        self.assertIs(adaptation_enabled(enabled_override=False), False)

    def test_model_config_still_declares_the_feature_flag(self):
        text = (REPO_ROOT / "model_config.py").read_text(encoding="utf-8")
        self.assertIn("ENABLE_LLM_ADAPTATION", text)

    def test_disabled_rollout_keeps_canonical_generation_off(self):
        # Rollout defaults are operator-controlled.  Exercise the disabled
        # compatibility contract with explicit test overrides instead of
        # asserting the active deployment configuration.
        with patch.object(
            model_config_module,
            "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            False,
        ), patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", False):
            self.assertIs(canonical_monster_generation_enabled(), False)
            self.assertIs(adaptation_enabled(), False)

    def test_canonical_generation_requires_exact_true(self):
        for value in (False, "true", "1", 1, 0, 1.0, [], {}):
            with self.subTest(value=repr(value)):
                self.assertIs(canonical_monster_generation_enabled(value), False)
        self.assertIs(canonical_monster_generation_enabled(True), True)
        with patch.object(
            model_config_module,
            "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            False,
        ):
            self.assertIs(canonical_monster_generation_enabled(), False)

    def test_missing_canonical_generation_config_is_disabled(self):
        saved = getattr(
            model_config_module,
            "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION",
            None,
        )
        had_flag = hasattr(model_config_module, "ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION")
        if had_flag:
            del model_config_module.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION
        try:
            self.assertIs(canonical_monster_generation_enabled(), False)
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = saved

    def test_config_template_documents_flag_and_rollout_gating(self):
        text = (REPO_ROOT / "config_template.py").read_text(encoding="utf-8")
        self.assertIn("# ENABLE_LLM_ADAPTATION = False", text)
        self.assertIn(
            "# ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION = False",
            text,
        )
        self.assertIn("LLM-led", text)
        self.assertIn("legacy accurate-ingest", text)

    def test_explicit_true_override_enables(self):
        self.assertIs(adaptation_enabled(enabled_override=True), True)

    def test_invalid_config_values_fail_safe_to_disabled(self):
        # NOTE: None is NOT invalid: it is the "read live model_config"
        # sentinel and is covered separately by the missing-flag test. Only
        # non-boolean junk values must fail safe to disabled.
        for junk in ("yes", "1", 1, 0, [], {}, 3.5):
            with self.subTest(value=repr(junk)):
                self.assertIs(adaptation_enabled(enabled_override=junk), False)

    def test_missing_model_config_flag_fails_safe_to_legacy(self):
        saved = getattr(model_config_module, "ENABLE_LLM_ADAPTATION", None)
        had_flag = hasattr(model_config_module, "ENABLE_LLM_ADAPTATION")
        if had_flag:
            del model_config_module.ENABLE_LLM_ADAPTATION
        try:
            self.assertIs(adaptation_enabled(), False)
            resolution = resolve_adaptation_routing(BUILD_MODE_LLM_ADAPTATION)
            self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
            self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION = saved


class TestAdaptationRoutingResolution(unittest.TestCase):
    """Routing resolution preserves legacy behavior until rollout."""

    def test_not_requested_resolves_to_explicit_legacy_route(self):
        resolution = resolve_adaptation_routing()
        self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
        self.assertEqual(resolution["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
        self.assertEqual(resolution["legacy_mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
        self.assertIsNone(resolution["requested_mode"])
        self.assertEqual(resolution["reason"], ROUTING_REASON_NOT_REQUESTED)

    def test_requested_while_disabled_resolves_to_legacy(self):
        resolution = resolve_adaptation_routing(
            BUILD_MODE_LLM_ADAPTATION,
            enabled_override=False,
        )
        self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
        self.assertEqual(resolution["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
        self.assertEqual(resolution["requested_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)

    def test_requested_while_enabled_resolves_to_adaptation(self):
        resolution = resolve_adaptation_routing(
            BUILD_MODE_LLM_ADAPTATION,
            enabled_override=True,
        )
        self.assertEqual(resolution["status"], ROUTING_STATUS_ENABLED)
        self.assertEqual(resolution["mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(resolution["mode"], ADAPTATION_MODE_LLM)
        self.assertEqual(resolution["reason"], ROUTING_REASON_REQUESTED_AND_ENABLED)

    def test_invalid_request_mode_resolves_to_legacy(self):
        resolution = resolve_adaptation_routing(
            "not_a_real_mode",
            enabled_override=True,
        )
        self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
        self.assertEqual(resolution["reason"], ROUTING_REASON_INVALID_REQUEST)

    def test_non_string_request_resolves_to_legacy(self):
        resolution = resolve_adaptation_routing({"mode": "llm_adaptation"})
        self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
        self.assertIsNone(resolution["requested_mode"])

    def test_mode_predicates(self):
        self.assertIs(is_llm_adaptation_build_mode(BUILD_MODE_LLM_ADAPTATION), True)
        self.assertIs(is_llm_adaptation_build_mode("source_enhanced_modulebuilder"), False)
        self.assertIs(
            is_llm_adaptation_build_mode(BUILD_MODE_LEGACY_ACCURATE_INGEST),
            False,
        )
        self.assertIs(is_legacy_accurate_ingest_build_mode(BUILD_MODE_LLM_ADAPTATION), False)

    def test_all_documented_legacy_modes_are_still_routable(self):
        runtime_legacy_modes = {
            "source_enhanced_modulebuilder",
            "source_blueprint_modulebuilder",
            "blueprint_seed_fallback",
            "blueprint_seed_preview",
            "blueprint_seed_support",
            "packet_workspace_v1",
            "packet_workspace_v2",
            "legacy_builder_narrative_v1",
        }
        self.assertTrue(runtime_legacy_modes.issubset(LEGACY_ACCURATE_INGEST_BUILD_MODES))
        for mode in LEGACY_ACCURATE_INGEST_BUILD_MODES:
            with self.subTest(mode=mode):
                self.assertIs(is_legacy_accurate_ingest_build_mode(mode), True)

    def test_adaptation_mode_is_never_a_legacy_mode(self):
        self.assertNotIn(BUILD_MODE_LLM_ADAPTATION, LEGACY_ACCURATE_INGEST_BUILD_MODES)


class TestPacketBuilderAdaptationRouting(unittest.TestCase):
    """Packet builder default and adaptation-route behavior is unchanged."""

    def setUp(self):
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspace = _create_workspace(
            self.scratch,
            source_hash="adaptation-routing-source-hash",
        )

    def _build_with_mocked_executor(self, adaptation_route=None):
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        real_derive = packet_builder._derive_builder_shape

        def _redirect_into_scratch(packet):
            redirected = dict(real_derive(packet))
            module_name = str(redirected.get("module_name") or "Scratch_Module")
            redirected["output_directory"] = str(
                self.scratch / "modules" / module_name
            )
            return redirected

        with patch.object(
            packet_builder, "_derive_builder_shape", side_effect=_redirect_into_scratch
        ), patch.object(packet_builder, "_execute_module_builder") as mock_executor:
            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "adaptation-routing-job",
                adaptation_route=adaptation_route,
            )
        return result, mock_executor

    def _staging_root_rel(self) -> str:
        """Project-relative staging root inside the per-test scratch."""
        return (self.scratch / "staging").relative_to(REPO_ROOT).as_posix()

    def _build_adaptation_with_mocked_executor(self, **adaptation_kwargs):
        """Run an enabled adaptation handoff with the executor seam mocked.

        The build-fidelity gate is pinned off for these tests so the enabled
        handoff is exercised deterministically to its packet-build boundary
        without any fidelity/editor cascade. Module output and the reserved
        staging target stay inside the per-test scratch.
        """
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        real_derive = packet_builder._derive_builder_shape

        def _redirect_into_scratch(packet):
            redirected = dict(real_derive(packet))
            module_name = str(redirected.get("module_name") or "Scratch_Module")
            redirected["output_directory"] = str(
                self.scratch / "modules" / module_name
            )
            return redirected

        with patch.object(
            packet_builder, "_derive_builder_shape", side_effect=_redirect_into_scratch
        ), patch.object(packet_builder, "_execute_module_builder") as mock_executor, patch(
            "utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES",
            False,
        ):
            result = run_toolkit_homebrew_packet_build(
                self.workspace,
                "adaptation-routing-job",
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                **adaptation_kwargs,
            )
        return result, mock_executor

    def _adaptation_workspace(self):
        """Reset the workspace with the fixture source hash for adaptation."""
        self.workspace = _create_workspace(
            self.scratch,
            source_hash=ADAPTATION_SOURCE_HASH,
        )
        return self.workspace

    def test_default_call_has_no_adaptation_resolution_and_uses_legacy(self):
        result, mock_executor = self._build_with_mocked_executor()
        self.assertNotIn("adaptation_route_resolution", result)
        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        self.assertIn(
            result["build_mode"],
            LEGACY_ACCURATE_INGEST_BUILD_MODES,
        )
        mock_executor.assert_called_once()

    def test_legacy_packet_builder_handoff_omits_adaptation_kwargs(self):
        """Legacy packet builds do not receive adaptation-only arguments."""
        result, mock_executor = self._build_with_mocked_executor()
        self.assertIn(result["build_mode"], LEGACY_ACCURATE_INGEST_BUILD_MODES)
        _, kwargs = mock_executor.call_args
        self.assertEqual(
            {
                key
                for key in kwargs
                if key.startswith("adaptation_")
            },
            set(),
        )

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", False)
    def test_requested_adaptation_while_disabled_uses_legacy_path(self):
        result, mock_executor = self._build_with_mocked_executor(
            adaptation_route=BUILD_MODE_LLM_ADAPTATION,
        )
        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        self.assertIn(
            result["build_mode"],
            LEGACY_ACCURATE_INGEST_BUILD_MODES,
        )
        resolution = result["adaptation_route_resolution"]
        self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
        self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)
        self.assertEqual(resolution["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
        mock_executor.assert_called_once()

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_requested_adaptation_while_enabled_without_dossier_fails_closed(self):
        result, mock_executor = self._build_with_mocked_executor(
            adaptation_route=BUILD_MODE_LLM_ADAPTATION,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "llm_adaptation_dossier_missing")
        self.assertEqual(
            result["adaptation_route_resolution"]["status"],
            ROUTING_STATUS_ENABLED,
        )
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_with_valid_dossier_proceeds_past_dead_end(self):
        """A valid enabled handoff leaves the legacy path and reaches the
        packet build with the dossier, provenance, and an isolated staging
        target preserved."""
        self._adaptation_workspace()
        dossier = _load_fixture_dossier()
        staging_root = self._staging_root_rel()
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier=dossier,
            adaptation_provenance=_fixture_provenance("task-4-2-proceed"),
            adaptation_staging_root=staging_root,
        )
        self.assertEqual(mock_executor.call_count, 1)
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertNotEqual(result.get("error"), "llm_adaptation_not_implemented")
        self.assertNotEqual(result.get("error"), "llm_adaptation_dossier_missing")
        self.assertIn(result["status"], {"success", "blocked", "failed"})
        target = result.get("staging_target") or {}
        self.assertTrue(
            str(target.get("path") or "").startswith(staging_root + "/"),
            "staging target must be project-relative under the staging root",
        )
        self.assertNotIn("modules/", str(target.get("path") or ""))

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_uses_forwarded_reserved_staging_target(self):
        """A reserved staging target forwarded by the runtime handoff is
        validated and used instead of reserving a new one."""
        self._adaptation_workspace()
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        dossier = _load_fixture_dossier()
        staging_root = self._staging_root_rel()
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        module_name = packet_builder.derive_packet_module_name(packet)
        forwarded = create_adaptation_staging_target(
            ADAPTATION_SOURCE_HASH,
            attempt_id="task-4-2-forwarded",
            attempt_number=1,
            revision_number=0,
            job_id="adaptation-routing-job",
            source_path="uploads/fixture.md",
            module_slug=module_name,
            staging_root=staging_root,
        )
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier=dossier,
            adaptation_provenance=_fixture_provenance("task-4-2-forwarded"),
            adaptation_staging_root=staging_root,
            adaptation_staging_target=forwarded,
        )
        self.assertEqual(mock_executor.call_count, 1)
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        target = result.get("staging_target") or {}
        self.assertEqual(target.get("path"), forwarded["path"])
        self.assertIn(
            target.get("completion_state"),
            ("completed", "failed"),
            "forwarded staging target must reach a terminal state",
        )

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_without_staging_handoff_reserves_isolated_target(self):
        """A missing staging handoff still reserves a fresh isolated target
        under the project-relative staging root, never under modules."""
        self._adaptation_workspace()
        dossier = _load_fixture_dossier()
        staging_root = self._staging_root_rel()
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier=dossier,
            adaptation_provenance=_fixture_provenance("task-4-2-auto"),
            adaptation_staging_root=staging_root,
        )
        self.assertEqual(mock_executor.call_count, 1)
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        target = result.get("staging_target") or {}
        self.assertTrue(
            str(target.get("path") or "").startswith(staging_root + "/"),
            "staging target must be project-relative under the staging root",
        )
        self.assertNotIn("modules/", str(target.get("path") or ""))

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_with_malformed_dossier_fails_closed(self):
        """A malformed dossier fails closed before staging or the executor."""
        self._adaptation_workspace()
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier={"status": "ready", "adapted_title": "not real"},
            adaptation_provenance=_fixture_provenance("task-4-2-malformed"),
            adaptation_staging_root=self._staging_root_rel(),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "builder_input")
        self.assertTrue(
            str(result.get("error") or "").startswith("llm_adaptation_dossier_invalid:"),
            "malformed dossier must fail closed with a bounded dossier diagnostic",
        )
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_with_invalid_provenance_fails_closed(self):
        """A contradictory provenance payload fails closed before staging."""
        self._adaptation_workspace()
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier=_load_fixture_dossier(),
            adaptation_provenance="not-a-mapping",
            adaptation_staging_root=self._staging_root_rel(),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "builder_input")
        self.assertEqual(result["error"], "llm_adaptation_provenance_invalid")
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION", True)
    def test_enabled_with_unsafe_staging_handoff_fails_closed(self):
        """An unsafe staging handoff fails closed before the executor."""
        self._adaptation_workspace()
        dossier = _load_fixture_dossier()
        unsafe_target = {
            "contract_version": "toolkit_adaptation_staging.v1",
            "target_kind": "staging",
            "stage_id": "task-4-2-unsafe:revision_000",
            "attempt_id": "task-4-2-unsafe",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": ADAPTATION_SOURCE_HASH,
            "source_path": "uploads/fixture.md",
            "module_slug": "Scratch_Module",
            "staging_root": "tmp/adaptation-staging",
            "path": "modules/Scratch_Module",
            "output_directory": "modules/Scratch_Module",
            "completion_state": "reserved",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "metadata_path": "modules/Scratch_Module/staging_metadata.json",
        }
        result, mock_executor = self._build_adaptation_with_mocked_executor(
            adaptation_dossier=dossier,
            adaptation_provenance=_fixture_provenance("task-4-2-unsafe"),
            adaptation_staging_root=self._staging_root_rel(),
            adaptation_staging_target=unsafe_target,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "staging")
        mock_executor.assert_not_called()


class TestAdaptationConfigFileHygiene(unittest.TestCase):
    """Changed files follow SPDX and ASCII-only rules."""

    def test_changed_files_are_ascii_only(self):
        for rel in (
            "utils/toolkit_adaptation_config.py",
            "web/extensions/toolkit_homebrew_packet_builder.py",
            "model_config.py",
            "config_template.py",
            "scripts/test_toolkit_adaptation_config.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            non_ascii = [ch for ch in text if ord(ch) >= 128]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {rel}")

    def test_changed_python_files_have_spdx_header(self):
        # Config files (model_config.py, config_template.py) use their own
        # established comment conventions and are not header-bearing modules.
        for rel in (
            "utils/toolkit_adaptation_config.py",
            "web/extensions/toolkit_homebrew_packet_builder.py",
            "scripts/test_toolkit_adaptation_config.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("SPDX-FileCopyrightText", text)
            self.assertIn("SPDX-License-Identifier", text)

    def test_packet_builder_has_no_not_implemented_dead_end(self):
        """The enabled-path not-implemented dead end (task 4.2) is removed."""
        text = (REPO_ROOT / "web" / "extensions" / "toolkit_homebrew_packet_builder.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("llm_adaptation_not_implemented", text)
        self.assertIn("llm_adaptation_dossier_missing", text)

    def test_no_os_temp_or_absolute_scratch_paths(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        # Scan only the code/docstring before this test's own token list so
        # the assertion is not self-referential.
        scan = own_source.split("def test_no_os_temp_or_absolute_scratch_paths", 1)[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)

    def test_scratch_is_project_relative(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn('"tmp"', own_source)
        self.assertIn("toolkit_adaptation_config", own_source)
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))


if __name__ == "__main__":
    unittest.main()
