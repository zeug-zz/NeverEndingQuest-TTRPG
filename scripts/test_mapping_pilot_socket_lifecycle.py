# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Socket.IO and owned-worker lifecycle diagnostics tests."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.mapping_pilot.row_runner import (
    SocketScriptDriver,
    _socket_worker_lifecycle_snapshot,
)


class _FakeSession:
    def __init__(self, _args: Any) -> None:
        self.disconnected = False
        self.connected = False
        self.start_readiness = {"status": "ready"}
        self.disconnect_handler: Any = None
        self.disconnect_calls = 0
        self.transcript_closed = False

    def open_transcript(self) -> None:
        return None

    def connect(self) -> None:
        self.connected = True
        self.disconnect_handler = self._on_disconnect

    def start_session(self, require_ready_quiet: bool = False) -> bool:
        return True

    def _on_disconnect(self, *_args: Any) -> None:
        self.disconnected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False
        if self.disconnect_handler is not None:
            self.disconnect_handler("client disconnect")

    def close_transcript(self) -> None:
        self.transcript_closed = True


class _FakeProcess:
    def __init__(self, return_code: int | None) -> None:
        self.return_code = return_code

    def poll(self) -> int | None:
        return self.return_code


class _FakeServer:
    def __init__(self, return_code: int | None) -> None:
        self.process = _FakeProcess(return_code)


class MappingPilotSocketLifecycleTests(unittest.TestCase):
    def _driver(self, session_factory: Any = _FakeSession) -> SocketScriptDriver:
        driver = SocketScriptDriver(
            party_size=1,
            transcript_path=Path("tmp/mapping-pilot-socket-test/transcript.txt"),
            runtime_root="tmp/combat_capture",
            session_factory=session_factory,
        )
        self.addCleanup(driver.close)
        return driver

    def test_remote_disconnect_reason_and_running_worker_are_recorded(self) -> None:
        driver = self._driver()
        driver.start()
        live_started = time.monotonic() - 2.0
        driver.session.disconnect_handler("transport error")
        driver.close()

        snapshot = _socket_worker_lifecycle_snapshot(
            driver,
            _FakeServer(None),
            live_started,
        )

        self.assertTrue(snapshot["socket_disconnect_observed"])
        self.assertEqual(snapshot["socket_disconnect_reason"], "transport_error")
        self.assertEqual(snapshot["socket_disconnect_initiator"], "socket_callback")
        self.assertEqual(
            snapshot["socket_payload_decode_bound"],
            {
                "source": "engineio.payload.Payload.max_decode_packets",
                "before": 16,
                "active": 64,
                "after": 16,
                "restored": True,
            },
        )
        self.assertGreaterEqual(snapshot["socket_disconnect_after_launch_seconds"], 2.0)
        self.assertEqual(snapshot["worker_state_at_capture"], "running")
        self.assertIsNone(snapshot["worker_return_code_at_capture"])

    def test_teardown_and_unknown_reason_are_sanitized(self) -> None:
        driver = self._driver()
        driver.start()
        driver.session.disconnect_handler("secret-bearing unexpected reason")
        driver.close()

        snapshot = _socket_worker_lifecycle_snapshot(
            driver,
            _FakeServer(-9),
            None,
        )

        self.assertEqual(snapshot["socket_disconnect_reason"], "other")
        self.assertEqual(snapshot["socket_disconnect_initiator"], "socket_callback")
        self.assertNotIn("secret-bearing", repr(snapshot))
        self.assertEqual(snapshot["worker_state_at_capture"], "exited")
        self.assertEqual(snapshot["worker_return_code_at_capture"], -9)

    def test_driver_disconnect_is_distinguished_from_remote_disconnect(self) -> None:
        driver = self._driver()
        driver.start()
        driver.close()

        snapshot = _socket_worker_lifecycle_snapshot(
            driver,
            _FakeServer(0),
            None,
        )

        self.assertEqual(snapshot["socket_disconnect_reason"], "client_disconnect")
        self.assertEqual(snapshot["socket_disconnect_initiator"], "driver_close")
        self.assertEqual(snapshot["worker_state_at_capture"], "exited")
        self.assertEqual(snapshot["worker_return_code_at_capture"], 0)

    def test_capture_scope_decodes_22_packets_caps_65_and_restores_library_default(self) -> None:
        from engineio import packet
        from engineio.payload import Payload

        encoded_packet = packet.Packet(packet.MESSAGE, data="capture").encode()
        encoded_22 = "\x1e".join([encoded_packet] * 22)
        encoded_65 = "\x1e".join([encoded_packet] * 65)

        self.assertEqual(Payload.max_decode_packets, 16)
        with self.assertRaisesRegex(ValueError, "Too many packets"):
            Payload().decode(encoded_22)

        driver = self._driver()
        driver.start()
        self.assertEqual(Payload.max_decode_packets, 64)
        active_observation = driver.socket_lifecycle_metadata(
            live_started_monotonic=None
        )["socket_payload_decode_bound"]
        self.assertEqual(active_observation["before"], 16)
        self.assertEqual(active_observation["active"], 64)
        self.assertIsNone(active_observation["after"])
        self.assertFalse(active_observation["restored"])
        bounded_payload = Payload()
        bounded_payload.decode(encoded_22)
        self.assertEqual(len(bounded_payload.packets), 22)
        with self.assertRaisesRegex(ValueError, "Too many packets"):
            Payload().decode(encoded_65)

        driver.close()
        self.assertEqual(Payload.max_decode_packets, 16)
        with self.assertRaisesRegex(ValueError, "Too many packets"):
            Payload().decode(encoded_22)

    def test_overlapping_drivers_are_refused_without_disturbing_current_owner(self) -> None:
        from engineio.payload import Payload

        owner = self._driver()
        overlapping = self._driver()
        owner.start()
        self.assertEqual(Payload.max_decode_packets, 64)

        with self.assertRaisesRegex(RuntimeError, "another mapping-pilot"):
            overlapping.start()
        self.assertEqual(Payload.max_decode_packets, 64)
        self.assertTrue(owner.session.connected)

        owner.close()
        self.assertEqual(Payload.max_decode_packets, 16)
        self.assertEqual(overlapping.session.disconnect_calls, 1)

    def test_changed_preexisting_decoder_bound_fails_closed_without_mutation(self) -> None:
        from engineio.payload import Payload

        original = Payload.max_decode_packets
        driver = self._driver()
        Payload.max_decode_packets = 23
        try:
            with self.assertRaisesRegex(RuntimeError, "expected the library default of 16"):
                driver.start()
            self.assertEqual(Payload.max_decode_packets, 23)
            self.assertFalse(driver.session.connected)
        finally:
            Payload.max_decode_packets = original
            driver.close()

    def test_unexpected_active_bound_change_is_restored_and_reported(self) -> None:
        from engineio.payload import Payload

        driver = self._driver()
        driver.start()
        Payload.max_decode_packets = 32

        with self.assertRaisesRegex(RuntimeError, "changed during the capture session"):
            driver.close()

        self.assertEqual(Payload.max_decode_packets, 16)
        metadata = driver.socket_lifecycle_metadata(live_started_monotonic=None)
        self.assertTrue(metadata["socket_payload_decode_bound"]["restored"])

    def test_session_constructor_failure_leaves_decoder_default_untouched(self) -> None:
        from engineio.payload import Payload

        def fail_constructor(_args: Any) -> Any:
            self.assertEqual(Payload.max_decode_packets, 16)
            raise ValueError("injected constructor failure")

        with self.assertRaisesRegex(ValueError, "injected constructor failure"):
            self._driver(fail_constructor)
        self.assertEqual(Payload.max_decode_packets, 16)

    def test_start_failure_disconnects_and_restores_decoder_bound(self) -> None:
        from engineio.payload import Payload

        class FailingSession(_FakeSession):
            def connect(self) -> None:
                self.connected = True
                self.disconnect_handler = self._on_disconnect
                raise ValueError("injected connect failure")

        driver = self._driver(FailingSession)
        with self.assertRaisesRegex(ValueError, "injected connect failure"):
            driver.start()

        self.assertEqual(Payload.max_decode_packets, 16)
        self.assertFalse(driver.session.connected)
        self.assertEqual(driver.session.disconnect_calls, 1)
        self.assertTrue(driver.session.transcript_closed)

    def test_close_joins_active_read_loop_before_restoring_decoder_bound(self) -> None:
        from engineio.payload import Payload

        class ReadLoopTask:
            def __init__(self) -> None:
                self.alive = True
                self.bound_during_join: Any = None

            def is_alive(self) -> bool:
                return self.alive

            def join(self) -> None:
                self.bound_during_join = Payload.max_decode_packets
                self.alive = False

        class EngineIOClient:
            def __init__(self) -> None:
                self.state = "connected"
                self.read_loop_task = ReadLoopTask()

        class SocketClient:
            def __init__(self) -> None:
                self.eio = EngineIOClient()

        class ThreadedSession(_FakeSession):
            def __init__(self, args: Any) -> None:
                super().__init__(args)
                self.socket = SocketClient()

        driver = self._driver(ThreadedSession)
        driver.start()
        task = driver.session.socket.eio.read_loop_task
        driver.close()

        self.assertEqual(task.bound_during_join, 64)
        self.assertFalse(task.is_alive())
        self.assertEqual(Payload.max_decode_packets, 16)


if __name__ == "__main__":
    unittest.main()
