# Spatial Constraint Solver Generalization

## Problem

The current spatial coordinate assignment algorithm in `scripts/remediate_module_coordinates.py` uses a greedy BFS placement followed by a hill-climbing pairwise swap repair (`_repair_non_adjacent_pairs`). This two-pass approach fails on planar grid-embeddable graphs when the BFS placement order produces coordinate sets where the needed cell for a multi-connected room doesn't exist in the coordinate set. The swap algorithm can only reassign existing coordinates — it cannot create new cells.

**Current failure case:** Numillian re-ingest produces two 5-node "bread loaf" graphs (NP003 and TTM002) that the algorithm cannot fully cardinal-embed. Both graphs have a 4-cycle structure (no triangles, max degree 3) that is trivially embeddable on a grid. The BFS places rooms in a linear pattern that forces one edge to be diagonal (Manhattan distance 3), and the swap repair cannot find coordinates at the needed intersection cell because it was never created.

**Root cause:** `_repair_non_adjacent_pairs` (lines 109-141) only swaps room positions between existing occupied cells. When the optimal layout requires a coordinate cell that no room currently occupies, the algorithm has no mechanism to create it. The greedy BFS (lines 164-194) always tries cardinal directions in the fixed order `east → south → west → north` and never backtracks when a placement creates impossible constraints for later rooms.

## Objective

Replace the greedy BFS + swap-repair algorithm with a constraint-based solver that:

1. Places rooms using a backtracking search with proper constraint propagation
2. Computes candidate cells by intersecting the cardinal neighborhoods of all placed neighbors for multi-connected rooms
3. Tries multiple BFS roots (highest-degree nodes first) to find valid embeddings
4. Falls back through a 3-tier chain: constraint solver → cell-expansion relaxation → linear layout

## Non-Goals

- Does NOT change the spatial contract schema or validator
- Does NOT modify `utils/spatial_contract.py` (used by the builder, which has different constraints)
- Does NOT add LLM-assisted spatial reasoning (deterministic Python only)
- Does NOT handle graphs with odd cycles (triangles) — these are geometrically impossible on a grid and require author intervention

## Risks

| Risk | Mitigation |
|---|---|
| Backtracking exponential blow-up for large graphs | Bounded graph size: modules have 3-15 rooms, trivial for constraint solver. Guard: hard limit at 20 rooms, fall back to tier 2/3 above. |
| New algorithm produces different coordinates for existing modules | Only active when `--force-relayout` is True, which is already used by the readiness gate. Non-force-relayout remediation is unchanged. |
| Tier 1 fails on graphs with no valid grid embedding | Tier 2 (cell-expansion) and Tier 3 (linear layout) provide deterministic fallbacks. All connected graphs are guaranteed to produce SOME valid output (linear layout always works). |

## Fallback

- **Tier 1 failure** → cell-expansion relaxation (add empty buffer cells, run swap)
- **Tier 2 failure** → linear chain layout (all rooms in one row, every edge has Manhattan=1)
- **No solution is possible** → the algorithm always succeeds (linear chain is always valid for any connected graph)
