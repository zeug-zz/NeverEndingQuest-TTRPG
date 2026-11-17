# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Validate comparison-only tool and application source identities."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_A_ROLE = "frozen-origin-main"
APPLICATION_A_SHA = "f4f49b9ddece4adea10b7bdb4db9a1358b208b0d"
APPLICATION_A_TREE = "09e203e38d57ced35f7b4200fc3af105fcbd388e"
APPLICATION_B_ROLE = "pre-105-control"
APPLICATION_B_SHA = "5999af374ded4f56b21b25d68fc10f9520444b51"
APPLICATION_B_TREE = "e1a257b8a937418145bd86a50ef51d3cae382fac"

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_IDENTITY_KEYS = {"schema_version", "mode", "tool", "application"}
_TOOL_KEYS = {"sha", "tree"}
_APPLICATION_KEYS = {"role", "sha", "tree"}
_APPLICATIONS = {
    APPLICATION_A_ROLE: (APPLICATION_A_SHA, APPLICATION_A_TREE),
    APPLICATION_B_ROLE: (APPLICATION_B_SHA, APPLICATION_B_TREE),
}
_APPLICATION_WORKTREES = {
    APPLICATION_A_ROLE: Path("tmp/fr11-compare-f4f49b9d"),
    APPLICATION_B_ROLE: Path("tmp/fr11-compare-5999af37"),
}
# These exact untracked artifacts are unrelated to the frozen preflight tool
# and are not imported or read by its execution path. Any other untracked path,
# especially a tool/runtime source or data path, remains a dirty checkout.
_SAFE_UNTRACKED_TOOL_PATHS = frozenset(
    {
        "plans/references/neq-overseer-lifecycle.md",
        "plans/relay-plan.md",
        "plans/skill.md",
        "scripts/run_overseer_watcher.py",
        "scripts/test_overseer_watcher.py",
    }
)


class ComparisonIdentityError(ValueError):
    """Raised when an explicit comparison-only source binding is invalid."""


def build_comparison_identity(
    *,
    tool_sha: str,
    tool_tree: str,
    application_sha: str,
    application_tree: str,
) -> dict[str, Any]:
    """Return the strict identity envelope for one comparison execution."""
    if not isinstance(application_sha, str) or not isinstance(application_tree, str):
        raise ComparisonIdentityError("comparison_identity_sha_invalid")
    role = _application_role(application_sha, application_tree)
    value = {
        "schema_version": 1,
        "mode": "comparison-only",
        "tool": {"sha": tool_sha, "tree": tool_tree},
        "application": {
            "role": role,
            "sha": application_sha,
            "tree": application_tree,
        },
    }
    return validate_comparison_identity(value)


def validate_comparison_identity(
    value: Any,
    *,
    expected_application_sha: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize one comparison-only tool/application binding."""
    if not isinstance(value, Mapping) or set(value) != _IDENTITY_KEYS:
        raise ComparisonIdentityError("comparison_identity_shape_invalid")
    tool = value.get("tool")
    application = value.get("application")
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("mode") != "comparison-only"
        or not isinstance(tool, Mapping)
        or set(tool) != _TOOL_KEYS
        or not isinstance(application, Mapping)
        or set(application) != _APPLICATION_KEYS
    ):
        raise ComparisonIdentityError("comparison_identity_shape_invalid")

    tool_sha = tool.get("sha")
    tool_tree = tool.get("tree")
    application_sha = application.get("sha")
    application_tree = application.get("tree")
    role = application.get("role")
    if (
        not isinstance(tool_sha, str)
        or _SHA1.fullmatch(tool_sha) is None
        or not isinstance(tool_tree, str)
        or _SHA1.fullmatch(tool_tree) is None
        or not isinstance(application_sha, str)
        or _SHA1.fullmatch(application_sha) is None
        or not isinstance(application_tree, str)
        or _SHA1.fullmatch(application_tree) is None
        or not isinstance(role, str)
        or role not in _APPLICATIONS
    ):
        raise ComparisonIdentityError("comparison_identity_sha_invalid")

    expected_sha, expected_tree = _APPLICATIONS[role]
    if application_sha != expected_sha:
        raise ComparisonIdentityError("comparison_application_commit_mismatch")
    if application_tree != expected_tree:
        raise ComparisonIdentityError("comparison_application_tree_mismatch")
    if (
        expected_application_sha is not None
        and application_sha != expected_application_sha
    ):
        raise ComparisonIdentityError("comparison_source_sha_mismatch")
    if tool_sha in {APPLICATION_A_SHA, APPLICATION_B_SHA}:
        raise ComparisonIdentityError("comparison_tool_commit_not_separate")
    return {
        "schema_version": 1,
        "mode": "comparison-only",
        "tool": {"sha": tool_sha, "tree": tool_tree},
        "application": {
            "role": role,
            "sha": application_sha,
            "tree": application_tree,
        },
    }


def application_snapshot_path(identity: Any) -> Path:
    """Resolve the fixed local application worktree without following links."""
    normalized = validate_comparison_identity(identity)
    root = PROJECT_ROOT.resolve(strict=True)
    tmp_root = root / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise ComparisonIdentityError("comparison_tmp_unavailable_or_unsafe")
    relative = _APPLICATION_WORKTREES[normalized["application"]["role"]]
    candidate = root / relative
    cursor = root
    try:
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ComparisonIdentityError("comparison_application_path_unsafe")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(tmp_root.resolve(strict=True))
    except ComparisonIdentityError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ComparisonIdentityError(
            "comparison_application_path_unavailable"
        ) from exc
    if not resolved.is_dir():
        raise ComparisonIdentityError("comparison_application_path_unavailable")
    return resolved


def verify_application_worktree(identity: Any) -> Path:
    """Verify the pre-existing local worktree against its pinned commit/tree."""
    normalized = validate_comparison_identity(identity)
    root = application_snapshot_path(normalized)
    _verify_worktree_admin_path(root)
    expected_sha = normalized["application"]["sha"]
    expected_tree = normalized["application"]["tree"]
    observed_root = _git_output(root, ("rev-parse", "--show-toplevel"))
    observed_sha = _git_output(root, ("rev-parse", "HEAD"))
    observed_tree = _git_output(root, ("rev-parse", "HEAD^{tree}"))
    status = _git_output(root, ("status", "--porcelain", "--untracked-files=all"))
    if (
        Path(observed_root).resolve(strict=True) != root
        or observed_sha != expected_sha
    ):
        raise ComparisonIdentityError("comparison_application_commit_mismatch")
    if observed_tree != expected_tree:
        raise ComparisonIdentityError("comparison_application_tree_mismatch")
    if status:
        raise ComparisonIdentityError("comparison_application_worktree_dirty")
    return root


def verify_tool_tree(tool_sha: str, tool_tree: str, *, project_root: Path) -> None:
    """Require the current feature tool checkout to match its frozen identity."""
    if (
        not isinstance(tool_sha, str)
        or _SHA1.fullmatch(tool_sha) is None
        or not isinstance(tool_tree, str)
        or _SHA1.fullmatch(tool_tree) is None
    ):
        raise ComparisonIdentityError("comparison_tool_identity_invalid")
    observed_sha = _git_output(project_root, ("rev-parse", "HEAD"))
    observed_tree = _git_output(project_root, ("rev-parse", "HEAD^{tree}"))
    status = _git_output(
        project_root,
        ("status", "--porcelain=v1", "--untracked-files=all", "-z"),
    )
    if observed_sha != tool_sha:
        raise ComparisonIdentityError("comparison_tool_commit_mismatch")
    if observed_tree != tool_tree:
        raise ComparisonIdentityError("comparison_tool_tree_mismatch")
    for record in status.split("\0"):
        if not record:
            continue
        if (
            not record.startswith("?? ")
            or record[3:] not in _SAFE_UNTRACKED_TOOL_PATHS
        ):
            raise ComparisonIdentityError("comparison_tool_worktree_dirty")


def _application_role(application_sha: str, application_tree: str) -> str:
    for role, (expected_sha, expected_tree) in _APPLICATIONS.items():
        if application_sha == expected_sha and application_tree == expected_tree:
            return role
    if application_sha in {item[0] for item in _APPLICATIONS.values()}:
        raise ComparisonIdentityError("comparison_application_tree_mismatch")
    raise ComparisonIdentityError("comparison_application_commit_mismatch")


def _verify_worktree_admin_path(worktree: Path) -> None:
    git_marker = worktree / ".git"
    if git_marker.is_symlink() or not git_marker.is_file():
        raise ComparisonIdentityError("comparison_application_worktree_invalid")
    try:
        raw = git_marker.read_bytes()
    except OSError as exc:
        raise ComparisonIdentityError(
            "comparison_application_worktree_invalid"
        ) from exc
    if (
        len(raw) > 512
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
        or b"\r" in raw
    ):
        raise ComparisonIdentityError("comparison_application_worktree_invalid")
    try:
        line = raw[:-1].decode("ascii")
    except UnicodeError as exc:
        raise ComparisonIdentityError(
            "comparison_application_worktree_invalid"
        ) from exc
    if (
        not line.startswith("gitdir: ")
        or line.endswith(" ")
        or "\n" in line
        or "\r" in line
    ):
        raise ComparisonIdentityError("comparison_application_worktree_invalid")
    git_dir_value = line[len("gitdir: ") :]
    git_dir = Path(git_dir_value)
    if not git_dir.is_absolute():
        git_dir = worktree / git_dir
    try:
        lexical_git_dir = Path(os.path.abspath(git_dir))
        lexical_relative = lexical_git_dir.relative_to(PROJECT_ROOT)
        cursor = PROJECT_ROOT
        for part in PurePosixPath(lexical_relative.as_posix()).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ComparisonIdentityError(
                    "comparison_application_worktree_invalid"
                )
    except (OSError, ValueError) as exc:
        raise ComparisonIdentityError(
            "comparison_application_worktree_invalid"
        ) from exc
    try:
        resolved_git_dir = git_dir.resolve(strict=True)
        allowed_root = (PROJECT_ROOT / ".git" / "worktrees").resolve(strict=True)
        resolved_git_dir.relative_to(allowed_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ComparisonIdentityError(
            "comparison_application_worktree_invalid"
        ) from exc
    cursor = PROJECT_ROOT
    try:
        relative = resolved_git_dir.relative_to(PROJECT_ROOT)
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ComparisonIdentityError(
                    "comparison_application_worktree_invalid"
                )
    except ValueError as exc:
        raise ComparisonIdentityError(
            "comparison_application_worktree_invalid"
        ) from exc


def _preflight_guard_active() -> bool:
    """True when this process runs under the preflight subprocess deny guard."""
    from scripts import live_gate_preflight_safety as safety

    try:
        safety.require_guard_active()
    except safety.NetworkGuardError:
        return False
    return True


def _git_output(cwd: Path, arguments: tuple[str, ...]) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    command = ["git", "-C", str(cwd), *arguments]
    run_options: dict[str, Any] = {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 10.0,
    }
    try:
        if _preflight_guard_active():
            # The deny guard rejects plain subprocess launches; use the sanctioned path.
            from scripts.live_gate_preflight_safety import run_guarded_subprocess

            completed = run_guarded_subprocess(
                command, cwd=PROJECT_ROOT, env=env, **run_options
            )
        else:
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, env=env, **run_options
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComparisonIdentityError("comparison_git_identity_unavailable") from exc
    if completed.returncode != 0:
        raise ComparisonIdentityError("comparison_git_identity_unavailable")
    return completed.stdout.rstrip("\n")
