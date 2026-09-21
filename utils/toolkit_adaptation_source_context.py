# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Source Context
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded source-context assembly for the LLM adaptation author.
Raw source, summaries, manifests, normalized packets, and source-graph atoms
are context evidence only.  They are never source locks or required dossier
output, and this utility does not persist source content or call a provider.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_dossier import VALID_SOURCE_PROFILES
from utils.toolkit_source_manifest import build_source_manifest


SOURCE_CONTEXT_VERSION = "toolkit_adaptation_source_context.v1"

# The author runner has a larger request bound, but this smaller envelope is
# intentionally kept independent so a source-context caller cannot fill the
# whole provider request with one raw upload or one extracted bucket.
MAX_SOURCE_TITLE_CHARS = 240
MAX_RAW_SOURCE_CHARS = 4_800
MAX_SOURCE_SUMMARY_CHARS = 2_800
MAX_SOURCE_SECTION_CHARS = 480
MAX_SOURCE_SECTIONS = 12
MAX_MANIFEST_ITEMS = 24
MAX_PACKET_ITEMS = 16
MAX_CONTEXT_ITEMS = 72
MAX_CONTEXT_ITEM_CHARS = 480
MAX_CONTEXT_SERIALIZED_CHARS = 16_000
MAX_DIAGNOSTICS = 24

ASSEMBLY_STATUS_READY = "ready"
ASSEMBLY_STATUS_DEGRADED = "degraded"
ASSEMBLY_STATUS_INVALID = "invalid"

CONTEXT_STATUS_AVAILABLE = "available"
CONTEXT_STATUS_REFERENCED = "referenced"
CONTEXT_STATUS_UNAVAILABLE = "unavailable"

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_SEVERITY_WARNING = "warning"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROOM_HEADING_RE = re.compile(r"^\s*#{2,4}\s+Room\s+\d+\s*:", re.IGNORECASE | re.MULTILINE)
_CREDENTIAL_RE = re.compile(
    r"(?i)(\b(?:api[_ -]?key|authorization|password|secret|token|bearer)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_PROMPT_LINE_RE = re.compile(
    r"(?im)^\s*(?:system|developer|assistant|user)[_ -]?(?:prompt|message)?\s*[:=].*$"
)

_SUMMARY_TEXT_KEYS = (
    "summary",
    "source_summary",
    "bounded_summary",
    "description",
    "adventure_summary",
)
_TITLE_KEYS = ("source_title", "title", "name")
_HASH_KEYS = ("source_hash", "sha256", "hash")
_PATH_KEYS = ("source_path", "source_ref", "path")
_PROFILE_HINT_KEYS = (
    "source_profile_hint",
    "profile_hint",
    "source_profile",
    "structure_class",
)
_UNTRUSTED_MAPPING_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "raw_prompt",
        "raw_response",
        "secret",
        "system",
        "system_prompt",
        "token",
        "user_prompt",
        "messages",
        "instructions",
    }
)

_PROFILE_GUIDANCE = {
    "adventure": (
        "Room or scene progression is optional evidence. Adapt it into a "
        "coherent NEQ adventure and add original connective material."
    ),
    "catalogue": (
        "Treat listings and item headings as optional source evidence for a "
        "shop or market frame; do not promote item headings into locations."
    ),
    "location": (
        "Treat place descriptions as optional exploration evidence and build "
        "a location-shaped module with original hooks."
    ),
    "lore": (
        "Treat history and setting material as optional lore evidence and "
        "convert selected ideas into playable scenes, people, or objects."
    ),
    "encounter": (
        "Treat set-piece conflict material as optional encounter evidence and "
        "build multiple meaningful resolution paths."
    ),
    "sandbox": (
        "Treat fragmented material as optional seeds and build an open-ended "
        "playable frame with original connective material."
    ),
}


def _ascii_text(value: Any, limit: int) -> Tuple[str, bool, int]:
    """Return sanitized text, truncation state, and sanitized source length."""
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _PROMPT_LINE_RE.sub("[redacted source instruction]", text)
    text = _CREDENTIAL_RE.sub("[redacted credential]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _OPENAI_KEY_RE.sub("[redacted]", text)
    text = "".join(char if char in "\n\t" or ord(char) >= 32 else " " for char in text)
    text = text.encode("ascii", "replace").decode("ascii").strip()
    original_length = len(text)
    if len(text) <= limit:
        return text, False, original_length
    marker = " [truncated]"
    keep = max(0, limit - len(marker))
    return text[:keep].rstrip() + marker, True, original_length


def _diagnostic(
    code: str,
    message: str,
    severity: str = DIAGNOSTIC_SEVERITY_WARNING,
) -> Dict[str, str]:
    message_text, _, _ = _ascii_text(message, MAX_CONTEXT_ITEM_CHARS)
    return {
        "code": code,
        "message": message_text,
        "severity": severity,
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _first_mapping_text(mapping: Mapping[str, Any], keys: Sequence[str]) -> Tuple[str, str]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip() and key.lower() not in _UNTRUSTED_MAPPING_KEYS:
            text, _, _ = _ascii_text(value, MAX_SOURCE_SUMMARY_CHARS)
            if text:
                return text, key
    return "", ""


def _mapping_scalar(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and key.lower() not in _UNTRUSTED_MAPPING_KEYS:
            return mapping.get(key)
    return None


def _safe_project_relative_path(value: Any) -> Tuple[Optional[str], bool]:
    """Return a project-relative path and whether the input was unsafe."""
    if value is None:
        return None, False
    if isinstance(value, Mapping):
        value = value.get("path")
    if not isinstance(value, (str, Path)):
        return None, True
    raw = str(value).strip()
    if not raw or "\x00" in raw or "\\" in raw:
        return None, True
    raw, _, _ = _ascii_text(raw, 512)

    repo_root = Path(__file__).resolve().parents[1]
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve(strict=False).relative_to(repo_root)
        except ValueError:
            return None, True
        raw = relative.as_posix()

    normalized = PurePosixPath(raw)
    if not normalized.parts or any(part in {"", ".", ".."} for part in normalized.parts):
        return None, True
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None, True
    return normalized.as_posix(), False


def _source_ref(
    source_path: Optional[str],
    source_hash: str,
    *,
    size_bytes: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    reference: Dict[str, Any] = {}
    if source_path:
        reference["path"] = source_path
    if source_hash:
        reference["sha256"] = source_hash
    if isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes >= 0:
        reference["size_bytes"] = size_bytes
    return reference or None


def _source_record(
    kind: str,
    provenance: str,
    text: str,
    source_path: Optional[str],
    source_hash: str,
    limit: int,
) -> Dict[str, Any]:
    bounded, truncated, original_chars = _ascii_text(text, limit)
    return {
        "kind": kind,
        "provenance": provenance,
        "source_hash": source_hash,
        "source_ref": _source_ref(source_path, source_hash),
        "text": bounded,
        "original_chars": original_chars,
        "included_chars": len(bounded),
        "truncated": truncated,
        "advisory": True,
    }


def _candidate_value(candidate: Mapping[str, Any]) -> Tuple[str, str]:
    for key in ("name", "cue", "phrase", "text", "title"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    return "", ""


def _candidate_summary(candidate: Mapping[str, Any]) -> str:
    for key in ("description", "context", "summary", "purpose"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _manifest_evidence(
    manifest: Mapping[str, Any],
    source_path: Optional[str],
    source_hash: str,
) -> Tuple[Dict[str, Any], int, bool]:
    """Keep typed manifest evidence without copying the raw manifest."""
    evidence: List[Dict[str, Any]] = []
    candidate_keys = (
        "location_candidates",
        "entity_candidates",
        "item_candidates",
        "encounter_candidates",
        "puzzle_candidates",
        "mechanic_candidates",
        "tone_candidates",
        "headings",
    )
    for bucket in candidate_keys:
        candidates = manifest.get(bucket, [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            value, value_key = _candidate_value(candidate)
            if not value:
                continue
            summary = _candidate_summary(candidate)
            bounded_value, value_truncated, _ = _ascii_text(value, MAX_CONTEXT_ITEM_CHARS)
            bounded_summary, summary_truncated, _ = _ascii_text(summary, MAX_CONTEXT_ITEM_CHARS)
            line_start = candidate.get("line_start")
            if not isinstance(line_start, int) or isinstance(line_start, bool) or line_start < 1:
                line_start = None
            evidence_item: Dict[str, Any] = {
                "kind": bucket[:-1] if bucket.endswith("s") else bucket,
                "value": bounded_value,
                "value_key": value_key,
                "summary": bounded_summary,
                "line_start": line_start,
                "source_hash": source_hash,
                "source_ref": _source_ref(source_path, source_hash),
                "advisory": True,
                "truncated": value_truncated or summary_truncated,
            }
            evidence.append(evidence_item)

    evidence.sort(
        key=lambda item: (
            item.get("line_start") if isinstance(item.get("line_start"), int) else 10**9,
            str(item.get("kind", "")),
            str(item.get("value", "")).lower(),
        )
    )
    original_count = len(evidence)
    truncated = original_count > MAX_MANIFEST_ITEMS
    evidence = evidence[:MAX_MANIFEST_ITEMS]

    summary = manifest.get("summary")
    counts: Dict[str, int] = {}
    if isinstance(summary, Mapping):
        for key in (
            "npc_candidates",
            "location_candidates",
            "puzzle_candidates",
            "encounter_candidates",
            "item_candidates",
            "tone_candidates",
            "total_atoms",
        ):
            value = summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                counts[key] = value

    payload = {
        "kind": "source_manifest",
        "provenance": "deterministic_source_manifest",
        "manifest_version": str(manifest.get("manifest_version") or "unknown")[:80],
        "source_hash": source_hash,
        "source_ref": _source_ref(source_path, source_hash),
        "candidate_counts": counts,
        "evidence": evidence,
        "original_items": original_count,
        "included_items": len(evidence),
        "truncated": truncated,
        "advisory": True,
    }
    return payload, original_count, truncated


def _compact_packet_item(value: Any) -> Any:
    if isinstance(value, str):
        text, _, _ = _ascii_text(value, MAX_CONTEXT_ITEM_CHARS)
        return text
    if not isinstance(value, Mapping):
        return None
    allowed = (
        "name",
        "title",
        "purpose",
        "description",
        "summary",
        "setup",
        "stakes",
        "role",
        "location",
        "category",
        "connections",
        "adversaries",
        "source_basis",
    )
    result: Dict[str, Any] = {}
    for key in allowed:
        if key.lower() in _UNTRUSTED_MAPPING_KEYS or key not in value:
            continue
        raw = value.get(key)
        if isinstance(raw, str):
            text, _, _ = _ascii_text(raw, MAX_CONTEXT_ITEM_CHARS)
            if text:
                result[key] = text
        elif isinstance(raw, list):
            items = []
            for item in raw[:6]:
                text, _, _ = _ascii_text(item, 120)
                if text:
                    items.append(text)
            if items:
                result[key] = items
    return result or None


def _packet_metadata(packet: Mapping[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Select safe packet fields; never copy arbitrary packet keys."""
    metadata: Dict[str, Any] = {}
    truncated = False
    for key in ("title", "description", "adventure_summary", "module_tone"):
        value = packet.get(key)
        if isinstance(value, str) and value.strip():
            text, was_truncated, _ = _ascii_text(value, MAX_CONTEXT_ITEM_CHARS)
            metadata[key] = text
            truncated = truncated or was_truncated

    list_fields = (
        "acts",
        "locations",
        "npc_seeds",
        "encounter_seeds",
        "item_seeds",
        "plot_progression",
        "connectivity_hints",
        "continuity_hints",
        "assumptions",
        "warnings",
    )
    for key in list_fields:
        values = packet.get(key)
        if not isinstance(values, list) or not values:
            continue
        original_count = len(values)
        compacted = []
        for value in values[:MAX_PACKET_ITEMS]:
            item = _compact_packet_item(value)
            if item:
                compacted.append(item)
        if original_count > MAX_PACKET_ITEMS:
            truncated = True
        if compacted:
            metadata[key] = compacted
    return metadata, truncated


def _graph_evidence(
    source_graph: Mapping[str, Any],
    source_path: Optional[str],
    source_hash: str,
) -> Optional[Dict[str, Any]]:
    atoms = source_graph.get("atoms")
    if not isinstance(atoms, list):
        return None
    items: List[Dict[str, Any]] = []
    for atom in atoms[:MAX_MANIFEST_ITEMS]:
        if not isinstance(atom, Mapping):
            continue
        name = atom.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        value, value_truncated, _ = _ascii_text(name, MAX_CONTEXT_ITEM_CHARS)
        summary, summary_truncated, _ = _ascii_text(atom.get("summary", ""), MAX_CONTEXT_ITEM_CHARS)
        atom_type, _, _ = _ascii_text(atom.get("type", "source_atom"), 80)
        items.append(
            {
                "kind": "source_graph_atom",
                "atom_type": atom_type,
                "value": value,
                "summary": summary,
                "source_hash": source_hash,
                "source_ref": _source_ref(source_path, source_hash),
                "advisory": True,
                "truncated": value_truncated or summary_truncated,
            }
        )
    if not items:
        return None
    return {
        "kind": "source_graph",
        "provenance": "deterministic_source_graph",
        "source_hash": source_hash,
        "source_ref": _source_ref(source_path, source_hash),
        "evidence": items,
        "original_items": len(atoms),
        "included_items": len(items),
        "truncated": len(atoms) > len(items),
        "advisory": True,
    }


def _count_candidates(manifest: Mapping[str, Any], key: str) -> int:
    value = manifest.get(key)
    return len(value) if isinstance(value, list) else 0


def _profile_hint(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    for profile in VALID_SOURCE_PROFILES:
        if lowered == profile:
            return profile
    return None


def _infer_source_profile(
    raw_source: str,
    source_summary: Any,
    manifest: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> Tuple[str, str, List[str]]:
    text_for_cues = raw_source
    if isinstance(source_summary, str):
        text_for_cues += "\n" + source_summary
    elif isinstance(source_summary, Mapping):
        summary, _ = _first_mapping_text(source_summary, _SUMMARY_TEXT_KEYS)
        text_for_cues += "\n" + summary
    packet_summary, _ = _first_mapping_text(packet, _SUMMARY_TEXT_KEYS)
    text_for_cues += "\n" + packet_summary
    lowered = text_for_cues.lower()

    room_candidates = manifest.get("location_candidates", [])
    strong_room_count = 0
    if isinstance(room_candidates, list):
        strong_room_count = sum(
            1
            for candidate in room_candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get("location_type", "")).lower() in {"room", "map_key"}
        )
    room_count = strong_room_count + len(_ROOM_HEADING_RE.findall(raw_source))
    item_count = _count_candidates(manifest, "item_candidates")
    encounter_count = _count_candidates(manifest, "encounter_candidates")
    location_count = _count_candidates(manifest, "location_candidates")
    packet_locations = len(packet.get("locations", [])) if isinstance(packet.get("locations"), list) else 0
    packet_acts = len(packet.get("acts", [])) if isinstance(packet.get("acts"), list) else 0
    packet_encounters = len(packet.get("encounter_seeds", [])) if isinstance(packet.get("encounter_seeds"), list) else 0
    packet_items = len(packet.get("item_seeds", [])) if isinstance(packet.get("item_seeds"), list) else 0

    basis: List[str] = []
    if strong_room_count or room_count:
        basis.append("room_or_map_structure")
    if item_count or packet_items:
        basis.append("item_evidence")
    if encounter_count or packet_encounters:
        basis.append("encounter_evidence")
    if packet_locations:
        basis.append("packet_locations")

    # Strong shape signals take precedence over titles and weak hints.
    if strong_room_count >= 2 or room_count >= 2 or packet_acts >= 2:
        return "adventure", "room_or_progression_shape", basis or ["progression_cues"]
    if item_count >= 2 or packet_items >= 2 or re.search(
        r"\b(catalogue|catalog|shop|market|stock|price|prices|inventory)\b",
        lowered,
    ):
        return "catalogue", "item_listing_shape_without_rooms", basis or ["catalogue_cues"]
    if strong_room_count == 1 or room_count == 1:
        return "location", "single_place_or_room_shape", basis or ["location_cues"]
    if encounter_count >= 2 or packet_encounters >= 2 or re.search(
        r"\b(set[- ]piece|encounter|ambush|battle|combat)\b", lowered
    ):
        return "encounter", "set_piece_shape", basis or ["encounter_cues"]
    if location_count >= 2 or packet_locations >= 2:
        return "location", "place_description_shape", basis or ["location_cues"]
    if re.search(r"\b(history|legend|lore|chronicle|myth|customs)\b", lowered):
        return "lore", "setting_text_shape", basis or ["lore_cues"]

    for candidate in (
        source_summary.get("source_profile_hint") if isinstance(source_summary, Mapping) else None,
        source_summary.get("profile_hint") if isinstance(source_summary, Mapping) else None,
        packet.get("source_profile_hint"),
        packet.get("source_profile"),
    ):
        hint = _profile_hint(candidate)
        if hint:
            return hint, "provided_shape_hint", basis or ["shape_hint"]
    return "sandbox", "mixed_or_unknown_shape", basis or ["no_dominant_shape"]


def _safe_summary_sections(
    source_summary: Any,
    source_path: Optional[str],
    source_hash: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(source_summary, Mapping):
        return None
    raw_sections = source_summary.get("section_summaries")
    if not isinstance(raw_sections, list):
        return None
    sections: List[Dict[str, Any]] = []
    truncated = len(raw_sections) > MAX_SOURCE_SECTIONS
    for section in raw_sections[:MAX_SOURCE_SECTIONS]:
        if not isinstance(section, Mapping):
            continue
        heading, _ = _first_mapping_text(section, ("heading", "title", "name"))
        summary, _ = _first_mapping_text(section, _SUMMARY_TEXT_KEYS)
        if not heading and not summary:
            continue
        heading, heading_truncated, _ = _ascii_text(heading, 160)
        summary, summary_truncated, _ = _ascii_text(summary, MAX_SOURCE_SECTION_CHARS)
        sections.append(
            {
                "heading": heading or "Untitled section",
                "summary": summary,
                "kind": "source_summary_section",
                "provenance": "explicit_source_summary",
                "source_hash": source_hash,
                "source_ref": _source_ref(source_path, source_hash),
                "advisory": True,
                "truncated": heading_truncated or summary_truncated,
            }
        )
    if not sections:
        return None
    return {
        "kind": "source_summary_sections",
        "provenance": "explicit_source_summary",
        "source_hash": source_hash,
        "source_ref": _source_ref(source_path, source_hash),
        "sections": sections,
        "original_items": len(raw_sections),
        "included_items": len(sections),
        "truncated": truncated,
        "advisory": True,
    }


def _serialize(context: Mapping[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def serialize_adaptation_source_context(context: Mapping[str, Any]) -> str:
    """Serialize an already assembled context with deterministic JSON settings."""
    if not isinstance(context, Mapping):
        raise ValueError("adaptation source context must be an object")
    encoded = _serialize(context)
    if len(encoded) > MAX_CONTEXT_SERIALIZED_CHARS:
        raise ValueError("adaptation source context exceeds its serialized bound")
    return encoded


def _shrink_context(context: Dict[str, Any]) -> bool:
    """Deterministically shrink low-precedence source material by one step."""
    inputs = context.get("source_inputs")
    if not isinstance(inputs, list):
        return False

    # Explicit summaries have priority over raw excerpts, manifests, and
    # packet metadata. Shrink lower-precedence evidence first.
    for kind in ("raw_source_excerpt", "source_manifest", "source_graph", "normalized_packet", "source_summary"):
        for record in inputs:
            if not isinstance(record, dict) or record.get("kind") != kind:
                continue
            text = record.get("text")
            if isinstance(text, str) and len(text) > 80:
                shortened, _, original_chars = _ascii_text(text, max(80, len(text) - 512))
                record["text"] = shortened
                record["included_chars"] = len(shortened)
                record["original_chars"] = max(original_chars, int(record.get("original_chars", 0) or 0))
                record["truncated"] = True
                return True
            for list_key in ("evidence", "sections"):
                values = record.get(list_key)
                if isinstance(values, list) and len(values) > 1:
                    values.pop()
                    record["included_items"] = len(values)
                    record["truncated"] = True
                    return True
            metadata = record.get("metadata")
            if isinstance(metadata, dict) and metadata:
                key = sorted(metadata)[-1]
                metadata.pop(key, None)
                record["truncated"] = True
                return True

    packet_metadata = context.get("packet_metadata")
    if isinstance(packet_metadata, dict):
        for key in sorted(packet_metadata, reverse=True):
            value = packet_metadata[key]
            if isinstance(value, list) and len(value) > 1:
                value.pop()
                context.setdefault("truncation", {}).setdefault("removed_packet_fields", []).append(key)
                return True
            if isinstance(value, str) and len(value) > 80:
                shortened, _, _ = _ascii_text(value, max(80, len(value) - 256))
                packet_metadata[key] = shortened
                context.setdefault("truncation", {}).setdefault("shortened_packet_fields", []).append(key)
                return True

    # Last resort: remove the least useful source input while retaining its
    # reference metadata in the truncation ledger.
    for index in range(len(inputs) - 1, -1, -1):
        record = inputs[index]
        if isinstance(record, dict) and record.get("kind") != "source_summary":
            removed = inputs.pop(index)
            context.setdefault("truncation", {}).setdefault("removed_sources", []).append(
                removed.get("kind", "unknown")
            )
            return True
    return False


def _fit_context(context: Dict[str, Any]) -> Dict[str, Any]:
    truncation = context.setdefault("truncation", {})
    truncation.setdefault("serialized_limit_chars", MAX_CONTEXT_SERIALIZED_CHARS)
    truncation.setdefault("truncated", False)
    for record in context.get("source_inputs", []):
        if isinstance(record, Mapping) and record.get("truncated"):
            truncation["truncated"] = True

    for _ in range(MAX_CONTEXT_ITEMS):
        encoded = _serialize(context)
        if len(encoded) <= MAX_CONTEXT_SERIALIZED_CHARS:
            actual_size = len(encoded)
            if truncation.get("serialized_chars") != actual_size:
                truncation["serialized_chars"] = actual_size
                continue
            if actual_size <= MAX_CONTEXT_SERIALIZED_CHARS:
                return context
        if not _shrink_context(context):
            break
        truncation["truncated"] = True

    # The fixed envelope is deliberately small, so this branch should only be
    # reachable after an unusual caller supplies pathological metadata.
    context["source_inputs"] = []
    context["packet_metadata"] = {}
    truncation["truncated"] = True
    truncation["fallback"] = "references_only"
    truncation["serialized_chars"] = len(_serialize(context))
    return context


def build_adaptation_source_context(
    raw_source: Any = None,
    source_summary: Any = None,
    source_manifest: Any = None,
    normalized_packet: Any = None,
    source_path: Any = None,
    source_hash: Any = None,
    source_title: Any = None,
    profile_override: Any = None,
    source_graph: Any = None,
    source_profile_override: Any = None,
) -> Dict[str, Any]:
    """Build a deterministic bounded context envelope for adaptation authoring.

    Precedence is intentionally explicit: valid ``profile_override`` (or its
    ``source_profile_override`` alias) wins for profile selection; explicit
    source summary wins over packet summary; raw source is retained only as a
    bounded excerpt; manifests and packets supply typed advisory evidence and
    metadata.  No extracted atom is a required output field.  Invalid input
    returns an ``assembly_status=invalid`` envelope instead of silently
    guessing or calling a provider.
    """
    diagnostics: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    if source_profile_override is not None:
        if profile_override is not None and profile_override != source_profile_override:
            diagnostics.append(
                _diagnostic(
                    "source_profile_override_conflict",
                    "multiple source profile overrides were supplied",
                    DIAGNOSTIC_SEVERITY_ERROR,
                )
            )
        else:
            profile_override = source_profile_override

    raw_text = ""
    if raw_source is not None:
        if isinstance(raw_source, bytes):
            try:
                raw_text = raw_source.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(_diagnostic("raw_source_invalid_utf8", "raw source is not valid UTF-8", DIAGNOSTIC_SEVERITY_ERROR))
        elif isinstance(raw_source, str):
            raw_text = raw_source
        else:
            diagnostics.append(_diagnostic("raw_source_invalid_type", "raw source must be text or UTF-8 bytes", DIAGNOSTIC_SEVERITY_ERROR))

    def _validate_mapping(value: Any, name: str) -> Mapping[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return value
        diagnostics.append(_diagnostic(f"{name}_invalid_type", f"{name} must be an object", DIAGNOSTIC_SEVERITY_ERROR))
        return {}

    summary_mapping = _validate_mapping(source_summary, "source_summary") if source_summary is not None and not isinstance(source_summary, str) else {}
    manifest = _validate_mapping(source_manifest, "source_manifest")
    packet = _validate_mapping(normalized_packet, "normalized_packet")
    graph = _validate_mapping(source_graph, "source_graph")

    explicit_hash = source_hash if source_hash is not None else None
    hash_candidates: List[Tuple[str, str]] = []
    if explicit_hash is not None:
        hash_candidates.append(("explicit_argument", str(explicit_hash).strip().lower()))
    for label, mapping in (
        ("source_summary", summary_mapping),
        ("source_manifest", manifest),
        ("normalized_packet", packet),
        ("source_graph", graph),
    ):
        value = _mapping_scalar(mapping, _HASH_KEYS)
        if value is not None:
            hash_candidates.append((label, str(value).strip().lower()))

    resolved_hash = ""
    hash_provenance = ""
    for label, candidate in hash_candidates:
        if not _is_sha256(candidate):
            if label == "explicit_argument":
                diagnostics.append(_diagnostic("source_hash_invalid", "source hash must be a lowercase SHA-256 digest", DIAGNOSTIC_SEVERITY_ERROR))
            else:
                warnings.append(_diagnostic("source_hash_reference_invalid", "a source reference hash was ignored", DIAGNOSTIC_SEVERITY_WARNING))
            continue
        resolved_hash = candidate
        hash_provenance = label
        break

    raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else ""
    if raw_digest:
        if resolved_hash and resolved_hash != raw_digest:
            diagnostics.append(_diagnostic("source_hash_mismatch", "provided source hash does not match raw source", DIAGNOSTIC_SEVERITY_ERROR))
        elif not resolved_hash:
            resolved_hash = raw_digest
            hash_provenance = "raw_source"

    raw_source_path = source_path
    if raw_source_path is None:
        raw_source_path = _mapping_scalar(summary_mapping, _PATH_KEYS)
    if raw_source_path is None:
        raw_source_path = _mapping_scalar(manifest, _PATH_KEYS)
    if raw_source_path is None:
        raw_source_path = _mapping_scalar(packet, _PATH_KEYS)
    safe_path, unsafe_path = _safe_project_relative_path(raw_source_path)
    if unsafe_path:
        warnings.append(_diagnostic("source_reference_omitted", "unsafe source path was omitted from context"))

    title = ""
    title_provenance = ""
    if isinstance(source_title, str) and source_title.strip():
        title, _, _ = _ascii_text(source_title, MAX_SOURCE_TITLE_CHARS)
        title_provenance = "explicit_argument"
    if not title:
        title, title_provenance = _first_mapping_text(summary_mapping, _TITLE_KEYS)
    if not title:
        title, title_provenance = _first_mapping_text(packet, _TITLE_KEYS)
    if not title and safe_path:
        title, _, _ = _ascii_text(Path(safe_path).stem.replace("_", " "), MAX_SOURCE_TITLE_CHARS)
        title_provenance = "source_reference"
    if not title:
        title = "Untitled readable source"
        title_provenance = "fallback"
    title, _, _ = _ascii_text(title, MAX_SOURCE_TITLE_CHARS)

    summary_text = ""
    summary_provenance = ""
    if isinstance(source_summary, str):
        summary_text, _, _ = _ascii_text(source_summary, MAX_SOURCE_SUMMARY_CHARS)
        summary_provenance = "explicit_source_summary"
    elif summary_mapping:
        summary_text, summary_key = _first_mapping_text(summary_mapping, _SUMMARY_TEXT_KEYS)
        summary_provenance = "explicit_source_summary." + summary_key if summary_key else ""
    if not summary_text:
        summary_text, summary_key = _first_mapping_text(packet, _SUMMARY_TEXT_KEYS)
        summary_provenance = "normalized_packet." + summary_key if summary_key else ""

    # Generate the existing deterministic manifest only when raw source is
    # available and the caller did not supply one. This reuses legacy parsing
    # as evidence while keeping its atoms advisory to the adaptation author.
    if not manifest and raw_text:
        try:
            manifest = build_source_manifest(
                raw_text,
                safe_path or "",
                resolved_hash or raw_digest,
            )
        except Exception:
            warnings.append(_diagnostic("source_manifest_unavailable", "deterministic source manifest was unavailable"))
            manifest = {}

    if resolved_hash:
        for label, mapping in (("source_manifest", manifest), ("normalized_packet", packet), ("source_graph", graph)):
            candidate = _mapping_scalar(mapping, _HASH_KEYS)
            if isinstance(candidate, str) and candidate.strip().lower() and candidate.strip().lower() != resolved_hash:
                warnings.append(_diagnostic(f"{label}_hash_mismatch", f"{label} evidence hash was omitted"))
                if label == "source_manifest":
                    manifest = {}
                if label == "source_graph":
                    graph = {}

    valid_override = None
    if profile_override is not None:
        if isinstance(profile_override, str) and profile_override.strip().lower() in VALID_SOURCE_PROFILES:
            valid_override = profile_override.strip().lower()
        else:
            diagnostics.append(_diagnostic("source_profile_override_invalid", "source profile override is not supported", DIAGNOSTIC_SEVERITY_ERROR))

    if valid_override:
        profile = valid_override
        profile_reason = "explicit_profile_override"
        profile_basis = ["explicit_override"]
        profile_source = "explicit_override"
    elif profile_override is not None:
        profile = None
        profile_reason = "invalid_profile_override"
        profile_basis = []
        profile_source = "invalid_override"
    else:
        profile, profile_reason, profile_basis = _infer_source_profile(
            raw_text, source_summary, manifest, packet
        )
        profile_source = "shape_inference"

    source_inputs: List[Dict[str, Any]] = []
    if summary_text:
        source_inputs.append(
            _source_record(
                "source_summary",
                summary_provenance or "source_summary",
                summary_text,
                safe_path,
                resolved_hash,
                MAX_SOURCE_SUMMARY_CHARS,
            )
        )
    sections = _safe_summary_sections(source_summary, safe_path, resolved_hash)
    if sections:
        source_inputs.append(sections)
    if raw_text:
        source_inputs.append(
            _source_record(
                "raw_source_excerpt",
                "raw_source_bounded_excerpt",
                raw_text,
                safe_path,
                resolved_hash or raw_digest,
                MAX_RAW_SOURCE_CHARS,
            )
        )
    if manifest:
        manifest_record, _, _ = _manifest_evidence(manifest, safe_path, resolved_hash or raw_digest)
        source_inputs.append(manifest_record)
    if graph:
        graph_record = _graph_evidence(graph, safe_path, resolved_hash or raw_digest)
        if graph_record:
            source_inputs.append(graph_record)
    packet_metadata, packet_truncated = _packet_metadata(packet)
    if packet_metadata:
        source_inputs.append(
            {
                "kind": "normalized_packet",
                "provenance": "normalized_packet_advisory_metadata",
                "source_hash": resolved_hash,
                "source_ref": _source_ref(safe_path, resolved_hash),
                "metadata": packet_metadata,
                "original_items": len(packet),
                "included_items": len(packet_metadata),
                "truncated": packet_truncated,
                "advisory": True,
            }
        )

    if unsafe_path:
        path_note = "source path omitted"
    else:
        path_note = "source path referenced when project-relative"
    if not resolved_hash:
        diagnostics.append(_diagnostic("source_hash_missing", "source hash is unavailable", DIAGNOSTIC_SEVERITY_ERROR))
    if not source_inputs:
        diagnostics.append(_diagnostic("source_context_empty", "no bounded source context was supplied", DIAGNOSTIC_SEVERITY_ERROR))

    if raw_text or summary_text:
        context_status = CONTEXT_STATUS_AVAILABLE
    elif source_inputs:
        context_status = CONTEXT_STATUS_REFERENCED
    else:
        context_status = CONTEXT_STATUS_UNAVAILABLE

    truncation_records = [
        record for record in source_inputs if isinstance(record, Mapping) and record.get("truncated")
    ]
    assembly_status = ASSEMBLY_STATUS_INVALID if diagnostics else (
        ASSEMBLY_STATUS_DEGRADED if warnings or truncation_records or context_status != CONTEXT_STATUS_AVAILABLE else ASSEMBLY_STATUS_READY
    )
    context: Dict[str, Any] = {
        "context_version": SOURCE_CONTEXT_VERSION,
        "assembly_status": assembly_status,
        "context_status": context_status,
        "source_title": title,
        "source_title_provenance": title_provenance,
        "source_hash": resolved_hash,
        "source_hash_provenance": hash_provenance,
        "source_ref": _source_ref(safe_path, resolved_hash),
        "source_reference_policy": path_note,
        "source_profile": profile,
        "source_profile_source": profile_source,
        "profile_reason": profile_reason,
        "profile_basis": profile_basis[:8],
        "profile_guidance": _PROFILE_GUIDANCE.get(profile, "No source profile was selected."),
        "input_precedence": [
            "explicit_source_summary",
            "raw_source_bounded_excerpt",
            "deterministic_manifest_evidence",
            "normalized_packet_advisory_metadata",
        ],
        "source_inputs": source_inputs,
        "packet_metadata": packet_metadata,
        "atom_policy": {
            "source_atoms_are_advisory": True,
            "required_output_fields": [],
            "may_omit": True,
            "may_reinterpret": True,
            "may_replace": True,
        },
        "truncation": {
            "truncated": bool(truncation_records),
            "serialized_limit_chars": MAX_CONTEXT_SERIALIZED_CHARS,
            "per_input_limits": {
                "raw_source_excerpt": MAX_RAW_SOURCE_CHARS,
                "source_summary": MAX_SOURCE_SUMMARY_CHARS,
                "source_summary_section": MAX_SOURCE_SECTION_CHARS,
                "manifest_items": MAX_MANIFEST_ITEMS,
                "packet_items": MAX_PACKET_ITEMS,
            },
            "inputs": [record.get("kind", "unknown") for record in truncation_records],
        },
        "diagnostics": (diagnostics + warnings)[:MAX_DIAGNOSTICS],
    }
    return _fit_context(context)


assemble_adaptation_source_context = build_adaptation_source_context
build_source_context = build_adaptation_source_context
assemble_source_context = build_adaptation_source_context


__all__ = [
    "ASSEMBLY_STATUS_DEGRADED",
    "ASSEMBLY_STATUS_INVALID",
    "ASSEMBLY_STATUS_READY",
    "CONTEXT_STATUS_AVAILABLE",
    "CONTEXT_STATUS_REFERENCED",
    "CONTEXT_STATUS_UNAVAILABLE",
    "MAX_CONTEXT_ITEM_CHARS",
    "MAX_CONTEXT_SERIALIZED_CHARS",
    "MAX_MANIFEST_ITEMS",
    "MAX_RAW_SOURCE_CHARS",
    "MAX_SOURCE_SECTIONS",
    "MAX_SOURCE_SUMMARY_CHARS",
    "SOURCE_CONTEXT_VERSION",
    "assemble_adaptation_source_context",
    "assemble_source_context",
    "build_adaptation_source_context",
    "build_source_context",
    "serialize_adaptation_source_context",
]
