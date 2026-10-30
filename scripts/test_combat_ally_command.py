# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for private, non-action /cmd directives."""

import copy
import unittest
from types import SimpleNamespace
from unittest import mock

import model_config
from core.combat.ally_controller import (
    AllyActorMenu,
    AllyMenus,
    build_ally_directive_history_record,
    build_ally_perception_projection_from_history,
    latest_ally_directives_from_history,
    parse_ally_directive_command,
)
from core.combat.commands import FastCommandIO, run_fast_commands_stage
from core.combat.enemy_resolution import CombatantIdentity
from core.combat.turn_commit import (
    COMBAT_ALLY_DIRECTIVE_HISTORY_KEY,
    conversation_history_for_prompt,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase


def _encounter():
    return {
        "encounterId": "ally-command-encounter",
        "creatures": [
            {"name": "Serah", "type": "npc", "currentHitPoints": 12, "status": "alive"},
            {"name": "Serah Vale", "type": "npc", "currentHitPoints": 9, "status": "alive"},
            {"name": "Downed Serah", "type": "npc", "currentHitPoints": 0, "status": "unconscious"},
            {"name": "Goblin", "type": "enemy", "currentHitPoints": 7, "status": "alive"},
        ],
    }


class _Manager:
    current_pc_name = "Acheron"
    combat_phase = "PC_PHASE"
    pc_phase_complete = False

    def __init__(self):
        self.command_calls = []
        self.end_calls = 0

    def handle_combat_command(self, command, *_args, **_kwargs):
        self.command_calls.append(command)
        return None, None, None, False

    def force_end_pc_phase(self):
        self.end_calls += 1
        self.pc_phase_complete = True

    def get_remaining_enemies_for_round(self):
        return ["Goblin"]

    def set_current_pc(self, _name):
        return None


class CombatAllyCommandTests(ProviderFreeTestCase):
    def _run_command(
        self,
        command,
        *,
        encounter=None,
        encounter_id="ally-command-encounter",
        active_encounter_id="ally-command-encounter",
    ):
        encounter = _encounter() if encounter is None else encounter
        history = [{"role": "system", "content": "unchanged system bytes"}]
        original_history = copy.deepcopy(history)
        original_encounter = copy.deepcopy(encounter)
        manager = _Manager()
        events = []
        writes = []
        io = FastCommandIO(
            emit=lambda message: events.append(("emit", message)),
            flush=lambda: events.append(("flush",)),
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            save_json=lambda path, payload: writes.append((path, copy.deepcopy(payload))) or True,
            persist_encounter=lambda *_args: events.append(("encounter_write",)) or True,
        )
        result = run_fast_commands_stage(
            cmd=command.lower(),
            clean_input=command,
            user_input_text=command,
            input_actor_name="Acheron",
            multi_pc_manager=manager,
            encounter_data=encounter,
            encounter_id=encounter_id,
            party_tracker_data={"active_character": "Acheron"},
            active_encounter_id=active_encounter_id,
            conversation_history=history,
            conversation_history_file="combat-history.json",
            io=io,
        )
        return result, manager, history, original_history, encounter, original_encounter, events, writes

    def test_parser_uses_longest_normalized_active_npc_prefix_and_sanitizes(self):
        parsed = parse_ally_directive_command(
            "/CMD   Serah   Vale  Hold\x00\tthe   bridge ",
            _encounter(),
        )
        self.assertEqual(parsed.status, "accepted")
        self.assertEqual(parsed.actor_name, "Serah Vale")
        self.assertEqual(parsed.directive, "Hold the bridge")

    def test_parser_rejects_empty_long_unknown_and_inactive_directives(self):
        encounter = _encounter()
        cases = (
            ("/cmd", "invalid_syntax"),
            ("/cmd Serah", "empty_directive"),
            ("/cmd Serah " + ("x" * 241), "directive_too_long"),
            ("/cmd Missing guard the east gate", "unknown_ally"),
            ("/cmd Downed Serah hold position", "unknown_ally"),
            ("/cmdx Serah take cover", "not_command"),
        )
        for command, expected in cases:
            with self.subTest(command=command[:32]):
                self.assertEqual(
                    parse_ally_directive_command(command, encounter).status,
                    expected,
                )

    def test_valid_command_persists_private_metadata_without_ending_or_counting_action(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True):
            result, manager, history, _old_history, encounter, old_encounter, events, writes = (
                self._run_command("/cmd Serah Vale Hold the bridge")
            )

        self.assertEqual(result.control_action, "continue")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(manager.command_calls, [])
        self.assertEqual(manager.end_calls, 0)
        self.assertFalse(manager.pc_phase_complete)
        self.assertEqual(encounter, old_encounter)
        self.assertEqual(len(history), 2)
        record = history[-1]
        self.assertEqual(record["role"], "user")
        self.assertEqual(record["content"], "")
        self.assertIn("turn_id", record)
        self.assertEqual(
            record[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY],
            {
                "schema_version": 1,
                "actor_name": "Serah Vale",
                "directive": "Hold the bridge",
            },
        )
        self.assertEqual(writes[0][0], "combat-history.json")
        self.assertEqual(writes[0][1], history)
        self.assertEqual(
            conversation_history_for_prompt(history),
            [{"role": "system", "content": "unchanged system bytes"}],
        )
        self.assertEqual([event[0] for event in events], ["emit", "flush"])
        self.assertIn("choice of action remains theirs", events[0][1])
        self.assertNotIn("Hold the bridge", events[0][1])

    def test_normal_turn_returns_before_pc_action_decision_for_cmd(self):
        from core.combat.turn import (
            CombatNormalTurnInputs,
            InputPhaseGateResult,
            prepare_combat_normal_turn,
        )

        encounter = _encounter()
        history = []
        manager = _Manager()
        events = []
        prefetch_calls = []

        def capture_prefetch(**kwargs):
            call = dict(kwargs)
            call["conversation_history"] = copy.deepcopy(kwargs["conversation_history"])
            prefetch_calls.append(call)

        io = FastCommandIO(
            emit=events.append,
            flush=lambda: None,
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            save_json=lambda *_args: True,
            persist_encounter=lambda *_args: True,
        )
        session = SimpleNamespace(
            active_pc=None,
            phase=None,
            set_phase=lambda phase: setattr(session, "phase", phase),
        )
        iteration = SimpleNamespace(
            session=session,
            encounter_data=encounter,
            multi_pc_manager=manager,
            party_tracker_data={
                "active_character": "Acheron",
                "worldConditions": {"activeCombatEncounter": "ally-command-encounter"},
            },
            conversation_history=history,
            conversation_history_file="history.json",
            user_input_text="/cmd Serah Hold the line",
            path_manager=None,
            npc_templates={},
            player_file="",
            fresh_player_data=None,
            current_hp=10,
            max_hp=10,
            player_name_display="Acheron",
            player_info={},
        )
        dependencies = SimpleNamespace(
            input_phase_gate=lambda *_args, **_kwargs: InputPhaseGateResult(
                raw_input="/cmd Serah Hold the line",
                clean_input="/cmd Serah Hold the line",
                input_actor_name="Acheron",
                pc_phase_started=False,
            ),
            phase_gate_io_factory=lambda _manager: None,
            initiative_gate=None,
            fast_command_stage=run_fast_commands_stage,
            fast_command_io_factory=lambda: io,
            submit_standing_orders=None,
            submit_ally_prefetch=capture_prefetch,
        )

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True):
            result = prepare_combat_normal_turn(
                CombatNormalTurnInputs(
                    iteration=iteration,
                    encounter_id="ally-command-encounter",
                    json_file_path="encounter.json",
                    conversation_history_file="history.json",
                    location_info={},
                ),
                dependencies,
            )

        self.assertEqual(result.control_action, "continue")
        self.assertEqual(manager.command_calls, [])
        self.assertEqual(manager.end_calls, 0)
        self.assertFalse(manager.pc_phase_complete)
        self.assertEqual(session.phase, "PC_PHASE")
        self.assertEqual(len(history), 1)
        self.assertIn(COMBAT_ALLY_DIRECTIVE_HISTORY_KEY, history[0])
        self.assertEqual(len(events), 1)
        self.assertIn("recorded your request", events[0])
        self.assertEqual(len(prefetch_calls), 2)
        self.assertEqual(
            [call["trigger"] for call in prefetch_calls],
            ["initial", "directive"],
        )
        self.assertEqual(prefetch_calls[0]["conversation_history"], [])
        self.assertEqual(
            prefetch_calls[1]["conversation_history"][-1][COMBAT_ALLY_DIRECTIVE_HISTORY_KEY]["directive"],
            "Hold the line",
        )

    def test_unknown_inactive_and_mismatched_encounter_make_no_state_change(self):
        cases = (
            ("/cmd Missing hold the line", "unknown_ally", "ally-command-encounter"),
            ("/cmd Downed Serah hold the line", "unknown_ally", "ally-command-encounter"),
            ("/cmd Serah hold the line", "inactive_encounter", "other-encounter"),
        )
        for command, expected_reason, active_id in cases:
            with self.subTest(reason=expected_reason, command=command), \
                    mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                    mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True):
                result, manager, history, original_history, encounter, original_encounter, events, writes = (
                    self._run_command(command, active_encounter_id=active_id)
                )
            self.assertEqual(result.control_action, "continue")
            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, expected_reason)
            self.assertEqual(history, original_history)
            self.assertEqual(encounter, original_encounter)
            self.assertEqual(writes, [])
            self.assertEqual(manager.command_calls, [])
            self.assertEqual(manager.end_calls, 0)
            self.assertEqual([event[0] for event in events], ["emit", "flush"])
            self.assertNotIn("recorded your request", events[0][1])

    def test_controller_default_off_leaves_existing_command_path_inert(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", False):
            result, manager, history, original_history, encounter, original_encounter, _events, writes = (
                self._run_command("/cmd Serah Hold the bridge")
            )
        self.assertEqual(result.control_action, "proceed")
        self.assertEqual(manager.command_calls, ["/cmd Serah Hold the bridge"])
        self.assertEqual(history, original_history)
        self.assertEqual(encounter, original_encounter)
        self.assertEqual(writes, [])

    def test_user_owned_end_still_transitions_the_pc_phase(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True):
            result, manager, _history, _old_history, _encounter_data, _old_encounter, _events, _writes = (
                self._run_command("/end")
            )
        self.assertEqual(result.user_input_text, "Enemies turn.")
        self.assertEqual(manager.end_calls, 1)
        self.assertTrue(manager.pc_phase_complete)

    def test_valid_directive_after_replan_submission_is_rejected_without_state_change(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True), \
                mock.patch(
                    "core.combat.ally_prefetch.has_ally_prefetch_replan_submission",
                    return_value=True,
                ):
            result, manager, history, original_history, encounter, original_encounter, events, writes = (
                self._run_command("/cmd Serah Hold the bridge")
            )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "replan_already_submitted")
        self.assertEqual(history, original_history)
        self.assertEqual(encounter, original_encounter)
        self.assertEqual(writes, [])
        self.assertEqual(manager.command_calls, [])
        self.assertEqual(manager.end_calls, 0)
        self.assertEqual([event[0] for event in events], ["emit", "flush"])
        self.assertIn("no further request was recorded", events[0][1])

    def test_prefetch_enabled_rejects_directive_when_cap_check_raises(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True), \
                mock.patch(
                    "core.combat.ally_prefetch.has_ally_prefetch_replan_submission",
                    side_effect=RuntimeError("cap registry unavailable"),
                ):
            result, manager, history, original_history, encounter, original_encounter, events, writes = (
                self._run_command("/cmd Serah Hold the bridge")
            )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "prefetch_state_unavailable")
        self.assertEqual(history, original_history)
        self.assertEqual(encounter, original_encounter)
        self.assertEqual(writes, [])
        self.assertEqual(manager.command_calls, [])
        self.assertEqual(manager.end_calls, 0)
        self.assertEqual([event[0] for event in events], ["emit", "flush"])
        self.assertIn("could not verify", events[0][1])
        self.assertIn("no request was recorded", events[0][1])

    def test_prefetch_enabled_rejects_directive_when_batch_identity_is_invalid(self):
        invalid_encounter_id = "ally command encounter"
        encounter = _encounter()
        encounter["encounterId"] = invalid_encounter_id
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", True), \
                mock.patch(
                    "core.combat.ally_prefetch.has_ally_prefetch_replan_submission",
                    return_value=False,
                ) as cap_check:
            result, manager, history, original_history, encounter, original_encounter, events, writes = (
                self._run_command(
                    "/cmd Serah Hold the bridge",
                    encounter=encounter,
                    encounter_id=invalid_encounter_id,
                    active_encounter_id=invalid_encounter_id,
                )
            )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "prefetch_state_unavailable")
        self.assertEqual(history, original_history)
        self.assertEqual(encounter, original_encounter)
        self.assertEqual(writes, [])
        self.assertEqual(manager.command_calls, [])
        self.assertEqual(manager.end_calls, 0)
        self.assertEqual([event[0] for event in events], ["emit", "flush"])
        self.assertIn("no request was recorded", events[0][1])
        cap_check.assert_not_called()

    def test_prefetch_disabled_does_not_require_cap_registry(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_CONTROLLER_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_ALLY_PREFETCH_ENABLED", False), \
                mock.patch(
                    "core.combat.ally_prefetch.has_ally_prefetch_replan_submission",
                    side_effect=RuntimeError("cap registry unavailable"),
                ) as cap_check:
            result, _manager, history, original_history, _encounter_data, _old_encounter, _events, writes = (
                self._run_command("/cmd Serah Hold the bridge")
            )

        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.reason, "accepted")
        self.assertEqual(len(history), len(original_history) + 1)
        self.assertEqual(len(writes), 1)
        cap_check.assert_not_called()

    def test_directives_coalesce_and_projection_keeps_them_actor_scoped(self):
        first = build_ally_directive_history_record("Serah", "Watch the west gate")
        latest = build_ally_directive_history_record("  SERAH  ", "Guard the bridge")
        other = build_ally_directive_history_record("Serah Vale", "Stay close")
        history = [first, latest, other]
        self.assertEqual(
            latest_ally_directives_from_history(
                history,
                active_allies=("Serah", "Serah Vale"),
            ),
            {"SERAH": "Guard the bridge", "Serah Vale": "Stay close"},
        )

        menus = AllyMenus(
            batch_id="command-test-batch",
            actor_menus=(
                AllyActorMenu(CombatantIdentity("Serah", "npc"), (), (), ""),
                AllyActorMenu(CombatantIdentity("Serah Vale", "npc"), (), (), ""),
            ),
            legal_targets=(),
        )
        projection = build_ally_perception_projection_from_history(menus, history)
        rows = {row["actor"]: row for row in projection["scheduled_allies"]}
        self.assertEqual(rows["Serah"]["directive"], "Guard the bridge")
        self.assertEqual(rows["Serah Vale"]["directive"], "Stay close")
        self.assertNotIn("_combat_ally_directive", projection)

    def test_private_directive_metadata_must_be_versioned_and_valid(self):
        record = build_ally_directive_history_record("Serah", "Hold position")
        malformed = copy.deepcopy(record)
        malformed[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY]["schema_version"] = True
        self.assertEqual(
            latest_ally_directives_from_history([malformed]),
            {},
        )


if __name__ == "__main__":
    unittest.main()
