# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Integrated provider-free and production-boundary checks for Mapping Pilot."""

from __future__ import annotations

import ast
import pathlib
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FORBIDDEN_IMPORTS = {
    "openai", "requests", "httpx", "anthropic", "main", "web",
    "model_config", "config",
}
FIXTURE_IDS = {
    "combat_stage_tavern_zones",
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
}


class MappingPilotBoundaryTests(unittest.TestCase):
    def test_static_sources_are_provider_free_and_project_relative(self) -> None:
        sources = sorted((ROOT / "scripts" / "mapping_pilot").glob("*.py"))
        sources += sorted((ROOT / "scripts").glob("test_mapping_pilot_*.py"))
        self.assertTrue(sources)
        for path in sources:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("/" + "tmp/", source, path.relative_to(ROOT).as_posix())
            tree = ast.parse(source, filename=str(path))
            imported = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(imported & FORBIDDEN_IMPORTS,
                             "%s imports %s at module scope" % (path, sorted(imported & FORBIDDEN_IMPORTS)))

    def test_all_tooling_modules_import_without_runtime_owners(self) -> None:
        modules = sorted("scripts.mapping_pilot." + path.stem for path in
                         (ROOT / "scripts" / "mapping_pilot").glob("*.py")
                         if path.stem != "__init__")
        code = (
            "import importlib, sys; "
            "[importlib.import_module(name) for name in %r]; "
            "bad = sorted(set(sys.modules) & {'main','model_config','config','openai','web.web_interface'}); "
            "print('OFFENDING=' + ','.join(bad)); sys.exit(bool(bad))"
        ) % modules
        code = ("import socket; socket.socket.connect = lambda *a, **k: "
                "(_ for _ in ()).throw(RuntimeError('socket connect prohibited')); " + code)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("socket connect prohibited")):
            result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OFFENDING=", result.stdout)

    def test_seed_suite_covers_all_fixtures_for_both_party_sizes(self) -> None:
        seed_path = ROOT / "scripts" / "test_mapping_pilot_seed.py"
        source = seed_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        planned = next(node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "_PLANNED_ROWS"
                               for target in node.targets))
        covered = set()
        for key in planned.value.keys:
            if isinstance(key, ast.Tuple) and len(key.elts) == 2:
                fixture_node, party_node = key.elts
                if (isinstance(fixture_node, ast.Constant)
                        and isinstance(party_node, ast.Constant)):
                    covered.add((fixture_node.value, party_node.value))
        self.assertEqual(covered, {(fixture, size) for fixture in FIXTURE_IDS
                                    for size in (1, 4)})

    def test_production_boundary_diff(self) -> None:
        try:
            try:
                base_result = subprocess.run(["git", "merge-base", "HEAD", "origin/main"],
                                             cwd=str(ROOT), capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError:
                base_result = subprocess.run(["git", "merge-base", "HEAD", "main"],
                                             cwd=str(ROOT), capture_output=True, text=True, check=True)
            base = base_result.stdout.strip()
            tracked = subprocess.run(["git", "diff", "--name-only", base, "--"],
                                     cwd=str(ROOT), capture_output=True, text=True, check=True)
            untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                       cwd=str(ROOT), capture_output=True, text=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            self.skipTest("git boundary inspection unavailable (origin/main and main merge-base lookup failed): %s" % exc)
        paths = set(tracked.stdout.splitlines()) | set(untracked.stdout.splitlines())
        allowed = (
            "scripts/",
            "openspec/changes/v2-mapping-pilot-tooling/",
            "openspec/changes/v2-mapping-pilot-offline/",
            "openspec/changes/v2-mapping-pilot-execution/",
            "adrs/0034-spatial-authority-and-projections.md",
            "adrs/index.md",
        )
        violations = sorted(path for path in paths if not path.startswith(allowed))
        forbidden = sorted(path for path in paths if path.startswith(("core/", "web/", "modules/", "plans/"))
                           or path in {"main.py", "model_config.py", "config.py"})
        self.assertFalse(violations, "out-of-scope paths: %s" % violations)
        self.assertFalse(forbidden, "production-boundary paths: %s" % forbidden)


if __name__ == "__main__":
    unittest.main()
