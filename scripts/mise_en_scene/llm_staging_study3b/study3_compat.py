# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Grant-rooted adapters around the immutable Study 3 modules."""

from __future__ import annotations

import ast
import hashlib
import os
import sys
from importlib import import_module
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec, SourceFileLoader
from importlib.util import spec_from_loader
from pathlib import Path
from types import MappingProxyType, ModuleType

from . import isolation, protocol as study3b_protocol


_SOURCE_ROOT = "scripts/mise_en_scene/llm_staging_study3"
_PACKAGE_NAME = __package__ + "._study3_source"
_APPROVED_MODULES = frozenset({"protocol", "contract", "newrequest"})
_SOURCE_SHA256 = MappingProxyType(
    {
        _SOURCE_ROOT
        + "/protocol.py": "a8837cae9b620e8a0688eba3024be0294429fd6fa1225ff29b6dee854b46b571",
        _SOURCE_ROOT
        + "/contract.py": "aac9c3a0335df8e1128c4e3d463081078193fc0cede54f10fcf2c7ce1a3afa11",
        _SOURCE_ROOT
        + "/newrequest.py": "1d5d03240c3b7f877f00230d7450f2036dab8994cf65831a97698b9f4b4c6b22",
    }
)


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


def _is_lexical_protocol_root(node: ast.AST) -> bool:
    if (
        not isinstance(node, ast.Subscript)
        or not isinstance(node.value, ast.Attribute)
        or node.value.attr != "parents"
        or not isinstance(node.slice, ast.Constant)
        or node.slice.value != 3
        or not isinstance(node.value.value, ast.Call)
    ):
        return False
    root_call = node.value.value
    if (
        root_call.args
        or root_call.keywords
        or not isinstance(root_call.func, ast.Attribute)
        or root_call.func.attr != "resolve"
        or not isinstance(root_call.func.value, ast.Call)
    ):
        return False
    path_call = root_call.func.value
    return (
        isinstance(path_call.func, ast.Name)
        and path_call.func.id == "Path"
        and len(path_call.args) == 1
        and not path_call.keywords
        and isinstance(path_call.args[0], ast.Name)
        and path_call.args[0].id == "__file__"
    )


def _source_shape(source: bytes, relative_path: str) -> ast.Module:
    try:
        tree = ast.parse(source.decode("utf-8"), filename=relative_path)
    except (UnicodeError, SyntaxError):
        raise Study3CompatError("STUDY3_SOURCE_INVALID") from None

    is_protocol = relative_path.endswith("/protocol.py")
    is_contract = relative_path.endswith("/contract.py")
    root_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "REPO_ROOT"
            for target in node.targets
        )
    ]
    if is_protocol:
        if (
            len(root_assignments) != 1
            or root_assignments[0] not in tree.body
            or len(root_assignments[0].targets) != 1
            or not _is_lexical_protocol_root(root_assignments[0].value)
        ):
            raise Study3CompatError("STUDY3_PROTOCOL_ROOT_SHAPE_UNSUPPORTED")
    elif root_assignments:
        raise Study3CompatError("STUDY3_PROTOCOL_ROOT_SHAPE_UNSUPPORTED")

    readers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_safe_project_read"
    ]
    expected_reader_count = int(is_protocol or is_contract)
    if len(readers) != expected_reader_count or any(
        not isinstance(node, ast.FunctionDef) or node not in tree.body
        for node in readers
    ):
        raise Study3CompatError("STUDY3_PROTOCOL_PATH_SHAPE_UNSUPPORTED")
    for reader in readers:
        positional = [*reader.args.posonlyargs, *reader.args.args]
        if (
            [argument.arg for argument in positional] != ["relative_path"]
            or reader.args.vararg is not None
            or reader.args.kwarg is not None
            or (
                is_contract
                and (
                    [argument.arg for argument in reader.args.kwonlyargs]
                    != ["root"]
                    or len(reader.args.kw_defaults) != 1
                    or not isinstance(reader.args.kw_defaults[0], ast.Constant)
                    or reader.args.kw_defaults[0].value is not None
                )
            )
            or (not is_contract and reader.args.kwonlyargs)
        ):
            raise Study3CompatError("STUDY3_PROTOCOL_READER_SIGNATURE_UNSUPPORTED")

    ignored_nodes = {id(node) for node in readers + root_assignments}

    class _PathResolutionGuard(ast.NodeVisitor):
        def visit(self, node: ast.AST) -> None:
            if id(node) in ignored_nodes:
                return
            super().visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"resolve", "realpath"}
            ):
                raise Study3CompatError("STUDY3_PATH_ADAPTER_INCOMPLETE")
            self.generic_visit(node)

    _PathResolutionGuard().visit(tree)
    return tree


class _FrozenStudy3SourceLoader(SourceFileLoader):
    """Use the standard source loader with bytes read through the rooted fd API."""

    def __init__(self, name: str, filename: str, source: bytes) -> None:
        super().__init__(name, filename)
        self._frozen_filename = filename
        self._frozen_source = source

    def get_data(self, path: str) -> bytes:
        if path != self._frozen_filename:
            raise OSError("STUDY3_SOURCE_CACHE_DISABLED")
        return self._frozen_source

    def path_stats(self, path: str) -> dict[str, int]:
        if path != self._frozen_filename:
            raise OSError("STUDY3_SOURCE_PATH_REJECTED")
        return {"mtime": 0, "size": len(self._frozen_source)}

    def set_data(
        self, path: str, data: bytes, *, _mode: int = 0o666
    ) -> None:
        del path, data, _mode


class _FrozenStudy3SourceFinder(MetaPathFinder):
    """Expose one pre-read prior module through normal Python import semantics."""

    def __init__(self, name: str, relative_path: str, root: Path) -> None:
        self._name = name
        self._relative_path = relative_path
        self._root = root
        self.loader: _FrozenStudy3SourceLoader | None = None

    def find_spec(
        self, fullname: str, path: object = None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        del path, target
        if fullname != self._name:
            return None
        try:
            source = _safe_project_read(self._relative_path, self._root)
        except (OSError, ValueError, RuntimeError):
            raise Study3CompatError("STUDY3_SOURCE_UNAVAILABLE") from None
        expected_sha256 = _SOURCE_SHA256.get(self._relative_path)
        if (
            expected_sha256 is None
            or hashlib.sha256(source).hexdigest() != expected_sha256
        ):
            raise Study3CompatError("STUDY3_SOURCE_HASH_MISMATCH")
        _source_shape(source, self._relative_path)
        filename = os.fspath(self._root / self._relative_path)
        self.loader = _FrozenStudy3SourceLoader(fullname, filename, source)
        module_spec = spec_from_loader(fullname, self.loader, origin=filename)
        if module_spec is None:
            raise Study3CompatError("STUDY3_SOURCE_SPEC_UNAVAILABLE")
        module_spec.has_location = True
        return module_spec


def _create_package() -> ModuleType:
    package = sys.modules.get(_PACKAGE_NAME)
    if package is not None:
        return package
    package = ModuleType(_PACKAGE_NAME)
    package.__package__ = _PACKAGE_NAME
    package_path = os.fspath(study3b_protocol.REPO_ROOT / _SOURCE_ROOT)
    package.__path__ = [package_path]
    package.__file__ = os.path.join(package_path, "__init__.py")
    package_spec = ModuleSpec(_PACKAGE_NAME, loader=None, is_package=True)
    package_spec.submodule_search_locations = package.__path__
    package.__spec__ = package_spec
    sys.modules[_PACKAGE_NAME] = package
    parent = sys.modules.get(__package__)
    if parent is not None:
        setattr(parent, "_study3_source", package)
    return package


def _import_protocol_source(full_name: str, source_path: str) -> ModuleType:
    """Import the frozen protocol with its one root calculation made lexical."""

    original_resolve = Path.resolve
    resolve_count = 0

    def _lexical_source_root(path: Path, *args: object, **kwargs: object) -> Path:
        nonlocal resolve_count
        if (
            os.fspath(path) != source_path
            or args
            or kwargs
            or resolve_count != 0
        ):
            raise Study3CompatError("STUDY3_PROTOCOL_ROOT_SHAPE_UNSUPPORTED")
        resolve_count += 1
        return path

    try:
        Path.resolve = _lexical_source_root
        module = import_module(full_name)
    finally:
        Path.resolve = original_resolve
    if resolve_count != 1:
        raise Study3CompatError("STUDY3_PROTOCOL_ROOT_SHAPE_UNSUPPORTED")
    return module


def _load_source_module(name: str) -> ModuleType:
    if name not in _APPROVED_MODULES:
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
    finder = _FrozenStudy3SourceFinder(
        full_name, relative_path, study3b_protocol.REPO_ROOT
    )
    source_path = os.fspath(study3b_protocol.REPO_ROOT / relative_path)
    sys.meta_path.insert(0, finder)
    module: ModuleType | None = None
    try:
        if name == "protocol":
            module = _import_protocol_source(full_name, source_path)
        else:
            module = import_module(full_name)
        if finder.loader is None or module.__spec__.loader is not finder.loader:
            raise Study3CompatError("STUDY3_SOURCE_LOADER_UNEXPECTED")
        setattr(package, name, module)
        if name == "protocol":
            module.REPO_ROOT = study3b_protocol.REPO_ROOT
            original_reader = module._safe_project_read

            def _safe_protocol_read(relative_path: str) -> bytes:
                return _safe_project_read(relative_path, module.REPO_ROOT)

            _safe_protocol_read.__doc__ = original_reader.__doc__
            module._safe_project_read = _safe_protocol_read
        else:
            if name == "contract":
                original_reader = module._safe_project_read

                def _safe_contract_read(
                    relative_path: str, *, root: Path | None = None
                ) -> bytes:
                    return _safe_contract_project_read(relative_path, root, module)

                _safe_contract_read.__doc__ = original_reader.__doc__
                module._safe_project_read = _safe_contract_read
    except BaseException:
        sys.modules.pop(full_name, None)
        if module is not None and getattr(package, name, None) is module:
            delattr(package, name)
        raise
    finally:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass
    if module is None:
        raise Study3CompatError("STUDY3_SOURCE_UNAVAILABLE")
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
