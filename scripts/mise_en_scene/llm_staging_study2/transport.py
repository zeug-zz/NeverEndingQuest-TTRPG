# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""One-shot Study 2 OpenRouter adapter, usable only with a ledger capability."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import math
import re
from typing import TYPE_CHECKING, Any, Protocol

from ..llm_staging.transport import _sanitize_provider_response

if TYPE_CHECKING:
    from .client import Study2TransportResult


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = "openai/gpt-6-luna"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_USAGE_KEY_RE = re.compile(r"^[a-z_]{1,40}$")
_REQUEST_FIELDS = frozenset(
    {
        "model",
        "messages",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "max_tokens",
        "stream",
        "response_format",
        "tools",
        "tool_choice",
        "provider",
    }
)
_CONFIG_FIELDS = frozenset(
    {
        "schema",
        "endpoint",
        "model_id",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "max_tokens",
        "timeout_seconds",
        "stream",
        "response_format",
        "tools",
        "tool_choice",
        "provider",
    }
)


class Study2TransportError(RuntimeError):
    """Bounded adapter error that never exposes provider or credential detail."""


class HTTPPost(Protocol):
    """Narrow fakeable POST boundary; redirects are explicitly prohibited."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
        allow_redirects: bool,
    ) -> tuple[int, bytes]:
        """Perform one POST and return its status and body."""


@dataclass
class _ReservedDispatchContext:
    """One-use capability created after the Study 2 ledger fsyncs a reservation."""

    owner_token: object
    attempt_number: int
    scene_id: str
    run_id: str
    request_sha256: str
    config_sha256: str
    _used: bool = False

    def claim(self, owner_token: object) -> None:
        if self._used or owner_token is not self.owner_token:
            raise Study2TransportError("RESERVATION_CAPABILITY_INVALID")
        self._used = True


def _create_reserved_dispatch_context(
    owner_token: object,
    *,
    attempt_number: int,
    scene_id: str,
    run_id: str,
    request_sha256: str,
    config_sha256: str,
) -> _ReservedDispatchContext:
    if (
        type(attempt_number) is not int
        or attempt_number < 1
        or type(scene_id) is not str
        or not scene_id
        or type(run_id) is not str
        or not run_id
        or type(request_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None
        or type(config_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None
    ):
        raise Study2TransportError("RESERVATION_CAPABILITY_INVALID")
    return _ReservedDispatchContext(
        owner_token=owner_token,
        attempt_number=attempt_number,
        scene_id=scene_id,
        run_id=run_id,
        request_sha256=request_sha256,
        config_sha256=config_sha256,
    )


class _UrllibHTTP:
    """Default HTTP implementation with a handler that refuses redirects."""

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
            raise Study2TransportError("REDIRECTS_DISABLED")

        import urllib.error
        import urllib.request

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, response_headers, new_url):
                return None

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(NoRedirectHandler())
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error_response:
            try:
                return int(error_response.code), error_response.read(MAX_RESPONSE_BYTES + 1)
            finally:
                error_response.close()
        with response:
            return int(response.getcode()), response.read(MAX_RESPONSE_BYTES + 1)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise Study2TransportError("REQUEST_JSON_INVALID") from None


def _load_runtime_config() -> object:
    """Import local credentials only after capability and request checks."""

    return importlib.import_module("config")


def _parse_provider_body(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    return value if type(value) is dict else None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _safe_identity(value: object, limit: int = 256) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > limit
        or not value.isascii()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return ""
    return value


def _valid_usage(value: object, depth: int = 0) -> dict[str, Any] | None:
    if type(value) is not dict or not value or len(value) > 32 or depth > 4:
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str or _USAGE_KEY_RE.fullmatch(key) is None:
            return None
        if key == "is_byok":
            if depth != 0 or type(item) is not bool:
                return None
            result[key] = item
        elif type(item) in (int, float):
            if item < 0 or (type(item) is float and not math.isfinite(item)):
                return None
            result[key] = item
        elif type(item) is dict:
            nested = _valid_usage(item, depth + 1)
            if nested is None:
                return None
            result[key] = nested
        elif type(item) is list and len(item) <= 32:
            normalized: list[Any] = []
            for child in item:
                if type(child) in (int, float) and child >= 0 and (
                    type(child) is int or math.isfinite(child)
                ):
                    normalized.append(child)
                else:
                    return None
            result[key] = normalized
        else:
            return None
    if depth == 0 and any(
        type(result.get(key)) is not int or result[key] < 0
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return None
    return result


def _extract_response_metadata(body: bytes) -> tuple[str, str, str, dict[str, Any] | None]:
    parsed = _parse_provider_body(body)
    if parsed is None:
        return "", "", "", None
    usage = _valid_usage(parsed.get("usage"))
    return (
        _safe_identity(parsed.get("model")),
        _safe_identity(parsed.get("provider"), 128),
        _safe_identity(parsed.get("id")),
        usage,
    )


def _validate_generation_config(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _CONFIG_FIELDS:
        raise Study2TransportError("GENERATION_CONFIG_INVALID")
    if (
        value.get("schema") != "neq.llm_staging_study2_generation_config.v1"
        or value.get("endpoint") != OPENROUTER_ENDPOINT
        or value.get("model_id") != MODEL_ID
        or type(value.get("max_tokens")) is not int
        or value["max_tokens"] <= 0
        or type(value.get("timeout_seconds")) is not int
        or value["timeout_seconds"] <= 0
        or value.get("stream") is not False
        or value.get("response_format") != {"type": "json_object"}
        or value.get("tools") != []
        or value.get("tool_choice") != "none"
        or value.get("provider") != {"allow_fallbacks": False}
    ):
        raise Study2TransportError("GENERATION_CONFIG_INVALID")
    for field in ("temperature", "top_p", "frequency_penalty", "presence_penalty"):
        item = value.get(field)
        if type(item) not in (int, float) or not math.isfinite(float(item)):
            raise Study2TransportError("GENERATION_CONFIG_INVALID")
    return value


class OpenRouterTransport:
    """Guarded HTTP adapter. Public invocation always refuses without a capability."""

    def __init__(
        self,
        *,
        http: HTTPPost | None = None,
        config_loader=None,
    ) -> None:
        self._http = http if http is not None else _UrllibHTTP()
        self._config_loader = config_loader if config_loader is not None else _load_runtime_config

    def __call__(self, endpoint: str, request: dict[str, Any]) -> None:
        raise Study2TransportError("RESERVATION_REQUIRED")

    @staticmethod
    def _validate_request(endpoint: object, request: object, config: dict[str, Any]) -> bytes:
        if endpoint != OPENROUTER_ENDPOINT or type(request) is not dict or set(request) != _REQUEST_FIELDS:
            raise Study2TransportError("FROZEN_REQUEST_REQUIRED")
        if request.get("model") != MODEL_ID:
            raise Study2TransportError("FROZEN_MODEL_REQUIRED")
        for field in (
            "temperature", "top_p", "frequency_penalty", "presence_penalty",
            "max_tokens", "stream", "response_format", "tools", "tool_choice", "provider",
        ):
            if type(request.get(field)) is not type(config[field]) or request[field] != config[field]:
                raise Study2TransportError("FROZEN_PARAMETERS_REQUIRED")
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
            raise Study2TransportError("FROZEN_MESSAGE_SHAPE_REQUIRED")
        body = _canonical_bytes(request)
        if len(body) > MAX_REQUEST_BYTES:
            raise Study2TransportError("REQUEST_SIZE_LIMIT")
        return body

    def _dispatch_reserved(
        self,
        context: object,
        endpoint: object,
        request: object,
        generation_config_bytes: object,
        *,
        owner_token: object,
    ) -> Study2TransportResult:
        """Validate the one-use reservation before config lookup or HTTP."""

        if type(context) is not _ReservedDispatchContext:
            raise Study2TransportError("RESERVATION_CAPABILITY_INVALID")
        context.claim(owner_token)

        if type(generation_config_bytes) is not bytes or hashlib.sha256(generation_config_bytes).hexdigest() != context.config_sha256:
            raise Study2TransportError("GENERATION_CONFIG_HASH_MISMATCH")
        try:
            config_document = json.loads(
                generation_config_bytes.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=_parse_finite_float,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise Study2TransportError("GENERATION_CONFIG_INVALID") from None
        config = _validate_generation_config(config_document)
        request_body = self._validate_request(endpoint, request, config)
        request_hash = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        if request_hash != context.request_sha256:
            raise Study2TransportError("RESERVED_REQUEST_HASH_MISMATCH")

        credentials_unavailable = False
        try:
            configuration = self._config_loader()
            secret = getattr(configuration, "OPENROUTER_API_KEY", None)
        except Exception:
            credentials_unavailable = True
            secret = None
        if credentials_unavailable:
            raise Study2TransportError("CREDENTIALS_UNAVAILABLE") from None
        if (
            type(secret) is not str
            or not secret
            or len(secret) <= len("[REDACTED]")
            or not secret.isascii()
            or any(ord(character) < 33 or ord(character) > 126 for character in secret)
        ):
            raise Study2TransportError("CREDENTIALS_UNAVAILABLE")

        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + secret,
            "Content-Type": "application/json",
        }
        dispatch_failed = False
        try:
            status, response_body = self._http.post(
                url=OPENROUTER_ENDPOINT,
                headers=headers,
                body=request_body,
                timeout=float(config["timeout_seconds"]),
                allow_redirects=False,
            )
        except Exception:
            dispatch_failed = True
            status = None
            response_body = None
        if dispatch_failed:
            raise Study2TransportError("HTTP_DISPATCH_FAILED") from None
        if (
            type(status) is not int
            or not 100 <= status <= 599
            or type(response_body) is not bytes
        ):
            raise Study2TransportError("HTTP_RESPONSE_INVALID")

        safe_body, credential_echo = _sanitize_provider_response(response_body, secret)
        if credential_echo or len(safe_body) > MAX_RESPONSE_BYTES:
            model_id, provider, generation_id, usage = "", "", "", None
        else:
            model_id, provider, generation_id, usage = _extract_response_metadata(safe_body)
        return _make_transport_result(
            status,
            safe_body,
            model_id,
            provider,
            generation_id,
            usage,
        )


def _make_transport_result(
    status: int,
    body: bytes,
    model_id: str,
    provider: str,
    generation_id: str,
    usage: dict[str, Any] | None,
) -> Study2TransportResult:
    from .client import Study2TransportResult

    return Study2TransportResult(
        http_status=status,
        body=body,
        returned_model_id=model_id,
        upstream_provider=provider,
        generation_id=generation_id,
        usage=usage,
    )


__all__ = ["OpenRouterTransport", "Study2TransportError"]
