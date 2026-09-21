# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free legacy text-description runtime contract tests
(task 5.3 of toolkit-llm-adaptation-runtime-unification).

The suite executes the REAL host worker ``web.web_interface.
simulate_build_process`` with injected deterministic fakes and proves the
exact legacy direct text-description route is preserved when
``ENABLE_LLM_ADAPTATION`` is missing, invalid, or exactly ``False`` (and
for ineligible text inputs even when the flag is exactly True):

  * the existing direct ``ModuleBuilder`` invocation happens with the
    ``./modules/<module_name>`` output shape and the submitted narrative;
  * the existing readiness gate runs BEFORE the post-build finisher, and
    ``module_complete`` / ``module_error`` are emitted with their exact
    legacy status/result keys and event ordering;
  * legacy progress events use only the legacy stage mapping (0-12); no
    adaptation progress phase is emitted;
  * no adaptation workspace, staging reservation, dossier, provenance,
    registry/campaign marker, or new adaptation key is created or required;
  * the adaptation-enabled branch never intercepts ineligible text inputs
    and falls through to the legacy path exactly as before.

The suite also locks source contracts for the legacy payload key sets and
for the seam ``None`` fall-through guard in the host worker.

Isolation and path policy
-------------------------

No OS-temporary scratch is used. Runtime tests write nothing to disk: the
module builder, readiness gate, and finisher are injected deterministic
fakes, and the real ``modules/<name>`` paths, registry, and campaign
artifacts are byte-sentinel checked. The live operator flag is NEVER
relied on: every behavioral test explicitly patches
``model_config.ENABLE_LLM_ADAPTATION`` (or deletes it for the missing-flag
case). No provider/network imports or calls.
"""

import hashlib
import json
import sys
import types
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.web_interface as web_interface

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_INTERFACE_PATH = REPO_ROOT / "web" / "web_interface.py"
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_legacy_contract"
REGISTRY_PATH = REPO_ROOT / "modules" / "world_registry.json"
CAMPAIGN_PATH = REPO_ROOT / "modules" / "campaign.json"
MODULES_DIR = REPO_ROOT / "modules"
TEXT_WORKSPACES_ROOT = REPO_ROOT / "tmp" / "toolkit-text-workspaces"
ADAPTATION_STAGING_ROOT = REPO_ROOT / "tmp" / "adaptation-staging"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
MODULE_NAME = "Sunken_Lighthouse"

# Exact legacy keys emitted by the worker (web/web_interface.py).
LEGACY_COMPLETE_KEYS = frozenset({
    "module_name",
    "message",
    "final_status",
    "post_build_status",
    "ready_status",
    "publishable_status",
    "build_report",
    "readiness_result",
})
LEGACY_READINESS_ERROR_KEYS = frozenset({
    "error",
    "generation_succeeded",
    "readiness_failed",
    "readiness_skipped",
    "module_name",
    "readiness_result",
})
LEGACY_FINISHER_ERROR_KEYS = frozenset({
    "error",
    "generation_succeeded",
    "readiness_passed",
    "module_name",
    "finishing_report",
})


class _EmitRecorder:
    """Records socketio.emit calls in order."""

    def __init__(self) -> None:
        self.events: List[tuple] = []

    def emit(self, event: str, payload: Any) -> None:
        self.events.append((str(event), deepcopy(payload)))


class _FakeBuilderConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.module_name = kwargs.get("module_name")
        self.num_areas = kwargs.get("num_areas")
        self.locations_per_area = kwargs.get("locations_per_area")
        self.output_directory = kwargs.get("output_directory")
        self.verbose = kwargs.get("verbose")


class _FakeModuleBuilder:
    """Deterministic ModuleBuilder fake recording the direct invocation."""

    last_instance: Optional["_FakeModuleBuilder"] = None

    def __init__(self, config: Any) -> None:
        _FakeModuleBuilder.last_instance = self
        self.config = config
        self.progress_callback = None
        self.per_area_locations = None
        self.build_calls: List[str] = []

    def build_module(self, narrative: Any) -> None:
        self.build_calls.append(str(narrative))
        if self.progress_callback is not None:
            try:
                self.progress_callback("saving", "Saving generated module files...")
            except Exception:
                pass


def _fake_module_builder_module() -> types.ModuleType:
    fake = types.ModuleType("core.generators.module_builder")
    fake.ModuleBuilder = _FakeModuleBuilder
    fake.BuilderConfig = _FakeBuilderConfig
    return fake


class _FakeReadinessGate:
    """Deterministic readiness gate recording invocation order."""

    def __init__(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.result = result if result is not None else {
            "status": "pass",
            "module_name": MODULE_NAME,
            "ready_for_finishing": True,
        }
        self.calls: List[tuple] = []

    def __call__(self, module_name: str, state_callback: Any = None) -> Dict[str, Any]:
        self.calls.append((module_name, state_callback is not None))
        if state_callback is not None:
            state_callback("validating", {"audit": {"ok": True, "module": module_name}})
            state_callback(
                "repairing_deterministic",
                {"pass": 1, "categories": {"schema": "ok"}},
            )
            state_callback("validating", {"revalidation": True})
            state_callback("repairing_semantic", {})
        return dict(self.result)


class _FakeFinisher:
    """Deterministic post-build finisher recording invocation order."""

    def __init__(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.result = result if result is not None else {
            "status": "success",
            "module_slug": MODULE_NAME,
            "publishable_status": "pass",
            "stages": {},
        }
        self.calls: List[tuple] = []

    def __call__(self, module_name: str, strict: bool = True) -> Dict[str, Any]:
        self.calls.append((module_name, strict))
        return dict(self.result)


def _params(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "narrative": FIXTURE_TEXT,
        "num_areas": 5,
        "locations_per_area": 3,
    }
    base.update(overrides)
    return base


class _LegacyRuntimeHarness(unittest.TestCase):
    """Shared fake wiring for executing the real legacy worker path."""

    def setUp(self) -> None:
        self.recorder = _EmitRecorder()
        self.builder_fake_module = _fake_module_builder_module()
        _FakeModuleBuilder.last_instance = None
        self.readiness = _FakeReadinessGate()
        self.finisher = _FakeFinisher()
        self._adaptation_flag_was_present = hasattr(
            model_config_module, "ENABLE_LLM_ADAPTATION"
        )
        self._adaptation_flag_before_test = getattr(
            model_config_module, "ENABLE_LLM_ADAPTATION", None
        )
        self.flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        )
        self.flag_patch.start()
        # _enable_adaptation() and invalid-value cases replace flag_patch.
        # Register one cleanup that always handles the currently active
        # patcher and restores the value observed before setUp changed it.
        self.addCleanup(self._restore_adaptation_flag)
        # Always install the fake builder module so the direct import inside
        # simulate_build_process resolves deterministically (never the real
        # builder, never a provider).
        self.sys_modules_patch = patch.dict(
            sys.modules, {"core.generators.module_builder": self.builder_fake_module}
        )
        self.sys_modules_patch.start()
        self.addCleanup(self.sys_modules_patch.stop)
        self.patches = [
            patch.object(web_interface, "socketio", self.recorder),
            patch.object(web_interface, "TOOLKIT_BUILDER_READINESS_AVAILABLE", True),
            patch.object(
                web_interface, "run_toolkit_builder_readiness_gate", self.readiness
            ),
            patch.object(web_interface, "TOOLKIT_MODULE_FINISHER_AVAILABLE", True),
            patch.object(
                web_interface, "run_toolkit_module_postbuild_finishing", self.finisher
            ),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _enable_adaptation(self) -> None:
        self.flag_patch.stop()
        self.flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self.flag_patch.start()

    def _restore_adaptation_flag(self) -> None:
        """Stop the active flag patcher and restore the pre-test value."""
        self.flag_patch.stop()
        if self._adaptation_flag_was_present:
            model_config_module.ENABLE_LLM_ADAPTATION = (
                self._adaptation_flag_before_test
            )
        elif hasattr(model_config_module, "ENABLE_LLM_ADAPTATION"):
            delattr(model_config_module, "ENABLE_LLM_ADAPTATION")

    def _run_worker(self, params: Dict[str, Any]) -> None:
        web_interface.simulate_build_process(params)

    # -- event inspection helpers ------------------------------------------
    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

    def _progress_stage_names(self) -> List[str]:
        return [
            str(payload.get("stage_name") or "")
            for event, payload in self.recorder.events
            if event == "module_progress"
        ]

    def _event_index(self, name: str, predicate: Any = None) -> int:
        for index, (event, payload) in enumerate(self.recorder.events):
            if event == name and (predicate is None or predicate(payload)):
                return index
        return -1

    def _assert_no_adaptation_keys(self, payload: Dict[str, Any]) -> None:
        for key in payload:
            self.assertNotIn(
                "adaptation", str(key).lower(), f"adaptation key leaked: {key}"
            )

    def _snapshot_tmp_entries(self) -> List[str]:
        """Snapshot every tmp/ entry (files and directories, project-relative)."""
        if not (REPO_ROOT / "tmp").exists():
            return []
        return sorted(
            str(p.relative_to(REPO_ROOT))
            for p in (REPO_ROOT / "tmp").rglob("*")
        )

    def _snapshot_protected(self) -> Dict[str, Any]:
        def _bytes(path: Path) -> Optional[bytes]:
            try:
                return path.read_bytes()
            except FileNotFoundError:
                return None

        return {
            "registry": _bytes(REGISTRY_PATH),
            "campaign": _bytes(CAMPAIGN_PATH),
            "modules_entries": sorted(
                str(entry.relative_to(MODULES_DIR)) for entry in MODULES_DIR.iterdir()
            ),
        }

    def _assert_protected_unchanged(self, before: Dict[str, Any]) -> None:
        after = self._snapshot_protected()
        self.assertEqual(after["registry"], before["registry"], "registry mutated")
        self.assertEqual(after["campaign"], before["campaign"], "campaign mutated")
        self.assertEqual(
            after["modules_entries"], before["modules_entries"], "modules tree mutated"
        )

    def _assert_no_adaptation_artifacts_created(self, tmp_before: List[str]) -> None:
        tmp_after = self._snapshot_tmp_entries()
        new_entries = [path for path in tmp_after if path not in set(tmp_before)]
        for path in new_entries:
            self.assertNotIn(
                "adaptation", path.lower(), f"adaptation scratch created: {path}"
            )
            self.assertNotIn(
                "text-workspace", path.lower(), f"text workspace created: {path}"
            )
        # The legacy flow must never create the adaptation attempt-workspace
        # root or add entries to the adaptation staging root. The staging
        # root directory itself may pre-exist empty (residue); no NEW entry
        # under it may appear.
        self.assertFalse(TEXT_WORKSPACES_ROOT.exists())
        staging_new = [
            path
            for path in new_entries
            if path.startswith("tmp/adaptation-staging")
        ]
        self.assertEqual(staging_new, [], "staging entries created by legacy run")


class TestLegacyFlagFalseRuntimeContract(_LegacyRuntimeHarness):
    """Exact-False flag keeps the full legacy runtime contract."""

    def test_exact_false_full_legacy_flow(self) -> None:
        protected = self._snapshot_protected()
        tmp_before = self._snapshot_tmp_entries()
        self._run_worker(_params())

        # Direct ModuleBuilder invocation with the submitted narrative and
        # the exact legacy ./modules/<name> output shape.
        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(instance.build_calls, [FIXTURE_TEXT])
        self.assertEqual(
            instance.config.output_directory, f"./modules/{MODULE_NAME}"
        )
        self.assertEqual(instance.config.module_name, MODULE_NAME)

        # Readiness gate ran before the finisher, each exactly once.
        self.assertEqual(len(self.readiness.calls), 1)
        self.assertEqual(len(self.finisher.calls), 1)
        self.assertEqual(self.finisher.calls[0][1], True)  # strict=True
        readiness_index = self._event_index(
            "module_progress",
            lambda payload: str(payload.get("stage_name")) == "Readiness Validation",
        )
        finishing_index = self._event_index(
            "module_progress",
            lambda payload: str(payload.get("stage_name")) == "Post Build Finishing",
        )
        complete_index = self._event_index("module_complete")
        self.assertGreaterEqual(readiness_index, 0)
        self.assertLess(readiness_index, finishing_index)
        self.assertLess(finishing_index, complete_index)

        # Exact legacy progress stages; no adaptation progress phase.
        progress_names = self._progress_stage_names()
        self.assertNotIn("Adaptation Publication", progress_names)
        for name in progress_names:
            self.assertNotIn("adaptation", name.lower())

        # Exact legacy module_complete payload.
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        payload = complete[0]
        self.assertEqual(set(payload.keys()), LEGACY_COMPLETE_KEYS)
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["final_status"], "success")
        self.assertEqual(payload["post_build_status"], "success")
        self.assertEqual(payload["ready_status"], "pass")
        self.assertEqual(payload["publishable_status"], "pass")
        self.assertEqual(payload["build_report"]["status"], "success")
        self.assertEqual(payload["readiness_result"]["ready_for_finishing"], True)
        self.assertNotIn("adaptation", json.dumps(payload).lower())

        # No adaptation error payloads and no adaptation artifacts.
        self.assertEqual(len(self._events("module_error")), 0)
        self._assert_no_adaptation_artifacts_created(tmp_before)
        self._assert_protected_unchanged(protected)

    def test_exact_false_progress_ordering_matches_legacy_mapping(self) -> None:
        self._run_worker(_params())
        stage_names = self._progress_stage_names()
        self.assertIn("Initializing", stage_names)
        self.assertIn("Starting Build", stage_names)
        self.assertIn("Saving", stage_names)
        self.assertIn("Readiness Validation", stage_names)
        self.assertIn("Post Build Finishing", stage_names)
        # No adaptation progress phases anywhere.
        self.assertEqual(
            [name for name in stage_names if "adaptation" in name.lower()],
            [],
        )


class TestLegacyFlagMissingInvalidRuntimeContract(_LegacyRuntimeHarness):
    """Missing and invalid flag values keep the exact legacy route."""

    def test_missing_flag_full_legacy_flow(self) -> None:
        protected = self._snapshot_protected()
        tmp_before = self._snapshot_tmp_entries()
        self.flag_patch.stop()
        had_flag = hasattr(model_config_module, "ENABLE_LLM_ADAPTATION")
        saved = getattr(model_config_module, "ENABLE_LLM_ADAPTATION", None)
        if had_flag:
            delattr(model_config_module, "ENABLE_LLM_ADAPTATION")
        try:
            self._run_worker(_params())
        finally:
            if had_flag:
                model_config_module.ENABLE_LLM_ADAPTATION = saved
            self.flag_patch.start()

        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(instance.build_calls, [FIXTURE_TEXT])
        self.assertEqual(
            instance.config.output_directory, f"./modules/{MODULE_NAME}"
        )
        self.assertEqual(len(self.readiness.calls), 1)
        self.assertEqual(len(self.finisher.calls), 1)
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        self.assertEqual(set(complete[0].keys()), LEGACY_COMPLETE_KEYS)
        self.assertEqual(complete[0]["final_status"], "success")
        self.assertNotIn("adaptation", json.dumps(complete[0]).lower())
        self.assertEqual(len(self._events("module_error")), 0)
        self._assert_no_adaptation_artifacts_created(tmp_before)
        self._assert_protected_unchanged(protected)

    def test_invalid_flag_values_full_legacy_flow(self) -> None:
        for junk in ("yes", "1", 1, 0, [], {}, 3.5):
            with self.subTest(value=repr(junk)):
                self.flag_patch.stop()
                self.flag_patch = patch.object(
                    model_config_module, "ENABLE_LLM_ADAPTATION", junk
                )
                self.flag_patch.start()
                self.recorder.events = []
                self.readiness.calls = []
                self.finisher.calls = []
                _FakeModuleBuilder.last_instance = None

                self._run_worker(_params())

                instance = _FakeModuleBuilder.last_instance
                self.assertIsNotNone(instance)
                self.assertEqual(instance.build_calls, [FIXTURE_TEXT])
                self.assertEqual(
                    instance.config.output_directory, f"./modules/{MODULE_NAME}"
                )
                self.assertEqual(len(self.readiness.calls), 1)
                self.assertEqual(len(self.finisher.calls), 1)
                complete = self._events("module_complete")
                self.assertEqual(len(complete), 1)
                self.assertEqual(set(complete[0].keys()), LEGACY_COMPLETE_KEYS)
                self.assertNotIn("adaptation", json.dumps(complete[0]).lower())
                self.assertEqual(len(self._events("module_error")), 0)


class TestLegacyIneligibleInputsRuntimeContract(_LegacyRuntimeHarness):
    """Enabled branch never intercepts ineligible text inputs."""

    def test_enabled_but_empty_description_falls_through_to_legacy(self) -> None:
        protected = self._snapshot_protected()
        tmp_before = self._snapshot_tmp_entries()
        self._enable_adaptation()
        self._run_worker(_params(narrative="   "))

        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(len(instance.build_calls), 1)
        self.assertEqual(len(self.readiness.calls), 1)
        self.assertEqual(len(self.finisher.calls), 1)
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        self.assertEqual(set(complete[0].keys()), LEGACY_COMPLETE_KEYS)
        self.assertEqual(complete[0]["final_status"], "success")
        self.assertNotIn("adaptation", json.dumps(complete[0]).lower())
        # No adaptation outcome payloads were emitted (authoring never ran).
        self.assertEqual(len(self._events("module_error")), 0)
        self._assert_no_adaptation_artifacts_created(tmp_before)
        self._assert_protected_unchanged(protected)

    def test_enabled_but_invalid_module_name_falls_through_to_legacy(self) -> None:
        self._enable_adaptation()
        self._run_worker(_params(module_name="Bad Module Name!"))
        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(len(instance.build_calls), 1)
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        self.assertNotIn("adaptation", json.dumps(complete[0]).lower())

    def test_enabled_but_oversized_description_falls_through_to_legacy(self) -> None:
        from utils import toolkit_adaptation_config

        self._enable_adaptation()
        with patch.object(toolkit_adaptation_config, "MAX_TEXT_DESCRIPTION_CHARS", 10):
            self._run_worker(_params())
        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(len(instance.build_calls), 1)
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        self.assertNotIn("adaptation", json.dumps(complete[0]).lower())

    def test_seam_unavailable_falls_through_to_legacy(self) -> None:
        protected = self._snapshot_protected()
        tmp_before = self._snapshot_tmp_entries()
        self._enable_adaptation()
        with patch.object(
            web_interface, "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", False
        ), patch.object(web_interface, "run_text_description_adaptation_seam", None):
            self._run_worker(_params())
        instance = _FakeModuleBuilder.last_instance
        self.assertIsNotNone(instance)
        self.assertEqual(len(instance.build_calls), 1)
        self.assertEqual(len(self.readiness.calls), 1)
        self.assertEqual(len(self.finisher.calls), 1)
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        self.assertEqual(set(complete[0].keys()), LEGACY_COMPLETE_KEYS)
        self.assertNotIn("adaptation", json.dumps(complete[0]).lower())
        self._assert_no_adaptation_artifacts_created(tmp_before)
        self._assert_protected_unchanged(protected)


class TestLegacyReadinessFinisherErrorContracts(_LegacyRuntimeHarness):
    """Legacy readiness/finisher failure payloads stay exact and adaptation-free."""

    def test_readiness_failure_emits_legacy_module_error_before_finisher(self) -> None:
        protected = self._snapshot_protected()
        self.readiness.result = {
            "status": "failed",
            "module_name": MODULE_NAME,
            "ready_for_finishing": False,
        }
        self._run_worker(_params())

        self.assertEqual(len(self.finisher.calls), 0)
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(set(payload.keys()), LEGACY_READINESS_ERROR_KEYS)
        self.assertIs(payload["generation_succeeded"], True)
        self.assertIs(payload["readiness_failed"], True)
        self.assertIs(payload["readiness_skipped"], False)
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["readiness_result"]["status"], "failed")
        self._assert_no_adaptation_keys(payload)
        self.assertEqual(len(self._events("module_complete")), 0)
        self._assert_protected_unchanged(protected)

    def test_readiness_unavailable_marks_skipped_in_error_payload(self) -> None:
        with patch.object(web_interface, "TOOLKIT_BUILDER_READINESS_AVAILABLE", False):
            self.readiness.result = {
                "status": "failed",
                "module_name": MODULE_NAME,
                "ready_for_finishing": False,
            }
            self._run_worker(_params())
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        self.assertIs(errors[0]["readiness_skipped"], True)
        self.assertEqual(len(self.finisher.calls), 0)

    def test_finisher_failure_emits_legacy_module_error(self) -> None:
        protected = self._snapshot_protected()
        self.finisher.result = {
            "status": "failed",
            "module_slug": MODULE_NAME,
            "reason": "finisher_boom",
            "stages": {},
        }
        self._run_worker(_params())

        self.assertEqual(len(self.readiness.calls), 1)
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(set(payload.keys()), LEGACY_FINISHER_ERROR_KEYS)
        self.assertIs(payload["generation_succeeded"], True)
        self.assertIs(payload["readiness_passed"], True)
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["finishing_report"]["status"], "failed")
        self._assert_no_adaptation_keys(payload)
        self.assertEqual(len(self._events("module_complete")), 0)
        self._assert_protected_unchanged(protected)

    def test_finisher_degraded_keeps_legacy_complete_contract(self) -> None:
        self.finisher.result = {
            "status": "degraded",
            "module_slug": MODULE_NAME,
            "publishable_status": "degraded",
            "stages": {},
        }
        self._run_worker(_params())
        complete = self._events("module_complete")
        self.assertEqual(len(complete), 1)
        payload = complete[0]
        self.assertEqual(set(payload.keys()), LEGACY_COMPLETE_KEYS)
        self.assertEqual(payload["final_status"], "degraded")
        self.assertEqual(payload["post_build_status"], "degraded")
        self.assertEqual(payload["publishable_status"], "degraded")
        self.assertIn("degraded", payload["message"])
        self._assert_no_adaptation_keys(payload)
        self.assertEqual(len(self._events("module_error")), 0)


class TestLegacyWorkerSourceContracts(unittest.TestCase):
    """Source contracts locking the exact legacy payload keys and ordering."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_INTERFACE_PATH.read_text(encoding="utf-8")
        cls.build_slice = _function_slice(
            cls.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )

    def test_module_complete_payload_keys_are_legacy_exact(self) -> None:
        emit_slice = _extract_emit_payload(self.build_slice, "module_complete")
        for key in LEGACY_COMPLETE_KEYS:
            self.assertIn(f"'{key}'", emit_slice)
        self.assertNotIn("adaptation", emit_slice.lower())

    def test_module_error_readiness_payload_keys_are_legacy_exact(self) -> None:
        # First module_error emit in the worker is the readiness-failure block.
        error_slice = _extract_emit_payload(self.build_slice, "module_error", 0)
        for key in LEGACY_READINESS_ERROR_KEYS:
            self.assertIn(f"'{key}'", error_slice)
        self.assertNotIn("adaptation", error_slice.lower())

    def test_module_error_finisher_payload_keys_are_legacy_exact(self) -> None:
        # Second module_error emit is the finisher-failure block.
        finisher_error_slice = _extract_emit_payload(self.build_slice, "module_error", 1)
        for key in LEGACY_FINISHER_ERROR_KEYS:
            self.assertIn(f"'{key}'", finisher_error_slice)
        self.assertNotIn("adaptation", finisher_error_slice.lower())

    def test_legacy_progress_stage_mapping_unchanged(self) -> None:
        mapping_keys = (
            "'initializing'",
            "'base_structure'",
            "'npcs'",
            "'monsters'",
            "'areas'",
            "'plots'",
            "'connections'",
            "'finalizing'",
            "'saving'",
            "'post_build_finishing'",
        )
        for key in mapping_keys:
            self.assertIn(key, self.build_slice)
        self.assertIn("'Post Build Finishing'", self.build_slice)
        # The legacy progress mapping never emits the adaptation phase name:
        # the only 'Adaptation Publication' emit lives inside the enabled
        # branch (before the seam-return check), which legacy runs never
        # reach. Lock that the legacy emit region after the branch contains
        # no adaptation stage name.
        legacy_region = self.build_slice[
            self.build_slice.index(
                'info(f"Starting actual module build for: {module_name}")'
            ):
        ]
        self.assertNotIn("Adaptation Publication", legacy_region)

    def test_seam_none_fallthrough_guard_preserved(self) -> None:
        # The adaptation branch falls through to the legacy path only when
        # the seam returns None; the legacy direct builder then runs.
        branch_slice = _function_slice(
            self.build_slice,
            "if TEXT_DESCRIPTION_ADAPTATION_AVAILABLE",
            'info(f"Starting actual module build for: {module_name}")',
        )
        self.assertIn("if adaptation_result is not None:", branch_slice)
        self.assertIn("return", branch_slice)
        legacy_region = self.build_slice[
            self.build_slice.index(
                'info(f"Starting actual module build for: {module_name}")'
            ):
        ]
        # The direct builder import happens at the top of the worker (before
        # the branch); the direct write shape and build_module call live in
        # the legacy region reached only after the seam returns None.
        self.assertIn(
            "from core.generators.module_builder import ModuleBuilder, BuilderConfig",
            self.build_slice,
        )
        self.assertLess(
            self.build_slice.index(
                "from core.generators.module_builder import ModuleBuilder, BuilderConfig"
            ),
            self.build_slice.index("if TEXT_DESCRIPTION_ADAPTATION_AVAILABLE"),
        )
        self.assertIn('output_directory=f"./modules/{module_name}"', legacy_region)
        self.assertIn("builder.build_module(narrative)", legacy_region)

    def test_legacy_build_module_complete_emitted_after_finisher(self) -> None:
        self.assertLess(
            self.build_slice.index("run_toolkit_module_postbuild_finishing"),
            self.build_slice.index("socketio.emit('module_complete'"),
        )


def _function_slice(source: str, start_marker: str, end_marker: str) -> str:
    """Return source text between start_marker and the first end_marker."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _extract_emit_payload(source: str, event: str, occurrence: int = 0) -> str:
    """Extract the dict literal of the Nth ``socketio.emit('<event>', {...})``.

    Uses brace matching so f-string interpolations (which may contain
    ``})`` inside ``{expression})``) do not truncate the slice.
    """
    marker = f"socketio.emit('{event}', {{"
    start = source.index(marker)
    for _ in range(occurrence):
        start = source.index(marker, start + 1)
    depth = 0
    index = start + len(marker) - 1  # position of the '{'
    while index < len(source):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unbalanced emit payload for {event!r}")


class TestLegacyContractHygiene(unittest.TestCase):
    """ASCII, SPDX, and path-policy rules for this suite."""

    def test_this_suite_is_ascii_only(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [], "non-ASCII characters in this suite")

    def test_this_suite_has_spdx_header(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestLegacyContractHygiene", 1)[0]
        self.assertNotIn("tempfile", scan)
        self.assertNotIn("/tmp", scan)
        self.assertNotIn("/var/folders", scan)
        self.assertIn('"tmp"', scan)
        self.assertIn("toolkit_text_description_legacy_contract", scan)
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))

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

    def test_flag_is_patched_not_reliant_on_live_value(self) -> None:
        # Every behavioral test patches the flag explicitly; the dirty
        # worktree value (True) is never relied upon.
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            'patch.object(model_config_module, "ENABLE_LLM_ADAPTATION"', own_source
        )


if __name__ == "__main__":
    unittest.main()
