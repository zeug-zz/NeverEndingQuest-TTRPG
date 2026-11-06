# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for committed host changes entering player sync."""

from __future__ import annotations

import asyncio
import ast
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from utils import file_operations, pc_manager
from utils.player_host_publication import (
    PlayerHostChangeNotice,
    PlayerHostChangePublisher,
    submit_player_host_change,
)
from web.extensions.player import (
    PLAYER_HOST,
    PLAYER_NAMESPACE,
    PLAYER_PORT,
    PlayerInputAdmission,
    PlayerSnapshot,
    create_app,
)
from web.extensions.player.assets import VerifiedPlayerClientAssets
from web.extensions.player.auth import PlayerSecurity
from web.extensions.player.contracts import PROTOCOL_VERSION
from web.extensions.player.sync import PlayerSyncCoordinator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("tmp") / "n2"
TEST_CLIENT_BUILD_ID = "0123456789abcdef0123456789abcdef"
INSTANCE_ID = "I" * 32
SESSION_EPOCH = "S" * 32


def _projection(location: str = "Lanternkeep") -> dict[str, object]:
    return {
        "party": {
            "members": [
                {
                    "name": "Acheron",
                    "level": 1,
                    "class": "Fighter",
                    "host_only_fixture_marker": "HOST_SECRET_MEMBER",
                }
            ],
            "active_character": "Acheron",
            "active_character_revision": 0,
            "world": {"currentLocation": location},
        },
        "transcript": {"available": True, "messages": []},
        "combat": {
            "available": True,
            "active": False,
            "round": None,
            "phase": None,
            "turn_order": [],
        },
        "busy": False,
        "host_only_fixture_marker": "HOST_SECRET_TOP_LEVEL",
    }


class _MutableGateway:
    def __init__(self) -> None:
        self.projection = _projection()
        self.snapshot_reads = 0
        self.fail_reads = False

    def read_snapshot(self) -> PlayerSnapshot:
        self.snapshot_reads += 1
        if self.fail_reads:
            raise RuntimeError("HOST_SECRET_READ_FAILURE")
        projection = copy.deepcopy(self.projection)
        revision = projection["party"]["active_character_revision"]
        return PlayerSnapshot(revision=revision, projection=projection)

    def admit_input(self, command: object) -> PlayerInputAdmission:
        return PlayerInputAdmission(getattr(command, "request_id"), "accepted")


def _install_test_client_assets(app: object) -> None:
    app._client_assets = VerifiedPlayerClientAssets(
        shell_document=b"",
        shell_content_type=b"text/html; charset=utf-8",
        client_build_id=TEST_CLIENT_BUILD_ID,
        protocol_version=PROTOCOL_VERSION,
        assets={},
    )


def _source_function(path: str, function_name: str) -> str:
    source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"missing function {function_name} in {path}")


class PlayerHostPublicationListenerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.gateway = _MutableGateway()
        self.security = PlayerSecurity(lambda: None)
        self.app = create_app(gateway=self.gateway, security=self.security)
        _install_test_client_assets(self.app)
        self.emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.emit_failure: str | None = None

        async def capture_emit(*args: object, **kwargs: object) -> None:
            if args and args[0] == self.emit_failure:
                raise RuntimeError("HOST_SECRET_SOCKET_FAILURE")
            self.emitted.append((args, kwargs))

        async def ignore_disconnects(socket_ids: object) -> None:
            del socket_ids

        self.app.socket_server.emit = capture_emit
        self.app._disconnect_sockets = ignore_disconnects
        await self.app._startup()
        grant = self.security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        self.grant = grant
        self.assertTrue(
            self.security.register_socket(
                "authorized-player",
                grant.cookie_value,
                f"{PLAYER_HOST}:{PLAYER_PORT}",
                f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
        )
        self.addAsyncCleanup(self.app._shutdown)

    async def _submit(self, kind: str, revision: int | None = None) -> None:
        previous_tail = self.app._host_publication_tail
        accepted = await asyncio.to_thread(submit_player_host_change, kind, revision)
        self.assertTrue(accepted)
        tail = self.app._host_publication_tail
        for _ in range(20):
            if tail is not None and tail is not previous_tail:
                break
            await asyncio.sleep(0)
            tail = self.app._host_publication_tail
        self.assertIsNotNone(tail)
        assert tail is not None
        await asyncio.wait_for(asyncio.shield(tail), timeout=2)

    async def test_canonical_projection_is_ordered_safe_and_auth_socket_only(self) -> None:
        self.security.register_socket(
            "not-registered-player",
            None,
            f"{PLAYER_HOST}:{PLAYER_PORT}",
            f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.gateway.projection = _projection("West Gate")
        await self._submit("transcript")

        self.gateway.projection = _projection("Watchtower")
        await self._submit("combat")

        self.assertEqual(len(self.emitted), 2)
        events = []
        for args, kwargs in self.emitted:
            self.assertEqual(args[0], "player.event")
            self.assertEqual(kwargs.get("namespace"), PLAYER_NAMESPACE)
            self.assertEqual(kwargs.get("to"), "authorized-player")
            event = args[1]
            self.assertEqual(
                set(event),
                {
                    "schema_version",
                    "instance_id",
                    "session_epoch",
                    "event_id",
                    "revision",
                    "type",
                    "projection",
                },
            )
            self.assertEqual(event["type"], "projection.updated")
            events.append(event)
        self.assertEqual([event["event_id"] for event in events], [1, 2])
        self.assertEqual(
            events[0]["projection"]["party"]["world"]["currentLocation"],
            "West Gate",
        )
        self.assertEqual(
            events[1]["projection"]["party"]["world"]["currentLocation"],
            "Watchtower",
        )
        encoded = json.dumps(events, sort_keys=True)
        self.assertNotIn("HOST_SECRET", encoded)
        self.assertEqual(self.gateway.snapshot_reads, 2)

    async def test_event_delivery_failure_forces_snapshot_and_future_resync(self) -> None:
        self.emit_failure = "player.event"
        with self.assertLogs("web.extensions.player.app", level="WARNING") as logs:
            await self._submit("combat")

        self.assertEqual([item[0][0] for item in self.emitted], ["player.snapshot"])
        snapshot = self.emitted[0][0][1]
        self.assertEqual(snapshot["event_cursor"], 1)
        self.assertNotIn("HOST_SECRET", json.dumps(snapshot, sort_keys=True))
        self.assertTrue(all("HOST_SECRET" not in record for record in logs.output))

        reconnect = self.app.sync.reconnect(
            self.security.server_instance_id,
            self.grant.session_epoch,
            0,
            self.grant.session_epoch,
            self.gateway.read_snapshot,
        )
        self.assertEqual(reconnect["kind"], "resync_required")
        self.assertEqual(reconnect["reason"], "event_gap")
        self.assertEqual(reconnect["snapshot"]["event_cursor"], 1)

    async def test_failed_canonical_read_is_diagnostic_and_never_raises_to_host(self) -> None:
        self.gateway.fail_reads = True
        with self.assertLogs("web.extensions.player.app", level="WARNING") as logs:
            previous_tail = self.app._host_publication_tail
            accepted = await asyncio.to_thread(
                submit_player_host_change,
                "transcript",
            )
            self.assertTrue(accepted)
            tail = self.app._host_publication_tail
            for _ in range(20):
                if tail is not None and tail is not previous_tail:
                    break
                await asyncio.sleep(0)
                tail = self.app._host_publication_tail
            assert tail is not None
            await asyncio.wait_for(asyncio.shield(tail), timeout=2)

        self.assertEqual([item[0][0] for item in self.emitted], ["player.error"])
        self.assertEqual(self.emitted[0][0][1]["code"], "snapshot_unavailable")
        self.assertTrue(all("HOST_SECRET" not in record for record in logs.output))


class PlayerHostPublisherTests(unittest.TestCase):
    def test_stopped_or_invalid_notices_are_noops(self) -> None:
        publisher = PlayerHostChangePublisher()
        self.assertFalse(publisher.submit("transcript"))
        self.assertFalse(publisher.submit({"type": "transcript"}))
        self.assertFalse(publisher.submit("active_pc", True))
        self.assertFalse(publisher.submit("combat", 1))

    def test_host_submit_does_not_wait_for_listener_dispatch(self) -> None:
        publisher = PlayerHostChangePublisher()
        loop = asyncio.new_event_loop()
        loop_started = threading.Event()
        submit_returned = threading.Event()
        dispatch_entered = threading.Event()
        dispatch_completed = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop_started.set()
            loop.run_forever()
            asyncio.set_event_loop(None)

        def dispatch(notice: PlayerHostChangeNotice) -> None:
            self.assertEqual(notice.kind, "transcript")
            dispatch_entered.set()
            if not submit_returned.wait(timeout=2):
                raise AssertionError("host submit waited for listener dispatch")
            dispatch_completed.set()

        thread = threading.Thread(target=run_loop, name="player-host-publication-test")
        thread.start()
        self.assertTrue(loop_started.wait(timeout=2))
        token = publisher.register(loop, dispatch)
        try:
            accepted = publisher.submit("transcript")
            submit_returned.set()
            self.assertTrue(accepted)
            self.assertTrue(dispatch_entered.wait(timeout=2))
            self.assertTrue(dispatch_completed.wait(timeout=2))
        finally:
            publisher.unregister(token)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()
        self.assertFalse(thread.is_alive())


class PlayerHostCursorBoundaryTests(unittest.TestCase):
    def test_snapshot_before_host_publication_replays_contiguous_event(self) -> None:
        sync = PlayerSyncCoordinator(INSTANCE_ID)
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()
        captured: list[dict[str, object]] = []
        published: list[object] = []

        def blocking_old_reader() -> PlayerSnapshot:
            snapshot_started.set()
            if not release_snapshot.wait(timeout=2):
                raise TimeoutError("snapshot fixture was not released")
            return PlayerSnapshot(0, _projection("Before"))

        snapshot_thread = threading.Thread(
            target=lambda: captured.append(
                sync.capture_snapshot(SESSION_EPOCH, blocking_old_reader)
            )
        )
        snapshot_thread.start()
        self.assertTrue(snapshot_started.wait(timeout=2))

        publisher_thread = threading.Thread(
            target=lambda: published.append(
                sync.publish_snapshot_event(
                    lambda: PlayerSnapshot(0, _projection("After"))
                )
            )
        )
        publisher_thread.start()
        release_snapshot.set()
        snapshot_thread.join(timeout=2)
        publisher_thread.join(timeout=2)
        self.assertFalse(snapshot_thread.is_alive())
        self.assertFalse(publisher_thread.is_alive())

        self.assertEqual(captured[0]["event_cursor"], 0)
        self.assertEqual(published[0].event_id, 1)
        replay = sync.reconnect(
            INSTANCE_ID,
            SESSION_EPOCH,
            0,
            SESSION_EPOCH,
            lambda: PlayerSnapshot(0, _projection("After")),
        )
        self.assertEqual(replay["kind"], "replay")
        self.assertEqual([event["event_id"] for event in replay["events"]], [1])
        self.assertEqual(
            replay["events"][0]["projection"]["party"]["world"]["currentLocation"],
            "After",
        )

    def test_host_publication_before_snapshot_is_in_snapshot_cursor(self) -> None:
        sync = PlayerSyncCoordinator(INSTANCE_ID)
        publication_started = threading.Event()
        release_publication = threading.Event()
        captured: list[dict[str, object]] = []

        def blocking_new_reader() -> PlayerSnapshot:
            publication_started.set()
            if not release_publication.wait(timeout=2):
                raise TimeoutError("publication fixture was not released")
            return PlayerSnapshot(0, _projection("After"))

        publisher_thread = threading.Thread(
            target=lambda: sync.publish_snapshot_event(blocking_new_reader)
        )
        publisher_thread.start()
        self.assertTrue(publication_started.wait(timeout=2))
        snapshot_thread = threading.Thread(
            target=lambda: captured.append(
                sync.capture_snapshot(
                    SESSION_EPOCH,
                    lambda: PlayerSnapshot(0, _projection("After")),
                )
            )
        )
        snapshot_thread.start()
        release_publication.set()
        publisher_thread.join(timeout=2)
        snapshot_thread.join(timeout=2)
        self.assertFalse(publisher_thread.is_alive())
        self.assertFalse(snapshot_thread.is_alive())

        snapshot = captured[0]
        self.assertEqual(snapshot["event_cursor"], 1)
        self.assertEqual(
            snapshot["projection"]["party"]["world"]["currentLocation"],
            "After",
        )
        replay = sync.reconnect(
            INSTANCE_ID,
            SESSION_EPOCH,
            snapshot["event_cursor"],
            SESSION_EPOCH,
            lambda: PlayerSnapshot(0, _projection("After")),
        )
        self.assertEqual(replay["kind"], "replay")
        self.assertEqual(replay["events"], [])


class PlayerHostCommitHookTests(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self._temp_dir = tempfile.TemporaryDirectory(
            dir=str(TMP_ROOT),
            prefix="player-host-publication-",
        )
        self.addCleanup(self._temp_dir.cleanup)
        self.party_path = Path(self._temp_dir.name) / "party_tracker.json"
        self._party_patch = mock.patch.object(
            pc_manager,
            "PARTY_TRACKER_FILE",
            str(self.party_path),
        )
        self._party_patch.start()
        self.addCleanup(self._party_patch.stop)
        self.assertTrue(
            file_operations.atomic_writer.write_json(
                str(self.party_path),
                {
                    "partyMembers": ["Acheron", "Merisiel"],
                    "active_character": "Acheron",
                    "active_character_revision": 0,
                    "worldConditions": {},
                },
            )
        )

    def test_active_pc_notice_follows_only_a_persisted_revision(self) -> None:
        with mock.patch(
            "utils.player_host_publication.submit_player_host_change"
        ) as submit:
            result = pc_manager.set_active_pc_checked("Merisiel", 0)
        self.assertEqual((result.status, result.revision, result.changed), ("updated", 1, True))
        submit.assert_called_once_with("active_pc", 1)

    def test_rejected_active_pc_write_submits_no_notice(self) -> None:
        with mock.patch.object(pc_manager, "safe_write_json", return_value=False), mock.patch(
            "utils.player_host_publication.submit_player_host_change"
        ) as submit:
            result = pc_manager.set_active_pc_checked("Merisiel", 0)
        self.assertEqual(result.status, "write_failed")
        submit.assert_not_called()

    def test_rejected_encounter_write_submits_no_notice(self) -> None:
        from updates import update_encounter as update_encounter_module

        with (
            mock.patch.object(update_encounter_module, "_sync_non_enemy_creatures"),
            mock.patch.object(update_encounter_module, "_normalize_enemy_defeat_states"),
            mock.patch.object(update_encounter_module, "_normalize_creature_statuses"),
            mock.patch("builtins.open", side_effect=OSError("fixture write failure")),
            mock.patch(
                "utils.player_host_publication.submit_player_host_change"
            ) as submit,
        ):
            with self.assertRaises(OSError):
                update_encounter_module._finalize_encounter_update(
                    {},
                    {},
                    {},
                    "fixture-encounter",
                    object(),
                )
        submit.assert_not_called()

    def test_host_hooks_submit_only_typed_change_kinds(self) -> None:
        expected_calls = {
            ("web/web_interface.py", "save_message_cache"): 'submit_player_host_change("transcript")',
            ("utils/pc_manager.py", "_commit_active_character"): 'submit_player_host_change("active_pc", new_revision)',
            ("updates/update_encounter.py", "_finalize_encounter_update"): 'submit_player_host_change("combat")',
            ("core/combat/turn_commit.py", "commit_combat_turn"): 'submit_player_host_change("combat")',
            ("core/combat/bootstrap.py", "recover_pending_combat_turn"): 'submit_player_host_change("combat")',
        }
        for (path, function_name), expected in expected_calls.items():
            with self.subTest(path=path, function=function_name):
                source = _source_function(path, function_name)
                self.assertIn("# TABLETOP MODE:", source)
                self.assertIn(expected, source)
                self.assertNotIn("socketio.emit", source)
        self.assertIn(
            'submit_player_host_change("combat")',
            (PROJECT_ROOT / "core/combat/combat_manager.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'submit_player_host_change("combat")',
            (PROJECT_ROOT / "core/ai/action_handler.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'submit_player_host_change("combat")',
            _source_function("core/combat/persistence.py", "finalize_combat_session"),
        )


if __name__ == "__main__":
    unittest.main()
