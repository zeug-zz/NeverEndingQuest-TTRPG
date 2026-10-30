"""Source-contract tests for accurate-ingest generator source locks.

Tests verify source lock context propagates into ModuleGenerator prompts.
All tests are provider-free -- LLM calls use fake responses.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.generators.module_generator import ModuleGenerator
from core.generators.area_generator import MapLayoutGenerator
from core.generators.location_generator import LocationGenerator
from core.generators.plot_generator import PlotGenerator
from core.generators.module_builder import ModuleBuilder, BuilderConfig


SCRATCH_DIR = os.path.join(
    os.path.dirname(__file__), "..", "tmp", "router-rollout", "g6"
)


class RecordingLLMCall:
    """Record facade kwargs and return queued response-content strings."""

    def __init__(self, *responses: str):
        self.calls = []
        self.responses = list(responses or ("test",))

    def __call__(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


class TestGeneratorSourceLocks(unittest.TestCase):

    _SOURCE_CONTEXT = (
        "=== SOURCE LOCK CONTEXT ===\n"
        "NPCS: Elara, Thorn\n"
        "LOCATIONS: Dark Forest, Crystal Cave\n"
        "PUZZLES: skull_riddle\n"
        "MONSTERS: Alhoon\n"
        "ENCOUNTER_SEEDS:\n"
        "- The skull riddle trial\n"
        "SOURCE_LOCKS: canonical_names_locked, invented_major_entities_forbidden"
    )

    @staticmethod
    def _mock_facade(module_name: str, *responses: str):
        """Patch the named generator's facade and return its call recorder."""
        fake_call = RecordingLLMCall(*responses)
        patch_call = patch(
            f"core.generators.{module_name}.llm.call",
            side_effect=fake_call,
        )
        return fake_call, patch_call

    def test_generate_field_includes_source_lock_context(self):
        """generate_field prompt includes source lock context when present."""
        fake_call, p_call = self._mock_facade("module_generator")

        with p_call:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": self._SOURCE_CONTEXT},
            )

            call_args = fake_call.calls[-1]
            messages = call_args["messages"]
            user_prompt = messages[1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("skull riddle trial", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_generate_field_source_lock_provider_free(self):
        """generate_field does not trigger real provider calls with patched facade."""
        fake_call, p_call = self._mock_facade("module_generator")

        with p_call:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": "test"},
            )

            self.assertEqual(len(fake_call.calls), 1)
            call_args = fake_call.calls[0]
            self.assertEqual(call_args["task"], "module_generator")
            messages = call_args["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "system")
            self.assertEqual(messages[1]["role"], "user")

    def test_generate_field_missing_context_no_crash(self):
        """generate_field handles empty or missing source context gracefully."""
        fake_call, p_call = self._mock_facade("module_generator")

        with p_call:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": "A heroic adventure in the dark woods."},
            )

            call_args = fake_call.calls[-1]
            messages = call_args["messages"]
            user_prompt = messages[1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("dark woods", user_prompt)

    def test_area_thematic_names_prompt_includes_source_lock_context(self):
        """generate_thematic_names prompt includes source lock context when present."""
        fake_call, p_call = self._mock_facade(
            "area_generator", json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Dark Forest",
            "area_type": "wilderness",
            "theme": self._SOURCE_CONTEXT,
        }

        with p_call:
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("skull riddle trial", user_prompt)

    def test_area_thematic_names_missing_context_no_crash(self):
        """generate_thematic_names handles missing source context gracefully."""
        fake_call, p_call = self._mock_facade(
            "area_generator", json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Test Area",
            "area_type": "dungeon",
            "theme": "heroic fantasy adventure",
        }

        with p_call:
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("heroic fantasy adventure", user_prompt)

    def test_location_batch_prompt_includes_source_lock_context(self):
        """generate_location_batch prompt includes source lock context when present."""
        fake_call, p_call = self._mock_facade(
            "location_generator", json.dumps({"locations": []})
        )

        area_data = {"areaName": "Dark Forest", "areaType": "wilderness"}
        plot_data = {"plotTitle": "Test Plot", "mainObjective": "Explore"}
        module_data = {"moduleName": "Test Module"}
        location_stubs = [{"id": "L001", "name": "Crystal Cave"}]

        with p_call:
            gen = LocationGenerator()
            gen.generate_location_batch(
                area_data,
                plot_data,
                module_data,
                location_stubs,
                context_header=self._SOURCE_CONTEXT,
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_location_batch_missing_context_no_crash(self):
        """generate_location_batch handles missing source context gracefully."""
        fake_call, p_call = self._mock_facade(
            "location_generator", json.dumps({"locations": []})
        )

        area_data = {"areaName": "Dark Forest", "areaType": "wilderness"}
        plot_data = {"plotTitle": "Test Plot", "mainObjective": "Explore"}
        module_data = {"moduleName": "Test Module"}
        location_stubs = [{"id": "L001", "name": "Crystal Cave"}]

        with p_call:
            gen = LocationGenerator()
            gen.generate_location_batch(
                area_data,
                plot_data,
                module_data,
                location_stubs,
                context_header="",
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)

    def test_plot_generator_field_includes_source_lock_context(self):
        """generate_field prompt includes source lock context when present in context dict."""
        fake_call, p_call = self._mock_facade("plot_generator")

        with p_call:
            gen = PlotGenerator()
            gen.generate_field(
                "plotTitle",
                {"type": "string"},
                {"initialConcept": self._SOURCE_CONTEXT},
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_plot_generator_field_missing_context_no_crash(self):
        """generate_field handles missing source context gracefully."""
        fake_call, p_call = self._mock_facade("plot_generator")

        with p_call:
            gen = PlotGenerator()
            gen.generate_field(
                "plotTitle",
                {"type": "string"},
                {"initialConcept": "A heroic adventure in the dark woods."},
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("dark woods", user_prompt)

    def test_plot_plot_structure_includes_source_lock_context(self):
        """generate_plot_structure prompt includes source lock context when present."""
        fake_call, p_call = self._mock_facade(
            "plot_generator", json.dumps({"plotPoints": []})
        )

        context = {"module_name": "Test Module", "areas": {}, "locations": {}, "npcs": {}}

        with p_call:
            gen = PlotGenerator()
            gen.generate_plot_structure(
                3,
                context,
                context_header=self._SOURCE_CONTEXT,
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_plot_plot_structure_missing_context_no_crash(self):
        """generate_plot_structure handles missing source context gracefully."""
        fake_call, p_call = self._mock_facade(
            "plot_generator", json.dumps({"plotPoints": []})
        )

        context = {"module_name": "Test Module", "areas": {}, "locations": {}, "npcs": {}}

        with p_call:
            gen = PlotGenerator()
            gen.generate_plot_structure(
                3,
                context,
                context_header="",
            )

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)

    def test_plot_generator_adaptation_calls_use_facade_parameter_ownership(self):
        """Adaptation calls keep request parameters owned by the facade."""
        fake_call, p_call = self._mock_facade(
            "plot_generator", "Test plot title", json.dumps({"plotPoints": []})
        )

        with p_call:
            gen = PlotGenerator(llm_timeout_seconds=27)
            gen.generate_field("plotTitle", {"type": "string"}, {})
            gen.generate_plot_structure(
                3,
                {"module_name": "Test", "areas": {}, "locations": {}, "npcs": {}},
            )

        self.assertEqual(len(fake_call.calls), 2)
        for call in fake_call.calls:
            self.assertEqual(call["task"], "plot_generator")
            self.assertFalse({"model", "temperature", "timeout"}.intersection(call))

    def test_plot_generator_legacy_calls_leave_parameters_with_facade(self):
        """Legacy calls omit caller-owned provider parameters."""
        fake_call, p_call = self._mock_facade(
            "plot_generator", "Test plot title", json.dumps({"plotPoints": []})
        )

        with p_call:
            gen = PlotGenerator()
            gen.generate_field("plotTitle", {"type": "string"}, {})
            gen.generate_plot_structure(
                3,
                {"module_name": "Test", "areas": {}, "locations": {}, "npcs": {}},
            )

        self.assertEqual(len(fake_call.calls), 2)
        for call in fake_call.calls:
            self.assertEqual(call["task"], "plot_generator")
            self.assertFalse({"model", "temperature", "timeout"}.intersection(call))

    def test_module_builder_facade_call_leaves_provider_parameters_to_facade(self):
        """Module plot unification does not pass model, temperature, or timeout."""
        builder = object.__new__(ModuleBuilder)
        builder.module_data = {"moduleName": "Test Module", "moduleDescription": "A test."}
        builder.areas_data = {"A001": {"areaName": "Dark Forest"}}
        builder.plots_data = {
            "A001": {
                "plotTitle": "The Lost Path",
                "mainObjective": "Find the trail.",
                "plotPoints": [],
            }
        }
        builder.adaptation_prompt_context = {}
        builder.build_mode = "legacy"
        builder.config = type("Config", (), {"output_directory": "unused"})()
        builder.save_json = MagicMock()
        builder.log = lambda message: None
        builder._create_fallback_unified_plot = MagicMock()
        fake_call = RecordingLLMCall(
            json.dumps(
                {
                    "plotTitle": "Unified Plot",
                    "mainObjective": "Find the trail.",
                    "plotPoints": [],
                }
            )
        )

        # ModuleBuilder imports ll locally inside unify_plots, so patch the
        # shared facade singleton rather than a nonexistent module attribute.
        with patch("utils.llm_router.llm.call", side_effect=fake_call):
            builder.unify_plots()

        self.assertEqual(len(fake_call.calls), 1)
        call = fake_call.calls[0]
        self.assertEqual(call["task"], "unify_plots")
        self.assertFalse({"model", "temperature", "timeout"}.intersection(call))
        builder.save_json.assert_called_once()

    def test_module_builder_extract_source_lock_context(self):
        """_extract_source_lock_context returns source block when present."""
        builder = object.__new__(ModuleBuilder)
        text_with_source = (
            "Build a module about a hidden city.\n\n"
            "=== SOURCE LOCK CONTEXT ===\n"
            "NPCS: Elara, Thorn\n"
            "SOURCE_LOCKS: canonical_names_locked"
        )
        result = builder._extract_source_lock_context(text_with_source)
        self.assertIn("SOURCE LOCK CONTEXT", result)
        self.assertIn("Elara", result)
        self.assertIn("canonical_names_locked", result)

    def test_module_builder_ignores_missing_source_lock_context(self):
        """_extract_source_lock_context returns empty when no source block."""
        builder = object.__new__(ModuleBuilder)
        text_without_source = "Build a module about a hidden city."
        result = builder._extract_source_lock_context(text_without_source)
        self.assertEqual(result, "")

    @patch("core.generators.module_builder.ModuleGenerator")
    @patch("core.generators.module_builder.PlotGenerator")
    @patch("core.generators.module_builder.LocationGenerator")
    @patch("core.generators.module_builder.AreaGenerator")
    def test_module_builder_propagates_source_context(
        self, mock_area_gen_cls, mock_loc_gen_cls, mock_plot_gen_cls, mock_mod_gen_cls
    ):
        """build_module stores source context and appends to context_header for downstream."""
        os.makedirs(SCRATCH_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH_DIR) as tmpdir:
            cfg = BuilderConfig(
                module_name="Test_Module",
                output_directory=tmpdir,
                verbose=False,
            )
            builder = ModuleBuilder(cfg)
            # Mock all sub-generator instances
            builder.module_gen = MagicMock()
            builder.module_gen.generate_module.return_value = {
                "moduleName": "Test Module",
                "moduleDescription": "A test module",
                "worldMap": [],
            }
            builder.area_gen = MagicMock()
            builder.location_gen = MagicMock()
            builder.plot_gen = MagicMock()
            # Mock downstream builder methods to avoid full pipeline execution
            builder.generate_areas = MagicMock()
            builder.generate_locations = MagicMock()
            builder.generate_plots = MagicMock()
            builder.create_party_tracker = MagicMock()
            builder.create_module_summary = MagicMock()
            builder.validate_module = MagicMock()
            builder.create_bu_backups = MagicMock()

            initial_concept = (
                "Build a module.\n\n"
                "=== SOURCE LOCK CONTEXT ===\n"
                "NPCS: Elara, Thorn\n"
                "SOURCE_LOCKS: canonical_names_locked"
            )
            builder.build_module(initial_concept)
            self.assertIn("SOURCE LOCK CONTEXT", builder.source_lock_context)
            self.assertIn("Elara", builder.source_lock_context)
            # context_header should contain source block after step 1
            self.assertIn("SOURCE LOCK CONTEXT", builder.context_header)

    @patch("core.generators.module_builder.ModuleGenerator")
    @patch("core.generators.module_builder.PlotGenerator")
    @patch("core.generators.module_builder.LocationGenerator")
    @patch("core.generators.module_builder.AreaGenerator")
    def test_module_builder_legacy_no_source_leak(
        self, mock_area_gen_cls, mock_loc_gen_cls, mock_plot_gen_cls, mock_mod_gen_cls
    ):
        """Legacy build_module without source block does not add source context."""
        os.makedirs(SCRATCH_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH_DIR) as tmpdir:
            cfg = BuilderConfig(
                module_name="Test_Module",
                output_directory=tmpdir,
                verbose=False,
            )
            builder = ModuleBuilder(cfg)
            builder.module_gen = MagicMock()
            builder.module_gen.generate_module.return_value = {
                "moduleName": "Test Module",
                "moduleDescription": "A test module",
                "worldMap": [],
            }
            builder.area_gen = MagicMock()
            builder.location_gen = MagicMock()
            builder.plot_gen = MagicMock()
            # Mock downstream builder methods to avoid full pipeline execution
            builder.generate_areas = MagicMock()
            builder.generate_locations = MagicMock()
            builder.generate_plots = MagicMock()
            builder.create_party_tracker = MagicMock()
            builder.create_module_summary = MagicMock()
            builder.validate_module = MagicMock()
            builder.create_bu_backups = MagicMock()

            builder.build_module("Build a module.")
            self.assertEqual(builder.source_lock_context, "")
            self.assertNotIn("SOURCE LOCK CONTEXT", builder.context_header)

    def test_area_thematic_names_source_lock_context_key(self):
        """generate_thematic_names includes source block through _source_lock_context key."""
        fake_call, p_call = self._mock_facade(
            "area_generator", json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Dark Forest",
            "area_type": "wilderness",
            "theme": "heroic fantasy",
            "_source_lock_context": self._SOURCE_CONTEXT,
        }

        with p_call:
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = fake_call.calls[-1]
            user_prompt = call_args["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("SOURCE CONSTRAINTS", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Alhoon", user_prompt)


if __name__ == "__main__":
    unittest.main()
