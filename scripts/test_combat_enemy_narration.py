# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for narration from deterministic enemy ledgers."""

import copy
import json
import re
import unittest
from dataclasses import replace
from unittest import mock
from pathlib import Path

from core.combat.enemy_narration import (
    NarrationResult,
    _first_unknown_name,
    _ledger_names,
    build_enemy_batch_narration_messages,
    build_enemy_batch_template_narration,
    narrate_enemy_batch,
)
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyCoverUpdate,
    EnemyDeparture,
    EnemyResolutionLedger,
    plan_enemy_batch,
)
from scripts import combat_latency_fixtures as latency_fixtures
from utils.llm_router import GameLLMTerminalError


ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts/combat/enemy_batch_narration_prompt.txt"


def _scenario(party_size=4):
    if party_size == 1:
        encounter = copy.deepcopy(latency_fixtures._one_pc_encounter_payload())
        party_names = [latency_fixtures.ONE_PC_NAME]
        enemy_window = [
            {"name": latency_fixtures.ONE_PC_ENEMY_NAME, "kind": "enemy"}
        ]
    else:
        encounter = copy.deepcopy(latency_fixtures._encounter_payload())
        party_names = list(latency_fixtures.PC_NAMES)
        enemy_window = [
            {"name": name, "kind": "enemy"}
            for name in latency_fixtures.ENEMY_NAMES
        ]

    pc_states = {}
    for name in party_names:
        initiative = (
            latency_fixtures.ONE_PC_INITIATIVE
            if party_size == 1
            else latency_fixtures.PC_INITIATIVES[name]
        )
        state = latency_fixtures._character_payload(name, initiative)
        pc_states[name] = state
        encounter["creatures"].append({
            "name": name,
            "type": "player",
            "initiative": initiative,
            "status": "alive",
            "conditions": [],
            "actions": {"actionType": "", "target": ""},
            "currentHitPoints": state["hitPoints"],
            "maxHitPoints": state["maxHitPoints"],
            "armorClass": state["armorClass"],
        })

    turn_order = [
        {"name": creature["name"], "kind": creature["type"]}
        for creature in sorted(
            encounter["creatures"],
            key=lambda item: item["initiative"],
            reverse=True,
        )
    ]
    monster_path = ROOT / "modules/Capture_Arena/monsters/goblin.json"
    monster = json.loads(monster_path.read_text(encoding="utf-8"))
    return {
        "encounter": encounter,
        "pc_states": pc_states,
        "monster_definitions": {"Goblin": monster},
        "turn_order": turn_order,
        "batch_id": "enemy-batch-1",
        "batch_kind": "enemy_phase",
        "fixture_seed": "capture-seed-1",
        "enemy_turn_window": enemy_window,
    }


def _ledger(party_size=4):
    result = plan_enemy_batch(**_scenario(party_size))
    if not isinstance(result, EnemyResolutionLedger):
        raise AssertionError("fixture must produce an eligible enemy ledger")
    return result


def _valid_narration(ledger):
    clauses = []
    for entry in ledger.entries:
        bonus = entry.attack_total - entry.d20
        outcome = "hits" if entry.hit else "misses"
        clauses.append(
            f"{entry.actor.name} attacks {entry.target.name}, and {outcome}."
        )
        clauses.append(f"{entry.actor.name} attack roll is {entry.d20}.")
        clauses.append(f"{entry.actor.name} attack bonus is {bonus}.")
        clauses.append(f"{entry.actor.name} attack total is {entry.attack_total}.")
        clauses.append(f"{entry.target.name} AC is {entry.armor_class}.")
        if entry.hit:
            clauses.append(
                f"{entry.actor.name} deals {entry.damage_total} "
                f"{entry.damage_type} damage to {entry.target.name}."
            )
        clauses.append(
            f"{entry.target.name} HP {entry.target_hp_before} to "
            f"{entry.target_hp_after}."
        )
    return " ".join(clauses)


def _audit_ledger(*, alpha_target="Vitreol", beta_target="Vitreol"):
    def attack(actor, target, *, d20, hit, damage, before, after, max_hp=20):
        return EnemyAttackLedgerEntry(
            actor=CombatantIdentity(actor, "enemy"),
            action_name="Scimitar",
            target=CombatantIdentity(target, "player"),
            d20=d20,
            attack_total=d20 + 4,
            armor_class=14,
            hit=hit,
            critical=False,
            damage_dice_rolls=(damage,) if hit else (),
            damage_total=damage,
            damage_type="slashing",
            target_hp_before=before,
            target_hp_after=after,
            target_status_after="alive" if after > 0 else "unconscious",
            target_max_hp=max_hp,
        )

    entries = (
        attack(
            "Goblin Alpha", alpha_target, d20=6, hit=False, damage=0,
            before=20, after=20,
        ),
        attack(
            "Goblin Beta", beta_target, d20=18, hit=True, damage=7,
            before=20, after=13,
        ),
    )
    return EnemyResolutionLedger(
        encounter_id="audit-encounter",
        round_number=1,
        batch_id="audit-batch",
        batch_kind="enemy_phase",
        seed=481,
        entries=entries,
        bloodied=(),
    )


def _commander_multiattack_ledger(
    attacks, *, starting_hp=231, max_hp=231, target_name="Acheron", round_number=1
):
    current_hp = starting_hp
    entries = []
    for attack in attacks:
        actor_name, hit, damage = attack[:3]
        critical = attack[3] if len(attack) > 3 else False
        before = current_hp
        if hit:
            current_hp -= damage
        entries.append(EnemyAttackLedgerEntry(
            actor=CombatantIdentity(actor_name, "enemy"),
            action_name="Longsword" if actor_name == "Hobgoblin Captain" else "Scimitar",
            target=CombatantIdentity(target_name, "player"),
            d20=20 if critical else (15 if hit else 4),
            attack_total=24 if critical else (19 if hit else 8),
            armor_class=14,
            hit=hit,
            critical=critical,
            damage_dice_rolls=(damage,) if hit else (),
            damage_total=damage,
            damage_type="slashing",
            target_hp_before=before,
            target_hp_after=current_hp,
            target_status_after="alive",
            target_max_hp=max_hp,
        ))
    return EnemyResolutionLedger(
        encounter_id="commander-multiattack",
        round_number=round_number,
        batch_id="enemy:r%d" % round_number,
        batch_kind="enemy_phase",
        seed=481,
        entries=tuple(entries),
        bloodied=(),
    )


def _captured_batch_ledger(
    attacks,
    *,
    starting_hp=231,
    target_max_hp=231,
    target_name="Acheron",
    cover_clear=(),
    departures=(),
):
    current_hp = starting_hp
    entries = []
    for actor, action_name, hit, damage, damage_type, critical in attacks:
        before = current_hp
        if hit:
            current_hp = max(0, current_hp - damage)
        d20 = 20 if critical else (15 if hit else 4)
        entries.append(EnemyAttackLedgerEntry(
            actor=CombatantIdentity(actor, "enemy"),
            action_name=action_name,
            target=CombatantIdentity(target_name, "player"),
            d20=d20,
            attack_total=d20 + 5,
            armor_class=14,
            hit=hit,
            critical=critical,
            damage_dice_rolls=(damage,) if hit else (),
            damage_total=damage if hit else 0,
            damage_type=damage_type,
            target_hp_before=before,
            target_hp_after=current_hp,
            target_status_after="alive" if current_hp > 0 else "unconscious",
            target_max_hp=target_max_hp,
            action_is_ranged=action_name.casefold() == "shortbow",
        ))
    return EnemyResolutionLedger(
        encounter_id="captured-g5t",
        round_number=2,
        batch_id="enemy:r2",
        batch_kind="enemy_phase",
        seed=1792884142,
        entries=tuple(entries),
        bloodied=(),
        departures=tuple(departures),
        cover_updates=tuple(
            EnemyCoverUpdate(CombatantIdentity(name, "enemy"))
            for name in cover_clear
        ),
    )


def _g5t_smoke3_ledger():
    def attack(actor, *, d20, hit, damage, before, after, critical=False):
        return EnemyAttackLedgerEntry(
            actor=CombatantIdentity(actor, "enemy"),
            action_name="Scimitar" if actor != "Hobgoblin Captain" else "Longsword",
            target=CombatantIdentity("Kira", "player"),
            d20=d20,
            attack_total=d20 + 5,
            armor_class=15,
            hit=hit,
            critical=critical,
            damage_dice_rolls=(damage,) if hit else (),
            damage_total=damage,
            damage_type="slashing",
            target_hp_before=before,
            target_hp_after=after,
            target_status_after="alive",
            target_max_hp=93,
        )

    return EnemyResolutionLedger(
        encounter_id="g5t-smoke3",
        round_number=1,
        batch_id="enemy:r1",
        batch_kind="enemy_phase",
        seed=481,
        entries=(
            attack("Hobgoblin Captain", d20=7, hit=False, damage=0,
                   before=93, after=93),
            attack("Hobgoblin Captain", d20=20, hit=True, damage=7,
                   before=93, after=86),
            attack("Hobgoblin Captain", d20=13, hit=False, damage=0,
                   before=86, after=86),
            attack("Goblin Squad A", d20=20, hit=True, damage=8,
                   before=86, after=78, critical=True),
            attack("Goblin Squad B", d20=8, hit=False, damage=0,
                   before=78, after=78),
        ),
        bloodied=(),
    )


class CombatEnemyNarrationTests(unittest.TestCase):
    def _fake_call(self, response, calls):
        def llm_call(task, messages, **kwargs):
            calls.append((task, messages, kwargs))
            if task == "combat_validation":
                raise AssertionError("enemy narration must not request validation")
            return response

        return llm_call

    def _assert_ledger_facts(self, text, ledger):
        lines = text.splitlines()
        self.assertEqual(len(lines), len(ledger.entries))
        for line, entry in zip(lines, ledger.entries):
            self.assertIn(entry.actor.name, line)
            self.assertIn(entry.target.name, line)
            self.assertIn(
                f"(Rolled {entry.attack_total} vs AC {entry.armor_class}; "
                f"d20 {entry.d20})",
                line,
            )
            if entry.hit:
                self.assertIn(
                    f"It deals {entry.damage_total} {entry.damage_type} damage.",
                    line,
                )
            else:
                self.assertNotRegex(line, r"\bdeals?\b|\bdamage\b")
            if entry.critical:
                self.assertIn("critical hit", line.casefold())
            else:
                self.assertNotIn("critical", line.casefold())
            if entry.target.kind == "player" and entry.hit:
                if entry.target_max_hp:
                    self.assertIn(
                        f"{entry.target_hp_after}/{entry.target_max_hp} HP", line
                    )
                if entry.target_hp_before > 0 and entry.target_hp_after <= 0:
                    self.assertIn(f"{entry.target.name} is down.", line)
            for forbidden in ("ledger", "status", "bloodied", "dice", "not critical"):
                self.assertNotIn(forbidden, line.casefold())

    def test_accepted_narration_makes_one_combat_main_call(self):
        ledger = _ledger()
        calls = []
        observer = lambda *_args, **_kwargs: None
        result = narrate_enemy_batch(
            ledger,
            "Rain taps against the stone courtyard.",
            {entry.actor.name: "A goblin fighter." for entry in ledger.entries},
            self._fake_call(_valid_narration(ledger), calls),
            receipt_observer=observer,
        )

        self.assertEqual(result.source, "llm")
        self.assertIsNone(result.reason_code)
        self.assertEqual(result.text, _valid_narration(ledger))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "combat_main")
        self.assertIs(calls[0][2]["json_output"], False)
        self.assertIs(calls[0][2]["observer"], observer)

    def test_mismatched_name_number_and_kill_use_one_call_then_exact_template_facts(self):
        ledger = _ledger()
        entry = ledger.entries[0]
        responses = (
            (f"{entry.actor.name} attacks {entry.target.name}. The Ogre watches.", "unknown_name"),
            (f"{entry.actor.name} attacks {entry.target.name} with roll 999.", "number_mismatch"),
            (f"{entry.actor.name} kills {entry.target.name}.", "kill_claim_contradiction"),
        )
        for response, expected_reason in responses:
            with self.subTest(reason=expected_reason):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "A stone courtyard.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], "combat_main")
                self.assertEqual(result.source, "template")
                self.assertEqual(result.reason_code, expected_reason)
                self.assertEqual(result.reason_detail, expected_reason)
                self._assert_ledger_facts(result.text, ledger)

    def test_empty_response_uses_template_without_retry(self):
        ledger = _ledger(party_size=1)
        calls = []
        result = narrate_enemy_batch(
            ledger, "", {}, self._fake_call("  ", calls)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "combat_main")
        self.assertEqual(result.source, "template")
        self.assertEqual(result.reason_code, "empty_response")
        self._assert_ledger_facts(result.text, ledger)

    def test_router_terminal_error_propagates_without_fabricated_success(self):
        ledger = _ledger()
        calls = []

        def terminal_call(task, messages, **kwargs):
            calls.append((task, messages, kwargs))
            raise GameLLMTerminalError("quota")

        with self.assertRaises(GameLLMTerminalError):
            narrate_enemy_batch(ledger, "", {}, terminal_call)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "combat_main")

    def test_template_is_deterministic_and_preserves_ledger_order(self):
        ledger = _ledger()
        equal_ledger = _ledger()
        self.assertEqual(ledger, equal_ledger)
        first = build_enemy_batch_template_narration(ledger)
        second = build_enemy_batch_template_narration(equal_ledger)
        self.assertEqual(first, second)
        self._assert_ledger_facts(first, ledger)
        self.assertFalse(first.startswith("The enemy actions"))

        calls = []
        result = narrate_enemy_batch(
            ledger, "Rain on stone.", {}, self._fake_call(first, calls)
        )
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.text, first)

    def test_template_only_calls_critical_hits_critical_and_reports_hp_on_pc_hits(self):
        ledger = _audit_ledger()
        first, second = ledger.entries
        critical_ledger = replace(
            ledger,
            entries=(first, replace(second, critical=True)),
        )
        text = build_enemy_batch_template_narration(critical_ledger)
        first_line, second_line = text.splitlines()
        self.assertNotIn("critical", first_line.casefold())
        self.assertIn("critical hit", second_line.casefold())
        self.assertNotIn("20/20 HP", first_line)
        self.assertIn("13/20 HP", second_line)

    def test_realistic_correct_multi_enemy_narrations_pass_audit(self):
        same_target = _audit_ledger()
        different_targets = _audit_ledger(alpha_target="Acheron")
        other_party_members = _audit_ledger(alpha_target="Lidda", beta_target="Aria")
        cases = (
            (same_target,
             "Goblin Alpha attacks Vitreol with its scimitar and misses. "
             "Goblin Beta hits Vitreol for 7 slashing damage; he has 13 HP left."),
            (same_target,
             "Goblin Alpha's scimitar whistles past Vitreol. Goblin Beta's blade "
             "bites into Vitreol for seven points of slashing damage, leaving him "
             "with 13 hit points."),
            (same_target,
             "Goblin Alpha swings at Vitreol and misses. Goblin Beta hits him again "
             "for 7 slashing damage, leaving Vitreol down to 13 HP."),
            (same_target,
             "Goblin Alpha misses Vitreol, while Goblin Beta hits her for seven "
             "points of damage. Vitreol has 13 HP left."),
            (same_target,
             "Goblin Alpha attacks Vitreol and goes wide; Goblin Beta's scimitar "
             "connects with him for 7 slashing damage. He is at 13/20 HP."),
            (same_target,
             "Goblin Alpha fails to connect with Vitreol. Goblin Beta finds its "
             "mark on Vitreol and deals 7 slashing damage."),
            (same_target,
             "Both Goblin Alpha and Goblin Beta attack Vitreol in turn: Goblin "
             "Alpha misses, while Goblin Beta hits him for seven slashing damage."),
            (same_target,
             "Goblin Alpha misses Vitreol, and Goblin Beta's blade cuts into him "
             "for 7 slashing damage; they are left with 13 HP."),
            (different_targets,
             "Goblin Alpha misses Acheron. Goblin Beta hits Vitreol for 7 slashing "
             "damage; he has 13 hit points left."),
            (other_party_members,
             "Goblin Alpha's scimitar goes wide of Lidda. Goblin Beta lands a blow "
             "on Aria for seven points of slashing damage, leaving her at 13 HP."),
            (same_target,
             "Vitreol dodges Goblin Alpha's strike. Goblin Beta hits him for 7 "
             "slashing damage, and he is down to 13."),
            (same_target,
             "Goblin Alpha misses Vitreol; Goblin Beta lands a hit on him for "
             "seven points, leaving him with 13 HP."),
        )

        for ledger, response in cases:
            with self.subTest(response=response):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "Rain drums on the arena stones.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.source, "llm")
                self.assertIsNone(result.reason_detail)

    def test_ledger_consistent_commander_multiattack_narrations_pass(self):
        cases = (
            (
                _commander_multiattack_ledger((
                    ("Hobgoblin Captain", False, 0),
                    ("Hobgoblin Captain", True, 3),
                    ("Hobgoblin Captain", False, 0),
                    ("Goblin Squad A", True, 3),
                    ("Goblin Squad B", False, 0),
                )),
                "The Hobgoblin Captain swings at Acheron three times with a "
                "longsword: the first blow misses, the second hits for 3 "
                "slashing damage, and the third misses. Goblin Squad A's "
                "scimitar hits Acheron for 3 slashing damage. Goblin Squad B's "
                "scimitar misses. Acheron remains alive.",
            ),
            (
                _commander_multiattack_ledger((
                    ("Hobgoblin Captain", True, 3),
                    ("Hobgoblin Captain", False, 0),
                    ("Hobgoblin Captain", True, 9),
                    ("Goblin Squad A", False, 0),
                    ("Goblin Squad B", False, 0),
                ), starting_hp=225, round_number=2),
                "The Hobgoblin Captain struck Acheron with a longsword, then "
                "missed with a second swing. A third strike hit, leaving "
                "Acheron alive at 213 HP. Goblin Squad A's scimitar missed "
                "Acheron. Goblin Squad B's scimitar missed as well.",
            ),
            (
                _commander_multiattack_ledger((
                    ("Hobgoblin Captain", True, 6),
                    ("Hobgoblin Captain", True, 9),
                    ("Hobgoblin Captain", False, 0),
                    ("Goblin Squad B", False, 0),
                ), round_number=3),
                "The Hobgoblin Captain's longsword struck Acheron twice, "
                "dealing 6 and then 9 slashing damage. A third swing missed. "
                "A scimitar from Goblin Squad B also missed Acheron.",
            ),
        )

        for ledger, response in cases:
            with self.subTest(response=response):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "The training pit echoes with steel.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.source, "llm")
                self.assertIsNone(result.reason_detail)
                self.assertEqual(result.text, response)

    def test_gate2_rejected_narrations_match_their_batch_ledgers(self):
        captain = "Hobgoblin Captain"
        squad_a = "Goblin Squad A"
        squad_b = "Goblin Squad B"
        hit = lambda actor, damage, critical=False: (actor, True, damage, critical)
        miss = lambda actor: (actor, False, 0, False)
        cases = (
            (
                _commander_multiattack_ledger((
                    miss(captain), hit(captain, 3), miss(captain),
                    hit(squad_a, 6), hit(squad_b, 3),
                )),
                "The Hobgoblin Captain's first longsword swing misses Acheron. "
                "The second hits for 3 slashing damage, but the third misses. "
                "Goblin Squad A strikes with a scimitar for 6 slashing damage, "
                "and Goblin Squad B follows with a hit for 3. Acheron remains "
                "alive at 219 HP.",
            ),
            (
                _commander_multiattack_ledger((
                    miss(captain), miss(captain), hit(captain, 3),
                    hit(squad_a, 6), miss(squad_b),
                )),
                "The Hobgoblin Captain's first two longsword swings miss Acheron, "
                "but the third cuts for 3 slashing damage. Goblin Squad A lands "
                "a scimitar strike for 6 slashing damage. Goblin Squad B's "
                "scimitar swing misses.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 3), hit(captain, 4), miss(captain),
                    hit(squad_a, 6), miss(squad_b),
                ), round_number=2),
                "In round 2, the Hobgoblin Captain struck Acheron twice with its "
                "longsword, dealing 3 and then 4 slashing damage, before its "
                "third swing missed. Goblin Squad A hit Acheron with a scimitar "
                "for 6 slashing damage. Goblin Squad B's scimitar attack missed. "
                "Acheron remained alive.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 7, True), hit(captain, 7), miss(captain),
                    miss(squad_b),
                ), starting_hp=209, round_number=2),
                "The bloodied Hobgoblin Captain struck Acheron with a critical "
                "longsword hit for 7 slashing damage, then landed a second blow "
                "for 7 more. Its third swing missed. Goblin Squad B's scimitar "
                "also missed. Acheron remained alive at 195 HP.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 8), hit(captain, 5), hit(captain, 8),
                    miss(squad_a), hit(squad_b, 7),
                ), round_number=3),
                "The Hobgoblin Captain lands three longsword strikes on Acheron, "
                "dealing 8, 5, and 8 slashing damage. Goblin Squad A's scimitar "
                "swings wide. Goblin Squad B hits Acheron with a scimitar for "
                "7 slashing damage. Acheron remains alive at 203 HP.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 3), miss(captain), miss(captain),
                    hit(squad_a, 11, True), hit(squad_b, 4),
                ), starting_hp=203, round_number=3),
                "The Hobgoblin Captain's longsword struck Acheron for 3 slashing "
                "damage, then its next two swings missed. Goblin Squad A landed "
                "a critical scimitar strike for 11 slashing damage. Goblin Squad "
                "B followed with a scimitar hit for 4 more. Acheron remained "
                "alive at 185 HP.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 5), hit(captain, 7), hit(captain, 8),
                    hit(squad_a, 5), hit(squad_b, 3),
                ), starting_hp=93, max_hp=93, target_name="Merisiel"),
                "The Hobgoblin Captain struck Merisiel three times with a "
                "longsword, dealing 5, 7, and 8 slashing damage. Merisiel "
                "remained alive, her hit points falling from 93 to 73.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 3), miss(captain), hit(captain, 12, True),
                    hit(squad_b, 8),
                ), starting_hp=65, max_hp=93, target_name="Merisiel"),
                "The Hobgoblin Captain's first longsword strike cuts Merisiel "
                "from 65 to 62 HP. His next swing misses; the third lands "
                "critically, dropping her to 50 HP. Goblin Squad B then strikes "
                "with a scimitar, leaving Merisiel at 42 HP. She remains alive.",
            ),
            (
                _commander_multiattack_ledger((
                    miss(captain), miss(captain), miss(captain),
                    miss(squad_a), miss(squad_b),
                ), max_hp=93, round_number=2),
                "The Hobgoblin Captain's three longsword swings all miss Acheron. "
                "Goblin Squad A's scimitar misses as well, followed by Goblin "
                "Squad B's. Acheron remains unharmed.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 5), miss(captain), hit(captain, 4),
                    miss(squad_b),
                ), starting_hp=93, max_hp=93, round_number=2),
                "The Hobgoblin Captain's longsword hits Acheron for 5 slashing "
                "damage. A second swing misses, but the third hits for 4 more; "
                "Acheron remains alive at 84 hit points.",
            ),
            (
                _commander_multiattack_ledger((
                    miss(captain), hit(captain, 3), hit(captain, 8),
                    hit(squad_a, 3), hit(squad_b, 6, True),
                ), starting_hp=93, max_hp=93, round_number=3),
                "The Hobgoblin Captain's first longsword swing misses Acheron, "
                "but its next two strikes land for 3 and 8 slashing damage. "
                "Goblin Squad A hits with a scimitar for 3 damage, then Goblin "
                "Squad B lands a critical scimitar hit for 6. Acheron remains "
                "alive at 73 HP.",
            ),
            (
                _commander_multiattack_ledger((
                    hit(captain, 5), miss(captain), hit(captain, 6),
                    hit(squad_b, 8, True),
                ), starting_hp=73, max_hp=93, round_number=3),
                "The Hobgoblin Captain's longsword hits Acheron for 5 slashing "
                "damage. His next swing misses, but a third hits for 6 more. "
                "Goblin Squad B's scimitar then lands a critical hit, dealing 8 "
                "slashing damage. Acheron remains alive at 54 HP.",
            ),
        )

        self.assertEqual(len(cases), 12)
        accepted = 0
        rejected = 0
        for case_index, (ledger, response) in enumerate(cases):
            with self.subTest(response=response):
                result = narrate_enemy_batch(
                    ledger, "The training pit echoes with steel.", {},
                    self._fake_call(response, []),
                )
                if case_index == 6:
                    rejected += 1
                    self.assertEqual(result.source, "template")
                    self.assertEqual(result.reason_detail, "ledger_entry_omitted")
                else:
                    accepted += 1
                    self.assertEqual(result.source, "llm")
                    self.assertIsNone(result.reason_detail)
                    self.assertEqual(result.text, response)
        self.assertEqual((accepted, rejected), (11, 1))

    def test_completeness_allows_omitted_miss_only_actor_but_requires_damage(self):
        miss_only_ledger = _commander_multiattack_ledger((
            ("Hobgoblin Captain", True, 5),
            ("Hobgoblin Captain", False, 0),
            ("Hobgoblin Captain", True, 4),
            ("Goblin Squad B", False, 0),
        ), starting_hp=93, max_hp=93, round_number=2)
        omitted_miss_text = (
            "The Hobgoblin Captain's longsword hits Acheron for 5 slashing "
            "damage. A second swing misses, but the third hits for 4 more; "
            "Acheron remains alive at 84 hit points."
        )
        accepted = narrate_enemy_batch(
            miss_only_ledger, "The training pit echoes with steel.", {},
            self._fake_call(omitted_miss_text, []),
        )
        self.assertEqual(accepted.source, "llm")
        self.assertIsNone(accepted.reason_detail)

        damaging_ledger = _commander_multiattack_ledger((
            ("Hobgoblin Captain", True, 5),
            ("Hobgoblin Captain", False, 0),
            ("Hobgoblin Captain", True, 4),
            ("Goblin Squad B", True, 1),
        ), starting_hp=93, max_hp=93, round_number=2)
        omitted_damage_text = (
            "The Hobgoblin Captain's longsword hits Acheron for 5 slashing "
            "damage. A second swing misses, but the third hits for 4 more."
        )
        rejected = narrate_enemy_batch(
            damaging_ledger, "The training pit echoes with steel.", {},
            self._fake_call(omitted_damage_text, []),
        )
        self.assertEqual(rejected.source, "template")
        self.assertEqual(rejected.reason_detail, "ledger_entry_omitted")

    def test_completeness_rejects_omitted_kill_and_departure_outcomes(self):
        base = _audit_ledger()
        lethal_beta = replace(
            base.entries[1],
            damage_dice_rolls=(20,),
            damage_total=20,
            target_hp_after=0,
            target_status_after="dead",
        )
        lethal = replace(base, entries=(base.entries[0], lethal_beta))
        cases = (
            (
                lethal,
                "Goblin Alpha misses Vitreol. Goblin Beta hits Vitreol for 20 "
                "slashing damage.",
            ),
            (
                replace(
                    base,
                    departures=(EnemyDeparture(
                        CombatantIdentity("Goblin Alpha", "enemy"), "fled"
                    ),),
                ),
                "Goblin Alpha misses Vitreol. Goblin Beta hits Vitreol for 7 "
                "slashing damage.",
            ),
            (
                replace(
                    base,
                    departures=(EnemyDeparture(
                        CombatantIdentity("Goblin Alpha", "enemy"), "surrendered"
                    ),),
                ),
                "Goblin Alpha misses Vitreol. Goblin Beta hits Vitreol for 7 "
                "slashing damage.",
            ),
        )

        for ledger, response in cases:
            with self.subTest(response=response):
                result = narrate_enemy_batch(
                    ledger, "The training pit echoes with steel.", {},
                    self._fake_call(response, []),
                )
                self.assertEqual(result.source, "template")
                self.assertEqual(result.reason_detail, "ledger_entry_omitted")

    def test_completeness_rejects_intermediate_hp_as_final_batch_hp(self):
        ledger = _commander_multiattack_ledger((
            ("Hobgoblin Captain", True, 5),
            ("Hobgoblin Captain", True, 7),
            ("Hobgoblin Captain", True, 8),
            ("Goblin Squad A", True, 5),
            ("Goblin Squad B", True, 3),
        ), starting_hp=93, max_hp=93, target_name="Merisiel")
        response = (
            "The Hobgoblin Captain struck Merisiel three times with a longsword, "
            "dealing 5, 7, and 8 slashing damage, leaving her at 73 HP. "
            "Goblin Squad A hits Merisiel for 5 slashing damage. Goblin Squad B "
            "hits Merisiel for 3 slashing damage."
        )

        result = narrate_enemy_batch(
            ledger, "The training pit echoes with steel.", {},
            self._fake_call(response, []),
        )
        self.assertEqual(result.source, "template")
        self.assertEqual(result.reason_detail, "ledger_entry_omitted")

    def test_completeness_requires_cover_change_to_be_narrated(self):
        base = _audit_ledger()
        ledger = replace(
            base,
            cover_updates=(EnemyCoverUpdate(
                CombatantIdentity("Goblin Alpha", "enemy"), "RACKS", "half"
            ),),
        )
        accepted_text = (
            "Goblin Alpha takes half cover behind the racks. Goblin Beta hits "
            "Vitreol for 7 slashing damage."
        )
        accepted = narrate_enemy_batch(
            ledger, "The training pit echoes with steel.", {},
            self._fake_call(accepted_text, []),
        )
        self.assertEqual(accepted.source, "llm")

        omitted = narrate_enemy_batch(
            ledger, "The training pit echoes with steel.", {},
            self._fake_call(
                "Goblin Alpha moves behind the racks. Goblin Beta hits Vitreol "
                "for 7 slashing damage.",
                [],
            ),
        )
        self.assertEqual(omitted.source, "template")
        self.assertEqual(omitted.reason_detail, "ledger_entry_omitted")
        self.assertIn("Goblin Alpha takes half cover", omitted.text)

    def test_captured_gate4_narrations_accept_implicit_cover_clears(self):
        enemy_names = ("Goblin Squad A", "Goblin Squad B", "Hobgoblin Captain")
        surrender_ledger = _captured_batch_ledger(
            (),
            departures=tuple(
                EnemyDeparture(CombatantIdentity(name, "enemy"), "surrendered")
                for name in enemy_names
            ),
            cover_clear=enemy_names,
        )
        surrender_texts = (
            "Goblin Squad A surrenders, followed by Goblin Squad B and the "
            "Hobgoblin Captain.",
            "At the splintered practice stakes, Goblin Squad A surrendered, "
            "followed by Goblin Squad B. The Hobgoblin Captain surrendered as well.",
        )
        for response in surrender_texts:
            with self.subTest(response=response):
                result = narrate_enemy_batch(
                    surrender_ledger, "The practice pit is quiet.", {},
                    self._fake_call(response, []),
                )
                self.assertEqual(result.source, "llm")
                self.assertIsNone(result.reason_detail)

        mixed_attack_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", True, 6, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 5, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 7, "slashing", False),
                ("Goblin Squad A", "Shortbow", True, 3, "piercing", False),
                ("Goblin Squad B", "Shortbow", True, 7, "piercing", False),
            ),
            starting_hp=139,
            target_max_hp=139,
            cover_clear=("Hobgoblin Captain",),
        )
        mixed_attack_text = (
            "The Hobgoblin Captain struck Acheron three times with its longsword, "
            "dealing 6, then 5, then 7 slashing damage. Goblin Squad A hit Acheron "
            "with a shortbow for 3 piercing damage, followed by Goblin Squad B\u2019s "
            "shortbow hit for 7. Acheron remained alive at 111 HP."
        )
        mixed_attack = narrate_enemy_batch(
            mixed_attack_ledger, "The practice pit rings with steel.", {},
            self._fake_call(mixed_attack_text, []),
        )
        self.assertEqual(mixed_attack.source, "llm")
        self.assertIsNone(mixed_attack.reason_detail)

        melee_misses_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", True, 9, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 9, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 5, "slashing", False),
                ("Goblin Squad A", "Shortbow", False, 0, "piercing", False),
                ("Goblin Squad B", "Shortbow", False, 0, "piercing", False),
            ),
            cover_clear=("Hobgoblin Captain",),
        )
        melee_misses_text = (
            "The Hobgoblin Captain\u2019s longsword strikes Acheron three times, "
            "dealing 9, 9, and 5 slashing damage. Acheron remains alive at 208 HP. "
            "Goblin Squad A\u2019s shortbow misses, and Goblin Squad B\u2019s shortbow misses."
        )
        melee_misses = narrate_enemy_batch(
            melee_misses_ledger, "The practice pit rings with steel.", {},
            self._fake_call(melee_misses_text, []),
        )
        self.assertEqual(melee_misses.source, "llm")
        self.assertIsNone(melee_misses.reason_detail)

        negative_variants = (
            (
                mixed_attack_ledger,
                mixed_attack_text.replace("then 7 slashing damage", "then 8 slashing damage"),
                "number_mismatch",
            ),
            (
                mixed_attack_ledger,
                mixed_attack_text.replace(
                    ", followed by Goblin Squad B\u2019s shortbow hit for 7", ""
                ).replace("at 111 HP", "at 118 HP"),
                "ledger_entry_omitted",
            ),
            (
                mixed_attack_ledger,
                mixed_attack_text.replace("at 111 HP", "at 112 HP"),
                "number_mismatch",
            ),
        )
        for ledger, response, reason in negative_variants:
            with self.subTest(reason=reason, response=response):
                result = narrate_enemy_batch(
                    ledger, "The practice pit rings with steel.", {},
                    self._fake_call(response, []),
                )
                self.assertEqual(result.source, "template")
                self.assertEqual(result.reason_detail, reason)

    def test_missed_twice_is_checked_as_a_miss_count_not_damage(self):
        ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", True, 10, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Goblin Squad A", "Shortbow", True, 8, "piercing", True),
                ("Goblin Squad B", "Shortbow", True, 4, "piercing", False),
            ),
            cover_clear=("Hobgoblin Captain",),
        )
        text = (
            "The Hobgoblin Captain\u2019s longsword struck Acheron for 10 slashing "
            "damage, then missed twice. Goblin Squad A scored a critical hit with "
            "its shortbow, dealing 8 piercing damage. Goblin Squad B\u2019s shortbow "
            "hit for 4 more piercing damage. Acheron finished the phase at 209 HP."
        )
        accepted = narrate_enemy_batch(
            ledger, "The practice pit rings with steel.", {},
            self._fake_call(text, []),
        )
        self.assertEqual(accepted.source, "llm")
        self.assertIsNone(accepted.reason_detail)

        misses_after_count = (
            "The Hobgoblin Captain\u2019s longsword struck Acheron for 10 slashing "
            "damage. The captain\u2019s next two swings miss. Goblin Squad A "
            "scored a critical hit with its shortbow, dealing 8 piercing damage. "
            "Goblin Squad B\u2019s shortbow hit for 4 more piercing damage. Acheron "
            "finished the phase at 209 HP."
        )
        accepted_after_count = narrate_enemy_batch(
            ledger, "The practice pit rings with steel.", {},
            self._fake_call(misses_after_count, []),
        )
        self.assertEqual(accepted_after_count.source, "llm")
        self.assertIsNone(accepted_after_count.reason_detail)

        wrong_miss_count = narrate_enemy_batch(
            ledger, "The practice pit rings with steel.", {},
            self._fake_call(text.replace("missed twice", "missed three times"), []),
        )
        self.assertEqual(wrong_miss_count.source, "template")
        self.assertEqual(wrong_miss_count.reason_detail, "number_mismatch")

        wrong_count_after_verb = narrate_enemy_batch(
            ledger, "The practice pit rings with steel.", {},
            self._fake_call(
                misses_after_count.replace("next two swings", "next three swings"),
                [],
            ),
        )
        self.assertEqual(wrong_count_after_verb.source, "template")
        self.assertEqual(wrong_count_after_verb.reason_detail, "number_mismatch")

        capitalized_alias = narrate_enemy_batch(
            ledger, "The practice pit rings with steel.", {},
            self._fake_call(
                misses_after_count.replace("The captain\u2019s", "The Captain\u2019s"),
                [],
            ),
        )
        self.assertEqual(capitalized_alias.source, "template")
        self.assertEqual(capitalized_alias.reason_detail, "unknown_name")

    def test_followed_by_departure_group_checks_every_named_actor(self):
        base = _audit_ledger()
        all_depart = replace(
            base,
            departures=(
                EnemyDeparture(CombatantIdentity("Goblin Alpha", "enemy"), "fled"),
                EnemyDeparture(CombatantIdentity("Goblin Beta", "enemy"), "fled"),
            ),
        )
        response = (
            "Goblin Beta hits Vitreol for 7 slashing damage. Goblin Alpha flees, "
            "followed by Goblin Beta."
        )
        accepted = narrate_enemy_batch(
            all_depart, "A torchlit arena.", {}, self._fake_call(response, []),
        )
        self.assertEqual(accepted.source, "llm")
        self.assertIsNone(accepted.reason_detail)

        alpha_only = replace(
            base,
            departures=(
                EnemyDeparture(CombatantIdentity("Goblin Alpha", "enemy"), "fled"),
            ),
        )
        rejected = narrate_enemy_batch(
            alpha_only, "A torchlit arena.", {}, self._fake_call(response, []),
        )
        self.assertEqual(rejected.source, "template")
        self.assertEqual(rejected.reason_detail, "departure_claim_contradiction")

    def test_g5t_smoke3_numbered_narration_passes_and_contradictions_fail(self):
        ledger = _g5t_smoke3_ledger()
        smoke3_narration = (
            "The Hobgoblin Captain swung at Kira three times: the first strike "
            "missed, the second hit for 7 slashing damage, and the third missed. "
            "Goblin Squad A landed a critical scimitar strike for 8 slashing "
            "damage. Goblin Squad B's scimitar missed. Kira remained alive at "
            "78 of 93 HP."
        )
        calls = []
        result = narrate_enemy_batch(
            ledger, "The training pit echoes with steel.", {},
            self._fake_call(smoke3_narration, calls),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.source, "llm")
        self.assertIsNone(result.reason_detail)
        self.assertEqual(result.text, smoke3_narration)

        contradictions = (
            smoke3_narration.replace("for 7 slashing damage", "for 9 slashing damage"),
            smoke3_narration.replace("78 of 93 HP", "79 of 93 HP"),
            smoke3_narration.replace("78 of 93 HP", "78 of 94 HP"),
            smoke3_narration.replace(
                "swung at Kira three times", "hit Kira twice"
            ),
        )
        for response in contradictions:
            with self.subTest(response=response):
                result = narrate_enemy_batch(
                    ledger, "The training pit echoes with steel.", {},
                    self._fake_call(response, []),
                )
                self.assertEqual(result.source, "template")
                self.assertEqual(result.reason_detail, "number_mismatch")

    def test_captured_ordinal_attack_references_follow_ledger_order(self):
        p1_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 3, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Goblin Squad A", "Scimitar", True, 4, "slashing", False),
                ("Goblin Squad B", "Scimitar", False, 0, "slashing", False),
            ),
            starting_hp=213,
            target_max_hp=231,
        )
        p1_text = (
            "The Hobgoblin Captain\u2019s first longsword swing missed Acheron. "
            "The second struck for 3 slashing damage; the third missed. Goblin "
            "Squad A hit Acheron with a scimitar for 4 slashing damage. Goblin "
            "Squad B\u2019s scimitar missed. Acheron finished the batch at 206 HP."
        )

        p4_second_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", True, 6, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 12, "slashing", True),
                ("Goblin Squad A", "Scimitar", False, 0, "slashing", False),
                ("Goblin Squad B", "Scimitar", True, 8, "slashing", False),
            ),
            starting_hp=93,
            target_max_hp=93,
        )
        p4_second_text = (
            "The Hobgoblin Captain\u2019s first longsword strike hit Acheron, then "
            "its second swung wide. A third blow landed critically, leaving "
            "Acheron at 75 HP. Goblin Squad A\u2019s scimitar missed; Goblin Squad "
            "B\u2019s scimitar struck, leaving Acheron at 67 HP."
        )

        p4_next_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 6, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Goblin Squad A", "Scimitar", False, 0, "slashing", False),
                ("Goblin Squad B", "Scimitar", True, 4, "slashing", False),
            ),
            starting_hp=93,
            target_max_hp=93,
        )
        p4_next_text = (
            "The Hobgoblin Captain\u2019s first longsword swing missed Acheron, "
            "but the next struck, dealing 6 slashing damage. Its third swing "
            "missed. Goblin Squad A\u2019s scimitar attack also missed. Goblin "
            "Squad B then hit Acheron with a scimitar for 4 slashing damage, "
            "leaving him at 83 HP."
        )

        for ledger, response in (
            (p1_ledger, p1_text),
            (p4_second_ledger, p4_second_text),
            (p4_next_ledger, p4_next_text),
        ):
            with self.subTest(response=response):
                result = narrate_enemy_batch(
                    ledger, "The practice pit rings with steel.", {},
                    self._fake_call(response, []),
                )
                self.assertEqual(result.source, "llm")
                self.assertIsNone(result.reason_detail)

        wrong_order_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", False, 0, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 3, "slashing", False),
                ("Goblin Squad A", "Scimitar", True, 4, "slashing", False),
                ("Goblin Squad B", "Scimitar", False, 0, "slashing", False),
            ),
            starting_hp=213,
            target_max_hp=231,
        )
        wrong_order_text = p1_text.replace(
            "The second struck for 3 slashing damage; the third missed.",
            "The second struck for 3 slashing damage; the third struck for 3 "
            "slashing damage.",
        )
        rejected = narrate_enemy_batch(
            wrong_order_ledger, "The practice pit rings with steel.", {},
            self._fake_call(wrong_order_text, []),
        )
        self.assertEqual(rejected.source, "template")
        self.assertEqual(rejected.reason_detail, "hit_claim_contradiction")

        wide_hit_ledger = _captured_batch_ledger(
            (
                ("Hobgoblin Captain", "Longsword", True, 6, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 1, "slashing", False),
                ("Hobgoblin Captain", "Longsword", True, 11, "slashing", True),
                ("Goblin Squad A", "Scimitar", False, 0, "slashing", False),
                ("Goblin Squad B", "Scimitar", True, 8, "slashing", False),
            ),
            starting_hp=93,
            target_max_hp=93,
        )
        wide_rejected = narrate_enemy_batch(
            wide_hit_ledger, "The practice pit rings with steel.", {},
            self._fake_call(p4_second_text, []),
        )
        self.assertEqual(wide_rejected.source, "template")
        self.assertEqual(wide_rejected.reason_detail, "miss_claim_contradiction")

    def test_prompt_supplied_squad_names_and_curly_possessives_pass_audit(self):
        base = _audit_ledger()
        first, second = base.entries
        ledger = replace(base, entries=(
            replace(first, actor=CombatantIdentity("Goblin Squad A", "enemy")),
            replace(second, actor=CombatantIdentity("Goblin Squad B", "enemy")),
        ))
        responses = (
            "Goblin Squad A's scimitar misses Vitreol. Goblin Squad B's scimitar "
            "hits Vitreol for 7 slashing damage; he has 13 HP left.",
            "Goblin Squad A\u2019s scimitar misses Vitreol. Goblin Squad B\u2019s scimitar "
            "hits Vitreol for 7 slashing damage; he has 13 HP left.",
        )

        for response in responses:
            with self.subTest(response=response):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "The training pit echoes with steel.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.source, "llm")
                self.assertIsNone(result.reason_detail)

        shared_prefix_response = (
            "Goblin Squad attacks Vitreol and misses. Goblin Squad B hits Vitreol "
            "for 7 slashing damage; he has 13 HP left."
        )
        self.assertIsNone(_first_unknown_name(shared_prefix_response, _ledger_names(ledger)))
        result = narrate_enemy_batch(
            ledger, "The training pit echoes with steel.", {},
            self._fake_call(shared_prefix_response, []),
        )
        # The shared squad stem is known, but its attack claim cannot be
        # attributed uniquely between a miss and a hit in this ledger.
        self.assertEqual(result.source, "template")
        self.assertEqual(result.reason_detail, "claim_attribution_ambiguous")

    def test_invented_squad_suffix_remains_unknown_name(self):
        base = _audit_ledger()
        first, second = base.entries
        ledger = replace(base, entries=(
            replace(first, actor=CombatantIdentity("Goblin Squad A", "enemy")),
            replace(second, actor=CombatantIdentity("Goblin Squad B", "enemy")),
        ))
        result = narrate_enemy_batch(
            ledger, "The training pit.", {},
            self._fake_call("Goblin Squad C joins the attack.", []),
        )
        self.assertEqual(result.source, "template")
        self.assertEqual(result.reason_detail, "unknown_name")

    def test_realistic_wrong_multi_enemy_narrations_are_rejected_with_rule_codes(self):
        same_target = _audit_ledger()
        alpha_targets_acheron = _audit_ledger(alpha_target="Acheron")
        cases = (
            (alpha_targets_acheron, "Goblin Alpha attacks Vitreol and misses.",
             "target_claim_contradiction"),
            (same_target, "Goblin Alpha hits Vitreol.", "hit_claim_contradiction"),
            (same_target, "Goblin Beta misses Vitreol.", "miss_claim_contradiction"),
            (same_target, "Goblin Beta deals 8 slashing damage to Vitreol.",
             "number_mismatch"),
            (same_target, "Goblin Beta hits Vitreol for 7 slashing damage, leaving him at 12 HP.",
             "number_mismatch"),
            (same_target, "Ogre joins the attack.", "unknown_name"),
            (same_target, "Goblin Beta kills Vitreol.", "kill_claim_contradiction"),
            (same_target, "Goblin Alpha deals 7 slashing damage to Vitreol.",
             "number_mismatch"),
            (same_target, "Goblin Alpha rolls 7 against Vitreol.", "number_mismatch"),
            (same_target, "Goblin Beta knocks Vitreol out.", "defeat_claim_contradiction"),
        )

        for ledger, response, reason in cases:
            with self.subTest(response=response):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "A torchlit arena.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.source, "template")
                self.assertEqual(result.reason_detail, reason)

    def test_flee_and_surrender_claims_are_departure_aware(self):
        base = _audit_ledger()
        departed = replace(
            base,
            departures=(EnemyDeparture(CombatantIdentity("Goblin Alpha", "enemy"), "fled"),),
        )
        cases = (
            (
                departed,
                "Goblin Alpha flees. Goblin Beta hits Vitreol for 7 slashing damage.",
                "llm",
                None,
            ),
            (
                departed,
                "Goblin Alpha fled from the arena. Goblin Beta hits Vitreol for 7 "
                "slashing damage.",
                "llm",
                None,
            ),
            (departed, "Goblin Beta flees.", "template", "departure_claim_contradiction"),
            (
                departed,
                "Goblin Alpha and Goblin Beta flee.",
                "template",
                "departure_claim_contradiction",
            ),
            (
                replace(
                    base,
                    departures=(EnemyDeparture(
                        CombatantIdentity("Goblin Alpha", "enemy"), "surrendered"
                    ),),
                ),
                "Goblin Alpha surrenders. Goblin Beta hits Vitreol for 7 slashing "
                "damage.",
                "llm",
                None,
            ),
        )
        for ledger, response, source, reason in cases:
            with self.subTest(response=response):
                calls = []
                result = narrate_enemy_batch(
                    ledger, "A torchlit arena.", {},
                    self._fake_call(response, calls),
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.source, source)
                self.assertEqual(result.reason_detail, reason)
                if source == "template":
                    self.assertIn("Goblin Alpha disengages and flees", result.text)

    def test_departures_are_bounded_authoritative_narration_facts(self):
        ledger = replace(
            _audit_ledger(),
            departures=(EnemyDeparture(CombatantIdentity("Goblin Alpha", "enemy"), "fled"),),
        )
        messages = build_enemy_batch_narration_messages(
            ledger,
            "A torchlit arena.",
            {},
            tactical_plan_intent=[{
                "actor": "Goblin Alpha",
                "intent": "flee",
                "defeat_reason": "fled",
            }],
        )
        payload = json.loads(messages[1]["content"])
        self.assertEqual(
            payload["authoritative_ledger"]["departures"],
            [{"name": "Goblin Alpha", "reason": "fled"}],
        )
        self.assertEqual(payload["tactical_plan_intent"], [{
            "actor": "Goblin Alpha",
            "intent": "flee",
            "defeat_reason": "fled",
        }])
        self.assertIn("Goblin Alpha disengages and flees", build_enemy_batch_template_narration(ledger))

    def test_rejected_narration_logs_bounded_text_and_rule_only_to_debug(self):
        ledger = _audit_ledger()
        rejected = "Goblin Alpha misses Vitreol. Ogre " + ("waits quietly. " * 120)
        calls = []
        with mock.patch("core.combat.enemy_narration.debug") as debug_log:
            result = narrate_enemy_batch(
                ledger, "A torchlit arena.", {},
                self._fake_call(rejected, calls),
            )

        self.assertEqual(result.reason_detail, "unknown_name")
        self.assertEqual(debug_log.call_count, 1)
        message = debug_log.call_args.args[0]
        self.assertLessEqual(len(message), 1000)
        self.assertIn("rule=unknown_name", message)
        self.assertIn("Ogre", message)
        self.assertEqual(debug_log.call_args.kwargs["category"], "combat_events")
        self.assertNotIn("Ogre", result.text)

    def test_prompt_asset_is_ascii_and_messages_are_prose_only(self):
        prompt_bytes = PROMPT_PATH.read_bytes()
        prompt_bytes.decode("ascii")
        ledger = _ledger()
        messages = build_enemy_batch_narration_messages(
            ledger, "A cold rain falls.", {}
        )
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertEqual(messages[0]["content"].encode("ascii"), prompt_bytes)
        user_payload = json.loads(messages[1]["content"])
        self.assertEqual(user_payload["authoritative_ledger"]["batch_id"], ledger.batch_id)
        self.assertEqual(len(user_payload["authoritative_ledger"]["entries"]), len(ledger.entries))
        self.assertNotRegex(messages[0]["content"], re.compile(r"[\u0080-\uffff]"))


if __name__ == "__main__":
    unittest.main()
