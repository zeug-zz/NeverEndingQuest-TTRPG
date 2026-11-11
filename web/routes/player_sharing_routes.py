# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Facilitator-local HTTP routes for the isolated player-sharing lifecycle."""

# TABLETOP MODE: These routes belong only to the local facilitator surface.

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request

from web.extensions.player.auth import _parse_public_https_origin


MAX_REQUEST_BYTES = 4096
_MAX_COUNTER = (1 << 31) - 1
_LOCAL_HOST_PATTERN = re.compile(r"(?i)(localhost|127\.0\.0\.1):([0-9]+)\Z")
_LIFECYCLE_STATES = frozenset(
    {
        "off",
        "initializing_required",
        "starting",
        "ready",
        "degraded",
        "failed",
        "stopping",
        "unsupported_platform",
    }
)
_LIFECYCLE_REASONS = frozenset(
    {
        "off",
        "startup_in_progress",
        "ready",
        "stopped",
        "unsupported_platform",
        "companion_missing",
        "identity_not_initialized",
        "credential_not_configured",
        "local_runtime_unavailable",
        "assets_unavailable",
        "listener_failed",
        "companion_failed",
        "monitor_failed",
        "reconnect_budget_exhausted",
        "route_unhealthy",
        "origin_unbound",
        "origin_changed",
        "stale_generation",
        "startup_cancelled",
        "readiness_regressed",
        "cleanup_failed",
        "cleanup_ambiguous",
        "shutting_down",
    }
)
_REASON_CODES = _LIFECYCLE_REASONS | frozenset(
    {
        "access_revoked",
        "credential_already_configured",
        "credential_issued",
        "credential_not_configured",
        "credential_revocation_failed",
        "credential_rotated",
        "credential_store_failed",
        "credential_store_invalid",
        "facilitator_confirmation_required",
        "identity_initialization_failed",
        "invitation_ready",
        "invitation_unavailable",
        "profile_unavailable",
        "controller_unavailable",
        "operation_failed",
        "companion_unavailable",
        "profile_layout_not_ready",
        "companion_unresolved",
        "companion_not_executable",
        "companion_digest_mismatch",
        "deadline_invalid",
        "bootstrap_dependency_invalid",
        "marker_valid",
        "marker_invalid",
        "profile_lock_unavailable",
        "profile_lock_timeout",
        "environment_allowlist_invalid",
        "preexisting_owned_resource",
        "precheck_unproven",
        "status_unproven",
        "up_failed_status_unproven",
        "owned_resource_remains",
        "postcheck_unproven",
        "down_failed",
        "up_failed",
        "marker_write_failed",
        "identity_initialized",
        "reconciliation_complete",
        "reconciliation_required",
        "reconciliation_failed",
        "host_not_allowed",
        "origin_not_allowed",
        "json_required",
        "request_too_large",
        "invalid_json",
        "request_invalid",
        "confirmation_required",
        "service_unavailable",
        "credential_unavailable",
        "listener_port_in_use",
        "listener_state_unavailable",
    }
)
_CHECK_FIELDS = (
    "platform_supported",
    "companion_available",
    "identity_initialized",
    "credential_configured",
    "local_runtime",
    "player_assets",
    "listener_started",
    "listener_authenticated",
    "owned_route_healthy",
    "route_generation_matches",
    "origin_bound",
)
_COUNTER_FIELDS = (
    "start_attempts",
    "successful_starts",
    "failed_starts",
    "readiness_checks",
    "degraded_transitions",
    "stop_requests",
    "cleanup_failures",
)


def register_player_sharing_routes(
    app: Flask,
    service_provider: Callable[[], Any],
    *,
    host_port: int = 8357,
    start_blocked: Callable[[], bool] | None = None,
) -> None:
    """Register local-only controls without constructing the service.

    POSTs require a loopback client and the exact same-origin HTTP Origin and
    Host for ``127.0.0.1`` or ``localhost`` on ``host_port``. They also require
    an application/json body no larger than ``MAX_REQUEST_BYTES``. This is the
    local host application's CSRF boundary; the player application's separate
    authentication and CSRF policy is unchanged.
    """
    if not callable(service_provider):
        raise TypeError("player_sharing_service_provider_required")
    if (
        not isinstance(host_port, int)
        or isinstance(host_port, bool)
        or not 1 <= host_port <= 65535
    ):
        raise ValueError("player_sharing_host_port_invalid")
    if start_blocked is not None and not callable(start_blocked):
        raise TypeError("player_sharing_start_guard_invalid")

    def respond(payload: dict[str, Any], status_code: int = 200) -> Response:
        response = jsonify(payload)
        response.status_code = status_code
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def fail(reason: str, status_code: int) -> Response:
        return respond({"ok": False, "reason": _safe_reason(reason)}, status_code)

    def check_local_surface(*, require_origin: bool) -> Response | None:
        remote_addr = request.remote_addr
        try:
            is_loopback_client = bool(
                isinstance(remote_addr, str)
                and ipaddress.ip_address(remote_addr.split("%", 1)[0]).is_loopback
            )
        except ValueError:
            is_loopback_client = False
        if not is_loopback_client or request.scheme.casefold() != "http":
            return fail("host_not_allowed", 403)

        hosts = request.headers.getlist("Host")
        if len(hosts) != 1 or not _valid_local_authority(hosts[0], host_port):
            return fail("host_not_allowed", 403)
        if not require_origin:
            return None

        origins = request.headers.getlist("Origin")
        if len(origins) != 1 or not _valid_same_origin(origins[0], hosts[0], host_port):
            return fail("origin_not_allowed", 403)
        return None

    def read_json_object() -> tuple[dict[str, Any] | None, Response | None]:
        content_types = request.headers.getlist("Content-Type")
        if (
            len(content_types) != 1
            or request.mimetype != "application/json"
            or any(
                parameter.casefold() != "utf-8"
                for name, parameter in request.mimetype_params.items()
                if name.casefold() == "charset"
            )
            or any(name.casefold() != "charset" for name in request.mimetype_params)
        ):
            return None, fail("json_required", 415)

        content_length = request.content_length
        if content_length is not None and content_length > MAX_REQUEST_BYTES:
            return None, fail("request_too_large", 413)
        try:
            raw = request.stream.read(MAX_REQUEST_BYTES + 1)
        except Exception:
            return None, fail("invalid_json", 400)
        if len(raw) > MAX_REQUEST_BYTES:
            return None, fail("request_too_large", 413)
        try:
            text = raw.decode("utf-8")
            value = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            return None, fail("invalid_json", 400)
        if not isinstance(value, dict):
            return None, fail("request_invalid", 400)
        return value, None

    def validate_fields(payload: dict[str, Any], allowed: frozenset[str]) -> Response | None:
        if any(not isinstance(key, str) for key in payload) or not set(payload).issubset(allowed):
            return fail("request_invalid", 400)
        return None

    def get_service() -> Any:
        try:
            service = service_provider()
        except Exception:
            return None
        return service

    def action_response(
        method_name: str,
        *,
        response_field: str | None = None,
    ) -> Response:
        service = get_service()
        if service is None:
            return fail("service_unavailable", 503)
        try:
            result = getattr(service, method_name)()
        except Exception:
            return fail("service_unavailable", 503)
        if getattr(result, "ok", None) is not True:
            return fail(_safe_reason(getattr(result, "reason", "operation_failed")), 409)

        status_payload = _status_projection(getattr(result, "status", None))
        if status_payload is None:
            return fail("service_unavailable", 503)
        response_payload: dict[str, Any] = {
            "ok": True,
            "reason": _safe_reason(getattr(result, "reason", "operation_failed")),
            "status": status_payload,
        }
        if response_field == "credential":
            holder = getattr(result, "credential", None)
            try:
                credential = holder.reveal()
            except Exception:
                return fail("credential_unavailable", 503)
            if (
                not isinstance(credential, str)
                or not credential
                or not credential.isascii()
                or len(credential) > 256
            ):
                return fail("credential_unavailable", 503)
            response_payload["credential"] = credential
        elif response_field == "invitation":
            invitation = getattr(result, "invitation", None)
            parsed = _parse_public_https_origin(invitation)
            if parsed is None:
                return fail("invitation_unavailable", 409)
            response_payload["invitation"] = parsed[0]
        return respond(response_payload)

    @app.route("/api/player-sharing/status", methods=["GET"])
    def player_sharing_status() -> Response:
        local_error = check_local_surface(require_origin=False)
        if local_error is not None:
            return local_error
        service = get_service()
        if service is None:
            return fail("service_unavailable", 503)
        try:
            status = service.diagnostics()
        except Exception:
            return fail("service_unavailable", 503)
        projection = _status_projection(status)
        if projection is None:
            return fail("service_unavailable", 503)
        return respond({"ok": True, "status": projection})

    @app.route("/api/player-sharing/initialize-identity", methods=["POST"])
    def player_sharing_initialize_identity() -> Response:
        return _initialize_identity()

    def _initialize_identity() -> Response:
        local_error = check_local_surface(require_origin=True)
        if local_error is not None:
            return local_error
        payload, parse_error = read_json_object()
        if parse_error is not None:
            return parse_error
        assert payload is not None
        invalid_fields = validate_fields(payload, frozenset({"confirm"}))
        if invalid_fields is not None:
            return invalid_fields
        if payload.get("confirm") is not True:
            return fail("confirmation_required", 400)
        service = get_service()
        if service is None:
            return fail("service_unavailable", 503)
        try:
            result = service.initialize_identity(facilitator_confirmed=True)
        except Exception:
            return fail("service_unavailable", 503)
        return _result_response(result)

    @app.route("/api/player-sharing/issue-access", methods=["POST"])
    def player_sharing_issue_access() -> Response:
        return _empty_body_action("issue_access", response_field="credential")

    @app.route("/api/player-sharing/start", methods=["POST"])
    def player_sharing_start() -> Response:
        return _empty_body_action("start", check_start_guard=True)

    @app.route("/api/player-sharing/stop", methods=["POST"])
    def player_sharing_stop() -> Response:
        return _empty_body_action("stop")

    @app.route("/api/player-sharing/rotate", methods=["POST"])
    def player_sharing_rotate() -> Response:
        return _empty_body_action("rotate_access", response_field="credential")

    @app.route("/api/player-sharing/revoke", methods=["POST"])
    def player_sharing_revoke() -> Response:
        return _empty_body_action("revoke_access")

    @app.route("/api/player-sharing/copy-invitation", methods=["POST"])
    def player_sharing_copy_invitation() -> Response:
        return _empty_body_action("copy_invitation", response_field="invitation")

    def _empty_body_action(
        method_name: str,
        *,
        response_field: str | None = None,
        check_start_guard: bool = False,
    ) -> Response:
        local_error = check_local_surface(require_origin=True)
        if local_error is not None:
            return local_error
        payload, parse_error = read_json_object()
        if parse_error is not None:
            return parse_error
        assert payload is not None
        invalid_fields = validate_fields(payload, frozenset())
        if invalid_fields is not None:
            return invalid_fields
        if check_start_guard and start_blocked is not None:
            try:
                if start_blocked() is True:
                    return fail("listener_port_in_use", 409)
            except Exception:
                return fail("listener_state_unavailable", 503)
        return action_response(method_name, response_field=response_field)

    def _result_response(result: Any) -> Response:
        if getattr(result, "ok", None) is not True:
            return fail(_safe_reason(getattr(result, "reason", "operation_failed")), 409)
        projection = _status_projection(getattr(result, "status", None))
        if projection is None:
            return fail("service_unavailable", 503)
        return respond(
            {
                "ok": True,
                "reason": _safe_reason(getattr(result, "reason", "operation_failed")),
                "status": projection,
            }
        )


def _valid_local_authority(authority: str, expected_port: int) -> bool:
    if not isinstance(authority, str) or not authority.isascii():
        return False
    match = _LOCAL_HOST_PATTERN.fullmatch(authority)
    if match is None or match.group(2) != str(expected_port):
        return False
    return match.group(1).casefold() in {"localhost", "127.0.0.1"}


def _valid_same_origin(origin: str, authority: str, expected_port: int) -> bool:
    if (
        not isinstance(origin, str)
        or not origin.isascii()
        or len(origin) > 512
        or any(ord(character) <= 32 or ord(character) == 127 for character in origin)
    ):
        return False
    try:
        parsed = urlsplit(origin)
        parsed_port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.netloc.casefold() == authority.casefold()
        and parsed.hostname is not None
        and parsed.hostname.casefold() in {"localhost", "127.0.0.1"}
        and parsed_port == expected_port
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.username is None
        and parsed.password is None
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid_json_constant")


def _safe_reason(value: object) -> str:
    return value if isinstance(value, str) and value in _REASON_CODES else "operation_failed"


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _bounded_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return min(max(value, 0), _MAX_COUNTER)


def _status_projection(status: object) -> dict[str, Any] | None:
    lifecycle = getattr(status, "lifecycle", None)
    if lifecycle is None:
        return None
    raw_state = _enum_value(getattr(lifecycle, "state", None))
    raw_reason = getattr(lifecycle, "reason", None)
    state = raw_state if isinstance(raw_state, str) and raw_state in _LIFECYCLE_STATES else "failed"
    reason = raw_reason if isinstance(raw_reason, str) and raw_reason in _LIFECYCLE_REASONS else "operation_failed"
    checks_obj = getattr(lifecycle, "checks", None)
    counters_obj = getattr(lifecycle, "counters", None)
    checks = {
        name: getattr(checks_obj, name, False) is True
        for name in _CHECK_FIELDS
    }
    counters = {
        name: _bounded_int(getattr(counters_obj, name, 0))
        for name in _COUNTER_FIELDS
    }
    raw_profile_state = getattr(status, "profile_state", None)
    profile_states = {
        "absent",
        "ready",
        "invalid",
        "unsafe_path",
        "foreign_or_invalid",
    }
    profile_state = (
        raw_profile_state
        if isinstance(raw_profile_state, str) and raw_profile_state in profile_states
        else "unavailable"
    )
    raw_credential_state = getattr(status, "credential_state", None)
    credential_state = (
        raw_credential_state
        if isinstance(raw_credential_state, str)
        and raw_credential_state in {"present", "absent", "invalid", "unsafe"}
        else "unavailable"
    )
    credential_generation = getattr(status, "credential_generation", None)
    if credential_generation is not None:
        credential_generation = _bounded_int(credential_generation)
    return {
        "state": state,
        "reason": reason,
        "generation": _bounded_int(getattr(lifecycle, "generation", 0)),
        "checks": checks,
        "counters": counters,
        "profile_state": profile_state,
        "identity_initialized": getattr(status, "identity_initialized", False) is True,
        "credential_state": credential_state,
        "credential_generation": credential_generation,
    }


__all__ = ["MAX_REQUEST_BYTES", "register_player_sharing_routes"]
