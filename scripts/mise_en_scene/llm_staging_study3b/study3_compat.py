# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""In-memory, grant-rooted Study 3 adapters without importing the old package."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
from importlib.machinery import ModuleSpec
from types import ModuleType

from . import isolation, protocol as study3b_protocol


_SOURCE_ROOT = "scripts/mise_en_scene/llm_staging_study3"
_PACKAGE_NAME = __package__ + "._study3_source"


class Study3CompatError(RuntimeError):
    """Fail-closed error if the immutable Study 3 source shape drifts."""


def _safe_project_read(relative_path: str, root: Path) -> bytes:
    if (
        type(relative_path) is not str
        or not relative_path
        or "\\" in relative_path
        or any(part in ("", ".", "..") for part in relative_path.split("/"))
    ):
        raise ValueError("STUDY3_PATH_REJECTED")
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.as_posix() != relative_path:
        raise ValueError("STUDY3_PATH_REJECTED")
    try:
        return isolation._read_project_file(root, relative_path)
    except isolation.BaselinePathRejected:
        raise ValueError("STUDY3_PATH_REJECTED") from None
    except isolation.BaselineFileInvalid:
        raise ValueError("STUDY3_FILE_INVALID") from None
    except ValueError:
        raise ValueError("STUDY3_PATH_REJECTED") from None
    except isolation.BaselineScopeError:
        raise ValueError("STUDY3_ARTIFACT_UNAVAILABLE") from None
    except (OSError, RuntimeError):
        raise ValueError("STUDY3_ARTIFACT_UNAVAILABLE") from None


def _safe_contract_project_read(
    relative_path: str, root: Path | None, module: ModuleType
) -> bytes:
    try:
        base = module.protocol.REPO_ROOT if root is None else root
        return isolation._read_project_file(base, relative_path)
    except isolation.BaselinePathRejected:
        raise module.ContractError(
            "PROJECT_PATH_REJECTED", "HOST-PROJECT-PATH-BOUNDARY"
        ) from None
    except isolation.BaselineFileInvalid:
        raise module.ContractError(
            "PROJECT_FILE_INVALID", "HOST-PROJECT-PATH-BOUNDARY"
        ) from None
    except ValueError:
        raise module.ContractError(
            "PROJECT_PATH_REJECTED", "HOST-PROJECT-PATH-BOUNDARY"
        ) from None
    except isolation.BaselineScopeError:
        raise module.ContractError(
            "PROJECT_FILE_UNAVAILABLE", "HOST-PROJECT-PATH-BOUNDARY"
        ) from None
    except (OSError, RuntimeError):
        raise module.ContractError(
            "PROJECT_FILE_UNAVAILABLE", "HOST-PROJECT-PATH-BOUNDARY"
        ) from None


class _PathReadAdapter(ast.NodeTransformer):
    def __init__(self, root: Path, *, contract: bool = False) -> None:
        self._root = root
        self._contract = contract
        self.root_assignment_count = 0
        self.reader_count = 0

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        if any(
            isinstance(target, ast.Name) and target.id == "REPO_ROOT"
            for target in node.targets
        ):
            self.root_assignment_count += 1
            node.value = ast.Call(
                func=ast.Name(id="Path", ctx=ast.Load()),
                args=[ast.Constant(value=os.fspath(self._root))],
                keywords=[],
            )
            return ast.copy_location(node, node)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name != "_safe_project_read":
            return self.generic_visit(node)
        self.reader_count += 1
        if (
            [argument.arg for argument in node.args.args] != ["relative_path"]
            or (
                self._contract
                and [argument.arg for argument in node.args.kwonlyargs] != ["root"]
            )
            or (not self._contract and node.args.kwonlyargs)
        ):
            raise Study3CompatError("STUDY3_PROTOCOL_READER_SIGNATURE_UNSUPPORTED")
        docstring = node.body[0] if node.body and _is_docstring(node.body[0]) else None
        body: list[ast.stmt] = []
        if docstring is not None:
            body.append(docstring)
        helper = (
            "_study3b_safe_contract_read"
            if self._contract
            else "_study3b_safe_project_read"
        )
        body.append(
            ast.Return(
                value=ast.Call(
                    func=ast.Name(id=helper, ctx=ast.Load()),
                    args=[ast.Name(id="relative_path", ctx=ast.Load())],
                    keywords=(
                        [
                            ast.keyword(
                                arg="root", value=ast.Name(id="root", ctx=ast.Load())
                            )
                        ]
                        if self._contract
                        else []
                    ),
                )
            )
        )
        node.body = body
        return ast.copy_location(node, node)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is str
    )


def _create_package() -> ModuleType:
    package = sys.modules.get(_PACKAGE_NAME)
    if package is not None:
        return package
    package = ModuleType(_PACKAGE_NAME)
    package.__package__ = _PACKAGE_NAME
    package.__path__ = []
    package.__file__ = os.fspath(study3b_protocol.REPO_ROOT / _SOURCE_ROOT / "__init__.py")
    package.__spec__ = ModuleSpec(_PACKAGE_NAME, loader=None, is_package=True)
    sys.modules[_PACKAGE_NAME] = package
    parent = sys.modules.get(__package__)
    if parent is not None:
        setattr(parent, "_study3_source", package)
    return package


def _parse_source_tree(source: bytes, relative_path: str) -> ast.Module:
    try:
        tree = ast.parse(source.decode("utf-8"), filename=relative_path)
    except (UnicodeError, SyntaxError):
        raise Study3CompatError("STUDY3_SOURCE_INVALID") from None
    adapter = _PathReadAdapter(
        study3b_protocol.REPO_ROOT, contract=relative_path.endswith("/contract.py")
    )
    tree = adapter.visit(tree)
    if relative_path.endswith("/protocol.py") and adapter.root_assignment_count != 1:
        raise Study3CompatError("STUDY3_PROTOCOL_ROOT_SHAPE_UNSUPPORTED")
    expected_reader_count = int(
        relative_path.endswith("/protocol.py")
        or relative_path.endswith("/contract.py")
    )
    if adapter.reader_count != expected_reader_count:
        raise Study3CompatError("STUDY3_PROTOCOL_PATH_SHAPE_UNSUPPORTED")
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"resolve", "realpath"}
        for node in ast.walk(tree)
    ):
        raise Study3CompatError("STUDY3_PATH_ADAPTER_INCOMPLETE")
    return ast.fix_missing_locations(tree)


def _load_source_module(name: str) -> ModuleType:
    if name not in {"protocol", "contract", "newrequest"}:
        raise Study3CompatError("STUDY3_COMPAT_MODULE_NOT_APPROVED")
    full_name = _PACKAGE_NAME + "." + name
    existing = sys.modules.get(full_name)
    if existing is not None:
        return existing

    package = _create_package()
    if name == "contract":
        _load_source_module("protocol")
    elif name == "newrequest":
        _load_source_module("protocol")
        _load_source_module("contract")

    relative_path = _SOURCE_ROOT + "/" + name + ".py"
    try:
        source = isolation._read_project_file(study3b_protocol.REPO_ROOT, relative_path)
    except (OSError, ValueError, isolation.BaselineScopeError):
        raise Study3CompatError("STUDY3_SOURCE_UNAVAILABLE") from None
    tree = _parse_source_tree(source, relative_path)

    module = ModuleType(full_name)
    module.__file__ = os.fspath(study3b_protocol.REPO_ROOT / relative_path)
    module.__package__ = _PACKAGE_NAME
    module.__spec__ = ModuleSpec(full_name, loader=None)
    if name == "protocol":
        module.__dict__["_study3b_safe_project_read"] = lambda path: _safe_project_read(
            path, module.REPO_ROOT
        )
    elif name == "contract":
        module.__dict__["_study3b_safe_contract_read"] = (
            lambda path, root=None: _safe_contract_project_read(path, root, module)
        )
    sys.modules[full_name] = module
    setattr(package, name, module)
    try:
        code = compile(tree, module.__file__, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(full_name, None)
        if getattr(package, name, None) is module:
            delattr(package, name)
        raise
    return module


protocol = _load_source_module("protocol")
contract = _load_source_module("contract")
newrequest = _load_source_module("newrequest")

__all__ = [
    "Study3CompatError",
    "contract",
    "newrequest",
    "protocol",
]
