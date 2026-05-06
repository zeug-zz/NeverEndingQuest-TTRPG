# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
GPT-5.4 Mini prompt/runtime parity audit.
"""

import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import utils.ai_client_factory as ai_client_factory


def _read(relative_path: str) -> str:
    with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class TestGPT54ChatParamsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_source = _read("main.py")
        cls.combat_source = _read("core/managers/combat_manager.py")
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
            "gpt-5.4-mini-2026-03-17",
            temperature_override=0.7,
        )

        self.assertEqual(params["model"], "gpt-5.4-mini-2026-03-17")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")

    def test_gpt5_params_exclude_legacy_temperature_by_default(self):
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.4-mini-2026-03-17",
            temperature_override=0.7,
        )

        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_non_gpt5_params_preserve_temperature(self):
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.42,
        )

        self.assertEqual(params["temperature"], 0.42)
        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("verbosity", params)

    def test_retry_tier_high_uses_high_reasoning(self):
        params = ai_client_factory.get_chat_completion_params(
            "combat_validation",
            "gpt-5.4-mini-2026-03-17",
            retry_tier="high",
        )

        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "low")

    def test_main_narrator_callsites_use_shared_helper_and_timeout(self):
        self.assertEqual(
            self.main_source.count("client.chat.completions.create("),
            self.main_source.count("**get_chat_completion_params("),
        )
        self.assertEqual(
            self.main_source.count("client.chat.completions.create("),
            self.main_source.count("timeout=NARRATOR_API_TIMEOUT_SECONDS"),
        )
        self.assertIn("handle_provider_error(", self.main_source)
        self.assertIn("create_chat_client(use_fallback=True)", self.main_source)

    def test_combat_callsites_use_shared_helper_and_timeout(self):
        self.assertEqual(
            self.combat_source.count("client.chat.completions.create("),
            self.combat_source.count("**get_chat_completion_params("),
        )
        self.assertGreaterEqual(
            self.combat_source.count("timeout=COMBAT_API_TIMEOUT_SECONDS"),
            3,
        )
        self.assertIn("retry_tier=\"high\"", self.combat_source)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
