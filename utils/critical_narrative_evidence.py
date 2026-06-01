# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Critical Narrative Evidence Pass
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic, provider-free detection of critical narrative omissions
by comparing benchmark source expectations against live module JSON
and the original source markdown.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.enhanced_logger import error, warning

MODULES_DIR = Path("modules")
BENCHMARKS_DIR = Path("data/benchmarks")

OMISSION_TYPE_MISSING_ACTOR = "missing_critical_actor"
OMISSION_TYPE_MISSING_PUZZLE = "missing_critical_puzzle"

CLASSIFICATION_BUILDER_REPAIR = "builder_repair_recommended"
CLASSIFICATION_ALIAS_VARIANT = "alias_variant_review"

# Surface groups tracked for honest reporting.
ACTOR_SURFACE_MODULE_CONTEXT = "module_context.json npcs"
ACTOR_SURFACE_MODULE_CONTEXT_NESTED = "module_context.json areas/locations npc refs"
ACTOR_SURFACE_AREA_LOCATIONS = "area location npcs entries"
ACTOR_SURFACES_CHECKED = [
    ACTOR_SURFACE_MODULE_CONTEXT,
    ACTOR_SURFACE_MODULE_CONTEXT_NESTED,
    ACTOR_SURFACE_AREA_LOCATIONS,
]

PUZZLE_SURFACE_MODULE_CONTEXT = "module_context puzzles"
PUZZLE_SURFACE_MODULE_PLOT = "module_plot plot points"
PUZZLE_SURFACE_AREA_TEXT = "area location descriptions/features/dcChecks"
PUZZLE_SURFACES_CHECKED = [
    PUZZLE_SURFACE_MODULE_CONTEXT,
    PUZZLE_SURFACE_MODULE_PLOT,
    PUZZLE_SURFACE_AREA_TEXT,
]

# Puzzle keyword map for heuristic detection in text fields.
_PUZZLE_KEYWORD_MAP: Dict[str, List[str]] = {
    "skull_riddle": ["skull", "first trial", "copper plate", "receptacle"],
    "flooding_room": ["flood", "water", "barracks", "rising water"],
    "kill_the_dog_mindscape": ["dog", "kill the dog", "false third trial"],
}


def _normalize_name(name: str) -> str:
    """Normalize an entity name for matching (lowercase, stripped)."""
    return name.strip().lower()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON file, returning None on failure."""
    try:
        if path.exists() and path.is_file():
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
    except Exception as exc:
        error(f"EVIDENCE: Failed to read {path}: {exc}", category="narrative_evidence")
    return None


def _get_module_dir(slug: str) -> Path:
    """Get the module directory for a given slug."""
    return MODULES_DIR / slug


def _get_benchmark_path(slug: str) -> Path:
    """Get the benchmark fixture path for a given module slug."""
    return BENCHMARKS_DIR / f"{slug}_benchmark.json"


def _truncate_excerpt(text: str, max_chars: int = 200) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


# ---------------------------------------------------------------------------
#  Source markdown reading
# ---------------------------------------------------------------------------

def _resolve_source_markdown_path(fixture: Dict[str, Any],
                                  module_slug: str) -> Optional[Path]:
    """Resolve the source markdown path from the benchmark fixture.

    Reads fixture.source_path and resolves relative to the repo root.
    Returns None if no path is set or the file does not exist.
    """
    raw = fixture.get("source_path", fixture.get("fixture_source_path", ""))
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    if p.exists() and p.is_file():
        return p
    # Try relative to repo root
    from_root = Path(".") / raw
    if from_root.exists() and from_root.is_file():
        return from_root
    return None


def _read_source_markdown(path: Path) -> Optional[str]:
    """Read the full text of a source markdown file.

    Returns None if the file does not exist or cannot be read.
    """
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as exc:
        error(f"EVIDENCE: Failed to read source markdown {path}: {exc}",
              category="narrative_evidence")
    return None


def _extract_source_excerpt(markdown: str, section_header: str,
                            max_chars: int = 300) -> str:
    """Extract a bounded excerpt under a markdown section heading.

    Reads from the heading line to the next same-level heading or
    page-break delimiter. Returns bounded text, truncated if needed.
    """
    # Build a regex for the section header (case-insensitive)
    pattern = re.compile(
        rf'^#{{1,4}}\s*{re.escape(section_header)}\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(markdown)
    if not match:
        return ""

    start = match.end()
    # Find next heading of same or higher level, or page break
    next_heading = re.search(
        r'^#{1,4}\s+\S|^\\page|^```\s*$',
        markdown[start:],
        re.MULTILINE,
    )
    end = start + next_heading.start() if next_heading else len(markdown)

    excerpt = markdown[start:end].strip()
    # Strip trailing empty formatting lines
    excerpt = re.sub(r'\n{3,}', '\n\n', excerpt)
    return _truncate_excerpt(excerpt, max_chars)


def _extract_source_markdown_excerpts(
    fixture: Dict[str, Any],
    module_slug: str,
) -> Dict[str, str]:
    """Extract bounded source excerpts from the original source markdown.

    Returns a dict mapping excerpt keys to bounded text snippets.
    """
    excerpts: Dict[str, str] = {}
    md_path = _resolve_source_markdown_path(fixture, module_slug)
    if md_path is None:
        return excerpts

    markdown = _read_source_markdown(md_path)
    if markdown is None:
        return excerpts

    # Kobe excerpt from the No-win scenario section
    kobe_raw = _extract_source_excerpt(markdown, "No-win scenario", max_chars=800)
    if kobe_raw:
        excerpts["kobe"] = kobe_raw
    else:
        # Fallback: search for 'Kobe' text
        for line in markdown.split("\n"):
            if "Kobe" in line:
                excerpts["kobe"] = _truncate_excerpt(line.strip(), 300)
                break

    # Skull riddle excerpt from The First Trial section
    trial_raw = _extract_source_excerpt(markdown, "The First Trial", max_chars=400)
    if trial_raw:
        excerpts["skull_riddle"] = trial_raw
    else:
        excerpts["skull_riddle"] = ""  # will use fixture description

    # Flooding room excerpt from The Second Trial section
    flood_raw = _extract_source_excerpt(markdown, "The Second Trial", max_chars=400)
    if flood_raw:
        excerpts["flooding_room"] = flood_raw
    else:
        excerpts["flooding_room"] = ""

    return excerpts


# ---------------------------------------------------------------------------
#  Source excerpt indexing (agent-run support)
# ---------------------------------------------------------------------------

def _extract_bounded_source_excerpt_with_lines(
    markdown: str,
    section_header: str,
    max_chars: int = 1200,
) -> Dict[str, Any]:
    """Extract a bounded source excerpt with line metadata.

    Returns a dict with excerpt, start_line, end_line, char_count.
    Line fields are 1-indexed, null if unavailable.
    """
    result: Dict[str, Any] = {
        "excerpt": "",
        "start_line": None,
        "end_line": None,
        "char_count": 0,
    }

    pattern = re.compile(
        rf'^#{{1,4}}\s*{re.escape(section_header)}\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(markdown)
    if not match:
        return result

    # Count lines before the match start to get start_line
    before = markdown[:match.start()]
    start_line = before.count("\n") + 1

    excerpt_start = match.end()
    # Find next heading or page break
    next_heading = re.search(
        r'^#{1,4}\s+\S|^\\page|^```\s*$',
        markdown[excerpt_start:],
        re.MULTILINE,
    )
    excerpt_end = excerpt_start + next_heading.start() if next_heading else len(markdown)

    excerpt = markdown[excerpt_start:excerpt_end].strip()
    excerpt = re.sub(r'\n{3,}', '\n\n', excerpt)
    excerpt = _truncate_excerpt(excerpt, max_chars)
    result["excerpt"] = excerpt
    result["start_line"] = start_line
    # Count lines in the excerpt
    result["end_line"] = start_line + excerpt.count("\n")
    result["char_count"] = len(excerpt)
    return result


def build_source_excerpt_index(
    fixture: Dict[str, Any],
    module_slug: str,
) -> Dict[str, Any]:
    """Build a structured source excerpt index for the agent run.

    Returns a dict mapping entity keys to excerpt records with:
      name, type, source_path, excerpt, start_line, end_line, char_count.
    """
    index: Dict[str, Any] = {}
    md_path = _resolve_source_markdown_path(fixture, module_slug)
    if md_path is None:
        return index

    markdown = _read_source_markdown(md_path)
    if markdown is None:
        return index

    source_path_str = str(md_path)

    # Kobe
    kobe = _extract_bounded_source_excerpt_with_lines(
        markdown, "No-win scenario", max_chars=1200,
    )
    if kobe["excerpt"]:
        kobe["name"] = "Kobe"
        kobe["type"] = OMISSION_TYPE_MISSING_ACTOR
        kobe["source_path"] = source_path_str
        index["kobe"] = kobe

    # skull_riddle
    skull = _extract_bounded_source_excerpt_with_lines(
        markdown, "The First Trial", max_chars=1200,
    )
    if skull["excerpt"]:
        skull["name"] = "skull_riddle"
        skull["type"] = OMISSION_TYPE_MISSING_PUZZLE
        skull["source_path"] = source_path_str
        index["skull_riddle"] = skull

    # flooding_room
    flood = _extract_bounded_source_excerpt_with_lines(
        markdown, "The Second Trial", max_chars=1200,
    )
    if flood["excerpt"]:
        flood["name"] = "flooding_room"
        flood["type"] = OMISSION_TYPE_MISSING_PUZZLE
        flood["source_path"] = source_path_str
        index["flooding_room"] = flood

    return index


# ---------------------------------------------------------------------------
#  Live surface inspection
# ---------------------------------------------------------------------------

def _collect_module_npcs(module_context: Optional[Dict[str, Any]]) -> List[str]:
    """Collect display names of all NPCs registered in module_context.json."""
    names: List[str] = []
    if not module_context:
        return names
    npcs = module_context.get("npcs", {})
    if not isinstance(npcs, dict):
        return names
    for slug, entry in npcs.items():
        name = entry.get("name", slug)
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return sorted(set(names))


def _collect_module_context_nested_npcs(
    module_context: Optional[Dict[str, Any]],
) -> List[str]:
    """Collect NPC references from module_context nested surfaces.

    Scans:
      - module_context.areas[area_id].npcs
      - module_context.locations[loc_id] for npcs, notableNPCs,
        visibleNPCs, sceneNPCs
    """
    names: List[str] = []
    if not module_context:
        return names

    # Scan areas block
    areas = module_context.get("areas", {})
    if isinstance(areas, dict):
        for area_id, area in areas.items():
            if not isinstance(area, dict):
                continue
            for entry in area.get("npcs", []):
                if isinstance(entry, str):
                    names.append(entry.strip())
                elif isinstance(entry, dict):
                    n = entry.get("name", entry.get("id", ""))
                    if isinstance(n, str) and n.strip():
                        names.append(n.strip())

    # Scan locations block
    locations = module_context.get("locations", {})
    if isinstance(locations, dict):
        for loc_id, loc in locations.items():
            if not isinstance(loc, dict):
                continue
            for key in ("npcs", "notableNPCs", "visibleNPCs", "sceneNPCs"):
                for entry in loc.get(key, []):
                    if isinstance(entry, str):
                        names.append(entry.strip())
                    elif isinstance(entry, dict):
                        n = entry.get("name", entry.get("id", ""))
                        if isinstance(n, str) and n.strip():
                            names.append(n.strip())

    return sorted(set(names))


def _collect_area_npc_names(module_slug: str) -> List[str]:
    """Collect NPC display names from area BU files location entries.

    Scans modules/<slug>/areas/*_BU.json for location-level npcs arrays.
    """
    names: Set[str] = set()
    area_dir = _get_module_dir(module_slug) / "areas"
    if not area_dir.exists() or not area_dir.is_dir():
        return sorted(names)

    for fpath in sorted(area_dir.glob("*_BU.json")):
        data = _load_json(fpath)
        if not data:
            continue
        locations = data.get("locations", [])
        if not isinstance(locations, list):
            continue
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            for entry in loc.get("npcs", []):
                if isinstance(entry, str):
                    names.add(entry.strip())
                elif isinstance(entry, dict):
                    n = entry.get("name", entry.get("id", ""))
                    if isinstance(n, str) and n.strip():
                        names.add(n.strip())
    return sorted(names)


def _collect_puzzles_from_module_context(
    module_context: Optional[Dict[str, Any]],
) -> Set[str]:
    """Collect puzzle IDs from module_context.json puzzles block."""
    ids: Set[str] = set()
    if not module_context:
        return ids
    puzzles = module_context.get("puzzles")
    if not isinstance(puzzles, list):
        return ids
    for p in puzzles:
        pid = p.get("id", p.get("name", "")) if isinstance(p, dict) else str(p)
        if pid.strip():
            ids.add(_normalize_name(pid.strip()))
    return ids


def _collect_puzzles_from_plot(
    module_plot: Optional[Dict[str, Any]],
) -> Set[str]:
    """Collect puzzle IDs from module_plot plot-point text fields."""
    ids: Set[str] = set()
    if not module_plot:
        return ids
    plot_points = module_plot.get("plotPoints", module_plot.get("plot_points", []))
    if not isinstance(plot_points, list):
        return ids
    for pp in plot_points:
        if not isinstance(pp, dict):
            continue
        text = " ".join([
            pp.get("title", ""),
            pp.get("description", ""),
        ]).lower()
        for puzzle_id, keywords in _PUZZLE_KEYWORD_MAP.items():
            if any(kw in text for kw in keywords):
                ids.add(puzzle_id)
    return ids


def _collect_puzzles_from_area_text(module_slug: str) -> Set[str]:
    """Collect puzzle IDs from area BU file text fields.

    Checks description, dmInstructions, features, dcChecks,
    and plotHooks for puzzle keywords.
    """
    ids: Set[str] = set()
    area_dir = _get_module_dir(module_slug) / "areas"
    if not area_dir.exists() or not area_dir.is_dir():
        return ids

    for fpath in sorted(area_dir.glob("*_BU.json")):
        data = _load_json(fpath)
        if not data:
            continue
        locations = data.get("locations", [])
        if not isinstance(locations, list):
            continue
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            text_parts: List[str] = [
                loc.get("description", ""),
                loc.get("dmInstructions", ""),
            ]
            # features
            for feat in loc.get("features", []):
                if isinstance(feat, dict):
                    text_parts.append(feat.get("description", ""))
                    text_parts.append(feat.get("text", ""))
                elif isinstance(feat, str):
                    text_parts.append(feat)
            # dcChecks
            for check in loc.get("dcChecks", []):
                if isinstance(check, dict):
                    text_parts.append(check.get("description", ""))
                    text_parts.append(check.get("name", ""))
                elif isinstance(check, str):
                    text_parts.append(check)
            # plotHooks
            for hook in loc.get("plotHooks", []):
                if isinstance(hook, dict):
                    text_parts.append(hook.get("description", ""))
                elif isinstance(hook, str):
                    text_parts.append(hook)
            # Adventure summary
            text_parts.append(loc.get("adventureSummary", ""))

            combined = " ".join(text_parts).lower()
            for puzzle_id, keywords in _PUZZLE_KEYWORD_MAP.items():
                if any(kw in combined for kw in keywords):
                    ids.add(puzzle_id)
    return ids


# ---------------------------------------------------------------------------
#  Source description extraction (from fixture)
# ---------------------------------------------------------------------------

def _extract_lore_source_descriptions(fixture: Dict[str, Any]) -> Dict[str, str]:
    """Extract lore source_descriptions from benchmark fixture.

    Fixture nesting: expectations -> lore_preservation -> source_descriptions
    """
    expectations = fixture.get("expectations", {})
    lore = expectations.get("lore_preservation", {})
    descs = lore.get("source_descriptions", {})
    if isinstance(descs, dict):
        return {str(k): str(v) for k, v in descs.items()}
    return {}


def _extract_puzzle_source_descriptions(fixture: Dict[str, Any]) -> Dict[str, str]:
    """Extract puzzle source_descriptions from benchmark fixture.

    Fixture nesting: expectations -> puzzle_preservation -> source_descriptions
    """
    expectations = fixture.get("expectations", {})
    puzzle = expectations.get("puzzle_preservation", {})
    descs = puzzle.get("source_descriptions", {})
    if isinstance(descs, dict):
        return {str(k): str(v) for k, v in descs.items()}
    return {}


# ---------------------------------------------------------------------------
#  Alias variant detection
# ---------------------------------------------------------------------------

def _normalize_clean(name: str) -> str:
    """Normalize and strip parenthetical content for alias matching."""
    cleaned = re.sub(r'\([^)]*\)', '', name)
    return _normalize_name(cleaned)


def _has_alias_in_live(actor_name: str, live_npc_names: List[str]) -> bool:
    """Check if an actor name has an alias or name variant in live NPCs.

    Returns True when any live NPC name matches the expected name through
    substring, token overlap, or parenthetical alias resolution.

    Catches cases like:
      'Wayne (Waynobibille Nebiddlespun)' vs 'Wayne'
      'Wayne (Waynobibille Nebiddlespun)' vs 'Waynobibille Nebiddlespun'
    """
    norm_actor = _normalize_name(actor_name)
    # Also strip parenthetical for broader matching
    clean_actor = _normalize_clean(actor_name)

    for live in live_npc_names:
        norm_live = _normalize_name(live)
        clean_live = _normalize_clean(live)

        # Exact match (including parenthetical)
        if norm_actor == norm_live:
            return True
        if clean_actor == norm_live:
            return True
        if norm_actor == clean_live:
            return True
        if clean_actor == clean_live:
            return True

        # Substring: one is wholly contained in the other
        if norm_live in norm_actor or norm_actor in norm_live:
            return True

        # Token overlap after parenthetical stripping
        actor_tokens = set(clean_actor.split())
        live_tokens = set(clean_live.split())
        if not actor_tokens or not live_tokens:
            continue
        if actor_tokens.issubset(live_tokens) or live_tokens.issubset(actor_tokens):
            return True
        # Single-token check
        if len(actor_tokens) == 1 and list(actor_tokens)[0] in norm_live:
            return True
        if len(live_tokens) == 1 and list(live_tokens)[0] in norm_actor:
            return True
        # Any token from expected name appears in live name
        if any(tok in norm_live for tok in actor_tokens if len(tok) > 3):
            return True
    return False


# ---------------------------------------------------------------------------
#  Detection functions
# ---------------------------------------------------------------------------

def detect_missing_actors(
    expected_actor_names: List[str],
    live_module_npcs: List[str],
    live_area_npcs: List[str],
    module_slug: str,
    fixture: Dict[str, Any],
    source_excerpts: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Detect expected actors absent from live module NPC surfaces.

    Args:
        expected_actor_names: Actor names from the source benchmark fixture.
        live_module_npcs: Names from module_context.json npcs section.
        live_area_npcs: Names from area BU files location npcs entries.
        fixture: Full benchmark fixture (for lore descriptions).
        source_excerpts: Bounded source markdown excerpts.

    Returns:
        List of omission evidence dicts. Alias/normalization misses are
        classified as alias_variant_review, not builder_repair_recommended.
    """
    all_live = sorted(set(live_module_npcs + live_area_npcs))
    live_norm = {_normalize_name(n) for n in all_live}
    lore_descs = _extract_lore_source_descriptions(fixture)
    critical: List[Dict[str, Any]] = []
    reviews: List[Dict[str, Any]] = []

    # Determine which surfaces were actually checked
    checked_surfaces: List[str] = [
        ACTOR_SURFACE_MODULE_CONTEXT,
        ACTOR_SURFACE_MODULE_CONTEXT_NESTED,
    ]
    area_dir = _get_module_dir(module_slug) / "areas"
    if area_dir.exists() and area_dir.is_dir():
        checked_surfaces.append(ACTOR_SURFACE_AREA_LOCATIONS)

    for actor_name in expected_actor_names:
        norm = _normalize_name(actor_name)
        if norm in live_norm:
            continue

        # Classification: alias variant or critical omission
        if _has_alias_in_live(actor_name, all_live):
            classification = CLASSIFICATION_ALIAS_VARIANT
        else:
            classification = CLASSIFICATION_BUILDER_REPAIR

        # Source description
        source_desc = ""
        if classification == CLASSIFICATION_BUILDER_REPAIR:
            # Only use Kobe excerpt when the missing actor IS Kobe
            if norm == _normalize_name("Kobe"):
                source_desc = source_excerpts.get("kobe", "")
        if not source_desc:
            for lore_text in lore_descs.values():
                if norm in _normalize_name(lore_text):
                    source_desc = lore_text
                    break
        if not source_desc:
            source_desc = (
                f"Actor '{actor_name}' is expected by the source benchmark "
                f"but is absent from the live module NPC surfaces."
            )

        missing_surfaces = list(checked_surfaces)
        present_surfaces: List[str] = []

        item = {
            "name": actor_name,
            "type": OMISSION_TYPE_MISSING_ACTOR,
            "classification": classification,
            "source_ref": {
                "description": _truncate_excerpt(source_desc, max_chars=600),
                "source": "numillian_benchmark.v1",
                "fixture_field": "expectations.npc_preservation.named_source_npcs",
            },
            "missing_surfaces": missing_surfaces,
            "present_surfaces": present_surfaces,
        }

        if classification == CLASSIFICATION_BUILDER_REPAIR:
            critical.append(item)
        else:
            reviews.append(item)

    return {
        "critical_omissions": critical,
        "review_items": reviews,
    }


def detect_missing_puzzles(
    expected_puzzle_ids: List[str],
    live_puzzles_context: Set[str],
    live_puzzles_plot: Set[str],
    live_puzzles_area: Set[str],
    fixture: Dict[str, Any],
    source_excerpts: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Detect expected puzzles absent from live module puzzle surfaces.

    Args:
        expected_puzzle_ids: Puzzle IDs from the benchmark fixture.
        live_puzzles_context: Puzzle IDs from module_context.json.
        live_puzzles_plot: Puzzle IDs from module_plot.json.
        live_puzzles_area: Puzzle IDs from area BU files.
        fixture: Full benchmark fixture (for puzzle descriptions).
        source_excerpts: Bounded source markdown excerpts.

    Returns:
        List of omission evidence dicts.
    """
    all_live = live_puzzles_context | live_puzzles_plot | live_puzzles_area
    puzzle_descs = _extract_puzzle_source_descriptions(fixture)
    omissions: List[Dict[str, Any]] = []

    # Determine which surfaces were actually checked
    checked_surfaces: List[str] = [
        PUZZLE_SURFACE_MODULE_CONTEXT,
        PUZZLE_SURFACE_MODULE_PLOT,
        PUZZLE_SURFACE_AREA_TEXT,
    ]

    for puzzle_id in expected_puzzle_ids:
        norm = _normalize_name(puzzle_id)
        if norm in all_live:
            continue

        # Source description: prefer markdown excerpt (by puzzle id), then fixture, then fallback
        source_desc = source_excerpts.get(puzzle_id, "")
        if not source_desc:
            source_desc = puzzle_descs.get(puzzle_id, "")
        if not source_desc:
            source_desc = (
                f"Puzzle '{puzzle_id}' is expected by the source benchmark "
                f"but is absent from the live module puzzle surfaces."
            )

        # Build per-surface presence
        missing_surfaces: List[str] = []
        present_surfaces: List[str] = []

        if norm not in live_puzzles_context:
            missing_surfaces.append(PUZZLE_SURFACE_MODULE_CONTEXT)
        else:
            present_surfaces.append(PUZZLE_SURFACE_MODULE_CONTEXT)

        if norm not in live_puzzles_plot:
            missing_surfaces.append(PUZZLE_SURFACE_MODULE_PLOT)
        else:
            present_surfaces.append(PUZZLE_SURFACE_MODULE_PLOT)

        if norm not in live_puzzles_area:
            missing_surfaces.append(PUZZLE_SURFACE_AREA_TEXT)
        else:
            present_surfaces.append(PUZZLE_SURFACE_AREA_TEXT)

        omission = {
            "name": puzzle_id,
            "type": OMISSION_TYPE_MISSING_PUZZLE,
            "classification": CLASSIFICATION_BUILDER_REPAIR,
            "source_ref": {
                "description": _truncate_excerpt(source_desc, max_chars=400),
            },
            "missing_surfaces": missing_surfaces,
            "present_surfaces": present_surfaces,
        }
        omissions.append(omission)

    return omissions


# ---------------------------------------------------------------------------
#  Main evidence pass
# ---------------------------------------------------------------------------

def run_critical_omission_evidence_pass(
    module_slug: str,
) -> Dict[str, Any]:
    """Run the critical narrative omission evidence pass for a module.

    Reads the benchmark fixture, source markdown, and live module JSON,
    then compares source expectations against current state. Returns
    structured evidence of all critical omissions found.

    Args:
        module_slug: Module directory name (e.g. 'The_Hidden_City_of_Numillian').

    Returns:
        A dict with:
          - module_slug: Module identifier.
          - source_markdown_read: Whether the source markdown was successfully read.
          - source_markdown_path: The resolved markdown path (or null).
          - critical_omissions: List of omission evidence dicts.
          - pass_count: Number of evidence checks that passed (no omission).
          - fail_count: Number of omissions detected.
          - error: Error message if the pass failed entirely.
    """
    result: Dict[str, Any] = {
        "module_slug": module_slug,
        "source_markdown_read": False,
        "source_markdown_path": None,
        "critical_omissions": [],
        "review_items": [],
        "pass_count": 0,
        "fail_count": 0,
        "review_count": 0,
        "error": None,
    }

    # Load benchmark fixture
    fixture_path = _get_benchmark_path(module_slug)
    fixture = _load_json(fixture_path)
    if fixture is None:
        result["error"] = f"Benchmark fixture not found or invalid: {fixture_path}"
        return result

    expectations = fixture.get("expectations", {})
    if not isinstance(expectations, dict):
        result["error"] = "Benchmark fixture missing expectations block"
        return result

    # Read source markdown for bounded excerpts
    md_path = _resolve_source_markdown_path(fixture, module_slug)
    result["source_markdown_path"] = str(md_path) if md_path else None
    source_excerpts = _extract_source_markdown_excerpts(fixture, module_slug)
    result["source_markdown_read"] = bool(source_excerpts)

    # Load live module JSON
    module_dir = _get_module_dir(module_slug)
    module_context = _load_json(module_dir / "module_context.json")
    module_plot = _load_json(module_dir / "module_plot.json")

    if module_context is None:
        warning(
            f"EVIDENCE: module_context.json not found for {module_slug}",
            category="narrative_evidence",
        )

    # --- NPC / Actor gap detection ---
    npc_section = expectations.get("npc_preservation", {})
    expected_actor_names = npc_section.get("named_source_npcs", [])
    if isinstance(expected_actor_names, list) and expected_actor_names:
        live_module_npcs = sorted(set(
            _collect_module_npcs(module_context) +
            _collect_module_context_nested_npcs(module_context)
        ))
        live_area_npcs = _collect_area_npc_names(module_slug)
        actor_omissions = detect_missing_actors(
            expected_actor_names, live_module_npcs, live_area_npcs,
            module_slug, fixture, source_excerpts,
        )
        result["critical_omissions"].extend(actor_omissions.get("critical_omissions", []))
        result["review_items"].extend(actor_omissions.get("review_items", []))

    # --- Puzzle gap detection ---
    puzzle_section = expectations.get("puzzle_preservation", {})
    expected_puzzle_ids = puzzle_section.get("required_puzzles", [])
    if isinstance(expected_puzzle_ids, list) and expected_puzzle_ids:
        live_puzzles_context = _collect_puzzles_from_module_context(module_context)
        live_puzzles_plot = _collect_puzzles_from_plot(module_plot)
        live_puzzles_area = _collect_puzzles_from_area_text(module_slug)
        puzzle_omissions = detect_missing_puzzles(
            expected_puzzle_ids,
            live_puzzles_context, live_puzzles_plot, live_puzzles_area,
            fixture, source_excerpts,
        )
        result["critical_omissions"].extend(puzzle_omissions)

    # --- Count pass/fail ---
    actor_count = len(expected_actor_names) if isinstance(expected_actor_names, list) else 0
    puzzle_count = len(expected_puzzle_ids) if isinstance(expected_puzzle_ids, list) else 0
    missing_count = len(result["critical_omissions"])
    total_checks = actor_count + puzzle_count

    result["pass_count"] = total_checks - missing_count
    result["fail_count"] = missing_count
    result["review_count"] = len(result["review_items"])

    return result


# ---------------------------------------------------------------------------
#  Agent run evidence writer
# ---------------------------------------------------------------------------

_TARGET_SURFACES_KOBE = [
    "module_context.json npcs",
    "module_context areas/locations npc refs",
    "area location npcs entries",
    "final trial plot/objective surfaces",
]

_TARGET_SURFACES_SKULL = [
    "module_plot.json trial/puzzle plot surfaces",
    "area location descriptions/features/dcChecks/puzzle surfaces",
    "module_context puzzle/source-lock surfaces",
]

_TARGET_SURFACES_FLOOD = [
    "module_plot.json trial/puzzle plot surfaces",
    "area location descriptions/features/dcChecks/puzzle surfaces",
]

_NO_MANUAL_REPAIR_GUARDRAILS = """\
Python has NOT authored the repair content below.
The Builder LLM MUST synthesize source-faithful narrative repair
from the source excerpts. The excerpts are bounded and deterministic;
they are NOT pre-written module JSON. Do NOT copy excerpts verbatim
into module files.
"""

_FORBIDDEN_INPUTS_BLOCK = """\
Forbidden inputs:
- MODULE_SUMMARY.md (derived output only - use source markdown instead)
- Benchmark thresholds or scanner logic edits
- Benchmark fixture edits
- Manual JSON string injection into module files
- Tool-generated placeholder removal without source-faithful replacement
"""

_DO_NOT_USE_BLOCK = """\
- Do not use MODULE_SUMMARY.md as repair input.
- Do not edit benchmark thresholds, scanner logic, or fixture files.
- Do not manually inject JSON strings into module files.
- Do not edit report-only status fields to bypass gates.
- Do not invent replacement puzzles or substitute NPCs."""

_SOURCE_LOCK_CONSTRAINTS = """\
- Source markdown is authoritative for narrative content.
- Kobe is the final no-win trial actor/objective. Do not rename, remove, or replace.
- skull_riddle is the First Trial puzzle (three skulls, three receptacles, riddle logic).
  It is NOT three NPC-only skull atoms without puzzle context.
- flooding_room is the Second Trial puzzle/trial (barracks, rising water, escape items).
- Preserve the adventure-arc trial topology (First Trial -> Second Trial -> ... -> No-Win Scenario).
  This is separate from map/location topology.
- Do not invent replacement puzzles, substitute NPCs, or genericize the source beats."""

_ACCEPTANCE_CHECKS = """\
- `run_critical_omission_evidence_pass()` no longer reports Kobe as a critical omission.
- `run_critical_omission_evidence_pass()` no longer reports skull_riddle as a critical omission.
- `run_critical_omission_evidence_pass()` no longer reports flooding_room as a critical omission.
- Wayne remains review-only or is resolved as a non-blocking alias; it must not become a
  false builder_repair_recommended blocker.
- Benchmark source fidelity passes for NPC, puzzle, location, lore, and tone dimensions.
- Schema validation must still pass, or blockers must be reported separately from
  critical narrative repair."""

_REPAIR_TARGETS = """\
### Kobe
- module_context.json NPC/character surfaces
- module_context areas/locations NPC/character references
- Final trial plot/objective surfaces
- Area/location scene objective surfaces if needed

### skull_riddle
- module_plot.json trial/puzzle plot surfaces
- Area/location descriptions, features, dcChecks, puzzle surfaces
- module_context puzzle/source-lock surfaces

### flooding_room
- module_plot.json trial/puzzle plot surfaces
- Area/location descriptions, features, dcChecks, puzzle surfaces"""


def _atomic_write(path: Path, content: str) -> bool:
    """Write content to a file atomically using a temp file and rename."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception as exc:
        error(f"AGENT_RUN: Failed to write {path}: {exc}",
              category="narrative_evidence")
        return False


def _generate_task_id(module_slug: str) -> str:
    """Generate a deterministic-ish timestamped task id."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{module_slug.lower()}-critical-narrative-{ts}"


def build_critical_narrative_agent_run(
    evidence: Dict[str, Any],
    module_slug: str,
    task_id: str,
) -> Dict[str, Any]:
    """Build an agent-run evidence package from the evidence pass result.

    Does NOT write files. Returns a dict with all artifact content
    and metadata that `write_critical_narrative_agent_run` consumes.
    """
    md_path = evidence.get("source_markdown_path")
    md_read = evidence.get("source_markdown_read", False)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    run = {
        "task_id": task_id,
        "module_slug": module_slug,
        "created_at": created_at,
        "status": "evidence_collected",
        "source_markdown_path": md_path,
        "source_markdown_read": md_read,
        "evidence_file": "critical_evidence.json",
        "source_excerpts_file": "source_excerpts.json",
        "builder_repair_brief_file": "builder_repair_brief.md",
        "fail_count": evidence.get("fail_count", 0),
        "review_count": evidence.get("review_count", 0),
    }

    critical_evidence = {
        "module_slug": module_slug,
        "critical_omissions": evidence.get("critical_omissions", []),
        "review_items": evidence.get("review_items", []),
        "fail_count": evidence.get("fail_count", 0),
        "review_count": evidence.get("review_count", 0),
        "source_markdown_path": md_path,
        "source_markdown_read": md_read,
    }

    # Build source excerpts with line info from the markdown
    fixture = _load_json(_get_benchmark_path(module_slug))
    excerpt_index = {}
    if fixture:
        excerpt_index = build_source_excerpt_index(fixture, module_slug)

    # Build the brief
    brief = _render_builder_repair_brief(
        module_slug, evidence, excerpt_index,
    )

    return {
        "run": run,
        "critical_evidence": critical_evidence,
        "source_excerpts": excerpt_index,
        "builder_repair_brief": brief,
    }


def write_critical_narrative_agent_run(
    output_dir: Path,
    package: Dict[str, Any],
) -> Dict[str, Any]:
    """Write agent-run artifacts to disk atomically.

    Returns a dict of written file paths keyed by artifact name.
    """
    files: Dict[str, str] = {}
    run = package.get("run", {})

    def _w(key: str, filename: str, payload: Any) -> None:
        fpath = output_dir / filename
        if isinstance(payload, str):
            ok = _atomic_write(fpath, payload)
        else:
            ok = _atomic_write(fpath, json.dumps(payload, indent=2, ensure_ascii=False))
        if ok:
            files[key] = str(fpath)

    _w("critical_evidence", run.get("evidence_file", "critical_evidence.json"),
       package.get("critical_evidence", {}))
    _w("source_excerpts", run.get("source_excerpts_file", "source_excerpts.json"),
       package.get("source_excerpts", {}))
    _w("builder_repair_brief", run.get("builder_repair_brief_file", "builder_repair_brief.md"),
       package.get("builder_repair_brief", ""))
    _w("run", "run.json", run)

    return files


def _render_builder_repair_brief(
    module_slug: str,
    evidence: Dict[str, Any],
    excerpt_index: Dict[str, Any],
) -> str:
    """Render a Builder-facing repair brief from critical narrative evidence."""
    lines: List[str] = []
    lines.append(f"# Critical Narrative Repair Brief - {module_slug}")
    lines.append("")

    lines.append("## Module")
    lines.append("")
    lines.append(f"- **Module slug:** `{module_slug}`")
    lines.append(f"- **Evidence status:** {evidence.get('fail_count', 0)} critical "
                 f"omissions, {evidence.get('review_count', 0)} alias review items")
    lines.append(f"- **Source markdown read:** {evidence.get('source_markdown_read', False)}")
    lines.append("")

    lines.append("## Critical Omissions Summary")
    lines.append("")
    for o in evidence.get("critical_omissions", []):
        name = o.get("name", "?")
        otype = o.get("type", "?")
        classification = o.get("classification", "?")
        lines.append(f"- **[{otype}] {name}** - `{classification}`")
        missing = o.get("missing_surfaces", [])
        if missing:
            lines.append(f"  - Missing from: {', '.join(missing)}")
    lines.append("")

    lines.append("## Source-Lock Constraints")
    lines.append("")
    lines.append(_SOURCE_LOCK_CONSTRAINTS)
    lines.append("")

    lines.append("## Source Excerpts")
    lines.append("")
    for key, rec in sorted(excerpt_index.items()):
        name = rec.get("name", key)
        lines.append(f"### {name}")
        lines.append(f"- **Source path:** `{rec.get('source_path', '?')}`")
        if rec.get("start_line"):
            lines.append(f"- **Lines:** {rec.get('start_line')}-{rec.get('end_line')} "
                         f"({rec.get('char_count', 0)} chars)")
        lines.append("")
        lines.append("```text")
        lines.append(rec.get("excerpt", ""))
        lines.append("```")
        lines.append("")
    lines.append("")

    lines.append("## Required Repair Targets")
    lines.append("")
    lines.append(_REPAIR_TARGETS)
    lines.append("")

    lines.append("## Builder Instructions")
    lines.append("")
    lines.append(_NO_MANUAL_REPAIR_GUARDRAILS)
    lines.append("")
    lines.append("### Source-Faithful Narrative Repair Contract")
    lines.append("")
    lines.append("- Synthesize missing narrative content from the source excerpts above.")
    lines.append("- Do NOT invent new characters, puzzles, or locations.")
    lines.append("- Write into the correct module surfaces listed under Required Repair Targets.")
    lines.append("- Preserve existing module content; only add missing narrative elements.")
    lines.append("- Use source-voice prose appropriate to the original markdown.")
    lines.append("")

    lines.append("### Do Not Use")
    lines.append("")
    lines.append(_DO_NOT_USE_BLOCK)
    lines.append("")
    lines.append("### Forbidden Inputs")
    lines.append("")
    lines.append(_FORBIDDEN_INPUTS_BLOCK)
    lines.append("")

    lines.append("## Acceptance Checks For Later Repair")
    lines.append("")
    lines.append(_ACCEPTANCE_CHECKS)
    lines.append("")

    lines.append("## Release Blocking")
    lines.append("")
    lines.append("These critical omissions block release proof until repaired and verified.")
    lines.append("After repair, re-run the benchmark and evidence pass to confirm closure.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  Summary formatting
# ---------------------------------------------------------------------------

def format_evidence_summary(evidence: Dict[str, Any]) -> str:
    """Format a compact human-readable summary of evidence results."""
    lines: List[str] = []
    slug = evidence.get("module_slug", "?")
    error_msg = evidence.get("error")

    if error_msg:
        lines.append(f"[EVIDENCE_ERROR] {slug}: {error_msg}")
        return "\n".join(lines)

    src_read = evidence.get("source_markdown_read", False)
    src_path = evidence.get("source_markdown_path")
    fail_count = evidence.get("fail_count", 0)
    review_count = evidence.get("review_count", 0)
    lines.append(f"[EVIDENCE] {slug}: {evidence.get('pass_count', 0)} checks pass, "
                 f"{fail_count} critical omissions"
                 f"{', ' + str(review_count) + ' review items' if review_count else ''}")
    lines.append(f"  source_markdown_read={src_read}"
                 f"{'' if not src_path else ' path=' + src_path}")

    omissions = evidence.get("critical_omissions", [])
    if omissions:
        lines.append(f"  --- Critical Omissions ---")
        for o in omissions:
            o_type = o.get("type", "?")
            o_name = o.get("name", "?")
            o_class = o.get("classification", "?")
            src_desc = o.get("source_ref", {}).get("description", "")
            missing_surfaces = o.get("missing_surfaces", [])
            present_surfaces = o.get("present_surfaces", [])

            lines.append(f"  [{o_type}] {o_name}")
            lines.append(f"    classification: {o_class}")
            lines.append(f"    source: {_truncate_excerpt(src_desc, 160)}")
            if missing_surfaces:
                lines.append(f"    missing from: {', '.join(missing_surfaces)}")
            if present_surfaces:
                lines.append(f"    present in: {', '.join(present_surfaces)}")

    reviews = evidence.get("review_items", [])
    if reviews:
        lines.append(f"  --- Review Items (non-blocking) ---")
        for r in reviews:
            r_type = r.get("type", "?")
            r_name = r.get("name", "?")
            r_class = r.get("classification", "?")
            lines.append(f"  [{r_type}] {r_name}")
            lines.append(f"    classification: {r_class}")

    return "\n".join(lines)
