# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""One-shot OpenRouter transport guarded by a staging-ledger reservation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import re
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from .client import TransportResult


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = "openai/gpt-6-luna"
REQUEST_TIMEOUT_SECONDS = 180.0
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_USAGE_KEY_RE = re.compile(r"^[a-z_]{1,40}$")
_REQUEST_FIELDS = frozenset({
    "model", "messages", "temperature", "top_p", "frequency_penalty",
    "presence_penalty", "max_tokens", "stream", "response_format",
    "tools", "tool_choice", "provider",
})
_FROZEN_PARAMETERS = {
    "temperature": 1.0,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "max_tokens": 4096,
    "stream": False,
    "response_format": {"type": "json_object"},
    "tools": [],
    "tool_choice": "none",
    "provider": {"allow_fallbacks": False},
}


class OpenRouterTransportError(RuntimeError):
    """Safe transport failure with no provider or credential detail."""


@dataclass(frozen=True)
class _JSONObjectPairs:
    """JSON object representation retaining duplicate keys during scanning."""

    pairs: list[tuple[str, Any]]


class HTTPPost(Protocol):
    """Narrow injectable single-POST boundary used by offline tests."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
        allow_redirects: bool,
    ) -> tuple[int, bytes]:
        """Perform one HTTP POST and return its status and bounded body."""


@dataclass
class _ReservedDispatchContext:
    """One-use capability minted only after the client writes a reservation."""

    owner_token: object
    attempt_number: int
    scene_id: str
    request_sha256: str
    _used: bool = False

    def claim(self, owner_token: object) -> None:
        if self._used or owner_token is not self.owner_token:
            raise OpenRouterTransportError("a pending staging reservation is required")
        self._used = True


def _create_reserved_dispatch_context(
    owner_token: object,
    attempt_number: int,
    scene_id: str,
    request_sha256: str,
) -> _ReservedDispatchContext:
    """Mint an internal one-use dispatch capability for StagingClient only."""

    if (
        type(attempt_number) is not int
        or attempt_number < 1
        or type(scene_id) is not str
        or not scene_id
        or type(request_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None
    ):
        raise OpenRouterTransportError("staging reservation identity is invalid")
    return _ReservedDispatchContext(owner_token, attempt_number, scene_id, request_sha256)


class _UrllibHTTP:
    """Default HTTP implementation; urllib is called only after reservation."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
        allow_redirects: bool,
    ) -> tuple[int, bytes]:
        if allow_redirects is not False:
            raise OpenRouterTransportError("redirects are disabled")

        import urllib.error
        import urllib.request

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, headers, new_url):
                return None

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(NoRedirectHandler())
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error_response:
            try:
                status = int(error_response.code)
                response_body = error_response.read(MAX_RESPONSE_BYTES + 1)
            finally:
                error_response.close()
            return status, response_body

        with response:
            status = int(response.getcode())
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
        return status, response_body


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _load_config() -> object:
    """Load the existing local config only when a reserved dispatch is ready."""

    return importlib.import_module("config")


def _contains_secret_echo(value: object, secret: str) -> bool:
    if type(value) is _JSONObjectPairs:
        return any(
            secret in key or _contains_secret_echo(child, secret)
            for key, child in value.pairs
        )
    if type(value) is list:
        return any(_contains_secret_echo(child, secret) for child in value)
    if type(value) is str:
        return secret in value
    return False


def _contains_secret_in_json_strings(text: str, secret: str) -> bool:
    """Find escaped secret echoes in complete JSON string tokens, even if the
    surrounding response is malformed.
    """

    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        if text[index] != '"':
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        if type(value) is str and secret in value:
            return True
        index = max(end, index + 1)
    return False


def _sanitize_json_value(value: object, secret: str) -> object:
    if type(value) is _JSONObjectPairs:
        return {
            key.replace(secret, "[REDACTED]"): _sanitize_json_value(child, secret)
            for key, child in value.pairs
        }
    if type(value) is list:
        return [_sanitize_json_value(child, secret) for child in value]
    if type(value) is str:
        return value.replace(secret, "[REDACTED]")
    return value


def _sanitize_provider_response(body: bytes, secret: str) -> tuple[bytes, bool]:
    """Return original bytes when clean; otherwise redact every JSON echo.

    Credential-bearing responses are deliberately degraded so their metadata
    cannot produce a successful receipt. Malformed bodies with an echo are
    replaced wholesale because their structure cannot be safely rewritten.
    """

    secret_bytes = secret.encode("ascii")
    raw_echo = secret_bytes in body
    try:
        decoded = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_JSONObjectPairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        text_for_scan = body.decode("utf-8", errors="replace")
        decoded_echo = _contains_secret_in_json_strings(text_for_scan, secret)
        if raw_echo or decoded_echo:
            return b"[REDACTED]", True
        return body, False

    try:
        decoded_echo = _contains_secret_echo(decoded, secret)
    except RecursionError:
        decoded_echo = _contains_secret_in_json_strings(
            body.decode("utf-8", errors="replace"),
            secret,
        )
    if not raw_echo and not decoded_echo:
        return body, False

    try:
        sanitized_value = _sanitize_json_value(decoded, secret)
        sanitized_body = json.dumps(
            sanitized_value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        return b"[REDACTED]", True
    try:
        sanitized_decoded = json.loads(
            sanitized_body.decode("ascii"),
            object_pairs_hook=_JSONObjectPairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return b"[REDACTED]", True
    try:
        if secret_bytes in sanitized_body or _contains_secret_echo(sanitized_decoded, secret):
            return b"[REDACTED]", True
    except RecursionError:
        return b"[REDACTED]", True
    return sanitized_body, True


def _safe_response_metadata(body: bytes) -> tuple[str, str, str, dict[str, int]]:
    try:
        response = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return "", "", "", {}
    if type(response) is not dict:
        return "", "", "", {}

    def identity(field: str) -> str:
        value = response.get(field)
        if type(value) is not str:
            return ""
        return value

    raw_usage = response.get("usage")
    usage: dict[str, int] = {}
    if type(raw_usage) is dict:
        for key, value in raw_usage.items():
            if (
                type(key) is str
                and _USAGE_KEY_RE.fullmatch(key)
                and type(value) is int
                and value >= 0
            ):
                usage[key] = value
    return identity("model"), identity("provider"), identity("id"), usage


class OpenRouterTransport:
    """OpenRouter chat-completions adapter with no standalone send path.

    ``http`` and ``config_loader`` are injectable for provider-free tests. The
    default config loader and real HTTP implementation are used only when the
    staging client passes a one-use capability minted after ledger reservation.
    """

    def __init__(
        self,
        *,
        http: HTTPPost | None = None,
        config_loader: Callable[[], object] | None = None,
    ) -> None:
        self._http = http if http is not None else _UrllibHTTP()
        self._config_loader = config_loader if config_loader is not None else _load_config

    def __call__(self, endpoint: str, request: dict[str, Any]) -> None:
        """Refuse the legacy injected-transport seam before loading config."""

        raise OpenRouterTransportError("OpenRouter requires a pending staging reservation")

    @staticmethod
    def _validate_request(endpoint: object, request: object) -> bytes:
        if type(endpoint) is not str or endpoint != OPENROUTER_ENDPOINT:
            raise OpenRouterTransportError("the frozen OpenRouter endpoint is required")
        if type(request) is not dict or set(request) != _REQUEST_FIELDS:
            raise OpenRouterTransportError("the frozen one-shot request shape is required")
        if type(request.get("model")) is not str or request.get("model") != MODEL_ID:
            raise OpenRouterTransportError("the frozen OpenRouter model is required")
        for field, expected in _FROZEN_PARAMETERS.items():
            value = request.get(field)
            if type(value) is not type(expected) or value != expected:
                raise OpenRouterTransportError("the frozen generation parameters are required")
        messages = request.get("messages")
        if (
            type(messages) is not list
            or len(messages) != 2
            or any(
                type(message) is not dict
                or set(message) != {"role", "content"}
                or type(message.get("content")) is not str
                for message in messages
            )
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
        ):
            raise OpenRouterTransportError("the frozen system/user message shape is required")
        try:
            body = _canonical_bytes(request)
        except (TypeError, ValueError, RecursionError):
            raise OpenRouterTransportError("the frozen request is not valid JSON") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise OpenRouterTransportError("the frozen request exceeded its size limit")
        return body

    def _dispatch_reserved(
        self,
        context: object,
        endpoint: object,
        request: object,
        *,
        owner_token: object,
    ) -> TransportResult:
        """Perform exactly one POST after consuming a client-owned capability."""

        if type(context) is not _ReservedDispatchContext:
            raise OpenRouterTransportError("a pending staging reservation is required")
        context.claim(owner_token)
        request_body = self._validate_request(endpoint, request)
        try:
            request_hash = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        except (TypeError, ValueError, RecursionError):
            raise OpenRouterTransportError("the reserved request changed before dispatch") from None
        if request_hash != context.request_sha256:
            raise OpenRouterTransportError("the reserved request changed before dispatch")

        credential_lookup_failed = False
        secret: object = None
        try:
            configuration = self._config_loader()
            secret = getattr(configuration, "OPENROUTER_API_KEY", None)
        except Exception:
            credential_lookup_failed = True
        if credential_lookup_failed:
            raise OpenRouterTransportError("OpenRouter credentials are unavailable") from None
        if (
            type(secret) is not str
            or not secret
            or len(secret) <= len("[REDACTED]")
            or any(ord(character) < 33 or ord(character) > 126 for character in secret)
        ):
            raise OpenRouterTransportError("OpenRouter credentials are unavailable")
        try:
            secret.encode("utf-8")
        except UnicodeEncodeError:
            raise OpenRouterTransportError("OpenRouter credentials are unavailable") from None

        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + secret,
            "Content-Type": "application/json",
        }
        dispatch_failed = False
        status: object = None
        response_body: object = None
        try:
            status, response_body = self._http.post(
                url=OPENROUTER_ENDPOINT,
                headers=headers,
                body=request_body,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except Exception:
            dispatch_failed = True
        if dispatch_failed:
            raise OpenRouterTransportError("one-shot OpenRouter dispatch failed; allocation consumed") from None
        if (
            type(status) is not int
            or not 100 <= status <= 599
            or type(response_body) is not bytes
        ):
            raise OpenRouterTransportError("OpenRouter returned an invalid bounded response")

        safe_body, credential_echo = _sanitize_provider_response(response_body, secret)
        if credential_echo:
            return self._transport_result(status, safe_body, "", "", "", {})
        if len(safe_body) > MAX_RESPONSE_BYTES:
            return self._transport_result(status, safe_body, "", "", "", {})
        model_id, provider, generation_id, usage = _safe_response_metadata(safe_body)
        return self._transport_result(
            status,
            safe_body,
            model_id,
            provider,
            generation_id,
            usage,
        )

    @staticmethod
    def _transport_result(
        status: int,
        body: bytes,
        model_id: str,
        provider: str,
        generation_id: str,
        usage: dict[str, int],
    ) -> TransportResult:
        # Local import keeps the client seam free of config/network imports and
        # avoids a module import cycle.
        from .client import TransportResult

        return TransportResult(
            http_status=status,
            body=body,
            returned_model_id=model_id,
            upstream_provider=provider,
            generation_id=generation_id,
            usage=usage,
        )


__all__ = ["OpenRouterTransport", "OpenRouterTransportError"]
