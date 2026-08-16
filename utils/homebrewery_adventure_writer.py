# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
Homebrewery Adventure Writer - Generate V3 Homebrewery markdown from NEQ module data.

Reads module context, plot, area, monster, and map data from a NeverEndingQuest
module directory and produces a complete Homebrewery V3 adventure document suitable
for pasting into https://homebrewery.naturalcrit.com/new .

Usage:
    from utils.homebrewery_adventure_writer import generate_homebrewery_adventure

    md = generate_homebrewery_adventure("The_Ancients_Lab")
    with open("modules/The_Ancients_Lab/MODULE_SUMMARY.md", "w") as f:
        f.write(md)
"""

import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.homebrewery_style import (
    COLUMN_BREAK,
    CREDITS_SNIPPET,
    FRONT_COVER_SNIPPET,
    PAGE_BREAK,
    MONSTER_PORTRAIT_URL,
    NPC_PORTRAIT_URL,
    COVER_IMAGE_URL,
    format_cover_page,
    format_item_block,
    format_metadata,
    format_monster_statblock,
    _format_damage_dice,
    sanitize_markdown_text,
)

MODULES_DIR = Path("modules")


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------


def load_module_data(module_slug: str) -> Dict[str, Any]:
    """Load all module data sources into a unified dict.

    Prefers _BU (backup/canonical) files, falling back to live files.
    """
    module_dir = MODULES_DIR / module_slug
    data: Dict[str, Any] = {
        "module_slug": module_slug,
        "display_name": module_slug.replace("_", " "),
        "author": "",
        "license": "",
        "npcs": {},
        "plot_points": [],
        "areas": [],
        "monsters": [],
        "maps": [],
        "_cross_area_edges": [],
    }

    # Module context - prefer BU for structure, merge live for narrative
    ctx_path_bu = module_dir / "module_context_BU.json"
    ctx_path_live = module_dir / "module_context.json"
    ctx_live = {}
    if ctx_path_bu.exists():
        ctx = _safe_json_load(ctx_path_bu) or {}
    elif ctx_path_live.exists():
        ctx = _safe_json_load(ctx_path_live) or {}
    else:
        ctx = {}
    if ctx:
        data["npcs"] = ctx.get("npcs", {})
        data["main_objective"] = ctx.get("mainObjective", "")
        data["author"] = ctx.get("author", "")
        data["license"] = ctx.get("license", "")
    # Merge narrative-enriched data from live file where BU is empty
    if ctx_path_live.exists() and ctx_path_live.stat().st_size > 0:
        ctx_live = _safe_json_load(ctx_path_live) or {}
        if ctx_live:
            # Author and license
            if ctx_live.get("author"):
                data["author"] = ctx_live.get("author", "")
            if ctx_live.get("license"):
                data["license"] = ctx_live.get("license", "")
            # NPC descriptions, roles, factions
            live_npcs = ctx_live.get("npcs", {})
            for npc_name, live_npc in live_npcs.items():
                if npc_name in data["npcs"]:
                    bu_npc = data["npcs"][npc_name]
                    desc = bu_npc.get("description", "")
                    live_desc = live_npc.get("description", "")
                    if len(live_desc or "") > len(desc or ""):
                        data["npcs"][npc_name]["description"] = live_desc
                    # Roles and factions always from live when present
                    if live_npc.get("role"):
                        data["npcs"][npc_name]["role"] = live_npc["role"]
                    if live_npc.get("faction"):
                        data["npcs"][npc_name]["faction"] = live_npc["faction"]
                elif live_npc.get("description"):
                    data["npcs"][npc_name] = live_npc

    # Module plot - prefer BU, merge descriptions from live
    plot_path = _prefer_bu(module_dir / "module_plot.json")
    if plot_path and plot_path.exists():
        plot = _safe_json_load(plot_path)
        if plot:
            data["plot_points"] = plot.get("plotPoints", [])
    # Merge plot point descriptions from live if longer
    if ctx_live:
        live_plot_path = module_dir / "module_plot.json"
        live_plot = _safe_json_load(live_plot_path)
        if live_plot:
            live_plot_points = {pp.get("id", ""): pp for pp in live_plot.get("plotPoints", [])}
            for i, pp in enumerate(data["plot_points"]):
                pp_id = pp.get("id", "")
                live_pp = live_plot_points.get(pp_id)
                if live_pp:
                    live_desc = live_pp.get("description", "")
                    if len(live_desc or "") > len(pp.get("description", "") or ""):
                        data["plot_points"][i]["description"] = live_desc

    # Areas - deduplicate by areaId
    areas_dir = module_dir / "areas"
    if areas_dir.is_dir():
        seen_ids: set = set()
        for area_file in sorted(areas_dir.glob("*.json")):
            path = _prefer_bu(area_file)
            if path and path.exists():
                area = _safe_json_load(path)
                if area:
                    aid = area.get("areaId", "")
                    if aid and aid in seen_ids:
                        continue
                    if aid:
                        seen_ids.add(aid)
                    data["areas"].append(area)
        # Merge area descriptions from live files where BU is empty
        if ctx_live:
            for area_file in sorted(areas_dir.glob("*.json")):
                if "_BU." not in area_file.name:
                    live_area = _safe_json_load(area_file)
                    if live_area:
                        lid = live_area.get("areaId", "")
                        for i, bu_area in enumerate(data["areas"]):
                            if bu_area.get("areaId") == lid:
                                if not bu_area.get("description") and live_area.get("description"):
                                    data["areas"][i]["description"] = live_area["description"]
                                if not bu_area.get("locationName") and live_area.get("locationName"):
                                    data["areas"][i]["locationName"] = live_area["locationName"]
                                if live_area.get("dmInstructions"):
                                    if not bu_area.get("dmInstructions"):
                                        data["areas"][i]["dmInstructions"] = live_area["dmInstructions"]
                                break

        # Cross-area connectivity edges
        for area in data["areas"]:
            from_aid = area.get("areaId", "")
            for loc in area.get("locations", []):
                conn_names = loc.get("areaConnectivity", [])
                conn_ids = loc.get("areaConnectivityId", [])
                if not conn_names and not conn_ids:
                    continue
                from_lid = loc.get("locationId", "")
                max_pairs = min(len(conn_names), len(conn_ids))
                for i in range(max_pairs):
                    to_name = conn_names[i]
                    to_lid = conn_ids[i]
                    to_aid = _resolve_area_name_to_id(data["areas"], to_name)
                    if to_aid:
                        data["_cross_area_edges"].append(
                            (from_aid, from_lid, to_aid, to_lid)
                        )
                    else:
                        print(
                            "WARNING: Could not resolve cross-area name "
                            "'{}' for {}/{}".format(to_name, from_aid, from_lid)
                        )
                if len(conn_names) != len(conn_ids):
                    print(
                        "WARNING: Mismatched areaConnectivity ({} items) "
                        "and areaConnectivityId ({} items) in {}/{}".format(
                            len(conn_names), len(conn_ids), from_aid, from_lid
                        )
                    )

    # Monsters
    monsters_dir = module_dir / "monsters"
    if monsters_dir.is_dir():
        for mf in sorted(monsters_dir.glob("*.json")):
            monster = _safe_json_load(mf)
            if monster:
                data["monsters"].append(monster)

    # Maps
    for mf in sorted(module_dir.glob("map_*.json")):
        path = _prefer_bu(mf)
        if path and path.exists():
            map_data = _safe_json_load(path)
            if map_data:
                data["maps"].append(map_data)

    return data


# ---------------------------------------------------------------------------
# Main Generator
# ---------------------------------------------------------------------------


def generate_homebrewery_adventure(module_slug: str) -> str:
    """Return complete Homebrewery V3 markdown for a module."""
    data = load_module_data(module_slug)

    parts: List[str] = []
    parts.append(format_metadata(data["display_name"]))
    parts.append("\n")
    parts.append(_build_cover_page(data))
    parts.append("\n")
    parts.append(PAGE_BREAK)
    parts.append(_build_intro_section(data))
    parts.append(_build_plot_overview(data))
    parts.append(_build_locations_section(data))
    parts.append(_build_npc_gallery(data))
    parts.append(_build_monster_appendix(data))
    parts.append(_build_items_appendix(data))
    parts.append(_build_credits(data))

    result = "".join(parts)
    return sanitize_markdown_text(result)


# ---------------------------------------------------------------------------
# Section Builders
# ---------------------------------------------------------------------------


def _build_cover_page(data: Dict[str, Any]) -> str:
    """Build front cover page."""
    name = data["display_name"]
    return format_cover_page(
        title=sanitize_markdown_text(name),
        subtitle="A 5e Adventure Module",
        cover_image_url=COVER_IMAGE_URL,
    )


def _build_intro_section(data: Dict[str, Any]) -> str:
    """Build introduction page(s) with LLM-generated narrative prose.

    Attempts LLM call for flowing narrative. Falls back to deterministic
    assembly (bullet stats + concatenated abstract + author + running text).
    """
    name = data["display_name"]
    npc_count = len(data.get("npcs", {}))
    plot_count = len(data.get("plot_points", []))
    area_count = len(data.get("areas", []))
    monster_count = len(data.get("monsters", []))
    author_raw = data.get("author", "")
    display_name, _ = _parse_author_field(author_raw)

    # Build plot text for LLM
    plot_text = _build_plot_text(data)

    # Attempt LLM narrative generation
    llm_result = _llm_intro_narrative(
        name=name,
        npc_count=npc_count,
        plot_count=plot_count,
        area_count=area_count,
        monster_count=monster_count,
        author_name=display_name,
        plot_text=plot_text,
    )
    if llm_result:
        lines: List[str] = []
        lines.append("# {}\n\n".format(sanitize_markdown_text(name)))
        lines.append("## Introduction\n\n")
        lines.append(llm_result)
        return "".join(lines)

    # Fallback: deterministic assembly
    lines: List[str] = []
    lines.append("# {}\n\n".format(sanitize_markdown_text(name)))
    lines.append("## Introduction\n\n")

    main_obj = data.get("main_objective", "")
    if main_obj:
        lines.append(sanitize_markdown_text(main_obj))
        lines.append("\n\n")

    lines.append("### Module Overview\n\n")
    lines.append("This module contains:\n\n")
    lines.append("- **{}** named NPCs\n".format(npc_count))
    lines.append("- **{}** plot points\n".format(plot_count))
    lines.append("- **{}** locations\n".format(area_count))
    lines.append("- **{}** creature stat blocks\n".format(monster_count))
    lines.append("\n")

    # Plot abstract fallback
    lines.append(_fallback_plot_abstract(data))

    if display_name:
        lines.append("Original adventure by **{}**.\n\n".format(
            sanitize_markdown_text(display_name)
        ))

    lines.append("### Running the Adventure\n\n")
    lines.append(
        "This adventure is designed for a party of three to five characters "
        "of levels 3-5. The DM should read the full plot chain and NPC "
        "descriptions before running the module.\n\n"
    )

    return "".join(lines)


def _llm_intro_narrative(
    name: str,
    npc_count: int,
    plot_count: int,
    area_count: int,
    monster_count: int,
    author_name: str,
    plot_text: str,
) -> Optional[str]:
    """Call LLM to generate narrative intro prose."""
    if not plot_text.strip():
        return None
    try:
        from utils.ai_client_factory import create_chat_client, get_chat_completion_params
        from model_config import DM_SUMMARIZATION_MODEL

        client = create_chat_client()
        response = client.chat.completions.create(
            **get_chat_completion_params(
                "summaries", DM_SUMMARIZATION_MODEL, temperature_override=0.5
            ),
            messages=[{
                "role": "user",
                "content": (
                    "You are writing a D&D 5e adventure module introduction for a Dungeon Master. "
                    "Using the data below, write three markdown sections in colourful fantasy prose. "
                    "You MUST use exactly these H3 markdown headings in this exact order:\n\n"
                    "### Module Overview\n"
                    "A 1-paragraph summary describing what this adventure contains and the opening "
                    "situation. Mention the module has {} NPCs, {} plot points, {} locations, "
                    "and {} creature stat blocks in flowing prose (not as a bullet list).\n\n"
                    "### The Story So Far\n"
                    "A 2-3 paragraph narrative summary of the adventure's plot arc. Cover the overall "
                    "journey, key locations, and central conflict. Write in third-person present tense. "
                    "Do NOT list individual plot point IDs.\n\n"
                    "### Running the Adventure\n"
                    "A 1-paragraph practical note about party size, level range, and DM preparation.\n\n"
                    "DATA:\n"
                    "Author: {}\n"
                    "Level range: 3-5\n\n"
                    "PLOT TEXT:\n"
                    "{}".format(
                        npc_count, plot_count, area_count, monster_count,
                        author_name, plot_text,
                    )
                )
            }],
            max_completion_tokens=800,
        )
        result = response.choices[0].message.content.strip()
        if result:
            # Force correct H3 heading levels regardless of LLM output
            result = re.sub(r"^##\s*(Module Overview)", r"### \1", result, flags=re.MULTILINE)
            result = re.sub(r"^##\s*(The Story So Far)", r"### \1", result, flags=re.MULTILINE)
            result = re.sub(r"^##\s*(Running the Adventure)", r"### \1", result, flags=re.MULTILINE)
            return sanitize_markdown_text(result) + "\n"
    except Exception:
        pass
    return None


def _build_plot_text(data: Dict[str, Any]) -> str:
    """Build concatenated plot text for LLM summarization."""
    plot_points = data.get("plot_points", [])
    plot_text_lines: List[str] = []
    for pp in plot_points:
        pid = pp.get("id", "")
        title = pp.get("title", pid)
        desc = pp.get("description", "")
        if title and desc:
            plot_text_lines.append("{} - {}:\n{}".format(pid, title, desc))
        elif desc:
            plot_text_lines.append(desc)
    return "\n\n".join(plot_text_lines)


def _fallback_plot_abstract(data: Dict[str, Any]) -> str:
    """Deterministic fallback for plot abstract when LLM unavailable."""
    plot_points = data.get("plot_points", [])
    if not plot_points:
        return "*No plot data available for summary.*\n\n"
    first_desc = plot_points[0].get("description", "")
    last_desc = plot_points[-1].get("description", "")
    fallback_lines: List[str] = []
    if first_desc:
        fallback_lines.append(first_desc[:300])
    fallback_lines.append(
        "\n\nThe adventure culminates in a confrontation that will "
        "determine the fate of the region..."
    )
    if last_desc:
        fallback_lines.append("\n\n" + last_desc[:300])
    return sanitize_markdown_text("".join(fallback_lines)) + "\n\n"


def _llm_plot_hook(plot_text: str, plot_count: int, author_name: str) -> Optional[str]:
    """Call LLM to generate a colourful plot overview lead-in paragraph."""
    if not plot_text.strip():
        return None
    try:
        from utils.ai_client_factory import create_chat_client, get_chat_completion_params
        from model_config import DM_SUMMARIZATION_MODEL

        client = create_chat_client()
        response = client.chat.completions.create(
            **get_chat_completion_params(
                "summaries", DM_SUMMARIZATION_MODEL, temperature_override=0.7
            ),
            messages=[{
                "role": "user",
                "content": (
                    "Write a 1-paragraph colourful fantasy summary introducing the adventure "
                    "plot chain below. Write like the opening of a story or the back-cover "
                    "blurb of a novel. Capture the central mystery and tone. "
                    "Do not list plot point IDs. Use third-person present tense.\n\n"
                    "PLOT TEXT:\n{}".format(plot_text)
                )
            }],
            max_completion_tokens=250,
        )
        result = response.choices[0].message.content.strip()
        if result:
            return sanitize_markdown_text(result) + "\n\n"
    except Exception:
        pass
    return None


def _build_plot_overview(data: Dict[str, Any]) -> str:
    """Build plot chain summary."""
    plot_points = data.get("plot_points", [])
    lines: List[str] = []

    lines.append(PAGE_BREAK)
    lines.append("# Plot Overview\n\n")

    if not plot_points:
        lines.append("*No plot points found in module data.*\n")
        return "".join(lines)

    # Try LLM hook, fall back to deterministic one-liner
    plot_text = _build_plot_text(data)
    hook = _llm_plot_hook(plot_text, len(plot_points), "")
    if hook:
        lines.append(hook)
    else:
        lines.append(
            "The adventure unfolds across {} scenes, drawing the party "
            "deeper into a web of ancient mysteries and dangers...\n\n".format(
                len(plot_points)
            )
        )

    for pp in plot_points:
        pp_id = pp.get("id", "")
        title = pp.get("title", pp_id)
        desc = pp.get("description", "")
        prereqs = pp.get("prerequisites", [])

        lines.append("### {} -- {}\n\n".format(pp_id, sanitize_markdown_text(title)))

        if prereqs:
            lines.append("*Prerequisites: {}*\n\n".format(", ".join(prereqs)))

        if desc:
            lines.append(sanitize_markdown_text(desc))
            lines.append("\n\n")

    return "".join(lines)


def _build_npc_gallery(data: Dict[str, Any]) -> str:
    """Build NPC entries."""
    npcs = data.get("npcs", {})
    lines: List[str] = []

    lines.append(PAGE_BREAK)
    lines.append("# NPC Gallery\n\n")

    if not npcs:
        lines.append("*No NPC data available for this module.*\n")
        return "".join(lines)

    for npc_name, npc_data in sorted(npcs.items()):
        display = _npc_display_name(npc_name)
        desc = npc_data.get("description", "")
        role = npc_data.get("role", "")
        faction = npc_data.get("faction", "")

        lines.append("### {}\n\n".format(sanitize_markdown_text(display)))
        lines.append(
            ">![{}]({}){{width:100px,margin-right:0.5cm,wrapRight}}\n".format(
                sanitize_markdown_text(display), NPC_PORTRAIT_URL
            )
        )

        if role:
            lines.append("**Roles:** {}\n".format(sanitize_markdown_text(role)))
            lines.append(">___\n")
        if faction:
            lines.append("**Faction:** {}\n".format(sanitize_markdown_text(faction)))
            lines.append(">___\n")
        if desc:
            lines.append(sanitize_markdown_text(desc))
            lines.append("\n\n")
        else:
            lines.append("*No description available.*\n\n")

        lines.append("---\n\n")

    return "".join(lines)


def _append_edge_name(
    parts: List[str],
    target_aid: str,
    target_lid: str,
    areas: List[Dict[str, Any]],
) -> None:
    """Append a cross-area edge display name, resolving areaId to areaName."""
    for area in areas:
        if area.get("areaId") == target_aid:
            parts.append("{} ({})".format(
                area.get("areaName", target_aid), target_lid
            ))
            return
    parts.append("{} ({})".format(target_aid, target_lid))


def _llm_area_overview(area: Dict[str, Any], data: Dict[str, Any]) -> Optional[str]:
    """Generate 2-3 paragraph DM overview prose for an area.

    Builds a prompt with area metadata, per-location summaries (names,
    truncated descriptions, NPC/monster names), relevant plot points
    (matched by area ID), and cross-area edges. Calls DM_SUMMARIZATION_MODEL.
    Returns None on failure for deterministic fallback to areaDescription.
    """
    area_name = area.get("areaName", "")
    area_id = area.get("areaId", "")
    area_desc = area.get("areaDescription", "")
    area_type = area.get("areaType", "")
    locations = area.get("locations", [])
    if not locations:
        return None

    # Per-location summaries for LLM
    loc_lines: List[str] = []
    for loc in locations:
        name = loc.get("name", "")
        desc = loc.get("description", "")[:200]
        npcs = [
            n.get("name", "")
            for n in loc.get("npcs", [])
            if isinstance(n, dict) and n.get("name")
        ]
        monsters = [
            m.get("name", "")
            for m in loc.get("monsters", [])
            if isinstance(m, dict) and m.get("name")
        ]
        conn = loc.get("connectivity", [])
        area_conn = loc.get("areaConnectivity", [])

        parts: List[str] = ["### {}".format(name)]
        if desc:
            parts.append(desc)
        if npcs:
            parts.append("NPCs: " + ", ".join(npcs))
        if monsters:
            parts.append("Monsters: " + ", ".join(monsters))
        if conn:
            parts.append("Connects to: " + ", ".join(conn))
        if area_conn:
            parts.append("Cross-area: " + ", ".join(area_conn))
        loc_lines.append("\n".join(parts))

    location_text = "\n\n".join(loc_lines)
    if not location_text.strip():
        return None

    # Relevant plot points (match area ID in description)
    plot_points = data.get("plot_points", [])
    relevant_plots: List[str] = []
    for pp in plot_points:
        pp_desc = pp.get("description", "")
        if area_id and area_id in pp_desc:
            relevant_plots.append(
                "{} - {}".format(pp.get("id", ""), pp.get("title", ""))
            )
    plot_context = ""
    if relevant_plots:
        plot_context = "Relevant plot points: " + ", ".join(relevant_plots[:4])

    # Cross-area edges (incoming and outgoing)
    cross_edges = data.get("_cross_area_edges", [])
    from_edges: List[str] = []
    to_edges: List[str] = []
    for edge in cross_edges:
        if len(edge) >= 4:
            f_a, f_l, t_a, t_l = edge[0], edge[1], edge[2], edge[3]
            if f_a == area_id:
                _append_edge_name(from_edges, t_a, t_l, data.get("areas", []))
            if t_a == area_id:
                _append_edge_name(to_edges, f_a, f_l, data.get("areas", []))

    cross_text = ""
    if from_edges:
        cross_text += "Leads to: " + ", ".join(from_edges) + ". "
    if to_edges:
        cross_text += "Reachable from: " + ", ".join(to_edges) + "."
    cross_text = cross_text.strip()

    prompt = (
        "You are writing a D&D 5e adventure module location guide "
        "for a Dungeon Master. "
        "Write 2-3 paragraphs of colourful fantasy prose giving a DM "
        "an overview of this area. "
        "Cover: (1) the area's atmosphere and what makes it distinctive, "
        "(2) how its rooms connect to the adventure's plot, "
        "(3) the key NPCs and monsters that dwell here, "
        "and (4) how this area connects to other areas of the adventure. "
        "Write in third-person present tense. "
        "Do NOT list individual room names.\n\n"
        "AREA: {} ({})\n"
        "Type: {}\n"
        "Area Description: {}\n"
        "{}\n"
        "{}\n\n"
        "LOCATIONS:\n{}"
    ).format(
        area_name,
        area_id,
        area_type.title() if area_type else "Unknown",
        area_desc[:300] if area_desc else "(none)",
        plot_context,
        cross_text,
        location_text,
    )

    try:
        from utils.ai_client_factory import create_chat_client, get_chat_completion_params
        from model_config import DM_SUMMARIZATION_MODEL

        client = create_chat_client()
        response = client.chat.completions.create(
            **get_chat_completion_params(
                "summaries", DM_SUMMARIZATION_MODEL, temperature_override=0.6
            ),
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=500,
        )
        result = response.choices[0].message.content.strip()
        if result:
            return sanitize_markdown_text(result)
    except Exception:
        pass
    return None


def _build_locations_section(data: Dict[str, Any]) -> str:
    """Build location entries from area.locations[] structure.

    Each area renders with:
      - `## AreaName (AreaCode)` heading
      - LLM overview prose (or areaDescription fallback)
      - Metadata line (area type, recommended level)
      - Per-location `### LocationId -- LocationName` with all authored fields

    Falls back to flat-schema rendering when area.locations[] is absent.
    """
    areas = data.get("areas", [])
    lines: List[str] = []

    lines.append(PAGE_BREAK)
    lines.append("# Locations\n\n")

    if not areas:
        lines.append("*No location data available for this module.*\n")
        return "".join(lines)

    for area in areas:
        area_id = area.get("areaId", "")
        area_name = area.get("areaName", area_id)
        area_desc = area.get("areaDescription", "")
        area_type = area.get("areaType", "")
        rec_level = area.get("recommendedLevel", "")
        locations = area.get("locations", [])

        # -- Area header --
        lines.append("## {} -- {}\n\n".format(
            area_id, sanitize_markdown_text(area_name)
        ))

        # -- Area overview (LLM or fallback) --
        overview = _llm_area_overview(area, data)
        if overview:
            lines.append(overview)
            lines.append("\n\n")
        elif area_desc:
            lines.append(sanitize_markdown_text(area_desc))
            lines.append("\n\n")

        # -- Metadata line --
        meta_parts: List[str] = []
        if area_type:
            meta_parts.append("**Area Type:** {}".format(area_type.title() if area_type else ""))
        else:
            meta_parts.append("**Area Type:** Unknown")
        if rec_level:
            meta_parts.append("**Recommended Level:** {}".format(rec_level))
        lines.append(" | ".join(meta_parts) + "\n\n")

        # -- Flat-schema fallback --
        if not locations:
            _render_flat_location(lines, area, area_id, area_name)
            continue

        # -- Per-location rendering --
        for loc in locations:
            loc_id = loc.get("locationId", "")
            loc_name = loc.get("name", loc_id)
            desc = loc.get("description", "")
            danger = loc.get("dangerLevel", "")
            accessibility = loc.get("accessibility", "")
            adv_summary = loc.get("adventureSummary", "")
            features = loc.get("features", [])
            dc_checks = loc.get("dcChecks", [])
            plot_hooks = loc.get("plotHooks", [])
            traps = loc.get("traps", [])
            doors = loc.get("doors", [])
            loot = loc.get("lootTable", [])
            encounters = loc.get("encounters", [])
            npcs = loc.get("npcs", [])
            monsters = loc.get("monsters", [])
            connectivity = loc.get("connectivity", [])
            area_conn_names = loc.get("areaConnectivity", [])
            area_conn_ids = loc.get("areaConnectivityId", [])
            dm = loc.get("dmInstructions", "")

            lines.append("### {} -- {}\n\n".format(
                loc_id, sanitize_markdown_text(loc_name)
            ))

            # Description
            if desc:
                lines.append(sanitize_markdown_text(desc))
                lines.append("\n\n")

            # Danger Level / Accessibility / Adventure Summary
            if danger:
                lines.append("*Danger Level: {}*\n\n".format(danger))
            if accessibility:
                lines.append("*Accessibility: {}*\n\n".format(
                    sanitize_markdown_text(accessibility)
                ))
            if adv_summary:
                lines.append(">{}\n\n".format(sanitize_markdown_text(adv_summary)))

            # Features
            if features:
                lines.append("**Features:**\n\n")
                for f in features:
                    if isinstance(f, dict):
                        fname = f.get("name", "")
                        fdesc = f.get("description", "")
                        line = "- **{}**".format(sanitize_markdown_text(fname))
                        if fdesc:
                            line += ": {}".format(sanitize_markdown_text(fdesc))
                        lines.append(line + "\n")
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(f))))
                lines.append("\n")

            # DC Checks
            if dc_checks:
                lines.append("**DC Checks:**\n\n")
                for dc in dc_checks:
                    lines.append("- {}\n".format(sanitize_markdown_text(str(dc))))
                lines.append("\n")

            # Plot Hooks
            if plot_hooks:
                lines.append("**Plot Hooks:**\n\n")
                for ph in plot_hooks:
                    lines.append("- {}\n".format(sanitize_markdown_text(str(ph))))
                lines.append("\n")

            # Traps
            if traps:
                lines.append("**Traps:**\n\n")
                for t in traps:
                    if isinstance(t, dict):
                        parts: List[str] = []
                        if t.get("detectDC"):
                            parts.append("Detect DC {}".format(t["detectDC"]))
                        if t.get("disableDC"):
                            parts.append("Disable DC {}".format(t["disableDC"]))
                        if t.get("triggerDC"):
                            parts.append("Trigger DC {}".format(t["triggerDC"]))
                        if t.get("damage"):
                            parts.append("Damage: {}".format(t["damage"]))
                        lines.append("- {}\n".format(
                            sanitize_markdown_text(" | ".join(parts))
                        ))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(t))))
                lines.append("\n")

            # Doors
            if doors:
                lines.append("**Doors:**\n\n")
                for d in doors:
                    if isinstance(d, dict):
                        dname = d.get("name", "")
                        ddesc = d.get("description", "")
                        locked = d.get("locked", False)
                        lock_dc = d.get("lockDC", "")
                        is_trapped = d.get("trapped", False)
                        keyname = d.get("keyname", "")
                        door_parts: List[str] = []
                        if dname:
                            door_parts.append(sanitize_markdown_text(dname))
                        if ddesc:
                            door_parts.append(sanitize_markdown_text(ddesc))
                        if locked:
                            lock_str = "Locked (DC {})".format(lock_dc) if lock_dc else "Locked"
                            door_parts.append(lock_str)
                        if is_trapped:
                            door_parts.append("Trapped")
                        if keyname:
                            door_parts.append("Key: {}".format(
                                sanitize_markdown_text(keyname)
                            ))
                        lines.append("- {}\n".format(" -- ".join(door_parts)))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(d))))
                lines.append("\n")

            # Loot
            if loot:
                lines.append("**Loot:**\n\n")
                for lt in loot:
                    if isinstance(lt, dict):
                        item_name = lt.get("item", lt.get("name", str(lt)))
                        lines.append("- {}\n".format(sanitize_markdown_text(str(item_name))))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(lt))))
                lines.append("\n")

            # Encounters
            if encounters:
                lines.append("**Encounters:**\n\n")
                for enc in encounters:
                    if isinstance(enc, dict):
                        etype = enc.get("type", "")
                        edesc = enc.get("description", "")
                        enc_part = ""
                        if etype:
                            enc_part += "*{}*: ".format(etype)
                        if edesc:
                            enc_part += sanitize_markdown_text(edesc)
                        lines.append("- {}\n".format(enc_part))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(enc))))
                lines.append("\n")

            # NPCs
            if npcs:
                lines.append("**NPCs:**\n\n")
                for n in npcs:
                    if isinstance(n, dict):
                        nname = n.get("name", "")
                        natt = n.get("attitude", "")
                        npart = sanitize_markdown_text(nname)
                        if natt:
                            npart += " ({})".format(sanitize_markdown_text(natt))
                        lines.append("- {}\n".format(npart))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(n))))
                lines.append("\n")

            # Monsters
            if monsters:
                lines.append("**Monsters:**\n\n")
                for m in monsters:
                    if isinstance(m, dict):
                        mname = m.get("name", "")
                        mdesc = m.get("description", "")
                        mpart = sanitize_markdown_text(mname)
                        if mdesc:
                            mpart += " -- {}".format(sanitize_markdown_text(mdesc))
                        lines.append("- {}\n".format(mpart))
                    else:
                        lines.append("- {}\n".format(sanitize_markdown_text(str(m))))
                lines.append("\n")

            # Connectivity
            conn_parts: List[str] = []
            if connectivity:
                conn_list = [sanitize_markdown_text(str(c)) for c in connectivity]
                conn_parts.append("Within area: {}".format(", ".join(conn_list)))
            for i in range(min(len(area_conn_names), len(area_conn_ids))):
                conn_parts.append("{} / {}".format(
                    sanitize_markdown_text(area_conn_names[i]),
                    sanitize_markdown_text(area_conn_ids[i]),
                ))
            if conn_parts:
                lines.append("*Connected to: {}*\n\n".format("; ".join(conn_parts)))

            # DM Guidance (full, always last)
            if dm:
                lines.append("**DM Guidance:**\n\n")
                lines.append(sanitize_markdown_text(dm))
                lines.append("\n\n")

            lines.append("---\n\n")

        lines.append("\n")

    return "".join(lines)


def _render_flat_location(
    lines: List[str],
    area: Dict[str, Any],
    area_id: str,
    area_name: str,
) -> None:
    """Render a single location from flat (non-nested) area data."""
    desc = area.get("description", "")
    dm = area.get("dmInstructions", "")
    npcs = area.get("npcs", [])
    monsters = area.get("monsters", [])
    connected = area.get("connectedLocations", [])

    lines.append("### {} -- {}\n\n".format(
        area_id, sanitize_markdown_text(area_name)
    ))

    if desc:
        lines.append(sanitize_markdown_text(desc))
        lines.append("\n\n")
    else:
        lines.append("*Room descriptions not yet authored.*\n\n")

    if npcs:
        npc_names = [
            n.get("name", n) if isinstance(n, dict) else n
            for n in npcs
        ]
        lines.append("**NPCs:**\n\n")
        for nn in npc_names:
            lines.append("- {}\n".format(sanitize_markdown_text(str(nn))))
        lines.append("\n")

    if monsters:
        monster_names = [
            m.get("name", m) if isinstance(m, dict) else m
            for m in monsters
        ]
        lines.append("**Monsters:**\n\n")
        for mn in monster_names:
            lines.append("- {}\n".format(sanitize_markdown_text(str(mn))))
        lines.append("\n")

    if connected:
        lines.append("*Connected to: {}*\n\n".format(
            ", ".join(sanitize_markdown_text(str(c)) for c in connected)
        ))

    if dm:
        lines.append("**DM Guidance:**\n\n")
        lines.append(sanitize_markdown_text(dm))
        lines.append("\n\n")

    lines.append("---\n\n")


def _build_monster_appendix(data: Dict[str, Any]) -> str:
    """Build monster stat block appendix."""
    monsters = data.get("monsters", [])
    lines: List[str] = []

    lines.append(PAGE_BREAK)
    lines.append("# Monster Gallery\n\n")

    if not monsters:
        lines.append("*No monster data available for this module.*\n")
        return "".join(lines)

    for monster in monsters:
        name = monster.get("name", "Unknown Creature")
        size = monster.get("size", "Medium")
        creature_type = monster.get("type", "Monstrosity")
        alignment = monster.get("alignment", "Unaligned")
        armor_class = monster.get("armorClass", 10)
        hit_points = monster.get("hitPoints", 1)
        max_hp = monster.get("maxHitPoints", hit_points)
        speed_val = monster.get("speed", 30)
        speed = _format_speed(speed_val)

        abilities = monster.get("abilities", {})
        str_score = abilities.get("strength", 10)
        dex_score = abilities.get("dexterity", 10)
        con_score = abilities.get("constitution", 10)
        int_score = abilities.get("intelligence", 10)
        wis_score = abilities.get("wisdom", 10)
        cha_score = abilities.get("charisma", 10)

        # Format hit dice
        hd = monster.get("hitDice", "")
        if hd:
            hp_str = "{} ({})".format(max_hp, hd)
        else:
            hp_str = str(max_hp)

        # Abilities section - comma-separated bold names
        ability_lines: List[str] = []
        special_abilities = monster.get("specialAbilities", [])
        ab_names = [sa.get("name", "") for sa in special_abilities if sa.get("name")]
        if ab_names:
            ability_lines.append("> #### Abilities")
            names_list = []
            for i, an in enumerate(ab_names):
                clean = sanitize_markdown_text(an)
                if i == len(ab_names) - 1:
                    names_list.append("***{}.***".format(clean))
                else:
                    names_list.append("***{}***".format(clean))
            ability_lines.append("> {}".format(", ".join(names_list)))
        abilities_str = "\n".join(ability_lines) if ability_lines else ">"

        # Actions section - separated by >___ with : spacer at end
        action_lines: List[str] = []
        actions_list = monster.get("actions", [])
        if actions_list:
            action_lines.append(">___")
            action_lines.append("> #### Actions")
        for idx, action in enumerate(actions_list):
            if idx > 0:
                action_lines.append(">___")
            action_name = action.get("name", "")
            action_desc = action.get("description", action.get("desc", ""))
            action_attack_bonus = action.get("attackBonus")
            action_damage_dice = action.get("damageDice", "0")
            action_damage_bonus = action.get("damageBonus", 0)
            action_damage_type = action.get("damageType", "None")
            if action_name:
                action_line = "> ***{}.*** ".format(sanitize_markdown_text(action_name))
                if action_attack_bonus is not None or (action_damage_dice and action_damage_dice != "0"):
                    attack_text = _format_damage_dice(
                        dice=action_damage_dice,
                        bonus=action_damage_bonus,
                        dtype=action_damage_type,
                        attack_bonus=action_attack_bonus,
                    )
                    if attack_text:
                        action_line += attack_text
                    elif action_desc:
                        action_line += sanitize_markdown_text(action_desc)
                elif action_desc:
                    action_line += sanitize_markdown_text(action_desc)
                action_lines.append(action_line)
        if action_lines:
            action_lines.append(":")
        actions_str = "\n".join(action_lines) if action_lines else ">"

        try:
            block = format_monster_statblock(
                name=sanitize_markdown_text(name),
                size=sanitize_markdown_text(size),
                creature_type=sanitize_markdown_text(creature_type),
                alignment=sanitize_markdown_text(alignment),
                armor_class=armor_class,
                hit_points=hp_str,
                speed=sanitize_markdown_text(speed),
                strength=str_score,
                dexterity=dex_score,
                constitution=con_score,
                intelligence=int_score,
                wisdom=wis_score,
                charisma=cha_score,
                abilities=abilities_str,
                actions=actions_str,
                portrait_url=MONSTER_PORTRAIT_URL,
            )
            lines.append(block)
            lines.append("\n\n")
        except Exception:
            lines.append("> ### {}\n".format(sanitize_markdown_text(name)))
            lines.append(
                "> *{} {}, {}*\n>\n".format(
                    sanitize_markdown_text(size),
                    sanitize_markdown_text(creature_type),
                    sanitize_markdown_text(alignment),
                )
            )
            lines.append("> - **Armor Class** {}\n".format(armor_class))
            lines.append("> - **Hit Points** {}\n".format(hp_str))
            lines.append("> - **Speed** {}\n".format(sanitize_markdown_text(speed)))
            lines.append("\n*(Full stat block generation failed; basic info shown.)*\n\n\n")

    return "".join(lines)


def _build_treasure_index(data: Dict[str, Any]) -> str:
    """Aggregate all lootTable entries into a deduplicated markdown bullet list.

    Walks every area.locations[].lootTable, deduplicates by normalized name
    (lowercase, whitespace-collapsed), and formats as a quick-reference index
    with source location IDs.
    """
    areas = data.get("areas", [])
    if not areas:
        return ""

    items: Dict[str, List[str]] = {}  # normalized name -> full text for dedup

    for area in areas:
        aid = area.get("areaId", "")
        for loc in area.get("locations", []):
            lid = loc.get("locationId", "")
            for entry in loc.get("lootTable", []):
                text = str(entry).strip()
                if not text:
                    continue
                norm = " ".join(text.lower().split())
                if norm not in items:
                    items[norm] = []
                items[norm].append("{}/{}".format(aid, lid))

    if not items:
        return ""

    lines: List[str] = []
    for norm in sorted(items.keys()):
        source_text = None  # find the original text
        for area in areas:
            for loc in area.get("locations", []):
                for entry in loc.get("lootTable", []):
                    etext = str(entry).strip()
                    if " ".join(etext.lower().split()) == norm:
                        source_text = etext
                        break
                if source_text:
                    break
            if source_text:
                break

        if source_text is None:
            source_text = norm

        loc_str = ", ".join(items[norm])
        match = re.match(r'^(.+?)\s*\((.+)\)\s*$', source_text)
        if match:
            name = match.group(1).strip()
            details = match.group(2).strip()
            line = "- **{}** -- {} ({})".format(
                sanitize_markdown_text(name),
                sanitize_markdown_text(details),
                loc_str,
            )
        else:
            line = "- **{}** ({})".format(
                sanitize_markdown_text(source_text), loc_str
            )
        lines.append(line)

    return "\n".join(lines) + "\n"


def _build_items_appendix(data: Dict[str, Any]) -> str:
    """Build items/treasures appendix with aggregated loot index."""
    lines: List[str] = []
    lines.append(PAGE_BREAK)
    lines.append("# Appendix A: Treasures\n\n")

    treasure_content = _build_treasure_index(data)
    if treasure_content:
        lines.append(treasure_content)
        lines.append("\n")
    else:
        lines.append(
            "*No curated treasure data is available for this module. "
            "Treasures are listed in their locations above.*\n\n"
        )

    return "".join(lines)


def _build_credits(data: Dict[str, Any]) -> str:
    """Build credits page with attribution.

    Reads data["author"] and data["license"] from module_context.json.
    Parses author field to extract display name and source URL.
    Uses {{credits}} V3 snippet followed by {{wide}} block.
    Source and license URLs are formatted as [URL](URL) markdown links.
    """
    author_raw = data.get("author", "")
    license_val = data.get("license", "")

    display_name, source_url = _parse_author_field(author_raw)

    lines: List[str] = []
    lines.append(PAGE_BREAK)
    lines.append(CREDITS_SNIPPET)
    lines.append("\n\n")
    lines.append("{{wide\n")
    lines.append("# Credits\n")
    lines.append("**Module adapted for NeverEndingQuest**\n\n")
    lines.append(
        "**Module Builder:** [NEQ-TTRPG]"
        "(https://github.com/zeug-zz/NeverEndingQuest-TTRPG)\n\n"
    )

    if display_name:
        lines.append("**Author:** {}\n\n".format(sanitize_markdown_text(display_name)))
    if source_url:
        lines.append("**Source:** [{url}]({url})\n\n".format(url=source_url))
    if license_val:
        lines.append("**License:** [{url}]({url})\n\n".format(url=license_val))

    if not display_name and not source_url and not license_val:
        lines.append("*Attribution information not available for this module.*\n\n")

    lines.append("*Portions derived from SRD 5.2.1, CC BY 4.0.*\n")
    lines.append("}}\n")
    lines.append("\n")
    lines.append("{{pageNumber,auto}}\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_author_field(author_str: str) -> Tuple[str, str]:
    """Parse author field into (display_name, source_url).

    Handles:
        "Kuhal - Module derived from https://example.com/share/abc"
        "Name -- description https://example.com"
        "Name" (no URL)
    """
    author_str = author_str.strip()
    if not author_str:
        return "", ""

    # Extract URL
    url_match = re.search(r"https?://\S+", author_str)
    source_url = url_match.group(0) if url_match else ""

    # Split on first dash/separator to get display name
    name_parts = re.split(r"\s+[\-\u2014\u2013]+\s+", author_str, maxsplit=1)
    display_name = name_parts[0].strip()

    return display_name, source_url


def _resolve_area_name_to_id(areas: List[Dict[str, Any]], name: str) -> str:
    """Resolve a human-readable area name to its areaId.

    Matches by exact string comparison against each area's areaName field.
    Returns empty string if no match is found.
    """
    name = name.strip()
    if not name:
        return ""
    for area in areas:
        if area.get("areaName") == name:
            return area.get("areaId", "")
    return ""


def _npc_display_name(npc_key: str) -> str:
    """Convert NPC key to display name."""
    return npc_key.replace("_", " ").title()


def _format_speed(speed: Any) -> str:
    """Format speed value to string."""
    if isinstance(speed, str):
        return speed
    if isinstance(speed, (int, float)):
        return "{} ft.".format(int(speed))
    return str(speed)


def _prefer_bu(filepath: Path) -> Optional[Path]:
    """Return the _BU variant if it exists, otherwise the original.

    For area_N001.json, prefer area_N001_BU.json.
    """
    stem = filepath.stem
    # If already a _BU file, return as-is
    if stem.endswith("_BU"):
        return filepath if filepath.exists() else None
    bu_path = filepath.with_name(stem + "_BU.json")
    if bu_path.exists():
        return bu_path
    return filepath


def _safe_json_load(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file safely, returning None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
