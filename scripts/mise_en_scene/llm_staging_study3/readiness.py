# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3 readiness bound to primary-supplied exact-head evidence.

The primary supplies raw public GitHub CheckRuns JSON and its SHA-256 after a
direct retrieval from the fixed repository endpoint. SHA-256 verifies the saved
bytes, not their origin; that direct primary retrieval is the trust root. This
module independently checks the exact head, required checks and app identities,
the open DRAFT PR head through supported ``gh pr view --repo`` fields, pinned
ruling text and cap envelope, local gates, and post-gate worktree identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
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
import time
from typing import Any, Mapping

from . import frozen_inventory, preflight, protocol, sizing
from .ledger import PREP_ROOT_RELATIVE
from .newrequest import request_transport_metadata


GITHUB_REPOSITORY = "zeug-zz/NeverEndingQuest-TTRPG"
GITHUB_PR_MINIMUM = 127
MAX_GATE_OUTPUT_BYTES = 32 * 1024 * 1024
GATE_TIMEOUT_SECONDS = 1800
PR_VIEW_TIMEOUT_SECONDS = 30
MAX_CI_EVIDENCE_BYTES = 1024 * 1024
MAX_CI_CHECK_RUNS = 64
MAX_CI_RECORD_BYTES = 64 * 1024
MAX_CI_JSON_DEPTH = 12
MAX_CI_JSON_NODES = 20_000
MAX_CI_STRING_LENGTH = 8192
MAX_CI_EVIDENCE_AGE_SECONDS = 15 * 60
MAX_RULING_SOURCE_BYTES = 4 * 1024 * 1024
MAX_READINESS_EVIDENCE_BYTES = 128 * 1024
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME_RE = re.compile(r"^[a-z0-9-]{1,80}$")
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
DISPATCH_RULING_ID = "neq-s-study3-unblock-20261111"
RUNNER_REVISION_RULING_ID = "neq-s-study3-runner-revision-20261111"
READINESS_TRUST_BOUNDARY = (
    "PRIMARY_DIRECT_GITHUB_PUBLIC_API_RETRIEVAL_IS_TRUST_ROOT; "
    "SHA256_CHECKS_BYTES_ONLY_NOT_ORIGIN"
)
RULING_SOURCE_PATH = (
    protocol.REPO_ROOT.parent
    / "NeverEndingQuest"
    / ".git"
    / "overseer-relay"
    / "campaigns"
    / "neq-current-build"
    / "rulings"
    / "B.md"
)
PINNED_RULING_SHA256: Mapping[str, str] = {
    "neq-standing-authority-20261110": "d6a6f732808ec7542b6c3cc75cdd479feb828b7f9356a3d804f42256a8d3c4d3",
    "neq-study3-pre-approved-20261110": "2769c192036f20ada0aad83bc81cd5b5125c34e113fda992d5d44fc7dd9dd9ec",
    RUNNER_REVISION_RULING_ID: "8ffdb4b88e09ace88c572ae591f052f52558f1d02fa107518a8fdc0385f0f8d0",
    DISPATCH_RULING_ID: "66086b12d6f01e3a486be8ca14c25462a45505f385c3c065904001cc894bbb81",
}

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

REQUIRED_PREFLIGHT_GATE_IDS = (
    "focused-study3-tests",
    "full-mise-en-scene-tests",
    "mapping-pilot-tests",
    "ascii-compliance",
    "study3-openspec-strict",
    "study2-openspec-strict",
    "frozen-study1-study2-inventory-before",
    "frozen-study1-study2-inventory-after",
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
    "frozen-study1-study2-inventory-before": (
        ".venv/bin/python",
        "scripts/mise_en_scene/llm_staging_study3/frozen_inventory.py",
    ),
    "frozen-study1-study2-inventory-after": (
        ".venv/bin/python",
        "scripts/mise_en_scene/llm_staging_study3/frozen_inventory.py",
    ),
}

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
_READINESS_EVIDENCE_RELATIVE = PREP_ROOT_RELATIVE + "/readiness"

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
    dispatch_ruling_id: str | None = None
    evidence_relative_path: str | None = None
    evidence_sha256: str | None = None
    gate_failures: tuple[str, ...] = ()
    infrastructure_failures: tuple[str, ...] = ()
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
    """Return true only for a fresh exact-head preflight issued in this process."""

    return (
        type(value) is ReadinessVerification
        and value._proof is _READY_PROOF
        and value.status == "READY"
        and value.external_provenance_verified is True
        and value.reason_codes == ()
        and value.ci_check_count == len(REQUIRED_CI_CHECK_NAMES)
        and value.preflight_gate_count == len(REQUIRED_PREFLIGHT_GATE_IDS)
        and value.gate_failures == ()
        and value.infrastructure_failures == ()
        and type(value.evidence_relative_path) is str
        and type(value.evidence_sha256) is str
        and _SHA256_RE.fullmatch(value.evidence_sha256) is not None
    )


def verify_readiness_evidence(
    *,
    expected_sha: object = None,
    ci_evidence_path: object = None,
    ci_evidence_sha256: object = None,
    source_repository: object = None,
    pr_number: object = None,
    dispatch_ruling_id: object = None,
) -> ReadinessVerification:
    """Verify primary-fetched exact-SHA provenance, local gates, and pinned approval.

    The optional ruling ID is an explicit opt-in. Without the exact approved ID,
    this may report software readiness but never permits real dispatch.
    """

    current_head: str | None = None
    try:
        _validate_readiness_arguments(
            expected_sha=expected_sha,
            ci_evidence_path=ci_evidence_path,
            ci_evidence_sha256=ci_evidence_sha256,
            source_repository=source_repository,
            pr_number=pr_number,
            dispatch_ruling_id=dispatch_ruling_id,
        )
        current_head, status = _read_local_git_state()
        if status:
            raise ReadinessVerificationError("LOCAL_WORKTREE_NOT_CLEAN")
        if current_head != expected_sha:
            raise ReadinessVerificationError("LOCAL_HEAD_SHA_MISMATCH")

        ci_bytes, ci_modified_at = _read_ci_evidence(ci_evidence_path)
        if hashlib.sha256(ci_bytes).hexdigest() != ci_evidence_sha256:
            raise ReadinessVerificationError("CI_EVIDENCE_SHA256_MISMATCH")
        ci_summary = _validate_check_runs(ci_bytes, expected_sha)
        if time.time() - ci_modified_at > MAX_CI_EVIDENCE_AGE_SECONDS:
            raise ReadinessVerificationError("CI_EVIDENCE_STALE")
        if ci_modified_at > time.time() + 60:
            raise ReadinessVerificationError("CI_EVIDENCE_TIMESTAMP_INVALID")

        approval_summary = _verify_pinned_approval()
        pr_summary = _verify_pull_request_head(pr_number, expected_sha)
        current_head, status = _read_local_git_state()
        if status:
            raise ReadinessVerificationError("LOCAL_WORKTREE_NOT_CLEAN")
        if current_head != expected_sha:
            raise ReadinessVerificationError("LOCAL_HEAD_SHA_MISMATCH")

        preflight_summary = _run_provider_free_preflight(expected_sha)
        if preflight_summary.infrastructure_failures or preflight_summary.gate_failures:
            reasons = tuple(
                sorted(
                    set(preflight_summary.infrastructure_failures)
                    | set(preflight_summary.gate_failures)
                )
            )
        else:
            reasons = ()

        # CI bytes and the remote DRAFT head must still describe this exact
        # subject after the potentially long local gates have finished.
        try:
            final_ci_bytes, _final_ci_modified_at = _read_ci_evidence(ci_evidence_path)
            if (
                final_ci_bytes != ci_bytes
                or hashlib.sha256(final_ci_bytes).hexdigest() != ci_evidence_sha256
            ):
                raise ReadinessVerificationError("CI_EVIDENCE_SHA256_MISMATCH_AFTER_PREFLIGHT")
        except ReadinessVerificationError as error:
            reasons = tuple(sorted(set(reasons) | {error.code}))
        try:
            pr_summary = _verify_pull_request_head(pr_number, expected_sha)
        except ReadinessVerificationError as error:
            reasons = tuple(sorted(set(reasons) | {error.code}))

        current_head, status = _read_local_git_state()
        if status:
            reasons = tuple(sorted(set(reasons) | {"LOCAL_WORKTREE_NOT_CLEAN"}))
        if current_head != expected_sha:
            reasons = tuple(sorted(set(reasons) | {"LOCAL_HEAD_SHA_MISMATCH"}))

        live_dispatch_permitted = (
            not reasons and dispatch_ruling_id == DISPATCH_RULING_ID
        )
        readiness_status = "READY" if not reasons else "BLOCKED"
        evidence = _readiness_evidence_record(
            status=readiness_status,
            expected_sha=expected_sha,
            source_repository=source_repository,
            ci_evidence_path=ci_evidence_path,
            ci_evidence_sha256=ci_evidence_sha256,
            ci_summary=ci_summary,
            pr_number=pr_number,
            pr_summary=pr_summary,
            approval_summary=approval_summary,
            dispatch_ruling_id=dispatch_ruling_id,
            live_dispatch_permitted=live_dispatch_permitted,
            preflight_summary=preflight_summary,
            reason_codes=reasons,
        )
        evidence_path, evidence_sha256 = _write_immutable_evidence(evidence)

        # The immutable record reports the pre-write state checks. Re-read once
        # after persistence so no proof escapes if another process changed HEAD
        # or dirtied the checkout during evidence creation.
        final_head, final_status = _read_local_git_state()
        if final_head != expected_sha or final_status:
            return _blocked(
                ("LOCAL_GIT_STATE_CHANGED_AFTER_PREFLIGHT",),
                final_head,
                ci_check_count=ci_summary["required_check_count"],
                preflight_gate_count=len(preflight_summary.checks),
                external_provenance_verified=True,
                dispatch_ruling_id=dispatch_ruling_id,
                evidence_relative_path=evidence_path,
                evidence_sha256=evidence_sha256,
                gate_failures=preflight_summary.gate_failures,
                infrastructure_failures=preflight_summary.infrastructure_failures,
            )
        if reasons:
            return _blocked(
                reasons,
                current_head,
                ci_check_count=ci_summary["required_check_count"],
                preflight_gate_count=len(preflight_summary.checks),
                external_provenance_verified=True,
                dispatch_ruling_id=dispatch_ruling_id,
                evidence_relative_path=evidence_path,
                evidence_sha256=evidence_sha256,
                gate_failures=preflight_summary.gate_failures,
                infrastructure_failures=preflight_summary.infrastructure_failures,
            )
        return ReadinessVerification(
            status="READY",
            reason_codes=(),
            current_head_sha=current_head,
            ci_check_count=ci_summary["required_check_count"],
            preflight_gate_count=len(preflight_summary.checks),
            external_provenance_verified=True,
            live_dispatch_permitted=live_dispatch_permitted,
            dispatch_ruling_id=dispatch_ruling_id,
            evidence_relative_path=evidence_path,
            evidence_sha256=evidence_sha256,
            gate_failures=(),
            infrastructure_failures=(),
            _proof=_READY_PROOF,
        )
    except ReadinessVerificationError as error:
        return _blocked((error.code,), current_head)
    except Exception:
        return _blocked(("READINESS_VERIFICATION_FAILED",), current_head)


def _blocked(
    reason_codes: tuple[str, ...],
    current_head: str | None,
    *,
    ci_check_count: int = 0,
    preflight_gate_count: int = 0,
    external_provenance_verified: bool = False,
    dispatch_ruling_id: str | None = None,
    evidence_relative_path: str | None = None,
    evidence_sha256: str | None = None,
    gate_failures: tuple[str, ...] = (),
    infrastructure_failures: tuple[str, ...] = (),
) -> ReadinessVerification:
    return ReadinessVerification(
        status="BLOCKED",
        reason_codes=tuple(sorted(set(reason_codes))) or ("READINESS_NOT_VERIFIED",),
        current_head_sha=current_head,
        ci_check_count=ci_check_count,
        preflight_gate_count=preflight_gate_count,
        external_provenance_verified=external_provenance_verified,
        live_dispatch_permitted=False,
        dispatch_ruling_id=dispatch_ruling_id,
        evidence_relative_path=evidence_relative_path,
        evidence_sha256=evidence_sha256,
        gate_failures=gate_failures,
        infrastructure_failures=infrastructure_failures,
    )


def _validate_readiness_arguments(
    *,
    expected_sha: object,
    ci_evidence_path: object,
    ci_evidence_sha256: object,
    source_repository: object,
    pr_number: object,
    dispatch_ruling_id: object,
) -> None:
    if type(expected_sha) is not str or _SHA1_RE.fullmatch(expected_sha) is None:
        raise ReadinessVerificationError("EXACT_HEAD_SHA_REQUIRED")
    if type(ci_evidence_path) is not str:
        raise ReadinessVerificationError("CI_EVIDENCE_PATH_REQUIRED")
    if type(ci_evidence_sha256) is not str or _SHA256_RE.fullmatch(ci_evidence_sha256) is None:
        raise ReadinessVerificationError("CI_EVIDENCE_SHA256_REQUIRED")
    if (
        type(source_repository) is not str
        or source_repository != GITHUB_REPOSITORY
    ):
        raise ReadinessVerificationError("CI_SOURCE_REPOSITORY_MISMATCH")
    if type(pr_number) is not int or pr_number < GITHUB_PR_MINIMUM or pr_number > 1_000_000:
        raise ReadinessVerificationError("DRAFT_PULL_REQUEST_NUMBER_INVALID")
    if dispatch_ruling_id is not None and (
        type(dispatch_ruling_id) is not str
        or dispatch_ruling_id != DISPATCH_RULING_ID
    ):
        raise ReadinessVerificationError("DISPATCH_RULING_ID_MISMATCH")


def _read_ci_evidence(relative_path: object) -> tuple[bytes, float]:
    raw, metadata = _read_study3_file(
        relative_path,
        max_bytes=MAX_CI_EVIDENCE_BYTES,
        kind="CI_EVIDENCE",
    )
    now = time.time()
    if metadata.st_mtime > now + 60:
        raise ReadinessVerificationError("CI_EVIDENCE_TIMESTAMP_INVALID")
    if now - metadata.st_mtime > MAX_CI_EVIDENCE_AGE_SECONDS:
        raise ReadinessVerificationError("CI_EVIDENCE_STALE")
    return raw, metadata.st_mtime


def _validate_check_runs(raw: bytes, expected_sha: str) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CI_EVIDENCE_BYTES:
        raise ReadinessVerificationError("CI_EVIDENCE_SIZE_INVALID")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ReadinessVerificationError("CI_EVIDENCE_JSON_INVALID") from None
    _validate_bounded_json(document)
    if (
        type(document) is not dict
        or set(document) != {"total_count", "check_runs"}
        or type(document.get("total_count")) is not int
        or type(document.get("check_runs")) is not list
        or len(document["check_runs"]) > MAX_CI_CHECK_RUNS
        or document["total_count"] != len(document["check_runs"])
    ):
        raise ReadinessVerificationError("CI_CHECK_RUN_SET_INVALID")

    required_rows_by_name: dict[str, dict[str, Any]] = {}
    for row in document["check_runs"]:
        try:
            row_bytes = _canonical_bytes(row)
        except (TypeError, ValueError, RecursionError):
            raise ReadinessVerificationError("CI_CHECK_RUN_RECORD_INVALID") from None
        if len(row_bytes) > MAX_CI_RECORD_BYTES or type(row) is not dict:
            raise ReadinessVerificationError("CI_CHECK_RUN_RECORD_INVALID")
        name = row.get("name")
        if (
            type(name) is not str
            or not name
            or len(name) > 256
        ):
            raise ReadinessVerificationError("CI_CHECK_RUN_NAME_DUPLICATE_OR_INVALID")
        if name not in _CI_APP_BY_CHECK:
            continue
        if name in required_rows_by_name:
            raise ReadinessVerificationError("CI_CHECK_RUN_NAME_DUPLICATE_OR_INVALID")
        required_rows_by_name[name] = row

    if set(required_rows_by_name) != set(REQUIRED_CI_CHECK_NAMES):
        raise ReadinessVerificationError("CI_REQUIRED_CHECK_SET_INCOMPLETE")

    required_by_name: dict[str, dict[str, Any]] = {}
    app_ids: dict[str, int] = {}
    for name in REQUIRED_CI_CHECK_NAMES:
        row = required_rows_by_name[name]
        app = row.get("app")
        expected_slug, expected_name, expected_app_id = _CI_APP_BY_CHECK[name]
        if (
            type(row.get("head_sha")) is not str
            or row["head_sha"] != expected_sha
            or row.get("status") != "completed"
            or row.get("conclusion") != "success"
            or type(app) is not dict
            or not {"id", "slug", "name"} <= set(app)
            or type(app.get("id")) is not int
            or app["id"] != expected_app_id
            or app.get("slug") != expected_slug
            or app.get("name") != expected_name
        ):
            raise ReadinessVerificationError("CI_REQUIRED_CHECK_IDENTITY_OR_STATE_INVALID")
        previous_app_id = app_ids.get(expected_slug)
        if previous_app_id is not None and previous_app_id != app["id"]:
            raise ReadinessVerificationError("CI_CHECK_APP_ID_INCONSISTENT")
        app_ids[expected_slug] = app["id"]
        required_by_name[name] = {
            "name": name,
            "head_sha": row["head_sha"],
            "status": "completed",
            "conclusion": "success",
            "app_slug": expected_slug,
            "app_id": app["id"],
        }

    slug_counts = {
        slug: sum(1 for row in required_by_name.values() if row["app_slug"] == slug)
        for slug in _REQUIRED_CI_APP_COUNTS
    }
    if (
        slug_counts != _REQUIRED_CI_APP_COUNTS
        or app_ids != _REQUIRED_CI_APP_IDS
    ):
        raise ReadinessVerificationError("CI_REQUIRED_APP_IDENTITY_SET_INVALID")
    return {
        "required_check_count": len(required_by_name),
        "total_check_run_count": document["total_count"],
        "required_checks": [required_by_name[name] for name in REQUIRED_CI_CHECK_NAMES],
        "app_identities": {
            slug: {"slug": slug, "name": _expected_app_name(slug), "id": app_ids[slug]}
            for slug in sorted(app_ids)
        },
    }


def _expected_app_name(slug: str) -> str:
    return "GitHub Actions" if slug == "github-actions" else "GitHub Advanced Security"


def _validate_bounded_json(value: object) -> None:
    remaining = [MAX_CI_JSON_NODES]

    def visit(node: object, depth: int) -> None:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > MAX_CI_JSON_DEPTH:
            raise ReadinessVerificationError("CI_JSON_COMPLEXITY_LIMIT_EXCEEDED")
        if type(node) is str:
            if len(node) > MAX_CI_STRING_LENGTH:
                raise ReadinessVerificationError("CI_JSON_STRING_LIMIT_EXCEEDED")
            return
        if type(node) is dict:
            if len(node) > 512:
                raise ReadinessVerificationError("CI_JSON_OBJECT_LIMIT_EXCEEDED")
            for key, item in node.items():
                if type(key) is not str or len(key) > 128:
                    raise ReadinessVerificationError("CI_JSON_KEY_INVALID")
                visit(item, depth + 1)
            return
        if type(node) is list:
            if len(node) > MAX_CI_CHECK_RUNS * 16:
                raise ReadinessVerificationError("CI_JSON_ARRAY_LIMIT_EXCEEDED")
            for item in node:
                visit(item, depth + 1)
            return
        if node is None or type(node) in {bool, int, float}:
            return
        raise ReadinessVerificationError("CI_JSON_VALUE_INVALID")

    visit(value, 0)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _read_study3_file(
    relative_path: object,
    *,
    max_bytes: int,
    kind: str,
) -> tuple[bytes, os.stat_result]:
    if type(relative_path) is not str:
        raise ReadinessVerificationError(kind + "_PATH_INVALID")
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
        raise ReadinessVerificationError(kind + "_PATH_OUTSIDE_STUDY3_ROOT")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(protocol.REPO_ROOT, _DIRECTORY_FLAGS)
        for index, part in enumerate(candidate.parts[:-1]):
            try:
                named = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
                    raise ReadinessVerificationError(kind + "_PATH_UNSAFE")
                child_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                opened = os.fstat(child_fd)
            except ReadinessVerificationError:
                raise
            except OSError:
                raise ReadinessVerificationError(kind + "_UNAVAILABLE") from None
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
                or (
                    index >= len(prep_parts) - 1
                    and opened.st_mode & 0o022
                )
            ):
                os.close(child_fd)
                raise ReadinessVerificationError(kind + "_PATH_UNSAFE")
            os.close(directory_fd)
            directory_fd = child_fd

        name = candidate.parts[-1]
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(named.st_mode) or not stat.S_ISREG(named.st_mode):
                raise ReadinessVerificationError(kind + "_FILE_UNSAFE")
            file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
            opened = os.fstat(file_fd)
        except ReadinessVerificationError:
            raise
        except OSError:
            raise ReadinessVerificationError(kind + "_UNAVAILABLE") from None
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
            or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_size < 1
            or opened.st_size > max_bytes
        ):
            raise ReadinessVerificationError(kind + "_FILE_UNSAFE_OR_OVERSIZED")
        chunks: list[bytes] = []
        size = 0
        while size <= max_bytes:
            chunk = os.read(file_fd, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > max_bytes:
            raise ReadinessVerificationError(kind + "_SIZE_LIMIT_EXCEEDED")
        after = os.fstat(file_fd)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or (named_after.st_dev, named_after.st_ino) != (opened.st_dev, opened.st_ino)
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise ReadinessVerificationError(kind + "_FILE_CHANGED_DURING_READ")
        return b"".join(chunks), opened
    except ReadinessVerificationError:
        raise
    except OSError:
        raise ReadinessVerificationError(kind + "_UNAVAILABLE") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _verify_pinned_approval() -> dict[str, Any]:
    sections = _read_pinned_ruling_sections()
    for ruling_id, expected_hash in PINNED_RULING_SHA256.items():
        if (
            type(expected_hash) is not str
            or _SHA256_RE.fullmatch(expected_hash) is None
            or hashlib.sha256(sections[ruling_id]).hexdigest() != expected_hash
        ):
            raise ReadinessVerificationError("PINNED_RULING_TEXT_MISMATCH")

    standing_id = preflight.STANDING_AUTHORITY_RULING_ID
    cap_id = preflight.CAP_APPROVAL_RULING_ID
    standing_hash = PINNED_RULING_SHA256[standing_id]
    cap_hash = PINNED_RULING_SHA256[cap_id]
    try:
        metadata = request_transport_metadata(protocol.SCENE_ORDER[0])
        config_hash = metadata.get("generation_config_sha256")
        manifest_bytes = protocol._safe_project_read(
            protocol.PROTOCOL_RELATIVE + "/staging-manifest.json"
        )
    except (OSError, ValueError, KeyError, TypeError):
        raise ReadinessVerificationError("PINNED_STUDY3_ARTIFACT_UNAVAILABLE") from None
    if type(config_hash) is not str or _SHA256_RE.fullmatch(config_hash) is None:
        raise ReadinessVerificationError("PINNED_GENERATION_CONFIG_HASH_INVALID")

    pins_without_envelope = preflight.ApprovalPins(
        study_id=protocol.STUDY_ID,
        manifest_sha256=protocol.STUDY3_MANIFEST_SHA256,
        generation_config_sha256=config_hash,
        standing_authority_ruling_id=standing_id,
        standing_authority_sha256=standing_hash,
        cap_approval_ruling_id=cap_id,
        cap_approval_sha256=cap_hash,
        cap_envelope_sha256="0" * 64,
    )
    envelope = preflight._approved_cap_envelope(
        pins_without_envelope,
        standing_hash=standing_hash,
        cap_hash=cap_hash,
    )
    envelope_bytes = preflight._canonical_json(envelope)
    pins = preflight.ApprovalPins(
        study_id=pins_without_envelope.study_id,
        manifest_sha256=pins_without_envelope.manifest_sha256,
        generation_config_sha256=pins_without_envelope.generation_config_sha256,
        standing_authority_ruling_id=pins_without_envelope.standing_authority_ruling_id,
        standing_authority_sha256=pins_without_envelope.standing_authority_sha256,
        cap_approval_ruling_id=pins_without_envelope.cap_approval_ruling_id,
        cap_approval_sha256=pins_without_envelope.cap_approval_sha256,
        cap_envelope_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
    )
    try:
        preflight._verify_approval(
            pins,
            sections[standing_id],
            sections[cap_id],
            envelope_bytes,
            manifest_bytes,
        )
        verified_config_hash = preflight._verify_fixed_generation_envelope(pins)
        sizing_report, conservative_total = sizing._fresh_preflight_sizing_report()
    except (preflight.PreflightBlocked, sizing.SizingBlocked, OSError, ValueError):
        raise ReadinessVerificationError("PINNED_CAP_OR_ESTIMATE_INVALID") from None
    expected_total = Decimal("0.0125671")
    expected_conservative = Decimal("0.0324461")
    if (
        verified_config_hash != config_hash
        or conservative_total != expected_conservative
        or Decimal(sizing_report.get("expected_total_usd_estimate", "-1")) != expected_total
        or Decimal(sizing_report.get("conservative_total_usd_estimate", "-1"))
        != expected_conservative
        or sizing_report.get("rates", {}).get("source_sha256")
        != sizing.RATE_LISTING_SHA256
        or sizing_report.get("hard_ceiling_usd") != "0.05"
        or conservative_total >= sizing.HARD_CEILING_USD
    ):
        raise ReadinessVerificationError("PINNED_CAP_OR_ESTIMATE_MISMATCH")
    return {
        "ruling_hashes": {
            ruling_id: PINNED_RULING_SHA256[ruling_id]
            for ruling_id in sorted(PINNED_RULING_SHA256)
        },
        "standing_authority_ruling_id": standing_id,
        "cap_approval_ruling_id": cap_id,
        "dispatch_ruling_id": DISPATCH_RULING_ID,
        "runner_revision_ruling_id": RUNNER_REVISION_RULING_ID,
        "manifest_sha256": protocol.STUDY3_MANIFEST_SHA256,
        "generation_config_sha256": config_hash,
        "cap_envelope_sha256": pins.cap_envelope_sha256,
        "attempt_cap": 3,
        "attempts_per_scene": 1,
        "scene_order": list(protocol.SCENE_ORDER),
        "model_id": protocol.MODEL_ID,
        "provider": "openrouter",
        "allow_fallbacks": False,
        "max_tokens": 16384,
        "timeout_seconds": 720,
        "historical_rate_source_sha256": sizing.RATE_LISTING_SHA256,
        "sizing_report_sha256": hashlib.sha256(_canonical_bytes(sizing_report)).hexdigest(),
        "expected_total_usd_estimate": str(expected_total),
        "conservative_total_usd_estimate": str(expected_conservative),
        "hard_ceiling_usd": "0.05",
    }


def _read_pinned_ruling_sections() -> dict[str, bytes]:
    path = Path(RULING_SOURCE_PATH)
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if (
            resolved != path
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < 1
            or metadata.st_size > MAX_RULING_SOURCE_BYTES
        ):
            raise ReadinessVerificationError("PINNED_RULING_SOURCE_UNSAFE")
        raw = resolved.read_bytes()
    except ReadinessVerificationError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ReadinessVerificationError("PINNED_RULING_SOURCE_UNAVAILABLE") from None
    if len(raw) > MAX_RULING_SOURCE_BYTES:
        raise ReadinessVerificationError("PINNED_RULING_SOURCE_OVERSIZED")

    heading_lines: list[tuple[int, bytes]] = []
    for match in re.finditer(rb"(?m)^## [^\r\n]*(?:\r?\n|$)", raw):
        line = match.group(0)
        if line.endswith(b"\r\n"):
            line = line[:-2]
        elif line.endswith(b"\n"):
            line = line[:-1]
        heading_lines.append((match.start(), line))
    closing_markers = [
        match.start()
        for match in re.finditer(rb"(?m)^<!-- /ruling -->[ \t]*(?:\r?\n|$)", raw)
    ]

    sections: dict[str, bytes] = {}
    for ruling_id in PINNED_RULING_SHA256:
        if ruling_id.startswith("neq-s-"):
            heading = b"## Ruling: " + ruling_id.encode("ascii")
        else:
            heading = b"## " + ruling_id.encode("ascii")

        exact_heading_starts = [
            start
            for start, line in heading_lines
            if line == heading
            or (
                not ruling_id.startswith("neq-s-")
                and line.startswith(heading + b" - ")
            )
        ]
        heading_occurrences = [
            match.start() for match in re.finditer(re.escape(heading), raw)
        ]
        if not exact_heading_starts and heading_occurrences:
            raise ReadinessVerificationError("PINNED_RULING_HEADING_INVALID")
        if len(exact_heading_starts) != 1 or len(heading_occurrences) != 1:
            raise ReadinessVerificationError("PINNED_RULING_ID_MISSING_OR_DUPLICATE")
        start = exact_heading_starts[0]
        if heading_occurrences[0] != start:
            raise ReadinessVerificationError("PINNED_RULING_HEADING_INVALID")

        next_heading_starts = [
            heading_start for heading_start, _line in heading_lines if heading_start > start
        ]
        next_heading = min(next_heading_starts) if next_heading_starts else None
        marker_starts = [
            marker_start
            for marker_start in closing_markers
            if marker_start > start
            and (next_heading is None or marker_start < next_heading)
        ]
        if len(marker_starts) > 1:
            raise ReadinessVerificationError("PINNED_RULING_SECTION_AMBIGUOUS")
        if marker_starts:
            end = marker_starts[0]
        elif next_heading is not None:
            if raw[next_heading - 2 : next_heading] == b"\r\n":
                end = next_heading - 2
            elif raw[next_heading - 1 : next_heading] == b"\n":
                end = next_heading - 1
            else:
                raise ReadinessVerificationError("PINNED_RULING_HEADING_INVALID")
        else:
            raise ReadinessVerificationError("PINNED_RULING_SECTION_INCOMPLETE")
        if end <= start + len(heading):
            raise ReadinessVerificationError("PINNED_RULING_SECTION_INCOMPLETE")
        sections[ruling_id] = raw[start:end]
    if preflight.STANDING_AUTHORITY_RULING_ID.encode("ascii") not in sections[
        preflight.CAP_APPROVAL_RULING_ID
    ]:
        raise ReadinessVerificationError("CAP_APPROVAL_AUTHORITY_REFERENCE_MISSING")
    return sections


def _verify_pull_request_head(pr_number: int, expected_sha: str) -> dict[str, Any]:
    executable = _resolve_trusted_executable("gh")
    if executable is None:
        raise ReadinessVerificationError("TRUSTED_GH_UNAVAILABLE")
    result = _run_process(
        (
            executable,
            "pr",
            "view",
            str(pr_number),
            "--repo",
            GITHUB_REPOSITORY,
            "--json",
            "number,state,isDraft,headRefOid",
        ),
        cwd=protocol.REPO_ROOT,
        timeout=PR_VIEW_TIMEOUT_SECONDS,
        env=_base_child_environment(),
    )
    if (
        result.returncode != 0
        or len(result.stdout) > 64 * 1024
        or len(result.stderr) > 64 * 1024
    ):
        raise ReadinessVerificationError("DRAFT_PULL_REQUEST_QUERY_FAILED")
    try:
        record = json.loads(
            result.stdout.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ReadinessVerificationError("DRAFT_PULL_REQUEST_JSON_INVALID") from None
    if (
        type(record) is not dict
        or set(record) != {"number", "state", "isDraft", "headRefOid"}
        or type(record.get("number")) is not int
        or record["number"] != pr_number
        or record.get("state") != "OPEN"
        or record.get("isDraft") is not True
        or record.get("headRefOid") != expected_sha
    ):
        raise ReadinessVerificationError("DRAFT_PULL_REQUEST_HEAD_OR_STATE_MISMATCH")
    return {
        "number": pr_number,
        "state": "OPEN",
        "is_draft": True,
        "head_sha": expected_sha,
        "repository": GITHUB_REPOSITORY,
    }


def _readiness_evidence_record(
    *,
    status: str,
    expected_sha: str,
    source_repository: str,
    ci_evidence_path: str,
    ci_evidence_sha256: str,
    ci_summary: dict[str, Any],
    pr_number: int,
    pr_summary: dict[str, Any],
    approval_summary: dict[str, Any],
    dispatch_ruling_id: str | None,
    live_dispatch_permitted: bool,
    preflight_summary: _PreflightSummary,
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema": "neq.llm_staging_study3_exact_sha_preflight.v1",
        "status": status,
        "created_at": _utc_now(),
        "study_id": protocol.STUDY_ID,
        "repository": source_repository,
        "head_sha": expected_sha,
        "trust_boundary": READINESS_TRUST_BOUNDARY,
        "ci_evidence": {
            "path": ci_evidence_path,
            "sha256": ci_evidence_sha256,
            "required_check_count": ci_summary["required_check_count"],
            "total_check_run_count": ci_summary["total_check_run_count"],
            "required_checks": ci_summary["required_checks"],
            "app_identities": ci_summary["app_identities"],
        },
        "pull_request": {**pr_summary, "number": pr_number},
        "approval_and_pins": approval_summary,
        "dispatch_ruling_id": dispatch_ruling_id,
        "live_dispatch_permitted": live_dispatch_permitted,
        "preflight_started_at": preflight_summary.started_at,
        "preflight_completed_at": preflight_summary.completed_at,
        "checks": list(preflight_summary.checks),
        "gate_failures": list(preflight_summary.gate_failures),
        "infrastructure_failures": list(preflight_summary.infrastructure_failures),
        "reason_codes": list(reason_codes),
        "frozen_inventory_before_sha256": _gate_output_hash(
            preflight_summary, "frozen-study1-study2-inventory-before"
        ),
        "frozen_inventory_after_sha256": _gate_output_hash(
            preflight_summary, "frozen-study1-study2-inventory-after"
        ),
    }


def _gate_output_hash(summary: _PreflightSummary, gate_id: str) -> str | None:
    row = next((item for item in summary.checks if item.get("gate_id") == gate_id), None)
    value = row.get("stdout_sha256") if type(row) is dict else None
    return value if type(value) is str and _SHA256_RE.fullmatch(value) is not None else None


def _write_immutable_evidence(record: dict[str, Any]) -> tuple[str, str]:
    try:
        raw = _canonical_bytes(record)
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        raise ReadinessVerificationError("READINESS_EVIDENCE_SERIALIZATION_FAILED") from None
    if not 1 <= len(raw) <= MAX_READINESS_EVIDENCE_BYTES:
        raise ReadinessVerificationError("READINESS_EVIDENCE_SIZE_INVALID")
    directory_fd = _open_readiness_directory()
    head_sha = record.get("head_sha")
    if type(head_sha) is not str or _SHA1_RE.fullmatch(head_sha) is None:
        os.close(directory_fd)
        raise ReadinessVerificationError("READINESS_EVIDENCE_HEAD_INVALID")
    name = "readiness-" + head_sha[:12] + "-" + str(time.time_ns()) + ".json"
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
            raise ReadinessVerificationError("READINESS_EVIDENCE_FILE_UNSAFE")
        _write_all(file_fd, raw)
        os.fsync(file_fd)
        os.fsync(directory_fd)
    except FileExistsError:
        raise ReadinessVerificationError("READINESS_EVIDENCE_ALREADY_EXISTS") from None
    except ReadinessVerificationError:
        raise
    except OSError:
        raise ReadinessVerificationError("READINESS_EVIDENCE_PERSIST_FAILED") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    return (
        _READINESS_EVIDENCE_RELATIVE + "/" + name,
        hashlib.sha256(raw).hexdigest(),
    )


def _open_readiness_directory() -> int:
    parts = Path(_READINESS_EVIDENCE_RELATIVE).parts
    prep_parts = Path(PREP_ROOT_RELATIVE).parts
    descriptor = os.open(protocol.REPO_ROOT, _DIRECTORY_FLAGS)
    try:
        for index, part in enumerate(parts):
            try:
                named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                    named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                except OSError:
                    raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_CREATE_FAILED") from None
            if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
                raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_UNSAFE")
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                opened = os.fstat(child)
                named_after = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_UNSAFE") from None
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named_after.st_mode)
                or (opened.st_dev, opened.st_ino) != (named_after.st_dev, named_after.st_ino)
                or (hasattr(os, "geteuid") and opened.st_uid != os.geteuid())
            ):
                os.close(child)
                raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_UNSAFE")
            if index >= len(prep_parts) - 1:
                try:
                    os.fchmod(child, 0o700)
                except OSError:
                    os.close(child)
                    raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_PERMISSIONS_INVALID") from None
                if os.fstat(child).st_mode & 0o077:
                    os.close(child)
                    raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_PERMISSIONS_INVALID")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except ReadinessVerificationError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise ReadinessVerificationError("READINESS_EVIDENCE_ROOT_UNSAFE") from None


def _write_all(descriptor: int, contents: bytes) -> None:
    position = 0
    while position < len(contents):
        written = os.write(descriptor, contents[position:])
        if written <= 0:
            raise OSError("short evidence write")
        position += written


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
    inventory_hashes: dict[str, str] = {}
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
            if gate_id.startswith("frozen-study1-study2-inventory-"):
                try:
                    inventory_hashes[gate_id] = _validate_inventory_output(result.stdout)
                    check_row["inventory_sha256"] = inventory_hashes[gate_id]
                except ReadinessVerificationError as error:
                    infrastructure_failures.append(error.code)
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

    before = inventory_hashes.get("frozen-study1-study2-inventory-before")
    after = inventory_hashes.get("frozen-study1-study2-inventory-after")
    if before is not None and after is not None and before != after:
        infrastructure_failures.append("FROZEN_INVENTORY_CHANGED_DURING_PREFLIGHT")
    if before is None or after is None:
        infrastructure_failures.append("FROZEN_INVENTORY_COMPARISON_INCOMPLETE")
    if len(checks) != len(REQUIRED_PREFLIGHT_GATE_IDS):
        infrastructure_failures.append("PREFLIGHT_GATE_SET_INCOMPLETE")
    return _PreflightSummary(
        started_at=started_at,
        completed_at=_utc_now(),
        checks=tuple(checks),
        gate_failures=tuple(sorted(set(gate_failures))),
        infrastructure_failures=tuple(sorted(set(infrastructure_failures))),
    )


def _validate_inventory_output(raw: bytes) -> str:
    try:
        record = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ReadinessVerificationError("FROZEN_INVENTORY_OUTPUT_INVALID") from None
    if (
        type(record) is not dict
        or set(record) != {"file_counts", "inventory_sha256", "status"}
        or record.get("status") != "PASS"
        or record.get("inventory_sha256") != frozen_inventory.FROZEN_INVENTORY_SHA256
        or record.get("file_counts") != frozen_inventory.FROZEN_FILE_COUNTS
    ):
        raise ReadinessVerificationError("FROZEN_INVENTORY_OUTPUT_MISMATCH")
    return frozen_inventory.FROZEN_INVENTORY_SHA256


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
        # Validate the target, but invoke the fixed in-repository path: executing
        # the resolved system binary bypasses pyvenv.cfg and loses the venv.
        actual_executable = str(candidate)
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
    """Delegate to the one supported readiness CLI argument contract."""

    return preflight.main(argv)


__all__ = [
    "DISPATCH_RULING_ID",
    "GITHUB_REPOSITORY",
    "PINNED_RULING_SHA256",
    "READINESS_TRUST_BOUNDARY",
    "REQUIRED_CI_CHECK_NAMES",
    "REQUIRED_PREFLIGHT_GATE_COMMANDS",
    "REQUIRED_PREFLIGHT_GATE_IDS",
    "RUNNER_REVISION_RULING_ID",
    "ReadinessVerification",
    "ReadinessVerificationError",
    "is_verified_readiness",
    "main",
    "verify_readiness_evidence",
]
