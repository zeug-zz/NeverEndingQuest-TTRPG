# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free orchestration boundary for adaptation publication convergence.

This module deliberately does not repair module content or call a provider by
itself.  An optional callback is an injected proposal boundary.  The seam
validates the current staging identity before invoking it and persists only a
small, atomic report beside that staging revision.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_config import BUILD_MODE_LLM_ADAPTATION
from utils.toolkit_adaptation_staging import (
    STAGING_METADATA_FILENAME,
    STAGING_STATE_BUILDING,
    STAGING_STATE_RESERVED,
    validate_adaptation_staging_target,
)
from utils.toolkit_adaptation_output_safety import AdaptationOutputSafety, project_safe_event
from utils.toolkit_adaptation_semantic_authority import (
    build_adaptation_semantic_authority,
    persist_adaptation_semantic_authority,
)
from utils.toolkit_homebrew_upload_contract import (
    load_normalized_packet_artifact,
    load_source_graph_artifact,
    load_source_manifest_artifact,
)


CONVERGENCE_CONTRACT_VERSION = "toolkit_adaptation_publication_convergence.v1"
CONVERGENCE_REPORT_FILENAME = "adaptation_convergence_report.json"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_OPERATIONS_PER_ROUND = 1
DEFAULT_OPERATION_TIMEOUT_SECONDS = 30
VALID_STATUSES = frozenset({"not_applicable", "ready", "blocked", "failed", "budget_exhausted"})
VALID_PROVIDER_FAILURE_CLASSES = frozenset(
    {"timeout", "quota", "unavailable", "malformed", "rejected", "unknown"}
)

# Bounds for the provider-facing ambiguity context.  These limits are kept
# here, rather than in a caller, so every future provider seam gets the same
# small, deterministic contract.
RESOLUTION_OPERATION = "resolve_destination_alias"
RESOLUTION_CONTRACT_VERSION = "adaptation_destination_resolution.v1"
RESOLUTION_CONFIDENCE_THRESHOLD = 0.80
MAX_RESOLUTION_PHRASE_CHARS = 160
MAX_RESOLUTION_CANDIDATES = 8
MAX_RESOLUTION_CANDIDATE_CHARS = 120
MAX_RESOLUTION_SOURCE_REFERENCES = 8
MAX_RESOLUTION_SOURCE_REF_ID_CHARS = 120
MAX_RESOLUTION_SOURCE_EXCERPT_CHARS = 320
MAX_RESOLUTION_TOPOLOGY_CHARS = 1200
MAX_RESOLUTION_TOPOLOGY_LOCATIONS = 24
MAX_RESOLUTION_TOPOLOGY_EDGES = 24
MAX_RESOLUTION_DIAGNOSTICS = 8

# Preparation bounds are deliberately smaller than the provider serializer.
# This object is an internal handoff for the next convergence task, not a
# second source-content envelope.
MAX_REPAIR_SOURCE_REFS = 8
MAX_REPAIR_SOURCE_REF_ID_CHARS = 120
MAX_REPAIR_SOURCE_EXCERPT_CHARS = 320
MAX_REPAIR_CANDIDATES = 8
MAX_REPAIR_TOPOLOGY_LOCATIONS = 24
MAX_REPAIR_TOPOLOGY_EDGES = 24

# Finalization is intentionally a separate contract from the older request
# serializer above.  These operations describe proposals, not file patches.
FINALIZATION_CONTRACT_VERSION = "adaptation_finalization_proposal.v1"
FINALIZATION_OPERATION_DESTINATION_ALIAS = "resolve_destination_alias"
FINALIZATION_OPERATION_NARRATIVE_COMPLETION = "complete_authored_narrative"
FINALIZATION_OPERATION_STAT_COMPLETION = "request_canonical_stat_completion"
FINALIZATION_OPERATION_MONSTER_REFERENCE = "resolve_monster_reference"
FINALIZATION_OPERATIONS = frozenset(
    {
        FINALIZATION_OPERATION_DESTINATION_ALIAS,
        FINALIZATION_OPERATION_NARRATIVE_COMPLETION,
        FINALIZATION_OPERATION_STAT_COMPLETION,
        FINALIZATION_OPERATION_MONSTER_REFERENCE,
    }
)
FINALIZATION_CONFIDENCE_THRESHOLD = 0.80
MAX_FINALIZATION_TEXT_CHARS = 640
MAX_FINALIZATION_SOURCE_REFERENCES = 8
MAX_FINALIZATION_DIAGNOSTICS = 12
_FINALIZATION_FIELDS = {
    FINALIZATION_OPERATION_DESTINATION_ALIAS: frozenset(
        {"operation", "identity", "target", "source_references", "confidence", "replacement", "topology", "contract_version"}
    ),
    FINALIZATION_OPERATION_NARRATIVE_COMPLETION: frozenset(
        {"operation", "identity", "target", "source_references", "confidence", "replacement", "topology", "contract_version"}
    ),
    FINALIZATION_OPERATION_STAT_COMPLETION: frozenset(
        {"operation", "identity", "target", "source_references", "confidence", "topology", "contract_version"}
    ),
    FINALIZATION_OPERATION_MONSTER_REFERENCE: frozenset(
        {
            "operation", "identity", "target", "source_references", "confidence",
            "quantity_confirmation", "resolution_code", "contract_version",
        }
    ),
}

FINALIZATION_MONSTER_RESOLUTION_CODES = frozenset(
    {"canonical_alias", "plural_group_label", "scene_reference"}
)
MAX_FINALIZATION_MONSTER_REFERENCE_CHARS = 160
MAX_FINALIZATION_MONSTER_IDENTITY_CHARS = 160
MAX_FINALIZATION_MONSTER_QUANTITY = 999

_SHA256_LENGTH = 64


@dataclass(frozen=True)
class AdaptationConvergenceConfig:
    """Fixed, bounded budgets for one finalization invocation."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_operations_per_round: int = DEFAULT_MAX_OPERATIONS_PER_ROUND
    operation_timeout_seconds: int = DEFAULT_OPERATION_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if isinstance(self.max_operations_per_round, bool) or not 1 <= self.max_operations_per_round <= 10:
            raise ValueError("max_operations_per_round must be between 1 and 10")
        if isinstance(self.operation_timeout_seconds, bool) or not 1 <= self.operation_timeout_seconds <= 300:
            raise ValueError("operation_timeout_seconds must be between 1 and 300")


@dataclass(frozen=True)
class AdaptationConvergenceResult:
    """Typed result containing bounded diagnostics and no provider payload."""

    status: str
    reason_code: str
    attempt_id: Optional[str]
    attempt_number: Optional[int]
    revision_number: Optional[int]
    report_path: Optional[str]
    next_revision_eligible: bool
    max_attempts: int
    max_operations_per_round: int
    operation_timeout_seconds: int
    current_attempt: int = 0
    stage: str = "finalization"
    operation_name: Optional[str] = None
    accepted_operation: Optional[Dict[str, Any]] = None
    provider_failure_class: Optional[str] = None
    diagnostics: tuple[str, ...] = ()
    proposal_input_hash: Optional[str] = None
    accepted_output_hash: Optional[str] = None
    provenance_hash: Optional[str] = None
    source_hash: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        safe_report_path = self.report_path
        if isinstance(safe_report_path, str) and (
            safe_report_path.startswith(("/", "\\")) or ":\\" in safe_report_path
        ):
            safe_report_path = None
        safe_diagnostics = []
        for diagnostic in self.diagnostics[:MAX_FINALIZATION_DIAGNOSTICS]:
            event = project_safe_event(
                phase=self.stage,
                status=self.status,
                code=diagnostic if isinstance(diagnostic, str) else "finalization_diagnostic",
                message=diagnostic,
            )
            safe_diagnostics.append(event.get("message") or event["code"])
        return {
            "contract_version": CONVERGENCE_CONTRACT_VERSION,
            "status": self.status,
            "reason_code": self.reason_code,
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "revision_number": self.revision_number,
            "report_path": safe_report_path,
            "next_revision_eligible": self.next_revision_eligible,
            "budget": {
                "max_attempts": self.max_attempts,
                "max_operations_per_round": self.max_operations_per_round,
                "operation_timeout_seconds": self.operation_timeout_seconds,
            },
            "budget_state": {
                "current_attempt": self.current_attempt,
                "max_attempts": self.max_attempts,
                "max_operations_per_round": self.max_operations_per_round,
                "operation_timeout_seconds": self.operation_timeout_seconds,
            },
            "stage": self.stage,
            "operation": self.operation_name,
            "accepted_operation": deepcopy(self.accepted_operation) if self.accepted_operation else None,
            "provider_failure_class": self.provider_failure_class,
            "diagnostics": safe_diagnostics,
            "proposal_input_hash": self.proposal_input_hash,
            "accepted_output_hash": self.accepted_output_hash,
            "provenance_hash": self.provenance_hash,
            "source_hash": self.source_hash,
        }


ProviderCallback = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _resolution_ascii(value: Any, limit: int) -> str:
    return str(value or "").strip().encode("ascii", "replace").decode("ascii")[:limit]


def _repair_identity(value: Mapping[str, Any]) -> Dict[str, Any]:
    bounded: Dict[str, Any] = {
        "attempt_id": _resolution_ascii(value.get("attempt_id"), 96),
        "attempt_number": value.get("attempt_number"),
        "revision_number": value.get("revision_number"),
        "source_hash": _resolution_ascii(value.get("source_hash"), 64),
    }
    return bounded


def _repair_source_references(
    manifest: Mapping[str, Any], packet: Mapping[str, Any], graph: Mapping[str, Any]
) -> list[Dict[str, str]]:
    """Extract only compact, source-owned references for one repair request."""
    rows: Dict[str, Dict[str, str]] = {}

    def add(ref_id: Any, excerpt: Any, fallback: str) -> None:
        identifier = _resolution_ascii(ref_id or fallback, MAX_REPAIR_SOURCE_REF_ID_CHARS)
        text = _resolution_ascii(excerpt, MAX_REPAIR_SOURCE_EXCERPT_CHARS)
        if identifier and text and identifier not in rows:
            rows[identifier] = {"id": identifier, "excerpt": text}

    for item in manifest.get("location_candidates", []) if isinstance(manifest.get("location_candidates"), list) else []:
        if isinstance(item, Mapping):
            add(item.get("source_ref") or item.get("source_path"), item.get("name"), "source_manifest")
    for key in ("destination_phrases", "source_location_names", "locations"):
        values = packet.get(key)
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if isinstance(item, Mapping):
                add(item.get("source_ref") or item.get("source_path"), item.get("excerpt") or item.get("phrase") or item.get("name"), f"normalized_packet.{key}[{index}]")
            elif item:
                add(f"normalized_packet.{key}[{index}]", item, f"normalized_packet.{key}[{index}]")
    atoms = graph.get("atoms")
    if isinstance(atoms, list):
        for index, item in enumerate(atoms):
            if isinstance(item, Mapping):
                add(item.get("source_ref") or item.get("atom_id") or item.get("id"), item.get("excerpt") or item.get("text") or item.get("content"), f"source_graph.atoms[{index}]")
    return [rows[key] for key in sorted(rows)[:MAX_REPAIR_SOURCE_REFS]]


def _repair_topology(module_dir: Path, authority: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a bounded topology summary using the staged authored areas."""
    location_index = authority.get("location_index") if isinstance(authority.get("location_index"), Mapping) else {}
    locations = sorted(
        str(key) for key in location_index
        if str(key).strip()
    )[:MAX_REPAIR_TOPOLOGY_LOCATIONS]
    edges: set[tuple[str, str]] = set()
    for scoped_id in locations:
        record = location_index.get(scoped_id)
        location = record.get("location") if isinstance(record, Mapping) else None
        if not isinstance(location, Mapping):
            continue
        area_id = str(record.get("area_id") or "").strip().upper()
        for field in ("connectivity", "connectedLocations", "areaConnectivityId"):
            values = location.get(field)
            if not isinstance(values, list):
                continue
            for value in values:
                raw = str(value or "").strip().upper()
                if not raw:
                    continue
                target = raw if ":" in raw else (f"{area_id}:{raw}" if area_id and f"{area_id}:{raw}" in location_index else raw)
                if target in location_index and target != scoped_id:
                    edges.add(tuple(sorted((scoped_id, target))))
    edge_rows = [list(edge) for edge in sorted(edges)[:MAX_REPAIR_TOPOLOGY_EDGES]]
    return {"locations": locations, "edges": edge_rows}


def prepare_adaptation_repair_context(
    *,
    workspace: Path,
    staged_module_path: Path,
    module_slug: str,
    attempt: Mapping[str, Any],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Prepare current staged authority and one bounded repair context.

    This is intentionally provider-free.  It persists authority only beneath
    ``staged_module_path`` and returns an empty context when no genuinely
    ambiguous destination blocker remains.
    """
    identity = _repair_identity(attempt)
    required = ("attempt_id", "attempt_number", "revision_number", "source_hash")
    # ``revision_number=0`` is the valid initial staging revision, so truthy
    # checks incorrectly reject every first-pass adaptation build.
    if any(identity.get(field) in (None, "") for field in required):
        return {"status": "blocked", "reason_code": "repair_context_identity_invalid", "identity": identity, "validation_context": None, "diagnostics": ["identity_missing"]}
    try:
        metadata = safe_read_json(str(staged_module_path / STAGING_METADATA_FILENAME))
        if not isinstance(metadata, Mapping):
            raise ValueError("staging_metadata_missing")
        target = validate_adaptation_staging_target(
            metadata,
            source_hash=identity["source_hash"],
            attempt_id=identity["attempt_id"],
            attempt_number=identity["attempt_number"],
            revision_number=identity["revision_number"],
            module_slug=module_slug,
            repo_root=repo_root,
            require_reserved=False,
        )
        if target.get("module_slug") != module_slug:
            raise ValueError("staging_module_slug_mismatch")
        manifest = load_source_manifest_artifact(workspace)
        packet = load_normalized_packet_artifact(workspace)
        graph = load_source_graph_artifact(workspace)
        if not isinstance(manifest, Mapping) or not isinstance(packet, Mapping) or not isinstance(graph, Mapping):
            raise ValueError("source_artifact_missing_or_malformed")
        authority_result = build_adaptation_semantic_authority(
            module_slug, staged_module_path, attempt=identity,
            source_manifest=manifest, normalized_packet=packet,
        )
        if not isinstance(authority_result.get("semantic_authority"), Mapping):
            raise ValueError("semantic_authority_unavailable")
        persisted = persist_adaptation_semantic_authority(staged_module_path, authority_result)
        if persisted.get("status") != "persisted":
            raise ValueError(str(persisted.get("reason") or "semantic_authority_persist_failed"))
        authority = authority_result["semantic_authority"]
        blocker = next((row for row in authority_result.get("blockers", []) if isinstance(row, Mapping) and row.get("code") == "ambiguous_destination_phrase"), None)
        if blocker is None:
            return {"status": "no_repairable_blocker", "reason_code": "no_repairable_ambiguous_destination", "identity": identity, "semantic_authority": authority, "validation_context": None, "diagnostics": []}
        phrase = _resolution_ascii(blocker.get("phrase"), MAX_RESOLUTION_PHRASE_CHARS)
        raw_ids = authority.get("location_aliases", {}).get(phrase, {}).get("candidate_internal_location_ids", [])
        if not raw_ids:
            raw_ids = blocker.get("candidate_location_ids", [])
        candidates = []
        for candidate_id in list(raw_ids)[:MAX_REPAIR_CANDIDATES]:
            row = authority.get("location_index", {}).get(str(candidate_id))
            if isinstance(row, Mapping):
                candidates.append({"id": str(row.get("scoped_location_id") or candidate_id), "name": _resolution_ascii(row.get("location_name"), MAX_RESOLUTION_CANDIDATE_CHARS), "area_id": _resolution_ascii(row.get("area_id"), 96)})
        candidates = [row for row in candidates if row["id"] and row["name"]]
        source_references = _repair_source_references(manifest, packet, graph)
        topology = _repair_topology(staged_module_path, authority)
        if not candidates or not source_references:
            return {"status": "no_repairable_blocker", "reason_code": "ambiguous_destination_evidence_insufficient", "identity": identity, "semantic_authority": authority, "validation_context": None, "diagnostics": ["bounded_candidates_or_source_references_missing"]}
        context = {
            "status": "repairable",
            "repairable": True,
            "attempt_id": identity["attempt_id"],
            "attempt_number": identity["attempt_number"],
            "revision_number": identity["revision_number"],
            "source_hash": identity["source_hash"],
            "repair_requests": [{"operation": RESOLUTION_OPERATION, "phrase": phrase, "blocker": "ambiguous_destination_phrase"}],
            "source_reference_ids": [row["id"] for row in source_references],
            "source_references": source_references,
            "canonical_location_ids": [row["id"] for row in candidates],
            "candidates": candidates,
            "topology": topology,
            "allowed_operations": [RESOLUTION_OPERATION],
            "confidence_threshold": RESOLUTION_CONFIDENCE_THRESHOLD,
            "operation_budget": 1,
            "timeout_seconds": DEFAULT_OPERATION_TIMEOUT_SECONDS,
        }
        return {"status": "repairable", "reason_code": "ambiguous_destination_ready", "identity": identity, "semantic_authority": authority, "validation_context": context, "diagnostics": []}
    except Exception as exc:
        return {"status": "blocked", "reason_code": "repair_context_preparation_failed", "identity": identity, "validation_context": None, "diagnostics": [_resolution_ascii(str(exc), 240)]}


def _resolution_identity(
    attempt_id: Any,
    attempt_number: Any,
    revision_number: Any,
    source_hash: Any,
) -> tuple[Optional[Dict[str, Any]], list[str]]:
    diagnostics: list[str] = []
    normalized_id = _resolution_ascii(attempt_id, 96)
    if not normalized_id or normalized_id != str(attempt_id).strip() or len(str(attempt_id).strip()) > 96:
        diagnostics.append("attempt_id_invalid")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 0:
        diagnostics.append("attempt_number_invalid")
    if isinstance(revision_number, bool) or not isinstance(revision_number, int) or revision_number < 0:
        diagnostics.append("revision_number_invalid")
    if not _is_sha256(source_hash):
        diagnostics.append("source_hash_invalid")
    if diagnostics:
        return None, diagnostics[:MAX_RESOLUTION_DIAGNOSTICS]
    return {
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "revision_number": revision_number,
        "source_hash": source_hash,
    }, []


def _resolution_candidate_rows(value: Any) -> tuple[list[Dict[str, str]], list[str]]:
    if not isinstance(value, (list, tuple)):
        return [], ["candidates_invalid"]
    if len(value) > MAX_RESOLUTION_CANDIDATES:
        return [], ["candidates_limit_exceeded"]
    rows: list[Dict[str, str]] = []
    diagnostics: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            candidate_id = item.get("id") or item.get("location_id")
            name = item.get("name") or item.get("display_name")
            if set(item) - {"id", "location_id", "name", "display_name"}:
                diagnostics.append("candidate_fields_not_allowed")
        elif isinstance(item, str):
            candidate_id, name = item, item
        else:
            diagnostics.append("candidate_invalid")
            continue
        candidate_id = _resolution_ascii(candidate_id, MAX_RESOLUTION_CANDIDATE_CHARS)
        name = _resolution_ascii(name, MAX_RESOLUTION_CANDIDATE_CHARS)
        if not candidate_id or not name:
            diagnostics.append("candidate_identity_missing")
            continue
        if len(str(item.get("id") if isinstance(item, Mapping) and item.get("id") else candidate_id)) > MAX_RESOLUTION_CANDIDATE_CHARS:
            diagnostics.append("candidate_id_limit_exceeded")
        rows.append({"id": candidate_id, "name": name})
    rows = sorted(rows, key=lambda row: (row["id"].lower(), row["name"].lower()))
    if len({row["id"] for row in rows}) != len(rows):
        diagnostics.append("candidate_ids_not_unique")
    if not rows:
        diagnostics.append("candidates_missing")
    return rows, diagnostics[:MAX_RESOLUTION_DIAGNOSTICS]


def _resolution_source_rows(value: Any) -> tuple[list[Dict[str, str]], list[str]]:
    if not isinstance(value, (list, tuple)):
        return [], ["source_references_invalid"]
    if len(value) > MAX_RESOLUTION_SOURCE_REFERENCES:
        return [], ["source_references_limit_exceeded"]
    rows: list[Dict[str, str]] = []
    diagnostics: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"id", "ref_id", "excerpt"}:
            diagnostics.append("source_reference_fields_not_allowed")
            continue
        ref_id = _resolution_ascii(item.get("id") or item.get("ref_id"), MAX_RESOLUTION_SOURCE_REF_ID_CHARS)
        excerpt = _resolution_ascii(item.get("excerpt"), MAX_RESOLUTION_SOURCE_EXCERPT_CHARS)
        if not ref_id or not excerpt:
            diagnostics.append("source_reference_identity_or_excerpt_missing")
            continue
        if len(str(item.get("id") or item.get("ref_id"))) > MAX_RESOLUTION_SOURCE_REF_ID_CHARS:
            diagnostics.append("source_reference_id_limit_exceeded")
        if len(str(item.get("excerpt"))) > MAX_RESOLUTION_SOURCE_EXCERPT_CHARS:
            diagnostics.append("source_excerpt_limit_exceeded")
        rows.append({"id": ref_id, "excerpt": excerpt})
    rows = sorted(rows, key=lambda row: row["id"].lower())
    if not rows:
        diagnostics.append("source_references_missing")
    return rows, diagnostics[:MAX_RESOLUTION_DIAGNOSTICS]


def _resolution_topology(value: Any) -> tuple[Optional[Dict[str, Any]], list[str]]:
    if not isinstance(value, Mapping):
        return None, ["topology_summary_invalid"]
    allowed = {"locations", "location_ids", "edges", "summary"}
    if set(value) - allowed:
        return None, ["topology_fields_not_allowed"]
    locations = value.get("locations", value.get("location_ids", []))
    edges = value.get("edges", [])
    summary = _resolution_ascii(value.get("summary"), MAX_RESOLUTION_TOPOLOGY_CHARS)
    if not isinstance(locations, (list, tuple)) or len(locations) > MAX_RESOLUTION_TOPOLOGY_LOCATIONS:
        return None, ["topology_locations_limit_exceeded"]
    if not isinstance(edges, (list, tuple)) or len(edges) > MAX_RESOLUTION_TOPOLOGY_EDGES:
        return None, ["topology_edges_limit_exceeded"]
    location_rows = sorted({_resolution_ascii(item, MAX_RESOLUTION_CANDIDATE_CHARS) for item in locations if _resolution_ascii(item, MAX_RESOLUTION_CANDIDATE_CHARS)})
    edge_rows: list[list[str]] = []
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            return None, ["topology_edge_invalid"]
        edge_rows.append(sorted([_resolution_ascii(edge[0], MAX_RESOLUTION_CANDIDATE_CHARS), _resolution_ascii(edge[1], MAX_RESOLUTION_CANDIDATE_CHARS)]))
    normalized = {"locations": location_rows, "edges": sorted(edge_rows)}
    if summary:
        normalized["summary"] = summary
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_RESOLUTION_TOPOLOGY_CHARS:
        return None, ["topology_summary_limit_exceeded"]
    return normalized, []


def build_adaptation_resolution_request(
    *,
    mode: str,
    ambiguous_phrase: Any,
    candidates: Any,
    source_references: Any,
    topology_summary: Any,
    attempt_id: Any,
    attempt_number: Any,
    revision_number: Any,
    source_hash: Any,
    current_identity: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the provider-independent, bounded destination proposal request.

    This is a request serializer only.  It intentionally has no provider
    callback and no module path; a later task may pass the returned ``request``
    to an injected provider and Python will remain the authority for applying
    any proposal.
    """
    if mode != BUILD_MODE_LLM_ADAPTATION:
        return {"status": "not_applicable", "reason_code": "legacy_mode", "request": None, "diagnostics": []}

    identity, diagnostics = _resolution_identity(attempt_id, attempt_number, revision_number, source_hash)
    if current_identity is not None:
        if not isinstance(current_identity, Mapping):
            diagnostics.append("current_identity_invalid")
        else:
            for field in ("attempt_id", "attempt_number", "revision_number", "source_hash"):
                if current_identity.get(field) != locals()[field]:
                    diagnostics.append("current_identity_mismatch:" + field)
    phrase = _resolution_ascii(ambiguous_phrase, MAX_RESOLUTION_PHRASE_CHARS)
    if not phrase or phrase != str(ambiguous_phrase or "").strip() or len(str(ambiguous_phrase or "").strip()) > MAX_RESOLUTION_PHRASE_CHARS:
        diagnostics.append("ambiguous_phrase_invalid_or_limit_exceeded")
    candidate_rows, candidate_diagnostics = _resolution_candidate_rows(candidates)
    source_rows, source_diagnostics = _resolution_source_rows(source_references)
    topology, topology_diagnostics = _resolution_topology(topology_summary)
    diagnostics.extend(candidate_diagnostics + source_diagnostics + topology_diagnostics)
    if diagnostics or identity is None or topology is None:
        return {"status": "blocked", "reason_code": "resolution_context_invalid", "request": None, "diagnostics": diagnostics[:MAX_RESOLUTION_DIAGNOSTICS]}

    request = {
        "contract_version": RESOLUTION_CONTRACT_VERSION,
        "operation": RESOLUTION_OPERATION,
        "confidence": {"minimum": RESOLUTION_CONFIDENCE_THRESHOLD, "unit": "probability"},
        "identity": identity,
        "limits": {
            "max_candidates": MAX_RESOLUTION_CANDIDATES,
            "max_source_references": MAX_RESOLUTION_SOURCE_REFERENCES,
            "max_topology_chars": MAX_RESOLUTION_TOPOLOGY_CHARS,
        },
        "context": {
            "ambiguous_phrase": phrase,
            "candidates": candidate_rows,
            "source_references": source_rows,
            "topology_summary": topology,
        },
    }
    return {"status": "ready", "reason_code": "bounded_resolution_request", "request": request, "diagnostics": []}


def _bounded_reason(value: Any) -> str:
    return str(value or "unknown").strip().encode("ascii", "replace").decode("ascii")[:120]


def _safe_operation_name(value: Any) -> Optional[str]:
    """Keep operation labels allowlisted; never copy provider text to reports."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if candidate in FINALIZATION_OPERATIONS else None


def _bounded_diagnostics(value: Any) -> tuple[str, ...]:
    """Return diagnostic codes only; provider messages never enter reports."""
    if isinstance(value, Mapping):
        value = value.get("diagnostics", ())
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        value = (value,) if value else ()
    rows = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("code") or item.get("reason_code")
        if item:
            rows.append(_bounded_reason(item))
    return tuple(dict.fromkeys(rows))[:MAX_FINALIZATION_DIAGNOSTICS]


def _stable_hash(value: Any) -> str:
    """Hash an input/output without persisting its contents."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        encoded = repr(value)
    return hashlib.sha256(encoded.encode("utf-8", "replace")).hexdigest()


def _provider_failure_class(exc: Any = None, callback_result: Any = None) -> Optional[str]:
    if isinstance(callback_result, Mapping):
        explicit = callback_result.get("provider_failure_class")
        if isinstance(explicit, str) and explicit in {
            "timeout", "quota", "unavailable", "malformed", "rejected", "unknown"
        }:
            return explicit
    text = " ".join(
        _bounded_reason(part).lower()
        for part in (
            getattr(exc, "__class__", type("Unknown", (), {})).__name__ if exc else "",
            str(exc) if exc else "",
            callback_result.get("reason_code", "") if isinstance(callback_result, Mapping) else "",
        )
    )
    if not text:
        return None
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in text for token in ("quota", "rate_limit", "rate limit", "429")):
        return "quota"
    if any(token in text for token in ("unavailable", "connection", "credential", "auth", "503", "504")):
        return "unavailable"
    if isinstance(callback_result, Mapping) and callback_result.get("status") in {"malformed", "invalid"}:
        return "malformed"
    if isinstance(callback_result, Mapping) and callback_result.get("status") in {"rejected", "failed"}:
        return "rejected"
    return "unknown"


def _retry_allowed_after_callback_failure(
    provider_failure_class: Optional[str],
    *,
    current_attempt: int,
    budget: AdaptationConvergenceConfig,
    failure_class: Optional[str] = None,
) -> bool:
    """Keep retry eligibility limited to retryable infrastructure failures.

    The callback boundary can return malformed or rejected proposals as well
    as provider infrastructure failures.  Those outcomes are not equivalent:
    an invalid proposal must remain blocked, while an eligible timeout, quota,
    or unavailable provider attempt may be retried under the existing attempt
    budget.  Dependency failures remain terminal per the shared failure
    classifier contract.
    """
    return (
        failure_class != "dependency"
        and
        provider_failure_class in {"timeout", "quota", "unavailable"}
        and current_attempt < budget.max_attempts
    )


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _finalization_diag(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {"code": str(code)[:96], "message": str(message)[:240], "path": str(path)[:160]}


def _finalization_text(value: Any, limit: int = MAX_FINALIZATION_TEXT_CHARS) -> Optional[str]:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        return None
    text = value.strip().encode("ascii", "replace").decode("ascii")
    if not text or "\x00" in text:
        return None
    return text


def _normalize_phrase(value: Any) -> str:
    text = str(value or "").lower().replace("_", " ").replace("-", "").replace("'", "")
    return " ".join("".join(char if char.isalnum() or char.isspace() else " " for char in text).split())


def _finalization_identity(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    attempt_id = value.get("attempt_id")
    attempt_number = value.get("attempt_number")
    revision_number = value.get("revision_number")
    source_hash = value.get("source_hash")
    if not isinstance(attempt_id, str) or not attempt_id or not isinstance(attempt_number, int) or isinstance(attempt_number, bool):
        return None
    if not isinstance(revision_number, int) or isinstance(revision_number, bool) or not _is_sha256(source_hash):
        # revision_number is checked separately below; this branch keeps the
        # source digest requirement explicit and fail-closed.
        if not isinstance(revision_number, int) or isinstance(revision_number, bool) or not _is_sha256(source_hash):
            return None
    return {"attempt_id": attempt_id, "attempt_number": attempt_number, "revision_number": revision_number, "source_hash": source_hash}


def _finalization_topology(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) - {"location_ids", "edges"}:
        return None
    locations = value.get("location_ids")
    edges = value.get("edges")
    if not isinstance(locations, (list, tuple)) or not isinstance(edges, (list, tuple)):
        return None
    location_ids = {str(item) for item in locations if isinstance(item, str) and item}
    normalized_edges = set()
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2 or not all(isinstance(item, str) for item in edge):
            return None
        if edge[0] not in location_ids or edge[1] not in location_ids:
            return None
        normalized_edges.add(tuple(sorted(edge)))
    return {"location_ids": location_ids, "edges": normalized_edges}


def _bounded_finalization_validation_context(value: Any) -> Optional[Dict[str, Any]]:
    """Keep callback validation context canonical and bounded."""
    if not isinstance(value, Mapping):
        return None
    source_ids = value.get("source_reference_ids", ())
    location_ids = value.get("canonical_location_ids", ())
    authored_ids = value.get("authored_target_ids", ())
    monster_ids = value.get("approved_monster_ids", ())
    approved_identities = value.get("approved_monster_identities", ())
    reference_keys = value.get("monster_reference_keys", ())
    if not all(isinstance(item, (list, tuple, set, frozenset)) for item in (source_ids, location_ids, authored_ids, monster_ids, approved_identities, reference_keys)):
        return None
    raw_topology = value.get("topology")
    if isinstance(raw_topology, Mapping) and "location_ids" not in raw_topology:
        raw_topology = {
            "location_ids": raw_topology.get("locations", []),
            "edges": raw_topology.get("edges", []),
        }
    topology = _finalization_topology(raw_topology)
    if topology is None:
        return None
    bounded: Dict[str, Any] = {
        "status": _bounded_reason(value.get("status"),) if value.get("status") not in (None, "") else "blocked",
        "repairable": value.get("repairable") is True,
        "repair_requests": [],
        "source_reference_ids": sorted({str(item)[:MAX_RESOLUTION_SOURCE_REF_ID_CHARS] for item in source_ids if isinstance(item, str)})[:MAX_FINALIZATION_SOURCE_REFERENCES],
        "canonical_location_ids": sorted({str(item)[:MAX_RESOLUTION_CANDIDATE_CHARS] for item in location_ids if isinstance(item, str)})[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
        "authored_target_ids": sorted({str(item)[:MAX_RESOLUTION_CANDIDATE_CHARS] for item in authored_ids if isinstance(item, str)})[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
        "approved_monster_ids": sorted({str(item)[:MAX_RESOLUTION_CANDIDATE_CHARS] for item in monster_ids if isinstance(item, str)})[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
        "approved_monster_identities": sorted({str(item)[:MAX_FINALIZATION_MONSTER_IDENTITY_CHARS] for item in approved_identities if isinstance(item, str)})[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
        "monster_reference_keys": sorted({str(item)[:MAX_FINALIZATION_MONSTER_REFERENCE_CHARS] for item in reference_keys if isinstance(item, str)})[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
        "quantity_bounds": value.get("quantity_bounds") if isinstance(value.get("quantity_bounds"), Mapping) else {},
        "topology": {
            "location_ids": sorted(topology["location_ids"])[:MAX_RESOLUTION_TOPOLOGY_LOCATIONS],
            "edges": [list(edge) for edge in sorted(topology["edges"])[:MAX_RESOLUTION_TOPOLOGY_EDGES]],
        },
    }
    for item in value.get("repair_requests", [])[:MAX_FINALIZATION_DIAGNOSTICS]:
        if not isinstance(item, Mapping):
            continue
        row: Dict[str, Any] = {}
        if item.get("code"):
            row["code"] = _bounded_reason(item.get("code"))
        if item.get("operation") == RESOLUTION_OPERATION:
            row["operation"] = RESOLUTION_OPERATION
        if item.get("phrase"):
            row["phrase"] = _resolution_ascii(item.get("phrase"), MAX_RESOLUTION_PHRASE_CHARS)
        if item.get("blocker"):
            row["blocker"] = _bounded_reason(item.get("blocker"))
        if row:
            bounded["repair_requests"].append(row)
    phrase = value.get("ambiguous_phrase")
    if not phrase:
        for item in bounded["repair_requests"]:
            if item.get("operation") == RESOLUTION_OPERATION and item.get("phrase"):
                phrase = item["phrase"]
                break
    if phrase:
        bounded["ambiguous_phrase"] = _resolution_ascii(phrase, MAX_RESOLUTION_PHRASE_CHARS)
    candidates = value.get("candidates")
    if isinstance(candidates, (list, tuple)):
        rows = []
        for item in candidates[:MAX_REPAIR_CANDIDATES]:
            if not isinstance(item, Mapping):
                continue
            candidate_id = _resolution_ascii(item.get("id") or item.get("location_id"), MAX_RESOLUTION_CANDIDATE_CHARS)
            name = _resolution_ascii(item.get("name") or item.get("display_name"), MAX_RESOLUTION_CANDIDATE_CHARS)
            area_id = _resolution_ascii(item.get("area_id"), 96)
            if candidate_id and name:
                rows.append({"id": candidate_id, "name": name, "area_id": area_id})
        if rows:
            bounded["candidates"] = rows
    references = value.get("source_references")
    if isinstance(references, (list, tuple)):
        rows = []
        for item in references[:MAX_REPAIR_SOURCE_REFS]:
            if not isinstance(item, Mapping):
                continue
            ref_id = _resolution_ascii(item.get("id") or item.get("ref_id"), MAX_REPAIR_SOURCE_REF_ID_CHARS)
            excerpt = _resolution_ascii(item.get("excerpt"), MAX_REPAIR_SOURCE_EXCERPT_CHARS)
            if ref_id and excerpt:
                rows.append({"id": ref_id, "excerpt": excerpt})
        if rows:
            bounded["source_references"] = rows
    for field in ("allowed_operations", "confidence_threshold", "operation_budget", "timeout_seconds"):
        if field in value:
            bounded[field] = deepcopy(value[field])
    return bounded


def _apply_destination_alias_to_staging_file(
    staging_path: Path,
    operation: Mapping[str, Any],
    expected_identity: Mapping[str, Any],
    *,
    strict_resolution: bool = False,
) -> Dict[str, Any]:
    """Apply one accepted alias atomically to the staging context only."""
    context_path = staging_path / "module_context.json"
    context = safe_read_json(str(context_path))
    if not isinstance(context, dict):
        return {"status": "rejected", "reason_code": "module_context_missing"}
    authority = context.get("semantic_authority")
    if not isinstance(authority, dict) or authority.get("attempt") != dict(expected_identity):
        return {"status": "rejected", "reason_code": "semantic_authority_identity_mismatch"}
    target = operation.get("target")
    if not isinstance(target, Mapping):
        return {"status": "rejected", "reason_code": "destination_target_missing"}
    phrase = _finalization_text(target.get("phrase"), 160)
    location_id = target.get("location_id")
    if not phrase or not isinstance(location_id, str):
        return {"status": "rejected", "reason_code": "destination_target_invalid"}
    # The production corrective seam accepts only area-scoped canonical IDs.
    # A raw/local ID is ambiguous when more than one area uses the same local
    # location key and must never be guessed here.
    if strict_resolution and (":" not in location_id or ":" not in str(target.get("origin_location_id") or location_id)):
        return {"status": "rejected", "reason_code": "destination_target_not_area_scoped"}
    current_authority = updated_authority = authority
    location_index = current_authority.get("location_index")
    if strict_resolution and (not isinstance(location_index, Mapping) or location_id not in location_index):
        return {"status": "rejected", "reason_code": "destination_target_not_current"}
    candidate_aliases = current_authority.get("location_aliases")
    if strict_resolution and not isinstance(candidate_aliases, Mapping):
        return {"status": "rejected", "reason_code": "destination_alias_authority_missing"}
    if not isinstance(candidate_aliases, Mapping):
        candidate_aliases = {}
    normalized_phrase = _normalize_phrase(phrase)
    alias_record = candidate_aliases.get(normalized_phrase) or candidate_aliases.get(phrase)
    candidate_ids = alias_record.get("candidate_internal_location_ids", []) if isinstance(alias_record, Mapping) else []
    if strict_resolution and location_id not in candidate_ids:
        return {"status": "rejected", "reason_code": "destination_target_not_authority_candidate"}
    input_hash = _stable_hash(context)
    updated = deepcopy(context)
    updated_authority = updated["semantic_authority"]
    phrases = updated_authority.setdefault("destination_phrases", {})
    phrases[phrase] = {
        "status": "resolved",
        "location_id": location_id,
        "candidate_location_ids": [location_id],
        "sources": list(operation.get("source_references", []))[:MAX_FINALIZATION_SOURCE_REFERENCES],
        "player_facing": True,
        "observed": True,
        "finalization_provenance": "accepted_python_validated_operation",
    }
    diagnostics = updated_authority.setdefault("diagnostics", {})
    normalized_phrase = _normalize_phrase(phrase)
    for key in ("ambiguous_destination_phrases", "unresolved_destination_phrases"):
        rows = diagnostics.get(key)
        if isinstance(rows, list):
            diagnostics[key] = [
                row for row in rows
                if _normalize_phrase(row.get("phrase") if isinstance(row, Mapping) else row) != normalized_phrase
            ]
    repairs = updated_authority.setdefault("finalization_repairs", [])
    if not isinstance(repairs, list):
        repairs = []
        updated_authority["finalization_repairs"] = repairs
    repairs.append({
        "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
        "phrase": phrase,
        "location_id": location_id,
        "source_references": list(operation.get("source_references", []))[:MAX_FINALIZATION_SOURCE_REFERENCES],
        "identity": dict(expected_identity),
        "input_hash": input_hash,
    })
    updated_authority["finalization_repairs"] = repairs[-MAX_FINALIZATION_DIAGNOSTICS:]
    summary = updated_authority.setdefault("summary", {})
    if isinstance(summary, dict):
        try:
            summary["ambiguous_destination_count"] = max(0, int(summary.get("ambiguous_destination_count", 0) or 0) - 1)
        except (TypeError, ValueError):
            summary["ambiguous_destination_count"] = 0
        summary["accepted_finalization_repair_count"] = len(updated_authority["finalization_repairs"])
    provenance = updated_authority.setdefault("adaptation_provenance", {})
    accepted = []
    if isinstance(provenance, dict):
        accepted = provenance.setdefault("accepted_finalization_repairs", [])
        if not isinstance(accepted, list):
            accepted = []
            provenance["accepted_finalization_repairs"] = accepted
        accepted.append({
            "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
            "phrase": phrase,
            "location_id": location_id,
            "source_references": list(operation.get("source_references", []))[:MAX_FINALIZATION_SOURCE_REFERENCES],
            "identity": dict(expected_identity),
            "input_hash": input_hash,
        })
        provenance["accepted_finalization_repairs"] = accepted[-MAX_FINALIZATION_DIAGNOSTICS:]
    output_hash = _stable_hash(updated)
    provenance_hash = _stable_hash({
        "operation": FINALIZATION_OPERATION_DESTINATION_ALIAS,
        "phrase": phrase, "location_id": location_id,
        "identity": dict(expected_identity), "input_hash": input_hash,
        "output_hash": output_hash,
    })
    repairs[-1]["output_hash"] = output_hash
    repairs[-1]["provenance_hash"] = provenance_hash
    if accepted:
        accepted[-1]["output_hash"] = output_hash
        accepted[-1]["provenance_hash"] = provenance_hash
    if not safe_write_json(str(context_path), updated, create_backup=False):
        return {"status": "rejected", "reason_code": "module_context_write_failed"}
    return {
        "status": "applied", "path": "module_context.json", "phrase": phrase,
        "location_id": location_id, "input_hash": input_hash,
        "output_hash": output_hash, "provenance_hash": provenance_hash,
    }


def apply_validated_adaptation_finalization_operation(
    staging_path: Path,
    operation: Mapping[str, Any],
    expected_identity: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply an already Python-validated operation to staging only."""
    if operation.get("operation") != FINALIZATION_OPERATION_DESTINATION_ALIAS:
        return {"status": "not_required", "reason_code": "operation_not_staging_applied"}
    return _apply_destination_alias_to_staging_file(staging_path, operation, expected_identity)


def validate_adaptation_finalization_proposal(
    proposal: Any,
    *,
    mode: str = BUILD_MODE_LLM_ADAPTATION,
    current_identity: Mapping[str, Any],
    source_reference_ids: Any,
    canonical_location_ids: Any = (),
    topology: Any = None,
    authored_target_ids: Any = (),
    approved_monster_ids: Any = (),
    approved_monster_identities: Any = None,
    monster_reference_keys: Any = (),
    quantity_bounds: Any = None,
    confidence_threshold: float = FINALIZATION_CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """Validate one injected finalization proposal without provider or I/O.

    The returned ``operation`` is a Python-owned, path-free description.  No
    LLM-selected path, structural field, identity, or live artifact is ever
    accepted by this boundary.
    """
    if mode != BUILD_MODE_LLM_ADAPTATION:
        return {
            "valid": False,
            "status": "not_applicable",
            "operation": None,
            "diagnostics": [_finalization_diag("legacy_mode", "finalization proposal is adaptation-only")],
        }
    diagnostics: list[Dict[str, str]] = []
    if not isinstance(proposal, Mapping):
        return {"valid": False, "status": "rejected", "operation": None, "diagnostics": [_finalization_diag("proposal_shape_invalid", "proposal must be an object")]}
    operation = proposal.get("operation")
    if operation not in FINALIZATION_OPERATIONS:
        diagnostics.append(_finalization_diag("operation_not_allowlisted", "operation is not allowlisted", "operation"))
        return {"valid": False, "status": "rejected", "operation": None, "diagnostics": diagnostics}
    if proposal.get("contract_version") not in (None, FINALIZATION_CONTRACT_VERSION):
        diagnostics.append(_finalization_diag("contract_version_invalid", "proposal contract version is unsupported", "contract_version"))
    unexpected = set(proposal) - _FINALIZATION_FIELDS[operation]
    if unexpected:
        diagnostics.extend(_finalization_diag("unknown_proposal_field", "proposal contains an extraneous field", str(key)) for key in sorted(unexpected))
    identity = _finalization_identity(proposal.get("identity"))
    expected = _finalization_identity(current_identity)
    if identity is None or expected is None:
        diagnostics.append(_finalization_diag("identity_invalid", "attempt identity is malformed", "identity"))
    elif identity != expected:
        diagnostics.append(_finalization_diag("identity_mismatch", "proposal is not for the current attempt and revision", "identity"))
    try:
        threshold = float(confidence_threshold)
    except (TypeError, ValueError):
        threshold = FINALIZATION_CONFIDENCE_THRESHOLD
    confidence = proposal.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or confidence < threshold or confidence > 1:
        diagnostics.append(_finalization_diag("confidence_below_threshold", "proposal confidence is below the required threshold", "confidence"))
    refs = proposal.get("source_references")
    allowed_refs = set(source_reference_ids) if isinstance(source_reference_ids, (list, tuple, set, frozenset)) else set()
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_FINALIZATION_SOURCE_REFERENCES or not all(isinstance(ref, str) and ref in allowed_refs for ref in refs):
        diagnostics.append(_finalization_diag("source_evidence_invalid", "source references must belong to the request context", "source_references"))
    target = proposal.get("target")
    target_fields = {"location_id", "origin_location_id", "phrase", "target_id", "target_type", "field", "monster_id"}
    if operation == FINALIZATION_OPERATION_MONSTER_REFERENCE:
        target_fields = {"reference_key", "canonical_identity"}
    if not isinstance(target, Mapping) or set(target) - target_fields:
        diagnostics.append(_finalization_diag("target_invalid", "target is not a canonical, allowlisted target", "target"))
        target = {}
    canonical_locations = set(canonical_location_ids) if isinstance(canonical_location_ids, (list, tuple, set, frozenset)) else set()
    topo = _finalization_topology(topology) if topology is not None else None
    if topo is None and operation in {FINALIZATION_OPERATION_DESTINATION_ALIAS, FINALIZATION_OPERATION_NARRATIVE_COMPLETION}:
        diagnostics.append(_finalization_diag("topology_invalid", "topology context is required and malformed", "topology"))
    if operation == FINALIZATION_OPERATION_DESTINATION_ALIAS:
        location_id = target.get("location_id")
        phrase = _finalization_text(target.get("phrase"), 160)
        replacement = _finalization_text(proposal.get("replacement"), 160)
        if not isinstance(location_id, str) or location_id not in canonical_locations or not phrase or replacement != location_id:
            diagnostics.append(_finalization_diag("canonical_destination_invalid", "destination alias must resolve to one canonical location", "target"))
        elif location_id not in topo["location_ids"]:
            diagnostics.append(_finalization_diag("topology_destination_invalid", "destination is absent from current topology", "target.location_id"))
        elif target.get("origin_location_id") and tuple(sorted((target["origin_location_id"], location_id))) not in topo["edges"]:
            diagnostics.append(_finalization_diag("topology_edge_invalid", "destination is not compatible with current topology", "target.origin_location_id"))
    elif operation == FINALIZATION_OPERATION_NARRATIVE_COMPLETION:
        target_id = target.get("target_id")
        field = target.get("field")
        replacement = _finalization_text(proposal.get("replacement"))
        if target_id not in set(authored_target_ids) or field not in {"description", "dmInstructions", "adventureSummary"} or replacement is None:
            diagnostics.append(_finalization_diag("authored_target_invalid", "narrative completion requires an authored target and bounded field", "target"))
    elif operation == FINALIZATION_OPERATION_MONSTER_REFERENCE:
        if proposal.get("contract_version") != FINALIZATION_CONTRACT_VERSION:
            diagnostics.append(_finalization_diag("contract_version_required", "monster resolution requires the finalization contract version", "contract_version"))
        allowed_identities = approved_monster_identities
        if allowed_identities is None:
            allowed_identities = approved_monster_ids
        approved = {
            item for item in allowed_identities
            if isinstance(item, str) and item and len(item) <= MAX_FINALIZATION_MONSTER_IDENTITY_CHARS
        } if isinstance(allowed_identities, (list, tuple, set, frozenset)) else set()
        reference_keys = {
            item for item in monster_reference_keys
            if isinstance(item, str) and item and len(item) <= MAX_FINALIZATION_MONSTER_REFERENCE_CHARS
        } if isinstance(monster_reference_keys, (list, tuple, set, frozenset)) else set()
        reference_key = target.get("reference_key")
        canonical_identity = target.get("canonical_identity")
        target_allowed = {"reference_key", "canonical_identity"}
        if set(target) != target_allowed:
            diagnostics.append(_finalization_diag("monster_target_fields_invalid", "monster resolution target fields are exact and path-free", "target"))
        if not isinstance(reference_key, str) or not reference_key.strip() or len(reference_key) > MAX_FINALIZATION_MONSTER_REFERENCE_CHARS or reference_key not in reference_keys:
            diagnostics.append(_finalization_diag("monster_reference_not_approved", "target reference is not a Python-owned registry key", "target.reference_key"))
        if not isinstance(canonical_identity, str) or not canonical_identity.strip() or len(canonical_identity) > MAX_FINALIZATION_MONSTER_IDENTITY_CHARS or canonical_identity not in approved:
            diagnostics.append(_finalization_diag("monster_identity_not_approved", "canonical monster identity is not approved", "target.canonical_identity"))
        resolution_code = proposal.get("resolution_code")
        if resolution_code not in FINALIZATION_MONSTER_RESOLUTION_CODES:
            diagnostics.append(_finalization_diag("monster_resolution_code_invalid", "monster resolution code is not allowlisted", "resolution_code"))
        quantity = proposal.get("quantity_confirmation")
        if quantity is not None:
            if not isinstance(quantity, Mapping) or set(quantity) - {"confirmed", "min", "max"}:
                diagnostics.append(_finalization_diag("monster_quantity_invalid", "quantity confirmation fields are not allowlisted", "quantity_confirmation"))
            else:
                confirmed = quantity.get("confirmed")
                minimum = quantity.get("min")
                maximum = quantity.get("max")
                values = (confirmed, minimum, maximum)
                if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FINALIZATION_MONSTER_QUANTITY for value in values):
                    diagnostics.append(_finalization_diag("monster_quantity_bounds_invalid", "quantity confirmation is outside bounded integer limits", "quantity_confirmation"))
                elif minimum > maximum or not minimum <= confirmed <= maximum:
                    diagnostics.append(_finalization_diag("monster_quantity_bounds_invalid", "confirmed quantity is outside its declared bounds", "quantity_confirmation"))
                expected_bounds = None
                if isinstance(quantity_bounds, Mapping):
                    if reference_key in quantity_bounds and isinstance(quantity_bounds.get(reference_key), Mapping):
                        expected_bounds = quantity_bounds[reference_key]
                    elif {"min", "max"}.issubset(quantity_bounds):
                        expected_bounds = quantity_bounds
                if expected_bounds is not None and (
                    expected_bounds.get("min") != minimum or expected_bounds.get("max") != maximum
                ):
                    diagnostics.append(_finalization_diag("monster_quantity_context_mismatch", "quantity bounds do not match Python context", "quantity_confirmation"))
    else:
        monster_id = target.get("monster_id") or target.get("target_id")
        if monster_id not in set(approved_monster_ids) or set(target) - {"monster_id"}:
            diagnostics.append(_finalization_diag("monster_identity_not_approved", "stat completion requires an already approved monster identity", "target"))
    if unexpected:
        diagnostics.append(_finalization_diag("structural_edit_rejected", "arbitrary paths and structural edits are forbidden"))
    if diagnostics:
        return {"valid": False, "status": "rejected", "operation": None, "diagnostics": diagnostics[:MAX_FINALIZATION_DIAGNOSTICS]}
    normalized = {"contract_version": FINALIZATION_CONTRACT_VERSION, "operation": operation, "identity": deepcopy(dict(identity)), "target": deepcopy(dict(target)), "source_references": list(refs), "confidence": float(confidence)}
    if "topology" in proposal:
        normalized["topology"] = deepcopy(dict(proposal["topology"]))
    if "replacement" in proposal:
        normalized["replacement"] = proposal["replacement"]
    if operation == FINALIZATION_OPERATION_MONSTER_REFERENCE:
        normalized["resolution_code"] = proposal["resolution_code"]
        if "quantity_confirmation" in proposal:
            normalized["quantity_confirmation"] = deepcopy(dict(proposal["quantity_confirmation"]))
    return {"valid": True, "status": "accepted", "operation": normalized, "diagnostics": []}


def apply_adaptation_finalization_proposal(
    staging: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    mode: str = BUILD_MODE_LLM_ADAPTATION,
) -> Dict[str, Any]:
    """Apply an accepted operation to an injected staging dict only.

    This helper has no path or file arguments.  It returns a copy and records
    stat requests as metadata; it never changes module identity or structure.
    """
    if not isinstance(staging, Mapping) or not isinstance(operation, Mapping):
        raise ValueError("staging and operation must be objects")
    result = deepcopy(dict(staging))
    if mode != BUILD_MODE_LLM_ADAPTATION:
        return result
    validated = validate_adaptation_finalization_proposal(
        operation,
        mode=BUILD_MODE_LLM_ADAPTATION,
        current_identity=operation.get("identity", {}),
        source_reference_ids=operation.get("source_references", []),
        canonical_location_ids=(operation.get("target", {}).get("location_id"),),
        topology={"location_ids": [operation.get("target", {}).get("location_id")], "edges": []},
        authored_target_ids=(operation.get("target", {}).get("target_id"),),
        approved_monster_ids=(operation.get("target", {}).get("monster_id"),),
        approved_monster_identities=(operation.get("target", {}).get("canonical_identity"),),
        monster_reference_keys=(operation.get("target", {}).get("reference_key"),),
    )
    if not validated.get("valid"):
        raise ValueError("operation is not valid")
    op = validated["operation"]
    if op["operation"] == FINALIZATION_OPERATION_DESTINATION_ALIAS:
        authority = result.setdefault("semantic_authority", {})
        phrases = authority.setdefault("destination_phrases", {})
        phrases[op["target"]["phrase"]] = {"status": "resolved", "location_id": op["target"]["location_id"], "sources": op["source_references"]}
    elif op["operation"] == FINALIZATION_OPERATION_NARRATIVE_COMPLETION:
        result.setdefault("narrative_completions", []).append(op)
    elif op["operation"] == FINALIZATION_OPERATION_MONSTER_REFERENCE:
        result.setdefault("monster_resolution_requests", []).append(op)
    else:
        result.setdefault("stat_completion_requests", []).append(op)
    return result


def _result(
    status: str,
    reason_code: str,
    config: AdaptationConvergenceConfig,
    *,
    target: Optional[Mapping[str, Any]] = None,
    report_path: Optional[str] = None,
    next_revision_eligible: bool = False,
    current_attempt: int = 0,
    operation_name: Optional[str] = None,
    accepted_operation: Optional[Mapping[str, Any]] = None,
    provider_failure_class: Optional[str] = None,
    diagnostics: Any = (),
    proposal_input_hash: Optional[str] = None,
    accepted_output_hash: Optional[str] = None,
    provenance_hash: Optional[str] = None,
) -> AdaptationConvergenceResult:
    return AdaptationConvergenceResult(
        status=status,
        reason_code=_bounded_reason(reason_code),
        attempt_id=target.get("attempt_id") if target else None,
        attempt_number=target.get("attempt_number") if target else None,
        revision_number=target.get("revision_number") if target else None,
        report_path=report_path,
        next_revision_eligible=next_revision_eligible,
        max_attempts=config.max_attempts,
        max_operations_per_round=config.max_operations_per_round,
        operation_timeout_seconds=config.operation_timeout_seconds,
        current_attempt=current_attempt,
        operation_name=_safe_operation_name(operation_name),
        accepted_operation=deepcopy(dict(accepted_operation)) if isinstance(accepted_operation, Mapping) else None,
        provider_failure_class=provider_failure_class if provider_failure_class in VALID_PROVIDER_FAILURE_CLASSES else None,
        diagnostics=_bounded_diagnostics(diagnostics),
        proposal_input_hash=proposal_input_hash if _is_sha256(proposal_input_hash) else None,
        accepted_output_hash=accepted_output_hash if _is_sha256(accepted_output_hash) else None,
        provenance_hash=provenance_hash if _is_sha256(provenance_hash) else None,
        source_hash=(target.get("source_hash") if target and _is_sha256(target.get("source_hash")) else None),
    )


def _write_report(
    target_path: Path,
    result: AdaptationConvergenceResult,
    *,
    repo_root: Optional[Path] = None,
) -> str:
    report_file = target_path / CONVERGENCE_REPORT_FILENAME
    try:
        report_path = report_file.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        report_path = CONVERGENCE_REPORT_FILENAME
    report = AdaptationConvergenceResult(
        **{**result.__dict__, "report_path": report_path}
    ).as_dict()
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not safe_write_json(str(report_file), report, create_backup=False):
        raise OSError("convergence report could not be persisted")
    return report_path


def _revalidate_staging_target_after_callback(
    path: Path,
    target: Mapping[str, Any],
    *,
    repo_root: Optional[Path],
) -> Dict[str, Any]:
    """Re-read and compare staging identity after the callback returns."""
    metadata_path = path / STAGING_METADATA_FILENAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    current = validate_adaptation_staging_target(
        metadata,
        source_hash=target.get("source_hash"),
        attempt_id=target.get("attempt_id"),
        attempt_number=target.get("attempt_number"),
        revision_number=target.get("revision_number"),
        module_slug=target.get("module_slug", ""),
        repo_root=repo_root,
        require_reserved=False,
    )
    # ``validate_adaptation_staging_target`` already checks every identity
    # field against the expected values and rejects unsafe path derivations.
    # Do not compare the normalized mapping wholesale: staging lifecycle
    # metadata may legitimately gain bounded bookkeeping fields while the
    # callback is running.
    return current


def validate_adaptation_publication_continuation(
    *,
    staging_target: Mapping[str, Any],
    build_result: Mapping[str, Any],
    attempt_report: Mapping[str, Any],
    semantic_authority: Mapping[str, Any],
    convergence_result: Mapping[str, Any],
    gate_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Authorize the handoff from staged gates to the finisher.

    This is a deliberately strict, provider-free join across the artifacts
    produced by one adaptation attempt.  A passing status from any single
    report is insufficient: every identity-bearing report and every hard gate
    must describe the same staging revision and source digest.
    """
    identity_fields = ("attempt_id", "attempt_number", "revision_number", "source_hash")
    expected = {key: staging_target.get(key) for key in identity_fields}
    blockers: list[str] = []

    def attempt_report_identity(value: Any) -> Optional[Dict[str, Any]]:
        """Normalize the build-result artifact's documented identity envelope.

        Build-result artifacts keep the source digest in both the provenance
        envelope and ``payload.source_ref``; unlike the staging/convergence
        projections, the artifact schema does not duplicate it at the root.
        Accept either documented nested location only when every supplied
        digest is a valid, identical SHA-256 value.  A missing or conflicting
        digest remains a hard identity failure.
        """
        if not isinstance(value, Mapping):
            return None
        provenance = value.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        payload = value.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        source_ref = payload.get("source_ref")
        source_ref = source_ref if isinstance(source_ref, Mapping) else {}
        hashes = [
            value.get("source_hash"),
            provenance.get("source_hash"),
            source_ref.get("sha256"),
        ]
        supplied = [item for item in hashes if item not in (None, "")]
        if not supplied or any(not _is_sha256(item) for item in supplied):
            return None
        if len(set(supplied)) != 1:
            return None
        identity = {key: value.get(key) for key in identity_fields}
        identity["source_hash"] = supplied[0]
        return identity

    def compare(label: str, value: Any) -> None:
        if not isinstance(value, Mapping):
            blockers.append(label + "_missing")
            return
        actual = (
            attempt_report_identity(value)
            if label == "attempt_report"
            else {key: value.get(key) for key in identity_fields}
        )
        if actual is None or actual != expected:
            blockers.append(label + "_identity_mismatch")

    compare("staging_target", staging_target)
    compare("attempt_report", attempt_report)
    compare("convergence_result", convergence_result)
    compare("semantic_authority", semantic_authority.get("attempt"))

    if build_result.get("status") != "success":
        blockers.append("build_result_not_success")
    if not isinstance(gate_result, Mapping):
        blockers.append("gate_result_missing")
    else:
        provenance = gate_result.get("provenance")
        compare("gate_result", provenance)
        if gate_result.get("status") != "pass":
            blockers.append("gate_composition_not_passing")
        if gate_result.get("playable_status") != "pass":
            blockers.append("playable_status_not_passing")
        if gate_result.get("publishable_status") != "pass":
            blockers.append("publishable_status_not_passing")
        if gate_result.get("candidate_eligible") is not True:
            blockers.append("candidate_not_eligible")
        gates = gate_result.get("gates")
        required_domains = (
            "schema", "readiness", "mechanical_closure", "semantic_authority",
            "semantic_probes", "report_agreement",
        )
        if not isinstance(gates, Mapping):
            blockers.append("hard_gate_reports_missing")
        else:
            for domain in required_domains:
                report = gates.get(domain)
                if not isinstance(report, Mapping):
                    blockers.append("hard_gate_missing:" + domain)
                elif report.get("effective_status", report.get("status")) != "pass":
                    blockers.append("hard_gate_not_passing:" + domain)
            agreement = gates.get("report_agreement")
            if isinstance(agreement, Mapping):
                adaptation_agreement = agreement.get("adaptation_report_agreement")
                if isinstance(adaptation_agreement, Mapping) and adaptation_agreement.get("status") != "pass":
                    blockers.append("adaptation_report_agreement_not_passing")

    if convergence_result.get("status") != "ready":
        blockers.append("convergence_not_ready")
    report_path = convergence_result.get("report_path")
    if not isinstance(report_path, str) or not report_path.strip():
        blockers.append("convergence_report_missing")

    # The semantic authority must be the current adaptation payload, not merely
    # an identity-shaped object supplied by a caller.
    if semantic_authority.get("adaptation_provenance", {}).get("source_hash") != expected["source_hash"]:
        blockers.append("semantic_authority_source_hash_mismatch")
    unique = list(dict.fromkeys(blockers))
    return {
        "allowed": not unique,
        "status": "allowed" if not unique else "blocked",
        "reason_code": "publication_inputs_agree" if not unique else "publication_inputs_disagree",
        "identity": expected,
        "blockers": unique[:MAX_FINALIZATION_DIAGNOSTICS],
    }


def _callback_identity_matches_target(
    callback_result: Mapping[str, Any],
    target: Mapping[str, Any],
) -> bool:
    """Require identity on production results while preserving generic success."""
    identity_fields = ("attempt_id", "attempt_number", "revision_number", "source_hash")
    identity_source: Mapping[str, Any] = callback_result
    proposal = callback_result.get("proposal")
    if (
        not any(field in callback_result for field in identity_fields)
        and isinstance(proposal, Mapping)
        and isinstance(proposal.get("identity"), Mapping)
    ):
        identity_source = proposal["identity"]
    present = [field for field in identity_fields if field in identity_source]
    if not present:
        if callback_result.get("status") not in {"success", "accepted"}:
            return True
        return (
            callback_result.get("status") == "success"
            and not callback_result.get("reason_code")
            and not isinstance(callback_result.get("proposal"), Mapping)
            and not isinstance(callback_result.get("operation"), Mapping)
        )
    if len(present) != len(identity_fields):
        return False
    if any(identity_source.get(field) != target.get(field) for field in identity_fields):
        return False
    staging_identity = callback_result.get("staging_identity")
    if not isinstance(staging_identity, Mapping):
        return False
    expected = {
        key: target.get(key)
        for key in ("stage_id", "module_slug", "path", "output_directory")
    }
    return all(staging_identity.get(key) == value for key, value in expected.items())


def _run_adaptation_publication_convergence(
    staged_module_path: str,
    *,
    mode: str,
    attempt_id: str,
    attempt_number: int,
    revision_number: int,
    source_hash: str,
    current_attempt: int = 0,
    config: Optional[AdaptationConvergenceConfig] = None,
    provider_callback: Optional[ProviderCallback] = None,
    validation_context: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run one bounded, adaptation-only finalization orchestration round.

    Preconditions are checked before the callback and before any report write.
    A valid staging target may receive only the convergence report; module
    content and live module paths are never copied or modified here.
    """
    budget = config or AdaptationConvergenceConfig()
    if mode != BUILD_MODE_LLM_ADAPTATION:
        return _result("not_applicable", "legacy_mode", budget).as_dict()

    if not _is_sha256(source_hash):
        return _result("blocked", "source_provenance_invalid", budget).as_dict()
    if isinstance(current_attempt, bool) or not isinstance(current_attempt, int) or current_attempt < 0:
        return _result("blocked", "attempt_budget_invalid", budget).as_dict()
    if current_attempt >= budget.max_attempts:
        return _result("budget_exhausted", "finalization_attempt_budget_exhausted", budget, current_attempt=current_attempt).as_dict()

    path = Path(staged_module_path)
    try:
        metadata_path = path / STAGING_METADATA_FILENAME
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("completion_state") not in {STAGING_STATE_RESERVED, STAGING_STATE_BUILDING}:
            # The staging helper validates identity before rejecting reuse when
            # require_reserved is true.  Distinguish a valid terminal marker
            # from a stale or mismatched one without touching the target.
            try:
                validate_adaptation_staging_target(
                    metadata,
                    source_hash=source_hash,
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    revision_number=revision_number,
                    repo_root=repo_root,
                    require_reserved=True,
                )
            except Exception as exc:
                if "already in use" not in str(exc):
                    raise
            return _result("blocked", "staging_target_terminal", budget, target=metadata).as_dict()
        target = validate_adaptation_staging_target(
            metadata,
            source_hash=source_hash,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            revision_number=revision_number,
            repo_root=repo_root,
            require_reserved=False,
        )
        if target.get("completion_state") not in {STAGING_STATE_RESERVED, STAGING_STATE_BUILDING}:
            return _result("blocked", "staging_target_terminal", budget, target=target).as_dict()
        if not path.is_dir() or path.is_symlink():
            return _result("blocked", "staging_path_unsafe", budget).as_dict()
        expected_path = (Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[1]) / target["path"]
        if path.resolve() != expected_path.resolve():
            return _result("blocked", "staging_path_unsafe", budget).as_dict()
    except Exception:
        return _result("blocked", "staging_target_invalid_or_mismatched", budget).as_dict()

    bounded_validation_context = _bounded_finalization_validation_context(validation_context)
    identity_boundary_failed = False
    if provider_callback is None:
        result = _result("blocked", "finalization_callback_missing", budget, target=target, current_attempt=current_attempt)
    else:
        callback_context = {
            "contract_version": CONVERGENCE_CONTRACT_VERSION,
            "attempt_id": target["attempt_id"],
            "attempt_number": target["attempt_number"],
            "revision_number": target["revision_number"],
            "source_hash": target["source_hash"],
            "staging_identity": {
                "stage_id": target.get("stage_id"),
                "module_slug": target.get("module_slug", ""),
                "path": target.get("path"),
                "output_directory": target.get("output_directory"),
            },
            "budget": {
                "current_attempt": current_attempt,
                "max_attempts": budget.max_attempts,
                "max_operations_per_round": budget.max_operations_per_round,
                "operation_timeout_seconds": budget.operation_timeout_seconds,
            },
        }
        if validation_context is not None:
            callback_validation_context = {
                key: bounded_validation_context[key]
                for key in (
                    "status", "repairable", "ambiguous_phrase", "candidates",
                    "source_references", "allowed_operations", "confidence_threshold",
                    "operation_budget", "timeout_seconds", "repair_requests", "source_reference_ids",
                    "canonical_location_ids", "authored_target_ids",
                    "approved_monster_ids", "approved_monster_identities",
                    "monster_reference_keys", "quantity_bounds", "topology",
                )
                if bounded_validation_context and key in bounded_validation_context
            }
            callback_context["validation_context"] = callback_validation_context or {"status": "invalid"}
            if callback_validation_context and callback_validation_context.get("ambiguous_phrase"):
                callback_context["request"] = {
                    "contract_version": RESOLUTION_CONTRACT_VERSION,
                    "operation": RESOLUTION_OPERATION,
                    "validation_context": deepcopy(callback_validation_context),
                }
        proposal_input_hash = _stable_hash(callback_context)
        try:
            callback_result = provider_callback(callback_context)
            metadata_revalidated = True
            try:
                _revalidate_staging_target_after_callback(
                    path, target, repo_root=repo_root
                )
            except Exception:
                metadata_revalidated = False
            if not metadata_revalidated:
                identity_boundary_failed = True
                result = _result(
                    "blocked",
                    "staging_target_changed_after_callback",
                    budget,
                    target=target,
                    current_attempt=current_attempt,
                    diagnostics=("staging_identity_changed_after_callback",),
                )
            elif not isinstance(callback_result, Mapping):
                result = _result(
                    "failed", "callback_result_invalid", budget, target=target,
                    current_attempt=current_attempt, provider_failure_class="malformed",
                    diagnostics=("callback_result_invalid",), proposal_input_hash=proposal_input_hash,
                )
            elif not _callback_identity_matches_target(callback_result, target):
                identity_boundary_failed = True
                result = _result(
                    "blocked",
                    "callback_identity_mismatched",
                    budget,
                    target=target,
                    current_attempt=current_attempt,
                    diagnostics=("callback_identity_mismatched",),
                )
            elif callback_result.get("status") in {"success", "accepted"} and (
                isinstance(callback_result.get("proposal"), Mapping)
                or isinstance(callback_result.get("operation"), Mapping)
            ):
                if bounded_validation_context is None:
                    result = _result(
                        "failed", "validation_context_missing", budget, target=target,
                        current_attempt=current_attempt, provider_failure_class="rejected",
                        diagnostics=("validation_context_missing",), proposal_input_hash=proposal_input_hash,
                    )
                else:
                    proposal = callback_result.get("proposal", callback_result.get("operation"))
                    strict_alias_context = bool(
                        bounded_validation_context.get("allowed_operations")
                        == [FINALIZATION_OPERATION_DESTINATION_ALIAS]
                    )
                    if strict_alias_context:
                        candidates = bounded_validation_context.get("candidates", [])
                        candidate_ids = {
                            item.get("id") for item in candidates
                            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
                        }
                        if (
                            operation := proposal.get("operation")
                            if isinstance(proposal, Mapping) else None
                        ) != FINALIZATION_OPERATION_DESTINATION_ALIAS:
                            result = _result(
                                "failed", "finalization_proposal_rejected", budget,
                                target=target, current_attempt=current_attempt,
                                provider_failure_class="rejected",
                                diagnostics=("operation_not_allowlisted",),
                                proposal_input_hash=proposal_input_hash,
                            )
                            proposal = None
                        elif (
                            not isinstance(proposal.get("target"), Mapping)
                            or proposal["target"].get("phrase") != bounded_validation_context.get("ambiguous_phrase")
                            or proposal["target"].get("location_id") not in candidate_ids
                            or len(candidate_ids) != len(candidates)
                            or any(":" not in str(item) for item in candidate_ids)
                            or proposal.get("source_references", []) == []
                            or proposal.get("confidence", 0) < bounded_validation_context.get("confidence_threshold", FINALIZATION_CONFIDENCE_THRESHOLD)
                        ):
                            result = _result(
                                "failed", "finalization_proposal_rejected", budget,
                                target=target, current_attempt=current_attempt,
                                provider_failure_class="rejected",
                                diagnostics=("destination_resolution_context_mismatch",),
                                proposal_input_hash=proposal_input_hash,
                            )
                            proposal = None
                    if proposal is None:
                        pass
                    else:
                        validation = validate_adaptation_finalization_proposal(
                            proposal,
                            current_identity={
                                "attempt_id": target["attempt_id"],
                                "attempt_number": target["attempt_number"],
                                "revision_number": target["revision_number"],
                                "source_hash": target["source_hash"],
                            },
                            source_reference_ids=bounded_validation_context["source_reference_ids"],
                            canonical_location_ids=bounded_validation_context["canonical_location_ids"],
                            topology=bounded_validation_context["topology"],
                            authored_target_ids=bounded_validation_context["authored_target_ids"],
                            approved_monster_ids=bounded_validation_context["approved_monster_ids"],
                            approved_monster_identities=bounded_validation_context.get("approved_monster_identities"),
                            monster_reference_keys=bounded_validation_context.get("monster_reference_keys", ()),
                            quantity_bounds=bounded_validation_context.get("quantity_bounds"),
                        )
                        if not validation.get("valid"):
                            result = _result(
                                "failed", "finalization_proposal_rejected", budget, target=target,
                                current_attempt=current_attempt, provider_failure_class="rejected",
                                diagnostics=[item.get("code") for item in validation.get("diagnostics", [])],
                                proposal_input_hash=proposal_input_hash,
                            )
                        else:
                            operation = validation["operation"]
                            apply_result = {"status": "not_required"}
                            if operation["operation"] == FINALIZATION_OPERATION_DESTINATION_ALIAS:
                                apply_result = _apply_destination_alias_to_staging_file(
                                    path, operation, {
                                        "attempt_id": target["attempt_id"],
                                        "attempt_number": target["attempt_number"],
                                        "revision_number": target["revision_number"],
                                        "source_hash": target["source_hash"],
                                    },
                                    strict_resolution=strict_alias_context,
                                )
                            if apply_result.get("status") not in {"applied", "not_required"}:
                                result = _result(
                                    "failed", str(apply_result.get("reason_code") or "finalization_apply_failed"), budget,
                                    target=target, current_attempt=current_attempt, provider_failure_class="rejected",
                                    diagnostics=(str(apply_result.get("reason_code") or "finalization_apply_failed"),),
                                    proposal_input_hash=proposal_input_hash,
                                )
                            else:
                                result = _result(
                                    "ready", "callback_proposal_accepted", budget, target=target, next_revision_eligible=True,
                                    current_attempt=current_attempt, operation_name=operation.get("operation"),
                                    accepted_operation=operation,
                                    diagnostics=("operation_applied:" + str(apply_result.get("path")),) if apply_result.get("path") else (),
                                    proposal_input_hash=proposal_input_hash,
                                    accepted_output_hash=apply_result.get("output_hash") or _stable_hash({"operation": operation, "apply": apply_result}),
                                    provenance_hash=apply_result.get("provenance_hash") or _stable_hash({"source_hash": target["source_hash"], "attempt_id": target["attempt_id"], "revision_number": target["revision_number"]}),
                                )
            elif callback_result.get("status") == "success":
                result = _result(
                    "ready", "callback_success", budget, target=target, next_revision_eligible=True,
                    current_attempt=current_attempt, operation_name=callback_result.get("operation"),
                    diagnostics=callback_result.get("diagnostics", ()), proposal_input_hash=proposal_input_hash,
                    accepted_output_hash=_stable_hash({"status": callback_result.get("status"), "operation": callback_result.get("operation")}),
                    provenance_hash=_stable_hash({"source_hash": target["source_hash"], "attempt_id": target["attempt_id"], "revision_number": target["revision_number"]}),
                )
            else:
                failure_class = _provider_failure_class(callback_result=callback_result)
                callback_failure_class = (
                    callback_result.get("failure_class")
                    if isinstance(callback_result.get("failure_class"), str)
                    else None
                )
                result = _result(
                    "failed", _bounded_reason(callback_result.get("reason_code") or "callback_failed"), budget,
                    target=target,
                    next_revision_eligible=_retry_allowed_after_callback_failure(
                        failure_class,
                        current_attempt=current_attempt,
                        budget=budget,
                        failure_class=callback_failure_class,
                    ),
                    current_attempt=current_attempt,
                    provider_failure_class=failure_class, diagnostics=callback_result.get("diagnostics", ()),
                    proposal_input_hash=proposal_input_hash,
                )
        except Exception as exc:
            failure_class = _provider_failure_class(exc=exc)
            result = _result(
                "failed", "callback_failed", budget, target=target,
                next_revision_eligible=_retry_allowed_after_callback_failure(
                    failure_class, current_attempt=current_attempt, budget=budget
                ),
                current_attempt=current_attempt, provider_failure_class=failure_class,
                diagnostics=("callback_failed",), proposal_input_hash=proposal_input_hash,
            )

    if identity_boundary_failed:
        return result.as_dict()

    try:
        report_path = _write_report(path, result, repo_root=repo_root)
        result = AdaptationConvergenceResult(**{**result.__dict__, "report_path": report_path})
    except Exception:
        result = _result("failed", "report_persist_failed", budget, target=target, next_revision_eligible=False)
    return result.as_dict()


def run_adaptation_publication_convergence(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run finalization convergence inside the adaptation-only boundary."""
    if kwargs.get("mode") != BUILD_MODE_LLM_ADAPTATION:
        return _run_adaptation_publication_convergence(*args, **kwargs)
    with AdaptationOutputSafety(
        phase="adaptation_revision", status="running", redirect_streams=True
    ):
        return _run_adaptation_publication_convergence(*args, **kwargs)


__all__ = [
    "AdaptationConvergenceConfig",
    "AdaptationConvergenceResult",
    "CONVERGENCE_CONTRACT_VERSION",
    "CONVERGENCE_REPORT_FILENAME",
    "RESOLUTION_CONTRACT_VERSION",
    "RESOLUTION_OPERATION",
    "FINALIZATION_CONTRACT_VERSION",
    "FINALIZATION_CONFIDENCE_THRESHOLD",
    "FINALIZATION_OPERATIONS",
    "FINALIZATION_OPERATION_DESTINATION_ALIAS",
    "FINALIZATION_OPERATION_NARRATIVE_COMPLETION",
    "FINALIZATION_OPERATION_STAT_COMPLETION",
    "FINALIZATION_OPERATION_MONSTER_REFERENCE",
    "prepare_adaptation_repair_context",
    "build_adaptation_resolution_request",
    "validate_adaptation_finalization_proposal",
    "apply_adaptation_finalization_proposal",
    "apply_validated_adaptation_finalization_operation",
    "validate_adaptation_publication_continuation",
    "run_adaptation_publication_convergence",
]
