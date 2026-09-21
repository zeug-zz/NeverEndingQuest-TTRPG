# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Failure Packet
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded diagnostics for the final semantic adaptation stage.
The packet is an advisory handoff only. Python-owned gate results remain the
authority for publication, and this module never writes files or runtime
state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
    VALID_SOURCE_PROFILES,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_adaptation_gate_composer import REQUIRED_GATE_DOMAINS
from utils.toolkit_adaptation_output_safety import redact_diagnostic_text


FAILURE_PACKET_CONTRACT_VERSION = "toolkit_adaptation_failure_packet.v1"
FAILURE_PACKET_KIND = "adaptation_failure_packet"

PACKET_STATUS_BLOCKED = "blocked"
PACKET_STATUS_NOT_NEEDED = "not_needed"
PACKET_STATUS_INVALID = "invalid"
VALID_PACKET_STATUSES = (
    PACKET_STATUS_BLOCKED,
    PACKET_STATUS_NOT_NEEDED,
    PACKET_STATUS_INVALID,
)

GATE_STATUS_PASS = "pass"
GATE_STATUS_DEGRADED = "degraded"
GATE_STATUS_BLOCKED = "blocked"
GATE_STATUS_UNKNOWN = "unknown"
GATE_STATUS_NOT_RUN = "not_run"
GATE_STATUS_DEFERRED = "deferred"
GATE_STATUS_NOT_APPLICABLE = "not_applicable"
VALID_GATE_STATUSES = (
    GATE_STATUS_PASS,
    GATE_STATUS_DEGRADED,
    GATE_STATUS_BLOCKED,
    GATE_STATUS_UNKNOWN,
    GATE_STATUS_NOT_RUN,
    GATE_STATUS_DEFERRED,
    GATE_STATUS_NOT_APPLICABLE,
)

FINDING_KIND_ERROR = "error"
FINDING_KIND_BLOCKER = "blocker"
FINDING_KIND_WARNING = "warning"
FINDING_KIND_STATUS = "status"
VALID_FINDING_KINDS = (
    FINDING_KIND_ERROR,
    FINDING_KIND_BLOCKER,
    FINDING_KIND_WARNING,
    FINDING_KIND_STATUS,
)

# These are the only publication objectives that can enter the packet. They
# are labels, not instructions, commands, or model-provided operations.
ALLOWED_PUBLICATION_GOALS = (
    "schema",
    "readiness",
    "mechanical_closure",
    "semantic_authority",
    "semantic_probes",
    "report_agreement",
    "markdown_quality",
    "registry_verification",
)
DEFAULT_PUBLICATION_GOALS = ALLOWED_PUBLICATION_GOALS

MAX_PACKET_SERIALIZED_CHARS = 24_000
MAX_GATE_DOMAINS = 16
MAX_GATE_FINDINGS = 96
MAX_FINDING_CODE_CHARS = 160
MAX_FINDING_MESSAGE_CHARS = 800
MAX_MODULE_SUMMARIES = 8
MAX_MODULE_SUMMARY_CHARS = 1_600
MAX_MODULE_SUMMARIES_CHARS = 8_000
MAX_SUMMARY_ITEMS = 8
MAX_SUMMARY_ITEM_CHARS = 180
MAX_SOURCE_CONTEXT_REFS = 32
MAX_PUBLICATION_GOALS = 12
MAX_ATTEMPT_TEXT_CHARS = 240
MAX_DIAGNOSTICS = 32
MAX_DIAGNOSTIC_CHARS = 240
MAX_REPORT_BYTES = 200_000

# The monster handoff is intentionally a separate, smaller contract inside
# the generic failure packet.  It is the only content sent to the adaptation
# auditor for this remediation; the older gate/report fields remain unchanged.
MONSTER_FAILURE_PACKET_CONTRACT_VERSION = "toolkit_adaptation_monster_failure_packet.v1"
MAX_MONSTER_PACKET_CHARS = 12_000
MAX_MONSTER_LOCATIONS = 32
MAX_MONSTER_QUANTITY_RECORDS = 32
MAX_MONSTER_SCENE_EVIDENCE = 16
MAX_MONSTER_EVIDENCE_CHARS = 320
MAX_MONSTER_IDENTITIES = 16
MAX_MONSTER_SOURCE_REFERENCE_IDS = 32
_LOCATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")

_STATUS_ALIASES = {
    "success": GATE_STATUS_PASS,
    "ok": GATE_STATUS_PASS,
    "ready": GATE_STATUS_PASS,
    "complete": GATE_STATUS_PASS,
    "completed": GATE_STATUS_PASS,
    "warning": GATE_STATUS_DEGRADED,
    "warn": GATE_STATUS_DEGRADED,
    "partial": GATE_STATUS_DEGRADED,
    "skipped": GATE_STATUS_DEGRADED,
    "fail": GATE_STATUS_BLOCKED,
    "failed": GATE_STATUS_BLOCKED,
    "error": GATE_STATUS_BLOCKED,
    "invalid": GATE_STATUS_BLOCKED,
    "not-run": GATE_STATUS_NOT_RUN,
    "not run": GATE_STATUS_NOT_RUN,
    "not-available": GATE_STATUS_DEFERRED,
}

_FINDING_FIELDS = (
    ("errors", FINDING_KIND_ERROR),
    ("blocking_errors", FINDING_KIND_ERROR),
    ("blockers", FINDING_KIND_BLOCKER),
    ("warnings", FINDING_KIND_WARNING),
    ("diagnostics", FINDING_KIND_ERROR),
    ("findings", FINDING_KIND_ERROR),
    ("issues", FINDING_KIND_ERROR),
)

_CODE_KEYS = (
    "code",
    "error_code",
    "blocker_code",
    "failure_code",
    "reason_code",
    "category",
    "type",
)
_MESSAGE_KEYS = ("message", "reason", "detail", "error", "description")
_REFERENCE_KEYS = (
    "evidence_ref",
    "evidence_reference",
    "evidence",
    "report_ref",
    "source_ref",
    "report_path",
    "evidence_path",
)

_SUMMARY_STRING_FIELDS = (
    "module_slug",
    "module_title",
    "title",
    "status",
    "ready_status",
    "publishable_status",
    "effective_publishable_status",
    "source_fidelity_status",
    "summary",
    "reason",
    "report_name",
)
_SUMMARY_LIST_FIELDS = ("blockers", "errors", "warnings", "missing_categories")
_SUMMARY_COUNT_FIELDS = (
    "area_count",
    "area_bu_count",
    "monster_count",
    "location_count",
    "npc_count",
)
_SUMMARY_BOOL_FIELDS = (
    "has_module_context",
    "has_module_plot",
    "truncated",
)
_ALLOWED_REPORT_FILES = (
    "validation_report.json",
    "toolkit_build_report.json",
    "source_fidelity_report.json",
    "readiness_report.json",
    "semantic_authority_report.json",
    "semantic_probe_report.json",
    "module_media_generator_report.json",
)

_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "campaign",
        "credentials",
        "full_prompt",
        "full_source",
        "password",
        "prompt",
        "provider_payload",
        "raw_markdown",
        "raw_pdf",
        "raw_prompt",
        "raw_response",
        "raw_source",
        "response_content",
        "response_text",
        "secret",
        "source_content",
        "source_text",
        "token",
        "world_registry",
    }
)
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|credential|password|secret|token|private[_ -]?key)"
)
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|password|secret|credential|token)\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_KEY_TOKEN_RE = re.compile(r"(?i)\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{7,}")
_PAYLOAD_RE = re.compile(
    r"(?i)\b(?:raw[_ -]?(?:source|markdown|pdf|prompt|response)|full[_ -]?(?:source|prompt)|"
    r"source[_ -]?content|source[_ -]?text|provider[_ -]?payload|prompt[_ -]?content|"
    r"response[_ -]?content)\s*[:=]\s*[^;\n]+"
)


def _ascii_text(
    value: Any,
    limit: int,
    state: Optional[Dict[str, Any]] = None,
    field: str = "",
) -> Tuple[str, bool]:
    """Return bounded ASCII text after deterministic sensitive-value removal."""
    if value is None:
        return "", False
    if isinstance(value, (Mapping, list, tuple, set)):
        if state is not None:
            state.setdefault("excluded_fields", set()).add(field or "text")
        return "", False
    text = str(value).replace("\x00", " ")
    before = text
    text = _PAYLOAD_RE.sub("[REDACTED_PAYLOAD]", text)
    text = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED_CREDENTIAL]", text)
    text = _KEY_TOKEN_RE.sub("[REDACTED_CREDENTIAL]", text)
    text = " ".join(text.split()).strip()
    # Adaptation packet text is a persistence boundary.  Do not retain raw
    # exception/provider/source text merely because it arrived under an
    # otherwise allowlisted field name.
    text = redact_diagnostic_text(text, limit)
    if not text:
        return "", False
    text = text.encode("ascii", "replace").decode("ascii")
    if state is not None and text != before:
        state.setdefault("redacted_fields", set()).add(field or "text")
    truncated = len(text) > limit
    if truncated:
        marker = " [truncated]"
        text = text[: max(0, limit - len(marker))].rstrip() + marker
        if state is not None:
            state.setdefault("truncated_sections", set()).add(field or "text")
    return text, truncated


def _diagnostic(
    code: str,
    message: str,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    text, _ = _ascii_text(message, MAX_DIAGNOSTIC_CHARS, state, "diagnostics.message")
    code_text, _ = _ascii_text(code, 96, state, "diagnostics.code")
    return {"code": code_text or "invalid_packet", "message": text}


def _record_diagnostic(state: Dict[str, Any], code: str, message: str) -> None:
    diagnostics = state.setdefault("diagnostics", [])
    item = _diagnostic(code, message, state)
    if item not in diagnostics and len(diagnostics) < MAX_DIAGNOSTICS:
        diagnostics.append(item)


def _safe_path(
    value: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
    field: str,
) -> Optional[str]:
    """Normalize a path to a project-relative POSIX reference."""
    if isinstance(value, Mapping):
        value = value.get("path") or value.get("report_path") or value.get("target_path")
    if not isinstance(value, (str, Path)):
        if value not in (None, ""):
            _record_diagnostic(state, "unsafe_path_omitted", field + " is not a path")
        return None
    raw = str(value).strip()
    if not raw or "\x00" in raw or "\\" in raw:
        _record_diagnostic(state, "unsafe_path_omitted", field + " is not project-relative")
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            raw = candidate.resolve(strict=False).relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            _record_diagnostic(state, "unsafe_path_omitted", field + " points outside the project")
            return None
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _record_diagnostic(state, "unsafe_path_omitted", field + " contains an unsafe path segment")
        return None
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        _record_diagnostic(state, "unsafe_path_omitted", field + " is not project-relative")
        return None
    return PurePosixPath(raw).as_posix()


def _safe_hash(value: Any, state: Dict[str, Any], field: str) -> Optional[str]:
    if not isinstance(value, str):
        if value not in (None, ""):
            _record_diagnostic(state, "invalid_hash", field + " must be a lowercase SHA-256 digest")
        return None
    candidate = value.strip().lower()
    if not _SHA256_RE.fullmatch(candidate):
        _record_diagnostic(state, "invalid_hash", field + " must be a lowercase SHA-256 digest")
        return None
    return candidate


def _safe_reference(
    value: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
    field: str,
    role: str = "",
    expected_hash: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Keep only a hash and a project-relative path from a reference."""
    if isinstance(value, Mapping):
        raw_path = value.get("path") or value.get("report_path") or value.get("target_path")
        raw_hash = value.get("sha256") or value.get("source_hash") or value.get("report_hash")
        raw_role = value.get("role") or value.get("kind") or role
    else:
        raw_path = value
        raw_hash = None
        raw_role = role

    path = _safe_path(raw_path, repo_root=repo_root, state=state, field=field + ".path")
    digest = _safe_hash(raw_hash, state, field + ".sha256") if raw_hash not in (None, "") else None
    if expected_hash and digest and digest != expected_hash:
        _record_diagnostic(state, "reference_hash_mismatch", field + " hash does not match attempt source hash")
        return None
    if path is None and digest is None:
        if value not in (None, "", {}):
            _record_diagnostic(state, "invalid_reference_omitted", field + " has no safe path or hash")
        return None

    reference: Dict[str, Any] = {}
    if path is not None:
        reference["path"] = path
    if digest is not None:
        reference["sha256"] = digest
    if raw_role not in (None, ""):
        role_text, _ = _ascii_text(raw_role, 80, state, field + ".role")
        if role_text:
            reference["role"] = role_text
    reference["reference_only"] = True
    return reference


def _safe_identifier(value: Any, state: Dict[str, Any], field: str) -> str:
    if not isinstance(value, str):
        _record_diagnostic(state, "invalid_identifier", field + " must be bounded text")
        return ""
    candidate = value.strip()
    if not candidate or not _SAFE_TOKEN_RE.fullmatch(candidate):
        _record_diagnostic(state, "invalid_identifier", field + " is not path-safe")
        return ""
    return candidate


def _status_token(value: Any, state: Dict[str, Any], field: str) -> str:
    raw, _ = _ascii_text(value, 64, state, field)
    token = raw.strip().lower()
    token = _STATUS_ALIASES.get(token, token)
    if token not in VALID_GATE_STATUSES:
        _record_diagnostic(state, "unknown_gate_status", field + " is not an allowed gate status")
        return GATE_STATUS_UNKNOWN
    return token


def _finding_items(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _finding_code(
    item: Any,
    *,
    domain: str,
    kind: str,
    state: Dict[str, Any],
) -> Tuple[str, bool]:
    raw = ""
    if isinstance(item, Mapping):
        for key in _CODE_KEYS:
            if item.get(key) not in (None, ""):
                raw = str(item.get(key))
                break
    if not raw:
        raw = f"{domain}_{kind}"
    return _ascii_text(raw, MAX_FINDING_CODE_CHARS, state, "gate_findings.code")


def _finding_message(
    item: Any,
    *,
    code: str,
    state: Dict[str, Any],
) -> Tuple[str, bool]:
    if isinstance(item, Mapping):
        for key in _MESSAGE_KEYS:
            if item.get(key) not in (None, ""):
                text, truncated = _ascii_text(
                    item.get(key),
                    MAX_FINDING_MESSAGE_CHARS,
                    state,
                    "gate_findings.message",
                )
                return text or code, truncated
        return _ascii_text(code, MAX_FINDING_MESSAGE_CHARS, state, "gate_findings.message")
    text, truncated = _ascii_text(item, MAX_FINDING_MESSAGE_CHARS, state, "gate_findings.message")
    return text or code, truncated


def _finding_reference(
    item: Any,
    report: Mapping[str, Any],
    *,
    repo_root: Path,
    state: Dict[str, Any],
    domain: str,
    index: int,
) -> Optional[Dict[str, Any]]:
    raw: Any = None
    if isinstance(item, Mapping):
        for key in _REFERENCE_KEYS:
            if item.get(key) not in (None, ""):
                raw = item.get(key)
                break
        if raw is None and item.get("path") not in (None, ""):
            raw = {
                "path": item.get("path"),
                "sha256": item.get("sha256") or item.get("report_hash"),
            }
    if raw is None:
        for key in ("evidence_ref", "report_ref", "report_path"):
            if report.get(key) not in (None, ""):
                raw = report.get(key)
                break
        if raw is None and report.get("path") not in (None, ""):
            raw = {
                "path": report.get("path"),
                "sha256": report.get("sha256") or report.get("report_hash"),
            }
    return _safe_reference(
        raw,
        repo_root=repo_root,
        state=state,
        field=f"gate_findings[{domain}][{index}].evidence_ref",
        role="gate_evidence",
    )


def _gate_reports(gate_results: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(gate_results, Mapping):
        return {}, {}
    if isinstance(gate_results.get("gates"), Mapping):
        return dict(gate_results.get("gates") or {}), dict(gate_results)
    return dict(gate_results), dict(gate_results)


def _iter_gate_reports(
    reports: Mapping[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    if depth > 2:
        return
    for raw_domain in sorted(reports, key=lambda value: str(value)):
        report = reports.get(raw_domain)
        domain = str(raw_domain)
        full_domain = f"{prefix}.{domain}" if prefix else domain
        if isinstance(report, Mapping):
            yield full_domain, report
            nested = report.get("gates")
            if isinstance(nested, Mapping):
                yield from _iter_gate_reports(nested, prefix=full_domain, depth=depth + 1)
        else:
            yield full_domain, {"status": "unknown", "errors": ["gate_result_not_an_object"]}


def _normalize_gate_findings(
    gate_results: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    reports, container = _gate_reports(gate_results)
    statuses: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    seen_domains = set()

    for domain, report in _iter_gate_reports(reports):
        if len(seen_domains) >= MAX_GATE_DOMAINS and domain not in seen_domains:
            _record_diagnostic(state, "gate_domain_limit", "additional gate domains were omitted")
            continue
        seen_domains.add(domain)
        raw_status = report.get("effective_status", report.get("status", report.get("overall_status")))
        reported_status, _ = _ascii_text(raw_status, 64, state, f"gate_statuses.{domain}.reported_status")
        status = _status_token(raw_status, state, f"gate_statuses.{domain}.status")
        report_blocking = report.get("blocking") is True
        blocking = bool(
            report_blocking
            or status in {GATE_STATUS_BLOCKED, GATE_STATUS_UNKNOWN, GATE_STATUS_NOT_RUN, GATE_STATUS_DEFERRED}
            or report.get("errors")
            or report.get("blockers")
            or report.get("blocking_errors")
        )
        status_entry: Dict[str, Any] = {
            "domain": _ascii_text(domain, 96, state, "gate_statuses.domain")[0],
            "status": status,
            "reported_status": reported_status or "missing",
            "blocking": blocking,
        }
        report_ref = _finding_reference(
            report,
            {},
            repo_root=repo_root,
            state=state,
            domain=domain,
            index=0,
        )
        if report_ref is not None:
            status_entry["evidence_ref"] = report_ref
        statuses.append(status_entry)

        for field_name, default_kind in _FINDING_FIELDS:
            items = _finding_items(report.get(field_name))
            for item_index, item in enumerate(items):
                if len(findings) >= MAX_GATE_FINDINGS:
                    _record_diagnostic(state, "gate_finding_limit", "additional gate findings were omitted")
                    break
                kind = default_kind
                if isinstance(item, Mapping):
                    raw_kind = str(item.get("kind") or item.get("severity") or "").strip().lower()
                    if raw_kind in VALID_FINDING_KINDS:
                        kind = raw_kind
                    elif raw_kind == "warning":
                        kind = FINDING_KIND_WARNING
                code, code_truncated = _finding_code(
                    item,
                    domain=domain,
                    kind=kind,
                    state=state,
                )
                message, message_truncated = _finding_message(
                    item,
                    code=code,
                    state=state,
                )
                finding: Dict[str, Any] = {
                    "domain": _ascii_text(domain, 96, state, "gate_findings.domain")[0],
                    "status": status,
                    "finding_kind": kind,
                    "code": code,
                    "message": message,
                    "origin_field": field_name,
                    "blocking": bool(kind in {FINDING_KIND_ERROR, FINDING_KIND_BLOCKER} or blocking),
                    "truncated": bool(code_truncated or message_truncated),
                }
                if isinstance(item, Mapping):
                    details: Dict[str, str] = {}
                    for detail_key in ("expected", "actual", "field", "severity"):
                        if item.get(detail_key) not in (None, ""):
                            detail_text, _ = _ascii_text(
                                item.get(detail_key),
                                MAX_SUMMARY_ITEM_CHARS,
                                state,
                                "gate_findings.details." + detail_key,
                            )
                            if detail_text:
                                details[detail_key] = detail_text
                    if details:
                        finding["details"] = details
                evidence_ref = _finding_reference(
                    item,
                    report,
                    repo_root=repo_root,
                    state=state,
                    domain=domain,
                    index=item_index,
                )
                if evidence_ref is not None:
                    finding["evidence_ref"] = evidence_ref
                findings.append(finding)

    required_domains = set(REQUIRED_GATE_DOMAINS)
    present_top_level = {status.get("domain") for status in statuses}
    for domain in REQUIRED_GATE_DOMAINS:
        if domain in present_top_level:
            continue
        _record_diagnostic(state, "required_gate_missing", "required gate result missing: " + domain)
        statuses.append(
            {
                "domain": domain,
                "status": GATE_STATUS_UNKNOWN,
                "reported_status": "missing",
                "blocking": True,
            }
        )
        findings.append(
            {
                "domain": domain,
                "status": GATE_STATUS_UNKNOWN,
                "finding_kind": FINDING_KIND_ERROR,
                "code": domain + "_result_missing",
                "message": "Required Python gate result was not supplied.",
                "origin_field": "missing_gate_result",
                "blocking": True,
                "truncated": False,
            }
        )

    statuses.sort(key=lambda item: (str(item.get("domain")), str(item.get("status"))))
    findings.sort(
        key=lambda item: (
            str(item.get("domain")),
            str(item.get("origin_field")),
            str(item.get("code")),
            str(item.get("message")),
        )
    )
    return statuses[:MAX_GATE_DOMAINS], findings[:MAX_GATE_FINDINGS]


def _safe_summary_items(
    value: Any,
    *,
    state: Dict[str, Any],
    field: str,
) -> List[str]:
    items = _finding_items(value)
    result: List[str] = []
    for index, item in enumerate(items[:MAX_SUMMARY_ITEMS]):
        if isinstance(item, Mapping):
            item = next(
                (
                    item.get(key)
                    for key in _MESSAGE_KEYS + _CODE_KEYS
                    if item.get(key) not in (None, "")
                ),
                None,
            )
        text, _ = _ascii_text(item, MAX_SUMMARY_ITEM_CHARS, state, f"{field}[{index}]")
        if text and text not in result:
            result.append(text)
    if len(items) > MAX_SUMMARY_ITEMS:
        _record_diagnostic(state, "summary_items_truncated", field + " exceeded its item bound")
        state.setdefault("truncated_sections", set()).add(field)
    return result


def _normalize_module_summary(
    raw: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
    field: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, Mapping):
        _record_diagnostic(state, "module_summary_invalid", field + " must be an object")
        return None

    result: Dict[str, Any] = {}
    for key in _SUMMARY_STRING_FIELDS:
        value = raw.get(key)
        if value not in (None, "") and not isinstance(value, (Mapping, list, tuple, set)):
            text, _ = _ascii_text(value, MAX_ATTEMPT_TEXT_CHARS, state, field + "." + key)
            if text:
                result[key] = text
    if "module_slug" in result and not _MODULE_SLUG_RE.fullmatch(result["module_slug"]):
        _record_diagnostic(state, "module_slug_invalid", field + ".module_slug was omitted")
        result.pop("module_slug", None)

    for key in _SUMMARY_LIST_FIELDS:
        if key in raw:
            result[key] = _safe_summary_items(raw.get(key), state=state, field=field + "." + key)

    for key in _SUMMARY_COUNT_FIELDS:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000:
            result[key] = value
        elif value not in (None, ""):
            _record_diagnostic(state, "summary_count_invalid", field + "." + key + " was omitted")

    for key in _SUMMARY_BOOL_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool):
            result[key] = value

    inventory = raw.get("artifact_inventory", raw.get("artifact_counts"))
    if isinstance(inventory, Mapping):
        counts: Dict[str, Any] = {}
        for key in _SUMMARY_COUNT_FIELDS + _SUMMARY_BOOL_FIELDS:
            value = inventory.get(key)
            if isinstance(value, (int, bool)) and not isinstance(value, float):
                counts[key] = value
        if counts:
            result["artifact_inventory"] = counts
    elif inventory not in (None, ""):
        _record_diagnostic(state, "summary_inventory_invalid", field + ".artifact_inventory was omitted")

    refs = raw.get("report_refs", raw.get("artifact_refs"))
    if refs is not None:
        normalized_refs: List[Dict[str, Any]] = []
        for index, ref in enumerate(_finding_items(refs)[:MAX_SOURCE_CONTEXT_REFS]):
            normalized = _safe_reference(
                ref,
                repo_root=repo_root,
                state=state,
                field=f"{field}.report_refs[{index}]",
                role="module_report",
            )
            if normalized is not None:
                normalized_refs.append(normalized)
        if normalized_refs:
            result["report_refs"] = normalized_refs

    reports = raw.get("reports")
    if isinstance(reports, Mapping):
        normalized_reports: List[Dict[str, Any]] = []
        for report_name in _ALLOWED_REPORT_FILES:
            report = reports.get(report_name)
            if isinstance(report, Mapping):
                entry = _normalize_module_summary(
                    {**dict(report), "report_name": report_name},
                    repo_root=repo_root,
                    state=state,
                    field=field + ".reports." + report_name,
                )
                if entry is not None:
                    normalized_reports.append(entry)
        if normalized_reports:
            result["reports"] = normalized_reports
        for key in reports:
            if key not in _ALLOWED_REPORT_FILES:
                state.setdefault("excluded_fields", set()).add(field + ".reports." + str(key))
    elif reports not in (None, ""):
        _record_diagnostic(state, "summary_reports_invalid", field + ".reports was omitted")

    for key in ("report_ref", "report_path", "module_path"):
        if raw.get(key) not in (None, ""):
            ref = _safe_reference(
                raw.get(key),
                repo_root=repo_root,
                state=state,
                field=field + "." + key,
                role="module_report",
            )
            if ref is not None:
                result[key] = ref

    for key in raw:
        if key not in set(_SUMMARY_STRING_FIELDS) | set(_SUMMARY_LIST_FIELDS) | set(_SUMMARY_COUNT_FIELDS) | set(_SUMMARY_BOOL_FIELDS) | {
            "artifact_inventory",
            "artifact_counts",
            "report_refs",
            "artifact_refs",
            "reports",
            "report_ref",
            "report_path",
            "module_path",
        }:
            state.setdefault("excluded_fields", set()).add(field + "." + str(key))

    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_MODULE_SUMMARY_CHARS:
        state.setdefault("truncated_sections", set()).add(field)
        result["truncated"] = True
        if isinstance(result.get("reports"), list):
            result["reports"] = result["reports"][:2]
        for key in ("errors", "blockers", "warnings"):
            if isinstance(result.get(key), list):
                result[key] = result[key][:3]
        if isinstance(result.get("summary"), str):
            result["summary"], _ = _ascii_text(
                result["summary"],
                max(120, MAX_MODULE_SUMMARY_CHARS // 3),
                state,
                field + ".summary",
            )
    return result


def _module_summary_from_dir(
    module_dir: Path,
    *,
    repo_root: Path,
    state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not module_dir.exists() or not module_dir.is_dir() or module_dir.is_symlink():
        _record_diagnostic(state, "module_summary_path_invalid", "module_dir is not a readable directory")
        return None
    summary: Dict[str, Any] = {
        "module_slug": module_dir.name,
        "artifact_inventory": {
            "has_module_context": (module_dir / "module_context.json").is_file(),
            "has_module_plot": (module_dir / "module_plot.json").is_file(),
            "area_count": len(list((module_dir / "areas").glob("*.json"))) if (module_dir / "areas").is_dir() else 0,
            "monster_count": len(list((module_dir / "monsters").glob("*.json"))) if (module_dir / "monsters").is_dir() else 0,
        },
        "reports": {},
    }
    for report_name in _ALLOWED_REPORT_FILES:
        path = module_dir / report_name
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except Exception:
            _record_diagnostic(state, "module_report_unreadable", report_name + " could not be read")
            continue
        report_ref: Dict[str, Any] = {
            "path": _safe_path(path, repo_root=repo_root, state=state, field="module_report.path"),
            "role": "module_report",
        }
        if size > MAX_REPORT_BYTES:
            summary["reports"][report_name] = {
                "report_name": report_name,
                "status": "unknown",
                "summary": "Report exceeded the bounded read size.",
                "truncated": True,
                "report_ref": report_ref,
            }
            state.setdefault("truncated_sections", set()).add("module_report." + report_name)
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            report_ref["sha256"] = digest
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"status": "unknown", "errors": ["report_json_unreadable"]}
        if isinstance(payload, Mapping):
            summary["reports"][report_name] = {
                **dict(payload),
                "report_name": report_name,
                "report_ref": report_ref,
            }
    return summary


def _normalize_module_summaries(
    values: Any,
    *,
    module_dir: Optional[Path],
    repo_root: Path,
    state: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    raw_items: List[Any] = []
    if values is None and module_dir is not None:
        summary = _module_summary_from_dir(module_dir, repo_root=repo_root, state=state)
        if summary is not None:
            raw_items = [summary]
    elif isinstance(values, Mapping):
        summary_keys = set(_SUMMARY_STRING_FIELDS) | set(_SUMMARY_LIST_FIELDS) | set(_SUMMARY_COUNT_FIELDS) | {
            "artifact_inventory",
            "artifact_counts",
            "report_refs",
            "artifact_refs",
            "reports",
            "report_ref",
            "report_path",
            "module_path",
        }
        if set(values).intersection(summary_keys):
            raw_items = [values]
        elif values and all(isinstance(item, Mapping) for item in values.values()):
            for slug, item in sorted(values.items(), key=lambda pair: str(pair[0])):
                raw_items.append({"module_slug": slug, **dict(item)})
        else:
            raw_items = [values]
    elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        raw_items = list(values)
    elif values not in (None, ""):
        _record_diagnostic(state, "module_summaries_invalid", "module_summaries must be bounded objects")

    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_items[:MAX_MODULE_SUMMARIES]):
        item = _normalize_module_summary(
            raw,
            repo_root=repo_root,
            state=state,
            field=f"module_summaries[{index}]",
        )
        if item is not None:
            normalized.append(item)
    if len(raw_items) > MAX_MODULE_SUMMARIES:
        _record_diagnostic(state, "module_summary_count_truncated", "additional module summaries were omitted")
        state.setdefault("truncated_sections", set()).add("module_summaries")

    fitted: List[Dict[str, Any]] = []
    total_chars = 0
    for item in normalized:
        encoded = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded) > MAX_MODULE_SUMMARY_CHARS:
            item = {
                key: item[key]
                for key in ("module_slug", "module_title", "status", "ready_status", "publishable_status")
                if key in item
            }
            item["summary"] = "Module summary exceeded the per-summary bound."
            item["truncated"] = True
            encoded = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            state.setdefault("truncated_sections", set()).add("module_summaries")
        additional_chars = len(encoded) + (1 if fitted else 2)
        if total_chars + additional_chars > MAX_MODULE_SUMMARIES_CHARS:
            _record_diagnostic(state, "module_summary_total_truncated", "additional module summary content was omitted")
            state.setdefault("truncated_sections", set()).add("module_summaries")
            break
        fitted.append(item)
        total_chars += additional_chars
    return fitted, {
        "per_summary_chars": MAX_MODULE_SUMMARY_CHARS,
        "total_chars": MAX_MODULE_SUMMARIES_CHARS,
        "included_chars": total_chars,
        "included_count": len(fitted),
        "truncated": "module_summaries" in state.get("truncated_sections", set()),
    }


def _normalize_attempt_metadata(
    metadata: Any,
    *,
    staging_target: Any,
    stage: Optional[str],
    revision_number: Optional[int],
    repo_root: Path,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    raw = dict(metadata) if isinstance(metadata, Mapping) else {}
    if isinstance(raw.get("provenance"), Mapping):
        merged = dict(raw["provenance"])
        merged.update({key: value for key, value in raw.items() if key != "provenance"})
        raw = merged
    target = staging_target if isinstance(staging_target, Mapping) else {}

    def value(key: str) -> Any:
        return raw.get(key, target.get(key))

    result: Dict[str, Any] = {}
    attempt_id = value("attempt_id")
    if isinstance(attempt_id, str) and _ATTEMPT_ID_RE.fullmatch(attempt_id.strip()):
        result["attempt_id"] = attempt_id.strip()
    else:
        _record_diagnostic(state, "attempt_id_required", "a path-safe attempt_id is required")
    attempt_number = value("attempt_number")
    if isinstance(attempt_number, int) and not isinstance(attempt_number, bool) and 1 <= attempt_number <= 1_000_000:
        result["attempt_number"] = attempt_number
    else:
        _record_diagnostic(state, "attempt_number_invalid", "attempt_number is outside the supported range")

    resolved_revision = revision_number if revision_number is not None else value("revision_number")
    if isinstance(resolved_revision, int) and not isinstance(resolved_revision, bool) and 0 <= resolved_revision <= 100:
        result["revision_number"] = resolved_revision
    else:
        _record_diagnostic(state, "revision_number_invalid", "revision_number is outside the supported range")

    resolved_stage = stage or value("stage") or value("failed_stage") or "adaptation_gate_composition"
    stage_text, _ = _ascii_text(resolved_stage, MAX_ATTEMPT_TEXT_CHARS, state, "attempt_metadata.stage")
    if not stage_text or not _SAFE_TOKEN_RE.fullmatch(stage_text):
        _record_diagnostic(state, "stage_invalid", "stage must be a bounded identifier")
    else:
        result["stage"] = stage_text

    source_hash = _safe_hash(value("source_hash"), state, "attempt_metadata.source_hash")
    if source_hash is not None:
        result["source_hash"] = source_hash
    else:
        _record_diagnostic(state, "source_hash_required", "source_hash is required for a failure packet")
    source_path = _safe_path(value("source_path"), repo_root=repo_root, state=state, field="attempt_metadata.source_path")
    if source_path is not None:
        result["source_path"] = source_path
    else:
        _record_diagnostic(state, "source_path_required", "source_path must be project-relative")

    for key in (
        "source_title",
        "source_format",
        "job_id",
        "stage_id",
        "world_seed_version",
        "world_context_version",
        "world_context_selected_module",
    ):
        if value(key) not in (None, ""):
            text, _ = _ascii_text(value(key), MAX_ATTEMPT_TEXT_CHARS, state, "attempt_metadata." + key)
            if text:
                result[key] = text

    profile = value("source_profile")
    if profile not in (None, ""):
        profile_text, _ = _ascii_text(profile, 64, state, "attempt_metadata.source_profile")
        if profile_text.lower() not in VALID_SOURCE_PROFILES:
            _record_diagnostic(state, "source_profile_invalid", "source_profile is not an allowed profile")
        else:
            result["source_profile"] = profile_text.lower()

    adaptation_mode = value("adaptation_mode") or ADAPTATION_MODE_LLM
    if value("adaptation_mode") in (None, ""):
        _record_diagnostic(state, "adaptation_mode_missing", "adaptation_mode is required")
    if adaptation_mode != ADAPTATION_MODE_LLM:
        _record_diagnostic(state, "adaptation_mode_invalid", "failure packet requires llm_adaptation mode")
    result["adaptation_mode"] = ADAPTATION_MODE_LLM

    rights_class = value("rights_class")
    if rights_class in VALID_RIGHTS_CLASSES:
        result["rights_class"] = rights_class
    else:
        _record_diagnostic(state, "rights_class_invalid", "rights_class is missing or unsupported")
    if value("rights_basis") not in (None, ""):
        text, _ = _ascii_text(value("rights_basis"), MAX_ATTEMPT_TEXT_CHARS, state, "attempt_metadata.rights_basis")
        if text:
            result["rights_basis"] = text
    else:
        _record_diagnostic(state, "rights_basis_required", "rights_basis is required")
    review_required = value("rights_review_required")
    if isinstance(review_required, bool):
        result["rights_review_required"] = review_required
    else:
        _record_diagnostic(state, "rights_review_required_invalid", "rights_review_required must be boolean")
    review_status = value("rights_review_status")
    if review_status in VALID_RIGHTS_REVIEW_STATUSES:
        result["rights_review_status"] = review_status
    else:
        _record_diagnostic(state, "rights_review_status_invalid", "rights_review_status is missing or unsupported")

    model_metadata = value("model_metadata")
    if not isinstance(model_metadata, Mapping):
        model_metadata = {}
        _record_diagnostic(state, "model_metadata_missing", "model metadata was not supplied")
    normalized_model: Dict[str, Any] = {}
    allowed_model_keys = {
        "provider",
        "model",
        "model_version",
        "request_id",
        "parameter_profile",
        "temperature",
        "reasoning_effort",
        "verbosity",
    }
    for key, raw_value in model_metadata.items():
        key_text = str(key)
        if key_text.lower() in _FORBIDDEN_KEYS or _SECRET_KEY_RE.search(key_text):
            state.setdefault("redacted_fields", set()).add("attempt_metadata.model_metadata." + key_text)
            continue
        if key_text not in allowed_model_keys:
            state.setdefault("excluded_fields", set()).add("attempt_metadata.model_metadata." + key_text)
            continue
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            if key_text == "temperature" and not 0 <= float(raw_value) <= 2:
                _record_diagnostic(state, "model_metadata_invalid", "temperature is outside the supported range")
                continue
            normalized_model[key_text] = raw_value
        elif isinstance(raw_value, str):
            text, _ = _ascii_text(raw_value, MAX_ATTEMPT_TEXT_CHARS, state, "attempt_metadata.model_metadata." + key_text)
            if text:
                normalized_model[key_text] = text
        else:
            _record_diagnostic(state, "model_metadata_invalid", "model metadata values must be bounded scalars")
    if normalized_model:
        result["model_metadata"] = normalized_model
    else:
        _record_diagnostic(state, "model_metadata_missing", "bounded model metadata is required")

    artifact_refs: List[Dict[str, Any]] = []
    for key in ("source_context_artifact_path", "dossier_artifact_path", "failure_artifact_path", "revision_report_path"):
        if value(key) not in (None, ""):
            ref = _safe_reference(
                value(key),
                repo_root=repo_root,
                state=state,
                field="attempt_metadata." + key,
                role=key,
            )
            if ref is not None:
                artifact_refs.append(ref)
    if artifact_refs:
        result["artifact_refs"] = sorted(
            artifact_refs,
            key=lambda item: (str(item.get("role", "")), str(item.get("path", "")), str(item.get("sha256", ""))),
        )
    world_seed_hash = _safe_hash(value("world_seed_hash"), state, "attempt_metadata.world_seed_hash") if value("world_seed_hash") not in (None, "") else None
    if world_seed_hash is not None:
        result["world_seed_hash"] = world_seed_hash
    if value("world_context_read_only") is not None:
        if value("world_context_read_only") is True:
            result["world_context_read_only"] = True
        else:
            _record_diagnostic(state, "world_context_authority_invalid", "world context must be read-only")
    for key in ("world_seed_status", "world_context_status"):
        raw_status = value(key)
        if raw_status not in (None, ""):
            text, _ = _ascii_text(raw_status, 64, state, "attempt_metadata." + key)
            allowed = {"available", "unavailable", "invalid"} if key == "world_seed_status" else {"available", "fallback", "unavailable"}
            if text.lower() not in allowed:
                _record_diagnostic(state, "world_context_status_invalid", key + " is invalid")
            else:
                result[key] = text.lower()
    for key in ("world_context_hash", "context_hash"):
        digest = _safe_hash(value(key), state, "attempt_metadata." + key) if value(key) not in (None, "") else None
        if digest is not None:
            result[key] = digest
    return result


def _normalize_staging_reference(
    target: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(target, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for key in ("stage_id", "target_kind", "completion_state"):
        if target.get(key) not in (None, ""):
            text, _ = _ascii_text(target.get(key), MAX_ATTEMPT_TEXT_CHARS, state, "staging_reference." + key)
            if text:
                result[key] = text
    for key in ("attempt_id", "attempt_number", "revision_number"):
        value = target.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result[key] = value
        elif key == "attempt_id" and isinstance(value, str) and _ATTEMPT_ID_RE.fullmatch(value):
            result[key] = value
    path = _safe_path(target.get("path") or target.get("output_directory"), repo_root=repo_root, state=state, field="staging_reference.path")
    if path is not None:
        result["path"] = path
    digest = _safe_hash(target.get("source_hash"), state, "staging_reference.source_hash") if target.get("source_hash") not in (None, "") else None
    if digest is not None:
        result["source_hash"] = digest
    result["reference_only"] = True
    return result


def _normalize_source_context_refs(
    source_context: Any,
    explicit_refs: Any,
    *,
    source_hash: Optional[str],
    repo_root: Path,
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Tuple[Any, str]] = []
    if explicit_refs is not None:
        for value in _finding_items(explicit_refs):
            candidates.append((value, "explicit_source_context"))
    context = source_context if isinstance(source_context, Mapping) else {}
    if isinstance(context.get("payload"), Mapping):
        context = context["payload"]
    for key, role in (
        ("source_ref", "source"),
        ("manifest_ref", "manifest"),
        ("source_context_ref", "source_context"),
    ):
        if context.get(key) not in (None, ""):
            candidates.append((context.get(key), role))
    for key in ("bounded_context_refs", "source_context_refs", "source_inputs"):
        values = context.get(key)
        for value in _finding_items(values):
            if key == "source_inputs" and isinstance(value, Mapping):
                value = value.get("source_ref")
            if value not in (None, ""):
                candidates.append((value, "source_context"))

    result: List[Dict[str, Any]] = []
    seen = set()
    for index, (candidate, role) in enumerate(candidates[:MAX_SOURCE_CONTEXT_REFS * 2]):
        ref = _safe_reference(
            candidate,
            repo_root=repo_root,
            state=state,
            field=f"source_context_refs[{index}]",
            role=role,
            expected_hash=source_hash,
        )
        if ref is None:
            continue
        identity = (ref.get("path", ""), ref.get("sha256", ""), ref.get("role", ""))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    result.sort(key=lambda item: (str(item.get("role", "")), str(item.get("path", "")), str(item.get("sha256", ""))))
    if len(result) > MAX_SOURCE_CONTEXT_REFS:
        state.setdefault("truncated_sections", set()).add("source_context_refs")
        _record_diagnostic(state, "source_context_ref_limit", "additional source context references were omitted")
    return result[:MAX_SOURCE_CONTEXT_REFS]


def _normalize_publication_goals(
    values: Any,
    *,
    state: Dict[str, Any],
) -> List[str]:
    raw_values = DEFAULT_PUBLICATION_GOALS if values is None else _finding_items(values)
    selected = set()
    aliases = {
        "schema_validation": "schema",
        "mechanical": "mechanical_closure",
        "semantic": "semantic_authority",
        "registry": "registry_verification",
        "markdown": "markdown_quality",
    }
    for index, value in enumerate(raw_values[:MAX_PUBLICATION_GOALS * 2]):
        if not isinstance(value, str):
            state.setdefault("excluded_fields", set()).add(f"publication_goals[{index}]")
            continue
        token = value.strip().lower()
        token = aliases.get(token, token)
        if token not in ALLOWED_PUBLICATION_GOALS:
            state.setdefault("excluded_fields", set()).add(f"publication_goals[{index}]")
            _record_diagnostic(state, "publication_goal_rejected", "publication goal is not allowlisted")
            continue
        selected.add(token)
    if len(raw_values) > MAX_PUBLICATION_GOALS:
        state.setdefault("truncated_sections", set()).add("publication_goals")
        _record_diagnostic(state, "publication_goal_limit", "additional publication goals were omitted")
    # Canonical order makes the packet stable regardless of caller ordering.
    return [goal for goal in ALLOWED_PUBLICATION_GOALS if goal in selected]


def _normalize_failure_classification(
    value: Any,
    *,
    state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    allowed = (
        "failure_class",
        "failure_group",
        "classification_status",
        "stage",
        "failed_stage",
        "domain",
        "failure_domain",
        "code",
        "message",
        "retryable",
        "terminal",
        "blocked",
        "next_revision_eligible",
        "revision_eligible",
        "semantic_revision_eligible",
        "semantic_revision_budget_consumed",
        "consumes_semantic_revision_budget",
    )
    result: Dict[str, Any] = {}
    for key in allowed:
        raw = value.get(key)
        if isinstance(raw, bool):
            result[key] = raw
        elif raw not in (None, ""):
            text, _ = _ascii_text(raw, MAX_FINDING_MESSAGE_CHARS, state, "failure_classification." + key)
            if text:
                result[key] = text
    diagnostics = value.get("diagnostics")
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        bounded_diagnostics: List[Dict[str, str]] = []
        for item in list(diagnostics)[:8]:
            if isinstance(item, Mapping):
                code = item.get("code") or value.get("code") or "content_gate_failed"
                message = item.get("message") or item.get("reason") or value.get("message") or "content gate failed"
            else:
                code = value.get("code") or "content_gate_failed"
                message = item
            bounded_diagnostics.append(_diagnostic(str(code), str(message), state))
        if bounded_diagnostics:
            result["diagnostics"] = bounded_diagnostics
    budget = value.get("revision_budget")
    if isinstance(budget, Mapping):
        normalized_budget: Dict[str, Any] = {}
        for key in ("current_revision", "max_revisions", "remaining_before_failure", "explicit_opt_in", "decision"):
            raw = budget.get(key)
            if isinstance(raw, bool):
                normalized_budget[key] = raw
            elif isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 100:
                normalized_budget[key] = raw
            elif isinstance(raw, str) and key == "decision":
                text, _ = _ascii_text(raw, 64, state, "failure_classification.revision_budget.decision")
                normalized_budget[key] = text
        if normalized_budget:
            result["revision_budget"] = normalized_budget
    result["publication_allowed"] = False
    result["advisory"] = True
    return result


def _packet_state() -> Dict[str, Any]:
    return {
        "diagnostics": [],
        "redacted_fields": set(),
        "excluded_fields": set(),
        "truncated_sections": set(),
    }


def _world_context_attempt_fields(provenance: Mapping[str, Any]) -> Dict[str, Any]:
    """Return only scalar world provenance fields for packet identity."""
    values = {
        "world_seed_status": provenance.get("world_seed_status"),
        "world_seed_version": provenance.get("world_seed_version"),
        "world_seed_hash": provenance.get("world_seed_hash"),
        "world_context_status": provenance.get("context_status"),
        "world_context_version": provenance.get("context_version"),
        "world_context_hash": provenance.get("context_hash"),
        "context_hash": provenance.get("context_hash"),
        "world_context_selected_module": provenance.get("selected_module"),
        "world_context_read_only": provenance.get("read_only"),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _monster_safe_text(value: Any, limit: int, field: str = "") -> str:
    """Return a single-line ASCII excerpt with source/provider details removed."""
    if isinstance(value, (Mapping, list, tuple, set)) or value is None:
        return ""
    text, _ = _ascii_text(value, limit, None, field)
    # Evidence is for interpretation, not retrieval.  Do not let a source
    # path, provider payload, or exception traceback cross this boundary.
    text = re.sub(r"(?i)(?:https?://|file://|/|\\)[^\s;]+", "[REDACTED_REFERENCE]", text)
    text = re.sub(r"(?i)\b(?:provider|openai|httpx|httpcore|request[_ -]?body|response[_ -]?headers)\b[^;]*", "[REDACTED_PROVIDER_DETAIL]", text)
    text = re.sub(r"(?i)(?:api[_ -]?key|authorization|bearer|credential|password|secret|token)\s*[:=]?\s*[^\s,;]+", "[REDACTED_CREDENTIAL]", text)
    return " ".join(text.split()).strip()[:limit]


def _monster_safe_id(value: Any, field: str) -> str:
    text = _monster_safe_text(value, 160, field)
    if not text or not _SAFE_TOKEN_RE.fullmatch(text):
        return ""
    return text


def _monster_slug(value: Any) -> str:
    text = _monster_safe_text(value, 160, "monster_reference")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _monster_quantity(value: Any) -> Optional[Dict[str, int]]:
    if isinstance(value, Mapping):
        minimum, maximum = value.get("min"), value.get("max")
        if isinstance(minimum, int) and not isinstance(minimum, bool) and isinstance(maximum, int) and not isinstance(maximum, bool):
            if 0 <= minimum <= maximum <= 999:
                return {"min": minimum, "max": maximum}
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 999:
        return {"min": value, "max": value}
    return None


def _monster_registry_entry(registry: Any, normalized_reference: str) -> Optional[Mapping[str, Any]]:
    if not isinstance(registry, Mapping):
        return None
    target = _monster_slug(normalized_reference)
    target_folded = target[:-1] if target.endswith("s") else target
    for entry in registry.get("entries", []) if isinstance(registry.get("entries"), list) else []:
        if not isinstance(entry, Mapping):
            continue
        candidate = _monster_slug(entry.get("canonical_slug") or entry.get("canonical_identity"))
        if candidate == target or candidate == target_folded or candidate + "s" == target:
            return entry
    return None


def build_adaptation_monster_failure_packet(
    failure: Optional[Mapping[str, Any]] = None,
    *,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    revision_budget: Optional[Mapping[str, Any]] = None,
    canonical_registry: Any = None,
    guardrail_report: Any = None,
    normalized_reference: Any = None,
    raw_reference: Any = None,
    approved_canonical_identities: Any = None,
    candidate_canonical_identities: Any = None,
    affected_locations: Any = None,
    quantity_records: Any = None,
    scene_evidence: Any = None,
    source_reference_ids: Any = None,
    failure_code: Any = "monster_reference_unresolved",
    failed_stage: Any = "adaptation_monster_guardrail",
) -> Dict[str, Any]:
    """Build the redacted, provider-free monster remediation handoff.

    This contract deliberately accepts content diagnostics, never source
    documents or provider responses.  Raw labels are retained only as bounded
    labels beside the normalized identity; filesystem references are not part
    of this packet.
    """
    failure = failure if isinstance(failure, Mapping) else {}
    report = guardrail_report if isinstance(guardrail_report, Mapping) else failure
    registry_entry = _monster_registry_entry(canonical_registry, normalized_reference or failure.get("normalized_reference"))
    normalized = _monster_slug(normalized_reference or failure.get("normalized_reference") or failure.get("raw_reference") or "")
    raw = _monster_safe_text(raw_reference or failure.get("raw_reference") or failure.get("reference") or normalized, 160, "raw_reference")

    approved_values = approved_canonical_identities
    if approved_values is None and registry_entry is not None:
        approved_values = [registry_entry.get("canonical_identity")]
    if approved_values is None and isinstance(canonical_registry, Mapping):
        approved_values = canonical_registry.get("approved_identities", [])
    candidates = candidate_canonical_identities
    if candidates is None and registry_entry is not None:
        candidates = [registry_entry.get("canonical_identity")]
    if candidates is None:
        candidates = approved_values

    def identities(values: Any) -> List[str]:
        items = [values] if isinstance(values, str) else values if isinstance(values, Sequence) and not isinstance(values, (bytes, str)) else []
        result: List[str] = []
        for value in items[:MAX_MONSTER_IDENTITIES]:
            text = _monster_safe_text(value, 160, "canonical_identity")
            if text and text not in result:
                result.append(text)
        return sorted(result)

    locations: List[str] = []
    raw_locations = affected_locations
    if raw_locations is None and registry_entry is not None:
        raw_locations = registry_entry.get("affected_location_ids", [])
    for value in (raw_locations or []) if isinstance(raw_locations, Sequence) and not isinstance(raw_locations, (str, bytes)) else []:
        location = _monster_safe_id(value, "location_id")
        if location and _LOCATION_ID_RE.fullmatch(location) and location not in locations:
            locations.append(location)

    records: List[Dict[str, Any]] = []
    raw_quantities = quantity_records
    if raw_quantities is None and registry_entry is not None:
        raw_quantities = registry_entry.get("quantity_evidence", [])
    for item in raw_quantities or [] if isinstance(raw_quantities, Sequence) and not isinstance(raw_quantities, (str, bytes)) else []:
        if not isinstance(item, Mapping):
            continue
        location = _monster_safe_id(item.get("location_id") or item.get("location"), "quantity.location_id")
        quantity = _monster_quantity(item.get("quantity"))
        if not location or quantity is None:
            continue
        record: Dict[str, Any] = {"location_id": location, "quantity": quantity}
        encounter = _monster_safe_id(item.get("encounter_reference") or item.get("encounter_id"), "quantity.encounter_id")
        if encounter:
            record["encounter_id"] = encounter
        records.append(record)
        if location not in locations:
            locations.append(location)
        if len(records) >= MAX_MONSTER_QUANTITY_RECORDS:
            break
    records.sort(key=lambda item: (item["location_id"], item.get("encounter_id", ""), item["quantity"]["min"], item["quantity"]["max"]))

    evidence: List[Dict[str, Any]] = []
    raw_evidence = scene_evidence
    if raw_evidence is None and isinstance(report, Mapping):
        raw_evidence = report.get("contradiction_diagnostics", [])
    for item in raw_evidence or [] if isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, (str, bytes)) else []:
        if not isinstance(item, Mapping):
            continue
        location = _monster_safe_id(item.get("source_location") or item.get("location_id"), "evidence.location_id")
        excerpt = _monster_safe_text(item.get("scene_evidence") or item.get("evidence") or item.get("message"), MAX_MONSTER_EVIDENCE_CHARS, "scene_evidence")
        if not excerpt:
            continue
        entry: Dict[str, Any] = {"location_id": location or "unknown", "excerpt": excerpt}
        code = _monster_safe_id(item.get("code"), "evidence.code")
        if code:
            entry["diagnostic_code"] = code
        evidence.append(entry)
        if location and location not in locations:
            locations.append(location)
        if len(evidence) >= MAX_MONSTER_SCENE_EVIDENCE:
            break
    evidence.sort(key=lambda item: (item["location_id"], item.get("diagnostic_code", ""), item["excerpt"]))

    attempt = attempt_metadata if isinstance(attempt_metadata, Mapping) else {}
    attempt_id = _monster_safe_id(attempt.get("attempt_id") or failure.get("attempt_id"), "attempt_id")
    revision = attempt.get("revision_number", failure.get("revision_number", 0))
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or revision > 100:
        revision = 0
    budget = dict(revision_budget or failure.get("revision_budget") or {})
    current = budget.get("current_revision", revision)
    maximum = budget.get("max_revisions", budget.get("maximum", 0))
    current = current if isinstance(current, int) and not isinstance(current, bool) and 0 <= current <= 100 else revision
    maximum = maximum if isinstance(maximum, int) and not isinstance(maximum, bool) and 0 <= maximum <= 100 else 0
    remaining = budget.get("remaining_before_failure", max(0, maximum - current))
    remaining = remaining if isinstance(remaining, int) and not isinstance(remaining, bool) and 0 <= remaining <= 100 else max(0, maximum - current)
    source_ids: List[str] = []
    for value in source_reference_ids or (registry_entry.get("approval_provenance", []) if registry_entry else []):
        value = value.get("source") if isinstance(value, Mapping) else value
        token = _monster_safe_text(value, 160, "source_reference_id")
        token = re.sub(r"[^A-Za-z0-9._:-]+", "_", token).strip("_")
        if token and token not in source_ids and "path" not in token.lower():
            source_ids.append(token)
    packet = {
        "contract_version": MONSTER_FAILURE_PACKET_CONTRACT_VERSION,
        "packet_kind": "monster_content_failure",
        "packet_status": "blocked",
        "adaptation_only": True,
        "attempt": {"attempt_id": attempt_id, "revision_number": revision},
        "failure": {"code": _monster_safe_id(failure_code, "failure_code"), "stage": _monster_safe_id(failed_stage, "failed_stage")},
        "unresolved_reference": {"normalized": normalized, "raw_label": raw},
        "canonical_identities": {"approved": identities(approved_values), "candidates": identities(candidates)},
        "affected_location_ids": sorted(locations)[:MAX_MONSTER_LOCATIONS],
        "quantity_records": records,
        "scene_evidence": evidence,
        "source_reference_ids": sorted(source_ids)[:MAX_MONSTER_SOURCE_REFERENCE_IDS],
        "revision_budget": {"current_revision": current, "max_revisions": maximum, "remaining": remaining, "next_revision_eligible": bool(remaining > 0)},
        "security": {"raw_source_included": False, "provider_payloads_included": False, "credentials_included": False, "paths_included": False},
        "raw_provider_payload_exposed": False,
        "bounds": {"max_serialized_chars": MAX_MONSTER_PACKET_CHARS, "max_evidence_chars": MAX_MONSTER_EVIDENCE_CHARS},
    }
    serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_MONSTER_PACKET_CHARS:
        packet["scene_evidence"] = packet["scene_evidence"][:4]
        packet["source_reference_ids"] = packet["source_reference_ids"][:8]
        serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_MONSTER_PACKET_CHARS:
        packet["packet_status"] = "invalid"
    return packet


def validate_adaptation_monster_failure_packet(
    packet: Any,
    *,
    expected_attempt_id: Optional[str] = None,
    expected_revision_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate association, bounds, ASCII safety, and redaction markers."""
    if not isinstance(packet, Mapping):
        return {"valid": False, "diagnostics": ["packet_type_invalid"]}
    diagnostics: List[str] = []
    allowed_top = {
        "contract_version", "packet_kind", "packet_status", "adaptation_only",
        "attempt", "failure", "unresolved_reference", "canonical_identities",
        "affected_location_ids", "quantity_records", "scene_evidence",
        "source_reference_ids", "revision_budget", "security", "bounds",
        "raw_provider_payload_exposed",
    }
    if set(packet) - allowed_top:
        diagnostics.append("unknown_packet_field")
    if packet.get("contract_version") != MONSTER_FAILURE_PACKET_CONTRACT_VERSION:
        diagnostics.append("contract_version_invalid")
    if packet.get("packet_kind") != "monster_content_failure":
        diagnostics.append("packet_kind_invalid")
    attempt = packet.get("attempt")
    if not isinstance(attempt, Mapping) or not _monster_safe_id(attempt.get("attempt_id"), "attempt_id"):
        diagnostics.append("attempt_identity_invalid")
    if expected_attempt_id is not None and (not isinstance(attempt, Mapping) or attempt.get("attempt_id") != expected_attempt_id):
        diagnostics.append("attempt_identity_mismatch")
    if not isinstance(attempt, Mapping) or not isinstance(attempt.get("revision_number"), int) or isinstance(attempt.get("revision_number"), bool):
        diagnostics.append("revision_identity_invalid")
    if expected_revision_number is not None and (not isinstance(attempt, Mapping) or attempt.get("revision_number") != expected_revision_number):
        diagnostics.append("revision_identity_mismatch")
    budget = packet.get("revision_budget")
    if isinstance(budget, Mapping) and isinstance(attempt, Mapping) and budget.get("current_revision") != attempt.get("revision_number"):
        diagnostics.append("revision_budget_mismatch")
    failure = packet.get("failure")
    unresolved = packet.get("unresolved_reference")
    if not isinstance(failure, Mapping) or not failure.get("code") or not failure.get("stage"):
        diagnostics.append("failure_identity_invalid")
    if not isinstance(unresolved, Mapping) or not _monster_slug(unresolved.get("normalized")):
        diagnostics.append("normalized_reference_invalid")
    if not isinstance(packet.get("quantity_records"), list) or len(packet["quantity_records"]) > MAX_MONSTER_QUANTITY_RECORDS:
        diagnostics.append("quantity_records_invalid")
    if not isinstance(packet.get("scene_evidence"), list) or len(packet["scene_evidence"]) > MAX_MONSTER_SCENE_EVIDENCE:
        diagnostics.append("scene_evidence_invalid")
    else:
        for evidence in packet["scene_evidence"]:
            if not isinstance(evidence, Mapping) or not isinstance(evidence.get("excerpt"), str) or len(evidence["excerpt"]) > MAX_MONSTER_EVIDENCE_CHARS or not evidence["excerpt"].isascii():
                diagnostics.append("scene_evidence_bound_invalid")
                break
    security = packet.get("security")
    if not isinstance(security, Mapping) or any(security.get(key) is not False for key in ("raw_source_included", "provider_payloads_included", "credentials_included", "paths_included")):
        diagnostics.append("security_marker_invalid")
    if packet.get("raw_provider_payload_exposed") is not False:
        diagnostics.append("raw_provider_payload_marker_invalid")
    serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_MONSTER_PACKET_CHARS:
        diagnostics.append("packet_total_limit")
    if not serialized.isascii():
        diagnostics.append("ascii_required")
    forbidden = ("raw_source", "full_prompt", "provider_response", "authorization", "api_key", "request_body", "absolute_path")
    scanned = json.dumps({key: value for key, value in packet.items() if key not in {"security", "bounds"}}, ensure_ascii=True, sort_keys=True).lower()
    if any(token in scanned for token in forbidden):
        diagnostics.append("redaction_leak")
    return {"valid": not diagnostics, "status": "valid" if not diagnostics else "invalid", "packet": deepcopy(dict(packet)) if not diagnostics else None, "diagnostics": diagnostics}


def serialize_adaptation_monster_failure_packet(packet: Mapping[str, Any]) -> str:
    result = validate_adaptation_monster_failure_packet(packet)
    if not result["valid"]:
        raise ValueError("invalid adaptation monster failure packet: " + ",".join(result["diagnostics"]))
    return json.dumps(result["packet"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def persist_adaptation_monster_failure_packet(
    packet: Mapping[str, Any],
    target_path: Path,
    *,
    repo_root: Optional[Path] = None,
) -> bool:
    """Atomically persist one validated packet beneath the project root."""
    root = Path(repo_root or _REPO_ROOT).resolve()
    target = Path(target_path)
    try:
        resolved = target.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    try:
        serialized = serialize_adaptation_monster_failure_packet(packet)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_name(resolved.name + ".tmp")
        temporary.write_text(serialized, encoding="ascii")
        os.replace(str(temporary), str(resolved))
        return resolved.read_text(encoding="ascii") == serialized
    except (OSError, UnicodeError, ValueError, TypeError):
        try:
            if 'temporary' in locals() and temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        return False


def build_adaptation_failure_packet(
    gate_results: Any,
    *,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    staging_target: Optional[Mapping[str, Any]] = None,
    module_summaries: Any = None,
    current_module_summaries: Any = None,
    current_module_summary: Any = None,
    module_dir: Optional[Path] = None,
    source_context: Any = None,
    source_context_refs: Any = None,
    publication_goals: Any = None,
    failure_classification: Any = None,
    world_context: Any = None,
    world_context_provenance: Any = None,
    stage: Optional[str] = None,
    revision_number: Optional[int] = None,
    repo_root: Optional[Path] = None,
    monster_content_failure: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic bounded packet for a failed adaptation attempt.

    All inputs are treated as Python-owned diagnostics. Unknown keys are
    omitted, source context text is never copied, and the returned packet
    cannot authorize publication. This helper performs no file writes; when
    ``module_dir`` is supplied it reads only the allowlisted report files and
    artifact names used for a compact summary.
    """
    state = _packet_state()
    root = Path(repo_root or _REPO_ROOT).resolve()
    if not isinstance(root, Path):
        root = _REPO_ROOT

    raw_container = gate_results if isinstance(gate_results, Mapping) else {}
    if attempt_metadata is None and isinstance(raw_container.get("provenance"), Mapping):
        attempt_metadata = raw_container.get("provenance")
    if staging_target is None and isinstance(raw_container.get("staging_target"), Mapping):
        staging_target = raw_container.get("staging_target")
    if module_summaries is None:
        if current_module_summaries is not None:
            module_summaries = current_module_summaries
        elif current_module_summary is not None:
            module_summaries = current_module_summary
        else:
            for key in ("module_summaries", "current_module_summaries", "module_summary", "current_module_summary"):
                if raw_container.get(key) is not None:
                    module_summaries = raw_container.get(key)
                    break
    if failure_classification is None:
        failure_classification = raw_container.get("failure_classification")

    selected_world_context = world_context
    if selected_world_context is None and world_context_provenance is not None:
        selected_world_context = world_context_provenance
    world_provenance = build_world_context_provenance(
        selected_world_context if selected_world_context is not None else attempt_metadata
    )
    if selected_world_context is not None:
        attempt_metadata = dict(attempt_metadata or {})
        attempt_metadata.update(_world_context_attempt_fields(world_provenance))

    normalized_attempt = _normalize_attempt_metadata(
        attempt_metadata,
        staging_target=staging_target,
        stage=stage,
        revision_number=revision_number,
        repo_root=root,
        state=state,
    )
    source_hash = normalized_attempt.get("source_hash")
    normalized_staging = _normalize_staging_reference(
        staging_target,
        repo_root=root,
        state=state,
    )
    if not normalized_staging:
        _record_diagnostic(state, "staging_reference_required", "a staging reference is required")
    if normalized_staging.get("source_hash") and source_hash and normalized_staging["source_hash"] != source_hash:
        _record_diagnostic(state, "staging_source_hash_mismatch", "staging source hash does not match attempt metadata")
    if normalized_staging.get("attempt_id") and normalized_attempt.get("attempt_id") and normalized_staging["attempt_id"] != normalized_attempt["attempt_id"]:
        _record_diagnostic(state, "staging_attempt_mismatch", "staging attempt does not match attempt metadata")

    statuses, findings = _normalize_gate_findings(
        gate_results,
        repo_root=root,
        state=state,
    )
    summaries, summary_bounds = _normalize_module_summaries(
        module_summaries,
        module_dir=Path(module_dir) if module_dir is not None else None,
        repo_root=root,
        state=state,
    )
    context_refs = _normalize_source_context_refs(
        source_context,
        source_context_refs,
        source_hash=source_hash,
        repo_root=root,
        state=state,
    )
    if not context_refs and source_hash and normalized_attempt.get("source_path"):
        context_refs = [
            {
                "path": normalized_attempt["source_path"],
                "sha256": source_hash,
                "role": "source",
                "reference_only": True,
            }
        ]
    goals = _normalize_publication_goals(publication_goals, state=state)
    missing_or_blocked = bool(
        state["diagnostics"]
        or any(item.get("blocking") for item in statuses)
        or any(item.get("blocking") for item in findings)
    )
    classification = _normalize_failure_classification(failure_classification, state=state)
    # Early gate and malformed-input paths often have no classifier object.
    # Keep the packet envelope useful and stable rather than returning null
    # failure identity fields.  Codes remain Python-owned and bounded; no raw
    # provider or exception text is promoted into the packet.
    classification_code = classification.get("code") if classification else None
    if not classification_code:
        explicit_code = next(
            (
                raw_container.get(key)
                for key in ("failure_code", "reason_code", "error_code", "code")
                if raw_container.get(key) not in (None, "")
            ),
            None,
        )
        explicit_code_text, _ = _ascii_text(explicit_code, MAX_FINDING_CODE_CHARS, state, "failure_code")
        if explicit_code_text and _SAFE_TOKEN_RE.fullmatch(explicit_code_text):
            classification_code = explicit_code_text
    if not classification_code:
        classification_code = next(
            (
                str(item.get("code"))
                for item in findings
                if isinstance(item, Mapping) and item.get("code")
            ),
            "adaptation_gate_blocked" if missing_or_blocked else "adaptation_failure_unclassified",
        )
    classification_stage = (
        (classification or {}).get("stage")
        or (classification or {}).get("failed_stage")
        or raw_container.get("failed_stage")
        or raw_container.get("failure_stage")
        or raw_container.get("stage")
        or stage
        or normalized_attempt.get("stage")
        or "adaptation_gate_composition"
    )
    classification_class = (classification or {}).get("failure_class") or (
        "validation" if missing_or_blocked else "unknown"
    )
    classification_domain = (classification or {}).get("domain") or classification_stage
    monster_packet = None
    if isinstance(monster_content_failure, Mapping):
        monster_packet = build_adaptation_monster_failure_packet(**dict(monster_content_failure))

    packet_status = PACKET_STATUS_BLOCKED if missing_or_blocked else PACKET_STATUS_NOT_NEEDED
    def _bounded_state_names(values: Iterable[Any], limit: int = 64) -> List[str]:
        names: List[str] = []
        for value in sorted(str(item) for item in values)[:limit]:
            text, _ = _ascii_text(value, 160, state, "redactions.field")
            if text:
                names.append(text)
        return names

    packet: Dict[str, Any] = {
        "contract_version": FAILURE_PACKET_CONTRACT_VERSION,
        "packet_kind": FAILURE_PACKET_KIND,
        "packet_status": packet_status,
        "advisory": True,
        "python_authoritative": True,
        "publication_allowed": False,
        "attempt_id": normalized_attempt.get("attempt_id", ""),
        "attempt_number": normalized_attempt.get("attempt_number"),
        "revision_number": normalized_attempt.get("revision_number"),
        "stage": normalized_attempt.get("stage", ""),
        "source_hash": normalized_attempt.get("source_hash", ""),
        "attempt_metadata": normalized_attempt,
        "world_context_provenance": world_provenance,
        "staging_reference": normalized_staging,
        "gate_statuses": statuses,
        "gate_findings": findings,
        "module_summaries": summaries,
        "source_context_refs": context_refs,
        "publication_goals": goals,
        "required_gate_domains": list(REQUIRED_GATE_DOMAINS),
        "module_summary_bounds": summary_bounds,
        "failure_classification": classification,
        "next_revision_eligible": bool(
            classification and classification.get("next_revision_eligible") is True
        ),
        "revision_eligible": bool(
            classification and classification.get("revision_eligible") is True
        ),
        "semantic_revision_eligible": bool(
            classification and classification.get("semantic_revision_eligible") is True
        ),
        "semantic_revision_budget_consumed": bool(
            classification and classification.get("semantic_revision_budget_consumed") is True
        ),
        "revision_budget": deepcopy(
            dict(classification.get("revision_budget") or {})
        ) if classification else {},
        "failure_class": classification_class,
        "failure_code": classification_code,
        "failed_stage": classification_stage,
        "failure_domain": classification_domain,
        "failure_diagnostics": list(classification.get("diagnostics") or [])[:8]
        if classification
        else [],
        "publication_attempted": False,
        "raw_provider_payload_exposed": False,
        "security": {
            "raw_source_included": False,
            "full_prompts_included": False,
            "provider_payloads_included": False,
            "credentials_included": False,
        },
        "bounds": {
            "max_packet_serialized_chars": MAX_PACKET_SERIALIZED_CHARS,
            "max_gate_findings": MAX_GATE_FINDINGS,
            "max_finding_message_chars": MAX_FINDING_MESSAGE_CHARS,
            "max_module_summary_chars": MAX_MODULE_SUMMARY_CHARS,
            "max_module_summaries_chars": MAX_MODULE_SUMMARIES_CHARS,
            "max_source_context_refs": MAX_SOURCE_CONTEXT_REFS,
            "max_publication_goals": MAX_PUBLICATION_GOALS,
            "truncated": bool(state["truncated_sections"]),
            "truncated_sections": sorted(state["truncated_sections"]),
        },
        "redactions": {
            "redacted_fields": _bounded_state_names(state["redacted_fields"]),
            "excluded_fields": _bounded_state_names(state["excluded_fields"]),
        },
        "diagnostics": state["diagnostics"][:MAX_DIAGNOSTICS],
    }
    if monster_packet is not None:
        packet["monster_content_failure"] = monster_packet
    serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PACKET_SERIALIZED_CHARS:
        # A final deterministic fallback retains gate identity and provenance
        # while dropping optional summaries and classification before marking
        # the packet invalid. No source or provider payload is reintroduced.
        packet["module_summaries"] = []
        packet["failure_classification"] = None
        packet["bounds"]["truncated"] = True
        packet["bounds"]["truncated_sections"] = sorted(
            set(packet["bounds"].get("truncated_sections", [])) | {"packet_total"}
        )
        _record_diagnostic(state, "packet_total_truncated", "optional packet sections exceeded the total bound")
        packet["diagnostics"] = state["diagnostics"][:MAX_DIAGNOSTICS]
        serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PACKET_SERIALIZED_CHARS:
        # Keep every domain represented, but shorten verbose diagnostics before
        # dropping any finding. Codes and evidence references remain intact.
        for finding in packet.get("gate_findings", []):
            message = finding.get("message")
            if isinstance(message, str) and len(message) > 240:
                finding["message"] = message[:228].rstrip() + " [truncated]"
                finding["truncated"] = True
        packet["bounds"]["truncated"] = True
        packet["bounds"]["truncated_sections"] = sorted(
            set(packet["bounds"].get("truncated_sections", [])) | {"gate_findings"}
        )
        _record_diagnostic(state, "gate_finding_messages_compacted", "verbose gate messages were compacted to fit the packet bound")
        packet["diagnostics"] = state["diagnostics"][:MAX_DIAGNOSTICS]
        serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PACKET_SERIALIZED_CHARS:
        # A final deterministic cap keeps the first finding for each domain and
        # then retains the remaining findings in source-sorted order.
        findings = packet.get("gate_findings", [])
        selected: List[Dict[str, Any]] = []
        seen_domains = set()
        for finding in findings:
            domain = finding.get("domain")
            if domain not in seen_domains:
                selected.append(finding)
                seen_domains.add(domain)
        for finding in findings:
            if finding in selected:
                continue
            if len(selected) >= 32:
                break
            selected.append(finding)
        packet["gate_findings"] = selected
        packet["bounds"]["truncated_sections"] = sorted(
            set(packet["bounds"].get("truncated_sections", [])) | {"gate_findings"}
        )
        _record_diagnostic(state, "gate_finding_count_compacted", "additional gate findings were omitted to fit the packet bound")
        packet["diagnostics"] = state["diagnostics"][:MAX_DIAGNOSTICS]
        serialized = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PACKET_SERIALIZED_CHARS:
        packet["packet_status"] = PACKET_STATUS_INVALID
        _record_diagnostic(state, "packet_total_limit", "failure packet exceeded its serialized size bound")
        packet["diagnostics"] = state["diagnostics"][:MAX_DIAGNOSTICS]
    return packet


def _validate_reference(
    value: Any,
    *,
    repo_root: Path,
    state: Dict[str, Any],
    field: str,
) -> None:
    if not isinstance(value, Mapping):
        _record_diagnostic(state, "reference_invalid", field + " must be an object")
        return
    if set(value) - {"path", "sha256", "role", "reference_only"}:
        _record_diagnostic(state, "reference_unknown_field", field + " contains an unknown field")
    if value.get("path") is not None:
        _safe_path(value.get("path"), repo_root=repo_root, state=state, field=field + ".path")
    if value.get("sha256") is not None:
        _safe_hash(value.get("sha256"), state, field + ".sha256")
    if value.get("path") in (None, "") and value.get("sha256") in (None, ""):
        _record_diagnostic(state, "reference_empty", field + " has no path or hash")
    if value.get("reference_only") is not True:
        _record_diagnostic(state, "reference_not_reference_only", field + " must be reference_only")


def validate_adaptation_failure_packet(
    packet: Any,
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate the bounded packet contract without provider or file writes."""
    state = _packet_state()
    root = Path(repo_root or _REPO_ROOT).resolve()
    if not isinstance(packet, Mapping):
        return {"valid": False, "status": "invalid", "packet": None, "diagnostics": [_diagnostic("packet_type_invalid", "packet must be an object", state)]}
    value = dict(packet)
    allowed_top = {
        "contract_version",
        "packet_kind",
        "packet_status",
        "advisory",
        "python_authoritative",
        "publication_allowed",
        "attempt_id",
        "attempt_number",
        "revision_number",
        "stage",
        "source_hash",
        "attempt_metadata",
        "world_context_provenance",
        "staging_reference",
        "gate_statuses",
        "gate_findings",
        "module_summaries",
        "source_context_refs",
        "publication_goals",
        "required_gate_domains",
        "module_summary_bounds",
        "failure_classification",
        "next_revision_eligible",
        "revision_eligible",
        "semantic_revision_eligible",
        "semantic_revision_budget_consumed",
        "revision_budget",
        "failure_class",
        "failure_code",
        "failed_stage",
        "failure_domain",
        "failure_diagnostics",
        "publication_attempted",
        "raw_provider_payload_exposed",
        "security",
        "bounds",
        "redactions",
        "diagnostics",
        "monster_content_failure",
    }
    for key in value:
        if key not in allowed_top:
            _record_diagnostic(state, "unknown_packet_field", "unknown packet field: " + str(key))
    if value.get("contract_version") != FAILURE_PACKET_CONTRACT_VERSION:
        _record_diagnostic(state, "contract_version_invalid", "unsupported failure packet contract")
    if value.get("packet_kind") != FAILURE_PACKET_KIND:
        _record_diagnostic(state, "packet_kind_invalid", "unsupported failure packet kind")
    if value.get("packet_status") not in VALID_PACKET_STATUSES:
        _record_diagnostic(state, "packet_status_invalid", "packet status is invalid")
    for key, expected in (("advisory", True), ("python_authoritative", True), ("publication_allowed", False)):
        if value.get(key) is not expected:
            _record_diagnostic(state, "authority_marker_invalid", key + " marker is unsafe")

    world_context_provenance = value.get("world_context_provenance")
    normalized_world_context: Optional[Dict[str, Any]] = None
    if world_context_provenance is not None:
        if not isinstance(world_context_provenance, Mapping):
            _record_diagnostic(state, "world_context_provenance_invalid", "world_context_provenance must be an object")
        else:
            normalized_world = build_world_context_provenance(world_context_provenance)
            if normalized_world != dict(world_context_provenance):
                _record_diagnostic(state, "world_context_provenance_invalid", "world_context_provenance is not canonical")
            else:
                normalized_world_context = normalized_world

    attempt = value.get("attempt_metadata")
    if not isinstance(attempt, Mapping):
        _record_diagnostic(state, "attempt_metadata_missing", "attempt_metadata is required")
    else:
        allowed_attempt = {
            "attempt_id",
            "attempt_number",
            "revision_number",
            "stage",
            "source_hash",
            "source_path",
            "source_title",
            "source_format",
            "job_id",
            "stage_id",
            "world_seed_version",
            "world_seed_hash",
            "world_seed_status",
            "world_context_status",
            "world_context_version",
            "world_context_hash",
            "context_hash",
            "world_context_selected_module",
            "world_context_read_only",
            "source_profile",
            "adaptation_mode",
            "rights_class",
            "rights_basis",
            "rights_review_required",
            "rights_review_status",
            "model_metadata",
            "artifact_refs",
        }
        for key in attempt:
            if key not in allowed_attempt:
                _record_diagnostic(state, "attempt_metadata_unknown_field", "unknown attempt metadata field: " + str(key))
        required = ("attempt_id", "attempt_number", "revision_number", "stage", "source_hash", "source_path", "adaptation_mode")
        required += ("rights_class", "rights_basis", "rights_review_required", "rights_review_status", "model_metadata")
        for key in required:
            if key not in attempt:
                _record_diagnostic(state, "attempt_metadata_missing", "attempt_metadata missing " + key)
        if not isinstance(attempt.get("attempt_id"), str) or not _ATTEMPT_ID_RE.fullmatch(str(attempt.get("attempt_id", ""))):
            _record_diagnostic(state, "attempt_id_invalid", "attempt_id is not path-safe")
        if not isinstance(attempt.get("attempt_number"), int) or isinstance(attempt.get("attempt_number"), bool) or not 1 <= attempt.get("attempt_number", 0) <= 1_000_000:
            _record_diagnostic(state, "attempt_number_invalid", "attempt_number is invalid")
        if not isinstance(attempt.get("revision_number"), int) or isinstance(attempt.get("revision_number"), bool) or not 0 <= attempt.get("revision_number", -1) <= 100:
            _record_diagnostic(state, "revision_number_invalid", "revision_number is invalid")
        if attempt.get("adaptation_mode") != ADAPTATION_MODE_LLM:
            _record_diagnostic(state, "adaptation_mode_invalid", "adaptation mode is not llm_adaptation")
        if attempt.get("rights_class") not in VALID_RIGHTS_CLASSES:
            _record_diagnostic(state, "rights_class_invalid", "rights_class is missing or unsupported")
        if not isinstance(attempt.get("rights_basis"), str) or not attempt.get("rights_basis"):
            _record_diagnostic(state, "rights_basis_required", "rights_basis is required")
        if not isinstance(attempt.get("rights_review_required"), bool):
            _record_diagnostic(state, "rights_review_required_invalid", "rights_review_required must be boolean")
        if attempt.get("rights_review_status") not in VALID_RIGHTS_REVIEW_STATUSES:
            _record_diagnostic(state, "rights_review_status_invalid", "rights_review_status is missing or unsupported")
        _safe_hash(attempt.get("source_hash"), state, "attempt_metadata.source_hash")
        _safe_path(attempt.get("source_path"), repo_root=root, state=state, field="attempt_metadata.source_path")
        if attempt.get("artifact_refs") is not None:
            if not isinstance(attempt.get("artifact_refs"), list):
                _record_diagnostic(state, "artifact_refs_invalid", "attempt artifact_refs must be a list")
            else:
                for index, ref in enumerate(attempt.get("artifact_refs", [])):
                    _validate_reference(ref, repo_root=root, state=state, field=f"attempt_metadata.artifact_refs[{index}]")
        model_metadata = attempt.get("model_metadata")
        if not isinstance(model_metadata, Mapping):
            _record_diagnostic(state, "model_metadata_missing", "attempt model_metadata is required")
        else:
            allowed_model = {
                "provider",
                "model",
                "model_version",
                "request_id",
                "parameter_profile",
                "temperature",
                "reasoning_effort",
                "verbosity",
            }
            for key in model_metadata:
                if key not in allowed_model:
                    _record_diagnostic(state, "model_metadata_unknown_field", "unknown model metadata field: " + str(key))
        if not isinstance(model_metadata.get("model"), str) or not model_metadata.get("model"):
            _record_diagnostic(state, "model_metadata_missing", "model metadata requires a model")
        if normalized_world_context is not None:
            flat_world_fields = {
                "world_seed_status": normalized_world_context.get("world_seed_status"),
                "world_seed_version": normalized_world_context.get("world_seed_version"),
                "world_seed_hash": normalized_world_context.get("world_seed_hash"),
                "world_context_status": normalized_world_context.get("context_status"),
                "world_context_version": normalized_world_context.get("context_version"),
                "world_context_hash": normalized_world_context.get("context_hash"),
                "context_hash": normalized_world_context.get("context_hash"),
                "world_context_selected_module": normalized_world_context.get("selected_module"),
                "world_context_read_only": normalized_world_context.get("read_only"),
            }
            for key, expected in flat_world_fields.items():
                if key in attempt and attempt.get(key) not in (None, expected):
                    _record_diagnostic(state, "world_context_provenance_mismatch", key + " contradicts world_context_provenance")
        for key in ("attempt_id", "attempt_number", "revision_number", "stage", "source_hash"):
            if key in value and value.get(key) != attempt.get(key):
                _record_diagnostic(state, "attempt_metadata_mismatch", "top-level attempt metadata does not match nested metadata")

    staging = value.get("staging_reference")
    if not isinstance(staging, Mapping) or not staging:
        _record_diagnostic(state, "staging_reference_missing", "staging_reference is required")
    elif staging:
        if staging.get("path") is not None:
            _safe_path(staging.get("path"), repo_root=root, state=state, field="staging_reference.path")
        if staging.get("reference_only") is not True:
            _record_diagnostic(state, "staging_reference_not_reference_only", "staging reference must be reference_only")

    statuses = value.get("gate_statuses")
    if not isinstance(statuses, list) or len(statuses) > MAX_GATE_DOMAINS:
        _record_diagnostic(state, "gate_statuses_invalid", "gate_statuses exceeds its bound")
    else:
        for index, item in enumerate(statuses):
            if not isinstance(item, Mapping):
                _record_diagnostic(state, "gate_status_invalid", f"gate_statuses[{index}] must be an object")
                continue
            if item.get("status") not in VALID_GATE_STATUSES:
                _record_diagnostic(state, "gate_status_invalid", f"gate_statuses[{index}].status is invalid")
            if item.get("evidence_ref") is not None:
                _validate_reference(item.get("evidence_ref"), repo_root=root, state=state, field=f"gate_statuses[{index}].evidence_ref")

    findings = value.get("gate_findings")
    if not isinstance(findings, list) or len(findings) > MAX_GATE_FINDINGS:
        _record_diagnostic(state, "gate_findings_invalid", "gate_findings exceeds its bound")
    else:
        for index, item in enumerate(findings):
            if not isinstance(item, Mapping):
                _record_diagnostic(state, "gate_finding_invalid", f"gate_findings[{index}] must be an object")
                continue
            allowed_finding = {
                "domain",
                "status",
                "finding_kind",
                "code",
                "message",
                "origin_field",
                "blocking",
                "truncated",
                "details",
                "evidence_ref",
            }
            for key in item:
                if key not in allowed_finding:
                    _record_diagnostic(state, "gate_finding_unknown_field", f"gate_findings[{index}] contains an unknown field")
            if item.get("status") not in VALID_GATE_STATUSES:
                _record_diagnostic(state, "gate_finding_invalid", f"gate_findings[{index}].status is invalid")
            if item.get("finding_kind") not in VALID_FINDING_KINDS:
                _record_diagnostic(state, "gate_finding_invalid", f"gate_findings[{index}].finding_kind is invalid")
            if not isinstance(item.get("code"), str) or len(item.get("code", "")) > MAX_FINDING_CODE_CHARS:
                _record_diagnostic(state, "gate_finding_invalid", f"gate_findings[{index}].code is invalid")
            if not isinstance(item.get("message"), str) or len(item.get("message", "")) > MAX_FINDING_MESSAGE_CHARS + len(" [truncated]"):
                _record_diagnostic(state, "gate_finding_invalid", f"gate_findings[{index}].message is invalid")
            if item.get("evidence_ref") is not None:
                _validate_reference(item.get("evidence_ref"), repo_root=root, state=state, field=f"gate_findings[{index}].evidence_ref")
            details = item.get("details")
            if details is not None:
                if not isinstance(details, Mapping) or len(details) > 4:
                    _record_diagnostic(state, "gate_finding_details_invalid", f"gate_findings[{index}].details is invalid")
                else:
                    for detail_key, detail_value in details.items():
                        if detail_key not in {"expected", "actual", "field", "severity"} or not isinstance(detail_value, str) or len(detail_value) > MAX_SUMMARY_ITEM_CHARS:
                            _record_diagnostic(state, "gate_finding_details_invalid", f"gate_findings[{index}].details is invalid")

    summaries = value.get("module_summaries")
    if not isinstance(summaries, list) or len(summaries) > MAX_MODULE_SUMMARIES:
        _record_diagnostic(state, "module_summaries_invalid", "module_summaries exceeds its bound")
    else:
        total = 0
        for index, summary in enumerate(summaries):
            if not isinstance(summary, Mapping):
                _record_diagnostic(state, "module_summary_invalid", f"module_summaries[{index}] must be an object")
                continue
            encoded = json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if len(encoded) > MAX_MODULE_SUMMARY_CHARS:
                _record_diagnostic(state, "module_summary_too_large", f"module_summaries[{index}] exceeds its bound")
            total += len(encoded) + 1
            for ref_key in ("report_ref", "report_path"):
                if summary.get(ref_key) is not None:
                    _validate_reference(summary.get(ref_key), repo_root=root, state=state, field=f"module_summaries[{index}].{ref_key}")
        if total > MAX_MODULE_SUMMARIES_CHARS:
            _record_diagnostic(state, "module_summary_total_too_large", "module summaries exceed their total bound")

    refs = value.get("source_context_refs")
    if not isinstance(refs, list) or len(refs) > MAX_SOURCE_CONTEXT_REFS:
        _record_diagnostic(state, "source_context_refs_invalid", "source_context_refs exceeds its bound")
    else:
        for index, ref in enumerate(refs):
            _validate_reference(ref, repo_root=root, state=state, field=f"source_context_refs[{index}]")
            expected_hash = (
                value.get("attempt_metadata", {}).get("source_hash")
                if isinstance(value.get("attempt_metadata"), Mapping)
                else None
            )
            if isinstance(ref, Mapping) and expected_hash and ref.get("sha256") not in (None, expected_hash):
                _record_diagnostic(state, "source_context_hash_mismatch", "source context reference hash does not match attempt source hash")

    goals = value.get("publication_goals")
    if not isinstance(goals, list) or len(goals) > MAX_PUBLICATION_GOALS:
        _record_diagnostic(state, "publication_goals_invalid", "publication_goals exceeds its bound")
    else:
        for goal in goals:
            if goal not in ALLOWED_PUBLICATION_GOALS:
                _record_diagnostic(state, "publication_goal_invalid", "publication goal is not allowlisted")

    security = value.get("security")
    if not isinstance(security, Mapping) or any(security.get(key) is not False for key in (
        "raw_source_included",
        "full_prompts_included",
        "provider_payloads_included",
        "credentials_included",
    )):
        _record_diagnostic(state, "security_marker_invalid", "failure packet security markers are unsafe")

    if value.get("monster_content_failure") is not None:
        monster_validation = validate_adaptation_monster_failure_packet(value.get("monster_content_failure"))
        if not monster_validation.get("valid"):
            _record_diagnostic(state, "monster_content_failure_invalid", "nested monster content failure packet is invalid")

    if value.get("raw_provider_payload_exposed") is not False:
        _record_diagnostic(state, "raw_provider_payload_marker_invalid", "raw provider payload marker must be false")

    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PACKET_SERIALIZED_CHARS:
        _record_diagnostic(state, "packet_total_limit", "failure packet exceeds its serialized size bound")

    # Detect injected forbidden keys without inspecting or copying their values.
    def scan_keys(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key).lower()
                if key_text in _FORBIDDEN_KEYS:
                    _record_diagnostic(state, "forbidden_field_present", path + "." + str(key))
                scan_keys(child, path + "." + str(key))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                scan_keys(child, f"{path}[{index}]")

    scan_keys(value)
    diagnostics = state["diagnostics"][:MAX_DIAGNOSTICS]
    valid = not diagnostics
    return {
        "valid": valid,
        "status": "valid" if valid else "invalid",
        "packet": deepcopy(value) if valid else None,
        "diagnostics": diagnostics,
    }


def serialize_adaptation_failure_packet(packet: Mapping[str, Any]) -> str:
    """Return deterministic compact JSON after validating the packet."""
    result = validate_adaptation_failure_packet(packet)
    if not result.get("valid"):
        first = (result.get("diagnostics") or [{}])[0]
        raise ValueError(str(first.get("message") or "invalid adaptation failure packet"))
    return json.dumps(result["packet"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))


build_failure_packet = build_adaptation_failure_packet
validate_failure_packet = validate_adaptation_failure_packet
serialize_failure_packet = serialize_adaptation_failure_packet


__all__ = [
    "ALLOWED_PUBLICATION_GOALS",
    "DEFAULT_PUBLICATION_GOALS",
    "FAILURE_PACKET_CONTRACT_VERSION",
    "FAILURE_PACKET_KIND",
    "MONSTER_FAILURE_PACKET_CONTRACT_VERSION",
    "MAX_FINDING_MESSAGE_CHARS",
    "MAX_GATE_FINDINGS",
    "MAX_MODULE_SUMMARIES_CHARS",
    "MAX_MODULE_SUMMARY_CHARS",
    "MAX_PACKET_SERIALIZED_CHARS",
    "MAX_PUBLICATION_GOALS",
    "MAX_SOURCE_CONTEXT_REFS",
    "PACKET_STATUS_BLOCKED",
    "PACKET_STATUS_INVALID",
    "PACKET_STATUS_NOT_NEEDED",
    "build_adaptation_failure_packet",
    "build_adaptation_monster_failure_packet",
    "build_failure_packet",
    "serialize_adaptation_failure_packet",
    "serialize_adaptation_monster_failure_packet",
    "serialize_failure_packet",
    "persist_adaptation_monster_failure_packet",
    "validate_adaptation_failure_packet",
    "validate_adaptation_monster_failure_packet",
    "validate_failure_packet",
]
