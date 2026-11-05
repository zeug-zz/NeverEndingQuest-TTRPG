# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free active-PC revision and stale-selection contract tests."""

from __future__ import annotations

import copy
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from jsonschema import Draft7Validator

from core.combat.persistence import (
    CombatActionDependencies,
    CombatFinalizationDependencies,
    CombatFinalizationInputs,
    finalize_combat_session,
    process_combat_action_batch,
)
from core.combat.turn import PhaseGateIO, run_input_phase_gate
from utils import pc_manager
from utils import file_operations
from utils.encoding_utils import safe_json_dump, safe_json_load
from web.extensions.player.active_pc import select_player_active_pc
from web.extensions.player.gateway import PlayerInputCommand, PlayerSnapshot
from web.extensions.player.projections import PlayerProjectionBuilder
from web.extensions.player.runtime_gateway import PlayerRuntimeGateway


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("tmp") / "n1"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "party_schema.json"
_MISSING = object()


class _ObservedRLock:
    """RLock test double that exposes when another thread contends."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._owner: int | None = None
        self._depth = 0
        self.contender_attempted = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        thread_id = threading.get_ident()
        with self._state_lock:
            if self._owner is not None and self._owner != thread_id:
                self.contender_attempted.set()
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            with self._state_lock:
                if self._owner == thread_id:
                    self._depth += 1
                else:
                    self._owner = thread_id
                    self._depth = 1
        return acquired

    def release(self) -> None:
        thread_id = threading.get_ident()
        with self._state_lock:
            if self._owner == thread_id:
                self._depth -= 1
                if self._depth == 0:
                    self._owner = None
        self._lock.release()

    def __enter__(self) -> _ObservedRLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()


class _CombatActor:
    def __init__(self, name: str, actor_type: str) -> None:
        self.name = name
        self.type = actor_type


class _CombatSwitchManager:
    def __init__(self, actor: _CombatActor, next_actor: _CombatActor) -> None:
        self.current_actor = actor
        self.next_actor = next_actor
        self.current_pc_name = None
        self.combat_phase = "ENEMY_PHASE"
        self.pc_states = {}

    def advance_turn(self) -> _CombatActor:
        self.current_actor = self.next_actor
        return self.next_actor

    def set_current_pc(self, name: str) -> None:
        self.current_pc_name = name


def _party_data(
    members: list[str],
    active_character: str | object = _MISSING,
    revision: int | object = _MISSING,
) -> dict[str, object]:
    party: dict[str, object] = {
        "module": "Revision Test",
        "partyMembers": list(members),
        "partyNPCs": [],
        "worldConditions": {
            "year": 1,
            "month": "Firstmonth",
            "day": 1,
            "time": "09:00:00",
            "weather": "Clear",
            "season": "Spring",
            "dayNightCycle": "Day",
            "moonPhase": "New Moon",
            "currentLocation": "Test Room",
            "currentArea": "Test Area",
            "currentAreaId": "area-1",
            "majorEventsUnderway": [],
            "politicalClimate": "Calm",
            "activeEncounter": "",
            "activeCombatEncounter": "",
            "weatherConditions": "Clear",
        },
    }
    if active_character is not _MISSING:
        party["active_character"] = active_character
    if revision is not _MISSING:
        party["active_character_revision"] = revision
    return party


class PlayerActivePCRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self._temp_dir = tempfile.TemporaryDirectory(
            dir=str(TMP_ROOT), prefix="active-pc-revision-"
        )
        self.addCleanup(self._temp_dir.cleanup)
        self.party_path = Path(self._temp_dir.name) / "party_tracker.json"
        self._party_file_patch = mock.patch.object(
            pc_manager, "PARTY_TRACKER_FILE", str(self.party_path)
        )
        self._party_file_patch.start()
        self.addCleanup(self._party_file_patch.stop)

    def _write_party(
        self,
        members: list[str],
        active_character: str | object = _MISSING,
        revision: int | object = _MISSING,
    ) -> dict[str, object]:
        party = _party_data(members, active_character, revision)
        # Seed exact on-disk fixtures without applying production write guards.
        self.assertTrue(
            file_operations.atomic_writer.write_json(str(self.party_path), party)
        )
        return party

    def _read_file(self) -> dict[str, object]:
        data = pc_manager.safe_read_json(str(self.party_path))
        self.assertIsInstance(data, dict)
        return data

    def _assert_snapshot_matches_disk(self, snapshot: pc_manager.PartyTrackerSnapshot) -> None:
        persisted = self._read_file()
        self.assertEqual(dict(snapshot), dict(persisted))
        self.assertEqual(
            pc_manager.party_tracker_snapshot_baseline(str(self.party_path), snapshot),
            dict(persisted),
        )

    def test_legacy_file_without_revision_reads_zero_and_remains_usable(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron")

        self.assertEqual(pc_manager.read_active_pc_state(), ("Acheron", 0))
        loaded = pc_manager.get_party_tracker()
        self.assertEqual(loaded["active_character"], "Acheron")
        self.assertNotIn("active_character_revision", loaded)

        selection = pc_manager.set_active_pc_checked("Merisiel", expected_revision=0)
        self.assertEqual(selection.status, "updated")
        self.assertEqual((selection.active_character, selection.revision), ("Merisiel", 1))
        self.assertEqual(self._read_file()["active_character_revision"], 1)

    def test_unrelated_whole_party_write_keeps_legacy_revision_optional(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron")
        stale_snapshot = pc_manager.get_party_tracker()
        stale_snapshot["worldConditions"]["weather"] = "Rain"

        self.assertTrue(safe_json_dump(stale_snapshot, str(self.party_path)))

        persisted = self._read_file()
        self.assertEqual(persisted["active_character"], "Acheron")
        self.assertNotIn("active_character_revision", persisted)
        self.assertEqual(persisted["worldConditions"]["weather"], "Rain")

    def test_unchanged_legacy_selection_does_not_materialize_revision(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron")

        selection = pc_manager.set_active_pc_checked("Acheron", expected_revision=0)

        self.assertEqual((selection.status, selection.revision), ("unchanged", 0))
        self.assertNotIn("active_character_revision", self._read_file())

    def test_unrelated_fresh_party_update_keeps_legacy_revision_optional(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron")

        updated = pc_manager.update_party_tracker(
            lambda party: party["worldConditions"].update({"weather": "Rain"})
        )

        self.assertIsNotNone(updated)
        persisted = self._read_file()
        self.assertEqual(persisted["worldConditions"]["weather"], "Rain")
        self.assertNotIn("active_character_revision", persisted)

    def test_safe_writer_loads_selection_guard_for_standalone_callers(self) -> None:
        script = "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                "Path('party_tracker.json').write_text(json.dumps({",
                "    'partyMembers': ['Acheron', 'Merisiel'],",
                "    'active_character': 'Merisiel',",
                "    'active_character_revision': 7,",
                "}), encoding='utf-8')",
                "from utils.file_operations import safe_write_json",
                "assert 'utils.pc_manager' not in sys.modules",
                "stale = {",
                "    'partyMembers': ['Acheron', 'Merisiel'],",
                "    'active_character': 'Acheron',",
                "    'active_character_revision': 6,",
                "}",
                "assert not safe_write_json('party_tracker.json', stale)",
                "saved = json.loads(Path('party_tracker.json').read_text(encoding='utf-8'))",
                "assert (saved['active_character'], saved['active_character_revision']) == ('Merisiel', 7)",
            ]
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(PROJECT_ROOT)

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self._temp_dir.name,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_whole_party_write_merges_unrelated_edits_after_selection_races(self) -> None:
        party = self._write_party(["A", "B", "C"], "A", 5)
        party["worldConditions"].update({"time": 1, "weather": "old"})
        with pc_manager._authorized_party_tracker_write("replace"):
            self.assertTrue(
                pc_manager.safe_write_json(str(self.party_path), party)
            )

        stale_snapshot = safe_json_load(str(self.party_path))
        self.assertIsInstance(stale_snapshot, pc_manager.PartyTrackerSnapshot)
        stale_snapshot["worldConditions"]["time"] = 2
        self.assertEqual(pc_manager.commit_active_character("B").revision, 6)
        self.assertEqual(
            pc_manager.set_active_pc_checked("C", expected_revision=6).revision,
            7,
        )

        def write_fresh_unrelated_state(current: dict[str, object]) -> None:
            current["worldConditions"]["weather"] = "new"
            current["worldConditions"]["nested"] = {
                "marker": {"source": "fresh"}
            }

        self.assertIsNotNone(pc_manager.update_party_tracker(write_fresh_unrelated_state))
        self.assertTrue(safe_json_dump(stale_snapshot, str(self.party_path)))

        persisted = self._read_file()
        self.assertEqual(
            (persisted["active_character"], persisted["active_character_revision"]),
            ("C", 7),
        )
        self.assertEqual(persisted["worldConditions"]["time"], 2)
        self.assertEqual(persisted["worldConditions"]["weather"], "new")
        self.assertEqual(
            persisted["worldConditions"]["nested"]["marker"], {"source": "fresh"}
        )

    def test_stale_whole_party_write_merges_without_selection_revision_change(self) -> None:
        party = self._write_party(["A", "B"], "A", 5)
        party["worldConditions"].update({"time": 1, "weather": "old"})
        with pc_manager._authorized_party_tracker_write("replace"):
            self.assertTrue(
                pc_manager.safe_write_json(str(self.party_path), party)
            )
        stale_snapshot = pc_manager.get_party_tracker()
        stale_snapshot["worldConditions"]["time"] = 2

        def update_fresh_fields(current: dict[str, object]) -> None:
            current["worldConditions"]["weather"] = "new"
            current["worldConditions"]["nested"] = {"marker": "preserved"}

        self.assertIsNotNone(pc_manager.update_party_tracker(update_fresh_fields))
        self.assertTrue(safe_json_dump(stale_snapshot, str(self.party_path)))

        persisted = self._read_file()
        self.assertEqual(
            (persisted["active_character"], persisted["active_character_revision"]),
            ("A", 5),
        )
        self.assertEqual(persisted["worldConditions"]["weather"], "new")
        self.assertEqual(persisted["worldConditions"]["nested"]["marker"], "preserved")
        self.assertEqual(persisted["worldConditions"]["time"], 2)

    def test_three_way_merge_handles_nested_edits_deletions_and_conflicts(self) -> None:
        party = self._write_party(["A", "B"], "A", 2)
        party["worldConditions"]["metadata"] = {
            "stale_edit": "base",
            "fresh_edit": "base",
            "delete_me": "base",
        }
        with pc_manager._authorized_party_tracker_write("replace"):
            self.assertTrue(
                pc_manager.safe_write_json(str(self.party_path), party)
            )

        stale_snapshot = pc_manager.get_party_tracker()
        metadata = stale_snapshot["worldConditions"]["metadata"]
        metadata["stale_edit"] = "stale"
        del metadata["delete_me"]

        def fresh_nested_edit(current: dict[str, object]) -> None:
            current_metadata = current["worldConditions"]["metadata"]
            current_metadata["fresh_edit"] = "fresh"
            current_metadata["new_marker"] = {"kept": True}

        self.assertIsNotNone(pc_manager.update_party_tracker(fresh_nested_edit))
        self.assertTrue(safe_json_dump(stale_snapshot, str(self.party_path)))
        metadata_after = self._read_file()["worldConditions"]["metadata"]
        self.assertEqual(metadata_after["stale_edit"], "stale")
        self.assertEqual(metadata_after["fresh_edit"], "fresh")
        self.assertNotIn("delete_me", metadata_after)
        self.assertEqual(metadata_after["new_marker"], {"kept": True})

        conflicting = pc_manager.get_party_tracker()
        conflicting["worldConditions"]["metadata"]["fresh_edit"] = "stale-conflict"
        self.assertIsNotNone(
            pc_manager.update_party_tracker(
                lambda current: current["worldConditions"]["metadata"].update(
                    {"fresh_edit": "newer-conflict"}
                )
            )
        )
        self.assertFalse(safe_json_dump(conflicting, str(self.party_path)))
        self.assertEqual(
            self._read_file()["worldConditions"]["metadata"]["fresh_edit"],
            "newer-conflict",
        )

    def test_concurrent_membership_edit_is_preserved_or_conflict_rejected(self) -> None:
        self._write_party(["A", "B"], "A", 4)
        stale_unrelated = pc_manager.get_party_tracker()
        stale_unrelated["worldConditions"]["time"] = "10:00:00"
        self.assertIsNotNone(
            pc_manager.update_party_tracker(
                lambda current: current["partyMembers"].append("C")
            )
        )
        self.assertTrue(safe_json_dump(stale_unrelated, str(self.party_path)))
        self.assertEqual(self._read_file()["partyMembers"], ["A", "B", "C"])

        stale_membership = pc_manager.get_party_tracker()
        stale_membership["partyMembers"] = ["A"]
        self.assertIsNotNone(
            pc_manager.update_party_tracker(
                lambda current: current["partyMembers"].append("D")
            )
        )
        self.assertFalse(safe_json_dump(stale_membership, str(self.party_path)))
        self.assertEqual(self._read_file()["partyMembers"], ["A", "B", "C", "D"])

    def test_plain_or_copied_dict_without_baseline_is_rejected(self) -> None:
        self._write_party(["A", "B"], "A", 3)
        copied = dict(pc_manager.get_party_tracker())
        copied["worldConditions"]["time"] = "10:00:00"

        self.assertFalse(safe_json_dump(copied, str(self.party_path)))
        persisted = self._read_file()
        self.assertNotEqual(persisted["worldConditions"]["time"], "10:00:00")
        self.assertEqual(
            (persisted["active_character"], persisted["active_character_revision"]),
            ("A", 3),
        )

    def test_missing_corrupt_and_failed_party_writes_do_not_create_or_advance_state(self) -> None:
        plain_payload = _party_data(["A"], "A", 8)
        self.assertFalse(safe_json_dump(plain_payload, str(self.party_path)))
        self.assertFalse(self.party_path.exists())

        self.party_path.write_text("{invalid json", encoding="utf-8")
        corrupt_bytes = self.party_path.read_bytes()
        self.assertFalse(safe_json_dump(plain_payload, str(self.party_path)))
        self.assertEqual(self.party_path.read_bytes(), corrupt_bytes)

        self._write_party(["A", "B"], "A", 5)
        with mock.patch.object(file_operations.atomic_writer, "write_json", return_value=False):
            result = pc_manager.set_active_pc_checked("B", expected_revision=5)

        self.assertEqual(result.status, "write_failed")
        self.assertEqual(self._read_file()["active_character_revision"], 5)
        self.assertEqual(pc_manager._known_active_pc_state(), (5, "A"))

    def test_combat_end_of_turn_save_keeps_newer_party_state(self) -> None:
        party = self._write_party(["A", "B", "C"], "A", 5)
        party["worldConditions"]["activeCombatEncounter"] = "combat-1"
        with pc_manager._authorized_party_tracker_write("replace"):
            self.assertTrue(
                pc_manager.safe_write_json(str(self.party_path), party)
            )
        combat_snapshot = pc_manager.get_party_tracker()

        self.assertEqual(pc_manager.commit_active_character("B").revision, 6)
        self.assertEqual(
            pc_manager.set_active_pc_checked("C", expected_revision=6).revision,
            7,
        )
        self.assertIsNotNone(
            pc_manager.update_party_tracker(
                lambda current: current["worldConditions"].update(
                    {"weather": "new", "nested_marker": {"fresh": True}}
                )
            )
        )

        def write_party_tracker(filepath: str, payload: object) -> bool:
            target = self.party_path if filepath == "party_tracker.json" else Path(filepath)
            return pc_manager.safe_write_json(str(target), payload)

        finalize_combat_session(
            CombatFinalizationInputs(
                party_tracker_data=combat_snapshot,
                conversation_history=[],
                location_info={},
                encounter_id="combat-1",
                player_file="unused.json",
            ),
            CombatFinalizationDependencies(
                summarize_dialogue=lambda *_args: "summary",
                safe_write_json=write_party_tracker,
                generate_chat_history=lambda *_args: None,
                safe_json_load=lambda _path: {},
                log_info=lambda *_args, **_kwargs: None,
                log_debug=lambda *_args, **_kwargs: None,
            ),
        )

        persisted = self._read_file()
        self.assertEqual(
            (persisted["active_character"], persisted["active_character_revision"]),
            ("C", 7),
        )
        self.assertEqual(persisted["worldConditions"]["weather"], "new")
        self.assertEqual(
            persisted["worldConditions"]["nested_marker"], {"fresh": True}
        )
        self.assertEqual(persisted["worldConditions"]["activeCombatEncounter"], "")
        self.assertEqual(
            persisted["worldConditions"]["lastCompletedEncounter"], "combat-1"
        )

    def test_selection_sync_then_combat_finalization_keeps_baseline_current(self) -> None:
        parties = [
            ["Acheron"],
            ["Acheron", "Merisiel", "Kira", "Vitreol"],
        ]
        for members in parties:
            with self.subTest(party_size=len(members)):
                encounter_id = f"combat-{len(members)}"
                party = _party_data(members, members[0], 5)
                party["worldConditions"]["activeCombatEncounter"] = encounter_id
                party["worldConditions"]["nested"] = {"host": {"kept": True}}
                self.assertTrue(
                    file_operations.atomic_writer.write_json(
                        str(self.party_path), party
                    )
                )
                snapshot = pc_manager.get_party_tracker()
                baseline_before = pc_manager.party_tracker_snapshot_baseline(
                    str(self.party_path), snapshot
                )
                selected_name = members[1] if len(members) > 1 else members[0]
                selection = pc_manager.commit_active_character(selected_name)
                expected_revision = 5 + (1 if selected_name != members[0] else 0)
                self.assertEqual(selection.status, "updated" if expected_revision == 6 else "unchanged")
                self.assertEqual(selection.revision, expected_revision)

                pc_manager.sync_active_pc_fields(snapshot, selection)
                expected_baseline = copy.deepcopy(baseline_before)
                expected_baseline["active_character"] = selected_name
                expected_baseline["active_character_revision"] = expected_revision
                self.assertEqual(
                    pc_manager.party_tracker_snapshot_baseline(
                        str(self.party_path), snapshot
                    ),
                    expected_baseline,
                )

                self.assertIsNotNone(
                    pc_manager.update_party_tracker(
                        lambda current: current["worldConditions"].update(
                            {
                                "weather": "Fog",
                                "nested": {
                                    "host": {"kept": True},
                                    "newer": {"preserved": True},
                                },
                            }
                        )
                    )
                )

                def write_party_tracker(filepath: str, payload: object) -> bool:
                    target = self.party_path if filepath == "party_tracker.json" else Path(filepath)
                    return pc_manager.safe_write_json(str(target), payload)

                finalize_combat_session(
                    CombatFinalizationInputs(
                        party_tracker_data=snapshot,
                        conversation_history=[],
                        location_info={},
                        encounter_id=encounter_id,
                        player_file="unused.json",
                    ),
                    CombatFinalizationDependencies(
                        summarize_dialogue=lambda *_args: "summary",
                        safe_write_json=write_party_tracker,
                        generate_chat_history=lambda *_args: None,
                        safe_json_load=lambda _path: {},
                        log_info=lambda *_args, **_kwargs: None,
                        log_debug=lambda *_args, **_kwargs: None,
                    ),
                )

                persisted = self._read_file()
                self.assertEqual(
                    (persisted["active_character"], persisted["active_character_revision"]),
                    (selected_name, expected_revision),
                )
                self.assertEqual(
                    persisted["worldConditions"]["activeCombatEncounter"], ""
                )
                self.assertEqual(
                    persisted["worldConditions"]["lastCompletedEncounter"], encounter_id
                )
                self.assertEqual(persisted["worldConditions"]["weather"], "Fog")
                self.assertEqual(
                    persisted["worldConditions"]["nested"]["newer"],
                    {"preserved": True},
                )
                self._assert_snapshot_matches_disk(snapshot)

    def test_original_snapshot_advances_across_sanitized_and_atomic_saves(self) -> None:
        parties = [
            ["Acheron"],
            ["Acheron", "Merisiel", "Kira", "Vitreol"],
        ]
        for members in parties:
            with self.subTest(party_size=len(members)):
                party = _party_data(members, members[0], 0)
                party["worldConditions"]["nested"] = {
                    "caller": "initial",
                    "concurrent": "initial",
                }
                self.assertTrue(
                    file_operations.atomic_writer.write_json(
                        str(self.party_path), party
                    )
                )
                snapshot = pc_manager.get_party_tracker()

                snapshot["worldConditions"]["nested"]["caller"] = "first\u2014saved"
                self.assertTrue(safe_json_dump(snapshot, str(self.party_path)))
                self.assertEqual(
                    self._read_file()["worldConditions"]["nested"]["caller"],
                    "first--saved",
                )
                self._assert_snapshot_matches_disk(snapshot)

                snapshot["worldConditions"]["nested"]["caller"] = "second"
                self.assertTrue(
                    pc_manager.safe_write_json(str(self.party_path), snapshot)
                )
                self.assertEqual(
                    self._read_file()["worldConditions"]["nested"]["caller"],
                    "second",
                )
                self._assert_snapshot_matches_disk(snapshot)

                snapshot["worldConditions"]["nested"]["caller"] = "third"
                self.assertTrue(safe_json_dump(snapshot, str(self.party_path)))
                self._assert_snapshot_matches_disk(snapshot)
                snapshot["worldConditions"]["nested"]["caller"] = "fourth"
                self.assertTrue(
                    pc_manager.safe_write_json(str(self.party_path), snapshot)
                )
                self._assert_snapshot_matches_disk(snapshot)

                self.assertIsNotNone(
                    pc_manager.update_party_tracker(
                        lambda current: current["worldConditions"]["nested"].update(
                            {
                                "concurrent": "fresh",
                                "fresh_only": {"retained": True},
                            }
                        )
                    )
                )
                snapshot["worldConditions"]["nested"]["caller"] = "after-merge"
                self.assertTrue(safe_json_dump(snapshot, str(self.party_path)))
                persisted = self._read_file()
                self.assertEqual(
                    persisted["worldConditions"]["nested"]["concurrent"], "fresh"
                )
                self.assertEqual(
                    persisted["worldConditions"]["nested"]["fresh_only"],
                    {"retained": True},
                )
                self._assert_snapshot_matches_disk(snapshot)

                snapshot["worldConditions"]["nested"]["caller"] = "after-merge-again"
                self.assertTrue(
                    pc_manager.safe_write_json(str(self.party_path), snapshot)
                )
                persisted = self._read_file()
                self.assertEqual(
                    persisted["worldConditions"]["nested"]["caller"],
                    "after-merge-again",
                )
                self.assertEqual(
                    persisted["worldConditions"]["nested"]["fresh_only"],
                    {"retained": True},
                )
                self._assert_snapshot_matches_disk(snapshot)

    def test_failed_writes_and_unsuccessful_selection_leave_snapshot_unchanged(self) -> None:
        self._write_party(["A", "B", "C"], "A", 5)

        conflict_snapshot = pc_manager.get_party_tracker()
        conflict_snapshot["worldConditions"]["time"] = "stale-time"
        self.assertIsNotNone(
            pc_manager.update_party_tracker(
                lambda current: current["worldConditions"].update(
                    {"time": "fresh-time"}
                )
            )
        )
        conflict_data_before = copy.deepcopy(dict(conflict_snapshot))
        conflict_baseline_before = pc_manager.party_tracker_snapshot_baseline(
            str(self.party_path), conflict_snapshot
        )
        self.assertFalse(
            pc_manager.safe_write_json(str(self.party_path), conflict_snapshot)
        )
        self.assertEqual(dict(conflict_snapshot), conflict_data_before)
        self.assertEqual(
            pc_manager.party_tracker_snapshot_baseline(
                str(self.party_path), conflict_snapshot
            ),
            conflict_baseline_before,
        )

        stale_snapshot = pc_manager.get_party_tracker()
        stale_data_before = copy.deepcopy(dict(stale_snapshot))
        stale_baseline_before = pc_manager.party_tracker_snapshot_baseline(
            str(self.party_path), stale_snapshot
        )
        self.assertEqual(pc_manager.commit_active_character("B").revision, 6)
        stale_result = pc_manager.set_active_pc_checked("C", expected_revision=5)
        self.assertEqual(stale_result.status, "stale")
        pc_manager.sync_active_pc_fields(stale_snapshot, stale_result)
        rejected_result = pc_manager.set_active_pc_checked("not-a-member", expected_revision=6)
        self.assertEqual(rejected_result.status, "rejected")
        pc_manager.sync_active_pc_fields(stale_snapshot, rejected_result)
        self.assertEqual(dict(stale_snapshot), stale_data_before)
        self.assertEqual(
            pc_manager.party_tracker_snapshot_baseline(
                str(self.party_path), stale_snapshot
            ),
            stale_baseline_before,
        )

        failed_snapshot = pc_manager.get_party_tracker()
        failed_snapshot["worldConditions"]["weather"] = "failed-write"
        failed_data_before = copy.deepcopy(dict(failed_snapshot))
        failed_baseline_before = pc_manager.party_tracker_snapshot_baseline(
            str(self.party_path), failed_snapshot
        )
        with mock.patch.object(
            file_operations.atomic_writer,
            "_atomic_replace",
            side_effect=OSError("synthetic atomic replacement failure"),
        ):
            self.assertFalse(
                pc_manager.safe_write_json(str(self.party_path), failed_snapshot)
            )
        self.assertEqual(dict(failed_snapshot), failed_data_before)
        self.assertEqual(
            pc_manager.party_tracker_snapshot_baseline(
                str(self.party_path), failed_snapshot
            ),
            failed_baseline_before,
        )
        self.assertNotEqual(self._read_file()["worldConditions"]["weather"], "failed-write")

    def test_legacy_file_without_active_character_uses_default_member_at_revision_zero(self) -> None:
        self._write_party(["Acheron", "Merisiel"])

        self.assertEqual(pc_manager.read_active_pc_state(), ("Acheron", 0))
        unchanged = pc_manager.set_active_pc_checked("Acheron", expected_revision=0)
        self.assertEqual(unchanged.status, "unchanged")
        self.assertEqual(unchanged.revision, 0)

    def test_assignment_does_not_advance_revision_when_value_is_unchanged(self) -> None:
        party = _party_data(["Acheron"], "Acheron", 7)

        changed = pc_manager.assign_active_character(party, "Acheron")

        self.assertFalse(changed)
        self.assertEqual(party["active_character"], "Acheron")
        self.assertEqual(party["active_character_revision"], 7)

        changed = pc_manager.assign_active_character(party, "Merisiel")
        self.assertTrue(changed)
        self.assertEqual(party["active_character_revision"], 8)

    def test_host_assignment_normalizes_malformed_revision_and_logs(self) -> None:
        for malformed_revision in ("x", True, -3):
            with self.subTest(revision=malformed_revision):
                party = _party_data(
                    ["Acheron", "Merisiel"], "Acheron", malformed_revision
                )

                with self.assertLogs("NeverEndingQuest", level="WARNING") as captured:
                    changed = pc_manager.assign_active_character(party, "Merisiel")

                self.assertTrue(changed)
                self.assertEqual(party["active_character"], "Merisiel")
                self.assertEqual(party["active_character_revision"], 1)
                self.assertTrue(
                    any("Malformed active character revision" in line for line in captured.output)
                )

    def test_player_checked_selection_rejects_malformed_stored_revision(self) -> None:
        for malformed_revision in ("x", True, -3):
            with self.subTest(revision=malformed_revision):
                self._write_party(
                    ["Acheron", "Merisiel"], "Acheron", malformed_revision
                )

                selection = select_player_active_pc("Merisiel", expected_revision=0)

                self.assertEqual(selection.status, "rejected")
                self.assertEqual(selection.reason, "invalid_revision")
                self.assertEqual(selection.active_character, "Acheron")
                self.assertEqual(selection.revision, 0)
                self.assertEqual(
                    self._read_file()["active_character_revision"], malformed_revision
                )

    def test_host_then_player_selection_rejects_stale_revision(self) -> None:
        initial = self._write_party(
            ["Acheron", "Merisiel", "Kira", "Vitreol"], "Acheron", 0
        )

        from flask import Flask
        from web.routes.tabletop_party_routes import register_tabletop_party_routes

        app = Flask(__name__)
        app.config["TESTING"] = True
        register_tabletop_party_routes(app, user_input_queue=object())
        client = app.test_client()

        with mock.patch(
            "web.routes.tabletop_party_routes.safe_read_json", return_value=initial
        ):
            host_response = client.post(
                "/api/party/set_active",
                json={"character": "Merisiel", "active_character_revision": 0},
            )
        self.assertEqual(host_response.status_code, 200)
        self.assertEqual(host_response.get_json()["active_character_revision"], 1)

        with mock.patch(
            "web.routes.tabletop_party_routes.safe_read_json", return_value=initial
        ):
            stale_host_response = client.post(
                "/api/party/set_active",
                json={"character": "Acheron", "active_character_revision": 0},
            )
        self.assertEqual(stale_host_response.status_code, 409)
        self.assertEqual(
            stale_host_response.get_json()["active_character_revision"], 1
        )

        stale_player = select_player_active_pc("Acheron", expected_revision=0)
        self.assertEqual(stale_player.status, "stale")
        self.assertEqual(stale_player.revision, 1)
        self.assertEqual(pc_manager.read_active_pc_state(), ("Merisiel", 1))

        current_player = select_player_active_pc("Kira", expected_revision=1)
        self.assertEqual(current_player.status, "selected")
        self.assertEqual((current_player.active_character, current_player.revision), ("Kira", 2))

    def test_stale_revision_is_rejected_without_mutation(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron", 3)

        result = pc_manager.set_active_pc_checked("Merisiel", expected_revision=2)

        self.assertEqual(result.status, "stale")
        self.assertEqual(result.reason, "stale_revision")
        self.assertEqual(pc_manager.read_active_pc_state(), ("Acheron", 3))

    def test_selection_transaction_preserves_latest_unrelated_party_fields(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron", 4)
        stale_snapshot = pc_manager.get_party_tracker()
        stale_snapshot["worldConditions"]["weather"] = "Clear"
        updated = pc_manager.update_party_tracker(
            lambda party: party["worldConditions"].update({"weather": "Fog"})
        )
        self.assertIsNotNone(updated)

        selection = pc_manager.set_active_pc_checked("Merisiel", expected_revision=4)

        self.assertEqual((selection.active_character, selection.revision), ("Merisiel", 5))
        persisted = self._read_file()
        self.assertEqual(persisted["worldConditions"]["weather"], "Fog")
        self.assertEqual(stale_snapshot["worldConditions"]["weather"], "Clear")

    def test_non_member_and_removed_member_are_rejected(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron", 0)

        outsider = select_player_active_pc("Blairen", expected_revision=0)
        self.assertEqual(outsider.status, "rejected")
        self.assertEqual(outsider.reason, "not_party_member")
        self.assertEqual(pc_manager.read_active_pc_state(), ("Acheron", 0))

        self.assertTrue(pc_manager.remove_pc("Acheron"))
        after_removal = pc_manager.read_active_pc_state()
        self.assertEqual(after_removal, ("Merisiel", 1))
        removed = select_player_active_pc("Acheron", expected_revision=1)
        self.assertEqual(removed.status, "rejected")
        self.assertEqual(removed.reason, "not_party_member")
        self.assertEqual(pc_manager.read_active_pc_state(), ("Merisiel", 1))

    def test_checked_writes_are_serialized_and_revisions_are_not_lost(self) -> None:
        members = ["Acheron", "Merisiel", "Kira", "Vitreol"]
        self._write_party(members, members[0], 0)
        worker_count = 64
        barrier = threading.Barrier(worker_count)

        def select(index: int) -> pc_manager.ActivePCWriteResult:
            barrier.wait()
            return pc_manager.set_active_pc_checked(members[index % len(members)])

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(select, range(worker_count)))

        changed_revisions = sorted(result.revision for result in results if result.changed)
        final_active, final_revision = pc_manager.read_active_pc_state()
        self.assertGreater(len(changed_revisions), 0)
        self.assertEqual(changed_revisions, list(range(1, final_revision + 1)))
        self.assertEqual(final_revision, sum(result.changed for result in results))
        self.assertIn(final_active, members)
        self.assertTrue(all(result.status in {"updated", "unchanged"} for result in results))

    def test_stale_whole_party_write_cannot_rollback_selection_or_gateway_revision(self) -> None:
        members = ["Merisiel", "Kira", "Acheron", "Vitreol"]
        self._write_party(members, "Merisiel", 6)
        stale_snapshot = pc_manager.get_party_tracker()
        stale_snapshot["worldConditions"]["weather"] = "Rain"

        selected = pc_manager.commit_active_character("Kira")
        self.assertEqual((selected.active_character, selected.revision), ("Kira", 7))
        self.assertTrue(pc_manager.safe_write_json(str(self.party_path), stale_snapshot))

        persisted = self._read_file()
        self.assertEqual(
            (persisted["active_character"], persisted["active_character_revision"]),
            ("Kira", 7),
        )
        self.assertEqual(persisted["worldConditions"]["weather"], "Rain")

        runtime_queue: queue.Queue[str] = queue.Queue()
        gateway = PlayerRuntimeGateway(
            runtime_queue,
            read_party_state=pc_manager.get_party_tracker,
            canonical_state_lock=threading.Lock(),
            busy_probe=lambda: False,
            echo_input=lambda _message: None,
            snapshot_reader=lambda: PlayerSnapshot(0, {}),
        )
        old_input = gateway.admit_input(
            PlayerInputCommand("old-revision", "Merisiel", 6, "I take a turn")
        )
        self.assertEqual(old_input.status, "stale")
        self.assertEqual(runtime_queue.qsize(), 0)

    def test_concurrent_stale_write_and_selection_are_serialized_deterministically(self) -> None:
        self._write_party(["Merisiel", "Kira"], "Merisiel", 6)
        stale_snapshot = pc_manager.get_party_tracker()
        observed_lock = _ObservedRLock()
        write_paused = threading.Event()
        release_write = threading.Event()
        original_write_json = file_operations.atomic_writer.write_json

        def pause_stale_write(filepath, data, *args, **kwargs):
            if data is stale_snapshot:
                write_paused.set()
                if not release_write.wait(5):
                    raise TimeoutError("timed out waiting to release stale party write")
            return original_write_json(filepath, data, *args, **kwargs)

        with mock.patch.object(pc_manager, "_party_tracker_lock", observed_lock), \
                mock.patch.object(file_operations.atomic_writer, "write_json", side_effect=pause_stale_write):
            with ThreadPoolExecutor(max_workers=2) as executor:
                stale_write = executor.submit(
                    pc_manager.safe_write_json, str(self.party_path), stale_snapshot
                )
                self.assertTrue(write_paused.wait(5))
                selection = executor.submit(pc_manager.set_active_pc_checked, "Kira")
                self.assertTrue(observed_lock.contender_attempted.wait(5))
                release_write.set()
                self.assertTrue(stale_write.result(timeout=5))
                committed = selection.result(timeout=5)

        self.assertEqual((committed.active_character, committed.revision), ("Kira", 7))
        self.assertEqual(pc_manager.read_active_pc_state(), ("Kira", 7))

    def test_bulk_restore_and_reset_keep_revision_monotonic(self) -> None:
        self._write_party(["Acheron", "Merisiel"], "Acheron", 8)

        restored = pc_manager.replace_party_tracker_data(
            _party_data(["Acheron", "Merisiel"], "Merisiel", 2)
        )
        self.assertIsNotNone(restored)
        self.assertEqual(
            (restored["active_character"], restored["active_character_revision"]),
            ("Merisiel", 9),
        )

        stale_restore = pc_manager.replace_party_tracker_data(
            _party_data(["Acheron", "Merisiel"], "Merisiel", 3)
        )
        self.assertIsNotNone(stale_restore)
        self.assertEqual(stale_restore["active_character_revision"], 9)

        reset = pc_manager.replace_party_tracker_data({})
        self.assertIsNotNone(reset)
        self.assertEqual((reset["partyMembers"], reset["active_character"]), ([], ""))
        self.assertEqual(reset["active_character_revision"], 10)

    def test_explicit_replacement_recovers_missing_and_corrupt_party_state(self) -> None:
        missing_replacement = pc_manager.replace_party_tracker_data(
            _party_data(["A"], "A", 8)
        )
        self.assertIsNotNone(missing_replacement)
        self.assertEqual(
            (missing_replacement["active_character"],
             missing_replacement["active_character_revision"]),
            ("A", 8),
        )

        self.party_path.write_text("{invalid json", encoding="utf-8")
        corrupt_replacement = pc_manager.replace_party_tracker_data(
            _party_data(["B"], "B", 0)
        )
        self.assertIsNotNone(corrupt_replacement)
        self.assertEqual(
            (corrupt_replacement["active_character"],
             corrupt_replacement["active_character_revision"]),
            ("B", 9),
        )
        self.assertEqual(self._read_file()["partyMembers"], ["B"])

    def test_untrusted_membership_removal_uses_revisioned_selection_fallback(self) -> None:
        self._write_party(["Acheron", "Kira"], "Kira", 7)
        stale_membership = pc_manager.get_party_tracker()
        stale_membership["partyMembers"] = ["Acheron"]

        self.assertTrue(pc_manager.safe_write_json(str(self.party_path), stale_membership))

        self.assertEqual(pc_manager.read_active_pc_state(), ("Acheron", 8))

    def test_failed_guarded_membership_write_does_not_advance_revision(self) -> None:
        self._write_party(["Kira", "Acheron"], "Kira", 6)
        stale_membership = pc_manager.get_party_tracker()
        stale_membership["partyMembers"] = ["Acheron"]

        with mock.patch.object(file_operations.atomic_writer, "write_json", return_value=False):
            self.assertFalse(
                pc_manager.safe_write_json(str(self.party_path), stale_membership)
            )

        self.assertEqual(pc_manager.read_active_pc_state(), ("Kira", 6))
        persisted = self._read_file()
        self.assertEqual(persisted["partyMembers"], ["Kira", "Acheron"])
        self.assertEqual(persisted["active_character_revision"], 6)

    def test_combat_turn_advance_commits_selection_and_keeps_update_emission(self) -> None:
        members = ["Merisiel", "Kira"]
        self._write_party(members, "Merisiel", 6)
        party_snapshot = pc_manager.get_party_tracker()
        emissions = []
        manager = _CombatSwitchManager(
            _CombatActor("Goblin", "npc"), _CombatActor("Kira", "pc")
        )
        dependencies = CombatActionDependencies(
            queue_character_update=lambda *_args: None,
            update_encounter=lambda *_args, **_kwargs: None,
            normalize_encounter_status=lambda data: data,
            sync_non_pc_queue_state=lambda *_args: False,
            log_info=mock.Mock(),
            log_debug=mock.Mock(),
            log_error=mock.Mock(),
            log_warning=mock.Mock(),
            calculate_xp=lambda: ("", 0),
            save_json=mock.Mock(),
            active_character_update_available=True,
            emit_combat_event=lambda event, payload: emissions.append((event, payload)),
            get_current_actor=lambda current: current.current_actor,
            advance_turn=lambda current: current.advance_turn(),
            get_pc_state=lambda current, name: current.pc_states.get(name),
            pc_acted_status="acted",
            npc_combatant_type="npc",
            pc_combatant_type="pc",
            check_all_monsters_defeated=lambda _data: False,
            commit_active_character=pc_manager.commit_active_character,
        )

        process_combat_action_batch(
            [{"action": "updateCharacterInfo", "parameters": {"characterName": "Kira", "changes": "waits"}}],
            {"creatures": []},
            {},
            encounter_id="revision-combat",
            conversation_history=[],
            conversation_history_file="history.json",
            multi_pc_manager=manager,
            party_tracker_data=party_snapshot,
            is_combat_ending=False,
            dependencies=dependencies,
        )

        self.assertEqual(pc_manager.read_active_pc_state(), ("Kira", 7))
        self.assertEqual(
            (party_snapshot["active_character"], party_snapshot["active_character_revision"]),
            ("Kira", 7),
        )
        self.assertEqual(
            emissions, [("active_character_update", {"character": "Kira"})]
        )
        dependencies.save_json.assert_not_called()

    def test_combat_input_actor_switch_commits_authoritative_selection(self) -> None:
        self._write_party(["Merisiel", "Kira"], "Merisiel", 6)
        party_snapshot = pc_manager.get_party_tracker()
        manager = _CombatSwitchManager(
            _CombatActor("Goblin", "npc"), _CombatActor("Goblin", "npc")
        )
        manager.current_pc_name = "Merisiel"
        manager.pc_states = {"Merisiel": object(), "Kira": object()}
        io = PhaseGateIO(
            emit=mock.Mock(),
            flush=mock.Mock(),
            debug=mock.Mock(),
            save_json=mock.Mock(),
            parse_death_save_roll=mock.Mock(),
            commit_active_character=pc_manager.commit_active_character,
        )

        result = run_input_phase_gate(
            "[Kira]: I take a turn",
            encounter_data={},
            multi_pc_manager=manager,
            party_tracker_data=party_snapshot,
            json_file_path="encounter.json",
            conversation_history=[],
            conversation_history_file="history.json",
            io=io,
            initiative_gate=mock.Mock(),
        )

        self.assertEqual(result.control_action, "proceed")
        self.assertEqual(pc_manager.read_active_pc_state(), ("Kira", 7))
        self.assertEqual(manager.current_pc_name, "Kira")
        self.assertEqual(
            (party_snapshot["active_character"], party_snapshot["active_character_revision"]),
            ("Kira", 7),
        )

    def test_single_and_four_pc_party_selection(self) -> None:
        parties = [
            ["Acheron"],
            ["Acheron", "Merisiel", "Kira", "Vitreol"],
        ]
        for members in parties:
            with self.subTest(party_size=len(members)):
                self._write_party(members, members[0], 0)
                selection = select_player_active_pc(members[-1], expected_revision=0)
                self.assertEqual(selection.status, "selected")
                self.assertEqual(selection.active_character, members[-1])
                self.assertEqual(selection.revision, 0 if len(members) == 1 else 1)

    def test_party_schema_accepts_legacy_and_revisioned_files(self) -> None:
        import json

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)
        legacy = _party_data(["Acheron"], "Acheron")
        revisioned = _party_data(["Acheron"], "Acheron", 0)

        self.assertEqual(list(validator.iter_errors(legacy)), [])
        self.assertEqual(list(validator.iter_errors(revisioned)), [])
        revisioned["active_character_revision"] = -1
        self.assertNotEqual(list(validator.iter_errors(revisioned)), [])

    def test_projection_reads_revision_from_canonical_pc_manager_helper(self) -> None:
        party = _party_data(["Acheron", "Merisiel"], "Acheron", 99)
        character = {
            "name": "Acheron",
            "type": "player",
            "character_type": "player",
            "character_role": "player",
            "level": 1,
        }
        with (
            mock.patch.object(pc_manager, "get_party_tracker", return_value=party),
            mock.patch.object(pc_manager, "read_active_pc_state", return_value=("Merisiel", 4)) as reader,
            mock.patch.object(pc_manager, "get_character_state", return_value=character),
        ):
            projection = PlayerProjectionBuilder.from_pc_manager().build()

        reader.assert_called_once_with()
        self.assertEqual(projection["party"]["active_character"], "Merisiel")
        self.assertEqual(projection["party"]["active_character_revision"], 4)


if __name__ == "__main__":
    unittest.main()
