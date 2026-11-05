# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the shadow-only combat zone ledger."""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest
from dataclasses import replace
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arm provider and external-write guards before importing pilot code.
from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.adapter import observe_movement_hint as parse_movement_hint
from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.zone_ledger import (
    COMBAT_FIXTURE_ID,
    CONTRADICTION_CATEGORIES,
    CoverRelation,
    _build_zone_ledger,
    classify_movement_parse_outcome,
    count_contradictions,
    cover_between,
    initialize_zone_ledger,
    line_of_sight_between,
    load_script_intended_move,
    observe_movement_hint,
    record_contradictions,
    resolve_enemy_phase,
    serialize_ledger,
    serialize_observations,
    zone_band,
)


PREREG_ROOT = ROOT / "plans" / "v2-mapping-pilot-prereg"
_FIXTURES, _VERIFIED_HASHES = load_verified_fixtures(PREREG_ROOT)
_COMBAT_FIXTURE = _FIXTURES[COMBAT_FIXTURE_ID]


def _response(
    from_zone: str,
    to_zone: str,
    *,
    disengage: bool = False,
    cover_sought: str = "none",
) -> dict[str, Any]:
    return {
        "narration": "The actor moves toward the next zone.",
        "actions": [{"action": "attack", "status": "accepted"}],
        "movement_hint": {
            "from": from_zone,
            "to": to_zone,
            "disengage": disengage,
            "cover_sought": cover_sought,
        },
    }


class MappingPilotZoneLedgerTests(unittest.TestCase):
    def test_verified_fixture_initializes_exact_p1_and_p4_positions_and_groups(self) -> None:
        fixture_copy = copy.deepcopy(_COMBAT_FIXTURE)
        before = copy.deepcopy(fixture_copy)
        p1 = _build_zone_ledger(fixture_copy, 1)
        p4 = _build_zone_ledger(fixture_copy, 4)
        self.assertEqual(fixture_copy, before)
        self.assertEqual(
            p1.positions,
            {
                "Acheron": "MPV2_Z_FLOOR",
                "MPV2_ENEMY_MELEE_ALPHA": "MPV2_Z_FLOOR",
                "MPV2_ENEMY_MELEE_BETA": "MPV2_Z_HEARTH",
                "MPV2_ENEMY_BALCONY_ARCHER": "MPV2_Z_BALCONY",
            },
        )
        self.assertEqual(
            p1.engagement_groups,
            {
                "MPV2_ENGAGEMENT_ALPHA": ["Acheron", "MPV2_ENEMY_MELEE_ALPHA"],
                "MPV2_ENGAGEMENT_BETA": ["MPV2_ENEMY_MELEE_BETA"],
            },
        )
        self.assertEqual(
            p4.positions,
            {
                "Acheron": "MPV2_Z_FLOOR",
                "Merisiel": "MPV2_Z_FLOOR",
                "Kira": "MPV2_Z_HEARTH",
                "Vitreol": "MPV2_Z_HEARTH",
                "MPV2_ENEMY_MELEE_ALPHA": "MPV2_Z_FLOOR",
                "MPV2_ENEMY_MELEE_BETA": "MPV2_Z_HEARTH",
                "MPV2_ENEMY_BALCONY_ARCHER": "MPV2_Z_BALCONY",
            },
        )
        self.assertEqual(
            p4.engagement_groups,
            {
                "MPV2_ENGAGEMENT_ALPHA": [
                    "Acheron",
                    "Merisiel",
                    "MPV2_ENEMY_MELEE_ALPHA",
                ],
                "MPV2_ENGAGEMENT_BETA": [
                    "Kira",
                    "Vitreol",
                    "MPV2_ENEMY_MELEE_BETA",
                ],
            },
        )
        self.assertEqual(initialize_zone_ledger(1).positions, p1.positions)
        self.assertEqual(initialize_zone_ledger(4).positions, p4.positions)

    def test_unknown_party_size_and_malformed_fixture_fail_loudly(self) -> None:
        for party_size in (0, 2, 5, True):
            with self.subTest(party_size=party_size):
                with self.assertRaisesRegex(ValueError, "party_size"):
                    initialize_zone_ledger(party_size)

        malformed = copy.deepcopy(_COMBAT_FIXTURE)
        malformed["enemy_movement_policy"].pop("path_tie_break_order")
        before = copy.deepcopy(malformed)
        with self.assertRaises(ValueError):
            _build_zone_ledger(malformed, 1)
        self.assertEqual(malformed, before)

    def test_adjacency_elevation_cover_and_graph_bands_are_fixture_derived(self) -> None:
        ledger = initialize_zone_ledger(1)
        self.assertIn("MPV2_Z_BAR", ledger.adjacency["MPV2_Z_FLOOR"])
        self.assertIn("MPV2_Z_STAIRS", ledger.adjacency["MPV2_Z_BALCONY"])
        self.assertEqual(ledger.zones["MPV2_Z_BALCONY"].elevation_level, "upper")
        self.assertEqual(
            ledger.zones["MPV2_Z_BALCONY"].relative_levels_above_ground, 1
        )
        self.assertEqual(
            ledger.zones["MPV2_Z_STAIRS"].elevation_level,
            "transition_ground_to_upper",
        )
        self.assertEqual(cover_between(ledger, "MPV2_Z_FLOOR", "MPV2_Z_BAR"), "half")
        self.assertEqual(cover_between(ledger, "MPV2_Z_BAR", "MPV2_Z_FLOOR"), "half")
        self.assertEqual(
            line_of_sight_between(ledger, "MPV2_Z_FLOOR", "MPV2_Z_BAR"), "clear"
        )
        self.assertEqual(zone_band(ledger, "Acheron", "MPV2_ENEMY_MELEE_ALPHA"), "Engaged")
        self.assertEqual(zone_band(ledger, "Acheron", "MPV2_ENEMY_MELEE_BETA"), "Near")
        self.assertEqual(zone_band(ledger, "Acheron", "MPV2_ENEMY_BALCONY_ARCHER"), "Far")
        self.assertEqual(set(ledger.band_definitions), {"Engaged", "Near", "Far", "Out of sight"})
        self.assertIn("graph", ledger.distance_policy)
        self.assertEqual(ledger.authored_distances, ())

        blocked_copy = copy.deepcopy(ledger)
        blocked_copy.cover_relations = tuple(
            replace(relation, line_of_sight="blocked")
            if {relation.zone_a, relation.zone_b}
            == {"MPV2_Z_FLOOR", "MPV2_Z_HEARTH"}
            else relation
            for relation in blocked_copy.cover_relations
        )
        self.assertEqual(zone_band(blocked_copy, "Acheron", "MPV2_ENEMY_MELEE_BETA"), "Out of sight")

    def test_p1_enemy_phase_moves_beta_joins_group_and_holds_archer_cover(self) -> None:
        ledger = initialize_zone_ledger(1)
        cover_before = copy.deepcopy(ledger.cover_relations)
        self.assertEqual(
            cover_between(ledger, "MPV2_Z_FLOOR", "MPV2_Z_BALCONY"), "half"
        )
        first_phase = resolve_enemy_phase(ledger)
        self.assertEqual(ledger.positions["MPV2_ENEMY_MELEE_ALPHA"], "MPV2_Z_FLOOR")
        self.assertEqual(ledger.positions["MPV2_ENEMY_MELEE_BETA"], "MPV2_Z_FLOOR")
        self.assertEqual(ledger.positions[ledger.balcony_archer_actor_id], "MPV2_Z_BALCONY")
        self.assertEqual(
            ledger.engagement_groups["MPV2_ENGAGEMENT_ALPHA"],
            ["Acheron", "MPV2_ENEMY_MELEE_ALPHA", "MPV2_ENEMY_MELEE_BETA"],
        )
        self.assertNotIn("MPV2_ENGAGEMENT_BETA", ledger.engagement_groups)
        self.assertEqual(ledger.cover_relations, cover_before)
        self.assertEqual(
            cover_between(ledger, "MPV2_Z_FLOOR", "MPV2_Z_BALCONY"), "half"
        )
        self.assertEqual(
            [row.status for row in first_phase], ["held", "moved_and_joined", "held"]
        )

        repeated = initialize_zone_ledger(1)
        repeated_phase = resolve_enemy_phase(repeated)
        self.assertEqual(first_phase, repeated_phase)
        self.assertEqual(serialize_ledger(ledger), serialize_ledger(repeated))
        self.assertEqual(serialize_observations(ledger), serialize_observations(repeated))

    def test_enemy_target_tie_uses_fixture_party_order(self) -> None:
        ledger = initialize_zone_ledger(4)
        move_acheron = _response("MPV2_Z_FLOOR", "MPV2_Z_BAR", cover_sought="half")
        move_merisiel = _response("MPV2_Z_FLOOR", "MPV2_Z_TABLE", cover_sought="half")
        self.assertTrue(observe_movement_hint(ledger, "Acheron", move_acheron).applied_to_shadow)
        self.assertTrue(observe_movement_hint(ledger, "Merisiel", move_merisiel).applied_to_shadow)
        phase = resolve_enemy_phase(ledger)
        alpha = next(row for row in phase if row.actor_id == "MPV2_ENEMY_MELEE_ALPHA")
        self.assertEqual(alpha.target_actor_id, "Acheron")
        self.assertEqual(alpha.to_zone, "MPV2_Z_BAR")
        self.assertEqual(alpha.status, "moved_and_joined")

    def test_enemy_path_tie_uses_fixture_zone_order(self) -> None:
        ledger = initialize_zone_ledger(1)
        move_to_entry = _response("MPV2_Z_FLOOR", "MPV2_Z_ENTRY")
        self.assertTrue(observe_movement_hint(ledger, "Acheron", move_to_entry).applied_to_shadow)
        phase = resolve_enemy_phase(ledger)
        beta = next(row for row in phase if row.actor_id == "MPV2_ENEMY_MELEE_BETA")
        self.assertEqual(
            beta.path,
            ("MPV2_Z_HEARTH", "MPV2_Z_FLOOR", "MPV2_Z_ENTRY"),
        )
        self.assertEqual(beta.to_zone, "MPV2_Z_FLOOR")
        self.assertEqual(ledger.positions["MPV2_ENEMY_BALCONY_ARCHER"], "MPV2_Z_BALCONY")

    def test_movement_hints_validate_one_two_steps_and_never_touch_response(self) -> None:
        one_step_ledger = initialize_zone_ledger(1)
        one_step = _response("MPV2_Z_FLOOR", "MPV2_Z_BAR", cover_sought="half")
        one_step_before = copy.deepcopy(one_step)
        one_step_result = observe_movement_hint(one_step_ledger, "Acheron", one_step)
        self.assertEqual(one_step_result.status, "valid")
        self.assertEqual(one_step_result.steps, 1)
        self.assertEqual(one_step_result.path, ("MPV2_Z_FLOOR", "MPV2_Z_BAR"))
        self.assertTrue(one_step_result.applied_to_shadow)
        self.assertEqual(one_step_ledger.positions["Acheron"], "MPV2_Z_BAR")
        self.assertEqual(one_step, one_step_before)

        two_step_ledger = initialize_zone_ledger(1)
        two_step = _response("MPV2_Z_FLOOR", "MPV2_Z_BALCONY", cover_sought="half")
        two_step_before = copy.deepcopy(two_step)
        two_step_result = observe_movement_hint(
            two_step_ledger, "Acheron", two_step, movement_mode="extended"
        )
        self.assertEqual(two_step_result.status, "valid")
        self.assertEqual(two_step_result.steps, 2)
        self.assertEqual(
            two_step_result.path,
            ("MPV2_Z_FLOOR", "MPV2_Z_STAIRS", "MPV2_Z_BALCONY"),
        )
        self.assertEqual(two_step_ledger.positions["Acheron"], "MPV2_Z_BALCONY")
        self.assertEqual(two_step, two_step_before)

        standard_ledger = initialize_zone_ledger(1)
        standard_result = observe_movement_hint(standard_ledger, "Acheron", two_step)
        self.assertEqual(standard_result.status, "invalid")
        self.assertEqual(standard_result.reason, "movement_exceeds_allowance")
        self.assertFalse(standard_result.applied_to_shadow)
        self.assertEqual(standard_ledger.positions["Acheron"], "MPV2_Z_FLOOR")

        absent_ledger = initialize_zone_ledger(1)
        absent_response = {
            "narration": "The party waits.",
            "actions": [{"action": "attack", "status": "accepted"}],
        }
        absent_before = copy.deepcopy(absent_response)
        absent = observe_movement_hint(absent_ledger, "Acheron", absent_response)
        self.assertEqual(absent.status, "missing")
        self.assertEqual(absent_ledger.positions["Acheron"], "MPV2_Z_FLOOR")
        self.assertEqual(absent_response, absent_before)
        self.assertEqual(absent_response["actions"][0]["status"], "accepted")
        self.assertFalse(hasattr(absent, "veto"))

        wrong_actor_from = _response("MPV2_Z_BAR", "MPV2_Z_ENTRY")
        mechanical_state_copy = {
            "phase": "pc",
            "acheron_hp": 17,
            "action_status": "accepted",
        }
        mechanical_state_before = copy.deepcopy(mechanical_state_copy)
        wrong_actor_from["mechanical_state_copy"] = mechanical_state_copy
        wrong_actor_from_before = copy.deepcopy(wrong_actor_from)
        invalid = observe_movement_hint(absent_ledger, "Acheron", wrong_actor_from)
        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(invalid.reason, "from_zone_does_not_match_shadow_position")
        self.assertEqual(absent_ledger.positions["Acheron"], "MPV2_Z_FLOOR")
        self.assertEqual(mechanical_state_copy, mechanical_state_before)
        self.assertEqual(wrong_actor_from, wrong_actor_from_before)
        self.assertFalse(hasattr(invalid, "veto"))

        malformed = observe_movement_hint(
            absent_ledger, "Acheron", {"movement_hint": "not-an-object"}
        )
        self.assertEqual(malformed.status, "invalid")
        self.assertEqual(malformed.reason, "hint_not_object")
        self.assertEqual(absent_ledger.positions["Acheron"], "MPV2_Z_FLOOR")

    def test_movement_parse_classifies_exact_only_without_human_judgment(self) -> None:
        ledger = initialize_zone_ledger(1)
        intended = load_script_intended_move("K2-01", 1, PREREG_ROOT)
        intended_before = copy.deepcopy(intended)
        exact_response = _response(
            intended["from"],
            intended["to"],
            disengage=intended["disengage"],
            cover_sought=intended["cover_sought"],
        )
        exact = classify_movement_parse_outcome(
            ledger, intended, parse_movement_hint(exact_response)
        )
        self.assertEqual(exact, "exact")

        alternate_response = _response(
            "MPV2_Z_FLOOR", "MPV2_Z_STAIRS", cover_sought="none"
        )
        alternate = classify_movement_parse_outcome(
            ledger, intended, parse_movement_hint(alternate_response)
        )
        self.assertIsNone(alternate)
        reviewed = classify_movement_parse_outcome(
            ledger,
            intended,
            parse_movement_hint(alternate_response),
            adjudicated_outcome="acceptable",
        )
        self.assertEqual(reviewed, "acceptable")
        refused = classify_movement_parse_outcome(
            ledger,
            intended,
            parse_movement_hint({"narration": "I cannot move."}),
            adjudicated_outcome="refused",
        )
        self.assertEqual(refused, "refused")
        wrong = classify_movement_parse_outcome(
            ledger,
            intended,
            parse_movement_hint(alternate_response),
            adjudicated_outcome="wrong",
        )
        clarified = classify_movement_parse_outcome(
            ledger,
            intended,
            parse_movement_hint({"narration": "Which bar do you mean?"}),
            adjudicated_outcome="clarified",
        )
        self.assertEqual(wrong, "wrong")
        self.assertEqual(clarified, "clarified")
        self.assertEqual(intended, intended_before)
        unclassified = next(
            row
            for row in ledger.observations
            if row.get("kind") == "movement_parse_outcome"
            and row.get("classification") is None
        )
        self.assertEqual(unclassified["intended_move"], intended_before)

    def test_structured_contradiction_claims_are_counted_once_without_prose_analysis(self) -> None:
        ledger = initialize_zone_ledger(4)
        claims = [
            {
                "claim_id": "r1-1",
                "category": "melee_across_non_engaged_zones",
                "contradiction": True,
                "actor_ids": ["MPV2_ENEMY_MELEE_BETA", "Acheron"],
            },
            {
                "claim_id": "r1-2",
                "category": "false_elevation_cover_or_engagement_relation",
                "contradiction": True,
                "actor_ids": ["MPV2_ENEMY_BALCONY_ARCHER"],
            },
            {
                "claim_id": "r1-3",
                "category": "actor_assigned_two_zones",
                "contradiction": False,
            },
        ]
        before = copy.deepcopy(claims)
        self.assertEqual(record_contradictions(ledger, claims), 2)
        self.assertEqual(count_contradictions(ledger), 2)
        self.assertEqual(claims, before)
        self.assertEqual(len(CONTRADICTION_CATEGORIES), 6)

        invalid_claims = [
            {"category": "not_a_preregistered_category", "contradiction": True}
        ]
        observations_before = copy.deepcopy(ledger.observations)
        with self.assertRaisesRegex(ValueError, "unknown contradiction category"):
            record_contradictions(ledger, invalid_claims)
        self.assertEqual(ledger.observations, observations_before)

    def test_serialization_is_stable_and_runtime_owners_are_not_imported(self) -> None:
        first = initialize_zone_ledger(4)
        second = initialize_zone_ledger(4)
        self.assertEqual(serialize_ledger(first), serialize_ledger(second))
        self.assertEqual(serialize_observations(first), serialize_observations(second))
        self.assertTrue(serialize_ledger(first).isascii())
        self.assertTrue(serialize_observations(first).isascii())
        self.assertTrue(serialize_ledger(first).startswith('{"actor_kinds"'))
        for forbidden in (
            "main",
            "web.web_interface",
            "core.combat.combat_manager",
            "core.combat.turn",
        ):
            self.assertNotIn(forbidden, sys.modules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
