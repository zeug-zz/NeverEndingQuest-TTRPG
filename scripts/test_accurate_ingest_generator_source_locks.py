"""Source-contract tests for accurate-ingest generator source locks.

Tests verify source lock context propagates into ModuleGenerator prompts.
All tests are provider-free -- LLM calls use fake responses.
"""

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


class FakeChoice:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeResponse:
    def __init__(self, content: str = "test"):
        self.choices = [FakeChoice(content)]


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

    @classmethod
    def _mock_provider(cls, return_content: str = "test"):
        """Set up patched provider and return (mock_client, patches) tuple."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(return_content)
        patch_client = patch(
            "core.generators.module_generator.create_chat_client",
            return_value=mock_client,
        )
        patch_config = patch(
            "core.generators.module_generator.get_model_config",
            return_value={"model": "test-model"},
        )
        return mock_client, patch_client, patch_config

    def test_generate_field_includes_source_lock_context(self):
        """generate_field prompt includes source lock context when present."""
        mock_client, p_client, p_config = self._mock_provider()

        with p_client, p_config:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": self._SOURCE_CONTEXT},
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            messages = call_args[1]["messages"]
            user_prompt = messages[1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("skull riddle trial", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_generate_field_source_lock_provider_free(self):
        """generate_field does not trigger real provider calls with patched client."""
        mock_client, p_client, p_config = self._mock_provider()

        with p_client, p_config:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": "test"},
            )

            mock_client.chat.completions.create.assert_called_once()
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args[1]["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "system")
            self.assertEqual(messages[1]["role"], "user")

    def test_generate_field_missing_context_no_crash(self):
        """generate_field handles empty or missing source context gracefully."""
        mock_client, p_client, p_config = self._mock_provider()

        with p_client, p_config:
            gen = ModuleGenerator()
            gen.generate_field(
                "moduleName",
                {"type": "string"},
                {"initialConcept": "A heroic adventure in the dark woods."},
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            messages = call_args[1]["messages"]
            user_prompt = messages[1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("dark woods", user_prompt)

    def test_area_thematic_names_prompt_includes_source_lock_context(self):
        """generate_thematic_names prompt includes source lock context when present."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Dark Forest",
            "area_type": "wilderness",
            "theme": self._SOURCE_CONTEXT,
        }

        with patch(
            "core.generators.area_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.area_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("skull riddle trial", user_prompt)

    def test_area_thematic_names_missing_context_no_crash(self):
        """generate_thematic_names handles missing source context gracefully."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Test Area",
            "area_type": "dungeon",
            "theme": "heroic fantasy adventure",
        }

        with patch(
            "core.generators.area_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.area_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("heroic fantasy adventure", user_prompt)

    def test_location_batch_prompt_includes_source_lock_context(self):
        """generate_location_batch prompt includes source lock context when present."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps({"locations": []})
        )

        area_data = {"areaName": "Dark Forest", "areaType": "wilderness"}
        plot_data = {"plotTitle": "Test Plot", "mainObjective": "Explore"}
        module_data = {"moduleName": "Test Module"}
        location_stubs = [{"id": "L001", "name": "Crystal Cave"}]

        with patch(
            "core.generators.location_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.location_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = LocationGenerator()
            gen.generate_location_batch(
                area_data,
                plot_data,
                module_data,
                location_stubs,
                context_header=self._SOURCE_CONTEXT,
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_location_batch_missing_context_no_crash(self):
        """generate_location_batch handles missing source context gracefully."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps({"locations": []})
        )

        area_data = {"areaName": "Dark Forest", "areaType": "wilderness"}
        plot_data = {"plotTitle": "Test Plot", "mainObjective": "Explore"}
        module_data = {"moduleName": "Test Module"}
        location_stubs = [{"id": "L001", "name": "Crystal Cave"}]

        with patch(
            "core.generators.location_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.location_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = LocationGenerator()
            gen.generate_location_batch(
                area_data,
                plot_data,
                module_data,
                location_stubs,
                context_header="",
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)

    def test_plot_generator_field_includes_source_lock_context(self):
        """generate_field prompt includes source lock context when present in context dict."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse()

        with patch(
            "core.generators.plot_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.plot_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = PlotGenerator()
            gen.generate_field(
                "plotTitle",
                {"type": "string"},
                {"initialConcept": self._SOURCE_CONTEXT},
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Dark Forest", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_plot_generator_field_missing_context_no_crash(self):
        """generate_field handles missing source context gracefully."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse()

        with patch(
            "core.generators.plot_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.plot_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = PlotGenerator()
            gen.generate_field(
                "plotTitle",
                {"type": "string"},
                {"initialConcept": "A heroic adventure in the dark woods."},
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("dark woods", user_prompt)

    def test_plot_plot_structure_includes_source_lock_context(self):
        """generate_plot_structure prompt includes source lock context when present."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps({"plotPoints": []})
        )

        context = {"module_name": "Test Module", "areas": {}, "locations": {}, "npcs": {}}

        with patch(
            "core.generators.plot_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.plot_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = PlotGenerator()
            gen.generate_plot_structure(
                3,
                context,
                context_header=self._SOURCE_CONTEXT,
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("skull_riddle", user_prompt)
            self.assertIn("Alhoon", user_prompt)
            self.assertIn("canonical_names_locked", user_prompt)

    def test_plot_plot_structure_missing_context_no_crash(self):
        """generate_plot_structure handles missing source context gracefully."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps({"plotPoints": []})
        )

        context = {"module_name": "Test Module", "areas": {}, "locations": {}, "npcs": {}}

        with patch(
            "core.generators.plot_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.plot_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = PlotGenerator()
            gen.generate_plot_structure(
                3,
                context,
                context_header="",
            )

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertNotIn("SOURCE LOCK CONTEXT", user_prompt)

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
        with tempfile.TemporaryDirectory() as tmpdir:
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
        with tempfile.TemporaryDirectory() as tmpdir:
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
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = FakeResponse(
            json.dumps(["Entrance Hall"])
        )

        room_data = [{"id": "L001", "type": "entrance", "connections": ["L002"]}]
        area_context = {
            "module_name": "Test Module",
            "area_name": "Dark Forest",
            "area_type": "wilderness",
            "theme": "heroic fantasy",
            "_source_lock_context": self._SOURCE_CONTEXT,
        }

        with patch(
            "core.generators.area_generator.create_chat_client",
            return_value=mock_client,
        ), patch(
            "core.generators.area_generator.get_model_config",
            return_value={"model": "test-model"},
        ):
            gen = MapLayoutGenerator()
            gen.generate_thematic_names(room_data, area_context)

            call_args = mock_client.chat.completions.create.call_args
            self.assertIsNotNone(call_args)
            user_prompt = call_args[1]["messages"][1]["content"]

            self.assertIn("SOURCE LOCK CONTEXT", user_prompt)
            self.assertIn("SOURCE CONSTRAINTS", user_prompt)
            self.assertIn("Elara", user_prompt)
            self.assertIn("Alhoon", user_prompt)


if __name__ == "__main__":
    unittest.main()
