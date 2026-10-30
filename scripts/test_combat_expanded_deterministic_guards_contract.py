# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - combat expanded deterministic guards Contract Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Steps 1.1-1.4 contract tests for combat-expanded-deterministic-guards.
"""

import os
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


MECHANICS_CONTRADICTION_CLASSES = {
    "unconscious vs HP contradictions",
    "ammo underflow for explicit ranged-ammo spend/use",
    "spell-slot underflow for explicit combat casting/spend language",
}

PHASE_INTEGRITY_CONTRADICTION_CLASSES = {
    "illegal action by forbidden phase actor",
    "illegal stop mid enemy batch",
    "illegal exit while hostiles remain",
    "illegal round increment before all PCs acted",
}


def _resolve_change_root(change_slug, repo_root=REPO_ROOT):
    live_root = os.path.join(repo_root, "openspec", "changes", change_slug)
    if os.path.isdir(live_root):
        return live_root

    archive_root = os.path.join(repo_root, "openspec", "changes", "archive")
    matches = sorted(
        os.path.join(archive_root, name)
        for name in os.listdir(archive_root)
        if name.endswith(f"-{change_slug}")
        and os.path.isdir(os.path.join(archive_root, name))
    ) if os.path.isdir(archive_root) else []
    if len(matches) > 1:
        raise AssertionError(f"Ambiguous archived OpenSpec change {change_slug}: {matches}")
    if not matches:
        raise FileNotFoundError(f"OpenSpec change not found (live or archive): {change_slug}")
    return matches[0]


def _resolve_main_or_archive_spec(spec_slug, change_slug, change_root=None, repo_root=REPO_ROOT):
    main_spec = os.path.join(repo_root, "openspec", "specs", spec_slug, "spec.md")
    if os.path.isfile(main_spec):
        return main_spec

    resolved_root = change_root or _resolve_change_root(change_slug, repo_root)
    archive_spec = os.path.join(resolved_root, "specs", spec_slug, "spec.md")
    if os.path.isfile(archive_spec):
        return archive_spec
    raise FileNotFoundError(f"OpenSpec capability not found in main or unique change path: {spec_slug}")


class TestOpenSpecArtifactResolution(unittest.TestCase):
    def test_canonical_spec_precedes_archived_delta(self):
        with tempfile.TemporaryDirectory(
            prefix="combat_guards_spec_resolution_",
            dir=os.path.join(REPO_ROOT, "tmp"),
        ) as repo_root:
            main_spec = os.path.join(repo_root, "openspec", "specs", "capability", "spec.md")
            delta_spec = os.path.join(repo_root, "archive", "specs", "capability", "spec.md")
            os.makedirs(os.path.dirname(main_spec), exist_ok=True)
            os.makedirs(os.path.dirname(delta_spec), exist_ok=True)
            with open(main_spec, "w", encoding="utf-8") as handle:
                handle.write("canonical")
            with open(delta_spec, "w", encoding="utf-8") as handle:
                handle.write("delta")

            self.assertEqual(
                _resolve_main_or_archive_spec(
                    "capability", "change", os.path.join(repo_root, "archive"), repo_root
                ),
                main_spec,
            )

    def test_ambiguous_archive_roots_fail_closed(self):
        with tempfile.TemporaryDirectory(
            prefix="combat_guards_archive_resolution_",
            dir=os.path.join(REPO_ROOT, "tmp"),
        ) as repo_root:
            archive_root = os.path.join(repo_root, "openspec", "changes", "archive")
            os.makedirs(os.path.join(archive_root, "2026-01-first-combat-guards-change"))
            os.makedirs(os.path.join(archive_root, "2026-02-second-combat-guards-change"))
            with self.assertRaisesRegex(AssertionError, "Ambiguous archived OpenSpec change"):
                _resolve_change_root("combat-guards-change", repo_root)


class TestCombatExpandedGuardsOpenSpecContracts(unittest.TestCase):
    """Lock OpenSpec artifacts for expanded deterministic combat guards."""

    @classmethod
    def setUpClass(cls):
        change_root = _resolve_change_root("combat-expanded-deterministic-guards")
        cls.paths = {
            "proposal": os.path.join(change_root, "proposal.md"),
            "design": os.path.join(change_root, "design.md"),
            "tasks": os.path.join(change_root, "tasks.md"),
            "mechanics_spec": _resolve_main_or_archive_spec(
                "tt-combat-mechanics-contradiction-guards",
                "combat-expanded-deterministic-guards",
                change_root,
            ),
            "phase_spec": _resolve_main_or_archive_spec(
                "tt-combat-phase-integrity-guards",
                "combat-expanded-deterministic-guards",
                change_root,
            ),
        }

        cls.content = {}
        for key, path in cls.paths.items():
            with open(path, "r", encoding="utf-8") as file_handle:
                cls.content[key] = file_handle.read()

    def test_tasks_cover_steps_1_1_to_1_4(self):
        tasks_text = self.content["tasks"]
        self.assertIn("1.1 Add focused combat contract tests", tasks_text)
        self.assertIn("1.2 Add contract coverage for explicit HP/unconscious", tasks_text)
        self.assertIn("1.3 Add contract coverage for forbidden phase actor", tasks_text)
        self.assertIn("1.4 Add fail-open contract coverage", tasks_text)

    def test_proposal_locks_explicit_and_bounded_scope(self):
        proposal_text = self.content["proposal"]
        self.assertIn("deterministic combat guards for explicit contradictions only", proposal_text)
        self.assertIn("fail-open behavior for ambiguous or unparseable combat text", proposal_text)
        self.assertIn("`updateEncounter.ops`", proposal_text)
        self.assertIn("roll resolution or dice-engine behavior", proposal_text)

    def test_design_locks_fail_open_and_no_broad_nlp(self):
        design_text = self.content["design"]
        self.assertIn("Ambiguity fails open", design_text)
        self.assertIn("No roll resolution engine", design_text)
        self.assertIn("No style/tactics validation", design_text)


class TestCombatMechanicsContradictionLocks(unittest.TestCase):
    """Lock mechanics contradiction classes for deterministic guard expansion."""

    @classmethod
    def setUpClass(cls):
        change_root = _resolve_change_root("combat-expanded-deterministic-guards")
        spec_path = _resolve_main_or_archive_spec(
            "tt-combat-mechanics-contradiction-guards",
            "combat-expanded-deterministic-guards",
            change_root,
        )
        design_path = os.path.join(change_root, "design.md")
        with open(spec_path, "r", encoding="utf-8") as file_handle:
            cls.spec_text = file_handle.read()
        with open(design_path, "r", encoding="utf-8") as file_handle:
            cls.design_text = file_handle.read()

    def test_mechanics_contradiction_classes_locked_in_design(self):
        for contradiction_class in sorted(MECHANICS_CONTRADICTION_CLASSES):
            self.assertIn(contradiction_class, self.design_text)

    def test_mechanics_contradiction_scenarios_locked_in_spec(self):
        self.assertIn("Above-zero HP contradicts unconscious mechanical state", self.spec_text)
        self.assertIn("Explicit ranged-ammo spend underflows tracked ammunition", self.spec_text)
        self.assertIn("Explicit leveled combat cast underflows known slots", self.spec_text)

    def test_mechanics_fail_open_scenarios_locked_in_spec(self):
        self.assertIn("Combat deterministic mechanics guards SHALL fail open on ambiguity", self.spec_text)
        self.assertIn("SHALL NOT reject on that basis alone", self.spec_text)
        self.assertIn("SHALL defer to the existing validation path", self.spec_text)


class TestCombatPhaseIntegrityLocks(unittest.TestCase):
    """Lock phase-integrity contradiction classes for deterministic guard expansion."""

    @classmethod
    def setUpClass(cls):
        change_root = _resolve_change_root("combat-expanded-deterministic-guards")
        spec_path = _resolve_main_or_archive_spec(
            "tt-combat-phase-integrity-guards",
            "combat-expanded-deterministic-guards",
            change_root,
        )
        design_path = os.path.join(change_root, "design.md")
        with open(spec_path, "r", encoding="utf-8") as file_handle:
            cls.spec_text = file_handle.read()
        with open(design_path, "r", encoding="utf-8") as file_handle:
            cls.design_text = file_handle.read()

    def test_phase_integrity_classes_locked_in_design(self):
        for contradiction_class in sorted(PHASE_INTEGRITY_CONTRADICTION_CLASSES):
            self.assertIn(contradiction_class, self.design_text)

    def test_phase_integrity_scenarios_locked_in_spec(self):
        self.assertIn("Forbidden phase actor attempts an illegal action", self.spec_text)
        self.assertIn("Enemy batch stops before the next legal PC boundary", self.spec_text)
        self.assertIn("Combat exits while hostiles remain", self.spec_text)
        self.assertIn("Round increments before all required PCs acted", self.spec_text)

    def test_phase_integrity_fail_open_scenario_locked_in_spec(self):
        self.assertIn("Combat phase-integrity guards SHALL fail open on non-authoritative ambiguity", self.spec_text)
        self.assertIn("SHALL NOT reject solely from inferred phase assumptions", self.spec_text)


class TestCombatExpandedGuardsRuntimeTouchpoints(unittest.TestCase):
    """Lock source touchpoints expected for later deterministic guard implementation."""

    @classmethod
    def setUpClass(cls):
        cls.paths = {
            "combat_manager": os.path.join(REPO_ROOT, "core", "combat", "combat_manager.py"),
            "combat_prompts": os.path.join(REPO_ROOT, "core", "combat", "prompts.py"),
            "combat_validation": os.path.join(REPO_ROOT, "core", "combat", "validation.py"),
            "action_handler": os.path.join(REPO_ROOT, "core", "ai", "action_handler.py"),
        }
        cls.content = {}
        for key, path in cls.paths.items():
            with open(path, "r", encoding="utf-8") as file_handle:
                cls.content[key] = file_handle.read()

    def test_runtime_touchpoint_files_exist(self):
        for path in self.paths.values():
            self.assertTrue(os.path.exists(path), msg=f"Missing expected runtime file: {path}")

    def test_combat_manager_contains_phase_integrity_surfaces(self):
        prompt_source = self.content["combat_prompts"]
        validation_source = self.content["combat_validation"]
        self.assertIn("CURRENT_PHASE", prompt_source)
        self.assertIn("PC_PHASE_COMPLETE", prompt_source)
        self.assertIn("PENDING_ENEMIES", prompt_source)
        self.assertIn("All monsters have been defeated", prompt_source)
        self.assertIn("Include exit action", prompt_source)
        self.assertIn("You CANNOT end the round until ALL PCs have taken their turns", validation_source)

    def test_combat_manager_wires_phase_integrity_precheck(self):
        manager_source = self.content["combat_manager"]
        validation_source = self.content["combat_validation"]
        self.assertIn("phase_precheck=validate_combat_phase_integrity_precheck", manager_source)
        self.assertIn("def _derive_authoritative_phase_state(", validation_source)
        self.assertIn("forbidden_actors = multi_pc_manager.get_forbidden_actors()", validation_source)
        self.assertIn("pending_enemies = multi_pc_manager.get_remaining_enemies_for_round()", validation_source)
        self.assertIn("pc_phase_complete = multi_pc_manager.pc_phase_complete", validation_source)
        self.assertIn(
            'current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))',
            validation_source,
        )
        self.assertIn('"forbidden_actors": forbidden_actors', validation_source)
        self.assertIn('"pending_enemies": pending_enemies', validation_source)
        self.assertIn('"pc_phase_complete": pc_phase_complete', validation_source)
        self.assertIn('"current_round": current_round', validation_source)

    def test_action_handler_contains_narrow_action_contract_surfaces(self):
        source = self.content["action_handler"]
        self.assertIn('ACTION_REQUEST_ROLL = "requestRoll"', source)
        self.assertIn('ACTION_UPDATE_ENCOUNTER = "updateEncounter"', source)
        self.assertIn("validate_request_roll_parameters(parameters)", source)
        self.assertIn("encounter_id = parameters.get(\"encounterId\")", source)
        self.assertIn("changes = parameters.get(\"changes\")", source)

    def test_request_roll_runtime_boundary_remains_scaffold_only(self):
        source = self.content["action_handler"]
        self.assertIn("Runtime behavior remains narration-driven in this phase", source)
        self.assertIn("validate payload shape", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
