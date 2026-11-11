# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Path-confinement tripwires for Study 3b imports and local file readers."""

from __future__ import annotations

import ast
import builtins
from contextlib import ExitStack, contextmanager
from decimal import Decimal
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch


_SCRIPT_PATH = os.path.abspath(__file__)
_SCRIPTS_ROOT = os.path.dirname(_SCRIPT_PATH)
_REPO_ROOT = Path(os.path.dirname(_SCRIPTS_ROOT))
_PREP_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3b-prep"
)
_CAMPAIGN_ROOT = Path(
    "/Users/zeug/Projects/NeverEndingQuest/.git/overseer-relay/campaigns/neq-current-build"
)
sys.path.insert(0, os.fspath(_REPO_ROOT))


def _path_text(path: object) -> str:
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if type(raw) is not str:
        raise AssertionError("Filesystem path is not text")
    return raw


def _under(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath((candidate, root)) == root
    except (ValueError, OSError):
        return False


@contextmanager
def _tripwire_no_outside_filesystem_access():
    repo = os.path.normcase(os.path.normpath(os.fspath(_REPO_ROOT)))
    campaign = os.path.normcase(os.path.normpath(os.fspath(_CAMPAIGN_ROOT)))
    directory_fds: set[int] = set()
    rooted_fds: set[int] = set()
    active_realpaths: list[str] = []
    events: list[tuple[str, str]] = []
    original_open = os.open
    original_dup = os.dup
    original_close = os.close
    original_read = os.read
    original_write = os.write
    original_fstat = os.fstat
    original_fsync = os.fsync
    original_stat = os.stat
    original_lstat = os.lstat
    original_listdir = os.listdir
    original_scandir = os.scandir
    original_mkdir = os.mkdir
    original_symlink = os.symlink
    original_unlink = os.unlink
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_open_code = io.open_code
    original_path_open = Path.open
    original_path_stat = Path.stat
    original_path_lstat = Path.lstat
    original_path_resolve = Path.resolve
    original_realpath = os.path.realpath
    original_import = builtins.__import__

    def check_no_symlink_components(path: str, root: str) -> None:
        relative = os.path.relpath(path, root)
        current = root
        try:
            root_metadata = original_lstat(root)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(root_metadata.st_mode):
            raise AssertionError("filesystem root is a symlink")
        if relative == ".":
            return
        for part in relative.split(os.sep):
            current = os.path.join(current, part)
            try:
                metadata = original_lstat(current)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(metadata.st_mode):
                raise AssertionError("filesystem path contains a symlink")

    def check_path(operation: str, path: object, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            if dir_fd not in directory_fds:
                raise AssertionError(operation + " used an unrooted directory fd")
            raw = _path_text(path)
            if raw.startswith("/") or "/" in raw or raw in ("", ".", ".."):
                raise AssertionError(operation + " used a non-leaf dirfd path")
            events.append((operation, "dirfd:" + raw))
            return
        if isinstance(path, int):
            if path not in directory_fds:
                raise AssertionError(operation + " used an unrooted descriptor")
            events.append((operation, "fd"))
            return
        raw = _path_text(path)
        if ".." in raw.split(os.sep):
            raise AssertionError(operation + " used a traversal path")
        if not os.path.isabs(raw):
            raw = os.path.abspath(raw)
        normalized = os.path.normcase(os.path.normpath(raw))
        if _under(normalized, repo):
            check_no_symlink_components(normalized, repo)
        elif _under(normalized, campaign):
            check_no_symlink_components(normalized, campaign)
        else:
            raise AssertionError(operation + " escaped the granted roots")
        events.append((operation, normalized))

    def guarded_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and not flags & getattr(os, "O_NOFOLLOW", 0):
            raise AssertionError("dirfd open must reject symlinks")
        if flags & getattr(os, "O_DIRECTORY", 0) and not flags & getattr(
            os, "O_NOFOLLOW", 0
        ):
            raise AssertionError("directory open must reject symlinks")
        check_path("open", path, dir_fd)
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        rooted_fds.add(descriptor)
        if flags & getattr(os, "O_DIRECTORY", 0):
            directory_fds.add(descriptor)
        return descriptor

    def guarded_dup(descriptor: int) -> int:
        duplicate = original_dup(descriptor)
        if descriptor in rooted_fds:
            rooted_fds.add(duplicate)
        if descriptor in directory_fds:
            directory_fds.add(duplicate)
        return duplicate

    def guarded_close(descriptor: int) -> None:
        original_close(descriptor)
        directory_fds.discard(descriptor)
        rooted_fds.discard(descriptor)

    def check_descriptor(operation: str, descriptor: int) -> None:
        if descriptor not in rooted_fds:
            raise AssertionError(operation + " used an unrooted descriptor")
        events.append((operation, "fd"))

    def guarded_read(descriptor: int, count: int) -> bytes:
        check_descriptor("read", descriptor)
        return original_read(descriptor, count)

    def guarded_write(descriptor: int, data: bytes) -> int:
        check_descriptor("write", descriptor)
        return original_write(descriptor, data)

    def guarded_fstat(descriptor: int):
        check_descriptor("fstat", descriptor)
        return original_fstat(descriptor)

    def guarded_fsync(descriptor: int) -> None:
        check_descriptor("fsync", descriptor)
        original_fsync(descriptor)

    def guarded_stat(path: object, *args: object, **kwargs: object):
        if kwargs.get("dir_fd") is not None and kwargs.get("follow_symlinks", True):
            raise AssertionError("dirfd stat must not follow symlinks")
        check_path("stat", path, kwargs.get("dir_fd"))
        return original_stat(path, *args, **kwargs)

    def guarded_lstat(path: object, *args: object, **kwargs: object):
        if active_realpaths and not isinstance(path, int):
            raw = _path_text(path)
            if ".." not in raw.split(os.sep):
                absolute = raw if os.path.isabs(raw) else os.path.abspath(raw)
                normalized = os.path.normcase(os.path.normpath(absolute))
                if any(_under(realpath, normalized) for realpath in active_realpaths):
                    metadata = original_lstat(path, *args, **kwargs)
                    if stat.S_ISLNK(metadata.st_mode):
                        raise AssertionError("realpath encountered a symlink component")
                    events.append(("realpath-component-lstat", normalized))
                    return metadata
        check_path("lstat", path)
        return original_lstat(path, *args, **kwargs)

    def guarded_listdir(path: object = "."):
        if isinstance(path, int):
            check_path("listdir", path)
        else:
            check_path("listdir", path)
        return original_listdir(path)

    def guarded_scandir(path: object = "."):
        check_path("scandir", path)
        return original_scandir(path)

    def guarded_mkdir(
        path: object, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        check_path("mkdir", path, dir_fd)
        original_mkdir(path, mode, dir_fd=dir_fd)

    def guarded_unlink(path: object, *, dir_fd: int | None = None) -> None:
        check_path("unlink", path, dir_fd)
        original_unlink(path, dir_fd=dir_fd)

    def guarded_symlink(
        src: object,
        dst: object,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> None:
        source_text = _path_text(src)
        if not os.path.isabs(source_text):
            raise AssertionError("symlink targets must be absolute and root-verifiable")
        check_path("symlink-target", src)
        check_path("symlink-destination", dst, dir_fd)
        original_symlink(
            src,
            dst,
            target_is_directory=target_is_directory,
            dir_fd=dir_fd,
        )

    def forbidden_readlink(path: object, *, dir_fd: int | None = None) -> str:
        check_path("readlink", path, dir_fd)
        raise AssertionError("symlink resolution is forbidden in the confinement test")

    def guarded_builtin_open(file: object, *args: object, **kwargs: object):
        check_path("builtin-open", file)
        return original_builtin_open(file, *args, **kwargs)

    def guarded_io_open(file: object, *args: object, **kwargs: object):
        check_path("io-open", file)
        return original_io_open(file, *args, **kwargs)

    def guarded_open_code(path: object):
        check_path("open-code", path)
        return original_open_code(path)

    def guarded_path_open(path: Path, *args: object, **kwargs: object):
        mode = args[0] if args else kwargs.get("mode", "r")
        if type(mode) is not str:
            raise AssertionError("Path.open mode must be text")
        raw = _path_text(path)
        check_path("path-open-write", raw)
        if any(flag in mode for flag in "wax+"):
            normalized = os.path.normcase(os.path.normpath(raw))
            prep_root = os.path.normcase(
                os.path.normpath(os.fspath(_REPO_ROOT / _PREP_RELATIVE))
            )
            if not _under(normalized, prep_root):
                raise AssertionError(
                    "Path.open writes must stay under the Study 3b prep root"
                )
        return original_path_open(path, *args, **kwargs)

    def guarded_path_stat(path: Path, *args: object, **kwargs: object):
        check_path("path-stat", path)
        return original_path_stat(path, *args, **kwargs)

    def guarded_path_lstat(path: Path, *args: object, **kwargs: object):
        check_path("path-lstat", path)
        return original_path_lstat(path, *args, **kwargs)

    def guarded_import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: object = (),
        level: int = 0,
    ):
        resolved_name = name
        package_name = (
            globals.get("__package__") if isinstance(globals, dict) else None
        )
        if level and type(package_name) is str:
            package_parts = package_name.split(".")
            base_length = len(package_parts) - level + 1
            if base_length < 0:
                raise AssertionError("relative import escaped its package")
            resolved_name = ".".join(
                (*package_parts[:base_length], *(name.split(".") if name else ()))
            )
        import_targets = [resolved_name]
        if isinstance(fromlist, (tuple, list)):
            import_targets.extend(
                resolved_name + "." + item
                for item in fromlist
                if type(item) is str and item != "*" and resolved_name
            )
        if any(
            target == "scripts.mise_en_scene.llm_staging_study3"
            or target.startswith("scripts.mise_en_scene.llm_staging_study3.")
            for target in import_targets
        ):
            raise AssertionError("Study 3b must not import the immutable Study 3 package")
        return original_import(name, globals, locals, fromlist, level)

    def guarded_realpath(path: object, *args: object, **kwargs: object) -> str:
        check_path("realpath", path)
        raw = _path_text(path)
        absolute = raw if os.path.isabs(raw) else os.path.abspath(raw)
        normalized = os.path.normcase(os.path.normpath(absolute))
        active_realpaths.append(normalized)
        try:
            resolved = original_realpath(path, *args, **kwargs)
        finally:
            active_realpaths.pop()
        check_path("realpath-result", resolved)
        return resolved

    def guarded_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        check_path("path-resolve", path)
        resolved = original_path_resolve(path, *args, **kwargs)
        check_path("path-resolve-result", resolved)
        return resolved

    with ExitStack() as stack:
        stack.enter_context(patch.object(os, "open", guarded_open))
        stack.enter_context(patch.object(os, "dup", guarded_dup))
        stack.enter_context(patch.object(os, "close", guarded_close))
        stack.enter_context(patch.object(os, "read", guarded_read))
        stack.enter_context(patch.object(os, "write", guarded_write))
        stack.enter_context(patch.object(os, "fstat", guarded_fstat))
        stack.enter_context(patch.object(os, "fsync", guarded_fsync))
        stack.enter_context(patch.object(os, "stat", guarded_stat))
        stack.enter_context(patch.object(os, "lstat", guarded_lstat))
        stack.enter_context(patch.object(os, "listdir", guarded_listdir))
        stack.enter_context(patch.object(os, "scandir", guarded_scandir))
        stack.enter_context(patch.object(os, "mkdir", guarded_mkdir))
        stack.enter_context(patch.object(os, "symlink", guarded_symlink))
        stack.enter_context(patch.object(os, "readlink", forbidden_readlink))
        stack.enter_context(patch.object(os, "unlink", guarded_unlink))
        stack.enter_context(patch.object(builtins, "open", guarded_builtin_open))
        stack.enter_context(patch.object(io, "open", guarded_io_open))
        stack.enter_context(patch.object(io, "open_code", guarded_open_code))
        stack.enter_context(patch.object(Path, "open", guarded_path_open))
        stack.enter_context(patch.object(Path, "stat", guarded_path_stat))
        stack.enter_context(patch.object(Path, "lstat", guarded_path_lstat))
        stack.enter_context(patch.object(builtins, "__import__", guarded_import))
        stack.enter_context(patch.object(os.path, "realpath", guarded_realpath))
        stack.enter_context(patch.object(Path, "resolve", guarded_resolve))
        yield events


def _write_fixture(path: Path, content: bytes) -> None:
    os.makedirs(path.parent, exist_ok=True)
    path.write_bytes(content)


def _baseline_fixture(root: Path) -> bytes:
    source = b"synthetic baseline source bytes"
    _write_fixture(root / "scripts/mise_en_scene/prior-study.py", source)
    _write_fixture(root / "scripts/test_mise_en_scene_prior.py", b"synthetic test")
    for relative in (
        "modules/Into_the_Deepvault/areas/HA003_BU.json",
        "modules/Into_the_Deepvault/areas/SD005_BU.json",
        "modules/Xhalruuns_Masquerade/areas/TSU001_BU.json",
        "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/protocol.md",
        "openspec/changes/v2-mise-en-scene-study3-contract-parity/protocol.md",
        "plans/v2-mapping-pilot.md",
    ):
        _write_fixture(root / relative, b"synthetic prior fixture bytes")
    (root / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline").mkdir(
        parents=True, exist_ok=True
    )
    return source


def _protocol_fixture(root: Path, protocol_module: object) -> tuple[bytes, bytes]:
    source_manifest_path = "fixture/source-manifest.json"
    source_protocol_path = "fixture/source-protocol.md"
    artifact_protocol_path = "fixture/study3b-protocol.md"
    artifact_config_path = "fixture/study3b-config.json"
    manifest_path = "fixture/study3b-manifest.json"
    source_manifest = b"synthetic source manifest bytes"
    source_protocol = b"synthetic source protocol bytes"
    artifact_protocol = b"synthetic Study 3b protocol bytes\n"
    artifact_config = b"synthetic Study 3b config bytes\n"
    for relative, content in (
        (source_manifest_path, source_manifest),
        (source_protocol_path, source_protocol),
        (artifact_protocol_path, artifact_protocol),
        (artifact_config_path, artifact_config),
    ):
        _write_fixture(root / relative, content)

    source_manifest_hash = hashlib.sha256(source_manifest).hexdigest()
    source_protocol_hash = hashlib.sha256(source_protocol).hexdigest()
    artifact_protocol_hash = hashlib.sha256(artifact_protocol).hexdigest()
    artifact_config_hash = hashlib.sha256(artifact_config).hexdigest()
    artifacts = {
        "protocol": (artifact_protocol_path, artifact_protocol_hash),
        "generation_config": (artifact_config_path, artifact_config_hash),
    }
    manifest = {
        "schema": "neq.llm_staging_study3b_manifest.v1",
        "study_id": protocol_module.STUDY_ID,
        "protocol_version": protocol_module.PROTOCOL_VERSION,
        "status": "CONTRACT_PREPARATION_ONLY",
        "software_preparation_readiness": "PENDING",
        "dispatch_authorized": False,
        "scene_order": list(protocol_module.SCENE_ORDER),
        "attempt_cap": {
            "identity": protocol_module.STUDY_ID,
            "total": 3,
            "per_scene": 1,
            "scene_order": list(protocol_module.SCENE_ORDER),
        },
        "source_provenance": {
            "study_id": "synthetic-source-study",
            "manifest": {
                "path": source_manifest_path,
                "sha256": source_manifest_hash,
            },
            "protocol": {
                "path": source_protocol_path,
                "sha256": source_protocol_hash,
            },
        },
        "artifacts": {
            name: {"path": path, "sha256": digest}
            for name, (path, digest) in artifacts.items()
        },
        "hash_canonicalization": (
            "Protocol and configuration hashes cover exact stored UTF-8 bytes; "
            "manifest SHA-256 is pinned by the Study 3b protocol module."
        ),
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_fixture(root / manifest_path, manifest_bytes)
    values = {
        "MANIFEST_RELATIVE": manifest_path,
        "MANIFEST_SHA256": hashlib.sha256(manifest_bytes).hexdigest(),
        "SOURCE_STUDY_ID": "synthetic-source-study",
        "SOURCE_STUDY3_MANIFEST_RELATIVE": source_manifest_path,
        "SOURCE_STUDY3_MANIFEST_SHA256": source_manifest_hash,
        "SOURCE_STUDY3_PROTOCOL_RELATIVE": source_protocol_path,
        "SOURCE_STUDY3_PROTOCOL_SHA256": source_protocol_hash,
        "_ARTIFACTS": artifacts,
    }
    return artifact_protocol, values


def _seed_bound_protocol_fixtures(
    root: Path, study3b_protocol: object, study3_compat: object
) -> None:
    """Copy hash-bound protocol and source inputs under the disposable root."""

    for relative in (
        study3b_protocol.MANIFEST_RELATIVE,
        study3b_protocol.PROTOCOL_RELATIVE,
        study3b_protocol.GENERATION_CONFIG_RELATIVE,
        study3b_protocol.SOURCE_STUDY3_MANIFEST_RELATIVE,
        study3b_protocol.SOURCE_STUDY3_PROTOCOL_RELATIVE,
    ):
        _write_fixture(
            root / relative, study3b_protocol._safe_project_read(relative)
        )

    study3_protocol = study3_compat.protocol
    source_paths = {
        study3_protocol.PROTOCOL_RELATIVE + "/staging-manifest.json",
        *study3_protocol._ARTIFACT_PATHS.values(),
    }
    for relative in sorted(source_paths):
        _write_fixture(root / relative, study3_protocol._safe_project_read(relative))

    binding_path = study3_protocol._ARTIFACT_PATHS["input_bindings"]
    bindings = json.loads(
        study3_protocol._safe_project_read(binding_path).decode("utf-8")
    )
    for row in bindings["scenes"]:
        for key in ("source_packet", "expected_bundle"):
            relative = row["input_refs"][key]["id"]
            _write_fixture(
                root / relative, study3_protocol._safe_project_read(relative)
            )


class Study3bPathConfinementTests(unittest.TestCase):
    def test_compat_uses_no_explicit_dynamic_compile_or_exec(self) -> None:
        source_path = (
            _REPO_ROOT
            / "scripts/mise_en_scene/llm_staging_study3b/study3_compat.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        dynamic_calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"compile", "exec"}
        ]
        self.assertEqual(dynamic_calls, [])

    def test_prior_source_hashes_match_baseline_and_reject_tampering_first(self) -> None:
        prefix = "scripts.mise_en_scene.llm_staging_study3b"
        compat = importlib.import_module(prefix + ".study3_compat")
        isolation = importlib.import_module(prefix + ".isolation")
        baseline = isolation.read_baseline_metadata(repository_root=_REPO_ROOT)
        baseline_hashes = {
            entry["path"]: entry["sha256"] for entry in baseline["files"]
        }
        self.assertEqual(
            compat._SOURCE_SHA256,
            {
                path: baseline_hashes[path]
                for path in compat._SOURCE_SHA256
            },
        )

        for relative_path in compat._SOURCE_SHA256:
            with self.subTest(path=relative_path):
                module_name = Path(relative_path).stem
                finder = compat._FrozenStudy3SourceFinder(
                    compat._PACKAGE_NAME + "." + module_name,
                    relative_path,
                    _REPO_ROOT,
                )
                with patch.object(
                    compat,
                    "_safe_project_read",
                    return_value=b"\x00synthetic tampered source",
                ):
                    with self.assertRaisesRegex(
                        compat.Study3CompatError,
                        "STUDY3_SOURCE_HASH_MISMATCH",
                    ):
                        finder.find_spec(finder._name)
                self.assertIsNone(finder.loader)

    def test_import_baseline_and_protocol_io_stay_inside_granted_roots(self) -> None:
        prefix = "scripts.mise_en_scene.llm_staging_study3b"
        staging_prefix = "scripts.mise_en_scene.llm_staging"
        dependency_prefixes = (
            "jsonschema",
            "jsonschema_specifications",
            "referencing",
        )
        prior_modules = {
            name: module
            for name, module in tuple(sys.modules.items())
            if name == prefix or name.startswith(prefix + ".")
        }
        prior_staging_modules = {
            name: module
            for name, module in tuple(sys.modules.items())
            if name == staging_prefix or name.startswith(staging_prefix + ".")
        }
        prior_dependency_modules = {
            name: module
            for name, module in tuple(sys.modules.items())
            if any(
                name == dependency or name.startswith(dependency + ".")
                for dependency in dependency_prefixes
            )
        }
        for name in (
            *prior_modules,
            *prior_staging_modules,
            *prior_dependency_modules,
        ):
            sys.modules.pop(name, None)

        prep_root = _REPO_ROOT / _PREP_RELATIVE
        prep_root.mkdir(parents=True, exist_ok=True)
        fixture_root = prep_root / ("path-confinement-" + uuid.uuid4().hex)
        events: list[tuple[str, str]] = []
        try:
            with _tripwire_no_outside_filesystem_access() as events:
                isolation = importlib.import_module(prefix + ".isolation")
                protocol = importlib.import_module(prefix + ".protocol")
                with self.assertRaisesRegex(
                    AssertionError, "immutable Study 3 package"
                ):
                    builtins.__import__(
                        "llm_staging_study3",
                        {"__package__": prefix},
                        {},
                        ("protocol",),
                        2,
                    )

                source_bytes = _baseline_fixture(fixture_root)
                baseline = isolation.build_prior_study_baseline(fixture_root)
                source_entry = next(
                    entry
                    for entry in baseline["files"]
                    if entry["path"] == "scripts/mise_en_scene/prior-study.py"
                )
                self.assertEqual(
                    source_entry["sha256"], hashlib.sha256(source_bytes).hexdigest()
                )
                self.assertEqual(source_entry["size_bytes"], len(source_bytes))
                baseline_path = isolation.write_baseline_exclusive(
                    fixture_root,
                    _PREP_RELATIVE + "/baseline.json",
                )
                self.assertEqual(
                    isolation.read_baseline_metadata(
                        baseline_path, repository_root=fixture_root
                    ),
                    isolation.validate_baseline_metadata(baseline),
                )

                artifact_protocol, values = _protocol_fixture(fixture_root, protocol)
                with ExitStack() as stack:
                    for name, value in values.items():
                        stack.enter_context(patch.object(protocol, name, value))
                    stack.enter_context(patch.object(protocol, "REPO_ROOT", fixture_root))
                    manifest = protocol.load_manifest()
                    self.assertEqual(manifest["study_id"], protocol.STUDY_ID)
                    self.assertEqual(protocol.load_protocol_text(), artifact_protocol.decode())

                study3_compat = importlib.import_module(prefix + ".study3_compat")
                self.assertEqual(
                    study3_compat.protocol.__name__,
                    prefix + "._study3_source.protocol",
                )
                self.assertEqual(study3_compat.protocol.REPO_ROOT, _REPO_ROOT)
                _seed_bound_protocol_fixtures(fixture_root, protocol, study3_compat)
                cloned_protocol = study3_compat.protocol
                cloned_contract = study3_compat.contract
                safe_bytes = b"synthetic Study 3 protocol input"
                _write_fixture(fixture_root / "compat/safe-input.json", safe_bytes)
                os.makedirs(fixture_root / "compat/unsafe-directory")
                (fixture_root / "compat/alias.json").symlink_to(
                    fixture_root / "compat/safe-input.json"
                )
                with patch.object(cloned_protocol, "REPO_ROOT", fixture_root):
                    self.assertEqual(
                        cloned_protocol._safe_project_read("compat/safe-input.json"),
                        safe_bytes,
                    )
                    with self.assertRaisesRegex(
                        ValueError, "STUDY3_PATH_REJECTED"
                    ):
                        cloned_protocol._safe_project_read("compat/../outside.json")
                    with self.assertRaisesRegex(
                        ValueError, "STUDY3_PATH_REJECTED"
                    ):
                        cloned_protocol._safe_project_read("compat/alias.json")
                    with self.assertRaisesRegex(ValueError, "STUDY3_FILE_INVALID"):
                        cloned_protocol._safe_project_read("compat/unsafe-directory")
                with patch.object(cloned_protocol, "REPO_ROOT", fixture_root):
                    with self.assertRaises(cloned_contract.ContractError) as rejected:
                        cloned_contract._safe_project_read("compat/alias.json")
                    self.assertEqual(rejected.exception.code, "PROJECT_PATH_REJECTED")
                    with self.assertRaises(cloned_contract.ContractError) as invalid:
                        cloned_contract._safe_project_read("compat/unsafe-directory")
                    self.assertEqual(invalid.exception.code, "PROJECT_FILE_INVALID")

                inventory_module = importlib.import_module(prefix + ".inventory")
                request_module = importlib.import_module(prefix + ".newrequest")
                preflight_module = importlib.import_module(prefix + ".preflight")
                runner_module = importlib.import_module(prefix + ".runner")
                client_module = importlib.import_module(
                    "scripts.mise_en_scene.llm_staging.client"
                )
                transport_module = importlib.import_module(
                    "scripts.mise_en_scene.llm_staging.transport"
                )
                ledger_module = preflight_module.ledger
                self.assertIs(ledger_module.TransportResult, client_module.TransportResult)
                self.assertIs(runner_module.TransportResult, client_module.TransportResult)
                self.assertIs(
                    runner_module._OpenRouterTransport,
                    transport_module.OpenRouterTransport,
                )
                self.assertIs(
                    runner_module._ReservedDispatchContext,
                    transport_module._ReservedDispatchContext,
                )
                self.assertIs(
                    runner_module._create_reserved_dispatch_context,
                    transport_module._create_reserved_dispatch_context,
                )
                self.assertIs(
                    runner_module._UrllibHTTP,
                    transport_module._UrllibHTTP,
                )

                baseline_relative = (
                    _PREP_RELATIVE + "/prior-study-source-protocol-evidence-baseline.json"
                )
                baseline_bytes = isolation._read_project_file(
                    _REPO_ROOT, baseline_relative
                )
                self.assertEqual(
                    hashlib.sha256(baseline_bytes).hexdigest(),
                    preflight_module.PINNED_PRIOR_STUDY_BASELINE_SHA256,
                )
                pinned_baseline = json.loads(baseline_bytes.decode("utf-8"))
                for source_relative in (
                    "scripts/mise_en_scene/llm_staging/client.py",
                    "scripts/mise_en_scene/llm_staging/transport.py",
                ):
                    source_entries = [
                        entry
                        for entry in pinned_baseline["files"]
                        if entry.get("path") == source_relative
                    ]
                    self.assertEqual(len(source_entries), 1)
                    source_bytes = isolation._read_project_file(
                        _REPO_ROOT, source_relative
                    )
                    self.assertEqual(
                        hashlib.sha256(source_bytes).hexdigest(),
                        source_entries[0]["sha256"],
                    )
                    self.assertEqual(len(source_bytes), source_entries[0]["size_bytes"])

                owner_token = object()
                capability = transport_module._create_reserved_dispatch_context(
                    owner_token, 1, "synthetic-scene", "0" * 64
                )
                self.assertIs(type(capability), transport_module._ReservedDispatchContext)
                capability.claim(owner_token)
                with self.assertRaises(transport_module.OpenRouterTransportError):
                    capability.claim(owner_token)

                self.assertEqual(
                    tuple(client_module.TransportResult.__dataclass_fields__),
                    (
                        "http_status",
                        "body",
                        "returned_model_id",
                        "upstream_provider",
                        "generation_id",
                        "usage",
                    ),
                )
                with ExitStack() as stack:
                    stack.enter_context(patch.object(protocol, "REPO_ROOT", fixture_root))
                    stack.enter_context(
                        patch.object(cloned_protocol, "REPO_ROOT", fixture_root)
                    )
                    for scene_id in protocol.SCENE_ORDER:
                        inventory = inventory_module.load_scene_inventory(scene_id)
                        request = request_module.build_request(scene_id)
                        self.assertTrue(inventory.inventory_sha256)
                        self.assertTrue(type(request) is dict)
                        self.assertEqual(request.get("model"), protocol.MODEL_ID)
                        self.assertEqual(request.get("max_tokens"), 16384)
                        self.assertIs(request_module.study3_request, study3_compat.newrequest)

                    preflight_binding = SimpleNamespace(
                        scene_estimates=(
                            SimpleNamespace(conservative_cost_usd=Decimal("0.01")),
                        )
                    )
                    with patch.object(
                        preflight_module.ledger,
                        "_load_binding",
                        return_value=preflight_binding,
                    ):
                        cost_binding = preflight_module._validate_fixed_study_and_cost()
                    self.assertEqual(cost_binding["study_id"], protocol.STUDY_ID)
                    preflight_module._assert_fresh_run_root()

                self.assertTrue(any(event[0] == "listdir" for event in events))
                self.assertTrue(any(event[1] == "dirfd:fixture" for event in events))
                self.assertTrue(
                    any(
                        event[0] == "open" and event[1] == "dirfd:scripts"
                        for event in events
                    )
                )
                campaign_text = os.fspath(_CAMPAIGN_ROOT)
                self.assertFalse(
                    any(campaign_text in event[1] for event in events),
                    "synthetic import/request/preflight touched the campaign root",
                )
                self.assertFalse(
                    any(
                        name == prefix + ".legacy_transport"
                        or name.startswith(prefix + "._legacy_llm_staging")
                        for name in sys.modules
                    ),
                    "copied or dynamically compiled transport adapter was imported",
                )
                self.assertIn("scripts.mise_en_scene.llm_staging.client", sys.modules)
                self.assertIn("scripts.mise_en_scene.llm_staging.transport", sys.modules)
                self.assertTrue(
                    any(
                        event[0] == "path-resolve"
                        and event[1].endswith("/llm_staging/client.py")
                        for event in events
                    ),
                    "the original transport dependency import was not instrumented",
                )
                self.assertFalse(
                    any(
                        event[0] == "path-resolve"
                        and "/llm_staging_study3/" in event[1]
                        for event in events
                    ),
                    "immutable Study 3 import resolved a source ancestor",
                )
                self.assertTrue(
                    any(
                        event[0] == "path-stat" and "/.venv/" in event[1]
                        for event in events
                    ),
                    "in-worktree virtualenv metadata access was not exercised",
                )
                repo_text = os.path.normcase(os.path.normpath(os.fspath(_REPO_ROOT)))
                campaign_text = os.path.normcase(
                    os.path.normpath(os.fspath(_CAMPAIGN_ROOT))
                )
                for operation, candidate in events:
                    if operation == "realpath-component-lstat":
                        self.assertTrue(
                            _under(candidate, repo_text)
                            or _under(repo_text, candidate)
                            or _under(candidate, campaign_text)
                            or _under(campaign_text, candidate),
                            "realpath probed an unrelated ancestor/outside path",
                        )
        finally:
            shutil.rmtree(fixture_root, ignore_errors=True)
            for name in tuple(sys.modules):
                if (
                    name == prefix
                    or name.startswith(prefix + ".")
                    or name == staging_prefix
                    or name.startswith(staging_prefix + ".")
                ):
                    sys.modules.pop(name, None)
            sys.modules.update(prior_modules)
            sys.modules.update(prior_staging_modules)
            sys.modules.update(prior_dependency_modules)

    def test_symlinks_and_traversal_are_rejected_without_following_them(self) -> None:
        prefix = "scripts.mise_en_scene.llm_staging_study3b"
        prep_root = _REPO_ROOT / _PREP_RELATIVE
        fixture_root = prep_root / ("path-rejection-" + uuid.uuid4().hex)
        try:
            with _tripwire_no_outside_filesystem_access():
                isolation = importlib.import_module(prefix + ".isolation")
                os.makedirs(prep_root, exist_ok=True)
                with self.assertRaises(AssertionError):
                    _REPO_ROOT.parent.stat()
                with self.assertRaises(AssertionError):
                    _REPO_ROOT.parent.resolve()
                target = fixture_root / "safe" / "sentinel.txt"
                _write_fixture(target, b"synthetic sentinel")
                alias = fixture_root / "safe" / "alias.txt"
                alias.symlink_to(target)
                with self.assertRaises(isolation.BaselineScopeError):
                    isolation._read_project_file(
                        fixture_root, "safe/alias.txt"
                    )
                with self.assertRaises(AssertionError):
                    alias.stat()
                with self.assertRaises(AssertionError):
                    alias.lstat()
                with self.assertRaises(AssertionError):
                    alias.resolve()
                with self.assertRaises(ValueError):
                    isolation._read_project_file(fixture_root, "safe/../sentinel.txt")
                with self.assertRaises(isolation.PriorStudyMutationDenied):
                    isolation.assert_study3b_write_target(
                        alias, repository_root=fixture_root, action="append"
                    )
                self.assertEqual(
                    isolation._read_project_file(fixture_root, "safe/sentinel.txt"),
                    b"synthetic sentinel",
                )
        finally:
            shutil.rmtree(fixture_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
