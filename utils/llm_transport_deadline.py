# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Synchronous HTTPX transport with a total wall-clock request deadline.

Architecture: the factory builds an ordinary ``httpx.Client`` first so its
default TLS, proxy, mount, and connection-pool behavior is retained. Its base
and proxy transports are then wrapped. For HTTPX's built-in HTTP transports,
the existing httpcore network backend is decorated so every socket operation
uses the smaller of its configured timeout and the remaining request budget.
The response stream carries the same deadline across body reads and closes the
inner stream when the budget expires. No worker threads are created.
"""

from __future__ import annotations

import contextvars
import math
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpcore
import httpx


_DEADLINE_MESSAGE = "Total request deadline exceeded"
_MAX_READ_BLOCK_SECONDS = 0.25


@dataclass(frozen=True)
class _RequestDeadline:
    expires_at: float
    clock: Callable[[], float]
    request: httpx.Request


_ACTIVE_DEADLINE: contextvars.ContextVar[Optional[_RequestDeadline]] = (
    contextvars.ContextVar("neq_llm_request_deadline", default=None)
)


def _remaining_timeout(
    configured_timeout: Optional[float],
    timeout_error: type[httpcore.TimeoutException],
) -> Optional[float]:
    """Cap one blocking network operation to the active request deadline."""
    deadline = _ACTIVE_DEADLINE.get()
    if deadline is None:
        return configured_timeout

    remaining = deadline.expires_at - deadline.clock()
    if remaining <= 0:
        raise timeout_error(_DEADLINE_MESSAGE)
    if configured_timeout is None:
        return remaining
    return min(float(configured_timeout), remaining)


class _DeadlineNetworkStream:
    """Apply the active request's remaining time to each httpcore socket call."""

    def __init__(self, stream: object) -> None:
        self._stream = stream

    def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        deadline = _ACTIVE_DEADLINE.get()
        if deadline is None:
            return self._stream.read(max_bytes, timeout=timeout)

        operation_expires_at = (
            None if timeout is None else deadline.clock() + float(timeout)
        )
        while True:
            now = deadline.clock()
            request_remaining = deadline.expires_at - now
            operation_remaining = (
                None
                if operation_expires_at is None
                else operation_expires_at - now
            )
            if request_remaining <= 0 or (
                operation_remaining is not None and operation_remaining <= 0
            ):
                raise httpcore.ReadTimeout(_DEADLINE_MESSAGE)

            bounded_timeout = min(
                request_remaining,
                operation_remaining
                if operation_remaining is not None
                else request_remaining,
                _MAX_READ_BLOCK_SECONDS,
            )
            try:
                return self._stream.read(max_bytes, timeout=bounded_timeout)
            except httpcore.ReadTimeout:
                # Socket read timeouts do not consume response bytes. Poll again
                # only while both the configured read timeout and total request
                # budget still have time remaining.
                now = deadline.clock()
                if now >= deadline.expires_at or (
                    operation_expires_at is not None
                    and now >= operation_expires_at
                ):
                    raise

    def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        self._stream.write(
            buffer,
            timeout=_remaining_timeout(timeout, httpcore.WriteTimeout),
        )

    def start_tls(
        self,
        ssl_context: object,
        server_hostname: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "_DeadlineNetworkStream":
        stream = self._stream.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            timeout=_remaining_timeout(timeout, httpcore.ConnectTimeout),
        )
        return _DeadlineNetworkStream(stream)

    def close(self) -> None:
        self._stream.close()

    def get_extra_info(self, info: str) -> object:
        return self._stream.get_extra_info(info)


class _DeadlineNetworkBackend:
    """Delegate network setup while capping each operation to request time."""

    def __init__(self, backend: object) -> None:
        self._backend = backend

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: object = None,
    ) -> _DeadlineNetworkStream:
        stream = self._backend.connect_tcp(
            host=host,
            port=port,
            timeout=_remaining_timeout(timeout, httpcore.ConnectTimeout),
            local_address=local_address,
            socket_options=socket_options,
        )
        return _DeadlineNetworkStream(stream)

    def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options: object = None,
    ) -> _DeadlineNetworkStream:
        stream = self._backend.connect_unix_socket(
            path=path,
            timeout=_remaining_timeout(timeout, httpcore.ConnectTimeout),
            socket_options=socket_options,
        )
        return _DeadlineNetworkStream(stream)

    def sleep(self, seconds: float) -> None:
        bounded_sleep = _remaining_timeout(seconds, httpcore.ConnectTimeout)
        if bounded_sleep is None:
            return
        self._backend.sleep(bounded_sleep)
        deadline = _ACTIVE_DEADLINE.get()
        if deadline is not None and bounded_sleep < seconds:
            raise httpcore.ConnectTimeout(_DEADLINE_MESSAGE)

    def __getattr__(self, name: str) -> object:
        return getattr(self._backend, name)


class _DeadlineSyncByteStream(httpx.SyncByteStream):
    """Check each body chunk and keep the network deadline active while reading."""

    def __init__(self, stream: httpx.SyncByteStream, deadline: _RequestDeadline) -> None:
        self._stream = stream
        self._deadline = deadline
        self._closed = False

    def __iter__(self):
        iterator = iter(self._stream)
        while True:
            token = _ACTIVE_DEADLINE.set(self._deadline)
            try:
                self._raise_if_expired()
                try:
                    chunk = next(iterator)
                except StopIteration:
                    self._raise_if_expired()
                    return
                self._raise_if_expired()
            except BaseException:
                try:
                    self.close()
                except Exception:
                    # Preserve the original timeout/transport failure while
                    # still attempting to release the underlying response.
                    pass
                raise
            finally:
                _ACTIVE_DEADLINE.reset(token)
            yield chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stream.close()

    def _raise_if_expired(self) -> None:
        if self._deadline.clock() >= self._deadline.expires_at:
            raise httpx.ReadTimeout(
                _DEADLINE_MESSAGE,
                request=self._deadline.request,
            )


class TotalDeadlineTransport(httpx.BaseTransport):
    """Wrap an HTTPX transport so each request has one wall-clock budget."""

    def __init__(
        self,
        transport: httpx.BaseTransport,
        deadline_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise ValueError("deadline_seconds must be a positive finite number")
        self._transport = transport
        self._deadline_seconds = float(deadline_seconds)
        self._clock = clock
        self._install_network_backend()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        deadline = _RequestDeadline(
            expires_at=self._clock() + self._deadline_seconds,
            clock=self._clock,
            request=request,
        )
        token = _ACTIVE_DEADLINE.set(deadline)
        try:
            response = self._transport.handle_request(request)
        finally:
            _ACTIVE_DEADLINE.reset(token)

        if self._clock() >= deadline.expires_at:
            try:
                response.close()
            except Exception:
                # A close failure must not replace the deadline exception.
                pass
            raise httpx.ReadTimeout(_DEADLINE_MESSAGE, request=request)

        response.stream = _DeadlineSyncByteStream(response.stream, deadline)
        return response

    def close(self) -> None:
        self._transport.close()

    def _install_network_backend(self) -> None:
        """Decorate a fresh HTTPX HTTP/Proxy transport's httpcore backend."""
        pool = getattr(self._transport, "_pool", None)
        backend = getattr(pool, "_network_backend", None)
        if backend is None or isinstance(backend, _DeadlineNetworkBackend):
            return
        try:
            pool._network_backend = _DeadlineNetworkBackend(backend)
        except (AttributeError, TypeError):
            # Non-httpcore transports still receive per-chunk deadline checks.
            return


def create_deadline_http_client(
    timeout: httpx.Timeout,
    deadline_seconds: float,
) -> httpx.Client:
    """Build a default HTTPX client and wrap its base/proxy transports.

    Creating the default client first preserves HTTPX's environment proxy,
    TLS, and connection-pool configuration. Every selected HTTP transport is
    wrapped, including proxy mounts, before the client can issue a request.
    """
    client = httpx.Client(timeout=timeout)
    wrapped: dict[int, TotalDeadlineTransport] = {}

    def wrap(transport: httpx.BaseTransport) -> TotalDeadlineTransport:
        existing = wrapped.get(id(transport))
        if existing is not None:
            return existing
        result = TotalDeadlineTransport(transport, deadline_seconds)
        wrapped[id(transport)] = result
        return result

    try:
        client._transport = wrap(client._transport)
        for pattern, transport in tuple(client._mounts.items()):
            if transport is not None:
                client._mounts[pattern] = wrap(transport)
    except BaseException:
        client.close()
        raise
    return client
