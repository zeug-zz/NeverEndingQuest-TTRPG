# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free semantic authority for an adaptation staging revision.

This adapter deliberately builds on ``module_semantic_authority``.  It adds
attempt identity and source/packet evidence without changing the legacy
module enrichment contract or writing outside an adaptation staging target.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Optional

from utils.file_operations import safe_read_json, safe_write_json
from utils.module_semantic_authority import build_module_semantic_authority

MAX_BLOCKERS = 12
MAX_PROVENANCE_ROWS = 24
ADAPTATION_MODE = "llm_adaptation"
_SHA256_LENGTH = 64


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bounded_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip().encode("ascii", "replace").decode("ascii")
    return text[:limit]


def _normalize_phrase(value: Any) -> str:
    text = str(value or "").lower().replace("_", " ").replace("-", " ").replace("'", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text)).strip()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == _SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in text.lower()
    )


def _bounded_source_references(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    references: List[str] = []
    for item in value[:MAX_PROVENANCE_ROWS]:
        if not isinstance(item, str):
            continue
        reference = _bounded_text(item, 180)
        if reference and reference not in references:
            references.append(reference)
    return references


def _merge_validated_finalization_repairs(
    authority: Dict[str, Any],
    previous_authority: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    """Carry only validated alias repairs into a rebuilt authority payload.

    The authored files and source artifacts remain the authority baseline.  A
    persisted repair is eligible only when its complete identity and hash
    envelope is current and the rebuilt authority still confirms the target
    as a canonical candidate for the same alias.
    """
    previous_provenance = _mapping(previous_authority.get("adaptation_provenance"))
    records: List[Mapping[str, Any]] = []
    for collection in (
        previous_authority.get("finalization_repairs"),
        previous_provenance.get("accepted_finalization_repairs"),
    ):
        if isinstance(collection, list):
            records.extend(item for item in collection if isinstance(item, Mapping))

    location_index = _mapping(authority.get("location_index"))
    aliases = _mapping(authority.get("location_aliases"))
    diagnostics = authority.setdefault("diagnostics", {})
    if not isinstance(diagnostics, dict):
        return
    seen = set()
    accepted_records: List[Dict[str, Any]] = []
    for record in records:
        identity = record.get("identity")
        phrase = _bounded_text(record.get("phrase"), 240)
        location_id = record.get("location_id")
        source_references = _bounded_source_references(record.get("source_references"))
        if (
            record.get("operation") != "resolve_destination_alias"
            or not isinstance(identity, Mapping)
            or dict(identity) != dict(expected)
            or not phrase
            or not isinstance(location_id, str)
            or ":" not in location_id
            or not source_references
            or not _is_sha256(record.get("input_hash"))
            or not _is_sha256(record.get("output_hash"))
            or not _is_sha256(record.get("provenance_hash"))
        ):
            continue
        alias = aliases.get(_normalize_phrase(phrase))
        if not isinstance(alias, Mapping):
            continue
        candidate_ids = alias.get("candidate_internal_location_ids")
        if not isinstance(candidate_ids, list) or location_id not in candidate_ids:
            continue
        if location_id not in location_index:
            continue
        key = (_normalize_phrase(phrase), location_id)
        if key in seen:
            continue
        seen.add(key)
        resolved = deepcopy(dict(alias))
        resolved.update(
            {
                "status": "resolved",
                "location_id": location_id,
                "scoped_location_id": location_id,
                "candidate_location_ids": [location_id],
                "source_references": source_references,
                "player_facing": True,
                "observed": True,
                "finalization_provenance": "accepted_python_validated_operation",
                "input_hash": record["input_hash"],
                "output_hash": record["output_hash"],
                "provenance_hash": record["provenance_hash"],
            }
        )
        authority.setdefault("destination_phrases", {})[phrase] = resolved
        accepted_records.append(dict(record))
        normalized = _normalize_phrase(phrase)
        for key_name in ("ambiguous_destination_phrases", "unresolved_destination_phrases"):
            rows = diagnostics.get(key_name)
            if isinstance(rows, list):
                diagnostics[key_name] = [
                    row for row in rows
                    if _normalize_phrase(row.get("phrase") if isinstance(row, Mapping) else row) != normalized
                ]

    if accepted_records:
        authority["finalization_repairs"] = accepted_records[-MAX_PROVENANCE_ROWS:]
        provenance = authority.setdefault("adaptation_provenance", {})
        if isinstance(provenance, dict):
            provenance["accepted_finalization_repairs"] = accepted_records[-MAX_PROVENANCE_ROWS:]
    summary = authority.get("summary")
    if isinstance(summary, dict):
        rows = diagnostics.get("ambiguous_destination_phrases", [])
        summary["ambiguous_destination_count"] = len(rows) if isinstance(rows, list) else 0


def _identity(value: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "attempt_id": _bounded_text(value.get("attempt_id"), 96),
        "attempt_number": value.get("attempt_number"),
        "revision_number": value.get("revision_number"),
        "source_hash": _bounded_text(value.get("source_hash"), 64),
    }


def _identity_mismatch_fields(
    expected: Mapping[str, Any], manifest: Mapping[str, Any], packet: Mapping[str, Any], module_slug: str
) -> List[str]:
    """Validate the identity envelope before any authority can be persisted."""
    mismatches = _identity_mismatches(expected, manifest, packet)
    for label, evidence in (("source_manifest", manifest), ("normalized_packet", packet)):
        if not evidence:
            mismatches.append(f"{label}.missing")
        evidence_slug = str(evidence.get("module_slug") or evidence.get("module_name") or "").strip()
        if evidence_slug and evidence_slug != module_slug:
            mismatches.append(f"{label}.module_slug_mismatch")
        if not str(evidence.get("source_hash") or "").strip():
            mismatches.append(f"{label}.source_hash_missing")
    return mismatches


def _identity_mismatches(
    expected: Mapping[str, Any], manifest: Mapping[str, Any], packet: Mapping[str, Any]
) -> List[str]:
    mismatches: List[str] = []
    expected_source = str(expected.get("source_hash") or "").strip()
    for label, evidence in (("source_manifest", manifest), ("normalized_packet", packet)):
        if expected_source and evidence.get("source_hash") and str(evidence.get("source_hash")) != expected_source:
            mismatches.append(f"{label}.source_hash_mismatch")
    for field in ("attempt_id", "attempt_number", "revision_number"):
        expected_value = expected.get(field)
        if expected_value is None:
            continue
        for label, evidence in (("source_manifest", manifest), ("normalized_packet", packet)):
            if field in evidence and evidence.get(field) != expected_value:
                mismatches.append(f"{label}.{field}_mismatch")
    return mismatches


def _source_evidence(manifest: Mapping[str, Any], packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    candidates = manifest.get("location_candidates")
    if isinstance(candidates, list):
        for item in candidates[:MAX_PROVENANCE_ROWS]:
            if isinstance(item, Mapping) and item.get("name"):
                rows.append({"kind": "source_location", "name": _bounded_text(item.get("name")), "source": "source_manifest", "source_ref": _bounded_text(item.get("source_ref") or item.get("source_path") or "source_manifest", 180)})
    for key in ("source_location_names", "destination_phrases", "locations"):
        values = packet.get(key)
        if isinstance(values, list):
            for value in values[:MAX_PROVENANCE_ROWS]:
                source_ref = ""
                if isinstance(value, Mapping):
                    source_ref = value.get("source_ref") or value.get("source_path") or ""
                    value = value.get("name") or value.get("phrase") or value.get("display_name")
                if value:
                    rows.append({"kind": "packet_destination", "name": _bounded_text(value), "source": "normalized_packet", "source_ref": _bounded_text(source_ref or "normalized_packet", 180)})
    return rows[:MAX_PROVENANCE_ROWS]


def build_adaptation_semantic_authority(
    module_slug: str,
    module_dir: Path,
    *,
    attempt: Mapping[str, Any],
    source_manifest: Optional[Mapping[str, Any]] = None,
    normalized_packet: Optional[Mapping[str, Any]] = None,
    mode: str = ADAPTATION_MODE,
) -> Dict[str, Any]:
    """Build current-attempt authority, retaining bounded blockers on failure."""
    if mode != ADAPTATION_MODE:
        return {"status": "not_applicable", "semantic_authority": {}, "blockers": [], "identity": _identity(attempt), "mode": mode}
    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"
    context = safe_read_json(str(context_path))
    plot = safe_read_json(str(plot_path))
    manifest = _mapping(source_manifest)
    packet = _mapping(normalized_packet)
    previous_authority = (
        deepcopy(context.get("semantic_authority"))
        if isinstance(context.get("semantic_authority"), Mapping)
        else {}
    )
    expected = _identity(attempt)
    mismatches = _identity_mismatch_fields(expected, manifest, packet, module_slug)
    if not isinstance(context, dict):
        mismatches.append("module_context_missing")
    if not isinstance(plot, dict):
        mismatches.append("module_plot_missing")
    if mismatches:
        return {
            "status": "blocked",
            "semantic_authority": {},
            "blockers": [{"code": "stale_or_missing_authority_input", "details": mismatches[:MAX_BLOCKERS]}],
            "identity": expected,
            "mode": mode,
        }

    authority = build_module_semantic_authority(module_slug, context, plot, module_dir)
    authority = deepcopy(authority)
    authority["attempt"] = expected
    authority["adaptation_provenance"] = {
        "mode": mode,
        "module_slug": module_slug,
        "source_hash": expected["source_hash"],
        "source_manifest_evidence": [row.get("source_ref") for row in _source_evidence(manifest, {})][:MAX_PROVENANCE_ROWS],
        "normalized_packet_evidence": [row.get("source_ref") for row in _source_evidence({}, packet)][:MAX_PROVENANCE_ROWS],
    }
    authority["source_evidence"] = _source_evidence(manifest, packet)
    # Packet phrases are evidence, not a competing location model.  A phrase
    # may be promoted only when its normalized form already has one canonical
    # authored alias; otherwise it remains an explicit blocker below.
    destination_phrases = authority.setdefault("destination_phrases", {})
    for evidence in authority["source_evidence"]:
        phrase = _normalize_phrase(evidence.get("name"))
        if not phrase or phrase in destination_phrases:
            continue
        alias = authority.get("location_aliases", {}).get(phrase)
        if not isinstance(alias, Mapping):
            continue
        candidate_ids = list(
            alias.get("candidate_internal_location_ids")
            or alias.get("candidate_location_ids")
        )
        if len(candidate_ids) == 1:
            raw_location_id = list(alias.get("candidate_location_ids") or [phrase])[0]
            destination_phrases[phrase] = {
                "status": "resolved",
                "location_id": raw_location_id,
                "scoped_location_id": candidate_ids[0],
                "candidate_location_ids": list(alias.get("candidate_location_ids") or [raw_location_id]),
                "candidate_internal_location_ids": candidate_ids,
                "sources": sorted(set(alias.get("sources") or []) | {evidence.get("source", "")}),
                "observed": True,
                "player_facing": True,
                "observation_count": 1,
                }
    _merge_validated_finalization_repairs(authority, previous_authority, expected)
    diagnostics = authority.setdefault("diagnostics", {})
    missing_categories = diagnostics.setdefault("missing_authority_categories", [])
    if not authority.get("location_aliases"):
        missing_categories.append("location_aliases")
    if not authority.get("destination_phrases"):
        missing_categories.append("destination_phrases")
    if "npc_scene_authority" not in authority:
        missing_categories.append("npc_scene_authority")
    missing_categories[:] = sorted(set(missing_categories))
    blockers: List[Dict[str, Any]] = []
    for category in missing_categories[:MAX_BLOCKERS]:
        blockers.append({"code": "missing_authority_category", "category": category})
    for row in diagnostics.get("missing_npc_authority", [])[:MAX_BLOCKERS]:
        if isinstance(row, Mapping):
            blockers.append({"code": "missing_npc_scene_authority", "npc": _bounded_text(row.get("npc")), "sources": list(row.get("sources") or [])[:4]})
    for phrase in diagnostics.get("unresolved_destination_phrases", [])[:MAX_BLOCKERS]:
        if isinstance(phrase, Mapping) and phrase.get("player_facing"):
            blockers.append({"code": "unresolved_destination_phrase", "phrase": _bounded_text(phrase.get("phrase")), "sources": phrase.get("sources", [])[:4]})
    for phrase in diagnostics.get("ambiguous_destination_phrases", [])[:MAX_BLOCKERS]:
        if isinstance(phrase, Mapping) and phrase.get("player_facing"):
            blockers.append({"code": "ambiguous_destination_phrase", "phrase": _bounded_text(phrase.get("phrase")), "candidate_location_ids": phrase.get("candidate_location_ids", [])[:8]})
    return {"status": "blocked" if blockers else "success", "semantic_authority": authority, "blockers": blockers[:MAX_BLOCKERS], "identity": expected, "mode": mode}


def persist_adaptation_semantic_authority(
    module_dir: Path,
    result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Persist authority only in the supplied staging module directory."""
    authority = result.get("semantic_authority")
    if result.get("mode") != ADAPTATION_MODE:
        return {"status": "not_applicable", "reason": "legacy_or_non_adaptation_mode"}
    if not isinstance(authority, Mapping) or not authority.get("attempt"):
        return {"status": "blocked", "reason": "semantic_authority_not_current"}
    provenance = authority.get("adaptation_provenance")
    if not isinstance(provenance, Mapping) or provenance.get("mode") != ADAPTATION_MODE:
        return {"status": "blocked", "reason": "adaptation_provenance_missing"}
    context_path = module_dir / "module_context.json"
    context = safe_read_json(str(context_path))
    if not isinstance(context, dict):
        return {"status": "blocked", "reason": "module_context_missing"}
    updated = deepcopy(context)
    updated["semantic_authority"] = deepcopy(dict(authority))
    if not safe_write_json(str(context_path), updated, create_backup=False):
        return {"status": "blocked", "reason": "semantic_authority_write_failed"}
    return {"status": "persisted", "path": "module_context.json", "identity": authority.get("attempt")}
