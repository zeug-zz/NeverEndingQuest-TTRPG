## 1. Tier 1 Strengthening

- [x] 1.1 Audit `_solve_grid_embedding` and document current ordering, caps, and failure modes.
- [x] 1.2 Add deterministic room ordering that prioritizes constrained/high-degree rooms and stable room ids.
- [x] 1.3 Add or verify candidate-cell pruning using already placed neighbors and occupied-cell constraints.
- [x] 1.4 Make Tier 1 room/search limits explicit constants with structured `tier1_search_limit` diagnostics.
- [x] 1.5 Ensure Tier 1 returns a result envelope rather than an ambiguous coordinate-or-None value.

## 2. Tier 2 and Tier 3 Contract Correction

- [x] 2.1 Rename or reclassify `_relax_with_expansion` as best-effort unless its output passes full adjacency validation.
- [x] 2.2 Remove any claim that diagonal scatter, cell expansion, or swap repair guarantees success.
- [x] 2.3 Roll back `_build_linear_layout` as a general fallback; keep it only where final validation proves the graph is actually satisfied.
- [x] 2.4 Block publication/reporting success from any tier whose output has unresolved graph edges.

## 3. Diagnostics

- [x] 3.1 Emit unresolved-edge diagnostics with room ids, room names when available, Manhattan distance, and tier source.
- [x] 3.2 Add error classes for `non_cardinal_edge`, `tier1_search_limit`, `fallback_unvalidated`, and `coordinate_overlap`.
- [x] 3.3 Make diagnostics stable and JSON-serializable for downstream remediation/reporting.

## 4. Regression Coverage

- [x] 4.1 Add a bread-loaf fixture that Tier 1 solves and Tier 3 linear layout cannot falsely pass.
- [x] 4.2 Add a cross-edge/cycle fixture proving linear layout reports failure unless full validation passes.
- [x] 4.3 Add a star-degree-4 fixture proving Tier 1 preserves cardinal adjacency around a hub.
- [x] 4.4 Add a search-limit fixture proving bounded failure emits diagnostics instead of false success.
- [x] 4.5 Re-run Numillian publishability/audit checks to prove no regression.

## 5. Verification

- [x] 5.1 Run targeted Python compile checks for changed solver and tests.
- [x] 5.2 Run spatial embedding and coordinate grounding regression tests.
- [x] 5.3 Run Numillian publishability audit and confirm spatial status is based on validator success.
- [x] 5.4 Run `openspec validate spatial-solver-tier-contract-correction`.

## Guidance

This change should not add connector rooms or mutate authored topology. It prepares honest diagnostics for the dependent failsafe change.
