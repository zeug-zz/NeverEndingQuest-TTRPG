# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free parity tests for combat narration ownership."""

import ast
import builtins
import hashlib
import os
import pathlib
import socket
import unittest
from unittest import mock

from core.combat import narration
from core.combat.multi_pc import manager as multi_pc_manager
from utils import combat_pc_action_parser as parser


class ForbiddenSideEffect(BaseException):
    """Fatal guard used to catch writes or network activity in these tests."""


def _forbidden(*args, **kwargs):
    raise ForbiddenSideEffect("unexpected test side effect")


def _guarded_open(path, mode="r", *args, **kwargs):
    if any(flag in mode for flag in "wax+"):
        return _forbidden(path, mode, *args, **kwargs)
    return _real_open(path, mode, *args, **kwargs)


_real_open = builtins.open


class TestCombatNarrationParity(unittest.TestCase):
    def setUp(self):
        self._guards = [
            mock.patch.object(builtins, "open", side_effect=_guarded_open),
            mock.patch.object(os, "open", side_effect=_forbidden),
            mock.patch.object(os, "remove", side_effect=_forbidden),
            mock.patch.object(os, "rename", side_effect=_forbidden),
            mock.patch.object(os, "replace", side_effect=_forbidden),
            mock.patch.object(os, "mkdir", side_effect=_forbidden),
            mock.patch.object(os, "makedirs", side_effect=_forbidden),
            mock.patch.object(pathlib.Path, "write_text", side_effect=_forbidden),
            mock.patch.object(pathlib.Path, "write_bytes", side_effect=_forbidden),
            mock.patch.object(pathlib.Path, "unlink", side_effect=_forbidden),
            mock.patch.object(pathlib.Path, "mkdir", side_effect=_forbidden),
            mock.patch.object(pathlib.Path, "touch", side_effect=_forbidden),
            mock.patch.object(socket, "socket", side_effect=_forbidden),
        ]
        for guard in self._guards:
            guard.start()

    def tearDown(self):
        for guard in reversed(self._guards):
            guard.stop()

    def test_shared_selector_preserves_legacy_seed_and_order_contract(self):
        templates = ["first", "second", "third"]
        seed_parts = [None, 0, False, "\u00e9"]
        seed = "|".join(str(part or "") for part in seed_parts)
        old_index = hashlib.sha1(seed.encode("utf-8")).digest()[0] % len(templates)
        self.assertEqual(narration.select_deterministic_template(seed_parts, templates),
                         templates[old_index])
        self.assertEqual(narration.select_deterministic_template([], []), "")
        empty_seed_index = hashlib.sha1(b"").digest()[0] % len(templates)
        self.assertEqual(narration.select_deterministic_template([], templates), templates[empty_seed_index])

    def test_multi_pc_facade_uses_shared_chooser_and_keeps_private_patch_point(self):
        with mock.patch.object(narration, "select_deterministic_template", return_value="shared") as chooser:
            result = multi_pc_manager._build_fast_path_narration(
                "attack_miss", "Acheron", "Goblin", weapon_name="axe", roll=9, ac=15
            )
        self.assertEqual(result, "shared")
        chooser.assert_called_once()
        self.assertEqual(
            multi_pc_manager._build_fast_path_narration(
                "attack_miss", "Acheron", "Goblin", weapon_name="axe", roll=9, ac=15
            ),
            "Acheron's axe cuts empty air as Goblin slips just outside the strike.",
        )
        with mock.patch.object(multi_pc_manager, "_select_deterministic_template", return_value="patched"):
            self.assertEqual(
                multi_pc_manager._build_fast_path_narration(
                    "attack_miss", "Acheron", "Goblin", weapon_name="axe", roll=9, ac=15
                ),
                "patched",
            )

    def test_natural_language_parser_uses_shared_chooser_and_keeps_private_patch_point(self):
        encounter = {"creatures": [{"name": "Goblin", "type": "enemy", "armorClass": 15}]}
        party = {"partyMembers": ["Acheron"]}
        with mock.patch.object(narration, "select_deterministic_template", return_value="shared") as chooser:
            result = parser.parse_pc_phase_action(
                "attack goblin roll 9 with axe", encounter, party, "Acheron"
            )
        self.assertEqual(result["spoken_narration"], "Dungeon Master: shared")
        chooser.assert_called_once()
        with mock.patch.object(parser, "_pick_template", return_value="patched"):
            parsed = parser.parse_pc_phase_action(
                "attack goblin roll 9 with axe",
                encounter,
                party,
                "Acheron",
            )
        self.assertEqual(parsed["spoken_narration"], "Dungeon Master: patched")

    def test_multi_pc_attack_and_damage_output_matches_legacy_templates(self):
        self.assertEqual(
            multi_pc_manager._build_fast_path_narration(
                "attack_miss", "Acheron", "Goblin", weapon_name="axe", roll=9, ac=15
            ),
            "Acheron's axe cuts empty air as Goblin slips just outside the strike.",
        )
        self.assertEqual(
            multi_pc_manager._build_fast_path_narration(
                "damage", "Acheron", "Goblin", weapon_name="axe", amount=5,
                hp_before=7, hp_after=2, status_text="alive",
            ),
            "Goblin reels under Acheron's blow, its defense breaking for a dangerous moment.",
        )

    def test_parser_magic_missile_healing_and_movement_narration_parity(self):
        encounter = {
            "creatures": [
                {"name": "Goblin", "type": "enemy", "armorClass": 15,
                 "currentHitPoints": 7, "maxHitPoints": 7, "status": "alive"},
                {"name": "Merisiel", "type": "player", "armorClass": 14,
                 "currentHitPoints": 6, "maxHitPoints": 20, "status": "alive"},
            ]
        }
        party = {"partyMembers": ["Acheron", "Merisiel"], "active_character": "Acheron"}
        casting_state = {"spellcasting": {"spellSlots": {"level1": {"current": 1, "max": 1}}}}
        with mock.patch.object(parser, "get_character_state", return_value=casting_state):
            missile = parser.parse_pc_phase_action(
                "Magic Missile, 5 to Goblin", encounter, party, "Acheron"
            )
            healing = parser.parse_pc_phase_action(
                "heal Merisiel for 8", encounter, party, "Acheron"
            )
            movement = parser.parse_pc_phase_action(
                "move north", encounter, party, "Acheron"
            )
        self.assertEqual(
            missile["spoken_narration"],
            "Dungeon Master: Acheron speaks the incantation, and shimmering missiles race unerringly home.",
        )
        self.assertEqual(
            healing["spoken_narration"],
            "Dungeon Master: A warm radiance flows from Acheron into Merisiel, mending injuries.",
        )
        self.assertEqual(movement["spoken_narration"], "Dungeon Master: Acheron move north.")

        miss = parser.parse_pc_phase_action(
            "attack goblin roll 9 with axe", encounter, party, "Acheron"
        )
        self.assertEqual(
            miss["spoken_narration"],
            "Dungeon Master: Acheron's attack cuts empty air as Goblin slips just outside the strike.",
        )

    def test_publication_emits_legacy_line_then_flushes(self):
        events = []
        narration.publish_combat_narration(
            "The line is unchanged.",
            emit=lambda text: events.append(("emit", text)),
            flush=lambda: events.append(("flush", None)),
        )
        self.assertEqual(events, [
            ("emit", "Dungeon Master: The line is unchanged."),
            ("flush", None),
        ])

    def test_committed_publication_correlates_privately_without_payload_change(self):
        events = []
        observations = []
        applied_id = "sha256:" + "a" * 64
        with mock.patch(
            "utils.combat_latency_trace.trace_combat_observation",
            side_effect=lambda name, **fields: observations.append((name, fields)),
        ):
            published_id = narration.publish_combat_narration(
                "The line is unchanged.",
                applied_id=applied_id,
                emit=lambda text: events.append(("emit", text)),
                flush=lambda: events.append(("flush", None)),
            )

        self.assertEqual(published_id, applied_id)
        self.assertEqual(events, [
            ("emit", "Dungeon Master: The line is unchanged."),
            ("flush", None),
        ])
        self.assertEqual(observations, [(
            "combat_turn_success_publication", {"applied_id": applied_id},
        )])

    def test_owner_publishes_correlated_narration_after_commit_and_sync(self):
        source = pathlib.Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal"
        )
        loops = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.While)
            and isinstance(node.test, ast.Constant)
            and node.test.value is True
            and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "run_combat_provider_retry_stage"
                for call in ast.walk(node)
            )
        ]
        self.assertEqual(len(loops), 1, "identify exactly one normal turn loop by its retry-stage call")
        normal_loop = loops[0]
        calls_by_name = {}
        for node in ast.walk(normal_loop):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls_by_name.setdefault(node.func.id, []).append(node)

        expected_calls = (
            "run_combat_provider_retry_stage",
            "process_combat_action_batch",
            "stage_combat_turn_snapshot",
            "_commit_normal_combat_turn",
            "sync_committed_combat_turn",
            "publish_combat_narration",
        )
        for name in expected_calls:
            self.assertEqual(len(calls_by_name.get(name, [])), 1, f"normal turn must call {name} once")

        retry_call = calls_by_name["run_combat_provider_retry_stage"][0]
        round_call = calls_by_name["stage_combat_turn_snapshot"][0]
        publish_call = calls_by_name["publish_combat_narration"][0]
        batch_call = calls_by_name["process_combat_action_batch"][0]
        consolidated_call = calls_by_name["_commit_normal_combat_turn"][0]
        self.assertTrue(publish_call.args and isinstance(publish_call.args[0], ast.Name))
        self.assertEqual(publish_call.args[0].id, "narration")
        keywords = {item.arg: item.value for item in publish_call.keywords}
        self.assertIsInstance(keywords.get("emit"), ast.Name)
        self.assertEqual(keywords["emit"].id, "print")
        self.assertEqual(ast.unparse(keywords["flush"]), "sys.stdout.flush")
        self.assertEqual(ast.unparse(keywords["applied_id"]), "turn_commit.applied_id")

        ordered_lines = [
            retry_call.lineno,
            batch_call.lineno,
            round_call.lineno,
            consolidated_call.lineno,
            calls_by_name["sync_committed_combat_turn"][0].lineno,
            publish_call.lineno,
        ]
        self.assertEqual(ordered_lines, sorted(ordered_lines))
        self.assertNotIn("def publish_final_narration", source)


if __name__ == "__main__":
    unittest.main()
