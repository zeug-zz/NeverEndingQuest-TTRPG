# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Standalone inert N0 network fixture.

Architecture: a loopback-only Uvicorn process serves a small hand-written HTTP
ASGI fallback and a separate python-socketio AsyncServer ASGI application.
Host/Origin validation wraps both applications so it also covers polling and
WebSocket handshakes. This fixture has no game-runtime imports or state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qs

import socketio
import uvicorn

if __package__:
    from . import fixture_auth
else:
    import fixture_auth


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8370
SESSION_COOKIE_NAME = "n0_session"
SESSION_TTL_SECONDS = 900
MAX_LOGIN_BODY_BYTES = 4096
MAX_ECHO_BYTES = 1024
NAMESPACE = "/n0"
SOCKETIO_PATH = "/socket.io"
STATIC_ROOT = Path(__file__).resolve().parent / "static"
_LOGGER = logging.getLogger("network_spike.fixture")
_GENERIC_HOST_ERROR = b"misdirected request"
_GENERIC_ORIGIN_ERROR = b"forbidden origin"
_GENERIC_NOT_FOUND = b"not found"


def _validate_public_host(public_host: Optional[str]) -> Optional[str]:
    """Validate a configured public authority without accepting a URL/path."""
    if public_host is None:
        return None
    if (
        not isinstance(public_host, str)
        or not public_host
        or not fixture_auth.validate_host(public_host, (public_host,))
    ):
        raise ValueError("public host must be a hostname with an optional port")
    origin = "https://" + public_host
    if not fixture_auth.validate_origin(origin, (origin,), require=True):
        raise ValueError("public host must be a hostname with an optional port")
    return public_host


def _header_identity(
    headers: Iterable[Tuple[Union[bytes, str], Union[bytes, str]]],
) -> Tuple[Optional[str], Optional[str]]:
    """Extract only raw Host and Origin headers, rejecting duplicate identity."""
    selected: Dict[Union[bytes, str], Union[bytes, str]] = {}
    seen = set()
    for name, value in headers:
        normalized = (
            name.decode("latin-1").casefold()
            if isinstance(name, bytes)
            else name.casefold()
            if isinstance(name, str)
            else ""
        )
        if normalized not in ("host", "origin"):
            continue
        if normalized in seen:
            raise ValueError("duplicate identity header")
        seen.add(normalized)
        selected[name] = value
    return fixture_auth.extract_host_origin(selected)


def _header_values(scope: Mapping[str, Any], wanted: bytes) -> List[bytes]:
    values = []
    for name, value in scope.get("headers", ()):
        if isinstance(name, bytes) and name.lower() == wanted:
            values.append(value if isinstance(value, bytes) else str(value).encode("latin-1"))
    return values


def _is_socketio_path(path: str) -> bool:
    return path == SOCKETIO_PATH or path.startswith(SOCKETIO_PATH + "/")


async def _send_http_response(
    send: Any,
    status: int,
    body: bytes,
    content_type: bytes = b"text/plain; charset=utf-8",
    headers: Sequence[Tuple[bytes, bytes]] = (),
) -> None:
    response_headers = [
        (b"content-type", content_type),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
    ]
    response_headers.extend(headers)
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


def _path_for_log(path: str) -> str:
    """Return the path without query data or terminal-control characters."""
    return path.replace("\r", "%0D").replace("\n", "%0A")[:2048]


class _HostValidatedASGI:
    """Validate request identity before forwarding to Socket.IO or HTTP routes."""

    def __init__(
        self,
        app: Any,
        port: int,
        public_host: Optional[str],
        allowed_hosts: Sequence[str],
        allowed_origins: Sequence[str],
    ) -> None:
        self.app = app
        self.port = port
        self.public_host = public_host
        self.allowed_hosts = tuple(allowed_hosts)
        self.allowed_origins = tuple(allowed_origins)
        self.local_host = f"{LOOPBACK_HOST}:{port}"

    async def _reject(self, scope: Mapping[str, Any], send: Any, status: int, body: bytes) -> None:
        if scope["type"] == "http":
            await _send_http_response(send, status, body)
            return

        extensions = scope.get("extensions", {})
        if "websocket.http.response" in extensions:
            headers = [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ]
            await send({
                "type": "websocket.http.response.start",
                "status": status,
                "headers": headers,
            })
            await send({"type": "websocket.http.response.body", "body": body})
            return
        await send({"type": "websocket.close", "code": 1008})

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))
        host: Optional[str] = None
        origin: Optional[str] = None
        status: Optional[int] = None
        try:
            host, origin = _header_identity(scope.get("headers", ()))
        except (TypeError, ValueError):
            status = 421
            await self._reject(scope, send, status, _GENERIC_HOST_ERROR)

        if status is None and not fixture_auth.validate_host(host, self.allowed_hosts):
            status = 421
            await self._reject(scope, send, status, _GENERIC_HOST_ERROR)

        check_origin = (
            (scope_type == "websocket" and _is_socketio_path(path))
            or (scope_type == "http" and _is_socketio_path(path))
            or (scope_type == "http" and method == "POST" and path in ("/login", "/logout"))
        )
        if (
            status is None
            and check_origin
            and not fixture_auth.validate_origin(origin, self.allowed_origins, require=False)
        ):
            status = 403
            await self._reject(scope, send, status, _GENERIC_ORIGIN_ERROR)

        if status is None:
            status = 101 if scope_type == "websocket" else 500

            async def tracked_send(message: Mapping[str, Any]) -> None:
                nonlocal status
                message_type = message.get("type")
                if message_type == "http.response.start":
                    status = int(message.get("status", 500))
                elif message_type == "websocket.http.response.start":
                    status = int(message.get("status", 500))
                elif message_type == "websocket.close" and status == 101:
                    status = 403
                await send(message)

            try:
                await self.app(scope, receive, tracked_send)
            except Exception:
                _LOGGER.exception("fixture request handler failed")
                status = 500
                if scope_type == "http":
                    await _send_http_response(send, status, b"internal error")
                else:
                    await send({"type": "websocket.close", "code": 1011})

        if host is not None and self.public_host is not None and host.casefold() == self.public_host.casefold():
            host_label = "<public>"
        elif host is not None and host.casefold() == self.local_host.casefold():
            host_label = "<loopback>"
        else:
            host_label = "<rejected>"
        _LOGGER.info(
            "request method=%s path=%s status=%d host=%s",
            method,
            _path_for_log(path),
            status if status is not None else 500,
            host_label,
        )


class _HTTPFallback:
    """Small hand-written ASGI implementation for the fixture HTTP routes."""

    def __init__(self, service: "_FixtureService") -> None:
        self.service = service
        self.static_root = STATIC_ROOT.resolve()

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))

        if method == "GET" and path == "/healthz":
            await _send_http_response(send, 200, b"ok")
            return

        if method == "POST" and path == "/login":
            body, too_large = await self._read_body(scope, receive)
            if too_large:
                await _send_http_response(send, 413, b"request too large")
                return
            supplied = self._parse_password(scope, body or b"")
            if not fixture_auth.check_password(supplied, self.service.password):
                await _send_http_response(send, 401, b"unauthorized")
                return
            cookie = fixture_auth.build_session_cookie(
                SESSION_COOKIE_NAME,
                self.service.signer.issue(),
                SESSION_TTL_SECONDS,
            )
            await _send_http_response(
                send,
                200,
                b'{"ok":true}',
                b"application/json; charset=utf-8",
                ((b"set-cookie", cookie.encode("ascii")),),
            )
            return

        if method == "POST" and path == "/logout":
            cookie = fixture_auth.clear_session_cookie(SESSION_COOKIE_NAME)
            await _send_http_response(
                send,
                204,
                b"",
                headers=((b"set-cookie", cookie.encode("ascii")),),
            )
            return

        if method in ("GET", "HEAD") and (path == "/" or path.startswith("/static/")):
            await self._serve_static(path, method == "HEAD", send)
            return

        if path in ("/healthz", "/login", "/logout") or path == "/" or path.startswith("/static/"):
            await _send_http_response(
                send,
                405,
                b"method not allowed",
                headers=((b"allow", b"GET, HEAD, POST"),),
            )
            return

        await _send_http_response(send, 404, _GENERIC_NOT_FOUND)

    async def _read_body(self, scope: Mapping[str, Any], receive: Any) -> Tuple[Optional[bytes], bool]:
        lengths = _header_values(scope, b"content-length")
        if len(lengths) > 1:
            return None, True
        if lengths:
            try:
                declared_length = int(lengths[0].decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                return None, True
            if declared_length < 0 or declared_length > MAX_LOGIN_BODY_BYTES:
                return None, True

        chunks = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return None, False
            if message.get("type") != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_LOGIN_BODY_BYTES:
                return None, True
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks), False

    @staticmethod
    def _parse_password(scope: Mapping[str, Any], body: bytes) -> Optional[str]:
        content_types = _header_values(scope, b"content-type")
        if len(content_types) != 1:
            return None
        content_type = content_types[0].decode("latin-1").split(";", 1)[0].strip().casefold()
        try:
            text = body.decode("utf-8")
            if content_type == "application/x-www-form-urlencoded":
                values = parse_qs(text, keep_blank_values=True).get("password", [])
                return values[0] if len(values) == 1 else None
            if content_type == "application/json":
                value = json.loads(text)
                if isinstance(value, dict) and isinstance(value.get("password"), str):
                    return value["password"]
        except (UnicodeDecodeError, ValueError, TypeError):
            return None
        return None

    async def _serve_static(self, path: str, head_only: bool, send: Any) -> None:
        if path == "/":
            relative_path = "index.html"
        else:
            relative_path = path[len("/static/"):]
        try:
            candidate = (self.static_root / relative_path).resolve(strict=True)
            candidate.relative_to(self.static_root)
            if not candidate.is_file():
                raise FileNotFoundError
            body = candidate.read_bytes()
        except (OSError, RuntimeError, ValueError):
            await _send_http_response(send, 404, _GENERIC_NOT_FOUND)
            return

        content_type, _encoding = mimetypes.guess_type(candidate.name)
        media_type = (content_type or "application/octet-stream").encode("ascii")
        headers = [
            (b"content-type", media_type),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
        ]
        if candidate.name == "index.html":
            headers.append((
                b"content-security-policy",
                b"default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            ))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if head_only else body})


class _FixtureService:
    """Own the fixture's isolated Socket.IO server and shutdown lifecycle."""

    def __init__(self, password: str, public_host: Optional[str], port: int) -> None:
        fixture_auth.ensure_loopback_bind(LOOPBACK_HOST)
        if not isinstance(password, str) or not password:
            raise ValueError("fixture password must not be empty")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")

        self.password = password
        self.public_host = _validate_public_host(public_host)
        self.port = port
        self.signer = fixture_auth.SessionSigner(SESSION_TTL_SECONDS)
        self.counter = 0
        self.transports: Dict[str, str] = {}
        self._tick_task: Any = None
        self._hello_tasks: set = set()

        local_host = f"{LOOPBACK_HOST}:{port}"
        allowed_hosts = [local_host]
        allowed_origins = [f"http://{local_host}"]
        if self.public_host is not None:
            allowed_hosts.append(self.public_host)
            allowed_origins.append(f"https://{self.public_host}")

        self.socket_server = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=allowed_origins,
            cors_credentials=True,
            max_http_buffer_size=MAX_LOGIN_BODY_BYTES,
            logger=False,
            engineio_logger=False,
        )
        self.socket_server.on("connect", self._connect_n0, namespace=NAMESPACE)
        self.socket_server.on("disconnect", self._disconnect_n0, namespace=NAMESPACE)
        self.socket_server.on("echo", self._echo, namespace=NAMESPACE)
        self.socket_server.on("connect", self._reject_default_namespace, namespace="/")

        self.http_app = _HTTPFallback(self)
        socketio_app = socketio.ASGIApp(
            self.socket_server,
            other_asgi_app=self.http_app,
            on_startup=self.startup,
            on_shutdown=self.shutdown,
        )
        self.app = _HostValidatedASGI(
            socketio_app,
            port,
            self.public_host,
            allowed_hosts,
            allowed_origins,
        )

    async def startup(self) -> None:
        """Start the counter task when Uvicorn sends ASGI lifespan startup."""
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = self.socket_server.start_background_task(self._tick)

    async def shutdown(self) -> None:
        """Cancel and await all fixture background tasks during shutdown."""
        tasks = list(self._hello_tasks)
        if self._tick_task is not None:
            tasks.append(self._tick_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._hello_tasks.clear()
        self._tick_task = None

    async def _tick(self) -> None:
        while True:
            await self.socket_server.sleep(1)
            self.counter += 1
            await self.socket_server.emit("tick", {"n": self.counter}, namespace=NAMESPACE)

    async def _connect_n0(
        self,
        sid: str,
        environ: Mapping[str, Any],
        auth: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        if not self.signer.verify(self._session_token(environ)):
            raise socketio.exceptions.ConnectionRefusedError("unauthorized")

        scope = environ.get("asgi.scope")
        scope_type = scope.get("type") if isinstance(scope, Mapping) else None
        transport = "websocket" if scope_type == "websocket" else "polling" if scope_type == "http" else "unknown"
        self.transports[sid] = transport
        task = self.socket_server.start_background_task(self._emit_hello, sid, transport)
        self._hello_tasks.add(task)
        task.add_done_callback(self._hello_tasks.discard)
        return True

    async def _emit_hello(self, sid: str, transport: str) -> None:
        for _attempt in range(100):
            if self.socket_server.manager.is_connected(sid, NAMESPACE):
                await self.socket_server.emit(
                    "hello",
                    {"transport": transport, "sid": sid},
                    to=sid,
                    namespace=NAMESPACE,
                )
                return
            await self.socket_server.sleep(0.01)

    async def _disconnect_n0(self, sid: str, reason: Optional[str] = None) -> None:
        self.transports.pop(sid, None)

    async def _echo(self, sid: str, payload: Any = None) -> Any:
        try:
            encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            return {"error": "invalid_payload"}
        if len(encoded) > MAX_ECHO_BYTES:
            return {"error": "payload_too_large"}
        return payload

    async def _reject_default_namespace(
        self,
        sid: str,
        environ: Mapping[str, Any],
        auth: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        raise socketio.exceptions.ConnectionRefusedError("unauthorized")

    @staticmethod
    def _session_token(environ: Mapping[str, Any]) -> Optional[str]:
        value = environ.get("HTTP_COOKIE")
        if isinstance(value, bytes):
            cookie_headers = [value.decode("latin-1")]
        elif isinstance(value, str):
            cookie_headers = [value]
        else:
            scope = environ.get("asgi.scope")
            headers = scope.get("headers", ()) if isinstance(scope, Mapping) else ()
            cookie_headers = [
                item.decode("latin-1") if isinstance(item, bytes) else str(item)
                for name, item in headers
                if (name.decode("latin-1") if isinstance(name, bytes) else str(name)).casefold() == "cookie"
            ]

        found: Optional[str] = None
        seen = False
        for cookie_header in cookie_headers:
            for item in cookie_header.split(";"):
                name, separator, cookie_value = item.strip().partition("=")
                if separator and name == SESSION_COOKIE_NAME:
                    if seen:
                        return None
                    seen = True
                    found = cookie_value.strip()
        return found if seen and found else None


def create_app(password: str, public_host: Optional[str], port: int) -> _HostValidatedASGI:
    """Create the isolated ASGI fixture application for in-process use."""
    return _FixtureService(password, public_host, port).app


def _read_password(args: argparse.Namespace) -> Optional[str]:
    if args.password_file is not None:
        try:
            return Path(args.password_file).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError):
            _LOGGER.error("fixture password file could not be read")
            return None
    return os.environ.get("N0_FIXTURE_PASSWORD")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the fixture using Uvicorn's SIGINT/SIGTERM-aware server loop."""
    parser = argparse.ArgumentParser(description="Run the inert N0 network fixture")
    parser.add_argument("--host", default=LOOPBACK_HOST, help="must be exactly 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="local test port (default: 8370)")
    parser.add_argument("--password-file", help="read the fixture password from this file")
    parser.add_argument("--public-host", help="expected public HTTPS Host authority, without a scheme")
    args = parser.parse_args(argv)

    try:
        fixture_auth.ensure_loopback_bind(args.host)
    except ValueError:
        print("fixture bind host must be exactly 127.0.0.1", file=sys.stderr)
        return 2

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    password = _read_password(args)
    if not password:
        _LOGGER.error("set N0_FIXTURE_PASSWORD or provide a non-empty --password-file")
        return 2

    try:
        app = create_app(password, args.public_host, args.port)
    except ValueError as exc:
        _LOGGER.error("invalid fixture configuration: %s", exc)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Trust boundary: OpenTunnel forwards visitor-supplied headers unchanged
    # (openspec/changes/v2-network-transport-feasibility/design.md D1), so
    # Uvicorn must not reinterpret them as proxy metadata.
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=args.port,
        access_log=False,
        log_config=None,
        proxy_headers=False,
        forwarded_allow_ips="",
        server_header=False,
        timeout_graceful_shutdown=3,
        timeout_keep_alive=1,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
