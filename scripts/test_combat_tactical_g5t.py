# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free G5T capture identity and evidence projection contracts."""

import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.combat.enemy_batch_orchestrator import _creature_descriptions
from core.combat.tactical_brain import build_commander_plan_messages

# Importing the shared capture harness arms its provider, network, and write tripwires.
from scripts import test_capture_drive as guarded_capture_import
from scripts.combat_tactical_test_support import build_g5t_scenario, build_menus

capture_evidence = guarded_capture_import.capture_evidence
fixtures = guarded_capture_import.fixtures


class CombatTacticalG5TCaptureTests(unittest.TestCase):
    def setUp(self):
        self.run_root = capture_evidence.G5T_RUN_ROOT
        self.root_existed = self.run_root.exists()
        self.run_root.mkdir(parents=True, exist_ok=True)
        if not self.root_existed:
            self.addCleanup(self._remove_empty_run_root)
        self.scratch = tempfile.TemporaryDirectory(
            prefix="task53-g5t-evidence-", dir=str(self.run_root))
        self.addCleanup(self.scratch.cleanup)

    def _remove_empty_run_root(self):
        try:
            self.run_root.rmdir()
        except OSError:
            pass

    def test_commander_prompt_guides_cover_and_self_preservation_choices(self):
        prompt = (ROOT / "prompts" / "combat" / "commander_plan_prompt.txt").read_text(
            encoding="ascii"
        )
        self.assertIn("Use a listed cover feature when it meaningfully protects an actor.", prompt)
        self.assertIn("A listed flee option means the actor uses its action to Disengage", prompt)
        self.assertIn("makes no", prompt)
        self.assertIn("treat that preference as meaningful guidance", prompt)
        self.assertIn("This is a preference, not an automatic choice", prompt)
        self.assertIn("same plan", prompt)
        self.assertIn(
            "When a near-death commander is the only eligible enemy actor", prompt
        )
        self.assertIn("treat it as abandoned by its squad", prompt)
        self.assertIn("strongly prefer one listed", prompt)
        self.assertIn("choose exactly one", prompt)
        self.assertIn("not forced behavior", prompt)
        self.assertIn(
            "Python validates the issued IDs and owns all outcomes",
            " ".join(prompt.split()),
        )

    def test_g5t_captain_disposition_supports_yielding_when_abandoned(self):
        captain = fixtures.build_g5t_commander_monster()
        disposition = captain["description"]

        self.assertLessEqual(len(disposition), 240)
        self.assertIn("disciplined hobgoblin officer", disposition)
        self.assertIn("If near death after his troops have fled or fallen", disposition)
        self.assertIn("prefers to yield rather than die pointlessly", disposition)
        self.assertIn("otherwise he fights with tactical discipline", disposition)

    def test_g5t_captain_disposition_reaches_only_eligible_plan_actor(self):
        scenario = build_g5t_scenario(1)
        scenario["enemy_turn_window"] = [{
            "name": fixtures.G5T_COMMANDER_NAME,
            "kind": "enemy",
        }]
        menus = build_menus(scenario)
        dispositions = _creature_descriptions(
            scenario["encounter"], scenario["monster_definitions"]
        )
        messages = build_commander_plan_messages(
            menus, scenario["pc_states"], actor_dispositions=dispositions
        )

        projected = json.loads(messages[1]["content"])
        self.assertEqual(
            [row["actor"] for row in projected["eligible_actors"]],
            [fixtures.G5T_COMMANDER_NAME],
        )
        self.assertEqual(
            projected["eligible_actors"][0]["disposition"],
            fixtures.build_g5t_commander_monster()["description"],
        )

    def test_g5t_goblin_disposition_prefers_flight_without_forcing_choice(self):
        goblin = fixtures.build_g5t_goblin_monster()
        disposition = goblin["description"]

        self.assertLessEqual(len(disposition), 240)
        self.assertIn("When bloodied and offered direct flee", disposition)
        self.assertIn("prefer escape over attacking or taking cover", disposition)
        self.assertIn("Nimble Escape", disposition)
        self.assertIn("surrender individually only when cornered", disposition)
        self.assertIn("near death", disposition)
        self.assertEqual(
            [ability["name"] for ability in goblin["specialAbilities"]],
            ["Nimble Escape"],
        )

    @staticmethod
    def _snapshot(party_size, encounter, *, active_encounter, observation=None):
        roster = fixtures.PC_NAMES[:party_size]
        return {
            "records": {
                "party_tracker.json": {
                    "status": "ok", "partyMembers": list(roster),
                    "worldConditions": {"activeCombatEncounter": active_encounter},
                },
                "selected_encounter": {
                    "status": "ok", "encounterId": encounter["encounterId"],
                    "creatures": copy.deepcopy(encounter["creatures"]),
                },
            },
            "observation": copy.deepcopy(observation or {}),
        }

    def _observed_g5t_checks(self, party_size=1, *, omit=None, illegal_choice=False,
                             decision_source="llm_tactical", omit_plan_results=False,
                             squad_followed=True, zero_applied=False,
                              unobserved_self_preservation=False,
                              positive_hp_self_preservation=False,
                              removed_by_exit=False,
                              omit_auto_exit=False,
                              uncovered_attack=False, invalid_self_preservation=False,
                             invalid_cover_attack=False):
        scenario = "g5t-commander-p%d" % party_size
        profile = fixtures.build_gate_profile("g5t", scenario, party_size)
        fixture = fixtures.build_g5t_commander_fixture(party_size)
        initial_creatures = copy.deepcopy(fixture["encounter"]["creatures"])
        final_creatures = copy.deepcopy(initial_creatures)
        goblin_a = next(row for row in final_creatures
                        if row.get("name") == fixtures.G5T_GOBLIN_NAMES[0])
        goblin_b = next(row for row in final_creatures
                        if row.get("name") == fixtures.G5T_GOBLIN_NAMES[1])
        if not unobserved_self_preservation:
            goblin_a.update({"currentHitPoints": 9 if positive_hp_self_preservation else 0,
                             "status": "defeated", "defeatReason": "fled"})
            if invalid_self_preservation:
                goblin_a["defeatReason"] = "surrendered"
            goblin_b.update({"currentHitPoints": 0, "status": "defeated",
                             "defeatReason": "surrendered"})

        before = self._snapshot(party_size, fixture["encounter"], active_encounter=scenario)
        after_encounter = copy.deepcopy(fixture["encounter"])
        after_encounter["creatures"] = final_creatures
        after = self._snapshot(party_size, after_encounter, active_encounter=None)

        covered_creatures = copy.deepcopy(initial_creatures)
        covered_goblin = next(row for row in covered_creatures
                              if row.get("name") == fixtures.G5T_GOBLIN_NAMES[1])
        covered_goblin.update({"coverFeatureId": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                               "coverType": "half"})
        covered_encounter = {"encounterId": scenario, "creatures": covered_creatures}
        uncovered_creatures = copy.deepcopy(initial_creatures)
        uncovered_goblin = next(row for row in uncovered_creatures
                                if row.get("name") == fixtures.G5T_GOBLIN_NAMES[1])
        uncovered_goblin.pop("coverFeatureId", None)
        uncovered_goblin.pop("coverType", None)
        uncovered_encounter = {"encounterId": scenario,
                               "creatures": uncovered_creatures}
        scripted_steps = fixtures.build_g5t_script_steps(party_size)
        attack_step = next(row for row in scripted_steps
                           if "covered-target attack" in row["label"])
        self.assertGreaterEqual(
            sum(row["input"] == attack_step["input"] for row in scripted_steps), 2
        )
        step_rows = []
        for script_step in scripted_steps:
            snapshot_encounter = fixture["encounter"]
            if script_step["step"] == attack_step["step"]:
                snapshot_encounter = uncovered_encounter if uncovered_attack else covered_encounter
            before_observation = {"input": script_step["input"], "label": script_step["label"]}
            after_observation = {}
            if script_step["step"] == attack_step["step"]:
                if uncovered_attack:
                    attack_output = (
                        "Dungeon Master: Hit! (Rolled 19 vs AC 15). Attack result committed."
                    )
                elif invalid_cover_attack:
                    attack_output = (
                        "Dungeon Master: Hit! (Rolled 19 vs AC 16). Attack result committed."
                    )
                else:
                    attack_output = (
                        "Dungeon Master: Hit! (Rolled 19 vs AC 17). Attack result committed."
                    )
                after_observation["actual_backend_outputs"] = [{
                    "type": "narration", "content": attack_output,
                }]
            step_rows.append({
                "before": self._snapshot(
                    party_size, snapshot_encounter, active_encounter=scenario,
                    observation=before_observation),
                "after": self._snapshot(
                    party_size, snapshot_encounter, active_encounter=scenario,
                    observation=after_observation),
            })

        from utils.combat_latency_trace import build_run_local_actor_ids

        actor_ids = build_run_local_actor_ids(initial_creatures)
        events = []
        batches = [row for row in profile["fixture"]["steps"]
                   if row.get("unit_type") == "batch"]
        exit_batch_id = (
            ("enemy:r1" if removed_by_exit and any(
                row.get("self_preservation_outcome") == "fled" for row in events
            ) else "enemy:r2")
            if removed_by_exit else batches[-1]["trace_batch_id"]
        )
        omitted = set(omit or [])
        for batch_index, batch in enumerate(batches):
            batch_id = batch["trace_batch_id"]
            if int(batch_id.rsplit("r", 1)[1]) > int(exit_batch_id.rsplit("r", 1)[1]):
                continue
            if batch_id in omitted:
                continue
            if batch.get("requires_combat_exit") is True:
                events.append({
                    "event_type": "decision", "decision_point": "enemy_batch_resolution",
                    "decision_source": "deterministic", "decision_outcome": "resolver_supported",
                    "decision_reason": "ledger_supported", "batch_id": batch_id,
                })
                continue
            events.append({
                "event_type": "decision", "decision_point": "enemy_batch_resolution",
                "decision_source": decision_source, "batch_id": batch_id,
            })
            if decision_source == "llm_tactical" and not omit_plan_results:
                departed = set()
                if batch_index >= 1:
                    departed.add(actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[0].casefold())])
                if batch_index >= 2:
                    departed.add(actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[1].casefold())])
                current_menu_ids = [
                    actor_id for (kind, _name), actor_id in actor_ids.items()
                    if kind == "enemy" and actor_id not in departed
                ]
                events.append({
                    "event_type": "combat_observation",
                    "observation": "combat_tactical_plan_result", "batch_id": batch_id,
                    "tactical_plan_outcome": "accepted",
                    "actor_ids": current_menu_ids,
                    "target_ids": current_menu_ids,
                })
            if decision_source == "llm_tactical" and not zero_applied:
                legal_count = 1 if illegal_choice and batch_index == 0 else 2
                events.append({
                    "event_type": "combat_observation",
                    "observation": "applied_choice_legality", "batch_id": batch_id,
                    "applied_choice_count": 2, "legal_applied_choice_count": legal_count,
                })
                events.append({
                    "event_type": "combat_observation",
                    "observation": "commander_squad_follows_orders", "batch_id": batch_id,
                    "followed_orders": squad_followed and not zero_applied,
                    "issued_choice_count": 2,
                    "applied_choice_count": 0 if zero_applied else 2 if squad_followed else 1,
                })
            elif decision_source == "llm_tactical":
                events.append({
                    "event_type": "combat_observation",
                    "observation": "commander_squad_follows_orders", "batch_id": batch_id,
                    "followed_orders": False, "issued_choice_count": 2,
                    "applied_choice_count": 0,
                })
        if "fled" not in omitted and not unobserved_self_preservation:
            events.append({
                "event_type": "combat_observation",
                "observation": "combat_self_preservation_outcome",
                "actor_id": actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[0].casefold())],
                "self_preservation_outcome": "fled", "batch_id": "enemy:r1",
            })
        if "surrendered" not in omitted and not unobserved_self_preservation:
            events.append({
                "event_type": "combat_observation",
                "observation": "combat_self_preservation_outcome",
                "actor_id": actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[1].casefold())],
                "self_preservation_outcome": "surrendered", "batch_id": "enemy:r2",
            })
        if not omit_auto_exit:
            events.append({
                "event_type": "combat_observation", "observation": "xp_award",
                "source": "auto_exit", "batch_id": exit_batch_id, "amount": 100,
            })
        covered_actor_id = actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[1].casefold())]
        if "cover_applied" not in omitted:
            events.append({"observation": "combat_cover_outcome", "batch_id": "enemy:r1",
                           "actor_id": covered_actor_id,
                           "feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                           "cover_type": "half", "cover_state": "applied"})
        if "cover_expired" not in omitted and not unobserved_self_preservation:
            events.append({"observation": "combat_cover_outcome", "batch_id": "enemy:r2",
                           "actor_id": covered_actor_id,
                           "feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                           "cover_type": "half", "cover_state": "expired"})
        artifacts = {
            "trace": "trace.jsonl", "after_snapshot": "snapshots/after-run.json",
            "required_evidence_status": "ok", "trace_applicability": {"status": "required"},
        }
        checks = capture_evidence.observed_checks(
            profile, before, after, artifacts, steps=step_rows, observations=events)
        self.last_step_rows = step_rows
        return profile, checks, events, before, after

    @staticmethod
    def _evaluation_manifest(profile):
        expected_bounds = capture_evidence._expected_profile_bounds(profile)
        bounds = dict(expected_bounds)
        bounds.update({"turn_timeout_seconds": 150, "start_timeout_seconds": 30,
                       "turn_quiet_seconds": 1})
        count_names = (
            "step_attempts", "steps_sent", "backend_output_count", "control_request_attempts",
            "control_request_calls", "control_request_failures", "control_requests_sent",
            "active_switch_attempts", "active_switch_requests_sent", "blocked_step_attempts",
            "blocked_control_attempts", "timeouts", "step_caps_reached",
            "idle_settle_caps_reached", "active_switch_failures", "health_read_attempts",
            "exit_health_read_attempts", "start_timeout",
        )
        source_roots = (
            "core/combat/", "core/managers/combat_manager.py", "core/managers/multi_pc_combat.py",
            "core/managers/combat_state_sync.py", "main.py", "core/ai/action_handler.py",
            "utils/combat_latency_trace.py", "utils/ai_client_factory.py", "model_config.py",
        )
        relevant_sources = {path: hashlib.sha256(path.encode("ascii")).hexdigest()
                            for path in source_roots}
        dirty_sources = {}
        dirty_digest = hashlib.sha256(json.dumps(dirty_sources, sort_keys=True).encode("utf-8")).hexdigest()
        profile_contract = {key: profile.get(key) for key in
                            ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
        profile_contract["gate"] = "g5t"
        scenario_id, party_size = profile["scenario_id"], profile["party_size"]
        scenario_digest = hashlib.sha256(
            json.dumps(profile_contract, sort_keys=True).encode("utf-8")).hexdigest()
        local_key = capture_evidence.matrix_key(scenario_id, party_size)
        return {
            "gate": "g5t", "evidence_kind": "live-candidate", "live_eligible": True,
            "scenario": {"id": scenario_id, "branch": None, "phase": None,
                         "sha256": scenario_digest},
            "party": {"size": party_size},
            "counts": {key: 0 for key in count_names},
            "bounds": bounds,
            "source": {"head": "a" * 40, "relevant_source_sha256": relevant_sources,
                       "relevant_dirty_source_sha256": dirty_sources,
                       "relevant_dirty_sha256": dirty_digest},
            "sandbox_runtime": {"trace_gate": {"status": "ok", "enabled": True}},
            "prompt_identity_sha256": {"prompt-%d" % i: "b" * 64 for i in range(9)},
            "transport": {"client_source": "socketio.Client"},
            "artifacts": {"matrix_keys": [local_key], "required_evidence_status": "ok"},
        }

    def test_observed_checks_use_shared_actor_projection_and_trace_events(self):
        expected_ids = {
            "applied_choice_legality", "commander_squad_follows_orders",
            "self_preservation_removal", "cover_changes_effective_ac", "cover_expiration",
        }
        for party_size in (1, 4):
            profile, checks, _events, _before, _after = self._observed_g5t_checks(party_size)
            rows = {row["id"]: row for row in checks}
            self.assertTrue(expected_ids.issubset(rows))
            self.assertEqual({key: rows[key]["status"] for key in expected_ids},
                             {key: "PASS" for key in expected_ids})
            self.assertTrue(all(rows[key]["required"] is False for key in expected_ids))
            self.assertEqual(
                len(rows["applied_choice_legality"]["observations"]),
                len([row for row in profile["fixture"]["steps"]
                     if row.get("unit_type") == "batch"]),
            )
            self.assertEqual(rows["self_preservation_removal"]["observed"]["observations"][0][
                "defeat_reason"], "fled")
            self.assertEqual(rows["cover_changes_effective_ac"]["observed"]["effective_ac"], 17)
            self.assertEqual(rows["cover_expiration"]["observed"]["cover_inert_after_exit"], True)
            self.assertEqual(profile["fixture"]["fixture_id"], "g5t-commander-p%d" % party_size)

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, omit={"enemy:r2", "fled", "cover_expired"})
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["applied_choice_legality"]["status"], "BLOCKED")
        self.assertEqual(rows["self_preservation_removal"]["status"], "BLOCKED")
        self.assertEqual(rows["cover_expiration"]["status"], "BLOCKED")

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, omit={"fled", "surrendered", "cover_applied", "cover_expired"},
            unobserved_self_preservation=True, uncovered_attack=True)
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["self_preservation_removal"]["status"], "NOT_OBSERVED")
        self.assertEqual(rows["cover_changes_effective_ac"]["status"], "NOT_OBSERVED")
        self.assertEqual(rows["cover_expiration"]["status"], "BLOCKED")

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, uncovered_attack=True, omit={"cover_applied", "cover_expired"})
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["cover_changes_effective_ac"]["status"], "NOT_OBSERVED")
        self.assertEqual(rows["cover_changes_effective_ac"]["observed"]["attack_effective_ac"], 15)

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, invalid_self_preservation=True, invalid_cover_attack=True)
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["self_preservation_removal"]["status"], "FAIL")
        self.assertEqual(rows["cover_changes_effective_ac"]["status"], "FAIL")

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, positive_hp_self_preservation=True)
        removal = next(row for row in checks if row["id"] == "self_preservation_removal")
        positive_hp_row = next(row for row in removal["observed"]["observations"]
                               if row.get("outcome") == "fled")
        self.assertEqual(removal["status"], "PASS")
        self.assertEqual(positive_hp_row["current_hit_points"], 9)
        self.assertTrue(positive_hp_row["encounter_state_consistent"])

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, removed_by_exit=True)
        removal = next(row for row in checks if row["id"] == "self_preservation_removal")
        exit_row = next(row for row in removal["observed"]["observations"]
                        if row.get("outcome") == "surrendered")
        self.assertEqual(removal["status"], "PASS")
        self.assertTrue(exit_row["satisfied_by_exit"])
        self.assertIsNone(exit_row["actor_removed_from_later_actor_menus"])
        self.assertIsNone(exit_row["actor_removed_from_later_target_menus"])

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            4, omit_auto_exit=True)
        removal = next(row for row in checks if row["id"] == "self_preservation_removal")
        surrendered_row = next(row for row in removal["observed"]["observations"]
                               if row.get("outcome") == "surrendered")
        self.assertEqual(surrendered_row["status"], "PASS")
        self.assertFalse(surrendered_row["satisfied_by_exit"])
        self.assertTrue(surrendered_row["actor_removed_from_later_actor_menus"])
        self.assertTrue(surrendered_row["actor_removed_from_later_target_menus"])

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, illegal_choice=True)
        legality = next(row for row in checks if row["id"] == "applied_choice_legality")
        self.assertEqual(legality["status"], "FAIL")
        self.assertIn("FAIL", {row["status"] for row in legality["observations"]})

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, decision_source="deterministic")
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["applied_choice_legality"]["status"], "NOT_APPLICABLE")
        self.assertEqual(rows["commander_squad_follows_orders"]["status"], "BLOCKED")
        no_plan_manifest = self._evaluation_manifest(_profile)
        no_plan_evaluation = capture_evidence.evaluate_evidence(
            no_plan_manifest, checks, no_plan_manifest["artifacts"],
            run_dir=pathlib.Path(self.scratch.name) / "no-plan",
            integrity={"failures": []}, profile=_profile,
        )
        self.assertNotIn("applied_choice_legality", {
            row["id"] for row in no_plan_evaluation["blocked_required_checks"]
        })

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, omit_plan_results=True)
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["applied_choice_legality"]["status"], "BLOCKED")
        self.assertEqual(rows["commander_squad_follows_orders"]["status"], "PASS")

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, squad_followed=False)
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["commander_squad_follows_orders"]["status"], "FAIL")
        self.assertEqual(
                [row["status"] for row in
                 rows["commander_squad_follows_orders"]["observed"]["observations"]],
                ["NOT_APPLICABLE" if row.get("requires_combat_exit") is True else "FAIL"
                 for row in _profile["fixture"]["steps"]
                 if row.get("unit_type") == "batch"],
        )

        _profile, checks, _events, _before, _after = self._observed_g5t_checks(
            1, zero_applied=True)
        rows = {row["id"]: row for row in checks}
        self.assertEqual(rows["applied_choice_legality"]["status"], "NOT_APPLICABLE")
        self.assertEqual(rows["commander_squad_follows_orders"]["status"], "FAIL")

    def test_duplicate_attack_input_uses_the_unique_covered_step_label(self):
        profile, checks, _events, _before, _after = self._observed_g5t_checks(1)
        scripted = fixtures.build_g5t_script_steps(1)
        covered = next(row for row in scripted
                       if "covered-target attack" in row["label"])
        duplicates = [pair["before"]["observation"] for pair in self.last_step_rows
                      if pair["before"]["observation"].get("input") == covered["input"]]
        self.assertGreaterEqual(len(duplicates), 2)
        self.assertEqual(sum(row.get("label") == covered["label"] for row in duplicates), 1)
        cover_check = next(row for row in checks if row["id"] == "cover_changes_effective_ac")
        self.assertEqual(cover_check["status"], "PASS")
        self.assertEqual(cover_check["observed"]["effective_ac"], 17)
        self.assertEqual(profile["scenario_id"], "g5t-commander-p1")

    def test_last_batch_after_snapshot_reference_falls_back_to_after_run(self):
        profile, _checks, events, before, after = self._observed_g5t_checks(4)
        run_dir = pathlib.Path(self.scratch.name) / "snapshot-fallback"
        snapshots = run_dir / "snapshots"
        snapshots.mkdir(parents=True)
        (snapshots / "after-run.json").write_text("{}\n", encoding="ascii")
        artifacts = {"trace": "trace.jsonl", "after_snapshot": "snapshots/after-run.json"}
        derived = capture_evidence.observed_checks(
            profile, before, after, artifacts, steps=self.last_step_rows,
            observations=events, run_dir=run_dir)
        legality = next(row for row in derived if row["id"] == "applied_choice_legality")
        last = legality["observations"][-1]
        self.assertEqual(last["evidence_refs"][-1], "snapshots/after-run.json")

    def test_later_fallback_batch_cohort_proves_departed_commander_removal(self):
        fixture = fixtures.build_g5t_commander_fixture(4)
        from utils.combat_latency_trace import build_run_local_actor_ids

        actor_ids = build_run_local_actor_ids(fixture["encounter"]["creatures"])
        captain_id = actor_ids[("enemy", fixtures.G5T_COMMANDER_NAME.casefold())]
        events = [
            {"event_type": "decision", "decision_point": "enemy_batch_resolution",
             "decision_source": "llm_fallback", "batch_id": "enemy:r4"},
            {"event_type": "combat_observation", "observation": "combat_action_batch",
             "batch_id": "enemy:r4", "validation_accepted": True,
             "enemy_phase_batch": True, "eligible_non_pc_cohort": [fixtures.G5T_GOBLIN_NAMES[0]],
             "explicit_actor_records": [],
             "affected_entities": [{"name": "Acheron", "source": "characterName"}]},
            {"event_type": "combat_observation", "observation": "combat_validation_result",
             "batch_id": "enemy:r4", "validation_accepted": True,
             "eligible_non_pc_cohort": [fixtures.G5T_GOBLIN_NAMES[0]]},
        ]
        self.assertEqual(
            capture_evidence._g5t_self_preservation_menu_removal(
                events, captain_id, "enemy:r3", actor_name=fixtures.G5T_COMMANDER_NAME,
                encounter_cleared=False, auto_exit_batches=set()),
            (True, True, False),
        )
        without_validation = [row for row in events
                              if row.get("observation") != "combat_validation_result"]
        self.assertEqual(
            capture_evidence._g5t_self_preservation_menu_removal(
                without_validation, captain_id, "enemy:r3",
                actor_name=fixtures.G5T_COMMANDER_NAME,
                encounter_cleared=False, auto_exit_batches=set()),
            (None, None, False),
        )

    def test_gate4_resolver_trace_shape_passes_only_for_named_g5t(self):
        profile = fixtures.build_gate_profile("g5t", "g5t-commander-p1", 1)
        # This is the bounded event shape from g5t-gate4-p1-r1: one supported
        # tactical decision, one template narration result, and no validation call.
        events = [
            {
                "batch_id": "enemy:r1",
                "decision_outcome": "resolver_supported",
                "decision_point": "enemy_batch_resolution",
                "decision_source": "llm_tactical",
                "event_type": "decision",
                "logical_turn": 1,
                "decision_reason": "ledger_entry_omitted",
            },
            {
                "batch_id": "enemy:r1",
                "event_type": "combat_observation",
                "logical_turn": 1,
                "observation": "combat_batch_narration_result",
                "source": "template",
                "reason_code": "ledger_entry_omitted",
            },
        ]
        artifacts = {"trace_provider_events": []}
        checks = capture_evidence.observed_checks(
            profile, None, {}, artifacts, [], events
        )
        truth = next(row for row in checks
                     if row["id"] == "final_response_validation_truth")
        self.assertEqual(truth["status"], "PASS")
        self.assertEqual(truth["observed"]["resolver_batches"], [{
            "batch_id": "enemy:r1", "logical_turn": 1,
            "decision_source": "llm_tactical", "narration_sources": ["template"],
            "validation_provider_calls": 0, "status": "PASS",
        }])

        for legacy_gate in ("g5", "g5r"):
            legacy_profile = dict(profile, gate=legacy_gate)
            legacy_checks = capture_evidence.observed_checks(
                legacy_profile, None, {}, artifacts, [], events
            )
            legacy_truth = next(row for row in legacy_checks
                                if row["id"] == "final_response_validation_truth")
            self.assertEqual(legacy_truth["status"], "BLOCKED", legacy_gate)

    def test_evidence_evaluation_promotes_capture_time_g5t_checks_to_gate_requirements(self):
        profile, checks, _events, _before, _after = self._observed_g5t_checks(1)
        manifest = self._evaluation_manifest(profile)
        clean = capture_evidence.evaluate_evidence(
            manifest, checks, manifest["artifacts"], run_dir=pathlib.Path(self.scratch.name) / "clean",
            integrity={"failures": []}, profile=profile)
        self.assertEqual(clean["missing_required_checks"], [])
        g5t_ids = {
            "applied_choice_legality", "commander_squad_follows_orders",
            "self_preservation_removal", "cover_changes_effective_ac", "cover_expiration",
        }
        self.assertFalse(g5t_ids.intersection(row["id"] for row in clean["blocked_required_checks"]))

        failed_checks = copy.deepcopy(checks)
        legality = next(row for row in failed_checks if row["id"] == "applied_choice_legality")
        legality["status"] = "FAIL"
        failed = capture_evidence.evaluate_evidence(
            manifest, failed_checks, manifest["artifacts"],
            run_dir=pathlib.Path(self.scratch.name) / "failed",
            integrity={"failures": []}, profile=profile)
        self.assertIn("applied_choice_legality",
                      {row["id"] for row in failed["failed_required_checks"]})
        self.assertIn("failed_required_checks", failed["problems"])

        blocked_checks = copy.deepcopy(checks)
        cover = next(row for row in blocked_checks if row["id"] == "cover_expiration")
        cover["status"] = "BLOCKED"
        blocked = capture_evidence.evaluate_evidence(
            manifest, blocked_checks, manifest["artifacts"],
            run_dir=pathlib.Path(self.scratch.name) / "blocked",
            integrity={"failures": []}, profile=profile)
        self.assertIn("cover_expiration",
                      {row["id"] for row in blocked["blocked_required_checks"]})

    def test_named_g5t_profile_key_is_accepted_by_bundle_loader(self):
        party_size = 1
        scenario_id = "g5t-commander-p1"
        profile = fixtures.build_gate_profile("g5t", scenario_id, party_size)
        roster = list(fixtures.PC_NAMES[:party_size])
        profile_contract = {key: profile.get(key) for key in
                            ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
        profile_contract["gate"] = "g5t"
        profile_hash = hashlib.sha256(
            json.dumps(profile_contract, sort_keys=True).encode("utf-8")).hexdigest()
        seed_profile = dict(profile["seed"])
        seed_hash = hashlib.sha256(json.dumps(seed_profile, sort_keys=True).encode("utf-8")).hexdigest()
        encounter = fixtures.build_g5t_commander_fixture(party_size)["encounter"]
        snapshot = self._snapshot(party_size, encounter, active_encounter=scenario_id)
        manifest = {
            "gate": "g5t", "scenario": {"id": scenario_id, "branch": None, "phase": None,
                                        "profile_contract": profile_contract, "sha256": profile_hash},
            "party": {"size": party_size, "roster": roster},
            "seed": {"roster": roster, "active_encounter": scenario_id,
                     "profile_seed": seed_profile, "seed_profile_sha256": seed_hash,
                     "seed_id": seed_hash},
            "bounds": capture_evidence._expected_profile_bounds(profile),
            "counts": {"steps_sent": 0}, "artifacts": {},
        }
        integrity = {"loaded": {"before_snapshot": snapshot, "after_snapshot": snapshot,
                                 "report": {"status": "ok"}, "observations": []},
                     "failures": []}
        with patch.object(capture_evidence, "load_bundle_json", return_value=(manifest, None)), \
                patch.object(capture_evidence, "_artifact_integrity", return_value=integrity):
            result = capture_evidence._load_run_evidence(
                pathlib.Path(self.scratch.name) / "manifest-only")
        self.assertNotEqual(result.get("error"), "unknown_matrix_key")
        self.assertEqual(result["matrix_key"], "g5t-commander-p1:p1")


if __name__ == "__main__":
    unittest.main()
