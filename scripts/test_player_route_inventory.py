# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free inventory tests for the host/player HTTP and Socket.IO split."""

from __future__ import annotations

import ast
import asyncio
import re
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web.extensions.player import PLAYER_NAMESPACE, create_app
from web.extensions.player.auth import PlayerSecurity
from web.extensions.player.capabilities import (
    HOST_ONLY,
    HOST_SURFACE_CLASSES,
    HOST_SURFACE_CLASSIFICATION,
    PLAYER_HTTP_ALLOWLIST,
    PLAYER_PROJECTION_OR_TYPED_COMMAND,
    PLAYER_SOCKET_EMISSION_ALLOWLIST,
    PLAYER_SOCKET_EVENT_ALLOWLIST,
    PLAYER_SOCKET_LIFECYCLE_EVENTS,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLAYER_PACKAGE_ROOT = REPOSITORY_ROOT / "web" / "extensions" / "player"
ROUTE_PARAMETER_PATTERN = re.compile(r"<(?:(?P<converter>[^:<>]+):)?(?P<name>[^<>]+)>")
PLAYER_CAPABILITIES_SPEC = (
    REPOSITORY_ROOT / "openspec" / "specs" / "player-capabilities" / "spec.md"
)


@dataclass(frozen=True)
class SurfaceInventory:
    """Fresh host surface names discovered from the checked-out source tree."""

    http_routes: frozenset[str]
    inbound_events: frozenset[str]
    emissions: frozenset[str]
    dynamic_event_sites: frozenset[str]
    discovery_errors: tuple[str, ...] = ()


def _expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _literal_string(node: ast.AST | None, constants: dict[str, str]) -> str | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (TypeError, ValueError):
        value = None
    if isinstance(value, str):
        return value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _module_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = _literal_string(node.value, {})
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


def _relative_path(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _python_trees(paths: list[Path]) -> tuple[dict[Path, ast.Module], list[str]]:
    trees: dict[Path, ast.Module] = {}
    errors: list[str] = []
    for path in sorted(set(paths)):
        try:
            source = path.read_text(encoding="utf-8")
            trees[path] = ast.parse(source, filename=_relative_path(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as parse_error:
            errors.append(f"{_relative_path(path)}: {parse_error}")
    return trees, errors


def _web_source_files() -> list[Path]:
    return [
        path
        for path in (REPOSITORY_ROOT / "web").rglob("*.py")
        if "web/extensions/player/" not in path.relative_to(REPOSITORY_ROOT).as_posix()
    ]


def _resolve_blueprint_symbol(
    module: str,
    expression: ast.AST,
    blueprint_defaults: dict[tuple[str, str], str],
    imported_symbols: dict[tuple[str, str], tuple[str, str]],
    imported_modules: dict[tuple[str, str], str],
) -> tuple[str, str] | None:
    if isinstance(expression, ast.Name):
        local_symbol = (module, expression.id)
        if local_symbol in blueprint_defaults:
            return local_symbol
        return imported_symbols.get(local_symbol)
    if isinstance(expression, ast.Attribute):
        parent = expression.value
        if isinstance(parent, ast.Name):
            imported_module = imported_modules.get((module, parent.id))
            if imported_module is not None:
                imported_symbol = (imported_module, expression.attr)
                if imported_symbol in blueprint_defaults:
                    return imported_symbol
        parent_symbol = _resolve_blueprint_symbol(
            module,
            parent,
            blueprint_defaults,
            imported_symbols,
            imported_modules,
        )
        if parent_symbol is not None:
            symbol = (f"{parent_symbol[0]}.{parent_symbol[1]}", expression.attr)
            if symbol in blueprint_defaults:
                return symbol
    return None


def _join_url_prefix(prefix: str, route: str) -> str:
    if not prefix:
        return route if route.startswith("/") else f"/{route}"
    if not route or route == "/":
        return prefix.rstrip("/") or "/"
    return f"{prefix.rstrip('/')}/{route.lstrip('/')}"


def _static_route_from_flask_app(
    path: Path,
    tree: ast.Module,
    errors: list[str],
) -> set[str]:
    """Include Flask's implicit static route when the real app enables it."""
    assignments: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments[node.target.id] = node.value

    def assigned_string(value: ast.AST, seen: frozenset[str] = frozenset()) -> str | None:
        try:
            literal = ast.literal_eval(value)
        except (TypeError, ValueError):
            literal = None
        if isinstance(literal, str):
            return literal
        if isinstance(value, ast.Name) and value.id not in seen:
            assignment = assignments.get(value.id)
            if assignment is not None:
                return assigned_string(assignment, seen | {value.id})
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            if value.func.attr == "join" and value.args:
                return assigned_string(value.args[-1], seen)
        return None

    routes: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or (_expression_name(node.func) or "").split(".")[-1] != "Flask"
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        static_folder = keywords.get("static_folder")
        if static_folder is None:
            folder_name = "static"
        else:
            try:
                static_folder_value = ast.literal_eval(static_folder)
            except (TypeError, ValueError):
                static_folder_value = object()
            if static_folder_value is None or static_folder_value is False:
                continue
            folder_name = assigned_string(static_folder)
            if folder_name is None:
                errors.append(
                    f"{_relative_path(path)}:{node.lineno}: non-literal Flask static_folder"
                )
                continue
            folder_name = folder_name.rstrip("/").split("/")[-1]

        static_url_path = keywords.get("static_url_path")
        if static_url_path is None:
            route_prefix = f"/{folder_name}"
        else:
            try:
                static_url_value = ast.literal_eval(static_url_path)
            except (TypeError, ValueError):
                static_url_value = object()
            if static_url_value is None:
                route_prefix = f"/{folder_name}"
            elif isinstance(static_url_value, str):
                route_prefix = "/" + static_url_value.strip("/")
            else:
                errors.append(
                    f"{_relative_path(path)}:{node.lineno}: non-literal Flask static_url_path"
                )
                continue
        routes.add(f"{route_prefix.rstrip('/')}/<path:filename>")
    return routes


def _discover_host_http_routes(trees: dict[Path, ast.Module]) -> tuple[set[str], list[str]]:
    routes: set[str] = set()
    errors: list[str] = []
    modules: dict[Path, str] = {}
    for path in trees:
        relative = path.relative_to(REPOSITORY_ROOT).with_suffix("").as_posix()
        module = relative[:-len("/__init__")] if relative.endswith("/__init__") else relative
        modules[path] = module.replace("/", ".")

    blueprint_defaults: dict[tuple[str, str], str] = {}
    imported_symbols: dict[tuple[str, str], tuple[str, str]] = {}
    imported_modules: dict[tuple[str, str], str] = {}

    for path, tree in trees.items():
        module = modules[path]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_module = node.module
                for alias in node.names:
                    imported_symbols[(module, alias.asname or alias.name)] = (
                        imported_module,
                        alias.name,
                    )
                continue
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    imported_modules[(module, local_name)] = alias.name
                continue
            elif isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if not isinstance(value, ast.Call):
                continue
            if (_expression_name(value.func) or "").split(".")[-1] != "Blueprint":
                continue
            keyword_map = {keyword.arg: keyword.value for keyword in value.keywords if keyword.arg}
            prefix_node = keyword_map.get("url_prefix")
            try:
                prefix = ast.literal_eval(prefix_node) if prefix_node is not None else ""
            except (TypeError, ValueError):
                prefix = None
            if prefix is not None and not isinstance(prefix, str):
                prefix = None
            for target in targets:
                if isinstance(target, ast.Name):
                    symbol = (module, target.id)
                    if prefix is None:
                        errors.append(
                            f"{_relative_path(path)}:{node.lineno}: non-literal Blueprint url_prefix"
                        )
                    else:
                        blueprint_defaults[symbol] = prefix

    blueprint_registrations: dict[tuple[str, str], list[str]] = {}
    for path, tree in trees.items():
        module = modules[path]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "register_blueprint" or not node.args:
                continue
            symbol = _resolve_blueprint_symbol(
                module,
                node.args[0],
                blueprint_defaults,
                imported_symbols,
                imported_modules,
            )
            if symbol is None:
                errors.append(
                    f"{_relative_path(path)}:{node.lineno}: unresolved register_blueprint target"
                )
                continue
            url_prefix_node = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "url_prefix"),
                None,
            )
            if url_prefix_node is None:
                prefix = blueprint_defaults[symbol]
            else:
                try:
                    prefix = ast.literal_eval(url_prefix_node)
                except (TypeError, ValueError):
                    prefix = None
            if not isinstance(prefix, str):
                errors.append(
                    f"{_relative_path(path)}:{node.lineno}: non-literal blueprint registration prefix"
                )
                continue
            blueprint_registrations.setdefault(symbol, []).append(prefix)

    for path, tree in trees.items():
        module = modules[path]
        for node in ast.walk(tree):
            route_call: ast.Call | None = None
            receiver: ast.AST | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "route"
                    ):
                        route_call = decorator
                        receiver = decorator.func.value
                        rule_node = route_call.args[0] if route_call.args else next(
                            (
                                keyword.value
                                for keyword in route_call.keywords
                                if keyword.arg in ("rule", "rule_string")
                            ),
                            None,
                        )
                        rule = _literal_string(rule_node, {})
                        if rule is None:
                            errors.append(
                                f"{_relative_path(path)}:{route_call.lineno}: non-literal HTTP route"
                            )
                            continue
                        blueprint_symbol = _resolve_blueprint_symbol(
                            module,
                            receiver,
                            blueprint_defaults,
                            imported_symbols,
                            imported_modules,
                        )
                        if blueprint_symbol is None:
                            routes.add(rule if rule.startswith("/") else f"/{rule}")
                        else:
                            for prefix in blueprint_registrations.get(blueprint_symbol, []):
                                routes.add(_join_url_prefix(prefix, rule))
                continue
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_url_rule"
            ):
                route_call = node
                receiver = node.func.value
            if route_call is None or receiver is None:
                continue
            rule_node = route_call.args[0] if route_call.args else next(
                (keyword.value for keyword in route_call.keywords if keyword.arg in ("rule", "rule_string")),
                None,
            )
            rule = _literal_string(rule_node, {})
            if rule is None:
                errors.append(
                    f"{_relative_path(path)}:{route_call.lineno}: non-literal HTTP route"
                )
                continue

            blueprint_symbol = _resolve_blueprint_symbol(
                module,
                receiver,
                blueprint_defaults,
                imported_symbols,
                imported_modules,
            )
            if blueprint_symbol is None:
                routes.add(rule if rule.startswith("/") else f"/{rule}")
                continue
            prefixes = blueprint_registrations.get(blueprint_symbol, [])
            for prefix in prefixes:
                routes.add(_join_url_prefix(prefix, rule))

    for path, tree in trees.items():
        if _relative_path(path) == "web/web_interface.py":
            routes.update(_static_route_from_flask_app(path, tree, errors))
    return routes, errors


class _HostEventVisitor(ast.NodeVisitor):
    """Collect host registrations/emissions while retaining dynamic callsites."""

    def __init__(self, path: Path, constants: dict[str, str], emit_aliases: set[str]) -> None:
        self.path = path
        self.constants = constants
        self.emit_aliases = emit_aliases
        self.function_stack: list[str] = []
        self.inbound_events: set[str] = set()
        self.emissions: set[str] = set()
        self.dynamic_sites: set[str] = set()

    def _site(self, kind: str, line: int) -> str:
        function_name = ".".join(self.function_stack) or "<module>"
        return f"dynamic:{kind}:{_relative_path(self.path)}:{function_name}:{line}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr in ("on", "on_event")
            and (_expression_name(function.value) or "").split(".")[-1] == "socketio"
        ):
            event_name = _literal_string(node.args[0] if node.args else None, self.constants)
            if event_name is None:
                self.dynamic_sites.add(self._site("inbound", node.lineno))
            else:
                self.inbound_events.add(event_name)

        host_socket_emit = (
            isinstance(function, ast.Attribute)
            and function.attr == "emit"
            and (_expression_name(function.value) or "").split(".")[-1] == "socketio"
        ) or (
            isinstance(function, ast.Name)
            and (
                function.id in self.emit_aliases
                or (
                    function.id == "emit_fn"
                    and _relative_path(self.path)
                    == "web/extensions/tabletop_socket_handlers.py"
                )
            )
        )
        if host_socket_emit:
            event_name = _literal_string(node.args[0] if node.args else None, self.constants)
            if event_name is None:
                self.dynamic_sites.add(self._site("emit", node.lineno))
            else:
                self.emissions.add(event_name)
        self.generic_visit(node)


def _flask_emit_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "flask_socketio":
            aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "emit"
            )
    return aliases


def _call_uses_host_socketio_emit(call: ast.Call) -> bool:
    function = call.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "emit"
        and (_expression_name(function.value) or "").split(".")[-1] == "socketio"
    )


def _host_emission_hooks(trees: dict[Path, ast.Module]) -> tuple[bool, bool]:
    has_stream_transport = False
    has_chat_monitor = False
    for path, tree in trees.items():
        if _relative_path(path) != "web/web_interface.py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "configure_stream_transport":
                has_stream_transport = has_stream_transport or any(
                    isinstance(argument, ast.Attribute)
                    and argument.attr == "emit"
                    and (_expression_name(argument.value) or "").split(".")[-1] == "socketio"
                    for argument in node.args
                )
            if node.func.id == "setup_live_chat_monitor":
                has_chat_monitor = has_chat_monitor or any(
                    isinstance(argument, ast.Name) and argument.id == "socketio"
                    for argument in node.args
                )
    return has_stream_transport, has_chat_monitor


def discover_host_surfaces() -> SurfaceInventory:
    """Re-enumerate source-defined host routes, handlers, and emissions."""
    web_files = _web_source_files()
    event_files = [
        path
        for source_root in ("web", "core", "utils", "updates")
        for path in (REPOSITORY_ROOT / source_root).rglob("*.py")
        if "web/extensions/player/" not in path.relative_to(REPOSITORY_ROOT).as_posix()
    ]
    event_files.append(REPOSITORY_ROOT / "main.py")
    trees, errors = _python_trees(web_files + event_files)
    routes, route_errors = _discover_host_http_routes(
        {path: tree for path, tree in trees.items() if path in web_files}
    )
    errors.extend(route_errors)

    inbound_events: set[str] = set()
    emissions: set[str] = set()
    dynamic_sites: set[str] = set()
    for path in event_files:
        tree = trees.get(path)
        if tree is None:
            continue
        visitor = _HostEventVisitor(path, _module_constants(tree), _flask_emit_aliases(tree))
        visitor.visit(tree)
        inbound_events.update(visitor.inbound_events)
        emissions.update(visitor.emissions)
        dynamic_sites.update(visitor.dynamic_sites)

    has_stream_transport, has_chat_monitor = _host_emission_hooks(trees)
    if has_stream_transport:
        stream_path = REPOSITORY_ROOT / "web" / "extensions" / "streaming_events.py"
        stream_tree = trees.get(stream_path)
        if stream_tree is not None:
            constants = _module_constants(stream_tree)
            visitor = _HostEventVisitor(stream_path, constants, set())
            visitor.visit(stream_tree)
            for node in ast.walk(stream_tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id == "_socket_emit":
                    event_name = _literal_string(node.args[0] if node.args else None, constants)
                    if event_name is None:
                        function_stack = _function_stack_for_line(stream_tree, node.lineno)
                        function_name = ".".join(function_stack) or "<module>"
                        dynamic_sites.add(
                            f"dynamic:emit:{_relative_path(stream_path)}:{function_name}:{node.lineno}"
                        )
                    else:
                        emissions.add(event_name)
                elif node.func.id == "_emit":
                    event_name = _literal_string(node.args[0] if node.args else None, constants)
                    if event_name is None:
                        function_stack = _function_stack_for_line(stream_tree, node.lineno)
                        function_name = ".".join(function_stack) or "<module>"
                        dynamic_sites.add(
                            f"dynamic:emit:{_relative_path(stream_path)}:{function_name}:{node.lineno}"
                        )
                    else:
                        emissions.add(event_name)

    if has_chat_monitor:
        monitor_path = REPOSITORY_ROOT / "web" / "extensions" / "live_chat_monitor.py"
        monitor_tree = trees.get(monitor_path)
        if monitor_tree is not None:
            for node in ast.walk(monitor_tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "original_socketio_emit"
                ):
                    event_name = _literal_string(
                        node.args[0] if node.args else None,
                        _module_constants(monitor_tree),
                    )
                    if event_name is None:
                        function_stack = _function_stack_for_line(monitor_tree, node.lineno)
                        function_name = ".".join(function_stack) or "<module>"
                        dynamic_sites.add(
                            f"dynamic:emit:{_relative_path(monitor_path)}:{function_name}:{node.lineno}"
                        )
                    else:
                        emissions.add(event_name)

    return SurfaceInventory(
        http_routes=frozenset(routes),
        inbound_events=frozenset(inbound_events),
        emissions=frozenset(emissions),
        dynamic_event_sites=frozenset(dynamic_sites),
        discovery_errors=tuple(sorted(set(errors))),
    )


def _function_stack_for_line(tree: ast.Module, line: int) -> list[str]:
    """Return enclosing function names for a source callsite line."""
    best: list[str] = []

    def visit(node: ast.AST, stack: list[str]) -> None:
        nonlocal best
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                next_stack = stack + [node.name]
                if len(next_stack) > len(best):
                    best = next_stack
                for child in ast.iter_child_nodes(node):
                    visit(child, next_stack)
                return
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    visit(tree, [])
    return best


def _inventory_surface_keys(inventory: SurfaceInventory) -> set[str]:
    return (
        {f"http:{route}" for route in inventory.http_routes}
        | {f"inbound:{event}" for event in inventory.inbound_events}
        | {f"emission:{event}" for event in inventory.emissions}
        | set(inventory.dynamic_event_sites)
    )


def _classification_differences(
    inventory: SurfaceInventory,
    classification: Mapping[str, str] = HOST_SURFACE_CLASSIFICATION,
) -> tuple[set[str], set[str], set[str]]:
    observed = _inventory_surface_keys(inventory)
    classified = set(classification)
    unclassified = observed - classified
    stale = classified - observed
    invalid_categories = {
        key
        for key, category in classification.items()
        if category not in HOST_SURFACE_CLASSES
    }
    return unclassified, stale, invalid_categories


def _sample_route(rule: str) -> str:
    def replace_parameter(match: re.Match[str]) -> str:
        converter = match.group("converter") or "string"
        if converter == "int":
            return "1"
        if converter == "float":
            return "1.0"
        if converter == "uuid":
            return "00000000-0000-0000-0000-000000000001"
        return "inventory-probe"

    return ROUTE_PARAMETER_PATTERN.sub(replace_parameter, rule)


def _dispatch_http(app: Any, path: str) -> tuple[int, bytes]:
    messages: list[dict[str, Any]] = []
    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "query_string": b"",
                "headers": [(b"host", b"127.0.0.1:8370")],
            },
            receive,
            send,
        )
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), body


def _discover_player_emissions() -> tuple[set[str], set[str]]:
    paths = list(PLAYER_PACKAGE_ROOT.rglob("*.py"))
    trees, errors = _python_trees(paths)
    if errors:
        raise AssertionError("player source could not be parsed: " + "; ".join(errors))
    emissions: set[str] = set()
    dynamic_sites: set[str] = set()
    for path, tree in trees.items():
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = _expression_name(node.func.value) or ""
            if node.func.attr != "emit" or "socket_server" not in receiver.split("."):
                continue
            event_name = _literal_string(node.args[0] if node.args else None, constants)
            if event_name is None:
                function_name = ".".join(_function_stack_for_line(tree, node.lineno)) or "<module>"
                dynamic_sites.add(
                    f"{_relative_path(path)}:{function_name}:{node.lineno}"
                )
            else:
                emissions.add(event_name)
    return emissions, dynamic_sites


def _player_allowlists_from_spec() -> tuple[
    frozenset[tuple[str, str]],
    frozenset[str],
    frozenset[str],
]:
    """Read the positive player route/event/emission set from its N1 contract."""
    spec = PLAYER_CAPABILITIES_SPEC.read_text(encoding="utf-8")
    requirement = next(
        (
            line
            for line in spec.splitlines()
            if line.startswith("The player application SHALL expose only ")
        ),
        None,
    )
    if requirement is None:
        raise AssertionError("player-capabilities allowlist requirement is missing")
    routes = frozenset(
        (method, path)
        for method, path in re.findall(r"`(GET|POST) ([^`]+)`", requirement)
    )
    try:
        event_clause = requirement.split(
            "Its `/player` namespace SHALL accept only ", 1
        )[1]
        accepted_clause, emitted_clause = event_clause.split(" and emit only ", 1)
        emitted_clause = emitted_clause.split(". Unknown paths", 1)[0]
    except IndexError as exc:
        raise AssertionError("player-capabilities event allowlists are malformed") from exc
    accepted = frozenset(re.findall(r"`([^`]+)`", accepted_clause))
    emitted = frozenset(re.findall(r"`([^`]+)`", emitted_clause))
    return routes, accepted, emitted


class PlayerRouteInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Importing web.web_interface is unsafe for an inventory test: module
        # initialization bootstraps the memory database and starts workers.
        # This source scan is the documented side-effect-free fallback; it
        # includes route decorators, add_url_rule, blueprint prefixes, and the
        # implicit Flask static route. No listener or provider is started.
        cls.inventory = discover_host_surfaces()

    def test_every_discovered_host_surface_has_one_current_classification(self) -> None:
        self.assertEqual(self.inventory.discovery_errors, ())
        unclassified, stale, invalid_categories = _classification_differences(self.inventory)
        self.assertEqual(unclassified, set(), f"unclassified host surfaces: {sorted(unclassified)}")
        self.assertEqual(stale, set(), f"stale host classifications: {sorted(stale)}")
        self.assertEqual(
            invalid_categories,
            set(),
            f"invalid host surface classes: {sorted(invalid_categories)}",
        )

    def test_player_app_registrations_equal_the_current_positive_allowlists(self) -> None:
        app = create_app(security=PlayerSecurity(lambda: None))
        self.assertEqual(app.http_router.registered_routes, PLAYER_HTTP_ALLOWLIST)
        self.assertEqual(app.registered_socket_events, PLAYER_SOCKET_EVENT_ALLOWLIST)
        self.assertEqual(app.socket_server.namespaces, [PLAYER_NAMESPACE])

        namespace_handlers = app.socket_server.handlers.get(PLAYER_NAMESPACE, {})
        self.assertEqual(
            set(namespace_handlers),
            set(PLAYER_SOCKET_EVENT_ALLOWLIST | PLAYER_SOCKET_LIFECYCLE_EVENTS),
        )
        self.assertEqual(app.socket_server.namespace_handlers, {})

        player_emissions, dynamic_player_emissions = _discover_player_emissions()
        self.assertEqual(player_emissions, PLAYER_SOCKET_EMISSION_ALLOWLIST)
        self.assertEqual(dynamic_player_emissions, set())

    def test_implemented_allowlists_equal_the_n1_spec_exactly(self) -> None:
        spec_http, spec_events, spec_emissions = _player_allowlists_from_spec()
        self.assertEqual(PLAYER_HTTP_ALLOWLIST, spec_http)
        self.assertEqual(PLAYER_SOCKET_EVENT_ALLOWLIST, spec_events)
        self.assertEqual(PLAYER_SOCKET_EMISSION_ALLOWLIST, spec_emissions)

    def test_host_only_http_paths_are_not_reachable_through_player_asgi_app(self) -> None:
        app = create_app(security=PlayerSecurity(lambda: None))
        host_only_routes = sorted(
            surface.removeprefix("http:")
            for surface, classification in HOST_SURFACE_CLASSIFICATION.items()
            if surface.startswith("http:") and classification == HOST_ONLY
        )
        self.assertTrue(host_only_routes, "the fresh host-only HTTP inventory must not be empty")
        for route in host_only_routes:
            path = _sample_route(route)
            with self.subTest(route=route, path=path):
                status, body = _dispatch_http(app, path)
                if route == "/":
                    # Both isolated apps use the root path, but the player app
                    # must serve only its public login shell, never the host UI.
                    self.assertEqual(status, 200)
                    self.assertIn(b"Player login", body)
                    self.assertNotIn(b"game_interface.html", body)
                    continue
                self.assertEqual(status, 404)
                self.assertNotIn(b"game_interface.html", body)

    def test_host_inbound_events_are_unregistered_from_player_namespace(self) -> None:
        app = create_app(security=PlayerSecurity(lambda: None))
        server = app.socket_server
        for event_name in sorted(self.inventory.inbound_events):
            with self.subTest(event=event_name):
                if event_name in PLAYER_SOCKET_LIFECYCLE_EVENTS:
                    # Socket.IO reserves connect/disconnect for transport
                    # lifecycle; the player's connect handler is its own auth
                    # boundary, not the host's connect callback.
                    if event_name == "connect":
                        result = asyncio.run(
                            server._trigger_event(
                                "connect",
                                PLAYER_NAMESPACE,
                                "inventory-probe-sid",
                                {},
                            )
                        )
                        self.assertFalse(result)
                    self.assertNotIn(event_name, app.registered_socket_events)
                    continue

                result = asyncio.run(
                    server._trigger_event(
                        event_name,
                        PLAYER_NAMESPACE,
                        "inventory-probe-sid",
                        {},
                    )
                )
                self.assertIs(result, server.not_handled)

    def test_synthetic_unclassified_route_and_event_make_inventory_check_fail(self) -> None:
        synthetic_inventory = SurfaceInventory(
            http_routes=self.inventory.http_routes | {"/synthetic-unclassified-route"},
            inbound_events=self.inventory.inbound_events | {"synthetic_unclassified_event"},
            emissions=self.inventory.emissions,
            dynamic_event_sites=self.inventory.dynamic_event_sites,
            discovery_errors=self.inventory.discovery_errors,
        )
        unclassified, _stale, _invalid = _classification_differences(synthetic_inventory)
        self.assertIn("http:/synthetic-unclassified-route", unclassified)
        self.assertIn("inbound:synthetic_unclassified_event", unclassified)
        self.assertTrue(unclassified)


if __name__ == "__main__":
    unittest.main()
