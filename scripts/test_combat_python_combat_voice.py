# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free checks for Python-authored combat command replies."""

import unittest

from core.combat.commands import (
    DeterministicCommandIO,
    FastCommandIO,
    format_ally_command_feedback,
    run_deterministic_command_stage,
    run_fast_commands_stage,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase


class CombatPythonCombatVoiceTests(ProviderFreeTestCase):
    def test_end_command_uses_narrator_voice_and_keeps_phase_debug_logging(self):
        chat = []
        debug = []
        events = []
        writes = []
        history = []

        class Manager:
            current_pc_name = "Acheron"

            def set_current_pc(self, name):
                events.append(("set_current_pc", name))
                self.current_pc_name = name

            def force_end_pc_phase(self):
                events.append(("force_end_pc_phase",))

            def get_remaining_enemies_for_round(self):
                events.append(("get_remaining_enemies",))
                return ["Goblin"]

            def handle_combat_command(self, command, _encounter, **_kwargs):
                events.append(("handle_combat_command", command))
                return None, None, None, True

        io = FastCommandIO(
            emit=chat.append,
            flush=lambda: events.append(("flush",)),
            debug=lambda message, **kwargs: debug.append(
                (message, kwargs.get("category"))
            ),
            warning=lambda *_args, **_kwargs: None,
            save_json=lambda path, payload: writes.append((path, payload)) or True,
            persist_encounter=lambda *_args: True,
        )
        result = run_fast_commands_stage(
            cmd="/end",
            clean_input="/end",
            user_input_text="/end",
            input_actor_name="Acheron",
            multi_pc_manager=Manager(),
            encounter_data={},
            encounter_id="voice-test-encounter",
            party_tracker_data={"active_character": "Acheron"},
            conversation_history=history,
            conversation_history_file="combat-history.json",
            io=io,
        )

        self.assertEqual(
            chat,
            ["Dungeon Master: Your turn is over; the combat moves on."],
        )
        self.assertEqual(
            debug,
            [
                ("TURN_END: Detected explicit force enemy phase command", "combat_events"),
                ("TURN_END: Forcing enemy phase injection", "combat_events"),
            ],
        )
        self.assertEqual(result.control_action, "continue")
        self.assertEqual(result.user_input_text, "Enemies turn.")
        self.assertEqual(events.count(("force_end_pc_phase",)), 1)
        self.assertIn(("handle_combat_command", "/end"), events)
        self.assertIn("Turn Order: Goblin.", history[-1]["content"])
        self.assertEqual(writes, [("combat-history.json", history)])
        self.assertNotIn("DEBUG", chat[0])

    def test_end_combat_replaces_internal_status_with_narrator_acknowledgement(self):
        chat = []
        events = []
        history = []
        party_tracker = {
            "worldConditions": {"activeCombatEncounter": "voice-test-encounter"}
        }
        player_info = {"name": "Acheron"}

        io = DeterministicCommandIO(
            emit=chat.append,
            flush=lambda: events.append(("flush",)),
            load_json=lambda path: events.append(("load_json", path)) or player_info,
            save_json=lambda path, payload: events.append(("save_json", path)) or True,
            write_json=lambda *_args: None,
            path_manager=None,
            normalize_name=lambda name: name,
            sync_active_encounter=lambda **_kwargs: None,
            save_manager_factory=lambda: None,
            summarize_dialogue=lambda _history, _location, _party: "summary",
            generate_chat_history=lambda _history, encounter_id: events.append(
                ("generate_chat_history", encounter_id)
            ),
        )
        result = run_deterministic_command_stage(
            cmd="/end_combat",
            current_round=2,
            encounter_id="voice-test-encounter",
            encounter_data={},
            party_tracker_data=party_tracker,
            conversation_history=history,
            location_info={},
            player_file="characters/acheron.json",
            io=io,
        )

        self.assertEqual(chat, ["Dungeon Master: You bring the combat to an end."])
        self.assertEqual(result.control_action, "return")
        self.assertEqual(result.return_value, ("summary", player_info))
        self.assertEqual(
            party_tracker["worldConditions"]["activeCombatEncounter"], ""
        )
        self.assertEqual(
            party_tracker["worldConditions"]["lastCompletedEncounter"],
            "voice-test-encounter",
        )
        self.assertEqual(len(history), 1)
        self.assertIn("forcefully ended by the user", history[0]["content"])
        self.assertIn(("generate_chat_history", "voice-test-encounter"), events)
        self.assertIn(("load_json", "characters/acheron.json"), events)
        self.assertNotIn("COMBAT_MANAGER", chat[0])

    def test_acceptance_acknowledges_guidance_without_claiming_an_action(self):
        reply = format_ally_command_feedback("accepted", "Serah Vale")
        self.assertEqual(
            reply,
            "Dungeon Master: I have recorded your request for Serah Vale; "
            "the choice of action remains theirs.",
        )
        self.assertNotIn("[SYSTEM]", reply)
        self.assertNotIn("attack", reply.casefold())

    def test_rejections_explain_outcome_without_raw_diagnostics_or_receipt_claims(self):
        cases = (
            ("unknown_ally", "No active ally by that name"),
            ("empty_directive", "non-empty instruction"),
            ("directive_too_long", "240 characters or fewer"),
            ("inactive_encounter", "no matching active encounter"),
            ("history_persist_failed", "could not secure that request"),
        )
        for status, expected_phrase in cases:
            with self.subTest(status=status):
                reply = format_ally_command_feedback(status, "InternalError\nDetail")
                self.assertTrue(reply.startswith("Dungeon Master: "))
                self.assertIn(expected_phrase, reply)
                self.assertIn("no request was recorded", reply)
                self.assertNotIn("InternalError", reply)
                self.assertNotIn("\n", reply)
                self.assertNotIn("[SYSTEM]", reply)

    def test_malformed_feedback_is_concise_and_does_not_claim_delivery(self):
        reply = format_ally_command_feedback("invalid_syntax")
        self.assertEqual(
            reply,
            "Dungeon Master: Name an active ally and give a brief instruction; "
            "no request was recorded.",
        )


if __name__ == "__main__":
    unittest.main()
