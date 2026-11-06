# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Isolated player ASGI/Socket.IO application with no host-app imports."""

from __future__ import annotations

import asyncio
import json
import re
from os import PathLike
from typing import Any, Awaitable, Callable, Iterable, Mapping
from urllib.parse import parse_qs

import socketio

from .capabilities import (
    PLAYER_HTTP_ALLOWLIST,
    PLAYER_SOCKET_EVENT_ALLOWLIST,
    PLAYER_SOCKET_LIFECYCLE_EVENTS,
)
from .assets import (
    PRELOGIN_CSRF_PLACEHOLDER,
    PlayerClientAssetsError,
    VerifiedPlayerClientAssets,
    load_player_client_assets,
)
from .auth import (
    PLAYER_SESSION_COOKIE,
    PRELOGIN_CSRF_COOKIE,
    PRELOGIN_CSRF_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    PlayerSessionIdentity,
    PlayerSecurity,
    build_cookie,
    cookie_value,
    extract_host_origin,
    header_values,
)
from .constants import PLAYER_NAMESPACE, PLAYER_PORT
from .gateway import PlayerGateway, UnavailablePlayerGateway
from .active_pc import PlayerActivePCSelection, select_player_active_pc
from .media import MediaRegistry
from .limiters import PlayerLimiters
from .limits import (
    MAX_HTTP_BODY_BYTES,
    MAX_REPLAY_BYTES,
    MAX_SNAPSHOT_BYTES,
    MAX_SOCKETIO_EVENT_BYTES,
)
from .projections import (
    ProjectionError,
)
from .contracts import (
    EnvelopeTooLargeError,
    EnvelopeValidationError,
    PROTOCOL_VERSION,
    canonical_json_bytes,
    make_error_envelope,
    validate_active_pc_selection_envelope,
    validate_snapshot_request_envelope,
)
from .sync import PlayerSyncCoordinator

CLIENT_BUILD_HEADER = "x-neq-client-build"
PROTOCOL_VERSION_HEADER = "x-neq-protocol-version"
_CLIENT_BUILD_ID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")
_CLIENT_PROTOCOL_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]{0,8})\Z")
_SOCKET_CONNECT_AUTH_FIELDS = frozenset({"client_build_id", "protocol_version"})

_PLAYER_CONTENT_SECURITY_POLICY = (
    b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    b"font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    b"frame-ancestors 'none'; object-src 'none'"
)

class PlayerHTTPRouter:
    """Serve the unauthenticated shell and the two authentication mutations."""

    def __init__(
        self,
        security: PlayerSecurity,
        disconnect_sockets: Callable[[Iterable[str]], Awaitable[None]],
        gateway: PlayerGateway,
        media_registry: MediaRegistry,
        sync: PlayerSyncCoordinator,
        get_client_assets: Callable[[], VerifiedPlayerClientAssets],
    ) -> None:
        self.security = security
        self._disconnect_sockets = disconnect_sockets
        self._gateway = gateway
        self._media_registry = media_registry
        self._sync = sync
        self._get_client_assets = get_client_assets
        self._route_handlers = {
            ("GET", "/"): "login_shell",
            ("GET", "/static/player/<asset-id>"): "public_asset",
            ("POST", "/api/player/login"): "login",
            ("POST", "/api/player/logout"): "logout",
            ("GET", "/api/player/snapshot"): "snapshot",
            ("GET", "/api/player/media/<media-id>"): "media",
        }
        if frozenset(self._route_handlers) != PLAYER_HTTP_ALLOWLIST:
            raise RuntimeError("player HTTP registrations do not match the allowlist")

    async def __call__(
        self,
        scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[Mapping[str, Any]]],
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        method = scope.get("method")
        path = scope.get("path")
        route_handler, route_parameter = self._match_route(
            method,
            path,
            scope.get("raw_path"),
        )
        is_mutation = route_handler in ("login", "logout")
        try:
            host, origin, unique_identity = extract_host_origin(scope.get("headers", ()))
        except TypeError:
            host, origin, unique_identity = None, None, False
        if not unique_identity or not self.security.request_identity_is_valid(
            host,
            origin,
            require_origin=is_mutation,
        ):
            await _send_json(send, 403, {"error": "request_rejected"})
            return

        if route_handler is None:
            await _send_json(send, 404, {"error": "not_found"})
            return

        session_id: str | None = None
        session_identity: PlayerSessionIdentity | None = None
        if route_handler in ("snapshot", "media"):
            session_cookie = cookie_value(scope.get("headers", ()), PLAYER_SESSION_COOKIE)
            if route_handler == "snapshot":
                session_identity = self.security.session_context_for_cookie(session_cookie)
                session_id = (
                    None if session_identity is None else session_identity.session_id
                )
            else:
                session_id = self.security.session_id_for_cookie(session_cookie)
            if session_id is None:
                await _send_json(send, 404, {"error": "not_found"})
                return
            if route_handler == "snapshot":
                read_allowed = self.security.limiters.allow_snapshot_read(session_id)
            else:
                read_allowed = self.security.limiters.allow_media_read(session_id)
            if not read_allowed:
                await _send_json(send, 429, {"error": "rate_limited"})
                return
            if route_handler == "snapshot":
                client_version = _parse_http_client_version(scope.get("headers", ()))
                if client_version is None or client_version[1] != PROTOCOL_VERSION:
                    await _send_json(
                        send,
                        409,
                        {"error": "client_version_mismatch"},
                    )
                    return
                try:
                    client_assets = self._get_client_assets()
                except PlayerClientAssetsError:
                    await _send_json(send, 503, {"error": "client_assets_unavailable"})
                    return
                if (
                    client_version[0] != client_assets.client_build_id
                    or client_version[1] != client_assets.protocol_version
                ):
                    await _send_json(
                        send,
                        409,
                        {"error": "client_version_mismatch"},
                    )
                    return

        if route_handler == "login":
            if not self.security.allow_login_attempt():
                await _send_json(send, 429, {"error": "rate_limited"})
                return

        body, body_status = await _read_bounded_body(scope, receive)
        if body_status is not None:
            await _send_json(send, body_status, {"error": "invalid_request"})
            return
        if body is None:
            await _send_json(send, 400, {"error": "invalid_request"})
            return

        if route_handler == "login_shell":
            await self._serve_login_shell(send)
            return
        if route_handler == "public_asset":
            await self._serve_public_asset(route_parameter, send)
            return
        if route_handler == "login":
            await self._login(scope, body, send)
            return
        if route_handler == "logout":
            await self._logout(scope, body, send)
            return
        if route_handler == "snapshot":
            if session_identity is None:
                await _send_json(send, 404, {"error": "not_found"})
                return
            await self._serve_snapshot(scope, session_identity, send)
            return
        if route_handler == "media":
            await self._serve_media(route_parameter, send)
            return
        await _send_json(send, 404, {"error": "not_found"})

    def _match_route(
        self,
        method: object,
        path: object,
        raw_path: object = None,
    ) -> tuple[str | None, str | None]:
        if not isinstance(method, str) or not isinstance(path, str):
            return None, None
        exact_handler = self._route_handlers.get((method, path))
        if exact_handler is not None:
            return exact_handler, None
        asset_prefix = "/static/player/"
        if method == "GET" and path.startswith(asset_prefix):
            if raw_path is not None:
                try:
                    expected_raw_path = path.encode("ascii")
                except UnicodeEncodeError:
                    return None, None
                if not isinstance(raw_path, bytes) or raw_path != expected_raw_path:
                    return None, None
            identifier = path[len(asset_prefix):]
            if not identifier or len(identifier) > 128 or "/" in identifier:
                return None, None
            return self._route_handlers[("GET", "/static/player/<asset-id>")], identifier
        for prefix, template in (
            ("/api/player/media/", ("GET", "/api/player/media/<media-id>")),
        ):
            if method != template[0] or not path.startswith(prefix):
                continue
            identifier = path[len(prefix):]
            if identifier and "/" not in identifier:
                handler = self._route_handlers.get(template)
                if handler is not None:
                    return handler, identifier
        return None, None

    @property
    def registered_routes(self) -> frozenset[tuple[str, str]]:
        """Return routes used by the actual HTTP dispatch table."""
        return frozenset(self._route_handlers)

    async def _serve_login_shell(self, send: Callable[[Mapping[str, Any]], Awaitable[None]]) -> None:
        try:
            assets = self._get_client_assets()
        except PlayerClientAssetsError:
            await _send_json(send, 503, {"error": "client_assets_unavailable"})
            return
        challenge = self.security.issue_prelogin_challenge()
        if challenge is None:
            await _send_json(send, 503, {"error": "temporarily_unavailable"})
            return
        body = assets.shell_document.replace(
            PRELOGIN_CSRF_PLACEHOLDER,
            challenge.csrf_nonce.encode("ascii"),
        )
        headers = _base_headers(assets.shell_content_type, len(body))
        headers.extend(
            [
                (
                    b"content-security-policy",
                    _PLAYER_CONTENT_SECURITY_POLICY,
                ),
                (b"cross-origin-resource-policy", b"same-origin"),
                (
                    b"set-cookie",
                    build_cookie(
                        PRELOGIN_CSRF_COOKIE,
                        challenge.cookie_value,
                        PRELOGIN_CSRF_TTL_SECONDS,
                    ).encode("ascii"),
                ),
            ]
        )
        await _send_response(send, 200, body, headers)

    async def _serve_public_asset(
        self,
        asset_id: str | None,
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        try:
            assets = self._get_client_assets()
        except PlayerClientAssetsError:
            await _send_json(send, 503, {"error": "client_assets_unavailable"})
            return
        asset = assets.assets.get(asset_id or "")
        if asset is None:
            await _send_json(send, 404, {"error": "not_found"})
            return
        headers = _base_headers(
            asset.content_type,
            len(asset.body),
            cache_control=b"public, max-age=31536000, immutable",
        )
        headers.extend(
            [
                (b"content-security-policy", _PLAYER_CONTENT_SECURITY_POLICY),
                (b"cross-origin-resource-policy", b"same-origin"),
            ]
        )
        await _send_response(send, 200, asset.body, headers)

    async def _serve_snapshot(
        self,
        scope: Mapping[str, Any],
        session_identity: PlayerSessionIdentity,
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        try:
            self._sync.reset_for_instance(session_identity.instance_id)
            reconnect_request, query_status = _parse_reconnect_query(
                scope.get("query_string", b"")
            )
            if query_status is not None:
                await _send_json(send, query_status, {"error": "invalid_request"})
                return
            if reconnect_request is None:
                response = await asyncio.to_thread(
                    _capture_player_snapshot,
                    self._sync,
                    self._gateway,
                    session_identity.session_epoch,
                )
            else:
                response = await asyncio.to_thread(
                    self._sync.reconnect,
                    reconnect_request.get("instance_id"),
                    reconnect_request.get("session_epoch"),
                    reconnect_request.get("cursor"),
                    session_identity.session_epoch,
                    self._gateway.read_snapshot,
                )
            if response.get("kind") == "replay":
                body = canonical_json_bytes(response, MAX_REPLAY_BYTES)
            else:
                body = canonical_json_bytes(response, MAX_SNAPSHOT_BYTES)
        except EnvelopeTooLargeError:
            await _send_json(send, 413, {"error": "snapshot_too_large"})
            return
        except (
            AttributeError,
            EnvelopeValidationError,
            OSError,
            ProjectionError,
            RuntimeError,
            TypeError,
            ValueError,
            RecursionError,
        ):
            await _send_json(send, 503, {"error": "snapshot_unavailable"})
            return
        await _send_response(
            send,
            200,
            body,
            _base_headers(b"application/json; charset=utf-8", len(body)),
        )

    async def _serve_media(
        self,
        media_id: str | None,
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        media = self._media_registry.read(media_id)
        if media is None:
            await _send_json(send, 404, {"error": "media_not_found"})
            return
        headers = _base_headers(media.content_type.encode("ascii"), len(media.body))
        headers.extend(
            [
                (b"content-disposition", b"inline"),
                (b"content-security-policy", b"default-src 'none'; sandbox"),
                (b"cross-origin-resource-policy", b"same-origin"),
            ]
        )
        await _send_response(send, 200, media.body, headers)

    async def _login(
        self,
        scope: Mapping[str, Any],
        body: bytes,
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        fields = _parse_login_fields(body, scope.get("headers", ()))
        if fields is None:
            await _send_json(send, 400, {"error": "invalid_request"})
            return
        password, csrf_nonce = fields
        if not self.security.consume_prelogin_challenge(
            cookie_value(scope.get("headers", ()), PRELOGIN_CSRF_COOKIE),
            csrf_nonce,
        ):
            await _send_json(send, 403, {"error": "csrf_rejected"})
            return
        limiters: PlayerLimiters = self.security.limiters
        if password is not None and not limiters.password_allowed(password):
            await _send_json(send, 400, {"error": "invalid_credentials"})
            return
        if not await asyncio.to_thread(self.security.verify_password, password):
            await _send_json(send, 401, {"error": "invalid_credentials"})
            return
        grant = self.security.create_session()
        if grant is None:
            await _send_json(send, 503, {"error": "capacity_reached"})
            return
        response_body = json.dumps(
            {"csrf_token": grant.csrf_token, "expires_at": grant.expires_at},
            separators=(",", ":"),
        ).encode("ascii")
        headers = _base_headers(b"application/json; charset=utf-8", len(response_body))
        headers.extend(
            [
                (
                    b"set-cookie",
                    build_cookie(
                        PLAYER_SESSION_COOKIE,
                        grant.cookie_value,
                        SESSION_TTL_SECONDS,
                    ).encode("ascii"),
                ),
                (
                    b"set-cookie",
                    build_cookie(PRELOGIN_CSRF_COOKIE, "", 0).encode("ascii"),
                ),
            ]
        )
        await _send_response(send, 200, response_body, headers)

    async def _logout(
        self,
        scope: Mapping[str, Any],
        body: bytes,
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        csrf_token = _parse_csrf_token(body, scope.get("headers", ()))
        if csrf_token is None:
            await _send_json(send, 400, {"error": "invalid_request"})
            return
        session_cookie = cookie_value(scope.get("headers", ()), PLAYER_SESSION_COOKIE)
        socket_ids = self.security.revoke_session(session_cookie, csrf_token)
        if socket_ids is None:
            await _send_json(send, 403, {"error": "csrf_rejected"})
            return
        await self._disconnect_sockets(socket_ids)
        headers = _base_headers(b"application/json; charset=utf-8", 0)
        headers.append(
            (
                b"set-cookie",
                build_cookie(PLAYER_SESSION_COOKIE, "", 0).encode("ascii"),
            )
        )
        await _send_response(send, 204, b"", headers)


class PlayerApplication:
    """Own the player-only Socket.IO server and its minimal HTTP router."""

    def __init__(
        self,
        gateway: PlayerGateway | None = None,
        *,
        port: int = PLAYER_PORT,
        security: PlayerSecurity | None = None,
        media_registry: MediaRegistry | None = None,
        build_root: str | PathLike[str] | None = None,
    ) -> None:
        self.gateway = gateway if gateway is not None else UnavailablePlayerGateway()
        self.security = security if security is not None else PlayerSecurity(port=port)
        self.media_registry = media_registry if media_registry is not None else MediaRegistry()
        self._build_root = build_root
        self._client_assets: VerifiedPlayerClientAssets | None = None
        self.sync = PlayerSyncCoordinator(self.security.server_instance_id)
        self.socket_server = socketio.AsyncServer(
            async_mode="asgi",
            namespaces=[PLAYER_NAMESPACE],
            cors_allowed_origins=[],
            max_http_buffer_size=MAX_SOCKETIO_EVENT_BYTES,
            logger=False,
            engineio_logger=False,
        )
        self._socket_event_handlers: dict[str, Callable[..., Any]] = {
            "player.snapshot.request": self._handle_player_snapshot_request,
            "player.active_pc.select": self._handle_player_active_pc_select,
            "player.input.submit": self._handle_player_input,
        }
        if frozenset(self._socket_event_handlers) != PLAYER_SOCKET_EVENT_ALLOWLIST:
            raise RuntimeError("player Socket.IO registrations do not match the allowlist")
        for event_name, handler in self._socket_event_handlers.items():
            self.socket_server.on(event_name, handler, namespace=PLAYER_NAMESPACE)
        self.socket_server.on("connect", self._accept_player_connect, namespace=PLAYER_NAMESPACE)
        self.socket_server.on("disconnect", self._handle_disconnect, namespace=PLAYER_NAMESPACE)
        self.http_router = PlayerHTTPRouter(
            self.security,
            self._disconnect_sockets,
            self.gateway,
            self.media_registry,
            self.sync,
            self.preflight_client_assets,
        )
        self.asgi_app = socketio.ASGIApp(
            self.socket_server,
            other_asgi_app=self.http_router,
            on_startup=self._startup,
            on_shutdown=self._shutdown,
        )

    @property
    def registered_socket_events(self) -> frozenset[str]:
        """Return app-level handlers, excluding Socket.IO lifecycle callbacks."""
        namespace_handlers = self.socket_server.handlers.get(PLAYER_NAMESPACE, {})
        return frozenset(namespace_handlers) - PLAYER_SOCKET_LIFECYCLE_EVENTS

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        scope_type = scope.get("type")
        is_socketio_path = _is_socketio_path(scope.get("path"))
        if scope_type in ("http", "websocket") and is_socketio_path:
            try:
                host, origin, unique_identity = extract_host_origin(scope.get("headers", ()))
            except TypeError:
                host, origin, unique_identity = None, None, False
            is_initial_handshake = _is_initial_socketio_handshake(scope)
            requires_origin = scope_type == "websocket" or is_initial_handshake is True
            if not unique_identity or not self.security.request_identity_is_valid(
                host,
                origin,
                require_origin=requires_origin,
            ):
                if scope_type == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await _send_json(send, 403, {"error": "request_rejected"})
                return
            if is_initial_handshake is None:
                if scope_type == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await _send_json(send, 400, {"error": "invalid_request"})
                return
            if scope_type == "websocket" or is_initial_handshake:
                session_cookie = cookie_value(scope.get("headers", ()), PLAYER_SESSION_COOKIE)
                if self.security.session_id_for_cookie(session_cookie) is None:
                    if scope_type == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                    else:
                        await _send_json(send, 401, {"error": "authentication_required"})
                    return
        await self.asgi_app(scope, receive, send)

    async def _accept_player_connect(
        self,
        sid: str,
        environ: Mapping[str, Any],
        auth: object = None,
    ) -> bool:
        """Authenticate and version-check before registering the player socket."""
        asgi_scope = environ.get("asgi.scope")
        if not isinstance(asgi_scope, Mapping):
            return False
        headers = asgi_scope.get("headers", ())
        try:
            host, origin, unique_identity = extract_host_origin(headers)
        except TypeError:
            return False
        if not unique_identity or not self.security.request_identity_is_valid(
            host,
            origin,
            require_origin=True,
        ):
            return False

        session_cookie = cookie_value(headers, PLAYER_SESSION_COOKIE)
        if self.security.session_id_for_cookie(session_cookie) is None:
            return False

        client_version = _parse_socket_client_version(auth)
        if client_version is None or client_version[1] != PROTOCOL_VERSION:
            raise socketio.exceptions.ConnectionRefusedError("client_version_mismatch")
        try:
            client_assets = self.preflight_client_assets()
        except PlayerClientAssetsError:
            return False
        if (
            client_version[0] != client_assets.client_build_id
            or client_version[1] != client_assets.protocol_version
        ):
            raise socketio.exceptions.ConnectionRefusedError("client_version_mismatch")

        return self.security.register_socket(
            sid,
            session_cookie,
            host,
            origin,
        )

    async def _handle_disconnect(self, sid: str, reason: str | None = None) -> None:
        del reason
        self.security.unregister_socket(sid)

    async def _handle_player_snapshot_request(self, sid: str, payload: object) -> None:
        """Return a canonical snapshot only to this authenticated socket."""
        identity = self._authorized_socket_identity(sid)
        if identity is None:
            return
        if not self.security.limiters.event_payload_allowed(payload):
            await self._emit_player_error(sid, "invalid_command")
            return
        try:
            request = validate_snapshot_request_envelope(payload)
        except EnvelopeValidationError:
            await self._emit_player_error(sid, "invalid_command")
            return
        if not self.security.limiters.allow_snapshot_read(identity.session_id):
            await self._emit_player_error(sid, "rate_limited")
            return
        if request.instance_id != identity.instance_id:
            await self._emit_player_error(sid, "server_instance_changed")
        elif request.session_epoch != identity.session_epoch:
            await self._emit_player_error(sid, "session_epoch_changed")
        await self._emit_player_snapshot(sid, identity, read_admitted=True)

    async def _handle_player_active_pc_select(self, sid: str, payload: object) -> None:
        """Commit one revision-checked selection and refresh only its requester."""
        identity = self._authorized_socket_identity(sid)
        if identity is None:
            return
        if not self.security.limiters.event_payload_allowed(payload):
            await self._emit_player_error(sid, "invalid_command")
            await self._emit_player_snapshot(sid, identity)
            return
        if not self.security.limiters.allow_snapshot_read(identity.session_id):
            await self._emit_player_error(sid, "rate_limited")
            return
        try:
            request = validate_active_pc_selection_envelope(payload)
        except EnvelopeValidationError:
            await self._emit_player_error(sid, "invalid_command")
            await self._emit_player_snapshot(sid, identity, read_admitted=True)
            return

        if request.instance_id != identity.instance_id:
            await self._emit_player_error(sid, "server_instance_changed")
            await self._emit_player_snapshot(sid, identity, read_admitted=True)
            return
        if request.session_epoch != identity.session_epoch:
            await self._emit_player_error(sid, "session_epoch_changed")
            await self._emit_player_snapshot(sid, identity, read_admitted=True)
            return

        selection = await asyncio.to_thread(
            select_player_active_pc,
            request.character_name,
            request.expected_revision,
        )
        if not self.security.authorize_socket_event(sid):
            return
        if selection.status == "selected":
            if selection.changed:
                self._active_pc_selection_committed(selection)
        else:
            error_code = (
                "stale_context"
                if selection.status == "stale"
                else "not_party_member"
                if selection.reason == "not_party_member"
                else "selection_rejected"
            )
            await self._emit_player_error(sid, error_code)
        await self._emit_player_snapshot(sid, identity, read_admitted=True)

    def _active_pc_selection_committed(
        self,
        selection: PlayerActivePCSelection,
    ) -> None:
        """Single post-change seam for task 3.3 ordered player publication."""
        # TABLETOP MODE: Task 3.3 will connect this committed selection to the
        # ordered PlayerSyncCoordinator publication path. Task 3.1 deliberately
        # sends no selection event to other player sockets.
        del selection

    def _authorized_socket_identity(
        self,
        sid: str,
    ) -> PlayerSessionIdentity | None:
        if not self.security.authorize_socket_event(sid):
            return None
        return self.security.session_context_for_socket(sid)

    async def _emit_player_error(self, sid: str, code: str) -> None:
        if not self.security.authorize_socket_event(sid):
            return
        payload = make_error_envelope(code)
        if not self.security.limiters.event_payload_allowed(payload):
            return
        await self.socket_server.emit(
            "player.error",
            payload,
            namespace=PLAYER_NAMESPACE,
            to=sid,
        )

    async def _emit_player_snapshot(
        self,
        sid: str,
        identity: PlayerSessionIdentity,
        *,
        read_admitted: bool = False,
    ) -> None:
        if not self.security.authorize_socket_event(sid):
            return
        current_identity = self.security.session_context_for_socket(sid)
        if current_identity != identity:
            return
        if not read_admitted and not self.security.limiters.allow_snapshot_read(
            identity.session_id
        ):
            await self._emit_player_error(sid, "rate_limited")
            return
        try:
            self.sync.reset_for_instance(identity.instance_id)
            snapshot = await asyncio.to_thread(
                _capture_player_snapshot,
                self.sync,
                self.gateway,
                identity.session_epoch,
            )
            encoded = canonical_json_bytes(snapshot, MAX_SNAPSHOT_BYTES)
            if not self.security.limiters.snapshot_allowed(encoded):
                await self._emit_player_error(sid, "snapshot_too_large")
                return
        except EnvelopeTooLargeError:
            await self._emit_player_error(sid, "snapshot_too_large")
            return
        except (
            AttributeError,
            EnvelopeValidationError,
            OSError,
            ProjectionError,
            RuntimeError,
            TypeError,
            ValueError,
            RecursionError,
        ):
            await self._emit_player_error(sid, "snapshot_unavailable")
            return
        if not self.security.authorize_socket_event(sid):
            return
        if self.security.session_context_for_socket(sid) != identity:
            return
        await self.socket_server.emit(
            "player.snapshot",
            snapshot,
            namespace=PLAYER_NAMESPACE,
            to=sid,
        )

    async def _handle_player_input(self, sid: str, payload: object) -> None:
        """Validate, deduplicate, and acknowledge one typed player command."""
        if not self.security.authorize_socket_event(sid):
            return
        identity = self.security.session_context_for_socket(sid)
        if identity is None:
            return
        self.sync.reset_for_instance(identity.instance_id)
        receipt = await asyncio.to_thread(
            self.sync.submit_command,
            payload,
            session_id=identity.session_id,
            session_epoch=identity.session_epoch,
            limiters=self.security.limiters,
            gateway=self.gateway,
        )
        if not self.security.authorize_socket_event(sid):
            return
        if "request_id" in receipt:
            await self.socket_server.emit(
                "player.input.receipt",
                receipt,
                namespace=PLAYER_NAMESPACE,
                to=sid,
            )
        else:
            await self.socket_server.emit(
                "player.error",
                receipt,
                namespace=PLAYER_NAMESPACE,
                to=sid,
            )

    async def _disconnect_sockets(self, socket_ids: Iterable[str]) -> None:
        results = await asyncio.gather(
            *(
                self.socket_server.disconnect(sid, namespace=PLAYER_NAMESPACE)
                for sid in socket_ids
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                raise RuntimeError("failed to disconnect a revoked player socket") from result

    async def _startup(self) -> None:
        """Rotate security identities at each explicit listener start."""
        self.preflight_client_assets()
        self.security.start_listener()
        self.sync.reset_for_instance(self.security.server_instance_id)

    def preflight_client_assets(self) -> VerifiedPlayerClientAssets:
        """Load and retain the complete verified bundle before readiness."""
        if self._client_assets is not None:
            return self._client_assets
        try:
            self._client_assets = load_player_client_assets(self._build_root)
        except PlayerClientAssetsError as exc:
            from utils.enhanced_logger import error

            error(
                f"Player client assets failed preflight ({exc.code})",
                category="player",
            )
            raise
        return self._client_assets

    async def _shutdown(self) -> None:
        """Invalidate sessions and close their namespace sockets on stop."""
        socket_ids = self.security.stop_listener()
        await self._disconnect_sockets(socket_ids)

    async def publish_player_event(
        self,
        revision: int,
        event_type: str,
        projection: Mapping[str, object],
    ) -> int:
        """Retain and emit a versioned event only to authorized player sockets."""
        self.sync.reset_for_instance(self.security.server_instance_id)
        published = self.sync.publish_event(revision, event_type, projection)
        socket_ids = self.security.authorized_socket_ids()
        delivered = 0
        for sid in socket_ids:
            identity = self.security.session_context_for_socket(sid)
            if identity is None:
                continue
            event = published.for_session(identity.instance_id, identity.session_epoch)
            if not self.security.limiters.event_payload_allowed(event):
                raise ValueError("player event exceeds the configured size limit")
            await self.socket_server.emit(
                "player.event",
                event,
                namespace=PLAYER_NAMESPACE,
                to=sid,
            )
            delivered += 1
        return delivered


def create_app(
    gateway: PlayerGateway | None = None,
    *,
    port: int = PLAYER_PORT,
    security: PlayerSecurity | None = None,
    media_registry: MediaRegistry | None = None,
    build_root: str | PathLike[str] | None = None,
) -> PlayerApplication:
    """Construct the separate player app without opening a listener."""
    return PlayerApplication(
        gateway=gateway,
        port=port,
        security=security,
        media_registry=media_registry,
        build_root=build_root,
    )


def _capture_player_snapshot(
    sync: PlayerSyncCoordinator,
    gateway: PlayerGateway,
    session_epoch: str,
) -> dict[str, object]:
    """Use the same canonical snapshot path for HTTP and Socket.IO reads."""
    return sync.capture_snapshot(session_epoch, gateway.read_snapshot)


async def _read_bounded_body(
    scope: Mapping[str, Any],
    receive: Callable[[], Awaitable[Mapping[str, Any]]],
) -> tuple[bytes | None, int | None]:
    """Read no more than the configured HTTP body bound before parsing."""
    try:
        content_lengths = header_values(scope.get("headers", ()), "content-length")
    except TypeError:
        return None, 400
    if len(content_lengths) > 1:
        return None, 400
    expected_length: int | None = None
    if content_lengths:
        content_length = content_lengths[0]
        if not content_length.isascii() or not content_length.isdigit():
            return None, 400
        if len(content_length) > 20:
            return None, 413
        try:
            expected_length = int(content_length)
        except ValueError:
            return None, 400
        if expected_length > MAX_HTTP_BODY_BYTES:
            return None, 413

    body = bytearray()
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return None, 400
        if message.get("type") != "http.request":
            return None, 400
        chunk = message.get("body", b"")
        if not isinstance(chunk, bytes):
            return None, 400
        if len(body) + len(chunk) > MAX_HTTP_BODY_BYTES:
            return None, 413
        body.extend(chunk)
        if not message.get("more_body", False):
            break
    if expected_length is not None and len(body) != expected_length:
        return None, 400
    return bytes(body), None


def _parse_login_fields(
    body: bytes,
    headers: Iterable[tuple[object, object]],
) -> tuple[str | None, str | None] | None:
    content_types = header_values(headers, "content-type")
    if len(content_types) != 1:
        return None
    media_type = content_types[0].split(";", 1)[0].strip().casefold()
    if media_type == "application/json":
        try:
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return None
        if not isinstance(payload, dict) or set(payload) - {"password", "csrf_token"}:
            return None
        password = payload.get("password")
        csrf_nonce = payload.get("csrf_token")
    elif media_type == "application/x-www-form-urlencoded":
        try:
            encoded_form = body.decode("ascii")
            fields = parse_qs(
                encoded_form,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=2,
            )
        except (UnicodeDecodeError, ValueError):
            return None
        if set(fields) - {"password", "csrf_token"}:
            return None
        if any(len(values) != 1 for values in fields.values()):
            return None
        password = fields.get("password", [None])[0]
        csrf_nonce = fields.get("csrf_token", [None])[0]
    else:
        return None
    if password is not None and not isinstance(password, str):
        return None
    if csrf_nonce is not None and not isinstance(csrf_nonce, str):
        return None
    return password, csrf_nonce


def _parse_csrf_token(
    body: bytes,
    headers: Iterable[tuple[object, object]],
) -> str | None:
    content_types = header_values(headers, "content-type")
    if len(content_types) != 1:
        return None
    media_type = content_types[0].split(";", 1)[0].strip().casefold()
    if media_type == "application/json":
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return None
        if not isinstance(payload, dict) or set(payload) != {"csrf_token"}:
            return None
        token = payload["csrf_token"]
    elif media_type == "application/x-www-form-urlencoded":
        try:
            fields = parse_qs(
                body.decode("ascii"),
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=1,
            )
        except (UnicodeDecodeError, ValueError):
            return None
        if set(fields) != {"csrf_token"} or len(fields["csrf_token"]) != 1:
            return None
        token = fields["csrf_token"][0]
    else:
        return None
    return token if isinstance(token, str) else None


async def _send_json(
    send: Callable[[Mapping[str, Any]], Awaitable[None]],
    status: int,
    payload: Mapping[str, object],
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("ascii")
    await _send_response(
        send,
        status,
        body,
        _base_headers(b"application/json; charset=utf-8", len(body)),
    )


async def _send_response(
    send: Callable[[Mapping[str, Any]], Awaitable[None]],
    status: int,
    body: bytes,
    headers: list[tuple[bytes, bytes]],
) -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _base_headers(
    content_type: bytes,
    content_length: int,
    *,
    cache_control: bytes = b"no-store",
) -> list[tuple[bytes, bytes]]:
    return [
        (b"content-type", content_type),
        (b"content-length", str(content_length).encode("ascii")),
        (b"cache-control", cache_control),
        (b"x-content-type-options", b"nosniff"),
    ]


def _is_socketio_path(path: object) -> bool:
    return isinstance(path, str) and (
        path == "/socket.io" or path.startswith("/socket.io/")
    )


def _is_initial_socketio_handshake(scope: Mapping[str, Any]) -> bool | None:
    query_string = scope.get("query_string", b"")
    if not isinstance(query_string, bytes) or len(query_string) > 2048:
        return None
    try:
        query = parse_qs(
            query_string.decode("ascii"),
            keep_blank_values=True,
            max_num_fields=16,
        )
    except (UnicodeDecodeError, ValueError):
        return None
    session_ids = query.get("sid", [])
    if len(session_ids) > 1 or (session_ids and not session_ids[0]):
        return None
    return not session_ids


def _parse_reconnect_query(
    query_string: object,
) -> tuple[dict[str, object] | None, int | None]:
    """Parse only the bounded, exact cursor tuple used for reconnect replay."""
    if query_string == b"":
        return None, None
    if not isinstance(query_string, bytes) or len(query_string) > 1024:
        return None, 400
    try:
        query = parse_qs(
            query_string.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=3,
        )
    except (UnicodeDecodeError, ValueError):
        return None, 400
    if set(query) - {"instance_id", "session_epoch", "cursor"}:
        return None, 400
    if any(len(values) != 1 for values in query.values()):
        return None, 400
    raw_cursor = query.get("cursor", [None])[0]
    cursor: int | None = None
    if (
        isinstance(raw_cursor, str)
        and raw_cursor.isascii()
        and raw_cursor.isdigit()
        and len(raw_cursor) <= 19
    ):
        try:
            parsed_cursor = int(raw_cursor)
        except ValueError:
            parsed_cursor = -1
        if str(parsed_cursor) == raw_cursor and parsed_cursor <= (1 << 63) - 1:
            cursor = parsed_cursor
    return {
        "instance_id": query.get("instance_id", [None])[0],
        "session_epoch": query.get("session_epoch", [None])[0],
        "cursor": cursor,
    }, None


def _parse_http_client_version(
    headers: Iterable[tuple[object, object]],
) -> tuple[str, int] | None:
    """Parse one bounded build/protocol pair from the documented HTTP headers."""
    try:
        build_values = header_values(headers, CLIENT_BUILD_HEADER)
        protocol_values = header_values(headers, PROTOCOL_VERSION_HEADER)
    except (TypeError, ValueError):
        return None
    if len(build_values) != 1 or len(protocol_values) != 1:
        return None
    build_id = build_values[0]
    protocol_text = protocol_values[0]
    if _CLIENT_BUILD_ID_PATTERN.fullmatch(build_id) is None:
        return None
    if (
        len(protocol_text) > 9
        or _CLIENT_PROTOCOL_VERSION_PATTERN.fullmatch(protocol_text) is None
    ):
        return None
    try:
        protocol_version = int(protocol_text)
    except ValueError:
        return None
    return build_id, protocol_version


def _parse_socket_client_version(auth: object) -> tuple[str, int] | None:
    """Accept only the exact, typed version fields in Socket.IO connect auth."""
    if not isinstance(auth, Mapping) or set(auth) != _SOCKET_CONNECT_AUTH_FIELDS:
        return None
    build_id = auth.get("client_build_id")
    protocol_version = auth.get("protocol_version")
    if (
        not isinstance(build_id, str)
        or _CLIENT_BUILD_ID_PATTERN.fullmatch(build_id) is None
        or type(protocol_version) is not int
        or protocol_version < 0
        or protocol_version > 999_999_999
    ):
        return None
    return build_id, protocol_version


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result
