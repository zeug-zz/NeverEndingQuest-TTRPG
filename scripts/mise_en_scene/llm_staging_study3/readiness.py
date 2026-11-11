# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3 readiness with an explicit GitHub provenance blocker.

Local ``gh pr checks --help`` exposes per-check name/state/workflow/link fields;
``gh run view --help`` exposes ``headSha`` and ``workflowDatabaseId`` for
workflow runs. These views do not expose a per-check app identity or bind every
required status check (including Advanced Security checks) to a trusted
workflow source and exact SHA. The raw CheckRun API path used by an earlier
draft requires ``gh api --repo``, which this installed CLI does not support;
omitting that flag would violate the repository's mandatory explicit-repository
rule. Until a supported, independently verifiable source is available,
readiness fails closed before GitHub credentials/network or local preflight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping

from . import protocol


GITHUB_REPOSITORY = "zeug-zz/NeverEndingQuest-TTRPG"
MAX_GATE_OUTPUT_BYTES = 32 * 1024 * 1024
GATE_TIMEOUT_SECONDS = 1800
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_NAME_RE = re.compile(r"^[a-z0-9-]{1,80}$")

# Historical check labels only; names and green states are not producer proof.
REQUIRED_CI_CHECK_NAMES: tuple[str, ...] = (
    "ascii-check",
    "dependency-scan",
    "sast-semgrep",
    "frontend-dependency-audit",
    "secret-scan",
    "Analyze (actions)",
    "Analyze (javascript-typescript)",
    "Analyze (python)",
    "sast-bandit",
    "CodeQL",
    "Semgrep OSS",
)

CI_PROVENANCE_BLOCKER_CODES = (
    "GITHUB_CI_APP_ID_AND_SLUG_NOT_EXPOSED_BY_SUPPORTED_GH_JSON_FIELDS",
    "GITHUB_CI_HEAD_SHA_NOT_EXPOSED_FOR_ALL_REQUIRED_CHECKS",
    "GITHUB_CI_WORKFLOW_PATH_NOT_BINDABLE_TO_EACH_CHECK",
    "GITHUB_CI_ADVANCED_SECURITY_RUN_IDENTITY_NOT_EXPOSED_BY_SUPPORTED_GH_CLI",
    "GITHUB_CI_CHECK_RUN_API_UNAVAILABLE_WITH_REQUIRED_GH_REPO_FLAG",
)

REQUIRED_PREFLIGHT_GATE_IDS = (
    "focused-study3-tests",
    "full-mise-en-scene-tests",
    "mapping-pilot-tests",
    "ascii-compliance",
    "study3-openspec-strict",
    "study2-openspec-strict",
    "frozen-study1-study2-inventory",
)
REQUIRED_PREFLIGHT_GATE_COMMANDS: Mapping[str, tuple[str, ...]] = {
    "focused-study3-tests": (
        ".venv/bin/python",
        "scripts/test_mise_en_scene_llm_staging_study3.py",
    ),
    "full-mise-en-scene-tests": (
        ".venv/bin/python",
        "-m",
        "unittest",
        "discover",
        "-s",
        "scripts",
        "-p",
        "test_mise_en_scene_*.py",
    ),
    "mapping-pilot-tests": (
        ".venv/bin/python",
        "-m",
        "unittest",
        "discover",
        "-s",
        "scripts",
        "-p",
        "test_mapping_pilot_*.py",
    ),
    "ascii-compliance": (
        "python3",
        "scripts/check_ascii_compliance.py",
        "--summary-only",
    ),
    "study3-openspec-strict": (
        "openspec",
        "validate",
        "v2-mise-en-scene-study3-contract-parity",
        "--strict",
    ),
    "study2-openspec-strict": (
        "openspec",
        "validate",
        "v2-mise-en-scene-authoring-projection-evaluation",
        "--strict",
    ),
    "frozen-study1-study2-inventory": (
        ".venv/bin/python",
        "scripts/mise_en_scene/llm_staging_study3/frozen_inventory.py",
    ),
}

if sys.platform == "darwin":
    _TRUSTED_TOOL_DIRECTORIES = (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    )
elif os.name == "nt":
    _TRUSTED_TOOL_DIRECTORIES = (
        r"C:\Program Files\GitHub CLI",
        r"C:\Program Files\nodejs",
        r"C:\Windows\System32",
    )
else:
    _TRUSTED_TOOL_DIRECTORIES = ("/usr/local/bin", "/usr/bin", "/bin")
TRUSTED_EXECUTABLE_PATH = os.pathsep.join(_TRUSTED_TOOL_DIRECTORIES)
LIVE_DISPATCH_ENABLED = False


class ReadinessVerificationError(RuntimeError):
    """Metadata-only refusal from a readiness source or local gate."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReadinessVerification:
    """Safe readiness summary carrying a private in-process proof marker."""

    status: str
    reason_codes: tuple[str, ...]
    current_head_sha: str | None
    ci_check_count: int
    preflight_gate_count: int
    external_provenance_verified: bool = False
    live_dispatch_permitted: bool = False
    _proof: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _PreflightSummary:
    started_at: str
    completed_at: str
    checks: tuple[dict[str, Any], ...]
    gate_failures: tuple[str, ...]
    infrastructure_failures: tuple[str, ...]


_READY_PROOF = object()


def is_verified_readiness(value: object) -> bool:
    """Return true only for an object issued by a fresh successful verifier."""

    return (
        type(value) is ReadinessVerification
        and value._proof is _READY_PROOF
        and value.status == "READY"
        and value.external_provenance_verified is True
        and value.live_dispatch_permitted is True
        and value.reason_codes == ()
    )


def verify_readiness_evidence() -> ReadinessVerification:
    """Return a fail-closed result until supported CI provenance is available."""

    try:
        current_head, status = _read_local_git_state()
    except ReadinessVerificationError as error:
        return _blocked((error.code,), None)
    if status:
        return _blocked(("LOCAL_WORKTREE_NOT_CLEAN",), current_head)
    return _blocked(CI_PROVENANCE_BLOCKER_CODES, current_head)


def _blocked(
    reason_codes: tuple[str, ...],
    current_head: str | None,
) -> ReadinessVerification:
    return ReadinessVerification(
        status="BLOCKED",
        reason_codes=tuple(sorted(set(reason_codes))) or ("READINESS_NOT_VERIFIED",),
        current_head_sha=current_head,
        ci_check_count=0,
        preflight_gate_count=0,
        external_provenance_verified=False,
        live_dispatch_permitted=False,
    )


def _read_local_git_state() -> tuple[str, bytes]:
    head = _git_read("rev-parse", "--verify", "HEAD")
    status = _git_read(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    try:
        head_sha = head.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ReadinessVerificationError("LOCAL_GIT_HEAD_INVALID") from None
    if _SHA1_RE.fullmatch(head_sha) is None:
        raise ReadinessVerificationError("LOCAL_GIT_HEAD_INVALID")
    return head_sha, status


def _git_read(*arguments: str) -> bytes:
    executable = _resolve_trusted_executable("git")
    if executable is None:
        raise ReadinessVerificationError("TRUSTED_GIT_UNAVAILABLE")
    try:
        result = _run_process(
            (executable, *arguments),
            cwd=protocol.REPO_ROOT,
            timeout=10,
            env=_base_child_environment(),
        )
    except ReadinessVerificationError:
        raise
    if result.returncode != 0 or type(result.stdout) is not bytes:
        raise ReadinessVerificationError("LOCAL_GIT_STATE_UNAVAILABLE")
    return result.stdout


def _run_provider_free_preflight(subject_sha: str) -> _PreflightSummary:
    started_at = _utc_now()
    checks: list[dict[str, Any]] = []
    gate_failures: list[str] = []
    infrastructure_failures: list[str] = []
    for gate_id in REQUIRED_PREFLIGHT_GATE_IDS:
        if _SAFE_NAME_RE.fullmatch(gate_id) is None:
            raise ReadinessVerificationError("PREFLIGHT_GATE_ID_INVALID")
        reason_suffix = gate_id.upper().replace("-", "_")
        try:
            result = _run_preflight_command(gate_id)
            if (
                type(result) is not _CommandResult
                or type(result.returncode) is not int
                or type(result.stdout) is not bytes
                or type(result.stderr) is not bytes
                or len(result.stdout) > MAX_GATE_OUTPUT_BYTES
                or len(result.stderr) > MAX_GATE_OUTPUT_BYTES
            ):
                raise ReadinessVerificationError("PREFLIGHT_COMMAND_RESULT_INVALID")
        except ReadinessVerificationError as error:
            code = "PREFLIGHT_INFRASTRUCTURE_FAILURE_" + reason_suffix
            infrastructure_failures.append(code)
            checks.append(
                {
                    "gate_id": gate_id,
                    "argv": list(REQUIRED_PREFLIGHT_GATE_COMMANDS[gate_id]),
                    "exit_code": None,
                    "stdout_sha256": None,
                    "stderr_sha256": None,
                    "failure_code": error.code,
                }
            )
        except Exception:
            infrastructure_failures.append(
                "PREFLIGHT_INFRASTRUCTURE_FAILURE_" + reason_suffix
            )
            checks.append(
                {
                    "gate_id": gate_id,
                    "argv": list(REQUIRED_PREFLIGHT_GATE_COMMANDS[gate_id]),
                    "exit_code": None,
                    "stdout_sha256": None,
                    "stderr_sha256": None,
                    "failure_code": "COMMAND_EXECUTION_FAILED",
                }
            )

        else:
            check_row = {
                "gate_id": gate_id,
                "argv": list(REQUIRED_PREFLIGHT_GATE_COMMANDS[gate_id]),
                "exit_code": result.returncode,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            }
            checks.append(check_row)
            if result.returncode != 0:
                gate_failures.append("PREFLIGHT_GATE_FAILED_" + reason_suffix)

        # A gate can mutate the checkout even when it exits unsuccessfully or
        # raises. Recheck after every attempted gate before allowing another
        # command to run, so no downstream result can be attached to a changed
        # or dirty subject tree.
        try:
            current_head, status = _read_local_git_state()
        except ReadinessVerificationError as error:
            infrastructure_failures.append(error.code)
            break
        if current_head != subject_sha or status:
            infrastructure_failures.append("LOCAL_GIT_STATE_CHANGED_DURING_PREFLIGHT")
            break

    if len(checks) != len(REQUIRED_PREFLIGHT_GATE_IDS):
        infrastructure_failures.append("PREFLIGHT_GATE_SET_INCOMPLETE")
    return _PreflightSummary(
        started_at=started_at,
        completed_at=_utc_now(),
        checks=tuple(checks),
        gate_failures=tuple(sorted(set(gate_failures))),
        infrastructure_failures=tuple(sorted(set(infrastructure_failures))),
    )


def _run_preflight_command(gate_id: str) -> _CommandResult:
    canonical_argv = REQUIRED_PREFLIGHT_GATE_COMMANDS.get(gate_id)
    if canonical_argv is None or not canonical_argv:
        raise ReadinessVerificationError("PREFLIGHT_GATE_NOT_ALLOWLISTED")
    executable = canonical_argv[0]
    if executable == ".venv/bin/python":
        candidate = protocol.REPO_ROOT / executable
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except OSError:
            raise ReadinessVerificationError("PROJECT_PYTHON_UNAVAILABLE") from None
        if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
            raise ReadinessVerificationError("PROJECT_PYTHON_UNAVAILABLE")
        actual_executable = str(resolved)
    else:
        actual_executable = _resolve_trusted_executable(executable)
        if actual_executable is None:
            raise ReadinessVerificationError("TRUSTED_PREFLIGHT_TOOL_UNAVAILABLE")
    actual_argv = (actual_executable, *canonical_argv[1:])
    env = _preflight_child_environment()
    if gate_id in {
        "focused-study3-tests",
        "full-mise-en-scene-tests",
        "mapping-pilot-tests",
    }:
        env["PYTHONPATH"] = "."
    if gate_id in {"study3-openspec-strict", "study2-openspec-strict"}:
        env["OPENSPEC_TELEMETRY"] = "0"
        env["DO_NOT_TRACK"] = "1"
    return _run_process(
        actual_argv,
        cwd=protocol.REPO_ROOT,
        timeout=GATE_TIMEOUT_SECONDS,
        env=env,
    )


def _run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str],
) -> _CommandResult:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise ReadinessVerificationError("EXTERNAL_COMMAND_TIMEOUT") from None
    except (OSError, subprocess.SubprocessError):
        raise ReadinessVerificationError("EXTERNAL_COMMAND_UNAVAILABLE") from None
    if type(result.returncode) is not int:
        raise ReadinessVerificationError("EXTERNAL_COMMAND_RESULT_INVALID")
    if type(result.stdout) is not bytes or type(result.stderr) is not bytes:
        raise ReadinessVerificationError("EXTERNAL_COMMAND_RESULT_INVALID")
    return _CommandResult(result.returncode, result.stdout, result.stderr)


def _resolve_trusted_executable(name: str) -> str | None:
    if type(name) is not str or _SAFE_NAME_RE.fullmatch(name) is None:
        return None
    candidate = shutil.which(name, path=TRUSTED_EXECUTABLE_PATH)
    if candidate is None:
        return None
    try:
        resolved = Path(candidate).resolve(strict=True)
        metadata = resolved.stat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
        or metadata.st_mode & 0o022
        or resolved.is_relative_to(protocol.REPO_ROOT)
    ):
        return None
    return str(resolved)


def _base_child_environment() -> dict[str, str]:
    home = _user_home()
    return {
        "PATH": TRUSTED_EXECUTABLE_PATH,
        "HOME": home,
        "LC_ALL": "C",
        "LANG": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _preflight_child_environment() -> dict[str, str]:
    home = _user_home()
    return {
        "PATH": TRUSTED_EXECUTABLE_PATH,
        "HOME": home,
        "XDG_CONFIG_HOME": str(Path(home) / ".config"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
        "LC_ALL": "C",
        "LANG": "C",
        "TERM": "dumb",
    }


def _user_home() -> str:
    if hasattr(os, "getuid"):
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            home = ""
        if home:
            return home
    try:
        return str(Path.home())
    except (RuntimeError, OSError):
        raise ReadinessVerificationError("USER_HOME_UNAVAILABLE") from None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def main(argv: list[str] | None = None) -> int:
    """Print local HEAD and the fail-closed CI provenance blockers."""

    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        result = {
            "status": "BLOCKED",
            "reason_codes": ["READINESS_ARGUMENTS_NOT_ACCEPTED"],
        }
        print(_canonical_bytes(result).decode("ascii"))
        return 2
    verification = verify_readiness_evidence()
    result = {
        "status": verification.status,
        "reason_codes": list(verification.reason_codes),
        "current_head_sha": verification.current_head_sha,
        "ci_check_count": verification.ci_check_count,
        "preflight_gate_count": verification.preflight_gate_count,
        "external_provenance_verified": verification.external_provenance_verified,
        "live_dispatch_permitted": verification.live_dispatch_permitted,
    }
    print(_canonical_bytes(result).decode("ascii"))
    return 0 if is_verified_readiness(verification) else 1


__all__ = [
    "CI_PROVENANCE_BLOCKER_CODES",
    "GITHUB_REPOSITORY",
    "LIVE_DISPATCH_ENABLED",
    "REQUIRED_CI_CHECK_NAMES",
    "REQUIRED_PREFLIGHT_GATE_COMMANDS",
    "REQUIRED_PREFLIGHT_GATE_IDS",
    "ReadinessVerification",
    "ReadinessVerificationError",
    "is_verified_readiness",
    "main",
    "verify_readiness_evidence",
]
