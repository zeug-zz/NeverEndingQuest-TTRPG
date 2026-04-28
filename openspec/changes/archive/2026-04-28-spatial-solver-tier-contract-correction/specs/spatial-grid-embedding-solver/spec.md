# Spatial Grid Embedding Solver

## Purpose

Correct the spatial solver contract so coordinate-only success is based on strict validation, not fallback-tier claims. Tier 1 remains the authoritative solver path; Tier 2 and Tier 3 become best-effort or diagnostic unless their output passes the same full adjacency validator.

## MODIFIED Requirements

### Requirement: Constraint-based solver SHALL embed valid cardinal-grid room graphs

The constraint solver SHALL use deterministic backtracking with constraint propagation to find a layout where every authored connected room pair has Manhattan distance exactly 1 and no two rooms share a coordinate. It SHALL try constrained/high-degree rooms before less constrained rooms using stable tie-breakers.

#### Scenario: 5-node bread loaf graph embeds correctly

- GIVEN a 5-node graph with edges G01-G02, G02-G03, G02-G05, G03-G04, G04-G05
- WHEN the Tier 1 constraint solver runs within its configured budget
- THEN the output coordinates have all 5 authored edges at Manhattan distance 1
- AND no two rooms share a coordinate
- AND the solver result reports `status="success"` and `tier="tier1_constraint_solver"`

#### Scenario: Solver failure is bounded and explicit

- GIVEN a graph that cannot be solved within the configured Tier 1 budget
- WHEN the Tier 1 solver exhausts its budget
- THEN it returns `status="failed"`
- AND it reports an error class such as `tier1_search_limit` or `non_embed_candidate_exhausted`
- AND it does not emit publishable coordinates as success

### Requirement: Solver success SHALL be gated by strict adjacency validation

Every coordinate output from every tier SHALL be validated against the authored room graph before it can be reported as successful or written as a repaired layout. A tier output with any non-cardinal edge SHALL be diagnostics-only.

#### Scenario: Best-effort fallback cannot falsely pass

- GIVEN a fallback tier emits coordinates for a graph
- AND at least one authored edge has Manhattan distance other than 1
- WHEN the solver orchestration evaluates the fallback output
- THEN the final result is failed or diagnostic
- AND the fallback tier is not reported as a successful repair
- AND unresolved edges are included in structured diagnostics

### Requirement: Linear layout SHALL NOT be a guaranteed fallback for arbitrary graphs

The linear layout helper SHALL NOT be described or used as a guaranteed fallback for arbitrary connected graphs. It MAY only report success when the final strict adjacency validator confirms every authored edge is cardinal-adjacent.

#### Scenario: Cross-edge graph rejects false linear success

- GIVEN a connected graph whose authored edges include cross-links not satisfied by a single BFS row
- WHEN the linear layout helper emits a row layout
- THEN the strict validator detects any non-cardinal cross-edge
- AND the helper result remains failed or diagnostic
- AND publication/readiness reporting does not treat the layout as repaired

## ADDED Requirements

### Requirement: Spatial solver diagnostics SHALL identify unresolved authored edges

When coordinate-only embedding fails, the solver SHALL return structured diagnostics identifying unresolved authored edges and failure reasons. Diagnostics SHALL be deterministic and JSON-serializable.

#### Scenario: Failed fallback reports exact edge debt

- GIVEN rooms A and B are connected in authored topology
- AND the proposed coordinates place them more than one Manhattan step apart
- WHEN the fallback output is rejected
- THEN diagnostics include the A-B edge
- AND diagnostics include the computed Manhattan distance
- AND diagnostics include the tier that produced the rejected output
