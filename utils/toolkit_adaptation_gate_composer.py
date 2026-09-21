# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Gate Composer
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free composition of the deterministic gates used by the staged LLM
adaptation lane. The composer validates an explicit staging target, invokes
existing Python-owned validators, and returns a bounded candidate result. It
never registers, publishes, or mutates campaign/runtime state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from scripts.audit_module_readiness import (
    _safe_json_load as _readiness_safe_json_load,
    _extract_gameplay_payload,
    _maybe_relax_toolkit_media_only_gameplay_gate,
    evaluate_continuity_gate,
    evaluate_gameplay_gate,
    evaluate_schema_gate,
)
from scripts.module_continuity_audit import audit_module_continuity
from scripts.module_semantic_authority_audit import audit_module_semantic_authority
from scripts.module_semantic_probe_harness import run_module_semantic_probes
from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_publication_convergence import (
    validate_adaptation_finalization_proposal,
)
from utils.module_semantic_authority import enrich_module_semantic_authority
from utils.monster_reference_closure import (
    collect_existing_monster_slugs,
    collect_referenced_monsters,
)
from utils.toolkit_adaptation_failure_classifier import classify_adaptation_failure
from utils.toolkit_adaptation_source_fidelity import (
    ADAPTATION_MODE_LLM,
    ADAPTATION_SOURCE_FIDELITY_STATUS,
    evaluate_adaptation_source_fidelity,
)
from utils.toolkit_adaptation_staging import (
    validate_adaptation_staging_target,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_report_agreement import (
    _derive_validation_status,
    compose_adaptation_report_agreement,
    compose_report_agreement,
)


ADAPTATION_GATE_COMPOSITION_CONTRACT_VERSION = (
    "toolkit_adaptation_gate_composition.v1"
)

GATE_SCHEMA = "schema"
GATE_READINESS = "readiness"
GATE_MECHANICAL_CLOSURE = "mechanical_closure"
GATE_SEMANTIC_AUTHORITY = "semantic_authority"
GATE_SEMANTIC_PROBES = "semantic_probes"
GATE_REPORT_AGREEMENT = "report_agreement"
REQUIRED_GATE_DOMAINS = (
    GATE_SCHEMA,
    GATE_READINESS,
    GATE_MECHANICAL_CLOSURE,
    GATE_SEMANTIC_AUTHORITY,
    GATE_SEMANTIC_PROBES,
    GATE_REPORT_AGREEMENT,
)

GATE_STATUS_PASS = "pass"
GATE_STATUS_DEGRADED = "degraded"
GATE_STATUS_BLOCKED = "blocked"
GATE_STATUS_UNKNOWN = "unknown"

MAX_FINDINGS = 20
MAX_TEXT_CHARS = 320
MAX_PROVENANCE_TEXT_CHARS = 160
MAX_UNRESOLVED_SLUGS = 20
GATE_COMMAND_TIMEOUT_SECONDS = 120


class AdaptationGateCompositionError(ValueError):
    """Raised when a staged adaptation gate request is unsafe."""


def _utc_now_iso() -> str:
    """Return an ASCII UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ascii_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Return bounded, whitespace-normalized ASCII text."""
    if value is None:
        return ""
    text = str(value).replace("\x00", " ")
    text = " ".join(text.split()).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _bounded_items(values: Any, *, limit: int = MAX_FINDINGS) -> List[str]:
    """Extract bounded diagnostic strings without retaining raw payloads."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    if not isinstance(values, Sequence):
        values = [values]

    output: List[str] = []
    seen = set()
    for value in list(values)[:limit]:
        if isinstance(value, Mapping):
            value = (
                value.get("message")
                or value.get("reason")
                or value.get("error")
                or value.get("detail")
                or value.get("code")
            )
        text = _ascii_text(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _status_token(value: Any) -> str:
    """Normalize a gate status without treating unknown values as pass."""
    token = str(value or "").strip().lower()
    if token in {"pass", "success", "ok", "ready", "complete", "completed"}:
        return GATE_STATUS_PASS
    if token in {"degraded", "warning", "warn", "partial", "skipped"}:
        return GATE_STATUS_DEGRADED
    if token in {"blocked", "fail", "failed", "error", "invalid"}:
        return GATE_STATUS_BLOCKED
    return GATE_STATUS_UNKNOWN


def _normalize_gate_result(domain: str, report: Any) -> Dict[str, Any]:
    """Normalize one existing Python gate result to a bounded gate envelope."""
    if not isinstance(report, Mapping):
        return {
            "domain": domain,
            "status": GATE_STATUS_BLOCKED,
            "effective_status": GATE_STATUS_BLOCKED,
            "errors": [f"{domain}_result_missing_or_invalid"],
            "blockers": [f"{domain}_result_missing_or_invalid"],
            "warnings": [],
            "blocking": True,
        }

    raw_status = report.get("status")
    if raw_status is None and report.get("overall_status") is not None:
        raw_status = report.get("overall_status")
    status = _status_token(raw_status)

    errors = _bounded_items(report.get("errors"))
    blockers = _bounded_items(report.get("blockers"))
    blockers.extend(_bounded_items(report.get("blocking_errors")))
    blockers = _bounded_items(blockers)
    warnings = _bounded_items(report.get("warnings"))
    manual_handoff_reason = "toolkit_structural_media_handoff_only"
    debt_count = report.get("structural_media_debt_count")
    debt_slugs = report.get("structural_media_debt_slugs")
    bounded_debt_slugs = (
        _bounded_items(debt_slugs, limit=MAX_UNRESOLVED_SLUGS)
        if isinstance(debt_slugs, list)
        else []
    )
    valid_debt_metadata = (
        isinstance(debt_count, int)
        and not isinstance(debt_count, bool)
        and 0 < debt_count <= MAX_UNRESOLVED_SLUGS
        and isinstance(debt_slugs, list)
        and len(bounded_debt_slugs) == debt_count
        and len(set(bounded_debt_slugs)) == debt_count
    )
    manual_handoff_only = (
        report.get("status") == GATE_STATUS_PASS
        and report.get("manual_handoff_only") is True
        and report.get("reason") == manual_handoff_reason
        and valid_debt_metadata
    )
    playable_publication_status = report.get("playable_publication_status")
    if playable_publication_status is None and isinstance(report.get("agreement"), Mapping):
        playable_publication_status = report["agreement"].get(
            "playable_publication_status"
        )

    if status == GATE_STATUS_UNKNOWN:
        errors.append(f"{domain}_status_unknown")
        blockers.append(f"{domain}_status_unknown")
        status = GATE_STATUS_BLOCKED
    raw_exit_code = report.get("exit_code")
    if errors or blockers or raw_exit_code not in (None, 0):
        if raw_exit_code not in (None, 0) and not manual_handoff_only:
            blockers.append(f"{domain}_exit_code_{report.get('exit_code')}")
        if errors or blockers or not manual_handoff_only:
            status = GATE_STATUS_BLOCKED

    # Report agreement may carry informational missing-legacy-report warnings
    # on a fresh adaptation staging target.  Its explicit playable contract is
    # authoritative; warnings must remain visible without turning an otherwise
    # passing adaptation gate into a false structural failure.
    if (
        domain == GATE_REPORT_AGREEMENT
        and not errors
        and not blockers
        and _status_token(playable_publication_status) == GATE_STATUS_PASS
    ):
        status = GATE_STATUS_PASS

    errors = _bounded_items(errors)
    blockers = _bounded_items(blockers)
    blocking = bool(errors or blockers or status == GATE_STATUS_BLOCKED)
    # A warning/degraded gate is not equivalent to a passing gate.  Keep the
    # diagnostic non-blocking, but preserve its degraded status so the
    # adaptation status composer cannot claim a playable candidate from a
    # partial result.
    effective_status = (
        GATE_STATUS_BLOCKED
        if blocking
        else GATE_STATUS_DEGRADED
        if status == GATE_STATUS_DEGRADED
        else GATE_STATUS_PASS
    )

    normalized: Dict[str, Any] = {
        "domain": domain,
        "status": status,
        "effective_status": effective_status,
        "errors": errors,
        "blockers": blockers,
        "warnings": warnings,
        "blocking": blocking,
    }
    if playable_publication_status is not None:
        normalized["playable_publication_status"] = _status_token(
            playable_publication_status
        )
    for key in ("reason", "stage", "source", "module_path", "report_path"):
        if report.get(key) not in (None, ""):
            normalized[key] = _ascii_text(
                report.get(key), MAX_PROVENANCE_TEXT_CHARS
            )
    if report.get("exit_code") is not None:
        normalized["exit_code"] = report.get("exit_code")
    if manual_handoff_only:
        normalized["manual_handoff_only"] = True
        normalized["structural_media_debt_count"] = debt_count
        normalized["structural_media_debt_slugs"] = bounded_debt_slugs
    return normalized


def _safe_relative_path(path: Path, repo_root: Path) -> str:
    """Return a project-relative path or an empty value."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return ""


def _validated_staging_context(
    staging_target: Mapping[str, Any],
    module_dir: Optional[Path],
    repo_root: Path,
) -> Tuple[Dict[str, Any], Path, str]:
    """Validate the exact target and reject non-staged module paths."""
    target = validate_adaptation_staging_target(
        staging_target,
        repo_root=repo_root,
        require_reserved=False,
    )
    target_path = (repo_root / str(target["path"])).resolve()
    candidate = target_path if module_dir is None else Path(module_dir)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve()
    if candidate != target_path:
        raise AdaptationGateCompositionError(
            "module_dir must equal the validated adaptation staging target"
        )
    if not candidate.is_dir() or candidate.is_symlink():
        raise AdaptationGateCompositionError(
            "adaptation staging target is not a real directory"
        )
    module_slug = str(target.get("module_slug") or candidate.name).strip()
    if not module_slug:
        raise AdaptationGateCompositionError("staging module_slug is missing")
    return target, candidate, module_slug


def _parse_command_json(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse a bounded gate command response using the existing readiness parser."""
    return _readiness_safe_json_load(stdout)


def _run_command(command: List[str], *, cwd: Path) -> Dict[str, Any]:
    """Run a deterministic local validator with a bounded timeout."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GATE_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "json": _parse_command_json(completed.stdout),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 124,
            "stdout": "",
            "stderr": "gate command timed out",
            "json": None,
        }
    except Exception as exc:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": _ascii_text(exc),
            "json": None,
        }


def _run_schema_gate(module_dir: Path, repo_root: Path) -> Dict[str, Any]:
    """Reuse the canonical schema validator against the explicit staging path."""
    command = [
        sys.executable,
        str(repo_root / "core" / "validation" / "validate_module_files.py"),
        "--module-path",
        str(module_dir),
        "--json",
    ]
    raw = _run_command(command, cwd=repo_root)
    return evaluate_schema_gate(raw)


def _run_gameplay_gate(
    module_dir: Path,
    repo_root: Path,
    module_slug: Optional[str] = None,
) -> Dict[str, Any]:
    """Reuse the gameplay audit in an isolated temporary module view.

    The legacy gameplay CLI accepts a module slug rather than a module path.
    A temporary ``modules/<slug>`` view therefore points at the explicit
    staging directory without creating or changing any repository module.
    """
    scratch_root = repo_root / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="adaptation-gate-", dir=str(scratch_root)
    ) as isolated_name:
        isolated_root = Path(isolated_name)
        modules_root = isolated_root / "modules"
        modules_root.mkdir()
        isolated_module_slug = str(module_slug or module_dir.name).strip()
        module_link = modules_root / isolated_module_slug
        try:
            os.symlink(str(module_dir), str(module_link), target_is_directory=True)
        except OSError:
            shutil.copytree(module_dir, module_link)

        schemas_link = isolated_root / "schemas"
        try:
            os.symlink(
                str(repo_root / "schemas"), str(schemas_link), target_is_directory=True
            )
        except OSError:
            shutil.copytree(repo_root / "schemas", schemas_link)

        command = [
            sys.executable,
            str(repo_root / "scripts" / "audit_module_gameplay.py"),
            "--module",
            isolated_module_slug,
            "--json",
            "--strict-instructions",
        ]
        raw = _run_command(command, cwd=isolated_root)
        return evaluate_gameplay_gate(raw)


def _run_continuity_gate(module_dir: Path) -> Dict[str, Any]:
    """Reuse the strict continuity audit without writing a report artifact."""
    try:
        report = audit_module_continuity(module_dir, strict=True)
        if report.get("exit_code") == 0 and not report.get("blocking_errors"):
            # Empty cross-module references and similar advisory findings are
            # retained as warnings, but do not convert an otherwise passing
            # strict continuity audit into a blocked adaptation candidate.
            report["status"] = GATE_STATUS_PASS
        return report
    except Exception as exc:
        return {
            "status": GATE_STATUS_BLOCKED,
            "errors": [f"continuity_audit_exception:{exc}"],
            "blocking_errors": [f"continuity_audit_exception:{exc}"],
            "warnings": [],
        }


def _run_mechanical_closure_gate(
    module_dir: Path,
    build_result: Optional[Mapping[str, Any]],
    gameplay_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Reuse monster closure collectors and combine them with gameplay integrity."""
    errors: List[str] = []
    warnings: List[str] = []
    try:
        referenced = collect_referenced_monsters(str(module_dir))
        existing = collect_existing_monster_slugs(str(module_dir))
        unresolved = sorted(set(referenced) - set(existing))
    except Exception as exc:
        return {
            "status": GATE_STATUS_BLOCKED,
            "errors": [f"mechanical_closure_scan_exception:{exc}"],
            "blockers": [f"mechanical_closure_scan_exception:{exc}"],
            "warnings": [],
        }

    closure = build_result.get("monster_closure") if isinstance(build_result, Mapping) else None
    if isinstance(closure, Mapping):
        try:
            closure_unresolved = int(closure.get("unresolved", 0) or 0)
        except (TypeError, ValueError):
            closure_unresolved = 1
        if closure_unresolved > 0:
            errors.append(f"monster_reference_closure_unresolved:{closure_unresolved}")
        for slug in closure.get("ambiguous_npc_like", []) or []:
            text = _ascii_text(slug, MAX_PROVENANCE_TEXT_CHARS)
            if text:
                warnings.append(f"ambiguous_npc_like_monster_reference:{text}")

    if unresolved:
        errors.append(
            "monster_reference_closure_unresolved_slugs:"
            + ",".join(unresolved[:MAX_UNRESOLVED_SLUGS])
        )

    gameplay_blockers = _bounded_items(gameplay_report.get("blocking_errors"))
    if gameplay_blockers:
        errors.append("gameplay_integrity_blockers_present")

    status = GATE_STATUS_BLOCKED if errors else (
        GATE_STATUS_DEGRADED if warnings else GATE_STATUS_PASS
    )
    return {
        "status": status,
        "errors": errors,
        "blockers": errors,
        "warnings": warnings,
        "referenced_count": len(referenced),
        "existing_count": len(existing),
        "unresolved_count": len(unresolved),
        "unresolved_slugs": unresolved[:MAX_UNRESOLVED_SLUGS],
    }


def _run_semantic_authority_gate(
    module_slug: str,
    module_dir: Path,
    convergence_result: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive and audit semantic authority in the staged candidate only."""
    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"
    module_context = safe_read_json(str(context_path))
    module_plot = safe_read_json(str(plot_path))
    if not isinstance(module_context, dict) or not isinstance(module_plot, dict):
        return {
            "status": GATE_STATUS_BLOCKED,
            "errors": ["semantic_authority_context_or_plot_missing_or_invalid"],
            "blockers": ["semantic_authority_context_or_plot_missing_or_invalid"],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []
    convergence_alias_applied = False
    try:
        existing_authority = (
            dict(module_context.get("semantic_authority"))
            if isinstance(module_context.get("semantic_authority"), Mapping)
            else {}
        )
        enrichment = enrich_module_semantic_authority(
            module_slug=module_slug,
            module_context=module_context,
            module_plot=module_plot,
            module_dir=module_dir,
        )
        errors.extend(_bounded_items(enrichment.get("errors")))
        warnings.extend(_bounded_items(enrichment.get("warnings")))
        if enrichment.get("status") == "failed":
            errors.append("semantic_authority_enrichment_failed")
        if enrichment.get("changed"):
            enriched_context = enrichment.get("module_context")
            if not isinstance(enriched_context, dict) or not safe_write_json(
                str(context_path), enriched_context
            ):
                errors.append("semantic_authority_persistence_failed")

        if isinstance(convergence_result, Mapping):
            metadata = safe_read_json(str(module_dir / "staging_metadata.json"))
            current_identity = {
                "attempt_id": metadata.get("attempt_id") if isinstance(metadata, Mapping) else None,
                "attempt_number": metadata.get("attempt_number") if isinstance(metadata, Mapping) else None,
                "revision_number": metadata.get("revision_number") if isinstance(metadata, Mapping) else None,
                "source_hash": metadata.get("source_hash") if isinstance(metadata, Mapping) else None,
            }
            convergence_identity = {key: convergence_result.get(key) for key in current_identity}
            operation = convergence_result.get("accepted_operation")
            deterministic_noop = (
                operation is None
                and convergence_result.get("reason_code")
                in {"no_repairable_blocker", "callback_success"}
            )
            if convergence_result.get("status") != "ready" or convergence_identity != current_identity:
                errors.append("adaptation_convergence_operation_identity_stale_or_mismatched")
            elif deterministic_noop:
                warnings.append(
                    "adaptation_convergence_deterministic_noop_accepted"
                )
            elif not isinstance(operation, Mapping):
                errors.append("adaptation_convergence_accepted_operation_missing")
            else:
                authority = module_context.get("semantic_authority")
                if not isinstance(authority, dict):
                    errors.append("semantic_authority_payload_missing_for_convergence_operation")
                else:
                    for preserved_key in ("source_evidence", "adaptation_provenance"):
                        if preserved_key in existing_authority and preserved_key not in authority:
                            authority[preserved_key] = existing_authority[preserved_key]
                    authority["attempt"] = dict(current_identity)
                    source_refs = set()
                    for row in authority.get("source_evidence", []):
                        if isinstance(row, Mapping):
                            for key in ("source", "source_ref"):
                                if isinstance(row.get(key), str) and row.get(key).strip():
                                    source_refs.add(row[key].strip())
                    canonical_ids = {
                        str(candidate)
                        for row in authority.get("location_aliases", {}).values()
                        if isinstance(row, Mapping)
                        for candidate in row.get("candidate_location_ids", [])
                    }
                    canonical_ids.update(
                        str(row.get("location_id"))
                        for row in authority.get("destination_phrases", {}).values()
                        if isinstance(row, Mapping) and row.get("location_id")
                    )
                    topology = operation.get("topology")
                    validated = validate_adaptation_finalization_proposal(
                        operation,
                        current_identity=current_identity,
                        source_reference_ids=sorted(source_refs),
                        canonical_location_ids=sorted(canonical_ids),
                        topology=topology,
                        authored_target_ids=(),
                        approved_monster_ids=(),
                    )
                    if not validated.get("valid"):
                        errors.extend(
                            "adaptation_convergence_operation_rejected:" + str(item.get("code"))
                            for item in validated.get("diagnostics", [])[:MAX_FINDINGS]
                        )
                    else:
                        # Convergence already performed the single atomic
                        # staging write.  Gate composition must consume that
                        # post-application artifact, never apply the provider
                        # operation a second time or write stale authority.
                        current_context = safe_read_json(str(context_path))
                        current_authority = (
                            current_context.get("semantic_authority")
                            if isinstance(current_context, Mapping)
                            else None
                        )
                        target = validated["operation"].get("target", {})
                        phrase = target.get("phrase") if isinstance(target, Mapping) else None
                        destination = (
                            current_authority.get("destination_phrases", {}).get(phrase)
                            if isinstance(current_authority, Mapping)
                            and isinstance(current_authority.get("destination_phrases"), Mapping)
                            else None
                        )
                        if not isinstance(destination, Mapping) or destination.get("location_id") != target.get("location_id"):
                            errors.append("adaptation_convergence_post_application_artifact_missing")
                        else:
                            convergence_alias_applied = True
    except Exception as exc:
        errors.append(f"semantic_authority_enrichment_exception:{exc}")

    try:
        audit = audit_module_semantic_authority(module_dir)
        errors.extend(_bounded_items(audit.get("blocking_errors")))
        warnings.extend(_bounded_items(audit.get("warnings")))
    except Exception as exc:
        errors.append(f"semantic_authority_audit_exception:{exc}")

    if convergence_alias_applied:
        current_context = safe_read_json(str(context_path))
        current_authority = current_context.get("semantic_authority", {}) if isinstance(current_context, Mapping) else {}
        diagnostics = current_authority.get("diagnostics", {}) if isinstance(current_authority, Mapping) else {}
        if not diagnostics.get("ambiguous_destination_phrases"):
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith("semantic_authority_ambiguous_destination_phrases=")
            ]

    errors = _bounded_items(errors)
    warnings = _bounded_items(warnings)
    # Deterministic informational normalization/provenance warnings remain in
    # the report but do not make the semantic gate non-playable. Any actual
    # enrichment error or audit blocker remains fail-closed above.
    status = GATE_STATUS_BLOCKED if errors else GATE_STATUS_PASS
    return {
        "status": status,
        "errors": errors,
        "blockers": errors,
        "warnings": warnings,
    }


def _run_semantic_probe_gate(module_dir: Path) -> Dict[str, Any]:
    """Reuse the deterministic semantic probe harness against the staging path."""
    try:
        report = run_module_semantic_probes(module_dir)
        if not isinstance(report, dict):
            return {
                "status": GATE_STATUS_BLOCKED,
                "errors": ["semantic_probe_result_invalid"],
                "blocking_errors": ["semantic_probe_result_invalid"],
                "warnings": [],
            }
        errors = report.get("errors") or []
        blocking_errors = report.get("blocking_errors") or []
        status = str(report.get("status", "")).strip().lower()
        exit_code = report.get("exit_code")
        if exit_code == 0 and not errors and not blocking_errors and status in {"pass", "degraded", "success"}:
            # Fixture debt is retained for operators, but a zero-exit probe
            # run with no blocking findings is a passing adaptation gate.
            report["status"] = GATE_STATUS_PASS
        else:
            report["status"] = GATE_STATUS_BLOCKED
        return report
    except Exception as exc:
        return {
            "status": GATE_STATUS_BLOCKED,
            "errors": [f"semantic_probe_exception:{exc}"],
            "blocking_errors": [f"semantic_probe_exception:{exc}"],
            "warnings": [],
        }


def _load_optional_report(path: Path, label: str) -> Dict[str, Any]:
    """Load a staged report while distinguishing missing and malformed files."""
    if not path.exists():
        return {
            "label": label,
            "state": "missing_optional",
            "status": "not_available",
        }
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {
            "label": label,
            "state": "malformed",
            "status": GATE_STATUS_BLOCKED,
            "errors": [f"{label}_report_malformed:{exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "label": label,
            "state": "malformed",
            "status": GATE_STATUS_BLOCKED,
            "errors": [f"{label}_report_root_not_object"],
        }
    return {"label": label, "state": "present", "payload": payload}


def _report_freshness_state(payload: Mapping[str, Any]) -> str:
    """Apply the existing report-agreement legacy freshness convention."""
    freshness = payload.get("report_freshness", payload.get("freshness", {}))
    if isinstance(freshness, Mapping):
        state = str(
            freshness.get("state", freshness.get("freshness_state", "unknown"))
            or "unknown"
        ).strip().lower()
    else:
        state = str(freshness or "unknown").strip().lower()
    if state in {"current", "authoritative", "degraded", "stale"}:
        return state
    direct = str(payload.get("freshness_state", "") or "").strip().lower()
    if direct in {"current", "authoritative", "degraded", "stale"}:
        return direct
    return "current"


def _is_module_builder_context_validation_report(payload: Any) -> bool:
    """Identify ModuleBuilder's context report, not a schema result.

    ModuleBuilder writes ``validation_report.json`` as a context-consistency
    summary with ``validation_date``, ``issues``, and ``context_summary``.
    It deliberately has no schema-validator status.  The adaptation lane must
    not infer schema validity from an empty ``issues`` list; its subprocess
    schema gate remains authoritative.  Requiring the complete known shape
    keeps unknown or malformed reports fail-closed.
    """
    if not isinstance(payload, Mapping):
        return False
    if any(key in payload for key in ("status", "overall_status", "summary")):
        return False
    return (
        isinstance(payload.get("validation_date"), str)
        and bool(payload.get("validation_date", "").strip())
        and isinstance(payload.get("issues"), list)
        and isinstance(payload.get("context_summary"), Mapping)
    )


def _explicit_report_freshness_state(payload: Mapping[str, Any]) -> Optional[str]:
    """Return an explicitly supplied freshness token, if present."""
    freshness = payload.get("report_freshness", payload.get("freshness"))
    if isinstance(freshness, Mapping):
        return str(
            freshness.get("state", freshness.get("freshness_state", "unknown"))
            or "unknown"
        ).strip().lower()
    if freshness is not None:
        return str(freshness or "unknown").strip().lower()
    if "freshness_state" in payload:
        return str(payload.get("freshness_state") or "unknown").strip().lower()
    return None


def _run_report_agreement_gate(
    module_dir: Path,
    gate_reports: Mapping[str, Mapping[str, Any]],
    *,
    source_fidelity_status: Optional[str],
    build_result: Optional[Mapping[str, Any]],
    attempt_metadata: Optional[Mapping[str, Any]],
    staging_target: Optional[Mapping[str, Any]],
    module_slug: str,
    attempt_report: Any = None,
) -> Dict[str, Any]:
    """Compose report agreement from current gates and optional staged reports."""
    legacy_reports = {
        label: _load_optional_report(module_dir / filename, label)
        for label, filename in (
            ("validation", "validation_report.json"),
            ("toolkit_build", "toolkit_build_report.json"),
            ("source_fidelity", "source_fidelity_report.json"),
        )
    }
    report_blockers: List[str] = []
    report_warnings: List[str] = []
    freshness_states: Dict[str, str] = {}

    source_report = legacy_reports["source_fidelity"]
    source_evidence = (
        source_report.get("payload")
        if source_report.get("state") == "present"
        else source_fidelity_status
    )
    evidence_state = source_report.get("state")
    if evidence_state == "missing_optional" and source_fidelity_status is not None:
        evidence_state = "provided"
    build_fidelity_evidence = None
    if isinstance(build_result, Mapping):
        build_fidelity_evidence = build_result.get("build_fidelity")
    adaptation_fidelity = evaluate_adaptation_source_fidelity(
        source_fidelity_evidence=source_evidence,
        literal_mismatch_evidence=build_fidelity_evidence,
        evidence_state=evidence_state,
        evidence_errors=source_report.get("errors"),
        attempt_metadata=attempt_metadata,
        staging_target=staging_target,
        module_slug=module_slug,
    )
    adaptation_fidelity_report = adaptation_fidelity["report"]
    report_blockers.extend(
        _bounded_items(adaptation_fidelity.get("blockers"))
    )
    if source_report.get("state") == "present":
        evidence_freshness = adaptation_fidelity_report.get("evidence", {}).get(
            "freshness_state", "unknown"
        )
        freshness_states["source_fidelity"] = (
            "stale" if evidence_freshness == "stale" else "current"
        )
    elif source_report.get("state") == "malformed":
        freshness_states["source_fidelity"] = "stale"

    validation_status = (
        GATE_STATUS_PASS
        if _normalize_gate_result(GATE_SCHEMA, gate_reports.get(GATE_SCHEMA)).get(
            "effective_status"
        )
        == GATE_STATUS_PASS
        else GATE_STATUS_BLOCKED
    )
    ready_status = (
        GATE_STATUS_PASS
        if _normalize_gate_result(GATE_READINESS, gate_reports.get(GATE_READINESS)).get(
            "effective_status"
        )
        == GATE_STATUS_PASS
        else GATE_STATUS_BLOCKED
    )
    core_publishable = all(
        _normalize_gate_result(domain, gate_reports.get(domain)).get(
            "effective_status"
        )
        == GATE_STATUS_PASS
        for domain in (
            GATE_MECHANICAL_CLOSURE,
            GATE_SEMANTIC_AUTHORITY,
            GATE_SEMANTIC_PROBES,
        )
    )
    publishable_status = GATE_STATUS_PASS if core_publishable else GATE_STATUS_BLOCKED
    effective_publishable_status = publishable_status
    toolkit_top_level_status = (
        GATE_STATUS_PASS
        if validation_status == GATE_STATUS_PASS
        and ready_status == GATE_STATUS_PASS
        and core_publishable
        else GATE_STATUS_BLOCKED
    )

    validation_report = legacy_reports["validation"]
    if validation_report["state"] == "missing_optional":
        report_warnings.append("optional_legacy_report_missing:validation")
    elif validation_report["state"] == "malformed":
        report_blockers.extend(_bounded_items(validation_report.get("errors")))
        validation_status = GATE_STATUS_BLOCKED
    else:
        payload = validation_report["payload"]
        if _is_module_builder_context_validation_report(payload):
            # This is an informational ModuleBuilder context artifact, not
            # the canonical schema-validator report.  Do not let its missing
            # status fields contradict the authoritative schema subprocess.
            # Explicit stale metadata still fails closed because freshness is
            # a hard artifact contract even for non-authoritative reports.
            explicit_freshness_state = _explicit_report_freshness_state(payload)
            explicit_freshness = any(
                key in payload for key in ("report_freshness", "freshness", "freshness_state")
            )
            if explicit_freshness and explicit_freshness_state not in {
                "current", "authoritative", "degraded"
            }:
                freshness_states["validation"] = explicit_freshness_state or "unknown"
                report_blockers.append(
                    "stale_report:validation:" + (explicit_freshness_state or "unknown")
                )
            else:
                report_warnings.append(
                    "non_authoritative_validation_context_report_ignored"
                )
        else:
            freshness_states["validation"] = _report_freshness_state(payload)
            explicit_freshness_state = _explicit_report_freshness_state(payload)
            if explicit_freshness_state is not None and explicit_freshness_state not in {
                "current", "authoritative", "degraded"
            }:
                freshness_states["validation"] = explicit_freshness_state
                report_blockers.append(
                    "stale_report:validation:" + explicit_freshness_state
                )
            report_status = _derive_validation_status(payload)
            if report_status != GATE_STATUS_PASS:
                report_blockers.append("authoritative_validation_report_not_passing")
                validation_status = GATE_STATUS_BLOCKED

    toolkit_report = legacy_reports["toolkit_build"]
    if toolkit_report["state"] == "missing_optional":
        report_warnings.append("optional_legacy_report_missing:toolkit_build")
    elif toolkit_report["state"] == "malformed":
        report_blockers.extend(_bounded_items(toolkit_report.get("errors")))
        toolkit_top_level_status = GATE_STATUS_BLOCKED
    else:
        payload = toolkit_report["payload"]
        freshness_states["toolkit_build"] = _report_freshness_state(payload)
        if _status_token(payload.get("status")) == GATE_STATUS_BLOCKED:
            report_blockers.append("authoritative_toolkit_build_report_not_passing")
            toolkit_top_level_status = GATE_STATUS_BLOCKED
        if _status_token(payload.get("ready_status")) == GATE_STATUS_BLOCKED:
            ready_status = GATE_STATUS_BLOCKED
        if _status_token(payload.get("publishable_status")) == GATE_STATUS_BLOCKED:
            publishable_status = GATE_STATUS_BLOCKED
            effective_publishable_status = GATE_STATUS_BLOCKED

    resolved_source_fidelity = ADAPTATION_SOURCE_FIDELITY_STATUS
    if source_report["state"] == "missing_optional":
        report_warnings.append("optional_legacy_report_missing:source_fidelity_evidence")

    agreement = compose_report_agreement(
        source_fidelity_status=resolved_source_fidelity,
        validation_status=validation_status,
        ready_status=ready_status,
        publishable_status=publishable_status,
        effective_publishable_status=effective_publishable_status,
        toolkit_top_level_status=toolkit_top_level_status,
        source_fidelity_mode=ADAPTATION_MODE_LLM,
        report_freshness_states=freshness_states or None,
    )
    adaptation_report_agreement = None
    if attempt_report is not None:
        adaptation_report_agreement = compose_adaptation_report_agreement(
            attempt_report,
            expected_attempt_id=(attempt_metadata or {}).get("attempt_id")
            if isinstance(attempt_metadata, Mapping)
            else staging_target.get("attempt_id") if isinstance(staging_target, Mapping) else None,
            expected_source_hash=(attempt_metadata or {}).get("source_hash")
            if isinstance(attempt_metadata, Mapping)
            else staging_target.get("source_hash") if isinstance(staging_target, Mapping) else None,
            expected_revision_number=(attempt_metadata or {}).get("revision_number")
            if isinstance(attempt_metadata, Mapping)
            else staging_target.get("revision_number") if isinstance(staging_target, Mapping) else None,
        )
        if adaptation_report_agreement.get("status") != GATE_STATUS_PASS:
            report_blockers.extend(
                _bounded_items(adaptation_report_agreement.get("blockers"))
            )
        report_warnings.extend(
            _bounded_items(adaptation_report_agreement.get("diagnostics"))
        )
    report_blockers.extend(_bounded_items(agreement.get("blockers")))
    report_warnings.extend(_bounded_items(agreement.get("diagnostics")))

    if agreement.get("playable_publication_status") != GATE_STATUS_PASS:
        report_blockers.append(
            "report_agreement_playable_status:"
            + _ascii_text(agreement.get("playable_publication_status"), 64)
        )
    report_blockers = _bounded_items(report_blockers)
    report_warnings = _bounded_items(report_warnings)
    status = GATE_STATUS_BLOCKED if report_blockers else GATE_STATUS_PASS
    if status == GATE_STATUS_PASS and report_warnings:
        status = GATE_STATUS_DEGRADED

    return {
        "status": status,
        "errors": [],
        "blockers": report_blockers,
        "warnings": report_warnings,
        "agreement": agreement,
        "playable_publication_status": agreement.get(
            "playable_publication_status", GATE_STATUS_BLOCKED
        ),
        "legacy_reports": legacy_reports,
        "source_fidelity_status": str(resolved_source_fidelity or "unknown"),
        "source_fidelity_report": adaptation_fidelity_report,
        "source_fidelity_evaluation": adaptation_fidelity,
        "build_result_present": isinstance(build_result, Mapping),
        "adaptation_report_agreement": adaptation_report_agreement,
    }


def _provenance_envelope(
    target: Mapping[str, Any],
    module_dir: Optional[Path],
    repo_root: Optional[Path],
    attempt_metadata: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build bounded attempt/stage provenance from Python-owned metadata."""
    metadata = attempt_metadata if isinstance(attempt_metadata, Mapping) else {}
    result: Dict[str, Any] = {
        "contract_version": ADAPTATION_GATE_COMPOSITION_CONTRACT_VERSION,
        "stage": "adaptation_gate_composition",
        "stage_id": _ascii_text(target.get("stage_id"), MAX_PROVENANCE_TEXT_CHARS),
        "attempt_id": _ascii_text(target.get("attempt_id"), MAX_PROVENANCE_TEXT_CHARS),
        "attempt_number": target.get("attempt_number"),
        "revision_number": target.get("revision_number"),
        "source_hash": _ascii_text(target.get("source_hash"), 64),
        "module_slug": _ascii_text(target.get("module_slug"), MAX_PROVENANCE_TEXT_CHARS),
    }
    world_context = build_world_context_provenance(metadata)
    result["world_context_provenance"] = world_context
    result["world_seed_status"] = world_context.get("world_seed_status")
    result["world_seed_version"] = world_context.get("world_seed_version")
    result["world_seed_hash"] = world_context.get("world_seed_hash")
    if module_dir is not None and repo_root is not None:
        result["module_path"] = _safe_relative_path(module_dir, repo_root)
    for key in ("source_path", "source_format", "dossier_artifact_path"):
        if metadata.get(key) not in (None, ""):
            result[key] = _ascii_text(metadata.get(key), MAX_PROVENANCE_TEXT_CHARS)
    return result


def compose_adaptation_gate_result(
    gate_results: Mapping[str, Any],
    *,
    staging_target: Mapping[str, Any],
    module_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    llm_result: Any = None,
    legacy_reports: Optional[Mapping[str, Any]] = None,
    convergence_result: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose a fail-closed adaptation candidate result.

    ``gate_results`` must come from Python-owned validators. ``llm_result`` is
    intentionally advisory metadata only and is never consulted for status.
    The returned ``publication`` envelope always records that stateful
    publication is deferred to a later Python transaction.
    """
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        target, resolved_module_dir, module_slug = _validated_staging_context(
            staging_target, module_dir, root
        )
    except Exception as exc:
        target = dict(staging_target) if isinstance(staging_target, Mapping) else {}
        resolved_module_dir = None
        module_slug = ""
        gate_results = {
            domain: {
                "status": GATE_STATUS_BLOCKED,
                "errors": [f"staging_target_invalid:{exc}"],
                "blockers": [f"staging_target_invalid:{exc}"],
                "warnings": [],
            }
            for domain in REQUIRED_GATE_DOMAINS
        }

    normalized_gates: Dict[str, Dict[str, Any]] = {}
    for domain in REQUIRED_GATE_DOMAINS:
        normalized_gates[domain] = _normalize_gate_result(
            domain, gate_results.get(domain) if isinstance(gate_results, Mapping) else None
        )

    blockers: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []
    for domain, gate in normalized_gates.items():
        blockers.extend(f"{domain}:{item}" for item in gate.get("blockers", []))
        errors.extend(f"{domain}:{item}" for item in gate.get("errors", []))
        warnings.extend(f"{domain}:{item}" for item in gate.get("warnings", []))

    all_pass = all(
        gate.get("effective_status") == GATE_STATUS_PASS
        for gate in normalized_gates.values()
    )
    all_nonblocking = all(
        gate.get("effective_status") in {GATE_STATUS_PASS, GATE_STATUS_DEGRADED}
        for gate in normalized_gates.values()
    )
    blockers = _bounded_items(blockers)
    errors = _bounded_items(errors)
    warnings = _bounded_items(warnings)

    report_agreement_gate = (
        gate_results.get(GATE_REPORT_AGREEMENT)
        if isinstance(gate_results, Mapping)
        else None
    )
    source_fidelity_report = (
        report_agreement_gate.get("source_fidelity_report")
        if isinstance(report_agreement_gate, Mapping)
        else None
    )
    if not isinstance(source_fidelity_report, Mapping):
        source_fidelity_evidence = (
            report_agreement_gate.get("source_fidelity_status")
            if isinstance(report_agreement_gate, Mapping)
            else None
        )
        source_fidelity_evaluation = evaluate_adaptation_source_fidelity(
            source_fidelity_evidence=source_fidelity_evidence,
            attempt_metadata=attempt_metadata,
            staging_target=target,
            module_slug=module_slug,
        )
        source_fidelity_report = source_fidelity_evaluation["report"]
    else:
        source_fidelity_evaluation = (
            report_agreement_gate.get("source_fidelity_evaluation")
            if isinstance(report_agreement_gate, Mapping)
            else None
        )
        if not isinstance(source_fidelity_evaluation, Mapping):
            source_fidelity_evaluation = evaluate_adaptation_source_fidelity(
                source_fidelity_evidence=source_fidelity_report.get(
                    "evidence", {}
                ),
                attempt_metadata=attempt_metadata,
                staging_target=target,
                module_slug=module_slug,
            )
    adaptation_source_status = str(
        source_fidelity_report.get(
            "source_fidelity_status", ADAPTATION_SOURCE_FIDELITY_STATUS
        )
        or ADAPTATION_SOURCE_FIDELITY_STATUS
    )

    failure_classification: Optional[Dict[str, Any]] = None
    if not all_pass:
        failed_domain = next(
            domain
            for domain, gate in normalized_gates.items()
            if gate.get("effective_status") != GATE_STATUS_PASS
        )
        failed_gate = normalized_gates[failed_domain]
        raw_message = (
            (failed_gate.get("errors") or [])
            + (failed_gate.get("blockers") or [])
            + [f"{failed_domain}_gate_failed"]
        )[0]
        failure_classification = classify_adaptation_failure(
            {
                "failure_class": (
                    "publication"
                    if failed_domain == GATE_REPORT_AGREEMENT
                    else "semantic"
                    if failed_domain in {GATE_SEMANTIC_AUTHORITY, GATE_SEMANTIC_PROBES}
                    else "mechanical"
                ),
                "message": raw_message,
            },
            attempt_metadata=attempt_metadata,
            stage="adaptation_gate_composition",
            domain=failed_domain,
        )

    provenance = _provenance_envelope(
        target,
        resolved_module_dir,
        root,
        attempt_metadata,
    )
    # A convergence report is optional for direct/provider-free composer
    # callers, but when supplied by the adaptation packet builder it is part
    # of the current gate identity and must be accepted before any status can
    # be surfaced.
    convergence_identity: Dict[str, Any] = {}
    if isinstance(convergence_result, Mapping):
        convergence_identity = {
            "status": _ascii_text(convergence_result.get("status"), 32),
            "reason_code": _ascii_text(convergence_result.get("reason_code"), 96),
            "attempt_id": _ascii_text(convergence_result.get("attempt_id"), MAX_PROVENANCE_TEXT_CHARS),
            "attempt_number": convergence_result.get("attempt_number"),
            "revision_number": convergence_result.get("revision_number"),
            "source_hash": _ascii_text(convergence_result.get("source_hash"), 64),
            "report_path": _ascii_text(convergence_result.get("report_path"), MAX_PROVENANCE_TEXT_CHARS),
        }
        expected_identity = {
            "attempt_id": target.get("attempt_id"),
            "attempt_number": target.get("attempt_number"),
            "revision_number": target.get("revision_number"),
            "source_hash": target.get("source_hash"),
        }
        actual_identity = {key: convergence_identity.get(key) for key in expected_identity}
        if convergence_identity.get("status") != "ready" or actual_identity != expected_identity:
            blockers.append("adaptation_convergence_report_stale_or_mismatched")
            all_pass = False
            all_nonblocking = False

    playable_status = (
        GATE_STATUS_PASS
        if all_pass
        else GATE_STATUS_DEGRADED
        if all_nonblocking and not blockers
        else GATE_STATUS_BLOCKED
    )
    publishable_status = GATE_STATUS_PASS if all_pass else GATE_STATUS_BLOCKED

    result: Dict[str, Any] = {
        "contract_version": ADAPTATION_GATE_COMPOSITION_CONTRACT_VERSION,
        "status": GATE_STATUS_PASS if all_pass else GATE_STATUS_BLOCKED,
        "adaptation_status": "ready_for_publication" if all_pass else "blocked",
        "playable_status": playable_status,
        "publishable_status": publishable_status,
        "candidate_eligible": bool(all_pass),
        "publication": {
            "authority": "python",
            "status": "deferred",
            "attempted": False,
            "allowed": False,
            "candidate_eligible": bool(all_pass),
        },
        "python_authoritative": True,
        "llm_publication_override": False,
        "provenance": provenance,
        "gates": normalized_gates,
        "blockers": blockers,
        "errors": errors,
        "warnings": warnings,
        "source_fidelity_status": adaptation_source_status,
        "source_fidelity_report": dict(source_fidelity_report),
        "source_fidelity_evaluation": dict(source_fidelity_evaluation),
        "failure_classification": failure_classification,
        "model_advisory": {
            "provided": llm_result is not None,
            "used_for_gate": False,
            "ignored_for_publication": llm_result is not None,
            "reason": "Only Python-owned deterministic gates decide eligibility.",
        },
        "checked_at": _utc_now_iso(),
    }
    if convergence_identity:
        result["convergence_report"] = convergence_identity
    if isinstance(legacy_reports, Mapping):
        result["legacy_reports"] = {
            _ascii_text(key, 64): {
                "state": _ascii_text(value.get("state"), 64)
                if isinstance(value, Mapping)
                else "unknown"
            }
            for key, value in list(legacy_reports.items())[:8]
        }
    return result


def run_adaptation_gate_composer(
    staging_target: Mapping[str, Any],
    *,
    module_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    attempt_metadata: Optional[Mapping[str, Any]] = None,
    source_fidelity_status: Optional[str] = None,
    build_result: Optional[Mapping[str, Any]] = None,
    llm_result: Any = None,
    attempt_report: Any = None,
    convergence_result: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run all deterministic adaptation gates against one staging target."""
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        target, resolved_module_dir, module_slug = _validated_staging_context(
            staging_target, module_dir, root
        )
    except Exception as exc:
        invalid = {
            domain: {
                "status": GATE_STATUS_BLOCKED,
                "errors": [f"staging_target_invalid:{exc}"],
                "blockers": [f"staging_target_invalid:{exc}"],
                "warnings": [],
            }
            for domain in REQUIRED_GATE_DOMAINS
        }
        invalid_result = compose_adaptation_gate_result(
            invalid,
            staging_target=staging_target,
            module_dir=module_dir,
            repo_root=root,
            attempt_metadata=attempt_metadata,
            llm_result=llm_result,
        )
        return invalid_result

    schema_report = _run_schema_gate(resolved_module_dir, root)
    gameplay_report = _run_gameplay_gate(resolved_module_dir, root, module_slug)
    gameplay_payload = _extract_gameplay_payload(
        gameplay_report.get("raw") or {}
        if isinstance(gameplay_report, Mapping)
        else {}
    )
    gameplay_report = _maybe_relax_toolkit_media_only_gameplay_gate(
        gameplay_report,
        gameplay_payload,
        "toolkit",
    )
    continuity_report = _run_continuity_gate(resolved_module_dir)

    schema_gate = _normalize_gate_result(GATE_SCHEMA, schema_report)
    gameplay_gate = _normalize_gate_result("gameplay", gameplay_report)
    continuity_gate = _normalize_gate_result("continuity", continuity_report)
    readiness_report = {
        "status": (
            GATE_STATUS_PASS
            if all(
                gate.get("effective_status") == GATE_STATUS_PASS
                for gate in (schema_gate, gameplay_gate, continuity_gate)
            )
            else GATE_STATUS_BLOCKED
        ),
        "gates": {
            "schema": schema_gate,
            "gameplay": gameplay_gate,
            "continuity": continuity_gate,
        },
        "blocking_errors": [
            item
            for gate in (schema_gate, gameplay_gate, continuity_gate)
            for item in gate.get("blockers", [])
        ],
        "warnings": [
            item
            for gate in (schema_gate, gameplay_gate, continuity_gate)
            for item in gate.get("warnings", [])
        ],
    }

    gate_reports: Dict[str, Any] = {
        GATE_SCHEMA: schema_report,
        GATE_READINESS: readiness_report,
        GATE_MECHANICAL_CLOSURE: _run_mechanical_closure_gate(
            resolved_module_dir,
            build_result,
            gameplay_report,
        ),
        GATE_SEMANTIC_AUTHORITY: _run_semantic_authority_gate(
            module_slug,
            resolved_module_dir,
            convergence_result=convergence_result,
        ),
        GATE_SEMANTIC_PROBES: _run_semantic_probe_gate(resolved_module_dir),
    }
    gate_reports[GATE_REPORT_AGREEMENT] = _run_report_agreement_gate(
        resolved_module_dir,
        gate_reports,
        source_fidelity_status=source_fidelity_status,
        build_result=build_result,
        attempt_metadata=attempt_metadata,
        staging_target=target,
        module_slug=module_slug,
        attempt_report=attempt_report,
    )

    legacy_reports = gate_reports[GATE_REPORT_AGREEMENT].get("legacy_reports")
    result = compose_adaptation_gate_result(
        gate_reports,
        staging_target=target,
        module_dir=resolved_module_dir,
        repo_root=root,
        attempt_metadata=attempt_metadata,
        llm_result=llm_result,
        legacy_reports=legacy_reports,
        convergence_result=convergence_result,
    )
    result["source_fidelity_status"] = gate_reports[GATE_REPORT_AGREEMENT].get(
        "source_fidelity_status", "unknown"
    )
    result["staging_target"] = {
        "stage_id": _ascii_text(target.get("stage_id"), MAX_PROVENANCE_TEXT_CHARS),
        "path": _ascii_text(target.get("path"), MAX_PROVENANCE_TEXT_CHARS),
        "completion_state": _ascii_text(
            target.get("completion_state"), MAX_PROVENANCE_TEXT_CHARS
        ),
    }
    return result


# Discoverable aliases for callers that prefer an action-oriented name.
run_adaptation_gates = run_adaptation_gate_composer
compose_adaptation_gates = compose_adaptation_gate_result


__all__ = [
    "ADAPTATION_GATE_COMPOSITION_CONTRACT_VERSION",
    "GATE_SCHEMA",
    "GATE_READINESS",
    "GATE_MECHANICAL_CLOSURE",
    "GATE_SEMANTIC_AUTHORITY",
    "GATE_SEMANTIC_PROBES",
    "GATE_REPORT_AGREEMENT",
    "REQUIRED_GATE_DOMAINS",
    "GATE_STATUS_PASS",
    "GATE_STATUS_DEGRADED",
    "GATE_STATUS_BLOCKED",
    "GATE_STATUS_UNKNOWN",
    "ADAPTATION_SOURCE_FIDELITY_STATUS",
    "AdaptationGateCompositionError",
    "compose_adaptation_gate_result",
    "compose_adaptation_gates",
    "run_adaptation_gate_composer",
    "run_adaptation_gates",
]
