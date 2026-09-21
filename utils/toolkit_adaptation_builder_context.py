# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Builder Context
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded prompt context for the explicit LLM adaptation builder
lane. Dossier values are advisory creative guidance. They are never source
locks, required rosters, structural instructions, or publication decisions.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM


ADAPTATION_CONTEXT_VERSION = "toolkit_adaptation_builder_context.v1"
ADAPTATION_CONTEXT_MARKER = "=== LLM ADAPTATION CONTEXT ==="
MAX_ADAPTATION_CONTEXT_CHARS = 12000
MAX_CONTEXT_VALUE_CHARS = 420
MAX_CONTEXT_ITEMS = 8
MAX_AREA_LOCATION_ITEMS = 5

_PROFILE_GUIDANCE = {
    "adventure": (
        "Use progression and scene evidence as inspiration for a coherent NEQ "
        "adventure; room evidence may inform locations but does not require "
        "literal one-to-one room preservation."
    ),
    "catalogue": (
        "Use item and listing evidence to shape a shop, market, or trade frame. "
        "Item headings are not location requirements."
    ),
    "location": (
        "Use place evidence to shape an explorable region with original hooks; "
        "one-to-one source place reproduction is optional and is not a room list."
    ),
    "lore": (
        "Use selected history and setting evidence as discoverable scenes, "
        "people, and objects rather than as a prose reproduction or forced room list."
    ),
    "encounter": (
        "Use set-piece conflict evidence to create a playable situation with "
        "multiple resolution paths and appropriate aftermath; do not force a "
        "set-piece into a literal room sequence."
    ),
    "sandbox": (
        "Use fragmented seeds to create an open-ended playable frame with "
        "original connective material rather than a mandatory source room list."
    ),
}

_SURFACE_GUIDANCE = {
    "module": (
        "Shape a distinct NEQ module identity, adapted title, premise, tone, "
        "level range, and broad destination frame."
    ),
    "areas": (
        "Use area and location candidates to guide themes and purposes. They "
        "are optional candidates, not a room list or ID contract."
    ),
    "locations": (
        "Give locations playable purposes and use NPC, encounter, item, and "
        "puzzle seeds selectively. Preserve map-owned topology."
    ),
    "plot": (
        "Turn the objective, progression, trials, and encounter stakes into a "
        "coherent plot that uses the generated location IDs."
    ),
    "npcs": (
        "Use NPC seeds as character ideas and role guidance; create original "
        "relationships and avoid party-member name collisions."
    ),
    "encounters": (
        "Use encounter seeds and adversaries as narrative prompts. Keep "
        "encounter references valid and provide non-combat resolution paths."
    ),
    "monsters": (
        "Use adversary concepts only when they are valid encounter inhabitants. "
        "Use singular names and compatible 5e mechanics."
    ),
    "items": (
        "Use item seeds as optional treasure, utility, or plot-item ideas. "
        "Write lootTable values in the existing schema format."
    ),
    "connective": (
        "Add bounded original NEQ connective material that links areas, plot, "
        "NPCs, encounters, and follow-up possibilities."
    ),
}

_STRUCTURAL_RULES = (
    "PYTHON-OWNED STRUCTURAL CONTRACT:",
    "- This block is advisory creative context, not a source lock or required roster.",
    "- Python owns schema fields, generated IDs, coordinates, topology, and connectivity.",
    "- Preserve existing location, plot, NPC, monster, encounter, and loot field names.",
    "- Keep encounter references resolvable and mechanics compatible with SRD 5.2.1.",
    "- Do not emit file paths, write instructions, runtime state mutations, or registry changes.",
    "- Use generic fantasy framing, ASCII text, and existing NEQ output conventions.",
)


def _ascii_text(value: Any, limit: int = MAX_CONTEXT_VALUE_CHARS) -> str:
    """Return bounded, printable ASCII text for a prompt block."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char if char in "\n\t" or ord(char) >= 32 else " " for char in text)
    text = text.encode("ascii", "replace").decode("ascii").strip()
    if len(text) <= limit:
        return text
    marker = " [truncated]"
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _handoff_parts(handoff: Any) -> Optional[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Return a ready adaptation dossier and safe provenance, or ``None``."""
    if not isinstance(handoff, Mapping):
        return None
    dossier = handoff.get("dossier")
    provenance = handoff.get("provenance")
    if not isinstance(dossier, Mapping) or not isinstance(provenance, Mapping):
        return None
    if dossier.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        return None
    if provenance.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        return None
    if dossier.get("status") != "ready":
        return None
    return dossier, provenance


def _append_line(lines: List[str], label: str, value: Any, limit: int = MAX_CONTEXT_VALUE_CHARS) -> None:
    text = _ascii_text(value, limit)
    if text:
        lines.append(f"{label}: {text}")


def _append_bullets(
    lines: List[str],
    heading: str,
    values: Any,
    *,
    fields: Sequence[str] = (),
    limit: int = MAX_CONTEXT_ITEMS,
) -> None:
    """Append bounded list values without exposing arbitrary dossier keys."""
    if not isinstance(values, list) or not values:
        return
    output: List[str] = []
    for value in values[:limit]:
        if isinstance(value, Mapping) and fields:
            parts: List[str] = []
            for field in fields:
                if field not in value:
                    continue
                item = value.get(field)
                if isinstance(item, list):
                    compact_items = [_ascii_text(entry, 140) for entry in item[:4]]
                    compact_items = [entry for entry in compact_items if entry]
                    if compact_items:
                        parts.append(f"{field}={', '.join(compact_items)}")
                else:
                    compact = _ascii_text(item, MAX_CONTEXT_VALUE_CHARS)
                    if compact:
                        parts.append(f"{field}={compact}")
            if parts:
                output.append("- " + "; ".join(parts))
        else:
            compact = _ascii_text(value, MAX_CONTEXT_VALUE_CHARS)
            if compact:
                output.append("- " + compact)
    if output:
        lines.append(heading + ":")
        lines.extend(output)


def _append_area_guidance(lines: List[str], dossier: Mapping[str, Any]) -> None:
    areas = dossier.get("areas")
    if not isinstance(areas, list):
        return
    output: List[str] = []
    for area in areas[:MAX_CONTEXT_ITEMS]:
        if not isinstance(area, Mapping):
            continue
        area_name = _ascii_text(area.get("name"), 180)
        purpose = _ascii_text(area.get("purpose"), MAX_CONTEXT_VALUE_CHARS)
        if not area_name:
            continue
        line = f"- {area_name}"
        if purpose:
            line += f": {purpose}"
        location_seeds = area.get("location_seeds")
        if isinstance(location_seeds, list):
            location_names = []
            for location in location_seeds[:MAX_AREA_LOCATION_ITEMS]:
                if isinstance(location, Mapping):
                    name = _ascii_text(location.get("name"), 160)
                    if name:
                        location_names.append(name)
            if location_names:
                line += f"; optional location ideas: {', '.join(location_names)}"
        output.append(line)
    if output:
        lines.append("AREA AND LOCATION IDEAS (ADVISORY):")
        lines.extend(output)


def _append_provenance(lines: List[str], dossier: Mapping[str, Any], provenance: Mapping[str, Any]) -> None:
    lines.append("PROVENANCE (REFERENCE ONLY):")
    _append_line(lines, "source title", dossier.get("source_title"), 240)
    _append_line(lines, "source hash", dossier.get("source_hash"), 64)
    _append_line(lines, "rights class", dossier.get("rights_class"), 80)
    _append_line(lines, "adaptation notice", dossier.get("adaptation_notice"), 80)
    _append_line(lines, "attempt", provenance.get("attempt_id"), 160)
    revision = provenance.get("revision_number")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0:
        _append_line(lines, "revision", revision, 20)
    model_metadata = provenance.get("model_metadata")
    if isinstance(model_metadata, Mapping):
        for key in ("provider", "model", "parameter_profile"):
            _append_line(lines, key, model_metadata.get(key), 160)


def _append_common(lines: List[str], dossier: Mapping[str, Any], provenance: Mapping[str, Any], surface: str) -> None:
    profile = _ascii_text(dossier.get("source_profile"), 40)
    lines.append(ADAPTATION_CONTEXT_MARKER)
    _append_line(lines, "context version", ADAPTATION_CONTEXT_VERSION, 80)
    _append_line(lines, "surface", surface, 40)
    _append_line(lines, "adaptation mode", dossier.get("adaptation_mode"), 40)
    _append_line(lines, "source profile", profile, 40)
    _append_line(lines, "profile guidance", _PROFILE_GUIDANCE.get(profile, "Use the selected source shape as optional creative evidence."))
    _append_line(lines, "surface guidance", _SURFACE_GUIDANCE.get(surface, _SURFACE_GUIDANCE["module"]))
    _append_line(lines, "adapted title", dossier.get("adapted_title"), 240)
    _append_line(lines, "module tone", dossier.get("module_tone"), 360)
    level_range = dossier.get("level_range")
    if isinstance(level_range, Mapping):
        minimum = level_range.get("min")
        maximum = level_range.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int):
            lines.append(f"level range: {minimum}-{maximum}")
    starting = dossier.get("starting_location")
    if isinstance(starting, Mapping):
        _append_line(lines, "starting location", starting.get("name"), 180)
        _append_line(lines, "starting location purpose", starting.get("description"), 360)
        _append_line(lines, "entry hook", starting.get("entry_hook"), 360)


def _append_plot_guidance(lines: List[str], dossier: Mapping[str, Any]) -> None:
    objective = dossier.get("plot_objective")
    if isinstance(objective, Mapping):
        _append_line(lines, "plot objective", objective.get("summary"), 420)
        _append_line(lines, "success condition", objective.get("success_condition"), 360)
        _append_line(lines, "failure condition", objective.get("failure_condition"), 360)
    _append_bullets(
        lines,
        "PLOT PROGRESSION (ADVISORY)",
        dossier.get("plot_progression"),
        fields=("order", "name", "description", "objective", "resolution"),
    )


def _append_connective_guidance(lines: List[str], dossier: Mapping[str, Any]) -> None:
    lines.append("ORIGINAL NEQ CONNECTIVE MATERIAL (ADVISORY):")
    original = dossier.get("original_adaptation_elements")
    if isinstance(original, list) and original:
        for item in original[:MAX_CONTEXT_ITEMS]:
            if not isinstance(item, Mapping):
                continue
            element = _ascii_text(item.get("element"), 360)
            kind = _ascii_text(item.get("kind"), 160)
            reason = _ascii_text(item.get("reason"), 360)
            if element:
                suffix = f" [{kind}]" if kind else ""
                if reason:
                    suffix += f": {reason}"
                lines.append(f"- {element}{suffix}")
    else:
        lines.append("- Add original hooks, relationships, and transitions that bind the adaptation into a playable NEQ module.")

    _append_bullets(
        lines,
        "RETAINED SOURCE IDEAS (ADVISORY)",
        dossier.get("retained_source_elements"),
        fields=("element", "reason", "source_ref"),
    )
    _append_bullets(
        lines,
        "OMITTED SOURCE IDEAS (INTENTIONAL)",
        dossier.get("omitted_source_elements"),
        fields=("element", "reason", "source_ref"),
    )
    _append_bullets(lines, "ASSUMPTIONS AND INFERENCES", dossier.get("assumptions"))
    _append_bullets(lines, "WARNINGS", dossier.get("warnings"))
    _append_bullets(
        lines,
        "WORLD HOOK PROPOSALS",
        dossier.get("world_narrative_hooks"),
        fields=("hook", "relationship", "proposed_follow_up"),
    )
    _append_bullets(
        lines,
        "CONTINUITY HINTS",
        dossier.get("continuity_hints"),
        fields=("hint", "scope", "related_module", "entity"),
    )


def _surface_body(lines: List[str], dossier: Mapping[str, Any], surface: str) -> None:
    if surface in {"module", "areas", "locations"}:
        _append_area_guidance(lines, dossier)
    if surface in {"module", "plot", "locations", "encounters", "connective"}:
        _append_plot_guidance(lines, dossier)
    if surface in {"locations", "npcs"}:
        _append_bullets(
            lines,
            "NPC SEEDS (ADVISORY)",
            dossier.get("npc_seeds"),
            fields=("name", "role", "purpose", "disposition", "source_basis"),
        )
    if surface in {"locations", "encounters", "monsters"}:
        _append_bullets(
            lines,
            "ENCOUNTER AND MONSTER IDEAS (ADVISORY)",
            dossier.get("encounter_seeds"),
            fields=("name", "setup", "stakes", "resolution_paths", "adversaries", "location", "source_basis"),
        )
    if surface in {"locations", "items"}:
        _append_bullets(
            lines,
            "ITEM AND TREASURE IDEAS (ADVISORY)",
            dossier.get("item_seeds"),
            fields=("name", "purpose", "description", "category", "source_basis"),
        )
    if surface in {"locations", "plot", "encounters", "connective"}:
        _append_bullets(
            lines,
            "PUZZLE AND TRIAL IDEAS (ADVISORY)",
            dossier.get("puzzle_or_trial_seeds"),
            fields=("name", "premise", "resolution_guidance", "failure_consequence"),
        )
    if surface in {"module", "plot", "connective", "locations", "npcs", "encounters", "items"}:
        _append_connective_guidance(lines, dossier)


def _fit_context(lines: Iterable[str]) -> str:
    """Keep the structural guard at the end when the context reaches its cap."""
    body = "\n".join(lines).strip()
    suffix = "\n".join(_STRUCTURAL_RULES)
    if len(body) <= MAX_ADAPTATION_CONTEXT_CHARS:
        return body
    available = max(0, MAX_ADAPTATION_CONTEXT_CHARS - len(suffix) - 32)
    return body[:available].rstrip() + "\n[context truncated]\n" + suffix


def build_adaptation_prompt_context(handoff: Any, surface: str = "module") -> str:
    """Return bounded adaptation guidance for one creative generator surface."""
    parts = _handoff_parts(handoff)
    if parts is None:
        return ""
    dossier, provenance = parts
    selected_surface = surface if surface in _SURFACE_GUIDANCE else "module"
    lines: List[str] = []
    _append_common(lines, dossier, provenance, selected_surface)
    _surface_body(lines, dossier, selected_surface)
    _append_provenance(lines, dossier, provenance)
    lines.extend(_STRUCTURAL_RULES)
    return _fit_context(lines)


def build_adaptation_context_bundle(handoff: Any) -> Dict[str, str]:
    """Build all bounded surface blocks for an explicit adaptation handoff."""
    parts = _handoff_parts(handoff)
    if parts is None:
        return {}
    return {
        surface: build_adaptation_prompt_context(handoff, surface)
        for surface in _SURFACE_GUIDANCE
    }


__all__ = [
    "ADAPTATION_CONTEXT_MARKER",
    "ADAPTATION_CONTEXT_VERSION",
    "MAX_ADAPTATION_CONTEXT_CHARS",
    "build_adaptation_context_bundle",
    "build_adaptation_prompt_context",
]
