# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""SP3b's isolated, durable admission and budget-control foundation.

This module deliberately does not import or invoke the SP3 seeder, launcher,
server, socket driver, or provider. H3 may wire these controls and run
provider-free tests before a FREEZE; live execution requires a specific
Overseer SP3b FREEZE ruling.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SP3B_ROOT = Path("tmp/router-rollout/mapping-pilot/sp3b")
DEFAULT_PREREG_ROOT = Path("plans/v2-mapping-pilot-prereg")
AMENDMENT_NAME = "SP3b-amendment.md"
LEDGER_NAME = "execution-ledger.json"
FREEZE_NAME = "execution-freeze.json"
LEDGER_SCHEMA_VERSION = 1

BASELINE_ATTEMPTS = 513
BASELINE_LIVE_SECONDS = 3453.3628182079847
TOTAL_ATTEMPT_CAP = 800
TOTAL_LIVE_SECONDS_CAP = 21600.0
ROW_ATTEMPT_CAP = 35
ROW_LIVE_SECONDS_CAP = 1500.0

EXPECTED_MANIFEST_SHA256 = "49d600b9a7080253d99aa66a725bd981a594afbc3fde76b5df70253219d59c07"
EXPECTED_AMENDMENT_SHA256 = "ce49bead0c786c36fb97bbbd7dd09c220bc0fc6f74cb4b04ba0a443e416b0313"
PRIMARY_CLOSEOUT_RELATIVE_PATH = Path(
    "tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/primary-collection-closeout.json"
)
PRIMARY_CLOSEOUT_SHA256 = "2c265cb7bfd5124c19a9ca15738ccfb1522f3455075c72b3f0b2f065b929c4e2"
PRIMARY_SP3_RUN_ID = "sp3-s-20261105t200000z"

EXPECTED_MANIFEST_ENTRIES = (
    ("README.md", "3dba22343f65b2713975e3f47512d189fe97c47521c0ca0f98dbc54424d4e62b"),
    ("rubric.md", "74f8c9af9aaf54c6a58527a09f441848abf6ea203f3d538140c245bb4e9481d8"),
    ("fixtures/combat_stage_tavern.json", "ce01f3c759ed90e05eb4f44315c28fdd9eabe59a490ac67f1054096dcecb5293"),
    ("fixtures/interior_tavern.json", "279e79300f52fdeb634e6d6cecd4c4cbb0fed57935c7272fad67b78bdb5fc462"),
    ("fixtures/landscape_village.json", "411826a9f931c6f0ba438ba3bd387dfe429ccce044b58dd98fc26c27b1aeefe5"),
    ("fixtures/transition_tower_approach.json", "5cd6a02f59cc58a18886b1a6c55eb32fb4b69309410ee5480aa9c15c0623b358"),
    ("scripts/combat.json", "aa865ff24afeed4414141fdf4e152003ef596f6938435ac7ff128ac5fcb17ec3"),
    ("scripts/interior.json", "26015a80451ba062d2343b7a648789813133d2e5d2286e2b635af75ff2e962a9"),
    ("scripts/landscape.json", "d0c968109b171f8d299098ff76b65cdba42de6d114c2fcf5c5b28f515f0e1e37"),
    ("counterbalance.json", "ef680c1c9049d9c570c66a1fb337fcca664f87abbd4dcca81e6133be2539ff70"),
)

_EXPECTED_SOURCE_CELLS = (
    "E01",
    "E03",
    "E04",
    "E05",
    "E06",
    "E13",
    "E14",
    "E15",
    "E16",
    "E17",
    "E18",
    "C01",
    "C02",
    "C03",
    "C04",
    "C05",
    "C06",
    "C07",
    "C08",
)
_AMENDMENT_ROW = re.compile(
    r"^\| `SP3B-(\d{3})` \| ([EC]\d{2}) \| (\d{2}) \| ([ABD]) \| "
    r"P([14]) \| `([^`]+)` \| ([1-9][0-9]*) \| ([1-9][0-9]*) \|",
    re.MULTILINE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID = re.compile(r"^[0-9a-f]{40,64}$")
_RUN_ID = re.compile(r"^sp3b-[A-Za-z0-9][A-Za-z0-9._-]{0,58}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_ENVIRONMENT = (
    "NEQ_OPEN_BROWSER",
    "PYTHONHASHSEED",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "TZ",
    "LANG",
    "LC_ALL",
)
_STATIC_ROUTE_NAMES = (
    "LLM_PROVIDER",
    "OPENROUTER_CHAT_MODEL",
    "ENABLE_PROVIDER_FALLBACK",
    "OPENROUTER_STRATEGY",
    "OPENROUTER_FULL_MODEL",
    "OPENROUTER_MINI_MODEL",
)
_EXPECTED_REQUESTED_ROUTE = {
    "profile": "production-auto",
    "provider": "openrouter",
    "model": "openrouter/auto",
    "explicit_model": False,
}
_EVIDENCE_CODES = {
    "process": frozenset(
        ("sandbox_prepare_failed", "sandbox_boot_failed", "listener_failed", "evidence_capture_failed")
    ),
    "transport": frozenset(
        (
            "socket_control_failed",
            "dns_failed",
            "tls_failed",
            "connection_reset",
            "transport_timeout",
            "no_transport_error",
        )
    ),
    "provider_status": frozenset(
        ("http_429", "http_5xx", "usable_response_returned", "no_provider_failure")
    ),
    "timing": frozenset(("row_timeout", "row_live_cap", "matrix_live_cap")),
    "artifact_presence": frozenset(
        (
            "required_artifact_missing",
            "required_artifact_present",
            "evidence_capture_failed",
            "transcript_present",
            "transcript_missing",
        )
    ),
}
_INFRASTRUCTURE_EVIDENCE = frozenset(
    (
        ("process", "sandbox_prepare_failed"),
        ("process", "sandbox_boot_failed"),
        ("process", "listener_failed"),
        ("process", "evidence_capture_failed"),
        ("transport", "socket_control_failed"),
        ("transport", "dns_failed"),
        ("transport", "tls_failed"),
        ("transport", "connection_reset"),
        ("provider_status", "http_429"),
        ("provider_status", "http_5xx"),
        ("artifact_presence", "evidence_capture_failed"),
    )
)
_ATTEMPT_KINDS = frozenset(
    ("startup", "resume", "model_turn", "retry", "fallback", "classifier", "child", "provider")
)
_ATTEMPT_OUTCOMES = frozenset(
    ("response", "error", "unknown", "cancelled_before_transport")
)
_ROW_STATES = frozenset(
    ("unstarted", "admitted", "live", "stopped", "classified", "terminal", "missing")
)
_TERMINAL_ROW_STATUSES = frozenset(("PASS", "FAIL", "BLOCKED"))
_LEDGER_FIELDS = frozenset(
    (
        "schema_version",
        "sp3b_run_id",
        "created_at",
        "updated_at",
        "execution_identity_sha256",
        "freeze_artifact_sha256",
        "row_bindings_sha256",
        "budget_baseline",
        "rows",
        "attempts",
        "totals",
        "control",
    )
)
_ROW_PROGRESS_FIELDS = frozenset(
    (
        "attempt_count",
        "state",
        "reason_code",
        "admitted_at",
        "live_started_at",
        "live_started_monotonic",
        "live_finished_at",
        "live_elapsed_seconds",
        "measured_teardown_headroom_seconds",
        "measured_window_seconds_remaining",
        "restart_events",
        "classification",
        "terminal_status",
    )
)


class SP3BError(ValueError):
    """Raised when SP3b inputs, identity, or durable controls are unsafe."""


class SP3BIdentityDriftError(SP3BError):
    """Raised after an immutable execution identity changes or becomes unknown."""


class SP3BPausedError(SP3BError):
    """Raised when a row or request is attempted while owner review is required."""


class SP3BBudgetError(SP3BError):
    """Raised when a cumulative or per-row budget cannot safely admit work."""


def load_sp3b_bindings(
    *,
    prereg_root: str | Path = DEFAULT_PREREG_ROOT,
    amendment_path: str | Path | None = None,
) -> dict[str, Any]:
    """Parse and verify the exact approved 19-row amendment schedule."""
    root_rel = _safe_relative_path(prereg_root, "prereg_root")
    root = _project_path(root_rel, require_exists=True)
    if not root.is_dir():
        raise SP3BError("SP3b preregistration root is not a directory")
    manifest_rel = root_rel / "MANIFEST.sha256"
    manifest_path = _project_path(manifest_rel, require_exists=True)
    manifest_bytes = _read_bytes(manifest_path, "frozen manifest")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_hash != EXPECTED_MANIFEST_SHA256:
        raise SP3BError("frozen 10-entry manifest bytes changed")

    try:
        from scripts.mapping_pilot.manifest import verify_manifest

        records = verify_manifest(root)
    except Exception as exc:
        raise SP3BError("frozen preregistration manifest verification failed") from exc
    expected_entries = list(EXPECTED_MANIFEST_ENTRIES)
    if len(records) != 10 or list(records.items()) != expected_entries:
        raise SP3BError("frozen manifest entries, hashes, or order changed")

    counterbalance_rel = root_rel / "counterbalance.json"
    counterbalance_path = _project_path(counterbalance_rel, require_exists=True)
    counterbalance_raw = _read_bytes(counterbalance_path, "frozen counterbalance")
    if hashlib.sha256(counterbalance_raw).hexdigest() != dict(expected_entries)["counterbalance.json"]:
        raise SP3BError("frozen counterbalance hash changed")
    counterbalance = _strict_json(counterbalance_raw, "frozen counterbalance")
    rows = counterbalance.get("rows") if isinstance(counterbalance, Mapping) else None
    if not isinstance(rows, list):
        raise SP3BError("frozen counterbalance rows are malformed")
    by_id: dict[str, Mapping[str, Any]] = {}
    for source_row in rows:
        if not isinstance(source_row, Mapping):
            raise SP3BError("frozen counterbalance row is malformed")
        source_id = source_row.get("row_id")
        if not isinstance(source_id, str) or source_id in by_id:
            raise SP3BError("frozen counterbalance row identity is duplicated or invalid")
        by_id[source_id] = source_row

    if amendment_path is None:
        amendment_rel = root_rel / AMENDMENT_NAME
    else:
        amendment_rel = _safe_relative_path(amendment_path, "amendment_path")
    amendment_file = _project_path(amendment_rel, require_exists=True)
    amendment_raw = _read_bytes(amendment_file, "SP3b amendment")
    amendment_hash = hashlib.sha256(amendment_raw).hexdigest()
    if amendment_hash != EXPECTED_AMENDMENT_SHA256:
        raise SP3BError("approved SP3b amendment bytes changed")
    try:
        amendment_text = amendment_raw.decode("utf-8")
    except UnicodeError as exc:
        raise SP3BError("SP3b amendment is not valid UTF-8") from exc

    matches = list(_AMENDMENT_ROW.finditer(amendment_text))
    table_rows = re.findall(r"^\| `SP3B-", amendment_text, re.MULTILINE)
    if len(matches) != 19 or len(table_rows) != 19:
        raise SP3BError("SP3b amendment must contain exactly 19 schedule rows")
    bindings: list[dict[str, Any]] = []
    observed_sources: list[str] = []
    for index, match in enumerate(matches, start=1):
        new_number, source_id, order, arm, party, script, repeat, seed = match.groups()
        expected_new_id = "SP3B-%03d" % index
        if new_number != "%03d" % index or source_id != _EXPECTED_SOURCE_CELLS[index - 1]:
            raise SP3BError("SP3b amendment row IDs or filtered order changed")
        source_row = by_id.get(source_id)
        if source_row is None or source_row.get("row_type") != "planned":
            raise SP3BError("SP3b source cell is not an original planned row")
        expected_tuple = (
            int(order),
            arm,
            int(party),
            script,
            int(repeat),
            int(seed),
        )
        frozen_tuple = (
            source_row.get("run_order"),
            source_row.get("arm"),
            source_row.get("party"),
            source_row.get("script"),
            source_row.get("repeat"),
            source_row.get("fixed_seed"),
        )
        if frozen_tuple != expected_tuple:
            raise SP3BError("SP3b amendment binding differs from counterbalance.json")
        observed_sources.append(source_id)
        bindings.append(
            {
                "row_id": expected_new_id,
                "source_cell": source_id,
                "source": copy.deepcopy(dict(source_row)),
            }
        )
    if tuple(observed_sources) != _EXPECTED_SOURCE_CELLS:
        raise SP3BError("SP3b amendment selected an unlisted or replacement cell")

    binding_material = {
        "manifest_sha256": manifest_hash,
        "manifest_entries": expected_entries,
        "amendment_sha256": amendment_hash,
        "rows": bindings,
    }
    return {
        "manifest_sha256": manifest_hash,
        "manifest_entries": dict(expected_entries),
        "amendment_sha256": amendment_hash,
        "rows": bindings,
        "row_bindings_sha256": _canonical_hash(binding_material),
    }


def load_budget_baseline(
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the hash-bound, verified primary SP3 closeout totals."""
    selected_path = PRIMARY_CLOSEOUT_RELATIVE_PATH if source_path is None else source_path
    relative = _safe_relative_path(selected_path, "primary closeout path", require_tmp=True)
    if relative != PRIMARY_CLOSEOUT_RELATIVE_PATH:
        raise SP3BError("SP3b baseline source path is not the verified primary closeout")
    path = _project_path(relative, require_exists=True)
    raw = _read_bytes(path, "primary SP3 closeout")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PRIMARY_CLOSEOUT_SHA256:
        raise SP3BError("primary SP3 closeout hash changed")
    value = _strict_json(raw, "primary SP3 closeout")
    totals = value.get("matrix_totals") if isinstance(value, Mapping) else None
    if not isinstance(totals, Mapping) or set(totals) != {
        "matrix_attempts",
        "matrix_elapsed_seconds",
    }:
        raise SP3BError("primary SP3 closeout totals are malformed")
    attempts = totals.get("matrix_attempts")
    elapsed = totals.get("matrix_elapsed_seconds")
    if type(attempts) is not int or attempts != BASELINE_ATTEMPTS:
        raise SP3BError("primary SP3 attempt baseline is unknown or mismatched")
    if not _finite_nonnegative(elapsed) or float(elapsed) != BASELINE_LIVE_SECONDS:
        raise SP3BError("primary SP3 live-time baseline is unknown or mismatched")
    if value.get("no_reserves_or_replays") is not True:
        raise SP3BError("primary SP3 closeout does not verify no reserves or replays")
    if value.get("original_26_slot_records_unchanged") is not True:
        raise SP3BError("primary SP3 closeout does not verify immutable original slots")
    return {
        "source_path": relative.as_posix(),
        "source_sha256": digest,
        "matrix_attempts": attempts,
        "matrix_elapsed_seconds": float(elapsed),
    }


def classify_pre_content(evidence: Any) -> dict[str, Any]:
    """Classify only allowlisted process/transport/status/timing/artifact evidence.

    Content, transcript, response text, score, and outcome-quality fields are
    never accepted or copied. Unknown evidence is UNRESOLVED, not infrastructure.
    """
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        return _unresolved_classification("evidence_missing_or_malformed")
    normalized: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"kind", "code", "source"}:
            return _unresolved_classification("evidence_not_allowlisted")
        kind = item.get("kind")
        code = item.get("code")
        source = item.get("source")
        if (
            not isinstance(kind, str)
            or kind not in _EVIDENCE_CODES
            or not isinstance(code, str)
            or code not in _EVIDENCE_CODES[kind]
        ):
            return _unresolved_classification("evidence_not_allowlisted")
        if not isinstance(source, str):
            return _unresolved_classification("evidence_source_unknown")
        try:
            source_path = _safe_relative_path(source, "classification evidence source", require_tmp=True)
            _project_path(source_path, require_exists=False)
        except SP3BError:
            return _unresolved_classification("evidence_source_unsafe")
        normalized.append({"kind": kind, "code": code, "source": source_path.as_posix()})

    if any((item["kind"], item["code"]) in _INFRASTRUCTURE_EVIDENCE for item in normalized):
        return {
            "classification": "INFRASTRUCTURE",
            "reason": "objective_pre_content_infrastructure_evidence",
            "evidence": normalized,
        }
    if any(
        item["kind"] == "provider_status" and item["code"] == "usable_response_returned"
        for item in normalized
    ):
        return {
            "classification": "CONTENT/RESULT",
            "reason": "usable_response_without_independent_infrastructure_cause",
            "evidence": normalized,
        }
    return _unresolved_classification(
        "no_independent_pre_content_infrastructure_cause", normalized
    )


def capture_environment_identity() -> dict[str, Any]:
    """Capture actual repository/runtime identity without reading credentials.

    Only the explicitly selected non-secret environment names and AST-literal
    route settings are collected. config.py and environment variables outside
    the allowlist are not opened or hashed.
    """
    commit = _git_output(["rev-parse", "HEAD"])
    tree = _git_output(["rev-parse", "HEAD^{tree}"])
    status = _git_output(["status", "--porcelain=v1", "-z", "--untracked-files=all"], raw=True)
    if status:
        raise SP3BError("execution identity requires a clean worktree")
    tracked_raw = _git_output(["ls-files", "-z"], raw=True)
    tracked_paths = [os.fsdecode(part) for part in tracked_raw.split(b"\0") if part]
    if not tracked_paths:
        raise SP3BError("execution identity has no tracked source tree")

    tracked_hashes: dict[str, str] = {}
    tree_digest = hashlib.sha256()
    source_hashes: dict[str, str] = {}
    tool_hashes: dict[str, str] = {}
    prompt_hashes: dict[str, str] = {}
    for raw_relative in sorted(tracked_paths):
        relative = _safe_relative_path(raw_relative, "tracked source path")
        if _is_sensitive_path(relative):
            continue
        path = _project_path(relative, require_exists=True)
        if not path.is_file():
            raise SP3BError("tracked source tree contains a non-file path")
        digest = hashlib.sha256(_read_bytes(path, "tracked source file")).hexdigest()
        normalized = relative.as_posix()
        tracked_hashes[normalized] = digest
        tree_digest.update(normalized.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(bytes.fromhex(digest))
        if relative.suffix == ".py":
            source_hashes[normalized] = digest
        if relative.parts[:2] == ("scripts", "mapping_pilot") or normalized in {
            "scripts/capture_drive.py",
            "scripts/capture_evidence.py",
            "scripts/seed_combat_capture.py",
        }:
            tool_hashes[normalized] = digest
        if relative.parts and relative.parts[0] == "prompts":
            prompt_hashes[normalized] = digest
    if not source_hashes or not tool_hashes or not prompt_hashes:
        raise SP3BError("execution identity is missing source, tool, or prompt hashes")

    lock_rel = Path("requirements-lock.txt")
    lock_path = _project_path(lock_rel, require_exists=True)
    lock_raw = _read_bytes(lock_path, "dependency lock")
    dependency_versions = _installed_locked_versions(lock_raw)
    route_rel = Path("model_config.py")
    route_path = _project_path(route_rel, require_exists=True)
    static_route = _safe_static_route_config(_read_bytes(route_path, "static model route"))

    bindings = load_sp3b_bindings()
    baseline = load_budget_baseline()
    prereg_prefix = "plans/v2-mapping-pilot-prereg/"
    input_hashes = {
        prereg_prefix + path: digest
        for path, digest in bindings["manifest_entries"].items()
    }
    input_hashes[prereg_prefix + "MANIFEST.sha256"] = bindings["manifest_sha256"]
    input_hashes[prereg_prefix + "SP3b-amendment.md"] = bindings["amendment_sha256"]
    input_hashes[baseline["source_path"]] = baseline["source_sha256"]
    profile_hashes = {
        prereg_prefix + "README.md": input_hashes[prereg_prefix + "README.md"],
        prereg_prefix + "rubric.md": input_hashes[prereg_prefix + "rubric.md"],
        prereg_prefix + "SP3b-amendment.md": bindings["amendment_sha256"],
    }
    return {
        "source_commit_sha": commit,
        "source_tree_oid": tree,
        "source_content_sha256": tree_digest.hexdigest(),
        "status_digest_sha256": hashlib.sha256(status).hexdigest(),
        "requirements_lock_sha256": hashlib.sha256(lock_raw).hexdigest(),
        "interpreter": {
            "executable": str(Path(sys.executable).resolve()),
            "implementation": sys.implementation.name,
            "version": sys.version,
            "platform": sys.platform,
        },
        "dependency_versions": dependency_versions,
        "environment": {name: os.environ.get(name) for name in _SAFE_ENVIRONMENT},
        "requested_route": dict(_EXPECTED_REQUESTED_ROUTE),
        "static_route_config": static_route,
        "prompt_hashes": prompt_hashes,
        "tool_hashes": tool_hashes,
        "source_hashes": source_hashes,
        "input_hashes": input_hashes,
        "profile_hashes": profile_hashes,
        "tracked_source_file_count": len(tracked_hashes),
    }


class SP3BExecution:
    """Parent-owned stable-root ledger for SP3b identity, budgets, and admission.

    ``freeze_authorizer`` is an external trust seam. This module creates only a
    DRAFT identity artifact and has no operation that can promote it to FREEZE.
    H3 must provide a callback that validates the actual Overseer ruling.
    """

    def __init__(
        self,
        run_id: str,
        *,
        ledger_root: str | Path | None = None,
        identity_provider: Callable[[], Mapping[str, Any]] | None = None,
        freeze_authorizer: Callable[[str, str], Mapping[str, Any] | None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise SP3BError("SP3b run_id must be a new sp3b-prefixed identity")
        if run_id == PRIMARY_SP3_RUN_ID:
            raise SP3BError("SP3b run_id cannot reuse the primary SP3 identity")
        self.run_id = run_id
        selected_root = DEFAULT_SP3B_ROOT if ledger_root is None else ledger_root
        self.ledger_root = _safe_relative_path(selected_root, "ledger_root", require_tmp=True)
        canonical_root = _safe_relative_path(DEFAULT_SP3B_ROOT, "default ledger root", require_tmp=True)
        if self.ledger_root != canonical_root:
            raise SP3BError("SP3b requires one stable cumulative ledger root")
        self._root = _project_path(self.ledger_root, require_exists=False)
        self._identity_provider = identity_provider or capture_environment_identity
        if not callable(self._identity_provider):
            raise SP3BError("identity_provider must be callable")
        self._freeze_authorizer = freeze_authorizer
        self._monotonic = monotonic
        self._wall_clock = wall_clock

    @property
    def ledger_path(self) -> Path:
        return self._root / LEDGER_NAME

    @property
    def freeze_path(self) -> Path:
        return self._root / FREEZE_NAME

    def initialize(self) -> dict[str, Any]:
        """Bind one immutable DRAFT freeze and cumulative ledger under this root."""
        self._ensure_root()
        with _exclusive_root_lock(self._root):
            ledger_exists = self.ledger_path.exists() or self.ledger_path.is_symlink()
            freeze_exists = self.freeze_path.exists() or self.freeze_path.is_symlink()
            if ledger_exists or freeze_exists:
                if not ledger_exists or not freeze_exists:
                    raise SP3BError("partial SP3b root cannot be silently repaired")
                ledger = self._read_ledger()
                if ledger["sp3b_run_id"] != self.run_id:
                    raise SP3BError("stable SP3b root is already bound to another run_id")
                self._verify_fresh_identity_or_stop(ledger)
                return copy.deepcopy(ledger)

            identity = self._fresh_identity()
            identity_hash = _canonical_hash(identity)
            bindings = load_sp3b_bindings()
            timestamp = _timestamp(self._wall_clock())
            freeze = {
                "schema_version": 1,
                "status": "DRAFT",
                "execution_authorized": False,
                "authorization_status": "awaiting_specific_overseer_sp3b_freeze",
                "sp3b_run_id": self.run_id,
                "created_at": timestamp,
                "execution_identity_sha256": identity_hash,
                "identity": identity,
            }
            if self.freeze_path.exists() or self.freeze_path.is_symlink():
                raise SP3BError("execution freeze artifact already exists; overwrite refused")
            self._write_json(self.freeze_path, freeze)
            freeze_hash = hashlib.sha256(_read_bytes(self.freeze_path, "execution freeze")).hexdigest()

            baseline = load_budget_baseline()
            rows = []
            for binding in bindings["rows"]:
                rows.append(
                    {
                        **copy.deepcopy(binding),
                        "attempt_count": 0,
                        "state": "unstarted",
                        "reason_code": None,
                        "admitted_at": None,
                        "live_started_at": None,
                        "live_started_monotonic": None,
                        "live_finished_at": None,
                        "live_elapsed_seconds": 0.0,
                        "measured_teardown_headroom_seconds": None,
                        "measured_window_seconds_remaining": None,
                        "restart_events": [],
                        "classification": None,
                        "terminal_status": None,
                    }
                )
            ledger = {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "sp3b_run_id": self.run_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "execution_identity_sha256": identity_hash,
                "freeze_artifact_sha256": freeze_hash,
                "row_bindings_sha256": bindings["row_bindings_sha256"],
                "budget_baseline": baseline,
                "rows": rows,
                "attempts": [],
                "totals": {},
                "control": {
                    "paused": False,
                    "infrastructure_failure_streak": [],
                    "pauses": [],
                    "identity_stopped": False,
                    "identity_stop_reason": None,
                    "stopped": False,
                    "stop_reason": None,
                    "classification_sequence": 0,
                },
            }
            _refresh_totals(ledger)
            self._validate_ledger(ledger)
            self._write_json(self.ledger_path, ledger)
            return copy.deepcopy(ledger)

    def snapshot(self) -> dict[str, Any]:
        """Read and validate the bound ledger without changing its state."""
        self._ensure_root_exists()
        with _exclusive_root_lock(self._root):
            ledger = self._read_ledger()
            self._verify_fresh_identity_or_stop(ledger)
            return copy.deepcopy(ledger)

    def admit_row(
        self,
        row_id: str,
        *,
        measured_teardown_headroom_seconds: float,
        measured_window_seconds_remaining: float,
    ) -> dict[str, Any]:
        """Durably reserve the next filtered row before H3 starts preparation."""
        headroom = _required_seconds(measured_teardown_headroom_seconds, "teardown headroom")
        window = _required_seconds(measured_window_seconds_remaining, "window remaining")
        with self._transaction(require_freeze=True) as ledger:
            control = ledger["control"]
            self._require_not_stopped_or_paused(control)
            if ledger["totals"]["matrix_attempts"] >= TOTAL_ATTEMPT_CAP:
                raise SP3BBudgetError("SP3b cumulative attempt cap leaves no request budget")
            active = next(
                (
                    item
                    for item in ledger["rows"]
                    if item["state"] in ("admitted", "live", "stopped", "classified")
                ),
                None,
            )
            if active is not None:
                raise SP3BError("the prior SP3b row must be terminal before the next row is admitted")
            row = self._find_row(ledger, row_id)
            next_row = next((item for item in ledger["rows"] if item["state"] == "unstarted"), None)
            if next_row is None or next_row["row_id"] != row_id:
                raise SP3BError("SP3b rows must be admitted once in filtered counterbalance order")
            if row["state"] != "unstarted":
                raise SP3BError("SP3b row is already admitted, terminal, or missing")
            self._require_budget_headroom(ledger, row, headroom, window, at_request=False)
            row["state"] = "admitted"
            row["admitted_at"] = _timestamp(self._wall_clock())
            row["measured_teardown_headroom_seconds"] = headroom
            row["measured_window_seconds_remaining"] = window
            _refresh_totals(ledger)
        return self.snapshot()

    def start_live_interval(
        self,
        row_id: str,
        *,
        measured_teardown_headroom_seconds: float,
        measured_window_seconds_remaining: float,
    ) -> dict[str, Any]:
        """Start one continuous launch-through-final-teardown interval.

        A server restart does not reset the stored start anchor; call
        ``record_restart`` instead so restart time remains inside this interval.
        """
        headroom = _required_seconds(measured_teardown_headroom_seconds, "teardown headroom")
        window = _required_seconds(measured_window_seconds_remaining, "window remaining")
        with self._transaction(require_freeze=True) as ledger:
            self._require_not_stopped_or_paused(ledger["control"])
            row = self._find_row(ledger, row_id)
            if row["state"] != "admitted":
                raise SP3BError("row must be admitted before its first launch")
            self._require_budget_headroom(ledger, row, headroom, window, at_request=False)
            now_monotonic = self._checked_clock(self._monotonic(), "monotonic clock")
            row["state"] = "live"
            row["live_started_at"] = _timestamp(self._wall_clock())
            row["live_started_monotonic"] = now_monotonic
            row["measured_teardown_headroom_seconds"] = headroom
            row["measured_window_seconds_remaining"] = window
            row["live_elapsed_seconds"] = 0.0
            _refresh_totals(ledger)
        return self.snapshot()

    def record_restart(self, row_id: str) -> dict[str, Any]:
        """Record a restart without resetting the row's live-time anchor."""
        with self._transaction(require_freeze=True) as ledger:
            self._require_not_stopped_or_paused(ledger["control"])
            row = self._find_row(ledger, row_id)
            if row["state"] != "live":
                raise SP3BError("only a live row may record a restart")
            elapsed = self._active_elapsed(row)
            row["live_elapsed_seconds"] = elapsed
            row["restart_events"].append(
                {"recorded_at": _timestamp(self._wall_clock()), "elapsed_seconds": elapsed}
            )
            _refresh_totals(ledger)
        return self.snapshot()

    def admit_provider_attempt(
        self,
        row_id: str,
        attempt_id: str,
        *,
        kind: str,
        measured_teardown_headroom_seconds: float,
        measured_window_seconds_remaining: float,
    ) -> dict[str, Any]:
        """Atomically count an attempt before a parent or child sends a request.

        Each retry, fallback, classifier, lifecycle, or child request must call
        this against the same stable root. An admitted attempt is charged even if
        its eventual outcome is an error or is lost during process interruption.
        """
        if not isinstance(attempt_id, str) or not _TOKEN.fullmatch(attempt_id):
            raise SP3BError("attempt_id is invalid")
        if not isinstance(kind, str) or kind not in _ATTEMPT_KINDS:
            raise SP3BError("provider attempt kind is not allowlisted")
        headroom = _required_seconds(measured_teardown_headroom_seconds, "teardown headroom")
        window = _required_seconds(measured_window_seconds_remaining, "window remaining")
        with self._transaction(require_freeze=True) as ledger:
            self._require_not_stopped_or_paused(ledger["control"])
            row = self._find_row(ledger, row_id)
            if row["state"] != "live":
                raise SP3BError("provider request admission requires an active live row")
            if any(item["attempt_id"] == attempt_id for item in ledger["attempts"]):
                raise SP3BError("attempt_id is already charged in the durable SP3b ledger")
            elapsed = self._active_elapsed(row)
            row["live_elapsed_seconds"] = elapsed
            self._require_budget_headroom(
                ledger,
                row,
                headroom,
                window,
                at_request=True,
            )
            if row["attempt_count"] >= ROW_ATTEMPT_CAP:
                raise SP3BBudgetError("SP3b per-row attempt cap reached")
            if ledger["totals"]["matrix_attempts"] >= TOTAL_ATTEMPT_CAP:
                raise SP3BBudgetError("SP3b cumulative attempt cap reached")
            ledger["attempts"].append(
                {
                    "sequence": len(ledger["attempts"]) + 1,
                    "attempt_id": attempt_id,
                    "row_id": row_id,
                    "kind": kind,
                    "admitted_at": _timestamp(self._wall_clock()),
                    "outcome": None,
                }
            )
            row["attempt_count"] += 1
            row["measured_teardown_headroom_seconds"] = headroom
            row["measured_window_seconds_remaining"] = window
            _refresh_totals(ledger)
        return self.snapshot()

    def record_attempt_outcome(self, attempt_id: str, outcome: str) -> dict[str, Any]:
        """Attach one bounded outcome to an already charged attempt."""
        if not isinstance(outcome, str) or outcome not in _ATTEMPT_OUTCOMES:
            raise SP3BError("provider attempt outcome is not allowlisted")
        with self._transaction(closeout_only=True) as ledger:
            attempt = next(
                (item for item in ledger["attempts"] if item["attempt_id"] == attempt_id),
                None,
            )
            if attempt is None:
                raise SP3BError("provider attempt was not durably admitted")
            if attempt["outcome"] is not None:
                raise SP3BError("provider attempt outcome is immutable")
            attempt["outcome"] = outcome
        return copy.deepcopy(ledger)

    def finish_live_interval(self, row_id: str) -> dict[str, Any]:
        """Close the current live interval at final teardown, without clamping."""
        with self._transaction(closeout_only=True) as ledger:
            row = self._find_row(ledger, row_id)
            if row["state"] != "live":
                raise SP3BError("row has no active live interval")
            elapsed = self._active_elapsed(row)
            row["live_elapsed_seconds"] = elapsed
            row["live_finished_at"] = _timestamp(self._wall_clock())
            row["state"] = "stopped"
            matrix_elapsed = BASELINE_LIVE_SECONDS + sum(
                float(item["live_elapsed_seconds"]) for item in ledger["rows"]
            )
            if elapsed >= ROW_LIVE_SECONDS_CAP or matrix_elapsed >= TOTAL_LIVE_SECONDS_CAP:
                ledger["control"]["stopped"] = True
                ledger["control"]["stop_reason"] = "live_time_cap_reached_during_teardown"
            _refresh_totals(ledger)
        return copy.deepcopy(ledger)

    def classify_row(self, row_id: str, evidence: Any) -> dict[str, Any]:
        """Atomically persist deterministic pre-content classification and pause."""
        decision = classify_pre_content(evidence)
        with self._transaction(closeout_only=True) as ledger:
            row = self._find_row(ledger, row_id)
            if row["state"] not in ("admitted", "stopped"):
                raise SP3BError("pre-content classification requires a stopped row")
            row_index = ledger["rows"].index(row)
            if any(
                prior["state"] not in ("terminal", "missing")
                for prior in ledger["rows"][:row_index]
            ):
                raise SP3BError("SP3b classification must follow filtered row order")
            if row["classification"] is not None:
                raise SP3BError("pre-content classification is immutable")
            sequence = ledger["control"]["classification_sequence"] + 1
            recorded = {
                **copy.deepcopy(decision),
                "sequence": sequence,
                "recorded_at": _timestamp(self._wall_clock()),
            }
            row["classification"] = recorded
            row["state"] = "classified"
            control = ledger["control"]
            control["classification_sequence"] = sequence
            if decision["classification"] == "INFRASTRUCTURE":
                control["infrastructure_failure_streak"].append(row_id)
            else:
                control["infrastructure_failure_streak"] = []
            if len(control["infrastructure_failure_streak"]) >= 3:
                triggers = control["infrastructure_failure_streak"][-3:]
                control["pauses"].append(
                    {
                        "pause_id": "sp3b-pause-%03d" % len(control["pauses"] + [None]),
                        "triggering_row_ids": list(triggers),
                        "triggering_classification_sequences": [
                            self._find_row(ledger, trigger)["classification"]["sequence"]
                            for trigger in triggers
                        ],
                        "triggered_at": recorded["recorded_at"],
                        "owner_review": None,
                        "resumed_at": None,
                    }
                )
                control["paused"] = True
        return copy.deepcopy(ledger)

    def finish_row(self, row_id: str, *, status: str, reason_code: str) -> dict[str, Any]:
        """Record an immutable terminal SP3b row outcome after classification."""
        if not isinstance(status, str) or status not in _TERMINAL_ROW_STATUSES:
            raise SP3BError("terminal row status must be PASS, FAIL, or BLOCKED")
        if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
            raise SP3BError("row reason_code must be a safe non-content token")
        with self._transaction(closeout_only=True) as ledger:
            row = self._find_row(ledger, row_id)
            if row["state"] != "classified" or row["classification"] is None:
                raise SP3BError("row must have an immutable pre-content classification")
            if status == "PASS" and row["classification"]["classification"] != "CONTENT/RESULT":
                raise SP3BError("only a resolved non-infrastructure row can be PASS")
            row["state"] = "terminal"
            row["terminal_status"] = status
            row["reason_code"] = reason_code
        return copy.deepcopy(ledger)

    def mark_unrun_missing(self, *, reason_code: str) -> dict[str, Any]:
        """Stop the execution and mark every still-unstarted approved row missing."""
        if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
            raise SP3BError("missing-row reason_code must be a safe non-content token")
        with self._transaction(closeout_only=True) as ledger:
            control = ledger["control"]
            cap_stop = control["stop_reason"] == "live_time_cap_reached_during_teardown"
            if control["stopped"] and not cap_stop:
                raise SP3BError("SP3b execution stop is immutable")
            if any(
                row["state"] in ("admitted", "live", "stopped", "classified")
                for row in ledger["rows"]
            ):
                raise SP3BError("the current SP3b row must be closed before marking later rows missing")
            if not control["stopped"]:
                control["stopped"] = True
                control["stop_reason"] = reason_code
            for row in ledger["rows"]:
                if row["state"] == "unstarted":
                    row["state"] = "missing"
                    row["reason_code"] = reason_code
        return copy.deepcopy(ledger)

    def authorize_resume(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        """Clear a pause only with explicit owner review and checked authorization."""
        with self._transaction(require_freeze=True) as ledger:
            control = ledger["control"]
            if not control["paused"] or not control["pauses"]:
                raise SP3BPausedError("SP3b is not paused for owner review")
            if control["stopped"]:
                raise SP3BPausedError("stopped SP3b execution cannot be resumed")
            pause = control["pauses"][-1]
            if pause["owner_review"] is not None or pause["resumed_at"] is not None:
                raise SP3BPausedError("SP3b pause review is immutable")
            normalized = _validate_resume_authorization(
                authorization,
                run_id=self.run_id,
                pause_id=pause["pause_id"],
            )
            pause["owner_review"] = normalized
            pause["resumed_at"] = _timestamp(self._wall_clock())
            control["paused"] = False
            control["infrastructure_failure_streak"] = []
        return self.snapshot()

    @contextmanager
    def _transaction(
        self,
        *,
        require_freeze: bool = False,
        closeout_only: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Serialize ledger writes; closeout mode cannot authorize new execution."""
        self._ensure_root_exists()
        with _exclusive_root_lock(self._root):
            ledger = self._read_ledger()
            if closeout_only:
                if require_freeze:
                    raise SP3BError("closeout-only transactions cannot authorize new execution")
                control = ledger["control"]
                if not control["identity_stopped"]:
                    try:
                        current_hash = _canonical_hash(self._fresh_identity())
                    except Exception:
                        stop_reason = "fresh_identity_unknown_or_invalid"
                    else:
                        stop_reason = (
                            "immutable_execution_identity_changed"
                            if current_hash != ledger["execution_identity_sha256"]
                            else None
                        )
                    if stop_reason is not None:
                        self._latch_identity_stop(ledger, stop_reason)
            else:
                self._verify_fresh_identity_or_stop(ledger)
            if require_freeze:
                self._require_freeze_authorization(ledger)
            yield ledger
            ledger["updated_at"] = _timestamp(self._wall_clock())
            _refresh_totals(ledger)
            self._validate_ledger(ledger)
            self._write_json(self.ledger_path, ledger, overwrite=True)

    def _fresh_identity(self) -> dict[str, Any]:
        try:
            capture = self._identity_provider()
            normalized_capture = _validate_capture_identity(capture)
            bindings = load_sp3b_bindings()
            baseline = load_budget_baseline()
        except SP3BError:
            raise
        except Exception as exc:
            raise SP3BError("execution identity capture failed closed") from exc
        identity = {
            "capture": normalized_capture,
            "manifest_sha256": bindings["manifest_sha256"],
            "manifest_entries": bindings["manifest_entries"],
            "amendment_sha256": bindings["amendment_sha256"],
            "rows": bindings["rows"],
            "row_bindings_sha256": bindings["row_bindings_sha256"],
            "budget_baseline": baseline,
            "controls": {
                "total_attempt_cap": TOTAL_ATTEMPT_CAP,
                "total_live_seconds_cap": TOTAL_LIVE_SECONDS_CAP,
                "row_attempt_cap": ROW_ATTEMPT_CAP,
                "row_live_seconds_cap": ROW_LIVE_SECONDS_CAP,
                "baseline_attempts": BASELINE_ATTEMPTS,
                "baseline_live_seconds": BASELINE_LIVE_SECONDS,
            },
        }
        _canonical_json(identity)
        return identity

    def _verify_fresh_identity_or_stop(self, ledger: dict[str, Any]) -> None:
        control = ledger["control"]
        if control["identity_stopped"]:
            raise SP3BIdentityDriftError("SP3b execution identity is permanently stopped")
        try:
            current_hash = _canonical_hash(self._fresh_identity())
        except Exception as exc:
            self._latch_identity_stop(ledger, "fresh_identity_unknown_or_invalid")
            raise SP3BIdentityDriftError(
                "fresh SP3b identity is unavailable; execution permanently stopped"
            ) from exc
        if current_hash != ledger["execution_identity_sha256"]:
            self._latch_identity_stop(ledger, "immutable_execution_identity_changed")
            raise SP3BIdentityDriftError(
                "SP3b identity drift permanently stopped the entire execution"
            )

    def _latch_identity_stop(
        self,
        ledger: dict[str, Any],
        reason: str,
        *,
        persist: bool = True,
    ) -> None:
        control = ledger["control"]
        control["identity_stopped"] = True
        control["identity_stop_reason"] = reason
        for row in ledger["rows"]:
            if row["state"] == "unstarted" or (
                row["state"] == "admitted" and row["live_started_at"] is None
            ):
                row["state"] = "missing"
                row["reason_code"] = "identity_drift"
        ledger["updated_at"] = _timestamp(self._wall_clock())
        _refresh_totals(ledger)
        self._validate_ledger(ledger)
        if persist:
            self._write_json(self.ledger_path, ledger, overwrite=True)

    def _require_freeze_authorization(self, ledger: Mapping[str, Any]) -> None:
        if self._freeze_authorizer is None:
            raise SP3BError("execution freeze is DRAFT; a verified external SP3b FREEZE is required")
        try:
            authorization = self._freeze_authorizer(
                ledger["freeze_artifact_sha256"], ledger["execution_identity_sha256"]
            )
        except Exception as exc:
            raise SP3BError("external SP3b FREEZE authorization could not be verified") from exc
        _validate_freeze_authorization(
            authorization,
            freeze_hash=ledger["freeze_artifact_sha256"],
            identity_hash=ledger["execution_identity_sha256"],
        )

    def _read_ledger(self) -> dict[str, Any]:
        _reject_symlink_components(self._root, self.ledger_path)
        _reject_symlink_components(self._root, self.freeze_path)
        if not self.ledger_path.is_file() or not self.freeze_path.is_file():
            raise SP3BError("durable SP3b ledger or draft freeze is unavailable")
        ledger = _strict_json(_read_bytes(self.ledger_path, "SP3b ledger"), "SP3b ledger")
        freeze_raw = _read_bytes(self.freeze_path, "SP3b draft freeze")
        freeze_hash = hashlib.sha256(freeze_raw).hexdigest()
        if not isinstance(ledger, dict):
            raise SP3BError("durable SP3b ledger is not an object")
        if freeze_hash != ledger.get("freeze_artifact_sha256"):
            raise SP3BError("SP3b draft freeze is missing or changed")
        freeze = _strict_json(freeze_raw, "SP3b draft freeze")
        if (
            not isinstance(freeze, Mapping)
            or set(freeze) != {
                "schema_version",
                "status",
                "execution_authorized",
                "authorization_status",
                "sp3b_run_id",
                "created_at",
                "execution_identity_sha256",
                "identity",
            }
            or freeze.get("schema_version") != 1
            or freeze.get("status") != "DRAFT"
            or freeze.get("execution_authorized") is not False
            or freeze.get("authorization_status") != "awaiting_specific_overseer_sp3b_freeze"
            or freeze.get("sp3b_run_id") != self.run_id
            or freeze.get("execution_identity_sha256") != ledger.get("execution_identity_sha256")
            or _canonical_hash(freeze.get("identity")) != ledger.get("execution_identity_sha256")
        ):
            raise SP3BError("SP3b freeze is not the bound immutable DRAFT artifact")
        _parse_timestamp(freeze.get("created_at"), "freeze created_at")
        self._validate_ledger(ledger)
        if ledger.get("sp3b_run_id") != self.run_id:
            raise SP3BError("SP3b ledger is bound to a different run_id")
        return ledger

    def _validate_ledger(self, ledger: Mapping[str, Any]) -> None:
        if not isinstance(ledger, Mapping) or set(ledger) != _LEDGER_FIELDS:
            raise SP3BError("SP3b ledger fields are malformed")
        if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise SP3BError("SP3b ledger schema version is invalid")
        if ledger.get("sp3b_run_id") != self.run_id:
            raise SP3BError("SP3b ledger run identity changed")
        _parse_timestamp(ledger.get("created_at"), "ledger created_at")
        _parse_timestamp(ledger.get("updated_at"), "ledger updated_at")
        for field in ("execution_identity_sha256", "freeze_artifact_sha256", "row_bindings_sha256"):
            if not isinstance(ledger.get(field), str) or not _SHA256.fullmatch(ledger[field]):
                raise SP3BError("SP3b ledger hash binding is invalid")
        baseline = ledger.get("budget_baseline")
        if baseline != {
            "source_path": PRIMARY_CLOSEOUT_RELATIVE_PATH.as_posix(),
            "source_sha256": PRIMARY_CLOSEOUT_SHA256,
            "matrix_attempts": BASELINE_ATTEMPTS,
            "matrix_elapsed_seconds": BASELINE_LIVE_SECONDS,
        }:
            raise SP3BError("SP3b ledger cumulative baseline changed or is unknown")

        bindings = load_sp3b_bindings()
        if ledger["row_bindings_sha256"] != bindings["row_bindings_sha256"]:
            raise SP3BError("SP3b row binding hash changed")
        raw_rows = ledger.get("rows")
        if not isinstance(raw_rows, list) or len(raw_rows) != 19:
            raise SP3BError("SP3b ledger must contain exactly 19 approved rows")
        rows_by_id: dict[str, Mapping[str, Any]] = {}
        attempts_by_row: dict[str, int] = {binding["row_id"]: 0 for binding in bindings["rows"]}
        for row, binding in zip(raw_rows, bindings["rows"]):
            if not isinstance(row, Mapping):
                raise SP3BError("SP3b ledger row is malformed")
            if set(row) != set(binding) | _ROW_PROGRESS_FIELDS:
                raise SP3BError("SP3b ledger row fields changed")
            for key, value in binding.items():
                if row.get(key) != value:
                    raise SP3BError("SP3b row binding or original source cell changed")
            if not isinstance(row.get("state"), str) or row["state"] not in _ROW_STATES:
                raise SP3BError("SP3b row state is invalid")
            _validate_optional_reason(row.get("reason_code"))
            for time_field in (
                "admitted_at",
                "live_started_at",
                "live_finished_at",
            ):
                if row.get(time_field) is not None:
                    _parse_timestamp(row[time_field], "row " + time_field)
            if not _finite_nonnegative(row.get("live_elapsed_seconds")):
                raise SP3BError("SP3b row live-time total is unknown or malformed")
            attempt_count = row.get("attempt_count")
            if type(attempt_count) is not int or not 0 <= attempt_count <= ROW_ATTEMPT_CAP:
                raise SP3BError("SP3b row attempt count is outside its immutable cap")
            if row.get("live_started_monotonic") is not None and not _finite_nonnegative(
                row["live_started_monotonic"]
            ):
                raise SP3BError("SP3b row monotonic start is malformed")
            for field in (
                "measured_teardown_headroom_seconds",
                "measured_window_seconds_remaining",
            ):
                value = row.get(field)
                if value is not None and not _finite_nonnegative(value):
                    raise SP3BError("SP3b row safety measurement is malformed")
            restart_events = row.get("restart_events")
            if not isinstance(restart_events, list):
                raise SP3BError("SP3b restart events are malformed")
            for event in restart_events:
                if not isinstance(event, Mapping) or set(event) != {
                    "recorded_at",
                    "elapsed_seconds",
                }:
                    raise SP3BError("SP3b restart event fields are malformed")
                _parse_timestamp(event.get("recorded_at"), "restart recorded_at")
                if not _finite_nonnegative(event.get("elapsed_seconds")):
                    raise SP3BError("SP3b restart elapsed time is malformed")
            classification = row.get("classification")
            if classification is not None:
                _validate_classification_record(classification)
            status = row.get("terminal_status")
            if status is not None and (
                not isinstance(status, str) or status not in _TERMINAL_ROW_STATUSES
            ):
                raise SP3BError("SP3b terminal row status is invalid")
            if row["state"] == "terminal" and (status is None or classification is None):
                raise SP3BError("SP3b terminal row lacks status or pre-content classification")
            if row["state"] == "terminal" and row.get("reason_code") is None:
                raise SP3BError("SP3b terminal row lacks its reason code")
            if (
                row["state"] == "terminal"
                and status == "PASS"
                and classification["classification"] != "CONTENT/RESULT"
            ):
                raise SP3BError("unresolved or infrastructure SP3b row cannot be PASS")
            if row["state"] != "terminal" and status is not None:
                raise SP3BError("nonterminal SP3b row has a terminal status")
            if row["state"] == "missing" and (status is not None or not row.get("reason_code")):
                raise SP3BError("SP3b missing row needs a reason and no terminal score")
            if row["state"] == "unstarted" and (
                row.get("admitted_at") is not None
                or row.get("live_started_at") is not None
                or row.get("live_finished_at") is not None
                or attempt_count != 0
                or classification is not None
            ):
                raise SP3BError("unstarted SP3b row contains execution progress")
            if row["state"] == "admitted" and row.get("admitted_at") is None:
                raise SP3BError("admitted SP3b row lacks its durable admission timestamp")
            if row["state"] == "admitted" and (
                row.get("live_started_at") is not None
                or row.get("live_started_monotonic") is not None
                or row.get("live_finished_at") is not None
            ):
                raise SP3BError("admitted SP3b row already contains live-interval state")
            if row["state"] == "live" and (
                row.get("admitted_at") is None
                or row.get("live_started_at") is None
                or row.get("live_started_monotonic") is None
                or row.get("live_finished_at") is not None
            ):
                raise SP3BError("SP3b active live interval anchors are incomplete")
            if row["state"] == "stopped" and (
                row.get("live_started_at") is None or row.get("live_finished_at") is None
            ):
                raise SP3BError("stopped SP3b row lacks its complete live interval")
            if row["state"] in ("stopped", "classified", "terminal") and row.get("live_started_at") is not None and row.get("live_finished_at") is None:
                raise SP3BError("closed SP3b live interval lacks its teardown timestamp")
            if row["state"] == "classified" and classification is None:
                raise SP3BError("classified SP3b row lacks its classification")
            if row["state"] in ("unstarted", "admitted", "live", "stopped") and classification is not None:
                raise SP3BError("SP3b classification was recorded in the wrong row state")
            rows_by_id[row["row_id"]] = row

        attempts = ledger.get("attempts")
        if not isinstance(attempts, list):
            raise SP3BError("SP3b attempt ledger is malformed")
        seen_attempt_ids: set[str] = set()
        for sequence, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, Mapping) or set(attempt) != {
                "sequence",
                "attempt_id",
                "row_id",
                "kind",
                "admitted_at",
                "outcome",
            }:
                raise SP3BError("SP3b attempt record fields are malformed")
            if type(attempt.get("sequence")) is not int or attempt["sequence"] != sequence:
                raise SP3BError("SP3b attempt sequence is invalid")
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str) or not _TOKEN.fullmatch(attempt_id) or attempt_id in seen_attempt_ids:
                raise SP3BError("SP3b attempt ID is invalid or duplicated")
            seen_attempt_ids.add(attempt_id)
            row_id = attempt.get("row_id")
            attempt_kind = attempt.get("kind")
            if (
                not isinstance(row_id, str)
                or row_id not in attempts_by_row
                or not isinstance(attempt_kind, str)
                or attempt_kind not in _ATTEMPT_KINDS
            ):
                raise SP3BError("SP3b attempt row or kind is invalid")
            _parse_timestamp(attempt.get("admitted_at"), "attempt admitted_at")
            outcome = attempt.get("outcome")
            if outcome is not None and (
                not isinstance(outcome, str) or outcome not in _ATTEMPT_OUTCOMES
            ):
                raise SP3BError("SP3b attempt outcome is invalid")
            attempts_by_row[row_id] += 1
        for row_id, row in rows_by_id.items():
            attempt_count = row.get("attempt_count")
            if attempt_count != attempts_by_row[row_id]:
                raise SP3BError("SP3b per-row attempt total is malformed or unknown")
            if attempt_count and row["state"] in ("unstarted", "admitted", "missing"):
                raise SP3BError("SP3b attempt is attached to a row that never became live")
        if len(attempts) > TOTAL_ATTEMPT_CAP - BASELINE_ATTEMPTS:
            raise SP3BError("SP3b cumulative attempt ledger exceeds the remaining hard cap")

        control = ledger.get("control")
        expected_control_fields = {
            "paused",
            "infrastructure_failure_streak",
            "pauses",
            "identity_stopped",
            "identity_stop_reason",
            "stopped",
            "stop_reason",
            "classification_sequence",
        }
        if not isinstance(control, Mapping) or set(control) != expected_control_fields:
            raise SP3BError("SP3b control state is malformed")
        if type(control.get("paused")) is not bool or type(control.get("identity_stopped")) is not bool or type(control.get("stopped")) is not bool:
            raise SP3BError("SP3b control flags are malformed")
        _validate_optional_reason(control.get("identity_stop_reason"))
        _validate_optional_reason(control.get("stop_reason"))
        if control["identity_stopped"] != (control["identity_stop_reason"] is not None):
            raise SP3BError("SP3b identity stop flag and reason disagree")
        if control["stopped"] != (control["stop_reason"] is not None):
            raise SP3BError("SP3b stop flag and reason disagree")
        if any(row["state"] == "missing" for row in rows_by_id.values()) and not (
            control["stopped"] or control["identity_stopped"]
        ):
            raise SP3BError("missing SP3b rows require an immutable execution stop")
        if type(control.get("classification_sequence")) is not int or control["classification_sequence"] < 0:
            raise SP3BError("SP3b classification sequence is malformed")
        classification_records = sorted(
            (
                row["classification"]
                for row in rows_by_id.values()
                if row["classification"] is not None
            ),
            key=lambda item: item["sequence"],
        )
        if [item["sequence"] for item in classification_records] != list(
            range(1, control["classification_sequence"] + 1)
        ):
            raise SP3BError("SP3b classification history is incomplete or reordered")
        streak = control.get("infrastructure_failure_streak")
        if (
            not isinstance(streak, list)
            or len(streak) > 3
            or len(set(streak)) != len(streak)
            or any(not isinstance(item, str) or item not in rows_by_id for item in streak)
            or any(
                rows_by_id[item]["classification"] is None
                or rows_by_id[item]["classification"]["classification"] != "INFRASTRUCTURE"
                for item in streak
            )
        ):
            raise SP3BError("SP3b infrastructure streak is malformed")
        pauses = control.get("pauses")
        if not isinstance(pauses, list):
            raise SP3BError("SP3b pause records are malformed")
        if control["paused"] and not pauses:
            raise SP3BError("paused SP3b execution has no durable pause record")
        pending_pause_count = 0
        for index, pause in enumerate(pauses, start=1):
            if not isinstance(pause, Mapping) or set(pause) != {
                "pause_id",
                "triggering_row_ids",
                "triggering_classification_sequences",
                "triggered_at",
                "owner_review",
                "resumed_at",
            }:
                raise SP3BError("SP3b pause record fields are malformed")
            if pause.get("pause_id") != "sp3b-pause-%03d" % index:
                raise SP3BError("SP3b pause identity is invalid")
            trigger_ids = pause.get("triggering_row_ids")
            trigger_sequences = pause.get("triggering_classification_sequences")
            if (
                not isinstance(trigger_ids, list)
                or len(trigger_ids) != 3
                or any(not isinstance(item, str) or item not in rows_by_id for item in trigger_ids)
                or not isinstance(trigger_sequences, list)
                or len(trigger_sequences) != 3
                or any(type(item) is not int or item < 1 for item in trigger_sequences)
            ):
                raise SP3BError("SP3b pause trigger evidence is malformed")
            if trigger_sequences != list(range(trigger_sequences[-1] - 2, trigger_sequences[-1] + 1)):
                raise SP3BError("SP3b pause must follow three consecutive classifications")
            for trigger_id, trigger_sequence in zip(trigger_ids, trigger_sequences):
                classification = rows_by_id[trigger_id]["classification"]
                if (
                    classification is None
                    or classification["classification"] != "INFRASTRUCTURE"
                    or classification["sequence"] != trigger_sequence
                ):
                    raise SP3BError("SP3b pause trigger is not backed by infrastructure evidence")
            _parse_timestamp(pause.get("triggered_at"), "pause triggered_at")
            owner_review = pause.get("owner_review")
            resumed_at = pause.get("resumed_at")
            if (owner_review is None) != (resumed_at is None):
                raise SP3BError("SP3b pause review and resume timestamp must be paired")
            if resumed_at is not None:
                _parse_timestamp(pause["resumed_at"], "pause resumed_at")
            else:
                pending_pause_count += 1
            if owner_review is not None:
                _validate_resume_authorization(
                    owner_review,
                    run_id=self.run_id,
                    pause_id=pause["pause_id"],
                )
        if pending_pause_count > 1 or control["paused"] != (pending_pause_count == 1):
            raise SP3BError("SP3b pause state disagrees with immutable review history")
        if control["paused"] != (len(streak) >= 3):
            raise SP3BError("SP3b pause state disagrees with infrastructure streak")

        totals = ledger.get("totals")
        expected_totals = _derive_totals(ledger)
        if not isinstance(totals, Mapping) or set(totals) != set(expected_totals):
            raise SP3BError("SP3b cumulative totals are malformed or unknown")
        if dict(totals) != expected_totals:
            raise SP3BError("SP3b cumulative totals disagree with durable attempts or live time")
        live_rows = [row for row in rows_by_id.values() if row["state"] == "live"]
        if expected_totals["matrix_elapsed_seconds"] >= TOTAL_LIVE_SECONDS_CAP and not live_rows and not control["stopped"]:
            raise SP3BError("SP3b reached its cumulative live-time cap without a durable stop")
        if any(
            row["state"] in ("stopped", "classified", "terminal")
            and row["live_elapsed_seconds"] >= ROW_LIVE_SECONDS_CAP
            for row in rows_by_id.values()
        ) and not control["stopped"]:
            raise SP3BError("SP3b reached a row live-time cap without a durable stop")

    def _require_budget_headroom(
        self,
        ledger: Mapping[str, Any],
        row: dict[str, Any],
        headroom: float,
        window: float,
        *,
        at_request: bool,
    ) -> None:
        if window <= headroom:
            raise SP3BBudgetError("measured execution window does not exceed teardown headroom")
        if headroom <= 0:
            raise SP3BBudgetError("teardown headroom must be a positive measured reserve")
        elapsed = row["live_elapsed_seconds"]
        if row["state"] == "live":
            elapsed = self._active_elapsed(row)
        projected_row = float(elapsed) + headroom
        other_rows_elapsed = sum(
            float(item["live_elapsed_seconds"])
            for item in ledger["rows"]
            if item["row_id"] != row["row_id"]
        )
        projected_matrix = BASELINE_LIVE_SECONDS + other_rows_elapsed + float(elapsed) + headroom
        if not _finite_nonnegative(projected_row) or not _finite_nonnegative(projected_matrix):
            raise SP3BBudgetError("SP3b projected live-time totals are unknown")
        if at_request:
            if projected_row >= ROW_LIVE_SECONDS_CAP:
                raise SP3BBudgetError("request refused before teardown headroom reserve")
            if projected_matrix >= TOTAL_LIVE_SECONDS_CAP:
                raise SP3BBudgetError("request refused before cumulative teardown headroom reserve")
        else:
            if projected_row >= ROW_LIVE_SECONDS_CAP:
                raise SP3BBudgetError("row cannot start within its teardown headroom")
            if projected_matrix >= TOTAL_LIVE_SECONDS_CAP:
                raise SP3BBudgetError("row cannot start within cumulative teardown headroom")

    def _active_elapsed(self, row: Mapping[str, Any]) -> float:
        start_monotonic = row.get("live_started_monotonic")
        start_wall = _parse_timestamp(row.get("live_started_at"), "live start")
        now_monotonic = self._checked_clock(self._monotonic(), "monotonic clock")
        if now_monotonic >= start_monotonic:
            elapsed = now_monotonic - start_monotonic
        else:
            now_wall = self._wall_clock()
            if not isinstance(now_wall, datetime) or now_wall.tzinfo is None:
                raise SP3BBudgetError("wall clock is unknown after process or clock restart")
            elapsed = (now_wall.astimezone(timezone.utc) - start_wall).total_seconds()
        if not _finite_nonnegative(elapsed):
            raise SP3BBudgetError("SP3b live-time measurement is unknown or malformed")
        return float(elapsed)

    def _checked_clock(self, value: Any, label: str) -> float:
        if not _finite_nonnegative(value):
            raise SP3BBudgetError("%s is unknown or malformed" % label)
        return float(value)

    def _find_row(self, ledger: Mapping[str, Any], row_id: str) -> dict[str, Any]:
        if not isinstance(row_id, str) or not _TOKEN.fullmatch(row_id):
            raise SP3BError("SP3b row_id is invalid")
        for row in ledger["rows"]:
            if row["row_id"] == row_id:
                return row
        raise SP3BError("row_id is not one of the 19 approved SP3b rows")

    def _require_not_stopped_or_paused(self, control: Mapping[str, Any]) -> None:
        if control["identity_stopped"]:
            raise SP3BIdentityDriftError("SP3b identity drift permanently stopped execution")
        if control["paused"]:
            raise SP3BPausedError("SP3b is paused pending owner review")
        if control["stopped"]:
            raise SP3BError("SP3b execution is stopped")

    def _ensure_root(self) -> None:
        _reject_symlink_components(PROJECT_ROOT, self._root)
        self._root.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(PROJECT_ROOT, self._root)
        if not self._root.is_dir():
            raise SP3BError("SP3b ledger root is not a directory")

    def _ensure_root_exists(self) -> None:
        _reject_symlink_components(PROJECT_ROOT, self._root)
        if not self._root.is_dir() or self._root.is_symlink():
            raise SP3BError("SP3b ledger root is unavailable")

    def _write_json(
        self,
        path: Path,
        value: Mapping[str, Any],
        *,
        overwrite: bool = False,
    ) -> None:
        _reject_symlink_components(self._root, path)
        target_exists = path.exists() or path.is_symlink()
        if path.name == FREEZE_NAME and (target_exists or overwrite):
            raise SP3BError("immutable SP3b artifact overwrite refused")
        if target_exists and (path.name != LEDGER_NAME or not overwrite):
            raise SP3BError("SP3b artifact overwrite refused")
        if overwrite and path.name != LEDGER_NAME:
            raise SP3BError("only the mutable SP3b ledger may be replaced")
        from utils.file_operations import safe_write_json

        wrote = safe_write_json(
            str(path),
            dict(value),
            create_backup=False,
            acquire_lock=False,
            json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
        )
        if not wrote:
            raise SP3BError("atomic SP3b JSON write failed")


@contextmanager
def _exclusive_root_lock(root: Path) -> Iterator[None]:
    """Serialize every read/modify/write transaction across threads/processes."""
    lock_key = root / ".sp3b-transaction"
    lock_file = Path(str(lock_key) + ".lock")
    _reject_symlink_components(PROJECT_ROOT, lock_key)
    if lock_file.is_symlink():
        raise SP3BError("SP3b transaction lock path is a symlink")
    from utils.file_operations import atomic_writer

    try:
        acquired = atomic_writer.acquire_lock(str(lock_key), timeout=15.0)
    except Exception as exc:
        raise SP3BError("SP3b transaction lock is unavailable") from exc
    if acquired is None:
        raise SP3BError("SP3b transaction lock was not acquired")
    try:
        if lock_file.is_symlink():
            raise SP3BError("SP3b transaction lock path changed unsafely")
        yield
    finally:
        atomic_writer.release_lock(str(lock_key))


def _refresh_totals(ledger: dict[str, Any]) -> None:
    ledger["totals"] = _derive_totals(ledger)


def _derive_totals(ledger: Mapping[str, Any]) -> dict[str, Any]:
    attempts = ledger.get("attempts")
    rows = ledger.get("rows")
    if not isinstance(attempts, list) or not isinstance(rows, list):
        raise SP3BError("SP3b attempt or row totals are unavailable")
    if any(not isinstance(row, Mapping) or not _finite_nonnegative(row.get("live_elapsed_seconds")) for row in rows):
        raise SP3BError("SP3b live-time totals are unknown or malformed")
    matrix_attempts = BASELINE_ATTEMPTS + len(attempts)
    matrix_seconds = BASELINE_LIVE_SECONDS + sum(float(row["live_elapsed_seconds"]) for row in rows)
    if not _finite_nonnegative(matrix_seconds):
        raise SP3BError("SP3b cumulative live-time total is nonfinite")
    counts: dict[str, int] = {row["row_id"]: 0 for row in rows}
    for attempt in attempts:
        if not isinstance(attempt, Mapping) or attempt.get("row_id") not in counts:
            raise SP3BError("SP3b attempt total cannot be reconciled")
        counts[attempt["row_id"]] += 1
    for row in rows:
        if row.get("attempt_count") != counts[row["row_id"]]:
            raise SP3BError("SP3b row attempt count differs from durable request admissions")
    return {
        "matrix_attempts": matrix_attempts,
        "matrix_elapsed_seconds": matrix_seconds,
        "remaining_attempts": TOTAL_ATTEMPT_CAP - matrix_attempts,
        "remaining_live_seconds": TOTAL_LIVE_SECONDS_CAP - matrix_seconds,
        "sp3b_attempts": len(attempts),
        "sp3b_live_seconds": matrix_seconds - BASELINE_LIVE_SECONDS,
    }


def _validate_capture_identity(value: Any) -> dict[str, Any]:
    expected_fields = {
        "source_commit_sha",
        "source_tree_oid",
        "source_content_sha256",
        "status_digest_sha256",
        "requirements_lock_sha256",
        "interpreter",
        "dependency_versions",
        "environment",
        "requested_route",
        "static_route_config",
        "prompt_hashes",
        "tool_hashes",
        "source_hashes",
        "input_hashes",
        "profile_hashes",
        "tracked_source_file_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise SP3BError("execution identity fields are incomplete or unknown")
    for field in ("source_commit_sha", "source_tree_oid"):
        item = value.get(field)
        if not isinstance(item, str) or not _GIT_OID.fullmatch(item):
            raise SP3BError("execution identity git source ID is invalid")
    for field in ("source_content_sha256", "status_digest_sha256", "requirements_lock_sha256"):
        item = value.get(field)
        if not isinstance(item, str) or not _SHA256.fullmatch(item):
            raise SP3BError("execution identity source hash is invalid")
    interpreter = value.get("interpreter")
    if not isinstance(interpreter, Mapping) or set(interpreter) != {
        "executable",
        "implementation",
        "version",
        "platform",
    } or any(not isinstance(item, str) or not item for item in interpreter.values()):
        raise SP3BError("exact Python interpreter identity is incomplete")
    dependencies = value.get("dependency_versions")
    if not isinstance(dependencies, Mapping) or not dependencies:
        raise SP3BError("installed dependency versions are unknown")
    if any(
        not isinstance(name, str)
        or not name
        or not isinstance(version, str)
        or not version
        for name, version in dependencies.items()
    ):
        raise SP3BError("installed dependency version map is malformed")
    environment = value.get("environment")
    if not isinstance(environment, Mapping) or set(environment) != set(_SAFE_ENVIRONMENT):
        raise SP3BError("selected non-secret environment identity is incomplete")
    if any(item is not None and not isinstance(item, str) for item in environment.values()):
        raise SP3BError("selected environment identity is malformed")
    if value.get("requested_route") != _EXPECTED_REQUESTED_ROUTE:
        raise SP3BError("SP3b must request production-auto on openrouter/auto")
    static_route = value.get("static_route_config")
    if not isinstance(static_route, Mapping) or set(static_route) != set(_STATIC_ROUTE_NAMES):
        raise SP3BError("selected non-secret static route configuration is incomplete")
    if (
        static_route.get("LLM_PROVIDER") != "openrouter"
        or not isinstance(static_route.get("OPENROUTER_CHAT_MODEL"), str)
        or not static_route["OPENROUTER_CHAT_MODEL"]
        or type(static_route.get("ENABLE_PROVIDER_FALLBACK")) is not bool
        or not isinstance(static_route.get("OPENROUTER_STRATEGY"), str)
        or not isinstance(static_route.get("OPENROUTER_FULL_MODEL"), str)
        or not isinstance(static_route.get("OPENROUTER_MINI_MODEL"), str)
    ):
        raise SP3BError("selected static route settings do not identify OpenRouter")
    result = dict(value)
    for field in ("prompt_hashes", "tool_hashes", "source_hashes", "input_hashes", "profile_hashes"):
        result[field] = _validate_hash_map(value.get(field), field)
    count = value.get("tracked_source_file_count")
    if type(count) is not int or count < 1:
        raise SP3BError("full tracked source tree count is unknown")
    _canonical_json(result)
    return result


def _validate_hash_map(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise SP3BError("execution identity %s are incomplete" % label)
    result: dict[str, str] = {}
    for raw_path, digest in value.items():
        path = _safe_relative_path(raw_path, label + " path")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise SP3BError("execution identity %s contains an invalid hash" % label)
        result[path.as_posix()] = digest
    if len(result) != len(value):
        raise SP3BError("execution identity %s paths collide" % label)
    return dict(sorted(result.items()))


def _installed_locked_versions(raw_lock: bytes) -> dict[str, str]:
    try:
        lines = raw_lock.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise SP3BError("requirements-lock.txt is not ASCII") from exc
    locked: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", value)
        if match is None:
            raise SP3BError("dependency lock line %d is not an exact pin" % line_number)
        name, expected_version = match.groups()
        normalized_name = re.sub(r"[-_.]+", "-", name).lower()
        if normalized_name in locked:
            raise SP3BError("dependency lock contains a duplicate package")
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise SP3BError("locked dependency is not installed: %s" % normalized_name) from exc
        if installed != expected_version:
            raise SP3BError("installed dependency differs from requirements-lock.txt")
        locked[normalized_name] = installed
    if not locked:
        raise SP3BError("dependency lock contains no installed exact pins")
    return dict(sorted(locked.items()))


def _safe_static_route_config(raw: bytes) -> dict[str, Any]:
    try:
        tree = ast.parse(raw.decode("utf-8"), filename="model_config.py")
    except (UnicodeError, SyntaxError) as exc:
        raise SP3BError("static model route configuration is invalid") from exc
    values: dict[str, Any] = {}
    for node in tree.body:
        assigned_names: list[str] = []
        expression: ast.expr | None = None
        if isinstance(node, ast.Assign):
            assigned_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            expression = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned_names = [node.target.id]
            expression = node.value
        selected = [name for name in assigned_names if name in _STATIC_ROUTE_NAMES]
        if not selected or expression is None:
            continue
        try:
            literal = ast.literal_eval(expression)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(literal, (str, bool, int, float)) and not (
            isinstance(literal, float) and not math.isfinite(literal)
        ):
            for name in selected:
                values[name] = literal
    if set(values) != set(_STATIC_ROUTE_NAMES):
        raise SP3BError("selected static route settings are missing or nonliteral")
    return values


def _git_output(arguments: list[str], *, raw: bool = False) -> Any:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SP3BError("git source identity capture failed") from exc
    if result.returncode != 0:
        raise SP3BError("git source identity capture failed")
    if raw:
        return result.stdout
    try:
        return result.stdout.decode("ascii").strip()
    except UnicodeError as exc:
        raise SP3BError("git source identity is not ASCII") from exc


def _is_sensitive_path(path: PurePosixPath) -> bool:
    sensitive_parts = {
        ".aws",
        ".ssh",
        ".secrets",
        "credentials",
        "secrets",
        "private",
    }
    if any(part.casefold() in sensitive_parts for part in path.parts):
        return True
    name = path.name.casefold()
    return (
        name == "config.py"
        or name.startswith("config.")
        or name == ".env"
        or name.startswith(".env.")
        or name in {".netrc", ".npmrc", ".pypirc", "auth.json"}
        or any(marker in name for marker in ("credential", "secret", "password", "passwd", "api_key", "apikey", "private_key", "privatekey"))
        or re.search(r"(^|[_.-])key([_.-]|$)", name) is not None
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
    )


def _safe_relative_path(
    value: str | Path,
    label: str,
    *,
    require_tmp: bool = False,
) -> Path:
    if not isinstance(value, (str, Path)):
        raise SP3BError("%s must be a project-relative path" % label)
    raw = value.as_posix() if isinstance(value, Path) else value
    parsed = PurePosixPath(raw)
    if (
        not raw
        or parsed.is_absolute()
        or "\\" in raw
        or any(part in ("", ".", "..") for part in parsed.parts)
        or (
            require_tmp
            and (len(parsed.parts) < 2 or parsed.parts[0] != "tmp")
        )
    ):
        raise SP3BError("%s is not a safe project-relative path" % label)
    return Path(*parsed.parts)


def _project_path(relative: str | Path, *, require_exists: bool) -> Path:
    safe_relative = _safe_relative_path(relative, "project path")
    path = PROJECT_ROOT.joinpath(*safe_relative.parts)
    _reject_symlink_components(PROJECT_ROOT, path)
    try:
        resolved = path.resolve(strict=require_exists)
        resolved.relative_to(PROJECT_ROOT.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SP3BError("project-relative path is missing or escapes the repository") from exc
    if require_exists and not resolved.is_file() and not resolved.is_dir():
        raise SP3BError("project-relative input is not a regular file or directory")
    return path


def _reject_symlink_components(root: Path, path: Path) -> None:
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        relative = path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SP3BError("SP3b path escapes its owning project root") from exc
    if root.is_symlink():
        raise SP3BError("SP3b path root is a symlink")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SP3BError("SP3b path traverses a symlink")


def _read_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SP3BError("%s is missing or unsafe" % label)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SP3BError("%s cannot be read" % label) from exc


def _strict_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SP3BError("%s is malformed JSON" % label) from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-finite JSON constant: %s" % value)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SP3BError("SP3b identity or ledger contains noncanonical data") from exc


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


def _required_seconds(value: Any, label: str) -> float:
    if not _finite_nonnegative(value):
        raise SP3BBudgetError("measured %s must be finite and nonnegative" % label)
    return float(value)


def _timestamp(value: Any) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SP3BError("SP3b clock must provide a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SP3BError("%s must be an explicit UTC timestamp" % label)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SP3BError("%s is malformed" % label) from exc
    if parsed.tzinfo is None:
        raise SP3BError("%s is missing timezone information" % label)
    return parsed.astimezone(timezone.utc)


def _validate_evidence(evidence: Any) -> None:
    if not isinstance(evidence, list):
        raise SP3BError("pre-content evidence must be a list")
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"kind", "code", "source"}:
            raise SP3BError("pre-content evidence fields are malformed")
        kind = item.get("kind")
        code = item.get("code")
        if (
            not isinstance(kind, str)
            or kind not in _EVIDENCE_CODES
            or not isinstance(code, str)
            or code not in _EVIDENCE_CODES[kind]
        ):
            raise SP3BError("pre-content evidence code is not allowlisted")
        if not isinstance(item.get("source"), str):
            raise SP3BError("pre-content evidence source is malformed")
        _safe_relative_path(item["source"], "pre-content evidence source", require_tmp=True)


def _validate_classification_record(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "classification",
        "reason",
        "evidence",
        "sequence",
        "recorded_at",
    }:
        raise SP3BError("pre-content classification record fields are malformed")
    if value.get("classification") not in ("INFRASTRUCTURE", "CONTENT/RESULT", "UNRESOLVED"):
        raise SP3BError("pre-content classification value is invalid")
    if not isinstance(value.get("reason"), str) or not _REASON_CODE.fullmatch(value["reason"]):
        raise SP3BError("pre-content classification reason is unsafe")
    if type(value.get("sequence")) is not int or value["sequence"] < 1:
        raise SP3BError("pre-content classification sequence is invalid")
    _parse_timestamp(value.get("recorded_at"), "classification timestamp")
    _validate_evidence(value.get("evidence"))
    expected = classify_pre_content(value["evidence"])
    if (
        value["classification"] != expected["classification"]
        or value["reason"] != expected["reason"]
        or value["evidence"] != expected["evidence"]
    ):
        raise SP3BError("SP3b classification is inconsistent with its allowlisted evidence")


def _validate_freeze_authorization(
    value: Any,
    *,
    freeze_hash: str,
    identity_hash: str,
) -> None:
    expected = {
        "decision",
        "authorized",
        "checked",
        "amendment_sha256",
        "freeze_sha256",
        "execution_identity_sha256",
        "ruling_sha256",
        "reviewer",
        "authorization_id",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SP3BError("external SP3b FREEZE authorization fields are incomplete")
    if (
        value.get("decision") != "SP3B_FREEZE"
        or value.get("authorized") is not True
        or value.get("checked") is not True
        or value.get("amendment_sha256") != EXPECTED_AMENDMENT_SHA256
        or value.get("freeze_sha256") != freeze_hash
        or value.get("execution_identity_sha256") != identity_hash
        or not isinstance(value.get("ruling_sha256"), str)
        or not _SHA256.fullmatch(value["ruling_sha256"])
        or not isinstance(value.get("reviewer"), str)
        or not value["reviewer"].strip()
        or not isinstance(value.get("authorization_id"), str)
        or not _TOKEN.fullmatch(value["authorization_id"])
    ):
        raise SP3BError("external SP3b FREEZE authorization does not match this DRAFT identity")


def _validate_resume_authorization(
    value: Any,
    *,
    run_id: str,
    pause_id: str,
) -> dict[str, Any]:
    expected = {
        "status",
        "checked",
        "resume_authorized",
        "sp3b_run_id",
        "pause_id",
        "reviewer",
        "authorization_id",
        "evidence_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SP3BPausedError("owner review needs checked resume authorization")
    if (
        value.get("status") != "OWNER_REVIEW_CHECKED"
        or value.get("checked") is not True
        or value.get("resume_authorized") is not True
        or value.get("sp3b_run_id") != run_id
        or value.get("pause_id") != pause_id
        or not isinstance(value.get("reviewer"), str)
        or not value["reviewer"].strip()
        or not isinstance(value.get("authorization_id"), str)
        or not _TOKEN.fullmatch(value["authorization_id"])
        or not isinstance(value.get("evidence_sha256"), str)
        or not _SHA256.fullmatch(value["evidence_sha256"])
    ):
        raise SP3BPausedError("owner review is not a checked resume authorization")
    return dict(value)


def _validate_optional_reason(value: Any) -> None:
    if value is not None and (not isinstance(value, str) or not _REASON_CODE.fullmatch(value)):
        raise SP3BError("SP3b reason code is malformed")


def _unresolved_classification(
    reason: str,
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "classification": "UNRESOLVED",
        "reason": reason,
        "evidence": evidence or [],
    }
