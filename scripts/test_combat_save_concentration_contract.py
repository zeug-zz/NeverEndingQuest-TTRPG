# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - combat save/concentration Contract Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Step 1.1 contract tests for combat-save-concentration-contract.
"""

import os
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


REQUEST_ROLL_ACTION = "requestRoll"
REQUEST_ROLL_TYPES = {
    "saving_throw",
    "ability_check",
    "skill_check",
}
CONCENTRATION_FORMULA = "max(10, floor(damage / 2))"


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


def _resolve_main_or_archive_spec(
    spec_slug,
    change_slug,
    change_root=None,
    repo_root=REPO_ROOT,
    prefer_archive_delta=False,
):
    resolved_root = change_root or _resolve_change_root(change_slug, repo_root)
    archive_spec = os.path.join(resolved_root, "specs", spec_slug, "spec.md")
    if prefer_archive_delta and os.path.isfile(archive_spec):
        return archive_spec

    main_spec = os.path.join(repo_root, "openspec", "specs", spec_slug, "spec.md")
    if os.path.isfile(main_spec):
        return main_spec

    if os.path.isfile(archive_spec):
        return archive_spec
    raise FileNotFoundError(f"OpenSpec capability not found in main or unique change path: {spec_slug}")


class TestOpenSpecArtifactResolution(unittest.TestCase):
    def test_canonical_spec_precedes_archived_delta(self):
        with tempfile.TemporaryDirectory(
            prefix="combat_save_spec_resolution_",
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
            prefix="combat_save_archive_resolution_",
            dir=os.path.join(REPO_ROOT, "tmp"),
        ) as repo_root:
            archive_root = os.path.join(repo_root, "openspec", "changes", "archive")
            os.makedirs(os.path.join(archive_root, "2026-01-first-combat-save-change"))
            os.makedirs(os.path.join(archive_root, "2026-02-second-combat-save-change"))
            with self.assertRaisesRegex(AssertionError, "Ambiguous archived OpenSpec change"):
                _resolve_change_root("combat-save-change", repo_root)


class TestCombatSaveConcentrationOpenSpecContracts(unittest.TestCase):
    """Lock OpenSpec artifacts for combat requestRoll and concentration contracts."""

    @classmethod
    def setUpClass(cls):
        change_root = _resolve_change_root("combat-save-concentration-contract")
        cls.paths = {
            "proposal": os.path.join(change_root, "proposal.md"),
            "design": os.path.join(change_root, "design.md"),
            "tasks": os.path.join(change_root, "tasks.md"),
            "request_roll_spec": _resolve_main_or_archive_spec(
                "tt-combat-request-roll-routing",
                "combat-save-concentration-contract",
                change_root,
                prefer_archive_delta=True,
            ),
            "concentration_spec": _resolve_main_or_archive_spec(
                "tt-combat-concentration-request-dc",
                "combat-save-concentration-contract",
                change_root,
            ),
        }
        cls.content = {}
        for key, path in cls.paths.items():
            with open(path, "r", encoding="utf-8") as file_handle:
                cls.content[key] = file_handle.read()

    def test_request_roll_preference_documented(self):
        self.assertIn("prefer `requestRoll`", self.content["proposal"])
        self.assertIn("prefer `requestRoll`", self.content["design"])
        self.assertIn("prefer `requestRoll`", self.content["request_roll_spec"])

    def test_stop_after_request_semantics_documented(self):
        self.assertIn("stop-after-request semantics", self.content["proposal"])
        self.assertIn("stop after issuing the request", self.content["design"])
        self.assertIn("same response SHALL stop after issuing the request", self.content["request_roll_spec"])
        self.assertIn("SHALL stop after the request", self.content["concentration_spec"])

    def test_no_contingent_outcomes_documented(self):
        self.assertIn("does not narrate contingent", self.content["proposal"])
        self.assertIn("SHALL NOT narrate contingent success/failure", self.content["design"])
        self.assertIn("SHALL NOT narrate contingent success or failure", self.content["request_roll_spec"])
        self.assertIn("SHALL NOT narrate contingent save success or failure", self.content["concentration_spec"])

    def test_prose_compatibility_documented(self):
        self.assertIn("prose-only compatibility", self.content["proposal"])
        self.assertIn("Prose-only save/check requests SHALL remain compatibility-valid", self.content["design"])
        self.assertIn("preserve prose-only", self.content["request_roll_spec"])
        self.assertIn("prose fallback", self.content["concentration_spec"])
        self.assertIn("explicit prose-compatibility fallback", self.content["tasks"])

    def test_concentration_formula_documented(self):
        self.assertIn(CONCENTRATION_FORMULA, self.content["proposal"])
        self.assertIn(CONCENTRATION_FORMULA, self.content["design"])
        self.assertIn(CONCENTRATION_FORMULA, self.content["concentration_spec"])


class TestCombatSaveConcentrationRuntimeSourceContracts(unittest.TestCase):
    """Lock current runtime scaffolding presence for combat save/check contracts."""

    @classmethod
    def setUpClass(cls):
        cls.paths = {
            "action_handler": os.path.join(REPO_ROOT, "core", "ai", "action_handler.py"),
            "combat_manager": os.path.join(REPO_ROOT, "core", "combat", "combat_manager.py"),
        }
        cls.content = {}
        for key, path in cls.paths.items():
            with open(path, "r", encoding="utf-8") as file_handle:
                cls.content[key] = file_handle.read()

    def test_action_handler_has_request_roll_branch(self):
        source = self.content["action_handler"]
        self.assertIn('ACTION_REQUEST_ROLL = "requestRoll"', source)
        self.assertIn("elif action_type == ACTION_REQUEST_ROLL", source)
        self.assertIn("validate_request_roll_parameters(parameters)", source)

    def test_action_handler_references_concentration_dc_helper(self):
        source = self.content["action_handler"]
        self.assertIn("calculate_concentration_dc", source)
        self.assertIn('"concentration" in reason_text.lower()', source)
        self.assertIn("expected_dc = calculate_concentration_dc(damage_value)", source)

    def test_action_handler_request_roll_path_is_scaffold_only(self):
        source = self.content["action_handler"]
        self.assertIn("Runtime behavior remains narration-driven in this phase", source)
        self.assertIn("validate payload shape", source)

    def test_combat_manager_has_request_roll_helpers(self):
        source = self.content["combat_manager"]
        self.assertIn("def build_request_roll_action(", source)
        self.assertIn('"action": "requestRoll"', source)
        self.assertIn("def get_concentration_request_dc(damage_taken: int) -> int", source)
        self.assertIn("return calculate_concentration_dc(damage_taken)", source)


class TestCombatSaveConcentrationCompatibilityContracts(unittest.TestCase):
    """Lock compatibility-oriented behavior for request payloads and formula."""

    def test_request_roll_types_locked(self):
        self.assertEqual(
            REQUEST_ROLL_TYPES,
            {
                "saving_throw",
                "ability_check",
                "skill_check",
            },
        )

    def test_request_roll_payload_validator_accepts_saving_throw(self):
        from utils.save_roll_contract import validate_request_roll_parameters

        is_valid, error_message = validate_request_roll_parameters(
            {
                "characterName": "Acheron",
                "rollType": "saving_throw",
                "dc": 13,
                "reason": "Maintain concentration after taking damage.",
                "ability": "constitution",
                "advantage": "normal",
            }
        )
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")

    def test_request_roll_payload_validator_accepts_skill_check(self):
        from utils.save_roll_contract import validate_request_roll_parameters

        is_valid, error_message = validate_request_roll_parameters(
            {
                "characterName": "Merisiel",
                "rollType": "skill_check",
                "dc": 15,
                "reason": "Spot weak cover in the battlefield.",
                "skill": "perception",
            }
        )
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")

    def test_concentration_formula_helper_contract(self):
        from utils.save_roll_contract import calculate_concentration_dc

        self.assertEqual(calculate_concentration_dc(1), 10)
        self.assertEqual(calculate_concentration_dc(19), 10)
        self.assertEqual(calculate_concentration_dc(23), 11)


class TestCombatConcentrationSpecificContracts(unittest.TestCase):
    """Lock concentration-specific contract expectations for Step 1.2."""

    @classmethod
    def setUpClass(cls):
        change_root = _resolve_change_root("combat-save-concentration-contract")
        cls.concentration_spec_path = _resolve_main_or_archive_spec(
            "tt-combat-concentration-request-dc",
            "combat-save-concentration-contract",
            change_root,
        )
        cls.request_roll_spec_path = _resolve_main_or_archive_spec(
            "tt-combat-request-roll-routing",
            "combat-save-concentration-contract",
            change_root,
        )
        cls.design_path = os.path.join(change_root, "design.md")

        with open(cls.concentration_spec_path, "r", encoding="utf-8") as file_handle:
            cls.concentration_spec = file_handle.read()
        with open(cls.request_roll_spec_path, "r", encoding="utf-8") as file_handle:
            cls.request_roll_spec = file_handle.read()
        with open(cls.design_path, "r", encoding="utf-8") as file_handle:
            cls.design = file_handle.read()

    def test_concentration_open_spec_low_and_high_damage_scenarios_locked(self):
        self.assertIn("less than 20 damage", self.concentration_spec)
        self.assertIn("SHALL use DC 10", self.concentration_spec)
        self.assertIn("deals 23 damage", self.concentration_spec)
        self.assertIn("SHALL use DC 11", self.concentration_spec)

    def test_concentration_open_spec_pause_only_and_no_contingent_outcome_locked(self):
        self.assertIn("SHALL stop after the request", self.concentration_spec)
        self.assertIn("SHALL NOT narrate contingent save success or failure", self.concentration_spec)
        self.assertIn("SHALL NOT narrate contingent success or failure", self.request_roll_spec)

    def test_concentration_open_spec_prose_fallback_locked(self):
        self.assertIn("Prose concentration request remains compatibility-valid", self.concentration_spec)
        self.assertIn("Prose-only save/check requests SHALL remain compatibility-valid", self.design)

    def test_concentration_formula_helper_boundary_values(self):
        from utils.save_roll_contract import calculate_concentration_dc

        self.assertEqual(calculate_concentration_dc(20), 10)
        self.assertEqual(calculate_concentration_dc(21), 10)
        self.assertEqual(calculate_concentration_dc(22), 11)

    def test_request_roll_validator_accepts_concentration_saving_throw_payload(self):
        from utils.save_roll_contract import validate_request_roll_parameters

        is_valid, error_message = validate_request_roll_parameters(
            {
                "characterName": "Acheron",
                "rollType": "saving_throw",
                "dc": 11,
                "reason": "Concentration save after taking 23 damage.",
                "ability": "constitution",
            }
        )
        self.assertTrue(is_valid)
        self.assertEqual(error_message, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
