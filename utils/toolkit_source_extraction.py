# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Section-Bounded Source Extraction
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Section-bounded LLM extraction orchestration for readable Homebrew uploads.
Phase 2 of the accurate-ingest pipeline.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

SOURCE_EXTRACTION_VERSION = "toolkit_source_extraction.v1"

_MAX_SECTION_CHARS_DEFAULT = 8000
_MAX_EXCERPT_CHARS = 200
_SECTION_CACHE_VERSION = 1


def build_extraction_units(
    source_text: str,
    source_path: str = "",
    source_hash: str = "",
    source_graph: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build section extraction units from source text and manifest headings.

    Each unit contains bounded source text, heading context, line range,
    and mechanical atom hints drawn from the source graph when available.
    """

    if not source_hash:
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    lines = source_text.split("\n")

    # Re-use heading extraction from source manifest module
    from utils.toolkit_source_manifest import _extract_heading_hierarchy

    headings = _extract_heading_hierarchy(source_text)
    units: List[Dict[str, Any]] = []

    # Build atom hint lookup keyed by line start for quick section assignment
    atom_hints_by_line: Dict[int, List[Dict[str, Any]]] = {}
    if source_graph:
        for atom in source_graph.get("atoms", []):
            refs = atom.get("source_refs", [])
            if refs:
                line = refs[0].get("line_start", 0)
                if line:
                    line = int(line)
                    atom_hints_by_line.setdefault(line, []).append(
                        {
                            "atom_id": atom.get("id", ""),
                            "type": atom.get("type", ""),
                            "name": atom.get("name", ""),
                            "summary": atom.get("summary", "")[:_MAX_EXCERPT_CHARS],
                            "criticality": atom.get("criticality", "minor"),
                        }
                    )

    if not headings:
        # Single flat section for the whole source (only if non-empty)
        bounded = source_text.strip()
        if bounded:
            units.append(
                _make_unit(
                    source_text=bounded,
                    source_path=source_path,
                    source_hash=source_hash,
                    section_id="X001",
                    heading_path="Full Source",
                    line_start=1,
                    line_end=len(lines),
                    atom_hints=list(
                        {
                            h["atom_id"]: h
                            for hints in atom_hints_by_line.values()
                            for h in hints
                        }.values()
                    ),
                )
            )
        return units

    # Section 0: above the first heading (if content exists)
    first_heading = headings[0]
    first_line = int(first_heading.get("line_start", 1))
    if first_line > 1:
        preamble_text = "\n".join(lines[0 : first_line - 1]).strip()
        if preamble_text:
            units.append(
                _make_unit(
                    source_text=preamble_text,
                    source_path=source_path,
                    source_hash=source_hash,
                    section_id="P001",
                    heading_path="Preamble",
                    line_start=1,
                    line_end=first_line - 1,
                    atom_hints=_collect_hints(1, first_line - 1, atom_hints_by_line),
                )
            )

    counter = 0
    for i, h in enumerate(headings):
        counter += 1
        section_id = f"S{counter:03d}"
        heading_path = str(h.get("heading_path", h.get("text", f"Section {counter}")))
        h_start = int(h.get("line_start", 1))
        h_end = (
            int(headings[i + 1]["line_start"]) - 1
            if i + 1 < len(headings)
            else len(lines)
        )
        h_end = max(h_end, h_start)

        section_text = "\n".join(lines[h_start - 1 : h_end])
        hints = _collect_hints(h_start, h_end, atom_hints_by_line)

        units.append(
            _make_unit(
                source_text=section_text,
                source_path=source_path,
                source_hash=source_hash,
                section_id=section_id,
                heading_path=heading_path,
                line_start=h_start,
                line_end=h_end,
                atom_hints=hints,
            )
        )

    return units


def build_extraction_index(
    units: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the section_extractions/index.json registry."""
    entries = []
    index_source_hash = units[0].get("source_hash", "") if units else ""
    for u in units:
        entries.append(
            {
                "section_id": u["section_id"],
                "heading_path": u["heading_path"],
                "line_start": u["line_start"],
                "line_end": u["line_end"],
                "chars": u["chars"],
                "section_identity": u.get("section_identity", ""),
                "atom_hint_count": len(u.get("atom_hints", [])),
                "status": u.get("status", "pending"),
                "artifact": f"section_extractions/{u['section_id']}.json",
            }
        )
    return {
        "index_version": SOURCE_EXTRACTION_VERSION,
        "source_hash": index_source_hash,
        "total_units": len(entries),
        "degraded_units": sum(1 for e in entries if e["status"] == "degraded"),
        "completed_units": sum(
            1 for e in entries if e["status"] in ("success", "cached")
        ),
        "entries": entries,
    }


def record_section_extraction_result(
    unit: Dict[str, Any],
    status: str,
    model_name: str = "",
    extracted_atoms: Optional[List[Dict[str, Any]]] = None,
    error: str = "",
    response_preview: str = "",
    cache_hit: bool = False,
) -> Dict[str, Any]:
    """Record a per-section extraction result artifact."""
    payload: Dict[str, Any] = {
        "extraction_version": SOURCE_EXTRACTION_VERSION,
        "section_id": unit["section_id"],
        "heading_path": unit["heading_path"],
        "source_hash": unit.get("source_hash", ""),
        "section_identity": unit.get("section_identity", ""),
        "line_start": unit.get("line_start", 0),
        "line_end": unit.get("line_end", 0),
        "status": status,
        "model": model_name,
        "error": error,
        "cache_hit": cache_hit,
        "response_preview": response_preview[:_MAX_EXCERPT_CHARS],
        "extracted_atoms": extracted_atoms or [],
        "evidence_summary": {
            "atom_count": len(extracted_atoms or []),
            "types": sorted(
                {
                    a.get("type", "unknown")
                    for a in (extracted_atoms or [])
                }
            ),
        },
    }
    unit["status"] = status
    unit["cache_hit"] = cache_hit
    return payload


def compute_section_identity(text: str) -> str:
    """Stable identity for caching per section text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_unit(
    source_text: str,
    source_path: str,
    source_hash: str,
    section_id: str,
    heading_path: str,
    line_start: int,
    line_end: int,
    atom_hints: List[Dict[str, Any]],
) -> Dict[str, Any]:
    bounded = source_text.strip()
    if len(bounded) > _MAX_SECTION_CHARS_DEFAULT:
        bounded = bounded[:_MAX_SECTION_CHARS_DEFAULT]
    return {
        "section_id": section_id,
        "heading_path": heading_path,
        "line_start": line_start,
        "line_end": line_end,
        "chars": len(bounded),
        "source_text": bounded,
        "source_path": source_path,
        "source_hash": source_hash,
        "atom_hints": atom_hints,
        "section_identity": compute_section_identity(bounded),
        "status": "pending",
    }


def _collect_hints(
    line_start: int,
    line_end: int,
    atom_hints_by_line: Dict[int, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Collect atom hints whose evidence falls within the given line range."""
    hints: List[Dict[str, Any]] = []
    seen: set = set()
    for line, hlist in atom_hints_by_line.items():
        if line_start <= line <= line_end:
            for h in hlist:
                if h["atom_id"] not in seen:
                    seen.add(h["atom_id"])
                    hints.append(h)
    return hints
