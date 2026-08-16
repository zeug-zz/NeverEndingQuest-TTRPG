# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free request and fallback contracts for task 3.1 call sites.

Covers the three Markdown enrichment call sites in
``utils/homebrewery_adventure_writer.py`` migrated in task 3.1:

- M1 ``_llm_intro_narrative`` (task id ``summaries``, override 0.5,
  max_completion_tokens 800)
- M2 ``_llm_plot_hook`` (task id ``summaries``, override 0.7,
  max_completion_tokens 250)
- M3 ``_llm_area_overview`` (task id ``summaries``, override 0.6,
  max_completion_tokens 500)

Assertions, all provider-free (mock client captures final kwargs):

1. Direct GPT-5 branch: the captured request carries the ``summaries``
   low/medium reasoning profile and omits legacy ``temperature``/``top_p``;
   ``model``, ``messages``, and ``max_completion_tokens`` are preserved.
2. Compatible non-GPT-5 branch: the caller's temperature intent
   (0.5/0.7/0.6) is preserved through the helper override and no GPT-5
   profile keys are present.
3. OpenRouter branch: the configured OpenRouter model and
   ``extra_body`` thinking/request fields are preserved with the same
   temperature override; no GPT-5 profile substitution.
4. Deterministic fallback: when the provider raises or returns unusable
   (empty) output, each ``_llm_*`` function returns ``None`` and the
   enclosing section builders emit their existing deterministic Markdown
   (bullet overview, one-liner plot hook, areaDescription fallback)
   instead of a false successful enrichment artifact.

Provider-free: no live API, no credentials, no raw source persistence.
"""

from __future__ import annotations

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

_MARKDOWN_TASK_ID = "summaries"


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


_INTRO_PLOT_TEXT = "PP001 - The Call:\nThe party is summoned to the gate."
_HOOK_PLOT_TEXT = "PP001 - The Call:\nThe party is summoned to the gate."


def _area_fixture() -> dict:
    return {
        "areaId": "AR001",
        "areaName": "Gate Hall",
        "areaDescription": "A stone hall beneath the keep.",
        "areaType": "dungeon",
        "locations": [
            {
                "locationId": "AR001A",
                "name": "Gate Room",
                "description": "An iron door.",
                "connectivity": ["AR001B"],
            }
        ],
    }


def _area_data_fixture(area: dict) -> dict:
    return {
        "plot_points": [],
        "_cross_area_edges": [],
        "areas": [area],
    }


def _assert_markdown_gpt5_kwargs(
    test_case: unittest.TestCase, kwargs: dict, max_completion_tokens: int
) -> None:
    expected_profile = ai_client_factory._resolve_gpt5_chat_profile(_MARKDOWN_TASK_ID)
    for key, value in expected_profile.items():
        test_case.assertEqual(kwargs.get(key), value, key)
    test_case.assertNotIn("temperature", kwargs)
    test_case.assertNotIn("top_p", kwargs)
    test_case.assertEqual(kwargs["max_completion_tokens"], max_completion_tokens)
    test_case.assertEqual(kwargs["model"], "gpt-5.6-luna")
    test_case.assertIn("messages", kwargs)


class TestMarkdownWriterGpt5RequestShapes(unittest.TestCase):
    """M1-M3 final kwargs under the direct GPT-5 branch."""

    @staticmethod
    def _call_intro(client) -> str:
        from utils import homebrewery_adventure_writer as writer

        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            return writer._llm_intro_narrative(
                name="Test Module",
                npc_count=3,
                plot_count=4,
                area_count=5,
                monster_count=6,
                author_name="Author",
                plot_text=_INTRO_PLOT_TEXT,
            )

    @staticmethod
    def _call_plot_hook(client) -> str:
        from utils import homebrewery_adventure_writer as writer

        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            return writer._llm_plot_hook(_HOOK_PLOT_TEXT, 4, "Author")

    @staticmethod
    def _call_area_overview(client) -> str:
        from utils import homebrewery_adventure_writer as writer

        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            area = _area_fixture()
            return writer._llm_area_overview(area, _area_data_fixture(area))

    def test_intro_narrative_gpt5_kwargs(self) -> None:
        client = _RecordingClient(
            "### Module Overview\nA summary of the module.\n\n"
            "### The Story So Far\nThe party travels.\n\n"
            "### Running the Adventure\nA note for the DM."
        )
        result = self._call_intro(client)
        self.assertIn("Module Overview", result)
        self.assertEqual(len(client.chat.completions.calls), 1)
        _assert_markdown_gpt5_kwargs(self, client.chat.completions.calls[0], 800)

    def test_plot_hook_gpt5_kwargs(self) -> None:
        client = _RecordingClient("A mystery stirs beneath the gate.")
        result = self._call_plot_hook(client)
        self.assertIn("mystery stirs", result)
        self.assertEqual(len(client.chat.completions.calls), 1)
        _assert_markdown_gpt5_kwargs(self, client.chat.completions.calls[0], 250)

    def test_area_overview_gpt5_kwargs(self) -> None:
        client = _RecordingClient("A hall of iron and old stone.")
        result = self._call_area_overview(client)
        self.assertIn("iron and old stone", result)
        self.assertEqual(len(client.chat.completions.calls), 1)
        _assert_markdown_gpt5_kwargs(self, client.chat.completions.calls[0], 500)


class TestMarkdownWriterCompatibleNonGpt5RequestShapes(unittest.TestCase):
    """M1-M3 preserve the caller temperature intent on non-GPT-5 models."""

    @staticmethod
    def _expected_temperature() -> float:
        # Task id "summaries" resolves to the config temperature when no
        # override is passed; overrides below always win on compatible models.
        return ai_client_factory.get_model_config(
            _MARKDOWN_TASK_ID, "gpt-4.1-2025-04-14"
        )["temperature"]

    def test_intro_narrative_preserves_temperature_override(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("### Module Overview\nOk.\n\n### The Story So Far\nOk.\n\n### Running the Adventure\nOk.")
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ), patch("model_config.DM_SUMMARIZATION_MODEL", "gpt-4.1-2025-04-14"):
            writer._llm_intro_narrative(
                name="Test Module", npc_count=3, plot_count=4,
                area_count=5, monster_count=6, author_name="Author",
                plot_text=_INTRO_PLOT_TEXT,
            )
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["model"], "gpt-4.1-2025-04-14")
        self.assertEqual(kwargs["max_completion_tokens"], 800)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("verbosity", kwargs)

    def test_plot_hook_preserves_temperature_override(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("A hook.")
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ), patch("model_config.DM_SUMMARIZATION_MODEL", "gpt-4.1-2025-04-14"):
            writer._llm_plot_hook(_HOOK_PLOT_TEXT, 4, "Author")
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["max_completion_tokens"], 250)
        self.assertNotIn("reasoning_effort", kwargs)

    def test_area_overview_preserves_temperature_override(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("A hall.")
        area = _area_fixture()
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ), patch("model_config.DM_SUMMARIZATION_MODEL", "gpt-4.1-2025-04-14"):
            writer._llm_area_overview(area, _area_data_fixture(area))
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["temperature"], 0.6)
        self.assertEqual(kwargs["max_completion_tokens"], 500)
        self.assertNotIn("reasoning_effort", kwargs)


class TestMarkdownWriterOpenRouterRequestShapes(unittest.TestCase):
    """M1-M3 keep OpenRouter model and provider request fields."""

    @staticmethod
    def _expected_config() -> dict:
        with bf.forced_provider("openrouter", True):
            return ai_client_factory.get_model_config(
                _MARKDOWN_TASK_ID, "gpt-5.6-luna"
            )

    def test_intro_narrative_openrouter_fields(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("### Module Overview\nOk.\n\n### The Story So Far\nOk.\n\n### Running the Adventure\nOk.")
        with bf.forced_provider("openrouter", True), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            writer._llm_intro_narrative(
                name="Test Module", npc_count=3, plot_count=4,
                area_count=5, monster_count=6, author_name="Author",
                plot_text=_INTRO_PLOT_TEXT,
            )
        expected = self._expected_config()
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], expected["model"])
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["max_completion_tokens"], 800)
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(kwargs.get(key), value)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("verbosity", kwargs)

    def test_plot_hook_openrouter_fields(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("A hook.")
        with bf.forced_provider("openrouter", True), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            writer._llm_plot_hook(_HOOK_PLOT_TEXT, 4, "Author")
        expected = self._expected_config()
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], expected["model"])
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["max_completion_tokens"], 250)
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(kwargs.get(key), value)

    def test_area_overview_openrouter_fields(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("A hall.")
        area = _area_fixture()
        with bf.forced_provider("openrouter", True), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            writer._llm_area_overview(area, _area_data_fixture(area))
        expected = self._expected_config()
        kwargs = client.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], expected["model"])
        self.assertEqual(kwargs["temperature"], 0.6)
        self.assertEqual(kwargs["max_completion_tokens"], 500)
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(kwargs.get(key), value)


class TestMarkdownWriterDeterministicFallback(unittest.TestCase):
    """LLM failure/unusable output never becomes a false enrichment artifact."""

    def test_intro_narrative_returns_none_on_provider_error(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient(error=RuntimeError("provider rejection"))
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = writer._llm_intro_narrative(
                name="Test Module", npc_count=3, plot_count=4,
                area_count=5, monster_count=6, author_name="Author",
                plot_text=_INTRO_PLOT_TEXT,
            )
        self.assertIsNone(result)

    def test_intro_narrative_returns_none_on_unusable_output(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("   \n  ")
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = writer._llm_intro_narrative(
                name="Test Module", npc_count=3, plot_count=4,
                area_count=5, monster_count=6, author_name="Author",
                plot_text=_INTRO_PLOT_TEXT,
            )
        self.assertIsNone(result)

    def test_plot_hook_returns_none_on_provider_error(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient(error=RuntimeError("provider rejection"))
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = writer._llm_plot_hook(_HOOK_PLOT_TEXT, 4, "Author")
        self.assertIsNone(result)

    def test_area_overview_returns_none_on_provider_error(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient(error=RuntimeError("provider rejection"))
        area = _area_fixture()
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = writer._llm_area_overview(area, _area_data_fixture(area))
        self.assertIsNone(result)

    def test_area_overview_returns_none_on_unusable_output(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        client = _RecordingClient("")
        area = _area_fixture()
        with bf.forced_provider("openai", False), patch(
            "utils.ai_client_factory.create_chat_client", return_value=client
        ):
            result = writer._llm_area_overview(area, _area_data_fixture(area))
        self.assertIsNone(result)

    def test_build_intro_section_uses_deterministic_assembly_on_failure(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        data = {
            "display_name": "Test Module",
            "npcs": {"a": {"description": "x"}},
            "plot_points": [
                {"id": "PP001", "title": "The Call", "description": "A call."}
            ],
            "areas": [],
            "monsters": [],
            "author": "Kuhal - https://example.com/share/abc",
            "main_objective": "Find the gate.",
        }
        with patch.object(writer, "_llm_intro_narrative", return_value=None):
            section = writer._build_intro_section(data)
        # Deterministic fallback must appear; no LLM artifact may be promoted.
        self.assertIn("### Module Overview", section)
        self.assertIn("- **1** named NPCs", section)
        self.assertIn("- **1** plot points", section)
        self.assertIn("Original adventure by", section)
        self.assertNotIn("## Introduction from the LLM", section)

    def test_build_plot_overview_uses_deterministic_hook_on_failure(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        data = {
            "plot_points": [
                {"id": "PP001", "title": "The Call", "description": "A call."}
            ]
        }
        with patch.object(writer, "_llm_plot_hook", return_value=None):
            section = writer._build_plot_overview(data)
        self.assertIn("The adventure unfolds across 1 scenes", section)
        self.assertIn("### PP001 -- The Call", section)
        self.assertNotIn("LLM_HOOK_ARTIFACT", section)

    def test_build_locations_section_uses_area_description_on_failure(self) -> None:
        from utils import homebrewery_adventure_writer as writer

        area = _area_fixture()
        data = _area_data_fixture(area)
        with patch.object(writer, "_llm_area_overview", return_value=None):
            section = writer._build_locations_section(data)
        # areaDescription fallback replaces the missing LLM overview.
        self.assertIn("A stone hall beneath the keep.", section)
        self.assertIn("### AR001A -- Gate Room", section)
        self.assertNotIn("LLM_AREA_OVERVIEW_ARTIFACT", section)


if __name__ == "__main__":
    unittest.main()
