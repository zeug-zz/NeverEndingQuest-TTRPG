# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for task 3.2 adaptation builder prompt context."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.generators.area_generator import AreaConfig, AreaGenerator, MapLayoutGenerator
from core.generators.location_generator import LocationGenerator
from core.generators.module_builder import BuilderConfig, ModuleBuilder
from core.generators.module_generator import ModuleGenerator
from core.generators.plot_generator import PlotGenerator
from utils.toolkit_adaptation_builder_context import (
    ADAPTATION_CONTEXT_MARKER,
    MAX_ADAPTATION_CONTEXT_CHARS,
    build_adaptation_context_bundle,
    build_adaptation_prompt_context,
)
from web.extensions.toolkit_homebrew_packet_builder import build_llm_adaptation_handoff


REPO_ROOT = Path(__file__).resolve().parents[1]
DOSSIER_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


def _handoff():
    dossier = json.loads(DOSSIER_PATH.read_text(encoding="utf-8"))
    return build_llm_adaptation_handoff(
        dossier,
        {
            "attempt_id": "task-3-2-fixture",
            "model_metadata": {
                "provider": "fixture",
                "model": "mock-adaptation-model",
                "parameter_profile": "toolkit_adaptation_author",
            },
        },
    )


class TestAdaptationContextContract(unittest.TestCase):
    def test_context_is_bounded_and_covers_required_creative_surfaces(self):
        handoff = _handoff()
        bundle = build_adaptation_context_bundle(handoff)

        expected_surfaces = {
            "module",
            "areas",
            "locations",
            "plot",
            "npcs",
            "encounters",
            "monsters",
            "items",
            "connective",
        }
        self.assertEqual(set(bundle), expected_surfaces)
        for surface, context in bundle.items():
            self.assertIn(ADAPTATION_CONTEXT_MARKER, context)
            self.assertLessEqual(len(context), MAX_ADAPTATION_CONTEXT_CHARS)
            self.assertIn("PYTHON-OWNED STRUCTURAL CONTRACT", context)
            self.assertIn("Adapted for NEQ-TTRPG", context)
            self.assertIn("Lantern Market", context)
            self.assertNotIn("SOURCE LOCK CONTEXT", context)

    def test_catalogue_profile_keeps_item_headings_out_of_area_guidance(self):
        handoff = _handoff()
        areas_context = build_adaptation_prompt_context(handoff, "areas")
        locations_context = build_adaptation_prompt_context(handoff, "locations")

        self.assertIn("catalogue", areas_context)
        self.assertIn("Item headings are not location requirements", areas_context)
        self.assertIn("Lantern Market Gate", areas_context)
        self.assertIn("Lanternwright Stall", areas_context)
        self.assertNotIn("Hooded Lantern", areas_context)
        self.assertIn("NPC SEEDS (ADVISORY)", locations_context)
        self.assertIn("ENCOUNTER AND MONSTER IDEAS (ADVISORY)", locations_context)
        self.assertIn("ITEM AND TREASURE IDEAS (ADVISORY)", locations_context)
        self.assertIn("ORIGINAL NEQ CONNECTIVE MATERIAL (ADVISORY)", locations_context)

    def test_legacy_or_invalid_input_does_not_activate_adaptation_context(self):
        dossier = json.loads(DOSSIER_PATH.read_text(encoding="utf-8"))
        self.assertEqual(build_adaptation_prompt_context(dossier, "module"), "")
        self.assertEqual(build_adaptation_context_bundle({}), {})


class TestAdaptationPromptPropagation(unittest.TestCase):
    def test_module_generator_field_prompt_receives_adaptation_context(self):
        context = build_adaptation_prompt_context(_handoff(), "module")
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = FakeResponse("Lantern Market")
        with patch(
            "core.generators.module_generator.create_chat_client",
            return_value=fake_client,
        ), patch(
            "core.generators.module_generator.get_chat_completion_params",
            return_value={},
        ):
            ModuleGenerator().generate_field(
                "moduleName",
                {"type": "string"},
                {"_llm_adaptation_prompt_context": context},
            )
        prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn(ADAPTATION_CONTEXT_MARKER, prompt)
        self.assertIn("Warm market fantasy", prompt)

    def test_module_builder_passes_explicit_context_to_module_overview(self):
        handoff = _handoff()
        with tempfile.TemporaryDirectory(dir=str(REPO_ROOT / "tmp"), prefix="task_3_2_builder_") as tmpdir:
            builder = ModuleBuilder(
                BuilderConfig(
                    module_name="Lantern_Market",
                    num_areas=1,
                    locations_per_area=2,
                    output_directory=tmpdir,
                    verbose=False,
                )
            )
            builder.module_gen = MagicMock()
            builder.module_gen.generate_module.return_value = {
                "moduleName": "Lantern Market",
                "moduleDescription": "A market adaptation.",
                "worldMap": [],
            }
            builder.generate_areas = MagicMock()
            builder.generate_locations = MagicMock()
            builder.generate_plots = MagicMock()
            builder.create_party_tracker = MagicMock()
            builder.create_module_summary = MagicMock()
            builder.validate_module = MagicMock()
            builder.create_bu_backups = MagicMock()

            builder.build_module("Build the market.", llm_adaptation=handoff)

            call = builder.module_gen.generate_module.call_args
            self.assertIsNotNone(call)
            self.assertEqual(
                call.kwargs["adaptation_context"],
                builder.adaptation_prompt_context["module"],
            )
            self.assertIn("Lantern Market", call.kwargs["adaptation_context"])
            self.assertIn("ORIGINAL NEQ CONNECTIVE MATERIAL", call.kwargs["adaptation_context"])

    def test_area_location_and_plot_generators_receive_adaptation_context(self):
        handoff = _handoff()
        areas_context = build_adaptation_prompt_context(handoff, "areas")
        locations_context = build_adaptation_prompt_context(handoff, "locations")
        plot_context = build_adaptation_prompt_context(handoff, "plot")

        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = FakeResponse(
            json.dumps(["Market Gate"])
        )
        with patch("core.generators.area_generator.create_chat_client", return_value=fake_client), patch(
            "core.generators.area_generator.get_chat_completion_params", return_value={}
        ):
            MapLayoutGenerator().generate_thematic_names(
                [{"id": "A01", "type": "gate", "connections": []}],
                {
                    "module_name": "Lantern Market",
                    "area_name": "Lantern Market",
                    "area_type": "town",
                    "theme": "market mystery",
                    "_llm_adaptation_prompt_context": areas_context,
                },
            )
        area_prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn(ADAPTATION_CONTEXT_MARKER, area_prompt)
        self.assertIn("Lanternwright Stall", area_prompt)

        fake_location_client = MagicMock()
        fake_location_client.chat.completions.create.return_value = FakeResponse(
            json.dumps({"locations": []})
        )
        with patch(
            "core.generators.location_generator.create_chat_client",
            return_value=fake_location_client,
        ), patch(
            "core.generators.location_generator.get_chat_completion_params",
            return_value={},
        ):
            LocationGenerator().generate_location_batch(
                {"areaName": "Lantern Market", "areaType": "town"},
                {},
                {
                    "moduleName": "Lantern Market",
                    "_llm_adaptation_prompt_context": locations_context,
                },
                [{"id": "A01", "name": "Market Gate"}],
            )
        location_prompt = fake_location_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn(ADAPTATION_CONTEXT_MARKER, location_prompt)
        self.assertIn("Wayfinder Lantern", location_prompt)
        self.assertIn("The Sealed Lantern", location_prompt)

        fake_plot_client = MagicMock()
        fake_plot_client.chat.completions.create.return_value = FakeResponse("Market Plot")
        with patch(
            "core.generators.plot_generator.create_chat_client",
            return_value=fake_plot_client,
        ), patch(
            "core.generators.plot_generator.get_chat_completion_params",
            return_value={},
        ):
            PlotGenerator().generate_field(
                "plotTitle",
                {"type": "string"},
                {"_llm_adaptation_prompt_context": plot_context},
            )
        plot_prompt = fake_plot_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn(ADAPTATION_CONTEXT_MARKER, plot_prompt)
        self.assertIn("Find the missing shipment", plot_prompt)


class TestAdaptationStructuralContracts(unittest.TestCase):
    def test_representative_adapted_outputs_pass_existing_validators(self):
        module_data = {
            "moduleName": "Lantern Market",
            "moduleDescription": "A market mystery.",
            "moduleMetadata": {
                "author": "NeverEndingQuest",
                "version": "1.0",
                "levelRange": {"min": 1, "max": 4},
                "estimatedPlayTime": "2 sessions",
                "moduleType": "urban",
            },
            "mainPlot": {
                "mainObjective": "Recover the missing shipment.",
                "antagonist": "A hidden buyer",
                "plotStages": [
                    {
                        "stageName": "Market Investigation",
                        "stageDescription": "The party follows the shipment trail.",
                        "requiredLevel": 1,
                        "keyNPCs": ["Mira Vell"],
                        "majorEvents": ["The sealed lantern is discovered"],
                    }
                ],
            },
            "factions": [],
            "worldMap": [
                {
                    "regionName": "Lantern Market",
                    "regionDescription": "A covered market district.",
                    "mapId": "LM001",
                    "dangerLevel": "low",
                    "recommendedLevel": 1,
                    "levels": [
                        {
                            "name": "Market Level",
                            "id": "LM001-A",
                            "description": "The main market level.",
                        }
                    ],
                }
            ],
            "timelineEvents": [],
        }
        self.assertEqual(ModuleGenerator().validate_module(module_data), [])

        location = {
            "name": "Lantern Market Gate",
            "type": "gate",
            "description": "A covered market gate.",
            "dmInstructions": "Use the gate to introduce the missing shipment.",
            "locationId": "LM01",
            "coordinates": "X10Y10",
            "aliases": ["market gate"],
            "tactical_grid": ["open"] * 9,
            "accessibility": "Open archway",
            "npcs": [{"name": "Mira Vell", "description": "A worried keeper.", "attitude": "friendly"}],
            "monsters": [],
            "plotHooks": ["A shipment is missing."],
            "lootTable": ["Wayfinder Lantern"],
            "dangerLevel": "Low",
            "connectivity": [],
            "areaConnectivity": [],
            "areaConnectivityId": [],
            "traps": [],
            "features": [{"name": "Covered stalls", "description": "Colored lanterns hang overhead."}],
            "dcChecks": ["Investigation DC 12: Find the missing shipment ledger."],
            "encounters": [],
            "adventureSummary": "The party begins the investigation.",
            "doors": [],
        }
        jsonschema.validate({"locations": [location]}, LocationGenerator().schema)

        plot_data = {
            "plotTitle": "The Sealed Lantern",
            "mainObjective": "Recover the missing shipment.",
            "plotPoints": [
                {
                    "id": "PP001",
                    "title": "Ask at the Gate",
                    "description": "The keeper explains the problem.",
                    "location": "LM01",
                    "nextPoints": [],
                    "status": "not started",
                    "plotImpact": "",
                }
            ],
        }
        self.assertEqual(
            PlotGenerator().validate_plot(plot_data, {"locations": [location]}),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
