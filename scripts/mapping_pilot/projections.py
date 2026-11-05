# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Render deterministic, allowlisted B/D packets from filtered facts.

External text is required to be ASCII. Non-ASCII input is rejected with a
clear error rather than silently changing names or packet meaning.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any


SHARED_INSTRUCTION = (
    "Use these places as the stable stage of the scene. Refer to landmarks "
    "naturally when relevant; do not recite the map, coordinates or this note."
)
_GRID = {
    "northwest": (0, 0), "north": (0, 1), "northeast": (0, 2),
    "west": (1, 0), "center": (1, 1), "east": (1, 2),
    "southwest": (2, 0), "south": (2, 1), "southeast": (2, 2),
    "upper_east": (0, 2), "upper-east": (0, 2),
}


def relationship_statements(projection: Mapping[str, Any]) -> list[str]:
    """Render filtered facts; optional location names must come from party-known data.

    Callers may pass ``known_location_names`` as an ID-to-safe-name mapping,
    and ``recent_movement.from_name`` as a safe name already authorized by the
    knowledge filter. Neither is inferred from fixture/source metadata.
    """
    _require_mapping(projection, "projection")
    names: dict[str, str] = {}
    rows: list[str] = []
    features = _rows(projection.get("feature_anchors"))
    location_names = projection.get("known_location_names")
    if not isinstance(location_names, Mapping):
        location_names = {}
    for row in features:
        name = _safe_name(row.get("name"))
        identifier = row.get("feature_id")
        if name and isinstance(identifier, str):
            names[identifier] = name

    current = projection.get("current_location")
    if isinstance(current, Mapping):
        current_name = _safe_name(current.get("name"))
        if current_name:
            rows.append("Current place: %s." % current_name)

    orientation = projection.get("orientation")
    if isinstance(orientation, Mapping):
        origin = names.get(orientation.get("origin_feature_id"))
        if origin:
            rows.append("Schematic origin: %s." % origin)
        for key, label in (("north", "North"), ("entry_facing", "Entry facing")):
            value = _safe_name(orientation.get(key))
            if value:
                rows.append("%s: %s." % (label, value.replace("_", " ")))

    for row in features:
        name = _safe_name(row.get("name"))
        if not name:
            continue
        position = _safe_name(row.get("position"))
        state = _safe_name(row.get("state"))
        if position:
            rows.append("%s is at schematic position %s." % (name, position.replace("_", " ")))
        if state:
            rows.append("%s is %s." % (name, state.replace("_", " ")))
        reachability = row.get("reachability")
        if reachability == "unreachable_from_current_location":
            rows.append("%s is visible but unreachable from here." % name)
        elif reachability == "reachable_from_current_location":
            rows.append("%s is reachable from here." % name)

    for collection in ("npc_anchors", "occupant_anchors"):
        for row in _rows(projection.get(collection)):
            name = _safe_name(row.get("name"))
            if not name:
                continue
            anchor = names.get(row.get("anchor_feature_id"))
            position = _safe_name(row.get("position"))
            if anchor:
                statement = "%s is at %s" % (name, anchor)
                if position:
                    statement += " (%s)" % position.replace("_", " ")
                rows.append(statement + ".")
            elif row.get("visibility") == "known_only":
                rows.append("%s is known to the party; current position is unknown." % name)

    for row in _rows(projection.get("exits")):
        feature = names.get(row.get("feature_id"))
        side = _safe_name(row.get("side"))
        state = _safe_name(row.get("state"))
        if not feature or not side or not state:
            continue
        destination = row.get("destination")
        target = _safe_name(location_names.get(destination)) if isinstance(destination, str) else None
        if destination == "unknown" or not isinstance(destination, str):
            ending = "destination unknown"
        elif target:
            ending = "destination %s" % target
        else:
            ending = "known destination"
        rows.append("Exit at %s is on the %s side, %s; %s." % (feature, side.replace("_", " "), state.replace("_", " "), ending))

    for row in _rows(projection.get("visible_landmarks")):
        name = _safe_name(row.get("name"))
        if name:
            rows.append("Visible but unreachable landmark: %s." % name)

    movement = projection.get("recent_movement")
    if isinstance(movement, Mapping):
        from_name = _safe_name(movement.get("from_name"))
        if from_name:
            rows.append("The party recently moved to the current place from %s." % from_name)
        else:
            rows.append("The party recently moved to the current place from a known place.")

    for row in _rows(projection.get("authored_distances")):
        left = names.get(row.get("from_feature_id"))
        right = names.get(row.get("to_feature_id"))
        value = _safe_name(row.get("value", row.get("distance")))
        unit = _safe_name(row.get("unit"))
        if left and right and value:
            rows.append("Authored distance from %s to %s: %s." % (left, right, value + ((" " + unit) if unit else "")))

    if projection.get("absence_semantics") == "omission_does_not_prove_nonexistence":
        rows.append("Omitted facts are unknown, not evidence of nonexistence.")
    return _deduplicate(rows)


def render_schematic(projection: Mapping[str, Any]) -> str:
    """Render a small ASCII schematic from supplied occupant/anchor positions only."""
    _require_mapping(projection, "projection")
    cells: dict[tuple[int, int], list[str]] = {}
    unplaced: list[str] = []
    upper_level: list[str] = []
    for row in _rows(projection.get("feature_anchors")):
        name = _safe_name(row.get("name"))
        if name and isinstance(row.get("feature_id"), str):
            position = _safe_name(row.get("position"))
            if position:
                if _is_upper_east(position):
                    upper_level.append("%s at upper level east" % name)
                    continue
                cell = _position_cell(position)
                if cell is not None:
                    cells.setdefault(cell, []).append(name)
                else:
                    unplaced.append("%s at %s" % (name, position.replace("_", " ")))
    for collection in ("occupant_anchors", "npc_anchors"):
        for row in _rows(projection.get(collection)):
            name = _safe_name(row.get("name"))
            if not name or row.get("visibility") == "known_only":
                continue
            position = _safe_name(row.get("position"))
            if not position:
                continue
            if _is_upper_east(position):
                upper_level.append("%s at upper level east" % name)
                continue
            cell = _position_cell(position)
            if cell is None:
                unplaced.append("%s at %s" % (name, position.replace("_", " ")))
            else:
                cells.setdefault(cell, []).append(name)
    lines = ["Schematic (not to scale):"]
    for row_index in range(3):
        rendered_cells = []
        for column in range(3):
            labels = sorted(set(cells.get((row_index, column), [])))
            rendered_cells.append(", ".join(labels) if labels else "-")
        lines.append(" | ".join(rendered_cells))
    if upper_level:
        lines.append("Upper level (elevation; layout unspecified):")
        lines.extend("- %s" % value for value in sorted(set(upper_level)))
    if unplaced:
        lines.append("Known anchor positions (layout unspecified):")
        lines.extend("- %s" % value for value in sorted(set(unplaced)))
    return "\n".join(lines)


def render_packet(projection: Mapping[str, Any], arm: str) -> str:
    """Render one deterministic B or D packet; arm A is intentionally disabled."""
    if arm not in ("B", "D"):
        raise ValueError("projection arm must be B or D")
    statements = relationship_statements(projection)
    sections = [render_schematic(projection)] if arm == "D" else []
    sections.extend(("Relationships:", *statements, SHARED_INSTRUCTION))
    packet = "\n\n".join(sections)
    try:
        packet.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("projection contains non-ASCII text; packet text must be ASCII") from exc
    return packet


def packet_hash(packet: str) -> str:
    """Return the SHA-256 hex digest of the exact ASCII packet bytes."""
    if not isinstance(packet, str):
        raise TypeError("packet must be a string")
    try:
        payload = packet.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("packet must contain ASCII text") from exc
    return hashlib.sha256(payload).hexdigest()


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _safe_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if not value.isascii():
        raise ValueError("projection contains non-ASCII text; packet text must be ASCII")
    return re.sub(r"\s+", " ", value.strip())


def _position_cell(position: str) -> tuple[int, int] | None:
    normalized = position.lower().replace("-", "_").replace(" ", "_")
    direct = _GRID.get(normalized)
    if direct is not None:
        return direct
    row = 1
    column = 1
    if "north" in normalized:
        row = 0
    elif "south" in normalized:
        row = 2
    if "west" in normalized:
        column = 0
    elif "east" in normalized:
        column = 2
    elif "center" in normalized:
        column = 1
    return (row, column) if any(token in normalized for token in ("north", "south", "west", "east", "center", "upper_")) else None


def _is_upper_east(position: str) -> bool:
    normalized = position.lower().replace("-", "_").replace(" ", "_")
    return normalized in ("upper_east", "upper_east_center")


def _deduplicate(rows: list[str]) -> list[str]:
    return list(dict.fromkeys(rows))


def _require_mapping(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("%s must be an object" % label)
