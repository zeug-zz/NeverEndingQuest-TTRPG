# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free regression for nonblocking Socket.IO connect updates."""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _import_web_interface_provider_free():
    """Import the web app without starting unrelated workers or providers."""
    if "web.web_interface" in sys.modules:
        return sys.modules["web.web_interface"]

    import threading

    from core.memory import memory_db
    from utils import ai_client_factory
    from web.extensions import missing_media_autogen, module_ingest_watch

    class _NoStartThread:
        def __init__(self, *args, **kwargs):
            self.daemon = kwargs.get("daemon", False)

        def start(self):
            return None

    with mock.patch.object(
        memory_db, "bootstrap_memory_db_from_seed", return_value={"status": "skipped"}
    ), mock.patch.object(memory_db, "init_memory_db", return_value=True), mock.patch.object(
        missing_media_autogen, "start_missing_media_autogen_worker"
    ), mock.patch.object(
        module_ingest_watch, "start_module_ingest_watch_worker"
    ), mock.patch.object(
        threading, "Thread", _NoStartThread
    ), mock.patch.object(
        ai_client_factory, "create_chat_client", return_value=mock.Mock()
    ), mock.patch("os.makedirs", return_value=None):
        import web.web_interface as web_interface

    return web_interface


web_interface = _import_web_interface_provider_free()


class TestWebConnectNonblockingVersionCheck(unittest.TestCase):
    def test_connect_schedules_version_check_and_emits_to_connecting_sid(self):
        from utils import version_checker

        calls = []
        background_tasks = []
        emitted = []
        event_order = []
        original_connect_emit = web_interface.emit
        update_target = {
            "owner_repo": "example-owner/example-repo",
            "branch": "stable",
        }
        remote_version = "9.8.7"

        def delayed_resolve_update_target(*, repo_path):
            calls.append(("resolve_update_target", repo_path))
            time.sleep(0.01)
            return update_target

        def delayed_get_latest_remote_version(owner_repo, branch, *, silent):
            calls.append(("get_latest_remote_version", owner_repo, branch, silent))
            time.sleep(0.01)
            return remote_version

        def delayed_compare_versions(local, remote):
            calls.append(("compare_versions", local, remote))
            time.sleep(0.01)
            return "update_available"

        def record_background_task(target, *args, **kwargs):
            event_order.append("background_task")
            background_tasks.append((target, args, kwargs))
            return None

        def record_connect_emit(event, payload, *args, **kwargs):
            event_order.append(event)
            return original_connect_emit(event, payload, *args, **kwargs)

        def record_socket_emit(event, payload, **kwargs):
            emitted.append((event, payload, kwargs))
            event_order.append(event)

        version_path = web_interface.resolve_repository_path(
            "VERSION", root=web_interface.INSTALL_ROOT
        )
        expected_local_version = (
            version_path.read_text(encoding="utf-8").strip()
            if version_path.exists()
            else "0.0.0"
        )

        with mock.patch.object(
            version_checker,
            "resolve_update_target",
            side_effect=delayed_resolve_update_target,
        ), mock.patch.object(
            version_checker,
            "get_latest_remote_version",
            side_effect=delayed_get_latest_remote_version,
        ), mock.patch.object(
            version_checker,
            "compare_versions",
            side_effect=delayed_compare_versions,
        ), mock.patch.object(
            web_interface.socketio,
            "start_background_task",
            side_effect=record_background_task,
        ), mock.patch.object(
            web_interface, "emit", side_effect=record_connect_emit
        ), mock.patch.object(
            web_interface, "load_message_cache", return_value=[]
        ), mock.patch.object(
            web_interface.game_output_queue, "empty", return_value=True
        ), mock.patch.object(
            web_interface.debug_output_queue, "empty", return_value=True
        ), mock.patch.object(
            web_interface.module_progress_queue, "empty", return_value=True
        ):
            client = web_interface.socketio.test_client(web_interface.app)
            try:
                received = client.get_received()
                self.assertEqual([event["name"] for event in received], ["connected"])
                self.assertEqual(
                    received[0]["args"], [{"data": "Connected to NeverEndingQuest"}]
                )

                self.assertEqual(calls, [])
                self.assertEqual(len(background_tasks), 1)
                target, args, kwargs = background_tasks[0]
                self.assertEqual(kwargs, {})
                self.assertEqual(len(args), 1)
                client_sid = args[0]
                self.assertTrue(client_sid)

                with mock.patch.object(
                    web_interface.socketio, "emit", side_effect=record_socket_emit
                ):
                    target(*args, **kwargs)

                self.assertEqual(
                    [call[0] for call in calls],
                    [
                        "resolve_update_target",
                        "get_latest_remote_version",
                        "compare_versions",
                    ],
                )
                self.assertEqual(calls[0][1], str(web_interface.INSTALL_ROOT))
                self.assertEqual(
                    calls[1],
                    (
                        "get_latest_remote_version",
                        update_target["owner_repo"],
                        update_target["branch"],
                        True,
                    ),
                )
                self.assertEqual(
                    calls[2], ("compare_versions", expected_local_version, remote_version)
                )

                self.assertEqual(len(emitted), 1)
                event, payload, emit_kwargs = emitted[0]
                self.assertEqual(event, "version_status")
                self.assertEqual(emit_kwargs, {"to": client_sid})
                self.assertEqual(
                    set(payload),
                    {
                        "update_available",
                        "update_supported",
                        "local_version",
                        "remote_version",
                        "message",
                        "install_hint",
                    },
                )
                self.assertEqual(
                    payload,
                    {
                        "update_available": True,
                        "update_supported": True,
                        "local_version": expected_local_version,
                        "remote_version": remote_version,
                        "message": "Update check complete",
                        "install_hint": (
                            "Git install detected (example-owner/example-repo@stable). "
                            "Use [UPDATE] Fork Update for incremental updates."
                        ),
                    },
                )
                self.assertEqual(
                    event_order, ["connected", "background_task", "version_status"]
                )
            finally:
                client.disconnect()


if __name__ == "__main__":
    unittest.main()
