# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Perception projection is bounded to legal encounter facts and options."""

import json
import unittest
from dataclasses import replace

from core.combat.tactical_brain import (
    MAX_ACTION_TEXT_CHARS,
    MAX_DISPOSITION_CHARS,
    build_perception_projection,
    build_commander_plan_messages,
)
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    build_g5t_scenario,
    build_menus,
)


class CombatTacticalPerceptionTests(ProviderFreeTestCase):
    def _scenario_with_hidden_facts(self):
        scenario = build_g5t_scenario(4)
        encounter = scenario["encounter"]
        encounter["module_roster"] = ["Hidden NPC Registry Entry"]
        encounter["worldAtlas"] = {"secret_location": "The Off-scene Vault"}
        for creature in encounter["creatures"]:
            creature["coordinates"] = {"x": 999, "y": -999}
            creature["secret"] = "SECRET CREATURE FACT"

        hidden = {
            "name": "Off-scene Wight",
            "type": "enemy",
            "monsterType": "Hidden Wight Type",
            "initiative": 3,
            "status": "alive",
            "conditions": [],
            "actions": {"actionType": "attack", "target": "Acheron"},
            "currentHitPoints": 98765,
            "maxHitPoints": 98765,
            "armorClass": 17,
            "coordinates": {"x": 12, "y": 34},
            "secret": "OFF SCENE SECRET",
        }
        encounter["creatures"].append(hidden)
        scenario["turn_order"].append({"name": hidden["name"], "kind": "enemy"})
        scenario["monster_definitions"]["Hidden Wight Type"] = {
            "actions": [{
                "name": "Hidden Claw",
                "attackBonus": 8,
                "damageDice": "2d8",
                "damageBonus": 4,
                "damageType": "necrotic",
            }]
        }

        for index, (name, state) in enumerate(scenario["pc_states"].items()):
            state["hitPoints"] = 13711 + index
            state["maxHitPoints"] = 27422 + index * 2
            state["spellcasting"] = {"spellSlots": {"level1": 99}}
            state["coordinates"] = {"x": index, "y": index + 1}
            state["hidden_backstory"] = "PRIVATE PC RESOURCE AND LORE"
            matching = next(
                row for row in encounter["creatures"] if row["name"] == name
            )
            matching["currentHitPoints"] = state["hitPoints"]
            matching["maxHitPoints"] = state["maxHitPoints"]
        scenario["tactical_features"].append({
            "featureId": "unissued-player-feature",
            "name": "Unissued Player-only Barricade",
            "kind": "cover",
            "coverType": "three_quarters",
            "usableBy": ["player"],
        })
        return scenario

    def test_projection_contains_only_current_eligible_actors_and_legal_targets(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        self.assertEqual(projection["batch_id"], scenario["batch_id"])
        self.assertEqual(
            {row["actor"] for row in projection["eligible_actors"]},
            {"Hobgoblin Captain", "Goblin Squad A", "Goblin Squad B"},
        )
        self.assertEqual(
            {row["name"] for row in projection["visible_pcs"]},
            {row.name for row in menus.legal_targets},
        )

    def test_projection_redacts_exact_hp_resources_coordinates_and_hidden_facts(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        encoded = json.dumps(projection, sort_keys=True)
        for forbidden in (
            "13711",
            "27422",
            "98765",
            "coordinates",
            "worldAtlas",
            "module_roster",
            "spellSlots",
            "PRIVATE PC RESOURCE AND LORE",
            "SECRET CREATURE FACT",
            "OFF SCENE SECRET",
            "Off-scene Wight",
            "Hidden Wight Type",
            "The Off-scene Vault",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, encoded)

    def test_visible_wounds_are_qualitative_and_omit_exact_values(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        wound_values = {row["wound"] for row in projection["visible_pcs"]}
        self.assertEqual(wound_values, {"bloodied"})
        self.assertNotIn("hp", json.dumps(projection).lower())

    def test_qualitative_wounds_use_authoritative_hp_at_inclusive_boundaries(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        state = scenario["pc_states"]["Acheron"]
        encounter_pc = next(
            creature for creature in scenario["encounter"]["creatures"]
            if creature["type"] == "player" and creature["name"] == "Acheron"
        )

        for hp, expected in (
            (20, "unhurt"),
            (11, "unhurt"),
            (10, "bloodied"),
            (6, "bloodied"),
            (5, "near_death"),
            (1, "near_death"),
        ):
            with self.subTest(hp=hp):
                state["hitPoints"] = hp
                state["maxHitPoints"] = 20
                # Encounter HP is deliberately stale; the PC state is authoritative.
                encounter_pc["currentHitPoints"] = 99999
                encounter_pc["maxHitPoints"] = 99999
                projection = build_perception_projection(menus, scenario["pc_states"])
                acheron = next(
                    row for row in projection["visible_pcs"]
                    if row["name"] == "Acheron"
                )
                self.assertEqual(acheron["wound"], expected)
                self.assertNotIn(str(hp), json.dumps(acheron))
                self.assertNotIn("20", json.dumps(acheron))

    def test_only_issued_enemy_cover_feature_is_projected(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        self.assertEqual(
            projection["issued_features"],
            [{
                "feature_id": "ca02-shield-racks",
                "name": "Scarred Shield Racks",
                "cover_type": "half",
            }],
        )
        self.assertNotIn("unissued-player-feature", json.dumps(projection))
        self.assertNotIn("Unissued Player-only Barricade", json.dumps(projection))

    def test_attack_options_expose_no_roll_damage_or_raw_stat_fields(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        encoded = json.dumps(projection)
        for forbidden_key in (
            "attackBonus",
            "damageDice",
            "damageBonus",
            "damageType",
            "d20",
            "armorClass",
            "currentHitPoints",
            "maxHitPoints",
        ):
            self.assertNotIn(forbidden_key, encoded)

    def test_recent_action_projection_accepts_only_visible_bounded_known_facts(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        actions = [
            {"actor": "Acheron", "action": [], "target": "Goblin Squad A"},
            {"actor": "Acheron", "action": "attacked", "target": "Goblin Squad A"},
            {"actor": "Off-scene Wight", "action": "attacked", "target": "Acheron"},
            {"actor": "Acheron", "action": "attacked", "target": "Hidden Wight Type"},
            {
                "actor": "Acheron",
                "action": "used_feature",
                "feature_id": "unissued-player-feature",
            },
            {
                "actor": "Acheron",
                "action": "used_feature",
                "feature_id": "ca02-shield-racks",
                "coordinates": {"x": 100, "y": 200},
            },
        ]
        projection = build_perception_projection(
            menus, scenario["pc_states"], observed_recent_actions=actions
        )
        self.assertEqual(projection["observed_recent_actions"], [
            {"actor": "Acheron", "action": "attacked", "target": "Goblin Squad A"},
            {
                "actor": "Acheron",
                "action": "used_feature",
                "feature_id": "ca02-shield-racks",
            },
        ])
        encoded = json.dumps(projection)
        self.assertNotIn("Off-scene Wight", encoded)
        self.assertNotIn("Hidden Wight Type", encoded)
        self.assertNotIn("coordinates", encoded)
        self.assertNotIn("unissued-player-feature", encoded)

    def test_recent_actions_are_bounded_per_visible_pc(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        actions = [
            {"actor": "Acheron", "action": "held"}
            for _ in range(8)
        ]
        projection = build_perception_projection(
            menus, scenario["pc_states"], observed_recent_actions=actions
        )
        self.assertEqual(len(projection["observed_recent_actions"]), 3)

    def test_omission_is_not_rewritten_as_a_negative_fact(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        for observations in (None, []):
            with self.subTest(observations=observations):
                projection = build_perception_projection(
                    menus,
                    scenario["pc_states"],
                    observed_recent_actions=observations,
                )
                self.assertNotIn("observed_recent_actions", projection)
                encoded = json.dumps(projection).lower()
                self.assertNotIn("no recent actions", encoded)
                self.assertNotIn("no hidden creatures", encoded)
                self.assertNotIn("not present", encoded)

    def test_projection_does_not_echo_unissued_target_or_arbitrary_observation_text(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(
            menus,
            scenario["pc_states"],
            observed_recent_actions=[{
                "actor": "Acheron",
                "action": "attacked",
                "target": "Unissued Arbitrary Target",
                "text": "The target is secretly a dragon.",
            }],
        )
        encoded = json.dumps(projection)
        self.assertNotIn("Unissued Arbitrary Target", encoded)
        self.assertNotIn("secretly a dragon", encoded)

    def test_projection_is_deterministic_for_same_menu_and_observations(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        observations = [
            {"actor": "Acheron", "action": "attacked", "target": "Goblin Squad A"},
            {"actor": "Acheron", "action": "used_feature", "feature_id": "ca02-shield-racks"},
        ]
        first = build_perception_projection(
            menus, scenario["pc_states"], observed_recent_actions=observations
        )
        second = build_perception_projection(
            menus, scenario["pc_states"], observed_recent_actions=observations
        )
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_projected_action_labels_are_bounded(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        captain_index = next(
            index for index, menu in enumerate(menus.actor_menus)
            if menu.actor.name == "Hobgoblin Captain"
        )
        captain = menus.actor_menus[captain_index]
        long_label = "Authored action " * 40
        bounded_slots = tuple(
            tuple(
                replace(option, action_name=long_label)
                if option.kind == "attack" else option
                for option in slot
            )
            for slot in captain.attack_slots
        )
        actor_menus = list(menus.actor_menus)
        actor_menus[captain_index] = replace(captain, attack_slots=bounded_slots)
        projected_menus = replace(menus, actor_menus=tuple(actor_menus))

        projection = build_perception_projection(projected_menus, scenario["pc_states"])
        labels = [
            option["action"]
            for slot in projection["eligible_actors"][captain_index]["attack_slots"]
            for option in slot
        ]
        self.assertTrue(labels)
        self.assertTrue(all(len(label) <= MAX_ACTION_TEXT_CHARS for label in labels))

    def test_actor_disposition_is_bounded_and_scoped_to_eligible_actors(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        actor_dispositions = {
            "Goblin Squad B": (
                "  Cowardly goblin raider breaks and runs when bloodied.  "
                + ("extra authored text " * 40)
            ),
            "Off-scene Wight": "OFF SCENE DISPOSITION SECRET",
        }
        projection = build_perception_projection(
            menus,
            scenario["pc_states"],
            actor_dispositions=actor_dispositions,
        )
        rows = {row["actor"]: row for row in projection["eligible_actors"]}
        disposition = rows["Goblin Squad B"]["disposition"]
        self.assertLessEqual(len(disposition), MAX_DISPOSITION_CHARS)
        self.assertTrue(disposition.startswith("Cowardly goblin raider"))
        self.assertNotIn("disposition", rows["Goblin Squad A"])
        self.assertNotIn("disposition", rows["Hobgoblin Captain"])
        self.assertNotIn("Off-scene Wight", json.dumps(projection))
        self.assertNotIn("OFF SCENE DISPOSITION SECRET", json.dumps(projection))

        messages = build_commander_plan_messages(
            menus,
            scenario["pc_states"],
            actor_dispositions=actor_dispositions,
        )
        projected_message = json.loads(messages[1]["content"])
        message_rows = {
            row["actor"]: row for row in projected_message["eligible_actors"]
        }
        self.assertEqual(
            message_rows["Goblin Squad B"]["disposition"], disposition
        )

    def test_flee_option_explains_disengage_and_turn_end_departure(self):
        scenario = build_g5t_scenario(1)
        next(
            row for row in scenario["encounter"]["creatures"]
            if row.get("name") == "Goblin Squad A"
        )["currentHitPoints"] = 3
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        goblin = next(
            row for row in projection["eligible_actors"]
            if row["actor"] == "Goblin Squad A"
        )
        flee = next(choice for choice in goblin["choices"] if choice["kind"] == "flee")

        self.assertEqual(
            flee["meaning"],
            "Direct flee is offered to a bloodied actor. Use this actor's action "
            "to take the Disengage action, make no attack, and leave combat at "
            "turn end.",
        )
        message_projection = json.loads(
            build_commander_plan_messages(menus, scenario["pc_states"])[1]["content"]
        )
        message_goblin = next(
            row for row in message_projection["eligible_actors"]
            if row["actor"] == "Goblin Squad A"
        )
        message_flee = next(
            choice for choice in message_goblin["choices"]
            if choice["kind"] == "flee"
        )
        self.assertEqual(message_flee["meaning"], flee["meaning"])

    def test_missing_or_malformed_actor_disposition_is_omitted(self):
        scenario = self._scenario_with_hidden_facts()
        menus = build_menus(scenario)
        projection = build_perception_projection(
            menus,
            scenario["pc_states"],
            actor_dispositions={
                "Goblin Squad A": {"disposition": "must not pass through"},
                "Goblin Squad B": "\x00\x01\x02",
                "Hobgoblin Captain": None,
            },
        )
        self.assertTrue(all(
            "disposition" not in row for row in projection["eligible_actors"]
        ))


if __name__ == "__main__":
    unittest.main()
