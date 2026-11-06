# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free parity and confinement tests for mapping-pilot state hashes."""

from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot import launcher, row_runner
from scripts.mapping_pilot.manifest import PROJECT_ROOT


class MappingPilotLauncherHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path("tmp") / ("mapping_pilot_launcher_" + uuid.uuid4().hex)

    def tearDown(self) -> None:
        shutil.rmtree(PROJECT_ROOT / self.scratch, ignore_errors=True)

    def _make_sandbox(self, name: str) -> tuple[Path, Path, Path]:
        owner = PROJECT_ROOT / self.scratch / name
        root = owner / "tmp" / "combat_capture"
        (root / "characters").mkdir(parents=True)
        (root / "modules" / "Mapping_Pilot_Arena" / "areas").mkdir(parents=True)
        (root / "modules" / "encounters").mkdir(parents=True)
        (root / "encounters").mkdir(parents=True)
        (root / "party_tracker.json").write_text("{}", encoding="ascii")
        (root / "characters" / "acheron.json").write_text(
            '{"name":"Acheron"}', encoding="ascii"
        )
        (root / "modules" / "Mapping_Pilot_Arena" / "areas" / "MPA001.json").write_text(
            '{"areaId":"MPA001"}', encoding="ascii"
        )
        actual_encounter = (
            root
            / "modules"
            / "encounters"
            / "encounter_mapping_pilot_combat.json"
        )
        actual_encounter.write_text('{"round":1}', encoding="ascii")
        (root / "encounters" / "legacy.json").write_text(
            '{"legacy":true}', encoding="ascii"
        )
        return owner, root, actual_encounter

    def test_hashes_match_and_mutated_canonical_encounter_invalidates_checkpoint(self) -> None:
        owner, root, encounter = self._make_sandbox("parity")
        with mock.patch.object(row_runner, "PROJECT_ROOT", owner):
            before = row_runner.hash_canonical_sandbox_state()
            self.assertIn(
                "modules/encounters/encounter_mapping_pilot_combat.json",
                before["files"],
            )
            self.assertIn("encounters/legacy.json", before["files"])
            self.assertEqual(
                before["sha256"], launcher._canonical_state_sha256(root)
            )

            encounter.write_text('{"round":2}', encoding="ascii")
            after = row_runner.hash_canonical_sandbox_state()
            self.assertNotEqual(before["sha256"], after["sha256"])
            self.assertNotEqual(
                before["sha256"], launcher._canonical_state_sha256(root)
            )
            with self.assertRaisesRegex(ValueError, "checkpoint hash does not match"):
                launcher._validate_resume_checkpoint(
                    root,
                    fixture_id="interior_tavern",
                    mapping={},
                    tracker={},
                    world={},
                    runtime_to_source={},
                    resume_checkpoint_sha256=before["sha256"],
                )

    def test_hashers_reject_symlinked_canonical_encounter_paths(self) -> None:
        for name, symlink_kind in (
            ("directory", "directory"),
            ("file", "file"),
        ):
            with self.subTest(symlink_kind=symlink_kind):
                owner, root, encounter = self._make_sandbox("symlink-" + name)
                external = PROJECT_ROOT / self.scratch / ("outside-" + name)
                if symlink_kind == "directory":
                    shutil.rmtree(root / "modules" / "encounters")
                    external.mkdir(parents=True)
                    (root / "modules" / "encounters").symlink_to(
                        external, target_is_directory=True
                    )
                else:
                    external.parent.mkdir(parents=True, exist_ok=True)
                    external.write_text('{"round":1}', encoding="ascii")
                    encounter.unlink()
                    encounter.symlink_to(external)

                with mock.patch.object(row_runner, "PROJECT_ROOT", owner):
                    with self.assertRaises(row_runner.RowExecutionError):
                        row_runner.hash_canonical_sandbox_state()
                with self.assertRaisesRegex(ValueError, "sandbox path is unsafe"):
                    launcher._canonical_state_sha256(root)


if __name__ == "__main__":
    unittest.main()
