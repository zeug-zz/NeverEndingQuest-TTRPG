# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Exact-head Study 3b readiness fence for primary-only dispatch.

The primary supplies the raw public GitHub CheckRuns JSON and its SHA-256 after
retrieval through context-mode. That retrieval is the provenance trust root;
the digest verifies the saved bytes, not their origin. Readiness itself is
provider-free and never opens the Study 3b ledger or reads OpenRouter secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Mapping

from . import isolation, ledger, protocol
from .isolation import (
    BASELINE_PATH_RELATIVE,
    PREP_ROOT_RELATIVE,
    STUDY3B_RUN_ROOT_RELATIVE,
)


GITHUB_REPOSITORY = "zeug-zz/NeverEndingQuest-TTRPG"
GITHUB_PR_NUMBER = 127
DISPATCH_RULING_ID = "neq-s-study3-adjudication-20261111"
RULING_CAMPAIGN_TREE_ROOT = Path(
    "/Users/zeug/Projects/NeverEndingQuest/.git/overseer-relay/campaigns/neq-current-build"
)
RULING_SOURCE_DIRECTORY = "rulings"
RULING_SOURCE_NAME = "B.md"
PINNED_RULING_SECTION_SHA256 = (
    "950ed79edc700cd1e81b58d9d8e1a43241c1348e975416cfeb324ff18b9917ca"
)
PINNED_PRIOR_STUDY_BASELINE_SHA256 = (
    "62065f978894fe2de246b20ad462ca07dc1df733af44f27c91b48fdd8672a8f2"
)
READINESS_TRUST_BOUNDARY = (
    "PRIMARY_CONTEXT_MODE_PUBLIC_GITHUB_CHECK_RUNS_RETRIEVAL_IS_TRUST_ROOT; "
    "SHA256_VERIFIES_BYTES_NOT_ORIGIN_AUTHENTICATION"
)

MAX_CI_EVIDENCE_BYTES = 1024 * 1024
MAX_CI_CHECK_RUNS = 64
MAX_CI_JSON_NODES = 20_000
MAX_CI_JSON_DEPTH = 12
MAX_CI_STRING_LENGTH = 8192
MAX_CI_RECORD_BYTES = 64 * 1024
MAX_GATE_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_READINESS_EVIDENCE_BYTES = 128 * 1024
MAX_RULING_SOURCE_BYTES = 4 * 1024 * 1024
MAX_CI_EVIDENCE_AGE_SECONDS = 15 * 60
GATE_TIMEOUT_SECONDS = 1800
GH_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_SECONDS = 10

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
_CI_APP_BY_CHECK: Mapping[str, tuple[str, str, int]] = {
    **{
        name: ("github-actions", "GitHub Actions", 15368)
        for name in REQUIRED_CI_CHECK_NAMES
        if name not in {"CodeQL", "Semgrep OSS"}
    },
    "CodeQL": ("github-advanced-security", "GitHub Advanced Security", 57789),
    "Semgrep OSS": ("github-advanced-security", "GitHub Advanced Security", 57789),
}
_REQUIRED_CI_APP_COUNTS = {"github-actions": 9, "github-advanced-security": 2}
_REQUIRED_CI_APP_IDS = {"github-actions": 15368, "github-advanced-security": 57789}

# Commands are fixed and provider-free. The venv executable is intentionally
# lexical: do not resolve its symlink before passing it to subprocess.
REQUIRED_PREFLIGHT_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "study3b-provider-free-tests",
        (
            ".venv/bin/python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_mise_en_scene_study3b_*.py",
        ),
    ),
    (
        "study3b-package-pycompile",
        (
            ".venv/bin/python",
            "-m",
            "py_compile",
            "scripts/mise_en_scene/llm_staging_study3b/__init__.py",
            "scripts/mise_en_scene/llm_staging_study3b/contract.py",
            "scripts/mise_en_scene/llm_staging_study3b/diagnostic.py",
            "scripts/mise_en_scene/llm_staging_study3b/hydration.py",
            "scripts/mise_en_scene/llm_staging_study3b/inventory.py",
            "scripts/mise_en_scene/llm_staging_study3b/isolation.py",
            "scripts/mise_en_scene/llm_staging_study3b/ledger.py",
            "scripts/mise_en_scene/llm_staging_study3b/newrequest.py",
            "scripts/mise_en_scene/llm_staging_study3b/preflight.py",
            "scripts/mise_en_scene/llm_staging_study3b/protocol.py",
            "scripts/mise_en_scene/llm_staging_study3b/runner.py",
        ),
    ),
    (
        "study3b-ascii-compliance",
        ("python3", "scripts/check_ascii_compliance.py", "--summary-only"),
    ),
    (
        "study3b-openspec-strict",
        (
            "openspec",
            "validate",
            "v2-mise-en-scene-study3b-hydration-parity",
            "--strict",
        ),
    ),
)

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(
    os, "O_CLOEXEC", 0
)
_FILE_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_TRUSTED_TOOL_DIRECTORIES = (
    ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
    if sys.platform == "darwin"
    else ("/usr/local/bin", "/usr/bin", "/bin")
)
_TRUSTED_EXECUTABLE_PATH = os.pathsep.join(_TRUSTED_TOOL_DIRECTORIES)
_READINESS_DIRECTORY_RELATIVE = PREP_ROOT_RELATIVE + "/readiness"
_READY_PROOF = object()
_RULING_REQUIRED_SCOPE = (
    b"Authorized next (routine corrected rerun, no owner ask):",
    b"Study 3b: same three scenes in the same order, same model and caps "
    b"(3 attempts, no retry or fallback, 16384 tokens, 720 s, about USD "
    b"0.012, ceiling 0.05), new study ID, after exact-head green CI and a "
    b"clean provider-free preflight.",
    b"Standing approvals apply.",
)


class ReadinessBlocked(RuntimeError):
    """Metadata-only refusal from Study 3b readiness."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _BaselinePin:
    evidence_sha256: str
    inventory_sha256: str
    file_count: int
    opaque_bytes_count: int
    files: tuple[dict[str, Any], ...] = field(repr=False)


@dataclass(frozen=True)
class _GateSummary:
    checks: tuple[dict[str, Any], ...]
    gate_failures: tuple[str, ...]
    infrastructure_failures: tuple[str, ...]
    inventory_sha256: str


@dataclass(frozen=True)
class ReadinessVerification:
    """Metadata-only preflight result with a private same-process proof."""

    status: str
    reason_codes: tuple[str, ...]
    study_id: str
    expected_head_sha: str | None
    current_head_sha: str | None
    ci_check_count: int
    preflight_gate_count: int
    external_provenance_verified: bool
    live_dispatch_permitted: bool
    ruling_id: str | None
    ruling_section_sha256: str | None
    ci_evidence_path: str | None
    ci_evidence_sha256: str | None
    evidence_relative_path: str | None
    evidence_sha256: str | None
    gate_failures: tuple[str, ...] = ()
    infrastructure_failures: tuple[str, ...] = ()
    _proof: object | None = field(default=None, repr=False, compare=False)


def is_verified_readiness(value: object) -> bool:
    """Return true only for a successful exact-head fence from this process."""

    return (
        type(value) is ReadinessVerification
        and value._proof is _READY_PROOF
        and value.status == "READY"
        and value.reason_codes == ()
        and value.study_id == protocol.STUDY_ID
        and value.external_provenance_verified is True
        and value.live_dispatch_permitted is True
        and type(value.expected_head_sha) is str
        and _SHA1_RE.fullmatch(value.expected_head_sha) is not None
        and value.current_head_sha == value.expected_head_sha
        and value.ci_check_count == len(REQUIRED_CI_CHECK_NAMES)
        and value.preflight_gate_count == len(REQUIRED_PREFLIGHT_COMMANDS)
        and value.ruling_id == DISPATCH_RULING_ID
        and value.ruling_section_sha256 == PINNED_RULING_SECTION_SHA256
        and type(value.ci_evidence_path) is str
        and type(value.ci_evidence_sha256) is str
        and _SHA256_RE.fullmatch(value.ci_evidence_sha256) is not None
        and type(value.evidence_relative_path) is str
        and type(value.evidence_sha256) is str
        and _SHA256_RE.fullmatch(value.evidence_sha256) is not None
        and value.gate_failures == ()
        and value.infrastructure_failures == ()
    )


def verify_live_readiness(
    *,
    expected_head_sha: object,
    ci_evidence_path: object,
    ci_evidence_sha256: object,
    dispatch_ruling_id: object,
) -> ReadinessVerification:
    """Run exact-head checks and persist metadata-only immutable evidence.

    The CI JSON and its digest must be supplied by the primary. The only
    accepted ruling ID is the already-authorized Study 3 adjudication; this
    function never requests or synthesizes a new owner approval.
    """

    current_head: str | None = None
    ci_summary: dict[str, Any] | None = None
    ruling_summary: dict[str, Any] | None = None
    pr_summary: dict[str, Any] | None = None
    baseline_pin: _BaselinePin | None = None
    gate_summary: _GateSummary | None = None
    ci_stat: os.stat_result | None = None
    ci_bytes: bytes | None = None
    external_provenance_verified = False
    reason_codes: list[str] = []

    try:
        _validate_inputs(
            expected_head_sha=expected_head_sha,
            ci_evidence_path=ci_evidence_path,
            ci_evidence_sha256=ci_evidence_sha256,
            dispatch_ruling_id=dispatch_ruling_id,
        )
        current_head, status = _read_local_git_state()
        if status:
            raise ReadinessBlocked("LOCAL_WORKTREE_NOT_CLEAN")
        if current_head != expected_head_sha:
            raise ReadinessBlocked("LOCAL_HEAD_SHA_MISMATCH")

        _validate_fixed_study_and_cost()
        _assert_fresh_run_root()
        ruling_summary = _verify_adjudication_ruling()
        ci_bytes, ci_stat = _read_ci_evidence(ci_evidence_path)
        if hashlib.sha256(ci_bytes).hexdigest() != ci_evidence_sha256:
            raise ReadinessBlocked("CI_EVIDENCE_SHA256_MISMATCH")
        ci_summary = _validate_check_runs(ci_bytes, expected_head_sha)
        external_provenance_verified = True
        pr_summary = _verify_pull_request_head(expected_head_sha)
        baseline_pin = _load_baseline_pin()
        _assert_baseline_unchanged(baseline_pin)
        gate_summary = _run_provider_free_preflight(
            expected_head_sha,
            baseline_pin,
        )
        reason_codes.extend(gate_summary.gate_failures)
        reason_codes.extend(gate_summary.infrastructure_failures)

        # Revalidate all evidence after the tests: no green result may be reused
        # for a different SHA, changed file, stale file, or moved PR head.
        final_ci_bytes, final_ci_stat = _read_ci_evidence(ci_evidence_path)
        if (
            final_ci_bytes != ci_bytes
            or hashlib.sha256(final_ci_bytes).hexdigest() != ci_evidence_sha256
            or _stat_identity(final_ci_stat) != _stat_identity(ci_stat)
        ):
            reason_codes.append("CI_EVIDENCE_CHANGED_DURING_PREFLIGHT")
        pr_summary = _verify_pull_request_head(expected_head_sha)
        _assert_baseline_unchanged(baseline_pin)
        current_head, status = _read_local_git_state()
        if status:
            reason_codes.append("LOCAL_WORKTREE_NOT_CLEAN_AFTER_PREFLIGHT")
        if current_head != expected_head_sha:
            reason_codes.append("LOCAL_HEAD_SHA_CHANGED_DURING_PREFLIGHT")
        _assert_fresh_run_root()
    except ReadinessBlocked as error:
        reason_codes.append(error.code)
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
        reason_codes.append("READINESS_VERIFICATION_FAILED_CLOSED")
    except Exception:
        reason_codes.append("READINESS_VERIFICATION_FAILED_CLOSED")

    reasons = tuple(sorted(set(reason_codes)))
    gates_passed = (
        gate_summary is not None
        and not gate_summary.gate_failures
        and not gate_summary.infrastructure_failures
        and len(gate_summary.checks) == len(REQUIRED_PREFLIGHT_COMMANDS)
    )
    ready = (
        not reasons
        and current_head == expected_head_sha
        and ci_summary is not None
        and ruling_summary is not None
        and pr_summary is not None
        and baseline_pin is not None
        and gates_passed
        and external_provenance_verified
    )
    record = _readiness_record(
        status="READY" if ready else "BLOCKED",
        expected_head_sha=(
            _safe_sha1(expected_head_sha)
        ),
        current_head_sha=current_head,
        dispatch_ruling_id=(
            dispatch_ruling_id if type(dispatch_ruling_id) is str else None
        ),
        ruling_summary=ruling_summary,
        ci_evidence_path=(
            _safe_ci_evidence_path(ci_evidence_path)
        ),
        ci_evidence_sha256=(
            _safe_sha256(ci_evidence_sha256)
        ),
        ci_summary=ci_summary,
        pr_summary=pr_summary,
        baseline_pin=baseline_pin,
        gate_summary=gate_summary,
        reason_codes=reasons,
        external_provenance_verified=external_provenance_verified,
    )
    try:
        evidence_relative_path, evidence_sha256 = _write_immutable_evidence(record)
    except Exception:
        evidence_relative_path = None
        evidence_sha256 = None
        if ready:
            ready = False
            reasons = ("READINESS_EVIDENCE_PERSIST_FAILED",)

    if ready:
        # Bind the in-memory dispatch proof to exact evidence and all pins. The
        # runner independently rechecks these immediately before ledger init.
        verification = ReadinessVerification(
            status="READY",
            reason_codes=(),
            study_id=protocol.STUDY_ID,
            expected_head_sha=expected_head_sha,
            current_head_sha=current_head,
            ci_check_count=len(REQUIRED_CI_CHECK_NAMES),
            preflight_gate_count=len(REQUIRED_PREFLIGHT_COMMANDS),
            external_provenance_verified=True,
            live_dispatch_permitted=True,
            ruling_id=DISPATCH_RULING_ID,
            ruling_section_sha256=PINNED_RULING_SECTION_SHA256,
            ci_evidence_path=ci_evidence_path,
            ci_evidence_sha256=ci_evidence_sha256,
            evidence_relative_path=evidence_relative_path,
            evidence_sha256=evidence_sha256,
            _proof=_READY_PROOF,
        )
        try:
            _verify_persisted_readiness_evidence(
                verification,
                ci_summary=ci_summary,
                pr_summary=pr_summary,
                ruling_summary=ruling_summary,
                baseline_pin=baseline_pin,
            )
            current_head, status = _read_local_git_state()
            if status:
                raise ReadinessBlocked("LOCAL_WORKTREE_NOT_CLEAN_AFTER_EVIDENCE")
            if current_head != expected_head_sha:
                raise ReadinessBlocked("LOCAL_HEAD_SHA_CHANGED_AFTER_EVIDENCE")
        except ReadinessBlocked as error:
            ready = False
            reasons = (error.code,)
        else:
            return verification

    return ReadinessVerification(
        status="BLOCKED",
        reason_codes=reasons or ("READINESS_NOT_VERIFIED",),
        study_id=protocol.STUDY_ID,
        expected_head_sha=(
            _safe_sha1(expected_head_sha)
        ),
        current_head_sha=current_head,
        ci_check_count=(
            ci_summary["required_check_count"] if ci_summary is not None else 0
        ),
        preflight_gate_count=(
            len(gate_summary.checks) if gate_summary is not None else 0
        ),
        external_provenance_verified=external_provenance_verified,
        live_dispatch_permitted=False,
        ruling_id=(
            DISPATCH_RULING_ID
            if dispatch_ruling_id == DISPATCH_RULING_ID
            else None
        ),
        ruling_section_sha256=(
            PINNED_RULING_SECTION_SHA256 if ruling_summary is not None else None
        ),
        ci_evidence_path=(
            _safe_ci_evidence_path(ci_evidence_path)
        ),
        ci_evidence_sha256=(
            _safe_sha256(ci_evidence_sha256)
        ),
        evidence_relative_path=evidence_relative_path,
        evidence_sha256=evidence_sha256,
        gate_failures=gate_summary.gate_failures if gate_summary is not None else (),
        infrastructure_failures=(
            gate_summary.infrastructure_failures if gate_summary is not None else ()
        ),
    )


def assert_dispatch_readiness_current(value: object) -> None:
    """Repeat the immediate dispatch boundary without reserving or dispatching."""

    if not is_verified_readiness(value):
        raise ReadinessBlocked("LIVE_READINESS_PROOF_REQUIRED")
    assert isinstance(value, ReadinessVerification)
    current_head, status = _read_local_git_state()
    if status:
        raise ReadinessBlocked("LOCAL_WORKTREE_NOT_CLEAN_BEFORE_LEDGER")
    if current_head != value.expected_head_sha:
        raise ReadinessBlocked("LOCAL_HEAD_SHA_MISMATCH_BEFORE_LEDGER")
    _validate_fixed_study_and_cost()
    ruling_summary = _verify_adjudication_ruling()
    _assert_fresh_run_root()
    raw, _metadata = _read_ci_evidence(value.ci_evidence_path)
    if hashlib.sha256(raw).hexdigest() != value.ci_evidence_sha256:
        raise ReadinessBlocked("CI_EVIDENCE_CHANGED_BEFORE_LEDGER")
    summary = _validate_check_runs(raw, value.expected_head_sha)
    if summary["required_check_count"] != len(REQUIRED_CI_CHECK_NAMES):
        raise ReadinessBlocked("CI_REQUIRED_CHECK_SET_INCOMPLETE")
    pr_summary = _verify_pull_request_head(value.expected_head_sha)
    baseline_pin = _load_baseline_pin()
    _assert_baseline_unchanged(baseline_pin)
    evidence_record = _verify_persisted_readiness_evidence(
        value,
        ci_summary=summary,
        pr_summary=pr_summary,
        ruling_summary=ruling_summary,
        baseline_pin=baseline_pin,
    )
    if (
        evidence_record["ci_evidence"].get("required_checks")
        != summary["required_checks"]
        or evidence_record["ci_evidence"].get("app_identities")
        != summary["app_identities"]
    ):
        raise ReadinessBlocked("READINESS_EVIDENCE_CI_BINDING_MISMATCH")
    current_head, status = _read_local_git_state()
    if status or current_head != value.expected_head_sha:
        raise ReadinessBlocked("LOCAL_GIT_STATE_CHANGED_BEFORE_LEDGER")
    _assert_fresh_run_root()


def _verify_persisted_readiness_evidence(
    value: ReadinessVerification,
    *,
    ci_summary: dict[str, Any],
    pr_summary: dict[str, Any],
    ruling_summary: dict[str, Any],
    baseline_pin: _BaselinePin,
) -> dict[str, Any]:
    if (
        type(value.evidence_relative_path) is not str
        or type(value.evidence_sha256) is not str
        or _SHA256_RE.fullmatch(value.evidence_sha256) is None
    ):
        raise ReadinessBlocked("READINESS_EVIDENCE_IDENTITY_INVALID")
    raw, _metadata = _read_preparation_file(
        value.evidence_relative_path,
        max_bytes=MAX_READINESS_EVIDENCE_BYTES,
        kind="READINESS_EVIDENCE",
    )
    if hashlib.sha256(raw).hexdigest() != value.evidence_sha256:
        raise ReadinessBlocked("READINESS_EVIDENCE_SHA256_MISMATCH")
    try:
        record = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        _validate_bounded_json(record)
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError, RecursionError):
        raise ReadinessBlocked("READINESS_EVIDENCE_JSON_INVALID") from None
    if type(record) is not dict:
        raise ReadinessBlocked("READINESS_EVIDENCE_JSON_INVALID")
    ci_evidence = record.get("ci_evidence")
    run_fence = record.get("run_fence")
    inventory = record.get("prior_study_inventory")
    checks = record.get("checks")
    expected_ci_url = (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/commits/"
        + value.expected_head_sha
        + "/check-runs?per_page=100"
    )
    if (
        record.get("schema") != "neq.llm_staging_study3b_exact_head_preflight.v1"
        or record.get("status") != "READY"
        or record.get("study_id") != protocol.STUDY_ID
        or record.get("repository") != GITHUB_REPOSITORY
        or record.get("head_sha") != value.expected_head_sha
        or record.get("current_head_sha") != value.expected_head_sha
        or record.get("trust_boundary") != READINESS_TRUST_BOUNDARY
        or record.get("reason_codes") != []
        or record.get("live_dispatch_permitted") is not True
        or record.get("ledger_initialized") is not False
        or record.get("credentials_loaded") is not False
        or record.get("http_dispatched") is not False
        or record.get("gate_failures") != []
        or record.get("infrastructure_failures") != []
        or type(ci_evidence) is not dict
        or ci_evidence.get("path") != value.ci_evidence_path
        or ci_evidence.get("sha256") != value.ci_evidence_sha256
        or ci_evidence.get("source_repository") != GITHUB_REPOSITORY
        or ci_evidence.get("pull_request_number") != GITHUB_PR_NUMBER
        or ci_evidence.get("source_url") != expected_ci_url
        or ci_evidence.get("retrieval_trust_root") != READINESS_TRUST_BOUNDARY
        or ci_evidence.get("external_provenance_verified") is not True
        or ci_evidence.get("required_check_count") != len(REQUIRED_CI_CHECK_NAMES)
        or ci_evidence.get("required_checks") != ci_summary["required_checks"]
        or ci_evidence.get("app_identities") != ci_summary["app_identities"]
        or type(run_fence) is not dict
        or run_fence.get("ruling_id") != DISPATCH_RULING_ID
        or run_fence.get("ruling_section_sha256") != PINNED_RULING_SECTION_SHA256
        or run_fence.get("study_id") != protocol.STUDY_ID
        or run_fence.get("manifest_sha256") != protocol.MANIFEST_SHA256
        or run_fence.get("protocol_sha256") != protocol.PROTOCOL_SHA256
        or run_fence.get("generation_config_sha256")
        != protocol.GENERATION_CONFIG_SHA256
        or run_fence.get("final_head_sha") != value.expected_head_sha
        or run_fence.get("attempt_cap") != len(protocol.SCENE_ORDER)
        or run_fence.get("attempts_per_scene") != 1
        or run_fence.get("scene_order") != list(protocol.SCENE_ORDER)
        or run_fence.get("hard_ceiling_usd") != "0.05"
        or record.get("approval_scope") != ruling_summary
        or record.get("pull_request") != pr_summary
        or type(inventory) is not dict
        or inventory.get("baseline_path") != BASELINE_PATH_RELATIVE
        or inventory.get("baseline_evidence_sha256") != baseline_pin.evidence_sha256
        or inventory.get("inventory_sha256") != baseline_pin.inventory_sha256
        or inventory.get("file_count") != baseline_pin.file_count
        or inventory.get("opaque_bytes_count") != baseline_pin.opaque_bytes_count
        or inventory.get("checked_before_and_after_each_gate") is not True
        or inventory.get("prior_study_reset_or_replay") is not False
        or type(checks) is not list
        or len(checks) != len(REQUIRED_PREFLIGHT_COMMANDS)
        or record.get("preflight_gate_count") != len(REQUIRED_PREFLIGHT_COMMANDS)
    ):
        raise ReadinessBlocked("READINESS_EVIDENCE_BINDING_MISMATCH")
    for check, (gate_id, command) in zip(checks, REQUIRED_PREFLIGHT_COMMANDS):
        if (
            type(check) is not dict
            or set(check)
            != {"gate_id", "argv", "exit_code", "stdout_sha256", "stderr_sha256"}
            or check.get("gate_id") != gate_id
            or check.get("argv") != list(command)
            or type(check.get("exit_code")) is not int
            or check.get("exit_code") != 0
            or type(check.get("stdout_sha256")) is not str
            or _SHA256_RE.fullmatch(check["stdout_sha256"]) is None
            or type(check.get("stderr_sha256")) is not str
            or _SHA256_RE.fullmatch(check["stderr_sha256"]) is None
        ):
            raise ReadinessBlocked("READINESS_EVIDENCE_PREFLIGHT_BINDING_MISMATCH")
    return record


def _validate_inputs(
    *,
    expected_head_sha: object,
    ci_evidence_path: object,
    ci_evidence_sha256: object,
    dispatch_ruling_id: object,
) -> None:
    if type(dispatch_ruling_id) is not str:
        raise ReadinessBlocked("EXACT_DISPATCH_RULING_ID_REQUIRED")
    if dispatch_ruling_id != DISPATCH_RULING_ID:
        raise ReadinessBlocked("DISPATCH_RULING_ID_MISMATCH")
    if type(expected_head_sha) is not str or _SHA1_RE.fullmatch(expected_head_sha) is None:
        raise ReadinessBlocked("EXACT_FINAL_HEAD_SHA_REQUIRED")
    if type(ci_evidence_path) is not str:
        raise ReadinessBlocked("CI_EVIDENCE_PATH_REQUIRED")
    if type(ci_evidence_sha256) is not str or _SHA256_RE.fullmatch(
        ci_evidence_sha256
    ) is None:
        raise ReadinessBlocked("CI_EVIDENCE_SHA256_REQUIRED")


def _validate_fixed_study_and_cost() -> dict[str, Any]:
    try:
        manifest = protocol.load_manifest()
        config = protocol.load_generation_config()
        protocol.load_protocol_text()
        binding = ledger._load_binding()
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        ledger.Study3bLedgerError,
    ):
        raise ReadinessBlocked("STUDY3B_PROTOCOL_OR_COST_BINDING_INVALID") from None
    total_estimate = sum(
        (row.conservative_cost_usd for row in binding.scene_estimates), Decimal(0)
    )
    if (
        manifest.get("study_id") != protocol.STUDY_ID
        or config.get("study_id") != protocol.STUDY_ID
        or config.get("max_tokens") != 16384
        or config.get("timeout_seconds") != 720
        or config.get("cost_limit_usd") != "0.05"
        or ledger.HARD_CEILING_USD != Decimal("0.05")
        or not total_estimate.is_finite()
        or total_estimate < 0
        or total_estimate >= ledger.HARD_CEILING_USD
    ):
        raise ReadinessBlocked("STUDY3B_FIXED_COST_OR_IDENTITY_INVALID")
    return {
        "study_id": protocol.STUDY_ID,
        "manifest_sha256": protocol.MANIFEST_SHA256,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "generation_config_sha256": protocol.GENERATION_CONFIG_SHA256,
        "hard_ceiling_usd": "0.05",
        "conservative_total_usd_estimate": format(total_estimate, "f"),
        "strict_pre_dispatch_rule": "conservative estimate must be strictly below hard ceiling",
        "attempt_cap": 3,
        "attempts_per_scene": 1,
        "scene_order": list(protocol.SCENE_ORDER),
    }


def _assert_fresh_run_root() -> None:
    parts = Path(STUDY3B_RUN_ROOT_RELATIVE).parts
    root_fd: int | None = None
    current_fd: int | None = None
    try:
        root_fd = os.open(protocol.REPO_ROOT, _DIRECTORY_FLAGS)
        current_fd = root_fd
        for index, part in enumerate(parts):
            try:
                metadata = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(metadata.st_mode):
                raise ReadinessBlocked("STUDY3B_RUN_ROOT_UNSAFE")
            if index < len(parts) - 1:
                if not stat.S_ISDIR(metadata.st_mode):
                    raise ReadinessBlocked("STUDY3B_RUN_ROOT_UNSAFE")
                child_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
                opened = os.fstat(child_fd)
                named_after = os.stat(
                    part, dir_fd=current_fd, follow_symlinks=False
                )
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or stat.S_ISLNK(named_after.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != (metadata.st_dev, metadata.st_ino)
                    or (named_after.st_dev, named_after.st_ino)
                    != (opened.st_dev, opened.st_ino)
                ):
                    os.close(child_fd)
                    raise ReadinessBlocked("STUDY3B_RUN_ROOT_UNSAFE")
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = child_fd
            else:
                raise ReadinessBlocked("STUDY3B_ALLOCATION_ALREADY_EXISTS")
    except ReadinessBlocked:
        raise
    except OSError:
        raise ReadinessBlocked("STUDY3B_RUN_ROOT_UNAVAILABLE") from None
    finally:
        if current_fd is not None and current_fd != root_fd:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)


def _verify_adjudication_ruling() -> dict[str, str]:
    raw = _read_ruling_source()
    section = _extract_ruling_section(raw)
    digest = hashlib.sha256(section).hexdigest()
    if digest != PINNED_RULING_SECTION_SHA256:
        raise ReadinessBlocked("ADJUDICATION_RULING_SECTION_HASH_MISMATCH")
    if any(text not in section for text in _RULING_REQUIRED_SCOPE):
        raise ReadinessBlocked("ADJUDICATION_RULING_SCOPE_MISMATCH")
    return {
        "ruling_id": DISPATCH_RULING_ID,
        "section_sha256": digest,
        "authority": "OVERSEER_STANDING_AUTHORITY; NO_NEW_OWNER_APPROVAL_REQUESTED",
        "approved_study_id": protocol.STUDY_ID,
        "approved_protocol_sha256": protocol.PROTOCOL_SHA256,
        "approved_generation_config_sha256": protocol.GENERATION_CONFIG_SHA256,
        "approved_final_head_sha": "BOUND_AT_PREFLIGHT_TO_EXACT_LOCAL_HEAD",
        "attempt_cap": 3,
        "attempts_per_scene": 1,
        "max_tokens": 16384,
        "timeout_seconds": 720,
        "hard_ceiling_usd": "0.05",
    }


def _read_ruling_source() -> bytes:
    campaign_fd: int | None = None
    rulings_fd: int | None = None
    file_fd: int | None = None
    try:
        campaign_fd = os.open(RULING_CAMPAIGN_TREE_ROOT, _DIRECTORY_FLAGS)
        campaign_before = os.fstat(campaign_fd)
        if not stat.S_ISDIR(campaign_before.st_mode):
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNSAFE")

        rulings_named = os.stat(
            RULING_SOURCE_DIRECTORY,
            dir_fd=campaign_fd,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(rulings_named.st_mode) or not stat.S_ISDIR(
            rulings_named.st_mode
        ):
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNSAFE")
        rulings_fd = os.open(
            RULING_SOURCE_DIRECTORY,
            _DIRECTORY_FLAGS,
            dir_fd=campaign_fd,
        )
        rulings_before = os.fstat(rulings_fd)
        rulings_after_open = os.stat(
            RULING_SOURCE_DIRECTORY,
            dir_fd=campaign_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(rulings_before.st_mode)
            or (rulings_before.st_dev, rulings_before.st_ino)
            != (rulings_named.st_dev, rulings_named.st_ino)
            or (rulings_after_open.st_dev, rulings_after_open.st_ino)
            != (rulings_before.st_dev, rulings_before.st_ino)
        ):
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNSAFE")

        named_before = os.stat(
            RULING_SOURCE_NAME,
            dir_fd=rulings_fd,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(named_before.st_mode) or not stat.S_ISREG(named_before.st_mode):
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNSAFE")
        file_fd = os.open(
            RULING_SOURCE_NAME,
            _FILE_READ_FLAGS,
            dir_fd=rulings_fd,
        )
        before = os.fstat(file_fd)
        if (
            (before.st_dev, before.st_ino)
            != (named_before.st_dev, named_before.st_ino)
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or (hasattr(os, "geteuid") and before.st_uid != os.geteuid())
            or before.st_size < 1
        ):
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNSAFE")
        if before.st_size > MAX_RULING_SOURCE_BYTES:
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_OVERSIZED")
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_RULING_SOURCE_BYTES:
            chunk = os.read(file_fd, min(65536, MAX_RULING_SOURCE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_RULING_SOURCE_BYTES:
            raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_OVERSIZED")
        raw = b"".join(chunks)
        after = os.fstat(file_fd)
        named_after = os.stat(
            RULING_SOURCE_NAME,
            dir_fd=rulings_fd,
            follow_symlinks=False,
        )
        rulings_after_read = os.stat(
            RULING_SOURCE_DIRECTORY,
            dir_fd=campaign_fd,
            follow_symlinks=False,
        )
        campaign_after = os.fstat(campaign_fd)
    except ReadinessBlocked:
        raise
    except OSError:
        raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_UNAVAILABLE") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if rulings_fd is not None:
            os.close(rulings_fd)
        if campaign_fd is not None:
            os.close(campaign_fd)
    if (
        len(raw) != before.st_size
        or _stat_identity(before) != _stat_identity(after)
        or (named_after.st_dev, named_after.st_ino) != (before.st_dev, before.st_ino)
        or (rulings_after_read.st_dev, rulings_after_read.st_ino)
        != (rulings_before.st_dev, rulings_before.st_ino)
        or _stat_identity(campaign_before) != _stat_identity(campaign_after)
    ):
        raise ReadinessBlocked("ADJUDICATION_RULING_SOURCE_CHANGED_DURING_READ")
    return raw


def _extract_ruling_section(raw: bytes) -> bytes:
    heading = b"## Ruling: " + DISPATCH_RULING_ID.encode("ascii")
    heading_lines = [
        match
        for match in re.finditer(rb"(?m)^## [^\r\n]*(?:\r?\n|$)", raw)
        if match.group(0).rstrip(b"\r\n") == heading
    ]
    occurrences = [match.start() for match in re.finditer(re.escape(heading), raw)]
    if len(heading_lines) != 1 or len(occurrences) != 1:
        raise ReadinessBlocked("ADJUDICATION_RULING_ID_MISSING_OR_DUPLICATE")
    start = heading_lines[0].start()
    if occurrences[0] != start:
        raise ReadinessBlocked("ADJUDICATION_RULING_HEADING_INVALID")
    next_heading = re.search(rb"(?m)^## [^\r\n]*(?:\r?\n|$)", raw[heading_lines[0].end() :])
    if next_heading is not None:
        boundary = heading_lines[0].end() + next_heading.start()
    else:
        boundary = len(raw)
    close = [
        match
        for match in re.finditer(rb"(?m)^<!-- /ruling -->[ \t]*(?:\r?\n|$)", raw[start:boundary])
    ]
    if len(close) != 1:
        raise ReadinessBlocked("ADJUDICATION_RULING_SECTION_INCOMPLETE")
    end = start + close[0].start()
    section = raw[start:end]
    if not section:
        raise ReadinessBlocked("ADJUDICATION_RULING_SECTION_INCOMPLETE")
    return section


def _read_ci_evidence(relative_path: object) -> tuple[bytes, os.stat_result]:
    if type(relative_path) is not str:
        raise ReadinessBlocked("CI_EVIDENCE_PATH_REQUIRED")
    raw, metadata = _read_preparation_file(
        relative_path,
        max_bytes=MAX_CI_EVIDENCE_BYTES,
        kind="CI_EVIDENCE",
    )
    now = time.time()
    if metadata.st_mtime > now + 60:
        raise ReadinessBlocked("CI_EVIDENCE_TIMESTAMP_INVALID")
    if now - metadata.st_mtime > MAX_CI_EVIDENCE_AGE_SECONDS:
        raise ReadinessBlocked("CI_EVIDENCE_STALE")
    return raw, metadata


def _read_preparation_file(
    relative_path: str,
    *,
    max_bytes: int,
    kind: str,
) -> tuple[bytes, os.stat_result]:
    candidate = Path(relative_path)
    prep_parts = Path(PREP_ROOT_RELATIVE).parts
    if (
        candidate.is_absolute()
        or candidate.as_posix() != relative_path
        or "\\" in relative_path
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.parts[: len(prep_parts)] != prep_parts
        or len(candidate.parts) <= len(prep_parts)
    ):
        raise ReadinessBlocked(kind + "_PATH_OUTSIDE_PREP_ROOT")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(protocol.REPO_ROOT, _DIRECTORY_FLAGS)
        for index, part in enumerate(candidate.parts[:-1]):
            try:
                named = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
                    raise ReadinessBlocked(kind + "_PATH_UNSAFE")
                child_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                opened = os.fstat(child_fd)
            except ReadinessBlocked:
                raise
            except OSError:
                raise ReadinessBlocked(kind + "_UNAVAILABLE") from None
            if (
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
                or (
                    index >= len(prep_parts) - 1
                    and opened.st_mode & 0o022
                )
            ):
                os.close(child_fd)
                raise ReadinessBlocked(kind + "_PATH_UNSAFE")
            os.close(directory_fd)
            directory_fd = child_fd

        name = candidate.parts[-1]
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(named.st_mode) or not stat.S_ISREG(named.st_mode):
                raise ReadinessBlocked(kind + "_FILE_UNSAFE")
            file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
            opened = os.fstat(file_fd)
        except ReadinessBlocked:
            raise
        except OSError:
            raise ReadinessBlocked(kind + "_UNAVAILABLE") from None
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
            or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_size < 1
            or opened.st_size > max_bytes
        ):
            raise ReadinessBlocked(kind + "_FILE_UNSAFE_OR_OVERSIZED")
        chunks: list[bytes] = []
        size = 0
        while size <= max_bytes:
            chunk = os.read(file_fd, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > max_bytes:
            raise ReadinessBlocked(kind + "_SIZE_LIMIT_EXCEEDED")
        after = os.fstat(file_fd)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            _stat_identity(after) != _stat_identity(opened)
            or (named_after.st_dev, named_after.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise ReadinessBlocked(kind + "_FILE_CHANGED_DURING_READ")
        return b"".join(chunks), opened
    except ReadinessBlocked:
        raise
    except OSError:
        raise ReadinessBlocked(kind + "_UNAVAILABLE") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _validate_check_runs(raw: bytes, expected_sha: str) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_CI_EVIDENCE_BYTES
        or _SHA1_RE.fullmatch(expected_sha) is None
    ):
        raise ReadinessBlocked("CI_EVIDENCE_SIZE_OR_HEAD_INVALID")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ReadinessBlocked("CI_EVIDENCE_JSON_INVALID") from None
    _validate_bounded_json(document)
    if (
        type(document) is not dict
        or set(document) != {"total_count", "check_runs"}
        or type(document.get("total_count")) is not int
        or type(document.get("check_runs")) is not list
        or len(document["check_runs"]) > MAX_CI_CHECK_RUNS
        or document["total_count"] != len(document["check_runs"])
    ):
        raise ReadinessBlocked("CI_CHECK_RUN_SET_INVALID")

    required_by_name: dict[str, dict[str, Any]] = {}
    for row in document["check_runs"]:
        if type(row) is not dict:
            raise ReadinessBlocked("CI_CHECK_RUN_RECORD_INVALID")
        if len(_canonical_json(row)) > MAX_CI_RECORD_BYTES:
            raise ReadinessBlocked("CI_CHECK_RUN_RECORD_INVALID")
        name = row.get("name")
        if type(name) is not str or not name or len(name) > 256:
            raise ReadinessBlocked("CI_CHECK_RUN_NAME_INVALID")
        if name not in _CI_APP_BY_CHECK:
            continue
        if name in required_by_name:
            raise ReadinessBlocked("CI_CHECK_RUN_NAME_DUPLICATE")
        required_by_name[name] = row

    if set(required_by_name) != set(REQUIRED_CI_CHECK_NAMES):
        raise ReadinessBlocked("CI_REQUIRED_CHECK_SET_INCOMPLETE")

    sanitized: dict[str, dict[str, Any]] = {}
    app_ids: dict[str, int] = {}
    for name in REQUIRED_CI_CHECK_NAMES:
        row = required_by_name[name]
        expected_slug, expected_name, expected_id = _CI_APP_BY_CHECK[name]
        app = row.get("app")
        if (
            type(row.get("head_sha")) is not str
            or _SHA1_RE.fullmatch(row["head_sha"]) is None
            or row["head_sha"] != expected_sha
            or row.get("status") != "completed"
            or row.get("conclusion") != "success"
            or type(app) is not dict
            or not {"id", "slug", "name"} <= set(app)
            or type(app.get("id")) is not int
            or app.get("id") != expected_id
            or app.get("slug") != expected_slug
            or app.get("name") != expected_name
        ):
            raise ReadinessBlocked("CI_REQUIRED_CHECK_PRODUCER_STATE_OR_SHA_INVALID")
        app_ids[expected_slug] = app["id"]
        sanitized[name] = {
            "name": name,
            "head_sha": expected_sha,
            "status": "completed",
            "conclusion": "success",
            "app_slug": expected_slug,
            "app_id": expected_id,
        }

    app_counts = {
        slug: sum(1 for row in sanitized.values() if row["app_slug"] == slug)
        for slug in _REQUIRED_CI_APP_COUNTS
    }
    if app_counts != _REQUIRED_CI_APP_COUNTS or app_ids != _REQUIRED_CI_APP_IDS:
        raise ReadinessBlocked("CI_REQUIRED_CHECK_PRODUCER_SET_INVALID")
    return {
        "required_check_count": len(sanitized),
        "total_check_run_count": document["total_count"],
        "required_checks": [sanitized[name] for name in REQUIRED_CI_CHECK_NAMES],
        "app_identities": {
            slug: {
                "slug": slug,
                "name": (
                    "GitHub Actions"
                    if slug == "github-actions"
                    else "GitHub Advanced Security"
                ),
                "id": app_ids[slug],
            }
            for slug in sorted(app_ids)
        },
    }


def _validate_bounded_json(value: object) -> None:
    remaining = [MAX_CI_JSON_NODES]

    def visit(node: object, depth: int) -> None:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > MAX_CI_JSON_DEPTH:
            raise ReadinessBlocked("CI_JSON_COMPLEXITY_LIMIT_EXCEEDED")
        if type(node) is str:
            if len(node) > MAX_CI_STRING_LENGTH:
                raise ReadinessBlocked("CI_JSON_STRING_LIMIT_EXCEEDED")
            return
        if type(node) is dict:
            if len(node) > 512:
                raise ReadinessBlocked("CI_JSON_OBJECT_LIMIT_EXCEEDED")
            for key, item in node.items():
                if type(key) is not str or len(key) > 128:
                    raise ReadinessBlocked("CI_JSON_KEY_INVALID")
                visit(item, depth + 1)
            return
        if type(node) is list:
            if len(node) > MAX_CI_CHECK_RUNS * 16:
                raise ReadinessBlocked("CI_JSON_ARRAY_LIMIT_EXCEEDED")
            for item in node:
                visit(item, depth + 1)
            return
        if node is None or type(node) in {bool, int, float}:
            return
        raise ReadinessBlocked("CI_JSON_VALUE_INVALID")

    visit(value, 0)


def _verify_pull_request_head(expected_sha: str) -> dict[str, Any]:
    executable = _resolve_trusted_executable("gh")
    if executable is None:
        raise ReadinessBlocked("TRUSTED_GH_UNAVAILABLE")
    result = _run_process(
        (
            executable,
            "pr",
            "view",
            str(GITHUB_PR_NUMBER),
            "--repo",
            GITHUB_REPOSITORY,
            "--json",
            "number,state,isDraft,headRefOid",
        ),
        cwd=protocol.REPO_ROOT,
        timeout=GH_TIMEOUT_SECONDS,
        env=_child_environment(),
    )
    if result.returncode != 0 or len(result.stdout) > 64 * 1024 or len(result.stderr) > 64 * 1024:
        raise ReadinessBlocked("DRAFT_PULL_REQUEST_QUERY_FAILED")
    try:
        document = json.loads(
            result.stdout.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ReadinessBlocked("DRAFT_PULL_REQUEST_JSON_INVALID") from None
    if (
        type(document) is not dict
        or set(document) != {"number", "state", "isDraft", "headRefOid"}
        or type(document.get("number")) is not int
        or document.get("number") != GITHUB_PR_NUMBER
        or document.get("state") != "OPEN"
        or document.get("isDraft") is not True
        or document.get("headRefOid") != expected_sha
    ):
        raise ReadinessBlocked("DRAFT_PULL_REQUEST_HEAD_OR_STATE_MISMATCH")
    return {
        "number": GITHUB_PR_NUMBER,
        "state": "OPEN",
        "is_draft": True,
        "head_sha": expected_sha,
        "repository": GITHUB_REPOSITORY,
    }


def _load_baseline_pin() -> _BaselinePin:
    try:
        raw, _metadata = _read_preparation_file(
            BASELINE_PATH_RELATIVE,
            max_bytes=32 * 1024 * 1024,
            kind="PRIOR_STUDY_BASELINE",
        )
        if hashlib.sha256(raw).hexdigest() != PINNED_PRIOR_STUDY_BASELINE_SHA256:
            raise ReadinessBlocked("PRIOR_STUDY_BASELINE_SHA256_MISMATCH")
        payload = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        isolation.validate_baseline_metadata(payload)
    except ReadinessBlocked:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise ReadinessBlocked("PRIOR_STUDY_BASELINE_INVALID_OR_MISSING") from None
    inventory = _baseline_inventory_record(payload)
    return _BaselinePin(
        evidence_sha256=hashlib.sha256(raw).hexdigest(),
        inventory_sha256=hashlib.sha256(_canonical_json(inventory)).hexdigest(),
        file_count=payload["file_count"],
        opaque_bytes_count=payload["opaque_bytes_count"],
        files=tuple(payload["files"]),
    )


def _baseline_inventory_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": payload["format"],
        "path_base": payload["path_base"],
        "scanned_roots": payload["scanned_roots"],
        "excluded_new_study3b_roots": payload["excluded_new_study3b_roots"],
        "file_count": payload["file_count"],
        "opaque_bytes_count": payload["opaque_bytes_count"],
        "files": payload["files"],
    }


def _assert_baseline_unchanged(pin: _BaselinePin) -> None:
    try:
        current = isolation.build_prior_study_baseline(protocol.REPO_ROOT)
        isolation.validate_baseline_metadata(current)
    except (OSError, ValueError, TypeError, isolation.BaselineScopeError):
        raise ReadinessBlocked("PRIOR_STUDY_INVENTORY_UNAVAILABLE") from None
    if (
        current["file_count"] != pin.file_count
        or current["opaque_bytes_count"] != pin.opaque_bytes_count
        or tuple(current["files"]) != pin.files
    ):
        raise ReadinessBlocked("PRIOR_STUDY_INVENTORY_CHANGED")


def _run_provider_free_preflight(
    expected_sha: str,
    baseline_pin: _BaselinePin,
) -> _GateSummary:
    checks: list[dict[str, Any]] = []
    gate_failures: list[str] = []
    infrastructure_failures: list[str] = []
    for gate_id, command in REQUIRED_PREFLIGHT_COMMANDS:
        try:
            _assert_git_state(expected_sha, "BEFORE_" + gate_id)
            _assert_fresh_run_root()
            _assert_baseline_unchanged(baseline_pin)
            result = _run_process(
                command,
                cwd=protocol.REPO_ROOT,
                timeout=GATE_TIMEOUT_SECONDS,
                env=_child_environment(provider_free=True),
            )
            if (
                type(result) is not _CommandResult
                or type(result.returncode) is not int
                or type(result.stdout) is not bytes
                or type(result.stderr) is not bytes
                or len(result.stdout) > MAX_GATE_OUTPUT_BYTES
                or len(result.stderr) > MAX_GATE_OUTPUT_BYTES
            ):
                raise ReadinessBlocked("PREFLIGHT_COMMAND_RESULT_INVALID")
            checks.append(
                {
                    "gate_id": gate_id,
                    "argv": list(command),
                    "exit_code": result.returncode,
                    "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                }
            )
            if result.returncode != 0:
                gate_failures.append("PREFLIGHT_GATE_FAILED_" + _safe_gate_id(gate_id))
        except ReadinessBlocked as error:
            infrastructure_failures.append(
                "PREFLIGHT_INFRASTRUCTURE_" + _safe_gate_id(gate_id) + "_" + error.code
            )
            checks.append(
                {
                    "gate_id": gate_id,
                    "argv": list(command),
                    "exit_code": None,
                    "stdout_sha256": None,
                    "stderr_sha256": None,
                    "failure_code": error.code,
                }
            )
            break
        except Exception:
            infrastructure_failures.append(
                "PREFLIGHT_INFRASTRUCTURE_" + _safe_gate_id(gate_id)
            )
            checks.append(
                {
                    "gate_id": gate_id,
                    "argv": list(command),
                    "exit_code": None,
                    "stdout_sha256": None,
                    "stderr_sha256": None,
                    "failure_code": "COMMAND_EXECUTION_FAILED",
                }
            )
            break

        # Re-hash the frozen inventory and recheck exact HEAD after every gate,
        # even a failed test, before any later command can run.
        try:
            _assert_baseline_unchanged(baseline_pin)
            _assert_fresh_run_root()
            _assert_git_state(expected_sha, "AFTER_" + gate_id)
        except ReadinessBlocked as error:
            infrastructure_failures.append(error.code)
            break

    if len(checks) != len(REQUIRED_PREFLIGHT_COMMANDS):
        infrastructure_failures.append("PREFLIGHT_GATE_SET_INCOMPLETE")
    return _GateSummary(
        checks=tuple(checks),
        gate_failures=tuple(sorted(set(gate_failures))),
        infrastructure_failures=tuple(sorted(set(infrastructure_failures))),
        inventory_sha256=baseline_pin.inventory_sha256,
    )


def _assert_git_state(expected_sha: str, boundary: str) -> None:
    current_head, status = _read_local_git_state()
    if status:
        raise ReadinessBlocked("LOCAL_WORKTREE_NOT_CLEAN_" + boundary)
    if current_head != expected_sha:
        raise ReadinessBlocked("LOCAL_HEAD_SHA_MISMATCH_" + boundary)


def _read_local_git_state() -> tuple[str, bytes]:
    git = _resolve_trusted_executable("git")
    if git is None:
        raise ReadinessBlocked("TRUSTED_GIT_UNAVAILABLE")
    head = _run_process(
        (git, "rev-parse", "--verify", "HEAD"),
        cwd=protocol.REPO_ROOT,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_child_environment(),
    )
    status = _run_process(
        (
            git,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ),
        cwd=protocol.REPO_ROOT,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_child_environment(),
    )
    if (
        head.returncode != 0
        or status.returncode != 0
        or len(head.stdout) > 256
        or len(status.stdout) > 1024 * 1024
    ):
        raise ReadinessBlocked("LOCAL_GIT_STATE_UNAVAILABLE")
    try:
        head_sha = head.stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ReadinessBlocked("LOCAL_GIT_HEAD_INVALID") from None
    if _SHA1_RE.fullmatch(head_sha) is None:
        raise ReadinessBlocked("LOCAL_GIT_HEAD_INVALID")
    return head_sha, status.stdout


def _resolve_trusted_executable(name: str) -> str | None:
    return shutil.which(name, path=_TRUSTED_EXECUTABLE_PATH)


def _child_environment(*, provider_free: bool = False) -> dict[str, str]:
    environment = {
        "PATH": _TRUSTED_EXECUTABLE_PATH,
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENSPEC_TELEMETRY": "0",
        "DO_NOT_TRACK": "1",
    }
    if provider_free:
        environment["NEQ_STUDY3B_PREFLIGHT"] = "1"
    return environment


def _run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
) -> _CommandResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReadinessBlocked("PREFLIGHT_PROCESS_EXECUTION_FAILED") from None
    if type(completed.stdout) is not bytes or type(completed.stderr) is not bytes:
        raise ReadinessBlocked("PREFLIGHT_PROCESS_OUTPUT_INVALID")
    return _CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _readiness_record(
    *,
    status: str,
    expected_head_sha: str | None,
    current_head_sha: str | None,
    dispatch_ruling_id: str | None,
    ruling_summary: dict[str, Any] | None,
    ci_evidence_path: str | None,
    ci_evidence_sha256: str | None,
    ci_summary: dict[str, Any] | None,
    pr_summary: dict[str, Any] | None,
    baseline_pin: _BaselinePin | None,
    gate_summary: _GateSummary | None,
    reason_codes: tuple[str, ...],
    external_provenance_verified: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    safe_head_sha = _safe_sha1(expected_head_sha)
    return {
        "schema": "neq.llm_staging_study3b_exact_head_preflight.v1",
        "status": status,
        "created_at_utc": now,
        "study_id": protocol.STUDY_ID,
        "repository": GITHUB_REPOSITORY,
        "head_sha": safe_head_sha,
        "current_head_sha": _safe_sha1(current_head_sha),
        "trust_boundary": READINESS_TRUST_BOUNDARY,
        "run_fence": {
            "ruling_id": (
                dispatch_ruling_id
                if dispatch_ruling_id == DISPATCH_RULING_ID
                else None
            ),
            "ruling_section_sha256": (
                ruling_summary.get("section_sha256")
                if ruling_summary is not None
                else None
            ),
            "study_id": protocol.STUDY_ID,
            "manifest_sha256": protocol.MANIFEST_SHA256,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "generation_config_sha256": protocol.GENERATION_CONFIG_SHA256,
            "final_head_sha": safe_head_sha,
            "attempt_cap": 3,
            "attempts_per_scene": 1,
            "scene_order": list(protocol.SCENE_ORDER),
            "hard_ceiling_usd": "0.05",
        },
        "approval_scope": ruling_summary,
        "ci_evidence": {
            "path": _safe_ci_evidence_path(ci_evidence_path),
            "sha256": _safe_sha256(ci_evidence_sha256),
            "source_repository": GITHUB_REPOSITORY,
            "pull_request_number": GITHUB_PR_NUMBER,
            "source_url": (
                "https://api.github.com/repos/"
                + GITHUB_REPOSITORY
                + "/commits/"
                + safe_head_sha
                + "/check-runs?per_page=100"
                if safe_head_sha is not None
                else None
            ),
            "retrieval_trust_root": READINESS_TRUST_BOUNDARY,
            "external_provenance_verified": external_provenance_verified,
            "required_check_count": (
                ci_summary.get("required_check_count")
                if ci_summary is not None
                else 0
            ),
            "total_check_run_count": (
                ci_summary.get("total_check_run_count")
                if ci_summary is not None
                else 0
            ),
            "required_checks": (
                ci_summary.get("required_checks") if ci_summary is not None else []
            ),
            "app_identities": (
                ci_summary.get("app_identities") if ci_summary is not None else {}
            ),
        },
        "pull_request": pr_summary,
        "prior_study_inventory": (
            {
                "baseline_path": BASELINE_PATH_RELATIVE,
                "baseline_evidence_sha256": baseline_pin.evidence_sha256,
                "inventory_sha256": baseline_pin.inventory_sha256,
                "file_count": baseline_pin.file_count,
                "opaque_bytes_count": baseline_pin.opaque_bytes_count,
                "checked_before_and_after_each_gate": True,
                "prior_study_reset_or_replay": False,
            }
            if baseline_pin is not None
            else None
        ),
        "checks": list(gate_summary.checks) if gate_summary is not None else [],
        "preflight_gate_count": len(gate_summary.checks) if gate_summary else 0,
        "gate_failures": list(gate_summary.gate_failures) if gate_summary else [],
        "infrastructure_failures": (
            list(gate_summary.infrastructure_failures) if gate_summary else []
        ),
        "reason_codes": list(reason_codes),
        "live_dispatch_permitted": status == "READY",
        "ledger_initialized": False,
        "credentials_loaded": False,
        "http_dispatched": False,
    }


def _safe_ci_evidence_path(value: object) -> str | None:
    if type(value) is not str or not 1 <= len(value) <= 512:
        return None
    candidate = Path(value)
    prep_parts = Path(PREP_ROOT_RELATIVE).parts
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or "\\" in value
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.parts[: len(prep_parts)] != prep_parts
        or len(candidate.parts) <= len(prep_parts)
        or re.fullmatch(r"[A-Za-z0-9_./-]{1,512}", value) is None
    ):
        return None
    return value


def _safe_sha1(value: object) -> str | None:
    return value if type(value) is str and _SHA1_RE.fullmatch(value) else None


def _safe_sha256(value: object) -> str | None:
    return value if type(value) is str and _SHA256_RE.fullmatch(value) else None


def _write_immutable_evidence(record: dict[str, Any]) -> tuple[str, str]:
    raw = _canonical_json(record)
    if not 1 <= len(raw) <= MAX_READINESS_EVIDENCE_BYTES:
        raise ReadinessBlocked("READINESS_EVIDENCE_SIZE_INVALID")
    head_sha = record.get("head_sha")
    if head_sha is not None and (
        type(head_sha) is not str or _SHA1_RE.fullmatch(head_sha) is None
    ):
        raise ReadinessBlocked("READINESS_EVIDENCE_HEAD_INVALID")
    directory_fd = _open_readiness_directory()
    suffix = head_sha[:12] if type(head_sha) is str else "blocked"
    name = "readiness-" + suffix + "-" + str(time.time_ns()) + ".json"
    path = Path(_READINESS_DIRECTORY_RELATIVE) / name
    isolation.assert_study3b_write_target(
        path,
        repository_root=protocol.REPO_ROOT,
        action="write",
    )
    file_fd: int | None = None
    try:
        file_fd = os.open(name, _FILE_WRITE_FLAGS, 0o600, dir_fd=directory_fd)
        os.fchmod(file_fd, 0o600)
        opened = os.fstat(file_fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_mode & 0o077
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
        ):
            raise ReadinessBlocked("READINESS_EVIDENCE_FILE_UNSAFE")
        _write_all(file_fd, raw)
        os.fsync(file_fd)
        os.fsync(directory_fd)
    except FileExistsError:
        raise ReadinessBlocked("READINESS_EVIDENCE_ALREADY_EXISTS") from None
    except ReadinessBlocked:
        raise
    except OSError:
        raise ReadinessBlocked("READINESS_EVIDENCE_PERSIST_FAILED") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    return (
        (_READINESS_DIRECTORY_RELATIVE + "/" + name),
        hashlib.sha256(raw).hexdigest(),
    )


def _open_readiness_directory() -> int:
    parts = Path(_READINESS_DIRECTORY_RELATIVE).parts
    prep_parts = Path(PREP_ROOT_RELATIVE).parts
    descriptor = os.open(protocol.REPO_ROOT, _DIRECTORY_FLAGS)
    try:
        for index, part in enumerate(parts):
            try:
                named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if index < len(prep_parts):
                    raise ReadinessBlocked("READINESS_PREP_ROOT_MISSING") from None
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                    named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                except OSError:
                    raise ReadinessBlocked("READINESS_EVIDENCE_ROOT_CREATE_FAILED") from None
            if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
                raise ReadinessBlocked("READINESS_EVIDENCE_ROOT_UNSAFE")
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                opened = os.fstat(child)
                named_after = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                raise ReadinessBlocked("READINESS_EVIDENCE_ROOT_UNSAFE") from None
            if (
                (opened.st_dev, opened.st_ino) != (named_after.st_dev, named_after.st_ino)
                or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
                or (index >= len(prep_parts) - 1 and opened.st_mode & 0o022)
            ):
                os.close(child)
                raise ReadinessBlocked("READINESS_EVIDENCE_ROOT_UNSAFE")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except ReadinessBlocked:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise ReadinessBlocked("READINESS_EVIDENCE_ROOT_UNSAFE") from None


def _write_all(descriptor: int, contents: bytes) -> None:
    position = 0
    while position < len(contents):
        written = os.write(descriptor, contents[position:])
        if written <= 0:
            raise OSError("short readiness evidence write")
        position += written


def _safe_gate_id(value: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", value.upper())


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def main(argv: list[str] | None = None) -> int:
    """Run provider-free exact-head readiness; never create a ledger."""

    arguments = sys.argv[1:] if argv is None else argv
    parsed = _parse_cli_arguments(arguments)
    if parsed is None:
        print('{"reason_codes":["READINESS_ARGUMENTS_NOT_ACCEPTED"],"status":"BLOCKED"}')
        return 2
    result = verify_live_readiness(
        expected_head_sha=parsed["--head-sha"],
        ci_evidence_path=parsed["--ci-json"],
        ci_evidence_sha256=parsed["--ci-sha256"],
        dispatch_ruling_id=parsed["--dispatch-ruling-id"],
    )
    safe_result = {
        "status": result.status,
        "reason_codes": list(result.reason_codes),
        "study_id": result.study_id,
        "head_sha": result.expected_head_sha,
        "current_head_sha": result.current_head_sha,
        "ci_check_count": result.ci_check_count,
        "preflight_gate_count": result.preflight_gate_count,
        "external_provenance_verified": result.external_provenance_verified,
        "live_dispatch_permitted": result.live_dispatch_permitted,
        "ruling_id": result.ruling_id,
        "ruling_section_sha256": result.ruling_section_sha256,
        "evidence_relative_path": result.evidence_relative_path,
        "evidence_sha256": result.evidence_sha256,
        "gate_failures": list(result.gate_failures),
        "infrastructure_failures": list(result.infrastructure_failures),
        "trust_boundary": READINESS_TRUST_BOUNDARY,
    }
    print(_canonical_json(safe_result).decode("ascii"))
    return 0 if is_verified_readiness(result) else 1


def _parse_cli_arguments(arguments: list[str]) -> dict[str, str] | None:
    if type(arguments) is not list or not arguments or arguments[0] != "--exact-sha-readiness":
        return None
    allowed = {
        "--head-sha",
        "--ci-json",
        "--ci-sha256",
        "--dispatch-ruling-id",
    }
    tail = arguments[1:]
    if len(tail) % 2:
        return None
    values: dict[str, str] = {}
    for index in range(0, len(tail), 2):
        key, value = tail[index : index + 2]
        if (
            key not in allowed
            or key in values
            or type(value) is not str
            or not value
            or value.startswith("--")
        ):
            return None
        values[key] = value
    required = allowed
    return values if required <= set(values) else None


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DISPATCH_RULING_ID",
    "GITHUB_REPOSITORY",
    "PINNED_RULING_SECTION_SHA256",
    "PINNED_PRIOR_STUDY_BASELINE_SHA256",
    "REQUIRED_CI_CHECK_NAMES",
    "REQUIRED_PREFLIGHT_COMMANDS",
    "READINESS_TRUST_BOUNDARY",
    "ReadinessBlocked",
    "ReadinessVerification",
    "assert_dispatch_readiness_current",
    "is_verified_readiness",
    "main",
    "verify_live_readiness",
]
