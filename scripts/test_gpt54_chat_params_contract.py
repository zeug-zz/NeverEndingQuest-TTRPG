# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
GPT-5.6 Luna chat-params prompt/runtime parity contract (generic GPT-5 family).
"""

import ast
import os
import sys
import unittest

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import utils.ai_client_factory as ai_client_factory


def _read(relative_path: str) -> str:
    with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class TestGPT54ChatParamsContract(unittest.TestCase):
    def setUp(self):
        self._actual_provider = ai_client_factory._get_actual_provider
        ai_client_factory._get_actual_provider = lambda use_fallback=False: ("openai", False)

    def tearDown(self):
        ai_client_factory._get_actual_provider = self._actual_provider

    @classmethod
    def setUpClass(cls):
        cls.main_source = _read("main.py")
        cls.combat_source = _read("core/combat/combat_manager.py")
        cls.combat_bootstrap_source = _read("core/combat/bootstrap.py")
        cls.combat_turn_source = _read("core/combat/turn.py")
        cls.combat_validation_source = _read("core/combat/validation.py")
        cls.narrator_prompt = _read("prompts/system_prompt.txt")
        cls.narrator_prompt_compressed = _read("prompts/system_prompt_compressed.txt")
        cls.combat_sim_prompt = _read("prompts/combat/combat_sim_prompt_multipc.txt")
        cls.combat_sim_prompt_compressed = _read(
            "prompts/combat/combat_sim_prompt_multipc_compressed.txt"
        )
        cls.combat_validation_prompt = _read(
            "prompts/combat/combat_validation_prompt_multipc.txt"
        )
        cls.combat_validation_prompt_compressed = _read(
            "prompts/combat/combat_validation_prompt_multipc_compressed.txt"
        )

    def test_gpt5_params_include_reasoning_and_verbosity(self):
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertEqual(params["model"], "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")

    def test_gpt5_params_exclude_legacy_temperature_by_default(self):
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_non_gpt5_params_use_task_temperature_policy(self):
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.42,
        )

        self.assertEqual(params["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("verbosity", params)

    def test_retry_tier_high_uses_high_reasoning(self):
        params = ai_client_factory.get_chat_completion_params(
            "combat_validation",
            "gpt-5.6-luna",
            retry_tier="high",
        )

        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "low")

    def test_main_narrator_callsites_use_router_and_facade_owned_timeout(self):
        from scripts.test_core_chat_inventory_contract import _functions, _calls, _call_name

        narrator = _functions("main.py")["get_ai_response"]
        router_calls = [call for call in _calls(narrator) if _call_name(call) == "llm.call"]
        self.assertEqual(len(router_calls), 1)
        self.assertFalse(any(_call_name(call) == "request_chat_completion_with_recovery" for call in _calls(narrator)))
        self.assertFalse(any(_call_name(call) == "create_chat_client" for call in _calls(narrator)))
        keywords = {keyword.arg for keyword in router_calls[0].keywords}
        self.assertTrue({"task", "messages", "json_output", "empty_retry_limit", "model_tier"}.issubset(keywords))
        self.assertNotIn("timeout", keywords)

    def test_combat_callsites_use_router_and_leave_timeout_ownership_to_factory(self):
        from scripts.test_core_chat_inventory_contract import _functions, _calls, _call_name

        expected = {
            ("core/combat/bootstrap.py", "_startup_provider_call"): ("combat_main", 1),
            ("core/combat/bootstrap.py", "_run_initial_scene_generation"): ("combat_main", 1),
            ("core/combat/turn.py", "run_combat_provider_retry_stage"): ("combat_main", 3),
            ("core/combat/validation.py", "validate_combat_response"): ("combat_validation", 1),
            ("core/combat/combat_manager.py", "summarize_dialogue"): ("combat_summary", 1),
            ("core/combat/combat_manager.py", "generate_combat_round_summary"): ("compression", 1),
            ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker"): ("combat_main", 1),
        }
        for (path, name), (task, count) in expected.items():
            routed = [
                call for call in _calls(_functions(path)[name])
                if _call_name(call) in {"llm.call", "dependencies.llm_call"}
            ]
            with self.subTest(owner=path + "::" + name):
                self.assertEqual(len(routed), count)
                for call in routed:
                    task_node = next(
                        (item.value for item in call.keywords if item.arg == "task"),
                        call.args[0] if call.args else None,
                    )
                    self.assertEqual(ast.literal_eval(task_node), task)
                    keywords = {item.arg: item.value for item in call.keywords}
                    self.assertIs(ast.literal_eval(keywords["json_output"]), False)
                    self.assertNotIn("timeout", keywords)
                    self.assertNotIn("model", keywords)
                self.assertFalse(any(
                    _call_name(call).endswith("chat.completions.create")
                    or _call_name(call) in {"OpenAI", "create_chat_client"}
                    for call in _calls(_functions(path)[name])
                ))

        self.assertEqual(
            sum(_call_name(call) == "_startup_provider_call"
                for call in _calls(_functions("core/combat/bootstrap.py")["_run_resume_narrative"])),
            2,
        )
        self.assertIn('temperature=0.3', self.combat_validation_source)
        self.assertIn('retry_tier="high"', self.combat_turn_source)

    def test_narrator_prompt_pairs_agree_on_movement_and_roll_contracts(self):
        self.assertIn(
            "Do NOT use updatePartyTracker for same-module movement. Same-module movement must use transitionLocation.",
            self.narrator_prompt,
        )
        self.assertIn(
            "updatePartyTracker: cross-module activation/travel and tracker state updates",
            self.narrator_prompt_compressed,
        )
        self.assertIn("requestRoll", self.narrator_prompt)
        self.assertIn("requestRoll", self.narrator_prompt_compressed)
        self.assertIn("WAIT for the player to provide their roll result", self.narrator_prompt)
        self.assertIn(
            "Do NOT narrate contingent success/failure yet",
            self.narrator_prompt_compressed,
        )

    def test_narrator_prompt_pairs_agree_on_follower_state_contracts(self):
        self.assertIn("Use \"updateSceneFollower\" for durable scene followers", self.narrator_prompt)
        self.assertIn("Do not use moveBackgroundNPC as follower location persistence", self.narrator_prompt)
        self.assertIn("updateSceneFollower", self.narrator_prompt_compressed)
        self.assertIn(
            "Same-module party travel is committed by transitionLocation; Python synchronizes eligible traveling followers after commit.",
            self.narrator_prompt_compressed,
        )

    def test_combat_prompt_pairs_agree_on_phase_and_replay_contracts(self):
        self.assertIn("CURRENT_PHASE", self.combat_sim_prompt)
        self.assertIn("CURRENT_PHASE", self.combat_sim_prompt_compressed)
        self.assertIn("ENEMY_PHASE", self.combat_sim_prompt)
        self.assertIn("ENEMY_PHASE", self.combat_sim_prompt_compressed)
        self.assertIn("resolve only the active PC marked with `[>]` and then STOP", self.combat_sim_prompt)
        self.assertIn("resolve only the active PC marked with `[>]` and then STOP", self.combat_sim_prompt_compressed)
        self.assertIn("Spirit Guardians damages Goblin -> updateEncounter", self.combat_sim_prompt_compressed)
        self.assertIn("[ALREADY_APPLIED]", self.combat_sim_prompt)
        self.assertIn("[ALREADY_APPLIED]", self.combat_sim_prompt_compressed)

    def test_combat_validation_prompts_allow_exit_only_when_no_living_hostiles(self):
        self.assertIn(
            "Do NOT exit if any enemy still has status \"alive\"",
            self.combat_validation_prompt,
        )
        self.assertIn(
            "exit REQUIRED when ALL enemies are dead/unconscious/defeated",
            self.combat_validation_prompt_compressed,
        )
        self.assertIn("If all enemies are defeated", self.combat_validation_prompt)
        self.assertIn("MUST call exit action immediately", self.combat_validation_prompt_compressed)
        self.assertIn("pc_phase_branch", self.combat_validation_prompt_compressed)
        self.assertIn("enemy_phase_branch", self.combat_validation_prompt_compressed)
        self.assertIn("at most one updateEncounter when enemy state changes exist", self.combat_validation_prompt_compressed)
        self.assertIn("At most one updateEncounter per response when enemy state changes exist", self.combat_validation_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
