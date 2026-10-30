# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-tripwire tests for combined ally/hostile receipt recovery."""

from __future__ import annotations

from unittest import mock

import model_config
from core.combat.enemy_batch_apply import EnemyBatchApplyError
from core.combat.turn_commit import (
    COMBAT_ALLY_DIRECTIVE_HISTORY_KEY,
    COMBAT_TURN_COMMIT_MANIFEST_KEY,
    commit_combat_turn,
    compute_applied_id,
    read_character_applied_id,
)
from scripts.combat_ally_test_support import AllyBatchHarness, FIXED_TURN_ID
from scripts.combat_tactical_test_support import ProviderFreeTestCase


class CombatAllyCommitTests(ProviderFreeTestCase):
    def test_combined_effects_recover_and_receipt_replay_is_noop(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                harness = AllyBatchHarness(party_size, starts_with="pcGroup")
                try:
                    harness.fail_encounter_write = True
                    with mock.patch.multiple(
                        model_config,
                        DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                        COMBAT_ALLY_CONTROLLER_ENABLED=True,
                    ):
                        with self.assertRaises(EnemyBatchApplyError) as raised:
                            harness.execute()
                    self.assertEqual(raised.exception.stage, "encounter")

                    manifest = harness.commit_manifest()
                    expected_applied_id = compute_applied_id(
                        harness.encounter_id,
                        FIXED_TURN_ID,
                    )
                    self.assertEqual(manifest["path"], "enemy_batch")
                    self.assertEqual(manifest["applied_id"], expected_applied_id)
                    self.assertEqual(
                        manifest["receipt"],
                        {
                            "schema_version": 1,
                            "turn_id": FIXED_TURN_ID,
                            "applied_id": expected_applied_id,
                            "encounter_id": harness.encounter_id,
                            "combat_round": 2,
                        },
                    )
                    staged_enemy = next(
                        row for row in manifest["encounter_projection"]["creatures"]
                        if row["name"] == "Goblin Alpha"
                    )
                    self.assertLess(staged_enemy["currentHitPoints"], 10)
                    self.assertEqual(staged_enemy["status"], "alive")
                    staged_effect_names = [
                        row["character_name"]
                        for row in manifest["character_effects"]
                    ]
                    self.assertTrue(staged_effect_names)
                    self.assertEqual(
                        staged_effect_names,
                        sorted(staged_effect_names, key=lambda name: " ".join(name.split()).casefold()),
                    )
                    self.assertEqual(
                        harness.ally_directive_record()[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY][
                            "consumed_by_applied_id"
                        ],
                        expected_applied_id,
                    )
                    provider_call_count = len(harness.provider_calls)

                    harness.fail_encounter_write = False
                    harness.writes.clear()
                    recovered = harness.recover()
                    self.assertTrue(recovered.recovered)
                    self.assertEqual(
                        [label for label, _payload in harness.writes],
                        ["encounter"],
                    )
                    self.assertEqual(
                        recovered.encounter_data["turn_receipts"][0]["applied_id"],
                        expected_applied_id,
                    )
                    self.assertLess(
                        next(
                            row["currentHitPoints"]
                            for row in recovered.encounter_data["creatures"]
                            if row["name"] == "Goblin Alpha"
                        ),
                        10,
                    )
                    self.assertEqual(len(harness.provider_calls), provider_call_count)
                    self.assertEqual(
                        harness.published[-1],
                        (
                            manifest["success_narration"]["text"],
                            expected_applied_id,
                        ),
                    )

                    harness.writes.clear()
                    no_op_recovery = harness.recover()
                    self.assertFalse(no_op_recovery.recovered)
                    replay = commit_combat_turn(
                        harness.encounter_id,
                        FIXED_TURN_ID,
                        harness.encounter_path,
                        recovered.encounter_data,
                        (),
                        read_json=harness._read_json,
                        write_json=harness._write_json,
                    )
                    self.assertTrue(replay.replayed)
                    self.assertEqual(replay.write_count, 0)
                    self.assertEqual(harness.writes, [])
                    self.assertEqual(len(harness.persisted_encounter["turn_receipts"]), 1)
                    self.assertEqual(len(harness.provider_calls), provider_call_count)

                    for name in staged_effect_names:
                        character = harness.characters[
                            harness.path_manager.get_character_path(name)
                        ]
                        self.assertEqual(
                            read_character_applied_id(character),
                            expected_applied_id,
                        )
                finally:
                    harness.close()
