# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free AST inventory and tripwire for production text-chat transport.

The inventory includes Chat Completions, its raw-response variant, and the
Responses API because each can issue text-model requests outside the facade.
Image, audio, and speech SDK calls are separate media transports and are not
part of this chat contract.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Avoid creating bytecode outside the explicitly-owned G6 scratch tree.
sys.dont_write_bytecode = True

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()


# These are repository documentation, scratch, environment, and test roots,
# not production executable source. Root-only names are kept separate so a
# nested production package named "docs" or "plans" is not silently hidden.
_ROOT_EXCLUDED_DIRECTORIES = frozenset(
    {"docs", "plans", "openspec", "memory-bank", "docs-history", "tmp"}
)
_ANY_LEVEL_EXCLUDED_DIRECTORIES = frozenset(
    {".venv", "venv", "node_modules", ".git", "__pycache__", "tests"}
)

# Explicit non-test_ helpers/runners that contain test-only infrastructure.
# combat_latency_fixtures.py is intentionally not excluded: capture/operator
# scripts import it, so it remains in the executable production scan.
_TEST_SUPPORT_FILES = frozenset(
    {
        "scripts/core_chat_test_safety.py",
        "scripts/combat_tactical_test_support.py",
        "scripts/c5_regression_combat.py",
    }
)

# All supported text-generation SDK entry points are included. The raw
# response and Responses API forms are included so future transport variants
# cannot bypass the tripwire; non-chat media namespaces are not matched.
_CHAT_CALL_SUFFIXES = (
    ("chat", "completions", "create"),
    ("chat", "completions", "with_raw_response", "create"),
    ("responses", "create"),
)

_ALLOWED_RAW_CALLS = {
    "utils/llm_router.py": frozenset({"LLMRouter.call"}),
    "utils/provider_response_recovery.py": frozenset(
        {"request_chat_completion_with_recovery"}
    ),
}

_REQUIRED_PRODUCTION_FILES = frozenset(
    {
        "utils/action_predictor.py",
        "web/web_interface.py",
        "core/generators/area_generator.py",
        "scripts/run_critical_narrative_repair.py",
    }
)

_MIXED_PURPOSE_FUNCTIONS = {
    "utils/action_predictor.py": ("predict_actions_required",),
    "web/web_interface.py": (
        "fetch_npc_descriptions.generate_descriptions",
        "_generate_toolkit_npc_description",
    ),
}

_G6_SCRATCH = ROOT / "tmp" / "router-rollout" / "g6"


@dataclass(frozen=True, order=True)
class ChatCallsite:
    """An executable text-chat SDK call in source order-independent form."""

    path: str
    function: str
    line: int


class _ChatAstVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.scopes: list[str] = []
        self.function_depth = 0
        self.callsites: list[ChatCallsite] = []
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def _visit_function_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        for type_parameter in getattr(node, "type_params", ()):
            self.visit(type_parameter)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)
        self.scopes.append(node.name)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_header(node)
        self.scopes.append(node.name)
        self.function_depth += 1
        qualified_name = ".".join(self.scopes)
        self.functions[qualified_name] = node
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.function_depth -= 1
            self.scopes.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_header(node)
        self.scopes.append(node.name)
        self.function_depth += 1
        qualified_name = ".".join(self.scopes)
        self.functions[qualified_name] = node
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.function_depth -= 1
            self.scopes.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if _is_chat_transport_call(node):
            function = ".".join(self.scopes) if self.function_depth else "<module>"
            self.callsites.append(
                ChatCallsite(self.relative_path, function, node.lineno)
            )
        self.generic_visit(node)


def _call_name_parts(node: ast.expr) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def _is_chat_transport_call(node: ast.Call) -> bool:
    parts = _call_name_parts(node.func)
    return any(
        len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix
        for suffix in _CHAT_CALL_SUFFIXES
    )


def _analyze_source(relative_path: str, source: str) -> _ChatAstVisitor:
    visitor = _ChatAstVisitor(relative_path)
    visitor.visit(ast.parse(source, filename=relative_path))
    return visitor


def _is_test_file(relative_path: str) -> bool:
    return Path(relative_path).name.startswith("test_") and relative_path.endswith(
        ".py"
    )


def _has_archive_component(relative_path: str) -> bool:
    return any("archive" in part.casefold() for part in Path(relative_path).parts)


def _git_ignored_archive_files(root: Path, relative_paths: list[str]) -> set[str]:
    candidates = sorted(path for path in relative_paths if _has_archive_component(path))
    if not candidates:
        return set()

    payload = "\0".join(candidates) + "\0"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=root,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            "git check-ignore failed while filtering ignored archive trees: "
            + result.stderr.strip()
        )
    return {path for path in result.stdout.split("\0") if path}


def _production_python_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for directory, child_directories, filenames in os.walk(root, topdown=True):
        current = Path(directory)
        relative_directory = current.relative_to(root)
        is_root = not relative_directory.parts
        excluded = _ANY_LEVEL_EXCLUDED_DIRECTORIES
        child_directories[:] = sorted(
            name
            for name in child_directories
            if name not in excluded
            and not (is_root and name in _ROOT_EXCLUDED_DIRECTORIES)
        )
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = current / filename
            relative_path = path.relative_to(root).as_posix()
            if _is_test_file(relative_path) or relative_path in _TEST_SUPPORT_FILES:
                continue
            files.append(path)

    relative_paths = [path.relative_to(root).as_posix() for path in files]
    ignored_archives = _git_ignored_archive_files(root, relative_paths)
    return sorted(
        path
        for path in files
        if path.relative_to(root).as_posix() not in ignored_archives
    )


def _production_inventory(root: Path = ROOT) -> tuple[list[ChatCallsite], set[str]]:
    root = root.resolve()
    files = _production_python_files(root)
    callsites: list[ChatCallsite] = []
    relative_paths: set[str] = set()
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        relative_paths.add(relative_path)
        visitor = _analyze_source(relative_path, path.read_text(encoding="utf-8"))
        callsites.extend(visitor.callsites)
    return sorted(callsites), relative_paths


def _format_callsites(callsites: list[ChatCallsite]) -> str:
    return "\n".join(
        "%s:%d (%s)" % (callsite.path, callsite.line, callsite.function)
        for callsite in sorted(callsites)
    )


def _disallowed_callsites(callsites: list[ChatCallsite]) -> list[ChatCallsite]:
    return [
        callsite
        for callsite in callsites
        if callsite.function
        not in _ALLOWED_RAW_CALLS.get(callsite.path, frozenset())
    ]


def _assert_only_allowlisted(callsites: list[ChatCallsite]) -> None:
    offenders = _disallowed_callsites(callsites)
    if offenders:
        raise AssertionError(
            "raw production chat transport outside allowlist:\n"
            + _format_callsites(offenders)
        )


def _function_nodes(relative_path: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    return _analyze_source(relative_path, source).functions


def _calls_in(function: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(function) if isinstance(node, ast.Call)]


def _is_facade_call(node: ast.Call) -> bool:
    return _call_name_parts(node.func) == ("llm", "call")


class ProductionChatTripwire(unittest.TestCase):
    def test_fresh_production_inventory_is_exactly_the_transport_allowlist(self):
        inventory, scanned_paths = _production_inventory()
        _assert_only_allowlisted(inventory)
        print("Production Python files scanned: %d" % len(scanned_paths))
        print("Raw chat callsites inventoried: %d" % len(inventory))

        actual_owners = {(call.path, call.function) for call in inventory}
        expected_owners = {
            (path, function)
            for path, functions in _ALLOWED_RAW_CALLS.items()
            for function in functions
        }
        missing = sorted(expected_owners - actual_owners)
        extra = sorted(actual_owners - expected_owners)
        self.assertEqual(
            actual_owners,
            expected_owners,
            "production chat owner inventory mismatch; missing=%r extra=%r"
            % (missing, extra),
        )

    def test_required_mixed_purpose_and_operator_sources_stay_in_scan_scope(self):
        _, scanned_paths = _production_inventory()
        self.assertTrue(
            _REQUIRED_PRODUCTION_FILES.issubset(scanned_paths),
            "production scope omitted required source files: %r"
            % sorted(_REQUIRED_PRODUCTION_FILES - scanned_paths),
        )

    def test_mixed_purpose_text_chat_uses_the_facade(self):
        for relative_path, function_names in _MIXED_PURPOSE_FUNCTIONS.items():
            functions = _function_nodes(relative_path)
            for function_name in function_names:
                with self.subTest(owner=relative_path + "::" + function_name):
                    self.assertIn(function_name, functions)
                    calls = _calls_in(functions[function_name])
                    self.assertTrue(
                        any(_is_facade_call(call) for call in calls),
                        "%s::%s must route its text chat through llm.call"
                        % (relative_path, function_name),
                    )
                    self.assertFalse(
                        any(_is_chat_transport_call(call) for call in calls),
                        "%s::%s contains raw chat transport"
                        % (relative_path, function_name),
                    )

    def test_negative_fixture_reports_path_line_and_ignores_docstrings_and_media(self):
        source = '''"""Example only: client.chat.completions.create(model="x", messages=[])."""
# client.chat.completions.create(model="comment", messages=[])
def injected_direct_chat():
    client.chat.completions.create(model="x", messages=[])

def documentation_only():
    """client.chat.completions.create(model="docstring", messages=[])."""
    pass

def image_generation():
    client.images.generate(prompt="portrait")

def audio_generation():
    client.audio.speech.create(model="x", voice="alloy", input="prompt")
'''
        with tempfile.TemporaryDirectory(
            prefix="tripwire-fixture-", dir=_G6_SCRATCH
        ) as scratch_directory:
            fixture = Path(scratch_directory) / "production_offender.py"
            fixture.write_text(source, encoding="utf-8")
            relative_path = fixture.relative_to(ROOT).as_posix()
            found = _analyze_source(
                relative_path, fixture.read_text(encoding="utf-8")
            ).callsites

        expected = [ChatCallsite(relative_path, "injected_direct_chat", 4)]
        self.assertEqual(found, expected)
        with self.assertRaises(AssertionError) as failure:
            _assert_only_allowlisted(found)
        expected_report = (
            "raw production chat transport outside allowlist:\n"
            + "%s:4 (injected_direct_chat)" % relative_path
        )
        self.assertEqual(str(failure.exception), expected_report)
        print("Expected tripwire failure output:\n" + str(failure.exception))

    def test_raw_response_and_responses_api_variants_are_inventoried(self):
        source = '''
def raw_response_variant():
    client.chat.completions.with_raw_response.create(model="x", messages=[])

def responses_api_variant():
    client.responses.create(model="x", input="prompt")
'''
        found = _analyze_source("fixture/variants.py", source).callsites
        self.assertEqual(
            found,
            [
                ChatCallsite("fixture/variants.py", "raw_response_variant", 3),
                ChatCallsite("fixture/variants.py", "responses_api_variant", 6),
            ],
        )

    def test_validator_backup_is_absent_and_not_an_allowlist_exception(self):
        backup = "core/validation/character_validator_backup.py"
        self.assertFalse((ROOT / backup).exists(), backup + " must remain deleted")
        self.assertNotIn(backup, _ALLOWED_RAW_CALLS)

    def test_process_tripwires_remain_untouched(self):
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
