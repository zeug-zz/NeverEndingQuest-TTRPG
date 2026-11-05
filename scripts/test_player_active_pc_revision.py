# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free active-PC revision and stale-selection contract tests."""

from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from jsonschema import Draft7Validator

from utils import pc_manager
from web.extensions.player.active_pc import select_player_active_pc
from web.extensions.player.projections import PlayerProjectionBuilder


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("tmp") / "n1"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "party_schema.json"
_MISSING = object()


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
        self.assertTrue(pc_manager.safe_write_json(str(self.party_path), party))
        return party

    def _read_file(self) -> dict[str, object]:
        data = pc_manager.safe_read_json(str(self.party_path))
        self.assertIsInstance(data, dict)
        return data

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
