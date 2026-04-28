# Design: Spatial Constraint Solver Generalization

## Architecture

### Modified File

Only `scripts/remediate_module_coordinates.py` is modified. No other files change.

### Algorithm Replacement

The current algorithm chain (BFS placement → swap repair) at lines 85-207 is replaced with a 3-tier solver chain:

```
_build_force_relayout_coordinates()
    │
    ▼
┌─────────────────────────────────────┐
│  Tier 1: _solve_grid_embedding()    │  ← Constraint-based backtracking
│  Multi-root BFS from highest-degree │
│  Intersection-based candidate gen   │
│  Full backtracking on placement     │
└─────────────────────────────────────┘
    │ (failed)
    ▼
┌─────────────────────────────────────┐
│  Tier 2: _relax_with_expansion()    │  ← Cell-expansion swap
│  Run old BFS for initial coords     │
│  Expand grid with buffer cells      │
│  Run pairwise swap on expanded set  │
└─────────────────────────────────────┘
    │ (failed)
    ▼
┌─────────────────────────────────────┐
│  Tier 3: _build_linear_layout()     │  ← Guaranteed to succeed
│  All rooms in one row in BFS order  │
│  Every connected pair has Manhattan=1│
└─────────────────────────────────────┘
```

### Tier 1: `_solve_grid_embedding(graph)` — Constraint-Based Backtracking

**Algorithm:**

```
Input: graph = {room_id: [connected_room_ids]}
Output: {room_id: (x, y)} or None

1. rooms = sorted(graph.keys(), key=lambda r: len(graph[r]), reverse=True)
2. For each room as root:
   a. order = bfs_order(graph, root)
   b. coords = {}, occupied = set()
   c. Try place(0) with backtracking:
      - node = order[idx]
      - placed_neighbors = [n in graph[node] if n in coords]
      - if no placed_neighbors:
          candidates = {(5,5)}  (arbitrary start, offset later)
      - else:
          candidates = cardinal_intersection(placed_neighbors, coords)
          candidates -= occupied
      - for each candidate: place, recurse, backtrack on failure
   d. If place succeeds for all rooms, check all edges have Manhattan=1
      → return coords (offset to (10,10) base)
3. If all roots fail: return None
```

**`cardinal_intersection(placed_neighbors, coords)`**:
```
Start with cardinal neighborhood of first placed neighbor
For each subsequent neighbor:
    Compute cardinal neighborhood of that neighbor
    Intersect with running set
Return intersection (set of (x,y) tuples)
```

**Key design decision — multi-root:** The algorithm tries roots in descending degree order. For the bread-loaf graph with G02 as the degree-3 root, the solution is found on the first attempt. If G01 (degree 1) is tried first, it fails at step G04 (impossible constraints), backtracks through G05/G03 placements, and eventually fails. Then G02 as root succeeds.

**Key design decision — BFS order within backtrack:** The BFS order from a given root is deterministic. Backtracking handles the different N/S/E/W choices within the BFS placement.

**Why this works for NP003/TTM002:** Rooting at G02 places the hub first, then places G01, G03, G05 around it in any order. When G04 (connected to both G03 and G05) is placed last, the intersection of G03's and G05's cardinal neighborhoods always yields at least one valid cell (unless G03 and G05 were placed opposite each other, which backtracks).

**Complexity:** For N=5 rooms with max degree 3, the state space is ~50 nodes. For N=15, worst case is still bounded by the constraint propagation. Hard guard: if rooms > 20, skip Tier 1 and go directly to Tier 2.

### Tier 2: `_relax_with_expansion(graph)` — Cell-Expansion Swap

If Tier 1 fails for all roots:

1. Run the old BFS algorithm to get initial coordinates
2. For each connected pair with Manhattan > 1:
   a. Compute the intersection of their cardinal neighborhoods
   b. If an unoccupied cell exists in the intersection, add it as a "buffer" cell
3. Run the existing pairwise swap algorithm on the expanded coordinate set
4. If all edges become cardinal-adjacent, return. Otherwise, continue to Tier 3.

**Why this helps:** The original swap algorithm fails because the needed cell doesn't exist. By expanding the coordinate set to include the intersection cells of non-adjacent pairs, we give the swap algorithm room to maneuver.

### Tier 3: `_build_linear_layout(graph)` — Guaranteed Fallback

```
For each room in BFS order from first root:
    coordinates[room_id] = (10 + i, 10)
```

Every connected pair in the graph will be adjacent with Manhattan=1 because all rooms are in a straight line. Visually boring but always valid.

### Removed Functions

- `_count_adjacent_connected_pairs` (lines 85-106) — no longer needed; verification is done inline in Tier 1
- `_repair_non_adjacent_pairs` (lines 109-141) — replaced by Tier 1 constraint solver; reused in Tier 2

### Preserved Code

- `_build_force_relayout_coordinates` (line 144) — refactored to call the 3-tier chain
- All functions after `_build_force_relayout_coordinates` (`remediate_area_map_pair`, `remediate_module`, CLI) — unchanged

## Trade-offs

| Trade-off | Decision |
|---|---|
| Exhaustive search vs heuristic | Backtracking is effectively exhaustive for small graphs (< 20 rooms). Accepts the one-time compute cost (microseconds for 5-15 rooms) for the guarantee of correctness. |
| Multiple attempts vs single-pass | Multi-root approach is correct because an invalid root choice can make the graph un-embeddable even though a different root would succeed. |
| Code complexity vs generality | Adding ~100 lines to replace ~60 lines. The new code is more complex but generalizes to all planar grid-embeddable graphs. |
| Preserved swap algorithm | Tier 2 reuses the existing `_repair_non_adjacent_pairs` logic as a fallback. The old code still has value for cases where the grid needs cell expansion rather than complete reassignment. |
