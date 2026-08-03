# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Source Manifest & Source Graph
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic source manifest and source graph extraction for readable
Homebrew uploads. Phase 1 of the accurate-ingest pipeline.
"""

import hashlib
import re
from typing import Any, Dict, List, Optional

SOURCE_MANIFEST_VERSION = "toolkit_source_manifest.v1"
SOURCE_GRAPH_VERSION = "toolkit_source_graph.v1"

_MAX_EXCERPT_CHARS = 200


def build_source_manifest(source_text: str, source_path: str = "",
                         source_hash: str = "") -> Dict[str, Any]:
    """Extract headings, tables, location candidates, entity candidates,
    mechanic candidates, and tone candidates from markdown source.

    Returns a manifest dict with raw extraction buckets.
    """
    if not source_hash:
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    headings = _extract_heading_hierarchy(source_text)
    tables = _extract_markdown_tables(source_text)
    location_candidates = _extract_location_candidates(source_text, headings)
    entity_candidates = _extract_entity_candidates(source_text, headings, tables)
    mechanic_candidates = _extract_mechanic_candidates(source_text, headings)
    puzzle_candidates = _extract_puzzle_candidates(source_text, headings)
    item_candidates = _extract_item_candidates(source_text, headings)
    encounter_candidates = _extract_encounter_candidates(source_text, headings)
    tone_candidates = _extract_tone_candidates(source_text)

    return {
        "manifest_version": SOURCE_MANIFEST_VERSION,
        "source_path": source_path,
        "source_hash": source_hash,
        "headings": headings,
        "tables": tables,
        "location_candidates": location_candidates,
        "entity_candidates": entity_candidates,
        "mechanic_candidates": mechanic_candidates,
        "puzzle_candidates": puzzle_candidates,
        "item_candidates": item_candidates,
        "encounter_candidates": encounter_candidates,
        "tone_candidates": tone_candidates,
    }


def build_source_graph(source_text: str, source_path: str = "",
                       source_hash: str = "") -> Dict[str, Any]:
    """Convert raw manifest candidates into typed source atoms with
    evidence references, criticality, and confidence.
    """
    if not source_hash:
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    manifest = build_source_manifest(source_text, source_path, source_hash)
    atoms: List[Dict[str, Any]] = []
    atom_counter: int = 0

    for loc in manifest.get("location_candidates", []):
        refs = _build_refs(loc, source_path)
        atom_id = _make_atom_id(source_hash, "loc", loc.get("name", "unknown"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "location",
            "name": loc.get("name", ""),
            "summary": loc.get("description", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "required",
            "confidence": "high",
            "source_refs": refs,
            "metadata": {"location_type": loc.get("location_type", "map_key")},
        })

    for ent in manifest.get("entity_candidates", []):
        refs = _build_refs(ent, source_path)
        atom_id = _make_atom_id(source_hash, "ent", ent.get("name", "unknown"), atom_counter, refs)
        atom_counter += 1
        crit = _classify_entity_criticality(ent)
        etype = ent.get("entity_type", "unknown")
        conf = ent.get("confidence", "medium")
        atoms.append({
            "id": atom_id,
            "type": etype,
            "name": ent.get("name", ""),
            "summary": ent.get("context", "")[:_MAX_EXCERPT_CHARS],
            "criticality": crit,
            "confidence": conf,
            "source_refs": refs,
            "metadata": {"source": ent.get("source", "")},
        })

    for pc in manifest.get("puzzle_candidates", []):
        refs = _build_refs(pc, source_path)
        atom_id = _make_atom_id(source_hash, "puz", pc.get("cue", "unknown"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "puzzle",
            "name": pc.get("cue", ""),
            "summary": pc.get("context", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "required",
            "confidence": "medium",
            "source_refs": refs,
            "metadata": {},
        })

    for mc in manifest.get("mechanic_candidates", []):
        refs = _build_refs(mc, source_path)
        atom_id = _make_atom_id(source_hash, "mech", mc.get("cue", "unknown"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "mechanic",
            "name": mc.get("cue", ""),
            "summary": mc.get("context", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "major",
            "confidence": "high",
            "source_refs": refs,
            "metadata": {},
        })

    for ic in manifest.get("item_candidates", []):
        refs = _build_refs(ic, source_path)
        atom_id = _make_atom_id(source_hash, "item", ic.get("cue", "unknown"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "item",
            "name": ic.get("cue", ""),
            "summary": ic.get("context", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "major",
            "confidence": "medium",
            "source_refs": refs,
            "metadata": {},
        })

    for ec in manifest.get("encounter_candidates", []):
        refs = _build_refs(ec, source_path)
        atom_id = _make_atom_id(source_hash, "enc", ec.get("cue", "unknown"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "encounter",
            "name": ec.get("cue", ""),
            "summary": ec.get("context", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "major",
            "confidence": "medium",
            "source_refs": refs,
            "metadata": {},
        })

    for tc in manifest.get("tone_candidates", []):
        refs = _build_refs(tc, source_path)
        atom_id = _make_atom_id(source_hash, "tone", tc.get("phrase", "tone"), atom_counter, refs)
        atom_counter += 1
        atoms.append({
            "id": atom_id,
            "type": "tone_marker",
            "name": tc.get("phrase", ""),
            "summary": tc.get("phrase", "")[:_MAX_EXCERPT_CHARS],
            "criticality": "minor",
            "confidence": "medium",
            "source_refs": refs,
            "metadata": {},
        })

    _dedupe_atoms(atoms)

    npc_count = sum(1 for a in atoms if a["type"] == "npc")
    loc_count = sum(1 for a in atoms if a["type"] == "location")
    puzzle_count = sum(1 for a in atoms if a["type"] == "puzzle")
    encounter_count = sum(1 for a in atoms if a["type"] == "encounter")
    item_count = sum(1 for a in atoms if a["type"] == "item")
    tone_count = sum(1 for a in atoms if a["type"] == "tone_marker")

    return {
        "graph_version": SOURCE_GRAPH_VERSION,
        "source_path": source_path,
        "source_hash": source_hash,
        "atoms": atoms,
        "summary": {
            "npc_candidates": npc_count,
            "location_candidates": loc_count,
            "puzzle_candidates": puzzle_count,
            "encounter_candidates": encounter_count,
            "item_candidates": item_count,
            "tone_candidates": tone_count,
            "total_atoms": len(atoms),
        },
    }


def _line_at(text: str, pos: int) -> int:
    """Return 1-indexed line number for character position."""
    return text[:pos].count("\n") + 1 if pos >= 0 else 1


def _excerpt(text: str, pos: int, length: int = _MAX_EXCERPT_CHARS) -> str:
    """Return bounded excerpt starting near character position."""
    start = max(0, pos - 20)
    excerpt = text[start:start + length]
    if len(excerpt) >= length:
        excerpt = excerpt[:_MAX_EXCERPT_CHARS - 3] + "..."
    return excerpt.replace("\n", " ").strip()


def _heading_key(heading_text: str) -> str:
    """Lowercase stripped heading text for matching."""
    return heading_text.strip().lower()


# ---------------------------------------------------------------------------
# 1. Heading hierarchy
# ---------------------------------------------------------------------------

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _normalize_heading_text(raw_text: str) -> str:
    r"""Strip markdown escaping and trailing whitespace from heading text.

    Handles common escape patterns such as ``1\\. Chapel`` -> ``1. Chapel``.
    """
    text = raw_text.strip()
    text = re.sub(r"\\([#\-.()\[\]{}_*+?!|~`@:])", r"\1", text)
    return text


def _extract_heading_hierarchy(text: str) -> List[Dict[str, Any]]:
    """Extract all headings with level, text, line range, and parent
    tracking."""
    headings: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    for match in _HEADING_PATTERN.finditer(text):
        level = len(match.group(1))
        heading_text = _normalize_heading_text(match.group(2))
        start_line = _line_at(text, match.start())
        end_line = start_line  # will be fixed up to next heading
        entry = {
            "level": level,
            "text": heading_text,
            "line_start": start_line,
            "line_end": end_line,
            "parent": "",
        }
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            entry["parent"] = stack[-1]["text"]
        stack.append(entry)
        headings.append(entry)

    for i, h in enumerate(headings):
        if i + 1 < len(headings):
            h["line_end"] = headings[i + 1]["line_start"] - 1
        else:
            total_lines = text.count("\n") + 1
            h["line_end"] = total_lines

    return headings


# ---------------------------------------------------------------------------
# 2. Markdown tables
# ---------------------------------------------------------------------------

_TABLE_PATTERN = re.compile(
    r"\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)", re.MULTILINE
)


def _extract_markdown_tables(text: str) -> List[Dict[str, Any]]:
    """Extract markdown pipe tables with headers and rows."""
    tables: List[Dict[str, Any]] = []
    for match in _TABLE_PATTERN.finditer(text):
        header_line = match.group(1)
        rows_text = match.group(2)
        headers = [h.strip() for h in header_line.split("|") if h.strip()]
        rows: List[List[str]] = []
        row_line_numbers: List[int] = []
        table_start_line = _line_at(text, match.start())
        for row_line in rows_text.strip().split("\n"):
            if "|" in row_line:
                row_cells = [c.strip() for c in row_line.split("|") if c.strip()]
                if row_cells:
                    rows.append(row_cells)
                    row_line_numbers.append(table_start_line + 2 + len(row_line_numbers))
        if headers and rows:
            tables.append({
                "headers": headers,
                "rows": rows,
                "row_line_numbers": row_line_numbers,
                "line_start": _line_at(text, match.start()),
                "line_end": _line_at(text, match.end()),
            })
    return tables


# ---------------------------------------------------------------------------
# 2b. Table header role classification helpers
# ---------------------------------------------------------------------------
# These pure helpers classify table headers as identity-bearing
# (NPC/character/creature tables) vs. effect/mechanics/description
# tables.  Used by _extract_entity_candidates to filter table-cell
# entity registration (wired in task 2.2).


def _normalize_table_header(header: str) -> str:
    """Normalize a markdown table header for classification matching.

    Strips leading/trailing whitespace, bold/italic markers (**, *),
    and trailing punctuation (colon, semicolon, comma, period, !?).
    Returns lowercase plain text.  Pure helper, no side effects.
    """
    h = header.strip()
    h = h.strip("*_:;,.!?")
    h = h.strip()
    return h.lower()


_TABLE_IDENTITY_HEADERS: set = {
    "name",
    "npc", "npcs",
    "character", "characters",
    "creature", "creatures",
    "monster", "monsters",
    "faction", "factions",
    "person",
    "people",
    "actor", "actors",
    "identity",
}


_TABLE_EFFECT_HEADERS: set = {
    "d100", "d%",
    "effect", "effects",
    "complication", "complications",
    "result", "results",
    "description", "descriptions",
    "spell", "spells",
    "trigger", "triggers",
    "trap", "traps",
    "mechanic", "mechanics",
    "trick", "tricks",
    "damage",
    "condition", "conditions",
    "passive element",
    "active element",
}


def _table_headers_indicate_entity_identity(headers: List[str]) -> bool:
    """Check if table headers suggest the table contains named entities
    (NPCs, characters, creatures, factions, etc.).

    Normalizes each header and tests for overlap with
    _TABLE_IDENTITY_HEADERS.  Also checks individual words from multi-word
    headers (e.g. "NPC Name" -> {"npc", "name"} both in identity set).
    Pure helper, no side effects.
    """
    if not headers:
        return False
    normalized = {_normalize_table_header(h) for h in headers}
    if normalized & _TABLE_IDENTITY_HEADERS:
        return True
    # Check individual words of multi-word headers to catch
    # patterns like "NPC Name", "Character Name", "Monster Name"
    for h in headers:
        norm = _normalize_table_header(h)
        for word in norm.split():
            if word in _TABLE_IDENTITY_HEADERS:
                return True
    return False


def _table_headers_indicate_effect_text(headers: List[str]) -> bool:
    """Check if table headers suggest the table contains effect, trap,
    description, or mechanic text (not named entities).

    Normalizes each header and tests for overlap with
    _TABLE_EFFECT_HEADERS.  Pure helper, no side effects.
    """
    if not headers:
        return False
    normalized = {_normalize_table_header(h) for h in headers}
    return bool(normalized & _TABLE_EFFECT_HEADERS)


# ---------------------------------------------------------------------------
# 3. Location candidates
# ---------------------------------------------------------------------------

_MAP_KEY_PATTERN = re.compile(
    r"^#{3,4}\s+(\d+\\?[\.\)\-\s]+\s*.+)$", re.MULTILINE
)
_ROOM_PATTERN = re.compile(
    r"^##\s+Room\s+(\d+):\s*(.+)$", re.MULTILINE
)

_APPENDIX_PATTERN = re.compile(
    r"^(?:Appendix|Appendices|Table\s+of\s+Contents|Index|Glossary|"
    r"Credits|Contributors|Acknowledgments|References|Bibliography|"
    r"Version\s+History|Changelog|Errata)",
    re.IGNORECASE | re.MULTILINE,
)

_HEADING_PREFIX_WORDS: set = {
    "a", "an", "the",
    "gathered", "around", "about", "across", "after", "again",
    "almost", "along", "always", "another", "around", "away",
    "back", "before", "behind", "below", "between", "beyond",
    "both", "but", "down", "each", "either", "enough",
    "even", "ever", "every", "few", "first", "forward",
    "from", "further", "great", "here", "how", "into",
    "just", "last", "less", "many", "more", "most",
    "much", "near", "never", "next", "none", "not",
    "nothing", "now", "once", "only", "other", "our",
    "over", "own", "right", "same", "should", "since",
    "some", "still", "such", "than", "that", "their",
    "them", "then", "there", "these", "they", "this",
    "through", "under", "until", "very", "well", "were",
    "what", "when", "where", "which", "while", "will",
    "with", "would", "your",
    # Prose-fragment filler words
    "looking", "seeing", "heard", "felt", "seemed", "appeared",
    "took", "made", "came", "went", "could", "said",
}


def _extract_location_candidates(text: str,
                                 headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract map-key, room-style, and heading-based location candidates."""
    candidates: List[Dict[str, Any]] = []
    seen_names: set = set()

    for match in _MAP_KEY_PATTERN.finditer(text):
        name = _normalize_heading_text(match.group(1).strip())
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        start_line = _line_at(text, match.start())
        end_line = start_line + 5
        section = _find_section_for_line(headings, start_line)
        candidates.append({
            "name": name,
            "number": 0,
            "location_type": "map_key",
            "description": _excerpt(text, match.end(), 300),
            "section": section,
            "line_start": start_line,
            "line_end": end_line,
            "_raw_match_start": match.start(),
        })

    for match in _ROOM_PATTERN.finditer(text):
        name = match.group(2).strip()
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        start_line = _line_at(text, match.start())
        end_line = start_line + 5
        section = _find_section_for_line(headings, start_line)
        candidates.append({
            "name": name,
            "number": int(match.group(1)),
            "location_type": "room",
            "description": _excerpt(text, match.end(), 300),
            "section": section,
            "line_start": start_line,
            "line_end": end_line,
            "_raw_match_start": match.start(),
        })

    # Heading-based locations: Level 2-4 headings that look like named places.
    # Skip appendix/toc/credits headings.  Map-key and room-style headings
    # are already captured above; heading-based extraction adds remaining
    # level 2-4 headings that look like location names.
    _seen_raw_starts: set = {c.get("_raw_match_start") for c in candidates if "_raw_match_start" in c}
    for heading in headings:
        h_text = heading["text"]
        h_level = heading["level"]
        if h_level < 2 or h_level > 4:
            continue
        norm = h_text.lower()
        if norm in seen_names:
            continue
        if _APPENDIX_PATTERN.match(h_text):
            continue
        if not _is_heading_location_name(h_text):
            continue
        seen_names.add(norm)
        candidates.append({
            "name": h_text,
            "number": 0,
            "location_type": "heading_location",
            "description": _excerpt(text, 0, 300),
            "section": h_text,
            "line_start": heading["line_start"],
            "line_end": heading["line_end"],
        })

    # Strip internal bookkeeping fields
    for c in candidates:
        c.pop("_raw_match_start", None)

    return candidates


def _find_section_for_line(headings: List[Dict[str, Any]],
                           line: int) -> str:
    """Find the most specific heading that contains a given line number."""
    best = ""
    for h in headings:
        if h["line_start"] <= line <= h["line_end"]:
            best = h["text"]
    return best


def _is_map_key_style_heading(text: str) -> bool:
    """Return True if the heading looks like a numbered map-key entry."""
    normalized = _normalize_heading_text(text.strip())
    return bool(re.match(r"^\d+[\.\)\-\s]", normalized))


def _is_heading_location_name(text: str) -> bool:
    """Return True if heading text looks like a meaningful location name.

    Rejects headings that are:
    - Common section labels (Introduction, Overview, Synopsis, etc.)
    - Prose-fragment patterns (mostly function words)
    - Single generic words
    - Appendix/credits/glossary headings
    """
    text = text.strip()
    if len(text) < 3 or len(text) > 120:
        return False
    if _APPENDIX_PATTERN.match(text):
        return False

    words = [w for w in text.split() if w]
    if not words:
        return False

    # Single generic word is not a location
    if len(words) == 1 and words[0].lower() in _COMMON_WORDS:
        return False

    # Reject prose fragments: if >= 50% of words are heading-prefix function
    # words, it is likely a prose fragment like "gathered around a stone"
    prefix_word_count = sum(1 for w in words if w.lower() in _HEADING_PREFIX_WORDS)
    if prefix_word_count >= max(3, len(words) * 0.5):
        return False

    # Reject common non-location section labels
    _non_location_labels: set = {
        "introduction", "overview", "synopsis", "summary", "conclusion",
        "background", "notes", "author notes", "design notes",
        "running the adventure", "adventure hooks", "plot hooks",
        "player character", "non player character", "npcs",
        "magic items", "equipment", "combat", "exploration",
        "roleplaying", "experience", "milestones", "advancement",
        "monsters", "monster", "statistics", "stat block",
        "preface", "foreword", "afterword", "afterword",
        "getting started", "setup", "settings", "theme",
        "tone", "mood", "premise",
    }
    if text.lower() in _non_location_labels:
        return False

    return True


# ---------------------------------------------------------------------------
# 4. Entity candidates (conservative)
# ---------------------------------------------------------------------------

_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
_QUOTED_PATTERN = re.compile(r'"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)"')


def _extract_entity_candidates(text: str,
                               headings: List[Dict[str, Any]],
                               tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract named entity candidates from bold spans, table cells,
    quoted names, and title-case proper noun patterns. Conservative
    approach prefers explicit markup over inference."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()

    def _register(name: str, source: str, context: str,
                  start_pos: int, etype: str = "npc",
                  line_override: Optional[int] = None,
                  section_override: Optional[str] = None):
        norm = name.strip().lower()
        if not norm or len(norm) < 3:
            return
        if norm in seen:
            return
        seen.add(norm)
        line = line_override if line_override is not None else _line_at(text, start_pos)
        section = section_override if section_override is not None else _find_section_for_line(headings, line)
        confidence = "high" if source in ("bold_span", "table_cell") else "medium"
        candidates.append({
            "name": name.strip(),
            "entity_type": etype,
            "source": source,
            "context": context[:_MAX_EXCERPT_CHARS],
            "section": section,
            "confidence": confidence,
            "line_start": line,
            "line_end": line,
        })

    for match in _BOLD_PATTERN.finditer(text):
        bold_text = match.group(1).strip()
        if _is_likely_name(bold_text):
            ctx = _excerpt(text, match.start(), 120)
            _register(bold_text, "bold_span", ctx, match.start())

    for table in tables:
        headers = table.get("headers", [])
        # Task 2.2: Only register table cells as entity/NPC candidates when
        # table headers indicate the table contains named entities (NPCs,
        # characters, creatures, etc.).  Effect/description/mechanics tables
        # and ambiguous tables are skipped to avoid false-positive NPC
        # extraction from trap/effect prose.
        if not _table_headers_indicate_entity_identity(headers):
            continue
        rows = table.get("rows", [])
        row_line_numbers = table.get("row_line_numbers", [])
        for row_idx, row in enumerate(rows):
            row_line = row_line_numbers[row_idx] if row_idx < len(row_line_numbers) else table.get("line_start", 0)
            row_section = _find_section_for_line(headings, row_line)
            for cell in row:
                cell_text = cell.strip()
                if _is_likely_name(cell_text):
                    ctx = f"Table: {', '.join(table.get('headers', []))} -> {cell_text}"
                    _register(cell_text, "table_cell", ctx, 0,
                              line_override=row_line, section_override=row_section)

    for match in _QUOTED_PATTERN.finditer(text):
        quoted = match.group(1).strip()
        if _is_likely_name(quoted) and quoted.lower() not in seen:
            ctx = _excerpt(text, match.start(), 120)
            _register(quoted, "quoted", ctx, match.start())

    _proper_noun_candidates(text, headings, seen, candidates)

    return candidates


_COMMON_WORDS: set = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "party", "players", "character", "characters", "npc", "npcs",
    "location", "area", "room", "door", "chest", "treasure", "trap",
    "secret", "passage", "hall", "corridor", "chamber", "entrance",
    "exit", "staircase", "stairs", "level", "floor", "wall", "ground",
    "attack", "action", "move", "bonus", "reaction", "check", "save",
    "skill", "spell", "weapon", "armor", "item", "magic", "magical",
    "effect", "damage", "healing", "rest", "short", "long", "minute",
    "hour", "day", "night", "morning", "evening", "north", "south",
    "east", "west", "northeast", "northwest", "southeast", "southwest",
    "investigation", "perception", "survival", "persuasion",
    "intimidation", "deception", "insight", "acrobatics", "athletics",
    "stealth", "history", "arcana", "nature", "religion", "medicine",
    "animal", "handling", "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
}


def _is_likely_name(text: str) -> bool:
    """Check if text looks like a named entity (not a common word/phrase)."""
    text = text.strip()
    if len(text) < 3 or len(text) > 80:
        return False
    words = text.split()
    if len(words) == 0:
        return False
    if len(words) == 1 and not words[0][0].isupper():
        return False
    if text.lower() in _COMMON_WORDS:
        return False
    if all(w.lower() in _COMMON_WORDS for w in words):
        return False
    # Reject prose fragments dominated by function/prefix words
    prefix_word_count = sum(1 for w in words if w.lower() in _HEADING_PREFIX_WORDS)
    if prefix_word_count >= max(2, len(words) * 0.5):
        return False
    return True


def _proper_noun_candidates(text: str, headings: List[Dict[str, Any]],
                            seen: set, candidates: List[Dict[str, Any]]):
    """Find title-case multi-word phrases as low-confidence candidates."""
    pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")
    for match in pattern.finditer(text):
        phrase = match.group(1).strip()
        norm = phrase.lower()
        if norm in seen or len(phrase) < 5:
            continue
        words = phrase.split()
        # Reject phrases dominated by function/prefix words (prose fragments)
        prefix_word_count = sum(1 for w in words if w.lower() in _HEADING_PREFIX_WORDS)
        if prefix_word_count >= max(2, len(words) * 0.5):
            continue
        if all(w.lower() in _COMMON_WORDS for w in words):
            continue
        line = _line_at(text, match.start())
        section = _find_section_for_line(headings, line)
        ctx = _excerpt(text, match.start(), 100)
        seen.add(norm)
        candidates.append({
            "name": phrase,
            "entity_type": "unknown",
            "source": "proper_noun",
            "context": ctx,
            "section": section,
            "confidence": "low",
            "line_start": line,
        })


# ---------------------------------------------------------------------------
# 5. Mechanic candidates (DC, checks, saves)
# ---------------------------------------------------------------------------

_DC_PATTERN = re.compile(
    r"(?:DC\s*(\d+)|(?:Perception|Investigation|Survival|Arcana|History|"
    r"Nature|Religion|Medicine|Insight|Persuasion|Intimidation|Deception|"
    r"Acrobatics|Athletics|Stealth|Sleight\s*of\s*Hand|Strength|Dexterity|"
    r"Constitution|Intelligence|Wisdom|Charisma)\s*(?:check|save|saving\s+"
    r"throw))",
    re.IGNORECASE,
)


def _extract_mechanic_candidates(text: str,
                                 headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract DC and check patterns as mechanic candidates."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for match in _DC_PATTERN.finditer(text):
        cue = match.group(0).strip()
        norm = cue.lower()
        if norm in seen:
            continue
        seen.add(norm)
        line = _line_at(text, match.start())
        section = _find_section_for_line(headings, line)
        ctx = _excerpt(text, match.start(), 120)
        candidates.append({
            "cue": cue,
            "context": ctx,
            "section": section,
            "line_start": line,
        })
    return candidates


# ---------------------------------------------------------------------------
# 6. Puzzle/trial candidates
# ---------------------------------------------------------------------------

_PUZZLE_PATTERN = re.compile(
    r"\b(?:riddle|puzzle|trial|flooding|flood|riddle'?s?|"
    r"brain[-\s]teaser|challenge|test\s+of\s+(?:knowledge|wisdom|"
    r"strength|courage)|mindscape|maze|labyrinth|code|cypher|"
    r"logic\s+puzzle|riddle\s*(?:door|room|gate))\b",
    re.IGNORECASE,
)


def _extract_puzzle_candidates(text: str,
                               headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract puzzle/trial cue patterns."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for match in _PUZZLE_PATTERN.finditer(text):
        cue = match.group(0).strip()
        norm = cue.lower()
        if norm in seen:
            continue
        seen.add(norm)
        line = _line_at(text, match.start())
        section = _find_section_for_line(headings, line)
        ctx = _excerpt(text, max(0, match.start() - 40), 200)
        candidates.append({
            "cue": cue,
            "context": ctx,
            "section": section,
            "line_start": line,
        })
    return candidates


# ---------------------------------------------------------------------------
# 7. Item/treasure candidates
# ---------------------------------------------------------------------------

_ITEM_PATTERN = re.compile(
    r"\b(?:treasure|reward|key|journal|letter|note|relic|artifact|"
    r"magic\s+item|weapon\s*\+|armor\s*\+|potion|scroll|wand|ring|"
    r"amulet|gem|coin|chest|loot|cache)\b",
    re.IGNORECASE,
)


def _extract_item_candidates(text: str,
                             headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract item/treasure cue patterns."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for match in _ITEM_PATTERN.finditer(text):
        cue = match.group(0).strip()
        norm = cue.lower()
        if norm in seen:
            continue
        seen.add(norm)
        line = _line_at(text, match.start())
        section = _find_section_for_line(headings, line)
        ctx = _excerpt(text, max(0, match.start() - 40), 200)
        candidates.append({
            "cue": cue,
            "context": ctx,
            "section": section,
            "line_start": line,
        })
    return candidates


# ---------------------------------------------------------------------------
# 8. Encounter candidates
# ---------------------------------------------------------------------------

_ENCOUNTER_PATTERN = re.compile(
    r"\b(?:encounter|monster|creature|guardian|skeleton|zombie|goblin|"
    r"orc|bandit|cultist|wight|specter|ghost|elemental|demon|devil|"
    r"dragon|wyrm|giant\s+(?:spider|rat|scorpion|centipede|snake)|"
    r"construct|golem|animated|statue|trap|ambush|patrols?|"
    r"spectral|gargoyle|sentinel|challenge(?:s|d)?|intruder(?:s)?|"
    r"hostile|enemy|combat|battle|fight|attack|defend|"
    r"assassin|knight|guard\s+(?:dog|cat|hound|beast)|"
    r"lesser|greater|black|white|red|green|blue|golden|silver|"
    r"lion|lizard|wolf|bear|serpent|scorpion|spider|"
    r"nomadic|wandering|ancient|elder|shadow|"
    r"hollow|undead|corrupted|fallen|risen)\b",
    re.IGNORECASE,
)


def _extract_encounter_candidates(text: str,
                                  headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract encounter/monster cue patterns."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for match in _ENCOUNTER_PATTERN.finditer(text):
        cue = match.group(0).strip()
        norm = cue.lower()
        if norm in seen:
            continue
        seen.add(norm)
        line = _line_at(text, match.start())
        section = _find_section_for_line(headings, line)
        ctx = _excerpt(text, max(0, match.start() - 40), 200)
        candidates.append({
            "cue": cue,
            "context": ctx,
            "section": section,
            "line_start": line,
        })
    return candidates


# ---------------------------------------------------------------------------
# 9. Tone markers
# ---------------------------------------------------------------------------

_TONE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:quirky|whimsical|comic|humorous|funny|witty|"
               r"light[-\s]hearted|cheerful|charming|delightful)\b", re.IGNORECASE),
    re.compile(r"\b(?:dark|gritty|gothic|horror|terrifying|creepy|"
               r"ominous|foreboding|sinister|macabre|bleak|grim)\b", re.IGNORECASE),
    re.compile(r"\b(?:cosmic|lovecraftian|eldritch|weird|strange|"
               r"surreal|dreamlike|nightmarish|unsettling)\b", re.IGNORECASE),
    re.compile(r"\b(?:epic|heroic|grand|majestic|sweeping|"
               r"legendary|mythic|larger[-\s]than[-\s]life)\b", re.IGNORECASE),
    re.compile(r"\b(?:intrigue|mystery|suspense|detective|investigat|"
               r"conspiracy|shadowy|secret|hidden|unknown)\b", re.IGNORECASE),
]


def _extract_tone_candidates(text: str) -> List[Dict[str, Any]]:
    """Extract tone/style marker phrases from source."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for pattern in _TONE_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            norm = phrase.lower()
            if norm in seen:
                continue
            seen.add(norm)
            candidates.append({
                "phrase": phrase,
                "line_start": _line_at(text, match.start()),
            })
    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTITY_TYPE_KEYWORDS: Dict[str, str] = {
    "npc_": "npc",
    "innkeeper": "npc",
    "wizard": "npc",
    "bard": "npc",
    "merchant": "npc",
    "guard": "npc",
    "assassin": "npc",
    "duergar": "npc",
    "kenku": "npc",
    "gnome": "npc",
    "dwarf": "npc",
    "elf": "npc",
    "halfling": "npc",
    "location": "location",
    "tower": "location",
    "inn": "location",
    "temple": "location",
    "gallery": "location",
    "tomb": "location",
    "grove": "location",
    "rookery": "location",
    "forge": "location",
    "vault": "location",
    "hall": "location",
    "cell": "location",
    "chamber": "location",
    "crossing": "location",
    "gate": "location",
    "portal": "location",
    "bridge": "location",
}


def _classify_entity_criticality(ent: Dict[str, Any]) -> str:
    """Assign criticality based on source evidence and context."""
    source = ent.get("source", "")
    if source in ("bold_span", "table_cell"):
        name_lower = ent.get("name", "").lower()
        for keyword, etype in _ENTITY_TYPE_KEYWORDS.items():
            if keyword in name_lower:
                ent["entity_type"] = etype
                return "required"
        return "major"
    if source == "quoted":
        return "major"
    return "ambiguous"


def _build_refs(candidate: Dict[str, Any],
                source_path: str) -> List[Dict[str, Any]]:
    """Build evidence reference list from a candidate dict."""
    refs: List[Dict[str, Any]] = [{
        "source_path": source_path,
        "section": candidate.get("section", ""),
        "line_start": candidate.get("line_start", 0),
        "line_end": candidate.get("line_end", candidate.get("line_start", 0)),
        "excerpt": candidate.get("context", candidate.get("description",
                                                          candidate.get("phrase", "")))[:_MAX_EXCERPT_CHARS],
    }]
    return refs


def _make_atom_id(source_hash: str, atom_type: str, name: str,
                  counter: int, refs: List[Dict[str, Any]]) -> str:
    """Build a stable atom ID using a hash prefix and readable identity."""
    hash_prefix = (source_hash or "")[:16]
    line_start = 0
    if refs:
        try:
            line_start = int(refs[0].get("line_start", 0) or 0)
        except Exception:
            line_start = 0
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or atom_type).lower()).strip("_")[:24]
    identity = f"{atom_type}|{name}|{line_start}|{counter}"
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"{hash_prefix}_{atom_type}_{slug}_{line_start}_{suffix}".strip("_")


def _dedupe_atoms(atoms: List[Dict[str, Any]]) -> None:
    """Remove duplicate atoms by type+name, keeping higher criticality."""
    best_atoms: Dict[str, Dict[str, Any]] = {}
    order = {"required": 0, "major": 1, "minor": 2, "ambiguous": 3, "ignore": 4}
    for atom in atoms:
        name = atom.get("name", "") or atom.get("summary", "")
        key = f"{atom['type']}:{name.lower()}"
        existing = best_atoms.get(key)
        if existing is None:
            best_atoms[key] = atom
            continue

        existing_priority = order.get(existing.get("criticality", "ambiguous"), 4)
        new_priority = order.get(atom.get("criticality", "ambiguous"), 4)
        if new_priority < existing_priority:
            atom["source_refs"] = _merge_source_refs(existing.get("source_refs", []) + atom.get("source_refs", []))
            best_atoms[key] = atom
        else:
            existing["source_refs"] = _merge_source_refs(existing.get("source_refs", []) + atom.get("source_refs", []))

    atoms[:] = list(best_atoms.values())


def _merge_source_refs(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicate source refs while preserving order."""
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for ref in refs:
        key = (
            ref.get("source_path", ""),
            ref.get("section", ""),
            ref.get("line_start", 0),
            ref.get("line_end", 0),
            ref.get("excerpt", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return merged
