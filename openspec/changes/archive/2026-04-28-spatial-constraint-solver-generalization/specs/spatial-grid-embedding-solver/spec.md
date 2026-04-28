# Spatial Grid Embedding Solver

## Purpose

Provide a generalized constraint-based solver that produces cardinal-adjacent grid embeddings for connected room graphs, replacing the greedy BFS + swap-repair algorithm with a 3-tier fallback chain that always succeeds.

## ADDED Requirements

### Requirement: Constraint-based solver SHALL embed planar graphs on a cardinal grid

The solver SHALL use backtracking with constraint propagation to find a layout where every connected room pair has Manhattan distance exactly 1. It SHALL try roots in descending degree order and SHALL compute candidate cells by intersecting the cardinal neighborhoods of all placed neighbors for multi-connected rooms.

#### Scenario: 5-node bread loaf graph embeds correctly

- GIVEN a 5-node graph with edges G01-G02, G02-G03, G02-G05, G03-G04, G04-G05 (a 4-cycle with one pendant)
- WHEN the constraint solver runs with root G02 (degree 3)
- THEN G02 is placed first at the origin
- AND G01, G03, and G05 are placed in cardinal cells around G02
- AND G04 is placed at the intersection cell (common cardinal neighbor of G03 and G05)
- AND all 5 edges have Manhattan distance exactly 1

#### Scenario: NP003 Numillian Proper graph resolves

- GIVEN the NP003 area with the 5-node bread loaf graph
- AND the current BFS+swap algorithm produces G04(X13Y10) -> G05(X11Y11) with Manhattan 3
- WHEN the constraint solver runs on NP003
- THEN the output coordinates have all 5 edges at Manhattan distance 1
- AND the spatial contract validator reports zero violations

#### Scenario: Star graph embeds correctly

- GIVEN a 5-node graph with one hub connected to all 4 other nodes (max degree 4)
- WHEN the constraint solver runs
- THEN the hub is placed at center
- AND all 4 neighbors occupy the 4 cardinal cells around the hub
- AND all 4 edges are at Manhattan distance 1

### Requirement: Multi-root strategy SHALL try highest-degree nodes first

The solver SHALL sort candidate roots by degree in descending order. It SHALL try the highest-degree node as BFS root first, falling back to lower-degree nodes only if higher-degree placements fail.

#### Scenario: Low-degree root fails, high-degree succeeds

- GIVEN the bread loaf graph where the pendant nodes (G01, G03, G04, G05) all have degree ≤ 2
- AND G02 is the only degree-3 node
- WHEN the solver tries G01 as root first (if sorted by degree, it's low-degree, tried last)
- THEN G02 (highest degree) is tried first
- AND the solver succeeds on the first root attempt (no wasted trials)

### Requirement: Solver SHALL have bounded runtime for up to 20 rooms

The constraint solver SHALL terminate for graphs with up to 20 rooms. If runtime exceeds 100ms or recursion depth exceeds 1000, the solver SHALL abandon Tier 1 and fall back to Tier 2 (cell-expansion).

#### Scenario: 20-room graph terminates within bounds

- GIVEN a 20-node connected planar graph
- WHEN the constraint solver runs
- THEN it produces coordinates OR returns None within 100ms
- AND the 3-tier chain delivers valid coordinates (via Tier 2 or Tier 3 if Tier 1 fails)

### Requirement: Tier 2 cell-expansion SHALL extend the grid when no existing cell satisfies constraints

When the constraint solver fails, the cell-expansion fallback SHALL:
1. Run the old BFS algorithm for initial coordinates
2. Identify connected pairs with Manhattan distance > 1
3. Compute the intersection cardinal cell for each non-adjacent pair
4. Add that cell to the coordinate set if unoccupied
5. Run pairwise swap optimization on the expanded set

#### Scenario: Cell expansion fixes a near-miss layout

- GIVEN a BFS layout where G04-G05 are non-adjacent because no room occupies the needed intersection cell
- AND the constraint solver failed for this root choice
- WHEN Tier 2 cell expansion runs
- THEN the intersection cell for G04 and G05 is added to the grid
- AND swap optimization moves a room into that cell
- AND the edge becomes cardinal-adjacent

### Requirement: Tier 3 linear layout SHALL be a guaranteed fallback for any connected graph

For any connected graph, the linear layout SHALL place all rooms in a single horizontal row in BFS order, producing coordinates `(10+i, 10)` for the i-th room. Every connected pair in the BFS tree SHALL have Manhattan distance 1.

#### Scenario: Linear layout resolves a 6-node chain

- GIVEN a 6-node linear chain: A-B-C-D-E-F
- WHEN Tier 3 linear layout runs
- THEN rooms are placed at (10,10), (11,10), (12,10), (13,10), (14,10), (15,10)
- AND all 5 edges are at Manhattan distance 1

#### Scenario: Linear layout resolves a disconnected graph

- GIVEN a graph with 2 disconnected components of 3 nodes each
- WHEN Tier 3 linear layout runs
- THEN all 6 rooms are placed in one row
- AND all edges within each component are at Manhattan distance 1

### Requirement: Force-relayout flag SHALL remain the activation trigger

The constraint solver SHALL only replace the BFS+swap algorithm when `force_relayout=True` is passed through `remediate_module()`. The non-force-relayout path (existing coordinate refinement) SHALL remain unchanged.

#### Scenario: Non-force-relayout path unchanged

- GIVEN a module with existing valid coordinates
- AND `force_relayout=False` is passed to `remediate_module()`
- WHEN remediation runs
- THEN existing coordinates are refined (not replaced)
- AND the constraint solver is never invoked
