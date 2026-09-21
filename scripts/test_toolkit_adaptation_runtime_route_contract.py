# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free runtime route contract tests for the toolkit LLM adaptation
lane (task 1.1 of toolkit-llm-adaptation-runtime-unification).

This suite inventories the two existing Toolkit build lifecycles, locks their
current write/finish boundaries, and locks the feature-flag route contract:

  * ``ENABLE_LLM_ADAPTATION`` exactly False, missing, or invalid preserves
    the legacy accurate-ingest (upload) and direct-builder (text description)
    lifecycles.
  * Exactly True selects the background adaptation route for eligible upload
    and text-description inputs without requiring a GUI mode selector.

Lifecycle inventory
-------------------

Upload job lifecycle (web/routes/toolkit_homebrew_routes.py):

  * Accepted/review boundary: an upload runs the shared ingest pipeline and
    normalization, then pauses at ``awaiting_review`` only when a fidelity
    decision is required. Build may start only from
    ``approved_for_build`` / ``awaiting_overwrite_confirmation`` /
    ``ready_for_finishing`` (start_toolkit_homebrew_job_build).
  * Write boundary: the background worker ``_run_homebrew_build_job`` calls
    ``_run_homebrew_packet_build``, which delegates to
    ``run_toolkit_homebrew_packet_build`` (web/extensions/
    toolkit_homebrew_packet_builder.py). The packet builder owns module
    writes; it returns ``success`` / ``blocked`` /
    ``final_reconciliation_required``.
  * Finish boundary: on packet ``success`` the job runs
    ``_run_homebrew_readiness_gate`` (``ready_for_finishing``) and then
    ``_run_homebrew_finisher``; terminal states are ``completed``,
    ``not_publishable``, or ``finishing_failed``.

Text-description Socket.IO lifecycle (web/web_interface.py):

  * Entry boundary: ``@socketio.on('start_build')`` ->
    ``handle_start_build`` spawns a daemon thread running
    ``simulate_build_process``.
  * Write boundary: ``simulate_build_process`` builds a
    ``ModuleBuilder(BuilderConfig(output_directory=f"./modules/{name}"))``
    and calls ``builder.build_module(narrative)`` directly (legacy direct
    write; no staging).
  * Finish boundary: after the direct build, the worker runs
    ``run_toolkit_builder_readiness_gate`` and then
    ``run_toolkit_module_postbuild_finishing`` before emitting
    ``module_complete`` / ``module_error``.

Route contract
--------------

The route decision is driven only by the operator feature flag. No GUI
field selects adaptation: the existing upload controls and the existing
text-description form remain the only operator surfaces. A selected
adaptation attempt that fails must fail closed and must not silently fall
through to legacy generation (specs/toolkit-adaptation-runtime-routing).

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch
root ``tmp/toolkit_adaptation_route_contract/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The two
functional packet-builder tests inject a redirect seam on
``_derive_builder_shape`` so the packet builder's module output directory
resolves inside the scratch root; the real production ``modules/<name>``
paths, runtime registry, and campaign artifacts are never touched. The
module builder executor is mocked, so no provider or network call occurs.

All tests in this suite are provider-free: they read source text, exercise
the deterministic resolver (utils/toolkit_adaptation_config.py), or call
the packet builder with a mocked module-builder executor. The live
``model_config.ENABLE_LLM_ADAPTATION`` operator value is never relied on;
every behavioral test passes an explicit override or patches the module
attribute.
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

from utils import toolkit_adaptation_config as adaptation_config
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LEGACY_ACCURATE_INGEST,
    BUILD_MODE_LLM_ADAPTATION,
    ROUTING_REASON_DISABLED,
    ROUTING_REASON_INVALID_REQUEST,
    ROUTING_REASON_NOT_REQUESTED,
    ROUTING_REASON_REQUESTED_AND_ENABLED,
    ROUTING_STATUS_ENABLED,
    ROUTING_STATUS_LEGACY,
    adaptation_enabled,
    resolve_adaptation_routing,
)
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM

REPO_ROOT = Path(__file__).resolve().parents[1]

# Project-local scratch root for fixtures and generated artifacts. The repo
# keeps its task scratch under tmp/ (git-ignored); each suite run gets a
# unique subdirectory that is removed in cleanup.
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_route_contract"

# Eligible input kinds used by the background adaptation route. The route
# resolver is input-kind agnostic; these are the input classes the Toolkit
# owns today (specs/toolkit-adaptation-source-input-handoff).
ELIGIBLE_UPLOAD_KINDS = ("upload_markdown", "upload_pdf")
ELIGIBLE_TEXT_KIND = "text_description"
ELIGIBLE_INPUT_KINDS = ELIGIBLE_UPLOAD_KINDS + (ELIGIBLE_TEXT_KIND,)

# Source files owned by the two host lifecycles.
UPLOAD_ROUTES_PATH = REPO_ROOT / "web" / "routes" / "toolkit_homebrew_routes.py"
WEB_INTERFACE_PATH = REPO_ROOT / "web" / "web_interface.py"
MODULE_BUILDER_TEMPLATE_PATH = REPO_ROOT / "web" / "templates" / "module_builder.html"
PACKET_BUILDER_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_homebrew_packet_builder.py"
)
ADAPTATION_CONFIG_PATH = REPO_ROOT / "utils" / "toolkit_adaptation_config.py"


def _function_slice(source: str, start_marker: str, end_marker: str) -> str:
    """Return source text between start_marker and the first end_marker."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _make_scratch_dir() -> Path:
    """Create and return a unique project-local scratch directory."""
    scratch = SCRATCH_ROOT / str(uuid.uuid4())
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _redirect_module_output(
    params_dict: Dict[str, Any],
    scratch_root: Path,
) -> Dict[str, Any]:
    """Redirect a derived builder shape's module output into scratch.

    Used as an injected seam so packet-builder functional tests never touch
    the real production ``modules/<name>`` paths. Only the output directory
    is changed; module identity and all other builder parameters are kept.
    """
    redirected = dict(params_dict)
    module_name = str(params_dict.get("module_name") or "Scratch_Module")
    redirected["output_directory"] = str(
        scratch_root / "modules" / module_name
    )
    return redirected


# Matches the v2 blueprint version used by the existing toolkit routing tests.
VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"

_V2_BLUEPRINT = {
    "blueprint_version": VALID_V2_VERSION,
    "blueprint_status": "ready",
    "module": {"title": "Route Contract Fixture", "summary": "fixture"},
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


def _create_workspace(scratch_root: Path, source_hash: str) -> Path:
    """Create a minimal approved upload workspace inside the scratch root."""
    ws = scratch_root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    files = {
        "normalized_packet.json": {
            "packet_version": "packet.v1",
            "name": "route-contract-001",
            "title": "Route Contract Fixture",
            "description": "A test adventure for runtime route contract tests",
            "source_hash": source_hash,
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        },
        "ui_review_snapshot.json": {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": "route-contract-job",
            "packet_identity": {"source_hash": source_hash},
        },
        "builder_blueprint.json": _V2_BLUEPRINT,
        "builder_blueprint_report.json": {
            "blueprint_status": "ready",
            "fidelity_status": "pass",
        },
        "builder_narrative.txt": "Test narrative for route contract build",
    }
    for filename, content in files.items():
        path = ws / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(content) if isinstance(content, dict) else content,
            encoding="utf-8",
        )
    return ws


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = _make_scratch_dir()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)


class TestUploadJobLifecycleInventory(unittest.TestCase):
    """Locks the current upload-job accepted/review/build/finish boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.source = UPLOAD_ROUTES_PATH.read_text(encoding="utf-8")

    def test_upload_build_entry_boundary_requires_approved_job(self):
        self.assertIn("def start_toolkit_homebrew_job_build(job_id: str)", self.source)
        self.assertIn("approved_for_build", self.source)
        self.assertIn("awaiting_overwrite_confirmation", self.source)
        self.assertIn("ready_for_finishing", self.source)
        self.assertIn("awaiting_review", self.source)

    def test_upload_write_boundary_is_packet_builder(self):
        build_slice = _function_slice(
            self.source,
            "def _run_homebrew_build_job(",
            "def register_toolkit_homebrew_routes(app: Flask)",
        )
        self.assertIn("_run_homebrew_packet_build(", build_slice)
        self.assertIn("run_toolkit_homebrew_packet_build", self.source)
        self.assertIn(
            "toolkit_homebrew_packet_builder",
            self.source,
        )

    def test_upload_finish_boundary_is_readiness_then_finisher(self):
        build_slice = _function_slice(
            self.source,
            "def _run_homebrew_build_job(",
            "def register_toolkit_homebrew_routes(app: Flask)",
        )
        self.assertIn("_run_homebrew_readiness_gate(", build_slice)
        self.assertIn("_run_homebrew_finisher(", build_slice)
        # The finishing_only branch invokes the finisher without readiness, so
        # compare against the LAST (normal-path) finisher invocation.
        self.assertLess(
            build_slice.index("_run_homebrew_readiness_gate("),
            build_slice.rindex("_run_homebrew_finisher("),
        )
        for terminal in ("completed", "not_publishable", "finishing_failed"):
            with self.subTest(terminal=terminal):
                self.assertIn(terminal, build_slice)

    def test_upload_build_start_payload_has_no_adaptation_selector(self):
        route_slice = _function_slice(
            self.source,
            "def start_toolkit_homebrew_job_build(job_id: str)",
            "def retry_toolkit_homebrew_from_packet(job_id: str)",
        )
        self.assertIn('payload.get("confirm_overwrite")', route_slice)
        self.assertIn('payload.get("overwrite_policy")', route_slice)
        self.assertIn('payload.get("seed_writer_mode")', route_slice)
        self.assertNotIn('payload.get("adaptation', route_slice)
        self.assertNotIn('payload.get("llm_adaptation', route_slice)


class TestTextDescriptionLifecycleInventory(unittest.TestCase):
    """Locks the current text-description Socket.IO write/finish boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.source = WEB_INTERFACE_PATH.read_text(encoding="utf-8")

    def test_text_build_socket_entry_boundary(self):
        self.assertIn("@socketio.on('start_build')", self.source)
        self.assertIn("def handle_start_build(data)", self.source)
        self.assertIn(
            "threading.Thread(target=simulate_build_process, args=(data,))",
            self.source,
        )

    def test_text_build_write_boundary_is_direct_module_builder(self):
        build_slice = _function_slice(
            self.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )
        self.assertIn(
            "from core.generators.module_builder import ModuleBuilder, BuilderConfig",
            build_slice,
        )
        self.assertIn('output_directory=f"./modules/{module_name}"', build_slice)
        self.assertIn("builder.build_module(narrative)", build_slice)

    def test_text_build_finish_boundary_is_readiness_then_finisher(self):
        build_slice = _function_slice(
            self.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )
        self.assertIn("run_toolkit_builder_readiness_gate", build_slice)
        self.assertIn("run_toolkit_module_postbuild_finishing", build_slice)
        self.assertLess(
            build_slice.index("run_toolkit_builder_readiness_gate"),
            build_slice.index("run_toolkit_module_postbuild_finishing"),
        )
        self.assertIn("socketio.emit('module_complete'", build_slice)
        self.assertIn("socketio.emit('module_error'", build_slice)

    def test_text_legacy_path_remains_intact_inside_enabled_worker(self):
        # Task 5.1 (toolkit-llm-adaptation-runtime-unification) added the
        # adaptation-enabled branch to the worker. The legacy direct-builder
        # path below the branch stays intact: ModuleBuilder import, direct
        # output directory, build_module call, readiness-before-finisher
        # ordering, and module_complete/module_error emits all remain present
        # so the flag-False/missing/invalid path keeps its exact behavior.
        build_slice = _function_slice(
            self.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )
        self.assertIn(
            "from core.generators.module_builder import ModuleBuilder, BuilderConfig",
            build_slice,
        )
        self.assertIn('output_directory=f"./modules/{module_name}"', build_slice)
        self.assertIn("builder.build_module(narrative)", build_slice)
        self.assertIn("run_toolkit_builder_readiness_gate", build_slice)
        self.assertIn("run_toolkit_module_postbuild_finishing", build_slice)
        self.assertIn("socketio.emit('module_complete'", build_slice)
        self.assertIn("socketio.emit('module_error'", build_slice)

    def test_text_enabled_branch_precedes_direct_module_builder(self):
        # The enabled branch resolves the shared adaptation seam BEFORE any
        # ModuleBuilder write and returns early, so a selected adaptation
        # attempt can never silently downgrade to direct legacy generation.
        build_slice = _function_slice(
            self.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )
        self.assertIn("run_text_description_adaptation_seam", build_slice)
        self.assertIn("_emit_text_description_adaptation_outcome", build_slice)
        self.assertIn("TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", build_slice)
        self.assertLess(
            build_slice.index("run_text_description_adaptation_seam"),
            build_slice.index("builder.build_module(narrative)"),
        )

    def test_text_adaptation_outcome_helper_never_emits_legacy_success(self):
        # The task 5.1 authoring-outcome helper only ever emits the explicit
        # adaptation module_error payloads; it must never emit the legacy
        # module_complete success event (prose may name the event, but no
        # emit call shape may target it).
        helper_slice = _function_slice(
            self.source,
            "def _emit_text_description_adaptation_outcome(",
            "def _emit_text_description_publication_outcome(",
        )
        self.assertNotIn("socketio.emit('module_complete'", helper_slice)
        self.assertIn("socketio.emit('module_error'", helper_slice)
        self.assertIn("'adaptation_route'", helper_slice)
        self.assertIn("'adaptation_job'", helper_slice)
        self.assertIn("'adaptation_outcome'", helper_slice)

    def test_text_publication_outcome_helper_emits_success_only_after_verification(self):
        # The task 5.2 terminal publication helper is the ONLY place a
        # text-description adaptation attempt may emit the legacy success
        # event name, and it does so only when the shared publication
        # transaction verified completion (outcome == 'completed'). Blocked
        # publication results keep the explicit adaptation module_error shape
        # with bounded diagnostics and never claim success.
        publication_slice = _function_slice(
            self.source,
            "def _emit_text_description_publication_outcome(",
            "def simulate_build_process(params):",
        )
        self.assertIn("socketio.emit('module_complete'", publication_slice)
        self.assertIn("outcome == 'completed'", publication_slice)
        self.assertIn("socketio.emit('module_error'", publication_slice)
        self.assertIn("'adaptation_job'", publication_slice)
        self.assertIn("'adaptation_outcome'", publication_slice)


class TestAdaptationFlagFalseMissingInvalidPreserveLegacy(
    _ProjectLocalScratchMixin, unittest.TestCase
):
    """Exact False, missing, and invalid configuration preserve legacy."""

    def test_exact_false_preserves_legacy_for_all_eligible_inputs(self):
        for kind in ELIGIBLE_INPUT_KINDS:
            with self.subTest(input_kind=kind):
                resolution = resolve_adaptation_routing(
                    BUILD_MODE_LLM_ADAPTATION,
                    enabled_override=False,
                )
                self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
                self.assertEqual(resolution["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
                self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)

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
                    resolution = resolve_adaptation_routing(BUILD_MODE_LLM_ADAPTATION)
                    self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
                    self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION = saved

    def test_invalid_flag_values_preserve_legacy_for_all_eligible_inputs(self):
        # NOTE: None is NOT invalid: it is the "read live model_config" sentinel
        # and is covered separately by the missing-flag test. Only non-boolean
        # junk values must resolve to legacy.
        for junk in ("yes", "1", 1, 0, [], {}, 3.5):
            with self.subTest(value=repr(junk)):
                self.assertIs(adaptation_enabled(enabled_override=junk), False)
                resolution = resolve_adaptation_routing(
                    BUILD_MODE_LLM_ADAPTATION,
                    enabled_override=junk,
                )
                self.assertEqual(resolution["status"], ROUTING_STATUS_LEGACY)
                self.assertEqual(resolution["reason"], ROUTING_REASON_DISABLED)

    def test_unrequested_and_invalid_requests_preserve_legacy(self):
        self.assertEqual(
            resolve_adaptation_routing(enabled_override=True)["reason"],
            ROUTING_REASON_NOT_REQUESTED,
        )
        self.assertEqual(
            resolve_adaptation_routing("not_a_real_mode", enabled_override=True)[
                "reason"
            ],
            ROUTING_REASON_INVALID_REQUEST,
        )

    def test_legacy_upload_packet_build_requires_no_adaptation_artifacts(self):
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        workspace = _create_workspace(self.scratch, "route-contract-source-hash")
        real_derive = packet_builder._derive_builder_shape

        def _redirect_into_scratch(packet):
            return _redirect_module_output(real_derive(packet), self.scratch)

        with patch.object(
            packet_builder, "_derive_builder_shape", side_effect=_redirect_into_scratch
        ), patch.object(packet_builder, "_execute_module_builder") as mock_executor:
            result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace,
                "route-contract-job",
            )
        self.assertNotIn("adaptation_route_resolution", result)
        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        self.assertIn(
            result["build_mode"],
            adaptation_config.LEGACY_ACCURATE_INGEST_BUILD_MODES,
        )
        self.assertTrue(
            str(result["output_directory"]).startswith(str(self.scratch)),
            "packet build output must stay inside the project-local scratch root",
        )
        mock_executor.assert_called_once()


class TestAdaptationFlagTrueSelectsBackgroundRoute(
    _ProjectLocalScratchMixin, unittest.TestCase
):
    """Exact True selects the background adaptation route for both inputs."""

    def test_exact_true_selects_adaptation_for_upload_inputs(self):
        for kind in ELIGIBLE_UPLOAD_KINDS:
            with self.subTest(input_kind=kind):
                resolution = resolve_adaptation_routing(
                    BUILD_MODE_LLM_ADAPTATION,
                    enabled_override=True,
                )
                self.assertEqual(resolution["status"], ROUTING_STATUS_ENABLED)
                self.assertEqual(resolution["mode"], BUILD_MODE_LLM_ADAPTATION)
                self.assertEqual(resolution["mode"], ADAPTATION_MODE_LLM)
                self.assertEqual(
                    resolution["reason"],
                    ROUTING_REASON_REQUESTED_AND_ENABLED,
                )

    def test_exact_true_selects_adaptation_for_text_description(self):
        resolution = resolve_adaptation_routing(
            BUILD_MODE_LLM_ADAPTATION,
            enabled_override=True,
        )
        self.assertEqual(resolution["status"], ROUTING_STATUS_ENABLED)
        self.assertEqual(resolution["mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(
            resolution["reason"],
            ROUTING_REASON_REQUESTED_AND_ENABLED,
        )

    def test_enabled_upload_route_selection_is_recorded_and_fails_closed(self):
        # A selected adaptation route is authoritative: without a validated
        # dossier handoff the packet build fails closed and never invokes the
        # legacy ModuleBuilder executor. Task 4.2 replaces the current
        # not-implemented failure reason with the real authoring handoff;
        # this suite locks the fail-closed envelope, not the interim reason.
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        workspace = _create_workspace(self.scratch, "route-contract-source-hash")
        real_derive = packet_builder._derive_builder_shape

        def _redirect_into_scratch(packet):
            return _redirect_module_output(real_derive(packet), self.scratch)

        with patch.object(
            packet_builder, "_derive_builder_shape", side_effect=_redirect_into_scratch
        ), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(packet_builder, "_execute_module_builder") as mock_executor:
            result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace,
                "route-contract-job",
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["adaptation_route_resolution"]["status"],
            ROUTING_STATUS_ENABLED,
        )
        mock_executor.assert_not_called()


class TestNoGuiModeSelectorRequired(unittest.TestCase):
    """The feature flag is the only route selector; no GUI mode is added."""

    @classmethod
    def setUpClass(cls):
        cls.config_source = ADAPTATION_CONFIG_PATH.read_text(encoding="utf-8")
        cls.builder_template = MODULE_BUILDER_TEMPLATE_PATH.read_text(
            encoding="utf-8"
        )

    def test_resolver_requires_no_gui_parameters(self):
        signature = self.config_source.split("def resolve_adaptation_routing(", 1)[1]
        signature = signature.split("\n)", 1)[0]
        self.assertIn("requested_mode", signature)
        self.assertIn("enabled_override", signature)
        self.assertNotIn("gui", signature.lower())

    def test_route_decision_is_flag_driven_only(self):
        self.assertIn("enabled_override", self.config_source)
        self.assertIn("model_config.ENABLE_LLM_ADAPTATION", self.config_source)
        self.assertIn("ROUTING_REASON_REQUESTED_AND_ENABLED", self.config_source)

    def test_text_builder_form_has_no_adaptation_selector(self):
        emit_slice = _function_slice(
            self.builder_template,
            "socket.emit('start_build', {",
            "});",
        )
        self.assertIn("module_name", emit_slice)
        self.assertIn("narrative", emit_slice)
        self.assertNotIn("adaptation", emit_slice)
        self.assertNotIn("llm_adaptation", emit_slice)

    def test_upload_build_controls_are_reused(self):
        # The upload build payload carries no adaptation field: the existing
        # upload, review, build, progress, and result interactions are the
        # whole operator surface.
        upload_source = UPLOAD_ROUTES_PATH.read_text(encoding="utf-8")
        route_slice = _function_slice(
            upload_source,
            "def start_toolkit_homebrew_job_build(job_id: str)",
            "def retry_toolkit_homebrew_from_packet(job_id: str)",
        )
        self.assertNotIn('data.get("adaptation', route_slice)
        self.assertNotIn("llm_adaptation", route_slice)


class TestNoProviderNetworkTripwire(unittest.TestCase):
    """Route selection and this suite never call a provider or the network."""

    FORBIDDEN_TOKENS = (
        "openai",
        "create_chat_client",
        "httpx",
        "requests.get",
        "urllib.request",
        "http.client",
        "socketio",
    )

    def test_route_selection_modules_never_use_providers(self):
        for path in (
            ADAPTATION_CONFIG_PATH,
            REPO_ROOT / "utils" / "toolkit_adaptation_dossier.py",
        ):
            text = path.read_text(encoding="utf-8")
            for token in self.FORBIDDEN_TOKENS:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, text)

    def test_this_suite_never_imports_provider_modules(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        import_lines = [
            line
            for line in own_source.splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        for token in ("openai", "httpx", "requests", "create_chat_client"):
            with self.subTest(token=token):
                self.assertNotIn(token, imports)


class TestRuntimeRouteContractHygiene(unittest.TestCase):
    """Changed test artifact follows SPDX, ASCII, and path-policy rules."""

    def test_changed_files_are_ascii_only(self):
        for path in (Path(__file__),):
            text = path.read_text(encoding="utf-8")
            non_ascii = [ch for ch in text if ord(ch) >= 128]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_changed_python_files_have_spdx_header(self):
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        # Scan only the code/docstring before this test's own token list so
        # the assertion is not self-referential.
        scan = own_source.split(
            "def test_no_os_temp_or_absolute_scratch_paths", 1
        )[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)

    def test_scratch_is_project_relative(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn('"tmp"', own_source)
        self.assertIn("toolkit_adaptation_route_contract", own_source)
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))


if __name__ == "__main__":
    unittest.main()
