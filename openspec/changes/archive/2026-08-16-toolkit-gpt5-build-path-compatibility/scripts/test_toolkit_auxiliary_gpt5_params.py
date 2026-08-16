# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free request and stage-error contracts for task 2.3 call sites."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

def _find_repo_root():
    candidate = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(candidate, "openspec")) and os.path.isfile(
            os.path.join(candidate, "config_template.py")
        ):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            raise RuntimeError("Unable to locate NeverEndingQuest repository root")
        candidate = parent


_REPO_ROOT = _find_repo_root()
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_CHANGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES_DIR = os.path.join(_CHANGE_DIR, "fixtures")
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

import build_request_fixture as bf
import utils.ai_client_factory as ai_client_factory


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [
            type(
                "Choice",
                (),
                {"message": type("Message", (), {"content": content})()},
            )()
        ]


class _RecordingCompletions:
    def __init__(self, content: str = "{}", error: Exception | None = None) -> None:
        self.calls = []
        self.content = content
        self.error = error

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.content)


class _RecordingClient:
    def __init__(self, content: str = "{}", error: Exception | None = None) -> None:
        self.chat = type(
            "Chat",
            (),
            {"completions": _RecordingCompletions(content, error)},
        )()


def _assert_gpt5_kwargs(test_case: unittest.TestCase, kwargs: dict, task_id: str) -> None:
    expected_profile = ai_client_factory._resolve_gpt5_chat_profile(task_id)
    for key, value in expected_profile.items():
        test_case.assertEqual(kwargs.get(key), value, task_id)
    test_case.assertNotIn("temperature", kwargs, task_id)
    test_case.assertNotIn("top_p", kwargs, task_id)


class TestTask23RequestShapes(unittest.TestCase):
    """Capture final kwargs from each included spatial/toolkit stage."""

    def test_spatial_gpt5_kwargs_and_json_mode(self) -> None:
        from utils import spatial_contract

        client = _RecordingClient(
            '{"coordinates":{"ROOM001":"X10Y10"},"connectivity":{"ROOM001":[]}}'
        )
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = spatial_contract.resolve_semantic_spatial_plan(
                [{"id": "ROOM001", "name": "Room", "connections": []}],
                use_llm=True,
            )

        self.assertEqual(result["coordinates"]["ROOM001"], "X10Y10")
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "dm_validation")
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_classification_gpt5_kwargs_and_json_mode(self) -> None:
        from web.extensions import toolkit_llm_classification as classification

        client = _RecordingClient(
            '{"classifications":{"Spectral Servant":"combatant"}}'
        )
        with bf.forced_provider("openai", False), patch.object(
            classification, "create_chat_client", return_value=client
        ):
            result = classification.call_llm_classify_entities(
                [{
                    "entity_name": "Spectral Servant",
                    "area_id": "AR001",
                    "context": "A figure waits.",
                }]
            )

        self.assertEqual(result["Spectral Servant"], "combatant")
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "dm_validation")
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_module_stitcher_gpt5_kwargs(self) -> None:
        from core.generators.module_stitcher import ModuleStitcher

        client = _RecordingClient(
            '{"travelNarration":"A road leads onward.","dmGuidance":"Introduce the region."}'
        )
        stitcher = object.__new__(ModuleStitcher)
        stitcher.client = client
        stitcher.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            result = stitcher._generate_travel_narration(
                {
                    "moduleName": "Test Module",
                    "plotObjective": "Find the gate.",
                    "levelRange": {"min": 1, "max": 3},
                    "areas": {"AR001": {"areaName": "Gate", "areaType": "dungeon"}},
                }
            )

        self.assertEqual(result["travelNarration"], "A road leads onward.")
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "travel_narration")

    def test_module_stitcher_safety_gpt5_kwargs(self) -> None:
        from core.generators.module_stitcher import ModuleStitcher

        client = _RecordingClient('{"safe":true,"reason":"ok"}')
        stitcher = object.__new__(ModuleStitcher)
        stitcher.client = client
        stitcher.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            result = stitcher._ai_validate_content_safety(
                {
                    "plotObjective": "Protect the village.",
                    "themes": ["mystery"],
                    "areas": {"AR001": {"areaDescription": "A quiet road."}},
                }
            )

        self.assertTrue(result)
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "safety_review")

    def test_toolkit_npc_description_gpt5_kwargs(self) -> None:
        from web.web_interface import _generate_toolkit_npc_description

        client = _RecordingClient("A weathered traveler with a bright cloak.")
        with bf.forced_provider("openai", False):
            result = _generate_toolkit_npc_description("Scout Kira", client=client)

        self.assertEqual(result["status"], "success")
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "npc_builder")
        self.assertEqual(kwargs["max_tokens"], 300)

    def test_npc_reconciler_gpt5_kwargs(self) -> None:
        from utils.npc_reconciler import NpcReconciler

        client = _RecordingClient("true")
        reconciler = object.__new__(NpcReconciler)
        reconciler.client = client
        reconciler.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            result = reconciler._ai_confirm_merge("Old Elara", "Elara")

        self.assertTrue(result)
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "dm_validation")
        self.assertEqual(kwargs["max_tokens"], 1)

    def test_critical_repair_gpt5_kwargs(self) -> None:
        from scripts.run_critical_narrative_repair import _try_provider_call

        client = _RecordingClient('{"proposals":[]}')
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            raw = _try_provider_call("repair prompt")

        self.assertEqual(json.loads(raw), {"proposals": []})
        kwargs = client.chat.completions.calls[0]
        _assert_gpt5_kwargs(self, kwargs, "builders")
        self.assertEqual(kwargs["timeout"], 120)

    def test_included_stages_preserve_openrouter_request_fields(self) -> None:
        from web.extensions import toolkit_llm_classification as classification

        client = _RecordingClient('{"classifications":{"x":"combatant"}}')
        with bf.forced_provider("openrouter", True), patch.object(
            classification, "create_chat_client", return_value=client
        ):
            expected = ai_client_factory.get_model_config(
                "dm_validation", "gpt-5.6-luna"
            )
            classification.call_llm_classify_entities(
                [{"entity_name": "x", "area_id": "AR001", "context": "x"}]
            )

        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], expected["model"])
        self.assertEqual(kwargs["temperature"], expected["temperature"])
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(kwargs.get(key), value)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("verbosity", kwargs)


class TestTask23StageErrors(unittest.TestCase):
    """Provider failures remain stage-identifiable and preserve fallbacks."""

    def test_spatial_failure_is_degraded_and_stage_tagged(self) -> None:
        from utils import spatial_contract

        client = _RecordingClient(error=RuntimeError("provider rejection"))
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = spatial_contract.resolve_semantic_spatial_plan(
                [{"id": "ROOM001", "name": "Room", "connections": []}],
                use_llm=True,
            )

        diagnostics = result["provider_diagnostics"]
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(diagnostics["status"], "degraded")
        self.assertEqual(diagnostics["stage"], "toolkit_spatial.semantic_plan")
        self.assertEqual(diagnostics["fallback"], "deterministic_spatial_plan")

    def test_classification_failure_is_defaulted_and_stage_tagged(self) -> None:
        from web.extensions import toolkit_llm_classification as classification

        client = _RecordingClient(error=RuntimeError("provider outage"))
        errors = []
        with bf.forced_provider("openai", False), patch.object(
            classification, "create_chat_client", return_value=client
        ):
            result = classification.call_llm_classify_entities(
                [{"entity_name": "x", "area_id": "AR001", "context": "x"}],
                error_sink=errors,
            )

        self.assertEqual(result["x"], "combatant")
        self.assertEqual(errors[0]["stage"], "toolkit_classification.entity")
        self.assertEqual(errors[0]["status"], "degraded")

    def test_classification_pass_reports_degraded_provider_stage(self) -> None:
        from web.extensions import toolkit_llm_classification as classification

        client = _RecordingClient(error=RuntimeError("provider outage"))
        with bf.forced_provider("openai", False), patch.object(
            classification, "create_chat_client", return_value=client
        ), patch.object(
            classification,
            "detect_ambiguous_entities",
            return_value=[{"name": "x", "area": "AR001", "sentence": "x"}],
        ), patch.object(classification, "detect_ambiguous_destinations", return_value=[]), patch.object(
            classification, "detect_ambiguous_npc_visibility", return_value=[]
        ):
            result = classification.run_llm_classification_pass("modules/Test")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(
            result["provider_errors"][0]["stage"],
            "toolkit_classification.entity",
        )

    def test_remediation_failure_is_empty_and_stage_tagged(self) -> None:
        from web.extensions import toolkit_llm_classification as classification

        client = _RecordingClient(error=RuntimeError("provider outage"))
        errors = []
        with bf.forced_provider("openai", False), patch.object(
            classification, "create_chat_client", return_value=client
        ):
            result = classification.call_llm_remediation_proposals(
                [{"blocker_classes": ["semantic_gap"]}],
                error_sink=errors,
            )

        self.assertEqual(result, [])
        self.assertEqual(
            errors[0]["stage"],
            "toolkit_classification.remediation",
        )
        self.assertEqual(errors[0]["status"], "degraded")

    def test_module_stitcher_failures_keep_stage_identity(self) -> None:
        from core.generators.module_stitcher import ModuleStitcher

        client = _RecordingClient(error=RuntimeError("provider rejection"))
        stitcher = object.__new__(ModuleStitcher)
        stitcher.client = client
        stitcher.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            travel = stitcher._generate_travel_narration(
                {"moduleName": "Test", "areas": {}}
            )
        self.assertEqual(travel["status"], "degraded")
        self.assertEqual(
            stitcher.provider_stage_errors[0]["stage"],
            "module_stitcher.travel_narration",
        )

        safety_client = _RecordingClient(error=RuntimeError("provider outage"))
        stitcher.client = safety_client
        stitcher.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            self.assertTrue(
                stitcher._ai_validate_content_safety(
                    {"areas": {}, "themes": [], "plotObjective": ""}
                )
            )
        self.assertEqual(
            stitcher.provider_stage_errors[0]["stage"],
            "module_stitcher.safety_review",
        )

    def test_toolkit_npc_description_failure_is_degraded_and_stage_tagged(self) -> None:
        from web.web_interface import _generate_toolkit_npc_description

        result = _generate_toolkit_npc_description(
            "Scout Kira",
            client=_RecordingClient(error=RuntimeError("provider outage")),
        )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(
            result["failure"]["stage"],
            "toolkit_mmg.npc_description",
        )
        self.assertIn("Scout Kira", result["description"])

    def test_npc_reconciler_failure_preserves_do_not_merge_fallback(self) -> None:
        from utils.npc_reconciler import NpcReconciler

        reconciler = object.__new__(NpcReconciler)
        reconciler.client = _RecordingClient(error=RuntimeError("provider outage"))
        reconciler.provider_stage_errors = []
        with bf.forced_provider("openai", False):
            self.assertFalse(reconciler._ai_confirm_merge("Old Elara", "Elara"))
        self.assertEqual(
            reconciler.provider_stage_errors[0]["stage"],
            "module_builder.npc_reconciliation",
        )
        self.assertEqual(
            reconciler.provider_stage_errors[0]["fallback"],
            "do_not_merge",
        )

    def test_critical_repair_failure_is_fail_closed_and_stage_tagged(self) -> None:
        from scripts.run_critical_narrative_repair import _try_provider_call

        client = _RecordingClient(error=RuntimeError("provider outage"))
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = json.loads(_try_provider_call("repair prompt"))

        self.assertTrue(result["provider_error"])
        self.assertEqual(
            result["provider_stage"],
            "accurate_ingest.critical_narrative_repair",
        )

    def test_registry_stage_surfaces_module_stitcher_provider_diagnostics(self) -> None:
        from web.extensions import toolkit_module_finisher as finisher

        class _FakeStitcher:
            provider_stage_errors = [{
                "status": "degraded",
                "stage": "module_stitcher.safety_review",
                "error_type": "RuntimeError",
            }]

            def integrate_module(self, module_slug):
                return True

        with patch(
            "core.generators.module_stitcher.ModuleStitcher",
            return_value=_FakeStitcher(),
        ), patch.object(
            __import__("scripts.homebrew_registry_guard", fromlist=["verify_present"]),
            "verify_present",
            side_effect=[
                {"present": False},
                {"present": True},
            ]
        ):
            result = finisher._run_registry_stage("Test_Module")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(
            result["provider_stage_errors"][0]["stage"],
            "module_stitcher.safety_review",
        )

    def test_remediation_stage_surfaces_provider_diagnostics(self) -> None:
        from web.extensions import toolkit_module_finisher as finisher

        def _provider_failure(batch, error_sink=None):
            error_sink.append({
                "status": "degraded",
                "stage": "toolkit_classification.remediation",
                "error_type": "RuntimeError",
            })
            return []

        with patch(
            "web.extensions.toolkit_llm_classification.call_llm_remediation_proposals",
            side_effect=_provider_failure,
        ):
            result = finisher._run_llm_remediation_stage(
                "Test_Module",
                os.path.join(_REPO_ROOT, "modules", "Test_Module"),
                {
                    "report": {
                        "remediation_categories": ["semantic_gap"],
                        "blocker_classes": ["semantic_gap"],
                    }
                },
            )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(
            result["provider_errors"][0]["stage"],
            "toolkit_classification.remediation",
        )


if __name__ == "__main__":
    unittest.main()
