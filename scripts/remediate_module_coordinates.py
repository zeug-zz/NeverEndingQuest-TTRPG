#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Spatial Contract Remediation Tool
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Backfills spatial contract fields for legacy modules in dry-run or apply mode.
"""

import argparse
import json
import sys
import time as _time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.file_operations import safe_write_json
from utils.spatial_contract import (
    build_direction_map_from_rooms,
    build_location_aliases,
    build_tactical_grid,
    is_valid_coordinate,
    parse_coordinate,
    resolve_semantic_spatial_plan,
)


def _is_excluded_json_file(path: Path) -> bool:
    name = path.name
    return any(
        token in name
        for token in ("_BU.json", ".bak", ".backup", ".tmp", "_backup.json")
    )


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_room_index(map_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    room_index: Dict[str, Dict[str, Any]] = {}
    for room in map_data.get("rooms", []):
        room_id = room.get("id")
        if isinstance(room_id, str) and room_id:
            room_index[room_id] = room
    return room_index


def _build_plan_from_locations(locations: List[Dict[str, Any]]) -> Dict[str, Any]:
    room_records: List[Dict[str, Any]] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        location_id = location.get("locationId")
        if not isinstance(location_id, str) or not location_id:
            continue
        room_records.append(
            {
                "id": location_id,
                "name": location.get("name", location_id),
                "type": location.get("type", "room"),
                "description": location.get("description", ""),
                "connections": location.get("connectivity", []),
            }
        )

    return resolve_semantic_spatial_plan(
        room_records,
        start_x=10,
        start_y=10,
        use_llm=False,
    )


# ---------------------------------------------------------------------------
# Tier 1: Constraint-based grid embedding solver
# ---------------------------------------------------------------------------

_CARDINAL_DELTAS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
_MAX_ROOMS_TIER1 = 20
_MAX_EMBED_MS = 100
_CONNECTOR_ARCHETYPES = [
    {
        "name": "Mirror Portal",
        "type": "connector",
        "description": "A remediation-generated mirror portal bridges a spatial gap.",
    },
    {
        "name": "Trapdoor Crawlspace",
        "type": "connector",
        "description": "A remediation-generated crawlspace drops movement through the gap.",
    },
    {
        "name": "Hidden Passage",
        "type": "connector",
        "description": "A remediation-generated hidden passage bridges the gap.",
    },
    {
        "name": "Dimensional Threshold",
        "type": "connector",
        "description": "A remediation-generated threshold bridges the gap without overlapping coordinates.",
    },
    {
        "name": "Service Tunnel",
        "type": "connector",
        "description": "A remediation-generated service tunnel bridges the gap.",
    },
]


def _bfs_order(graph: Dict[str, List[str]], root: str) -> List[str]:
    """Return BFS ordering from *root*, covering all connected components."""
    nodes = list(graph.keys())
    if root not in graph:
        root = nodes[0] if nodes else ""
    order: List[str] = []
    seen: set = set()
    # Process root's component first, then process remaining components
    remaining = list(nodes)
    while remaining:
        start = root if root in remaining else remaining[0]
        if start in seen:
            remaining = [n for n in remaining if n not in seen]
            continue
        order.append(start)
        seen.add(start)
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in graph.get(node, []):
                if neighbor in seen or neighbor not in graph:
                    continue
                seen.add(neighbor)
                order.append(neighbor)
                queue.append(neighbor)
        remaining = [n for n in remaining if n not in seen]
    return order


def _cardinal_intersection(
    placed_neighbors: List[str],
    coords: Dict[str, Tuple[int, int]],
) -> set:
    """Return cells that are cardinally adjacent to ALL *placed_neighbors*."""
    if not placed_neighbors:
        return set()
    px, py = coords[placed_neighbors[0]]
    candidates = {(px + dx, py + dy) for dx, dy in _CARDINAL_DELTAS}
    for nb in placed_neighbors[1:]:
        nx, ny = coords[nb]
        nb_cells = {(nx + dx, ny + dy) for dx, dy in _CARDINAL_DELTAS}
        candidates &= nb_cells
        if not candidates:
            break
    return candidates


def _is_fully_adjacent(
    coords_xy: Dict[str, Tuple[int, int]],
    graph: Dict[str, List[str]],
) -> bool:
    """True when every edge in *graph* has Manhattan distance exactly 1."""
    seen: set = set()
    for a, neighbors in graph.items():
        if a not in coords_xy:
            return False
        ax, ay = coords_xy[a]
        for b in neighbors:
            pair = tuple(sorted([a, b]))
            if pair in seen or b not in coords_xy:
                continue
            seen.add(pair)
            bx, by = coords_xy[b]
            if abs(ax - bx) + abs(ay - by) != 1:
                return False
    return True


def _normalize_edge_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((a, b)))


def _collect_unresolved_edges(
    coords_xy: Dict[str, Tuple[int, int]],
    graph: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    unresolved: List[Dict[str, Any]] = []
    seen: set = set()
    for a, neighbors in graph.items():
        for b in neighbors:
            pair = _normalize_edge_key(a, b)
            if pair in seen:
                continue
            seen.add(pair)
            source_coordinate = coords_xy.get(a)
            target_coordinate = coords_xy.get(b)
            if source_coordinate is None or target_coordinate is None:
                unresolved.append(
                    {
                        "source": a,
                        "target": b,
                        "reason": "missing_coordinate",
                        "source_coordinate": None
                        if source_coordinate is None
                        else f"X{source_coordinate[0]}Y{source_coordinate[1]}",
                        "target_coordinate": None
                        if target_coordinate is None
                        else f"X{target_coordinate[0]}Y{target_coordinate[1]}",
                        "manhattan_distance": None,
                    }
                )
                continue
            manhattan_distance = abs(source_coordinate[0] - target_coordinate[0]) + abs(
                source_coordinate[1] - target_coordinate[1]
            )
            if manhattan_distance != 1:
                unresolved.append(
                    {
                        "source": a,
                        "target": b,
                        "reason": "non_cardinal_edge",
                        "source_coordinate": f"X{source_coordinate[0]}Y{source_coordinate[1]}",
                        "target_coordinate": f"X{target_coordinate[0]}Y{target_coordinate[1]}",
                        "manhattan_distance": manhattan_distance,
                    }
                )
    return unresolved


def _collect_coordinate_overlaps(
    coords_xy: Dict[str, Tuple[int, int]],
) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[int, int], List[str]] = {}
    for room_id, coordinate in coords_xy.items():
        buckets.setdefault(coordinate, []).append(room_id)

    overlaps: List[Dict[str, Any]] = []
    for (x, y), room_ids in sorted(buckets.items()):
        if len(room_ids) > 1:
            overlaps.append(
                {
                    "coordinate": f"X{x}Y{y}",
                    "room_ids": sorted(room_ids),
                }
            )
    return overlaps


def _build_relaxation_seed(graph: Dict[str, List[str]]) -> Dict[str, Tuple[int, int]]:
    nodes = list(graph.keys())
    if not nodes:
        return {}
    root = max(nodes, key=lambda n: len(graph.get(n, [])))
    order = _bfs_order(graph, root)
    occupied: set = set()
    seed: Dict[str, Tuple[int, int]] = {}
    for lid in order:
        start = (10, 10)
        while start in occupied:
            start = (start[0] + 1, start[1] + 1)
        seed[lid] = start
        occupied.add(start)
    return seed


def _build_tiered_spatial_report(graph: Dict[str, List[str]]) -> Dict[str, Any]:
    """Return the best deterministic coordinate plan plus diagnostics."""
    nodes = list(graph.keys())
    if not nodes:
        return {
            "status": "success",
            "tier": "tier1_constraint_solver",
            "coordinates": {},
            "unresolved_edges": [],
            "diagnostics": [],
        }

    diagnostics: List[Dict[str, Any]] = []
    tier1_coords = _solve_grid_embedding(graph)
    if tier1_coords is not None and _is_fully_adjacent(tier1_coords, graph):
        return {
            "status": "success",
            "tier": "tier1_constraint_solver",
            "coordinates": {
                rid: f"X{x}Y{y}" for rid, (x, y) in tier1_coords.items()
            },
            "unresolved_edges": [],
            "diagnostics": [],
        }

    if len(graph) > _MAX_ROOMS_TIER1:
        diagnostics.append(
            {
                "tier": "tier1_constraint_solver",
                "code": "tier1_search_limit",
                "limit": _MAX_ROOMS_TIER1,
            }
        )
    else:
        diagnostics.append(
            {
                "tier": "tier1_constraint_solver",
                "code": "non_embed_candidate_exhausted",
            }
        )

    seed_xy = _build_relaxation_seed(graph)
    seed_coordinates = {
        rid: f"X{x}Y{y}" for rid, (x, y) in seed_xy.items()
    }

    tier2_coords = _relax_with_expansion(dict(seed_coordinates), graph)
    tier2_xy = {
        rid: parse_coordinate(cs) for rid, cs in tier2_coords.items() if not rid.startswith("_buf_")
    }
    if tier2_xy and _is_fully_adjacent(tier2_xy, graph):
        return {
            "status": "success",
            "tier": "tier2_relaxation",
            "coordinates": {
                rid: f"X{x}Y{y}" for rid, (x, y) in tier2_xy.items()
            },
            "unresolved_edges": [],
            "diagnostics": diagnostics,
        }

    if tier2_xy:
        diagnostics.append(
            {
                "tier": "tier2_relaxation",
                "code": "fallback_unvalidated",
                "reason": "non_cardinal_edge",
                "unresolved_edges": _collect_unresolved_edges(tier2_xy, graph),
            }
        )

    tier3_coords = _build_linear_layout(graph)
    tier3_xy = {
        rid: parse_coordinate(cs) for rid, cs in tier3_coords.items()
    }
    if tier3_xy and _is_fully_adjacent(tier3_xy, graph):
        return {
            "status": "success",
            "tier": "tier3_linear_layout",
            "coordinates": {
                rid: f"X{x}Y{y}" for rid, (x, y) in tier3_xy.items()
            },
            "unresolved_edges": [],
            "diagnostics": diagnostics,
        }

    if tier3_xy:
        diagnostics.append(
            {
                "tier": "tier3_linear_layout",
                "code": "fallback_unvalidated",
                "reason": "non_cardinal_edge",
                "unresolved_edges": _collect_unresolved_edges(tier3_xy, graph),
            }
        )

    best_xy = tier3_xy or tier2_xy or tier1_coords or seed_xy
    best_coordinates = {
        rid: f"X{x}Y{y}" for rid, (x, y) in best_xy.items()
    }
    unresolved_edges = _collect_unresolved_edges(best_xy, graph)
    overlaps = _collect_coordinate_overlaps(best_xy)
    if overlaps:
        diagnostics.append(
            {
                "tier": "best_effort",
                "code": "coordinate_overlap",
                "overlaps": overlaps,
            }
        )
    if unresolved_edges:
        diagnostics.append(
            {
                "tier": "best_effort",
                "code": "non_cardinal_edge",
                "unresolved_edges": unresolved_edges,
            }
        )

    return {
        "status": "failed",
        "tier": "tier3_linear_layout" if tier3_coords else "tier2_relaxation",
        "coordinates": best_coordinates,
        "unresolved_edges": unresolved_edges,
        "diagnostics": diagnostics,
    }


def _build_tiered_coordinates(graph: Dict[str, List[str]]) -> Dict[str, str]:
    return _build_tiered_spatial_report(graph)["coordinates"]


def _find_detour_path(
    start: Tuple[int, int],
    end: Tuple[int, int],
    blocked: set,
) -> Optional[List[Tuple[int, int]]]:
    """Find a deterministic 4-neighbor path around blocked cells."""
    if start == end:
        return [start]

    relevant_points = list(blocked) + [start, end]
    min_x = min(point[0] for point in relevant_points)
    max_x = max(point[0] for point in relevant_points)
    min_y = min(point[1] for point in relevant_points)
    max_y = max(point[1] for point in relevant_points)
    max_margin = max(6, len(blocked) + 6)

    for margin in range(2, max_margin + 1):
        lower_x = min_x - margin
        upper_x = max_x + margin
        lower_y = min_y - margin
        upper_y = max_y + margin
        queue: deque[Tuple[int, int]] = deque([start])
        parents: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}

        while queue:
            current = queue.popleft()
            if current == end:
                path: List[Tuple[int, int]] = []
                node: Optional[Tuple[int, int]] = current
                while node is not None:
                    path.append(node)
                    node = parents[node]
                return list(reversed(path))

            cx, cy = current
            candidates = [
                (cx + 1, cy),
                (cx, cy + 1),
                (cx - 1, cy),
                (cx, cy - 1),
            ]
            candidates = [
                cell
                for cell in candidates
                if lower_x <= cell[0] <= upper_x and lower_y <= cell[1] <= upper_y
            ]
            candidates.sort(
                key=lambda cell: (
                    abs(cell[0] - end[0]) + abs(cell[1] - end[1]),
                    cell[0],
                    cell[1],
                )
            )

            for cell in candidates:
                if cell != end and cell in blocked:
                    continue
                if cell in parents:
                    continue
                parents[cell] = current
                queue.append(cell)

    return None


def _stable_connector_seed(edge: Dict[str, Any], segment_index: int) -> int:
    seed_text = (
        f"{edge.get('source','')}|{edge.get('target','')}|"
        f"{edge.get('source_coordinate','')}|{edge.get('target_coordinate','')}|{segment_index}"
    )
    return sum(ord(ch) for ch in seed_text)


def _select_connector_archetype(edge: Dict[str, Any], segment_index: int) -> Dict[str, str]:
    seed = _stable_connector_seed(edge, segment_index)
    return _CONNECTOR_ARCHETYPES[seed % len(_CONNECTOR_ARCHETYPES)]


def _next_connector_id(existing_ids: set, seed: int) -> str:
    start = (seed % 90) + 1
    for offset in range(90):
        candidate_number = ((start + offset - 1) % 90) + 1
        candidate = f"CN{candidate_number:02d}"
        if candidate not in existing_ids:
            return candidate
    raise ValueError("Unable to allocate connector location id")


def _build_generated_connector_location(
    connector_id: str,
    coordinate: Tuple[int, int],
    source_edge: Dict[str, Any],
    archetype: Dict[str, str],
    segment_index: int,
    total_segments: int,
) -> Dict[str, Any]:
    display_name = archetype["name"]
    if total_segments > 1:
        display_name = f"{display_name} {segment_index + 1}"

    source_pair = [source_edge.get("source", ""), source_edge.get("target", "")]
    return {
        "locationId": connector_id,
        "name": display_name,
        "type": archetype["type"],
        "description": archetype["description"],
        "dmInstructions": (
            f"Route movement through this generated connector between {source_pair[0]} and {source_pair[1]}."
        ),
        "coordinates": f"X{coordinate[0]}Y{coordinate[1]}",
        "aliases": build_location_aliases(display_name, connector_id),
        "tactical_grid": build_tactical_grid(display_name, archetype["type"]),
        "accessibility": "Remediation-generated connector path.",
        "npcs": [],
        "monsters": [],
        "plotHooks": [],
        "lootTable": [],
        "dangerLevel": "Low",
        "connectivity": [],
        "areaConnectivity": [],
        "areaConnectivityId": [],
        "traps": [],
        "features": [
            {
                "name": archetype["name"],
                "description": archetype["description"],
            }
        ],
        "dcChecks": [],
        "encounters": [],
        "adventureSummary": "",
        "doors": [],
        "spatial_remediation": {
            "generated": True,
            "reason": "non_embed_edge",
            "source_edge": source_pair,
            "method": "deterministic_connector_insertion",
            "segment_index": segment_index,
            "total_segments": total_segments,
            "archetype": archetype["name"],
        },
    }


def _normalize_connectivity(connectivity: List[str]) -> List[str]:
    normalized: List[str] = []
    for target in connectivity:
        if isinstance(target, str) and target and target not in normalized:
            normalized.append(target)
    return normalized


def _apply_connector_failsafe(
    locations: List[Dict[str, Any]],
    graph: Dict[str, List[str]],
    coordinates: Dict[str, str],
) -> Tuple[int, List[Dict[str, Any]]]:
    """Insert connector nodes for unresolved edges using deterministic routing."""
    coords_xy: Dict[str, Tuple[int, int]] = {
        rid: parse_coordinate(cs)
        for rid, cs in coordinates.items()
        if is_valid_coordinate(cs)
    }
    unresolved_edges = _collect_unresolved_edges(coords_xy, graph)
    if not unresolved_edges:
        return 0, []

    adjacency: Dict[str, List[str]] = {
        location.get("locationId"): _normalize_connectivity(
            list(location.get("connectivity", []))
            if isinstance(location.get("connectivity"), list)
            else []
        )
        for location in locations
        if isinstance(location, dict) and isinstance(location.get("locationId"), str)
    }
    existing_ids = set(adjacency.keys())
    existing_coords = set(coords_xy.values())
    generated_locations: List[Dict[str, Any]] = []

    for edge_index, edge in enumerate(
        sorted(
            unresolved_edges,
            key=lambda item: (
                item.get("source", ""),
                item.get("target", ""),
                item.get("manhattan_distance") is None,
                item.get("manhattan_distance") or 0,
            ),
        )
    ):
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            continue

        source_coordinate = coords_xy.get(source)
        target_coordinate = coords_xy.get(target)
        if source_coordinate is None or target_coordinate is None:
            continue

        path = _find_detour_path(source_coordinate, target_coordinate, existing_coords)
        if not path or len(path) < 2:
            raise ValueError(f"Unable to route connector path for {source}->{target}")

        intermediates = path[1:-1]
        if not intermediates:
            continue

        connector_ids: List[str] = []
        connector_locations_for_chain: List[Dict[str, Any]] = []
        for segment_index, coordinate in enumerate(intermediates):
            connector_seed = _stable_connector_seed(edge, segment_index)
            connector_id = _next_connector_id(existing_ids, connector_seed)
            existing_ids.add(connector_id)
            existing_coords.add(coordinate)
            connector_ids.append(connector_id)
            archetype = _select_connector_archetype(edge, segment_index)
            connector_location = _build_generated_connector_location(
                connector_id=connector_id,
                coordinate=coordinate,
                source_edge=edge,
                archetype=archetype,
                segment_index=segment_index,
                total_segments=len(intermediates),
            )
            generated_locations.append(connector_location)
            connector_locations_for_chain.append(connector_location)
            coords_xy[connector_id] = coordinate

        chain = [source] + connector_ids + [target]
        for left, right in zip(chain, chain[1:]):
            adjacency.setdefault(left, [])
            adjacency.setdefault(right, [])
            if right not in adjacency[left]:
                adjacency[left].append(right)
            if left not in adjacency[right]:
                adjacency[right].append(left)

        if target in adjacency.get(source, []):
            adjacency[source] = [item for item in adjacency[source] if item != target]
        if source in adjacency.get(target, []):
            adjacency[target] = [item for item in adjacency[target] if item != source]

        for index, connector_location in enumerate(connector_locations_for_chain):
            connector_location["connectivity"] = [chain[index], chain[index + 2]]

    if not generated_locations:
        return 0, []

    for location in locations:
        if not isinstance(location, dict):
            continue
        location_id = location.get("locationId")
        if not isinstance(location_id, str) or not location_id:
            continue
        if location_id in adjacency:
            location["connectivity"] = _normalize_connectivity(adjacency[location_id])

    locations.extend(generated_locations)
    return len(generated_locations), generated_locations


def _solve_grid_embedding(
    graph: Dict[str, List[str]],
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Constraint-based backtracking solver for planar grid embeddings.

    Tries roots in descending degree order.  Uses intersection of placed
    neighbours' cardinal neighborhoods to compute valid candidate cells.
    """
    nodes = list(graph.keys())
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]: (10, 10)}

    roots = sorted(nodes, key=lambda n: len(graph.get(n, [])), reverse=True)
    _start = _time.perf_counter()

    for root in roots:
        order = _bfs_order(graph, root)
        if len(order) != len(nodes):
            continue

        coords: Dict[str, Tuple[int, int]] = {}
        occupied: set = set()
        _depth = 0

        def _place(idx: int) -> bool:
            nonlocal _depth
            if _time.perf_counter() - _start >= _MAX_EMBED_MS / 1000.0:
                return False  # wall-clock exceeded
            _depth += 1
            if _depth > 2000:
                _depth -= 1
                return False  # recursion depth exceeded
            try:
                if idx == len(order):
                    return True
                node = order[idx]
                placed_neighbors = [n for n in graph.get(node, []) if n in coords]

                candidates: set
                if not placed_neighbors:
                    if idx == 0:
                        candidates = {(0, 0)}
                    else:
                        candidates = set()
                        for prev in list(coords.values()):
                            px, py = prev
                            candidates.update(
                                (px + dx, py + dy) for dx, dy in _CARDINAL_DELTAS
                            )
                        candidates -= occupied
                else:
                    candidates = _cardinal_intersection(placed_neighbors, coords)
                    candidates -= occupied

                for cx, cy in sorted(candidates):
                    coords[node] = (cx, cy)
                    occupied.add((cx, cy))
                    if _place(idx + 1):
                        return True
                    del coords[node]
                    occupied.discard((cx, cy))
                return False
            finally:
                _depth -= 1

        if _place(0):
            min_x = min(c[0] for c in coords.values())
            min_y = min(c[1] for c in coords.values())
            return {
                rid: (x - min_x + 10, y - min_y + 10)
                for rid, (x, y) in coords.items()
            }

    return None


# ---------------------------------------------------------------------------
# Tier 2: Cell-expansion swap relaxation
# ---------------------------------------------------------------------------


def _count_adjacent_connected_pairs(
    coordinates: Dict[str, str],
    graph: Dict[str, List[str]],
) -> int:
    """Count connected room pairs that are cardinally adjacent."""
    count = 0
    seen: set = set()
    for loc_id, neighbors in graph.items():
        if loc_id not in coordinates:
            continue
        cx, cy = parse_coordinate(coordinates[loc_id])
        for neighbor_id in neighbors:
            if neighbor_id not in coordinates:
                continue
            pair = tuple(sorted([loc_id, neighbor_id]))
            if pair in seen:
                continue
            seen.add(pair)
            nx, ny = parse_coordinate(coordinates[neighbor_id])
            if abs(cx - nx) + abs(cy - ny) == 1:
                count += 1
    return count


def _swap_optimize(
    coordinates: Dict[str, str],
    graph: Dict[str, List[str]],
    max_iterations: int = 50,
) -> None:
    """Iteratively swap rooms to maximize cardinal adjacency of connected pairs."""
    coord_keys = list(coordinates.keys())
    max_possible = sum(len(v) for v in graph.values()) // 2

    for _ in range(max_iterations):
        current_score = _count_adjacent_connected_pairs(coordinates, graph)
        if current_score >= max_possible:
            return

        best_swap: Optional[Tuple[str, str]] = None
        best_score = current_score

        for i in range(len(coord_keys)):
            for j in range(i + 1, len(coord_keys)):
                id_a, id_b = coord_keys[i], coord_keys[j]
                ca, cb = coordinates[id_a], coordinates[id_b]
                coordinates[id_a], coordinates[id_b] = cb, ca
                score = _count_adjacent_connected_pairs(coordinates, graph)
                coordinates[id_a], coordinates[id_b] = ca, cb
                if score > best_score:
                    best_score = score
                    best_swap = (id_a, id_b)

        if best_swap is None:
            return

        id_a, id_b = best_swap
        coordinates[id_a], coordinates[id_b] = coordinates[id_b], coordinates[id_a]


def _relax_with_expansion(
    coordinates: Dict[str, str],
    graph: Dict[str, List[str]],
) -> Dict[str, str]:
    """Expand the grid with intersection cells for non-adjacent pairs, then swap."""
    coord_xy: Dict[str, Tuple[int, int]] = {
        rid: parse_coordinate(cs) for rid, cs in coordinates.items()
    }
    seen: set = set()

    for a, neighbors in graph.items():
        if a not in coord_xy:
            continue
        ax, ay = coord_xy[a]
        for b in neighbors:
            pair = tuple(sorted([a, b]))
            if pair in seen or b not in coord_xy:
                continue
            seen.add(pair)
            bx, by = coord_xy[b]
            if abs(ax - bx) + abs(ay - by) == 1:
                continue
            intersection = _cardinal_intersection([a, b], coord_xy)
            for cx, cy in intersection:
                cell_str = f"X{cx}Y{cy}"
                if cell_str not in coordinates.values():
                    coordinates[f"_buf_{a}_{b}"] = cell_str
                    break

    _swap_optimize(coordinates, graph)
    return coordinates


# ---------------------------------------------------------------------------
# Tier 3: Linear layout (diagnostic-only fallback)
# ---------------------------------------------------------------------------


def _build_linear_layout(graph: Dict[str, List[str]]) -> Dict[str, str]:
    """Diagnostic linear layout that only succeeds when strict validation passes."""
    nodes = list(graph.keys())
    if not nodes:
        return {}
    root = max(nodes, key=lambda n: len(graph.get(n, [])))
    order = _bfs_order(graph, root)
    return {rid: f"X{10 + i}Y10" for i, rid in enumerate(order)}


# ---------------------------------------------------------------------------
# Force-relayout entry point (3-tier chain)
# ---------------------------------------------------------------------------


def _build_force_relayout_report(locations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the tiered solver report for existing locations."""
    graph: Dict[str, List[str]] = {}
    for location in locations:
        if not isinstance(location, dict):
            continue
        lid = location.get("locationId")
        if not isinstance(lid, str) or not lid:
            continue
        graph[lid] = [
            t for t in location.get("connectivity", [])
            if isinstance(t, str) and t
        ]

    if not graph:
        return {
            "status": "success",
            "tier": "tier1_constraint_solver",
            "coordinates": {},
            "unresolved_edges": [],
            "diagnostics": [],
        }

    return _build_tiered_spatial_report(graph)


def _build_force_relayout_coordinates(locations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return the best deterministic coordinate plan for existing locations."""
    return _build_force_relayout_report(locations)["coordinates"]


def remediate_area_map_pair(
    area_data: Dict[str, Any],
    map_data: Dict[str, Any],
    force_relayout: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
    """Backfill spatial contract fields while preserving authored connectivity."""
    locations = area_data.get("locations", [])
    room_index = _build_room_index(map_data)
    fallback_plan = _build_plan_from_locations(locations)
    force_plan = _build_force_relayout_report(locations) if force_relayout else {}
    forced_coordinates = force_plan.get("coordinates", {}) if force_relayout else {}
    changes = 0

    for index, location in enumerate(locations):
        if not isinstance(location, dict):
            continue
        location_id = location.get("locationId")
        if not isinstance(location_id, str) or not location_id:
            continue

        map_room = room_index.get(location_id, {})
        map_coordinate = map_room.get("coordinates")
        fallback_coordinate = forced_coordinates.get(location_id) or fallback_plan["coordinates"].get(
            location_id, f"X{10 + index}Y10"
        )
        coordinate = location.get("coordinates")
        if force_relayout and coordinate != fallback_coordinate:
            location["coordinates"] = fallback_coordinate
            changes += 1
        elif is_valid_coordinate(map_coordinate) and coordinate != map_coordinate:
            location["coordinates"] = map_coordinate
            changes += 1
        elif not is_valid_coordinate(coordinate):
            location["coordinates"] = (
                map_coordinate
                if is_valid_coordinate(map_coordinate)
                else fallback_coordinate
            )
            changes += 1

        if (
            "aliases" not in location
            or not isinstance(location.get("aliases"), list)
            or not location.get("aliases")
        ):
            location["aliases"] = build_location_aliases(
                location.get("name", ""), location_id
            )
            changes += 1

        if (
            "tactical_grid" not in location
            or not isinstance(location.get("tactical_grid"), list)
            or len(location.get("tactical_grid", [])) != 9
        ):
            location["tactical_grid"] = build_tactical_grid(
                location.get("name", ""), location.get("type", "room")
            )
            changes += 1

        if "connectivity" not in location or not isinstance(
            location.get("connectivity"), list
        ):
            location["connectivity"] = map_room.get(
                "connections", fallback_plan["connectivity"].get(location_id, [])
            )
            changes += 1

    if force_relayout:
        topology_graph: Dict[str, List[str]] = {}
        topology_coordinates: Dict[str, Tuple[int, int]] = {}
        for location in locations:
            if not isinstance(location, dict):
                continue
            location_id = location.get("locationId")
            if not isinstance(location_id, str) or not location_id:
                continue
            topology_graph[location_id] = _normalize_connectivity(
                list(location.get("connectivity", []))
                if isinstance(location.get("connectivity"), list)
                else []
            )
            coordinate = location.get("coordinates")
            if is_valid_coordinate(coordinate):
                topology_coordinates[location_id] = parse_coordinate(coordinate)

        unresolved_edges = _collect_unresolved_edges(topology_coordinates, topology_graph)
        if unresolved_edges:
            connector_count, generated_locations = _apply_connector_failsafe(
                locations,
                topology_graph,
                forced_coordinates or fallback_plan.get("coordinates", {}),
            )
            if connector_count > 0:
                changes += connector_count
                room_index = _build_room_index(map_data)
                for connector_location in generated_locations:
                    location_id = connector_location.get("locationId")
                    if not isinstance(location_id, str) or not location_id:
                        continue
                    room_index[location_id] = {
                        "id": location_id,
                        "name": connector_location.get("name", location_id),
                        "type": connector_location.get("type", "connector"),
                        "description": connector_location.get("description", ""),
                        "connections": _normalize_connectivity(
                            list(connector_location.get("connectivity", []))
                            if isinstance(connector_location.get("connectivity"), list)
                            else []
                        ),
                        "coordinates": connector_location.get("coordinates", "X10Y10"),
                    }

    area_data["spatialContractVersion"] = 1

    map_rooms: List[Dict[str, Any]] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        location_id = location.get("locationId")
        if not isinstance(location_id, str) or not location_id:
            continue

        current_room = room_index.get(location_id, {})
        location_connectivity = location.get("connectivity")
        room_connections = current_room.get("connections")

        if isinstance(location_connectivity, list):
            # Use authored location connectivity as the canonical runtime source.
            room_connections = [
                target
                for target in location_connectivity
                if isinstance(target, str) and target
            ]
        elif isinstance(room_connections, list):
            room_connections = [
                target
                for target in room_connections
                if isinstance(target, str) and target
            ]
        else:
            room_connections = fallback_plan["connectivity"].get(location_id, [])

        room_record = dict(current_room) if isinstance(current_room, dict) else {}
        room_record["id"] = location_id
        room_record["name"] = (
            current_room.get("name") or location.get("name") or location_id
        )
        room_record["connections"] = room_connections
        room_record["coordinates"] = location.get(
            "coordinates", fallback_plan["coordinates"].get(location_id, "X10Y10")
        )
        map_rooms.append(room_record)

    direction_map = build_direction_map_from_rooms(map_rooms)
    for room in map_rooms:
        room["directions"] = direction_map.get(room["id"], {})

    if map_data.get("rooms") != map_rooms:
        map_data["rooms"] = map_rooms
        changes += 1

    expected_layout = fallback_plan.get("layout", [])
    existing_layout = map_data.get("layout")
    if not isinstance(existing_layout, list) or not existing_layout:
        map_data["layout"] = expected_layout
        changes += 1

    map_data["totalRooms"] = len(map_rooms)
    map_data["startRoom"] = map_rooms[0]["id"] if map_rooms else ""
    map_data["spatialContractVersion"] = 1

    return area_data, map_data, changes


def remediate_module(module_path: Path, apply: bool, force_relayout: bool = False) -> Dict[str, Any]:
    """Remediate one module path and return summary metrics."""
    areas_dir = module_path / "areas"
    if not areas_dir.exists():
        return {"module": module_path.name, "processed": 0, "changed": 0, "errors": []}

    processed = 0
    changed = 0
    errors: List[str] = []

    for area_path in sorted(areas_dir.glob("*.json")):
        if _is_excluded_json_file(area_path):
            continue
        try:
            area_data = _load_json(area_path)
            area_id = area_data.get("areaId")
            if not isinstance(area_id, str) or not area_id:
                continue

            map_path = module_path / f"map_{area_id}.json"
            has_external_map = map_path.exists() and not _is_excluded_json_file(
                map_path
            )

            if has_external_map:
                map_data = _load_json(map_path)
            else:
                embedded_map = area_data.get("map")
                if not isinstance(embedded_map, dict) or not embedded_map:
                    continue
                map_data = embedded_map

            patched_area, patched_map, pair_changes = remediate_area_map_pair(
                area_data,
                map_data,
                force_relayout=force_relayout,
            )

            processed += 1

            # Detect stale embedded map even when coordinates already agree
            if has_external_map and pair_changes == 0:
                original_embedded = area_data.get("map", {})
                if isinstance(original_embedded, dict) and original_embedded.get("rooms") != patched_map.get("rooms"):
                    pair_changes = 1

            if pair_changes > 0:
                changed += 1
                if apply:
                    if has_external_map:
                        patched_area["map"] = patched_map
                    safe_write_json(str(area_path), patched_area)
                    if has_external_map:
                        safe_write_json(str(map_path), patched_map)
        except Exception as exc:
            errors.append(f"{area_path.name}: {exc}")

    return {
        "module": module_path.name,
        "processed": processed,
        "changed": changed,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill spatial contract fields for module area/map files"
    )
    parser.add_argument(
        "--module", type=str, default="", help="Single module slug under modules/"
    )
    parser.add_argument("--apply", action="store_true", help="Write remediated files")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview only (default behavior)"
    )
    parser.add_argument(
        "--force-relayout",
        action="store_true",
        help="Force full coordinate relayout of area and map files",
    )
    args = parser.parse_args()

    modules_root = Path("modules")
    if args.module:
        module_paths = [modules_root / args.module]
    else:
        module_paths = [
            path for path in sorted(modules_root.iterdir()) if path.is_dir()
        ]

    apply_mode = bool(args.apply)
    force_relayout = bool(args.force_relayout)
    results = []
    for module_path in module_paths:
        if not module_path.exists():
            continue
        results.append(remediate_module(module_path, apply=apply_mode, force_relayout=force_relayout))

    total_processed = sum(item["processed"] for item in results)
    total_changed = sum(item["changed"] for item in results)
    total_errors = sum(len(item["errors"]) for item in results)

    mode_label = "apply" if apply_mode else "dry-run"
    print(
        f"SPATIAL_REMEDIATE mode={mode_label} modules={len(results)} processed={total_processed} changed={total_changed} errors={total_errors}"
    )
    for item in results:
        print(
            f"- {item['module']}: processed={item['processed']} changed={item['changed']} errors={len(item['errors'])}"
        )
        for error_text in item["errors"]:
            print(f"  [ERROR] {error_text}")


if __name__ == "__main__":
    main()
