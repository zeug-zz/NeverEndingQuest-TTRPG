# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Explicit, loopback-only Uvicorn lifecycle for the player ASGI app."""

from __future__ import annotations

import asyncio
from os import PathLike
import threading
import time

import uvicorn

from .app import PlayerApplication, create_app
from .auth import PlayerSecurity
from .constants import PLAYER_HOST, PLAYER_PORT
from .gateway import PlayerGateway
from .limits import MAX_SOCKETIO_EVENT_BYTES

STARTUP_TIMEOUT_SECONDS = 10.0
STOP_JOIN_TIMEOUT_SECONDS = 5.0
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 3


class PlayerListener:
    """Run one Uvicorn server on 127.0.0.1, only when explicitly started.

    ``test_only_port`` is an explicit test seam for binding an ephemeral port.
    Production construction omits it and is fixed to ``PLAYER_PORT``.
    """

    def __init__(
        self,
        gateway: PlayerGateway | None = None,
        *,
        # TABLETOP MODE: The host may inject its profile-bound N1 security authority.
        security: PlayerSecurity | None = None,
        test_only_port: int | None = None,
        build_root: str | PathLike[str] | None = None,
    ) -> None:
        if test_only_port is not None and (
            not isinstance(test_only_port, int)
            or isinstance(test_only_port, bool)
            or not 1 <= test_only_port <= 65535
        ):
            raise ValueError("test_only_port must be an integer between 1 and 65535")

        self._port = PLAYER_PORT if test_only_port is None else test_only_port
        self.app: PlayerApplication = create_app(
            gateway=gateway,
            port=self._port,
            security=security,
            build_root=build_root,
        )
        self._state_lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_error: BaseException | None = None

    @property
    def port(self) -> int:
        """Return the configured listener port."""
        return self._port

    @property
    def is_running(self) -> bool:
        """Return whether the owned Uvicorn thread has completed startup."""
        thread = self._thread
        server = self._server
        return bool(thread is not None and thread.is_alive() and server is not None and server.started)

    def start(self, host: str = PLAYER_HOST, port: int | None = None) -> None:
        """Start the listener and wait until Uvicorn has bound its socket."""
        if host != PLAYER_HOST:
            raise ValueError("player listener host must be exactly 127.0.0.1")

        selected_port = self._port if port is None else port
        if (
            not isinstance(selected_port, int)
            or isinstance(selected_port, bool)
            or selected_port != self._port
        ):
            raise ValueError("player listener port must match its configured port")

        self.app.preflight_client_assets()

        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("player listener is already running")
            self._server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host=PLAYER_HOST,
                    port=self._port,
                    ws="websockets",
                    workers=1,
                    reload=False,
                    ws_max_size=MAX_SOCKETIO_EVENT_BYTES,
                    proxy_headers=False,
                    forwarded_allow_ips="",
                    server_header=False,
                    access_log=False,
                    log_config=None,
                    lifespan="on",
                    timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
                    timeout_keep_alive=1,
                )
            )
            self._thread_error = None
            self._loop = None
            server = self._server
            thread = threading.Thread(
                target=self._serve,
                args=(server,),
                name="player-asgi-uvicorn",
                daemon=True,
            )
            self._thread = thread
            thread.start()

        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if server.started:
                return
            thread.join(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if not thread.is_alive():
                break

        if server.started:
            return

        if thread.is_alive():
            self._request_exit(server)
            thread.join(timeout=STOP_JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            raise TimeoutError("player listener did not finish startup or stop in time")

        failure = self._thread_error
        self._clear_state(thread)
        if failure is not None:
            raise RuntimeError("player listener failed during startup") from failure
        raise TimeoutError("player listener did not start before the startup deadline")

    def stop(self) -> None:
        """Stop the owned server, join its thread, and release the bound port.

        Calling stop repeatedly, including before start, is safe.
        """
        with self._state_lock:
            thread = self._thread
            server = self._server
            loop = self._loop
            if thread is None:
                return
            if thread.is_alive() and server is not None:
                self._request_exit(server, loop)

        thread.join(timeout=STOP_JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            raise TimeoutError("player listener did not stop within the join timeout")

        failure = self._thread_error
        self._clear_state(thread)
        if failure is not None:
            raise RuntimeError("player listener exited with an error") from failure

    def _serve(self, server: uvicorn.Server) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(server.serve())
        except (Exception, SystemExit) as exc:
            self._thread_error = exc
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as exc:
                if self._thread_error is None:
                    self._thread_error = exc
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    def _request_exit(
        self,
        server: uvicorn.Server,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        selected_loop = loop if loop is not None else self._loop
        if selected_loop is not None and selected_loop.is_running():
            selected_loop.call_soon_threadsafe(setattr, server, "should_exit", True)
        else:
            server.should_exit = True

    def _clear_state(self, thread: threading.Thread) -> None:
        with self._state_lock:
            if self._thread is thread:
                self._thread = None
                self._server = None
                self._loop = None
                self._thread_error = None
