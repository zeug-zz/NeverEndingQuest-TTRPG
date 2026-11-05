# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for player envelopes, cursors, replay, and deduplication."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import unittest
from typing import Any
from urllib.parse import urlencode

from web.extensions.player import (
    PLAYER_HOST,
    PLAYER_NAMESPACE,
    PLAYER_PORT,
    PlayerInputAdmission,
    PlayerSnapshot,
    create_app,
)
from web.extensions.player.auth import PLAYER_SESSION_COOKIE, PlayerSecurity
from web.extensions.player.contracts import (
    EnvelopeValidationError,
    MAX_IDENTITY_BYTES,
    PROTOCOL_VERSION,
    canonical_json_bytes,
    make_event_envelope,
    make_receipt_envelope,
    make_snapshot_envelope,
    validate_command_envelope,
    validate_event_envelope,
    validate_receipt_envelope,
    validate_snapshot_envelope,
)
from web.extensions.player.gateway import UnavailablePlayerGateway
from web.extensions.player.limiters import PlayerLimiters
from web.extensions.player.limits import (
    MAX_REPLAY_BYTES,
    MAX_REPLAY_EVENTS,
    MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION,
    MAX_SOCKETIO_EVENT_BYTES,
    MAX_SNAPSHOT_BYTES,
)
from web.extensions.player.sync import PlayerSyncCoordinator

PC_NAMES = ("Acheron", "Merisiel", "Kira", "Vitreol")


def _identity() -> str:
    return secrets.token_urlsafe(32)


def _projection(party_size: int = 1) -> dict[str, object]:
    names = list(PC_NAMES[:party_size])
    return {
        "party": {
            "members": [
                {"name": name, "level": index + 1, "class": "Fighter"}
                for index, name in enumerate(names)
            ],
            "active_character": names[-1],
            "active_character_revision": 0,
            "world": {"currentLocation": "Lanternkeep"},
        },
        "busy": False,
    }


class _Gateway:
    def __init__(self, party_size: int = 1, status: str = "accepted") -> None:
        self.party_size = party_size
        self.status = status
        self.admissions: list[object] = []
        self.snapshot_reads = 0

    def read_snapshot(self) -> PlayerSnapshot:
        self.snapshot_reads += 1
        return PlayerSnapshot(self.snapshot_reads, _projection(self.party_size))

    def admit_input(self, command: object) -> PlayerInputAdmission:
        self.admissions.append(command)
        return PlayerInputAdmission(
            request_id=getattr(command, "request_id"),
            status=self.status,
        )


def _command(
    instance_id: str,
    session_epoch: str,
    *,
    request_id: str = "request-1",
    character_name: str = "Acheron",
    text: str = "Move north",
) -> dict[str, object]:
    return {
        "schema_version": PROTOCOL_VERSION,
        "instance_id": instance_id,
        "session_epoch": session_epoch,
        "request_id": request_id,
        "character_name": character_name,
        "active_character_revision": 0,
        "text": text,
    }


def _new_dedup_state(session_epoch: str) -> tuple[PlayerLimiters, str]:
    session_id = "session-" + secrets.token_urlsafe(18)
    limiters = PlayerLimiters(lambda: 1_000_000.0)
    if not limiters.register_session(session_id, session_epoch):
        raise AssertionError("dedup test session was not registered")
    return limiters, session_id


def _dispatch_http(
    app: Any,
    path: str,
    *,
    query: str = "",
    cookie: str,
) -> tuple[int, bytes]:
    messages: list[dict[str, Any]] = []
    body_sent = False
    headers = [
        (b"host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
        (b"origin", f"http://{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
        (b"cookie", f"{PLAYER_SESSION_COOKIE}={cookie}".encode("ascii")),
    ]

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "query_string": query.encode("ascii"),
                "headers": headers,
            },
            receive,
            send,
        )
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), body


class GameplaySyncEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance_id = _identity()
        self.session_epoch = _identity()
        self.command = _command(self.instance_id, self.session_epoch)
        self.snapshot = make_snapshot_envelope(
            self.instance_id,
            self.session_epoch,
            1,
            0,
            _projection(),
        )
        self.event = make_event_envelope(
            self.instance_id,
            self.session_epoch,
            1,
            1,
            "projection.updated",
            _projection(),
        )
        self.receipt = make_receipt_envelope(
            self.instance_id,
            self.session_epoch,
            "request-1",
            "accepted",
        )

    def test_valid_versioned_command_snapshot_event_and_receipt(self) -> None:
        parsed = validate_command_envelope(self.command)
        self.assertEqual(parsed.request_id, "request-1")
        self.assertEqual(validate_snapshot_envelope(self.snapshot), self.snapshot)
        self.assertEqual(validate_event_envelope(self.event), self.event)
        self.assertEqual(validate_receipt_envelope(self.receipt), self.receipt)

    def test_unknown_fields_wrong_versions_and_bad_types_are_rejected(self) -> None:
        bad_command = dict(self.command, host_action="reset")
        wrong_command_version = dict(self.command, schema_version=2)
        bool_revision = dict(self.command, active_character_revision=True)
        bad_text = dict(self.command, text=["not", "text"])
        for value in (bad_command, wrong_command_version, bool_revision, bad_text):
            with self.subTest(envelope="command", value=value):
                with self.assertRaises(EnvelopeValidationError):
                    validate_command_envelope(value)

        for value in (
            dict(self.snapshot, private="unknown"),
            dict(self.snapshot, schema_version=False),
            dict(self.snapshot, event_cursor="0"),
        ):
            with self.subTest(envelope="snapshot", value=value):
                with self.assertRaises(EnvelopeValidationError):
                    validate_snapshot_envelope(value)

        for value in (
            dict(self.event, unknown=True),
            dict(self.event, schema_version=0),
            dict(self.event, event_id=True),
            dict(self.event, type="host.debug"),
        ):
            with self.subTest(envelope="event", value=value):
                with self.assertRaises(EnvelopeValidationError):
                    validate_event_envelope(value)

        for value in (
            dict(self.receipt, extra="field"),
            dict(self.receipt, schema_version=2),
            dict(self.receipt, status="success"),
            dict(self.receipt, request_id=7),
        ):
            with self.subTest(envelope="receipt", value=value):
                with self.assertRaises(EnvelopeValidationError):
                    validate_receipt_envelope(value)

    def test_oversized_envelopes_and_invalid_identity_bounds_are_rejected(self) -> None:
        oversized_command = dict(self.command, extra="x" * MAX_SOCKETIO_EVENT_BYTES)
        oversized_event = dict(self.event, extra="x" * MAX_SOCKETIO_EVENT_BYTES)
        oversized_receipt = dict(self.receipt, extra="x" * MAX_SOCKETIO_EVENT_BYTES)
        oversized_snapshot = dict(self.snapshot, extra="x" * MAX_SNAPSHOT_BYTES)
        for validator, payload in (
            (validate_command_envelope, oversized_command),
            (validate_event_envelope, oversized_event),
            (validate_receipt_envelope, oversized_receipt),
            (validate_snapshot_envelope, oversized_snapshot),
        ):
            with self.subTest(validator=validator.__name__):
                with self.assertRaises(EnvelopeValidationError):
                    validator(payload)

        with self.assertRaises(EnvelopeValidationError):
            validate_command_envelope(
                dict(self.command, instance_id="i" * (MAX_IDENTITY_BYTES + 1))
            )
        with self.assertRaises(EnvelopeValidationError):
            validate_command_envelope(dict(self.command, text="x" * 4097))
        with self.assertRaises(EnvelopeValidationError):
            canonical_json_bytes({"not_json": object()}, MAX_SOCKETIO_EVENT_BYTES)

    def test_one_pc_and_four_pc_snapshot_shapes_share_the_same_contract(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                sync = PlayerSyncCoordinator(self.instance_id)
                snapshot = sync.capture_snapshot(
                    self.session_epoch,
                    lambda: PlayerSnapshot(5, _projection(party_size)),
                )
                validated = validate_snapshot_envelope(snapshot)
                members = validated["projection"]["party"]["members"]
                self.assertEqual(len(members), party_size)
                self.assertEqual(validated["event_cursor"], 0)


class GameplaySyncCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance_id = _identity()
        self.session_epoch = _identity()
        self.sync = PlayerSyncCoordinator(self.instance_id)

    def test_reconnect_replays_exact_contiguous_range_once(self) -> None:
        for revision in range(1, 4):
            self.sync.publish_event(revision, "projection.updated", _projection())
        result = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            1,
            self.session_epoch,
            lambda: PlayerSnapshot(3, _projection()),
        )
        self.assertEqual(result["kind"], "replay")
        self.assertEqual(result["after_cursor"], 1)
        self.assertEqual(result["event_cursor"], 3)
        self.assertEqual([event["event_id"] for event in result["events"]], [2, 3])

        current = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            3,
            self.session_epoch,
            lambda: PlayerSnapshot(3, _projection()),
        )
        self.assertEqual(current["kind"], "replay")
        self.assertEqual(current["events"], [])

    def test_gap_expiry_instance_and_epoch_mismatch_require_fresh_snapshot(self) -> None:
        for revision in range(1, 4):
            self.sync.publish_event(revision, "projection.updated", _projection())
        middle = self.sync._events[1]
        del self.sync._events[1]
        self.sync._replay_bytes -= middle.encoded_bytes
        gap = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            0,
            self.session_epoch,
            lambda: PlayerSnapshot(9, _projection()),
        )
        self.assertEqual(gap["kind"], "resync_required")
        self.assertEqual(gap["reason"], "event_gap")
        self.assertEqual(gap["snapshot"]["event_cursor"], 3)

        expired_sync = PlayerSyncCoordinator(self.instance_id)
        for revision in range(MAX_REPLAY_EVENTS + 1):
            expired_sync.publish_event(revision, "projection.updated", _projection())
        expired = expired_sync.reconnect(
            self.instance_id,
            self.session_epoch,
            0,
            self.session_epoch,
            lambda: PlayerSnapshot(10, _projection()),
        )
        self.assertEqual(expired["reason"], "cursor_expired")
        self.assertEqual(expired["snapshot"]["event_cursor"], MAX_REPLAY_EVENTS + 1)

        wrong_instance = self.sync.reconnect(
            _identity(),
            self.session_epoch,
            0,
            self.session_epoch,
            lambda: PlayerSnapshot(11, _projection()),
        )
        self.assertEqual(wrong_instance["reason"], "instance_mismatch")
        wrong_epoch = self.sync.reconnect(
            self.instance_id,
            _identity(),
            0,
            self.session_epoch,
            lambda: PlayerSnapshot(12, _projection()),
        )
        self.assertEqual(wrong_epoch["reason"], "session_epoch_mismatch")
        future = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            100,
            self.session_epoch,
            lambda: PlayerSnapshot(13, _projection()),
        )
        self.assertEqual(future["reason"], "future_cursor")

    def test_event_snapshot_race_has_a_linearized_cursor_boundary(self) -> None:
        state_revision = [0]
        snapshot_read = threading.Event()
        allow_snapshot_return = threading.Event()
        publication_started = threading.Event()
        publication_finished = threading.Event()
        captured: list[dict[str, object]] = []

        def blocking_reader() -> PlayerSnapshot:
            observed_revision = state_revision[0]
            snapshot_read.set()
            if not allow_snapshot_return.wait(timeout=2):
                raise TimeoutError("snapshot test barrier was not released")
            return PlayerSnapshot(observed_revision, _projection())

        snapshot_thread = threading.Thread(
            target=lambda: captured.append(
                self.sync.capture_snapshot(self.session_epoch, blocking_reader)
            )
        )
        snapshot_thread.start()
        self.assertTrue(snapshot_read.wait(timeout=2))

        def publish_after_commit() -> None:
            state_revision[0] = 1
            publication_started.set()
            self.sync.publish_event(1, "projection.updated", _projection())
            publication_finished.set()

        publisher_thread = threading.Thread(target=publish_after_commit)
        publisher_thread.start()
        self.assertTrue(publication_started.wait(timeout=2))
        self.assertFalse(publication_finished.is_set())
        allow_snapshot_return.set()
        snapshot_thread.join(timeout=2)
        publisher_thread.join(timeout=2)
        self.assertFalse(snapshot_thread.is_alive())
        self.assertFalse(publisher_thread.is_alive())
        self.assertTrue(publication_finished.is_set())

        first_snapshot = captured[0]
        self.assertEqual(first_snapshot["revision"], 0)
        self.assertEqual(first_snapshot["event_cursor"], 0)
        replay = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            first_snapshot["event_cursor"],
            self.session_epoch,
            lambda: PlayerSnapshot(state_revision[0], _projection()),
        )
        self.assertEqual([event["event_id"] for event in replay["events"]], [1])

        second_snapshot = self.sync.capture_snapshot(
            self.session_epoch,
            lambda: PlayerSnapshot(state_revision[0], _projection()),
        )
        after_hydration = self.sync.reconnect(
            self.instance_id,
            self.session_epoch,
            second_snapshot["event_cursor"],
            self.session_epoch,
            lambda: PlayerSnapshot(state_revision[0], _projection()),
        )
        self.assertEqual(second_snapshot["event_cursor"], 1)
        self.assertEqual(after_hydration["events"], [])

    def test_replay_retention_never_exceeds_event_or_byte_bounds(self) -> None:
        for revision in range(MAX_REPLAY_EVENTS + 3):
            self.sync.publish_event(revision, "projection.updated", _projection())
        self.assertLessEqual(len(self.sync._events), MAX_REPLAY_EVENTS)
        self.assertLessEqual(self.sync._replay_bytes, MAX_REPLAY_BYTES)
        self.assertEqual(self.sync.event_cursor, MAX_REPLAY_EVENTS + 3)

        byte_limited = PlayerSyncCoordinator(_identity())
        large_projection = _projection()
        large_projection["party"]["world"]["currentLocation"] = "x" * 4000
        for revision in range(80):
            byte_limited.publish_event(revision, "projection.updated", large_projection)
        self.assertLessEqual(byte_limited._replay_bytes, MAX_REPLAY_BYTES)
        self.assertLess(len(byte_limited._events), MAX_REPLAY_EVENTS)
        self.assertGreater(byte_limited._events[0].event.event_id, 1)


class GameplaySyncDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance_id = _identity()
        self.session_epoch = _identity()
        self.sync = PlayerSyncCoordinator(self.instance_id)
        self.limiters, self.session_id = _new_dedup_state(self.session_epoch)
        self.gateway = _Gateway()

    def test_duplicate_request_returns_original_receipt_without_readmission(self) -> None:
        command = _command(self.instance_id, self.session_epoch)
        first = self.sync.submit_command(
            command,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        retry = self.sync.submit_command(
            command,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(retry, first)
        self.assertEqual(len(self.gateway.admissions), 1)
        self.assertEqual(self.limiters.receipt_count(self.session_id), 1)

    def test_concurrent_duplicate_requests_admit_once(self) -> None:
        entered_gateway = threading.Event()
        release_gateway = threading.Event()
        gateway = self.gateway

        class _BlockingGateway:
            def admit_input(self, command: object) -> PlayerInputAdmission:
                gateway.admissions.append(command)
                entered_gateway.set()
                if not release_gateway.wait(timeout=2):
                    raise TimeoutError("dedup test gateway barrier was not released")
                return PlayerInputAdmission(
                    request_id=getattr(command, "request_id"),
                    status="accepted",
                )

        command = _command(self.instance_id, self.session_epoch)
        start = threading.Barrier(3)
        receipts: list[dict[str, object]] = []

        def submit() -> None:
            start.wait(timeout=2)
            receipts.append(
                self.sync.submit_command(
                    command,
                    session_id=self.session_id,
                    session_epoch=self.session_epoch,
                    limiters=self.limiters,
                    gateway=_BlockingGateway(),
                )
            )

        workers = [threading.Thread(target=submit) for _index in range(2)]
        for worker in workers:
            worker.start()
        start.wait(timeout=2)
        self.assertTrue(entered_gateway.wait(timeout=2))
        release_gateway.set()
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(len(gateway.admissions), 1)

    def test_conflicting_request_id_is_rejected_without_readmission(self) -> None:
        original = _command(self.instance_id, self.session_epoch)
        self.sync.submit_command(
            original,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        for changed in (
            dict(original, text="Move south"),
            dict(original, character_name="Merisiel"),
        ):
            result = self.sync.submit_command(
                changed,
                session_id=self.session_id,
                session_epoch=self.session_epoch,
                limiters=self.limiters,
                gateway=self.gateway,
            )
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["code"], "request_id_conflict")
        self.assertEqual(len(self.gateway.admissions), 1)

    def test_bad_commands_are_rejected_before_gateway_and_request_identity_is_retained(self) -> None:
        invalid = dict(_command(self.instance_id, self.session_epoch), host_action="shutdown")
        first = self.sync.submit_command(
            invalid,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        retry = self.sync.submit_command(
            invalid,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["code"], "invalid_command")
        self.assertEqual(retry, first)
        self.assertEqual(self.gateway.admissions, [])

    def test_receipt_cap_refuses_new_commands_without_evicting_retained_ids(self) -> None:
        for index in range(MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION):
            self.assertTrue(
                self.limiters.retain_receipt(
                    self.session_id,
                    f"used-{index}",
                    {"status": "accepted"},
                )
            )
        command = _command(
            self.instance_id,
            self.session_epoch,
            request_id="new-after-cap",
        )
        result = self.sync.submit_command(
            command,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        self.assertEqual(result["code"], "receipt_capacity")
        self.assertEqual(self.limiters.receipt_count(self.session_id), MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION)
        self.assertEqual(self.limiters.get_receipt(self.session_id, "used-0"), {"status": "accepted"})
        self.assertEqual(self.gateway.admissions, [])

    def test_gateway_failure_is_uncertain_and_not_retried(self) -> None:
        command = _command(self.instance_id, self.session_epoch)
        unavailable = UnavailablePlayerGateway()
        first = self.sync.submit_command(
            command,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=unavailable,
        )
        retry = self.sync.submit_command(
            command,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )
        self.assertEqual(first["status"], "uncertain")
        self.assertEqual(first["code"], "runtime_admission_uncertain")
        self.assertEqual(retry, first)
        self.assertEqual(self.gateway.admissions, [])

    def test_old_instance_command_after_restart_is_uncertain_not_replayed(self) -> None:
        old_instance = self.instance_id
        old_epoch = self.session_epoch
        new_instance = _identity()
        new_epoch = _identity()
        self.sync.reset_for_instance(new_instance)
        new_limiters, new_session_id = _new_dedup_state(new_epoch)
        old_command = _command(old_instance, old_epoch, text="Uncertain retry")
        result = self.sync.submit_command(
            old_command,
            session_id=new_session_id,
            session_epoch=new_epoch,
            limiters=new_limiters,
            gateway=self.gateway,
        )
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["code"], "server_instance_changed")
        self.assertEqual(self.sync.event_cursor, 0)
        self.assertEqual(self.gateway.admissions, [])


class GameplaySyncApplicationTests(unittest.TestCase):
    def test_security_epochs_are_session_scoped_and_rotate_with_instance(self) -> None:
        security = PlayerSecurity(lambda: None)
        first = security.create_session()
        second = security.create_session()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.cookie_value.split(".")[1], security.server_instance_id)
        self.assertNotEqual(first.session_epoch, second.session_epoch)
        previous_instance = security.server_instance_id
        security.start_listener()
        self.assertNotEqual(security.server_instance_id, previous_instance)
        self.assertIsNone(security.session_context_for_cookie(first.cookie_value))

    def test_snapshot_route_event_publication_and_reconnect_share_cursor(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                security = PlayerSecurity(lambda: None)
                grant = security.create_session()
                self.assertIsNotNone(grant)
                assert grant is not None
                gateway = _Gateway(party_size)
                app = create_app(gateway=gateway, security=security)
                self.assertTrue(
                    security.register_socket(
                        f"sync-sid-{party_size}",
                        grant.cookie_value,
                        f"{PLAYER_HOST}:{PLAYER_PORT}",
                        f"http://{PLAYER_HOST}:{PLAYER_PORT}",
                    )
                )

                status, body = _dispatch_http(
                    app,
                    "/api/player/snapshot",
                    cookie=grant.cookie_value,
                )
                self.assertEqual(status, 200)
                snapshot = json.loads(body)
                self.assertEqual(snapshot["schema_version"], PROTOCOL_VERSION)
                self.assertEqual(snapshot["event_cursor"], 0)
                self.assertEqual(snapshot["session_epoch"], grant.session_epoch)
                self.assertEqual(
                    len(snapshot["projection"]["party"]["members"]),
                    party_size,
                )

                emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

                async def capture_emit(*args: object, **kwargs: object) -> None:
                    emitted.append((args, kwargs))

                app.socket_server.emit = capture_emit
                delivered = asyncio.run(
                    app.publish_player_event(
                        2,
                        "projection.updated",
                        _projection(party_size),
                    )
                )
                self.assertEqual(delivered, 1)
                self.assertEqual(emitted[0][0][0], "player.event")
                event = emitted[0][0][1]
                self.assertEqual(event["event_id"], 1)
                self.assertEqual(event["session_epoch"], grant.session_epoch)

                query = urlencode(
                    {
                        "instance_id": security.server_instance_id,
                        "session_epoch": grant.session_epoch,
                        "cursor": 0,
                    }
                )
                replay_status, replay_body = _dispatch_http(
                    app,
                    "/api/player/snapshot",
                    query=query,
                    cookie=grant.cookie_value,
                )
                self.assertEqual(replay_status, 200)
                replay = json.loads(replay_body)
                self.assertEqual(replay["kind"], "replay")
                self.assertEqual([item["event_id"] for item in replay["events"]], [1])

                stale_query = urlencode(
                    {
                        "instance_id": _identity(),
                        "session_epoch": grant.session_epoch,
                        "cursor": 0,
                    }
                )
                resync_status, resync_body = _dispatch_http(
                    app,
                    "/api/player/snapshot",
                    query=stale_query,
                    cookie=grant.cookie_value,
                )
                resync = json.loads(resync_body)
                self.assertEqual(resync_status, 200)
                self.assertEqual(resync["kind"], "resync_required")
                self.assertEqual(resync["reason"], "instance_mismatch")
                self.assertEqual(resync["snapshot"]["event_cursor"], 1)

    def test_player_input_event_emits_deduplicated_typed_receipt(self) -> None:
        security = PlayerSecurity(lambda: None)
        grant = security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        gateway = _Gateway()
        app = create_app(gateway=gateway, security=security)
        sid = "command-sid"
        self.assertTrue(
            security.register_socket(
                sid,
                grant.cookie_value,
                f"{PLAYER_HOST}:{PLAYER_PORT}",
                f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
        )
        emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def capture_emit(*args: object, **kwargs: object) -> None:
            emitted.append((args, kwargs))

        app.socket_server.emit = capture_emit
        handler = app.socket_server.handlers[PLAYER_NAMESPACE]["player.input.submit"]
        command = _command(
            security.server_instance_id,
            grant.session_epoch,
        )
        asyncio.run(handler(sid, command))
        asyncio.run(handler(sid, command))
        self.assertEqual(len(gateway.admissions), 1)
        self.assertEqual(len(emitted), 2)
        self.assertEqual(emitted[0][0][0], "player.input.receipt")
        self.assertEqual(emitted[1][0][1], emitted[0][0][1])
        self.assertEqual(emitted[0][0][1]["status"], "accepted")

        changed = dict(command, text="Move east")
        asyncio.run(handler(sid, changed))
        self.assertEqual(len(gateway.admissions), 1)
        self.assertEqual(emitted[-1][0][1]["code"], "request_id_conflict")

    def test_changed_session_epoch_and_invalid_command_never_reach_gateway(self) -> None:
        security = PlayerSecurity(lambda: None)
        grant = security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        gateway = _Gateway()
        app = create_app(gateway=gateway, security=security)
        sid = "invalid-command-sid"
        self.assertTrue(
            security.register_socket(
                sid,
                grant.cookie_value,
                f"{PLAYER_HOST}:{PLAYER_PORT}",
                f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
        )
        emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def capture_emit(*args: object, **kwargs: object) -> None:
            emitted.append((args, kwargs))

        app.socket_server.emit = capture_emit
        handler = app.socket_server.handlers[PLAYER_NAMESPACE]["player.input.submit"]
        stale = _command(
            security.server_instance_id,
            _identity(),
            request_id="stale-epoch",
        )
        asyncio.run(handler(sid, stale))
        self.assertEqual(emitted[-1][0][1]["status"], "uncertain")
        self.assertEqual(emitted[-1][0][1]["code"], "session_epoch_changed")

        malformed = {"text": "not an envelope"}
        asyncio.run(handler(sid, malformed))
        self.assertEqual(emitted[-1][0][0], "player.error")
        self.assertEqual(emitted[-1][0][1]["code"], "invalid_command")
        self.assertEqual(gateway.admissions, [])


if __name__ == "__main__":
    unittest.main()
