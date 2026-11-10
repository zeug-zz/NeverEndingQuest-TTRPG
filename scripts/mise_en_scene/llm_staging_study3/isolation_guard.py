# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Test-only suite-wide side-effect tripwires for Study 3 preparation."""

from __future__ import annotations

import builtins
import http.client
import importlib
import io
import os
from pathlib import Path
import socket
import sys
from typing import Any
import urllib.request
from unittest.mock import patch


PREP_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3-prep"
)
REAL_LEDGER_ROOTS = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging",
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2",
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study3",
)

_PROVIDER_SDK_ROOTS = frozenset(
    {
        "anthropic",
        "cohere",
        "google",
        "groq",
        "litellm",
        "mistralai",
        "openai",
        "replicate",
        "together",
        "vertexai",
    }
)
_HTTP_CLIENT_ROOTS = frozenset(
    {
        "aiohttp",
        "httpcore",
        "httpx",
        "requests",
        "socketio",
        "urllib3",
        "websockets",
    }
)
_CREDENTIAL_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_KEY",
    "_TOKEN",
    "_SECRET",
    "_SECRET_KEY",
    "_PASSWORD",
    "_CREDENTIALS",
    "_PRIVATE_KEY",
    "_KEY",
)
_PROVIDER_CONSTRUCTOR_NAMES = frozenset(
    {
        "Anthropic",
        "AsyncAnthropic",
        "AsyncClient",
        "AsyncGroq",
        "AsyncOpenAI",
        "AsyncTogether",
        "Client",
        "ClientV2",
        "GenerativeModel",
        "Groq",
        "Mistral",
        "OpenAI",
        "Together",
    }
)
_REAL_LEDGER_API_METHODS = (
    (
        "scripts.mise_en_scene.llm_staging.client",
        "StagingClient",
        ("_append_ledger_event", "send_once", "send_once_with_openrouter"),
    ),
    (
        "scripts.mise_en_scene.llm_staging_study2.client",
        "Study2Client",
        ("initialize_ledger", "send_once"),
    ),
    (
        "scripts.mise_en_scene.llm_staging_study2.ledger",
        "Study2Ledger",
        ("initialize", "reserve", "complete"),
    ),
)
_HTTP_TARGETS = (
    ("http.client", "HTTPConnection", "connect"),
    ("http.client", "HTTPConnection", "request"),
    ("http.client", "HTTPSConnection", "connect"),
    ("http.client", "HTTPSConnection", "request"),
    ("urllib.request", None, "urlopen"),
    ("urllib.request", "OpenerDirector", "open"),
    ("urllib.request", "HTTPHandler", "do_open"),
    ("urllib.request", "HTTPSHandler", "do_open"),
    ("requests.api", None, "request"),
    ("requests.sessions", "Session", "request"),
    ("requests.adapters", "HTTPAdapter", "send"),
    ("httpx", "Client", "send"),
    ("httpx", "AsyncClient", "send"),
    ("httpx._client", "Client", "send"),
    ("httpx._client", "AsyncClient", "send"),
    ("httpcore", "ConnectionPool", "handle_request"),
    ("httpcore", "AsyncConnectionPool", "handle_async_request"),
    ("urllib3.connectionpool", "HTTPConnectionPool", "urlopen"),
    ("urllib3.connectionpool", "HTTPSConnectionPool", "urlopen"),
    ("urllib3.poolmanager", "PoolManager", "urlopen"),
    ("aiohttp.client", "ClientSession", "_request"),
    ("socketio.client", "Client", "connect"),
    ("socketio.async_client", "AsyncClient", "connect"),
    ("websockets.sync.client", None, "connect"),
    ("websockets.asyncio.client", None, "connect"),
)


class TripwireBlocked(BaseException):
    """Uncatchable-by-ordinary-Exception sentinel raised before a side effect."""


def _block(calls: dict[str, int], category: str) -> None:
    calls[category] = calls.get(category, 0) + 1
    raise TripwireBlocked("STUDY3_TRIPWIRE_" + category.upper())


def _credential_name(name: object) -> bool:
    if isinstance(name, bytes):
        name = os.fsdecode(name)
    if type(name) is not str:
        return False
    normalized = name.upper()
    return any(normalized.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES)


def _path_forms(path: object) -> tuple[str, ...]:
    try:
        raw_path = os.fspath(path)
    except (TypeError, ValueError, OSError):
        return ()
    if isinstance(raw_path, bytes):
        raw_path = os.fsdecode(raw_path)
    try:
        absolute = os.path.normcase(os.path.abspath(raw_path))
        real = os.path.normcase(os.path.realpath(absolute))
    except (TypeError, ValueError, OSError, RuntimeError):
        return ()
    return (absolute, real)


def _under(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath((candidate, root)) == root
    except (ValueError, OSError):
        return False


def protected_real_ledger_path(path: object, repo_root: Path) -> bool:
    """Match fixed Study 1/2/3 roots lexically and through existing symlinks."""

    candidates = _path_forms(path)
    if not candidates:
        return False
    for relative_root in REAL_LEDGER_ROOTS:
        lexical_root = os.path.normcase(os.path.abspath(repo_root / relative_root))
        real_root = os.path.normcase(os.path.realpath(lexical_root))
        for candidate in candidates:
            if _under(candidate, lexical_root) or _under(candidate, real_root):
                return True
    return False


def _is_sensitive_config_path(path: object, repo_root: Path) -> bool:
    candidates = _path_forms(path)
    if not candidates:
        return False
    for relative_path in ("config.py", "model_config.py"):
        lexical = os.path.normcase(os.path.abspath(repo_root / relative_path))
        real = os.path.normcase(os.path.realpath(lexical))
        if any(candidate in (lexical, real) for candidate in candidates):
            return True
    return False


def _writes_mode(mode: object) -> bool:
    return type(mode) is str and any(flag in mode for flag in "wax+")


def _forbidden_import(name: object) -> str | None:
    if type(name) is not str:
        return None
    if name in {"config", "model_config"} or name.startswith(
        ("config.", "model_config.")
    ):
        return "config_import"
    root = name.split(".", 1)[0]
    if root in _PROVIDER_SDK_ROOTS:
        return "provider_import"
    if root in _HTTP_CLIENT_ROOTS:
        return "http_import"
    return None


class _ImportBlocker:
    def __init__(self, calls: dict[str, int]) -> None:
        self._calls = calls

    def find_spec(self, fullname: str, path: object = None, target: object = None):
        category = _forbidden_import(fullname)
        if category is not None:
            _block(self._calls, category)
        return None


def _install_http_guards(
    stack: ExitStack,
    calls: dict[str, int],
    patched_targets: set[tuple[int, str]],
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        _block(calls, "network")

    for name in (
        "create_connection",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
        "getnameinfo",
    ):
        if hasattr(socket, name):
            stack.enter_context(patch.object(socket, name, side_effect=deny_network))
    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            stack.enter_context(
                patch.object(socket.socket, name, side_effect=deny_network)
            )

    for module_name, class_name, attribute in _HTTP_TARGETS:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        namespace = getattr(module, "__dict__", {})
        target: object | None = module if class_name is None else namespace.get(class_name)
        if target is None:
            continue
        if class_name is None and attribute not in namespace:
            continue
        if class_name is not None and not hasattr(target, attribute):
            continue
        key = (id(target), attribute)
        if key in patched_targets:
            continue
        patched_targets.add(key)
        try:
            stack.enter_context(
                patch.object(target, attribute, side_effect=deny_network)
            )
        except (AttributeError, TypeError):
            _block(calls, "http_guard_installation")


def _install_provider_constructor_guards(
    stack: ExitStack,
    calls: dict[str, int],
    patched_classes: set[int],
) -> None:
    def deny_construction(*_args: object, **_kwargs: object) -> None:
        _block(calls, "provider_construction")

    for module_name, module in tuple(sys.modules.items()):
        if module is None or module_name.split(".", 1)[0] not in _PROVIDER_SDK_ROOTS:
            continue
        namespace = getattr(module, "__dict__", {})
        for constructor_name in _PROVIDER_CONSTRUCTOR_NAMES:
            constructor = namespace.get(constructor_name)
            if not isinstance(constructor, type):
                continue
            if constructor.__module__.split(".", 1)[0] not in _PROVIDER_SDK_ROOTS:
                continue
            identity = id(constructor)
            if identity in patched_classes:
                continue
            patched_classes.add(identity)
            try:
                stack.enter_context(
                    patch.object(
                        constructor,
                        "__init__",
                        side_effect=deny_construction,
                    )
                )
            except (AttributeError, TypeError):
                _block(calls, "provider_guard_installation")


def _install_real_ledger_api_guards(
    stack: ExitStack,
    calls: dict[str, int],
    patched_targets: set[tuple[int, str]],
) -> None:
    def deny_real_ledger(*_args: object, **_kwargs: object) -> None:
        _block(calls, "real_ledger_api")

    for module_name, class_name, method_names in _REAL_LEDGER_API_METHODS:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        namespace = getattr(module, "__dict__", {})
        ledger_class = namespace.get(class_name)
        if not isinstance(ledger_class, type):
            continue
        for method_name in method_names:
            if not hasattr(ledger_class, method_name):
                continue
            key = (id(ledger_class), method_name)
            if key in patched_targets:
                continue
            patched_targets.add(key)
            try:
                stack.enter_context(
                    patch.object(ledger_class, method_name, side_effect=deny_real_ledger)
                )
            except (AttributeError, TypeError):
                _block(calls, "real_ledger_guard_installation")


def install_tripwires(stack: ExitStack, repo_root: Path) -> dict[str, int]:
    """Install process-wide tripwires without importing config or provider SDKs."""

    calls: dict[str, int] = {}
    http_targets: set[tuple[int, str]] = set()
    provider_classes: set[int] = set()
    ledger_targets: set[tuple[int, str]] = set()

    def check_open(path: object, *, read: bool, write: bool) -> None:
        if (read or write) and _is_sensitive_config_path(path, repo_root):
            _block(calls, "config_file_access")
        if write and protected_real_ledger_path(path, repo_root):
            _block(calls, "real_ledger_path_write")

    original_builtin_open = builtins.open

    def guarded_builtin_open(file: object, *args: object, **kwargs: object):
        mode = args[0] if args else kwargs.get("mode", "r")
        write = _writes_mode(mode)
        check_open(file, read=not write, write=write)
        return original_builtin_open(file, *args, **kwargs)

    stack.enter_context(patch.object(builtins, "open", guarded_builtin_open))

    original_io_open = io.open

    def guarded_io_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        write = _writes_mode(mode)
        check_open(file, read=not write, write=write)
        return original_io_open(file, mode, *args, **kwargs)

    stack.enter_context(patch.object(io, "open", guarded_io_open))

    original_path_open = Path.open

    def guarded_path_open(
        path: Path, mode: str = "r", *args: object, **kwargs: object
    ):
        write = _writes_mode(mode)
        check_open(path, read=not write, write=write)
        return original_path_open(path, mode, *args, **kwargs)

    stack.enter_context(patch.object(Path, "open", guarded_path_open))

    if hasattr(io, "open_code"):
        original_open_code = io.open_code

        def guarded_open_code(path: object):
            check_open(path, read=True, write=False)
            return original_open_code(path)

        stack.enter_context(patch.object(io, "open_code", guarded_open_code))

    original_os_open = os.open
    write_flags = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_CREAT
        | os.O_TRUNC
        | os.O_APPEND
    )

    def guarded_os_open(path: object, flags: int, *args: object, **kwargs: object):
        write = bool(flags & write_flags)
        check_open(path, read=not write, write=write)
        return original_os_open(path, flags, *args, **kwargs)

    stack.enter_context(patch.object(os, "open", guarded_os_open))

    mutators: tuple[tuple[str, tuple[int, ...]], ...] = (
        ("chmod", (0,)),
        ("chown", (0,)),
        ("link", (0, 1)),
        ("makedirs", (0,)),
        ("mkdir", (0,)),
        ("mkfifo", (0,)),
        ("mknod", (0,)),
        ("remove", (0,)),
        ("rename", (0, 1)),
        ("replace", (0, 1)),
        ("rmdir", (0,)),
        ("symlink", (1,)),
        ("truncate", (0,)),
        ("unlink", (0,)),
        ("utime", (0,)),
    )
    for name, path_indexes in mutators:
        if not hasattr(os, name):
            continue
        original = getattr(os, name)

        def guarded_mutator(
            *args: object,
            _original: Any = original,
            _path_indexes: tuple[int, ...] = path_indexes,
            **kwargs: object,
        ):
            for path_index in _path_indexes:
                if path_index < len(args):
                    candidate = args[path_index]
                elif path_index == 0:
                    candidate = kwargs.get("path", kwargs.get("src"))
                else:
                    candidate = kwargs.get("dst")
                if candidate is not None and protected_real_ledger_path(
                    candidate, repo_root
                ):
                    _block(calls, "real_ledger_path_write")
            return _original(*args, **kwargs)

        stack.enter_context(patch.object(os, name, guarded_mutator))

    environ_types: set[type] = set()
    for environ in (getattr(os, "environ", None), getattr(os, "environb", None)):
        if environ is None or type(environ) in environ_types:
            continue
        environ_type = type(environ)
        environ_types.add(environ_type)
        for method_name in ("get", "__getitem__", "__contains__", "setdefault", "pop"):
            if not hasattr(environ_type, method_name):
                continue
            original = getattr(environ_type, method_name)

            def guarded_environment_lookup(
                env: object,
                key: object,
                *args: object,
                _original: Any = original,
                **kwargs: object,
            ):
                if _credential_name(key):
                    _block(calls, "credential_lookup")
                return _original(env, key, *args, **kwargs)

            stack.enter_context(
                patch.object(environ_type, method_name, guarded_environment_lookup)
            )

        for method_name in ("popitem", "items", "values", "copy", "__repr__"):
            if not hasattr(environ_type, method_name):
                continue
            original = getattr(environ_type, method_name)

            def guarded_environment_enumeration(
                env: object,
                *args: object,
                _original: Any = original,
                **kwargs: object,
            ):
                _block(calls, "credential_enumeration")
                return _original(env, *args, **kwargs)

            stack.enter_context(
                patch.object(
                    environ_type,
                    method_name,
                    guarded_environment_enumeration,
                )
            )

    original_getenv = os.getenv

    def guarded_getenv(key: object, default: object = None):
        if _credential_name(key):
            _block(calls, "credential_lookup")
        return original_getenv(key, default)

    stack.enter_context(patch.object(os, "getenv", guarded_getenv))
    if hasattr(os, "getenvb"):
        original_getenvb = os.getenvb

        def guarded_getenvb(key: object):
            if _credential_name(key):
                _block(calls, "credential_lookup")
            return original_getenvb(key)

        stack.enter_context(patch.object(os, "getenvb", guarded_getenvb))

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        category = _forbidden_import(name)
        if category is not None:
            _block(calls, category)
        imported = original_import(name, *args, **kwargs)
        _install_real_ledger_api_guards(stack, calls, ledger_targets)
        return imported

    stack.enter_context(patch.object(builtins, "__import__", guarded_import))

    original_import_module = importlib.import_module

    def guarded_import_module(name: str, package: str | None = None):
        category = _forbidden_import(name)
        if category is not None:
            _block(calls, category)
        imported = original_import_module(name, package)
        _install_real_ledger_api_guards(stack, calls, ledger_targets)
        return imported

    stack.enter_context(
        patch.object(importlib, "import_module", guarded_import_module)
    )

    blocker = _ImportBlocker(calls)
    sys.meta_path.insert(0, blocker)
    stack.callback(lambda: sys.meta_path.remove(blocker) if blocker in sys.meta_path else None)

    _install_http_guards(stack, calls, http_targets)
    _install_provider_constructor_guards(stack, calls, provider_classes)
    _install_real_ledger_api_guards(stack, calls, ledger_targets)
    return calls
