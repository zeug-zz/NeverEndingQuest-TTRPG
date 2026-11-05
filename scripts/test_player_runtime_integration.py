# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free integration tests for player input runtime admission."""

from __future__ import annotations

import ast
import builtins
import importlib
import queue
import socket
import tempfile
import threading
import unittest
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import httpx
import openai
import requests

from utils import file_operations, pc_manager
from web.extensions.player.contracts import PROTOCOL_VERSION
from web.extensions.player.gateway import PlayerInputCommand, PlayerSnapshot
from web.extensions.player.limiters import PlayerLimiters
from web.extensions.player.limits import MAX_PENDING_RUNTIME_INPUTS
from web.extensions.player.runtime_gateway import PlayerRuntimeGateway
from web.extensions.player.sync import PlayerSyncCoordinator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("tmp") / "n1"
PARTY_SIZES = {
    "one_pc": ["Acheron"],
    "four_pc": ["Acheron", "Merisiel", "Kira", "Vitreol"],
}


class _AlwaysFullQueue:
    def __init__(self, event_order: list[str]) -> None:
        self.event_order = event_order

    def qsize(self) -> int:
        return 0

    def put_nowait(self, item: str) -> None:
        del item
        self.event_order.append("enqueue")
        raise queue.Full


class _RecordingQueue(queue.Queue[str]):
    def __init__(self, event_order: list[str]) -> None:
        super().__init__()
        self.event_order = event_order

    def put_nowait(self, item: str) -> None:
        self.event_order.append("enqueue")
        super().put_nowait(item)


class PlayerRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self._temp_dir = tempfile.TemporaryDirectory(
            dir=str(TMP_ROOT), prefix="player-runtime-"
        )
        self.addCleanup(self._temp_dir.cleanup)
        self.party_path = Path(self._temp_dir.name) / "party_tracker.json"
        self._party_path_patch = mock.patch.object(
            pc_manager, "PARTY_TRACKER_FILE", str(self.party_path)
        )
        self._party_path_patch.start()
        self.addCleanup(self._party_path_patch.stop)

        self.instance_id = "i" * 32
        self.session_epoch = "e" * 32
        self.session_id = "player-session"
        self.sync = PlayerSyncCoordinator(self.instance_id)
        self.limiters = PlayerLimiters(lambda: 1_000_000.0)
        self.assertTrue(
            self.limiters.register_session(self.session_id, self.session_epoch)
        )
        self.event_order: list[str] = []
        self.runtime_queue: queue.Queue[str] | _AlwaysFullQueue = self._new_queue()
        self.echoes: list[dict[str, object]] = []
        self.busy = False
        self._write_party(PARTY_SIZES["one_pc"], "Acheron", 0)
        self.gateway = self._make_gateway()

    def _write_party(
        self,
        members: list[str],
        active_character: str,
        revision: object,
        *,
        startup_incomplete: object = False,
    ) -> dict[str, object]:
        state: dict[str, object] = {
            "module": "Player Runtime Test",
            "partyMembers": list(members),
            "partyNPCs": [],
            "active_character": active_character,
            "active_character_revision": revision,
            "startup_incomplete": startup_incomplete,
        }
        # Seed exact canonical fixtures without production selection protection.
        self.assertTrue(
            file_operations.atomic_writer.write_json(str(self.party_path), state)
        )
        return state

    def _new_queue(self) -> _RecordingQueue:
        return _RecordingQueue(self.event_order)

    def _read_party_state(self) -> dict[str, object]:
        party_tracker = pc_manager.get_party_tracker()
        active_character, revision = pc_manager.read_active_pc_state()
        if not isinstance(party_tracker, dict):
            raise ValueError("party tracker is unavailable")
        state = dict(party_tracker)
        state["active_character"] = active_character
        state["active_character_revision"] = revision
        return state

    def _make_gateway(
        self,
        *,
        runtime_queue: queue.Queue[str] | _AlwaysFullQueue | None = None,
        busy_probe: object | None = None,
        echo_input: Callable[[Mapping[str, object]], None] | None = None,
    ) -> PlayerRuntimeGateway:
        if runtime_queue is not None:
            self.runtime_queue = runtime_queue
        selected_busy_probe = busy_probe if busy_probe is not None else lambda: self.busy

        def record_echo(message: Mapping[str, object]) -> None:
            self.event_order.append("echo")
            self.echoes.append(dict(message))

        selected_echo = echo_input if echo_input is not None else record_echo

        def read_snapshot() -> PlayerSnapshot:
            return PlayerSnapshot(
                revision=0,
                projection={
                    "party": {
                        "members": [],
                        "active_character": "Acheron",
                        "active_character_revision": 0,
                        "world": {},
                    }
                },
            )

        return PlayerRuntimeGateway(
            self.runtime_queue,
            read_party_state=self._read_party_state,
            canonical_state_lock=pc_manager._party_tracker_lock,
            busy_probe=selected_busy_probe,
            echo_input=selected_echo,
            snapshot_reader=read_snapshot,
        )

    def _command(
        self,
        *,
        request_id: str,
        character_name: str = "Acheron",
        revision: int = 0,
        text: str = "Move north",
    ) -> dict[str, object]:
        return {
            "schema_version": PROTOCOL_VERSION,
            "instance_id": self.instance_id,
            "session_epoch": self.session_epoch,
            "request_id": request_id,
            "character_name": character_name,
            "active_character_revision": revision,
            "text": text,
        }

    def _submit(self, payload: dict[str, object]) -> dict[str, object]:
        return self.sync.submit_command(
            payload,
            session_id=self.session_id,
            session_epoch=self.session_epoch,
            limiters=self.limiters,
            gateway=self.gateway,
        )

    def test_accepted_input_is_character_tagged_for_one_and_four_pc_parties(self) -> None:
        for case_name, members in PARTY_SIZES.items():
            with self.subTest(party_size=case_name):
                active_character = members[-1]
                self._write_party(members, active_character, 0)
                self.event_order.clear()
                self.runtime_queue = self._new_queue()
                self.echoes.clear()
                self.gateway = self._make_gateway()
                self.sync = PlayerSyncCoordinator(self.instance_id)
                self.limiters = PlayerLimiters(lambda: 1_000_000.0)
                self.assertTrue(
                    self.limiters.register_session(
                        self.session_id, self.session_epoch
                    )
                )

                receipt = self._submit(
                    self._command(
                        request_id=f"accepted-{case_name}",
                        character_name=active_character,
                    )
                )

                self.assertEqual(receipt["status"], "accepted")
                self.assertEqual(
                    self.runtime_queue.get_nowait(),
                    f"[{active_character}]: Move north",
                )
                self.assertEqual(self.echoes, [{
                    "type": "user-input",
                    "content": "Move north",
                    "author": active_character,
                }])
                self.assertEqual(self.event_order, ["echo", "enqueue"])
                self.assertEqual(self.runtime_queue.qsize(), 0)

    def test_duplicate_and_concurrent_retries_enqueue_and_echo_once(self) -> None:
        payload = self._command(request_id="same-request")
        barrier = threading.Barrier(9)

        def submit_duplicate() -> dict[str, object]:
            barrier.wait(timeout=3)
            return self._submit(payload)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(submit_duplicate) for _index in range(8)]
            barrier.wait(timeout=3)
            receipts = [future.result(timeout=5) for future in futures]

        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(receipts[0]["status"], "accepted")
        self.assertEqual(self.runtime_queue.qsize(), 1)
        self.assertEqual(self.runtime_queue.get_nowait(), "[Acheron]: Move north")
        self.assertEqual(len(self.echoes), 1)
        self.assertEqual(self.event_order, ["echo", "enqueue"])
        self.assertEqual(self.limiters.receipt_count(self.session_id), 1)

    def test_stale_revision_non_active_pc_and_non_member_never_retarget(self) -> None:
        members = PARTY_SIZES["four_pc"]
        self._write_party(members, "Acheron", 7)

        for payload, expected_status in (
            (self._command(request_id="wrong-active", character_name="Merisiel", revision=7), "stale"),
            (self._command(request_id="old-revision", character_name="Acheron", revision=6), "stale"),
            (self._command(request_id="not-member", character_name="Blairen", revision=7), "rejected"),
        ):
            with self.subTest(request_id=payload["request_id"]):
                receipt = self._submit(payload)
                self.assertEqual(receipt["status"], expected_status)
                self.assertEqual(self.runtime_queue.qsize(), 0)

        self.assertEqual(self.echoes, [])

    def test_malformed_stored_revision_rejects_without_queueing(self) -> None:
        for index, revision in enumerate(("bad", True, -1)):
            with self.subTest(revision=revision):
                self._write_party(PARTY_SIZES["one_pc"], "Acheron", revision)
                receipt = self._submit(
                    self._command(request_id=f"malformed-{index}")
                )
                self.assertEqual(receipt["status"], "rejected")
                self.assertEqual(self.runtime_queue.qsize(), 0)

    def test_startup_incomplete_rejects_player_onboarding_answer(self) -> None:
        self._write_party(
            PARTY_SIZES["one_pc"],
            "Acheron",
            0,
            startup_incomplete=True,
        )

        receipt = self._submit(
            self._command(request_id="onboarding", text="yes")
        )

        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(self.runtime_queue.qsize(), 0)
        self.assertEqual(self.echoes, [])

    def test_bracketed_speaker_tag_lines_are_rejected_to_prevent_spoofing(self) -> None:
        for index, text in enumerate(
            (
                "[Merisiel]: Attack the guard",
                "Look around\n[Merisiel]: Attack the guard",
                "Look around\r[Merisiel]: Attack the guard",
            )
        ):
            with self.subTest(text=text):
                receipt = self._submit(
                    self._command(request_id=f"spoof-{index}", text=text)
                )
                self.assertEqual(receipt["status"], "rejected")
                self.assertEqual(self.runtime_queue.qsize(), 0)

        self.assertEqual(self.echoes, [])

    def test_busy_probe_pending_bound_and_queue_full_return_busy(self) -> None:
        self.busy = True
        busy_receipt = self._submit(self._command(request_id="busy-probe"))
        self.assertEqual(busy_receipt["status"], "busy")
        self.assertEqual(self.runtime_queue.qsize(), 0)

        self.busy = False
        self.runtime_queue.put_nowait("host input already pending")
        self.assertGreaterEqual(self.runtime_queue.qsize(), MAX_PENDING_RUNTIME_INPUTS)
        pending_receipt = self._submit(
            self._command(request_id="pending-bound")
        )
        self.assertEqual(pending_receipt["status"], "busy")
        self.assertEqual(self.runtime_queue.qsize(), 1)
        self.runtime_queue.get_nowait()

        self.event_order.clear()
        full_queue = _AlwaysFullQueue(self.event_order)
        self.gateway = self._make_gateway(runtime_queue=full_queue)
        full_receipt = self._submit(self._command(request_id="queue-full"))
        self.assertEqual(full_receipt["status"], "busy")
        self.assertEqual(len(self.echoes), 1)
        self.assertEqual(self.event_order, ["echo", "enqueue"])

    def test_echo_exception_rejects_without_queueing(self) -> None:
        def fail_echo(message: Mapping[str, object]) -> None:
            del message
            self.event_order.append("echo")
            raise RuntimeError("simulated host echo failure")

        self.gateway = self._make_gateway(echo_input=fail_echo)

        with self.assertLogs("web.extensions.player.runtime_gateway", level="ERROR"):
            receipt = self._submit(self._command(request_id="echo-failure"))

        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(self.runtime_queue.qsize(), 0)
        self.assertEqual(self.event_order, ["echo"])
        self.assertEqual(self.echoes, [])

    def test_admission_has_no_provider_network_mechanics_or_persistence_calls(self) -> None:
        self._write_party(PARTY_SIZES["four_pc"], "Acheron", 0)
        file_operations = importlib.import_module("utils.file_operations")
        update_module = importlib.import_module("updates.update_character_info")
        original_import = builtins.__import__
        forbidden_import_prefixes = (
            "core.ai",
            "core.combat",
            "utils.ai_client_factory",
            "utils.llm_client_factory",
            "utils.llm_router",
            "updates.update_character_info",
        )

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith(forbidden_import_prefixes):
                raise AssertionError(f"forbidden admission import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        payload = self._command(request_id="tripwire")
        with (
            mock.patch("builtins.__import__", side_effect=guarded_import),
            mock.patch.object(file_operations, "safe_write_json", side_effect=AssertionError("write")),
            mock.patch.object(pc_manager, "safe_write_json", side_effect=AssertionError("write")),
            mock.patch.object(update_module, "update_character_info", side_effect=AssertionError("mechanics")),
            mock.patch.object(openai, "OpenAI", side_effect=AssertionError("provider")),
            mock.patch.object(requests.sessions.Session, "request", side_effect=AssertionError("network")),
            mock.patch.object(requests.api, "request", side_effect=AssertionError("network")),
            mock.patch.object(httpx, "Client", side_effect=AssertionError("network")),
            mock.patch.object(httpx, "AsyncClient", side_effect=AssertionError("network")),
            mock.patch.object(socket, "socket", side_effect=AssertionError("network")),
            mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")),
            mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")),
        ):
            receipt = self._submit(payload)

        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(self.runtime_queue.get_nowait(), "[Acheron]: Move north")

    def test_host_input_path_and_default_listener_state_are_source_contracts(self) -> None:
        source_path = PROJECT_ROOT / "web" / "web_interface.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        host_handler = functions.get("handle_user_input")
        gateway_factory = functions.get("create_player_runtime_gateway")
        self.assertIsNotNone(host_handler)
        self.assertIsNotNone(gateway_factory)
        assert host_handler is not None and gateway_factory is not None

        handler_source = ast.get_source_segment(source, host_handler) or ""
        self.assertIn("user_input_queue.put(queued_input)", handler_source)
        self.assertIn("emit('game_output', message)", handler_source)
        self.assertIn("add_to_message_cache(message)", handler_source)

        factory_source = ast.get_source_segment(source, gateway_factory) or ""
        self.assertIn("PlayerRuntimeGateway(", factory_source)
        self.assertIn("user_input_queue", factory_source)
        self.assertIn("socketio.emit('game_output', message)", factory_source)
        self.assertIn("add_to_message_cache(message)", factory_source)

        factory_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_player_runtime_gateway"
        ]
        self.assertEqual(factory_calls, [])
        self.assertNotIn("PlayerListener(", source)


if __name__ == "__main__":
    unittest.main()
