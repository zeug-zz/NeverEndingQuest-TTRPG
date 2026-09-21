# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for monster builder output destination handling."""

import contextlib
import io
import shutil
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.generators.monster_builder import (
    _create_argument_parser,
    _resolve_monster_output_path,
    generate_monster,
    main,
)
from utils.module_path_manager import ModulePathManager


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "tmp" / "monster_builder_output_directory_test"


class TestMonsterBuilderOutputDirectory(unittest.TestCase):
    """Explicit staging output and legacy output remain distinct and safe."""

    def tearDown(self):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def test_parser_accepts_explicit_output_directory(self):
        output_root = TEST_ROOT / "staged"
        args = _create_argument_parser().parse_args(
            ["Goblin", "--output-directory", str(output_root)]
        )
        self.assertEqual(args.output_directory, str(output_root))

    def test_parser_accepts_adaptation_safe_output(self):
        args = _create_argument_parser().parse_args(
            ["Goblin", "--adaptation-safe-output"]
        )
        self.assertTrue(args.adaptation_safe_output)

    def test_adaptation_safe_generation_suppresses_raw_ai_response(self):
        sentinel = "RAW_AI_RESPONSE_SENTINEL_FULL_PROMPT"

        class FakeCompletions:
            def create(self, **_kwargs):
                return type(
                    "Response",
                    (),
                    {"choices": [type("Choice", (), {"message": type("Message", (), {"content": sentinel})()})()]},
                )()

        fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()
        output = io.StringIO()
        with patch("core.generators.monster_builder.create_chat_client", return_value=fake_client), patch(
            "core.generators.monster_builder.get_chat_completion_params", return_value={}
        ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = generate_monster(
                "Goblin",
                {"type": "object"},
                adaptation_safe_output=True,
            )

        self.assertIsNone(result)
        self.assertNotIn(sentinel, output.getvalue())

    def test_explicit_output_uses_canonical_slug_under_monsters(self):
        output_root = TEST_ROOT / "staged"
        path_manager = ModulePathManager("Ignored_Module")

        output_path = Path(
            _resolve_monster_output_path(
                "Sir Big-Bellied Night",
                path_manager,
                output_directory=output_root,
            )
        )

        self.assertEqual(
            output_path,
            output_root / "monsters" / "sir_big_bellied_night.json",
        )
        self.assertTrue((output_root / "monsters").is_dir())
        self.assertEqual(output_path.parent.resolve(), (output_root / "monsters").resolve())

    def test_cli_writes_generated_json_under_explicit_output(self):
        output_root = TEST_ROOT / "staged"
        with patch(
            "core.generators.monster_builder.load_schema",
            return_value={"type": "object"},
        ), patch(
            "core.generators.monster_builder.generate_monster",
            return_value={"name": "Goblin"},
        ), patch.object(
            sys,
            "argv",
            [
                "monster_builder.py",
                "Goblin",
                "--module",
                "Ignored_Module",
                "--output-directory",
                str(output_root),
            ],
        ):
            main()

        output_file = output_root / "monsters" / "goblin.json"
        self.assertTrue(output_file.is_file())
        self.assertEqual(output_file.read_text(encoding="utf-8"), '{\n  "name": "Goblin"\n}')

    def test_explicit_output_uses_closure_slug_for_possessive_name(self):
        output_root = TEST_ROOT / "staged"
        path_manager = ModulePathManager("Ignored_Module")

        output_path = Path(
            _resolve_monster_output_path(
                "Simon Vey's Hired Scout",
                path_manager,
                output_directory=output_root,
            )
        )

        self.assertEqual(
            output_path,
            output_root / "monsters" / "simon_veys_hired_scout.json",
        )

    def test_omitted_output_preserves_module_path_manager(self):
        path_manager = ModulePathManager("Legacy_Module")
        expected = path_manager.get_monster_path("Goblin")

        self.assertEqual(
            _resolve_monster_output_path("Goblin", path_manager),
            expected,
        )
        self.assertFalse(TEST_ROOT.exists())

    def test_explicit_monsters_symlink_is_rejected(self):
        output_root = TEST_ROOT / "staged"
        outside_root = TEST_ROOT / "outside"
        (output_root).mkdir(parents=True)
        outside_root.mkdir()
        (output_root / "monsters").symlink_to(outside_root, target_is_directory=True)

        with self.assertRaises(ValueError):
            _resolve_monster_output_path(
                "Goblin",
                ModulePathManager("Ignored_Module"),
                output_directory=output_root,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
